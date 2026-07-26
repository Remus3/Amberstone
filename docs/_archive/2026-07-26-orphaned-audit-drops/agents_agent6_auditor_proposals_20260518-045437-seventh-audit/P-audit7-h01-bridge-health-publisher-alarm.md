# P-audit7-h01 - Bridge health-publisher staleness alarm path

**Target agent:** Agent 2 (backend)
**Severity:** HIGH
**Filed by:** Agent 6, audit pass 2026-05-18 04:54 UTC

## Trigger evidence

Session bootstrap probe 2026-05-17 23:54 local:
```
gamepc bridge daemon: watcher=alive queue=0 age=8489s ⚠ STALE
peer bridge daemon:    watcher=alive queue=0 age=25s
```
Same task loop, ~340× heartbeat-age delta. The task loop itself is
alive (s154 LCU agent redeploy via bridge task was 63s round-trip the
same day), so the failure is isolated to the **health publisher
sub-process**, not the bridge daemon proper.

## Problem

The STALE marker renders in the rc_facts probe output but nothing
else picks it up:
- `/api/health/all` does not surface `health_publisher_age_s`.
- No dashboard chip flips amber.
- No Agent 1 task is filed on threshold cross.

A publisher silent for 142+ minutes while the loop is alive is the
exact false-confidence shape charter focus-area #6 warns about.

## Proposed fix (two parts)

### Part A - surface staleness in `/api/health/all`

`dashboard/routes_state.py` (or wherever `/api/health/all` is wired
- Agent 2 to confirm). Add a per-node `health_publisher_age_s` field
derived from the same `health.json` file the rc_facts probe reads.

```python
# dashboard/_state_builder.py-adjacent (Agent 2 routes the exact site)
node_health = {
    "node": "gamepc",
    "watcher": "alive",
    "queue": 0,
    "health_publisher_age_s": int(time.time() - os.path.getmtime(
        Path("ops/runtime/bridge_gamepc_health.json"))),
}
```

Dashboard renders amber chip when `> 600`, red chip when `> 1800`.

### Part B - Phase 3 supervisor alarm

`ops/rc_supervisor.py` `_Phase3Watcher` already has the structure
(per s171 active-priority - Phase 3 supervisor folded into main).
Add a sibling check that files an Agent 1 task on threshold cross:

```python
# ops/rc_supervisor.py near _Phase3Watcher.check()
HEALTH_PUBLISHER_THRESHOLD_S = 1800

def _check_bridge_publishers(self):
    for node in ("gamepc", "peer"):
        path = Path(f"ops/runtime/bridge_{node}_health.json")
        if not path.exists():
            continue
        age = time.time() - path.stat().st_mtime
        if age > HEALTH_PUBLISHER_THRESHOLD_S:
            self._file_agent1_task(
                kind="bridge_publisher_stale",
                severity="warning",
                node=node,
                age_s=int(age),
                dedup_key=f"bridge-publisher-stale-{node}",
                suggested_action=f"tools/gamepc_boot.ps1 restart of "
                                f"RC-WatcherHealthPublisher-{node}",
            )
```

The dedup_key prevents spam - Agent 1 only re-files when the task is
acknowledged or aged out.

## Why this is the right shape

Bundles cleanly with the s167 deferral bucket already calling out
`RC-WatcherHealthPublisher-GamePC` and `RC-BridgeWatcher-GamePC`
hardening in `tools/gamepc_boot.ps1`. The alarm path is the
*detection* half; the boot-script hardening is the *prevention* half.
Both ship in the same Agent 2 pass and the alarm continues to be
useful even after the boot script is hardened (catches non-boot-time
crashes).

## Test plan

- Unit test: simulate `health.json` mtime 700s ago, assert
  `/api/health/all` returns `health_publisher_age_s: 700`.
- Unit test: simulate mtime 2000s ago, assert
  `_check_bridge_publishers` queues exactly one Agent 1 task.
- Unit test: second consecutive call with mtime still 2000s+ ago,
  assert dedup suppresses second filing.

## Acceptance

- [ ] `/api/health/all` carries `health_publisher_age_s` per node.
- [ ] Dashboard renders amber/red chip on threshold cross.
- [ ] Agent 1 receives exactly one task per node-staleness event.
- [ ] Live verification on the current Game-PC publisher (still STALE
      as of audit time) - task fires within 5 minutes of deploy.
