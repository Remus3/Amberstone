# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s152 wrap — 2026-05-09 (DS pill in header + ARAM Build-row fallback + match-record wire)

## What shipped (commits `091d18c` + `0bed0cc`)
- **`#ds-pill` in header row 2.** New glanceable surface for the engine's top pick — `◆ <Item> +Ndps`, info-blue (distinct from gold augments-pill). [web/index.html:113](web/index.html:113), [web/css/panels/map_state.css:166](web/css/panels/map_state.css:166), [web/js/panels/item_build.js:265](web/js/panels/item_build.js:265). Sig-keyed paint so cadence churn doesn't flicker; mode-gated to in-game (CSS hides client/tft).
- **Next/ARAM `Build` row DS fallback.** [web/js/panels/next.js:130](web/js/panels/next.js:130) — when the coach hasn't emitted `item_extra` or `objective`, the row falls back to `DS: <name> +Ndps (Ng)` from `daemon_slayer_picks[0]`. Coach copy still wins when present (precedence preserved). Both branches verified live via Playwright direct-import eval.
- **Match-record DS wire.** `performance_tracker._ds_picks_snapshot(sd, category)` reads the per-mode coaching JSON and folds the engine's last DS pick set into `matches.raw_data["daemon_slayer_picks"]` at game-end save. Calibration analysis loses the JSONL ⨝ on (champion, mode, ~ts) — single SELECT now covers it. [performance_tracker.py:48](performance_tracker.py:48) + [performance_tracker.py:340](performance_tracker.py:340).
- **8 new tests** in `tests/phase2_smoke/test_perf_tracker_ds_snapshot.py` — category mapping pin (SR/ARAM/ARENA/BRAWL only; TFT explicitly excluded) + soft-fail paths (missing file, unparseable JSON, wrong field type, non-dict top-level). **Total suite: 624 pass** (was 616).
- **Smoketested live**. Header pill rendered `Stormrazor +54dps` from real coach state. RC reload (PID 2388) clean.

## Key decisions
- **Co-locate DS pill render with item-build panel.** `IB.dsPill` ref + paint live in [panels/item_build.js](web/js/panels/item_build.js); no separate panel module. Single source of truth for any DS-related render — chips + pill update in lock-step from one `dsPicks` array.
- **Build row uses fallback, not replacement.** Coach copy ALWAYS wins when present. The DS surface is a "fill the gap" path — the engine fires every coaching cycle so the row is never empty.
- **DB wire reads from coaching JSON, not in-flight rank_for() call.** Decoupled from coach lifecycle; if save_rating fires after coach has stopped writing, picks are still readable from the on-disk file. Soft-fails to `[]` so DS persistence is observability, never gates the match save.
- **TFT explicitly excluded from `_DS_COACH_FILE_BY_CATEGORY`.** TFT has no DPS framework — pinning the mapping in tests so a future "wire TFT" change is deliberate.

## Follow-up still open (NOT shipped)
- **`map_state.js:720` `gameTime is not defined`** — STILL pending from s151. Bare `gameTime.textContent` at line 720; line 721 is the working `MM.gameTime.textContent`. Fires once per second on every page load; visible in console as ~200 errors per session. Suggested fix: delete line 720.

## What's next
- `map_state.js:720` cleanup — 1-line delete, 30-second job, has been pending since s151.
- **FU01 minimap-locate** — independent + ready anytime. Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- **Don't redo:** DS pill + Build-row fallback + raw_data wire are shipped end-to-end. Tests pass. Don't re-add the pill to a different header row, and don't move the DS render out of `panels/item_build.js`.

## Blockers
- None.

---

# s151 wrap — 2026-05-09 (augment-pill flicker fix + ESM-split _ibBuilds orphan)

## What shipped (commit `8db992b`)
- **Augment-pill flicker root-cause fix.** `dashboard/_state_builder.py:117` now passes `aram_mode/arena_mode/brawl_mode/tft_mode` through the trimmed health envelope. Without them, JS `onHealth` fell through to `tag="sr"` whenever `has_game=True` and no specific flag was set, racing `onState`'s `mode_key="arena"` from the same `/api/state` payload — `body[data-mode]` flapped every cadence cycle, flashing every mode-gated CSS rule (augments-pill the most visible casualty).
- **`_ibBuilds` orphan const fixed.** Const declaration moved from `web/js/panels/champ_select.js:207` (referenced nowhere in that module post-split) into `web/js/panels/item_build.js:264` next to its 17 callers. Phase 3 ESM split moved the references but left the data behind. Every `renderItemBuild` call with `state.mode in {sr,aram,brawl}` + champion known had been throwing `ReferenceError`, silently aborting the rest of `onState` (Minimap/Stats/GameSense/WhatWent/Digest/Adaptation never reached). Arena/TFT/client hit the early-return so the regression hid behind recent Arena play.
- **Verified end-to-end via Playwright.** `renderItemBuild` confirmed throw-free on sr/aram/brawl/arena. `champ_select.js` exports still callable. Synthetic arena payload renders 2 Recommended + 3 Owned tiles + 3 DS chips, in that order — DS does NOT replace Item Build, it's a sibling section. API smoke 6/7 200 (`/api/ds-preview` correctly POST-only).

## Key decisions
- **Patched at the data-pass-through layer, not the JS dispatcher.** `_state_builder.py` is the canonical health-envelope assembler; surfacing the four mode flags fixes the flicker for both `/api/state` REST polls and the `/api/state-stream` SSE channel in one edit. JS `onHealth` left as-is.
- **Moved `_ibBuilds`, didn't duplicate it.** `champ_select.js` had no remaining call sites; declaring it in two modules would just invite the next forgotten edit.

## Follow-up still open (NOT shipped)
- **`map_state.js:720` `ReferenceError: gameTime is not defined`** — same Phase 3 ESM split miss. Bare `gameTime.textContent = str` at line 720, while line 721 is the working `MM.gameTime.textContent = str`. Fires once per second on every page load. Suggested fix: delete line 720 (line 721 covers it). Reported but left for separate session — out of scope after the user approved the `_ibBuilds` fix.

## What's next
- `gameTime` cleanup at `map_state.js:720` — 1-line delete, 30-second job.
- **FU01 minimap-locate** — independent + ready anytime. Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- **Don't redo:** augment-pill flicker is fixed at the source (state-builder); don't go patching `onHealth` in main.js. `_ibBuilds` is now in `panels/item_build.js` — don't re-add it to `champ_select.js`.

## Blockers
- None.

---

# s149 wrap — 2026-05-09 (LCU agent → /api/team-context/refresh wiring)

## What shipped
- **FU02 last mile** (commit `e7b5af1`): Game-PC `tools/gamepc_lcu_agent.py` now POSTs the 10-player roster (with PUUIDs) to Legion `:8888/api/team-context/refresh` on ChampSelect entry + on lock/swap. Bearer auth via `bridge_shared_secret`. +238 LOC, no removals.
- **Bridge-secret resolver**: `RC_BRIDGE_SECRET` env → `bridge_secret.txt` → `local_paths.json{bridge_shared_secret}` → `""`. Empty = warn-once + skip POST (no historical default).
- **Champion-id → name cache**: lazy-loaded once per agent boot from LCU's `/lol-game-data/assets/v1/champion-summary.json`. Unknown ids translate to `""` so the dashboard renders blank rather than numeric garbage.
- **Edge-trigger semantics**: POSTs on (a) entering ChampSelect, (b) `(cellId, championId)` signature change. Rate-limited to `TEAM_CONTEXT_REPOST_S=3.0s` between re-fires; resets state on leave so next CS always re-fires the initial POST. Failure isolated from `/upload-lcu` cadence.
- **30 new tests** in `tests/fu02_team_context/test_lcu_agent_refresh.py`: resolver priority, pick-signature stability, body translation, POST helper, edge-trigger rate-limit + leave-reset + failure-doesn't-latch. **Total suite: 595 pass** (was 565). Ruff clean.
- **Game-PC deployed live**: `bridge_secret.txt` written via gamepc MCP, agent fetched from `:8888/agent/`, RC-LCU restarted (PID 16080). Resolver self-test confirmed `secret_len=43 first4=at_Y last2=WQ`. `/api/team-context` returns `null` cold, ready to fill.
- **Docs sync**: `tools/GAMEPC_CLAUDE.md` now documents the new POST + the bridge-secret deploy steps.

## Key decisions
- **Stdlib-only on Game-PC.** No `from core import bridge` — agent runs from `C:\RC-Agent\` where the project tree isn't importable. File-based resolver mirrors the pattern in `bridge_watcher_health_publisher.py:_resolve_token`.
- **Send display-name strings, not numeric ids.** Route's `_skeleton_entry` stores `locked_champion: str` for direct dashboard render; route's `_champ_name_to_id()` reverses via DDragon for mastery. Sticking with the FU02-shipped contract avoided a server-side schema change.
- **Edge-fire from `_state_push_loop`, not a new thread.** POST is fire-and-forget over Tailnet (~200ms) and only runs once per change. Spawning a fourth thread for one-shot POSTs was overkill.
- **`puuid` added to `_team_picks()` snapshot** — also makes /upload-lcu consumers richer with no new endpoint shape needed.

## What's next
- **Live verification** — waiting on next CS pop. Watch for `[team-context] refresh OK queue=… roster=…` in agent stdout (hidden — easier probe: `curl -k https://127.0.0.1:8888/api/team-context | py -m json.tool`).
- **FU01 minimap-locate** — still independent. 3-path resolver for `agents/supervisor.py:597`. Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- **Don't redo:** FU02 wiring is shipped end-to-end (panel + fan-out + LCU agent). Bridge secret is on Game-PC (`C:\RC-Agent\bridge_secret.txt`). Agent (PID 16080) is healthy and heartbeating.

## Blockers
- None. Verification is observational — picks itself up on the next champ-select.
