"""Item-power-spike callouts must count COMPLETED LEGENDARIES, not slots.

Third and last consumer of the raw-inventory-slot-count defect. 5f1b6d5c fixed
the ARAM shadow assembler, 040f011e fixed the served build-order index, and both
deliberately left this one alone: ``next_callouts`` still received
``len(gs["items"])``, and ``dashboard/_liveclient.py`` builds that list from
EVERY inventory slot displayName / itemID (line 187 + 191), trinket and Health
Potions included.

``core.event_callouts._item_spike_callouts`` documents its parameter as the
number of completed items owned and emits an ACTIVE row at 1 / 2 / 3
("2-item spike - force fights now", eta_s 0.0). So a player holding nothing but
a trinket and a Health Potion was told they had hit a 2-item power spike.

The semantics chosen here are NOT the build-progress count 040f011e used for the
recall index, and that difference is pinned by test:

  * A power spike is a fact about the player's combat stats, so a legendary
    bought OFF the recommended build order still spikes
    (test_off_build_order_legendary_counts).
  * Boots are not a power spike, and 171 of 173 champions carry boots at index
    1 of their balanced build order, so a build-progress count reports a spike
    for a player who bought only shoes (test_boots_are_not_a_spike_item).

Arena matters here: item-spike rows are NOT mode-gated (they sit outside every
mode guard in next_callouts, so they fire for all of _KNOWN_MODES == sr / aram /
arena), and Arena's purchasable ids are flat 22-prefixed aliases. Those are
covered (test_arena_alias_ids_count).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from core.event_callouts import next_callouts  # noqa: E402
from dashboard import _deterministic_coaching as dc  # noqa: E402


@pytest.fixture(autouse=True)
def _no_state_leak():
    """The WS4 stagnation memory ``_STATE_SINCE`` is module-global and keyed on
    (champion, mode_key). The served tests below tick at an early game_time, and
    leaving an entry behind makes a SIBLING file's later-game tick look stagnant
    - which fires the advisory row that evicts the third callout slot."""
    dc._STATE_SINCE.clear()
    yield
    dc._STATE_SINCE.clear()

# Kalista's balanced order (identical in the sr and aram tables), with the
# 16.14.1 gold total beside each so a catalog drift breaks loudly here.
_BOTRK = ("3153", "Blade of The Ruined King")      # 3200
_BOOTS = ("3006", "Berserker's Greaves")           # 1100, Boots tag
_RUNAANS = ("3085", "Runaan's Hurricane")          # 2650
_TERMINUS = ("3302", "Terminus")                   # 3000
_KRAKEN = ("6672", "Kraken Slayer")                # 3000
_LDR = ("3036", "Lord Dominik's Regards")          # 3300
# Not anywhere in Kalista's order - the off-build-order case.
_RABADONS = ("3089", "Rabadon's Deathcap")         # 3500

_TRINKET = ("3363", "Farsight Alteration")         # 0, Trinket tag
_POTION = ("2003", "Health Potion")                # 50, Consumable tag
_REFILL = ("2031", "Refillable Potion")            # 150, Consumable tag

# Arena aliases of three of the above, plus an Arena prismatic. All flat
# 22-/44-prefixed ids with no component list, which is why the repo's existing
# classifier cannot see them (see the fix docstring).
_A_BOTRK = ("223153", "Blade of The Ruined King")  # 2500
_A_RUNAANS = ("223085", "Runaan's Hurricane")      # 2500
_A_KRAKEN = ("226672", "Kraken Slayer")            # 2500
_A_BOOTS = ("223006", "Berserker's Greaves")       # 500, Boots tag
_A_HAMSTRINGER = ("443069", "Hamstringer")         # 2750


def _ids(*items) -> list[str]:
    return [i for i, _ in items]


def _names(*items) -> list[str]:
    return [n for _, n in items]


# ---------------------------------------------------------------------------
# The primitive.
# ---------------------------------------------------------------------------

def test_trinket_and_potion_only_is_zero_legendaries():
    """THE reported defect shape. The raw slot count read this as 2."""
    held = (_TRINKET, _POTION)
    assert dc._owned_legendary_count(_ids(*held), _names(*held)) == 0


def test_one_two_three_real_legendaries():
    for n, expected in ((1, 1), (2, 2), (3, 3)):
        held = (_BOTRK, _RUNAANS, _TERMINUS)[:n] + (_TRINKET, _POTION)
        assert dc._owned_legendary_count(_ids(*held), _names(*held)) == expected


def test_boots_are_not_a_spike_item():
    """Boots + trinket + potion is a 0-item spike, not a 1-item spike.

    This is the assertion a build-progress count fails: boots sit at index 1 of
    171 of 173 balanced build orders."""
    held = (_BOOTS, _TRINKET, _POTION)
    assert dc._owned_legendary_count(_ids(*held), _names(*held)) == 0
    held2 = (_BOTRK, _BOOTS, _TRINKET, _POTION)
    assert dc._owned_legendary_count(_ids(*held2), _names(*held2)) == 1


def test_off_build_order_legendary_counts():
    """The semantics decision, pinned: a legendary that is NOT on the champion's
    recommended order still spikes, so the count is legendary-owned rather than
    build-progress. Rabadon's is nowhere in Kalista's order."""
    order = dc._load_build_orders("sr").get("Kalista", {}).get("balanced") or []
    assert _RABADONS[0] not in [str(i) for i in order], "fixture drift: pick another item"
    held = (_BOTRK, _RABADONS, _TRINKET, _POTION)
    assert dc._owned_legendary_count(_ids(*held), _names(*held)) == 2


def test_full_six_slot_build():
    """Boots + 5 legendaries in all six slots -> 5, not 6."""
    held = (_BOTRK, _BOOTS, _RUNAANS, _TERMINUS, _KRAKEN, _LDR)
    assert dc._owned_legendary_count(_ids(*held), _names(*held)) == 5


def test_empty_inventory_is_zero():
    assert dc._owned_legendary_count([], []) == 0
    assert dc._owned_legendary_count(None, None) == 0


def test_consumables_never_count():
    held = (_POTION, _POTION, _REFILL, _TRINKET)
    assert dc._owned_legendary_count(_ids(*held), _names(*held)) == 0


def test_name_fallback_when_ids_absent():
    """A coach payload can carry display names only."""
    held = (_BOTRK, _RUNAANS, _BOOTS, _TRINKET, _POTION)
    assert dc._owned_legendary_count(None, _names(*held)) == 2


def test_arena_alias_ids_count():
    """Arena inventories report 22-/44-prefixed alias ids."""
    held = (_A_BOTRK, _A_BOOTS, _A_RUNAANS, _POTION)
    assert dc._owned_legendary_count(_ids(*held), _names(*held)) == 2
    held2 = (_A_BOTRK, _A_RUNAANS, _A_KRAKEN, _A_HAMSTRINGER, _A_BOOTS)
    assert dc._owned_legendary_count(_ids(*held2), _names(*held2)) == 4


def test_unknown_ids_are_fail_soft():
    assert dc._owned_legendary_count(["999999", "", None], ["Nonsense Item"]) == 0
    assert dc._owned_legendary_count("not-a-list", 42) == 0


# ---------------------------------------------------------------------------
# The served path: what a user actually reads.
# ---------------------------------------------------------------------------

def _stub_laning(monkeypatch):
    monkeypatch.setattr(dc, "laning_choices", lambda gs, mode="SR", **kw: [])


def _spy_spike_count(monkeypatch) -> dict:
    """Capture the count the served callout generator receives."""
    real = dc.next_callouts
    seen: dict = {}

    def _spy(mode, gt, lvl, count, **kw):
        seen["count"] = count
        return real(mode, gt, lvl, count, **kw)

    monkeypatch.setattr(dc, "next_callouts", _spy)
    return seen


def _gs(*held, champ: str = "Kalista", level: int = 4) -> dict:
    return {
        "my_champion": champ,
        "game_time_s": 600.0,
        "level": level,
        "items": _names(*held),
        "my_item_ids": _ids(*held),
        "gold": 200,
        "enemy_comp": [],
        "enemy_item_ids": [],
        "ally_item_ids": [],
    }


def _active_spike_lines(out: dict) -> list[str]:
    return [str(c.get("line") or "") for c in (out.get("callouts") or [])
            if c.get("kind") == "item_spike" and c.get("eta_s") == 0.0]


def test_served_trinket_and_potion_only_emits_no_active_spike(monkeypatch):
    """RED before the fix: a "2-item spike - force fights now" fired at zero
    items. The three pending "Next spike N-item" rows are correct and stay."""
    _stub_laning(monkeypatch)
    seen = _spy_spike_count(monkeypatch)
    out = dc._compute_uncached(_gs(_TRINKET, _POTION), "sr")
    assert seen["count"] == 0
    assert _active_spike_lines(out) == []


def test_served_active_spike_matches_real_legendary_count(monkeypatch):
    _stub_laning(monkeypatch)
    expected = {
        1: "1-item spike - fight on cooldowns up",
        2: "2-item spike - force fights now",
        3: "3-item spike - your peak mid-game",
    }
    for n in (1, 2, 3):
        seen = _spy_spike_count(monkeypatch)
        held = (_BOTRK, _RUNAANS, _TERMINUS)[:n] + (_BOOTS, _TRINKET, _POTION)
        out = dc._compute_uncached(_gs(*held), "sr")
        assert seen["count"] == n, n
        assert expected[n] in _active_spike_lines(out), (n, out.get("callouts"))


def test_served_arena_counts_alias_ids(monkeypatch):
    """Arena is inside _KNOWN_MODES, so its spike rows are served too."""
    _stub_laning(monkeypatch)
    seen = _spy_spike_count(monkeypatch)
    out = dc._compute_uncached(
        _gs(_A_BOTRK, _A_RUNAANS, _A_BOOTS, _POTION), "arena")
    assert seen["count"] == 2
    assert "2-item spike - force fights now" in _active_spike_lines(out)


def test_served_aram_counts_legendaries(monkeypatch):
    _stub_laning(monkeypatch)
    seen = _spy_spike_count(monkeypatch)
    dc._compute_uncached(_gs(_BOTRK, _BOOTS, _TRINKET, _POTION), "aram")
    assert seen["count"] == 1


def test_served_full_build_drops_every_spike_row(monkeypatch):
    """5 legendaries is past the 3-item spike, so all three rows are dropped."""
    _stub_laning(monkeypatch)
    seen = _spy_spike_count(monkeypatch)
    out = dc._compute_uncached(
        _gs(_BOTRK, _BOOTS, _RUNAANS, _TERMINUS, _KRAKEN, _LDR), "sr")
    assert seen["count"] == 5
    assert [c for c in (out.get("callouts") or []) if c.get("kind") == "item_spike"] == []


def test_served_champion_without_a_build_order_still_counts(monkeypatch):
    """The spike count must not depend on a build-order row existing - that
    coupling is exactly what the build-progress count would have introduced."""
    _stub_laning(monkeypatch)
    seen = _spy_spike_count(monkeypatch)
    gs = _gs(_BOTRK, _RUNAANS, _TRINKET, champ="NotAChampionZZZ")
    dc._compute_uncached(gs, "sr")
    assert seen["count"] == 2


# ---------------------------------------------------------------------------
# Mode gating, measured rather than assumed.
# ---------------------------------------------------------------------------

def test_item_spike_rows_are_not_mode_gated():
    """core/event_callouts.py:965-966 emits the level + item spike rows outside
    every mode guard, so all three known modes carry them. Unlike the recall row
    (_RECALL_MODES == {"sr"}), this fix is user-visible in sr AND aram AND
    arena."""
    for mode in ("sr", "aram", "arena"):
        rows = [c for c in next_callouts(mode, 600.0, 4, 2, max_n=99)
                if c.get("kind") == "item_spike"]
        assert any(c.get("eta_s") == 0.0 for c in rows), mode
    assert next_callouts("tft", 600.0, 4, 2, max_n=99) == []
