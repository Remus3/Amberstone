# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-23i - rc-shell stale-overlay blocker cleared + 1.239.0 stamp drift

Two commits, LEDGER 1013. Tier-1 + data-regen. ENGINE-IMPACT NONE. CI green
(`30057696467` + `30057696474`). The live-frame acceptance is STILL OWED - it
is not drainable headlessly; see below.

- **Blocker cleared.** Electron was started 17:36:32, the widget landed
  18:10:21, so the running overlay had no `w-nextbuy`. Killed the tree,
  relaunched with `--remote-debugging-port=9222 --remote-allow-origins=*`.
  CDP confirms the renderer fetched `next_buy.js` / `next_buy_model.js` /
  `next_buy.css` / `overlay_layout.js`, and `#am-next-buy` is present,
  hidden, `display:none`, rect 0x0 - the no-reflow half is discharged.
- **GOTCHA: rc-shell holds a single-instance lock.** A second launch with
  new flags exits silently and leaves the STALE process serving. Kill the
  ROOT pid `/T` first.
- **1.239.0 stamp drift was 12 red, not 14.** Regenerated both tables with
  the commands the failures cite; re-ran fresh: 19 passed, 6 skipped, and
  each of the 12 verified PASSED individually. The 6 skips are the opt-in
  `test_content_freshness_matches_static_regen` params, skipped before too.
- **NEW `tools/overlay_live_frame_probe.py`** - one command for the owed
  acceptance. Selectors verified against source first; my first draft
  guessed `#am-objective-gauges` / `[data-og-dial]` and both were wrong.
- **STILL OWED - needs the operator in an SR game.** All four acceptance
  lines gate on `body[data-shell="overlay"]` (`next_buy.js:83`), which only
  exists mid-game. ARAM/Arena exercise neither BARON nor the trinket row.
- **Caveat on my own tool:** its `current_gold` path
  (`liveclient.activePlayer.currentGold`, fallback `liveclient.current_gold`)
  was never confirmed against a real payload - liveclient was empty all
  session. A null GOLD cross-check in-game means that path, not the widget.
- **Do NOT redo:** the theme picker, the widget, the cadence, or the table
  regen. Do NOT re-derive the CDP session - use the committed probe.

---

# 2026-07-23h - Settings theme picker + arcane default

Two commits, LEDGER 1012. Operator-ad-hoc (not a ROADMAP item). Tier-1 + UI.
ENGINE-IMPACT NONE. ZERO API / ZERO LLM / ZERO server-side additions. CI green
(`30054685888`). The live-frame overlay verification queued for this session
was BLOCKED - no game was running - and is still owed; see below.

- **Trigger:** operator noticed the dashboard has no theme selector. Probe
  confirmed it: the 6 DS2 palettes were reachable ONLY via `?theme=`
  (`main.js:116-124`), a swap-and-pick evaluation seam that never shipped a
  control. Settings `#view-settings` was the obvious home.
- **NEW `web/js/lib/theme.js`** is the single source of truth (THEMES
  whitelist, DEFAULT_THEME, THEME_KEY, and the SOLE writer of
  `<html data-theme>`). `hextech` stays UNSTAMPED - base.css `:root` owns the
  gold palette, so stamping the string would break it. Precedence:
  `?theme=` wins session-only and never writes storage -> localStorage
  `rc-theme` -> default.
- **Storage key is `rc-theme`, NOT `rc_theme`.** The Plan agent caught that my
  proposed underscore key contradicted the repo convention (`rc-view-manual` /
  `rc-ui-mock`); underscores are infra-only (`rc_dash_token`).
- **Inline pre-paint `<head>` guard in index.html.** Without it a persisted
  theme flashes the gold base palette on EVERY load, because main.js is a
  `type=module` at end-of-body. It hand-copies the whitelist (it must run
  before the module graph), so a static drift test pins the two copies.
- **Then the default flipped terminal -> arcane** (operator pick, `7d63b85b`).
  The flip silently WEAKENED an existing test - `test_stored_theme_applies_
  and_selects` seeded `arcane` to prove the storage read works, and `arcane`
  had just become the default, so it would have passed with the read fully
  broken. Now it picks the first non-default non-hextech theme. Caught on
  review, not by a failure. **Lesson: flipping a default can turn a real
  assertion into a tautology - re-read every test that names the old value.**
- **Verified:** 14 green (`test_settings_theme_picker.py` 10 new + 
  `test_settings_view.py` 4), ruff clean, hygiene trio 13 green, CI green.
  5-phase UI audit did a REAL live render (Chrome DevTools MCP, not static):
  select measures 360x45 / 22px `--fs-md`, byte-identical to the sibling
  select. Zero MUST-FIX. ADR-008 covers all four web files - no RC restart.
- **Do NOT redo:** the picker, the FOUC guard, the drift test, or the default
  flip. All shipped and pushed.
- **Logged, NOT fixed (both pre-existing, now more visible):** 7 panels emit
  hardcoded hex into generated SVG (`active_match`, `ds_sweep`, `map_state`,
  `objective_gauges`, `spike_curve`, `threat_donut`, `ward_heat`) and do NOT
  re-tint on a live theme switch. And the DISPLAY settings-card renders at
  y=1092 on the 1920x1080 baseline - below the fold, because CLIENT SETTINGS
  sits above it in a single 896px column.
- **STILL OWED from 2026-07-23g:** live-frame verification of `w-nextbuy` +
  the OQ16 90s/10s cadence. Probed this session: `mode_key=client`,
  `has_game=false`. Also found rc-shell is STALE - the electron processes
  started 17:36:32, the widget landed 18:10:21, so the running overlay has no
  `w-nextbuy` module at all. It needs a full relaunch (NOT a hot-reload)
  before any live check is meaningful.

---

# 2026-07-23g - Overlay HUD micro-lifts (BACKLOG NOW closed, all 3 slices)

One commit + LEDGER 1011. ENGINE-IMPACT NONE (frontend panels + CSS + one
CustomEvent in the shared item dictionary; no DS bump, no :8893 bounce, no
Share touch). Tier-1 + UI. ZERO API / ZERO LLM / ZERO server-side additions.

- **The probe found slice (c) already built server-side and never rendered.**
  `core/build_planner/replan.py:684-689` has emitted `kind="upgrade_trinket"`
  (3340 Stealth Ward -> 3363 Farsight Alteration, gated `stage >= mid` via
  `scoring.stage_for`) all along - no surface consumed it. So the trinket lift
  is a CONSUMER, not a new heuristic. Do not re-invent that rule.
- **(a)** `objective_gauges.js` `_alertTier` -> `soon` (<= 90s) / `imminent`
  (<= 10s) on any counting-down dial, off the SAME `etaS` the ring draws (so
  it cannot drift from the `core/event_callouts.py` mirror). UP / "-" never
  escalate. In `gaugesSig`, else a threshold crossing leaves a stale alert.
- **(b)+(c)** NEW `w-nextbuy` widget: `web/js/lib/next_buy_model.js` (PURE,
  node --test) + `web/js/panels/next_buy.js` (thin render) + `#am-next-buy`.
  Rows NEXT / GOLD / TRINKET. GOLD = cost - owned DIRECT components - gold.
- **Two bugs the tests caught, neither shipped.** `Number(null) === 0` made an
  ABSENT purse read as a confident `0g` (gold is activePlayer-only). And
  `ITEM_COSTS` is an ASYNC fetch - the first render beat it and sig-dedup then
  PINNED the "-" sentinel; fixed with a new `rc:item-costs-ready` event from
  the `items_index.js` cost loader. **The second was invisible to unit tests -
  only the rendered-Chromium harness caught it.** Any future overlay panel
  that reads an items_index singleton needs the same re-render wiring.
- **Widen-to-fit is real, not theoretical.** The 210px `--ovx-w` default
  ellipsised "Farsight Alteration" in the rendered proof -> 260px in
  `overlay.css`, pinned by a `scrollWidth <= clientWidth` assertion.
- **OWED: in-game live-frame verification.** rc-shell does NOT hot-reload a
  NEW overlay JS module ([[reference_overlay_live_verify_technique]]), so
  `w-nextbuy` needs a relaunch + a live game. No game ran at ship time.
- **Repo was already RED before this slice.** 14 pre-existing failures, all DS
  `ENGINE_VERSION` stamp drift from `3956081f` (build-order precompute +
  variants tables stamped 1.238.0 vs engine 1.239.0, plus the docs drift + the
  Share-mirror check). PROVEN pre-existing in a detached worktree at clean
  HEAD `7a563ae0`. **A build-order table regen + docs sync is owed by whoever
  owns that DS bump - it is not this slice's to fix.**
- Also closed the BACKLOG playstyle-inference line, verified stale against the
  shipped `core/playstyle_labels.py` + `/api/playstyle-labels` +
  `#playstyle-labels-card` (`6f1b6d11`, LEDGER 1008).
