# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-22b - UI/UX pass: spatial brand decided + 6-theme OKLCH system + overlay/rofl infra (operator-present)

Merges into main: overlay `77ed2798`, rofl `fb91c2bb`, theme `a2848e4c` (+ 3 --no-ff merge commits). Full
program ledger: `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md`. This was a live operator-present session (per
`feedback_operator_ui_qa_method`), NOT headless.

DECISIONS + DELIVERABLES:
- **SPATIAL BRAND (operator-adjudicated):** RC out-of-game = a full floating LANDSCAPE hub +
  resolution-adaptive auto-fit + manual scale + remembered position. RETIRES the 920x1280 portrait AND
  the "live in the empty gutter beside the client" premise (no competitor does it; it was the root of the
  overflow/wrong-resolution pain). Measured Legion desktop 2560x1440 (work area 2560x1400, taskbar 40px,
  League client fixed 1280x720 centered). Swept 6 competitors LIVE (Overlay App E/Aggregator A/Coaching App Z7/Overlay App F/
  Aggregator C/Aggregator B/Overlay App Z5) - all floating landscape hubs ~1000-1650 wide, NONE dock to the client;
  Aggregator A's resolution auto-fit is the overflow cure. Full record: `docs/qa/SPATIAL_BRAND_SPEC_2026-07-22.md`.
  Memory `project_out_of_game_spatial_brand`.
- **THEME SYSTEM:** collapsed the 3 competing panel-chrome systems into ONE (killed the white-glass
  hairline on 10 DS panels), fixed the `--faint` AA contrast fail, repaired ds_statcheck. NEW
  `web/css/themes.css` = 6 swappable OKLCH multi-hue palettes (hextech/terminal/ember/bloodmoon/moonlit/
  arcane) via the `?theme` seam, **DEFAULT = terminal**. Passed the 5-phase fixture audit. Method +
  OKLCH recipes: `docs/qa/THEME_MULTIHUE_METHOD_2026-07-22.md`; design map:
  `docs/qa/DESIGN_SYSTEM_MAP_2026-07-22.md`.
- **OVERLAY pseudo-screen:** `tools/pseudo_screen_overlay.py` renders the in-game HUD headless at
  2560x1440 with no League (modes sr/aram/mayhem/complete) + 2 mock fixtures + a 2-line `_amMockUrl` seam.
- **ROFL q2400 backfill:** recovered 3 NULL-tracked rows LIVE incl `NA1_5604806601` (ARAM Mayhem q2400 ->
  Aurora 9/12/21, queue_id preserved). `core/rofl_stats_backfill.py` + `tools/rofl_tracked_backfill.py`
  (--commit gated, Riot-ID join never puuid). 25/25 tests pass on main. (4 net-new matches not in the DB
  are a separate ingest gap, not fixed here.)

NEXT SESSION (queued - `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md` + `SPATIAL_BRAND_SPEC` section 5):
- **Per-panel competitor capture library** (operator ask): capture each competitor app's individual
  panels for content+spacing research. Apps stay installed/logged-in on Legion; full-window shots
  preserved LOCAL (not committed) at `C:\Users\Administrator\Documents\RC_Competitor_Research\`.
- **Build the landscape auto-fit hub** (resolution-adaptive sizing; retire the 920x1280 portrait).
- **2-3 layout alternatives per page** (item A2) against the landscape hub + Terminal theme.
- **champ_select_view.css** Tailwind->theme conversion (ruling DS4 - the last off-theme page).
- Logged defects: footer "Legion-PC" (`web/index.html:2251`), em-dash `GRADE_LABEL` escapes
  (`performance_tracker.py:37-39`) + `data/ratings/*.json` backfill, nav-grid gaps, loading-forever,
  PGR double-grade/phantom button/provenance, Replay header clip, Settings voice picker.
- Optional: full theme deployment-map polish (header sweeps, gradient hairlines per the method doc).

---

# 2026-07-22a - HEXCORE Snapshots gallery refresh (full-scope mock + overlay mockup)

Commit `a50d42e2` (pushed, CI green). LEDGER 1004. ENGINE-IMPACT NONE (docs-only).

Operator ad-hoc ask: new mock-data snapshots in full scope + the in-game overlay mockup,
added to the HEXCORE offline explorer (`docs/HEXCORE_offline.html`, `window.HEXCORE_SNAPSHOTS`).

- Built a reusable Playwright capture harness: headless chromium, `ignore_https_errors`
  (bypasses the mkcert `:8888` cert), force mock via `localStorage.rc-ui-mock=1` (the
  `?ui_mock=1` fallback only fires when live `/api` is EMPTY, and Home has real data, so the
  localStorage force is required), `wait_until=domcontentloaded` (SSE push means networkidle
  never fires), viewport 560x798 DSF2 -> Lanczos downscale. Hits the LIVE :8888 so panels
  render real /api + the client-side mock fixtures = faithful to the originals.
- 12 current dashboard pages recaptured. Active Match now a populated SR game (was empty idle).
- Dropped the 2 stale champ-select subs (kit-axes+GPI, fight-model): that DS trio left
  champ-select upstream (`web/js/panels/champ_select.js:42`); replaced with a champ-select
  build+bans scroll.
- New In-Game Overlay entry (landscape 1000x563): overlay HUD widgets (`?overlay=1`, cue +
  DS build + minimap ZOI + launcher, control-center `#am-pane-ovds` removed) composited over a
  synthetic dark backdrop - no live game running, so a mock composite (the calib frames have a
  dev code-window dead-center, unusable).
- Verified live in the Browser pane (gallery + lightbox render), dust test 11 passed, ASCII clean.

Do NOT redo: snapshots are current as of this session. Capture harness + probe traps saved to
memory `reference_hexcore_snapshot_regen`. Only open follow-up: if operator wants a dedicated
GPI-radar / DS-profile entry back (via their new Builds/PGR homes), add it - otherwise nothing.

Next: pick the next ROADMAP item.

---

# 2026-07-21m - R162 SHARE PACKAGE MADE SHIPPABLE (gemini headless loop, cycle 9 - FINAL cycle)

LEDGER 1003. Merge `0bda3c2e` (six slices). ENGINE-IMPACT NONE - no bump, no DS bounce, no RC
restart. Operator stopped the loop at this cycle ("last headless run for these cycles");
`ops/loop/control/STOP` is written, so there is no cycle 10.

## What the directive asked vs what was actually wrong

The directive called the `Share/` presentation overhaul an unstarted unit. It is the THIRD pick of
it - R139 (`a4261c54`) and R149 (`774ed236`, the same day) both shipped it. The drift was real
anyway, and chasing it surfaced three defects that are product defects, not presentation:

1. **The shipped package could not pass its own test suite.** The sync mirrored
   `data/daemon_slayer/<patch>/**` only, so the patch-independent tables the engine reads through
   `ult_rates.py:60-63` (`spell_cast_rates.json`, `ult_cast_rates.json`) never shipped. A reviewer
   running it got 8802 passed / 108 failed / 172 errors while the README advertised 9190 passing.
   Both files ship now (497 -> 498). Honest exit-0 subset: 6920 passed / 0 failed with the 46
   ignored files named and the command printed.
2. **The public package redistributed a Overlay App E win-rate scrape.**
   `mayhem_augment_stats.json` (endpoint `data.v2.iesdev.com`, 199 augments with `win_rate`) shipped
   inside `Share/src` with no license grant, while the README claimed DS does not scrape win-rate
   aggregators and that the sidecars were consistent with Riot's no-win-rate policy. The DS engine
   has ZERO references to it. Excluded from the mirror; the live RC feed is untouched; the Overlay App E
   credit is reframed in `LICENSE.md`, not deleted.
3. **The recurrence is now mechanized.** `tests/test_ds_share_changelog_freshness.py` and
   `tests/test_ds_share_data_snapshot_scope.py` pin both classes by property. R139 had already
   diagnosed WHY this rots (the anchor rules exclude changelog history by design) and nobody wrote
   the guard - that is why it came back twice.

## Carry-forward for the next session

- The full `tests/` run was still in flight when this note was written; DS was 9190 passed / 1
  skipped / 3865 subtests and `ds_share_sync --check` green at 498 files. Confirm the RC suite +
  CI green for the final SHA before treating the package as reviewer-ready.
- The 46-file boundary set in the shipped package is characterized but not closed: 434 references
  to absent historical patch dirs (`16.10.1` / `16.11.1` / `16.13.1`) plus 8 lazy host imports.
  Closing it means either shipping the historical snapshots or re-pinning those tests.
- `Share/` should now be treated as a real external deliverable. Anything that changes the engine's
  data reads has to go through the sync's `_ROOT_DATA_FILES` / `_EXCLUDED_SNAPSHOT_FILES` or the new
  guards fail - which is the intended behaviour.

---

# 2026-07-21l - R161 ARENA STAT LINE DOCTRINE B (gemini headless loop, cycle 8) - ENGINE 1.237.0 -> 1.238.0

LEDGER 1002. Commit `77a34890`. ENGINE-IMPACT BUMP. DS bounced, both build-order families
regenerated, Share mirror re-synced. No RC restart needed (no route change).

## The decision

R152, R153 and R160 each surfaced the same question and each correctly refused to answer it: do
Arena mirrors inherit their SR twin's coefficients, or does an explicitly different DDragon stat
line win? The director answered **doctrine B - an explicit Arena stat line wins.** Arena mirrors no
longer inherit SR BASE STAT magnitudes. Passive-COEFFICIENT inheritance where Meraki has no mirror
entry is unchanged; only explicitly-stated base stat lines flip.

Twelve rows re-credited from their own DDragon 16.14.1 feed entry: lethality `223142` 18->22,
`223814` 15->14, `224004` 15->21, `226676` 10->12, `226699` 10->20, `226701` 18->15, `226691`
18->22 (inert, maps={}); flat magic pen `223020` 12->20, `224645` 15->10; percent pen `223036`
0.35->0.40, `226694` 0.35->0.40, `223302` Terminus 0.30->0.24 on both axes (8 percent per stack,
cap 3). SR twins untouched.

Highest live impact is the BOOT, not the lethality list: `223020` is the Arena mage default boot,
in essentially every Arena AP build, under-crediting magic damage ~5.7-6.9 percent through
`effective_target_mr`.

## Two directive premises were refuted before any code landed

1. The directive said to invert `test_arena_prowlers_lethality_same_as_sr`. `226693` Prowler's Claw
   states 22 in the Arena feed and SR `6693` states 22 - an exact match, never a divergence.
   Inverting it would have fabricated a failure. Kept; only its docstring reason changed.
2. "Meraki carries no 22xxxx/44xxxx mirror ids at all" (repeated in ORCHESTRATION_PLAN since R152)
   is FALSE - the pinned 16.13.1 snapshot carries 17. It just lacks `223302`, the only claim the
   Terminus guard needed. Both corrections are now fenced in the plan's don't-redo.

Doctrine B also was not novel: `226695` Arena Serpent's Fang has always credited its own 19 against
SR `6695` 15, and R152 said "do not normalize them". The call generalizes an existing exception.

## The bump was not the deliverable - the regen was

A bump alone leaves every precomputed Arena build order computed under the REJECTED doctrine. Both
families regenerated against the bounced 1.238.0 engine: **99 of 173 Arena build orders and 89 of
173 Arena variants moved.** Drift-guard held exactly as predicted - SR and ARAM differ only in
stamp fields (all 12 ids are map-30 only), so a non-stamp SR/ARAM diff would have meant a leak.
`reference_build_order_regen_full_roster_and_nightly` earned its keep twice: the WRONG-TOOL trap
(the `tools/` script is not what the stamp tests read) and the `--champions all` trap (omitting it
collapses 173 champs to a 10-champ seed).

## Incidental find - the flat table was ten engine versions stale

`data/daemon_slayer/16.14.1/build_orders_sr.json` picked up a `6696` -> `6695` flip in 6 SR cells
(Zed, Qiyana). Last written at ENGINE 1.228.0 (`1f13188b`); the nested table already carried `6695`
at 1.237.0, so the two disagreed before this cycle. The live deterministic + laning coaches had
been serving 1.228.0-era builds. Now current. Not caused by doctrine B.

## Gates

Verifier CONFIRM 8/8 on the merged tree. DS 9190 passed / 1 skipped / 3865 subtests. RC suite
green. ruff clean. `ds_share_sync --check` green at 1.238.0. Three worktree agents on disjoint file
sets (engine data / guard tests / docs), Claude sole merger, engine merged first and docs last.
