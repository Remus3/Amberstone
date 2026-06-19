"""
tools/run_phase2_perf.py
Phase 2 Step 4 / 4.1 -- Deterministic local performance/latency probe.

Usage (from project root):
    python tools/run_phase2_perf.py

Or via wrapper:
    tools\\run_phase2_perf.cmd

Measures the highest-value hot paths using fixtures/fakes.
No live Riot API, no Anthropic API, no Tk, no internet required.
Produces:
  - Console output (human-readable)
  - audit/phase2_step4_proof/perf_baseline.json
  - audit/phase2_step4_proof/perf_baseline.md

Exit code semantics (Phase 2 Step 4.1 fix):
  - 0: all sections completed successfully
  - 1: one or more sections failed internally, OR harness-internal fatal error

CLI flags (test-only):
  --fail-section <name>   Force the named section to raise a RuntimeError so
                          that the nonzero-exit behavior can be proven without
                          breaking real benchmarks.  Has no effect in normal
                          production runs.
"""
import json
import math
import queue
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# -- Constants --------------------------------------------------------------

WARMUP   = 5     # warmup iterations (discarded)
REPS     = 100   # measurement iterations per benchmark
REPS_IO  = 50    # reps for I/O-bound benchmarks (file reads/writes)
WORKER_STOP_TIMEOUT = 4.0  # seconds

# -- CLI / test-hook: --fail-section <name> ---------------------------------
# Forces one named section to raise, proving nonzero-exit behavior.
# Test-only; no runtime code path sets this.

_FORCE_FAIL_SECTION = None
for _i, _arg in enumerate(sys.argv[1:]):
    if _arg == "--fail-section" and _i + 2 <= len(sys.argv) - 1:
        _FORCE_FAIL_SECTION = sys.argv[_i + 2]
        break

# -- Stat helpers -----------------------------------------------------------

def _stats(samples):
    n = len(samples)
    if n == 0:
        return {"count": 0, "mean_us": 0, "median_us": 0, "p95_us": 0, "max_us": 0}
    s = sorted(samples)
    mean  = sum(s) / n
    med   = s[n // 2] if n % 2 else (s[n//2-1] + s[n//2]) / 2
    p95   = s[int(math.ceil(0.95 * n)) - 1]
    return {
        "count":     n,
        "mean_us":   round(mean * 1e6, 2),
        "median_us": round(med  * 1e6, 2),
        "p95_us":    round(p95  * 1e6, 2),
        "max_us":    round(max(s) * 1e6, 2),
    }

def _bench(label, fn, reps=REPS, warmup=WARMUP):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    st = _stats(samples)
    print(f"  {label:<50}  mean={st['mean_us']:>8.1f}us  "
          f"p95={st['p95_us']:>8.1f}us  max={st['max_us']:>8.1f}us")
    return label, st

# -- Fakes (same stubs as smoke harness) -----------------------------------

class _FakeReader:
    def __init__(self, states):
        self._states = list(states); self._idx = 0
    def read_game(self):
        if self._idx < len(self._states):
            s = self._states[self._idx]; self._idx += 1; return s
        return None
    def reset(self): pass

class _FakeCoach:
    def submit_state(self, s): pass
    def reset_state(self): pass

class _FakeTftReader:
    def __init__(self, states):
        self._states = list(states); self._idx = 0
    def read(self):
        if self._idx < len(self._states):
            s = self._states[self._idx]; self._idx += 1; return s
        return None
    def shutdown(self): pass

class _FakeEngine:
    def submit(self, s): pass
    def reset_state(self): pass
    def shutdown(self): pass

class _FakeLive:
    def set_ai_bar(self, b): pass
    def start(self): pass
    def shutdown(self): pass
    def notify_coach_state(self, s): pass
    def notify_round(self, s): pass

class _FakeProxy:
    def set_scanning(self, pct=0): pass
    def set_done(self): pass
    def set_interval(self, s): pass
    def notify_scan_scheduled(self, t): pass

# -- Fixtures ---------------------------------------------------------------

from tests.fixtures.state_dicts import SR_STATE, ARAM_STATE, TFT_STATE

SR_CLASSIC = dict(SR_STATE, game_mode="CLASSIC")

# -- Section A: feature_policy ----------------------------------------------

def _bench_feature_policy(td: Path):
    import core.feature_policy as fp
    from core.feature_policy import is_allowed, get_policy_state

    results = []
    print("\n[A] feature_policy hot paths")

    fp._reload()
    results.append(_bench("is_allowed() cached (no reload)",
                           lambda: is_allowed("sr", "live_coaching")))

    fp._reload()
    results.append(_bench("get_policy_state() cached (no reload)",
                           lambda: get_policy_state()))

    cfg = td / "fp_valid.json"
    cfg.write_text(json.dumps({"sr": {"live_coaching": "allow"}}))
    fp._reload(cfg)
    def _force_valid_reload():
        cfg.write_text(json.dumps({"sr": {"live_coaching": "allow"}}))
        is_allowed("sr", "live_coaching")
    results.append(_bench("is_allowed() with valid file reload",
                           _force_valid_reload, reps=20, warmup=3))

    cfg_bad = td / "fp_bad.json"
    cfg.write_text(json.dumps({"sr": {"live_coaching": "allow"}}))
    fp._reload(cfg)
    def _force_invalid_reload():
        cfg_bad.write_text('{"sr":{"live_coaching":"bad"}}')
        fp._cache._mtime = -1.0
        fp._cache._path = cfg_bad
        is_allowed("sr", "live_coaching")
        fp._cache._path = cfg
    results.append(_bench("is_allowed() with invalid reload (LKG retained)",
                           _force_invalid_reload, reps=20, warmup=2))

    fp._reload()
    return results

# -- Section B: MetricsCache ------------------------------------------------

def _bench_metrics_cache(td: Path):
    import core.feature_policy as fp
    from core.metrics_cache import MetricsCache

    fp._reload()
    results = []
    print("\n[B] MetricsCache hot paths")

    rt = td / "runtime"
    rt.mkdir(parents=True, exist_ok=True)
    (rt / "status.json").write_text(json.dumps({
        "supervisor_state": "healthy_ready", "process_running": True,
        "awaiting_first_heartbeat": False,
    }))
    (rt / "monitor_state.json").write_text(json.dumps({
        "consecutive_fails": 0, "ladder_index": 0,
        "circuit_breaker": {"tripped": False},
    }))
    (rt / "health.json").write_text(json.dumps({"mode": "game"}))
    (rt / "last_coaching_ts.json").write_text(
        json.dumps({"ts": "2026-04-13T10:00:00+00:00"}))
    incidents = [
        {"ts": f"2026-04-13T10:0{i}:00Z", "severity": "WARN",
         "subsystem": "rc.super", "trigger": "restart", "detail": f"entry {i}"}
        for i in range(5)
    ]
    (rt / "incident_log.jsonl").write_text(
        "\n".join(json.dumps(e) for e in incidents) + "\n", encoding="utf-8")

    mc = MetricsCache(rt, refresh_interval_s=9999)
    mc._refresh()

    results.append(_bench("MetricsCache._refresh() (full cycle)",
                           lambda: mc._refresh(), reps=REPS_IO, warmup=3))
    results.append(_bench("MetricsCache.get_summary() (snapshot copy)",
                           lambda: mc.get_summary()))
    results.append(_bench("MetricsCache._read_incident_tail()",
                           lambda: mc._read_incident_tail(), reps=REPS_IO, warmup=3))

    from core.metrics_cache import MetricsSummary
    def _pol_only():
        s = MetricsSummary()
        mc._read_policy_state(s)
    results.append(_bench("MetricsCache._read_policy_state() only", _pol_only))
    return results

# -- Section C: snapshot translation ---------------------------------------

def _bench_snapshots():
    from game_reader import GameReader
    from tft.tft_state_reader import TftStateReader

    results = []
    print("\n[C] Snapshot translation")

    results.append(_bench("GameReader.to_rift_snapshot(SR_STATE)",
                           lambda: GameReader.to_rift_snapshot(SR_STATE)))
    results.append(_bench("GameReader.to_aram_snapshot(ARAM_STATE)",
                           lambda: GameReader.to_aram_snapshot(ARAM_STATE)))
    results.append(_bench("TftStateReader.to_tft_snapshot(TFT_STATE)",
                           lambda: TftStateReader.to_tft_snapshot(TFT_STATE)))
    from core.game_snapshot import GameEnvelope
    results.append(_bench("GameEnvelope.client()",
                           lambda: GameEnvelope.client()))
    return results

# -- Section D: disabled placeholder writes ---------------------------------

def _bench_placeholders(td: Path):
    from core.feature_policy import write_disabled_placeholder

    results = []
    print("\n[D] Disabled placeholder writes (to temp root)")

    art = td / "artifacts"
    results.append(_bench("write_disabled_placeholder('sr')",
                           lambda: write_disabled_placeholder("sr", artifact_root=art),
                           reps=REPS_IO, warmup=3))
    results.append(_bench("write_disabled_placeholder('arena')",
                           lambda: write_disabled_placeholder("arena", artifact_root=art),
                           reps=REPS_IO, warmup=3))
    results.append(_bench("write_disabled_placeholder('brawl')",
                           lambda: write_disabled_placeholder("brawl", artifact_root=art),
                           reps=REPS_IO, warmup=3))
    results.append(_bench("write_disabled_placeholder('tft','live_coaching')",
                           lambda: write_disabled_placeholder("tft", "live_coaching",
                                                              artifact_root=art),
                           reps=REPS_IO, warmup=3))
    results.append(_bench("write_disabled_placeholder('tft','tft_vision_analysis')",
                           lambda: write_disabled_placeholder("tft", "tft_vision_analysis",
                                                              artifact_root=art),
                           reps=REPS_IO, warmup=3))
    return results

# -- Section E: worker contract timing -------------------------------------

def _bench_workers():
    from core.sr_aram_worker import SrAramWorker
    from core.tft_worker import TftWorker, TftWorkerResult
    import core.feature_policy as fp

    fp._reload()
    results_raw = []
    print("\n[E] Worker contract timing")

    def _sr_start_stop():
        rq = queue.Queue(maxsize=4)
        w = SrAramWorker(result_queue=rq, coach=_FakeCoach())
        w._reader = _FakeReader([])
        w.start(); w.stop(); w.join(timeout=WORKER_STOP_TIMEOUT)

    t0 = time.perf_counter()
    _sr_start_stop()
    sr_ss = time.perf_counter() - t0
    label = "SrAramWorker start+stop (single)"
    st = {"count": 1, "mean_us": round(sr_ss*1e6, 2),
          "median_us": round(sr_ss*1e6, 2),
          "p95_us": round(sr_ss*1e6, 2), "max_us": round(sr_ss*1e6, 2)}
    print(f"  {label:<50}  {sr_ss*1000:.1f}ms")
    results_raw.append((label, st))

    def _tft_start_stop():
        rq = queue.Queue(maxsize=4)
        w = TftWorker(result_queue=rq)
        w._reader = _FakeTftReader([])
        w._engine = _FakeEngine()
        w._live   = _FakeLive(); w._live.start()
        w.start(); w.stop(); w.join(timeout=WORKER_STOP_TIMEOUT)

    t0 = time.perf_counter()
    _tft_start_stop()
    tft_ss = time.perf_counter() - t0
    label = "TftWorker start+stop (single)"
    st = {"count": 1, "mean_us": round(tft_ss*1e6, 2),
          "median_us": round(tft_ss*1e6, 2),
          "p95_us": round(tft_ss*1e6, 2), "max_us": round(tft_ss*1e6, 2)}
    print(f"  {label:<50}  {tft_ss*1000:.1f}ms")
    results_raw.append((label, st))

    handoff_times = []
    import core.sr_aram_worker as _wmod
    _orig_min = _wmod.BACKOFF_MIN_S
    _orig_max = _wmod.BACKOFF_MAX_S
    _wmod.BACKOFF_MIN_S = 0.005
    _wmod.BACKOFF_MAX_S = 0.01
    try:
        for _ in range(10):  # 10 reps is sufficient to characterise handoff
            rq = queue.Queue(maxsize=8)
            w = SrAramWorker(result_queue=rq, coach=_FakeCoach())
            w._reader = _FakeReader([SR_CLASSIC])
            w.start()
            t_start = time.perf_counter()
            result = None
            deadline = t_start + 3.0
            while time.perf_counter() < deadline:
                try: result = rq.get_nowait(); break
                except queue.Empty: time.sleep(0.005)
            t_end = time.perf_counter()
            w.stop(); w.join(timeout=WORKER_STOP_TIMEOUT)
            if result is not None:
                handoff_times.append(t_end - t_start)
    finally:
        _wmod.BACKOFF_MIN_S = _orig_min
        _wmod.BACKOFF_MAX_S = _orig_max

    if handoff_times:
        st = _stats(handoff_times)
        label = "SrAramWorker queue handoff (state->result)"
        print(f"  {label:<50}  mean={st['mean_us']/1000:.1f}ms  "
              f"p95={st['p95_us']/1000:.1f}ms  max={st['max_us']/1000:.1f}ms  "
              f"n={st['count']}")
        results_raw.append((label, st))

    return results_raw

# -- Main -------------------------------------------------------------------

def main() -> int:
    import platform
    from datetime import datetime, timezone

    print("=" * 72)
    print("Riot Commander - Phase 2 Step 4 Performance Probe")
    print(f"REPS={REPS}  WARMUP={WARMUP}  Python {sys.version.split()[0]}")
    if _FORCE_FAIL_SECTION:
        print(f"[TEST HOOK] --fail-section {_FORCE_FAIL_SECTION} active")
    print("=" * 72)

    all_results    = {}
    section_errors = []   # accumulates (key, error_str) for each failed section

    try:
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            sections = [
                ("feature_policy",       lambda: _bench_feature_policy(td)),
                ("metrics_cache",        lambda: _bench_metrics_cache(td)),
                ("snapshot_translation", _bench_snapshots),
                ("placeholder_writes",   lambda: _bench_placeholders(td)),
                ("worker_contract",      _bench_workers),
            ]
            for key, fn in sections:
                try:
                    # Test hook: force failure in the named section.
                    if _FORCE_FAIL_SECTION and key == _FORCE_FAIL_SECTION:
                        raise RuntimeError(
                            f"[TEST HOOK] Forced failure in section '{key}'"
                        )
                    pairs = fn()
                    all_results[key] = {label: st for label, st in pairs}
                except Exception as exc:  # noqa: BLE001
                    err_str = str(exc)
                    print(f"\n  SECTION FAILED [{key}]: {err_str}")
                    all_results[key] = {"_section_error": err_str}
                    section_errors.append((key, err_str))

    except Exception as exc:  # noqa: BLE001
        print(f"\nHarness internal error: {exc}")
        return 1

    # -- Write baseline artifacts (always, even on partial failure) ----------
    proof_dir = _PROJECT_ROOT / "audit" / "phase2_step4_proof"
    proof_dir.mkdir(parents=True, exist_ok=True)

    run_failed = len(section_errors) > 0
    baseline = {
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "machine":          platform.node(),
        "python":           sys.version.split()[0],
        "reps":             f"{REPS} (cpu-bound) / {REPS_IO} (io-bound)",
        "warmup":           WARMUP,
        "run_failed":       run_failed,
        "section_failures": [
            {"section": k, "error": e} for k, e in section_errors
        ],
        "results":          all_results,
    }
    json_path = proof_dir / "perf_baseline.json"
    json_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(f"\nJSON baseline written: {json_path}")

    # Markdown summary
    status_hdr = (
        "**STATUS: FAILED** (see section_failures below)"
        if run_failed else "**STATUS: OK**"
    )
    lines = [
        "# perf_baseline.md - Phase 2 Step 4 Baseline",
        status_hdr,
        f"**Timestamp:** {baseline['timestamp']}",
        f"**Machine:** {baseline['machine']}",
        f"**Python:** {baseline['python']}",
        f"**Reps:** {REPS}  **Warmup:** {WARMUP}",
        "",
    ]
    if run_failed:
        lines += ["## SECTION FAILURES", ""]
        for k, e in section_errors:
            lines.append(f"- **{k}**: {e}")
        lines.append("")

    for section, data in all_results.items():
        lines.append(f"## {section}")
        lines.append("")
        lines.append("| benchmark | count | mean us | median us | p95 us | max us |")
        lines.append("|---|---|---|---|---|---|")
        for label, st in data.items():
            if label == "_section_error":
                lines.append(f"| SECTION ERROR | - | - | - | - | {st} |")
            else:
                lines.append(
                    f"| {label} | {st['count']} | {st['mean_us']} | "
                    f"{st['median_us']} | {st['p95_us']} | {st['max_us']} |"
                )
        lines.append("")

    md_path = proof_dir / "perf_baseline.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Markdown baseline written: {md_path}")

    print("\n" + "=" * 72)
    if run_failed:
        print(f"Perf probe FAILED: {len(section_errors)} section(s) had errors.")
        for k, e in section_errors:
            print(f"  FAILED SECTION [{k}]: {e}")
        return 1

    print("Perf probe complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
