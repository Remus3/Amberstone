"""Background poll for in-game audit. Runs ~10 minutes, samples every
15 s, appends one JSONL row per sample. Stop with Ctrl-C or the
runtime cap. Writes to data/.audit-ingame.jsonl (gitignored)."""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / ".audit-ingame.jsonl"
TOK  = (ROOT / "config" / "vision_token.txt").read_text(encoding="utf-8").strip()

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _get(url: str, *, auth: bool = False, timeout: float = 4.0):
    headers = {"X-RC-Token": TOK} if auth else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(
            req, context=CTX if url.startswith("https") else None, timeout=timeout
        ) as r:
            return json.load(r)
    except Exception as e:
        return {"_error": str(e)[:120]}


def sample() -> dict:
    h     = _get("https://127.0.0.1:8888/api/health/all")
    vstat = _get("http://127.0.0.1:8889/stats", auth=True)
    fmeta = _get("http://127.0.0.1:8889/latest-frame/meta", auth=True)
    lcu   = _get("http://127.0.0.1:8889/latest-lcu", auth=True)
    lc    = _get("http://127.0.0.1:8889/latest-liveclient", auth=True)
    cost  = _get("https://127.0.0.1:8888/api/cost")
    trace = _get("https://127.0.0.1:8888/api/coach/trace?limit=3")
    s = (vstat or {}).get("stats", {}) if isinstance(vstat, dict) else {}
    now = time.time()
    return {
        "ts":           now,
        "ts_iso":       time.strftime("%H:%M:%S"),
        "rollup":       h.get("status"),
        "rc_pid":       (h.get("rc") or {}).get("pid"),
        "vision_uptime_s": (h.get("vision") or {}).get("uptime_s"),
        "vision_calls":  (s.get("vision") or {}).get("calls", 0),
        "vision_ms":     (s.get("vision") or {}).get("total_ms", 0),
        "coach_calls":   (s.get("coach")  or {}).get("calls", 0),
        "ocr_calls":     (s.get("ocr")    or {}).get("calls", 0),
        "frame_uploads": (s.get("frame_upload") or {}).get("calls", 0),
        "lcu_uploads":   (s.get("lcu_upload")   or {}).get("calls", 0),
        "lc_uploads":    (s.get("liveclient_upload") or {}).get("calls", 0),
        "frame_age_s":   round(now - (fmeta.get("ts") or 0), 1) if fmeta.get("ts") else None,
        "lcu_phase":     (lcu.get("data") or {}).get("phase") if isinstance(lcu.get("data"), dict) else None,
        "lcu_age_s":     round(now - (lcu.get("ts") or 0), 1) if lcu.get("ts") else None,
        "liveclient_state": "present" if not lc.get("error") else lc.get("error"),
        "lc_age_s":      round(now - (lc.get("ts") or 0), 1) if lc.get("ts") and not lc.get("error") else None,
        "cost_usd":      (cost.get("spend") or {}).get("total_usd", 0.0),
        "cost_calls":    (cost.get("spend") or {}).get("calls", 0),
        "trace_records": len(trace.get("records") or []),
    }


def main(runtime_s: float = 720, interval_s: float = 15) -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("", encoding="utf-8")
    deadline = time.time() + runtime_s
    n = 0
    print(f"audit monitor: interval {interval_s:.0f}s, runtime {runtime_s/60:.0f}min, out -> {OUT}")
    while time.time() < deadline:
        try:
            row = sample()
        except Exception as exc:
            row = {"ts": time.time(), "_sample_error": str(exc)[:200]}
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        n += 1
        # Print a compact line so a tail -f shows progress.
        print(f"  {row.get('ts_iso','?')} phase={row.get('lcu_phase','?'):<12} "
              f"vision={row.get('vision_calls',0):>4} coach={row.get('coach_calls',0):>4} "
              f"cost=${row.get('cost_usd',0):.4f} trace={row.get('trace_records',0)}",
              flush=True)
        time.sleep(interval_s)
    print(f"audit monitor: done. {n} samples.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
