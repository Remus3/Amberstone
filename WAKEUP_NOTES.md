# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s116 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s119 wrap — 2026-05-08 (Roadmap — 5 items shipped)

## What shipped
- **Phase 4 SessionStart enrichment** (`tools/rc_facts.py`, d069e4d): `_watcher_summary()` adds bridge watcher pid/cadence/queue/auto_ok/err/suppressed (since boot) + esc_24h as a Legion section line. Bridge section gains 24h activity counts (tasks/results/notes). `267014` added to allow-list → RC-VisionServer no longer fires as false anomaly.
- **DS startup diagnostics** (`tools/start_daemon_slayer.py`, 04e63d4): wraps `serve_forever()` in try-except; appends timestamped entries to `logs/daemon_slayer_startup.log` on port-skip, startup, and failure. Next task failure will be diagnosable.
- **SR coach objective_window fix** (`coach_integration.py`, e8d976b): `_state_signature` now has a fallback for `objective_window=None` → reads `objective_timers` dict, emits 1 when dragon/baron < 90s. All 5 non-obvious key mismatches are now fixed. 53 coach tests pass.
- **Bridge introspection** (`dashboard/_bridge_log.py` + `routes_bridge.py`, 5a790d2): `bridge_since()` gains `source` kwarg; `/api/bridge` route adds `?source=<node>&hours=N` params. Example: `?source=gamepc&kind=result&hours=24` → 20 entries. Default limit 20→100.
- **ROADMAP closures**: items_index auto-rotation (already in `cmd_all()`), vision_token rotation policy (documented, next rotation ~2026-08-01).

## Do NOT redo
- RC-VisionServer `result=267014` is now in the allow-list. It's no longer an anomaly.
- RC-DaemonSlayer `result=1` (from May 5) — server IS running via a manual start on May 6. Not a functional problem; diagnostic logging will capture the next failure.
- `coach_integration.py` is NOT frozen (memory was wrong). The objective_window fix was safe to make directly.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **TFT 17.3** — due ~2026-05-12. Same process as 17.2.
4. **Bridge Watcher acceptance-criteria** — need 50+ auto-action samples; currently 0.
5. **Auto-ops verb expansion** — after 95% success rate.
6. **RC dev mode toggle** — next unblocked Future item: dev panel with fixture switcher, force-vision, log tail.
7. **Investigate RC-DaemonSlayer exit 1** — check `logs/daemon_slayer_startup.log` after next reboot.

---

# s118 wrap — 2026-05-08 (Bridge Watcher node-load restraint)

## What shipped
- **Bridge Watcher node-load restraint** (`bridge_watcher.py`, commit f3ae4cb): `_check_rc_health(health, now)` pure function checks RC alive/last_reload_ok/booting/heartbeat age/restart grace. When RC is degraded, auto-action lanes downgrade to escalate for that poll cycle. Push notifications suppressed during RC-degraded cycles. New heartbeat fields: `auto_suppressed_since_boot` + `auto_suppressed_24h`. 9 new selftests at boundary inputs; 30/30 pass. Watcher restarted at pid=15004.
- **DDragon "16.9.1" is correct** — Riot uses year-based marketing versions (26.9) but DDragon API version string stays "16.9.1". Data pipeline is current, not stale.

## Do NOT redo
- Bridge watcher node-load restraint is preventive hardening, not a fix for observed harm. The feature is intentionally conservative (120s grace, 60s staleness threshold).
- DDragon version issue was a false alarm — no pipeline change needed.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **TFT 17.3** — next patch due ~2026-05-12. Same update process as 17.2.
4. **Bridge Watcher acceptance-criteria** — watch `auto_ok_since_boot` vs `auto_err_since_boot`; target ≥90% read / ≥95% ops.
5. **Auto-ops verb expansion** — needs 95% success rate first; check heartbeat before enabling.

---

# s117 wrap — 2026-05-08 (TFT patch 17.2 — Encounters + God Blessings)

## What shipped
- **TFT patch 17.2 update** (commit be3d168): Current League patch is 26.9 (year-based numbering) = TFT patch 17.2 (April 28, 2026).
  - `tft_pbe_engine.py` system prompt: Encounters section (16 returning + 5 new), God Blessings section (24 choices across 6 gods), trait balance changes (Timebreaker rework, Meeple nerf, Stargazer Fountain disabled, Anima buff).
  - `tft_pbe_data.py`: new `ENCOUNTERS` dict (21 entries), new `GOD_BLESSINGS` dict (24 choices), Timebreaker breakpoints corrected [2,3,4], trait notes updated.
  - `data/meta/tft_set17_meta.json`: `_patch` bumped to `17.2`, `_patch_notes_17.2` key added.
- RC restarted clean (pid=11716).

## Do NOT redo
- DDragon still reports version "16.9.1" (stale cache). Actual current League patch is 26.9 (year-based numbering). TFT patch follows TFT set versioning (17.2), not League patch numbers.
- `tft_data.py` (legacy Set 14 file) is fine as-is — only used for TIER_ODDS/XP tables by the old coach engine; active TFT coaching runs through `tft_pbe_engine.py`.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **DDragon version cache** — `data/meta/ddragon_version.json` shows 16.9.1; actual patch is 26.9. `data_pipeline.py ddragon` won't re-download since it thinks it's current. Low urgency — coaching data is functional.
4. **TFT 17.3** — next patch due ~2026-05-12; repeat this process when it drops.
5. **Bridge Watcher acceptance-criteria** — accumulates naturally.


