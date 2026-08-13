// branch_review.js - B4-e (RM-189) DECISION BRANCHES, post-game only.
//
// The post-game half of the B4 compliance split. Riot's third-party rules ban
// in-game notifications that dictate player action, so RC computes the
// multi-path choice set DURING the game, writes it to the shadow corpus and
// renders NOTHING live (see dashboard/_state_builder.suppress_live_directives
// and web/js/lib/live_directive_gate.js). This module replays that capture
// afterwards: "here is the branch you were at, here is what each path was
// worth".
//
// Source: GET /api/branch-review (core/branch_review.py). Render-only - it
// never computes a verdict and never posts.
//
// It deliberately does NOT claim what the operator CHOSE. Once the chips stop
// rendering in-game there is no click to capture, so the capture records what
// was OFFERED. Asserting a choice RC never observed would be a fabrication;
// see docs/OVERLAY_B4_DESIGN.md section 2, gap 2.
//
// HARD CONSTRAINT: this block must never mount in the ?overlay=1 shell. It
// lives inside #view-last-match, which the overlay never shows, and the
// module self-gates as well - defence in depth, because the compliance
// question a reviewer asks is about the in-game surface.

import { directivesAllowed } from '../lib/live_directive_gate.js';

const WRAP_ID = 'lm-branch-review';
const LIST_ID = 'lm-br-list';
const META_ID = 'lm-br-meta';
const NOTE_ID = 'lm-br-note';
const EMPTY_ID = 'lm-br-empty';

// Render dedup: the post-game view re-renders on every envelope, and the
// series for a finished match never changes.
let _lastSig = '';

function _el(id) { return document.getElementById(id); }

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Seconds -> "M:SS". Negative / non-finite reads as "-".
function fmtClock(sec) {
  const n = Number(sec);
  if (!Number.isFinite(n) || n < 0) return '-';
  const m = Math.floor(n / 60);
  const s = Math.floor(n % 60);
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

const _CONF_CLASS = { high: 'is-high', mid: 'is-mid', low: 'is-low' };

function _choiceHtml(c) {
  const key = _esc(String(c.key || '?').slice(0, 2));
  const label = _esc(String(c.label || '').slice(0, 120));
  const outcome = _esc(String(c.expected_outcome || '').slice(0, 160));
  const conf = String(c.confidence || '').toLowerCase();
  const confClass = _CONF_CLASS[conf] || '';
  const confTag = conf ? `<span class="lm-br-conf ${confClass}">${_esc(conf)}</span>` : '';
  const outcomeLine = outcome
    ? `<div class="lm-br-outcome">${outcome}</div>`
    : '';
  return `
    <div class="lm-br-choice">
      <span class="lm-br-key">${key}</span>
      <div class="lm-br-choice-body">
        <div class="lm-br-label">${label}${confTag}</div>
        ${outcomeLine}
      </div>
    </div>`;
}

function _branchHtml(b) {
  const clock = _esc(fmtClock(b.game_time_s));
  const bits = [];
  if (b.band) bits.push(_esc(b.band));
  if (b.item_count != null) bits.push(`${_esc(b.item_count)} items`);
  const context = bits.length
    ? `<span class="lm-br-context">${bits.join(' - ')}</span>` : '';
  // An excluded row still renders, so the reader learns the moment existed
  // and why its paths are missing, rather than seeing an unexplained gap.
  const body = b.precompute_excluded
    ? `<div class="lm-br-excluded">paths withheld - this mode's precompute
         table is not mode-native (RM-158)</div>`
    : (b.choices || []).map(_choiceHtml).join('');
  const native = b.native_action
    ? `<div class="lm-br-native">live coach said: ${_esc(b.native_action)}</div>`
    : '';
  return `
    <li class="lm-br-row">
      <div class="lm-br-when"><span class="lm-br-clock">${clock}</span>${context}</div>
      <div class="lm-br-paths">${body}${native}</div>
    </li>`;
}

function _noteFor(data) {
  const notes = [];
  if (data.truncated) {
    notes.push('showing the most recent part of this match - the capture '
               + 'window clipped earlier branches');
  }
  if (data.precompute_excluded) {
    notes.push('some paths are withheld: this mode\'s precompute table '
               + 'carries SR content (RM-158)');
  }
  if (data.legacy_rows_skipped) {
    notes.push(`${data.legacy_rows_skipped} older records carry no match id `
               + 'and could not be grouped');
  }
  return notes;
}

/**
 * Render the decision-branch series.
 *
 * @param {object|null} data - the /api/branch-review payload.
 * @param {object|null} state - the /api/state envelope, for the live gate.
 */
export function renderBranchReview(data, state) {
  const wrap = _el(WRAP_ID);
  if (!wrap) return;
  const list = _el(LIST_ID);
  const meta = _el(META_ID);
  const note = _el(NOTE_ID);
  const empty = _el(EMPTY_ID);
  if (!list || !meta || !note || !empty) return;

  // Self-gate: never surface branch paths while a game is live, even if some
  // caller wires this into an in-game tick by mistake.
  const d = (state !== undefined && !directivesAllowed(state)) ? null : data;
  const branches = (d && Array.isArray(d.branches)) ? d.branches : [];

  const sig = d
    ? `${d.game_run_id || ''}:${branches.length}:${!!d.truncated}`
    : 'none';
  if (sig === _lastSig) return;
  _lastSig = sig;

  if (!branches.length) {
    wrap.hidden = !d;
    list.innerHTML = '';
    note.hidden = true;
    note.textContent = '';
    empty.hidden = false;
    meta.textContent = '-';
    return;
  }

  wrap.hidden = false;
  empty.hidden = true;

  const who = d.enemy ? `${d.my_champion} vs ${d.enemy}` : (d.my_champion || '');
  const modeTag = d.mode ? String(d.mode).toUpperCase() : '';
  meta.textContent = [modeTag, who, `${branches.length} branches`]
    .filter(Boolean).join(' - ');

  const notes = _noteFor(d);
  note.hidden = notes.length === 0;
  note.textContent = notes.join('; ');

  list.innerHTML = branches.map(_branchHtml).join('');
}

/** Fetch + render. Fail-soft: a dead route renders the empty state. */
export function refreshBranchReview(state, runId) {
  const q = runId ? `?run=${encodeURIComponent(runId)}` : '';
  return fetch(`/api/branch-review${q}`, { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => renderBranchReview(data, state))
    .catch(() => renderBranchReview(null, state));
}

// Test seam.
export const _internals = { fmtClock, _choiceHtml, _branchHtml, _noteFor, _esc };
