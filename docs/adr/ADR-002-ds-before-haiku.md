# ADR-002: Daemon Slayer item ranking runs before Haiku coaching call

**Date:** 2026-04 (Daemon Slayer integration)  
**Status:** Accepted

## Context

Haiku coaching prompts included raw item lists and champion stats, but Haiku lacks the math depth to evaluate complex item interactions (e.g., Lethality stacking, Sheen proc timing, AD-scaling on ability passives). Coach prompts were long and Haiku still gave generic "build AD items" advice.

Alternative: run a separate heavier model (Sonnet) for item evaluation. Cost would be 10–20× higher per coaching tick.

## Decision

Daemon Slayer (`:8893`, pure-Python DPS math engine) evaluates all purchasable items for the current champion before the Haiku call. It ranks items by computed DPS contribution and injects a `top_items` list into the coaching prompt. Haiku sees pre-ranked items and focuses on game-state advice, not item math.

All four coach modes (ARAM, Arena, Brawl, SR-preview) are DS-before-Haiku.

## Consequences

**Good:** Coaching quality improved dramatically for itemization. DS runs locally with no API cost. Haiku token usage dropped because prompts are more focused.  
**Trade-off:** DS must be kept current with every patch (item stat changes, new items). Batch workflow exists for this (see `ROADMAP.md`).  
**Watch for:** DS `ENGINE_VERSION` must match the live patch. Stale DS = stale item recommendations. The `DS server :8893` line in `rc_facts.py` surfaces staleness.
