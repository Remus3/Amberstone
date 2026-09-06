# B4 design - move coach imperatives off the live surface

Status: DESIGN, not built. Filed 2026-08-12 under RM-189.
Decision it implements: `docs/OVERLAY_COMPLIANCE_PLAN.md` section 6c
(operator, 2026-08-11) - live coaching moves to pre-game and post-game; the
retained in-game behaviour is SILENT capture of decision branch points.

Every claim below is measured against the tree at 2026-08-12, cited file:line.
No part of this design was scaffolded against an assumed surface.

## 1. Two corrections to the B4 row in the compliance plan

The plan's B4 row (`OVERLAY_COMPLIANCE_PLAN.md:67`) names
`web/js/panels/right_now.js`, `coach.action` / `coach.immediate` /
`coach.fight_rule`, and `coaches/voice_coach.py`. Measurement changes the
picture in both directions, so the row must not be actioned as written.

**Correction 1 - the in-game overlay renders FEWER of those than the row
implies.** `web/css/overlay.css:127` hides every direct child of
`#right-now .panel-body` except three:

```
body[data-shell="overlay"] #right-now .panel-body > *:not(#rn-lead):not(#rn-choices):not(#rn-callouts)
```

`#rn-action` is a direct child (`web/index.html:482`), as are `#rn-immediate`
(`:489`) and the `.kv` block carrying Fight/Base (`:502`). All are therefore
ALREADY dark in the overlay shell. The live imperative surface is exactly
`#rn-lead` (`:488`), `#rn-choices` (`:495`) and `#rn-callouts` (`:501`).

**Correction 2 - the surface that survives is the WORST one.** `#rn-choices`
is the A/B/C decision chip set rendered by `web/js/panels/coach_choices.js`
from `state.coach.choices`. Each chip carries a `label`, a `trigger`, and a
re-branch line rendered as `-> B if <condition>`
(`coach_choices.js:86-89`). That is a notification dictating player action
based on current game state, in the most literal possible form. It is the one
right-now surface the overlay keeps.

Net: B4 is narrower than filed but not smaller in risk.

**Correction 3, found during B4-b (2026-08-12) - ALL THREE overlay survivors
are imperative, and two of them are not coach fields at all.** `#rn-callouts`
and `#rn-lead` are fed by TOP-LEVEL `/api/state` keys (`callouts`,
`lead_projection`), not by anything under `coach`, which is why the B4-a
coach-field sweep did not reach them. Both are directive at the source:

- `core/event_callouts.py:107` "Drake spawns 5:00 - set up vision"
- `core/event_callouts.py:109` "Plates fall 14:00 - shove for gold"
- `core/event_callouts.py:119` "Your lvl-6 spike - look for all-in"
- `core/event_callouts.py:127` "2-item spike - force fights now"
- `core/lead_projection.py:211` "Big lead: dive or roam, snowball it now."

`core/lead_projection.py:321` calls its own table a "per-mode directive
table", and `core/event_callouts.py:133` describes the recall callout as "a
correct-by-construction directive". The code says what it is.

**This also means B3 is not actually done.** B3 is recorded as
"power-spike cue - DONE, deleted" (`OVERLAY_COMPLIANCE_PLAN.md:41`), and it
did delete `web/js/panels/spike_cue.js`. But the level and item spike lines
above still fire live into `#rn-callouts`, which is one of the three mounts
the overlay keeps. The banned artefact survived its own removal by living on a
second mount. B4-b's producer suppression closes it in a live game; the B3 row
in the plan should be corrected rather than left reading DONE.

## 2. The capture half already exists - do not build it

Section 6c asks RC to "compute the multi-path choice set at each decision
moment DURING the game, write it to the match record, and render NOTHING
live". The compute-and-write half is SHIPPED, as the Haiku-to-ZERO validation
substrate:

- `core/hz_choice_shadow.py:90` `log_precomputed_choices(...)` - fail-soft
  (never raises), coarse-state dedup so the 2Hz `/api/state` poll does not
  flood, engine-version stamped, exact-`game_time_s` freshness guard.
- Sink: `data/hz_choice_shadow.jsonl` - 68,555,143 bytes on disk, newest
  record `2026-08-02T22:34:15Z` (measured 2026-08-12; the file is stale only
  because RC itself was down 08-09 to 08-12).
- A live record already carries both columns the post-game replay needs: the
  precomputed `choices` array (`key` / `label` / `expected_outcome` /
  `confidence` / `source_tag` / `trigger` / `rebranch_when` / `rebranch_to`),
  the live `native_action` and `native_choices`, plus `mode`, `my_champion`,
  `enemy`, `band`, `mana_state`, `cd_state`, `covered`, `game_time_s`,
  `level`, `item_count`, `engine_version` and `cv_override`.

So B4 is not "build a branch recorder". It is **gate the renderer, then build
the post-game reader over a stream that is already being written.** That is a
materially cheaper item than the plan's "highest-cost item" label suggests,
and it is the same convergence 6c predicted between the compliance path and
the cost path.

### Gaps in the existing stream (the only capture work B4 needs)

1. **No match identifier.** A record is keyed by wall-clock `ts` plus
   `game_time_s`. Post-game review needs to bind a branch series to one match.
   Add a `match_id` (and a per-boot `game_run_id` for event modes where
   Match-V5 returns nothing - see the ARAM Mayhem / queue-2400 fence in
   CLAUDE.md). Append at the END of the record, never mid-schema.
2. **No operator choice.** The record holds what was OFFERED, not what was
   TAKEN. The chips are already hotkey-selectable (Alt+1/2/3, see
   `tests/test_coach_choices_alt_hotkey.py`), so the selection event exists at
   the UI layer and is discarded. Post-game "here is what you chose" needs it.
   NOTE: once the chips stop rendering in-game (section 3) there is no click to
   capture, so this must instead be INFERRED post-hoc from the timeline, or
   dropped from the review copy. Recommend: drop the claim, review shows "here
   is the branch you were at and what each path was worth" only. Do not ship a
   review that asserts a choice RC did not observe.
3. **Arena column is pre-flagged poison** (`hz_choice_shadow.py:38-45`, RM-158
   writer gate). The post-game reader MUST honour that flag and exclude the
   precompute column for arena records while keeping the native observation.
   A reader that ignores it will present SR content wearing an arena label.

## 3. The gate - suppress at the PRODUCER, not the renderer

The plan says "the compliance boundary is the RENDERER"
(`OVERLAY_COMPLIANCE_PLAN.md:147`). Implement it one layer lower anyway.

Today the overlay/dashboard split is enforced in CSS (`overlay.css:127`). CSS
is a weak boundary for a compliance guarantee:

- an undefined or renamed selector fails SILENTLY and inherits instead
  (memory `reference_css_undefined_var_fails_silently`);
- the payload still reaches the client, so the banned content is one DevTools
  panel away from a reviewer;
- a future panel added to `.panel-body` is dark by accident, and a future
  refactor that flattens the DOM un-hides all three survivors at once.

The plan already set the correct precedent twice: B5 obfuscates names "at the
producer, not the renderer, so every consumer inherits it"
(`OVERLAY_COMPLIANCE_PLAN.md:68`), and B2 leaves `summoner_cooldowns` on
`/api/state` "as a permanent null so consumers degrade"
(`:40`). B4 should follow both.

**Design:** in `dashboard/_state_builder.py`, while a game is live, emit the
directive fields as null rather than populating them. Nothing to render
because nothing is sent. The shadow writer keeps the full branch set on disk,
unchanged, because it never travelled through `/api/state`.

Suppress while live:

| field | today | live-game value |
|---|---|---|
| `coach.action` | imperative headline | `null` |
| `coach.immediate` | imperative prose | `null` |
| `coach.fight_rule` | imperative | `null` |
| `coach.next` | imperative | `null` |
| `coach.choices` | A/B/C chips | `[]` |
| `coach.risk` | directive framing | `null` |
| `coach.target_priority` (arena) | "focus X" | `null` |
| `coach.round_strategy` (arena) | imperative | `null` |
| `callouts` (top level) | objective + spike imperatives | `[]` |
| `lead_projection` (top level) | macro directive line | `{}` |

Keep live (descriptive state, not a directive): `hp_pct`, `gold`, `level`,
game clock, CS, KDA, the rebuilt `cc_threat_cell` (CC durations, B10), and the
STATS block, whose rows are observations rather than instructions.

**Client-side complement, defence in depth only:** a single
`web/js/lib/live_directive_gate.js` exporting `directivesAllowed(state)`,
consumed by `right_now.js` and `coach_choices.js` so a stale cached payload
cannot paint a directive either. It must not be the only gate.

**Deliberately NOT decided here - build recommendations.** `coach.reset_item`
(`right_now.js:613`) and the next-buy panel dictate purchases, not plays. The
Riot wording bans notifications that "dictate player action based on the
current game state"; a shop recommendation is arguably outside it, and every
approved competitor ships one. Flag to DevRel with B8/B9 rather than
unilaterally deleting a core feature. See section 6.

## 4. voice_coach

`coaches/voice_coach.py` `speak(text, *, dedup=True, rate=0)` is a live TTS
imperative channel and is the single most reviewer-visible form of "dictates
player action" - a reviewer does not have to read a panel, they hear it. It is
hard-gated on the same live-game predicate as the producer above, not merely
muted by config. `is_available()` is a capability probe and is deliberately
NOT gated.

SHIPPED B4-c. Two details that are load-bearing:

- The gate sits inside `speak()`, not on its one current caller
  (`dashboard/routes_coach.py`, the `/api/speak` route), so any future caller
  inherits it.
- It sits BEFORE the dedup / rate-limit bookkeeping. A suppressed in-game line
  must not consume the dedup slot, or the first legitimate post-game utterance
  of the same text is silently swallowed as a duplicate.

B4-c also moved the predicate to `core/live_game_gate.py`, which is now its
single home: `dashboard/_state_builder.py` re-exports `is_live_game` rather
than defining its own, and the voice path (which holds no `/api/state`
envelope) uses the sibling `live_game_now()`, reading `ops/runtime/health.json`
directly. That file always carries the RAW flags - `apply_preflip_mirror`
stamps the champ-select mirror onto the served copy only - so the disk reader
needs no `preflip_active` argument. `live_game_now()` is fail-safe: an
unreadable health.json answers False, since "I cannot tell" is not evidence of
a game and failing closed would permanently silence the legitimate pre-game
and post-game surfaces the first time the file went missing.

## 5. Post-game review surface

Consumes `data/hz_choice_shadow.jsonl` filtered to one `match_id` (gap 1),
renders a time-ordered branch list: at `game_time_s`, the branch set offered,
each path's `expected_outcome` and `confidence`, and the `trigger` that put
the operator at that branch. Arena records honour the RM-158 flag (gap 3).

This is a NEW view, not a re-skin of `#right-now`. It must not mount inside
the overlay shell under any state, so it belongs on the dashboard's post-game
route alongside the surviving `spike_curve` / `spike_markers` analysis that
B3 kept for exactly this reason (`OVERLAY_COMPLIANCE_PLAN.md:66`).

Reader tooling already exists to model against: `tools/hz_shadow_report.py`,
which also documents a real corpus hazard - "~8.3k false comparable leaks +
~20.8k mislabeled" (`hz_shadow_report.py:189`). Read that before trusting a
naive filter over the corpus. That hazard is about scoring native-vs-precompute
AGREEMENT, which the review does not do - it renders what was offered - so it
does not constrain the reader, but a future scoring pass over the same corpus
must honour it.

SHIPPED B4-e. `core/branch_review.py` + `GET /api/branch-review` (and
`/runs` for the match picker) + the `#lm-branch-review` card inside
`#view-last-match`. Three properties worth keeping:

- **Bounded read.** The corpus is 68 MB and this serves an HTTP route, so the
  reader takes a 4 MB tail and reports `truncated` rather than serving a short
  series as if it were complete.
- **Legacy rows are counted, not guessed at.** Measured against the live
  corpus the moment the route went up: 4633 rows in the tail, ZERO with a
  `game_run_id`, so it answers `reason: "legacy-only"`. Almost the whole
  corpus predates B4-d; inventing a grouping for it would invent matches.
- **RM-158 exclusion drops the COLUMN, not the row**, and the card says so
  in place rather than leaving an unexplained gap in the timeline.

The 5-phase UI audit ran against the live dashboard before the commit.
STRUCTURE: mounts inside `#view-last-match`, hidden by default, empty state
present, follows the sibling `lm-wpa-*` card shape. TYPOGRAPHY: 29 / 22 / 18 /
16 px straight off the tokens, all resolving under the live theme (the
computed values come back as theme oklch, which is what proves no token fell
back). HIT-TARGETS: not applicable - the card has ZERO focusable elements by
design, since it is render-only. ASCII: clean per the web sweep. HIERARCHY:
fixed 108 px clock column so the timeline reads as a column, confidence
colour-coded, caveats warn-tinted and non-blocking, and no horizontal overflow
at a forced 400-character label.

Two independent barriers keep it off the in-game surface, and they are worth
stating precisely: the overlay shell computes `display: none` on the whole
`#view-last-match` SECTION (so the card is hidden by its ancestor, not by a
rule of its own), and `branch_review.js` additionally refuses to render when
`live_directive_gate` says a game is live.

## 6. Guard tests

Follow the B1-B3 precedent exactly: every removal leaves an INVERTED guard
behind rather than a hole, so reinstating the surface turns a test red
(`OVERLAY_COMPLIANCE_PLAN.md:50-52`). Model on the existing
`tests/test_cc_threat_cell_riot_compliance.py`.

1. Producer: with a live-game state, assert each field in the section-3 table
   is null/empty on the built envelope. Assert the descriptive fields SURVIVE
   in the same test, so a future over-broad suppression also turns it red.
2. Producer, negative control: with a NON-live state (client / post-game),
   assert the same fields are populated. Without this the suppression test
   passes trivially against an always-null builder
   (memory `feedback_negative_assertion_rules_out_without_pinning_down`).
3. Renderer: node-executed DOM test asserting `#rn-choices` and `#rn-callouts`
   stay empty under a live-game payload. `web/js` is node-executable in tests
   (memory `reference_web_js_node_subprocess_harness`); note
   `node --check` is blind on import-leading files, so use the ESM sweep
   (memory `reference_node_check_blind_on_import_files`).
4. voice_coach: assert `speak()` is a no-op under a live-game state. Do NOT
   write this as a raise-based spy - a raising spy is vacuous under a
   fail-soft caller (memory `reference_raise_based_spy_is_vacuous_under_fail_soft`).
5. Capture: assert the shadow writer STILL records the full branch set while
   the producer is suppressed. This is the test that proves compliance did not
   silently kill the Haiku-to-ZERO substrate.

## 7. Staging

| slice | content | tier | gated on |
|---|---|---|---|
| B4-a | producer suppression + guards 1/2/5 | 2 (schema) | no |
| B4-b | client gate module + guard 3 | 1 | no |
| B4-c | voice_coach gate + guard 4 | 1 | no |
| B4-d | `match_id` / `game_run_id` on the shadow record | 1 | no |
| B4-e | post-game branch review view + UI fixture ritual | 2 | no |
| B4-f | build-recommendation question | - | DevRel, with B8/B9 |

B4-a through B4-e are all executable without a live game: the fixtures under
`web/data/ui_mock/` plus the 68 MB existing corpus cover every state. Only
end-to-end confirmation that the live overlay is clean during a real match is
live-gated, and that belongs in `docs/LIVE_GAME_GATED_SYNC.md`, not as a
blocker on the code.

## 8. Open questions for DevRel

1. Build/shop recommendations during a live game - in or out? (section 3.)
2. Does a post-game replay of branch points RC computed live count as a live
   notification? Plain reading says no; 6c already flags that a reviewer sees
   the UI and not the design intent.
3. Does a purely descriptive live overlay (HP, CC durations, clock, CS) remain
   acceptable once every imperative is gone?

## 9. Doc drift found while measuring

`OVERLAY_COMPLIANCE_PLAN.md:162` records the operator product-name pick as
"Reliquary". The rename that actually shipped (RM-189 Tiers 0+1, LEDGER
1238/1239) is **Amberstone**, appId `com.amberstone.shell`, repo
`Remus3/Amberstone`. Section 6b2 is stale and should be corrected to match the
shipped name so a future reader does not re-open a settled decision. Tier-0
doc fix, not part of B4 proper.
