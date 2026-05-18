# ADR-007: Event-driven coaching pivot

**Date:** 2026-05-11
**Status:** Accepted (s169 - phased rollout begins)

## Context

The four mode coaches (SR / ARAM / Arena / Brawl) operate on a debounce loop:
`_poll_loop` fetches Live Client state every 1.5 s and calls `_maybe_coach()`
which fires whenever `now - _last_coach > _DEBOUNCE_S` (default 8 s). The
result is a continuous narration stream - useful when nothing else is
happening, actively harmful when the player is mid-fight and the warning
("you are low HP") is already two seconds stale by the time it renders.

Three concrete pain points the operator cited (s169 discussion):

1. **Reactive warnings the player already knows.** "Don't tell me 3× I'm
   low HP mid-fight when by the time I look at the UI I'm already dead."
2. **Wasted tokens on non-actionable narration** - the coach spends Sonnet
   budget describing the situation rather than surfacing a decision.
3. **Missing the actually-pivotable moments** - jungler last seen near my
   lane with full clear in their pocket, contesting a 4v5 baron because
   nobody warned about MIAs, throwing a gold lead by overstaying after
   trades.

Meanwhile, `core/decision_detector.py` has shipped a complete event-driven
coaching infrastructure since 2026-05-01 (Tier 3 #15):

- `DECISION_REGISTRY` extensible detector pattern (one function = one
  pure trigger; just append to the registry).
- `Decision` dataclass with A/B `options`, deterministic `id`, expiry,
  context.
- `DecisionStore` - atomic pending list + JSONL log with cross-process
  portalocker.
- `DecisionLoop` - daemon thread in the Phase 3 supervisor, polls
  `liveclient_cache` + `vision_state.json` every 1 s, dedupes by id,
  rate-caps at 5/game + 30 s min-gap.
- `/api/decisions` GET + `/api/decisions/<id>` POST + dashboard banner
  (`coach-decisions` panel) with one-click resolution.
- Five detectors shipped: `objective_contest_with_missing`, `low_hp_back`,
  `lane_roam_window`, `postfight_objective`, `kill_diff_objective`.

But the only entries in `data/decisions_log.jsonl` are smoke-test rows -
the system has never fired in a real game because the operator played
five matches in five months and the existing detectors are
SR-+-mid-game-only. The infrastructure is solid; the detector library
is undersized and the dashboard banner is not glanceable enough during
gameplay.

## Decision

Pivot RC's coaching surface from **continuous narration** to
**event-driven decisions**, extending the existing `decision_detector`
infrastructure rather than rebuilding it. Three concurrent workstreams:

1. **Expand the detector library** - one trigger per pivotable moment
   identified in the s169 discussion: jungler-gank-likely, throwing-lead,
   wave-freeze-window, augment-fit (Arena), end-game-plan-fork.
   Append-only - never edit an existing detector's id once decisions
   are in the log.
2. **Glanceable heartbeat surface** - `#trigger-pill` in header row 2
   (next to `#ds-pill`) shows the eval counter + alive indicator so the
   operator can confirm the system is watching without reading prose.
   Resets on new-game detection. The full banner stays as the
   when-something-fires UI.
3. **Postmortem-from-rewind_history.db** - offline `scripts/postmortem_analyze.py`
   mines the local match DB for per-player death patterns (overstay,
   1v2+, throw-lead) and writes `data/coaching/death_patterns.json`.
   Realtime coach system prompts pick up the player's top-3 death modes
   as PERSONAL CONTEXT so live advice is calibrated to actual mistakes
   instead of generic patterns. Deferred to a follow-up session - out
   of scope for s169 ship.

In parallel, **tighten the existing narration coaches** to defer to
the decision detector for moments it covers. The mode coaches keep
the build-recommendation / item-tile / lane-state surfaces but stop
firing prose Sonnet calls on situations the detector already owns.
This shifts the token budget from narration to decision-fork Sonnet
calls (higher quality at the moment when it matters).

## Consequences

**Good:**
- Token spend reframes from O(20 prompts/game) to O(3–5 decisions/game).
  At that volume metered Anthropic API is the right answer; the
  Max-plan workaround discussion from s169 (P6) becomes moot.
- The coach respects the operator's attention budget - silent when
  nothing pivotable is happening, surfaces a decision when it is.
- Detector library grows cheaply: one function appended to the
  registry per new trigger. Each detector is a pure
  `(snapshot, vision_state) -> Optional[Decision]` - fixture-testable
  in isolation, no coupling to the loop or store.
- The postmortem pipeline (deferred) lets us inject *personalized*
  context into the live coach - the difference between "you're low
  HP" and "this is the exact situation you died to 14× last season."

**Trade-off:**
- The "always-on companion" feel goes away. Some sessions will surface
  zero decisions because nothing pivotable happened. The heartbeat
  pill mitigates this - operator can glance over and confirm
  "system saw 142 evals this game, decided not to fire" instead of
  worrying it silently broke.
- Detectors that touch wave-state / camp-tracking / position-correction
  need new derived data the current pipeline doesn't surface
  (vision_tracker only emits position-on-vision; jungle camp clear
  status isn't tracked at all). Each new detector category has a
  pre-req data layer.
- The existing mode coaches still narrate - full deprecation is a
  multi-session refactor. ADR-007 sets the direction; the actual
  prose-coach trimming happens detector-by-detector as their decision
  detector counterpart proves out.

**Watch for:**
- Detector false-positive rate. Once the pill+banner are live in real
  gameplay, monitor `data/decisions_log.jsonl` for ids that the
  operator dismisses (choice="skip") significantly more than they
  engage with. Tune thresholds or retire detectors with skip-rate >70%.
- Rate-cap interaction with new detectors. `_MAX_PER_GAME = 5` and
  `_MIN_GAP_S = 30` were tuned against the original 5-detector roster.
  Adding 5 more might starve some triggers; revisit caps after first
  3 real games' worth of logs.
- The heartbeat pill must not become its own noise. Keep it small,
  monochrome until amber/red, no animation on the increment.
- ADR-002 (DS-before-Haiku) stays in force - DS picks remain a
  separate surface from the decision detector. They are
  recommendations, not decisions; they update continuously and don't
  ask for A/B input.

## Phase-1 ship (this session, s169)

- Tighten `detect_low_hp_backable` - gate on recent damage in last 8 s
  AND `alive_for ≥ 90 s` (was 45) so it doesn't fire on safe retreats
  or right after respawning.
- Add `detect_jungler_gank_likely` - JG missing ≥ 20 s AND last seen
  outside their own jungle quadrant.
- Add `detect_throwing_lead` - your gold lead negative-delta over
  rolling 90 s window AND ≥ 2 of those gold drops correspond to
  ChampionKill victim events naming you.
- Add `DecisionLoop.heartbeat()` + `/api/decisions/heartbeat` endpoint.
- Add `#trigger-pill` to the dashboard header (glanceable counter +
  green/amber/red alive indicator).
- Add `tools/gamepc_keybind_listener.py` (install-only; not
  auto-deployed) so the operator can A/B respond via Left Alt + 1/2/3
  while in-game without alt-tabbing. (Left Alt chosen because Ctrl+1..6
  are League's item-cast binds - Alt+1..6 are unbound by default.)

Postmortem pipeline (`scripts/postmortem_analyze.py`) + prose-coach
deprecation pass are deferred to s170+.
