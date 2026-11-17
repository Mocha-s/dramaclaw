"""Per-user sandbox for multi-user (AIGCDO) Agent workers: #346 P1②."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from novelvideo.security import sandbox_wrap
from novelvideo.security.sandbox_wrap import SandboxSpec, per_user_sandbox_ok, wrap_command


@pytest.fixture
def layout(monkeypatch, tmp_path):
    """Two users' data, the deployment's private state, and a secret in our own environment."""
    from novelvideo import config
    from novelvideo.shared import runtime_env

    monkeypatch.setattr(runtime_env, "load_project_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("SUPERTALE_AUTH_PROVIDER", "aigcdo")
    monkeypatch.setenv("SUPERTALE_ALLOW_UNSANDBOXED", "1")  # must not matter for multi-user
    monkeypatch.setenv("AIGCDO_ENCRYPTION_KEY", "canary-deployment-key")
    monkeypatch.setenv("AIGCDO_STATE_DIR", str(tmp_path / "aigcdo"))
    (tmp_path / "aigcdo").mkdir()
    (tmp_path / "aigcdo" / "sessions.db").write_text("canary-sessions")
    for kind in ("state", "output", "runtime"):
        # The API resolves its roots in config; only the state root is also in the environment,
        # as when an operator sets NOVELVIDEO_DATA_ROOT alone.
        monkeypatch.setattr(config, f"{kind.upper()}_DIR", str(tmp_path / kind))
        monkeypatch.delenv(f"NOVELVIDEO_{kind.upper()}_DIR", raising=False)
        for user in ("alice", "bob"):
            (tmp_path / kind / user / "project").mkdir(parents=True)
            (tmp_path / kind / user / "project" / "data.txt").write_text(f"{user}-{kind}")
    monkeypatch.setenv("NOVELVIDEO_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state" / "local").mkdir()
    (tmp_path / "state" / "local" / "projects.db").write_text("canary-registry")
    home = tmp_path / "state" / "alice" / ".hermes"
    home.mkdir()
    sandbox_wrap._SANDBOX_PROBE_CACHE.clear()
    return tmp_path, home


def test_view_hides_shared_trees_before_showing_only_the_users_slice(layout, monkeypatch):
    root, home = layout
    monkeypatch.setattr(sandbox_wrap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox_wrap.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(sandbox_wrap, "per_user_sandbox_ok", lambda bwrap=None: True)
    argv = wrap_command(["hermes", "acp"], SandboxSpec(user="alice", hermes_home=home))

    assert argv[-2:] == ["hermes", "acp"] and argv[0] == "/usr/bin/bwrap"
    for flag in ("--unshare-user", "--unshare-pid", "--die-with-parent"):
        assert flag in argv
    assert argv[argv.index("--proc") + 1] == "/proc"

    def position(flag, path):
        return next(i for i in range(len(argv) - 1) if argv[i] == flag and argv[i + 1] == str(path))

    for kind in ("state", "output", "runtime"):
        hidden = position("--tmpfs", root / kind)
        assert hidden < position("--ro-bind", root / kind / "alice")
        assert position("--remount-ro", root / kind) > position("--bind", home)
        assert str(root / kind / "bob") not in argv
    # _shared holds every user's replay traces; the checkout holds .git, logs and maybe old data.
    (root / "state" / "_shared").mkdir()
    argv = wrap_command(["hermes", "acp"], SandboxSpec(user="alice", hermes_home=home))
    assert str(root / "state" / "_shared") not in argv
    repo = sandbox_wrap.SUPERTALE_ROOT
    assert position("--tmpfs", repo) < position("--ro-bind", repo / "src")
    assert not any(argv[i] == "--ro-bind" and argv[i + 1] == str(repo) for i in range(len(argv) - 1))
    # A migrated project lives under the old owner's tree: only that project is shown.
    (root / "state" / "local" / "legacy").mkdir(parents=True, exist_ok=True)
    argv = wrap_command(["hermes", "acp"], SandboxSpec(
        user="alice", hermes_home=home, extra_read_paths=[root / "state" / "local" / "legacy"]))
    assert position("--ro-bind", root / "state" / "local" / "legacy") > position("--tmpfs", root / "state")
    assert not any(argv[i] == "--ro-bind" and argv[i + 1] == str(root / "state" / "local")
                   for i in range(len(argv) - 1))
    position("--tmpfs", root / "aigcdo")
    position("--tmpfs", Path.home())
    assert position("--bind", home) > position("--ro-bind", root / "state" / "alice")


@pytest.mark.parametrize("system, bwrap", [("Linux", None), ("Darwin", "/usr/bin/bwrap")])
def test_multi_user_never_falls_back_to_an_unsandboxed_worker(layout, monkeypatch, system, bwrap):
    _, home = layout
    monkeypatch.setattr(sandbox_wrap.platform, "system", lambda: system)
    monkeypatch.setattr(sandbox_wrap.shutil, "which", lambda name: bwrap)
    with pytest.raises(RuntimeError, match="sandbox"):
        wrap_command(["hermes", "acp"], SandboxSpec(user="alice", hermes_home=home))


def test_unusable_bubblewrap_fails_closed(layout, monkeypatch):
    _, home = layout
    monkeypatch.setattr(sandbox_wrap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox_wrap.shutil, "which", lambda name: "/bin/false")
    assert per_user_sandbox_ok("/bin/false") is False
    with pytest.raises(RuntimeError, match="per-user sandbox unavailable"):
        wrap_command(["hermes", "acp"], SandboxSpec(user="alice", hermes_home=home))


_REAL = sys.platform == "linux" and bool(shutil.which("bwrap")) and per_user_sandbox_ok()


@pytest.mark.skipif(not _REAL, reason="needs bubblewrap with unprivileged user namespaces")
def test_a_wrapped_worker_cannot_read_peers_or_deployment_secrets(layout):
    """The acceptance test of #346 P1②: peer reads must fail, not merely be reported."""
    root, home = layout
    script = r"""
import ctypes, os, sys
root = sys.argv[1]
kinds = ("state", "output", "runtime")
libc = ctypes.CDLL(None, use_errno=True)
def unhide():
    for kind in kinds:
        libc.umount2(f"{root}/{kind}".encode(), 2)
unhide()  # the worker holds no capability over its own mount namespace
pid = os.fork()
if pid == 0:
    # A nested user namespace grants capabilities, but only over mounts it cannot unlock.
    if libc.unshare(0x10000000 | 0x00020000) == 0:
        unhide()
    os._exit(1 if any(os.path.exists(f"{root}/{kind}/bob") for kind in kinds) else 0)
escaped = os.waitpid(pid, 0)[1] != 0
def readable(path):
    try:
        with open(path) as handle:
            handle.read()
        return True
    except OSError:
        return False
def writable(path):
    try:
        with open(path, "w") as handle:
            handle.write("x")
        return True
    except OSError:
        return False
leaks = ["a nested namespace revealed peer data"] if escaped else []
for kind in kinds:
    if not readable(f"{root}/{kind}/alice/project/data.txt"):
        leaks.append(f"own {kind} slice is unreadable")
    if os.path.exists(f"{root}/{kind}/bob") or readable(f"{root}/{kind}/bob/project/data.txt"):
        leaks.append(f"peer {kind} slice is visible")
    if sorted(os.listdir(f"{root}/{kind}")) != ["alice"]:
        leaks.append(f"{kind} root lists {os.listdir(f'{root}/{kind}')}")
    if writable(f"{root}/{kind}/alice/project/data.txt") or writable(f"{root}/{kind}/planted"):
        leaks.append(f"{kind} is writable outside the worker home")
if readable(f"{root}/state/local/projects.db"):
    leaks.append("project registry is readable")
if os.listdir(f"{root}/aigcdo"):
    leaks.append("deployment state is visible")
if not writable(f"{root}/state/alice/.hermes/note") or writable("/tmp/planted"):
    leaks.append("write policy is wrong")
for pid in os.listdir("/proc"):
    if pid.isdigit():
        try:
            with open(f"/proc/{pid}/environ", "rb") as handle:
                if b"canary-deployment-key" in handle.read():
                    leaks.append(f"pid {pid} exposes the deployment key")
        except OSError:
            pass
if "AIGCDO_ENCRYPTION_KEY" in os.environ:
    leaks.append("worker environment inherited the deployment key")
print("\n".join(leaks))
sys.exit(1 if leaks else 0)
"""
    # A system interpreter: the venv one may resolve into the (hidden) operator home.
    python = shutil.which("python3", path="/usr/local/bin:/usr/bin:/bin")
    argv = wrap_command(
        [python, "-I", "-c", script, str(root)], SandboxSpec(user="alice", hermes_home=home),
    )
    # The pool passes workers a strict environment; the API's own secrets stay behind.
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=60,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)},
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
    assert (home / "note").read_text() == "x"
    assert not (root / "state" / "planted").exists()
