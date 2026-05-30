# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-30 - item 221 NEAR-COMPLETE: lolmath-wiki extractor + combo.py consumer wire shipped (2 commits db4c268 + merge 56980d6; NO ENGINE bump 1.63.0; NO DS restart; RC restarted for combo/data_loader). ONLY sidecar DATA owed - wiki host-blocked (re-probed +35min, still 401)

Operator "in parallel: start all Open/actionable" (3rd same-prompt drain). AskUserQuestion picked lolmath-wiki off BACKLOG:20; on the wiki-blocked fork picked "ship tool now, data+wire owed". Targets item-217 GO-conditional (`docs/LOLMATH_WIKI_SOURCE_2026-05-30.md`).

**Shipped:** NEW `tools/daemon_slayer_wiki_stats_extract.py` (offline patch-refresh, mirrors abilities-extractor: stdlib urllib + UA + --sleep + fail-soft + atomic + ASCII + argparse). Calls `action=expandtemplates&text={{#invoke:ChampionData|get|<DisplayName>|<field>}}` (lean; item-217 probe verified Aatrox attack_cast_time->0.3). Fields: attack_cast_time (AA windup; replaces combo.py `_DEFAULT_AA_WINDUP_S=0.25` per-champ) + missile_speed (ranged; bare-then-`stats.` fallback). Champ ids from abilities snapshot top-level `data` dict (171 @ 16.11.1; keyed under `data` NOT `champions`). Names from `data/meta_build/ddragon/<patch>/champion.json` `.data.<id>.name` (ChampionData keyed by DISPLAY name - Kaisa->Kai'Sa, MonkeyKing->Wukong). NEW `tests/test_wiki_stats_extract.py` 33 offline tests (no network; monkeypatched `_expand`).

**BLOCKER:** live extraction did NOT run, NO sidecar data committed - wiki edge-blocked EVERY call from Legion (401 tool-UA / 403 + wiki.gg "Blocked" interstitial browser-UA = Cloudflare bot-block, NOT a UA gate; clean sub-agent probe confirmed). Item-217 agent reached it earlier same day -> likely rate-trip from my ~40 probes or host-egress rule, not permanent. Tool `--dry-run` from Legion correctly prints `WARNING: 0 champs resolved a cast time ... NOT a committable sidecar` + writes nothing.

**Verified:** py_compile + ruff clean; 33/33 offline tests; dry-run WARNING proven; no wiki_stats.json written.

**Process note:** an over-optimistic earlier batch drafted FABRICATED build outcomes ("action=bucket DEAD", "172/170 with cast_time") from misread all-401s; cascade-cancel + manual `git checkout` of 4 docs reverted ALL of it pre-commit. Shipped tool carries ONLY item-217-verified claims + edge-block note. ([[feedback_verify_generated_reports]] + [[feedback_verify_before_declare_broken]].)

**combo wire DONE (merge 56980d6):** data_loader DataSnapshot optional `wiki_stats` frozen field + `wiki_attack_cast_time()` accessor (load() reads `_read_optional("wiki_stats.json")`; missing/degenerate -> {} never raises); combo.py AA windup reads per-champ value when present, else `_DEFAULT_AA_WINDUP_S`=0.25 (the existing default, found+preserved). SPELL path untouched (Meraki authoritative). Byte-identical when sidecar absent OR all-null (pinned by ComboWireTests). 13 new tests; DS suite 5008->5021. A degenerate all-401 wiki_stats.json from the first optimistic run was written-but-never-committed (untracked); DELETED so absent-path is genuinely exercised.

**The ONE remaining OWED piece:** run `py tools/daemon_slayer_wiki_stats_extract.py --patch 16.11.1` from a host that reaches wiki.gg (Legion is host-blocked: 401 on every call, confirmed persistent at +35min - NOT a transient rate-trip; the wiki itself is live per item-217). Commit `data/daemon_slayer/16.11.1/wiki_stats.json` ONLY if `_with_cast_time>0`. The moment a real sidecar lands, combo.py consumes it with NO further code change. Plus: action=bucket mode-mults (Arena/URF/NB) NOT built (ARAM Meraki-covered); all item 220 carries unchanged.

---

# 2026-05-30 - item 220: 3 deferred/held competitor-lift items in parallel - statcheck stat-sandbox + relative-score bar + fight-length-reweight knob + item-218 forward-marker fix (3 worktree merges + 1 wiring commit; non-engine; non-frozen; NO ENGINE bump; NO DS restart; RC restarted pid 17136 -> 15580)

Operator "in parallel: start all Open/actionable" (same prompt as item 219). This run drains the 3 buildable items item 219 left HELD/DEFERRED. AskUserQuestion scope-fork: operator picked all 3 (statcheck #5 + relative-score-bar #3b as own panel + fight-length-reweight knob); lolmath-wiki extractor stays gated. Orchestrator-merge: 3 parallel worktree agents on disjoint slices; orchestrator wired the 5 shared files + folded in the item-218 pre-existing-failure fix.

**3 slices shipped (each READS existing engine math, NO ENGINE bump):**
- (A) **statcheck stat-sandbox** (lift #5): NEW `dashboard/routes_ds_statcheck.py` `/api/ds-statcheck` wraps `compute_dps` for the locked champ at operator-set TARGET stats (blank -> auto curve) -> resolved CHAMPION stat block (`DpsResult.stats`: ad/ap/as/crit/hp/mp/armor/mr) + dps + phase + `ds_statcheck.js` (editable enemy-armor/MR/HP/bonusHP inputs, debounced) + .css. DpsResult has NO ttk; champ-side AD/AS/crit DISPLAYED not editable (no engine stat-injection arg).
- (B) **relative-score bar** (lift #3) - **resolves the long-HELD surface decision: shipped as its OWN panel `#csv-ds-relscore`** (item 200 deleted the DS-top-picks row; the item-219 lifts each got own panel = same pattern). NEW `dashboard/routes_ds_relscore.py` `/api/ds-relscore` READ-ONLY (no knobs, auto target stats) wraps `rank_items` -> per-row `score_pct = delta_dps/top_delta*100` (row0=100.0) + `ds_relscore.js` (horizontal bar fill = score_pct%, hero element) + .css.
- (C) **fight-length-reweight knob** - closes item-219 C DEFERRED. `rank.py` `rank_items` gains `fight_length: Optional[float]=None` (END of sig) + `RankedItem.effective_score: float=0.0` + `_safe_burst()`. None/<=0 = **BYTE-IDENTICAL** (pinned by `ByteIdenticalWhenNoneTests`). Set = `effective_score = (burst(build+item)-burst(build)) + delta_dps*fight_length` (burst only when engaged), sort DESC - short=burst, long=sustained. `routes_ds_knobs.py` threads &fight_length + docstring DEFERRED->SHIPPED; `ds_knobs.js` 4th "Fight length (s)" input. NOT an ENGINE bump (in-process helper; :8893 /rank never passes fight_length).

**Item-218 pre-existing-failure fix (folded in, not a separate branch):** item 218's `cooldown_watch.py:50` imports `cc_conditional` but never registered in the forward-marker guard `_ALLOWED_SOURCE_FILES` (was `{"cc_pressure.py"}`) - guard red since item 218. Added `"cooldown_watch.py"`. Real intended consumer; does not loosen the seam.

**Wiring (5 shared files, +17/-1):** `_dispatch.py` 2 imports + 2 GET_ROUTES; `dashboard.css` 2 @imports (parity 32->34); `index.html` 2 blocks; `champ_select.js` 2 imports + 2 mounts + 2 cache decls + dsr/dss sig tokens; forward-marker allow-list +1.

**Verified:** new panel+route+knob 83 passed; forward-marker + rank fight-length 22 passed (item-218 guard GREEN); full DS + full RC suites green; ruff + py_compile + node --check clean. RC restarted -> pid 15580 alive reload_ok mode=client. **Live curl all 3 ok=true:** ds-statcheck Caitlyn dps=25.86 + 8 stat keys + auto armor95/mr63; ds-relscore Caitlyn 12 rows top3 Runaan's 100.0/ER 96.6/Kraken 92.0; ds-knobs fight_length=3 top3 ER/IE/Lord Dominik's vs fight_length=20 Runaan's #2 + Kraken #3 - **inversion proven live**.

**Carries forward (tomorrow-you):** (a) **LIVE VISUAL CAPTURE OWED** statcheck + relscore (gate on LOCKED champ; operator mode=client) + the new ds-knobs fight-length input; capture at next champ-select. (b) lolmath-wiki extractor STILL gated (external dep, BACKLOG:20). (c) item-219 carries unchanged EXCEPT relative-score bar HELD->SHIPPED + fight-length-reweight DEFERRED->SHIPPED. (d) item 218 cooldown-watch capture + item 215 relocated-agent LIVE VERIFY + OBS launch-test still owed (live-gated). (e) 3 worktree branches harness-locked. Don't bump ENGINE / don't restart DS for any of these (in-process route reads). `RankedItem.effective_score` additive optional (default 0.0); `rank_items(fight_length=None)` MUST stay byte-identical.

---

# 2026-05-30 - item 219: 4 competitor-lift panels in parallel (5 worktree merges + 1 wiring commit; non-engine; non-frozen; NO ENGINE bump; NO DS restart; RC restarted pid 17136)

Operator "in parallel: start all Open/actionable" off wakeup+backlog. Orchestrator-merge: 5 parallel worktree agents on disjoint NEW-files slices; orchestrator wired the 5 shared files. HELD (stated): relative-score bar (lift #3 - needs a NEW surface, item 200 removed the DS-top-picks row = product call) + lolmath-wiki extractor (external MediaWiki dep, own gate). Live-owed skipped.

**4 panels shipped (each NEW route + panel js/css + tests; READ existing engine math, NO ENGINE bump):**
- (A) stat-sweep graph: `agents/daemon_slayer/dps_sweep.py` + `/api/ds-sweep` + `ds_sweep.js` (reuses spike_curve sparkline; armor/mr/level axes; champ-select card `#csv-sugg-ds-sweep`).
- (B) action-queue combo sim: NEW `agents/daemon_slayer/combo.py` (composes `compute_burst_damage` + mitigation; per-hit timeline; v1 fixed cast-times 0.25s fallback, on-CD recast skipped) + `/api/ds-combo` + `ds_combo.js` (host `_csvRenderDsCombo` wrapper owns input re-fetch).
- (C) engine-knobs v1: `/api/ds-knobs` wraps `rank_items` (NOT :8893 dispatcher - no budget arg) with target_armor/mr/budget overrides + `ds_knobs.js` 3-input strip; fight-length-reweight DEFERRED (needs new engine arg).
- (D) live power-spike markers: NEW `agents/daemon_slayer/spike_markers.py` (level 6/11/16 + item 1/2/3, crossed/next/future) + `/api/spike-markers` + `spike_markers.js` on ACTIVE-MATCH (`_renderSpikeMarkersFromCtx`, keyed p.level+p.items); live-clock cursor OWED.
- (E) type-hints + ruff (BACKLOG:33 CLOSED): 14 public-API param-type sites across coaches/core/dashboard/tft/lcu/agents; ruff clean; 0 behavior change.

**Verified:** RC suite (excl phase8) 4025 passed/1 skip/71 subtests (+185); phase8 70/70; DS combo+spike+CSS-parity 70/70; ruff + py_compile + node --check clean. RC restarted -> pid 17136 alive reload_ok. Live curl all 4 ok=true (sweep 13pts/combo 5hits/knobs 8rows/spike 6markers). DOM WiringTests flipped skip->pass after wiring (1 skip left vs ~10).

**Carries forward (tomorrow-you):** (a) **LIVE VISUAL CAPTURE OWED** all 4 panels - champ-select trio gates on a LOCKED champ (`cs.my_champion`), spike-markers on a live InProgress game; operator was mode=client; capture at next champ-select + next game (spike-markers live-clock cursor also OWED). (b) relative-score bar STILL HELD (new-surface product call). (c) lolmath-wiki extractor STILL gated. (d) item 218 cooldown-watch capture + item 215 relocated-agent LIVE VERIFY + OBS launch-test all still owed. (e) 5 worktree branches harness-locked (parent owns lifecycle). Don't bump ENGINE / don't restart DS for any of these 4 (in-process route reads).

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

