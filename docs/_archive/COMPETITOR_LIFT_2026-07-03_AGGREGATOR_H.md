# Competitor Lift - Aggregator H (Section-7b deep-dive: early/late power curves)

Date: 2026-07-03. Target: **Aggregator H** (aggregator H), specifically
its EARLY-vs-LATE champion power presentation - the "Winrate / Game Duration"
graph family on every champion stats page. Single-target teardown in the
2026-06-21 Aggregator B format: WHAT / HOW / HAVE / WHERE / EFFORT+RISK / LIFT per
finding, then a NOW / FUTURE / CLOSED triage.

**Sourcing caveat (honest):** aggregator H sits behind a Cloudflare
managed challenge - direct WebFetch returns 403 and curl with a browser UA
returns the challenge shell. Firsthand capture came from the Wayback Machine
snapshot of `/champions/stats/nasus` (2026-02-20, HTTP 200, 341 KB full HTML)
plus `/champions/winrates-by-xp` (2026-03-02). All data shapes below are
extracted from the real inline chart payloads in those pages, not inferred.
Patch-era numbers are from that snapshot; the SHAPES are what matter.

**Anchor fact (captured):** Aggregator H does zero client-side aggregation.
Every graph is a server-rendered inline Flot call - literal
`$.plot($("#graphDDn"), [{data: [[x,y],...]}])` arrays baked into script tags
in the HTML. No XHR, no JSON API, no methodology page. The site's power-curve
story is told entirely by pre-aggregated ranked-match win rates re-bucketed
along different x-axes (duration, K-D at a timestamp, games played). RC
already owns the precompute-then-render-flat pattern (DS engine + 5-min route
caches + the local 2954-match rewind SQLite), so the liftable value is
presentation and one missing aggregation, not architecture.

**Captured graph inventory** (champion stats page, in page order; ids
graphDD8-graphDD15, all Flot line charts with filled area):

| Graph title (exact) | x-axis | y-axis | Sample data (Nasus, captured) |
|---|---|---|---|
| Gold / Game duration | minute marks 0,2,3,4,5,7,10,15,20,25,30 | avg cumulative gold | [[0,500],[10,3288.6],[30,12370.5]] |
| Minions / Game duration | same marks | avg cumulative CS | [[10,63.1],[30,207.3]] |
| Kills + Assists / Game duration | same marks | avg cumulative K+A | [[10,1.47],[30,10.64]] |
| Deaths / Game duration | same marks | avg cumulative deaths | [[10,1.16],[30,5.41]] |
| Winrate / Game Duration | 5-min buckets 10..50 | win % of games ending in that bucket | [[10,50.19],[15,53.14],[20,49.79],[25,50.6],[30,50.82],[35,50.54],[40,51.44],[45,54.74],[50,68.89]] |
| Winrate / Ranked Games Played | games-played buckets 0..80 | win % | [[0,51.22],[10,53.99],[80,55.77]] |
| Winrate / (Kills - deaths) @10 min | K-D integer -5..+5 | win % | [[-5,26.02],[0,52.89],[5,76.83]] |
| Winrate / (Kills - deaths) @20 min | K-D integer -10..+10 | win % | [[-10,20.34],[0,51.96],[10,76.36]] |

Notable NON-finding: the page carries NO explicit "Early game" / "Late game"
tag text anywhere (grep of the full 341 KB HTML). The early/late identity is
communicated purely by the SLOPE of Winrate / Game Duration - Nasus reading
as a late-game champion because the curve climbs from ~50% to 68.9% at the
50-minute bucket. The reader does the inference; the site never labels it.
Their separate "Win Stats" page re-slices the same data by three coarse
duration categories (<25 min, 25-35 min, >35 min).

---

## Findings (6-point depth checklist each)

### F1 - "Winrate / Game Duration": the per-champion early/late curve
- **WHAT:** the headline power-curve presentation. One line per champion: win
  rate of that champion's games as a function of the minute the game ENDED,
  in 5-minute buckets from 10 to 50. Upslope = scales / late-game champion;
  downslope = early / snowball champion. This is the entire "power spike"
  story Aggregator H tells - correlational, per-champion, one glance.
- **HOW:** site-wide ranked-match aggregate keyed (champion, patch-window,
  region/rank filter), bucketed by gameDuration into 5-min bins; win % per
  bin baked as a literal Flot array into the page (`$.plot`, y-axis
  `min:0` with a `%` tick formatter, green fill). No smoothing visible; thin
  tail buckets (50 min) swing hard (68.89%).
- **HAVE:** PARTIAL - RC computes exactly this curve over the operator's OWN
  corpus but never per-champion in the UI. `core/duration_winrate.py:47-54`
  defines the buckets (<15m, 15-20m, 20-25m, 25-30m, 30-35m, 35m+),
  `MIN_BUCKET_N = 5` sample gate at `core/duration_winrate.py:43`, and the
  compute already accepts an optional `champion` filter
  (`core/duration_winrate.py:74-77`, filter applied at line 100-102). The
  route exposes it: `dashboard/routes_duration_winrate.py:9` documents
  `GET /api/duration-winrate[?mode=..][&champion=64]` and parses it at
  lines 63-69 (route registered at lines 129-131). But the panel never sends
  it - `web/js/panels/duration_winrate.js:41-44` builds the URL with mode
  ONLY, so the Game Length tab (mount `bi-duration-mount`,
  `duration_winrate.js:22`; tab dispatch `web/js/panels/build_insights.js:519`)
  always shows the all-champions curve.
- **WHERE:** presentation-only lift inside the existing Game Length tab:
  an "All champs | <locked/selected champ>" toggle in
  `web/js/panels/duration_winrate.js` that appends the ALREADY-LIVE
  `&champion=<id>` param (cache key extends mode -> mode+champ). Zero
  backend work; `MIN_BUCKET_N` already renders thin buckets as a muted "-".
- **EFFORT+RISK:** LOW. No new data, no Riot/Claude call, no schema lift, no
  engine math; the backend param is tested and sample-gated. Panel JS only
  (asset-hash auto-reload per ADR-008, no RC restart). Risk = thin
  per-champion buckets on a personal corpus - already handled by the
  existing null-winrate gate.
- **LIFT VERDICT: HIGH-lift LOW-risk -> NOW.**

### F2 - Slope-to-identity: a computed early/late tendency readout
- **WHAT:** Aggregator H makes the reader infer "late-game champ" from the
  curve slope. The lift is doing that inference FOR the operator: a one-word
  tendency chip ("early-leaning" / "flat" / "late-leaning") computed from
  the same bucket payload.
- **HOW (theirs):** none - they render the raw line and stop. The chip is
  RC going one step further on identical data.
- **HAVE:** the manual-read instruction already ships as caption prose -
  `web/js/panels/duration_winrate.js:82-86` literally tells the operator
  "Bars sloping down ... early-game / snowball tendency; sloping up ...
  scaling / late-game tendency". No code computes the slope.
- **WHERE:** `web/js/panels/duration_winrate.js` - derive from the fetched
  `buckets[]` (n-weighted first-half vs second-half winrate delta over
  non-null buckets; render a chip next to the mode bar). Pure client-side
  arithmetic over the existing `/api/duration-winrate` response. If a
  server-side home is preferred later, `core/smoothed_rates.py:47-79`
  (`laplace_rate` / `shrink` / `blend`) is the sanctioned primitive for
  stabilizing the halves before differencing.
- **EFFORT+RISK:** LOW. Presentation-only over an existing payload;
  testable in the panel's .mjs test style; degrade to no chip when too few
  non-null buckets. Must stay descriptive (a tendency label, not a
  win-probability claim).
- **LIFT VERDICT: HIGH-lift LOW-risk -> NOW (same slice as F1).**

### F3 - Snowball elasticity: Winrate / (K-D) @10 and @20
- **WHAT:** two per-champion curves: win rate as a function of the
  champion's kills-minus-deaths at minute 10 and minute 20. The captured
  Nasus shape (26% at -5 up to ~77% at +5 by minute 10) quantifies lead
  conversion: a steep curve = snowball-dependent, a flat curve =
  comeback-capable. This is the sharpest analytical idea on the page - it
  measures HOW MUCH the early game matters per champion, not just when.
- **HOW:** per-game tuples (K-D at timestamp T, won?) from timeline kill
  events, aggregated site-wide per champion into integer K-D bins; served as
  the same inline Flot arrays (linked out to their /champions/
  snowballing-stats ranking page).
- **HAVE:** NO computed equivalent, but the raw data is fully local. Live
  schema (probed this session): `data/rewind_history.db` has 2954 matches
  and a `timeline_events` table carrying `event_type, timestamp_ms,
  killer_id, victim_id` - K-D at any minute is a filtered count. Nothing in
  `core/` aggregates it: the only "snowball" hit is a coach prose string
  (`core/lead_projection.py:107`); `core/benchmarks.py:15` benchmarks
  cs_at_10-style stats but not WR-conditioned-on-lead.
- **WHERE:** new aggregator `core/` module mirroring the
  `core/duration_winrate.py` shape (read-only, conn-injection seam for
  clean-checkout tests, MIN_BUCKET_N gating) computing per-mode (and
  optional per-champion) WR by K-D@10 bins over the tracked player; shrink
  thin bins with `core/smoothed_rates.py:47` `laplace_rate`. New thin route
  (mirror `dashboard/routes_duration_winrate.py`) + a Build Insights tab or
  a row in the Game Length tab.
- **EFFORT+RISK:** MED. New compute path over a gitignored DB (fixture
  discipline per the clean-checkout-probe memory), new route + panel + the
  per-page UI-audit ritual. Personal corpus is thin per champion - bins
  must be coarse (<=-2, -1, 0, +1, >=+2) and n-gated. No external
  dependency; descriptive only, never fed into DS rank (DS default rank
  stays pure simulation).
- **LIFT VERDICT: HIGH value, new compute -> FUTURE (BACKLOG). Top FUTURE
  candidate.**

### F4 - Stat-vs-duration point curves (Gold / Minions / K+A / Deaths)
- **WHAT:** four small charts of average cumulative gold / CS / K+A /
  deaths at fixed minute marks (0,2,3,4,5,7,10,15,20,25,30) - the growth
  curves under the winrate curve.
- **HOW:** averaged Match-V5 timeline participant frames at those
  timestamps, site-wide, inline Flot as above.
- **HAVE:** YES and richer for gold/CS - `core/perf_curve.py:1-9` computes
  the per-minute cumulative gold or CS curve over the operator's corpus
  SPLIT WIN VS LOSS (Aggregator H does not split), served by
  `dashboard/routes_perf_curve.py:10` (`/api/perf-curve?metric=gold|cs`)
  and rendered by `web/js/panels/perf_curve.js`. Kills/deaths-per-minute is
  deliberately absent: frames lack kill counts and `core/perf_curve.py:20-22`
  documents why the damage field was excluded; a K/D-per-minute variant
  would need `timeline_events` counting (superset of F3's compute).
- **WHERE:** n/a for gold/CS (shipped). A deaths-per-minute metric could
  ride F3's event aggregation later if wanted.
- **EFFORT+RISK:** marginal gain; the win/loss split RC already renders is
  strictly more instructive than Aggregator H' unsplit average.
- **LIFT VERDICT: CLOSED (gold/CS shipped richer); K/D variant folds into
  F3 if ever built.**

### F5 - Mastery curve: "Winrate / Ranked Games Played"
- **WHAT:** win rate vs how many ranked games the player has on the
  champion (buckets 0..80+; captured Nasus: 51.2% at 0 games rising to
  ~55% by 30). Site-wide it answers "how hard is this champ to learn";
  their dedicated page is titled "Winrate by experience".
- **HOW:** cross-player aggregate keyed (champion, games-played-so-far
  bucket) - inherently multi-player data.
- **HAVE:** NO, and the global basis is out of scope for RC (single-player
  tool, no redistributable global meta - same stance recorded in the Aggregator B
  teardown F3). The PERSONAL analog is computable: order the operator's
  matches on a champion by `game_creation_ts` (matches table:
  tracked_champion_id, tracked_win) and bucket by cumulative game index -
  "your first 10 Nasus games vs your last 10" - a learning-curve readout.
- **WHERE:** small aggregator in the same `core/duration_winrate.py` family
  (matches table only, no joins) + a row in the Game Length tab.
- **EFFORT+RISK:** MED-LOW compute, but per-champion personal samples are
  very thin (most champs < 20 games); the readout risks being noise
  presented as signal even with shrink.
- **LIFT VERDICT: MED -> FUTURE (only if a champ-games histogram shows
  enough depth to be honest).**

### F6 - Delivery pattern: server-baked inline chart data, zero client math
- **WHAT/HOW:** every chart is a literal data array in an inline script tag;
  aggregation happens offline; the page is cacheable flat HTML. Their donut
  KPIs (Popularity 5.8% / Winrate 50.8% / BanRate 4.5%) follow the same
  pattern.
- **HAVE:** RC owns the equivalent discipline already - precomputed DS
  tables, 5-min in-process route caches (`dashboard/routes_duration_winrate.py:39`),
  sig-dedup renders (`web/js/panels/duration_winrate.js:105-107`), ADR-008
  asset-hash reload. Nothing to copy.
- **LIFT VERDICT: CLOSED (pattern parity).**

### F7 - Relation to RC's model-based spike curve (kept-separate check)
- **WHAT:** Aggregator H' early/late story is CORRELATIONAL (win rate by
  duration). RC's existing spike surface is CAUSAL - a simulated power
  curve.
- **HAVE:** `dashboard/routes_spike_curve.py:2-53` computes per-minute
  (0..40) team power from DS archetype scorers (level ramp at line 214-216,
  item checkpoints at 99-100, 70%-of-max peak semantic at 362-370), rendered
  by `web/js/panels/spike_curve.js:1-17`; discrete level/item spike markers
  live in `agents/daemon_slayer/spike_markers.py:1-14`. The two bases are
  complementary: sim says "when your build comes online", the personal
  duration curve says "when you actually win".
- **WHERE:** no merge. Per the standing rule, DS default rank stays pure
  simulation - the duration-winrate surfaces stay descriptive Build
  Insights panels and must not feed rank_items or the spike curve math.
- **LIFT VERDICT: CLOSED (boundary note, not a work item).**

---

## Triage

| Finding | Verdict | Disposition |
|---|---|---|
| F1 per-champion duration-winrate toggle | HIGH / LOW-risk / presentation-only | **NOW** - surface the live `&champion=` param in the Game Length tab |
| F2 computed early/late tendency chip | HIGH / LOW-risk / presentation-only | **NOW** - same slice as F1 (client arithmetic over the existing payload) |
| F3 snowball elasticity (WR by K-D@10/@20) | HIGH / new compute over local timeline_events | FUTURE (BACKLOG) - top candidate |
| F5 personal learning curve (WR by nth game) | MED / thin samples | FUTURE (sample-depth gated) |
| F4 stat-vs-duration curves | shipped richer (win/loss split perf_curve) | CLOSED |
| F6 inline-flat delivery pattern | already RC discipline | CLOSED |
| F7 correlational-vs-sim merge | boundary: DS rank stays pure sim | CLOSED (do not merge) |
| Global cross-player curve basis | single-player tool, no redistributable meta | CLOSED (deliberate non-goal) |

NOW scope note: F1+F2 together are one Tier-1 panel slice - JS-only edits to
`web/js/panels/duration_winrate.js` (+ a champ-id feed from the existing
build-insights context), .mjs panel tests, 5-phase UI audit before commit,
no restart (ADR-008). No new dependency, no engine math, no schema lift.

Lift policy honored: no vendored code, shapes re-implemented from firsthand
captured data, competitor name confined to this docs file.
