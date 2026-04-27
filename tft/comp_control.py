"""
tft/comp_control.py
Comp Control + Champ/Item Control panels.
- Item clipart from data/icons/items/*.png
- LCU direct team planner import on comp select
- Tooltip hover fixed (delayed, robust)
- Item icons with fallback to styled text
"""
import tkinter as tk
import json
import logging
import re
import subprocess
import threading
from PIL import Image, ImageTk
from pathlib import Path

_log = logging.getLogger("rc.tft.compctrl")

# ── Theme ──────────────────────────────────────────────────────────────────
BG      = "#0b0b12"
BG_SEC  = "#111119"
BORDER  = "#252535"
LABEL_C = "#9090aa"
_TIER_COLORS  = {"S": "#FFD700", "A": "#44FF88", "B": "#4A9EFF", "C": "#D0D0E0"}
_COST_COLORS  = {1: "#9B9B9B", 2: "#11B288", 3: "#207AC7", 4: "#C440DA", 5: "#FFB93B"}
_EMBLEM_BG    = "#2a2a10"
_EMBLEM_BORDER= "#FFD700"
_SELECTED_BG  = "#1a2a1a"

# ── Paths ──────────────────────────────────────────────────────────────────
_META_DIR  = Path(__file__).parent.parent / "data" / "meta"
_ICON_DIR  = Path(__file__).parent.parent / "data" / "icons" / "items"   # item PNGs live here
_STATE_FILE= Path(__file__).parent.parent / "data" / "comp_state.json"

# ── Item icon cache ────────────────────────────────────────────────────────
_icon_cache: dict = {}

def _item_slug(name: str) -> str:
    s = name.lower().strip()
    s = s.replace("'s", "s").replace("'", "").replace("\u2019s", "s")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

def _get_icon(name: str, size: int = 22):
    """Load item icon as PhotoImage, cached. Returns None if not found."""
    slug = _item_slug(name)
    key  = f"{slug}_{size}"
    if key in _icon_cache:
        return _icon_cache[key]
    # Try multiple slug variants
    for s in [slug, slug.replace("-", ""), slug + "2", slug.replace("s-", "-")]:
        p = _ICON_DIR / f"{s}.png"
        if p.exists():
            try:
                img   = Image.open(p).resize((size, size), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                _icon_cache[key] = photo
                return photo
            except Exception:
                pass
    _icon_cache[key] = None   # cache miss
    return None

# ── Persistence ────────────────────────────────────────────────────────────
def _save_state(selected, ignore_emblems, pbe=False):
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps({"selected": selected, "ignore_emblems": ignore_emblems, "pbe": pbe}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

def _load_state() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

# ── Meta loader ────────────────────────────────────────────────────────────
def _load_meta(pbe: bool = False) -> dict:
    """Load meta. pbe=True uses PBE path, pbe=False uses live path."""
    # Phase 7 P1-A: route to correct meta based on PBE flag
    if pbe:
        candidates = ["tft_set17_pbe_meta.json", "tft_set17_meta.json"]
    else:
        candidates = ["tft_set17_meta.json", "tft_set16_meta.json"]
    for fn in candidates:
        fp = _META_DIR / fn
        if fp.exists():
            try:
                data = json.loads(fp.read_text(encoding="utf-8-sig"))
                if not pbe and data.get("_data_type") == "pbe":
                    continue
                _log.debug("Loaded meta: %s (pbe=%s)", fn, pbe)
                return data
            except Exception as e:
                _log.warning("Failed to load %s: %s", fn, e)
    return {}

# ── Team planner code generator ────────────────────────────────────────────
def build_team_code(units: list, meta: dict, set_name: str = "TFTSet17") -> str:
    """
    Build team planner import code.
    Format: "02" + up to 10 champions as 3-char zero-padded hex + set_name
    Uses team_planner_codes (decimal ints) from meta, converted to hex.
    """
    # Load discovered codes if available
    codes_file = _META_DIR / "tft_set17_champion_codes.json"
    live_codes: dict = {}
    if codes_file.exists():
        try:
            live_codes = json.loads(codes_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    tp_codes = {**meta.get("team_planner_codes", {}), **live_codes}
    hex_parts = []
    for unit in units[:10]:
        code = tp_codes.get(unit)
        if code is not None:
            hex_parts.append(f"{int(code):03x}")
    # Pad to exactly 10 slots
    while len(hex_parts) < 10:
        hex_parts.append("000")
    return f"02{''.join(hex_parts)}{set_name}"

# ── LCU team planner import ────────────────────────────────────────────────
def _lcu_import_units(units: list, team_id: str, set_id: str = "TFTSet17") -> bool:
    """Import units into LCU team planner using correct string-array format."""
    import ssl
    import base64
    import urllib.request as _ur
    lockfiles = [
        Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
        Path(r"C:\Riot Games\League of Legends\lockfile"),
    ]
    lf = next((p for p in lockfiles if p.exists()), None)
    if not lf:
        return False
    try:
        parts = lf.read_text().strip().split(":")
        port, pw = parts[2], parts[3]
        auth = base64.b64encode(f"riot:{pw}".encode()).decode()
        sctx = ssl.create_default_context()
        sctx.check_hostname = False
        sctx.verify_mode    = ssl.CERT_NONE
        hdrs = {"Authorization": f"Basic {auth}", "Content-Type": "application/json", "Accept": "application/json"}
        def _to_tft_id(u):
            s = str(u)
            # Remove all non-alphanumeric except underscore
            import re as _re
            s = _re.sub(r"[^A-Za-z0-9]", "", s)
            return "TFT17_" + s
        champ_ids = [_to_tft_id(u) for u in units[:10] if u]
        body = json.dumps(champ_ids).encode()
        ep   = f"https://192.168.8.237:{port}/lol-tft-team-planner/v1/sets/{set_id}/teams/{team_id}/import"
        req  = _ur.Request(ep, data=body, headers=hdrs, method="POST")
        with _ur.urlopen(req, context=sctx, timeout=5) as r:
            _log.info("LCU import: %d units HTTP %d", len(champ_ids), r.status)
            return r.status in (200, 201, 204)
    except Exception as e:
        _log.debug("LCU import failed: %s", e)
        return False

_lcu_import_team_code = _lcu_import_units  # backwards compat alias

def _lcu_get_team_id() -> str:
    """Get the current team planner team ID from previous-context endpoint."""
    import ssl
    import base64
    import urllib.request as _ur
    lockfiles = [
        Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
        Path(r"C:\Riot Games\League of Legends\lockfile"),
    ]
    lf = next((p for p in lockfiles if p.exists()), None)
    if not lf:
        return ""
    try:
        parts = lf.read_text().strip().split(":")
        port, pw = parts[2], parts[3]
        auth = base64.b64encode(f"riot:{pw}".encode()).decode()
        sctx = ssl.create_default_context()
        sctx.check_hostname = False
        sctx.verify_mode    = ssl.CERT_NONE
        hdrs = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
        ep   = f"https://192.168.8.237:{port}/lol-tft-team-planner/v1/previous-context"
        req  = _ur.Request(ep, headers=hdrs)
        with _ur.urlopen(req, context=sctx, timeout=3) as r:
            data = json.loads(r.read().decode())
            return data.get("optionalTeamId", "")
    except Exception:
        return ""

def _clip_silent(text: str):
    """Copy text to clipboard without flashing a PowerShell window.

    AUDIT C1 (2026-04-22): previously interpolated ``text`` into a
    PowerShell ``-Command`` string with single-quotes. If ``text``
    contained ``'``, ``;``, or ``|`` this allowed arbitrary command
    execution. Now we pass the payload via stdin and let PowerShell read
    it literally — no user data ever enters the command line.
    """
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$input | Set-Clipboard"],
            input=text, encoding="utf-8",
            capture_output=True, timeout=3, startupinfo=si,
        )
    except Exception:
        pass

# ── Tooltip ────────────────────────────────────────────────────────────────
class _Tooltip:
    """Robust tooltip: delayed show, auto-expire, force-destroy on leave/click."""
    def __init__(self, widget, text_or_func):
        self._w   = widget
        self._fn  = text_or_func if callable(text_or_func) else lambda: text_or_func
        self._tw  = None
        self._aid = None
        widget.bind("<Enter>",    self._enter)
        widget.bind("<Leave>",    self._leave)
        widget.bind("<Destroy>",  self._leave)
        widget.bind("<Button-1>", self._leave)

    def _enter(self, event):
        self._kill()
        self._ex = event.x_root
        self._ey = event.y_root
        try:
            self._aid = self._w.after(350, self._show)
        except Exception:
            pass

    def _show(self):
        self._aid = None
        text = self._fn()
        if not text:
            return
        try:
            if not self._w.winfo_exists():
                return
            self._tw = tw = tk.Toplevel(self._w)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", False)
            tw.wm_geometry(f"+{self._ex + 14}+{self._ey + 8}")
            tk.Label(
                tw, text=text, bg="#1a1a2a", fg="#e0e0ff",
                font=("Segoe UI", 9), justify="left",
                relief="solid", borderwidth=1, padx=8, pady=5,
            ).pack()
            tw.after(4000, self._kill)
        except Exception:
            self._tw = None

    def _leave(self, event=None):
        self._kill()

    def _kill(self):
        if self._aid:
            try:
                self._w.after_cancel(self._aid)
            except Exception:
                pass
            self._aid = None
        if self._tw:
            try:
                self._tw.destroy()
            except Exception:
                pass
            self._tw = None


# ══════════════════════════════════════════════════════════════════════════
#  CompControl
# ══════════════════════════════════════════════════════════════════════════
class CompControl(tk.Frame):
    """Scrollable meta comp selector. Height reduced by 15px vs old version."""

    def __init__(self, parent, on_select=None):
        super().__init__(parent, bg=BG_SEC,
                         highlightbackground=BORDER, highlightthickness=1)
        self._on_select      = on_select
        # Phase 7 P1-A: load meta based on saved pbe state
        _st_early = _load_state()
        self._meta = _load_meta(pbe=_st_early.get("pbe", False))
        self._selected: str | None = None
        self._ignore_emblems = tk.BooleanVar(value=False)
        self._pbe            = tk.BooleanVar(value=True)
        self._emblem_comps: set = set()
        self._comp_frames: dict = {}

        # ── Header: title + checkboxes ─────────────────────────────────
        hdr = tk.Frame(self, bg=BG_SEC)
        hdr.pack(fill="x", padx=4, pady=(3, 0))
        tk.Label(hdr, text="COMP", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 10, "bold"), anchor="w").pack(side="left")
        tk.Checkbutton(
            hdr, text="PBE", bg=BG_SEC, fg="#ff8844", selectcolor=BG,
            activebackground=BG_SEC, font=("Segoe UI", 7),
            variable=self._pbe, command=self._on_pbe_toggle,
        ).pack(side="right", padx=(0, 1))
        tk.Checkbutton(
            hdr, text="Emblems", bg=BG_SEC, fg="#9090aa", selectcolor=BG,
            activebackground=BG_SEC, font=("Segoe UI", 7),
            variable=self._ignore_emblems, command=self._on_emblem_toggle,
        ).pack(side="right", padx=(0, 1))

        # ── Search ────────────────────────────────────────────────────
        sf = tk.Frame(self, bg=BG_SEC)
        sf.pack(fill="x", padx=4, pady=(1, 0))
        self._search_var = tk.StringVar()
        se = tk.Entry(sf, textvariable=self._search_var,
                      bg="#1a1a2a", fg="#d0d0e0", insertbackground="#d0d0e0",
                      font=("Segoe UI", 7), relief="flat", bd=0,
                      highlightbackground="#333355", highlightthickness=1, width=16)
        se.pack(side="right")
        se.bind("<KeyRelease>", lambda e: self._filter_comps())
        se.bind("<Escape>",     lambda e: (self._search_var.set(""), self._filter_comps()))

        # ── Scrollable list ────────────────────────────────────────────
        self._canvas     = tk.Canvas(self, bg=BG_SEC, bd=0, highlightthickness=0)
        self._scrollbar  = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._list_frame = tk.Frame(self._canvas, bg=BG_SEC)
        self._list_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.create_window((0, 0), window=self._list_frame, anchor="nw")
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=(1, 3))
        self._scrollbar.pack(side="right", fill="y", pady=(1, 3))
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", self._scroll))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        self._build_comp_list()

        # Restore state
        _st = _load_state()
        if _st.get("ignore_emblems"):
            self._ignore_emblems.set(True)
        if "pbe" in _st:
            self._pbe.set(_st["pbe"])
        _last = _st.get("selected")
        if _last and _last in self._comp_frames:
            self.after(100, lambda: self._select_comp(_last))

    # ── Helpers ────────────────────────────────────────────────────────
    def _scroll(self, event):
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _on_pbe_toggle(self):
        _save_state(self._selected, self._ignore_emblems.get(), self._pbe.get())
        self._meta = _load_meta(pbe=self._pbe.get())  # Phase 7 P1-A
        self._build_comp_list()
        _log.info("PBE toggle -> %s", self._pbe.get())
        # Phase 7 P1-A: reload meta when PBE flag changes
        self._meta = _load_meta(pbe=self._pbe.get())
        self._build_comp_list()
        _log.info("PBE toggle -> pbe=%s", self._pbe.get())

    def is_pbe(self) -> bool:
        return self._pbe.get()

    def _on_emblem_toggle(self):
        self._refresh_emblem_highlights()
        _save_state(self._selected, self._ignore_emblems.get(), self._pbe.get())

    def _filter_comps(self):
        q = self._search_var.get().strip().lower()
        comps_db = self._meta.get("comps", {})
        for name, w in self._comp_frames.items():
            if not q:
                w["frame"].pack(fill="x", padx=2, pady=1)
                continue
            comp  = comps_db.get(name, {})
            parts = [name.lower()]
            for k in ("core_units", "flex_units", "lv9"):
                parts.extend(str(u).lower() for u in comp.get(k, []))
            parts.extend(str(t).lower() for t in comp.get("emblem_value", []))
            parts.append(comp.get("gameplan", "").lower())
            if q in " ".join(parts):
                w["frame"].pack(fill="x", padx=2, pady=1)
            else:
                w["frame"].pack_forget()

    # ── Build list ─────────────────────────────────────────────────────
    def _build_comp_list(self):
        tier_list = self._meta.get("tier_list", {})
        comps_db  = self._meta.get("comps", {})
        all_comps = []
        for tier in ("S", "A", "B", "C"):
            for cd in tier_list.get(tier, []):
                name = cd.get("name", "?") if isinstance(cd, dict) else str(cd)
                if name in comps_db:
                    top4 = comps_db[name].get("top4_pct", 0)
                    all_comps.append((name, tier, top4))
        all_comps.sort(key=lambda x: -x[2])
        for name, tier, top4 in all_comps:
            self._add_comp_row(name, tier, top4)

    def _add_comp_row(self, name: str, tier: str, top4: int = 0):
        if name not in self._meta.get("comps", {}):
            return
        f = tk.Frame(self._list_frame, bg=BG_SEC, cursor="hand2",
                     highlightbackground=BORDER, highlightthickness=1)
        f.pack(fill="x", padx=2, pady=1)

        tc = _TIER_COLORS.get(tier, "#888888")
        tk.Label(f, text=tier, bg=BG_SEC, fg=tc,
                 font=("Consolas", 9, "bold"), width=2).pack(side="left", padx=(4, 2))

        # Build display label with source suffix
        _comp_data_row = self._meta.get("comps", {}).get(name, {})
        _src = _comp_data_row.get("display_source", "")
        _SRC_LABELS = {"moba": "M", "bunny": "B", "overlay app E": "Z",
                       "moba+bunny": "MB", "bunny+moba": "MB",
                       "moba+overlay app E": "MZ", "overlay app E+moba": "MZ",
                       "bunny+overlay app E": "BZ", "moba+bunny+overlay app E": "MBZ"}
        _src_tag = _SRC_LABELS.get(_src, "")
        _display_name = f"{name}  [{_src_tag}]" if _src_tag else name
        lbl = tk.Label(f, text=_display_name, bg=BG_SEC, fg="#d0d0e0",
                       font=("Segoe UI", 9), anchor="w")
        lbl.pack(side="left", fill="x", expand=True, padx=(2, 4))

        if top4 > 0:
            t4c = "#44FF88" if top4 >= 60 else "#4A9EFF" if top4 >= 50 else "#D0D0E0"
            tk.Label(f, text=f"{top4}%", bg=BG_SEC, fg=t4c,
                     font=("Consolas", 7), width=4).pack(side="right", padx=(0, 2))

        chk = tk.Label(f, text="", bg=BG_SEC, fg="#44ff88",
                       font=("Consolas", 11, "bold"))
        chk.pack(side="right", padx=(2, 6))

        self._comp_frames[name] = {"frame": f, "label": lbl, "check": chk, "tier": tier}

        for widget in (f, lbl, chk):
            widget.bind("<Button-1>",           lambda e, n=name: self._select_comp(n))
            widget.bind("<Control-Button-1>",   lambda e, n=name: self._clipboard_code(n))
            widget.bind("<Button-3>",           lambda e: self._deselect_comp())

        # Tooltip: show gameplan + level plan
        comp_data = self._meta.get("comps", {}).get(name, {})
        tip = "\n".join(filter(None, [
            comp_data.get("gameplan", ""),
            f"Level plan: {comp_data.get('level_plan', '')}",
        ]))
        if tip:
            _Tooltip(f, tip)

    # ── Selection ─────────────────────────────────────────────────────
    def _select_comp(self, name: str):
        if self._selected == name:
            self._deselect_comp()
            return
        self._selected = name
        for n, w in self._comp_frames.items():
            if n == name:
                w["frame"].configure(bg=_SELECTED_BG)
                w["label"].configure(bg=_SELECTED_BG, fg="#ffffff")
                w["check"].configure(bg=_SELECTED_BG, text="✓")
            else:
                bg = _EMBLEM_BG if (not self._ignore_emblems.get() and n in self._emblem_comps) else BG_SEC
                brd = _EMBLEM_BORDER if bg == _EMBLEM_BG else BORDER
                w["frame"].configure(bg=bg, highlightbackground=brd)
                w["label"].configure(bg=bg, fg="#d0d0e0")
                w["check"].configure(bg=bg, text="")

        _log.info("Comp selected: %s", name)
        _save_state(name, self._ignore_emblems.get(), self._pbe.get())

        # Build and push team code
        comp_data = self._meta.get("comps", {}).get(name, {})
        lv9 = comp_data.get("lv9") or comp_data.get("core_units", []) + comp_data.get("flex_units", [])
        _log.info("Team import: %s -> %s", name, lv9[:8])

        # Store for retry
        self._last_import_units = list(lv9)
        self._last_import_name  = name

        # Always copy unit names to clipboard (readable, usable format)
        unit_names_str = ", ".join(lv9[:10])
        _clip_silent(unit_names_str)
        _log.info("Clipboard: %s", unit_names_str)

        # LCU direct import in background
        _lv9_import = list(lv9)
        def _do_import(_u=_lv9_import, _n=name):
            team_id = _lcu_get_team_id()
            if team_id:
                ok = _lcu_import_units(_u, team_id)
                status = "LCU OK" if ok else "LCU FAIL"
                _log.info("Team planner import: %s -> %s", _n, status)
            else:
                _log.info("Team planner: no team_id (open team planner first)")
        threading.Thread(target=_do_import, daemon=True, name="TeamPlannerImport").start()

        if self._on_select:
            self._on_select(name, comp_data)

    def push_to_planner(self, name: str = None) -> str:
        """Push current (or named) comp to team planner via LCU. Returns status string."""
        target = name or self._selected
        if not target:
            return "No comp selected"
        comp_data = self._meta.get("comps", {}).get(target, {})
        lv9 = comp_data.get("lv9") or comp_data.get("core_units", []) + comp_data.get("flex_units", [])
        if not lv9:
            return "No units in comp"
        # Always clip unit names
        _clip_silent(", ".join(lv9[:10]))
        # Try LCU
        team_id = _lcu_get_team_id()
        if team_id:
            ok = _lcu_import_units(lv9, team_id)
            return f"Pushed {target} ({len(lv9)} units)" if ok else "LCU import failed — units clipped"
        return f"Clipped: {', '.join(lv9[:6])}..."

    def _clipboard_code(self, name: str):
        """Ctrl+click: copy unit names to clipboard."""
        comp_data = self._meta.get("comps", {}).get(name, {})
        lv9 = comp_data.get("lv9") or []
        unit_str = ", ".join(lv9[:10])
        _clip_silent(unit_str)
        _log.info("Units clipped (ctrl+click): %s -> %s", name, unit_str)

    def _deselect_comp(self):
        self._selected = None
        for w in self._comp_frames.values():
            w["frame"].configure(bg=BG_SEC, highlightbackground=BORDER)
            w["label"].configure(bg=BG_SEC, fg="#d0d0e0")
            w["check"].configure(bg=BG_SEC, text="")
        _save_state(None, self._ignore_emblems.get(), self._pbe.get())
        if self._on_select:
            self._on_select(None, {})

    def set_emblem(self, emblem_name: str):
        self._emblem_comps.clear()
        if not emblem_name:
            self._refresh_emblem_highlights()
            return
        for name, data in self._meta.get("comps", {}).items():
            if isinstance(data, dict):
                if any(emblem_name.lower() in str(e).lower() for e in data.get("emblem_value", [])):
                    self._emblem_comps.add(name)
        self._refresh_emblem_highlights()

    def _refresh_emblem_highlights(self):
        for name, w in self._comp_frames.items():
            if name == self._selected:
                continue
            if not self._ignore_emblems.get() and name in self._emblem_comps:
                w["frame"].configure(bg=_EMBLEM_BG, highlightbackground=_EMBLEM_BORDER)
                w["label"].configure(bg=_EMBLEM_BG)
                w["check"].configure(bg=_EMBLEM_BG)
            else:
                w["frame"].configure(bg=BG_SEC, highlightbackground=BORDER)
                w["label"].configure(bg=BG_SEC)
                w["check"].configure(bg=BG_SEC)

    def get_selected(self) -> tuple:
        if self._selected:
            return self._selected, self._meta.get("comps", {}).get(self._selected, {})
        return None, {}

    def get_meta(self) -> dict:
        return self._meta


# ══════════════════════════════════════════════════════════════════════════
#  ChampItemControl  — shows BIS items with PNG icons + component breakdown
# ══════════════════════════════════════════════════════════════════════════
class ChampItemControl(tk.Frame):
    """BIS items per champion with icon clipart, tooltips, and built-state tracking."""

    ICON_SIZE = 22   # item icon size in pixels

    def __init__(self, parent):
        super().__init__(parent, bg=BG_SEC,
                         highlightbackground=BORDER, highlightthickness=1)
        self._comp_name: str | None  = None
        self._comp_data: dict        = {}
        self._built_items: dict      = {}   # {(champ, i): True}

        tk.Label(self, text="CHAMP / ITEM", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 10, "bold"), anchor="w").pack(
            anchor="w", padx=4, pady=(4, 0))

        self._scroll_canvas = tk.Canvas(self, bg=BG_SEC, bd=0, highlightthickness=0)
        self._scroll_sb     = tk.Scrollbar(self, orient="vertical",
                                            command=self._scroll_canvas.yview)
        self._inner         = tk.Frame(self._scroll_canvas, bg=BG_SEC)
        self._inner.bind(
            "<Configure>",
            lambda e: self._scroll_canvas.configure(
                scrollregion=self._scroll_canvas.bbox("all")))
        self._scroll_canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._scroll_canvas.configure(yscrollcommand=self._scroll_sb.set)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scroll_sb.pack(side="right", fill="y")
        self._scroll_canvas.bind(
            "<Enter>",
            lambda e: self._scroll_canvas.bind_all(
                "<MouseWheel>",
                lambda ev: self._scroll_canvas.yview_scroll(-1 * (ev.delta // 120), "units")))
        self._scroll_canvas.bind(
            "<Leave>",
            lambda e: self._scroll_canvas.unbind_all("<MouseWheel>"))

        self._empty_label = tk.Label(self._inner, text="Select a comp above",
                                      bg=BG_SEC, fg="#555566", font=("Segoe UI", 9))
        self._empty_label.pack(expand=True)

    # ── Public API ─────────────────────────────────────────────────────
    def set_comp(self, name: str | None, comp_data: dict):
        self._comp_name  = name
        self._comp_data  = comp_data
        self._built_items.clear()
        for w in self._inner.winfo_children():
            w.destroy()

        if not name or not comp_data:
            tk.Label(self._inner, text="Select a comp above",
                     bg=BG_SEC, fg="#555566", font=("Segoe UI", 9)).pack(expand=True)
            return

        items_data = comp_data.get("items", {})
        if not items_data:
            tk.Label(self._inner,
                     text=f"{name}\n(No item data)",
                     bg=BG_SEC, fg="#888888",
                     font=("Segoe UI", 9)).pack(expand=True)
            return

        meta     = _load_meta()
        item_db  = meta.get("items", {})
        costs    = meta.get("unit_costs", {})
        lv9_all  = comp_data.get("lv9", [])
        core_set = set(comp_data.get("core_units", []))
        shown    = set()

        # Augment advice row (if comp has augment recommendations)
        aug_data = comp_data.get("augment_advice", {})
        if aug_data:
            ar = tk.Frame(self._inner, bg="#1a1a2a",
                          highlightbackground="#444444", highlightthickness=1)
            ar.pack(fill="x", pady=(0, 3), padx=2)
            tk.Label(ar, text="AUGMENTS", bg="#1a1a2a", fg="#ffd700",
                     font=("Consolas", 8, "bold"), anchor="w").pack(
                anchor="w", padx=4, pady=(2, 0))
            for tier_key in ("prismatic", "gold", "silver"):
                names = aug_data.get(tier_key, [])
                if names:
                    tc = {"prismatic": "#cc66ff", "gold": "#ffd700", "silver": "#aaaaaa"}[tier_key]
                    tk.Label(ar, text=f"{tier_key.upper()}: {', '.join(names[:3])}",
                             bg="#1a1a2a", fg=tc,
                             font=("Segoe UI", 8), anchor="w",
                             wraplength=300, justify="left").pack(anchor="w", padx=8, pady=(0, 1))

        # Level/gold timing row
        level_plan = comp_data.get("level_plan", "")
        timing     = comp_data.get("gameplan", "")
        if level_plan:
            tr = tk.Frame(self._inner, bg="#0a1a0a",
                          highlightbackground="#224422", highlightthickness=1)
            tr.pack(fill="x", pady=(0, 2), padx=2)
            tk.Label(tr, text=f"📈 {level_plan.upper().replace('_', ' ')}  |  {timing[:80]}",
                     bg="#0a1a0a", fg="#44ff88",
                     font=("Segoe UI", 8), anchor="w",
                     wraplength=310, justify="left").pack(anchor="w", padx=6, pady=2)


        # Units WITH items first (carries/tanks)
        for champ, item_info in items_data.items():
            shown.add(champ)
            self._add_unit_row(champ, item_info, item_db, costs, core_set, is_flex=False)

        # Remaining Lv9 units without dedicated item data
        for unit in lv9_all:
            if unit in shown:
                continue
            shown.add(unit)
            cost = costs.get(unit, 3)
            cc   = _COST_COLORS.get(cost, "#888899")
            row  = tk.Frame(self._inner, bg=BG_SEC)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=unit, bg=BG_SEC, fg=cc,
                     font=("Segoe UI", 8), width=12, anchor="w").pack(
                side="left", padx=(4, 4))
            tk.Label(row, text=f"({cost}g)", bg=BG_SEC, fg="#556677",
                     font=("Consolas", 7)).pack(side="left")


    # ── Private: unit row ──────────────────────────────────────────────
    def _add_unit_row(self, champ: str, item_info: dict, item_db: dict,
                      costs: dict, core_set: set, is_flex: bool):
        meta  = _load_meta()
        cost  = costs.get(champ, 3)
        cc    = _COST_COLORS.get(cost, "#d0d0e0")
        is_core = champ in core_set
        row   = tk.Frame(self._inner, bg=BG_SEC)
        row.pack(fill="x", pady=1)

        # Champion name label
        font_w = "bold" if is_core else "normal"
        tk.Label(row, text=champ, bg=BG_SEC, fg=cc,
                 font=("Segoe UI", 9, font_w), width=11, anchor="w").pack(
            side="left", padx=(4, 2))

        # Trait / special effect (if available)
        nova_data = meta.get("nova_units", {}).get(champ)
        if nova_data:
            strike = nova_data.get("strike", "")
            if strike:
                tk.Label(row, text=f"⚡{strike[:18]}", bg=BG_SEC, fg="#44ccff",
                         font=("Segoe UI", 7), anchor="w").pack(side="left", padx=(0, 4))

        # BIS items with icons
        bis = item_info.get("bis", [])[:3]
        alt = item_info.get("alt", [])
        for i, item_name in enumerate(bis):
            self._add_item_widget(row, champ, i, item_name, item_db, is_core)

        # Alt item divider + name (text only, smaller)
        if alt:
            tk.Label(row, text="|", bg=BG_SEC, fg="#333345",
                     font=("Consolas", 8)).pack(side="left", padx=1)
            alt_name = alt[0]
            comps    = item_db.get(alt_name, {}).get("components", [])
            tip_text = f"{alt_name}\n{'  +  '.join(comps)}" if comps else alt_name
            short    = alt_name[:7] if len(alt_name) > 7 else alt_name
            al = tk.Label(row, text=short, bg=BG_SEC, fg="#667788",
                          font=("Consolas", 7))
            al.pack(side="left", padx=1)
            _Tooltip(al, tip_text)

    def _add_item_widget(self, row, champ: str, idx: int, item_name: str,
                          item_db: dict, is_core: bool):
        meta      = _load_meta()
        components = item_db.get(item_name, {}).get("components", [])
        tip_lines  = [item_name]
        if components:
            tip_lines.append("  +  ".join(components))
        # Add type
        itype = item_db.get(item_name, {}).get("type", "")
        if itype:
            tip_lines.append(f"Type: {itype}")
        tip_text = "\n".join(tip_lines)

        border_c = "#665500" if is_core else "#2a2a44"
        frame    = tk.Frame(row, bg="#16161f",
                             highlightbackground=border_c,
                             highlightthickness=1, cursor="hand2")
        frame.pack(side="left", padx=1)

        icon = _get_icon(item_name, self.ICON_SIZE)
        key  = (champ, idx)

        if icon:
            lbl = tk.Label(frame, image=icon, bg="#16161f", padx=1, pady=1)
            lbl._icon_ref = icon   # keep reference
        else:
            # Styled text fallback
            short = item_name[:6]
            item_type = item_db.get(item_name, {}).get("type", "")
            fg = {"AP": "#88aaff", "AD": "#ffaa44", "AS": "#44ffaa",
                  "tank": "#44ccff", "utility": "#ffdd44"}.get(item_type, "#c0c0d8")
            lbl = tk.Label(frame, text=short, bg="#16161f", fg=fg,
                           font=("Consolas", 7, "bold"), padx=3, pady=2)
        lbl.pack()

        # Click → toggle built
        for w in (frame, lbl):
            w.bind("<Button-1>",
                   lambda e, k=key, f=frame, l=lbl, n=item_name: self._toggle_built(k, f, l, n))

        _Tooltip(frame, tip_text)

    def _toggle_built(self, key, frame, label, item_name=""):
        if key in self._built_items:
            del self._built_items[key]
            frame.configure(bg="#16161f", highlightbackground="#2a2a44")
            label.configure(bg="#16161f")
        else:
            self._built_items[key] = item_name
            frame.configure(bg="#0a2a0a", highlightbackground="#44ff88")
            label.configure(bg="#0a2a0a")
        self._persist_built_items()

    def _persist_built_items(self):
        try:
            _f = _STATE_FILE
            _d = json.loads(_f.read_text(encoding="utf-8")) if _f.exists() else {}
            _d["built_items"] = {f"{c}:{i}": n for (c,i),n in self._built_items.items() if n}
            _tmp = _f.with_suffix(".json.tmp")
            _tmp.write_text(json.dumps(_d, indent=2), encoding="utf-8")
            _tmp.replace(_f)
        except Exception as _exc:
            _log.debug("comp_control built_items persist failed: %s", _exc)
