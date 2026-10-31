"""Lane 8 (true-audit) s144 cycle 82 - POST /api/coach-choice hardening.

Audit of dashboard/routes_coach_choice.py and the one store method it calls,
core.decision_detector.DecisionStore.record_coach_choice. Each class below is
one finding, red before the fix:

  F1  a failed log append answered 200 {"ok": true} - the store swallowed the
      OSError and returned the entry anyway, so the route's own 500 branch was
      dead and a click the operator saw "PICKED" was never logged.
  F2  the append ran outside _decisions_critical_section, while the sibling
      record_choice() appends to the same JSONL under it (Windows O_APPEND is
      seek-then-write, so two unserialized appenders can interleave).
  F3  json.dumps allowed NaN / Infinity, writing a non-strict-JSON line.
  F4  str(v) coerced any JSON value: a dict choice_key became "{", True
      became "T", 1 became "1" - each logged as a real A/B/C choice.
  F5  a key letter outside the producer's A/B/C set was logged.
  F6  a non-string label was logged as its Python repr, control characters
      reached the log verbatim, and the "..." cap overran the limit by 3.
  F7  same for source_tag.
  F8  game_context was stored WHOLE: any keys, any depth, up to the 1 MiB
      body cap per click, into an append-only log nothing rotates, whose
      /api/decisions/log tail reader spends a fixed 4 MiB byte budget.
  F9  an unexpected store failure was logged without a traceback.
"""
from __future__ import annotations

import contextlib
import json
import logging

import pytest

from core import decision_detector as dd
from dashboard import routes_coach_choice as rcc


class _H:
    def __init__(self) -> None:
        self.status = 0
        self.body = b""

    def _send(self, status, body, ctype, cache_control=None):
        self.status = status
        self.body = body

    def json(self) -> dict:
        return json.loads(self.body.decode())


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "_LOCK_PATH", tmp_path / "decisions.lock")
    s = dd.DecisionStore(pending_path=tmp_path / "pending.json",
                         log_path=tmp_path / "decisions_log.jsonl")
    monkeypatch.setattr(rcc, "_store", lambda: s)
    return s


def _lines(s) -> list[dict]:
    if not s._log_path.exists():
        return []
    raw = s._log_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(x, parse_constant=_reject_constant) for x in raw if x]


def _reject_constant(name):
    raise AssertionError(f"non-strict JSON constant {name} in log")


def _post(body) -> _H:
    h = _H()
    rcc._serve_coach_choice(h, body)
    return h


_OK = {"choice_key": "A", "choice_label": "Contest"}


# -- F1 ------------------------------------------------------------------------

class TestF1FailedAppendIsNotOk:
    def test_store_returns_none_when_append_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dd, "_LOCK_PATH", tmp_path / "decisions.lock")
        blocked = tmp_path / "log_is_a_dir"
        blocked.mkdir()
        s = dd.DecisionStore(pending_path=tmp_path / "p.json", log_path=blocked)
        got = s.record_coach_choice(choice_key="A", choice_label="x",
                                    confidence="mid", source_tag="")
        assert got is None

    def test_route_answers_503_not_200_when_nothing_was_logged(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(dd, "_LOCK_PATH", tmp_path / "decisions.lock")
        blocked = tmp_path / "log_is_a_dir"
        blocked.mkdir()
        s = dd.DecisionStore(pending_path=tmp_path / "p.json", log_path=blocked)
        monkeypatch.setattr(rcc, "_store", lambda: s)
        h = _post(dict(_OK))
        assert h.status == 503
        body = h.json()
        assert body["ok"] is False
        assert "log_is_a_dir" not in h.body.decode()

    def test_success_logs_exactly_one_strict_line_and_echoes_its_ts(self, store):
        h = _post(dict(_OK))
        assert h.status == 200
        rows = _lines(store)
        assert len(rows) == 1
        assert rows[0]["type"] == "coach_choice"
        assert h.json() == {"ok": True, "logged_ts": rows[0]["ts_unix"]}


# -- F2 ------------------------------------------------------------------------

class TestF2AppendIsSerialized:
    def test_append_runs_inside_the_decisions_critical_section(
            self, store, monkeypatch):
        state = {"inside": False, "wrote_inside": None}

        @contextlib.contextmanager
        def recording():
            state["inside"] = True
            try:
                yield
            finally:
                state["inside"] = False

        real_open = type(store._log_path).open

        def spy_open(self, *a, **kw):
            if self == store._log_path:
                state["wrote_inside"] = state["inside"]
            return real_open(self, *a, **kw)

        monkeypatch.setattr(dd, "_decisions_critical_section", recording)
        monkeypatch.setattr(type(store._log_path), "open", spy_open)
        assert store.record_coach_choice(choice_key="A", choice_label="x",
                                         confidence="mid",
                                         source_tag="") is not None
        assert state["wrote_inside"] is True


# -- F3 ------------------------------------------------------------------------

class TestF3StrictJson:
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_store_refuses_a_non_finite_float_and_writes_nothing(self, store, bad):
        got = store.record_coach_choice(choice_key="A", choice_label="x",
                                        confidence="mid", source_tag="",
                                        game_context={"cs": bad})
        assert got is None
        assert _lines(store) == []

    def test_route_drops_non_finite_context_and_still_logs(self, store):
        body = json.loads('{"choice_key":"A","choice_label":"x",'
                          '"game_context":{"cs":NaN,"level":Infinity,'
                          '"game_time_s":-Infinity}}')
        h = _post(body)
        assert h.status == 200
        assert _lines(store)[0]["game_context"] == {}


# -- F4 / F5 -------------------------------------------------------------------

class TestF4F5ChoiceKey:
    @pytest.mark.parametrize("bad", [{"a": 1}, ["A"], True, 1, 0.5])
    def test_non_string_key_is_400_and_not_logged(self, store, bad):
        h = _post({"choice_key": bad, "choice_label": "x"})
        assert h.status == 400
        assert _lines(store) == []

    @pytest.mark.parametrize("bad", ["Z", "1", "{", "-A", "D"])
    def test_key_outside_abc_is_400(self, store, bad):
        h = _post({"choice_key": bad, "choice_label": "x"})
        assert h.status == 400
        assert _lines(store) == []

    @pytest.mark.parametrize("raw,want", [("b", "B"), (" c ", "C"),
                                          ("AAAA", "A")])
    def test_valid_key_normalizes(self, store, raw, want):
        h = _post({"choice_key": raw, "choice_label": "x"})
        assert h.status == 200
        assert _lines(store)[0]["choice_key"] == want


# -- F6 ------------------------------------------------------------------------

class TestF6Label:
    @pytest.mark.parametrize("bad", [{"t": "Contest"}, ["Contest"], 7, True])
    def test_non_string_label_is_400(self, store, bad):
        h = _post({"choice_key": "A", "choice_label": bad})
        assert h.status == 400
        assert _lines(store) == []

    def test_control_characters_are_scrubbed(self, store):
        h = _post({"choice_key": "A", "choice_label": "Con\x00test\n\t now\x1b"})
        assert h.status == 200
        assert _lines(store)[0]["choice_label"] == "Contest now"

    def test_label_of_only_controls_is_400(self, store):
        h = _post({"choice_key": "A", "choice_label": "\x00\x07\n"})
        assert h.status == 400

    def test_overlong_label_cap_includes_the_ellipsis(self, store):
        h = _post({"choice_key": "A", "choice_label": "x" * 500})
        assert h.status == 200
        label = _lines(store)[0]["choice_label"]
        assert len(label) == rcc._MAX_LABEL
        assert label.endswith("...")


# -- F7 ------------------------------------------------------------------------

class TestF7SourceTag:
    @pytest.mark.parametrize("bad", [{"s": 1}, ["synth"], 3])
    def test_non_string_source_is_400(self, store, bad):
        h = _post({"choice_key": "A", "choice_label": "x", "source_tag": bad})
        assert h.status == 400
        assert _lines(store) == []

    def test_source_cap_includes_the_ellipsis(self, store):
        h = _post({"choice_key": "A", "choice_label": "x",
                   "source_tag": "s" * 200})
        assert h.status == 200
        assert len(_lines(store)[0]["source_tag"]) == rcc._MAX_SOURCE

    def test_missing_source_is_empty(self, store):
        h = _post(dict(_OK))
        assert h.status == 200
        assert _lines(store)[0]["source_tag"] == ""


# -- F8 ------------------------------------------------------------------------

class TestF8GameContextBounded:
    def test_the_dashboard_snapshot_shape_round_trips(self, store):
        ctx = {"mode_key": "sr", "champion": "Lux", "level": 11,
               "game_time_s": 812.5, "kda": "3/1/4", "cs": 97}
        h = _post({"choice_key": "A", "choice_label": "x", "game_context": ctx})
        assert h.status == 200
        assert _lines(store)[0]["game_context"] == ctx

    def test_unknown_keys_and_containers_are_dropped(self, store):
        ctx = {"champion": "Lux", "extra": "y", "nested": {"a": [1, 2]},
               "level": [11], "cs": {"n": 1}, "kda": ["3/1/4"]}
        h = _post({"choice_key": "A", "choice_label": "x", "game_context": ctx})
        assert h.status == 200
        assert _lines(store)[0]["game_context"] == {"champion": "Lux"}

    def test_bool_and_out_of_range_numbers_are_dropped(self, store):
        ctx = {"level": True, "cs": -1, "game_time_s": 1e12}
        h = _post({"choice_key": "A", "choice_label": "x", "game_context": ctx})
        assert h.status == 200
        assert _lines(store)[0]["game_context"] == {}

    def test_strings_are_scrubbed_and_capped(self, store):
        ctx = {"champion": "Lu\x00x" + "z" * 500, "mode_key": 5}
        h = _post({"choice_key": "A", "choice_label": "x", "game_context": ctx})
        assert h.status == 200
        got = _lines(store)[0]["game_context"]
        assert set(got) == {"champion"}
        assert got["champion"].startswith("Lux")
        assert len(got["champion"]) == rcc._MAX_CTX_STR

    def test_a_megabyte_context_stores_a_bounded_line(self, store):
        ctx = {f"k{i}": "v" * 1000 for i in range(1000)}
        ctx["champion"] = "c" * 100000
        h = _post({"choice_key": "A", "choice_label": "x", "game_context": ctx})
        assert h.status == 200
        size = store._log_path.stat().st_size
        assert size < 1024, size


# -- F9 ------------------------------------------------------------------------

class TestF9UnexpectedFailure:
    def test_unexpected_error_is_500_with_a_traceback_and_no_raw_text(
            self, monkeypatch, caplog):
        class Boom:
            def record_coach_choice(self, **kw):
                raise RuntimeError("secret-ish detail")

        monkeypatch.setattr(rcc, "_store", lambda: Boom())
        with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
            h = _post(dict(_OK))
        assert h.status == 500
        assert b"secret-ish" not in h.body
        recs = [r for r in caplog.records if r.name == "rc.web_dashboard"]
        assert recs and recs[-1].exc_info is not None
