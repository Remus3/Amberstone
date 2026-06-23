// ds_statcheck.js - statcheck stat-sandbox panel (competitor lift #5).
//
// Self-contained champ-select panel: a "stat sandbox" for the LOCKED champion.
// The operator edits the TARGET (enemy) stats - armor / MR / HP / bonus HP - and
// the panel shows the resolved CHAMPION stat block (AD / AP / attack speed / crit
// / HP / armor / MR) plus the engine DPS number against that what-if target.
// Reads the /api/ds-statcheck route (which wraps the in-process compute_dps call).
//
// v1 honest contract: the champion-side stats are DISPLAYED read-only (they are
// the resolved stat block from the build, not editable).  The sandbox knobs are
// the TARGET (enemy) stats only.
//
// Mount contract (orchestrator-owned): champ_select.js calls
// renderDsStatcheck(blockEl, cs) on every central-pane render with the live
// champ-select context object cs.  We gate on cs.my_champion (the LOCKED
// champion numeric id) and stay hidden until a champ is locked.  The numeric id
// is resolved to the champion NAME via resolveChampNames before the fetch (the
// route's champion= param is the DDragon name/slug string).
//
// ESM, ASCII only.  No DOM writes outside renderDsStatcheck.

import { resolveChampNames } from "./cc_conditional_pressure.js";

const _DSS_MODE_MAP = {
  420: "SR",
  430: "SR",
  440: "SR",
  400: "SR",
  450: "ARAM",
  700: "SR",
  900: "ARAM",
  1700: "ARENA",
  1710: "ARENA",
  1900: "SR",
};

const _CACHE = new Map();
const _INFLIGHT = new Map();
const _TS = new Map();
const _SIG = new Map();
const _KNOBS = new Map();
const _CACHE_TTL_MS = 300000;

// Stat block rows: [response-key, display-label, formatter]
const _STAT_ROWS = [
  ["ad", "Attack Damage", "n1"],
  ["attack_speed", "Attack Speed", "n3"],
  ["crit_chance", "Crit Chance", "pct"],
  ["ap", "Ability Power", "n1"],
  ["hp", "Health", "n0"],
  ["armor", "Armor", "n1"],
  ["mr", "Magic Resist", "n1"],
  ["avg_attack_dmg", "Avg Hit (mit.)", "n1"],
  ["raw_attack_dps", "Raw Atk DPS", "n1"],
  ["per_attack_on_hit_damage", "On-Hit / AA", "n1"],
];

function _modeFromQueue(qid) {
  return _DSS_MODE_MAP[Number(qid)] || "SR";
}

function _num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function _fmt(kind, v) {
  if (v == null) return "-";
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  if (kind === "pct") return (n * 100).toFixed(0) + "%";
  if (kind === "n3") return n.toFixed(3);
  if (kind === "n2") return n.toFixed(2);
  if (kind === "n0") return n.toFixed(0);
  return n.toFixed(1);
}

function getDsStatcheckCacheCount() {
  return _CACHE.size;
}

function _resetDsStatcheck() {
  _CACHE.clear();
  _INFLIGHT.clear();
  _TS.clear();
  _SIG.clear();
  _KNOBS.clear();
}

let _schedule = null;
function setDsStatcheckScheduler(fn) {
  _schedule = typeof fn === "function" ? fn : null;
}

function _wireStrip(blockEl, champId) {
  const strip = blockEl.querySelector(".dss-strip");
  if (!strip || strip.dataset.wired === "1") return;
  strip.dataset.wired = "1";
  const inputs = strip.querySelectorAll("input[data-knob]");
  let _t = null;
  const onEdit = () => {
    if (_t) clearTimeout(_t);
    _t = setTimeout(() => {
      const k = {};
      inputs.forEach((inp) => {
        const key = inp.dataset.knob;
        const val = (inp.value || "").trim();
        if (val !== "") k[key] = val;
      });
      _KNOBS.set(champId, k);
      // force re-fetch by clearing cached ts for this champ
      for (const key of Array.from(_TS.keys())) {
        if (key.startsWith(champId + ":")) _TS.delete(key);
      }
      if (typeof _schedule === "function") _schedule();
    }, 280);
  };
  inputs.forEach((inp) => {
    inp.addEventListener("input", onEdit);
    inp.addEventListener("change", onEdit);
  });
}

function _stripHtml(knobs) {
  const a = (knobs && knobs.target_armor) || "";
  const m = (knobs && knobs.target_mr) || "";
  const h = (knobs && knobs.target_hp) || "";
  const bh = (knobs && knobs.target_bonus_hp) || "";
  return (
    '<div class="dss-strip" data-wired="0">' +
    '<label class="dss-knob"><span>Enemy Armor</span>' +
    '<input type="number" min="0" step="5" data-knob="target_armor" value="' +
    a +
    '" placeholder="auto"></label>' +
    '<label class="dss-knob"><span>Enemy MR</span>' +
    '<input type="number" min="0" step="5" data-knob="target_mr" value="' +
    m +
    '" placeholder="auto"></label>' +
    '<label class="dss-knob"><span>Enemy HP</span>' +
    '<input type="number" min="0" step="50" data-knob="target_hp" value="' +
    h +
    '" placeholder="0"></label>' +
    '<label class="dss-knob"><span>Bonus HP</span>' +
    '<input type="number" min="0" step="50" data-knob="target_bonus_hp" value="' +
    bh +
    '" placeholder="0"></label>' +
    "</div>"
  );
}

function _readoutHtml(j) {
  const out = [];
  const dps = j && j.dps != null ? Number(j.dps).toFixed(1) : "-";
  out.push('<div class="dss-dps"><span class="dss-dps-label">DPS</span>');
  out.push('<span class="dss-dps-value">' + dps + "</span>");
  if (j && j.phase) {
    out.push('<span class="dss-phase">' + String(j.phase) + "</span>");
  }
  out.push("</div>");
  const inputs = (j && j.inputs) || {};
  const aSrc = inputs.armor_source === "auto" ? " (auto)" : "";
  const mSrc = inputs.mr_source === "auto" ? " (auto)" : "";
  out.push('<div class="dss-target">vs Armor ');
  out.push(Number(inputs.target_armor || 0).toFixed(0) + aSrc);
  out.push(" / MR " + Number(inputs.target_mr || 0).toFixed(0) + mSrc + "</div>");
  const stats = (j && j.stats) || {};
  out.push('<div class="dss-rows">');
  _STAT_ROWS.forEach(([key, label, kind]) => {
    const v = stats[key];
    if (v == null) return;
    out.push(
      '<div class="dss-row"><span class="dss-name">' +
        label +
        '</span><span class="dss-val">' +
        _fmt(kind, v) +
        "</span></div>",
    );
  });
  out.push("</div>");
  return out.join("");
}

async function _fetchStatcheck(champName, mode, knobs, champId) {
  const qs = new URLSearchParams();
  qs.set("champion", champName);
  qs.set("mode", mode);
  if (knobs && knobs.target_armor) qs.set("target_armor", knobs.target_armor);
  if (knobs && knobs.target_mr) qs.set("target_mr", knobs.target_mr);
  if (knobs && knobs.target_hp) qs.set("target_hp", knobs.target_hp);
  if (knobs && knobs.target_bonus_hp) qs.set("target_bonus_hp", knobs.target_bonus_hp);
  const url = "/api/ds-statcheck?" + qs.toString();
  const key = champId + ":" + url;
  const cached = _CACHE.get(key);
  const ts = _TS.get(key);
  if (cached && ts && Date.now() - ts < _CACHE_TTL_MS) return cached;
  if (_INFLIGHT.has(key)) return _INFLIGHT.get(key);
  const p = fetch(url, { headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      _CACHE.set(key, j);
      _TS.set(key, Date.now());
      _INFLIGHT.delete(key);
      return j;
    })
    .catch(() => {
      _INFLIGHT.delete(key);
      return null;
    });
  _INFLIGHT.set(key, p);
  return p;
}

export function renderDsStatcheck(blockEl, cs) {
  if (!blockEl) return;
  const champId = cs && _num(cs.my_champion);
  if (!champId || champId <= 0) {
    blockEl.hidden = true;
    blockEl.innerHTML = "";
    return;
  }
  const names = resolveChampNames([champId]);
  // resolveChampNames returns a POSITIONAL array of slugs (not an id-keyed
  // map), so the single locked-champ name is names[0].  Indexing by the
  // numeric champId left champName always "" -> the panel never rendered.
  const champName = names.length ? names[0] : "";
  if (!champName) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;
  const mode = _modeFromQueue(cs.queue_id);
  const knobs = _KNOBS.get(champId) || {};

  let host = blockEl.querySelector(".dss-host");
  if (!host) {
    blockEl.innerHTML =
      '<div class="dss-host"><div class="dss-title">Stat Sandbox</div>' +
      '<div class="dss-strip-mount"></div><div class="dss-readout-mount"></div></div>';
    host = blockEl.querySelector(".dss-host");
  }
  const stripMount = host.querySelector(".dss-strip-mount");
  if (stripMount.dataset.rendered !== "1") {
    stripMount.innerHTML = _stripHtml(knobs);
    stripMount.dataset.rendered = "1";
    _wireStrip(blockEl, champId);
  }

  const sig = champId + ":" + mode + ":" + JSON.stringify(knobs);
  _fetchStatcheck(champName, mode, knobs, champId).then((j) => {
    const readMount = host.querySelector(".dss-readout-mount");
    if (!readMount) return;
    if (!j || !j.ok) {
      if (_SIG.get(blockEl) !== "err:" + sig) {
        readMount.innerHTML = '<div class="dss-empty">No stat readout available.</div>';
        _SIG.set(blockEl, "err:" + sig);
      }
      return;
    }
    const newSig = sig + ":" + (j.dps == null ? "x" : j.dps) + ":" + (j.count || 0);
    if (_SIG.get(blockEl) === newSig) return;
    readMount.innerHTML = _readoutHtml(j);
    _SIG.set(blockEl, newSig);
  });
}

export { getDsStatcheckCacheCount, _resetDsStatcheck, setDsStatcheckScheduler };

export const __test = {
  _modeFromQueue,
  _stripHtml,
  _readoutHtml,
  _fmt,
  _num,
  _STAT_ROWS,
  _DSS_MODE_MAP,
};
