// Playstyle-labels card (Session view). Renders core.playstyle_labels'
// deterministic per-champion playstyle fingerprint over the operator's OWN
// rewind corpus: for each champion with enough games, a set of SELF-RELATIVE
// verdict labels (dies more/less than your own norm, kill-focused,
// team-involved, consistent / coinflip) alongside the honest WR. Computed
// entirely over the operator's own games (no global / Riot / Claude
// dependency) - an observation, not causal advice; the Haiku-to-ZERO north
// star.
//
// Backend wire:
//   GET /api/playstyle-labels[?queue=<id,..>][&min_games=N]
//   Response: { ok, n, overall_wr, baseline:{kills,deaths,assists,kp,kda_ratio},
//     champions:[{champion_id, champion_name, games, wins, wr, kda_cv,
//       labels:[{tag, verdict, basis, value}, ...]}, ...] }
//
// Only champions that earned at least one label surface (the interesting
// ones); the card caps the list and notes the cap. Champions with no labels
// are your baseline-normal picks and are omitted to keep the card glanceable.
//
// Discipline mirrors session_hygiene.js / duration_winrate.js: pure ESM, ASCII
// only, single cache + TTL, inflight guard, sig-dedup, no DOM writes outside
// renderPlaystyleLabels(), degraded text on error.

const _MOUNT = 'playstyle-labels-card';
const _TTL_MS = 5 * 60 * 1000;
const _MAX_ROWS = 12;   // keep the card glanceable; note when truncated
let _cache = null;
let _ts = 0;
let _inflight = false;
let _sig = '';

// Verdict tags -> a good/bad/neutral lean for the chip color. These are
// self-relative observations, so "kill-focused" is not intrinsically good;
// the coloring only flags the direction relative to the player's own norm.
const _TAG_TONE = {
  'death-averse': 'pl-good',
  'death-prone': 'pl-bad',
  'kill-focused': 'pl-good',
  'low-kill': 'pl-dim',
  'team-involved': 'pl-good',
  'solo-leaning': 'pl-dim',
  'consistent': 'pl-good',
  'high-variance': 'pl-bad',
};

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _tagTone(tag) {
  return _TAG_TONE[String(tag || '')] || 'pl-dim';
}

function _wrClass(wr) {
  const w = Number(wr);
  if (!isFinite(w)) return 'pl-dim';
  if (w >= 0.5) return 'pl-good';
  return 'pl-bad';
}

function _labelChip(l) {
  const tag = _esc(l.tag);
  const tip = l.verdict ? ` title="${_esc(l.verdict)}"` : '';
  return `<span class="pl-chip ${_tagTone(l.tag)}"${tip}>${tag}</span>`;
}

function _champRow(c) {
  const chips = (c.labels || []).map(_labelChip).join('');
  const wr = c.wr != null ? `${(Number(c.wr) * 100).toFixed(0)}%` : '-';
  return (
    `<div class="pl-row">` +
      `<div class="pl-champ">${_esc(c.champion_name || c.champion_id)}` +
        `<span class="pl-games">${c.games | 0}g</span></div>` +
      `<div class="pl-wr ${_wrClass(c.wr)}">${wr}</div>` +
      `<div class="pl-chips">${chips}</div>` +
    `</div>`
  );
}

function playstyleLabelsHtml(payload) {
  if (!payload || payload.ok === false) {
    return '<div class="pl-empty">Playstyle labels unavailable.</div>';
  }
  const labeled = (payload.champions || []).filter(
    (c) => c.labels && c.labels.length);
  labeled.sort((a, b) => (b.games | 0) - (a.games | 0));
  const shown = labeled.slice(0, _MAX_ROWS);
  const b = payload.baseline || {};
  const baseChip = (b.kda_ratio != null)
    ? `<span class="pl-baseline" title="Your cross-champion averages - the ` +
      `bar each label is measured against">your norm: ${(+b.kills).toFixed(1)}/` +
      `${(+b.deaths).toFixed(1)}/${(+b.assists).toFixed(1)} ` +
      `(${(+b.kda_ratio).toFixed(2)} KDA)</span>`
    : '';
  if (!shown.length) {
    return `<div class="session-card-head">PLAYSTYLE ${baseChip}</div>` +
      `<div class="pl-empty">No champion stands out from your own norm yet ` +
      `(need enough games per champ). "-" until the sample clears.</div>`;
  }
  const rows = shown.map(_champRow).join('');
  const more = labeled.length > shown.length
    ? `<div class="pl-more">+ ${labeled.length - shown.length} more labeled ` +
      `champions not shown</div>` : '';
  return (
    `<div class="session-card-head">PLAYSTYLE ${baseChip}</div>` +
    `<div class="pl-rows">${rows}</div>${more}` +
    `<div class="pl-caption">Self-relative labels over your own games ` +
    `(n=${payload.n | 0}) - each champ vs YOUR cross-champion norm, not the ` +
    `global meta. An observation, not advice.</div>`
  );
}

function _signature(payload) {
  if (!payload || payload.ok === false) return '_empty';
  const labeled = (payload.champions || []).filter(
    (c) => c.labels && c.labels.length);
  const s = labeled.map((c) =>
    `${c.champion_id}:${(c.labels || []).map((l) => l.tag).join(',')}`
  ).join(';');
  return `${payload.n | 0}:${labeled.length}:${s}`;
}

export function renderPlaystyleLabels() {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const now = Date.now();
  if (_cache && (now - _ts) < _TTL_MS) { _paint(mount, _cache); return; }
  if (_inflight) return;
  _inflight = true;
  fetch('/api/playstyle-labels', { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
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
  mount.innerHTML = playstyleLabelsHtml(data);
}

function _degraded(mount) {
  _sig = '';
  mount.hidden = false;
  mount.innerHTML = '<div class="session-card-head">PLAYSTYLE</div>' +
    '<div class="pl-empty">Playstyle labels unavailable.</div>';
}

export function _resetPlaystyleLabels() {
  _cache = null; _ts = 0; _inflight = false; _sig = '';
}

export const __test = {
  _tagTone, _wrClass, _labelChip, _champRow, playstyleLabelsHtml, _signature,
  _MAX_ROWS, _TAG_TONE,
};
