"""
modes/arena_overlay.py  — v2 (full upgrade)

Arena 2v2v2v2 dedicated overlay.

Right-top  (320×520): Round / HP / ACTION / AUGMENT ADVICE / ANVIL ITEMS
Right-bot  (320×520): CLOCK / ROUND STRATEGY / FIGHT RULE / RISK / CAMP PHASE
Bottom     (1920×160):
    Left  220px  — ROUND STATUS (round#, wins/losses, rank)
    Center 1440px — TEAM HEALTH CANVAS v2
                     (8 teams ranked by HP, trend △▽, partner/opponent highlight,
                      camp phase indicator, round transition banner)
    Right  260px  — TARGET PRIORITY + AUGMENT PLAY

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
    "round":     "#ffdd00",
    "augment":   "#ffd700",
    "anvil":     "#4ab0ff",
    "strategy":  "#4affaa",
    "fight":     "#ffa84a",
    "risk":      "#ff4a6a",
    "you":       "#44ff88",
    "partner":   "#88ff44",
    "opponent":  "#ff9944",
    "others":    "#6688aa",
    "dead":      "#444455",
    "clock":     "#ffdd00",
    "stats":     "#d0d0e0",
    "camp":      "#44ffcc",
}

_LBL    = ("Consolas", 10, "bold")
_LBL_HD = ("Consolas", 12, "bold")
_VAL_LG = ("Segoe UI", 14, "bold")
_BODY   = ("Segoe UI", 12)
_TAG_RE = re.compile(r'\[A\](.*?)\[/A\]|\[E\](.*?)\[/E\]|\[T\](.*?)\[/T\]', re.DOTALL)


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


# ── Team Health Canvas v2 ─────────────────────────────────────────────────────
# 8 teams ranked by HP descending (dead at bottom)
# YOUR pair: bright green border + "YOU" tag
# Partner: separate row with partner label
# Next opponent: orange border + "NEXT" tag + threat icon
# Trend arrows: △ gained HP (healed), ▽ lost HP (took damage since last round)
# Camp phase: banner overlay when detected
# ─────────────────────────────────────────────────────────────────────────────
class ArenaHealthCanvas(tk.Frame):
    ROW_H  = 17

    def __init__(self, parent):
        super().__init__(parent, bg=BG_SEC)
        total_h = 8 * self.ROW_H + 40
        self.canvas = tk.Canvas(self, bg=BG_SEC, bd=0, highlightthickness=0,
                                height=total_h)
        self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self._teams      = []
        self._round      = 0
        self._camp_phase = False
        self._prev_hp    = {}   # name → hp_pct from last update for trend
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

    def update_teams(self, teams: list, round_num: int = 0, camp_phase: bool = False):
        """
        teams: list of dicts:
          name, hp_pct (0-100), is_you, is_partner, is_next_opponent, is_dead
        """
        # Compute trends vs previous HP
        new_hp = {t.get("name","?"): t.get("hp_pct", 0) for t in teams}
        trends = {}
        for name, hp in new_hp.items():
            prev = self._prev_hp.get(name)
            if prev is None:
                trends[name] = " "
            elif hp > prev:
                trends[name] = "\u25b3"    # △ gained
            elif hp < prev:
                trends[name] = "\u25bd"    # ▽ lost
            else:
                trends[name] = " "
        self._prev_hp = new_hp
        self._trends  = trends

        living = sorted([t for t in teams if not t.get("is_dead")],
                        key=lambda t: -t.get("hp_pct", 0))
        dead   = [t for t in teams if t.get("is_dead")]
        self._teams      = living + dead
        self._round      = round_num
        self._camp_phase = camp_phase
        self._redraw()

    def _redraw(self):
        cv = self.canvas
        cv.delete("all")
        w  = cv.winfo_width() or 900
        rh = self.ROW_H

        # Header
        if self._camp_phase:
            cv.create_rectangle(0, 0, w, 18, fill="#0a2a22", outline="")
            cv.create_text(w // 2, 9, text="\u26fa CAMP PHASE — BUY ITEMS & HEAL",
                           fill=C["camp"], font=("Consolas", 9, "bold"))
        else:
            rnd = f"ROUND {self._round}" if self._round > 0 else "ARENA"
            cv.create_text(w // 2, 9, text=rnd,
                           fill=C["round"], font=("Consolas", 10, "bold"))

        if not self._teams:
            cv.create_text(w // 2, 50, text="Waiting for game data...",
                           fill=LABEL_C, font=("Consolas", 9))
            return

        y_start = 22
        name_w  = 150
        bw      = max(80, w - name_w - 70)

        for i, team in enumerate(self._teams[:8]):
            y      = y_start + i * rh
            name   = team.get("name", "Team")[:12]
            hp     = max(0, min(100, team.get("hp_pct", 100)))
            is_you = team.get("is_you", False)
            is_par = team.get("is_partner", False)
            is_opp = team.get("is_next_opponent", False)
            is_dead= team.get("is_dead", False)
            trend  = getattr(self, "_trends", {}).get(name, " ")

            # Row background + border
            if is_you:
                bg, bdr = "#0d2b0d", C["you"]
            elif is_par:
                bg, bdr = "#0d2b0d", C["partner"]
            elif is_opp:
                bg, bdr = "#2b1500", C["opponent"]
            elif is_dead:
                bg, bdr = "#0a0a0f", BG
            else:
                bg, bdr = BG, "#1c1c2e"

            cv.create_rectangle(2, y, w - 2, y + rh - 1,
                                fill=bg, outline=bdr, width=1)

            # Name + tag
            name_color = (C["you"] if is_you else C["partner"] if is_par
                         else C["opponent"] if is_opp
                         else C["dead"] if is_dead else C["others"])
            tag = " YOU" if is_you else (" PARTNER" if is_par
                  else " NEXT" if is_opp else "")
            bold = "bold" if (is_you or is_par or is_opp) else "normal"
            cv.create_text(6, y + rh//2,
                           text=f"{name}{tag}",
                           fill=name_color,
                           font=("Consolas", 8, bold),
                           anchor="w")

            # HP bar
            bx = name_w
            bar_h = rh - 6
            if not is_dead:
                bar_fill = int(bw * hp / 100)
                bar_col  = (C["you"] if is_you else C["partner"] if is_par
                            else C["opponent"] if is_opp else "#336688")
                if hp < 20:
                    bar_col = "#ff4444"
                elif hp < 40:
                    bar_col = "#ff8844"
                cv.create_rectangle(bx, y + 3, bx + bw, y + 3 + bar_h,
                                    fill="#1c1c2e", outline="")
                if bar_fill > 0:
                    cv.create_rectangle(bx, y + 3, bx + bar_fill, y + 3 + bar_h,
                                        fill=bar_col, outline="")
                # HP % text
                cv.create_text(bx + bw + 4, y + rh//2,
                               text=f"{hp}%", fill=name_color,
                               font=("Consolas", 8), anchor="w")
                # Trend arrow
                trend_col = "#44ff88" if trend == "\u25b3" else "#ff4444" if trend == "\u25bd" else LABEL_C
                cv.create_text(bx + bw + 36, y + rh//2,
                               text=trend, fill=trend_col,
                               font=("Consolas", 9, "bold"), anchor="w")
            else:
                cv.create_text(bx, y + rh//2, text="ELIMINATED",
                               fill=C["dead"], font=("Consolas", 8), anchor="w")


# ── Right-top ─────────────────────────────────────────────────────────────────
class ArenaRightTop(tk.Toplevel):
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
        for col, (k, t) in enumerate([("round","R0"),("hp","100HP"),("rank","#1"),("alive","8T")]):
            lb = tk.Label(sr, text=t, bg="#16161f", fg=C["stats"],
                          font=("Consolas", 11, "bold"))
            lb.grid(row=0, column=col, padx=4)
            self._stats[k] = lb
        for c in range(4): sr.columnconfigure(c, weight=1)
        con.rowconfigure(0, weight=0, minsize=36)

        self._action_var, self._act_lbl = _bar(con, 1, "ACTION", C["action"], minsize=44)
        self._augment_txt = _sec(con, 2, "AUGMENT ADVICE", C["augment"], minsize=170)
        self._anvil_txt   = _sec(con, 3, "ANVIL / ITEMS",  C["anvil"],   minsize=160)

    def update(self, data: dict):
        self._stats["round"].configure(text=f"R{data.get('round', 0)}")
        hp = data.get("hp_pct", 100)
        self._stats["hp"].configure(
            text=f"{hp}HP",
            fg="#ff4444" if hp < 20 else ("#ffaa44" if hp < 40 else C["stats"]))
        self._stats["rank"].configure(text=f"#{data.get('rank', '?')}")
        self._stats["alive"].configure(text=f"{data.get('alive_teams', 8)}T")
        act = data.get("action", "") or "\u2014"
        self._action_var.set(act)
        self._act_lbl.configure(fg="#ff2244" if hp <= 20 else C["action"])

        # During augment select: override augment panel
        if data.get("augment_select"):
            take = data.get("aug_take", "")
            why  = data.get("aug_why",  "")
            plan = data.get("aug_plan", "")
            _write_rich(self._augment_txt,
                        f"TAKE: {take}\n{why}\n{plan}" if take else "\u2014",
                        C["augment"])
        else:
            _write_rich(self._augment_txt, data.get("augment_advice", "\u2014"), C["augment"])

        _write_rich(self._anvil_txt, data.get("anvil_advice", "\u2014"), C["anvil"])


# ── Right-bot ─────────────────────────────────────────────────────────────────

class ArenaAiStatusBar(tk.Toplevel):
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


class ArenaCoachStatusBar(tk.Toplevel):
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
        self._data_file=Path(__file__).parent.parent/"data"/"arena_coaching_data.json"
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

class ArenaRightBot(tk.Toplevel):
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

        self._strategy_txt = _sec(con, 1, "ROUND STRATEGY", C["strategy"], minsize=120)
        self._fight_txt    = _sec(con, 2, "FIGHT RULE",     C["fight"],    minsize=120)
        self._risk_txt     = _sec(con, 3, "RISK",           C["risk"],     minsize=100)

        f = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        f.grid(row=4, column=0, sticky="nsew", pady=(2, 0))
        tk.Label(f, text="CAMP / TARGET PLAY", bg=BG_SEC, fg=LABEL_C,
                 font=_LBL_HD, anchor="w").pack(anchor="w", padx=8, pady=(4, 0))
        self._camp_txt = _make_txt(f, C["camp"])
        self._camp_txt.tag_configure("base", foreground=C["camp"])
        self._camp_txt.pack(fill="both", expand=True, pady=(0, 4))
        con.rowconfigure(4, weight=1, minsize=110)

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
        _write_rich(self._strategy_txt, data.get("round_strategy", "\u2014"), C["strategy"])
        _write_rich(self._fight_txt,    data.get("fight_rule",     "\u2014"), C["fight"])
        _write_rich(self._risk_txt,     data.get("risk",           "\u2014"), C["risk"])
        camp_txt = "CAMP PHASE ACTIVE\u2014BUY + HEAL NOW" if data.get("camp_phase") \
                   else data.get("target_priority", "\u2014")
        _write_rich(self._camp_txt, camp_txt, C["camp"])
        gt = data.get("game_time_s", 0)
        if gt:
            self.sync_clock(gt)

    def destroy_clock(self):
        if self._clock_job:
            try: self.after_cancel(self._clock_job)
            except Exception: pass


# ── Bottom strip ──────────────────────────────────────────────────────────────
class ArenaBottomStrip(tk.Toplevel):
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

        # Left — ROUND STATUS
        fl = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        fl.grid(row=0, column=0, sticky="nsew")
        tk.Label(fl, text="ROUND STATUS", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 9, "bold"), anchor="w"
                 ).pack(anchor="w", padx=10, pady=(5, 0))
        self._status_txt = _txt(fl, C["round"])

        # Center — TEAM HEALTH CANVAS
        fc = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        fc.grid(row=0, column=1, sticky="nsew", padx=(2, 2))
        tk.Label(fc, text="TEAM HEALTH RANKING  [\u25b3=gained \u25bd=lost]",
                 bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 10, "bold"), anchor="w"
                 ).pack(anchor="w", padx=8, pady=(4, 0))
        self._health_canvas = ArenaHealthCanvas(fc)
        self._health_canvas.pack(fill="both", expand=True, pady=(0, 3))

        # Right — TARGET PRIORITY
        fr = tk.Frame(con, bg=BG_SEC, highlightbackground=BORDER, highlightthickness=1)
        fr.grid(row=0, column=2, sticky="nsew")
        tk.Label(fr, text="TARGET / AUGMENT PLAY", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 9, "bold"), anchor="w"
                 ).pack(anchor="w", padx=10, pady=(5, 0))
        self._target_txt = _txt(fr, C["fight"])

    def update(self, data: dict, teams: list = None):
        rnd    = data.get("round",       0)
        wins   = data.get("wins",        0)
        losses = data.get("losses",      0)
        alive  = data.get("alive_teams", 8)
        rank   = data.get("rank",        "?")
        status = f"Round {rnd}\n{wins}W / {losses}L\nRank #{rank} of {alive} teams"
        _write_rich(self._status_txt, status, C["round"])

        if teams:
            self._health_canvas.update_teams(
                teams, rnd, camp_phase=bool(data.get("camp_phase")))

        target = data.get("target_priority", "") or ""
        aug    = data.get("augment_play",   "") or ""
        parts  = []
        if data.get("augment_select"):
            take = data.get("aug_take", "")
            why  = data.get("aug_why",  "")
            parts.append(f"AUGMENT\nTake: {take}\n{why}" if take else "AUGMENT SELECT")
        else:
            if target: parts.append(target)
            if aug and aug not in ("N/A", "n/a", ""):
                parts.append(f"Aug: {aug}")
        _write_rich(self._target_txt,
                    "\n".join(parts) if parts else "\u2014",
                    C["fight"])
