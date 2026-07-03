# arch: R65 slice B RED-first pins - live championStats + stat-shard ingestion | section=tests | frozen=no
"""R65 slice B (RED-first): L9/L10 live championStats + stat-shard ingestion.

Contract pinned by the R65 orchestrator - the implementation lands in a
PARALLEL slice, so every test touching the three new surfaces below is
EXPECTED to fail RED in this worktree until that slice merges:

1. game_reader.snapshot_normalizer._NormalizerMixin._process_game(raw) gains
   "combat_stats": 19 numeric keys mapped from activePlayer.championStats
   (NaN/inf-safe float coercion, default 0.0) plus "resource_type" (str, "").
2. _process_game gains "runes_full" from the NEW
   _NormalizerMixin._read_my_runes_structured() ({} on any failure, never
   raises) and "stat_shards": list[int] == runes_full["stat_runes"]
   ([] on failure).
3. core.coaching_payload._Base gains END-appended combat_stats: dict = {}
   and stat_shards: list = [].

Harness mirrors tests/test_p2w1_app_a.py: RC_VISION_TOKEN is set before
importing game_reader (the vision bearer token resolves at module load),
GameReader() gets its network-touching enrichment reads stubbed as instance
attributes, and self._get (game_reader.poller._PollerMixin._get, the sole
transport for the rune endpoints) is always replaced so no test ever opens
a socket.
"""

import copy
import math

import pytest

# ---------------------------------------------------------------------------
# Contract tables
# ---------------------------------------------------------------------------

# combat_stats output key -> activePlayer.championStats source key.
_STAT_SOURCES = {
    "attack_damage":  "attackDamage",
    "ability_power":  "abilityPower",
    "armor":          "armor",
    "magic_resist":   "magicResist",
    "armor_pen_flat": "physicalLethality",
    "armor_pen_pct":  "armorPenetrationPercent",
    "magic_pen_flat": "magicPenetrationFlat",
    "magic_pen_pct":  "magicPenetrationPercent",
    "ability_haste":  "abilityHaste",
    "attack_speed":   "attackSpeed",
    "crit_chance":    "critChance",
    "crit_damage":    "critDamage",
    "life_steal":     "lifeSteal",
    "physical_vamp":  "physicalVamp",
    "spell_vamp":     "spellVamp",
    "move_speed":     "moveSpeed",
    "attack_range":   "attackRange",
    "tenacity":       "tenacity",
    "health_regen":   "healthRegenRate",
}

# Distinct per-source values so a source->destination swap cannot pass.
_STAT_VALUES = {
    "attackDamage":            142.5,
    "abilityPower":            88.25,
    "armor":                   71.5,
    "magicResist":             42.75,
    "physicalLethality":       18.0,
    "armorPenetrationPercent": 0.24,
    "magicPenetrationFlat":    12.5,
    "magicPenetrationPercent": 0.31,
    "abilityHaste":            45.0,
    "attackSpeed":             1.42,
    "critChance":              0.55,
    "critDamage":              1.75,
    "lifeSteal":               0.12,
    "physicalVamp":            0.07,
    "spellVamp":               0.09,
    "moveSpeed":               372.0,
    "attackRange":             550.0,
    "tenacity":                0.3,
    "healthRegenRate":         3.6,
}

_EXPECTED_COMBAT_STATS = {
    out_key: _STAT_VALUES[src] for out_key, src in _STAT_SOURCES.items()
}
_EXPECTED_COMBAT_STATS["resource_type"] = "MANA"

_DEFAULT_COMBAT_STATS = {out_key: 0.0 for out_key in _STAT_SOURCES}
_DEFAULT_COMBAT_STATS["resource_type"] = ""

# /activeplayerrunes structured payload (Riot naming) -> runes_full contract.
_RUNES_PAYLOAD = {
    "keystone": {
        "id": 8112,
        "displayName": "Electrocute",
        "rawDescription": "perk_tooltip_Electrocute",
    },
    "primaryRuneTree": {"id": 8100, "displayName": "Domination"},
    "secondaryRuneTree": {"id": 8200, "displayName": "Sorcery"},
    "generalRunes": [
        {"id": 8112, "displayName": "Electrocute"},
        {"id": 8139, "displayName": "Taste of Blood"},
        {"id": 8138, "displayName": "Eyeball Collection"},
        {"id": 8135, "displayName": "Treasure Hunter"},
        {"id": 8226, "displayName": "Manaflow Band"},
        {"id": 8236, "displayName": "Gathering Storm"},
    ],
    "statRunes": [
        {"id": 5008, "rawDescription": "perk_tooltip_StatModAdaptive"},
        {"id": 5008, "rawDescription": "perk_tooltip_StatModAdaptive"},
        {"id": 5011, "rawDescription": "perk_tooltip_StatModHealth"},
    ],
}

_EXPECTED_RUNES_FULL = {
    "keystone": {"id": 8112, "name": "Electrocute"},
    "primary_tree": "Domination",
    "secondary_tree": "Sorcery",
    "general_runes": [
        {"id": 8112, "name": "Electrocute"},
        {"id": 8139, "name": "Taste of Blood"},
        {"id": 8138, "name": "Eyeball Collection"},
        {"id": 8135, "name": "Treasure Hunter"},
        {"id": 8226, "name": "Manaflow Band"},
        {"id": 8236, "name": "Gathering Storm"},
    ],
    "stat_runes": [5008, 5008, 5011],
}


# ---------------------------------------------------------------------------
# Hermetic harness (mirrors tests/test_p2w1_app_a.py)
# ---------------------------------------------------------------------------


def _set_token(monkeypatch):
    """Make the vision-token resolver succeed without the gitignored file."""
    monkeypatch.setenv("RC_VISION_TOKEN", "r65-slice-b-test-token")


def _no_network(url, *args, **kwargs):
    raise RuntimeError(f"hermetic test: unexpected network _get({url})")


def _runes_get(url, *args, **kwargs):
    """Serve the structured /activeplayerrunes payload; refuse anything else."""
    if "activeplayerrunes" in url:
        return copy.deepcopy(_RUNES_PAYLOAD)
    raise RuntimeError(f"hermetic test: unexpected network _get({url})")


def _raising_get(url, *args, **kwargs):
    raise RuntimeError("hermetic test: transport down")


def _build_reader(monkeypatch, get_stub=_no_network):
    _set_token(monkeypatch)
    from game_reader import GameReader
    r = GameReader()
    # Stub the network-touching enrichment reads so _process_game stays
    # offline (mirrors test_p2w1_app_a._build_reader). The NEW
    # _read_my_runes_structured is deliberately NOT stubbed - it must run
    # for real against the _get stub below.
    r._try_lcu_game_id = lambda: ""
    r._read_my_runes = lambda: ""
    r._read_enemy_runes = lambda enemies: {}
    r._read_my_abilities = lambda: {}
    # The sole transport never leaves the process: rune tests swap in
    # payload-returning stubs, everything else raises.
    r._get = get_stub
    return r


def _raw_game(active_extra=None):
    active = {"championName": "Ahri", "level": 7, "currentGold": 950.0}
    if active_extra:
        active.update(active_extra)
    return {
        "gameData": {"gameTime": 725.0, "gameMode": "CLASSIC"},
        "activePlayer": active,
        "allPlayers": [],
        "events": {"Events": []},
    }


# ---------------------------------------------------------------------------
# 1. Full championStats payload -> combat_stats exact mapped values
# ---------------------------------------------------------------------------


def test_combat_stats_full_payload_exact_mapping(monkeypatch):
    r = _build_reader(monkeypatch)
    champion_stats = dict(_STAT_VALUES)
    champion_stats.update({
        "currentHealth": 820.0, "maxHealth": 1400.0,
        "resourceValue": 310.0, "resourceMax": 500.0,
        "resourceType": "MANA",
    })
    out = r._process_game(_raw_game({"championStats": champion_stats}))
    assert isinstance(out, dict)
    combat = out["combat_stats"]  # RED until L9 lands: KeyError
    assert combat == _EXPECTED_COMBAT_STATS
    for key, value in combat.items():
        if key == "resource_type":
            assert isinstance(value, str)
            continue
        assert isinstance(value, float), f"{key}: expected float, got {type(value).__name__}"
        assert math.isfinite(value), f"{key}: non-finite value leaked"
    # hp/mana regression pins - the existing absolute-stat path is unchanged.
    assert out["hp_abs"] == 820
    assert out["hp_max"] == 1400
    assert out["mp_abs"] == 310
    assert out["mp_max"] == 500
    assert out["hp_pct"] == int(100 * 820 / 1400)


# ---------------------------------------------------------------------------
# 2. NaN / Infinity championStats values -> coerced to 0.0, no raise
# ---------------------------------------------------------------------------


def test_combat_stats_nan_inf_coerced_to_defaults(monkeypatch):
    r = _build_reader(monkeypatch)
    champion_stats = {
        "attackDamage": float("nan"),
        "abilityPower": float("inf"),
        "armor": float("-inf"),
        "attackSpeed": "not-a-number",
        "critChance": None,
        "currentHealth": 500.0, "maxHealth": 1000.0,
        "resourceType": "MANA",
    }
    out = r._process_game(_raw_game({"championStats": champion_stats}))  # must not raise
    assert isinstance(out, dict)
    combat = out["combat_stats"]  # RED until L9 lands: KeyError
    assert combat["attack_damage"] == 0.0
    assert combat["ability_power"] == 0.0
    assert combat["armor"] == 0.0
    assert combat["attack_speed"] == 0.0
    assert combat["crit_chance"] == 0.0
    # Sources absent from the payload fall back to the 0.0 default too.
    assert combat["magic_resist"] == 0.0
    assert combat["move_speed"] == 0.0
    assert combat["resource_type"] == "MANA"
    for key, value in combat.items():
        if key == "resource_type":
            continue
        assert math.isfinite(value), f"{key}: non-finite value leaked"


# ---------------------------------------------------------------------------
# 3. championStats missing / non-dict -> all-default combat_stats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("active_extra", [
    {},                                        # championStats key absent
    {"championStats": "transitional-string"},  # non-dict (API transitional state)
    {"championStats": 42},
    {"championStats": None},
    {"championStats": ["list", "not", "dict"]},
], ids=["missing", "str", "int", "none", "list"])
def test_combat_stats_missing_or_non_dict_all_defaults(monkeypatch, active_extra):
    r = _build_reader(monkeypatch)
    out = r._process_game(_raw_game(active_extra))
    assert isinstance(out, dict)
    combat = out["combat_stats"]  # RED until L9 lands: KeyError
    assert combat == _DEFAULT_COMBAT_STATS
    assert combat["resource_type"] == ""
    # Existing hp defaults hold (non-dict stats guard already in place).
    assert out["hp_abs"] == 0
    assert out["hp_max"] == 1


# ---------------------------------------------------------------------------
# 4. /activeplayerrunes structured payload -> runes_full + stat_shards
# ---------------------------------------------------------------------------


def test_read_my_runes_structured_parses_payload_exactly(monkeypatch):
    r = _build_reader(monkeypatch, get_stub=_runes_get)
    result = r._read_my_runes_structured()  # RED until L10 lands: AttributeError
    assert result == _EXPECTED_RUNES_FULL
    assert all(isinstance(rid, int) for rid in result["stat_runes"])


def test_process_game_carries_runes_full_and_stat_shards(monkeypatch):
    r = _build_reader(monkeypatch, get_stub=_runes_get)
    out = r._process_game(_raw_game({"championStats": {
        "currentHealth": 820.0, "maxHealth": 1400.0,
    }}))
    assert isinstance(out, dict)
    assert out["runes_full"] == _EXPECTED_RUNES_FULL  # RED until L10 lands: KeyError
    assert out["stat_shards"] == [5008, 5008, 5011]
    assert out["stat_shards"] == out["runes_full"]["stat_runes"]


# ---------------------------------------------------------------------------
# 5. _get raising / returning non-dict -> runes_full {} / stat_shards []
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("get_stub", [
    _raising_get,
    lambda url, *a, **k: None,
    lambda url, *a, **k: "not-a-dict",
    lambda url, *a, **k: 7,
    lambda url, *a, **k: [],
], ids=["raises", "none", "str", "int", "list"])
def test_read_my_runes_structured_failure_returns_empty(monkeypatch, get_stub):
    r = _build_reader(monkeypatch, get_stub=get_stub)
    result = r._read_my_runes_structured()  # RED until L10 lands: AttributeError
    assert result == {}


def test_process_game_runes_failure_lands_empty_defaults(monkeypatch):
    r = _build_reader(monkeypatch, get_stub=_raising_get)
    out = r._process_game(_raw_game())  # must not raise
    assert isinstance(out, dict)
    assert out["runes_full"] == {}  # RED until L10 lands: KeyError
    assert out["stat_shards"] == []


# ---------------------------------------------------------------------------
# 6. core.coaching_payload._Base schema: combat_stats + stat_shards
# ---------------------------------------------------------------------------


def test_base_payload_declares_combat_stats_and_stat_shards():
    from core.coaching_payload import _Base
    fields = list(_Base.model_fields)
    assert "combat_stats" in fields  # RED until the schema lands
    assert "stat_shards" in fields
    # END-appended after the pre-existing _Base fields (python-conventions
    # rule: never insert mid-class).
    assert fields.index("combat_stats") > fields.index("action")
    assert fields.index("stat_shards") > fields.index("action")
    inst = _Base()
    assert inst.combat_stats == {}
    assert inst.stat_shards == []


def test_validate_payload_well_typed_combat_fields_true():
    from core.coaching_payload import validate_coaching_payload
    payload = {
        "mode": "aram",
        "action": "Shove wave then rotate",
        "combat_stats": dict(_EXPECTED_COMBAT_STATS),
        "stat_shards": [5008, 5008, 5011],
    }
    assert validate_coaching_payload(payload) is True


def test_validate_payload_wrong_typed_combat_fields_soft_fail_no_raise():
    from core.coaching_payload import validate_coaching_payload
    bad = {
        "mode": "aram",
        "combat_stats": "not-a-dict",
        "stat_shards": "not-a-list",
    }
    result = validate_coaching_payload(bad)  # must not raise (soft validation)
    # RED today: the fields are undeclared, extra="allow" skips type checks
    # and this returns True. Once _Base declares them, wrong types soft-fail.
    assert result is False
