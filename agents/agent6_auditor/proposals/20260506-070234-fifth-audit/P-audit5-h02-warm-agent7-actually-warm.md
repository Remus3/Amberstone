# P-audit5-h02 - `_warm_agent7_handle` must use the warm session

**Owner:** Agent 2
**Severity:** HIGH
**Bundle with:** P-audit5-h01

## Problem

`agents/supervisor.py:1811-1815` ignores `self._warm_agent7` and
always returns `spawn_ephemeral_llm("7", ...)`. Queue-dispatched
Agent 7 tasks pay full cold subprocess cost (~5 s, ~6× tokens) even
though the warm session is alive and primed (`:1599`, `:1842`,
`:1859`). Inline `/api/input` already uses the warm path correctly
at `:489-501` - the queue path is the only regression.

## Fix (unified diff sketch - pick one of the two)

### Option A - reuse `warm_spawn_factory`

```diff
--- a/agents/supervisor.py
+++ b/agents/supervisor.py
@@ -1811,7 +1811,15 @@ class Supervisor:
     def _warm_agent7_handle(self, task) -> dict:
-        if not self._warm_agent7_alive:
-            log.info("warming agent7 session for task %s", task.id)
-            self._warm_agent7_alive = True
-        return spawn_ephemeral_llm("7", task.id, task.op, task.payload)
+        if self._warm_agent7 is None:
+            return spawn_ephemeral_llm("7", task.id, task.op, task.payload)
+        if not self._warm_agent7_alive:
+            log.info("warming agent7 session for task %s", task.id)
+            self._warm_agent7_alive = True
+        spawn = warm_spawn_factory(self._warm_agent7)
+        try:
+            return spawn("7", task.id, task.op, task.payload)
+        except WarmSessionError as e:
+            log.warning("warm send failed, fallback ephemeral: %s", e)
+            return spawn_ephemeral_llm("7", task.id, task.op, task.payload)
```

### Option B - inline (no factory)

See `agents/agent7_context/warm_session.py:210-243` for the envelope
shape `warm_spawn_factory` produces; replicate inline if the import
graph is awkward.

## Test

- Synthetic agent="7" queue task → expect `substrate=warm_agent7_session`.
- Same task with `_warm_agent7=None` → expect fallback to
  `ephemeral_cli` substrate (preserves backward compat).
- Force `WarmSessionError` (mock SDK) → expect fallback path taken.
