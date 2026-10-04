"""RM-296b: /api/loadout/apply must surface the vision server's command ids.

It read the `{"id": N}` reply of each /lcu-cmd enqueue and discarded it, so a
push the LCU agent later rejected could never be polled via
/api/lcu-cmd-result. The ids are now returned alongside `queued` (whose str
element type is unchanged for its existing consumers).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import routes_loadout as mod  # noqa: E402


class _H:
    def __init__(self):
        self.sent = None

    def _send(self, status, body, ctype):
        self.sent = (status, body, ctype)


def _resolved(*a):
    return {"ok": True, "mode": "sr", "label": "x",
            "rune_cmd": {"cmd": "apply_runes"},
            "item_cmd": {"cmd": "apply_item_set", "blocks": []},
            "summ_cmd": {"cmd": "set_summoners", "d": 4, "f": 14},
            "raw_items": []}


def test_successful_enqueues_return_the_server_ids(monkeypatch):
    ids = iter([41, 42, 43])
    monkeypatch.setattr(mod, "_post_lcu_cmd",
                        lambda c: json.dumps({"ok": True, "id": next(ids)}).encode())
    monkeypatch.setattr(mod, "_resolve_variant", _resolved)
    h = _H()
    mod._serve_loadout_apply_post(h, {"champion": "Jinx", "variant": "v1"})
    body = json.loads(h.sent[1])
    assert body["ok"] is True
    assert body["queued"] == ["apply_runes", "apply_item_set", "set_summoners"]
    assert body["queued_ids"] == [
        {"cmd": "apply_runes", "id": 41},
        {"cmd": "apply_item_set", "id": 42},
        {"cmd": "set_summoners", "id": 43},
    ]


def test_unreadable_reply_keeps_the_enqueue_with_a_null_id(monkeypatch):
    monkeypatch.setattr(mod, "_post_lcu_cmd", lambda c: b"not json")
    monkeypatch.setattr(mod, "_resolve_variant", _resolved)
    h = _H()
    mod._serve_loadout_apply_post(h, {"champion": "Jinx", "variant": "v1",
                                      "push_items": False,
                                      "push_summoners": False})
    body = json.loads(h.sent[1])
    assert body["queued_ids"] == [{"cmd": "apply_runes", "id": None}]


def test_queue_id_parser():
    assert mod._queue_id(b'{"id": 7}') == 7
    assert mod._queue_id(b'{"id": "abc"}') == "abc"
    assert mod._queue_id(b'{"id": true}') is None
    assert mod._queue_id(b"[1]") is None
    assert mod._queue_id(b"") is None
