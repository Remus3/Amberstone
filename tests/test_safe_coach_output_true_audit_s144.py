"""True-audit (s144, S144-T-715) of core/safe_coach_output.py.

The decorator wraps the live tick of the ARAM, Arena and Brawl coaches
(`coaches/aram_coach.py`, `coaches/arena_coach.py`, `coaches/brawl_coach.py`).
None of those coaches defines `_write_status_field`, so the LIVE path is the
fallback that patches `immediate` in the coach's own artifact file.

Characterization first (the classifications that were already right), then one
regression test per finding:

- F1 a plain substring match misread code bugs as API faults: a KeyError
  naming `separate_limit` read "rate limited", a count of 14000 read "request
  invalid", a KeyError naming `connection_id` read "API unreachable".
- F1b it was type-blind: a builtin TimeoutError ("timed out") and an HTTP 529
  overloaded error both read "internal error".
- F2 an internal error was logged as one line with no traceback, so a real bug
  in a coach tick degraded silently.
- F3 an exception whose __str__ raises escaped the decorator.
- F5 a coach artifact holding valid JSON that is not an object (a list, null)
  raised TypeError inside the fallback, so no paused status was ever written.
- F7 the blank artifact was built even when the file was readable, so a
  raising `_blank_artifact_data` blocked a write that did not need it.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import safe_coach_output as sco
from core.safe_coach_output import classify_coach_error, coach_status_text, safe_coach_output


class _StatusErr(Exception):
    """Stand-in for an SDK error that carries an HTTP status code."""

    def __init__(self, msg: str, status_code: int) -> None:
        super().__init__(msg)
        self.status_code = status_code


class _Unprintable(Exception):
    def __str__(self) -> str:  # pragma: no cover - the point is it raises
        raise RuntimeError("str() itself fails")


class _FallbackCoach:
    """Mirrors the live coaches: no _write_status_field, an _out artifact."""

    def __init__(self, out, blank=None, blank_raises=False):
        self._out = out
        self._blank = blank if blank is not None else {"immediate": "", "next": ""}
        self._blank_raises = blank_raises

    def _blank_artifact_data(self):
        if self._blank_raises:
            raise RuntimeError("blank builder broken")
        return dict(self._blank)

    @safe_coach_output("ARAM")
    def _run_coach(self, exc):
        raise exc


class _WriterCoach:
    def __init__(self):
        self.statuses = []

    def _write_status_field(self, status):
        self.statuses.append(status)

    @safe_coach_output("Arena")
    def _run_coach(self, exc):
        raise exc

    @safe_coach_output("Arena")
    def _ok(self, value):
        return value


# -- characterization: classifications that were already right -----------------

@pytest.mark.parametrize(
    "exc, kind",
    [
        (Exception("Your credit balance is too low to access the Anthropic API"), "add API credits"),
        (Exception("Error code: 429 - {'error': {'type': 'rate_limit_error'}}"), "rate limited"),
        (Exception("Error code: 401 - {'error': {'type': 'authentication_error'}}"), "auth error"),
        (Exception("Error code: 400 - {'error': {'type': 'invalid_request_error'}}"), "request invalid"),
        (Exception("Request timeout"), "API timeout"),
        (Exception("Connection error."), "API unreachable"),
        (Exception("host unreachable"), "API unreachable"),
        (ValueError("boom"), "internal error"),
    ],
)
def test_characterization_existing_classes_unchanged(exc, kind):
    assert classify_coach_error(exc) == kind


def test_credit_balance_wins_over_its_400_status():
    exc = _StatusErr("Error code: 400 - Your credit balance is too low", 400)
    assert classify_coach_error(exc) == "add API credits"


def test_status_text_shape_is_unchanged():
    assert coach_status_text("ARAM", ValueError("x")) == "(ARAM coach paused - internal error)"


def test_real_anthropic_errors_classify_by_type():
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx")
    req = httpx.Request("POST", "https://api.invalid")
    rl = anthropic.RateLimitError("slow down", response=httpx.Response(429, request=req), body=None)
    assert classify_coach_error(rl) == "rate limited"
    assert classify_coach_error(anthropic.APITimeoutError(request=req)) == "API timeout"
    assert classify_coach_error(anthropic.APIConnectionError(request=req)) == "API unreachable"


# -- F1: substring false positives ---------------------------------------------

@pytest.mark.parametrize(
    "exc",
    [
        KeyError("separate_limit"),
        ValueError("generate failed: item limit reached"),
        ValueError("expected 14000 rows"),
        ValueError("1401 champions"),
        KeyError("connection_id"),
    ],
)
def test_f1_code_bug_is_not_reported_as_an_api_fault(exc):
    assert classify_coach_error(exc) == "internal error"


# -- F1b: type and status code ---------------------------------------------------

def test_f1b_builtin_timeout_is_a_timeout():
    assert classify_coach_error(TimeoutError("timed out")) == "API timeout"


def test_f1b_builtin_connection_error_is_unreachable():
    assert classify_coach_error(ConnectionResetError("peer reset")) == "API unreachable"


@pytest.mark.parametrize(
    "exc, kind",
    [
        (_StatusErr("slow", 429), "rate limited"),
        (_StatusErr("nope", 401), "auth error"),
        (_StatusErr("nope", 403), "auth error"),
        (_StatusErr("bad", 400), "request invalid"),
        (_StatusErr("busy", 529), "API unavailable"),
        (_StatusErr("down", 503), "API unavailable"),
        (Exception("Error code: 529 - {'error': {'type': 'overloaded_error'}}"), "API unavailable"),
    ],
)
def test_f1b_status_code_and_overloaded(exc, kind):
    assert classify_coach_error(exc) == kind


# -- F2: internal errors carry a traceback, the first line keeps its format ------

def test_f2_internal_error_is_logged_with_traceback(caplog):
    coach = _WriterCoach()
    with caplog.at_level(logging.ERROR, logger="coach"):
        assert coach._run_coach(KeyError("separate_limit")) is None
    recs = [r for r in caplog.records if r.name == "coach"]
    assert recs, "no coach error record"
    assert recs[0].getMessage().startswith("Arena coach error: ")
    assert isinstance(recs[0].exc_info, tuple) and recs[0].exc_info[0] is KeyError


def test_f2_api_error_logs_one_line_without_traceback(caplog):
    coach = _WriterCoach()
    with caplog.at_level(logging.ERROR, logger="coach"):
        coach._run_coach(_StatusErr("rate_limit_error", 429))
    recs = [r for r in caplog.records if r.name == "coach"]
    assert recs[0].getMessage() == "Arena coach error: rate_limit_error"
    assert not recs[0].exc_info


# -- F3: an unprintable exception never escapes ----------------------------------

def test_f3_unprintable_exception_is_absorbed():
    coach = _WriterCoach()
    assert coach._run_coach(_Unprintable()) is None
    assert coach.statuses == ["(Arena coach paused - internal error)"]


class _BadStatusCode(Exception):
    @property
    def status_code(self):
        raise RuntimeError("property fails")


def test_f3_raising_status_code_property_is_absorbed():
    assert classify_coach_error(_BadStatusCode("boom")) == "internal error"
    coach = _WriterCoach()
    assert coach._run_coach(_BadStatusCode("boom")) is None
    assert coach.statuses == ["(Arena coach paused - internal error)"]


def test_f3_coach_with_raising_getattr_is_absorbed():
    class _Hostile:
        def __getattr__(self, name):
            raise RuntimeError(f"no {name}")

        @safe_coach_output("Brawl")
        def _run_coach(self):
            raise ValueError("x")

    assert _Hostile()._run_coach() is None


def test_gateway_timeout_504_stays_a_timeout():
    assert classify_coach_error(_StatusErr("deadline", 504)) == "API timeout"
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx")
    req = httpx.Request("POST", "https://api.invalid")
    exc = anthropic.DeadlineExceededError(
        "Error code: 504", response=httpx.Response(504, request=req), body=None)
    assert classify_coach_error(exc) == "API timeout"


def test_oserror_connection_closed_stays_unreachable():
    assert classify_coach_error(OSError("connection closed")) == "API unreachable"


class _HashBomb(int):
    def __hash__(self):
        raise RuntimeError("hash fails")


def test_f3_int_subclass_status_code_is_absorbed():
    exc = _StatusErr("boom", 429)
    exc.status_code = _HashBomb(429)
    assert classify_coach_error(exc) == "internal error"


def test_f3_status_writer_with_raising_bool_is_absorbed():
    class _BoolBomb:
        def __bool__(self):
            raise RuntimeError("bool fails")

        def __call__(self, status):
            raise RuntimeError("call fails")

    coach = _WriterCoach()
    coach._write_status_field = _BoolBomb()
    assert coach._run_coach(ValueError("x")) is None


def test_f3_raising_logger_filter_is_absorbed():
    def _bomb(_record):
        raise RuntimeError("filter fails")

    sco._log.addFilter(_bomb)
    try:
        coach = _WriterCoach()
        assert coach._run_coach(ValueError("x")) is None
    finally:
        sco._log.removeFilter(_bomb)
    # a broken log call must not cost the operator the paused status
    assert coach.statuses == ["(Arena coach paused - internal error)"]


@pytest.mark.parametrize(
    "msg",
    ["connection lost", "no connection to host", "connection pool is full",
     "Failed to establish a new connection"],
)
def test_plain_message_transport_faults_stay_unreachable(msg):
    assert classify_coach_error(RuntimeError(msg)) == "API unreachable"


def test_failed_to_establish_needs_the_connection_phrase():
    assert classify_coach_error(ValueError("failed to establish champion mapping")) == "internal error"


def test_coach_error_record_points_at_the_handler_not_the_guard(caplog):
    with caplog.at_level(logging.ERROR, logger="coach"):
        _WriterCoach()._run_coach(ValueError("x"))
    rec = [r for r in caplog.records if r.name == "coach"][0]
    assert rec.funcName == "_degrade"


class _BadLowerStr(str):
    def lower(self):
        raise RuntimeError("lower fails")


class _OddStr(Exception):
    def __str__(self):
        return _BadLowerStr("odd")


def test_f3_classify_never_raises_and_status_still_lands():
    assert classify_coach_error(_OddStr()) == "internal error"
    coach = _WriterCoach()
    assert coach._run_coach(_OddStr()) is None
    assert coach.statuses == ["(Arena coach paused - internal error)"]


def test_status_writer_path_and_success_passthrough():
    coach = _WriterCoach()
    assert coach._ok(7) == 7
    coach._run_coach(_StatusErr("x", 429))
    assert coach.statuses == ["(Arena coach paused - rate limited)"]


def test_status_writer_failure_is_logged_not_raised(caplog):
    coach = _WriterCoach()

    def _broken(_s):
        raise OSError("disk gone")

    coach._write_status_field = _broken
    with caplog.at_level(logging.ERROR, logger="coach"):
        assert coach._run_coach(ValueError("x")) is None
    assert any("Failed to write safe fallback" in r.getMessage() for r in caplog.records)


# -- F5 / F7: the live fallback path ---------------------------------------------

def test_fallback_patches_immediate_and_keeps_other_fields(tmp_path):
    out = tmp_path / "aram_coaching_data.json"
    out.write_text(json.dumps({"immediate": "old", "next": "keep me"}), encoding="utf-8")
    _FallbackCoach(out)._run_coach(_StatusErr("x", 429))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {"immediate": "Immediate: (ARAM coach paused - rate limited)", "next": "keep me"}


def test_fallback_missing_file_uses_blank(tmp_path):
    out = tmp_path / "aram_coaching_data.json"
    _FallbackCoach(out)._run_coach(ValueError("x"))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {"immediate": "Immediate: (ARAM coach paused - internal error)", "next": ""}


def test_fallback_corrupt_json_uses_blank(tmp_path):
    out = tmp_path / "aram_coaching_data.json"
    out.write_text("{not json", encoding="utf-8")
    _FallbackCoach(out)._run_coach(ValueError("x"))
    assert json.loads(out.read_text(encoding="utf-8"))["next"] == ""


@pytest.mark.parametrize("doc", ["[]", "null", "3", '"text"'])
def test_f5_non_object_json_still_gets_the_paused_status(tmp_path, doc):
    out = tmp_path / "aram_coaching_data.json"
    out.write_text(doc, encoding="utf-8")
    _FallbackCoach(out)._run_coach(ValueError("x"))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {"immediate": "Immediate: (ARAM coach paused - internal error)", "next": ""}


def test_f7_blank_builder_not_needed_when_file_is_readable(tmp_path):
    out = tmp_path / "aram_coaching_data.json"
    out.write_text(json.dumps({"next": "keep me"}), encoding="utf-8")
    _FallbackCoach(out, blank_raises=True)._run_coach(ValueError("x"))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {"next": "keep me", "immediate": "Immediate: (ARAM coach paused - internal error)"}


def test_fallback_write_is_lf_bytes(tmp_path):
    out = tmp_path / "aram_coaching_data.json"
    _FallbackCoach(out)._run_coach(ValueError("x"))
    assert b"\r\n" not in out.read_bytes()


def test_no_out_attribute_is_a_quiet_no_op():
    class _Bare:
        @safe_coach_output("Brawl")
        def _run_coach(self):
            raise ValueError("x")

    assert _Bare()._run_coach() is None


def test_module_is_ascii_lf():
    raw = open(sco.__file__, "rb").read()
    raw.decode("ascii")
    assert b"\r\n" not in raw
