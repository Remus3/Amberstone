# ADR-012: RC<->Peer cross-Claude bridge + lessons-sync decommissioned

**Date:** 2026-06-24
**Status:** Accepted (executed 2026-06-24; supersedes ADR-004)

## Context

The RC<->Peer cross-Claude bridge (ADR-004) and the Phase-4 lessons-sync
subsystem were built so a Claude session on one machine could dispatch tasks,
post activity, and ship "lessons" (cross_project memory envelopes) to a Claude
session on another machine over Tailscale. With Game-PC retired (ADR-011) the
only remaining peer was Peer, and the operator confirmed the cross-machine
coordination is no longer needed: in practice the bridge carried near-zero real
traffic and the always-on poll daemons + scheduled tasks were pure idle cost.

## Decision

Full removal of the bridge and the lessons cross-project sync subsystem.

1. **Code + tests.** ~67 modules/routes/tests deleted: `core/bridge*.py`,
   `core/lessons_*.py`, all `tools/bridge_*.py` + `tools/lessons_*.py`,
   `dashboard/routes_bridge*.py` + `routes_health_peer.py` + `routes_lessons.py`
   + `_bridge_log.py`, and their tests.
2. **Daemons + scheduled tasks.** RC-BridgeWatcher / RC-BridgeDaemon /
   RC-Bridge-MCP / RC-VerifyBridgeRoundtrip-Once removed, plus
   `ops/RC-BridgeWatcher.xml`.
3. **`core.bridge.send` is gone**, so the two escalation callers that reused it
   are now LOCAL-ONLY: the CI-watchdog writes `ops/runtime/ci_watchdog/
   ESCALATION.md`, and `tools/upstream_drift_check.py` logs drift locally
   instead of posting a note to Peer.
4. **`/api/champions`** (formerly served by the bridge route module) was
   extracted to `dashboard/routes_champions.py`. The `/api/team-context` POST is
   now local-only with no bearer auth.
5. **Docs + memory** swept: `docs/BRIDGE.md` deleted; ARCHITECTURE / OPERATIONS /
   AGENTS / CI_WATCHDOG_PLAN bridge content removed; the bridge/lessons memory
   topic files + their MEMORY.md index lines deleted.

## Consequences

- No cross-Claude messaging or lessons sync remains. Peer persists only as the
  separate private-project machine; it is no longer an RC peer.
- Escalation is local-only (an operator-read file), not a cross-machine ping.
- Do NOT re-pitch a bridge or a lessons-sync subsystem. ADR-004 is superseded;
  this is a deliberate, operator-directed removal.
