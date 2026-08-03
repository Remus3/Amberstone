# S4 - ARAM deterministic-vs-Haiku action mismatch taxonomy

Read-only analysis slice. Source: `data/aram_coach_shadow.jsonl` (4970 rows,
7411781 bytes, mtime 2026-08-02 17:34). All figures below were computed this
session from that file; nothing is carried forward from a prior report.

Baseline reproduced: total 4970, dead_state 795, non_dead 4175, comparable 2424,
agree 1781 = 0.7347.

## VERDICT: (a) fixable deterministic rule gap

Not (b) Haiku noise, and not (c) a comparison artifact. Both were tested
directly and both were refuted. The evidence for (a) is four independent
measurements that all point at the same single missing rule operator.

### Evidence 1 - 98.6 percent of mismatches are EXACTLY one ladder tier

Mapping both sides onto the canonical ARAM ladder
(`core/aram_action_rule.py:52`, ALL-IN 0 / POKE 1 / HOLD 2 / DISENGAGE 3 /
FALL BACK 4, collapsed to all_in 0 / trade 1 / hold 2 / back_off 3 by the
report's coarse verdicts) and taking `native_index - det_index`:

```
  -3 :     1  ( 0.0%)
  -2 :     6  ( 0.2%)
  -1 :   372  (15.3%)   Haiku one tier MORE aggressive
  +0 :  1781  (73.5%)   agree
  +1 :   262  (10.8%)   Haiku one tier LESS aggressive
  +2 :     2  ( 0.1%)
```

Mismatch total 643; |delta| == 1 accounts for 634 of them (98.6 percent).
Only 9 rows in the entire corpus are two or more tiers apart. A disagreement
that is quantised to exactly one tier is not a judgment difference; it is a
missing one-tier operator.

The `-1` bucket is exactly the orchestrator's `det=hold -> native=trade` (233)
plus `det=back_off -> native=hold` (80) plus `det=trade -> native=all_in` (59).
The `+1` bucket is exactly `det=trade -> native=hold` (262). The two headline
classes are therefore not two phenomena but the two SIGNS of one.

### Evidence 2 - the rule has exactly one one-tier operator, and it is off

`core/aram_action_rule.py` implements the operator's documented ladder
faithfully: an HP base tier, then a wave shift of `index -1` when `wave_pct > 65`
and `index +1` when `wave_pct < 35`. That is the only plus-or-minus-one operator
in the rule, and its magnitude and sign structure match the residual exactly.

At the sole live call site, both non-HP inputs are hardcoded off:

`dashboard/_deterministic_coaching.py:1334-1337`
```
        det_block = build_block(
            hp_pct=hp_pct,
            wave_pct=None,  # vision-only; absent server-side -> no tier shift
            low_enemy_count=None,
```

So the shipped deterministic ARAM action is a pure function of `hp_pct` alone.
The wave arm can never fire.

### Evidence 3 - Haiku IS given wave_pct; the deterministic side is not

`coaches/aram_coach.py:1035` passes `wave_pct = vs.get("wave_pct", 50)` into the
Haiku user prompt, and `coaches/aram_coach.py:341-344` states the same
>65 / <35 shift rule verbatim. The two sides run the SAME ladder over
DIFFERENT input sets. This is a measured asymmetry in the wiring, not an
inference about model behaviour.

### Evidence 4 - the ALL-IN tier is structurally unreachable for the det side

Deterministic action vocabulary over the 4175 non-dead rows:

```
  POKE 1741 | FALL BACK 887 | HOLD 795 | DISENGAGE 416 | "" 336
```

Zero ALL-IN, in 4175 rows. ALL-IN requires `low_enemy_count >= 2` (or an HP>80
row lifted by `wave_pct > 65`), and `low_enemy_count` is hardcoded `None` at
line 1337, which `decide_action` defensively coerces to 0. Haiku emitted an
all_in verdict on 63 comparable rows. Every one of those 63 is a guaranteed
mismatch by construction. That is 2.60 pp of the 26.5 pp residual that is
provably a wiring gap and provably not noise.

## Hypotheses tested and REFUTED (negative results)

Class (c) was tested first and hardest, because it is the one that most often
masquerades as a rule gap.

**Timing skew between the det snapshot and the live tick - REFUTED.**
Lag sweep, comparing det at row `i` against native at row `i+lag` within a
session (472 sessions, segmented on a 240s gap or a champion change):

```
  lag  -2  agree 0.2977     lag  +1  agree 0.4345
  lag  -1  agree 0.4044     lag  +2  agree 0.3254
  lag  +0  agree 0.7347     lag +/-3..12  agree 0.35 - 0.41
```

A sharp single-point peak at lag 0 with a 30 pp cliff on both sides. If the
native block were systematically stale by one or more logged states, the peak
would sit at a positive lag. It does not.

**Stale / unrefreshed Haiku block - REFUTED as a separator.** Fraction of rows
whose `live_haiku` block is byte-identical to the previous row's: 35.4 percent
of AGREE rows vs 36.5 percent of MISMATCH rows. Staleness is present but is
distributed evenly, so it cannot explain the mismatch.

**Deterministic oscillation artifact - REFUTED as a separator.** The dedup
signature (`core/aram_coach_shadow.py:126-131`) is
`(mode_key, champ, enemy_comp, det.action)`, so a row is emitted precisely when
the DETERMINISTIC action changes. That is a genuine selection bias worth
knowing, and it predicts an A->B->A oscillation artifact. Measured: rows whose
det action differs from both neighbours while the neighbours agree with each
other are 14.4 percent of AGREE rows vs 12.3 percent of MISMATCH rows. The bias
is real but it is not the mismatch mechanism.

**Dead-state leakage - REFUTED.** 795 dead rows are excluded by
`_is_dead_state`. No surviving comparable row carries a respawn or
coaching-disabled marker, and 100 percent of comparable rows map onto the
ladder (0 unmapped).

**(b) Irreducible Haiku 50/50 noise - REFUTED.** For pairs of rows in the same
session sharing an IDENTICAL deterministic action string, how often do the two
native verdicts differ?

```
  W= 15s   1103 pairs   native self-agreement 0.9982
  W= 30s   1257 pairs   native self-agreement 0.9889
  W= 60s   1999 pairs   native self-agreement 0.8989
  W=120s   3769 pairs   native self-agreement 0.8273
```

Mirror control, pairs sharing an identical NATIVE action string:

```
  W= 15s   1376 pairs   DET self-agreement 0.9041
  W= 30s   1731 pairs   DET self-agreement 0.8128
```

At short timescales Haiku is the STABLE side (99.8 percent self-consistent at
15s) and the deterministic side is the volatile one (90.4 percent). A 26.5
percent residual cannot be attributed to a coin-flip by the side that flips
0.18 percent of the time. Caveat stated honestly: native short-window stability
is partly confounded with its refresh rate, so treat 0.9982 as an upper bound on
its true stability. Even the unconfounded 120s figure (0.8273) leaves Haiku more
self-consistent than the det side is at 30s.

**Champion-specific judgment - REFUTED as the dominant driver.** Of the 9
champions with 3 or more qualifying sessions, 6 flip the SIGN of their mean
ladder offset from game to game (Tristana spans -0.32 to +0.41; Senna -0.23 to
+0.20; Vayne -0.21 to +0.19). Standard deviation of the per-SESSION mean offset
is 0.188; of the per-CHAMPION mean offset, 0.118. The bias lives in the game,
not in the champion.

**Per-game systematic bias - CONFIRMED.** Of 67 sessions with 15 or more
comparable rows, 34 have one direction so dominant that the weaker direction is
under 25 percent of the stronger (for example one Kalista game 60.0 percent
negative / 0.0 percent positive; one Tristana game 0.0 percent negative / 40.6
percent positive). This is what a missing per-game state input looks like, and
it explains why the aggregate looks deceptively symmetric: per-game one-sided
biases in opposite directions cancel when summed.

## Per-axis measured separation table

A = `det trade -> native hold` (n=262). B = `det hold -> native trade` (n=233).
AGREE = all agreeing comparable rows (n=1781). Values are means over rows where
the axis is defined.

| axis | A | B | AGREE | separating? |
|---|---|---|---|---|
| elapsed sec within session | 485.4 | 476.8 | 544.8 | NO |
| enemy_comp length | 4.98 | 5.00 | 5.00 | NO |
| gold-remaining string present | 0.698 | 0.725 | 0.710 | NO |
| gold-remaining value (g) | 3295 | 2963 | 3047 | NO |
| det reset_item empty | 0.302 | 0.275 | 0.290 | NO |
| det choices length | 1.45 | 1.50 | 1.48 | NO |
| det objective present | 0.698 | 0.734 | 0.709 | NO |
| native risk text names a CC | 0.844 | 0.785 | 0.826 | NO |
| native text mentions a health pack | 0.015 | 0.052 | 0.127 | WEAK |
| native text names tower/inhib/nexus | 0.034 | 0.034 | 0.031 | NO |
| native fight_rule length (chars) | 81.0 | 78.3 | 78.2 | NO |
| det oscillation (A->B->A) | 0.145 | 0.069 | 0.144 | NO |
| native block stale vs prev row | 0.359 | 0.365 | 0.354 | NO |
| inter-row gap under 1s | 0.313 | 0.356 | 0.338 | NO |

Every candidate axis recoverable from this file is non-separating. The single
weak signal is health-pack mentions, which are 8x rarer in class A (1.5 percent)
than in agreement rows (12.7 percent); that is a symptom of the GRAB PACK gap
below, not a driver of the trade/hold split.

**UNMEASURED - not present in the log at any granularity.** The shadow record
schema is `ts, mode, champ, enemy_comp, deterministic, live_haiku` and nothing
else (`core/aram_coach_shadow.py:140-160`). Therefore the following requested
axes could not be measured and are NOT estimated here: self HP percent, enemy
HP percent, level, gold total, wave_pct, low_enemy_count, game time, objective
or respawn timers, and proximity to a death or a reset. Session-elapsed seconds
(above) is a weak proxy for game time and is non-separating; there is no proxy
at all for the rest. This is the single largest obstacle to closing the item and
is addressed as Step 0 below.

## Secondary findings (comparability, not agreement)

Only 2424 of 4175 non-dead rows (58.1 percent) are comparable. The 1415
det-only rows break down as:

```
  1105  native action ""            (no Haiku verdict written for that tick)
   227  "GRAB PACK"
    16  "PUSH WAVE"
    11  "GRAB LEFT PACK"
    11  "```JSON"
    10  "PUSH NEXUS"     5 "HUG TOWER"    4 "PUSH MID"    3 "PUSH INHIB"
```

1. **No pack tier.** 238 rows are a health-pack verdict. `coaches/aram_coach.py`
   lists GRAB PACK / SPRINT TO PACK as sanctioned ARAM action labels, but
   neither the 5-label ladder in `core/aram_action_rule.py:52` nor the verdict
   table in `tools/aram_shadow_report.py` has a pack concept. Adding it raises
   comparability; it does not by itself move the agreement percentage.
2. **A parse leak.** 11 rows carry the literal native action `` ```JSON ``. A
   markdown code fence reached the action field, so the Haiku JSON parser let a
   fence through on those ticks. Small, but it is a real data-quality bug and
   it is not covered by any axis above.
3. **Late-game push vocabulary.** 35 rows are PUSH NEXUS / PUSH WAVE / PUSH MID
   / PUSH INHIB, a game-phase verdict with no ladder equivalent at all.

## Concrete rule change (class (a)), NOT implemented

Ordered. Step 0 is mandatory and must land before Step 1, because without it
Step 1 cannot be verified.

**Step 0 - instrument the shadow row (makes the hypothesis falsifiable).**

- File: `core/aram_coach_shadow.py`, function `log_aram_coach`, the `record`
  dict at lines 140-160 (and the `_BLOCK_KEYS` normalisation above it).
- Change: record the three raw rule inputs alongside the two blocks -
  `hp_pct`, `wave_pct`, `low_enemy_count` - passed through from the assembler.
- Why mandatory: `wave_pct` appears nowhere in the current log, so the size of
  the wave effect is unmeasurable today. Wiring Step 1 without Step 0 produces
  a change whose delta cannot be attributed.
- Predicted agreement delta: ZERO by construction. This step measures, it does
  not fix.

**Step 1 - stop hardcoding the wave shift off.**

- File: `dashboard/_deterministic_coaching.py`, function
  `shadow_log_aram_coach`, lines 1336-1337.
- Change: `wave_pct=None` becomes a read of `coach.get("wave_pct")`, guarded
  the same way the two lines immediately above it already guard tower HP
  (`my_tower_hp = coach.get("my_tower_hp") if isinstance(coach, dict) else None`,
  line 1331).
- Thresholds: NO threshold edit anywhere. `core/aram_action_rule.py` already
  implements >65 / <35 / >=2 correctly and matches the prompt at
  `coaches/aram_coach.py:341-344` line for line. The rule is right; only its
  input is disconnected.
- Non-circularity: `wave_pct` is echoed onto the coach artifact from the VISION
  tiered reader at `coaches/aram_coach.py:791-796`, in the same four-key loop as
  `my_tower_hp` and `enemy_tower_hp`. The det assembler already reads two of
  those four keys and its own comment at lines 1327-1330 establishes exactly why
  that is non-circular: it is vision-only INPUT state, not a Haiku OUTPUT field.
  `wave_pct` inherits that argument unchanged.
- Verified available: `data/aram_coaching_data.json` currently carries
  `wave_pct = 50` as a top-level key, so `coach.get("wave_pct")` resolves today.

**Predicted agreement delta - bounded, not point-estimated.**

- Upper bound: +26.2 pp (634 of 2424 rows are one-tier mismatches, the exact
  class a one-tier shift can address), taking 0.735 to a ceiling of 0.997.
  This is a CEILING, not a forecast.
- Provable floor from the sibling `low_enemy_count` half: +2.60 pp (63 native
  all_in rows against a det side that structurally cannot emit ALL-IN).
- The realised value is UNMEASURABLE from this file. Two facts bound the risk
  downward and must be stated: (i) the live artifact currently reads
  `wave_pct = 50`, which sits inside the neutral 35-65 no-shift band, so if
  wave_pct is usually 50 the fix is inert; (ii) `data/vision_regions.json`
  contains no wave region (keys are timer, level, hp, mana, gold, kda, cs, ping,
  fps, score_blue, score_red, ally_N_hp, ally_N_mana, ally_ults, ally_levels),
  so `wave_pct` is produced only by the Sonnet vision escalation tier and never
  by OCR. It is therefore available but not free, and its live distribution is
  unknown. Step 0 exists to resolve exactly this.
- Note for the Haiku-to-ZERO objective: sourcing `wave_pct` from the vision tier
  does not reintroduce a Haiku coaching call. It does add a Sonnet vision
  dependency to the deterministic action, which is a scope decision for the
  operator, not a measurement.

**Step 2 - close the comparability gaps (optional, does not move agreement).**

- Add a pack tier to `core/aram_action_rule.py` and a pack phrase to the verdict
  table in `tools/aram_shadow_report.py`: +238 comparable rows.
- Fix the `` ```JSON `` fence leak in the ARAM Haiku response parser: 11 rows.

**Do NOT pursue.** `low_enemy_count` cannot be wired from the current coach
dict: the artifact carries `ally_1_hp .. ally_4_hp` but no enemy-HP fields
(`low_enemy_count`, `alive_enemies` and `dead_enemies` all read `None` in the
live artifact). Sourcing it needs a new vision field, so it is a larger item
than Step 1 and should not be bundled with it.

## Reproduction

Analysis scripts were written to the session scratchpad
(`...\9ca9a5d8-1bf1-435c-92b3-ade28b1dfb3f\scratchpad\s1_keys.py` through
`s10_champ.py`) and no scratch file was created inside the repository other
than this report. No git command was run and no repository file was modified.
