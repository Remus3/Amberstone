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

No test here performs real network I/O: the HTTP seam and urlopen are stubbed.
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
        return None

    monkeypatch.setattr(RTS, "fetch_rows", _slow_fetch)
    RTB._reset_cache()

    got = False
    worker = threading.Thread(target=RTB.source, name="rtb-probe", daemon=True)
    worker.start()
    try:
        assert started.wait(10.0), "the live sweep never started"
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
        return None

    monkeypatch.setattr(RTS, "fetch_rows", _slow_fetch)

    t0 = time.monotonic()
    grid = RTB.rank_tier_grid("iron", "SR")
    elapsed = time.monotonic() - t0
    gate.set()

    assert grid["all"]["early"]["cs"]["avg"] == 140, "stale grid was not served"
    assert started.wait(10.0), "the refresh never ran at all"
    assert elapsed < 1.0, (
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
        return None

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
    monkeypatch.setattr(RTS.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(body, reads))
    with pytest.raises(RTS.RankTierSourceError, match="exceeds"):
        RTS._http_get_json("https://agg.example/agg")


def test_defect_c_response_read_is_size_bounded(monkeypatch):
    cap = getattr(RTS, "_MAX_BODY_BYTES", None)
    assert isinstance(cap, int) and cap > 0, "no response size cap"
    body = json.dumps({"data": _rows()}).encode("utf-8")
    reads = []
    monkeypatch.setattr(RTS.urllib.request, "urlopen",
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
    assert a != b and a != c            # endpoint + tier_param both bind
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
    monkeypatch.setattr(RTS.urllib.request, "urlopen",
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
    monkeypatch.setattr(RTS.urllib.request, "urlopen",
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
    monkeypatch.setattr(RTS.urllib.request, "urlopen",
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
    monkeypatch.setattr(
        RTS.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(b"{}", reads, status=503))
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)
    assert "503" in str(ei.value), str(ei.value)


def test_defect_f_transport_failure_message_carries_no_credential(monkeypatch):
    def _boom(req, timeout=None):
        raise RTS.urllib.error.URLError("timed out")

    monkeypatch.setattr(RTS.urllib.request, "urlopen", _boom)
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

    monkeypatch.setattr(RTS.urllib.request, "urlopen", _boom)
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)


def test_defect_f_bad_json_message_carries_no_credential(monkeypatch):
    reads = []
    monkeypatch.setattr(
        RTS.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(b"{not json", reads))
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)
    assert "JSON" in str(ei.value), str(ei.value)


def test_defect_f_non_dict_toplevel_message_carries_no_credential(monkeypatch):
    reads = []
    monkeypatch.setattr(
        RTS.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(b"[1, 2, 3]", reads))
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(_dummy_url())
    _assert_no_credential(ei.value)
    assert "list" in str(ei.value), str(ei.value)


def test_defect_f_oversize_body_message_carries_no_credential(monkeypatch):
    cap = RTS._MAX_BODY_BYTES
    body = b'{"data":[{"role":"all"}],"pad":"' + (b"x" * (cap + 1024)) + b'"}'
    reads = []
    monkeypatch.setattr(
        RTS.urllib.request, "urlopen",
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

    monkeypatch.setattr(RTS.urllib.request, "urlopen", _boom)
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


def _is_log_call(node) -> bool:
    """print(...), or a <level>(...) call rooted at a log-ish name."""
    name = _call_name(node)
    if name == "print":
        return True
    if name not in _LOG_FUNCS:
        return False
    root = node.func
    while isinstance(root, ast.Attribute):
        root = root.value
    base = root.id.lower() if isinstance(root, ast.Name) else ""
    return (base.lstrip("_").startswith("log")
            or base in {"logging", "logger", "sys", "warnings", "traceback"})


class _TaintScan(ast.NodeVisitor):
    """Every term in one expression that could carry the raw endpoint.

    Calls to the module's own sanitizers are PRUNED rather than descended into,
    so `_safe_url(url)` is clean while a bare `url` is not."""

    def __init__(self, tainted_locals):
        self._tainted = tainted_locals
        self.found = []

    def visit_Call(self, node):
        name = _call_name(node)
        if name in _SANITIZERS:
            return
        if name in _TAINTED_CALLS:
            self.found.append(f"{name}()")
        self.generic_visit(node)

    def visit_Name(self, node):
        low = node.id.lower()
        if node.id in self._tainted or any(p in low for p in _TAINTED_NAME_PARTS):
            self.found.append(node.id)

    def visit_Attribute(self, node):
        if any(p in node.attr.lower() for p in ("url", "endpoint")):
            self.found.append(f".{node.attr}")
        self.generic_visit(node)

    def visit_Constant(self, node):
        if (isinstance(node.value, str)
                and node.value.strip().lower() in _CONFIG_SECRET_KEYS):
            self.found.append(f"config key {node.value!r}")


def _walk_stmts(node):
    """Statements under `node` in source order (body, then handlers, then
    orelse / finalbody), so an assignment is seen before the raise below it."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.stmt, ast.excepthandler)):
            yield child
            yield from _walk_stmts(child)


def _retaint(stmt, tainted) -> None:
    """Propagate taint across one binding statement. Scope is deliberately
    small - assignments and except-as names - because that is what carries a
    URL into a message; reaching a URL off an object is caught by the attribute
    rule (`.full_url`, `.geturl`) instead of by over-tainting the object."""
    if isinstance(stmt, ast.ExceptHandler):
        if stmt.name:
            # A third-party exception can quote the URL it was handed back at
            # us, so it is untrusted text until it goes through a sanitizer.
            tainted.add(stmt.name)
        return
    if isinstance(stmt, ast.Assign):
        targets, value = stmt.targets, stmt.value
    elif isinstance(stmt, (ast.AugAssign, ast.AnnAssign)):
        targets, value = [stmt.target], stmt.value
    else:
        return
    if value is None:
        return
    scan = _TaintScan(tainted)
    scan.visit(value)
    for target in targets:
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name):
                if scan.found:
                    tainted.add(sub.id)
                else:
                    tainted.discard(sub.id)


def _message_leak_sites(path):
    """Every raise / logging site in `path` whose message could carry the raw
    endpoint, one taint scope per function plus the module scope."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    scopes = [tree] + [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    leaks = set()
    for scope in scopes:
        tainted = set()
        for stmt in _walk_stmts(scope):
            exprs = []
            if isinstance(stmt, ast.Raise):
                exprs = [e for e in (stmt.exc, stmt.cause) if e is not None]
            for call in [n for n in ast.walk(stmt) if isinstance(n, ast.Call)]:
                if _is_log_call(call):
                    exprs.extend(call.args)
                    exprs.extend(kw.value for kw in call.keywords)
            for expr in exprs:
                scan = _TaintScan(tainted)
                scan.visit(expr)
                if scan.found:
                    leaks.add(
                        f"{Path(path).name}:{expr.lineno}: {sorted(set(scan.found))}")
            _retaint(stmt, tainted)
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
