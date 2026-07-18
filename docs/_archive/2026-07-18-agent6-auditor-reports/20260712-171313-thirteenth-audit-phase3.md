# Agent 6 - Thirteenth Audit (Phase 3 repo pass)

- **Date:** 2026-07-12 17:13 UTC (cron `t-d51f34f8a017`)
- **Auditor:** Agent 6 (Opus 4.7, ephemeral, $3.00 spawn budget)
- **Scope:** Recency pass over 7-day window since audit-12
  (2026-07-05 -> 2026-07-12). ~40 commits: item-1 rune-follows-build
  Phase 1-6 (SHIPPED + LIVE-VALIDATED per ledger 867), R108-R110 DS
  scorer waves (ENGINE 1.181.0 -> 1.203.0, 3 bumps), Lane E CV atlas
  flip-readiness validator, ARAM Mayhem augment-reco fix
  (67519018 `is_augment_select` alias), Terminus ranged-only melee
  gate (d39d50f5), overlay HUD scale-drag clamp + poll-timeout raise
  + DS owned-items read, minimap_dots off /api/state hot path,
  TTS voice default OFF.
- **Follows:** `20260705-201555-twelfth-audit-phase3.md`.

## Closure verification - audit-12 findings

### L-01 vision_profiles.save_profile base validation - **CLOSED**

Task `t-4802b906f485` completed 2026-07-06 00:33 UTC by Agent 2
(commit c2fdf13d). `core/vision_profiles.py` gained
`validate_base()` + `_BASE_MAX=10000`; `_save_profile_from_body`
in `dashboard/routes_vision_calibrator.py` returns 400 pre-save
on any malformed base; `tests/test_vision_calibrator_profile.py`
gained 6 new `BaseValidationTests` cases (None, `[0,0]`, wrong
length, string coord, negative, valid 200 regression) - 18/18
pass. Contract from audit-12 delivered as specified.

## Live-state snapshot

- `agents/state/resolved_decisions.json`: version phase3-1.1,
  locked_at 2026-06-28, **26 decisions**. Unchanged since
  audit-12; no new operator decisions in the last 7 days that
  would need a d027+ - all 40 commits fit inside existing
  d001-d026 envelopes (rune-follows-build is item-1 tail per
  memory `project_overlay_item1_rune_follows_build`, not a
  framework decision).
- Daemon Slayer: ENGINE 1.181.0 -> 1.203.0 (3 bumps in 7 days;
  R108 general %DR, R109 item HSP ability-amp, R110 item low-HP
  magic/true amp). Cadence continues to validate d023 "live truth
  = /health" - no stale-engine leak on any spot-check.
- No red audit runs in `last_outcomes` (t-9061a61f1ef1 remains
  the only red at 27 days old). Green-rollup pattern still
  correct.

## New findings

### L-02 Orphaned `lockfile.<pid>.tmp` files in `agents/state/` - **low, propose-and-queue**

- **Location:** `agents/_supervisor_common.py:199-213`
  (`_atomic_write_json`), consumed by `acquire_lock()` at
  `:259` and `refresh_lock()` at `:336`.
- **Observed evidence (2026-07-12 17:12 UTC):**
  ```
  agents/state/lockfile.5572.tmp   Jul  9 01:26   136 B
  agents/state/lockfile.10124.tmp  Jul  9 03:56   137 B
  agents/state/lockfile.13064.tmp  Jul  9 09:58   137 B
  agents/state/lockfile.19784.tmp  Jul  8 10:05   137 B
  agents/state/lockfile.9544.tmp   Jul 11 22:11   136 B
  ```
  5 orphan `.tmp` files across a 4-day window, none matching a
  live PID (supervisor is pid 25408 per `ops/runtime/health.json`
  spot check pattern).
- **What's wrong:** The atomic dance at line 211-213 is:
  ```python
  tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
  tmp.write_text(json.dumps(obj), encoding="utf-8")
  os.replace(tmp, target)
  ```
  If `os.replace` raises (documented flake:
  `reference_os_replace_winerror5` - transient WinError 5 under
  concurrent read; also mid-process SIGTERM / power loss / disk
  contention), the tmp is orphaned. There is no `try/finally`,
  no `missing_ok` unlink, and no startup sweeper to reap
  `lockfile.*.tmp` where `<pid>` is dead.
- **Why it is wrong:** The frozen `_Phase3Watcher` in
  `ops/rc_supervisor.py` reads `LOCKFILE` on every cycle. A pid
  suffix that is not the live pid clutters the state dir but is
  harmless today - **however**, the pattern is contract-fragile:
  the same `_atomic_write_json` is called from `refresh_lock()`
  every heartbeat. Under sustained WinError5 conditions the
  state dir grows unbounded, `ls`/`Get-ChildItem` walks get
  slower, and any future consumer that greps `lockfile.*` (e.g.
  a health probe listing recent write attempts) will pick up
  stale entries. Also violates the CLAUDE.md atomic-write
  contract of "clean up after yourself" (implicit but the
  existing `dashboard/routes_vision_calibrator.py` seam does
  retry + unlink on WinError5 - the calibrator surface got the
  hardening, the supervisor lockfile did not).
- **Concrete fix (proposal):**
  1. Wrap the `os.replace` in the same 3-attempt PermissionError
     retry used at `dashboard/routes_vision_calibrator.py`
     (60ms backoff between tries).
  2. Add a `try/finally: tmp.unlink(missing_ok=True)` around the
     replace so any final failure still cleans up.
  3. Add a startup sweeper in `acquire_lock()`: glob
     `STATE_DIR / "lockfile.*.tmp"`, parse the pid, `_pid_alive(pid)`
     check, `unlink(missing_ok=True)` if dead. Same-file-tree
     safe because the sentinel + real lockfile are separate
     paths (`lockfile.sentinel` and `lockfile`; `.tmp` files
     never collide with either).
  4. One-shot cleanup of the 5 existing orphans by the same
     sweeper on first boot after the fix lands.
- **Autonomous authority:** NO -
  `agents/_supervisor_common.py` is outside the charter's
  autonomous-edit scope (blocklist.json / safeguards / source_quality
  / rotating-log / firewall-adjacent ops). Filed as a proposal
  for Agent 2 (backend, supervisor plumbing owner).
- **Fix action:** proposal at
  `agents/agent6_auditor/proposals/20260712-171313-l02-lockfile-tmp-leak/`
  with the unified diff + test plan; task filed to Agent 1
  queue for Agent 2.

### I-04 `data.setdefault("type", ...)` on ingest mutates caller frame - **info, no action**

`agents/agent2_backend/ws_server.py:145-149` mutates the parsed
`data` dict from `json.loads(raw)` in place with
`data.setdefault("type", ...)` + `data["ingested_at"] = ...`
before broadcasting. Since `json.loads` returns a fresh dict per
frame and no other reference is retained, this is safe. Flagging
for context only in case a future refactor reuses the parsed
frame across handlers - the mutation would then leak the
`ingested_at` field back upstream. Not a bug today.

### I-05 SMB push deadcode still preserved as unreachable - **info, no action**

Spot-check confirms `agents/agent2_backend/smb_push.py` still
guards per d026: `share_reachable()` at :73 hard-False;
`push()` at :146 and `trigger_forwarder_restart()` at :212 both
raise `RuntimeError(_RETIRED_MSG)` before any live filesystem
touch. No live import in the runtime tree. The deferred
single-swing cleanup remains queued per operator decision;
NOT re-escalated this pass.

## Follow-up tasks filed to Agent 1

- **L-02** -> task **t-efda5d578ead** (owner Agent 2, priority 200,
  op `implement-l02-lockfile-tmp-leak`, status READY). Proposal directory
  `agents/agent6_auditor/proposals/20260712-171313-l02-lockfile-tmp-leak/`
  carries the unified diff + test plan.

## Summary

- Audit-12's sole L-01 finding closed by c2fdf13d.
- One new low-severity resource-leak finding on the supervisor
  atomic-write path, proposal filed.
- No critical / high / medium findings this pass.
- 26 decisions in `resolved_decisions.json` still cover every
  operator-decided settled topic; no d027+ needed for the last
  7 days of commits.
- Agent 6 status: green.
