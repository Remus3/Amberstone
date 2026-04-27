"""
core/theme.py — Shared visual constants for all Riot Commander UI.

Single source of truth for colors, fonts, zone geometry, and grade colors.
Import from here instead of defining constants in each panel file.
"""

# ── Background / Frame ───────────────────────────────────────────────────────
BG = "#0b0b12"
BG_SECTION = "#111119"
BG_FIELD = "#16161f"
BORDER = "#252535"

# ── Text colors ──────────────────────────────────────────────────────────────
LABEL_COLOR = "#9090aa"
DIM_TEXT = "#888898"
MODE_INDICATOR_COLOR = "#333345"

# ── Field-specific accent colors ─────────────────────────────────────────────
FIELD_COLORS = {
    "immediate":  "#ff6b4a",
    "next":       "#4a9eff",
    "fight_rule": "#ffa84a",
    "wave":       "#3ddba8",
    "objective":  "#c77dff",
    "reset_item": "#a8c023",
    "risk":       "#ff4a6a",
    "map":        "#6a8cbb",
    "log":        "#667799",
    "pregame":    "#c8c8d8",
    "stat_value": "#d0d0e0",
    "action":     "#ff2244",
    "clock":      "#ffdd00",
    "winpct":     "#aaffcc",
}

# ── Ally / Enemy / Time tag colors ───────────────────────────────────────────
ALLY_COLOR = "#44ff88"
ENEMY_COLOR = "#ff4444"
TIME_COLOR = "#ffdd00"
ITEM_COLOR = "#4ab0ff"

# ── Zone geometry (1920×1080 desktop, 100% DPI) ─────────────────────────────
# Game client: 1600×900 at (0,0). Right panel: 320px wide.
# Bottom strip: 160px tall from y=900 (League bottom edge) to y=1060.
# Taskbar: bottom 40px (y=1040→1080).

GAME_ZONES = {
    "bottom":    {"x": 0,    "y": 900, "w": 1600, "h": 160},  # flush with League 1600x900 bottom
    "right_top": {"x": 1600, "y": 0,   "w": 320,  "h": 520},
    "right_bot": {"x": 1600, "y": 520, "w": 320,  "h": 520},
}

CLIENT_ZONES = {
    "main": {"x": 800, "y": 900, "w": 480, "h": 148},  # below League 900px bottom
}

# ── Grade colors (F→S) ──────────────────────────────────────────────────────
GRADE_COLORS = {
    "S":  "#ffdd00",
    "A":  "#44ff88",
    "B":  "#4a9eff",
    "C":  "#c8c8d8",
    "D":  "#ff8844",
    "F":  "#ff4444",
}

# ── Tab colors for ClientPanel ───────────────────────────────────────────────
TAB_COLORS = {
    "ARAM":  "#44FF88",
    "SR":    "#4A9EFF",
    "ARENA": "#FFA84A",
    "BRAWL": "#FF4A6A",
    "TFT":   "#FFD700",
}
TAB_BG = "#2a2a38"
TAB_BORDER = "#3a3a4a"
TAB_ACTIVE_BG = "#3a3a4a"

# ── Excluded game modes (no rating saved) ────────────────────────────────────
EXCLUDED_MODES = {
    "PRACTICETOOL", "TUTORIAL",
    "TUTORIAL_MODULE_1", "TUTORIAL_MODULE_2", "TUTORIAL_MODULE_3",
}

# ── Helpers ──────────────────────────────────────────────────────────────────
def strip_tags(text: str) -> str:
    """Remove [A],[/A],[E],[/E],[T],[/T] markup from text."""
    import re
    return re.sub(r'\[/?[AET]\]', '', text)
