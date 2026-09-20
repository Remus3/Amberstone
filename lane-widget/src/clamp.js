// lane-widget/src/clamp.js
//
// PURE window-geometry maths. No electron import, no IO, no clock - main.js
// feeds it the renderer-reported content size and the display work area and
// applies the result with setBounds.
//
// The rule (spec section 4): the window is never larger than its content needs,
// never larger than the work area, and never smaller than min. Those three can
// conflict, so the precedence is fixed and deliberate:
//
//   1. start from what the CONTENT needs (that is the whole point - no empty
//      gutter, no clipped row). When the content size is unknown (0 / not
//      finite, e.g. before the renderer's first report) fall back to the
//      REQUESTED size, and failing that to min.
//   2. cap to the work area - a window bigger than the screen is unusable.
//   3. floor at min - this is applied LAST, so on an absurdly small work area
//      min wins. That is intentional: a 20px window is worse than one that
//      overhangs.
//
// x/y follow the rc-shell/src/config.js clampPosition discipline: a window that
// has never been positioned reports { x: null, y: null } so the caller lets the
// OS centre it.

"use strict";

const DEFAULT_MIN_WIDTH = 200;
const DEFAULT_MIN_HEIGHT = 80;

// Positive finite number, else the fallback. Mirrors rc-shell's posNum.
function posNum(v, fallback) {
  return typeof v === "number" && isFinite(v) && v > 0 ? v : fallback;
}

function clampAxis(requested, content, work, minimum) {
  const c = posNum(content, 0);
  const r = posNum(requested, 0);
  const m = posNum(minimum, 0);
  const w = posNum(work, 0);

  // 1. what the content needs, else the request, else the minimum.
  let target = c > 0 ? c : r > 0 ? r : m;
  if (target <= 0) {
    target = m;
  }
  // 2. never larger than the work area.
  if (w > 0) {
    target = Math.min(target, w);
  }
  // 3. never smaller than min (applied last - see the header note).
  target = Math.max(target, m);
  return Math.round(target);
}

// clampToContent({ requested, content, workArea, min })
//   requested: { x?, y?, width?, height? }  the current / saved window box
//   content:   { width, height }            renderer-reported content size
//   workArea:  { x, y, width, height }      the display work area
//   min:       { width, height }            hard floor
// -> { x, y, width, height }  x/y are null when the window is not yet placed.
function clampToContent(args) {
  const a = args && typeof args === "object" ? args : {};
  const requested = a.requested && typeof a.requested === "object" ? a.requested : {};
  const content = a.content && typeof a.content === "object" ? a.content : {};
  const workArea = a.workArea && typeof a.workArea === "object" ? a.workArea : {};
  const min = a.min && typeof a.min === "object" ? a.min : {};

  const minW = posNum(min.width, DEFAULT_MIN_WIDTH);
  const minH = posNum(min.height, DEFAULT_MIN_HEIGHT);

  const width = clampAxis(requested.width, content.width, workArea.width, minW);
  const height = clampAxis(requested.height, content.height, workArea.height, minH);

  // Not yet positioned -> signal "centre me", exactly like rc-shell.
  const hasX = typeof requested.x === "number" && isFinite(requested.x);
  const hasY = typeof requested.y === "number" && isFinite(requested.y);
  if (!hasX || !hasY) {
    return { x: null, y: null, width, height };
  }

  const wx = typeof workArea.x === "number" && isFinite(workArea.x) ? workArea.x : 0;
  const wy = typeof workArea.y === "number" && isFinite(workArea.y) ? workArea.y : 0;
  const ww = posNum(workArea.width, 1920);
  const wh = posNum(workArea.height, 1080);

  // Max top-left keeping the far edge on screen. If the window is bigger than
  // the work area, max collapses below min and the Math.max pins to the origin.
  const maxX = wx + ww - width;
  const maxY = wy + wh - height;
  const x = Math.round(Math.max(wx, Math.min(requested.x, Math.max(wx, maxX))));
  const y = Math.round(Math.max(wy, Math.min(requested.y, Math.max(wy, maxY))));

  return { x, y, width, height };
}

// minimumSizeFor({ content, workArea, min }) -> { width, height }
//
// The floor handed to setMinimumSize, i.e. the narrowest box the USER may drag
// the window to. It is NOT the same number as `min` above, and that difference
// is the whole point of this function.
//
// WHY THE WIDTH TRACKS THE CONTENT. widget.css gives .panel `width:max-content`,
// which is load bearing (main.js clamps to a measured box rather than a guessed
// viewport) and which does NOT shrink: a panel whose content is 499px wide stays
// 499px wide in a 240px window, and `body { overflow: hidden }` clips the
// remainder - the gear on the right edge included. A static 240px floor
// therefore hands the user a drag range in which the widget is visibly broken
// until the resize-settle clamp snaps it back. Since clampToContent already
// forces the width back to the content box on every settle, that range was
// never a real degree of freedom; refusing the drag is the honest expression of
// a contract the clamp was enforcing anyway.
//
// The width is computed by the same clampAxis the clamp uses, with no requested
// size, so it lands on exactly the width clampToContent would choose. That
// equality matters: a floor ABOVE the clamped width would make the clamp's own
// setBounds unsatisfiable on a work area narrower than the content.
//
// WHY THE HEIGHT DOES NOT. A short window is not the same defect as a narrow
// one - .panel is capped by the work-area-derived --panel-max-height and .cards
// scrolls, so vertical truncation degrades gracefully. More importantly the
// height axis is the one that carried the 2026-09-19 SHRINK RATCHET, so it
// keeps the static floor and nothing here reads a window-derived height.
//
// This is a constant function of the CONTENT, never of the window: max-content
// does not vary with the width it is given, so no feedback loop is opened.
function minimumSizeFor(args) {
  const a = args && typeof args === "object" ? args : {};
  const content = a.content && typeof a.content === "object" ? a.content : {};
  const workArea = a.workArea && typeof a.workArea === "object" ? a.workArea : {};
  const min = a.min && typeof a.min === "object" ? a.min : {};

  const minW = posNum(min.width, DEFAULT_MIN_WIDTH);
  const minH = posNum(min.height, DEFAULT_MIN_HEIGHT);

  return {
    width: clampAxis(0, content.width, workArea.width, minW),
    height: minH,
  };
}

module.exports = {
  DEFAULT_MIN_WIDTH,
  DEFAULT_MIN_HEIGHT,
  clampToContent,
  minimumSizeFor,
};
