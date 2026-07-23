# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-23c - Haiku-to-ZERO: five-layer deterministic draft score aggregator + route

Commit pending push. ENGINE-IMPACT NONE (no DS bump, no :8893 bounce, no Share touch). LEDGER 1007.

- **NEW `core/draft_score.py`** (Haiku-to-ZERO sibling of session_hygiene / playstyle_labels): closes
  the BACKLOG "Five-layer deterministic draft score" NOW item. ZERO API/LLM. Fuses lane-matchup 30pct /
  pairwise-synergy 20pct / AD-AP-tank damage-balance 15pct / early-late scaling 10pct / base-WR 25pct
  into ONE bounded score + HIGH/MED/LOW confidence.
- **Data sources (all owned):** matchup / synergy / base-WR from `core.draft_elo_db` (the `participants`
  table = full 10-player Match-V5 rows, DISTINCT from the tracked-only `matches` table playstyle/hygiene
  read; Laplace-smoothed via core.smoothed_rates). Damage-balance from an injectable DS kit-mix resolver
  (`core.damage_mix` with EMPTY items = kit-only physical/magical lean). Synergy nudged by item-277 101qq.
- **HONEST 42-58 band** (no-fake-spread): trust-weighted (weight x shrink(n)) mean of layer WR-deviations,
  50 + delta*100, hard-clamped [42,58]. A layer with no evidence is marked contributed=False and drops
  out of the blend - NOT dragged toward 50. Scaling layer ships INERT by design (no cheap per-champ
  power-timing primitive; declared with reserved 10pct weight, activates when a scaling_resolver is fed).
  Pure `fuse_layers()` split out DB-free for the math proof. Never-raises.
- **NEW route `/api/draft-score`** (`routes_draft_score.py`): ?ally + ?enemy + ?queue, 5min LRU cache,
  structured 400/500, wires the default DS + 101qq + name resolvers. Into `_dispatch.py` GET chain (110 routes).
- Verified: 23 aggregator/route tests + 1435 dispatch/route/draft suite green, ruff clean, RC restart
  alive+reload_ok (pid 9584), live HTTPS probe served score 54.4/MED (4 layers contributing from real
  corpus + DS kit-mix), 400 on bad-length, matchup inert with no enemy comp.

NEXT: Haiku-to-ZERO consumer/UI wiring for the three new routes (session-hygiene / playstyle-labels /
draft-score) is operator-present-preferred (do NOT build headless). Premade detection stays BLOCKED
(tracked-only matches table). Do NOT touch RM-99b Heartsteel cadence. A DS spike-derived scaling_resolver
would activate the draft-score scaling layer (future, when the operator wants it).

---

# 2026-07-23b - Haiku-to-ZERO: playstyle-labels aggregator + session-hygiene/playstyle routes

Commit `06cd7bf3` (pushed, CI pending). ENGINE-IMPACT NONE (no DS bump, no :8893 bounce). 5 files, 849 insertions.

- **NEW `core/playstyle_labels.py`** (Haiku-to-ZERO sibling of session_hygiene): deterministic
  per-champion playstyle fingerprint over the player's own rewind_history.db. ZERO API/LLM.
  Self-relative VERDICT labels (death-prone/averse, kill-focused/low-kill, team-involved/solo-leaning,
  consistent/high-variance) comparing each champ's per-game means to the player's OWN cross-champion
  baseline - observation not causal advice. **Champion-keyed on purpose**: corpus is ARAM-dominant,
  `tracked_lane` is 0 for 2963/2966 games so a lane/role split degenerates to one bucket. Mirrors
  session_hygiene: `_open_ro` seam, laplace/shrink/blend, never-raises, "-" thin sentinel. 16 tests.
  Live corpus: 83/99 eligible champs labeled; CV_HIGH=0.70 catches top ~20% (well-calibrated, not
  firing on everything).
- **NEW route `/api/session-hygiene`** (`routes_session_hygiene.py`) - the OWED consumer surface for
  the already-shipped session_hygiene aggregator (`1653d959`). ?queue filter, 5min cache, structured
  400/500 (no raw error leak). Mirrors routes_duration_winrate.
- **NEW route `/api/playstyle-labels`** (`routes_playstyle_labels.py`) - ?queue + ?min_games, 5min cache.
- Both wired into `dashboard/_dispatch.py` GET chain.
- Verified: 38 aggregator tests + 25 route-count guards green, ruff clean, RC restart alive+reload_ok
  (pid 31872), both endpoints serve well-formed JSON over live HTTPS (n=2963 / n=2966).

NEXT: remaining Haiku-to-ZERO siblings - the five-layer deterministic draft score (needs duo-synergy +
DS damage-mix fusion; honest 42-58 band) is the biggest open one. Premade detection is BLOCKED (matches
table is tracked-player-only; no teammate identity columns). UI/snapshot-card wiring for both new routes
is operator-present-preferred (do NOT build headless). Do NOT touch RM-99b Heartsteel cadence.

---

# 2026-07-23a - headless loop: 5 slices + 1 CLEAN sweep (self-adjudicated, operator away)

Commits (all pushed, CI-green): `02137ffb` `0a05e897` `083605c5` `37d13e85` `1653d959` + LEDGER `1006`.

- **CI-red fix** `02137ffb`: nightly OQ6 dark-ratchet red on the theme swap - themes.css pinned at 36 (theme-source layer), ds_statcheck pin 3->0.
- **G2-12 ranged reflect** `0a05e897`, **ENGINE 1.238.0 -> 1.239.0**: shipped a stale WIP branch (rebased 1.232->main), ranged exposure factor 0.35, melee byte-identical; 145 pins synced, DS live 1.239.0, 9203 DS tests. FUTURE: mode-aware ARAM factor.
- **RM-112 CLOSED** `083605c5`: Share package runs its own suite clean standalone (7270/0/0). Excluded 40 host/cross-patch tests + shipped CC_CONDITIONAL_NOTES.md; rewrote 05_AUDIT + added the 1.239.0 Share release entry. 97 guards green.
- **perf-tracker em-dash strip** `37d13e85`: 27 runtime em-dash escapes -> hyphen (source-byte scanners miss the `\uXXXX` class), 4 ratings JSON backfilled, new runtime-ASCII guard.
- **session-hygiene aggregator** `1653d959` (Haiku-to-ZERO): NEW `core/session_hygiene.py` + 22 tests - deterministic tilt/readiness over rewind_history.db, zero API/LLM. Consumer surface (route + card) OWED.
- **cost/latency sweep**: 7/7 CLEAN, no commit.

NEXT: build the sibling Haiku-to-ZERO deterministic aggregators (playstyle labels / draft score / premade detection) + wire session-hygiene to a read-only `/api/session-hygiene` route. Do NOT redo RM-112 (closed) or re-ship G2-12 (1.239.0 live). Do NOT touch RM-99b Heartsteel cadence headless (operator-gated). UI wiring is operator-present-preferred.

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
