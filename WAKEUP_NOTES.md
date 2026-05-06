# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s103 archived to `docs/history_notes.md`. Only the last 2 sessions kept here.

---

# s107 wrap — 2026-05-06 (API cost audit + dynamic debounce + CLAUDE.md slim)

## What shipped
- **Vision loop gate** — `_run_vision()` guards in ARAM/Arena/Brawl coaches: `if self._fetch_game_data() is None: return`. Kills 24/7 Sonnet burn when no game is active (was 84% of LoLOverlay key spend on May 4).
- **Dynamic debounce** — all 3 coaches: `_STABLE_DEBOUNCE_S` class attr (ARAM 25s / Arena 22s / Brawl 20s). `_on_state_received` sets `self._DEBOUNCE_S` to stable rate when no meaningful state change; snaps back to fast rate on dead_enemies / items / level / hp_pct drop ≥10.
- **CLAUDE.md slimmed** from 355→109 lines. Deep docs moved to `docs/AGENTS.md` (new) + `docs/DAEMON_SLAYER.md` (new). Bridge spawn cost note added.
- **Settings cleanup** — both `.claude/settings.json` files: removed `typescript-lsp` plugin; `additionalDirectories` `C:/` → `C:/Riot Commander`.
- **Per-machine API key note** added to CLAUDE.md (LoLOverlay retired shared key → riot-commander-legion/gamepc/peer).
- **WAKEUP_NOTES archiving** — s92–s103 + ledger table moved to `docs/history_notes.md`; WAKEUP_NOTES trimmed to last 2 sessions.

## Do NOT redo
- Vision gate is in all 3 coaches. Do not add it to `_base_coach.py` (frozen).
- Dynamic debounce uses `type(self)._DEBOUNCE_S` (class-level default), not a hardcoded constant — correct intentionally.
- CLAUDE.md is now intentionally short (~109 lines). Do not pad it back.

## Open work (priority order)
1. **Bridge tasks** — update Game-PC + Peer `.claude/settings.json` (remove typescript-lsp, narrow additionalDirectories); propagate WAKEUP_NOTES archiving convention
2. **`~/.claude/commands/wrap.md`** — add session-size check step (warn if current `.jsonl` > 10MB)
3. **`~/.claude/commands/done.md`** — add §6c WAKEUP_NOTES archiving step
4. **UNIVERSAL_FILES review** — `C:\Users\Administrator\Desktop\UNIVERSAL_FILES\` files 2–5 accuracy updates; create file 6 (step-by-step usage guide)
5. **RC-VisionServer failing** (last_result=267014) — investigate pythonw path in task XML
6. **Peer daemon install** — confirm `~/peer_bridge_daemon_health.json` on Peer
7. **DS calibration** — accumulate 50+ games in `data/ds_calibration.jsonl`
8. **Vision regions calibration** — tune `data/vision_regions.json` bboxes

---

# s106 wrap — 2026-05-05 (DaemonSlayer flash fix + preflight expansion)

## What shipped
- **`ops/RC-DaemonSlayer.xml`** — `python.exe` → `pythonw.exe`; task reinstalled. No more console flash on boot/restart. DS live at `:8893` engine=0.60.0 patch=16.9.1.
- **`start_claude.ps1`** — added RC-DaemonSlayer + RC-Phase3-Supervisor + RC-BridgeWatcher preflight checks; `:8893` + `:8890` HTTP probes; final `claude` launch fixed to `--name "Legion"`. commit `0d1b545`.

## Do NOT redo
- RC-DaemonSlayer XML is already pythonw.exe.

## Open work (carry-forward from s106)
1. **RC-VisionServer failing** (last_result=267014) — check pythonw path + whether SYSTEM context can find moon_vision_server.py.
2. **Peer daemon install** — confirm `~/peer_bridge_daemon_health.json` exists on Peer.
3. **DS calibration**: 50+ games needed; auto-collects into `data/ds_calibration.jsonl`.
4. **Vision regions calibration**: tune `data/vision_regions.json` bboxes.
