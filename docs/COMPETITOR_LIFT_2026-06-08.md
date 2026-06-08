# Competitor Lift Review - 2026-06-08 (LIFT1)

**Scope:** Operator-queued deep-dive lift review (headless-upgrade Section 7b) of 3 tools:
1. https://seb16120.github.io/LoL-Target-Vs-Opponent-What-stat-to-buy/ - target-vs-opponent "what stat to buy" advisor
2. https://simulator-tool-r.invalid/ - LoL damage/combat simulator
3. https://www.reddit.com/r/simulator-tool-r/ - community context for #2

**Method:** 2 heavyweight general-purpose research agents (one per primary target; #3 folded into #2 as community context), each applying the 6-point depth checklist per finding (WHAT / HOW / HAVE-grep-RC-cite-file / WHERE / EFFORT+RISK / LIFT verdict). Every load-bearing HAVE/WHERE claim was re-verified live against the RC tree before publishing (see "Premise verification" below). Lift policy: re-implement in RC's own code only, never vendor.

## Bottom line

RC already supersedes all three targets. NO finding is HIGH-lift + LOW-risk, so per the ACT gate (MED/LOW always defer) this cycle ships NO in-run code slice - it is a research + triage result. simulator tool R's entire surface (sequential combo, two-champ head-to-head, DPS/TTK, EHP, build-sorting, free sandbox) was already lifted into RC by the prior `docs/COMPETITOR_LIFT_2026-05-30.md` calc.gg work and is live across `agents/daemon_slayer/{combo,matchup,dps,fight_report}.py` + their `:8893` routes + `web/js/panels/ds_combo.js` / `ds_matchup.js`. The stat advisor is a manual-entry defensive EHP calculator that RC's `agents/daemon_slayer/ehp.py` + `core/defensive_picks.py` + the live `cc_blended_ehp_threat` panel already beat AUTOMATICALLY from live state. Two genuine FUTURE gaps recorded to BACKLOG; neither is NOW-actionable.

## Triage summary

| ID | Tool | Finding | Lift | Triage |
|---|---|---|---|---|
| T1-F1 | Stat advisor | League resist -> damage-taken curve | LOW | CLOSED (identical to shipped) |
| T1-F2 | Stat advisor | Per-type + blended EHP | LOW | CLOSED (RC superior) |
| T1-F3 | Stat advisor | Enemy-pen-aware effective resists | MED | FUTURE (engine schema lift) |
| T1-F4 | Stat advisor | Per-unit-stat EHP/gold buy verdict | MED | FUTURE (depends on T1-F3) |
| T1-F5 | Stat advisor | Damage-taken bars + stat gold-value | LOW | CLOSED (near-dup panel) |
| T2-F1 | simulator tool R | Sequential combo / action queue | LOW | CLOSED (calc.gg lift 05-30) |
| T2-F2 | simulator tool R | Two-champ 1v1 head-to-head | LOW | CLOSED (matchup.py) |
| T2-F3 | simulator tool R | Sustained DPS + time-to-kill | LOW | FUTURE (TTK headline nicety) |
| T2-F4 | simulator tool R | Rune/keystone feeding combo surface | MED | FUTURE (route+panel wire-up) |
| T2-F5 | simulator tool R | Free sandbox input | LOW | CLOSED (parity) |
| T2-F6 | simulator tool R | Build sorting by TTK/DPS | LOW | CLOSED (RC exceeds) |

**NOW-actionable:** none.
**FUTURE (recorded to BACKLOG):** T1-F3 (pen-aware EHP), T2-F4 (rune-threaded combo surface). Minor/optional: T2-F3 (TTK headline), T1-F4 (per-stat EHP/gold).
**CLOSED (RC parity or superior):** T1-F1, T1-F2, T1-F5, T2-F1, T2-F2, T2-F5, T2-F6.

---

## Tool 1: Target-Vs-Opponent Stat Advisor
**URL:** https://seb16120.github.io/LoL-Target-Vs-Opponent-What-stat-to-buy/

**Summary:** Despite the repo name implying an attacker-side "what pen/AD/AP to buy" advisor, the live tool (V0.7) is a DEFENSIVE EHP calculator. The user manually types their own champ's defensive stats (HP, armor, natural armor, MR, bonus HP) plus the enemy's full offensive profile (damage-type split, raw AD/AP/true, lethality, flat/% armor pen, bonus-armor-pen, armor shred, Black Cleaver shred, LDR, flat/% magic pen, magic shred), and it computes effective resists after penetration, per-type and blended EHP, damage-taken bars, EHP-per-gold for +1 HP / +1 Armor / +1 MR, and a one-line "Acheter: HP|Armor|MR" verdict. 100% client-side (one `app.js`, no CDN script, no network calls, NO embedded champion/item data - every number is hand-entered).

#### T1-F1 - League resist -> damage-taken curve
- WHAT: `dmgMult(resist)` = `resist>=0 ? 100/(100+resist) : 2 - 100/(100-resist)`.
- HOW: Byte-exact standard League armor/MR curve with the negative-resist amplification branch.
- HAVE: YES, identical. `agents/daemon_slayer/ehp.py` and `agents/daemon_slayer/dps.py` both implement `100/(100+R)` positive / `2 - 100/(100-R)` negative; parametrized boundary tests in `agents/daemon_slayer/tests/test_dps.py`.
- WHERE: N/A - already engine-core.
- EFFORT+RISK: None.
- LIFT: LOW - exact duplicate of shipped math.
- **Triage:** CLOSED (have, identical).

#### T1-F2 - Per-type + blended EHP from an enemy damage-type split
- WHAT: Armor-EHP, Magic-EHP, True-EHP, then a damage-share-weighted blend (`pPhys*physTaken + pMagic*magicTaken + pTrue*1`, shares normalized), EHP = TotalHP / weighted.
- HOW: Weighted blend; pre-resist multipliers (Exhaust, flat reductions, LDR amp) multiply separately from the resist curve.
- HAVE: YES, deeper. `agents/daemon_slayer/ehp.py` (`physical_ehp`/`magical_ehp`/`true_ehp`/`blended_ehp`, blend weighted by enemy AD/AP share in `compute_ehp`). RC also layers shields, heals, lifesteal, ARAM dmg-taken/tenacity, CC discount, revive, survival-window - none modeled by the competitor.
- WHERE: N/A.
- EFFORT+RISK: None.
- LIFT: LOW - RC strictly supersedes.
- **Triage:** CLOSED (have, superior).

#### T1-F3 - Ordered enemy-penetration pipeline folded into the tank's effective resists
- WHAT: `effectiveArmor()` applies, in order: flat armor reduction -> % shred (capped 99%) -> bonus-armor-pen (bonus armor only) -> general %pen (multiplicative, LDR combined) -> lethality (flat, post-%). `effectiveMR()`: flat reduction -> %shred -> %pen -> flat magic pen. Splits natural vs bonus armor so bonus-only pen is correct.
- HOW: `combinePercentMultiplicative = 1 - prod(1 - clamp(v,0,0.99))`; `splitArmorAfterFlatReduction` separates natural/bonus; lethality and flat magic pen subtract last.
- HAVE: PARTIAL / NO at the EHP-math layer. `agents/daemon_slayer/ehp.py` explicitly lists "Caster-side enemy pen/reduction (Black Cleaver shred ON the tank, Void Staff %MR pen ON the tank) - needs enemy build plumbing" as a deliberate Phase-1 omission; `compute_ehp` has NO lethality/armor-pen/shred kwargs. RC DOES detect enemy lethality/armor-pen stacking but only at the THREAT-SCORING layer (`core/defensive_picks.py`), never to produce a post-pen effective-resist number.
- WHERE: Engine math - optional `enemy_lethality`/`enemy_armor_pen_pct`/`enemy_shred_pct`/`enemy_magic_pen*` kwargs on `compute_ehp` feeding a new `_effective_resist_after_pen()` before `_armor_factor`. Enemy item IDs already plumbed via `defensive_picks.py`.
- EFFORT+RISK: MED. No Riot/Claude dep, no new data source, but it IS an engine-math schema lift on a core scorer with a WIDE test blast radius (every EHP test pins byte-identical output; new kwargs must default to current no-pen behavior). Re-litigates a documented deliberate omission.
- LIFT: MED - real capability gap, but NEW MATH on the deepest scorer, not presentation.
- **Triage:** FUTURE (the one genuine differentiator; opt-in engine extension, not a NOW UI win; matches the ehp.py stated deferral).

#### T1-F4 - Marginal EHP-per-gold for +1 HP vs +1 Armor vs +1 MR, with a buy verdict
- WHAT: Recomputes EHP at +1 bonus HP / +1 armor / +1 MR; divides each gain by a per-unit gold cost (HP 2.6667g, armor 20g, MR 20g); sorts; prints "Acheter: <stat>" plus the gap to 2nd.
- HOW: Finite-difference marginal EHP/gold on three pure stats.
- HAVE: PARTIAL. RC has whole-ITEM gold efficiency (`agents/daemon_slayer/rank.py` `dps_per_gold`, `rank_items_by_ehp()` in ehp.py) but NO per-unit-STAT gold comparison and no per-stat gold constants anywhere in core/ or the engine. RC answers "buy Randuin's next", not "your next gold is better in armor than MR".
- WHERE: Presentation/route layer - a small pure helper (e.g. in `core/defensive_picks.py`) calling `compute_ehp` three times with a +1-stat override / 3 gold constants. No engine change if a thin override wrapper is used.
- EFFORT+RISK: LOW-MED. Reuses `compute_ehp`; only new inputs are 3 standard gold-per-stat constants. `compute_ehp` lacks stat-override kwargs today, so it needs a thin perturbation wrapper.
- LIFT: MED - low-risk but lower coaching value than RC's existing item-level recommender (players buy items, not raw stat points), and it leans on the same un-penetrated resists as T1-F3 so the verdict can mislead vs a lethality-stacked enemy.
- **Triage:** FUTURE (secondary readout; defer until/unless T1-F3 pen-aware resists land).

#### T1-F5 - Stat-to-gold value heuristic + damage-taken bars + net-modifier readout
- WHAT: `statGoldValue`, `effectiveGoldValue`, physical/magic/true damage-taken % bars, net phys/magic modifier.
- HOW: Pure display re-composition of EHP intermediates; bar width % = clamp(taken*100,0,100).
- HAVE: Mostly YES. RC surfaces EHP threat live via `web/js/panels/cc_blended_ehp_threat.js` + `dashboard/routes_cc_blended_ehp_threat.py`, and the damage-MIX donut (`core/damage_mix.py`) shows enemy phys/magic/true/on-hit split. RC lacks an explicit "% damage taken bar" and a gold-value-of-my-stats line, but those are cosmetic restatements of numbers RC already has.
- WHERE: `web/js/panels/cc_blended_ehp_threat.js` (asset-only, ADR-008 auto-reload).
- EFFORT+RISK: LOW (presentation-only) but LOW value - duplicates existing panels.
- LIFT: LOW.
- **Triage:** CLOSED (have equivalent; not worth a near-dup panel).

### Tool 1 verdict
Nothing HIGH-lift + LOW-risk + NOW-actionable. The single genuine capability gap (T1-F3) is NEW ENGINE MATH, not presentation: RC's EHP scorer deliberately does not fold ENEMY penetration into the tank's effective resists (the data is plumbed via `enemy_items` in `defensive_picks.py` but only feeds threat scores). That, and the per-unit-stat EHP/gold verdict that depends on it (T1-F4), are FUTURE engine slices.

---

## Tool 2: simulator tool R.com (+ r/simulator tool R)
**URL:** https://simulator-tool-r.invalid/ ; https://www.reddit.com/r/simulator-tool-r/

**Summary:** simulator tool R.com (a.k.a. "LoLSim Damage Calculator") is a client-side JS SPA League damage/combat simulator on Patch 26.11 (app 2.21.5, sim engine 3.16.6). The user builds an attacker AND a defender champion (level slider, item slots, runes, ability ranks) and a sequential combo, and it computes per-ability damage, burst total, sustained DPS, and time-to-kill against the target's resolved defenses. All math is client-side (no observable backend API); the body is JS-rendered so WebFetch retrieved only title/version metadata (RENDERING GAP - live calculator numbers gated behind a tutorial prompt, not byte-captured). Architecture corroborated against an exact open-source functional twin (PauHPMCBR/LolDamageCalculator: event-driven sim loop, combo + DPS modes, build-sorting by TTK, `100/(100+resist)` reduction, 4-auto crit cycle, hand-coded champions).

#### T2-F1 - Sequential combo / action-queue builder
- WHAT: User types an ordered cast/attack list; tool shows each action's damage in time order plus a running cumulative total.
- HOW: Event-driven clock - each token stamped with start time, clock advances by cast time; armor/MR per hit; crit on a 4-auto cycle.
- HAVE: YES, already shipped. `agents/daemon_slayer/combo.py` is an action-queue combo simulator authored explicitly as "Competitor lift #2" vs calc.gg's Action Queue; route `agents/daemon_slayer/server.py` `/burst` (`combo_sequence`) + `dashboard/routes_ds_combo.py` (`GET /api/ds-combo?...&seq=Q,AA,W,R`); panel `web/js/panels/ds_combo.js` renders the per-hit timeline.
- WHERE: Already integrated end-to-end.
- EFFORT+RISK: None.
- LIFT: LOW - already shipped.
- **Triage:** CLOSED (parity via the 2026-05-30 calc.gg lift).

#### T2-F2 - Two-champion 1v1 head-to-head
- WHAT: Build champ A and B, fire A's combo into B's defenses and vice-versa, get a who-wins verdict and damage each way.
- HOW: Resolve each side's armor/MR/HP at level+items, mitigate burst, compute fraction-of-EHP removed and a net swing scalar.
- HAVE: YES. `agents/daemon_slayer/matchup.py` `compute_matchup` -> `MatchupResult` (`dmg_a_to_b`, `dmg_b_to_a`, EHP each side, `pct_*_removed`, `net_swing`, `verdict` all_in/back_off/trade/even); DS route `/v2/matchup`; dashboard route `dashboard/routes_ds_matchup.py`; panel `web/js/panels/ds_matchup.js`.
- WHERE: Already integrated.
- EFFORT+RISK: None.
- LIFT: LOW - already shipped.
- **Triage:** CLOSED (RC's Lane-A matchup engine; the deterministic Haiku-replacement north star already in flight).

#### T2-F3 - Sustained DPS + time-to-kill against a defended target
- WHAT: Continuous-combat DPS and TTK (seconds to kill) given attacker output vs target EHP.
- HOW: DPS accumulation loop; kill threshold = target EHP / DPS.
- HAVE: YES (math). `agents/daemon_slayer/dps.py` `compute_dps` + `compute_dps_curve` + `dps_sweep.py`; EHP via the antitank/EHP scorers; mana-bounded gate `mana_sim.compute_mana_bounded_combo`; scenario sweep in `fight_report.py` `compute_fight_report` (`/v2/fight-report`). An explicit single "TTK seconds" scalar is computed inside the fight/matchup composition but not surfaced as its own headline on the combo panel.
- WHERE: `web/js/panels/ds_combo.js` totals block - a "TTK = EHP/DPS" line over values the route already returns.
- EFFORT+RISK: LOW - presentation-only over existing math; no new data/dep/schema; testable.
- LIFT: LOW - thin presentation lift.
- **Triage:** FUTURE (nice-to-have headline TTK; small, not a capability gap; do only if a combo-panel polish slice opens, with the Section 3b UI ritual).

#### T2-F4 - Rune/keystone selection feeding the combo math
- WHAT: simulator tool R exposes rune selection as a first-class input that changes combo/DPS output (Electrocute, Conqueror, etc.).
- HOW: Keystone/rune procs added into per-cast and per-auto damage during the sim.
- HAVE: PARTIAL. The MATH exists - `agents/daemon_slayer/` has `rune_procs` wired into `fight_report.py` and burst (`tests/test_rune_wire_burst_combo.py`, `test_rune_procs_per_attack.py`). BUT the dashboard combo route does NOT thread runes: `dashboard/routes_ds_combo.py` accepts champion/level/items/target only (grep for `rune|keystone` returned ZERO matches - verified live).
- WHERE: `dashboard/routes_ds_combo.py` (add `runes=`/`keystone=` query param) + `web/js/panels/ds_combo.js` (keystone selector) -> pass through to the existing `rune_procs` path the burst walker already supports.
- EFFORT+RISK: MED - route + panel wiring + a passthrough + a test + the Section 3b UI ritual (panel touched). No new data source (rune data already in DS), no Claude/Riot dep.
- LIFT: MED - the math is there; the combo SURFACE does not expose runes yet.
- **Triage:** FUTURE (highest-value true gap vs simulator tool R; a scoped slice with a test + UI audit, not a one-liner).

#### T2-F5 - Free sandbox (arbitrary champ/items/level, ungated from the live game)
- WHAT: Pure sandbox - pick any champion/items/level with no game running.
- HAVE: YES. Both RC panels take free input (`ds-combo`: champion/level/items/seq/target_*; `ds-matchup`: arbitrary champ_a/champ_b + levels + mode). Not locked to live state.
- EFFORT+RISK: None.
- LIFT: LOW - parity.
- **Triage:** CLOSED.

#### T2-F6 - Build sorting (rank builds by damage/TTK)
- WHAT: Sort builds by TTK/DPS to find the best build.
- HAVE: YES, deeper. RC has `rank_items_by_burst`, the 6 archetype scorers, `dps_sweep`, gold-efficiency ranking - core competency, not a gap.
- EFFORT+RISK: None.
- LIFT: LOW - RC exceeds.
- **Triage:** CLOSED.

### Community signal (r/simulator tool R)
- Reddit was unfetchable (WebFetch blocked on reddit.com; targeted searches returned no live thread content) - GAP noted, not inferred.
- Adjacent open-source twins (PauHPMCBR, FermiParadox) confirm the wanted feature set is exactly combo damage, DPS/TTK, and build-sorting - all of which RC already has. The recurring stated limitation of these tools is "champions must be hand-coded / only a few implemented," which is precisely where RC's 172-champ Meraki+DDragon+CommunityDragon-driven engine is structurally superior (do NOT change DS source-of-truth - Settled).

### Tool 2 verdict
Nothing NOW-actionable rises to HIGH-lift. simulator tool R's entire core was already shipped in RC via the prior calc.gg lift. The single best genuine gap is T2-F4 (rune/keystone in the combo SURFACE) - a scoped MED wire-up (route param + keystone selector + test + UI audit), FUTURE not today. The only LOW/NOW nicety is T2-F3 (a headline TTK line), worth doing only if a combo-panel polish slice opens.

---

## Premise verification (re-checked live before publishing)

| Claim | Check | Result |
|---|---|---|
| combo.py is an action-queue combo sim | `head` file header | CONFIRMED ("action-queue combo simulator") |
| routes_ds_combo.py has no runes param | grep `rune|keystone` | CONFIRMED (zero matches) |
| ehp.py documents enemy-pen omission | read lines ~28-33 | CONFIRMED ("Caster-side enemy pen/reduction ... needs enemy build plumbing") |
| cc_blended_ehp_threat panel + route live | file existence | CONFIRMED (both present) |
| prior calc.gg lift doc exists | file existence | CONFIRMED (docs/COMPETITOR_LIFT_2026-05-30.md) |
| matchup.py + fight_report.py present | file existence | CONFIRMED |

## Provenance
Champion/item math sourced from Riot Data Dragon, CommunityDragon, and Meraki (DS source-of-truth). Competitor tools reviewed read-only over public web; no third-party code vendored - any FUTURE lift re-implements in RC's own code per the Settled lift policy. KebsCS-class catalogs remain reference-only.
