// Patch-impact card (Session view). Renders core.patch_impact: the cross-patch
// Daemon Slayer snapshot diff (tools/ds_patch_diff) intersected with the
// champions the operator ACTUALLY plays, from the local rewind corpus. Answers
// "what moved for MY champs this patch" instead of restating the patch note.
// Computed entirely locally (no Riot / Claude dependency) - the Haiku-to-ZERO
// north star.
//
// Backend wire:
//   GET /api/patch-impact[?mode=sr|aram|arena][&top=N][&min_games=N]
//   Response: { ok, mode, old_patch, new_patch, n_matches, changed_items,
//     reason, champions:[{champion_id, champion, name, games, wins, winrate,
//       play_share, change_count, champion_changes:[{field,old,new}],
//       ability_changes:[{key,field,old,new}],
//       build_changes:[{archetype,old,new}],
//       item_changes:[{item_id,name,fields:[{field,old,new}]}]}, ...] }
//
// DESCRIPTIVE ONLY. The card says what moved, never whether the champion got
// better - a build-order reshuffle is not a buff, and claiming so would launder
// a snapshot diff into advice the data does not support. Champions with zero
// changes keep their row and render the "-" sentinel rather than vanishing, so
// the card does not reflow between patches.
//
// Discipline mirrors playstyle_labels.js / session_hygiene.js: pure ESM, ASCII
// only, single cache + TTL, inflight guard, sig-dedup, no DOM writes outside
// renderPatchImpact(), degraded text on error. Detail rides in title= tooltips
// so a long change list can never overflow the row.

const _MOUNT = 'patch-impact-card';
const _TTL_MS = 5 * 60 * 1000;
const _MAX_ROWS = 10;
const _MAX_TIP = 6;     // detail lines per tooltip; the rest is summarised
let _cache = null;
let _ts = 0;
let _inflight = false;
let _sig = '';

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// A change value may be a number, a string, a list (build order), or null.
function _fmtVal(v) {
  if (v == null) return '-';
  if (Array.isArray(v)) return `${v.length} items`;
  return String(v);
}

// A missing winrate is dim, never "bad" - Number(null) is 0, so the null check
// has to come before the numeric one or an absent value reads as a 0% champion.
function _wrClass(wr) {
  if (wr == null) return 'pi-dim';
  const w = Number(wr);
  if (!isFinite(w)) return 'pi-dim';
  return w >= 50 ? 'pi-good' : 'pi-bad';
}

function _tip(lines) {
  const shown = lines.slice(0, _MAX_TIP);
  if (lines.length > shown.length) {
    shown.push(`+ ${lines.length - shown.length} more`);
  }
  return shown.join('\n');
}

// Each chip is one section of the diff. Tone is neutral everywhere: none of
// these say better or worse, only that the section moved.
function _chips(c) {
  const out = [];
  const stat = c.champion_changes || [];
  if (stat.length) {
    out.push(['stat', stat.length, _tip(stat.map(
      (r) => `${r.field}: ${_fmtVal(r.old)} -> ${_fmtVal(r.new)}`))]);
  }
  const abil = c.ability_changes || [];
  if (abil.length) {
    out.push(['ability', abil.length, _tip(abil.map(
      (r) => `${r.key} ${r.field}: ${_fmtVal(r.old)} -> ${_fmtVal(r.new)}`))]);
  }
  const build = c.build_changes || [];
  if (build.length) {
    out.push(['build', build.length, _tip(build.map(
      (r) => `${r.archetype}: ${_fmtVal(r.old)} -> ${_fmtVal(r.new)}`))]);
  }
  const items = c.item_changes || [];
  if (items.length) {
    out.push(['item', items.length, _tip(items.map(
      (r) => `${r.name}: ${(r.fields || []).map((f) => f.field).join(', ')}`))]);
  }
  return out.map(([kind, n, tip]) =>
    `<span class="pi-chip pi-${kind}" title="${_esc(tip)}">` +
    `${n} ${_esc(kind)}</span>`).join('');
}

function _champRow(c) {
  const chips = _chips(c);
  const cell = chips || '<span class="pi-none">-</span>';
  const wr = c.winrate != null ? `${Number(c.winrate).toFixed(0)}%` : '-';
  const share = c.play_share != null
    ? ` title="${_esc(`${c.play_share}% of your games this mode`)}"` : '';
  return (
    `<div class="pi-row">` +
      `<div class="pi-champ"${share}>${_esc(c.name || c.champion || '-')}` +
        `<span class="pi-games">${c.games | 0}g</span></div>` +
      `<div class="pi-wr ${_wrClass(c.winrate)}">${wr}</div>` +
      `<div class="pi-chips">${cell}</div>` +
    `</div>`
  );
}

function _head(payload) {
  const to = _esc(payload.new_patch || '-');
  const from = _esc(payload.old_patch || '-');
  return `<div class="session-card-head">PATCH ${to}` +
    `<span class="pi-from">from ${from}</span></div>`;
}

function patchImpactHtml(payload) {
  if (!payload || payload.ok === false) {
    return '<div class="session-card-head">PATCH</div>' +
      '<div class="pi-empty">Patch impact unavailable.</div>';
  }
  const champs = payload.champions || [];
  if (!champs.length) {
    const why = payload.reason
      ? ` (${_esc(payload.reason)})` : ' - "-" until the corpus clears.';
    return _head(payload) +
      `<div class="pi-empty">No played champion has enough games yet${why}</div>`;
  }
  const shown = champs.slice(0, _MAX_ROWS);
  const rows = shown.map(_champRow).join('');
  const more = champs.length > shown.length
    ? `<div class="pi-more">+ ${champs.length - shown.length} more champions ` +
      `not shown</div>` : '';
  return (
    _head(payload) +
    `<div class="pi-rows">${rows}</div>${more}` +
    `<div class="pi-caption">Snapshot diff x your own ` +
    `${payload.n_matches | 0} ${_esc(payload.mode || '')} matches. ` +
    `${payload.changed_items | 0} items changed patch-wide; only the ones in ` +
    `your build orders count here. Descriptive - it says what moved, not ` +
    `whether the champion got better.</div>`
  );
}

function _signature(payload) {
  if (!payload || payload.ok === false) return '_empty';
  const s = (payload.champions || []).map(
    (c) => `${c.champion_id}:${c.games | 0}:${c.change_count | 0}`).join(';');
  return `${payload.old_patch}>${payload.new_patch}:${payload.n_matches | 0}:${s}`;
}

export function renderPatchImpact() {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const now = Date.now();
  if (_cache && (now - _ts) < _TTL_MS) { _paint(mount, _cache); return; }
  if (_inflight) return;
  _inflight = true;
  fetch('/api/patch-impact', { cache: 'no-store' })
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
  mount.innerHTML = patchImpactHtml(data);
}

function _degraded(mount) {
  _sig = '';
  mount.hidden = false;
  mount.innerHTML = '<div class="session-card-head">PATCH</div>' +
    '<div class="pi-empty">Patch impact unavailable.</div>';
}

export function _resetPatchImpact() {
  _cache = null; _ts = 0; _inflight = false; _sig = '';
}

export const __test = {
  _fmtVal, _wrClass, _tip, _chips, _champRow, _head, patchImpactHtml,
  _signature, _MAX_ROWS, _MAX_TIP,
};
