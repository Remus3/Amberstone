"""
ui/aram_pregame_panel.py — ARAM pre-game champion select panel.

Appears in the unused strip at x=0, y=900, w=800, h=148 —
to the LEFT of the ClientPanel mode tabs, below the League client.

Only visible during ARAM / KIWI champion select.
Disappears automatically when champ select ends.

Features:
  • My champion choice(s) shown as clickable icons — click to pick
  • Bench champions shown — click to swap (bypasses 5-second client cooldown)
  • Summoner spell toggles: Snowball (default ON) | Exhaust | AI Chosen
    — mutually exclusive; clicking one disables the other two
  • Champion icons loaded from LCU local asset server
"""
from __future__ import annotations

import io
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import font as tkfont

_log = logging.getLogger("rc.ui.pregame")

# ── Geometry ──────────────────────────────────────────────────────────────────
GEO = {"x": 0, "y": 900, "w": 800, "h": 148}

# ── Colours (match RC dark theme) ────────────────────────────────────────────
BG          = "#0a0a12"
BORDER      = "#2a2a3a"
HEADER_BG   = "#111120"
HEADER_FG   = "#7788aa"
NAME_FG     = "#c8c8dd"
DIM_FG      = "#555566"
SEL_BORDER  = "#55aaff"   # active selection highlight
BENCH_BG    = "#0e0e1a"
BTN_OFF_BG  = "#1a1a28"
BTN_OFF_FG  = "#666677"
BTN_OFF_BD  = "#333344"
BTN_ON_BG   = "#1e3060"
BTN_ON_FG   = "#88ccff"
BTN_ON_BD   = "#4488cc"
BTN_HOVER   = "#252535"

# ── Icon sizes ────────────────────────────────────────────────────────────────
MY_ICON_SZ  = 58   # my champion choices
BENCH_ICON_SZ = 42 # bench champions
ICON_CACHE: dict[tuple[int,int], object] = {}  # (champ_id, size) → PhotoImage

# ── Summoner spell presets ────────────────────────────────────────────────────
MODE_SNOWBALL = "snowball"   # Flash + Snowball (default ON)
MODE_EXHAUST  = "exhaust"    # Flash + Exhaust
MODE_AI       = "ai"         # AI-recommended

try:
    from lcu.lcu_rune_writer import save_spell_pref as _save_spell_pref
except Exception:
    def _save_spell_pref(k, v): pass  # type: ignore

SPELL_IDS = {
    "flash":    4,
    "snowball": 32,
    "exhaust":  3,
    "heal":     7,
    "barrier":  21,
}


def _make_placeholder(size: int, label: str) -> "tk.PhotoImage":
    """Create a simple coloured placeholder when no icon is available."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk
        img = Image.new("RGBA", (size, size), (30, 30, 50, 255))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, size-3, size-3], fill=(60, 60, 100), outline=(80, 80, 130))
        # Draw first 2 chars of label
        txt = label[:2].upper() if label else "?"
        try:
            fnt = ImageFont.truetype("arial.ttf", size // 3)
        except Exception:
            fnt = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), txt, font=fnt)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size - tw) // 2, (size - th) // 2), txt, fill=(180, 180, 220), font=fnt)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def _load_icon(lcu, champ_id: int, size: int) -> Optional[object]:
    """Load champion icon from LCU asset server, cached by (id, size)."""
    key = (champ_id, size)
    if key in ICON_CACHE:
        return ICON_CACHE[key]
    try:
        from PIL import Image, ImageTk
        data = lcu.get_champion_icon_bytes(champ_id)
        if data:
            img = Image.open(io.BytesIO(data)).convert("RGBA").resize(
                (size, size), Image.LANCZOS)
            ph = ImageTk.PhotoImage(img)
            ICON_CACHE[key] = ph
            return ph
    except Exception as exc:
        _log.debug("_load_icon(%d, %d): %s", champ_id, size, exc)
    # Return placeholder
    return None


class _ChampButton(tk.Frame):
    """Single champion icon button with name label below."""

    def __init__(self, parent, lcu, champ_id: int, champ_name: str,
                 icon_size: int, on_click, is_mine: bool = False):
        super().__init__(parent, bg=BG)
        self._lcu       = lcu
        self._champ_id  = champ_id
        self._champ_name = champ_name
        self._icon_size = icon_size
        self._on_click  = on_click
        self._is_mine   = is_mine
        self._photo     = None

        # Border frame for selection highlight
        self._border = tk.Frame(
            self, bg=SEL_BORDER if is_mine else BORDER,
            highlightthickness=0
        )
        self._border.pack(padx=1, pady=1)

        # Icon canvas
        self._canvas = tk.Canvas(
            self._border, width=icon_size, height=icon_size,
            bg=BENCH_BG, highlightthickness=0, cursor="hand2"
        )
        self._canvas.pack()
        self._canvas.bind("<Button-1>", self._click)
        self._canvas.bind("<Enter>", self._hover_on)
        self._canvas.bind("<Leave>", self._hover_off)

        # Name label (up to 2 lines, truncated)
        name_disp = self._wrap_name(champ_name, 10)
        self._name_lbl = tk.Label(
            self, text=name_disp, bg=BG,
            fg=NAME_FG if not is_mine else SEL_BORDER,
            font=("Segoe UI", 7, "bold" if is_mine else "normal"),
            justify="center", anchor="n",
            width=icon_size // 7 + 1,
            wraplength=icon_size + 4,
        )
        self._name_lbl.pack()
        self._name_lbl.bind("<Button-1>", self._click)

        # Load icon in background
        threading.Thread(target=self._load_and_draw, daemon=True).start()

    @staticmethod
    def _wrap_name(name: str, max_per_line: int) -> str:
        """Wrap champion name for 2-line display."""
        if len(name) <= max_per_line:
            return name
        # Try split on space
        parts = name.split()
        if len(parts) >= 2 and len(parts[0]) <= max_per_line:
            return parts[0] + "\n" + " ".join(parts[1:])
        return name[:max_per_line] + "\n" + name[max_per_line:max_per_line*2]

    def _load_and_draw(self):
        photo = _load_icon(self._lcu, self._champ_id, self._icon_size)
        if photo:
            self._photo = photo
            try:
                self._canvas.after(0, self._draw)
            except Exception:
                pass

    def _draw(self):
        if self._photo:
            try:
                self._canvas.delete("all")
                self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
            except Exception:
                pass  # widget destroyed before icon loaded

    def _click(self, _event=None):
        if self._on_click:
            self._on_click(self._champ_id, self._champ_name)

    def _hover_on(self, _event=None):
        self._border.config(bg=SEL_BORDER)

    def _hover_off(self, _event=None):
        self._border.config(bg=SEL_BORDER if self._is_mine else BORDER)

    def set_selected(self, selected: bool):
        self._is_mine = selected
        self._border.config(bg=SEL_BORDER if selected else BORDER)
        self._name_lbl.config(fg=SEL_BORDER if selected else NAME_FG,
                               font=("Segoe UI", 7, "bold" if selected else "normal"))


class AramPregamePanel(tk.Toplevel):
    """
    ARAM pre-game champion select overlay.
    Positioned at x=0, y=900, w=800, h=148 (below League client,
    left of the ClientPanel mode tabs).

    Lifecycle:
      Created once in main.py.
      Hides itself when not in ARAM champ select.
      Polls the LCU every 1.5s.
    """

    POLL_INTERVAL = 1.5   # seconds

    def __init__(self, root: tk.Tk, lcu):
        super().__init__(root)
        self._root  = root
        self._lcu   = lcu
        self._stop  = threading.Event()

        # State
        # Load saved spell preference (default: snowball)
        try:
            import json as _j
            from pathlib import Path as _P
            _pp = _P(__file__).parent.parent / "data" / "spell_prefs.json"
            self._spell_mode = _j.loads(_pp.read_text()).get("aram_mode", MODE_SNOWBALL)
        except Exception:
            self._spell_mode = MODE_SNOWBALL
        self._last_session  = None
        self._champ_id_map: dict[int, str] = {}
        self._my_champ_btns: list[_ChampButton] = []
        self._bench_btns:    list[_ChampButton]  = []
        self._ai_spell_info = ("flash", "snowball")  # AI default for ARAM

        # Build window
        self._setup_window()
        self._build_ui()

        # Load champion ID map
        threading.Thread(target=self._load_champ_map, daemon=True).start()

        # Start poll loop
        self._hidden = True
        self.withdraw()
        self._root.after(500, self._poll_tick)

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self):
        g = GEO
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.overrideredirect(True)  # no title bar
        self.attributes("-topmost", True)
        self.configure(bg=BG)
        # Subtle border
        self.config(highlightbackground=BORDER, highlightthickness=1)

    def _build_ui(self):
        """Build the static panel structure."""
        # Root container
        self._container = tk.Frame(self, bg=BG,
                                   highlightbackground=BORDER,
                                   highlightthickness=1)
        self._container.pack(fill="both", expand=True, padx=0, pady=0)

        # ── Header row ───────────────────────────────────────────────────────
        hdr = tk.Frame(self._container, bg=HEADER_BG, height=18)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="ARAM CHAMP SELECT", bg=HEADER_BG, fg=HEADER_FG,
                 font=("Segoe UI", 7, "bold")).pack(side="left", padx=6)
        self._timer_lbl = tk.Label(hdr, text="", bg=HEADER_BG, fg="#ddaa22",
                                   font=("Segoe UI", 7, "bold"))
        self._timer_lbl.pack(side="left", padx=4)
        self._status_lbl = tk.Label(hdr, text="waiting for champ select...",
                                    bg=HEADER_BG, fg=DIM_FG,
                                    font=("Segoe UI", 7))
        self._status_lbl.pack(side="left", padx=4)

        # ── Main body: Champions left | Spells right ──────────────────────────
        body = tk.Frame(self._container, bg=BG)
        body.pack(fill="both", expand=True, padx=2, pady=2)

        # Left: champions area (610px)
        self._champ_area = tk.Frame(body, bg=BG, width=612)
        self._champ_area.pack(side="left", fill="both", expand=True)
        self._champ_area.pack_propagate(False)

        # My picks section
        self._picks_frame = tk.Frame(self._champ_area, bg=BG)
        self._picks_frame.pack(side="left", fill="y", padx=(2, 4))

        self._picks_lbl = tk.Label(self._picks_frame, text="MY CHAMPION",
                                   bg=BG, fg=DIM_FG, font=("Segoe UI", 6))
        self._picks_lbl.pack(anchor="w")
        self._picks_row = tk.Frame(self._picks_frame, bg=BG)
        self._picks_row.pack()

        # Divider
        tk.Frame(self._champ_area, bg=BORDER, width=1).pack(
            side="left", fill="y", padx=2)

        # Bench section
        self._bench_frame = tk.Frame(self._champ_area, bg=BENCH_BG)
        self._bench_frame.pack(side="left", fill="both", expand=True, padx=2)

        bench_hdr = tk.Frame(self._bench_frame, bg=BENCH_BG)
        bench_hdr.pack(fill="x")
        tk.Label(bench_hdr, text="BENCH  (click to swap — no cooldown)",
                 bg=BENCH_BG, fg=DIM_FG, font=("Segoe UI", 6)).pack(
                     side="left", anchor="w", padx=4)
        self._bench_row = tk.Frame(self._bench_frame, bg=BENCH_BG)
        self._bench_row.pack(fill="x", padx=4, pady=2)

        # Right: summoner spells (180px)
        tk.Frame(body, bg=BORDER, width=1).pack(side="left", fill="y")
        spell_frame = tk.Frame(body, bg=BG, width=182)
        spell_frame.pack(side="left", fill="y", padx=4, pady=2)
        spell_frame.pack_propagate(False)

        tk.Label(spell_frame, text="SUMMONER SPELLS",
                 bg=BG, fg=DIM_FG, font=("Segoe UI", 6)).pack(anchor="w", pady=(0,3))

        self._btn_snowball = self._make_spell_btn(
            spell_frame, "SNOWBALL", "Flash + Snowball", MODE_SNOWBALL)
        self._btn_exhaust = self._make_spell_btn(
            spell_frame, "EXHAUST", "Flash + Exhaust", MODE_EXHAUST)
        self._btn_ai = self._make_spell_btn(
            spell_frame, "AI CHOSEN", "Let AI recommend", MODE_AI)

        # Set initial state
        self._refresh_spell_buttons()

    def _make_spell_btn(self, parent, label: str, tooltip: str,
                        mode: str) -> tk.Button:
        """Create a mutually-exclusive toggle button for summoner spells."""
        btn = tk.Button(
            parent,
            text=f"  {label}",
            anchor="w",
            relief="flat",
            bd=1,
            padx=6, pady=3,
            font=("Segoe UI", 8, "bold"),
            cursor="hand2",
            command=lambda m=mode: self._on_spell_toggle(m),
        )
        btn.pack(fill="x", pady=2)
        return btn

    # ── Summoner spell logic ──────────────────────────────────────────────────

    def _refresh_spell_buttons(self):
        for btn, mode in [(self._btn_snowball, MODE_SNOWBALL),
                          (self._btn_exhaust,  MODE_EXHAUST),
                          (self._btn_ai,       MODE_AI)]:
            on = (self._spell_mode == mode)
            check = "☑" if on else "☐"
            labels = {MODE_SNOWBALL: "SNOWBALL", MODE_EXHAUST: "EXHAUST",
                      MODE_AI: "AI CHOSEN"}
            btn.config(
                text=f"  {check} {labels[mode]}",
                bg=BTN_ON_BG if on else BTN_OFF_BG,
                fg=BTN_ON_FG if on else BTN_OFF_FG,
                highlightbackground=BTN_ON_BD if on else BTN_OFF_BD,
                highlightthickness=1,
            )

    def _on_spell_toggle(self, mode: str):
        if self._spell_mode == mode:
            return  # already set
        self._spell_mode = mode
        self._refresh_spell_buttons()
        _save_spell_pref("aram_mode", mode)  # persist preference
        self._apply_summoner_spells()

    def _apply_summoner_spells(self):
        """Write the chosen summoner spell combo to LCU."""
        if self._spell_mode == MODE_SNOWBALL:
            s1, s2 = SPELL_IDS["flash"], SPELL_IDS["snowball"]
        elif self._spell_mode == MODE_EXHAUST:
            s1, s2 = SPELL_IDS["flash"], SPELL_IDS["exhaust"]
        else:
            # AI: stay with current spells (or set Flash+Snowball as safe default)
            s1, s2 = SPELL_IDS["flash"], SPELL_IDS["snowball"]
        threading.Thread(
            target=self._lcu.set_summoner_spells, args=(s1, s2), daemon=True
        ).start()

    # ── Champion selection logic ──────────────────────────────────────────────

    def _on_pick_click(self, champ_id: int, champ_name: str):
        """User clicked a champion in the 'my picks' section."""
        if self._last_session is None:
            return
        action = self._lcu.get_my_pick_action(self._last_session)
        if action:
            action_id = action.get("id")
            if action_id is not None:
                _log.info("Picking champion %s (%d) via action %d",
                          champ_name, champ_id, action_id)
                threading.Thread(
                    target=self._lcu.pick_champion,
                    args=(action_id, champ_id, True),
                    daemon=True,
                ).start()
        else:
            # Might already be locked — try bench swap
            _log.debug("No pick action found, trying bench swap for %d", champ_id)
            threading.Thread(
                target=self._lcu.bench_swap_fast, args=(champ_id,), daemon=True
            ).start()

    def _on_bench_click(self, champ_id: int, champ_name: str):
        """User clicked a bench champion."""
        _log.info("Bench swapping to %s (%d)", champ_name, champ_id)
        threading.Thread(
            target=self._lcu.bench_swap_fast, args=(champ_id,), daemon=True
        ).start()

    # ── Champion name map ─────────────────────────────────────────────────────

    def _load_champ_map(self):
        try:
            from lcu.lcu_rune_writer import build_champ_id_map
            self._champ_id_map = build_champ_id_map()
            _log.debug("AramPregamePanel: %d champion IDs loaded",
                       len(self._champ_id_map))
        except Exception as exc:
            _log.warning("AramPregamePanel: champ map load: %s", exc)

    def _id_to_name(self, cid: int) -> str:
        return self._champ_id_map.get(cid, f"Champ {cid}")

    # ── Poll loop ─────────────────────────────────────────────────────────────

    def _poll_tick(self):
        """Called every POLL_INTERVAL seconds on the tkinter main thread."""
        threading.Thread(target=self._poll, daemon=True).start()
        try:
            self._root.after(int(self.POLL_INTERVAL * 1000), self._poll_tick)
        except Exception:
            pass  # root destroyed

    def _poll(self):
        """Background poll — calls back to UI thread via after()."""
        try:
            # Only show in ARAM / KIWI
            lobby = self._lcu._request("GET", "/lol-lobby/v2/lobby")
            mode = "CLASSIC"
            if lobby and isinstance(lobby, dict):
                gc = lobby.get("gameConfig", {})
                mode = gc.get("gameMode", "CLASSIC").upper()

            if mode not in ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM"):
                self._root.after(0, self._hide)
                return

            session = self._lcu.get_champ_select()
            if not session or not isinstance(session, dict):
                self._root.after(0, self._hide)
                return

            # We're in ARAM champ select
            self._root.after(0, lambda s=session: self._update_ui(s))

        except Exception as exc:
            _log.debug("AramPregamePanel poll: %s", exc)
            try:
                self._root.after(0, self._hide)
            except Exception:
                pass

    def _update_ui(self, session: dict):
        """Update panel contents from session (called on Tk thread)."""
        self._last_session = session

        # Show panel - apply spells once on first show. Respect HEADLESS:
        # when the web dashboard owns the UI, keep this panel hidden.
        if self._hidden:
            try:
                from app._overlay_manager import _HEADLESS
            except Exception:
                _HEADLESS = False
            if not _HEADLESS:
                self.deiconify()
            self._hidden = False
            self._apply_summoner_spells()  # apply once on first show

        # Timer
        timer = session.get("timer", {})
        secs_left = int(timer.get("adjustedTimeLeftInPhase", 0)) // 1000
        phase = timer.get("phase", "")
        self._timer_lbl.config(text=f"{secs_left}s" if secs_left > 0 else "")

        # Debug: save session for multi-pick format analysis
        try:
            _dbg = Path(__file__).parent.parent / "data" / "debug_champ_select_session.json"
            _dbg.write_text(__import__("json").dumps(session, indent=2, default=str),
                            encoding="utf-8")
        except Exception:
            pass

        # Detect available pick options (standard pick or multi-choice)
        my_champ_id = self._lcu.get_my_current_champion(session)
        # Also check for pickable champions from available pool
        pick_options = self._get_pick_options(session)

        # Get bench
        bench_ids = self._lcu.get_bench_champion_ids(session)

        # Rebuild champion buttons only if changed
        # Use detected pick options if available, else show current champion
        my_ids = pick_options if pick_options else ([my_champ_id] if my_champ_id else [])
        self._rebuild_picks(my_ids)
        self._rebuild_bench(bench_ids)

        # Summoner spells display
        s1, s2 = self._lcu.get_my_summoner_spells(session)
        spell_names = {v: k for k, v in SPELL_IDS.items()}
        s1n = spell_names.get(s1, str(s1))
        s2n = spell_names.get(s2, str(s2))
        self._status_lbl.config(text=f"{s1n.upper()} + {s2n.upper()}")



    def _get_pick_options(self, session: dict) -> list:
        """Return champion IDs the local player can pick from.
        Standard ARAM : returns [assigned_champ_id] (one champion).
        ARAM Mayhem   : returns the subset options during pick phase.
        Falls back to get_my_current_champion if nothing else found.
        """
        # ARAM Mayhem multi-choice: subsetChampionPicks populated during pick phase
        subset = session.get("subsetChampionPicks") or []
        if subset:
            return [int(c) for c in subset if c]

        # Standard path: find the local player in myTeam by localPlayerCellId
        local_cell = session.get("localPlayerCellId", -1)
        for player in (session.get("myTeam") or []):
            if player.get("cellId") == local_cell:
                cid = player.get("championId", 0)
                if cid and cid > 0:
                    return [cid]
                break

        # Last resort: LCU mixin
        cid = self._lcu.get_my_current_champion(session)
        return [cid] if cid else []

    def _rebuild_picks(self, champ_ids: list[int]):
        """Rebuild my champion pick buttons."""
        for w in self._picks_row.winfo_children():
            w.destroy()
        self._my_champ_btns = []

        if not champ_ids:
            tk.Label(self._picks_row, text="Picking...",
                     bg=BG, fg=DIM_FG, font=("Segoe UI", 8)).pack()
            return

        for cid in champ_ids:
            name = self._id_to_name(cid)
            btn = _ChampButton(
                self._picks_row, self._lcu, cid, name,
                MY_ICON_SZ, self._on_pick_click, is_mine=True
            )
            btn.pack(side="left", padx=3)
            self._my_champ_btns.append(btn)

    def _rebuild_bench(self, bench_ids: list[int]):
        """Rebuild bench champion buttons."""
        # Only rebuild if IDs changed
        current_ids = [b._champ_id for b in self._bench_btns]
        if current_ids == bench_ids:
            return

        for w in self._bench_row.winfo_children():
            w.destroy()
        self._bench_btns = []

        for cid in bench_ids[:12]:  # max 12 bench shown
            name = self._id_to_name(cid)
            btn = _ChampButton(
                self._bench_row, self._lcu, cid, name,
                BENCH_ICON_SZ, self._on_bench_click, is_mine=False
            )
            btn.pack(side="left", padx=2)
            self._bench_btns.append(btn)

    def _hide(self):
        if not self._hidden:
            self.withdraw()
            self._hidden = True
            self._last_session = None
            # Clear buttons
            for w in self._picks_row.winfo_children():
                w.destroy()
            for w in self._bench_row.winfo_children():
                w.destroy()
            self._my_champ_btns = []
            self._bench_btns = []
            self._status_lbl.config(text="waiting for champ select...")
            self._timer_lbl.config(text="")

    def destroy(self):
        self._stop.set()
        super().destroy()
