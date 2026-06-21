# H-04 publisher vs watcher freshness conflated (audit-10)

- Target agent: 2 (backend)
- Severity: HIGH
- Audit: `20260621-100200-tenth-audit-phase3.md`

## Problem

`/api/health/all` peer rollup computes `age_s = time.time() -
rec.received_at`. This measures publisher relay age, not the
underlying watcher heartbeat age. A wedged watcher whose publisher
keeps relaying a frozen snapshot is reported `green` indefinitely.

Live evidence (2026-06-21 10:02 UTC):
- `peers.peer.age_s = 0.2s` (status green, watcher_alive: true)
- `heartbeat.updated_at = 1780344276` = 2026-06-01, **19.6 days stale**.

This is exactly the false-confidence failure mode H-01 was supposed
to close.

## Concrete fix (unified-diff sketch)

In `dashboard/routes_state.py` (the `peers` rollup block, lines
~309-332):

```python
peers[node] = {
    "age_s":          round(age_s, 1),
    "stale":          age_s > _PEER_HEALTH_WARN_S,
    "status":         _peer_health_status(age_s),
    ...
}
```

becomes:

```python
hb_updated = (rec.get("heartbeat") or {}).get("updated_at") or 0
hb_age_s = max(0.0, time.time() - hb_updated) if hb_updated else None
effective_age_s = max(age_s, hb_age_s) if hb_age_s is not None else age_s
peers[node] = {
    "age_s":          round(age_s, 1),
    "heartbeat_age_s": round(hb_age_s, 1) if hb_age_s is not None else None,
    "stale":          effective_age_s > _PEER_HEALTH_WARN_S,
    "status":         _peer_health_status(effective_age_s),
    ...
}
```

Then `peer_degraded` check downstream is unchanged because it reads
the new `status`.

## Acceptance

- A peer whose publisher POSTs every 60s but whose heartbeat
  `updated_at` is > 600s stale must surface `status: yellow` and
  cap top-level `rollup.status` at yellow.
- Existing fresh-publisher fresh-watcher cases must still report
  `status: green` (regression test).
- Add a unit test in `tests/test_routes_state_peer_rollup.py`
  covering both cases.

## Notes

`heartbeat_publisher` on the peer side may also benefit from
detecting its own staleness and refusing to relay a frozen heartbeat
- but that is a peer-side fix outside Legion's authority. The Legion
rollup is the authoritative alarm surface and should not depend on
publisher cooperation.
