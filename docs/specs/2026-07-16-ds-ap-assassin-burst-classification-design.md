# DS AP-axis kit sweep - Slice A: AP-assassin burst classification

- Date: 2026-07-16
- Status: APPROVED design (pre-implementation)
- Author: brainstorming session (DS meta-valuation sweep lane)
- Tier: RC-side core change (full `tests/` suite + live `/api/build-plan` validation + RC reload). NO ENGINE bump / NO Share mirror / NO DS `:8893` restart - the DS engine is unchanged.

## 1. Problem

The DS default build reco is kit-blind on the AP axis. Every AP champion is
routed to the sustained-ability (`ds.ability`) scorer, which - against the
tanky mode-level-curve target (armor ~105, HP ~2430 at level 13) - leads a
near-uniform DoT / anti-tank core (`Liandry's Torment > Blackfire Torch >
Cryptbloom > Rabadon's > Shadowflame > Void Staff`) for burst mages, on-hit AP,
and AP assassins alike. This is the AP analog of the AD kit-blindness that
OQ23-25 fixed (LEDGER 875/885/886).

Live evidence (probed 2026-07-16 via `POST /api/build-plan {champion, mode:"SR",
level:13}`):

| Champ    | Kit         | DS default lead (scorer)                                   |
|----------|-------------|-----------------------------------------------------------|
| Akali    | AP assassin | `Liandry's > Blackfire > Rabadon's > Cryptbloom ...` (ability) |
| Ekko     | AP assassin | `Liandry's > Blackfire > Cryptbloom > Rabadon's ...` (ability) |
| Fizz     | AP assassin | `Liandry's > Blackfire > Rabadon's > Cryptbloom ...` (ability) |
| Katarina | AP assassin | `Liandry's > Blackfire > Cryptbloom > Stormsurge ...` (ability) |
| Qiyana   | AD assassin | `Lord Dominik's > Essence Reaver > Axiom Arc ...` (burst)  |

Qiyana is the only assassin reaching the burst scorer - because she is AD.

## 2. Scope

- **Slice A (THIS spec):** AP-assassin burst classification. Route AP burst
  assassins to the existing, already-AP-capable `ds.burst` scorer instead of
  the sustained `ds.ability` scorer.
- **Slice B (outlined in section 7, deferred):** on-hit AP (Nashor's Tooth)
  valuation. Separate, harder - needs a new scorer term, not a reroute.
- **Out of scope:** ranged burst mages (Syndra/Xerath leading Liandry's are
  correctly `mage`-classified; whether the ability scorer needs a burst mode is
  a distinct question). Zhonya's Hourglass ("back off for cooldowns") is a
  defensive-slot buy the pure-damage burst scorer will not surface - a separate
  defensive-item concern.

## 3. Root cause (validated)

The default archetype resolver mis-classifies AP assassins:

- `dashboard/routes_state.py:590` resolves the default archetype via
  `core.archetype_picks.get_archetype_for(champion)["primary"]`.
- `core/archetype_picks.default_for_champion` (line 429) applies
  `axis_correct_archetype` (line 282). `_ARCHETYPE_AXIS` (line 132) tags
  `assassin` as an **AD-axis** archetype, and `_AP_AXIS_ARCHETYPE = "mage"`
  (line 139). So any AP kit whose tag-derived primary is `assassin` is
  force-collapsed to `mage` (line 293-294) - and lands on `ds.ability`.
- The P6 axis-correction was built to stop AP kits from reaching AD scorers
  (e.g. Fighter-tagged Gwen -> bruiser -> AD). It over-reached: it assumed the
  `ds.burst` (assassin) scorer is AD-only. It is not - `agents/daemon_slayer/
  burst.py` docstring: the burst window flows the full AP amp pipeline
  (Rabadon's, Liandry's, Riftmaker HP->AP) "so a Diana or Akali build registers
  their AP amplification."

**Validation - the burst scorer serves AP correctly.** Forcing
`archetype=assassin` via `POST /api/ds-preview` (probed 2026-07-16):

| Champ    | Forced `assassin` build (burst scorer)                          |
|----------|-----------------------------------------------------------------|
| Akali    | `Void Staff > Rabadon's > Lich Bane > Shadowflame > LDR > BORK`  |
| Diana    | `Void Staff > Lich Bane > Rabadon's > Shadowflame > Mejai's ...` |
| Ekko     | `Lich Bane > Rabadon's > Void Staff > Mejai's > Shadowflame ...` |
| Katarina | `Rabadon's > Lich Bane > Void Staff > BORK > Mejai's ...`        |
| LeBlanc  | `Void Staff > Rabadon's > Shadowflame > Mejai's > Stormsurge ...`|
| Fizz     | `Lich Bane > Rabadon's > Void Staff > BORK > Mejai's ...`        |

AP burst core (Rabadon's / Void Staff / Lich Bane / Shadowflame) replaces the
wrong sustained DoT. Residual AD artifacts (BORK / LDR) leak mid-pack - see 5.4.

## 4. Why a curated override, not the axis tweak I first pitched

The initial pitch ("make `assassin` axis-neutral") is wrong on two counts:

1. **Pyke regression.** Pyke is tagged `["Support","Assassin"]` with an AD kit.
   Today `enchanter` (from Support) is corrected to `assassin` via the AD-kit
   branch (line 296-299: prefer an AD secondary tag). That branch keys on
   `_ARCHETYPE_AXIS["assassin"] == "ad"`. Making assassin axis-neutral breaks
   it - Pyke would fall to `carry`.
2. **DDragon tags do not separate burst-AP from sustained-AP.** LeBlanc is
   tagged `["Mage","Assassin"]` (Mage first) - she is classified `mage`
   directly, never via the correction, so a "fix the correction" approach
   misses her. Cassiopeia (`["Mage"]`, sustained DoT) must STAY mage. No
   heuristic over available data cleanly splits these.

A curated AP-assassin override set is the idiomatic RC mechanism (mirrors
`core/cc_threat.py`'s hard-CC roster from C6 / LEDGER 909, and the existing
`aram_archetype_override.json` seam). It is explicit, controllable, covers the
tag-ambiguous cases, and touches only the default - operator picks still win.

## 5. Slice A design

### 5.1 Mechanism

Add a curated `_AP_ASSASSIN` override set to `core/archetype_picks.py`. In
`default_for_champion`, AFTER the tag + axis-correction step, if the champion is
in the set, force `primary = "assassin"` and demote the tag-derived primary to
`secondary` (so the operator can flip back in one tap). The override is applied
only for `source == default` - an explicit operator pick (`get_archetype_for`
returns early on a persisted pick, line 621) is never touched.

### 5.2 Champion set (seed + per-champ validate)

Seed (validated live in section 3): `Akali, Ekko, Fizz, Katarina, LeBlanc,
Diana`. During implementation, evaluate and decide per-champ (probe forced-
assassin vs meta, keep only genuine improvements):

- Candidates to evaluate: `Kassadin` (scaling AP - may prefer sustained),
  `Vex` (burst mage, likely mage not assassin), `Naafiri` (AD - excluded),
  `Sylas` (AP bruiser - likely bruiser), `Kennen` (AP marksman - excluded),
  `Elise/Nidalee` (situational).
- Borderline (validate, may keep as mage/bruiser): `Diana` and `Katarina` blur
  into sustain/bruiser; keep only if the forced-assassin build reads better than
  their current default AND matches how they itemize.

### 5.3 Controls (MUST NOT change)

- AD assassins stay `assassin`: `Qiyana, Zed, Talon, Naafiri`.
- Sustained AP mages stay `mage`: `Syndra, Xerath, Cassiopeia, Vladimir, Vex`.
- Pyke stays `assassin` via the untouched AD-kit correction branch.
- On-hit AP stays as-is in Slice A (Slice B owns it): `Gwen, Kayle`.

### 5.4 Residual / optional (defer unless trivial)

- **AD-artifact coherence filter.** BORK / Lord Dominik's leak mid-pack on
  AP-assassin burst builds (same cross-archetype-artifact class the AD path
  had). A candidate-pool AP/AD coherence gate on the burst scorer would clean
  it. Defer to a follow-up; Slice A is a net win without it.
- **Per-champ combo templates.** `ds.burst` uses the default combo
  `(Q,W,E,AA,R,AA)`; per-champ templates (Akali R1->R2, Fizz E-Q-R) are burst.py
  Phase 5.5 and improve accuracy but are not required - the default-combo builds
  in section 3 are already sensible.

### 5.5 Data flow (unchanged infra)

`default_for_champion` (curated override) -> `get_archetype_for` ->
`routes_state._serve_ds_preview_post` -> `core.daemon_slayer_client.
rank_for_primary_archetype(archetype="assassin")` -> POST `/rank-assassin` to
`:8893` `ds.burst`. The engine already serves this route; no engine edit.

### 5.6 Tests (RED-first, TDD)

- Characterization / regression in `tests/` (or `core` test dir) covering
  `default_for_champion` / `get_archetype_for`:
  - Each seed champ: `primary == "assassin"`, `secondary` = the demoted tag
    primary. (RED today: Akali resolves to `mage`.)
  - Controls unchanged: Qiyana/Zed -> assassin; Syndra/Cassiopeia -> mage;
    Pyke -> assassin; Gwen/Kayle -> mage.
  - Operator pick still wins: a persisted `mage` pick on Akali is not overridden.
  - Override-set membership is the single source (no duplication with tags).
- Optional integration smoke: `/api/build-plan` for a seed champ returns
  `scorer == "burst"` and an AP-led build (assert scorer + AP presence, not a
  brittle exact-item list).

### 5.7 Verification + release

- Run the full RC `tests/` suite once (blast radius: many champ default
  classifications) + the archetype_picks tests. Trust exit code (R6).
- Live-validate via `/api/build-plan` probes on the seed set + 2-3 controls.
- Reload RC via `restart_trigger.txt`; confirm `health.json` new pid + alive.
- NO ENGINE_VERSION bump, NO Share mirror stage, NO DS `:8893` restart - the
  `agents/daemon_slayer/` engine is byte-unchanged. This matches the C4 caller-
  default-flip precedent (RC-side + RC reload only).
- LEDGER entry (newest-first) + docs sync per the DS-batch docs rule.

## 6. Risks

- **Tag/roster drift.** New AP-assassin releases need a roster add. Guard with a
  test that the seed set resolves to assassin; a patch-refresh reviewer note.
- **Borderline champs.** Diana/Katarina/Kassadin may read better as bruiser/mage;
  resolved by per-champ validation in 5.2, and the operator CS-picker override is
  always available.
- **Over-routing a sustained AP champ to burst** would under-value waveclear /
  sustained poke. Mitigated by the curated (not heuristic) set + controls.

## 7. Slice B outline (deferred - own spec later)

On-hit AP (Nashor's Tooth) for AS-scaling AP kits (Gwen, Kayle, Kog'Maw-AP).
Validated NOT fixable by reroute: forcing Gwen to `bruiser` yielded an AD build
(`BORK > Trinity > Heartsteel > Kraken ...`) with still no Nashor's; Kayle ->
bruiser yielded a tanky-AP mix. Nashor's / on-hit AP DPS is unmodeled across all
six scorers. Slice B needs a genuine on-hit-AP DPS term (AP + attack-speed +
on-hit magic, with ability-proc scaling) - a scorer enhancement (likely engine-
side, so Tier-2 with ENGINE bump + Share), designed after Slice A lands and is
validated.
