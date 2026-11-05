// web/js/lib/escape_layers.js
//
// RM-1070: one Escape closes the layer PAINTED ON TOP. Every transient
// layer (task modal, view menu, Find Match picker, digest popover, draft-elo
// contributions overlay) used to bind its own document capture listener, so
// the first REGISTERED open layer took the press: with the view menu or the
// Find Match picker open over the task modal, Escape closed the modal
// underneath and left the upper layer showing. Layers now register here and
// one capture listener picks the topmost open one, closes it and consumes
// the press (preventDefault), so the bubble-phase Escape chain in main.js
// (modal -> reply toast -> zen) and the Replay player stand down on it. A
// press already consumed upstream is left alone (RM-1069); with nothing
// open the press passes through untouched.
//
// A layer: { name, el: () => Element|null, isOpen: () => bool, close(),
// dismiss()?, modal? }. The optional dismiss() closes without moving focus; a
// view change uses it (RM-1368, dismissStrandedLayers below). `modal: true`
// marks a full-page scrim the page's shortcuts stand down behind (RM-1364,
// modalLayerRendered below).
// "Topmost" is paint order. Each open layer's element gets its stacking
// path: every ancestor-or-self that creates a stacking context, outermost
// first, with the z it paints at inside its parent context, then the
// element itself at z 0 when it creates none. Two paths are compared at
// the first entry where they differ: the higher z wins, equal z goes to
// the later element in tree order (later paints on top), and a layer
// inside another one's context wins over it.
//
// RM-1074: the first cut ranked a layer by the z-index of its outermost
// POSITIONED ancestor, which is exact for this page's five layers (all
// position:fixed in the root context: modal 200, view menu 9100, picker
// 9200, digest 9500) but not for a layer inside a context created any
// other way. A position:fixed z-index 9999 layer under a transformed
// wrapper paints at the wrapper's z 0, below a z-index 50 layer, yet ranked
// 9999; a static flex item with z-index 60 lifts its z-index 1 child over
// that z-index 50 layer, yet ranked 1. stackingZ() below carries the CSS
// creation rules; a top-layer element (an open popover or modal dialog)
// paints over every z-index and ranks above all of them.
// Known approximations: a non-positioned leaf ranks with the z 0 positioned
// ones, and a negative-z child is still ranked over its own context root.
//
// RM-1075: four more creators measured in Chromium 147 (view-transition-
// name, content-visibility auto / hidden, -webkit-box-reflect, offset-path);
// a display:contents element has no box and makes no context; a flex or
// grid item's parent is its nearest ancestor that has a box. Two top-layer
// layers paint in the order they were OPENED, not in tree order: a capture
// beforetoggle listener (fired synchronously by showPopover and showModal)
// stamps each open with a sequence number, a later stamp wins, a stamped
// layer beats an unstamped one (opened before the listener was bound), and
// two unstamped ones fall back to tree order.
//
// RM-1076: the open-order rule rests on three assumptions.
// 1. beforetoggle fires for showModal as well as showPopover. Measured in
//    Chromium 147 (the dialog-opened-second-RED case in
//    tests/snapshot_panels/test_escape_one_action.py). An engine that fired
//    it for popovers only would leave every modal unstamped, so a stamped
//    popover opened BEFORE a modal would outrank it and Escape would close
//    the inert popover underneath instead of the modal.
// 2. beforetoggle is not composed: a popover or dialog opened inside a
//    shadow root never reaches the document capture listener, so it stays
//    unstamped and ranks by tree order (and _stackPath's parentElement walk
//    stops at its shadow root anyway). No layer here lives in a shadow root.
// 3. Fullscreen is not detected as top layer. The page only ever
//    fullscreens the root (main.js requestFullscreen on documentElement),
//    which _stackPath never walks, so a :fullscreen check would rank
//    nothing. A layer inside a fullscreened non-root element would also
//    need a fullscreenchange stamp to order it against open popovers.
//
// RM-1322: a HELD Escape is still one press. Its autorepeat keydowns
// (event.repeat) close nothing and are consumed here, ahead of every
// bubble-phase handler, so the main.js chain and the Replay player stand down
// on them too and a hold cannot walk the layer stack and then exit zen.

const _layers = [];
let _bound = false;
const _openSeq = new WeakMap();
let _seq = 0;

export function registerEscapeLayer(layer) {
  _layers.push(layer);
  if (!_bound && typeof document !== "undefined") {
    _bound = true;
    document.addEventListener("keydown", _onEscape, true);
    document.addEventListener("beforetoggle", _onBeforeToggle, true);
  }
}

function _onBeforeToggle(e) {
  if (e.newState === "open" && e.target) _openSeq.set(e.target, ++_seq);
}

// Pure: the z an element paints at inside its parent stacking context when
// it creates a stacking context of its own, else null. `cs` is its computed
// style, `parentCs` its parent's (null at the top). z-index applies to a
// positioned element and to a flex or grid item; anywhere else, and as
// "auto", the context paints at z 0. Every rule here was measured against
// elementsFromPoint in headless Chromium 147; container-type was measured
// to create NO context there and is left out.
const _GRID_FLEX = /^(inline-)?(flex|grid)$/;
const _WILL_CHANGE = new Set([
  "transform", "translate", "rotate", "scale", "opacity", "filter",
  "backdrop-filter", "perspective", "clip-path", "mask", "mask-image",
  "isolation", "mix-blend-mode", "z-index", "position", "contain",
]);
const _isSet = (v) => !!v && v !== "none";

export function stackingZ(cs, parentCs) {
  if (cs.display === "contents") return null;
  const pos = cs.position || "static";
  const item = !!parentCs && _GRID_FLEX.test(parentCs.display || "");
  const n = parseInt(cs.zIndex, 10);
  const z = (pos !== "static" || item) && !Number.isNaN(n) ? n : null;
  const contain = String(cs.contain || "");
  const forms = (
    z !== null
    || pos === "fixed" || pos === "sticky"
    || (cs.opacity !== undefined && cs.opacity !== "" && Number(cs.opacity) < 1)
    || _isSet(cs.transform) || _isSet(cs.translate)
    || _isSet(cs.rotate) || _isSet(cs.scale)
    || _isSet(cs.filter) || _isSet(cs.backdropFilter)
    || _isSet(cs.perspective) || _isSet(cs.clipPath)
    || _isSet(cs.maskImage) || _isSet(cs.webkitMaskImage)
    || (!!cs.mixBlendMode && cs.mixBlendMode !== "normal")
    || cs.isolation === "isolate"
    || /\b(layout|paint|strict|content)\b/.test(contain)
    || cs.contentVisibility === "auto" || cs.contentVisibility === "hidden"
    || _isSet(cs.viewTransitionName) || _isSet(cs.webkitBoxReflect)
    || _isSet(cs.offsetPath)
    || String(cs.willChange || "").split(",").some((p) => _WILL_CHANGE.has(p.trim()))
  );
  return forms ? (z === null ? 0 : z) : null;
}

// Pure: paint-order comparison of two { path, node } entries, where path is
// [{ el, z, seq }] outermost first (see the header; `seq` is the open stamp
// of a top-layer entry, absent elsewhere). Positive when `a` paints over
// `b`. `follows(x, y)` is true when x comes after y in tree order.
export function compareStacking(a, b, follows) {
  const n = Math.min(a.path.length, b.path.length);
  for (let i = 0; i < n; i++) {
    const x = a.path[i];
    const y = b.path[i];
    if (x.el === y.el) continue;
    if (x.z !== y.z) return x.z > y.z ? 1 : -1;
    const xs = x.seq === undefined ? -1 : x.seq;
    const ys = y.seq === undefined ? -1 : y.seq;
    if (xs !== ys) return xs > ys ? 1 : -1;
    return follows(x.el, y.el) ? 1 : -1;
  }
  if (follows(a.node, b.node)) return 1;
  return follows(b.node, a.node) ? -1 : 0;
}

// Pure choice over [{ layer, path, node }]: the entry painted on top, or
// null when there is none; a full tie keeps the first entry.
export function pickTopmost(entries, follows) {
  let best = null;
  for (const c of entries) {
    if (!best || compareStacking(c, best, follows) > 0) best = c;
  }
  return best;
}

function _inTopLayer(el) {
  for (const sel of [":modal", ":popover-open"]) {
    try { if (el.matches(sel)) return true; } catch (_) { /* unsupported */ }
  }
  return false;
}

// The computed style of the nearest ancestor that generates a box (a
// display:contents ancestor is walked through), or null at the top.
function _boxParentStyle(el) {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const cs = getComputedStyle(p);
    if (cs.display !== "contents") return cs;
  }
  return null;
}

function _stackPath(node) {
  if (!node) return [{ el: null, z: 0 }];
  const path = [];
  for (let a = node; a && a !== document.documentElement; a = a.parentElement) {
    if (_inTopLayer(a)) {
      path.push({ el: a, z: Infinity, seq: _openSeq.get(a) });
      break;
    }
    const z = stackingZ(getComputedStyle(a), _boxParentStyle(a));
    if (z !== null) path.push({ el: a, z });
    else if (a === node) path.push({ el: a, z: 0 });
  }
  return path.reverse();
}

function _follows(a, b) {
  return !!(a && b && (b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING));
}

// Pure: the [{ layer, node }] that may take an Escape, in registration
// order. A layer takes part when isOpen() says so (a throw reads as closed)
// and, RM-1365, when its element is rendered: `hasBox(node)` false drops
// it. The Lobby layers' isOpen() answers from a class, and a view change
// did not close a layer, so a Lobby menu or lane popup left open by a hash
// change or Back kept its class inside the display:none Lobby view; it
// used to win the press, close unseen and consume the Escape, so zen stayed
// on and nothing visible changed. (A view change now dismisses such layers,
// RM-1368; this filter stays for any other way a layer loses its box.)
// A layer whose el() gives no element keeps taking part, ranked at z 0, as
// before.
export function openEntries(layers, hasBox) {
  const out = [];
  for (const layer of layers) {
    let isOpen = false;
    try { isOpen = !!layer.isOpen(); } catch (_) { isOpen = false; }
    if (!isOpen) continue;
    const node = layer.el();
    if (node && !hasBox(node)) continue;
    out.push({ layer, node });
  }
  return out;
}

// Pure: the layers a view change stranded, in registration order: open
// (isOpen() true; a throw reads as closed) with an element that has no box.
// A layer whose el() gives no element is never stranded: nothing says it
// is unrendered, so it is left alone.
export function strandedLayers(layers, hasBox) {
  const out = [];
  for (const layer of layers) {
    let isOpen = false;
    try { isOpen = !!layer.isOpen(); } catch (_) { isOpen = false; }
    if (!isOpen) continue;
    const node = layer.el();
    if (node && !hasBox(node)) out.push(layer);
  }
  return out;
}

// RM-1368: applyView (main.js) calls this right after a view change.
// The Home Find Match picker's scrim lives on <body>, so a hash change or
// Back with the picker open left it dimming the new view and taking its
// first click, and Escape could not clear it (an unrendered layer takes no
// press, RM-1365); the Lobby menus stayed open behind the view and were
// still open on return. Every stranded layer is dismissed with its
// `dismiss()` (a closer that never moves focus), else its `close()`. A
// layer that throws does not stop the others. Returns the dismissed names.
export function dismissStrandedLayers() {
  if (typeof document === "undefined") return [];
  const done = [];
  for (const layer of strandedLayers(_layers, _hasBox)) {
    try {
      if (typeof layer.dismiss === "function") layer.dismiss();
      else layer.close();
      done.push(layer.name);
    } catch (_) { /* the next layer is still dismissed */ }
  }
  return done;
}

// RM-1364: a layer registered with `modal: true` (the task modal, the
// digest popout: each a position:fixed scrim over the whole page) owns the
// page's shortcuts while it is open and rendered, as a role="menu" does.
// main.js _letterShortcutsYield and the Replay player (hotkeyAction's
// modalOpen) both ask modalLayerRendered(), so the two cannot drift apart.
// Pure: true when a modal layer takes part by the openEntries rule above.
export function modalShowing(layers, hasBox) {
  return openEntries(layers.filter((l) => l && l.modal === true), hasBox).length > 0;
}

export function modalLayerRendered() {
  if (typeof document === "undefined") return false;
  return modalShowing(_layers, _hasBox);
}

// Rendered is what counts, the test main.js _letterShortcutsYield and
// review_player.js _menuOpen use: no box under display:none, itself or on an
// ancestor. A visibility:hidden or opacity 0 layer still has a box and still
// takes part (a grep of web/css finds no layer here hidden that way; not
// measured in a browser).
function _hasBox(node) {
  return node.getClientRects().length > 0;
}

function _onEscape(e) {
  if (e.key !== "Escape" && e.code !== "Escape") return;
  if (e.defaultPrevented) return;
  if (e.repeat) { e.preventDefault(); return; }
  const open = openEntries(_layers, _hasBox)
    .map(({ layer, node }) => ({ layer, node, path: _stackPath(node) }));
  const top = pickTopmost(open, _follows);
  if (!top) return;
  // Consume first: a close() that throws must not leak the press to the
  // bubble-phase chain (which would then exit zen on it as well).
  e.preventDefault();
  top.layer.close();
}
