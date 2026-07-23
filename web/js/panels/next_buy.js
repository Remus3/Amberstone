// web/js/panels/next_buy.js
//
// NEXT BUY - two precomputed overlay rule lines from the BACKLOG "Overlay HUD
// micro-lifts" item, rendered as three fixed rows (NEXT / GOLD / TRINKET).
// ZERO API, zero LLM: all of it is arithmetic over fields /api/state already
// carries. The maths + every cited producer live in the pure model
// web/js/lib/next_buy_model.js; this file is the thin DOM render (the same
// split as web/js/lib/item_value.js -> map_state.renderItemValueDiff).
//
// HONEST NO-DATA: the widget hides ENTIRELY outside a live game with a build
// path (no sr_items, or no game clock, or no gold). Once visible ALL THREE
// rows always render - an absent value is the approved "-" sentinel, never a
// removed row - so the widget cannot reflow mid-game.
//
// Discipline mirrors objective_gauges.js / patch_impact.js: pure ESM, ASCII
// only, sig-dedup so an unchanged tick skips the DOM write, no DOM writes
// outside renderNextBuy(), self-gates on body[data-shell="overlay"] (a cheap
// no-op on the 1920 dashboard). No fetch: every input rides /api/state.

import { ITEM_COSTS, ITEM_RECIPES, _resolveItemId } from '../lib/items_index.js';
import { computeNextBuy } from '../lib/next_buy_model.js';

function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _row(key, label, value, state) {
  return (
    `<div class="nb-row nb-${key}" data-nb-row="${key}"`
    + `${state ? ` data-nb-state="${state}"` : ""}>`
    + `<span class="nb-k">${_esc(label)}</span>`
    + `<span class="nb-v">${_esc(value)}</span>`
    + `</div>`
  );
}

// A null/undefined remaining is the "-" sentinel (unknown cost), NOT 0g - an
// unknown cost must never read as "you can buy it now".
export function nextBuyHtml(m) {
  const known = m.remaining !== null && m.remaining !== undefined;
  const goldTxt = !known ? "-" : (m.remaining <= 0 ? "BUY NOW" : `${m.remaining}g`);
  return (
    `<div class="nb-grid">`
    + _row("item", "NEXT", m.item || "-", "")
    + _row("gold", "GOLD", goldTxt, known && m.remaining <= 0 ? "ready" : "")
    + _row("trinket", "TRINKET", m.trinket || "-", m.trinket ? "due" : "")
    + `</div>`
  );
}

// Signature over the rendered model so an unchanged tick skips the DOM write.
export function nextBuySig(m) {
  const rem = (m.remaining === null || m.remaining === undefined) ? "-" : m.remaining;
  return `${m.item || ""}|${rem}|${m.trinket || ""}`;
}

// --- DOM render (overlay-only) -------------------------------------------------
let _sig = null;
let _lastEnv = null;
let _wired = false;

// The item name index + the cost table are ASYNC fetches in items_index.js. A
// render that lands before they resolve can only show the "-" sentinel, and
// sig-dedup would then pin that sentinel until some OTHER field changed. So
// re-render once each table lands (the rc:items-ready idiom items_index.js
// already uses for the tile caches).
function _wireDictReady() {
  if (_wired || typeof document === "undefined") return;
  _wired = true;
  const again = () => { _sig = null; renderNextBuy(_lastEnv); };
  document.addEventListener("rc:items-ready", again);
  document.addEventListener("rc:item-costs-ready", again);
}

// env = { liveclient } - threaded by main.js at both the ui_mock and live
// active-match dispatch sites (beside renderObjectiveGauges).
export function renderNextBuy(env) {
  _wireDictReady();
  _lastEnv = env;
  const mount = document.getElementById("am-next-buy");
  if (!mount) return;
  if (!document.body || document.body.dataset.shell !== "overlay") {
    mount.hidden = true;
    return;
  }
  const e = env && typeof env === "object" ? env : {};
  const model = computeNextBuy(e.liveclient, {
    costs: ITEM_COSTS,
    recipes: ITEM_RECIPES,
    resolve: _resolveItemId,
  });
  if (!model) {
    if (_sig !== "_hidden") {
      mount.innerHTML = "";
      mount.hidden = true;
      _sig = "_hidden";
    }
    return;
  }
  const sig = nextBuySig(model);
  if (sig === _sig) return;
  _sig = sig;
  mount.innerHTML = nextBuyHtml(model);
  mount.hidden = false;
}

// Test reset (module-scope sig).
export function _resetNextBuy() {
  _sig = null;
  _lastEnv = null;
}

export const __test = { nextBuyHtml, nextBuySig };
