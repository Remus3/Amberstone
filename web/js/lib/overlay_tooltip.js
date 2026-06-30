// WP-D1 (OVERLAY_BUILD_MASTER_PLAN Section D): hover tooltip for build-module
// item icons. A single tip element lives on <html> (dodging the dashboard body
// `zoom`, mirroring the champ_select trade popup at champ_select.js:303). It
// shows an item's name + stats + passive - pulled from the /api/dictionary/items
// dict already loaded by items_index.js (ITEM_DETAILS) - after the cursor
// settles, anchored toward the screen edge so it never covers the play area.
//
// Doctrine (master plan WP-D1): show 300-500ms after the cursor settles;
// immediate (<=100ms) hover highlight; ~0.5s hide grace; pointer-events:none so
// the tip never traps the cursor / never shows with nothing beneath it. Tier-1
// (overlay-only), no server dependency. The page had only native `title=` attrs
// before this.

import { ITEM_DETAILS, parseItemTooltip } from "./items_index.js";

const SHOW_DELAY = 350;   // ms after the cursor settles on an icon (300-500 band)
const HIDE_GRACE = 500;   // ms grace before the tip hides on mouseleave (~0.5s)
const EDGE_GAP = 10;      // px gap between icon / viewport edge and the tip

let _tip = null;          // the singleton tip element (on <html>)
let _showT = 0;           // pending show timer
let _hideT = 0;           // pending hide timer

// Match overlay_layout._bodyZoom: the dashboard body carries a `zoom` (base.css)
// and a position:fixed tip on <html> must scale to match its visual size.
function _bodyZoom() {
  const z = parseFloat(getComputedStyle(document.body).zoom);
  return Number.isFinite(z) && z > 0 ? z : 1;
}

function _ensureTip() {
  if (_tip) return _tip;
  _tip = document.createElement("div");
  _tip.id = "rc-item-tip";
  // Inline-styled (house style): opaque card, above everything, inert. The
  // pointer-events:none is doctrine - the tip can never sit under the cursor.
  _tip.style.cssText = [
    "position:fixed",
    "z-index:2147483600",
    "max-width:280px",
    "padding:8px 10px",
    "border-radius:8px",
    "background:rgba(12,14,20,0.97)",
    "border:1px solid #2a2f3a",
    "box-shadow:0 6px 20px rgba(0,0,0,0.55)",
    "color:#e6e8ee",
    "pointer-events:none",
    "visibility:hidden",
    "left:0",
    "top:0",
  ].join(";") + ";";
  document.documentElement.appendChild(_tip);
  return _tip;
}

// Build the tip body: bold name (16px) -> stats lines (13px) -> passive prose
// (13px). Only the prose block is allowed wrapped text (per the doctrine).
function _renderInto(tip, detail) {
  const t = parseItemTooltip(detail);
  tip.textContent = "";
  const nm = document.createElement("div");
  nm.textContent = t.name || "?";
  nm.style.cssText = "font-size:16px;font-weight:700;color:#ffffff;margin-bottom:4px;";
  tip.appendChild(nm);
  if (t.stats.length) {
    const st = document.createElement("div");
    st.style.cssText = "font-size:13px;line-height:1.35;color:#cfe8ff;";
    t.stats.forEach((line) => {
      const row = document.createElement("div");
      row.textContent = line;
      st.appendChild(row);
    });
    tip.appendChild(st);
  }
  if (t.passive) {
    const ps = document.createElement("div");
    ps.textContent = t.passive;
    ps.style.cssText = "font-size:13px;line-height:1.4;color:#b9bdc7;margin-top:6px;white-space:pre-line;";
    tip.appendChild(ps);
  }
}

// Render-then-measure placement. The tip is sized while visibility:hidden, then
// anchored to the side away from the play area: an icon in the right viewport
// half opens its tip rightward (toward the screen edge), left-half leftward;
// flip if it would clip, then clamp into the viewport on both axes.
function _place(tip, anchorEl) {
  const z = _bodyZoom() || 1;
  tip.style.zoom = String(z);  // match the dashboard / overlay visual scale
  const a = anchorEl.getBoundingClientRect();
  const r = tip.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const aCx = (a.left + a.right) / 2;
  let left = aCx > vw / 2 ? a.right + EDGE_GAP : a.left - r.width - EDGE_GAP;
  if (left < EDGE_GAP) left = a.right + EDGE_GAP;                       // flip right
  if (left + r.width > vw - EDGE_GAP) left = a.left - r.width - EDGE_GAP; // flip left
  left = Math.max(EDGE_GAP, Math.min(left, vw - r.width - EDGE_GAP));
  let top = Math.max(EDGE_GAP, Math.min(a.top, vh - r.height - EDGE_GAP));
  // a/r/vw/vh are SCREEN px (getBoundingClientRect is post-zoom), but the tip
  // carries zoom=z, so style.left/top are multiplied by z when rendered. Divide
  // by z so the tip lands at the computed SCREEN position instead of z-times
  // further right + down (operator 2026-06-29: tooltip appeared far right/below
  // the anchor at any overlay ovscale != 1).
  tip.style.left = Math.round(left / z) + "px";
  tip.style.top = Math.round(top / z) + "px";
}

function _clearTimers() {
  if (_showT) { clearTimeout(_showT); _showT = 0; }
  if (_hideT) { clearTimeout(_hideT); _hideT = 0; }
}

function _hideNow() {
  if (_tip) _tip.style.visibility = "hidden";
}

// Wire the hover tooltip onto one build-module icon cell. itemId resolves the
// detail in ITEM_DETAILS; itemName is the fallback when the id has no dict entry
// (base items / fallback tiles) so the tip still shows the name.
export function installItemTooltip(anchorEl, itemId, itemName) {
  if (!anchorEl) return;
  anchorEl.addEventListener("mouseenter", () => {
    _clearTimers();
    // Immediate (<=100ms) hover affordance - synchronous, before the deferred
    // tip fires. Cyan (#6cf) matches the in-module NEXT accent.
    anchorEl.style.boxShadow = "0 0 0 2px #6cf";
    _showT = setTimeout(() => {
      if (!anchorEl.isConnected) return;  // icon left the DOM mid-wait
      const detail = (ITEM_DETAILS.byId && ITEM_DETAILS.byId[String(itemId)])
        || { name: itemName || "", description: "" };
      const tip = _ensureTip();
      tip.style.visibility = "hidden";
      _renderInto(tip, detail);
      _place(tip, anchorEl);
      tip.style.visibility = "visible";
    }, SHOW_DELAY);
  });
  anchorEl.addEventListener("mouseleave", () => {
    _clearTimers();
    anchorEl.style.boxShadow = "";
    _hideT = setTimeout(_hideNow, HIDE_GRACE);
  });
}
