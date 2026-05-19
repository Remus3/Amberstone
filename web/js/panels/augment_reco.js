// Augment recommendation panel (CLAUDE #88 foregrounding, 2026-05-18).
//
// Foregrounds the data-driven Arena/Mayhem augment ranking that the
// backend (core/augment_recommender.py + augment_external_source.py,
// wired through coaches/arena_coach.py:_augment_recommendation) already
// ships. Until now the only surface was the #augments-pill `title`
// hover tooltip - useless mid-game on a glance-only secondary monitor.
// This renders the ranking as a prominent, always-visible block inside
// the in-game ITEM BUILD panel, mirroring the #ib-ds-block show/hide
// pattern (a self-contained toggled build-section - no reflow of the
// other info panels, which is why augments were moved off item-build
// to the header pill in the first place; the *recommendation* is a
// distinct, augment-select-scoped signal, not the owned-glance).
//
// Reads the coach payload `p` fields the arena coach stamps:
//   p.aug_reco          [{id,name,rarity,score,conf,n_own,ext_wr,own_wr,syn}]
//   p.aug_reco_top      name of the #1 pick
//   p.aug_reco_conf     blend weight = how much own-history is trusted
//   p.aug_reco_mode     "mayhem" | "arena"
//   p.aug_reco_stage    Mayhem stage (1-5) or null
//   p.aug_reco_n_matches own augment-bearing games scanned
//   p.aug_reco_external  whether the external Mayhem prior was used
//   p.augment_select    true while the in-game augment panel is open
//
// Presence of a non-empty p.aug_reco IS the mode gate - the recommender
// only emits it for Arena/Mayhem, so no separate state.mode check is
// needed (keeps this module decoupled from the mode authority).
//
// The competitive "why" (opportunity #1/#4): every row shows own WR vs
// the external Mayhem prior + synergy with already-picked augments + the
// sample size behind it - the causal explanation Overlay App Z6/Aggregator B/Overlay App E
// structurally cannot give for Arena augments (a niche they all skip).

import { el } from '../lib/helpers.js';

const AR = {
  block: el("ib-aug-reco-block"),
  top:   el("ib-aug-reco-top"),
  list:  el("ib-aug-reco-list"),
  meta:  el("ib-aug-reco-meta"),
};

let _lastSig = "";

function _hide() {
  if (!AR.block) return;
  if (!AR.block.hidden) AR.block.hidden = true;
  AR.block.classList.remove("is-active");
  _lastSig = "";
}

function _pct(v) {
  return (v == null || Number.isNaN(v)) ? "-" : `${Math.round(v * 100)}%`;
}

// Synergy is a shrunk (pair_wr - own_wr) delta on the win-rate scale -
// small, signed, and 0 until something has been picked this game. Render
// as signed percentage points; blank when neutral so the column doesn't
// add noise on the first pick.
function _syn(v) {
  if (!v) return "";
  const pp = (v * 100).toFixed(1);
  return v > 0 ? `+${pp}` : `${pp}`;
}

export function renderAugmentReco(p) {
  if (!AR.block) return;
  const reco = (p && Array.isArray(p.aug_reco)) ? p.aug_reco : [];
  if (!reco.length) { _hide(); return; }

  const active   = p.augment_select === true;
  const topName  = p.aug_reco_top || (reco[0] && reco[0].name) || "-";
  const conf     = Math.round((p.aug_reco_conf || 0) * 100);
  const mode     = p.aug_reco_mode || "?";
  const stage    = p.aug_reco_stage;
  const nMatches = p.aug_reco_n_matches || 0;
  const ext      = p.aug_reco_external === true;

  // Idempotency - the block lives on the 2s state cadence; without a
  // signature guard the rows would tear down + rebuild every tick (the
  // dashboard-render-idempotency rule).
  const sig = [
    active ? "A" : "_",
    topName, conf, mode, stage, nMatches, ext ? "x" : "o",
    reco.map(r => `${r.id}:${r.score}:${r.syn || 0}`).join(","),
  ].join("|");
  if (sig === _lastSig && !AR.block.hidden) {
    AR.block.classList.toggle("is-active", active);
    return;
  }
  _lastSig = sig;

  // Top pick - the headline. "PICK NOW" only while the augment panel is
  // genuinely open; otherwise it's the standing recommendation.
  AR.top.innerHTML =
    `<span class="ar-top-cue">${active ? "PICK NOW" : "TOP PICK"}</span>` +
    `<span class="ar-top-name">${topName}</span>` +
    `<span class="ar-top-conf" title="Confidence = blend weight: how much your own history is trusted vs the external Mayhem prior. Low early by design.">conf ${conf}%</span>`;

  // Ranked rows - rank, name, score, own/ext WR, synergy, sample size.
  const anySyn = reco.some(r => r.syn);
  AR.list.innerHTML = reco.slice(0, 5).map((r, i) => {
    const rk   = i + 1;
    const name = r.name || String(r.id || "?");
    const rar  = (r.rarity || "").toLowerCase();
    const own  = _pct(r.own_wr);
    const exv  = (r.ext_wr == null) ? "-" : _pct(r.ext_wr);
    const synV = anySyn ? _syn(r.syn) : "";
    const synCell = synV
      ? `<span class="ar-syn ${r.syn > 0 ? "pos" : "neg"}">${synV}</span>`
      : `<span class="ar-syn"></span>`;
    return (
      `<div class="ar-row${rk === 1 ? " is-top" : ""}">` +
        `<span class="ar-rank">${rk}</span>` +
        `<span class="ar-name" title="${name}">` +
          (rar ? `<i class="ar-rar ${rar}"></i>` : "") + name +
        `</span>` +
        `<span class="ar-score" title="Blended marginal + synergy score">${(r.score != null ? r.score : 0)}</span>` +
        `<span class="ar-wr" title="Your win-rate (n=${r.n_own || 0}) / external Mayhem prior">` +
          `${own}<span class="ar-sep">/</span>${exv}</span>` +
        synCell +
      `</div>`
    );
  }).join("");

  const parts = [mode];
  if (stage) parts.push(`stage ${stage}`);
  parts.push(`${nMatches} own game${nMatches === 1 ? "" : "s"}`);
  parts.push(ext ? "external prior" : "own-only");
  AR.meta.textContent = parts.join(" · ");

  AR.block.classList.toggle("is-active", active);
  AR.block.hidden = false;
}

// Test/diagnostic helper - reset the dedup signature so the next render
// writes to the DOM unconditionally.
export function _resetAugmentRecoSig() { _lastSig = ""; }
