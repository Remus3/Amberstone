"""
ui/base.py — Base overlay window class + shared rendering helpers.

All overlay panels inherit from OverlayWindow.
Rich-text rendering helpers (_render_tagged, _scan_names) are used by
multiple game panels for [A]/[E]/[T] tag colorization.
"""

import re
import tkinter as tk
import tkinter.font as tk_font
from pathlib import Path
from core.theme import BG, ALLY_COLOR, ENEMY_COLOR, TIME_COLOR, ITEM_COLOR


class OverlayWindow:
    """Borderless always-on-top window at a fixed pixel position."""

    def __init__(self, root, geo: dict, tag: str = ""):
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", False)
        self.top.configure(bg=BG)
        self.top.geometry(f"{geo['w']}x{geo['h']}+{geo['x']}+{geo['y']}")
        self.tag = tag
        self.geo = geo
        self._visible = False
        self.top.withdraw()
        self._menu = None

    def attach_menu(self, menu_callback):
        self._menu = menu_callback
        self.top.bind("<Button-3>", self._show_menu)

    def _show_menu(self, event):
        if self._menu:
            self._menu(event)

    def set_topmost(self, on: bool = True):
        """Toggle always-on-top. Call with True during active game if needed."""
        self.top.attributes("-topmost", on)

    def show(self):
        if not self._visible:
            self.top.deiconify()
            self.top.lift()
            self._visible = True

    def hide(self):
        if self._visible:
            self.top.withdraw()
            self._visible = False


# ── Shared tag regex ─────────────────────────────────────────────────────────
TAG_RE = re.compile(
    r'\[A\](.*?)\[/A\]|\[E\](.*?)\[/E\]|\[T\](.*?)\[/T\]', re.DOTALL
)
TIME_RE = re.compile(r'\b\d{1,2}:\d{2}\b|\b\d+s\b|\b\d+\s*min\b', re.I)


def strip_tags(text: str) -> str:
    """Remove raw [A],[/A],[E],[/E],[T],[/T] markers."""
    return re.sub(r'\[/?[AET]\]', '', text)


def render_tagged(widget: tk.Text, text: str, base_tag: str = "normal",
                  ally_names: list = None, enemy_names: list = None):
    """
    Write text into a disabled tk.Text widget with [A]/[E]/[T] tag coloring.
    Falls back to name-scanning if no tags are present.

    Assumes widget has tags configured: ally, enemy, time, normal/base.
    """
    widget.configure(state="normal")
    widget.delete("1.0", "end")

    if not text or text == "\u2014":
        widget.insert("end", "\u2014", base_tag)
        widget.configure(state="disabled")
        return

    has_tags = bool(TAG_RE.search(text))

    if has_tags:
        pos = 0
        for m in TAG_RE.finditer(text):
            if m.start() > pos:
                widget.insert("end", strip_tags(text[pos:m.start()]), base_tag)
            a, e, t = m.group(1), m.group(2), m.group(3)
            if a is not None:
                widget.insert("end", a, "ally")
            elif e is not None:
                widget.insert("end", e, "enemy")
            elif t is not None:
                widget.insert("end", t, "time")
            pos = m.end()
        if pos < len(text):
            widget.insert("end", strip_tags(text[pos:]), base_tag)
    else:
        _scan_names(widget, text, base_tag, ally_names or [], enemy_names or [])

    widget.configure(state="disabled")


def _scan_names(widget: tk.Text, text: str, base_tag: str,
                ally_names: list, enemy_names: list):
    """Fallback: highlight ally/enemy names and time patterns in plain text."""
    # Split on time patterns first
    tokens = []
    p = 0
    for m in TIME_RE.finditer(text):
        if m.start() > p:
            tokens.append((text[p:m.start()], None))
        tokens.append((m.group(), "time"))
        p = m.end()
    if p < len(text):
        tokens.append((text[p:], None))

    for frag, tag in tokens:
        if tag:
            widget.insert("end", frag, tag)
            continue
        frag_lower = frag.lower()
        sub_pos = 0
        while sub_pos < len(frag):
            best_start, best_end, best_tag = len(frag), len(frag), None
            for name in ally_names:
                idx = frag_lower.find(name, sub_pos)
                if idx != -1 and idx < best_start:
                    best_start, best_end, best_tag = idx, idx + len(name), "ally"
            for name in enemy_names:
                idx = frag_lower.find(name, sub_pos)
                if idx != -1 and idx < best_start:
                    best_start, best_end, best_tag = idx, idx + len(name), "enemy"
            if best_tag:
                if best_start > sub_pos:
                    widget.insert("end", frag[sub_pos:best_start], base_tag)
                widget.insert("end", frag[best_start:best_end], best_tag)
                sub_pos = best_end
            else:
                widget.insert("end", frag[sub_pos:], base_tag)
                break


def configure_rich_tags(widget: tk.Text, base_color: str):
    """Add standard ally/enemy/time/item/base tags to a Text widget."""
    bf = tk_font.Font(family="Segoe UI", size=12, weight="bold")
    widget.tag_configure("ally",   foreground=ALLY_COLOR,  font=bf)
    widget.tag_configure("enemy",  foreground=ENEMY_COLOR, font=bf)
    widget.tag_configure("time",   foreground=TIME_COLOR,  font=bf)
    widget.tag_configure("item",   foreground=ITEM_COLOR,  font=bf)
    widget.tag_configure("base",   foreground=base_color)
    widget.tag_configure("normal", foreground=base_color)
