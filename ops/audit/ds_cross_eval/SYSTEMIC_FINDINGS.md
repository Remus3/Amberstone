# DS cross-eval - SYSTEMIC findings (cross-champion root causes)

Roster 172/172 judged. Grounded against the live engine (not agent eyeballing).
These are the engine-level D1 nominations the per-champion verdicts roll up
into. Each is Tier-2 if pursued (ENGINE bump + dual suite + Share mirror) and
must be validated per-champion vs rewind WIN outcomes BEFORE any code (gate D1
report-first). Raw rollup: REPORT.md. Per-champion: reports/ + verdicts/.

## Severity by scorer (where the defects concentrate)

| scorer | OK | MINOR | MISMATCH | mismatch% |
|---|---|---|---|---|
| ability (mage) | 1 | 47 | 5 | 9% |
| ehp (tank) | 0 | 22 | 2 | 8% |
| dps (carry) | 0 | 19 | 9 | 32% |
| hybrid (bruiser) | 0 | 27 | 16 | 37% |
| hps (enchanter) | 0 | 9 | 6 | 40% |
| burst (assassin) | 0 | 5 | 4 | 44% |

Totals: 42 MISMATCH, 129 MINOR, 1 OK. Mages + tanks are largely sound; the
defect mass is hybrid + hps + dps/burst.

## Cluster A: archetype-assignment divergence (default kit-archetype vs ARAM win-axis)

The default `get_archetype_for` routes each champ to its KIT archetype (correct
by tag/damage-axis). But rewind ARAM win-data favors a DIFFERENT build axis for
a cluster, so the scorer's whole pool misses the empirically winning build:
- hps routed but ARAM wins on AP-mage / tank: Bard, Morgana, Seraphine, Taric,
  Thresh, Zilean (Thresh/Taric actually win as TANK in ARAM, not enchanter).
- tank routed but ARAM wins on AP-mage: Malphite (Rabadon's/Sorcerer's above
  baseline; ehp pool has zero overlap), Nunu.
- mage routed but on-hit CARRY wins: Kayle (BotRK/Guinsoo/Terminus), KogMaw
  (Wit's End/Terminus); Lulu is user_cs=carry on an AP kit.
- assassin/AD routed but AP wins in ARAM: Shaco (Blackfire/Liandry), Shyvana
  (Liandry/Shojin/Riftmaker), MissFortune (burst ranks AP over AD crit).

Verified: these defaults ARE kit-correct (Malphite=tank, Shaco=assassin,
Kayle=mage). So this is a CALIBRATION judgment, not an obvious bug - ARAM is an
off-meta where AP/tank/on-hit builds outperform the kit's "intended" axis.
Nomination (report-only): per-champion ARAM archetype-override table (the
`cs_archetype_picks.json` mechanism already supports overrides; 9 user_cs exist).
Anchor each override on the ARAM win-axis, not the kit tag. Do NOT auto-flip;
operator/Gemini decides which off-meta ARAM builds DS should chase.

## Cluster B: generic marksman/AS/crit template on the AD scorers (dps/burst/hybrid)

The DPS-side emits a near-identical BotRK / Runaan's Hurricane / Kraken /
Essence Reaver / Trinity Force ranking for almost every AD champ regardless of
kit. Verified: Ezreal and Xayah both get BotRK #1, Runaan's #2, Kraken #3 byte-
identical; Nilah BotRK #1. Champion identity (caster-ADC, melee fighter,
lethality assassin) is ignored on the item axis. Empirically the template LOSES
for several: Ezreal BotRK wr 25.0 (-21 vs base), Xayah BotRK 25%, Nilah 28.6%
(vs 60 base), Senna 44.4%, Briar BotRK 37.5%, XinZhao 42.9%. The win-correlated
items (Collector, IE, LDR, Statikk, Muramana, Sundered Sky, Death's Dance) are
buried (Cluster B subsumes the pilot F1 melee-bruiser case).

Two distinct sub-defects:
- B1 (melee mis-credit): Runaan's bolts / crit-AS multi-hit get full DPS credit
  on MELEE autos (Jarvan, Renekton, Vi, Briar, all hybrid bruisers). The seed's
  exact concern, confirmed roster-wide.
- B2 (kit-agnostic item axis): caster-ADCs (Ezreal, Aphelios) and on-hit/
  lethality kits get the same crit-marksman template instead of their winning
  axis (Manamune/Trinity for Ezreal; lethality for assassins).
Refuted sub-hypothesis (tested, do NOT pursue as the fix): sort_by="efficiency"
(gold-normalized, already in hybrid.py:836) makes the bruiser staples WORSE
(Death's Dance 38->51). The defect is DPS CREDITING / candidate applicability,
not the sort key.
Nomination: champion-kit-aware DPS crediting - a melee-applicability gate on
multi-hit/crit marksman items + per-champion candidate-pool tailoring. Anchor:
the buried items are the rewind win-correlated ones.

## Cluster C: champion-specific engine bugs

- Aphelios (CONFIRMED BUG, high priority): the dps scorer returns delta 0.0 for
  EVERY item and the candidate pool collapses to Doran's starters only. His
  gun-rotation kit breaks the dps model -> the coach surfaces a useless all-
  Doran's, all-zero ranking. This is a genuine defect, not calibration. Root-
  cause the dps model's Aphelios path (likely a stat/AA-model divide-by or a
  missing base-AD path) and add a regression test. Tier-2.

## F2 (secondary): default sort_by="delta" is gold-blind at the top

Void Immolation (id 223069, 6000g ARAM-exclusive, true-dmg-off-max-HP) ranks #1
on every melee bruiser cell because raw absolute delta scales with item cost.
Real but secondary (efficiency sort drops it 1->6 but does not fix Cluster B). A
cost-aware top, or excluding the 6000g ARAM ultra from "next item" recs, is a
minor calibration. Tier-2.

## F3 (read every verdict through this): "absent" usually means "buried"

The per-champion data JSON stores only top-12 per comp cell, so judge agents
wrote "X absent from scorer pool". Full-depth probe shows staples are IN the
~124-item pool, ranked 27-58. Read "absent/missing staple" as "buried below
rank 12" unless a full-depth check confirms true absence. The substance (win-
correlated items ranked far below their win-rate) stands; the framing was top-12
limited. (Aphelios is a TRUE absence/zero - the exception.)

## Not-defects (do not file)

- hps/enchanter comp invariance: EXPECTED (ally-facing value, no enemy-resist
  surface). comp_ok=true by design.
- ARAM HP-stack staples (Warmog's, Fimbulwinter) on enchanters: ARAM mode-meta
  nuance, note only.

## Next pass (Tier-2, gated on this report, operator/Gemini scoped)

1. Aphelios dps zero-output bug (Cluster C) - clearest, fix + regression test.
2. Cluster B1 melee-applicability DPS gate (highest roster reach: 16 hybrid +
   bruiser/carry MISMATCH).
3. Cluster A ARAM archetype-override table (per-champion, override mechanism
   exists; needs the operator/Gemini off-meta-chase decision).
4. F2 gold-aware top (minor).
Validate each per-champion against rewind WIN outcomes before shipping.
