"""Tests for tools/gamepc_phase_watcher.py - LCU WAMP event-driven capture.

Item 207: implementation of docs/LCU_PHASE_CAPTURE_WATCHER_PLAN.md. The
watcher runs on Game-PC and fires DXGI capture on phase transitions
(champ-select / Cherry augment / lobby / InProgress). WaitingForStats is
intentionally EXCLUDED (2026-05-27 item 209): the WaitingForStats edge
fires at the game-end resolution swap (1920x1080 <-> 1440p), so a DXGI
grab there is unreliable. PGR captures must be driven by a post-swap
trigger, not the WAMP edge.

TDD-first per CLAUDE.md. Suite is stdlib-only and stub-driven so it runs
on any platform (no LCU + no DXGI + no network).

Operator scope-fork answers locked at session start:
- Q1 capture target: BOTH monitors per event
- Q2 debounce: per (topic, sub_phase, queue_id) per gameflow cycle
- Q3 frame format: JPEG q75 (inherit gamepc_screen_agent.py)
- Q4 Cherry urgency: standard debounce
- Q5 bridge envelope: YES emit kind=ui_capture on Legion bridge
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO = Path(__file__).resolve().parents[1]
_WATCHER_PATH = _REPO / "tools" / "gamepc_phase_watcher.py"


def _load_watcher_module():
    """Load tools/gamepc_phase_watcher.py without booting the WAMP loop."""
    spec = importlib.util.spec_from_file_location(
        "_gamepc_phase_watcher_under_test", _WATCHER_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class ClassifyGameflowPhaseTests(unittest.TestCase):
    """The watcher subscribes to /lol-gameflow/v1/gameflow-phase and only
    captures on transitions to ChampSelect / InProgress.
    Other phases (Lobby / Matchmaking / ReadyCheck / EndOfGame /
    WaitingForStats / None) return None. WaitingForStats is excluded per
    item 209 (the game-end resolution swap coincides with the WAMP edge,
    so a grab there is unreliable).
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_champ_select_transition_captured(self):
        out = self.mod.classify_gameflow_phase("ChampSelect", queue_id=420)
        self.assertEqual(out, ("gameflow_phase", "ChampSelect", 420))

    def test_in_progress_transition_captured(self):
        out = self.mod.classify_gameflow_phase("InProgress", queue_id=1750)
        self.assertEqual(out, ("gameflow_phase", "InProgress", 1750))

    def test_waiting_for_stats_NOT_captured_item_209(self):
        # Item 209 (2026-05-27): WaitingForStats fires at the game-end
        # resolution swap (1920x1080 <-> 1440p), so a DXGI grab there is
        # unreliable. DO NOT re-add. PGR captures must come from a
        # post-swap trigger.
        out = self.mod.classify_gameflow_phase("WaitingForStats", queue_id=450)
        self.assertIsNone(out)

    def test_inprogress_capture_delay_constant_defined(self):
        # Item 209 sibling fix: the InProgress WAMP edge coincides with
        # the game-start resolution swap. handle_event sleeps
        # INPROGRESS_CAPTURE_DELAY_S past the edge before binding DXGI.
        delay = getattr(self.mod, "INPROGRESS_CAPTURE_DELAY_S", None)
        self.assertIsNotNone(delay,
                             "module must expose INPROGRESS_CAPTURE_DELAY_S "
                             "constant for swap-safe InProgress capture")
        self.assertGreaterEqual(float(delay), 5.0,
                                "delay must be >=5s to clear the resolution "
                                "swap; 15s is the calibrated default")

    def test_lobby_phase_not_captured_here(self):
        # Lobby is captured via /lol-lobby/v2/lobby topic, not gameflow.
        out = self.mod.classify_gameflow_phase("Lobby", queue_id=420)
        self.assertIsNone(out)

    def test_ready_check_not_captured(self):
        out = self.mod.classify_gameflow_phase("ReadyCheck", queue_id=420)
        self.assertIsNone(out)

    def test_matchmaking_not_captured(self):
        out = self.mod.classify_gameflow_phase("Matchmaking", queue_id=420)
        self.assertIsNone(out)

    def test_end_of_game_not_captured(self):
        out = self.mod.classify_gameflow_phase("EndOfGame", queue_id=420)
        self.assertIsNone(out)

    def test_none_phase_returns_none(self):
        out = self.mod.classify_gameflow_phase(None, queue_id=None)
        self.assertIsNone(out)

    def test_unknown_phase_returns_none_does_not_raise(self):
        # Drift guard: a future LCU adding a new phase string must not
        # crash the watcher. None means "don't capture; logged at INFO".
        out = self.mod.classify_gameflow_phase("RiotBlitz", queue_id=420)
        self.assertIsNone(out)


class ClassifyChampSelectSessionTests(unittest.TestCase):
    """/lol-champ-select/v1/session: fire on timer.phase transitions
    PLANNING -> BAN_PICK -> FINALIZATION. Item 184 carry.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_planning_phase_captured(self):
        payload = {"timer": {"phase": "PLANNING"}, "gameId": 0}
        out = self.mod.classify_champ_select_session(payload, queue_id=420)
        self.assertEqual(out, ("champ_select_session", "PLANNING", 420))

    def test_ban_pick_phase_captured(self):
        payload = {"timer": {"phase": "BAN_PICK"}, "gameId": 0}
        out = self.mod.classify_champ_select_session(payload, queue_id=1750)
        self.assertEqual(out, ("champ_select_session", "BAN_PICK", 1750))

    def test_finalization_phase_captured(self):
        payload = {"timer": {"phase": "FINALIZATION"}, "gameId": 0}
        out = self.mod.classify_champ_select_session(payload, queue_id=450)
        self.assertEqual(out, ("champ_select_session", "FINALIZATION", 450))

    def test_missing_timer_returns_none(self):
        out = self.mod.classify_champ_select_session({}, queue_id=420)
        self.assertIsNone(out)

    def test_missing_phase_returns_none(self):
        out = self.mod.classify_champ_select_session(
            {"timer": {}}, queue_id=420)
        self.assertIsNone(out)

    def test_unknown_phase_returns_none(self):
        out = self.mod.classify_champ_select_session(
            {"timer": {"phase": "BAN_PICK_PRESELECT"}}, queue_id=420)
        self.assertIsNone(out)


class ClassifyCherryAugmentsTests(unittest.TestCase):
    """/lol-cherry-game-intra-event/v1/augments: fire when available[] is
    first observed non-empty per gameflow cycle. Item 187 Slice C carry.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_non_empty_available_captured(self):
        payload = {"available": [1, 2, 3, 4], "selected": []}
        out = self.mod.classify_cherry_augments(payload, queue_id=1750)
        self.assertEqual(out, ("cherry_augments", "available", 1750))

    def test_empty_available_not_captured(self):
        payload = {"available": [], "selected": []}
        out = self.mod.classify_cherry_augments(payload, queue_id=1750)
        self.assertIsNone(out)

    def test_missing_available_not_captured(self):
        out = self.mod.classify_cherry_augments({}, queue_id=1750)
        self.assertIsNone(out)

    def test_non_dict_payload_not_captured(self):
        out = self.mod.classify_cherry_augments(None, queue_id=1750)
        self.assertIsNone(out)
        out = self.mod.classify_cherry_augments([], queue_id=1750)
        self.assertIsNone(out)


class ClassifyLobbyTests(unittest.TestCase):
    """/lol-lobby/v2/lobby: capture on first non-null lobby + per-queue-id
    transition. Closes item 180 Arena 1750 + Practice Tool 3140 coverage.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_lobby_with_queue_id_captured(self):
        payload = {"gameConfig": {"queueId": 420}}
        out = self.mod.classify_lobby(payload)
        self.assertEqual(out, ("lobby", "joined", 420))

    def test_arena_1750_captured(self):
        payload = {"gameConfig": {"queueId": 1750}}
        out = self.mod.classify_lobby(payload)
        self.assertEqual(out, ("lobby", "joined", 1750))

    def test_practice_tool_3140_captured(self):
        payload = {"gameConfig": {"queueId": 3140}}
        out = self.mod.classify_lobby(payload)
        self.assertEqual(out, ("lobby", "joined", 3140))

    def test_null_lobby_not_captured(self):
        out = self.mod.classify_lobby(None)
        self.assertIsNone(out)

    def test_missing_game_config_not_captured(self):
        out = self.mod.classify_lobby({})
        self.assertIsNone(out)

    def test_missing_queue_id_not_captured(self):
        out = self.mod.classify_lobby({"gameConfig": {}})
        self.assertIsNone(out)


class DebouncerTests(unittest.TestCase):
    """Q2: 1 capture per (topic, sub_phase, queue_id) per gameflow cycle.
    Re-fire only after next post-game -> Lobby cycle (reset_cycle()).
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_first_fire_returns_true(self):
        deb = self.mod.Debouncer()
        self.assertTrue(deb.should_fire("gameflow_phase", "ChampSelect", 420))

    def test_repeat_fire_same_cycle_returns_false(self):
        deb = self.mod.Debouncer()
        self.assertTrue(deb.should_fire("gameflow_phase", "ChampSelect", 420))
        self.assertFalse(deb.should_fire("gameflow_phase", "ChampSelect", 420))
        self.assertFalse(deb.should_fire("gameflow_phase", "ChampSelect", 420))

    def test_different_sub_phase_same_topic_fires(self):
        deb = self.mod.Debouncer()
        self.assertTrue(deb.should_fire("gameflow_phase", "ChampSelect", 420))
        self.assertTrue(deb.should_fire("gameflow_phase", "InProgress", 420))

    def test_different_queue_id_same_topic_fires(self):
        deb = self.mod.Debouncer()
        self.assertTrue(deb.should_fire("lobby", "joined", 420))
        self.assertTrue(deb.should_fire("lobby", "joined", 1750))

    def test_reset_cycle_allows_refire(self):
        deb = self.mod.Debouncer()
        self.assertTrue(deb.should_fire("gameflow_phase", "ChampSelect", 420))
        self.assertFalse(deb.should_fire("gameflow_phase", "ChampSelect", 420))
        deb.reset_cycle()
        self.assertTrue(deb.should_fire("gameflow_phase", "ChampSelect", 420))


class WampMessageTests(unittest.TestCase):
    """WAMP-JSON v2 wire protocol parsing.

    EVENT messages from the LCU look like:
        [8, "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase",
         {"data": "ChampSelect", "eventType": "Update", "uri": "..."}]
    SUBSCRIBE messages we send look like:
        [5, "OnJsonApiEvent_<uri-with-underscores>"]
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_subscribe_frame_uses_message_type_5(self):
        frame = self.mod.build_subscribe_frame(
            "lol-gameflow/v1/gameflow-phase")
        decoded = json.loads(frame)
        self.assertEqual(decoded[0], 5)
        self.assertEqual(
            decoded[1], "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase")

    def test_subscribe_frame_converts_slashes_to_underscores(self):
        frame = self.mod.build_subscribe_frame(
            "lol-cherry-game-intra-event/v1/augments")
        decoded = json.loads(frame)
        self.assertEqual(
            decoded[1],
            "OnJsonApiEvent_lol-cherry-game-intra-event_v1_augments")

    def test_parse_event_returns_topic_event_type_data(self):
        raw = json.dumps([
            8,
            "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase",
            {"data": "ChampSelect", "eventType": "Update",
             "uri": "/lol-gameflow/v1/gameflow-phase"},
        ])
        out = self.mod.parse_wamp_event(raw)
        self.assertIsNotNone(out)
        topic, event_type, data = out
        self.assertEqual(topic, "/lol-gameflow/v1/gameflow-phase")
        self.assertEqual(event_type, "Update")
        self.assertEqual(data, "ChampSelect")

    def test_parse_non_event_message_returns_none(self):
        # [0, "subscribed", ...] etc - not WAMP type 8.
        raw = json.dumps([0, "subscribed", {}])
        out = self.mod.parse_wamp_event(raw)
        self.assertIsNone(out)

    def test_parse_garbage_returns_none(self):
        self.assertIsNone(self.mod.parse_wamp_event("not-json"))
        self.assertIsNone(self.mod.parse_wamp_event(""))
        self.assertIsNone(self.mod.parse_wamp_event(json.dumps({})))


class TopicDispatchTests(unittest.TestCase):
    """The watcher maps LCU topic strings (with slashes) to one of the
    classifier functions. Drift guard: every subscribed topic has an
    entry; an unknown topic does NOT raise.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_subscribed_topics_constant_includes_all_planned_topics(self):
        expected = {
            "/lol-gameflow/v1/gameflow-phase",
            "/lol-champ-select/v1/session",
            "/lol-cherry-game-intra-event/v1/augments",
            "/lol-cherry-game-intra-event/v1/augment-select",
            "/lol-lobby/v2/lobby",
        }
        self.assertEqual(set(self.mod.SUBSCRIBED_TOPICS), expected)

    def test_unknown_topic_dispatch_returns_none(self):
        out = self.mod.dispatch_topic("/lol-nonexistent/v1/thing",
                                       data="anything", queue_id=420)
        self.assertIsNone(out)


class SidecarWriteTests(unittest.TestCase):
    """Sidecar JSON written to data/event_captures/<topic>_<sub_phase>_
    <queue_id>_<iso>.json - distinct from data/coaching_data/ so it does
    NOT leak into coach-prompt context.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_sidecar_filename_shape(self):
        name = self.mod.sidecar_filename(
            "gameflow_phase", "ChampSelect", 420,
            captured_at_iso="2026-05-27T21-15-00Z")
        self.assertEqual(
            name, "gameflow_phase_ChampSelect_420_2026-05-27T21-15-00Z.json")

    def test_sidecar_writes_event_meta_to_disk(self, *_):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            meta = {
                "topic": "/lol-gameflow/v1/gameflow-phase",
                "sub_phase": "ChampSelect",
                "queue_id": 420,
                "captured_at": "2026-05-27T21:15:00Z",
            }
            frame_meta = [
                {"monitor": "game", "width": 1920, "height": 1080,
                 "format": "jpeg", "size": 200000},
                {"monitor": "dashboard", "width": 1920, "height": 1280,
                 "format": "jpeg", "size": 250000},
            ]
            path = self.mod.write_sidecar(base, meta, frame_meta)
            self.assertTrue(path.exists())
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written["topic"],
                             "/lol-gameflow/v1/gameflow-phase")
            self.assertEqual(written["sub_phase"], "ChampSelect")
            self.assertEqual(written["queue_id"], 420)
            self.assertEqual(len(written["frames"]), 2)
            self.assertEqual(written["frames"][0]["monitor"], "game")
            self.assertEqual(written["frames"][1]["monitor"], "dashboard")


class BridgeEnvelopeTests(unittest.TestCase):
    """Q5 (default YES): on every capture, emit kind=ui_capture envelope
    on the Legion bridge so the UI-audit-ritual subagent can subscribe to
    event-tagged frames specifically.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_envelope_shape(self):
        env = self.mod.build_bridge_envelope(
            topic="/lol-gameflow/v1/gameflow-phase",
            sub_phase="ChampSelect",
            queue_id=420,
            captured_at="2026-05-27T21:15:00Z",
            frames=[
                {"monitor": "game", "width": 1920, "height": 1080},
                {"monitor": "dashboard", "width": 1920, "height": 1280},
            ],
        )
        self.assertEqual(env["kind"], "ui_capture")
        self.assertEqual(env["source"], "gamepc")
        self.assertEqual(env["target"], "legion")
        self.assertIn("summary", env)
        self.assertIn("body", env)
        body = env["body"]
        self.assertEqual(body["topic"], "/lol-gameflow/v1/gameflow-phase")
        self.assertEqual(body["sub_phase"], "ChampSelect")
        self.assertEqual(body["queue_id"], 420)
        self.assertEqual(body["captured_at"], "2026-05-27T21:15:00Z")
        self.assertEqual(len(body["frames"]), 2)

    def test_envelope_id_field_present(self):
        env = self.mod.build_bridge_envelope(
            topic="/lol-lobby/v2/lobby",
            sub_phase="joined",
            queue_id=1750,
            captured_at="2026-05-27T21:15:00Z",
            frames=[{"monitor": "game"}],
        )
        self.assertIn("id", env)
        # IDs are short hex slugs per bridge convention.
        self.assertGreater(len(env["id"]), 4)

    def test_summary_includes_topic_and_queue(self):
        env = self.mod.build_bridge_envelope(
            topic="/lol-cherry-game-intra-event/v1/augments",
            sub_phase="available",
            queue_id=1750,
            captured_at="2026-05-27T21:15:00Z",
            frames=[{"monitor": "game"}, {"monitor": "dashboard"}],
        )
        s = env["summary"]
        self.assertIn("available", s)
        self.assertIn("1750", s)


class UploadFramePayloadShapeTests(unittest.TestCase):
    """The upload helper packages JPEG b64 + source + dimensions in the
    same shape as gamepc_screen_agent.py.upload(), plus an event_meta
    dict that the extended /upload-frame route reads.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_payload_includes_image_b64_source_event_meta(self):
        payload = self.mod.build_upload_payload(
            b64="abc=", fmt="jpeg", w=1920, h=1080,
            source="game-pc-event-game", primary=False,
            event_meta={
                "topic": "/lol-gameflow/v1/gameflow-phase",
                "sub_phase": "ChampSelect",
                "queue_id": 420,
                "captured_at": "2026-05-27T21:15:00Z",
                "monitor": "game",
            },
        )
        self.assertEqual(payload["image_b64"], "abc=")
        self.assertEqual(payload["source"], "game-pc-event-game")
        self.assertEqual(payload["format"], "jpeg")
        self.assertEqual(payload["width"], 1920)
        self.assertEqual(payload["height"], 1080)
        self.assertEqual(payload["primary"], False)
        self.assertIn("event_meta", payload)
        self.assertEqual(payload["event_meta"]["queue_id"], 420)


class BothMonitorsCaptureTests(unittest.TestCase):
    """Q1 (locked): BOTH monitors captured per event. The capture helper
    returns a list of per-monitor (b64, fmt, w, h, label) tuples.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_capture_both_monitors_returns_two_entries(self):
        # Operator's real setup: monitor 0 = 1920x1080 (game),
        # monitor 1 = 1920x1280 (dashboard). Resolution-based classifier
        # maps to {"game", "dashboard"}.
        def fake_capture(idx):
            return ("b64", "jpeg", 1920, 1080) if idx == 0 \
                else ("b64", "jpeg", 1920, 1280)

        with patch.object(self.mod, "_capture_one_monitor", fake_capture):
            out = self.mod.capture_both_monitors()
        self.assertEqual(len(out), 2)
        labels = [e["monitor"] for e in out]
        self.assertEqual(set(labels), {"game", "dashboard"})

    def test_capture_classifies_monitors_by_resolution(self):
        # 1920x1080 = game; 1920x1280 = dashboard. Index swaps across
        # reboots per reference_gamepc_monitor_index_volatility memory.
        def fake_capture(idx):
            if idx == 0:
                return ("game_b64", "jpeg", 1920, 1080)
            return ("dash_b64", "jpeg", 1920, 1280)

        with patch.object(self.mod, "_capture_one_monitor", fake_capture):
            out = self.mod.capture_both_monitors()
        by_label = {e["monitor"]: e for e in out}
        self.assertEqual(by_label["game"]["height"], 1080)
        self.assertEqual(by_label["dashboard"]["height"], 1280)


class JpegQualityDefaultTests(unittest.TestCase):
    """Q3 (locked): JPEG q75 default to inherit gamepc_screen_agent.py
    contract. Drift guard catches a future re-tune that drops the
    quality without an explicit operator decision.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_jpeg_quality_constant_is_75(self):
        self.assertEqual(self.mod.JPEG_QUALITY, 75)

    def test_format_constant_is_jpeg(self):
        self.assertEqual(self.mod.USE_JPEG, True)


class AsciiHygieneTests(unittest.TestCase):
    """No em-dashes / en-dashes / smart quotes per CLAUDE.md hard rule."""

    def test_watcher_source_is_ascii_clean(self):
        raw = _WATCHER_PATH.read_bytes()
        banned = {
            "em-dash": b"\xe2\x80\x94",
            "en-dash": b"\xe2\x80\x93",
            "smart-left-double": b"\xe2\x80\x9c",
            "smart-right-double": b"\xe2\x80\x9d",
            "smart-left-single": b"\xe2\x80\x98",
            "smart-right-single": b"\xe2\x80\x99",
        }
        for label, seq in banned.items():
            count = raw.count(seq)
            self.assertEqual(
                count, 0,
                f"watcher source contains {count} x {label} byte(s)",
            )

    def test_test_source_is_ascii_clean(self):
        raw = Path(__file__).read_bytes()
        banned = {
            "em-dash": b"\xe2\x80\x94",
            "en-dash": b"\xe2\x80\x93",
            "smart-left-double": b"\xe2\x80\x9c",
            "smart-right-double": b"\xe2\x80\x9d",
            "smart-left-single": b"\xe2\x80\x98",
            "smart-right-single": b"\xe2\x80\x99",
        }
        for label, seq in banned.items():
            count = raw.count(seq)
            self.assertEqual(
                count, 0,
                f"test source contains {count} x {label} byte(s)",
            )


class WiredSitesGrepTests(unittest.TestCase):
    """Pins the watcher to the planned helpers + constants so a future
    refactor that renames them fails CI before any live event misses
    its capture.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _WATCHER_PATH.read_text(encoding="utf-8")

    def test_subscribed_topics_constant_defined(self):
        self.assertIn("SUBSCRIBED_TOPICS", self.text)

    def test_debouncer_class_defined(self):
        self.assertIn("class Debouncer", self.text)

    def test_build_subscribe_frame_defined(self):
        self.assertIn("def build_subscribe_frame", self.text)

    def test_parse_wamp_event_defined(self):
        self.assertIn("def parse_wamp_event", self.text)

    def test_dispatch_topic_defined(self):
        self.assertIn("def dispatch_topic", self.text)

    def test_capture_both_monitors_defined(self):
        self.assertIn("def capture_both_monitors", self.text)

    def test_build_upload_payload_defined(self):
        self.assertIn("def build_upload_payload", self.text)

    def test_build_bridge_envelope_defined(self):
        self.assertIn("def build_bridge_envelope", self.text)

    def test_write_sidecar_defined(self):
        self.assertIn("def write_sidecar", self.text)

    def test_sidecar_filename_defined(self):
        self.assertIn("def sidecar_filename", self.text)

    def test_jpeg_quality_constant_inherits_gamepc_screen_agent(self):
        # Inherits the 75 baseline; if operator decides to bump later, the
        # constant moves in lockstep with gamepc_screen_agent.py.
        self.assertIn("JPEG_QUALITY = 75", self.text)


class DispatchIntegrationTests(unittest.TestCase):
    """End-to-end through the dispatcher: WAMP frame -> classifier ->
    debouncer -> capture builder. No actual capture or network here;
    the test patches the capture + upload sinks.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_watcher_module()

    def test_dispatch_topic_routes_gameflow_phase_to_classifier(self):
        out = self.mod.dispatch_topic(
            "/lol-gameflow/v1/gameflow-phase",
            data="ChampSelect", queue_id=420)
        self.assertEqual(out, ("gameflow_phase", "ChampSelect", 420))

    def test_dispatch_topic_routes_lobby(self):
        out = self.mod.dispatch_topic(
            "/lol-lobby/v2/lobby",
            data={"gameConfig": {"queueId": 1750}}, queue_id=None)
        self.assertEqual(out, ("lobby", "joined", 1750))

    def test_dispatch_topic_routes_cherry_augments(self):
        out = self.mod.dispatch_topic(
            "/lol-cherry-game-intra-event/v1/augments",
            data={"available": [1, 2]}, queue_id=1750)
        self.assertEqual(out, ("cherry_augments", "available", 1750))

    def test_dispatch_topic_routes_champ_select(self):
        out = self.mod.dispatch_topic(
            "/lol-champ-select/v1/session",
            data={"timer": {"phase": "BAN_PICK"}}, queue_id=420)
        self.assertEqual(out, ("champ_select_session", "BAN_PICK", 420))


if __name__ == "__main__":
    unittest.main()
