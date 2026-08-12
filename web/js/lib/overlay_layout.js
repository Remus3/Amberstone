// web/js/lib/overlay_layout.js
//
// RC Overlay Doctrine (docs/OVERLAY_DOCTRINE.md section 2-4) - the movable,
// position-PERSISTENT widget field. Replaces the old monolithic 460px right-edge
// dock: each in-game cue is an independently absolute-positioned widget the
// operator drags to where their eye rests, and the (x,y) is saved + reloaded so
// it never moves on its own again (rule 9: fixed/learnable beats smart/moving).
//
// Self-gates on body[data-shell="overlay"] - a no-op on the 1920 dashboard
// (retired as a user surface, but it still renders for headless audits, so this
// must not touch it). The CSS (.ovx-widget in overlay.css) owns position:fixed +
// the Hextech shell; this module owns ONLY the dynamic left/top + the drag +
// the persistence, so the look and the layout logic never drift.
//
// Drag is grabbed by a small handle marked data-rc-zone so the rc-shell
// click-through machine (clickthrough_zones.js) makes JUST the handle
// interactive while the widget body stays click-through during play; in a plain
// browser (no rc-shell bridge) everything is clickable, so drag still works for
// preview / headless audit captures.
//
// Persistence: localStorage["rc-overlay-layout"] = { <id>: {x,y,hidden,scale} }.
// When the rc-shell bridge exposes setWidgetLayout/getWidgetLayout the layout is
// ALSO mirrored to the shell's on-disk state (durable across a localStorage
// wipe + hand-editable); absent the bridge it degrades to localStorage-only,
// which already survives a reload since the overlay shares the dashboard origin.

const LS_KEY = "rc-overlay-layout";

// Widget registry: id -> mount selector + default 1080p (x,y) + tier. Defaults
// push urgent cues toward the eye (minimap / champion HUD / combat center) per
// OVERLAY_DOCTRINE section 4. (x,y) is the widget top-left in 1920x1080 game px;
// the body zoom (--rc-overlay-scale / ovscale) scales them with the window.
const WIDGETS = [
  // Default 1080p positions = the EYE-LINE ANCHORS (OVERLAY_DOCTRINE section 4).
  // Operator chose near-the-eye over the old left-edge column (2026-06-22): each
  // cue defaults to where the eye already rests rather than a tidy out-of-play
  // gutter, so the most time-critical call is not in the corner furthest from the
  // combat center-of-mass (rule 9). Placement map: the CALL sits upper-center
  // above combat; the A/B choices sit lower-center above the ability bar; the
  // objective/spike callouts sit at the minimap; the macro-lead pill sits under
  // the top score bar; the spike cue sits bottom-left by the champion stats; the
  // trinket glyph sits by the avatar. Drag still OVERRIDES + PERSISTS per widget
  // (rule 9), and Alt+Shift+R resets the field to THESE defaults (section 3).
  // (x,y) is design-px in 1920x1080; the fullscreen window's body zoom scales them
  // with the resolution.
  // Operator 2026-06-27 nudge: CALL (760,140 -> 180,130) + the WARD/trinket glyph
  // (920,540 -> 340,600) moved OFF the center combat column - they were rendering
  // over the champion / top play lane in-game. The rest keep the near-eye anchors;
  // drag still overrides per-widget (Ctrl+Shift+A then drag; Alt+Shift+R resets).
  { id: "w-lead", sel: "#rn-lead", x: 786, y: 44, tier: "ambient", label: "Macro Lead" },
  { id: "w-call", sel: "#view-active-match .am-pane-call", x: 180, y: 130, tier: "primary", label: "Coach Call" },
  { id: "w-choices", sel: "#rn-choices", x: 760, y: 815, tier: "urgent", label: "A/B Choices" },
  { id: "w-callouts", sel: "#rn-callouts", x: 1486, y: 780, tier: "ambient", label: "Callouts" },
  // w-threat (Threat / CDs, .am-pane-cd) removed 2026-07-05 (operator): the enemy
  // CD ledger guessed at cooldowns the Live Client API does not expose - not needed.
  { id: "w-build", sel: "#view-active-match .am-pane-build", x: 70, y: 470, tier: "ambient", label: "Build", tall: true },
  // 2026-07-27 collision sweep (see the registry recheck note below): 430 put
  // this 210px column 52px UNDER w-build's 412px box (right edge 482) for 537px
  // of height, which truncated build text in-game. 490 clears that edge by 8px
  // and is still left of the centre combat column.
  { id: "w-ovds", sel: "#am-pane-ovds", x: 490, y: 80, tier: "ambient", label: "DS Controls" },
  // New doctrine cue (OVERLAY_DOCTRINE section 4). Data-gated (its renderer
  // un-hides the mount only when actionable) + coach-core. Mounted as a direct
  // am-grid child (NOT inside a pane) so position:fixed is viewport-relative, not
  // trapped by a transformed pane. (w-trinket / Ward Cue removed 2026-07-05: it
  // could not turn off on ward cooldown - Live Client exposes no cooldowns.)
  // 2026-07-27 collision sweep: (360,840) sat INSIDE w-build's box (70..482 x,
  // 470..1064 y - a populated build module fills its whole 594px cap), so the
  // glyph landed on top of the build rows. The bottom-left is w-build's for as
  // long as w-build anchors there, so the cue moves to the free strip between
  // the ability bar and the minimap - still low + near the eye, still out of
  // the champion / ability-bar lane.
  // Operator 2026-06-28: the enemy summoner-spell tap-tracker (zone -> tappable
  // mid-game) + the API-backed HP/mana/stats mini-panel. Both overlay-only.
  // 2026-07-27 collision sweep: (1500,120) ran its 280x~210 box into the ARAM
  // balance grid's top edge (y 290) and into w-objgauges. Moving it up + left
  // keeps the upper-right urgent anchor while clearing both.
  // 2026-07-27 collision sweep: (40,250) is unusable. The 240px-wide panel
  // cannot clear w-call (180..390 x) on either side inside the 482px left
  // gutter, and its bottom ran into w-build. The peripheral upper-right edge is
  // the only slot that fits 240x240 without entering the combat column or the
  // minimap (top ~y 720).
  { id: "w-stats", sel: "#am-statspanel", x: 1670, y: 220, tier: "ambient", label: "Stats" },
  // OQ16 (OQ3 variant A): peripheral objective gauge cluster (DRAKE/BARON/
  // ELDER ring dials, panels/objective_gauges.js). Display-only + data-gated
  // (SR in-game only); peripheral right-edge default, clear of the minimap
  // (1600,760). (The SUMMS dial was removed 2026-07-05: no Live Client CD data.)
  // 2026-07-27 collision sweep: x 1690 + the 288px widen-to-fit width put the
  // right edge at 1978, i.e. 58px OFF a 1920 screen (the 3rd dial was clipped
  // by the viewport, not by the widget). 1632 lands the edge exactly on 1920.
  // y 400 -> 90 as well: a 288px-wide box cannot sit RIGHT of the ARAM grid
  // (1670 + 288 > 1920), so it clears that grid by staying ABOVE its y 290 top
  // instead. Still the peripheral right edge, still well clear of the minimap.
  { id: "w-objgauges", sel: "#am-obj-gauges", x: 1632, y: 90, tier: "ambient", label: "Objective Gauges" },
  // NEXT BUY rule lines (panels/next_buy.js): gold-to-next-DS-item + the free
  // trinket upgrade. Display-only + data-gated (a live game with a build path).
  // 2026-07-27 collision sweep: "low-left under the Stats panel" put its
  // 260x~90 box squarely inside w-build (70..482 x, 470..1064 y), so a
  // populated build module rendered straight through it. Moved to the free
  // low-centre-right strip, which is the side the in-game gold / shop readout
  // actually lives on and is above the ability bar.
  { id: "w-nextbuy", sel: "#am-next-buy", x: 1010, y: 790, tier: "ambient", label: "Next Buy" },
  // ARAM balance grid (panels/aram_balance.js). Promoted OUT of the BUILD pane
  // to its own widget 2026-07-20 (operator): once the champion-resolution fix
  // made it actually populate, its ~11 rows pushed META BUILD / the DS item row
  // into a scroll region inside .am-pane-build and clipped them in-game. It is
  // glanceable REFERENCE data, not read line-by-line beside the build order, so
  // it earns its own freely-positionable surface. tier "ambient" (never urgent).
  // Self-gates to ARAM in its own renderer (renderAramBalance hides the mount
  // outside _AB_ARAM_MODES), so it occupies nothing in SR / Arena.
  //
  // Default anchor: right-of-center playfield. --ovx-w is 620 (overlay.css - a
  // 3-chip row needs ~615px or the chips wrap and DOUBLE the height of all 11
  // rows), and the populated grid MEASURES 436px tall at 10 rows (headless
  // overlay probe), so budget ~480 for a full 11-row ARAM lobby: the box is
  // x 1050..1670, y 290..~770. Drag still overrides + persists.
  //
  // REGISTRY RECHECK 2026-07-27. The claim that used to sit here - that this
  // anchor was "deliberately checked against EVERY other default" - was only
  // ever true one way round: the OTHERS were checked against w-arambalance, and
  // no default was ever checked against the rest of the left-side cluster.
  // A headless 1920x1080 render measured w-build (x 70, --ovx-w 412 -> right
  // edge 482, and a populated build module fills its whole 594px --ovx-maxh cap
  // so the box is y 470..1064) sitting 52px UNDER w-ovds for 537px of height,
  // truncating build text in-game. The same sweep found four more:
  // w-nextbuy + w-spike were both anchored INSIDE w-build's box, w-stats could
  // not clear w-call in the 482px left gutter, and w-enemyspells clipped the
  // ARAM grid's top edge. w-objgauges was also 58px off the right of a 1920
  // screen (1690 + 288). Six defaults moved; the eye-line tiers are unchanged.
  // tests/test_overlay_default_layout_collision.py is now the machine version
  // of the promise this comment used to make by hand - it crosses this array
  // with the overlay.css --ovx-w map and fails on ANY overlapping or
  // off-screen default pair, so the claim cannot rot again. The one exempt
  // pair is w-arambalance vs w-objgauges (ARAM-only vs SR-only, so they can
  // never paint together).
  { id: "w-arambalance", sel: "#aram-balance-panel", x: 1050, y: 290, tier: "ambient", label: "ARAM Balance" },
];

// The launcher is a CONTROL widget, not a panel: a small always-visible square
// (HUD summoner-spell sized) the operator drags anywhere and taps (in ACTIVE) to
// open the layout control center - per-panel show/hide + reset + panel-set. It is
// the in-game escape hatch back to a panel that was right-click-hidden: the only
// other un-hide path (Alt+Shift+R resetOverlayLayout) is Electron-globalShortcut-
// only and so dead while League holds foreground focus. Deliberately NOT in
// WIDGETS - it is never itself hideable and never appears in its own panel list.
// Its position rides the same _layout mirror under its own id; a reset clears that
// entry, so it returns to the default corner (and stays visible) like every panel.
const LAUNCHER = { id: "w-launcher", sel: "#w-launcher", x: 24, y: 24, tier: "control", label: "Overlay menu" };

// Panel sets the menu can switch to (mirror of rc-shell overlay_state PANEL_SETS;
// the shell's normOverlayAction re-validates, so this list is only the UI source).
const PANEL_SETS = ["coach", "build", "threat"];

// Widgets that anchor by their BOTTOM (growing upward) when dropped in the lower
// half - only the tall content panels that would otherwise shrink against the
// maxh floor or overflow when top-anchored near the screen bottom (operator
// 2026-06-29: BUILD). Every OTHER widget is free-placed exactly where dropped, so
// dragging one near the bottom-right minimap no longer flings it to the bottom
// corner. See _applyPos.
const TALL_IDS = new Set(WIDGETS.filter((w) => w.tall).map((w) => w.id));

// Keep at least this many design-px of a widget's top-left corner (where the drag
// handle lives) on-screen so a drag - or a stale saved position - can NEVER strand
// a panel off-screen / fully behind the minimap with no grabbable handle (operator
// 2026-06-29: "un-retrievable" panels). Pure; clamps the stored (x,y) before it is
// applied or persisted.
const MIN_VISIBLE = 48;
function _clampXY(x, y, W, H, minVis = MIN_VISIBLE) {
  const nx = Number.isFinite(x) ? x : 0;
  const ny = Number.isFinite(y) ? y : 0;
  return {
    x: Math.min(Math.max(nx, 0), Math.max(0, W - minVis)),
    y: Math.min(Math.max(ny, 0), Math.max(0, H - minVis)),
  };
}

// A per-panel `zoom: var(--ovx-scale)` (overlay.css) scales a FIXED element's
// top/left/bottom by the scale as well as its size (empirically verified: a
// zoom:0.5 fixed element with top:500 renders at viewport 250). So a scaled-down
// panel's applied position collapses toward the top-left and the operator can no
// longer drag it to the screen bottom - the draggable "floor" appears to shift
// up with scale (operator 2026-07-11). Dividing the design-px position by the
// panel scale cancels the zoom so the panel lands where dropped at ANY scale;
// size (width / --ovx-maxh) is intentionally left to zoom so the panel shrinks.
// _scalePos(v, 1) returns v unchanged, so every unscaled panel is untouched.
function _scalePos(v, scale) {
  const s = Number.isFinite(scale) && scale > 0 ? scale : 1;
  return s === 1 ? v : v / s;
}

// Where a widget actually PAINTS for a given stored (x,y) - the same decision
// _applyPos makes: clamp on-screen, and bottom-anchor a tall widget dropped in
// the lower half (top = H - 16 - rendered height). Pure so it is unit-testable.
// The drag used to anchor at the RAW stored (x,y); whenever that differed from
// the render (stale off-field save, or the tall bottom-anchor) the first move
// tick teleported the panel away from the cursor or dead-zoned the drag until
// the cursor crossed the gap (RM-05 round-2 symptom a).
function _effectiveXY(id, x, y, W, H, hDesign) {
  const c = _clampXY(x, y, W, H);
  const ny = Number.isFinite(y) ? y : 0;
  if (TALL_IDS.has(id) && ny > H * 0.5 && Number.isFinite(hDesign) && hDesign > 0) {
    return { x: c.x, y: _clampXY(0, H - 16 - hDesign, W, H).y };
  }
  return c;
}

let _layout = {};
let _saveTimer = 0;

function _readLayout() {
  try {
    const o = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    return o && typeof o === "object" ? o : {};
  } catch (_e) {
    return {};
  }
}

function _persist() {
  // Debounced write: a drag fires many pointermove ticks; only the settled
  // position needs to hit storage. localStorage is synchronous + origin-shared.
  if (_saveTimer) clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(_layout));
    } catch (_e) {
      // best-effort; a full / disabled storage must not break dragging.
    }
    try {
      if (window.rcShell && typeof window.rcShell.setWidgetLayout === "function") {
        Promise.resolve(window.rcShell.setWidgetLayout(_layout)).catch(() => {});
      }
    } catch (_e) {
      // no bridge (plain browser) - localStorage already holds the value.
    }
  }, 400);
}

function _posFor(w) {
  const saved = _layout[w.id] || {};
  return {
    x: Number.isFinite(saved.x) ? saved.x : w.x,
    y: Number.isFinite(saved.y) ? saved.y : w.y,
    hidden: saved.hidden === true,
    scale: Number.isFinite(saved.scale) ? saved.scale : 1,
    // Per-panel opacity (operator 2026-06-28): a 0.3-1.0 multiplier so each cue
    // can recede independently of the global window opacity. Absent -> 1 (opaque).
    opacity: Number.isFinite(saved.opacity) ? saved.opacity : 1,
  };
}

function _applyPos(el, p) {
  // CSS owns position:fixed; this sets only the dynamic values.
  // design-px viewport box (the field is design-px; the body zoom is ovscale).
  const z = _bodyZoom() || 1;
  const H = (window.innerHeight / z) || 1080;
  const W = (window.innerWidth / z) || 1920;
  // Bottom-corner anchoring (operator 2026-06-29): a content-TALL panel (BUILD)
  // positioned by its TOP near the screen bottom either shrinks against the maxh
  // floor (140px) or overflows off-screen - so it could not sit in the bottom-left
  // corner ("keeps auto shrinking"). For a TALL widget dropped in the LOWER half,
  // anchor it by its BOTTOM (16px margin) so it grows UPWARD at full height; cap
  // maxh to the room from the top margin to that anchor. Every OTHER widget is
  // free-placed exactly where dropped (operator 2026-06-29: the snap-everything
  // rule flung panels to the bottom when dragged near the minimap). Either way the
  // (x,y) is clamped on-screen so the panel stays grabbable. The drag handler
  // clears `bottom` while moving and re-applies this on drop. Recomputed on resize.
  const isTall = TALL_IDS.has(el.dataset && el.dataset.ovxId);
  if (isTall && p.y > H * 0.5) {
    el.style.left = _scalePos(_clampXY(p.x, 0, W, H).x, p.scale) + "px";
    el.style.top = "auto";
    el.style.bottom = _scalePos(16, p.scale) + "px";
    el.style.setProperty("--ovx-maxh", Math.max(140, Math.round(H - 32)) + "px");
  } else {
    const c = _clampXY(p.x, p.y, W, H);
    el.style.left = _scalePos(c.x, p.scale) + "px";
    el.style.bottom = "auto";
    el.style.top = _scalePos(c.y, p.scale) + "px";
    const availH = H - c.y - 16;
    el.style.setProperty("--ovx-maxh", Math.max(140, Math.round(availH)) + "px");
  }
  if (p.scale && p.scale !== 1) {
    el.style.setProperty("--ovx-scale", String(p.scale));
  } else {
    el.style.removeProperty("--ovx-scale");
  }
  // Per-panel opacity is an inline style (composes with the Electron window-level
  // global opacity); only set it when dimmed so the default stays clean.
  if (Number.isFinite(p.opacity) && p.opacity < 1) {
    el.style.opacity = String(p.opacity);
  } else {
    el.style.opacity = ""; // standard prop - clearing the string removes it
  }
  el.classList.toggle("ovx-hidden", p.hidden);
}

function _bodyZoom() {
  const z = parseFloat(getComputedStyle(document.body).zoom);
  return Number.isFinite(z) && z > 0 ? z : 1;
}

// ACTIVE-mode signal (doctrine section 2/3): the rc-shell main process lights
// the overlay ACTIVE (Alt+Shift+A) by adding the "rc-shell-active" class to
// <html> (rc-shell/src/active_indicator.js activeIndicatorSetJS). That class is
// present in the page DOM EXACTLY while the overlay is interactive, so it is the
// authoritative page-side ACTIVE check - the same gate the drag affordance lives
// behind (the drag handle is only grabbable when click-through is off / ACTIVE).
// PASSIVE (click-through) => the class is absent => this returns false and the
// hide menu stays a pure no-op so right-clicks pass through to the game.
function _isActiveMode() {
  try {
    return document.documentElement.classList.contains("rc-shell-active");
  } catch (_e) {
    return false; // headless / locked-down document: treat as PASSIVE (safe).
  }
}

// Per-widget HIDE affordance (doctrine section 2: "A widget the operator never
// wants is hidden via a per-widget toggle"; section 3: "A per-widget reset is
// the right-click affordance in ACTIVE mode"). Sets hidden:true on this widget's
// layout entry, persists via the EXISTING mirror, and applies the hide through
// the SAME read-side path (_applyPos toggles .ovx-hidden). hidden != deleted -
// the mount + its wiring stay; the field just stops painting it. Restored by the
// existing Alt+Shift+R resetOverlayLayout (clears _layout -> hidden:false again).
function _hideWidget(el, w) {
  _layout[w.id] = { ...(_layout[w.id] || {}), hidden: true };
  _applyPos(el, _posFor(w));
  _persist();
}

// Bidirectional show/hide for the launcher menu's per-panel toggles. _hideWidget
// only sets hidden:true (the right-click affordance); the menu must also bring a
// panel BACK - the whole reason the launcher exists. Same read-side path
// (_applyPos -> .ovx-hidden) and same persistence (mirror) as every other layout
// mutation. The mount is looked up fresh (the menu has no el in hand).
function _setHidden(w, hidden) {
  _layout[w.id] = { ...(_layout[w.id] || {}), hidden: !!hidden };
  const el = document.querySelector(w.sel);
  if (el) _applyPos(el, _posFor(w));
  _persist();
}

// Toggle one panel's visibility; returns the new hidden state (for the menu row).
function _toggleHidden(w) {
  const next = !_posFor(w).hidden;
  _setHidden(w, next);
  return next;
}

// Per-panel opacity (0.3-1.0) + scale (0.5-1.6) setters for the menu sliders.
// Same read-side path (_applyPos) + persistence (mirror) as hide/position.
function _clampNum(v, lo, hi, dflt) {
  const n = Number(v);
  if (!Number.isFinite(n)) return dflt;
  return Math.max(lo, Math.min(hi, n));
}
function _setOpacity(w, value) {
  _layout[w.id] = { ...(_layout[w.id] || {}), opacity: _clampNum(value, 0.3, 1, 1) };
  const el = document.querySelector(w.sel);
  if (el) _applyPos(el, _posFor(w));
  _persist();
}
function _setScale(w, value) {
  _layout[w.id] = { ...(_layout[w.id] || {}), scale: _clampNum(value, 0.5, 1.6, 1) };
  const el = document.querySelector(w.sel);
  if (el) _applyPos(el, _posFor(w));
  _persist();
}

// Fire an overlay action through the rc-shell bridge (set-panel / set-active).
// Degrades to a no-op in a plain browser (no bridge); returns whether it fired.
// best-effort: a missing/locked bridge must never throw into a click handler.
function _shellAction(msg) {
  try {
    if (window.rcShell && typeof window.rcShell.overlayAction === "function") {
      window.rcShell.overlayAction(msg);
      return true;
    }
  } catch (_e) {
    // swallow: the click is a convenience, never a crash surface.
  }
  return false;
}

// Right-click hide, mirroring _installDrag's structure. STRICTLY gated on ACTIVE:
// in PASSIVE mode the handler does NOTHING - no preventDefault, no capture - so
// the contextmenu event is never consumed and never blocks/leaks to the game
// underneath the click-through overlay (doctrine: never require a mid-fight
// dismissal, never obstruct). Only in ACTIVE does it preventDefault + hide.
function _installHideMenu(el, w) {
  el.addEventListener("contextmenu", (e) => {
    if (!_isActiveMode()) return; // PASSIVE: pure no-op, let it fall through.
    e.preventDefault();
    _hideWidget(el, w);
  });
}

// Guarded window-level listener helpers. The drag attaches its move/up
// tracking to `window` for the drag's duration (see _installDrag); a headless
// or locked-down host without add/removeEventListener must degrade to the
// el-level listeners instead of throwing out of a pointer handler.
function _winOn(type, fn) {
  try {
    if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
      window.addEventListener(type, fn);
    }
  } catch (_e) {
    // el-level listeners still track; window tracking is the robustness layer.
  }
}
function _winOff(type, fn) {
  try {
    if (typeof window !== "undefined" && typeof window.removeEventListener === "function") {
      window.removeEventListener(type, fn);
    }
  } catch (_e) {
    // already gone / locked down; harmless.
  }
}

// Drag core. Returns a `begin(e)` starter the caller wires to whichever element
// should grab the drag: the small handle (always - the passive quick-drag via
// data-rc-zone) AND, in ACTIVE mode, the whole widget body (operator 2026-06-27:
// "in ACTIVE I expect to drag the panel, not hunt a 3px grip"). Capture is set
// on `el`, and move/up listeners live on `el` AND (mid-drag only) on `window`:
// panel renderers rebuild these mounts (replaceWith / innerHTML), and a mount
// swap mid-drag used to orphan the el-only listeners and silently kill the drag
// - the same death the operator hit whenever capture failed and the cursor left
// the 3px handle (RM-05 round-2 symptom b).
function _installDrag(el, w) {
  // One drag closure per mount, forever (RM-126). _placeAll re-runs _makeHandle
  // on the SAME persistent el after every renderer rebuild, so an unguarded
  // re-entry stacked another el-level move/up/cancel set per repaint. Reusing
  // the stored `begin` is what makes that safe: the listeners below close over
  // THIS call's drag state, so handing a later caller a fresh closure would
  // leave the surviving listeners reading state nobody writes.
  if (el._ovxDragBegin) return el._ovxDragBegin;
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let originX = 0;
  let originY = 0;
  let scale = 1;  // panel zoom, captured at drag start (item 9 - see _scalePos)
  let hadZone = false; // el's own [data-rc-zone] state, restored on drop

  // The mount can be swapped by its renderer mid-drag; style writes must land
  // on the node that is actually painting, not the orphaned one we wired.
  const _liveEl = () => {
    try {
      if (el.isConnected === false && typeof document !== "undefined" && document.querySelector) {
        return document.querySelector(w.sel) || el;
      }
    } catch (_e) {
      // stub / locked-down document: the wired node is all there is.
    }
    return el;
  };

  const onMove = (e) => {
    if (!dragging) return;
    // clientX/Y are screen px; the stored (x,y) are design px, so divide the
    // delta by the body zoom to keep 1:1 cursor tracking at any ovscale.
    const z = _bodyZoom();
    const H = (window.innerHeight / (z || 1)) || 1080;
    const W = (window.innerWidth / (z || 1)) || 1920;
    // Clamp so the top-left (drag handle) can never leave the screen mid-drag -
    // guarantees the panel stays retrievable (operator 2026-06-29).
    const c = _clampXY(
      Math.round(originX + (e.clientX - startX) / z),
      Math.round(originY + (e.clientY - startY) / z),
      W, H);
    _layout[w.id] = { ...(_layout[w.id] || {}), x: c.x, y: c.y };
    const node = _liveEl();
    node.style.left = _scalePos(c.x, scale) + "px";
    // Track by TOP while moving (clear any bottom-anchor from a prior drop) so the
    // panel follows the cursor 1:1; _applyPos on drop re-decides top vs bottom.
    // Divide by the panel scale: `zoom` scales top/left too (item 9), so an
    // uncompensated set would drift a scaled panel off the cursor.
    node.style.bottom = "auto";
    node.style.top = _scalePos(c.y, scale) + "px";
  };

  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    el.classList.remove("ovx-dragging");
    // Drop the temporary zone mark unless the widget is a zone in its own
    // right (w-enemyspells) - stripping that would kill its tap-to-interact.
    try {
      if (!hadZone && typeof el.removeAttribute === "function") {
        el.removeAttribute("data-rc-zone");
      }
    } catch (_e) {
      // locked-down node; the mark dies with it.
    }
    _winOff("pointermove", onMove);
    _winOff("pointerup", end);
    _winOff("pointercancel", end);
    try {
      el.releasePointerCapture(e.pointerId);
    } catch (_e) {
      // already released; harmless.
    }
    // Re-apply so a drop into the lower half snaps to the bottom-corner anchor
    // immediately (not only on the next load/resize).
    _applyPos(_liveEl(), _posFor(w));
    _persist();
  };

  const begin = (e) => {
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    const p = _posFor(w);
    scale = Number.isFinite(p.scale) && p.scale > 0 ? p.scale : 1;
    // Anchor at the RENDERED position (clamp + tall bottom-anchor), never the
    // raw stored (x,y) - see _effectiveXY (RM-05 round-2 symptom a).
    const z = _bodyZoom() || 1;
    const W = (window.innerWidth / z) || 1920;
    const H = (window.innerHeight / z) || 1080;
    const oh = el.offsetHeight;
    const eff = _effectiveXY(w.id, p.x, p.y, W, H,
      Number.isFinite(oh) && oh > 0 ? oh * scale : NaN);
    originX = eff.x;
    originY = eff.y;
    el.classList.add("ovx-dragging");
    // The rc-shell zone machine (clickthrough_zones.js) hit-tests e.target per
    // pointermove; once capture retargets moves to `el`, the handle's own
    // [data-rc-zone] no longer matches and the shell flipped the window back to
    // click-through MID-DRAG, killing it (RM-05 round-2 symptom b). Marking el
    // itself a zone for the drag's duration keeps the window interactive via
    // the zone machine's generic [data-rc-zone] opt-in hook.
    try {
      hadZone = typeof el.hasAttribute === "function" && el.hasAttribute("data-rc-zone");
      if (!hadZone && typeof el.setAttribute === "function") {
        el.setAttribute("data-rc-zone", "");
      }
    } catch (_e) {
      hadZone = false;
    }
    try {
      el.setPointerCapture(e.pointerId);
    } catch (_e) {
      // setPointerCapture can throw if the pointer is gone; harmless.
    }
    _winOn("pointermove", onMove);
    _winOn("pointerup", end);
    _winOn("pointercancel", end);
    e.preventDefault();
  };

  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el._ovxDragBegin = begin;
  return begin;
}

// Clickable controls inside a widget that must NOT start a body drag in ACTIVE
// mode - a press on these should still actuate the control (and the handle has
// its own grab). Everything else in the body becomes a drag surface in ACTIVE.
const _NO_BODY_DRAG =
  ".ovx-handle, button, input, select, textarea, a, [contenteditable], " +
  "#ovset, #rn-choices, #am-pane-ovds, [data-rc-zone]";

function _makeHandle(el, w) {
  if (el.querySelector(":scope > .ovx-handle")) return;
  const h = document.createElement("div");
  h.className = "ovx-handle";
  // data-rc-zone: the rc-shell click-through machine makes this grabbable in
  // PASSIVE mode without the global ACTIVE toggle - a deliberate small target so
  // the body stays click-through during play (no accidental drags mid-fight).
  h.setAttribute("data-rc-zone", "");
  h.title = "drag to move (saves automatically); right-click to hide (ACTIVE)";
  h.innerHTML = "<span></span><span></span><span></span>";
  el.appendChild(h);
  const begin = _installDrag(el, w);
  // Handle: always grabbable (the passive quick-drag target).
  h.addEventListener("pointerdown", begin);
  // The body bind needs its OWN latch (RM-126). The guard at the top only sees
  // the handle CHILD, which a renderer rebuild drops - so this el-level bind
  // re-ran on the surviving el every repaint. Same dataset idiom as
  // _makeHideMenu: a fresh mount carries no flag and wires normally.
  if (el.dataset.ovxBodyDrag === "1") return;
  el.dataset.ovxBodyDrag = "1";
  // Body: grabbable ONLY in ACTIVE mode, and never on an interactive control or
  // the handle (operator 2026-06-27: once you have explicitly entered ACTIVE,
  // drag the whole panel instead of hunting the small grip).
  el.addEventListener("pointerdown", (e) => {
    if (!_isActiveMode()) return;
    const t = e.target;
    if (!t) return;
    // Border/chrome presses target el ITSELF (content presses target a child).
    // A press on a panel's edge ring was starting a drag of whatever container
    // heard it - widgets overlap freely, so the operator got "the whole region"
    // instead of the intended widget (RM-05 round-2 symptom c). Edge presses
    // are handle-only; content presses keep the 2026-06-27 body-drag.
    if (t === el) return;
    if (t.closest) {
      if (t.closest(_NO_BODY_DRAG)) return;
      // A press whose nearest widget is NOT this el belongs to a nested /
      // overlapping widget - its own wiring must win, never this container.
      const hitWidget = t.closest(".ovx-widget");
      if (hitWidget && hitWidget !== el) return;
    }
    begin(e);
  });
}

// Attach the right-click hide listener once per mount. Idempotent: a dataset
// flag survives re-renders that keep the same node, and _placeAll re-runs the
// whole pass after a renderer rebuilds a mount (a fresh node has no flag, so the
// listener re-attaches). Mirrors _makeHandle's double-attach guard.
function _makeHideMenu(el, w) {
  if (el.dataset.ovxHideMenu === "1") return;
  el.dataset.ovxHideMenu = "1";
  _installHideMenu(el, w);
}

// Reveal the field once the first full place pass has run. The CSS keeps every
// .ovx-widget visibility:hidden until <body>.ovx-ready, so the lazily-created
// full-screen overlay window never flashes the widgets at their pre-layout "max
// size" before _placeAll positions + scales them (the first-match flash). Set
// once; subsequent re-render passes (_placeAll via the observer) are no-ops here.
function _markFieldReady() {
  try {
    document.body.classList.add("ovx-ready");
  } catch (_e) {
    // headless / locked-down document: the field still positions; nothing to reveal.
  }
}

function _placeAll() {
  for (const w of WIDGETS) {
    const el = document.querySelector(w.sel);
    if (!el) continue;
    el.classList.add("ovx-widget");
    el.dataset.ovxId = w.id;
    el.dataset.ovxTier = w.tier;
    // Zone widgets (operator 2026-06-28: the spell/CD panel) are interactive while
    // playing - mark them [data-rc-zone] so the rc-shell makes the window
    // interactive on hover in PASSIVE, no ACTIVE toggle needed. (A/B/C #rn-choices
    // is already a static zone in clickthrough_zones.js.)
    if (w.zone) el.setAttribute("data-rc-zone", "");
    _applyPos(el, _posFor(w));
    _makeHandle(el, w);
    _makeHideMenu(el, w);
  }
}

// --- Launcher control widget + layout control center -------------------------
// The launcher is a small square (HUD summoner-spell sized) that is ALWAYS
// present and a click-through ZONE (data-rc-zone) - the rc-shell makes the window
// interactive on hover, so it is usable mid-game in PASSIVE without the ACTIVE
// toggle (operator 2026-06-28). Tap it to open the menu; drag it (movement past a
// small threshold) to reposition. Off the square, clicks fall through to the game.
let _menuEl = null;

// Drag-vs-tap on the launcher: a press that does not move past THRESH px is a TAP
// (open/close the menu); a press that does is a DRAG (reposition + persist). We
// cannot reuse _installDrag (it treats every pointerdown as a drag) because the
// launcher must distinguish the two from a single press.
function _installLauncher(el, w, onTap) {
  const THRESH = 4;
  let down = false;
  let moved = false;
  let startX = 0;
  let startY = 0;
  let originX = 0;
  let originY = 0;
  let lscale = 1; // launcher zoom at press time - same item-9 law as _installDrag
  el.addEventListener("pointerdown", (e) => {
    // The OP/SZ sliders + the toggle/reset/done buttons live INSIDE the menu,
    // which is a DOM child of this launcher el - so their pointerdown bubbles
    // here. The handler's e.preventDefault() (below) then blocked the slider's
    // native thumb-drag, so the sliders looked dead (operator 2026-06-29). Let
    // any interactive control handle its own pointer events. The WHOLE menu is
    // excluded, not just its controls: a press on a row gap / label / border
    // armed a launcher drag (the menu region moved instead of the intended
    // panel row) and, un-moved, its release re-fired onTap and toggled the menu
    // shut under the cursor (RM-05 round-2 symptom c).
    if (e.target && e.target.closest &&
        e.target.closest("input, button, select, textarea, .ovx-launcher-menu")) {
      return;
    }
    // The launcher is a click-through ZONE (data-rc-zone), so the rc-shell makes
    // the window interactive whenever the cursor is over it - in PASSIVE too. A
    // pointerdown therefore only lands here when the operator is actually on the
    // square (hover-to-interact), so no ACTIVE-mode gate is needed: the launcher
    // is reachable mid-game without flipping the whole overlay interactive.
    down = true;
    moved = false;
    startX = e.clientX;
    startY = e.clientY;
    const p = _posFor(w);
    // Same effective-origin law as _installDrag: a stale off-field save renders
    // clamped, so the drag must start from the clamped spot or the square
    // teleports / dead-zones on the first move tick (RM-05 round-2 symptom a).
    const z0 = _bodyZoom() || 1;
    const W0 = (window.innerWidth / z0) || 1920;
    const H0 = (window.innerHeight / z0) || 1080;
    const c0 = _clampXY(p.x, p.y, W0, H0);
    originX = c0.x;
    originY = c0.y;
    lscale = Number.isFinite(p.scale) && p.scale > 0 ? p.scale : 1;
    try {
      el.setPointerCapture(e.pointerId);
    } catch (_e) {
      // harmless if the pointer is gone.
    }
    e.preventDefault();
  });
  el.addEventListener("pointermove", (e) => {
    if (!down) return;
    if (!moved && (Math.abs(e.clientX - startX) > THRESH || Math.abs(e.clientY - startY) > THRESH)) {
      moved = true;
      el.classList.add("ovx-dragging");
    }
    if (!moved) return;
    const z = _bodyZoom();
    const H = (window.innerHeight / (z || 1)) || 1080;
    const W = (window.innerWidth / (z || 1)) || 1920;
    // Clamp the launcher too - losing the menu button off-screen would strand the
    // operator with no way to reach panel settings (operator 2026-06-29).
    const c = _clampXY(
      Math.round(originX + (e.clientX - startX) / z),
      Math.round(originY + (e.clientY - startY) / z),
      W, H);
    _layout[w.id] = { ...(_layout[w.id] || {}), x: c.x, y: c.y };
    // _scalePos keeps a zoomed launcher under the cursor (item 9); a no-op at
    // the default scale 1, but a hand-edited layout JSON can carry a scale.
    el.style.left = _scalePos(c.x, lscale) + "px";
    el.style.top = _scalePos(c.y, lscale) + "px";
  });
  const end = (e) => {
    if (!down) return;
    down = false;
    el.classList.remove("ovx-dragging");
    try {
      el.releasePointerCapture(e.pointerId);
    } catch (_e) {
      // already released; harmless.
    }
    if (moved) _persist(); // a real drag settled - save the new position.
    else onTap(); // a tap - toggle the menu.
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
}

function _setMenu(open) {
  if (!_menuEl) return;
  _menuEl.classList.toggle("ovx-menu-open", !!open);
  if (open) _renderMenu(_menuEl);
}

// Build one per-panel control row: a show/hide toggle + an opacity slider + a
// scale slider. Each control mutates only its own _layout field through the
// shared read-side path (_applyPos) + persistence, so they compose cleanly.
function _menuPanelRow(menu, w) {
  const p = _posFor(w);
  const row = document.createElement("div");
  row.className = "ovx-menu-prow";
  row.dataset.ovxTarget = w.id;

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "ovx-menu-row ovx-menu-toggle";
  toggle.dataset.on = p.hidden ? "0" : "1";
  toggle.textContent = (p.hidden ? "[ ] " : "[x] ") + (w.label || w.id);
  toggle.addEventListener("click", () => {
    _toggleHidden(w);
    _renderMenu(menu); // refresh every row's state
  });
  row.appendChild(toggle);

  // Sliders only matter for a shown panel; render them regardless so toggling
  // back on does not change the row height, but dim them when hidden.
  const sliders = document.createElement("div");
  sliders.className = "ovx-menu-sliders" + (p.hidden ? " ovx-dim" : "");

  const opWrap = document.createElement("label");
  opWrap.className = "ovx-menu-slider";
  opWrap.appendChild(document.createTextNode("op"));
  const op = document.createElement("input");
  op.type = "range";
  op.min = "30"; op.max = "100"; op.step = "5";
  op.value = String(Math.round((p.opacity == null ? 1 : p.opacity) * 100));
  op.addEventListener("input", () => { _setOpacity(w, Number(op.value) / 100); });
  opWrap.appendChild(op);
  sliders.appendChild(opWrap);

  const scWrap = document.createElement("label");
  scWrap.className = "ovx-menu-slider";
  scWrap.appendChild(document.createTextNode("sz"));
  const sc = document.createElement("input");
  sc.type = "range";
  sc.min = "50"; sc.max = "160"; sc.step = "10";
  sc.value = String(Math.round((p.scale == null ? 1 : p.scale) * 100));
  sc.addEventListener("input", () => { _setScale(w, Number(sc.value) / 100); });
  scWrap.appendChild(sc);
  sliders.appendChild(scWrap);

  row.appendChild(sliders);
  menu.appendChild(row);
}

// Rebuild the menu from CURRENT state each open so every row reflects what is
// actually shown / its live opacity + scale. The coach/build/threat panel-set
// quick-swap is RETIRED (operator 2026-06-28): all panels are accessible and the
// operator manages each one here (hide / reposition / opacity / scale).
function _renderMenu(menu) {
  menu.innerHTML = "";
  const head = document.createElement("div");
  head.className = "ovx-menu-head";
  head.textContent = "PANELS";
  menu.appendChild(head);

  for (const w of WIDGETS) _menuPanelRow(menu, w);

  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "ovx-menu-row ovx-menu-reset";
  reset.textContent = "Reset all panels";
  reset.addEventListener("click", () => {
    resetOverlayLayout();
    _renderMenu(menu);
  });
  menu.appendChild(reset);

  const done = document.createElement("button");
  done.type = "button";
  done.className = "ovx-menu-row ovx-menu-done";
  done.textContent = "Done (back to play)";
  done.addEventListener("click", () => {
    _setMenu(false);
    _shellAction({ action: "set-active" }); // flip back to PASSIVE / click-through
  });
  menu.appendChild(done);
}

// Create the launcher mount once (idempotent: returns the existing node on a
// re-render). Mounted as a direct #am-grid child (NOT inside a pane) so its
// position:fixed is viewport-relative, matching the doctrine cues.
function _ensureLauncher() {
  // best-effort: a locked-down / minimal document (or a host with no appendChild)
  // must never throw into resetOverlayLayout / init - the launcher is additive.
  try {
    let el = document.querySelector(LAUNCHER.sel);
    if (el) {
      _menuEl = (el.querySelector && el.querySelector(".ovx-launcher-menu")) || _menuEl;
      _applyPos(el, _posFor(LAUNCHER));
      return el;
    }
    const host = document.querySelector("#am-grid") || document.body;
    if (!host || typeof host.appendChild !== "function") return null;

    el = document.createElement("div");
    el.id = "w-launcher";
    el.className = "ovx-widget ovx-launcher";
    el.dataset.ovxId = LAUNCHER.id;
    el.dataset.ovxTier = LAUNCHER.tier;
    el.title = "overlay menu - tap to open, drag to move";
    el.setAttribute("aria-label", "Open overlay layout menu");
    // Click-through ZONE: the rc-shell makes the window interactive on hover over
    // any [data-rc-zone] element, so the launcher (+ its menu, a child) is usable
    // mid-game in PASSIVE without the ACTIVE toggle (operator 2026-06-28).
    el.setAttribute("data-rc-zone", "");

    const icon = document.createElement("div");
    icon.className = "ovx-launcher-icon";
    // three CSS bars (a hamburger glyph drawn in CSS - no non-ASCII source char).
    icon.innerHTML = "<span></span><span></span><span></span>";
    el.appendChild(icon);

    const menu = document.createElement("div");
    menu.className = "ovx-launcher-menu";
    menu.id = "ovx-launcher-menu";
    el.appendChild(menu);
    _menuEl = menu;

    host.appendChild(el);
    _applyPos(el, _posFor(LAUNCHER));
    _installLauncher(el, LAUNCHER, () => _setMenu(!menu.classList.contains("ovx-menu-open")));
    return el;
  } catch (_e) {
    return null; // additive widget; never break the field over it.
  }
}

export function initOverlayLayout() {
  if (document.body.dataset.shell !== "overlay") return;
  _layout = _readLayout();

  // Expose the field reset so the rc-shell Alt+Shift+R global hotkey can call it
  // over executeJavaScript (the overlay is click-through during play, so a
  // page-level keydown never fires - the OS-level hotkey is the only path). The
  // doctrine section 3 reset clears both stores + re-places at the defaults.
  try {
    window.__rcOverlayReset = resetOverlayLayout;
  } catch (_e) {
    // window may be locked down in a headless context; the export still works.
  }

  // Seed from the rc-shell on-disk mirror when localStorage is empty + the
  // bridge is present (durable across a localStorage wipe), then place.
  if (
    Object.keys(_layout).length === 0 &&
    window.rcShell &&
    typeof window.rcShell.getWidgetLayout === "function"
  ) {
    Promise.resolve(window.rcShell.getWidgetLayout())
      .then((s) => {
        if (s && typeof s === "object") {
          _layout = s;
          try {
            localStorage.setItem(LS_KEY, JSON.stringify(_layout));
          } catch (_e) {
            // best-effort mirror.
          }
        }
      })
      .catch(() => {})
      .finally(() => {
        _placeAll();
        _ensureLauncher();
        _markFieldReady(); // first pass done -> reveal the gated field
      });
  } else {
    _placeAll();
    _ensureLauncher();
    _markFieldReady(); // first pass done -> reveal the gated field
  }

  // The body zoom can change with the window (ovscale); re-apply on resize so
  // the design-px positions keep their on-screen anchor.
  window.addEventListener("resize", () => {
    for (const w of WIDGETS) {
      const el = document.querySelector(w.sel);
      if (el) _applyPos(el, _posFor(w));
    }
  });

  // Survive re-renders. The lead / choices / callouts mounts are rebuilt by
  // their panel renderers (replaceWith / innerHTML), which drops the .ovx-widget
  // class AND the drag handle. A debounced observer re-runs the idempotent
  // _placeAll so positioning + handles re-attach after every re-render. The
  // observer disconnects around its own DOM writes so handle-appends do not
  // re-trigger it (no feedback loop).
  let reTimer = 0;
  const mo = new MutationObserver(() => {
    if (reTimer) return;
    reTimer = setTimeout(() => {
      reTimer = 0;
      mo.disconnect();
      _placeAll();
      _ensureLauncher(); // re-create the launcher if a re-render dropped it
      mo.observe(document.body, { childList: true, subtree: true });
    }, 150);
  });
  mo.observe(document.body, { childList: true, subtree: true });
}

// Reset the field to the section-4 defaults (clears both stores). Wired to a
// future Alt+Shift+R rc-shell hotkey; exported now for tests + a settings hook.
export function resetOverlayLayout() {
  _layout = {};
  try {
    localStorage.removeItem(LS_KEY);
  } catch (_e) {
    // best-effort.
  }
  _placeAll();
  _ensureLauncher(); // restore the launcher to its default corner + keep it shown
  _persist();
}

// Exported for unit tests (pure helpers + the registry + the hide-affordance
// seams). _setLayout lets a test drive the module's internal layout state so the
// contextmenu + reset behavior can be exercised without a real rc-shell bridge.
export const _internals = {
  WIDGETS,
  LAUNCHER,
  PANEL_SETS,
  TALL_IDS,
  _clampXY,
  _effectiveXY,
  MIN_VISIBLE,
  LS_KEY,
  _posFor,
  _readLayout,
  _isActiveMode,
  _hideWidget,
  _setHidden,
  _toggleHidden,
  _setOpacity,
  _setScale,
  _shellAction,
  _ensureLauncher,
  _renderMenu,
  _installHideMenu,
  _makeHandle,
  _persist,
  _applyPos,
  _getLayout: () => _layout,
  _setLayout: (o) => {
    _layout = o && typeof o === "object" ? o : {};
  },
};
