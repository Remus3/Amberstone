# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s115 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

---

# s116 wrap — 2026-05-08 (Game-PC boot fix + Smite jungler detection)

## What shipped
- **`gamepc_boot.ps1`** (commit 1ef54e3 + 2229d89): now calls `start_gamepc_claude.ps1` at end of boot sequence so Claude window actually appears. `start_gamepc_claude.ps1` updated to open a plain interactive session (no `/loop` — RC-BridgeDaemon handles automated task processing). Scheduled task installs now use absolute python.exe path (fixes `py` ERROR_FILE_NOT_FOUND in task-scheduler context).
- **Smite-based jungler detection** (`game_reader.py`, commit 6bec3ce): `_has_smite(player)` static method checks `summonerSpells` dict. `_gank_threat` now uses 3-tier cascade: zone-based → Smite → `_JUNGLE_CHAMPS` name heuristic. Same order for ally jungler. Any champion playing jungle (including off-meta picks and new releases) now correctly detected without manual list updates. 8 new tests, 237 pass.

## Do NOT redo
- `_JUNGLE_CHAMPS` is intentionally kept as tier-3 fallback for relay warm-up frames where summoner spell data may be absent.
- The `/loop 1m /process-bridge-tasks` removal from `start_gamepc_claude.ps1` was requested by Game-PC Claude via bridge task.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game; fresh match data needed for DS calibration correlation.
2. **Vision regions calibration** — blocked on live game.
3. **TFT Set data** — `tft/tft_data.py` seeded for Set 14/patch 15.x; current is 16.9.1. Requires web research for current set champions/traits/items. Scope is significant.
4. **Bridge Watcher acceptance-criteria** — accumulates naturally with real traffic.
5. **Cross-Claude Phase 4** — low urgency.



