# Auto-Action Lanes Enablement Gate Probe

Probed 2026-05-25 by Slice G of item 188 parallel headless drain.
Mirrors item 187 Slice F audit-only verdict; deepens with peer-state evidence
and ready-to-ship enablement recipe.

ROADMAP entry: L125 - "Game-PC + Peer auto-action lanes - watchers installed
but `--enable-auto-action-lanes` is OFF. Enable when success rate is proven."

---

## Verdict

**DEFERRED.** Gate NOT cleared.

Wait for: real cross-peer auto-action samples to accumulate (N>=50, success
>=95%). Current state: insufficient sample size + Legion watcher is itself
stale-dead since 2026-05-23.

---

## Numbers

| Metric | Value | Gate Threshold | Verdict |
|---|---|---|---|
| Total auto-action samples (ops/runtime/bridge_action_history.db) | 2 | >= 50 | FAIL |
| Success count | 2 | - | - |
| Failure count | 0 | - | - |
| Success rate | 100% (2/2) | >= 95% | PASS but N too small |
| Sample provenance | both `legion-self-test` | real cross-peer | FAIL |
| Days since last sample | 22 | < 7 | FAIL |
| Cadence since 2026-05-03 | zero | non-zero | FAIL |

Sample window: 2026-05-03 13:03:01 UTC to 2026-05-03 13:03:18 UTC (17 seconds,
both Phase 4 cache self-tests).

ETA to gate: indeterminate at current zero-cadence. Even at peak observed
historical cadence (~50 cross-peer envelopes / week), N>=50 takes ~1 week of
sustained real traffic; this would also need active operator use of bridge
auto-action verbs which is not happening today.

---

## Live peer state (probed 2026-05-25 ~15:32 local)

| Node | Watcher PID | Alive | Lanes Flag | auto_ok_since_boot | auto_err |
|---|---|---|---|---|---|
| Legion | 6204 (stale) | NO - heartbeat age 42h | `read,ops` (per `ops/RC-BridgeWatcher.xml:39`) | 0 | 0 |
| Game-PC | 7024 | YES | OFF (default per install.ps1:200) | 0 | 0 |
| Peer | 11832 | YES | OFF (default per install.ps1:200) | 0 | 0 |

Legion's task scheduler reports `LastTaskResult: 267014 = 0x4137E "task is
currently running"` for `RC-BridgeWatcher`, but `Get-Process -Id 6204` errors
(dead). PID file at `ops/runtime/bridge_watcher.pid` is stale.

Probe: `curl -ks https://127.0.0.1:8888/api/health/all | jq .peers`.

---

## Flag consumer

- File: `tools/bridge_watcher.py:1083` argparse definition
- File: `tools/bridge_watcher.py:1148` consumer; populates `enabled_lanes: set`
- Threaded into `_run()` via `run_kwargs["enabled_lanes"]` at line 1162
- Default: empty string -> empty set -> classifier never returns `auto-*` lanes
- Legion baked-in via `ops/RC-BridgeWatcher.xml:39`: `--enable-auto-action-lanes read,ops`
- Game-PC + Peer install via `tools/bridge_watcher_install.ps1:200` does NOT
  pass the flag -> daemons run with `enabled_lanes={}` -> auto-action is off

---

## Ready-to-ship enablement recipe (do NOT execute until gate clears)

When Slice F (or a future audit) reports gate CLEARED with N>=50 real samples
at >=95% success, dispatch these via the bridge per `[[reference_rc_peer_bridge]]`:

### 1. Game-PC enablement

Bridge task to Game-PC: stop the running watcher, re-register the scheduled
task with `--enable-auto-action-lanes read` (read lane only first; ops lane
is the 2nd-stage promotion after 24h of clean read-lane samples).

```
py "C:\Riot Commander\tools\bridge_post_result.py" --source legion --reply-to gamepc --summary "enable auto-action-lanes read" --body '{"prompt": "Re-register RC-BridgeWatcher-GamePC with --enable-auto-action-lanes read. Stop current task, re-run bridge_watcher_install.ps1 with -Node gamepc -EnableLanes read, verify heartbeat reports lanes=[read]"}'
```

(NOTE: `bridge_watcher_install.ps1` does NOT yet expose an `-EnableLanes`
parameter - line 200 hardcodes the args list. A 1-line install script edit
to thread `--enable-auto-action-lanes $EnableLanes` is owed as a prep step
before the flip. Operator-gated; ~5 LOC.)

### 2. Peer enablement (same recipe)

Same bridge task to Peer with `--reply-to peer`. Peer RC bridge address is
`<peer-tailnet-ip>`; per `tools/PEER_ROADMAP_SUGGESTIONS.md:55`, Peer has its own
`bridge_watcher_install.ps1` clone at `C:\Peer-VIP\core\` and the operator
flips the Peer scheduled task XML directly.

### 3. Verification curls

```
# Peer health: lanes should appear in heartbeat config
curl -ks https://127.0.0.1:8888/api/health/all | jq '.peers.gamepc, .peers.peer'

# Direct peer probe
curl -k https://gamepc-rc:8893/bridge_watcher_health.json
curl -k https://peer-host:8888/api/bridge/watcher_health
```

Expected post-flip:
- `auto_actions_since_boot` increments as real envelopes match auto-* patterns
- `auto_ok_since_boot / (auto_ok + auto_err)` >= 0.95 sustained

### 4. Rollback

```
# Stop the task, re-register without the flag
schtasks /End /TN RC-BridgeWatcher-GamePC
schtasks /Change /TN RC-BridgeWatcher-GamePC /TR "<path-to-pythonw>:<install-dir>\bridge_watcher.py --node gamepc --poll 15"
schtasks /Run /TN RC-BridgeWatcher-GamePC
```

(Mirror for Peer with `-Peer` suffix and Peer paths.)

### 5. Promotion to `ops` lane

After 24h of clean read-lane samples with >=95% success on N>=20 per peer,
re-dispatch the bridge task with `--enable-auto-action-lanes read,ops`.

---

## Cross-checks for next audit pass

1. **Legion watcher stale**: PID 6204 died 2026-05-23. Heartbeat stale ~42h.
   `RC-BridgeWatcher` task shows "still running" but process is gone. This
   blocks any auto-action regardless of peer state. Repro: ` schtasks /End /TN RC-BridgeWatcher; schtasks /Run /TN RC-BridgeWatcher`. **NOT
   this slice's scope** (frozen-file-adjacent + cross-cutting; operator).
2. **Game-PC bridge red**: `gamepc_result_age_s = 412213` (~4.8 days). No
   Game-PC -> Legion bridge results since 2026-05-20. The Game-PC daemon is
   alive but not posting results - likely related to (1).
3. **Bridge daemon at Legion pid 2216** is healthy (invocations_since_boot=0,
   age 4.2s). It is the cron-poll receiver for Game-PC pulls, not the
   auto-action runner.

---

## Memory anchor

Per `[[reference_rc_peer_bridge]]`: `core.bridge.send()` only routes to Peer.
Game-PC bridge tasks need direct POST to Legion local `/api/bridge` with
explicit `target=gamepc id` (Game-PC polls Legion). Recipe above respects
that asymmetry via `bridge_post_result.py --reply-to <peer>`.
