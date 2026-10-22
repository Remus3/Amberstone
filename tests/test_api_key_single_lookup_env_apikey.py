"""ENV-APIKEY (MAIN ORDER 2026-10-13 1641): ONE Anthropic key lookup.

WHY THIS FILE EXISTS. A Machine-scope ANTHROPIC_API_KEY on this box is
inherited by every process and, for any `claude` started outside the fleet
kit spawn helper, can move billing from the subscription to the API. MAIN
will remove the Machine variable once RC no longer depends on it. Before
this change the readers did NOT share one lookup:

  * `coach_integration/_coach.py`  env ONLY - no key file path at all, so
    removing the Machine variable would switch SR auto-coaching off;
  * `tft/tft_pbe_engine.py`, `tft/tft_coach_engine.py`  their own
    `env or _read_key_file()` copies ("first PRESENT", not first valid);
  * `coaches/tft_pbe_coach.py`, `agents/agent7_context/warm_session.py`
    their own env-then-file copies;
  * `vision_server/_config.py`  its own copy that ALSO read key files in the
    home folder and on the Desktop - outside the repo.

The order (MAIN section 2): (1) process env ANTHROPIC_API_KEY, only if a
launcher set it for that one process; (2) API-Key-Claude.txt at the RC repo
root. `core/anthropic_key.read_anthropic_key` is that one lookup;
`coaches/_base_coach.read_api_key` stays as a thin re-export.

What is pinned here:
  (a) every consumer resolves THROUGH the shared function (a spy on it is
      what each consumer hands onward), and through it: env set -> env;
      env DELETED + key file -> file; both absent -> the consumer's own
      degraded state, nothing raised;
  (b) in a CHILD PROCESS whose environment has the variable DELETED (popped,
      never blanked) every consumer MAIN listed finds the key from a key
      file - the order's acceptance line, run here on a fake key;
  (c) no module other than the shared one reads the variable or locates the
      key file (AST guard; frozen files and two tools allow-listed with
      reasons);
  (d) the child-env strippers for spawned `claude` children still strip it,
      and the shared lookup never re-injects it into os.environ;
  (e) no tracked installer or script persists the variable (install.bat ran
      `setx ANTHROPIC_API_KEY` until s112; it now writes the key file only,
      never echoing the key).

Never touches the real key location: the shared lookup's root is pointed at
`tmp_path` (in-process via monkeypatch, in the child by rebinding the
module attribute inside the child). Every key value here is fake.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _repo_walk

REPO = Path(__file__).resolve().parent.parent
ENV_VAR = "ANTHROPIC_API_KEY"
KEY_FILE = "API-Key-Claude.txt"

# Fake, structurally valid keys - distinct per source so a test can tell
# WHICH source answered.
ENV_KEY = "sk-ant-TESTONLY111env"  # rc-credential-scan: allow-fixture
FILE_KEY = "sk-ant-TESTONLY111file"  # rc-credential-scan: allow-fixture
SENTINEL = "sk-ant-TESTONLY111spy"  # rc-credential-scan: allow-fixture


def _write_key(root: Path, value: str = FILE_KEY) -> Path:
    p = root / KEY_FILE
    p.write_text(value, encoding="utf-8")
    return p


class _Recorder:
    """Stands in for anthropic.Anthropic: records the key, makes no client."""

    def __init__(self, api_key=None, **_kw):
        self.api_key = api_key


class _Handler:
    """Minimal stand-in for the BaseHTTPRequestHandler the routes take."""

    def __init__(self) -> None:
        self.status = 0
        self.body = b""

    def _send(self, status, body, ctype, cache_control=None):
        self.status = status
        self.body = body

    def json(self) -> dict:
        return json.loads(self.body.decode())


@pytest.fixture
def no_sdk(monkeypatch):
    """No real Anthropic client is ever built in this file."""
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _Recorder)
    return anthropic


@pytest.fixture
def key_root(tmp_path, monkeypatch):
    """Point the ONE shared lookup's default root at tmp."""
    from core import anthropic_key
    monkeypatch.setattr(anthropic_key, "_KEY_ROOT", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Consumer adapters: each returns the key string the consumer ends up using.
# `root` is where the key file (if any) lives for this test.
# ---------------------------------------------------------------------------

def _c_shared(root, monkeypatch):
    from core import anthropic_key
    return anthropic_key.read_anthropic_key()


def _c_base_coach_default(root, monkeypatch):
    from coaches._base_coach import read_api_key
    return read_api_key()


def _c_base_coach_app_dir(root, monkeypatch):
    """BaseCoach.__init__ passes its module `_APP_DIR` (the repo root)."""
    from coaches import _base_coach
    monkeypatch.setattr(_base_coach, "_APP_DIR", root)
    return _base_coach.read_api_key(_base_coach._APP_DIR)


def _c_tft_pbe_coach(root, monkeypatch):
    from coaches import tft_pbe_coach
    return tft_pbe_coach._read_api_key()


def _c_warm_session(root, monkeypatch):
    from agents.agent7_context.warm_session import WarmAgent7Session
    return WarmAgent7Session(charter="C")._api_key


def _c_vision_server(root, monkeypatch):
    from vision_server import _config
    return _config._load_key()


def _c_coach_integration(root, monkeypatch):
    import modules.cache_engine as ce
    from coach_integration._coach import CoachIntegration
    monkeypatch.setattr(ce, "CacheEngine", lambda *a, **kw: object())
    ci = CoachIntegration(root / "sr_coaching_data.json")
    return ci._client.api_key if ci._client is not None else ""


def _c_tft_pbe_engine(root, monkeypatch):
    from tft.tft_pbe_engine import TftPbeCoachEngine
    eng = TftPbeCoachEngine(root / "tft_pbe_coaching_data.json")
    return eng._client.api_key if eng._client is not None else ""


def _c_tft_coach_engine(root, monkeypatch):
    from tft.tft_coach_engine import TftCoachEngine
    eng = TftCoachEngine(root / "tft_coaching_data.json")
    return eng._client.api_key if eng._client is not None else ""


def _c_screen_read(root, monkeypatch):
    from dashboard import _screen_read
    reader = _screen_read._build_reader()
    return reader._client.api_key or ""


def _c_routes_coach(root, monkeypatch):
    """The dashboard champ-select route; captures what reached coach_pick."""
    import coaches.champ_select_coach as csc
    from core import champ_select_shadow
    from dashboard import routes_coach

    seen: dict = {}

    def _fake_coach_pick(state, api_key):
        seen["api_key"] = api_key
        return {"ok": True, "advice": "stub"}

    monkeypatch.setattr(csc, "coach_pick", _fake_coach_pick)
    monkeypatch.setattr(champ_select_shadow, "log_champ_select_advice",
                        lambda *a, **kw: None)
    monkeypatch.setattr(routes_coach, "APP_DIR", root)
    h = _Handler()
    routes_coach._serve_champ_select_coach_post(h, {"my_champion": "Ahri"})
    assert h.status == 200, h.body
    return seen["api_key"]


def _c_performance_tracker(root, monkeypatch):
    import coaches.experimental_builder as eb
    import performance_tracker as pt

    seen: dict = {}

    def _capture(champion, grade, gs, api_key):
        seen["api_key"] = api_key
        return {}

    monkeypatch.setattr(eb, "consume_active", lambda: {"champion": "Ahri"})
    monkeypatch.setattr(eb, "record_result", _capture)
    monkeypatch.setattr(pt, "_match_db", None)
    pt.save_rating(str(root), "Ahri", {
        "game_mode": "CLASSIC", "game_seconds": 1200,
        "cs_per_min": 6.0, "deaths": 3, "kills": 5,
        "assists": 7, "gold": 12000, "kda": "5/3/7",
    }, 10)
    return seen["api_key"]


CONSUMERS = [
    pytest.param(_c_shared, id="core.anthropic_key.read_anthropic_key"),
    pytest.param(_c_base_coach_default, id="coaches._base_coach.read_api_key()"),
    pytest.param(_c_base_coach_app_dir, id="coaches._base_coach.read_api_key(_APP_DIR)"),
    pytest.param(_c_tft_pbe_coach, id="coaches.tft_pbe_coach"),
    pytest.param(_c_warm_session, id="agent7.warm_session"),
    pytest.param(_c_vision_server, id="vision_server._config"),
    pytest.param(_c_coach_integration, id="coach_integration._coach"),
    pytest.param(_c_tft_pbe_engine, id="tft.tft_pbe_engine"),
    pytest.param(_c_tft_coach_engine, id="tft.tft_coach_engine"),
    pytest.param(_c_screen_read, id="dashboard._screen_read"),
    pytest.param(_c_routes_coach, id="dashboard.routes_coach"),
    pytest.param(_c_performance_tracker, id="performance_tracker.save_rating"),
]
assert CONSUMERS, "empty consumer set - this file would pass proving nothing"


# ---------------------------------------------------------------------------
# (a) every consumer resolves THROUGH the one shared function.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("load", CONSUMERS)
def test_consumer_resolves_through_the_shared_function(load, key_root,
                                                       monkeypatch, no_sdk):
    """A spy replaces the shared lookup; each consumer must hand on ITS value.

    Holds env and file both absent so a consumer with a private copy would
    answer "" (or its own file), never the spy's value.
    """
    from core import anthropic_key
    calls: list = []

    def _spy(root=None):
        calls.append(root)
        return SENTINEL

    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(anthropic_key, "read_anthropic_key", _spy)
    if load is _c_shared:
        assert anthropic_key.read_anthropic_key() == SENTINEL
        return
    assert load(key_root, monkeypatch) == SENTINEL
    assert calls, "the consumer never called core.anthropic_key"


@pytest.mark.parametrize("load", CONSUMERS)
def test_env_value_wins_when_set(load, key_root, monkeypatch, no_sdk):
    monkeypatch.setenv(ENV_VAR, ENV_KEY)
    _write_key(key_root)
    assert load(key_root, monkeypatch) == ENV_KEY


@pytest.mark.parametrize("load", CONSUMERS)
def test_key_file_is_used_when_env_is_deleted(load, key_root, monkeypatch,
                                              no_sdk):
    monkeypatch.delenv(ENV_VAR, raising=False)
    _write_key(key_root)
    assert load(key_root, monkeypatch) == FILE_KEY


@pytest.mark.parametrize("load", CONSUMERS)
def test_both_absent_degrades_without_raising(load, key_root, monkeypatch,
                                              no_sdk):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert not (key_root / KEY_FILE).exists()
    assert load(key_root, monkeypatch) == ""


def test_both_absent_route_still_answers_200_with_the_disabled_advice(
        key_root, monkeypatch):
    """The champ-select route's degraded state is a 200, not a raw error."""
    import coaches.champ_select_coach as csc
    from core import champ_select_shadow
    from dashboard import routes_coach

    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(routes_coach, "APP_DIR", key_root)
    monkeypatch.setattr(champ_select_shadow, "log_champ_select_advice",
                        lambda *a, **kw: None)
    assert csc.coach_pick is not None
    h = _Handler()
    routes_coach._serve_champ_select_coach_post(h, {"my_champion": "Ahri"})
    assert h.status == 200
    assert "API key missing" in h.json()["advice"]


def test_key_file_value_is_stripped_of_whitespace_newline_and_bom(
        key_root, monkeypatch):
    """A key file saved by Notepad / PowerShell 5.1 carries CRLF and maybe a
    UTF-8 BOM; both must come off, or the SDK sends a header-hostile key."""
    from core import anthropic_key
    monkeypatch.delenv(ENV_VAR, raising=False)
    (key_root / KEY_FILE).write_bytes(
        b"\xef\xbb\xbf  " + FILE_KEY.encode("ascii") + b"\r\n\r\n")
    assert anthropic_key.read_anthropic_key() == FILE_KEY


def test_malformed_env_falls_through_to_the_file(key_root, monkeypatch):
    """env first means first VALID, not first PRESENT (the tft engines used
    `env or file`, so a junk env value shadowed a good file)."""
    from core import anthropic_key
    monkeypatch.setenv(ENV_VAR, "not-a-key")
    _write_key(key_root)
    assert anthropic_key.read_anthropic_key() == FILE_KEY


# ENV-APIKEY residual (4), verifier nit: with NO key file, an unusable env
# value used to come back as-is (`return env`), so a junk or whitespace-only
# variable reached the SDK as a truthy "key" and failed at request time
# instead of degrading to the no-coaching state. Unusable = what
# `usable_key` rejects: no sk-ant- prefix, whitespace, internal space,
# non-ASCII.
_UNUSABLE_ENV = (
    pytest.param("not-a-key", id="junk"),
    pytest.param("   ", id="whitespace-only"),
    pytest.param("sk-ant-aaa bbb", id="internal-space"),
    pytest.param("sk-ant-TESTONLY" + chr(0xE9) + "x", id="non-ascii"),  # rc-credential-scan: allow-fixture
)


@pytest.mark.parametrize("value", _UNUSABLE_ENV)
def test_unusable_env_with_no_key_file_degrades_to_empty(value, key_root,
                                                         monkeypatch):
    from core import anthropic_key
    monkeypatch.setenv(ENV_VAR, value)
    assert not (key_root / KEY_FILE).exists()
    assert anthropic_key.read_anthropic_key() == ""


@pytest.mark.parametrize("load", CONSUMERS)
def test_junk_env_with_no_key_file_degrades_every_consumer(load, key_root,
                                                           monkeypatch, no_sdk):
    """Same degraded state as both-absent, for every consumer."""
    monkeypatch.setenv(ENV_VAR, "not-a-key")
    assert not (key_root / KEY_FILE).exists()
    assert load(key_root, monkeypatch) == ""


def test_unreadable_key_file_degrades_instead_of_raising(key_root,
                                                         monkeypatch):
    from core import anthropic_key
    monkeypatch.delenv(ENV_VAR, raising=False)
    (key_root / KEY_FILE).write_bytes(b"\xff\xfe\x00bad")
    assert anthropic_key.read_anthropic_key() == ""


def test_key_file_with_an_internal_space_is_rejected(key_root, monkeypatch):
    from core import anthropic_key
    monkeypatch.delenv(ENV_VAR, raising=False)
    _write_key(key_root, "sk-ant-aaa bbb")
    assert anthropic_key.read_anthropic_key() == ""


def test_default_root_is_the_repo_root_derived_from_the_module_path():
    from core import anthropic_key
    assert anthropic_key.REPO_ROOT == Path(anthropic_key.__file__).resolve().parent.parent
    assert anthropic_key.REPO_ROOT == REPO
    assert anthropic_key.KEY_FILENAME == KEY_FILE
    assert anthropic_key.ENV_VAR == ENV_VAR


def test_suite_never_resolves_against_the_real_repo_root():
    """tests/conftest.py redirects the shared root for every test, so once
    the real key file exists no test can pick it up by default."""
    from core import anthropic_key
    root = Path(anthropic_key._KEY_ROOT).resolve()
    assert root != REPO
    assert REPO not in root.parents


def test_vision_server_no_longer_reads_home_or_desktop(tmp_path, key_root,
                                                      monkeypatch):
    """Only the repo-root key file counts: key files in the home folder or
    on the Desktop (outside the repo) are never read."""
    from vision_server import _config
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    (home / KEY_FILE).write_text(FILE_KEY, encoding="utf-8")
    (home / "Desktop" / KEY_FILE).write_text(FILE_KEY, encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert _config._load_key() == ""


# ---------------------------------------------------------------------------
# (b) child process with the variable DELETED from its environment.
# ---------------------------------------------------------------------------

_CHILD = r'''
import ast, json, os, sys
from pathlib import Path

repo, root = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo))
want = (root / "API-Key-Claude.txt").read_text(encoding="utf-8").strip()
out = {"env_absent_at_start": "ANTHROPIC_API_KEY" not in os.environ}


class _Rec:
    def __init__(self, api_key=None, **kw):
        self.api_key = api_key


import anthropic
anthropic.Anthropic = _Rec

from core import anthropic_key
anthropic_key._KEY_ROOT = root


def run(name, fn):
    try:
        out[name] = fn() == want
    except Exception as exc:
        out[name] = "raised " + type(exc).__name__


class _H:
    status = 0
    def _send(self, status, body, ctype, cache_control=None):
        self.status = status


def _routes():
    import coaches.champ_select_coach as csc
    from core import champ_select_shadow
    from dashboard import routes_coach
    seen = {}

    def _pick(state, api_key):
        seen["k"] = api_key
        return {"ok": True, "advice": "stub"}

    csc.coach_pick = _pick
    champ_select_shadow.log_champ_select_advice = lambda *a, **k: None
    routes_coach.APP_DIR = root
    h = _H()
    routes_coach._serve_champ_select_coach_post(h, {"my_champion": "Ahri"})
    return seen.get("k")


def _coach_integration():
    import modules.cache_engine as ce
    ce.CacheEngine = lambda *a, **k: object()
    from coach_integration._coach import CoachIntegration
    return CoachIntegration(root / "sr.json")._client.api_key


def _base_coach_app_dir():
    from coaches import _base_coach
    _base_coach._APP_DIR = root
    return _base_coach.read_api_key(_base_coach._APP_DIR)


def _game_lifecycle():
    from app import _game_lifecycle as glc
    glc.SCRIPT_DIR = root
    return object.__new__(glc.GameLifecycleManager).try_read_api_key()


def _vision():
    from vision_server import _config
    assert _config.api_key_present()
    assert _config._API_KEY == want
    return _config._load_key()


def _main_py():
    src = (repo / "main.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "_load_api_key")
    mod = ast.Module(body=[fn], type_ignores=[])

    class _Log:
        def info(self, *a, **k): pass
        def error(self, *a, **k): pass

    ns = {"os": os, "APP_DIR": root, "_log": _Log()}
    exec(compile(mod, "main.py:_load_api_key", "exec"), ns)
    return ns["_load_api_key"]()


run("core.anthropic_key", lambda: anthropic_key.read_anthropic_key())
run("coaches._base_coach.read_api_key", lambda: __import__(
    "coaches._base_coach", fromlist=["x"]).read_api_key())
run("coaches._base_coach BaseCoach(_APP_DIR)", _base_coach_app_dir)
run("coaches.tft_pbe_coach", lambda: __import__(
    "coaches.tft_pbe_coach", fromlist=["x"])._read_api_key())
run("coach_integration._coach", _coach_integration)
run("vision_server._config", _vision)
run("tft.tft_pbe_engine", lambda: __import__(
    "tft.tft_pbe_engine", fromlist=["x"]).TftPbeCoachEngine(
        root / "p.json")._client.api_key)
run("tft.tft_coach_engine", lambda: __import__(
    "tft.tft_coach_engine", fromlist=["x"]).TftCoachEngine(
        root / "t.json")._client.api_key)
run("agents.agent7_context.warm_session", lambda: __import__(
    "agents.agent7_context.warm_session", fromlist=["x"]).WarmAgent7Session(
        charter="C")._api_key)
run("dashboard.routes_coach champ-select", _routes)
run("dashboard._screen_read", lambda: __import__(
    "dashboard._screen_read", fromlist=["x"])._build_reader()._client.api_key)
run("app._game_lifecycle (FROZEN)", _game_lifecycle)
out["env_still_absent_before_main"] = "ANTHROPIC_API_KEY" not in os.environ
run("main.py _load_api_key (FROZEN)", _main_py)
print("RESULT " + json.dumps(out, sort_keys=True))
'''

CHILD_CONSUMERS = (
    "core.anthropic_key",
    "coaches._base_coach.read_api_key",
    "coaches._base_coach BaseCoach(_APP_DIR)",
    "coaches.tft_pbe_coach",
    "coach_integration._coach",
    "vision_server._config",
    "tft.tft_pbe_engine",
    "tft.tft_coach_engine",
    "agents.agent7_context.warm_session",
    "dashboard.routes_coach champ-select",
    "dashboard._screen_read",
    "app._game_lifecycle (FROZEN)",
    "main.py _load_api_key (FROZEN)",
)


def test_every_consumer_finds_the_key_file_in_a_child_with_the_variable_deleted(
        tmp_path):
    root = tmp_path / "rc_root"
    root.mkdir()
    _write_key(root)
    script = tmp_path / "child_probe.py"
    script.write_text(_CHILD, encoding="utf-8")

    env = dict(os.environ)
    env.pop(ENV_VAR, None)          # DELETED, never set to ""
    # A bool local, never the mapping: a failing assert must not render the
    # environment (tests/test_no_environ_in_assert_operands.py).
    still_set = ENV_VAR in env
    assert not still_set
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    proc = subprocess.run(
        [sys.executable, str(script), str(REPO), str(root)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, creationflags=flags)
    assert FILE_KEY not in proc.stdout and FILE_KEY not in proc.stderr, (
        "a consumer printed or logged the key value")
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert proc.returncode == 0 and lines, (
        f"child failed rc={proc.returncode}\n{proc.stderr[-3000:]}")
    out = json.loads(lines[-1][len("RESULT "):])
    assert out.pop("env_absent_at_start") is True
    assert out.pop("env_still_absent_before_main") is True, (
        "a consumer re-injected ANTHROPIC_API_KEY into os.environ")
    assert sorted(out) == sorted(CHILD_CONSUMERS)
    failed = {k: v for k, v in out.items() if v is not True}
    assert not failed, f"consumers that did not find the key file: {failed}"


# ---------------------------------------------------------------------------
# (c) no module but the shared one reads the variable or locates the file.
# ---------------------------------------------------------------------------

SHARED = "core/anthropic_key.py"

# rel path -> reason. Each entry must still carry a read (stale entries red).
ALLOWED = {
    "main.py": "FROZEN entry point; env first then the repo-root key file "
               "(confirmed s112), re-exports the key into its own process env",
    "app/_game_lifecycle.py": "FROZEN; _try_read_api_key is env first then "
                              "SCRIPT_DIR key file (confirmed s112)",
    "tools/bootstrap_env_check.py": "install diagnostic: validates the key "
                                    "FILE's prefix, never resolves a key for "
                                    "a client",
    "tools/build_portable.py": "packaging: locates the key file in a BUILD "
                               "OUTPUT to prove the secret is absent, never "
                               "reads it",
}

# This guard's own scope: tests write fake key files and set the variable on
# purpose; docs quote code; the fleet kit is vendored byte-for-byte and only
# ever strips the variable (changes arrive as a MAIN kit version).
_SCOPE_SKIP_TOP = {"tests", "docs"}
_SCOPE_SKIP_PREFIX = ("ops/fleet_kit/",)


def _str_const(node, aliases) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and (
        node.value in aliases)


def _aliases(tree, value_ok) -> set:
    names = set()
    for n in ast.walk(tree):
        targets, value = [], None
        if isinstance(n, ast.Assign):
            targets, value = n.targets, n.value
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            targets, value = [n.target], n.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str) \
                and value_ok(value.value):
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


def _is_environ(node) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "environ") or (
        isinstance(node, ast.Name) and node.id == "environ")


def _is_key_file(node, file_aliases) -> bool:
    if isinstance(node, ast.Name):
        return node.id in file_aliases
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and (
        node.value.lower().replace("\\", "/").rsplit("/", 1)[-1]
        == KEY_FILE.lower())


def find_key_reads(source: str) -> list:
    """(lineno, kind) for every env-var READ and every key-file LOCATION.

    A read = os.environ.get / os.getenv / os.environ[...] in Load context.
    Pops, deletes, stores and `in` checks are stripping, not reading.
    A location = `<path> / "API-Key-Claude.txt"`, `Path(...)` /
    `os.path.join(...)` / `open(...)` with that name.
    """
    tree = ast.parse(source)
    env_names = {ENV_VAR} | _aliases(tree, lambda v: v == ENV_VAR)
    file_names = _aliases(tree, lambda v: v.lower() == KEY_FILE.lower())
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f, args = n.func, n.args
            fname = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else "")
            if fname == "get" and isinstance(f, ast.Attribute) and \
                    _is_environ(f.value) and args and _str_const(args[0], env_names):
                hits.append((n.lineno, "env-read"))
            elif fname == "getenv" and args and _str_const(args[0], env_names):
                hits.append((n.lineno, "env-read"))
            elif fname in {"join", "Path", "open", "PurePath", "WindowsPath"} and \
                    any(_is_key_file(a, file_names) for a in args):
                hits.append((n.lineno, "key-file"))
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and \
                _is_environ(n.value) and _str_const(n.slice, env_names):
            hits.append((n.lineno, "env-read"))
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) and \
                _is_key_file(n.right, file_names):
            hits.append((n.lineno, "key-file"))
    return sorted(set(hits))


def _in_scope(rel: str) -> bool:
    parts = rel.split("/")
    if parts[0] in _SCOPE_SKIP_TOP or rel.startswith(_SCOPE_SKIP_PREFIX):
        return False
    name = parts[-1]
    return not (name.startswith("test_") or name == "conftest.py")


def _scan() -> dict:
    found = {}
    for p in _repo_walk.iter_repo_files(REPO, ("*.py",)):
        rel = _repo_walk.relative_posix(p, REPO)
        if not _in_scope(rel):
            continue
        try:
            src = p.read_text(encoding="utf-8")
            hits = find_key_reads(src)
        except (UnicodeDecodeError, SyntaxError):
            continue
        if hits:
            found[rel] = hits
    return found


def test_detector_is_not_vacuous():
    """Every shape the old private copies used must be detected."""
    src = (
        'import os\nfrom pathlib import Path\n'
        'a = os.environ.get("ANTHROPIC_API_KEY", "")\n'
        'b = __import__("os").environ.get("ANTHROPIC_API_KEY", "")\n'
        'c = os.getenv("ANTHROPIC_API_KEY")\n'
        'd = os.environ["ANTHROPIC_API_KEY"]\n'
        'V = "ANTHROPIC_API_KEY"\ne = os.environ.get(V)\n'
        'f = Path(__file__).parent / "API-Key-Claude.txt"\n'
        'g = Path.home() / "Desktop" / "API-Key-Claude.txt"\n'
        'h = os.path.join("x", "API-Key-Claude.txt")\n'
        # stripping, never reading:
        'env = dict(os.environ)\nenv.pop("ANTHROPIC_API_KEY", None)\n'
        'del env["ANTHROPIC_API_KEY"]\nok = "ANTHROPIC_API_KEY" not in env\n'
        'os.environ["ANTHROPIC_API_KEY"] = "x"\n'
        'EXCLUDE = ("API-Key-Claude.txt",)\n'
    )
    kinds = find_key_reads(src)
    assert [k for k in kinds if k[1] == "env-read"] == [
        (3, "env-read"), (4, "env-read"), (5, "env-read"), (6, "env-read"),
        (8, "env-read")]
    assert [k for k in kinds if k[1] == "key-file"] == [
        (9, "key-file"), (10, "key-file"), (11, "key-file")]


def test_only_the_shared_module_reads_the_key():
    _repo_walk.self_check(REPO)
    found = _scan()
    assert SHARED in found, (
        f"{SHARED} not reached or reads nothing - the scan is vacuous")
    kinds = {k for _ln, k in found[SHARED]}
    assert kinds == {"env-read", "key-file"}, found[SHARED]
    offenders = {rel: hits for rel, hits in found.items()
                 if rel != SHARED and rel not in ALLOWED}
    assert not offenders, (
        "these modules read ANTHROPIC_API_KEY or locate API-Key-Claude.txt "
        "themselves; route them through core.anthropic_key.read_anthropic_key:"
        f"\n{json.dumps(offenders, indent=1)}")


def test_allow_list_is_not_stale():
    found = _scan()
    stale = sorted(rel for rel in ALLOWED if rel not in found)
    assert not stale, f"allow-listed but no longer reading - remove: {stale}"


# ---------------------------------------------------------------------------
# (d) spawned `claude` children still never get the variable.
# ---------------------------------------------------------------------------

def _parent_env() -> dict:
    return {"PATH": os.environ.get("PATH", ""), ENV_VAR: "sk-ant-TESTONLY111parent"}  # rc-credential-scan: allow-fixture


def test_fleet_kit_child_env_still_strips_the_variable():
    from ops.loop import fleet_route
    k = fleet_route.kit()
    child = k.child_env("http://127.0.0.1:1", bare=False, parent=_parent_env())
    still_set = ENV_VAR in child
    assert not still_set


def test_rc_child_env_strippers_still_strip_the_variable():
    from tools import inbox_responder_exec as rexec
    from tools import inbox_responder_spawn as rspawn
    assert ENV_VAR not in rspawn.child_env(_parent_env())
    assert ENV_VAR not in rexec.measure_env(_parent_env())


@pytest.mark.parametrize("rel", ["ops/loop/run_lane.ps1",
                                 "ops/loop/launch_queue_loop.ps1"])
def test_powershell_lane_launchers_still_null_the_variable(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert "$env:ANTHROPIC_API_KEY = $null" in text


def test_shared_lookup_never_writes_the_environment(key_root, monkeypatch):
    """Resolving from the file must not re-inject the key into os.environ,
    or every child the process spawns would inherit it again."""
    from core import anthropic_key
    monkeypatch.delenv(ENV_VAR, raising=False)
    _write_key(key_root)
    assert anthropic_key.read_anthropic_key() == FILE_KEY
    reinjected = os.getenv(ENV_VAR)
    assert reinjected is None
    tree = ast.parse((REPO / SHARED).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and not isinstance(n.ctx, ast.Load):
            assert not _is_environ(n.value), "shared lookup writes os.environ"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            assert n.func.attr not in {"putenv", "setdefault", "update"} or \
                not _is_environ(n.func.value), "shared lookup writes os.environ"


# ---------------------------------------------------------------------------
# (e) no installer or script persists the variable to the user / machine env.
# ---------------------------------------------------------------------------

_PERSIST = re.compile(
    r"setx\s+(?:/m\s+)?ANTHROPIC_API_KEY"
    r"|SetEnvironmentVariable\(\s*['\"]ANTHROPIC_API_KEY"
    r"|reg(?:\.exe)?\s+add\s+\S*Environment\S*.*ANTHROPIC_API_KEY",
    re.IGNORECASE)


def test_no_tracked_script_persists_the_key_variable():
    this_file = Path(__file__).resolve()
    scanned, offenders = 0, []
    for path in _repo_walk.repo_files(
            REPO, ("*.py", "*.ps1", "*.psm1", "*.bat", "*.cmd")):
        # This guard names its own needles, so it must not scan itself.
        if path.resolve() == this_file:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        if _PERSIST.search(text):
            offenders.append(_repo_walk.relative_posix(path, REPO))
    assert scanned > 100, "enumeration collapsed - this guard would pass vacuously"
    assert any(_repo_walk.relative_posix(p, REPO) == "install.bat"
               for p in _repo_walk.repo_files(REPO, ("*.bat",))), (
        "install.bat not reached - the scan proves nothing about it")
    assert not offenders, f"persists ANTHROPIC_API_KEY: {offenders}"


def test_install_bat_writes_the_key_file_and_never_echoes_the_key():
    text = (REPO / "install.bat").read_text(encoding="ascii")
    assert not re.search(r"setx\s+ANTHROPIC_API_KEY", text, re.IGNORECASE)
    # One line, no padding, staged in a private temp file, written IN PLACE
    # (keeps a restricted ACL on the key file), skipped when unchanged.
    assert '>"%KEY_TMP%" echo(!API_KEY!' in text
    assert 'fc /b "%KEY_TMP%" "%API_FILE%"' in text
    assert 'type "%KEY_TMP%" > "%API_FILE%"' in text
    assert "set KEY_TMP=%TEMP%\\" in text
    code = [ln for ln in text.splitlines()
            if not ln.lstrip().lower().startswith(("::", "rem "))]
    assert not any(re.search(r"\bmove\b.*%API_FILE%", ln, re.IGNORECASE)
                   for ln in code), "a move over the key file drops its ACL"
    assert "(gitignored)" in text.replace("^(", "(").replace("^)", ")")
    # The only line that expands the key next to an echo writes the temp file.
    for n, line in enumerate(text.splitlines(), 1):
        if re.search(r"%API_KEY%|!API_KEY!", line) and re.search(
                r"\becho\b", line, re.IGNORECASE):
            assert line.strip().startswith('>"%KEY_TMP%"'), (
                f"install.bat:{n} echoes the key: {line.strip()!r}")


# ENV-APIKEY residual (4), verifier nit: install.bat step 3 rejected a key
# file saved as UTF-8 WITH BOM (Notepad, PowerShell 5.1 -Encoding UTF8):
# `set /p` keeps the EF BB BF bytes, so the sk-ant- prefix check failed on a
# good key. Measured on cmd.exe (code page 437): the first seven characters
# of the read value were the three BOM bytes plus "sk-a". This runs the REAL
# step-3 block (cut from install.bat between its STEP 3 and STEP 4 headers)
# in a harness that sets what steps 1-2 would have set; notepad is stubbed
# out and TEMP points at tmp_path.

def _step3_harness(tmp_path: Path, option_b: bool) -> Path:
    lines = (REPO / "install.bat").read_text(encoding="ascii").splitlines()
    start = next(i for i, ln in enumerate(lines) if "STEP 3 -- API Key" in ln)
    end = next(i for i, ln in enumerate(lines) if "STEP 4 --" in ln)
    block = ["rem notepad stubbed" if ln.strip().lower().startswith("notepad ")
             else ln for ln in lines[start:end]]
    head = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        "set OPTION_B=" + ("1" if option_b else "0"),
        'set "EMBED_PY=' + sys.executable + '"',
        "set LOG_FILE=%~dp0setup.log",
        "set ERRORS=0",
    ]
    tail = [
        '>"%~dp0key.out" echo(!API_KEY!',
        "echo STEP3=PASS",
        "goto :EOF",
        ":SUMMARY",
        "echo STEP3=FAIL",
    ]
    bat = tmp_path / "step3_harness.bat"
    bat.write_bytes(("\r\n".join(head + block + tail) + "\r\n").encode("ascii"))
    return bat


def _run_step3(tmp_path: Path, raw: bytes, option_b: bool) -> tuple[str, str]:
    (tmp_path / KEY_FILE).write_bytes(raw)
    temp = tmp_path / "temp"
    temp.mkdir()
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp))
    env.pop(ENV_VAR, None)
    # Option A runs `python` from PATH; put this interpreter first on it.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    bat = _step3_harness(tmp_path, option_b)
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(bat)], cwd=str(tmp_path), env=env,
        capture_output=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = proc.stdout.decode("ascii", "replace")
    key_out = tmp_path / "key.out"
    got = key_out.read_bytes().decode("latin-1").strip() if key_out.exists() else ""
    assert list(temp.iterdir()) == [], "step 3 left a temp file behind"
    return out, got


_BOM = b"\xef\xbb\xbf"


@pytest.mark.skipif(sys.platform != "win32", reason="runs install.bat under cmd.exe")
@pytest.mark.parametrize("option_b", [True, False], ids=["embedded", "path-python"])
@pytest.mark.parametrize("raw", [
    pytest.param(_BOM + FILE_KEY.encode("ascii") + b"\r\n", id="bom-crlf"),
    pytest.param(_BOM + FILE_KEY.encode("ascii"), id="bom-no-newline"),
    pytest.param(FILE_KEY.encode("ascii") + b"\r\n", id="plain-crlf"),
])
def test_install_bat_step3_accepts_a_good_key_with_or_without_a_bom(
        tmp_path, raw, option_b):
    out, got = _run_step3(tmp_path, raw, option_b)
    assert "STEP3=PASS" in out
    assert got == FILE_KEY


@pytest.mark.skipif(sys.platform != "win32", reason="runs install.bat under cmd.exe")
@pytest.mark.parametrize("raw", [
    pytest.param(_BOM + b"not-a-key\r\n", id="bom-junk"),
    pytest.param(b"not-a-key\r\n", id="junk"),
])
def test_install_bat_step3_still_rejects_a_bad_key(tmp_path, raw):
    out, _ = _run_step3(tmp_path, raw, option_b=True)
    assert "STEP3=FAIL" in out
    assert "STEP3=PASS" not in out


# ---------------------------------------------------------------------------
# (f) COLLECTION never resolves the real key file. vision_server/_config.py
# resolves the key at IMPORT time and ~10 test modules import vision_server
# at module top, so the lookup runs during collection - before any
# function-scoped fixture. The redirect must already be in place then, for
# BOTH suite roots.
# ---------------------------------------------------------------------------

_SPY_PLUGIN = r'''
import os
from pathlib import Path

from core import anthropic_key as _ak

_OUT = Path(os.environ["RC_KEYSPY_OUT"])
_orig = _ak.key_file_path


def _record(line):
    with _OUT.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _spy(root=None):
    p = _orig(root)
    _record("PATH " + str(Path(p).resolve()))
    return p


_ak.key_file_path = _spy


def pytest_collection_finish(session):
    _record("ROOT " + str(Path(_ak._KEY_ROOT).resolve()))
'''

# Module-level: what the shared root is while THIS module is being collected.
from core import anthropic_key as _ak_at_collection  # noqa: E402

_KEY_ROOT_AT_COLLECTION = Path(_ak_at_collection._KEY_ROOT).resolve()


def test_key_root_is_already_redirected_while_this_module_is_collected():
    assert _KEY_ROOT_AT_COLLECTION != REPO
    assert REPO not in _KEY_ROOT_AT_COLLECTION.parents


def _under_repo(p: Path) -> bool:
    return p == REPO or REPO in p.parents


@pytest.mark.parametrize("target,expect_paths", [
    ("tests/test_vision_server_bind_rm150.py", True),
    ("agents/daemon_slayer/tests/test_boot_utility.py", False),
])
def test_collection_never_resolves_the_real_key_file(tmp_path, target,
                                                     expect_paths):
    assert (REPO / target).is_file(), target
    (tmp_path / "rc_keyspy.py").write_text(_SPY_PLUGIN, encoding="ascii")
    out = tmp_path / "resolved.txt"
    env = dict(os.environ)
    env.pop(ENV_VAR, None)          # DELETED, never set to ""
    for k in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_CURRENT_TEST",
              "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT",
              "PYTEST_XDIST_TESTRUNUID"):
        env.pop(k, None)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(tmp_path), env.get("PYTHONPATH", "")) if p)
    env["RC_KEYSPY_OUT"] = str(out)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", "-p", "rc_keyspy", target],
        cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300, creationflags=flags)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    lines = out.read_text(encoding="utf-8").splitlines() if out.exists() else []
    paths = [Path(ln[5:]) for ln in lines if ln.startswith("PATH ")]
    roots = [Path(ln[5:]) for ln in lines if ln.startswith("ROOT ")]
    assert roots, "the spy plugin never ran - this test would pass vacuously"
    if expect_paths:
        assert paths, ("collecting a vision_server importer resolved no key "
                       "path - the probe no longer exercises the import-time read")
    leaks = sorted({str(p) for p in paths if _under_repo(p)})
    assert not leaks, f"collection resolved the real key file: {leaks}"
    assert not any(_under_repo(r) for r in roots), (
        f"key root still inside the repo after collection: {roots}")
