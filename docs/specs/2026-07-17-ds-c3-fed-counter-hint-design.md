# DS build-reco - light up the C3 fed counter-hint (design)

Status: SLICE S1 (orchestrator-directed, 2026-07-17). Tier-1 (RC-side; no
ENGINE bump / Share / :8893 restart). Slice scope: C3 fed ONLY, HINT-ONLY,
mirroring the shipped C2 antiheal (LEDGER 908) + C6 tenacity (LEDGER 909)
pattern. Supersedes the flag/shadow posture of docs/specs/leap/
LEAP-08-c3-fed-criterion.md for this slice (deviations listed below); the
LEAP-08 fed formula + payload field names are ADOPTED unchanged.

ASCII only - " - " for a clause break (repo hard rule).

## Why

Follow-up to LEDGER 908/909 (commit e9487a78). Of the 6 situational counter-
build criteria, C1/C4/C5 were always live, C2 antiheal + C6 tenacity fire
since 2026-07-16. ONLY C3 fed remains WIRED BUT DEAD:

  * `core/build_planner/situational.py:134` - `EnemyProfile.fed: bool = False`
    exists on the locked dataclass.
  * `situational.py:407-413` - the `counter_build_hints` C3 gate `if ep.fed:`
    emits `CounterHint(criterion="fed", satisfied=any_survival,
    severity="high", label="SURVIVE", detail="fed enemy - itemize defense",
    suggest_class="resist")`. Fully plumbed; dead only because the route never
    populates `fed`.
  * `situational.py:469-479` - `build_enemy_profile(..., fed=False, ...)`
    already accepts the kwarg and sets it at `:545`. NO situational.py gating
    edit is needed (same posture as C6).

This slice gives `fed` a live source (a NEW pure estimator module) and adds a
damage-axis DIRECTION to the served fed hint (armor vs a fed AD threat, MR vs
a fed AP threat) at the route's projection layer - situational.py's locked
gate + dataclasses stay byte-identical.

## Goal / non-goals

GOAL: the SURVIVE counter chip fires on `/api/build-plan.counter_hints` when
any single enemy is provably fed (combat lead AND estimated-economy lead),
with the hint detail naming the fed enemy + the defensive direction matching
THAT enemy's damage axis (`suggest_class` armor for a fed AD threat, mr for a
fed AP threat, the generic resist fallback when the axis is unknown).

NON-GOALS (out of scope, deferred):
  * ANY change to the DS-scored plan (`loop.tick` / `live[]` / `meta[]`).
  * ANY edit to `situational.py` (gate, dataclasses, W_FED, detail template -
    all LOCKED; the axis enrichment happens on the route's projected dicts).
  * `web/js/panels/active_match.js` - OUT OF THIS SLICE'S FILE SET. The two
    new payload fields land server-side fail-soft; the JS POST of
    `enemy_scores` + `enemy_levels` (LEAP-08 section "active_match.js") is the
    follow-up slice, after which the chip lights in live games.
  * Kill-streak detection (needs an event scan - the scoreboard has no streak
    field), role/lane detection (no positions over the Live Client API), a
    graduated fed score (the dataclass field is bool), per-patch tuning.

## Deviations from LEAP-08 (orchestrator-directed for this slice)

  1. NO feature flags (`RC_FED_HINT` / `RC_FED_SHADOW` dropped) and NO shadow
     log. Directive: hint-only, flagless - exactly how C2 + C6 shipped. The
     chip stays dark in production anyway until the JS slice posts the new
     fields (absent fields -> fed False -> no chip), which preserves the
     ship-dark posture without a flag.
  2. Module lives at `core/build_planner/fed_threat.py` (NOT
     `core/build_planner/fed_threat.py`) - slice file ownership is `core/build_planner/**`.
     It is a build-planner-scoped concern; the cc_threat/heal_threat shape is
     mirrored, only the directory differs.
  3. The served fed hint gains a per-threat damage-axis direction (LEAP-08
     deferred this as "future refinement" because it assumed a situational.py
     detail edit; this slice does it WITHOUT touching situational.py by
     enriching the already-projected JSON dict in the route).

## Key invariant: HINT-ONLY (plan stays byte-identical)

`fed` is populated ONLY on the counter-hint profile, NEVER on the `loop.tick`
`enemy_profile` (`routes_build_plan.py:327`). The new payload fields
(`enemy_scores`, `enemy_levels`) influence counter_hints[] ONLY. This mirrors
the shipped R102/R103 + C2 + C6 discipline, so the DS-scored `live[]`/`meta[]`
are byte-identical with vs without fed inputs. No do-not-flip-blind risk: the
plan does not move; only the advisory chip appears.

## fed formula: COMBAT LEAD and ECONOMY LEAD (LEAP-08, adopted)

Per enemy X (all inputs index-aligned with `enemies`):

```
fed(X) := (kills(X) - deaths(X)) >= KDA_LEAD_CUT (3)
          AND (est_gold(X) - est_gold(me)) >= GOLD_LEAD_CUT (2000)

est_gold(p) = sum(item gold.total over p's owned ids) + LEVEL_GOLD (130) * level
```

`EnemyProfile.fed` = any enemy satisfies fed(X). The named enemy in the hint
detail is the TOP fed enemy (max by net kills, then kills). Why AND
(conservative): mirrors the heal_threat / cc_threat under-fire-never-mis-fire
philosophy - a 5-1 enemy WITH a 2000+ estimated-gold lead is unmistakably
fed; either signal alone is not yet "itemize defense NOW". Why the ACTIVE
PLAYER as the economy baseline: the chip serves MY itemization, my `items` +
`level` are already in every build-plan POST (`routes_build_plan.py:297,300`),
and it is role-agnostic (no positions API exists). Enemy gold is NOT readable
over the Live Client API (activePlayer-only) - the estimator over public
`allPlayers[].items` + `level` is the one honest economy signal
(precedent: `web/js/lib/item_value.js` R117 F1).

Assists are deliberately excluded from the combat gate (a high-assist support
must not read as a fed CARRY). Item-count-only proxies are deliberately
excluded (late-game everyone is item-saturated; gold-total + level is the
honest proxy).

## Damage-axis direction: existing facts only

The fed enemy's axis comes from DDragon `info.attack` vs `info.magic`
(`core/defensive_picks._load_champ_info` - the same index
`compute_threat_profile` classifies with; cross-module private-helper import
precedent: `situational.py:39`) overlaid with
`core.champion_info_overrides.merged_info` (the shipped fix for the zeroed
Seraphine/Akshan/Rell/Vex/Qiyana blocks, same consumers as
routes_dictionary/routes_pickban). Strictly greater attack -> "ad", strictly
greater magic -> "ap", tie/unknown -> "" (the enrichment then leaves the
generic situational detail untouched - under-inclusion never mis-directs).

## Components

### 1. `core/build_planner/fed_threat.py` (NEW - mirrors core/cc_threat.py)

Pure, network/LLM/engine-free, fail-soft. Public surface:

```
def estimate_player_gold(item_ids, level) -> float:
    """sum(gold.total over owned ids) + LEVEL_GOLD * level. Unknown id
    contributes 0. Fail-soft 0.0 on bad / missing input."""

def assess_fed_threat(enemies, enemy_items_by_player, enemy_scores,
                      enemy_levels, my_item_ids, my_level) -> dict | None:
    """The TOP fed enemy as {champion, kills, deaths, axis} or None when no
    enemy clears BOTH cuts. axis in {"ad", "ap", ""}. Fail-soft None."""

def compute_fed(...) -> bool:
    """assess_fed_threat(...) is not None - the EnemyProfile.fed bool."""
```

Item-gold map: private one-time lazy `{id_str: float(gold.total)}` from
`data/meta/ddragon_items.json` (verified: 706/706 entries carry gold.total;
the same file `situational.py:84` loads). Any load failure -> empty map ->
economy gate never clears (graceful).

### 2. `dashboard/routes_build_plan.py` (wire the hint path)

  * Parse two NEW optional payload fields with coercers mirroring
    `_coerce_enemy_items` (`:438`): `enemy_scores` -> list of
    {kills,deaths,assists} int dicts, `enemy_levels` -> list of ints, both
    index-aligned with `enemies`, absent/malformed -> None.
  * `fed_info = assess_fed_threat(enemies, enemy_items, enemy_scores,
    enemy_levels, owned, level)`; `fed = fed_info is not None`.
  * Extend `_resolve_enemy_profile` (`:462`) with a `fed=False` kwarg
    forwarded to `build_enemy_profile` (parallel to `cc_score`).
  * Build the HINT profile whenever `enemy_items` OR `heal_sources` OR
    `cc_score` OR `fed` is present; the `loop.tick` `enemy_profile` (`:327`)
    is untouched.
  * `_enrich_fed_hint(counter_hints, fed_info)`: on the PROJECTED dicts only,
    rewrite the criterion=="fed" entry's detail to
    "fed <Name> <k>/<d> - build armor|mr" + suggest_class "armor"|"mr" when
    the axis is known; axis "" leaves the generic entry untouched. label stays
    "SURVIVE" (chip identity), criterion/satisfied/severity untouched.
    Fail-soft: any error returns the hints unchanged.

### 3. Live Client field grounding (consumed via the payload, cited)

  * `game_reader/snapshot_normalizer.py:300-304` - per enemy:
    `e.get("scores", {})` -> kills/deaths/assists, `e.get("level", 0)`. So
    `allPlayers[].scores.{kills,deaths,assists}` + `allPlayers[].level` are
    hard public facts for all ten players.
  * `web/js/panels/active_match.js:217-233` already walks `lc.allPlayers`
    per-enemy for names+items - the follow-up JS slice extends it to POST
    `enemy_scores` + `enemy_levels` (LEAP-08 shape, unchanged).

## Data flow

`POST {champion, level(me), items(me), enemies, [enemy_items],
       [enemy_scores], [enemy_levels], [ally_items]}`
  -> `fed_info = assess_fed_threat(...)` (fed_threat)
  -> `build_enemy_profile(..., fed=bool(fed_info))` (HINT profile only)
  -> `counter_build_hints(owned, hint_profile, ally_state)`
  -> `_enrich_fed_hint(projected_hints, fed_info)`
  -> `counter_hints[]` gains {criterion:"fed", label:"SURVIVE",
     detail:"fed <Name> <k>/<d> - build armor|mr",
     suggest_class:"armor"|"mr"|"resist"} (satisfied = build owns any
     armor/mr/health item, computed by the locked situational gate).

## Testing (all client-mode, RED-first)

`tests/test_c3_fed_counter_hint.py` (NEW, self-contained - copies the small
`_Handler`/`_post` harness from tests/test_build_plan_contract.py:46-124 so
this slice touches no shared test file):

  * estimate_player_gold: additive decomposition (items-only + LEVEL_GOLD *
    level), unknown-id contributes 0, fail-soft 0.0.
  * compute_fed/assess boundaries: TRUE at net>=3 AND lead>=2000; FALSE
    combat-only; FALSE economy-only; level-fold boundary (equal items, level
    lead 17-vs-1 fires at 2080, 16-vs-1 does not at 1950); fail-soft on
    absent/short/junk inputs; top-enemy pick; axis ad (Draven 9/1) / ap
    (Annie 2/10) / overlay (Seraphine zeroed -> ap via merged_info) /
    unknown -> "".
  * Route: a fed comp surfaces the fed/SURVIVE hint with the axis-directed
    detail + suggest_class; a non-fed comp does NOT; `live[]` + `meta[]` are
    BYTE-IDENTICAL with vs without the fed inputs (the load-bearing
    invariant); junk enemy_scores never raises (200, hints present).
  * ASCII hygiene over the new module + test file + this spec.

## Error handling

Every new read is fail-soft: bad `enemy_scores`/`enemy_levels` -> None -> fed
False -> no chip; estimator load failure -> economy gate never clears; the
enrichment returns hints unchanged on any error; the route's existing
try/except never raises into the response; `counter_hints` stays
always-present (`[]` on any failure). No raw error string ever reaches a
panel.

## Tier / verification

Tier-1 RC-side: `core/build_planner/fed_threat.py` (new) +
`dashboard/routes_build_plan.py`. No engine, no schema, no ENGINE_VERSION, no
Share mirror, no :8893 restart - RC reload only. Verify: py_compile + ruff on
touched files; `tests/test_situational_counter_build.py` +
`tests/test_c3_fed_counter_hint.py` + `tests/test_build_plan_contract.py`
green. The overlay chip render is live-verify owed AFTER the follow-up JS
slice posts the new fields.
