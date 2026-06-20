# RC 2.0 Phase 6.6 - Port/CPU Footprint Regression Verification

Date: 2026-06-20. Topology: 1-PC (Legion, ADR-011). Closes Phase 6
RESPONSIVENESS. Builds on the P6.1 IO timing map
(`docs/research/RC2_RESEARCH_io_timing_map.md`) and the P6.4 port-safety
audit (`docs/research/RC2_PORT_SAFETY_AUDIT.md`). ASCII only.

Goal: prove that the Phase 6 cadence tightening (6.2/6.3) and latency
overlap (6.5) introduced NO net loopback-socket or CPU footprint
regression, and machine-lock every footprint invariant so a future edit
to any single lever cannot silently regress the aggregate.

---

## 1. Per-lever footprint delta (what changed, what bounds it)

| Stage | Change | Socket delta | CPU delta | Safeguard (constant) |
|---|---|---|---|---|
| 6.2 | RuneWriter poll 2.0s -> 1.0s | +0.5 GET/s, SAME single loop on one lockfile port | negligible | `RuneWriter.POLL_INTERVAL` floor (`>0`, `<=1.0`), env `RC_RUNEWRITER_POLL_SEC` |
| 6.3 | State cadence 1.0s -> 0.5s (SSE tick + TTL) | ZERO new sockets - SSE is push over one long-lived stream | <=2 builds/s, TTL-gated | `_STATE_CADENCE_S` floor-clamp `>=0.1`; `_SSE_TICK_S == _STATE_CADENCE_S` (one constant, cannot drift) |
| 6.4 | LCU pooling primitives (L6/L7) | ZERO - ships DEFAULT-OFF (`RC_LCU_POOL=0`), lazy singleton | none until opt-in | `pool_enabled()` default off; `MinIntervalGuard` floor (L7); L8 :2999 floor `>=1.5s` |
| 6.5 | State-pipeline relay overlap | ZERO - SAME two relay round-trips, briefly overlapped, never multiplied | bounded thread pool | `_RELAY_POOL` ThreadPoolExecutor `max_workers=4` |

Net: the only steady-state socket-rate increase across all of Phase 6 is
+0.5 LCU GET/s from the single RuneWriter loop (6.2). Everything else is
push (SSE), default-off (pooling), or an overlap of already-open
connections (relay pool). No new connection class, no fan-out.

## 2. Why each tightening is port-safe

- **6.2 RuneWriter** - one loop, one lockfile port. The audit's binding
  constraint (per-call handshake -> TIME_WAIT churn) scales linearly; +0.5
  GET/s is far under the ephemeral-port ceiling and is the lever E7 will
  later consolidate onto the L6 pool. Floor-locked so a future edit cannot
  drop it to a busy spin.
- **6.3 render cadence** - SSE is a single persistent stream; a faster tick
  re-emits on the SAME socket, adding zero connections. The TTL and the SSE
  tick are now ONE constant (`_STATE_CADENCE_S`), so they cannot drift into
  double the build rate, and a garbage/zero override is floor-clamped to
  0.1s. The 8-subscriber SSE cap and the 600s connection-lifetime cap bound
  dispatcher-thread accumulation.
- **6.4 pooling** - `pool_enabled()` reads `RC_LCU_POOL` (default "0") and
  `get_shared_pool()` is lazy, so importing the module reserves NO socket;
  the live path is byte-identical until an operator opts in. `MinIntervalGuard`
  (L7) caps any consolidated reader's effective rate. The L8 :2999 direct
  floor stays `>=1.5s`.
- **6.5 relay overlap** - the latency win comes from running the two
  EXISTING relay round-trips concurrently, not from adding readers. The pool
  is a small fixed `max_workers=4` (TTL-gated build at ~2/s never queues a
  fan-out), with a named thread prefix (`rc-state-relay`) so a thread dump
  can attribute the workers. A hung relay is bounded at `max()` not `sum()`
  of the two 1s timeouts.

## 3. Live loopback observation (baseline)

Probed 2026-06-20, RC pid 5540, mode=client (no game in progress),
`netstat -ano -p TCP` filtered to `127.0.0.1`:

| metric | value | note |
|---|---|---|
| loopback rows | 1120 | total localhost TCP rows |
| ESTABLISHED | 20 | live long-lived streams (SSE, DS, phase3) |
| TIME_WAIT :8889 | 537 | in-process vision relay/cache 0.5s loop (cheap target) |
| TIME_WAIT :8888 | 8 | dashboard polls/SSE |
| TIME_WAIT :8890 | 29 | phase3 supervisor |
| TIME_WAIT :2999 | 0 | Riot direct - idle (relay self-read fires only when cache stale) |
| TIME_WAIT LCU port | 0 | no champ-select active this probe |

Reading: all churn is against the IN-PROCESS :8889 cache (audit Section 1:
`liveclient_cache` 0.5s -> :8889, never :2999) - the cheap target by
design. The expensive direct targets (:2999, the LCU lockfile port) show
ZERO TIME_WAIT at idle, confirming the cadence tightening did not push
churn onto a Riot-facing port. The champ-select peak (~4 LCU GET/s, audit
Section 1) was not active this probe; its math is unchanged from the audit
and remains under the ephemeral ceiling, with the L6 pool ready to
decouple it on E7 opt-in.

## 4. Machine-locked invariants (regression guard)

`tests/test_port_cpu_footprint_rc2.py` (13 tests) re-asserts every Phase 6
footprint invariant in ONE consolidated guard so a future edit to any
single lever fails loud:

- `RC_LCU_POOL` default-off; `_shared_pool` lazy (no eager socket);
  `MinIntervalGuard` enforces its floor.
- :2999 self-read floor `>=1.5s`; self-read timeout `<=1.5s`.
- `_RELAY_POOL` is a ThreadPoolExecutor, `max_workers<=4`, named
  `rc-state-relay`.
- `_SSE_TICK_S == _STATE_CADENCE_S`; cadence floor-clamped `>=0.1`; default
  0.5s; SSE max-duration `<=600s`.
- `RuneWriter.POLL_INTERVAL` positive and `<=1.0s`.

The per-stage tests still lock each lever in isolation; this file is the
aggregate gate.

## 5. Verdict

No port or CPU footprint regression across Phase 6. The single steady-state
delta (+0.5 LCU GET/s from 6.2) is bounded and far under the port ceiling;
every other lever is push, default-off, or an overlap of already-open
connections. All invariants are machine-locked. Phase 6 RESPONSIVENESS is
complete.

The `RC_LCU_POOL` default-ON flip remains operator-gated on a real-game
socket observation -> `docs/LIVE_GAME_GATED_SYNC.md`.
