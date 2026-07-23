// Draft-score card (Champ Select). Renders core.draft_score's deterministic
// five-layer draft-quality read for the operator's committed ally comp
// (optionally vs the enemy comp) as ONE bounded 42-58 score + a HIGH/MED/LOW
// confidence chip + a per-layer contributed/inert breakdown. Computed entirely
// over the operator's OWN rewind participant corpus + owned DS/101qq primitives
// (no global / Riot / Claude dependency) - the Haiku-to-ZERO north star.
//
// Backend wire:
//   GET /api/draft-score?ally=<id,id,id,id,id>[&enemy=<id,...5>][&queue=<id,..>]
//   ally  : EXACTLY 5 numeric riot champion ids (the LCU championId, not slug).
//   enemy : optional 5 enemy ids for the lane-matchup layer.
//   Response: { ok, score, confidence, band:[lo,hi], contributing,
//     layers:[{name, weight, sub_score|null, n, trust, contributed}, ...] }
//   A layer with no evidence (no enemy comp -> matchup; no scaling primitive ->
//   scaling) returns contributed=false + sub_score=null -> a muted "-" row.
//
// The card is HIDDEN until 5 ally champions are committed (the route rejects a
// short ally list). Enemy is optional - the matchup layer just goes inert.
//
// Discipline mirrors cc_conditional_pressure.js / duration_winrate.js: pure ESM,
// ASCII only, per-key cache + TTL, inflight guard, sig-dedup so an unchanged
// payload skips the rebuild, no DOM writes outside renderDraftScore(), degraded
// text on error (never a raw error string - repo Error-Handling rule).

const _DS_CACHE = Object.create(null);     // cacheKey -> response JSON
const _DS_INFLIGHT = Object.create(null);
const _DS_TS = Object.create(null);
const _DS_SIG = Object.create(null);
const _DS_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

// Human labels + display order for the five layers (source-of-truth order
// follows core.draft_score's weights: matchup 30 / synergy 20 / damage 15 /
// scaling 10 / base_wr 25).
const _LAYER_LABEL = {
  matchup: 'Lane matchup',
  synergy: 'Team synergy',
  damage_balance: 'Damage balance',
  scaling: 'Early / late scaling',
  base_wr: 'Champion base WR',
};

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _cacheKey(allyIds, enemyIds, queueIds) {
  const a = (allyIds || []).slice().sort((x, y) => x - y).join(',');
  const e = (enemyIds && enemyIds.length)
    ? (enemyIds).slice().sort((x, y) => x - y).join(',') : '';
  const q = (queueIds && queueIds.length) ? queueIds.join(',') : '';
  return `${a}|${e}|${q}`;
}

// Signature for the sig-dedup gate: score + confidence + each layer's live
// sub_score/contributed so an unchanged payload never rebuilds the DOM.
function _signature(payload) {
  if (!payload || payload.ok === false) return '_empty';
  const layers = (payload.layers || []).map((l) =>
    `${l.name}:${l.contributed ? '1' : '0'}:` +
    `${l.sub_score == null ? '-' : Number(l.sub_score).toFixed(3)}:${l.n | 0}`
  ).join(';');
  return `${Number(payload.score).toFixed(1)}:${payload.confidence}:` +
    `${payload.contributing | 0}:${layers}`;
}

// Score band -> class. The honest band is [42,58]; >52 leans favorable, <48
// leans unfavorable, the middle reads even. A descriptive lean, not a win
// probability.
function _scoreClass(score) {
  const s = Number(score);
  if (!isFinite(s)) return 'ds-dim';
  if (s >= 52) return 'ds-good';
  if (s <= 48) return 'ds-bad';
  return 'ds-even';
}

function _confClass(conf) {
  const c = String(conf || '').toUpperCase();
  if (c === 'HIGH') return 'ds-conf-high';
  if (c === 'LOW') return 'ds-conf-low';
  return 'ds-conf-med';
}

// One layer row. A contributed layer shows its sub_score as a WR% (sub_score
// is 0..1) with the sample n; an inert layer (contributed=false) shows the "-"
// thin sentinel and is muted so the operator sees WHY the band is what it is.
function _layerRow(layer) {
  const name = _LAYER_LABEL[layer.name] || layer.name;
  const wPct = Math.round((Number(layer.weight) || 0) * 100);
  const live = !!layer.contributed && layer.sub_score != null;
  const cls = live ? _scoreClass(Number(layer.sub_score) * 100) : 'ds-dim';
  const val = live ? `${(Number(layer.sub_score) * 100).toFixed(1)}%` : '-';
  const pct = live
    ? Math.max(0, Math.min(100, Number(layer.sub_score) * 100)) : 0;
  const nTxt = live ? `n=${layer.n | 0}` : 'no data';
  return (
    `<div class="ds-layer${live ? '' : ' is-inert'}">` +
      `<div class="ds-layer-name">${_esc(name)}` +
        `<span class="ds-layer-w">${wPct}%</span></div>` +
      `<div class="ds-layer-track"><div class="ds-layer-fill ${cls}" ` +
        `style="width:${pct}%"></div></div>` +
      `<div class="ds-layer-val ${cls}">${val}` +
        `<span class="ds-layer-n">${nTxt}</span></div>` +
    `</div>`
  );
}

// Full card HTML. payload is the backend response.
function draftScoreHtml(payload) {
  if (!payload || payload.ok === false) {
    return '<div class="ds-draft-empty">Draft score unavailable.</div>';
  }
  const score = Number(payload.score);
  const cls = _scoreClass(score);
  const conf = String(payload.confidence || 'LOW').toUpperCase();
  const band = Array.isArray(payload.band) ? payload.band : [42, 58];
  const contributing = payload.contributing | 0;
  const layers = (payload.layers || []).map(_layerRow).join('');
  return (
    `<div class="ds-draft-head">` +
      `<span class="ds-draft-title">DRAFT SCORE</span>` +
      `<span class="ds-draft-score ${cls}">${isFinite(score) ? score.toFixed(1) : '-'}</span>` +
      `<span class="ds-draft-conf ${_confClass(conf)}" ` +
        `title="Confidence tier from the evidence weight behind the score">` +
        `${_esc(conf)}</span>` +
    `</div>` +
    `<div class="ds-draft-layers">${layers}</div>` +
    `<div class="ds-draft-caption">` +
      `${contributing} of ${(payload.layers || []).length} layers contributing ` +
      `over your own game corpus. Honest ${band[0]}-${band[1]} band - a lean, ` +
      `not a win probability; inert layers (e.g. no enemy comp) show "-" ` +
      `and drop out of the blend.` +
    `</div>`
  );
}

// -- fetch / cache -----------------------------------------------------------

export function fetchDraftScore(allyIds, enemyIds, queueIds, onLand) {
  if (!Array.isArray(allyIds) || allyIds.length !== 5) return;
  const key = _cacheKey(allyIds, enemyIds, queueIds);
  const fresh = _DS_CACHE[key] && _DS_TS[key]
    && (Date.now() - _DS_TS[key]) < _DS_TTL_MS;
  if (fresh || _DS_INFLIGHT[key]) return;
  _DS_INFLIGHT[key] = true;
  const params = { ally: allyIds.join(',') };
  if (Array.isArray(enemyIds) && enemyIds.length === 5) {
    params.enemy = enemyIds.join(',');
  }
  if (Array.isArray(queueIds) && queueIds.length) {
    params.queue = queueIds.join(',');
  }
  const qs = new URLSearchParams(params);
  fetch('/api/draft-score?' + qs.toString(), { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _DS_INFLIGHT[key] = false;
      if (data && data.ok !== false) {
        _DS_CACHE[key] = data;
        _DS_TS[key] = Date.now();
        if (typeof onLand === 'function') onLand();
      }
    })
    .catch(() => { _DS_INFLIGHT[key] = false; });
}

export function getCachedDraftScore(allyIds, enemyIds, queueIds) {
  return _DS_CACHE[_cacheKey(allyIds, enemyIds, queueIds)] || null;
}

export function getDraftScoreCacheCount() {
  return Object.keys(_DS_CACHE).length;
}

// Render the draft-score card into the provided element. payload may be null
// on cold-load (keep hidden until the response lands).
export function renderDraftScore(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || '_ds_default';
  const sig = _signature(payload);
  if (_DS_SIG[sigKey] === sig) return;
  _DS_SIG[sigKey] = sig;
  if (!payload || payload.ok === false) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;
  blockEl.innerHTML = draftScoreHtml(payload);
}

export function _resetDraftScore() {
  for (const k of Object.keys(_DS_CACHE)) delete _DS_CACHE[k];
  for (const k of Object.keys(_DS_INFLIGHT)) delete _DS_INFLIGHT[k];
  for (const k of Object.keys(_DS_TS)) delete _DS_TS[k];
  for (const k of Object.keys(_DS_SIG)) delete _DS_SIG[k];
}

export const __test = {
  _cacheKey, _signature, _scoreClass, _confClass, _layerRow, draftScoreHtml,
  _LAYER_LABEL,
};
