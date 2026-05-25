"""
ui/client_panel.py — Tabbed per-mode rating panel + ops observability.
Tabs: ARAM | SR | ARENA | BRAWL | TFT | OPS
Layout: stats top-center, grade left, notes right (no cutoff).
OPS tab: MetricsCache summary + manual deploy/rollback actions.
"""
import time
import tkinter as tk
from pathlib import Path
from core.theme import (BG, BORDER, LABEL_COLOR, DIM_TEXT, CLIENT_ZONES,
                         TAB_COLORS, TAB_BG, TAB_BORDER, TAB_ACTIVE_BG)
from ui.base import OverlayWindow
SCRIPT_DIR = Path(__file__).parent.parent
try:
    from performance_tracker import load_all_ratings, GRADE_COLORS
    HAS_TRACKER = True
except Exception:
    HAS_TRACKER = False; GRADE_COLORS = {}

try:
    from core.ops_ui_actions import run_action_async
    HAS_OPS_ACTIONS = True
except Exception:
    HAS_OPS_ACTIONS = False


# Colour constants for the OPS tab status badges
_C_OK     = "#44cc66"
_C_WARN   = "#ddaa22"
_C_ERR    = "#ff4455"
_C_DIM    = "#555566"
_C_TEXT   = "#a0a0b8"
_C_ACTION = "#334466"
_C_ACT_FG = "#88aadd"

# OPS tab colour in tab row
_OPS_TAB_COLOR = "#7788aa"


class ClientPanel(OverlayWindow):
    def __init__(self, root):
        super().__init__(root, CLIENT_ZONES["main"], tag="client_main")
        self._root_ref   = root
        self._metrics    = None   # set later via set_metrics_cache()
        self._ops_status = {}     # last summary dict shown in OPS tab
        self._lcu_client  = None   # set later via set_lcu_client()
        self._rune_last_refresh = 0.0

        container = tk.Frame(self.top, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        container.pack(fill="both", expand=True, padx=1, pady=1)

        # -- Tab row ------------------------------------------------------
        tab_row = tk.Frame(container, bg=BG); tab_row.pack(fill="x", pady=(1, 0))
        self._tab_labels = {}; self._active_tab = "SR"
        _all_tabs = ["ARAM", "SR", "ARENA", "BRAWL", "TFT", "OPS"]
        _tab_colors = dict(TAB_COLORS)
        _tab_colors["OPS"] = _OPS_TAB_COLOR
        for i, mode in enumerate(_all_tabs):
            color = _tab_colors.get(mode, _OPS_TAB_COLOR)
            f = tk.Frame(tab_row, bg=TAB_BG, highlightbackground=TAB_BORDER, highlightthickness=1)
            f.grid(row=0, column=i, sticky="nsew", padx=1, pady=0)
            lbl = tk.Label(f, text=mode, bg=TAB_BG, fg=color, font=("Consolas", 9, "bold"),
                          cursor="hand2", padx=8, pady=1)
            lbl.pack(fill="both", expand=True)
            lbl.bind("<Button-1>", lambda e, m=mode: self._select_tab(m))
            f.bind("<Button-1>", lambda e, m=mode: self._select_tab(m))
            self._tab_labels[mode] = (f, lbl); tab_row.columnconfigure(i, weight=1)

        # -- Rating body (shared by ARAM/SR/ARENA/BRAWL/TFT tabs) ---------
        self._rating_frame = tk.Frame(container, bg=BG)
        self._rating_frame.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        # Stats line
        self._stats_var = tk.StringVar(value="")
        tk.Label(self._rating_frame, textvariable=self._stats_var, bg=BG, fg=LABEL_COLOR,
                 font=("Segoe UI", 9), anchor="center", wraplength=380, justify="center"
                 ).pack(fill="x", padx=4, pady=(4, 0))

        # Rune page line (shown for ARAM/SR tabs when LCU connected)
        self._rune_var = tk.StringVar(value="")
        self._rune_lbl = tk.Label(
            self._rating_frame, textvariable=self._rune_var,
            bg=BG, fg="#556677", font=("Consolas", 8),
            anchor="center", wraplength=380,
        )
        self._rune_lbl.pack(fill="x", padx=4, pady=(0, 2))

        # Body: grade LEFT + notes RIGHT
        body = tk.Frame(self._rating_frame, bg=BG)
        body.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        grade_col = tk.Frame(body, bg=BG)
        grade_col.pack(side="left", padx=(4, 8), pady=(0, 0))
        self._placement_var = tk.StringVar(value="")
        self._placement_lbl = tk.Label(grade_col, textvariable=self._placement_var, bg=BG, fg="#ccccee",
                                    font=("Consolas", 13, "bold"), anchor="center")
        self._placement_lbl.pack(fill="x")
        self._grade_var = tk.StringVar(value="\u2014")
        self._grade_lbl = tk.Label(grade_col, textvariable=self._grade_var, bg=BG, fg="#555577",
                                    font=("Consolas", 36, "bold"), anchor="center")
        self._grade_lbl.pack(fill="x")

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._label_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self._label_var, bg=BG, fg=LABEL_COLOR,
                 font=("Segoe UI", 9, "bold"), anchor="w", wraplength=300, justify="left"
                 ).pack(fill="x", anchor="w", pady=(2, 0))

        self._notes_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self._notes_var, bg=BG, fg=DIM_TEXT,
                 font=("Segoe UI", 9), anchor="nw", wraplength=300, justify="left"
                 ).pack(fill="both", expand=True, anchor="nw", pady=(0, 0))

        self._time_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self._time_var, bg=BG, fg="#555566",
                 font=("Consolas", 8), anchor="e"
                 ).pack(fill="x", anchor="e", pady=(0, 2))

        # -- OPS tab body (hidden until OPS tab is selected) ---------------
        self._ops_frame = tk.Frame(container, bg=BG)
        # (Not packed yet — shown on demand by _select_tab)
        self._build_ops_tab(self._ops_frame)

        self._ratings_cache = {}; self._load_all(); self._select_tab("SR")

    # -- MetricsCache wiring -----------------------------------------------

    def set_metrics_cache(self, metrics_cache) -> None:
        """Called by app.py after MetricsCache is available."""
        self._metrics = metrics_cache

    # -- LCU rune page wiring (AUDIT-PHASE-2-API-001) ---------------------

    def set_lcu_client(self, lcu) -> None:
        """Pass the live LcuClient so the panel can show current rune page."""
        self._lcu_client = lcu

    def _refresh_rune_page(self) -> None:
        """
        Query LCU for the current rune page and update the rune label.
        Only shown on ARAM and SR tabs; hidden on all others.
        """
        if self._lcu_client is None or self._active_tab not in ("ARAM", "SR"):
            self._rune_var.set("")
            return
        try:
            page_str = self._lcu_client.format_rune_page()
            if page_str:
                self._rune_var.set(f"\u25b8 {page_str[:80]}")
            else:
                self._rune_var.set("")
        except Exception:
            self._rune_var.set("")

    # -- OPS tab construction ----------------------------------------------

    def _build_ops_tab(self, parent: tk.Frame) -> None:
        """Build the OPS observability + action surface."""
        # -- Observability section -----------------------------------------
        obs_frame = tk.Frame(parent, bg=BG)
        obs_frame.pack(fill="x", padx=6, pady=(4, 0))

        tk.Label(obs_frame, text="RUNTIME STATUS", bg=BG, fg=_OPS_TAB_COLOR,
                 font=("Consolas", 8, "bold"), anchor="w").pack(fill="x")

        # Status grid: two columns of key=value pairs
        grid = tk.Frame(obs_frame, bg=BG)
        grid.pack(fill="x", pady=(2, 0))

        self._obs_vars: dict = {}
        _fields = [
            ("supervisor",  "supervisor"),
            ("process",     "process"),
            ("mode",        "mode"),
            ("cb_tripped",  "circuit_breaker"),
            ("ladder",      "ladder_idx"),
            ("cons_fails",  "consec_fails"),
            ("stable",      "stable_ticks"),
            ("awaiting_hb", "await_heartbeat"),
            ("coaching_ts", "last_coaching"),
        ]
        for row_i, (key, label) in enumerate(_fields):
            c = row_i % 2
            r = row_i // 2
            cell = tk.Frame(grid, bg=BG)
            cell.grid(row=r, column=c, sticky="w", padx=(0, 8), pady=0)
            tk.Label(cell, text=f"{label}:", bg=BG, fg=_C_DIM,
                     font=("Consolas", 8), anchor="w").pack(side="left")
            var = tk.StringVar(value="\u2014")
            lbl = tk.Label(cell, textvariable=var, bg=BG, fg=_C_TEXT,
                           font=("Consolas", 8, "bold"), anchor="w")
            lbl.pack(side="left", padx=(2, 0))
            self._obs_vars[key] = (var, lbl)
        grid.columnconfigure(0, weight=1); grid.columnconfigure(1, weight=1)

        # Incidents section
        tk.Label(obs_frame, text="LAST INCIDENTS", bg=BG, fg=_OPS_TAB_COLOR,
                 font=("Consolas", 8, "bold"), anchor="w").pack(fill="x", pady=(4, 0))
        self._incidents_var = tk.StringVar(value="\u2014")
        tk.Label(obs_frame, textvariable=self._incidents_var, bg=BG, fg=_C_TEXT,
                 font=("Consolas", 7), anchor="nw", justify="left", wraplength=370
                 ).pack(fill="x")

        # Refresh timestamp
        self._obs_ts_var = tk.StringVar(value="")
        tk.Label(obs_frame, textvariable=self._obs_ts_var, bg=BG, fg=_C_DIM,
                 font=("Consolas", 7), anchor="e").pack(fill="x")

        # -- Policy section ------------------------------------------
        tk.Frame(obs_frame, bg="#222233", height=1).pack(fill="x", pady=(4, 0))
        tk.Label(obs_frame, text="FEATURE POLICY", bg=BG, fg=_OPS_TAB_COLOR,
                 font=("Consolas", 8, "bold"), anchor="w").pack(fill="x", pady=(2, 0))

        pol_grid = tk.Frame(obs_frame, bg=BG)
        pol_grid.pack(fill="x", pady=(1, 0))

        self._policy_vars: dict = {}
        _policy_fields = [
            ("pol_status",    "status"),
            ("pol_reload_ts", "reloaded"),
            ("pol_sr",        "sr.coaching"),
            ("pol_aram",      "aram.coaching"),
            ("pol_arena",     "arena.coaching"),
            ("pol_brawl",     "brawl.coaching"),
            ("pol_tft_c",     "tft.coaching"),
            ("pol_tft_v",     "tft.vision"),
        ]
        for row_i, (key, label) in enumerate(_policy_fields):
            c = row_i % 2
            r = row_i // 2
            cell = tk.Frame(pol_grid, bg=BG)
            cell.grid(row=r, column=c, sticky="w", padx=(0, 8), pady=0)
            tk.Label(cell, text=f"{label}:", bg=BG, fg=_C_DIM,
                     font=("Consolas", 7), anchor="w").pack(side="left")
            var = tk.StringVar(value="\u2014")
            lbl = tk.Label(cell, textvariable=var, bg=BG, fg=_C_TEXT,
                           font=("Consolas", 7, "bold"), anchor="w")
            lbl.pack(side="left", padx=(2, 0))
            self._policy_vars[key] = (var, lbl)
        pol_grid.columnconfigure(0, weight=1); pol_grid.columnconfigure(1, weight=1)

        self._policy_warn_var = tk.StringVar(value="")
        tk.Label(obs_frame, textvariable=self._policy_warn_var, bg=BG, fg=_C_WARN,
                 font=("Consolas", 7), anchor="w", wraplength=370, justify="left"
                 ).pack(fill="x")

        # -- Action section ------------------------------------------------
        tk.Frame(parent, bg="#222233", height=1).pack(fill="x", padx=6, pady=(4, 0))
        act_frame = tk.Frame(parent, bg=BG)
        act_frame.pack(fill="x", padx=6, pady=(4, 4))

        tk.Label(act_frame, text="MANUAL ACTIONS", bg=BG, fg=_OPS_TAB_COLOR,
                 font=("Consolas", 8, "bold"), anchor="w").pack(fill="x")

        btn_row = tk.Frame(act_frame, bg=BG)
        btn_row.pack(fill="x", pady=(2, 0))

        def _btn(parent_frame, label, cmd):
            b = tk.Button(parent_frame, text=label, command=cmd,
                          bg=_C_ACTION, fg=_C_ACT_FG, activebackground="#445577",
                          font=("Consolas", 8), relief="flat", padx=6, pady=2,
                          cursor="hand2")
            b.pack(side="left", padx=(0, 4))
            return b

        _btn(btn_row, "Preflight",  self._action_preflight)
        _btn(btn_row, "Snapshot",   self._action_snapshot)
        _btn(btn_row, "Rollback \u26a0", self._action_rollback_confirm)

        # Action result line
        self._action_result_var = tk.StringVar(value="")
        self._action_result_lbl = tk.Label(act_frame, textvariable=self._action_result_var,
                 bg=BG, fg=_C_TEXT, font=("Consolas", 7), anchor="w",
                 wraplength=370, justify="left")
        self._action_result_lbl.pack(fill="x", pady=(2, 0))

    # -- OPS tab refresh ---------------------------------------------------

    def refresh_ops(self) -> None:
        """
        Refresh the OPS tab from MetricsCache.
        Called by app.py on a modest cadence (every ~5s) via root.after.
        Reads only from MetricsCache.get_summary() — no file I/O here.
        """
        if self._active_tab != "OPS":
            return  # don't refresh hidden tab
        if self._metrics is None:
            return
        try:
            s = self._metrics.get_summary()
            self._apply_ops_summary(s)
        except Exception:
            pass

    def _apply_ops_summary(self, s) -> None:
        """Apply a MetricsSummary to the OPS tab widgets."""

        def _fmt(val, true_str="yes", false_str="no"):
            if val is None:
                return "\u2014"
            if isinstance(val, bool):
                return true_str if val else false_str
            return str(val)

        def _set(key, text, color=_C_TEXT):
            if key in self._obs_vars:
                var, lbl = self._obs_vars[key]
                var.set(text)
                lbl.configure(fg=color)

        # supervisor_state
        sv = s.supervisor_state or "\u2014"
        sv_col = (_C_OK if sv == "healthy_ready"
                  else _C_WARN if "tolerated" in sv
                  else _C_ERR if sv != "\u2014"
                  else _C_DIM)
        _set("supervisor", sv[:22], sv_col)

        # process_running
        pr = s.process_running
        _set("process",
             "running" if pr else "stopped" if pr is False else "\u2014",
             _C_OK if pr else _C_ERR if pr is False else _C_DIM)

        # current_mode
        _set("mode", _fmt(s.current_mode), _C_TEXT)

        # circuit_breaker
        cb = s.circuit_breaker_tripped
        _set("cb_tripped",
             "TRIPPED" if cb else "ok" if cb is False else "\u2014",
             _C_ERR if cb else _C_OK if cb is False else _C_DIM)

        # ladder_idx
        _set("ladder", _fmt(s.ladder_idx), _C_TEXT)

        # consecutive_fails
        cf = s.consecutive_fails
        cf_col = _C_ERR if (cf or 0) >= 3 else _C_WARN if (cf or 0) >= 1 else _C_OK
        _set("cons_fails", _fmt(cf), cf_col if cf is not None else _C_DIM)

        # stable_ticks
        _set("stable", _fmt(s.stable_ticks), _C_TEXT)

        # awaiting_first_heartbeat
        awh = s.awaiting_first_heartbeat
        _set("awaiting_hb",
             "waiting" if awh else "no" if awh is False else "\u2014",
             _C_WARN if awh else _C_OK if awh is False else _C_DIM)

        # last_coaching_ts
        lct = s.last_coaching_ts
        _set("coaching_ts", str(lct)[-19:] if lct else "\u2014", _C_TEXT)

        # incidents
        incidents = s.last_5_incidents or []
        if incidents:
            lines = []
            for inc in reversed(incidents[-5:]):  # up to last 5, newest first
                ts  = str(inc.get("ts", ""))[-8:] or "?"
                sev = str(inc.get("severity", ""))[:4].upper()
                sub = str(inc.get("subsystem", ""))[:12]
                trg = str(inc.get("trigger", ""))[:20]
                lines.append(f"[{ts}] {sev} {sub} {trg}")
            self._incidents_var.set("\n".join(lines))
        else:
            self._incidents_var.set("none")

        # refreshed_at
        rt = str(s.refreshed_at or "")
        if "T" in rt:
            rt = rt.split("T")[1][:8]
        self._obs_ts_var.set(f"refreshed {rt}" if rt else "")

        # -- Policy section ----------------------------------------------
        def _pset(key, text, color=_C_TEXT):
            if key in self._policy_vars:
                var, lbl = self._policy_vars[key]
                var.set(text[:22])
                lbl.configure(fg=color)

        ps = s.policy_source_status or "—"
        ps_col = (_C_OK if ps == "loaded"
                  else _C_WARN if ps in ("last_known_good", "invalid_reload_retained", "missing")
                  else _C_DIM)
        _pset("pol_status", ps[:18], ps_col)

        prt = s.policy_last_reload_ts
        _pset("pol_reload_ts", str(prt)[-19:] if prt else "—", _C_TEXT)

        def _dec(val):
            if val is None: return "—"
            return val
        def _dec_col(val):
            if val == "disabled": return _C_WARN
            if val == "allow":    return _C_OK
            return _C_DIM

        _pset("pol_sr",     _dec(s.policy_sr_live_coaching),    _dec_col(s.policy_sr_live_coaching))
        _pset("pol_aram",   _dec(s.policy_aram_live_coaching),  _dec_col(s.policy_aram_live_coaching))
        _pset("pol_arena",  _dec(s.policy_arena_live_coaching), _dec_col(s.policy_arena_live_coaching))
        _pset("pol_brawl",  _dec(s.policy_brawl_live_coaching), _dec_col(s.policy_brawl_live_coaching))
        _pset("pol_tft_c",  _dec(s.policy_tft_live_coaching),   _dec_col(s.policy_tft_live_coaching))
        _pset("pol_tft_v",  _dec(s.policy_tft_vision_analysis), _dec_col(s.policy_tft_vision_analysis))

        warn = s.policy_last_warning or ""
        self._policy_warn_var.set(warn[:120] if warn else "")

    # -- Action handlers ---------------------------------------------------

    def _action_preflight(self) -> None:
        self._set_action_status("Running preflight...", _C_TEXT)
        if not HAS_OPS_ACTIONS:
            self._set_action_status("ops_ui_actions unavailable", _C_WARN)
            return
        run_action_async("preflight", self._on_action_result)

    def _action_snapshot(self) -> None:
        self._set_action_status("Running snapshot...", _C_TEXT)
        if not HAS_OPS_ACTIONS:
            self._set_action_status("ops_ui_actions unavailable", _C_WARN)
            return
        run_action_async("snapshot", self._on_action_result)

    def _action_rollback_confirm(self) -> None:
        """Show a confirmation dialog before launching rollback."""
        if not HAS_OPS_ACTIONS:
            self._set_action_status("ops_ui_actions unavailable", _C_WARN)
            return
        dlg = tk.Toplevel(self._root_ref)
        dlg.title("Confirm Rollback")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="Roll back to last snapshot?",
                 bg=BG, fg=_C_WARN, font=("Segoe UI", 10, "bold"),
                 padx=16, pady=8).pack()
        tk.Label(dlg, text="This will overwrite current files with the last snapshot.",
                 bg=BG, fg=_C_TEXT, font=("Segoe UI", 9),
                 padx=16, pady=0).pack()

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(pady=8)

        def _confirm():
            dlg.destroy()
            self._set_action_status("Running rollback...", _C_TEXT)
            run_action_async("rollback_last", self._on_action_result, confirmed=True)

        def _cancel():
            dlg.destroy()
            self._set_action_status("Rollback cancelled.", _C_DIM)

        tk.Button(btn_row, text="Rollback", command=_confirm,
                  bg="#552222", fg=_C_ERR, activebackground="#663333",
                  font=("Consolas", 9), relief="flat", padx=10, pady=3).pack(side="left", padx=4)
        tk.Button(btn_row, text="Cancel", command=_cancel,
                  bg=_C_ACTION, fg=_C_ACT_FG, activebackground="#445577",
                  font=("Consolas", 9), relief="flat", padx=10, pady=3).pack(side="left", padx=4)

    def _on_action_result(self, result) -> None:
        """Callback from ops_ui_actions worker thread — marshal to Tk."""
        def _apply():
            ok_col = _C_OK if result.ok else _C_ERR
            prefix = "\u2713" if result.ok else "\u2717"
            short = result.summary.splitlines()[-1][:80] if result.summary else ""
            self._set_action_status(f"{prefix} {result.action}: {short}", ok_col)
        try:
            self._root_ref.after(0, _apply)
        except Exception:
            pass

    def _set_action_status(self, text: str, color: str = _C_TEXT) -> None:
        """Update action result label — must be called from Tk thread."""
        try:
            self._action_result_var.set(text[:120])
            self._action_result_lbl.configure(fg=color)
        except Exception:
            pass

    # -- Tab switching -----------------------------------------------------

    def _select_tab(self, mode):
        self._active_tab = mode

        # Update tab highlight
        for m, (f, lbl) in self._tab_labels.items():
            if m == mode:
                f.configure(bg=TAB_ACTIVE_BG); lbl.configure(bg=TAB_ACTIVE_BG, font=("Consolas", 9, "bold"))
            else:
                f.configure(bg=TAB_BG); lbl.configure(bg=TAB_BG, font=("Consolas", 9))

        if mode == "OPS":
            self._rating_frame.pack_forget()
            self._ops_frame.pack(fill="both", expand=True)
            self.refresh_ops()
        else:
            self._ops_frame.pack_forget()
            self._rating_frame.pack(fill="both", expand=True, padx=4, pady=(0, 2))
            data = self._ratings_cache.get(mode)
            if data:
                self._apply_rating(data, mode)
            else:
                self._grade_var.set("\u2014"); self._grade_lbl.configure(fg="#333345")
                self._stats_var.set(f"No {mode} games recorded")
                self._label_var.set(""); self._notes_var.set(""); self._time_var.set("")
            self._refresh_rune_page()

    # -- Rating methods (unchanged from pre-Step-6) ------------------------

    def _load_all(self):
        if not HAS_TRACKER: return
        try: self._ratings_cache = load_all_ratings(SCRIPT_DIR)
        except Exception: pass

    def _apply_rating(self, data, mode=""):
        grade = data.get("rating", "")
        if not grade: return
        color = GRADE_COLORS.get(grade, "#c8c8d8"); cat = data.get("mode_category", mode or "SR")
        if cat == "TFT": stat_str = self._format_tft(data)
        elif cat == "ARAM": stat_str = self._format_aram(data)
        elif cat == "ARENA": stat_str = self._format_arena(data)
        elif cat == "BRAWL": stat_str = self._format_brawl(data)
        else: stat_str = self._format_sr(data)
        notes = data.get("notes", []); label = data.get("label", ""); ts = data.get("timestamp", "")
        self._grade_var.set(grade); self._grade_lbl.configure(fg=color)
        self._stats_var.set(stat_str[:80]); self._label_var.set(label[:60])
        if hasattr(self, "_placement_var"):
            if cat == "TFT":
                pl = data.get("tft_placement", 0)
                if pl:
                    _ord = {1:"1st",2:"2nd",3:"3rd"}.get(pl, f"{pl}th")
                    self._placement_var.set(f"{_ord}")
                    _pc = "#44ff88" if pl <= 1 else "#a8c023" if pl <= 2 else "#ffdd00" if pl <= 4 else "#ff4a6a"
                    self._placement_lbl.configure(fg=_pc)
                else:
                    self._placement_var.set("")
            else:
                self._placement_var.set("")
        if cat == "TFT" and label:
            comp_check = data.get("tft_comp", "")
            if comp_check and comp_check in label:
                label = label.replace(comp_check, "").strip(" —-\u2014").strip()
            self._label_var.set(label[:60])
        self._notes_var.set("\n".join(f"\u2022 {n}" for n in notes))
        self._time_var.set(ts)

    def _format_sr(self, d):
        s=d.get("stats",{}); ch=d.get("champion","")
        return f"{ch}  \u2014  {s.get('kda','?')}  \u2022  {s.get('cs_per_min','?')} CS/min  \u2022  {s.get('gold_per_min','?')} GPM"
    def _format_aram(self, d):
        s=d.get("stats",{}); ch=d.get("champion",""); gt=d.get("game_time","")
        return f"{ch}  \u2014  {s.get('kda','?')}  \u2022  {s.get('kill_participation','?')}% KP  \u2022  {gt}"
    def _format_arena(self, d):
        s=d.get("stats",{}); ch=d.get("champion",""); gt=d.get("game_time","")
        return f"{ch}  \u2014  {s.get('kda','?')}  \u2022  {s.get('deaths',0)}d  \u2022  {gt}"
    def _format_brawl(self, d):
        s=d.get("stats",{}); ch=d.get("champion",""); rm=d.get("game_mode","")
        mt=f" [{rm}]" if rm not in ("","CLASSIC") else ""
        return f"{ch}{mt}  \u2014  {s.get('kda','?')}  \u2022  {s.get('gold_per_min','?')} GPM"
    def _format_tft(self, d):
        comp=d.get("tft_comp","") or d.get("champion","")
        lv=d.get("tft_level",0); st=d.get("tft_stage",0); gt=d.get("game_time","")
        parts=[]
        if comp and comp!=f"TFT #{d.get('tft_placement',0)}": parts.append(comp)
        if lv: parts.append(f"Lv{lv}")
        if st: parts.append(f"Stage {st}")
        if gt and gt!="?": parts.append(gt)
        return "  \u2022  ".join(parts)

    def update_data(self, _data):
        self._load_all()
        # Refresh rune page display at most every 5s (rate-limited LCU call)
        _now = time.monotonic()
        if _now - self._rune_last_refresh > 5.0:
            self._rune_last_refresh = _now
            self._refresh_rune_page()
        if self._active_tab != "OPS":
            d = self._ratings_cache.get(self._active_tab)
            if d: self._apply_rating(d, self._active_tab)
        else:
            self.refresh_ops()
