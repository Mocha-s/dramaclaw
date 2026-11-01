from pathlib import Path

import pytest

from novelvideo.project_context import ProjectContext


def _ctx(tmp_path: Path) -> ProjectContext:
    return ProjectContext(
        project_id="proj_audio_123",
        project_name="demo",
        owner_type="user",
        owner_id="user_owner",
        owner_username="alice",
        requester_user_id="user_editor",
        requester_username="bob",
        requester_principals=(("user", "user_editor"),),
        effective_role="editor",
        home_node_id="node_a",
        output_dir=tmp_path / "output" / "alice" / "demo",
        state_dir=tmp_path / "state" / "alice" / "demo",
        runtime_dir=tmp_path / "runtime" / "alice" / "demo",
        is_home_node=True,
    )


@pytest.mark.asyncio
async def test_audio_separate_runner_returns_public_urls_without_internal_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from novelvideo.task_backend.runners import freezone as freezone_runner

    ctx = _ctx(tmp_path)
    project_dir = Path(ctx.output_dir)
    audio_path = project_dir / "freezone" / "_outputs" / "freezone_audio_separate" / "job.mp3"
    mute_video_path = (
        project_dir / "freezone" / "_outputs" / "freezone_audio_separate" / "job_mute.mp4"
    )
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"audio")
    mute_video_path.write_bytes(b"video")

    class FakeTaskManager:
        def update_progress_for_project(self, *_args, **_kwargs):
            pass

    async def fake_run_freezone_audio_separate(**_kwargs):
        return {"audio_path": audio_path, "mute_video_path": mute_video_path}

    monkeypatch.setattr(freezone_runner, "get_task_manager", lambda: FakeTaskManager())
    monkeypatch.setattr(
        "novelvideo.freezone.jobs.run_freezone_audio_separate",
        fake_run_freezone_audio_separate,
    )

    result = await freezone_runner._run_freezone_audio_separate_async(
        {
            "task_type": "freezone_audio_separate",
            "payload": {
                "job_id": "job",
                "project_dir": str(project_dir),
                "source_path": str(project_dir / "source.mp4"),
            },
        },
        ctx,
    )

    assert "audio_path" not in result
    assert "mute_video_path" not in result
    assert result["audio_url"].startswith("/static/projects/proj_audio_123/")
    assert result["mute_video_url"].startswith("/static/projects/proj_audio_123/")
    assert "/alice/demo/" not in result["audio_url"]
    assert "/alice/demo/" not in result["mute_video_url"]


def test_audio_separate_output_path_prefers_mp3_and_keeps_legacy_m4a(tmp_path: Path) -> None:
    from novelvideo.api.routes import freezone as freezone_routes
    from novelvideo.freezone.paths import outputs_dir

    project_dir = tmp_path / "project"
    output_dir = outputs_dir(project_dir, "freezone_audio_separate")
    output_dir.mkdir(parents=True)

    assert freezone_routes._audio_separate_audio_output_path(project_dir, "new").name == "new.mp3"

    (output_dir / "old.m4a").write_bytes(b"legacy")
    assert freezone_routes._audio_separate_audio_output_path(project_dir, "old").name == "old.m4a"

    (output_dir / "old.mp3").write_bytes(b"audio")
    assert freezone_routes._audio_separate_audio_output_path(project_dir, "old").name == "old.mp3"


@pytest.mark.asyncio
async def test_audio_separate_mute_video_is_written_faststart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """静音视频的 moov 必须在文件头。

    浏览器端会直接播放它，画面裁切/智能续写/深度动作捕捉还会整段 fetch 它。moov 在尾部时
    Chrome 得反复 Range 回跳才能起播，还会把稀疏/截断的缓存条目喂给同一 URL 的 fetch()。
    """
    from novelvideo.freezone import jobs

    commands: list[list[str]] = []

    async def fake_run_cmd(cmd: list[str], **_kwargs) -> None:
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"out")

    async def fake_probe_has_audio(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(jobs.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(jobs, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(jobs, "_probe_has_audio", fake_probe_has_audio)

    result = await jobs.run_freezone_audio_separate(
        project_dir=tmp_path / "project",
        job_id="job",
        source_path=str(tmp_path / "source.mp4"),
    )

    assert result["mute_video_path"] is not None
    assert result["mute_video_path"].name == "job_mute.mp4"
    mute_cmd = commands[-1]
    assert mute_cmd[:2] == ["ffmpeg", "-y"]
    assert "-an" in mute_cmd
    assert "-movflags" in mute_cmd
    assert mute_cmd[mute_cmd.index("-movflags") + 1] == "+faststart"
