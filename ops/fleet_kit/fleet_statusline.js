'use strict';
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
//
// Fleet kit v9 - the CLI status line (FLEET-COMMON item 15; UI/UX standard s3).
// Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
// edit a vendored copy: report the defect to MAIN. Both ACCOUNT settings point
// at it (kit cli_display.json); a tree sets no statusLine.
//
// Line 1, fixed-width slots, one space apart, never `|`:
//   STATE A# CODE/L# branch +N  ctx NN%  5h NN%  7d NN%  model eff
//   STATE is blank, or DONE / FAIL (validated /done marker), NEEDS, STALE, BLOCK
//   (v14: a progress row or the loop status says blocked - an outside condition
//   such as a proxy outage), HALT.
//   Absent value -> `--` in its slot. Narrow COLUMNS drops whole slots from the
//   RIGHT; a slot never shrinks. Percent slots reserve two cells for the
//   problem mark (>= 70 -> 33 + `!`, >= 90 -> 1;31 + `!!`), so a mark never
//   moves a later slot.
// Lines 2-5, workflow rows from ops/loop/control/progress/*.json (item 12):
//   [>] task-name     [####------]  45% ~3m   step text
//   Order = file creation (first seen), never re-sorted. [+]/[x] rows stay 10
//   min after their last write; running silent > 2x ETA (floor 5 min) -> [!]
//   STALE; a stale row older than 24 h is abandoned and dropped. Over 4 rows:
//   3 rows + `... +N more`.
// Colour only on problems and on DONE. Files only, git dirty count cached per
// cwd for 5 s, no network, ASCII + SGR only, always exit 0, never prints
// names, emails or ids.

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

const SLOTS = [['state', 6], ['acct', 2], ['code', 8], ['branch', 12],
  ['ctx', 10], ['h5', 9], ['d7', 9], ['model', 11]];
const STATE_SGR = { DONE: '1;32', FAIL: '1;31', STALE: '1;31', NEEDS: '1;33', HALT: '35', BLOCK: '1;33' };
const ROW_GLYPH = { running: '[>]', done: '[+]', failed: '[x]', stale: '[!]',
  needs: '[?]', halted: '[=]', blocked: '[#]' };
const ROW_SGR = { running: '1', failed: '1;31', stale: '1;31', needs: '1;33', halted: '35',
  blocked: '1;33' };
const MARKER_REL = ['ops', 'loop', 'control', 'session_done.json'];
const PROGRESS_REL = ['ops', 'loop', 'control', 'progress'];
const STATUS_REL = ['ops', 'loop', 'control', 'inbox_status.json'];
const DONE_KEEP_S = 600;
const STALE_FLOOR_S = 300;
const ABANDON_S = 86400;
const GIT_TTL_MS = 5000;
const MAX_ROWS = 4;
const EFF = { low: 'lo', medium: 'md', high: 'hi', xhigh: 'xh', max: 'mx' };

const ESC = '\x1b[';
function sgr(code, s) { return code ? ESC + code + 'm' + s + ESC + '0m' : s; }

function ascii(s) {
  return String(s == null ? '' : s).replace(/[^\x20-\x7e]/g, '?');
}

function readJson(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { return null; }
}

function norm(p) { return String(p || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase(); }

// ---------------------------------------------------------------- tree facts

function gitInfo(start) {
  // {worktree, main, gitDir} for the repo holding `start`, read from files.
  let dir = path.resolve(start || '.');
  for (let i = 0; i < 64; i++) {
    const dotgit = path.join(dir, '.git');
    let st = null;
    try { st = fs.statSync(dotgit); } catch (e) { st = null; }
    if (st && st.isDirectory()) return { worktree: dir, main: dir, gitDir: dotgit, common: dotgit };
    if (st && st.isFile()) {
      try {
        const m = /^gitdir:\s*(.+)$/m.exec(fs.readFileSync(dotgit, 'utf8'));
        if (m) {
          const gd = path.resolve(dir, m[1].trim());
          const parent = path.dirname(gd);
          if (path.basename(parent) === 'worktrees') {
            const common = path.dirname(parent);
            return { worktree: dir, main: path.dirname(common), gitDir: gd, common };
          }
          return { worktree: dir, main: dir, gitDir: gd, common: gd };
        }
      } catch (e) { /* fall through */ }
    }
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return null;
}

function readRef(common, ref) {
  const loose = path.join(common, ...ref.split('/'));
  try { return fs.readFileSync(loose, 'utf8').trim(); } catch (e) { /* packed */ }
  try {
    for (const line of fs.readFileSync(path.join(common, 'packed-refs'), 'utf8').split('\n')) {
      const [sha, name] = line.trim().split(' ');
      if (name === ref) return sha;
    }
  } catch (e) { /* none */ }
  return null;
}

function headOf(info) {
  // {branch, sha} of the worktree's HEAD; files only.
  if (!info) return { branch: null, sha: null };
  let txt = '';
  try { txt = fs.readFileSync(path.join(info.gitDir, 'HEAD'), 'utf8').trim(); } catch (e) {
    return { branch: null, sha: null };
  }
  const m = /^ref:\s*(.+)$/.exec(txt);
  if (!m) return { branch: 'detached', sha: /^[0-9a-f]{40}$/.test(txt) ? txt : null };
  const ref = m[1].trim();
  const sha = readRef(info.common, ref);
  return { branch: ref.replace(/^refs\/heads\//, ''), sha: sha && /^[0-9a-f]{40}$/.test(sha) ? sha : null };
}

function mainHead(info) {
  if (!info) return null;
  return headOf({ gitDir: info.common, common: info.common }).sha;
}

function laneOf(worktree) {
  const m = /[\\/]([A-Za-z0-9]+)-worktrees[\\/]lane-(\d+)$/.exec(String(worktree || ''));
  return m ? { code: m[1].toUpperCase(), lane: m[2] } : null;
}

function rosterPaths() {
  const out = [];
  if (process.env.FLEET_ROSTER) out.push(process.env.FLEET_ROSTER);
  out.push(path.join(__dirname, '..', 'ops', 'fleet_roster.json'));
  out.push(path.join(__dirname, '..', 'fleet_roster.json'));
  return out;
}

function codeOf(main, rosterFiles) {
  for (const f of rosterFiles || rosterPaths()) {
    const doc = readJson(f);
    if (!doc || !Array.isArray(doc.repos)) continue;
    const want = norm(main);
    for (const r of doc.repos) {
      if (r && r.root && norm(r.root) === want && /^[A-Z0-9]{1,6}$/.test(String(r.code))) return r.code;
    }
  }
  return null;
}

function dirtyCount(worktree, now) {
  const key = crypto.createHash('sha1').update(norm(worktree)).digest('hex').slice(0, 16);
  const dir = path.join(os.tmpdir(), 'fleet-statusline');
  const file = path.join(dir, key + '.json');
  const c = readJson(file);
  if (c && typeof c.n === 'number' && now - c.t < GIT_TTL_MS && c.t <= now) return c.n;
  let n = null;
  try {
    const out = execFileSync('git', ['-C', worktree, 'status', '--porcelain'],
      { timeout: 1500, windowsHide: true, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    n = out.split('\n').filter(Boolean).length;
  } catch (e) { n = null; }
  try {
    fs.mkdirSync(dir, { recursive: true });
    const tmp = file + '.' + process.pid + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify({ t: now, n }));
    fs.renameSync(tmp, file);
  } catch (e) { /* cache is optional */ }
  return n;
}

// ---------------------------------------------------------------- /done marker

function sha256File(p) {
  try { return crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex'); } catch (e) { return null; }
}

function markerVerdict(main, sessionId, headSha) {
  // 'DONE' | 'FAIL' | null - the CLI side of the standard's validation rules.
  if (!main || !sessionId) return null;
  const d = readJson(path.join(main, ...MARKER_REL));
  if (!d || d.schema !== 1) return null;
  if (d.status !== 'done' && d.status !== 'failed') return null;
  if (d.status === 'done' && d.safe_to_clear !== true) return null;
  if (d.session_id !== sessionId) return null;
  if (typeof d.commit !== 'string' || !/^[0-9a-f]{40}$/.test(d.commit) || d.commit !== headSha) return null;
  const h = d.handoff;
  if (typeof h !== 'string' || !/-NEXT-SESSION\.txt$/.test(h) || /[\\/]/.test(h)) return null;
  if (typeof d.handoff_sha256 !== 'string' || sha256File(path.join(main, h)) !== d.handoff_sha256) return null;
  return d.status === 'done' ? 'DONE' : 'FAIL';
}

// ---------------------------------------------------------------- workflow rows

function fmtEta(s) {
  if (typeof s !== 'number' || !(s > 0)) return '';
  if (s < 120) return '~' + Math.round(s) + 's';
  if (s < 7200) return '~' + Math.round(s / 60) + 'm';
  return '~' + Math.round(s / 3600) + 'h';
}

function progressRows(main, nowMs) {
  // Rows to show, in first-seen order: {state, task, pct, eta, step, order}.
  const dir = path.join(main, ...PROGRESS_REL);
  let names = [];
  try { names = fs.readdirSync(dir).filter((n) => n.endsWith('.json')); } catch (e) { return []; }
  const rows = [];
  for (const name of names) {
    const p = path.join(dir, name);
    let st;
    try { st = fs.statSync(p); } catch (e) { continue; }
    const d = readJson(p);
    if (!d || typeof d !== 'object') continue;
    const age = (nowMs - st.mtimeMs) / 1000;
    const eta = typeof d.eta_s === 'number' ? d.eta_s : null;
    let state = null;
    if (d.status === 'running') {
      const limit = Math.max(2 * (eta || 0), STALE_FLOOR_S);
      if (age > limit) state = age > ABANDON_S ? null : 'stale';
      else state = 'running';
    } else if (d.status === 'done' || d.status === 'failed') {
      state = age <= DONE_KEEP_S ? d.status : null;
    } else if (d.status === 'needs-operator') {
      state = age <= ABANDON_S ? 'needs' : null;
    } else if (d.status === 'halted') {
      state = age <= ABANDON_S ? 'halted' : null;
    } else if (d.status === 'blocked') {
      state = age <= ABANDON_S ? 'blocked' : null;
    }
    if (!state) continue;
    let step = d.step;
    if (Array.isArray(d.checklist) && d.checklist.length && d.checklist[0]) step = d.checklist[0].task || step;
    const born = st.birthtimeMs || st.ctimeMs || st.mtimeMs;
    rows.push({ state, task: d.task || name.slice(0, -5), pct: d.pct, eta: state === 'running' ? eta : null,
      step, order: born, name });
  }
  rows.sort((a, b) => (a.order - b.order) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return rows;
}

function pad(s, w) { s = String(s); return s.length >= w ? s.slice(0, w) : s + ' '.repeat(w - s.length); }
function rpad(s, w) { s = String(s); return s.length >= w ? s.slice(0, w) : ' '.repeat(w - s.length) + s; }

function rowLine(r, columns, plain) {
  const pct = typeof r.pct === 'number' ? Math.max(0, Math.min(100, Math.round(r.pct))) : null;
  const fill = pct == null ? 0 : Math.round(pct / 10);
  const bar = '[' + '#'.repeat(fill) + '-'.repeat(10 - fill) + ']';
  const head = ' ' + pad(ascii(r.task), 13) + ' ' + bar + ' ' + rpad(pct == null ? '--' : pct + '%', 4) +
    ' ' + pad(fmtEta(r.eta), 5) + ' ';
  const room = Math.max(0, columns - 3 - head.length);
  const step = ascii(r.step).replace(/\s+/g, ' ').trim().slice(0, room);
  return sgr(plain ? '' : ROW_SGR[r.state], ROW_GLYPH[r.state]) + (head + step).replace(/\s+$/, '');
}

function rowLines(rows, columns) {
  if (rows.length > MAX_ROWS) {
    return rows.slice(0, MAX_ROWS - 1).map((r) => rowLine(r, columns))
      .concat(['... +' + (rows.length - (MAX_ROWS - 1)) + ' more']);
  }
  return rows.map((r) => rowLine(r, columns));
}

// ---------------------------------------------------------------- line 1

function pctSlot(label, v) {
  if (typeof v !== 'number' || !isFinite(v)) return { text: label + ' --' };
  const n = Math.max(0, Math.round(v));
  if (n >= 90) return { text: label + ' ' + n + '%!!', sgr: '1;31' };
  if (n >= 70) return { text: label + ' ' + n + '%!', sgr: '33' };
  return { text: label + ' ' + n + '%' };
}

function shortModel(d) {
  const m = d.model || {};
  let s = m.display_name || '';
  if (s) s = s.toLowerCase().replace(/\s*\(.*\)\s*$/, '').replace(/\s+/g, '-');
  else if (m.id) s = String(m.id).replace(/^claude-/, '').replace(/-(\d+)-(\d+)(\b|$).*/, '-$1.$2');
  return ascii(s);
}

function quotaFallback(cfgDir) {
  // The teamclaude quota file, only when stdin lacks rate_limits. Fractions 0-1.
  try {
    const cj = readJson(cfgDir ? path.join(cfgDir, '.claude.json') : path.join(os.homedir(), '.claude.json'));
    const uuid = cj && cj.oauthAccount && cj.oauthAccount.accountUuid;
    if (!uuid) return null;
    const j = readJson(path.join(os.homedir(), '.config', 'teamclaude.state.json'));
    const q = j && (j.quota || []).find((x) => x && x.accountUuid === uuid);
    if (!q || !q.quota) return null;
    const f = (v) => (typeof v === 'number' ? v * 100 : null);
    return { h5: f(q.quota.unified5h), d7: f(q.quota.unified7d) };
  } catch (e) { return null; }
}

function rateOf(d, cfgDir) {
  const rl = d.rate_limits;
  const g = (o) => (o && typeof o.used_percentage === 'number' ? o.used_percentage : null);
  if (rl && (rl.five_hour || rl.seven_day)) return { h5: g(rl.five_hour), d7: g(rl.seven_day) };
  return quotaFallback(cfgDir) || { h5: null, d7: null };
}

function halted(main) {
  const s = readJson(path.join(main, ...STATUS_REL));
  return !!(s && ['halted', 'backoff', 'limit'].includes(s.state));
}

function blocked(main) {
  // v14: an outside condition (proxy down) stops the loop - not a refusal.
  const s = readJson(path.join(main, ...STATUS_REL));
  return !!(s && s.state === 'blocked');
}

function fitSlots(slots, columns) {
  let n = slots.length;
  const width = (k) => slots.slice(0, k).reduce((a, s) => a + s.w, 0) + (k - 1);
  while (n > 1 && width(n) > columns) n--;
  const parts = slots.slice(0, n).map((s) => {
    const t = pad(s.text, s.w);
    const body = t.replace(/\s+$/, '');
    return sgr(s.sgr, body) + t.slice(body.length);
  });
  return parts.join(' ').replace(/\s+$/, '');
}

function render(d, opts) {
  opts = opts || {};
  const env = opts.env || process.env;
  const nowMs = opts.nowMs || Date.now();
  const columns = Number(d.columns || (d.terminal && d.terminal.columns) || env.COLUMNS) || 200;
  const cwd = (d.workspace && d.workspace.current_dir) || d.cwd || opts.cwd || process.cwd();
  const info = gitInfo(cwd);
  const lane = info ? laneOf(info.worktree) : null;
  const main = info ? info.main : null;
  const code = (main && codeOf(main, opts.roster)) || (lane && lane.code) || null;
  const hd = headOf(info);
  const dirty = info ? (opts.dirty !== undefined ? opts.dirty : dirtyCount(info.worktree, nowMs)) : null;
  const rows = main ? progressRows(main, nowMs) : [];
  const verdict = markerVerdict(main, d.session_id, mainHead(info));
  let state = '';
  if (verdict === 'FAIL') state = 'FAIL';
  else if (verdict === 'DONE') state = 'DONE';
  else if (rows.some((r) => r.state === 'needs')) state = 'NEEDS';
  else if (rows.some((r) => r.state === 'stale')) state = 'STALE';
  else if (rows.some((r) => r.state === 'blocked') || (main && blocked(main))) state = 'BLOCK';
  else if (main && halted(main)) state = 'HALT';
  const cfg = env.CLAUDE_CONFIG_DIR || '';
  const am = /acct(\d+)/i.exec(path.basename(cfg));
  const acct = 'A' + (am ? am[1] : '1');
  const plus = dirty ? ' +' + dirty : '';
  const branch = hd.branch ? ascii(hd.branch).slice(0, 12 - plus.length) + plus : '--';
  const rate = rateOf(d, cfg || null);
  const used = d.context_window && d.context_window.used_percentage;
  const effRaw = (d.effort && d.effort.level) || env.CLAUDE_EFFORT || '';
  const eff = EFF[effRaw] || ascii(effRaw).slice(0, 2);
  // The model name gives way so the effort is never cut off.
  const model = [shortModel(d).slice(0, eff ? 11 - eff.length - 1 : 11).replace(/[.-]+$/, ''), eff].filter(Boolean).join(' ') || '--';
  const vals = {
    state: { text: state, sgr: STATE_SGR[state] },
    acct: { text: acct },
    code: { text: code ? code + (lane ? '/L' + lane.lane : '') : '--' },
    branch: { text: branch },
    ctx: pctSlot('ctx', used),
    h5: pctSlot('5h', rate.h5),
    d7: pctSlot('7d', rate.d7),
    model: { text: model },
  };
  const slots = SLOTS.map(([k, w]) => ({ w, text: ascii(vals[k].text), sgr: vals[k].sgr }));
  const lines = [fitSlots(slots, columns)].concat(rowLines(rows, columns));
  return lines.join('\n');
}

function readStdin() {
  try { return JSON.parse(fs.readFileSync(0, 'utf8')); } catch (e) { return {}; }
}

module.exports = { render, progressRows, rowLine, rowLines, markerVerdict, gitInfo, headOf,
  mainHead, codeOf, laneOf, pctSlot, fitSlots, fmtEta, SLOTS, ascii };

if (require.main === module) {
  let out;
  try { out = render(readStdin()); } catch (e) { out = '--'; }
  process.stdout.write(out);
  process.exitCode = 0;
}
