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
// A layer: { name, el: () => Element|null, isOpen: () => bool, close() }.
// "Topmost" is the paint order of the root stacking context: the z-index
// of the outermost positioned ancestor-or-self with a numeric z-index
// (0 when none), ties broken by tree order (later paints on top). That is
// exact for this page's layers, which are all position:fixed children of
// <body> or of a static wrapper (measured: modal 200, view menu 9100,
// picker 9200, digest 9500); a nested stacking context is compared by its
// root-level ancestor, which is what decides which one covers the other.

const _layers = [];
let _bound = false;

export function registerEscapeLayer(layer) {
  _layers.push(layer);
  if (!_bound && typeof document !== "undefined") {
    _bound = true;
    document.addEventListener("keydown", _onEscape, true);
  }
}

// Pure choice over [{ layer, z, node }]: the highest z wins; equal z goes to
// the later node in tree order. `follows(a, b)` is true when a comes after b.
export function pickTopmost(entries, follows) {
  let best = null;
  for (const c of entries) {
    if (!best || c.z > best.z || (c.z === best.z && follows(c.node, best.node))) {
      best = c;
    }
  }
  return best;
}

function _rootZ(node) {
  let z = 0;
  for (let a = node; a && a !== document.body; a = a.parentElement) {
    const cs = getComputedStyle(a);
    const n = parseInt(cs.zIndex, 10);
    if (cs.position !== "static" && !Number.isNaN(n)) z = n;
  }
  return z;
}

function _follows(a, b) {
  return !!(a && b && (b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING));
}

function _onEscape(e) {
  if (e.key !== "Escape" && e.code !== "Escape") return;
  if (e.defaultPrevented) return;
  const open = [];
  for (const layer of _layers) {
    let isOpen = false;
    try { isOpen = !!layer.isOpen(); } catch (_) { isOpen = false; }
    if (!isOpen) continue;
    const node = layer.el();
    open.push({ layer, node, z: node ? _rootZ(node) : 0 });
  }
  const top = pickTopmost(open, _follows);
  if (!top) return;
  // Consume first: a close() that throws must not leak the press to the
  // bubble-phase chain (which would then exit zen on it as well).
  e.preventDefault();
  top.layer.close();
}
