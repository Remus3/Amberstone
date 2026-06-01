# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-01 - item 248: DS GAP-2 bilinear AP-on-HP passive schema lift + 4 SEEDED passives, default-OFF byte-identical (ENGINE 1.79.0 -> 1.80.0; DS restarted 1.80.0; RC not restarted - DS engine + tests + Share + docs only)

Operator "start the next DS schema lift and exhaust it". The next staged schema need from item 247 = the bilinear AP-on-HP evaluator term Gwen P needed.

FINDING (verified vs live 16.11.1 effects_descriptions BEFORE building): the AP-scaled %-of-HP passive form "X% (+ Y% per 100 AP) of target HP" is a PRODUCT of two ctx stats (ctx[ap] * ctx[target_hp]) that NO single linear _SCALING_TARGETS field expresses (each field is one pct * one ctx attr; base-X%-only under-models ~2x at 200 AP).

SCHEMA LIFT: NEW DamageBlock.bilinear_terms (flat tuple (factor, ctx_attr_a, ctx_attr_b) summed as factor * ctx[a] * ctx[b] in ability_dps._evaluate_block AFTER the per-rank linear terms; default () = every existing block BYTE-IDENTICAL) + has_damage_scaling True for a bilinear-only block + _passive_damage_overrides._per_100(pct, per_attr, of_attr) authoring helper (factor = pct/10000: /100 pct->fraction, /100 "per 100" denom).

SEEDED (4, default-OFF, exact from verbatim 16.11.1): Gwen P A Thousand Cuts (1% + 0.55%/100AP target max HP, on-hit - the item-247 staged canonical case) / Aurora P Spirit Abjuration (2.5% + 2%/100AP max HP, 3rd-stack consume) / Lillia P Dream-Laden Bough (5% + 1.25%/100AP max HP, dot) / Renata P Leverage (1%:2% level + 2%/100AP max HP, first-hit per_fight). All 4 on target MAX HP (non-zero at default full-HP ctx, NOT inert).

EXHAUSTED (scanned all 171 champs' no_damage forms for "per 100 AP" + "health"): 9 bilinear-on-HP candidates, 4 shipped + 5 STAYED STAGED - Kai'Sa P (dominant per-application term is a Plasma-stack-count ramp; 5th-stack-consume bilinear sub-term partial + conditional) / Brand P + Ekko W (bilinear term CONDITIONAL - ring detonation / sub-30%-HP gate; Ekko's is missing-HP-scaled = ~0 at full-HP ctx) / Karma W f1 + Viego P (bilinear term is a HEAL, not damage).

+22 tests test_passive_damage_bilinear_item248.py + item-247 StagedAbsent split (Gwen now seeded, Kai'Sa stays staged). ENGINE 1.79.0 -> 1.80.0 + 35 test-pin syncs + CHANGELOG prepend + Share re-sync (--check clean, 249 files engine 1.80.0) + DS restart (PowerShell taskkill + schtasks RC-DaemonSlayer). DS 5715 -> 5738 (0 failed); ruff clean; added-diff 0 non-ASCII (abilities.py/ability_dps.py/CHANGELOG carry PRE-EXISTING non-ASCII = operator-gated retro-sweep, diff-verified clean).

Don't-redo: (a) bilinear_terms is the canonical home for ANY ctx[a]*ctx[b] product damage term; factor is FLAT (level-independent) by Riot's "% per 100 AP" convention - do NOT make it per-rank without a real level-scaled bilinear case. (b) _per_100 factor = pct/10000 (NOT pct/100) - "per 100 AP" denominator is the second /100. (c) the 4 SEEDED are EXACT for the modeled terms; vs-minion/monster caps + heal sub-clauses are uncapped/utility (Aatrox/Zed precedent) - do NOT model. (d) the 5 STAGED skips are NOT bilinear-coverable: Kai'Sa needs a Plasma-stack-count assumption; Brand/Ekko W need a Phase-D conditional/low-HP assumption; Karma W f1 + Viego P are HEALS. (e) Ekko W is missing-HP-scaled -> ~0 at default full-HP ctx (misleading inert ship). (f) DS restart PowerShell taskkill + schtasks (NEVER Stop-Process).

NEXT (Phase D / live / operator-gated, unchanged from item 247): flag-flips (apply_passive_damage now covers 10 P + 6 C3 exotic + 4 bilinear = 20 passives, per-passive AFTER on_hit->AA cadence wire / apply_ability_amps / build_tenacity+cc_blended / mode_modifiers / gate_ammo / aoe_targets_hit); author the 5 C2 AA-empower values + cadence live; Kai'Sa P per-Plasma-stack ramp (own slice, needs stack-count decision); AurelionSol W cross-spell seam; item-240 UI part-3 + #7/#8 + item-243 NEXT(2) ranked-SR UI watch.

---

# 2026-06-01 (/headless-upgrade) - item 247: DS gap-plan Phase C3 (6/8 exotic passives) + C2 (AA-empower seam), both default-OFF byte-identical (commits 04dbcde C3 ENGINE 1.78.0 / 092a549 C2 1.79.0; pushed 5d8cd59..092a549; CI green; DS restarted 1.79.0; RC pid 13544 not restarted)

Headless run off item-246 NEXT. Pre-flight clean: DS 1.77.0 in sync, CI 6/6 green, 0 PRs, 2 merged worktrees + 7 scratch cleaned.

C3 (04dbcde, ENGINE 1.77.0 -> 1.78.0): authored 6 of 8 gap-plan exotic passives in _passive_damage_overrides.py from VERBATIM 16.11.1 effects_descriptions, default-OFF (injects only under apply_passive_damage=True; 6 new P forms stay no_damage flag OFF). Additive schema (no core DamageBlock change): _step_per_level (3-tier even-thirds level step for slash-notation) + PassiveDamageEntry scaling fields widen to float|tuple (per-level coefficient rides target_max_hp_pct/total_ad_pct) + to_damage_block coerces + wires target_current_hp_pct.
SEEDED: Aatrox P (4%:8% target max HP lerp) / JarvanIV P (8% target current HP flat; min/cap inert in champ band) / Zed P (6/8/10% target max HP step; below-50% gate NOT modeled = magnitude gate-independent) / Caitlyn P (60/90/120% AD step; +crit-chance AD multiplier OMITTED = AA-crit seam) / Ekko P (30:140 + 90% AP; every-3rd-stack cadence metadata) / Gangplank P (50:250 + 100% bonus AD TRUE dot 2.5s; +crit term OMITTED).
STAGED own-slice (NOT shipped guessed): Gwen P (bilinear AP*HP product) + Kai'Sa P (per-Plasma-stack). +31 tests test_passive_damage_exotic_item247.py.

C2 (092a549, ENGINE 1.78.0 -> 1.79.0): the 5 base="aa" AmpEntry champs (Caitlyn W / Fiora E / Jayce W f1 / Sivir W / Nidalee Q), registered item 239 but NO consumer (inert in ability_dps), now wired into the AA scorer. compute_dps gains apply_ability_amps (default False = byte-identical); when True NEW _aa_amp_multiplier scales ONLY base-AA (item procs unamped) via compute_dps -> _phase_weighted_dps -> _rotation_attack_dps (aa_empower_amp) + per-hit displays; route-reachable via /dps. rank_at_level imported function-level (dps<->ability_dps cycle break). FORWARD-MARKER: placeholder (0.0,) + conditional-no-condition (prob 0) -> inert today; Phase D authors the value + flips always_on/a condition per champ. +8 tests test_aa_empower_seam_item247.py.

Each: ENGINE bump + 35 test-pin syncs + CHANGELOG prepend + Share re-sync (--check clean) + DS restart (PowerShell taskkill + schtasks RC-DaemonSlayer). DS 5689 -> 5707 -> 5715, 0 failed; phase8 70/70; ruff clean. Cost/latency 7-lever sweep CLEAN no-commit (top /api/adaptation 0.116/s; 17 RC-* tasks 14+3; 34==34 CSS parity).

Don't-redo: (a) OMITTED crit terms (Caitlyn/Gangplank) belong in an AA-crit/crit-context seam, not a passive block - do NOT bolt a crit field onto DamageBlock here. (b) Zed below-50% gate intentionally not modeled (% of MAX HP = gate-independent); 3-tier breakpoints (Zed/Caitlyn) are EVEN-THIRDS estimates - verify exact 16.11.1 boundaries in Phase D, the live-wiki breakpoints are the DRIFTED current-patch values. (c) Gwen+Kaisa staged on purpose. (d) C2 seam is a forward-marker even flipped on (placeholders + prob 0); Phase D must set always_on or a condition AND a value. The amp scales base-AA only - do NOT fold into damage_amp. (e) dps.py has pre-existing non-ASCII (operator-gated); the C2 ASCII test scopes to the amp module + test file (item-247 additions added 0 non-ASCII, diff-verified).

NEXT (Phase D / live / operator-gated): flag-flips per champ/mode/passive (apply_ability_amps / apply_passive_damage after D1 on_hit->AA cadence / build_tenacity+cc_blended / mode_modifiers / gate_ammo / aoe_targets_hit); author the 5 C2 AA-empower values + cadence live; finish Gwen+Kaisa exotics; AurelionSol W cross-spell seam; item-240 UI part-3 + #7/#8 + item-243 NEXT(2) ranked-SR UI watch.

---

# 2026-06-01 - item 246: DS gap-plan Phase C1 - staged-amp block-index routing Hwei Q f2 + Sion Q resolved-pre-seam (commit 24ea243; pushed 83dcc92..24ea243; ENGINE 1.76.0 -> 1.77.0; DS restarted 1.77.0; RC not restarted - DS engine + tests + Share + docs only; default-OFF byte-identical)

Operator: "start next item ... commit + push and /done and /clear then start /headless-upgrade". Next item = item-245 NEXT C1 from docs/DS_GAP_COMPLETION_PLAN.md.

FINDING (verified vs live champion_abilities.json BEFORE building): the 2 _STAGED_AMP_CANDIDATES Sion Q + Hwei Q f2 each carry a "Maximum ..." damage block that ALREADY holds the charged/isolated ceiling -> an amp would DOUBLE-COUNT; grounded fix = block-index ROUTING (never an amp).
(a) Sion Q ALREADY resolved BEFORE this seam: champion_block_index.json {Q:2} (s191 routing) selects "Maximum Physical Damage" by DEFAULT (char-probe: Sion Q raw 577.904 itemless L9 = Maximum block; flag on/off byte-identical). STAGED entry REMOVED; no gated route needed.
(b) Hwei Q f2 Severing Bolt now wired via NEW _STAGED_AMP_BLOCK_ROUTES = {("Hwei","Q",2): 1} + _staged_amp_block_route_for() in _ability_amp_overrides.py; compute_ability_dps consults it ONLY when apply_ability_amps=True (precedence over block_index_overrides for that champ/key/form), routing to damage-block 1 "Maximum Damage". NO separate Gap-2 missing-HP coeff needed - Meraki PRE-BAKES "Maximum Damage" flat == block0 * "Maximum Damage Increase" % (verified rank1 120=60*2.0, rank5 560=160*3.5), so the routed block IS the ceiling. STAGED entry REMOVED.
AurelionSol W stays STAGED (cross-spell seam, DEFERRED to own session per plan).

CRITICAL: _select_blocks indexes DAMAGE-only filtered blocks, NOT the raw array. Hwei Q f2 raw [damage, modifier, damage] -> damage-index 0="Magic Damage"(160), 1="Maximum Damage"(560); route value = 1 (not raw-array 2).

+10 tests test_staged_amp_block_route_item246.py. ENGINE 1.76.0 -> 1.77.0 + 36 test-pin syncs (35 files). DS suite 5679 -> 5689 (+10, 0 failed). ruff clean. Share re-synced 246 files (engine 1.77.0, --check clean; gist auto-pushed 1.77.0/255 files). Living docs synced (DAEMON_SLAYER/ARCHITECTURE/BRIEF/CLAUDE).
LIVE :8893 proof (DS restarted taskkill pid 16428 + schtasks -> /health 1.77.0/16.11.1/172/705): POST /ability-dps Hwei form_index={Q:2} apply_ability_amps=false -> Q raw 160.0; true -> 560.0.

Don't-redo: (a) Sion Q DONE via default block_index {Q:2} - do NOT add a gated route/amp (double-count/re-rank). (b) _STAGED_AMP_BLOCK_ROUTES values are DAMAGE-block indices (post attribute_kind=="damage" filter); Hwei Q f2 = 1, not raw-array 2. (c) route GATED on apply_ability_amps (default False) = byte-identical; do NOT flip default-on without LIVE validation (Phase D). (d) no Gap-2 coeff needed (block pre-bakes the ceiling). (e) DS restart PowerShell taskkill /F /PID + schtasks RC-DaemonSlayer (NEVER Stop-Process; DS not supervisor-watched).

NEXT (gap-plan headless spine; each = own ENGINE bump + DS restart, default-OFF byte-identical): C2 AA-empower seam in compute_dps (5 base="aa" entries Caitlyn W / Fiora E / Jayce W f1 / Sivir W / Nidalee Q, inert in ability_dps) / C3 author 8 exotic passives default-OFF in _passive_damage_overrides.py (Aatrox P / JarvanIV P / Zed P / Gwen P / Caitlyn P Headshot / Kaisa P / Ekko P / Gangplank P). Then Phase D (live flag-flips) + Phase E (Share re-sync) + item-240 UI part-3 + #7/#8 sign-off + item-243 NEXT(2) ranked-SR UI watch (live). AurelionSol W cross-spell seam DEFERRED (own session).
