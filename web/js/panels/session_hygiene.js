// Session-hygiene card (Session view). Renders core.session_hygiene's
// deterministic "Should I Queue" readiness read over the operator's OWN
// rewind corpus: a bounded 0-100 readiness score + HIGH/MED/LOW confidence +
// the contributing factors (session position, rust, hour, weekday,
// same-champ requeue) each as a signed win% nudge, plus a win-rate-by-
// session-position tilt strip. Computed entirely over the operator's own
// games (no global / Riot / Claude dependency) - the Haiku-to-ZERO north star.
//
// Backend wire:
//   GET /api/session-hygiene[?queue=<id,..>]
//   Response: { ok, n, overall_wr, readiness:{score, confidence,
//     factors:[{factor, delta_pts, note, contributed, n}, ...], context,
//     state, flags:[{flag, kind, n, delta_pts, note}, ...], basis},
//     wr_by_session_position:[{position, label, wr, games}, ...],
//     same_champ_requeue:{same_champ:{wr,games}, diff_champ:{wr,games}}, ... }
//   An inert factor (contributed=false) shows the "-" thin sentinel.
//   Y-04: score is null and state 'unknown' when no context bucket has
//   enough games; the card then shows "-" plus the basis line in the SAME
//   skeleton (no reflow), never "0/100" (Number(null) === 0).
//
// Discipline mirrors duration_winrate.js / draft_score.js: pure ESM, ASCII
// only, single-key cache + TTL, inflight guard, sig-dedup, no DOM writes
// outside renderSessionHygiene(), degraded text on error (never a raw error
// string - repo Error-Handling rule).

const _MOUNT = 'session-hygiene-card';
const _TTL_MS = 5 * 60 * 1000;
let _cache = null;
let _ts = 0;
let _inflight = false;
let _sig = '';

const _FACTOR_LABEL = {
  session_position: 'Session position',
  rust: 'Rust (time off)',
  hour: 'Time of day',
  weekday: 'Day of week',
  same_champ: 'Same-champ requeue',
  requeue: 'Same-champ requeue',
};

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Readiness is 0-100 (higher = a better time to queue). >=55 favorable,
// <=45 unfavorable, the middle reads neutral - a lean, not a guarantee.
// Y-04: a null score is UNKNOWN, not 0 - Number(null) is 0 and isFinite(0)
// is true, so null must be caught before the coercion.
function _readinessClass(score) {
  if (score == null) return 'sh-dim';
  const s = Number(score);
  if (!isFinite(s)) return 'sh-dim';
  if (s >= 55) return 'sh-good';
  if (s <= 45) return 'sh-bad';
  return 'sh-even';
}

function _confClass(conf) {
  const c = String(conf || '').toUpperCase();
  if (c === 'HIGH') return 'sh-conf-high';
  if (c === 'LOW') return 'sh-conf-low';
  return 'sh-conf-med';
}

// A signed win% nudge is colored good/bad only past a +/-2pt band; smaller
// moves read neutral so noise near zero never looks decisive.
function _deltaClass(pts) {
  const d = Number(pts);
  if (!isFinite(d)) return 'sh-dim';
  if (d >= 2) return 'sh-good';
  if (d <= -2) return 'sh-bad';
  return 'sh-dim';
}

function _fmtDelta(pts) {
  const d = Number(pts) || 0;
  return `${d >= 0 ? '+' : ''}${d.toFixed(1)}`;
}

function _factorRow(f) {
  const name = _FACTOR_LABEL[f.factor] || f.factor;
  const live = !!f.contributed;
  const cls = live ? _deltaClass(f.delta_pts) : 'sh-dim';
  const val = live ? `${_fmtDelta(f.delta_pts)}pt` : '-';
  const note = f.note ? ` <span class="sh-factor-note">${_esc(f.note)}</span>` : '';
  return (
    `<div class="sh-factor${live ? '' : ' is-inert'}">` +
      `<div class="sh-factor-name">${_esc(name)}${note}</div>` +
      `<div class="sh-factor-val ${cls}">${val}` +
        `<span class="sh-factor-n">${live ? `n=${f.n | 0}` : 'no data'}</span></div>` +
    `</div>`
  );
}

// Small WR-by-session-position tilt strip: does win-rate decay as a session
// runs long? Bars are win% (0-100); the current session's next position is
// highlighted when known.
function _tiltStrip(rows) {
  const bars = (rows || []).map((r) => {
    const wr = r.wr != null ? Number(r.wr) * 100 : null;
    const has = wr != null && isFinite(wr);
    const pct = has ? Math.max(0, Math.min(100, wr)) : 0;
    const cls = !has ? 'sh-dim' : (wr >= 50 ? 'sh-good' : 'sh-bad');
    const val = has ? `${wr.toFixed(0)}%` : '-';
    return (
      `<div class="sh-tilt-col" title="game #${_esc(r.label)}: ${val} over ${r.games | 0} games">` +
        `<div class="sh-tilt-track"><div class="sh-tilt-fill ${cls}" ` +
          `style="height:${pct}%"></div></div>` +
        `<div class="sh-tilt-label">${_esc(r.label)}</div>` +
      `</div>`
    );
  }).join('');
  return `<div class="sh-tilt" aria-label="Win rate by game number within a session">${bars}</div>`;
}

// Y-04 readiness light. The backend sends state in {unknown, green, yellow,
// red}; a legacy payload without it derives the light from the score with the
// same <=45 band the backend uses (core.session_hygiene._LIGHT_LOW_SCORE).
const _STATES = ['unknown', 'green', 'yellow', 'red'];
const _STATE_LABEL = {
  unknown: 'UNKNOWN', green: 'GREEN', yellow: 'YELLOW', red: 'RED',
};

function _state(rd) {
  const s = String((rd && rd.state) || '').toLowerCase();
  if (_STATES.includes(s)) return s;
  if (!rd || rd.score == null || !isFinite(Number(rd.score))) return 'unknown';
  return Number(rd.score) <= 45 ? 'yellow' : 'green';
}

// One flag line: odds-shift wording comes from the backend note verbatim
// (escaped); an override flag is marked so it reads as the cap it is.
function _flagRow(f) {
  const over = f && f.kind === 'override';
  return (
    `<div class="sh-flag${over ? ' is-override' : ''}">` +
      `${_esc((f && (f.note || f.flag)) || '')}</div>`
  );
}

function sessionHygieneHtml(payload) {
  if (!payload || payload.ok === false) {
    return '<div class="sh-empty">Session readiness unavailable.</div>';
  }
  const rd = payload.readiness || {};
  const state = _state(rd);
  const unknown = state === 'unknown' || rd.score == null;
  const score = unknown ? NaN : Number(rd.score);
  const cls = unknown ? 'sh-dim' : _readinessClass(score);
  const conf = String(rd.confidence || 'LOW').toUpperCase();
  const factors = (rd.factors || []).map(_factorRow).join('');
  const tilt = _tiltStrip(payload.wr_by_session_position);
  const overall = payload.overall_wr != null
    ? `${(Number(payload.overall_wr) * 100).toFixed(1)}%` : '-';
  const basis = rd.basis
    ? String(rd.basis)
    : (unknown ? 'Unknown: not enough games in any context bucket yet.' : '');
  const flagList = Array.isArray(rd.flags) ? rd.flags : [];
  const flags = flagList.length
    ? flagList.map(_flagRow).join('')
    : '<div class="sh-flag is-none">No flags</div>';
  return (
    `<div class="session-card-head">SHOULD I QUEUE</div>` +
    `<div class="sh-head">` +
      `<span class="sh-score ${cls}">${isFinite(score) ? score.toFixed(0) : '-'}` +
        `<span class="sh-score-max">/100</span></span>` +
      `<span class="sh-state sh-state-${state}" ` +
        `title="Readiness light: flags cap it; unknown means no read">` +
        `${_STATE_LABEL[state]}</span>` +
      `<span class="sh-conf ${_confClass(conf)}" ` +
        `title="Confidence from the evidence behind the readiness nudge">${_esc(conf)}</span>` +
    `</div>` +
    `<div class="sh-basis">${_esc(basis)}</div>` +
    `<div class="sh-flags">${flags}</div>` +
    `<div class="sh-factors">${factors}</div>` +
    `<div class="sh-tilt-wrap"><div class="sh-tilt-head">Win % by game # in a ` +
      `session</div>${tilt}</div>` +
    `<div class="sh-caption">Readiness is a signed nudge off your ${overall} ` +
      `baseline over your own games (n=${payload.n | 0}) - a lean, not a ` +
      `guarantee. Inert factors show "-" and drop out.</div>`
  );
}

function _signature(payload) {
  if (!payload || payload.ok === false) return '_empty';
  const rd = payload.readiness || {};
  const f = (rd.factors || []).map((x) =>
    `${x.factor}:${x.contributed ? '1' : '0'}:${Number(x.delta_pts || 0).toFixed(1)}`
  ).join(';');
  // String(rd.score), not Number(): null must not collide with a real 0.
  const score = rd.score == null ? 'null' : Number(rd.score).toFixed(0);
  const fl = (Array.isArray(rd.flags) ? rd.flags : []).map((x) => x && x.flag).join(',');
  return `${score}:${_state(rd)}:${fl}:${rd.confidence}:${f}:${payload.n | 0}`;
}

export function renderSessionHygiene() {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const now = Date.now();
  if (_cache && (now - _ts) < _TTL_MS) { _paint(mount, _cache); return; }
  if (_inflight) return;
  _inflight = true;
  // ?ui_mock=1 audit path: the Session view's mock fixture carries an
  // UNKNOWN-state readiness payload under `session_hygiene` (Y-04), so the
  // hardest-to-reach-live branch is reviewable.
  const mock = !!(document.body && document.body.dataset.uiMock === '1');
  const req = mock
    ? fetch('/data/ui_mock/session.json', { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => (d && d.session_hygiene) || null)
    : fetch('/api/session-hygiene', { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : null));
  req
    .then((data) => {
      if (data && data.ok !== false) {
        _cache = data; _ts = Date.now();
        _paint(mount, data);
      } else {
        _degraded(mount);
      }
    })
    .catch(() => { _degraded(mount); })
    .finally(() => { _inflight = false; });
}

function _paint(mount, data) {
  const sig = _signature(data);
  if (sig === _sig) return;
  _sig = sig;
  mount.hidden = false;
  mount.innerHTML = sessionHygieneHtml(data);
}

function _degraded(mount) {
  _sig = '';
  mount.hidden = false;
  mount.innerHTML = '<div class="session-card-head">SHOULD I QUEUE</div>' +
    '<div class="sh-empty">Session readiness unavailable.</div>';
}

export function _resetSessionHygiene() {
  _cache = null; _ts = 0; _inflight = false; _sig = '';
}

export const __test = {
  _readinessClass, _confClass, _deltaClass, _fmtDelta, _factorRow, _tiltStrip,
  sessionHygieneHtml, _signature, _FACTOR_LABEL, _state, _flagRow,
};
