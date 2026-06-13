// HURTS-THEM / HELPS-US ban-suggest toggle panel (item 109 carry-forward (a)).
//
// Surfaces the dual-score ban suggestion shipped 2026-05-20 commit 6e7b7e5
// (dashboard/routes_ban_suggest.py) as an explicit logic chip + sortable
// candidate list. Every other tool (Aggregator C / Overlay App E / Overlay App F /
// Draft Tool L / Draft Tool Z8) silently picks one logic and never tells the
// user which - this panel makes the choice explicit.
//
// Backend wire:
//   GET /api/ban-suggest?ally=A,A,A&enemy=E,E&candidates=C,C,C[&queue=Q]
//   Response: { ok, ally, enemy, candidates: [
//     { champ_id, solo_rating, solo_n,
//       hurts_them_score, helps_us_score,
//       min_solo_n, min_pair_n }
//   ], queue_ids, cached, elapsed_ms }
//
// Toggle state persists across re-renders via localStorage so the
// operator's preferred logic survives champ-select refresh + the next
// session. The mode chip remains visible at ALL TIMES during ban phase.
//
// Candidate pool source: the existing global-top-bans list
// (/api/champ-select/ban-suggestions) gives display name + icon URL +
// champion id for ~18 candidates. We dual-score those.
//
// Discipline: pure ESM module, ASCII only, sig-dedup gate, no DOM
// writes outside renderBanSuggestToggle().

const _BS_CACHE = Object.create(null);     // cacheKey -> response JSON
const _BS_INFLIGHT = Object.create(null);
const _BS_TS = Object.create(null);
const _BS_SIG = Object.create(null);
const _BS_TTL_MS = 5 * 60 * 1000;          // matches backend cache TTL

const _BS_MODE_KEY = "rc-cs-bansugg-mode"; // localStorage key
const _BS_VALID_MODES = ["hurts_them", "helps_us"];

// HTML-escape the champion display name before it lands in innerHTML /
// attribute context. Champion names carry apostrophes (Kai'Sa, Cho'Gath,
// Vel'Koz) and the meta name is not a trusted-markup source.
function _escHtml(s) {
  const div = document.createElement("div");
  div.textContent = String(s == null ? "" : s);
  return div.innerHTML;
}

function _cacheKey(allyIds, enemyIds, candidateIds, queue) {
  const a = (allyIds || []).slice().sort((x, y) => x - y).join(",");
  const e = (enemyIds || []).slice().sort((x, y) => x - y).join(",");
  const c = (candidateIds || []).slice().sort((x, y) => x - y).join(",");
  const q = (queue == null || queue === "") ? "" : String(queue);
  return `${a}|${e}|${c}|${q}`;
}

export function getBanSuggestMode() {
  try {
    const v = localStorage.getItem(_BS_MODE_KEY) || "";
    if (_BS_VALID_MODES.indexOf(v) >= 0) return v;
  } catch (_) {}
  return "hurts_them";
}

export function setBanSuggestMode(mode) {
  if (_BS_VALID_MODES.indexOf(mode) < 0) return;
  try { localStorage.setItem(_BS_MODE_KEY, mode); } catch (_) {}
}

export function fetchBanSuggest(allyIds, enemyIds, candidateIds, queue, onLand) {
  if (!Array.isArray(allyIds) || allyIds.length < 1) return;
  if (!Array.isArray(candidateIds) || candidateIds.length < 1) return;
  const key = _cacheKey(allyIds, enemyIds, candidateIds, queue);
  const fresh = _BS_CACHE[key] && _BS_TS[key]
                && (Date.now() - _BS_TS[key]) < _BS_TTL_MS;
  if (fresh || _BS_INFLIGHT[key]) return;
  _BS_INFLIGHT[key] = true;
  const qs = new URLSearchParams({
    ally:       allyIds.join(","),
    enemy:      (enemyIds || []).join(","),
    candidates: candidateIds.join(","),
  });
  if (queue) qs.set("queue", String(queue));
  fetch("/api/ban-suggest?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _BS_INFLIGHT[key] = false;
      if (data && data.ok) {
        _BS_CACHE[key] = data;
        _BS_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _BS_INFLIGHT[key] = false; });
}

export function getCachedBanSuggest(allyIds, enemyIds, candidateIds, queue) {
  return _BS_CACHE[_cacheKey(allyIds, enemyIds, candidateIds, queue)] || null;
}

export function getBanSuggestCacheCount() {
  return Object.keys(_BS_CACHE).length;
}

function _ratingBand(rating) {
  // -150..+150 typical range. Strong=>red, weak=>green. Symmetric
  // (large absolute score = strong signal regardless of mode).
  if (rating >= 50)  return "red";
  if (rating >= 0)   return "amber";
  return "green";
}

function _confidenceBand(soloN, pairN) {
  if (soloN < 5)  return "low";
  if (pairN < 3)  return "low";
  if (soloN < 20) return "mid";
  return "high";
}

function _scoreFor(cand, mode) {
  if (mode === "helps_us") return +cand.helps_us_score || 0;
  return +cand.hurts_them_score || 0;
}

function _otherScoreFor(cand, mode) {
  if (mode === "helps_us") return +cand.hurts_them_score || 0;
  return +cand.helps_us_score || 0;
}

function _signature(payload, mode) {
  if (!payload || !payload.ok || !Array.isArray(payload.candidates)) {
    return `${mode}:_empty`;
  }
  const cands = payload.candidates
    .slice()
    .sort((a, b) => _scoreFor(b, mode) - _scoreFor(a, mode))
    .slice(0, 8)
    .map((c) => [
      c.champ_id | 0,
      Math.round(_scoreFor(c, mode)),
      c.min_solo_n | 0,
    ].join(":"))
    .join("|");
  return `${mode}:${cands}`;
}

// Render the mode toggle chip into the provided element. Calls
// onModeChange(newMode) when the operator clicks the other side.
export function renderBanSuggestModeChip(chipEl, onModeChange) {
  if (!chipEl) return;
  const mode = getBanSuggestMode();
  chipEl.dataset.bsMode = mode;
  chipEl.innerHTML = (
    `<button type="button" class="bs-mode-opt"`
    + ` data-bs-mode="hurts_them"`
    + ` data-bs-active="${mode === "hurts_them" ? "1" : "0"}">`
    + `<span class="bs-mode-label">HURTS THEM</span>`
    + `<span class="bs-mode-sub">strong vs us</span>`
    + `</button>`
    + `<button type="button" class="bs-mode-opt"`
    + ` data-bs-mode="helps_us"`
    + ` data-bs-active="${mode === "helps_us" ? "1" : "0"}">`
    + `<span class="bs-mode-label">HELPS US</span>`
    + `<span class="bs-mode-sub">strong with us</span>`
    + `</button>`
  );
  chipEl.querySelectorAll(".bs-mode-opt").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = btn.dataset.bsMode;
      if (next === getBanSuggestMode()) return;
      setBanSuggestMode(next);
      if (typeof onModeChange === "function") onModeChange(next);
    });
  });
}

// Render the sortable candidate list into the provided element.
// Each row: portrait + name + active-mode rating (band-colored) +
// other-mode rating in muted text + n= sample-density indicator.
// candidatesMeta: array of { champId, name, icon } - used for display
// fallback when the backend payload lacks names.
export function renderBanSuggestList(listEl, payload, candidatesMeta) {
  if (!listEl) return;
  const mode = getBanSuggestMode();
  const sigKey = listEl.id || "_bs_default";
  const sig = _signature(payload, mode);
  if (_BS_SIG[sigKey] === sig) return;
  _BS_SIG[sigKey] = sig;

  if (!payload || !payload.ok || !Array.isArray(payload.candidates)
      || payload.candidates.length === 0) {
    listEl.dataset.bsState = "empty";
    listEl.innerHTML = '<div class="bs-empty">loading ban-suggest scores...</div>';
    return;
  }

  const metaById = Object.create(null);
  (candidatesMeta || []).forEach((m) => {
    if (m && m.champId) metaById[m.champId | 0] = m;
  });

  const sorted = payload.candidates.slice().sort(
    (a, b) => _scoreFor(b, mode) - _scoreFor(a, mode));
  const top = sorted.slice(0, 8);

  listEl.dataset.bsState = "ready";
  listEl.dataset.bsMode = mode;
  listEl.innerHTML = top.map((cand) => {
    const cid = cand.champ_id | 0;
    const meta = metaById[cid] || {};
    const name = meta.name || ("#" + cid);
    const icon = meta.icon || "";
    const active = _scoreFor(cand, mode);
    const other  = _otherScoreFor(cand, mode);
    const band = _ratingBand(active);
    const conf = _confidenceBand(cand.min_solo_n | 0, cand.min_pair_n | 0);
    const activeStr = (active >= 0 ? "+" : "") + Math.round(active);
    const otherStr  = (other  >= 0 ? "+" : "") + Math.round(other);
    const otherLabel = mode === "hurts_them" ? "helps us" : "hurts them";
    const safeName = _escHtml(name);
    const iconHtml = icon
      ? `<img src="${_escHtml(icon)}" alt="${safeName}" onerror="this.style.display='none'">`
      : "";
    return (
      `<div class="bs-row"`
      + ` data-champ-id="${cid}"`
      + ` data-bs-band="${band}"`
      + ` data-bs-conf="${conf}"`
      + ` title="Click to suggest ban: ${safeName}">`
        + `<div class="bs-row-icon">${iconHtml}</div>`
        + `<div class="bs-row-name">${safeName}</div>`
        + `<div class="bs-row-active bs-band-${band}">${activeStr}</div>`
        + `<div class="bs-row-other" title="${otherLabel}">${otherStr}</div>`
        + `<div class="bs-row-sample bs-sample-${conf}"`
        + ` title="solo n=${cand.min_solo_n | 0}, pair n=${cand.min_pair_n | 0}">`
        + `n=${cand.min_solo_n | 0}/${cand.min_pair_n | 0}</div>`
      + `</div>`
    );
  }).join("");

  // Click-to-ban wiring - mirrors the legacy global-top-bans card click.
  listEl.querySelectorAll(".bs-row").forEach((row) => {
    row.addEventListener("click", () => {
      const cid = parseInt(row.dataset.champId, 10) | 0;
      if (cid <= 0) return;
      fetch("/api/lcu-cmd", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cmd: "set_ban_intent", championId: cid }),
      }).catch(() => null);
    });
  });
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetBanSuggest() {
  for (const k of Object.keys(_BS_CACHE))    delete _BS_CACHE[k];
  for (const k of Object.keys(_BS_INFLIGHT)) delete _BS_INFLIGHT[k];
  for (const k of Object.keys(_BS_TS))       delete _BS_TS[k];
  for (const k of Object.keys(_BS_SIG))      delete _BS_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _ratingBand,
  _confidenceBand,
  _scoreFor,
  _BS_MODE_KEY,
  _BS_VALID_MODES,
  _BS_TTL_MS,
};
