"""Concurrency + resource-budget regression tests for the rank-tier live path.

core.rank_tier_bench mirrors core.smoothed_rates_101qq and core.rank_tier_source
mirrors core.synergy_external_source. The mirrored pair carries four defects
that this file pins:

  A  NETWORK I/O UNDER THE CACHE LOCK. _load_once() took _LOCK and then, still
     holding it, ran _try_live_grid() - a 10-tier x 2-mode = 20 cell sweep, each
     cell a fresh HTTP GET at rank_tier_source._TIMEOUT_S = 6.0s. That is a
     ~120s floor on the worst case with the lock that source() and
     rank_tier_grid() both take held the whole time. Probed here from a SECOND
     thread with a non-blocking acquire: _LOCK is an RLock, so a same-thread
     acquire always succeeds and would make the probe vacuous.

  B  NO NEGATIVE CACHING in rank_tier_source.fetch_rows - only successes were
     cached, so a down endpoint was re-paid in full on every one of the 20 cells
     of every refresh.

  C  UNBOUNDED RESPONSE READ in rank_tier_source._http_get_json - `r.read()`
     with no size cap over untrusted third-party bytes.

  D  CACHE KEY OMITTED ENDPOINT IDENTITY - keyed on (tier, mode) only, so an
     operator endpoint change kept serving the OLD endpoint's rows for up to the
     6h TTL. The key must carry a DIGEST of the endpoint, never the raw string
     (it can embed an API key), and that digest must never reach a log line or
     an exception message.

  E  NON-FINITE FLOATS FROM UNTRUSTED INPUT. json.loads accepts the
     non-standard literals NaN / Infinity / -Infinity by default; the value then
     passes isinstance(x, float), survives float() (which raises neither
     TypeError nor ValueError on a nan), lands in the grid, and json.dumps
     re-emits a bare NaN token that a browser JSON.parse REJECTS. One poisoned
     cell breaks the WHOLE /api/rank-tier-bench body, not one row. Verified by
     probe against the pre-fix modules before these tests were written.

  F  RAW ENDPOINT / URL IN EXCEPTION MESSAGES. Four raise sites in
     rank_tier_source._http_get_json interpolated the full fetch URL, and
     _build_url composes that URL verbatim from the operator-configured
     endpoint - so a credential in the endpoint query string landed in the
     exception message ("<endpoint>?api_key=... fetch failed: <urlopen error
     timed out>", proved live). _config_identity's docstring asserted the
     OPPOSITE invariant and named this file as its guard, but the guard
     filtered candidate lines with `if "ident" in s or "digest" in s`, so an
     f-string interpolating `url` was structurally invisible to it: it passed
     vacuously against the very string that carried the credential. The
     replacement below is an AST taint scan over EVERY raise and logging site
     in the module, with its own non-vacuity self-test, plus runtime probes
     that drive each failure path and assert the credential appears nowhere in
     the raised message OR anywhere in its __cause__ / __context__ chain.

No test here performs real network I/O: the HTTP seam and the module's own
opener (open_consented, RM-1441; urlopen before) are stubbed.
"""
from __future__ import annotations

import ast
import json
import math
import sys
import threading
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core import rank_tier_bench as RTB  # noqa: E402
from core import rank_tier_source as RTS  # noqa: E402
from tests._timing_budget import fleet_test_guard  # noqa: E402
from itertools import starmap


def _bind_opener(monkeypatch, fake) -> None:
    """RTS's OWN opener name (the `with open_consented(...)` in
    _http_get_json, RM-1441; it was `urllib.request.urlopen` before) ->
    FAKE, never the shared urllib.request a foreign thread of the xdist worker
    would also see (RM-801). setattr refuses a missing name, so a rename of
    the module's opener fails here instead of reaching the real network."""
    assert callable(getattr(RTS, "open_consented", None)), "RTS has no open_consented"
    monkeypatch.setattr(RTS, "open_consented", fake)


def _settle(timeout_s: float = 15.0) -> bool:
    """Block until no background bench refresh is in flight (True when idle)."""
    waiter = getattr(RTB, "_await_refresh_for_tests", None)
    if waiter is None:
        return True
    return bool(waiter(timeout_s))


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("RC_RANK_TIER_LIVE", raising=False)
    RTB._reset_cache()
    RTS._reset_cache_for_tests()
    yield
    _settle()
    RTB._reset_cache()
    RTS._reset_cache_for_tests()


def _write_config(tmp_path, monkeypatch, cfg) -> Path:
    p = tmp_path / "rank_tier_source.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(RTS, "_CONFIG_PATH", p)
    return p


def _rows():
    return [{"role": "all", "bracket": "early", "metric": "cs", "avg": 150.0}]


# --- defect A: no network I/O under the cache lock -----------------------

def test_defect_a_sweep_size_and_timeout_are_what_the_fix_assumes():
    """Ground truth for the ~120s figure: 10 tiers x 2 modes x 6.0s."""
    assert len(RTB.VALID_TIERS) == 10
    assert len(RTB.VALID_MODES) == 2
    assert RTS._TIMEOUT_S == 6.0
    assert len(RTB.VALID_TIERS) * len(RTB.VALID_MODES) * RTS._TIMEOUT_S == 120.0


def test_defect_a_bench_lock_is_not_held_across_the_live_fetch(monkeypatch):
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    started = threading.Event()
    release = threading.Event()

    def _slow_fetch(tier, mode, **kw):
        started.set()
        release.wait(10.0)

    monkeypatch.setattr(RTS, "fetch_rows", _slow_fetch)
    RTB._reset_cache()

    got = False
    worker = threading.Thread(target=RTB.source, name="rtb-probe", daemon=True)
    worker.start()
    try:
        assert started.wait(fleet_test_guard.budget(10.0)), "the live sweep never started"
        # _LOCK is an RLock: this probe is only meaningful from a thread that is
        # NOT the one inside the sweep, because a same-thread acquire always
        # succeeds and would pass even against the defect.
        assert threading.current_thread() is not worker
        got = RTB._LOCK.acquire(blocking=False)
        if got:
            RTB._LOCK.release()
    finally:
        release.set()
        worker.join(20.0)
    assert got, "network I/O ran while holding rank_tier_bench._LOCK"
    assert _settle()


def test_defect_a_stale_grid_is_served_without_waiting_for_the_sweep(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(RTB, "_clock", lambda: clock[0])
    RTB._reset_cache()
    # Cold start (allowed to block) publishes the static seed.
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["cs"]["avg"] == 140

    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    clock[0] += RTB._TTL_S + 1.0            # the cached grid is now stale

    first = {"seen": False}
    started = threading.Event()
    gate = threading.Event()

    def _slow_fetch(tier, mode, **kw):
        if not first["seen"]:
            first["seen"] = True
            started.set()
            gate.wait(2.0)

    monkeypatch.setattr(RTS, "fetch_rows", _slow_fetch)

    t0 = time.monotonic()
    grid = RTB.rank_tier_grid("iron", "SR")
    elapsed = time.monotonic() - t0
    gate.set()

    assert grid["all"]["early"]["cs"]["avg"] == 140, "stale grid was not served"
    assert started.wait(fleet_test_guard.budget(10.0)), "the refresh never ran at all"
    # Capped under the 2.0 s parked sweep, so a read that waits on it fails.
    assert elapsed < min(fleet_test_guard.budget(1.0), 1.8), (
        f"a stale read blocked {elapsed:.2f}s behind the live sweep"
    )
    assert _settle()


def test_defect_a_only_one_refresh_runs_at_a_time(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(RTB, "_clock", lambda: clock[0])
    RTB._reset_cache()
    assert RTB.source() == "static"

    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    clock[0] += RTB._TTL_S + 1.0

    gate = threading.Event()
    tally = threading.Lock()
    live_now = [0]
    peak = [0]

    def _slow_sweep():
        with tally:
            live_now[0] += 1
            peak[0] = max(peak[0], live_now[0])
        gate.wait(1.0)
        with tally:
            live_now[0] -= 1
        return {}

    monkeypatch.setattr(RTB, "_try_live_grid", _slow_sweep)

    threads = [threading.Thread(target=RTB.source, daemon=True) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(20.0)
    gate.set()
    assert _settle()
    assert peak[0] >= 1, "no refresh ran - the probe is vacuous"
    assert peak[0] == 1, f"{peak[0]} refreshes ran concurrently"


def test_defect_a_live_sweep_stops_at_the_wall_clock_budget(monkeypatch):
    budget = getattr(RTB, "_LIVE_BUDGET_S", None)
    assert isinstance(budget, float) and budget > 0, "no live-sweep wall budget"

    clock = [0.0]
    monkeypatch.setattr(RTB, "_clock", lambda: clock[0])
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")

    calls = []

    def _slow_fetch(tier, mode, **kw):
        calls.append((tier, mode))
        clock[0] += (budget / 2.0) + 0.1

    monkeypatch.setattr(RTS, "fetch_rows", _slow_fetch)
    RTB._reset_cache()
    RTB.source()
    assert _settle()
    assert calls, "the sweep never ran"
    assert len(calls) <= 3, (
        f"the sweep burned {len(calls)} of 20 cells past a {budget}s budget"
    )


# --- defect B: negative caching -----------------------------------------

def test_defect_b_failed_fetch_is_negative_cached(monkeypatch, tmp_path):
    neg_ttl = getattr(RTS, "_NEG_TTL_S", None)
    assert isinstance(neg_ttl, float) and neg_ttl > 0, "no negative-cache TTL"

    _write_config(tmp_path, monkeypatch, {
        "endpoint": "https://agg.example/agg", "tier_param": "tier", "enabled": True,
    })
    calls = []

    def _boom(url, timeout_s=RTS._TIMEOUT_S):
        calls.append(url)
        raise RTS.RankTierSourceError("endpoint down")

    monkeypatch.setattr(RTS, "_http_get_json", _boom)
    clock = [1000.0]
    monkeypatch.setattr(RTS, "_clock", lambda: clock[0])

    assert RTS.fetch_rows("iron", "SR") is None
    assert RTS.fetch_rows("iron", "SR") is None
    assert RTS.fetch_rows("iron", "SR") is None
    assert len(calls) == 1, (
        f"a down endpoint was re-paid {len(calls)} times inside the negative TTL"
    )

    clock[0] += neg_ttl + 1.0
    assert RTS.fetch_rows("iron", "SR") is None
    assert len(calls) == 2, "the negative cache never expires"


def test_defect_b_force_refresh_bypasses_the_negative_cache(monkeypatch, tmp_path):
    _write_config(tmp_path, monkeypatch, {
        "endpoint": "https://agg.example/agg", "tier_param": "tier", "enabled": True,
    })
    calls = []
    healthy = {"yes": False}

    def _seam(url, timeout_s=RTS._TIMEOUT_S):
        calls.append(url)
        if not healthy["yes"]:
            raise RTS.RankTierSourceError("endpoint down")
        return {"data": _rows()}

    monkeypatch.setattr(RTS, "_http_get_json", _seam)
    clock = [1000.0]
    monkeypatch.setattr(RTS, "_clock", lambda: clock[0])

    assert RTS.fetch_rows("iron", "SR") is None
    assert len(calls) == 1
    assert RTS.fetch_rows("iron", "SR") is None            # negative-cached
    assert len(calls) == 1

    healthy["yes"] = True
    rows = RTS.fetch_rows("iron", "SR", force_refresh=True)
    assert len(calls) == 2, "force_refresh did not bypass the negative cache"
    assert rows and rows[0]["avg"] == 150.0
    # A success must CLEAR the negative entry, not merely be shadowed by the
    # positive one. _NEG_TTL_S (60s) is far shorter than _TTL_S (6h) and the
    # positive cache is consulted first, so a leftover failure record is
    # invisible through the public API - the invariant only exists if asserted
    # directly, and a mutation probe proved it untested without this line.
    assert RTS._neg_cache == {}, RTS._neg_cache
    assert RTS.fetch_rows("iron", "SR") == rows
    assert len(calls) == 2


# --- defect C: bounded response read ------------------------------------

class _FakeResponse:
    """Minimal urlopen stand-in that records every read() size argument."""

    def __init__(self, body: bytes, reads: list, status: int = 200):
        self._body = body
        self._pos = 0
        self._reads = reads
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amt=-1):
        self._reads.append(amt)
        if amt is None or amt < 0:
            chunk = self._body[self._pos:]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos:self._pos + amt]
        self._pos += len(chunk)
        return chunk


def test_defect_c_oversize_response_body_is_rejected(monkeypatch):
    cap = getattr(RTS, "_MAX_BODY_BYTES", None)
    assert isinstance(cap, int) and cap > 0, "no response size cap"
    # Deliberately VALID JSON, so a module without the cap parses it happily and
    # this test fails for the right reason instead of on a JSON error.
    body = b'{"data":[{"role":"all"}],"pad":"' + (b"x" * (cap + 1024)) + b'"}'
    reads = []
    _bind_opener(monkeypatch,
                 lambda req, timeout=None: _FakeResponse(body, reads))
    with pytest.raises(RTS.RankTierSourceError, match="exceeds"):
        RTS._http_get_json("https://agg.example/agg")


def test_defect_c_response_read_is_size_bounded(monkeypatch):
    cap = getattr(RTS, "_MAX_BODY_BYTES", None)
    assert isinstance(cap, int) and cap > 0, "no response size cap"
    body = json.dumps({"data": _rows()}).encode("utf-8")
    reads = []
    _bind_opener(monkeypatch,
                 lambda req, timeout=None: _FakeResponse(body, reads))
    out = RTS._http_get_json("https://agg.example/agg")
    assert out["data"]
    assert reads, "the response was never read"
    assert all(isinstance(n, int) and 0 < n <= cap + 1 for n in reads), reads


# --- defect D: endpoint-aware cache key ---------------------------------

def test_defect_d_endpoint_change_invalidates_the_cache(monkeypatch, tmp_path):
    p = _write_config(tmp_path, monkeypatch, {
        "endpoint": "https://alpha.example/agg", "tier_param": "tier", "enabled": True,
    })
    seen = []

    def _seam(url, timeout_s=RTS._TIMEOUT_S):
        seen.append(url)
        avg = 1.0 if "alpha.example" in url else 2.0
        return {"data": [
            {"role": "all", "bracket": "early", "metric": "cs", "avg": avg},
        ]}

    monkeypatch.setattr(RTS, "_http_get_json", _seam)

    first = RTS.fetch_rows("iron", "SR")
    assert first and first[0]["avg"] == 1.0
    assert len(seen) == 1

    p.write_text(json.dumps({
        "endpoint": "https://beta.example/agg", "tier_param": "tier", "enabled": True,
    }), encoding="utf-8")

    second = RTS.fetch_rows("iron", "SR")
    assert len(seen) == 2, "the old endpoint's rows were served after a config change"
    assert second and second[0]["avg"] == 2.0


def test_defect_d_cache_key_carries_a_digest_not_the_raw_endpoint(monkeypatch, tmp_path):
    secret = "sUpErSeCrEtApiKey123"
    _write_config(tmp_path, monkeypatch, {
        "endpoint": f"https://agg.example/agg?api_key={secret}",
        "tier_param": "tier", "enabled": True,
    })
    monkeypatch.setattr(RTS, "_http_get_json",
                        lambda url, timeout_s=RTS._TIMEOUT_S: {"data": _rows()})
    assert RTS.fetch_rows("iron", "SR")

    blob = repr(list(RTS._cache.keys())) + repr(list(RTS._neg_cache.keys()))
    assert secret not in blob, "a credential from the endpoint landed in a cache key"
    assert "agg.example" not in blob, "the raw endpoint landed in a cache key"
    assert "iron" in blob and "SR" in blob, "the key lost its (tier, mode) identity"


def test_defect_d_config_identity_is_stable_and_endpoint_sensitive():
    a = RTS._config_identity({"endpoint": "https://a.example/x", "tier_param": "tier"})
    a2 = RTS._config_identity({"endpoint": "https://a.example/x", "tier_param": "tier"})
    b = RTS._config_identity({"endpoint": "https://b.example/x", "tier_param": "tier"})
    c = RTS._config_identity({"endpoint": "https://a.example/x", "tier_param": "rank"})
    assert a == a2                      # stable across calls
    assert a not in (b, c)              # endpoint + tier_param both bind
    assert len(a) <= 32 and a.isalnum()  # short digest, not a URL


# --- defect E: non-finite floats from untrusted input --------------------

_NON_FINITE_LITERALS = ("NaN", "Infinity", "-Infinity")


def _raw_body(literal: str) -> bytes:
    return (
        '{"data":[{"role":"all","bracket":"early","metric":"cs","avg":'
        + literal + "}]}"
    ).encode("utf-8")


@pytest.mark.parametrize("literal", _NON_FINITE_LITERALS)
def test_defect_e_http_get_json_rejects_non_finite_literals(monkeypatch, literal):
    reads = []
    _bind_opener(monkeypatch,
                 lambda req, timeout=None: _FakeResponse(_raw_body(literal), reads))
    with pytest.raises(RTS.RankTierSourceError):
        RTS._http_get_json("https://agg.example/agg")


@pytest.mark.parametrize("literal", _NON_FINITE_LITERALS)
def test_defect_e_fetch_rows_is_none_and_yields_no_poisoned_row(
        monkeypatch, tmp_path, literal):
    _write_config(tmp_path, monkeypatch, {
        "endpoint": "https://agg.example/agg", "tier_param": "tier", "enabled": True,
    })
    reads = []
    _bind_opener(monkeypatch,
                 lambda req, timeout=None: _FakeResponse(_raw_body(literal), reads))
    rows = RTS.fetch_rows("iron", "SR")
    # Not merely "is None" - a None can happen for the wrong reason. Pin that
    # NO row carrying a non-finite avg ever reaches a caller.
    assert rows is None
    for r in rows or []:
        assert math.isfinite(float(r.get("avg"))), r


def test_defect_e_finite_payload_still_succeeds_through_the_whole_chain(
        monkeypatch, tmp_path):
    """The cap must not over-reject: the happy path is unchanged."""
    _write_config(tmp_path, monkeypatch, {
        "endpoint": "https://agg.example/agg", "tier_param": "tier", "enabled": True,
    })
    body = _raw_body("150.5")
    reads = []
    _bind_opener(monkeypatch,
                 lambda req, timeout=None: _FakeResponse(body, reads))
    rows = RTS.fetch_rows("iron", "SR")
    assert rows and len(rows) == 1
    assert rows[0]["avg"] == 150.5
    assert math.isfinite(rows[0]["avg"])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_defect_e_fold_rows_drops_non_finite_avgs(bad):
    good = {"role": "all", "bracket": "early", "metric": "kda", "avg": 2.5}
    poison = {"role": "all", "bracket": "early", "metric": "cs", "avg": bad}
    out = RTB._fold_rows([poison, good])
    assert "cs" not in out.get("all", {}).get("early", {}), out
    assert out["all"]["early"]["kda"]["avg"] == 2.5, "a good row was dropped too"


def test_defect_e_fold_rows_rejects_bool_avgs():
    """Deliberate choice: bool is a subclass of int and float(True) is 1.0, but
    a boolean is not a measured average - accepting it would manufacture a
    benchmark number out of a type error. Rows with a bool avg are DROPPED."""
    out = RTB._fold_rows([
        {"role": "all", "bracket": "early", "metric": "cs", "avg": True},
        {"role": "all", "bracket": "early", "metric": "kp", "avg": False},
    ])
    assert out == {}, out


def test_defect_e_every_avg_in_a_live_overlaid_grid_is_finite(monkeypatch):
    """Positive whole-grid assertion, plus a strict JSON round trip proving the
    dashboard body a browser receives can never carry a bare NaN token."""
    live_rows = [
        {"role": "all", "bracket": "early", "metric": "cs", "avg": 777.0},
        {"role": "all", "bracket": "mid", "metric": "cs", "avg": float("nan")},
        {"role": "all", "bracket": "mid", "metric": "kp", "avg": float("inf")},
    ]
    monkeypatch.setattr(RTS, "fetch_rows", lambda tier, mode, **k: list(live_rows))
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    RTB._reset_cache()
    assert RTB.source() == "live"

    seen = 0
    whole = {}
    for tier in RTB.VALID_TIERS:
        for mode in RTB.VALID_MODES:
            grid = RTB.rank_tier_grid(tier, mode)
            whole[f"{tier}:{mode}"] = grid
            for _role, brackets in grid.items():
                for _bracket, metrics in brackets.items():
                    for metric, cell in metrics.items():
                        seen += 1
                        avg = cell["avg"]
                        assert isinstance(avg, (int, float))
                        assert math.isfinite(avg), (tier, mode, metric, avg)
    assert seen > 0, "the grid was empty - the assertion is vacuous"
    # The finite live cell must still have landed (proves we did not just drop
    # the whole live overlay to make the assertion easy).
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["cs"]["avg"] == 777.0

    def _reject(const):
        raise AssertionError(f"non-standard JSON constant emitted: {const}")

    json.loads(json.dumps(whole), parse_constant=_reject)
    assert _settle()


# --- defect F: no message site may carry the raw endpoint or URL ---------

# An obvious dummy. NEVER a real credential - it only has to be a string that
# could not turn up in a message by accident.
_DUMMY_KEY = "dummy-not-a-real-key"
_DUMMY_ENDPOINT = f"https://agg.example/agg?api_key={_DUMMY_KEY}"


def _dummy_url() -> str:
    """The URL the module would really fetch for a credentialed endpoint."""
    return RTS._build_url(_DUMMY_ENDPOINT, "tier", "iron", "SR")


def _exception_chain(exc):
    """`exc` plus every __cause__ / __context__ behind it.

    Both links matter: `raise X from exc` puts the original on __cause__ and a
    plain raise inside an except block puts it on __context__ - traceback
    prints either, so a credential in either is a credential in the log."""
    out, seen = [], set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        out.append(cur)
        cur = cur.__cause__ or cur.__context__
    return out


def _assert_no_credential(exc, *, url=None):
    """No link in the chain may carry the dummy credential or the raw URL, and
    the head must still name the endpoint - a message redacted down to nothing
    is its own regression."""
    raw = _dummy_url() if url is None else url
    for link in _exception_chain(exc):
        text = f"{type(link).__name__}: {link}"
        assert _DUMMY_KEY not in text, text
        assert "api_key" not in text, text
        assert raw not in text, text
    head = str(exc)
    assert "agg.example" in head, f"redacted past usefulness: {head!r}"


def test_defect_f_http_status_message_carries_no_credential(monkeypatch):
    reads = []
    _bind_opener(
        monkeypatch,
        lambda req, timeout=None: _FakeResponse(b"{}", reads, status=503))
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)
    assert "503" in str(ei.value), str(ei.value)


def test_defect_f_transport_failure_message_carries_no_credential(monkeypatch):
    def _boom(req, timeout=None):
        raise RTS.urllib.error.URLError("timed out")

    _bind_opener(monkeypatch, _boom)
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)
    assert "timed out" in str(ei.value), "the underlying failure was dropped"


def test_defect_f_a_transport_error_quoting_the_url_is_scrubbed(monkeypatch):
    """Adversarial: urllib is free to quote the URL it was handed straight back
    at us, so a wrapped third-party message is untrusted text, not a safe
    diagnostic - it has to be redacted before it is re-raised."""
    def _boom(req, timeout=None):
        raise RTS.urllib.error.URLError(f"cannot reach {_dummy_url()}")

    _bind_opener(monkeypatch, _boom)
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)


def test_defect_f_bad_json_message_carries_no_credential(monkeypatch):
    reads = []
    _bind_opener(
        monkeypatch,
        lambda req, timeout=None: _FakeResponse(b"{not json", reads))
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)
    assert "JSON" in str(ei.value), str(ei.value)


def test_defect_f_non_dict_toplevel_message_carries_no_credential(monkeypatch):
    reads = []
    _bind_opener(
        monkeypatch,
        lambda req, timeout=None: _FakeResponse(b"[1, 2, 3]", reads))
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)
    assert "list" in str(ei.value), str(ei.value)


def test_defect_f_oversize_body_message_carries_no_credential(monkeypatch):
    cap = RTS._MAX_BODY_BYTES
    body = b'{"data":[{"role":"all"}],"pad":"' + (b"x" * (cap + 1024)) + b'"}'
    reads = []
    _bind_opener(
        monkeypatch,
        lambda req, timeout=None: _FakeResponse(body, reads))
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)
    assert "exceeds" in str(ei.value), str(ei.value)


def test_defect_f_malformed_endpoint_message_carries_no_credential(monkeypatch):
    """SIBLING SITE. urllib.request.Request itself raises
    ValueError("unknown url type: %r" % url) for a schemeless endpoint, and
    that message quotes the RAW url, credential included. It is raised while
    BUILDING the request, so the fetch try/except never saw it. The stubbed
    urlopen is belt and braces - this must not reach the network either way."""
    def _boom(req, timeout=None):
        raise RTS.urllib.error.URLError("stub - must not be reached")

    _bind_opener(monkeypatch, _boom)
    url = RTS._build_url(f"agg.example/agg?api_key={_DUMMY_KEY}", "tier", "iron", "SR")
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(url)
    _assert_no_credential(ei.value, url=url)


def test_defect_f_safe_url_drops_query_fragment_and_userinfo():
    assert RTS._safe_url(_DUMMY_ENDPOINT) == "https://agg.example/agg?<redacted>"
    assert (RTS._safe_url(f"https://user:{_DUMMY_KEY}@agg.example:8443/agg")
            == "https://agg.example:8443/agg")
    assert _DUMMY_KEY not in RTS._safe_url(f"https://agg.example/agg#{_DUMMY_KEY}")
    assert RTS._safe_url("") == "<endpoint>"


def test_defect_f_redact_scrubs_a_wrapped_third_party_message():
    url = _dummy_url()
    out = RTS._redact(f"unknown url type: {url!r} (key {_DUMMY_KEY})", url)
    assert _DUMMY_KEY not in out, out
    assert "unknown url type" in out, "the diagnostic was thrown away with the key"


# The STATIC half. The guard this replaces filtered candidate lines with
# `if "ident" in s or "digest" in s`, which made it structurally incapable of
# seeing an f-string interpolating `url`. This one is an AST taint scan.

_SANITIZERS = ("_safe_url", "_redact")
# A name is credential-bearing if it mentions any of these. "ident" / "digest"
# preserve the ORIGINAL defect-D intent: the cache-key digest is derived from a
# possibly-credentialed endpoint and must not reach a message either.
_TAINTED_NAME_PARTS = ("url", "endpoint", "ident", "digest")
_TAINTED_CALLS = ("_build_url", "_config_identity")
# Reaching into config by one of these keys pulls the raw endpoint out even
# when no local variable is named "url".
_CONFIG_SECRET_KEYS = {"endpoint", "api_key", "apikey", "token", "secret"}
_LOG_FUNCS = {"print", "debug", "info", "warning", "warn", "error",
              "exception", "critical", "log", "write"}


def _call_name(node) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


_LOG_ROOTS = frozenset({"logging", "logger", "sys", "warnings", "traceback"})


def _is_log_name(name) -> bool:
    """A log-ish name: `log`, `_log`, `logging`, `self._logger`'s
    `_logger`, `get_logger`, `getLogger`, `sys`. `catalog` is not."""
    low = name.lower()
    return (low.lstrip("_").startswith("log") or low in _LOG_ROOTS
            or "logger" in low)


def _chain_names(expr):
    """Every name along an attribute / call chain, outermost first, and the
    chain's root: `a.b().c` gives ([c, b, a], Name a)."""
    names = []
    while isinstance(expr, (ast.Attribute, ast.Call)):
        if isinstance(expr, ast.Attribute):
            names.append(expr.attr)
            expr = expr.value
        else:
            expr = expr.func
    if isinstance(expr, ast.Name):
        names.append(expr.id)
    return names, expr


# S144-Q-91: the literal displays. Their value is always an instance of the
# builtin type itself, never of a class the module defines, and a builtin
# type takes no new attribute, so an attribute off one is the builtin's own.
# An f-string is one unless it is exactly one field (`_builtin_receiver`).
_BUILTIN_DISPLAYS = (ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict,
                     ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _builtin_receiver(expr) -> bool:
    """S144-Q-91: `expr` is a literal display (`', '.join`, `[1].count`,
    `f'at {u}'.strip`), so no class attribute mark (`_ATTR_MARKS`) is read
    off it, whatever its name. An f-string that is ONE field and nothing
    else (`f'{u}'`, `f'{u:>3}'`, `f'{u!s}'`) is not one: its value is
    what the field's `__format__` returns, which may be an instance of a
    `str` subclass the module defines (verifier, measured on 3.14); joining
    a literal part or a second field always builds a plain `str`. Every
    other receiver - a name, a call, an operator - may be an instance of
    the class that made the mark, so it stays read: the safe side.
    Residual: a name bound only to a literal (`s = 'x'; s.strip()`) is
    still read, since the marks carry no receiver type."""
    if isinstance(expr, ast.JoinedStr):
        return len(expr.values) != 1 or isinstance(expr.values[0], ast.Constant)
    return isinstance(expr, _BUILTIN_DISPLAYS)


def _is_logger_expr(expr, tainted=frozenset()) -> bool:
    """`expr` may evaluate to a logger OBJECT (RM-1563): a log-ish name
    anywhere along its chain (`log`, `self.log`, `get_logger()`,
    `logging.getLogger(n)`), a chain rooted at a name bound to one
    (`_LOGOBJ`), or a conditional either arm of which is one. RM-1563: so
    is a chain through an attribute a class body bound to a logger object
    (`self.lg` after `class C: lg = logging.getLogger()`)."""
    if isinstance(expr, ast.IfExp):
        return (_is_logger_expr(expr.body, tainted)
                or _is_logger_expr(expr.orelse, tainted))
    names, root = _chain_names(expr)
    if isinstance(root, ast.Name):
        if _LOGOBJ + root.id in tainted:
            return True
        attrs = names[:-1]
    elif _builtin_receiver(root) and names:
        attrs = names[:-1]    # S144-Q-91: the first attribute is the builtin's
    else:
        attrs = names
    if any(_LOGOBJATTR + n in tainted for n in attrs):
        return True
    return any(_is_log_name(n) for n in names)


def _is_log_call(node, tainted=frozenset()) -> bool:
    """print(...), or a <level>(...) call on a logger object.

    RM-1562: the chain walk goes through calls as well as attributes, so
    `logging.getLogger(__name__).info(...)` is a log call.
    RM-1563: the receiver is judged by `_is_logger_expr`, so every name
    along its chain counts, not only the root (`self.log.info`,
    `get_logger().info`), and so does a name bound to a logger object
    (`lg = logging.getLogger(); lg.info`). The called method's own name is
    not part of the receiver: `client.log(...)` is not a log call."""
    name = _call_name(node)
    if name == "print":
        return True
    if name not in _LOG_FUNCS:
        return False
    f = node.func
    if isinstance(f, ast.Name):
        return _is_log_name(f.id)
    return isinstance(f, ast.Attribute) and _is_logger_expr(f.value, tainted)


class _TaintScan(ast.NodeVisitor):
    """Every term in one expression that could carry the raw endpoint.

    Calls to the module's own sanitizers are PRUNED rather than descended into,
    so `_safe_url(url)` is clean while a bare `url` is not."""

    def __init__(self, tainted_locals, late=frozenset()):
        self._tainted = tainted_locals
        self._late = late
        self.found = []

    def _visit_deferred(self, node):
        # RM-1560 (a): a lambda or generator body runs later, so it reads
        # every name the scope may EVER bind (`late`), not only the current
        # state: `h = lambda: m` before `m = url` makes `h()` carry the url.
        saved = self._tainted
        self._tainted = set(saved) | set(self._late)
        try:
            self.generic_visit(node)
        finally:
            self._tainted = saved

    visit_Lambda = visit_GeneratorExp = _visit_deferred

    def visit_Call(self, node):
        name = _call_name(node)
        if name in _SANITIZERS:
            return
        if name in _TAINTED_CALLS:
            self.found.append(f"{name}()")
        self.generic_visit(node)

    def visit_Name(self, node):
        low = node.id.lower()
        if (node.id in self._tainted or _OBJ + node.id in self._tainted
                or any(p in low for p in _TAINTED_NAME_PARTS)):
            self.found.append(node.id)

    def visit_Attribute(self, node):
        if any(p in node.attr.lower() for p in ("url", "endpoint")):
            self.found.append(f".{node.attr}")
        if isinstance(node.value, ast.Name) and _object_only(node.value.id,
                                                             self._tainted):
            # `r.status` off a with-as object is clean; the url attributes
            # were judged above (RM-1558).
            return
        self.generic_visit(node)

    def visit_Constant(self, node):
        if (isinstance(node.value, str)
                and node.value.strip().lower() in _CONFIG_SECRET_KEYS):
            self.found.append(f"config key {node.value!r}")


# RM-1558: a with-as target built from a credential-bearing value is an
# OBJECT, held in the state as `_OBJ + name`. Its repr may quote what it was
# built from (a file object quotes its path), so a BARE reference to it is a
# leak, while an attribute read or method call off it (`r.status`,
# `r.read(n)`) is not - the url attributes (`.geturl`, `.full_url`) are caught
# by the attribute rule. Residual: a non-url attribute that still carries the
# value (a file object's `.name`) is not seen.
_OBJ = "obj:"
# RM-1562: a name bound to a logging function is held as `_LOGFN + name`.
# It carries no value (a bare reference to it is clean); a CALL through it is
# a sink (`_log_args`).
_LOGFN = "logfn:"
# RM-1563: a name bound to a logger OBJECT (`lg = logging.getLogger()`,
# `p = log`, `lg = self.log`) is held as `_LOGOBJ + name`. Like `_LOGFN` it
# carries no value; a level call off it (`lg.info(m)`) is a sink.
_LOGOBJ = "logobj:"
# RM-1563: a name a CLASS BODY binds at its own level to a logging function
# or logger object is a class attribute, held as `_LOGATTR + name` /
# `_LOGOBJATTR + name` (`_class_attr_marks`). Any attribute of that name is
# then read as one - off `self`, `cls`, the class or an instance (`self.p(m)`,
# `self.lg.info(m)`). The receiver is not checked, and the marks flow out of
# the class with the rest of its state, so `o.p(m)` after the class is a sink
# whatever `o` is: the safe side. S144-Q-91: except off a literal display
# (`'{}'.p(m)`, `_builtin_receiver`), whose attribute is the builtin's own.
_LOGATTR = "logattr:"
_LOGOBJATTR = "logobjattr:"
# RM-1786: a WRAPPER (`_SINKFN`) the class body binds at its own level - a
# def, a lambda, or a staticmethod / classmethod over one - is a method, held
# as `_SINKATTR + name + " " + kind + " " + spec` (`_class_attr_marks`), and a
# wrapper stored on an attribute (`self.g = lambda m: log.info(m)`) makes the
# same mark with the kind `_attr_store_kinds` gives it (`_retaint`). The kind
# says how a call off an attribute of that name binds the first parameter
# (`_attr_specs`): `static` binds nothing, `cls` always binds it, `any` is
# read both ways (RM-1563: `C.g = lambda self, m: ...` from outside), and
# `inst:<class>` binds it unless the receiver is the class name itself
# (`C.g(o, url)` is unbound). On a call that binds it, the first parameter
# of a plain method is the receiver itself (`_RECV`). As with `_LOGATTR`, the
# receiver is otherwise not checked: the safe side. S144-Q-91: except that no
# attribute mark is read off a literal display (`_builtin_receiver`).
_SINKATTR = "sinkattr:"
# RM-1790: a def that puts one parameter's value INTO the object another
# parameter names (`def h(q, v): q.append(v)`, `def h(self, v): self.q = v`)
# is a MUTATING helper, held as `_MUTFN + name + " " + dst + ">" + src`, one
# entry per (mutated parameter spec, source parameter spec) pair, in the
# `_SINKFN` spec grammar (`_mut_specs`). A call through it whose `src`
# argument is tainted taints the names of its `dst` argument, add-only, as
# `q.append(url)` taints `q` (`_bind_mut_calls`). A class body turns one into
# `_MUTATTR + name + " " + kind + " " + dst + ">" + src`, read off an
# attribute call as `_SINKATTR` is, so `self.h(url)` taints `self`.
# RM-1793: a def that puts an ENCLOSING tainted name into a parameter
# (`G = url; def h(q): q.append(G)`) makes the pair `dst>*` (`_MUT_ALWAYS`):
# a call through it taints its `dst` argument whatever it is passed. The
# sink- and mutating-parameter judges (`_judge_params`, `_judge_mut_params`)
# walk without those pairs (`_without_always`), so a wrapper that hands its
# own parameter to such a helper keeps that parameter's sink spec.
_MUTFN = "mutfn:"
_MUTATTR = "mutattr:"
_MUT_ALWAYS = "*"
# RM-1794: a plain binding of a name to an attribute or element of a name
# (`d = m.cache`, `b = m[0]`) makes it hold a PART of that name's object,
# held as the directed mark `_ALIAS + d + " " + m`: a value put into the
# part is in the whole. A binding to the bare name (`a = m`) holds the
# WHOLE object, so it is marked both ways (`_new_alias_marks`). A value put
# INTO an object in place (an attribute or element store, a `_MUTATORS`
# call, `setattr`, an augmented assignment that fills a list, set or dict
# (`_IN_PLACE_AUG`), a mutating helper) then taints
# every name the marks reach from its root, transitively
# (`_taint_aliases`). A store into the whole does not reach a part read
# out before (`p = d['k']; d['k'] = v` leaves `p` alone). Every re-binding
# of a name (`=`, and a `for` / `with` / walrus / except / import / match /
# def / class target) ends its marks and leaves what reached it marked to
# what it reached (`_drop_aliases`); a def's own names shadow the marks of
# the scope around it (`_shadow_aliases`), as a lambda's parameters and a
# comprehension's targets do in their view (`_call_views`), and a def's
# locals' marks do not flow out (`_drop_locals`). Like `_LOGFN` the marks
# carry no value. S144-Q-113 (c): an object STORED into a container
# (`a.append(k)`, `a.x = k`, `b = [k]`, a mutating helper) is a part of it
# too, marked `_ALIAS + k + " " + a` (`_held_marks`), so a value put into
# `k` later is in `a`.
_ALIAS = "alias:"


def _object_only(name, tainted) -> bool:
    low = name.lower()
    return (_OBJ + name in tainted and name not in tainted
            and not any(p in low for p in _TAINTED_NAME_PARTS))


_TYPE_ALIAS = (ast.TypeAlias,) if hasattr(ast, "TypeAlias") else ()


def _retaint(stmt, tainted, late=frozenset()) -> None:
    """Propagate taint across one binding statement. Scope is deliberately
    small - assignments (except-as names are bound at handler entry in
    `_flow_block`) - because that is what carries a URL into a message;
    reaching a URL off an object is caught by the attribute rule (`.full_url`,
    `.geturl`) instead of by over-tainting the object."""
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        # RM-1794: an import re-binds its names, as a `type` statement
        # re-binds its own.
        for alias in stmt.names:
            _drop_aliases((alias.asname or alias.name).split(".")[0], tainted)
        return
    if isinstance(stmt, _TYPE_ALIAS):
        _drop_target_aliases(stmt.name, tainted)
        return
    if isinstance(stmt, ast.Assign):
        targets, value = stmt.targets, stmt.value
    elif isinstance(stmt, (ast.AugAssign, ast.AnnAssign)):
        targets, value = [stmt.target], stmt.value
    else:
        return
    if value is None:
        return
    found = _is_tainted(value, tainted, late)
    plain = not isinstance(stmt, ast.AugAssign)
    # Every target is judged against the state BEFORE any of them is bound,
    # as Python evaluates the value once: `p, q = q, p` swaps the aliases.
    aliases = ([b for t in targets for b in _alias_bindings(t, value, tainted)]
               if plain else [])
    # RM-1563: `p = lambda m: log.info(m)` makes `p` a wrapper.
    # RM-1786: so does a staticmethod / classmethod over a lambda.
    # RM-1563: and an alias of a wrapper (`h = g`), a conditional over
    # one, and a re-wrap by name (`g = staticmethod(g)`), judged before the
    # binding drops the target's own wrapper. A tuple target is split as a
    # logging alias is (`_wrapper_bindings`: `h, k = g, fetch`, `h, k = k, h`).
    wrappers = ([b for t in targets for b in _wrapper_bindings(t, value, tainted, late)]
                if plain else [])
    # S144-Q-96: a mutating helper is bound the same ways (`k = h`,
    # `h = lambda q, v: q.append(v)`).
    muts = ([b for t in targets
             for b in _wrapper_bindings(t, value, tainted, late, _value_mut_specs)]
            if plain else [])
    # RM-1563: `self.p = log.info` stores the alias in an attribute, as a
    # class body's `p = log.info` does, so it makes the same mark. Add-only:
    # one store does not replace what another instance or the class holds.
    # RM-1786: a wrapper stored on an attribute is a method mark, its kind
    # read off the receiver and the value (`_attr_store_kinds`). RM-1563:
    # a store off any receiver but `self` may land on a class
    # (`C.g = lambda self, m: ...`, `cls.g = ...`), which binds `self`.
    # S144-Q-96: so is a mutating helper (`_MUTATTR`, `_attr_store_marks`).
    attr_marks = set()
    for target in targets if plain else []:
        if isinstance(target, ast.Attribute):
            attr_marks |= _attr_store_marks(target.attr, target.value, value,
                                            tainted, late)
    tainted |= attr_marks
    # RM-1794: the object marks the binding makes, judged before it ends
    # the targets' own marks (`a = a.q` still reaches what `a` did).
    joined = _new_alias_marks(targets, value, tainted) if plain else set()
    # S144-Q-113 (c): what the binding stores into a container is a part of
    # it (`b = [k]`, `a.x = k`, and `a += [k]` in place), judged before the
    # targets are re-bound, as the alias marks are. A store into an
    # attribute or element of an object the binding did not re-bind first
    # is applied before the re-binding too, so one that ends a held name or
    # the container's own ends the mark with it (`d.x, a = a, []` holds the
    # old `a`). A name bound to a new container, and a store into an
    # object an earlier target re-bound (`a, a.x = C(), k`: `_held_pairs`
    # `late`), is applied with the alias marks, after the old marks end;
    # there a held name the binding re-binds (`a = [a]`, `b, k = [k], []`)
    # was read before it was, so it stands for what reached its OLD object
    # (`j = k` before: `j`), as `_new_alias_marks` reads `a = a.q`.
    # Residuals: a `for` / `with` target store (`for a.x in [k]`) holds
    # nothing; and (the safe side) a container emptied or a part replaced
    # (`a.clear()`, `a.pop()`, `a[0] = []` after `a[0] = k`) still holds
    # what it held.
    if plain:
        bound = set()
        pairs = [p for t in targets for p in _held_pairs(t, value, bound)]
    else:
        bound = set()
        pairs = [(_chain_root(sub), _held_roots(value), False)
                 for sub in _in_place_targets(stmt.target, stmt)]
    early = set()
    for container, held, after in pairs:
        if not after:
            early |= _held_marks(container, held)
            continue
        joined |= _held_marks(container, held - bound)
        old = held & bound
        if old:
            joined |= {_alias_mark(s, container) for s, d in _alias_edges(tainted)
                       if d in old and s != container}
    tainted |= early
    for target in targets:
        # `m += "!"` keeps whatever `m` already carried (RM-1443): only a
        # plain re-binding to a clean value clears a name.
        _bind_names(target, found, tainted, clear=plain)
    if found:
        # RM-1794: a store INTO an object reaches every alias of it.
        for target in targets:
            for sub in _in_place_targets(target, stmt):
                _taint_aliases(sub, tainted)
    tainted |= joined
    for name, is_alias, is_obj in aliases:
        _bind_log_alias(name, is_alias, tainted, is_obj)
    for name, specs in wrappers:
        _bind_wrapper(name, specs, tainted)
    for name, pairs in muts:
        _bind_mut(name, pairs, tainted)


_METHOD_WRAPPERS = ("staticmethod", "classmethod")


def _method_wrapped(value):
    """RM-1786: the callable a staticmethod / classmethod call `value`
    wraps, or None if `value` is no such call."""
    if (isinstance(value, ast.Call) and _call_name(value) in _METHOD_WRAPPERS
            and value.args):
        return value.args[0]
    return None


def _value_wrapper_specs(value, tainted, late=frozenset(), mark=None):
    """The `_SINKFN` specs of the callable `value` evaluates to, judged with
    `tainted` as it stands: a lambda's own (RM-1563), the one a staticmethod
    / classmethod wraps (RM-1786), and RM-1563: a name already bound to
    a wrapper (`h = g`, and `g = staticmethod(g)` through the wrapper call)
    and either arm of a conditional. Empty for any other value.
    S144-Q-96: with `mark=_MUTFN` the same read gives the `_MUTFN` pairs
    of a mutating helper (`_value_mut_specs`)."""
    mark = mark or _SINKFN
    inner = _method_wrapped(value)
    if inner is not None:
        return _value_wrapper_specs(inner, tainted, late, mark)
    if isinstance(value, ast.Lambda):
        judge = _mut_specs if mark == _MUTFN else _sink_specs
        return set(judge(value, tainted, late))
    if isinstance(value, ast.Name):
        prefix = mark + value.id + " "
        return {e[len(prefix):] for e in tainted if e.startswith(prefix)}
    if isinstance(value, ast.IfExp):
        return (_value_wrapper_specs(value.body, tainted, late, mark)
                | _value_wrapper_specs(value.orelse, tainted, late, mark))
    return set()


def _value_mut_specs(value, tainted, late=frozenset()):
    """S144-Q-96: the `_MUTFN` pairs of the callable `value` evaluates to,
    read as `_value_wrapper_specs` reads a wrapper: a lambda's own, the
    one a staticmethod / classmethod wraps, a name already bound to a
    mutating helper (`k = h`) and either arm of a conditional."""
    return _value_wrapper_specs(value, tainted, late, _MUTFN)


def _attr_store_marks(attr, recv, value, tainted, late=frozenset()):
    """RM-1563 / RM-1786: the marks a store of `value` on attribute `attr`
    of `recv` from outside a class body makes (`self.p = log.info`,
    `self.g = lambda m: log.info(m)`): `_LOGATTR` / `_LOGOBJATTR` for a
    logging function or logger object, and a method mark per kind
    (`_attr_store_kinds`) and spec for a wrapper (`_SINKATTR`) and,
    S144-Q-96, a mutating helper (`_MUTATTR`). Shared by `_retaint` and
    a `setattr` with a literal name (`_bind_setattr_marks`)."""
    marks = set()
    if _is_log_callable(value, tainted):
        marks.add(_LOGATTR + attr)
    if _is_logger_expr(value, tainted):
        marks.add(_LOGOBJATTR + attr)
    for attr_mark, specs in ((_SINKATTR, _value_wrapper_specs(value, tainted, late)),
                             (_MUTATTR, _value_mut_specs(value, tainted, late))):
        if specs:
            marks.update(f"{attr_mark}{attr} {kind} {spec}"
                         for kind in _attr_store_kinds(recv, value)
                         for spec in specs)
    return marks


def _value_kinds(value):
    """RM-1786 / RM-1563: how a class body's binding of `value` binds
    the first parameter: (kinds, alias source names). A staticmethod /
    classmethod call gives `static` / `cls`, a lambda `inst`, a name the
    kinds of what it names (resolved by `_class_method_kinds`), and a
    conditional the union of its arms."""
    inner = _method_wrapped(value)
    if inner is not None:
        return {_METHOD_KIND[_call_name(value)]}, set()
    if isinstance(value, ast.Lambda):
        return {"inst"}, set()
    if isinstance(value, ast.Name):
        return set(), {value.id}
    if isinstance(value, ast.IfExp):
        k1, s1 = _value_kinds(value.body)
        k2, s2 = _value_kinds(value.orelse)
        return k1 | k2, s1 | s2
    return set(), set()


_METHOD_KIND = {"staticmethod": "static", "classmethod": "cls"}


def _attr_store_kinds(recv, value):
    """RM-1786 / RM-1563: the `_SINKATTR` kinds of a wrapper `value`
    stored on an attribute of `recv` from outside a class body (`_retaint`).
    A staticmethod binds nothing wherever it is stored: `static`. Off
    `self` the store lands on an instance, where a plain function (a
    lambda, or a name: a def) binds nothing either: `static`. Off any other
    receiver it may land on a class (`C.g = lambda self, m: ...`,
    `cls.g = ...`), where a plain function binds `self` off an instance and
    nothing off the class, and the receiver's own nature is unknown, so it
    is read both ways: `any`; a classmethod stored there always binds its
    first parameter: `cls`. A classmethod stored off `self` is read both
    ways too: the safe side. A conditional gives the union of its arms."""
    own, sources = _value_kinds(value)
    if sources or not own:
        own = own | {"inst"}
    on_self = isinstance(recv, ast.Name) and recv.id == "self"
    kinds = set()
    for kind in own:
        if kind == "static" or (on_self and kind == "inst"):
            kinds.add("static")
        elif kind == "cls" and not on_self:
            kinds.add("cls")
        else:
            kinds.add("any")
    return kinds


def _is_tainted(expr, tainted, late=frozenset()) -> bool:
    scan = _TaintScan(tainted, late)
    scan.visit(expr)
    return bool(scan.found)


def _bind_names(target, found, tainted, *, clear=True) -> None:
    """Bind every name in `target` to a value that is (`found`) or is not
    credential-bearing. `clear=False` only ever ADDS taint.

    RM-1559: only a plain name (bare, or inside a tuple / list / starred
    target) is REPLACED by the binding, so only it is cleared. A store into
    an element or an attribute (`m[1] = 'x'`, `self.n = 0`) leaves the rest
    of the container behind and only READS its index, so it only ever adds
    taint - to every name in it, the index included, as before."""
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _bind_names(elt, found, tainted, clear=clear)
        return
    if isinstance(target, ast.Starred):
        _bind_names(target.value, found, tainted, clear=clear)
        return
    if isinstance(target, ast.Name):
        if found:
            tainted.add(target.id)
        elif clear:
            tainted.discard(target.id)
            tainted.discard(_OBJ + target.id)
        if clear:
            # A plain re-binding replaces a logging-function alias or a
            # logger object whatever the new value is (RM-1562 / -77);
            # `_bind_log_alias` re-adds it.
            tainted.discard(_LOGFN + target.id)
            tainted.discard(_LOGOBJ + target.id)
            _drop_wrapper(target.id, tainted)
            _drop_aliases(target.id, tainted)
        return
    if found:
        fresh = _fresh_callees(target)
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name) and id(sub) not in fresh:
                tainted.add(sub.id)


def _alias_roots(value):
    """RM-1794: (root, whole) for every name whose object a plain binding
    of `value` may reach: the root of a name / attribute / element chain
    (`m`, `m.q`, `m[0]`: `m`), through either arm of a conditional, every
    operand of an `or` / `and` and both sides of a walrus. `whole` is True
    when the value IS the root's object (a bare name), False when it is a
    part of it. A call, a literal, an operator or a slice makes a new
    object (`list(m)`, `[m]`, `m + n`, `m[:]`): none. Residual: a slice of
    an object whose slice is a view (a numpy array) is one too."""
    if isinstance(value, ast.IfExp):
        return _alias_roots(value.body) | _alias_roots(value.orelse)
    if isinstance(value, ast.BoolOp):
        return set().union(*(_alias_roots(v) for v in value.values))
    if isinstance(value, ast.NamedExpr):
        return _alias_roots(value.value) | {(value.target.id, True)}
    if isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Slice):
        # A slice is a new list / str / tuple (`out = items[:]`); an
        # element of one (`m[1:][0]`) is still a part of `m`.
        return set()
    root = _chain_root(value)
    return {(root, isinstance(value, ast.Name))} if root is not None else set()


def _alias_pairs(target, value):
    """RM-1794: (name, `_alias_roots`) for every plain name binding
    `target = value` makes. A tuple target is paired element by element
    with a tuple value of the same length and no starred part
    (`a, b = m, n`); any other unpacking binds each name to a PART of the
    value. A starred target is a new list: none."""
    if isinstance(target, ast.Name):
        return [(target.id, _alias_roots(value))]
    if not isinstance(target, (ast.Tuple, ast.List)):
        return []
    elts = target.elts
    if (isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(elts)
            and not any(isinstance(e, ast.Starred) for e in (*elts, *value.elts))):
        return [p for t, v in zip(elts, value.elts) for p in _alias_pairs(t, v)]
    parts = {(root, False) for root, _ in _alias_roots(value)}
    return [(name, parts) for t in elts for name, _ in _alias_pairs(t, value)]


def _alias_edges(entries):
    """RM-1794: the `_ALIAS` marks in `entries` as (from, to) pairs."""
    return [tuple(e[len(_ALIAS):].split(" ", 1)) for e in entries
            if e.startswith(_ALIAS)]


def _alias_mark(src, dst):
    return f"{_ALIAS}{src} {dst}"


def _new_alias_marks(targets, value, tainted):
    """RM-1794: the `_ALIAS` marks `targets = value` makes, judged
    against `tainted` as it stands. A name bound to a PART of an object
    (`a = m.q`) reaches it: a value put into the part is in the whole.
    Only a name bound to the WHOLE object (`a = m`) is also reached from
    it; a store into the whole (`m['q'] = v`) replaces a part and leaves
    the one read out before alone. A root that is the target itself
    (`a = a.q`) stands for what the target reached before (and, for a
    whole, what reached it). Residual: a root that is ANOTHER target of
    the same binding (`a, b = b, a`) is read by its new name, so the two
    are marked to each other, as the plain taint of a swap is kept (the
    safe side)."""
    marks = set()
    edges = None
    for target in targets:
        for name, roots in _alias_pairs(target, value):
            for root, whole in roots:
                if root != name:
                    marks.add(_alias_mark(name, root))
                    if whole:
                        marks.add(_alias_mark(root, name))
                    continue
                if edges is None:
                    edges = _alias_edges(tainted)
                marks |= {_alias_mark(name, d) for s, d in edges if s == name != d}
                if whole:
                    marks |= {_alias_mark(s, name) for s, d in edges if d == name != s}
    return marks


_DISPLAYS = (ast.List, ast.Tuple, ast.Set)


def _held_roots(value):
    """S144-Q-113 (c): the root names of the objects a container that
    stores `value` then HOLDS: what `value` may be (`_alias_roots`: `k`,
    `k.q`, either arm of a conditional, both sides of a walrus) and every
    element of a list, tuple, set or dict display in it, nested displays
    and a dict's keys included (`[k]`, `{'x': [k]}`). A call, an operator,
    a slice or a comprehension is read as a new object holding none of
    them (`list(k)`, `k[:]`, `[x for x in k]`). Residuals: one may still
    hold `k` (`[k] + []`, `[k] * 2`, `list([k])`, `dict(x=k)`, `W(k)`,
    `[k for _ in xs]`, and `a = a + [k]`, `a += (k,)`) or a shallow copy
    `k`'s PARTS (`a.append(k[:]); k[0].append(url)`), and a later fill is
    missed there; and (the safe side) a
    root stands for its whole object, so a part (`a.append(k.q)`) or the
    items a starred element or an `extend` / `update` argument copies
    (`[*k]`, `a.extend(k)`) are read as `k` itself, and a later fill of
    `k` is read as reaching the container."""
    if isinstance(value, _DISPLAYS):
        return set().union(*(_held_roots(e) for e in value.elts))
    if isinstance(value, ast.Dict):
        return set().union(*(_held_roots(e) for e in (*value.keys, *value.values)
                             if e is not None))
    if isinstance(value, ast.IfExp):
        return _held_roots(value.body) | _held_roots(value.orelse)
    if isinstance(value, ast.BoolOp):
        return set().union(*(_held_roots(v) for v in value.values))
    if isinstance(value, ast.NamedExpr):
        return _held_roots(value.value) | {value.target.id}
    return {root for root, _ in _alias_roots(value)}


def _contained_roots(value):
    """S144-Q-113 (c): the root names of the objects a NEW container that
    `value` builds holds (`[k]`, `{'x': k}`, through either arm of a
    conditional, every operand of an `or` / `and` and a walrus's value):
    a name bound to it holds them. The value itself, when it is a name or
    a part of one, is an alias, not a container (`_alias_roots`)."""
    if isinstance(value, (*_DISPLAYS, ast.Dict)):
        return _held_roots(value)
    if isinstance(value, ast.IfExp):
        return _contained_roots(value.body) | _contained_roots(value.orelse)
    if isinstance(value, ast.BoolOp):
        return set().union(*(_contained_roots(v) for v in value.values))
    if isinstance(value, ast.NamedExpr):
        return _contained_roots(value.value)
    return set()


def _held_marks(container, held):
    """S144-Q-113 (c): the `_ALIAS` marks `held -> container`: an object a
    container holds is a PART of it, so a value put into it later is in
    the container (`a.append(k); k.append(url)` fills `a`). One-way, as a
    part read out is: a value put into the container does not reach what
    it holds. A container that hangs off no name (`f().append(k)`) gets
    no mark: no name could reach it (a guard against a mark to `None`,
    which no program can read)."""
    if container is None:
        return set()
    return {_alias_mark(r, container) for r in held if r != container}


def _held_pairs(target, value, bound):
    """S144-Q-113 (c): (container root, `_held_roots`, late) for every
    object `target = value` stores into a container: a plain name bound to
    a new container holds what the display holds (`b = [k]`:
    `_contained_roots`), and an attribute or element store puts the value
    itself into the target's root (`a.x = k`, `a['x'] = [k]`:
    `_held_roots`). A tuple target is paired element by element with a
    tuple value of the same length and no starred part; any other
    unpacking stores a PART of the value into each attribute or element
    target (read as the whole: the safe side) and binds each name to a
    part (`_alias_pairs`). A starred name is a new list of parts
    (residual: not a container here); a starred attribute or element
    (`*a.x, b = p`) holds them as any store does. Python stores the targets left to
    right, so `bound` collects the names re-bound so far, and `late` says
    the store lands in an object bound by this binding: a name's new
    container, or an attribute or element of a root an earlier target
    re-bound (`a, a.x = C(), k` fills the new `a`)."""
    if isinstance(target, ast.Name):
        bound.add(target.id)
        return [(target.id, _contained_roots(value), True)]
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        root = _chain_root(target)
        return [(root, _held_roots(value), root in bound)]
    if not isinstance(target, (ast.Tuple, ast.List)):
        return []
    elts = target.elts
    if (isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(elts)
            and not any(isinstance(e, ast.Starred) for e in (*elts, *value.elts))):
        return [p for t, v in zip(elts, value.elts) for p in _held_pairs(t, v, bound)]
    # A part of the value goes to each target: an attribute or element
    # store holds it (read as the whole value), a name only binds it.
    held = _held_roots(value)
    out = []

    def walk(t):
        if isinstance(t, ast.Starred):
            walk(t.value)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                walk(e)
        elif isinstance(t, ast.Name):
            bound.add(t.id)
        elif isinstance(t, (ast.Attribute, ast.Subscript)):
            root = _chain_root(t)
            out.append((root, held, root in bound))
    for t in elts:
        walk(t)
    return out


def _call_held_marks(call, view):
    """S144-Q-113 (c): the `_ALIAS` marks a call that stores its arguments
    into an object makes (`_held_marks`): the receiver of a `_MUTATORS`
    call, the object of `setattr` or an unbound dunder store
    (`_mutated_exprs`) holds every argument (`a.append(k)`,
    `a.insert(0, k)`, `d.setdefault('x', k)`, `setattr(o, 'x', k)`), and a
    mutating helper's destination holds its source argument (`h(a, k)`
    with `def h(q, v): q.append(v)`: `_mut_pairs`, read from `view`).
    Residuals: a key is read as held too (`d.__setitem__(k, v)`, the safe
    side); a helper pair says only that the source's VALUE reaches the
    destination, so `def h(q, v): q.append(str(v))` is read as holding
    `v` (the safe side); a receiver, or a held name, re-bound by a walrus
    later in the same call (`a.append((a := n) or k)`,
    `a.extend([k, (k := [])])`, `h(a, k, (k := []))`) is marked at its
    new object, so a fill of the old one is missed (so is a display that
    re-binds its own element: `a = [k, (k := [])]`); and a destination
    passed starred from a display (`h(*[a], k)`) hangs off no name, so
    it gets no mark."""
    marks = set()
    targets = _mutated_exprs(call)
    if targets:
        held = set().union(*(_held_roots(a) for a in
                             (*call.args, *(kw.value for kw in call.keywords))))
        for target in targets:
            marks |= _held_marks(_chain_root(target), held)
    for dst, src in _mut_pairs(call, view):
        if src == _MUT_ALWAYS:
            continue
        held = set().union(*(_held_roots(a) for a in _spec_args(call, {src})))
        for arg in _spec_args(call, {dst}):
            marks |= _held_marks(_chain_root(arg), held)
    return marks


def _drop_aliases(name, tainted) -> None:
    """RM-1794: a re-binding of `name` ends the `_ALIAS` marks it is in;
    what reached it still reaches what it reached (`a = m; b = a; a = []`
    leaves `b` reaching `m`), so those are marked to each other."""
    edges = [(s, d) for s, d in _alias_edges(tainted) if name in (s, d)]
    if not edges:
        return
    tainted -= set(starmap(_alias_mark, edges))
    froms = {s for s, d in edges if d == name}
    tos = {d for s, d in edges if s == name}
    tainted |= {_alias_mark(s, d) for s in froms for d in tos if s != d}


def _drop_target_aliases(target, tainted) -> None:
    """RM-1794: `_drop_aliases` for every plain name a binding target
    re-binds (a bare, tuple, list or starred name; an attribute or element
    store re-binds no name). Used for a target that may be a tuple: a
    `for`, `with` or comprehension target and a `type` statement name. The
    single-name forms call `_drop_aliases` directly (a walrus, except,
    import, match capture, def, class and lambda parameter), and `=`
    reaches it through `_bind_names`."""
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _drop_target_aliases(elt, tainted)
    elif isinstance(target, ast.Starred):
        _drop_target_aliases(target.value, tainted)
    elif isinstance(target, ast.Name):
        _drop_aliases(target.id, tainted)


def _shadow_aliases(entries, names):
    """RM-1794: `entries` without the `_ALIAS` marks about a name in
    `names` (the same object when nothing is dropped). S144-Q-108: what
    reached a hidden name still reaches what it reached (`a = m; b = a;
    def h(a): b.append(url)` fills `m`), so the chains through `names` are
    bridged (`_alias_bridges`), as `_drop_aliases` bridges a re-binding."""
    drop = {e for e in entries if e.startswith(_ALIAS)
            and not names.isdisjoint(e[len(_ALIAS):].split(" ", 1))}
    if not drop:
        return entries
    return (entries - drop) | _alias_bridges(_alias_edges(drop), names)


def _alias_bridges(edges, hidden):
    """S144-Q-108: the `_ALIAS` marks `src -> d` for every `src` and `d`
    not in `hidden` where `src` reaches `d` through `edges` by way of
    names in `hidden` only. A scope that cannot see the names in `hidden`
    still holds the objects they linked."""
    adj = {}
    for src, dst in edges:
        adj.setdefault(src, set()).add(dst)
    marks = set()
    for src, dsts in adj.items():
        if src in hidden:
            continue
        stack = [d for d in dsts if d in hidden]
        seen = set(stack)
        while stack:
            for d in adj.get(stack.pop(), ()):
                if d in hidden:
                    if d not in seen:
                        seen.add(d)
                        stack.append(d)
                elif d != src:
                    marks.add(_alias_mark(src, d))
    return marks


def _taint_aliases(expr, tainted, view=None) -> None:
    """RM-1794: a value put in place into the object `expr` hangs off
    (`_chain_root`) is in that object whatever name reaches it, so every
    name the `_ALIAS` marks reach from the root, transitively, carries it
    too. Add-only. The marks are read from `view`, the state the call or
    store reads (`_call_views`: a lambda parameter or comprehension target
    has none of the enclosing marks), else from `tainted`. The late view is
    never added: it still holds the marks a re-binding ended (`a = m;
    a = []`), and a def body walked from it gets its marks in its entry."""
    root = _chain_root(expr)
    if root is None:
        return
    edges = {}
    for src, dst in _alias_edges(tainted if view is None else view):
        edges.setdefault(src, set()).add(dst)
    if edges:
        tainted |= _alias_closure({root}, edges) - {root}


# RM-1794: the augmented assignments that put a value INTO a list, set or
# dict in place, keyed by operator: `a += [v]` (a list display: only a list
# or a mutable sequence takes one in place), `a |= {v}` (a set or dict
# display), `a ^= {v}` (a set display). Any other operator or value may
# re-bind the name to a new object (`msg += url`, `msg %= {'u': v}`,
# `n *= [v]`), which leaves an alias of the old object alone; `-=` and `&=`
# put nothing in. Residual: a frozenset `|=` / `^=` re-binds as well.
_IN_PLACE_AUG = {
    ast.Add: (ast.List, ast.ListComp),
    ast.BitOr: (ast.Set, ast.SetComp, ast.Dict, ast.DictComp),
    ast.BitXor: (ast.Set, ast.SetComp),
}


def _in_place_targets(target, stmt):
    """RM-1794: the parts of binding statement `stmt`'s `target` that
    are changed in place rather than re-bound: an attribute or element
    store, and the plain name of an augmented assignment `_IN_PLACE_AUG`
    reads as one."""
    if isinstance(target, (ast.Tuple, ast.List)):
        return [x for elt in target.elts for x in _in_place_targets(elt, stmt)]
    if isinstance(target, ast.Starred):
        return _in_place_targets(target.value, stmt)
    if isinstance(target, ast.Name):
        in_place = (isinstance(stmt, ast.AugAssign) and isinstance(
            stmt.value, _IN_PLACE_AUG.get(type(stmt.op), ())))
        return [target] if in_place else []
    return [target]


# RM-1792: builtin constructors whose call always returns a NEW object, so
# a value put into what one returns (`h(dict(), url)`, `dict().update(u=url)`,
# `list()[0] = url`) is not in anything the name `dict` reaches afterwards.
# Only the bare builtins: `make()` may hand back a shared object, and tainting
# `make` is how the walk follows it (`h(make(), url); log.info(make())`).
_FRESH_CTORS = frozenset({"dict", "list", "set", "bytearray"})
# The `_FRESH_CTORS` names the module under scan binds anywhere (filled and
# cleared by `_message_leak_sites`): there the name may not be the builtin
# (`dict = get_shared`), so its callee keeps the old taint.
_SHADOWED_FRESH = set()


def _fresh_callees(expr):
    """RM-1792: the ids of the callee nodes in `expr` that are a call of an
    unshadowed `_FRESH_CTORS` builtin. Only the callee name is skipped; the
    call's arguments are still tainted, since a shallow copy shares its
    elements (`h(list(r), url)` with `def h(q, v): q[0].append(v)` puts the
    url into an element of `r`)."""
    return {id(sub.func) for sub in ast.walk(expr)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
            and sub.func.id in _FRESH_CTORS
            and sub.func.id not in _SHADOWED_FRESH}


# RM-1792: how one module can re-bind a builtin's name without a binding
# `_module_bound_names` sees. Any of these anywhere in the module keeps the old
# taint for every `_FRESH_CTORS` name:
# - ANY import but an absolute `from __future__`. An imported callable can re-bind a
#   builtin given only a string or a keyword (`mock.patch('builtins.dict', g)`,
#   `timeit.timeit(src)`, `patch.multiple(m, dict=g)`), and each verifier
#   round found one more such channel, so the exemption is kept for
#   import-free code, whose channels are the builtins and the object model.
# The rest is read off WORDS: every string a field of any node holds
# (`_node_words`: a name, attribute, string literal, keyword, parameter,
# def / class name, `global` name, match-pattern attribute):
# - a word that is a `_FRESH_CTORS` name (`o.dict = g`, `ns['dict'] = g`,
#   `f(dict=g)`), except in a plain Name node (the call `dict()` itself),
#   whose binding `_module_bound_names` reads instead;
# - ANY dunder word but the few in `_INERT_DUNDERS`: the object-model hooks
#   are dunders
#   (`f.__globals__`, `mod.__dict__`, `__builtins__`, `object.__setattr__`,
#   `f.__code__`, `__subclasses__`, `__import__`, `exc.__traceback__`, and a
#   metaclass `def __prepare__` whose class-body namespace answers for
#   `dict`, a `case object(__globals__=g)` pattern), so one rule covers the
#   whole class;
# - a `_BUILTIN_ESCAPES` word: the namespace, code,
#   class and file builtins (`globals()['dict']`, `exec(src)`,
#   `type(n, b, ns)`, `metaclass=`, `open` on the process memory) and the
#   frame and code object attributes reached without a dunder or an import
#   (`gen.gi_frame.f_globals`, `code.replace(co_names=...)`);
# - the name `getattr` anywhere but as the callee of a call whose attribute
#   name is a string literal (`_literal_getattrs`): with a computed name, or
#   held as a value (`ga = getattr`, `map(getattr, ...)`), it can fetch any of
#   the above without spelling it.
# A heuristic list of the channels measured so far, not a proof that none is
# left; a patch done from ANOTHER module is not visible to a one-file scan at
# all.
_INERT_DUNDERS = frozenset({"__name__", "__file__", "__doc__", "__all__",
                            "__main__", "__init__", "__version__"})
_BUILTIN_ESCAPES = frozenset({
    "globals", "locals", "vars", "exec", "eval", "compile", "setattr",
    "getattr", "delattr", "breakpoint", "help", "open", "type", "metaclass",
    "f_globals", "f_builtins", "f_locals", "f_back", "f_code", "tb_frame",
    "tb_next", "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame",
    "ag_code", "co_names", "co_consts", "co_code"})


def _literal_getattrs(tree):
    """RM-1792: the ids of the `getattr` callee names in `tree` whose call
    names its attribute with a string literal (`getattr(o, 'x')`,
    `getattr(o, 'x', None)`): the one use of the name that is not a channel.
    The literal itself is still read as a word by `_rebinds_builtins`."""
    return {id(c.func) for c in ast.walk(tree)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id == "getattr" and not c.keywords
            and len(c.args) in (2, 3)
            and not any(isinstance(a, ast.Starred) for a in c.args)
            and isinstance(c.args[1], ast.Constant)
            and isinstance(c.args[1].value, str)}


def _is_live_dunder(s) -> bool:
    """RM-1792: `s` is a dunder string outside `_INERT_DUNDERS`."""
    return (isinstance(s, str) and len(s) > 4 and s.startswith("__")
            and s.endswith("__") and s not in _INERT_DUNDERS)


def _node_words(n):
    """RM-1792: every string held by a field of AST node `n` (one level, a
    list field's strings included): a name, attribute, string literal,
    keyword, parameter, def / class name, import alias, `global` name or
    match-pattern attribute (`case object(__globals__=g)` keeps its
    attribute names as plain strings, not nodes)."""
    words = []
    for _, value in ast.iter_fields(n):
        if isinstance(value, str):
            words.append(value)
        elif isinstance(value, list):
            words.extend(v for v in value if isinstance(v, str))
    return words


def _rebinds_builtins(n) -> bool:
    """RM-1792: `n` is one of the run-time re-binding channels above."""
    if isinstance(n, ast.ImportFrom):
        return n.module != "__future__" or n.level > 0
    if isinstance(n, ast.Import):
        return True
    if isinstance(n, ast.Name) and n.id in _FRESH_CTORS:
        return False  # the call `dict()` itself; a binding is read elsewhere
    return any(w in _BUILTIN_ESCAPES or w in _FRESH_CTORS or _is_live_dunder(w)
               for w in _node_words(n))


def _module_bound_names(tree):
    """RM-1792: every name `tree` binds anywhere, in any scope: store and
    del targets, def / class names, parameters, PEP 695 type parameters,
    import aliases, `global` / `nonlocal` names, except-handler names and
    match captures. A run-time re-binding channel (`_rebinds_builtins`,
    any import included) may re-bind a builtin, so it counts as binding every
    `_FRESH_CTORS` name."""
    type_params = tuple(getattr(ast, k) for k in ("TypeVar", "ParamSpec", "TypeVarTuple")
                        if hasattr(ast, k))
    literal = _literal_getattrs(tree)
    out = set()
    for n in ast.walk(tree):
        if id(n) not in literal and _rebinds_builtins(n):
            out |= _FRESH_CTORS
        if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load):
            out.add(n.id)
        elif isinstance(n, (*type_params, ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.alias):
            out.add((n.asname or n.name).split(".")[0])
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
        elif isinstance(n, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            out.add(n.rest)
    return out


# RM-1558: methods that put their arguments INTO the receiver. A tainted
# argument taints the receiver's names (add-only, as an assignment target
# would: `self.seen.append(url)` taints `self` like `self.last = url` does).
# `write` is not here: it is a sink (`_LOG_FUNCS`).
_MUTATORS = frozenset({"append", "appendleft", "extend", "extendleft", "insert",
                       "add", "update", "setdefault", "put", "put_nowait",
                       "__setitem__", "__setattr__"})
# RM-1794: a dunder store takes (key, value) bound (`d.__setitem__(k, v)`:
# a `_MUTATORS` call off its receiver; the key is only read) and
# (object, key, value) called off a class (`object.__setattr__(o, 'u', v)`,
# `Base.__setattr__(self, 'u', v)`, `dict.__setitem__(d, k, v)`), so with
# exactly three positional arguments (a `*args` counts as one) it names its
# object in the FIRST one, as `setattr(o, 'u', v)` always does, and the
# class is not changed. Residuals: a bound call to a user dunder taking an
# extra parameter (`d.__setitem__(k, v, x)`) is read as unbound and taints
# `k`; a call off a class with any other count (`Base.__setattr__(o, *r)`)
# taints the class, as `list.append(d, v)` taints `list`.
_FIRST_ARG_MUTATORS = frozenset({"__setitem__", "__setattr__"})


def _mutated_exprs(call):
    """RM-1794: the expressions call `call` may put its arguments INTO:
    the receiver of a `_MUTATORS` call, or, for a `_FIRST_ARG_MUTATORS`
    one called off a class (exactly three positional arguments), its first
    argument; and the first argument of `setattr`."""
    f = call.func
    out = []
    if isinstance(f, ast.Attribute) and f.attr in _MUTATORS:
        unbound = f.attr in _FIRST_ARG_MUTATORS and len(call.args) == 3
        if unbound:
            out.append(call.args[0])
        else:
            out.append(f.value)
    elif isinstance(f, ast.Name) and f.id == "setattr" and call.args:
        out.append(call.args[0])
    return out


def _bind_mutators(sub, seen, tainted, late=frozenset(), recv=None) -> None:
    """`q.append(url)` leaves `q` carrying the url for the rest of the scope.
    Applied with the walrus bindings, before the statement's sinks.
    RM-1563: each call is judged with the view `_call_views` gives it, so
    one in a comprehension sees the comprehension's targets
    (`[q.append(x) for x in [url]]`). RM-1794: so does `setattr(q, 'u',
    url)` and a dunder store (`_mutated_exprs`), and the value reaches
    every alias of the object (`_taint_aliases`). S144-Q-108: one call
    `sub` read with view `seen`, in `_bind_in_order`'s order.
    S144-Q-110: `recv`, when given, holds the `_ALIAS` marks as they stood
    when each part of the call was read (`_bind_in_order`); the aliases of
    the object filled are read where it was (`_operand_view`: a receiver
    before the arguments, a `setattr` object before the later ones), so
    `a.append((a := n) or url)` fills what `a` named before the walrus.
    Its own names are still bound (the safe side)."""
    targets = _mutated_exprs(sub)
    if targets:
        args = list(sub.args) + [kw.value for kw in sub.keywords]
        if any(_is_tainted(a, seen, late) for a in args):
            for target in targets:
                _bind_names(target, True, tainted, clear=False)
                _taint_aliases(target, tainted,
                               _operand_view(sub, target, recv, seen))


def _bind_setattr_marks(call, seen, tainted, late=frozenset()) -> None:
    """S144-Q-96: `setattr(o, 'cb', h)` with a literal name stores `h` on
    an attribute as `o.cb = h` does, so it makes the same marks
    (`_attr_store_marks`: a logging function, a wrapper, a mutating
    helper). Add-only, as every attribute store is; each call is judged
    with the view `_call_views` gives it. A non-literal name is not
    tracked (residual). S144-Q-108: one call, in `_bind_in_order`'s
    order."""
    f, args = call.func, call.args
    if (isinstance(f, ast.Name) and f.id == "setattr" and len(args) == 3
            and not call.keywords
            and not any(isinstance(a, ast.Starred) for a in args)
            and isinstance(args[1], ast.Constant)
            and isinstance(args[1].value, str)
            and args[1].value.isidentifier()):
        tainted |= _attr_store_marks(args[1].value, args[0], args[2],
                                     seen, late)


# RM-1557: the binding forms this walk added - `for` targets, `with ... as`
# targets and walrus - only ever ADD taint, never clear a name. A clearing
# model was tried in cycle 128 and four independent verifier rounds each found
# real leaks it lost that the RM-1443 walk caught: a walrus that may not run
# (`c or (m := 'x')`, an `assert` message, under `python -O` the assert
# itself), a name read before its own walrus in one value (`m + (m := 'y')`),
# a `for` over a container the taint model sees as clean (`q.append(m)`), and
# `with open(m) as m`, whose file repr quotes its path. A leak guard is wrong
# on the side of a miss, so the precision is given up. Plain `=` keeps its
# RM-1443 clearing rule (`_retaint`).

def _bind_walrus(sub, seen, tainted, late=frozenset(), *, drop=True,
                 join=True) -> None:
    """`(m := url)` binds `m` for the rest of the scope. Applied BEFORE a
    statement's sinks are checked: a sink in the same expression may run
    after the walrus (`log.info(m) if (m := url) else None`).
    RM-1563: the value is judged with the view `_call_views` gives it, so
    a walrus in a comprehension sees the comprehension's targets
    (`[(m := x) for x in [url]]`); it still binds the enclosing scope.
    S144-Q-102: a walrus read with the enclosing state itself makes the
    `_ALIAS` marks `=` makes (`if (a := m): a.append(url)` fills `m`),
    judged before it ends the target's own. One read with a copied view (a
    comprehension, a generator, a lambda body or default) makes none, as
    a comprehension's value may name its own target, not the enclosing
    name (residual: a walrus there over an enclosing name, a lambda
    default's included, is not an alias).
    S144-Q-107: `drop=False` (a walrus that may not run, or any walrus on
    a re-pass) ends none of the target's marks, so the binding only ADDS.
    S144-Q-108: one walrus `sub` read with view `seen`, in
    `_bind_in_order`'s order. S144-Q-109: `join=False` (a re-pass of
    `_Flow._expr_step`'s fixed point) makes no `_ALIAS` marks: the first
    pass made them where the walrus stands, and a re-pass reads the marks
    of the later walruses too, so a rotation
    (`g((t := a), (a := b), (b := t))`) made every name reach every
    source."""
    is_alias = _is_log_callable(sub.value, seen)
    is_obj = _is_logger_expr(sub.value, seen)
    wrapper = _value_wrapper_specs(sub.value, seen, late)
    muts = _value_mut_specs(sub.value, seen, late)    # S144-Q-96
    joined = (_new_alias_marks([sub.target], sub.value, tainted)
              if join and seen is tainted else set())    # S144-Q-102
    if drop:
        _drop_aliases(sub.target.id, tainted)    # RM-1794
    tainted |= joined
    _bind_names(sub.target, _is_tainted(sub.value, seen, late),
                tainted, clear=False)
    _bind_log_alias(sub.target, is_alias, tainted, is_obj)
    # RM-1563: `(h := g)` makes `h` a wrapper, add-only like the rest of
    # the walrus binding. S144-Q-96: so does `(k := h)` a mutating helper.
    _bind_wrapper(sub.target.id, wrapper, tainted)
    _bind_mut(sub.target.id, muts, tainted)


def _bind_in_order(nodes, tainted, late=frozenset(), *, drop=True,
                   recv=None) -> bool:
    """S144-Q-108: apply the binding sites of `nodes` - every walrus
    (`_bind_walrus`) and every call that fills a receiver, a helper's
    argument or an attribute (`_bind_mutators`, `_bind_mut_calls`,
    `_bind_setattr_marks`) - one at a time in EVALUATION order
    (`_call_views` with `post=True`: a site after the parts it reads, in
    `_eval_children` order). Binding every walrus first ended an alias
    before an earlier fill read it, so
    `a = m; g(a.append(url), (a := n)); raise E(m)` was missed.
    Each site is judged with the view `_call_views` gave it when the sites
    of its node (one of `nodes`) were collected: a copied view (a
    comprehension, a generator, a lambda) does not see a binding made
    later in the same pass, which the fixed point of `_Flow._expr_step`
    re-reads on its next pass (it only adds), nor an alias an earlier
    walrus ended, so `g((a := n), [a.append(url) for _ in xs])` still
    fills `a`'s old source (the safe side).
    A walrus that may not run (`_maybe_skipped`) ends no alias: the path
    that skips it keeps the old ones (the RM-1557 rule, the safe side).
    `drop=False` (a re-pass) ends and makes no walrus `_ALIAS` marks
    (S144-Q-109).
    S144-Q-110: a call's receiver is read before its arguments, and each
    argument before the next, but the call is applied after them all, so
    the `_ALIAS` marks are kept as they stand after each part
    (`_PreCall`, a receiver's or argument's own walrus included) and a
    fill reaches what the object named then (`_operand_view`):
    `a.append((a := n) or url)` and `h(a, (a := n) or url)` fill `a`'s old
    object. They are kept in `recv` (by call and part) on the first pass
    and read from it on a re-pass, whose marks are those the first pass
    ended on. A copied view does not change within a pass, so it is its
    own record.
    S144-Q-113 (c): a call that stores an object into another makes it a
    part of that one (`_call_held_marks`), on the first pass only (a
    re-pass would read a name a later walrus re-bound) and only with the
    enclosing state itself, as a walrus's alias marks are (residual: a
    store in a comprehension, generator or lambda makes none).
    Returns whether any walrus ran with `drop` on, so may have ended marks
    (`_Flow._expr_step` then always re-passes)."""
    ended = False
    recv = {} if recv is None else recv
    for node in nodes:
        sites = []
        _call_views(node, tainted, late, sites,
                    kinds=(ast.NamedExpr, ast.Call), post=True)
        skipped = set()
        _maybe_skipped(node, skipped)
        for sub, seen in sites:
            if isinstance(sub, _PreCall):
                if drop and seen is tainted:
                    recv[(id(sub.call), id(sub.part))] = {
                        e for e in tainted if e.startswith(_ALIAS)}
                continue
            if isinstance(sub, ast.NamedExpr):
                ends = drop and id(sub) not in skipped
                ended = ended or ends
                _bind_walrus(sub, seen, tainted, late, drop=ends, join=drop)
                continue
            _bind_mutators(sub, seen, tainted, late, recv)
            _bind_mut_calls(sub, seen, tainted, late, recv)
            _bind_setattr_marks(sub, seen, tainted, late)    # S144-Q-96
            if drop and seen is tainted:
                tainted |= _call_held_marks(sub, seen)    # S144-Q-113 (c)
    return ended


def _maybe_skipped(node, out, maybe=False) -> None:
    """S144-Q-108: add to `out` the `id` of every walrus in `node` that may
    not run where it stands: an operand of `and` / `or` after the first, a
    link of a chained comparison after the first two operands, an arm of a
    conditional (not its test), any part of a comprehension or
    generator but its first iterable (the loop may run zero times), a
    lambda body (it runs later, if at all) and an `assert` (its message
    runs only when it fails, and under `python -O` none of it runs)."""
    if isinstance(node, ast.NamedExpr) and maybe:
        out.add(id(node))
    if isinstance(node, ast.BoolOp):
        for i, value in enumerate(node.values):
            _maybe_skipped(value, out, maybe or i > 0)
        return
    if isinstance(node, ast.IfExp):
        _maybe_skipped(node.test, out, maybe)
        _maybe_skipped(node.body, out, True)
        _maybe_skipped(node.orelse, out, True)
        return
    if isinstance(node, ast.Compare):
        _maybe_skipped(node.left, out, maybe)
        for i, value in enumerate(node.comparators):
            _maybe_skipped(value, out, maybe or i > 0)
        return
    if isinstance(node, _COMPREHENSIONS):
        first = node.generators[0].iter
        _maybe_skipped(first, out, maybe)
        eager = {id(sub) for sub in ast.walk(first)}
        out |= {id(sub) for sub in ast.walk(node)
                if isinstance(sub, ast.NamedExpr) and id(sub) not in eager}
        return
    if isinstance(node, ast.Lambda):
        out |= {id(sub) for sub in ast.walk(node.body)
                if isinstance(sub, ast.NamedExpr)}
        a = node.args
        for d in a.defaults + [d for d in a.kw_defaults if d is not None]:
            _maybe_skipped(d, out, maybe)
        return
    maybe = maybe or isinstance(node, ast.Assert)
    for child in ast.iter_child_nodes(node):
        _maybe_skipped(child, out, maybe)


# Context managers whose __enter__ hands back the object they were given.
_PASSTHROUGH_CMS = frozenset({"nullcontext", "closing"})


def _with_target_found(item, tainted, late=frozenset()) -> bool:
    """RM-1557: a `with ... as m` target is the context manager's __enter__
    result, usually an OBJECT (`with open_consented(req) as r:` must leave
    `r.status` clean), so it is not tainted as a VALUE by the call's
    arguments - it is bound as an object instead (`_bind_objects`,
    RM-1558), and the attribute rule covers `.url` / `.geturl` on it. The passthroughs
    (`nullcontext(x)`, `closing(x)`) hand `x` itself back, so they taint it.
    The binding only ever ADDS taint (see the `with` arm of `_Flow.stmt`)."""
    expr = item.context_expr
    if not (isinstance(expr, ast.Call) and _call_name(expr) in _PASSTHROUGH_CMS):
        return False
    args = list(expr.args) + [kw.value for kw in expr.keywords]
    return any(_is_tainted(a, tainted, late) for a in args)


def _bind_objects(target, tainted) -> None:
    """RM-1558: every other `with ... as` target whose context expression
    carries the value is bound as an OBJECT (`_OBJ`): a bare reference to it
    is a leak, `r.status` is not. Add-only, like every with binding. A target
    that is not a plain name (`as self.conn`, `as d[k]`) taints its names as
    VALUES, as `self.conn = Opn(url)` would: as an object, `self.conn` would
    read as a clean attribute of `self` though it IS the object."""
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _bind_objects(elt, tainted)
        return
    if isinstance(target, ast.Starred):
        _bind_objects(target.value, tainted)
        return
    if not isinstance(target, ast.Name):
        _bind_names(target, True, tainted, clear=False)
        return
    tainted.add(_OBJ + target.id)


def _capture_names(pattern):
    """Every name a `match` pattern binds (RM-1559): `case x`, `case _ as
    x`, `case [*rest]`, `case {**kw}` and the captures nested in sequence,
    mapping, class and or-patterns."""
    names = []
    for sub in ast.walk(pattern):
        if isinstance(sub, (ast.MatchAs, ast.MatchStar)) and sub.name:
            names.append(sub.name)
        elif isinstance(sub, ast.MatchMapping) and sub.rest:
            names.append(sub.rest)
    return names


def _join(*states):
    """May-taint union of the live states; None (unreachable) if none is."""
    live = [s for s in states if s is not None]
    return set().union(*live) if live else None


# Statement fields that hold nested statement lists. Everything else on a
# statement (an `if` test, a `for` iterable, a `with` item, a `match` subject,
# a decorator or a default) is evaluated where the statement stands.
_BLOCK_FIELDS = frozenset({"body", "orelse", "finalbody", "handlers", "cases"})
_TRY_TYPES = (ast.Try,) + ((ast.TryStar,) if hasattr(ast, "TryStar") else ())


def _own_nodes(stmt):
    """The expression-level parts of `stmt`, without its nested blocks."""
    for field, value in ast.iter_fields(stmt):
        if field in _BLOCK_FIELDS:
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, ast.AST):
                yield item


# RM-1560 (a): expressions whose body runs later than it is written. An
# eager comprehension (list / set / dict) runs where it stands and is not here.
_DEFERRED = (ast.Lambda, ast.GeneratorExp)


def _is_log_callable(expr, tainted=frozenset()) -> bool:
    """`expr` evaluates to a logging function (RM-1562): a log function
    reference (`log.info`, `print`), a name bound to one (`_LOGFN`), or a
    `partial` over one, nested partials included. RM-1563: a conditional
    either arm of which is one, and a level method off a logger object
    (`lg.info` after `lg = logging.getLogger()`). RM-1563: an attribute a
    class body bound to a logging function (`_LOGATTR`: `self.p` after
    `class C: p = log.info`), and a `staticmethod` over one, the class-body
    spelling that keeps a plain function from binding `self`."""
    if isinstance(expr, ast.Name) and _LOGFN + expr.id in tainted:
        return True
    if (isinstance(expr, ast.Attribute) and _LOGATTR + expr.attr in tainted
            and not _builtin_receiver(expr.value)):    # S144-Q-91
        return True
    if isinstance(expr, ast.IfExp):
        return (_is_log_callable(expr.body, tainted)
                or _is_log_callable(expr.orelse, tainted))
    if (isinstance(expr, ast.Call) and _call_name(expr) in ("partial", "staticmethod")
            and expr.args):
        return _is_log_callable(expr.args[0], tainted)
    return _is_log_call(ast.Call(func=expr, args=[], keywords=[]), tainted)


def _bind_log_alias(target, is_alias, tainted, is_obj=False) -> None:
    """RM-1562: a plain name bound to a logging function becomes a sink
    when it is called; RM-1563: one bound to a logger object (`is_obj`)
    makes a level call off it a sink. Both are judged BEFORE the binding
    clears the name (`p = p` keeps it). Add-only here; a plain `=` to
    anything else clears them through `_bind_names`. A tuple target is
    split into its names by `_alias_bindings`; an attribute target makes a
    class-attribute mark instead (`_retaint`, RM-1563), and an element
    target is not tracked (residual)."""
    if not isinstance(target, ast.Name):
        return
    if is_alias:
        tainted.add(_LOGFN + target.id)
    if is_obj:
        tainted.add(_LOGOBJ + target.id)


def _target_names(target):
    """The plain names a binding target may bind a logging function or logger
    object to: a bare name, or one inside a tuple / list target. A starred
    name always binds a LIST, and an element or attribute is not tracked."""
    if isinstance(target, ast.Name):
        return [target]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _target_names(elt)]
    return []


def _literal_elts(value):
    """The leaf elements of a literal tuple / list / set, nested literals and
    starred literals flattened: `(a, (b, *[c]))` gives a, b, c. A starred
    non-literal (`*xs`) contributes nothing. None if `value` is no literal."""
    if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        return None
    out = []
    for elt in value.elts:
        inner = elt.value if isinstance(elt, ast.Starred) else elt
        nested = _literal_elts(inner)
        if nested is not None:
            out.extend(nested)
        elif not isinstance(elt, ast.Starred):
            out.append(elt)
    return out


def _alias_bindings(target, value, tainted):
    """RM-1563 tuple aliases: (name, is_alias, is_obj) for every plain name
    `target` binds from `value`, judged with `tainted` as it stands.

    A bare name is judged by the whole value. A tuple / list target is paired
    BY POSITION with a tuple / list value of the same length and no starred
    element on either side (`p, q = log.info, fetch` makes only `p` an
    alias). Any other split of a literal value - a starred side or a length
    mismatch - marks EVERY name in the target if ANY leaf of the value is a
    logging function or logger object: the safe side. A non-literal value
    (`p, q = pair()`) is not tracked (residual)."""
    if isinstance(target, ast.Name):
        return [(target, _is_log_callable(value, tainted),
                 _is_logger_expr(value, tainted))]
    if (isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
            and not any(isinstance(e, ast.Starred)
                        for e in target.elts + value.elts)):
        return [b for t, v in zip(target.elts, value.elts)
                for b in _alias_bindings(t, v, tainted)]
    leaves = _literal_elts(value)
    if not leaves:
        return []
    is_alias = any(_is_log_callable(e, tainted) for e in leaves)
    is_obj = any(_is_logger_expr(e, tainted) for e in leaves)
    return [(n, is_alias, is_obj) for n in _target_names(target)]


def _iter_alias_bindings(target, iterable, tainted):
    """RM-1563: what a `for` target binds from each item of a literal
    tuple / list / set iterable (`for p in (log.info,)`), unioned over the
    items: the loop may stop at any of them. A non-literal iterable is not
    tracked (residual)."""
    if not isinstance(iterable, (ast.Tuple, ast.List, ast.Set)):
        return []
    items = []
    for elt in iterable.elts:
        if isinstance(elt, ast.Starred):
            items.extend(_literal_elts(elt.value) or [])
        else:
            items.append(elt)
    return [b for item in items for b in _alias_bindings(target, item, tainted)]


def _wrapper_bindings(target, value, tainted, late=frozenset(),
                      judge=_value_wrapper_specs):
    """RM-1563: (name, `_SINKFN` specs) for every plain name `target`
    binds from `value`, split as `_alias_bindings` splits a logging alias:
    a bare name takes the whole value's specs (`_value_wrapper_specs`), a
    tuple / list target is paired BY POSITION with a literal value of the
    same length and no starred element (`h, k = g, fetch` makes only `h` a
    wrapper), and any other split of a literal value gives EVERY name the
    union of its leaves' specs: the safe side. A non-literal value
    (`h, k = pair()`) is not tracked (residual). S144-Q-96: `judge` reads
    the specs (`_value_mut_specs` for a mutating helper's pairs)."""
    if isinstance(target, ast.Name):
        return [(target.id, judge(value, tainted, late))]
    if (isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
            and not any(isinstance(e, ast.Starred)
                        for e in target.elts + value.elts)):
        return [b for t, v in zip(target.elts, value.elts)
                for b in _wrapper_bindings(t, v, tainted, late, judge)]
    leaves = _literal_elts(value)
    if not leaves:
        return []
    specs = set().union(*(judge(e, tainted, late) for e in leaves))
    return [(n.id, specs) for n in _target_names(target)]


def _iter_wrapper_bindings(target, iterable, tainted, late=frozenset(),
                           judge=_value_wrapper_specs):
    """RM-1563: what a `for` or comprehension target binds as a wrapper
    from each item of a literal iterable (`for h in (g,)`), unioned over the
    items as `_iter_alias_bindings` does. Non-literal: not tracked."""
    if not isinstance(iterable, (ast.Tuple, ast.List, ast.Set)):
        return []
    items = []
    for elt in iterable.elts:
        if isinstance(elt, ast.Starred):
            items.extend(_literal_elts(elt.value) or [])
        else:
            items.append(elt)
    return [b for item in items
            for b in _wrapper_bindings(target, item, tainted, late, judge)]


def _log_args(call, tainted=frozenset()):
    """The message arguments of a logging sink, or None if `call` is not one.

    RM-1561 (d): `functools.partial(log.info, m)` evaluates `m` where the
    partial is BUILT, so the partial is the sink and is judged there (a
    later re-binding of `m` changes nothing the partial holds).
    RM-1562: a call THROUGH a logging function - an alias `p(m)`, a
    partial called later `p = partial(log.info, '%s'); p(m)` or in place
    `partial(log.info, '%s')(m)` - is a sink for its own arguments too.
    RM-1563: so is a call through a local wrapper (`_wrapper_args`)."""
    if _is_log_callable(call.func, tainted):
        return list(call.args) + [kw.value for kw in call.keywords]
    if (_call_name(call) == "partial" and call.args
            and _is_log_callable(call.args[0], tainted)):
        return list(call.args[1:]) + [kw.value for kw in call.keywords]
    return _wrapper_args(call, tainted)


def _default_bindings(fn, state, late=frozenset()):
    """RM-1562: the parameters of def `fn` that a default makes carry the
    value (or a logging function, as `_LOGFN` marks). A default is evaluated
    where the def stands, so it is judged with the def-time state; a lambda
    inside one reads `late`, as everywhere. Keeps the RM-1561 (c) caveat:
    a tainted default keeps its parameter tainted however it is called.
    RM-1787 (a): a default that is itself a wrapper (a lambda, a name
    bound to one, either arm of a conditional: `_value_wrapper_specs`)
    makes the parameter one, as `_SINKFN` entries; the same caveat holds."""
    a = fn.args
    pos = a.posonlyargs + a.args
    pairs = list(zip(pos[len(pos) - len(a.defaults):], a.defaults))
    pairs += [(k, d) for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
    bound = set()
    for arg, default in pairs:
        if _is_tainted(default, state, late):
            bound.add(arg.arg)
        if _is_log_callable(default, state):
            bound.add(_LOGFN + arg.arg)
        if _is_logger_expr(default, state):
            bound.add(_LOGOBJ + arg.arg)
        bound.update(f"{_SINKFN}{arg.arg} {spec}" for spec in _value_wrapper_specs(default, state, late))
        # S144-Q-96: and a mutating helper's pairs (`def f(r, k=h)`).
        bound.update(f"{_MUTFN}{arg.arg} {pair}" for pair in _value_mut_specs(default, state, late))
    return bound


# RM-1563 wrappers: a name bound to a local def or lambda whose parameter
# reaches a raise or logging sink is held as `_SINKFN + name + " " + spec`,
# one entry per sink parameter: `pos:<i>` (positional index), `kw:<name>`
# (keyword), `star:<n>` (a `*args` parameter, every positional index from n
# on) and `dstar` (a `**kwargs` parameter, every keyword). Like `_LOGFN` the
# entries carry no value; a call through the name is a sink for the
# arguments those parameters bind (`_wrapper_args`).
_SINKFN = "sinkfn:"


def _def_locals(fn):
    """RM-1563: the names def `fn` binds as its own locals - a plain-name
    store, a for / with / walrus / except / import / match target, or a
    nested def or class name, at the def's own level - minus every name
    declared `global` or `nonlocal` at that level, or `global` anywhere
    inside it.
    Nested defs, classes, lambdas and comprehensions are not entered, and a
    name declared `global` in a nested scope is never counted local: both
    keep a binding flowing out, the safe side. RM-1791: a nested
    `nonlocal` is not subtracted, since it can only name a function's
    binding, so a def that binds the name still holds it.
    Kept per scan, like `_scope_names`.
    RM-1788: a parameter is local too, unless the def may MUTATE the object
    it names (`_mutated_names`): that taint reaches the caller's object, which
    the scan follows by spelling (`self.q.append(url)` taints `self` for the
    next method). A re-binding (`m = url`, `p = log.info`) stays inside.
    RM-1790: a parameter passed to the mutated parameter of a helper is
    mutated as well; that depends on the state, so the def arm takes it off
    this set (`_call_mutated_names`)."""
    hit = _LOCALS_CACHE.get(id(fn))
    if hit is not None and hit[0] is fn:
        return hit[1]
    found = set()
    declared = set()
    todo = list(fn.body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
            continue
        if isinstance(node, _OWN_SCOPES):
            continue
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            declared.update(node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            found.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            found.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            found.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            found.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            found.add(node.rest)
        todo.extend(ast.iter_child_nodes(node))
    # RM-1791: a `global` in a nested scope keeps the name flowing out (the
    # scan follows names by spelling, so the def's own `m` and a nested
    # global `m` are one entry); a nested `nonlocal` does not, as it names a
    # binding of the def itself or of a def between, never the module's.
    declared |= {name for node in ast.walk(fn)
                 if isinstance(node, ast.Global) for name in node.names}
    params = {name for name, _ in _param_specs(fn)}
    names = frozenset((found | params) - declared - (params & _mutated_names(fn)))
    _LOCALS_CACHE[id(fn)] = (fn, names)
    return names


def _mutated_names(fn):
    """RM-1788: every name the scan may taint inside `fn` (nested scopes
    included) WITHOUT re-binding it: any name in an attribute or element
    store target (`m.x = v`, `q[m] = v`, the index included, as
    `_bind_names` taints it), in the receiver of a `_MUTATORS` call
    (`q[m].append(v)`), or the plain-name target of an augmented assignment,
    which changes a list or set in place (`m += [v]`, `m |= {v}`).
    RM-1794: also every name in what `setattr` or a dunder store puts a
    value into (`_mutated_exprs`), and every name an alias of one of these
    may reach (`_alias_closure`: `a = m; a.append(v)` mutates `m`)."""
    found = set()
    edges = {}
    for node in ast.walk(fn):
        _add_alias_edges(node, edges)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
            continue
        if (isinstance(node, (ast.Attribute, ast.Subscript))
                and isinstance(node.ctx, ast.Store)):
            targets = [node]
        elif isinstance(node, ast.Call):
            targets = _mutated_exprs(node)
        else:
            continue
        for target in targets:
            found.update(sub.id for sub in ast.walk(target) if isinstance(sub, ast.Name))
    return _alias_closure(found, edges)


def _add_alias_edges(node, edges) -> None:
    """RM-1794: the alias edges (`_alias_pairs`) a plain assignment
    `node` makes into `edges` (name -> the names a value put into its
    object reaches), as `_new_alias_marks` makes them. S144-Q-102: a
    walrus makes them too, wherever it stands (flow-insensitive, as the
    edges are: the safe side for flow-out)."""
    if isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    elif (isinstance(node, ast.AnnAssign) and node.value is not None) or isinstance(node, ast.NamedExpr):
        targets, value = [node.target], node.value
    else:
        return
    for target in targets:
        for name, roots in _alias_pairs(target, value):
            for root, whole in roots:
                if root == name:
                    continue
                edges.setdefault(name, set()).add(root)
                if whole:
                    edges.setdefault(root, set()).add(name)


def _alias_closure(found, edges):
    """RM-1794: `found` plus every name `edges` reach from it,
    transitively. In `_mutated_names` / `_mutated_containers` the edges are
    flow-insensitive (a later re-binding does not cut one): the safe side
    for flow-out."""
    seen, todo = set(found), list(found)
    while todo:
        for peer in edges.get(todo.pop(), ()):
            if peer not in seen:
                seen.add(peer)
                todo.append(peer)
    return seen


def _chain_root(expr):
    """The name an attribute / element chain hangs off (`a` for `a.b[c].d`),
    or None if it hangs off anything else (a call, a literal).
    S144-Q-114: a walrus hands back the object it binds, so a chain off one
    hangs off its target (`t` for `(t := a).q`), which its `_ALIAS` marks
    tie to what it was bound from: `(t := a).append(url)` fills `a`'s
    object. Before, it hung off nothing, so the fill reached no alias."""
    while isinstance(expr, (ast.Attribute, ast.Subscript, ast.Starred)):
        expr = expr.value
    if isinstance(expr, ast.NamedExpr):
        expr = expr.target
    return expr.id if isinstance(expr, ast.Name) else None


def _mutated_containers(fn):
    """RM-1790: the names of the OBJECTS `fn` (nested scopes included) may
    change in place: the root of an attribute or element store target
    (`m.x = v`, `q[k] = v`: `m`, `q`, never the index `k`), of a
    `_MUTATORS` call's receiver (`q[k].append(v)`: `q`) and the plain-name
    target of an augmented assignment. The narrow half of `_mutated_names`,
    which also keeps every name in the target (the safe side for flow-out).
    RM-1794: the root of what `setattr` or a dunder store puts a value
    into (`_mutated_exprs`) too, and every alias of a root
    (`_alias_closure`: `def h(q, v): a = q; a.append(v)` mutates `q`)."""
    found = set()
    edges = {}
    for node in ast.walk(fn):
        _add_alias_edges(node, edges)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
            continue
        if (isinstance(node, (ast.Attribute, ast.Subscript))
                and isinstance(node.ctx, ast.Store)):
            targets = [node]
        elif isinstance(node, ast.Call):
            targets = _mutated_exprs(node)
        else:
            continue
        for target in targets:
            root = _chain_root(target)
            if root is not None:
                found.add(root)
    return _alias_closure(found, edges)


_LOCALS_CACHE = {}
# The class attribute marks are about an ATTRIBUTE, which a local of the same
# spelling does not hold, so they always flow out of a def.
_ATTR_MARKS = (_LOGATTR, _LOGOBJATTR, _SINKATTR, _MUTATTR)


def _drop_locals(state, names):
    """`state` without the entries about a name in `names` (`_def_locals`).
    RM-1794: an `_ALIAS` mark is about both its names."""
    return {entry for entry in _shadow_aliases(state, names)
            if entry.startswith(_ATTR_MARKS) or _entry_name(entry) not in names}


def _drop_wrapper(name, tainted) -> None:
    """A re-binding of `name` replaces whatever wrapper (RM-1790: or
    mutating helper) it named."""
    prefixes = (_SINKFN + name + " ", _MUTFN + name + " ")
    for entry in [e for e in tainted if e.startswith(prefixes)]:
        tainted.discard(entry)


def _has_mut_marks(view) -> bool:
    return any(e.startswith((_MUTFN, _MUTATTR)) for e in view)


def _mut_pairs(call, view):
    """RM-1790: the (dst spec, src spec) pairs of the mutating helper
    `call` goes through (`_MUTFN` off a name, `_MUTATTR` off an attribute,
    each attribute pair read for how the call binds the first parameter,
    as `_attr_specs` reads a `_SINKATTR` spec). A classmethod's first
    parameter is the receiver's class: as a SOURCE it carries none of the
    receiver's value (`_attr_specs`), but as a DESTINATION a store into it
    is read back off the receiver (`self.q` finds a class attribute), so
    there it is bound from the receiver: the safe side."""
    f = call.func
    pairs = set()
    if isinstance(f, ast.Name):
        prefix = _MUTFN + f.id + " "
        for entry in view:
            if entry.startswith(prefix):
                dst, src = entry[len(prefix):].split(">", 1)
                pairs.add((dst, src))
    elif isinstance(f, ast.Lambda):
        # S144-Q-96: a lambda called in place is judged where it stands,
        # as `_wrapper_args` judges a wrapper.
        for pair in _mut_specs(f, view):
            dst, src = pair.split(">", 1)
            pairs.add((dst, src))
    elif isinstance(f, ast.Attribute):
        prefix = _MUTATTR + f.attr + " "
        for entry in view:
            if not entry.startswith(prefix):
                continue
            kind, pair = entry[len(prefix):].split(" ", 1)
            dst, src = pair.split(">", 1)
            for way in _attr_ways(kind, f.value):
                if way == "cls":
                    dsts, srcs = _bound_specs(dst), _bound_specs(src) - {_RECV}
                elif way == "bound":
                    dsts, srcs = _bound_specs(dst), _bound_specs(src)
                else:
                    dsts, srcs = {dst}, {src}
                pairs |= {(d, s) for d in dsts for s in srcs}
    return pairs


def _call_mutated_names(fn, view):
    """RM-1790: the root name (`_chain_root`) of every argument (or
    receiver) that a call inside `fn` (nested scopes included, as
    `_mutated_names`) passes to the MUTATED parameter of a helper `view`
    knows (`_mut_pairs`). The value
    passed for the source is not judged: this is what the call MAY mutate,
    the safe side of `_def_locals`."""
    if not _has_mut_marks(view):
        return set()
    found = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        for dst, _ in _mut_pairs(node, view):
            for arg in _spec_args(node, {dst}):
                root = _chain_root(arg)
                if root is not None:
                    found.add(root)
    return found


def _bind_mut_calls(call, seen, tainted, late=frozenset(), recv=None) -> None:
    """RM-1790: a call through a mutating helper whose source argument is
    tainted leaves its destination argument's names carrying the value, as
    `q.append(url)` leaves `q` (`_bind_mutators`): `h(q, url)` with
    `def h(q, v): q.append(v)` taints `q`, and `self.h(url)` with
    `def h(self, v): self.q.append(v)` taints `self`. Add-only; each call
    is judged with the view `_call_views` gives it. S144-Q-108: one call,
    in `_bind_in_order`'s order. S144-Q-110: a destination's aliases are
    read where it was (`_operand_view`), before the later arguments:
    `h(a, (a := n) or url)` fills what `a` named before the walrus."""
    for dst, src in _mut_pairs(call, seen):
        # RM-1793: an always pair needs no tainted argument.
        if src == _MUT_ALWAYS or any(
                _is_tainted(a, seen, late) for a in _spec_args(call, {src})):
            for arg in _spec_args(call, {dst}):
                _bind_names(arg, True, tainted, clear=False)
                # RM-1794: and every alias of its object.
                _taint_aliases(arg, tainted,
                               _operand_view(call, arg, recv, seen))


def _param_specs(fn):
    """(parameter name, its `_SINKFN` specs) for every parameter of `fn`."""
    a = fn.args
    pos = a.posonlyargs + a.args
    out = [(p.arg, {f"pos:{i}"} | ({f"kw:{p.arg}"} if p in a.args else set()))
           for i, p in enumerate(pos)]
    out += [(p.arg, {f"kw:{p.arg}"}) for p in a.kwonlyargs]
    if a.vararg is not None:
        out.append((a.vararg.arg, {f"star:{len(pos)}"}))
    if a.kwarg is not None:
        out.append((a.kwarg.arg, {"dstar"}))
    return out


def _sink_specs(fn, state, late=frozenset()):
    """RM-1563: the `_SINKFN` specs of the parameters of def or lambda `fn`
    that reach a raise or logging sink in its body.

    The body is walked as its own scope, from what the scope around it may
    hold when the body runs (`state | late`, the parameters' own names
    removed: a parameter shadows them), once as it is and once more with
    the parameters carrying the value. A parameter is a sink parameter if
    tainting it adds a sink site, or changes what a site carries; each one
    is then judged alone so `def g(m, n): log.info(n)` marks only `n`. The
    walks report into throwaway sets, never into the real report.

    RM-1563: a parameter whose default is a logging function or logger
    object (`def g(m, p=log.info): p(m)`) is one inside the body, as the
    def's own walk has it (RM-1562), so its `_LOGFN` / `_LOGOBJ` mark is
    put back after the shadowing; RM-1787 (a): so is the `_SINKFN` mark
    of a default that is itself a wrapper (`def g(m, p=h): p(m)`). The
    default is judged from `state`; a def is judged from the state after it, a superset of the def-time
    state (the safe side). A tainted-VALUE default is not added: the def's
    own walk (RM-1562) already reports the sites it reaches. A caller that
    passes its own `p` is still read as logging through it (the safe
    side)."""
    params = _param_specs(fn)
    if not params:
        return set()
    names = {n for n, _ in params}
    body = _fn_body(fn)
    base = _param_base(fn, names, state, late)
    # The answer depends only on `fn` and `base`, and a nested def is judged
    # again on every pass of every walk around it, so it is memoised for one
    # `_message_leak_sites` call (the tree, so every `id`, outlives it).
    key = (id(fn), base)
    if key not in _SPEC_CACHE:
        _SPEC_CACHE[key] = frozenset(_judge_params(body, params, names, base))
    return _SPEC_CACHE[key]


_SPEC_CACHE = {}


def _param_base(fn, names, state, late):
    """The entry `_sink_specs` and `_mut_specs` walk def `fn`'s body from:
    what the scope around it may hold (`state | late`) less the entries
    about its parameters `names`, which shadow them, plus what the
    parameters' defaults bind (see `_sink_specs`)."""
    marks = (_OBJ, _LOGFN, _LOGOBJ)

    def shadowed(entry):
        return (entry in names or any(entry == m + n for m in marks for n in names)
                or any(entry.startswith((_SINKFN + n + " ", _MUTFN + n + " "))
                       for n in names))

    # RM-1656: only the entries the body can read decide the answer (see
    # `_walk_scope`), so the key is projected onto them.
    base = _readable(set(state) | set(late), _scope_names(_fn_body(fn)))
    # RM-1794: an `_ALIAS` mark about a parameter or a local is shadowed
    # too, as the def arm's walk has it.
    own = names if isinstance(fn, ast.Lambda) else names | _def_locals(fn)
    base = frozenset(e for e in _shadow_aliases(base, own) if not shadowed(e))
    return base | {e for e in _default_bindings(fn, state, late)
                   if e.startswith((_LOGFN, _LOGOBJ, _SINKFN, _MUTFN))}


def _mut_specs(fn, state, late=frozenset()):
    """RM-1790: the `_MUTFN` pairs (`dst>src`) of def `fn`: a parameter
    `dst` the def may mutate in place (`_mutated_names`, or passed on to a
    helper's mutated parameter: `_call_mutated_names`) that leaves the body
    carrying the value when parameter `src` does. Only a CONTAINER counts
    as mutated (`_mutated_containers`): the index of a store
    (`cache[url] = body`) is read, not changed, so it is never a `dst`.
    Judged as `_sink_specs` judges a sink parameter: from the same entry,
    one walk per parameter (memoised, so the walks `_sink_specs` already
    made are reused), into a throwaway report. What `dst` carries is read
    from every state the body may leave it in (fall-through, `return` and
    every state inside, as the def arm's flow-out is). S144-Q-96: a
    lambda is judged the same way, and a helper is bound as a wrapper is
    (`_value_mut_specs`: an alias `k = h`, a conditional, a tuple, a
    walrus, a `for` or comprehension target over a literal, a default, a
    staticmethod over one, a store on an attribute by `=` or by `setattr`
    with a literal name: `_attr_store_marks`). Residuals: a `setattr`
    with a non-literal name makes no mark, and a re-bound helper keeps
    its old pairs through the late view, the rule a wrapper follows (the
    safe side); a parameter mutated
    and then re-bound (`q.append('x'); q = [v]`) is read as still carrying
    `v`, the RM-1788 safe side.

    RM-1793: a parameter that leaves the body carrying the value with NO
    parameter tainted (it stores an enclosing tainted name: `q.append(G)`,
    or hands the parameter to such a helper) makes the always pair
    `dst>*` (`_MUT_ALWAYS`), so a def with one parameter is judged too.
    Residual: a judge walk drops only the always pairs it starts from, so
    a NESTED def that stores an enclosing tainted name, called on the
    wrapper's own parameter inside the wrapper, still pre-taints that
    parameter for the judge (the wrapper's own log site stays flagged; the
    caller line that hands the wrapper a url is missed)."""
    params = _param_specs(fn)
    if not params:
        return set()
    names = {n for n, _ in params}
    base = _param_base(fn, names, state, late)
    dsts = names & (_mutated_containers(fn) | _call_mutated_names(fn, base))
    if not dsts:
        return set()
    key = ("mut", id(fn), base)
    if key not in _SPEC_CACHE:
        _SPEC_CACHE[key] = frozenset(_judge_mut_params(_fn_body(fn), params, dsts, base))
    return _SPEC_CACHE[key]


def _is_always(entry) -> bool:
    """RM-1793: `entry` is a mutating-helper always pair (`dst>*`)."""
    return (entry.startswith((_MUTFN, _MUTATTR))
            and entry.endswith(">" + _MUT_ALWAYS))


def _without_always(base):
    """RM-1793: `base` less its always pairs, the entry a judge walks
    from: a pair that needs no tainted argument would pre-taint a
    parameter the body hands to the helper, so the parameter would add
    nothing over the baseline and lose its spec."""
    return frozenset(e for e in base if not _is_always(e))


def _judge_mut_params(body, params, dsts, base):
    """The uncached body of `_mut_specs`."""
    judged = _without_always(base)

    def carried(start, extra):
        out, returns, inside, _ = _walk_scope(body, start | extra, lambda e, f: None)
        flowed = _join(out, *returns, *inside) or set()
        return {d for d in dsts if d in flowed or _OBJ + d in flowed}

    specs = dict(params)
    # RM-1793: what the body leaves carrying the value with no parameter
    # tainted, read from the FULL entry, so a helper's own always pair
    # passes on (`def w(q): h(q)`).
    pairs = {f"{d}>{_MUT_ALWAYS}" for dst in carried(base, set()) for d in specs[dst]}
    if len(params) < 2:
        return pairs
    for src, src_specs in params:
        for dst in carried(judged, {src}) - {src}:
            pairs |= {f"{d}>{s}" for d in specs[dst] for s in src_specs}
    return pairs


def _bind_mut(name, pairs, tainted) -> None:
    for pair in pairs:
        tainted.add(f"{_MUTFN}{name} {pair}")


def _fn_body(fn):
    """The statements of def or lambda `fn`. A lambda's one expression is
    wrapped once per scan and kept in `_BODY_CACHE`, so its list `id` - a
    `_WALK_CACHE` key - is never reused by another list while the scan runs."""
    if not isinstance(fn, ast.Lambda):
        return fn.body
    hit = _BODY_CACHE.get(id(fn))
    if hit is None or hit[0] is not fn:
        hit = _BODY_CACHE[id(fn)] = (fn, [ast.Expr(value=fn.body)])
    return hit[1]


_BODY_CACHE = {}


def _judge_params(body, params, names, base):
    """The uncached body of `_sink_specs`."""
    base = _without_always(base)    # RM-1793

    def sites(extra):
        got = set()
        _walk_scope(body, base | extra,
                    lambda expr, found: got.add((id(expr), frozenset(found))))
        return got

    baseline = sites(set())
    if sites(names) <= baseline:
        return set()
    return {s for n, specs in params if not sites({n}) <= baseline for s in specs}


def _bind_wrapper(name, specs, tainted) -> None:
    for spec in specs:
        tainted.add(f"{_SINKFN}{name} {spec}")


def _wrapper_args(call, tainted=frozenset()):
    """RM-1563: the arguments a call through a wrapper (`_SINKFN`) binds
    to its sink parameters, or None if `call` is not through one. A lambda
    called in place is judged where it stands; RM-1786: a call off an
    attribute reads the method marks (`_attr_specs`). After a starred positional
    argument every later position is unknown, so every one counts, and a
    starred argument or a `**` mapping counts whole: the safe side."""
    f = call.func
    if isinstance(f, ast.Name):
        prefix = _SINKFN + f.id + " "
        specs = {e[len(prefix):] for e in tainted if e.startswith(prefix)}
    elif isinstance(f, ast.Lambda):
        specs = _sink_specs(f, tainted)
    elif isinstance(f, ast.Attribute):
        specs = _attr_specs(f, tainted)
    else:
        return None
    if not specs:
        return None
    return _spec_args(call, specs)


def _spec_args(call, specs):
    """The arguments of `call` bound to a parameter spec in `specs` (the
    `_SINKFN` grammar, `_RECV` included). Shared by `_wrapper_args` and
    the RM-1790 mutating-helper reads (`_bind_mut_calls`)."""
    f = call.func
    stars = [int(s[5:]) for s in specs if s.startswith("star:")]
    out, shifted = [], False
    for i, arg in enumerate(call.args):
        if isinstance(arg, ast.Starred):
            shifted = True
            out.append(arg.value)
        elif shifted or f"pos:{i}" in specs or any(i >= n for n in stars):
            out.append(arg)
    for kw in call.keywords:
        if kw.arg is None or "dstar" in specs or f"kw:{kw.arg}" in specs:
            out.append(kw.value)
    if _RECV in specs and isinstance(f, ast.Attribute):
        out.append(f.value)
    return out


def _bound_specs(spec):
    """RM-1786: `spec` as seen by a call that binds the first parameter
    itself (`self` / `cls`): every position moves down one and keywords are
    unchanged. RM-1563: the first position is bound from the receiver, so
    it becomes `recv` (`_wrapper_args` reads the receiver for it), and so
    does a `*args` parameter that starts at the first position (the
    receiver is its first item)."""
    if spec.startswith("pos:"):
        i = int(spec[4:])
        return {f"pos:{i - 1}"} if i > 0 else {_RECV}
    if spec.startswith("star:"):
        n = int(spec[5:])
        return {f"star:{max(n - 1, 0)}"} | ({_RECV} if n == 0 else set())
    return {spec}


# RM-1563: the spec of a sink parameter bound from the receiver of a call
# off an attribute (`o.g()` with `def g(self): log.info(self)`).
_RECV = "recv"


def _attr_specs(f, tainted):
    """RM-1786: the `_SINKFN`-style specs a call off attribute `f` binds
    to sink parameters of a method wrapper (`_SINKATTR`), each read for how
    that call binds the first parameter. A plain method (`inst:<class>`) is
    bound off `self`, `super()` or a new instance of its own class (`C()`),
    unbound off its own class name, and read BOTH ways off any other
    receiver, which may be a class (`cls`, `type(self)`, a subclass `D`, a
    dotted path `O.I`) or an instance: the safe side. RM-1563: an `any`
    mark (a plain function stored on a non-`self` attribute from outside a
    class body) is read both ways off every receiver.
    RM-1563: a def re-wrapped by name (`g = staticmethod(g)`) and an
    alias (`h = g`) keep the wrapper. On a bound call the first parameter
    is the receiver (`_RECV`: `o = C(url); o.g()` with `def g(self):
    log.info(self)`), except for a classmethod, whose first parameter is
    the receiver's class, which carries no value of the receiver's.
    Residual: a `super()` receiver is read as itself, not as the enclosing
    method's first parameter, so `super().g()` with a tainted `self` is
    missed."""
    prefix = _SINKATTR + f.attr + " "
    specs = set()
    for entry in tainted:
        if not entry.startswith(prefix):
            continue
        kind, spec = entry[len(prefix):].split(" ", 1)
        for way in _attr_ways(kind, f.value):
            if way == "cls":
                specs |= _bound_specs(spec) - {_RECV}
            elif way == "bound":
                specs |= _bound_specs(spec)
            else:
                specs.add(spec)
    return specs


def _attr_ways(kind, recv):
    """How a call off receiver `recv` binds the first parameter of a method
    mark of kind `kind` (`_attr_specs`): `plain` (unbound), `bound` (off
    the receiver) or `cls` (off the receiver's class), one or more of them.
    S144-Q-91: none off a literal display (`_builtin_receiver`)."""
    owner = kind[len("inst:"):]
    if _builtin_receiver(recv):
        return ()    # S144-Q-91: the builtin's own method, never the mark's
    if kind == "static":
        return ("plain",)
    if kind == "any":
        return ("plain", "bound")
    if kind == "cls":
        return ("cls",)
    if (isinstance(recv, ast.Name) and recv.id == "self") or (
            isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name)
            and recv.func.id in ("super", owner)):
        return ("bound",)
    if isinstance(recv, ast.Name) and recv.id == owner:
        return ("plain",)
    return ("plain", "bound")


_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _comp_bind(gen, view, late):
    """RM-1563: a copy of `view` with comprehension generator `gen`'s
    target bound from its iterable, as `_Flow._for` binds a `for` target:
    add-only (an outer tainted name the target shadows stays tainted, the
    safe side), the value judged before the binding, plus the logging
    aliases a literal iterable gives (`for p in (log.info,)`)."""
    found = _is_tainted(gen.iter, view, late)
    aliases = _iter_alias_bindings(gen.target, gen.iter, view)
    wrappers = _iter_wrapper_bindings(gen.target, gen.iter, view, late)
    muts = _iter_wrapper_bindings(gen.target, gen.iter, view, late,
                                  _value_mut_specs)    # S144-Q-96
    inner = set(view)
    # RM-1794: the target is the comprehension's own name.
    _drop_target_aliases(gen.target, inner)
    _bind_names(gen.target, found, inner, clear=False)
    for name, is_alias, is_obj in aliases:
        _bind_log_alias(name, is_alias, inner, is_obj)
    for name, specs in wrappers:
        _bind_wrapper(name, specs, inner)
    for name, pairs in muts:
        _bind_mut(name, pairs, inner)
    return inner


def _late_view(view, late):
    """`view | late`, the state a deferred body (a lambda, a generator)
    reads. RM-1794: less the late view's `_ALIAS` marks, which still
    hold the marks a re-binding ended (`a = m; a = []`)."""
    return set(view) | {e for e in late if not e.startswith(_ALIAS)}


def _call_views(node, view, late, out, kinds=ast.Call, post=False) -> None:
    """Append (call, state the call reads) for every call in `node` (every
    node of type `kinds`: `_bind_in_order` asks for `ast.NamedExpr` too).
    S144-Q-108: `post=True` appends a node after its parts, in
    `_eval_children` order, so the list is in evaluation order; the
    default is pre-order (a sink check does not depend on the order).

    RM-1563: a comprehension's parts read its targets. Each generator's
    iterable reads the view before its own target is bound (the first one
    the enclosing view), then its target, conditions and every later part
    read the view with that target bound (`_comp_bind`). The bindings are
    local to the comprehension: a copy, never the enclosing view, so they
    reach no sibling and do not flow out. A generator expression's parts
    all read the late view, as below.

    A call inside a lambda or generator (`_DEFERRED`) reads the late view
    (`view | late`): it runs after the statement, maybe after a re-binding.
    RM-1563: a call in a lambda BODY also reads the lambda's parameters a
    default makes carry the value, or a logging function or logger object
    (`lambda m=url: log.info(m)`, `lambda p=log.info: p(url)`), as a nested
    def's body does (RM-1562). The defaults are evaluated where the lambda
    stands, so they are judged with `view`; the parameters are local, so they
    reach only that body and the lambdas nested in it, never a sibling or the
    enclosing scope. The calls inside a default keep the late view."""
    if isinstance(node, _COMPREHENSIONS):
        inner = _late_view(view, late) if isinstance(node, _DEFERRED) else view
        for gen in node.generators:
            _call_views(gen.iter, inner, late, out, kinds, post)
            inner = _comp_bind(gen, inner, late)
            _call_views(gen.target, inner, late, out, kinds, post)
            for cond in gen.ifs:
                _call_views(cond, inner, late, out, kinds, post)
        parts = ((node.key, node.value) if isinstance(node, ast.DictComp)
                 else (node.elt,))
        for part in parts:
            _call_views(part, inner, late, out, kinds, post)
        return
    if isinstance(node, ast.Lambda):
        late_view = _late_view(view, late)
        a = node.args
        for d in a.defaults + [d for d in a.kw_defaults if d is not None]:
            _call_views(d, late_view, late, out, kinds, post)
        body_view = late_view | _default_bindings(node, view, late)
        # RM-1794: a parameter is the lambda's own name, so the
        # enclosing scope's `_ALIAS` marks about it do not hold inside.
        for name, _ in _param_specs(node):
            _drop_aliases(name, body_view)
        _call_views(node.body, body_view, late, out, kinds, post)
        return
    if isinstance(node, kinds) and not post:
        out.append((node, view))
    for child in _eval_children(node) if post else ast.iter_child_nodes(node):
        _call_views(child, view, late, out, kinds, post)
        if post and isinstance(node, ast.Call):
            out.append((_PreCall(node, child), view))    # S144-Q-110
    if isinstance(node, kinds) and post:
        out.append((node, view))


class _PreCall:
    """S144-Q-110: the point in `_call_views`'s `post=True` order where
    `part` of call `call` (its callee, an argument or a keyword) has been
    read and the parts after it not yet (`_bind_in_order` keeps the
    `_ALIAS` marks there)."""

    __slots__ = ("call", "part")

    def __init__(self, call, part):
        self.call = call
        self.part = part


def _operand_view(call, expr, recv, seen):
    """S144-Q-110: the view the aliases of `expr`, an object `call` fills,
    are read from: the `_ALIAS` marks `recv` kept just after the part of
    `call` holding it was read (the callee for a receiver, else the
    argument or keyword), or `seen` where none was kept (a copied view)."""
    part = None
    if isinstance(call.func, ast.Attribute) and expr is call.func.value:
        part = call.func
    for arg in call.args:
        if expr is arg or (isinstance(arg, ast.Starred) and expr is arg.value):
            part = arg
    for kw in call.keywords:
        if expr is kw.value:
            part = kw
    if recv is None or part is None:
        return seen
    return recv.get((id(call), id(part)), seen)


def _eval_children(node):
    """S144-Q-108: the child nodes of `node` in the order Python evaluates
    them. `ast.iter_child_nodes` already gives it for a call, a
    conditional (test first) and an operator; an assignment evaluates its
    value before its targets, a dict display each key just before its
    value (`**m` has no key), and a parameter list its positional defaults
    before its keyword-only ones (the annotations last: they may run lazily
    or never). A def's or class's decorators run before its defaults and
    bases (`_def_parts`). A call's receiver is read before its arguments
    but the call is applied after them, so `_call_views` marks the point
    after each part (`_PreCall`, S144-Q-110)."""
    if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
        return [node.value] + [c for c in ast.iter_child_nodes(node)
                               if c is not node.value]
    if isinstance(node, ast.Dict):
        return [c for k, v in zip(node.keys, node.values)
                for c in (k, v) if c is not None]
    if isinstance(node, ast.arguments):
        first = node.defaults + [d for d in node.kw_defaults if d is not None]
        return first + [c for c in ast.iter_child_nodes(node)
                        if not any(c is d for d in first)]
    return list(ast.iter_child_nodes(node))


def _def_parts(stmt):
    """S144-Q-108: the expression-level parts of a def or class statement
    (`_own_nodes`) in evaluation order: its decorators first, then its
    parameter list or bases and keywords."""
    decorators = list(stmt.decorator_list)
    return decorators + [n for n in _own_nodes(stmt)
                         if not any(n is d for d in decorators)]


def _check_sinks(nodes, stmt, tainted, report, late=frozenset()) -> None:
    """Flag a raise or logging call among `nodes` whose message is tainted.
    Each call is judged with the state `_call_views` gives it: a logging call
    inside a lambda or generator body reads the late view, plus a lambda's
    default-bound parameters."""
    exprs = []
    if isinstance(stmt, ast.Raise):
        exprs = [(e, tainted) for e in (stmt.exc, stmt.cause) if e is not None]
    for node in nodes:
        calls = []
        _call_views(node, tainted, late, calls)
        for call, seen in calls:
            args = _log_args(call, seen)
            if args is not None:
                exprs.extend((a, seen) for a in args)
    for expr, seen in exprs:
        scan = _TaintScan(seen, late)
        scan.visit(expr)
        if scan.found:
            report(expr, scan.found)


def _scope_names(body):
    """RM-1656: every string held anywhere in `body` - every name it reads,
    binds, defines, catches, captures or declares (`Name.id`, `arg.arg`, a
    def's `name`, an `except ... as` name, a match capture, `global` names)
    plus string literals. The literals only widen the set, the safe side.
    Kept per scan with `body` itself, so its `id` cannot be reused."""
    hit = _NAMES_CACHE.get(id(body))
    if hit is None or hit[0] is not body:
        names = set()
        for stmt in body:
            for node in ast.walk(stmt):
                for _, value in ast.iter_fields(node):
                    for item in value if isinstance(value, list) else [value]:
                        if isinstance(item, str):
                            names.add(item)
        hit = _NAMES_CACHE[id(body)] = (body, frozenset(names))
    return hit[1]


_NAMES_CACHE = {}


def _entry_name(entry):
    """The name a taint-state entry is about: `url`, `obj:r`, `logfn:p`,
    `logobj:lg` and `sinkfn:g pos:0` give url, r, p, lg and g; the class
    attribute marks (`logattr:p`, `sinkattr:g static pos:0`) give the
    attribute name, which a body reading `self.p` holds as an
    `Attribute.attr` string."""
    for mark in (_OBJ, _LOGFN, _LOGOBJ, _LOGATTR, _LOGOBJATTR):
        if entry.startswith(mark):
            return entry[len(mark):]
    for mark in (_SINKFN, _SINKATTR, _MUTFN, _MUTATTR, _ALIAS):
        if entry.startswith(mark):
            return entry[len(mark):].split(" ", 1)[0]
    return entry


def _readable(entries, names):
    """The entries a scope whose strings are `names` can read. An entry whose
    name is not an identifier is an unknown shape and is always kept.
    S144-Q-108: an `_ALIAS` chain from a name the scope reads runs on
    through names it does not (`b -> a -> k`, the scope reading only `b`),
    so every `_ALIAS` mark from a name reachable from one it reads is kept
    (`_alias_closure`): a value the scope puts into `b` still reaches `k`."""
    out = set()
    for entry in entries:
        name = _entry_name(entry)
        if name in names or not name.isidentifier():
            out.add(entry)
    edges = {}
    for src, dst in _alias_edges(entries):
        edges.setdefault(src, set()).add(dst)
    if edges:
        reach = _alias_closure({s for s in edges if s in names}, edges)
        out |= {e for e in entries
                if e.startswith(_ALIAS) and _entry_name(e) in reach}
    return frozenset(out)


def _walk_scope(body, entry, report, late=frozenset()):
    """`_walk_scope_uncached`, memoised for one `_message_leak_sites` call.

    RM-1656: an entry about a name `body` never mentions is never read,
    bound or cleared by the walk (every read and every binding goes through
    a name written in the body, its nested defs included), so it only rides
    along: it is in every state the walk hands back, and no sink site, test
    or fixed point depends on it. The walk is therefore run on the entries
    the body can read (`_readable`), keyed on them, and the rest of `entry`
    is put back into every state it returns. The sites it reported are
    recorded and replayed into `report` on every call. Without this, each
    enclosing pass re-walked a nested def with a state that differed only in
    names the def never reads, and the scan grew about 4x per level of def
    nesting (depth 9 took minutes)."""
    names = _scope_names(body)
    seen_entry = _readable(entry, names)
    seen_late = _readable(late, names)
    key = (id(body), seen_entry, seen_late)
    hit = _WALK_CACHE.get(key)
    if hit is None or hit[0] is not body:
        sites = []
        out, returns, inside, hands_back = _walk_scope_uncached(
            body, set(seen_entry),
            lambda expr, found: sites.append((expr, tuple(found))), seen_late)
        hit = _WALK_CACHE[key] = (
            body, None if out is None else frozenset(out),
            [frozenset(s) for s in returns], [frozenset(s) for s in inside],
            hands_back, sites)
    _, out, returns, inside, hands_back, sites = hit
    for expr, found in sites:
        report(expr, found)
    rest = set(entry) - seen_entry
    return (None if out is None else set(out) | rest,
            [set(s) | rest for s in returns],
            [frozenset(s | rest) for s in inside], hands_back)


_WALK_CACHE = {}

# Nodes whose body is a scope of its own: a name stored inside one is not a
# class attribute. A def or class still has decorators, defaults and bases
# evaluated in the class body (`_own_nodes`).
_OWN_SCOPES = (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _class_level_names(body):
    """RM-1563: every plain name class body `body` binds in the class
    namespace - assignment, `for`, `with` and walrus targets at the class's
    own level, in its branches, loops and handlers included - but not a name
    bound inside a method, a nested class, a lambda or a comprehension.
    Kept per scan with `body` itself, as `_scope_names` is."""
    hit = _CLASS_NAMES_CACHE.get(id(body))
    if hit is None or hit[0] is not body:
        names, stack = set(), list(body)
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                stack.extend(_own_nodes(node))
                continue
            if isinstance(node, _OWN_SCOPES):
                continue
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            stack.extend(ast.iter_child_nodes(node))
        hit = _CLASS_NAMES_CACHE[id(body)] = (body, frozenset(names))
    return hit[1]


_CLASS_NAMES_CACHE = {}


def _method_kind(fn):
    """RM-1786: how def `fn` in a class body binds its first parameter,
    read off its decorators: `static`, `cls` or `inst`."""
    for dec in fn.decorator_list:
        node = dec.func if isinstance(dec, ast.Call) else dec
        name = (node.id if isinstance(node, ast.Name)
                else node.attr if isinstance(node, ast.Attribute) else "")
        if name == "staticmethod":
            return "static"
        if name == "classmethod":
            return "cls"
    return "inst"


def _class_method_kinds(body):
    """RM-1786: {name: kinds} for every def, and every plain name bound to
    a lambda (or a staticmethod / classmethod over one), at class body
    `body`'s own level - its branches, loops and handlers included, never
    inside a method, nested class, lambda or comprehension. A name bound
    more than once keeps every kind: the safe side. Kept per scan.

    RM-1563: a name bound to another name (`h = g`) takes that name's
    kinds, to a fixed point over alias chains; a name the body binds to no
    def, lambda or method wrapper of its own (a module function) is a plain
    function, so `inst`. A re-wrap by name (`g = staticmethod(g)`) adds its
    kind to the def's own: both are read, the safe side. A tuple target, a
    `for` target over a literal iterable and a walrus bind as `h = g` does
    (`_kind_bindings`: `h, j = g, fetch`, `for h in (g,)`). Residual: kinds
    ignore statement order, so an alias written BEFORE a same-name def
    (`h = g` naming a module `g`, then `@staticmethod def g`) takes only
    the later def's kind."""
    hit = _CLASS_KINDS_CACHE.get(id(body))
    if hit is None or hit[0] is not body:
        kinds, aliases, stack = {}, [], list(body)
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kinds.setdefault(node.name, set()).add(_method_kind(node))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                stack.extend(_own_nodes(node))
                continue
            if isinstance(node, _OWN_SCOPES):
                continue
            pairs = []
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                pairs = [b for t in targets for b in _kind_bindings(t, node.value)]
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                pairs = _iter_kind_bindings(node.target, node.iter)
            elif isinstance(node, ast.NamedExpr):
                pairs = _kind_bindings(node.target, node.value)
            for name, own, sources in pairs:
                if own:
                    kinds.setdefault(name, set()).update(own)
                aliases.extend((name, s) for s in sources)
            stack.extend(ast.iter_child_nodes(node))
        alias_targets = {t for t, _ in aliases}
        changed = True
        while changed:
            changed = False
            for target, source in aliases:
                got = (kinds.get(source, set())
                       if source in kinds or source in alias_targets else {"inst"})
                have = kinds.setdefault(target, set())
                if not got <= have:
                    have.update(got)
                    changed = True
        # An alias left with no kind reads only other aliases (`g = g`, or a
        # cycle) and so names what the enclosing scope held: a plain function.
        for target in alias_targets:
            if not kinds.get(target):
                kinds[target] = {"inst"}
        hit = _CLASS_KINDS_CACHE[id(body)] = (
            body, {n: frozenset(k) for n, k in kinds.items() if k})
    return hit[1]


_CLASS_KINDS_CACHE = {}


def _kind_bindings(target, value):
    """RM-1563: (name, kinds, alias source names) for every plain name a
    class body's `target` binds from `value` (`_value_kinds`), split as
    `_wrapper_bindings` splits a wrapper: a bare name takes the whole value,
    a tuple / list target is paired BY POSITION with a literal value of the
    same length and no starred element, and any other split of a literal
    value gives every name the union of its leaves: the safe side."""
    if isinstance(target, ast.Name):
        own, sources = _value_kinds(value)
        return [(target.id, own, sources)]
    if (isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
            and not any(isinstance(e, ast.Starred)
                        for e in target.elts + value.elts)):
        return [b for t, v in zip(target.elts, value.elts)
                for b in _kind_bindings(t, v)]
    leaves = _literal_elts(value)
    if not leaves:
        return []
    own, sources = set(), set()
    for leaf in leaves:
        k, s = _value_kinds(leaf)
        own |= k
        sources |= s
    return [(n.id, own, sources) for n in _target_names(target)]


def _iter_kind_bindings(target, iterable):
    """RM-1563: `_kind_bindings` for a class-level `for` target over each
    item of a literal iterable (`for h in (g,)`), unioned over the items."""
    if not isinstance(iterable, (ast.Tuple, ast.List, ast.Set)):
        return []
    items = []
    for elt in iterable.elts:
        if isinstance(elt, ast.Starred):
            items.extend(_literal_elts(elt.value) or [])
        else:
            items.append(elt)
    return [b for item in items for b in _kind_bindings(target, item)]


def _class_attr_marks(body, out, cls_name=""):
    """RM-1563: the `_LOGATTR` / `_LOGOBJATTR` marks of class body `body`
    whose fall-through state is `out`. A method runs only once the class
    exists, so only what the body leaves BOUND counts (`p = log.info` then
    `p = fetch` makes no mark), and only for names the body itself binds: a
    logging alias in a method or in the enclosing scope is not an attribute.
    RM-1786: likewise a wrapper (`_SINKFN`) the body leaves bound to a
    def or lambda of its own makes a `_SINKATTR` mark per kind and spec; a
    wrapper defined inside a method, or in the enclosing scope, does not."""
    if not out:
        return set()
    marks = set()
    for name in _class_level_names(body):
        if _LOGFN + name in out:
            marks.add(_LOGATTR + name)
        if _LOGOBJ + name in out:
            marks.add(_LOGOBJATTR + name)
    kinds = _class_method_kinds(body)
    # RM-1790: a mutating helper (`_MUTFN`) left bound is a `_MUTATTR`
    # method mark, kind for kind as a wrapper is.
    for entry in out:
        for fn_mark, attr_mark in ((_SINKFN, _SINKATTR), (_MUTFN, _MUTATTR)):
            if not entry.startswith(fn_mark):
                continue
            name, spec = entry[len(fn_mark):].split(" ", 1)
            for kind in kinds.get(name, ()):
                if kind in ("inst", "cls") and _is_always(entry) and (
                        spec.split(">", 1)[0] in _receiver_specs(body, name)):
                    continue
                tag = f"inst:{cls_name}" if kind == "inst" else kind
                marks.add(f"{attr_mark}{name} {tag} {spec}")
    return marks


def _receiver_specs(body, name):
    """RM-1793: the specs (`pos:0`, `kw:<first parameter>`) of the first
    parameter of every def named `name` at class body `body`'s own level.
    An always pair whose destination is a plain method's or classmethod's
    receiver makes no `_MUTATTR` mark: a store into `self` / `cls` is
    already read by the class's other methods (its attributes are tainted
    for them), and the mark, keyed by attribute name only, would taint the
    receiver and the first argument of every same-named call off any
    other receiver (`subprocess.run([...])` for a `def run(self)` that
    stores a tainted module name into `self`). Residual: an instance
    logged OUTSIDE the class after such a call (`o.h(); log.info(o)`) is
    missed, as on HEAD."""
    specs, stack = {"pos:0"}, list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                first = (node.args.posonlyargs + node.args.args)[:1]
                specs |= {f"kw:{p.arg}" for p in first}
            continue
        if isinstance(node, ast.ClassDef):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return specs


def _walk_scope_uncached(body, entry, report, late=frozenset()):
    """RM-1560 (a): walk one scope's body to a fixed point of its may-taint
    set `ever` - every name tainted in ANY state anywhere in the scope, plus
    the enclosing scopes' `late`. `ever` is the late view a nested def,
    lambda or generator in this scope reads with, since it may run after any
    of the scope's bindings (`m = 'x'; def g(): log.info(m)` then `m = url`).
    Returns (fall-through state, `return` states, every state seen inside,
    whether a reachable `return` / `yield` value may carry the url)."""
    ever = set(entry) | set(late)
    while True:
        flow = _Flow(report, ever)
        inside = []
        flow.watchers.append(inside)
        out = flow.block(body, entry)
        seen = _join(out, *flow.returns, *inside) or set()
        if seen <= ever:
            return out, flow.returns, inside, flow.hands_back
        ever |= seen


class _Flow:
    """Run the taint state through one scope's statements.

    RM-1443: branches are ALTERNATIVE paths, so each arm starts from a copy
    of the state before it and the arms are JOINED by union afterwards. The
    sequential walk this replaced visited sibling except handlers and if /
    else arms top to bottom, so a sanitized re-binding in a later arm cleared
    a raw binding made in an earlier one. The result is a may-taint state:
    a name is tainted after a branch if ANY path into the join taints it.

    RM-1557: abrupt exits are modelled. A state is None where no path
    reaches (after `break` / `continue` / `return`). `break` and `continue`
    hand their state to the innermost loop's exit and next pass, `return` to
    the enclosing function's flow-out, and every state seen ANYWHERE inside a
    try body (nested blocks included) reaches its handlers, as every state in
    the body, `else` and handlers reaches `finally`. `raise` is NOT treated as
    ending a path: a suppressing context manager can resume after it, and
    over-reporting is the safe side of a guard.

    RM-1560 (a): `ever` is this scope's late view (see `_walk_scope`)."""

    def __init__(self, report, ever=frozenset()):
        self.report = report
        self.ever = frozenset(ever)
        self.loops = []     # innermost last: {"breaks": [...], "conts": [...]}
        self.watchers = []  # per open try: every state seen inside it
        self.returns = []   # states at `return` in this function body
        # RM-1561 (d): a reachable `return` / `yield` value may carry the url.
        self.hands_back = False

    def block(self, stmts, state):
        """The state after `stmts`, or None if no path falls through them."""
        if state is None:
            return None
        state = set(state)
        for i, stmt in enumerate(stmts):
            self._watch(state)
            after = self.stmt(stmt, state)
            if after is None:
                # The rest of the block is unreachable, but every raise and
                # logging site is still scanned, with the last live state, by
                # a throwaway walk that feeds no loop, try or flow-out.
                _Flow(self.report, self.ever).block(stmts[i + 1:], state)
                return None
            state = after
            self._watch(state)
        return state

    def _watch(self, state):
        for seen in self.watchers:
            seen.append(frozenset(state))

    def _expr_step(self, nodes, stmt, state):
        """Check the sinks in `nodes` and apply their walrus bindings."""
        state = set(state)
        nodes = list(nodes)
        # The bindings are run to a fixed point: within one statement a
        # walrus may read a container a later mutator fills
        # (`g(q.append(url), m := q[0])`), or one mutator a container
        # another fills after it (RM-1558). S144-Q-107: a walrus also ENDS
        # its target's `_ALIAS` marks (`_drop_aliases`), so it ends them on
        # the first pass only; a re-pass that ended them again would rotate
        # them (`g((t := a), (a := b), (b := t))` flipped between two
        # states of one size and stopped on the wrong one), so the first
        # pass compares the set itself. S144-Q-109: a re-pass makes no
        # walrus `_ALIAS` marks either: it would read the marks of the
        # walruses after it, so a rotation made every name reach every
        # source. Every later pass only ADDS, so there an unchanged size
        # is an unchanged state. S144-Q-108: within a pass every binding
        # site runs in evaluation order (`_bind_in_order`), so a fill before
        # a walrus in source order (`g(b.append(url), (b := n), (n := a))`)
        # is read before the walrus ends its alias. S144-Q-110: a call's
        # receiver is read before its arguments and each argument before the
        # next, so the aliases of an object a call fills are the marks kept
        # where it was read on the first pass (`recv`), on every pass.
        # A first pass in which any walrus ran with `drop` on is always
        # re-passed (S144-Q-108 verifier round 2): a first pass may end an
        # alias and put it back, ending on the state it began with. Kept as
        # the safe side: since `recv` no known program needs it (the
        # S144-Q-110 verifier's `setattr` and helper cases no longer do).
        first = frozenset(state)
        drop = True
        recv = {}
        while True:
            before = len(state)
            ended = _bind_in_order(nodes, state, self.ever, drop=drop,
                                   recv=recv)
            if (state == first and not ended) if drop else len(state) == before:
                break
            drop = False
        _check_sinks(nodes, stmt, state, self.report, self.ever)
        for node in nodes:
            for sub in ast.walk(node):
                if (isinstance(sub, (ast.Yield, ast.YieldFrom, ast.Return))
                        and sub.value is not None
                        and _is_tainted(sub.value, state, self.ever)):
                    self.hands_back = True
        return state

    def stmt(self, stmt, state):
        """The state after one statement, or None if it never falls through."""
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Decorators, defaults and bases run here. The body is ALSO walked
            # with the enclosing state, as the walk this replaced did, and what
            # it binds flows OUT by union (the body may or may not have run by
            # the time a later statement does), less a def's own locals (see
            # RM-1563 below): a `global` or `self.x` set from
            # a URL in one method must still taint a sink in the next. Each
            # function is walked again as its own scope in `_message_leak_sites`.
            # RM-1559: any statement may raise out of the body, so every
            # state seen inside it flows out too, not only the fall-through
            # and `return` states: `G = url; g(); G = 'clean'` leaves `G`
            # tainted on the path where `g()` raises.
            # RM-1560 (a): a def body runs LATER, so its sinks are judged a
            # second time from the late view (`state | self.ever`). Only the
            # def-time walk feeds the flow-out: the late view is what the body
            # may READ, not what it binds. A class body runs where it stands,
            # so it gets no late walk; its methods still read `self.ever`
            # through the class scope's own late view.
            # RM-1561 (d): a def whose `return` / `yield` value may carry
            # the url binds its name as a tainted VALUE, as `g = lambda: url`
            # does, so `raise E(g())` is a leak. Judged from both walks (the
            # late one sees what a later call reads). Add-only, like every
            # binding form but plain `=`: the body may still hold the old
            # value of the name.
            # RM-1562: a parameter whose default carries the value is
            # tainted inside the body. Judged by extra walks, so the def-time
            # flow-out stays the walk without them: a parameter is local, and
            # its default must not taint the enclosing scope's name.
            # RM-1563: a class body that leaves a logging alias bound makes
            # it a class attribute. Its methods were walked inside the body,
            # before the attribute existed, so the body is walked again with
            # the marks in its entry (the marks only ever add, so this ends);
            # they then flow out with the rest of the class state.
            # RM-1789: the decorators, defaults, bases and keywords are
            # ordinary expressions run in THIS scope, so their walrus and
            # mutator bindings apply here too, before the body is walked
            # (`def h(x=q.append(url))`, `@(m := url) and deco`), as every
            # other statement's do (`_expr_step`). Annotations and type
            # parameter bounds may run lazily (Python 3.14) or never; they
            # are read as run here, the safe side. The sinks were
            # checked here before, the bindings were not. S144-Q-108: the
            # decorators first, as they run (`_def_parts`).
            state = self._expr_step(_def_parts(stmt), stmt, state)
            # RM-1794: a def's parameters and locals are not the
            # enclosing scope's names, so the `_ALIAS` marks about them do
            # not reach into its body (`a = m; def f(a): a.append(url)`
            # leaves `m` alone).
            enter, late_in = state, self.ever
            if not isinstance(stmt, ast.ClassDef):
                own = _def_locals(stmt) | {n for n, _ in _param_specs(stmt)}
                enter = _shadow_aliases(state, own)
                late_in = _shadow_aliases(self.ever, own)
            out, returns, inside, hands_back = _walk_scope(
                stmt.body, enter, self.report, late_in)
            marks = set()
            while isinstance(stmt, ast.ClassDef):
                more = _class_attr_marks(stmt.body, out, stmt.name) - state - marks
                if not more:
                    break
                marks |= more
                out, returns, inside, hands_back = _walk_scope(
                    stmt.body, state | marks, self.report, self.ever)
            if not isinstance(stmt, ast.ClassDef):
                seeded = _default_bindings(stmt, state, self.ever) - state
                if seeded:
                    hands_back |= _walk_scope(stmt.body, enter | seeded,
                                              self.report, late_in)[3]
                if not late_in <= enter:
                    hands_back |= _walk_scope(stmt.body,
                                              enter | late_in | seeded,
                                              self.report, late_in)[3]
            flowed = _join(out, *returns, *inside) or set()
            if not isinstance(stmt, ast.ClassDef):
                # RM-1563: a name the def binds is its own local unless
                # declared `global` / `nonlocal`, so what the body bound to
                # it stays inside (`def g(): p = log.info` leaves the
                # enclosing `p` alone). Only the body's additions are
                # dropped: the enclosing state is kept whole by the union.
                # RM-1788: so is a parameter it never mutates.
                # RM-1790: a parameter passed to a helper's mutated
                # parameter is mutated (`self.h(url)` mutates `self`), as
                # the def-time state or the late view knows the helper.
                params = {n for n, _ in _param_specs(stmt)}
                kept = params & _call_mutated_names(stmt, state | self.ever)
                flowed = _drop_locals(flowed, _def_locals(stmt) - kept)
            state = state | flowed
            if hands_back and not isinstance(stmt, ast.ClassDef):
                state.add(stmt.name)
            # RM-1563: the def re-binds its name, so it names this wrapper
            # (or none) from here on; the body is judged from the def-time
            # state plus the late view, as a later call may run it.
            _drop_wrapper(stmt.name, state)
            _drop_aliases(stmt.name, state)    # RM-1794
            if not isinstance(stmt, ast.ClassDef):
                _bind_wrapper(stmt.name, _sink_specs(stmt, state, self.ever),
                              state)
                # RM-1790: and it names this mutating helper, judged the
                # same way.
                _bind_mut(stmt.name, _mut_specs(stmt, state, self.ever), state)
            return state
        if isinstance(stmt, ast.Return):
            # `return (m := url)` binds before leaving, and a `finally` or a
            # handler can still see that state.
            state = self._expr_step([stmt], stmt, state)
            self._watch(state)
            self.returns.append(set(state))
            return None
        if isinstance(stmt, (ast.Break, ast.Continue)):
            if not self.loops:
                return state    # not valid Python; fall through, never drop
            key = "breaks" if isinstance(stmt, ast.Break) else "conts"
            self.loops[-1][key].append(set(state))
            return None
        if isinstance(stmt, ast.If):
            state = self._expr_step(list(_own_nodes(stmt)), stmt, state)
            return _join(self.block(stmt.body, state),
                         self.block(stmt.orelse, state))
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            return self._for(stmt, state)
        if isinstance(stmt, ast.While):
            return self._while(stmt, state)
        if isinstance(stmt, _TRY_TYPES):
            return self._try(stmt, state)
        if isinstance(stmt, ast.Match):
            return self._match(stmt, state)
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            # Items enter left to right, each target bound before the next
            # item is evaluated.
            for item in stmt.items:
                state = self._expr_step([item], stmt, state)
                if item.optional_vars is not None:
                    _drop_target_aliases(item.optional_vars, state)    # RM-1794
                    _bind_names(item.optional_vars,
                                _with_target_found(item, state, self.ever),
                                state, clear=False)
                    if _is_tainted(item.context_expr, state, self.ever):
                        _bind_objects(item.optional_vars, state)
            # Any context manager may SUPPRESS an exception from its body
            # (`contextlib.suppress`), so every state seen inside the body can
            # resume after the `with` - even when the body ends in a return,
            # break or continue.
            inside = []
            self.watchers.append(inside)
            try:
                out = self.block(stmt.body, state)
            finally:
                self.watchers.pop()
            return _join(out, *inside)
        state = self._expr_step([stmt], stmt, state)
        _retaint(stmt, state, self.ever)
        return state

    def _match(self, stmt, state):
        """RM-1559: capture patterns are bindings, and a case is tried with
        whatever the cases before it bound. A capture taken from a tainted
        subject carries the value (add-only; a capture off an object subject
        is over-reported as a value, the safe side). A case whose guard fails
        - or whose pattern fails part-way - falls through with its captures
        and guard walrus still bound, so they reach every later case and the
        no-match exit."""
        state = self._expr_step([stmt.subject], stmt, state)
        found = _is_tainted(stmt.subject, state, self.ever)
        exits = []
        tried = set(state)
        for case in stmt.cases:
            entry = set(tried)
            for name in _capture_names(case.pattern):
                _drop_aliases(name, entry)    # RM-1794
            if found:
                entry.update(_capture_names(case.pattern))
            if case.guard is not None:
                entry = self._expr_step([case.guard], stmt, entry)
            exits.append(self.block(case.body, entry))
            tried = entry
        exits.append(tried)  # no case matched
        return _join(*exits)

    def _loop(self, entry, run_pass):
        """Iterate a loop body to a fixed point: a binding made late in one
        pass reaches a sink early in the next. `run_pass(entry)` runs one
        pass and returns (state at the test, state after the body). Returns
        (converged test state, every state handed to a `break`)."""
        breaks = []
        while True:
            frame = {"breaks": [], "conts": []}
            self.loops.append(frame)
            try:
                tested, out = run_pass(entry)
            finally:
                self.loops.pop()
            breaks.extend(frame["breaks"])
            after = _join(entry, out, *frame["conts"])
            if after == entry:
                return tested, breaks
            entry = after

    def _for(self, stmt, state):
        # The iterable is evaluated once, before the first pass.
        state = self._expr_step([stmt.iter], stmt, state)
        found = _is_tainted(stmt.iter, state, self.ever)
        aliases = _iter_alias_bindings(stmt.target, stmt.iter, state)
        wrappers = _iter_wrapper_bindings(stmt.target, stmt.iter, state, self.ever)
        muts = _iter_wrapper_bindings(stmt.target, stmt.iter, state, self.ever,
                                      _value_mut_specs)    # S144-Q-96

        def run_pass(entry):
            # The target is assigned once per item, so a sink in it
            # (`for d[log.info(m)] in xs`) sees what the last pass bound.
            body_in = self._expr_step([stmt.target], stmt, entry)
            _drop_target_aliases(stmt.target, body_in)    # RM-1794
            _bind_names(stmt.target, found, body_in, clear=False)
            # RM-1563: add-only, like the value binding above; RM-1563:
            # so is a wrapper (`for h in (g,)`).
            for name, is_alias, is_obj in aliases:
                _bind_log_alias(name, is_alias, body_in, is_obj)
            for name, specs in wrappers:
                _bind_wrapper(name, specs, body_in)
            for name, pairs in muts:
                _bind_mut(name, pairs, body_in)
            return entry, self.block(stmt.body, body_in)

        exhausted, breaks = self._loop(state, run_pass)
        # `else` runs when the loop ends without `break`; a `break` skips it.
        return _join(self.block(stmt.orelse, exhausted), *breaks)

    def _while(self, stmt, state):
        def run_pass(entry):
            # The test is re-evaluated before every pass, so at the fixed point
            # it sees what the body bound.
            tested = self._expr_step([stmt.test], stmt, entry)
            return tested, self.block(stmt.body, tested)

        # The converged test state is also the state the loop exhausts with.
        exhausted, breaks = self._loop(state, run_pass)
        return _join(self.block(stmt.orelse, exhausted), *breaks)

    def _try(self, stmt, state):
        """try / except / else / finally with each handler as its own path."""
        in_body, in_any = [], []
        marks = [(len(f["breaks"]), len(f["conts"])) for f in self.loops]
        ret_mark = len(self.returns)
        self.watchers.append(in_any)
        self.watchers.append(in_body)
        try:
            body_out = self.block(stmt.body, state)
        finally:
            # Popped by position: the two lists hold equal states here, so a
            # `remove` by value would take the wrong one.
            self.watchers.pop()
        try:
            # A handler can be entered from ANY state inside the body, nested
            # blocks included, not only between its top-level statements.
            handler_entry = _join(state, *in_body)
            if body_out is None and stmt.orelse:
                # An `else` after a body that never falls through is dead,
                # but its sites are still scanned (see `block`).
                _Flow(self.report, self.ever).block(stmt.orelse, handler_entry)
            exits = [self.block(stmt.orelse, body_out)]
            # RM-1789: a handler's type is an expression run when the
            # handlers are tried, in order, so its walrus and mutator
            # bindings (`except q.append(url) or E:`) reach its own body and
            # every later handler (`tried`), as a `match` case's guard does.
            # Each handler body's entry is watched, so `finally` and the exit
            # see them too, with no extra join.
            tried = set(handler_entry)
            for handler in stmt.handlers:
                if handler.type is not None:
                    tried = self._expr_step([handler.type], handler, tried)
                entry = set(tried)
                if handler.name:
                    # A third-party exception can quote the URL it was handed
                    # back at us, so it is untrusted text until it goes through
                    # a sanitizer.
                    entry.add(handler.name)
                    _drop_aliases(handler.name, entry)    # RM-1794
                exits.append(self.block(handler.body, entry))
        finally:
            self.watchers.pop()
        joined = _join(*exits)
        if not stmt.finalbody:
            return None if joined is None else joined | handler_entry
        # `finally` runs on every path, the raising and the abrupt ones too.
        fin_out = self.block(stmt.finalbody, _join(joined, handler_entry, *in_any))
        if fin_out is not None:
            # A break / continue / return taken inside the try reaches its
            # target only after `finally` ran, so whatever `finally` bound
            # travels with it.
            for frame, (b0, c0) in zip(self.loops, marks):
                frame["breaks"][b0:] = [s | fin_out for s in frame["breaks"][b0:]]
                frame["conts"][c0:] = [s | fin_out for s in frame["conts"][c0:]]
            self.returns[ret_mark:] = [s | fin_out for s in self.returns[ret_mark:]]
        return None if joined is None else fin_out


def _message_leak_sites(path):
    """Every raise / logging site in `path` whose message could carry the raw
    endpoint, one taint scope per function plus the module scope."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    scopes = [tree] + [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    leaks = set()

    def report(expr, found):
        leaks.add(f"{Path(path).name}:{expr.lineno}: {sorted(set(found))}")

    caches = (_SPEC_CACHE, _BODY_CACHE, _NAMES_CACHE, _WALK_CACHE,
              _CLASS_NAMES_CACHE, _CLASS_KINDS_CACHE, _LOCALS_CACHE)
    for cache in caches:
        cache.clear()
    _SHADOWED_FRESH.clear()
    _SHADOWED_FRESH.update(_module_bound_names(tree) & _FRESH_CTORS)
    try:
        for scope in scopes:
            _walk_scope(scope.body, set(), report)
    finally:
        for cache in caches:
            cache.clear()
        _SHADOWED_FRESH.clear()
    return sorted(leaks)


_CHECKER_SAMPLES = (
    ("direct f-string", "def f(url):\n    raise E(f'{url} boom')\n", True),
    ("indirect local", "def f(url):\n    m = 'at ' + url\n    raise E(m)\n", True),
    ("config key", "def f(cfg):\n    raise E(str(cfg['endpoint']))\n", True),
    ("builder call", "def f(c):\n    raise E(_build_url(c, 't', 'i', 'SR'))\n", True),
    ("identity digest", "def f(c):\n    raise E(_config_identity(c))\n", True),
    ("attribute reach", "def f(r):\n    raise E(f'{r.full_url}')\n", True),
    ("log site", "def f(endpoint):\n    log.warning('at %s', endpoint)\n", True),
    ("print site", "def f(url):\n    print(url)\n", True),
    ("raw exception",
     "def f():\n    try:\n        g()\n    except OSError as exc:\n"
     "        raise E(f'{exc}')\n", True),
    ("sanitized local",
     "def f(url):\n    safe = _safe_url(url)\n    raise E(f'{safe} boom')\n", False),
    ("sanitized inline", "def f(url):\n    raise E(f'{_safe_url(url)} boom')\n", False),
    ("redacted wrap",
     "def f(url):\n    try:\n        g()\n    except OSError as exc:\n"
     "        d = _redact(f'{exc}', url)\n    raise E(f'{_safe_url(url)}: {d}')\n",
     False),
    ("clean literal", "def f(url):\n    raise E('boom')\n", False),
    # RM-1443: sibling except handlers and if / else arms are ALTERNATIVE
    # paths, so a sanitized re-binding in a later arm must not clear a raw
    # binding made in an earlier one. The sequential walk this replaced read
    # the arms top to bottom and let the last one win.
    ("raw first handler, redacted second",
     "def f(url):\n    detail = ''\n    try:\n        g()\n"
     "    except KeyError as exc:\n        detail = f'{exc}'\n"
     "    except OSError as exc:\n        detail = _redact(f'{exc}', url)\n"
     "    raise E(f'{_safe_url(url)}: {detail}')\n", True),
    ("raw if arm, sanitized else arm",
     "def f(url, c):\n    if c:\n        m = 'at ' + url\n"
     "    else:\n        m = _safe_url(url)\n    raise E(m)\n", True),
    ("raw try body, sanitized handler",
     "def f(url):\n    try:\n        m = url\n    except OSError:\n"
     "        m = _safe_url(url)\n    raise E(m)\n", True),
    ("handler entered mid-body",
     "def f(url):\n    try:\n        m = url\n        m = g()\n"
     "    except OSError:\n        pass\n    raise E(m)\n", True),
    ("raw match case, sanitized later case",
     "def f(url, c):\n    match c:\n        case 1:\n            m = url\n"
     "        case _:\n            m = _safe_url(url)\n    raise E(m)\n", True),
    ("raw loop-carried binding",
     "def f(url, xs):\n    m = 'x'\n    for x in xs:\n        if x:\n"
     "            raise E(m)\n        m = url\n", True),
    ("augmented assignment keeps taint",
     "def f(url):\n    m = url\n    m += '!'\n    raise E(m)\n", True),
    ("global set in one function, logged in another",
     "_last = ''\ndef a(url):\n    global _last\n    _last = url\n"
     "def b():\n    log.info(_last)\n", True),
    ("attribute set in one method, logged in another",
     "class C:\n    def a(self, url):\n        self.last = url\n"
     "    def b(self):\n        log.info(self.last)\n", True),
    ("while test sees the body's binding",
     "def f(url):\n    m = 'x'\n    while log.info(m):\n        m = url\n", True),
    ("every handler redacted",
     "def f(url):\n    detail = ''\n    try:\n        g()\n"
     "    except KeyError as exc:\n        detail = _redact(f'{exc}', url)\n"
     "    except OSError as exc:\n        detail = _redact(f'{exc}', url)\n"
     "    raise E(f'{_safe_url(url)}: {detail}')\n", False),
    ("sanitized on both arms",
     "def f(url, c):\n    if c:\n        m = _safe_url(url)\n"
     "    else:\n        m = 'none'\n    raise E(m)\n", False),
    ("rebound clean after the branch",
     "def f(url, c):\n    if c:\n        m = url\n    m = 'clean'\n"
     "    raise E(m)\n", False),
    # RM-1557: abrupt exits and the binding forms the walk did not model.
    # Each of the next eight was misjudged by the RM-1443 walk.
    ("break carries a mid-body binding out of the loop",
     "def f(url, xs):\n    m = 'x'\n    for x in xs:\n        m = url\n"
     "        if x:\n            break\n        m = 'clean'\n    raise E(m)\n",
     True),
    ("continue carries a mid-body binding into the next pass",
     "def f(url, xs):\n    m = 'x'\n    for x in xs:\n        log.info(m)\n"
     "        m = url\n        if x:\n            continue\n        m = 'clean'\n",
     True),
    ("handler entered from a nested block of the try body",
     "def f(url, c):\n    m = 'x'\n    try:\n        if c:\n            m = url\n"
     "            g()\n            m = 'clean'\n    except OSError:\n"
     "        raise E(m)\n", True),
    ("for target bound from a tainted iterable",
     "def f(url):\n    for m in [url]:\n        raise E(m)\n", True),
    ("walrus binding in an if test",
     "def f(url):\n    if (m := 'at ' + url):\n        raise E(m)\n", True),
    ("walrus evaluated first in the same expression feeds its sink",
     "def f(url):\n    log.info(m) if (m := url) else None\n", True),
    ("nullcontext passes its tainted argument through",
     "def f(url):\n    with nullcontext(url) as m:\n        raise E(m)\n", True),
    ("return ends the arm that never reaches the sink",
     "def f(url, c):\n    m = url\n    if c:\n        m = 'clean'\n    else:\n"
     "        return\n    raise E(m)\n", False),
    # RM-1557 keep-greens: the RM-1443 walk already got these right, and
    # modelling abrupt exits must not lose them.
    ("break through a finally that binds the url",
     "def f(url, xs):\n    m = 'x'\n    for x in xs:\n        try:\n"
     "            break\n        finally:\n            m = url\n    raise E(m)\n",
     True),
    ("return in a handler still reaches finally",
     "def f(url):\n    m = 'x'\n    try:\n        g()\n    except OSError:\n"
     "        m = url\n        return\n    finally:\n        log.info(m)\n", True),
    ("attribute set before a return, logged in another method",
     "class C:\n    def a(self, url):\n        self.last = url\n        return\n"
     "    def b(self):\n        log.info(self.last)\n", True),
    ("break skips the loop else that would clear the binding",
     "def f(url, xs):\n    m = 'x'\n    for x in xs:\n        m = url\n"
     "        break\n    else:\n        m = 'clean'\n    raise E(m)\n", True),
    ("walrus in a log call is still a direct leak",
     "def f(url):\n    log.info(m := url)\n", True),
    # Found by the cycle 128 verifier against the first draft: a walrus that
    # may not run must not clear a name, a passthrough or attribute with-target
    # must not clear one either, and no sink may drop out of the scan.
    ("walrus after a short-circuit or may not run",
     "def f(url, c):\n    m = url\n    if c or (m := 'clean'):\n        pass\n"
     "    raise E(m)\n", True),
    ("walrus in one arm of a conditional expression",
     "def f(url, c):\n    m = url\n    x = (m := 'a') if c else 0\n    raise E(m)\n",
     True),
    ("walrus in a comprehension that may iterate zero times",
     "def f(url, xs):\n    m = url\n    [(m := 'x') for _ in xs]\n    raise E(m)\n",
     True),
    ("walrus in a while test after and",
     "def f(url, c):\n    m = url\n    while c and (m := 'x'):\n        c = 0\n"
     "    raise E(m)\n", True),
    ("closing passes its tainted argument through",
     "def f(url):\n    m = url\n    with closing(m) as m:\n        raise E(m)\n", True),
    ("closing binds a fresh name from its tainted argument",
     "def f(url):\n    with closing(url) as m:\n        raise E(m)\n", True),
    ("attribute with-target keeps its base name's taint",
     "class C:\n    def a(self, url):\n        self.last = url\n    def b(self):\n"
     "        with g() as self.conn:\n            pass\n        log.info(self.last)\n",
     True),
    ("sink inside a for target",
     "def f(url, xs, d):\n    for d[log.info(url)] in xs:\n        pass\n", True),
    ("sink in dead code after a return is still scanned",
     "def f(url):\n    return\n    raise E(url)\n", True),
    ("walrus in a return value reaches finally",
     "def f(url):\n    m = 'x'\n    try:\n        return (m := url)\n    finally:\n"
     "        log.info(m)\n", True),
    # Found by the cycle 128 second verifier round.
    ("walrus in an assert message may not run",
     "def f(url, c):\n    m = url\n    assert c, (m := 'clean')\n    raise E(m)\n",
     True),
    ("walrus past the first link of a chained comparison may not run",
     "def f(url, a, b):\n    m = url\n    if a < b < (m := 'clean'):\n        pass\n"
     "    raise E(m)\n", True),
    ("sink in a for target sees the previous pass",
     "def f(url, xs, d):\n    m = 'x'\n    for d[log.info(m)] in xs:\n        m = url\n",
     True),
    ("nullcontext passthrough given by keyword",
     "def f(url):\n    m = url\n    with nullcontext(enter_result=m) as m:\n"
     "        raise E(m)\n", True),
    ("keyword passthrough binds a fresh name",
     "def f(url):\n    with nullcontext(enter_result=url) as m:\n        raise E(m)\n",
     True),
    ("return inside a suppressing with does not end the path",
     "def f(url, c):\n    m = 'x'\n    if c:\n        with suppress(OSError):\n"
     "            m = url\n            return g()\n        raise E(m)\n", True),
    ("break inside a suppressing with does not end the path",
     "def f(url, xs):\n    m = 'x'\n    for x in xs:\n        with suppress(OSError):\n"
     "            m = url\n            g()\n            break\n        log.info(m)\n",
     True),
    ("binding inside a suppressing with before a return leaves the method",
     "class C:\n    def a(self, url):\n        with suppress(Exception):\n"
     "            self.last = url\n            return g()\n    def b(self):\n"
     "        log.info(self.last)\n", True),
    ("for iterable taint is judged before its walrus clears a name",
     "def f(url):\n    m = url\n    for n in [m, (m := 'y')]:\n        raise E(n)\n",
     True),
    ("with items bind left to right",
     "def f(url):\n    with nullcontext(url) as m, h(log.info(m)):\n        pass\n",
     True),
    # Found by the cycle 128 third verifier round.
    ("with-as over a tainted name keeps its taint",
     "def f(url):\n    m = 'cache_' + url\n    with open(m) as m:\n"
     "        log.info('%s', m)\n", True),
    ("with-as over an object keeps its taint",
     "def f(url):\n    m = open(url)\n    with m as m:\n        log.info('%s', m)\n",
     True),
    ("attribute for-target keeps its base name's taint",
     "class C:\n    def a(self, url):\n        self.last = url\n    def b(self, xs):\n"
     "        for self.cur in xs:\n            log.info(self.last)\n", True),
    # Found by the cycle 128 fourth verifier round (a differential fuzzer).
    ("name read before its own walrus in one value",
     "def f(url):\n    m = url\n    n = m + (m := 'y')\n    raise E(n)\n", True),
    ("name read before its own walrus in an augmented value",
     "def f(url):\n    m = url\n    n = ''\n    n += m + (m := 'y')\n    raise E(n)\n",
     True),
    ("name read before its own walrus in a passthrough",
     "def f(url):\n    m = url\n    with nullcontext([m, (m := 'x')]) as m:\n"
     "        log.info(m)\n", True),
    ("for over a container the model sees as clean keeps the name",
     "def f(url):\n    m = url\n    q = []\n    q.append(m)\n    for m in q:\n"
     "        raise E(m)\n", True),
    ("walrus over a container the model sees as clean keeps the name",
     "def f(url):\n    m = url\n    q = []\n    q.append(m)\n    if (m := q[0]):\n"
     "        raise E(m)\n", True),
    ("walrus in an assert test is skipped under -O",
     "def f(url):\n    m = url\n    assert (m := 'clean')\n    raise E(m)\n", True),
    ("dead try else is still scanned",
     "def f(url):\n    try:\n        return g()\n    except OSError:\n        pass\n"
     "    else:\n        raise E(url)\n", True),
    # RM-1558: the three RM-1557 known gaps, promoted. The RM-1443 walk
    # flagged them only by accident (through code after a `break` / `return`
    # it treated as reachable); the RM-1557 walk lost them.
    ("with-as object from a tainted call, behind a break",
     "def f(url, xs):\n    n = 'x'\n    for x in xs:\n        with Opn(url) as n:\n"
     "            log.info('%s', n)\n        n = url\n        break\n", True),
    ("with-as object from a tainted call, after a returning arm",
     "def f(url, c):\n    m = 'x'\n    if c:\n        m = url\n        return\n"
     "    with Opn(url) as m:\n        log.info('%s', m)\n", True),
    ("container filled by append, dead binding after a break",
     "def f(url):\n    q = []\n    q.append(url)\n    n = 'x'\n    for x in [1]:\n"
     "        break\n        n = url\n    n = n + q[0]\n    raise E(n)\n", True),
    # RM-1558 (a): a with-as target built from a tainted value is an OBJECT
    # that may quote it in its repr (a file object quotes its path). A bare
    # reference to it is a leak; reading an attribute off it is not.
    ("with-as object from a tainted call, bare reference",
     "def f(url):\n    with Opn(url) as r:\n        raise E(f'{r}')\n", True),
    ("with-as over a tainted object name binds a fresh name",
     "def f(url):\n    m = open(url)\n    with m as n:\n        log.info('%s', n)\n",
     True),
    ("with-as object passed on by plain assignment",
     "def f(url):\n    with Opn(url) as r:\n        s = r\n    raise E(f'{s}')\n", True),
    ("with-as object attribute set in one method, logged in another",
     "class C:\n    def a(self, url):\n        with Opn(url) as self.conn:\n"
     "            pass\n    def b(self):\n        log.info('%s', self)\n", True),
    ("with-as object url attribute is still a leak",
     "def f(url):\n    with Opn(url) as r:\n        raise E(r.geturl())\n", True),
    ("with-as object status read is clean",
     "def f(url):\n    with Opn(url) as r:\n        if r.status != 200:\n"
     "            raise E(f'{_safe_url(url)} -> HTTP {r.status}')\n", False),
    ("with-as object method result is clean",
     "def f(url):\n    with Opn(url) as r:\n        n = r.read(8)\n"
     "        log.info('%d bytes', len(n))\n", False),
    ("with-as object rebound clean",
     "def f(url):\n    with Opn(url) as r:\n        pass\n    r = 'done'\n"
     "    log.info('%s', r)\n", False),
    ("with-as target from a clean call stays clean",
     "def f(url):\n    with g() as r:\n        log.info('%s', r)\n", False),
    # RM-1558 (b): a container filled by a mutating method call carries
    # whatever was put in it.
    ("container filled by append, read back",
     "def f(url):\n    q = []\n    q.append(url)\n    raise E(q[0])\n", True),
    ("container filled by extend, joined",
     "def f(url):\n    q = []\n    q.extend([url])\n    log.info(', '.join(q))\n", True),
    ("container filled by insert",
     "def f(url):\n    q = []\n    q.insert(0, 'at ' + url)\n    raise E(str(q))\n",
     True),
    ("dict filled by update",
     "def f(url):\n    d = {}\n    d.update(src=url)\n    raise E(f'{d}')\n", True),
    ("dict filled by setdefault",
     "def f(url):\n    d = {}\n    d.setdefault('k', url)\n    raise E(d['k'])\n", True),
    ("set filled by add",
     "def f(url):\n    s = set()\n    s.add(url)\n    log.info('%s', s)\n", True),
    ("attribute container filled in one method, logged in another",
     "class C:\n    def a(self, url):\n        self.seen.append(url)\n"
     "    def b(self):\n        log.info('%s', self.seen)\n", True),
    ("mutator inside an expression still fills the container",
     "def f(url, c):\n    q = []\n    if c and q.append(url) is None:\n        pass\n"
     "    raise E(q[0])\n", True),
    ("container filled with clean values stays clean",
     "def f(url):\n    q = []\n    q.append(_safe_url(url))\n    q.extend(['x'])\n"
     "    raise E(', '.join(q))\n", False),
    # Found by the cycle 129 verifier.
    ("with-as object bound to an attribute, logged bare",
     "class C:\n    def a(self, url):\n        with Opn(url) as self.conn:\n"
     "            log.info('%s', self.conn)\n", True),
    ("with-as object in a tuple target, bare element",
     "def f(url):\n    with Opn(url) as (a, b):\n        raise E(f'{a}')\n", True),
    ("with-as object in a tuple target, element status read is clean",
     "def f(url):\n    with Opn(url) as (a, b):\n        log.info('%s', b.status)\n",
     False),
    ("walrus reads a container a later mutator in the statement fills",
     "def f(url):\n    q = []\n    g(q.append(url), m := q[0])\n    raise E(m)\n",
     True),
    ("mutator fills from a container a later mutator in the statement fills",
     "def f(url):\n    a, b = [], []\n    g(b.extend(a), a.append(url))\n"
     "    raise E(str(b))\n", True),
    ("container filled by a clean mutator call stays clean",
     "def f(url):\n    q = []\n    q.append(len(_safe_url(url)))\n    raise E(str(q))\n",
     False),
    # RM-1559 (a): `match` capture patterns are bindings. A capture taken
    # from a credential-bearing subject carries the value (add-only, like the
    # other non-`=` bindings).
    ("match as-capture of a tainted subject",
     "def f(url):\n    match url:\n        case str() as m:\n            raise E(m)\n",
     True),
    ("match star capture of a tainted subject",
     "def f(url):\n    match url.split('?'):\n        case [head, *rest]:\n"
     "            log.info('%s', rest)\n", True),
    ("match mapping value capture",
     "def f(url):\n    match {'u': url}:\n        case {'u': v}:\n            raise E(v)\n",
     True),
    ("match mapping rest capture",
     "def f(url):\n    match {'u': url}:\n        case {**kw}:\n"
     "            raise E(str(kw))\n", True),
    ("match class keyword capture",
     "def f(url):\n    match Box(url):\n        case Box(src=s):\n            raise E(s)\n",
     True),
    ("match capture does not clear a tainted name",
     "def f(url, c):\n    m = url\n    match c:\n        case m:\n            pass\n"
     "    raise E(m)\n", True),
    ("match capture of a clean subject stays clean",
     "def f(url, c):\n    match c:\n        case [a, *b]:\n            raise E(f'{a}{b}')\n",
     False),
    # RM-1559 (b): a case whose guard fails falls through to the next case
    # (and to the no-match exit) with its guard walrus and captures bound.
    ("match guard walrus reaches a later case",
     "def f(url, c):\n    match c:\n        case 1 if (m := url):\n            pass\n"
     "        case _:\n            raise E(m)\n", True),
    ("match capture under a failed guard reaches the no-match exit",
     "def f(url):\n    a = 'x'\n    match url.split('?'):\n"
     "        case [a, 'z'] if g():\n            return\n    raise E(a)\n", True),
    # RM-1559 (c): any statement may raise out of a def, so a global or
    # attribute bound from the value and cleared later in the same def still
    # leaves it behind on that path.
    ("global bound then cleared, a raise in between",
     "def a(url):\n    global G\n    G = url\n    g()\n    G = 'clean'\n\n"
     "def b():\n    log.info('%s', G)\n", True),
    # RM-1559 (d): storing into an element or an attribute does not replace
    # the container, so it never clears the container's name - nor the index
    # name, which is only READ.
    ("element store keeps the list tainted",
     "def f(url):\n    m = [url, 'y']\n    m[1] = 'x'\n    raise E(str(m))\n", True),
    ("attribute store keeps the object tainted",
     "def f(url):\n    m = Box(url)\n    m.a = 'x'\n    raise E(f'{m}')\n", True),
    ("index name read by a store is not cleared",
     "def f(url, d):\n    k = url\n    d[k] = 'x'\n    raise E(k)\n", True),
    ("attribute store in one method keeps self tainted for another",
     "class C:\n    def a(self, url):\n        self.u = url\n        self.n = 0\n"
     "    def b(self):\n        log.info('%s', self.u)\n", True),
    ("element store in a tuple target keeps the list tainted",
     "def f(url):\n    m = [url]\n    a, m[0] = 'x', 'y'\n    raise E(str(m))\n", True),
    ("plain name in a tuple target is still cleared",
     "def f(url):\n    m = url\n    m, n = 'x', 'y'\n    raise E(m)\n", False),
    ("starred name in a tuple target is still cleared",
     "def f(url):\n    m = url\n    *m, n = 'x', 'y'\n    raise E(str(m))\n", False),
    ("element store into a clean list stays clean",
     "def f(url):\n    m = []\n    m[0] = 'x'\n    raise E(str(m))\n", False),
    # RM-1560 (a): a nested def, a lambda or a generator expression runs
    # LATER than it is written, so a free name it reads may hold any value the
    # enclosing scope ever binds - not only the value at the def.
    ("closure reads a name bound after its def",
     "def f(url):\n    m = 'x'\n    def g():\n        log.info(m)\n    m = url\n"
     "    g()\n", True),
    ("module-level closure reads a name bound after its def",
     "m = 'x'\ndef g():\n    log.info(m)\nm = _build_url(c, 't', 'i', 'SR')\n", True),
    ("closure two defs deep reads a name bound after its def",
     "def f(url):\n    m = 'x'\n    def g():\n        def k():\n"
     "            log.info(m)\n        return k\n    m = url\n", True),
    ("method of a class in a function reads a name bound after it",
     "def f(url):\n    m = 'x'\n    class C:\n        def g(self):\n"
     "            log.info(m)\n    m = url\n", True),
    ("lambda body sink reads a name bound after the lambda",
     "def f(url):\n    m = 'x'\n    h = lambda: log.info(m)\n    m = url\n    h()\n",
     True),
    ("generator expression sink reads a name bound after it",
     "def f(url, xs):\n    m = 'x'\n    gen = (log.info(m) for _ in xs)\n    m = url\n"
     "    list(gen)\n", True),
    ("lambda returning a name bound after the lambda",
     "def f(url):\n    m = 'x'\n    h = lambda: m\n    m = url\n    raise E(h())\n",
     True),
    ("closure late read inside a loop body",
     "def f(url, xs):\n    m = 'x'\n    for x in xs:\n        def g():\n"
     "            log.info(m)\n    m = url\n", True),
    ("lambda in dead code after a return still reads late",
     "def f(url, c):\n    m = 'x'\n    if c:\n        return\n"
     "        h = lambda: log.info(m)\n    m = url\n", True),
    # RM-1560 (a) keep-greens: only what runs later gets the late view.
    ("closure over a name only ever bound clean",
     "def f(url):\n    m = 'x'\n    def g():\n        log.info(m)\n"
     "    m = _safe_url(url)\n", False),
    ("class body reads the name at its definition",
     "def f(url):\n    m = 'x'\n    class C:\n        log.info(m)\n    m = url\n",
     False),
    ("eager comprehension reads the name now",
     "def f(url, xs):\n    m = 'x'\n    [log.info(m) for _ in xs]\n    m = url\n",
     False),
    ("the late view does not flow out of a def",
     "def f(url):\n    m = 'x'\n    def g():\n        pass\n    log.info(m)\n"
     "    m = url\n", False),
    ("lambda over a name never tainted",
     "def f(url):\n    m = 'x'\n    h = lambda: log.info(m)\n    h()\n", False),
    # RM-1561 (d): what a nested def hands back is a value. A def whose
    # return or yield may carry the url taints its name, as `h = lambda: url`
    # already did, so a call to it in a message is a leak.
    ("nested def returns the value",
     "def f(url):\n    def g():\n        return url\n    raise E(g())\n", True),
    ("nested def returns a name bound after its def",
     "def f(url):\n    m = 'x'\n    def g():\n        return m\n    m = url\n"
     "    raise E(g())\n", True),
    ("nested def returns a local carrying the value",
     "def f(url):\n    def g():\n        m = url\n        return m\n"
     "    log.info('%s', g())\n", True),
    ("nested generator yields the value",
     "def f(url):\n    def g():\n        yield url\n    raise E(next(g()))\n", True),
    ("nested async def returns the value",
     "def f(url):\n    async def g():\n        return url\n    raise E(g())\n", True),
    ("module helper returning a built url, called in a later def",
     "def g(c):\n    return _build_url(c, 't', 'i', 'SR')\n\n"
     "def f(c):\n    log.info('%s', g(c))\n", True),
    ("module helper returning a built url, called in an earlier def",
     "def f(c):\n    log.info('%s', g(c))\n\n"
     "def g(c):\n    return _build_url(c, 't', 'i', 'SR')\n", True),
    # RM-1561 (d): functools.partial over a logging function takes its
    # arguments NOW, so it is a sink judged where it is built.
    ("partial over a log function with the value",
     "import functools\ndef f(url):\n    p = functools.partial(log.info, '%s', url)\n"
     "    p()\n", True),
    ("partial binds the value before the name is cleared",
     "def f(url):\n    m = url\n    p = partial(log.info, m)\n    m = 'x'\n    p()\n",
     True),
    ("partial over a log function with the value as a keyword",
     "def f(url):\n    p = partial(log.warning, '%s', extra=url)\n    p()\n", True),
    ("partial built in a lambda reads a name bound after it",
     "def f(url):\n    m = 'x'\n    h = lambda: partial(log.info, m)()\n    m = url\n"
     "    h()\n", True),
    # RM-1561 (d) keep-greens.
    ("nested def returns a sanitized value",
     "def f(url):\n    def g():\n        return _safe_url(url)\n    raise E(g())\n",
     False),
    ("nested def returns a constant",
     "def f(url):\n    def g():\n        return 'x'\n    raise E(g())\n", False),
    ("nested def returns its own clean parameter",
     "def f(url):\n    def g(m):\n        return m\n    raise E(g('x'))\n", False),
    ("partial over a log function with clean arguments",
     "def f(url):\n    p = partial(log.info, 'x')\n    p()\n", False),
    ("partial over a non-log function with the value",
     "def f(url):\n    p = partial(fetch, url)\n    p()\n", False),
    ("partial takes the value at build time, not at call time",
     "def f(url):\n    m = 'x'\n    p = partial(log.info, m)\n    m = url\n    p()\n",
     False),
    # RM-1562: a name bound to a logging function (an alias or a partial
    # over one) is a sink when it is CALLED, and a log call may be rooted at a
    # call (`logging.getLogger(n).info`). A parameter default is evaluated
    # where the def stands, so a tainted default taints its parameter.
    ("partial over a log function given the value at call time",
     "def f(url):\n    p = partial(log.info, '%s')\n    p(url)\n", True),
    ("partial over a log function called in place",
     "def f(url):\n    partial(log.info, '%s')(url)\n", True),
    ("alias of a log function called with the value",
     "def f(url):\n    p = log.info\n    p(url)\n", True),
    ("alias of a log function passed through a second name",
     "def f(url):\n    p = log.warning\n    q = p\n    q('%s', url)\n", True),
    ("alias of a log function bound by a walrus",
     "def f(url):\n    if (p := log.info):\n        p(url)\n", True),
    ("alias of print read by a nested def",
     "def f(url):\n    p = print\n    def g():\n        p(url)\n", True),
    ("alias read late by a lambda",
     "def f(url):\n    p = fetch\n    h = lambda: p(url)\n    p = log.info\n    h()\n",
     True),
    ("partial over a partial over a log function",
     "def f(url):\n    p = partial(partial(log.info), url)\n    p()\n", True),
    ("partial over a partial over a log function alias",
     "def f(url):\n    p = log.info\n    q = partial(partial(p), url)\n    q()\n", True),
    ("partial over a log method off getLogger",
     "import logging\ndef f(url):\n"
     "    p = partial(logging.getLogger('x').info, url)\n    p()\n", True),
    ("log call rooted at getLogger",
     "import logging\ndef f(url):\n"
     "    logging.getLogger(__name__).warning('%s', url)\n", True),
    ("default value handed back by a nested def",
     "def f(url):\n    def g(m=url):\n        return m\n    raise E(g())\n", True),
    ("keyword-only default logged in a nested def",
     "def f(url):\n    def g(*, m=url):\n        log.info(m)\n", True),
    ("positional-only default handed back by a nested def",
     "def f(url):\n    def g(a, m=url, /):\n        return m\n    raise E(g(1))\n",
     True),
    ("default value aliasing a log function",
     "def f(url):\n    def g(p=log.info):\n        p(url)\n", True),
    # RM-1562 keep-greens.
    ("alias re-bound to a non-log function before the call",
     "def f(url):\n    p = log.info\n    p = fetch\n    p(url)\n", False),
    ("alias of a log function called with a clean value",
     "def f(url):\n    p = log.info\n    p('x')\n", False),
    ("partial over a log function called with a sanitized value",
     "def f(url):\n    partial(log.info, '%s')(_safe_url(url))\n", False),
    ("attribute off a non-log name is not a log alias",
     "def f(url):\n    p = fetch.info\n    p(url)\n", False),
    ("log call rooted at getLogger with a clean message",
     "import logging\ndef f(url):\n    logging.getLogger('x').info('ok')\n", False),
    ("sanitized default handed back by a nested def",
     "def f(url):\n    def g(m=_safe_url(url)):\n        return m\n    raise E(g())\n",
     False),
    ("a tainted default does not flow out of the def",
     "def f(url):\n    m = 'x'\n    def g(m=url):\n        pass\n    log.info(m)\n",
     False),
    # RM-1563: a logger OBJECT bound to a name (or a parameter default), a
    # logger reached through an attribute or a call anywhere along the chain,
    # and a conditional alias are sinks too.
    ("logger object bound to a name",
     "import logging\ndef f(url):\n    lg = logging.getLogger('x')\n    lg.info(url)\n",
     True),
    ("logger object bound by a walrus",
     "import logging\ndef f(url):\n"
     "    if (lg := logging.getLogger()):\n        lg.warning('%s', url)\n", True),
    ("logger object passed through a second name",
     "import logging\ndef f(url):\n    lg = logging.getLogger()\n    q = lg\n"
     "    q.error(url)\n", True),
    ("alias of the logger module",
     "def f(url):\n    p = log\n    p.info(url)\n", True),
    ("alias of sys reaching stderr",
     "import sys\ndef f(url):\n    out = sys\n    out.stderr.write(url)\n", True),
    ("attribute logger off self",
     "def f(self, url):\n    self.log.info(url)\n", True),
    ("private attribute logger off self",
     "def f(self, url):\n    self._logger.warning('%s', url)\n", True),
    ("private attribute log off self",
     "def f(self, url):\n    self._log.error(url)\n", True),
    ("logger handed back by a get_logger call",
     "def f(url):\n    get_logger().info(url)\n", True),
    ("conditional alias of two log functions",
     "def f(url, x):\n    p = log.info if x else log.warning\n    p(url)\n", True),
    ("conditional logger object",
     "def f(url, x):\n    lg = other if x else log\n    lg.info(url)\n", True),
    ("alias of a method off a logger object",
     "import logging\ndef f(url):\n    lg = logging.getLogger()\n    p = lg.info\n"
     "    p(url)\n", True),
    ("logger object read late by a lambda",
     "import logging\ndef f(url):\n    lg = fetch\n    h = lambda: lg.info(url)\n"
     "    lg = logging.getLogger()\n    h()\n", True),
    ("logger object read by a nested def",
     "import logging\ndef f(url):\n    lg = logging.getLogger()\n    def g():\n"
     "        lg.info(url)\n", True),
    ("logger object as a parameter default",
     "import logging\ndef f(url):\n    def g(lg=logging.getLogger()):\n"
     "        lg.info(url)\n", True),
    # RM-1563 keep-greens.
    ("logger object re-bound to a non-logger before the call",
     "import logging\ndef f(url):\n    lg = logging.getLogger()\n    lg = fetch\n"
     "    lg.info(url)\n", False),
    ("logger object called with a clean message",
     "import logging\ndef f(url):\n    lg = logging.getLogger()\n    lg.info('ok')\n",
     False),
    ("attribute logger called with a sanitized value",
     "def f(self, url):\n    self.log.info(_safe_url(url))\n", False),
    ("a method named log off a non-log object is not a sink",
     "def f(url):\n    client.log(url)\n", False),
    ("an attribute ending in log is not a logger",
     "def f(self, url):\n    self.catalog.info(url)\n", False),
    ("a conditional of two non-log functions is not a log alias",
     "def f(url, x):\n    p = fetch if x else send\n    p(url)\n", False),
    # RM-1563 tuple aliases: a tuple / list target paired by position with
    # a tuple / list value, and a `for` over a literal tuple / list / set,
    # bind a logging function or a logger object as a plain name does.
    ("tuple alias of a log function",
     "def f(url):\n    p, q = log.info, fetch\n    p(url)\n", True),
    ("tuple alias in the second position",
     "def f(url):\n    p, q = fetch, log.warning\n    q('%s', url)\n", True),
    ("list target alias of a log function",
     "def f(url):\n    [p, q] = [log.info, fetch]\n    p(url)\n", True),
    ("tuple logger object",
     "import logging\ndef f(url):\n    lg, n = logging.getLogger(), 0\n"
     "    lg.info(url)\n", True),
    ("nested tuple alias",
     "def f(url):\n    p, (q, r) = fetch, (send, log.info)\n    r(url)\n", True),
    ("tuple swap moves the alias",
     "def f(url):\n    p, q = log.info, fetch\n    p, q = q, p\n    q(url)\n", True),
    ("starred tuple target",
     "def f(url):\n    p, *rest = log.info, fetch, send\n    p(url)\n", True),
    ("chained tuple targets",
     "def f(url):\n    p, q = r, s = log.info, fetch\n    r(url)\n", True),
    ("for over a tuple of log functions",
     "def f(url):\n    for p in (log.info,):\n        p(url)\n", True),
    ("for over a list with a log function second",
     "def f(url):\n    for p in [fetch, log.warning]:\n        p(url)\n", True),
    ("for over a tuple of logger objects",
     "import logging\ndef f(url):\n    for lg in (logging.getLogger('a'),):\n"
     "        lg.info(url)\n", True),
    ("for with a tuple target over pairs",
     "def f(url):\n    for p, q in ((fetch, log.info),):\n        q(url)\n", True),
    ("starred target over a nested literal",
     "def f(url):\n    p, *rest = fetch, (send, log.info)\n    p(url)\n", True),
    ("starred value element pairs nothing by position",
     "def f(url):\n    p, *q = *(log.info,), fetch\n    p(url)\n", True),
    ("starred tuple logger object",
     "import logging\ndef f(url):\n    lg, *rest = logging.getLogger(), 0, 1\n"
     "    lg.info(url)\n", True),
    ("for over a starred literal",
     "def f(url):\n    for p in (fetch, *[log.info]):\n        p(url)\n", True),
    ("for over a tuple holding an earlier alias",
     "def f(url):\n    p = log.info\n    for q in (p,):\n        q(url)\n", True),
    ("tuple alias of an earlier logger object",
     "import logging\ndef f(url):\n    lg = logging.getLogger()\n"
     "    a, b = 0, lg\n    b.info(url)\n", True),
    # RM-1563 tuple-alias keep-greens.
    ("tuple alias pairs by position",
     "def f(url):\n    p, q = log.info, fetch\n    q(url)\n", False),
    ("tuple re-binding clears an alias",
     "def f(url):\n    p = log.info\n    p, q = fetch, send\n    p(url)\n", False),
    ("tuple swap moves the alias away",
     "def f(url):\n    p, q = log.info, fetch\n    p, q = q, p\n    p(url)\n", False),
    ("for over non-log functions",
     "def f(url):\n    for p in (fetch, send):\n        p(url)\n", False),
    ("tuple alias called with a clean value",
     "def f(url):\n    p, q = log.info, fetch\n    p('x')\n", False),
    ("for over log functions called with a sanitized value",
     "def f(url):\n    for p in (log.info,):\n        p(_safe_url(url))\n", False),
    ("a starred target binds a list, not a log function",
     "def f(url):\n    p, *rest = fetch, log.info\n    rest(url)\n", False),
    # RM-1563 lambda defaults: a lambda parameter whose default carries the
    # value, or is a logging function or a logger object, is read inside the
    # lambda body, as a nested def's parameter is (RM-1562).
    ("lambda parameter default carries the value",
     "def f(url):\n    h = lambda m=url: log.info(m)\n    h()\n", True),
    ("lambda called in place with a tainted default",
     "def f(url):\n    (lambda m=url: log.warning('%s', m))()\n", True),
    ("lambda keyword-only default carries the value",
     "def f(url):\n    h = lambda *, m=url: log.info(m)\n    h()\n", True),
    ("lambda default bound from a tainted local",
     "def f(url):\n    m = 'at ' + url\n    h = lambda d=m: log.error(d)\n    h()\n",
     True),
    ("lambda default is a log function",
     "def f(url):\n    h = lambda p=log.info: p(url)\n    h()\n", True),
    ("lambda default is a logger object",
     "import logging\ndef f(url):\n    h = lambda lg=logging.getLogger(): lg.info(url)\n"
     "    h()\n", True),
    ("inner lambda reads an outer lambda default",
     "def f(url):\n    h = lambda m=url: (lambda: log.info(m))\n    h()()\n", True),
    ("inner lambda default reads an outer lambda default",
     "def f(url):\n    h = lambda m=url: (lambda d=m: log.info(d))\n    h()()\n", True),
    ("lambda default inside a nested def default",
     "def f(url):\n    def g(k=lambda m=url: log.info(m)):\n        k()\n", True),
    ("log call inside a lambda default",
     "def f(url):\n    h = lambda d=log.info(url): 0\n    h()\n", True),
    ("lambda default read late inside a default",
     "def f(url):\n    m = 'x'\n    h = lambda d=lambda: log.info(m): 0\n    m = url\n",
     True),
    # RM-1563 lambda-default keep-greens.
    ("lambda default with a sanitized value",
     "def f(url):\n    h = lambda m=_safe_url(url): log.info(m)\n    h()\n", False),
    ("lambda default with a clean value",
     "def f(url):\n    h = lambda m='x': log.info(m)\n    h()\n", False),
    ("lambda default of a non-log function",
     "def f(url):\n    h = lambda p=fetch: p(url)\n    h()\n", False),
    ("a lambda default does not reach a sibling lambda",
     "def f(url):\n    a = lambda m=url: 0\n    b = lambda m='x': log.info(m)\n    b()\n",
     False),
    ("a lambda default does not flow out of the lambda",
     "def f(url):\n    m = 'x'\n    h = lambda m=url: 0\n    log.info(m)\n", False),
    # RM-1563 wrappers: a local def or lambda whose parameter reaches a
    # raise or logging sink makes a call through it a sink for the arguments
    # bound to that parameter.
    ("nested def logs its parameter",
     "def f(url):\n    def g(m):\n        log.info(m)\n    g(url)\n", True),
    ("lambda bound to a name logs its parameter",
     "def f(url):\n    p = lambda m: log.info(m)\n    p(url)\n", True),
    ("lambda called in place logs its parameter",
     "def f(url):\n    (lambda m: log.info(m))(url)\n", True),
    ("wrapper parameter passed by keyword",
     "def f(url):\n    def g(a, m):\n        log.info(m)\n    g('x', m=url)\n", True),
    ("wrapper carries its parameter through a local",
     "def f(url):\n    def g(m):\n        n = 'at ' + m\n        log.warning(n)\n"
     "    g(url)\n", True),
    ("wrapper of a wrapper",
     "def f(url):\n    def g(m):\n        log.info(m)\n    def h(k):\n        g(k)\n"
     "    h(url)\n", True),
    ("module-level wrapper called from a function",
     "def g(m):\n    log.info(m)\ndef f(url):\n    g(url)\n", True),
    ("wrapper defined after its caller",
     "def f(url):\n    g(url)\ndef g(m):\n    log.info(m)\n", True),
    ("wrapper logs its varargs",
     "def f(url):\n    def g(fmt, *a):\n        log.info(fmt, *a)\n    g('%s', url)\n",
     True),
    ("wrapper logs its kwargs",
     "def f(url):\n    def g(**kw):\n        log.info(kw)\n    g(m=url)\n", True),
    ("wrapper raises its parameter",
     "def f(url):\n    def g(m):\n        raise E(m)\n    g(url)\n", True),
    ("starred call to a wrapper",
     "def f(url):\n    def g(m):\n        log.info(m)\n    g(*[url])\n", True),
    ("async wrapper logs its parameter",
     "async def f(url):\n    async def g(m):\n        log.info(m)\n    await g(url)\n",
     True),
    ("wrapper with a positional-only parameter",
     "def f(url):\n    def g(a, m, /):\n        log.info(m)\n    g(0, url)\n", True),
    ("positional argument after a starred one",
     "def f(url, xs):\n    def g(m, a):\n        log.info(m)\n    g(*xs, url)\n", True),
    ("wrapper of a wrapper defined after it",
     "def f(url):\n    def h(k):\n        g(k)\n    def g(m):\n        log.info(m)\n"
     "    h(url)\n", True),
    ("module-level wrapper of a wrapper defined after it",
     "def h(k):\n    g(k)\ndef g(m):\n    log.info(m)\ndef f(url):\n    h(url)\n", True),
    # RM-1563 wrapper keep-greens.
    ("wrapper sanitizes its parameter",
     "def f(url):\n    def g(m):\n        log.info(_safe_url(m))\n    g(url)\n", False),
    ("wrapper called with a sanitized value",
     "def f(url):\n    def g(m):\n        log.info(m)\n    g(_safe_url(url))\n", False),
    ("wrapper logs only its other parameter",
     "def f(url):\n    def g(m, n):\n        log.info(n)\n    g(url, 'x')\n", False),
    ("keyword to the wrapper parameter that is not logged",
     "def f(url):\n    def g(m, n):\n        log.info(n)\n    g(n='x', m=url)\n", False),
    ("wrapper name re-bound to a non-log function",
     "def f(url):\n    def g(m):\n        log.info(m)\n    g = fetch\n    g(url)\n", False),
    ("wrapper re-defined without the log call",
     "def f(url):\n    def g(m):\n        log.info(m)\n    def g(m):\n        return 0\n"
     "    g(url)\n", False),
    ("lambda that does not log its parameter",
     "def f(url):\n    p = lambda m: fetch(m)\n    p(url)\n", False),
    ("a parameter shadows an outer wrapper",
     "def g(m):\n    log.info(m)\ndef k(g, n):\n    g(n)\ndef f(url):\n    k(fetch, url)\n",
     False),
    # RM-1563 class-body aliases: a name the class body itself binds to a
    # logging function or logger object is a class ATTRIBUTE, read off
    # `self`, `cls`, the class or an instance.
    ("class attribute alias of a log function called off self",
     "class C:\n    p = log.info\n    def m(self, url):\n        self.p(url)\n", True),
    ("class attribute alias of print called off cls",
     "class C:\n    p = print\n    @classmethod\n    def m(cls, url):\n"
     "        cls.p(url)\n", True),
    ("class attribute alias called off the class after it",
     "class C:\n    p = log.warning\ndef f(url):\n    C.p(url)\n", True),
    ("class attribute alias called off the class from a def before it",
     "def f(url):\n    C.p(url)\nclass C:\n    p = log.warning\n", True),
    ("class attribute alias bound after the method",
     "class C:\n    def m(self, url):\n        self.p(url)\n    p = log.info\n", True),
    ("class attribute logger object",
     "import logging\nclass C:\n    lg = logging.getLogger('x')\n"
     "    def m(self, url):\n        self.lg.info(url)\n", True),
    ("class attribute staticmethod over a log function",
     "class C:\n    p = staticmethod(log.info)\n    def m(self, url):\n"
     "        self.p(url)\n", True),
    ("class attribute alias passed through a local",
     "class C:\n    p = log.info\n    def m(self, url):\n        q = self.p\n"
     "        q(url)\n", True),
    ("class attribute alias off an instance of a class in a function",
     "def f(url):\n    class C:\n        p = log.info\n    C().p(url)\n", True),
    ("class attribute tuple alias",
     "class C:\n    p, q = log.info, fetch\n    def m(self, url):\n        self.p(url)\n",
     True),
    ("class attribute alias bound in a class-level branch",
     "class C:\n    if X:\n        p = log.info\n    else:\n        p = fetch\n"
     "    def m(self, url):\n        self.p(url)\n", True),
    ("class attribute alias of an earlier class-level alias",
     "class C:\n    p = log.info\n    q = p\n    def m(self, url):\n        self.q(url)\n",
     True),
    ("instance attribute alias set in __init__",
     "class C:\n    def __init__(self):\n        self.p = log.info\n"
     "    def m(self, url):\n        self.p(url)\n", True),
    ("instance attribute alias set in a later method",
     "class C:\n    def m(self, url):\n        self.p(url)\n"
     "    def __init__(self):\n        self.p = print\n", True),
    ("instance attribute logger object",
     "import logging\nclass C:\n    def __init__(self):\n"
     "        self.lg = logging.getLogger()\n    def m(self, url):\n"
     "        self.lg.warning(url)\n", True),
    # RM-1563 class-body keep-greens.
    ("instance attribute of a non-log function",
     "class C:\n    def __init__(self):\n        self.p = fetch\n"
     "    def m(self, url):\n        self.p(url)\n", False),
    ("class attribute alias re-bound before the class ends",
     "class C:\n    p = log.info\n    p = fetch\n    def m(self, url):\n"
     "        self.p(url)\n", False),
    ("class attribute of a non-log function",
     "class C:\n    p = fetch\n    def m(self, url):\n        self.p(url)\n", False),
    ("another class attribute is not the alias",
     "class C:\n    p = log.info\n    q = fetch\n    def m(self, url):\n"
     "        self.q(url)\n", False),
    ("class attribute alias called with a sanitized value",
     "class C:\n    p = log.info\n    def m(self, url):\n        self.p(_safe_url(url))\n",
     False),
    ("a local alias does not make an attribute an alias",
     "def f(url, o):\n    p = log.info\n    o.p(url)\n", False),
    ("an alias bound in a method body is not a class attribute",
     "class C:\n    def a(self):\n        p = log.info\n    def m(self, url):\n"
     "        self.p(url)\n", False),
    ("a module alias does not make a class attribute",
     "p = log.info\nclass C:\n    def m(self, url):\n        self.p(url)\n", False),
    # RM-1786 method wrappers: a def or lambda the class body binds whose
    # parameter reaches a sink is a wrapper held as an attribute. A call off
    # an instance or `cls` binds the first parameter (`self` / `cls`), so the
    # positions shift by one; a staticmethod binds nothing, and a plain
    # method called off the class name itself is unbound.
    ("method wrapper called off self",
     "class C:\n    def g(self, m):\n        log.info(m)\n    def h(self, url):\n"
     "        self.g(url)\n", True),
    ("class-level lambda method wrapper",
     "class C:\n    g = lambda self, m: log.info(m)\n    def h(self, url):\n"
     "        self.g(url)\n", True),
    ("staticmethod wrapper called off self",
     "class C:\n    @staticmethod\n    def g(m):\n        log.info(m)\n"
     "    def h(self, url):\n        self.g(url)\n", True),
    ("staticmethod wrapper called off the class",
     "class C:\n    @staticmethod\n    def g(m):\n        log.info(m)\n"
     "def f(url):\n    C.g(url)\n", True),
    ("classmethod wrapper called off the class",
     "class C:\n    @classmethod\n    def g(cls, m):\n        log.info(m)\n"
     "def f(url):\n    C.g(url)\n", True),
    ("method wrapper called unbound off the class",
     "class C:\n    def g(self, m):\n        log.info(m)\n"
     "def f(o, url):\n    C.g(o, url)\n", True),
    ("method wrapper called off an instance after the class",
     "class C:\n    def g(self, m):\n        log.info(m)\ndef f(url):\n"
     "    C().g(url)\n", True),
    ("method wrapper defined after its caller",
     "class C:\n    def h(self, url):\n        self.g(url)\n    def g(self, m):\n"
     "        log.info(m)\n", True),
    ("method wrapper called by keyword",
     "class C:\n    def g(self, m):\n        log.info(m)\n    def h(self, url):\n"
     "        self.g(m=url)\n", True),
    ("varargs method wrapper",
     "class C:\n    def g(self, *a):\n        log.info(*a)\n    def h(self, url):\n"
     "        self.g('x', url)\n", True),
    ("varargs after a named parameter of a method wrapper",
     "class C:\n    def g(self, m, *a):\n        log.info(*a)\n    def h(self, url):\n"
     "        self.g('x', url)\n", True),
    ("method wrapper that raises",
     "class C:\n    def g(self, m):\n        raise E(m)\n    def h(self, url):\n"
     "        self.g(url)\n", True),
    ("async method wrapper",
     "class C:\n    async def g(self, m):\n        log.info(m)\n"
     "    async def h(self, url):\n        await self.g(url)\n", True),
    ("staticmethod over a lambda",
     "class C:\n    g = staticmethod(lambda m: log.info(m))\n"
     "    def h(self, url):\n        self.g(url)\n", True),
    ("instance attribute lambda wrapper",
     "class C:\n    def __init__(self):\n        self.g = lambda m: log.info(m)\n"
     "    def h(self, url):\n        self.g(url)\n", True),
    ("annotated class-level lambda method wrapper",
     "class C:\n    g: Any = lambda self, m: log.info(m)\n    def h(self, url):\n"
     "        self.g(url)\n", True),
    ("annotated staticmethod over a lambda",
     "class C:\n    g: Any = staticmethod(lambda m: log.info(m))\n"
     "    def h(self, url):\n        self.g(url)\n", True),
    ("method wrapper called unbound off a subclass",
     "class C:\n    def g(self, m):\n        log.info(m)\nclass D(C):\n    pass\n"
     "def f(o, url):\n    D.g(o, url)\n", True),
    ("method wrapper called unbound off a dotted class path",
     "class O:\n    class I:\n        def g(self, m):\n            log.info(m)\n"
     "def f(o, url):\n    O.I.g(o, url)\n", True),
    ("method wrapper called unbound off cls",
     "class C:\n    def g(self, m):\n        log.info(m)\n    @classmethod\n"
     "    def k(cls, o, url):\n        cls.g(o, url)\n", True),
    ("method wrapper called unbound off type(self)",
     "class C:\n    def g(self, m):\n        log.info(m)\n    def h(self, url):\n"
     "        type(self).g(self, url)\n", True),
    # RM-1786 keep-greens.
    ("method that does not log its parameter",
     "class C:\n    def g(self, m):\n        log.info('x')\n    def h(self, url):\n"
     "        self.g(url)\n", False),
    ("method wrapper positional shift",
     "class C:\n    def g(self, m, n):\n        log.info(m)\n    def h(self, url):\n"
     "        self.g('x', url)\n", False),
    ("method wrapper positional shift off a new instance",
     "class C:\n    def g(self, m, n):\n        log.info(m)\ndef f(url):\n"
     "    C().g('x', url)\n", False),
    ("classmethod wrapper positional shift",
     "class C:\n    @classmethod\n    def g(cls, m, n):\n        log.info(m)\n"
     "def f(url):\n    C.g('x', url)\n", False),
    ("unbound method call keeps the self slot",
     "class C:\n    def g(self, m, n):\n        log.info(n)\n"
     "def f(o, url):\n    C.g(o, url, 'x')\n", False),
    # The two below log their SECOND parameter, so a mark made for them would
    # be read shifted onto `url`.
    ("a module wrapper does not make a method wrapper",
     "def g(s, m):\n    log.info(m)\nclass C:\n    def h(self, url):\n"
     "        self.g(url)\n", False),
    ("method wrapper re-bound before the class ends",
     "class C:\n    def g(self, m):\n        log.info(m)\n    g = fetch\n"
     "    def h(self, url):\n        self.g(url)\n", False),
    ("method wrapper called with a sanitized value",
     "class C:\n    def g(self, m):\n        log.info(m)\n    def h(self, url):\n"
     "        self.g(_safe_url(url))\n", False),
    ("a wrapper nested in a method is not an attribute",
     "class C:\n    def a(self):\n        def g(s, m):\n            log.info(m)\n"
     "    def h(self, url):\n        self.g(url)\n", False),
    # RM-1563 wrapper aliases: a name bound to a wrapper (`h = g`), or to
    # a staticmethod / classmethod over one (`g = staticmethod(g)`), is the
    # same wrapper; in a class body it takes the kind the value gives it.
    ("alias of a wrapper def",
     "def g(m):\n    log.info(m)\nh = g\ndef f(url):\n    h(url)\n", True),
    ("alias of a wrapper lambda",
     "g = lambda m: log.info(m)\nh = g\ndef f(url):\n    h(url)\n", True),
    ("alias chain of a wrapper",
     "def g(m):\n    log.info(m)\nh = g\nk = h\ndef f(url):\n    k(url)\n", True),
    ("local alias of a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    h = g\n    h(url)\n", True),
    ("conditional alias of a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url, c):\n    h = g if c else fetch\n"
     "    h(url)\n", True),
    ("annotated alias of a wrapper",
     "def g(m):\n    log.info(m)\nh: Any = g\ndef f(url):\n    h(url)\n", True),
    ("def re-wrapped by name as a staticmethod",
     "class C:\n    def g(m):\n        log.info(m)\n    g = staticmethod(g)\n"
     "    def h(self, url):\n        self.g(url)\n", True),
    ("def re-wrapped by name as a classmethod",
     "class C:\n    def g(cls, m):\n        log.info(m)\n    g = classmethod(g)\n"
     "def f(url):\n    C.g(url)\n", True),
    ("class-level alias of a method wrapper",
     "class C:\n    def g(self, m):\n        log.info(m)\n    h = g\n"
     "    def k(self, url):\n        self.h(url)\n", True),
    ("class-level alias of a staticmethod wrapper",
     "class C:\n    @staticmethod\n    def g(m):\n        log.info(m)\n    h = g\n"
     "    def k(self, url):\n        self.h(url)\n", True),
    ("staticmethod over a module wrapper in a class body",
     "def g(m):\n    log.info(m)\nclass C:\n    h = staticmethod(g)\n"
     "    def k(self, url):\n        self.h(url)\n", True),
    ("module wrapper aliased in a class body is a method",
     "def g(s, m):\n    log.info(m)\nclass C:\n    h = g\n"
     "    def k(self, url):\n        self.h(url)\n", True),
    ("module wrapper stored on an instance attribute",
     "def g(m):\n    log.info(m)\nclass C:\n    def __init__(self):\n        self.h = g\n"
     "    def k(self, url):\n        self.h(url)\n", True),
    # RM-1563 wrapper-alias keep-greens.
    ("alias of a function that does not log its parameter",
     "def g(m):\n    log.info('x')\nh = g\ndef f(url):\n    h(url)\n", False),
    ("alias of a wrapper re-bound before the call",
     "def g(m):\n    log.info(m)\ndef f(url):\n    h = g\n    h = fetch\n    h(url)\n",
     False),
    ("staticmethod re-wrap of a non-wrapper",
     "class C:\n    def g(m):\n        log.info('x')\n    g = staticmethod(g)\n"
     "    def h(self, url):\n        self.g(url)\n", False),
    ("alias of a wrapper called with a sanitized value",
     "def g(m):\n    log.info(m)\nh = g\ndef f(url):\n    h(_safe_url(url))\n", False),
    ("class-level alias of a method wrapper keeps the positional shift",
     "class C:\n    def g(self, m, n):\n        log.info(m)\n    h = g\n"
     "    def k(self, url):\n        self.h('x', url)\n", False),
    # RM-1563 default-bound wrappers: a parameter whose default is a
    # logging function or logger object is one inside the body (RM-1562),
    # so a parameter the body hands it is a sink parameter of the wrapper.
    ("wrapper whose logging function is a default",
     "def g(m, p=log.info):\n    p(m)\ndef f(url):\n    g(url)\n", True),
    ("wrapper whose logging function is a keyword-only default",
     "def g(m, *, p=log.info):\n    p(m)\ndef f(url):\n    g(url)\n", True),
    ("wrapper whose logger object is a default",
     "def g(m, w=logging.getLogger()):\n    w.info(m)\ndef f(url):\n    g(url)\n", True),
    ("wrapper whose default is a partial over a logging function",
     "def g(m, p=partial(log.info, '%s')):\n    p(m)\ndef f(url):\n    g(url)\n", True),
    ("wrapper whose default is a name bound to a logging function",
     "q = log.info\ndef g(m, p=q):\n    p(m)\ndef f(url):\n    g(url)\n", True),
    ("lambda wrapper whose logging function is a default",
     "g = lambda m, p=log.info: p(m)\ndef f(url):\n    g(url)\n", True),
    ("lambda wrapper with a logging default called in place",
     "def f(url):\n    (lambda m, p=log.info: p(m))(url)\n", True),
    ("method wrapper whose logging function is a default",
     "class C:\n    def g(self, m, p=log.info):\n        p(m)\n"
     "    def h(self, url):\n        self.g(url)\n", True),
    ("local wrapper whose logging function is a default",
     "def f(url):\n    def g(m, p=log.info):\n        p(m)\n    g(url)\n", True),
    # RM-1563 default-bound wrapper keep-greens.
    ("default logging function never handed the parameter",
     "def g(m, p=log.info):\n    p('x')\ndef f(url):\n    g(url)\n", False),
    ("default-bound wrapper called with a sanitized value",
     "def g(m, p=log.info):\n    p(m)\ndef f(url):\n    g(_safe_url(url))\n", False),
    ("default that is not a logging function",
     "def g(m, p=fetch):\n    p(m)\ndef f(url):\n    g(url)\n", False),
    ("default logging function re-bound in the body",
     "def g(m, p=log.info):\n    p = fetch\n    p(m)\ndef f(url):\n    g(url)\n", False),
    ("default read from a name the module re-binds to a logger later",
     "q = fetch\ndef g(m, p=q):\n    p(m)\nq = log.info\ndef f(url):\n    g(url)\n",
     False),
    # RM-1563 comprehension targets: a comprehension's `for` target is
    # bound from its iterable, as a `for` statement's is (add-only), so a
    # wrapper, a logging call, a walrus or a mutator in its parts sees it.
    ("wrapper called in a list comprehension",
     "def g(m):\n    log.info(m)\ndef f(url):\n    [g(x) for x in [url]]\n", True),
    ("wrapper called in a set comprehension",
     "def g(m):\n    log.info(m)\ndef f(url):\n    {g(x) for x in [url]}\n", True),
    ("wrapper called in a dict comprehension value",
     "def g(m):\n    log.info(m)\ndef f(url):\n    {x: g(x) for x in [url]}\n", True),
    ("wrapper called in a generator expression",
     "def g(m):\n    log.info(m)\ndef f(url):\n    list(g(x) for x in [url])\n", True),
    ("logging call in a comprehension over a tainted name",
     "def f(url):\n    us = [url]\n    [log.info(x) for x in us]\n", True),
    ("logging call in a comprehension condition",
     "def f(url):\n    [1 for x in [url] if log.info(x)]\n", True),
    ("wrapper in a nested comprehension generator",
     "def g(m):\n    log.info(m)\ndef f(url):\n    [g(y) for x in [[url]] for y in x]\n",
     True),
    ("lambda wrapper called in a comprehension",
     "g = lambda m: log.info(m)\ndef f(url):\n    [g(x) for x in [url]]\n", True),
    ("method wrapper called in a comprehension",
     "class C:\n    def g(self, m):\n        log.info(m)\n    def h(self, url):\n"
     "        [self.g(x) for x in [url]]\n", True),
    ("comprehension target bound to a logging function",
     "def f(url):\n    [p(url) for p in (log.info,)]\n", True),
    ("lambda in a comprehension reads its target",
     "def f(url):\n    [(lambda: log.info(x))() for x in [url]]\n", True),
    ("walrus in a comprehension binds its target's value",
     "def f(url):\n    [(m := x) for x in [url]]\n    log.info(m)\n", True),
    ("walrus in a generator expression binds its target's value",
     "def f(url):\n    any((m := x) for x in [url])\n    log.info(m)\n", True),
    ("mutator in a comprehension fills its receiver",
     "def f(url):\n    q = []\n    [q.append(x) for x in [url]]\n    log.info(q)\n", True),
    # RM-1563 comprehension keep-greens.
    ("comprehension wrapper over a clean iterable",
     "def g(m):\n    log.info(m)\ndef f(url):\n    [g(x) for x in ['a']]\n", False),
    ("comprehension wrapper called with a sanitized value",
     "def g(m):\n    log.info(m)\ndef f(url):\n    [g(_safe_url(x)) for x in [url]]\n",
     False),
    ("comprehension over a function that does not log its parameter",
     "def g(m):\n    log.info('x')\ndef f(url):\n    [g(x) for x in [url]]\n", False),
    ("comprehension target does not flow out of the comprehension",
     "def f(url):\n    [0 for x in [url]]\n    log.info(x)\n", False),
    ("comprehension target does not reach a sibling comprehension",
     "def g(m):\n    log.info(m)\ndef f(url):\n    ([0 for x in [url]], [g(x) for x in 'a'])\n",
     False),
    ("a later generator's target does not reach an earlier iterable",
     "def f(url, xs):\n    [0 for y in [log.info(x) for x in 'a'] for x in [url]]\n", False),
    ("a generator's own target does not reach its own iterable",
     "def f(url):\n    [0 for x in (url, log.info(x))]\n", False),
    # RM-1563 wrapper bindings past a bare `=`: a tuple target paired by
    # position, a starred or mismatched split (every name, the safe side), a
    # walrus, a `for` target and a comprehension target over a literal
    # iterable all make the name a wrapper, as `h = g` does.
    ("tuple target bound to a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    h, k = g, fetch\n    h(url)\n", True),
    ("module tuple target bound to a wrapper",
     "def g(m):\n    log.info(m)\nh, k = g, fetch\ndef f(url):\n    h(url)\n", True),
    ("tuple swap moves a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    h, k = fetch, g\n    h, k = k, h\n"
     "    h(url)\n", True),
    ("nested tuple target bound to a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    (h, k), j = (fetch, g), fetch\n"
     "    k(url)\n", True),
    ("starred tuple target bound to a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    h, *k = fetch, g, fetch\n    h(url)\n",
     True),
    ("tuple target bound to a wrapper lambda",
     "def f(url):\n    h, k = lambda m: log.info(m), fetch\n    h(url)\n", True),
    ("walrus bound to a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    if (h := g):\n        h(url)\n", True),
    ("walrus bound to a wrapper lambda",
     "def f(url):\n    (h := lambda m: log.info(m))\n    h(url)\n", True),
    ("walrus in a comprehension bound to a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    [(h := g) for _ in 'a']\n    h(url)\n",
     True),
    ("walrus bound to a comprehension target bound to a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    [(h := k) for k in (g,)]\n    h(url)\n",
     True),
    ("for target bound to a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    for h in (g,):\n        h(url)\n", True),
    ("for tuple target bound to a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    for h, k in ((fetch, g),):\n"
     "        k(url)\n", True),
    ("comprehension target bound to a wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    [h(url) for h in (g,)]\n", True),
    # RM-1563 wrapper-binding keep-greens.
    ("tuple target pairs a wrapper by position",
     "def g(m):\n    log.info(m)\ndef f(url):\n    h, k = g, fetch\n    k(url)\n", False),
    ("tuple target bound to a wrapper called with a sanitized value",
     "def g(m):\n    log.info(m)\ndef f(url):\n    h, k = g, fetch\n    h(_safe_url(url))\n",
     False),
    ("tuple target re-bound before the call",
     "def g(m):\n    log.info(m)\ndef f(url):\n    h, k = g, fetch\n    h, k = fetch, fetch\n"
     "    h(url)\n", False),
    ("walrus bound to a non-wrapper",
     "def g(m):\n    log.info(m)\ndef f(url):\n    if (h := fetch):\n        h(url)\n", False),
    ("for target over non-wrappers",
     "def g(m):\n    log.info(m)\ndef f(url):\n    for h in (fetch,):\n        h(url)\n", False),
    ("comprehension tuple target pairs a wrapper by position",
     "def g(m):\n    log.info(m)\ndef f(url):\n    [k(url) for h, k in ((g, fetch),)]\n",
     False),
    ("comprehension wrapper target does not flow out",
     "def g(m):\n    log.info(m)\ndef f(url):\n    [0 for h in (g,)]\n    h(url)\n", False),
    # RM-1563 same root in a class body: a tuple, `for` or walrus binding
    # there makes a method, as `h = g` does (`_class_method_kinds`).
    ("class-level tuple alias of a method wrapper",
     "class C:\n    def g(self, m):\n        log.info(m)\n    h, j = g, fetch\n"
     "    def k(self, url):\n        self.h(url)\n", True),
    ("class-level for alias of a method wrapper",
     "class C:\n    def g(self, m):\n        log.info(m)\n    for h in (g,):\n        pass\n"
     "    def k(self, url):\n        self.h(url)\n", True),
    ("class-level walrus alias of a method wrapper",
     "class C:\n    def g(self, m):\n        log.info(m)\n    (h := g)\n"
     "    def k(self, url):\n        self.h(url)\n", True),
    ("class-level tuple alias of a method wrapper pairs by position",
     "class C:\n    def g(self, m):\n        log.info(m)\n    h, j = g, fetch\n"
     "    def k(self, url):\n        self.j(url)\n", False),
    ("class-level tuple alias of a method wrapper keeps the positional shift",
     "class C:\n    def g(self, m, n):\n        log.info(m)\n    h, j = g, fetch\n"
     "    def k(self, url):\n        self.h('x', url)\n", False),
    # RM-1787 (a): a parameter default that is itself a wrapper makes the
    # parameter one inside the body, so a parameter the body hands it is a
    # sink parameter (`_default_bindings` marks `_SINKFN` too).
    ("wrapper whose default is a lambda wrapper",
     "def g(m, p=lambda x: log.info(x)):\n    p(m)\ndef f(url):\n    g(url)\n", True),
    ("wrapper whose default is a name bound to a lambda wrapper",
     "h = lambda x: log.info(x)\ndef g(m, p=h):\n    p(m)\ndef f(url):\n    g(url)\n",
     True),
    ("wrapper whose default is a def wrapper",
     "def h(x):\n    log.info(x)\ndef g(m, p=h):\n    p(m)\ndef f(url):\n    g(url)\n",
     True),
    ("wrapper whose keyword-only default is a wrapper",
     "def h(x):\n    log.info(x)\ndef g(m, *, p=h):\n    p(m)\ndef f(url):\n    g(url)\n",
     True),
    ("wrapper whose default is a conditional over a wrapper",
     "def h(x):\n    log.info(x)\ndef g(m, p=h if ok else fetch):\n    p(m)\n"
     "def f(url):\n    g(url)\n", True),
    ("wrapper whose wrapper default is called by keyword",
     "def h(x):\n    log.info(x)\ndef g(m, p=h):\n    p(x=m)\ndef f(url):\n    g(url)\n",
     True),
    ("lambda wrapper whose default is a wrapper",
     "def h(x):\n    log.info(x)\ng = lambda m, p=h: p(m)\ndef f(url):\n    g(url)\n", True),
    ("lambda with a wrapper default called in place",
     "def h(x):\n    log.info(x)\ndef f(url):\n    (lambda m, p=h: p(m))(url)\n", True),
    ("lambda whose tainted default is handed to a wrapper default",
     "def h(x):\n    log.info(x)\ndef f(url):\n    k = lambda m=url, p=h: p(m)\n", True),
    ("local def whose tainted default is handed to a wrapper default",
     "def h(x):\n    log.info(x)\ndef f(url):\n    def g(m=url, p=h):\n        p(m)\n", True),
    ("local wrapper whose default is a wrapper",
     "def h(x):\n    log.info(x)\ndef f(url):\n    def g(m, p=h):\n        p(m)\n    g(url)\n",
     True),
    ("method wrapper whose default is a wrapper",
     "def h(x):\n    log.info(x)\nclass C:\n    def g(self, m, p=h):\n        p(m)\n"
     "    def k(self, url):\n        self.g(url)\n", True),
    # RM-1787 (a) keep-greens.
    ("wrapper default never handed the parameter",
     "def h(x):\n    log.info(x)\ndef g(m, p=h):\n    p('x')\ndef f(url):\n    g(url)\n",
     False),
    ("wrapper default called with a sanitized value",
     "def h(x):\n    log.info(x)\ndef g(m, p=h):\n    p(m)\ndef f(url):\n"
     "    g(_safe_url(url))\n", False),
    ("wrapper default handed the parameter at a non-sink position",
     "def h(x, y):\n    log.info(y)\ndef g(m, p=h):\n    p(m, 'x')\ndef f(url):\n"
     "    g(url)\n", False),
    ("wrapper default re-bound in the body",
     "def h(x):\n    log.info(x)\ndef g(m, p=h):\n    p = fetch\n    p(m)\n"
     "def f(url):\n    g(url)\n", False),
    ("default read from a name the module re-binds to a wrapper later",
     "def h(x):\n    log.info(x)\nq = fetch\ndef g(m, p=q):\n    p(m)\nq = h\n"
     "def f(url):\n    g(url)\n", False),
    # RM-1563 (nested-def flow-out precision): a name a def binds is local
    # to it unless declared `global` / `nonlocal`, so what the body binds to
    # it does not reach the enclosing scope's name of the same spelling.
    ("logging alias bound inside a nested def does not flow out",
     "def f(url):\n    def g():\n        p = log.info\n    g()\n    p(url)\n", False),
    ("logging alias bound inside a module-level def does not flow out",
     "def g():\n    p = log.info\ndef f(url):\n    p(url)\n", False),
    ("value bound inside a nested def does not flow out",
     "def f(url, m):\n    def g():\n        m = url\n    g()\n    raise E(m)\n", False),
    ("wrapper defined inside a nested def does not flow out",
     "def f(url):\n    def g():\n        def h(m):\n            log.info(m)\n    g()\n"
     "    h(url)\n", False),
    ("logger object bound inside a nested def does not flow out",
     "def f(url):\n    def g():\n        out = log\n    g()\n    out.info(url)\n", False),
    ("for target bound inside a nested def does not flow out",
     "def f(url, m):\n    def g():\n        for m in (url,):\n            pass\n    g()\n"
     "    raise E(m)\n", False),
    ("except name bound inside a nested def does not flow out",
     "def f():\n    def g():\n        try:\n            h()\n        except OSError as exc:\n"
     "            pass\n    g()\n    raise E(f'{exc}')\n", False),
    ("walrus target bound inside a nested def does not flow out",
     "def f(url, m):\n    def g():\n        (m := url)\n    g()\n    raise E(m)\n", False),
    # ... and every way the binding DOES reach the enclosing scope still flows.
    ("logging alias bound through global in a nested def",
     "def f(url):\n    def g():\n        global p\n        p = log.info\n    g()\n    p(url)\n",
     True),
    ("logging alias bound through nonlocal in a nested def",
     "def f(url):\n    p = str\n    def g():\n        nonlocal p\n        p = log.info\n"
     "    g()\n    p(url)\n", True),
    ("global declared deeper than the def that also binds the name",
     "def f(url):\n    def g():\n        m = 'x'\n        def h():\n            global m\n"
     "            m = url\n        h()\n    g()\n    raise E(m)\n", True),
    # RM-1791: a `nonlocal` declared in a NESTED scope names a binding of
    # some enclosing FUNCTION, never a module one, so it is still the def's
    # own local when the def binds the name: the nested re-bind reaches the
    # def's state (the rows above and below) but not the module's.
    ("parameter re-bound through nonlocal in a nested def does not flow out",
     "def f(m):\n    def g():\n        nonlocal m\n        m = url\n    g()\nraise E(m)\n",
     False),
    ("local re-bound through nonlocal in a nested def does not flow out",
     "def f():\n    m = 'x'\n    def g():\n        nonlocal m\n        m = url\n    g()\n"
     "raise E(m)\n", False),
    ("parameter re-bound through nonlocal does not reach a later def",
     "def f(m):\n    def g():\n        nonlocal m\n        m = url\n    g()\ndef k(m):\n"
     "    raise E(m)\n", False),
    ("logging alias re-bound through nonlocal does not flow out",
     "def f(p):\n    def g():\n        nonlocal p\n        p = log.info\n    g()\np(url)\n",
     False),
    ("method re-binds through nonlocal across a class, which does not flow out",
     "def f(m):\n    class C:\n        def g(self):\n            nonlocal m\n"
     "            m = url\n    C().g()\nraise E(m)\n", False),
    ("parameter re-bound through nonlocal is read inside the def",
     "def f(m):\n    def g():\n        nonlocal m\n        m = url\n    g()\n    raise E(m)\n",
     True),
    ("nonlocal two defs deep is read inside the def it names",
     "def f(m):\n    def g():\n        def h():\n            nonlocal m\n            m = url\n"
     "        h()\n    g()\n    raise E(m)\n", True),
    ("nonlocal across a class is read inside the def it names",
     "def f(m):\n    class C:\n        def g(self):\n            nonlocal m\n"
     "            m = url\n    C().g()\n    raise E(m)\n", True),
    ("nonlocal in the def itself reaches the enclosing def",
     "def o():\n    m = 'x'\n    def f():\n        nonlocal m\n        m = url\n    f()\n"
     "    raise E(m)\n", True),
    ("nonlocal the def does not bind passes through it",
     "def o():\n    m = 'x'\n    def f():\n        def g():\n            nonlocal m\n"
     "            m = url\n        g()\n    f()\n    raise E(m)\n", True),
    ("nonlocal in a nested def mutating the parameter still flows out",
     "def f(m):\n    def g():\n        nonlocal m\n        m.append(url)\n    g()\n"
     "raise E(m)\n", True),
    ("global beside a nested nonlocal of the same name still flows out",
     "def f():\n    m = 'x'\n    def g():\n        nonlocal m\n        m = 'y'\n"
     "    def h():\n        global m\n        m = url\n    h()\nraise E(m)\n", True),
    ("parameter mutated inside a nested def",
     "def f(url, q):\n    def g(q):\n        q.append(url)\n    g(q)\n    raise E(q[0])\n",
     True),
    ("parameter mutated, then re-bound, inside a nested def",
     "def f(url, q):\n    def g(q):\n        q.append(url)\n        q = []\n    g(q)\n"
     "    raise E(q[0])\n", True),
    # RM-1788: a parameter is local to its def, so what the body binds to
    # it by RE-BINDING the name does not reach the enclosing scope's name of
    # the same spelling. Only a parameter the body may mutate (an attribute
    # or element store, a `_MUTATORS` call or an augmented assignment,
    # anywhere in the def) keeps
    # its taint flowing out, as the object a caller passed in.
    ("parameter re-bound to the value does not flow out",
     "def g(m):\n    m = url\ndef f(m):\n    raise E(m)\n", False),
    ("parameter re-bound to a logging function does not flow out",
     "def g(p):\n    p = log.info\ndef f(url, p):\n    p(url)\n", False),
    ("parameter re-bound to a logger object does not flow out",
     "def g(p):\n    p = log\ndef f(url, p):\n    p.info(url)\n", False),
    ("parameter re-bound to a wrapper does not flow out",
     "def h(x):\n    log.info(x)\ndef g(p):\n    p = h\ndef f(url, p):\n    p(url)\n",
     False),
    ("method parameter re-bound does not reach a later method",
     "class C:\n    def a(self, m, url):\n        m = url\n    def b(self, m):\n"
     "        raise E(m)\n", False),
    ("parameter re-bound by a for target does not flow out",
     "def g(m):\n    for m in (url,):\n        pass\ndef f(m):\n    raise E(m)\n", False),
    ("parameter re-bound by a with target does not flow out",
     "def g(m):\n    with Opn(url) as m:\n        pass\ndef f(m):\n    raise E(m)\n", False),
    ("parameter re-bound by a walrus does not flow out",
     "def g(m):\n    (m := url)\ndef f(m):\n    raise E(m)\n", False),
    ("parameter re-bound, then a non-mutator method call, does not flow out",
     "def g(m):\n    m = url\n    m.strip()\ndef f(m):\n    raise E(m)\n", False),
    # ... and every way the body may mutate the caller's object still flows.
    ("parameter attribute stored at module level reaches a later def",
     "def g(m):\n    m.x = url\ndef f(m):\n    raise E(m)\n", True),
    ("parameter element stored at module level reaches a later def",
     "def g(m):\n    m[0] = url\ndef f(m):\n    raise E(m)\n", True),
    ("parameter filled by a mutator at module level reaches a later def",
     "def g(m):\n    m.append(url)\ndef f(m):\n    raise E(m)\n", True),
    ("parameter mutated by a closure reaches a later def",
     "def g(m):\n    def h():\n        m.append(url)\n    h()\ndef f(m):\n    raise E(m)\n",
     True),
    ("parameter used as the index of a filled element reaches a later def",
     "def g(m, q):\n    q[m].append(url)\ndef f(m):\n    raise E(m)\n", True),
    ("parameter used as the index of an element store reaches a later def",
     "def g(m, q):\n    q[m] = url\ndef f(m):\n    raise E(m)\n", True),
    ("parameter extended in place by += reaches a later def",
     "def g(m):\n    m += [url]\ndef f(m):\n    raise E(m)\n", True),
    ("parameter updated in place by |= reaches a later def",
     "def g(m):\n    m |= {url}\ndef f(m):\n    raise E(m)\n", True),
    ("parameter extended in place by += inside a nested def",
     "def f(url, q):\n    def g(q):\n        q += [url]\n    g(q)\n    raise E(q[0])\n",
     True),
    ("method parameter extended in place by += reaches a later method",
     "class C:\n    def a(self, q, url):\n        q += [url]\n    def b(self, q):\n"
     "        raise E(q)\n", True),
    ("parameter re-bound and also mutated keeps flowing out",
     "def g(m):\n    m = url\n    m.x = 1\ndef f(m):\n    raise E(m)\n", True),
    ("method attribute store still taints self for a later method",
     "class C:\n    def a(self, url):\n        self.q.append(url)\n    def b(self):\n"
     "        log.info(self.q)\n", True),
    ("attribute alias stored beside a local of the same name",
     "class C:\n    def __init__(self):\n        p = 1\n        self.p = log.info\n"
     "    def m(self, url):\n        self.p(url)\n", True),
    # RM-1794: a plain-name binding to a name (or an attribute / element
    # of one) ALIASES that object, so a value put into the alias in place is
    # in the object the other name holds too, and a parameter the def
    # mutates through an alias flows out as a mutated one does. So does a
    # store made through `setattr`, `__setitem__` or `__setattr__`.
    ("parameter filled through an alias reaches a later def",
     "def g(m):\n    a = m\n    a.append(url)\ndef f(m):\n    raise E(m)\n", True),
    ("local filled through an alias is read in its def",
     "def f(url):\n    m = []\n    a = m\n    a.append(url)\n    raise E(m)\n", True),
    ("name filled through an alias at module level",
     "a = m\na.append(url)\nraise E(m)\n", True),
    ("dict stored into under another name reaches a later def",
     "def g(m):\n    d = m\n    d['k'] = url\ndef f(m):\n    raise E(m)\n", True),
    ("attribute of a parameter stored into under another name",
     "def g(m):\n    d = m.cache\n    d[0] = url\ndef f(m):\n    raise E(m)\n", True),
    ("parameter filled through an alias of an alias",
     "def f(url):\n    m = []\n    a = m\n    b = a\n    b.append(url)\n    raise E(m)\n",
     True),
    ("alias kept when the name between is re-bound",
     "def f(url):\n    m = []\n    a = m\n    b = a\n    a = []\n    b.append(url)\n"
     "    raise E(m)\n", True),
    ("source filled in place is read through its alias",
     "def f(url):\n    m = []\n    a = m\n    m.append(url)\n    raise E(a)\n", True),
    ("parameter extended in place through an alias by +=",
     "def g(m):\n    a = m\n    a += [url]\ndef f(m):\n    raise E(m)\n", True),
    ("parameter filled through a conditional alias",
     "def g(m, n):\n    a = m if c else n\n    a.append(url)\ndef f(m):\n    raise E(m)\n",
     True),
    ("parameter filled through a tuple-bound alias",
     "def g(m, n):\n    a, b = m, n\n    a.append(url)\ndef f(m):\n    raise E(m)\n", True),
    ("alias passed to a mutating helper",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    m = []\n    a = m\n    h(a, url)\n"
     "    raise E(m)\n", True),
    ("helper that fills an alias of its parameter",
     "def h(q, v):\n    a = q\n    a.append(v)\ndef f(url):\n    m = []\n    h(m, url)\n"
     "    raise E(m)\n", True),
    ("parameter set through setattr reaches a later def",
     "def g(m):\n    setattr(m, 'x', url)\ndef f(m):\n    raise E(m)\n", True),
    ("name set through setattr at module level",
     "setattr(m, 'x', url)\nraise E(m)\n", True),
    ("helper that sets its parameter through setattr",
     "def h(q, v):\n    setattr(q, 'u', v)\ndef f(url):\n    m = C()\n    h(m, url)\n"
     "    raise E(m)\n", True),
    ("parameter stored into through __setitem__ reaches a later def",
     "def g(m):\n    m.__setitem__(0, url)\ndef f(m):\n    raise E(m)\n", True),
    ("local set through object.__setattr__",
     "def f(url):\n    o = C()\n    object.__setattr__(o, 'x', url)\n    raise E(o)\n", True),
    ("alias re-bound before the fill does not taint the source",
     "def f(url):\n    m = []\n    a = m\n    a = []\n    a.append(url)\n    raise E(m)\n",
     False),
    ("source re-bound before the fill is not tainted by the alias",
     "def f(url):\n    m = []\n    a = m\n    m = []\n    a.append(url)\n    raise E(m)\n",
     False),
    ("a copy is not an alias",
     "def g(m):\n    a = list(m)\n    a.append(url)\ndef f(m):\n    raise E(m)\n", False),
    ("a slice copy is not an alias",
     "def f(url, items):\n    out = items[:]\n    out.append(url)\n    log.info('%s', items)\n",
     False),
    ("an element of a slice is still a part of its source",
     "def f(url):\n    m = [[]]\n    a = m[0:][0]\n    a.append(url)\n    raise E(m)\n", True),
    ("parameter filled through an alias with a clean value",
     "def g(m):\n    a = m\n    a.append('x')\ndef f(m):\n    raise E(m)\n", False),
    ("alias re-bound to the value does not flow out",
     "def g(m):\n    a = m\n    a = url\ndef f(m):\n    raise E(m)\n", False),
    ("setattr of a clean value",
     "def f(o):\n    setattr(o, 'x', 'y')\n    raise E(o)\n", False),
    ("an alias local to a def does not reach a later def",
     "def g(m):\n    a = m\ndef f(url, a):\n    a.append(url)\n    raise E(m)\n", False),
    ("a parameter shadows an alias of the enclosing scope",
     "a = m\ndef f(url, a):\n    a.append(url)\nraise E(m)\n", False),
    ("an alias made inside a def does not flow out of it",
     "def g():\n    a = G\nG.append(url)\nraise E(a)\n", False),
    # S144-Q-102: a walrus binds an alias as `=` does (`_bind_walrus`).
    ("a walrus alias filled in place fills its source",
     "def f(url):\n    m = []\n    if (a := m):\n        a.append(url)\n    raise E(m)\n",
     True),
    ("a walrus alias of a part fills its source",
     "def f(url):\n    m = C()\n    if (a := m.q):\n        a.append(url)\n    raise E(m)\n",
     True),
    ("a source filled in place is read through its walrus alias",
     "def f(url):\n    m = []\n    if (a := m):\n        pass\n    m.append(url)\n"
     "    raise E(a)\n", True),
    ("a parameter filled through a walrus alias reaches a later def",
     "def g(m):\n    if (a := m):\n        a.append(url)\ndef f(m):\n    raise E(m)\n", True),
    ("a walrus over a walrus aliases both names",
     "def f(url):\n    m = []\n    if (a := (b := m)):\n        a.append(url)\n"
     "    raise E(m)\n", True),
    ("a walrus re-binding a name to a part of itself still reaches the old object",
     "def f(url):\n    m = []\n    a = m\n    if (a := a[0]):\n        a.append(url)\n"
     "    raise E(m)\n", True),
    ("a walrus bound to a copy is not an alias",
     "def f(url):\n    m = []\n    if (a := list(m)):\n        a.append(url)\n    raise E(m)\n",
     False),
    ("a walrus alias re-bound before the fill does not taint the source",
     "def f(url):\n    m = []\n    if (a := m):\n        a = []\n        a.append(url)\n"
     "    raise E(m)\n", False),
    ("a walrus in a comprehension does not alias the enclosing name of its target",
     "def f(url, xs):\n    x = []\n    [(a := x) for x in xs]\n    a.append(url)\n"
     "    raise E(x)\n", False),
    # S144-Q-107: the walrus aliases of one statement are ended once, in
    # source order, as separate `=` statements end them; a re-pass of the
    # fixed point must not rotate them again, and a fill before a walrus is
    # read through the aliases it ends.
    ("a walrus rotation leaves the last name aliasing the first source",
     "def f(url):\n    m = []\n    n = []\n    a = m\n    b = n\n"
     "    g((t := a), (a := b), (b := t))\n    b.append(url)\n    raise E(m)\n", True),
    ("a walrus rotation leaves the middle name aliasing the second source",
     "def f(url):\n    m = []\n    n = []\n    a = m\n    b = n\n"
     "    g((t := a), (a := b), (b := t))\n    a.append(url)\n    raise E(n)\n", True),
    ("a walrus rotation leaves the temporary aliasing the first source",
     "def f(url):\n    m = []\n    n = []\n    a = m\n    b = n\n"
     "    g((t := a), (a := b), (b := t))\n    t.append(url)\n    raise E(m)\n", True),
    ("a fill before a walrus chain in one statement still reaches its source",
     "def f(url):\n    a = []\n    b = a\n    n = []\n"
     "    g(b.append(url), (b := n), (n := a))\n    raise E(a)\n", True),
    ("a walrus cycle with a fill in one statement reaches a fixed point",
     "def f(url):\n    a = []\n    b = []\n    c = a\n    t = []\n    n = []\n"
     "    g(c.append(url), (n := t), (b := t), (t := c), (c := n))\n"
     "    b.append(url)\n    raise E(a)\n", True),
    # A first pass that ends as many marks as it adds still changed the
    # state, so it is re-run: here it fills `q`, ends `a`'s two marks and
    # taints `z`, and only a re-pass reads the filled `q` into `k`.
    ("a walrus re-reads a filled container after a size-neutral first pass",
     "def f(url):\n    m = []\n    q = []\n    a = m\n"
     "    g((k := q[0] + ''), q.append(url), (a := ''), (z := url + ''))\n"
     "    raise E(k)\n", True),
    # S144-Q-109: a re-pass makes no walrus `_ALIAS` marks, so a name does
    # not keep the aliases it had before its own walrus in one statement
    # (a re-pass re-joined them: each row below was flagged).
    ("a walrus rotation does not leave the last name aliasing the second source",
     "def f(url):\n    m = []\n    n = []\n    a = m\n    b = n\n"
     "    g((t := a), (a := b), (b := t))\n    b.append(url)\n    raise E(n)\n", False),
    ("a walrus rotation does not leave the middle name aliasing the first source",
     "def f(url):\n    m = []\n    n = []\n    a = m\n    b = n\n"
     "    g((t := a), (a := b), (b := t))\n    a.append(url)\n    raise E(m)\n", False),
    ("a walrus rotation does not leave the temporary aliasing the second source",
     "def f(url):\n    m = []\n    n = []\n    a = m\n    b = n\n"
     "    g((t := a), (a := b), (b := t))\n    t.append(url)\n    raise E(n)\n", False),
    ("a walrus swap does not leave the re-bound name aliasing its old source",
     "def f(url):\n    m = []\n    n = []\n    a = m\n    b = n\n"
     "    g((t := a), (a := b))\n    a.append(url)\n    raise E(m)\n", False),
    # S144-Q-108: the bindings of one statement run in evaluation order, so
    # a fill before a walrus that re-binds its alias reaches the old source,
    # whatever binds it (a mutator, a helper, setattr, a comprehension), and
    # where evaluation order is not source order (a conditional's test, an
    # assignment's value, a dict display's pairs) evaluation order wins.
    ("a fill before a walrus re-binding its alias in one statement",
     "def f(url):\n    m = []\n    a = m\n    n = []\n    g(a.append(url), (a := n))\n"
     "    raise E(m)\n", True),
    ("a helper fill before a walrus re-binding its alias in one statement",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    m = []\n    a = m\n    n = []\n"
     "    g(h(a, url), (a := n))\n    raise E(m)\n", True),
    ("a setattr before a walrus re-binding its alias in one statement",
     "def f(url):\n    m = C()\n    a = m\n    g(setattr(a, 'x', url), (a := C()))\n"
     "    raise E(m)\n", True),
    ("a comprehension fill before a walrus re-binding its alias",
     "def f(url, xs):\n    m = []\n    a = m\n    n = []\n"
     "    g([a.append(url) for _ in xs], (a := n))\n    raise E(m)\n", True),
    ("a conditional test fill runs before the walrus in its body",
     "def f(url):\n    m = []\n    a = m\n    n = []\n"
     "    g((a := n) if a.append(url) is None else 0)\n    raise E(m)\n", True),
    ("an assignment value fill runs before a walrus in its target",
     "def f(url):\n    m = []\n    a = m\n    n = []\n    d = {}\n"
     "    d[(a := n)] = a.append(url)\n    raise E(m)\n", True),
    ("a dict display pair runs before the next pair's walrus key",
     "def f(url):\n    m = []\n    a = m\n    n = []\n"
     "    g({1: a.append(url), (a := n): 0})\n    raise E(m)\n", True),
    ("a walrus re-binding an alias before the fill in one statement",
     "def f(url):\n    m = []\n    a = m\n    n = []\n    g((a := n), a.append(url))\n"
     "    raise E(m)\n", False),
    ("a dict display walrus key before the next pair's fill",
     "def f(url):\n    m = []\n    a = m\n    n = []\n"
     "    g({(a := n): 0, 1: a.append(url)})\n    raise E(m)\n", False),
    # A walrus that may not run ends no alias (`_maybe_skipped`): the path
    # that skips it keeps the old ones. Found by the S144-Q-108 verifier:
    # evaluation order moved such a walrus ahead of the read that needs the
    # old alias (an assignment value, an earlier dict pair).
    ("a walrus after `and` may not run, so a later read keeps the old alias",
     "def f(url, c):\n    m = []\n    a = m\n    g(c and (m := []), (n := m))\n"
     "    n.append(url)\n    raise E(a)\n", True),
    ("a walrus after `or` may not run, so a later read keeps the old alias",
     "def f(url, c):\n    m = []\n    a = m\n    g(c or (m := []), (n := m))\n"
     "    n.append(url)\n    raise E(a)\n", True),
    ("a walrus in a conditional arm may not run",
     "def f(url, c):\n    m = []\n    a = m\n    g((m := []) if c else 0, (n := m))\n"
     "    n.append(url)\n    raise E(a)\n", True),
    ("a walrus in a comprehension may not run",
     "def f(url, xs):\n    m = []\n    a = m\n    g([(m := x) for x in xs], (n := m))\n"
     "    n.append(url)\n    raise E(a)\n", True),
    ("a walrus in an assert message may not run",
     "def f(url, c):\n    m = []\n    a = m\n    assert c, (m := [])\n    n = m\n"
     "    n.append(url)\n    raise E(a)\n", True),
    ("a walrus that may not run in an assignment value",
     "def f(url, c):\n    m = []\n    a = m\n    d = {}\n"
     "    d[id(n := m)] = (c.append(c) and (m := []))\n    n.append(url)\n    raise E(a)\n",
     True),
    ("a walrus that may not run in an earlier dict pair",
     "def f(url, c):\n    m = []\n    a = m\n"
     "    g({1: (c.append(c) and (m := [])), id(n := m): 0})\n    n.append(url)\n"
     "    raise E(a)\n", True),
    ("a walrus in the first operand of `and` always runs",
     "def f(url, c):\n    m = []\n    a = m\n    g((m := []) and c, (n := m))\n"
     "    n.append(url)\n    raise E(a)\n", False),
    ("a walrus in a conditional test always runs",
     "def f(url, c):\n    m = []\n    a = m\n    g(0 if (m := []) else 1, (n := m))\n"
     "    n.append(url)\n    raise E(a)\n", False),
    ("a walrus past the first link of a chained comparison may not run",
     "def f(url, c, d):\n    m = []\n    a = m\n    g(c < d < (m := []), (n := m))\n"
     "    n.append(url)\n    raise E(a)\n", True),
    ("a walrus in the first link of a chained comparison always runs",
     "def f(url, c, d):\n    m = []\n    a = m\n    g(c < (m := []) < d, (n := m))\n"
     "    n.append(url)\n    raise E(a)\n", False),
    # Decorators run before a def's defaults or a class's bases, and
    # positional defaults before keyword-only ones (`_def_parts`,
    # `_eval_children`). A fill between walruses that end and restore its
    # alias reaches the old source on the first pass.
    ("a decorator fill runs before a default's walrus",
     "def f(url, n):\n    m = []\n    a = m\n    @deco(a.append(url))\n"
     "    def h(z=(a := n)):\n        pass\n    raise E(m)\n", True),
    ("a decorator fill runs before a base's walrus",
     "def f(url, n):\n    m = []\n    a = m\n    @deco(a.append(url))\n"
     "    class K(base((a := n))):\n        pass\n    raise E(m)\n", True),
    ("a positional default fill runs before a keyword-only default's walrus",
     "def f(url, n):\n    m = []\n    a = m\n"
     "    def h(x=a.append(url), *, z=(a := n)):\n        pass\n    raise E(m)\n", True),
    ("a lambda positional default fill runs before a keyword-only default's walrus",
     "def f(url, n):\n    m = []\n    a = m\n"
     "    h = lambda x=a.append(url), *, z=(a := n): 0\n    raise E(m)\n", True),
    ("a default fill between walruses that end and restore its alias",
     "def f(url, n):\n    m = []\n    a = m\n"
     "    def h(x=a.append(url), y=(a := m), *, z=(a := n)):\n        pass\n"
     "    raise E(m)\n", True),
    ("a decorator fill between walruses that end and restore its alias",
     "def f(url, n):\n    m = []\n    a = m\n    @deco(a.append(url), (a := m))\n"
     "    def h(z=(a := n)):\n        pass\n    raise E(m)\n", True),
    # A def body reads the enclosing marks through the names it holds
    # (`_readable`), and a parameter hides the enclosing name
    # (`_shadow_aliases`); a chain through a name it cannot see is kept
    # (`_readable`: its whole closure) or bridged (`_shadow_aliases`).
    # Evaluation order and a walrus that may not run leave more such
    # chains than binding every walrus first did (verifier round 3).
    ("a def body fills a name three links from the target",
     "def f(url):\n    m = []\n    a = m\n    x = a\n    b = x\n"
     "    def inner():\n        b.append(url)\n    inner()\n    raise E(m)\n", True),
    ("a def body fills a name reaching the target through a name it does not read",
     "def f(url):\n    m = []\n    a = m\n    b = m\n    g((k := (m := a)))\n"
     "    def inner():\n        b.append(url)\n    inner()\n    raise E(k)\n", True),
    ("a def body fills a name aliased through one a walrus may re-bind",
     "def f(url, c):\n    m = []\n    k = []\n    a = m\n    b = a\n    g(c and (a := k))\n"
     "    def inner():\n        b.append(url)\n    inner()\n    raise E(m)\n", True),
    ("a def body fills a name aliased through one its parameter hides",
     "def f(url):\n    m = []\n    a = m\n    b = a\n"
     "    def inner(a):\n        b.append(url)\n    inner(0)\n    raise E(m)\n", True),
    ("a parameter hiding an alias does not alias it to itself",
     "def f(url):\n    m = []\n    a = m\n    b = []\n"
     "    def inner(a):\n        b.append(url)\n    inner(0)\n    raise E(m)\n", False),
    # Here every other mark the statement makes is already there, so the
    # first pass ends on the state it began with; the receiver's aliases
    # are read before its arguments (S144-Q-110), so that pass fills `m`.
    ("a receiver fill between walruses that end and restore its alias",
     "def f(url):\n    m = []\n    n = []\n    n.append(url)\n    a = n\n"
     "    a.append(url)\n    g((a := m))\n"
     "    g(a.append((a := n) and url), (a := m))\n    raise E(m)\n", True),
    # S144-Q-110: a call's receiver is read before its arguments, so a
    # mutator fills the object its receiver named then, though a walrus in
    # the arguments re-binds the name (`_bind_in_order`: `_PreCall`).
    ("a receiver is filled though a walrus in its arguments re-binds it",
     "def f(url):\n    m = []\n    n = []\n    a = m\n"
     "    a.append((a := n) or url)\n    raise E(m)\n", True),
    ("a walrus in a receiver's arguments does not make it fill the new object",
     "def f(url):\n    m = []\n    n = []\n    a = m\n"
     "    a.append((a := n) or url)\n    raise E(n)\n", False),
    ("a receiver re-bound by an earlier walrus is filled though a later one re-binds it",
     "def f(url):\n    m = []\n    n = []\n    a = n\n"
     "    g((a := m), a.append((a := n) or url))\n    raise E(m)\n", True),
    ("a walrus receiver is filled though a walrus in its arguments re-binds it",
     "def f(url):\n    m = []\n    n = []\n    a = m\n"
     "    (a := m).append((a := n) or url)\n    raise E(m)\n", True),
    ("a walrus receiver's arguments do not make it fill the new object",
     "def f(url):\n    m = []\n    n = []\n    a = m\n"
     "    (a := m).append((a := n) or url)\n    raise E(n)\n", False),
    # A re-pass reads a container a later call fills into an earlier one
    # (`g(b.append(k), k.append(url))`: `b` holds `k`); the receiver is
    # still the object it named on the first pass, not where the
    # statement left the name.
    ("a container filled later reaches the old object of an earlier receiver",
     "def f(url):\n    m = []\n    k = []\n    b = m\n"
     "    g(b.append(k), (b := []), k.append(url))\n    raise E(m)\n", True),
    # A `setattr` object or a helper destination is read before the later
    # arguments too, also on a first pass that adds nothing and ends on
    # the state it began with (S144-Q-110 verifier).
    ("a setattr object re-bound by a later argument is filled at its old object",
     "def f(url, c):\n    z = C()\n    a = z\n    n = [url]\n    g(c or (a := url + ''))\n"
     "    g(setattr(a, 'u', (a := n) or url))\n    raise E(z)\n", True),
    ("a helper destination re-bound by a later argument is filled at its old object",
     "def h(q, x):\n    q.append(x)\ndef f(url):\n    m = []\n    n = []\n    a = m\n"
     "    h(a, (a := n) or url)\n    raise E(m)\n", True),
    ("a keyword helper destination re-bound by a later keyword is filled at its old object",
     "def h(q, x):\n    q.append(x)\ndef f(url):\n    m = []\n    n = []\n    a = m\n"
     "    h(q=a, x=(a := n) or url)\n    raise E(m)\n", True),
    ("a walrus in a later argument does not make a helper fill the new object",
     "def h(q, x):\n    q.append(x)\ndef f(url):\n    m = []\n    n = []\n    a = m\n"
     "    h(a, (a := n) or url)\n    raise E(n)\n", False),
    ("a setattr object re-bound and restored by later arguments",
     "def f(url, c):\n    z = C()\n    a = z\n    n = [url]\n    g(c or (a := url + ''))\n"
     "    g(setattr(a, 'u', (a := n) or url), (a := z))\n    raise E(z)\n", True),
    ("a helper destination re-bound and restored by later arguments",
     "def h(q, x):\n    q.append(x)\ndef f(url, c):\n    z = []\n    a = z\n    n = [url]\n"
     "    g(c or (a := url + ''))\n    g(h(a, (a := n) or url), (a := z))\n    raise E(z)\n",
     True),
    # S144-Q-114: a walrus hands back the object it binds, so a fill off one
    # reaches what it was bound from (`_chain_root`).
    ("a walrus receiver fills the object it was bound from",
     "def f(url):\n    m = []\n    a = m\n    (t := a).append(url)\n    raise E(m)\n", True),
    ("a walrus setattr object fills the object it was bound from",
     "def f(url):\n    m = C()\n    a = m\n    setattr((t := a), 'u', url)\n    raise E(m)\n",
     True),
    ("a walrus helper destination fills the object it was bound from",
     "def h(q, x):\n    q.append(x)\ndef f(url):\n    m = []\n    a = m\n"
     "    h((t := a), url)\n    raise E(m)\n", True),
    ("a walrus receiver in an outer receiver's arguments fills its own object",
     "def f(url):\n    m = []\n    a = m\n    t = []\n    t.append((t := a).append(url))\n"
     "    raise E(m)\n", True),
    ("a walrus receiver bound to a new object does not fill an old one",
     "def f(url):\n    m = []\n    a = m\n    (a := []).append(url)\n    raise E(m)\n", False),
    # S144-Q-113 (c): an object stored into a container is a part of it,
    # so a value put into the object later is in the container
    # (`_held_marks`); a value put into the container does not reach it.
    ("an appended object filled later is in its container",
     "def f(url):\n    a = []\n    k = []\n    a.append(k)\n    k.append(url)\n    raise E(a)\n",
     True),
    ("an inserted object filled later is in its container",
     "def f(url):\n    a = []\n    k = []\n    a.insert(0, k)\n    k.append(url)\n    raise E(a)\n",
     True),
    ("a setdefault object filled later is in its dict",
     "def f(url):\n    a = {}\n    k = []\n    a.setdefault('x', k)\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("an added object given an attribute later is in its set",
     "def f(url):\n    a = set()\n    k = C()\n    a.add(k)\n    k.u = url\n"
     "    raise E(a)\n", True),
    ("an element store holds an object filled later",
     "def f(url):\n    a = {}\n    k = []\n    a['x'] = k\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("an attribute store holds an object filled later",
     "def f(url):\n    a = C()\n    k = []\n    a.x = k\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a self attribute store holds an object filled later",
     "class C:\n    def f(self, url):\n        k = []\n        self.q = k\n        k.append(url)\n"
     "        raise E(self)\n", True),
    ("a setattr store holds an object filled later",
     "def f(url):\n    a = C()\n    k = []\n    setattr(a, 'x', k)\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a paired tuple store holds an object filled later",
     "def f(url):\n    a = C()\n    k = []\n    a.x, b = k, []\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a list display holds an object filled later",
     "def f(url):\n    k = []\n    a = [k]\n    k.append(url)\n    raise E(a)\n", True),
    ("a nested dict display holds an object filled later",
     "def f(url):\n    k = []\n    a = {'x': [k]}\n    k.append(url)\n    raise E(a)\n", True),
    ("an in-place += display holds an object filled later",
     "def f(url):\n    a = []\n    k = []\n    a += [k]\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a mutating helper's destination holds its source filled later",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    a = []\n    k = []\n    h(a, k)\n"
     "    k.append(url)\n    raise E(a)\n", True),
    ("a mutating method's receiver holds its source filled later",
     "class C:\n    def __init__(self):\n        self.q = []\n    def h(self, v):\n"
     "        self.q.append(v)\n    def f(self, url):\n        k = []\n        self.h(k)\n"
     "        k.append(url)\n        raise E(self)\n", True),
    ("a helper that stores a local then fills it mutates its parameter",
     "def w(q, v):\n    k = []\n    q.append(k)\n    k.append(v)\ndef f(url):\n    a = []\n"
     "    w(a, url)\n    raise E(a)\n", True),
    ("an object held two levels down filled later",
     "def f(url):\n    a = []\n    b = []\n    k = []\n    a.append(b)\n    b.append(k)\n"
     "    k.append(url)\n    raise E(a)\n", True),
    ("an alias of a held object filled later",
     "def f(url):\n    a = []\n    k = []\n    a.append(k)\n    j = k\n    j.append(url)\n"
     "    raise E(a)\n", True),
    ("an object appended through a container alias filled later",
     "def f(url):\n    a = []\n    b = a\n    k = []\n    b.append(k)\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("an object held by a container that is then re-bound still reaches its alias",
     "def f(url):\n    a = []\n    k = []\n    a.append(k)\n    b = a\n    a = []\n"
     "    k.append(url)\n    raise E(b)\n", True),
    ("an object appended under a walrus is filled through the walrus name",
     "def f(url):\n    a = []\n    k = []\n    a.append((j := k))\n    j.append(url)\n"
     "    raise E(a)\n", True),
    ("a new object appended under a walrus is filled through the walrus name",
     "def f(url):\n    a = []\n    a.append((j := []))\n    j.append(url)\n    raise E(a)\n", True),
    ("a display in a conditional arm appended holds an object filled later",
     "def f(url):\n    a = []\n    k = []\n    a.append([k] if k is not None else [])\n"
     "    k.append(url)\n    raise E(a)\n", True),
    ("a display in an and operand appended holds an object filled later",
     "def f(url):\n    a = []\n    k = []\n    a.append(k is not None and [k])\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a name bound to a conditional display holds an object filled later",
     "def f(url):\n    k = []\n    a = [k] if k is not None else []\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a name bound to an or display holds an object filled later",
     "def f(url):\n    k = []\n    a = [] or [k]\n    k.append(url)\n    raise E(a)\n", True),
    ("a name bound to a walrus display holds an object filled later",
     "def f(url):\n    k = []\n    a = (j := [k])\n    k.append(url)\n    raise E(a)\n", True),
    ("a container re-bound to a display of itself still holds its old parts",
     "def f(url):\n    a = []\n    k = []\n    a.append(k)\n    a = [a]\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a store of a name the same binding re-binds holds the old object",
     "def f(url):\n    d = C()\n    a = []\n    d.x, a = a, []\n    a.append(url)\n"
     "    raise E(d)\n", False),
    ("a new display appended under a walrus holds an object filled later",
     "def f(url):\n    a = []\n    k = []\n    a.append((j := [k]))\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("an else arm display appended holds an object filled later",
     "def f(url):\n    a = []\n    k = []\n    a.append([] if k is None else [k])\n"
     "    k.append(url)\n    raise E(a)\n", True),
    ("a first or operand display appended holds an object filled later",
     "def f(url):\n    a = []\n    k = []\n    a.append([k] or [])\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a name bound to an else arm display holds an object filled later",
     "def f(url):\n    k = []\n    a = [] if k is None else [k]\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a name bound to a first or operand display holds an object filled later",
     "def f(url):\n    k = []\n    a = [k] or []\n    k.append(url)\n    raise E(a)\n", True),
    ("a dict key given an attribute later is in its dict",
     "def f(url):\n    k = C()\n    a = {k: 1}\n    k.u = url\n    raise E(a)\n", True),
    ("a keyword argument stored by update is in its dict",
     "def f(url):\n    a = {}\n    k = []\n    a.update(x=k)\n    k.append(url)\n    raise E(a)\n",
     True),
    ("an unpacked part stored on an attribute holds an object filled later",
     "def f(url):\n    a = C()\n    k = []\n    p = [k, []]\n    a.x, b = p\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a store into a name an earlier target re-bound fills the new object",
     "def f(url):\n    k = []\n    a, a.x = C(), k\n    k.append(url)\n    raise E(a)\n", True),
    ("a store into a name a later target re-binds fills the old object",
     "def f(url):\n    a = C()\n    k = []\n    a.x, a = k, C()\n    k.append(url)\n"
     "    raise E(a)\n", False),
    ("a part appended and then filled is in the container",
     "def f(url):\n    k = C()\n    k.q = []\n    a = []\n    a.append(k.q)\n    k.q.append(url)\n"
     "    raise E(a)\n", True),
    ("a nested list display holds an object filled later",
     "def f(url):\n    k = []\n    a = [[k]]\n    k.append(url)\n    raise E(a)\n", True),
    ("a tuple display holds an object filled later",
     "def f(url):\n    k = []\n    a = (k,)\n    k.append(url)\n    raise E(a)\n", True),
    ("a set display holds an object given an attribute later",
     "def f(url):\n    k = C()\n    a = {k}\n    k.u = url\n    raise E(a)\n", True),
    ("a middle or operand display holds an object filled later",
     "def f(url):\n    k = []\n    a = [] or [k] or []\n    k.append(url)\n    raise E(a)\n", True),
    ("a starred attribute target of a paired value holds an object filled later",
     "def f(url):\n    a = C()\n    k = []\n    *a.x, b = k, []\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a starred attribute target of an unpacked name holds an object filled later",
     "def f(url):\n    a = C()\n    k = []\n    p = [k, []]\n    *a.x, b = p\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a nested attribute target of an unpacked name holds an object filled later",
     "def f(url):\n    a = C()\n    k = []\n    p = [[k, 1], 2]\n    (a.x, c), b = p\n"
     "    k.append(url)\n    raise E(a)\n", True),
    ("an unpacked store into a name an earlier target re-bound fills the new object",
     "def f(url):\n    k = []\n    p = [C(), k]\n    a, a.x = p\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("an unpacked store into a name a later target re-binds fills the old object",
     "def f(url):\n    o = C()\n    a = o\n    k = []\n    p = [k, C()]\n    a.x, a = p\n"
     "    k.append(url)\n    raise E(o)\n", True),
    ("a chained store into a name the first target re-bound leaves the old object",
     "def f(url):\n    o = C()\n    a = o\n    k = C()\n    a = a.x = k\n    k.u = url\n"
     "    raise E(o)\n", False),
    ("an in-place += of a name copies items, not the object filled later",
     "def f(url):\n    a = []\n    k = []\n    a += k\n    k.append(url)\n    raise E(a)\n", False),
    ("a helper destination holds only its source argument",
     "def h(q, v, w):\n    q.append(v)\ndef f(url):\n    a = []\n    k = []\n    j = []\n"
     "    h(a, k, j)\n    j.append(url)\n    raise E(a)\n", False),
    ("an object appended to an attribute container is in its root",
     "def f(url):\n    a = C()\n    a.items = []\n    k = []\n    a.items.append(k)\n"
     "    k.append(url)\n    raise E(a)\n", True),
    ("a dict key stored by setdefault is in its dict",
     "def f(url):\n    d = {}\n    k = C()\n    d.setdefault(k, None)\n    k.u = url\n"
     "    raise E(d)\n", True),
    ("an in-place += of a name holds the objects that name holds",
     "def f(url):\n    k2 = []\n    k = [k2]\n    a = C()\n    a.x = []\n    a.x += k\n"
     "    k2.append(url)\n    raise E(a)\n", True),
    ("a helper storing its starred parameter holds every later argument",
     "def h(q, *vs):\n    q.extend(vs)\ndef f(url):\n    a = []\n    k = []\n    j = []\n"
     "    h(a, k, j)\n    j.append(url)\n    raise E(a)\n", True),
    ("a middle or operand display appended holds an object filled later",
     "def f(url):\n    a = []\n    k = []\n    a.append([] or [k] or [])\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a list-shaped target store holds an object filled later",
     "def f(url):\n    a = C()\n    k = []\n    [a.x, b] = k, []\n    k.append(url)\n"
     "    raise E(a)\n", True),
    ("a nested list target store of an unpacked name holds an object filled later",
     "def f(url):\n    a = C()\n    k = []\n    p = [[k, 1], 2]\n    [a.x, c], b = p\n"
     "    k.append(url)\n    raise E(a)\n", True),
    ("a list display value is paired element by element",
     "def f(url):\n    a = C()\n    k = []\n    n = []\n    a.x, b = [n, k]\n    k.append(url)\n"
     "    raise E(a)\n", False),
    ("a display of a name the binding re-binds holds the old object",
     "def f(url):\n    k = []\n    j = k\n    b, k = [k], []\n    j.append(url)\n    raise E(b)\n",
     True),
    ("a display of a name the binding re-binds does not hold the new object",
     "def f(url):\n    k = []\n    b, k = [k], []\n    k.append(url)\n    raise E(b)\n", False),
    ("a helper with several destinations holds its source in each",
     "def h(v, *qs):\n    qs[1].append(v)\ndef f(url):\n    a = []\n    b = []\n    k = []\n"
     "    h(k, a, b)\n    k.append(url)\n    raise E(b)\n", True),
    ("a container appended to itself is not reached through a re-bound name",
     "def f(url):\n    a = []\n    a.append(a)\n    b = a\n    a = []\n    b.append(url)\n"
     "    raise E(a)\n", False),
    ("a comprehension target appended is not the enclosing name",
     "def f(url, xs):\n    x = []\n    a = []\n    [a.append(x) for x in xs]\n    x.append(url)\n"
     "    raise E(a)\n", False),
    ("an object held by a module container filled in a function",
     "G = []\ndef f(url):\n    k = []\n    G.append(k)\n    k.append(url)\ndef g():\n"
     "    log.info(G)\n", True),
    ("an object appended in a loop filled later in the body",
     "def f(url, xs):\n    a = []\n    for x in xs:\n        k = []\n        a.append(k)\n"
     "        k.append(url)\n    raise E(a)\n", True),
    ("a held object re-bound before the fill is not in the container",
     "def f(url):\n    a = []\n    k = []\n    a.append(k)\n    k = []\n    k.append(url)\n"
     "    raise E(a)\n", False),
    ("a held object re-bound by a later walrus in the statement is not filled",
     "def f(url):\n    a = []\n    k = []\n    g(a.append(k), (k := []))\n    k.append(url)\n"
     "    raise E(a)\n", False),
    ("a value put into a container does not reach the object it holds",
     "def f(url):\n    k = []\n    a = [k]\n    a.append(url)\n    raise E(k)\n", False),
    ("a container re-bound before the fill holds nothing",
     "def f(url):\n    a = []\n    k = []\n    a.append(k)\n    a = []\n    k.append(url)\n"
     "    raise E(a)\n", False),
    ("a slice copy appended is not the object filled later",
     "def f(url):\n    a = []\n    k = []\n    a.append(k[:])\n    k.append(url)\n    raise E(a)\n",
     False),
    ("a call over an object appended is not the object filled later",
     "def f(url):\n    a = []\n    k = []\n    a.append(len(k))\n    k.append(url)\n"
     "    raise E(a)\n", False),
    ("a copy built by a call holds nothing filled later",
     "def f(url):\n    k = []\n    a = list(k)\n    k.append(url)\n    raise E(a)\n", False),
    ("a paired tuple store holds only its own element",
     "def f(url):\n    a = C()\n    k = []\n    n = []\n    a.x, b = n, k\n    k.append(url)\n"
     "    raise E(a)\n", False),
    # Every binding form re-binds the name, not only `=`, and a lambda's
    # parameters and a comprehension's targets are its own names.
    ("a for target re-binding an alias does not fill its source",
     "def f(url, xs):\n    m = []\n    a = m\n    for a in xs:\n        a.append(url)\n"
     "    raise E(m)\n", False),
    ("an async for target re-binding an alias does not fill its source",
     "async def f(url, xs):\n    m = []\n    a = m\n    async for a in xs:\n"
     "        a.append(url)\n    raise E(m)\n", False),
    ("a with target re-binding an alias does not fill its source",
     "def f(url):\n    m = []\n    a = m\n    with g() as a:\n        a.append(url)\n"
     "    raise E(m)\n", False),
    ("an except target re-binding an alias does not fill its source",
     "def f(url):\n    m = []\n    a = m\n    try:\n        g()\n    except E as a:\n"
     "        a.append(url)\n    raise E(m)\n", False),
    ("an import re-binding an alias does not fill its source",
     "def f(url):\n    m = []\n    a = m\n    import a\n    a.append(url)\n    raise E(m)\n",
     False),
    ("a walrus re-binding an alias does not fill its source",
     "def f(url):\n    m = []\n    a = m\n    if (a := []):\n        a.append(url)\n"
     "    raise E(m)\n", False),
    ("a def re-binding an alias name does not fill its source",
     "def f(url):\n    m = []\n    a = m\n    def a():\n        pass\n    a.x = url\n"
     "    raise E(m)\n", False),
    ("a class re-binding an alias name does not fill its source",
     "def f(url):\n    m = []\n    a = m\n    class a:\n        pass\n    a.x = url\n"
     "    raise E(m)\n", False),
    ("a match capture re-binding an alias does not fill its source",
     "def f(url, v):\n    m = []\n    a = m\n    match v:\n        case a:\n"
     "            a.append(url)\n    raise E(m)\n", False),
    ("a type statement re-binding an alias does not fill its source",
     "def f(url):\n    m = []\n    a = m\n    type a = int\n    a.append(url)\n    raise E(m)\n",
     False),
    ("a comprehension target shadowing an alias does not fill its source",
     "def f(url, xs):\n    m = []\n    a = m\n    [a.append(url) for a in xs]\n    raise E(m)\n",
     False),
    ("a module comprehension target shadowing an alias",
     "a = m\nr = [a.append(url) for a in xs]\nraise E(m)\n", False),
    ("a generator target shadowing an alias does not fill its source",
     "def f(url, xs):\n    m = []\n    a = m\n    list(a.append(url) for a in xs)\n"
     "    raise E(m)\n", False),
    ("a lambda parameter shadowing an alias does not fill its source",
     "def f(url):\n    m = []\n    a = m\n    g = lambda a: a.append(url)\n    raise E(m)\n",
     False),
    ("a module lambda parameter shadowing an alias",
     "a = m\nf = lambda a: a.append(url)\nraise E(m)\n", False),
    ("an alias a re-binding ended is not read back by a lambda",
     "def f(url):\n    m = []\n    a = m\n    a = []\n    g = lambda: a.append(url)\n"
     "    raise E(m)\n", False),
    ("a lambda filling an alias it reads freely",
     "def f(url):\n    m = []\n    a = m\n    g = lambda: a.append(url)\n    g()\n    raise E(m)\n",
     True),
    ("a store through object.__setattr__ does not taint object",
     "def f(url):\n    o = C()\n    object.__setattr__(o, 'x', url)\n    p = object()\n"
     "    raise E(p)\n", False),
    ("a bound __setitem__ does not taint its key",
     "def f(url):\n    k = 'x'\n    d = {}\n    d.__setitem__(k, url)\n    raise E(k)\n", False),
    ("a store through a base class __setattr__ does not taint the class",
     "def f(url):\n    o = C()\n    Base.__setattr__(o, 'x', url)\n    raise E(Base)\n", False),
    ("a store through a base class __setattr__ taints the object",
     "class C(Base):\n    def h(self, url):\n        Base.__setattr__(self, 'u', url)\n"
     "        raise E(self)\n", True),
    ("an unbound __setitem__ off a non-builtin class does not taint it",
     "def f(url):\n    d = OrderedDict()\n    OrderedDict.__setitem__(d, 'k', url)\n"
     "    raise E(OrderedDict)\n", False),
    # `+=` by anything but a container display may re-bind the name to a new
    # str / int, leaving an alias of the old object alone.
    ("a string built by += through an alias does not taint the source",
     "def f(url, base):\n    msg = base\n    msg += url\n    log.info('%s', base)\n", False),
    ("an attribute read out and built by += does not taint its object",
     "class C:\n    def h(self, url):\n        s = self.base\n        s += url\n"
     "        log.info('%s', self)\n", False),
    ("a count built by += through an alias does not flow out",
     "def g(n, url):\n    k = n\n    k += len(url)\ndef f(n):\n    raise E(n)\n", False),
    ("a template filled by %= through an alias does not taint the source",
     "T = 'see %(u)s'\ndef f(url):\n    msg = T\n    msg %= {'u': url}\n"
     "    log.info('%s', T)\n", False),
    ("a repeat by *= through an alias does not taint the source",
     "def f(url, n):\n    k = n\n    k *= [url]\n    raise E(n)\n", False),
    ("a set difference through an alias puts nothing in",
     "def f(url):\n    m = set()\n    a = m\n    a -= {url}\n    raise E(m)\n", False),
    ("a set filled by |= through an alias",
     "def f(url):\n    m = set()\n    a = m\n    a |= {url}\n    raise E(m)\n", True),
    ("a set filled by ^= through an alias",
     "def f(url):\n    m = set()\n    a = m\n    a ^= {url}\n    raise E(m)\n", True),
    ("a name re-bound to a part of itself still reaches the old object",
     "def f(url):\n    m = []\n    a = m\n    a = a[0]\n    a.append(url)\n    raise E(m)\n",
     True),
    # A store into the whole REPLACES a part, so a part read out before it
    # is not changed (the shape of a real module-level state dict).
    ("an element read out is not changed by a store into its container",
     "def f(url):\n    d = {}\n    x = d['k']\n    d['k'] = url\n    raise E(x)\n", False),
    ("a prior value read out of a state dict does not make a sink parameter",
     "S = {}\ndef h(state):\n    prev = S['p']\n    S['p'] = state.get('x')\n"
     "    log.info(prev)\ndef f(url):\n    h(url)\n", False),
    ("a part read out and then filled in place reaches its container",
     "def f(url):\n    d = {}\n    x = d['k']\n    x.append(url)\n    raise E(d)\n", True),
    # RM-1563 wrappers stored on an attribute from outside the class body.
    # Only a store off `self` is known to land on an instance, where a
    # function binds nothing. Off any other receiver it may land on a class
    # (`C.g = lambda self, m: ...`), where a function binds `self` off an
    # instance, so a plain function is read both ways; a staticmethod still
    # binds nothing, and a classmethod stored off a non-`self` receiver
    # always binds its first parameter.
    ("lambda stored on a class from outside, called off an instance",
     "class C:\n    pass\nC.g = lambda self, m: log.info(m)\ndef f(url):\n"
     "    C().g(url)\n", True),
    ("lambda stored on a class from outside, called off self",
     "class C:\n    def h(self, url):\n        self.g(url)\n"
     "C.g = lambda self, m: log.info(m)\n", True),
    ("module wrapper stored on a class from outside",
     "def g(s, m):\n    log.info(m)\nclass C:\n    pass\nC.h = g\ndef f(o, url):\n"
     "    o.h(url)\n", True),
    ("classmethod lambda stored on a class from outside",
     "class C:\n    pass\nC.g = classmethod(lambda cls, m: log.info(m))\n"
     "def f(url):\n    C.g(url)\n", True),
    ("lambda stored on cls in a classmethod",
     "class C:\n    @classmethod\n    def setup(cls):\n"
     "        cls.g = lambda self, m: log.info(m)\n    def h(self, url):\n"
     "        self.g(url)\n", True),
    ("conditional method wrapper stored on a class from outside",
     "class C:\n    pass\nC.g = (lambda self, m: log.info(m)) if c else fetch\n"
     "def f(url):\n    C().g(url)\n", True),
    ("lambda stored on another object, called off it",
     "def f(o, url):\n    o.g = lambda m: log.info(m)\n    o.g(url)\n", True),
    ("lambda stored on another object, called off self",
     "class C:\n    def setup(self, o):\n        o.g = lambda m: log.info(m)\n"
     "    def h(self, url):\n        self.g(url)\n", True),
    # ... and the kinds a store DOES know keep their positions.
    ("staticmethod stored on a class from outside keeps its positions",
     "class C:\n    pass\nC.g = staticmethod(lambda m, n: log.info(n))\n"
     "def f(url):\n    C().g(url, 'x')\n", False),
    ("classmethod stored on a class from outside keeps the shift",
     "class C:\n    pass\nC.g = classmethod(lambda cls, m, n: log.info(m))\n"
     "def f(url):\n    C.g('x', url)\n", False),
    ("lambda stored on self keeps its positions",
     "class C:\n    def __init__(self):\n        self.g = lambda m, n: log.info(n)\n"
     "    def h(self, url):\n        self.g(url, 'x')\n", False),
    ("lambda stored on a class from outside, called with a sanitized value",
     "class C:\n    pass\nC.g = lambda self, m: log.info(m)\ndef f(url):\n"
     "    C().g(_safe_url(url))\n", False),
    # RM-1563 the receiver of a bound call: a call that binds the first
    # parameter binds it from the receiver, so a method that logs `self`
    # called off a receiver that carries the url is a sink for it.
    ("method logging self, called off a tainted instance",
     "class C:\n    def g(self):\n        log.info(self)\n"
     "def f(url):\n    o = C(url)\n    o.g()\n", True),
    ("method logging self, called off an instance built in place",
     "class C:\n    def g(self, m=''):\n        log.info(self)\n"
     "def f(url):\n    C(url).g()\n", True),
    ("method logging a self attribute, called off a tainted instance",
     "class C:\n    def g(self):\n        log.info(self.x)\n"
     "def f(url):\n    o = C(url)\n    o.g()\n", True),
    ("self.g() reached through a tainted self",
     "class C:\n    def g(self):\n        log.info(self)\n"
     "    def h(self):\n        self.g()\ndef f(url):\n    C.h(url)\n", True),
    ("star-args method, called off a tainted instance",
     "class C:\n    def g(*a):\n        log.info(a)\n"
     "def f(url):\n    o = C(url)\n    o.g()\n", True),
    ("lambda stored on a class from outside, called off a tainted instance",
     "class C:\n    pass\nC.g = lambda self: log.info(self)\n"
     "def f(url):\n    o = C(url)\n    o.g()\n", True),
    # ... and a receiver binds nothing it does not reach.
    ("classmethod logging cls, called off a tainted instance",
     "class C:\n    @classmethod\n    def g(cls):\n        log.info(cls)\n"
     "def f(url):\n    o = C(url)\n    o.g()\n", False),
    ("staticmethod, called off a tainted instance",
     "class C:\n    @staticmethod\n    def g(m=''):\n        log.info(m)\n"
     "def f(url):\n    o = C(url)\n    o.g()\n", False),
    ("method logging only its argument, called off a tainted instance",
     "class C:\n    def g(self, m):\n        log.info(m)\n"
     "def f(url):\n    o = C(url)\n    o.g('x')\n", False),
    ("star-args after self, called off a tainted instance",
     "class C:\n    def g(self, *a):\n        log.info(a)\n"
     "def f(url):\n    o = C(url)\n    o.g('x')\n", False),
    ("method logging self, called off a sanitized instance",
     "class C:\n    def g(self):\n        log.info(self)\n"
     "def f(url):\n    o = C(_safe_url(url))\n    o.g()\n", False),
    # RM-1789: a def's or class's decorators, defaults, annotations, bases
    # and keywords, and an except handler's type, run where the statement
    # stands, so a walrus or mutator in one binds the enclosing scope.
    ("mutator in a nested def's decorator",
     "def f(url):\n    q = []\n    @q.append(url) or deco\n    def h():\n"
     "        pass\n    log.info(q)\n", True),
    ("mutator in a nested def's parameter default",
     "def f(url):\n    q = []\n    def h(x=q.append(url)):\n        pass\n"
     "    log.info(q)\n", True),
    ("mutator in a nested def's keyword-only default",
     "def f(url):\n    q = []\n    def h(*, x=q.append(url)):\n        pass\n"
     "    log.info(q)\n", True),
    ("mutator in a nested def's annotation",
     "def f(url):\n    q = []\n    def h(x: q.append(url)):\n        pass\n"
     "    log.info(q)\n", True),
    ("mutator in a nested def's return annotation",
     "def f(url):\n    q = []\n    def h() -> q.append(url):\n        pass\n"
     "    log.info(q)\n", True),
    ("mutator in a nested async def's default",
     "async def f(url):\n    q = []\n    async def h(x=q.append(url)):\n"
     "        pass\n    log.info(q)\n", True),
    ("mutator in a nested def's default, logged in its body",
     "def f(url):\n    q = []\n    def h(x=q.append(url)):\n"
     "        log.info(q)\n", True),
    ("mutator in a class decorator",
     "def f(url):\n    q = []\n    @q.append(url) or deco\n    class C:\n"
     "        pass\n    log.info(q)\n", True),
    ("mutator in a class base",
     "def f(url):\n    q = []\n    class C(q.append(url) or object):\n"
     "        pass\n    log.info(q)\n", True),
    ("mutator in a class keyword",
     "def f(url):\n    q = []\n    class C(metaclass=q.append(url) or type):\n"
     "        pass\n    log.info(q)\n", True),
    ("walrus in a nested def's default",
     "def f(url):\n    def h(x=(m := url)):\n        pass\n    log.info(m)\n", True),
    ("walrus in a nested def's decorator",
     "def f(url):\n    @(m := url) and deco\n    def h():\n        pass\n"
     "    log.info(m)\n", True),
    ("walrus in a class base",
     "def f(url):\n    class C((m := url) and object):\n        pass\n"
     "    log.info(m)\n", True),
    ("mutator in an except type, logged in its body",
     "def f(url):\n    q = []\n    try:\n        g()\n"
     "    except q.append(url) or E:\n        log.info(q)\n", True),
    ("walrus in an except type, logged in a later handler",
     "def f(url):\n    try:\n        g()\n    except (m := url) and E:\n"
     "        pass\n    except F:\n        log.info(m)\n", True),
    ("mutator in an except type, logged in finally",
     "def f(url):\n    q = []\n    try:\n        g()\n"
     "    except q.append(url) or E:\n        pass\n    finally:\n"
     "        log.info(q)\n", True),
    ("mutator in an except type, logged after the try",
     "def f(url):\n    q = []\n    try:\n        g()\n"
     "    except q.append(url) or E:\n        pass\n    log.info(q)\n", True),
    # ... and a clean or sanitized value there binds nothing.
    ("clean mutator in a nested def's default",
     "def f(url):\n    q = []\n    def h(x=q.append('x')):\n        pass\n"
     "    log.info(q)\n", False),
    ("sanitized mutator in a nested def's decorator",
     "def f(url):\n    q = []\n    @q.append(_safe_url(url)) or deco\n"
     "    def h():\n        pass\n    log.info(q)\n", False),
    ("clean mutator in an except type",
     "def f(url):\n    q = []\n    try:\n        g()\n"
     "    except q.append('x') or E:\n        log.info(q)\n", False),
    # RM-1790: a call through a MUTATING helper - a def that puts one
    # parameter's value into the object another names - taints the object
    # the caller passed, as `q.append(url)` does, so a later read of it is a
    # leak: off a plain call, off `self` (the receiver is the first
    # parameter), from a helper defined after its caller, through a chain of
    # helpers, and off a staticmethod / classmethod. The clean rows keep it
    # tied to the value: a clean source, a sanitized one, a helper that
    # stores something else, one that only re-binds its parameter, and a
    # url passed to no source parameter.
    ("helper method mutates self, a later method logs it",
     "class C:\n    def h(self, v):\n        self.q.append(v)\n"
     "    def b(self, url):\n        self.h(url)\n    def c(self):\n"
     "        log.info(self.q)\n", True),
    ("helper method mutates self, the caller logs it",
     "class C:\n    def h(self, v):\n        self.q.append(v)\n"
     "    def b(self, url):\n        self.h(url)\n        log.info(self.q)\n", True),
    ("helper method stores an attribute of self",
     "class C:\n    def h(self, v):\n        self.u = v\n    def b(self, url):\n"
     "        self.h(url)\n    def c(self):\n        log.info(self.u)\n", True),
    ("helper method defined after its caller",
     "class C:\n    def b(self, url):\n        self.h(url)\n    def h(self, v):\n"
     "        self.q.append(v)\n    def c(self):\n        log.info(self.q)\n", True),
    ("helper function mutates a parameter, the caller logs it",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    q = []\n    h(q, url)\n"
     "    log.info(q)\n", True),
    ("helper function called with a keyword source",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    q = []\n    h(q, v=url)\n"
     "    log.info(q)\n", True),
    ("helper function defined after its caller",
     "def f(url):\n    q = []\n    h(q, url)\n    log.info(q)\ndef h(q, v):\n"
     "    q.append(v)\n", True),
    ("helper function reached through another helper",
     "def h(q, v):\n    q.append(v)\ndef h2(q, v):\n    h(q, v)\ndef f(url):\n"
     "    q = []\n    h2(q, url)\n    log.info(q)\n", True),
    ("helper method reached through another method",
     "class C:\n    def h(self, v):\n        self.q.append(v)\n    def h2(self, v):\n"
     "        self.h(v)\n    def b(self, url):\n        self.h2(url)\n"
     "    def c(self):\n        log.info(self.q)\n", True),
    ("helper function mutating through a nested def",
     "def h(q, v):\n    def k():\n        q.append(v)\n    k()\ndef f(url):\n"
     "    q = []\n    h(q, url)\n    log.info(q)\n", True),
    ("staticmethod helper called off self",
     "class C:\n    @staticmethod\n    def h(q, v):\n        q.append(v)\n"
     "    def b(self, url):\n        q = []\n        self.h(q, url)\n"
     "        log.info(q)\n", True),
    ("classmethod helper mutates its class, read off self",
     "class C:\n    @classmethod\n    def h(cls, v):\n        cls.q.append(v)\n"
     "    def b(self, url):\n        self.h(url)\n    def c(self):\n"
     "        log.info(self.q)\n", True),
    # A helper that caches under its url key mutates its cache, not the
    # key: a wrapper that calls it keeps its sink parameter, so the call
    # site that hands the wrapper a url is still flagged.
    ("wrapper calling a helper that caches under its url key",
     "CACHE = {}\ndef fetch(url):\n    body = get(url)\n    CACHE[url] = body\n"
     "    return body\ndef disc(over):\n    fetch(over)\n    log.info(over)\n"
     "def f(args):\n    disc(args.chunk_url)\n", True),
    ("helper method stores a tainted module name into self",
     "G = url\nclass C:\n    def h(self):\n        self.q.append(G)\n"
     "    def b(self):\n        self.h()\n    def c(self):\n        log.info(self.q)\n",
     True),
    ("helper method puts its receiver into a parameter",
     "class C:\n    def h(self, q):\n        q.append(self)\ndef f(url):\n"
     "    o = C(url)\n    q = []\n    o.h(q)\n    log.info(q)\n", True),
    ("helper function called with a clean source",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    q = []\n    h(q, 'x')\n"
     "    log.info(q)\n", False),
    ("helper method called with a clean source",
     "class C:\n    def h(self, v):\n        self.q.append(v)\n"
     "    def b(self, url):\n        self.h('x')\n    def c(self):\n"
     "        log.info(self.q)\n", False),
    ("helper function sanitizes its source",
     "def h(q, v):\n    q.append(_safe_url(v))\ndef f(url):\n    q = []\n"
     "    h(q, url)\n    log.info(q)\n", False),
    ("helper function stores a literal, not its source",
     "def h(q, v):\n    q.append('x')\ndef f(url):\n    q = []\n    h(q, url)\n"
     "    log.info(q)\n", False),
    ("helper function only re-binds its parameter",
     "def h(q, v):\n    q = [v]\ndef f(url):\n    q = []\n    h(q, url)\n"
     "    log.info(q)\n", False),
    ("helper function stores a clean module name whatever is passed",
     "G = 'x'\ndef h(q, v):\n    q.append(G)\ndef f(url):\n    r = []\n    h(r, 'x')\n"
     "    log.info(r)\n", False),
    # RM-1793: a helper that stores an ENCLOSING tainted name into its
    # parameter (`q.append(G)`) taints the object a caller passes whatever
    # the other arguments are: with a clean one, with no other parameter at
    # all, through a wrapper that passes its own parameter on, and off a
    # staticmethod or a dotted receiver. The clean rows keep it tied to the
    # value: a clean enclosing name, a sanitized one, and a helper that only
    # caches it under its parameter (the key is read, not changed).
    ("helper function stores a tainted module name whatever is passed",
     "G = url\ndef h(q, v):\n    q.append(G)\ndef f():\n    r = []\n    h(r, 'x')\n"
     "    log.info(r)\n", True),
    ("one-parameter helper stores a tainted module name",
     "G = url\ndef h(q):\n    q.append(G)\ndef f():\n    r = []\n    h(r)\n"
     "    log.info(r)\n", True),
    ("one-parameter helper reached through a wrapper",
     "G = url\ndef h(q):\n    q.append(G)\ndef w(q):\n    h(q)\ndef f():\n"
     "    r = []\n    w(r)\n    log.info(r)\n", True),
    ("one-parameter helper stores into an attribute of its parameter",
     "G = url\ndef h(o):\n    o.u = G\ndef f():\n    c = C()\n    h(c)\n"
     "    log.info(c)\n", True),
    ("staticmethod helper stores a tainted module name",
     "G = url\nclass C:\n    @staticmethod\n    def h(q):\n        q.append(G)\n"
     "    def b(self):\n        r = []\n        self.h(r)\n        log.info(r)\n",
     True),
    ("helper given an attribute, its object is logged",
     "G = url\ndef h(q):\n    q.append(G)\ndef f(o):\n    h(o.q)\n    log.info(o)\n",
     True),
    ("one-parameter helper stores a clean module name",
     "G = 'x'\ndef h(q):\n    q.append(G)\ndef f():\n    r = []\n    h(r)\n"
     "    log.info(r)\n", False),
    ("one-parameter helper stores a sanitized module name",
     "G = url\ndef h(q):\n    q.append(_safe_url(G))\ndef f():\n    r = []\n"
     "    h(r)\n    log.info(r)\n", False),
    ("one-parameter helper caches a tainted module name under its key",
     "G = url\nCACHE = {}\ndef put(k):\n    CACHE[k] = G\ndef f(name):\n"
     "    put(name)\n    log.info(name)\n", False),
    ("one-parameter helper given an object the caller never logs",
     "G = url\ndef h(q):\n    q.append(G)\ndef f(n):\n    r = []\n    h(r)\n"
     "    log.info(n)\n", False),
    # A method that stores a tainted module name into its own receiver
    # leaves a same-named call off another receiver alone (the mark is
    # keyed by attribute name only, so it would taint `cmd` here).
    ("method stores a tainted module name into self, a same-named call",
     "G = url\nclass C:\n    def run(self):\n        self.u = G\ndef f(cmd):\n"
     "    sp.run(cmd)\n    log.info(cmd)\n", False),
    ("method stores a tainted module name into self, a keyword call",
     "G = url\nclass C:\n    def run(self):\n        self.u = G\ndef f(cmd):\n"
     "    sp.run(self=cmd)\n    log.info(cmd)\n", False),
    ("classmethod stores a tainted module name into cls, a same-named call",
     "G = url\nclass C:\n    @classmethod\n    def run(cls):\n        cls.u = G\n"
     "def f(sp):\n    sp.run()\n    log.info(sp)\n", False),
    ("helper function stores under a key, the key is logged",
     "def put(d, k, v):\n    d[k] = v\ndef f(url, name):\n    c = {}\n"
     "    put(c, name, url)\n    log.info(name)\n", False),
    ("helper given an element whose key is a parameter",
     "def h(q, v):\n    q.append(v)\ndef w(k, url):\n    c = {}\n    h(c[k], url)\n"
     "def f(k):\n    log.info(k)\n", False),
    ("helper function caches a tainted module name under its key",
     "G = url\nCACHE = {}\ndef put(k):\n    CACHE[k] = G\ndef f(name):\n"
     "    put(name)\n    log.info(name)\n", False),
    ("helper function given the url for no source parameter",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    q = []\n    h(v='x', q=q)\n"
     "    log.info(q)\n", False),
    # RM-1792: a value put into a FRESH builtin object (a helper's
    # destination, a mutator's receiver, a store target) is in nothing the
    # constructor's name reaches afterwards, so the name stays clean.
    ("helper given a fresh dict, the dict builtin is logged",
     "def h(q, v):\n    q.append(v)\ndef f(url, x):\n    h(dict(), url)\n"
     "    log.info(isinstance(x, dict))\n", False),
    ("mutator on a fresh dict, the dict builtin is logged",
     "def f(url, x):\n    dict().update(u=url)\n    log.info(isinstance(x, dict))\n",
     False),
    ("mutator on a fresh set, the set builtin is logged",
     "def f(url, x):\n    set().add(url)\n    log.info(isinstance(x, set))\n", False),
    ("helper given a fresh list, the list builtin is logged",
     "def h(q, v):\n    q.append(v)\ndef f(url, x):\n    h(list(), url)\n"
     "    log.info(sorted(x, key=list))\n", False),
    ("store into a fresh list, the list builtin is logged",
     "def f(url, x):\n    list()[0] = url\n    log.info(sorted(x, key=list))\n", False),
    ("mutator deep in a fresh dict chain, the dict builtin is logged",
     "def f(url, x):\n    dict()['k'].append(url)\n    log.info(isinstance(x, dict))\n",
     False),
    # ... but only the bare builtin's NAME is skipped: any other callee may
    # hand back a shared object, a copy's argument shares its elements, and
    # a name the module binds may not be the builtin.
    ("helper given a call result, the same call is logged",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    h(make(), url)\n"
     "    log.info(make())\n", True),
    ("helper mutates an element of a shallow copy",
     "def h(q, v):\n    q[0].append(v)\ndef f(url, r):\n    h(list(r), url)\n"
     "    log.info(r)\n", True),
    ("mutator on a setdefault result",
     "def f(url, d, k):\n    d.setdefault(k, []).append(url)\n    log.info(d)\n", True),
    ("helper given a setdefault result",
     "def h(q, v):\n    q.append(v)\ndef f(url, d, k):\n"
     "    h(d.setdefault(k, []), url)\n    log.info(d)\n", True),
    ("dict re-bound in the scope",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    dict = get_shared\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict re-bound at module level",
     "dict = get_shared\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict bound as a parameter",
     "def h(q, v):\n    q.append(v)\ndef f(url, dict):\n    h(dict(), url)\n"
     "    log.info(dict())\n", True),
    ("dict bound by an import alias",
     "from m import shared as dict\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict possibly bound by a star import",
     "from m import *\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    # ... and a builtin replaced at run time binds no name at all.
    ("dict replaced through the builtins module",
     "import builtins\nbuiltins.dict = get_shared\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict replaced through an alias of the builtins module",
     "import builtins as b\nb.dict = get_shared\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict replaced on a looked-up builtins module",
     "import sys\nsys.modules['builtins'].dict = get_shared\n"
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    h(dict(), url)\n"
     "    log.info(dict())\n", True),
    ("dict replaced through setattr",
     "import b\nsetattr(b.ns, 'dict', get_shared)\n"
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    h(dict(), url)\n"
     "    log.info(dict())\n", True),
    ("dict replaced through a function's globals",
     "g.__globals__['dict'] = get_shared\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict replaced through the globals mapping",
     "globals()['dict'] = get_shared\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict replaced through __builtins__",
     "__builtins__[KEY] = get_shared\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict replaced through exec",
     "exec(SRC)\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict replaced on the module's own entry in sys.modules",
     "import sys\nsys.modules[__name__].dict = get_shared\ndef h(q, v):\n"
     "    q.append(v)\ndef f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict replaced on a module found by import_module",
     "import importlib as il\nil.import_module(NAME).dict = get_shared\n"
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    h(dict(), url)\n"
     "    log.info(dict())\n", True),
    ("dict replaced through a frame's globals",
     "import sys as s\ns._getframe().f_globals[KEY] = get_shared\ndef h(q, v):\n"
     "    q.append(v)\ndef f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict replaced through object.__setattr__",
     "object.__setattr__(MOD, KEY, get_shared)\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("namespace fetched through a computed getattr",
     "ns = getattr(fn, KEY)\nns[NAME] = get_shared\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict replaced on the module imported by its own name",
     "import sample\nsample.dict = get_shared\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("namespace fetched through a literal getattr of a frame",
     "ns = getattr(FRAME, 'f_globals')\nns[NAME] = get_shared\ndef h(q, v):\n"
     "    q.append(v)\ndef f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("dict re-bound in a namespace handed in",
     "def setup(ns):\n    ns['dict'] = get_shared\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("memory written through ctypes imported under an alias",
     "import ctypes as c\nc.memmove(ADDR, SRC, N)\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("code run from pickled data, loader imported by name",
     "from pickle import loads\nloads(BLOB)\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("code run from marshalled data",
     "import marshal as m\nrun(m.loads(BLOB))\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("namespace reached through an object-model dunder",
     "for c in object.__subclasses__():\n    poke(c)\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("namespace fetched through a literal getattr of a dunder",
     "ns = getattr(MOD, '__dict__')\nns[KEY] = get_shared\ndef h(q, v):\n"
     "    q.append(v)\ndef f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("code object names replaced",
     "k = CODE.replace(co_names=NAMES)\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("objects walked through gc",
     "import gc as g\nfor o in g.get_objects():\n    poke(o)\ndef h(q, v):\n"
     "    q.append(v)\ndef f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("the __name__ guard re-binds nothing, the dict builtin is logged",
     "def h(q, v):\n    q.append(v)\ndef f(url, x):\n    h(dict(), url)\n"
     "    log.info(isinstance(x, dict))\nif __name__ == '__main__':\n    f(1, 2)\n",
     False),
    ("dict patched by an imported helper given a string",
     "from unittest import mock\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    with mock.patch(TARGET, get_shared):\n        h(dict(), url)\n"
     "        log.info(dict())\n", True),
    ("dict re-bound through a keyword",
     "configure(dict=get_shared)\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    ("namespace reached through a generator frame",
     "def g():\n    yield\nGEN = g()\nGEN.gi_frame.f_globals[KEY] = get_shared\n"
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    h(dict(), url)\n"
     "    log.info(dict())\n", True),
    ("a class whose dunder hook may answer for dict",
     "class NS:\n    def __missing__(self, k):\n        return get_shared\n"
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    h(dict(), url)\n"
     "    log.info(dict())\n", True),
    ("a dunder parameter",
     "def g(__dict__=None):\n    pass\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("a class body run under a metaclass",
     "def f(url):\n    class C(metaclass=M):\n        h(dict(), url)\n"
     "        log.info(dict())\ndef h(q, v):\n    q.append(v)\n", True),
    ("a class built by type from a namespace",
     "C = type(NAME, BASES, NS)\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    ("process memory opened as a file",
     "MEM = open(PATH, MODE)\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    ("namespace fetched through an alias of getattr",
     "ga = getattr\nns = ga(FN, NAME)\nns[KEY] = get_shared\ndef h(q, v):\n"
     "    q.append(v)\ndef f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("namespace fetched through getattr handed to map",
     "for ns in map(getattr, FNS, NAMES):\n    ns[KEY] = get_shared\n"
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    h(dict(), url)\n"
     "    log.info(dict())\n", True),
    ("namespace fetched through a starred getattr",
     "ns = getattr(*PAIR, 'x')\nns[KEY] = get_shared\ndef h(q, v):\n    q.append(v)\n"
     "def f(url):\n    h(dict(), url)\n    log.info(dict())\n", True),
    ("namespace fetched by a class pattern",
     "match FN:\n    case object(__globals__=g):\n        g[KEY] = get_shared\n"
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    h(dict(), url)\n"
     "    log.info(dict())\n", True),
    ("frame fetched by a nested class pattern",
     "match GEN:\n    case object(gi_frame=object(f_globals=g)):\n"
     "        g[KEY] = get_shared\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    ("a relative import of a module named __future__",
     "from .__future__ import x\ndef h(q, v):\n    q.append(v)\ndef f(url):\n"
     "    h(dict(), url)\n    log.info(dict())\n", True),
    ("a __future__ import re-binds nothing, the dict builtin is logged",
     "from __future__ import annotations\ndef h(q, v):\n    q.append(v)\n"
     "def f(url, x):\n    h(dict(), url)\n    log.info(isinstance(x, dict))\n", False),
    ("a literal getattr re-binds nothing, the dict builtin is logged",
     "y = getattr(o, 'x')\ndef h(q, v):\n    q.append(v)\ndef f(url, x):\n"
     "    h(dict(), url)\n    log.info(isinstance(x, dict))\n", False),
    # S144-Q-96: a mutating helper is bound the way a wrapper is - a
    # lambda, an alias (`k = h`, a conditional, a tuple, a walrus, a `for`
    # or comprehension target over a literal, a default), a staticmethod
    # over one in a class body, one stored on an attribute from outside a
    # class body, and one stored by `setattr` with a literal name (which
    # stores a wrapper and a logging function too). The clean rows keep it
    # tied to the value: a clean source, and an alias re-bound before the
    # call.
    ("lambda mutating helper, the caller logs it",
     "def f(url):\n    h = lambda q, v: q.append(v)\n    r = []\n    h(r, url)\n"
     "    log.info(r)\n", True),
    ("module lambda mutating helper",
     "h = lambda q, v: q.append(v)\ndef f(url):\n    r = []\n    h(r, url)\n"
     "    log.info(r)\n", True),
    ("lambda mutating helper called in place",
     "def f(url):\n    r = []\n    (lambda q, v: q.append(v))(r, url)\n"
     "    log.info(r)\n", True),
    ("alias of a mutating helper",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    k = h\n    r = []\n"
     "    k(r, url)\n    log.info(r)\n", True),
    ("module alias of a mutating helper",
     "def h(q, v):\n    q.append(v)\nk = h\ndef f(url):\n    r = []\n"
     "    k(r, url)\n    log.info(r)\n", True),
    ("conditional alias of a mutating helper",
     "def h(q, v):\n    q.append(v)\ndef f(url, c):\n    k = h if c else g\n"
     "    r = []\n    k(r, url)\n    log.info(r)\n", True),
    ("conditional alias, the mutating helper in the else arm",
     "def h(q, v):\n    q.append(v)\ndef f(url, c):\n    k = g if c else h\n"
     "    r = []\n    k(r, url)\n    log.info(r)\n", True),
    ("tuple alias of a mutating helper",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    k, j = h, 1\n    r = []\n"
     "    k(r, url)\n    log.info(r)\n", True),
    ("walrus alias of a mutating helper",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    (k := h)\n    r = []\n"
     "    k(r, url)\n    log.info(r)\n", True),
    ("for target over a mutating helper",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    r = []\n"
     "    for k in (h,):\n        k(r, url)\n    log.info(r)\n", True),
    ("comprehension target over a mutating helper",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    r = []\n"
     "    [k(r, url) for k in (h,)]\n    log.info(r)\n", True),
    ("mutating helper as a parameter default",
     "def h(q, v):\n    q.append(v)\ndef f(url, k=h):\n    r = []\n    k(r, url)\n"
     "    log.info(r)\n", True),
    ("wrapper calling a mutating helper default, the caller logs it",
     "def h(q, v):\n    q.append(v)\ndef w(q, v, k=h):\n    k(q, v)\ndef f(url):\n"
     "    r = []\n    w(r, url)\n    log.info(r)\n", True),
    ("staticmethod over a mutating helper in a class body",
     "def h(q, v):\n    q.append(v)\nclass C:\n    cb = staticmethod(h)\n"
     "def f(c, url):\n    r = []\n    c.cb(r, url)\n    log.info(r)\n", True),
    ("mutating helper stored on an attribute",
     "def h(q, v):\n    q.append(v)\ndef f(o, url):\n    o.cb = h\n    r = []\n"
     "    o.cb(r, url)\n    log.info(r)\n", True),
    ("mutating lambda stored on self, another method calls it",
     "class C:\n    def __init__(self):\n        self.cb = lambda q, v: q.append(v)\n"
     "    def f(self, url):\n        r = []\n        self.cb(r, url)\n"
     "        log.info(r)\n", True),
    ("mutating helper stored by setattr",
     "def h(q, v):\n    q.append(v)\ndef f(o, url):\n    setattr(o, 'cb', h)\n"
     "    r = []\n    o.cb(r, url)\n    log.info(r)\n", True),
    ("wrapper stored by setattr",
     "def w(v):\n    log.info(v)\ndef f(o, url):\n    setattr(o, 'cb', w)\n"
     "    o.cb(url)\n", True),
    ("logging function stored by setattr",
     "def f(o, url):\n    setattr(o, 'p', log.info)\n    o.p(url)\n", True),
    ("lambda mutating helper called with a clean source",
     "def f(url):\n    h = lambda q, v: q.append(v)\n    r = []\n    h(r, 'x')\n"
     "    log.info(r)\n", False),
    ("alias of a mutating helper called with a clean source",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    k = h\n    r = []\n"
     "    k(r, 'x')\n    log.info(r)\n", False),
    ("alias of a mutating helper re-bound before the call",
     "def h(q, v):\n    q.append(v)\ndef f(url):\n    k = h\n    k = g\n    r = []\n"
     "    k(r, url)\n    log.info(r)\n", False),
    ("mutating helper stored by setattr, called with a clean source",
     "def h(q, v):\n    q.append(v)\ndef f(o, url):\n    setattr(o, 'cb', h)\n"
     "    r = []\n    o.cb(r, 'x')\n    log.info(r)\n", False),
    # Stored on `self` by `setattr`, the lambda binds no receiver (the
    # store lands on the instance), so the url goes into the url, not self.
    ("mutating lambda stored on self by setattr, self is logged",
     "class C:\n    def f(self, url):\n"
     "        setattr(self, 'cb', lambda q, v: q.append(v))\n        r = []\n"
     "        self.cb(url, r)\n        log.info(self)\n", False),
    ("lambda that stores a literal, not its source",
     "def f(url):\n    h = lambda q, v: q.append('x')\n    r = []\n    h(r, url)\n"
     "    log.info(r)\n", False),
    # S144-Q-91: a call off a literal display (`_builtin_receiver`) runs the
    # builtin type's own method, never a method a class body defines, so no
    # attribute mark of that name is read off it. A name or call receiver
    # may be an instance of the class, so it stays read as before.
    ("str literal receiver of a method wrapper",
     "class F:\n    def join(self, xs):\n        log.info(xs)\ndef f(url):\n"
     "    ', '.join(url)\n", False),
    ("f-string receiver of a method wrapper that logs self",
     "class C:\n    def strip(self):\n        log.info(self)\ndef f(url):\n"
     "    f'at {url}'.strip()\n", False),
    ("two-field f-string receiver of a method wrapper that logs self",
     "class C:\n    def strip(self):\n        log.info(self)\ndef f(url):\n"
     "    f'{url}{url}'.strip()\n", False),
    # A one-field f-string is what `__format__` returns: a str subclass may
    # define the method (verifier counterexample), so it stays read.
    ("one-field f-string receiver of a str subclass method stays flagged",
     "class S(str):\n    def strip(self):\n        log.info(self)\ndef f(url):\n"
     "    f'{url}'.strip()\n", True),
    ("one-field formatted f-string receiver stays flagged",
     "class S(str):\n    def strip(self):\n        log.info(self)\ndef f(url):\n"
     "    f'{url:>3}'.strip()\n", True),
    ("list display receiver of a method wrapper",
     "class C:\n    def count(self, v):\n        log.info(v)\ndef f(url):\n"
     "    [1].count(url)\n", False),
    ("f-string receiver of a mutating method",
     "class C:\n    def format(self, q):\n        q.append(self)\ndef f(url):\n"
     "    r = []\n    f'at {url}'.format(r)\n    log.info(r)\n", False),
    ("str literal receiver of a class logging attribute",
     "class C:\n    format = log.info\ndef f(url):\n    '{}'.format(url)\n", False),
    ("str literal receiver of a class logger object attribute",
     "class C:\n    upper = logging.getLogger('x')\ndef f(url):\n"
     "    'x'.upper.info(url)\n", False),
    ("name receiver of a method wrapper stays flagged",
     "class C:\n    def strip(self):\n        log.info(self)\ndef f(url):\n"
     "    url.strip()\n", True),
    ("call receiver of a mutating method stays flagged",
     "class C:\n    def format(self, q):\n        q.append(self)\ndef f(url):\n"
     "    r = []\n    g(url).format(r)\n    log.info(r)\n", True),
    ("name receiver of a class logging attribute stays flagged",
     "class C:\n    format = log.info\ndef f(o, url):\n    o.format(url)\n", True),
    ("name receiver of a class logger object attribute stays flagged",
     "class C:\n    upper = logging.getLogger('x')\ndef f(o, url):\n"
     "    o.upper.info(url)\n", True),
)


@pytest.mark.parametrize("label,sample,expect_leak", _CHECKER_SAMPLES)
def test_defect_f_leak_checker_is_not_vacuous(tmp_path, label, sample, expect_leak):
    """The guard this file replaced passed vacuously against a real leak, so
    prove this one cannot: it must flag every synthetic leak shape and clear
    every sanitized one."""
    p = tmp_path / "sample.py"
    p.write_text(sample, encoding="utf-8")
    found = _message_leak_sites(p)
    assert bool(found) is expect_leak, (label, found)


def _nested_wrapper_sample(depth, leak=True):
    """RM-1656: `depth` nested wrappers, each a two-parameter def holding a
    `for` loop that logs one parameter, re-binds the other late in the pass
    and calls the next wrapper with both. The url reaches the innermost log
    call only through every wrapper (`leak`), or never (`leak=False`)."""
    def level(d, ind):
        body = ind + "        "
        out = [f"{ind}def g{d}(a{d}, b{d}):", f"{ind}    for x in xs:",
               f"{body}log.info(a{d})", f"{body}c = b{d}"]
        if d < depth:
            out += level(d + 1, body) + [f"{body}g{d + 1}(c, a{d})"]
        return out + [f"{body}b{d} = a{d}"]
    arg = "url" if leak else "'x'"
    return "\n".join(["def f(url):"] + level(1, "    ") + [f"    g1('x', {arg})"]) + "\n"


@pytest.mark.parametrize("leak", [True, False])
def test_defect_f_leak_checker_cost_is_not_exponential_in_def_nesting(tmp_path, leak):
    """RM-1656: every enclosing pass re-walks a nested def with a state
    holding names its body never reads, so a cache keyed on the whole state
    missed and the scan grew about 4x per level (depth 5 1.5 s, depth 9
    minutes). The walk is keyed on the names the body can read; depth 9
    must finish well inside 5 s and still find exactly the leak."""
    p = tmp_path / "sample.py"
    p.write_text(_nested_wrapper_sample(9, leak), encoding="utf-8")
    t0 = time.perf_counter()
    found = _message_leak_sites(p)
    elapsed = time.perf_counter() - t0
    # Idle-box bound 5 s, scaled by the live suite-gate load (U5). budget()
    # tops out at MAX_SLOTS (4) x 5 = 20 s, still far below the unfixed
    # walk's minutes at depth 9, so no cap is needed to tell fixed from broken.
    assert elapsed < fleet_test_guard.budget(5.0), elapsed
    assert bool(found) is leak, found


def test_defect_f_leak_checker_walks_grow_linearly_with_def_nesting(tmp_path, monkeypatch):
    """RM-1656, the deterministic half of the timed test above: the number
    of scope walks actually run (cache misses) grows linearly with nesting
    depth. Measured 135 at depth 10 and 275 at depth 20; a cache keyed on
    the whole state, not the entries the body reads, ran 816 and 3831, and
    no walk cache at all is exponential."""
    real = _walk_scope_uncached
    runs = []

    def counted(*args, **kwargs):
        runs.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(sys.modules[__name__], "_walk_scope_uncached", counted)
    p = tmp_path / "sample.py"
    counts = {}
    for depth in (10, 20):
        p.write_text(_nested_wrapper_sample(depth), encoding="utf-8")
        runs.clear()
        assert _message_leak_sites(p), depth
        counts[depth] = len(runs)
    assert counts[10] > 0, counts
    assert counts[20] <= 2.2 * counts[10], counts


def test_defect_f_an_always_storing_helper_keeps_a_wrapper_sink_parameter(tmp_path):
    """RM-1793: a helper that stores an enclosing tainted name into its
    parameter taints the caller's object whatever it is passed, but that
    must not pre-taint a wrapper's own parameter when the wrapper is judged
    for sink parameters (`_judge_params`): the first try did, and so hid the
    sink parameter of every wrapper that calls such a helper on it. The
    wrapper's own log site is flagged, AND so is the caller line that hands
    it a url."""
    sample = ("G = url\ndef h(q):\n    q.append(G)\ndef w(q):\n    h(q)\n"
              "    log.info(q)\ndef f(a):\n    w(a.chunk_url)\n")
    p = tmp_path / "sample.py"
    p.write_text(sample, encoding="utf-8")
    lines = {int(s.split(":")[1]) for s in _message_leak_sites(p)}
    assert {6, 8} <= lines, lines


def test_defect_f_no_message_site_in_the_module_carries_the_raw_endpoint():
    """Widened replacement for the old defect-D guard (which filtered lines on
    "ident"/"digest" and so could not see the four `{url}` interpolations that
    actually leaked). Covers EVERY raise and logging site in the module, and
    still covers the digest the old name promised."""
    leaks = _message_leak_sites(_ROOT / "core" / "rank_tier_source.py")
    assert leaks == [], leaks


# --- preserved public contracts -----------------------------------------

def test_kill_switch_default_is_still_off(monkeypatch):
    monkeypatch.delenv("RC_RANK_TIER_LIVE", raising=False)
    assert RTB._live_enabled() is False
    RTB._reset_cache()
    assert RTB.source() == "static"


def test_fetch_rows_never_raises_on_a_hostile_seam(monkeypatch, tmp_path):
    _write_config(tmp_path, monkeypatch, {
        "endpoint": "https://agg.example/agg", "tier_param": "tier", "enabled": True,
    })

    def _hostile(url, timeout_s=RTS._TIMEOUT_S):
        raise ValueError("garbage")

    monkeypatch.setattr(RTS, "_http_get_json", _hostile)
    assert RTS.fetch_rows("iron", "SR") is None


# --- ascii hygiene -------------------------------------------------------

def test_touched_modules_are_ascii():
    for rel in ("core/rank_tier_bench.py", "core/rank_tier_source.py"):
        b = (_ROOT / rel).read_bytes()
        assert [(i, x) for i, x in enumerate(b) if x > 0x7F] == [], rel


def test_this_file_is_ascii():
    b = Path(__file__).read_bytes()
    assert [(i, x) for i, x in enumerate(b) if x > 0x7F] == []
