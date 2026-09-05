# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-04c - RM-340: the mountless `dev` view dropped, view registry guarded (ON MAIN)

STATE. Third row of the day, on top of LEDGER 1324 (six-slice batch) and 1325
(RM-339). ENGINE 1.280.0 unchanged, Tier-1 asset-only, no `:8860` bounce, no
Share sync. One merger-side adjudication + one build slice; worktree and branch
removed. LEDGER 1326. RM-341 filed.

WHAT IT ACTUALLY FIXED - not cosmetic. `VIEW_IDS` membership is read at
`main.js:611` / `:776` / `:6525`, so registering `dev` made `#dev` an ACCEPTED
hash that set `body[data-view="dev"]`, matched no CSS and showed no section: a
blank dashboard reachable by URL and by a stale `rc-view-manual` in
localStorage. It now falls back to `home`.

THE ROW FILED 2 SITES, THERE WERE 3. The third was an unreachable AND redundant
`else if (v === "dev")` branch at `main.js:928` - unreachable because it reads
`btn.dataset.view` and no menu item carries that value, redundant because it
did exactly what the generic `else` two lines below does.

GUARD: `tests/test_web_view_registry_rm340.py`, 15 tests, three directions -
id to mount, id and label BOTH ways, menu `data-view` to id. The label
direction is the one a naive guard misses and it was proven independent:
restoring only the `VIEW_LABELS` orphan reddens the label assertion while the
mount assertion stays green. **Both exemptions REDIRECT rather than skip** -
`home` resolves to `#home-overlay` (still asserted to exist) and `auto` is
pinned to `main.js:926` - and two further tests fail if either exemption goes
obsolete or loses its citation. Do not "simplify" an exemption into a skip.

THREE TRAPS WORTH CARRYING.
1. **`git checkout` to undo a probe takes your UNCOMMITTED work with it.** The
   slice reverted probe 1 that way and silently reverted its own fix, making
   probe 2's output invalid. It caught it and redid probes with file-copy
   backups. Back up the FILE, not the commit, when probing a dirty tree.
2. **A slice's incidental finding is a hypothesis too.** It reported the
   JS-vs-Python `VIEW_IDS` drift as 3 ids; re-measured it is **2**
   (`historical-pgr`, `build-insights`). Its 3 counted `dev`, which Python
   never carried and JS no longer does.
3. **A stale reference can pass forever.** `tests/test_view_router_state.py:279`
   listed `"dev"` among non-urgent views and stayed green, because `is_urgent`
   is membership in a hardcoded 4-tuple so any unknown id returns False.
   Cleaned, with the reason recorded in place.

HOUSEKEEPING FOR WHOEVER IS NEXT. **ROADMAP.md is at 89.7% of its 81920-byte
budget** and `tools/drift_guard.py` warns at 90, so the next filed row will trip
it. A relocation pass is owed and was deliberately NOT half-done here: the two
biggest closed rows (RM-253, RM-254) each carry OPEN sibling ids in the same
line, so convention leaves them in place - the pass needs real judgment, not a
byte trim. See the 2026-09-01 and 2026-09-04 sections of
`docs/ROADMAP_HISTORY.md` for how previous passes drew the line.

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-342.
      RM-341 (LANE 7, Tier-1) is the direct follow-on: TWO `VIEW_IDS`
      registries, `web/js/lib/state.js` (12 ids) and
      `dashboard/view_router_state.py:31` (10), drifted by 2 with nothing
      guarding them. **Do NOT default to equality** - `historical-pgr` is
      documented in state.js as manual-only ("the auto-derive view-router never
      selects it"), which is real evidence the Python tuple is a deliberate
      SUBSET. Establish intent from the consumers first, then guard containment
      or equality accordingly, parsing BOTH registries off disk.
      Also open: RM-322 (LANE 7), RM-212, RM-214, RM-286/287, RM-291..295.

Context: ENGINE 1.280.0, patch 16.15.1, :8860 serving. Lane worktrees at
      C:\rc-worktrees\rc-lane-* were NOT touched today and still sit at
      a55ece97e - fast-forward before using one.

Acceptance: whatever the chosen row states. Tier-2 rows (engine/scorer/schema/
      ENGINE_VERSION) need the full dual suite from the REPO ROOT plus a DS
      :8860 restart and a Share mirror sync; Tier-0/1 do not.

Do NOT redo: RM-340 CLOSED (LEDGER 1326), RM-339 CLOSED (1325),
      RM-208/209/220/326/327/328/338 CLOSED (1324). Do not re-derive the
      view-registry census or the id census - both were measured and corrected
      this session. Do not delete the RM-339 allowlist entries or the RM-340
      exemptions. `web/js/panels/dev.js` is a LIVE panel (settings / fixture
      viewer / replay scrubber) and is unrelated to the dead `dev` VIEW despite
      the name - do not confuse them.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.

---

# 2026-09-04b - RM-339: 20 dead element ids adjudicated per-id, 16 deleted, 4 allowlisted (ON MAIN)

STATE. Main carries RM-339 on top of the 1324 six-slice batch. ENGINE 1.280.0
unchanged, Tier-1 asset-only, no `:8860` bounce, no Share sync. Three read-only
adjudicators (one per family) + two build slices; all worktrees and branches
removed. LEDGER 1325 has the detail. RM-340 filed.

FINAL GUARD STATE. `tests/test_web_element_id_resolution_rm339.py` is GREEN:
20 unresolved, 4 allowlisted with cited reasons, 0 remaining, `KNOWN_OPEN`
empty. Do not "clean up" the allowlist - each entry is load-bearing.

THE COUNT WAS WRONG TWICE, IN BOTH DIRECTIONS.
Filed 25. RM-328 had closed 4, so the merger re-derived 21 - and got the
FAMILY SPLIT wrong too (the row's own dev.js enumeration sums to 13, not the
12 it stated). Then an adjudicator refuted the merger's 21:
`csv-sugg-ds-combo-input` is created at RUNTIME by `ds_combo.js:309` emitting
`id="${sigKey}-input"`. True count 20. Re-derive, then expect the re-derivation
to be wrong too.

THE DISCRIMINATOR THAT DECIDED EVERY ID.
RM-328 (earlier the same day) was RESTORE; RM-339 came out 16 REMOVE / 4
ALLOWLIST / 0 RESTORE. The test is not "did the removing commit have a
message" but "does the message name THIS thing". `832704a7c` (s162) says
"removed 5 live menu items (Loadouts/Diagnostics/Coach Calls/Bridge Pending/
Fleet)" - named, so REMOVE. `440ede616` enumerated its cuts exhaustively and
never mentioned the panel it killed - unnamed, so RESTORE. Both branches have
now been exercised; use the same test next time.

FOUR TRAPS WORTH CARRYING.
1. **A blanket "every getElementById must resolve" guard would be REVERTED.**
   `set-force-scan-btn` / `set-force-scan-status` are pinned in BOTH directions
   by `tests/test_settings_force_scan_dom.py` (:42-43 assert the ids are ABSENT
   from html, :56 asserts the binder is PRESENT in js), so a restore AND a
   removal both go red there. Four ids are deliberate optional targets.
2. **An exemption needs a falsifiable obligation, and the guard enforced it on
   the merger.** Allowlist reasons must cite a `.js`/`.html` `file:line`; the
   merger's first attempt cited only a `.py` path and was rejected by the
   guard's own test until real citations were added.
3. **`$'\u2191'` DOES NOT EXPAND in this shell.** The merger declared a slice's
   non-ASCII finding refuted on a grep that returned nothing, then found the
   pattern was literal. Byte-count instead: 12 arrow glyphs before, 8 after.
   The remaining 8 are in LIVE spans, which `test_web_ascii_sweep.py` excludes
   BY DESIGN (it sweeps comment spans only) - not a defect, do not "fix" it.
4. **A test can assert a falsehood while its name denies it.**
   `test_set_empty_state_does_not_reference_dead_id` pinned a list CONTAINING a
   dead id, and had done since the day the id died. Read what a guard asserts,
   not what it is called.

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-341.
      RM-340 (LANE 4, Tier-1) is the direct follow-on: `state.js:39` registers a
      `dev` view with no mount, no menu item and no markup, plus an orphan
      `VIEW_LABELS` entry at :56. It is NOT residue deletion - `VIEW_IDS`
      membership drives the hash-route parser, the persisted-selection restore
      and the menu builder, so read every consumer and cite it before deciding.
      Also open: RM-322 (LANE 7), RM-212, RM-214, RM-286/287, RM-291..295.
      Bodies + acceptance in BACKLOG.md; ROADMAP.md carries the pointers.

Context: ENGINE 1.280.0, patch 16.15.1, :8860 serving. Lane worktrees at
      C:\rc-worktrees\rc-lane-* were NOT touched today and still sit at
      a55ece97e - fast-forward before using one.

Acceptance: whatever the chosen row states. Tier-2 rows (engine/scorer/schema/
      ENGINE_VERSION) need the full dual suite from the REPO ROOT plus a DS
      :8860 restart and a Share mirror sync; Tier-0/1 do not.

Do NOT redo: RM-339 is CLOSED (LEDGER 1325) and RM-208/209/220/326/327/328/338
      closed the same day (LEDGER 1324). Do not re-run the id census - it is 20,
      measured twice and corrected once. Do not delete the 4 allowlist entries.
      Do not delete `/api/loadouts/all` or `/api/diagnostics` - both were left
      serving with no renderer ON PURPOSE (history_notes:23148: backends kept
      because ops tools depend on them); each removal is its own row.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.

---

# 2026-09-04 - six-slice batch: RM-208 / 209 / 220 / 326 / 327 / 328 shipped, RM-338 found+fixed, RM-339 filed (ON MAIN)

STATE. Main carries all seven. ENGINE **1.280.0 unchanged**, patch 16.15.1,
`:8860` NOT bounced and no Share sync - `ds_share_sync.py --check` exit 0 at 535
files proves nothing merged touches a mirrored file. Tier-1 throughout. Six
worktree slices on disjoint file sets plus one read-only adjudicator; all six
branches and worktrees removed at wrap. LEDGER 1324 has the full detail.

WHAT SHIPPED.
- RM-208 DS doc route guard: `ast` over `_POST_ROUTES`, BOTH directions, whole
  backticked doc tokens so `/v2/matchup` stops splitting into `/v` + `/matchup`.
- RM-220 wiki staleness: `{{ap|}}` brace-balancing reaches rank-count,
  enumerated and named-parameter forms. `skipped_labels` 109 -> 72, zero-label
  rows 27 -> 2, `findings` ROSE 214 -> 225. 2 cited aliases. Part (C) decided in
  writing, deliberately NOT implemented.
- RM-209 CSS: 5 tokens mapped onto existing names, 2 declared as new roles.
- RM-326/327 lobby: dataset-signature render gates + focus carry + reorder
  re-index, following the `champ_select.js:704` precedent.
- RM-328 team-context mount RESTORED (adjudicated, not assumed).
- RM-338 (filed and closed same day): every Top-8 `up` chevron was dead to the
  mouse. RM-339 filed, not fixed.

FIVE TRAPS WORTH CARRYING, all paid for this run.
1. **THREE FILED ACCEPTANCES WERE DEFECTIVE AND THE SLICES CAUGHT ALL THREE.**
   RM-328's "assert `#tc-allies` has 5 child slots" is VACUOUS - the no-payload
   branch pads to 5 placeholders, so it passes with the payload never reaching
   the DOM. RM-327's "two mouse clicks at one screen position" cannot
   discriminate a fix from HEAD in a position-indexed list. RM-208's 4(b)
   described the forward direction while asking for the reverse. Read an
   acceptance as a hypothesis, not an instruction.
2. **A WHOLE-TREE DIGEST CANNOT BE STAMPED BY A SLICE.**
   `test_web_ascii_sweep.py::test_live_half_digest_...` moves on any `web/` edit.
   The RM-209 slice correctly refused to stamp it. The merger owns it once,
   after every slice lands, and the file's own rule wants a two-tree diff with
   the SAME tokeniser - 11 differing files here, exactly the union of the four
   web-touching slices.
3. **TWO FILED CENSUSES WERE WRONG IN THE SAFE-LOOKING DIRECTION.** RM-209 filed
   21 sites / 8 files; truth is 22 / 10, and the row's own enumeration summed to
   22. RM-220's baseline had drifted 87/208 -> 92/214 because the wiki moves.
   Re-measure before building, every time.
4. **`git commit -m "merge: ..."` IS REJECTED.** The commit-msg hook enforces
   `<type>(<scope>)?: <description>`. Use `chore(merge): <branch>`. Four merges
   failed on this before it was noticed, and the failure reads like a conflict.
5. **RESTORING OLD MARKUP VERBATIM VIOLATES THE ASCII RULE.** The 2026-05
   team-context hunk carries U+2026 and U+2014. Anything recovered from
   pre-purge history needs a programmatic ASCII assertion, not a glance.

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-340.
      RM-339 (LANE 4, Tier-1) is the natural follow-on to this batch: 25 dead
      `getElementById` ids, of which 21 are still live residue. Adjudicate each
      RESTORE-or-REMOVE from git history the way RM-328 was - a dead id is NOT
      proof of dead code. Keep its guard SEPARATE from RM-209's CSS guard.
      Also open: RM-322 (LANE 7), RM-212, RM-214, RM-286/287, RM-291..295.
      Bodies + acceptance in BACKLOG.md; ROADMAP.md carries the pointers.

Context: Main is at the six-slice merge, ENGINE 1.280.0, patch 16.15.1, :8860
      serving. Lane worktrees at C:\rc-worktrees\rc-lane-* were NOT touched this
      run and still sit at a55ece97e - fast-forward them before using one.

Acceptance: whatever the chosen row states. Tier-2 rows (engine/scorer/schema/
      ENGINE_VERSION) need the full dual suite from the REPO ROOT plus a DS
      :8860 restart and a Share mirror sync; Tier-0/1 do not.

Do NOT redo: RM-208 / RM-209 / RM-220 / RM-326 / RM-327 / RM-328 / RM-338 are
      CLOSED (LEDGER 1324). RM-337 closed 2026-09-03 (LEDGER 1323). Do not
      re-open RM-220 part (B) as a blanket vocabulary gap - that hypothesis was
      refuted once already as RM-218, and the 2 zero-label rows that remain are
      a DIFFERENT mechanism (`{{as|}}` head-cut and `[[File:...]]` pipes), not
      an `{{ap|}}` form. Do not delete the 44x44 hit-target overlays - they are
      a deliberate audit floor; four of the five sibling sites were measured
      NOT broken.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.
