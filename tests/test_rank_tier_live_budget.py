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
        return None

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
        return None

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


def _is_logger_expr(expr, tainted=frozenset()) -> bool:
    """`expr` may evaluate to a logger OBJECT (RM-1563): a log-ish name
    anywhere along its chain (`log`, `self.log`, `get_logger()`,
    `logging.getLogger(n)`), a chain rooted at a name bound to one
    (`_LOGOBJ`), or a conditional either arm of which is one."""
    if isinstance(expr, ast.IfExp):
        return (_is_logger_expr(expr.body, tainted)
                or _is_logger_expr(expr.orelse, tainted))
    names, root = _chain_names(expr)
    if isinstance(root, ast.Name) and _LOGOBJ + root.id in tainted:
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


def _object_only(name, tainted) -> bool:
    low = name.lower()
    return (_OBJ + name in tainted and name not in tainted
            and not any(p in low for p in _TAINTED_NAME_PARTS))


def _retaint(stmt, tainted, late=frozenset()) -> None:
    """Propagate taint across one binding statement. Scope is deliberately
    small - assignments (except-as names are bound at handler entry in
    `_flow_block`) - because that is what carries a URL into a message;
    reaching a URL off an object is caught by the attribute rule (`.full_url`,
    `.geturl`) instead of by over-tainting the object."""
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
    for target in targets:
        # `m += "!"` keeps whatever `m` already carried (RM-1443): only a
        # plain re-binding to a clean value clears a name.
        _bind_names(target, found, tainted, clear=plain)
    for name, is_alias, is_obj in aliases:
        _bind_log_alias(name, is_alias, tainted, is_obj)


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
        return
    if found:
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name):
                tainted.add(sub.id)


# RM-1558: methods that put their arguments INTO the receiver. A tainted
# argument taints the receiver's names (add-only, as an assignment target
# would: `self.seen.append(url)` taints `self` like `self.last = url` does).
# `write` is not here: it is a sink (`_LOG_FUNCS`).
_MUTATORS = frozenset({"append", "appendleft", "extend", "extendleft", "insert",
                       "add", "update", "setdefault", "put", "put_nowait"})


def _bind_mutators(nodes, tainted, late=frozenset()) -> None:
    """`q.append(url)` leaves `q` carrying the url for the rest of the scope.
    Applied with the walrus bindings, before the statement's sinks."""
    for node in nodes:
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in _MUTATORS):
                args = list(sub.args) + [kw.value for kw in sub.keywords]
                if any(_is_tainted(a, tainted, late) for a in args):
                    _bind_names(sub.func.value, True, tainted, clear=False)


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

def _bind_walrus(nodes, tainted, late=frozenset()) -> None:
    """`(m := url)` binds `m` for the rest of the scope. Applied BEFORE a
    statement's sinks are checked: a sink in the same expression may run
    after the walrus (`log.info(m) if (m := url) else None`)."""
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.NamedExpr):
                is_alias = _is_log_callable(sub.value, tainted)
                is_obj = _is_logger_expr(sub.value, tainted)
                _bind_names(sub.target, _is_tainted(sub.value, tainted, late),
                            tainted, clear=False)
                _bind_log_alias(sub.target, is_alias, tainted, is_obj)


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
    (`lg.info` after `lg = logging.getLogger()`)."""
    if isinstance(expr, ast.Name) and _LOGFN + expr.id in tainted:
        return True
    if isinstance(expr, ast.IfExp):
        return (_is_log_callable(expr.body, tainted)
                or _is_log_callable(expr.orelse, tainted))
    if isinstance(expr, ast.Call) and _call_name(expr) == "partial" and expr.args:
        return _is_log_callable(expr.args[0], tainted)
    return _is_log_call(ast.Call(func=expr, args=[], keywords=[]), tainted)


def _bind_log_alias(target, is_alias, tainted, is_obj=False) -> None:
    """RM-1562: a plain name bound to a logging function becomes a sink
    when it is called; RM-1563: one bound to a logger object (`is_obj`)
    makes a level call off it a sink. Both are judged BEFORE the binding
    clears the name (`p = p` keeps it). Add-only here; a plain `=` to
    anything else clears them through `_bind_names`. A tuple target is
    split into its names by `_alias_bindings`; an element or attribute
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


def _log_args(call, tainted=frozenset()):
    """The message arguments of a logging sink, or None if `call` is not one.

    RM-1561 (d): `functools.partial(log.info, m)` evaluates `m` where the
    partial is BUILT, so the partial is the sink and is judged there (a
    later re-binding of `m` changes nothing the partial holds).
    RM-1562: a call THROUGH a logging function - an alias `p(m)`, a
    partial called later `p = partial(log.info, '%s'); p(m)` or in place
    `partial(log.info, '%s')(m)` - is a sink for its own arguments too."""
    if _is_log_callable(call.func, tainted):
        return list(call.args) + [kw.value for kw in call.keywords]
    if (_call_name(call) == "partial" and call.args
            and _is_log_callable(call.args[0], tainted)):
        return list(call.args[1:]) + [kw.value for kw in call.keywords]
    return None


def _default_bindings(fn, state, late=frozenset()):
    """RM-1562: the parameters of def `fn` that a default makes carry the
    value (or a logging function, as `_LOGFN` marks). A default is evaluated
    where the def stands, so it is judged with the def-time state; a lambda
    inside one reads `late`, as everywhere. Keeps the RM-1561 (c) caveat:
    a tainted default keeps its parameter tainted however it is called."""
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
    return bound


def _check_sinks(nodes, stmt, tainted, report, late=frozenset()) -> None:
    """Flag a raise or logging call among `nodes` whose message is tainted.
    A logging call inside a lambda or generator body is judged with the late
    view (`tainted | late`): it runs after the statement, maybe after a
    re-binding."""
    exprs = []
    if isinstance(stmt, ast.Raise):
        exprs = [(e, tainted) for e in (stmt.exc, stmt.cause) if e is not None]
    for node in nodes:
        deferred = {id(c) for d in ast.walk(node) if isinstance(d, _DEFERRED)
                    for c in ast.walk(d) if isinstance(c, ast.Call)}
        for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
            seen = (set(tainted) | set(late) if id(call) in deferred
                    else tainted)
            args = _log_args(call, seen)
            if args is not None:
                exprs.extend((a, seen) for a in args)
    for expr, seen in exprs:
        scan = _TaintScan(seen, late)
        scan.visit(expr)
        if scan.found:
            report(expr, scan.found)


def _walk_scope(body, entry, report, late=frozenset()):
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
        # Both binding kinds only ADD taint, so they are run to a fixed point:
        # within one statement a walrus may read a container a later mutator
        # fills (`g(q.append(url), m := q[0])`), or one mutator a container
        # another fills after it (RM-1558).
        while True:
            before = len(state)
            _bind_walrus(nodes, state, self.ever)
            _bind_mutators(nodes, state, self.ever)
            if len(state) == before:
                break
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
            # the time a later statement does): a `global` or `self.x` set from
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
            _check_sinks(_own_nodes(stmt), stmt, state, self.report, self.ever)
            out, returns, inside, hands_back = _walk_scope(
                stmt.body, state, self.report, self.ever)
            if not isinstance(stmt, ast.ClassDef):
                seeded = _default_bindings(stmt, state, self.ever) - state
                if seeded:
                    hands_back |= _walk_scope(stmt.body, state | seeded,
                                              self.report, self.ever)[3]
                if not self.ever <= state:
                    hands_back |= _walk_scope(stmt.body,
                                              state | self.ever | seeded,
                                              self.report, self.ever)[3]
            state = state | (_join(out, *returns, *inside) or set())
            if hands_back and not isinstance(stmt, ast.ClassDef):
                state.add(stmt.name)
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

        def run_pass(entry):
            # The target is assigned once per item, so a sink in it
            # (`for d[log.info(m)] in xs`) sees what the last pass bound.
            body_in = self._expr_step([stmt.target], stmt, entry)
            _bind_names(stmt.target, found, body_in, clear=False)
            # RM-1563: add-only, like the value binding above.
            for name, is_alias, is_obj in aliases:
                _bind_log_alias(name, is_alias, body_in, is_obj)
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
            for handler in stmt.handlers:
                _check_sinks([handler.type] if handler.type else [], handler,
                             handler_entry, self.report, self.ever)
                entry = set(handler_entry)
                if handler.name:
                    # A third-party exception can quote the URL it was handed
                    # back at us, so it is untrusted text until it goes through
                    # a sanitizer.
                    entry.add(handler.name)
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

    for scope in scopes:
        _walk_scope(scope.body, set(), report)
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
