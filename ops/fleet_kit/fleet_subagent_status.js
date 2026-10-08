'use strict';
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
//
// Fleet kit v9 - subagentStatusLine (FLEET-COMMON item 15; UI/UX standard s3).
// Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
// edit a vendored copy: report the defect to MAIN.
//
// stdin: {columns, tasks: [{id, name, description, label, status, cwd}, ...]}.
// stdout: one JSON line {"id", "content"} per task whose item-12 progress file
// matches the task label - same row grammar as the status line:
//   [>] task-name     [####------]  45% ~3m   step text
// A task with no matching file gets no line (the default row stays). Match:
// the progress stem equals the task name, or is one word of its label or
// description (stems shorter than 4 characters never match a word). Plain
// text (no SGR: the agent panel is not a terminal line). Files only, always
// exit 0, ASCII only.

const fs = require('fs');
const path = require('path');
const sl = require('./fleet_statusline.js');

const PROGRESS_REL = ['ops', 'loop', 'control', 'progress'];

function candidates(main) {
  const dir = path.join(main, ...PROGRESS_REL);
  let names = [];
  try { names = fs.readdirSync(dir).filter((n) => n.endsWith('.json')); } catch (e) { return []; }
  const out = [];
  for (const n of names) {
    try { out.push({ stem: n.slice(0, -5).toLowerCase(), mtime: fs.statSync(path.join(dir, n)).mtimeMs }); } catch (e) { /* gone */ }
  }
  return out.sort((a, b) => b.mtime - a.mtime);
}

function matchStem(task, cands) {
  const name = String(task.name || '').toLowerCase();
  const words = new Set(String((task.label || '') + ' ' + (task.description || '')).toLowerCase()
    .split(/[^a-z0-9_-]+/).filter(Boolean));
  for (const c of cands) if (name && c.stem === name) return c.stem;
  for (const c of cands) if (c.stem.length >= 4 && words.has(c.stem)) return c.stem;
  return null;
}

function render(d, nowMs) {
  nowMs = nowMs || Date.now();
  const columns = Number(d.columns) || 120;
  const out = [];
  const cache = new Map();
  for (const t of Array.isArray(d.tasks) ? d.tasks : []) {
    if (!t || !t.id) continue;
    const info = sl.gitInfo(t.cwd || d.cwd || process.cwd());
    if (!info) continue;
    if (!cache.has(info.main)) {
      cache.set(info.main, { cands: candidates(info.main), rows: sl.progressRows(info.main, nowMs) });
    }
    const { cands, rows } = cache.get(info.main);
    const stem = matchStem(t, cands);
    if (!stem) continue;
    const row = rows.find((r) => r.name.slice(0, -5).toLowerCase() === stem);
    if (!row) continue;
    out.push(JSON.stringify({ id: String(t.id), content: sl.rowLine(row, columns, true) }));
  }
  return out.join('\n');
}

module.exports = { render, matchStem };

if (require.main === module) {
  let out = '';
  try { out = render(JSON.parse(fs.readFileSync(0, 'utf8'))); } catch (e) { out = ''; }
  if (out) process.stdout.write(out + '\n');
  process.exitCode = 0;
}
