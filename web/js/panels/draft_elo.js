// Draft Elo chip panel (UX wave 2, 2026-05-20).
//
// Renders a small inline chip with the team-vs-team predicted WR + the
// rating delta + a sample-density indicator. Backend wire:
// GET /api/draft-elo?ally=...&enemy=...[&breakdown=1]
// (dashboard/routes_draft_elo.py).
//
// Designed as a sidecar to spike_curve.js - it answers a different
// question (draft-strength prior from match history, not power-curve
// time-series from DS engine math). Together they read for "the team
// you drafted" + "the team's per-minute combat strength".
//
// Per-row contribution hover strip (2026-05-20 BACKLOG/ROADMAP 109(b),
// Draft Tool L pair-list + Diff15 pattern): on hover of the chip the
// overlay renders the top-3 pair Elo deltas (which ally-pair /
// enemy-pair / matchup contributed most to predicted WR), labelled by
// kind + champ portraits + signed delta + sample density. The overlay
// is HOVER-ONLY (CSS :hover toggles display:block) - NEVER persistent.
// Field consensus per the multi-agent research wave is that persistent
// sidebars clutter at 1920x1080.
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
    ally:     allyIds.join(","),
    enemy:    enemyIds.join(","),
    breakdown: "1",
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
  // Contribution fingerprint is the rounded sum of |delta|s + the
  // count - cheap enough to recompute each render and stable enough
  // that the sig-dedup gate skips the overlay rebuild when the
  // backend payload has not actually changed.
  const tc = Array.isArray(payload.top_contributions)
              ? payload.top_contributions : [];
  const tcSig = tc.length
                + ":"
                + Math.round(tc.reduce((acc, x) => acc + Math.abs(+x.delta || 0), 0));
  return [
    Math.round((payload.predicted_wr || 0) * 1000),
    Math.round(payload.team_score || 0),
    (payload.sample || {}).min_solo | 0,
    (payload.sample || {}).min_pair | 0,
    tcSig,
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

// Pluggable champion-slug lookup. The frontend calls renderDraftElo
// after the items_index.js CHAMPS map is hydrated, but tests + headless
// fixtures need a way to inject a lookup that does not depend on the
// global. The default does a defensive global probe via window.CHAMPS;
// real callers can pass an explicit ``championSlugLookup``.
function _defaultSlugLookup(cid) {
  if (typeof window === "undefined") return "";
  const CHAMPS = window.CHAMPS || (window.RC && window.RC.CHAMPS) || null;
  if (!CHAMPS || !CHAMPS.byId) return "";
  return CHAMPS.byId[String(cid)] || "";
}

function _defaultVersionLookup() {
  if (typeof window === "undefined") return "16.10.1";
  const CHAMPS = window.CHAMPS || (window.RC && window.RC.CHAMPS) || null;
  return (CHAMPS && CHAMPS.version) || "16.10.1";
}

// One contribution row in the hover overlay. ``c`` is the
// Contribution dict from /api/draft-elo (kind, a, b, delta, n). The
// signed delta sign drives the +/-arrow + color class:
//   delta > 0  -> helps ally (green up-arrow)
//   delta < 0  -> hurts ally (red down-arrow)
// abs(delta) is shown to the user, rounded to integer rating points.
function _contribRow(c, slugLookup, ver) {
  const delta = +c.delta || 0;
  const n = c.n | 0;
  const sign = delta >= 0 ? "+" : "-";
  const cls = delta >= 0 ? "de-contrib-up" : "de-contrib-down";
  const kindLabel = {
    "ally-pair":  "ALLY",
    "enemy-pair": "ENEMY",
    "matchup":    "VS",
  }[c.kind] || c.kind;
  const slugA = slugLookup(c.a);
  const slugB = slugLookup(c.b);
  const portA = slugA
                ? `<img class="de-portrait" src="/data/ddragon/${ver}/img/champion/${slugA}.png" alt="${slugA}" onerror="this.style.display='none'">`
                : `<span class="de-portrait-fallback">${c.a}</span>`;
  const portB = slugB
                ? `<img class="de-portrait" src="/data/ddragon/${ver}/img/champion/${slugB}.png" alt="${slugB}" onerror="this.style.display='none'">`
                : `<span class="de-portrait-fallback">${c.b}</span>`;
  return (
    `<div class="de-contrib-row" data-kind="${c.kind}">`
    + `<span class="de-contrib-kind">${kindLabel}</span>`
    + portA + portB
    + `<span class="de-contrib-delta ${cls}">${sign}${Math.round(Math.abs(delta))}</span>`
    + `<span class="de-contrib-n" title="${n} games">n=${n}</span>`
    + `</div>`
  );
}

function _renderOverlay(contribs, slugLookup, ver) {
  if (!Array.isArray(contribs) || contribs.length === 0) return "";
  const rows = contribs.map((c) => _contribRow(c, slugLookup, ver)).join("");
  return (
    `<div class="draft-elo-contributions" data-de-contrib-state="ready">`
    + `<div class="de-contrib-head">TOP CONTRIBUTIONS</div>`
    + rows
    + `</div>`
  );
}

export function renderDraftElo(parentEl, payload, opts) {
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

  // Test/inject hooks: lets headless fixtures bypass the window.CHAMPS
  // global without monkey-patching it.
  const slugLookup = (opts && opts.championSlugLookup)
                     || _defaultSlugLookup;
  const versionLookup = (opts && opts.versionLookup)
                        || _defaultVersionLookup;
  const ver = versionLookup();

  parentEl.dataset.deState = "ready";
  parentEl.dataset.deBand = band;
  parentEl.dataset.deSampleBand = sBand;
  const overlayHtml = _renderOverlay(
    payload.top_contributions || [],
    slugLookup,
    ver,
  );
  parentEl.innerHTML = (
    `<span class="de-label">DRAFT</span>`
    + `<span class="de-wr de-band-${band}">${pct}%</span>`
    + `<span class="de-score">${scoreStr}</span>`
    + `<span class="de-sample de-sample-${sBand}" `
    + `title="solo min ${minSolo}, pair min ${minPair} - confidence ${sBand}">`
    + `n=${minSolo}/${minPair}</span>`
    + overlayHtml
  );
}

export function _resetDraftElo() {
  for (const k of Object.keys(_DE_CACHE)) delete _DE_CACHE[k];
  for (const k of Object.keys(_DE_INFLIGHT)) delete _DE_INFLIGHT[k];
  for (const k of Object.keys(_DE_TS)) delete _DE_TS[k];
  for (const k of Object.keys(_DE_SIG)) delete _DE_SIG[k];
}

// 2026-05-20 UI polish: ESC dismisses any visible
// .draft-elo-contributions overlay. The CSS contract is hover-only
// per HoverOnlyContractTests in tests/test_draft_elo_panel_dom.py
// (no click-to-pin, no pinned class, no click-event bindings;
// pointer-events:none on overlay so it cannot be clicked anyway).
// ESC is an orthogonal escape hatch for the operator who hovered
// over the chip while reading the rest of the page and wants the
// overlay gone without moving the cursor.
//
// Mechanism: ESC walks every .draft-elo-contributions and sets inline
// style.display = "none". Inline style wins over the :hover stylesheet
// rule via the cascade. On the chip's next mouseleave we clear the
// inline style so the hover-to-show contract resumes on the next
// hover cycle. This adds no click bindings, no pinned class, and
// no persistent JS state - the existing contract guards stay green.
if (typeof document !== "undefined" && !document.__deEscBound) {
  document.__deEscBound = true;
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" && e.code !== "Escape") return;
    const overlays = document.querySelectorAll(".draft-elo-contributions");
    overlays.forEach((o) => {
      if (getComputedStyle(o).display === "none") return;
      o.style.display = "none";
      // Clear the inline override on mouseleave of the parent chip so
      // the next hover cycle reveals the overlay again. one-shot.
      const chip = o.closest(".draft-elo-chip");
      if (chip) {
        const clear = () => {
          o.style.display = "";
          chip.removeEventListener("mouseleave", clear);
        };
        chip.addEventListener("mouseleave", clear);
      }
    });
  });
}

export const __test = {
  _cacheKey,
  _signature,
  _wrBand,
  _sampleBand,
  _DE_TTL_MS,
  _contribRow,
  _renderOverlay,
};
