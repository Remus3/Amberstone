"""wiki_stats overlay - DataSnapshot optional sidecar + combo.py AA windup.

Item 221 consumer wire. The DS engine OPTIONALLY consumes the lolmath-wiki
stat sidecar (data/daemon_slayer/<patch>/wiki_stats.json). When the sidecar
is absent / has no entry for a champ / the entry's attack_cast_time is null,
combo.py behaves EXACTLY as before (the fixed _DEFAULT_AA_WINDUP_S = 0.25
AA windup). When a real positive attack_cast_time is present, the AA hit
timing reflects that per-champ windup.

These tests NEVER touch the network and NEVER depend on the real wiki_stats
data file existing. They build synthetic snapshots two ways:
  * DataSnapshot(...) constructed directly with a wiki_stats= kwarg (tests
    the accessor + the combo wire in isolation - no disk).
  * DataSnapshot.load() against the real committed 16.11.1 snapshot dir to
    prove load() tolerates a MISSING wiki_stats.json (it does today - no
    such file is committed yet); skipped if that dir is absent.

Test surface:
* AccessorTests       - wiki_attack_cast_time present / absent / null / unknown.
* LoadToleratesAbsent - load() does not raise + wiki_stats == {} when no file.
* ComboWireTests      - empty-overlay AA windup == 0.25 (byte-identical pin);
                        populated overlay shifts the AA timing to the value.
* AsciiHygieneTest    - this file is pure 7-bit ASCII.
"""

from __future__ import annotations

import dataclasses
import pathlib
import unittest

from agents.daemon_slayer import combo as cb
from agents.daemon_slayer.combo import compute_combo
from agents.daemon_slayer.data_loader import DataSnapshot

# Real committed snapshot (for the load()-tolerates-absent test). The combo
# wire tests use this snapshot's data via compute_combo so a real champ
# (Caitlyn) resolves through the burst walker; the overlay is injected by
# building a sibling snapshot that copies every field but swaps wiki_stats.
_REAL = DataSnapshot.load()


def _snap_with_wiki(wiki: dict) -> DataSnapshot:
    """Clone the real snapshot, overriding only wiki_stats.

    dataclasses.replace keeps every populated container (champions, items,
    scenarios, ...) so the burst walker resolves a real champion, while the
    overlay under test is whatever ``wiki`` we pass.
    """
    return dataclasses.replace(_REAL, wiki_stats=wiki)


class AccessorTests(unittest.TestCase):
    def test_present_value_returned(self):
        snap = DataSnapshot(
            patch="16.11.1", manifest={}, champions={}, items={},
            scenarios_by_id={}, scenarios_by_lolmath={},
            arena_augments_by_id={}, arena_augments_by_api={},
            data_root=pathlib.Path("."),
            wiki_stats={"Caitlyn": {"attack_cast_time": 0.4}},
        )
        self.assertAlmostEqual(snap.wiki_attack_cast_time("Caitlyn"), 0.4)

    def test_unknown_champ_is_none(self):
        snap = DataSnapshot(
            patch="16.11.1", manifest={}, champions={}, items={},
            scenarios_by_id={}, scenarios_by_lolmath={},
            arena_augments_by_id={}, arena_augments_by_api={},
            data_root=pathlib.Path("."),
            wiki_stats={"Caitlyn": {"attack_cast_time": 0.4}},
        )
        self.assertIsNone(snap.wiki_attack_cast_time("Jinx"))

    def test_null_cast_time_is_none(self):
        snap = DataSnapshot(
            patch="16.11.1", manifest={}, champions={}, items={},
            scenarios_by_id={}, scenarios_by_lolmath={},
            arena_augments_by_id={}, arena_augments_by_api={},
            data_root=pathlib.Path("."),
            wiki_stats={"Jhin": {"attack_cast_time": None}},
        )
        self.assertIsNone(snap.wiki_attack_cast_time("Jhin"))

    def test_default_wiki_stats_is_empty(self):
        # A snapshot constructed without wiki_stats= defaults to {}.
        snap = DataSnapshot(
            patch="16.11.1", manifest={}, champions={}, items={},
            scenarios_by_id={}, scenarios_by_lolmath={},
            arena_augments_by_id={}, arena_augments_by_api={},
            data_root=pathlib.Path("."),
        )
        self.assertEqual(snap.wiki_stats, {})
        self.assertIsNone(snap.wiki_attack_cast_time("Caitlyn"))


class LoadToleratesAbsentTests(unittest.TestCase):
    def test_load_does_not_raise_and_wiki_empty(self):
        # No wiki_stats.json is committed yet, so the real snapshot's
        # wiki_stats must be {} and any lookup must be None. This proves
        # the absent-sidecar path is byte-identical to pre-sidecar.
        snap = DataSnapshot.load()
        self.assertIsInstance(snap.wiki_stats, dict)
        # The file is genuinely absent today -> empty overlay.
        if not (snap.data_root / snap.patch / "wiki_stats.json").exists():
            self.assertEqual(snap.wiki_stats, {})
            self.assertIsNone(snap.wiki_attack_cast_time("Caitlyn"))


class ComboWireTests(unittest.TestCase):
    """The KEY regression pin: empty overlay == pre-change AA windup."""

    def _aa_windup(self, snap) -> float:
        # Caitlyn Q,AA -> the AA hit at index 1 starts AFTER Q's cast_time;
        # its OWN cast_time is the AA windup the wire controls. Read the AA
        # row's cast_time directly (it is the windup that advances the clock).
        r = compute_combo(
            "Caitlyn", 11, item_ids=[], sequence=["Q", "AA"],
            target_armor=80.0, target_mr=60.0, mode="SR", snapshot=snap,
        )
        aa = [h for h in r.hits if h.action == "AA"][0]
        return aa.cast_time

    def test_empty_overlay_uses_default_windup(self):
        # No sidecar entry -> the AA windup is the fixed 0.25 default.
        snap = _snap_with_wiki({})
        self.assertAlmostEqual(self._aa_windup(snap), cb._DEFAULT_AA_WINDUP_S)
        self.assertAlmostEqual(cb._DEFAULT_AA_WINDUP_S, 0.25)

    def test_populated_overlay_shifts_windup(self):
        # A real per-champ windup overrides the default on the AA row.
        snap = _snap_with_wiki({"Caitlyn": {"attack_cast_time": 0.4}})
        self.assertAlmostEqual(self._aa_windup(snap), 0.4)

    def test_overlay_difference_is_exactly_the_value(self):
        # The empty-vs-populated AA windup delta equals the synthetic value
        # minus the default - the wire changes nothing else.
        empty = self._aa_windup(_snap_with_wiki({}))
        populated = self._aa_windup(
            _snap_with_wiki({"Caitlyn": {"attack_cast_time": 0.6}})
        )
        self.assertAlmostEqual(
            populated - empty, 0.6 - cb._DEFAULT_AA_WINDUP_S, places=6,
        )

    def test_offset_derived_windup_flows_into_combo(self):
        # The Win 1 wiki_offset tier produces a plain positive attack_cast_time
        # ((0.300 + attack_delay_offset)/as_base); to the consumer it is just a
        # value. Prove an offset-derived (Akali-shape) windup reaches the AA row.
        windup = round((0.300 + (-0.160999998450279)) / 0.625, 6)  # 0.2224
        self.assertNotAlmostEqual(windup, cb._DEFAULT_AA_WINDUP_S)
        snap = _snap_with_wiki({"Caitlyn": {"attack_cast_time": windup}})
        # combo rounds the per-hit cast_time to 3 places for the report row.
        self.assertAlmostEqual(self._aa_windup(snap), windup, places=3)

    def test_null_overlay_falls_back_to_default(self):
        # A present champ entry with null attack_cast_time keeps the default.
        snap = _snap_with_wiki({"Caitlyn": {"attack_cast_time": None}})
        self.assertAlmostEqual(self._aa_windup(snap), cb._DEFAULT_AA_WINDUP_S)

    def test_zero_overlay_falls_back_to_default(self):
        # A non-positive value is ignored (a 0s AA windup is nonsensical).
        snap = _snap_with_wiki({"Caitlyn": {"attack_cast_time": 0.0}})
        self.assertAlmostEqual(self._aa_windup(snap), cb._DEFAULT_AA_WINDUP_S)

    def test_other_champ_overlay_does_not_leak(self):
        # An overlay keyed on a DIFFERENT champ must not affect Caitlyn.
        snap = _snap_with_wiki({"Jinx": {"attack_cast_time": 0.5}})
        self.assertAlmostEqual(self._aa_windup(snap), cb._DEFAULT_AA_WINDUP_S)


class AsciiHygieneTest(unittest.TestCase):
    def test_this_test_file_is_ascii(self):
        src = pathlib.Path(__file__).read_bytes()
        nonascii = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(nonascii, [], f"non-ASCII bytes: {nonascii[:5]}")

    def test_data_loader_is_ascii(self):
        from agents.daemon_slayer import data_loader as dl
        src = pathlib.Path(dl.__file__).read_bytes()
        nonascii = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(nonascii, [], f"non-ASCII bytes: {nonascii[:5]}")


if __name__ == "__main__":
    unittest.main()
