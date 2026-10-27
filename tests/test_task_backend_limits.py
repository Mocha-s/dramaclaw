from novelvideo.task_backend import limits


def test_default_lane_limits_do_not_hide_a_three_task_cap(monkeypatch, tmp_path):
    from novelvideo import runtime_settings

    monkeypatch.setattr(runtime_settings, "runtime_settings_db_path", lambda: tmp_path / "settings.db")
    for name in (
        "ST_PROJECT_MAX_ACTIVE_DEFAULT_TASKS",
        "ST_PROJECT_USER_MAX_ACTIVE_DEFAULT_TASKS",
        "ST_PROJECT_MAX_ACTIVE_VIDEO_TASKS",
        "ST_PROJECT_USER_MAX_ACTIVE_VIDEO_TASKS",
        "ST_CE_GLOBAL_MAX_ACTIVE_VIDEO_TASKS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert limits.project_lane_active_limit("default") == 12
    assert limits.project_user_lane_active_limit("default") == 12
    assert limits.project_lane_effective_active_limit("default", eligible_user_count=1) == 12
    assert limits.project_lane_active_limit("video") == 4
    assert limits.project_user_lane_active_limit("video") == 4
    assert limits.project_lane_effective_active_limit("video", eligible_user_count=1) == 4
    assert limits.global_lane_concurrency("video") == 2
