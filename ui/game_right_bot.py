"""ui/game_right_bot.py — Right-bottom panel: CLOCK | ACTION | RESET/ITEM | WAVE
Rich-text rendering for item section, plain text for wave.
Note: WIN% row removed (Phase 6 Step 2 Fix 0) — no data producer exists for this field.
"""

import re
import time as _time_mod
import tkinter as tk
import tkinter.font as tk_font

from core.theme import (BG, BG_SECTION, BORDER, LABEL_COLOR,
                         FIELD_COLORS, GAME_ZONES)
from ui.base import OverlayWindow, strip_tags, TAG_RE


class GameRightBot(OverlayWindow):
    def __init__(self, root):
        super().__init__(root, GAME_ZONES["right_bot"], tag="game_rbot")
        container = tk.Frame(self.top, bg=BG)
        container.pack(fill="both", expand=True, padx=1, pady=1)

        _LBL = ("Consolas", 10, "bold")
        _VAL = ("Segoe UI", 14, "bold")
        _BOLD12 = tk_font.Font(family="Segoe UI", size=12, weight="bold")

        # CLOCK
        cf = tk.Frame(container, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        cf.grid(row=0, column=0, sticky="nsew")
        tk.Label(cf, text="CLOCK", bg=BG, fg=LABEL_COLOR, font=_LBL, anchor="w"
                 ).pack(side="left", padx=(8, 4), pady=(5, 5))
        self._clock_var = tk.StringVar(value="0:00")
        tk.Label(cf, textvariable=self._clock_var, bg=BG,
                 fg=FIELD_COLORS["clock"], font=_VAL, anchor="w"
                 ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._clock_base_time = 0.0
        self._clock_wall_time = 0.0
        self._clock_job = None

        # ACTION
        af = tk.Frame(container, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        af.grid(row=1, column=0, sticky="nsew", pady=(2, 0))
        tk.Label(af, text="ACTION", bg=BG, fg=LABEL_COLOR, font=_LBL, anchor="w"
                 ).pack(side="left", padx=(8, 4), pady=(5, 5))
        self._action_var = tk.StringVar(value="\u2014")
        tk.Label(af, textvariable=self._action_var, bg=BG,
                 fg=FIELD_COLORS["action"], font=_VAL, anchor="nw",
                 wraplength=230, justify="left"
                 ).pack(side="left", fill="both", expand=True, padx=(0, 8), pady=(4, 4))

        # RESET / ITEM (rich text)
        itf = tk.Frame(container, bg=BG_SECTION,
                       highlightbackground=BORDER, highlightthickness=1)
        itf.grid(row=2, column=0, sticky="nsew", pady=(2, 0))
        tk.Label(itf, text="RESET / ITEM", bg=BG_SECTION, fg=LABEL_COLOR,
                 font=("Consolas", 13, "bold"), anchor="w"
                 ).pack(anchor="w", padx=8, pady=(5, 0))
        self.item_txt = tk.Text(itf, bg=BG_SECTION,
                                fg=FIELD_COLORS["reset_item"],
                                font=("Segoe UI", 12), wrap="word", bd=0,
                                highlightthickness=0, insertbackground=BG_SECTION,
                                state="disabled", cursor="arrow", padx=8, pady=3)
        self.item_txt.pack(fill="both", expand=True, pady=(0, 4))
        for tag, fg in [("ally", "#44ff88"), ("enemy", "#ff4444"),
                        ("time", "#ffdd00"), ("item", "#4ab0ff"),
                        ("base", FIELD_COLORS["reset_item"])]:
            self.item_txt.tag_configure(
                tag, foreground=fg, font=_BOLD12 if tag != "base" else None)

        # WAVE
        wvf = tk.Frame(container, bg=BG_SECTION,
                       highlightbackground=BORDER, highlightthickness=1)
        wvf.grid(row=3, column=0, sticky="nsew", pady=(2, 0))
        tk.Label(wvf, text="WAVE", bg=BG_SECTION, fg=LABEL_COLOR,
                 font=("Consolas", 13, "bold"), anchor="w"
                 ).pack(anchor="w", padx=8, pady=(4, 0))
        self.wave_txt = tk.Text(wvf, bg=BG_SECTION, fg=FIELD_COLORS["wave"],
                                font=("Segoe UI", 12), wrap="word", bd=0,
                                highlightthickness=0, insertbackground=BG_SECTION,
                                state="disabled", cursor="arrow", padx=8, pady=2)
        self.wave_txt.pack(fill="both", expand=True, pady=(0, 3))
        self.wave_txt.tag_configure("base", foreground=FIELD_COLORS["wave"])

        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=0, minsize=38)
        container.rowconfigure(1, weight=0, minsize=60)
        container.rowconfigure(2, weight=5)
        container.rowconfigure(3, weight=1)
        self._ally_names = []
        self._enemy_names = []

    # ── Clock ────────────────────────────────────────────────────────────────

    def _tick_clock(self):
        if self._clock_wall_time > 0:
            elapsed = _time_mod.monotonic() - self._clock_wall_time
            total = max(0, self._clock_base_time + elapsed)
            self._clock_var.set(f"{int(total // 60)}:{int(total % 60):02d}")
        self._clock_job = self.top.after(1000, self._tick_clock)

    def sync_clock(self, game_seconds: float):
        self._clock_base_time = game_seconds
        self._clock_wall_time = _time_mod.monotonic()
        if self._clock_job is None:
            self._tick_clock()

    # ── Text helpers ─────────────────────────────────────────────────────────

    def _write_txt(self, txt, text: str):
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.insert("end", strip_tags(text) if text else "\u2014", "base")
        txt.configure(state="disabled")

    def _write_rich(self, txt, text: str):
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        if not text or text == "\u2014" or text == "":
            txt.insert("end", "\u2014", "base")
            txt.configure(state="disabled")
            return
        if TAG_RE.search(text):
            pos = 0
            for m in TAG_RE.finditer(text):
                if m.start() > pos:
                    txt.insert("end", strip_tags(text[pos:m.start()]), "base")
                a, e, t = m.group(1), m.group(2), m.group(3)
                if a:   txt.insert("end", a, "ally")
                elif e: txt.insert("end", e, "enemy")
                elif t: txt.insert("end", t, "time")
                pos = m.end()
            if pos < len(text):
                txt.insert("end", strip_tags(text[pos:]), "base")
        else:
            tl = text.lower()
            fp = 0
            while fp < len(text):
                best, bend, btag = len(text), len(text), None
                for n in self._ally_names:
                    i = tl.find(n, fp)
                    if i != -1 and i < best:
                        best, bend, btag = i, i + len(n), "ally"
                for n in self._enemy_names:
                    i = tl.find(n, fp)
                    if i != -1 and i < best:
                        best, bend, btag = i, i + len(n), "enemy"
                if btag:
                    if best > fp:
                        txt.insert("end", strip_tags(text[fp:best]), "base")
                    txt.insert("end", text[best:bend], btag)
                    fp = bend
                else:
                    txt.insert("end", strip_tags(text[fp:]), "base")
                    break
        txt.configure(state="disabled")

    # ── Data update ──────────────────────────────────────────────────────────

    def update_data(self, data):
        ally = data.get("ally_comp", [])
        enemy = data.get("enemy_comp", [])
        if isinstance(ally, list):
            self._ally_names = [n.lower() for n in ally]
        if isinstance(enemy, list):
            self._enemy_names = [n.lower() for n in enemy]
        self._action_var.set(data.get("action", "") or "\u2014")
        self._write_rich(self.item_txt, data.get("reset_item", "") or "\u2014")
        self._write_txt(self.wave_txt, data.get("wave", "") or "\u2014")
