# WAKEUP_NOTES — RC hand-off ledger

> **Compacted 2026-05-04** (was 9,209 lines / 499 KB). Sessions s27–s91 reduced
> to a one-liner ledger below; full narratives live in `ROADMAP.md §1` and
> `git log`. Only the current session (s92) is kept at full fidelity.

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

1. **Arena + Brawl coaches**: move DS call from post-Haiku to pre-Haiku (same 30-min pattern as ARAM, no system prompt sections to prune). Best prompt: `"Wire DS into arena and brawl coaches — same DS-before-Haiku pattern as ARAM refactor (commit 3b84949)."`
2. **SR coach** (`core/coach_integration.py`): DS not wired at all — `sr_build_note` is static JSON. Highest-value remaining gap. Best prompt: `"Wire DS into SR coach. No DS wiring exists. Add rank_for() pre-Haiku, inject {ds_picks} in user turn, write daemon_slayer_picks to SR output JSON. mode='SR'."`
3. **Ability-cast schema**: blocked on ability-frequency data; see ROADMAP Stage 3
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
