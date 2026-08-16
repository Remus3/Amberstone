# ADR-004: Bridge tasks processed by always-on daemon, not /loop polling

**Date:** 2026-05-02
**Status:** Superseded by ADR-012 (bridge decommissioned 2026-06-24; originally Accepted, superseding the /loop polling approach)

## Context

Bridge tasks (cross-Claude messages from Peer or Legion targeting Game-PC) originally required `/loop /process-bridge-tasks` to be running in an active Claude session on the receiving machine. If the Claude session restarted, the loop died and tasks accumulated silently.

Alternative: scheduled task + headless `claude --print` call on each poll cycle.

## Decision

`tools/bridge_watcher.py` + `RC-BridgeWatcher` scheduled task (on each machine) provides always-on daemon polling. On each cycle it: pulls tasks -> classifies -> acts (headless `claude --print`) -> posts result. No active Claude session required. The `/loop /process-bridge-tasks` skill still exists for manual override but is no longer the normal path.

## Consequences

**Good:** Bridge auto-flow survives Claude restarts. `rc_facts.py` surfaces daemon health (`watcher_alive`, `queue`, `age`). No operator babysitting.  
**Trade-off:** Daemon complexity - `bridge_watcher_classify.py` + `bridge_watcher_actions.py` + `bridge_watcher_history.py` are all frozen because a bad deploy breaks cross-Claude communication.  
**Watch for:** `auto_ok_since_boot` vs `auto_err_since_boot` in bridge health. 50+ auto-action samples needed to validate acceptance criteria. Until then, monitor these counters.
