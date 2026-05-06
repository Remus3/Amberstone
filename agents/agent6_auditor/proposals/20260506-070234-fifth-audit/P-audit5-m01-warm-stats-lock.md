# P-audit5-m01 — `WarmAgent7Session.stats()` must hold `_lock`

**Owner:** Agent 2
**Severity:** MEDIUM

## Problem

`agents/agent7_context/warm_session.py:194-207` reads `_client`,
`_last_activity`, `_messages`, `_total_*` outside `_lock`. All
mutators (`send`, `_check_idle`, `close`) hold the lock. The
watchdog at `agents/supervisor.py:1683-1702` polls `stats()` and
makes lifecycle decisions on the result; an inconsistent snapshot
can briefly contradict its own invariant
(`warm=True` ⇒ `_last_activity > 0`).

## Fix (unified diff)

```diff
--- a/agents/agent7_context/warm_session.py
+++ b/agents/agent7_context/warm_session.py
@@ -193,17 +193,18 @@ class WarmAgent7Session:
     # ---- introspection ------------------------------------------------
     def stats(self) -> dict[str, Any]:
-        return {
-            "warm": self._client is not None and self._last_activity > 0.0,
-            "model": self._model,
-            "history_len": len(self._messages),
-            "turns": self._total_sent,
-            "total_input_tokens": self._total_input_tokens,
-            "total_output_tokens": self._total_output_tokens,
-            "idle_sec": (
-                round(time.monotonic() - self._last_activity, 1)
-                if self._last_activity > 0 else None
-            ),
-            "idle_timeout_sec": self._idle_timeout,
-        }
+        with self._lock:
+            return {
+                "warm": self._client is not None and self._last_activity > 0.0,
+                "model": self._model,
+                "history_len": len(self._messages),
+                "turns": self._total_sent,
+                "total_input_tokens": self._total_input_tokens,
+                "total_output_tokens": self._total_output_tokens,
+                "idle_sec": (
+                    round(time.monotonic() - self._last_activity, 1)
+                    if self._last_activity > 0 else None
+                ),
+                "idle_timeout_sec": self._idle_timeout,
+            }
```

## Test

- Spawn 2 threads: one calls `send()` in a tight loop (mocked SDK
  with 50ms sleep), one calls `stats()` in a tight loop. Assert no
  `stats()` snapshot ever has `warm=True` with `idle_sec=None`, and
  no snapshot ever has `warm=False` with `idle_sec` a small positive
  number.
