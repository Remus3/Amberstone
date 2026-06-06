"""
tests/test_aram_comp_verdict_bench_ui.py - source-level + fixture-contract
tests for the deterministic ARAM comp-verdict bench surface.

Mirrors the source-regex style of tests/test_champ_select_coach.py. These
do not boot a browser; they pin the JS wiring, the CSS hooks, the mock
fixture shape, and that the verdict-presence token is folded into the
idempotent render signature so the banner re-fires when the fetch lands.

Frontend slice contract (matches the backend slice POST
/api/aram-comp-verdict): response carries
{ok, recommendation, swap_to, variant_to, reason, confidence, factors}.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

# Repo root = two levels up from this file (tests/ -> root).
_ROOT = Path(__file__).resolve().parent.parent
_JS_PATH = _ROOT / "web" / "js" / "panels" / "champ_select.js"
_CSS_PATH = _ROOT / "web" / "css" / "panels" / "champ_select_view.css"
_MOCK_PATH = _ROOT / "web" / "data" / "ui_mock" / "champ_select_aram.json"

_JS = _JS_PATH.read_text(encoding="utf-8")
_CSS = _CSS_PATH.read_text(encoding="utf-8")
_MOCK = json.loads(_MOCK_PATH.read_text(encoding="utf-8"))


class MockFixtureTests(unittest.TestCase):
    """The mock fixture must carry a well-formed sample verdict so the
    audit ritual can render the bench surface under ?ui_mock=1."""

    def test_aram_comp_verdict_present_and_shaped(self):
        self.assertIn("aram_comp_verdict", _MOCK,
                      "mock fixture missing top-level aram_comp_verdict key")
        v = _MOCK["aram_comp_verdict"]
        self.assertIsInstance(v, dict, "aram_comp_verdict must be a dict")
        for key in ("ok", "recommendation", "swap_to", "variant_to",
                    "reason", "confidence", "factors"):
            self.assertIn(key, v, f"verdict missing required key '{key}'")

    def test_recommendation_in_enum(self):
        v = _MOCK["aram_comp_verdict"]
        self.assertIn(v["recommendation"], {"swap", "variant", "stay"},
                      "recommendation must be one of swap/variant/stay")

    def test_swap_to_nonempty_when_recommendation_swap(self):
        v = _MOCK["aram_comp_verdict"]
        if v["recommendation"] == "swap":
            self.assertIsInstance(v["swap_to"], str)
            self.assertTrue(v["swap_to"].strip(),
                            "swap_to must be a non-empty str when "
                            "recommendation == 'swap'")

    def test_factors_is_dict(self):
        v = _MOCK["aram_comp_verdict"]
        self.assertIsInstance(v["factors"], dict,
                              "factors must be a dict of comp counts")


class JsWiringTests(unittest.TestCase):
    """Source-level pins on the JS wiring tokens."""

    def test_route_present(self):
        self.assertIn("/api/aram-comp-verdict", _JS,
                      "JS must POST to /api/aram-comp-verdict")

    def test_mock_key_referenced(self):
        self.assertIn("aram_comp_verdict", _JS,
                      "JS must read the aram_comp_verdict mock key")

    def test_module_cache_present(self):
        self.assertIn("_CSV_COMPVERDICT", _JS,
                      "JS must declare the _CSV_COMPVERDICT module cache")

    def test_banner_class_present(self):
        self.assertIn("csv-bench-verdict", _JS,
                      "JS must emit the csv-bench-verdict banner class")

    def test_swap_highlight_class_present(self):
        self.assertIn("is-verdict-swap", _JS,
                      "JS must mark the recommended cell with is-verdict-swap")

    def test_fetch_fn_present(self):
        self.assertIn("_csvFetchCompVerdict", _JS,
                      "JS must define the _csvFetchCompVerdict fetch fn")


class SigWiringTests(unittest.TestCase):
    """The verdict-presence token must be folded into _csvComputeSig so the
    idempotent render gate re-fires once the verdict fetch lands."""

    def test_compverdict_in_sig_body(self):
        start = _JS.find("function _csvComputeSig")
        self.assertNotEqual(start, -1, "_csvComputeSig not found in JS")
        nxt = _JS.find("\nfunction ", start + 1)
        body = _JS[start:nxt] if nxt != -1 else _JS[start:]
        self.assertIn("_CSV_COMPVERDICT", body,
                      "_csvComputeSig body must reference _CSV_COMPVERDICT so "
                      "the render sig changes when the verdict lands")


class CssWiringTests(unittest.TestCase):
    """CSS must define the banner + swap-highlight hooks."""

    def test_banner_rule_present(self):
        self.assertIn("csv-bench-verdict", _CSS,
                      "CSS must style .csv-bench-verdict")

    def test_swap_highlight_rule_present(self):
        self.assertIn("is-verdict-swap", _CSS,
                      "CSS must style .csv-bench-cell.is-verdict-swap")


if __name__ == "__main__":
    unittest.main()
