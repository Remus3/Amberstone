# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-02 - item 272: DS per-stack unbounded resist grant (ENGINE 1.99.0)

Operator "start the next DS schema lift and exhaust it then /done for /clear". Seeded the LAST cleanly headless-buildable resist-grant exclusion (per-stack unbounded). 2 commits `73bbb85` feat + docs (pushed). ENGINE 1.98.0 -> 1.99.0. DS :8893 restarted (taskkill pid 16868 + schtasks) -> 1.99.0/16.11.1/172/705, live-verified. RC NOT touched.

- NEW per-stack seam on `PassiveResistEntry`: `per_stack_armor`/`per_stack_mr` * `assumed_stacks` summed in `resist_grants` alongside the flat-add (264/267) + percent (268) halves; default 0.0 -> flat/percent/bounded entries unchanged; NO new EHP threading (compute_ehp already calls resist_grants). NEW `_ASSUMED_SOUL_COUNT=25.0` (item-249 assumed_stacks convention on the EHP seam; Phase D feeds the live soul count).
- SEEDED 1: Thresh P Damnation `per_stack_armor=1.0`, mr=0 (ARMOR ONLY - the +1 AP per soul is offensive), `assumed_stacks=25`, prob 1.0 permanent -> 25 bonus armor at the midpoint. Thresh's innate "armor does not grow per level" makes souls his ONLY armor scaling, so the grant is load-bearing.
- EXHAUSTIVE roster scan (per-stack + armor/MR co-occurrence): Thresh P is the SOLE per-stack-UNBOUNDED self-resist grant; every other per-stack resist is BOUNDED + already handled (Garen W cap30 at-cap, Graves E cap8 at-cap, Wukong P cap5 base+combat-omitted, Jax R active on-hit); 3 false positives (Corki/Kled MS/Ornn items).
- RESIST-grant lane now COMPLETE across all 6 source modes (flat 264 + rank-scaled-block 267 + percent 268 + unlabeled-block 270 + form-occupancy 271 + per-stack-unbounded 272). +19 tests `test_passive_resist_per_stack_item272.py`. DS 6142 -> 6161, 0 failed. ruff clean. Share 278 files --check clean (+ Share/CHANGELOG 1.94->1.99 condensed-range prepend). Live /ehp: Thresh L11 blended 2313.77 off / 2522.89 on, pr_armor 25.0 / pr_mr 0.0, armor 33.0 unchanged (+25 = ~76% of base); Caitlyn off==on byte-identical 2351.6756.
- Don't-redo: per_stack fields + assumed_stacks is the canonical home for an UNBOUNDED-accumulator resist (coefficient EXACT, only the count is the assumption; do NOT bake count into flat armor, do NOT route a BOUNDED per-stack through it); Thresh is ARMOR ONLY (no MR); Thresh is the SOLE per-stack-unbounded grant (do NOT re-pitch Corki/Kled/Ornn). The 2 remaining exclusions (Anivia P resurrection non-combat / Orianna E ball-attached ally-target) each need a DIFFERENT non-EHP seam - do NOT model as EHP-denominator addends. The clean headless effects-text survivability+resist lane is now EXHAUSTED across both EHP scorers + all 6 resist modes - remaining DS work is Phase D live flag-flips (for Thresh feed the live soul count not the 25 midpoint) + the 2 different-seam exclusions + Phase 11 vision-frame collapse + gamepc archival.

---

# 2026-06-02 - item 271: DS form-occupancy-gated resist grant (ENGINE 1.98.0)

Operator "start the next DS schema lift and exhaust it then /done for /clear". Seeded the LAST clean headless resist-grant exclusion class (form-gated). 1 commit `15b23e6` (pushed `0fec310..15b23e6`). ENGINE 1.97.0 -> 1.98.0. DS :8893 restarted (taskkill pid 4212 + schtasks) -> 1.98.0/16.11.1/172/705, live-verified. RC NOT touched.

- NO new schema field - reuses `conditional_probability` as a form-occupancy midpoint (NEW `_FORM_OCCUPANCY_PROB=0.5` constant, parallel to `_ACTIVE_RESIST_PROB`). A grant present only in ONE stance of a 2-form toggle; the other stance has ZERO, so unlike K'Sante All Out / Kayn R it cannot be seeded gate-independently.
- SEEDED 1: Jayce R Transform Mercury Hammer, armor==mr=`_step_per_level((5,15,25,35))` (4-tier even-quarters, item-247 helper), Hammer-stance only. +7.5% bonus-AD sub-term omitted (no bonus-AD ctx on EHP seam). Cannon-stance R (form 0) only shreds the TARGET, never a self-grant.
- EXHAUSTIVE roster scan: Jayce R Hammer is the SOLE form-gated self flat-resist grant (Kled forms are HP not resist; Elise/Nidalee/Gnar/Shyvana/Swain grant no flat resist). The 3 other exclusions RE-CONFIRMED: Anivia P (resurrection non-combat), Thresh P (per-stack-unbounded souls), Orianna E (ball-attached ally-target).
- RESIST-grant lane now COMPLETE across all 5 source modes (flat 264 + rank-scaled-block 267 + percent 268 + unlabeled-block 270 + form-occupancy 271). +24 tests `test_passive_resist_form_gated_item271.py`. DS 6118 -> 6142, 0 failed. Share 277 files --check clean. Live /ehp: Jayce L16 pr 17.5 (35*0.5), L11 12.5, armor 94.375 unchanged; Caitlyn off==on byte-identical.
- Don't-redo: do NOT add a new schema field for form-gating (conditional_probability covers it); 0.5 is operator-tunable (Phase D); the 3 remaining exclusions each need a DIFFERENT seam (non-combat-state gate / assumed-soul midpoint / ally-target seam). The clean headless effects-text survivability+resist lane is EXHAUSTED across both EHP scorers + all 5 resist modes - remaining DS work is Phase D live flag-flips + the 3 different-seam exclusions + Phase 11 vision-frame collapse + gamepc archival.

---

# 2026-06-02 - item 270: DS unlabeled-multi-stat-block resist grants (ENGINE 1.97.0)

Operator "start the next DS schema lift and exhaust it then /done for /clear". Seeded the LAST resist-grant exclusion class (Singed R / Braum W / Leona W / Jax R). 1 commit `fbb2934` (pushed `ff7ffa6..fbb2934`), CI green run 26831626137. ENGINE 1.96.0 -> 1.97.0. DS :8893 restarted (taskkill pid 15424 + schtasks) -> live-verified. RC NOT touched.

- NO new schema field - hand-attribution + the existing item-267 `rank_scaled` flat-add seam. The item-264 "unlabeled / not confidently attributed" framing was OVER-cautious: series[0] varies by rank = flat base; series[1] rank-constant = a percent coefficient (omitted per its base). Singed R is one shared series [25,60,95]=AP=armor=MR.
- SEEDED 4 rank_scaled flat-base active-amortized 0.3: Singed R (25/60/95), Braum W (20-40), Leona W (20-50), Jax R (armor 25/50/75 + MR 15/30/45). Percent coefficients omitted: Braum 36%-of-ALLY (cross-champ), Leona 20% (uncertain), Jax 40%/24%-of-bonus-AD (no seam).
- Exhaustive re-scan: the only other armor/MR blocks are target-SHRED (Evelynn/JarvanIV/Renekton/Rengar/Rumble/Yorick = offensive, NOT self-resist).
- +15t `test_passive_resist_unlabeled_block_item270.py`; item-264 exclusion-list dropped the 4. DS 6103 -> 6118; 51 test-pin syncs; Share 276 files --check clean; living docs 1.97.0/6118.
- LIVE /ehp: Singed L16 28.5; Jax L16 armor 22.5 / mr 13.5; Braum L11 9.0; Leona L16 15.0; Caitlyn off==on byte-identical.

Don't-redo: (a) the resist-grant lane is now COMPLETE (flat 264 + rank-block 267 + percent 268 + unlabeled-block 270) - do NOT re-pitch Singed/Braum/Leona/Jax. (b) the 4 remaining resist exclusions each need a DIFFERENT seam: Jayce R form-state midpoint / Anivia P resurrection / Thresh P per-stack / Orianna E ball-attached. (c) percent coefficients deliberately omitted (no ally / bonus-AD seam) - do NOT force-seed. (d) default apply_passive_resist=False byte-identical; flag-on CAN re-rank (non-linear _armor_factor) - Phase D live validation before default-on.
NEXT (operator-gated): the entire headless effects-text survivability + resist-grant lane is EXHAUSTED across both EHP scorers; remaining DS = Phase D live flag-flips + the 4 different-seam resist exclusions + the deferred Phase 11 vision-frame collapse + gamepc archival.
