# LEAP-08 - DS counter-build hint C3 "fed criterion" (spec)

Status: SPEC (Fable-5 forward-leap portfolio, 2026-07-16). Tier-1 RC-side.
Shadow-first: the fed signal is computed + shadow-logged + fully plumbed
headless, but the on-screen SURVIVE chip stays DARK behind a default-OFF flag
until the operator live-validates and flips it (a LIVE_GAME_GATED_SYNC row).
One execution session, model claude-opus-4-8 effort high.

ASCII only - use " - " for a clause break (repo hard rule). No em/en dashes.

--------------------------------------------------------------------------- #

## GOAL

"front-load the thinking into specs; execution sessions are typing, not
deciding".

Light up the C3 "fed" counter-build criterion. Today C1 resist / C4 hp-vs-pen /
C5 pen-type / C2 antiheal / C6 tenacity all fire live; ONLY C3 fed remains
wired-but-dead. Give `EnemyProfile.fed` a live, correct-by-construction source
so the situational counter-build surfaces a "an enemy is fed -> itemize defense
now" advisory, gated behind a shadow-first, operator-flipped switch.

The hard premise (verified below): the Live Client API exposes per-player
scores (kills / deaths / assists / creepScore) and level for ALL ten players,
but GOLD only for the active player. So the enemy economy lead cannot be read -
it must be ESTIMATED from each enemy's owned-item gold value (a hard public
fact) plus level. This spec picks that estimator and the fed formula, so the
execution session is pure typing.

## EVIDENCE (cited ground truth - every claim probed this session)

C3 is ALREADY fully plumbed - dead ONLY because the route never populates
`fed` (identical situation to C6 tenacity before LEDGER 909):

  * `core/build_planner/situational.py:134` - `EnemyProfile.fed: bool = False`
    field EXISTS on the locked dataclass.
  * `situational.py:251` - `situational_fit` C3: `r_fed = W_FED if (ep.fed and
    any_survival) else 0.0` (W_FED = 0.55, `situational.py:71`).
  * `situational.py:408-413` - `counter_build_hints` C3 gate: `if ep.fed:` emits
    `CounterHint(criterion="fed", satisfied=any_survival, severity="high",
    label="SURVIVE", detail="fed enemy - itemize defense",
    suggest_class="resist")`. This is the exact chip we light. NO edit needed.
  * `situational.py:469-479` - `build_enemy_profile(..., fed=False, ...)` already
    accepts the kwarg; `situational.py:545` sets `fed=bool(fed)` on the returned
    profile. So the builder is READY; nothing in situational.py changes.

The route + the hint-only discipline to clone (C2/C6 shipped pattern):

  * `dashboard/routes_build_plan.py:327` - `enemy_profile = _resolve_enemy_profile
    (enemies, level)` is the CHAMPION-ONLY profile that feeds `loop.tick`. It
    MUST NOT gain `fed`, or the DS-scored `live[]`/`meta[]` would move.
  * `routes_build_plan.py:340-356` - the HINT profile is a SEPARATE
    `_resolve_enemy_profile(..., heal_sources=, cc_score=)` built only when
    `enemy_items or heal_sources or cc_score` is truthy; `_resolve_counter_hints`
    threads it into `counter_build_hints`. This is exactly where `fed` slots in.
  * `routes_build_plan.py:462-484` - `_resolve_enemy_profile(enemies, level,
    enemy_items=, heal_sources=, cc_score=)` - add a `fed=False` kwarg here,
    forwarded to `build_enemy_profile`, parallel to `cc_score`.
  * `routes_build_plan.py:297` - `level = ...payload.get("level")` and
    `routes_build_plan.py:300` - `owned = ...payload.get("items")` are the ACTIVE
    player's level + owned items. These are the estimator BASELINE inputs - they
    are ALREADY in every build-plan POST, so NO new active-player payload field
    is needed.
  * `routes_build_plan.py:438-459` - `_coerce_enemy_items` / `_coerce_ally_items`
    are the fail-soft coercer pattern to mirror for `enemy_scores` /
    `enemy_levels`.

The curation/estimator module pattern to clone:

  * `core/cc_threat.py` (whole file) - the newest sibling: pure, fail-soft,
    correct-by-construction, `compute_cc_score` at `:112`. C3's module mirrors
    its shape.
  * `core/heal_threat.py:238` `count_heal_sources` / `:250` `ally_has_antiheal`
    - the +helpers-on-a-curation-module pattern; `:128` `_id_strs` coerces int-
    or-str item ids (the Live Client `itemID` can arrive either way).

The estimator premise + the CLIENT-side precedent that already implements it:

  * `web/js/lib/item_value.js:1-10` (docstring) - "Enemy GOLD is activePlayer-
    only over the Live Client API, but allPlayers[].items is public for all 10,
    so summing each player's on-board item gold-worth (ITEM_COSTS) and diffing
    ally-team vs enemy-team is the one economy signal computable client-side."
    This IS the premise, already proven and shipped (R117 F1, the map_state
    item-value bar). `_playerItemValue` (`:33`) sums `ITEM_COSTS.byId[id]` over
    `pl.items[].itemID`. C3 ports this sum server-side, per enemy.
  * `web/js/lib/items_index.js:14` `ITEM_COSTS = {ready, byId}` loaded from
    `/data/items_costs.json` (`:138-146`); the recipe loader reads
    `it.gold.total` from `/api/dictionary/items` (`:162`). Confirms item gold-
    total is the cost basis.

Enemy per-player scores + level are LIVE-AVAILABLE (the estimator inputs):

  * `game_reader/snapshot_normalizer.py:300-304` - per enemy `e`: `esc =
    e.get("scores", {})`, `elevel = e.get("level", 0)`, and
    `f"{esc.get('kills',0)}/{esc.get('deaths',0)}/{esc.get('assists',0)}"`. So
    `allPlayers[].scores.{kills,deaths,assists}` + `allPlayers[].level` are hard
    facts for every enemy (mirrored for allies at `:318-322`, active at `:249`).
  * `web/js/panels/active_match.js:217-233` - `_extractBpEnemies(allPlayers,
    myTeam)` already walks `allPlayers`, excludes my team, and emits index-
    aligned `names[]` + `items[]` from `pl.championName` + `pl.items[].itemID`.
    Extend it (or add a sibling) to ALSO emit `scores[]` + `levels[]`.
  * `active_match.js:266-296` - `_maybeRefreshBuildPlan` builds the POST body
    (`enemies`, `enemy_items`, `ally_items`) + the cache fingerprint. Add
    `enemy_scores` + `enemy_levels` to both.

The server-side item-gold source (for the Python estimator):

  * `data/meta/ddragon_items.json` - each item carries `gold.total` (verified:
    the file `situational.py:84` `_ITEMS_PATH` already loads has `"gold":
    {"total": 300, ...}` per entry). The estimator reads its OWN one-time lazy
    `{id_str: gold.total}` map from this SAME file (no situational.py edit).
  * Alternate/cross-check source: `data/daemon_slayer/16.14.1/items.json` also
    has `gold.total` per item (verified). Prefer ddragon_items.json for parity
    with the client `/data/items_costs.json` basis and the existing loader.

The test harness (no live :8893 needed) + the shadow-first precedent:

  * `tests/test_build_plan_contract.py:85-124` - `_fake_seed_fn` +
    `_post(payload, seed_fn=...)` monkeypatch `_seed_fn_factory`, so the route
    runs with a deterministic seed and no live DS. Reuse verbatim (as C2/C6
    tests did) for the fed contract cases.
  * ROADMAP.md:24 (RC_CAPGAP_SHADOW) - the sanctioned shadow-first pattern: a
    default-OFF env flag guards a shadow-log append with NO served-field change,
    accruing live data before any user-visible flip. C3's shadow-log mirrors it.

## SCOPE + NON-SCOPE

IN SCOPE (all headless, all shippable this session):

  1. `core/build_planner/fed_threat.py` (NEW) - the pure estimator + `compute_fed` + a lazy
     item-gold-total map loader. Correct-by-construction + fail-soft.
  2. `dashboard/routes_build_plan.py` - parse `enemy_scores` + `enemy_levels`;
     compute `fed`; a shadow-log append behind `RC_FED_SHADOW` (default OFF); a
     `fed=` kwarg through `_resolve_enemy_profile` into the HINT profile, gated
     behind `RC_FED_HINT` (default OFF, so the chip stays dark).
  3. `web/js/panels/active_match.js` - emit `enemy_scores` + `enemy_levels`
     index-aligned with `enemies`; POST them + fold into the refresh fingerprint.
  4. Tests: `tests/test_fed_threat.py` (NEW) + `tests/test_build_plan_contract.py`
     additions (all RED-first, all client-mode).

NON-SCOPE (deferred / explicitly out):

  * The on-screen SURVIVE chip RENDER confirm - LIVE-GATED. Add a
    `docs/LIVE_GAME_GATED_SYNC.md` row: "enable RC_FED_SHADOW in a live game,
    accrue data/fed_shadow.jsonl fed rows, eyeball the SURVIVE chip once
    RC_FED_HINT is flipped on". The Electron overlay is agent-blind (same owed-
    proof posture as C2/C6 + the C4/C5 chips at LGS:5).
  * The default-ON flip of `RC_FED_HINT` - operator-gated, post-live-validation.
    This session ships it DEFAULT-OFF. NO blind default-on flip.
  * ANY edit to `situational.py` - the fed gate, `EnemyProfile.fed`, and the
    `build_enemy_profile(fed=)` kwarg are ALREADY shipped; touching them is a
    defect. `W_FED` / the C3 gate / `counter_build_hints` stay LOCKED.
  * ANY change to the DS-scored plan (`loop.tick` / `live[]` / `meta[]`). The
    champion-only `enemy_profile` (routes_build_plan.py:327) never gains `fed`.
  * A per-target chip (naming the fed enemy in the detail) - would need a
    situational.py detail-string edit. v1 keeps the generic "fed enemy - itemize
    defense" text; per-enemy naming is a future refinement.
  * Role / lane detection - the Live Client exposes NO positions (memory
    reference_liveclient_no_positions); the baseline is role-agnostic (below).
  * A graduated fed SCORE - `fed` is a bool (the dataclass field is bool). A
    0..1 fed intensity is a future schema lift, not this item.

## KEY INVARIANT: HINT-ONLY + SHADOW-FIRST (plan byte-identical, chip dark)

`fed` is populated ONLY on the counter-hint profile, NEVER on the `loop.tick`
`enemy_profile` (routes_build_plan.py:327). AND even on the hint profile it is
populated only when `RC_FED_HINT` is ON. So with both flags at their default
OFF: the DS-scored `live[]`/`meta[]` are byte-identical AND `counter_hints` is
byte-identical to today (no SURVIVE chip). The shipped session changes NOTHING
user-visible - it lands tested plumbing + a dark switch. This mirrors the
R102/R103 + C2 + C6 discipline and the RC_CAPGAP_SHADOW flip discipline exactly.

## DESIGN DECISIONS (pre-answered - the execution session decides nothing)

### The fed formula (ONE primary, named constants)

Per enemy X, `fed(X)` is TRUE when BOTH a combat-lead AND an economy-lead hold:

```
fed(X) := (kills(X) - deaths(X)) >= KDA_LEAD_CUT
          AND (est_gold(X) - est_gold(active_player)) >= GOLD_LEAD_CUT

est_gold(player) = sum(item_gold_total[id] for id in player.owned_items)
                   + LEVEL_GOLD * player.level

EnemyProfile.fed := any(fed(X) for X in enemies)     # any single fed enemy fires
```

Named constants (in `core/build_planner/fed_threat.py`, tunable - tests assert ordinal
relations + boundaries, never absolute floats):

  * `KDA_LEAD_CUT = 3`   - net kills-minus-deaths. A 3-0 / 5-2 / 7-4 enemy is
    snowballing; assists are deliberately excluded from the combat gate so a
    high-assist support does not read as a fed CARRY (defensive itemization is
    about a fed threat).
  * `GOLD_LEAD_CUT = 2000` - estimated-gold lead over the active player. ~ a
    Pickaxe-and-then-some ahead = a real completed-component item lead, well
    above owned-item noise. This is the "estimated-item-gold lead >= threshold"
    the premise asks for.
  * `LEVEL_GOLD = 130` - gold-equivalent per champion level, folding the premise's
    "plus level" into the single economy estimate (a 2-level lead ~ 260 gold, a
    modest secondary term dominated by items, as it should be). A pure level
    lead therefore ALSO nudges est_gold - satisfying the "OR level lead"
    alternative WITHIN one formula.

Why AND (conservative): mirrors the heal_threat / cc_threat "under-fire, never
mis-fire" philosophy. A 5-1 enemy WITH a 2000+ gold item lead is unmistakably
fed - the right bar for "buy an armor item vs them". Either signal alone (a
lucky 3-0 with no items, or an item lead from safe farming with an even
scoreline) is not yet "itemize defense NOW".

Why the ACTIVE PLAYER as the economy baseline (not a role median): the C3 chip
serves the active player's OWN itemization ("should I go defensive vs X"), so
"X is 2000+ item-gold ahead of ME" is the decision-relevant comparison. It is
role-agnostic (sidesteps the no-positions gap), stage-adaptive (my own economy
tracks the game clock), and - critically - needs NO new payload field: the
active player's `items` + `level` are ALREADY in every build-plan POST
(routes_build_plan.py:297,:300). It also handles the whole-enemy-team-fed case
(each enemy is compared to me, not to their own team's inflated median).

### Which enemy triggers the hint

ANY single enemy satisfying `fed(X)` sets `EnemyProfile.fed = True`, lighting the
one comp-level SURVIVE chip. The existing chip detail is generic ("fed enemy -
itemize defense"), so a bool is all situational.py needs. The shadow-log (below)
records WHICH enemy(ies) fired + their net-combat + est_gold + baseline, for
live validation.

### The hint text shape (mirrors C2/C6 - already shipped, no edit)

The chip is `counter_build_hints`' existing C3 output (situational.py:409-413):
`{criterion:"fed", satisfied:<build owns any survival stat>, severity:"high",
label:"SURVIVE", detail:"fed enemy - itemize defense",
suggest_class:"resist"}`. `_resolve_counter_hints` already `asdict`s it into the
`counter_hints[]` payload. Nothing to author on the render side.

### `core/build_planner/fed_threat.py` (NEW - mirrors core/cc_threat.py)

Pure, network/LLM/engine-free, fail-soft. Public surface:

```
def estimate_player_gold(item_ids, level) -> float:
    """sum(item gold.total over owned ids) + LEVEL_GOLD * level. Unknown id
    contributes 0 (truthful undercount, mirrors _playerItemValue). Fail-soft
    0.0 on bad / missing / non-list input."""

def compute_fed(enemies, enemy_items_by_player, enemy_scores, enemy_levels,
                my_item_ids, my_level) -> bool:
    """True when ANY enemy X satisfies the fed formula above. All enemy lists
    are index-aligned with `enemies`; a missing/short entry -> that enemy uses
    level 0 / kills=deaths=0 (fail-soft, so absent data never fires). Any
    non-list / junk input -> False."""
```

Item-gold map: a private one-time lazy load of `{id_str: float(gold.total)}`
from `data/meta/ddragon_items.json` (`data.<id>.gold.total`), coercing int-or-
str ids like `heal_threat._id_strs`. Any load failure -> empty map -> every
est_gold is level-only -> the economy gate simply never clears (graceful). Cite
the exact path so the executor does not re-derive it.

### `dashboard/routes_build_plan.py` (wire the shadow-first hint path)

  * Parse two NEW optional payload fields with fail-soft coercers mirroring
    `_coerce_enemy_items`: `enemy_scores` -> list of `{kills,deaths,assists}`
    ints index-aligned with `enemies` (`_coerce_enemy_scores`); `enemy_levels`
    -> list of ints (`_coerce_enemy_levels`). Absent/malformed -> None.
  * Compute `fed = compute_fed(enemies, enemy_items, enemy_scores,
    enemy_levels, owned, level)` where `owned` + `level` are the ALREADY-parsed
    active-player items + level. Fail-soft False (wrap in the route try/except).
  * SHADOW-LOG behind `RC_FED_SHADOW` (default OFF): when ON, append one JSON
    line to `data/fed_shadow.jsonl` (atomic-ish append, never raises into the
    route) recording `{ts, champion, mode, fed, per-enemy: name, net_combat,
    est_gold, baseline_gold}`. NO served-field change (pure accrual).
  * Extend `_resolve_enemy_profile` with a `fed=False` kwarg forwarded to
    `build_enemy_profile`. Populate the HINT profile's `fed` ONLY when
    `RC_FED_HINT` is ON (else pass `fed=False`). Build the hint profile whenever
    `enemy_items or heal_sources or cc_score or (RC_FED_HINT and fed)` is present;
    otherwise it stays the champion-only profile (today's behavior). The
    `loop.tick` `enemy_profile` (:327) is untouched.
  * `_resolve_counter_hints` already threads the profile into
    `counter_build_hints`; the C3 gate fires off `ep.fed` with no further change.

### `web/js/panels/active_match.js` (send the estimator inputs)

Extend `_extractBpEnemies` (or add `_extractBpEnemyScores`) to emit, index-
aligned with `names[]`: `scores[]` (`{kills,deaths,assists}` from `pl.scores`)
and `levels[]` (`pl.level | 0`). Add `enemy_scores` + `enemy_levels` to the
`_maybeRefreshBuildPlan` POST body and to the refresh fingerprint key (so an
enemy KILL / LEVEL-UP re-fires the plan, like an enemy PURCHASE does via
`_bpEnemyItemsKey`). Pure + unit-testable (no DOM/fetch), fail-soft to empty
lists on a non-array roster. The active player's items + level are already in
the body (the DS rerank key), so no `me`-side field is added.

## DATA FLOW

```
POST {champion, level(me), items(me), enemies, enemy_items,
      enemy_scores, enemy_levels}
  -> fed = compute_fed(enemies, enemy_items, enemy_scores, enemy_levels,
                       items(me), level(me))            # fed_threat
  -> [RC_FED_SHADOW on] append data/fed_shadow.jsonl    # accrual, no served change
  -> build_enemy_profile(..., fed=(fed if RC_FED_HINT else False))  # HINT profile only
  -> counter_build_hints(owned, hint_profile, ally_state)
  -> counter_hints[] gains the {criterion:"fed", label:"SURVIVE"} entry
     ONLY when RC_FED_HINT is on AND some enemy is fed
     (satisfied = build owns any armor/mr/health item).
```

## TESTABLE ACCEPTANCE CRITERIA (RED-first - write the failing test first)

`tests/test_fed_threat.py` (NEW):

  1. `estimate_player_gold`: two known items + level -> sum(gold.total) +
     LEVEL_GOLD*level (assert the additive decomposition, not a magic float);
     an unknown id contributes 0; empty items -> LEVEL_GOLD*level; non-list /
     None / junk -> 0.0 (fail-soft).
  2. `compute_fed` TRUE: one enemy with (kills-deaths) >= 3 AND est_gold >=
     my_gold + GOLD_LEAD_CUT -> True.
  3. `compute_fed` FALSE - combat only: net-combat >= 3 but NO gold lead ->
     False (proves the AND).
  4. `compute_fed` FALSE - economy only: a big gold lead but net-combat < 3 ->
     False (proves the AND boundary).
  5. `compute_fed` fail-soft: absent/short `enemy_scores` or `enemy_levels` ->
     that enemy reads 0/0 -> False; a non-list roster -> False; never raises.
  6. LEVEL contribution: two identical item sets, one enemy +N levels, pushes
     est_gold over the baseline (proves LEVEL_GOLD folds in).

`tests/test_build_plan_contract.py` (reuse the `_post` / `_fake_seed_fn`
harness, monkeypatch env):

  7. With `RC_FED_HINT=1` and a fed comp (enemy_scores + enemy_levels +
     enemy_items making one enemy clear both cuts) -> a `fed`/"SURVIVE" entry is
     present in `counter_hints`.
  8. With the flag OFF (default) and the SAME fed comp -> NO `fed` chip
     (shadow-only; proves the dark-switch default).
  9. `live[]` + `meta[]` are BYTE-IDENTICAL with vs without a fed comp AND with
     the flag on vs off (proves `loop.tick` is untouched - the load-bearing
     invariant).
  10. With `RC_FED_SHADOW=1` (sink monkeypatched to a temp path) a fed POST
      appends exactly one row; an unwritable sink does NOT raise into the route
      (200, `counter_hints` still present).

Optional `web/js/panels/*.test.mjs` (mirror the enemy-items extractor test):
the enemy-scores/levels extractor is index-aligned with `names[]`, excludes my
team, and fail-softs to `[]` on a non-array roster.

## R5 TIER

TIER-1 (RC-side local logic). Justification from the evidence: the ONLY files
are `core/build_planner/fed_threat.py` (new, a pure data reader), `dashboard/routes_build_plan.py`
(consumer plumbing), `web/js/panels/active_match.js` (payload), and their tests.
There is NO DS engine touch (`agents/daemon_slayer/*` untouched), NO
`ENGINE_VERSION` bump, NO DS schema / scorer / item-effect change, NO Share
mirror, NO `:8893` restart. Reading `gold.total` from a static data file is the
same category as heal_threat reading item ids or situational reading
ddragon_items.json tags - a data read, not an engine change. The situational.py
fed gate is already shipped (no edit). Per R5/R6: verify with `py_compile` +
the `test_fed_threat.py` module + the `test_build_plan_contract.py` cluster,
once, trust the exit code. RC reload only (asset-hash auto-reload covers the JS
per ADR-008). NO Tier-2 dual-suite / DS-restart tax.

## FILES TOUCHED

  * `core/build_planner/fed_threat.py` - NEW (estimator + compute_fed + gold-map loader).
  * `dashboard/routes_build_plan.py` - enemy_scores/levels coercers; compute
    fed; RC_FED_SHADOW append; fed= kwarg through _resolve_enemy_profile gated
    on RC_FED_HINT.
  * `web/js/panels/active_match.js` - enemy scores + levels extract + POST +
    fingerprint.
  * `tests/test_fed_threat.py` - NEW.
  * `tests/test_build_plan_contract.py` - fed contract cases.
  * (optional) a `web/js/panels/*.test.mjs` - the client extractor unit test.

## EST SESSIONS

ONE session. Model claude-opus-4-8, effort high (Tier-1 logic + a formula with
boundary tests; not a Tier-2 engine bump, but the estimator + AND-boundary +
shadow-log wiring warrant high effort for a clean single pass).

## DONE RITUAL

  1. `py_compile` the two .py files; run `tests/test_fed_threat.py` +
     `tests/test_build_plan_contract.py` (Tier-1 scope) - green before commit.
  2. Commit (ASCII body, `git commit -F` or single-quoted here-string) + push.
     No Share mirror, no `:8893` restart, no ENGINE bump.
  3. Append a `docs/LEDGER.md` entry (newest-first, NOT CLAUDE.md): C3 fed
     plumbing + shadow-log shipped, chip DARK behind RC_FED_HINT (default OFF).
  4. Update `ROADMAP.md:18` - move C3 from "remains (live-gated)" to "plumbed +
     shadow-first shipped; default-ON flip live-gated".
  5. Add a `docs/LIVE_GAME_GATED_SYNC.md` row: enable RC_FED_SHADOW in a live
     game, accrue `data/fed_shadow.jsonl`, validate the fed calls, then flip
     RC_FED_HINT default-ON + eyeball the SURVIVE chip on the Electron overlay.
  6. RC reload (`echo restart > restart_trigger.txt`); confirm health.json new
     pid + alive. A live `/api/build-plan` probe with a synthetic fed comp +
     `RC_FED_HINT=1` to confirm the SURVIVE chip populates + the plan is
     unchanged (headless backend proof; the pixel render is the LGS row).

## GHOST LIST (do NOT investigate / build / design against)

  * NO enemy gold, NO positions/roles, NO HUD/cooldown/buff/ward/XP data over
    the Live Client API (memory reference_liveclient_no_positions /
    reference_liveclient_no_hud_data). Enemy gold is ESTIMATED from items+level -
    do NOT hunt for an enemy-gold field or a role/lane API; there is none.
  * The C4/C5 enemy-items chips (resist / hp_vs_pen / pen_type) are SHIPPED,
    tested-green, awaiting only live pixel proof (LGS:5). Do NOT rebuild or
    re-verify them. C2 antiheal + C6 tenacity are SHIPPED (LEDGER 908/909) - do
    NOT re-plumb them.
  * Do NOT edit `situational.py` - `EnemyProfile.fed`, the C3 gate
    (`counter_build_hints:408`, `situational_fit:251`), `W_FED`, and the
    `build_enemy_profile(fed=)` kwarg are ALL already shipped. Editing the locked
    gating is a defect.
  * Do NOT touch the DS engine / `ENGINE_VERSION` / `agents/daemon_slayer/*` /
    the Share mirror / restart `:8893`. This item is Tier-1 RC-side and reads a
    static gold field only.
  * Overlay / Electron chip RENDER work belongs to the live-gated tail, NOT this
    session. Ship the plumbing dark; the operator flips + eyeballs live.
  * Do NOT surface any raw API / parse error in the UI - the estimator + route
    are fail-soft (bad input -> fed False -> no chip; unwritable shadow sink ->
    swallow + log). No credit / 400 / rate-limit string ever reaches a panel.
  * Do NOT add a graduated fed score, a per-enemy-named chip detail, or a role
    median - all are future refinements out of this v1 (would need a schema or
    situational.py edit).
  * em/en dashes banned (7-bit ASCII); frozen files untouched (routes_build_plan.py,
    situational.py, cc_threat.py, heal_threat.py, active_match.js are all NON-
    frozen - safe to edit).
