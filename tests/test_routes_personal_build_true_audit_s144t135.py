"""True-audit (s144 cycle 135) regression tests for dashboard.routes_personal_build.

Each test names the weakness it pins (S144-T ids in the cycle report):

- the cache-hit path wrote the response while holding the module-wide cache
  lock, so one stalled client write blocked every other /api/personal-build
  request;
- the TTL ran on the wall clock, so a backward clock step kept an entry fresh
  until the clock caught up, and elapsed_ms could go negative;
- a transient read_error / no_db empty shell was cached for the full TTL, so
  one SQLite lock collision blanked the panel for five minutes;
- a cache hit echoed the FIRST requester's champion casing instead of this
  request's;
- a champion made only of punctuation / spaces passed validation and scanned
  the DB;
- a failed response write (client gone) was logged as an internal error and
  answered with a SECOND response on the same connection;
- a non-finite float reached the client as a bare NaN token (invalid JSON),
  and a non-dict compute result became a 500 instead of a degraded 503.

compute_personal_build is monkeypatched: the route is under test, not the DB.
"""
from __future__ import annotations

import json
import threading

import pytest

from dashboard import routes_personal_build as rpb


def _strict_loads(raw: bytes):
    def _reject(tok):
        raise ValueError(f"non-strict JSON constant {tok}")

    return json.loads(raw.decode("utf-8"), parse_constant=_reject)


class _H:
    def __init__(self, qs: str, send=None):
        self.path = "/api/personal-build" + (f"?{qs}" if qs else "")
        self.calls: list[tuple[int, bytes, str]] = []
        self._send_impl = send

    def _send(self, status, body, ctype):
        self.calls.append((status, body, ctype))
        if self._send_impl is not None:
            self._send_impl(status, body, ctype)

    @property
    def status(self):
        return self.calls[-1][0]

    def json(self):
        return _strict_loads(self.calls[-1][1])


def _ok_payload(champion, mode, confidence="ok"):
    return {
        "champion": str(champion).strip(),
        "champion_id": None,
        "mode": mode,
        "games": 20,
        "win_rate": 0.6,
        "baseline_win_rate": 0.6,
        "confidence": confidence,
        "items": [],
        "most_common_build": [],
        "source": "rewind_history.db",
    }


@pytest.fixture(autouse=True)
def _clean_cache():
    rpb._reset_caches()
    yield
    rpb._reset_caches()


@pytest.fixture
def compute_calls(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake(champion, mode="sr", **_kw):
        calls.append((champion, mode))
        return _ok_payload(champion, mode)

    monkeypatch.setattr(rpb.personal_build_wr, "compute_personal_build", fake)
    return calls


# --- lock held across network I/O ------------------------------------------

def test_cache_hit_send_runs_outside_the_cache_lock(compute_calls):
    rpb._serve_personal_build(_H("champion=Vayne"))
    seen: list[bool] = []

    def probe(_status, _body, _ctype):
        seen.append(rpb._CACHE_LOCK.locked())

    h = _H("champion=Vayne", send=probe)
    rpb._serve_personal_build(h)
    assert h.json()["cached"] is True
    assert seen == [False], "response written while holding _CACHE_LOCK"


def test_a_stalled_cache_hit_write_does_not_block_another_request(compute_calls):
    rpb._serve_personal_build(_H("champion=Vayne"))
    release = threading.Event()
    entered = threading.Event()

    def stall(_s, _b, _c):
        entered.set()
        release.wait(5)

    t = threading.Thread(
        target=rpb._serve_personal_build, args=(_H("champion=Vayne", send=stall),),
        daemon=True)
    t.start()
    try:
        assert entered.wait(5)
        other = _H("champion=Vayne")
        done = threading.Event()

        def run_other():
            rpb._serve_personal_build(other)
            done.set()

        threading.Thread(target=run_other, daemon=True).start()
        assert done.wait(2), "second request blocked behind a stalled write"
        assert other.json()["cached"] is True
    finally:
        release.set()
        t.join(5)


# --- wall-clock TTL ----------------------------------------------------------

class _FakeTime:
    """Stands in for the module's ``time``: every clock reads ``now``."""

    def __init__(self, now: float):
        self.now = now

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def perf_counter(self):
        return self.now


def test_a_backward_clock_step_does_not_keep_an_entry_fresh(compute_calls, monkeypatch):
    fake = _FakeTime(10_000.0)
    monkeypatch.setattr(rpb, "time", fake)
    rpb._serve_personal_build(_H("champion=Vayne"))
    fake.now = 1_000.0  # clock stepped back 9000 s
    h = _H("champion=Vayne")
    rpb._serve_personal_build(h)
    assert h.json()["cached"] is False
    assert len(compute_calls) == 2


def test_elapsed_ms_is_never_negative(monkeypatch):
    fake = _FakeTime(10_000.0)
    monkeypatch.setattr(rpb, "time", fake)

    def compute(champion, mode="sr", **_kw):
        fake.now = 5_000.0  # clock steps back mid-request
        return _ok_payload(champion, mode)

    monkeypatch.setattr(rpb.personal_build_wr, "compute_personal_build", compute)
    h = _H("champion=Vayne")
    rpb._serve_personal_build(h)
    assert h.status == 200
    assert h.json()["elapsed_ms"] >= 0


def test_entry_expires_after_the_ttl(compute_calls, monkeypatch):
    fake = _FakeTime(10_000.0)
    monkeypatch.setattr(rpb, "time", fake)
    rpb._serve_personal_build(_H("champion=Vayne"))
    fake.now += rpb._CACHE_TTL_S - 1
    h1 = _H("champion=Vayne")
    rpb._serve_personal_build(h1)
    assert h1.json()["cached"] is True
    fake.now += 2
    h2 = _H("champion=Vayne")
    rpb._serve_personal_build(h2)
    assert h2.json()["cached"] is False


# --- transient failures cached for the whole TTL -----------------------------

@pytest.mark.parametrize("transient", ["read_error", "no_db", "bad_mode"])
def test_a_transient_empty_shell_is_not_cached(monkeypatch, transient):
    answers = [transient, "ok"]

    def compute(champion, mode="sr", **_kw):
        return _ok_payload(champion, mode, confidence=answers.pop(0))

    monkeypatch.setattr(rpb.personal_build_wr, "compute_personal_build", compute)
    rpb._serve_personal_build(_H("champion=Vayne"))
    h = _H("champion=Vayne")
    rpb._serve_personal_build(h)
    assert h.json()["cached"] is False
    assert h.json()["confidence"] == "ok"


@pytest.mark.parametrize("verdict", ["ok", "thin", "insufficient"])
def test_a_data_verdict_is_cached(monkeypatch, verdict):
    calls = []

    def compute(champion, mode="sr", **_kw):
        calls.append(1)
        return _ok_payload(champion, mode, confidence=verdict)

    monkeypatch.setattr(rpb.personal_build_wr, "compute_personal_build", compute)
    rpb._serve_personal_build(_H("champion=Vayne"))
    h = _H("champion=Vayne")
    rpb._serve_personal_build(h)
    assert h.json()["cached"] is True
    assert len(calls) == 1


# --- cache hit echoes another request's champion ----------------------------

def test_cache_hit_echoes_this_requests_champion(compute_calls):
    rpb._serve_personal_build(_H("champion=KAI'SA"))
    h = _H("champion=kai'sa")
    rpb._serve_personal_build(h)
    body = h.json()
    assert body["cached"] is True
    assert body["champion"] == "kai'sa"
    assert len(compute_calls) == 1


# --- validation ----------------------------------------------------------------

@pytest.mark.parametrize("raw", ["...", "%26", "%27", "+.+", "%27%27%27", "."])
def test_a_champion_with_no_letter_or_digit_is_400(compute_calls, raw):
    h = _H(f"champion={raw}")
    rpb._serve_personal_build(h)
    assert h.status == 400
    assert compute_calls == []


@pytest.mark.parametrize("raw", ["Kai%27Sa", "Dr.+Mundo", "Nunu+%26+Willump", "222", "a"])
def test_real_champion_shapes_still_pass(compute_calls, raw):
    h = _H(f"champion={raw}")
    rpb._serve_personal_build(h)
    assert h.status == 200


def test_a_41_char_champion_is_400(compute_calls):
    h = _H("champion=" + "a" * 41)
    rpb._serve_personal_build(h)
    assert h.status == 400


def test_a_malformed_champion_error_says_what_is_wrong(compute_calls):
    h = _H("champion=%3Cscript%3E")
    rpb._serve_personal_build(h)
    assert h.status == 400
    err = h.json()["error"]
    assert "<script>" not in err
    assert "champion" in err


# --- a failed write is not an internal error --------------------------------

@pytest.mark.parametrize("exc", [BrokenPipeError, ConnectionResetError, ConnectionAbortedError])
def test_a_failed_write_is_not_followed_by_a_second_response(compute_calls, exc):
    def boom(_s, _b, _c):
        raise exc("client gone")

    h = _H("champion=Vayne", send=boom)
    rpb._serve_personal_build(h)
    assert len(h.calls) == 1, [c[0] for c in h.calls]


def test_a_failed_write_on_the_cache_hit_path_is_one_attempt(compute_calls):
    rpb._serve_personal_build(_H("champion=Vayne"))

    def boom(_s, _b, _c):
        raise BrokenPipeError("client gone")

    h = _H("champion=Vayne", send=boom)
    rpb._serve_personal_build(h)
    assert len(h.calls) == 1


# --- strict JSON / contract drift -------------------------------------------

def test_a_non_finite_float_never_reaches_the_client_as_a_bare_token(monkeypatch):
    def compute(champion, mode="sr", **_kw):
        p = _ok_payload(champion, mode)
        p["win_rate"] = float("nan")
        return p

    monkeypatch.setattr(rpb.personal_build_wr, "compute_personal_build", compute)
    h = _H("champion=Vayne")
    rpb._serve_personal_build(h)
    body = h.json()  # strict parse raises on NaN
    assert h.status == 503
    assert body["ok"] is False
    assert "nan" not in json.dumps(body).lower()


@pytest.mark.parametrize("bad", [None, [], "oops", 7])
def test_a_non_dict_compute_result_is_a_degraded_503(monkeypatch, bad):
    monkeypatch.setattr(
        rpb.personal_build_wr, "compute_personal_build", lambda *a, **k: bad)
    h = _H("champion=Vayne")
    rpb._serve_personal_build(h)
    assert h.status == 503
    assert h.json() == {"ok": False, "error": "rewind history unavailable"}


def test_a_non_finite_payload_is_not_cached(monkeypatch):
    calls = []

    def compute(champion, mode="sr", **_kw):
        calls.append(1)
        p = _ok_payload(champion, mode)
        if len(calls) == 1:
            p["win_rate"] = float("inf")
        return p

    monkeypatch.setattr(rpb.personal_build_wr, "compute_personal_build", compute)
    rpb._serve_personal_build(_H("champion=Vayne"))
    h = _H("champion=Vayne")
    rpb._serve_personal_build(h)
    assert h.status == 200
    assert h.json()["cached"] is False


def test_compute_exception_text_is_never_sent(monkeypatch):
    def compute(*_a, **_k):
        raise RuntimeError("secret-path <repo>/rewind_history.db locked")

    monkeypatch.setattr(rpb.personal_build_wr, "compute_personal_build", compute)
    h = _H("champion=Vayne")
    rpb._serve_personal_build(h)
    assert h.status == 503
    assert b"secret-path" not in h.calls[-1][1]


def test_cache_stays_bounded(compute_calls):
    for i in range(rpb._CACHE_MAX + 10):
        rpb._serve_personal_build(_H(f"champion=c{i}"))
    assert len(rpb._CACHE) <= rpb._CACHE_MAX
