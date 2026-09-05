"""tests/test_smoothed_rates_101qq_coercion.py - RM-291 Sweep B.

Tolerant numeric coercion at the 101.qq.com (Tencent) parse site.

Provenance: THIRD-PARTY. `core/smoothed_rates_101qq._rows_to_records` is
the consumer of a feed whose shape RC does not control, reached live via
`core/synergy_external_source.fetch_rows` (CLAUDE.md item 277) and seeded
statically from `data/external/101qq_hero_rank_double_tier200_capture_20260525.json`.

That captured payload PROVES the feed string-encodes numbers:

    {"championid1": "22", "itemp1": "4.78%", "doublewinrate": 0.5653, ...}

ids arrive as numeric strings and itemp1 as a percent-suffixed string,
which is why `_parse_itemp` exists. The four sibling numeric fields
(championid1/2, doublewinrate, iwinrate1/2, irank) were coerced with a
bare int()/float() inside `except (TypeError, ValueError): continue`, so a
value the feed could plausibly send - "22.0", "56.53%", "1.0" - did not
raise but silently DROPPED THE WHOLE ROW. Enough dropped rows makes
`_rows_to_records` return empty, which is exactly the condition that fires
the static May-2025 fallback: the operator would be served a 15-month-old
seed as if it were live, with nothing logged.

`int("1500.0")` / `float("n/a")` is the LEDGER 1299 W1 class; this is the
same class one module over.

CONTRACT ASSERTED HERE (deliberately non-regressive):
  * every row kept before is kept with byte-identical values,
  * a string-encoded number the feed could send is now PARSED, not dropped,
  * a value that carries no win rate at all ("n/a", None, "") still drops
    the row - a pairing with no rate is not a pairing, and inventing 0.0
    for it would rank a real duo dead last in the "best pairings" list.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import smoothed_rates_101qq as S101  # noqa: E402

_ID_TO_NAME = {22: "Ashe", 147: "Seraphine"}


def _row(**over):
    """One well-formed row in the shape the captured payload actually uses."""
    base = {
        "championid1": "22",
        "championid2": "147",
        "doublewinrate": 0.5653,
        "iwinrate1": 0.5223,
        "iwinrate2": 0.5307,
        "itemp1": "4.78%",
        "irank": 1,
    }
    base.update(over)
    return base


class RowsToRecordsCoercionTests(unittest.TestCase):
    """Hostile-but-plausible values at the third-party parse site."""

    def _one(self, **over):
        return S101._rows_to_records([_row(**over)], _ID_TO_NAME)

    # -- non-regression: today's live shape is untouched -------------

    def test_baseline_live_shape_unchanged(self):
        out = self._one()
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["bot"], "Ashe")
        self.assertEqual(r["sup"], "Seraphine")
        self.assertEqual(r["bot_id"], 22)
        self.assertEqual(r["sup_id"], 147)
        self.assertAlmostEqual(r["doublewinrate"], 0.5653)
        self.assertAlmostEqual(r["iwinrate_bot"], 0.5223)
        self.assertAlmostEqual(r["iwinrate_sup"], 0.5307)
        self.assertEqual(r["irank"], 1)

    # -- the LEDGER 1299 W1 shape: a float-formatted integer string --

    def test_champion_id_float_string_is_parsed_not_dropped(self):
        """int("22.0") raises ValueError; the row must survive it."""
        out = self._one(championid1="22.0", championid2="147.0")
        self.assertEqual(len(out), 1, "float-formatted id string dropped the row")
        self.assertEqual(out[0]["bot_id"], 22)
        self.assertEqual(out[0]["sup_id"], 147)

    def test_irank_float_string_is_parsed_not_dropped(self):
        out = self._one(irank="1.0")
        self.assertEqual(len(out), 1, "float-formatted irank dropped the row")
        self.assertEqual(out[0]["irank"], 1)

    # -- the shape this feed demonstrably uses for itemp1 ------------

    def test_percent_suffixed_rates_are_parsed_not_dropped(self):
        """itemp1 already arrives as "4.78%"; a sibling rate could too."""
        out = self._one(
            doublewinrate="56.53%", iwinrate1="52.23%", iwinrate2="53.07%",
        )
        self.assertEqual(len(out), 1, "percent-suffixed rate dropped the row")
        self.assertAlmostEqual(out[0]["doublewinrate"], 0.5653)
        self.assertAlmostEqual(out[0]["iwinrate_bot"], 0.5223)
        self.assertAlmostEqual(out[0]["iwinrate_sup"], 0.5307)

    def test_plain_numeric_string_rates_stay_decimal_shares(self):
        """"0.5653" is already a share and must NOT be divided by 100."""
        out = self._one(doublewinrate="0.5653")
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0]["doublewinrate"], 0.5653)

    def test_whitespace_padded_values_are_parsed(self):
        out = self._one(championid1=" 22 ", doublewinrate=" 0.5653 ", irank=" 1 ")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bot_id"], 22)
        self.assertAlmostEqual(out[0]["doublewinrate"], 0.5653)
        self.assertEqual(out[0]["irank"], 1)

    # -- degrade, never raise ---------------------------------------

    def test_uncoercible_values_degrade_without_raising(self):
        """The whole point: no ValueError escapes to the caller."""
        for field in ("championid1", "championid2", "doublewinrate",
                      "iwinrate1", "iwinrate2", "irank"):
            for hostile in ("n/a", "", None, "N/A", [], {}, "1e", float("nan")):
                with self.subTest(field=field, hostile=hostile):
                    try:
                        S101._rows_to_records(
                            [_row(**{field: hostile})], _ID_TO_NAME,
                        )
                    except Exception as exc:  # noqa: BLE001
                        self.fail(
                            f"{field}={hostile!r} raised "
                            f"{type(exc).__name__}: {exc}"
                        )

    def test_non_finite_values_are_rejected_not_propagated(self):
        """A NaN/Infinity must not reach the record.

        Pinned down explicitly because the no-raise test above passes
        whether or not the isfinite guard exists - a negative assertion
        rules a failure out without pinning the value down, and a
        mutation that deleted the guard survived on it. NaN is not valid
        JSON, so one leaking into the duo-synergy payload blanks the
        whole dashboard panel rather than degrading one row.
        """
        for hostile in (float("nan"), float("inf"), float("-inf"),
                        "nan", "inf", "-inf", "NaN", "Infinity"):
            with self.subTest(hostile=hostile):
                self.assertEqual(
                    S101._rows_to_records(
                        [_row(doublewinrate=hostile)], _ID_TO_NAME,
                    ),
                    [],
                    "a non-finite win rate must not be kept",
                )

    def test_booleans_are_not_numbers(self):
        """JSON `true` is a plausible field value, and `isinstance(True, int)`
        is True in Python - so without an explicit bool branch a boolean
        win rate would silently become 1.0/0.0 and be published as a real
        pairing rate. Pinned because a mutation of that branch survived."""
        self.assertIsNone(S101._as_rate(True))
        self.assertIsNone(S101._as_rate(False))
        self.assertIsNone(S101._as_int(True))
        self.assertIsNone(S101._as_int(False))
        for hostile in (True, False):
            with self.subTest(hostile=hostile):
                self.assertEqual(
                    S101._rows_to_records(
                        [_row(doublewinrate=hostile)], _ID_TO_NAME,
                    ),
                    [],
                    "a boolean win rate must not be published as a rate",
                )
                self.assertEqual(
                    S101._rows_to_records(
                        [_row(championid1=hostile)], _ID_TO_NAME,
                    ),
                    [],
                    "a boolean champion id must not resolve",
                )

    def test_helpers_reject_non_finite_directly(self):
        for hostile in (float("nan"), float("inf"), float("-inf"),
                        "nan", "inf", "NaN", "1e999"):
            with self.subTest(hostile=hostile):
                self.assertIsNone(S101._as_rate(hostile))
                self.assertIsNone(S101._as_int(hostile))

    def test_no_record_field_is_ever_non_finite(self):
        """Whole-record sweep: nothing the module publishes may be NaN/inf."""
        import math as _m
        rows = [
            _row(doublewinrate=float("nan")),
            _row(iwinrate1=float("inf"), championid1="22.0"),
            _row(irank="nan"),
            _row(),
        ]
        for r in S101._rows_to_records(rows, _ID_TO_NAME):
            for k, v in r.items():
                if isinstance(v, float):
                    self.assertTrue(
                        _m.isfinite(v), f"{k} published non-finite {v!r}",
                    )

    def test_row_with_no_usable_win_rate_is_still_dropped(self):
        """A pairing with no rate carries nothing; inventing 0.0 would rank
        a real duo dead last. This is the one field whose absence is fatal."""
        for hostile in ("n/a", "", None):
            with self.subTest(hostile=hostile):
                self.assertEqual(
                    S101._rows_to_records(
                        [_row(doublewinrate=hostile)], _ID_TO_NAME,
                    ),
                    [],
                    "a row with no win rate must not be kept",
                )

    def test_unresolvable_champion_id_is_still_dropped(self):
        for hostile in ("n/a", "", None, 0, "0"):
            with self.subTest(hostile=hostile):
                self.assertEqual(
                    S101._rows_to_records(
                        [_row(championid1=hostile)], _ID_TO_NAME,
                    ),
                    [],
                    "a row with no resolvable bot id must not be kept",
                )

    def test_non_dict_and_non_list_input_still_safe(self):
        self.assertEqual(S101._rows_to_records(None, _ID_TO_NAME), [])
        self.assertEqual(S101._rows_to_records("nope", _ID_TO_NAME), [])
        self.assertEqual(S101._rows_to_records([None, 5, "x"], _ID_TO_NAME), [])


if __name__ == "__main__":
    unittest.main()
