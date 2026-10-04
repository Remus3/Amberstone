"""RM-296a: /api/lcu-cmd validates each verb's PAYLOAD, not just the verb.

The edge forwarded every sibling key unexamined to the vision server's queue,
the last gate before the live League client. The schema is derived from the
`execute_command` branch in tools/lcu_agent.py that consumes each key.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import routes_loadout as mod  # noqa: E402


class _H:
    def __init__(self):
        self.sent = None

    def _send(self, status, body, ctype):
        self.sent = (status, body, ctype)


@pytest.fixture
def captured(monkeypatch):
    seen = []

    class _Resp:
        def __init__(self, data):
            self._d = data

        def read(self):
            return b'{"ok": true, "id": 1}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen.append(json.loads(req.data))
        return _Resp(req.data)

    monkeypatch.setattr(mod, "_urlopen", fake_urlopen)
    return seen


def _post(payload):
    h = _H()
    mod._serve_lcu_cmd_post(h, payload)
    return h.sent[0], json.loads(h.sent[1])


def test_schema_covers_exactly_the_allowlist():
    assert set(mod._LCU_CMD_SCHEMA) == set(mod._LCU_ALLOWED_CMDS)


def test_schema_matches_every_key_the_agent_reads():
    """Re-derive the agent's per-verb reads and compare - a schema that misses
    a key the agent consumes would STRIP it and break the action silently."""
    src = (ROOT / "tools" / "lcu_agent.py").read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(src) if l.startswith("def execute_command"))
    end = next(i for i in range(start + 1, len(src)) if src[i].startswith("def "))
    reads: dict[str, set] = {}
    cur: list[str] = []
    for line in src[start:end]:
        m = re.match(r"^\s{4}if name (==|in) (.+):", line)
        if m:
            cur = re.findall(r'"([a-z_.]+)"', m.group(2))
        keys = re.findall(r'cmd(?:\.get\(|\[)"([A-Za-z_]+)"', line)
        loop = re.search(r"for k in \(([^)]*)\)", line)
        if loop:
            keys += re.findall(r'"([A-Za-z_]+)"', loop.group(1))
        for v in cur:
            reads.setdefault(v, set()).update(k for k in keys if k != "cmd")
    for verb, keys in reads.items():
        assert keys == set(mod._LCU_CMD_SCHEMA[verb]), (verb, keys)


@pytest.mark.parametrize("payload,field", [
    ({"cmd": "lock_pick", "championId": {"x": 1}}, "championId"),
    ({"cmd": "lock_pick", "championId": True}, "championId"),
    ({"cmd": "set_summoners", "d": "four", "f": 14}, "d"),
    ({"cmd": "set_summoner_spell", "slot": 1.5, "spellId": 4}, "slot"),
    ({"cmd": "apply_runes", "page_name": 7, "primary_id": 8100,
      "sub_id": 8000, "perk_ids": list(range(9))}, "page_name"),
    ({"cmd": "apply_runes", "page_name": "RC: x", "primary_id": 8100,
      "sub_id": 8000, "perk_ids": "1,2,3"}, "perk_ids"),
    ({"cmd": "apply_item_sets_batch", "sets": {"a": 1}}, "sets"),
    ({"cmd": "set_config", "auto_accept": "yes"}, "auto_accept"),
    ({"cmd": "trade_request", "cell_id": [3]}, "cell_id"),
    ({"cmd": "change_queue_type", "queue_id": None}, "queue_id"),
    ({"cmd": "lobby.invite_player", "riot_id": 5}, "riot_id"),
    ({"cmd": "lobby.kick_member", "summoner_id": "abc"}, "summoner_id"),
    ({"cmd": "lobby.set_party_type", "party_type": True}, "party_type"),
    ({"cmd": "delete_stale_rc_item_sets", "active_champion": 3}, "active_champion"),
])
def test_wrong_typed_field_is_refused_and_named(captured, payload, field):
    status, body = _post(payload)
    assert status == 400
    assert body == {"error": "bad_lcu_cmd_field", "cmd": payload["cmd"], "field": field}
    assert captured == []  # never reached the queue


@pytest.mark.parametrize("payload", [
    {"cmd": "lock_pick", "championId": 103},
    {"cmd": "lock_pick", "championId": "103"},          # DOM dataset string
    {"cmd": "request_position_swap", "cell_id": "3"},
    {"cmd": "set_summoner_spell", "slot": 1, "spellId": 4},
    {"cmd": "lobby.set_position_prefs", "primary": None, "secondary": "MIDDLE"},
    {"cmd": "lobby.invite_player", "riot_id": "", "summoner_id": 0},
    {"cmd": "set_config", "auto_accept": False},
    {"cmd": "apply_item_sets_batch", "sets": [{"uid": "RC-x"}]},
    {"cmd": "start_matchmaking"},
])
def test_legitimate_traffic_still_passes(captured, payload):
    status, _ = _post(payload)
    assert status == 200
    assert captured[-1] == payload


def test_undeclared_sibling_keys_are_not_forwarded(captured):
    status, _ = _post({"cmd": "accept_ready", "__proto__": 1, "extra": "x"})
    assert status == 200
    assert captured[-1] == {"cmd": "accept_ready"}
