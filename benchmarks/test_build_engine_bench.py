"""CodSpeed performance benchmarks for the Riot Commander build engine.

These benchmarks exercise the pure-compute coaching paths that run several
times a second during a live match: enemy-comp analysis, item suggestion,
build resolution and the full purchase-advice entry point. They depend only
on the Python standard library plus the repo's local champion data, so they
run deterministically under CodSpeed's CPU simulation instrument.
"""
from __future__ import annotations

import composition_advisor as ca
import item_advisor as ia

# Representative live-match inputs: a mixed-damage enemy team, a typical ally
# comp, and a mid-game gold/items state. These mirror what the coaching loop
# feeds the engine on every tick.
ENEMY_COMP = ["Darius", "Garen", "Malphite", "Ahri", "Lux"]
ALLY_COMP = ["Thresh", "Lee Sin", "Orianna", "Jinx"]
CURRENT_ITEMS = ["Berserker's Greaves", "Kraken Slayer"]
GOLD = 3000
ADC_ROSTER = ["Jinx", "Vayne", "Tristana", "Caitlyn", "Nilah", "Miss Fortune"]


def test_enemy_damage_profile(benchmark):
    benchmark(ca.enemy_damage_profile, ENEMY_COMP)


def test_analyze_enemy_comp(benchmark):
    benchmark(ia.analyze_enemy_comp, ENEMY_COMP)


def test_suggest_items(benchmark):
    benchmark(
        ca.suggest_items,
        "Jinx",
        ENEMY_COMP,
        ALLY_COMP,
        CURRENT_ITEMS,
        GOLD,
    )


def test_comp_context_str(benchmark):
    benchmark(
        ca.comp_context_str,
        "Jinx",
        CURRENT_ITEMS,
        ENEMY_COMP,
        ALLY_COMP,
        [],
        "CLASSIC",
    )


def test_resolve_build(benchmark):
    benchmark(ia.resolve_build, "Jinx", ENEMY_COMP, CURRENT_ITEMS)


def test_get_purchase_advice(benchmark):
    benchmark(
        ia.get_purchase_advice,
        "Jinx",
        CURRENT_ITEMS,
        GOLD,
        ENEMY_COMP,
        ALLY_COMP,
    )


def test_purchase_advice_full_roster(benchmark):
    """Resolve purchase advice for every supported ADC against the same comp,
    approximating a champion-select sweep across the full carry roster."""

    def _sweep():
        out = []
        for champ in ADC_ROSTER:
            out.append(
                ia.get_purchase_advice(
                    champ,
                    CURRENT_ITEMS,
                    GOLD,
                    ENEMY_COMP,
                    ALLY_COMP,
                )
            )
        return out

    benchmark(_sweep)
