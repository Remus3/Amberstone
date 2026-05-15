# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

---

# s215 wrap — 2026-05-15 (Loadout auto-generator + DS Phase 5.9.21 sum-of-blocks data batch)

**Operator instruction:** "continue loadout then continue ds" — close the s214 carry-forward 3-curated-variant auto-generator, then keep DS engine moving.

## Shipped — commits `b395032` + `77d716c`

Pushed `e89a94c..77d716c main -> main` (4 commits, 2 features). CI status pre-flight: `py_compile` clean (2350 .py), `ruff` clean, 508 phase2+regression+phase8+fu02 pass, 11 snapshot panels pass.

### s215 part A — Loadout auto-generator (commit `b395032`)
New `tools/champion_loadout_autogen.py` (~400 LOC). Emits 3 algorithmic build variants per (champion, mode) into `data/champion_loadouts.json` via `rank_for_primary_archetype` per archetype. Hand-curated wins: each (champion, mode) counts curated variants with that mode in `modes[]`; only fills to 3 with auto entries when count < 3. Stable keys `auto-<mode>-<slot>-<archetype>` so reruns refresh in place. Runes mirror `_CSV_EXPERIMENTAL_RUNES` from `champ_select.js`; summoners archetype-keyed for SR + mode-default for ARAM (4,32) / Arena (4,7). 35 new tests via DS-stub mocks; 1064 wider RC tests pass (+40 vs s214). Full 172-champ run: 13.7s, 1017 auto entries added (332 SR + 169 ARAM + 516 Arena), 0 unfilled. Vayne/Lulu/Veigar curated entries spot-verified preserved.

### s215 part B — DS Phase 5.9.21 sum-of-blocks data batch (commit `77d716c`)
First pure-data batch consuming s207's schema lift. 4 new (champion, key) entries to `champion_block_index.json`: Thresh.E=[1,2] (Maximum Bonus Magic at full Souls + canonical Magic Damage — lifts s203's single-int {E:2}), Sona.Q=[0,1] (active + Power Chord), Kalista.E=[0,1,1,1,1] (base Rend + 4× stacks = 5-stack model), Malzahar.R=[0,2] (Total Magic channel + Total target-max-HP% bonus). ENGINE_VERSION 0.92.0 → 0.93.0. DS server restarted live to pid pinned at /health=0.93.0. **Live A/B headlines:** Kalista E **+147%** raw, Malzahar R **+150%** raw, Thresh E **+94%** raw, Sona Q **+16%** raw (Power Chord block has unparsed AP scaling Phase 4a can't extract). 19 new tests in `agents/daemon_slayer/tests/test_sum_of_blocks_expansion_s215.py` + 4 prior-batch tests updated for new Thresh shape. DS suite 2022 → 2041; wider RC 1064 green.

### What's next
- **Live ARAM Mayhem test** still scheduled by operator post-/clear (carried from s214). Now also has 3-variant build chooser to validate live on every locked champion + Phase 5.9.21 Thresh/Sona/Kalista/Malzahar ability_dps lifts ride through to `/api/ds-preview` for the build chooser's experimental row.
- **DS Phase 5.9.22+ sum-of-blocks candidates remaining**: Taliyah E (mechanic uncertain — block 2 'Total Maximum Detonation' already aggregates), Jinx R secondary AOE (not single-target), Kindred E (nested missing-HP parser bucket — Phase 4a parser limitation), Kayle E (same bucket), Belveth R execute curve (same bucket). Bucket queue moves from 6 → 2 with s215 closing Thresh/Sona/Kalista/Malzahar.
- **Loadout autogen calibration**: operator may want to flip some `default_per_mode` pointers post-Mayhem if a curated default loses to the auto-primary on live ARAM rounds. No code work — pure JSON edit. Autogen preserves operator's manual default choices on re-run.
- **Deadcode cleanup (carried)**: `coaches/brawl_coach.py` + brawl mode detection across 6 files.

### Blockers / don't redo
- Loadout autogen runs DS engine ~1500 times per full pass (~14s). If DS server is down during a run, all auto entries for unfilled slots stay missing — script reports them in the `unfilled` stat. Operator can re-run after starting DS. Not a bug, by design.
- Phase 4a Meraki parser limitation on Sona Q block 1's "X% of Sona's AP" (unparsed_modifiers) is upstream — the sum-of-blocks entry correctly captures the flat base (10-30) but the AP scaling is invisible to the engine until the Phase 4a parser learns to read nested `% of <champion>'s AP` syntax. Out of scope for this batch.
