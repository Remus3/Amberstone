# RM-1427 ruling - s150, 2026-11-05 (distinct adjudicator, operator order "RM-1427 - BEST ADJUDICATED ANSWER")

Read-only adjudication at HEAD `b0eb6698b` (clean tree; a gated suite was running, so no test, edit or commit was made).
Recall gate: `python tools/perseus_recall.py "RM-1427 modals entry point escape layer"` returned no CLOSED / REFUTED / shipped hit
for RM-1427 (top hits: ledger 1652, 1006, 607, 1964, 2004, 1039, 1388, all unrelated). Live probe: RC is not running
(`ops/runtime/health.json` updated_at 2026-11-01T02:17Z; `curl` to :8888 and :8890 returned 000), so `/api/activity` and
`/api/digest` were NOT read live; every fact below is from source and git.

Archive note: every file:line below is as read at `b0eb6698b` and moves as those files change (the build of this ruling changes the web files it cites). The row is `BACKLOG.md` RM-1427; the sibling finding at the end is filed as RM-1658; docs/LEDGER.md entry 2054 records the ruling. No scrub was needed (no machine path, account id or sibling name); this note is the only addition. Nothing else differs from the ruling as written.

## DECISION - SPLIT

1. RETIRE the cross-session digest popout (`#digest-popout`): its markup, its binder, its `digest-popover` escape-layer
   registration, its CSS, and the digest cases of its tests.
2. KEEP the task detail modal (`#task-modal`) DORMANT, as is: no entry point restored, no code removed. The operator's
   2026-04-29 visual-only hide of `#activity-strip` stands; its documented one-line restore brings back a working,
   keyboard-hardened modal.
3. Remove ONLY the visual pieces. Every data path stays: the coach payload's `digest_*` keys, the `match_metrics`
   columns, `/api/digest`, its `:8888` proxy entry and the advisory filer. The hidden `#digest-icon` / `#digest-label`
   write target stays too, minus the button role it no longer earns.

## ROW AND FILING EVIDENCE

- Row: `BACKLOG.md:29` (RM-1427 OPEN, S144-U-124). The crosswalk at `BACKLOG.md:25` marks RM-1425 / RM-1426 (S144-U-121 / -122)
  REFUTED as filed, superseded by RM-1427.
- Filing: `ops/loop/control/lane_prompts/s144_reports/uiux_s144u112-00b4ea.md:4,33,38-39,44,53` (gitignored lane report);
  ruling log `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md:186-216` (RM-1364 cycle 110, RM-1424 cycle 111, RM-1427 filed in cycle 112).

## MEASURED FACTS (file:line)

### Modal A - task detail modal `#task-modal`
- Markup `web/index.html:2506-2525`. JS `web/js/main.js:316-404`: `closeTaskModal` :331-335, `openTaskModal` :337-382
  (fetches `/api/task/<id>`, shows id / op / owner / status / priority / filed-at / event history), escape layer
  `task-modal` with `modal: true` :397-404.
- ONLY opener: the activity row click, `main.js:297-299` (`span.addEventListener("click", () => openTaskModal(e.task_id))`).
  The rows come from `refreshActivity` `main.js:261-311`, which polls `/api/activity` every 10 s (`:313-314`) and fills
  `#activity-line` inside `#activity-strip` (`web/index.html:2416-2420`).
- The strip is hidden: `web/css/panels/input_activity.css:363-368`: "User request 2026-04-29: visually hidden - supervisor
  task tracking ... still runs server-side and the JS still polls; only the strip is hidden so the row doesn't take screen
  real estate. Set display:flex to restore." Also hidden in zen (`web/css/panels/map_state.css:152`) and in the overlay
  shell (`web/css/overlay.css:114,119`).
- Removing commit: `77c5b7297` (2026-04-30, "home overlay V3 + footer cleanup + 12hr clocks", `git log -S'User request
  2026-04-29' -- web/css`; the diff turns `.activity-strip` `display: flex` into `display: none`). Its message does NOT
  name the strip; the in-place comment does, and it records a deliberate VISUAL-ONLY hide that keeps the wiring on purpose.
  There is no LEDGER entry: the commit predates the numbered ledger, and `docs/history_notes.md` has no entry for it.
- Backend live in source: `agents/_supervisor_http.py:219,598` (`/api/task/<id>`) and `:217,775` (`/api/activity`),
  proxied by `dashboard/_handler.py:306-322`.
- Function elsewhere: NONE. No other UI surface shows a supervisor task's detail. The only other `/api/task` caller is
  `main.js:6964-6977` `_pollTaskUntilDone`, used by the input bar, which has been hidden since 2026-04-25
  (`docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md:213`).

### Modal B - cross-session digest popout `#digest-popout`
- Markup `web/index.html:2483-2504`. Binder `web/js/panels/right_now.js:114-198` (`bindDigestIcon`: open :170-174, hide
  :175-178, escape layer `digest-popover` with `modal: true` :190-197; imports :7). Field writer `renderDigest`
  `right_now.js:89-113`, called every state tick from `main.js:1709`. CSS: `web/css/panels/header.css:3811-3920` (popout and
  insights) and the overlay hide entry `web/css/overlay.css:118`.
- ONLY opener: `#digest-icon` (`web/index.html:2476`, `hidden` attribute), forced shut by `header.css:3769-3771`
  (`.digest-icon[hidden] { display: none !important; }`). No script clears it: `renderDigest` sets only class, label and
  title, and every `.hidden = false` in web/js targets another element (`main.js:2140,3166,3209,3767,3790,3979,4031,5446-5457`).
- Entry-point history, and every step NAMES the digest:
  1. `77c5b7297` (2026-04-30) hid the footer pill but RE-HOMED its function: "Advisory + digest pills hidden via [hidden]
     attribute ... Their content is mirrored into Tonight's Pick's icon buttons". It added `#home-alerts-digest`, wired by
     `wireAlertRow("home-alerts-digest", "digest-icon")`, a proxy click.
  2. `3626bb00d` (s218, 2026-05-15, the operator-driven Home redesign capped "this page is done now",
     `docs/history_notes.md:24668`) deleted that pip: "Drop orphan .home-pick-btn* CSS, ... wireAlertRow calls for removed
     pip buttons". The s218 wrap section of `docs/history_notes.md` (from :25604) adds "advisory + digest pip-buttons that
     Section 3 redesign replaced". This is the LAST entry point, and its removal is a named, deliberate decommission.
  3. HOME_QA 2026-07-04 (`docs/qa/HOME_QA_2026-07-04.md:94-95`, an operator walkthrough) then dropped Section 3 (C1) and
     REMOVED the Home "Weekly Digest" as overlapping This Week plus Pick (C2).
- Producer: `core/aftergame_summary.py:349-360` `_pick_digest` is an MVP stub. It returns only `digest_state: "none"`,
  `digest_label: "-"` and `digest_tooltip`. Nothing outside the readers writes `digest_state_long`, `digest_streak`,
  `digest_recent`, `digest_kda_trend`, `digest_time_of_day`, `digest_fatigue` or `digest_advice` (repo-wide grep: only
  `right_now.js:106-112` reads them, and `core/match_metrics.py:482-484` maps two of them for persistence). So 7 of the
  popout's 8 blocks would render "-" forever, even if the popout were reached.
- The one live block, TOP INSIGHTS: `right_now.js:152-166` reads `/api/digest`, served by
  `agents/_supervisor_http.py:1000-1024`, built by `coaches/adaptation_hint_digest.py:21` (types `cold_streak`,
  `hot_streak`, `worst_hour`, `best_hour`, `worst_day` at :47,61,84,97,119). Its content already shows elsewhere:
  - hot and cold KDA streaks in Adaptation (`web/index.html:798-801`);
  - hour and weekday readiness factors in the Session view (`web/js/panels/session_hygiene.js:1-7`);
  - game-length win rate (`web/js/panels/duration_winrate.js:1-4`);
  - the Home hero streak sub-text (HOME_QA H2 row);
  - insights at severity 0.7 or above are filed as advisories (`agents/agent4_coach_mentor/insight_detector.py:33-40`).

### Escape layers and tests
- Exactly two layers carry `modal: true`: `main.js:397-404` (task-modal) and `right_now.js:190-197` (digest-popover). The
  other layers are view-menu, find-match-picker, lobby-lane-popup, lobby-mode-menu and draft-elo-contributions. The
  RM-1364 / RM-1424 modal machinery (`web/js/lib/escape_layers.js:263-335`) has production consumers at `main.js:7373,7482`
  and `web/js/panels/review_player.js:183`. Retiring BOTH modals would leave that machinery with no production modal.
- Tests tied to the modals:
  - `tests/snapshot_panels/test_modal_focus_open_close.py`: both modals, parametrized; the digest-over-task case is :269-283.
  - `tests/snapshot_panels/test_shortcuts_behind_a_modal.py`: `_MODALS` :56-59.
  - `tests/snapshot_panels/test_ctrl_k_needs_a_rendered_prompt.py:112-115`.
  - `tests/snapshot_panels/test_escape_one_action.py`:
    - RM-1068 digest test :186-206;
    - RM-1069 digest-over-task stack test :260-311;
    - `digest-popover` in `_LAYER_OPEN` / `_open_layer` :326-348;
    - registry map :505-523.
  - `tests/snapshot_panels/test_held_key_one_action.py:112-127` (task modal only).
  - `web/js/lib/escape_layers.test.mjs` uses "task-modal" as a synthetic name only.
- Couplings that go red on a careless retirement:
  - `tests/guard_data/web_live_half/*.txt` pins `right_now.js`, `index.html`, `header.css`, `overlay.css` (recapture
    command `tests/test_web_ascii_sweep.py:46-47`);
  - `docs/WEB_CSS_SPLIT_PLAN.md:255-262` slice HS-7 names the anchors `digest-popout` and `digest-insights`, enforced by
    `tests/test_web_css_split_plan_rm726.py:275-297` (anchor must have hits) and :333-355 (coupled file
    `test_escape_one_action.py` must co-mention header.css with an anchor; today it does only through its digest comment
    at :261-262).
- No other surface opens either modal: a grep of rc-shell, lane-widget, Python, AHK, PS1 and JSON (outside web/, tests/
  and docs/) finds nothing. No doc names either modal as wanted; the only intent records are the in-place comments
  `web/index.html:2469-2474` and `input_activity.css:363-366`.

### Operator UI direction (memory)
- `feedback_field_remove_visual_only.md`: a removal is visual-only; keep the populate path, the payload keys and the DB
  columns.
- `reference_dead_mount_restore_vs_remove_discriminator.md`: the test is whether the removing commit NAMES the thing.
  - Digest: named twice (`77c5b7297` re-home, `3626bb00d` removal), plus a replacement and an operator QA that removed
    overlapping digest surfaces, so verdict REMOVE.
  - Task modal: its opener was hidden by an in-place, visual-only, restore-documented operator request, so it is a
    designed optional target (`reference_dead_mount_may_be_a_deliberate_optional_target.md`) and not residue.
- `feedback_rendered_field_is_not_evidence_of_a_producer.md`: the digest kv rows are exactly that case.

## ALTERNATIVES WEIGHED

- A. Restore an entry point for both (rejected).
  - Digest: this reverses the s218 and HOME_QA 2026-07-04 operator decisions, and it resurrects a panel that is 7/8 stub
    dashes. Its live part already has visible homes.
  - Task modal: un-hiding the strip reverses the explicit 2026-04-29 request. A new opener (for example a health-dot menu
    or a command) is a new footer control the operator never asked for, against the footer de-clutter direction. Cost: a
    new control, the RM-1426 keyboard work and a 5-phase audit, for a Phase-3 queue view whose input bar the operator
    hid as not working.
- B. Retire both (rejected).
  - Deleting the task modal tears out wiring the operator kept on purpose when hiding the strip ("the JS still polls ...
    Set display:flex to restore"). The documented restore would then bring back rows that open nothing, which is lost
    function and the opposite of "remove = visual only".
  - The task modal does not meet the prove-it-dead bar (`tools/headless-repo.md:182-198`: zero callers AND a target that
    no longer exists). Its opener code and its `/api/task` target both exist; it is dormant, not dead.
  - It would also orphan the RM-1364 / RM-1424 modal machinery and its integration coverage.
- C. Split, retire the digest popout and keep the task modal dormant (CHOSEN).
  - It removes only the code proven dead on independent facts: zero reachable openers through a named, deliberate
    decommission, a stub producer for 7/8 blocks, and replacement surfaces for the live block.
  - No reachable function is lost, the strip's restore path keeps working, and the generic modal layer keeps one real
    consumer and its tests.
  - It neither reverses nor extends the 2026-04-29 hide: the strip stays hidden, and the digest retirement executes the
    LATER s218 decision.

## WHY (one paragraph)
The two modals look alike but are not the same case. The digest popout's entry point was moved and then deliberately
deleted by named operator-driven commits. Its fields have no producer, and what it showed that was real now lives on
three visible surfaces, so the popout and its binder are residue. The task modal's only entry point sits behind a
visual-only hide that the operator wrote down with its one-line restore. The modal still works, its backend is live, and
no other surface shows that data, so deleting it would cost function on the operator's own restore path. Keep what can
be reached by the documented path, and remove only what is proven dead.

## REVERSAL CONDITIONS
- Digest retirement reverses if any of these happens. The remedy is then to build a surface from `/api/digest` in a
  visible view such as Session, not to revive the popout:
  - the operator asks for a cross-session digest surface;
  - `core/aftergame_summary.py` `_pick_digest` gains a real producer for the detail fields;
  - a measurement shows the `/api/digest` insight types have NO visible surface (for example the Adaptation streak rows,
    the Session hygiene factors or the duration panel are removed).
- Task-modal keep reverses if either of these happens:
  - The operator restores `#activity-strip` (`display: flex`). The modal is then live, RM-1426's acceptance (the
    activity row becomes a keyboard-reachable button at the hit floor) becomes due, and S144-U-123 un-parks.
  - The Phase-3 supervisor queue (`/api/activity`, `/api/task`) is retired. Strip, rows, polling and modal then retire
    together, as named residue.

## IMPLEMENTATION SPEC (builder; Tier-1 UI, no engine, no frozen file, one worktree slice)

Files to change:
1. `web/index.html`:
   - delete the popout block :2483-2504 (its comment included);
   - on `#digest-icon` (:2476) drop `role="button"` and `aria-label="Open cross-session digest"`; keep the span, its
     `hidden`, its class and `#digest-label`, since the comment at :2469-2474 makes it a write target.
2. `web/js/panels/right_now.js`:
   - delete `bindDigestIcon` (:114-198);
   - delete the `setd(...)` lines and the `setd` helper in `renderDigest` (:105-112), which write only into the popout;
   - keep the class, label and title writes (:91-103);
   - rewrite the comment at :85-88 ("click opens" goes);
   - drop the now-unused `escape_layers.js` import at :7.
3. `web/css/panels/header.css`: delete :3811-3920 (`/* Digest popout ...` through `.digest-insights .dim`). Keep
   `.digest-icon*` (:3769-3809) and the `.advisory-badge*` rules.
4. `web/css/overlay.css`: delete the `#digest-popout` line at :118 (keep `#task-modal`).
5. `web/js/lib/escape_layers.js`: comment-only, at :263-264 "the task modal, the digest popout" becomes "the task modal".
6. `docs/WEB_CSS_SPLIT_PLAN.md` HS-7:
   - drop the anchors `digest-popout` and `digest-insights`, and retitle it "Header chips and toasts";
   - re-derive `Coupled` from the rm726 guard. If `test_escape_one_action.py` no longer co-mentions header.css with an
     anchor, set the field to the files that do, or to `none ...`, as the guard's none-branch accepts.
7. Tests, as listed below.
8. Re-capture the live-half digests:
   `python -c "import tests.test_web_ascii_sweep as t; print(t._recapture_live_half())"`. Confirm the only drifted
   sources are the four web files above, and give the reason in the commit message.
9. Docs:
   - append an RM-1427 RULING section to `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md`;
   - set `BACKLOG.md:29` RM-1427 to SHIPPED (split), with the commit;
   - record S144-U-123 as PARKED with the dormant task modal;
   - add a LEDGER entry.

Tests first (write them RED, then make them GREEN). Create `tests/test_rm1427_digest_popout_retired.py`, static with no
browser. Anchor every walk (assert that `main.js`, `right_now.js` and `header.css` were found) so that an empty
enumeration cannot pass.
- RED today:
  - (1) `web/index.html` carries none of the ids `digest-popout`, `digest-popout-close`, `digest-popout-title`,
    `dig-state`, `dig-streak`, `dig-recent`, `dig-kda-trend`, `dig-tod`, `dig-fatigue`, `dig-advice`, `dig-insights`,
    `dig-insights-count`.
  - (2) No `web/js/**/*.js` contains `digest-popout`, `digest-popover`, `dig-insights` or `/api/digest`.
  - (3) No `web/css/**/*.css` contains `.digest-popout`, `#digest-popout` or `.digest-insights`.
  - (4) The `registerEscapeLayer({...})` blocks with `modal: true` across web/js are exactly `["task-modal"]`.
  - (5) `#digest-icon` has `hidden` and no `role="button"`; `#digest-label` exists; `renderDigest` still writes
    `digest-label`.
- GREEN today, pinning the other direction (the RM-339 both-ways precedent):
  - (6) `#task-modal`, `#task-modal-close`, `#task-modal-title` and `#tm-events` are present; `main.js` still binds
    `openTaskModal(e.task_id)` on the activity row and registers `task-modal` with `modal: true`.
  - (7) The `.activity-strip {` rule in `input_activity.css` still carries `display: none;`. This ruling restores nothing.
  - (8) Visual-only pin: `"/api/digest"` is still in `dashboard._handler.SUPERVISOR_PROXY_PATHS`;
    `agents/_supervisor_http.py` still has `_handle_digest`; `core/aftergame_summary.py` still emits `"digest_state"`.
  - Run it once before the fix and record the red count.

Existing tests to edit:
- `test_modal_focus_open_close.py`:
  - drop `"digest"` from `_MODALS` and from every parametrization;
  - replace the digest-over-task case (:269-283) with the view menu opened over the task modal through
    `document.getElementById('view-trigger').click()`, the `test_escape_one_action.py:412-415` pattern. MEASURE the
    menu's Tab and Escape behaviour first. Keep these invariants: the modal's Tab trap does not act while a non-modal
    layer is topmost, and Escape closes the upper layer first and leaves the modal open. A defect found here is filed,
    not fixed in this slice.
- `test_shortcuts_behind_a_modal.py` and `test_ctrl_k_needs_a_rendered_prompt.py`: drop the digest param and its
  docstring lines.
- `test_escape_one_action.py`:
  - delete the RM-1068 digest test (:186-206) and the RM-1069 digest stack test (:260-311). Their peel-one-per-press
    coverage survives in the RM-1070 `test_escape_closes_the_layer_painted_on_top_first` cases (:412-447, view menu and
    Find Match picker over the task modal);
  - drop `digest-popover` from `_LAYER_OPEN` / `_open_layer`;
  - in the registry test (:505-523) remove `panels/right_now.js` from the import loop and from the expected map;
  - fix the docstring and comment mentions (:24-31, :318, :403).
- ruff the new and edited tests.

5-phase UI audit (popout DOM is removed although it was never rendered). Run it headless under `?ui_mock=1` on Home,
Settings, Active Match and the overlay shell (`?ui_mock=1&mode=sr&overlay=1`), at 1920x920 and 923x1280:
- STRUCTURE: footer children and their rects are identical before and after, and the body loses exactly one never-boxed
  child.
- TYPOGRAPHY: no rendered text changed.
- HIT-TARGETS: no boxed control was added or removed.
- ASCII: 0 non-ASCII bytes and 0 CR in the added lines; `tools/web_ascii_sweep.py --dry-run` reports clean.
- HIERARCHY: unchanged.
- One before/after Home screenshot diff at 1920x920 is enough rendered-pixel proof (R3).

Touched test files to run (Tier-1, not a whole suite, from the repo root):
`python -m pytest tests/test_rm1427_digest_popout_retired.py tests/snapshot_panels/test_modal_focus_open_close.py
tests/snapshot_panels/test_shortcuts_behind_a_modal.py tests/snapshot_panels/test_ctrl_k_needs_a_rendered_prompt.py
tests/snapshot_panels/test_escape_one_action.py tests/snapshot_panels/test_held_key_one_action.py
tests/snapshot_panels/test_overlay_view.py tests/test_web_css_split_plan_rm726.py tests/test_web_ascii_sweep.py
tests/test_ascii_source_sweep.py tests/test_web_element_id_resolution_rm339.py tests/test_web_js_esm_parse.py -q -n 8`
plus `node --test web/js/lib/escape_layers.test.mjs web/js/panels/review_player_model.test.mjs`. Then a read-only verifier
re-runs the cited files and `--collect-only`.

## SIBLING FINDING (not ruled here; the merger should file it as a new row)
- `#advisory-badge` (`web/index.html:2475`) is `hidden` the same way, and it is the ONLY opener of the advisory toast
  (`main.js:7096-7139`).
- Two places justify dropping the Home Advisories row with a footer badge that has been hidden since `77c5b7297`:
  - HOME_QA C1 (`docs/qa/HOME_QA_2026-07-04.md:94`, "duplicates footer advisory-count");
  - `main.js:4272-4274` ("the footer health-dot + advisory badge already carry that signal").
- `header.css:3928-3930` itself says "the badge ships [hidden]", and the health-dot tooltip (`main.js:8390-8405`) carries
  no advisory count.
- Net effect: cold-streak and coaching-insight advisories have no visible surface. That decision rested on a false
  premise, and it belongs to the operator; it is not part of RM-1427.
