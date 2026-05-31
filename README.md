# Riot Commander

A live coaching companion for League of Legends and Teamfight Tactics. RC reads the game's local data feed, watches the screen, and shows a second-screen dashboard with real-time advice - what to build next, when to fight, who to ban during the picking phase before a match.

Personal project. Private repo. Not packaged for general use.

---

## What it does

Coaching during a match. RC keeps a running picture of the game from Riot's local data feed (your gold, level, KDA, items, the enemy team's items, where champions are on the minimap) and turns that into short, situation-specific tips on the dashboard. When a decision needs visual judgment - minion wave state, fog-of-war inference, an item-spike timing - it sends a screenshot to an AI model for interpretation. Most decisions don't need that, so most ticks are cheap.

Real math, not tier lists. RC ships with a local build engine ("Daemon Slayer") that computes actual damage-per-second, effective HP, ability burst, and healing throughput for any champion × item × enemy combination. The AI coach reads those numbers when it suggests an item, so the recommendation matches *your* matchup rather than a static "best build" guide.

Champion select advice. Suggests bans and picks based on what you've actually played well historically, what the enemy team has, and what the patch favors. Writes runes into the client for you automatically.

Match history that you own. Roughly 3,000 of your matches with full timeline data are kept locally; the coach reads from that instead of scraping a third-party tracker.

Modes covered. Summoner's Rift (the standard 5v5), ARAM, Arena, Brawl, and Teamfight Tactics - all wired into the coaching pipeline.

---

## How it works

The dashboard is a regular web page served locally; you open it in Chrome on a second monitor. Behind it, a small Python service watches the game several times a second and decides whether the next tip should come from a quick local calculation or from an AI call. AI is reserved for nuance - wave state, contested objectives, end-screen reads - so most of what you see arrives in well under a second and the API bill stays small.

The build engine runs as a separate local service on a different port. When the coach is about to suggest an item, it asks the engine: given this champion at this level facing this enemy comp, what's the best item to buy next? The engine returns a ranked list with real damage numbers, and the coach drops that into its prompt. No cloud calls, no per-query cost.

---

## Daemon Slayer build engine

The technical centerpiece. A local service that scores any champion × item × enemy combination using real game math, with one of six scoring modes picked automatically based on your champion's role:

| Role | What it scores |
|---|---|
| Carry (ADC) | Auto-attack damage-per-second |
| Tank | Effective HP against the enemy team's damage mix |
| Bruiser | A blend of DPS and EHP, weighted per champion |
| Mage | Per-spell ability damage at your cast cadence |
| Assassin | Total burst inside a combo window |
| Enchanter | Healing and shielding throughput |

A registry of per-champion overrides handles the unusual mechanics - Nidalee's cougar form, Akali's R recast window, Zed's shadow Q, Renekton's Fury bar, Riven's Wind Slash, and so on. About three-quarters of the roster is covered today, with new entries added in regular small batches.

Coverage today: every purchasable item across all five modes (547 items), 5,335 tests, current League patch.

---

## Where it runs

RC normally runs across two machines on a small private network: one machine runs the brain (the coach, the dashboard, the build engine), the other runs the game and feeds the brain a live screen capture. They communicate over a small bridge service. A single-machine setup is technically possible and is the eventual goal - for now the split is what's documented.

The same bridge architecture also lets a third machine (a separate work-from-home setup) coordinate with RC for non-game projects. That's incidental to the coaching product but explains why some files mention a third hostname.

---

## Project status

RC has been in active development for over a year. The in-game coaching loop is functionally complete across all five modes: vision, build engine, dashboard, champion-select advice, and AI coaching are all live and stable.

Active work right now is mostly polish and validation:

- Calibrating which screen regions a cheap OCR pass can read versus when an AI vision call is needed.
- Validating the build engine's score against actual match outcomes.
- Filling in the per-champion override registry for the long tail of unusual ability mechanics.
- Iterating on the champion-select page of the dashboard.

Long-term direction is collapsing the two-machine setup into a single-machine install so RC can eventually be packaged for someone other than the author to run.

---

## More

- [`CLAUDE.md`](./CLAUDE.md) - operational context (paths, restart workflow, current priorities)
- [`ROADMAP.md`](./ROADMAP.md) - full milestone ledger
- [`docs/DAEMON_SLAYER.md`](./docs/DAEMON_SLAYER.md) - build engine deep reference
- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) - module map
- [`docs/adr/`](./docs/adr/) - architectural decisions

---

## License

All rights reserved. Personal use only.
