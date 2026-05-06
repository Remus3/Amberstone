# P-audit5-h01 — initialize `_warm_agent7_alive` in Supervisor.__init__

**Owner:** Agent 2
**Severity:** HIGH
**Bundle with:** P-audit5-h02 (same area, same PR)

## Problem

`agents/supervisor.py:1812` reads `self._warm_agent7_alive` but the
attribute is never assigned anywhere in `__init__` (`:1535-1558`).
Every queue-dispatched Agent 7 task hits `_warm_agent7_handle()` and
raises `AttributeError`, which the dispatch loop catches at
`:1740-1742` and converts into a `scheduler.fail()`.

## Fix (unified diff)

```diff
--- a/agents/supervisor.py
+++ b/agents/supervisor.py
@@ -1540,6 +1540,7 @@ class Supervisor:
         self._agent0: Evaluator | None = None
         self._file_ingest: FileIngest | None = None
         self._warm_agent7: WarmAgent7Session | None = None
+        self._warm_agent7_alive: bool = False
         self.cross_machine_enabled: bool = True
```

## Test

After H-02 lands, file a synthetic agent="7" task via the scheduler
and assert `result["substrate"] == "warm_agent7_session"` and no
exception was logged.
