# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated AH-slice `2026-07-19a`; newest 3 = RM-39 L2 widen `2026-07-19d` + RM-39 L1 build `2026-07-19c` + RM-39 adjudication `2026-07-19b`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-19d (RM-39/RM-43 L2 - TRUE credited, MIXED held, and the L1 guard rationale RETRACTED; ENGINE 1.223.0)

**The widen is the small half. The finding is that L1's stated guard was never
the guard.** L1's docstring claimed a PHYSICAL-only damage-type filter is what
stops an unfiltered ability term promoting Liandry's Torment to #1 for Aatrox.
False, twice over. Aatrox has ZERO nonzero non-PHYSICAL rows (Q 16.2499 /
W 2.6193 PHYSICAL, E and R 0.0), so PHYSICAL / +TRUE / +MIXED / unfiltered all
return the IDENTICAL number for him - the cited ablation cannot distinguish
them. What actually stops it is that the helper sums `per_spell`:
`item_proc_dps` (`ability_dps.py:1376-1381`) folds item burn into
`total_ability_dps` and appears in NO per_spell row. Measured residue for
Aatrox: 0.0000 empty, exactly 31.2500 with Liandry's. **That protection had no
test on it** - a refactor to `return result.total_ability_dps` would have
silently restored the bug with no filter change visible in the diff. Now pinned
by `test_ad_axis_term_is_per_spell_sum_not_total_ability_dps`. That pin is worth
more than the widen.

**L2 shipped:** `_AD_AXIS_CREDITED_DAMAGE_TYPES = frozenset({"PHYSICAL","TRUE"})`,
still DEFAULT-OFF. Two executable lines. TRUE credited on measurement not
argument - `_mitigation_factor` returns flat 1.0 for TRUE
(`ability_dps.py:372-373`) and all 5 in-cohort TRUE rows measured dAP 0.0000 /
dVoid 0.0000 (Olaf E, Vayne W, Darius R, MasterYi E, Garen R). **MIXED HELD** -
Yone only, and it does import magic pen (Void Staff 129 -> 111); honest fix is a
50 pct credit mirroring `ability_dps.py:377`, a separate design. **MAGIC
excluded permanently** - crediting it climbs Udyr's Rabadon's 55 places.

**THE AXIS SPLIT IS WHAT MAKES TRUE SAFE, NOT THE DAMAGE TYPE.** Roster-wide 2
of 7 TRUE rows DO scale with AP - Belveth R (dAP +1.2153), Chogath R (+0.6076) -
and are out of reach only because `_damage_axis` routes them "ap". Do not widen
assuming TRUE is AP-inert roster-wide.

**Golden diff:** flag OFF 0 of 92 changed; flag ON exactly 5 of 92, precisely
the TRUE set, zero top-1 changes. 6 HZ tables differ only in stamp fields.

**Reset overlap (L2 part 2): UNRESOLVED-BY-DATA, no code shipped.** `basic` is
NOT a reset marker - it is a flat swing count present on zero-reset champs
(Jinx 1, Ashe 3). Three population tests lean EXCLUDES but Nasus is authored
BOTH ways in the same file (`early[0]` basic:0 vs `mid[2]` basic:1, identical
1s single-Q sheen:1 rotations). Exposure narrowed 9 champs -> **2 spells**:
Vi E 6.19 pct, Renekton W 2.35 pct. Nasus Q structurally impossible (no AD
ratio); Shyvana Q disjoint (models the second strike). A proposed guard was
REJECTED - it string-matches `effects_descriptions` prose to correct an
unproven ~6 pct error on one champion on a default-off path.

**NEW: RM-98 filed, and it GATES default-ON.** The two summed terms are on
different time bases - the ON path adds a GAME-AVERAGE ability rate
(`spell_casts / game_duration_s` over 2851 matches, so laning + recalls + death
timers included) to a COMBAT-WINDOW auto rate. Renekton W reads 0.0184/s vs a
rotation-modelled 0.5/s: **27x**. Systematically under-prices the ability term.
SIZED, NOT ADJUDICATED. Do not flip default-ON until this is settled.

**Process, two of a kind:** I shipped a false green twice and caught both. The
DS restart ran through Git Bash, which mangled `schtasks /End` into
`C:/Program Files/Git/End` and did nothing, while the health poll in the same
command reported `up after 0s` at the OLD version. The golden diff printed
`changed 0 of 92` when every champion had thrown `TypeError`
(`HybridRankResult` is a dataclass, not a dict). **Both look exactly like
success.** The probe now raises on an empty ranked list. Use PowerShell for
schtasks. Step 4b rot recurred for the THIRD consecutive bump - `--check` was
green while `Share/CHANGELOG.md` and the `Share/README.md` release list were
both stale.

**Do NOT redo:** the RM-39/RM-43 haste adjudication (final). The Zeri
double-count (REFUTED, AST-locked). The L1 build. The reset-overlap
investigation - it is UNRESOLVED and further data cannot settle it; it needs the
lolmath authoring convention or replay-derived counts.

---

# 2026-07-19c (RM-39/RM-43 L1 BUILT - AD-axis ability term shipped DEFAULT-OFF, ENGINE 1.222.0; commit `2aaba1d2`)

**Built what 2026-07-19b adjudicated. Phase 1 was NOT re-litigated.**
`hybrid._physical_ability_damage` sums `per_spell` rows whose `damage_type`
normalizes to PHYSICAL; all three gate sites became `if ap / elif flag / else`
so the OFF branch is the pre-seam line VERBATIM. Flag
`apply_ad_axis_ability_damage`, route-surfaced on `/rank-bruiser`
(`server.py:865`, threaded `:902`) - without that surface the ON path is
unreachable over HTTP and the mandatory golden diff cannot be measured at all.

**Byte-identity at default proven TWICE:** 184/184 cohort rankings unchanged vs
a pre-change 1.221.0 baseline, AND the 6 regenerated build-order tables differ
only in `engine_version` + `generated_at`. The second was free and is stronger -
it covers the live consumer. **Guard verified live:** Liandry's for Aatrox
#16 -> **#20** squishy (falls, does not rise to #1). 79 of 92 reorder ON; the 13
zero-credit champions are byte-identical and are EXACTLY the unchanged set.

**DO NOT re-raise the Zeri double-count. It is REFUTED.** Her +217.7% lift plus
"her Q replaces her auto" made both the measuring agent and me conclude a
double-count, and I reported it as confirmed before reading the code. Wrong.
`_rotation_attack_dps` (`dps.py:508-562`) reads only `duration`/`basic`/
`basicTime`/`numberOfTargets`; `dps.py` reads q/w/e/r/p cast counts **zero times
anywhere** (grep + AST). It is a DENOMINATOR artifact - Zeri's `weighted_dps` is
9.04 vs Jhin 28.58, so a mid-pack ability term reads as a huge percentage.
`AutoAttackDisjointnessTests` now locks it via AST. **A big percentage lift off
an unknown base is not evidence of an inflated numerator.**

**NEXT (RM-39 L2), both now backed by measured magnitudes:**
1. Widen the guard? **TRUE/MIXED is the real excluded magnitude, not untyped** -
   Olaf E Reckless Swing 17.1 DPS is the largest excluded row in the cohort,
   bigger than all untyped undercount combined (which is ~1.0 DPS total, one
   real case: Pantheon R). Yone W/R are MIXED and half-physical.
2. Resolve the reset-champion overlap - 9 champions where `basic >= 1` AND a
   reset cast share a window; `maxOverlap` bound computed per champion (worst
   Zeri 66.9%, Renekton 8.3%). Needs the lolmath auto-reset authoring convention
   or a replay-derived basic-vs-reset count.
Default-ON flip stays operator-gated. Memory
`project_ds_ad_axis_ability_term_rm39`.

**Process:** the ordered bump ritual produced **zero stamp failures** this time
(vs 20-25 wasted minutes on each of the last two bumps). Share release notes
were stale AGAIN behind a green `--check` - second consecutive bump; now written
into `feedback_engine_bump_ritual_order` as required step 4b.

Verification: dual suite **20602 passed / 2 failed / 24 skipped / 2357 subtests
in 22:07**, the 2 being the known `coach_poll_offload` flake, verified standalone
at 2 passed in 0.13s. DS-only pre-bump 8625/1 skipped. New file 32 tests.

---

# 2026-07-19b (RM-39/RM-43 ADJUDICATED "no haste term", then my own headline RETRACTED; 4 Share/tool tails; 3 commits)

**Phase 1 answer, and it holds:** haste must NOT modulate the measured cast rate.
`ult_rates.get_spell_casts_per_sec` takes no `item_ids` (derivative zero across
candidates); cast rates divide by whole-game duration (already haste-inclusive);
and `hybrid._damage_axis` puts Aatrox 8/3 + Ambessa 9/0 on `ad` while every
`_ability_damage` site gates on `ap`. `grep -c ability_haste` = 0 in `dps.py` and
`hybrid.py`. Decisive: `compute_ability_dps` is called **0 times** for both in a
full rank (Veigar control 142). Spec `docs/specs/SPEC_rm39_rm43_ability_haste.md`.

**READ THIS BEFORE ANY DS PROBE.** I published a wrong retraction this session and
caught it myself. Every `/rank-*` route defaults its target to ALL ZEROS, and
BotRK's on-hit is %target-max-HP, so a zero-HP target sinks it ~50 places. At the
sweep's tanky target (`100/60/2500/1200`) the RM-39/RM-43 filings reproduce
**exactly** - Shojin 51 and 47. Two more traps: body key is `items` NOT `item_ids`,
and there is no `/rank-hybrid` (bruiser = `/rank-bruiser`). All three now in the
ROADMAP PROBE HAZARD block + `reference_ds_probe_zero_target_defaults`.
Eleven agents and an adversarial judge panel did not catch it - they verify that
code says what you claim, not that your probe asked the same question as the
finding you are contradicting.

**Do NOT redo:** RM-39/RM-43 are RE-SCOPED not rewritten - defect verbatim,
mechanism now "missing AD-axis ability term" (92/173 champs, est 3-5 sessions).
Do not re-pitch a haste term. Do not re-file the Share route-table / seam-doc /
anchor-rule / SESSION_RE tails - all shipped in `2f35163d` with tests.
`wakeup_prune.py` works now; the old "manual relocation" note is retired.

**Next:** the AD-axis ability term is the open build. Operator-gated and NOT mine
to flip: default-ON for `team_blended` (ds.ehp) and `apply_canonical_cast_rate_keys`
(ult_rates).
