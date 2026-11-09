"""s144 true-audit (S144-T-675): core/sr_schedule.py hardening.

core/sr_schedule.py exists so that every SR timer reads ONE table. Before
this audit that guarantee only held while nobody touched the table:

1. SCHEDULE was a plain module-global dict. Any importer (or a test) could
   assign or delete a row; value() then served the new number while the
   named constants (computed once at import) and every consumer that copied
   them kept the old one - two sources disagreeing again, the exact defect
   the module was created to end.
2. _ROWS was never validated. A duplicated key silently kept the LAST row
   (and the existing status test, which walks SCHEDULE, could not see the
   lost one); an unknown status, a removed row with a value, a negative,
   NaN, infinite or boolean value were all accepted.
3. PLATES_FALL_S / ATAKHAN_FIRST_S / VOIDGRUBS_RESPAWN_S were hard-coded
   None instead of read from their rows, so reinstating a row (Atakhan back
   with a spawn time) left the constant - and snapshot_normalizer's
   FIRST_ATAKHAN - at None while value() said otherwise.
4. value() / _req() on an unhashable key raised a bare TypeError and on an
   unknown key a bare KeyError naming nothing; both now raise one KeyError
   that names the module and the key.
"""
from __future__ import annotations

import inspect
import math
import sys
import types
import unittest

import core.sr_schedule as sched


def _exec_with_rows(old: str, new: str) -> dict:
    """Execute the module source with one row literal substituted."""
    src = inspect.getsource(sched)
    assert src.count(old) == 1, old
    # A registered module: @dataclass resolves its own module at class build.
    name = "_sr_schedule_probe"
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    try:
        exec(compile(src.replace(old, new), f"<{name}>", "exec"), mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod.__dict__


class ScheduleIsReadOnlyTests(unittest.TestCase):
    def test_row_assignment_is_refused(self):
        with self.assertRaises(TypeError):
            sched.SCHEDULE["baron_first"] = sched.Timing(
                "baron_first", 1.0, sched.STATUS_OFFICIAL, "x")
        self.assertEqual(sched.value("baron_first"), sched.BARON_FIRST_S)

    def test_row_deletion_is_refused(self):
        with self.assertRaises(TypeError):
            del sched.SCHEDULE["dragon_first"]
        self.assertIn("dragon_first", sched.SCHEDULE)

    def test_rows_are_frozen(self):
        row = sched.SCHEDULE["herald_first"]
        with self.assertRaises(AttributeError):
            row.value_s = 1.0  # type: ignore[misc]

    def test_as_dict_is_a_detached_copy(self):
        d = sched.as_dict()
        d["baron_first"]["value_s"] = 1.0
        d.pop("dragon_first")
        self.assertEqual(sched.value("baron_first"), sched.BARON_FIRST_S)
        self.assertEqual(sched.as_dict()["dragon_first"]["value_s"],
                         sched.DRAGON_FIRST_S)

    def test_every_row_survives_into_schedule(self):
        self.assertEqual(len(sched.SCHEDULE), len(sched._ROWS))


class RowValidationTests(unittest.TestCase):
    def _row(self, key="k", value_s=1.0, status=None, source="src"):
        return sched.Timing(key, value_s,
                            status or sched.STATUS_OFFICIAL, source)

    def test_valid_rows_build_a_mapping(self):
        m = sched._build_schedule((self._row("a"), self._row("b", None)))
        self.assertEqual(sorted(m), ["a", "b"])

    def test_duplicate_key_is_refused(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            sched._build_schedule((self._row("a", 1.0), self._row("a", 2.0)))

    def test_unknown_status_is_refused(self):
        with self.assertRaisesRegex(ValueError, "status"):
            sched._build_schedule((self._row(status="guess"),))

    def test_removed_row_with_a_value_is_refused(self):
        with self.assertRaisesRegex(ValueError, "removed"):
            sched._build_schedule(
                (self._row(value_s=60.0, status=sched.STATUS_REMOVED),))

    def test_bad_values_are_refused(self):
        for bad in (0.0, -1.0, math.nan, math.inf, True, "300", [300]):
            with self.subTest(bad=repr(bad)), self.assertRaises(ValueError):
                sched._build_schedule((self._row(value_s=bad),))

    def test_empty_key_or_source_is_refused(self):
        for row in (self._row(key=""), self._row(source="  "),
                    self._row(key=None)):
            with self.subTest(row=repr(row)), self.assertRaises(ValueError):
                sched._build_schedule((row,))

    def test_non_timing_row_is_refused(self):
        with self.assertRaises(ValueError):
            sched._build_schedule(({"key": "a"},))

    def test_shipped_rows_pass_validation(self):
        self.assertEqual(dict(sched._build_schedule(sched._ROWS)),
                         dict(sched.SCHEDULE))


class ConstantsFollowRowsTests(unittest.TestCase):
    def test_removed_constants_match_their_rows(self):
        self.assertEqual(sched.PLATES_FALL_S, sched.value("plates_fall"))
        self.assertEqual(sched.ATAKHAN_FIRST_S, sched.value("atakhan_first"))
        self.assertEqual(sched.VOIDGRUBS_RESPAWN_S,
                         sched.value("voidgrubs_respawn"))

    def test_reinstated_row_reaches_its_constant(self):
        ns = _exec_with_rows(
            '_t("atakhan_first", None, STATUS_REMOVED,',
            '_t("atakhan_first", 2400.0, STATUS_OFFICIAL,')
        self.assertEqual(ns["value"]("atakhan_first"), 2400.0)
        self.assertEqual(ns["ATAKHAN_FIRST_S"], 2400.0)

    def test_respawning_grubs_reach_their_constant(self):
        ns = _exec_with_rows('_t("voidgrubs_respawn", None,',
                             '_t("voidgrubs_respawn", 240.0,')
        self.assertEqual(ns["VOIDGRUBS_RESPAWN_S"], 240.0)

    def test_plates_fall_reaches_its_constant(self):
        ns = _exec_with_rows('_t("plates_fall", None,',
                             '_t("plates_fall", 840.0,')
        self.assertEqual(ns["PLATES_FALL_S"], 840.0)


class KeyContractTests(unittest.TestCase):
    def test_unknown_key_names_the_module_and_key(self):
        with self.assertRaisesRegex(KeyError, r"sr_schedule.*'nope'"):
            sched.value("nope")

    def test_unhashable_or_non_string_key_is_a_key_error(self):
        for bad in (["baron_first"], {"k": 1}, None, 1200):
            with self.subTest(bad=repr(bad)), self.assertRaises(KeyError):
                sched.value(bad)  # type: ignore[arg-type]

    def test_required_value_unknown_key_is_a_key_error(self):
        with self.assertRaisesRegex(KeyError, "sr_schedule"):
            sched._req("nope")
        with self.assertRaises(KeyError):
            sched._req(["x"])  # type: ignore[arg-type]

    def test_known_keys_still_resolve(self):
        self.assertEqual(sched.value("baron_first"), 1200.0)
        self.assertIsNone(sched.value("atakhan_first"))
        self.assertEqual(sched._req("dragon_first"), 300.0)


if __name__ == "__main__":
    unittest.main()
