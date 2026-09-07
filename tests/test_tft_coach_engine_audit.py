"""
Lane 8 (Headless-True-Audit) cycle 30 - regression corpus for
`tft/tft_coach_engine.py`, the LIVE TFT coach engine.

Target selected on four risk criteria at once: it reads `API-Key-Claude.txt`
(criterion 2), it writes `data/tft_coaching_data.json` which three separate
consumers poll (criterion 3), it parses a model response it does not author
(criterion 1), and it had NO dedicated test module before this one
(criterion 4).

20 of the 21 tests here were RED at 8bb010ba before the fix in the same
commit, and all 20 were mutation-tested (break the guarded production line,
confirm RED, restore).

The exception is TestAtomicWrites::test_write_status_output_is_valid_json,
which PASSES on the pre-fix code and is deliberately kept as a
CHARACTERIZATION test rather than a regression one: the old _write_status
already emitted valid JSON carrying `risk`, and only its atomicity was
wrong. It pins the payload contract that the RM-211 fix had to preserve.
Do not read it as evidence for that fix - its sibling
test_write_status_never_writes_the_destination_directly is.
"""

import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tft.tft_coach_engine import FIELD_MAP, TftCoachEngine, _parse_response


def _engine(tmp: Path) -> TftCoachEngine:
    """Build an engine without touching the real key file or config."""
    with patch.object(TftCoachEngine, "_read_key_file", return_value=""):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return TftCoachEngine(tmp / "tft_coaching_data.json")


class TestGodPickFieldContract(unittest.TestCase):
    """W1 - the system prompt requires `God pick:` every round; FIELD_MAP only
    knew `carousel`, so the advice was swallowed into the PRECEDING field and
    the key every consumer reads was never written."""

    def test_god_pick_line_is_parsed_into_its_own_field(self):
        r = _parse_response(
            "Action: ROLL\n"
            "Items: BF Sword on Jinx\n"
            "God pick: Evelynn boon\n"
            "Placement: D6\n"
        )
        self.assertEqual(r.get("god_pick"), "Evelynn boon")

    def test_god_pick_does_not_contaminate_the_items_field(self):
        r = _parse_response(
            "Items: BF Sword on Jinx\n"
            "God pick: Evelynn boon\n"
        )
        self.assertEqual(r.get("items"), "BF Sword on Jinx")
        self.assertNotIn("God pick", r.get("items", ""))

    def test_field_map_carries_the_key_the_payload_contract_declares(self):
        # core/coaching_payload.py TftPayload declares god_pick, and
        # coaches/tft_coach.py seeds the file with god_pick. The engine must
        # agree with both.
        self.assertIn("god_pick", FIELD_MAP.values())

    def test_written_payload_carries_god_pick(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            eng._write_fields("Action: ROLL\nGod pick: Soraka boon\n", {})
            got = json.loads((Path(d) / "tft_coaching_data.json").read_text("utf-8"))
            self.assertEqual(got.get("god_pick"), "Soraka boon")


class TestAtomicWrites(unittest.TestCase):
    """W2/W3/W4 - RM-211 plus the RM-254 shared-scratch class."""

    def test_write_status_never_writes_the_destination_directly(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            seen = []
            real = Path.write_text

            def spy(self, *a, **kw):
                seen.append(Path(self))
                return real(self, *a, **kw)

            with patch.object(Path, "write_text", spy):
                eng._write_status("Coaching paused - retrying")
            self.assertNotIn(eng._data_file, seen)

    def test_write_status_output_is_valid_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            eng._write_status("Coaching paused - retrying")
            got = json.loads(eng._data_file.read_text("utf-8"))
            self.assertEqual(got["risk"], "Coaching paused - retrying")

    def test_writers_do_not_share_one_scratch_filename(self):
        """reset_state runs on the game-lifecycle thread while _write_fields
        runs on the TftCoach daemon thread; a destination-derived scratch name
        means both open the SAME file and the destination is torn."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            names = []
            real_wb = Path.write_bytes
            real_wt = Path.write_text

            def spy_b(self, *a, **kw):
                names.append(Path(self).name)
                return real_wb(self, *a, **kw)

            def spy_t(self, *a, **kw):
                names.append(Path(self).name)
                return real_wt(self, *a, **kw)

            with patch.object(Path, "write_bytes", spy_b), \
                 patch.object(Path, "write_text", spy_t):
                eng.reset_state()
                eng._write_status("x")
                eng._write_fields("Action: ROLL\n", {})

            # Scope to this destination: _write_fields also stamps
            # data/coaching_ts_tft.json through core.coaching_timestamps,
            # which still hand-rolls a destination-derived scratch name
            # (RM-261 class, filed separately - not this module's file).
            scratch = [n for n in names
                       if n.startswith(eng._data_file.name) and n != eng._data_file.name]
            self.assertEqual(len(scratch), 3, f"expected 3 scratch writes, got {names}")
            self.assertEqual(len(set(scratch)), 3,
                             f"writers shared a scratch name: {scratch}")

    def test_replace_retries_on_windows_permission_error(self):
        """A poller holding the destination open makes os.replace raise
        WinError 5. A bare replace loses the coaching write for that tick."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            calls = {"n": 0}
            import core.polled_json as pj
            real = pj.os.replace

            def flaky(src, dst):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise PermissionError(5, "Access is denied")
                return real(src, dst)

            with patch.object(pj.os, "replace", flaky):
                eng._write_fields("Action: ROLL\n", {})
            self.assertGreaterEqual(calls["n"], 2, "no retry after WinError 5")
            self.assertTrue(eng._data_file.exists())

    def test_no_scratch_file_is_left_behind_on_failure(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            import core.polled_json as pj
            with patch.object(pj.os, "replace",
                              side_effect=PermissionError(5, "denied")):
                eng._write_fields("Action: ROLL\n", {})
            leftovers = [p.name for p in Path(d).iterdir()
                         if p.name != "tft_coaching_data.json"]
            self.assertEqual(leftovers, [], f"scratch litter: {leftovers}")

    def test_payload_bytes_are_not_crlf_inflated(self):
        """Path.write_text rewrites LF as CRLF on Windows; the live artifact
        was measured carrying 11 CRLF pairs."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            eng._write_fields("Action: ROLL\n", {})
            self.assertNotIn(b"\r\n", eng._data_file.read_bytes())


class TestEmptyFieldGuard(unittest.TestCase):
    """W5 - `fields['_stage_round']` was assigned BEFORE `if not fields`,
    so the guard was provably dead and unparseable model output blanked the
    overlay instead of retaining the last good advice."""

    def test_unparseable_response_does_not_overwrite_good_advice(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            eng._write_fields("Action: ROLL\nBoard: Jinx D7\n", {})
            before = eng._data_file.read_text("utf-8")
            eng._write_fields("I'm sorry, I can't help with that.", {})
            self.assertEqual(eng._data_file.read_text("utf-8"), before)

    def test_unparseable_response_is_logged(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            with self.assertLogs("rc.tft.coach", level="WARNING") as cm:
                eng._write_fields("no fields here at all", {})
            self.assertTrue(any("no fields parsed" in m for m in cm.output))


class TestRequestTimeout(unittest.TestCase):
    """W6 - self._timeout was assigned twice and never read, so the Anthropic
    call carried no timeout. A hung call holds self._lock, and every later
    submit logs 'busy - skipping' for as long as it hangs."""

    def test_configured_timeout_reaches_the_api_call(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            eng._timeout = 7

            class _Resp:
                content = [type("T", (), {"text": "Action: ROLL"})()]

            seen = {}

            class _Msgs:
                def create(self, **kw):
                    seen.update(kw)
                    return _Resp()

            eng._client = type("C", (), {"messages": _Msgs()})()
            eng._run({"stage": 2, "round": 1})
            self.assertEqual(seen.get("timeout"), 7)


class TestDegradedModeSignalling(unittest.TestCase):
    """W7/W8 - a missing API key logged 'ready' and then silently never
    coached; the spend-gate failed OPEN when its own import failed."""

    def test_missing_api_key_is_logged_as_disabled(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with self.assertLogs("rc.tft.coach", level="WARNING") as cm:
                _engine(Path(d))
            self.assertTrue(any("no api key" in m.lower() for m in cm.output),
                            f"no disabled-state warning: {cm.output}")

    def test_spend_gate_failure_does_not_fail_open(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            fired = {"n": 0}

            class _Msgs:
                def create(self, **kw):
                    fired["n"] += 1
                    raise AssertionError("api call made behind a broken gate")

            eng._client = type("C", (), {"messages": _Msgs()})()
            with patch.dict("sys.modules", {"core.cost_tracker": None}):
                eng._run({"stage": 2, "round": 1})
            self.assertEqual(fired["n"], 0)


class TestConfigValidation(unittest.TestCase):
    """W9 - config values were adopted with no type or range check, so a
    string debounce raised TypeError out of submit() into the poll loop."""

    def _write_cfg(self, payload):
        cfg = Path(__file__).parent.parent / "config" / "coach_settings.json"
        return cfg, payload

    def test_non_numeric_debounce_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            # The property under test is REJECTION - an invalid value is dropped
            # and the prior one kept - not a specific number. config/
            # coach_settings.json is GITIGNORED, so init legitimately differs by
            # box: CI has no file and lands on the code default 45.0, a dev box
            # may carry a local 15. Capturing `before` (as the sibling
            # test_non_string_model_is_rejected does) makes this hermetic;
            # hardcoding 45.0 failed on any box with a local config.
            before = eng._debounce_s
            eng._apply_config({"debounce_seconds": "not-a-number"})
            self.assertIsInstance(eng._debounce_s, (int, float))
            self.assertEqual(eng._debounce_s, before)

    def test_negative_debounce_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            eng._apply_config({"debounce_seconds": -5})
            self.assertGreaterEqual(eng._debounce_s, 0)

    def test_non_string_model_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            before = eng._model
            eng._apply_config({"model": 12345})
            self.assertEqual(eng._model, before)

    def test_submit_survives_a_hostile_config(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            eng._client = object()
            eng._apply_config({"debounce_seconds": "x", "max_tokens": -1,
                               "timeout": "y"})
            with patch.object(threading, "Thread"):
                eng.submit({"stage": 2, "round": 1, "health": 80})


class TestHpTypeAgreement(unittest.TestCase):
    """W10 - submit() accepted a STRING vision hp for the urgency gate while
    _write_fields rejected it for the rendered payload, and _write_fields
    accepted a BOOL (bool is an int subclass) as 1 hp."""

    def test_bool_vision_hp_is_not_rendered_as_one_hp(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            live = Path(__file__).parent.parent / "data" / "tft_live_data.json"
            with patch.object(Path, "read_text",
                              side_effect=lambda *a, **k: json.dumps({"hp": True})):
                hp = eng._resolve_hp({"health": 55})
            self.assertEqual(hp, 55)

    def test_string_vision_hp_agrees_across_both_paths(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            a = eng._vision_hp(lambda: {"hp": "45"})
            b = eng._vision_hp(lambda: {"hp": 45})
            self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
