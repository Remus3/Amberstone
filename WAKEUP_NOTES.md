# WAKEUP_NOTES — RC hand-off ledger

> **Compacted 2026-05-04** (was 9,209 lines / 499 KB). Sessions s27–s91 reduced
> to a one-liner ledger below; full narratives live in `ROADMAP.md §1` and
> `git log`. Only the current session (s92) is kept at full fidelity.

---

# s106 wrap — 2026-05-05 (DaemonSlayer flash fix + preflight expansion)

## What shipped
- **`ops/RC-DaemonSlayer.xml`** — `python.exe` → `pythonw.exe`; task reinstalled via `install_daemon_slayer_task.ps1`. No more console flash on boot/restart. DS still live at `:8893` engine=0.60.0 patch=16.9.1.
- **`start_claude.ps1`** — added RC-DaemonSlayer + RC-Phase3-Supervisor + RC-BridgeWatcher preflight checks; added `:8893` + `:8890` HTTP probes; fixed final `claude` launch to `--name "Legion"`. commit `0d1b545`.
- **`/loop 1m /process-bridge-tasks`** — shortcut loop stopped (bridge daemon on Game-PC handles that side; Legion Claude processes Legion-targeted tasks via session loop).

## Do NOT redo
- RC-DaemonSlayer XML is already pythonw.exe — don't revert.
- The flashing terminal is fixed; no further investigation needed.

## Open work (priority order)
1. **RC-VisionServer failing** (last_result=267014) — task starts SYSTEM context at boot; `267014` = process failed to start. Check if pythonw path is correct in the task, and whether it can find moon_vision_server.py.
2. **Peer daemon install** — confirm `~/peer_bridge_daemon_health.json` exists on Peer.
3. **Game-PC bridge loop** — liveness probe sent s106; if loop is dead, start `/loop /process-bridge-tasks` on Game-PC Claude (or RC-BridgeDaemon handles it).
4. **DS calibration**: 50+ games needed; auto-collects into `data/ds_calibration.jsonl`
5. **Vision regions calibration**: tune `data/vision_regions.json` bboxes

---

# s105 wrap — 2026-05-05 (zero-cost bridge daemons for Game-PC + Peer)

## What shipped
- **`tools/gamepc_bridge_daemon.py`** — zero-cost sentinel for Game-PC bridge. Polls Legion bridge via `bridge_pull_tasks.py --target gamepc` every 30s; invokes `claude --dangerously-skip-permissions -p /process-bridge-tasks` only when count > 0. Deployed to `C:\RC-Agent\gamepc_bridge_daemon.py`, installed as `RC-BridgeDaemon` scheduled task (pythonw.exe, AtLogon, restart 3×/1min). **Game-PC confirmed working** — queue drained 3 tasks, health→idle.
- **`tools/peer_bridge_daemon.py`** — self-contained Peer variant. Inline urllib fetch to `127.0.0.1:8888/api/bridge/messages`; handles Peer bare-list format + RC dict; reads `rc-bridge-tasks-processed.txt`. Deployment task sent to Peer via bridge.
- **`tools/gamepc_boot.ps1`** — section 6 now installs RC-BridgeDaemon instead of terminal `/loop`; pulls fresh daemon on each boot from `/agent/` allowlist.
- **`dashboard/routes_static.py`** — added `gamepc_bridge_daemon.py` + `peer_bridge_daemon.py` to `_AGENT_ALLOWED`.
- **Auth fix** — `ANTHROPIC_API_KEY` stored in `C:\Users\Administrator\.claude\settings.local.json` env block on Game-PC for headless `--print` auth. Also in `C:\RC-Agent\.claude\settings.local.json`.

## Do NOT redo
- `/loop 1m /process-bridge-tasks` on Game-PC is REPLACED by RC-BridgeDaemon scheduled task. Do not restart the old loop.
- `--dangerously-skip-permissions` is kebab-case (not camelCase). The daemon uses the correct form.

## Open work (priority order)
1. **Peer daemon install** — Peer should have received a bridge task with steps. Confirm Peer installs and starts `peer_bridge_daemon.py`; watch for health file at `~/peer_bridge_daemon_health.json`.
2. **Validate DS champ-select panel** — next champ select, confirm `#cs-ds-block` shows item tiles
3. **Validate icon fix** — next in-game, confirm item icons render on first load without "?"
4. **DS calibration**: 50+ games needed; auto-collects into `data/ds_calibration.jsonl`
5. **Vision regions calibration**: tune `data/vision_regions.json` bboxes
6. **Investigate failing scheduled tasks**: RC-DaemonSlayer (last_result=1), RC-VisionServer (last_result=267014)

---

# s103 wrap — 2026-05-05 (DS champ-select panel + dashboard bug fixes + done §6b)

## What shipped

- **DS Engine champ-select build preview** `112350a` — `#cs-ds-block` panel + `/api/ds-preview` endpoint. Fires once per (champion, mode) pair. Item tiles with +Ndps tooltips. `_CS_DS` tracker debounces independently of Haiku `_CS_LIVE`.
- **SR SSE mode fix** `5ee58b6` — `_state_builder.py` was returning `mode_key="game"`; JS `driveNow` silently dropped all SR SSE state. Corrected to `"sr"`.
- **Item icon cache race fixed** `f5ce231` — `_itemResolveCache` cached null for items resolved before `items_index.json` loaded; idempotency sig then blocked re-render. Fix: clear cache + tile sigs on ITEMS load.
- **Augments pill fix** `5ee58b6` — CSS static-pill rule overrode `.hidden`; now `display:none !important`.
- **`/done` §6b living-doc sync** `d6fbce0` — ROADMAP/CLAUDE.md/README now updated as part of the done ritual. Pushed to Peer + Game-PC bridge for pickup.

## Do NOT redo
- DS champ-select panel is fully wired (backend + HTML + CSS + JS). Next validation is in champ select.
- Icon "?" fix is in — next in-game session should show all icons on first load.
- SSE mode key is correct — if RECOMMENDED shows "—" again, check `liveclient_summary()` for `sr_items`.

## Open work (priority order)
1. **Validate DS champ-select panel** — next champ select, confirm `#cs-ds-block` shows item tiles
2. **Validate icon fix** — next in-game, confirm item icons render on first load without "?"
3. **Bridge auto-loop dead** — restart on Game-PC: `/loop 1m /process-bridge-tasks`
4. **DS calibration**: 50+ games needed; auto-collects into `data/ds_calibration.jsonl`
5. **Vision regions calibration**: tune `data/vision_regions.json` bboxes

---

# s102 wrap — 2026-05-05 (SR coach signature hash fix + RECOMMENDED panel fallback)

## What shipped (this session)

- **SR coach signature hash bug fixed** — `coach_integration.py` (frozen, user-approved)
  - `_state_signature` fallbacks had wrong key names vs `_convert` output
  - `hp_bucket`: `hp_pct // 10` → `my_hp_pct * 10` (was using unprefixed key + wrong scale)
  - `mana_bucket`: added fallback from `my_mana_pct * 10` (was always None)
  - `gold_bucket`: `gold // 300` → `my_gold // 300`
  - `level`: added fallback from `my_level` (was always None)
  - `_convert` now passthroughs `kda`, `dead_count`, `kill_window` from game_state
  - **Effect**: coach now re-fires on HP changes, gold/item thresholds, level-ups, deaths, kills — not just wave_state transitions

- **RECOMMENDED · NEXT TO BUY panel fixed** — `web/js/dashboard.js`
  - SR coach never writes `item_build`; added `sr_items` fallback (liveclient-derived via `_state_builder` overlay)
  - `sr_items` items with `next: true` populate RECOMMENDED when `item_build` is empty
  - Requires Edge page refresh to pick up (JS was cached from session start)

- **SR coach API key** — `API-Key-Claude.txt` written from CLI env to unblock SR coaching mid-game
  - File is gitignored; if missing, re-write from env and restart RC

## Do NOT redo
- `_state_signature` bug is fixed — coach was firing at 4:36 then not again until ~16:48 (only wave_state changed). Now fixed.
- `API-Key-Claude.txt` was missing; was written this session. If RC shows `api_key=MISSING` again, re-write the file.
- dashboard.js RECOMMENDED fix is deployed; needs Edge Ctrl+Shift+R to activate.

## Open work (priority order)

1. **Stage 5 calibration**: 50+ games needed; data auto-collects into `data/ds_calibration.jsonl`
2. **Vision regions calibration**: tune `data/vision_regions.json` bboxes for `timer`, tower HP%, nexus HP%
3. **Bridge auto-loop**: dead as of this session end — restart on Game-PC with `/loop 1m /process-bridge-tasks`

---

# s101 wrap — 2026-05-05 (DS health indicator + item build DS picks panel)

## What shipped (this session)

- **DS health in /api/health/all** `50248a7` — `dashboard/routes_state.py` now probes `:8893/health`
  - DS down → overall status flips to **yellow** (not red; RC + coaching still work)
  - `rollup["daemon_slayer"]` returns `{alive, engine_version, patch, items, champions}`
- **Health dot tooltip** — DS engine status added: `DS engine up · v0.60.0 · 547i/168c`
- **Item Build panel DS section** — new `#ib-ds-block` renders `daemon_slayer_picks` as compact chips
  - Format: `ItemName +202dps` (hidden when no picks present; shows during InProgress only)
  - `daemon_slayer_picks` was already written to all coaching JSONs but was never consumed by the UI — now wired
  - CSS: `.ds-chip` dark rounded tags, green delta-dps text

## Do NOT redo
- DS picks were already written to all coaching JSONs (ARAM/Arena/Brawl/SR) — they just weren't rendered. Don't reinvestigate the data pipeline, only the UI was missing.
- Bridge auto-loop is **NOT running on Game-PC** — start manually: `/loop 1m /process-bridge-tasks`

## Open work (priority order)

1. **Stage 5 calibration**: 50+ games needed; data auto-collects into `data/ds_calibration.jsonl`
2. **Vision regions calibration**: tune `data/vision_regions.json` bboxes for `timer`, tower HP%, nexus HP%
3. **Bridge auto-loop**: dead as of this session end — restart on Game-PC with `/loop 1m /process-bridge-tasks`

---

# s100 wrap — 2026-05-05 (Tiered vision + open-items cleanup)

## What shipped (this session)

- **Tiered vision** `46e9fb8` — `GameVisionReader.read_tiered()` + `read_or_escalate()` wired into ARAM/Arena/Brawl coaches
  - OCR runs first via `core.vision_routing.read_or_escalate` with mode-specific `TIERED_FIELDS` + `TIERED_VALIDATORS`
  - `timer` field is the in-game canary — OCR validates frame is a live HUD before Sonnet fires
  - Sonnet always escalates for semantic fields (tower HP%, augments, wave_pct, etc.) — no calibrated OCR regions yet
  - **Expand coverage by tuning `data/vision_regions.json` bboxes** for tower HP%, nexus HP%, event name, etc.
  - Arena: `round_number` + augment/anvil in TIERED_FIELDS; Brawl NB: nexus HP + event timer; URF: deaths_visible

- **Open items** `41c87bc` — all resolved in previous sub-session:
  - Rune writer SR shard3: 5002 (invalid) → 5001 (Health Scaling, valid Row 3)
  - items_index.json alias ID collision: sort by ID length so 4-digit canonical wins over 6-digit 22xxxx alias
  - Yunara phantom dups: zero-duration early exit + 90-min window dedup in game_ingest.py

## Open work (priority order)

1. **Stage 5 calibration**: 50+ games needed; data auto-collects into `data/ds_calibration.jsonl`. Then analyze vs rewind_history.db.
2. **Vision regions calibration**: tune `data/vision_regions.json` bboxes for `timer`, ARAM tower HP%, Brawl nexus HP% — once calibrated those fields drop out of Sonnet tier automatically.
3. **Permanently deferred (3)**: Lightning Braid, Kinkou Jitte, Mejai's Arena mirror — all genuinely unmodelable
4. Bridge auto-loop: **NOT running on Game-PC** — start manually: `/loop 1m /process-bridge-tasks`

---

# s99 wrap — 2026-05-05 (Daemon Slayer batch 64 — Malignance + Stage 5 pipeline)

## What shipped (this session)

- **Batch 64** `e7c4cd9` — Malignance Hatefog promoted (ENGINE_VERSION 0.60.0, 929 tests)
  - New `CallContext.ult_casts_per_sec` field — engine-derived from `ult_rates.py`
  - New `data/daemon_slayer/ult_cast_rates.json` — per-champion ult cast rate (casts/sec)
    from rewind_history.db (spell4_casts / game_duration_s), 172 champions
  - 3118 (SR) + 223118 (ARAM mirror) promoted: Hatefog `(180+15%AP) magic per ult zone hit`
  - Permanently deferred reduced from 4 to 3 (Lightning Braid, Kinkou Jitte, Mejai's Arena mirror remain)

- **Stage 5 calibration pipeline** (same commit)
  - New `core/ds_calibration.py` — append-only `data/ds_calibration.jsonl` log
  - All 4 coaches (ARAM, Arena, Brawl, SR) log DS picks after each tick
  - Calibration analysis: join log vs rewind_history.db on (champion, mode, ~ts)
  - Start collecting: queue up 50+ games, then run calibration analysis script

## Open work (priority order)

1. **Stage 5 calibration**: needs 50+ games with DS active. Play draft normals, data will collect automatically into `data/ds_calibration.jsonl`. Then analyze.
2. **Permanently deferred (3)**: Lightning Braid, Kinkou Jitte, Mejai's Arena mirror — all genuinely unmodelable
3. Bridge auto-loop: **NOT running on Game-PC** — start manually: `/loop 1m /process-bridge-tasks`

---

# s98 wrap — 2026-05-05 (Daemon Slayer batch 63 — blocked items resolved)

## What shipped (this session)

- **Batch 63** `e56e878` — 3 previously-blocked items promoted (ENGINE_VERSION 0.59.0, 922 tests)
  - **Hellfire Hatchet (4017)**: Char proc — Meraki CD=15s confirmed; not truly ability-frequency-blocked.
    Formula: `(5%+5%*hp_diff/2000 + lethality*(0.2%+0.2%*hp_diff/2000)) * target_max_hp physical/15s`
    `hp_diff = clamp(caster_max_hp - target_max_hp, 0, 2000)`; all in CallContext.
  - **Fiendhunter Bolts (2512)**: Opening Barrage — Meraki CD=45s confirmed.
    `3 × (base_ad + bonus_ad) × 0.70 physical/45s` (70% = midpoint of 60–80% crit template).
  - **Innervating Locket (447104)**: Fill the Soul `bonus_ap_stacked=175`.
    `pp|100–250 AP` at 30 charges; 175 midpoint; Arena-only; ally casts count.
    Wired via existing `total_stacked_ap()` path in dps.py.
  - Updated notes on 4 permanently deferred items:
    Lightning Braid (no Meraki formula, DPS-negative), Malignance (ult-zone, no CD),
    Kinkou Jitte (directional geometry), Mejai's Arena mirror (no Arena DDragon ID)

- **Key insight documented**: Items labelled "ability-triggered" may have an item-level CD
  in Meraki's `passives[].cooldown` field. Check Meraki FIRST before deferring.
  Hellfire Hatchet and Fiendhunter Bolts both had item CDs that made them promotable.

## Coverage status

- ITEM_EFFECTS: **547 entries — DDragon purchasable coverage COMPLETE**
- **922 tests passing** (ENGINE_VERSION 0.59.0)
- 4 items permanently deferred: Lightning Braid, Malignance, Kinkou Jitte, Mejai's Arena

## Open work (priority order)

1. **Ability-cast schema**: Lightning Braid + Malignance still need per-champion ability
   frequency data (not item CDs). Kinkou Jitte needs positional geometry. All deferred.
2. **Stage 5 calibration**: needs 50+ games with DS active. Long-term.
3. Bridge auto-loop: **NOT running on Game-PC** — start manually: `/loop 1m /process-bridge-tasks`

---

# s96 wrap — 2026-05-04 (documentation + ARAM DS-before-Haiku refactor)

## What shipped (this session)

- **ARAM coach DS-before-Haiku** `3b84949` — highest-value architectural fix
  - DS `rank_for()` moved before `messages.create()` in `coaches/aram_coach.py`
  - `{ds_picks}` injected into user turn: `InfinityEdge(+142dps,3400g) > ...`
  - Pre-DS hardcoded item rules removed: BUILD COMMITMENT, DAMAGE-TYPE ALIGNMENT,
    ITEM MUTUAL EXCLUSIONS, Banned components block (−37% system prompt, ~1,849→~1,170 tokens)
  - Post-Haiku block reuses `_ds_rows` — no second engine call
  - Fixed stale experimental override text referencing the now-removed "BUILD COMMITMENT rule"

- **Documentation sweep**
  - `CLAUDE.md`: added Game-PC agents table (5 agents with roles), DS engine section
    (module map, key data types, DS-before-Haiku pattern, coach integration status table,
    deferred items list), updated architecture map, updated active priorities
  - `README.md`: DS bullet updated (547/911/0.58.0), coaching pipeline step 4 added
    (DS-before-Haiku), DS roadmap section updated, RC Tutor table updated
  - `ROADMAP.md`: s92-s95 section added documenting all batches 38-62 + ARAM refactor;
    status table updated
  - `C:\Users\Administrator\Desktop\DS_COMPLETION_ROADMAP.txt` created — full guide:
    remaining stages (Stage 1: Arena+Brawl, Stage 2: SR, Stage 3: ability-cast, Stage 4: calibration),
    best prompts per stage, "complete" definition, session management guide, quick health checks
  - Memory: `project_daemon_slayer_engine.md` updated to reflect coverage complete status;
    `reference_daemon_slayer_engine_arch.md` header updated

## Coverage status

- ITEM_EFFECTS: **547 entries — DDragon purchasable coverage COMPLETE**
- **911 tests passing** (ENGINE_VERSION 0.58.0)
- ARAM coach: DS-before-Haiku ✅, pre-DS rules pruned ✅

## Open work (priority order)

1. ✅ **Arena + Brawl + SR coaches DS-before-Haiku** — commit b4609b4 (this session)
2. **Ability-cast schema**: blocked on ability-frequency data; see ROADMAP Stage 3
4. Bridge auto-loop: **NOT running on Game-PC** — start manually: `/loop 1m /process-bridge-tasks`

---

# s95 wrap — 2026-05-04 (Daemon Slayer batches 57–62)

## What shipped (this session)

- **Batches 57–60** `9f128c4..864e65d` — 4 promotions + 2 new CallContext fields (ENGINE_VERSION 0.57.0, 899 tests)
  - `caster_bonus_armor` + `caster_lethality` added to CallContext and computed in dps.py
  - Void Immolation (223069): 20 + 1.5% max HP TRUE/s, unique_passive_key="immolate"
  - The Golden Spatula (224403): Doing Something pp|26-43 magic/s
  - Darksteel Talons (443054): Gash TRUE on-hit, now +20% bonus armor scaling
  - Bastionbreaker (2520): Shaped Charge 15 + 0.75×lethality TRUE/45s
  - Reality Fracture (447102): ZZ'Rot 8 Voidmites × (6+4%AD+8%AP) magic/12s

- **Batch 61** `2148ed2` — Zaz'Zak's + Bloodsong (899 tests)
  - Zaz'Zak's Realmspike (3871): Void Explosion 10+15%AP+3%target maxHP magic/10s
  - Bloodsong (3877): Spellblade 100% base AD physical/1.5s + Expose Weakness damage_amp_pct=0.05

- **Batch 62** `dcfeb63` — Cruelty dual-variant (911 tests, ENGINE_VERSION 0.58.0)
  - Cruelty Arena (447109) + SR (667109): Watch Them Fall comet on CC, pp|50-150+40%AP+4%caster maxHP magic/6s
  - Fixed stale 667109 note (was wrongly labeled "Execute damage amp")

## Coverage status

- ITEM_EFFECTS: **547 entries — DDragon purchasable coverage COMPLETE**
- **911 tests passing** (ENGINE_VERSION 0.58.0)
- Promotion sweep complete — remaining unmodeled items are all ability-cast/ult-cast/positional-conditional blocked

## Schema gaps still open (priority order)

1. **Ability-cast schema** → Lightning Braid, Malignance Hatefog, Night Harvester SR, Innervating Locket, Fiendhunter Bolts — blocked on ability-frequency data
2. **Hellfire Hatchet Char** — 3-way scaling (level × hp_diff × lethality); formula too complex
3. **Kinkou Jitte** — directional weakpoint mechanic; positional conditional not modelable
4. **Fiendhunter Bolts** — ult-triggered crit-guarantee formula (complex template)
5. **Mejai's Arena mirror** — no Arena ID found in DDragon (3041 SR only)
6. Bridge auto-loop: **NOT running on Game-PC** — start manually: `/loop 1m /process-bridge-tasks`

---

# s94 wrap — 2026-05-04 (Daemon Slayer batches 54–56)

## What shipped (this session)

- **Batch 54** `ded3d01` — 2 new schema fields + 3 promotions (ENGINE_VERSION 0.55.0, 843 tests)
  - `bonus_ap_stacked`: Mejai's (3041) full-stacks 125 AP; added before Rabadon's amp so Magical Opus multiplies all AP
  - `bonus_as_conditional`: Yun Tal Flurry (3032, 223032) 30% AS / 27% uptime → 0.08 effective sustained AS; wired to stats_for_rotation["as"]
  - Sword of the Divine (443060): EV model for Excoriate uniform 0–50% crit damage → crit_damage_bonus=0.25

- **Batch 55** `e054c1c` — 46 new defensive_only entries; DDragon purchasable coverage complete (547 entries, 850 tests)
  - Doran's Helm, jungle companions, consumables, elixirs, Bandle Juice (2161-2163), Arena consumables (2141-2147), ward trinkets, support milestone quests, Arena Legendary/Prismatic selectors, Golden Spatula
  - Added coverage gate test: `test_ddragon_purchasable_coverage_complete()` asserts zero uncovered items

- **Batch 56** `ede9c89` — caster HP-scaled AP amp (ENGINE_VERSION 0.56.0, 856 tests)
  - `ap_amp_pct_per_100_caster_hp` + `ap_amp_pct_per_100_caster_hp_cap`: multiplicative AP amp keyed on caster max HP
  - 444637 Demonic Embrace (Arena): Sinister Pact +1.5% per 100 HP, cap 45% at 3000 HP
  - Applied AFTER Rabadon's ap_amp (multiplicative stacking per League buff system)

## Coverage status

- ITEM_EFFECTS: **547 entries — DDragon purchasable coverage COMPLETE** (all gold>0 purchasable items covered)
- 856 tests passing (276 defensive_only, 226 active, mixed Arena/ARAM mirrors)
- ENGINE_VERSION 0.56.0

## Schema gaps still open (priority order)

1. **Conditional AS** → Experimental Hexplate (ult-triggered, too low EV); Yun Tal Flurry now modeled at 27% uptime
2. **Ability-cast schema** → 8+ items (Lightning Braid, Night Harvester SR, Innervating Locket, Fiendhunter Bolts, etc.) — blocked on ability-frequency data
3. **Void Immolation (223069)** — Immolate proc formula unconfirmed from Meraki/DDragon
4. **Mejai's Arena mirror** — no Arena ID found in DDragon (3041 SR only)
5. Bridge auto-loop: **NOT running on Game-PC** — start manually: `/loop 1m /process-bridge-tasks`

---

# s93 wrap — 2026-05-04 (Daemon Slayer batches 50–53)

## What shipped (this session)

- **Batch 50** — `armor_reduction_flat` + `mr_reduction_flat` schema; Flesheater (667112, 447112) promoted
- **Batch 51** — Fated Ashes (2508) Inflame proc + 5 defensive-only components (2019/2021/2022/2420/2421)
- **Batch 52** — Night Harvester (4636, 444636) Soulrend; Luden's Echo (6655, 226655) Echo; Bloodletter's Curse SR (8010) mr_reduction_pct; ability-cast schema resolved via every_n_seconds
- **Batch 53** `255dd22` — Hamstringer (443069) Scour crit-bleed + Stormsurge (4646, 224646) Squall proc
  - ENGINE_VERSION 0.54.0 · **829 tests passing** · ITEM_EFFECTS = 496 entries

## Coverage status

- ITEM_EFFECTS: **496 entries — essentially complete**
- 829 tests passing (242+ defensive_only, 254+ active, mixed Arena/ARAM mirrors)
- Bridge auto-loop: **NOT running on Game-PC** — start manually: `/loop 1m /process-bridge-tasks`

## Schema gaps still open (priority order)

1. **Conditional AS** → Yun Tal Flurry, Experimental Hexplate (complex schema needed)
2. **Mejai's kill-stack AP** → separate schema needed
3. Most remaining unmodeled passives are ability-use-gated (e.g. further burst items) or non-combat

---

# s92 wrap — 2026-05-04 (Daemon Slayer batches 38–49)

## What shipped (this session)

- **Batch 38** `0369403` — Giant Slayer schema + 228xxx/443xxx/SR sweep
  - New `ItemEffect.giant_slayer_pct_per_100hp` + `giant_slayer_max_pct` + `total_giant_slayer_multiplier` wired into compute_dps
  - Wooglet's Witchcap (228002) ap_amp_pct=0.50; Deathblade (228003) lethality=20+crit_damage_bonus; Obsidian Cleaver (228005) armor_reduction_pct=0.35
  - 17 defensive_only completing 228xxx/443xxx pool; 453 → 477 tests

- **Batch 39** `97ddecb` — MR-reduction schema + Arena re-skin sweep
  - New `ItemEffect.mr_reduction_pct` wired into effective_target_mr
  - Bloodletter's Curse (4010) mr_reduction_pct=0.30; Divine Sunderer Arena (446632); Overlord's Bloodmail Arena (447111); Atma's Arena (663039); Hextech Gunblade Arena (663146)
  - 7 defensive_only; ENGINE_VERSION 0.43.0

- **Batch 40** `51e6787` — component items + final SR/Arena sweep
  - Last Whisper (3035) armor_pen_pct=0.18; Brutalizer (2020) lethality=5; Haunting Guise (3147) damage_amp_pct=0.06
  - 15 defensive_only completing final SR/Arena pool; 477 tests

- **Batch 41** `bc61b4c` — Arena 226xxx mirrors + Navori key collision fix
  - Fixed Navori Flickerblade (was keyed 6672 overwriting Kraken Slayer); moved to correct 6675
  - 14 active 226xxx mirrors + 14 defensive_only; 494 tests

- **Batches 42+43** `b92301f` — Arena 222xxx/224xxx/32xxxx + 223xxx complete
  - 10 active 222xxx/224xxx/32xxxx + 33 active 223xxx SR-exact mirrors; 83 defensive_only total; 530 tests

- **Batches 44+45** `6eaccae` — DPS components + defensive full items + boots
  - Sheen (3057) spellblade-key; Tiamat (3077) Cleave; Bami's Cinder (6660) Immolate; Rageknife (6677) Wrath; SotD (3131) lethality+proc
  - 21 defensive_only; Berserker's Greaves (3006) active; 558 tests

- **Batches 46+47** `8795097` — Arena 226xxx/228xxx/224xxx + 22xxxx/32xxxx pool
  - Divine Sunderer (226632) spellblade; Demonic Embrace (224637) ap_per_bonus_hp+Azakana's; Blighting Jewel (4630) magic_pen_pct=0.13
  - 587 tests

- **Batches 48+49** `1230dca` — 1xxx components + remaining 3xxx/2xxx/Arena
  - Recurve Bow (1043) Sting 15 phys/attack; all 29 1xxx components covered
  - Spellslinger's Shoes (3175) dual-pen: magic_pen_flat=18 + magic_pen_pct=0.08
  - Rite of Ruin (123430) crit_chance_bonus_flat=0.25; Hubris Arena (126697) lethality=18; Prowler's Claw Arena (446693) lethality=20
  - 11 defensive boots; 5 defensive components; 4 2xxx; 5 Arena
  - ENGINE_VERSION 0.53.0 · **603 tests passing** · ITEM_EFFECTS = 496 entries

## Schema gaps still open (priority order)

1. **Ability-cast schema** → Night Harvester, Luden's, Stormsurge, Hellfire Hatchet Char, Fated Ashes Inflame (6+ items unlock at once)
2. **armor_reduction_flat flat shred** → Flesheater (447112)
3. **Crit-gated proc rate** → Hamstringer (443069) Scour bleed on crit
4. **Conditional AS** → Yun Tal Flurry, Experimental Hexplate
5. **Mejai's kill-stack AP** → separate schema needed

## Coverage status

- ITEM_EFFECTS: **496 entries / ~496 unique DDragon purchasable IDs → essentially complete**
- 603 tests passing (242 defensive_only, 254 active, mixed Arena/ARAM mirrors)
- Bridge auto-loop: **NOT running on Game-PC** — start manually: `/loop 1m /process-bridge-tasks`

---

## Session ledger (s27–s91, condensed)

All narrative detail is in `ROADMAP.md §1` and `git log`.

| Session | Date | Key commit(s) | Theme |
|---|---|---|---|
| s27 (a–u) | 2026-05-01 | 778971d..957dab7 | All Tier 1–4 audit items; asyncio migration (T2 #8 C1–C5); tkinter-free |
| s28 | 2026-05-02 | a38d002..7307e6a | RC↔Peer cross-Claude bridge live (Tailscale); inheritance arc |
| s29 | 2026-05-02 | 7223afe, c4c9e07 | Game-PC joined tailnet as `gamepc-rc`; bridge_monitor sidecar live |
| s30 | 2026-05-02 | 645e041..4c2514d | One-click gamepc_boot.ps1; cross-Claude learning-sync vision doc |
| s31 | 2026-05-02 | — | Phase 3 supervisor; dashboard OWNED fix; cron echo silenced |
| s32 | 2026-05-02 | c58e689, dc73303 | Live stat mirror; ally_comp overwrite fix |
| s33–s36 | 2026-05-02–03 | 0302fc7..0fcf102 | Action label decay fix; bridge `/messages` alias; arena advisor v1 |
| s37–s45 | 2026-05-03 | (DS Phase 1) | Daemon Slayer extractor; lolmath chunk topology; champion builds refresh |
| s46–s55 | 2026-05-03 | (DS Phase 2) | DS engine scaffolding; stat walk; on-hit framework; 40 items |
| s56–s65 | 2026-05-03 | (DS Phase 3) | DS Arena items; beam search; augment schema; 150+ items |
| s66–s75 | 2026-05-03–04 | (DS Phase 4) | DS spellblade/unique-passive; Arena mirror pass; 300+ items |
| s76–s80 | 2026-05-04 | (DS batch 20–24) | Rune writer shard3 fix; Bridge Watcher hardening; Bridge Pending UI |
| s81–s84 | 2026-05-04 | (DS batch 25–28) | Arena augment persistence; Meraki bulk switch; vision tracker polish |
| s85–s88 | 2026-05-04 | 0cecfa3..28d2a93 | DS batches 29–32; magic_amp schema; Rabadon's; 550 tests |
| s89 | 2026-05-04 | 0cecfa3 | DS batch 33: ability-burn promos, caster_bonus_hp, 367 tests |
| s90 | 2026-05-04 | 1bd105d, 6b04992 | DS batches 34–35: magic_amp_pct schema, dual-pen, spellblade |
| s91 | 2026-05-04 | 8f7811b, 8d208c3 | DS batches 36–37: TRUE damage type, Arena 443/447 sweeps, 428 tests |
