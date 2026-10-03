"use strict";
// accounts.js - the ACCOUNTS strip: the proxy's per-account unified rate-limit
// readings (5-hour and 7-day utilization, resets, status), labelled by ROLE.
//
// MAIN 0925 addendum: the two example lines are asserted VERBATIM. Fixture
// identifiers below are INVENTED (example.invalid emails, made-up uuids); the
// leak test proves none of them ever reaches rendered text.

const test = require("node:test");
const assert = require("node:assert/strict");

const a = require("../src/accounts.js");

// A fixed clock. 2026-10-03T12:00:00Z in epoch SECONDS.
const NOW = Date.parse("2026-10-03T12:00:00Z") / 1000;
const NOW_MS = NOW * 1000;

const UUID_H = "11111111-2222-4333-8444-555555555555";
const UUID_I = "99999999-8888-4777-8666-555555555555";
const ORG_H = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const ORG_I = "ffffffff-eeee-4ddd-8ccc-bbbbbbbbbbbb";
const EMAIL_H = "headless.person@example.invalid";
const EMAIL_I = "interactive.person@example.invalid";

const ROLES = [
  { account_uuid: UUID_H, role: "Headless" },
  { account_uuid: UUID_I, role: "Interactive" },
];

function quota(over) {
  return Object.assign(
    {
      unified5h: null,
      unified7d: null,
      unified7dSonnet: null,
      unified5hReset: null,
      unified7dReset: null,
      unified7dSonnetReset: null,
      unifiedStatus: null,
      tokensLimit: null,
      tokensRemaining: null,
      requestsLimit: null,
      requestsRemaining: null,
      resetsAt: null,
    },
    over || {}
  );
}

const LIVE_H = quota({
  unified5h: 0.23,
  unified7d: 0.07,
  unified5hReset: NOW_MS + (2 * 3600 + 10 * 60) * 1000,
  unified7dReset: NOW_MS + (3 * 86400 + 4 * 3600) * 1000,
  unifiedStatus: "allowed",
});

function stateText(hQuota, iQuota) {
  return JSON.stringify({
    quota: [
      { accountUuid: UUID_I, orgUuid: ORG_I, orgName: EMAIL_I + "'s Organization", name: EMAIL_I, quota: iQuota || quota() },
      { accountUuid: UUID_H, orgUuid: ORG_H, orgName: EMAIL_H + "'s Organization", name: EMAIL_H, quota: hQuota || LIVE_H },
    ],
  });
}

function render(opts) {
  const o = Object.assign(
    { text: stateText(), mtimeMs: NOW_MS - 30 * 1000, now: NOW, probeS: 300, roles: ROLES },
    opts || {}
  );
  return a.accountsLines(a.accountsFor(o));
}

function texts(view) {
  return view.lines.map((l) => l.text);
}

// ---------------------------------------------------- the two verbatim lines

test("the two addendum example lines render verbatim, in roster role order", () => {
  assert.deepEqual(texts(render()), [
    "Headless     5h 23% (resets 2h10m)   7d 7% (resets 3d4h)   allowed",
    "Interactive  no data - not signed in to the proxy",
  ]);
});

test("an allowed account is not in the alarm style", () => {
  const view = render();
  assert.equal(view.lines[0].alarm, false);
  assert.equal(view.nosignal, false);
});

// ------------------------------------------------------------ limited status

test("a limited status renders its word in the alarm style", () => {
  const view = render({ text: stateText(Object.assign({}, LIVE_H, { unified5h: 1, unifiedStatus: "rejected" })) });
  assert.equal(view.lines[0].text, "Headless     5h 100% (resets 2h10m)   7d 7% (resets 3d4h)   rejected");
  assert.equal(view.lines[0].alarm, true);
});

test("a warning status is not 'allowed', so it is alarm-styled too", () => {
  const view = render({ text: stateText(Object.assign({}, LIVE_H, { unifiedStatus: "allowed_warning" })) });
  assert.equal(view.lines[0].alarm, true);
  assert.match(view.lines[0].text, / allowed_warning$/);
});

// --------------------------------------------------------- all-null / absent

test("an all-null quota is no data", () => {
  const view = render({ text: stateText(quota(), quota()) });
  assert.deepEqual(texts(view), [
    "Headless     no data - not signed in to the proxy",
    "Interactive  no data - not signed in to the proxy",
  ]);
});

test("a rostered account missing from quota[] is no data", () => {
  const text = JSON.stringify({ quota: [{ accountUuid: UUID_H, name: EMAIL_H, quota: LIVE_H }] });
  assert.equal(texts(render({ text }))[1], "Interactive  no data - not signed in to the proxy");
});

// --------------------------------------------------------------- no signal --

test("a state file older than 2x the probe interval is no signal with its age", () => {
  const view = render({ mtimeMs: NOW_MS - 11 * 60 * 1000 });
  assert.deepEqual(texts(view), ["Accounts: no signal [11m]"]);
  assert.equal(view.nosignal, true);
  assert.equal(view.lines[0].alarm, true);
});

test("exactly 2x the probe interval is still live; one second past is not", () => {
  assert.equal(render({ mtimeMs: NOW_MS - 600 * 1000 }).nosignal, false);
  assert.equal(render({ mtimeMs: NOW_MS - 601 * 1000 }).nosignal, true);
});

test("the probe interval comes from config", () => {
  assert.equal(render({ mtimeMs: NOW_MS - 15 * 60 * 1000, probeS: 600 }).nosignal, false);
});

test("an absent state file is no signal with an unknown age", () => {
  assert.deepEqual(texts(render({ text: null, mtimeMs: null })), ["Accounts: no signal [?]"]);
});

test("an unparseable or wrong-shape state file is no signal, never a throw", () => {
  assert.deepEqual(texts(render({ text: "{not json" })), ["Accounts: no signal [0m]"]);
  assert.deepEqual(texts(render({ text: JSON.stringify({ quota: "x" }) })), ["Accounts: no signal [0m]"]);
  assert.deepEqual(texts(render({ text: "[]" })), ["Accounts: no signal [0m]"]);
  assert.deepEqual(texts(a.accountsLines(a.accountsFor(null))), ["Accounts: no signal [?]"]);
  assert.deepEqual(texts(a.accountsLines(null)), ["Accounts: no signal [?]"]);
});

test("a long-stale file reports its age in h then d+h", () => {
  assert.deepEqual(texts(render({ mtimeMs: NOW_MS - (5 * 3600 + 7 * 60) * 1000 })), ["Accounts: no signal [5h7m]"]);
  assert.deepEqual(texts(render({ mtimeMs: NOW_MS - (2 * 86400 + 3 * 3600) * 1000 })), ["Accounts: no signal [2d3h]"]);
});

// ------------------------------------------------------- formats and edges --

test("durations: m under 120m, then h with m, then d+h", () => {
  assert.equal(a.formatDuration(0, "ceil"), "0m");
  assert.equal(a.formatDuration(59 * 60 + 1, "ceil"), "60m");
  assert.equal(a.formatDuration(119 * 60, "ceil"), "119m");
  assert.equal(a.formatDuration(120 * 60, "ceil"), "2h");
  assert.equal(a.formatDuration(2 * 3600 + 10 * 60, "ceil"), "2h10m");
  assert.equal(a.formatDuration(23 * 3600 + 59 * 60, "ceil"), "23h59m");
  assert.equal(a.formatDuration(24 * 3600, "ceil"), "1d");
  assert.equal(a.formatDuration(3 * 86400 + 4 * 3600, "ceil"), "3d4h");
  assert.equal(a.formatDuration(3 * 86400 + 4 * 3600 + 1, "floor"), "3d4h");
  assert.equal(a.formatDuration(null, "ceil"), "?");
  assert.equal(a.formatDuration(-5, "ceil"), "?");
});

test("percent is round(fraction * 100)", () => {
  const q = Object.assign({}, LIVE_H, { unified5h: 0.235, unified7d: 0.004 });
  assert.match(render({ text: stateText(q) }).lines[0].text, /^Headless {5}5h 24% .* 7d 0% /);
});

test("a reset already in the past reads 0m, never a negative span", () => {
  const q = Object.assign({}, LIVE_H, { unified5hReset: NOW_MS - 60000 });
  assert.match(render({ text: stateText(q) }).lines[0].text, /5h 23% \(resets 0m\)/);
});

test("data with a null status shows '?' and is not alarm-styled", () => {
  const q = Object.assign({}, LIVE_H, { unifiedStatus: null });
  const line = render({ text: stateText(q) }).lines[0];
  assert.equal(line.text, "Headless     5h 23% (resets 2h10m)   7d 7% (resets 3d4h)   ?");
  assert.equal(line.alarm, false);
});

test("an account the roster does not map gets a positional label, never its identity", () => {
  const view = render({ roles: [{ account_uuid: UUID_H, role: "Headless" }] });
  assert.deepEqual(texts(view), [
    "Headless     5h 23% (resets 2h10m)   7d 7% (resets 3d4h)   allowed",
    "Account 2    no data - not signed in to the proxy",
  ]);
});

test("a role that is itself an identifier is replaced by a positional label", () => {
  const view = render({ roles: [{ account_uuid: UUID_H, role: EMAIL_H }, { account_uuid: UUID_I, role: UUID_I }] });
  assert.ok(view.lines.every((l) => /^Account \d/.test(l.text)), JSON.stringify(view));
});

// ------------------------------------------------------------- leak guard --

test("NO email or uuid from the fixture ever appears in rendered output", () => {
  const forbidden = [UUID_H, UUID_I, ORG_H, ORG_I, EMAIL_H, EMAIL_I, "example.invalid", "@"];
  const cases = [
    render(),
    render({ text: stateText(quota(), quota()) }),
    render({ text: stateText(Object.assign({}, LIVE_H, { unifiedStatus: "rejected" })) }),
    render({ mtimeMs: NOW_MS - 3600 * 1000 }),
    render({ roles: [] }),
    render({ roles: [{ account_uuid: UUID_H, role: EMAIL_H }] }),
  ];
  for (const view of cases) {
    const blob = JSON.stringify(view);
    for (const bad of forbidden) {
      assert.equal(blob.indexOf(bad), -1, "leaked " + bad + " in " + blob);
    }
  }
  // The intermediate descriptor crosses IPC too - it must be clean as well.
  const desc = JSON.stringify(a.accountsFor({ text: stateText(), mtimeMs: NOW_MS, now: NOW, probeS: 300, roles: ROLES }));
  for (const bad of forbidden) assert.equal(desc.indexOf(bad), -1, "descriptor leaked " + bad);
});
