# ADR-014: The shipped ARAM laning tables are KNOWN-WRONG on economy and are deliberately NOT regenerated

**Date:** 2026-08-06
**Status:** Accepted
**Closes:** ROADMAP RM-175 (filed 2026-08-06, LEDGER 1220), acceptance branch 2
("record why a 50 percent economy error in a shadow-only table is tolerable").
**Depends on:** ADR-013 (the flip this table's verdict was built to feed is RETIRED).

## Context

`core.lead_projection.minutes_for_level` was mode-blind until 2026-08-06: one SR
levelling curve stood in for three different games. It now carries a per-mode
curve (`_LEVEL_CURVE`: SR `(1.0, 0.5)`, ARAM `(1.0, 1.01)`, ARENA `(3.0, 0.79)`)
plus a `level_curve_is_registered` refusal gate for offline generators.

`core.laning_scenario_precompute.economy_cell` bridges a level band to a minute
through that function and multiplies by the mode's gross income, so the fix
moves every economy leaf in the shipped ARAM laning tables. Those tables are
`data/daemon_slayer/laning_scenarios/16.12.1/laning_scenarios_aram.json` and
`.../16.13.1/laning_scenarios_aram.json`, both git-LFS, both ~66 MB.

RM-175's acceptance was "regen ARAM at both patches with the corrected curve, OR
record why a 50 percent economy error in a shadow-only table is tolerable". This
ADR is the second branch, and "tolerable" is the wrong word for what was found -
the error is **contained and unreachable**, which is a different and stronger
claim than tolerated.

### The error, derived analytically and then confirmed against the artifact

Both the SR and the ARAM curves start at base level 1.0, so in
`minutes_for_level` the `(level - base)` factor is identical and cancels. The
whole error is therefore the ratio of the two rates, and it is **exactly
band-independent**:

```
gold_corrected / gold_shipped = minutes_ARAM / minutes_SR
                              = rate_SR / rate_ARAM
                              = 0.5 / 1.01
                              = 0.49504950495049505
delta = -0.50495049504950495  ->  -50.495049504950495 percent
```

That is a closed form, not a sampled measurement, and it holds at every band the
generator emits. The shipped income row was already ARAM's own (`income_per_min:
600.0` in the header of both files), so income is not implicated - minutes are
the entire defect.

Per band (`GEN_BANDS` = L2 / L6 / L11):

| band | level | minutes shipped | minutes corrected | `gold_at_band` shipped | corrected | `next_spike` shipped -> corrected |
|---|---|---|---|---|---|---|
| L2 | 2 | 2.0 | 0.9900990099009901 | 1200.0 | 594.0594 | `first_item` -> `component` |
| L6 | 6 | 10.0 | 4.9504950495049505 | 6000.0 | 2970.297 | `two_item` -> `first_item` |
| L11 | 11 | 20.0 | 9.900990099009901 | 12000.0 | 5940.5941 | `complete` -> `two_item` |

**Confirmed against the shipped bytes, not just recomputed.** A full-file scan of
both ARAM tables returns exactly **six** distinct `(gold_at_band, next_spike,
recall)` triples, and they are exactly the six a mode-blind curve produces:

| triple | 16.12.1 leaves | 16.13.1 leaves |
|---|---|---|
| `1200.0 / first_item / hold` | 68800 | 69546 |
| `1200.0 / first_item / recall_now` | 49536 | 50170 |
| `6000.0 / two_item / back_soon` | 68800 | 69546 |
| `6000.0 / two_item / recall_now` | 49536 | 50170 |
| `12000.0 / complete / hold` | 68800 | 69546 |
| `12000.0 / complete / recall_now` | 49536 | 50170 |

**355008 economy leaves at 16.12.1 and 359148 at 16.13.1 are wrong on
`gold_at_band` and on `next_spike` - every single one.** `recall` is wrong on
137600 and 139092 of them respectively (the two `hold` groups, which become
`back_soon`).

### Correction to the RM-175 filing: the per-axis attribution is transposed

RM-175 as filed says "`next_spike` moves at L2 and L11, and `recall` at
L2/L6/L11". **Measured here by driving `economy_cell` under a mode-blind
`level_curve` against the real one, over all three bands x both mana states x
both manaless values (12 combinations), it is the other way round:**

- **`next_spike` moves at ALL THREE bands, 12 of 12 combinations.**
- **`recall` moves at L2 and L11 ONLY, 3 of 4 combinations at each, 6 of 12
  overall. It does NOT move at L6 (0 of 4).** The combination that does not move
  is `(mana_state=low, manaless=False)`, which is pinned to `recall_now` by rule
  1 of `_recall_verdict` on both curves; the other three go `hold -> back_soon`.

The `-50.495` percent figure in the filing is correct and is reproduced to full
precision above. Only the axis attribution was wrong. This ADR is the
correction; the ROADMAP row is not edited by this slice.

SR is unaffected (its curve did not move: 0.0 percent at every band, verified).
ARENA moves too (-100 pct at L2, -62.025 pct at L6, -49.367 pct at L11 - not a
constant, because ARENA's base level is 3.0 so the `(level - base)` factor does
NOT cancel) but ARENA already owed a regen from RM-158 and carries no new debt.

### Who actually consumes an ARAM laning table

Every non-test, non-tool reader, with file:line:

| reader | line | what it does |
|---|---|---|
| `dashboard/_state_builder.py` | 629 | calls `shadow_log_precomputed_choices(coach, lc, mode_key)` |
| `dashboard/_deterministic_coaching.py` | 1647 | `payload = load_laning_scenarios(lower)` - inside `shadow_log_precomputed_choices`, gated on a live liveclient champion |
| `core/precomputed_laning_coach.py` | 484, 521 | `load_laning_scenarios(mode)` when the caller passes no payload |
| `core/precomputed_laning_coach.py` | 333-342 | `_recall_outcome` - **the only consumer of the economy triple**, renders `"<N>g banked; next spike <label>"` onto a `CoachChoice` |
| `core/hz_choice_shadow.py` | 79 | reads `dimensions.economy` for the RM-158 arena writer gate (header only, not the leaves) |

**All of it terminates in `data/hz_choice_shadow.jsonl`**, which is gitignored
and machine-local. `shadow_log_precomputed_choices` states in its own docstring
that it has "NO effect on live output", and ADR-013 lists it under "explicitly
NOT retired" precisely because it is observation and not service.
`tests/test_laning_verdict_flip_retired.py` pins the permitted reference set with
SET EQUALITY, so the day anything else reads it, that guard goes red.

**Nothing renders an ARAM `gold_at_band` to a human.** The wrong number is
written into a local jsonl and read by three offline report tools.

## The deferral premise, re-checked

RM-175 deferred the regen for two stated reasons. They did not age the same way.

1. **"RM-155 defers the ~190 MB/mode v4 regen."** **This premise is GONE.**
   ADR-013 retired RM-155 on 2026-08-06 and says so in as many words: "the
   deferred ~190 MB/mode v4 regen stops being owed *to this row*". Inheriting
   this reason unchecked would have been the known failure class
   (`feedback_decline_reason_goes_stale_before_the_count`).
2. **"Landing one mode at a newer schema than its siblings is exactly what that
   deferral exists to prevent."** **This premise STANDS, and it never belonged
   to RM-155 in the first place.** It is a property of the generator, verified
   below.

So the deferral did lose half its stated basis. It also lost, in the same
document and on the same day, the entire *benefit* side: ADR-013 retired the
flip these tables' verdicts were built to feed, so a corrected table has nowhere
to go that a wrong one does not.

## The schema wall, verified

- **Every shipped table is `laning_scenarios/v3`.** Read off the tail of all
  seven files (16.11.1 sr; 16.12.1 and 16.13.1 x sr/aram/arena).
- **The generator has no v3 emit path.** `core/laning_scenario_precompute.py:856`
  hard-codes `"schema": "laning_scenarios/v4"`. There is no flag, no branch.
- Therefore **any regen of ARAM alone lands a v4 file next to v3 siblings in the
  same patch directory.** That is not a cosmetic version skew:
  - `lookup`'s v3/v4 compatibility is *descend-only* - a v3 `cd_state` node IS
    the leaf. ADR-013 already records that `item_state` is INERT on every
    shipped table for this reason. A v4 ARAM table makes that axis live for ARAM
    and ARAM only.
  - A v4 leaf carries `cooldown_window` / `spike_timing` blocks, which
    `dashboard/_deterministic_coaching.py:1691-1705` folds into
    `verdict_blocks`. The shadow corpus would then hold ARAM rows carrying
    verdict blocks against sr/arena rows that structurally cannot, and
    `tools/hz_shadow_report.py` / `hz_mismatch_diagnose.py` /
    `hz_shadow_arena_contamination.py` all read that one file. **Introducing a
    silent per-mode structural asymmetry into `hz_choice_shadow.jsonl` is the
    exact defect class RM-158 spent a session cleaning out of that same file.**
  - ~5x the leaf bytes: ~66 MB -> ~339 MB per file, as permanent git-LFS
    objects. (Figure inherited from RM-158 / LEDGER 1211; NOT re-measured here,
    because measuring it means running the regen.)

**A v3-compatible regen is not available today.** It would require adding a v3
emit path to the generator - new code in a Tier-2 module whose only purpose is
to keep a shadow-only artifact schema-consistent with its siblings. Considered
and rejected on cost/benefit given ADR-013.

**If a regen ever happens, the coherent unit is all three modes at ONE patch,
16.13.1 only.** That removes the mixed-schema objection outright, and it would
also discharge RM-158's open table half (the shipped `laning_scenarios_arena.json`
is an SR byte-copy; its header still reads `income_per_min: 450.0`). ARAM alone
is never the right unit.

## 16.12.1 is unreachable, so regenerating it is pure cost

Re-verified live, not inherited:

```
resolve_patch()                      -> 16.15.1
_latest_available_patch('aram')      -> 16.13.1
load_laning_scenarios('aram')        -> version 16.13.1, _served_patch 16.13.1,
                                        _requested_patch 16.15.1, schema v3
load_laning_scenarios('aram','16.12.1') -> version 16.12.1, _served_patch None
```

The prior-patch fallback takes `max()` over the patch dirs that have a table for
the mode, so while 16.13.1 exists the fallback can never select 16.12.1. **Every
production caller passes no `patch` argument** (`_deterministic_coaching.py:1647`,
`hz_choice_shadow.py:79`, `precomputed_laning_coach.py:484,521`), so no
production path can reach 16.12.1. An explicit pin IS honoured verbatim, and only
`tools/replay_laning_verdict_validate.py:644` can supply one. This reproduces the
sibling slice's finding exactly.

## Decision

**Do NOT regenerate the ARAM laning tables at 16.12.1 or at 16.13.1.** Record the
defect as a machine-checked pin instead of a prose note.

The reasoning, ranked:

1. **The consumer's destination is retired.** ADR-013 closed the only path on
   which a corrected `gold_at_band` could ever have reached a player. A 50 pct
   economy error in a number nothing serves has no victim except a future reader
   of the file - and that reader is exactly what the guard below is for.
2. **The fix costs more integrity than the defect does.** ARAM-alone lands a v4
   file among v3 siblings and injects a per-mode structural asymmetry into the
   shadow corpus that three tools read. Trading a known, bounded, closed-form
   numeric error for a silent structural one is a bad trade.
3. **Half the regen is provably wasted.** 16.12.1 is unreachable from every
   production caller.
4. **The error is fully characterised in closed form.** `0.5 / 1.01` is exact and
   band-independent; anyone who needs a corrected ARAM economy value can compute
   it from the shipped one by a single multiplication, without a 339 MB artifact.

### The case AGAINST this decision, stated fairly

- The tables are **tracked, shipped, and read on every live ARAM tick**. They are
  not scratch. A future session that opens `laning_scenarios_aram.json`, sees
  `mode: "aram"`, sees a correct `income_per_min: 600.0` header, and reads
  `gold_at_band: 12000.0` at L11 has every reason to trust it. **That is the
  RM-158 failure mode repeating** - an SR-shaped number wearing a mode header -
  and RM-158 cost a full session to unwind.
- "Nothing serves it" is a statement about **today**. `RC_LANING_CV_SERVED` is
  live-adjacent, and ADR-013 explicitly declined to decide it.
- A number that is wrong by half is not a rounding artifact. Doing nothing about
  a defect of that size sets a precedent that erodes with each repetition.

The guard below is what makes the decision survivable against all three: it
converts "we know it is wrong" from institutional memory into a test that fails
when anyone's assumption drifts.

## What was shipped instead

`tests/test_rm175_aram_table_known_wrong.py` - a durable, machine-checkable
statement of the defect. Four things it pins, deliberately split so the
teeth do not depend on git-LFS content being present:

1. **The closed form** (pure code, always runs): the corrected/shipped gold ratio
   equals `rate_SR / rate_ARAM` exactly, at every generated band, derived from
   `lead_projection.level_curve` rather than from a literal.
2. **The axis census** (pure code, always runs): `next_spike` moves at all three
   bands; `recall` moves at L2 and L11 only and never at L6. This is the
   assertion that would have caught the transposed RM-175 filing.
3. **The disk pin** (skips loudly on an LFS pointer or a missing file): the
   shipped ARAM tables at both patches contain exactly the six known-wrong
   triples and none of the corrected values.
4. **The contract**: this ADR is on disk and linked from `docs/adr/README.md`,
   and carries the ratio and the reachability finding.

**A metadata marker stamped into the table header was considered and rejected:**
rewriting a byte inside a 66 MB git-LFS object mints a whole new 66 MB LFS blob
per file and invalidates the file hashes RM-158 recorded as evidence. The cost
of the marker would exceed the cost of the thing it marks.

## What would make the regen NECESSARY

Any one of these flips the decision. They are the trigger list, not a wish list:

- **Anything starts SERVING an ARAM economy value to a human.** Watch
  `core/precomputed_laning_coach._recall_outcome` and the permitted-reference set
  in `tests/test_laning_verdict_flip_retired.py`. That guard going red is the
  signal.
- **The generator gains a v3 emit path**, or all three 16.13.1 modes are
  regenerated together for another reason (most likely RM-158's arena half). At
  that moment ARAM rides along for free and there is no reason not to.
- **`RC_LANING_CV_SERVED` is flipped on** and its base verdict is ever sourced
  from the precomputed table rather than a live `compute_matchup` call.
- **The 16.13.1 ARAM table is deleted or a 16.14.x+ ARAM table lands**, either of
  which changes what `_latest_available_patch('aram')` resolves to and can make
  16.12.1 reachable.
- **An analysis consumes `gold_at_band` as an absolute quantity** rather than as
  a band-ordinal. The error is a constant scale factor, so anything that only
  compares bands within ARAM is unaffected by it; anything that compares ARAM
  gold to SR gold, or to a real gold number, is not.

## Consequences

**Good:** no 339 MB LFS object, no mixed-schema patch directory, no new
asymmetry in the shadow corpus, and the defect is now asserted by a test rather
than remembered by a doc. The closed form means a corrected value is one
multiplication away for anyone who needs one.

**Trade-off:** two shipped, tracked artifacts remain wrong on 714156 economy
leaves combined. That is accepted, knowingly, and pinned.

**Watch for:** the guard's disk half skips when the tables are git-LFS pointers,
which is the normal state of a fresh clone and of CI. The pure-code half does not
skip and carries the load. Do not "fix" a skipping disk half by deleting the
skip - fetch the LFS objects instead.

## Not decided here

- Whether the Lane A precompute should exist at all. ADR-013 raised it and
  routed it to its own ADR; nothing here changes that.
- RM-158's open table half (the arena SR byte-copy). Named as the most likely
  trigger above, not resolved.
- Re-basing SR's own 0.5 rate to its measured 0.5584. Recorded in
  `core/lead_projection.py` as a known pre-existing inconsistency and explicitly
  operator-gated there.
