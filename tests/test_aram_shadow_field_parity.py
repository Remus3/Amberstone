"""Field-parity regression tests for the ARAM / Arena coach shadow comparator.

Closes three MEASURED gaps found by ``tools/aram_shadow_report.py`` over 4467
shadow rows, where the report's ``live_only=N`` column counts ticks on which
Haiku produced a field and the deterministic block was EMPTY:

  1. CAPTURE BUG (``choices`` reads both=0 / live_only=0 - structurally
     impossible for the live side to ever carry it). ``_live_aram_block`` and
     ``_live_arena_block`` each hardcoded their own key tuple, and both drifted
     behind the shadow modules' ``_BLOCK_KEYS``: the ARAM reader dropped
     ``choices`` / ``item_extra`` / ``objective`` and the Arena reader dropped
     ``choices``. The live column could never show a field the reader refused to
     read, so the anomaly was in the comparator, not in the coach.
  2. ``reset_item`` (820 live_only) - the build-order index was a RAW INVENTORY
     SLOT COUNT. ``dashboard/_liveclient.py`` builds ``owned_items`` from every
     inventory slot displayName, trinket and potions included, so a player with
     two legendaries plus a trinket and potions indexed a 6-entry legendary
     order at 5 or 6 - naming the wrong item, then falling off the end entirely
     and blanking ``reset_item``.
  3. ``item_build_reasons`` (830 live_only) - the assembler passed a hardcoded
     empty dict, so the ONLY reason source was the anti-tank / anti-heal hints.

All three are comparator-side / shadow-side; NO served field changes.
"""

from __future__ import annotations

import json

import pytest

from core import aram_coach_shadow, arena_coach_shadow
from dashboard._deterministic_coaching import (
    _live_aram_block,
    _live_arena_block,
    shadow_log_aram_coach,
)

# Kalista's tracked ARAM balanced build order resolves to these six names in
# order (data/daemon_slayer/<patch>/build_orders_aram.json + items.json). Index
# 2 is the assertion target: a player owning the FIRST TWO must be pointed at
# the third, no matter how many consumables share the inventory.
_KALISTA_BUILD_IDS = ["3153", "3006", "3085", "3302", "6672", "3036"]
_KALISTA_THIRD_ITEM = "Runaan's Hurricane"

# Trinket + potion ids. These occupy inventory slots but are NOT build items,
# and they are exactly what inflated the old raw-len() index.
_TRINKET_ID = "3340"
_POTION_IDS = ["2003", "2003", "2031"]


def _read_row(path):
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one shadow row, got {len(lines)}"
    return json.loads(lines[0])


def _aram_lc(owned_ids, owned_names):
    return {
        "champion": "Kalista",
        "enemy_team": ["Ashe", "Annie", "Leona", "Malphite", "Sett"],
        "hp": 850,
        "hp_max": 1000,
        "owned_items": owned_names,
        "owned_item_ids": owned_ids,
    }


# ---------------------------------------------------------------------------
# Gap 1 - the live-side capture bug behind the `choices` anomaly.
# ---------------------------------------------------------------------------

def test_live_aram_block_captures_every_shadow_schema_field(tmp_path):
    """The ARAM live reader must surface every column the shadow row records.

    Driven FROM the shadow module's _BLOCK_KEYS (the schema authority) INTO the
    reader (the consumer), so a future key added to the shadow schema fails here
    instead of silently reading as an all-empty live column for months.
    """
    artifact = tmp_path / "aram_coaching_data.json"
    payload = {key: f"live-{key}" for key in aram_coach_shadow._BLOCK_KEYS}
    payload["item_build_reasons"] = {"Kraken Slayer": "live reason"}
    payload["choices"] = [{"key": "A", "label": "All-in"}]
    payload["game_id"] = "ignored-extra-field"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    block = _live_aram_block(artifact)

    missing = [k for k in aram_coach_shadow._BLOCK_KEYS if k not in block]
    assert not missing, f"live ARAM reader dropped shadow columns: {missing}"
    assert block["choices"] == [{"key": "A", "label": "All-in"}]
    assert block["item_extra"] == "live-item_extra"
    assert block["objective"] == "live-objective"


def test_live_arena_block_captures_every_shadow_schema_field(tmp_path):
    """Arena sibling of the same root cause - its reader dropped `choices`."""
    artifact = tmp_path / "arena_coaching_data.json"
    payload = {key: f"live-{key}" for key in arena_coach_shadow._BLOCK_KEYS}
    payload["choices"] = [{"key": "B", "label": "Reposition"}]
    payload["round"] = "ignored-extra-field"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    block = _live_arena_block(artifact)

    missing = [k for k in arena_coach_shadow._BLOCK_KEYS if k not in block]
    assert not missing, f"live Arena reader dropped shadow columns: {missing}"
    assert block["choices"] == [{"key": "B", "label": "Reposition"}]


@pytest.mark.parametrize("reader", [_live_aram_block, _live_arena_block])
def test_live_block_readers_stay_fail_soft(tmp_path, reader):
    """A missing / malformed artifact still degrades to {}, never raises."""
    assert reader(tmp_path / "absent.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("[not, a, dict", encoding="utf-8")
    assert reader(bad) == {}
    not_dict = tmp_path / "list.json"
    not_dict.write_text("[1, 2, 3]", encoding="utf-8")
    assert reader(not_dict) == {}


# ---------------------------------------------------------------------------
# Gap 2 - reset_item: index the build order by OWNED BUILD ITEMS, not slots.
# ---------------------------------------------------------------------------

def test_reset_item_indexes_build_order_by_owned_build_items(tmp_path):
    """Two build items owned plus four consumables must still point at index 2.

    Six inventory slots used to index a six-entry order out of range, blanking
    reset_item. The count that matters is how many of the CHAMPION'S OWN build
    items are owned - matched by id, never by slot count.
    """
    target = tmp_path / "aram_coach_shadow.jsonl"
    owned_ids = _KALISTA_BUILD_IDS[:2] + [_TRINKET_ID] + _POTION_IDS
    owned_names = ["Blade of The Ruined King", "Berserker's Greaves",
                   "Scrying Orb", "Health Potion", "Health Potion",
                   "Refillable Potion"]
    assert len(owned_ids) >= len(_KALISTA_BUILD_IDS), (
        "the regression needs an inventory at least as long as the build order"
    )

    shadow_log_aram_coach(
        {"champion": "Kalista", "hp_pct": 85},
        _aram_lc(owned_ids, owned_names),
        "aram",
        path=target,
        live_path=tmp_path / "absent_live.json",
    )

    det = _read_row(target)["deterministic"]
    assert det["reset_item"], "reset_item blanked by a consumable-padded inventory"
    assert _KALISTA_THIRD_ITEM in det["reset_item"], (
        f"expected the 3rd build item, got: {det['reset_item']!r}"
    )


def test_reset_item_points_at_first_item_when_only_consumables_owned(tmp_path):
    """A trinket-and-potions-only inventory has bought NO build item yet."""
    target = tmp_path / "aram_coach_shadow.jsonl"
    shadow_log_aram_coach(
        {"champion": "Kalista", "hp_pct": 60},
        _aram_lc([_TRINKET_ID] + _POTION_IDS,
                 ["Scrying Orb", "Health Potion", "Health Potion",
                  "Refillable Potion"]),
        "aram",
        path=target,
        live_path=tmp_path / "absent_live.json",
    )

    det = _read_row(target)["deterministic"]
    assert "Blade of The Ruined King" in det["reset_item"], (
        f"expected the 1st build item, got: {det['reset_item']!r}"
    )


def test_reset_item_counts_owned_build_items_out_of_order(tmp_path):
    """Owning items 1 and 3 is two build items bought - point at index 2.

    ARAM lets a player buy off-order. The count is a MEMBERSHIP count, so an
    out-of-order purchase advances the pointer rather than mis-indexing.
    """
    target = tmp_path / "aram_coach_shadow.jsonl"
    owned_ids = [_KALISTA_BUILD_IDS[0], _KALISTA_BUILD_IDS[2], _TRINKET_ID]
    shadow_log_aram_coach(
        {"champion": "Kalista", "hp_pct": 70},
        _aram_lc(owned_ids, ["Blade of The Ruined King", "Runaan's Hurricane",
                             "Scrying Orb"]),
        "aram",
        path=target,
        live_path=tmp_path / "absent_live.json",
    )

    det = _read_row(target)["deterministic"]
    assert _KALISTA_THIRD_ITEM in det["reset_item"], (
        f"expected index 2 for two owned build items, got: {det['reset_item']!r}"
    )


# ---------------------------------------------------------------------------
# Gap 3 - item_build_reasons must carry the deterministic per-item cue map.
# ---------------------------------------------------------------------------

def test_item_build_reasons_carries_deterministic_cues(tmp_path, monkeypatch):
    """The assembler must pass a real per-item reason map, not a hardcoded {}.

    The cue corpus (data/coaching/aram_item_interaction.json) is a gitignored
    local artifact, so the cue producer is patched at its lazy-import site here;
    what this proves is that the ASSEMBLER forwards the primitive it is given.
    """
    import core.aram_item_interaction_context as cues_mod

    captured: dict = {}

    def fake_cues(enemies, game_time_s, item_names, *, game_mode=None):
        captured["enemies"] = list(enemies or [])
        captured["item_names"] = list(item_names or [])
        captured["game_mode"] = game_mode
        return {
            "Blade of The Ruined King": "percent-HP shred vs the enemy frontline",
            "Berserker's Greaves": cues_mod.CUE_SENTINEL,
            "Kraken Slayer": "third-hit true damage carries the late game",
        }

    monkeypatch.setattr(cues_mod, "item_interaction_cues", fake_cues)

    target = tmp_path / "aram_coach_shadow.jsonl"
    shadow_log_aram_coach(
        {"champion": "Kalista", "hp_pct": 85, "game_time_s": 900},
        _aram_lc(_KALISTA_BUILD_IDS[:1], ["Blade of The Ruined King"]),
        "aram",
        path=target,
        live_path=tmp_path / "absent_live.json",
    )

    reasons = _read_row(target)["deterministic"]["item_build_reasons"]
    assert reasons.get("Blade of The Ruined King") == (
        "percent-HP shred vs the enemy frontline"
    )
    assert reasons.get("Kraken Slayer") == (
        "third-hit true damage carries the late game"
    )
    # A sentinel cue is NOT a reason - recording it would manufacture fake
    # coverage in the very report this slice exists to make honest.
    assert "Berserker's Greaves" not in reasons, (
        "the '-' no-data sentinel must never be recorded as a reason"
    )
    # The cue producer must be fed the champion's own build path + ARAM mode.
    assert "Ashe" in captured["enemies"]
    assert "Blade of The Ruined King" in captured["item_names"]
    assert captured["game_mode"] == "ARAM"


def test_item_build_reasons_absent_cue_corpus_degrades_without_raising(tmp_path):
    """The REAL cue path over an ABSENT corpus: empty reasons, no raise.

    Deliberately UNPATCHED - this exercises the genuine
    core.aram_item_interaction_context call. The corpus
    (data/coaching/aram_item_interaction.json) is a gitignored local artifact,
    so on a fresh checkout and in CI the producer returns {} and the cue-derived
    reasons are simply absent. Paired with the patched-producer test above so
    BOTH branches are covered: that one proves the assembler forwards a real
    map, this one proves the corpus-absent path is inert rather than fatal.
    """
    from core.aram_item_interaction_context import item_interaction_cues

    corpus_present = bool(
        item_interaction_cues(
            ["Ashe"], 900.0, ["Blade of The Ruined King"], game_mode="ARAM",
        )
    )

    target = tmp_path / "aram_coach_shadow.jsonl"
    shadow_log_aram_coach(
        {"champion": "Kalista", "hp_pct": 85, "game_time_s": 900},
        _aram_lc(_KALISTA_BUILD_IDS[:1], ["Blade of The Ruined King"]),
        "aram",
        path=target,
        live_path=tmp_path / "absent_live.json",
    )

    det = _read_row(target)["deterministic"]
    assert isinstance(det["item_build_reasons"], dict)
    assert det["item_build"], "the build path must survive an absent cue corpus"
    assert det["reset_item"], "reset_item must survive an absent cue corpus"
    if not corpus_present:
        # No corpus on this machine: no cue key may have been invented.
        assert "Kraken Slayer" not in det["item_build_reasons"]


def test_item_build_reasons_survives_a_broken_cue_producer(tmp_path, monkeypatch):
    """A raising cue producer must not blank the hint-derived reasons."""
    import core.aram_item_interaction_context as cues_mod

    def boom(*_a, **_k):
        raise RuntimeError("cue corpus unreadable")

    monkeypatch.setattr(cues_mod, "item_interaction_cues", boom)

    target = tmp_path / "aram_coach_shadow.jsonl"
    shadow_log_aram_coach(
        {"champion": "Kalista", "hp_pct": 85},
        _aram_lc(_KALISTA_BUILD_IDS[:1], ["Blade of The Ruined King"]),
        "aram",
        path=target,
        live_path=tmp_path / "absent_live.json",
    )

    det = _read_row(target)["deterministic"]
    assert isinstance(det["item_build_reasons"], dict)
    assert det["item_build"], "a cue failure must not blank the build path"
