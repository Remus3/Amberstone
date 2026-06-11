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
at >=95% success, dispatch these via the bridge per `[[reference_rc_peer_bridge]]`.

PREP STATE (item 199 update): the `tools/bridge_watcher_install.ps1` script
NOW exposes a native `-EnableLanes` parameter (landed item 189 Slice A under
explicit frozen-file grant; commit `93695ca`). The old "manual ps1 edit owed"
path is RETIRED. Peer installers can pull the latest install.ps1 from Legion
and re-run with `-EnableLanes read` to flip the scheduled task XML; no manual
file edit is required. The pin tests at
`tests/test_bridge_watcher_install_enable_lanes.py` lock that surface so the
recipe below stays invocable.

### 1. Game-PC enablement (3 steps)

a. From Game-PC, pull the latest installer from Legion's `/agent/` HTTP serve:

```
iwr -UseBasicParsing https://legion-rc:8888/agent/bridge_watcher_install.ps1 -OutFile "$env:TEMP\bridge_watcher_install.ps1"
```

b. Run the installer with `-EnableLanes read` (read lane first; `ops` lane is
the 2nd-stage promotion after 24h of clean read-lane samples):

```
powershell -ExecutionPolicy Bypass -File "$env:TEMP\bridge_watcher_install.ps1" -Node gamepc -EnableLanes read
```

c. Verify the scheduled task XML carries the flag (heartbeat JSON does not
currently surface `enabled_lanes`; that is a separate operator-gated extension
to `tools/bridge_watcher.py:_write_heartbeat` - see item 199 carry-forward).
Until then, verify via the scheduled-task Arguments string:

```
schtasks /Query /TN RC-BridgeWatcher-GamePC /XML | findstr "enable-auto-action-lanes"
```

Expected output line:

```
<Arguments>...bridge_watcher.py --node gamepc --bridge-url ... --poll 15 --enable-auto-action-lanes read</Arguments>
```

Operator can also use the bridge-dispatch helper (see below) to enqueue all
three steps as a single ops_request envelope.

### 2. Peer enablement (same 3 steps)

Same recipe with `-Node peer`. Peer RC bridge address is `<peer-tailnet-ip>`; per
`tools/PEER_ROADMAP_SUGGESTIONS.md:55`, Peer has its own `bridge_watcher_install.ps1`
clone at `C:\Peer-VIP\core\`. The peer should pull the latest install.ps1 from
Legion (URL above), then run with `-Node peer -EnableLanes read`.

### 3. Dispatch helper (item 199 Slice A)

`tools/bridge_dispatch_enable_lanes.py` builds an `ops_request` bridge task
envelope with the install URL + sha256 checksum + the lanes string, posts it
to the target peer via `bridge_cli task` (the same chokepoint
`bridge_post_result.py` uses for non-result envelopes). Operator runs:

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:\Riot Commander\tools\bridge_dispatch_enable_lanes.py" --target gamepc --lanes read
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:\Riot Commander\tools\bridge_dispatch_enable_lanes.py" --target peer --lanes read
```

Add `--dry-run` to see the envelope without POSTing. Add `--lanes read,ops`
once the 2nd-stage promotion gate clears. The script is idempotent: it checks
the dashboard's `/api/health/all` for the peer's current `enabled_lanes`
shape before posting and exits 0 with a `"already enabled"` note if no change
is needed (peer's heartbeat must expose the field for the idempotence check
to fire; until then the script logs a notice and always posts).

### 4. Verification curls

```
# Peer health: lanes should appear in heartbeat config once item-199-carry lands
curl -ks https://127.0.0.1:8888/api/health/all | jq '.peers.gamepc, .peers.peer'

# Direct peer probe
curl -k https://gamepc-rc:8893/bridge_watcher_health.json
curl -k https://peer-host:8888/api/bridge/watcher_health

# Direct task XML probe (peer-side, until heartbeat surfaces lanes)
schtasks /Query /TN RC-BridgeWatcher-GamePC /XML | findstr "enable-auto-action-lanes"
schtasks /Query /TN RC-BridgeWatcher-Peer /XML | findstr "enable-auto-action-lanes"
```

Expected post-flip:
- Scheduled task Arguments includes `--enable-auto-action-lanes read`
- `auto_actions_since_boot` increments as real envelopes match auto-* patterns
- `auto_ok_since_boot / (auto_ok + auto_err)` >= 0.95 sustained

### 5. Rollback

```
# Re-run installer WITHOUT -EnableLanes (default is empty -> no flag in args)
powershell -ExecutionPolicy Bypass -File "$env:TEMP\bridge_watcher_install.ps1" -Node gamepc
# Or set explicitly to disable on a still-installed task:
powershell -ExecutionPolicy Bypass -File "$env:TEMP\bridge_watcher_install.ps1" -Node gamepc -EnableLanes ""
```

The installer is idempotent (re-runs replace the scheduled task XML in place).
Mirror for Peer with `-Node peer`.

### 6. Promotion to `ops` lane

After 24h of clean read-lane samples with >=95% success on N>=20 per peer,
re-run step 1 with `-EnableLanes read,ops`. The dispatch helper accepts
`--lanes read,ops`.

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
