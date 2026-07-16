# DS build-reco - light up the C2 antiheal counter-hint (design)

Status: APPROVED (operator, 2026-07-16). Tier-1 (RC-side; no ENGINE bump / Share
/ :8893 restart). Slice scope: C2 antiheal + AllyState dedup ONLY. C6 tenacity +
C3 fed are explicit follow-ups.

ASCII only - " - " for a clause break (repo hard rule).

## Why

Surfaced re-scoping the DS build-reco refactor after the client-mode 16.14.1
validation (LEDGER 907 - Locke fix). Ground truth vs the stale 2026-07-13 spec:
the situational counter-build (Step 2) is ALREADY shipped (WP-R102/R103) - the
`/api/build-plan` route builds an `EnemyProfile`, projects
`counter_build_hints`, and `active_match.js` renders the COUNTER chip row. But
the counter-build has 6 criteria and only THREE fire live:

  * C1 resist (ad/ap share), C4 hp-vs-pen (enemy_pen items), C5 pen-type
    (kill-target armor/MR) - LIVE (verified: `/api/build-plan` returns
    `resist ARMOR (enemy 86% physical)` + `pen_type ARMOR PEN (kill target 166
    armor)` for a Caitlyn-vs-AD-comp probe).
  * C2 antiheal, C3 fed, C6 tenacity - WIRED BUT DEAD. `build_enemy_profile`
    (`core/build_planner/situational.py:469`) is called with the default
    `heal_sources=0` / `cc_score=0.0` / `fed=False` (the route never populates
    them: `dashboard/routes_build_plan.py:435-453`), so those chips never fire.
    `AllyState.has_antiheal` (`situational.py:139`) is likewise never populated,
    so the C2 antiheal de-dup is moot.

This slice lights up C2 (antiheal) by giving it a live source, reusing the
existing curated `core/heal_threat.py`.

## Goal / non-goals

GOAL: the `ANTIHEAL` counter chip fires when the enemy comp/items warrant
Grievous Wounds AND no ally already owns it, on `/api/build-plan.counter_hints`.

NON-GOALS (out of scope, deferred):
  * C6 tenacity (needs net-new hard-CC champ curation - no enemy-CC source
    exists; `defensive_picks.compute_threat_profile` returns no CC metric).
  * C3 fed (needs live KDA / gold-lead - live-gated).
  * ANY change to the DS-scored plan (`loop.tick` / `live[]` / `meta[]`).
  * ANY edit to `situational.py`'s locked gating (`HEAL_THRESHOLD=2` stays;
    `counter_build_hints` / `situational_fit` unchanged).

## Key invariant: HINT-ONLY (plan stays byte-identical)

`heal_sources` + `AllyState` are populated ONLY on the counter-hint path, NEVER
on the `loop.tick` `enemy_profile` (`routes_build_plan.py:325`). This mirrors the
shipped R102/R103 discipline (enemy_items enrich hints only) so the DS-scored
`live[]`/`meta[]` are byte-identical with vs without heal-sources. No
do-not-flip-blind risk: the plan does not move; only the advisory chip appears.

## heal_sources mapping: LITERAL COUNT (approved)

`heal_sources = len(matched curated sustain champs) + (count of enemy heal
items)`. C2 fires at `heal_sources >= HEAL_THRESHOLD (2)`. Consequence: a LONE
heavy-sustain champ (one Soraka, 0 heal items -> count 1) does NOT fire the C2
chip - the separate standing `heal_threat_callout` (which fires at >=1 curated
champ) still advises antiheal. Two surfaces, honest count semantics, no fudge.

## Components

### 1. `core/heal_threat.py` (+2 pure public helpers)

Reuse the existing curated sets (`_HEAVY_SUSTAIN_CHAMPIONS`,
`_HEAL_ITEM_IDS`, `_GRIEVOUS_ITEM_IDS`) + private counters
(`_matched_sustain_champs`, `_count_in_set`) - no new curation.

```
def count_heal_sources(enemy_comp, enemy_item_ids) -> int:
    """len(matched curated sustain champs) + distinct enemy heal items.
    Fail-soft to 0 on bad/missing input (mirrors the module contract)."""

def ally_has_antiheal(ally_item_ids) -> bool:
    """True when any ally item is a Grievous-Wounds item. Fail-soft False."""
```

Both are pure set-membership reads over the same curation the callout uses.

### 2. `dashboard/routes_build_plan.py` (wire the hint path)

  * `_serve_build_plan`: parse a NEW optional `ally_items` payload field (flat
    id-string list; fail-soft via a small coercer, `[]`/None -> no dedup).
  * Compute `heal_sources = count_heal_sources(enemies, flatten(enemy_items))`
    (0 when no enemies/items).
  * Build the HINT profile with `heal_sources` (extend `_resolve_enemy_profile`
    with a `heal_sources=0` kwarg forwarded to `build_enemy_profile`). Build it
    as a SEPARATE profile whenever `enemy_items` OR `heal_sources` is present;
    otherwise it stays the champion-only `enemy_profile` (today's behavior).
  * Compute `ally_state = AllyState(has_antiheal=ally_has_antiheal(ally_items))`.
  * Thread `ally_state` into `counter_build_hints` via a new
    `_resolve_counter_hints(hint_profile, owned, ally_state)` param (currently
    `counter_build_hints(owned, enemy_profile)` at `:470` drops ally_state).
  * The `loop.tick` `enemy_profile` (`:325`) is untouched (heal_sources absent).

### 3. `web/js/panels/active_match.js` (send ally_items)

Mirror the existing `enemy_items` builder (off the `allPlayers` roster, ~`:211`)
to also POST `ally_items` (flat ally-team owned ids). Small; the visible chip
change is LIVE-VERIFY OWED (Electron overlay, not agent-reachable).

## Data flow

`POST {enemies, enemy_items, ally_items}`
  -> `heal_sources` (heal_threat) + `ally_state` (heal_threat)
  -> `build_enemy_profile(..., heal_sources=N)` (HINT profile only)
  -> `counter_build_hints(owned, hint_profile, ally_state)`
  -> `counter_hints[]` gains the `antiheal` entry (`satisfied` = build owns a
     Grievous item; suppressed entirely when `ally_state.has_antiheal`).

## Testing (all client-mode, RED-first)

  * `tests/test_heal_threat.py` (or existing): `count_heal_sources` (champ +
    item counting, dedup, fail-soft 0) and `ally_has_antiheal` (Grievous
    membership, fail-soft False).
  * `tests/test_build_plan_contract.py`: (a) a 2-healer enemy comp surfaces an
    `antiheal` counter-hint; (b) an ally Grievous item suppresses it; (c) a lone
    sustain champ does NOT fire it (literal-count boundary); (d) `live[]` +
    `meta[]` are BYTE-IDENTICAL with vs without heal-sources (proves `loop.tick`
    untouched - the load-bearing invariant).

## Error handling

Every new read is fail-soft: bad `ally_items` -> no dedup; `heal_threat` helpers
-> 0 / False; the route's existing try/except never raises into the response.
`counter_hints` remains always-present (`[]` on any failure).

## Tier / verification

Tier-1 RC-side: `core/heal_threat.py` + `dashboard/routes_build_plan.py` +
`web/js/panels/active_match.js`. No engine, no schema, no ENGINE_VERSION, no
Share mirror, no :8893 restart - RC reload only (asset-hash auto-reload for the
JS). Verify: the module + contract test cluster, then a live `/api/build-plan`
probe with a healer comp to confirm the `antiheal` chip populates + the plan is
unchanged. The overlay chip render is live-verify owed.
