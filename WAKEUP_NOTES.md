# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated Term A `2026-07-18l`; newest 3 = RM-39 L1 build `2026-07-19c` + RM-39 adjudication `2026-07-19b` + AH-slice `2026-07-19a`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-19a (RM-92 ability-haste slice SIZED -> DEFER, then its 4 tails SHIPPED 1.221.0; 2 commits, CI green)

**Verdict first, no code:** `docs/specs/SCOPE_rm92_ability_haste.md`. All 5 AH
champions route AWAY from the only scorer that prices ability haste (Twitch /
Xayah / Yunara -> `dps.py`, Udyr / Yorick -> `hybrid.py` AD branch). `dps.py` has
no ability model AT ALL - not merely no AH term. **The finding that settled it:
AH is ~1% live even where it IS wired** - the haste-shortened cooldown only feeds
the `measured <= 0` fallback (`ability_dps.py:1231`), and on the live 680-pair SR
table just 8 pairs reach it, 6 effectively. This is MODEL work already spec'd as
**RM-39 + RM-43 - do NOT open a third id.**

**Then the 4 tails, all shipped** (`5f2371ce`, ENGINE 1.221.0): `aram_ability_haste`
was assigned total AH and printed an ARAM note during SR runs (fixed, zero
production consumers); **NEW DEFAULT-OFF seam `apply_canonical_cast_rate_keys`** -
cast-rate lookups keyed the DISPLAY name against ID-keyed data so 21 champions
silently took `global_fallback` while still reporting "measured", across **4 call
sites** not 1, fixed at the `ult_rates.py` chokepoint; plus 3 stale comments and a
registry docstring citing a regen tool that has never existed. 8 ward PNGs
restored (zero code refs - removal stays a deliberate call).

**Two process errors, both self-caught.** (1) Skipped the regen step **with a
memory telling me not to** - `feedback_engine_bump_ritual_order` documents this
exact failure from the previous session. The stamp is independent of the content;
byte-identical output still needs the regen. Cost a 20-min suite. (2) Nearly
reported a stale subagent `repo_suite.txt` as my own run; caught on mtimes.

**Do NOT redo:** the RM-92 population audit (CLOSED), the AH sizing (DEFER is
final), the 4 tails (shipped + live-probed). **Open:** operator-gated default-ON
flips for BOTH seams (`team_blended`, `apply_canonical_cast_rate_keys`); three
Share gaps flagged not fixed (route tables claim "4 GET + 15 POST" vs a live 31;
`team_blended` + `kit_conversion_strength` undocumented in the authored half;
three version anchors uncovered by `_doc_anchor_rules()` - which is why README sat
72 minors stale while `--check` read green).
