"""RM-850: the ARAM comp-verdict POST carries the build variants.

Bug (filed s133 by the gated lane): `_csvFetchCompVerdict` in
web/js/panels/champ_select.js POSTed only my_champion / my_team /
their_team / bench to /api/aram-comp-verdict, and `_csvCompVerdictKey`
keyed the single-slot cache on champion + team + bench only. The engine
(core/aram_comp_verdict.py comp_verdict) returns a VARIANT verdict only
through `_find_variant` over state["variants"] (dicts with key / label /
summary) against state["current_variant"], and the route
(dashboard/routes_coach.py _serve_aram_comp_verdict_post) passes the body
through verbatim. So the variant verdict was unreachable live.

Fix contract pinned here:
  * the live POST body carries `variants` as [{key, label, summary}] (the
    chooser rows reduced to the fields the engine reads; the "empty"
    no-champion placeholder is not a variant) and `current_variant` (the
    active chooser variant's bare key);
  * the cache key folds in the variant set + the active variant, so user
    variants landing or a chooser click re-requests;
  * the mock path is unchanged: it reads the fixture, never POSTs, and keeps
    the pre-RM-850 key;
  * the render call site passes the resolved chooser variants and the active
    selection.

House pattern (mirrors tests/test_csv_push_swap_wipe.py and
tests/test_csv_push_toggles_phase5.py): structural pins plus a node
round-trip of the brace-extracted functions against a recording fetch stub.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAMP_SELECT_JS = REPO_ROOT / "web" / "js" / "panels" / "champ_select.js"
_NODE = shutil.which("node")

_ROUTE = "/api/aram-comp-verdict"
_MOCK_URL = "/data/ui_mock/champ_select_aram.json"


def _fn_body(text: str, sig: str) -> str:
    """Brace-balanced body of a top-level `function <sig> {`."""
    start = text.index(sig)
    open_brace = text.index("{", start)
    depth = 0
    for i in range(open_brace, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace:i + 1]
    raise AssertionError(f"unbalanced braces after {sig!r}")


def _fn_source(text: str, name: str) -> str:
    """`function <name>(<params>) { ... }` re-assembled from the source."""
    sig = f"function {name}("
    start = text.index(sig)
    params_end = text.index(")", start)
    return text[start:params_end + 1] + " " + _fn_body(text, sig)


class Rm850StructureTests(unittest.TestCase):
    """Static pins on the wiring the node round-trip cannot see."""

    @classmethod
    def setUpClass(cls):
        cls.js = CHAMP_SELECT_JS.read_text(encoding="utf-8")
        cls.fetch_body = _fn_body(cls.js, "function _csvFetchCompVerdict(")
        cls.pane = _fn_body(cls.js, "function _csvRenderCentralPane(")

    def test_post_body_names_variants_and_current_variant(self):
        self.assertIn("variants:", self.fetch_body,
            "the /api/aram-comp-verdict POST body must carry `variants` - the "
            "engine's _find_variant reads state['variants'] and nothing else.")
        self.assertIn("current_variant:", self.fetch_body,
            "the POST body must carry `current_variant` so the engine never "
            "recommends switching to the variant already active.")

    def test_render_passes_variants_after_they_resolve(self):
        variants_at = self.pane.index(
            "const variants = _csvBuildVariantsFor(")
        call_at = self.pane.index("_csvFetchCompVerdict(cs,")
        self.assertLess(variants_at, call_at,
            "the comp-verdict fetch must fire AFTER the chooser variants "
            "resolve, passing them in (it fired before, with cs alone).")
        self.assertNotIn("_csvFetchCompVerdict(cs);", self.pane,
            "the variant-less call site must be gone.")
        calls = re.findall(r"(?<!function )_csvFetchCompVerdict\(cs\b",
                           self.js)
        self.assertEqual(len(calls), 1,
            "exactly ONE comp-verdict fetch call site (the definition is "
            "not a call).")

    def test_current_variant_comes_from_the_active_selection(self):
        call_at = self.pane.index("_csvFetchCompVerdict(cs,")
        call = self.pane[call_at:self.pane.index(";", call_at)]
        self.assertIn("_activeSel", call,
            "current_variant must be the chooser's ACTIVE selection "
            "(_csvActiveBuildSelection: saved choice, else first row).")


@unittest.skipUnless(_NODE, "node not on PATH")
class Rm850BehaviorTests(unittest.TestCase):
    """Run the extracted key + fetch functions in node against a recording
    fetch stub and drive the live and mock scenarios."""

    @classmethod
    def setUpClass(cls):
        js = CHAMP_SELECT_JS.read_text(encoding="utf-8")
        fns = [_fn_source(js, "_csvCompVerdictKey"),
               _fn_source(js, "_csvFetchCompVerdict")]
        # RM-850 may add a payload helper; extract it when present so the
        # harness runs the real code, never a re-implementation.
        if "function _csvCompVerdictVariants(" in js:
            fns.insert(0, _fn_source(js, "_csvCompVerdictVariants"))
        harness = (
            'const _CSV_COMPVERDICT = { key: "", data: null, inflight: false };\n'
            "const document = { body: { dataset: { uiMock: '0' } } };\n"
            "const _NAMES = { 1: 'Ashe', 2: 'Garen', 3: 'Lux', 4: 'Jinx',"
            " 5: 'Sona', 6: 'Darius', 7: 'Zed', 8: 'Annie' };\n"
            "function _csChampName(cid) { return _NAMES[cid | 0] || ''; }\n"
            "let _renders = 0;\n"
            "function _csvScheduleRender() { _renders += 1; }\n"
            "const _calls = [];\n"
            "async function fetch(url, opts) {\n"
            "  _calls.push({ url, method: (opts && opts.method) || 'GET',\n"
            "    body: (opts && opts.body) ? JSON.parse(opts.body) : null });\n"
            "  const payload = String(url).indexOf('ui_mock') >= 0\n"
            "    ? { aram_comp_verdict: { ok: true, recommendation: 'stay' } }\n"
            "    : { ok: true, recommendation: 'stay' };\n"
            "  return { ok: true, json: async () => payload };\n"
            "}\n"
            + "\n".join(fns) + "\n"
            "const flush = () => new Promise((r) => setTimeout(r, 0));\n"
            "function drain() { const c = _calls.slice();"
            " _calls.length = 0; return c; }\n"
            "function reset(mock) {\n"
            "  _CSV_COMPVERDICT.key = ''; _CSV_COMPVERDICT.data = null;\n"
            "  _CSV_COMPVERDICT.inflight = false;\n"
            "  document.body.dataset.uiMock = mock ? '1' : '0';\n"
            "}\n"
            "const cs = { my_champion: 1,\n"
            "  my_team: [{ championId: 1 }, { championId: 2 },"
            " { championId: 3 }, { championId: 4 }, { championId: 5 }],\n"
            "  their_team: [{ championId: 6 }, { championId: 7 }],\n"
            "  bench: [8] };\n"
            "// Chooser rows as _csvBuildVariantsFor builds them (extra row\n"
            "// fields the engine never reads must not ride in the POST).\n"
            "const rows = [\n"
            "  { key: 'crit', label: 'Crit ADC', keystone: 'Lethal Tempo',\n"
            "    item_ids: [3031, 3006], summoners: [4, 32], is_user: true,\n"
            "    build_paths: [] },\n"
            "  { key: 'ap_burst', label: 'AP Burst', summary: 'magic burst',\n"
            "    keystone: 'Electrocute', item_ids: [3089], summoners: [4, 32],\n"
            "    is_user: true, build_paths: [] },\n"
            "];\n"
            "const out = {};\n"
            "(async () => {\n"
            "  // 1: live POST with the chooser rows + the active variant.\n"
            "  reset(false);\n"
            "  _csvFetchCompVerdict(cs, rows, 'crit');\n"
            "  await flush();\n"
            "  out.first = drain();\n"
            "  out.first_key = _CSV_COMPVERDICT.key;\n"
            "  // 2: same inputs re-render -> cache hit, no request.\n"
            "  _csvFetchCompVerdict(cs, JSON.parse(JSON.stringify(rows)),"
            " 'crit');\n"
            "  await flush();\n"
            "  out.same = drain();\n"
            "  // 3: chooser click to another variant -> re-request.\n"
            "  _csvFetchCompVerdict(cs, rows, 'ap_burst');\n"
            "  await flush();\n"
            "  out.click = drain();\n"
            "  // 4: the variant set changes (a row lands) -> re-request.\n"
            "  const more = rows.concat([{ key: 'tank', label: 'Tank',\n"
            "    item_ids: [3068], build_paths: [] }]);\n"
            "  _csvFetchCompVerdict(cs, more, 'ap_burst');\n"
            "  await flush();\n"
            "  out.grow = drain();\n"
            "  // 5: no-champion placeholder row is not a variant.\n"
            "  reset(false);\n"
            "  _csvFetchCompVerdict(cs, [{ key: 'empty',"
            " label: 'no champion yet', item_ids: [], is_default: true }], '');\n"
            "  await flush();\n"
            "  out.placeholder = drain();\n"
            "  // 6: key function: variant set + active variant both count.\n"
            "  out.k_a = _csvCompVerdictKey(cs);\n"
            "  // 7: mock path: fixture read, no POST, pre-RM-850 key.\n"
            "  reset(true);\n"
            "  _csvFetchCompVerdict(cs, rows, 'crit');\n"
            "  await flush();\n"
            "  out.mock = drain();\n"
            "  out.mock_key = _CSV_COMPVERDICT.key;\n"
            "  _csvFetchCompVerdict(cs, rows, 'ap_burst');\n"
            "  await flush();\n"
            "  out.mock_click = drain();\n"
            "  process.stdout.write(JSON.stringify(out));\n"
            "})().catch((e) => { process.stderr.write(String(e && e.stack"
            " || e)); process.exit(1); });\n"
        )
        cls._td = tempfile.mkdtemp()
        h = Path(cls._td) / "rm850.mjs"
        h.write_text(harness, encoding="utf-8")
        proc = subprocess.run([_NODE, str(h)], capture_output=True,
                              text=True, timeout=30)
        if proc.returncode != 0:
            raise AssertionError(f"node harness failed: {proc.stderr}")
        cls.res = json.loads(proc.stdout)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._td, ignore_errors=True)

    def _single_post(self, calls):
        posts = [c for c in calls if c["url"] == _ROUTE]
        self.assertEqual(len(posts), 1, f"expected one POST, got {calls!r}")
        self.assertEqual(posts[0]["method"], "POST")
        return posts[0]["body"]

    def test_post_body_carries_variants_and_current_variant(self):
        body = self._single_post(self.res["first"])
        self.assertEqual(body.get("variants"), [
            {"key": "crit", "label": "Crit ADC", "summary": ""},
            {"key": "ap_burst", "label": "AP Burst", "summary": "magic burst"},
        ], "variants must be the chooser rows reduced to key/label/summary "
           "(the fields core/aram_comp_verdict._variant_addresses reads).")
        self.assertEqual(body.get("current_variant"), "crit")

    def test_post_body_keeps_the_comp_fields(self):
        body = self._single_post(self.res["first"])
        self.assertEqual(body["my_champion"], "Ashe")
        self.assertEqual(body["my_team"],
                         ["Ashe", "Garen", "Lux", "Jinx", "Sona"])
        self.assertEqual(body["their_team"], ["Darius", "Zed"])
        self.assertEqual(body["bench"], ["Annie"])

    def test_same_inputs_hit_the_cache(self):
        self.assertEqual(self.res["same"], [],
            "an unchanged variant set + active variant must not re-request.")

    def test_variant_click_rerequests(self):
        body = self._single_post(self.res["click"])
        self.assertEqual(body.get("current_variant"), "ap_burst",
            "a chooser click changes current_variant, so the cache key must "
            "change and the verdict re-request.")

    def test_variant_set_change_rerequests(self):
        body = self._single_post(self.res["grow"])
        self.assertEqual([v["key"] for v in body.get("variants", [])],
                         ["crit", "ap_burst", "tank"])

    def test_cache_key_folds_in_the_variant_set(self):
        self.assertNotEqual(self.res["first_key"], self.res["k_a"],
            "the live cache key must include the variant set, not just "
            "champion + team + bench.")

    def test_placeholder_row_is_not_sent_as_a_variant(self):
        body = self._single_post(self.res["placeholder"])
        self.assertEqual(body.get("variants"), [])
        self.assertEqual(body.get("current_variant"), "")

    def test_mock_path_reads_fixture_and_never_posts(self):
        calls = self.res["mock"]
        self.assertEqual([c["url"] for c in calls], [_MOCK_URL])
        self.assertEqual(calls[0]["method"], "GET")
        self.assertIsNone(calls[0]["body"])

    def test_mock_path_keeps_the_pre_rm850_key(self):
        self.assertEqual(self.res["mock_key"], "1|1,2,3,4,5|8",
            "mock keeps the champion|team|bench key (mock path unchanged).")
        self.assertEqual(self.res["mock_click"], [],
            "mock mode does not refetch the fixture on a variant change.")


if __name__ == "__main__":
    unittest.main()
