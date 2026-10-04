"""RM-638 (directive X-38, external reference C) - the mark-this-moment slot.

tools/hotkey_listener.py gains slot 5 on Ctrl+Shift+K. On press the dispatch
worker GETs :2999 /liveclientdata/gamestats (short timeout) and appends one
{game_id, game_time_s, wall_ts} line to the marks jsonl. If :2999 is down
(loading screen, no game) the mark is DROPPED and logged, never queued.

The :2999 here is a fake: a plain local HTTP server on an ephemeral port that
serves a synthetic gamestats body (up) or a closed port (down). The physical
in-game key press is live-gated and is not claimed by these tests.
"""
from __future__ import annotations

import json
import logging
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

if sys.platform != "win32":
    pytest.skip("Windows-only Win32 hotkey listener", allow_module_level=True)

import tools.hotkey_listener as hk  # noqa: E402


# -- combo -------------------------------------------------------------------

# League's DEFAULT Ctrl-chord binds, as the reasoning for the combo choice:
# Ctrl+Q/W/E/R level an ability, Ctrl+1..6 play emotes / the mastery badge,
# Ctrl+F toggles the FPS/ping readout. The listener's hook OBSERVES and never
# swallows, so League sees the chord too - a trigger letter League binds under
# Ctrl would double-fire. RC carries no League keybind data to probe against
# (no input.ini parser in the tree), so this list is the stated assumption.
_LEAGUE_CTRL_DEFAULT_KEYS = {ord(c) for c in "QWERF123456"}


def test_moment_mark_combo_is_ctrl_shift_k():
    assert hk._VK_K == 0x4B
    assert (hk._SLOT_MOMENT_MARK, hk._VK_K) in hk._HOTKEYS
    assert hk.HotkeyDecoder().on_keydown(hk._VK_K, ctrl=True, shift=True) \
        == hk._SLOT_MOMENT_MARK


def test_combo_does_not_collide_with_existing_hotkeys():
    slots = [s for s, _ in hk._HOTKEYS]
    vks = [v for _, v in hk._HOTKEYS]
    assert len(set(slots)) == len(slots), "duplicate slot in _HOTKEYS"
    assert len(set(vks)) == len(vks), "duplicate trigger key in _HOTKEYS"
    assert hk._SLOT_MOMENT_MARK not in (1, 2, hk._SLOT_OVERLAY_TOGGLE,
                                        hk._SLOT_OVERLAY_PANEL_CYCLE)


def test_combo_avoids_league_default_ctrl_binds():
    assert hk._VK_K not in _LEAGUE_CTRL_DEFAULT_KEYS


def test_moment_mark_needs_both_modifiers():
    assert hk.HotkeyDecoder().on_keydown(hk._VK_K, ctrl=True, shift=False) is None
    assert hk.HotkeyDecoder().on_keydown(hk._VK_K, ctrl=False, shift=True) is None


def test_dispatch_routes_slot_to_mark_handler(monkeypatch):
    seen = []
    monkeypatch.setattr(hk, "handle_moment_mark", lambda: seen.append("mark"))
    hk._dispatch_one(hk.DecisionCache(), hk._SLOT_MOMENT_MARK)
    assert seen == ["mark"]


# -- fake :2999 ----------------------------------------------------------------

class _Gamestats(BaseHTTPRequestHandler):
    body = {"gameMode": "CLASSIC", "gameTime": 754.321, "mapName": "Map11",
            "mapNumber": 11, "mapTerrain": "Default"}
    hits: list = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        data = json.dumps(type(self).body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # silence
        pass


@pytest.fixture
def fake_2999():
    _Gamestats.hits = []
    srv = HTTPServer(("127.0.0.1", 0), _Gamestats)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_press_with_2999_up_appends_one_mark(fake_2999, tmp_path):
    marks = tmp_path / "moment_marks.jsonl"
    mark = hk.handle_moment_mark(
        base_url=fake_2999, game_id_provider=lambda: "7001",
        marks_file=marks, now=lambda: 1_700_000_000.5)
    assert _Gamestats.hits == ["/liveclientdata/gamestats"]
    assert mark == {"game_id": "7001", "game_time_s": 754.321,
                    "wall_ts": 1_700_000_000.5}
    rows = [json.loads(x) for x in marks.read_text(encoding="ascii").splitlines()]
    assert rows == [mark]


def test_press_with_unknown_game_id_records_null(fake_2999, tmp_path):
    marks = tmp_path / "m.jsonl"
    mark = hk.handle_moment_mark(base_url=fake_2999, game_id_provider=lambda: "",
                                 marks_file=marks, now=lambda: 5.0)
    assert mark["game_id"] is None
    assert json.loads(marks.read_text(encoding="ascii"))["game_id"] is None


def test_press_with_2999_down_drops_and_logs(tmp_path, caplog):
    marks = tmp_path / "m.jsonl"
    with caplog.at_level(logging.INFO, logger="rc.hotkey"):
        mark = hk.handle_moment_mark(
            base_url=f"http://127.0.0.1:{_closed_port()}",
            game_id_provider=lambda: "7001", marks_file=marks, now=lambda: 5.0)
    assert mark is None
    assert not marks.exists(), "a dropped mark must not write anything"
    assert any("moment mark dropped" in r.getMessage() for r in caplog.records)


def test_press_with_garbage_gamestats_drops(fake_2999, tmp_path, monkeypatch):
    monkeypatch.setattr(_Gamestats, "body", {"gameMode": "CLASSIC"})
    marks = tmp_path / "m.jsonl"
    assert hk.handle_moment_mark(base_url=fake_2999, game_id_provider=lambda: "1",
                                 marks_file=marks, now=lambda: 5.0) is None
    assert not marks.exists()


def test_game_id_provider_failure_never_costs_the_mark(fake_2999, tmp_path):
    def boom():
        raise RuntimeError("relay down")
    marks = tmp_path / "m.jsonl"
    mark = hk.handle_moment_mark(base_url=fake_2999, game_id_provider=boom,
                                 marks_file=marks, now=lambda: 5.0)
    assert mark["game_id"] is None and marks.exists()


def test_mark_calls_the_rm637_replay_buffer_hook(fake_2999, tmp_path, monkeypatch):
    from core import moment_marks
    seen = []
    monkeypatch.setattr(moment_marks, "request_replay_buffer_save",
                        lambda m: seen.append(m) or False)
    mark = hk.handle_moment_mark(base_url=fake_2999, game_id_provider=lambda: "1",
                                 marks_file=tmp_path / "m.jsonl", now=lambda: 5.0)
    assert seen == [mark]


def test_mark_timeout_is_short():
    # A press must not stall the dispatch worker behind a hung :2999.
    assert 0 < hk.MARK_HTTP_TIMEOUT <= 1.5
