// Interactive Item Shaper 3-knob strip (OQ14).
//
// A compact DAMAGE / SURV / UTILITY control strip that the operator nudges
// with - / + buttons (each axis clamps to [-2, +2]). Each change re-fetches a
// SHAPED-EMPHASIS preview from the backend and renders three ASCII lines
// "LABEL base% -> shaped%".
//
// State is NON-PERSISTING by design: a plain module var, NO localStorage. It
// snaps back to zero on champion change / match end. renderShaperStrip resets
// the knobs whenever the champion argument differs from the tracked one (a new
// match = a new champion), and resetShaper() is the explicit zeroing hook the
// host calls on match end.
//
// Route contract (built in parallel - code against it):
//   GET /api/ds-shape?champion=<canonicalId>&damage=<int -2..2>
//       &survivability=<int -2..2>&utility=<int -2..2>
//   200 -> { ok:true, champion, archetype_source,
//            knobs:{damage,survivability,utility},
//            baseline:{...}(fractions), shaped:{...}(fractions),
//            baseline_pct:{...}(ints), shaped_pct:{...}(ints), elapsed_ms }
//   blank champion -> 400 { ok:false, error }
//
// The pure helper computeShaperQuery() is shared by _refresh and the DOM test.

import { escHtml } from '../lib/helpers.js';
import { dedupFetch } from '../lib/dedup_fetch.js';

// ----- module state (NON-persisting; NO localStorage) --------------------
const _S = { champion: null, damage: 0, survivability: 0, utility: 0 };

// The three axes, in render order. `field` is the _S key + query param name;
// `label` is the short strip caption.
const AXES = [
  { field: 'damage', label: 'DMG' },
  { field: 'survivability', label: 'SURV' },
  { field: 'utility', label: 'UTIL' },
];

const KNOB_MIN = -2;
const KNOB_MAX = 2;
const _DEBOUNCE_MS = 180;
let _debounceTimer = null;

// Zero all knobs and forget the tracked champion. The host calls this on match
// end so the strip snaps back to neutral for the next game.
export function resetShaper() {
  _S.champion = null;
  _S.damage = 0;
  _S.survivability = 0;
  _S.utility = 0;
}

// PURE. Build the /api/ds-shape query string for a champion + knob state.
// champion is URL-encoded; the three knob ints are emitted verbatim (their
// range is already clamped by the caller). Shared by _refresh + the DOM test.
export function computeShaperQuery(champion, s) {
  const c = encodeURIComponent(champion == null ? '' : String(champion));
  const d = (s && s.damage) | 0;
  const v = (s && s.survivability) | 0;
  const u = (s && s.utility) | 0;
  return 'champion=' + c + '&damage=' + d + '&survivability=' + v + '&utility=' + u;
}

// Clamp an integer knob value into [KNOB_MIN, KNOB_MAX].
function _clampKnob(n) {
  const i = n | 0;
  if (i < KNOB_MIN) return KNOB_MIN;
  if (i > KNOB_MAX) return KNOB_MAX;
  return i;
}

// Render the emphasis preview into outEl from an ok payload. Three ASCII lines
// "LABEL base -> shaped" using the integer percent fields. Falls back to a
// dim note when a payload is missing / not ok.
function _renderOut(outEl, data) {
  if (!outEl) return;
  if (!data || !data.ok) {
    outEl.innerHTML = '<span class="bm-shaper-note">shaper preview unavailable</span>';
    return;
  }
  const base = data.baseline_pct || {};
  const shaped = data.shaped_pct || {};
  const lines = AXES.map((ax) => {
    const b = base[ax.field];
    const sh = shaped[ax.field];
    const bTxt = (typeof b === 'number') ? String(b) : '-';
    const shTxt = (typeof sh === 'number') ? String(sh) : '-';
    return '<div class="bm-shaper-line">'
      + escHtml(ax.label) + ' ' + escHtml(bTxt) + ' -&gt; ' + escHtml(shTxt)
      + '</div>';
  });
  outEl.innerHTML = lines.join('');
}

// Debounced fetch + render. Rapid clicks coalesce into one network call.
function _refresh(champion, mode, outEl) {
  if (_debounceTimer) clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => {
    _debounceTimer = null;
    if (!champion) {
      _renderOut(outEl, null);
      return;
    }
    const q = computeShaperQuery(champion, _S);
    const url = '/api/ds-shape?' + q;
    let p;
    try {
      p = (typeof dedupFetch === 'function') ? dedupFetch(url) : fetch(url);
    } catch (_e) {
      p = fetch(url);
    }
    Promise.resolve(p)
      .then((resp) => (resp && typeof resp.json === 'function') ? resp.json() : null)
      .then((data) => { _renderOut(outEl, data); })
      .catch(() => { _renderOut(outEl, null); });
  }, _DEBOUNCE_MS);
}

// Build one axis block: label, minus button, value, plus button. Wires the
// clamp + refresh handlers. stopPropagation mirrors the active_match.js meta
// strip so the overlay ACTIVE-mode click/contextmenu dismiss handler does not
// fire on a knob press.
function _buildAxis(ax, champion, mode, outEl) {
  const wrap = document.createElement('div');
  wrap.className = 'bm-shaper-axis';
  wrap.dataset.axis = ax.field;

  // BATCH A counter layout: the "- value +" counter on top, the cyan axis label
  // directly BELOW it (the operator EXAMPLE - a compact 2-row block), instead of
  // the old inline "LABEL - value +".
  const counter = document.createElement('div');
  counter.className = 'bm-shaper-counter';

  const minus = document.createElement('button');
  minus.className = 'bm-shaper-btn';
  minus.type = 'button';
  minus.textContent = '-';

  const val = document.createElement('span');
  val.className = 'bm-shaper-val';
  val.textContent = String(_S[ax.field]);

  const plus = document.createElement('button');
  plus.className = 'bm-shaper-btn';
  plus.type = 'button';
  plus.textContent = '+';

  minus.addEventListener('click', (e) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    _S[ax.field] = _clampKnob(_S[ax.field] - 1);
    val.textContent = String(_S[ax.field]);
    _refresh(champion, mode, outEl);
  });
  plus.addEventListener('click', (e) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    _S[ax.field] = _clampKnob(_S[ax.field] + 1);
    val.textContent = String(_S[ax.field]);
    _refresh(champion, mode, outEl);
  });

  counter.appendChild(minus);
  counter.appendChild(val);
  counter.appendChild(plus);

  const label = document.createElement('span');
  label.className = 'bm-shaper-label';
  label.textContent = ax.label;

  wrap.appendChild(counter);
  wrap.appendChild(label);
  return wrap;
}

// Remove all children of an element (idempotent render: wipe + rebuild).
function _clear(elm) {
  if (!elm) return;
  if (typeof elm.replaceChildren === 'function') {
    elm.replaceChildren();
    return;
  }
  while (elm.firstChild) elm.removeChild(elm.firstChild);
}

// Public entry: (re)build the shaper strip under rowEl for `champion` / `mode`.
// If champion differs from the tracked one, knobs reset to 0 (the snap-back on
// champion change / match end). Idempotent - wipes rowEl before rebuilding.
export function renderShaperStrip(rowEl, champion, mode) {
  if (!rowEl) return;
  if (champion !== _S.champion) {
    _S.champion = champion;
    _S.damage = 0;
    _S.survivability = 0;
    _S.utility = 0;
  }

  _clear(rowEl);

  const strip = document.createElement('div');
  strip.className = 'bm-shaper-strip';
  // BATCH A dead-counter fix: mark the strip an interactive zone so the in-game
  // overlay (rc-shell click-through) captures the cursor over the +/- buttons -
  // without it every click passed through the overlay to the game and the
  // counters never changed (clickthrough_zones.js ZONE_SELECTOR = [data-rc-zone]).
  strip.setAttribute('data-rc-zone', '');

  const out = document.createElement('div');
  out.className = 'bm-shaper-out';

  AXES.forEach((ax) => {
    strip.appendChild(_buildAxis(ax, champion, mode, out));
  });

  rowEl.appendChild(strip);
  rowEl.appendChild(out);

  // Initial preview at the current (freshly zeroed or retained) knob state.
  _refresh(champion, mode, out);
  return strip;
}

// Test-only introspection of the non-persisting module state.
export function _shaperState() {
  return { champion: _S.champion, damage: _S.damage, survivability: _S.survivability, utility: _S.utility };
}
