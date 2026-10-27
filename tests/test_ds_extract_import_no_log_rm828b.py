"""RM-828 (b) - importing a DS extractor opens no log file; its CLI still does.

DEFECT: `tools/daemon_slayer_extract.py` and its sibling
`tools/daemon_slayer_abilities_extract.py` ran `LOG_FILE.parent.mkdir(...)`
and `logging.basicConfig(handlers=[..., logging.FileHandler(LOG_FILE)])` at
MODULE level. The FileHandler is built as a call argument, so it OPENS the
file even when basicConfig then does nothing (pytest has already given the
root logger handlers). A DS-only run (`pytest agents/daemon_slayer/tests`)
imports both (test_abilities_content_freshness.py, test_artifact_patch_
marker_guard.py, test_abilities.py and other abilities tests), and the FileHandler
redirect that keeps those opens in tmp lives only in tests/conftest.py, so a
DS-only run created or appended to the live logs/daemon_slayer_extract.log
and logs/daemon_slayer_abilities_extract.log. Outside pytest the same import
also took over the importer's ROOT logger (stdout + file at INFO).

FIX: the logging setup moved into `_configure_logging()`, called from the
`__main__` block only. Importing the module touches no file; running the
tool still logs to its own file.

Each check runs the tool from a COPY under tmp_path, in a child interpreter,
so the module's `ROOT` (its parent's parent) is tmp and every path it could
create is visible to the test. The child has no pytest handlers on its root
logger, so basicConfig really runs there - which is the import-time
side-effect a plain in-process import would hide. The assertions are
POSITIVE (the CLI's file landed in tmp) plus an exact listing of what the
import created, never a stat of the live logs/ file, which other runs and
tools write too (the RM-148 trap).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# (tool file, log file name its LOG_FILE names)
_TOOLS = (
    ("daemon_slayer_extract.py", "daemon_slayer_extract.log"),
    ("daemon_slayer_abilities_extract.py", "daemon_slayer_abilities_extract.log"),
)
# Repo files a tool READS at import, resolved against its own ROOT, so the
# copy needs them beside it (daemon_slayer_extract `_CANONICAL_ALIAS_PATH`).
_IMPORT_INPUTS = ("web/data/champion_aliases.json",)

# The child imports the COPY by path and reports what the import did to the
# root logger. The real repo goes on sys.path AFTER the copy's own root, so
# `agents.daemon_slayer...` still resolves.
_IMPORT_PROBE = r"""
import importlib.util, json, logging, sys
copy, repo = sys.argv[1], sys.argv[2]
sys.path.append(repo)
spec = importlib.util.spec_from_file_location("_rm828b_probe", copy)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod  # @dataclass looks its module up here
spec.loader.exec_module(mod)
root = logging.getLogger()
print(json.dumps({
    "root_handlers": [type(h).__name__ for h in root.handlers],
    "root_level": root.level,
    "has_configure": callable(getattr(mod, "_configure_logging", None)),
}))
"""


def _stage(tmp_path: Path, tool: str) -> Path:
    for rel in ("tools/" + tool, *_IMPORT_INPUTS):
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, dst)
    return tmp_path / "tools" / tool


def _run(args, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, *args], cwd=str(cwd), env=env, capture_output=True,
        text=True, timeout=180, creationflags=_FLAGS,
    )


def _created(tmp_path: Path, copy: Path) -> list[str]:
    """Every path under tmp_path except the staged copy and inputs."""
    staged = {copy.relative_to(tmp_path).as_posix(), *_IMPORT_INPUTS}
    staged |= {Path(rel).parent.as_posix() for rel in list(staged)}
    staged |= {Path(rel).parent.as_posix() for rel in list(staged)}
    return sorted(
        rel for rel in (p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
        if rel not in staged
    )


@pytest.mark.parametrize("tool,log_name", _TOOLS, ids=[t for t, _ in _TOOLS])
def test_import_creates_no_file_and_leaves_root_logger_alone(tmp_path, tool, log_name):
    copy = _stage(tmp_path, tool)
    work = tmp_path / "cwd"
    work.mkdir()

    proc = _run(["-c", _IMPORT_PROBE, str(copy), str(REPO)], cwd=work)

    assert proc.returncode == 0, proc.stderr[-2000:]
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    # Nothing but the empty cwd exists beside the copy: no logs/ dir, no log.
    assert _created(tmp_path, copy) == ["cwd"], (
        f"importing {tool} created files: {_created(tmp_path, copy)}")
    assert not (tmp_path / "logs" / log_name).exists()
    # The import did not configure the importer's root logger.
    assert report["root_handlers"] == [], report
    assert report["root_level"] == 30, report  # logging.WARNING, untouched
    assert report["has_configure"] is True, report


@pytest.mark.parametrize("tool,log_name", _TOOLS, ids=[t for t, _ in _TOOLS])
def test_cli_still_opens_its_own_log(tmp_path, tool, log_name):
    """POSITIVE: run as a script, the tool logs to its LOG_FILE (here in tmp).

    `--help` makes argparse exit 0 inside main(), after the `__main__` block
    has configured logging and before any network fetch.
    """
    copy = _stage(tmp_path, tool)

    proc = _run([str(copy), "--help"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "usage" in proc.stdout.lower()
    assert (tmp_path / "logs" / log_name).is_file(), _created(tmp_path, copy)
