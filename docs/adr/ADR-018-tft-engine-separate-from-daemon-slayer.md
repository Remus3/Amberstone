# ADR-018: The TFT comp/item engine is separate from Daemon Slayer

**Date:** 2026-10-25  
**Status:** Accepted

## Context

The operator asked (session 134, 2026-10-25) for a TFT-centric program: per-round
capture of everything on screen, a TFT dashboard for lobby / match / post-match, an
in-game prior-top-4 team-planner picker, and fewer LLM calls - and asked directly:
"Will TFT's comp/item engine be separate from Daemon Slayer?"

Daemon Slayer (DS) is per-champion League of Legends DPS / EHP math served on
`:8860` (`docs/DAEMON_SLAYER.md`, `agents/daemon_slayer/`): ability formulas, item
passives, resist and penetration seams, archetype scorers, `ENGINE_VERSION` bumps and
a Tier-2 dual-suite gate. TFT shares none of that domain: its units, traits, star
levels, hex board, shared champion pool, shop odds, econ (interest, streaks) and item
recipes have no counterpart in DS, and no DS formula, scorer or data file applies.

Alternatives considered:

1. **Extend DS with a TFT module.** Rejected: DS changes are Tier-2 (full dual suite,
   `ENGINE_VERSION` bump, `:8860` restart), so every TFT tweak would pay the League
   engine's gate and risk its CLOSED / saturated registries (CLAUDE.md Settled) for no
   shared math.
2. **A second sidecar service like DS on its own port.** Rejected for now: the engine is
   small pure functions over a local SQLite store and set data; a service adds a port
   (seven port blocks already, memory `reference_cross_project_port_blocks`), a
   supervisor entry and a respawn path for no measured benefit. Revisit if engine cost
   ever blocks the RC loop.
3. **A separate in-process engine package** (chosen).

## Decision

The TFT comp/item engine is its own package, `tft/engine/`, in-process in RC, with no
import of `agents/daemon_slayer` and no call to `:8860`. Its provisional display name is
**Augur** (the operator may rename it): the name lives in ONE constant,
`tft.engine.ENGINE_NAME`, and every UI label and API payload reads it from there, so a
rename is a one-line change. Package, module, route and file names stay neutral
(`engine`, `/api/tft/...`) for the same reason.

## Consequences

**Good:** TFT work ships at Tier-1 without touching the DS gate; DS stays League-only
and its Settled fences stay intact. The engine reads only game data
(`data/meta/tft_set<N>_cdragon.json` via `tft/tft_set.py`) and the operator's own
matches (the per-round store in `docs/TFT_PROGRAM.md`), which keeps it inside the
RM-846 licence line (no third-party tier list, comp or ladder statistic in the tree).  
**Trade-off:** No shared infrastructure with DS (versioning, sweep tooling, health
endpoint); the engine needs its own versioning (`tft.engine.ENGINE_SCHEMA`) and its own
accuracy evidence. A future need for heavy compute (for example board-fight
simulation) would reopen alternative 2.  
**Watch for:** A guard must fail if `tft/engine/` imports `agents.daemon_slayer` or if
the literal engine name appears outside its one constant (slice TFT-13 in
`docs/TFT_PROGRAM.md`). If the operator renames Augur, change the constant; the only
other edits are prose (this ADR, its README row, `docs/TFT_PROGRAM.md`), in the same
commit.
