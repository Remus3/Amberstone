# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-23k - live-frame acceptance ADJUDICATED (owed 4 sessions, now closed out)

One commit, LEDGER 1014, Tier-1, ENGINE-IMPACT NONE. The operator queued SR and
the four acceptance lines were adjudicated against a real 22m30s game (Kai'Sa,
~300 CDP samples). **2 PASS, 1 FAIL-upstream, 1 OPEN.** RM-113 + RM-114 opened.

- **PASS - OQ16 cadence, both edges seen live.** `""` -> `soon` on drake at eta
  `1:32` -> `1:29`; `soon` -> `imminent` on baron at `0:11` -> `0:09`; then
  `state=up` at spawn. Matches `alertSoonS: 90` / `alertImminentS: 10`
  (`objective_gauges.js:66-67`) within the 3s sampling.
- **PASS - no reflow.** `#am-next-buy` = 108px across 235 in-game samples; the
  only `h=0` rows land after `game_time_s` goes null, so it tears down cleanly.
- **FAIL, but NOT the widget - RM-114.** `item_advisor.resolve_build` covers
  **6 of 172 champions** (Caitlyn, Jinx, Miss Fortune, Nilah, Tristana, Vayne).
  Kai'Sa returns `[]`, so no `sr_items` row carries `next:true` and the GOLD row
  correctly renders `-`. Invariant across three `owned` states (not the
  empty-build artifact) and across `Kai'Sa`/`Kaisa`/`KaiSa` plus plain `Ashe`
  (not name normalization). **Do NOT fix this blind** - sourcing `next` from DS
  changes what "next item" means; it is an operator product call.
- **OPEN - TRINKET, one field short.** Never activated in 260 samples, but
  `stageFor` returns `mid` on the clock arm alone at `c >= 600`
  (`next_buy_model.js:68-72`), so stage was provably `mid`/`late` for the last
  12.5 min and the gate cannot explain it. Hinges entirely on whether
  `owned_items` still held `stealth ward`. The probe now records that.
- **Probe fixed twice:** now emits `owned_items` / `completed_count` / `stage` /
  `holds_upgradable_trinket` / `next_item` / `sr_items_len`, and flushes per
  sample. **The flush matters** - block-buffered redirect served a 7-min-stale
  baron ETA that got reported as current, contradicting the operator mid-game.
  They were right; the file was wrong. Re-probe live before contradicting.
- **NEXT SESSION:** one SR game closes the TRINKET line with no new analysis -
  just run the probe and read `holds_upgradable_trinket` + `stage` against the
  TRINKET row. Then RM-114 needs an operator decision, not code.

---

# 2026-07-23j - live-frame probe gold/clock paths root-caused (caveat retired)

One commit (`10e92cf5`), Tier-1, ENGINE-IMPACT NONE. The live-frame acceptance
is STILL OWED - fourth session now - and still needs the operator in an SR game.
No headless work remains on it; the pre-flight is fully discharged.

- **Probe pre-flight PASSES.** rc-shell still alive with the CDP flags (root
  pid 2232) - no relaunch needed, the `2026-07-23i` blocker stays cleared.
  Probe attaches, reads the DOM, reports `#am-next-buy` present + hidden +
  rect 0x0 at `mode_key=client`.
- **The `2026-07-23i` caveat is RETIRED - it was a real bug, now fixed.**
  `/api/state.liveclient` is the FLATTENED block from
  `dashboard/_liveclient.py:114 liveclient_summary()` (attached at
  `dashboard/_state_builder.py:687`), NOT the raw Live Client `:2999` payload.
  Gold is `liveclient.gold` (`_liveclient.py:148`); the clock is
  `liveclient.game_time_s` (`_liveclient.py:144`). The probe read
  `activePlayer.currentGold` / `current_gold` / `gameData.gameTime` - none of
  those keys exist in that shape, so BOTH fields would have read null in-game
  regardless of widget behavior. A null GOLD in the next run is now a real
  widget signal, not probe noise.
- **Do NOT redo:** everything the `2026-07-23i` do-not-redo list names, plus
  this path fix. Do NOT re-derive the CDP session - use the committed probe.

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
