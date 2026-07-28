"""core.champion_info_overrides - curated DDragon info for zeroed champs.

DDragon serves an all-zero info block for Akshan/Rell/Seraphine/Vex and
attack=0 for the AD assassin Qiyana (verified upstream, not a local bug). The
overlay restores the correct AD/AP polarity, filling ONLY the fields DDragon
left zero so a future real value is respected.

COMPLETENESS GUARD (ZeroedChampionCoverageTests below)
------------------------------------------------------
The override dict alone pins nothing: a newly released champion - or a patch
that re-zeros an existing one - lands in data/meta/ddragon_champions.json and
is silently mis-classified. That is the exact operator-reported symptom that
created the module (Seraphine rendering "AD SUPPORT" off the 0>=0 tie,
2026-06-30). The module docstring asserts the four omissions are safe in PROSE;
prose is not a guard. So the universe here is DERIVED FROM THE DATA SIDE -
every mirror entry with a falsy info.attack or info.magic - never from
CHAMPION_INFO_OVERRIDES.keys(), which would be circular and would catch
nothing.

Live consumer polarity rules (source-read 2026-07-28, file:line):

  * dashboard/routes_dictionary.py:101
        return "AD" if attack >= magic else "AP"
    TIE -> "AD". Two things run BEFORE it: routes_dictionary.py:91-98
    short-circuits to "CC" / "BURST" for hardcoded name sets, and
    routes_dictionary.py:99-100 is a degraded fallback that discards the
    ratings entirely when BOTH are 0 and reads the role tags instead
    ("Marksman" -> AD, else AP).

  * dashboard/routes_pickban.py:255-260
        attack > magic -> "AD"; magic > attack -> "AP"; else "EVEN"
    TIE -> "EVEN". Fed by routes_pickban.py:218, which merges first.

  * core/build_planner/fed_threat.py:147-151
        attack > magic -> "ad"; magic > attack -> "ap"; else ""
    TIE -> "".

DIVERGENCE - the three do NOT agree on a tie. routes_dictionary silently
resolves attack == magic to "AD"; the other two return a neutral third state
("EVEN" / ""). That asymmetry IS the original bug shape: a zeroed champion hits
a tie and the dictionary chip confidently prints the wrong damage type while
the other two correctly report "unknown". The guard therefore demands STRICT
polarity (attack != magic post-merge) for every champion in the measured
universe - the intersection where all three consumers agree - and pins the
divergence explicitly in test_consumer_tie_rule_divergence_is_pinned so it
cannot drift unnoticed. The divergence is reported, not papered over.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import dashboard.routes_dictionary as _rd
import dashboard.routes_pickban as _rp
from core import champion_info_overrides as cio
from core import defensive_picks as _dp
from core.build_planner import fed_threat as _ft

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MIRROR_PATH = _REPO_ROOT / "data" / "meta" / "ddragon_champions.json"

# A name deliberately absent from routes_dictionary's hardcoded _HARD_CC_NAMES /
# _BURST_NAMES sets, so _damage_profile_tag falls through to the polarity branch
# at routes_dictionary.py:99-101 instead of short-circuiting to "CC" / "BURST".
_POLARITY_PROBE_NAME = "__rc_polarity_probe__"

# PINNED expectation for the DDragon-zeroed universe, measured off
# data/meta/ddragon_champions.json (173 champions, 2026-07-28).
#
#   name -> (expected axis, override_expected)
#
# override_expected=True  : the raw DDragon block is broken or ambiguous and the
#                           curated override MUST move the champion to its axis.
# override_expected=False : the raw block already resolves to the correct axis
#                           on its own, so omitting an override is provably safe
#                           (this is the module docstring's prose, made
#                           machine-checkable).
_EXPECTED_ZEROED_UNIVERSE: dict[str, tuple[str, bool]] = {
    # all-zero DDragon info block - no signal at all without the override
    "Akshan":    ("AD", True),   # AD marksman / assassin
    "Rell":      ("AP", True),   # AP tank support
    "Seraphine": ("AP", True),   # AP enchanter support
    "Vex":       ("AP", True),   # AP burst mage
    # attack=0 but a real magic=4 - reads AP without the override
    "Qiyana":    ("AD", True),   # AD assassin
    # magic=0 is a LEGIT rating for a pure-AD champion: already correct
    "Ambessa":   ("AD", False),
    "Naafiri":   ("AD", False),
    "Yunara":    ("AD", False),
    # attack=0 is a LEGIT rating for a pure-AP champion: already correct
    "Lillia":    ("AP", False),
}


def _load_mirror_entries() -> dict:
    """Parsed champion entries from the local DDragon mirror. Offline: a plain
    file read, no network and no RC server import chain."""
    raw = json.loads(_MIRROR_PATH.read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _zeroed_universe(entries: dict) -> dict[str, dict]:
    """DATA-SIDE universe: every champion whose DDragon info.attack or
    info.magic is falsy (0 / None / absent).

    Deriving this from CHAMPION_INFO_OVERRIDES.keys() would be circular - the
    dict would define its own completeness and a brand-new zeroed champion
    would be invisible. Takes the parsed entries as an argument precisely so a
    synthetic champion can be injected to prove the guard is not vacuous."""
    out: dict[str, dict] = {}
    for entry in (entries or {}).values():
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        info = entry.get("info") or {}
        if not isinstance(info, dict):
            info = {}
        if not info.get("attack") or not info.get("magic"):
            out[name] = {"info": info, "tags": list(entry.get("tags") or [])}
    return out


def _strict_axis(attack: object, magic: object) -> str:
    """"AD" / "AP" / "" using the STRICT rule - the intersection where all three
    live consumers agree (routes_dictionary.py:101, routes_pickban.py:255-260,
    fed_threat.py:147-151). "" means a tie, on which the three DIVERGE.

    This is the CONSUMER polarity rule, not a re-implementation of
    merged_info's fill rule (which is about WHICH fields get written)."""
    a = int(attack or 0)
    m = int(magic or 0)
    if a > m:
        return "AD"
    if m > a:
        return "AP"
    return ""


def _coverage_failures(universe: dict[str, dict],
                       pinned: dict[str, tuple[str, bool]]) -> list[str]:
    """Every reason the measured universe is not covered, each naming the
    champion and its info block. Shared by the real-data test and the synthetic
    negative cases, so the negatives exercise THIS code path - not a parallel
    re-implementation of it."""
    problems: list[str] = []
    for name in sorted(universe):
        info = universe[name]["info"]
        if name not in pinned:
            problems.append(
                f"UNPINNED zeroed champion {name!r} info={info!r} - DDragon left "
                f"attack or magic falsy and nothing on disk says what it should "
                f"classify as. Add it to _EXPECTED_ZEROED_UNIVERSE, and add a "
                f"CHAMPION_INFO_OVERRIDES entry unless the raw block already "
                f"resolves to the right axis."
            )
            continue
        expected_axis, _ = pinned[name]
        merged = cio.merged_info(name, info)
        actual = _strict_axis(merged.get("attack"), merged.get("magic"))
        if actual == "":
            problems.append(
                f"AMBIGUOUS zeroed champion {name!r} info={info!r} "
                f"merged={merged!r} - post-merge attack == magic, so "
                f"routes_dictionary.py:101 prints AD on the tie while "
                f"routes_pickban / fed_threat report EVEN / unknown. This is "
                f"the 2026-06-30 Seraphine bug shape."
            )
        elif actual != expected_axis:
            problems.append(
                f"MISCLASSIFIED zeroed champion {name!r} info={info!r} "
                f"merged={merged!r} - resolves {actual} but is pinned "
                f"{expected_axis}."
            )
    for name in sorted(pinned):
        if name not in universe:
            problems.append(
                f"STALE pin {name!r} - no longer has a falsy info.attack/magic "
                f"in the mirror. If DDragon populated it, drop the pin (and "
                f"probably the override)."
            )
    return problems


class MergedInfoTests(unittest.TestCase):
    def test_all_zero_champ_gets_full_override(self):
        # Seraphine (AP): 0/0 -> magic dominant.
        m = cio.merged_info("Seraphine", {"attack": 0, "magic": 0, "defense": 0})
        self.assertGreater(m["magic"], m["attack"], "Seraphine must read AP")

    def test_partial_zero_fills_missing_side_keeps_real(self):
        # Qiyana (AD assassin): DDragon attack=0, magic=4. Fill attack only;
        # keep the real magic=4. Result must lean AD (attack >= magic).
        m = cio.merged_info("Qiyana", {"attack": 0, "magic": 4, "defense": 2})
        self.assertEqual(m["magic"], 4, "real DDragon magic preserved")
        self.assertGreaterEqual(m["attack"], m["magic"], "Qiyana must read AD")

    def test_non_zero_ddragon_value_not_clobbered(self):
        # If DDragon later populates a real attack, the override must NOT win.
        m = cio.merged_info("Seraphine", {"attack": 5, "magic": 8})
        self.assertEqual(m["attack"], 5, "real DDragon attack preserved over override")

    def test_unlisted_champ_passthrough(self):
        raw = {"attack": 7, "magic": 6}
        self.assertEqual(cio.merged_info("Ezreal", raw), raw)

    def test_non_dict_raw_is_safe(self):
        self.assertEqual(cio.merged_info("Seraphine", None).get("magic"), 8)

    def test_does_not_mutate_input(self):
        raw = {"attack": 0, "magic": 0}
        cio.merged_info("Vex", raw)
        self.assertEqual(raw, {"attack": 0, "magic": 0}, "input dict untouched")

    def test_ad_overrides_lean_ad(self):
        for name in ("Akshan", "Qiyana"):
            m = cio.merged_info(name, {"attack": 0, "magic": 0})
            self.assertGreaterEqual(m["attack"], m["magic"], f"{name} must read AD")

    def test_ap_overrides_lean_ap(self):
        for name in ("Seraphine", "Rell", "Vex"):
            m = cio.merged_info(name, {"attack": 0, "magic": 0})
            self.assertGreater(m["magic"], m["attack"], f"{name} must read AP")


class ZeroedChampionCoverageTests(unittest.TestCase):
    """Data-driven completeness guard over the DDragon-zeroed population.

    Pins the population in BOTH directions: a new zeroed champion with no
    override fails loudly and by name, and a stale pin whose DDragon block got
    fixed upstream fails too. See the module docstring for the three consumer
    polarity rules and the tie-rule divergence between them."""

    def setUp(self):
        # No skip here on purpose. The mirror is TRACKED, so a checkout always
        # has it and an absent one is a broken tree, not an absent capability -
        # skipping would make this whole guard always-pass exactly when the data
        # it guards went missing (the B5 masking class, ROADMAP RM-119 audit).
        self.assertTrue(
            _MIRROR_PATH.is_file(),
            f"tracked DDragon mirror missing: {_MIRROR_PATH}")
        self.entries = _load_mirror_entries()
        self.universe = _zeroed_universe(self.entries)

    # -- population pin ---------------------------------------------------

    def test_zeroed_universe_is_fully_covered(self):
        """Every DDragon-zeroed champion is pinned AND post-merge correct."""
        problems = _coverage_failures(self.universe, _EXPECTED_ZEROED_UNIVERSE)
        self.assertEqual(
            problems, [],
            "DDragon-zeroed champion coverage broke:\n  - "
            + "\n  - ".join(problems))

    def test_universe_is_derived_from_the_data_not_the_override_dict(self):
        """Anti-circularity: the measured universe must be strictly larger than
        the override dict, proving it is not enumerated from the consumer
        side (memory: a guard deriving its universe from the consumer side is
        circular and catches nothing)."""
        override_names = set(cio.CHAMPION_INFO_OVERRIDES)
        self.assertTrue(
            override_names < set(self.universe),
            f"override keys {sorted(override_names)!r} are not a strict subset "
            f"of the measured zeroed universe {sorted(self.universe)!r}")

    # -- per-champion correctness through the REAL consumers --------------

    def test_every_zeroed_champion_resolves_unambiguously(self):
        """Post-merge attack != magic for every zeroed champion.

        A tie is the 2026-06-30 bug shape: routes_dictionary.py:101 turns
        0 >= 0 into a confident "AD" while routes_pickban.py:255-260 and
        fed_threat.py:147-151 correctly report EVEN / unknown. Needs no pin, so
        it fires even for a champion nobody has pinned yet."""
        for name, row in sorted(self.universe.items()):
            with self.subTest(champion=name):
                merged = cio.merged_info(name, row["info"])
                self.assertNotEqual(
                    _strict_axis(merged.get("attack"), merged.get("magic")), "",
                    f"{name} ties post-merge: info={row['info']!r} merged={merged!r}")

    def test_dictionary_consumer_reports_pinned_axis(self):
        """Real dashboard.routes_dictionary._damage_profile_tag, polarity branch
        (routes_dictionary.py:99-101). Probed under a sentinel name so the
        hardcoded CC / BURST short-circuit at routes_dictionary.py:91-98 (which
        legitimately wins for Lillia / Naafiri / Rell / Vex) cannot mask the
        polarity decision under test."""
        for name, (expected_axis, _) in sorted(_EXPECTED_ZEROED_UNIVERSE.items()):
            row = self.universe.get(name)
            if row is None:
                continue  # stale pin - reported by test_zeroed_universe_is_fully_covered
            with self.subTest(champion=name):
                merged = cio.merged_info(name, row["info"])
                tag = _rd._damage_profile_tag(
                    _POLARITY_PROBE_NAME, row["tags"],
                    int(merged.get("attack") or 0), int(merged.get("magic") or 0))
                self.assertEqual(
                    tag, expected_axis,
                    f"{name} renders {tag} in the dictionary chip")

    def test_pickban_consumer_reports_pinned_axis(self):
        """Real dashboard.routes_pickban._compute_team_damage_mix end to end -
        it does its own merged_info() call at routes_pickban.py:218 and applies
        the lean rule at routes_pickban.py:255-260."""
        for name, (expected_axis, _) in sorted(_EXPECTED_ZEROED_UNIVERSE.items()):
            entry = next((e for e in self.entries.values()
                          if isinstance(e, dict) and e.get("name") == name), None)
            if entry is None or not entry.get("key"):
                continue
            with self.subTest(champion=name):
                mix = _rp._compute_team_damage_mix((int(entry["key"]),))
                per_champ = mix.get("per_champ") or []
                self.assertEqual(len(per_champ), 1, f"{name} missing from the mix")
                self.assertEqual(
                    per_champ[0]["lean"], expected_axis,
                    f"{name} leans {per_champ[0]['lean']} in the team damage mix")

    def test_fed_threat_consumer_reports_pinned_axis(self):
        """Real core.build_planner.fed_threat._champ_axis end to end
        (fed_threat.py:139-151)."""
        for name, (expected_axis, _) in sorted(_EXPECTED_ZEROED_UNIVERSE.items()):
            if name not in self.universe:
                continue
            with self.subTest(champion=name):
                actual = _ft._champ_axis(name)
                self.assertEqual(actual, expected_axis.lower(),
                                 f"{name} axis {actual!r}")

    # -- override necessity, both directions ------------------------------

    def test_override_entries_are_load_bearing(self):
        """A pinned champion marked override_expected=True must (a) have an
        override entry and (b) be WRONG or ambiguous without it - otherwise the
        entry is dead weight and the pin is lying."""
        for name, (expected_axis, needs_override) in sorted(_EXPECTED_ZEROED_UNIVERSE.items()):
            if not needs_override or name not in self.universe:
                continue
            with self.subTest(champion=name):
                info = self.universe[name]["info"]
                self.assertIn(
                    name, cio.CHAMPION_INFO_OVERRIDES,
                    f"{name} is pinned as needing an override but has none")
                raw_axis = _strict_axis(info.get("attack"), info.get("magic"))
                self.assertNotEqual(
                    raw_axis, expected_axis,
                    f"{name} already resolves {expected_axis} from raw DDragon "
                    f"{info!r} - the override is dead weight, flip its pin to "
                    f"override_expected=False")
                merged = cio.merged_info(name, info)
                self.assertEqual(
                    _strict_axis(merged.get("attack"), merged.get("magic")),
                    expected_axis,
                    f"{name} override does not move it to {expected_axis} "
                    f"(merged={merged!r})")

    def test_omitted_zeroed_champions_are_already_correct(self):
        """The module docstring claims Ambessa / Naafiri / Yunara / Lillia are
        safe to omit because their zero is a LEGIT rating. Prose is not a
        guard - assert it against the mirror."""
        for name, (expected_axis, needs_override) in sorted(_EXPECTED_ZEROED_UNIVERSE.items()):
            if needs_override or name not in self.universe:
                continue
            with self.subTest(champion=name):
                self.assertNotIn(
                    name, cio.CHAMPION_INFO_OVERRIDES,
                    f"{name} is pinned as needing no override but has one")
                info = self.universe[name]["info"]
                self.assertEqual(
                    _strict_axis(info.get("attack"), info.get("magic")), expected_axis,
                    f"{name} omission is NOT safe: raw {info!r} does not "
                    f"resolve {expected_axis}")

    # -- tie-rule divergence, pinned not papered over ---------------------

    def test_consumer_tie_rule_divergence_is_pinned(self):
        """The three consumers DISAGREE on attack == magic. Pinned so the
        divergence is a tracked fact: if anyone aligns them, this fails and the
        module docstring gets corrected in the same slice."""
        self.assertEqual(
            _rd._damage_profile_tag(_POLARITY_PROBE_NAME, ["Mage"], 5, 5), "AD",
            "routes_dictionary.py:101 no longer resolves a tie to AD")
        prev = _rp._CHAMP_ID_TO_INFO
        try:
            _rp._CHAMP_ID_TO_INFO = {999001: (5, 5)}
            mix = _rp._compute_team_damage_mix((999001,))
            self.assertEqual(mix["per_champ"][0]["lean"], "EVEN",
                             "routes_pickban.py:255-260 no longer reports EVEN on a tie")
        finally:
            _rp._CHAMP_ID_TO_INFO = prev
        prev_info = _dp._CHAMP_INFO
        try:
            _dp._CHAMP_INFO = {"__rc_tie_probe__": {"attack": 5, "magic": 5,
                                                    "defense": 0, "difficulty": 0,
                                                    "tags": []}}
            self.assertEqual(_ft._champ_axis("__rc_tie_probe__"), "",
                             "fed_threat.py:147-151 no longer reports unknown on a tie")
        finally:
            _dp._CHAMP_INFO = prev_info

    # -- teeth: synthetic negatives (the guard must not be vacuous) -------

    def test_guard_rejects_synthetic_unpinned_all_zero_champion(self):
        """A brand-new champion arriving with an all-zero DDragon block and no
        override must be caught BY NAME. Injected into the parsed mirror, not
        written to disk."""
        injected = dict(self.entries)
        injected["Zzsynthetic"] = {
            "name": "Zzsynthetic", "key": "999002",
            "info": {"attack": 0, "magic": 0, "defense": 0, "difficulty": 0},
            "tags": ["Mage"],
        }
        universe = _zeroed_universe(injected)
        self.assertIn("Zzsynthetic", universe, "data-side universe missed the new champ")
        problems = _coverage_failures(universe, _EXPECTED_ZEROED_UNIVERSE)
        self.assertTrue(
            any("Zzsynthetic" in p and "UNPINNED" in p for p in problems),
            f"guard is vacuous - it accepted an unpinned 0/0 champion: {problems!r}")

    def test_guard_rejects_synthetic_pinned_champion_with_wrong_polarity(self):
        """A pinned AD champion whose block resolves AP (the Qiyana shape:
        attack zeroed, magic real) must be caught even though it is pinned and
        never ties."""
        injected = dict(self.entries)
        injected["Zzwrongaxis"] = {
            "name": "Zzwrongaxis", "key": "999003",
            "info": {"attack": 0, "magic": 5, "defense": 2, "difficulty": 5},
            "tags": ["Assassin"],
        }
        pinned = dict(_EXPECTED_ZEROED_UNIVERSE, Zzwrongaxis=("AD", True))
        problems = _coverage_failures(_zeroed_universe(injected), pinned)
        self.assertTrue(
            any("Zzwrongaxis" in p and "MISCLASSIFIED" in p for p in problems),
            f"guard is vacuous - it accepted a mis-classified champion: {problems!r}")

    def test_guard_rejects_synthetic_pinned_champion_that_ties(self):
        """A pinned champion whose block ties post-merge (no override to break
        it) must be caught as AMBIGUOUS - the original Seraphine shape."""
        injected = dict(self.entries)
        injected["Zztied"] = {
            "name": "Zztied", "key": "999004",
            "info": {"attack": 0, "magic": 0, "defense": 0, "difficulty": 0},
            "tags": ["Support"],
        }
        pinned = dict(_EXPECTED_ZEROED_UNIVERSE, Zztied=("AP", True))
        problems = _coverage_failures(_zeroed_universe(injected), pinned)
        self.assertTrue(
            any("Zztied" in p and "AMBIGUOUS" in p for p in problems),
            f"guard is vacuous - it accepted a tied champion: {problems!r}")

    def test_guard_rejects_stale_pin_when_ddragon_populates_the_block(self):
        """The other direction: DDragon fixes a block upstream, so the champion
        leaves the zeroed universe and its pin (and override) go stale."""
        problems = _coverage_failures(
            {n: r for n, r in self.universe.items() if n != "Seraphine"},
            _EXPECTED_ZEROED_UNIVERSE)
        self.assertTrue(
            any("Seraphine" in p and "STALE" in p for p in problems),
            f"guard is vacuous - it accepted a stale pin: {problems!r}")

    def test_real_consumers_degrade_on_a_synthetic_zeroed_champion(self):
        """End-to-end teeth: an un-overridden 0/0 champion really does produce
        an unusable axis in the two consumers that carry a neutral state, which
        is why the coverage guard above has to exist."""
        prev = _rp._CHAMP_ID_TO_INFO
        try:
            _rp._CHAMP_ID_TO_INFO = {999005: (0, 0)}
            mix = _rp._compute_team_damage_mix((999005,))
            self.assertEqual(mix["per_champ"][0]["lean"], "EVEN")
            self.assertEqual(mix["physical_pct"], 0)
        finally:
            _rp._CHAMP_ID_TO_INFO = prev
        prev_info = _dp._CHAMP_INFO
        try:
            _dp._CHAMP_INFO = {"__rc_zero_probe__": {"attack": 0, "magic": 0,
                                                     "defense": 0, "difficulty": 0,
                                                     "tags": ["Mage"]}}
            self.assertEqual(_ft._champ_axis("__rc_zero_probe__"), "")
        finally:
            _dp._CHAMP_INFO = prev_info


if __name__ == "__main__":
    unittest.main()
