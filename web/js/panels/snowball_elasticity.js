// Snowball-elasticity panel (Build Insights "Snowball" tab). Renders the
// tracked player's win % bucketed by their TEAM gold lead at the 10 min and
// 20 min checkpoints as horizontal bars over the operator's OWN rewind corpus
// - a descriptive personal-corpus lens on how a gold lead (or deficit) at a
// fixed clock converts to a win, NOT a global / Riot / Claude win probability.
// ORUN2 slice 2: pure frontend mirror of the shipped snowball-elasticity
// backend (core/snowball_elasticity.py). SR-only: no mode bar, no champion
// picker (unlike duration_winrate).
//
// Backend wire:
//   GET /api/snowball-elasticity
//   Response: { ok, mode:"sr", min_bucket_n,
//     checkpoints: [{key, target_ms, n, buckets: [
//       {label, lo|null, hi|null, wins, games, winrate|null, winrate_smoothed}
//     ]}, ...] }  (two checkpoints: 10min, 20min; five buckets behind->ahead)
//   A bucket with games < min_bucket_n returns winrate null -> a muted read
//   (the Laplace-smoothed winrate_smoothed is still shown as ~xx% when games
//   > 0, else "-"). ?ui_mock=1 -> /data/ui_mock/snowball_elasticity.json
//   fixture (renders without a populated rewind DB; mirrors build_insights.js).
//
// Elasticity chip: games-weighted mean of the smoothed win% over the two
// ahead buckets minus the two behind buckets. snowball-prone / comeback-prone
// / elastic is a DESCRIPTIVE lean label, never a win-probability claim. Either
// side with zero games -> no chip.
//
// Discipline mirrors duration_winrate.js: pure ESM, ASCII only, single-slot
// cache + TTL, inflight guard, sig-dedup so an unchanged payload skips the
// rebuild, no DOM writes outside renderSnowballElasticity(), degraded-mode
// text on error (never a raw error string - repo Error-Handling rule), and
// _degraded() resets _sig so a matching refetch still repaints.

const _MOUNT = 'bi-snowball-mount';
const _KEY = 'sr';
const _CACHE = Object.create(null);
const _INFLIGHT = Object.create(null);
const _TS = Object.create(null);
const _TTL_MS = 5 * 60 * 1000;
// Elasticity thresholds in winrate percentage points (ahead - behind).
const _SNOWBALL_HI = 20;
const _SNOWBALL_LO = 8;
const _CP_TITLE = { '10min': '10 min', '20min': '20 min' };
const _BKT_LABEL = {
  behind_big: 'Behind 2.5k+',
  behind: 'Behind',
  even: 'Even',
  ahead: 'Ahead',
  ahead_big: 'Ahead 2.5k+',
};
let _sig = '';

function _isMock() {
  try { return new URLSearchParams(location.search).get('ui_mock') === '1'; }
  catch (_e) { return false; }
}

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _url() {
  return _isMock() ? '/data/ui_mock/snowball_elasticity.json'
    : '/api/snowball-elasticity';
}

function _clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function _barRow(b) {
  const raw = (b && b.winrate);
  const sm = (b && b.winrate_smoothed);
  const g = (b && b.games) | 0;
  const hasSm = (sm !== null && sm !== undefined);
  const pct = hasSm ? _clamp(Number(sm), 0, 100) : 0;
  let cls;
  let val;
  if (raw !== null && raw !== undefined) {
    cls = (Number(raw) >= 50) ? 'se-good' : 'se-bad';
    val = `${Number(raw).toFixed(1)}%`;
  } else if (hasSm && g > 0) {
    cls = 'se-dim';
    val = `~${Math.round(Number(sm))}%`;
  } else {
    cls = 'se-dim';
    val = '-';
  }
  const label = _BKT_LABEL[b && b.label] || (b && b.label) || '';
  return (
    `<div class="se-row">` +
      `<div class="se-label">${_esc(label)}</div>` +
      `<div class="se-track"><div class="se-fill ${cls}" style="width:${pct}%"></div></div>` +
      `<div class="se-val ${cls}">${val}<span class="se-n">n=${g}</span></div>` +
    `</div>`
  );
}

// Games-weighted smoothed win% over a set of bucket labels; null when no
// games land in any of them (so the chip is suppressed rather than divide
// by zero).
function _weightedMean(buckets, labels) {
  const want = new Set(labels);
  let w = 0;
  let s = 0;
  (buckets || []).forEach((b) => {
    if (!b || !want.has(b.label)) return;
    const g = b.games | 0;
    const sm = b.winrate_smoothed;
    if (g > 0 && sm !== null && sm !== undefined) {
      w += g;
      s += g * Number(sm);
    }
  });
  return w > 0 ? { mean: s / w, games: w } : { mean: null, games: 0 };
}

// Ahead-bucket smoothed win% minus behind-bucket smoothed win%. Returns a
// {label, cls} chip descriptor or null (no chip) when either side is empty.
function _elasticity(buckets) {
  const ahead = _weightedMean(buckets, ['ahead', 'ahead_big']);
  const behind = _weightedMean(buckets, ['behind_big', 'behind']);
  if (ahead.games === 0 || behind.games === 0) return null;
  if (ahead.mean === null || behind.mean === null) return null;
  const spread = ahead.mean - behind.mean;
  if (spread >= _SNOWBALL_HI) return { label: 'snowball-prone', cls: 'se-good' };
  if (spread <= _SNOWBALL_LO) return { label: 'comeback-prone', cls: 'se-dim' };
  return { label: 'elastic', cls: 'se-dim' };
}

function _chip(buckets) {
  const e = _elasticity(buckets);
  if (!e) return '';
  return `<span class="se-chip ${e.cls}" title="gold-lead elasticity: ` +
    `ahead-bucket win% minus behind-bucket win% (smoothed) - a descriptive ` +
    `lean, not a win probability">${e.label}</span>`;
}

function _checkpointBlock(cp) {
  const title = _CP_TITLE[cp && cp.key] || (cp && cp.key) || '';
  const n = (cp && cp.n) | 0;
  const buckets = (cp && cp.buckets) || [];
  const rows = buckets.map(_barRow).join('');
  return (
    `<div class="se-cp">` +
      `<div class="se-cp-head">` +
        `<div class="se-cp-title">${_esc(title)}</div>` +
        `${_chip(buckets)}` +
        `<span class="se-n">n=${n}</span>` +
      `</div>` +
      `<div class="se-chart">${rows}</div>` +
    `</div>`
  );
}

function _html(data) {
  const checkpoints = (data && data.checkpoints) || [];
  const anyGames = checkpoints.some((cp) => (cp && cp.n) | 0);
  if (checkpoints.length === 0 || !anyGames) {
    return `<div class="se-empty">Not enough SR games tracked yet.</div>`;
  }
  const minN = (data && data.min_bucket_n) || 5;
  const blocks = checkpoints.map(_checkpointBlock).join('');
  return (
    blocks +
    `<div class="se-caption">Win % bucketed by your TEAM gold lead at 10 ` +
    `and 20 min over your own SR games. Sparse buckets are shrunk (Laplace) ` +
    `and shown as ~xx%; buckets under ${minN} games show "-" (too thin to ` +
    `trust). The snowball chip is the ahead-vs-behind lean (ahead-bucket ` +
    `win% minus behind-bucket win%) - a descriptive read of how your leads ` +
    `convert, not a win probability.</div>`
  );
}

function _paint(data) {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const sig = JSON.stringify(data && data.checkpoints);
  if (sig === _sig) return;
  _sig = sig;
  mount.innerHTML = _html(data);
}

function _degraded() {
  const mount = document.getElementById(_MOUNT);
  if (mount) {
    // Reset the sig: otherwise a refetch after a transient failure whose
    // payload matches the pre-failure sig early-returns in _paint and the
    // degraded text stays stuck on screen.
    _sig = '';
    mount.innerHTML = `<div class="se-empty">Snowball stats unavailable.</div>`;
  }
}

/** Render the Snowball tab. Idempotent - safe on every tab activation. */
export function renderSnowballElasticity() {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const key = _KEY;
  const now = Date.now();
  const cached = _CACHE[key];
  if (cached && _TS[key] && (now - _TS[key]) < _TTL_MS) { _paint(cached); return; }
  if (_INFLIGHT[key]) return;
  _INFLIGHT[key] = true;
  fetch(_url(), { headers: { 'Accept': 'application/json' } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((data) => {
      if (!data || data.ok === false) { _degraded(); return; }
      _CACHE[key] = data; _TS[key] = Date.now();
      _paint(data);
    })
    .catch(() => { _degraded(); })
    .finally(() => { _INFLIGHT[key] = false; });
}
