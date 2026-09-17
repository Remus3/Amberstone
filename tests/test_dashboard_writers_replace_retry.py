"""Lane 8 cycle 19: dashboard/_writers.atomic_write_json needs the WinError-5 retry.

`dashboard/_writers.py` opens with the CLAUDE.md hard rule in its own docstring
- "Atomic writes only ... Overlays poll mid-write" - and then called a bare
`tmp.replace(p)`. On Windows `os.replace` transiently raises
`PermissionError` (WinError 5) when a reader holds the destination open, and
these files are polled BY DESIGN, so the contention is routine rather than
exceptional.

MEASURED on this machine during the cycle-19 audit: a plain
`open(target, "r", encoding="utf-8")` held by a reader was sufficient to make
`tmp.replace(p)` raise `PermissionError [WinError 5] Access is denied`, and an
orphan `coaching_data.json.tmp` was left behind. The operator-visible symptom is
in the audited module: the dashboard Refresh button
(`routes_state._serve_command_post`) returns `500 {"error":"command_failed"}`
and does nothing, and `/api/input` returns `500 {"error":"write_failed"}`.

`core/polled_json.py:39-48 _replace_with_retry` is the in-tree answer (bounded
backoff, ~275 ms worst case, then re-raise). This module now reuses that exact
helper rather than re-rolling the backoff table, so the two cannot drift.

Serialization is deliberately NOT delegated to `polled_json.atomic_write_json`:
that helper passes `ensure_ascii=False`, which would change the bytes written
for any non-ASCII coaching text. Only the replace step is shared.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import _writers  # noqa: E402
from tests._replace_faults import scoped_fs_fault  # noqa: E402


def _always_denied(real, src, dst, *a, **kw):
    raise PermissionError(13, "Access is denied")


class AtomicWriteRetryTests(unittest.TestCase):

    def test_a_transient_winerror5_is_retried_not_surfaced(self):
        """Two transient PermissionErrors then success = the write succeeds."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            def flaky(real, src, dst, *a, **kw):
                if rec.attempts <= 2:
                    raise PermissionError(13, "Access is denied")
                return real(src, dst, *a, **kw)

            # RM-464: "core.polled_json.os.replace" IS os.replace process-wide;
            # the fault is scoped to this temp dir with an armed outside control.
            with mock.patch.object(_writers, "APP_DIR", tmp), \
                 scoped_fs_fault("replace", tmp, flaky) as rec:
                _writers.atomic_write_json("probe.json", {"a": 1})

            self.assertEqual(rec.attempts, 3, "expected two retries then success")
            written = json.loads((tmp / "probe.json").read_text(encoding="utf-8"))
            self.assertEqual(written, {"a": 1})

    def test_a_persistent_winerror5_still_raises(self):
        """The retry must be BOUNDED - an unbounded loop would hang a thread."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(_writers, "APP_DIR", tmp), \
                 scoped_fs_fault("replace", tmp, _always_denied):
                with self.assertRaises(PermissionError):
                    _writers.atomic_write_json("probe.json", {"a": 1})

    def test_serialization_is_byte_identical_to_the_previous_writer(self):
        """The fix must change the replace step ONLY.

        `core.polled_json.atomic_write_json` uses ensure_ascii=False; delegating
        wholesale would silently change the bytes for non-ASCII content, so this
        pins the existing json.dumps(..., indent=2) form.
        """
        import tempfile
        payload = {"pregame": "Caitlyn vs Kai'Sa", "n": 2, "nested": {"k": [1, 2]}}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(_writers, "APP_DIR", tmp):
                _writers.atomic_write_json("probe.json", payload)
            on_disk = (tmp / "probe.json").read_text(encoding="utf-8")
        self.assertEqual(on_disk, json.dumps(payload, indent=2))

    def test_no_orphan_tmp_is_left_when_the_replace_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(_writers, "APP_DIR", tmp), \
                 scoped_fs_fault("replace", tmp, _always_denied):
                with self.assertRaises(PermissionError):
                    _writers.atomic_write_json("probe.json", {"a": 1})
            leftovers = list(tmp.glob("*.tmp"))
        self.assertEqual(leftovers, [], f"orphan tmp left behind: {leftovers}")


if __name__ == "__main__":
    unittest.main()
