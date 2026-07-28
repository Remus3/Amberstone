# RC 2.0 Phase 6.4 - Port-Safety Audit (connection reuse, no fan-out storms)

Date: 2026-06-20. Topology: 1-PC (Legion, ADR-011). Builds on the P6.1 IO timing
map (`docs/research/RC2_RESEARCH_io_timing_map.md`). ASCII only.

Goal: bound loopback socket churn so a tighter poll cadence (P6.2/P6.3) cannot
exhaust ephemeral ports or open a connection storm. Deliverable: the audit below
plus two reusable primitives in `core/lcu_pool.py` (L6 pool + L7 floor) shipped
DEFAULT-OFF, and an L8 regression lock on the :2999 self-read floor.

---

## 1. Loopback connection inventory (who opens what, per second)

Every LCU + :2999 reader opens a NEW `urllib` connection per call with NO
keep-alive (timing map Findings B). Counting the LIVE 1-PC path only (legacy
Game-PC agent loops excluded - out of the pipeline post-ADR-011):

| loop | target | cadence | conns/sec (steady) | new socket each call? |
|---|---|---|---|---|
| `LcuClient._auto_accept_tick` (queue + `_maybe_apply_runes` champ-select) | LCU port | 1.0s | ~2 | yes (`lcu_client.py:86`) |
| `RuneWriter._poll` (champ-select + lobby) | LCU port | 1.0s (P6.2; was 2.0s) | ~2 | yes (per-call urlopen) |
| `game_reader.poller._lcu_get` (`read_champ_select`) | LCU port | on-demand (client-mode) | burst | yes -> **now poolable (L6)** |
| `liveclient_cache._fetch_once` | :8889 relay | 0.5s | ~2 | yes (in-process cache, NOT :2999) |
| `game_reader.poller._try_relay` + `_try_lcu_game_id` | :8889 relay | 1.5s | ~2 | yes |
| `vision_server/_relay._fetch_liveclient_direct` | :2999 direct | >=1.5s throttle, only when cache >2.0s stale | <=0.7 | yes (floor-guarded) |

Peak concurrency lands in the champ-select window: `LcuClient` (1.0s) + `RuneWriter`
(1.0s) hit the SAME lockfile port, i.e. ~4 LCU GETs/sec against one port, each a
fresh TCP+TLS handshake. The relay + cache loops target the in-process :8889
server (cheap), not Riot's :2999.

## 2. Why per-call connections are the binding port-safety constraint

A fresh `https://127.0.0.1:<port>` call is a full TCP 3-way + TLS handshake, then
the socket lands in `TIME_WAIT` (~4 min default on Windows) after close. At ~4
LCU GETs/sec that is ~960 sockets accumulating per 4-min window before reuse -
fine at today's cadence, but it scales linearly with poll rate. The IO map
flagged this as the reason "tightening any loop without consolidating risks a
connection storm" (Findings B.1/B.2). Connection REUSE breaks that coupling:
with keep-alive, N reads/sec on one endpoint cost ONE long-lived socket, so cadence
and socket count decouple. That is lever L6.

## 3. Mechanisms shipped (`core/lcu_pool.py`, default-OFF)

- **L6 `HttpsConnectionPool`** - one keep-alive `http.client.HTTPSConnection` per
  `(host, port)`, reused under a per-key lock. `request()` reads the full body
  each call (keeps the socket reusable) and returns `(status, body)` or fail-soft
  `None`. A peer-closed kept-alive socket is transparently reconnected ONCE
  (two-attempt loop) so reuse never strands a caller on a dead socket. Distinct
  ports get distinct sockets; same port serializes on its lock (one socket, no
  interleave). Verify=off loopback SSL context matches every existing LCU reader.
- **L7 `MinIntervalGuard`** - a shared monotonic rate FLOOR keyed per endpoint.
  `ready(key)` is non-blocking and returns True at most once per `min_interval_s`;
  a loop that gets False skips its read this tick. One guard shared by several
  callers means none can independently push the effective rate past the floor.
- **`pool_enabled()`** - reads `RC_LCU_POOL` (default "0"). The live path stays
  byte-identical until a caller opts in; `get_shared_pool()` is lazy so the pool
  is never built unless enabled.

### Pilot

`game_reader/poller.py._lcu_get` (NON-frozen) routes through the shared pool when
`RC_LCU_POOL=1`, else the unchanged per-call urlopen path; a pooled `None` falls
through to the per-call read. Proves the seam on a non-frozen reader before E7
wires the frozen `lcu/lcu_client.py._request` onto the same pool.

## 4. L8 - :2999 direct-read hard floor (do NOT lower)

`vision_server/_relay._SELF_READ_MIN_INTERVAL_S = 1.5s` is the hard floor for
DIRECT reads of Riot's localhost :2999 (Findings B.3). The 0.5s `liveclient_cache`
loop is safe ONLY because it targets the in-process :8889 cache, never :2999.
Locked by a regression test (`tests/test_lcu_pool.py::RelaySelfReadFloorTests`)
so a future "speed-up" cannot silently drop it. If a tighter :2999 cadence ever
throws `UNEXPECTED_EOF_WHILE_READING`, check `netsh interface portproxy show all`
FIRST (memory `reference_iphlpsvc_portproxy_2999`) - that is a self-loop rule, not
a cadence bug.

## 5. No-fan-out-storm verification

- SSE faster ticks (P6.3 L4) add NO connections (push over one long-lived stream;
  8-subscriber cap unchanged).
- DS :8893 is shielded by the `_deterministic_coaching` 3.0s call TTL regardless
  of UI cadence.
- LCU cadence x socket count is decoupled by L6 (opt-in); L7 caps any consolidated
  reader's effective rate; L8 pins the only direct-Riot floor.

Net: the P6.2/P6.3 cadence tightening is port-safe, and the pooling seam is ready
for E7 to consolidate the frozen LCU client onto one socket.

## 6. Follow-ups (tracked elsewhere)

- **E7** - wire frozen `lcu/lcu_client.py._request` onto `HttpsConnectionPool`
  (operator-approved frozen edit) + ARAM bench-swap latency. The pilot here is the
  reference implementation.
- Live default-ON flip of `RC_LCU_POOL` is operator-gated (real-game socket
  observation) -> `docs/LIVE_GAME_GATED_SYNC.md`.
