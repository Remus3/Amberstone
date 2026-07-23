# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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


# 2026-07-23f - GPI radar target-profile reference polygon (BACKLOG NOW/MED closed)

One commit, pushed: `8afe91cf` + LEDGER 1010. CI green (ci + CodSpeed).
ENGINE-IMPACT NONE (core module + route passthrough + asset layer; no DS bump,
no :8893 bounce, no Share touch). Tier-1 + UI. ZERO API / ZERO LLM.

- **The probe changed the design before any code.** BACKLOG asked for a "better-WR
  reference polygon". Measured live: `rewind_history.db` = 30928 participant rows over
  **23441 DISTINCT puuids**, only **20 puuids reach 20 games** (operator + a few
  premades). No population to rank win rates over -> a better-WR cohort would have to
  be INVENTED. Built the operator's OWN winning games, which the task pre-authorized.
  SR 338W/296L, ARAM 1028W/976L - ample.
- **`core/player_gpi._reference_block(games, window)`** -> `{kind:"own_wins", label, n,
  min_games, axes:[{key,score} x 8]}`, None below `MIN_REFERENCE_GAMES` (5) wins -
  never a partial polygon. Reuses `_relative_axis` / `_versatility_axis` /
  `_consistency_axis` unchanged (survival sign handling comes free, pinned).
- **Two parity decisions carry the feature.** (a) The percentile baseline stays the
  FULL filtered history - the same baseline `axes` uses - so a reference vertex and a
  player vertex at equal radius mean the same thing. (b) The reference set is capped at
  the most recent `window` WINS, not all wins: versatility is Shannon entropy
  normalized by `log(n)`, which saturates at `log(pool)` while the normalizer keeps
  growing, so 338 wins vs a 20-game window would read artificially LOW for no reason.
- **Route unchanged** - `/api/player-profile` passes the block through, cache included.
  The `EMPTY_KEYS` contract guard in `test_player_gpi_robustness.py` caught the payload
  change on the first run (the guard working, not a regression).
- **Panel** `web/js/panels/player_gpi.js`: `_refPolySvg` + `_refLegend`. Dashed teal
  ring emitted BEFORE `_dataSvg` so the filled recent-form polygon paints on top (SVG
  has no z-index - pinned by a document-order test), matched by axis KEY not position,
  ALL-OR-NOTHING on a null axis (a truncated ring would read as a real shape).
  `_signature` grew a `ref:` segment. Teal = the one panel hue not already spoken for.
- **5-phase fixture audit PASS, zero MUST-FIX.** ASCII asserted across .js/.css/.py/test.
- **Live SR read (634 games, 20-win reference):** objectives 41.5 -> 65.5, survival
  30.0 -> 45.2, tempo 48.1 -> 63.1 = the actionable gap. Versatility flat 44.9 vs 44.3,
  which is decision (b) paying off.
- **Verified:** 21 new backend + 6 new panel tests; 106 GPI/route green; full
  `tests/snapshot_panels` 393 green; 472 green across the gpi/player_profile/
  asset-hash/contract selection; ruff clean; RC pid 25664 alive + last_reload_ok; live
  HTTPS probe served the block.
- **Docs/memory:** BACKLOG line closed (the CHI-paper Diamond+ mechanics-band tail is
  left OPEN - it needs an external distribution RC does not have). Memory
  `reference_rewind_history_db` gained the no-cohort measurement + the equal-n rule.

---

# 2026-07-23e - patch-impact aggregator + route + Session card (+ the flagged ds_shaper red)

Three commits (all pushed): `ff77164f` `ad99cec7` `86b40fe7` + LEDGER 1009.
ENGINE-IMPACT NONE (aggregator + route + asset layer; no DS bump, no :8893 bounce, no Share).

- **ds_shaper red closed first** `ff77164f`: the 5/6 failure was the test file's own
  FakeEl shim missing `setAttribute` (prod `renderShaperStrip` marks the strip
  `[data-rc-zone]` for the overlay clickthrough zones). Added the attribute trio +
  a regression assert on `data-rc-zone`. 6/6. The task chip can be dismissed.
- **NEW `core/patch_impact.py`** `ad99cec7` (Haiku-to-ZERO sibling; closes the BACKLOG
  "patch-diff what changed for YOUR champs" tail): RM-110 cross-patch DS snapshot diff
  x the player's own rewind play counts. `_open_ro` + injectable `diff_fn`/`patches`/
  `key_map`, laplace winrate, never-raises with a stated reason. Join is on
  `champions.json` `key` (numeric), NOT the display name; item changes attribute only
  when the item is in that champ's build order for the mode. 29 tests.
- **NEW `/api/patch-impact`** same commit: `?mode&top&min_games&old&new`, 5min cache,
  structured 400/500, patch names gated on the ON-DISK allowlist (`ds_patch_diff._resolve`
  takes any existing dir - never hand it the raw query). 16 tests.
- **NEW Session `#patch-impact-card`** `86b40fe7` (`web/js/panels/patch_impact.js` + .css,
  21 tests): per-champ stat/ability/build/item chips, detail in tooltips, `-` sentinel on
  a no-change champ (no reflow). Descriptive-only is TEST-PINNED (no buff/nerf wording).
  5-phase audit PASS, zero MUST-FIX.
- Live: 16.13.1 -> 16.14.1 over 2044 ARAM matches in 76ms; the 8 changed items are Arena
  mirrors + components + Rocketbelt, so zero ARAM-build attributions is correct.
- Doc drift corrected against git: ROADMAP RM-111 "consumer surface NOT wired" was stale
  (shipped `a626ece0`); BACKLOG `/api/personal-build` UI tail likewise already shipped.

NEXT: RM-01 (Haiku-to-ZERO Lane E CV substrate) is still the top open thread and is
live-gated - `data/fusion_shadow.jsonl` does not exist yet, so the flip gate is genuinely
unmet. Do NOT flip blind. Non-gated BACKLOG siblings left in this lane: the radar
target-profile reference polygon and the predicted roam/invade route. Premade detection
stays BLOCKED (tracked-only matches table). Do NOT touch RM-99b Heartsteel cadence.

---

# 2026-07-23d - Haiku-to-ZERO: all 3 aggregator routes wired to UI cards + scaling layer activated

Three commits (all pushed): `7c86c4fa` `6f1b6d11` `703af159` + LEDGER 1008.
ENGINE-IMPACT NONE (asset + route-layer only; no DS bump, no :8893 bounce, no Share).

- **draft-score card** `7c86c4fa` -> Champ Select `#csv-draft-score`: 42-58 score +
  HIGH/MED/LOW chip + 5-layer contributed/inert breakdown, "-" sentinel on inert.
  SR-draft-only, hidden until 5 ally committed. NEW `web/js/panels/draft_score.js`
  (+ .css, 12 tests). 5-phase audit caught+fixed a flex horizontal-overflow MUST-FIX.
- **session-hygiene + playstyle cards** `6f1b6d11` -> Session view: NEW
  `session_hygiene.js` (`#session-hygiene-card` "SHOULD I QUEUE" 0-100 readiness +
  signed factor nudges + 8-bar tilt strip, 10 tests) + `playstyle_labels.js`
  (`#playstyle-labels-card` labeled-only champs, top-12 + "+N more", 9 tests). Both
  self-fetch on the session view switch (`main.js`). 5-phase audit PASS both.
- **scaling layer activated** `703af159`: `routes_draft_score._SpikeScalingResolver`
  derives per-champ power-timing 0..1 by reusing `routes_spike_curve._build_champ_curve`
  + the 70%-crossing minute (pure `_peak_timing` helper). Layer now CONTRIBUTES
  (live: contributing 4->5, scaling sub 0.65, score 55.5). 10 route tests. Cold
  1518ms / warm 0ms / 24h per-champ curve cache. All 5 draft-score layers now live.
- Verified: ruff clean, hygiene 13, py 42, node 31 green; RC pid 21616 alive+reload_ok.

NEXT: nothing pending on the Haiku-to-ZERO aggregator lane (BACKLOG lines 56-57
consumer surfaces DONE). Premade detection stays BLOCKED (tracked-only matches
table). Pre-existing `ds_shaper.test.mjs` red (5/6, unrelated) flagged as a chip.
Do NOT touch RM-99b Heartsteel cadence (operator-gated).
