# DS build-reco - light up the C6 tenacity counter-hint (design)

Status: APPROVED (operator, 2026-07-16). Tier-1 (RC-side; no ENGINE bump / Share
/ :8893 restart). Slice scope: C6 tenacity ONLY. C3 fed stays deferred (live-
gated - needs live KDA / gold-lead, no clean payload signal).

ASCII only - " - " for a clause break (repo hard rule).

## Why

Follow-up to LEDGER 908 (C2 antiheal). Ground truth: the situational counter-
build (Step 2) is shipped (WP-R102/R103); C2 antiheal was lit up 2026-07-16. Of
the 6 criteria, C1/C4/C5 were always live and C2 now fires. C6 tenacity + C3 fed
remain WIRED BUT DEAD:

  * C6 tenacity gate is `situational.py:450` (`if ep.cc_score >= CC_CUT`,
    `CC_CUT = 5.0`, line 79). `build_enemy_profile` (`situational.py:469`) already
    accepts a `cc_score=0.0` kwarg and sets `EnemyProfile.cc_score`
    (`:475`, `:542`) - so the gate is FULLY PLUMBED and dead only because the
    route never populates `cc_score` (`routes_build_plan.py` calls
    `_resolve_enemy_profile` with the default 0.0). No enemy-CC source exists:
    `defensive_picks.compute_threat_profile` returns ad/ap/burst/tank threat but
    NO CC metric, and there is no live CC API.

This slice gives `cc_score` a live source via a NEW curated hard-CC champ roster,
mirroring `core/heal_threat.py` exactly. Like C2, NO `situational.py` edit is
needed - only the curation module + the route thread.

## Goal / non-goals

GOAL: the `TENACITY` counter chip fires on `/api/build-plan.counter_hints` when
the enemy comp fields enough hard CC (`cc_score >= 5.0`), with `satisfied` = the
current build already owns a tenacity item.

NON-GOALS (out of scope, deferred):
  * C3 fed (needs live KDA / gold-lead - the build-plan payload has no clean fed
    signal; genuinely live-gated).
  * ANY change to the DS-scored plan (`loop.tick` / `live[]` / `meta[]`).
  * ANY edit to `situational.py`'s locked gating (`CC_CUT = 5.0` stays;
    `counter_build_hints` / `situational_fit` unchanged).
  * Enemy CC ITEMS (CC is a champion-kit property; a few items add slows but the
    roster is champ-only, matching the `enemy CC N/10` detail semantics).

## Key invariant: HINT-ONLY (plan stays byte-identical)

`cc_score` is populated ONLY on the counter-hint profile, NEVER on the
`loop.tick` `enemy_profile` (`routes_build_plan.py:327`). This mirrors the shipped
R102/R103 + C2 discipline (enemy_items / heal_sources enrich hints only) so the
DS-scored `live[]`/`meta[]` are byte-identical with vs without `cc_score`. No
do-not-flip-blind risk: the plan does not move; only the advisory chip appears.

## cc_score mapping: FLAT PER-CHAMP x2.5 (approved)

`cc_score = min(10.0, len(matched curated hard-CC champs) * 2.5)`. C6 fires at
`cc_score >= CC_CUT (5.0)`, i.e. at 2+ matched hard-CC champs (1 champ -> 2.5, no
fire; 2 -> 5.0, fires; 4+ -> 10.0 clamp). This is the exact `heal_threat`
philosophy (each curated champ = 1 unit), simplest to test/reason. A graduated
per-champ weight is a deliberate future refinement, not needed to light up the
criterion honestly.

Known simplification: tenacity does not shorten knockups / suppression /
displacement, but the chip is a general "CC-heavy comp -> itemize tenacity / QSS
/ cleanse" advisory (matching how players itemize), so the roster spans stuns /
roots / suppresses / taunts / charms / fears / reliable knockups. Refinement is
future work.

## Components

### 1. `core/cc_threat.py` (NEW - mirrors `core/heal_threat.py`)

A curated frozenset of hard-CC champion display-name keys (normalized lowercase-
alphanumeric, so "Cho'Gath" -> "chogath", "Jarvan IV" -> "jarvaniv"), reusing the
`heal_threat` normalization approach. One pure public helper:

```
def compute_cc_score(enemy_comp) -> float:
    """min(10.0, distinct matched curated hard-CC champs * 2.5). The float the
    situational EnemyProfile.cc_score consumes (the C6 tenacity counter-hint
    fires at >= CC_CUT (5.0)). Fail-soft to 0.0 on bad / missing input."""
```

Correct-by-construction + fail-soft: a name not in the roster simply does not
contribute (under-inclusion never fires a wrong chip; over-inclusion is the only
risk, so the roster is curated for RELIABLE hard CC). No network / LLM / engine.

Curated roster (v1, extensible - review target). Reliable hard-CC champions where
tenacity / QSS is standard counterplay:

  * Engage tanks / supports / junglers: leona, nautilus, amumu, sejuani,
    malphite, rell, alistar, thresh, blitzcrank, braum, rakan, zac, ornn,
    rammus, skarner, maokai, chogath, sion, gragas, vi, wukong, monkeyking,
    gnar, jarvaniv, nocturne, warwick, volibear, nunu, nunuwillump, galio,
    shen, poppy, taric
  * Mages / control: morgana, veigar, lissandra, malzahar, annie, neeko,
    syndra, ryze, ahri, zoe, swain, brand, xerath, lux, cassiopeia, vex
  * Enchanters / utility: nami, bard, sona, seraphine, janna
  * Marksmen with reliable hard CC: ashe, varus, jhin, kalista
  * Fighters / assassins with reliable hard-CC core: renekton, riven, irelia,
    camille, ekko, pantheon, jax, kennen, udyr, xinzhao, sett, fiddlesticks

Deliberately EXCLUDED (conditional / skillshot-sweet-spot CC, to avoid over-
firing): yasuo, yone, aatrox, vayne (all need a specific proc / wall / tornado).

### 2. `dashboard/routes_build_plan.py` (wire the hint path)

  * Compute `cc_score = compute_cc_score(enemies)` (0.0 when no enemies).
  * Extend `_resolve_enemy_profile` with a `cc_score=0.0` kwarg forwarded to
    `build_enemy_profile` (parallel to the C2 `heal_sources=0` kwarg).
  * Build the HINT profile whenever `enemy_items` OR `heal_sources` OR `cc_score`
    is present; otherwise it stays the champion-only `enemy_profile` (today's
    behavior). The `loop.tick` `enemy_profile` (`:327`) is untouched.
  * `_resolve_counter_hints` already threads the profile into
    `counter_build_hints`; the C6 gate fires off `ep.cc_score` with no further
    change.

### 3. `web/js/panels/active_match.js` (NO CHANGE)

`active_match.js` already POSTs `enemies` (the champion roster) - the only input
`compute_cc_score` needs. No new payload field, unlike C2's `ally_items`. The
visible chip render is LIVE-VERIFY OWED (Electron overlay, not agent-reachable).

## Data flow

`POST {enemies, [enemy_items], [ally_items]}`
  -> `cc_score = compute_cc_score(enemies)` (cc_threat)
  -> `build_enemy_profile(..., cc_score=N)` (HINT profile only)
  -> `counter_build_hints(owned, hint_profile, ally_state)`
  -> `counter_hints[]` gains the `tenacity` entry when `cc_score >= 5.0`
     (`satisfied` = build owns a tenacity item).

## Testing (all client-mode, RED-first)

  * `tests/test_cc_threat.py` (NEW): `compute_cc_score` - matched-champ count *
    2.5, 10.0 clamp at 4+ champs, distinct-dedup, fail-soft 0.0 on bad / missing
    / non-list input, an off-roster comp -> 0.0.
  * `tests/test_build_plan_contract.py`: (a) a >=2 hard-CC enemy comp surfaces a
    `tenacity` counter-hint; (b) a low / no-CC comp does NOT fire it; (c) `live[]`
    + `meta[]` are BYTE-IDENTICAL with vs without a high-CC comp (proves
    `loop.tick` untouched - the load-bearing invariant). Reuse the `_post`
    harness (monkeypatches the seed factory - no live :8893 needed).

## Error handling

Every new read is fail-soft: bad `enemies` -> `cc_score` 0.0 -> no chip; the
route's existing try/except never raises into the response; `counter_hints`
remains always-present (`[]` on any failure).

## Tier / verification

Tier-1 RC-side: `core/cc_threat.py` (new) + `dashboard/routes_build_plan.py`. No
engine, no schema, no ENGINE_VERSION, no Share mirror, no :8893 restart - RC
reload only. Verify: the module + contract test cluster, then a live
`/api/build-plan` probe with a hard-CC comp to confirm the `tenacity` chip
populates + the plan is unchanged. The overlay chip render is live-verify owed.
