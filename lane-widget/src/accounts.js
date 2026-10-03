"use strict";
/**
 * The ACCOUNTS strip: the proxy's per-account unified rate-limit readings,
 * reduced to one line per account, labelled by ROLE.
 *
 * Source (MAIN 0925 addendum): the proxy keeps Anthropic's unified rate-limit
 * readings per account in its STATE file, under `quota[]`:
 *
 *   { name, accountUuid, ..., quota: { unified5h, unified7d,
 *     unified5hReset, unified7dReset, unifiedStatus, ... } }
 *
 *   unified5h / unified7d          fraction of the window used (0.23)
 *   unified5hReset / unified7dReset epoch MILLISECONDS
 *   unifiedStatus                  "allowed", or a limited status
 *
 * IDENTIFIERS NEVER LEAVE THIS MODULE. name / accountUuid / orgUuid / orgName
 * are used only to MATCH an entry to a role from the gitignored roster; the
 * descriptor and the rendered lines carry the role label and numbers only, so
 * nothing identifying crosses IPC or reaches the panel.
 *
 * This widget only READS the state file - poll.js hands the raw text and mtime
 * in, this module never touches a disk. Pure: the clock arrives as `now`
 * (epoch SECONDS).
 *
 * Rendered grammar:
 *
 *   Headless     5h 23% (resets 2h10m)   7d 7% (resets 3d4h)   allowed
 *   Interactive  no data - not signed in to the proxy
 *   Accounts: no signal [<age>]
 *
 * NO SIGNAL is total: an absent file, unparseable JSON, a `quota` that is not
 * an array, or a file older than 2x the probe interval all render one
 * "Accounts: no signal" line - never the stale numbers the file still carries.
 */

const DEFAULT_PROBE_S = 300;
const LABEL_WIDTH = 11; // "Interactive" - the label column the addendum shows
const MAX_ROLE_CHARS = 16;
const MAX_STATUS_CHARS = 24;
const UNKNOWN = "?";
const NO_DATA = "no data - not signed in to the proxy";
const ALLOWED = "allowed";

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function finiteOrNull(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * A span in seconds -> "<n>m" under 120 minutes, then "<h>h<m>m" under a day,
 * then "<d>d<h>h". A zero trailing part is dropped ("2h", "1d").
 *
 * mode "ceil" for a countdown (never understate what is left), "floor" for an
 * age. The unit is decided on the ROUNDED minute count. Absent, negative or
 * non-finite -> "?".
 */
function formatDuration(seconds, mode) {
  const sec = finiteOrNull(seconds);
  if (sec === null || sec < 0) return UNKNOWN;
  const minutes = mode === "ceil" ? Math.ceil(sec / 60) : Math.floor(sec / 60);
  if (minutes < 120) return minutes + "m";
  if (minutes < 24 * 60) {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return h + "h" + (m === 0 ? "" : m + "m");
  }
  const d = Math.floor(minutes / (24 * 60));
  const h = Math.floor((minutes % (24 * 60)) / 60);
  return d + "d" + (h === 0 ? "" : h + "h");
}

/** The quota[] array, or null for every shape that is not one. */
function parseState(text) {
  if (typeof text !== "string" || text.trim() === "") return null;
  let blob;
  try {
    blob = JSON.parse(text);
  } catch (_err) {
    return null;
  }
  if (!isObject(blob) || !Array.isArray(blob.quota)) return null;
  return blob.quota;
}

// Anything shaped like an email or a uuid is an identifier, wherever it shows
// up - including a role label typed into the roster by mistake.
const IDENTIFIER_RE = /@|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

/** A printable-ASCII role label, or null when it is junk or an identifier. */
function cleanRole(v) {
  if (typeof v !== "string") return null;
  const ascii = v.replace(/[^\x20-\x7e]/g, "").replace(/\s+/g, " ").trim();
  if (ascii === "" || IDENTIFIER_RE.test(ascii)) return null;
  return ascii.slice(0, MAX_ROLE_CHARS).trim();
}

function cleanStatus(v) {
  if (typeof v !== "string") return null;
  const ascii = v.replace(/[^\x20-\x7e]/g, "").trim();
  if (ascii === "" || IDENTIFIER_RE.test(ascii)) return null;
  return ascii.slice(0, MAX_STATUS_CHARS);
}

/** The numbers for one quota entry, or null when it carries no data at all. */
function readingOf(entry, nowS) {
  const q = isObject(entry) && isObject(entry.quota) ? entry.quota : null;
  if (q === null) return null;
  const fiveH = finiteOrNull(q.unified5h);
  const sevenD = finiteOrNull(q.unified7d);
  const fiveHReset = finiteOrNull(q.unified5hReset);
  const sevenDReset = finiteOrNull(q.unified7dReset);
  const status = cleanStatus(q.unifiedStatus);
  if (fiveH === null && sevenD === null && fiveHReset === null && sevenDReset === null && status === null) {
    return null;
  }
  const until = (ms) => (ms === null || nowS === null ? null : Math.max(0, ms / 1000 - nowS));
  return {
    fiveHPct: fiveH === null ? null : Math.round(fiveH * 100),
    fiveHResetS: until(fiveHReset),
    sevenDPct: sevenD === null ? null : Math.round(sevenD * 100),
    sevenDResetS: until(sevenDReset),
    status,
  };
}

function matches(entry, key) {
  return isObject(entry) && typeof key === "string" && key !== "" && entry.accountUuid === key;
}

/**
 * accountsFor({ text, mtimeMs, now, probeS, roles }) -> descriptor:
 *
 *   { kind: "nosignal", ageS }                    ageS null when unknown
 *   { kind: "live", accounts: [ { role, reading } ] }   reading null = no data
 *
 * roles: [ { account_uuid, role } ] in strip order, from the gitignored roster.
 * Rostered roles come first in roster order (a role whose account is absent
 * from quota[] is "no data"); quota entries no role claims follow, labelled
 * positionally. Total: junk in returns "nosignal", never a throw.
 */
function accountsFor(opts) {
  const o = isObject(opts) ? opts : {};
  const now = finiteOrNull(o.now);
  const probeRaw = finiteOrNull(o.probeS);
  const probeS = probeRaw === null || probeRaw <= 0 ? DEFAULT_PROBE_S : probeRaw;
  const mtimeMs = finiteOrNull(o.mtimeMs);
  const ageS = mtimeMs === null || now === null ? null : Math.max(0, now - mtimeMs / 1000);

  const quota = parseState(o.text);
  if (quota === null) return { kind: "nosignal", ageS };
  if (ageS === null || ageS > 2 * probeS) return { kind: "nosignal", ageS };

  const roles = Array.isArray(o.roles) ? o.roles.filter(isObject) : [];
  const claimed = new Set();
  const accounts = [];
  for (const r of roles) {
    const idx = quota.findIndex((e, i) => !claimed.has(i) && matches(e, r.account_uuid));
    if (idx !== -1) claimed.add(idx);
    accounts.push({
      role: cleanRole(r.role),
      reading: idx === -1 ? null : readingOf(quota[idx], now),
    });
  }
  quota.forEach((entry, i) => {
    if (claimed.has(i) || !isObject(entry)) return;
    accounts.push({ role: null, reading: readingOf(entry, now) });
  });
  return { kind: "live", accounts };
}

function pct(v) {
  return (v === null ? UNKNOWN : v) + "%";
}

/**
 * accountsLines(descriptor) -> { nosignal, lines: [ { text, alarm } ] }
 *
 * A non-"allowed" status is alarm-styled. A null status beside real numbers
 * (the probe can read utilization without a status) renders "?" and is NOT an
 * alarm - there is no limited status to warn about. No signal is one alarm
 * line.
 */
function accountsLines(desc) {
  const d = isObject(desc) ? desc : { kind: "nosignal", ageS: null };
  if (d.kind !== "live" || !Array.isArray(d.accounts)) {
    return {
      nosignal: true,
      lines: [{ text: "Accounts: no signal [" + formatDuration(d.ageS, "floor") + "]", alarm: true }],
    };
  }
  const labels = d.accounts.map((acc, i) => (acc && acc.role) || "Account " + (i + 1));
  const width = labels.reduce((w, l) => Math.max(w, l.length), LABEL_WIDTH);
  const lines = d.accounts.map((acc, i) => {
    const head = labels[i].padEnd(width) + "  ";
    const r = acc && isObject(acc.reading) ? acc.reading : null;
    if (r === null) return { text: head + NO_DATA, alarm: false };
    const status = r.status === null ? UNKNOWN : r.status;
    return {
      text: head +
        "5h " + pct(r.fiveHPct) + " (resets " + formatDuration(r.fiveHResetS, "ceil") + ")   " +
        "7d " + pct(r.sevenDPct) + " (resets " + formatDuration(r.sevenDResetS, "ceil") + ")   " +
        status,
      alarm: r.status !== null && r.status !== ALLOWED,
    };
  });
  return { nosignal: false, lines };
}

module.exports = {
  DEFAULT_PROBE_S,
  NO_DATA,
  formatDuration,
  parseState,
  accountsFor,
  accountsLines,
};
