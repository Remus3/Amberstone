# Amberstone

A local, real-time coaching companion for League of Legends and Teamfight Tactics.

[![CI](https://github.com/Remus3/Amberstone/actions/workflows/ci.yml/badge.svg)](https://github.com/Remus3/Amberstone/actions/workflows/ci.yml) [![Docs guards](https://github.com/Remus3/Amberstone/actions/workflows/docs-guards.yml/badge.svg)](https://github.com/Remus3/Amberstone/actions/workflows/docs-guards.yml)

It watches the game you are actually in, does the item and damage math locally,
and turns that into short, situation-specific advice on a dashboard and an
in-game overlay.

Personal project, private repo, not packaged for general use. It is readable as
a reference, not installable as a product - see [Limitations](#limitations).

## Contents

| | |
|---|---|
| [What makes it different](#what-makes-it-different) | why the math runs before the model, and what that buys |
| [What it does](#what-it-does) | the features, and the modes they run in |
| [How it works](#how-it-works) | the pipeline in one diagram, plus the port map |
| [Daemon Slayer build engine](#daemon-slayer-build-engine) | the technical centerpiece, and the part most worth reading |
| [Limitations](#limitations) | what it cannot do, stated before you read further |
| [Where it runs](#where-it-runs) | the single-machine deployment |
| [Status](#status) | what is finished and where open work is tracked |
| [How the work gets done](#how-the-work-gets-done) | the headless lanes that maintain it, and why one item per cycle |
| [Data sources and credits](#data-sources-and-credits) | the public projects the game data comes from |
| [Documentation map](#documentation-map) | every other document, and who each is written for |

---

## What makes it different

Most build advice is a popularity contest: an item is recommended because many
players bought it in many games. This project takes the other route.

- **The math runs first, locally.** A build engine scores champion x item x
  target combinations from real game numbers - damage per second, effective HP,
  ability burst, healing throughput - and the AI coach reasons *over that
  output* rather than guessing. An item suggestion reflects your actual matchup,
  not a tier list.
- **No win-rate scraping.** Nothing here aggregates other players' win rates.
  Recommendations come from computed quantities, which is also why the engine
  can answer for matchups too rare to have a sample size.
- **Your own history, not a tracker's.** Matches land in a local SQLite archive
  with full timeline data, so champion-select advice reads history you own.
- **Offline at request time.** The engine makes no network calls and has no
  per-query cost, so it can be asked thousands of questions per game.

---

## What it does

- Keeps a running picture of the match from Riot's local data feed - gold,
  level, KDA, items on both teams - polled about once a second, and turns it
  into situation-specific tips.
- Reads the screen with OCR first; an AI vision model is escalated only for what
  OCR misses.
- Suggests picks in champion select from your own match history filtered by the
  enemy team's composition; ban and counter hints come from the engine's
  deterministic 1v1 math.
- Writes runes into the client automatically.

Modes: Summoner's Rift, ARAM (including its event variants), Arena, and
Teamfight Tactics. A fifth path covers Riot's rotating game modes - URF, One for
All, Nexus Blitz and their siblings - which is wired and enabled but only
exercised when Riot actually rotates one of them in.

---

## How it works

A Python service polls the game client's local data feed about once a second.
The build engine answers first with local math, and its output is injected into
every AI coaching call; the coach fires on a cadence - about every 8 seconds, or
immediately on kill and health swings. Results render on a locally served web
dashboard and an in-game overlay. A vision server sits to the side, turning
screen captures into data through tiered OCR with AI-vision escalation.

```
game client
    |
    v
local reader (polls about once a second)
    |
    v
build engine math first -> AI coach reasons over the math's output
    |
    v
dashboard + in-game overlay

vision server on the side: screen capture -> OCR -> AI vision only on a miss
```

| Port | Service |
|---|---|
| :8888 | Web dashboard (HTTPS) |
| :8889 | Vision server |
| :8890 | Agents supervisor (proxied by the dashboard) |
| :8891 | Agents WS relay |
| :8895 | Mission Control (its own process, so a dashboard restart cannot take the control plane with it) |
| :8860 | Daemon Slayer build engine |
| :8861 | Daemon Slayer match-history MCP server |
| :2999 | Riot Live Client API (the game client's own feed) |

---

## Daemon Slayer build engine

The technical centerpiece, and the part most worth reading. It models the full
champion roster and every item the shop actually offers in the modes it scores -
including the mode-specific pools - and picks one of seven scoring modes
automatically from the champion's role:

| Role | What it optimizes |
|---|---|
| Carry (ADC) | Auto-attack damage per second |
| Tank | Effective HP against the enemy team's damage mix |
| Bruiser | A per-champion blend of damage and durability |
| Mage | Ability damage at the champion's cast cadence |
| Assassin | Total burst inside a combo window |
| Enchanter | Healing and shielding throughput |
| On-hit (AP) | Ability damage plus on-hit auto damage combined into one score |

Champions do not fit one formula, so a registry of per-champion mechanic
overrides handles the unusual kits - form swaps, recast windows, resource bars,
revives - and covers most of the roster.

The engine's live counts are reported by its own `/health` endpoint rather than
restated here, so they cannot go stale in prose.

It also ships as a self-contained package for external review, with its own
documentation and test suite: [`Share/README.md`](./Share/README.md). Depth
reference: [`docs/DAEMON_SLAYER.md`](./docs/DAEMON_SLAYER.md).

---

## Limitations

Worth stating plainly before you read further:

- **Windows only, one machine.** The game, the coach, the dashboard and the
  overlay all run on the same PC. There is no hosted version and no installer.
- **Bring your own API key.** The AI coaching and vision paths call a
  third-party model API; without a key those paths stay off and the local math
  still works.
- **Riot's API limits what is knowable.** Some event modes return no match
  history through the public API, and some in-game state has no API at all -
  which is exactly why the vision path exists.
- **Not affiliated with Riot Games.** See the disclaimer below.

## Where it runs

One Windows PC runs the game and the coach together. A Python service runs under
a supervisor and serves the dashboard over local HTTPS to a browser, plus an
Electron overlay for in-game display. Operational procedures live in
[`docs/OPERATIONS.md`](./docs/OPERATIONS.md).

## Status

The coaching loop is functionally complete across the modes it covers; the build
engine and champion-select advice cover the League modes, and TFT uses the
vision and coaching paths. Open work is tracked in
[`ROADMAP.md`](./ROADMAP.md), with the longer-horizon queue in
[`BACKLOG.md`](./BACKLOG.md).

---

## How the work gets done

Maintenance runs as mutually exclusive headless lanes - one holder at a time,
each in its own git worktree, so nothing edits the checkout a person is reading.
A lane is a single `claude -p` worker fed a tracked prompt document, and Mission
Control fires them and shows their state.

Two of the lanes are a pair. Research files work items that carry an id, cited
`file:line` evidence and an acceptance check; the queue lane drains them one
item per cycle. The worker does exactly one item and exits, and a driver
re-fires it - so a crash loses one item rather than a night's work, and each
item arrives as its own reviewable commit.

The prompts live in [`tools/`](./tools/) and are readable on their own. Each
carries its lane's operating rules, the traps that lane has already measured,
and the anti-patterns it has already paid for.

---

## Data sources and credits

Game data comes from public sources, and they deserve naming:

- **Riot Data Dragon** - champion, item and rune data
- **CommunityDragon** - supplementary and pre-release game data
- **Meraki Analytics** - structured item and champion stat extracts
- **The League of Legends Wiki** - mechanic reference for kits the structured
  data does not describe
- **Riot APIs** - Match-V5 for match history, and the Live Client API the game
  client serves locally during a match

---

## Documentation map

For readers:

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) - component map and data flow
- [`docs/DAEMON_SLAYER.md`](./docs/DAEMON_SLAYER.md) - build engine deep reference
- [`docs/API.md`](./docs/API.md) - dashboard HTTP API
- [`docs/adr/`](./docs/adr/) - architectural decision index
- [`Share/README.md`](./Share/README.md) - the engine's external review package
- [`ROADMAP.md`](./ROADMAP.md) - open work

For maintenance and coding agents:

- [`CLAUDE.md`](./CLAUDE.md) - agent operating context
- [`docs/MISSION_CONTROL_PLAN.md`](./docs/MISSION_CONTROL_PLAN.md) - the headless-lane control plane and the lane roster
- [`docs/OPERATIONS.md`](./docs/OPERATIONS.md) - run, restart, and maintenance procedures
- [`BACKLOG.md`](./BACKLOG.md) - filed work items, each with acceptance criteria
- [`docs/LEDGER.md`](./docs/LEDGER.md) - per-item completion record, newest first
- [`docs/history_notes.md`](./docs/history_notes.md) - the deep archive

---

Amberstone is not endorsed by Riot Games and does not reflect the views or
opinions of Riot Games or anyone officially involved in producing or managing
Riot Games properties. League of Legends and Riot Games are trademarks or
registered trademarks of Riot Games, Inc.

All rights reserved. Personal use only.
