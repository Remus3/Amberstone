# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-30 - item 218: competitor lift #5 matchup cooldown-watch card (1 commit; non-engine; non-frozen; no ENGINE bump; no DS restart; RC restarted pid 20228)

Operator read wakeup+backlog, then picked lift #1 (cooldown-watch) off the item-217 competitor-lift gate slate via AskUserQuestion. Shipped the full vertical slice. Pure presentation JOIN - NO new compute, NO ENGINE math change, NO schema lift, NO new dep.

**Shipped:** NEW `agents/daemon_slayer/cooldown_watch.py` `compute_cooldown_watch(roster, top_n=5)` - per enemy champ, joins the single highest-threat hard-CC ability (longest max-rank duration across `_PER_SPELL_CC_DURATIONS` + `cc_conditional.get_conditional_entries`) to its max-rank base `cooldown` from `champion_abilities.json` (patch-pinned loader). Mode-agnostic (cooldown is intrinsic to the ability). NEW route `dashboard/routes_cooldown_watch.py` GET `/api/cooldown-watch?enemy=...[&top_n=5]` (sibling of routes_cc_conditional_pressure; 5-min cache; 400/no_champions/503). Wired into `_dispatch.py`. Frontend: NEW `web/js/panels/cooldown_watch.js` + `web/css/panels/cooldown_watch.css` + @import + `#csv-sugg-cooldown-watch` block (below the cc-conditional-pressure chip) + `_csvRenderCooldownWatch(cs)` (ENEMY-only, reads `cs.their_team`) + cdw cache-count in the section sig. v1 honesty: BASE cd by rank, NOT haste-adjusted (no live enemy AH; summoner_cooldowns is a separate summoner+ult layer - this is the Q/W/E base layer, previously unconsumed).

**Tests (55 new):** `test_cooldown_watch_2026_05_30.py` 21 (grounded vs 16.11.1: Blitz Q 1.0/cd16, Leona headline R 1.5/cd60, Aatrox COND W root 1.75/cd12, Morgana uncond Q 3.0 beats cond R 2.0, tie-break lower-cd, fail-soft, dedup) + `test_routes_cooldown_watch.py` 16 + `test_cooldown_watch_panel_dom.py` 18.

**Verified:** DS cooldown 21/21; RC suite 3840 passed/1 skip/71 subtests (excl phase8); ruff + py_compile + node --check clean; CSS parity 27 -> 28 (4/4). RC restarted -> pid 20228 alive reload_ok. Live curl enemy=Blitzcrank,Leona,Aatrox -> 3 cards sorted Aatrox(1.75)/Leona(1.5)/Overlay App E(1.0); missing enemy 400; empty no_champions.

**Carries forward (tomorrow-you):** (a) **LIVE VISUAL CAPTURE OWED** - card render-gates on committed enemies (`cs.their_team` ids); mock fixtures have empty their_team + operator was mode=client, so no live champ-select rendered it; capture at next champ-select with enemies locking. (b) READ-ONLY JOIN: do NOT bump ENGINE or restart DS :8893 (route imports in-process on :8888). (c) remaining 5 gate-slate lifts unchanged (BACKLOG.md:19). (d) all item 217 + 215 carries unchanged (item 215 LIVE VERIFY relocated agents + OBS launch-test still owed).

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
