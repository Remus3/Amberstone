"""Tests for tools/probe_101qq_hero_rank_double.py + tools/compare_101qq_vs_ddragon.py.

Synthetic fixtures live in tests/fixtures/qq101/. Operator's real capture
on Game-PC will replace them at runtime (the script does not depend on
the fixture shape; the fixtures only validate the analyzer code paths).

Coverage:
- argparse contract (required --url + --json; --cross-check-rewind flag)
- JSON schema-shape analyzer stub (numeric / pascal keys)
- JSONP unwrap on `.js` files
- DDragon cross-reference stub
- compare_101qq_vs_ddragon alignment + override hook
- ASCII hygiene (both tool files + the instructions doc)

Stdlib-only. No fixtures touch the real `data/rewind_history.db` or
`data/external/101qq_hero_id_map.json`.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from tools import compare_101qq_vs_ddragon as cmp_mod
from tools import probe_101qq_hero_rank_double as probe_mod

_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "qq101"
_NUMERIC = _FIXTURES / "hero_rank_double_numeric.json"
_PASCAL = _FIXTURES / "hero_rank_double_pascal.json"
_JSONP = _FIXTURES / "hero_rank_double_jsonp.js"

_TOOL_PROBE = _REPO_ROOT / "tools" / "probe_101qq_hero_rank_double.py"
_TOOL_COMPARE = _REPO_ROOT / "tools" / "compare_101qq_vs_ddragon.py"
_DOC_INSTRUCTIONS = _REPO_ROOT / "docs" / "CAPTURE_101QQ_INSTRUCTIONS.md"


class ProbeArgparseContractTests(unittest.TestCase):
    """The script MUST require --url + --json. --cross-check-rewind is optional."""

    def test_missing_url_exits(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            probe_mod.main(["--json", str(_NUMERIC)])
        # argparse parser_error -> SystemExit with code 2.
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_json_exits(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            probe_mod.main(["--url", "https://example.com/x.json"])
        self.assertEqual(ctx.exception.code, 2)

    def test_nonexistent_json_returns_1(self) -> None:
        rc = probe_mod.main([
            "--url", "https://example.com/x.json",
            "--json", str(_REPO_ROOT / "does_not_exist_qq101.json"),
        ])
        self.assertEqual(rc, 1)

    def test_cross_check_rewind_flag_is_optional(self) -> None:
        # Without the flag, runs cleanly + returns 0 on a valid fixture.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = probe_mod.main([
                "--url", "https://game.gtimg.cn/images/lol/act/img/js/hero-rank-double-tier200.js",
                "--json", str(_NUMERIC),
            ])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("url_structure", out)
        self.assertIn("json_schema", out)
        self.assertIn("ddragon_cross_reference", out)
        # cross_check section omitted unless flag given.
        self.assertNotIn("rewind_history_cross_check", out)


class UrlAnalyzerTests(unittest.TestCase):
    """Heuristic URL decomposition."""

    def test_gtimg_host_detected(self) -> None:
        f = probe_mod.analyze_url(
            "https://game.gtimg.cn/images/lol/act/img/js/hero-rank-double-tier200.js"
        )
        self.assertTrue(f["is_gtimg"])
        self.assertEqual(f["host"], "game.gtimg.cn")
        self.assertTrue(f["looks_jsonp"])
        self.assertFalse(f["looks_static_json"])

    def test_tier_token_extracted(self) -> None:
        f = probe_mod.analyze_url("https://example.cn/path/tier=200/data.json")
        self.assertEqual(f["tier_token"], "200")
        self.assertTrue(f["looks_static_json"])

    def test_unknown_host_is_not_gtimg(self) -> None:
        f = probe_mod.analyze_url("https://example.com/foo")
        self.assertFalse(f["is_gtimg"])


class SchemaAnalyzerTests(unittest.TestCase):
    """JSON shape summary."""

    def test_numeric_keys_classified(self) -> None:
        payload = json.loads(_NUMERIC.read_text(encoding="utf-8"))
        s = probe_mod.analyze_schema(payload)
        self.assertEqual(s["top_level_type"], "dict")
        self.assertEqual(s["top_level_len"], 3)
        self.assertEqual(s["champion_key_format_guess"], "numeric_ddragon_or_tencent_id")
        self.assertIn("266", s["top_level_keys"])

    def test_pascal_keys_classified(self) -> None:
        payload = json.loads(_PASCAL.read_text(encoding="utf-8"))
        s = probe_mod.analyze_schema(payload)
        self.assertEqual(s["champion_key_format_guess"], "ddragon_name_pascalcase")

    def test_empty_dict_is_unknown(self) -> None:
        s = probe_mod.analyze_schema({})
        self.assertEqual(s["champion_key_format_guess"], "unknown")


class JsonpUnwrapTests(unittest.TestCase):
    """The Tencent CDN occasionally wraps payloads as `varName=({...});`.
    The probe script must unwrap that before json.loads."""

    def test_jsonp_unwraps_correctly(self) -> None:
        obj = probe_mod.load_json(_JSONP)
        self.assertIsInstance(obj, dict)
        self.assertIn("266", obj)


class DdragonCrossReferenceTests(unittest.TestCase):
    """Stub: real DDragon map present + numeric keys ARE in it."""

    def test_load_ddragon_keys_returns_map(self) -> None:
        m = probe_mod.load_ddragon_keys()
        # 16.10.1 ships ~172 champions; tolerate fleet drift.
        self.assertGreater(len(m), 150)
        # "266" is Aatrox in DDragon 16.10.1.
        self.assertEqual(m.get("266"), "Aatrox")

    def test_cross_reference_numeric_payload(self) -> None:
        payload = json.loads(_NUMERIC.read_text(encoding="utf-8"))
        m = probe_mod.load_ddragon_keys()
        xref = probe_mod.cross_reference_ddragon(list(payload.keys()), m)
        self.assertEqual(xref["total_payload_keys"], 3)
        # All 3 numeric IDs in the fixture exist in DDragon 16.10.1.
        self.assertEqual(xref["matched_as_numeric_ddragon_key"], 3)


class CompareToolTests(unittest.TestCase):
    """compare_101qq_vs_ddragon CLI contract + alignment + override hook."""

    def test_missing_json_exits(self) -> None:
        with self.assertRaises(SystemExit):
            cmp_mod.main([])

    def test_alignment_numeric_payload(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmp_mod.main(["--json", str(_NUMERIC)])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertGreaterEqual(out["summary"]["aligned_count"], 3)
        self.assertEqual(out["summary"]["unmatched_count"], 0)

    def test_alignment_with_unknown_key(self) -> None:
        ddragon = cmp_mod.load_ddragon_keys()
        payload = {"266": [], "Aatrox": [], "completely_unknown_key": []}
        result = cmp_mod.build_alignment(payload, ddragon, {})
        self.assertIn("266", result["aligned"])
        self.assertIn("Aatrox", result["aligned"])
        self.assertIn("completely_unknown_key", result["unmatched"])

    def test_override_wins(self) -> None:
        ddragon = cmp_mod.load_ddragon_keys()
        payload = {"weird_code": []}
        override = {"weird_code": "MissFortune"}
        result = cmp_mod.build_alignment(payload, ddragon, override)
        self.assertEqual(result["aligned"].get("weird_code"), "MissFortune")
        self.assertNotIn("weird_code", result["unmatched"])


class NoExternalDepsTests(unittest.TestCase):
    """Confirm the tool files import only stdlib + the in-repo helpers."""

    def test_probe_tool_stdlib_only(self) -> None:
        text = _TOOL_PROBE.read_text(encoding="utf-8")
        # No `import requests` / urllib3 / httpx / aiohttp etc. NO network deps.
        for forbidden in ("import requests", "import httpx", "import aiohttp", "from urllib3", "urllib.request"):
            self.assertNotIn(forbidden, text, "probe tool must be stdlib + no-network")

    def test_compare_tool_stdlib_only(self) -> None:
        text = _TOOL_COMPARE.read_text(encoding="utf-8")
        for forbidden in ("import requests", "import httpx", "import aiohttp", "from urllib3", "urllib.request"):
            self.assertNotIn(forbidden, text, "compare tool must be stdlib + no-network")


class AsciiHygieneTests(unittest.TestCase):
    """CLAUDE.md hard rule: 7-bit ASCII in authored content."""

    def _assert_ascii(self, path: Path) -> None:
        raw = path.read_bytes()
        for i, b in enumerate(raw):
            if b >= 0x80:
                self.fail(
                    f"non-ASCII byte 0x{b:02x} at offset {i} in {path}"
                )

    def test_probe_tool_ascii(self) -> None:
        self._assert_ascii(_TOOL_PROBE)

    def test_compare_tool_ascii(self) -> None:
        self._assert_ascii(_TOOL_COMPARE)

    def test_instructions_doc_ascii(self) -> None:
        self._assert_ascii(_DOC_INSTRUCTIONS)

    def test_fixtures_ascii(self) -> None:
        for f in (_NUMERIC, _PASCAL, _JSONP):
            self._assert_ascii(f)


class TestModuleAsciiTests(unittest.TestCase):
    """The test file itself must stay 7-bit ASCII."""

    def test_test_file_is_ascii(self) -> None:
        path = Path(__file__).resolve()
        raw = path.read_bytes()
        for i, b in enumerate(raw):
            if b >= 0x80:
                self.fail(f"non-ASCII byte 0x{b:02x} at offset {i} in {path}")


if __name__ == "__main__":
    unittest.main()
