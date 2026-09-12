# arch: RM-234 regression - one /activeplayerrunes GET per snapshot tick | section=tests | frozen=no
"""RM-234: `_process_game` pays ONE `/activeplayerrunes` GET per tick.

Before this slice the tick called `_read_my_runes_structured()` (for
`runes_full` / `stat_shards`) AND `_read_my_runes()` (for the legacy
"Keystone | Primary / Secondary" string), each issuing its own GET against
the same Live Client endpoint. Two consequences, both pinned here:

1. two synchronous `timeout=2` GETs on the poll thread for one payload
   (`game_reader/poller.py:277` `_get`);
2. on a 404 `_note_subresource_failure("/activeplayerrunes", ...)` fired
   TWICE per tick, so `get_liveclient_subresource_failures()` overstated
   that endpoint 2x - in the one counter whose block comment says it never
   under-reports.

The fix derives the legacy string from `runes_full` through the pure helper
`game_reader.snapshot_normalizer._runes_text_from_structured`, which must be
byte-equivalent to the legacy formatter for the same payload (including ""
on an empty keystone name and the `.strip(" |/")` trim on missing trees).
`_read_my_runes` itself is KEPT - `tests/test_silent_except_liveclient_subresource.py`
exercises it directly - and `my_runes` still reaches the live ARAM prompt
(`coaches/aram_coach.py:430` template line, `:1031` format kwarg).

Harness mirrors `tests/test_liveclient_championstats_ingestion.py`: a real
`GameReader` with `_get` swapped for an in-process stub and the OTHER
network-touching enrichment reads stubbed. `_read_my_runes` is deliberately
NOT stubbed here - it is the subject. Importing `game_reader` resolves the
vision bearer token at module load (`core.vision_token` raises when
unconfigured and `config/vision_token.txt` is gitignored), so every import
happens in-function AFTER `monkeypatch.setenv` - same as the sibling files.
"""

import copy
import urllib.error

import pytest

_RUNES_PAYLOAD = {
    "keystone": {
        "id": 8005,
        "displayName": "Press the Attack",
        "rawDescription": "perk_tooltip_PressTheAttack",
        "rawDisplayName": "perk_displayname_PressTheAttack",
    },
    "primaryRuneTree": {
        "id": 8000,
        "displayName": "Precision",
        "rawDescription": "perk_tooltip_8000",
        "rawDisplayName": "perk_displayname_8000",
    },
    "secondaryRuneTree": {
        "id": 8100,
        "displayName": "Domination",
        "rawDescription": "perk_tooltip_8100",
        "rawDisplayName": "perk_displayname_8100",
    },
    "generalRunes": [
        {"id": 9111, "displayName": "Triumph"},
        {"id": 9104, "displayName": "Legend: Alacrity"},
    ],
    "statRunes": [{"id": 5008}, {"id": 5008}, {"id": 5011}],
}

_EXPECTED_TEXT = "Press the Attack | Precision / Domination"


def _normalizer(monkeypatch):
    """Set the vision token, THEN import the module under test."""
    monkeypatch.setenv("RC_VISION_TOKEN", "rm234-test-token")
    import game_reader.snapshot_normalizer as sn
    return sn


@pytest.fixture(autouse=True)
def _clean_counters(monkeypatch):
    sn = _normalizer(monkeypatch)
    sn.reset_liveclient_subresource_failures()
    yield
    sn.reset_liveclient_subresource_failures()


def _build_reader(monkeypatch, get_stub):
    _normalizer(monkeypatch)
    from game_reader import GameReader
    r = GameReader()
    # Stub the OTHER network-touching enrichment reads so the tick stays
    # offline. `_read_my_runes` and `_read_my_runes_structured` are NOT
    # stubbed: the transport count below is the thing under test.
    r._try_lcu_game_id = lambda: ""
    r._read_enemy_runes = lambda enemies: {}
    r._read_my_abilities = lambda: {}
    r._get = get_stub
    return r


def _raw_game():
    return {
        "gameData": {"gameTime": 725.0, "gameMode": "CLASSIC"},
        "activePlayer": {"championName": "Ahri", "level": 7, "currentGold": 950.0},
        "allPlayers": [],
        "events": {"Events": []},
    }


def _served(sn, payload):
    """Minimal mixin host whose `_get` returns a fixed payload."""

    class _Served(sn._NormalizerMixin):
        def __init__(self, data):
            self._payload = data

        def _get(self, url):
            return copy.deepcopy(self._payload)

    return _Served(payload)


# ---------------------------------------------------------------------------
# 1. One tick -> exactly one /activeplayerrunes GET (RED today: two)
# ---------------------------------------------------------------------------


def test_tick_pays_one_activeplayerrunes_get(monkeypatch):
    calls = []

    def _get(url, *args, **kwargs):
        calls.append(url)
        if "activeplayerrunes" in url:
            return copy.deepcopy(_RUNES_PAYLOAD)
        raise RuntimeError(f"hermetic test: unexpected network _get({url})")

    r = _build_reader(monkeypatch, _get)
    out = r._process_game(_raw_game())

    rune_gets = [u for u in calls if u.endswith("/activeplayerrunes")]
    assert len(rune_gets) == 1, (
        f"expected ONE /activeplayerrunes GET per tick, got {len(rune_gets)}: {calls}"
    )
    # With enemy runes / abilities / LCU stubbed, that GET is the tick's
    # ONLY transport call - pins the per-tick census, not just the rune half.
    assert calls == rune_gets

    # The legacy string still arrives, now derived from the single payload.
    assert out["my_runes"] == _EXPECTED_TEXT
    assert out["runes_full"]["keystone"] == {"id": 8005, "name": "Press the Attack"}
    assert out["runes_full"]["primary_tree"] == "Precision"
    assert out["runes_full"]["secondary_tree"] == "Domination"
    assert out["stat_shards"] == [5008, 5008, 5011]


# ---------------------------------------------------------------------------
# 2. _runes_text_from_structured is byte-equivalent to the legacy formatter
# ---------------------------------------------------------------------------


_FULL = {
    "keystone": {"id": 8005, "displayName": "Press the Attack"},
    "primaryRuneTree": {"id": 8000, "displayName": "Precision"},
    "secondaryRuneTree": {"id": 8100, "displayName": "Domination"},
}
_EMPTY_KEYSTONE_NAME = {
    "keystone": {"id": 0, "displayName": ""},
    "primaryRuneTree": {"id": 8000, "displayName": "Precision"},
    "secondaryRuneTree": {"id": 8100, "displayName": "Domination"},
}
_MISSING_TREES = {
    "keystone": {"id": 8005, "displayName": "Press the Attack"},
}
_ONE_TREE = {
    "keystone": {"id": 8005, "displayName": "Press the Attack"},
    "primaryRuneTree": {"id": 8000, "displayName": "Precision"},
}
_NON_DICT = ["not", "a", "dict"]


@pytest.mark.parametrize(
    "label,payload,expected",
    [
        ("full", _FULL, _EXPECTED_TEXT),
        ("empty keystone name", _EMPTY_KEYSTONE_NAME, ""),
        # `.strip(" |/")` edge: "Press the Attack |  / " -> "Press the Attack"
        ("missing trees", _MISSING_TREES, "Press the Attack"),
        # trailing " / " trimmed, the " | " separator survives
        ("one tree", _ONE_TREE, "Press the Attack | Precision"),
        ("non-dict payload", _NON_DICT, ""),
    ],
)
def test_runes_text_matches_legacy_formatter(monkeypatch, label, payload, expected):
    sn = _normalizer(monkeypatch)
    reader = _served(sn, payload)

    legacy = reader._read_my_runes()
    structured = reader._read_my_runes_structured()
    derived = sn._runes_text_from_structured(structured)

    assert derived == legacy, (
        f"[{label}] derived {derived!r} != legacy {legacy!r} for structured {structured!r}"
    )
    # Pin the literal too, so a defect that breaks BOTH paths identically
    # cannot hide behind the equivalence assertion.
    assert derived == expected, f"[{label}] got {derived!r}, expected {expected!r}"


def test_runes_text_helper_is_defensive_on_bad_structure(monkeypatch):
    """The helper runs on the poll thread with no try/except around it."""
    sn = _normalizer(monkeypatch)
    helper = sn._runes_text_from_structured

    assert helper({}) == ""          # the `_read_my_runes_structured` failure shape
    assert helper(None) == ""
    assert helper("garbage") == ""
    assert helper({"keystone": "not-a-dict"}) == ""
    assert helper({"keystone": {"name": ""}}) == ""
    # trees absent from the structure -> same strip edge as the legacy path
    assert helper({"keystone": {"name": "Conqueror"}}) == "Conqueror"


# ---------------------------------------------------------------------------
# 3. A 404 counts ONCE per tick, not twice (RED today: 2)
# ---------------------------------------------------------------------------


def test_tick_404_counts_activeplayerrunes_once(monkeypatch):
    sn = _normalizer(monkeypatch)

    def _get_404(url, *args, **kwargs):
        if "activeplayerrunes" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        raise RuntimeError(f"hermetic test: unexpected network _get({url})")

    r = _build_reader(monkeypatch, _get_404)
    assert sn.get_liveclient_subresource_failures() == {}

    out = r._process_game(_raw_game())

    failures = sn.get_liveclient_subresource_failures()
    assert failures.get("/activeplayerrunes") == 1, (
        "one tick with a 404 must increment the /activeplayerrunes counter ONCE; "
        f"got {failures!r}"
    )
    # Degrade-to-empty contract preserved on every derived rune field.
    assert out["my_runes"] == ""
    assert out["runes_full"] == {}
    assert out["stat_shards"] == []
