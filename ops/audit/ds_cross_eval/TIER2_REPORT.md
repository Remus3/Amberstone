# DS Tier-2 Scorer-Calibration - Report-First Validation

_2026-06-18. REPORT-FIRST GATE: this records the per-champion rewind-WIN evidence
for the three Tier-2 nominations in `SYSTEMIC_FINDINGS.md`. NO engine change is
made here. Any actual Tier-2 lift (ENGINE bump + dual suite + Share mirror)
stays gated on the `verifier` subagent re-confirming this evidence + an operator
go on the off-meta product calls._

Engine live at audit time: 1.140.0 / patch 16.12.1. Data: `data/rewind_history.db`
(2941 matches; ARAM n via `matches.game_mode='ARAM'` = 2081). Item id->name via
`data/daemon_slayer/16.11.1/items.json`. All 8 spot-checked cross-eval per-item
WR figures reproduced exactly against rewind, so `SYSTEMIC_FINDINGS.md` + the
verdict JSONs are accurate source data.

## Key upstream discovery (changes nomination A's shape)

The ARAM archetype-override mechanism is ALREADY BUILT, default-OFF:
`core/aram_archetype_override.json` (6-champion table) consumed by
`core/archetype_picks.py:628` via the `prefer_aram_win_axis=False` seam. Its
builder (`min_item_n=8`, `wr_margin=3.0`) already pruned the SYSTEMIC-named
cluster from ~14 champs to 6 and skipped Lulu/MissFortune as user-picks. So A is
a FLIP of an existing flag, not a greenfield table - and the empirical filtering
already happened.

## (A) ARAM archetype-override - WEAK except Shaco

Decisive test = within-champion WR of builds carrying >=2 override-axis items vs
builds without (the cleanest counterfactual), not raw per-item WR (which only
says "this item wins for this champ", not "the override axis beats the kit axis").

| champion | n | wr% | kit archetype | proposed | within-champ delta (ovr vs other) | in JSON | verdict |
|---|---|---|---|---|---|---|---|
| Shaco | 124 | 52.4 | assassin | mage/AP | +26.9pp (88 vs 36) | YES | CONFIRM |
| Zilean | 125 | 52.8 | enchanter | mage/AP | +11.2pp (other n=14 noise) | YES | INCONCLUSIVE-lean-CONFIRM |
| KogMaw | 148 | 42.6 | mage | on-hit | +8.3pp (champ wr <50) | YES | INCONCLUSIVE |
| Kayle | 143 | 53.8 | mage | on-hit | -5.4pp | YES | REFUTE/INCONCLUSIVE |
| Shyvana | 45 | 62.2 | bruiser | mage/AP | -20.7pp (n=45) | YES | INCONCLUSIVE (small n) |
| Taric | 36 | 58.3 | enchanter | tank | -46.9pp (other n=4) | YES | INCONCLUSIVE (small n) |
| Malphite | 180 | 46.7 | tank | mage/AP | -2.1pp (clean 92/88) | NO | REFUTE |
| Morgana | 250 | 52.0 | enchanter | mage/AP | -37.9pp (AP universal) | NO | REFUTE |
| Seraphine | 136 | 56.6 | enchanter | mage/AP | +0.8pp flat | NO | REFUTE/INCONCLUSIVE |
| Thresh | 242 | 51.7 | enchanter | tank | +0.4pp flat | NO | REFUTE |
| Bard | 98 | 54.1 | enchanter | mage/AP | +3.0pp noise | NO | INCONCLUSIVE |
| Nunu | 87 | 40.2 | tank | mage/AP | -6.1pp | NO | REFUTE |

Only Shaco has decisive WIN evidence: AP-build WR 60.2% vs non-AP 33.3% (+26.9pp,
n=88 vs 36); win-game AP-adoption 86% vs loss 66%; Blackfire 65.1% (n43) /
Liandry 62.3% (n77) vs AD Collector 36.0% (n25). The other 5 already-in-JSON
champs are INCONCLUSIVE (the override axis is the universally-played build, so
there is no counterfactual showing it beats the kit axis; several have champ
wr <53). The 6 builder-dropped champs REFUTE or are flat.

RECOMMENDATION (A): leave `prefer_aram_win_axis` default-OFF. The one defensible
narrow move is a Shaco-only enable, which is exactly the SYSTEMIC off-meta-chase
decision the operator/Gemini already flagged as a product call (NOT an auto-flip,
and a coach-affecting flip = do-not-flip-blind, validate on a live ARAM first).

## (B) champion-kit-aware DPS crediting - STRONGEST, actionable

Structural symptom confirmed: `dps.py`/`hybrid.py` have NO melee/attack_range
gate, so Runaan's bolts + crit-AS get full DPS credit on melee autos (B1 is real).
Winning ARAM builds (top items in WIN games, boots/Poro-Snax excluded) diverge
sharply from the alleged BotRK/Runaan's/Kraken template:

| champion | range | melee | n | wr% | actual WINNING build | defect | verdict |
|---|---|---|---|---|---|---|---|
| Ezreal | 550 | no | 274 | 48.5 | Muramana / Trinity Force / Serylda's | B2 caster-ADC axis | CONFIRM |
| Xayah | 525 | no | 195 | 47.2 | Navori / IE / Collector (crit) | B2 crit not on-hit | CONFIRM |
| Nilah | 225 | short | 83 | 54.2 | Collector / IE / Navori | B1+B2 | CONFIRM |
| Senna | 600 | no | 207 | 51.7 | Collector / Muramana / RFC | B2 | CONFIRM (weaker) |
| Briar | 125 | YES | 38 | 52.6 | Sundered Sky / Spirit Visage / Death's Dance | B1 melee | CONFIRM (small n) |
| XinZhao | 175 | YES | 83 | 48.2 | Sundered Sky / Eclipse / Death's Dance | B1 melee | CONFIRM |

B1 (melee-applicability gate) is the highest-reach, lowest-ambiguity fix: it is
structurally confirmed (no range gate exists) AND WIN-backed (Briar/XinZhao win
on bruiser items, never the mis-credited Runaan's/crit-AS template). B2
(kit-agnostic AD item axis) is WIN-backed by Ezreal (Muramana/TF) + Xayah/Nilah
(crit). This nomination has enough WIN evidence to justify a Tier-2 change.

## (F2) gold-aware top - confirmed behavioral, minor

`rank.py:530` defaults `sort_by="delta"` (absolute DPS/EHP gained, scales with
cost), so Void Immolation (id 223069, 6000g ARAM-exclusive) sits at RANK 1 in all
5 comp cells for 66 champions (concentrated on hybrid/bruiser + ehp/tank scorers
where 6000g absolute d_ehp dominates). Most distorted: melee bruisers/tanks
(Garen, Darius, Aatrox, Nasus, Hecarim, Mundo, KSante, Malphite, Leona). A
cost-aware top or excluding the 6000g ARAM ultra is a valid minor calibration; no
WIN gate needed (it is a ranking-surface artifact, not a build-correctness claim).

## Disposition

| nom | WIN evidence | next step |
|---|---|---|
| B (kit-aware DPS, B1 melee-gate) | YES, strongest | BACKLOG -> a future Tier-2 slice: add an attack_range/melee gate in `dps.py`/`hybrid.py` so Runaan's/crit-AS are not credited on melee autos. Gated on verifier re-confirm + per-champion re-rank validation. |
| F2 (gold-aware top) | behavioral, no WIN gate | BACKLOG -> minor: a cost-aware top or exclude the 6000g ARAM ultra in the `sort_by="delta"` surface. |
| A (ARAM override) | only Shaco | leave default-OFF; a Shaco-only enable is an operator off-meta product call (do-not-flip-blind). |

No engine change made in this report. The B1 melee-gate is the single
highest-value follow-on; it stays a gated Tier-2 slice (ENGINE bump + dual suite
+ Share mirror + DS restart + verifier CONFIRM), not an in-this-loop edit.
