"""
ui/game_bottom.py — Bottom strip panel: IMMEDIATE | NEXT | FIGHT RULE
Rich-text rendering with [A]/[E]/[T] tags, ward image overlays, flash alerts.
"""

import tkinter as tk
import tkinter.font as tk_font
from pathlib import Path

from core.theme import (BG, BG_SECTION, BORDER, LABEL_COLOR, FIELD_COLORS,
                         ALLY_COLOR, ENEMY_COLOR, TIME_COLOR, GAME_ZONES)
from ui.base import OverlayWindow, render_tagged

SCRIPT_DIR = Path(__file__).parent.parent

WARD_KEYWORDS = {
    "river tri": "river_tri", "tri-brush": "river_tri", "tri brush": "river_tri",
    "drake pit": "drake_pit", "baron pit": "baron_pit", "pixel bush": "pixel_bush",
    "river mid": "river_mid", "river bush": "river_mid", "lane ward": "lane_ward_bot",
    "jg bot": "jungle_bot", "jg top": "jungle_top",
    "jungle bot": "jungle_bot", "jungle top": "jungle_top",
}


class GameBottomStrip(OverlayWindow):
    """Bottom strip: IMMEDIATE | NEXT | FIGHT RULE with rich color-coded text."""

    def __init__(self, root):
        super().__init__(root, GAME_ZONES["bottom"], tag="game_bottom")

        self._ward_imgs = {}
        ward_dir = SCRIPT_DIR / "assets" / "wards"
        try:
            from PIL import Image as PilImage, ImageTk
            for stem in WARD_KEYWORDS.values():
                p = ward_dir / f"{stem}.png"
                if p.exists() and stem not in self._ward_imgs:
                    img = PilImage.open(str(p)).resize((36, 36))
                    self._ward_imgs[stem] = ImageTk.PhotoImage(img)
        except Exception:
            pass

        container = tk.Frame(self.top, bg=BG)
        container.pack(fill="both", expand=True, padx=1, pady=1)
        self.text_widgets = {}
        self._ward_labels = {}
        columns = [
            ("immediate", "IMMEDIATE", FIELD_COLORS["immediate"]),
            ("next",      "NEXT",      FIELD_COLORS["next"]),
            ("fight_rule","FIGHT RULE", FIELD_COLORS["fight_rule"]),
        ]
        for i, (key, label, color) in enumerate(columns):
            frame = tk.Frame(container, bg=BG_SECTION,
                             highlightbackground=BORDER, highlightthickness=1)
            frame.grid(row=0, column=i, sticky="nsew",
                       padx=(0 if i == 0 else 2, 0))
            hdr = tk.Frame(frame, bg=BG_SECTION)
            hdr.pack(fill="x")
            tk.Label(hdr, text=label, bg=BG_SECTION, fg=LABEL_COLOR,
                     font=("Consolas", 8, "bold"), anchor="w"
                     ).pack(side="left", padx=10, pady=(6, 0))
            wlbl = tk.Label(hdr, bg=BG_SECTION, image="", bd=0)
            wlbl.pack(side="right", padx=6, pady=(4, 0))
            wlbl.pack_forget()
            self._ward_labels[key] = wlbl

            txt = tk.Text(frame, bg=BG_SECTION, fg=color,
                          font=("Segoe UI", 11), wrap="word", bd=0,
                          highlightthickness=0, insertbackground=BG_SECTION,
                          state="disabled", cursor="arrow", padx=10, pady=4)
            txt.pack(fill="both", expand=True, padx=0, pady=(0, 6))
            _bf = tk_font.Font(family="Segoe UI", size=11, weight="bold")
            txt.tag_configure("ally",   foreground=ALLY_COLOR,  font=_bf)
            txt.tag_configure("enemy",  foreground=ENEMY_COLOR, font=_bf)
            txt.tag_configure("time",   foreground=TIME_COLOR,  font=_bf)
            txt.tag_configure("normal", foreground=color)
            self.text_widgets[key] = txt

        for i in range(3):
            container.columnconfigure(i, weight=1, uniform="col")
        container.rowconfigure(0, weight=1)
        self._ally_names = []
        self._enemy_names = []
        self._flash_job = None

    def set_teams(self, ally_comp, enemy_comp):
        self._ally_names = [n.lower() for n in (ally_comp or [])]
        self._enemy_names = [n.lower() for n in (enemy_comp or [])]

    def _flash_next(self, on, count=0):
        widget = self.text_widgets.get("next")
        if widget is None:
            return
        widget.configure(bg="#2a2800" if on else BG_SECTION)
        if count < 6:
            self._flash_job = widget.after(
                220, lambda: self._flash_next(not on, count + 1))
        else:
            widget.configure(bg=BG_SECTION)

    def _show_ward(self, key, text):
        """Show ward image if text contains a ward keyword."""
        ward_img_key = None
        text_lower = (text or "").lower()
        for kw, stem in WARD_KEYWORDS.items():
            if kw in text_lower:
                ward_img_key = stem
                break
        wlbl = self._ward_labels.get(key)
        if wlbl:
            if ward_img_key and ward_img_key in self._ward_imgs:
                wlbl.configure(image=self._ward_imgs[ward_img_key])
                wlbl.image = self._ward_imgs[ward_img_key]
                wlbl.pack(side="right", padx=6, pady=(4, 0))
            else:
                wlbl.pack_forget()

    def update_data(self, data):
        ally = data.get("ally_comp", [])
        enemy = data.get("enemy_comp", [])
        if isinstance(ally, list):
            self._ally_names = [n.lower() for n in ally]
        if isinstance(enemy, list):
            self._enemy_names = [n.lower() for n in enemy]

        for key, widget in self.text_widgets.items():
            text = data.get(key, "\u2014") or "\u2014"
            self._show_ward(key, text)
            render_tagged(widget, text, "normal",
                         self._ally_names, self._enemy_names)

        # Flash NEXT yellow for ward placement timings
        next_text = (data.get("next", "") or "").lower()
        ward_triggers = ("ward", "tri-brush", "tri brush", "pixel bush",
                        "drake pit", "baron pit", "river bush",
                        "1:30", "4:45", "19:30")
        if any(kw in next_text for kw in ward_triggers):
            if self._flash_job:
                try:
                    self.text_widgets["next"].after_cancel(self._flash_job)
                except Exception:
                    pass
            self._flash_next(True, 0)
