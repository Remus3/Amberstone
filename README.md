# Amberstone

A local, real-time coaching companion for League of Legends and Teamfight
Tactics.

[![CI](https://github.com/Remus3/Amberstone/actions/workflows/ci.yml/badge.svg)](https://github.com/Remus3/Amberstone/actions/workflows/ci.yml) [![Docs guards](https://github.com/Remus3/Amberstone/actions/workflows/docs-guards.yml/badge.svg)](https://github.com/Remus3/Amberstone/actions/workflows/docs-guards.yml)

It watches the match you are actually in through the Riot Live Client API, does
the item and damage math locally in a deterministic engine, and turns that into
short, situation-specific advice on a dashboard and an in-game overlay.

It is a single-machine personal build: one Windows PC runs the game, the engine,
the coach and the overlay together, with no hosted version and no installer.

**[Explore the codebase as a map](https://remus3.github.io/Amberstone/atlas.html)**
draws the project's main components as one interactive page, with source files
orbiting the component they belong to. It runs in the browser and loads nothing
from the network.

## Contents

| | |
|---|---|
| [What makes it different](#what-makes-it-different) | why the math runs before the model, and what that buys |
| [What it does](#what-it-does) | the features, and the modes they run in |
| [How it works](#how-it-works) | the pipeline in one diagram, plus the port map |
| [Daemon Slayer build engine](#daemon-slayer-build-engine) | the engine everything else is built around |
| [Limitations](#limitations) | what it cannot do, and why |
| [Status](#status) | what is done, what is in flight, what is blocked on a live game, and what is deliberately not being built |
| [How the work gets done](#how-the-work-gets-done) | the headless lanes that maintain it, and why one item per cycle |
| [Data sources and credits](#data-sources-and-credits) | the public projects the game data comes from |
| [Documentation map](#documentation-map) | every other document, and who each is written for |

---

## What makes it different

Most build advice is a popularity contest: an item is recommended because many
players bought it in many games. This project takes the other route.

- **The math runs first, locally.** A deterministic build calculator scores
  champion x item x target combinations from real game numbers - damage per
  second, effective HP, ability burst, healing throughput - and the LLM coaching
  agent reasons *over that output* rather than guessing. An item suggestion
  reflects your actual matchup, not a tier list.
- **No win-rate scraping for builds.** Item and build recommendations never
  come from other players' win rates. They come from computed quantities,
  which is also why the engine can answer for matchups too rare to have a
  sample size. Two narrow features do read published statistics - a
  bot-lane duo-synergy grid and ARAM Mayhem augment priors - and both are
  credited below.
- **Your own history, not a tracker's.** Matches land in a local SQLite archive
  with full timeline data, so champion select reads history you own.
- **Offline at request time.** The engine makes no network calls and has no
  per-query cost, so it can be asked thousands of questions per game.

---

## What it does

- Keeps a running picture of the match from the game client's own local feed -
  gold, level, KDA, items on both teams - polled about once a second, and turns
  it into situation-specific tips.
- Reads the screen with OCR first, and escalates to an AI vision model only for
  what OCR misses.
- Suggests picks in champion select from your own match history, filtered by the
  enemy team composition; ban and counter hints come from the engine's own 1v1
  damage math.
- Writes runes into the League client automatically, through the client's own
  local LCU (League Client API) endpoint.

Modes: Summoner's Rift, ARAM including its event variants, Arena, and Teamfight
Tactics. A fifth path covers Riot's rotating game modes - URF, One for All,
Nexus Blitz and their siblings - which is wired and enabled, but only exercised
when Riot actually rotates one of them in.

---

## How it works

A Python service polls the Live Client API about once a second. The build engine
answers first with local math, and its output is injected into every coaching
call. The coach fires roughly every 8 seconds, and immediately on kills and
health swings.

```text
  Riot Live Client API :2999         screen capture
  gold / level / items / KDA               |
              |                            v
              |                   OCR first, AI vision
              v                   only on a miss  :8889
  local reader, about 1 Hz  <--------------+
              |
              v
  +----------------------------------------------------+
  |  Daemon Slayer build engine           :8860        |
  |  computed DPS / EHP / burst / healing math         |
  |  no network calls, no per-query cost               |
  +----------------------------------------------------+
              |  scored builds, counters, item deltas
              v
  LLM coaching agent
              |
              v
  web dashboard :8888  and  in-game Electron overlay
```

| Port | Service |
|---|---|
| :8888 | Web dashboard (HTTPS) |
| :8889 | Vision server |
| :8890 | Agents supervisor (proxied by the dashboard) |
| :8891 | Agents WS relay |
| :8895 | Mission Control (separate process, JSON API only, no web page) |
| :8860 | Daemon Slayer build engine |
| :8861 | Daemon Slayer match-history MCP server |
| :2999 | Riot Live Client API (the game client's own feed) |

---

## Daemon Slayer build engine

The engine everything else is built around. It is a build calculator and item
optimizer in one: it models the full champion roster and every item the shop
actually offers in the modes it scores, including the mode-specific pools, and
picks one of seven scoring modes automatically from the champion's role.

| Role | What it optimizes |
|---|---|
| Carry (ADC) | Auto-attack damage per second |
| Tank | Effective HP against the enemy team's damage mix |
| Bruiser | A per-champion blend of damage and durability |
| Mage | Ability damage at the champion's cast cadence |
| Assassin | Total burst inside a combo window |
| Enchanter | Healing and shielding throughput |
| On-hit (AP) | Ability damage plus on-hit auto damage in one score |

Champions do not fit one formula, so a registry of per-champion mechanic
overrides handles the unusual kits - form swaps, recast windows, resource bars,
revives - and covers most of the roster.

It is self-contained and readable on its own: the scoring code, its per-champion
registries and its test suite all live under
[`agents/daemon_slayer/`](./agents/daemon_slayer/), and the depth reference is
[`docs/DAEMON_SLAYER.md`](./docs/DAEMON_SLAYER.md).

---

## Limitations

- **Windows only, one machine.** Game, coach, dashboard and overlay share a PC.
  A Python service runs under a supervisor, serves the dashboard over local
  HTTPS to a browser, and drives an Electron overlay for in-game display; the
  procedures for running it live in
  [`docs/OPERATIONS.md`](./docs/OPERATIONS.md).
- **Bring your own API key.** The coaching and vision paths call a third-party
  model API. Without a key those paths stay off and the local math still works.
- **Riot's API limits what is knowable.** Some event modes return no match
  history through the public API, and some in-game state has no API at all -
  which is exactly why the vision path exists.
- **Not affiliated with Riot Games.** See the disclaimer below.

---

## Status

**Working now.** The full loop runs end to end: the live reader, the build
engine, the coach, the dashboard and the overlay. The build engine and
champion-select advice cover the League modes; TFT runs on the vision and
coaching paths. Automatic rune writing, the local match archive with timeline
data, and the Electron overlay are shipped.

**In flight.** The largest open program is taking the model out of the hot path:
precompute the common coaching decisions as plain engine lookups so live LLM
calls trend toward zero, leaving the language model for what genuinely needs
judgement. Alongside it run a UI redesign, a standing per-file hardening audit
that files each finding as its own tracked item, and counter-build hints that
are code-complete and waiting on a live game to confirm.

**Blocked on a real game.** Render cadence, overlay timing and event ordering can
only be settled while a match is running, so those items are tracked apart in
[`docs/LIVE_GAME_GATED_SYNC.md`](./docs/LIVE_GAME_GATED_SYNC.md) rather than
closed on synthetic evidence.

**Deliberately not being built.** No win-rate-driven build advice and no
machine-learned win predictor - the engine exists so neither is needed. No replay packet parsing as a
shipping feature, since the format is re-obfuscated each patch. No replacement
for the in-game HUD: the Live Client API exposes no cooldowns, buffs, wards or
XP, so the overlay augments the HUD and cannot stand in for it. No hosted
service, no installer.

Open work lives in [`ROADMAP.md`](./ROADMAP.md), the longer-horizon queue in
[`BACKLOG.md`](./BACKLOG.md), and the completion record in
[`docs/LEDGER.md`](./docs/LEDGER.md).

---

## How the work gets done

**Headless lanes.** Maintenance runs as mutually exclusive lanes, one holder at
a time, each in its own git worktree, so nothing edits the checkout a person is
reading. A lane is a single `claude -p` worker fed a tracked prompt document
from [`tools/`](./tools/).

**One item per cycle.** A research lane files work items carrying an id, cited
`file:line` evidence and an acceptance check; a queue lane does exactly one of
them and exits, and a driver re-fires it. A crash loses one item rather than a
night's work, and each item arrives as its own reviewable commit.

The control plane and the lane roster are described in
[`docs/MISSION_CONTROL_PLAN.md`](./docs/MISSION_CONTROL_PLAN.md).

---

## Data sources and credits

Game data comes from these public sources:

- **Riot Data Dragon** - champion, item and rune data
- **CommunityDragon** - supplementary and pre-release game data
- **Meraki Analytics** - structured item and champion stat extracts
- **The League of Legends Wiki** - mechanic reference for kits the structured
  data does not describe
- **Riot APIs** - Match-V5 for match history, and the Live Client API the game
  client serves locally during a match
- **lolmath** - the data chunk the ARAM balance modifiers are extracted from
- **101.qq.com** - duo-synergy win-rate rows for the bot-lane pairing grid
- **An external augment-statistics endpoint** - ARAM Mayhem augment priors,
  fetched on demand and not cached in the repository

Each source keeps its own terms; [`NOTICE`](./NOTICE) records them one by one.

---

## Documentation map

The repository root mixes documents written for people with working files the
maintenance agents keep between sessions. The lists below separate the two.

For readers:

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) - component map and data flow
- [`docs/DAEMON_SLAYER.md`](./docs/DAEMON_SLAYER.md) - build engine deep reference
- [`docs/API.md`](./docs/API.md) - dashboard HTTP API
- [`docs/adr/`](./docs/adr/) - architectural decision index
- [`agents/daemon_slayer/`](./agents/daemon_slayer/) - the build engine itself, with its own tests
- [`ROADMAP.md`](./ROADMAP.md) - open work
- [`atlas.html`](./atlas.html) - the repository drawn as an interactive map, served at [remus3.github.io/Amberstone/atlas.html](https://remus3.github.io/Amberstone/atlas.html). One self-contained page; too large for GitHub's file view to render, so use the served link or open the file locally

For anyone reporting or contributing:

- [`.github/CONTRIBUTING.md`](./.github/CONTRIBUTING.md) - what a useful issue looks like, and why a pull request may not be merged
- [`.github/SECURITY.md`](./.github/SECURITY.md) - how to report a vulnerability privately
- [`.github/CODE_OF_CONDUCT.md`](./.github/CODE_OF_CONDUCT.md) - the short version: be civil, be specific

For maintenance and coding agents:

- [`CLAUDE.md`](./CLAUDE.md) - agent operating context
- [`docs/MISSION_CONTROL_PLAN.md`](./docs/MISSION_CONTROL_PLAN.md) - the headless-lane control plane and the lane roster
- [`docs/OPERATIONS.md`](./docs/OPERATIONS.md) - run, restart, and maintenance procedures
- [`BACKLOG.md`](./BACKLOG.md) - filed work items, each with acceptance criteria
- [`docs/LEDGER.md`](./docs/LEDGER.md) - per-item completion record, newest first
- [`docs/history_notes.md`](./docs/history_notes.md) - the deep archive
- [`WAKEUP_NOTES.md`](./WAKEUP_NOTES.md) and [`RC-NEXT-SESSION.txt`](./RC-NEXT-SESSION.txt) - session-to-session continuity, rewritten most nights. `RC-NEXT-SESSION.txt` is the single hand-off file: one file in the repo root, OVERWRITTEN every `/done`, never appended and never dated-suffixed, with a Desktop shortcut pointing at it. The older `NEXT_SESSION_PROMPT.md` was the same idea in a second place and was retired to `docs/_archive/2026-09-07-NEXT_SESSION_PROMPT.md` on 2026-09-20. Useful for watching how the work proceeds, and not written for a first read

---

Amberstone is not endorsed by Riot Games and does not reflect the views or
opinions of Riot Games or anyone officially involved in producing or managing
Riot Games properties. League of Legends and Riot Games are trademarks or
registered trademarks of Riot Games, Inc.

Source code and authored documentation are licensed under the Apache
License 2.0 - see [`LICENSE`](./LICENSE). That licence does NOT extend to
the third-party-sourced data files under `data/`, which stay governed by
their own upstream terms; [`NOTICE`](./NOTICE) records them source by
source. Nothing here grants a right to redistribute that data.
