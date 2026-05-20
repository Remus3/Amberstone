// Draft Elo chip panel (UX wave 2, 2026-05-20).
//
// Renders a small inline chip with the team-vs-team predicted WR + the
// rating delta + a sample-density indicator. Backend wire:
// GET /api/draft-elo?ally=...&enemy=... (dashboard/routes_draft_elo.py).
//
// Designed as a sidecar to spike_curve.js - it answers a different
// question (draft-strength prior from match history, not power-curve
// time-series from DS engine math). Together they read for "the team
// you drafted" + "the team's per-minute combat strength".
//
// Discipline: pure render, sig-dedup gate, ASCII only.

const _DE_CACHE = Object.create(null); // cacheKey -> response JSON
const _DE_INFLIGHT = Object.create(null);
const _DE_SIG = Object.create(null);
const _DE_TS = Object.create(null); // cacheKey -> Date.now()
const _DE_TTL_MS = 5 * 60 * 1000; // matches backend cache TTL

function _cacheKey(allyIds, enemyIds, queue) {
  const a = (allyIds || []).slice().sort().join(",");
  const e = (enemyIds || []).slice().sort().join(",");
  const q = (queue == null || queue === "") ? "" : String(queue);
  return `${a}|${e}|${q}`;
}

export function fetchDraftElo(allyIds, enemyIds, queue, onLand) {
  if (!Array.isArray(allyIds) || allyIds.length !== 5) return;
  if (!Array.isArray(enemyIds) || enemyIds.length !== 5) return;
  const key = _cacheKey(allyIds, enemyIds, queue);
  const fresh = _DE_CACHE[key] && _DE_TS[key]
                && (Date.now() - _DE_TS[key]) < _DE_TTL_MS;
  if (fresh || _DE_INFLIGHT[key]) return;
  _DE_INFLIGHT[key] = true;
  const qs = new URLSearchParams({
    ally:  allyIds.join(","),
    enemy: enemyIds.join(","),
  });
  if (queue) qs.set("queue", String(queue));
  fetch("/api/draft-elo?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _DE_INFLIGHT[key] = false;
      if (data && data.ok) {
        _DE_CACHE[key] = data;
        _DE_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _DE_INFLIGHT[key] = false; });
}

export function getCachedDraftElo(allyIds, enemyIds, queue) {
  return _DE_CACHE[_cacheKey(allyIds, enemyIds, queue)] || null;
}

function _signature(payload) {
  if (!payload || !payload.ok) return "_empty";
  return [
    Math.round((payload.predicted_wr || 0) * 1000),
    Math.round(payload.team_score || 0),
    (payload.sample || {}).min_solo | 0,
    (payload.sample || {}).min_pair | 0,
  ].join("|");
}

function _wrBand(wr) {
  // Three-tier color band: red <0.42, amber 0.42..0.58, green >0.58
  // (mirrors the personal_vs threat band thresholds for visual
  // consistency).
  if (wr < 0.42) return "red";
  if (wr > 0.58) return "green";
  return "amber";
}

function _sampleBand(minSolo, minPair) {
  // Low confidence if any solo champ has <10 games OR any pair has 0.
  if (minSolo < 10) return "low";
  if (minPair < 5)  return "low";
  if (minSolo < 30) return "mid";
  return "high";
}

export function renderDraftElo(parentEl, payload) {
  if (!parentEl) return;
  const sigKey = parentEl.id || "_de_default";
  const sig = _signature(payload);
  if (_DE_SIG[sigKey] === sig) return;
  _DE_SIG[sigKey] = sig;

  if (!payload || !payload.ok) {
    parentEl.dataset.deState = "empty";
    parentEl.innerHTML = '<div class="de-empty">no draft prior</div>';
    return;
  }

  const wr = +payload.predicted_wr || 0.5;
  const score = +payload.team_score || 0;
  const sample = payload.sample || {};
  const minSolo = sample.min_solo | 0;
  const minPair = sample.min_pair | 0;
  const band = _wrBand(wr);
  const sBand = _sampleBand(minSolo, minPair);

  const pct = Math.round(wr * 100);
  const scoreStr = (score >= 0 ? "+" : "") + Math.round(score);

  parentEl.dataset.deState = "ready";
  parentEl.dataset.deBand = band;
  parentEl.dataset.deSampleBand = sBand;
  parentEl.innerHTML = (
    `<span class="de-label">DRAFT</span>`
    + `<span class="de-wr de-band-${band}">${pct}%</span>`
    + `<span class="de-score">${scoreStr}</span>`
    + `<span class="de-sample de-sample-${sBand}" `
    + `title="solo min ${minSolo}, pair min ${minPair} - confidence ${sBand}">`
    + `n=${minSolo}/${minPair}</span>`
  );
}

export function _resetDraftElo() {
  for (const k of Object.keys(_DE_CACHE)) delete _DE_CACHE[k];
  for (const k of Object.keys(_DE_INFLIGHT)) delete _DE_INFLIGHT[k];
  for (const k of Object.keys(_DE_TS)) delete _DE_TS[k];
  for (const k of Object.keys(_DE_SIG)) delete _DE_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _wrBand,
  _sampleBand,
  _DE_TTL_MS,
};
