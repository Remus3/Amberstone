"""
Lane 8 cycle 43 - audit of tft/tft_live_analysis.py.

The module is the vision-driven TFT comp coach: it reads a board snapshot from
TftVisionReader, asks a Claude model for nine advice fields, and publishes them
to data/tft_live_data.json. SEVEN other modules touch that file; FOUR of them READ it
(agents/agent2_backend/
file_ingest.py:71, app/_game_lifecycle.py:174, coaches/tft_coach.py:150,
core/feature_policy.py:425, core/tft_worker.py:158, ops/rc_state_validator.py:53,
tft/tft_coach_engine.py:255).

NINE of these twelve were proven RED against the pre-fix module before the fix
landed, and each guard was mutation-tested by reverting the production line it
guards (8 mutants, 8 killed). The other THREE - test_w1c, test_w2b, test_w4b -
are CHARACTERIZATION tests that passed pre-fix by design: they pin behaviour the
rewrite had to preserve, and they are not evidence for any fix. Labelled
individually so no reader has to re-derive which is which.
"""
import json
import logging
import sys
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tft import tft_live_analysis as tla  # noqa: E402

_KEY = "sk-ant-lane8cycle43-not-a-real-key-0123456789"


class _FakeBlock:
    """A content block that is NOT a text block - e.g. a thinking block."""

    def __init__(self, kind="thinking"):
        self.type = kind


class _TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResp:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, resp):
        self._resp = resp

    def create(self, **kw):
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


class _FakeClient:
    def __init__(self, resp):
        self.messages = _FakeMessages(resp)


_GOOD_RAW = (
    "Comp: Vanguard Jinx\nBuild: Jinx\nBuy: hold gold\nSell: none\n"
    "Keep: Vi\nAugmentPlay: N/A\nLoss: N/A\n"
    "UnitPlacement: Jinx D7\nUnitSwap: none\n"
)

_VS = {
    "board_units": ["Jinx", "Vi"],
    "bench_units": ["Ekko"],
    "shop_units": ["Jinx"],
    "traits_active": ["Vanguard 2"],
    "augments": [],
    "level": 7,
    "hp": 80,
    "gold": 30,
}


def _mk(tmpdir, resp):
    """Construct TftLiveAnalysis with no network and a fake model client."""
    import threading

    obj = tla.TftLiveAnalysis.__new__(tla.TftLiveAnalysis)
    obj._client = _FakeClient(resp)
    obj._model = "claude-haiku-4-5-20251001"
    obj._data_file = Path(tmpdir) / "tft_live_data.json"
    obj._vision = None
    obj._lock = threading.Lock()
    obj._running = False
    obj._thread = None
    obj._last_round = (0, 0)
    obj._last_vision = 0.0
    obj._last_write = {}
    obj._coach_state = {"stage_round": "3-2", "level": 7}
    obj._vision_interval = 15.0
    obj._debug = False
    obj._known_augments = []
    obj._last_placement = ""
    obj._force_flag = False
    obj._round_start_time = 0.0
    obj._scanned_planning = False
    obj._scanned_mid = False
    obj._ai_bar = None
    return obj


class _NoProxy:
    """Stand-in for core.moon_proxy.moon_proxy that always declines."""

    @staticmethod
    def get_coaching(prompt, model=""):
        return None


class TftLiveAnalysisAuditTest(unittest.TestCase):

    def setUp(self):
        import tempfile

        self._td = tempfile.mkdtemp(prefix="lane8c43_")
        self.tmp = Path(self._td)
        # Force the local-fallback model path: the proxy declines.
        import core.moon_proxy as _mp

        self._real_proxy = _mp.moon_proxy
        _mp.moon_proxy = _NoProxy()
        # Neutralize the cost gate so _run_analysis is never short-circuited.
        import core.cost_tracker as _ct

        self._real_gt = _ct.get_tracker
        _ct.get_tracker = lambda: types.SimpleNamespace(
            gate_disabled=lambda _m: False)

    def tearDown(self):
        import shutil

        import core.cost_tracker as _ct
        import core.moon_proxy as _mp

        _mp.moon_proxy = self._real_proxy
        _ct.get_tracker = self._real_gt
        shutil.rmtree(self._td, ignore_errors=True)

    def _read(self, obj):
        return json.loads(obj._data_file.read_text(encoding="utf-8"))

    # ---- W1: the model response shape ------------------------------------

    def test_w1a_empty_content_list_does_not_lose_the_cycle(self):
        """A response with content=[] must not IndexError into a silent no-op.

        max_tokens=500 with a long prompt can stop before any block is
        emitted. Pre-fix this raised IndexError inside the blanket handler,
        so nothing was written and nothing user-visible said why.
        """
        obj = _mk(self.tmp, _FakeResp([]))
        obj._run_analysis(dict(_VS))          # must not raise
        self.assertTrue(obj._data_file.exists(),
                        "empty content produced no write at all")
        self.assertTrue(self._read(obj).get("degraded"),
                        "empty content must publish a degraded marker")

    def test_w1b_leading_thinking_block_does_not_lose_the_cycle(self):
        """content[0] need not be a text block; .text then AttributeErrors.

        REACHABILITY, stated because the refutation pass caught the overclaim:
        neither messages.create call passes a `thinking` parameter, so the SDK
        cannot emit a thinking block at these two sites TODAY. Only the empty
        content list (test_w1a) is live. This guard is defence for the day a
        thinking parameter is added, and it is honest about being that.
        """
        obj = _mk(self.tmp, _FakeResp([_FakeBlock(), _TextBlock(_GOOD_RAW)]))
        obj._run_analysis(dict(_VS))
        data = self._read(obj)
        self.assertEqual(data.get("comp"), "Vanguard Jinx",
                         "the text block after a thinking block was not used")

    def test_w1c_text_block_still_parses_normally(self):
        """Characterization: the happy path is unchanged."""
        obj = _mk(self.tmp, _FakeResp([_TextBlock(_GOOD_RAW)]))
        obj._run_analysis(dict(_VS))
        data = self._read(obj)
        self.assertEqual(data.get("comp"), "Vanguard Jinx")
        self.assertEqual(data.get("unit_placement"), "Jinx D7")
        # assertFalse would also pass when the key is ABSENT, which is the
        # pre-fix shape - pin the value itself.
        self.assertIs(data.get("degraded"), False)

    # ---- W2: malformed operator-authored side file -----------------------

    def test_w2_non_string_unit_presence_entries_do_not_kill_the_scan(self):
        """unit_presence.json is written by another surface; it can be wrong.

        Pre-fix the `", ".join(_bc)` sat OUTSIDE both try blocks, so a
        non-string entry raised TypeError out of _run_analysis, through
        _run_cycle's bare try/finally, into _loop's blanket handler - killing
        every scan for as long as the bad file stayed on disk.
        """
        obj = _mk(self.tmp, _FakeResp([_TextBlock(_GOOD_RAW)]))
        (self.tmp / "unit_presence.json").write_text(
            json.dumps({"board_confirmed": [1, 2], "extra_present": "Jinx"}),
            encoding="utf-8")
        obj._run_analysis(dict(_VS))          # must not raise
        self.assertEqual(self._read(obj).get("comp"), "Vanguard Jinx")

    def test_w2b_valid_unit_presence_still_reaches_the_prompt(self):
        """Characterization + guard: sanitizing must not drop good data."""
        seen = {}
        obj = _mk(self.tmp, _FakeResp([_TextBlock(_GOOD_RAW)]))

        class _Spy:
            @staticmethod
            def get_coaching(prompt, model=""):
                seen["p"] = prompt
                return _GOOD_RAW

        import core.moon_proxy as _mp

        _mp.moon_proxy = _Spy()
        (self.tmp / "unit_presence.json").write_text(
            json.dumps({"board_confirmed": ["Jinx"], "manual_level": 8}),
            encoding="utf-8")
        obj._run_analysis(dict(_VS))
        self.assertIn("CONFIRMED ON BOARD: Jinx", seen.get("p", ""))
        self.assertIn("CURRENT LEVEL: 8", seen.get("p", ""))

    # ---- W3: freshness fields hostage to the advice-change gate ----------

    def test_w3_state_fields_refresh_even_when_advice_is_unchanged(self):
        """The write gate compares only six ADVICE keys.

        Pre-fix, a round where the advice happened to repeat published
        nothing, so stage_round / hp / board_units stayed frozen at the
        previous round's values for every polling reader.
        """
        obj = _mk(self.tmp, _FakeResp([_TextBlock(_GOOD_RAW)]))
        f = tla._parse_analysis(_GOOD_RAW)
        obj._write(dict(_VS), f, {"stage_round": "3-2"})
        self.assertEqual(self._read(obj)["stage_round"], "3-2")
        vs2 = dict(_VS)
        vs2["hp"] = 55
        obj._write(vs2, f, {"stage_round": "3-5"})
        data = self._read(obj)
        self.assertEqual(data["stage_round"], "3-5",
                         "stage_round froze when advice repeated")
        self.assertEqual(data["hp"], 55,
                         "hp froze when advice repeated")

    # ---- W4: RM-261 shared scratch name (enumerated site :452) ------------

    def test_w4_writes_go_through_the_atomic_contract_module(self):
        """core/feature_policy.py:_write_json writes the SAME destination and
        derived its scratch from the destination too, so both writers opened
        data/tft_live_data.tmp. That is the torn-destination defect lane 8
        cycle 24 measured and fixed in core/polled_json.py; this file is the
        enumerated RM-261 site :452.
        """
        src = (_ROOT / "tft" / "tft_live_analysis.py").read_text(
            encoding="utf-8")
        self.assertNotIn('with_suffix(".tmp")', src,
                         "still derives a scratch name from the destination")
        self.assertNotIn('with_suffix(".json.tmp")', src,
                         "force_scan still derives a shared scratch name")
        self.assertIn("atomic_write_json", src,
                      "does not route through core/polled_json.py")

    def test_w4b_the_shared_scratch_name_is_not_touched(self):
        """The discriminating observation, not a post-condition of success.

        The first version of this test asserted only that no litter REMAINED
        after a write - which the pre-fix code also satisfied, because
        `tmp.replace(path)` renames the scratch file away on success. It could
        not observe the scratch NAME at all and was therefore vacuous.

        This version plants a sentinel at the destination-derived name that
        core/feature_policy.py:440 and coaches/_base_coach.py:94 both still
        use for this file. A writer that shares the name truncates it; a
        per-writer name leaves it exactly as found.
        """
        obj = _mk(self.tmp, _FakeResp([_TextBlock(_GOOD_RAW)]))
        shared = self.tmp / "tft_live_data.tmp"
        shared.write_text("SENTINEL-OTHER-WRITER", encoding="utf-8")
        tla._write(obj._data_file, {"mode": "tft_live", "comp": "x"})
        self.assertTrue(shared.exists(),
                        "the shared scratch name was consumed by this writer")
        self.assertEqual(shared.read_text(encoding="utf-8"),
                         "SENTINEL-OTHER-WRITER",
                         "another writer's scratch file was truncated")
        self.assertEqual(json.loads(
            obj._data_file.read_text(encoding="utf-8"))["comp"], "x")
        leftovers = sorted(p.name for p in self.tmp.iterdir())
        self.assertEqual(leftovers, ["tft_live_data.json", "tft_live_data.tmp"],
                         "write left its own scratch litter behind")

    # ---- W5: the secret must never reach a log or a repr -----------------

    def test_w5_upstream_error_text_is_redacted_before_it_is_logged(self):
        """The key comes from API-Key-Claude.txt via coaches/tft_pbe_coach.py
        _read_api_key and core/tft_worker.py. A raised SDK error is formatted
        into logger.error on this path, so the leak would be silent.
        """
        obj = _mk(self.tmp, RuntimeError("401 unauthorized for " + _KEY))
        records = []

        class _Cap(logging.Handler):
            def emit(self, rec):
                records.append(self.format(rec))

        h = _Cap()
        h.setFormatter(logging.Formatter("%(message)s"))
        lg = logging.getLogger("rc.tft.live")
        lg.addHandler(h)
        lg.setLevel(logging.DEBUG)
        try:
            obj._run_analysis(dict(_VS))
        finally:
            lg.removeHandler(h)
        self.assertTrue(records, "the failure path logged nothing at all")
        for r in records:
            self.assertNotIn(_KEY, r, "API key reached a log record")
        # NOTE: no repr() assertion here. The object never stores the key on
        # an attribute, so asserting it is absent from the default repr is
        # tautological and would pass with the redaction removed.

    def test_w5b_upstream_failure_publishes_degraded_text_not_the_error(self):
        """CLAUDE.md 'Error Handling': never surface a raw API error string;
        render a friendly degraded message and log the raw error.
        """
        obj = _mk(self.tmp, RuntimeError("credit balance is too low: 400"))
        obj._run_analysis(dict(_VS))
        self.assertTrue(obj._data_file.exists(),
                        "an upstream failure published nothing")
        data = self._read(obj)
        blob = json.dumps(data)
        self.assertNotIn("credit balance", blob,
                         "raw API error string reached the TFT panel")
        self.assertNotIn("400", blob)
        self.assertTrue(data.get("degraded"))

    def test_w5c_recovery_clears_degraded_even_when_advice_is_unchanged(self):
        """Regression on the FIX itself, found reviewing this slice's own diff.

        _publish_degraded writes without touching _last_write, so if the very
        next cycle succeeds with byte-identical advice the payload equals
        _last_write and the write gate suppresses it - leaving degraded=True
        on disk after the outage had already cleared. Publishing degraded
        must invalidate the gate.
        """
        obj = _mk(self.tmp, _FakeResp([_TextBlock(_GOOD_RAW)]))
        obj._run_analysis(dict(_VS))
        self.assertFalse(self._read(obj).get("degraded"))

        obj._client = _FakeClient(RuntimeError("upstream 529"))
        obj._run_analysis(dict(_VS))
        self.assertTrue(self._read(obj).get("degraded"), "outage not published")

        obj._client = _FakeClient(_FakeResp([_TextBlock(_GOOD_RAW)]))
        obj._run_analysis(dict(_VS))
        data = self._read(obj)
        self.assertFalse(data.get("degraded"),
                         "panel stayed degraded after recovery")
        self.assertEqual(data.get("comp"), "Vanguard Jinx")

    # ---- W7: the encoding contract this slice itself changed -------------

    def test_w7_every_reader_of_the_file_decodes_it_as_utf8(self):
        """Routing _write through atomic_write_json changed the BYTES.

        core/polled_json.py serializes with ensure_ascii=False, so this file
        can now hold raw UTF-8 where the old json.dumps default escaped
        everything to ASCII. Two readers in tft/tft_coach_engine.py called
        .read_text() with NO encoding, which on Windows resolves to the
        locale codepage. That happens to work on this box only because
        PYTHONUTF8=1 is set in the ENVIRONMENT, and no launcher in this repo
        sets it - a grep for PYTHONUTF8 over the tracked py/bat/ps1/json
        surface returns nothing. A model reply carrying a curly apostrophe
        would then mojibake or raise under cp1252.

        Structural because the failure is environment-dependent and cannot be
        forced portably - the reasoning cycle 24 used for its scratch-name
        guards.
        """
        import re as _re

        src = (_ROOT / "tft" / "tft_coach_engine.py").read_text(
            encoding="utf-8")
        bare = _re.findall(r"read_text\(\s*\)", src)
        self.assertEqual(
            bare, [],
            "tft_coach_engine.py still calls read_text() with no encoding; "
            "those reads decode this file with the platform codepage")

    def test_w7b_non_ascii_advice_round_trips_through_the_writer(self):
        """A model reply can contain a curly apostrophe or a dash."""
        name = "Kai" + chr(0x2019) + "Sa"
        body = "Comp: " + name + " reroll\nBuy: none\n"
        obj = _mk(self.tmp, _FakeResp([_TextBlock(body)]))
        obj._run_analysis(dict(_VS))
        raw = obj._data_file.read_bytes()
        self.assertIn(name.encode("utf-8"), raw,
                      "payload was not written as UTF-8 bytes")
        self.assertEqual(json.loads(raw.decode("utf-8"))["comp"],
                         name + " reroll")

    # ---- W6: the scanning-state leak (LATENT - see the ledger) -----------

    def test_w6_scan_state_is_released_on_every_exit_path(self):
        """_notify_done() sat on two of four exits, so the SPECTATING return
        and any vision exception left the bar mid-scan forever.

        LATENT, not live: TftAiStatusBar is defined NOWHERE in the repo and
        wire_ai_bar() has zero production callers, so _ai_bar is permanently
        None today. Fixed structurally so it cannot resurface if a bar is
        ever wired.
        """
        calls = []

        class _Bar:
            def set_scanning(self, pct=0):
                calls.append(("scanning", pct))

            def set_done(self):
                calls.append(("done", None))

            def notify_scan_scheduled(self, at):
                pass

        class _Vision:
            @staticmethod
            def read():
                return {"board_units": ["SPECTATING"]}

        obj = _mk(self.tmp, _FakeResp([_TextBlock(_GOOD_RAW)]))
        obj._vision = _Vision()
        obj._ai_bar = _Bar()
        obj._run_cycle()
        self.assertIn(("done", None), calls,
                      "SPECTATING exit never cleared the scanning state")

        calls.clear()

        class _Boom:
            @staticmethod
            def read():
                raise RuntimeError("vision died")

        obj._vision = _Boom()
        try:
            obj._run_cycle()
        except RuntimeError:
            pass
        self.assertIn(("done", None), calls,
                      "a vision exception left the bar mid-scan")


if __name__ == "__main__":
    unittest.main()
