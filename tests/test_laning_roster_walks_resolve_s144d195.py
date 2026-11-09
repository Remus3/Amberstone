"""Guard: every roster champion resolves a real laning walk (S144-D-195).

``generate_table``'s per-pair fail-soft drops a (my, enemy) pair only when the
engine RAISES. ``compute_matchup`` and the mana walk never raise, so a champion
the engine cannot model would be persisted as a junk pair (non-finite swing,
an unresolvable HP pool read as "fully removed", or a mana gate that never ran)
instead of being dropped.

Measured 2026-11-09 on snapshot 16.22.1 (173 champions, mirror matchups at
every generated band x cd state x mana state x SR / ARAM / ARENA): ZERO such
cells. The design question "should the fail-soft also drop an unresolved
pair" therefore has no reach today; this guard keeps that true, and fails
the moment a patch adds a champion whose walk resolves nothing, which is when
the question has to be answered.

A zero-damage combo is a different thing: it is a resolved walk whose spells
deal no damage at that level (Taric / Tryndamere / Twitch at L2 learn only
utility ranks; Aphelios's weapon kit deals 0 per cast in the burst walker,
and LEDGER 1213 lists him among the 0.0-damage-per-cast champions; root
cause measured in S144-D-196: Meraki ships his Q weapon forms and R with no
leveling payload at all, see
tests/test_ds_abilities_prose_only_damage_s144d196.py). It is
pinned as a ratchet: a NEW
zero-damage champion or band fails, a fixed one passes.
"""
from __future__ import annotations

import math

import pytest

from core import laning_scenario_precompute as lsp

MODES = ("SR", "ARAM", "ARENA")

# (champion, band) cells whose resolved combo deals 0 damage, measured at
# 16.22.1. Shrinking is fine; growing needs a measured reason.
KNOWN_ZERO_BURST = frozenset(
    {("Aphelios", band) for band in ("L2", "L6", "L11")}
    | {("Taric", "L2"), ("Tryndamere", "L2"), ("Twitch", "L2")}
)


@pytest.fixture(scope="module")
def snap():
    from agents.daemon_slayer.data_loader import DataSnapshot

    return DataSnapshot.load()


def _walks(snap):
    for champ in sorted(snap.champions):
        for band in lsp.GEN_BANDS:
            level = lsp.level_for_band(band)
            for mode in MODES:
                for mana in lsp.MANA_STATES:
                    for cd in lsp.CD_STATES:
                        seq, _manaless = lsp.derive_sequence(
                            snap, champ, level, mana, cd, mode=mode,
                        )
                        result = lsp._matchup(
                            snap, champ, champ, level, seq, cd, mode, (),
                        )
                        yield champ, band, mode, mana, cd, result


def test_every_roster_walk_resolves(snap):
    assert len(snap.champions) >= 170, len(snap.champions)
    assert tuple(lsp.GEN_BANDS), "no generated bands"
    junk = []
    seen = 0
    for champ, band, mode, mana, cd, r in _walks(snap):
        seen += 1
        why = [
            f for f in ("dmg_a_to_b", "a_hp_eff", "b_hp_eff", "net_swing",
                        "pct_a_removed", "pct_b_removed")
            if not math.isfinite(getattr(r, f))
        ]
        if r.a_hp_eff <= 0 or r.b_hp_eff <= 0:
            why.append("hp_eff<=0")
        if any("did not run" in n for n in r.notes):
            why.append("mana gate did not run")
        if r.verdict not in lsp.VALID_VERDICTS:
            why.append(f"verdict={r.verdict!r}")
        if why:
            junk.append((champ, band, mode, mana, cd, tuple(why)))
    assert seen >= 170 * len(lsp.GEN_BANDS) * len(MODES), seen
    assert junk == [], junk[:10]


def test_zero_damage_walks_stay_within_the_known_set(snap):
    zero = {
        (champ, band)
        for champ, band, _mode, _mana, _cd, r in _walks(snap)
        if r.dmg_a_to_b <= 0
    }
    assert zero <= KNOWN_ZERO_BURST, sorted(zero - KNOWN_ZERO_BURST)
