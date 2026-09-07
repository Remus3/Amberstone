# arch: lane 8 cycle 14 - game_reader/poller.py deep audit | section=tests | frozen=no
"""Lane 8 Headless-True-Audit cycle 14 - `game_reader/poller.py`.

Target picked on all five section-3 risk criteria at once: it parses input RC
did not author (the LCU lockfile, the LCU session, the relay envelope), it is
secret-adjacent (it carries a relay bearer token), it runs on the poll worker
thread, it is load-bearing with NO dedicated test module, and it is the single
biggest repeat offender found in recon (LEDGER 14 + history_notes 34 mentions).

Three defect families are pinned here.

1. THE RETIRED RELAY TOKEN. `core/vision_token.py` states in its own docstring
   that the hardcoded fallback "was retired by the 2026-04-28 audit, proposal
   1.7" so that a misconfigured deploy "fails loud instead of silently
   authenticating every request with a known constant". Five production modules
   kept a private copy of that retired constant anyway. It no longer matches the
   rotated token, so it authenticates nothing - it 401s. Memory
   `reference_vision_token_canonical` records this exact class twice already
   (items 242 and 243): a divergent token-resolution chain ending in this dead
   literal, whose only symptom under `pythonw` is that the feature silently dies.
   `test_retired_relay_token_appears_in_no_production_source` is the root-cause
   guard the two prior fixes never added.

2. `_process_champ_select` HAS NO TYPE GUARDS. The LCU sends `null` for a
   populated-later field, and `session.get("bans", {})` returns `None` - not the
   `{}` default - when the key is PRESENT and null. `read_champ_select` then
   swallows the AttributeError.

   SEVERITY, corrected by an adversarial pass and stated here so nobody
   re-inflates it: `read_champ_select` has NO production callers today, and it
   is the only caller of `_ensure_lcu`, `_lcu_get` and `_process_champ_select`,
   so this whole branch of the module is currently dormant. The same-named
   `_lcu_get` in `lcu/lcu_postgame_collector` is that class's own method, not
   this one. These are therefore hardening tests for a dormant path, not proof
   of an observed champ-select outage - and the null-`bans` shape is inferred
   from LCU behaviour, not from a captured payload.

3. THE LCU LOCKFILE PORT IS UNVALIDATED. `parts[2]` goes straight into an
   f-string URL. League writes that file at startup, so a torn read is a real
   race, and a non-numeric port silently produces a malformed request forever
   (the port is cached on the instance once set).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The constant retired by the 2026-04-28 audit. Split so this guard file does
# not itself trip the very grep it enforces.
_RETIRED_TOKEN = "8e8f131e" + "212b329438218eca27372dde"


def _set_token(monkeypatch):
    """Make the vision-token resolver succeed without the gitignored file."""
    monkeypatch.setenv("RC_VISION_TOKEN", "lane8-cycle14-test-token")


def _build_reader(monkeypatch):
    _set_token(monkeypatch)
    from game_reader import GameReader
    return GameReader()


# ---------------------------------------------------------------------------
# 1. Characterization - the documented happy path must keep working.
# ---------------------------------------------------------------------------

def test_char_process_champ_select_returns_documented_shape(monkeypatch):
    """Pin current GOOD behaviour before changing anything."""
    r = _build_reader(monkeypatch)
    session = {
        "myTeam": [{"championId": 103}, {"championId": 0}, {"championId": 64}],
        "theirTeam": [{"championId": 55}],
        "bans": {"myTeamBans": [17], "theirTeamBans": [22, 0]},
    }
    out = r._process_champ_select(session)
    assert out["phase"] == "champ_select"
    # championId 0 means "not locked in yet" and is deliberately dropped.
    assert out["my_team_ids"] == ["103", "64"]
    assert out["their_team_ids"] == ["55"]
    assert out["ban_ids"] == ["17", "22"]


def test_char_absent_keys_already_tolerated(monkeypatch):
    """An EMPTY session is already safe - only null/wrong-type is not."""
    r = _build_reader(monkeypatch)
    out = r._process_champ_select({})
    assert out["my_team_ids"] == []
    assert out["their_team_ids"] == []
    assert out["ban_ids"] == []


# ---------------------------------------------------------------------------
# 2. Regression - `_process_champ_select` shape hardening.
# ---------------------------------------------------------------------------

def test_champ_select_survives_null_session(monkeypatch):
    """The LCU returns null between phases; that must not raise."""
    r = _build_reader(monkeypatch)
    assert r._process_champ_select(None) is None


def test_champ_select_survives_null_bans_block(monkeypatch):
    """`bans` PRESENT and null defeats the `{}` default of dict.get.

    This is the sharp one: `session.get("bans", {})` returns the default only
    when the key is ABSENT. A present-but-null value returns None, and
    `None.get(...)` raises AttributeError.
    """
    r = _build_reader(monkeypatch)
    out = r._process_champ_select({"myTeam": [{"championId": 7}], "bans": None})
    assert out["ban_ids"] == []
    assert out["my_team_ids"] == ["7"]


def test_champ_select_survives_wrong_typed_team(monkeypatch):
    """A string where a list of dicts was expected must not raise."""
    r = _build_reader(monkeypatch)
    out = r._process_champ_select({"myTeam": "Ahri", "theirTeam": None})
    assert out["my_team_ids"] == []
    assert out["their_team_ids"] == []


def test_champ_select_survives_non_dict_pick_entries(monkeypatch):
    """A list of ints/None where a list of dicts was expected must not raise."""
    r = _build_reader(monkeypatch)
    out = r._process_champ_select(
        {"myTeam": [None, 42, {"championId": 99}, "x"]}
    )
    assert out["my_team_ids"] == ["99"]


def test_champ_select_survives_null_ban_list(monkeypatch):
    """`myTeamBans` present and null must not raise."""
    r = _build_reader(monkeypatch)
    out = r._process_champ_select(
        {"bans": {"myTeamBans": None, "theirTeamBans": [5]}}
    )
    assert out["ban_ids"] == ["5"]


# ---------------------------------------------------------------------------
# 3. Regression - LCU lockfile port validation.
# ---------------------------------------------------------------------------

def _lockfile(tmp_path: Path, body: str) -> Path:
    lf = tmp_path / "lockfile"
    lf.write_text(body, encoding="utf-8")
    return lf


def test_lockfile_with_valid_port_is_accepted(monkeypatch, tmp_path):
    """Characterization: a well-formed lockfile still connects."""
    r = _build_reader(monkeypatch)
    lf = _lockfile(tmp_path, "LeagueClient:1234:54321:secretpw:https")
    monkeypatch.setattr(type(r), "_LCU_LOCKFILE_PATHS", [lf])
    assert r._ensure_lcu() is True
    assert r._lcu_port == "54321"
    assert r._lcu_auth


def test_lockfile_with_non_numeric_port_is_rejected(monkeypatch, tmp_path):
    """A torn or corrupt lockfile must not poison the cached LCU port.

    `_lcu_port` is cached on the instance and reused for every later request,
    so accepting garbage here breaks champ select until the process restarts.
    """
    r = _build_reader(monkeypatch)
    lf = _lockfile(tmp_path, "LeagueClient:1234:NOTAPORT:secretpw:https")
    monkeypatch.setattr(type(r), "_LCU_LOCKFILE_PATHS", [lf])
    r._ensure_lcu()
    assert r._lcu_port != "NOTAPORT"


def test_lockfile_with_out_of_range_port_is_rejected(monkeypatch, tmp_path):
    """A digit string outside the valid TCP range is still not a port."""
    r = _build_reader(monkeypatch)
    lf = _lockfile(tmp_path, "LeagueClient:1234:99999:secretpw:https")
    monkeypatch.setattr(type(r), "_LCU_LOCKFILE_PATHS", [lf])
    r._ensure_lcu()
    assert r._lcu_port != "99999"


def test_lockfile_with_empty_password_is_rejected(monkeypatch, tmp_path):
    """An empty auth field yields a Basic header that cannot authenticate."""
    r = _build_reader(monkeypatch)
    lf = _lockfile(tmp_path, "LeagueClient:1234:54321::https")
    monkeypatch.setattr(type(r), "_LCU_LOCKFILE_PATHS", [lf])
    r._ensure_lcu()
    assert r._lcu_auth is None


# ---------------------------------------------------------------------------
# 3b. `_read_game_fallback` event normalisation must not pick an arbitrary key.
# ---------------------------------------------------------------------------

def _fallback_reader(monkeypatch, payloads: dict):
    r = _build_reader(monkeypatch)
    r._get = lambda url: payloads[url.rsplit("/", 1)[-1]]
    return r


def test_fallback_event_normalisation_picks_the_list_not_an_arbitrary_value():
    """`list(ev.values())[0]` trusted foreign key ORDER to find the events.

    A dict whose first value is not the event list silently became the event
    list. Select by shape (the first list-valued entry), not by position.
    """
    from game_reader.poller import _PollerMixin
    ev = {"apiVersion": "1.0", "Records": [{"EventName": "GameStart"}]}
    assert _PollerMixin._normalise_events(ev) == [{"EventName": "GameStart"}]


def test_fallback_event_normalisation_handles_no_list_value():
    from game_reader.poller import _PollerMixin
    assert _PollerMixin._normalise_events({"apiVersion": "1.0"}) == []
    assert _PollerMixin._normalise_events({}) == []


# ---------------------------------------------------------------------------
# 4. Root-cause guard - the retired token must not reappear ANYWHERE.
# ---------------------------------------------------------------------------

def _despliced(text: str) -> str:
    """Collapse Python/JS string-literal concatenation so a split hardcode shows.

    Mutation testing caught this: the contiguous-substring check alone passed
    against ``"8e8f131e" + "212b3..."``, so the guard could be defeated by the
    most obvious workaround. Joining adjacent quoted fragments closes that.
    """
    return re.sub(r"[\"']\s*\+?\s*[\"']", "", text)


def _tracked_sources() -> list[Path]:
    """Every tracked .py/.js under the repo, minus archives and this guard."""
    out: list[Path] = []
    skip_parts = {"_archive", ".git", "node_modules", "__pycache__"}
    for suffix in ("*.py", "*.js"):
        for p in _PROJECT_ROOT.rglob(suffix):
            if skip_parts & set(p.parts):
                continue
            out.append(p)
    return out


def test_retired_relay_token_appears_in_no_production_source():
    """`core/vision_token.py` retired the hardcoded fallback on purpose.

    Its docstring: "There is NO hardcoded fallback ... a missing token raises
    RuntimeError at import time so a misconfigured deploy fails loud instead of
    silently authenticating every request with a known constant."

    A private copy in a consumer defeats that entirely, and this exact literal
    has already caused two silent-401 outages (memory
    `reference_vision_token_canonical`, items 242 and 243). Two files are
    allowed to NAME it, both of which assert it is NOT used.
    """
    allowed = {
        _PROJECT_ROOT / "tests" / "test_p2w1_core_a.py",
        _PROJECT_ROOT / "tests" / "test_poller_lane8_cycle14.py",
    }
    offenders = []
    for p in _tracked_sources():
        if p in allowed:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _RETIRED_TOKEN in text or _RETIRED_TOKEN in _despliced(text):
            offenders.append(str(p.relative_to(_PROJECT_ROOT)))
    assert not offenders, (
        "the retired vision token is hardcoded in: " + ", ".join(sorted(offenders))
    )


def test_poller_resolves_its_relay_token_through_the_canonical_resolver():
    """poller.py must get its token from core.vision_token, with no literal."""
    src = (_PROJECT_ROOT / "game_reader" / "poller.py").read_text(encoding="utf-8")
    assert "from core.vision_token import" in src
    # No 32-hex literal anywhere in the module.
    assert not re.search(r"[\"'][0-9a-f]{32}[\"']", src), \
        "poller.py still carries a 32-hex token literal"


@pytest.mark.parametrize("relpath", [
    "tools/calibrate_vision.py",
    "tools/match_monitor.py",
    "tools/ds_matchdb_mcp_server.py",
    "web_dashboard.py",
])
def test_sibling_token_consumers_use_the_canonical_resolver(relpath):
    """Every sibling that carried the dead literal now resolves it properly.

    `calibrate_vision.py` and `match_monitor.py` held it UNCONDITIONALLY, so
    both were 401ing against the live relay before this cycle - the documented
    OCR-coverage workflow in CLAUDE.md ran through a tool that could not
    authenticate.
    """
    src = (_PROJECT_ROOT / relpath).read_text(encoding="utf-8")
    assert "vision_token" in src, f"{relpath} does not reference the resolver"
    assert not re.search(r"[\"'][0-9a-f]{32}[\"']", src), \
        f"{relpath} still carries a 32-hex token literal"
