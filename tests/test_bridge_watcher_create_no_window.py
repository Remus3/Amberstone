"""Drift guard: spawn sites in bridge_watcher.py + bridge_watcher_actions.py
MUST pass creationflags=subprocess.CREATE_NO_WINDOW (on Windows) when calling
claude.cmd or any .cmd shim. Without it, the pythonw parent has no console so
spawning a .cmd allocates a new visible cmd.exe window for the duration of
the call. This caused operator-visible cmd flashes on Legion every time the
escalation push_notif fired (item 208 hot-fix 2026-05-27).

Mirrors the flag pattern at tools/legion_bridge_daemon.py:212.
"""
from __future__ import annotations

import ast
import pathlib
import sys
import unittest


_ROOT = pathlib.Path(__file__).resolve().parent.parent
_WATCHER = _ROOT / "tools" / "bridge_watcher.py"
_ACTIONS = _ROOT / "tools" / "bridge_watcher_actions.py"


def _spawn_calls_in_function(src: str, func_name: str) -> list[ast.Call]:
    """Return every subprocess.run/Popen call inside the named function."""
    tree = ast.parse(src)
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr in {"run", "Popen", "call", "check_output"}
                        and isinstance(sub.func.value, ast.Name)
                        and sub.func.value.id == "subprocess"):
                    out.append(sub)
    return out


class PushNotifSpawnCreationFlagsTests(unittest.TestCase):
    """tools/bridge_watcher.py::_send_push_notification - non-frozen file."""

    def test_send_push_notification_passes_creationflags(self) -> None:
        src = _WATCHER.read_text(encoding="utf-8")
        calls = _spawn_calls_in_function(src, "_send_push_notification")
        self.assertEqual(len(calls), 1,
                         "expected exactly 1 subprocess spawn in _send_push_notification")
        kwargs = [k.arg for k in calls[0].keywords]
        self.assertIn("creationflags", kwargs,
                      "push_notif spawn MUST pass creationflags - else cmd.exe "
                      "window flashes on Windows each escalation (item 208)")


class ActionsRunSubprocessCreationFlagsTests(unittest.TestCase):
    """tools/bridge_watcher_actions.py::_run_subprocess - frozen file.

    Sibling fix to the push_notif site. The watcher auto-action lane spawns
    claude.cmd here too; same window-flash class of bug.
    """

    def test_run_subprocess_passes_creationflags(self) -> None:
        src = _ACTIONS.read_text(encoding="utf-8")
        calls = _spawn_calls_in_function(src, "_run_subprocess")
        self.assertEqual(len(calls), 1,
                         "expected exactly 1 subprocess spawn in _run_subprocess")
        kwargs = [k.arg for k in calls[0].keywords]
        self.assertIn("creationflags", kwargs,
                      "_run_subprocess spawn MUST pass creationflags - else "
                      "cmd.exe window flashes on Windows each auto-action (item 208 sibling)")


class AsciiHygieneTests(unittest.TestCase):
    def test_no_non_ascii_in_new_test_file(self) -> None:
        src = pathlib.Path(__file__).read_bytes()
        for i, b in enumerate(src):
            if b > 0x7F:
                self.fail(f"non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()
