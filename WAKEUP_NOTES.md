# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-30 - item 217 (/headless-upgrade run, operator away): DS caster-stat test-hardening + lolmath-wiki feasibility (item 216 carry a) + competitor-lift gate slate + cost/latency CLEAN (3 commits `f8d7ae8` + `2681bf5` + `93b313c`; non-engine; non-frozen; no DS/RC restart)

Long autonomous run. Orchestrator + 2 background research agents; merger verified EVERY agent premise vs live code before commit (caught 2 stale claims).

**Shipped:**
- `f8d7ae8` test(ds): NEW `agents/daemon_slayer/tests/test_caster_stat_scaling_2026_05_30.py` 13 tests / 110 subtests. Item 216 wired 3 caster-stat fields into the live evaluator but verified them ONLY live at ship; this pins the math as committed regression (from_build caster_armor = FULL armor NOT bonus-only; caster_bonus_mp/ms above-base; _evaluate_block linearity; Malphite W +22.5 + Janna 0.0). ENGINE unchanged; DS 4896 -> 4907 green.
- `2681bf5` docs: `docs/LOLMATH_WIKI_SOURCE_2026-05-30.md` (item 216 carry a, CLOSED as research) + `docs/COMPETITOR_LIFT_2026-05-30.md` (5 HIGH lifts deepened to gate specs).
- `93b313c` docs: CLAUDE item 217 + BACKLOG gate slate (6 lifts + wiki extractor) + COMPETITOR doc item-200 correction.

**lolmath-wiki verdict:** GO-conditional SIDECAR extractor. Live probes: Cargo GONE (wiki.gg -> Bucket ext + Scribunto); action=bucket read-callable; Module:ChampionData serves live. Net-new fields: AA-timing, static-CD flags, charge/ammo, Arena/URF/NB mode-mults. MERGER CORRECTION: ARAM mode-mults NOT a gap (Meraki aram_modifiers covers + DS applies dealt/taken/tenacity) - agent's "biggest win fixes ARAM" was the known false-claim pattern; net-new for non-ARAM modes only.

**Cost/latency 7-lever: CLEAN no-commit** (all green; details in CLAUDE item 217). Sub-note: agent6 auditor pinned claude-opus-4-7 (current Opus is 4-8) - model-currency, operator-gated, not a degrade.

**Carries forward (tomorrow-you):** (a) competitor-lift gate slate (6 lifts) in BACKLOG.md + pick-list/specs in docs/COMPETITOR_LIFT_2026-05-30.md - operator picks which to build (all OPERATOR-GATE). (b) relative-score bar needs a NEW render surface (item 200 removed the DS-top-picks row) - do NOT re-pitch as a trivial decoration. (c) do NOT re-pitch the wiki for ARAM mode-mults (already covered by Meraki). (d) item 215 LIVE VERIFY (relocated agents) + OBS launch-test still owed (live/operator-gated).

---

# 2026-05-30 - item 216: DS ability unit-map exhaustion + 3 caster-stat scaling fields wired (2 commits `9b61dc7` + docs `6ddfaa6`; ENGINE 1.62.0 -> 1.63.0; DS restarted 1.63.0; RC untouched)

Triggered by lolmath-handoff staging (extractor "extend `_UNIT_TO_FIELD`" note). A workflow classified all 29 unmapped Meraki damage-modifier unit strings: 8 typed, 21 intentional leaves (12 per-100-stat/per-stack/conditional amps + 9 Meraki mis-split crit-formula fragments).

**Shipped `9b61dc7`:** extractor `_UNIT_TO_FIELD` +6 (possessive-AP `% of Sona's/Ivern's AP` -> ap_pct; double-space `%  bonus AD` -> bonus_ad_pct; `% armor` -> caster_armor_pct; `% bonus mana` -> caster_bonus_mp_pct; `% bonus movement speed` -> caster_bonus_ms_pct) + `_canonicalize_unit` whitespace-only -> base (TahmKench Q / Lucian R flat dmg was silently dropped). `tools/migrate_abilities_units_2026_05_30.py` in-place re-typed 16.10.1 + 16.11.1 (NO Meraki re-fetch - mutable-latest rule; `.bak-units20260530-*` backups left untracked). 3 new caster fields wired end to end into the LIVE evaluator: DamageBlock + `_SCALING_FIELDS` + AbilityContext + `_SCALING_TARGETS` + from_build; caster_bonus_* follow the existing "above level-1 base" convention; DEFAULTED at END of frozen dataclass (inserting mid-class = 41-failure trap). ENGINE 1.62.0 -> 1.63.0 + 33 pin files. NEW `tests/test_abilities_unit_map_2026_05_30.py` 8/8.

**Verified:** DS suite 4894 passed / 0 fail; ruff clean; DS :8893 restarted 1.63.0 / 16.11.1 / 172 / 705; phase8 live engine 18/18 post-restart. Malphite W: caster_armor_pct recovers +22.5 raw (rank5, 150 armor) old parser dropped = ~29% on-cast understatement now corrected. Janna caster_bonus_ms 0.0 itemless (no overcount).

**Carries forward (tomorrow-you):** (a) lolmath wiki-source analysis OWED (operator on wakeup): whether wiki.leagueoflegends.com exposes Module:ChampionData via MediaWiki action=raw / Cargo cargoquery - the extractor normalization layer (unit-map + form stitching) is the reusable part if so. (b) external handoff bundle `Desktop\lolmath_handoff` (+ .7z) is NOT git-tracked + carries zero personal/outreach metadata (see [[feedback_keep_outreach_out_of_repo]]) - keep both true. (c) the 21 intentional unit leaves are NOT a parser gap (second-order amps + Meraki crit-garbage); ok_rate stays 0.9896 because residual is structural; do NOT re-attempt typing them. (d) item 215 LIVE VERIFY still owed (relocated agents push runes/items/summoners in champ select).

---

# 2026-05-29 - item 215: 1-PC consolidation EXECUTE + RC game-host config + agent relocation (1 commit `2e6081c` pushed origin/main; ADR-011; RC restarted pid 14944)

Migration session driven by the outside-repo runbook `Desktop\Legion-Migration-Plan`. Operator executed Phases 0-9: firmware spoof-in-place on Legion (NO hdd swap - same Win10 install, InstallDate 2026-04-18 / ProductId AA858; serials/MAC/UUID/MachineGuid re-rolled, Windows hostname now DESKTOP-JKZECV9 but Tailscale node STAYS legion-rc). League + Vanguard installed = clean-break identity. Post-Vanguard audit verified the spoof HELD (no re-roll; vgk Running). SystemSKUNumber="SKU" + EDID AOC Q27GBZD operator-accepted. Records archived to the Desktop folder (legion_identity_for_records.txt + post-vanguard audit).

Pivot: Game-PC OUT of League/RC entirely. OBS now local on Legion (NOT the Game-PC OBS-server plan) - pre-seeded `%APPDATA%\obs-studio` Display Capture WGC / NVENC / 1080p60 / mkv / C:\RC-Recordings.

**Shipped `2e6081c` (Phase 11 coaching slice):** `core/game_host.py` NEW `RC_GAME_HOST` (default 127.0.0.1) - 9 live readers flipped off hardcoded Game-PC IP 192.168.8.237 (incl FROZEN `lcu/lcu_client.py`, operator-granted). Agents relocated to Legion-local ONLOGON tasks: RC-LCUAgent + RC-LiveClientRelay + RC-HotkeyListener (Game-PC copies taskkilled; phase_watcher NOT relocated + RC-PhaseWatcher disabled - BSOD class). `tests/test_game_host.py` 4/4. ADR-011 + CLAUDE.md + ARCHITECTURE topology. Side-fixes (no commit): window-flash (RC-PatchRefresh + RC-PostmortemAnalyze Interactive->S4U), Acrobat error 1920 (Spooler Disabled->Automatic+started).

**Carries forward (tomorrow-you):** (a) **LIVE VERIFY OWED** - open League champ select to confirm relocated agents push runes/items/summoners + in-game :2999 flows (only real test; operator was not in client). (b) poller is relay-first: if RC-LiveClientRelay dies a :8889 404 wrongly short-circuits "no game" - watch it, or refactor poller to prefer direct local :2999 (ADR-011 watch-for). (c) OBS Display Capture = continuous DXGI = match-end BSOD class; watch. (d) OBS launch-test owed (operator opens obs64.exe, verify NVENC engages + Display Capture previews). (e) Game-PC cross-Claude bridge KEPT (operator decision). (f) Deferred Phase 11: in-process vision collapse, archive gamepc_*.py, ARCHITECTURE agent-section rewrite. (g) Migration Phases 0-9 + agent relocation DONE - do NOT re-run spoof/Vanguard.
