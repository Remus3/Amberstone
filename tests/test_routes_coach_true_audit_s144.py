"""Lane 8 (true-audit) s144 cycle 4: dashboard/routes_coach.py.

Each test names the weakness it pins. All handlers are driven with a fake
BaseHTTPRequestHandler; no socket, no Anthropic call, no live file.

1. /api/replay/matches ?queue= was gated by ``str.isdigit()``, which accepts
   Unicode digits ``int()`` rejects (``queue=%C2%B2``, a superscript two) and
   digit runs past the int-string limit - both raised ValueError and the list
   answered 500. Any other non-digit value (``abc``, ``-1``) DROPPED the
   filter silently and served every queue's matches - a filtered request
   answered unfiltered. Now: empty / absent = no filter, 1-9 ASCII digits =
   that queue, anything else = 400 ``bad queue``.
2. /api/coach/state hard-coded five modes while the kill-switch registry
   (core.cost_tracker.GATES) has seven, so the vision and champ_select gates
   were never reported; it re-read coach_settings.json itself with its own
   ``x.lower()`` rule, so a non-string entry 500ed the route while the
   tracker that actually gates spend read it fine. Now it reports
   ``gates_state()`` - the same truth /api/spend/gates and every coach use.
3. Every 200 body is strict JSON: a NaN / Infinity in a payload answers the
   generic 500 envelope instead of a body the browser's JSON.parse rejects.
4. The match_id check used ``re.match(...$)``, and ``$`` matches before a
   trailing newline; it is now a full match.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from dashboard import routes_coach as rc


class FakeHandler:
    def __init__(self, path: str) -> None:
        self.path = path
        self.sent: list[tuple[int, bytes, str]] = []

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.sent.append((code, body, ctype))

    @property
    def last(self) -> tuple[int, bytes, str]:
        assert len(self.sent) == 1, self.sent
        return self.sent[0]


def _strict(body: bytes):
    def _reject(tok):
        raise AssertionError(f"non-strict JSON token {tok!r} on the wire")
    return json.loads(body.decode("utf-8"), parse_constant=_reject)


# -- 1. ?queue= ---------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "%C2%B2",           # superscript two: isdigit() True, int() ValueError
    pytest.param("1" * 5000, id="digits5000"),  # past the int-string limit
    "abc",
    "-1",
    "4.2",
    "%D9%A3",           # Arabic-Indic three: not an ASCII digit
    pytest.param("1" * 10, id="digits10"),      # longer than any queue id
])
def test_replay_matches_bad_queue_is_400_and_never_unfiltered(raw):
    import core.replay_history as rh
    h = FakeHandler("/api/replay/matches?queue=" + raw)
    with mock.patch.object(rh, "list_matches", return_value=[]) as lm:
        rc._serve_replay_matches(h)
    code, body, _ = h.last
    assert code == 400, (code, body)
    assert _strict(body) == {"error": "bad queue"}
    lm.assert_not_called()


@pytest.mark.parametrize("qs, expected", [
    ("", None),
    ("?queue=", None),
    ("?queue=420", 420),
    ("?queue=0", 0),          # custom games are a real queue
    ("?queue=2400&limit=5", 2400),
    ("?queue=%20420%20", 420),  # surrounding blanks are not part of the id
])
def test_replay_matches_valid_queue_filters(qs, expected):
    import core.replay_history as rh
    h = FakeHandler("/api/replay/matches" + qs)
    with mock.patch.object(rh, "list_matches", return_value=[]) as lm:
        rc._serve_replay_matches(h)
    assert h.last[0] == 200
    assert lm.call_args.kwargs["queue_filter"] == expected


# -- 2. /api/coach/state ------------------------------------------------------

def _tracker(tmp_path, cfg):
    from core.cost_tracker import CostTracker
    return CostTracker(config_provider=lambda: cfg, spend_dir=tmp_path)


def _coach_state(tracker):
    import core.cost_tracker as ct
    h = FakeHandler("/api/coach/state")
    with mock.patch.object(ct, "get_tracker", return_value=tracker):
        rc._serve_coach_state(h)
    return h.last


def test_coach_state_reports_every_gate(tmp_path):
    from core.cost_tracker import GATES
    code, body, _ = _coach_state(_tracker(tmp_path, {}))
    assert code == 200
    out = _strict(body)
    assert set(out["enabled"]) == set(GATES)
    assert {"vision", "champ_select"} <= set(out["enabled"])
    assert all(out["enabled"].values())
    assert out["disabled"] == []


def test_coach_state_non_string_entry_is_not_500(tmp_path):
    cfg = {"disabled_coaches": [1, None, "ARAM"]}
    code, body, _ = _coach_state(_tracker(tmp_path, cfg))
    assert code == 200, body
    out = _strict(body)
    assert out["enabled"]["aram"] is False
    assert out["disabled"] == ["aram"]


def test_coach_state_agrees_with_the_tracker_that_gates_spend(tmp_path):
    cfg = {"disabled_coaches": ["Vision", "champ_select"]}
    tracker = _tracker(tmp_path, cfg)
    code, body, _ = _coach_state(tracker)
    assert code == 200
    out = _strict(body)
    for gate, enabled in out["enabled"].items():
        assert enabled is (not tracker.gate_disabled(gate)), gate
    assert out["enabled"]["vision"] is False
    assert out["enabled"]["champ_select"] is False
    assert sorted(out["disabled"]) == ["champ_select", "vision"]


# -- 3. strict JSON on every 200 path -------------------------------------------

_NAN = {"x": float("nan"), "y": float("inf")}


def _tracker_stub():
    t = mock.Mock()
    t.daily_spend.return_value = _NAN
    t.banner_state.return_value = "ok"
    t.allow_call.return_value = True
    t.gates_state.return_value = {"sr": {"label": "SR", "explain": "",
                                         "disabled": False}}
    t.recent_match_avg.return_value = _NAN
    return t


_CASES = [
    ("cost", "/api/cost", "core.cost_tracker.get_tracker", None),
    ("spend_gates", "/api/spend/gates", "core.cost_tracker.get_tracker", None),
    ("coach_trace", "/api/coach/trace", "core.coach_trace.read_recent",
     [_NAN]),
    ("replay_matches", "/api/replay/matches",
     "core.replay_history.list_matches", [_NAN]),
    ("replay_match", "/api/replay/match/NA1_123456",
     "core.replay_history.match_detail", _NAN),
    ("branch_review", "/api/branch-review",
     "core.branch_review.load_branch_series", _NAN),
    ("branch_review_runs", "/api/branch-review/runs",
     "core.branch_review.list_recent_runs", [_NAN]),
]


@pytest.mark.parametrize("name, path, target, value", _CASES,
                         ids=[c[0] for c in _CASES])
def test_get_nan_payload_answers_strict_json(name, path, target, value):
    fn = {
        "cost": rc._serve_cost,
        "spend_gates": rc._serve_spend_gates,
        "coach_trace": rc._serve_coach_trace,
        "replay_matches": rc._serve_replay_matches,
        "replay_match": rc._serve_replay_match,
        "branch_review": rc._serve_branch_review,
        "branch_review_runs": rc._serve_branch_review_runs,
    }[name]
    rv = _tracker_stub() if value is None else value
    h = FakeHandler(path)
    with mock.patch(target, return_value=rv):
        fn(h)
    code, body, _ = h.last
    out = _strict(body)
    assert code == 500
    assert out == {"error": "internal error - see logs"}


def test_aram_comp_verdict_nan_answers_strict_json():
    h = FakeHandler("/api/aram-comp-verdict")
    with mock.patch("core.aram_comp_verdict.comp_verdict",
                    return_value={"ok": True, "confidence": float("nan")}):
        rc._serve_aram_comp_verdict_post(h, {})
    code, body, _ = h.last
    assert code == 500
    assert _strict(body) == {"error": "internal error - see logs"}


def test_champ_select_coach_nan_answers_strict_json():
    h = FakeHandler("/api/champ-select-coach")
    with mock.patch("coaches._base_coach.read_api_key", return_value=""), \
            mock.patch("coaches.champ_select_coach.coach_pick",
                       return_value={"ok": True, "elapsed_ms": float("inf")}), \
            mock.patch("core.champ_select_shadow.log_champ_select_advice"):
        rc._serve_champ_select_coach_post(h, {"my_champion": "Ahri"})
    code, body, _ = h.last
    assert code == 500
    assert _strict(body) == {"error": "internal error - see logs"}


def test_finite_payloads_still_answer_200():
    import core.replay_history as rh
    h = FakeHandler("/api/replay/match/NA1_123456")
    with mock.patch.object(rh, "match_detail", return_value={"x": 1.5}):
        rc._serve_replay_match(h)
    code, body, ctype = h.last
    assert (code, ctype) == (200, "application/json")
    assert _strict(body) == {"x": 1.5}


# -- 4. match_id full match ---------------------------------------------------

@pytest.mark.parametrize("mid", [
    "NA1_123456\n",
    "na1_123456",
    "NA1-123456",
    "NA1",
    "N" * 41,
])
def test_replay_match_bad_id_is_400(mid):
    import core.replay_history as rh
    h = FakeHandler("/api/replay/match/" + mid)
    with mock.patch.object(rh, "match_detail", return_value={}) as md:
        rc._serve_replay_match(h)
    assert h.last[0] == 400
    md.assert_not_called()


def test_replay_match_strips_the_query_and_404s_unknown():
    import core.replay_history as rh
    h = FakeHandler("/api/replay/match/EUW1_9876543?x=1")
    with mock.patch.object(rh, "match_detail", return_value=None) as md:
        rc._serve_replay_match(h)
    md.assert_called_once_with("EUW1_9876543")
    code, body, _ = h.last
    assert code == 404
    assert _strict(body) == {"error": "not found"}
