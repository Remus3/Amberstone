---
description: Mission Control lane 4 (uiux). Headless UI/UX queue plus usability deep-dives across RC / DS / dashboard / overlay / menus / settings. Drives every page from mock data rooted in real match data so no League client and no live game are needed; confirms the rendered result text-first (computed styles, accessibility tree) with pixel capture reserved for genuine rendered-pixel questions. Authorized to add, remove, relocate and redesign the UI guidelines it works against. Runs detached in its own worktree with no operator present, so every "done" is gated by the 5-phase UI-fixture audit and an independent verifier.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20).** Always use subagents for substantive work; do not build solo in the main thread.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done".
> 4. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Subagent-First Protocol" + memory `feedback_subagent_first_protocol`.

This is the lane-4 command doc, fed verbatim to a detached headless `claude -p` worker with full authority
and NO operator present. Lane 3 is `tools/headless-upgrade.md`; the lane roster and the single
mutual-exclusion lock live in `ops/loop/lanes.py:105` (`LANES = ("upgrade", "uiux", "research", "ds",
"repo", "true-audit", "gated")`). Run sections in order.

### 1. Pre-flight baseline (do this FIRST, every time)

- **Confirm the worktree, not the main tree.** `git rev-parse --show-toplevel` must print
  `C:/rc-worktrees/rc-lane-uiux` and `git branch --show-current` must print `lane/uiux`. The convention is
  code, not lore: `ops/loop/lane_launcher.py:84` (`WORKTREE_BASE = C:\rc-worktrees`, overridable via
  `RC_LANE_WORKTREE_BASE`) and `:121` (`rc-lane-<lane>`). `ops/loop/lanes.py:221` `_require_worktree` raises
  on an absent worktree. If the toplevel is `C:/Riot Commander`, STOP and report; do not edit.
- **A fresh worktree has no hooks.** `python scripts/install_hooks.py` first (CLAUDE.md hard rule:
  `core.hooksPath` is LOCAL config and is not cloned). Then recall before building: `python
  tools/perseus_recall.py "<the item in your own words>"` - if a `settled` or `ledger` hit says CLOSED,
  report that instead of building.
- **Read, do not re-derive:** `CLAUDE.md` (UI Fixture Ritual, Execution Efficiency R1-R11, Session Default,
  Testing + Verification Discipline, the frozen-file list), `docs/UI_SCALE_SPEC_V2.md` (v2.1 tokens),
  `docs/qa/DESIGN_SYSTEM_MAP_2026-07-22.md` (the 4-layer cascade and where each token really lives),
  `docs/qa/THEME_MULTIHUE_METHOD_2026-07-22.md`, `docs/qa/SPATIAL_BRAND_SPEC_2026-07-22.md`,
  `docs/UI_CAPTURE_RECIPES.md`, `docs/OVERLAY_DOCTRINE.md`.
- **Probe live state, text-first:** `curl -k https://127.0.0.1:8888/api/state`, `curl -k
  https://127.0.0.1:8888/api/health/all`, Read `ops/runtime/health.json` (pid, alive, last_reload_ok). The
  cert is mkcert self-signed, so `-k` is mandatory; never screenshot to read a number, a version or a state
  (R2). **The dashboard must be UP** - both the pseudo-screen harness and the browser path load
  `https://127.0.0.1:8888`. If down: `echo restart > restart_trigger.txt`, then confirm a new `pid` +
  `last_reload_ok=true`.
- Note the HEAD sha you started from; `gh run list --limit 6` must be a green baseline.

### 2. Where the queue lives, and how to pick

Four sources, newest ruling wins. Read all four before picking.

1. `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md` - the MASTER ruling ledger (the operator's four asks, the F1-F4
   framing rulings, the PHASE 0-3 plan). Every ruling this lane makes is appended here.
2. `docs/qa/UI_UX_QUEUE_2026-07-21.md` - the source brief. Section A is the operator's own framing (do not
   narrow it), section B is ~20 already-diagnosed defects across Home / PGR / Replay / Settings / global /
   in-game overlay, section D is the method.
3. `ROADMAP.md` **RM-122** - read it, then respect its fence (section 7).
4. `docs/LIVE_GAME_GATED_SYNC.md` - anything whose acceptance needs a live game is NOT pickable here, and a
   headless proof may not be SUBSTITUTED for it (that substitution was the measured dominant failure of the
   2026-07-18 drain).

Pick rule: prefer a section-B defect that terminates in a **text-verifiable assertion** (a token value, a
DOM order, a computed style, a contrast ratio, a byte count) over anything that terminates in taste.
Per-page precedent to imitate: `docs/qa/CHAMP_SELECT_QA_2026-07-03.md` (the model artifact), plus
`HOME_QA_2026-07-04.md`, `LOBBY_QA_2026-07-04.md`, `PGR_QA_2026-07-04.md`, `E11_SWEEP_2026-07-04.md`.

### 3. The MOCK-DATA rule (there is no client and no live game)

League is not running, the LCU is not up, `:2999` is empty. Every render is driven from the fixture
mechanism the repo ALREADY has. Do not invent a second one.

- **Out-of-game pages: the `?ui_mock=1` path.** 31 JSON fixtures under `web/data/ui_mock/`. The flag IIFE at
  `web/js/main.js:6408` reads `?ui_mock=1` and sets `document.body.dataset.uiMock`; each panel's fetch
  call-site then short-circuits to its fixture (`web/js/main.js:3437` home, `:1804` session, `:1970`
  history, `:4037` lobby, `:4083-4090` champ select, `:4137-4141` active match by `&mode=`;
  `web/js/panels/build_insights.js:242-333` carries per-tab `mockUrl` entries). Per-page URLs:
  `docs/UI_CAPTURE_RECIPES.md`. Hard-reload to bypass the service worker.
- **In-game overlay: the pseudo-screen.** `tools/pseudo_screen_overlay.py <sr|aram|mayhem|complete|all>`
  renders the dock at 2560x1440 with no League and no live game over the same `?overlay=1` + `?ui_mock=1`
  path, writing `tools/pseudo_screen_out/overlay_<mode>_2560.png`. Needs the dashboard up. `ovscale=1.333`
  is load-bearing - without it the dock pins top-left at 1080p design px.
- **CI-durable renders: the snapshot harness.** `tests/snapshot_panels/` (58 modules) runs REAL headless
  Chromium (`conftest.py` `pw_browser`) against a fixture-driven mock HTTP server (`conftest.py`
  `mock_server`; fixtures at `tests/snapshot_panels/fixtures/*.json`, 10 of them, four adversarial:
  `adv_empty_strings`, `adv_no_coach`, `adv_null_fields`, `adv_out_of_range`). Any contract worth keeping
  gets pinned here. Scratch alternative: `ops/runtime/ui_recon/recon.py` renders one view at companion
  (920x1280) and desktop (1920x1080) with an overflow + visible-panel report - gitignored, delete at run
  end.
- **ROOTED IN REAL MATCH DATA is a rule about VALUES, not a second mechanism.** The existing fixtures are
  state-coverage shaped (their own `note` fields say "state-coverage check 5/7 per
  docs/UI_SCALE_SPEC_V2.md"), which is honest but is not the same as real. When you ADD or REFRESH a
  fixture, source its numbers from `data/rewind_history.db` (the real match store) or from the `.rofl`
  archive at `C:\Users\Administrator\Documents\RC_ROFL_Archive` (Layer-1 extraction yields 365-367 stat
  fields x 10 players, no client and no patch gate). Never hand-invent a stat line: impossible numbers
  manufacture UI bugs that do not exist and hide the ones that do.
- **Known fixture trap:** the `active_match_*.json` `liveclient` block is the RAW Live-Client envelope
  (`activePlayer` / `allPlayers` / `gameData`), while overlay panels consume the DERIVED
  `dashboard/_liveclient.liveclient_summary()` shape (`hp_max` / `game_time_s` / `kda` / `level` / `cs` /
  `stats.*`). A derived-shape panel gates on `lc.hp_max` and renders NOTHING under plain `?ui_mock=1` -
  inject a synthetic derived `lc` rather than concluding it is broken.

### 4. The RENDER-CONFIRMATION loop

**CLAUDE.md R3 governs: visual tools are for rendered-pixel / CSS / layout questions with no text
equivalent; everything else is text-first (R1/R2).** A screenshot answering a question `getComputedStyle`
could have answered is both a rule violation and a worse measurement.

1. **Computed styles + accessibility tree (default).** `preview_start` with a `url` opens the browser pane
   with no dev server; `navigate` to `https://127.0.0.1:8888/?ui_mock=1&mode=<sr|aram|arena>#<view>`,
   `read_page` for structure and `ref_N` handles, `javascript_tool` for the numbers -
   `getComputedStyle(el).fontSize` / `.color` / `.backgroundColor` / `.minHeight` and
   `el.getBoundingClientRect()`. Computed values are the ground truth for typography and hit-target floors;
   a source grep is not (section 6). `read_console_messages` + `read_network_requests` catch the fetch
   failures that surface as a stuck "loading...".
2. **The snapshot harness** when the assertion should survive into CI - same real Chromium, deterministic,
   runs on every push.
3. **Pixel capture** only for what the first two cannot answer: does the overlay dock composite legibly,
   does a gradient band, does an icon glyph render as an icon. Use `tools/pseudo_screen_overlay.py`
   (overlay) or `ops/runtime/ui_recon/recon.py` (page); attach the artifact path to the slice.
4. **OCR / CV confirmation.** The repo's OCR (`core/vision_tesseract.py`, `core/vision_template_match.py`)
   is calibrated to GAME-HUD regions via `data/vision_regions.json`; it is not a general dashboard reader
   and pointing it at a dashboard capture measures nothing. If a rendered-pixel claim genuinely needs
   machine confirmation, assert on the captured PNG directly (pixel sampling / dominant colour over a known
   rect) and SAY that is what you did. Never claim an OCR pass you did not run.

Historical trap: since 2026-06-28 the `preview_start name="Riot Commander"` launch.json path REFUSES to
reuse `:8888` ("Port 8888 is in use by pythonw.exe"). The `url` form and the `RC Web Static` config
(`.claude/launch.json`, `python -m http.server 8810 --directory web`) are the working alternatives; the
static server 404s `/api/*`, so panels render degraded there.

### 5. The 5-phase UI-fixture audit (HARD pre-commit gate)

No page change commits until the audit has RUN and every MUST-FIX is resolved IN THE SAME SLICE. Shipping a
page ahead of its audit (page #8) was called out explicitly by the operator. The audit is run by a subagent
that did not write the code - the agent that produced a thing never grades it; `.claude/agents/verifier.md`
is the read-only claim-checker.

- **STRUCTURE** - panel/grid matches the intended layout, no horizontal overflow at baseline, and a hidden
  container actually collapses (a bare `display:flex` beats the UA `[hidden]` rule and the cluster silently
  never collapses - measured, LEDGER 765).
- **TYPOGRAPHY** - every declaration on `docs/UI_SCALE_SPEC_V2.md` v2.1 tokens; no hardcoded sub-floor px
  below `--fs-xs` (16) without a documented operator exception carrying an inline rationale. Verify by
  COMPUTED value, not by grep.
- **HIT-TARGETS** - every clickable meets `--hit-min` (`web/css/tokens.css:119`, 42px) and has a
  `:focus-visible` affordance. Keyboard reachability belongs to this phase (section 6, trap 2).
- **ASCII** - 0 non-ASCII bytes introduced. `tools/web_ascii_sweep.py` is the JS/CSS/HTML comment tokeniser,
  `tests/test_web_comment_lines_ascii.py` the whole-tree guard, `tests/test_web_ascii_sweep.py` the
  false-positive pins. Before touching a RENDERED glyph read `docs/RM125_web_live_glyph_adjudication.md`: 31
  of the surviving 235 are LOAD-BEARING (e.g. `web/js/lib/items_index.js:62` holds a glyph as an alternation
  branch in a split regex), so a blind strip breaks BEHAVIOR, not just looks.
- **HIERARCHY** - readable at the 1920x1080 baseline with Chrome chrome present (usable viewport approx
  1920x920) without scroll, and the important thing is the brightest thing. Watch for hierarchy inverted by
  an INERT class: `dim` is inert repo-wide (`web/css` has no bare `.dim` rule, only descendant-scoped ones),
  so metadata tagged `dim` renders BRIGHTER than the note explaining it. Log SHOULD-FIX / NICE-TO-HAVE as
  FUTURE rows in the QA ledger, never as silent omissions.

### 6. Four measured traps this lane WILL hit again

Each is stated as a rule because each one passes the check you would naturally reach for.

1. **A `var(--x)` naming a custom property no stylesheet defines is INVALID at computed-value time and falls
   back to the INHERITED value.** It passes every source grep for the token name, so a grep-based token
   audit reports it clean. **`--bg` is defined nowhere in `web/css`** - the only `--bg:` declarations in the
   tree are `web/legacy_index.html:16`, `web/mock/oq3_*.html` and `web/vision_calibrator.html`, none of
   which the live dashboard loads. MEASURED: `color: var(--bg)` on the armed Mission Control button fell
   back to inherited near-white at **1.9:1 on amber**, on the one state where misreading the button costs
   most; `var(--canvas)` measures **9.03:1** there. Record: `web/css/panels/header.css:3082-3088`; guard:
   `tests/test_mission_control_panel.py:204`
   `test_every_custom_property_the_s4_css_uses_is_actually_defined`. **RULE: only a live computed-style read
   finds this class; every slice introducing a `var(--x)` extends that guard.**
2. **A panel that rebuilds itself with `innerHTML` on a timer throws keyboard focus to `<body>`.** MEASURED:
   `_mcPaint` rebuilt the row 4x/second while an arm countdown ran, so arming from the keyboard threw focus
   to `<body>` and the confirm click inside the 3s window was UNREACHABLE - the flow was silently
   mouse-only, and nothing in the source looks wrong. **RULE: any repainting host preserves
   `document.activeElement` across the repaint.** Pattern: `web/js/panels/dev.js:512-513` + `:573-574`
   (capture the focused id before the rebuild, restore after);
   `web/js/panels/overlay_ds_controls.js:367-378` is the other half (never overwrite an input the operator
   is currently in).
3. **Contrast must be computed on RESOLVED colors.** `web/css/themes.css` defines several tokens as
   `oklch()` - e.g. `:145` `--text-faint: oklch(0.63 0.045 40)`, `:227` `--surface-alt: oklch(0.31 0.036
   25)` - usually as a second declaration overriding a hex sibling on the line above, so a check parsing the
   hex it found by grep is checking a value the browser is not using. Resolve through `getComputedStyle`
   first.
4. **A token is AA on ONE surface, not on all of them.** `web/css/panels/base.css:19-20` documents
   `--text-faint` as WCAG-AA raised, "(4.88:1 on `--surface`)". MEASURED on `--surface-alt` it is **3.94:1**
   and `--bad` is **3.66:1** - both below AA, and that qualifier is the part everyone skips. **RULE: state
   the PAIR, never the token, when claiming a contrast result.**

### 7. Authority and limits

**MAY, without asking:** add, remove, relocate and REDESIGN the UI guidelines this lane works against - an
explicit grant in the lane-4 mandate. `docs/UI_SCALE_SPEC_V2.md`, the `docs/qa/*` specs and the
design-system map are all editable here, provided the guideline change lands with its rationale AND the test
that pins it in the same slice; a spec edited without the guard that enforces it is a wish, not a guideline.
Also: fix any section-B defect, add fixtures, add snapshot tests, restructure panel CSS/JS.

**MAY NOT:**
- Edit any `CLAUDE.md` frozen file (the 15-entry list under "Frozen files") **without an adjudicating
  agent's approval** recorded in the slice. There is no blanket headless grant in this lane; lane 3's
  frozen-file grant does not transfer.
- Commit a page ahead of its 5-phase audit. Ever.
- Pick up **RM-122**. `ROADMAP.md` fences it verbatim: "OPERATOR-PRESENT UI/UX LANE - THE HEADLESS LOOP MUST
  NOT PICK THIS UP", because every item terminates in a rendered-pixel judgement, the one class an agent
  cannot self-adjudicate under R3. This lane MAY PREPARE that work (map a page, author 2-3 layout
  alternatives, build the fixture a later operator-present session needs) and MUST log it as PREPARED, not
  DONE. Its item 1 additionally needs 8 logged-in desktop apps, and those shots stay LOCAL, never committed.
- Pull the `.rofl` q2400 backfill in; the queue routes it to RM-117 ingest.
- Close a `docs/LIVE_GAME_GATED_SYNC.md` row by substituting a headless proof.

### 8. The wrap

1. **Tests from the REPO ROOT** (from the DS dir, 13 CWD failures mimic registry regressions):
   `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest tests/ -q -n 8`,
   plus `tests/snapshot_panels/ -q` explicitly when the slice touched a rendered surface, plus `npm test`
   under `rc-shell/` for the Electron overlay. Report the counts you observed THIS run; never carry a
   subagent's number forward.
2. **Lint:** `... -m ruff check .` (F541 is the recurring CI killer) plus `-m py_compile` on any touched
   `.py`.
3. **ASCII hygiene:** `tools/web_ascii_sweep.py` + `tests/test_web_comment_lines_ascii.py` green, no em-dash
   / en-dash / smart quote / arrow / middot introduced anywhere. `tools/precommit_gate.py` and the git hooks
   are the authoritative backstop - a hook's PRESENCE is never proof it fires.
4. **Restart awareness:** editing `web/css/panels/*` or `web/js/panels/*` auto-reloads via
   `compute_asset_hash` (ADR-008) with NO RC restart - say so. A dashboard route needs `echo restart >
   restart_trigger.txt` plus a health.json confirm.
5. **Verifier gate, then merge, then commit + push.** Stage only files you authored; never `git add -A`.
   Unstage `_scratch/`, `tools/pseudo_screen_out/*.png`, `ops/runtime/ui_recon/*.png`. Commit message via
   `git commit -F <tmpfile>` (ASCII only).
6. **Append the per-item entry to `docs/LEDGER.md`** (append-only, newest-first). **NEVER to `CLAUDE.md`** -
   it is CI size-budgeted under 60KB and is touched only for rule / frozen-list / Settled changes. Append
   every ruling to `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md` too; that is this program's memory.
7. Update `WAKEUP_NOTES.md`, prune with `scripts/wakeup_prune.py --keep 3`, confirm CI green via `gh run
   list --limit 4`, clean worktree artifacts, then run `/done`.

### 9. Anti-patterns (do NOT repeat)

- Do NOT screenshot to read a number, a token value, a version or a state (R2).
- Do NOT audit tokens by grep - a defined-looking `var()` can be invalid at computed time.
- Do NOT report a contrast ratio without naming the surface it was measured against.
- Do NOT ship a repainting panel without a focus-preservation test.
- Do NOT invent fixture numbers; root them in `data/rewind_history.db` or the `.rofl` archive.
- Do NOT strip a rendered glyph before reading `docs/RM125_web_live_glyph_adjudication.md`.
- Do NOT commit a page before its audit, and do NOT defer a MUST-FIX to a later slice.
- Do NOT run against `C:\Riot Commander`; this lane is worktree-mandatory.
- Do NOT accept a subagent's "green" claim without an independent probe.
- Do NOT open an `AskUserQuestion`; the operator is away. Pick the reasonable default, log it.

### 10. Final banner

```
HEADLESS UIUX WRAP
  worktree: C:/rc-worktrees/rc-lane-uiux (lane/uiux)
  HEAD: <short-sha> (<N> commits this run)
  items: <N> closed / <N> PREPARED-for-operator / <N> FUTURE
  audits: <N> pages 5-phase audited, <N> MUST-FIX found + fixed in-slice
  renders: <N> computed-style proofs, <N> pixel captures (<paths>)
  tests: RC <N> passed / <N> skipped, snapshot_panels <N>, rc-shell <N>
  guidelines changed: <files, or none>
  CI: <N>/<N> green
  Ready for /done.
```

Then call `/done`.
