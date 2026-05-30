"""cooldown_watch - matchup cooldown-watch join (competitor lift #5).

Engine-layer JOIN of the CC threat registries (_PER_SPELL_CC_DURATIONS +
cc_conditional) to per-rank ability cooldowns from
champion_abilities.json. NO new compute / NO ENGINE math change - this
module is read-only over two existing registries. Spec:
docs/COMPETITOR_LIFT_2026-05-30.md "Lift 5".

Pinned values grounded against the live patch 16.11.1 dump at write time:
  * Blitzcrank Q Rocket Grab   - uncond stun 1.0s   - cd [20,19,18,17,16]
  * Leona R Solar Flare        - uncond stun 1.5s   - cd [90,75,60]
  * Aatrox W Infernal Chains   - COND root 1.75s    - cd [20,18,16,14,12]
  * Thresh Q Death Sentence    - uncond 1.5s        - cd [19,16.5,14,11.5,9]
  * Morgana Q Dark Binding     - uncond root 3.0s   - cd [10,10,10,10,10]
  * Lux Q Light Binding        - uncond root 3.0s   - cd [11,10.5,10,9.5,9]

Test surface:
* ContractTests       - dataclass shapes (frozen, field names, defaults).
* HeadlineTests       - per-champion highest-threat join (the 6 grounded).
* RankingTests        - sort DESC by CC duration, top_n, deterministic tie.
* FailSoftTests       - unknown / blank / None / no-CC / missing-cooldown.
* DedupTests          - duplicate roster entry collapses to one card.
* AsciiHygieneTest    - module is pure 7-bit ASCII.
"""

from __future__ import annotations

import dataclasses
import pathlib
import unittest

from agents.daemon_slayer import cooldown_watch as cw
from agents.daemon_slayer.cooldown_watch import (
    CooldownWatchCard,
    CooldownWatchResult,
    compute_cooldown_watch,
)


def _card_for(roster, champ):
    res = compute_cooldown_watch(roster, top_n=99)
    for c in res.cards:
        if c.champion == champ:
            return c
    return None


class ContractTests(unittest.TestCase):
    def test_card_is_frozen(self):
        c = CooldownWatchCard(
            champion="Blitzcrank", spell_key="Q", spell_name="Rocket Grab",
            cc_kind="", cc_duration_s=1.0, cooldown_s=16.0,
            cooldown_by_rank=(20.0, 16.0), conditional=False, probability=1.0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            c.cooldown_s = 5.0  # type: ignore[misc]

    def test_card_field_names(self):
        names = {f.name for f in dataclasses.fields(CooldownWatchCard)}
        self.assertEqual(
            names,
            {
                "champion", "spell_key", "spell_name", "cc_kind",
                "cc_duration_s", "cooldown_s", "cooldown_by_rank",
                "conditional", "probability",
            },
        )

    def test_result_default_empty(self):
        self.assertEqual(CooldownWatchResult().cards, ())


class HeadlineTests(unittest.TestCase):
    def test_blitzcrank_q_rocket_grab(self):
        c = _card_for(["Blitzcrank"], "Blitzcrank")
        self.assertIsNotNone(c)
        self.assertEqual(c.spell_key, "Q")
        self.assertEqual(c.spell_name, "Rocket Grab")
        self.assertAlmostEqual(c.cc_duration_s, 1.0)
        self.assertAlmostEqual(c.cooldown_s, 16.0)
        self.assertEqual(c.cooldown_by_rank, (20.0, 19.0, 18.0, 17.0, 16.0))
        self.assertFalse(c.conditional)
        self.assertAlmostEqual(c.probability, 1.0)

    def test_leona_headline_is_r_not_q(self):
        # Leona Q 1.25 / E 0.5 / R 1.5 -> R is the longest -> headline.
        c = _card_for(["Leona"], "Leona")
        self.assertEqual(c.spell_key, "R")
        self.assertEqual(c.spell_name, "Solar Flare")
        self.assertAlmostEqual(c.cc_duration_s, 1.5)
        self.assertAlmostEqual(c.cooldown_s, 60.0)
        self.assertEqual(c.cooldown_by_rank, (90.0, 75.0, 60.0))

    def test_aatrox_conditional_w_root(self):
        # Aatrox has NO unconditional CC; conditional Q knockup 0.5 +
        # W root 1.75 -> W is the headline (longest), flagged conditional.
        c = _card_for(["Aatrox"], "Aatrox")
        self.assertEqual(c.spell_key, "W")
        self.assertEqual(c.spell_name, "Infernal Chains")
        self.assertAlmostEqual(c.cc_duration_s, 1.75)
        self.assertAlmostEqual(c.cooldown_s, 12.0)
        self.assertEqual(c.cooldown_by_rank, (20.0, 18.0, 16.0, 14.0, 12.0))
        self.assertTrue(c.conditional)
        self.assertEqual(c.cc_kind, "root")
        self.assertAlmostEqual(c.probability, 0.5)

    def test_thresh_q_death_sentence(self):
        c = _card_for(["Thresh"], "Thresh")
        self.assertEqual(c.spell_key, "Q")
        self.assertEqual(c.spell_name, "Death Sentence")
        self.assertAlmostEqual(c.cc_duration_s, 1.5)
        self.assertAlmostEqual(c.cooldown_s, 9.0)

    def test_morgana_uncond_q_beats_cond_r(self):
        # Q uncond max-rank 3.0 > R cond 2.0 -> Q headline, unconditional.
        c = _card_for(["Morgana"], "Morgana")
        self.assertEqual(c.spell_key, "Q")
        self.assertEqual(c.spell_name, "Dark Binding")
        self.assertAlmostEqual(c.cc_duration_s, 3.0)
        self.assertAlmostEqual(c.cooldown_s, 10.0)
        self.assertFalse(c.conditional)

    def test_lux_q_light_binding(self):
        c = _card_for(["Lux"], "Lux")
        self.assertEqual(c.spell_key, "Q")
        self.assertEqual(c.spell_name, "Light Binding")
        self.assertAlmostEqual(c.cc_duration_s, 3.0)
        self.assertAlmostEqual(c.cooldown_s, 9.0)


class RankingTests(unittest.TestCase):
    def test_sorted_by_cc_duration_desc(self):
        roster = ["Blitzcrank", "Leona", "Aatrox", "Lux"]
        res = compute_cooldown_watch(roster, top_n=99)
        order = [c.champion for c in res.cards]
        # Lux 3.0 > Aatrox 1.75 > Leona 1.5 > Blitzcrank 1.0
        self.assertEqual(order, ["Lux", "Aatrox", "Leona", "Blitzcrank"])

    def test_top_n_truncates(self):
        roster = ["Blitzcrank", "Leona", "Aatrox", "Lux"]
        res = compute_cooldown_watch(roster, top_n=2)
        self.assertEqual([c.champion for c in res.cards], ["Lux", "Aatrox"])

    def test_duration_tie_breaks_by_lower_cooldown(self):
        # Lux Q 3.0 (cd 9.0) vs Morgana Q 3.0 (cd 10.0): lower cd first.
        res = compute_cooldown_watch(["Morgana", "Lux"], top_n=99)
        self.assertEqual([c.champion for c in res.cards], ["Lux", "Morgana"])

    def test_negative_top_n_returns_all(self):
        roster = ["Blitzcrank", "Leona", "Aatrox", "Lux"]
        res = compute_cooldown_watch(roster, top_n=-1)
        self.assertEqual(len(res.cards), 4)


class FailSoftTests(unittest.TestCase):
    def test_empty_roster(self):
        self.assertEqual(compute_cooldown_watch([]).cards, ())

    def test_none_roster(self):
        self.assertEqual(compute_cooldown_watch(None).cards, ())  # type: ignore[arg-type]

    def test_unknown_champ_skipped(self):
        self.assertEqual(compute_cooldown_watch(["NotAChampion"]).cards, ())

    def test_blank_and_none_entries_skipped(self):
        res = compute_cooldown_watch(["", None, "  ", "Blitzcrank"], top_n=99)
        self.assertEqual([c.champion for c in res.cards], ["Blitzcrank"])

    def test_champ_with_no_cc_skipped(self):
        # A pure-mage with no first-order CC registered (Veigar Q/W/E are
        # damage; only E Event Horizon stun is registered? guard against
        # picking a champ that DOES have CC). Use a known no-CC carry.
        res = compute_cooldown_watch(["Kaisa"], top_n=99)
        self.assertEqual(res.cards, ())

    def test_missing_cooldown_still_emits_card(self):
        # Monkeypatch the abilities map empty -> threat still surfaces,
        # cooldown degenerates to 0.0 + empty tuple.
        orig = cw._ABILITIES
        try:
            cw._ABILITIES = {}
            c = _card_for(["Blitzcrank"], "Blitzcrank")
            self.assertIsNotNone(c)
            self.assertEqual(c.spell_key, "Q")
            self.assertAlmostEqual(c.cc_duration_s, 1.0)
            self.assertAlmostEqual(c.cooldown_s, 0.0)
            self.assertEqual(c.cooldown_by_rank, ())
            self.assertEqual(c.spell_name, "")
        finally:
            cw._ABILITIES = orig


class DedupTests(unittest.TestCase):
    def test_duplicate_roster_entry_single_card(self):
        res = compute_cooldown_watch(["Leona", "Leona"], top_n=99)
        self.assertEqual(len(res.cards), 1)
        self.assertEqual(res.cards[0].champion, "Leona")


class AsciiHygieneTest(unittest.TestCase):
    def test_module_is_ascii(self):
        src = pathlib.Path(cw.__file__).read_bytes()
        nonascii = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(nonascii, [], f"non-ASCII bytes: {nonascii[:5]}")


if __name__ == "__main__":
    unittest.main()
