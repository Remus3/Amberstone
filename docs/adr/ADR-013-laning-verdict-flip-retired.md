# ADR-013: The HZ-A laning-verdict flip is RETIRED - the verdict carries zero information

**Date:** 2026-08-06
**Status:** Accepted
**Closes:** ROADMAP RM-155 (filed 2026-08-04). Supersedes the flip half of RM-09 / G7-01.

## Context

Haiku-to-ZERO Lane A precomputes a "trade / all-in / back off" laning verdict for
every champion x enemy x level-band x mana x cooldown cell into
`data/daemon_slayer/laning_scenarios/<patch>/laning_scenarios_<mode>.json`
(~66 MB per mode, three modes). `core/precomputed_laning_coach.precomputed_choices`
serves those cells. **The flip** is the step that was never taken: replacing the
live Claude Haiku laning judgement with that precomputed verdict.

The flip was always gated on a number, deliberately - "a wrong precompute is worse
than a Haiku call". Two different gates accumulated, and they are routinely
confused:

| gate | tool | asks |
|---|---|---|
| AGREEMENT | `tools/hz_shadow_report.py` over `data/hz_choice_shadow.jsonl` | does the precompute say what Haiku said? (substitutability) |
| VALIDITY | `tools/replay_laning_verdict_validate.py` over `data/rewind_history.db` | was the precomputed verdict RIGHT about the lane? (correctness) |

RM-155 is the VALIDITY gate. It has been at chance since it was first run
(0.4955 on 2026-06-18), and re-measurement has never moved it. Its acceptance was
written as "either a native per-mode corpus, or an explicit decision to retire the
laning-verdict flip". This ADR is that decision.

### What was measured (2026-08-06, this ADR's own run)

Command, from the repo root:

```
python tools/replay_laning_verdict_validate.py --db data/rewind_history.db
python tools/laning_verdict_information_probe.py --db data/rewind_history.db
```

400 SR replays, 1998 lane pairs, levels 6 and 11, lane gold at minute 10 as the
label, `even_band` 0.02, coverage 3978/3996 (99.5 pct):

- **SR L6: n=1107, agreement 0.48870822041553746, Wilson [0.45935, 0.51814].**
  L11: n=1100, 0.4890909090909091, [0.45964, 0.51862]. Solo-kill-duel proxy:
  L6 n=535 0.488, L11 n=526 0.489. Every interval straddles 0.50. This is a
  0.0000-drift reproduction of the figure RM-155 was filed on.
- **Mutual information 0.00039 bits at L6 against a label entropy of 0.99987
  bits - 0.039 pct.** phi -0.023, Yates chi-square 0.51 (p ~ 0.47). Pooled:
  MI 0.00035 bits, 0.035 pct of entropy. The point estimate is on the *wrong*
  side of chance.
- Base-rate census: decisive fraction 0.5548 (2207 of 3978 covered scorings;
  1779 excluded by the even dead-band, 10 gold ties). Predictor favours side a
  48.13 pct of the time; the label favours side a 50.25 pct. Both vary. The
  contingency cells at L6 are 254 / 274 / 292 / 287.

### The finding that actually closes the row

A 0.50 agreement has two explanations and the gate alone cannot separate them:
the VERDICT carries no information, or the LABEL does. The gate's balance census
only rules out a degenerate label (one that never varies); a label that varies
while measuring the wrong thing still yields zero MI against a *correct*
predictor. `tools/laning_verdict_information_probe.py` was built to settle it,
with a deliberately stupid control - the empirical mean lane-gold-at-10 per
(role, champion), fitted on half the matches and scored strictly held out on the
other half, against the identical label:

| predictor | n | agreement | Wilson 95 pct |
|---|---|---|---|
| shipped laning verdict, L6 | 1107 | **0.4887** | [0.4594, 0.5181] |
| champion-identity gold prior, fit A score B | 854 | **0.5457** | [0.5121, 0.5788] |
| champion-identity gold prior, fit B score A | 723 | **0.5394** | [0.5030, 0.5754] |
| solo-kill duel winner -> gold winner | 963 | **0.7705** | [0.7429, 0.7960] |

**Both held-out folds of the champion prior exclude 0.50, and the direct duel
outcome predicts the gold label 77 pct of the time.** The label is learnable and
it is strongly coupled to the head-to-head combat result the verdict claims to
predict. So the label is not the dead half. A per-champion mean - a lookup table
that would fit in a few kilobytes - beats a 200 MB scenario corpus, and the
scenario corpus does not beat a coin.

### The one place the verdict is not noise, and why it does not rescue it

Per-role MI is not uniform. JUNGLE is 0.3916 over n=429, phi -0.216, chi-square
19.1 - **significantly anti-correlated**; TOP is 0.5633 over n=474, phi +0.128.
The aggregate zero is two real subgroup effects of opposite sign cancelling, not
a flat nothing. It still does not rescue the feature:

- The served chip does not condition on role, so neither subgroup is reachable
  without a feature that does not exist.
- TOP's n is inflated: levels 6 and 11 are the *same* pair scored twice against
  the *same* minute-10 label, so the effective n is ~237 and the chi-square ~3.7,
  which no longer clears p=0.05. JUNGLE survives that halving; TOP does not.
- JUNGLE's effect has the wrong sign, and jungle "lane pairs" are an artifact -
  the harness pairs the two junglers as though they laned. Exploiting it would
  mean shipping an inverted verdict for a matchup that never happens.

### Why the other acceptance branch is not buildable

RM-155's alternative was "a native per-mode corpus". That is not a
data-collection problem, it is a definitional one, and this is the measurement
that killed it:

- `data/rewind_history.db` holds 2081 ARAM and 160 CHERRY matches with
  timelines, so raw material is not the constraint.
- **Riot emits no `team_position` for either mode: 20804 ARAM and 2792 CHERRY
  participant rows, every single one empty**, against 1356/1356/1355/1355/1352
  populated for CLASSIC. `extract_lane_pairs` skips any row with a falsy `pos`,
  so it returns **0 pairs from 25 ARAM matches and 0 from 25 CHERRY matches**
  (125 from 25 CLASSIC).
- That is correct behaviour, not a bug to fix. ARAM has one lane and ten
  players; Arena is 2v2 subteams. **There is no lane 1v1 in either mode for a
  lane-outcome label to be about.** No corpus build produces one.
- Arena is doubly blocked: RM-158 established the shipped
  `laning_scenarios_arena.json` is an SR copy (its header carries
  `income_per_min: 450.0`, identical to sr, against ARAM's 600.0).

So the "native per-mode corpus" branch cannot be specified as a buildable row at
any cost, and the cost that *was* on the table - the deferred v4 table regen,
~8.5 min and 339 MB per mode - would not have touched the number: it changes
which cell is read, not whether the cell's verdict predicts anything.

## Decision

**Retire the HZ-A laning-verdict flip.** The precomputed laning verdict is not a
candidate to replace the live laning judgement, on this gate or any refinement of
it, and the VALIDITY gate is closed rather than left pending a better number.

`tools/replay_laning_verdict_validate.py` now stamps `decision.status = RETIRED`
into every artifact it writes, and its interpretation text no longer offers
">= 0.55 with large n = a defensible deterministic substitute" as a live option.

### What "retire" means in code - precisely

**Retired:** the *decision* to serve `core.precomputed_laning_coach` verdicts as
live coach output. It was never wired, so retirement is enforced structurally
rather than by deleting a flag: `tests/test_laning_verdict_flip_retired.py`
pins the exact set of non-test, non-tool modules that may import the
precompute's verdict API. That guard goes red the day someone wires the
precompute into a served path, which is the only form the flip can take.

**Explicitly NOT retired, and must NOT be deleted:**

- **`data/daemon_slayer/laning_scenarios/**` (all three modes, all patches).**
  Git-LFS, ~66 MB per file. RM-158 and RM-172 are both open against these
  tables, and `core/laning_scenario_precompute.py`'s patch-fallback
  (`_latest_available_patch`) reads them. They are evidence and they are other
  rows' subject matter.
- **The shadow logging.** `dashboard/_deterministic_coaching.shadow_log_precomputed_choices`
  keeps running and keeps writing `data/hz_choice_shadow.jsonl`. It is the
  substrate for `tools/hz_shadow_report.py`, `tools/hz_mismatch_diagnose.py` and
  `tools/hz_shadow_arena_contamination.py`, and RM-158's corpus work is recorded
  in it. Retiring the flip does not retire the observation.
- **`core/precomputed_laning_coach.py` itself.** `core/laning_verdicts.py` imports
  `laning_trigger` from it - a pure string helper that renders the "Caitlyn, full
  mana, ult up, lvl 6" condition clause on a chip. That has nothing to do with
  the verdict and is on the live served path today.
- **`RC_LANING_CV_SERVED`.** A different feature and a different gate. It gates
  the *CV override* (`core/laning_cv_overrides.apply_cv_to_choices`), which
  replaces chips when vision sees the enemy dead / low HP / fogged, on top of a
  base verdict that comes from a *live* `compute_matchup` call, not from the
  precomputed table. This ADR does not decide it. It does contaminate its
  paperwork: its documented gate is `hz_shadow_report` agreement >= 70 pct, i.e.
  agreement with Haiku on a laning verdict now measured uninformative, so that
  criterion should be restated before anyone flips it. That restatement is not
  this row.
- **`tools/replay_laning_verdict_validate.py`.** Still a valid instrument, still
  runnable, still the thing to re-run if a future table changes the math. Only
  its flip-readiness framing is withdrawn.

**Nothing is deleted by this ADR.** The retirement is a decision plus a guard.

## Consequences

**Good:** a measured-dead feature stops consuming sessions. RM-155 closes, the
deferred ~190 MB/mode v4 regen stops being owed *to this row*, and the two
acceptance branches are both resolved rather than one being left as a standing
"someday". The evidence is re-derivable by one command instead of being a claim
in a doc, so re-opening is cheap and honest.

**Trade-off:** Lane A's precompute keeps being generated and shadow-logged with
no path to serving. That is deliberate - the tables are RM-158/RM-172 subject
matter and the shadow corpus is other tools' input - but it means real disk and
real regen time buy observation only. If a future session wants to reclaim that
cost, the row is "should Lane A precompute exist at all", which is a bigger
question than this one and needs its own ADR.

**Watch for:**

- **The `--mode` trap in `tools/replay_laning_verdict_validate.py`. This is the
  single easiest way to produce a plausible wrong re-measurement.**
  `replay_matchup_validate.select_sr_match_ids` is
  `WHERE game_mode = 'CLASSIC'` unconditionally, so `--mode` swaps the shipped
  TABLE and never the CORPUS. `--mode aram` on 2026-08-06 returned L6 n=1079
  agreement 50.3 pct [47.3, 53.3] with an *identical* `pairs=1998
  coverage=3978/3996` to the sr run - the ARAM table scored against SR lane
  outcomes. It reads like a native ARAM number and is not one. **ARAM has no
  native gate measurement and cannot have one.**
  `tools/laning_verdict_information_probe.py` refuses any mode but `sr` for
  exactly this reason.
- **`item_state` is INERT on every shipped table.** All of them are schema
  `laning_scenarios/v3`, in which the `cd_state` node IS the leaf (its keys are
  `economy` / `net_swing` / `pct_enemy_removed` / `pct_my_removed` / `verdict`).
  `lookup`'s descend-only fallback therefore returns the same cell for every
  `--item-state`. The axis sweep is correct code with no data behind it.
- **"SR is stranded on 16.12.1" is WRONG.** `16.13.1` ships all three modes
  (sr / aram / arena). Do not re-file that.
- **The RM-158 corpus correction cannot move this number**, and a re-measurement
  claiming it did is measuring something else. On 2026-08-06 a sibling slice
  re-flagged 1148 mislabelled arena rows in `data/hz_choice_shadow.jsonl`
  (`precompute_source: "sr_copy_rm158"`, not dropped). That file feeds
  `tools/hz_shadow_report.py`. This gate never opens it - it reads
  `data/rewind_history.db` and the shipped tables and nothing else. Verified by
  grep: zero `hz_choice_shadow` references in either replay tool.
- **Do not re-run the gate hoping for a better number, and do not build the v4
  regen to fix the score.** Neither addresses the finding. If you want to
  re-open, run `tools/laning_verdict_information_probe.py`: it emits
  `finding: verdict_carries_signal` and says so in plain text if the world has
  changed, and `finding: label_not_learnable` if the ground-truth proxy has
  rotted. Attach that artifact to the re-open.
