"""FU01 — HTTP ?bbox= override parsing tests (closes L-01 / M-01).

Exercises `agents._minimap_bbox.parse_http_override()` which is called by
`agents/supervisor.py:_handle_minimap_crop` to validate the ?bbox= query
parameter.  Keeps the test isolated from the full supervisor import graph.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from agents._minimap_bbox import parse_http_override  # noqa: E402


_BAD: list[tuple[str, str]] = [
    ("50,50,50,100",          "r<=l (degenerate width)"),
    ("100,50,50,100",         "r<l (inverted x)"),
    ("0,0,1920,0",            "b<=t (degenerate height)"),
    ("0,100,100,50",          "b<t (inverted y)"),
    ("-1,0,100,100",          "negative coord"),
    ("0,0,1000000,1000000",   "coord out of range"),
    ("0,0,100",               "too few elements"),
    ("0,0,100,100,100",       "too many elements"),
    ("a,b,c,d",               "non-numeric"),
    ("0,0,10001,100",         "coord exactly over limit"),
]

_GOOD: list[tuple[str, tuple[int, int, int, int]]] = [
    ("1565,735,1905,1075", (1565, 735, 1905, 1075)),  # hardcoded SR default
    ("0,0,1,1",            (0, 0, 1, 1)),              # minimal valid box
    ("0,0,10000,10000",    (0, 0, 10000, 10000)),      # max valid range
    ("100,200,300,400",    (100, 200, 300, 400)),       # ordinary interior box
]


class ParseHttpOverrideBadInputTests(unittest.TestCase):
    def _assert_bad(self, raw: str, note: str) -> None:
        with self.subTest(raw=raw, note=note):
            with self.assertRaises(ValueError):
                parse_http_override(raw)

    def test_bad_inputs_raise_value_error(self) -> None:
        for raw, note in _BAD:
            self._assert_bad(raw, note)


class ParseHttpOverrideGoodInputTests(unittest.TestCase):
    def test_good_inputs_return_correct_tuple(self) -> None:
        for raw, expected in _GOOD:
            with self.subTest(raw=raw):
                result = parse_http_override(raw)
                self.assertEqual(result, expected)
                self.assertIsInstance(result, tuple)
                self.assertEqual(len(result), 4)
                self.assertTrue(all(isinstance(v, int) for v in result))

    def test_return_order_is_l_t_r_b(self) -> None:
        l, t, r, b = parse_http_override("10,20,30,40")
        self.assertEqual((l, t, r, b), (10, 20, 30, 40))

    def test_boundary_exact_max_coord(self) -> None:
        result = parse_http_override("0,0,10000,10000")
        self.assertEqual(result, (0, 0, 10000, 10000))

    def test_boundary_coord_one_over_max_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_http_override("0,0,10001,100")

    def test_boundary_minimal_positive_box(self) -> None:
        result = parse_http_override("0,0,1,1")
        self.assertEqual(result, (0, 0, 1, 1))


if __name__ == "__main__":
    unittest.main()
