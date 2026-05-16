# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s233 wrap — 2026-05-16 (operator decision: DS conditional arc CLOSED; next = s220 aggregator G reframe)

**Operator instruction:** asked what direction the DS Part-2 decision needed, chose to close the arc, then "plan what is next then /done".

## Decision (recorded in ROADMAP §High-priority s232 line + CLAUDE.md item 84)

- **DS conditional Part-2 — SHELVED PERMANENTLY.** s229 finding confirmed: Part-1 `"default"` is the correct strategic model for the only DS surface (item-build ranking); live per-tick target-state resolution would only be valid as a *separate live-advisory product surface* = out of scope / not wanted. **Do NOT re-pitch Part-2.**
- **DrMundo E `caster_low_hp` vocab — DECLINED.** Single instance, fails the s227/s229 5+-uses bar, moot with Part-2 shelved. No caster-state vocab family will be added.
- The 10 shipped conditionals (s228–s231) stay as latent correctness scaffolding, guarded by the s232 saturation test. **No further DS conditional-engine work.**

## Don't-redo / blockers

- The entire DS conditional vein (autonomous pure-data AND Part-2) is **closed by operator decision**. A future "continue ds" must NOT reopen it — zero remaining DS-engine ROI here.
- Docs-only session: no code/engine change, ENGINE stays **1.3.0**, no DS restart, no test delta (suite still 2255).

## NEXT

**s220 Post Game Review aggregator-G-style reframe** — the big non-engine UI item, already a 🟡 in ROADMAP with full scope (clickable match rows → persistent header + 10-player score strip → AI Analysis/Graph/Build tabs; 0–100 color-banded score; MVP purple card; carried polish: Sustain rename, hero section-1, aggregator G roster row, color-coding, #9 augments). **NOT blocked on the Riot key** (diagnosed s220 — only event-mode/KIWI queue-2400 403s; standard-queue last-matches populate fine; do NOT redo the key investigation). Per-player runes/ranks need an `_enrich_from_lcu` extension.

---

# s232 wrap — 2026-05-16 (DS Phase 5.9.32: conditional pure-data vein SATURATION PROOF — autonomous loop concluded)

**Operator instruction:** "Continue ds". s231's wrap flagged the vein approaching exhaustion; rather than churn low-value no-op conversions (the explicit s223-227 "don't churn low-value registry work" lesson + the no-padding principle), I ran a definitive saturation scan, surfaced the finding via `AskUserQuestion`, and **the operator chose "Accept loop complete."**

## What happened — rigorous exhaustion proof, then a decision

s231's constant-k pair scanner had a structural blind spot (it rejects the Kindred-E archetype, where the amp is a different-ratio bump concentrated in an HP coefficient). Built `tools/ds_execute_prefilter.py` (kept, durable per-patch) to catch exactly that. Result: **zero unaddressed clean execute candidates.**
- `target_full_hp` (execute): Evelynn R + KogMaw R (s231) + Kindred E (s228) were the clean ones. The only other true `target_missing_hp_pct` pairs are **already engine-default-correct** (Jinx R — block 0 holds the 25-35% max missing-HP coeff, confirms s217; verified live by inspecting blocks) or **deliberate R-entangled skips** (Varus W blocks 5/6 — s225 chose block 2 to keep W R-independent). Veigar R stays the deferred stable-int fixture.
- `target_no_setup` (self-debuff amp): the one genuine correctness fix was Fiddlesticks Q (s230). Everything else the pair scanner finds is already correctly plain-int mapped — conditional conversion is a pure Part-1 no-op, zero ranking value until a Part-2 live-advisory surface consumes the downgrade (deliberately not built; s229 reframed per-tick B-2 as a mis-feature for item ranking).
- All other discrete-pair hits are `target_max_hp_pct` — NOT the `target_full_hp` execute semantic (max-HP scaling is a flat fraction of the health bar, not HP-gated) and already mapped-correctly.

This is the s227 situation for the conditional vein: the autonomous pure-data DS work is mined out; the high-ROI remaining DS work is Part-2 (live target-state plumbing) — architectural, wants sign-off, NOT autonomous.

## Shipped (committed) — NO registry/engine change, ENGINE stays 1.3.0

- `tools/ds_execute_prefilter.py` (new, kept) + `tools/ds_cond_pair_prefilter.py` (s231, kept) — the durable per-patch saturation tools.
- New `test_conditional_block_index_s232_saturation.py` (8 tests) — the s223-style **machine-checked saturation guard**: `MissingHpExecuteVeinSaturationGuard.test_no_unaccounted_clean_execute_pair` enumerates EVERY same-shape monotone-execute-coeff block pair across all 171 champs and asserts each (champ,key) is accounted-for (already-conditional / engine-default-block-0-correct / documented-skip). A future Meraki re-extract that introduces a genuinely-new clean execute candidate **trips this test** = the signal to revisit. Plus vocab-stays-2, all-10-shipped-conditionals-intact, registry-still-125, and an **ENGINE-UNCHANGED** pin (1.3.0 — there is nothing behavioral to version; do NOT bump for a docs/tooling/guard commit).
- **No ENGINE bump, no DS restart, no stale-pin migrations** (nothing behavioral changed). DS suite 2247→**2255** (+8 guard tests); ruff+py_compile clean.

## Don't-redo / blockers

- **The autonomous pure-data conditional-seed-expansion vein is CONCLUDED** (operator decision). Do NOT re-run `ds_cond_pair_prefilter.py` / `ds_execute_prefilter.py` expecting yield, and do NOT ship no-op plain-int→conditional conversions to look busy — they add zero ranking value (Part-1 always resolves to default == the prior int) until Part-2 exists. The saturation guard is the tripwire if a patch re-extract genuinely changes this.
- **Don't bump ENGINE_VERSION for pure docs/tooling/guard commits.** s232 deliberately stays 1.3.0; the s232 test pins it unchanged. ENGINE tracks engine/registry *behavior*.
- The 10 shipped conditionals (s228-s231) are all **Part-1 no-ops by design** — they resolve to `"default"` == their prior int/list. Their value is latent until Part-2. Don't "fix" the no-op.

## NEXT (operator decision required — not autonomous)

The high-ROI remaining DS investment is **Part-2: live target-state plumbing** (thread liveclient target HP%/CC into the ranking call so the 10 shipped conditional downgrade branches actually fire). It is architectural and wants explicit sign-off — and note s229's open question stands: the literal per-tick "B-2" was reframed as a *mis-feature for item-ranking* (would flicker build recs), so Part-2 would need to be a **separate live-advisory product surface**, not item-build wiring. That scoping decision is the real blocker. Other non-DS directions also pending: the s220 aggregator G Post-Game-Review UI reframe (the big non-engine item, flagged ~12 sessions). DrMundo E still needs a `caster_low_hp` vocab decision if caster-state conditionals are ever wanted. Recommend the next "continue" be an explicit operator choice among {Part-2 scoping, s220 UI reframe, other} rather than more autonomous DS pure-data (that vein is provably empty).

---

# s231 wrap — 2026-05-16 (DS Phase 5.9.31: conditional seed-expansion — EXECUTE family: Evelynn R + KogMaw R)

**Operator instruction:** "Continue ds" (self-continuing loop). Continued the s230 NEXT bucket: more debuff-state-family conditional amps. NO vocab change (s227 "don't over-build" — both entries reuse the existing `target_full_hp` term, extending the s228 Kindred E execute pattern).

## What happened — built a reusable pre-filter, found the execute vein

Built `tools/ds_cond_pair_prefilter.py` (kept, reusable per-patch) — scans all 171 champions for the discrete amped/un-amped pair signature (same-shape damage blocks where B_hi = constant k×B_lo). Found 280 hits but most are channel/multi-hit totals already correctly mapped as plain ints (the s193/s198 pattern, NOT target-state conditionals). The genuine untapped vein: **the EXECUTE family** (`target_full_hp` vocab, the Kindred-E s228 shape) — champions whose R deals a clean discrete multiple more to sub-threshold-HP targets, currently mapped as a plain int to the execute block. Verified each by hand (rigor bar).

## Shipped (committed)

- **Evelynn R "Last Caress"** int `1` → `{default:1, target_full_hp:0}` — Meraki block 1 = EXACTLY **2.4×** block 0 every rank (base 125→300, ap 75→180); the bonus-vs-sub-30%-max-HP execute. TWO discrete Meraki blocks (clean amped/un-amped pair), NOT a continuous in-block missing-HP coefficient — the precise distinction that rejected Bel'Veth R. `default`=1 (the execute, operator-commits canonical, s191 model — same as Kindred E s228); `target_full_hp`=0 (un-amped downgrade when target above threshold, Part-2's signal). Evelynn's s228 sibling Q `{default:5,target_no_setup:0}` preserved through the dict-merge. Live A/B :8893 /burst lvl11 80/30/2000: registry **1220.34** == forced{R:1} == cond-dict (provable Part-1 no-op); forced{R:0} **951.11** (load-bearing downgrade).
- **KogMaw R "Living Artillery"** int `1` → `{default:1, target_full_hp:0}` — Meraki block 1 = EXACTLY **2.0×** block 0 (base/bonus_ad/ap all 2×); the double-damage-vs-low-HP execute. Live A/B: registry **640.68** == forced{R:1} == cond-dict; forced{R:0} **532.99**.
- Both provable Part-1 no-op (default == prior int 1, byte-identical; default == s204 Evelynn / s196 KogMaw). Registry stays **125 champions** (both converted in-place). `_meta` appended via surgical str.replace. New `test_conditional_block_index_s231.py` (15 tests) + 11 ENGINE pin bumps + 9 stale-pin migrations (Evelynn/KogMaw R shape pins in test_block_index_overrides ×5, s228 ×2, s229 ×1, s226 form/block-compose ×1). **Caught + migrated a latent s230 stale pin:** `ServerRouteSourceTests.test_ability_dps_champion_source` asserted the pre-s230 Cassi E int shape — it's a *live-server* test and s230 only re-ran phase8_smoke post-restart (not the full suite), so it had been silently stale since s230; now asserts the s230 conditional shape. ENGINE **1.2.0→1.3.0**. DS suite 2232→**2247**; wider RC **1107**; ruff+py_compile clean; DS restarted (taskkill 3724 → pythonw relaunch, not supervisor-watched) → `/health` **1.3.0**.

## Don't-redo / blockers

- **Veigar R stays the deferred non-converted exemplar.** It IS a clean 2.0× execute (verified: block0 base[175,250,325]ap[65,70,75] → block1 exactly 2.0×) but it's the canonical stable-int test fixture (s229 _meta: "pick non-fixture executes" — s231 did exactly that with Evelynn/KogMaw). Converting Veigar R cascades fixture repoints across test_sum_of_blocks + test_block_index_overrides GetBlockIndexFor/ResolveBlockIndex/known_champion_overrides — only do it as a deliberate, independently-scoped fixture migration, NOT as part of a pure-data batch.
- **Akali R/R2 NOT a conditional candidate to touch.** Its execute lives in the s192 token-variant special case ({R:0, R2:2}) carefully scoped to avoid double-counting R1 in the combo registry — layering a conditional on top is high-risk. Leave it.
- **post-restart full-suite check matters.** The s230→s231 latent stale pin (ServerRouteSourceTests) proves: live-server tests must be re-run against the *restarted* server, not just phase8_smoke. s231 re-verified live A/B post-restart and the migrated pin will pass against 1.3.0 (Cassi E shape unchanged s230→s231).
- Conversions are intentionally zero-numeric-change (Part-1 resolves to `"default"` == the prior int); don't "fix" the no-op.

## NEXT (self-continuing loop)

The execute (`target_full_hp`) vein has Evelynn R + KogMaw R shipped; remaining clean executes are scarce (Veigar R deferred-fixture; most other "2× vs low HP" hits are already plain-int mapped-correctly and converting adds no value without a real downgrade consumer). Next candidates need fresh Meraki verification each (the s229/s230/s231 lesson: ROADMAP/_meta recollection mis-names mechanics ~half the time — `tools/ds_cond_pair_prefilter.py` + `tools/ds_cond_inspect.py` are the durable rigor tools). Remaining `target_no_setup` debuff-amp candidates are mostly already-correctly-mapped plain ints; the conditional-conversion ROI is now low (each adds value only if a future Part-2 live-advisory surface consumes the downgrade). Consider flagging to the operator that the autonomous conditional-seed-expansion vein is approaching exhaustion (like the s223-227 pure-data sweep did) — the high-ROI remaining DS work may be Part-2 (live target-state plumbing) which is architectural and wants sign-off. DrMundo E still blocked on a `caster_low_hp` vocab decision. s220 aggregator G Post-Game-Review reframe remains the big pending UI item.
