// DS action-queue combo simulator (competitor lift #2,
// docs/COMPETITOR_LIFT_2026-05-30.md). Sibling of the cooldown-watch card -
// surfaces a per-hit damage TIMELINE for an ordered cast/attack list the
// operator types ("Q, AA, W, R"). Turns RC's single aggregate burst into a
// calc.gg-style Action Queue: each row is one action with its clock time,
// raw + mitigated damage, and running cumulative total.
//
// Backend wire:
//   GET /api/ds-combo?champion=<id>&level=11&items=<id,..>&seq=Q,AA,W,R
//       &target_armor=&target_mr=&target_max_hp=&target_bonus_hp=&mode=SR
//   Response: {
//     ok, champion, champion_name, level, mode, sequence,
//     hits:[{index, action, ability_key, is_ability, form_name, rank, t,
//            cast_time, cooldown_s, damage_type, raw, mitigated,
//            cumulative, status, note}],
//     totals:{total_raw, total_mitigated, duration_s},
//     notes, count, elapsed_ms, cached
//   }
//
// Discipline: pure ESM, ASCII only, sig-dedup gate, no DOM writes outside
// renderDsCombo(). Mirrors the cooldown_watch.js pattern. The sequence
// input is rendered ONCE per block id; subsequent renders only repaint the
// timeline table so the operator's caret in the input is never clobbered.

const _COMBO_CACHE = Object.create(null);     // cacheKey -> response JSON
const _COMBO_INFLIGHT = Object.create(null);
const _COMBO_TS = Object.create(null);
const _COMBO_SIG = Object.create(null);
const _COMBO_INPUT_DONE = Object.create(null); // blockId -> input rendered
const _COMBO_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

// Per-champion default combos. A small, conventional opener per common
// locked champion; everything else falls back to the generic burst opener.
const _DEFAULT_COMBOS = {
  Lux: "Q,AA,E,R",
  Caitlyn: "Q,AA,W,E,R",
  Ahri: "E,Q,W,R,AA",
  Syndra: "E,Q,W,R",
  Veigar: "E,W,Q,R",
  Annie: "W,Q,R,AA",
  Brand: "W,Q,E,R",
  Xerath: "W,E,Q,R",
  Ezreal: "Q,W,AA,R",
  Jinx: "Q,AA,AA,W,R",
};
const _GENERIC_COMBO = "Q,AA,W,E,R";

function defaultComboFor(champion) {
  return _DEFAULT_COMBOS[champion] || _GENERIC_COMBO;
}

function _cacheKey(champion, level, items, seq, ta, tm, mode) {
  return [
    champion || "",
    level || 0,
    (items || []).slice().join("."),
    (seq || []).join(","),
    ta || 0,
    tm || 0,
    mode || "SR",
  ].join("|");
}

// Fetch the timeline for one (champion, level, seq, target) tuple. onLand
// fires once the response lands so the caller can repaint.
export function fetchDsCombo(opts, onLand) {
  if (!opts || !opts.champion) return;
  const seq = Array.isArray(opts.seq) ? opts.seq : [];
  if (seq.length < 1) return;
  const champion = opts.champion;
  const level = opts.level || 11;
  const items = Array.isArray(opts.items) ? opts.items : [];
  const ta = +opts.target_armor || 0;
  const tm = +opts.target_mr || 0;
  const mode = opts.mode || "SR";
  const key = _cacheKey(champion, level, items, seq, ta, tm, mode);
  const fresh = _COMBO_CACHE[key] && _COMBO_TS[key]
                && (Date.now() - _COMBO_TS[key]) < _COMBO_TTL_MS;
  if (fresh || _COMBO_INFLIGHT[key]) return;
  _COMBO_INFLIGHT[key] = true;
  const params = new URLSearchParams({
    champion: champion,
    level: String(level),
    seq: seq.join(","),
    target_armor: String(ta),
    target_mr: String(tm),
    mode: mode,
  });
  if (items.length) params.set("items", items.join(","));
  if (+opts.target_max_hp) params.set("target_max_hp", String(+opts.target_max_hp));
  if (+opts.target_bonus_hp) {
    params.set("target_bonus_hp", String(+opts.target_bonus_hp));
  }
  fetch("/api/ds-combo?" + params.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _COMBO_INFLIGHT[key] = false;
      if (data) {
        _COMBO_CACHE[key] = data;
        _COMBO_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _COMBO_INFLIGHT[key] = false; });
}

export function getCachedDsCombo(opts) {
  if (!opts || !opts.champion) return null;
  const key = _cacheKey(
    opts.champion, opts.level || 11,
    Array.isArray(opts.items) ? opts.items : [],
    Array.isArray(opts.seq) ? opts.seq : [],
    +opts.target_armor || 0, +opts.target_mr || 0, opts.mode || "SR",
  );
  return _COMBO_CACHE[key] || null;
}

export function getDsComboCacheCount() {
  return Object.keys(_COMBO_CACHE).length;
}

// Parse a raw "Q, AA, w,r" string into clean uppercase tokens.
export function parseSeqInput(raw) {
  if (!raw) return [];
  return String(raw)
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter((s) => s.length > 0);
}

function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  const hits = Array.isArray(payload.hits) ? payload.hits : [];
  const tot = payload.totals || {};
  return hits
    .map((h) => `${h.action}:${h.status}:${(+h.cumulative || 0)}`)
    .join("|") + `#${+tot.total_mitigated || 0}` || "_nohits";
}

function _statusBadge(hit) {
  return hit.status === "on_cooldown" ? "CD" : "";
}

// Build one timeline row.
function _rowHtml(hit) {
  const onCd = hit.status === "on_cooldown";
  const label = hit.is_ability
    ? `${String(hit.action || "")}`
    : "AA";
  const name = hit.form_name && hit.form_name !== "Auto"
    ? String(hit.form_name) : "";
  const raw = (+hit.raw || 0).toFixed(0);
  const mit = (+hit.mitigated || 0).toFixed(0);
  const cum = (+hit.cumulative || 0).toFixed(0);
  const t = (+hit.t || 0).toFixed(2);
  const badge = _statusBadge(hit);
  return (
    `<div class="dscombo-row"${onCd ? ' data-dscombo-cd="1"' : ""}>`
    + `<span class="dscombo-t">${t}s</span>`
    + `<span class="dscombo-act">`
    + `<span class="dscombo-slot">${label}</span>`
    + (name ? `<span class="dscombo-name">${name}</span>` : "")
    + (badge ? `<span class="dscombo-badge">${badge}</span>` : "")
    + `</span>`
    + `<span class="dscombo-raw">${raw}</span>`
    + `<span class="dscombo-mit">${mit}</span>`
    + `<span class="dscombo-cum">${cum}</span>`
    + `</div>`
  );
}

function _tableHtml(payload) {
  const hits = Array.isArray(payload.hits) ? payload.hits : [];
  const tot = payload.totals || {};
  const head = (
    `<div class="dscombo-row dscombo-head-row">`
    + `<span class="dscombo-t">t</span>`
    + `<span class="dscombo-act">action</span>`
    + `<span class="dscombo-raw">raw</span>`
    + `<span class="dscombo-mit">hit</span>`
    + `<span class="dscombo-cum">total</span>`
    + `</div>`
  );
  const rows = hits.map(_rowHtml).join("");
  const dur = (+tot.duration_s || 0).toFixed(2);
  const totMit = (+tot.total_mitigated || 0).toFixed(0);
  const totRaw = (+tot.total_raw || 0).toFixed(0);
  const foot = (
    `<div class="dscombo-foot">`
    + `<span class="dscombo-foot-dur">${dur}s</span>`
    + `<span class="dscombo-foot-tot">`
    + `${totMit} dmg <span class="dscombo-foot-raw">(${totRaw} raw)</span>`
    + `</span>`
    + `</div>`
  );
  return head + rows + foot;
}

// Render the combo panel into the provided element. ``payload`` is the
// backend response (may be null on cold load). ``opts`` carries the
// champion + current seq string so the input box can be (re)seeded. The
// input element is created once per block id and never repainted, so the
// operator's caret survives timeline repaints.
export function renderDsCombo(blockEl, payload, opts) {
  if (!blockEl) return;
  const o = opts || {};
  const sigKey = blockEl.id || "_dscombo_default";

  // First paint for this block: build the input row + an empty timeline
  // container. Wiring of the input is left to the host (champ_select.js)
  // which owns the re-fetch cadence; this panel just renders.
  if (!_COMBO_INPUT_DONE[sigKey]) {
    const seqStr = o.seqStr || defaultComboFor(o.champion || "");
    blockEl.innerHTML = (
      `<div class="dscombo-head">`
      + `<span class="dscombo-head-title">Combo timeline</span>`
      + `<span class="dscombo-head-sub">type an action queue: Q, AA, W, R</span>`
      + `</div>`
      + `<div class="dscombo-input-row">`
      + `<input type="text" class="dscombo-input" id="${sigKey}-input" `
      + `value="${seqStr}" spellcheck="false" `
      + `aria-label="combo action queue" />`
      + `</div>`
      + `<div class="dscombo-table" id="${sigKey}-table"></div>`
    );
    _COMBO_INPUT_DONE[sigKey] = true;
    _COMBO_SIG[sigKey] = null;
  }

  const tableEl = blockEl.querySelector(".dscombo-table");
  if (!tableEl) return;

  const sig = _signature(payload);
  if (_COMBO_SIG[sigKey] === sig) return;
  _COMBO_SIG[sigKey] = sig;

  if (!payload || !payload.ok) {
    tableEl.innerHTML = (
      `<div class="dscombo-empty">`
      + (payload && payload.reason === "empty_sequence"
        ? "enter an action queue above"
        : "no timeline yet")
      + `</div>`
    );
    return;
  }
  const hits = Array.isArray(payload.hits) ? payload.hits : [];
  if (!hits.length) {
    tableEl.innerHTML = (
      `<div class="dscombo-empty">no resolvable actions</div>`
    );
    return;
  }
  tableEl.innerHTML = _tableHtml(payload);
}

// Reset helper for tests (clears in-memory cache + sig stamps + input flags).
export function _resetDsCombo() {
  for (const k of Object.keys(_COMBO_CACHE))     delete _COMBO_CACHE[k];
  for (const k of Object.keys(_COMBO_INFLIGHT))  delete _COMBO_INFLIGHT[k];
  for (const k of Object.keys(_COMBO_TS))        delete _COMBO_TS[k];
  for (const k of Object.keys(_COMBO_SIG))       delete _COMBO_SIG[k];
  for (const k of Object.keys(_COMBO_INPUT_DONE)) delete _COMBO_INPUT_DONE[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _rowHtml,
  parseSeqInput,
  defaultComboFor,
  _COMBO_TTL_MS,
};
