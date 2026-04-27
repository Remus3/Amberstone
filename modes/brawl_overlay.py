"""
modes/brawl_overlay.py  â v2 (full upgrade)

Nexus Blitz / URF / One For All overlay.

Right-top  (320Ã520): Mode / Stats / ACTION / EVENT / ITEMS / FIGHT RULE
Right-bot  (320Ã520): CLOCK / ITEMS+RESET / OBJECTIVE / RISK / WAVE
Bottom     (1920Ã160):
    Left  220px  â MODE INFO / EVENT DETAILS
    Center 1440px â EVENT/POSITION CANVAS  (upgraded per mode)
        NB:  Two-lane map + player position dot + nexus HP bars + event urgency
        URF: Champion ability priority matrix (visual order of best-use skills)
        OFA: 5-stack readiness tracker + timing bar for group engage
    Right  260px  â FIGHT CONDITION / OBJECTIVE

[A]/[E]/[T] tag support in all text panels.
"""

import tkinter as tk
import tkinter.font as tk_font
import time
import re

BG      = "#0b0b12"
BG_SEC  = "#111119"
BORDER  = "#252535"
LABEL_C = "#9090aa"

C = {
    "action":    "#ff2244",
    "event":     "#ffd700",
    "event_act": "#ff9944",
    "items":     "#4ab0ff",
    "econ":      "#a8c023",
    "objective": "#c77dff",
    "risk":      "#ff4a6a",
    "clock":     "#ffdd00",
    "stats":     "#d0d0e0",
    "fight":     "#ffa84a",
    "mode":      "#44ffcc",
    "wave":      "#3ddba8",
    "you":       "#ffffff",
}

_LBL    = ("Consolas", 10, "bold")
_LBL_HD = ("Consolas", 12, "bold")
_VAL_LG = ("Segoe UI", 14, "bold")
_BODY   = ("Segoe UI", 12)
_TAG_RE = re.compile(r'\[A\](.*?)\[/A\]|\[E\](.*?)\[/E\]|\[T\](.*?)\[/T\]', re.DOTALL)

_NB_EVENT_COLORS = {
    "star guardian":   "#ff66cc",
    "bardle royale":   "#ff9944",
    "protect the svp": "#44ff88",
    "scuttle puddle":  "#44aaff",
    "teemo":           "#66aa44",
    "default":         "#ffd700",
}
_NB_EVENT_LOC = {
    "star guardian":   "TOP",
    "bardle royale":   "BOTH",
    "protect the svp": "BOT",
    "scuttle puddle":  "RIVER",
    "default":         "MAP",
}

# URF ability priority suggestions by damage type
_URF_ABILITY_TIPS = {
    "default": ["Longest range ability first",
                "Full combo on every CD cycle",
                "Buy Grievous Wounds by item 2 vs sustain",
                "Never let abilities sit off CD"],
}


def _strip(t):
    return re.sub(r'\[/?[AET]\]', '', t or "")


def _write_rich(w, text, base_color):
    w.configure(state="normal")
    w.delete("1.0", "end")
    text = text or "\u2014"
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    if _TAG_RE.search(text):
        pos = 0
        for m in _TAG_RE.finditer(text):
            if m.start() > pos:
                w.insert("end", _strip(text[pos:m.start()]), "base")
            a, e, t = m.group(1), m.group(2), m.group(3)
            if a:   w.insert("end", a, "ally")
            elif e: w.insert("end", e, "enemy")
            elif t: w.insert("end", t, "time")
            pos = m.end()
        if pos < len(text):
            w.insert("end", _strip(text[pos:]), "base")
    else:
        w.insert("end", _strip(text), "base")
    w.configure(state="disabled")


def _make_txt(parent, fg, font=None):
    bf = tk_font.Font(family="Segoe UI", size=12, weight="bold")
    w = tk.Text(parent, bg=BG_SEC, fg=fg, font=font or _BODY, wrap="word",
                bd=0, highlightthickness=0, insertbackground=BG_SEC,
                state="disabled", cursor="arrow", padx=8, pady=3, height=1)
    w.tag_configure("ally",  foreground="#44ff88", font=bf)
    w.tag_configure("enemy", foreground="#ff4444", font=bf)
    w.tag_configure("time",  foreground="#ffdd00", font=bf)
    w.tag_configure("base",  foreground=fg)
    return w


def _sec(parent, row, label, color, minsize=80):
    f = tk.Frame(parent, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
    f.grid(row=row, column=0, sticky="nsew", pady=(2, 0))
    tk.Label(f, text=label, bg=BG_SEC, fg=LABEL_C,
             font=_LBL_HD, anchor="w").pack(anchor="w", padx=8, pady=(4, 0))
    txt = _make_txt(f, color)
    txt.pack(fill="both", expand=True, pady=(0, 4))
    parent.rowconfigure(row, weight=1, minsize=minsize)
    return txt


def _bar(parent, row, label, color, minsize=40):
    f = tk.Frame(parent, bg=BG, highlightbackground=BORDER, highlightthickness=1)
    f.grid(row=row, column=0, sticky="nsew", pady=(2, 0))
    tk.Label(f, text=label, bg=BG, fg=LABEL_C, font=_LBL, anchor="w"
             ).pack(side="left", padx=(8, 4), pady=(5, 5))
    var = tk.StringVar(value="\u2014")
    lbl = tk.Label(f, textvariable=var, bg=BG, fg=color, font=_VAL_LG,
                   anchor="w", wraplength=220, justify="left")
    lbl.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=(3, 3))
    parent.rowconfigure(row, weight=0, minsize=minsize)
    return var, lbl


# ââ Brawl Event Canvas v2 âââââââââââââââââââââââââââââââââââââââââââââââââââââ
class BrawlEventCanvas(tk.Frame):
    """
    NB:  Two-lane topdown map with event location + player position + nexus HP bars
    URF: Ability priority sequence visual + current fight tip
    OFA: 5-stack readiness + engage timing indicator
    """

    def __init__(self, parent):
        super().__init__(parent, bg=BG_SEC)
        self.canvas = tk.Canvas(self, bg=BG_SEC, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=4, pady=2)
        self._event      = ""
        self._timer      = 0
        self._location   = ""
        self._mode       = "NEXUSBLITZ"
        self._fight_tip  = ""
        self._my_nexus   = 100
        self._en_nexus   = 100
        self._hp_pct     = 100
        # Player position in lane (0=top, 1=bot, 0.5=mid/roam)
        self._player_lane = 0.5
        self._ability_tips = []  # URF: list of ability tips
        self._ofa_ready    = []  # OFA: list of ready indicators
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self._redraw()
        self.bind("<Button-3>", self._rc_menu)
    def _rc_menu(self, event):
        """Phase 7 P3-B: right-click context menu."""
        import tkinter as _tk
        m = _tk.Menu(self.winfo_toplevel(), tearoff=0,
                     bg="#1a1a24", fg="#c0c0d0",
                     activebackground="#2a2a3a", activeforeground="#ffffff",
                     font=("Segoe UI", 9))
        m.add_command(label="Force Refresh", command=self._rc_refresh)
        m.add_separator()
        m.add_command(label="Hide Panel", command=self.hide)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _rc_refresh(self):
        try:
            from pathlib import Path as _P; import json as _j, time as _t
            _ts = _P(__file__).parent.parent / "data" / "coaching_ts.json"
            _ts.write_text(_j.dumps({"force": _t.time()}), encoding="utf-8")
        except Exception: pass

    def update_event(self, event: str = "", timer: int = 0, location: str = "",
                     fight_tip: str = "", my_nexus: int = 100,
                     enemy_nexus: int = 100, mode: str = "NEXUSBLITZ",
                     hp_pct: int = 100, player_lane: float = 0.5,
                     ability_tips: list = None, ofa_ready: list = None):
        self._event       = event
        self._timer       = timer
        self._location    = location or _NB_EVENT_LOC.get(event.lower(), "MAP")
        self._fight_tip   = fight_tip
        self._my_nexus    = my_nexus
        self._en_nexus    = enemy_nexus
        self._mode        = mode
        self._hp_pct      = hp_pct
        self._player_lane = player_lane
        self._ability_tips = ability_tips or []
        self._ofa_ready    = ofa_ready or []
        self._redraw()

    def _redraw(self):
        cv = self.canvas
        cv.delete("all")
        w  = cv.winfo_width() or 900
        h  = cv.winfo_height() or 120
        mode = self._mode.upper()

        if "URF" in mode or "ULTBOOK" in mode or "ARURF" in mode:
            self._draw_urf(cv, w, h)
        elif "GAMEMODEX" in mode or "OFA" in mode or "ONEFORALL" in mode:
            self._draw_ofa(cv, w, h)
        elif "NEXUS" in mode or "NB" in mode:
            self._draw_nb(cv, w, h)
        else:
            self._draw_generic(cv, w, h)

    def _draw_nb(self, cv, w, h):
        """Two-lane NB map + event location + player dot + nexus HP + event urgency flash."""
        BASE_W  = 32
        lane_h  = (h - 28) // 2 - 4
        top_y   = 18
        bot_y   = top_y + lane_h + 8

        ev      = self._event or ""
        ev_low  = ev.lower()
        loc     = self._location.upper()
        color   = _NB_EVENT_COLORS.get(ev_low, _NB_EVENT_COLORS["default"])
        timer   = self._timer
        urgent  = timer > 0 and timer < 15

        # Bases
        cv.create_rectangle(0, 0, BASE_W, h, fill="#0a2a0a", outline="#225522")
        cv.create_text(BASE_W//2, h//2, text="YOUR\nBASE", fill="#44aa44",
                       font=("Consolas", 6, "bold"), justify="center")
        cv.create_rectangle(w - BASE_W, 0, w, h, fill="#2a0a0a", outline="#552222")
        cv.create_text(w - BASE_W//2, h//2, text="ENEMY\nBASE", fill="#aa4444",
                       font=("Consolas", 6, "bold"), justify="center")

        # Lane area width
        lw = w - BASE_W * 2

        # Top lane
        top_fill = (color if loc in ("TOP", "BOTH") else "#1a1a2a")
        cv.create_rectangle(BASE_W, top_y, w - BASE_W, top_y + lane_h,
                            fill=top_fill, outline="#333355")
        cv.create_text(BASE_W + lw//2, top_y + lane_h//2,
                       text="\u25b2 TOP LANE",
                       fill="#ffffff" if loc in ("TOP","BOTH") else "#446688",
                       font=("Consolas", 9, "bold"))

        # River
        river_y  = top_y + lane_h + 1
        river_h  = 6
        river_fill = (color if "RIVER" in loc else "#0a0a1a")
        cv.create_rectangle(BASE_W, river_y, w - BASE_W, river_y + river_h,
                            fill=river_fill, outline="")
        cv.create_text(BASE_W + lw//2, river_y + river_h//2, text="RIVER",
                       fill="#446688" if "RIVER" not in loc else "#ffffff",
                       font=("Consolas", 6))

        # Bot lane
        bot_fill = (color if loc in ("BOT","BOTH") else "#1a1a2a")
        cv.create_rectangle(BASE_W, bot_y, w - BASE_W, bot_y + lane_h,
                            fill=bot_fill, outline="#333355")
        cv.create_text(BASE_W + lw//2, bot_y + lane_h//2,
                       text="\u25bc BOT LANE",
                       fill="#ffffff" if loc in ("BOT","BOTH") else "#446688",
                       font=("Consolas", 9, "bold"))

        # Player dot
        player_y = (top_y + lane_h//2 if self._player_lane < 0.3
                    else bot_y + lane_h//2 if self._player_lane > 0.7
                    else river_y + river_h//2)
        player_x = BASE_W + lw // 2
        dot_col  = ("#ff4444" if self._hp_pct < 30 else
                    "#ffaa44" if self._hp_pct < 60 else "#ffffff")
        cv.create_oval(player_x - 8, player_y - 8, player_x + 8, player_y + 8,
                       fill=dot_col, outline="#ffdd00", width=2)
        cv.create_text(player_x, player_y, text="YOU",
                       fill="#000000", font=("Consolas", 6, "bold"))

        # Event label (urgent = red blink text)
        ev_display = f"{ev}  [{timer}s!]" if urgent else (f"{ev}  [{timer}s]" if timer > 0 else ev or "No Event")
        ev_color   = "#ff4444" if urgent else color
        cv.create_text(BASE_W + lw//2, 9, text=ev_display,
                       fill=ev_color, font=("Consolas", 9, "bold" if urgent else "normal"))

        # Nexus HP bars at base edges
        self._draw_nexus_bar(cv, 2, h - 10, self._my_nexus, BASE_W - 4, "#44cc44")
        self._draw_nexus_bar(cv, w - BASE_W + 2, h - 10, self._en_nexus, BASE_W - 4, "#cc4444")

    def _draw_nexus_bar(self, cv, x, y, hp, bar_w, color):
        cv.create_rectangle(x, y - 7, x + bar_w, y, fill="#1a1a1a", outline="")
        filled = int(bar_w * max(0, hp) / 100)
        if filled > 0:
            cv.create_rectangle(x, y - 7, x + filled, y,
                                fill=color if hp > 20 else "#ff4444", outline="")
        cv.create_text(x + bar_w//2, y - 3, text=f"NX {hp}%",
                       fill=color, font=("Consolas", 6))

    def _draw_urf(self, cv, w, h):
        """URF: ability priority visual sequence."""
        cv.create_rectangle(0, 0, w, h, fill="#060618", outline="")
        cv.create_text(w//2, 10, text="ULTRA RAPID FIRE \u2014 ABILITY PRIORITY",
                       fill="#44ffcc", font=("Consolas", 10, "bold"))

        tips = self._ability_tips or _URF_ABILITY_TIPS["default"]
        # Draw as priority bars
        tip_y = 26
        bar_w = min(w - 40, 800)
        bar_x = (w - bar_w) // 2
        for i, tip in enumerate(tips[:5]):
            bh  = 18
            pct = max(0.3, 1.0 - i * 0.15)  # bars shrink to show priority
            fill_w = int(bar_w * pct)
            cols = ["#ff4444","#ff8844","#ffdd00","#44aaff","#44ff88"]
            cv.create_rectangle(bar_x, tip_y, bar_x + bar_w, tip_y + bh,
                                fill="#111122", outline="#223")
            cv.create_rectangle(bar_x, tip_y, bar_x + fill_w, tip_y + bh,
                                fill=cols[i % len(cols)], outline="")
            cv.create_text(bar_x + 6, tip_y + bh//2, text=f"{i+1}. {tip}",
                           fill="#000000" if i < 3 else "#ffffff",
                           font=("Consolas", 8, "bold"), anchor="w")
            tip_y += bh + 3

        # Fight tip below
        if self._fight_tip:
            short = _strip(self._fight_tip)[:80]
            cv.create_text(w//2, h - 10, text=short,
                           fill="#ffa84a", font=("Consolas", 8))

    def _draw_ofa(self, cv, w, h):
        """OFA: 5-stack readiness tracker + engage timing bar."""
        cv.create_rectangle(0, 0, w, h, fill="#060612", outline="")
        cv.create_text(w//2, 10, text="ONE FOR ALL \u2014 5-STACK TIMING",
                       fill="#c77dff", font=("Consolas", 10, "bold"))

        ready = self._ofa_ready  # list of 5 booleans (True=ready)
        player_labels = ["YOU", "P2", "P3", "P4", "P5"]
        slot_w = (w - 60) // 5
        base_x = 30
        base_y = 28

        # 5 readiness boxes
        for i, label in enumerate(player_labels):
            bx = base_x + i * slot_w
            is_ready = (i < len(ready) and ready[i])
            fill = "#1a4a1a" if is_ready else "#2a1a1a"
            border = "#44ff88" if is_ready else "#553333"
            cv.create_rectangle(bx, base_y, bx + slot_w - 4, base_y + 30,
                                fill=fill, outline=border, width=2)
            cv.create_text(bx + (slot_w - 4)//2, base_y + 10,
                           text=label, fill="#44ff88" if is_ready else "#ff4444",
                           font=("Consolas", 9, "bold"))
            cv.create_text(bx + (slot_w - 4)//2, base_y + 22,
                           text="\u2713 READY" if is_ready else "WAIT",
                           fill="#44ff88" if is_ready else "#aa3333",
                           font=("Consolas", 7))

        # Ready count
        n_ready = sum(1 for r in ready if r) if ready else 0
        engage_txt = f"{n_ready}/5 READY \u2014 " + (
            "ENGAGE NOW!" if n_ready >= 5 else "WAIT FOR ALL 5")
        engage_col = "#44ff88" if n_ready >= 5 else "#ffdd00"
        cv.create_text(w//2, base_y + 44, text=engage_txt,
                       fill=engage_col, font=("Consolas", 10, "bold"))

        # Stack bar
        bar_y   = base_y + 60
        bar_w_t = w - 60
        cv.create_rectangle(30, bar_y, w - 30, bar_y + 12,
                            fill="#1a1a2a", outline="#333355")
        if n_ready > 0:
            filled = int(bar_w_t * n_ready / 5)
            cv.create_rectangle(30, bar_y, 30 + filled, bar_y + 12,
                                fill="#44ff88" if n_ready >= 5 else "#ffaa44",
                                outline="")

        # Fight tip
        if self._fight_tip:
            short = _strip(self._fight_tip)[:80]
            cv.create_text(w//2, h - 10, text=short,
                           fill="#c77dff", font=("Consolas", 8))

    def _draw_generic(self, cv, w, h):
        cv.create_text(w//2, h//2, text=self._mode,
                       fill=C["mode"], font=("Consolas", 12, "bold"))


# ââ Right-top âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
class BrawlRightTop(tk.Toplevel):
    GEO = {"x": 1600, "y": 0, "w": 320, "h": 520}

    def __init__(self, root):
        super().__init__(root)
        g = self.GEO
        self.overrideredirect(True)
        self.attributes("-topmost", False)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg=BG)
        con = tk.Frame(self, bg=BG)
        con.pack(fill="both", expand=True, padx=1, pady=1)
        con.columnconfigure(0, weight=1)

        sf = tk.Frame(con, bg="#16161f", highlightbackground=BORDER, highlightthickness=1)
        sf.grid(row=0, column=0, sticky="nsew")
        sr = tk.Frame(sf, bg="#16161f")
        sr.pack(fill="x", padx=6, pady=4)
        self._stats = {}
        for col, (k, t) in enumerate([
            ("mode","BRAWL"),("hp","100%"),("kda","0/0/0"),("gold","0g")
        ]):
            lb = tk.Label(sr, text=t, bg="#16161f", fg=C["stats"],
                          font=("Consolas", 11, "bold"))
            lb.grid(row=0, column=col, padx=4)
            self._stats[k] = lb
        for c in range(4): sr.columnconfigure(c, weight=1)
        con.rowconfigure(0, weight=0, minsize=36)

        self._action_var, self._act_lbl = _bar(con, 1, "ACTION", C["action"], minsize=44)
        self._event_txt = _sec(con, 2, "EVENT",      C["event"], minsize=150)
        self._items_txt = _sec(con, 3, "ITEMS",      C["items"], minsize=60)
        self._fight_txt = _sec(con, 4, "FIGHT RULE", C["fight"], minsize=160)

    def update(self, data: dict):
        mode = data.get("game_mode", "BRAWL").upper()
        mode_short = ("NEX OVERLAY APP E" if "NEXUS" in mode else
                      "URF"       if "URF" in mode or "ULTBOOK" in mode else
                      "OFA"       if "OFA" in mode or "GAMEMODEX" in mode else
                      mode[:9])
        self._stats["mode"].configure(text=mode_short,
            fg=C["event"] if "NEXUS" in mode else
               "#44ffcc" if "URF" in mode else
               "#c77dff" if "OFA" in mode else C["stats"])
        hp = data.get("hp_pct", 100)
        self._stats["hp"].configure(text=f"{hp}%",
            fg="#ff4444" if hp < 30 else ("#ffaa44" if hp < 60 else C["stats"]))
        self._stats["kda"].configure(text=data.get("kda", "0/0/0"))
        self._stats["gold"].configure(text=f"{data.get('gold',0)}g")

        act = data.get("action", "") or "\u2014"
        self._action_var.set(act)
        self._act_lbl.configure(fg="#ff2244" if hp <= 35 else C["action"])

        event_str = data.get("event_name", "") or data.get("event_advice", "")
        timer     = data.get("event_timer", 0)
        if event_str:
            ev_line = f"{event_str}\n{timer}s remaining" if timer else event_str
            _write_rich(self._event_txt, ev_line, C["event"])
        else:
            _write_rich(self._event_txt, "No active event", LABEL_C)

        _write_rich(self._items_txt, data.get("reset_item", "\u2014"), C["items"])
        _write_rich(self._fight_txt, data.get("fight_rule",  "\u2014"), C["fight"])


# ââ Right-bot âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

class BrawlAiStatusBar(tk.Toplevel):
    GEO = {"x": 1600, "y": 520, "w": 320, "h": 20}
    def __init__(self, root):
        super().__init__(root); g = self.GEO
        self.overrideredirect(True); self.attributes("-topmost", False)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg="#050508")
        ff = tk.Frame(self, bg="#050508"); ff.pack(fill="both", expand=True)
        self._lbl = tk.Label(ff, text="AI  IDLE", bg="#050508", fg="#444466", font=("Consolas",9), anchor="w")
        self._lbl.pack(side="left", padx=(4,2), fill="x", expand=True)
        self._cd_var = tk.StringVar(value="")
        tk.Label(ff, textvariable=self._cd_var, bg="#050508", fg="#336655", font=("Consolas",9), anchor="e", width=8).pack(side="right", padx=(2,4))
        self._state="idle"; self._next_scan_at=0.0; self._scan_interval=15.0; self._tick_job=None; self._tick()
    def set_scanning(self, pct:int=0): self._state="scanning"; self._lbl.configure(text=f"SCAN {pct}%",fg="#22ccaa")
    def set_done(self, r=""): self._state="done"; self._next_scan_at=time.monotonic()+self._scan_interval; self._lbl.configure(text="✓ DONE",fg="#44ff88"); self.after(2000,self._idle)
    def set_force_scan(self): self._lbl.configure(text="⚡ FORCE",fg="#ffdd00")
    def _idle(self): self._state="idle"; self._lbl.configure(text="AI  IDLE",fg="#444466")
    def _tick(self):
        try:
            now=time.monotonic()
            if self._next_scan_at>now: self._cd_var.set(f"next:{int(self._next_scan_at-now)}s")
            self._tick_job=self.after(1000,self._tick)
        except tk.TclError: pass


class BrawlCoachStatusBar(tk.Toplevel):
    GEO = {"x": 1600, "y": 540, "w": 320, "h": 20}
    def __init__(self, root):
        super().__init__(root); g = self.GEO
        self.overrideredirect(True); self.attributes("-topmost", False)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg="#060508")
        ff = tk.Frame(self, bg="#060508"); ff.pack(fill="both", expand=True)
        self._lbl = tk.Label(ff, text="COACH  IDLE", bg="#060508", fg="#444455", font=("Consolas",9), anchor="w")
        self._lbl.pack(side="left", padx=(4,2), fill="x", expand=True)
        self._state="idle"; self._call_start=0.0; self._tick_job=None
        self._data_file=Path(__file__).parent.parent/"data"/"brawl_coaching_data.json"
        self._last_mtime=0.0; self._tick()
    def set_calling(self): self._state="calling"; self._call_start=time.monotonic(); self._lbl.configure(text="COACH  ...",fg="#ffaa44")
    def set_done(self, action:str=""): self._state="done"; self._lbl.configure(text=f"✓ {action[:26]}" if action else "✓ DONE",fg="#44ff88"); self.after(3000,self._idle)
    def _idle(self): self._state="idle"; self._lbl.configure(text="COACH  IDLE",fg="#444455")
    def _tick(self):
        try:
            if self._data_file.exists():
                mt=self._data_file.stat().st_mtime
                if mt!=self._last_mtime:
                    self._last_mtime=mt
                    try:
                        import json as _j; _d=_j.loads(self._data_file.read_text(encoding="utf-8"))
                        _a=_d.get("action","") or _d.get("round_strategy","")
                        if _a and self._state=="idle": self.set_done(_a)
                    except Exception: pass
            if self._state=="calling": self._lbl.configure(text=f"COACH  ...  {int(time.monotonic()-self._call_start)}s",fg="#ffaa44")
            self._tick_job=self.after(1000,self._tick)
        except tk.TclError: pass

class BrawlRightBot(tk.Toplevel):
    GEO = {"x": 1600, "y": 560, "w": 320, "h": 520}

    def __init__(self, root):
        super().__init__(root)
        g = self.GEO
        self.overrideredirect(True)
        self.attributes("-topmost", True)   # covers taskbar
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg=BG)
        con = tk.Frame(self, bg=BG)
        con.pack(fill="both", expand=True, padx=1, pady=1)
        con.columnconfigure(0, weight=1)

        self._clock_var, _ = _bar(con, 0, "CLOCK", C["clock"], minsize=40)
        con.rowconfigure(0, weight=0, minsize=40)

        self._econ_txt  = _sec(con, 1, "ITEMS / RESET", C["econ"],      minsize=100)
        self._obj_txt   = _sec(con, 2, "OBJECTIVE",     C["objective"], minsize=120)
        self._risk_txt  = _sec(con, 3, "RISK",          C["risk"],      minsize=100)

        f = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        f.grid(row=4, column=0, sticky="nsew", pady=(2, 0))
        tk.Label(f, text="WAVE / PUSH", bg=BG_SEC, fg=LABEL_C,
                 font=_LBL_HD, anchor="w").pack(anchor="w", padx=8, pady=(4, 0))
        self._wave_txt = _make_txt(f, C["wave"])
        self._wave_txt.tag_configure("base", foreground=C["wave"])
        self._wave_txt.pack(fill="both", expand=True, pady=(0, 4))
        con.rowconfigure(4, weight=1, minsize=120)

        self._clock_base = 0.0
        self._clock_wall = 0.0
        self._clock_job  = None

    def sync_clock(self, t: float):
        self._clock_base = t
        self._clock_wall = time.monotonic()
        if self._clock_job is None:
            self._tick()

    def _tick(self):
        if self._clock_wall > 0:
            total = max(0, self._clock_base + time.monotonic() - self._clock_wall)
            self._clock_var.set(f"{int(total//60)}:{int(total%60):02d}")
        self._clock_job = self.after(1000, self._tick)

    def update(self, data: dict):
        _write_rich(self._econ_txt, data.get("reset_item", "\u2014"), C["econ"])
        _write_rich(self._obj_txt,  data.get("objective",  "\u2014"), C["objective"])
        _write_rich(self._risk_txt, data.get("risk",       "\u2014"), C["risk"])
        _write_rich(self._wave_txt, data.get("wave",       "\u2014"), C["wave"])
        gt = data.get("game_time_s", 0)
        if gt:
            self.sync_clock(gt)

    def destroy_clock(self):
        if self._clock_job:
            try: self.after_cancel(self._clock_job)
            except Exception: pass


# ââ Bottom strip ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
class BrawlBottomStrip(tk.Toplevel):
    GEO = {"x": 0, "y": 880, "w": 1920, "h": 200}

    def __init__(self, root):
        super().__init__(root)
        g = self.GEO
        self.overrideredirect(True)
        self.attributes("-topmost", True)   # covers taskbar
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg=BG)
        con = tk.Frame(self, bg=BG)
        con.pack(fill="both", expand=True, padx=1, pady=1)
        con.columnconfigure(0, weight=2, minsize=200)
        con.columnconfigure(1, weight=9)
        con.columnconfigure(2, weight=2, minsize=240)
        con.rowconfigure(0, weight=1)

        bf = tk_font.Font(family="Segoe UI", size=11, weight="bold")

        def _txt(parent, color):
            t = tk.Text(parent, bg=BG_SEC, fg=color, font=("Segoe UI", 11),
                        wrap="word", bd=0, highlightthickness=0,
                        insertbackground=BG_SEC, state="disabled",
                        cursor="arrow", padx=10, pady=3, height=1)
            t.pack(fill="both", expand=True, pady=(0, 5))
            t.tag_configure("ally",  foreground="#44ff88", font=bf)
            t.tag_configure("enemy", foreground="#ff4444", font=bf)
            t.tag_configure("time",  foreground="#ffdd00", font=bf)
            t.tag_configure("base",  foreground=color)
            return t

        # Left â MODE INFO
        fl = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        fl.grid(row=0, column=0, sticky="nsew")
        tk.Label(fl, text="MODE INFO", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 9, "bold"), anchor="w"
                 ).pack(anchor="w", padx=10, pady=(5, 0))
        self._mode_txt = _txt(fl, C["mode"])

        # Center â EVENT / MAP CANVAS
        fc = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        fc.grid(row=0, column=1, sticky="nsew", padx=(2, 2))
        tk.Label(fc, text="EVENT / MAP / POWER", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 10, "bold"), anchor="w"
                 ).pack(anchor="w", padx=8, pady=(4, 0))
        self._event_canvas = BrawlEventCanvas(fc)
        self._event_canvas.pack(fill="both", expand=True, pady=(0, 3))

        # Right â FIGHT CONDITION
        fr = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        fr.grid(row=0, column=2, sticky="nsew")
        tk.Label(fr, text="FIGHT / OBJECTIVE", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 9, "bold"), anchor="w"
                 ).pack(anchor="w", padx=10, pady=(5, 0))
        self._fight_txt = _txt(fr, C["fight"])

    def update(self, data: dict):
        mode = data.get("game_mode", "") or ""
        ev   = data.get("event_name", "")  or data.get("event_advice", "") or ""
        t    = data.get("event_timer", 0)
        mode_line = mode
        if ev: mode_line += f"\nEvent: {ev}"
        if t:  mode_line += f"\n{t}s remaining"
        _write_rich(self._mode_txt, mode_line.strip() or mode, C["mode"])

        # Phase 6 Step 4.1: only pass nexus HP for NB where vision tracks it.
        # URF/OFA vision does not track nexus HP; passing 100 is misleading.
        _is_nb = "NEXUS" in mode.upper() or "NB" in mode.upper()
        self._event_canvas.update_event(
            event      = ev,
            timer      = t,
            location   = data.get("event_location", ""),
            fight_tip  = data.get("immediate", ""),
            my_nexus   = data.get("my_nexus_hp", 100) if _is_nb else 100,
            enemy_nexus= data.get("enemy_nexus_hp", 100) if _is_nb else 100,
            mode       = mode,
            hp_pct     = data.get("hp_pct", 100),
            ability_tips = data.get("ability_tips", []),
            ofa_ready    = data.get("ofa_ready", []),
        )

        immediate = data.get("immediate", "") or ""
        obj       = data.get("objective",  "") or ""
        parts     = []
        if immediate: parts.append(immediate)
        if obj:       parts.append(f"Obj: {obj}")
        _write_rich(self._fight_txt,
                    "\n".join(parts) if parts else "\u2014",
                    C["fight"])
