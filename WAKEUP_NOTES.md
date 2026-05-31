# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-31 - item 228: DS V2 S1 - wire ability_hps v2 into LIVE enchanter HPS scorer (ENGINE 1.63.0 -> 1.64.0; HEAD 965bbb9; pushed 1288141..965bbb9; DS :8893 restarted serves 1.64.0)

Operator: "continue DS V2 next slices: wire ability_hps v2 into live ds.hps; compose 5 substrate into unified V2 fight-report; wire rune_procs into burst/combo; expand rune+champ coverage; review lolmath changelog; parallel agents; full+frozen rights; do not solely trust current DS; CI+smoke+commit+push+/done." Headless-upgrade run; CONTEXT RAN OUT after S1 -> wrapped per protocol. Only S1 shipped this session; S2/S3/S4/L are carry-forward (all designed in docs/DS_V2_PLAN.md + mapped this session).

S1 SHIPPED (merge worktree-agent-a4a4307ce720f5bd7 `d4729b7` + ENGINE bump `965bbb9`): compute_hps (hps.py:469) now folds champion-spell heal/shield into total_throughput via FUNCTION-LEVEL `from .ability_hps import compute_ability_hps` (module-level = circular; ability_hps.py:100 imports back; fail-soft try/except -> 0.0+note). 3 new HpsResult fields at END (ability_heal_hps/ability_shield_hps/ability_hps_total). total_throughput = direct + buff_credit + ability_hps_total. include_passive=True (no-op at 16.11.1), resolve_target_relative=False (conservative lower bound - Taric W stays lower bound). BYTE-IDENTICAL for champs with no ability heal/shield blocks (Caitlyn ability_hps_total=0). Soraka SR itemless L11 0.0 -> 8.836; +Moonstone/Redemption/Ardent = direct 10.52 + buff 15.0 + ability 11.42 = 36.94. Mana uptime gates ability cast cadence (real finite-mana in HPS). rank_items_by_hps recomputes ability HPS per candidate (AP item raises ability heal - intended).

Pre-existing pins updated (EXPECTED re-rank): test_hps.py 8, test_hps_hybrid_burst_p1l17.py 3, test_rank_enchanter.py 1 (Moonstone naked delta 0.0 -> 0.65). NEW test_hps_ability_wire.py 13t. ENGINE 1.63.0 -> 1.64.0 + 33 test-pin sync. DS 5191 -> 5204 (+13). ruff clean. DS restarted 1.64.0/16.11.1/172/705. CI in_progress at wrap (DS suite + ruff green locally).

DON'T-REDO: S1 re-rank intentional+validated; resolve_target_relative stays False in LIVE compute_hps (honest lower bound) - S2 fight-report can pass representative target_max_hp for richer numbers, do NOT enable in compute_hps without operator sign-off (over-credits Taric W). Function-level ability_hps import REQUIRED. compute_ability_hps NOT edited (v2 shipped item 227).

NEXT (the repeatable continue - S2/S3/S4/L unstarted; partition disjoint: S2=fight_report.py+server.py, S3=burst.py+combo.py, S4=rune_procs.py): (2) S2 NEW agents/daemon_slayer/fight_report.py compose mana_sim+rune_procs+self_shred+ability_hps+scenario_matrix into compute_fight_report + /v2/fight-report route (server.py _POST_ROUTES @1117-1132; _route_hps@951 = pattern; additive no bump). (3) S3 OPTIONAL `runes` param on compute_burst_damage (sig burst.py:422; total agg burst.py:775-777; in-scope ad=ctx.ad/ap=ap_total/bonus_hp=ctx.caster_bonus_hp @567-599; add rune_proc_damage field + keystone_amp PtA; Conqueror=stat-stack EXCLUDE) + thread runes through combo.py (composes burst @285-290); BYTE-IDENTICAL default runes=None (test_burst.py:153 + test_combo_2026_05_30.py:11-17 Lux pins MUST stay green); = next ENGINE bump 1.64.0 -> 1.65.0 (orchestrator owns __init__.py:1324 + 33-pin sync via `py` replace over tests/; agents leave version alone, no version pin in new tests). (4) S4 expand rune_procs.py 8 -> +Summon Aery 8214/Grasp 8437/Aftershock 8439/First Strike 8369/Coup de Grace 8299/Cut Down 8014 (amps); coeffs VERBATIM data/meta_build/ddragon/16.11.1/runesReforged.json (DDragon wins, NEVER invent). (L) re-review lolmath changelog for entries AFTER 2026-05-30 (item 227: 0 NOW/0 FUTURE/7 CLOSED).

CARRY: cost/latency 7-lever sweep NOT run (context). S1 worktree + item 227 R1 worktrees harness-locked (next pre-flight cleans). Item 225 6 data sidecar buckets owed wiring. Git-Bash mangles taskkill/schtasks args (path coercion) - use PowerShell tool for DS restart (taskkill /F /PID then schtasks /Run, NOT Stop-Process). Anomaly RC-CostHealthWatchdog (carry). Frozen-file grant NOT used.

---

# 2026-05-30 - item 227: DS V2 bounded-combat-simulator substrate (5-slice parallel headless-upgrade run) (HEAD 7353be0; pushed acaf2fe..7353be0; CI green run 26703611726; NO ENGINE bump - 1.63.0 stays; NO DS restart; all 5 modules ADDITIVE, not wired into live :8893 scorers)

Operator: "continue DS missing-by-design + implement missing designs; review lolmath changelog; expand DS in parallel; V2; mana real-usage-not-infinite; cross-interaction fight sims; full + frozen rights; do not solely trust current DS for V2 - start implementation + put-off items." Re-issued same prompt mid-dispatch (no in-flight slice) -> task re-assert, continued.

V2 = steady-state DPS calculator -> BOUNDED COMBAT SIMULATOR. Plan + contracts in NEW docs/DS_V2_PLAN.md. 6 parallel worktree agents on disjoint files, orchestrator-merged (5 commit-bearing + 1 read-only); 0 conflicts. DS 5077 -> 5191 (+114). Full DS suite green, ruff clean, CI green.

5 substrate modules (ALL additive, nothing wired into live scorers - do NOT auto-wire):
- mana_sim.py (545/19t): finite-mana bounded rotation; pool=stats.scaled mp + item mana, regen/5; OOM-gates burst per-cast .cost; manaless/energy ungated (bounded==unbounded). Wait-to-ready cooldown (not combo skip) so the gate binds. Lux L9 14/24 OOM -> +Tear 18 -> +Archangel's 21 monotonic.
- rune_procs.py (396/32t): net-new rune layer (RC had ZERO). 8 runes; ALL coeffs verified+corrected vs LIVE DDragon 16.11.1 (brief numbers stale).
- ability_hps.py v2 (+154/-21; 17+22t): passive-P + target-relative/missing-HP units. HONEST: zero P-form heal damage_blocks in snapshot (heals in stripped effects-text) = data ceiling, asserted not fabricated. v1 byte-identical.
- self_shred.py (401/21t): target_shred -> own-DPS uplift; AD-reduction shreds (Trundle/Tryndamere) correctly skipped.
- scenario_matrix.py (431/25t): cross-interaction sweep + 5 invariants + violation probe (not a no-op).
- lolmath changelog: 0 NOW / 0 FUTURE / 7 CLOSED - all already correct in RC or by-design.

DON'T-REDO: all 5 additive (no auto-wire); ability_hps P-heal = data ceiling (do NOT re-hunt); rune coeffs DDragon-verified (trust formula strings); mana_sim wait-to-ready intentional; lolmath nothing actionable.

NEXT (operator-gated, ENGINE bump each, the repeatable continue picks up): (1) wire ability_hps v2 -> LIVE ds.hps enchanter scorer (re-ranks builds + lower-bound -> validate; DEFERRED from blind overnight); (2) unified V2 fight-report compose 5 modules; (3) wire rune_procs into burst/combo; (4) expand rune+champ coverage + mana_sim as scenario_matrix metric. Item 225's 6 data sidecar buckets still owed wiring.

CARRY: 6 R1 agent worktrees harness-locked (live pids 4044/20624) - next pre-flight cleans. Anomaly RC-CostHealthWatchdog last_result=1 (pre-existing watchdog; flag for operator). Frozen-file grant NOT used.

---

# 2026-05-30 - item 226: DS scraper-review 3-slice fix (lolmath chat) - ability heal/shield scorer + modifier taxonomy + bounded mana valuation (commit 5a303c2; CI green run 26702508176; NO ENGINE bump - 1.63.0 stays; NO DS restart; additive)

Operator pasted a lolmath dev-chat (a peer maintainer/Redymix) about moonbeam's scraper + 6 perceived issues; asked "review DS for the contents noted in here and provide a fix if needed - commenting on findings."

**VERDICT (verified vs ground truth, NOT agent-relayed - drift scan: committed 16.11.1 == current scraper, 1709 blocks 0 mismatch):**
- #1 Caitlyn W null damage_type -> no damage = NOT A BUG (Cait W has 0 `damage` blocks; Meraki omits trap damage; RC correctly scores 0).
- #3 MIXED mis-assignment / "two `_abil_damage_type` w/ F811" = NOT A BUG (no such dup exists - agent hallucinated; `_mitigation_factor` routes MIXED 50/50, null->MAGIC, per-block honored).
- #3b Akali electrocute proc-count / passive double-count = CANNOT EXIST (RC has ZERO rune-proc layer; Akali P = 0 damage blocks).
- #2 + #6 + #7 = real deferred-by-design gaps -> FIXED this session.

**AskUserQuestion:** operator picked all 3 buildable (#6 + #2 + #7). 3 slices, all PURELY ADDITIVE (byte-identical when knobs unset) so NO ENGINE bump + NO DS :8893 restart (phase8 70/70 vs live 1.63.0 confirms).

**#6 NEW `agents/daemon_slayer/ability_hps.py`** (24 tests): champ-spell heal/shield was extracted (96 heal + 56 shield blocks) but never consumed. ROOT CAUSE found by probing: heal/shield numbers live ONLY in `raw_modifiers` (flat + % AP / % bonus AD / % max health), never the typed fields the damage `_evaluate_block` reads -> returns 0 for every heal/shield block. `compute_ability_hps` parses raw_modifiers directly: caster-side unit map + meta-attr denylist (`_META_HEAL_SHIELD_RE` skips cost-reductions/multipliers/HP-grants), mirrors ability_dps AP-amp chain, folds ARAM aramHealing/aramShielding per-side, measured cast rates. Verified vs raw data: Soraka W=130 heal, Janna E=80 shield, Sona W dual 60 heal + 65 shield.

**#2 NEW `agents/daemon_slayer/modifier_blocks.py`** (22 tests): the 180 modifier blocks ARE correctly dropped from DPS - they're heterogeneous (125 pve-only / 17 target-shred / 17 defensive-self / 15 self-amp / 6 other), NOT one clean multiplier. A blanket apply would multiply champ damage by minion numbers + double-count resist shred. `classify_modifier_kind` + `summarize_modifiers` make them queryable WITHOUT corrupting DPS; target_shred (Nasus E etc.) flagged as the one real-champ-DPS class for a future deliberate slice.

**#7 `rank.py` `rank_items`** (+12 tests): NEW optional `mana_value_per_point` param. DPS scorer values flat mana ~0 so Tear/Lost Chapter/Blackfire rank below burn/AP for mana casters. Adds `mana_value_per_point * mana_gained` to each candidate's `mana_adjusted_score`, sorts by it. `RankedItem` gains `mana_adjusted_score` + `mana_gained` (both default 0.0). None/0/negative = byte-identical; no effect under sort_by=efficiency or when fight_length engaged. Probed on Ziggs: Blackfire (mp+600) surfaces #5.

**Verified:** DS suite 5077 / RC 4091 (+1 skip +71 subtests) / phase8 70/70 green; ruff clean repo-wide. RankResult has NO `mana_value_per_point` field (knob surfaced via notes, mirrors fight_length).

**Don't-redo:** (a) Issues #1/#3/#3b are RC non-bugs - do NOT re-investigate. (b) NO ENGINE bump happened - 1.63.0 is current; all 3 slices additive. (c) `ability_hps.py` is v1 ACTIVE-only - passive-P heals (Aatrox/Vladimir/DrMundo) + target-relative units (Taric W % target max-HP) are OUT OF SCOPE v1, flagged lower-bound not silently zeroed. (d) NOTHING in the engine consumes ability_hps or modifier_blocks yet - they are data-driven substrate for a future enchanter-HPS scorer / coach surface / self-shred DPS slice (each its own engine slice + ENGINE bump when opened). (e) target_shred is the ONE modifier class with real unconditional champ-DPS impact RC does not model - future slice. (f) the 2 `.bak-units20260530-003054` files are pre-existing item-225 junk (NOT mine; left untracked).
