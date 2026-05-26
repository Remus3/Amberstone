"""Drift guard: tools/bridge_dispatch_enable_lanes.py - item 199 Slice A.

Pins the ops_request envelope shape, sha256 checksum behavior, argparse
surface, dry-run discipline, idempotence path, and ASCII hygiene. The
script is the bridge-dispatched companion to docs/AUTO_ACTION_LANES_GATE_PROBE.md
step (3) - if these tests fail, the recipe doc is referencing a script
shape that no longer exists.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "tools" / "bridge_dispatch_enable_lanes.py"

sys.path.insert(0, str(ROOT / "tools"))
import bridge_dispatch_enable_lanes as bdel  # noqa: E402


class ScriptShapeTests(unittest.TestCase):
    """The script must exist as a runnable module under tools/."""

    def test_script_file_exists(self) -> None:
        self.assertTrue(SCRIPT_PATH.is_file(),
                        f"expected {SCRIPT_PATH}")

    def test_module_exports_canonical_callables(self) -> None:
        for name in ("compute_install_ps1_checksum", "build_envelope",
                     "peer_already_enabled", "post_envelope",
                     "build_parser", "main"):
            self.assertTrue(callable(getattr(bdel, name, None)),
                            f"missing top-level callable {name!r}")

    def test_module_exports_canonical_constants(self) -> None:
        self.assertEqual(bdel.VERB, "reinstall_bridge_watcher_with_lanes")
        self.assertEqual(bdel.VALID_TARGETS, ("gamepc", "peer"))
        self.assertIn("read", bdel.VALID_LANE_STRINGS)
        self.assertIn("ops", bdel.VALID_LANE_STRINGS)
        self.assertIn("read,ops", bdel.VALID_LANE_STRINGS)
        self.assertEqual(bdel.INSTALL_PS1_URL,
                         "https://legion-rc:8888/agent/bridge_watcher_install.ps1")


class ArgparseTests(unittest.TestCase):

    def test_parser_requires_target(self) -> None:
        parser = bdel.build_parser()
        buf = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stderr(buf):
            parser.parse_args([])

    def test_parser_rejects_unknown_target(self) -> None:
        parser = bdel.build_parser()
        buf = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stderr(buf):
            parser.parse_args(["--target", "legion"])

    def test_parser_rejects_unknown_lane_string(self) -> None:
        parser = bdel.build_parser()
        buf = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stderr(buf):
            parser.parse_args(["--target", "gamepc", "--lanes", "garbage"])

    def test_parser_default_lanes_is_read(self) -> None:
        parser = bdel.build_parser()
        ns = parser.parse_args(["--target", "gamepc"])
        self.assertEqual(ns.lanes, "read")
        self.assertFalse(ns.dry_run)
        self.assertFalse(ns.force)
        self.assertEqual(ns.source, "legion")

    def test_parser_accepts_read_ops(self) -> None:
        parser = bdel.build_parser()
        ns = parser.parse_args(["--target", "peer", "--lanes", "read,ops"])
        self.assertEqual(ns.target, "peer")
        self.assertEqual(ns.lanes, "read,ops")


class ChecksumTests(unittest.TestCase):

    def test_checksum_computes_from_real_install_ps1(self) -> None:
        # The live install.ps1 must exist (item 189 surface pinned elsewhere).
        digest = bdel.compute_install_ps1_checksum()
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))

    def test_checksum_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            bdel.compute_install_ps1_checksum(Path("/no/such/install.ps1"))

    def test_checksum_changes_with_content(self) -> None:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, mode="wb",
                                         suffix=".ps1") as fa:
            fa.write(b"abc")
            path_a = Path(fa.name)
        with tempfile.NamedTemporaryFile(delete=False, mode="wb",
                                         suffix=".ps1") as fb:
            fb.write(b"abcd")
            path_b = Path(fb.name)
        try:
            self.assertNotEqual(bdel.compute_install_ps1_checksum(path_a),
                                bdel.compute_install_ps1_checksum(path_b))
        finally:
            path_a.unlink(missing_ok=True)
            path_b.unlink(missing_ok=True)


class EnvelopeShapeTests(unittest.TestCase):

    def _baseline(self) -> dict:
        return bdel.build_envelope(
            "gamepc", "read",
            checksum="0" * 64,
            source="legion",
            task_id="task-fixed123",
            issued_ts=1700000000.0,
        )

    def test_envelope_has_required_top_level_fields(self) -> None:
        env = self._baseline()
        for k in ("kind", "id", "source", "target", "summary", "body"):
            self.assertIn(k, env)
        self.assertEqual(env["kind"], "task")
        self.assertEqual(env["target"], "gamepc")
        self.assertEqual(env["source"], "legion")
        self.assertEqual(env["id"], "task-fixed123")

    def test_envelope_body_has_required_fields(self) -> None:
        env = self._baseline()
        body = env["body"]
        for k in ("issued", "verb", "source_url", "checksum_sha256",
                  "lanes", "prompt"):
            self.assertIn(k, body, f"missing body.{k}")
        self.assertEqual(body["verb"], bdel.VERB)
        self.assertEqual(body["source_url"], bdel.INSTALL_PS1_URL)
        self.assertEqual(body["checksum_sha256"], "0" * 64)
        self.assertEqual(body["lanes"], "read")
        self.assertEqual(body["issued"], 1700000000.0)
        # Prompt must reference what the peer should do (verifies operator-
        # facing copy stays in step with the verb).
        self.assertIn("-EnableLanes", body["prompt"])
        self.assertIn("RC-BridgeWatcher", body["prompt"])

    def test_envelope_target_atx_round_trip(self) -> None:
        env = bdel.build_envelope("peer", "read,ops", checksum="a" * 64)
        self.assertEqual(env["target"], "peer")
        self.assertEqual(env["body"]["lanes"], "read,ops")

    def test_envelope_rejects_invalid_target(self) -> None:
        with self.assertRaises(ValueError):
            bdel.build_envelope("legion", "read", checksum="b" * 64)

    def test_envelope_rejects_invalid_lanes(self) -> None:
        with self.assertRaises(ValueError):
            bdel.build_envelope("gamepc", "garbage", checksum="c" * 64)

    def test_envelope_id_autogenerated_when_not_passed(self) -> None:
        env = bdel.build_envelope("gamepc", "read", checksum="d" * 64)
        self.assertTrue(env["id"].startswith("task-"))
        self.assertGreater(len(env["id"]), len("task-"))

    def test_envelope_is_json_serializable(self) -> None:
        env = self._baseline()
        encoded = json.dumps(env)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["body"]["verb"], bdel.VERB)


class DryRunDoesNotPOSTTests(unittest.TestCase):

    def test_dry_run_prints_envelope_no_network(self) -> None:
        # Sentinel: any call into urlopen during a --dry-run path is a bug.
        with mock.patch.object(bdel.urllib.request, "urlopen") as urlopen:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = bdel.main(["--target", "gamepc", "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertEqual(urlopen.call_count, 0,
                             "dry-run must not touch the network")
        out = buf.getvalue().strip()
        self.assertTrue(out.startswith("{"), out[:60])
        env = json.loads(out)
        self.assertEqual(env["kind"], "task")
        self.assertEqual(env["target"], "gamepc")
        self.assertEqual(env["body"]["verb"], bdel.VERB)


class IdempotenceProbeTests(unittest.TestCase):

    def test_already_enabled_when_health_lists_matching_lanes(self) -> None:
        payload = json.dumps({
            "peers": {"gamepc": {"enabled_lanes": ["read"]}},
        }).encode("utf-8")
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: False
        with mock.patch.object(bdel.urllib.request, "urlopen",
                               return_value=resp):
            self.assertTrue(bdel.peer_already_enabled("gamepc", "read"))

    def test_not_enabled_when_field_missing(self) -> None:
        # Most common today: heartbeat doesn't surface the field.
        payload = json.dumps({
            "peers": {"gamepc": {"alive": True}},
        }).encode("utf-8")
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: False
        with mock.patch.object(bdel.urllib.request, "urlopen",
                               return_value=resp):
            self.assertFalse(bdel.peer_already_enabled("gamepc", "read"))

    def test_probe_swallows_network_errors_returns_false(self) -> None:
        with mock.patch.object(bdel.urllib.request, "urlopen",
                               side_effect=OSError("conn refused")):
            self.assertFalse(bdel.peer_already_enabled("peer", "read"))


class AsciiHygieneTests(unittest.TestCase):
    """Per CLAUDE.md hard rule: no em-dashes, no smart quotes, ASCII only."""

    def test_script_ascii_only(self) -> None:
        text = SCRIPT_PATH.read_text(encoding="utf-8")
        self._assert_ascii_clean(text, str(SCRIPT_PATH))

    def test_test_file_ascii_only(self) -> None:
        self_path = Path(__file__).resolve()
        text = self_path.read_text(encoding="utf-8")
        self._assert_ascii_clean(text, str(self_path))

    def _assert_ascii_clean(self, text: str, label: str) -> None:
        # Probe for the specific banned codepoints in the no-em-dash rule.
        banned = {
            0x2013: "EN DASH",
            0x2014: "EM DASH",
            0x2018: "LEFT SINGLE QUOTE",
            0x2019: "RIGHT SINGLE QUOTE",
            0x201C: "LEFT DOUBLE QUOTE",
            0x201D: "RIGHT DOUBLE QUOTE",
        }
        for cp, name in banned.items():
            self.assertNotIn(chr(cp), text,
                             f"{label} contains banned {name} (U+{cp:04X})")


class FrozenFileNotTouchedTests(unittest.TestCase):
    """The dispatch script must not edit any frozen file at import time."""

    def test_import_does_not_write_frozen_files(self) -> None:
        # No-op: importing bridge_dispatch_enable_lanes only declares helpers.
        # Sanity-pin by re-importing and asserting frozen install.ps1 byte size
        # is unchanged compared to a fresh stat.
        import importlib
        install = ROOT / "tools" / "bridge_watcher_install.ps1"
        before = install.stat().st_size
        importlib.reload(bdel)
        after = install.stat().st_size
        self.assertEqual(before, after,
                         "import of dispatch helper must not mutate "
                         "tools/bridge_watcher_install.ps1 (frozen)")


if __name__ == "__main__":
    unittest.main()
