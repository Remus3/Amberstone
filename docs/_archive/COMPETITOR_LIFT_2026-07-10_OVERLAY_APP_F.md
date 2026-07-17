# Competitor Lift Teardown - Overlay App F (overlay app F)

Date: 2026-07-10 - Section 7b deep-dive - gemini-loop DIRECTOR REFILL R100.
Method: one heavyweight research subagent (live-site + web research) + an
orchestrator verify-premises pass against the live RC repo. 6-point depth
checklist (WHAT / HOW / HAVE / WHERE / EFFORT+RISK / LIFT) applied per feature.

## Executive summary

Overlay App F is a live pre-game and in-game SCOUTING companion. Its whole value
chain rests on a Riot PRODUCTION spectator-v4 key plus a server-side stats
warehouse (arbitrary-summoner live-game lookup, every player's ranked history).
Against RC's already-built and already-queued work it is ~90 percent DUPLICATE:

- The headline mechanic (type any summoner -> scout their live game with all 10
  players) is architecturally CLOSED for RC (needs a production key + user base;
  ADR-006 forbids it; ranked champ-select hides enemy identity until the `:2999`
  loading screen).
- The pre-game per-player card (rank / LP / recent win-rate / mastery / mains /
  recent W-L streak) is already BUILT in RC's FU02 team-context fan-out.
- Premade detection, playstyle-tendency labels, and self-tilt/session hygiene are
  already QUEUED under the R81 (2026-07-05) scouting fold-in.
- Lane-matchup difficulty, power-spike stoplight, and objective timers are already
  BUILT or queued under R89 / R81 / event_callouts.

VERIFY-PREMISES CORRECTION (the decisive finding): the research pass nominated one
"ship-in-run" candidate - render the fetched-but-unrendered `w_l_streak_7` as W/L
form dots. That premise is REFUTED live. `web/js/panels/team_context.js:126-133`
ALREADY renders the streak (as text "4W 3L" with a "Last 7 games" tooltip, for
both ally and enemy cards). The field is computed (`core/riot_api.py:670`), plumbed
(`dashboard/routes_team_context.py:238`), AND rendered. The only residual delta is
a cosmetic text-to-dots restyle plus a tilt hint - MED/LOW lift, overlapping R81's
snapshot-card lane, and un-provable this cycle (no live game -> no overlay visual).

Result: NO in-run code ship. This is an honest research-only cycle in the R85 /
R94 / R98 tradition (verify-before-build refuted the pick). Two genuinely-distinct
residuals go to BACKLOG FUTURE; everything else maps to an existing home.

## The architectural wall (data-source reality)

Overlay App F reads Riot spectator-v4 `/lol/spectator/v4/active-games/by-summoner`
behind a PRODUCTION key, joined to its own scraped stats warehouse. RC runs the
PERSONAL dev key (ADR-006): 20/s + 100/2min, no arbitrary-player warehouse, and
ranked champ-select hides enemy identity until the `:2999` loading screen. RC can
scout only its OWN lobby roster, at game start, not "any summoner on demand." This
is a CLOSED anchor (BACKLOG "CLOSED anchors"; do not re-pitch).

## Feature-by-feature teardown

| # | Overlay App F feature | HAVE in RC (cite) | Verdict |
|---|---|---|---|
| 1 | Live-game search by arbitrary summoner | No, and cannot - RC scouts own roster only (`dashboard/routes_scouting.py`) | CLOSED - production key + user base = ADR-006 violation |
| 2 | Pre-game card: rank / LP / WR / mastery / mains | BUILT - FU02 fan-out (`dashboard/routes_team_context.py:200-239`, `core/riot_api.py:611-670`, `dashboard/_party_mains.py`) | DUPLICATE (FU02) - no action |
| 3 | Recent W-L streak as tilt indicator | BUILT - computed `core/riot_api.py:670`, plumbed `routes_team_context.py:238`, RENDERED `web/js/panels/team_context.js:126-133` | DUPLICATE (FU02) - ship premise REFUTED; residual = cosmetic dots + tilt hint (FUTURE) |
| 4 | Player playstyle / tendency tags | Queued - R81 "playstyle-inference deterministic labels" | DUPLICATE (R81) - no action |
| 5 | Premade / duo detection | Queued - R81 "offline premade detection via rewind_history.db match-intersection" | DUPLICATE (R81) - no action |
| 6 | In-game matchup review (lane difficulty, spikes) | BUILT/queued - `web/js/panels/ds_matchup.js` verdict chip; lane-WR list R89 FUTURE; power spike stoplight R81 SHIPPED (`/api/spike-curve` phases) | DUPLICATE (R89/R81) - no action |
| 7 | In-game objective / jungle timers | BUILT - `core/event_callouts.py` + OQ16 `web/js/panels/objective_gauges.js` | DUPLICATE - no action |
| 8 | Manual click-to-track enemy summoner-spell / ult cooldown | No - no such tracker (grep clean); RC marks live per-player cooldowns DATA-BLOCKED, but that closure assumed a data FEED; Overlay App F sidesteps it with a manual click + static base CD | GENUINELY-NEW mechanic -> BACKLOG FUTURE (MED-lift interactive overlay, low solo-player fit) |
| 9 | Champion tier list + one-click build/rune import | DS owns builds/runes deterministically; `lcu/lcu_rune_writer.py` writes runes; a global ladder tier list is a deliberate non-goal (per-champ simulation, single-player) | DUPLICATE (builds) / out-of-scope (tier list) - no action |
| 10 | Post-game review (pacing, damage, KP, vision) | BUILT - PGR reframe + `core/perf_curve.py` (over-time curves, win/loss split) | DUPLICATE - no action (PGR S2-S5 is the tracked lane) |
| 11 | "Prepare for Battle" pick-a-gameplan selector | BUILT - R81 strength stoplight + `core/objective_playbook.py` / `core/macro_context.py` | DUPLICATE (marginal) - no action |

## ACT recommendation

Overlay App F is mostly-duplicate. Ten of eleven features map cleanly onto BUILT
(FU02, event_callouts, ds_matchup, perf_curve) or already-queued (R81
premade/playstyle/tilt, R89 lane-matchup) RC work, or onto CLOSED anchors
(production-key live search, curated-prose tips, global tier list). No in-run ship
is warranted - the single nominated candidate was refuted live.

BACKLOG FUTURE (2 genuinely-distinct residuals, do NOT build blind):

- F1 - Manual click-to-track enemy summoner-spell / ult cooldown overlay (feature
  8). The one distinct mechanic. A pure client-side UI state machine (click on a
  burn -> tick down the static base CD), no data feed. MED-lift: a new Electron
  overlay widget + in-game input plumbing (`web/js/panels/*` + `hotkey_listener.py`;
  globalShortcut is dead under League per memory). Low fit for a solo player mid
  fight, outside the deterministic-precompute lane. Log-only.
- F2 - Recent-form W-L "dots" restyle + tilt hint (feature 3). Cosmetic upgrade of
  the already-rendered `team_context.js:126-133` streak text to a green/red pip
  strip, plus a soft "on a skid" flag. LOW lift, but: overlaps R81's snapshot-card
  lane, needs Laplace-shrink discipline on a 7-game sample before any tilt claim
  (per `core/smoothed_rates.py`; do not assert tilt on tiny samples), and its whole
  value is visual so it needs a live-game overlay capture to validate. Fold into
  the R81 snapshot-card slice when that lands live, not as a standalone blind ship.

## Loop-health note (for the director)

The live-scouting / live-overlay competitor CATEGORY is now DRAINED. Overlay App F,
its pre-game card, its scouting, its overlay tips, and its timers are all covered
by FU02 (built) + R81 (2026-07-05 scouting + overlay fold-in) + R89 (Aggregator C,
2026-07-10) + event_callouts. The R100 directive's NOT-A-DUPLICATE check compared
only against R89 and missed R81, which is where ~90 percent of Overlay App F already
lives. Future competitor picks should either target a DIFFERENT category (draft
theory, replay/VOD analysis, economy/wave tooling) or accept that the competitor
well for RC's product shape is running dry - the meatier open lanes are the
DS-sweep Meraki refute rotation and the Haiku-to-ZERO Lane A/E precompute programs.

Third-party names are retained in THIS research artifact only; RC repo code carries
none (per the name-scrub policy). Plain ASCII throughout.
