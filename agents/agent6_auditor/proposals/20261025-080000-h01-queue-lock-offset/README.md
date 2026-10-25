# h01 - task_queue.jsonl cross-process lock does not exclude (high)

Filed by Agent 6 full audit pass t-02760f99d1a0 (2026-10-25). Owner: Agent 2.

## Defect
agents/agent1_lead/scheduler.py:_lock_file_exclusive calls
msvcrt.locking(f.fileno(), LK_NBLCK, 1), which locks ONE byte at the
CURRENT file position. _append_log opens with "a" (tell() == EOF) and
compact() opens with "r+" (tell() == 0). The two lock different bytes,
so they never exclude each other; two appenders also lock different
bytes once the file has grown between their opens.

Measured 2026-10-25 (probe in $TEMP, msvcrt): handle A opened "a" on a
100-byte file locks at offset 100; handle B opened "r+" locks offset 0
and the second LK_NBLCK SUCCEEDS -> no mutual exclusion.

Writers in separate processes or separate Scheduler instances (each has
its own RLock): agents/supervisor.py:328, agents/agent7_context/
input_parser.py:118 and ui_feedback.py:106 (default Scheduler() when none
injected), ops/phase3_file_audit.py:90, scheduler.py __main__.

Impact: compact() does read -> truncate -> write in place; an append from
another process landing between the read and the truncate is lost, or
lands mid-rewrite and interleaves. Also: after 5 s of contention
_lock_file_exclusive "proceeds unlocked", which for compact() means an
unlocked truncate of the live queue. compact() is also not atomic
(no tmp -> os.replace), so a crash mid-write loses the queue.

## Fix (sketch)
```diff
-    @staticmethod
-    def _lock_file_exclusive(f: Any) -> None:
+    @staticmethod
+    def _lock_file_exclusive(f: Any) -> bool:
         """Block on a cross-process exclusive lock with a retry budget."""
+        # msvcrt locks bytes at the CURRENT position; pin every holder to
+        # offset 0 so "a" and "r+" handles contend on the same byte.
+        pos = f.tell()
+        f.seek(0)
         ...
-                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
+                    try:
+                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
+                    finally:
+                        f.seek(pos)
         ...
-                    logger.error("append lock wait exceeded %ss - proceeding unlocked", ...)
-                    return
+                    logger.error("queue lock wait exceeded %ss", ...)
+                    return False
```
_unlock_file must seek(0) before LK_UNLCK the same way. compact() must
skip (return (0, 0)) when the lock was not acquired. Writes through an
"a" handle still go to EOF (O_APPEND) after the seek. Simpler
alternative: lock a dedicated sidecar `task_queue.jsonl.lock` at offset 0
for both paths.

## Tests (TDD first)
- two processes (multiprocessing): A holds _append_log lock, B's
  compact() must block / skip, not acquire.
- compact() returns (0, 0) and leaves the file byte-identical when the
  lock cannot be acquired within the budget.
