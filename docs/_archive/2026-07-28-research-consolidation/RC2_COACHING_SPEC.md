# RC 2.0 Phase 5 - Coaching Engine Upgrade (DESIGN SPEC)

Status: DESIGN ONLY (no code in this artifact). Authored 2026-06-19.
ASCII-only. Every cited module/field was grepped and read; file:line references
are load-bearing.

North star (charter 4b): drive live in-game Haiku spend toward ZERO by replacing
LLM coaching calls with deterministic precompute, validated do-not-flip-blind via
shadow logging BEFORE any flip. This spec extends the existing HZ precompute +
shadow program; it does not re-architect it.

---

## 0. Ground truth - what RC already has (verified)

### 0a. Live signal sources at request time

Two parallel feeds reach the coach state builder. Both already exist:

1. `dashboard/_liveclient.py::liveclient_summary()` (the `lc` dict). Read off the
   Live Client `:2999` snapshot relayed through `:8889`, cached in
   `core/liveclient_cache.py` (0.5s poll, immutable Snapshot, `age_s`, `no_game`).
   Fields confirmed present (`_liveclient.py:96-205`):
   - `game_time_s` (int), `game_time` (str), `level`, `gold` (currentGold),
     `hp` / `hp_max` (currentHealth / maxHealth),
     `mana` / `mana_max` (resourceValue / resourceMax) - line 101-104,
   - `kda` (str "K/D/A"), `cs` (creepScore), `champion` (championName) - 112-114,
   - `owned_items` (display names) + `owned_item_ids` (parallel id list) - 115-119,
   - `enemy_team` / `ally_team` (championName lists) - 122-128,
   - `enemy_item_ids` / `ally_item_ids` (public scoreboard items for all 10) - 133-138,
   - `players[]` (position ROLE string, team, creep_score, is_active) - 144-153,
   - `kill_participation_pct` (when team_kills > 0) - 162-173,
   - `game_mode`, `game_id`, `inhib_events` ({down_at_s, name}) - 176-204.

2. `core/vision_tracker.py` (the `data/vision_state.json` fog model). Derives
   enemy visibility from Live Client position-tick freshness (`_POS_EPSILON 5.0`,
   `_VISIBILITY_STALL_S 2.5`). Emits per-enemy `{visible, is_dead, respawn_in_s,
   missing_for_s, last_seen_zone, level}` plus a `summary` (`visible_count`,
   `missing_count`, `dead_count`) - `vision_tracker.py:169-184, 376-388`. ARAM/KIWI
   are shared-vision so it stamps `on_bridge` (`_SHARED_VISION_MODES`, line 51).

3. Screen OCR / Sonnet vision (`modes/shared_vision.py` + `vision_server/`). Tiered:
   OCR first via `core/vision_routing.read_or_escalate`, Sonnet escalation for
   misses (`shared_vision.py:165-209`). Regions calibrated in
   `data/vision_regions.json` (timer, level, hp, mana, gold, kda, cs, ally_*_hp/mana,
   ally_ults, ally_levels, enemy_deaths, death_timer).

### 0b. Deterministic precompute already shipped

- `core/laning_scenario_precompute.py` - offline sweep of the DS matchup engine
  over `(my_champ x enemy x level-band x mana-state x cd-state)` -> verdict
  (`all_in`/`trade`/`back_off`/`even`), `net_swing`, `pct_my_removed`,
  `pct_enemy_removed`, plus an HZ-A2 `economy` block (`recall`, `next_spike`,
  `gold_at_band`). Tables in `data/daemon_slayer/laning_scenarios/<patch>/` (LFS).
  Bands GENERATED = `GEN_BANDS = (L2, L6, L11)`; L16 fail-softs to L11 (line 134).
- `core/precomputed_laning_coach.py` - request-time reader: one cell -> two A/B
  `CoachChoice`. `_VERDICT_LABELS` (line 58-63), `band_for_level` /
  `mana_state_for` / `cd_state_for`. SOURCE_TAG `ds-precompute`.
- `agents/daemon_slayer/matchup.py::compute_matchup` - the live 1v1 engine
  (`_classify` thresholds: `_ALL_IN_KILL_THRESHOLD 1.0`, `_TRADE_MARGIN 0.10`,
  `_EVEN_BAND 0.05` - lines 34-36, 184-206). NO `hold`/`farm` verdict exists.
- `core/event_callouts.py` - pure objective + spike schedule (`next_callouts`):
  drake 5:00 cadence, herald 14:00, baron 20:00, plates 14:00, elder ~35:00,
  level spikes 6/11/16, item spikes 1/2/3, recall-affordability, inhib respawn 300s.
- `core/lead_projection.py` - pure macro read (`project_lead`): state
  (ahead/even/behind) x magnitude (slight/clear/large) x phase (early/mid/late) ->
  one directive line. Weights per mode (`_WEIGHTS`, line 84-93). Also hosts the
  gold-income + spike-ladder model (`expected_gold_earned`, `next_spike`,
  `spike_eta_seconds`, `SPIKE_COMPLETE`).
- `dashboard/_deterministic_coaching.py` - the resolver wired into `/api/state`
  via `dashboard/_state_builder.py:351-370`. `compute_deterministic` fans out
  `laning_choices` + `next_callouts` + `project_lead`, TTL-cached 3.0s on a coarse
  sig, warm-path single-flight refresh. `resolve_choices` is deterministic-FIRST
  (line 505-524): det choices win, else native, else synth.

### 0c. Shadow / validation substrate (do-not-flip-blind)

- `core/hz_choice_shadow.py::log_precomputed_choices` - records, per live tick,
  what the precompute WOULD offer vs the native Haiku action, with `covered` flag,
  to `data/hz_choice_shadow.jsonl`. Coarse-state dedup + frozen-game_time guard.
- Wired at `_deterministic_coaching.py:636-708`
  (`shadow_log_precomputed_choices`), fired from `_state_builder.py:366`.
- `tools/hz_shadow_report.py` - the offline agreement reader (confusion matrix).

### 0d. CRITICAL live finding (ground truth, not aspiration)

`ops/audit/HZ_HAIKU_CALL_INVENTORY.md:49-108` (runs 2026-06-19-01/02). Over
1490 live laning shadow rows / 693 comparable-covered ticks (42% table coverage):

- **Laning det-vs-Haiku agreement = 39% (160/406 comparable).** The flip is held
  by the do-not-flip-blind gate. The blocker is CALIBRATION, not games played.
- **Root cause:** the precompute verdict vocabulary only ever emits `back_off`
  (225) or `trade`/`even` (181). It has NO `hold`/`farm` band, but Haiku says
  `hold` on 114/406 ticks (28%). And it is back_off-biased (precompute back_off
  225 vs Haiku 69). Top mismatches: precompute `back_off` while Haiku `trade` x112;
  `back_off` while Haiku `hold` x57; `trade` while Haiku `hold` x57.
- **Quantified opportunity:** all 181 precompute-"trade" ticks are actually the
  `even` verdict (whose B-chip is already "Hold position"); 57 faced Haiku `hold`.
  An `even`<->`hold` mapping decision alone moves 39% -> 53%.

This finding is the spine of Workstream 1: the upgrade is NOT a new engine, it is
(a) a `hold`/`farm` verdict band + back_off softening + CV-gated confidence, then
(b) re-measure agreement, then (c) flip.

---

## Workstream 1 - Haiku-free laning coach tuned for local CV

### 1.1 CV signal map (reliably captured vs missing)

| Signal | Source | Reliability for laning |
|---|---|---|
| my HP / HP_max | lc.hp/hp_max (`_liveclient.py:101`), OCR fallback | RELIABLE (activePlayer) |
| my mana / max | lc.mana/mana_max (line 103), `_mana_fraction` (`_det:560`) | RELIABLE when champ has mana |
| my level | lc.level / OCR | RELIABLE |
| my CS | lc.cs / OCR | RELIABLE |
| my gold | lc.gold (activePlayer-only) | RELIABLE (on-hand, post-buy) |
| my items | lc.owned_items / owned_item_ids | RELIABLE |
| enemy comp | lc.enemy_team | RELIABLE (full roster) |
| enemy items | lc.enemy_item_ids (public scoreboard) | RELIABLE for all 10 |
| enemy laner HP | OCR ally panel is ALLIES only; enemy HP not in lc | MISSING live (no enemy HP bar feed) |
| enemy laner mana / level | not in lc; enemy level inferable from time | PARTIAL (level mirrored to mine today) |
| enemy VISIBLE / missing / zone | vision_state.json (`vision_tracker`) | RELIABLE (position-tick fog) |
| enemy DEAD + respawn_in_s | vision_state enemies[].respawn_in_s | RELIABLE when isDead |
| my ult cooldown / ability CDs | NOT surfaced to coach dict today (`_det:673` note) | MISSING - defaults to all_up |
| wave state / minion count | NOT captured (no minion OCR region) | MISSING |
| enemy position coords | Live Client position = ROLE string, never coords (memory) | MISSING (map dots impossible) |
| jungler location | derivable from vision_state enemies[role=JUNGLE].visible/zone | PARTIAL (shared with fog model) |

Key gaps that bound determinism: enemy laner exact HP, my real ability cooldowns,
and wave/minion state. The design treats these as CONFIDENCE-LOWERING unknowns
(conservative defaults), not fabricated inputs - consistent with
`laning_verdicts.py:272` ("enemy level mirrors mine when unknown; enemy items
unmodeled" - honest lower-fidelity, documented).

### 1.2 Deterministic laning decision logic

Inputs (all already assembled by `_build_game_state`, `_det:222-297`):
`my_champion`, `enemy_comp`, `level`, `mana_fraction` (`_mana_fraction`),
`my_item_ids`, plus NEW CV reads: enemy `visible`/`is_dead`/`respawn_in_s`/`zone`
from `vision_state.json`, and my `hp_fraction = lc.hp/lc.hp_max`.

Decision pipeline (pure, ordered; first match wins):

```
1. ENEMY DEAD (vision_state enemy.is_dead, respawn_in_s > 0)
   -> verdict = "free_farm" / "shove"  (confidence high)
      "Enemy dead {respawn_in_s}s - shove + take plates/prio"
2. ENEMY MISSING (not visible, missing_for_s >= MISS_THRESHOLD ~3s)
   -> verdict = "back_off" downgrade to "cautious"  (confidence mid)
      "Enemy missing {missing_for_s}s - back off, ward, don't overextend"
3. MY HP LOW (hp_fraction < LOW_HP ~0.35) AND verdict would be aggressive
   -> override to "disengage"  (confidence high)
4. CORE TRADE VERDICT from the precompute cell (precomputed_laning_coach):
   resolve cell by (champ, enemy, band, mana_state, cd_state).
   Apply the NEW recalibrated verdict band (1.3) -> one of:
      all_in / trade / even / hold / back_off
5. CONFIDENCE GATE (1.4): if net signal is thin or unknowns dominate,
   downgrade confidence; if below FLOOR, emit Haiku fallback (1.5).
```

Layers 1-3 are CV-driven overrides the current precompute does not model and are
the highest-value adds (enemy dead/missing is the single most common real laning
decision and is fully deterministic from `vision_state.json`).

### 1.3 The hold/farm band (closes the 39% gap)

Add a fifth verdict `hold` between `even` and `back_off`, derived WITHOUT
re-running the engine - it is a reinterpretation of existing cell scalars plus the
`even` remap the audit already quantified:

```
def laning_band(cell, hp_fraction, enemy_missing):
    swing = cell["net_swing"]; my_removed = cell["pct_my_removed"]
    enemy_removed = cell["pct_enemy_removed"]
    if enemy_removed >= 1.0 and my_removed < 1.0:        return "all_in"
    if my_removed >= 1.0:                                return "back_off"
    if swing <= -HOLD_LOW (~-0.05) and swing > -BACK (~-0.18):
                                                          return "hold"   # NEW
    if swing <= -BACK:                                   return "back_off"
    if swing >= TRADE (~0.10):                           return "trade"
    return "even"  # mapped to hold-eligible per 1.3a
```

1.3a `even` -> chip decision: the existing `even` A-chip "Even trade on your cd
window" is back-off-biased in practice (audit). Re-label the `even` verdict's
**A-chip to "Hold / poke" and B to "Trade on cd window"** so the dominant x267
`even` cell agrees with Haiku's `hold` (the audit's +57-tick, 39->53% win). This
is a pure label/threshold change in `core/precomputed_laning_coach.py::_VERDICT_LABELS`
+ a softened `_TRADE_MARGIN`/`back_off` threshold; it does NOT require regenerating
the LFS tables for the label half (only the threshold-softening half needs a
re-sweep, gated).

### 1.4 Confidence gating

`CoachChoice.confidence` is already a 3-band field (low/mid/high,
`coach_choices.py:38`). Gate:

```
confidence = base_from_swing_magnitude(|net_swing|)   # existing _confidence_for
- 1 band if mana_fraction is None (can't see resources)
- 1 band if enemy not in vision (missing/fog -> trade math is stale)
- 1 band if my ult cd unknown AND verdict depends on R (cd_state all_up default)
- floor at "low"
emit_haiku_fallback = (confidence == "low" AND verdict in {all_in, back_off})
```

Rationale: a low-confidence aggressive verdict (all-in / hard back) is exactly the
case where being wrong is costly, so that is the only case we pay for Haiku.
Even/hold/trade at low confidence are safe enough to serve deterministically.

### 1.5 Haiku fallback (narrow)

When `emit_haiku_fallback` is true, fall through to the EXISTING coach Haiku path
(`coaches/*_coach.py`) for that tick only - no new call site, just do NOT override
`coach["choices"]` with the deterministic set (the resolver already falls back to
native/synth when det is empty - `resolve_choices`, `_det:505`). So "fallback" =
emit `[]` from the deterministic laning producer, which is already a supported
degradation path. Zero new wiring.

### 1.6 Implementation plan (WS1)

Modules to ADD:
- `core/laning_cv_overrides.py` - pure: reads `data/vision_state.json` (enemy
  dead/missing/zone) + hp_fraction, returns an override verdict + confidence delta
  or None. Fail-soft `{}` on missing file (mirrors `vision_tracker` consumers).
- `core/laning_band.py` (or extend `precomputed_laning_coach`) - the 5-band
  classifier (1.3) + confidence gate (1.4). Pure, unit-testable.

Modules to EDIT:
- `core/precomputed_laning_coach.py` - `_VERDICT_LABELS` relabel for `even`/`hold`
  (1.3a); add `hold` entry. (Tier-1 logic; not frozen.)
- `dashboard/_deterministic_coaching.py::_compute_uncached` - after
  `laning_choices`, apply `laning_cv_overrides` + band reclassification before
  emitting `choices`. (Not frozen.)
- `agents/daemon_slayer/matchup.py::_classify` thresholds - ONLY the softened
  `_TRADE_MARGIN`/back_off margin, GATED, requires LFS table re-sweep + re-measure.
  This is the one Tier-2 piece; defer behind the agreement re-measurement.

Default-OFF + shadow-first:
- The CV-override + hold-band path writes to the EXISTING
  `data/hz_choice_shadow.jsonl` via `log_precomputed_choices` (it already records
  `native_action` vs precompute `choices` - `hz_choice_shadow.py:39`). Add the new
  verdict/confidence to that record so `tools/hz_shadow_report.py` can re-compute
  agreement WITH the hold band and CV overrides applied, on the same live games,
  BEFORE the served `choices` change.
- Flip = a single switch in `resolve_choices`/`_compute_uncached` that lets the new
  band drive the served chips. Hold it until the report shows agreement climbs
  (target: 39% -> >=70%) on accrued real games (operator/Gemini-gated per
  `HZ_HAIKU_CALL_INVENTORY.md:75`).

Validation:
- Unit: 5-band classifier truth table; CV-override precedence (dead > missing >
  low-hp > trade); confidence-downgrade per missing signal; `[]` fail-soft on
  absent vision_state.
- Live: re-run `tools/hz_shadow_report.py` confusion matrix after N games; gate on
  the agreement delta, not a guess.

---

## Workstream 2 - ABC choices: explicit triggers + condition-change branching

### 2.1 The gap

`CoachChoice` (`core/coach_choices.py:44-64`) carries
`key/label/expected_outcome/confidence/source_tag`. There is NO field naming the
TRIGGER/CONDITION under which the choice holds, and no notion of "if X changes,
switch to option B". The chips are a static snapshot per tick.

### 2.2 Schema extension (additive, back-compatible)

Add three OPTIONAL fields to `CoachChoice`, appended at the END with defaults
(per CLAUDE.md "Python Conventions" - never insert mid-class):

```
@pydantic.dataclasses.dataclass(frozen=True)
class CoachChoice:
    key: str
    label: str
    expected_outcome: str = ""
    confidence: str = "mid"
    source_tag: str = ""
    trigger: str = ""          # NEW: the live condition this option assumes
    rebranch_when: str = ""    # NEW: the observable change that flips the rec
    rebranch_to: str = ""      # NEW: which key (A/B/C) to switch to then
```

`to_dict`/`asdict` stay byte-stable for existing fields (the P2.2 golden master
guards them - `coach_choices.py:50`), new keys default empty so old consumers and
the dashboard renderer ignore them until the UI opts in.

### 2.3 Trigger + re-branch derivation (deterministic)

The trigger is already KNOWN at cell-resolution time - it is the lookup key. Stamp
it instead of discarding it:

```
trigger        = "{enemy} {mana_state} mana, {cd_state}, lvl {level}"
                 e.g. "Zed full mana, ult up, lvl 6"
rebranch_when  = the nearest axis that would change the verdict, computed by
                 probing adjacent cells (cheap - same loaded payload):
                   - if enemy currently visible: "if {enemy} roams / goes missing"
                     -> rebranch_to the back_off/cautious option
                   - if my ult down (cd_state no_ult): "when your ult comes up"
                     -> rebranch_to the all_in/trade option (probe the all_up cell)
                   - if mana_state low: "after you back / hit full mana"
                     -> rebranch_to the full-mana cell's verdict
rebranch_to    = the key (A/B/C) whose verdict the adjacent cell produces
```

The jungler example from the brief becomes concrete: when the enemy jungler shows
on the map (`vision_state` JUNGLE-role enemy `visible=True` in your lane zone), the
override layer (WS1) flips the served chip to the disengage option and the
`rebranch_when`="if jungler shows top" / `rebranch_to`="B" is the pre-stated reason.

### 2.4 Worked example

```json
[
  {"key":"A","label":"Trade Zed now","confidence":"mid",
   "expected_outcome":"net swing +0.14; remove 38% of Zed, lose 22%",
   "source_tag":"ds-precompute",
   "trigger":"Zed full mana, ult up, lvl 6, enemy visible",
   "rebranch_when":"if jungler shows top or Zed goes missing",
   "rebranch_to":"B"},
  {"key":"B","label":"Hold / poke","confidence":"mid",
   "expected_outcome":"play safe; reassess next tick",
   "source_tag":"ds-precompute","trigger":"enemy missing or ganked",
   "rebranch_when":"when your team is in vision again","rebranch_to":"A"}
]
```

### 2.5 Implementation plan (WS2)

- EDIT `core/coach_choices.py` - append the 3 fields (defaults); `parse_choices`
  sanitizes them (string-coerce + length cap, same as label). Update the P2.2
  golden-master test to assert the new keys default to "".
- EDIT `core/precomputed_laning_coach.py::_build_choices` - populate `trigger`
  from the resolved key tuple; populate `rebranch_when`/`rebranch_to` by probing
  the adjacent cell (pure, same payload, no engine call).
- EDIT the dashboard chip renderer (`web/js/panels/*` choice panel) to show the
  trigger as a sub-line and `rebranch_when` as a muted "-> switch to B if ..." hint.
  (Tier web; runs the UI fixture ritual per CLAUDE.md.)
- Shadow-first: the new fields ride the existing `hz_choice_shadow` records (they
  are inside the `choices` list already logged). No served change until the chip
  UI lands; validate the trigger/rebranch text reads correctly off accrued rows.

Validation: unit test the trigger string + adjacent-cell rebranch resolution
(deterministic given a fixture payload); UI audit for the sub-line layout.

---

## Workstream 3 - Mid/late-game + objective playbooks

### 3.1 What exists vs the gap

`core/event_callouts.py` already gives the SCHEDULE (drake 5:00, baron 20:00,
herald 14:00, elder, plates, inhib respawn, level/item spikes) and
`core/lead_projection.py` gives the ahead/even/behind macro line. The GAP is a
deterministic playbook that JOINS them: "given (objective spawning in T) x (you are
ahead/even/behind) x (phase), here is the setup + the fight/concede rule".

### 3.2 State inputs (all already derivable)

| Input | Source |
|---|---|
| next objective + eta_s | `event_callouts.next_callouts` (already in `det["callouts"]`) |
| lead state + magnitude | `lead_projection.project_lead` (already in `det["lead_projection"]`) |
| phase (early/mid/late) | `lead_projection._phase(game_time_s)` |
| enemy visible/missing count | `vision_state.summary` (visible_count/missing_count/dead_count) |
| enemy dead + respawn | `vision_state.enemies[].respawn_in_s` |
| my spike (lvl/item) | `next_callouts` level_spike/item_spike entries |

### 3.3 Rule table (objective x lead -> directive)

A pure dict keyed `(objective_tag, lead_state)` returning a setup line + a fight
rule. Magnitude/phase select within a tuple, mirroring `lead_projection._LINES`.

```
OBJECTIVE_PLAYBOOK = {
  ("dragon","ahead"):  ("Set deep vision, force them off it",  "Fight - you have tempo"),
  ("dragon","even"):   ("Match prio, ward both entrances",     "Fight only with prio + numbers"),
  ("dragon","behind"): ("Trade it for a different lane/turret", "Do not contest 5v5 down"),
  ("baron","ahead"):   ("Ward 30s early, zone them off",       "Start with vision + a pick"),
  ("baron","even"):    ("Get a pick first, then start",        "No pick = no baron"),
  ("baron","behind"):  ("Do not face-check, defend base",      "Only take on their mistake / ace"),
  ("herald","ahead"):  ("Take it, slam a plated turret",       "Solo or duo, keep prio"),
  ("herald","even"):   ("Contest only with prio",              "Trade for scuttle/plates if contested"),
  ("herald","behind"): ("Give herald, catch side waves",       "Avoid the 50/50"),
  ("elder","*"):       ("Group as 5, full vision",             "Elder fight is the game - no greed"),
}
```

Selector adds CV: if `vision_state.summary.missing_count >= 3` near an objective
spawn, append "enemies grouping/missing - assume contest"; if `dead_count >= 1` on
the enemy team with `respawn_in_s` covering the objective window, upgrade
ahead-line to "free objective - take it now".

### 3.4 Output

A new callout `kind = "playbook"` appended to `det["callouts"]` (the dashboard
already renders the callouts list). Eta-sorted with the existing objective rows via
`event_callouts._sort_key`. One row, <= 12 words, ASCII.

### 3.5 Implementation plan (WS3)

- ADD `core/objective_playbook.py` - pure: `playbook_callout(callouts, lead,
  vision_summary, phase) -> dict | None`. No engine, no network (same contract as
  `event_callouts`). Fail-soft `None`.
- EDIT `dashboard/_deterministic_coaching.py::_compute_uncached` - after `callouts`
  + `lead` are computed, call `playbook_callout` and splice the row (it already
  splices heal-threat the same way - `_det:413-418`).
- Read `vision_state.json` once per compute (cheap; `vision_tracker` writes it
  atomically). Cache via the existing `_CACHE` sig (add objective+lead to the sig).
- Shadow-first: log the playbook directive into a NEW `data/objective_playbook_
  shadow.jsonl` (mirror `hz_choice_shadow`) alongside the native coach `objective`
  field, so the deterministic objective call can be compared to Haiku's objective
  prose before it influences the served `objective`. Default-OFF for the served
  field; the callout row can ship first (additive, no Haiku replacement) while the
  `objective` field flip waits on agreement data.

Validation: unit truth-table over (tag x state x magnitude); CV-upgrade branches
(missing_count/dead_count); fail-soft on absent vision_state. Live: shadow-agreement
of playbook objective vs Haiku objective.

---

## Workstream 4 - Lost-objective + stagnation response

### 4.1 Trigger detection (deterministic, from live events)

Two trigger families, both from data RC already reads:

A) LOST-OBJECTIVE - infer from Live Client events + vision. The Live Client
`gameData.events.Events` stream already feeds `inhib_events` (`_liveclient.py:190`).
The same stream carries `DragonKill`/`BaronKill`/`HeraldKill`/`TurretKilled` events
(standard Live Client `EventName`s). Surface them the same way `inhib_events` is
surfaced (a parallel `objective_events` list: `{name, killer_team, down_at_s}`).
A "lost" objective = an enemy-team kill event for dragon/baron/herald within the
last ~LOSS_WINDOW (~45s).

B) STAGNATION - pure function of the existing signals over time. Stall = no lead
swing + no objective taken for a sustained window. Detect via a small rolling state
(the dashboard already holds per-game state):

```
stagnant = (game_time_s > 1200)                       # past 20 min
           AND no objective_event (either team) in last STALL_S (~150s)
           AND |project_lead composite| within EVEN band for last STALL_S
           AND no inhibitor down on either side
```

### 4.2 Response table

```
LOST_OBJECTIVE_RESPONSE = {
  ("dragon","behind"): "Lost drake - catch waves, do not force, scale to next",
  ("dragon","ahead"):  "Drake gone but you lead - pressure a side lane / next obj",
  ("baron","*"):       "Baron lost - group + defend, clear waves, wait for buff to fade",
  ("herald","*"):      "Herald lost - match the plates they take, trade mid prio",
}

STAGNATION_RESPONSE (lead-keyed, pick ONE):
  ahead:  "Stalled but ahead - force vision + a pick, then objective",
  even:   "Stalled - take a side lane to create a pick, do not coinflip 5v5",
  behind: "Stalled + behind = good - keep scaling, take safe CS, wait them out",
```

The four canonical actions the brief names map cleanly:
- SPLIT -> stagnation "take a side lane / pressure a side lane" (ahead/even).
- RESET -> lost-objective "catch waves / clear waves" (recover tempo + gold).
- PICK -> stagnation "force a pick" (the standard break-the-stall lever).
- DISENGAGE / SCALE -> behind responses ("do not force", "wait them out").

### 4.3 Implementation plan (WS4)

- EDIT `dashboard/_liveclient.py::liveclient_summary` - emit `objective_events`
  from the same `gameData.events.Events` loop that builds `inhib_events`
  (isolated try, fail-soft `[]`, identical pattern at line 188-199). (Not frozen.)
- ADD `core/macro_response.py` - pure: `lost_objective_response(objective_events,
  lead, game_time_s)` + `stagnation_response(objective_events, lead, game_time_s,
  inhib_events)`. Returns a callout dict (`kind="macro_response"`) or None.
  Stagnation needs a short time-window memory; keep it in the resolver's module
  state (like `_det`'s `_LAST_GOOD`), NOT in the pure module, so the pure function
  stays testable with explicit timestamps.
- EDIT `dashboard/_deterministic_coaching.py` - call both, splice the row (same
  pattern as heal-threat / playbook).
- Shadow-first: these are ADDITIVE callout rows (a new advisory the coach did not
  previously emit), so they can ship without replacing any Haiku call - lower risk
  than WS1. Still log to `data/macro_response_shadow.jsonl` for a sanity pass that
  the triggers fire at the right moments on real games before surfacing in the UI.

Validation: unit - fire `objective_events` fixtures (enemy baron 30s ago + behind
-> the defend line); stagnation true/false around the window/lead/inhib conditions;
fail-soft on empty events. Live: confirm triggers fire at correct moments in
shadow log over real games; UI fixture ritual when the row surfaces.

---

## Cross-cutting conventions (all workstreams)

- Pure modules read NO network and NO LLM (mirror `event_callouts` /
  `lead_projection`); impure file reads (`vision_state.json`, build orders) live in
  the dashboard resolver and pass data in.
- Fail-soft everywhere: any missing key / absent file -> fewer/empty outputs, never
  raises (the coach hot path contract - `precomputed_laning_coach.py:273`).
- ASCII-only, no em/en/smart-quotes (CLAUDE.md hard rule).
- New dataclass fields appended at END with defaults (CLAUDE.md Python Conventions).
- Shadow-log-FIRST for anything that REPLACES a Haiku output (WS1 served chips, WS3
  served `objective`); additive callout ROWS (WS3 playbook row, WS4 macro rows) may
  ship without a flip since they add a surface rather than replace a paid call.
- Flip gate = `tools/hz_shadow_report.py`-style agreement delta on accrued REAL
  games, operator/Gemini-gated - never a blind overnight flip
  (`HZ_HAIKU_CALL_INVENTORY.md:75`). Tier-2 (engine threshold / LFS table re-sweep)
  only for the matchup `_classify` softening; everything else is Tier-1 logic + a
  Tier-web UI pass.

---

## SUMMARY + 3 highest-leverage steps

Summary: RC already has the deterministic spine (matchup precompute + objective
table + lead projection) wired into `/api/state` with a working shadow-log
validation loop. The coaching upgrade is NOT new infrastructure - it is (1) adding
a `hold`/`farm` verdict band + CV-driven enemy-dead/missing overrides to close the
measured 39% laning-agreement gap, (2) stamping the already-known lookup key onto
each chip as an explicit trigger + condition-change re-branch, (3) joining the
objective schedule with the lead read into a deterministic playbook row, and (4)
adding lost-objective + stagnation advisory rows off Live Client kill events. Every
piece is pure Python, fail-soft, and validated do-not-flip-blind via the existing
`hz_choice_shadow` + `hz_shadow_report` loop before any served output changes.

Highest-leverage implementation steps (in order):

1. **WS1 hold-band + `even` relabel (Tier-1, biggest measured win).** Add the
   5-band classifier and relabel the `even` verdict's A-chip to "Hold / poke" in
   `core/precomputed_laning_coach.py::_VERDICT_LABELS`; emit the new verdict into
   the existing `hz_choice_shadow.jsonl`, then re-run `tools/hz_shadow_report.py`.
   The audit already quantifies this as 39% -> ~53%+ agreement with zero engine
   re-sweep and zero served-output change until the gate clears.

2. **WS1 CV overrides (Tier-1, highest decision value).** Add
   `core/laning_cv_overrides.py` reading `data/vision_state.json` for enemy
   dead/missing/zone + my hp_fraction, applied in
   `dashboard/_deterministic_coaching.py::_compute_uncached` ahead of the trade
   verdict. Enemy-dead-shove and enemy-missing-back-off are the most common real
   laning decisions and are fully deterministic from data RC already writes -
   shadow-logged first, then gated.

3. **WS3 objective playbook row (additive, no flip needed).** Add
   `core/objective_playbook.py` joining `det["callouts"]` + `det["lead_projection"]`
   + `vision_state.summary` into one `kind="playbook"` callout, spliced like the
   existing heal-threat row. It ships as a NEW advisory (no Haiku replacement, so no
   flip gate blocks it) and immediately enriches drake/baron/herald/elder coaching.
