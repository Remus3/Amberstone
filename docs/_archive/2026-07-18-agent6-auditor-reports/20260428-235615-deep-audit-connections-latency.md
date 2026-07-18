# RC Deep Audit - connections, smoke-tests, efficiency, latency, OCR setup

- **Date:** 2026-04-28 18:56 America/Chicago (23:56 UTC)
- **Branch:** main @ 7995e96 (after batches 1-12 + dot-row fix)
- **Trigger:** user-requested full diagnostic pass
- **Method:** live probes against running RC + vision server + agents :8890 +
  Game-PC LAN; no code changes from this audit (read-only).

## Verdict: 🟢 GREEN - every component reachable, no errors.
Two cosmetic anomalies to address (`RCVisionServer` dupe task,
`rewind_history.db` size). Everything else clean.

---

## 1. Topology & connection map

| Component | Address | State | Detail |
|---|---|---|---|
| RC app (main.py) | local | ✅ pid 8772, alive, mode=client, ui_age 0.5 s, last_reload_ok | |
| ops/rc_supervisor | local | ✅ pid 8280, run_id `28f0a06c...`, oslock held, uptime ≈ 93 min | |
| Vision server :8889 | local | ✅ alive, uptime ≈ 8476 s (≈ 2 h 21 m), api_key_ok | |
| Web dashboard :8888 (HTTPS) | local | ✅ all 16 probed routes 200 | |
| Phase 3 agents :8890 | local | ✅ /api/activity 200; /health is HTML 404 (expected, distinct supervisor) | |
| Game-PC | 192.168.8.237 | ✅ ping 0 % loss, 0 ms avg | |
| Game-PC screen agent | → vision :8889/upload-frame | ✅ 4237 uploads, 0 errors, 3.16 GB total, every 2 s | |
| Game-PC LCU agent | → vision :8889/upload-lcu | ✅ 8327 uploads, 0 errors, every 1 s, phase=`Offline` (League closed) | |
| Game-PC liveclient relay | → vision :8889/upload-liveclient | ⚪ 0 uploads (League not running - relay only emits during a live game; this is correct) | |

**Active processes (RSS):**
- 8772 main.py - 40.2 MB
- 1560 agents.supervisor - 27.4 MB
- 9724 moon_vision_server - 8.5 MB
- 8280 rc_supervisor - 5.6 MB

Healthy footprint; no process is leaking.

---

## 2. Endpoint smoke test

All 16 routes returned **HTTP 200**:

| Endpoint | Time | Bytes |
|---|--:|--:|
| /api/health | 4.0 ms | 642 |
| /api/health/all | 2.8 ms | 924 |
| /api/state | 57.6 ms (median 2.0 ms) | 628 |
| /api/cost | 2.2 ms | 196 |
| /api/coach/state | 1.8 ms | 98 |
| /api/coach/trace?limit=3 | 2.3 ms | 15 |
| /api/logs?n=5 | 4.9 ms | 633 |
| /api/replay/matches?limit=3 | 6.2 ms | 675 |
| /api/replay/match/&lt;id&gt; | 7.2 ms | 74 580 |
| /api/recommend-champ (cold) | 474 ms | 658 |
| /api/recommend-champ (warm) | 143 ms (median) | - |
| /api/home/summary | 10.1 ms | 1 628 |
| /api/diagnostics | **2 019 ms** | 5 853 |
| /api/session/summary | 3.6 ms | 1 418 |
| /api/history?scope=14d | 26.0 ms | 14 756 |
| /api/champions | 3.5 ms | 7 651 |
| /api/ui-version | 2.3 ms | 21 |

**Defenses verified:**
- ✅ CSRF cross-origin POST → HTTP 403 (`{"error":"cross_origin"}`)
- ✅ CSRF same-origin POST → HTTP 200 (passes through to handler)
- ✅ Asset hash injected: index.html serves `?v=0a2ae15fe4` for css + js
- ✅ Vision token source: `config` (legacy fallback retired)
- ✅ Supervisor PID lock: second-acquire blocked by msvcrt OS lock

---

## 3. Round-trip latency (5-sample, warm)

| Path | min | med | max | Notes |
|---|--:|--:|--:|---|
| Vision /health | 9.8 | 9.8 | 9.8 ms | one-shot |
| Vision /latest-frame/meta | 0.4 | 0.4 | 0.4 ms | in-memory, no decode |
| Vision /latest-lcu | 0.3 | 0.3 | 0.3 ms | in-memory |
| /api/state | 1.6 | 2.0 | 28.1 ms | first sample includes JSON parse warmup |
| /api/health/all | 2.2 | 2.5 | 2.5 ms | fans out to vision + supervisor.pid + cost |
| /api/cost | 1.9 | 2.0 | 2.0 ms | reads today's spend ledger |
| /api/replay/match | 6.6 | 6.9 | 6.9 ms | full match (10 parts × 36 frames + 77 kills) |
| /api/recommend-champ | 142.3 | 143.4 | 159.7 ms | KDA aggregation across 2.5M timeline events |
| /api/ocr | - | 562 ms | - | 11 ms server overhead + **551 ms Tesseract** |

**OCR is the slowest hot path.** Tesseract on a 3840×1280 frame across all 29
configured fields takes ~550 ms - that's the cost of a `/api/ocr` call. The
parallel ThreadPoolExecutor in `core/vision_tesseract.read_fast_fields` already
fans out across cores; further wins need either smaller crops or fewer fields.

---

## 4. Storage & efficiency

### Database sizes
| File | Size |
|---|--:|
| **data/rewind_history.db** | **1.67 GB** |
| data/match_metrics.db | 30.8 MB |
| data/db/aram.db | 22.1 MB |
| data/rewind_cache/history.json | 9.3 MB |
| data/db/sr_ranked.db | 4.8 MB |
| data/decisions.db | 0.6 MB |
| data/match_history.db | 0.1 MB |

`rewind_history.db` is dominant - that's the cost of 645 982 timeline frames +
2 516 873 events. Acceptable for a local-first dataset; bears watching as it
grows. WAL files are < 32 KB so no checkpoint pressure.

### Logs
- Today's log: 1.59 MB (2 h of operation)
- `logs/` total: 140.4 MB (30-day retention by `_prune_old_logs`)

### Spend ledger
- `data/spend/2026-04-28.json` not yet created → no Anthropic API calls today
  (League not running, no coach loops fired). cost_tracker telemetry works only
  when a real call records into it; absence here is correct, not a bug.

### Vision-server throughput
- 4237 frame uploads / 8476 s ≈ **0.50 fps** (matches Game-PC agent 2-s cadence)
- 8327 LCU uploads / 8476 s ≈ **0.98 / s** (matches LCU agent 1-s cadence)
- Both 0 errors - agents stable.

---

## 5. Anomalies / concerns

### ✅ Duplicate scheduled task - RESOLVED 2026-04-28
```
\RC-VisionServer    Running   last 4/28/2026 4:34 PM   result 267009 (running)
\RCVisionServer     Ready     last 4/28/2026 3:21 PM   result 0      (success)
```
Two tasks pointed at the same vision server. The currently-running one is
`RC-VisionServer` (with hyphen); the duplicate `RCVisionServer` (no hyphen)
would have collided on port 8889 if it ever fired alongside.

**Action taken** (post-audit): `schtasks /Delete /TN RCVisionServer /F` →
SUCCESS. Verified `RC-VisionServer` still Running, /health alive
(uptime 8978 s).

### 🟡 /api/diagnostics is 2 s
The dashboard's diagnostics view fans out to several heavy probes (DB
introspection, log tail, RC + vision health). 2 s is acceptable for an on-
demand view but would be too slow if anything polled it. Today nothing does.

### 🟢 Recommender cold latency
`/api/recommend-champ` first call ≈ 474 ms (subsequent ≈ 143 ms). Cause: the
KDA query joins `timeline_events` (2.5M rows) with `participants` per
champion. Sqlite caches pages so repeats hit the page cache. Future
optimization: a nightly materialized view at `data/coach_reference/champ_kda.json`
to make warm-cache the only path. Optional, not blocking.

### ⚪ liveclient relay 0 uploads
Expected when the League client is closed. The relay process only emits when
:2999 has a live game. Test will be incomplete until you launch a game.

---

## 6. OCR setup guidelines (for when you want to recalibrate)

The Tesseract pipeline is wired and working. Calibration is the manual step
that pins each HUD region to the right pixels.

### Current state
- **Pinned binary:** `C:\Program Files\Tesseract-OCR\tesseract.exe`
- **Regions file:** `data/vision_regions.json` (29 fields)
- **Base resolution:** 1920×1080 (declared via top-level `_base` key)
- **Detected frame:** 3840×1280 (Game-PC agent stitches monitor 0 + 1)
- **Auto-scale:** `core/vision_tesseract._scale_bbox` proportionally maps
  (1920×1080 → 3840×1280) at crop time. So a `timer` bbox of
  `[1857, 4, 1903, 26]` is automatically rescaled to `[3714, 4, 3806, 30]`
  when the actual frame is processed.

### Calibration workflow (when needed)

1. **Capture a reference frame** while a live game is in progress. Easiest:
   `curl -k -H "X-RC-Token: $(cat config/vision_token.txt)" \
   http://127.0.0.1:8889/latest-frame > frame.json`
   then base64-decode the `b64` field into `frame.png`.
2. **Identify HUD regions visually.** Use any image tool that shows pixel
   coordinates. Note bboxes in the actual frame's coordinate space first
   (whatever resolution it actually is).
3. **Convert back to the declared base.** If the captured frame is
   3840×1280, divide each x by 2 and each y by 1280/1080 ≈ 1.185 to land
   in the 1920×1080 reference. Or write the bboxes directly in the
   captured resolution and update `_base` in `vision_regions.json` to
   match - same outcome, less arithmetic.
4. **Live-preview a single field** to verify:
   `curl -sk "https://127.0.0.1:8888/api/ocr-crop?field=timer" | jq -r .b64
   | base64 -d > timer.png` then visually inspect.
5. **Reload regions live** without restarting RC:
   `curl -sk "https://127.0.0.1:8888/api/reload-regions"`
6. **Validate against ground truth** with `/api/validate-ocr` while a game
   is live - it cross-checks Tesseract output against the Live Client
   API's authoritative HP / mana / level / gold / KDA / CS values.

### Field cadence
`core/vision_tesseract` already implements:
- **Slow fields** (timer, score, cs, ping, fps): read every 5th call,
  cached otherwise.
- **Fast fields** (HP, mana, gold, kda, ult-ready bools): read every call.
- **Drop set** (`configure_drop_fields`): when Live Client API is fresh
  (< 3 s), the dashboard tells the OCR layer to skip cs/kda/gold/level/
  hp/mana/timer because the API is authoritative - saves ~80 % of OCR
  work during a live game.

### Recommended additions if you go for a deep recalibration
- Per-resolution overlays: instead of one base, support `_base_3840x1280`,
  `_base_2560x1440`, etc. - pick the closest match at frame-decode time
  rather than scaling. Higher fidelity for non-aspect-matched displays.
- A `data/vision_regions.YYYYMMDD.json` snapshot per calibration so you
  can roll back if a tweak regresses the validate-ocr score.

Everything below the workflow is optional polish; the current pipeline
works and the auto-scale handles the resolution mismatch transparently.

---

## 7. Recommendations (prioritized)

| # | Priority | Action |
|---|---|---|
| 1 | ✅ done | `schtasks /Delete /TN RCVisionServer /F` - duplicate vision-server task deleted post-audit; survivor `RC-VisionServer` still Running, /health alive. |
| 2 | low | Consider a nightly job that materializes per-champion KDA aggregates from `rewind_history.db` into a small JSON, so `/api/recommend-champ` cold-call drops from 474 ms to ≈ 50 ms. |
| 3 | low | When you get back into a live game, re-run this audit so the `liveclient_upload` line + Sonnet vision-call latency are also captured. |
| 4 | info | Daily spend ledger will populate the moment a coach loop or vision call fires; the empty file today is correct. |

No action required for green health. Audit complete.
