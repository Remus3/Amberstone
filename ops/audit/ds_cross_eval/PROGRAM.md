# DS comprehensive per-champion scorer cross-eval - PROGRAM CONTRACT

Durable contract for the multi-session, one-agent-per-champion DS scorer audit.
Read this first every session (it survives /clear). Operator directive:
memory `project_ds_comprehensive_cross_eval`. Seed:
`ops/audit/DS_BRUISER_DAMAGE_TYPE_2026-06-16.md`.

## Gate (Gemini operator-proxy LOCKED 2026-06-16, all CONFIRM)

- D1 DELIVERABLE = report-first. Per-champion mismatch/calibration report that
  NOMINATES a ranked weight-retune shortlist. NO blind global retune. Any actual
  weight/scorer change is a later Tier-2 pass (ENGINE bump + dual suite + Share
  mirror sync) gated on this report.
- D2 ANCHOR = rewind_history.db WIN outcomes, mode-segregated. Per champion:
  operator-self n>=8 -> tier `outcome_self`; elif all-player n>=8 ->
  `outcome_all`; else `synthetic` (scenario grid only). Tag every verdict.
- D3 RUNES = self-rune procs ONLY, on burst/assassin champs (the only path
  rune_procs.py feeds: burst.py/combo.py). Enemy + ally runes have ZERO DS
  scorer surface (coach Haiku text only) -> OUT of this program; modeling them
  is net-new Tier-2 engine work -> BACKLOG, do not block the roster sweep.
- RISK (honor) = ARAM data skew (2081 ARAM vs 652 SR in rewind). Anchor is
  mode-SEGREGATED and the scorer call is mode-MATCHED (scorer applies ARAM
  modifiers when mode=ARAM), so ARAM win rates are never compared to an
  SR-stat baseline.

## Ground truth (verified, file:line)

- Scorer invocation: `core/daemon_slayer_client.py:887 rank_for_primary_archetype`
  (posts to DS :8893). Archetype source: `core/archetype_picks.get_archetype_for`
  (axis-rebased default; 9 user_cs overrides). Keyspace = canonical DDragon id
  via `canonical_champion_id` (DB `FiddleSticks` vs DDragon `Fiddlesticks` =
  the one case-mismatch; resolve case-insensitively).
- Anchor DB: `data/rewind_history.db` participants (win, champion_name, item0-6,
  rune_keystone_id). 2941 matches: ARAM 2081, CLASSIC(SR) 652, CHERRY 154.
  172 champs. Operator self = `riot_id_game_name='SamplePlayer'` (taglines
  Vayne old + Trist new).
- Roster: 172 (DDragon 16.12.1). Scorer split: hybrid 43, ability(mage) 53,
  dps 28, ehp(tank) 24, hps(enchanter) 15, burst(assassin) 9.

## Harness (deterministic, proven; agents do NOT recompute)

- `tools/ds_cross_eval/probe_champion.py <Champion>` -> `data/<canon>.json`.
- `tools/ds_cross_eval/run_all.py` -> all 172 (21.6s, 0 fail). RE-RUN only on a
  DS ENGINE bump / patch refresh.
- Per-champion JSON fields: archetype{primary,secondary,source}, scorer,
  anchor_mode, evidence_tier{ARAM,SR}, comp_grid (5 cells, top-12 each),
  responsiveness{primary_axis, comp_blind, enemy_damage_type, target_resist}
  (rank-shift full-40-deep; EHP scorers test enemy damage type, DPS/burst test
  target resist), rune_relevant, empirical{ARAM,SR}x{self,all}{n,wr,items[]}.

## Per-champion JUDGE agent rubric (one agent per champion)

INPUT: read ONLY `data/<canon>.json` (ground truth - never invent numbers).
DECIDE 4 axes, then severity + nomination:

1. archetype_ok: does scorer axis (carry/bruiser/assassin=AD, mage/enchanter=AP,
   tank=neutral) match the kit AND the empirical above-baseline-winrate builds?
   Flag if the scorer itemizes the wrong damage axis vs what wins.
2. comp_ok: ehp/hybrid -> enemy_damage_type axis must move (comp_blind=True is a
   DEFECT candidate). dps/burst/ability/mage -> target_resist axis should move
   vs tanky. hps/enchanter -> comp invariance is EXPECTED (NOT a defect; comp is
   ally-value, no scorer surface) -> comp_ok=true by design.
3. outcome_ok: overlap scorer top-8 items vs empirical items with wr ABOVE the
   champ baseline wr (win-correlated). Flag if scorer top items are empirically
   LOSING/absent, or a high-wr staple is missing from the scorer pool.
4. rune_ok: rune_relevant only (burst/assassin). Note self-keystone wiring;
   non-burst -> n/a.

OUTPUT (both, atomic):
- `reports/<canon>.md` - human report: verdict line + the 4-axis reasoning +
  the specific items driving each flag (cite ranks/wr from the JSON) +
  nominated retune (or "none").
- `verdicts/<canon>.json`:
  {champion, scorer, evidence_tier_aram, archetype_ok, comp_ok, outcome_ok,
   rune_ok, severity (OK|MINOR|MISMATCH), nominated_retune (str|null),
   headline (<=140 chars)}
Severity: MISMATCH = a wrong-axis or empirically-losing top build, or a real
comp-blind EHP scorer. MINOR = pool gap / missing staple / weak responsiveness.
OK = aligned. Lint/py_compile any code touched (agents must not break CI).

## Coverage ledger

`verdicts/` holds one JSON per judged champion. Coverage = count(verdicts) / 172.
Aggregate with the roster scan; the D1 report ranks all MISMATCH+MINOR
nominations. Running count reported each session.

## Pre-seeded high-signal cohorts (from the roster aggregate)

- COMP-BLIND EHP/hybrid (n=10, prime defect candidates): Aatrox, Ambessa,
  Camille, Gnar, Kled, LeeSin, MonkeyKing, Riven, Udyr, Yasuo (all melee
  fighters; hybrid top-40 does not move with enemy damage type).
- RUNE-relevant (n=9 burst/assassin): the D3 self-rune cohort.
- ARCH user_cs overrides (n=9): operator-set primaries (trust over default).
