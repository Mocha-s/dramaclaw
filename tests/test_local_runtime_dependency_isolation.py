from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Imports made by novelvideo code fail unless they name the standard library,
# Hermes's own pydantic and python-dotenv, or the two packages the image and
# scripts/setup-hermes.sh install for the plugins.
# shortcut: import time only, an import inside a function further down
# novelvideo is never run here; call that function below when one fails.
_HERMES_INTERPRETER = """
import builtins, importlib, sys
available = set(sys.stdlib_module_names) | {
    "novelvideo", "pydantic", "dotenv", "jsonschema", "portalocker"}
missing = []
real_import = builtins.__import__
def hermes_import(name, globals=None, locals=None, fromlist=(), level=0):
    importer = (globals or {}).get("__name__", "")
    if level == 0 and importer.startswith("novelvideo") and name.split(".")[0] not in available:
        missing.append(f"{importer} imports {name}; Hermes's interpreter has no such module")
        raise ModuleNotFoundError(missing[-1])
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = hermes_import
for name in sys.argv[1:]:
    importlib.import_module(name)
# An optional import swallows the error and fails at call time instead, as the bridge did.
sys.exit("\\n".join(missing) or 0)
"""


def test_hermes_plugins_import_only_what_the_hermes_interpreter_has():
    # Plugins run in Hermes's interpreter, not the application's. One import of
    # novelvideo.api from this closure loaded the whole API there, and every
    # canvas write failed at call time with "No module named 'ulid'".
    modules = sorted({
        name
        for path in (ROOT / ".hermes" / "plugins").glob("*/*.py")
        for name in re.findall(
            r"^\s*from (novelvideo[\w.]*) import", path.read_text(encoding="utf-8"), re.M)
    })
    assert "novelvideo.freezone.workflow_preflight" in modules

    completed = subprocess.run(
        [sys.executable, "-c", _HERMES_INTERPRETER, *modules],
        capture_output=True, text=True, timeout=120)

    assert completed.returncode == 0, completed.stderr[-1500:]


def test_images_and_setup_script_give_hermes_the_plugin_requirements():
    install = "grep -E '^(jsonschema|portalocker)=='"

    assert install in (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert install in (ROOT / "scripts" / "setup-hermes.sh").read_text(encoding="utf-8")


def test_pydantic_ai_openai_adapter_imports_with_locked_sdk():
    # Recipe text generation imports this lazily. A Hermes install used to
    # downgrade openai after uv sync, so application startup still succeeded
    # while every generate_text action failed with a generic HTTP 503.
    from pydantic_ai.models.openai import OpenAIChatModel

    assert OpenAIChatModel is not None


def test_local_ce_keeps_hermes_out_of_application_venv():
    start_script = (ROOT / "scripts" / "start-ce.sh").read_text(encoding="utf-8")
    setup_script = (ROOT / "scripts" / "setup-hermes.sh").read_text(encoding="utf-8")

    assert "setup-hermes.sh" not in start_script
    assert "HERMES_ENV_DIR" not in start_script
    assert 'codex_bin="$(bash "$root_dir/scripts/setup-codex.sh")"' in start_script
    assert 'export CODEX_BIN="$codex_bin"' in start_script
    assert (
        'HERMES_PYTHON="${HERMES_PYTHON:-$HERMES_ENV_DIR/bin/python}"' in setup_script
    )
    assert 'uv pip install --python "$HERMES_PYTHON"' in setup_script


def test_source_startup_docs_configure_codex_runtime():
    documented_paths = (
        ROOT / "README.md",
        ROOT / "docs" / "en" / "getting-started" / "installation.md",
        ROOT / "docs" / "zh" / "getting-started" / "installation.md",
    )

    for path in documented_paths:
        content = path.read_text(encoding="utf-8")
        assert "scripts/start-ce.sh" in content
        assert "0.164.0" in content
        assert "SHA256" in content
        assert "CODEX_BIN" in content
        assert "hermes" not in content.lower()


def test_env_example_selects_codex_for_source_development():
    content = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "\nDRAMACLAW_CHAT_BACKEND=codex\n" in content
    assert "HERMES_MODEL=" not in content
