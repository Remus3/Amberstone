"""Anthropic API key LOAD ORDER - env first, API-Key-Claude.txt second.

WHY THIS FILE EXISTS (measured 2026-09-29). The key had two homes: the
machine-wide `ANTHROPIC_API_KEY` env var and the gitignored repo-root file
`API-Key-Claude.txt`. The operator rotated the key into the env and deleted
the file. Seven consumers read the key and they did NOT agree on precedence:

  * `main.py:46`                      env first, file fallback  (correct)
  * `coach_integration/_coach.py:50`  env only                  (correct)
  * `coaches/_base_coach.py`          FILE first                (flipped here)
  * `agents/agent7_context/warm_session.py`  FILE first         (flipped here)
  * `coaches/tft_pbe_coach.py`        FILE first                (flipped here)
  * `app/_game_lifecycle.py:315`      FILE first  (FROZEN - flipped 2026-09-29
                                      under an explicit, edit-scoped operator
                                      approval; it was the last file-first read)
  * `dashboard/routes_coach.py:185`   FILE ONLY - a LIVE BUG

TWO DEFECTS, and they are different in kind:

1. `routes_coach` had no env path AT ALL, so with the file deleted it passed
   `api_key = ""` into `coach_pick` and champ-select coaching was silently
   off while a perfectly good key sat in the environment. That is the one
   strictly-required fix, and `test_routes_coach_reads_the_environment` is
   the test that FAILED before it.

2. File-first ordering is a latent stale-wins trap. With no file present it
   is harmless - everything falls through to env. But recreate the file with
   a revoked key and the file-first consumers silently prefer the dead
   credential, so a future rotation LOOKS successful while half the process
   keeps using the revoked one. That is exactly the failure that cost this
   session's debugging, which is why the ordering is pinned by test rather
   than left to convention.

Four properties are asserted for every in-scope consumer:
  * env WINS when both sources are present and hold different keys,
  * the file is used when env is absent,
  * a MALFORMED env value does not shadow a good file value,
  * "" is RETURNED, not raised, when neither source exists.

Never touches the real key location: every consumer is pointed at `tmp_path`
and the env var is set through `monkeypatch`. Key values here are fake.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ENV_VAR = "ANTHROPIC_API_KEY"

# Fake, structurally-valid keys. Distinct per source so a test can tell
# WHICH source answered, which "both are present" cannot do otherwise.
ENV_KEY = "sk-ant-TESTONLY000env"
FILE_KEY = "sk-ant-TESTONLY000file"
# Wrong prefix: what a truncated paste or a shell-mangled value looks like.
MALFORMED = "not-a-key-at-all"


def _write_key_file(app_dir: Path, value: str) -> Path:
    p = app_dir / "API-Key-Claude.txt"
    p.write_text(value, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Consumer adapters - each returns the key string the consumer would use,
# with its file source rooted at `app_dir`.
# ---------------------------------------------------------------------------

def _load_base_coach(app_dir: Path, monkeypatch) -> str:
    from coaches._base_coach import read_api_key
    return read_api_key(app_dir)


def _load_warm_session(app_dir: Path, monkeypatch) -> str:
    from agents.agent7_context import warm_session
    return warm_session._load_api_key(app_dir)


def _load_tft_pbe(app_dir: Path, monkeypatch) -> str:
    from coaches import tft_pbe_coach
    return tft_pbe_coach._read_api_key(app_dir)


class _Handler:
    """Minimal stand-in for the BaseHTTPRequestHandler the routes take."""

    def __init__(self) -> None:
        self.status = 0
        self.body = b""
        self.ctype = ""

    def _send(self, status, body, ctype, cache_control=None):
        self.status = status
        self.body = body
        self.ctype = ctype

    def json(self) -> dict:
        return json.loads(self.body.decode())


def _load_routes_coach(app_dir: Path, monkeypatch) -> str:
    """Drive /api/champ-select-coach and report the key it handed onward.

    There is no key-reading function to call here - the read is inline in
    the handler - so the only honest probe is to run the route and capture
    the `api_key` argument that actually reached `coach_pick`.
    """
    import coaches.champ_select_coach as csc
    from core import champ_select_shadow
    from dashboard import routes_coach

    seen: dict[str, str] = {}

    def _fake_coach_pick(state, api_key):
        seen["api_key"] = api_key
        return {"ok": True, "advice": "stub"}

    monkeypatch.setattr(csc, "coach_pick", _fake_coach_pick)
    # The do-not-flip-blind shadow write is incidental to this route's key
    # handling and would touch data/ - neutralise it, do not exercise it.
    monkeypatch.setattr(champ_select_shadow, "log_champ_select_advice",
                        lambda *a, **kw: None)
    monkeypatch.setattr(routes_coach, "APP_DIR", app_dir)

    h = _Handler()
    routes_coach._serve_champ_select_coach_post(h, {"my_champion": "Ahri"})
    assert h.status == 200, (
        "the route did not answer 200 - the key assertion below would be "
        f"reading a failure, not a key (body={h.body!r})")
    assert "api_key" in seen, "coach_pick was never reached"
    return seen["api_key"]


def _load_game_lifecycle(app_dir: Path, monkeypatch) -> str:
    """Drive GameLifecycleManager.try_read_api_key with its file root moved.

    This consumer differs from the other three: it takes NO app_dir argument,
    so the file half cannot be redirected by a parameter. It resolves the key
    file against the module-level `SCRIPT_DIR`, which is what gets patched.

    The instance is built with `object.__new__` on purpose - `__init__` wants a
    live OverlayApp, and the method under test never touches `self`. The public
    `try_read_api_key` passthrough is called rather than the private method, so
    the passthrough -> private hop is genuinely exercised.

    Stated precisely, because the obvious stronger claim is not supported: the
    `app/__init__.py:221-222` wrapper above the passthrough is NOT covered here.
    Stubbing `app.OverlayApp._try_read_api_key` leaves this file fully green, so
    that outermost hop rests on inspection of a one-line delegation, not on a
    test. Do not read this adapter as pinning the whole chain.
    """
    from app import _game_lifecycle as glc

    monkeypatch.setattr(glc, "SCRIPT_DIR", app_dir)
    mgr = object.__new__(glc.GameLifecycleManager)
    return mgr.try_read_api_key()


CONSUMERS = [
    pytest.param(_load_base_coach, id="coaches._base_coach.read_api_key"),
    pytest.param(_load_warm_session, id="agent7.warm_session._load_api_key"),
    pytest.param(_load_tft_pbe, id="coaches.tft_pbe_coach._read_api_key"),
    pytest.param(_load_routes_coach, id="dashboard.routes_coach"),
    pytest.param(_load_game_lifecycle, id="app._game_lifecycle.try_read_api_key"),
]

assert CONSUMERS, "empty consumer set - this file would pass proving nothing"


# ---------------------------------------------------------------------------
# The four ordering properties, across every in-scope consumer.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("load", CONSUMERS)
def test_env_wins_when_both_sources_are_present(load, tmp_path, monkeypatch):
    """The stale-wins trap. A file present must NOT beat a rotated env var."""
    monkeypatch.setenv(ENV_VAR, ENV_KEY)
    _write_key_file(tmp_path, FILE_KEY)
    assert load(tmp_path, monkeypatch) == ENV_KEY


@pytest.mark.parametrize("load", CONSUMERS)
def test_file_is_used_when_env_is_absent(load, tmp_path, monkeypatch):
    """Flipping the order must not DELETE the file path - it is the fallback."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    _write_key_file(tmp_path, FILE_KEY)
    assert load(tmp_path, monkeypatch) == FILE_KEY


@pytest.mark.parametrize("load", CONSUMERS)
def test_malformed_env_does_not_shadow_a_good_file(load, tmp_path, monkeypatch):
    """env-first must mean "first VALID", not "first PRESENT".

    A bare env-first read would return the junk and never look at the file,
    turning a recoverable state into a hard outage. The `sk-ant-` prefix
    guard is what makes the fallback reachable.
    """
    monkeypatch.setenv(ENV_VAR, MALFORMED)
    _write_key_file(tmp_path, FILE_KEY)
    assert load(tmp_path, monkeypatch) == FILE_KEY


@pytest.mark.parametrize("load", CONSUMERS)
def test_returns_empty_string_when_neither_source_exists(load, tmp_path,
                                                         monkeypatch):
    """Fail-soft: degrade to no-coaching, never raise into the caller."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert not (tmp_path / "API-Key-Claude.txt").exists()
    assert load(tmp_path, monkeypatch) == ""


@pytest.mark.parametrize("load", CONSUMERS)
def test_unreadable_key_file_degrades_instead_of_raising(load, tmp_path,
                                                         monkeypatch):
    """A non-UTF8 key file is a UnicodeDecodeError on read_text.

    Every consumer must swallow it and fall through, not propagate it up
    into a coach tick or an HTTP handler.
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    (tmp_path / "API-Key-Claude.txt").write_bytes(b"\xff\xfe\x00bad")
    assert load(tmp_path, monkeypatch) == ""


# ---------------------------------------------------------------------------
# routes_coach specifically - the one live bug.
# ---------------------------------------------------------------------------

def test_routes_coach_reads_the_environment(tmp_path, monkeypatch):
    """THE regression test for the live bug - it FAILED before the fix.

    With `API-Key-Claude.txt` deleted (the state of the machine as of
    2026-09-29) the route read the file, found nothing, and passed "" into
    `coach_pick`, which answers "(API key missing - coach disabled)". The
    key was in the environment the whole time.
    """
    monkeypatch.setenv(ENV_VAR, ENV_KEY)
    assert not (tmp_path / "API-Key-Claude.txt").exists()
    assert _load_routes_coach(tmp_path, monkeypatch) == ENV_KEY, (
        "dashboard/routes_coach.py has no environment path - champ-select "
        "coaching is off whenever API-Key-Claude.txt is absent")


def test_routes_coach_stays_fail_soft_with_no_key_anywhere(tmp_path,
                                                           monkeypatch):
    """No key must still be a 200 with disabled advice, not a 500."""
    import coaches.champ_select_coach as csc
    from core import champ_select_shadow
    from dashboard import routes_coach

    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(routes_coach, "APP_DIR", tmp_path)
    monkeypatch.setattr(champ_select_shadow, "log_champ_select_advice",
                        lambda *a, **kw: None)
    # Real coach_pick here: its own `if not api_key` guard is the fail-soft
    # posture this route depends on, and a stub would not prove it holds.
    assert csc.coach_pick is not None

    h = _Handler()
    routes_coach._serve_champ_select_coach_post(h, {"my_champion": "Ahri"})
    assert h.status == 200
    assert "API key missing" in h.json()["advice"]
