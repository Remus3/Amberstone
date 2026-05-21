# ADR-009: Replay events sidecar over Match-V5 timeline, league_record GPLv3 cleanroom

**Date:** 2026-05-20
**Status:** Accepted

## Context

The s220 PGR S5 reframe adds an event-timeline ribbon to the Replay
view (per-frame scrubber already shipped). Three architecture options
were considered for the event source:

1. **`.rofl` replay file parsing.** Investigated through `fraxiinus/roflxd`
   (the maintained .ROFL parser family). A parsed `.rofl` exposes only
   end-of-game aggregate `PlayerStatistics[]` - a strict subset of
   what RC's existing Match-V5 SQLite already carries. The in-game
   packet stream (frame positions, ability casts, event stream a
   replay-review UI would actually want) is Riot-obfuscated and
   unparseable on the current patch. **Dead end** - confirmed
   2026-05-17, recorded in `BACKLOG.md` Speculative section, do not
   re-pitch.

2. **Custom protocol bridging League's in-process replay engine.**
   Out of scope (would require unsupported reverse engineering of a
   live process the operator runs for their own play, not safe).

3. **Match-V5 timeline events from `data/rewind_history.db`.** Already
   ingested by the rewind pipeline; `timeline_events` table has
   ~1M rows across the operator's match history (CHAMPION_KILL,
   BUILDING_KILL, ELITE_MONSTER_KILL, ITEM_PURCHASED, SKILL_LEVEL_UP,
   WARD_PLACED, TURRET_PLATE_DESTROYED, and 8+ more types).

The reference architecture for pairing an event sidecar with a real
replay surface comes from `league_record` (GPLv3) - a community
project that does local OBS *video* capture keyed to LCU game-
lifecycle events + a structured event-timeline sidecar JSON. The
methodology is the right shape (sidecar of typed events + optional
video overlay); the implementation is GPLv3 and must NOT be vendored
into this repo.

## Decision

**Match-V5 timeline events from `data/rewind_history.db.timeline_events`
are the canonical event source for the Replay view.** The new endpoint
`GET /api/replay/events?match_id=<id>[&include=items,skills,wards,all]`
serves the chronological ribbon. Server-side filtering defaults to
the strong-event subset (CHAMPION_KILL + BUILDING_KILL +
ELITE_MONSTER_KILL + TURRET_PLATE_DESTROYED) so the default ribbon for
a 35-minute SR match returns ~80-160 events instead of the ~3k events
the full set would return. The opt-in flags widen the set when the
operator wants item or skill detail.

`league_record` is treated as a **cleanroom methodology reference**:

- The sidecar shape (typed events with clock + actor + team) IS what
  this endpoint implements, but it is also the natural shape of
  Match-V5 timeline data - no implementation borrowed from
  league_record source.
- Do NOT vendor `league_record` source, do NOT depend on its binaries,
  do NOT ship it. The GPLv3 license is incompatible with this repo's
  license posture and the operator's distribution intent.
- A future operator-gated slice MAY add local OBS video capture keyed
  to LCU game-lifecycle to layer a real replay video behind this
  event ribbon. That slice is its own ADR + its own dependency
  decision.

## Consequences

**Good:**
- Zero new dependency. `timeline_events` is already populated by the
  rewind pipeline; this endpoint is a thin read.
- Sub-millisecond cold response (verified live on `NA1_5439050124`:
  100 events, 1ms cold).
- Server-side filter keeps payloads small (~5-15 KB per match default,
  ~80-120 KB with `include=items,skills,wards`).
- Sidecar shape forward-compatible with a future video overlay - the
  clock_s on each event is the same axis a video timestamp would key
  off.

**Trade-off:**
- No in-game position stream beyond `kill_pos_x/y` on `CHAMPION_KILL`.
  The .rofl dead-end means RC cannot show champion paths between
  events, only the discrete events themselves.
- Match-V5 timeline is unavailable for ARAM (`gameMode=ARAM`) and
  ARAM Mayhem (`gameMode=KIWI`) - Riot does not publish timelines
  for those modes. The Replay view will render the per-frame
  snapshots but the events ribbon stays empty (fail-soft, ok=true
  count=0).

**Watch for:**
- Any future contributor importing or referencing `league_record`
  source code. The CLAUDE.md "Don't re-litigate" digest should call
  this out if `league_record` ever lands on the research list again.
- Riot tightening the Match-V5 timeline access policy (currently
  Personal-tier permitted per ADR-006). If revoked, the events
  ribbon falls back to "no data" - the rewind pipeline already
  caches results so historical matches keep working.
