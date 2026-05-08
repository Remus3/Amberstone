# RC session history archive

Sessions older than the last 2–3 full sessions are progressively compacted here.
Current WAKEUP_NOTES.md keeps only the most recent 2–3 sessions.
Compaction rule: 3+ sessions old → 1-2 line summary entry below.

---

- **s116 2026-05-08** — Game-PC boot fix + Smite jungler detection (1ef54e3/2229d89/6bec3ce): `gamepc_boot.ps1` now calls `start_gamepc_claude.ps1`; Smite-based 3-tier jungler cascade in `game_reader.py`; 8 new tests.
- **s115 2026-05-07** — DS calibration game_id wiring (d66d14b): `gamepc_lcu_agent.py` fetches `gameData.gameId` in-game; `game_reader.py` reads `/latest-lcu` relay; `coach_integration.py` passes game_id to `log_ds_run()`.
- **s114 2026-05-07** — Bridge Watcher Phase 3 (6dd91ff): `--dry-run` mode, artifact rotation, self-healing watchdog thread; 21/21 selftests.
- **s113 2026-05-07** — Bridge Watcher Phase 2 (05983a4): adaptive cadence (`_read_mode()`), active/sleep/auto modes, `/api/bridge/cadence`, `/sleep`+`/wake` slash commands.
- **s112 2026-05-07** — Bridge Watcher Phase 1 (f6095a0): sliding 24h event ring, push notifications, RC-DaemonSlayer result=1 fix.
- **s111 2026-05-06** — Infrastructure fixes: RC-BridgeWatcher + RC-Phase3-Supervisor restarted; `claude-rc.ps1` `/loop` removed; ROADMAP fleet-health items marked ✅.
- **s110 2026-05-06** — Cross-Claude sync Phase 3 + DS/roadmap doc cleanup. `_lessons_summary()` in `rc_facts.py` for SessionStart hook (4c4ce1a); ROADMAP/CLAUDE/README doc cleanup (b6d02ae).
- **s109 2026-05-06** — Memory library: 6 new memory entries (feedback + reference patterns). No code changes to RC repo.

---

# s108 wrap — 2026-05-06 (WT flash fixes — Legion + Game-PC)

- `dashboard/server.py`: `creationflags=0x08000000` on vision server Popen (commit `cab0ce4`). Game-PC `gamepc_bridge_daemon.py`: `--dangerously-skip-permissions` fix + DEVNULL suppression — stopped 807+ crash-loop invocations per day.

---

# s107 wrap — 2026-05-06 (API cost audit + dynamic debounce + CLAUDE.md slim)

## What shipped
- **Vision loop gate** — `_run_vision()` guards in ARAM/Arena/Brawl coaches: `if self._fetch_game_data() is None: return`. Kills 24/7 Sonnet burn when no game is active (was 84% of LoLOverlay key spend on May 4).
- **Dynamic debounce** — all 3 coaches: `_STABLE_DEBOUNCE_S` class attr (ARAM 25s / Arena 22s / Brawl 20s). `_on_state_received` sets `self._DEBOUNCE_S` to stable rate when no meaningful state change; snaps back to fast rate on dead_enemies / items / level / hp_pct drop ≥10.
- **CLAUDE.md slimmed** from 355→109 lines. Deep docs moved to `docs/AGENTS.md` (new) + `docs/DAEMON_SLAYER.md` (new). Bridge spawn cost note added.
- **Settings cleanup** — both `.claude/settings.json` files: removed `typescript-lsp` plugin; `additionalDirectories` `C:/` → `C:/Riot Commander`.
- Commits: `5658b1f` (vision gate + debounce + CLAUDE.md slim)

---

## s106 wrap — 2026-05-05 (DaemonSlayer flash fix + preflight expansion)

### What shipped
- **`ops/RC-DaemonSlayer.xml`** — `python.exe` → `pythonw.exe`; task reinstalled. No more console flash on boot/restart. DS live at `:8893` engine=0.60.0 patch=16.9.1.
- **`start_claude.ps1`** — added RC-DaemonSlayer + RC-Phase3-Supervisor + RC-BridgeWatcher preflight checks; `:8893` + `:8890` HTTP probes; final `claude` launch fixed to `--name "Legion"`. commit `0d1b545`.

### Do NOT redo
- RC-DaemonSlayer XML is already pythonw.exe.

---

## s92–s103 detailed notes (2026-05-04 – 2026-05-05)

### s103 — 2026-05-05 (DS champ-select panel + dashboard bug fixes)
- **DS champ-select panel** `112350a` — `#cs-ds-block` + `/api/ds-preview` endpoint. Fires once per (champion, mode). Item tiles with +Ndps tooltips.
- **SR SSE mode fix** `5ee58b6` — `_state_builder.py` returned `mode_key="game"`; JS `driveNow` dropped all SR state. Fixed to `"sr"`.
- **Item icon cache race** `f5ce231` — `_itemResolveCache` cached null before `items_index.json` loaded; idempotency sig blocked re-render. Fix: clear cache + tile sigs on ITEMS load.
- **Augments pill fix** `5ee58b6` — CSS `static-pill` overrode `.hidden`; now `display:none !important`.
- **`/done` §6b living-doc sync** `d6fbce0` — ROADMAP/CLAUDE.md/README updated as part of done ritual.

### s102 — 2026-05-05 (SR coach signature hash fix + RECOMMENDED panel)
- **SR coach hash fix** (frozen, user-approved) — `_state_signature` fallbacks had wrong key names vs `_convert` output. hp_bucket/mana_bucket/gold_bucket/level all fixed. Coach now re-fires on HP changes, gold/item thresholds, level-ups, deaths.
- **RECOMMENDED panel** — `dashboard.js` falls back to `sr_items` when `item_build` empty; `next: true` items populate RECOMMENDED.
- **SR API key** — `API-Key-Claude.txt` written from CLI env to unblock SR coaching.

### s101 — 2026-05-05 (DS health indicator + Item Build DS picks panel)
- **DS health in `/api/health/all`** `50248a7` — probes `:8893/health`; DS down → yellow rollup.
- **Health dot tooltip** — DS engine status: `DS engine up · v0.60.0 · 547i/168c`.
- **Item Build panel DS section** — `#ib-ds-block` renders `daemon_slayer_picks` as `.ds-chip` compact chips with green delta-dps text.

### s100 — 2026-05-05 (Tiered vision + open-items cleanup)
- **Tiered vision** `46e9fb8` — `GameVisionReader.read_tiered()` + `read_or_escalate()` wired into ARAM/Arena/Brawl. OCR first; `timer` canary gates Sonnet escalation. Expand by calibrating `data/vision_regions.json`.
- **Open items** `41c87bc` — rune writer SR shard3: 5002→5001; items_index.json alias collision sorted by ID length; Yunara phantom dups: zero-duration exit + 90-min dedup.

### s99 — 2026-05-05 (Daemon Slayer batch 64 — Malignance + Stage 5 calibration)
- **Batch 64** `e7c4cd9` — Malignance Hatefog promoted (ENGINE_VERSION 0.60.0, 929 tests). New `CallContext.ult_casts_per_sec` + `ult_rates.py` (172 champions from rewind_history.db). Deferred: 3 (Lightning Braid, Kinkou Jitte, Mejai's Arena).
- **Stage 5 calibration pipeline** — `core/ds_calibration.py` + `data/ds_calibration.jsonl`; all 4 coaches log DS picks per tick.

### s98 — 2026-05-05 (Daemon Slayer batch 63 — blocked items resolved)
- **Batch 63** `e56e878` — Hellfire Hatchet (CD=15s confirmed), Fiendhunter Bolts (CD=45s confirmed), Innervating Locket Fill the Soul promoted. ENGINE_VERSION 0.59.0, 922 tests.
- Key insight: check Meraki `passives[].cooldown` before deferring "ability-triggered" items.

### s96 — 2026-05-04 (ARAM DS-before-Haiku refactor + documentation sweep)
- **ARAM coach DS-before-Haiku** `3b84949` — DS `rank_for()` before `messages.create()`; `{ds_picks}` injected into user turn; pre-DS hardcoded item rules removed (−37% system prompt ~1,849→1,170 tokens).
- **Documentation sweep** — CLAUDE.md, README.md, ROADMAP.md updated. `DS_COMPLETION_ROADMAP.txt` created on Desktop.

### s95 — 2026-05-04 (Daemon Slayer batches 57–62)
- Batches 57–60 `9f128c4..864e65d` — `caster_bonus_armor` + `caster_lethality` added; Void Immolation, Golden Spatula, Darksteel Talons, Bastionbreaker, Reality Fracture promoted. ENGINE_VERSION 0.57.0, 899 tests.
- Batch 61 `2148ed2` — Zaz'Zak's Realmspike + Bloodsong (spellblade + Expose Weakness damage_amp). 899 tests.
- Batch 62 `dcfeb63` — Cruelty dual-variant (Arena 447109 + SR 667109). ENGINE_VERSION 0.58.0, 911 tests.

### s94 — 2026-05-04 (Daemon Slayer batches 54–56)
- Batch 54 `ded3d01` — `bonus_ap_stacked` (Mejai's) + `bonus_as_conditional` (Yun Tal 27% uptime) + Sword of the Divine. ENGINE_VERSION 0.55.0, 843 tests.
- Batch 55 `e054c1c` — 46 defensive_only entries; DDragon purchasable coverage COMPLETE (547 entries, 850 tests). Coverage gate test added.
- Batch 56 `ede9c89` — `ap_amp_pct_per_100_caster_hp` schema; Demonic Embrace Arena. ENGINE_VERSION 0.56.0, 856 tests.

### s93 — 2026-05-04 (Daemon Slayer batches 50–53)
- Batch 50 — `armor_reduction_flat` + `mr_reduction_flat` schema; Flesheater promoted.
- Batch 51 — Fated Ashes (Inflame) + 5 defensive components.
- Batch 52 — Night Harvester, Luden's Echo, Bloodletter's Curse SR; ability-cast schema resolved via `every_n_seconds`.
- Batch 53 `255dd22` — Hamstringer Scour + Stormsurge Squall. ENGINE_VERSION 0.54.0, 829 tests.

### s92 — 2026-05-04 (Daemon Slayer batches 38–49)
- Batches 38–41 `0369403..bc61b4c` — Giant Slayer schema; `mr_reduction_pct`; Arena re-skins; Navori key collision fix. 494 tests.
- Batches 42–43 `b92301f` — Arena 222xxx/223xxx/224xxx/32xxxx mirrors; 83 defensive_only. 530 tests.
- Batches 44–45 `6eaccae` — Sheen spellblade; Tiamat Cleave; Bami's Cinder Immolate; boots. 558 tests.
- Batches 46–47 `8795097` — Divine Sunderer Arena; Demonic Embrace; Blighting Jewel. 587 tests.
- Batches 48–49 `1230dca` — 1xxx components complete; Spellslinger's Shoes dual-pen; Arena Arena. ENGINE_VERSION 0.53.0, 603 tests.

---

## Session ledger s27–s91 (condensed — from WAKEUP_NOTES compaction 2026-05-04)

All narrative detail in `ROADMAP.md §1` and `git log`.

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
