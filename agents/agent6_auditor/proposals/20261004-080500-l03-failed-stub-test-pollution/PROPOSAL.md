# Proposal L-03 - agent6 FAILED-stub writer: test pollution + unsanitised task_id

**Filed:** 2026-10-04 by agent6 during `t-508c0d9827ab` full-audit-pass
**Owner:** Agent 1 (queue) -> Agent 2 (backend) + Agent 3 (test)
**Severity:** low

## What

1. `agents/_supervisor_ephemeral.py:182` hardcodes
   `reports_dir = _PROJECT_ROOT / "agents" / "agent6_auditor" / "reports"`.
   `agents/agent3_testing/suite/test_supervisor_stub.py:48`
   (`test_nonzero_exit_raises_spawn_failed`, task id `t-exitfail`, op `demo`)
   drives the non-zero-exit path without redirecting that directory, so
   every suite run writes a real stub into the live reports dir. Measured on
   disk: `*-FAILED-t-exitfail.md` at 20260929-234606, -235112, -235725,
   20261003-025359; also `-tT2.md`, `-tINJ.md` from sibling tests.
   The files are gitignored (`.gitignore:364`) so CI is unaffected, but the
   operator-facing failure signal is drowned: a real agent6 failure is
   indistinguishable from test noise when listing the directory.
2. `task_id` is interpolated into the filename unsanitised
   (`f"{ts_file}-FAILED-{task_id}.md"`). Task ids are scheduler-minted
   today (`t-<hex>`), so not exploitable now, but a `../` or `:` in a
   user_override-filed id would escape the directory or fail on NTFS.

## Fix (diff sketch)

```diff
--- a/agents/_supervisor_ephemeral.py
+++ b/agents/_supervisor_ephemeral.py
@@
+import re
+
+# Module attr so tests can monkeypatch it (L-03).
+AGENT6_REPORTS_DIR = _PROJECT_ROOT / "agents" / "agent6_auditor" / "reports"
+_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")
@@ def _write_agent6_failure_stub(
-    reports_dir = _PROJECT_ROOT / "agents" / "agent6_auditor" / "reports"
+    reports_dir = AGENT6_REPORTS_DIR
@@
-        stub_path = reports_dir / f"{ts_file}-FAILED-{task_id}.md"
+        safe_id = _SAFE_ID.sub("_", task_id)[:64] or "unknown"
+        stub_path = reports_dir / f"{ts_file}-FAILED-{safe_id}.md"
```

```diff
--- a/agents/agent3_testing/suite/conftest.py
+++ b/agents/agent3_testing/suite/conftest.py
+@pytest.fixture(autouse=True)
+def _isolate_agent6_reports(tmp_path, monkeypatch):
+    from agents import _supervisor_ephemeral as se
+    monkeypatch.setattr(se, "AGENT6_REPORTS_DIR", tmp_path / "agent6_reports")
```

Tests: (a) after `test_nonzero_exit_raises_spawn_failed`, the live reports
dir gains no file (digest before/after); (b) a task id `../x:y` yields a
stub inside `AGENT6_REPORTS_DIR` named `...-FAILED-.._x_y.md`.

Backfill: Recycle-Bin (not unlink) the four `-FAILED-t-exitfail.md`,
`-FAILED-tT2.md`, `-FAILED-tINJ.md` fixture stubs after the fix lands.
