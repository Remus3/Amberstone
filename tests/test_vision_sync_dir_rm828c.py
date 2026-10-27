"""RM-828 (c) - importing vision_server._config creates no moon_sync_inbox/ in the CWD.

`vision_server/_config.py` built `SYNC_DIR = Path("moon_sync_inbox")` and ran
`SYNC_DIR.mkdir(exist_ok=True)` at IMPORT, so the directory landed wherever the
importing process happened to stand. Under the suite that is the checkout root
(pytest runs from it, and test modules import the server during collection),
so a run created - or in the main checkout reused - the LIVE channel inbox
`<repo>/moon_sync_inbox/`, and tests/test_vision_server_http_hardening.py wrote
its probe files into it and beside it at the repo root.

Now the default is anchored to the repo root (the directory the RM-735 watchdog
already spawns the server in, `dashboard/_vision_watchdog.spawn_vision`
`cwd=app_dir`, so the live inbox does not move), and a non-empty
RC_VISION_SYNC_DIR replaces it - the RM-812 env shape. `tests/conftest.py` sets
that variable at IMPORT, because the module binds SYNC_DIR during collection,
before any fixture runs (the RC_PHASE3_LOG_DIR precedent). The assertions are
POSITIVE (the directory the import made is the tmp one, and the child's CWD got
none), never a stat of the live inbox, which the live inbox tick rewrites
(RM-148).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
LIVE_INBOX = REPO / "moon_sync_inbox"


def _child(code: str, cwd: Path, env: dict) -> list:
    proc = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, r'{REPO}')\n" + code],
        cwd=str(cwd), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120, creationflags=_FLAGS)
    assert proc.returncode == 0, f"child failed rc={proc.returncode}:\n{proc.stderr[-1500:]}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"child printed nothing:\n{proc.stderr[-1500:]}"
    return json.loads(lines[-1])


_PRINT_SYNC_DIR = (
    "import json, logging\n"
    "from vision_server import _config as c\n"
    "logging.shutdown()\n"
    "print(json.dumps([c.SYNC_DIR_ENV, str(c.SYNC_DIR)]))\n"
)


def test_sync_dir_honours_the_env_then_falls_back_to_the_anchored_default(monkeypatch, tmp_path):
    from vision_server import _config as c
    assert c.SYNC_DIR_ENV == "RC_VISION_SYNC_DIR"
    # The default is the repo-root inbox, never a CWD-relative path.
    assert c._SYNC_DIR == LIVE_INBOX
    assert c._SYNC_DIR.is_absolute()
    monkeypatch.setenv(c.SYNC_DIR_ENV, str(tmp_path / "inbox"))
    assert c._sync_target() == tmp_path / "inbox"
    for blank in ("", "   "):
        monkeypatch.setenv(c.SYNC_DIR_ENV, blank)
        assert c._sync_target() == LIVE_INBOX
    monkeypatch.delenv(c.SYNC_DIR_ENV, raising=False)
    assert c._sync_target() == LIVE_INBOX
    # The resolver only names a path; it creates nothing.
    assert not (tmp_path / "inbox").exists()


def test_the_conftest_points_the_sync_dir_at_tmp_at_import():
    value = (os.environ.get("RC_VISION_SYNC_DIR") or "").strip()
    assert value, "tests/conftest.py did not set RC_VISION_SYNC_DIR at import"
    assert not Path(value).resolve().is_relative_to(REPO), value
    from vision_server import _config as c
    from vision_server import _http
    for bound in (c.SYNC_DIR, _http.SYNC_DIR):
        assert Path(bound) == Path(value), bound
        assert not Path(bound).resolve().is_relative_to(REPO), bound
    # Positive: the import-time mkdir landed in tmp.
    assert c.SYNC_DIR.is_dir()


def test_a_child_import_makes_its_inbox_in_the_redirect_not_the_cwd(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    target = tmp_path / "redirect" / "inbox"
    env = dict(os.environ, RC_VISION_SYNC_DIR=str(target))
    env_name, sync_dir = _child(_PRINT_SYNC_DIR, cwd, env)
    assert env_name == "RC_VISION_SYNC_DIR"
    assert Path(sync_dir) == target
    assert target.is_dir(), "the import did not create the redirected inbox"
    assert not (cwd / "moon_sync_inbox").exists(), (
        "the import still created moon_sync_inbox/ in the process CWD")


def test_a_child_with_no_override_never_creates_an_inbox_in_its_cwd(tmp_path):
    """The DEFAULT path, driven in a child whose CWD is not the repo root.

    The child resolves the anchored default; what it must not do is create
    `moon_sync_inbox/` in the directory it stands in, which is what every
    import outside the repo root did before RM-828 (c). `Path.mkdir` is
    recorded, not run, in the child, so this test never creates the repo-root
    inbox itself (in the main checkout that is the live channel inbox).
    """
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "RC_VISION_SYNC_DIR"}
    # The log handler still opens on an anchored file; keep it in tmp.
    env["RC_VISION_SERVER_LOG"] = str(tmp_path / "vision.log")
    code = (
        "import json, logging, pathlib\n"
        "made = []\n"
        "pathlib.Path.mkdir = lambda self, *a, **k: made.append(str(self.resolve()))\n"
        "from vision_server import _config as c\n"
        "logging.shutdown()\n"
        "print(json.dumps([str(c.SYNC_DIR), made]))\n"
    )
    sync_dir, made = _child(code, cwd, env)
    assert Path(sync_dir) == LIVE_INBOX
    assert LIVE_INBOX.resolve() in [Path(p) for p in made], made
    assert not any(Path(p).is_relative_to(cwd.resolve()) for p in made), made
    assert not (cwd / "moon_sync_inbox").exists()
