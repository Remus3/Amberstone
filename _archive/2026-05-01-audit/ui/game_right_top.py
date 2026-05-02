"""
ui/game_right_top.py — Right-top panel: Stats bar + RISK + OBJECTIVE
Rich-text with [A]/[E]/[T] tags and item name highlighting.
"""

import re
import tkinter as tk
import tkinter.font as tk_font

from core.theme import (BG, BG_SECTION, BG_FIELD, BORDER, LABEL_COLOR,
                         FIELD_COLORS, GAME_ZONES)
from ui.base import OverlayWindow, strip_tags, TAG_RE, TIME_RE

# Known item names for blue highlighting
ITEM_NAMES = {
    "yun tal wildarrows","infinity edge","kraken slayer","galeforce",
    "immortal shieldbow","bloodthirster","lord dominik's regards",
    "mortal reminder","runaan's hurricane","ravenous hydra",
    "navori quickblades","collector","rapidfire cannon","statikk shiv",
    "phantom dancer","guinsoo's rageblade","wit's end","botrk",
    "blade of the ruined king","berserker's greaves","plated steelcaps",
    "mercury's treads","sorcerer's shoes","luden's companion","shadowflame",
    "rabadon's deathcap","zhonya's hourglass","void staff",
    "rylai's crystal scepter","moonstone renewer","ardent censer",
    "staff of flowing water","redemption","knight's vow","locket",
    "shurelya's battlesong","imperial mandate","mikael's blessing",
    "stormsurge","malignance","horizon focus","lich bane",
    "sunfire aegis","heartsteel","warmog's armor","thornmail",
    "frozen heart","randuins omen","force of nature","spirit visage",
    "trinity force","sheen","black cleaver","titanic hydra","sterak's gage",
}


class GameRightTop(OverlayWindow):
    def __init__(self, root):
        super().__init__(root, GAME_ZONES["right_top"], tag="game_rtop")
        container = tk.Frame(self.top, bg=BG)
        container.pack(fill="both", expand=True, padx=1, pady=1)

        # Stats bar
        self.stats_frame = tk.Frame(container, bg=BG_FIELD,
                                     highlightbackground=BORDER, highlightthickness=1)
        self.stats_frame.grid(row=0, column=0, sticky="nsew")
        self.stat_labels = {}
        stats_row = tk.Frame(self.stats_frame, bg=BG_FIELD)
        stats_row.pack(fill="x", padx=6, pady=4)
        for col, (key, text) in enumerate([
            ("time", "0:00"), ("cs", "0 CS"), ("gold", "0g"), ("kda", "0/0/0")
        ]):
            lbl = tk.Label(stats_row, text=text, bg=BG_FIELD,
                           fg=FIELD_COLORS["stat_value"],
                           font=("Consolas", 11, "bold"))
            lbl.grid(row=0, column=col, padx=4)
            self.stat_labels[key] = lbl
        for c in range(4):
            stats_row.columnconfigure(c, weight=1)

        # Rich-text sections
        self.txt_widgets = {}
        sections = [
            ("risk",      "RISK",      FIELD_COLORS["risk"]),
            ("objective", "OBJECTIVE", FIELD_COLORS["objective"]),
        ]
        for i, (key, label, color) in enumerate(sections):
            frame = tk.Frame(container, bg=BG_SECTION,
                             highlightbackground=BORDER, highlightthickness=1)
            frame.grid(row=i + 1, column=0, sticky="nsew", pady=(2, 0))
            tk.Label(frame, text=label, bg=BG_SECTION, fg=LABEL_COLOR,
                     font=("Consolas", 13, "bold"), anchor="w"
                     ).pack(anchor="w", padx=8, pady=(5, 0))
            txt = tk.Text(frame, bg=BG_SECTION, fg=color,
                          font=("Segoe UI", 12), wrap="word", bd=0,
                          highlightthickness=0, insertbackground=BG_SECTION,
                          state="disabled", cursor="arrow", padx=8, pady=3)
            txt.pack(fill="both", expand=True, pady=(0, 4))
            _bold12 = tk_font.Font(family="Segoe UI", size=12, weight="bold")
            txt.tag_configure("ally",   foreground="#44ff88", font=_bold12)
            txt.tag_configure("enemy",  foreground="#ff4444", font=_bold12)
            txt.tag_configure("time",   foreground="#ffdd00", font=_bold12)
            txt.tag_configure("item",   foreground="#4ab0ff", font=_bold12)
            txt.tag_configure("base",   foreground=color)
            self.txt_widgets[key] = (txt, color)

        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=0)
        container.rowconfigure(1, weight=2)
        container.rowconfigure(2, weight=3)
        self._ally_names = []
        self._enemy_names = []

    def _write_rich(self, txt, text, base_color):
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        if not text or text == "\u2014":
            txt.insert("end", "\u2014", "base")
            txt.configure(state="disabled")
            return
        has_tags = bool(TAG_RE.search(text))
        if has_tags:
            pos = 0
            for m in TAG_RE.finditer(text):
                if m.start() > pos:
                    self._write_plain(txt, strip_tags(text[pos:m.start()]))
                a, e, t = m.group(1), m.group(2), m.group(3)
                if a:   txt.insert("end", a, "ally")
                elif e: txt.insert("end", e, "enemy")
                elif t: txt.insert("end", t, "time")
                pos = m.end()
            if pos < len(text):
                self._write_plain(txt, strip_tags(text[pos:]))
        else:
            frags = []
            p = 0
            for m in TIME_RE.finditer(text):
                if m.start() > p:
                    frags.append((text[p:m.start()], None))
                frags.append((m.group(), "time"))
                p = m.end()
            if p < len(text):
                frags.append((text[p:], None))
            for frag, tag in frags:
                if tag:
                    txt.insert("end", frag, tag)
                else:
                    self._write_plain(txt, frag)
        txt.configure(state="disabled")

    def _write_plain(self, txt, text):
        tl = text.lower()
        pos = 0
        while pos < len(text):
            best, bend, btag = len(text), len(text), None
            for n in self._ally_names:
                i = tl.find(n, pos)
                if i != -1 and i < best:
                    best, bend, btag = i, i + len(n), "ally"
            for n in self._enemy_names:
                i = tl.find(n, pos)
                if i != -1 and i < best:
                    best, bend, btag = i, i + len(n), "enemy"
            for n in ITEM_NAMES:
                i = tl.find(n, pos)
                if i != -1 and i < best:
                    best, bend, btag = i, i + len(n), "item"
            if btag:
                if best > pos:
                    txt.insert("end", strip_tags(text[pos:best]), "base")
                txt.insert("end", text[best:bend], btag)
                pos = bend
            else:
                txt.insert("end", strip_tags(text[pos:]), "base")
                break

    def update_data(self, data):
        ally = data.get("ally_comp", [])
        enemy = data.get("enemy_comp", [])
        if isinstance(ally, list):
            self._ally_names = [n.lower() for n in ally]
        if isinstance(enemy, list):
            self._enemy_names = [n.lower() for n in enemy]
        for key, (txt, color) in self.txt_widgets.items():
            self._write_rich(txt, data.get(key, "\u2014") or "\u2014", color)

    def update_stats(self, game_state):
        if not game_state:
            return
        self.stat_labels["time"].configure(
            text=game_state.get("game_time", "0:00"))
        self.stat_labels["cs"].configure(
            text=f"{game_state.get('cs', 0)} CS")
        self.stat_labels["gold"].configure(
            text=f"{game_state.get('gold', 0)}g")
        self.stat_labels["kda"].configure(
            text=game_state.get("kda", "0/0/0"))
