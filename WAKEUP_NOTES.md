# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s218 wrap — 2026-05-15 (Home page redesign + foundation overhaul)

**Operator instruction:** "doing ui work" — open-ended iterative pass on the Home view. Closed out with "this page is done now. commit and /done".

## Shipped — single commit (`4518ed9`)

**Foundation (applies to all views going forward):**
- Pin RC menu width at 230px (static across views; fits longest case "AUTO · PRE-GAME LOBBY"). `.title-current` switched from min-width to fixed width per operator hard rule.
- Bump typography +1px globally — 414 declarations across 14 panel CSS files via Python script; RC menu rules (4 skipped) preserved per directive.
- Flip body zoom default 1.33 → 1.0 in `base.css`. Fixed dev.js/main.js localStorage key mismatch (slider wrote `rc-zoom`, page-load read `rc-body-zoom` — body was always 1.33 regardless of slider position). Both now use `rc-zoom`.

**Dev/Sim Preview removal** (separate concern operator green-lit mid-session):
- Drop `#view-dev` section + menu item + `#sim-banner` block.
- Delete `web/js/sim.js`, `web/css/panels/dev.css`, `dashboard/routes_dev.py`.
- Archive `data/sim/*` + `data/sim_states.json` → `docs/_archive/2026-05-15-dev-sim-removal/`.
- Scrub orphan refs across `agents/supervisor.py`, `dashboard/_state_builder.py`, `dashboard/_handler.py`, `dashboard/_static.py`, `riot-commander.spec`, `tools/extract_panels.py`, `web_dashboard.py`, `view_router_state.py`.

**Home view content:**
- **7-tile quick actions** in operator's order: Find Match · Last Match · Session · History · Replay · Builds · Settings. Equal-width centered tiles. Find Match accented with lavender gradient + info-soft border + lavender icon (primary action signal).
- **Find Match opens a Home-unique queue picker modal** (centered fixed-position, backdrop dimmer, Escape/outside-click close). Mirrors lobby-view's `#lv-mode-menu` queue list with `data-hfm-*` attributes. Click → fires `change_queue_type` LCU command → routes to Pre-Game Lobby. Two false-start iterations resolved: synthetic `.click()` on `#lv-mode-trigger` after route was racing with the document outside-click handler → final landed approach is `e.stopPropagation()` on tile click + direct DOM mutation of menu's `hidden` class.
- **Tonight's Pick 3-section restructure**: Section 1 = champion intro (icon + name + meta); Section 2 = THE GOOD / THE BAD / THE UGLY placeholder rows tagged `data-dummy-data="tonights-pick-tips"`; Section 3 = STREAK / ADVISORIES sub-header rows wired live to `_HOME.streaks` (play_days + good_grades) and `#advisory-count`. Layout: `grid-template-columns: auto 1fr 1fr` so Section 1 sizes to content + Section 2 starts at a finite boundary after "best B" text. Section 3 uses 88px label col + 16px gap (matches Section 2) for symmetric label-value spacing. "Open Advisories" → "Advisories" rename to fit column. 14px row-gap between Streak + Advisories rows.
- **Recent 5 row updates**: spell out "X Minutes" (was "Xm"), append CS + CS/min chip, 6-slot placeholder item strip tagged `data-dummy-data="items-pending-ingest"`. Card click → History view with `sessionStorage.rc-history-focus-ts` → auto-select date-matching session + scroll target row + pulse-highlight class for 3.5s.
- **This Week row updates**: KDA breakdown "1.8 22/10/18" (avg + raw totals), AVG CS per game + CS/min (operator clarified avg not total), grade-tint demoted from card-bg-tint to 3px left-border accent (transparent bg + bottom-only divider — operator wanted list, not cards). Bumped `.home-week-bar-kda-raw` 13 → 14px to separate hierarchy from 15px ratio pill.
- **Backend (`dashboard/builders.py`)**: `/api/home/summary` recent[] gains `cs`, `cs_per_min`, `items[]`, `mode_subtype`; this_week[] gains `kills`, `deaths`, `assists`, `cs_total`, `cs_per_min`. RC hard-restarted (pid 18628 → 15752) via `taskkill /F /PID + restart.bat` after `restart_trigger.txt` mechanism didn't consume two attempts.
- **Hero headline**: drop absolute-threshold `up/down` classifier (was rendering 1.27 KDA as `.down` salmon-red despite no comparison baseline). Always `.flat` text-dim until real yesterday-comparison baseline ships.
- **Tonight's Pick "Jinx" name → History filtered by champion**: clickable (cursor:pointer + green-tinted underline on hover) → `sessionStorage.rc-history-focus-champion` → `_historyFetchAndRender` finds most recent session containing that champion + highlights all matching match rows + scrolls to first.

**Footer + tooltip polish:**
- Footer height 44 → 36px, color `--text-faint` → `--text-dim`, line-height 1, all children `inline-flex; align-items: center`. ui-version pill opacity 0.6 → 0.85.
- `wrapSixWords` (tooltip system) was splitting on ALL whitespace (including `\n`) so multi-section tooltips collapsed into one long line. Now preserves explicit `\n` boundaries, wrapping each source line independently at 6 words → RC pip / health-dot multi-section tooltip renders per-row.

**Cleanup:**
- Drop orphan `.home-pick-btn*` CSS (advisory + digest pip-buttons that Section 3 redesign replaced).
- Drop orphan `wireAlertRow` calls in `_homeWireStartup`.
- Drop orphan `view-dev` CSS selectors in header.css.
- All edits verified: py_compile clean on touched Python files; 27/27 view-router tests; live dashboard auto-reloaded via asset-hash; cache-bust hash flipped to `b5f4bf09c6`.

## Visual audit
Mid-session ran a `general-purpose` Agent for independent UI review. Surfaced 3 must-fix + 4 should-consider + 5 leave-alone findings. Operator picked 6 of 7 to apply (skipped #1 as false positive after re-verification). All 6 applied + verified live.

## Tests / verification
- `tests/test_view_router_state.py`: 27 pass + 16 subtests.
- `tests/test_routes_ds_preview_scorer.py` + `tests/test_state_builder_archetype_pick.py` + `tests/snapshot_panels/`: 59 pass + 16 subtests in 18.65s combined.
- Manual: Recent 5 click → History deep-link pulse-highlight verified by operator. Find Match picker modal → operator clicked queue → routed to Pre-Game Lobby successfully.

## What's next
- **Operator signaled next session = next view.** Page order likely: Pre-Game Lobby → Champ Select → Active Match → Last Match → Session → History → Replay → User Builds → Settings.
- **Tagged-for-removal placeholders** stay until backend work catches up: `data-dummy-data="tonights-pick-tips"` (needs post-match Good/Bad/Ugly analyzer), `data-dummy-data="items-pending-ingest"` (needs `items[]` column in match_history.db ingest), `builders.py` `items: []` + `mode_subtype: null` placeholders (same).

## Blockers / don't redo
- **Heartbeat ♥ — in header top-right** flagged by operator: WS heartbeat envelope (`{type:"heartbeat", t:epoch}`) doesn't re-arm immediately after RC restart. The dashboard at `web/js/main.js:5026` populates `#heartbeat` only on WS envelope arrival; supervisor's broadcast loop needs investigation. Don't re-investigate the WS connection itself — `ws://192.168.8.230:8891/push` is confirmed connected (footer shows it).
- **`restart_trigger.txt` watcher wedge** confirmed pre-existing — the supervisor's poll loop at `ops/rc_supervisor.py:1240` didn't consume trigger files on 2 attempts this session. Workaround: hard `taskkill /F /PID + restart.bat` documented as standard. Don't re-debug; existing memory entry `project_rc_supervisor_restart.md` already covers.
- **Hero headline up/down classifier removed**: do not re-add until a proper yesterday-comparison baseline is wired into `/api/home/summary`. Operator explicitly prefers flat over wrong-direction-tinted.

---

# s217 wrap — 2026-05-15 (DS Phase 5.9.22 sum-of-blocks data batch — Taliyah E + DrMundo W)

**Operator instruction:** "continue ds" — keep DS engine moving from where s215 left off.

## Shipped — single commit (this session)

Second pure-data sum-of-blocks batch following s215's s207-schema-lift consumption. Closes the s215 carry-forward queue under the operator-commits-to-canonical-burst model. 2 entries (1 NEW key + 1 LIFT of existing single-int):

- **Taliyah.E = [0, 2]** — NEW key. Block 0 "Magic Damage" (60-240 base + 60% AP — initial shard-impact pass-through when each launched shard hits an enemy) + Block 2 "Total Maximum Detonation Damage" (62.5-262.5 base + 75% AP — aggregate of multiple stone detonations when target steps through the resulting Unraveled Earth terrain). Operator commits to landing the spell on target + target moving through resulting terrain. Closes s215's "Taliyah E likely no-op since block 2 already aggregates" framing — that missed that block 0 IS an additional damage source separate from the detonation aggregate (the initial pass-through is a distinct hit from the detonation step-through).
- **DrMundo.W = [1, 2]** — LIFT from s193's single-int `{W: 1}`. Block 1 "Total Magic Damage" (80-320 base — full 4-second Heart Zapper drain channel) + Block 2 "Magic Damage" (20-80 base — recast detonation burst when operator manually re-fires W at end of channel). Same in-batch lift pattern as s215's Thresh.E lift `{E: 2}` → `{E: [1, 2]}`. Operator commits to letting Heart Zapper run + manual recast for full Mundo W single-target burst.

ENGINE_VERSION 0.93.0 → 0.94.0. Registry stays at 124 champions (Taliyah gains E key alongside existing Q=2; DrMundo lifted from int to list, same key count). Total (champion, key) entries: 192 → 193 (Taliyah +1; DrMundo unchanged).

**Live A/B headlines on :8893 (/ability-dps at lvl 11 vs 80 armor / 30 MR / 2000 HP HTTP probe):**
- Taliyah E per-spell raw 60.00 → 122.50 (**+104%**, 60+62.5 sum confirmed) — small total lift (+5.95%) because Taliyah Q's Threaded Volley already dominates her ability_dps total.
- DrMundo W per-spell raw 200.00 → 250.00 (**+25%**, 200+50 sum confirmed) — modest total lift (+4.1%) because Mundo's other spells (Q/E) contribute meaningfully too.

Arithmetic parity exact: `s217 sum = forced_block_A + forced_block_B` to 4 decimal places in tests. Per-rank math verified against Meraki 16.10.1 snapshot — Taliyah rank 5: 240+262.5=502.5 raw base; DrMundo rank 5: 320+80=400 raw base.

**Investigation outcomes:** During scan, confirmed the other s215 carry-forwards stay deferred per their original rationale: Jinx R (block 0 "Maximum Physical Damage" 300-600 + 155% bAD IS the canonical primary-target maximum at max-distance + missing-HP scaling; blocks 2-3 are secondary AOE on enemies behind primary — engine default block 0 already correct for single-target focus, no registry entry needed); Kindred E / Kayle E / Belveth R remain in the nested missing-HP parser bucket (Phase 4a parser limitation around `target_missing_hp_pct` nested under `unparsed_modifiers`).

## Tests
- **19 new tests** in `agents/daemon_slayer/tests/test_sum_of_blocks_expansion_s217.py` (Phase599_22RegistrySeedTests 3 / Phase599_22AbilityDpsTests 6 / Phase599_22BackwardCompatTests 9 / Phase599_22EngineVersionTests 1) mirroring s215's pattern.
- **2 ENGINE_VERSION pin bumps** in `test_effects_expansion.py` (0.93.0 → 0.94.0; one in `Phase599_20EngineVersionTests` per its 8-line s217 comment block, one in `test_batch64_version`).
- **1 ENGINE_VERSION pin update** in `test_sum_of_blocks_expansion_s215.py` (pin tracks current engine version per established convention).
- **3 existing assertions updated** in `test_block_index_overrides.py`: shape-pin in `test_assert_known_overrides` for DrMundo (`{W:1}` → `{W:[1,2]}`) + Taliyah (`{Q:2}` → `{Q:2,E:[0,2]}`); `test_drmundo_W_routes_to_block_1` renamed to `test_drmundo_W_routes_to_sum_of_blocks` with inline list-shape assertion replacing the `_delta_check` int-only helper (same pattern s215 used for Thresh.E lift); `test_pre_s202_taliyah_unchanged` backward-compat pinned to post-s217 shape.

DS suite 2041 → 2060 (+19). Wider RC `tests/` 953 green post-DS-restart (phase8_smoke probes live :8893 engine_version which was 0.93.0 pre-restart — fails until DS bounced; passes after restart). Full project test discovery (`py -m unittest discover -s . -p "test_*.py"`): 3013 tests green.

## DS server restart
- Killed pid 9696 (running 0.93.0).
- Cleaned stale 8893 listener (briefly bound by orphaned launcher).
- Restarted via `Start-Process pythonw tools\start_daemon_slayer.py`; new listener pid 19128.
- `/health` confirms `engine_version: "0.94.0", patch: 16.10.1, champions: 172, items: 705`.
- Note: HTTPS handshake returned SSL `WRONG_VERSION_NUMBER` on first attempt — DS server is serving HTTP not HTTPS at 127.0.0.1:8893. Live A/B used `http://127.0.0.1:8893` (matches the existing wider-test wire format). Not s217-introduced; pre-existing condition.

## What's next
- **Live ARAM Mayhem test** still scheduled by operator post-/clear (carried s214 → s215 → s216 → s217). Now also validates Phase 5.9.22 Taliyah/DrMundo ability_dps lifts ride through to `/api/ds-preview` for the build chooser's experimental row + Taliyah's Worked Ground commit + DrMundo Heart Zapper recast detonation.
- **DS Phase 5.9.23+ scoping** — sum-of-blocks bucket queue exhausted under current operator-commit framing. Next batch needs a different angle. Candidates for future work: (a) **Conditional target-state schema lift** — 6+ candidates queued since s195: Lux Illumination mark amp, DrMundo E missing-HP threshold, Renekton Q at full Fury (already routed via s197 single-int but conditional model would express the canonical Fury bar build-up), Zed shadow Q empowered, Aphelios weapon-form conditionals. Schema lift: `block_index: int | list[int] | dict[str, int]` where dict expresses conditional state → block_index mapping. (b) **Nested missing-HP parser bucket** — Kindred E / Kayle E / Belveth R execute curve still gated on Phase 4a parser learning nested `unparsed_modifiers` syntax. Upstream extractor work; not pure-data. (c) **Per-form block_index** — Heimerdinger.W form 1 (Upgrade!!!) has 20 rockets vs form 0's 5; current registry [0,1,1,1,1] under-counts upgrade form. Schema lift: registry value is per-form dict. (d) **Aphelios Q forms** — Meraki bulk parses all 6 Q weapon-form variants as `no_damage`; upstream data-quality fix required before any registry entry.
- **Loadout autogen calibration** unchanged from s215 (operator may flip `default_per_mode` pointers post-Mayhem).
- **Deadcode cleanup (carried, low priority)**: `coaches/brawl_coach.py` + brawl mode detection across 6 files.

## Blockers / don't redo
- DS server :8893 is HTTP, not HTTPS — don't waste cycles diagnosing SSL handshake errors. `curl -k -s https://...` returns RST/wrong-version; use `http://127.0.0.1:8893/...` instead. Pre-existing condition matches the wider-test wire format.
- `_delta_check(champion, key, expected_idx)` helper in `test_block_index_overrides.py` only handles int expected_idx — for sum-of-blocks (list-valued) entries, use the inline pattern from `test_drmundo_W_routes_to_sum_of_blocks` (assert `block_index_resolved.get(key) == [a, b]` + delta-check against forced single block). s215 established this pattern for Thresh.E; s217 extended to DrMundo.W.
- `_meta.rationale` in `champion_block_index.json` was NOT updated by s215 — last entries reference s205. s217 also only updated `_meta.description` (kept rationale append as future cleanup, since it's a 78KB file and rationale duplicates much of description's per-entry math). Not a regression — both fields are documentation.

---

# s216 wrap — 2026-05-15 (Game-PC: League settings restore from SamplePlayer backup + ReadOnly lock)

**Operator instruction:** "find my last saved persisted league setting file we did with rc where the league game was borderless windowed (we kept it in case of changing riot accounts) and overwrite the games current persisted file - then make it readme [readonly] after confirming the new file change over". Pointed to `C:\rc-agent\lol_settings_SamplePlayer.py` on Game-PC.

## Ops-only session — zero RC code changes, zero commits

- Backup file: `C:\rc-agent\lol_settings_SamplePlayer.py` (26820B, captured 2026-04-26 for SamplePlayer#Trist). Self-contained Python restore script — writes 4 files (`game.cfg`, `input.ini`, `PersistedSettings.json`, `LCUAccountPreferences.yaml`) and has `--backup` flag that auto-snapshots current files into a timestamped subfolder before overwriting.
- Pre-check: no LeagueClient/RiotClient processes running on Game-PC (script requires League closed).
- Ran `py "C:\rc-agent\lol_settings_SamplePlayer.py" --backup` via `mcp__gamepc__run_powershell`. All 4 files written, pre-restore state preserved at `C:\Riot Games\League of Legends\Config\_backup_SamplePlayer_20260515_085530\`.
- Verified `WindowMode=2` (borderless) and `Height=1080`/`Width=1920` in restored `game.cfg`.
- Set ReadOnly attribute on all 4 restored files via `Set-ItemProperty -Name IsReadOnly -Value $true`. Confirmed `Attributes` shows `ReadOnly, Archive` for each.
- Live `PersistedSettings.json` shrank 54734B → 11974B post-restore — expected; script's PERSISTED_SETTINGS_JSON only carries the curated subset captured 4/26, and Riot regenerates server-side data on next login (per the script's own comment).

## What's next

- Operator's previously-planned **live ARAM Mayhem test** (carried from s214/s215) now has stable settings — borderless windowed locked, won't drift across account swaps.
- All s215 DS Phase 5.9.22+ carry-forwards remain unchanged (Taliyah E, Jinx R secondary AOE, Kindred E/Kayle E/Belveth R nested missing-HP parser bucket).
- Loadout autogen calibration follow-up unchanged (operator may flip `default_per_mode` pointers post-Mayhem).

## Blockers / don't redo

- ReadOnly attribute means League cannot overwrite these on client-exit (intended) — BUT any in-game settings changes also won't persist until the attribute is cleared. Operator knows; flagged in chat. Clear via `Set-ItemProperty -Name IsReadOnly -Value $false` per-file if they want to retune live.
- Don't re-search for the backup — confirmed location is `C:\rc-agent\lol_settings_SamplePlayer.py` (also mirrored at `C:\RC-Agent\` — Windows case-insensitive duplicate listing).
- Pre-restore backup at `C:\Riot Games\League of Legends\Config\_backup_SamplePlayer_20260515_085530\` is the rollback artifact if needed.
