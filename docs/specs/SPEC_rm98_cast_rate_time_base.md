# RM-98 - cast-rate TIME-BASE adjudication

Status: **ADJUDICATED 2026-07-19. BUILT 2026-07-26, ENGINE 1.244.0.** Supersedes
the "SIZED, NOT ADJUDICATED" line in `docs/DS_SWEEP_TRACKER.md:144-159`.

> **Build note (2026-07-26).** The Recommendation below shipped DEFAULT-OFF as
> `apply_cast_rate_propensity_prior` in `agents/daemon_slayer/cast_propensity.py`,
> wired into `hybrid.py` ONLY. The five other consumers named under "RM-98 is
> under-scoped" are documented at the seam and deliberately NOT wired - narrow
> first, widen on test evidence.
>
> Two things the build learned that this spec does not say:
>
> 1. **The prior needs a REFERENCE propensity.** `availability * (measured /
>    availability)` is algebraically the identity. The shipped form is
>    `prior = min(1, propensity / FULL_AVAILABILITY_PROPENSITY)` with the
>    reference calibrated at 0.7191, the p90 of the roster-wide propensity
>    distribution (676 measured rows, 173 champions, L13 SR). p90 and not the
>    median, because a median reference hands half the roster a prior above full
>    availability. The reference being calibrated from the SAME table is what
>    makes the construction basis-free: a wrong denominator distorts numerator
>    and reference by one common factor, which cancels.
> 2. **24 of 676 rows measure propensity > 1.0** (Ivern R 10.98, Shaco R 5.56,
>    Riven Q 2.59) - multi-cast and pet kits fire more `spell[N]_casts` than one
>    cooldown permits. A `max(measured, ...)` floor is therefore required and is
>    provable rather than tuned (combat time is a subset of game time, so the
>    whole-game rate is a strict lower bound on the combat rate). Without it,
>    Riven Q is CUT 2.6x on the term she is 65.9% dependent on.
>
> Corollary for anyone re-reading item 2 of "Four corrections": the ability term
> is load-bearing, and the prior moves it. MEASURED L13 SR dps delta spans +1.68%
> (Riven, floor-clamped) to +39.06% (Veigar / Mordekaiser).

Question asked: is the whole-game basis of
`data/daemon_slayer/spell_cast_rates.json` a DELIBERATE modelling choice, or
an accident of reusing a convenient table?

## Verdict: NEITHER. It is a documented-but-unadjudicated inheritance.

One denominator-adjacent choice was made deliberately, recorded, and is
defensible. It was **measured vs `1/cooldown`**, not whole-game vs
combat-window. `docs/history_notes.md:12534` (s178 Findings):

> Cast rate from measured rewind data is dramatically better than
> `1/cooldown` for mage scoring. Veigar Q has 4s base cooldown -> theoretical
> 0.25 casts/sec; measured median is 0.098 casts/sec (40% of theoretical).

A combat-window denominator was **never in the option set**. It appears
nowhere in the generator, in commit `4421b8ef`, or in any s178-era doc. Its
first appearance anywhere in the repo is 2026-07 in
`docs/specs/RM39_design_C_baseline_delta.md:416-421`, as an audit finding.

The basis was inherited by shape, and the generator says so in its own words
(`scripts/build_spell_cast_rates.py:9-11`):

> Mirror of the (undocumented) s145 ad-hoc query that built
> `ult_cast_rates.json` for the Malignance Hatefog proc, generalised to the
> full Q/W/E/R surface.

There is no point in the chain where whole-game was adjudicated correct for a
DPS context. The s145 ancestor was already multiplying a whole-game rate into
a per-second combat term - `agents/daemon_slayer/ult_rates.py:5-7` describes
it as converting "ult cast frequency into a DPS-time proc rate". So the
"locally correct at origin" defence also fails.

Nothing would have caught a base swap: `test_cast_rates.py:194-197` asserts
only `0.01 < rate < 1.0`, a 100x-wide band that passes under either basis.

## The stated blocker is false and must be retracted

`project_ds_rm98_cast_rate_time_base.md:46-49` defends the basis as
"haste-inclusive by construction, which is why the RM-39/RM-43 haste
adjudication relied on it". Both halves are wrong.

**Haste-inclusiveness is a property of empiricism, not of the denominator.**
A combat-window empirical table is equally an observation of a population that
already built whatever haste it built. The generator attributes it correctly
(`build_spell_cast_rates.py:5-7`): "a **measured** cast rate already encodes
mana/cooldown downtime".

**RM-39 did not rely on it; it condemned it.**
`docs/specs/SPEC_rm39_rm43_ability_haste.md:187-192` argues the opposite and
labels that argument decisive:

> a statistic too diluted to SHOW haste is equally too diluted to have
> EMBEDDED the population-haste bias that B and C both exist to remove. That
> argument is correct and it is decisive.

RM-39 further prescribes replacing the denominator (`SPEC:174-176`,
`:198-202`, `:318-320`): "If the denominator is wrong, the fix is a better
denominator, not a correction factor layered on top." And RM-39's verdict
rests on disqualifiers 1.1 and 1.3 (call-signature and call-counting), neither
of which is whole-game dependent - per commit `cdaf500d`, "it rests on code
structure and call-counting".

The false claim entered by summarisation: three artifacts
(`project_ds_ability_haste_measured_inert.md:43-45`, `docs/LEDGER.md:51`,
`docs/history_notes.md:8356-8357`, relocated there from `WAKEUP_NOTES.md` by the
routine prune) each weld "whole-game duration" and "already
haste-inclusive" into one clause with an "and". A later summary read the
conjunction as causation.

## Four corrections to RM-98 as filed

**1. The defect is already shipped and DEFAULT-ON in three scorers.** RM-98 is
filed as a blocker on the DEFAULT-OFF `apply_ad_axis_ability_damage`. But the
identical plain sum is live in `ds.onhit` (`onhit_dps.py:143`, Slice B
2026-07-16, routed at `server.py:2107` `/rank-onhit`), whose docstring asserts
the thing that is false (`onhit_dps.py:4-5`): "into ONE combined-DPS score by
PLAIN SUM - both halves are in the same DPS units". Also live in `ds.dps`
(`dps.py:1023`, Malignance) and `ds.hps` (`hps.py:679`). Gating a default-OFF
flag on a defect that three shipped scorers already carry is incoherent.

`hybrid.py:151-153` makes the same false claim, and names the very step that
breaks additivity as its reason for additivity: "Rows are already
post-mitigation and post-cast-rate ..., so the sum is directly additive".
Post-cast-rate on a whole-game rate is exactly what makes it non-additive with
a combat-window rate.

**2. The term is NOT inert.** Tested and refuted. Per-cast damage is an order
of magnitude larger than per-second auto damage: Renekton W is 226.25
dmg/cast against a `weighted_dps` of 29.14 dmg/s, so 0.0184 casts/s still
yields 4.17 DPS. The ability term is 30.5% of Renekton's ON damage term,
29.2% cohort mean, 65.9% for Riven. It re-orders the ranked list (max
`|delta delta_pct|` 0.286 over top-20). It survives the ratio sort because it
is additive and item-dependent (`delta_A/delta_W` spans 0.000 to 0.430).
Scaling it 27x does not correct a small contribution - it inverts the scorer,
taking the ability term to 92% of the denominator.

**3. The 27x headline overstates.** Per-spell against the rotation-implied
reference: Q 7.83x, W 27.12x, E 6.44x. Characteristic distortion is ~7x; W is
the outlier. Further, the 0.5/s reference is `w: 1.5 / duration: 3` from
`scenarios.json`, and `_rotation_attack_dps` never reads the `q`/`w`/`e`/`r`
fields (`dps.py:549-566` reads only `duration`, `basic`, `basicTime`,
`numberOfTargets`). The 27x is a dimensional-error illustration, not a
discrepancy between two live engine values.

**4. RM-98 is under-scoped.** As filed it covers `hybrid.py:595` only. It does
not cover `ability_dps.py:1252` (where 6 champions - Aphelios, Katarina, Kled,
Teemo, Vayne, Vi - sum a `1/cooldown` combat-basis fallback and a whole-game
measured basis in the same total), the always-on `item_proc_dps` fold inside
`total_ability_dps` (27.9% of Veigar's total), `dps.py:1023`, `hps.py:679`, or
`onhit_dps.py:143`.

## Both fixes the RM-39 spec named are unavailable at the required fidelity

`SPEC_rm39_rm43_ability_haste.md:198-202` named two candidates and noted "A, C
and D independently converged on this and none of them sized it". Both are now
sized, from `data/rewind_history.db`:

**Candidate 1, "casts per second alive".** `participants.time_spent_dead`
exists, so this is directly computable. Measured on Renekton (130 matches,
`time_played > 600`, `spell2_casts > 0`): W whole-game median 0.02351, W
alive-time median 0.02927, dead fraction median 0.204. **Lift 1.25x** against
a 27x gap - 17.1x remains. **INADEQUATE.**

**Candidate 2, "per second within N seconds of damage dealt or taken".**
`timeline_frames` carries per-participant `total_dmg_done` / `total_dmg_taken`
(685,364 rows), but the frame cadence is 60s (measured deltas 60016-60021 ms).
A 3-10s combat window is not resolvable from 1-minute buckets. The best
achievable derivative is "minutes in which any combat occurred", far coarser
than the spec assumed. **NOT AVAILABLE at the fidelity the fix requires.**

## Recommendation

Do not pursue a denominator replacement. The data cannot support one, and a
correction factor is explicitly ruled out by RM-39.

Take the other half of `SPEC:198-202`, which survives this feasibility
finding intact: demote the measured rate **from a DPS multiplier to a
cast-propensity prior**. A prior needs correct relative ordering across spells
and champions, which the whole-game basis does preserve; it does not need a
correct denominator. This also protects the signal RM-39 flagged as
must-not-discard (`SPEC:203-205`): Aatrox W sits at 17.6% of theoretical
because Infernal Chains is genuinely cast less often than available, and a
cooldown-inverse model throws that away.

Sequencing consequence: `apply_ad_axis_ability_damage` default-ON should no
longer be gated on RM-98's original framing, because that framing rested on a
retracted premise and on a blocker three shipped scorers already carry. The
flip remains operator-gated and is NOT recommended here on its own merits -
that is a separate decision, and item 2 above (the term is load-bearing at
29.2% cohort mean) is the material input to it.

## Follow-on work filed

- Correct the three artifacts carrying the haste conjunction.
- Correct the two false additivity docstrings (`onhit_dps.py:4-5`,
  `hybrid.py:151-153`).
- Re-scope RM-98 to all consumers, or split per consumer.
- Untested hypothesis, flagged as such: the recorded "Liandry's #1 /
  Blackfire #2 for all seven mages" invariance
  (`DS_SWEEP_TRACKER.md:186-194`) is consistent with always-on item DPS
  entering `_rank_mage.py:332` at full combat weight while the spell rows it
  competes against enter at whole-game weight. If so, that invariance is
  partly an artifact of this defect. Needs its own experiment.
- `spell_cast_rates.json` `note` carries a literal em-dash (generated
  2026-05-12, predating the 2026-05-18 ASCII purge; the generator now emits a
  hyphen, so the file has not been regenerated since).
