#!/usr/bin/env node
/**
 * tools/usage-mcp-server.js - Anthropic usage MCP server
 *
 * Add to Claude Code:
 *   claude mcp add anthropic-usage -- node "<repo>\tools\usage-mcp-server.js"
 *
 * Key resolution order:
 *   1. ANTHROPIC_USAGE_KEY env var
 *   2. <project root>/.anthropic-usage.key file (gitignored)
 */

const https = require('https');
const readline = require('readline');
const fs = require('fs');
const path = require('path');

const KEY_FILE = path.join(__dirname, '..', '.anthropic-usage.key');

function loadKey() {
  if (process.env.ANTHROPIC_USAGE_KEY) return process.env.ANTHROPIC_USAGE_KEY.trim();
  try { return fs.readFileSync(KEY_FILE, 'utf8').trim(); } catch { return null; }
}

function httpsGet(url, headers) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers }, (res) => {
      let body = '';
      res.on('data', c => body += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(body) }); }
        catch { resolve({ status: res.statusCode, body }); }
      });
    });
    req.on('error', reject);
  });
}

function isoTs(d) { return d.toISOString().replace(/\.\d{3}Z$/, 'Z'); }
function yesterdayStart() { const d = new Date(); d.setUTCDate(d.getUTCDate() - 1); d.setUTCHours(0,0,0,0); return isoTs(d); }
function yesterdayEnd()   { const d = new Date(); d.setUTCHours(0,0,0,0); return isoTs(d); }
function isoDate(d)       { return d.toISOString().slice(0, 10); }
function yesterday()      { const d = new Date(); d.setUTCDate(d.getUTCDate() - 1); return isoDate(d); }

async function queryUsage(startDate, endDate) {
  const apiKey = loadKey();
  if (!apiKey) return 'Error: no API key found (set ANTHROPIC_USAGE_KEY or write to .anthropic-usage.key)';

  // Convert YYYY-MM-DD to ISO timestamps; ending_at must be exclusive (start of next day)
  const startTs = startDate.includes('T') ? startDate : `${startDate}T00:00:00Z`;
  const endTs = (() => {
    if (endDate.includes('T')) return endDate;
    const d = new Date(`${endDate}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + 1);
    return d.toISOString().replace(/\.\d{3}Z$/, 'Z');
  })();

  const headers = { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' };

  // -- Usage report (tokens by model) ------------------------------------------
  const uParams = new URLSearchParams({
    starting_at: startTs,
    ending_at:   endTs,
    bucket_width: '1d',
  });
  uParams.append('group_by[]', 'model');

  const uRes = await httpsGet(
    `https://api.anthropic.com/v1/organizations/usage_report/messages?${uParams}`,
    headers
  );

  // -- Cost report (actual USD by model via description) -----------------------
  const cParams = new URLSearchParams({
    starting_at: startTs,
    ending_at:   endTs,
    bucket_width: '1d',
  });
  cParams.append('group_by[]', 'description');

  const cRes = await httpsGet(
    `https://api.anthropic.com/v1/organizations/cost_report?${cParams}`,
    headers
  );

  const lines = [`Anthropic spend  ${startDate} → ${endDate}\n`];

  // -- Cost section (amounts in cents -> divide by 100 for USD) ------------------
  if (cRes.status === 200) {
    const results = (cRes.body.data?.[0]?.results) ?? [];
    const byCost = {};
    let total = 0;
    for (const row of results) {
      const m = row.model || 'other';
      const amt = parseFloat(row.amount || '0');
      byCost[m] = (byCost[m] || 0) + amt;
      total += amt;
    }
    lines.push('── Cost (USD) ──');
    for (const [m, cents] of Object.entries(byCost).sort()) {
      lines.push(`  ${m}: $${(cents / 100).toFixed(4)}`);
    }
    lines.push(`  TOTAL: $${(total / 100).toFixed(2)}\n`);
  } else {
    lines.push(`Cost API: HTTP ${cRes.status} - ${JSON.stringify(cRes.body)}\n`);
  }

  // -- Token section -------------------------------------------------------------
  if (uRes.status === 200) {
    const results = (uRes.body.data?.[0]?.results) ?? [];
    lines.push('── Tokens ──');
    for (const row of results) {
      const cw = (row.cache_creation?.ephemeral_5m_input_tokens || 0)
               + (row.cache_creation?.ephemeral_1h_input_tokens || 0);
      lines.push(`  ${row.model}`);
      lines.push(`    in:${(row.uncached_input_tokens||0).toLocaleString()}  out:${(row.output_tokens||0).toLocaleString()}  cache_w:${cw.toLocaleString()}  cache_r:${(row.cache_read_input_tokens||0).toLocaleString()}`);
    }
  } else {
    lines.push(`Usage API: HTTP ${uRes.status} - ${JSON.stringify(uRes.body)}`);
  }

  return lines.join('\n');
}

// -- MCP stdio transport ------------------------------------------------------

const TOOLS = [{
  name: 'query_usage',
  description: 'Fetch Anthropic API usage broken down by model for a date range. Defaults to yesterday.',
  inputSchema: {
    type: 'object',
    properties: {
      start_date: { type: 'string', description: 'YYYY-MM-DD (default: yesterday)' },
      end_date:   { type: 'string', description: 'YYYY-MM-DD (default: today)' },
    },
  },
}];

const rl = readline.createInterface({ input: process.stdin, terminal: false });
const send = obj => process.stdout.write(JSON.stringify(obj) + '\n');
const rpcError = (id, code, message) =>
  send({ jsonrpc: '2.0', id, error: { code, message } });

// RM-811: control characters escaped before any client-derived text reaches
// stderr (the RM-321 log-injection class), the core/log_scrub.py mapping.
const scrubLog = text => String(text).replace(
  /[\x00-\x1f\x7f-\x9f\\]/g,
  ch => (ch === '\\' ? '\\\\' : '\\x' + ch.charCodeAt(0).toString(16).padStart(2, '0')));

const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);

// RM-811 residuals: JSON-RPC 2.0 section 4 - an id is a string, a number or
// null (JSON.parse never yields a non-finite number).
const isValidId = v => v === null || typeof v === 'string' || typeof v === 'number';

rl.on('line', async (raw) => {
  // RM-811: one bad line must never end the server. A JSON `null` line threw
  // on the destructure below inside this async handler - an unhandled
  // rejection, so Node exited 1 and the MCP client lost the server.
  let id = null;
  try {
    await handleLine(raw, rid => { id = rid; });
  } catch (e) {
    process.stderr.write(`usage-mcp: internal error: ${scrubLog(e && e.message)}\n`);
    if (id !== null && id !== undefined) rpcError(id, -32603, 'Internal error');
  }
});

async function handleLine(raw, noteId) {
  const line = raw.trim();
  if (!line) return;
  let msg;
  // RM-811: JSON-RPC 2.0 answers a parse error and an invalid request (any
  // JSON that is not an object; batches are not supported) with id null,
  // rather than dropping the line with no reply.
  try { msg = JSON.parse(line); } catch {
    rpcError(null, -32700, 'Parse error');
    return;
  }
  if (!isObject(msg)) {
    rpcError(null, -32600, 'Invalid Request');
    return;
  }

  const { id, method, params } = msg;

  // RM-811 residuals: an object / array / boolean id was echoed in an
  // ordinary reply. A present id of the wrong type makes the request
  // invalid (it is not a notification either): -32600 with id null, before
  // the id is noted for the internal-error reply.
  if (id !== undefined && !isValidId(id)) {
    rpcError(null, -32600, 'Invalid Request');
    return;
  }
  noteId(id);

  // RM-811 (the RM-769 shape): the method must be a string.
  if (typeof method !== 'string') {
    rpcError(id === undefined ? null : id, -32600, 'Invalid Request');
    return;
  }

  if (method === 'initialize') {
    send({ jsonrpc: '2.0', id, result: {
      protocolVersion: '2024-11-05',
      capabilities: { tools: {} },
      serverInfo: { name: 'anthropic-usage', version: '1.0.0' },
    }});
  } else if (method === 'notifications/initialized' || method === 'initialized') {
    // no response
  } else if (method === 'ping') {
    send({ jsonrpc: '2.0', id, result: {} });
  } else if (method === 'tools/list') {
    send({ jsonrpc: '2.0', id, result: { tools: TOOLS } });
  } else if (method === 'tools/call') {
    // RM-811: params, when present, is an object (JSON-RPC 2.0 4.2; named
    // params): anything else is -32602, not a "Unknown tool" result.
    if (params !== undefined && params !== null && !isObject(params)) {
      if (id !== undefined) rpcError(id, -32602, 'Invalid params');
      return;
    }
    const name = params?.name;
    const args = params?.arguments || {};
    try {
      let text;
      if (name === 'query_usage') {
        text = await queryUsage(args.start_date || yesterday(), args.end_date || yesterday());
      } else {
        text = `Unknown tool: ${name}`;
      }
      send({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text }] } });
    } catch (e) {
      send({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: `Error: ${e.message}` }], isError: true } });
    }
  } else if (id !== undefined) {
    send({ jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } });
  }
}
