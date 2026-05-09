#!/usr/bin/env python3
"""
One-shot extractor: splits web/js/main.js into 7 panel ES modules.
Run from C:\Riot Commander\  →  python tools/extract_panels.py
"""
import os

SRC = "web/js/main.js"
PANELS_DIR = "web/js/panels"

with open(SRC, encoding="utf-8") as f:
    raw = f.readlines()           # 0-indexed internally, 1-indexed in comments

def L(start, end, dedent=True):
    """Extract lines start..end (1-indexed, inclusive).
    If dedent=True, strip exactly 2 leading spaces (legacy IIFE indent)."""
    chunk = raw[start - 1 : end]
    if not dedent:
        return "".join(chunk)
    out = []
    for line in chunk:
        if line.startswith("  "):
            out.append(line[2:])
        else:
            out.append(line)
    return "".join(out)

os.makedirs(PANELS_DIR, exist_ok=True)

# ── 1. right_now.js ──────────────────────────────────────────────────────────
RIGHT_NOW_HEADER = """\
// Right Now panel — immediate coaching actions, game-sense, stats, digest.
import { el, safe, fmtList, classifyAction, isArenaPayload, logLine, _formatRelativeAge } from '../lib/helpers.js';
import { state } from '../lib/state.js';

"""
RIGHT_NOW_FOOTER = """
export { RN, renderRightNow, renderWhatWent, renderDigest, renderGameSense, renderStats };
"""

rn_dom     = L(37, 45)    # const RN = {…};  line 45 = closing };
rn_bind    = L(571, 595)  # RN.action copy-click one-time handler
rn_funcs   = L(598, 1066) # renderWhatWent … renderRightNow

with open(f"{PANELS_DIR}/right_now.js", "w", encoding="utf-8") as f:
    f.write(RIGHT_NOW_HEADER + rn_dom + "\n" + rn_bind + "\n" + rn_funcs + RIGHT_NOW_FOOTER)
print("✓ right_now.js")

# ── 2. next.js ───────────────────────────────────────────────────────────────
NEXT_HEADER = """\
// Next panel — wave state, objective row, arena partner info.
import { el, safe, isArenaPayload } from '../lib/helpers.js';
import { state } from '../lib/state.js';

"""
NEXT_FOOTER = """
export { NX, renderNext, arenaDetectPartner, arenaPartnerLine, arenaWaveLine };
"""

nx_dom       = L(46, 53)    # const NX = {…};  line 53 = closing };
nx_wave_cmt  = L(1068, 1078) # wave-state comment block
nx_wave_fns  = L(1079, 1245) # _classifyWavePct … renderNext
nx_arena     = L(1493, 1540) # CAITLYN_PARTNER_COMBOS + arena helpers

with open(f"{PANELS_DIR}/next.js", "w", encoding="utf-8") as f:
    f.write(NEXT_HEADER + nx_dom + "\n" + nx_wave_cmt + nx_wave_fns + "\n" + nx_arena + NEXT_FOOTER)
print("✓ next.js")

# ── 3. item_build.js ─────────────────────────────────────────────────────────
ITEM_BUILD_HEADER = """\
// Item Build panel — owned/recommended tiles, DS picks, in-game build switcher.
import { el, safe, fmtList, isArenaPayload } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, ITEM_COSTS, _resolveItemId, _splitItemList } from '../lib/items_index.js';

"""
ITEM_BUILD_FOOTER = """
export {
  IB,
  renderItemBuild, renderItemTiles, _updateItemBuildHeader,
  _ibPushItems, _ibMaybeRenderBuilds, _ibFetchAndRender,
  _ibSetStatus, _ibRenderRows, _ibMarkSelectedRow, _ibSaveChoice,
};
"""

ib_dom      = L(54, 64)     # const IB = {…};  line 64 = closing };
ib_funcs    = L(1247, 1491)  # _lastItemBuildState … renderItemBuild
ib_ib_funcs = L(3270, 3419)  # _ibSetStatus … _ibMaybeRenderBuilds (extracted from champ_select range)

with open(f"{PANELS_DIR}/item_build.js", "w", encoding="utf-8") as f:
    f.write(ITEM_BUILD_HEADER + ib_dom + "\n" + ib_funcs + "\n" + ib_ib_funcs + ITEM_BUILD_FOOTER)
print("✓ item_build.js")

# ── 4. map_state.js ──────────────────────────────────────────────────────────
MAP_STATE_HEADER = """\
// Map State panel — minimap canvas, team strips, game clock, spell CDs,
// gold diff, objective countdowns.
import { el, safe, fmtList, _formatRelativeAge } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { CHAMPS, SPELLS, _resolveChampId, _resolveSpell } from '../lib/items_index.js';

// State slots initialised here (map_state owns the clock + spell tracking).
state.gameClock = { startedAt: 0, anchorS: 0, raw: "" };
state.adaptCounterMap = {};
state.spellCds = {};

"""
MAP_STATE_FOOTER = """
export {
  MM,
  renderMinimap, renderTeamTile, renderAllyStrip, renderEnemyStrip,
  _tickSpellCooldowns, _tickObjectiveCountdowns,
  _updateGameClock, _applyGamePhase,
  _snapshotSpells, _fmtMMSS, _renderMmStateLine,
};
"""

mm_dom        = L(78, 91)    # const MM = {…};  line 91 = closing };
mm_funcs      = L(1546, 2377) # _updateGameClock … _renderMmStateLine
mm_spell_fns  = L(2644, 2675) # state.spellCds comment + _spellKey … _currentSpellCd

# Remove the state.gameClock / state.adaptCounterMap / state.spellCds init
# lines that are inline in the function blocks — they're lifted to the header.
# Lines 1545, 1606, 2647 in original. The extractor pulls them verbatim;
# having duplicate assignments is harmless (second wins, same value).
with open(f"{PANELS_DIR}/map_state.js", "w", encoding="utf-8") as f:
    f.write(MAP_STATE_HEADER + mm_dom + "\n" + mm_funcs + "\n" + mm_spell_fns + MAP_STATE_FOOTER)
print("✓ map_state.js")

# ── 5. champ_select.js ───────────────────────────────────────────────────────
CHAMP_SELECT_HEADER = """\
// Champ Select panel — interactive overlay during ChampSelect phase,
// SR draft build chooser, champ-select analyzer.
// _ib* functions live in item_build.js (avoid circular dep).
import { el, safe, fmtList, isArenaPayload } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, CHAMPS, _normItemName, _resolveItemId, _resolveChampId } from '../lib/items_index.js';
import {
  _ibPushItems, _ibFetchAndRender, _ibSetStatus,
  _ibRenderRows, _ibMarkSelectedRow, _ibSaveChoice,
} from './item_build.js';

"""
CHAMP_SELECT_FOOTER = """
export { handleChampSelect, renderChampSelectPanel, renderChampSelectCoach };
"""

# Section 1: lcuCmd … _csMarkSelectedRow (3067–3269), then skip _ib* (3270–3419),
#            then _csOnBuildRowClick … _csWireButtonsOnce (3420–4051)
# Section 2: renderChampSelectPanel … renderChampSelectCoach  (5816–6223)
cs_comment  = L(3067, 3071)   # block comment before lcuCmd
cs_funcs1a  = L(3072, 3269)   # lcuCmd … _csMarkSelectedRow (before _ib* block)
cs_funcs1b  = L(3420, 4051)   # _csOnBuildRowClick … _csWireButtonsOnce (after _ib* block)
cs_panel    = L(5816, 6223)   # renderChampSelectPanel, handleChampSelect, renderChampSelectCoach

# renderChampSelectCoach uses RN.action / RN.immediate — rewrite to el() to
# avoid importing RN from right_now.js (creates unnecessary cross-panel dep).
cs_panel_fixed = cs_panel.replace(
    "if (!RN.action || !RN.immediate) return;\n    const head = data.advice || \"(no advice)\";\n    RN.action.innerHTML = \"▶ \" + head;\n",
    "const _rnAction = el(\"rn-action\"), _rnImmediate = el(\"rn-immediate\");\n    if (!_rnAction || !_rnImmediate) return;\n    const head = data.advice || \"(no advice)\";\n    _rnAction.innerHTML = \"▶ \" + head;\n"
).replace(
    "RN.immediate.textContent = lines.join(\"  •  \");",
    "_rnImmediate.textContent = lines.join(\"  •  \");"
)

with open(f"{PANELS_DIR}/champ_select.js", "w", encoding="utf-8") as f:
    f.write(CHAMP_SELECT_HEADER + cs_comment + cs_funcs1a + cs_funcs1b + "\n" + cs_panel_fixed + CHAMP_SELECT_FOOTER)
print("✓ champ_select.js")

# ── 6. bridge_pending.js ─────────────────────────────────────────────────────
BRIDGE_PENDING_HEADER = """\
// Bridge Pending panel — coach decisions banner, recent coach calls log,
// bridge task pending display. setIntervals start at module load.
import { el, safe, _formatRelativeAge } from '../lib/helpers.js';
import { state } from '../lib/state.js';

"""
BRIDGE_PENDING_FOOTER = """
export { renderCoachDecisions, renderRecentCoachCalls, renderBridgePending };
"""

bp_funcs = L(6500, 6829)  # COACH_DECISIONS … pollBridgePending + setInterval

with open(f"{PANELS_DIR}/bridge_pending.js", "w", encoding="utf-8") as f:
    f.write(BRIDGE_PENDING_HEADER + bp_funcs + BRIDGE_PENDING_FOOTER)
print("✓ bridge_pending.js")

# ── 7. dev.js ────────────────────────────────────────────────────────────────
DEV_HEADER = """\
// Dev panel — settings, diagnostics, dev/sim fixture viewer, replay scrubber.
import { el, safe, fmtList, _to12, logLine } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, CHAMPS } from '../lib/items_index.js';

"""
DEV_FOOTER = """
export {
  _settingsRefresh,
  _diagFetchAndRender, _diagWireOnce,
  _devViewWireOnce, _devViewFetch,
  _replayViewWireOnce, _replayViewRefresh, _replayLoadMatch,
};
"""

dev_funcs = L(4499, 4944)  # _settingsRefresh … _replayViewWireOnce

with open(f"{PANELS_DIR}/dev.js", "w", encoding="utf-8") as f:
    f.write(DEV_HEADER + dev_funcs + DEV_FOOTER)
print("✓ dev.js")

# ── 8. main.js — generate import block addition ──────────────────────────────
# Print the 7 import lines to prepend after the existing lib imports.
PANEL_IMPORTS = """
// ── Panel modules ─────────────────────────────────────────────────────────
import { RN, renderRightNow, renderWhatWent, renderDigest, renderGameSense, renderStats } from './panels/right_now.js';
import { NX, renderNext, arenaDetectPartner, arenaPartnerLine, arenaWaveLine } from './panels/next.js';
import { IB, renderItemBuild, renderItemTiles, _updateItemBuildHeader, _ibPushItems, _ibMaybeRenderBuilds, _ibFetchAndRender, _ibSetStatus, _ibRenderRows, _ibMarkSelectedRow, _ibSaveChoice } from './panels/item_build.js';
import { MM, renderMinimap, renderTeamTile, renderAllyStrip, renderEnemyStrip, _tickSpellCooldowns, _tickObjectiveCountdowns, _updateGameClock, _applyGamePhase, _snapshotSpells, _fmtMMSS, _renderMmStateLine } from './panels/map_state.js';
import { handleChampSelect, renderChampSelectPanel, renderChampSelectCoach } from './panels/champ_select.js';
import { renderBridgePending, renderCoachDecisions, renderRecentCoachCalls } from './panels/bridge_pending.js';
import { _settingsRefresh, _diagFetchAndRender, _diagWireOnce, _devViewWireOnce, _devViewFetch, _replayViewWireOnce, _replayViewRefresh, _replayLoadMatch } from './panels/dev.js';
"""

print("\nAll 7 panel files written to", PANELS_DIR)

# ── 9. Generate new main.js ─────────────────────────────────────────────────
# Ranges to REMOVE from main.js (1-indexed, inclusive).
# Order matters: must be non-overlapping. Listed in ascending order.
REMOVE_RANGES = [
    (36, 53),    # "// Panels" comment + RN + NX
    (54, 64),    # IB
    (78, 91),    # MM
    (571, 595),  # RN.action copy-click handler (moved to right_now.js)
    (598, 1066), # right_now panel functions
    (1068, 1245),# next panel functions
    (1247, 1491),# item_build panel functions
    (1493, 1540),# arena helpers (now in next.js)
    (1541, 1545),# gameClock comment + state.gameClock init (now in map_state.js header)
    (1546, 2377),# map_state panel functions
    (2644, 2675),# spell key functions (now in map_state.js)
    (3067, 4051),# champ_select panel functions section 1
    (4499, 4944),# dev panel functions
    (5816, 6223),# champ_select panel functions section 2
    (6500, 6829),# bridge_pending panel functions
]

removed = set()
for s, e in REMOVE_RANGES:
    for i in range(s, e+1):
        removed.add(i)

# Build new main.js:
# - Insert panel imports after the last lib import (line 19)
# - Skip all lines in removed set
new_lines = []
for i, line in enumerate(raw, 1):
    if i == 19:
        new_lines.append(line)   # keep the last lib import
        new_lines.append(PANEL_IMPORTS)
        continue
    if i in removed:
        continue
    new_lines.append(line)

new_main = "".join(new_lines)

# Backup original
import shutil
shutil.copy(SRC, SRC + ".bak")
with open(SRC, "w", encoding="utf-8") as f:
    f.write(new_main)

orig_lines = len(raw)
new_line_count = new_main.count("\n") + 1
print(f"✓ main.js: {orig_lines} → {new_line_count} lines ({orig_lines - new_line_count} removed)")
print(f"  Backup: {SRC}.bak")
