"""
modes/aram_overlay.py  â v2 (full upgrade)

ARAM / ARAM Mayhem dedicated overlay.

Right-top  (320Ã520): Stats / ACTION / ITEMS / FIGHT RULE / AUGMENTS
Right-bot  (320Ã520): CLOCK / FOUNTAIN+ITEM / POSITIONING / RISK / OBJECTIVE
Bottom     (1920Ã160):
    Left  220px  â COMP ANALYSIS
    Center 1440px â ARAM LANE CANVAS  (upgraded: health packs, minion wave,
                     recommended zone arrow, tower HP bars, danger overlay)
    Right  260px  â FIGHT CONDITION / IMMEDIATE

[A]ally[/A]  [E]enemy[/E]  [T]timing[/T]  tags supported in all text panels.
"""

import tkinter as tk
import tkinter.font as tk_font
import time
import re
from pathlib import Path


def _probe_league_bottom() -> int:
    """
    Detect the actual bottom y-coordinate of the League of Legends game
    viewport on-screen.  Returns 900 as fallback if League is not found.

    League runs windowed with an ~8px DWM shadow on each side.  The visible
    window bottom = rect.bottom - 8.  That equals title_bar + game_height
    (22 + 900 = 922 for a standard 1600x900 windowed install).

    We always return 900 as the FLOOR so the panel never hides data if
    the window is in an unexpected state.
    """
    try:
        import ctypes, ctypes.wintypes as wt
        class RECT(ctypes.Structure):
            _fields_ = [("left",ctypes.c_int),("top",ctypes.c_int),
                        ("right",ctypes.c_int),("bottom",ctypes.c_int)]
        result = [None]
        def _cb(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            if "League of Legends" in buf.value and "(TM)" in buf.value:
                r = RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
                # visible bottom = window bottom minus DWM shadow (8px)
                result[0] = max(900, r.bottom - 8)
            return True
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        ctypes.windll.user32.EnumWindows(WNDPROC(_cb), 0)
        return result[0] or 900
    except Exception:
        return 900


BG      = "#0b0b12"
BG_SEC  = "#111119"
BORDER  = "#252535"
LABEL_C = "#9090aa"

C = {
    "action":   "#ff2244",
    "items":    "#4ab0ff",
    "fight":    "#ffa84a",
    "risk":     "#ff4a6a",
    "econ":     "#a8c023",
    "position": "#c77dff",
    "comp":     "#a8e6cf",
    "clock":    "#ffdd00",
    "stats":    "#d0d0e0",
    "aug":      "#ffd700",
    "obj":      "#44ffcc",
}

_LBL    = ("Consolas", 10, "bold")
_LBL_HD = ("Consolas", 12, "bold")
_VAL_LG = ("Segoe UI", 14, "bold")
_BODY   = ("Segoe UI", 12)
_TAG_RE = re.compile(r'\[A\](.*?)\[/A\]|\[E\](.*?)\[/E\]|\[T\](.*?)\[/T\]', re.DOTALL)


def _strip(text):
    return re.sub(r'\[/?[AET]\]', '', text or "")


def _write_rich(w, text, base_color):
    """Write text with [A]/[E]/[T] tag support."""
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


# ââ ARAM Lane Canvas v2 âââââââââââââââââââââââââââââââââââââââââââââââââââââââ
# YOUR BASE â SAFE â POKE â MID â ENGAGE â DANGER â ENEMY BASE
# Features: zone bands, tower HP bars, health pack icons, minion wave marker,
#           player dot (current zone), recommended zone arrow, danger flash.
# âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
_ZONES     = ["safe", "poke", "mid", "engage", "danger"]
_ZONE_PX   = {"safe": 0.10, "poke": 0.30, "mid": 0.50, "engage": 0.70, "danger": 0.88}
_ZONE_FRAC = [("safe",0.20),("poke",0.20),("mid",0.20),("engage",0.20),("danger",0.20)]
_ZONE_BG   = {
    "safe":   "#0d2b0d",
    "poke":   "#2b2b00",
    "mid":    "#222232",
    "engage": "#2b1500",
    "danger": "#2b0000",
}
_ZONE_BRIGHT = {
    "safe":   "#1a5a1a",
    "poke":   "#585800",
    "mid":    "#303030",
    "engage": "#5c2a00",
    "danger": "#5c0000",
}

# Health packs spawn at ~35% and ~65% of lane
_HP_PACK_FRAC = [0.35, 0.65]


def _infer_zone(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ("all-in", "all in", "engage now", "commit", "dive in", "flash in")):
        return "engage"
    if any(w in t for w in ("danger", "overextended", "back immediately", "retreat now", "run")):
        return "danger"
    if any(w in t for w in ("poke only", "max range", "poke phase", "harass from")):
        return "poke"
    if any(w in t for w in ("fountain", "go base", "recall", "safe zone", "full back")):
        return "safe"
    return "mid"


def _infer_recommended(positioning: str) -> str:
    """Extract recommended positioning from positioning text."""
    p = (positioning or "").lower()
    if any(w in p for w in ("behind frontline", "stay back", "poke range", "max range")):
        return "poke"
    if any(w in p for w in ("step up", "forward", "close range", "melee range")):
        return "engage"
    if any(w in p for w in ("safe side", "fountain direction", "disengage")):
        return "safe"
    return "mid"


class AramLaneCanvas(tk.Frame):
    """
    ARAM Howling Abyss top-down lane display.
    - 5 colour zones (safe â danger) with brightness for active zone
    - Tower HP bars at 22% and 78% of lane width
    - Health pack icons at 35% and 65%
    - Minion wave marker (circle with colour) if available
    - Player dot (white) at current zone
    - Arrow pointing to recommended zone when different from current
    - Fight state label at top
    """

    def __init__(self, parent, h=130):
        super().__init__(parent, bg=BG_SEC)
        self._h = h
        self.canvas = tk.Canvas(self, bg=BG_SEC, bd=0, highlightthickness=0, height=h)
        self.canvas.pack(fill="both", expand=True, padx=4, pady=2)
        self._zone       = "mid"
        self._rec_zone   = "mid"
        self._my_tower   = 100
        self._en_tower   = 100
        self._fight_text = ""
        self._hp_pct     = 100
        self._wave_pct   = 50  # 0=at your base, 100=at enemy base (estimated)
        self._hp_packs   = [True, True]  # whether packs are available
        self._team       = "ORDER"  # ORDER=left base, CHAOS=right base
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

    def update_state(self, zone: str = "mid", recommended: str = "mid",
                     fight_text: str = "", my_tower = None,
                     enemy_tower = None, hp_pct: int = 100,
                     wave_pct: int = 50, hp_packs: list = None,
                     team: str = "ORDER"):
        self._zone      = zone
        self._rec_zone  = recommended
        self._fight_text= fight_text
        self._my_tower  = my_tower
        self._en_tower  = enemy_tower
        self._hp_pct    = hp_pct
        self._wave_pct  = wave_pct
        self._team      = team
        if hp_packs is not None:
            self._hp_packs = hp_packs
        self._redraw()

    def _redraw(self):
        cv = self.canvas
        cv.delete("all")
        w  = cv.winfo_width() or 900
        h  = self._h
        MID_Y = h // 2
        TOP_Y = 20
        BOT_Y = h - 16

        # Team-aware orientation: CHAOS = red side = base on RIGHT
        _is_chaos = (getattr(self, "_team", "ORDER") or "ORDER").upper() == "CHAOS"
        _zone_frac = list(reversed(_ZONE_FRAC)) if _is_chaos else _ZONE_FRAC
        _base_l_txt = "ENEMY\nBASE" if _is_chaos else "YOUR\nBASE"
        _base_r_txt = "YOUR\nBASE"  if _is_chaos else "ENEMY\nBASE"
        _base_l_col = "#883333"      if _is_chaos else "#336688"
        _base_r_col = "#336688"      if _is_chaos else "#883333"
        _t_mine  = 0.78 if _is_chaos else 0.22
        _t_enemy = 0.22 if _is_chaos else 0.78
        _wave_frac = max(0.05, min(0.95, (1.0 - self._wave_pct/100) if _is_chaos else (self._wave_pct/100)))
        _player_frac = (1.0 - _ZONE_PX.get(self._zone, 0.50)) if _is_chaos else _ZONE_PX.get(self._zone, 0.50)

        # ââ Zone bands ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
        lx = 0
        zone_edges = {}
        for zone, frac in _zone_frac:
            rx = int(lx + frac * w)
            fill = _ZONE_BRIGHT[zone] if zone == self._zone else _ZONE_BG[zone]
            cv.create_rectangle(lx, TOP_Y, rx, BOT_Y, fill=fill, outline="")
            # Zone label
            label_col = "#ffffff" if zone == self._zone else "#99aabb"
            LABEL_Y = TOP_Y + (BOT_Y - TOP_Y) // 4
            cv.create_text((lx + rx) // 2, LABEL_Y,
                           text=zone.upper(), fill=label_col,
                           font=("Consolas", 14, "bold"))
            zone_edges[zone] = ((lx + rx) // 2, lx, rx)
            lx = rx

        # ââ Lane edge lines âââââââââââââââââââââââââââââââââââââââââââââââââââ
        cv.create_line(0, TOP_Y, w, TOP_Y, fill="#222233", width=1)
        cv.create_line(0, BOT_Y, w, BOT_Y, fill="#222233", width=1)

        # ââ Base labels ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
        cv.create_text(4, MID_Y, text=_base_l_txt, fill=_base_l_col,
                       font=("Consolas", 11, "bold"), anchor="w", justify="center")
        cv.create_text(w - 4, MID_Y, text=_base_r_txt, fill=_base_r_col,
                       font=("Consolas", 11, "bold"), anchor="e", justify="center")

        # ââ Tower HP bars ââââââââââââââââââââââââââââââââââââââââââââââââââââââ
        def _tower(tx, hp, color, label):
            bh  = BOT_Y - TOP_Y
            cv.create_rectangle(tx - 5, TOP_Y, tx + 5, BOT_Y,
                                fill="#111118", outline="#333344")
            if hp is None:
                # Unknown HP: colour-code the bar gray
                cv.create_text(tx, BOT_Y + 4, text="?",
                               fill="#9090aa", font=("Consolas", 7, "bold"), anchor="n")
            else:
                fh = int(bh * max(0, hp) / 100)
                bar_col = ("#ff4444" if hp < 30 else
                           "#ffaa22" if hp < 60 else color)
                if fh > 0:
                    cv.create_rectangle(tx - 4, BOT_Y - fh, tx + 4, BOT_Y - 1,
                                        fill=bar_col, outline="")
                # HP% label inside bar at bottom, readable 8pt
                txt_y = min(BOT_Y - 4, BOT_Y - fh + 12) if fh > 14 else BOT_Y + 4
                anchor = "s" if fh > 14 else "n"
                cv.create_text(tx, txt_y, text=f"{hp}%",
                               fill="#ffffff" if fh > 14 else bar_col,
                               font=("Consolas", 8, "bold"), anchor=anchor)

        _tower(int(w * _t_mine),  self._my_tower, "#3399cc", "MY T1")
        _tower(int(w * _t_enemy), self._en_tower, "#cc3333", "EN T1")

        # ââ Health packs âââââââââââââââââââââââââââââââââââââââââââââââââââââââ
        for i, frac in enumerate(_HP_PACK_FRAC):
            px = int(w * frac)
            available = self._hp_packs[i] if i < len(self._hp_packs) else True
            _PACK_Y = MID_Y + 5
            if available:
                cv.create_oval(px - 7, _PACK_Y - 7, px + 7, _PACK_Y + 7,
                               fill="#44ff44", outline="#22aa22", width=1)
                cv.create_text(px, _PACK_Y, text="+", fill="#000000",
                               font=("Consolas", 9, "bold"))
            else:
                cv.create_oval(px - 6, _PACK_Y - 6, px + 6, _PACK_Y + 6,
                               fill="", outline="#334433", width=1)

        # ââ Minion wave marker ââââââââââââââââââââââââââââââââââââââââââââââââ
        wave_x = int(w * _wave_frac)
        wave_col = "#8888aa" if self._wave_pct < 50 else "#aaaaff"
        _WAV_Y = TOP_Y + (BOT_Y - TOP_Y) * 3 // 4   # lower quarter for wave
        cv.create_oval(wave_x - 5, _WAV_Y - 6, wave_x + 5, _WAV_Y + 6,
                       fill=wave_col, outline="#5555aa", width=1)
        cv.create_text(wave_x, _WAV_Y + 10, text="WAVE",
                       fill=wave_col, font=("Consolas", 7))

        # ââ Player dot ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
        px = int(w * _player_frac)
        player_col = ("#ff4444" if self._hp_pct < 30 else
                      "#ffaa44" if self._hp_pct < 60 else "#ffffff")
        _DOT_Y = BOT_Y - 22   # lower portion — below zone labels & HP packs
        cv.create_oval(px - 10, _DOT_Y - 10, px + 10, _DOT_Y + 10,
                       fill=player_col, outline="#ffdd00", width=2)
        cv.create_text(px, _DOT_Y, text="YOU",
                       fill="#000000", font=("Consolas", 7, "bold"))

        # ââ Recommended zone arrow ââââââââââââââââââââââââââââââââââââââââââââ
        if self._rec_zone != self._zone:
            tx  = int(w * _ZONE_PX.get(self._rec_zone, 0.50))
            mid_arrow_y = BOT_Y - 22  # same level as YOU dot
            cv.create_line(px, mid_arrow_y, tx, mid_arrow_y,
                           fill="#ffdd00", width=2, arrow=tk.LAST,
                           arrowshape=(8, 10, 4))
            cx = (px + tx) // 2
            cv.create_text(cx, mid_arrow_y - 10, text=f"\u2192 {self._rec_zone.upper()}",
                           fill="#ffdd00", font=("Consolas", 8, "bold"))

        # ââ Column headers ââââââââââââââââââââââââââââââââââââââââââââââââââââ
        cv.create_text(4, h - 8, text="\u2190 YOUR BASE",
                       fill="#4488aa", font=("Consolas", 9, "bold"), anchor="w")
        cv.create_text(w - 4, h - 8, text="ENEMY BASE \u2192",
                       fill="#aa4444", font=("Consolas", 9, "bold"), anchor="e")


# ââ Right-top âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ


def _add_rc_menu(widget, force_scan_cb=None):
    """Attach right-click context menu to any overlay widget or toplevel."""
    import tkinter as _tk
    def _show_menu(event):
        m = _tk.Menu(widget.winfo_toplevel(), tearoff=0,
                     bg="#1a1a24", fg="#c0c0d0",
                     activebackground="#2a2a3a", activeforeground="#ffffff",
                     font=("Segoe UI", 9))
        if force_scan_cb:
            m.add_command(label="⚡  Force Vision Scan  [Ctrl+Tab]", command=force_scan_cb)
            m.add_separator()
        m.add_command(label="Reload Overlay", command=lambda: _do_reload(widget))
        m.add_separator()
        m.add_command(label="Toggle Topmost",
                      command=lambda: widget.winfo_toplevel().attributes(
                          "-topmost", not widget.winfo_toplevel().attributes("-topmost")))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()
    def _do_reload(w):
        try:
            from pathlib import Path as _P; import json as _j, time as _t
            _ts = _P(__file__).parent.parent / "data" / "coaching_ts.json"
            _ts.write_text(_j.dumps({"force": _t.time()}), encoding="utf-8")
        except Exception: pass
    widget.bind("<Button-3>", _show_menu)
    # Also bind to all child widgets
    for child in widget.winfo_children() if hasattr(widget, 'winfo_children') else []:
        try: child.bind("<Button-3>", _show_menu)
        except Exception: pass

class AramRightTop(tk.Toplevel):
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
            ("time","0:00"),("hp","100%"),("kda","0/0/0"),("mode","ARAM")
        ]):
            lb = tk.Label(sr, text=t, bg="#16161f", fg=C["stats"],
                          font=("Consolas", 11, "bold"))
            lb.grid(row=0, column=col, padx=4)
            self._stats[k] = lb
        for c in range(4): sr.columnconfigure(c, weight=1)
        con.rowconfigure(0, weight=0, minsize=36)

        self._action_var, self._act_lbl = _bar(con, 1, "ACTION", C["action"], minsize=44)
        self._imm_txt   = _sec(con, 2, "IMMEDIATE",  C["fight"], minsize=130)
        self._fight_txt = _sec(con, 3, "FIGHT RULE", C["fight"], minsize=150)
        self._risk_txt  = _sec(con, 4, "RISK",       C["risk"],  minsize=150)
        self._aug_txt   = None  # augments hidden from right panel
        _add_rc_menu(self)

    def update(self, data: dict):
        self._stats["time"].configure(text=data.get("game_time", "0:00"))
        hp = data.get("hp_pct", 100)
        self._stats["hp"].configure(
            text=f"{hp}% HP",
            fg="#ff4444" if hp < 30 else ("#ffaa44" if hp < 60 else C["stats"]))
        self._stats["kda"].configure(text=data.get("kda", "0/0/0"))
        mode = data.get("game_mode", "ARAM")
        self._stats["mode"].configure(
            text="MAYHEM" if "MAYHEM" in mode.upper() else "ARAM",
            fg=C["aug"] if "MAYHEM" in mode.upper() else C["stats"])
        act = data.get("action", "") or "\u2014"
        self._action_var.set(act)
        self._act_lbl.configure(fg="#ff2244" if hp <= 30 else C["action"])
        _write_rich(self._imm_txt,   data.get("immediate",   "—"), C["fight"])
        _write_rich(self._fight_txt, data.get("fight_rule",  "—"), C["fight"])
        _write_rich(self._risk_txt,  data.get("risk",        "—"), C["risk"])


# ââ Right-bot âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

# ═══ ARAM AI / Coach Status Bars ═══════════════════════════════════════════
class AramAiStatusBar(tk.Toplevel):
    """20px scan progress bar — sits between right-top and right-bot."""
    GEO = {"x": 1600, "y": 520, "w": 320, "h": 20}
    def __init__(self, root):
        super().__init__(root)
        g = self.GEO
        self.overrideredirect(True); self.attributes("-topmost", False)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg="#050508")
        f = tk.Frame(self, bg="#050508"); f.pack(fill="both", expand=True)
        self._lbl = tk.Label(f, text="AI  IDLE", bg="#050508", fg="#444466",
                             font=("Consolas", 9), anchor="w")
        self._lbl.pack(side="left", padx=(4,2), fill="x", expand=True)
        self._cd_var = tk.StringVar(value="")
        self._cd_lbl = tk.Label(f, textvariable=self._cd_var, bg="#050508",
                                fg="#336655", font=("Consolas", 9), anchor="e", width=8)
        self._cd_lbl.pack(side="right", padx=(2,4))
        self._state = "idle"; self._progress = 0
        self._next_scan_at = 0.0; self._scan_interval = 15.0
        self._tick_job = None; self._tick()
    def set_scanning(self, pct: int = 0):
        self._state = "scanning"; self._progress = max(0, min(100, pct)); self._refresh()
    def set_done(self, result: str = ""):
        self._state = "done"; self._progress = 100
        self._next_scan_at = time.monotonic() + self._scan_interval; self._refresh()
        self.after(2000, self._set_idle)
    def set_force_scan(self):
        self._state = "force"; self._progress = 0; self._refresh()
    def _set_idle(self):
        if self._state in ("done", "force"):
            self._state = "idle"; self._progress = 0; self._refresh()
    def _refresh(self):
        s, p = self._state, self._progress
        if s == "scanning":
            bar = "█"*(p//10) + "░"*(10-p//10)
            text, fg, cd_fg = f"SCAN  {bar}  {p}%", "#22ccaa", "#336655"
        elif s == "force":  text, fg, cd_fg = "⚡ FORCE SCAN", "#ffdd00", "#ffdd00"
        elif s == "done":   text, fg, cd_fg = "✓ DONE", "#44ff88", "#44ff88"
        else:               text, fg, cd_fg = "AI  IDLE", "#444466", "#336655"
        try:
            self._lbl.configure(text=text, fg=fg)
            self._cd_lbl.configure(fg=cd_fg)
        except tk.TclError: pass
    def _tick(self):
        try:
            now = time.monotonic()
            if self._next_scan_at > now:
                self._cd_var.set(f"next:{int(self._next_scan_at-now)}s")
            elif self._state == "idle":
                self._cd_var.set("")
            self._tick_job = self.after(1000, self._tick)
        except tk.TclError: pass


class AramCoachStatusBar(tk.Toplevel):
    """20px coach call progress bar."""
    GEO = {"x": 1600, "y": 540, "w": 320, "h": 20}
    def __init__(self, root):
        super().__init__(root)
        g = self.GEO
        self.overrideredirect(True); self.attributes("-topmost", False)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg="#060508")
        f = tk.Frame(self, bg="#060508"); f.pack(fill="both", expand=True)
        self._lbl = tk.Label(f, text="COACH  IDLE", bg="#060508", fg="#444455",
                             font=("Consolas", 9), anchor="w")
        self._lbl.pack(side="left", padx=(4,2), fill="x", expand=True)
        self._ts_var = tk.StringVar(value="")
        tk.Label(f, textvariable=self._ts_var, bg="#060508", fg="#334455",
                 font=("Consolas", 9), anchor="e", width=8).pack(side="right", padx=(2,4))
        self._state = "idle"; self._last_action = ""; self._call_start = 0.0
        self._tick_job = None
        self._data_file = Path(__file__).parent.parent / "data" / "aram_coaching_data.json"
        self._last_mtime = 0.0; self._tick()
    def set_calling(self):
        self._state = "calling"; self._call_start = time.monotonic(); self._refresh()
    def set_done(self, action: str = ""):
        self._state = "done"; self._last_action = (action or "")[:28]; self._refresh()
        self.after(3000, self._set_idle)
    def _set_idle(self):
        if self._state in ("done","calling"):
            self._state = "idle"; self._refresh()
    def _refresh(self):
        s = self._state
        if s == "calling":
            text, fg = f"COACH  ⋯  {int(time.monotonic()-self._call_start)}s", "#ffaa44"
        elif s == "done":
            text, fg = f"✓ {self._last_action}" if self._last_action else "✓ DONE", "#44ff88"
        else:
            text, fg = "COACH  IDLE", "#444455"
        try: self._lbl.configure(text=text, fg=fg)
        except tk.TclError: pass
    def _tick(self):
        try:
            if self._data_file.exists():
                mtime = self._data_file.stat().st_mtime
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    try:
                        import json as _j
                        _d = _j.loads(self._data_file.read_text(encoding="utf-8"))
                        _act = _d.get("action","") or _d.get("reset_item","")
                        if _act and self._state == "idle":
                            self._state = "done"; self._last_action = str(_act)[:28]
                            self._refresh(); self.after(4000, self._set_idle)
                    except Exception: pass
            if self._state == "calling": self._refresh()
            self._tick_job = self.after(1000, self._tick)
        except tk.TclError: pass


# ═══ Item Build Canvas ═══════════════════════════════════════════════════════
class _ItemBuildCanvas(tk.Frame):
    """2-row x 3-col item build display with colored tiles + optional 3rd row."""
    _ABBR = {
        "blade of the ruined king":"BotRK","infinity edge":"IE",
        "guinsoo's rageblade":"Rageblade","phantom dancer":"PD",
        "runaan's hurricane":"RH","kraken slayer":"KS",
        "berserker's greaves":"Berserks","wit's end":"Wit's End",
        "mortal reminder":"Mortal R","lord dominik's regards":"LDR",
        "immortal shieldbow":"Shieldbow","galeforce":"Galeforce",
        "the collector":"Collector","navori quickblades":"Navori",
        "quicksilver sash":"QSS","mercurial scimitar":"Mercurial",
        "ravenous hydra":"Rav Hydra","death's dance":"Death's D",
        "deaths dance":"Death's D","sterak's gage":"Sterak's",
        "banshee's veil":"Banshee's","serpent's fang":"Serp Fang",
        "sorcerer's shoes":"Sorc Shoes","plated steelcaps":"Steelcaps",
        "ionian boots of lucidity":"Ionian","boots of swiftness":"Swift",
        "mercury's treads":"Mercs","trinity force":"Tri Force",
        "black cleaver":"BC","spear of shojin":"Shojin",
        "manamune":"Manamune","muramana":"Muramana",
        "divine sunderer":"Div Sund","heartsteel":"Heartsteel",
        "sundered sky":"Sund Sky","hullbreaker":"Hullbrkr",
    }
    def __init__(self, parent):
        super().__init__(parent, bg="#0a0a12")
        self._cv = tk.Canvas(self, bg="#0a0a12", bd=0, highlightthickness=0)
        self._cv.pack(fill="both", expand=True)
        self._build = []; self._owned = set(); self._extra = ""; self._imgs = []
        # AUDIT-OPUS PERF-001: cache PIL-decoded icons keyed by (slug, size) so
        # _redraw() no longer re-opens and re-resizes the PNG on every Configure
        # event or set_items() call.  Eliminates ~6 PIL decodes per redraw.
        self._icon_cache: dict = {}
        self._cv.bind("<Configure>", lambda e: self._redraw())
    def set_items(self, build_str: str, owned_str: str, extra_str: str):
        raw = [x.lstrip("+").strip() for x in build_str.split(",") if x.strip()]
        self._build = raw[:7]
        self._owned = {x.strip().lower() for x in owned_str.split(",") if x.strip()}
        self._extra = extra_str.strip()
        self._redraw()
    def _abbr(self, name: str) -> str:
        low = name.lower().strip()
        if low in self._ABBR: return self._ABBR[low]
        import re as _re
        words = _re.sub(r"'s?|'", "", low).split()
        skip = {"of","the","a","an","and","for","to","s"}
        r = "".join(w[0].upper() for w in words if w not in skip)
        return r[:6] if r else name[:5]
    def _load_icon(self, name: str, sz: int):
        import re as _re
        slug = _re.sub(r"[^a-z0-9]+", "-", _re.sub(r"'s?|'", "", name.lower())).strip("-")
        # AUDIT-OPUS PERF-001: serve from cache when available
        _cache_key = (slug, sz)
        _cached = self._icon_cache.get(_cache_key)
        if _cached is not None:
            return _cached
        try:
            from PIL import Image, ImageTk
            p = Path(__file__).parent.parent / "data" / "icons" / "aram_items" / f"{slug}.png"
            if p.exists():
                img = Image.open(p).resize((sz, sz), Image.LANCZOS)
                _photo = ImageTk.PhotoImage(img)
                self._icon_cache[_cache_key] = _photo
                return _photo
        except Exception: pass
        return None
    def _redraw(self):
        cv = self._cv; cv.delete("all"); self._imgs.clear()
        W = cv.winfo_width() or 312; H = cv.winfo_height() or 200
        if not self._build:
            cv.create_text(W//2, H//2, text="Awaiting build...",
                           fill="#334455", font=("Consolas", 9)); return
        items = self._build
        rows = [items[i:i+3] for i in range(0, min(len(items),6), 3)]
        has_extra = bool(self._extra and len(items) < 7)
        n_rows = len(rows) + (1 if has_extra else 0)
        n_text_lines = 2  # 2-line item names need more vertical space
        cell_h = H // max(n_rows, 2)
        cell_w = W // 3
        icon_sz = min(38, cell_h - 36)  # extra room for 2-line name
        for ri, row in enumerate(rows):
            for ci, item in enumerate(row):
                cx = ci * cell_w + cell_w // 2
                cy = ri * cell_h + (cell_h - icon_sz - 18) // 2
                owned = item.lower().strip() in self._owned
                icon = self._load_icon(item, icon_sz)
                ix, iy = cx - icon_sz//2, cy
                bg_c = "#002211" if owned else "#120c00"
                bd_c = "#44ff88" if owned else "#5a3a00"
                if icon:
                    self._imgs.append(icon)
                    cv.create_rectangle(ix-1,iy-1,ix+icon_sz+1,iy+icon_sz+1,
                                        fill=bg_c, outline=bd_c, width=2 if owned else 1)
                    cv.create_image(cx, iy+icon_sz//2, image=icon)
                else:
                    cv.create_rectangle(ix,iy,ix+icon_sz,iy+icon_sz,
                                        fill=bg_c, outline=bd_c, width=2 if owned else 1)
                    abbr = self._abbr(item)
                    cv.create_text(cx, iy+icon_sz//2, text=abbr,
                                   fill="#44ff88" if owned else "#cc8800",
                                   font=("Consolas", 8 if len(abbr)<=5 else 7, "bold"))
                # Split long names across 2 lines for readability
                _words = item.split()
                if len(item) <= 14:
                    _line1, _line2 = item, ""
                elif len(_words) >= 2:
                    _mid = max(1, len(_words) // 2)
                    _line1 = " ".join(_words[:_mid])
                    _line2 = " ".join(_words[_mid:])
                    if len(_line1) > 13: _line1 = _line1[:12] + "…"
                    if len(_line2) > 13: _line2 = _line2[:12] + "…"
                else:
                    _line1, _line2 = item[:12] + "…", ""
                _nc = "#44ff88" if owned else "#8899aa"
                _nf = ("Consolas", 8, "bold")
                if _line2:
                    cv.create_text(cx, iy+icon_sz+11, text=_line1, fill=_nc, font=_nf)
                    cv.create_text(cx, iy+icon_sz+21, text=_line2, fill=_nc, font=_nf)
                else:
                    cv.create_text(cx, iy+icon_sz+13, text=_line1, fill=_nc, font=_nf)
        if has_extra:
            ey = min(H - 12, len(rows)*cell_h + cell_h//2)
            cv.create_text(W//2, ey, text=self._extra, fill="#aaaaff",
                           font=("Consolas", 9), anchor="center",
                           width=W - 10)


class AramRightBot(tk.Toplevel):
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
        self._econ_txt = _sec(con, 1, "RESET / ITEM", C["econ"], minsize=110)
        con.rowconfigure(1, weight=1, minsize=110)
        # Item build grid (bottom half)
        _ib_frame = tk.Frame(con, bg="#0a0a12",
                             highlightbackground=BORDER, highlightthickness=1)
        _ib_frame.grid(row=2, column=0, sticky="nsew", pady=(2,0))
        tk.Label(_ib_frame, text="ITEM BUILD", bg="#0a0a12", fg=LABEL_C,
                 font=("Consolas", 9, "bold"), anchor="w").pack(
            anchor="w", padx=6, pady=(3,0))
        self._item_canvas = _ItemBuildCanvas(_ib_frame)
        self._item_canvas.pack(fill="both", expand=True, pady=(0,2))
        con.rowconfigure(2, weight=2, minsize=360)

        self._clock_base = 0.0
        self._clock_wall = 0.0
        self._clock_job  = None
        _add_rc_menu(self)

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
        _write_rich(self._econ_txt, data.get("reset_item", "—"), C["econ"])
        self._item_canvas.set_items(
            data.get("item_build", ""),
            data.get("items_display", ""),
            data.get("item_extra", ""),
        )
        gt = data.get("game_time_s", 0)
        if gt:
            self.sync_clock(gt)

    def destroy_clock(self):
        if self._clock_job:
            try: self.after_cancel(self._clock_job)
            except Exception: pass


# ââ Bottom strip ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
class AramBottomStrip(tk.Toplevel):
    # y and h set dynamically in __init__ via _probe_league_bottom()
    GEO = {"x": 0, "y": 920, "w": 1600, "h": 160}  # matches TFT bottom strip

    def __init__(self, root):
        super().__init__(root)
        g = self.GEO
        self.overrideredirect(True)
        self.attributes("-topmost", True)   # covers taskbar
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg=BG)
        con = tk.Frame(self, bg=BG)
        con.pack(fill="both", expand=True, padx=1, pady=1)
        con.columnconfigure(0, weight=13)               # LANE CANVAS (dominant)
        con.columnconfigure(1, weight=2, minsize=320)   # FIGHT CONDITION
        con.rowconfigure(0, weight=1)

        bf = tk_font.Font(family="Segoe UI", size=11, weight="bold")

        def _txt(parent, color):
            t = tk.Text(parent, bg=BG_SEC, fg=color, font=("Segoe UI", 13),
                        wrap="word", bd=0, highlightthickness=0, width=1,
                        insertbackground=BG_SEC, state="disabled",
                        cursor="arrow", padx=10, pady=3, height=4)
            t.pack(fill="both", expand=True, pady=(0, 5))
            t.tag_configure("ally",  foreground="#44ff88", font=bf)
            t.tag_configure("enemy", foreground="#ff4444", font=bf)
            t.tag_configure("time",  foreground="#ffdd00", font=bf)
            t.tag_configure("base",  foreground=color)
            return t

        # Left â LANE CANVAS (col 0)
        fc = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        fc.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
        tk.Label(fc, text="LANE POSITION", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 15, "bold"), anchor="w"
                 ).pack(anchor="w", padx=8, pady=(4, 0))
        self._lane_canvas = AramLaneCanvas(fc)
        self._lane_canvas.pack(fill="both", expand=True, pady=(0, 3))

        # Right â FIGHT CONDITION
        fr = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        fr.grid(row=0, column=1, sticky="nsew")
        tk.Label(fr, text="FIGHT CONDITION", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 9, "bold"), anchor="w"
                 ).pack(anchor="w", padx=10, pady=(5, 0))
        self._fight_txt = _txt(fr, C["fight"])
        _add_rc_menu(self)

    def update(self, data: dict):
        # Lane canvas
        imm     = data.get("immediate", "")  or ""
        pos     = data.get("positioning","") or ""
        action  = data.get("action", "")     or ""
        combined= f"{action} {imm} {pos}"
        zone    = _infer_zone(combined)
        rec     = _infer_recommended(pos)
        self._lane_canvas.update_state(
            zone        = zone,
            recommended = rec,
            fight_text  = imm,
            my_tower    = data.get("my_tower_hp"),
            enemy_tower = data.get("enemy_tower_hp"),
            hp_pct      = data.get("hp_pct",         100),
            wave_pct    = data.get("wave_pct",        50),
            hp_packs    = data.get("hp_packs",        [True, True]),
            team        = data.get("my_team",         "ORDER"),
        )

        # Fight condition
        immediate = data.get("immediate", "") or "\u2014"
        _wr(self._fight_txt, immediate, C["fight"])

    def update_live(self, live: dict):
        if live.get("augment_select"):
            take = live.get("aug_take", "")
            why  = live.get("aug_why",  "")
            plan = live.get("aug_plan", "")
            _wr(self._fight_txt, plan or "Selecting augment...", C["fight"])
            return


def _wr(w, text: str, color: str):
    """Write with rich tags but fallback cleanly."""
    _write_rich(w, text, color)
