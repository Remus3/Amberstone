# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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
