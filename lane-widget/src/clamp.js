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

module.exports = {
  DEFAULT_MIN_WIDTH,
  DEFAULT_MIN_HEIGHT,
  clampToContent,
};
