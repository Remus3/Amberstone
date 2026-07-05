# Player Snapshot Card - Design Spec

Date: 2026-07-04
Status: DRAFT (awaiting operator review)
Author: Claude (brainstorming session)
Source mockups: `Desktop/Icons and ideas/luna-sever-2.jpg` (annotated card),
`luna-sever-1.jpg` (competitor teardown), role-icon set (same folder).

## 1. Goal

Ship a compact, Hextech-styled player-snapshot card (the annotated luna-sever-2
layout: rating dial + 4 composite bars + 3 behavioral tags + KDA/Win-Rate/K-P
mini-dials + a name/rank/level/streak header + a "View Profile" expand). The
card is a SELF snapshot in v1 (the operator's own play), with a normalized data
contract that leaves room for an opponent-scouting adapter later.

It mounts in two places, each with its own data window:
- Home: one card per mode tab (SR / ARAM / Arena), showing that mode's LAST 24
  HOURS, aggregated.
- PGR (post-game review): one card for the specific match + mode being reviewed.

Operator directive: on both pages, ABSORB / REARRANGE / REFACTOR any existing
element whose information the card now shows. No duplicate information.

## 2. Why this is small (reuse-first)

RC already owns roughly 80 percent of the card's substance. Confirmed by recon
(file:line below):

- `core/player_gpi.py:55-81` computes 6 relative axes (aggression=dmg/min,
  farming=cs/min, vision=vis/min, objectives=obj/game, survival=deaths/min,
  tempo=gold/min) plus 2 shape axes (versatility, consistency), each scored
  0-100 as a self-relative percentile vs the operator's full history, from the
  local `rewind_history.db`. No Riot API, no Claude. `overall` and
  `weakest_axis` + `tip` already exist (`player_gpi.py:330-343`).
- `core/post_game_rubric.py` computes per-role saturation bars (KDA / CS-min /
  Objectives / Vision / DPM, 50 percent = role median, 100 percent = 2x) served
  at `/api/post-game-rubric` and rendered today as `#lm-rubric-components`
  (`web/js/panels/last_match.js:_setRubricComponents`).
- `web/css/tokens.css:1-218` already defines the full Hextech palette
  (`--prim-gold`, `--hextech-fill`, `--signal-good/warn/bad`), font tiers, and
  spacing. The card composes existing tokens, no new CSS system.
- `web/js/panels/player_gpi.js` (the 8-axis radar) is BUILT BUT NEVER MOUNTED
  (zero import sites in `main.js` or any view). The card's "View Profile" expand
  finally ships it.

Net-new is therefore narrow: a time-windowed GPI variant, win/streak/K-P
surfacing, a tag heuristic, the presentational card, and the two page reorgs.

## 3. Locked decisions

1. Subject: SELF only in v1. Data contract stays opponent-ready for a later
   scouting adapter (opponent data needs Match-V5 fan-out that ADR-006:45-50
   warns sits near the 100/2min rate wall - deferred).
2. Placement: Home (per mode tab, last 24h) + PGR (this match). Same component.
3. De-dup: absorb/refactor overlapping panels (tables in section 7).
4. Component: one presentational `renderPlayerSnapshot(el, model)` fed by
   per-context adapters. Same card on Home, PGR, and (v2) roster rows.
5. Baselines differ per context, by design:
   - Home card = GPI self-relative ("vs your own 24h norm"), from `player_gpi`.
   - PGR card = role-rubric ("vs your role's median"), from `post_game_rubric`.
   The presentational card is baseline-agnostic; each adapter supplies the
   already-computed values.
6. Surface = the rc-shell COMPANION (operator directive 2026-07-04), NOT the
   `:8888` dashboard. Later also the rc-shell OVERLAY - gated on getting the
   multi-lobby cards to load fast enough for the loading screen plus a shift+tab
   in-game display toggle. The presentational component + model contract are
   surface-agnostic; only the mount host changes. rc-shell must be located /
   confirmed in the codebase before wiring (recon claimed the Electron overlay
   was gone / all `:8888` - reconcile with rc-shell first).
7. "Compare" button dropped in v1 (needs opponent data). "View Profile" expands
   the existing GPI radar.
8. K-P computed from team kills, provenance-tagged `inferred` (the DB
   `matches.tracked_kp` column is frequently empty, per `player_gpi.py:20-22`).
   Win-rate and win-streak from the `participants.win` column.
9. ARAM's Vision/Objectives axes are low-signal by design (`player_gpi.py:44-47`)
   - shown but softened/flagged; per-mode bar tuning is v2.

## 4. Architecture

### 4.1 Presentational component

`renderPlayerSnapshot(el, model)` - pure render, no fetch, idempotent (stash a
signature, skip rebuild on unchanged payload - the pattern in
`duration_winrate.js:28-30`). Styled from `tokens.css`. HOST is the rc-shell
companion (path TBD pending an rc-shell locate); keep the module portable so the
same component mounts on the rc-shell overlay later. Written surface-agnostic:
it takes a model, it does not know its host.

### 4.2 Normalized model (the contract)

```
PlayerSnapshotModel = {
  header: {
    name, rank_tier, rank_lp|null, level,
    streak: { kind: "win"|"loss", n }|null,
    champion_id|null,               // most-played (Home) or played (PGR); splash
    result: "win"|"loss"|null       // PGR only
  },
  dial: { value: 0..100, band: "good"|"ok"|"poor", label },
  minis: [                          // KDA, Win-Rate, K-P
    { key, value, provenance: "source_truth"|"inferred" }
  ],
  bars: [                           // INCOME, COMBAT, OBJECTIVES, VISION
    { key, label, score: 0..100, provenance }
  ],
  tags: [ { label, tone: "strong"|"neutral"|"weak" } ],   // exactly 3
  profile_ref: { mode, window|match_id },   // drives View Profile -> GPI radar
  confidence: "high"|"low"|"insufficient",
  sample_n,
  empty: bool                       // true -> reserved slot + "-" sentinel
}
```

### 4.3 Adapters

- Home adapter: `GET /api/player-snapshot?mode=<tab>&hours=24` (new thin route,
  section 5). Assembles header (rank/level/streak) + minis + bars (GPI axes) +
  tags. One fetch.
- PGR adapter: composes the model client-side from the EXISTING
  `/api/last-match` + `/api/post-game-rubric?match_id=` responses. Rubric
  components -> bars, role-grade -> dial, last-match -> header/minis. No new
  route.

### 4.4 Bar composition

- Home (GPI self-relative):
  - INCOME = mean(farming, tempo)
  - COMBAT = aggression (KDA rides as a mini-dial)
  - OBJECTIVES = objectives axis
  - VISION = vision axis
- PGR (role-rubric): the rubric's 5 components fold into the 4 bars -
  INCOME = CS/min, COMBAT = mean(KDA, DPM), OBJECTIVES = Objectives,
  VISION = Vision.

### 4.5 Dial

- Home: GPI `overall` (the module's existing mean of all 8 axes,
  `player_gpi.py:330`; 0-100, 50 = your baseline).
- PGR: `post_game_rubric.compute_role_grade` total_score (0-100) + the letter
  grade it already returns (S+/S/A/B/C/D).
- Bands reuse RC's SHIPPED grade cutoffs (`post_game_rubric.py:390-402`, where a
  median game = 50 = B): Good >= 65 (A/S/S+), OK 35-64 (B/C), Poor < 35 (D). The
  same 0-100 cutoffs on both dials, so the Home self-relative dial and the PGR
  role-relative dial read consistently. No invented thresholds - these are the
  cutoffs the PGR letter grade already uses, calibrated to the standard "median
  game is a B" convention (`post_game_rubric.py:6-16`).

### 4.6 Tags (net-new heuristic, no LLM)

Three tags, in the third-party playstyle-tag style (reference examples are in the
non-repo research brief; the deferred research may extend the vocabulary).
Selection:
- GREEN (strong) = the highest of the 6 relative axes -> its high word.
- RED (weak) = the lowest of the 6 relative axes -> its low word.
- YELLOW (neutral) = the more pronounced SHAPE axis (versatility else
  consistency) -> a playstyle descriptor. Never a weakness: a one-trick reads low
  on versatility by choice (`player_gpi.py:64-67`), so shape axes are barred from
  the red slot.

Reuses the existing `weakest_axis` pick (`player_gpi.py:340-343`) plus a
symmetric strongest pick. Vocabulary (axis -> high word / low word):
- aggression  -> Aggressive       / Passive
- farming     -> Strong Farmer     / Weak Farm
- vision      -> Vision Control     / Visionless
- objectives  -> Objective Focused  / Objective Shy
- survival    -> Survivor           / Gank Prone
- tempo       -> Snowballer         / Slow Starter
- versatility -> Generalist         / One-Trick    (shape: neutral slot only)
- consistency -> Consistent         / Streaky      (shape: neutral slot only)

Tone drives color via the `tokens.css` signal palette (strong = `--signal-good`,
neutral = `--signal-warn`/gold, weak = `--signal-bad`).

## 5. Backend changes

### 5.1 `core/player_gpi.py`

- Add an optional time window: `compute_gpi(..., since_ts=None)` (or `hours=`)
  that filters the recent set to games with `game_creation_ts >= now - window`.
  The baseline stays the FULL history; the aggregate stays the existing
  mean-of-percentiles. Equal weight in v1 (recency-weighting = v2 knob).
- Add `p.win` to the `_fetch_operator_games` SELECT (`player_gpi.py:122-133`) ->
  per-game win -> compute win-streak + window win-rate.
- Add K-P: per-game kill-participation from team kills (sum of kills for the
  operator's team in that match via a subquery/aggregate over `participants`).
  Tag `inferred`.
- Expose a strongest-axis pick alongside `weakest_axis` for the tag row.

### 5.2 New route `dashboard/routes_player_snapshot.py` -> `/api/player-snapshot`

Params: `mode` (sr|aram|arena), `hours` (default 24). Calls `compute_gpi` with
the window, adds header (rank/level from the same LCU source `/api/home/summary`
uses at `main.js:3397-3407`; streak/win-rate from the win column), minis, bars,
tags. Returns the normalized model. Never raises; returns `empty: true` +
`confidence: "insufficient"` on thin/zero-game windows. Never surfaces raw API
errors (RC Error-Handling rule) - friendly degraded payload, raw error to logs.

## 6. Empty / degraded states

- Zero games in the 24h window, or below `MIN_GAMES` baseline: reserved slot,
  `-` sentinel, NO reflow (feedback: no reflow on data absence). Message like
  "No SR games in the last 24h."
- Low sample: render with a `confidence: "low"` hint (sample_n shown).
- Provenance: every mini/bar carries `source_truth` vs `inferred`; K-P is
  `inferred`, everything else `source_truth` (metric-provenance-tagging rule).

## 7. Page reorg (absorb / refactor / keep)

### 7.1 Home (`web/index.html:103-356`, `main.js:3036-3607`)

| Existing element | Overlaps | Action |
|---|---|---|
| `#home-hero-rank-tier` + WR | header.rank | ABSORB into card |
| `#home-hero-kda` (14D) | minis.kda | ABSORB (card = 24h value) |
| `#home-hero-headline` (momentum verdict) | tags | ABSORB into tag row |
| `#home-rank-wl` (last-20 W/L pips) | minis.winrate | REFACTOR - keep pips as a detail row under the card |
| `#home-hero-cs` (14D CS/min) | bars.income | REFACTOR - card's composite supersedes; keep sparkline as trajectory only |
| RECENT 3 cards | none (match rows) | KEEP |
| THIS WEEK champion chart | none (champion aggregate) | KEEP |
| TONIGHT'S PICK | none (pick coaching) | KEEP |

Note: existing Home trends are 14-day; the card is 24-hour by operator choice.
The 14D trend sparklines stay as trajectory (distinct from the card's 24h point
aggregate), not duplicated numbers.

### 7.2 PGR (`web/index.html:1633-1950`, `last_match.js`)

| Existing element | Overlaps | Action |
|---|---|---|
| `#lm-kda-text` + ratio | minis.kda | ABSORB into card |
| `#lm-hero-score` (0-100 lobby-relative) | dial | REFACTOR - suppress; its MVP signal survives on the roster MVP/SVP badges |
| `#lm-rubric-components` (5 role bars) | bars | REFACTOR - the card's 4 bars ARE these, folded in; suppress the standalone rows |
| `#lm-hero-role-grade` | dial/tags | REFACTOR - feeds the dial band + a tag |
| hero 8-stat grid | bars (raw inputs) | REFACTOR - keep as a collapsible "Detailed stats" row |
| `#lm-result-badge`, `#lm-grade-badge` | none (match outcome) | KEEP |
| `#lm-rank-compare` (tier averages) | none (vs-tier benchmark) | KEEP |
| roster `#lm-tc-*-list` | none (team table) | KEEP (v2: rows as mini-cards) |
| `#pgr-lane-compare-mount` | none (vs opponent) | KEEP |
| build-wpa / loadout / timeline / phases / quick-review | none (deep coaching) | KEEP; quick-review "chronic" may feed a weak tag |

## 8. Scope

v1 (this spec): presentational card + Home adapter (GPI 24h) + PGR adapter
(role-rubric) + View-Profile radar mount + the Home/PGR de-dup refactor + tags +
K-P + empty states + provenance + tests + the UI-fixture audit.

v2 (out of scope, noted so the contract accommodates them): the rc-shell OVERLAY
mount with multi-lobby loading-screen cards + a shift+tab in-game toggle, roster
rows as mini-cards, opponent-scouting adapter, per-mode ARAM bar tuning,
recency-weight knob, the Compare button.

Operator decision (2026-07-04): build Home + PGR TOGETHER in one plan (not
staged), since they share the presentational component + model contract.

## 9. Testing plan (TDD-first, RC rule)

Write failing tests first, then implement. Tier-1/2 (core module + web routes;
NOT an engine/ENGINE_VERSION change, so not the full DS suite).

- `player_gpi` time-window filter: games outside the window excluded, baseline
  still full history.
- win-streak / win-rate computation from the win column.
- K-P from team kills (and the `inferred` tag).
- tag derivation: strong/mid/weak selection + tone mapping.
- `/api/player-snapshot` contract: shape, empty state, degraded payload, no raw
  error leakage.
- PGR adapter mapping: rubric components -> 4 bars, role-grade -> dial.

## 10. UI audit

The new panel + Home/PGR reorg are UI changes: run the 5-phase visual-hierarchy
/ fixture audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) BEFORE
the commit, not after (RC UI Fixture Ritual). Resolve every MUST-FIX in the same
slice.

## 11. Frozen-file check

None of the touched files (`player_gpi.py`, the new route, `player_snapshot.js`,
`index.html`, `main.js`) are on the CLAUDE.md frozen list. No frozen file is
modified.

## 12. Decisions + open items

Resolved at operator review (2026-07-04):
- Dial bands reuse the shipped grade cutoffs (65 / 35 -> Good / OK / Poor; 4.5).
- Build Home + PGR together (8).
- Tag vocabulary set in 4.6 (third-party tag style; deferred research may extend it).
- Surface = rc-shell companion, later rc-shell overlay (3.6).

Open (a plan task, not a design blocker):
1. rc-shell: locate the rc-shell companion (and overlay) in the codebase and
   confirm the mount host + asset/render pipeline. Recon claimed the Electron
   overlay was gone / all `:8888`; the operator says the surface is rc-shell, and
   MEMORY confirms live overlay work through 2026-07-01. This is PLAN TASK #1 -
   locate rc-shell via `docs/OVERLAY_BUILD_MASTER_PLAN.md` / `docs/RC2_PLAN.md`
   before wiring. Does not change the data design, only the host.
