"""Overlay drag pointer-listener leak guard (source-parsing).

WHY a Python guard and not a .test.mjs: there is no JS-execution harness for the
overlay in this repo (no jsdom, no node subprocess, no .test.mjs for
web/js/lib/overlay_layout.js), so the repo standard - see
tests/test_overlay_default_layout_collision.py - is to read the module source and
pin the invariant structurally.

WHY it exists (RM-126). _placeAll re-runs on every repaint and calls
_makeHandle(el, w) per widget. _makeHandle early-returns only when a .ovx-handle
CHILD exists, so a renderer that rebuilds a widget body (replaceWith /
innerHTML) drops the handle, the guard passes, and everything below re-runs on
the SAME PERSISTENT el: _installDrag binds pointermove/pointerup/pointercancel
on el, and _makeHandle binds the body-drag pointerdown on el. Both hosts persist
across the rebuild, so the listeners stack without bound - one extra set per
repaint.

WHY the shape below and not just "an early return". _installDrag returns a
`begin` closure that closes over the drag state the el-level move/up/cancel
listeners read. The handle child IS legitimately recreated each repaint, so a
`begin` must still be handed back on every call - but it must be the SAME
closure the surviving el-level listeners were built around. Handing back a fresh
closure while the old listeners live on desyncs the drag (the fresh begin sets
state nobody reads). So the guard is pinned as: return a value STORED ON el, and
that same stored property is assigned later in the body. A bare token-presence
assert would be a tautology (memory feedback_default_flip_weakens_tests); every
assert here is positional against a brace-matched function body.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAYOUT_JS = REPO / "web" / "js" / "lib" / "overlay_layout.js"

# `if (<cond>) return <ret>;` - one level of nested parens in the condition is
# enough for this file (el.querySelector(":scope > .ovx-handle")).
_GUARD = re.compile(
    r"if\s*\(\s*(?P<cond>[^()]*(?:\([^()]*\)[^()]*)*?)\s*\)\s*return\b(?P<ret>[^;]*);"
)
# A dotted property read off the persistent widget element (el._x / el.dataset.x).
_EL_PROP = re.compile(r"\bel\.[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*")

_MOVE_BIND = 'el.addEventListener("pointermove"'
_UP_BIND = 'el.addEventListener("pointerup"'
_CANCEL_BIND = 'el.addEventListener("pointercancel"'
_BODY_BIND = 'el.addEventListener("pointerdown"'
_HANDLE_BIND = 'h.addEventListener("pointerdown", begin)'


def _mask(src: str) -> str:
    """Blank every comment + string literal to spaces, preserving length.

    Brace-matching a JS function body is only safe once braces inside strings
    and comments are gone; preserving length keeps every index valid against the
    ORIGINAL text, so the regex asserts below still see real string content.
    """
    out = list(src)
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
        elif c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif c in "\"'`":
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == c:
                    j += 1
                    break
                if c != "`" and src[j] == "\n":
                    break
                j += 1
        else:
            i += 1
            continue
        for k in range(i, min(j, n)):
            if out[k] != "\n":
                out[k] = " "
        i = max(j, i + 1)
    return "".join(out)


def _fn_body(src: str, masked: str, name: str) -> str:
    """Return the ORIGINAL source text of `function <name>`'s brace-matched body."""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", masked)
    assert m, f"function {name} not found in {LAYOUT_JS.name}"
    open_at = masked.index("{", m.end())
    depth = 0
    for i in range(open_at, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_at + 1:i]
    raise AssertionError(f"unbalanced braces in {name}")


class OverlayDragListenerLeak(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = LAYOUT_JS.read_text(encoding="utf-8")
        cls.masked = _mask(cls.src)
        cls.install_drag = _fn_body(cls.src, cls.masked, "_installDrag")
        cls.make_handle = _fn_body(cls.src, cls.masked, "_makeHandle")

    def test_bodies_parsed(self):
        # Cheap canary: a refactor that breaks the brace-matcher must not turn
        # this whole guard into a silent no-op.
        self.assertIn(_MOVE_BIND, self.install_drag)
        self.assertIn(_UP_BIND, self.install_drag)
        self.assertIn(_CANCEL_BIND, self.install_drag)
        self.assertIn(_BODY_BIND, self.make_handle)
        self.assertNotIn("function _makeHandle", self.install_drag)

    def test_install_drag_returns_the_stored_begin_before_rebinding(self):
        body = self.install_drag
        first_bind = body.index(_MOVE_BIND)
        stored = []
        for g in _GUARD.finditer(body):
            if g.start() >= first_bind:
                break
            prop = _EL_PROP.search(g.group("cond"))
            if prop:
                stored.append((g, prop.group(0)))
        self.assertTrue(
            stored,
            "_installDrag re-binds el pointermove/pointerup/pointercancel with no "
            "early return gated on a value stored on el: every repaint stacks a "
            "fresh listener set on the same persistent widget element (RM-126)",
        )
        guard, prop = stored[0]
        # The guarded path must hand back the SAME closure the surviving
        # el-level listeners were built around - a fresh one would desync.
        self.assertIn(
            prop, guard.group("ret"),
            f"the early return must return the stored {prop}, not a fresh closure; "
            f"got 'return{guard.group('ret')}'",
        )
        # ... and the property must actually be written, or the guard never latches.
        assign = re.search(re.escape(prop) + r"\s*=[^=]", body)
        self.assertIsNotNone(assign, f"{prop} is read as a guard but never assigned")
        self.assertGreater(
            assign.start(), guard.end(),
            f"{prop} must be assigned after the listeners are installed",
        )

    def test_make_handle_body_drag_bind_has_its_own_latch(self):
        body = self.make_handle
        bind_at = body.index(_BODY_BIND)
        guards = [g for g in _GUARD.finditer(body) if g.start() < bind_at]
        handle_guards = [g for g in guards if "ovx-handle" in g.group("cond")]
        self.assertTrue(
            handle_guards, "the .ovx-handle child-existence guard disappeared"
        )
        handle_cond = handle_guards[0].group("cond").strip()
        others = [g for g in guards if g.group("cond").strip() != handle_cond]
        self.assertTrue(
            others,
            "the el-level body-drag pointerdown bind is guarded ONLY by the "
            ".ovx-handle child check, which a renderer rebuild clears - so the "
            "bind re-runs on the same persistent el every repaint (RM-126)",
        )
        latch = others[0]
        prop = _EL_PROP.search(latch.group("cond"))
        self.assertIsNotNone(
            prop,
            "the second guard must gate on a per-el stored flag (mirroring "
            f"_makeHideMenu), got '{latch.group('cond').strip()}'",
        )
        assign = re.search(re.escape(prop.group(0)) + r"\s*=[^=]", body)
        self.assertIsNotNone(
            assign, f"{prop.group(0)} is read as a guard but never assigned"
        )
        self.assertGreater(
            assign.start(), latch.end(),
            f"{prop.group(0)} must be set after its own guard, not before",
        )
        self.assertLess(
            assign.start(), bind_at,
            f"{prop.group(0)} must be set before the bind it latches",
        )

    def test_handle_child_still_rebinds_every_pass(self):
        # Regression pin: `h` is a FRESH node on every _makeHandle pass, so its
        # pointerdown bind is correct and must never move behind the body-drag
        # latch - that would leave a rebuilt handle dead.
        body = self.make_handle
        self.assertIn(
            _HANDLE_BIND, body,
            "the handle child lost its pointerdown bind - a rebuilt handle "
            "would no longer start a drag",
        )
        h_at = body.index(_HANDLE_BIND)
        self.assertLess(
            h_at, body.index(_BODY_BIND),
            "the handle bind must precede the el-level body-drag bind",
        )
        for g in _GUARD.finditer(body):
            if g.start() >= h_at:
                break
            self.assertIn(
                "ovx-handle", g.group("cond"),
                "the handle bind must not sit behind any guard other than the "
                f"child-existence check; found 'if ({g.group('cond').strip()}) return'",
            )


if __name__ == "__main__":
    unittest.main()
