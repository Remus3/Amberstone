# Riot Commander

A local, real-time coaching companion for League of Legends and Teamfight Tactics.

[![CI](https://github.com/Remus3/riot-commander/actions/workflows/ci.yml/badge.svg)](https://github.com/Remus3/riot-commander/actions/workflows/ci.yml) [![Docs guards](https://github.com/Remus3/riot-commander/actions/workflows/docs-guards.yml/badge.svg)](https://github.com/Remus3/riot-commander/actions/workflows/docs-guards.yml)

Personal project. Private repo.
Not packaged for general use.

---

## What it does

- Keeps a running picture of the match from Riot's local data feed - gold, level,
  KDA, items on both teams - polled about once a second, and turns it into short,
  situation-specific tips on a dashboard.
- Reads the screen with OCR first; an AI vision model is escalated only for what
  OCR misses.
- Grounds build and fight advice in a local math engine, so an item suggestion
  reflects your actual matchup - real math, not tier lists.
- Suggests picks in champion select from your own match history filtered by the
  enemy team's composition; ban and counter hints come from the local matchup
  engine's deterministic 1v1 math.
- Writes runes into the client automatically.
- Keeps a local SQLite archive of your own matches - a few thousand games with
  full timeline data - so the coach reads history you own instead of scraping a
  third-party tracker.

Modes: Summoner's Rift, ARAM (including its event variants), Arena, and Teamfight Tactics.

---

## How it works

A Python service polls the game client's local data feed about once a second.
The build engine answers first with local math, and its output is injected into
every AI coaching call; the coach fires on a cadence - about every 8 seconds,
or immediately on kill and health swings. Results render on a locally served
web dashboard and an in-game overlay. A vision server sits to the side, turning
screen captures into data through tiered OCR with AI-vision escalation.

```
game client
    |
    v
local reader (polls about once a second)
    |
    v
Daemon Slayer math first -> AI coach reasons over the math's output
    |
    v
dashboard + in-game overlay

vision server on the side: screen capture -> OCR -> AI vision only on a miss
```

| Port | Service |
|---|---|
| :8888 | Web dashboard (HTTPS) |
| :8889 | Vision server |
| :8893 | Daemon Slayer build engine |
| :2999 | Riot Live Client API (the game client's own feed) |

---

## Daemon Slayer build engine

The technical centerpiece. A local service that scores champion x item x target
combinations with real game math: damage per second, effective HP, ability
burst, and healing throughput. It runs offline at request time - no network
calls, no per-query cost - and covers every purchasable item in the modes it
coaches. One of seven scoring modes is picked automatically from the champion's
role:

| Role | What it optimizes |
|---|---|
| Carry (ADC) | Auto-attack damage per second |
| Tank | Effective HP against the enemy team's damage mix |
| Bruiser | A per-champion blend of damage and durability |
| Mage | Ability damage at the champion's cast cadence |
| Assassin | Total burst inside a combo window |
| Enchanter | Healing and shielding throughput |
| On-hit (AP) | Ability damage plus on-hit auto damage combined into one score |

A registry of per-champion mechanic overrides handles unusual kits - form
swaps, recast windows, resource bars - and covers most of the roster.

Depth: [`docs/DAEMON_SLAYER.md`](./docs/DAEMON_SLAYER.md) (internal reference).
The engine also ships separately as a self-contained package for external
review: [`Share/README.md`](./Share/README.md).

---

## Where it runs

One Windows PC runs the game and the coach together. A Python service runs
under a supervisor and serves the dashboard over local HTTPS to a browser,
plus an Electron overlay for in-game display. Operational procedures live in
[`docs/OPERATIONS.md`](./docs/OPERATIONS.md).

## Status

The coaching loop is functionally complete across all four modes; the build
engine and champion-select advice cover the three League modes, and TFT uses
the vision and coaching paths. Open work is tracked in
[`ROADMAP.md`](./ROADMAP.md).

---

## Documentation map

For readers:

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) - component map and data flow
- [`docs/DAEMON_SLAYER.md`](./docs/DAEMON_SLAYER.md) - build engine deep reference
- [`docs/API.md`](./docs/API.md) - dashboard HTTP API
- [`docs/adr/`](./docs/adr/) - architectural decision index
- [`Share/README.md`](./Share/README.md) - the engine's external review package
- [`ROADMAP.md`](./ROADMAP.md) - open work

For the operator and coding agents:

- [`CLAUDE.md`](./CLAUDE.md) - agent operating context
- [`docs/OPERATIONS.md`](./docs/OPERATIONS.md) - run, restart, and maintenance procedures

---

All rights reserved. Personal use only.
