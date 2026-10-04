"""Tests for ``core/live_item_tape.py`` - the RM-607 live inventory tape.

All fixtures are SYNTHETIC and name-scrubbed: players are ``TapeP<n>#TST``.
Item ids are real DDragon ids read from the tracked catalog
``data/meta/ddragon_items.json`` so the COMBINE recipe check is made against
the same ``from`` data RC ships, not a hand-written recipe table.

Covers the X-07 acceptance list (external reference C, behaviour only):
  * folded final inventory == last snapshot, all 10 players
  * every ITEM_COMBINED matches a DDragon ``from`` recipe
  * keying survives a reordered allPlayers list (never index)
  * consumable decrement + trinket swap typed as their own events
  * exclusions (Ornn masterwork, champion-specific, Arena / Mayhem grants)
  * buy-and-undo inside one tick is invisible (under-count, never invent)
"""
from __future__ import annotations

import ast
import random
from collections import Counter
from pathlib import Path

import pytest

from core import live_item_tape as lit

ROOT = Path(__file__).resolve().parent.parent

# Real DDragon ids used by the synthetic scripts (asserted present below).
LONG_SWORD, RUBY, PICKAXE, BF_SWORD, CLOAK = 1036, 1028, 1037, 1038, 1018
IE, PHAGE, KINDLEGEM, CLEAVER = 3031, 3044, 3067, 3071
BOOTS, DAGGER, BERSERKERS = 1001, 1042, 3006
SWIFTNESS, SWIFTMARCH = 3009, 3170
MANAMUNE, MURAMANA = 3004, 3042
POTION, CONTROL_WARD = 2003, 2055
STEALTH_TRINKET, FARSIGHT, ORACLE = 3340, 3363, 3364
DORAN_BLADE = 1055


@pytest.fixture(scope="module")
def catalog() -> lit.ItemCatalog:
    cat = lit.load_default_catalog()
    for iid in (LONG_SWORD, RUBY, PICKAXE, BF_SWORD, CLOAK, IE, PHAGE,
                KINDLEGEM, CLEAVER, BOOTS, DAGGER, BERSERKERS, SWIFTNESS,
                SWIFTMARCH, MANAMUNE, MURAMANA, POTION, CONTROL_WARD,
                STEALTH_TRINKET, FARSIGHT, ORACLE, DORAN_BLADE):
        assert cat.has(iid), f"catalog lost item {iid}"
    return cat


def _item(iid: int, count: int = 1, slot: int = 0) -> dict:
    return {"itemID": iid, "count": count, "slot": slot,
            "displayName": f"item{iid}"}


def _inv(ids: list, trinket: int | None = STEALTH_TRINKET) -> list:
    """Build a Live Client ``items`` list from ids (tuples = (id, count))."""
    out = []
    for n, x in enumerate(ids):
        iid, cnt = (x if isinstance(x, tuple) else (x, 1))
        out.append(_item(iid, cnt, slot=n))
    if trinket:
        out.append(_item(trinket, 1, slot=6))
    return out


def _player(n: int, items: list, team: str | None = None) -> dict:
    return {
        "riotIdGameName": f"TapeP{n}",
        "riotIdTagLine": "TST",
        "summonerName": f"TapeP{n}",
        "team": team or ("ORDER" if n < 5 else "CHAOS"),
        "items": items,
    }


# One shop script per player archetype: each entry is (inventory ids, trinket).
_SCRIPT_A = [
    ([DORAN_BLADE, (POTION, 3)], STEALTH_TRINKET),
    ([DORAN_BLADE, (POTION, 2)], STEALTH_TRINKET),          # potion used
    ([DORAN_BLADE, (POTION, 1), BF_SWORD], STEALTH_TRINKET),  # buy BF + potion used
    ([DORAN_BLADE, BF_SWORD, PICKAXE], STEALTH_TRINKET),      # last potion used
    ([DORAN_BLADE, IE], STEALTH_TRINKET),                    # combine IE
    ([DORAN_BLADE, IE, BOOTS], FARSIGHT),                    # boots + trinket swap
    ([DORAN_BLADE, IE, BERSERKERS], FARSIGHT),               # combine boots
    ([IE, BERSERKERS, LONG_SWORD], FARSIGHT),                # sell doran, buy sword
]
_SCRIPT_B = [
    ([LONG_SWORD, (POTION, 2)], STEALTH_TRINKET),
    ([LONG_SWORD, RUBY, (POTION, 2)], STEALTH_TRINKET),
    ([CLEAVER, (POTION, 2)], STEALTH_TRINKET),               # nested combine
    ([CLEAVER, (POTION, 2), (CONTROL_WARD, 2)], ORACLE),     # wards bought, swap
    ([CLEAVER, (POTION, 2), (CONTROL_WARD, 1)], ORACLE),     # ward placed
    ([CLEAVER, (POTION, 2), (CONTROL_WARD, 1), SWIFTNESS], ORACLE),
    ([CLEAVER, (POTION, 2), (CONTROL_WARD, 1), SWIFTMARCH], ORACLE),  # quest upgrade
    ([CLEAVER, (CONTROL_WARD, 1), SWIFTMARCH, MANAMUNE], ORACLE),     # sell potions
]
_SCRIPT_C = [
    ([MANAMUNE], STEALTH_TRINKET),
    ([MURAMANA], STEALTH_TRINKET),                           # transform
    ([MURAMANA, PICKAXE, CLOAK], STEALTH_TRINKET),
    ([MURAMANA, PICKAXE, CLOAK], STEALTH_TRINKET),           # no change
    ([MURAMANA, IE], STEALTH_TRINKET),                       # combine w/ 2 comps
    ([MURAMANA, IE, PHAGE], STEALTH_TRINKET),
    ([MURAMANA, IE], STEALTH_TRINKET),                       # sell phage
    ([MURAMANA, IE, (POTION, 4)], FARSIGHT),
]
_SCRIPTS = [_SCRIPT_A, _SCRIPT_B, _SCRIPT_C]


def _ticks(shuffle_seed: int | None = None) -> list[tuple[float, list]]:
    """10 players x 8 ticks; player n runs script n % 3 with a lag of n % 2."""
    rng = random.Random(shuffle_seed) if shuffle_seed is not None else None
    out = []
    for t in range(9):
        players = []
        for n in range(10):
            script = _SCRIPTS[n % 3]
            step = max(0, min(len(script) - 1, t - (n % 2)))
            ids, trinket = script[step]
            players.append(_player(n, _inv(ids, trinket)))
        if rng is not None:
            rng.shuffle(players)
        out.append((60.0 * (t + 1), players))
    return out


def _run(catalog, ticks) -> lit.LiveItemTape:
    tape = lit.LiveItemTape(catalog=catalog)
    for gt, players in ticks:
        tape.ingest(players, gt)
    return tape


def _counter_of(items: list) -> Counter:
    c: Counter = Counter()
    for it in items:
        c[int(it["itemID"])] += int(it.get("count") or 1)
    return c


# ---------------------------------------------------------------- acceptance

def test_fold_equals_last_snapshot_for_all_ten_players(catalog):
    ticks = _ticks(shuffle_seed=7)
    tape = _run(catalog, ticks)
    folded = lit.fold(tape.events)
    last = ticks[-1][1]
    assert len(folded) == 10
    for p in last:
        key = lit.player_key(p)
        assert folded[key] == _counter_of(p["items"]), key


def test_every_combine_matches_a_ddragon_from_recipe(catalog):
    tape = _run(catalog, _ticks(shuffle_seed=3))
    combines = [e for e in tape.events if e.event_type == lit.EV_COMBINED]
    assert combines, "script must exercise COMBINE"
    for ev in combines:
        assert catalog.recipe(ev.item_id), ev
        assert ev.components, ev
        closure = catalog.recipe_closure(ev.item_id)
        assert not (Counter(ev.components) - closure), (ev, closure)


def test_combine_types_are_exactly_the_scripted_ones(catalog):
    tape = _run(catalog, _ticks())
    got = Counter(e.item_id for e in tape.events if e.event_type == lit.EV_COMBINED)
    # IE (scripts A + C), Berserker's (A), Black Cleaver (B); players per script
    # n%3==0 -> 4 players (0,3,6,9), ==1 -> 3, ==2 -> 3.
    assert got == Counter({IE: 4 + 3, BERSERKERS: 4, CLEAVER: 3})


def test_keying_survives_a_reordered_all_players_list(catalog):
    plain = _run(catalog, _ticks())
    shuffled = _run(catalog, _ticks(shuffle_seed=11))
    assert sorted(plain.events) == sorted(shuffled.events)


def test_index_swap_never_cross_contaminates(catalog):
    a = _player(1, _inv([IE, BERSERKERS]))
    b = _player(2, _inv([CLEAVER, (POTION, 2)]))
    tape = lit.LiveItemTape(catalog=catalog)
    tape.ingest([a, b], 60.0)
    baseline = len(tape.events)
    new = tape.ingest([b, a], 61.0)          # same inventories, swapped slots
    assert new == []
    assert len(tape.events) == baseline


def test_same_name_other_team_is_a_different_player(catalog):
    a = _player(1, _inv([IE]), team="ORDER")
    b = _player(1, _inv([CLEAVER]), team="CHAOS")
    tape = lit.LiveItemTape(catalog=catalog)
    tape.ingest([a, b], 60.0)
    assert tape.ingest([b, a], 61.0) == []
    assert len({(e.player, e.team) for e in tape.events}) == 2


def test_player_key_prefers_riot_id_then_summoner_name():
    full = {"riotIdGameName": "TapeP1", "riotIdTagLine": "TST",
            "summonerName": "Other", "team": "ORDER"}
    assert lit.player_key(full) == ("TapeP1#TST", "ORDER")
    riot_id = {"riotId": "TapeP2#TST", "team": "CHAOS"}
    assert lit.player_key(riot_id) == ("TapeP2#TST", "CHAOS")
    legacy = {"summonerName": "TapeP3", "team": "CHAOS"}
    assert lit.player_key(legacy) == ("TapeP3", "CHAOS")
    assert lit.player_key({"team": "ORDER"}) is None
    assert lit.player_key({"riotIdGameName": 5, "team": "ORDER"}) is None
    # a bare participantId is NOT an identity
    assert lit.player_key({"participantId": 3, "team": "ORDER"}) is None


def test_duplicate_key_in_one_snapshot_is_skipped(catalog):
    a = _player(1, _inv([IE]))
    tape = lit.LiveItemTape(catalog=catalog)
    tape.ingest([a], 60.0)
    dup1 = _player(1, _inv([IE, LONG_SWORD]))
    dup2 = _player(1, _inv([]))
    assert tape.ingest([dup1, dup2], 61.0) == []


# ---------------------------------------------------------------- typing

def _two_ticks(catalog, before: list, after: list,
               t_before=STEALTH_TRINKET, t_after=STEALTH_TRINKET):
    tape = lit.LiveItemTape(catalog=catalog)
    tape.ingest([_player(1, _inv(before, t_before))], 100.0)
    return tape.ingest([_player(1, _inv(after, t_after))], 101.0)


def _types(evs) -> Counter:
    return Counter((e.event_type, e.item_id, e.count) for e in evs)


def test_consumable_decrement_is_its_own_type(catalog):
    evs = _two_ticks(catalog, [(POTION, 3)], [(POTION, 1)])
    assert _types(evs) == Counter({(lit.EV_CONSUMABLE_USED, POTION, 2): 1})


def test_consumable_purchase_carries_count(catalog):
    evs = _two_ticks(catalog, [], [(CONTROL_WARD, 2)])
    assert _types(evs) == Counter({(lit.EV_PURCHASED, CONTROL_WARD, 2): 1})


def test_trinket_swap_is_its_own_type(catalog):
    evs = _two_ticks(catalog, [IE], [IE], STEALTH_TRINKET, ORACLE)
    assert len(evs) == 1
    ev = evs[0]
    assert ev.event_type == lit.EV_TRINKET_SWAP
    assert ev.item_id == ORACLE and ev.components == (STEALTH_TRINKET,)


def test_plain_purchase_and_sale(catalog):
    evs = _two_ticks(catalog, [IE], [LONG_SWORD])
    assert _types(evs) == Counter({(lit.EV_PURCHASED, LONG_SWORD, 1): 1,
                                   (lit.EV_SOLD, IE, 1): 1})


def test_combine_consumes_components_and_emits_no_sale(catalog):
    evs = _two_ticks(catalog, [BF_SWORD, PICKAXE, DORAN_BLADE], [IE, DORAN_BLADE])
    assert len(evs) == 1
    assert evs[0].event_type == lit.EV_COMBINED
    assert sorted(evs[0].components) == sorted([BF_SWORD, PICKAXE])


def test_nested_combine_reaches_grandchild_components(catalog):
    evs = _two_ticks(catalog, [LONG_SWORD, RUBY], [CLEAVER])
    assert len(evs) == 1 and evs[0].event_type == lit.EV_COMBINED
    assert sorted(evs[0].components) == sorted([LONG_SWORD, RUBY])


def test_completed_item_with_no_owned_component_is_a_purchase(catalog):
    evs = _two_ticks(catalog, [DORAN_BLADE], [DORAN_BLADE, IE])
    assert _types(evs) == Counter({(lit.EV_PURCHASED, IE, 1): 1})


def test_special_recipe_transform_is_not_buy_or_sell(catalog):
    evs = _two_ticks(catalog, [MANAMUNE], [MURAMANA])
    assert [(e.event_type, e.item_id, e.components) for e in evs] == [
        (lit.EV_TRANSFORMED, MURAMANA, (MANAMUNE,))]


def test_free_quest_upgrade_is_a_transform(catalog):
    evs = _two_ticks(catalog, [SWIFTNESS], [SWIFTMARCH])
    assert [(e.event_type, e.item_id, e.components) for e in evs] == [
        (lit.EV_TRANSFORMED, SWIFTMARCH, (SWIFTNESS,))]


def test_buy_and_undo_inside_one_tick_is_invisible(catalog):
    # Documented under-count: the shop round-trip never reaches a snapshot.
    assert _two_ticks(catalog, [IE], [IE]) == []


def test_missing_items_field_emits_nothing(catalog):
    tape = lit.LiveItemTape(catalog=catalog)
    tape.ingest([_player(1, _inv([IE, CLEAVER]))], 60.0)
    torn = _player(1, [])
    del torn["items"]
    assert tape.ingest([torn], 61.0) == []
    # and the next good tick diffs against the last GOOD inventory
    assert tape.ingest([_player(1, _inv([IE, CLEAVER]))], 62.0) == []


def test_absent_player_keeps_state(catalog):
    tape = lit.LiveItemTape(catalog=catalog)
    tape.ingest([_player(1, _inv([IE])), _player(2, _inv([CLEAVER]))], 60.0)
    assert tape.ingest([_player(2, _inv([CLEAVER]))], 61.0) == []
    assert tape.ingest([_player(1, _inv([IE])), _player(2, _inv([CLEAVER]))], 62.0) == []


def test_game_time_rewind_starts_a_new_game(catalog):
    tape = lit.LiveItemTape(catalog=catalog)
    tape.ingest([_player(1, _inv([IE]))], 900.0)
    evs = tape.ingest([_player(1, _inv([DORAN_BLADE]))], 5.0)
    assert {e.event_type for e in evs} == {lit.EV_BASELINE}
    assert lit.fold(tape.events)[("TapeP1#TST", "ORDER")] == _counter_of(
        _inv([DORAN_BLADE]))


def test_clock_rewind_discards_the_previous_games_events(catalog):
    """A missed game end must never leak game A's items into game B's drain
    (verifier probe: A buys 1036 at 600 s, B buys 1055)."""
    tape = lit.LiveItemTape(catalog=catalog)
    tape.ingest([_player(1, _inv([]))], 500.0)
    tape.ingest([_player(1, _inv([LONG_SWORD]))], 600.0)       # game A buy
    tape.ingest([_player(1, _inv([]))], 10.0)                  # game B starts
    tape.ingest([_player(1, _inv([DORAN_BLADE]))], 20.0)       # game B buy
    drained = tape.drain()
    buys = [e.item_id for e in drained if e.event_type == lit.EV_PURCHASED]
    assert buys == [DORAN_BLADE]
    assert len({e.segment for e in drained}) == 1


def test_events_carry_their_game_segment(catalog):
    tape = lit.LiveItemTape(catalog=catalog)
    tape.ingest([_player(1, _inv([]))], 500.0)
    seg_a = tape.segment
    tape.ingest([_player(1, _inv([]))], 10.0)
    assert tape.segment == seg_a + 1
    assert {e.segment for e in tape.events} == {seg_a + 1}


def test_persisted_types_are_the_three_timeline_types():
    assert lit.PERSISTED_TYPES == frozenset(
        {"ITEM_PURCHASED", "ITEM_SOLD", "ITEM_COMBINED"})


# ---------------------------------------------------------------- exclusions

ORNN_WITCHCAP = 228002
KALISTA_SPEAR = 3599
ARENA_PRISMATIC = 443054
ANVIL_VOUCHER = 220008
ANATHEMA_ARENA_MIRROR = 228001   # 228xxx but a BUYABLE Arena mirror, not Ornn


def test_ornn_upgrade_is_a_grant_not_a_buy_and_sell(catalog):
    evs = _two_ticks(catalog, [IE, DORAN_BLADE], [ORNN_WITCHCAP, DORAN_BLADE])
    kinds = {e.event_type for e in evs}
    assert lit.EV_PURCHASED not in kinds and lit.EV_SOLD not in kinds
    assert (lit.EV_GRANTED, ORNN_WITCHCAP) in {(e.event_type, e.item_id) for e in evs}


@pytest.mark.parametrize("iid", [KALISTA_SPEAR, ARENA_PRISMATIC, ANVIL_VOUCHER,
                                 224403, 664403, 4403, 994403, 223069, 226668])
def test_grant_items_never_count_as_purchases(catalog, iid):
    evs = _two_ticks(catalog, [DORAN_BLADE], [DORAN_BLADE, iid])
    assert _types(evs) == Counter({(lit.EV_GRANTED, iid, 1): 1})
    evs = _two_ticks(catalog, [DORAN_BLADE, iid], [DORAN_BLADE])
    assert _types(evs) == Counter({(lit.EV_REMOVED, iid, 1): 1})


def test_buyable_arena_mirror_is_not_excluded(catalog):
    ex = lit.build_exclusions(catalog)
    assert ANATHEMA_ARENA_MIRROR not in ex
    assert IE not in ex and CLEAVER not in ex


def test_exclusion_sweep_covers_every_mirror_id_suffix(catalog):
    ex = lit.build_exclusions(catalog)
    # Seeds are swept by 4-digit id suffix across every map-mirror namespace.
    for seed in lit.GRANT_SEED_IDS:
        for iid in catalog.ids():
            if str(iid)[-4:] == str(seed)[-4:]:
                assert iid in ex, (seed, iid)


def _ds_frozenset(name: str) -> set[int]:
    tree = ast.parse((ROOT / "agents" / "daemon_slayer" / "rank.py").read_text(
        encoding="utf-8"))
    for node in ast.walk(tree):
        target = getattr(node, "target", None)
        if isinstance(node, ast.AnnAssign) and isinstance(target, ast.Name) \
                and target.id == name:
            call = node.value
            return {int(c.value) for c in call.args[0].elts}
    raise AssertionError(f"{name} not found in DS rank.py")


def test_seeds_cover_the_ds_grant_deny_lists():
    """Parity with the DS deny-lists (agents/daemon_slayer/rank.py) without
    importing the engine: parsed by AST so a DS addition fails here loudly."""
    for name in ("_NON_COACHABLE_ITEM_IDS", "_ARAM_EXCLUDED_ITEM_IDS",
                 "_ARENA_EXCLUDED_ITEM_IDS"):
        missing = _ds_frozenset(name) - set(lit.GRANT_SEED_IDS)
        assert not missing, (name, missing)
