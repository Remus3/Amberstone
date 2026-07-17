# L-02: lockfile.<pid>.tmp orphan cleanup

**Origin:** agent6 thirteenth audit (report
`20260712-171313-thirteenth-audit-phase3.md`).
**Severity:** low.
**Owner:** Agent 2 (backend).
**File touched:** `agents/_supervisor_common.py` (NOT frozen).

## What

`_atomic_write_json` writes `target.with_name(f"{target.name}.{os.getpid()}.tmp")`
then `os.replace(tmp, target)`. On `os.replace` failure (WinError 5
transient per `reference_os_replace_winerror5`; also SIGTERM /
power loss between the two lines) the tmp is orphaned. Observed
5 orphans in `agents/state/` across 2026-07-08 -> 2026-07-11.

## Contract

1. Wrap the `os.replace` in a 3-attempt `PermissionError` retry
   with 60ms backoff (mirror the existing pattern in
   `dashboard/routes_vision_calibrator.py`).
2. `try/finally: tmp.unlink(missing_ok=True)` around the replace
   so a final failure still cleans up.
3. Startup sweeper: in `acquire_lock()`, after
   `STATE_DIR.mkdir(...)`, glob `lockfile.*.tmp`, parse the
   `<pid>` segment, call `_pid_alive(pid)`, `unlink(missing_ok=True)`
   if dead.

## Unified diff (indicative - reviewer confirms exact hunk)

```
--- a/agents/_supervisor_common.py
+++ b/agents/_supervisor_common.py
@@ -197,13 +197,26 @@
 # -------- PID lock ----------------------------------------------------

 def _atomic_write_json(target: Path, obj: object) -> None:
-    """Write ``obj`` as JSON to ``target`` atomically (CLAUDE.md hard rule).
-    ...
+    """Write ``obj`` as JSON to ``target`` atomically (CLAUDE.md hard rule).
+
+    Audit L-02 (2026-07-12): retry ``os.replace`` on transient
+    Windows PermissionError (reference_os_replace_winerror5), and
+    always clean up the ``.tmp`` sibling on any final failure so a
+    crash / WinError 5 never orphans a per-PID temp file into
+    ``agents/state/``.
     """
     target.parent.mkdir(parents=True, exist_ok=True)
     tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
-    tmp.write_text(json.dumps(obj), encoding="utf-8")
-    os.replace(tmp, target)
+    tmp.write_text(json.dumps(obj), encoding="utf-8")
+    try:
+        for attempt in range(3):
+            try:
+                os.replace(tmp, target)
+                return
+            except PermissionError:
+                if attempt == 2:
+                    raise
+                time.sleep(0.06)
+    finally:
+        try:
+            tmp.unlink(missing_ok=True)
+        except OSError:
+            pass
@@ def acquire_lock() -> bool:
     STATE_DIR.mkdir(parents=True, exist_ok=True)
+    _reap_orphan_lockfile_tmps()
     sentinel = STATE_DIR / "lockfile.sentinel"
@@
+def _reap_orphan_lockfile_tmps() -> None:
+    """Delete lockfile.<pid>.tmp files where <pid> is not a live process."""
+    for p in STATE_DIR.glob("lockfile.*.tmp"):
+        try:
+            pid = int(p.name.rsplit(".", 2)[-2])
+        except (ValueError, IndexError):
+            continue
+        if not _pid_alive(pid):
+            try:
+                p.unlink(missing_ok=True)
+            except OSError:
+                pass
```

## Test plan

- New test in `tests/test_supervisor_common.py` (or nearest):
  1. `test_atomic_write_json_retries_permissionerror` - monkeypatch
     `os.replace` to raise 2x then succeed; assert `target` written +
     no `.tmp` sibling remains.
  2. `test_atomic_write_json_final_failure_cleans_tmp` - monkeypatch
     `os.replace` to always raise; assert `PermissionError` bubbles +
     no `.tmp` remains.
  3. `test_reap_orphan_lockfile_tmps_dead_pid` - drop a
     `lockfile.99999.tmp` (dead PID) and a `lockfile.<mypid>.tmp`
     (self, alive), call `_reap_orphan_lockfile_tmps`, assert the
     dead-pid file is gone and the live-pid file is preserved.

## Autonomous cleanup after landing

The new `_reap_orphan_lockfile_tmps()` will clear the existing
5 orphans on the next supervisor `acquire_lock()`. No manual
`rm` needed - just land the fix and bounce the supervisor.
