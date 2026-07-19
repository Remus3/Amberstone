# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-19g (gemini-loop cycle 2 - DS modelled runes as offense only; defensive resist half now exists)

**The transferable lesson is about how a good agent report can still be wrong.**

The R132 sweep agent that found the rune hole did excellent work: every `file:line`
it cited survived an independent grep, its REFUTEs were all correct, and the
structural gap it identified was real. `ehp.py` grep for `rune|perk|keystone`
returns ZERO matches, `rank.py` returns ZERO, seven live Resolve rune ids return
0 hits across the entire package, and Aftershock 8439 is registered for damage
only with its own formula string admitting "(resist-bonus side not modeled)".

It still got the central formula wrong. It reported Aftershock as
`45 + 75% of Bonus Resists` and dropped the trailing longDesc clause:
"Resistance bonus from Aftershock capped at: 80-150 (based on level)". Building
on the paraphrase would have shipped math that over-credits precisely the
high-resist tanks the feature exists to serve - at level 18 with 150 bonus armor
the uncapped value is 157.5 against a cap of 150. What caught it was re-reading
the raw `runesReforged.json` longDesc instead of the agent's summary of it.

**Rule to carry: when a finding hands you a FORMULA, reproduce the formula from
source before building on it - checking the cited file:line is not the same
check.** Same failure family as the existing DS probe-trap memories, new surface
(paraphrase drift rather than probe-parameter drift).

Second lesson, smaller but sharp: **a test suite can PROTECT the defect it ought
to catch.** R133 found `test_arena_mirrors_credit_same_as_base` asserting
`base == mirror` - which is exactly the "base nominal" seeding bug expressed as
an invariant. The wrong Arena magnitudes were not merely uncaught, they were
pinned. Before assuming a red test means a new break, check what the existing
tests assert about the values you are correcting.

**Shipped:** R132 `e6a84734` (ENGINE 1.223.0 -> 1.224.0) new
`_rune_resist_grants.py` for Aftershock / Conditioning / Unflinching, folded into
`eff_armor` / `eff_mr` behind DEFAULT-OFF `apply_rune_resist_grants`. R133
`ad16ba65` (executor-opened, no bump) corrected three of four Arena / prismatic
mirror magnitudes - 226665 is 40% not 30%, 224401 is 50 MR not 70, 663059 is 10%
not 20% - each re-verified against the raw item index before editing.

**Deliberately not built, spec'd read-only:** RM-99 Heartsteel's permanent-HP
half is pinned at ZERO stacks forever (~43 EHP per proc; ~16.5 procs takes #1 off
Randuin's on Sion) - RM-101 the defensive-rune remainder - RM-102 Warmog's Arena
mirror credited a Vitality passive it does not have - RM-103 Unending Despair's
250% SELF heal uncredited and mislabelled "ally ... utility-only" - RM-104 Kaenic
Arena mirror double-gated out of its own shield. Font of Life is DATA-BLOCKED:
its base heal is an unresolved `@BaseHeal@` template var in live DDragon 16.14.1.
Do not invent a number for it.

---

# 2026-07-19f (gemini-loop cycle 1 - two silent failures closed: the nightly critic and the nightly suite)

**Both failures were invisible to the surfaces we actually watch. That is the
transferable lesson, not the individual fixes.**

**RC-GeminiAudit produced nothing for 28 nights while reading Enabled/Ready.**
`ops/runtime/gemini_last_audit.txt` pinned a worktree-slice sha that never
survived cherry-pick, so `git log <dangling>..HEAD` came back empty and
`tools/gemini_audit.ps1` took its own "nothing to audit" branch and exited 0 -
no review, no log line, `logs/gemini_audit.log` did not exist at all. The
session-start anomaly probe only ever surfaced the unrelated `0xC000013A`.
**Exit 0 is not success and Ready is not health.** Now self-heals to `HEAD~10`
with a loud WARN and logs `START pid=...` unconditionally as its first write.

**The 0xC000013A is a SEPARATE fault, still unproven, deliberately left open.**
Six hypotheses refuted, including my own leading one - InteractiveToken session
teardown died to a same-night control (5 sibling InteractiveToken tasks ran
3:00 through 4:17, all result 0, one of them one second earlier). The task was
NOT re-registered: changing a working ops surface on refuted evidence is churn.
**If it recurs on a later nightly, the marker fix is not the cause - read the
log. START then silence = killed mid-run; no START = died before line 20.**
The task still DISPLAYS `Last Result -1073741510` until the 7/20 run clears it;
that is historical, not live.

**The nightly full-suite had been red for 12 consecutive days** (runs
28935372989 .. 29682372934) and nobody saw it, because the push `check` job is
green BY CONSTRUCTION - it never runs `tests/` as one process, so it cannot
reproduce the pollution. Only the nightly can. **Two unrelated bugs, not one
ordering bug**, which is exactly why both files passed in isolation: Playwright's
session-scoped ProactorEventLoop leaves asyncio's per-thread running-loop marker
set on the main thread (that marker is LIVE - clearing it in conftest makes
snapshot_panels time out, tried and reverted), and the Jhin test depended on a
live `:8893` CI can never spawn (`creationflags=0x08000000` raises on Linux).
Test-side fixes only. **Main is green: 20544 passed, 82 skipped, 2357 subtests,
0 failed** (run 29688982602, dispatched manually since only that job reproduces).

**LATENT, carry forward:** `tests/snapshot_panels` still leaks the loop marker.
Any NEW test calling bare `asyncio.run()` on the main thread and sorting after
it fails identically - use the `_run_coro`/`_run_poll_loop` pattern. Four
near-identical local copies now exist; consolidating them is the open follow-up.

**Process note worth keeping:** both slice agents REFUTED an orchestrator
hypothesis on evidence, and both were right to. They were briefed to verify
premises rather than accept them. Keep briefing them that way.

---

# 2026-07-19e (RM-98 ADJUDICATED - unadjudicated inheritance, defence retracted, both named fixes infeasible)

**Question asked: deliberate modelling choice, or accident of reusing a
convenient table? Answer: NEITHER.** It is a documented-but-unadjudicated
inheritance. Exactly one denominator-adjacent choice was made deliberately and
recorded - **measured vs `1/cooldown`** (`history_notes.md:12534`, Veigar Q
0.098 measured vs 0.25 theoretical) - and that one is defensible and stands. The
DENOMINATOR was never in the option set; a combat-window basis first appears
anywhere in the repo in 2026-07, as an audit finding. The generator admits the
inheritance in its own words (`build_spell_cast_rates.py:9-11`): "Mirror of the
(undocumented) s145 ad-hoc query that built `ult_cast_rates.json` for the
Malignance Hatefog proc". And the "locally correct at origin" escape fails too -
`ult_rates.py:5-7` says the s145 ancestor already converted the rate into a
"DPS-time proc rate", so whole-game was never adjudicated correct for a DPS
context ANYWHERE in the chain. `test_cast_rates.py:194-197` is a 100x-wide band
that would not have caught a base swap.

**The blocker was FALSE and is retracted - and the mechanism is the lesson.**
RM-98 defended the basis as "haste-inclusive by construction, which is why the
RM-39/RM-43 adjudication relied on it". Haste-inclusiveness follows from
EMPIRICISM, not the denominator (a combat-window empirical table is equally
haste-inclusive; the generator attributes it correctly to the rate being
**measured**). And RM-39 did not rely on it - it **condemned** it:
`SPEC_rm39_rm43_ability_haste.md:187-192` calls the opposite decisive, and
`:174-176` / `:318-320` prescribe replacing the denominator. **How the error got
in:** three artifacts each weld "whole-game duration" and "already
haste-inclusive" with an "and"; a later summary read the conjunction as
CAUSATION. Two true facts joined by "and" became a false "because". All three
sources corrected this session.

**Four corrections to RM-98 as filed.** (1) The defect **already ships
DEFAULT-ON** in `ds.onhit` (`onhit_dps.py:143`, live at `/rank-onhit`), `ds.dps`
and `ds.hps` - gating a default-OFF flag on it is incoherent, and two docstrings
assert the falsehood outright (`onhit_dps.py:4-5` "both halves are in the same
DPS units"; `hybrid.py:151-153` names the step that BREAKS additivity as its
reason FOR additivity). (2) The term is **NOT inert** - I hypothesised it was and
was refuted by measurement: 29.2% cohort mean of the AD-axis damage term, 65.9%
Riven, and it re-orders. Per-cast damage dwarfs per-second auto damage, so a
small rate still lands. Scaling 27x INVERTS the scorer rather than correcting it.
(3) **27x overstates** - Q 7.83x / W 27.12x / E 6.44x, characteristic ~7x, and
the 0.5/s reference is a `scenarios.json` field `_rotation_attack_dps` never
reads. (4) **Under-scoped** - misses `ability_dps.py:1252`, where 6 champions sum
BOTH bases in one total.

**Both fixes RM-39 named are INFEASIBLE, and the spec said nobody had sized
them.** Sized here: "casts per second alive" is computable
(`participants.time_spent_dead`) but lifts only **1.25x** against a 27x gap, so
the gap is overwhelmingly LANING time, not death timers. "Per second within N
seconds of damage" needs sub-window resolution, but `timeline_frames` cadence is
**60s** (measured 60016-60021 ms) - a 3-10s window is not resolvable.

**Recommendation: do not chase a denominator replacement.** Demote the measured
rate from a DPS multiplier to a **cast-propensity prior** (`SPEC:198-202`), which
needs correct relative ordering - preserved by the whole-game basis - not a
correct denominator. Spec `docs/specs/SPEC_rm98_cast_rate_time_base.md`, LEDGER
956, commit `3aaf586f`. Tier-0, ENGINE stays 1.223.0. **NEXT:** the open
hypothesis that the seven-mage Liandry's/Blackfire invariance is partly an
artifact of this defect (`_rank_mage.py:332` mixes always-on item DPS at combat
weight with spell rows at whole-game weight) - unproven, needs its own
experiment.

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
