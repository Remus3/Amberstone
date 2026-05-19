# dashboard.js Quarantine - Corrected + Verified Spec (2026-05-18)

**Owner:** operator (SamplePlayer)
**Status:** SPEC ONLY - not started. Its own scoped `/clear`'d session.
**Supersedes:** `AUTONOMOUS_AUDIT_2026-05-18.md` section 4.A (that spec was
written before the coupling was verified and materially understates it).

ASCII-only (no em/en dashes; spaced hyphen for clause breaks).

---

## 0. Why this is its own session

`web/js/dashboard.js` (~8531 LOC) is dead at runtime - zero `<script>`
ref in `web/index.html`, zero ES imports (live UI is
`web/js/main.js` + `web/js/panels/*`). But it is referenced by ~10 test
assertions, a stale agent allowlist, generated data, and stale
comments. The audit's "just move it, 7 steps" was wrong. The hard part
is ~10 per-assertion judgment calls in the agent3 test harness, each
needing a repoint-vs-delete decision. Do NOT bulldoze this at the tail
of an unrelated session.

Pattern to follow: `reference_archive_dir.md` (quarantine, do not
delete), `feedback_audit_proposals_are_intent.md` (the audit is intent;
this corrected map is the spec). Quarantine target excluded from
ripgrep per CLAUDE.md (`docs/_archive/**`).

---

## 1. Pre-flight (do FIRST - load-bearing safety checks)

1. **Asset-hash (ADR-008).** Inspect `dashboard/_static.py`
   `compute_asset_hash` and `dashboard/routes_state.py` ui-version path.
   Confirm whether `web/js/dashboard.js` is in the hashed set.
   - If the hash walks all `web/js/` generically: moving the file out
     causes one benign cache-bust (acceptable; note it).
   - If there is an explicit by-name list including dashboard.js: that
     is a stale entry to remove in the same change.
   - Classify the grep hits in those two files (comment vs code).
2. **Frozen-file check** (CLAUDE.md "Frozen files" list, authoritative
   at execution time). Confirm NONE of the edit targets are frozen.
   As of 2026-05-18: `ui_applier.py`, `coaches/_base_coach.py`,
   `tools/daemon_slayer_extract.py`, `scripts/data_pipeline.py`,
   `dashboard/_static.py`, `dashboard/routes_state.py`,
   `tests/test_champion_aliases.py`, the agent3 suite - all NOT frozen.
   Verify again; do not assume.
3. **Is agent4 ui-applier still a live channel?** `ui_applier.py`
   `ALLOWED_PATHS` currently = {`web/css/dashboard.css`,
   `web/js/dashboard.js`, `web/js/sim.js`, `web/index.html`} +
   prefix `data/sim/`. `sim.js` and `data/sim/` were removed in s218;
   `dashboard.css`/`dashboard.js` are dead. The entire allowlist points
   at removed/dead targets. Decide: is the agent4 UI-apply channel
   vestigial (then the finding is bigger than "drop one entry"), or
   should the allowlist be repointed to live targets
   (`web/index.html`, `web/js/main.js`, `web/js/panels/`,
   `web/css/panels/`)? This is a scoped decision - surface it.

---

## 2. Complete verified coupling map

### A. Real test coupling

| # | Site | What it does | Action |
|---|---|---|---|
| A1 | `tests/test_champion_aliases.py:85` (+ docstring :6) | mirror-list entry; test reads file + asserts alias normalization. :6 already labels it "dead-code mirror" | Drop line 85; tidy docstring :6. Trivial. |
| A2 | `agents/agent3_testing/suite/test_round24.py:140-144` `test_dashboard_js_binds_kda_element` | asserts `'kda: el("adapt-kda")'`, `"data.avg_kda"`, recent_kda in dashboard.js | Judgment (below) |
| A3 | `test_round25.py:263-266` `test_dashboard_counter_line_uses_matchup_kda` | asserts `"c.kda_ratio"`, `"c.kda_delta"` | Judgment |
| A4 | `test_round27.py:15-35` x3 | streak el bindings, `/api/trending`+`fetchTrending`, `TRENDS.lastMode`+`30000` dedupe | Judgment |
| A5 | `test_round42.py` `test_dashboard_js_sends_sim_context` / `_polls_and_reloads` / `_renders_inline_diff` (+ ui_applier fixture tests :67-103) | SIM_ACTIVE/sim_context/sim_fixture, `_pollTaskUntilDone`, inline-diff; ui_applier apply/truncation using dashboard.js + sim.js as fixtures | Judgment + tied to ui_applier (B1) |

**`test_round40` is NOT in the grep** - the audit's example was stale.
Do not search for it.

**Per-assertion judgment procedure (A2-A5):** these assert dashboard.js
*content* - live behavior from when it WAS the UI. They pass today only
because the dead file still physically holds old code (zero regression
value). For each asserted token:
- `grep` `web/js/main.js` + `web/js/panels/*` for the token.
- If the behavior moved there (likely for kda/streaks/trending): repoint
  the test's `Path(...)` to the live file; fix the asserted substring if
  it was renamed during the s133 ESM split / s208 / s218.
- If the behavior is genuinely gone (sim_context/SIM_ACTIVE after the
  s218 sim removal is the prime suspect): delete the stale test with a
  one-line commit note ("asserted dead dashboard.js; behavior removed
  s218"). A test pinning a dead file's contents is not a regression
  guard.
- Record every repoint-vs-delete decision in the commit body.

### B. Stale agent allowlist

| # | Site | Action |
|---|---|---|
| B1 | `agents/agent4_coach_mentor/ui_applier.py:31-37` `ALLOWED_PATHS` + the dashboard.js-specific truncation guard the audit cited (~:102-104; verify line) | Resolve the section-1.3 question first. Then either reduce allowlist to live targets or document the channel as vestigial. Update `test_round42.py` ui_applier fixture tests to match. |

### C. Cosmetic stale comments (trim for a clean post-quarantine grep)

Audit 4.A listed only the 4 css + index.html. Also required:

- `web/index.html:428` - "in dashboard.js (`COACH_DECISIONS` block)"
- `web/css/panels/primitives.css:65` - "(see dashboard.js)"
- `web/css/panels/map_state.css:575` - "_applyGamePhase(gtS) in dashboard.js"
- `web/css/panels/bridge_pending.css:260` - "sig change-detection in dashboard.js"
- `web/css/panels/header.css:236` - "_refreshPrefsChip in dashboard.js"
- `tools/daemon_slayer_extract.py:788` - docstring lists dead dashboard.js
  (items_index.js is the live mirror - drop the dead mention)
- `coaches/_base_coach.py:95` - "(web/js/dashboard.js:2647-2675)"
  (NOT frozen; comment only - repoint to live consumer or generalize)
- `scripts/data_pipeline.py:118,163` - "index used by dashboard.js" /
  "matches dashboard.js _normItemName" (repoint to items_index.js; the
  normalization contract itself is real - lowercase, strip non-alnum)

Prefer generalizing ("the dashboard JS") over repointing to exact
new line numbers (line refs rot - see CLAUDE.md comment guidance).

### D. Generated data + docs

- `data/api_surface.csv` - ~45 rows index dashboard.js `fetch()` calls.
  After the move, regenerate via `scripts/audit_api_surface.py`. Verify
  the script scans `web/js/` and has no hardcoded dashboard.js, and
  will NOT pick up the archived copy under `docs/_archive/`.
- `docs/adr/ADR-008-unified-asset-hash.md`, `docs/ARCHITECTURE.md`,
  `docs/API.md` - living docs: doc-sync pass AFTER the move (or run
  `/sync-all-md`). Only if they make a load-bearing claim about
  dashboard.js; most refs are historical.
- `docs/API_SURFACE_AUDIT.md`, agent `*/reports/*.md`,
  `HEADLESS_BRIEF_*`, `WAKEUP_NOTES.md`, `docs/history_notes.md`,
  `CLAUDE.md`, `ROADMAP.md` - dated artifacts / history ledgers.
  DO NOT rewrite (`feedback_no_history_rewrite.md`). Touch CLAUDE.md /
  ROADMAP only if a live load-bearing claim exists (verify; expect
  none - they are changelog entries).

---

## 3. The move

```
git mv web/js/dashboard.js \
  docs/_archive/2026-05-18-dead-dashboard-js/web-js-dashboard.js
```
(create the dir; reversible; `docs/_archive/**` is ripgrep-excluded.)

Order of operations: Section 1 pre-flight -> A1 -> A2-A5 (per-assertion)
-> B1 -> C -> the move -> D regen -> full verification.

---

## 4. Verification (must all pass before commit)

- `python -m pytest tests/ agents/daemon_slayer/tests/ agents/agent3_testing -q`
  - full green (baseline before this session: 3536 + the Phase 4(d)
    additions; re-establish the live baseline at session start).
- `python -m ruff check` clean on every touched file.
- pre-commit hook (py_compile + archmap) green.
- `grep -rn "dashboard\.js" --` returns ONLY: the archived copy, history
  ledgers, dated artifacts. Zero live-code references.
- Commit (Conventional Commits subject; ASCII; Co-Authored-By trailer),
  push, confirm CI green via `gh run watch`.

---

## 5. Discipline notes

- ASCII-only authored content (CLAUDE.md hard rule).
- Quarantine, never delete (`reference_archive_dir.md`).
- The audit is intent, this map is the spec
  (`feedback_audit_proposals_are_intent.md`).
- Do not rewrite history ledgers (`feedback_no_history_rewrite.md`).
- Estimated size: ~15-18 files, ~10 test-assertion judgment calls, one
  scoped agent4-channel decision. Budget a full focused session.

---

## 6. Already shipped this session (context)

Two unrelated units landed + CI-green on origin/main before this was
deferred:
- `ebd0cd7` fix(supervisor): Phase3 watcher kill-then-run + DS-dir
  exclusion (frozen `ops/rc_supervisor.py`, operator-approved; 30/30
  tests; applied live, anomaly self-remediated).
- `aaa9c5a` feat(daemon-slayer): expose candidate unique_passive_key on
  all 6 rankers (Phase 4(d), ENGINE 1.3.0 -> 1.4.0; full DS suite 2370
  green; DS server restarted, live-verified).

Next-session priority after this quarantine: `builders.py` split
(4.C lowest-risk) + `_enrich_from_lcu` test coverage (4.E).
