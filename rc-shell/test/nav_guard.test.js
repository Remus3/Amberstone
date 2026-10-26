// rc-shell/test/nav_guard.test.js
//
// PKG Q/A 2026-10-26 (docs/PACKAGING_PLAN.md, findings M1 + M2): the pure
// external-link / navigation policy, plus source-contract checks that main.js
// routes every window-open and every companion/overlay navigation through it.
// NO electron. Run with: npm test

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const nav = require("../src/nav_guard");

const ORIGIN = "https://127.0.0.1:8888";
const MAIN_SRC = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");

// ---- isSafeExternalUrl ------------------------------------------------------

test("isSafeExternalUrl: http and https with a host are allowed", () => {
  assert.strictEqual(nav.isSafeExternalUrl("https://example.com/x?y=1"), true);
  assert.strictEqual(nav.isSafeExternalUrl("http://127.0.0.1:8860/health"), true);
  assert.strictEqual(nav.isSafeExternalUrl("  https://example.com  "), true);
});

test("isSafeExternalUrl: every non-http(s) scheme is refused", () => {
  const bad = [
    "file:///C:/Windows/System32/calc.exe",
    "ms-settings:privacy",
    "search-ms:query=x",
    "javascript:alert(1)",
    "data:text/html,<b>x</b>",
    "vbscript:msgbox(1)",
    "smb://host/share",
    "mailto:a@example.com",
    "about:blank",
  ];
  for (const url of bad) {
    assert.strictEqual(nav.isSafeExternalUrl(url), false, url);
  }
});

test("isSafeExternalUrl: garbage never throws and is refused", () => {
  for (const v of [undefined, null, "", "   ", 42, {}, [], "not a url", "//host/x", "/relative"]) {
    assert.strictEqual(nav.isSafeExternalUrl(v), false, String(v));
  }
});

// ---- isSameOrigin -----------------------------------------------------------

test("isSameOrigin: same scheme + host + port matches, path/query/hash ignored", () => {
  assert.strictEqual(nav.isSameOrigin("https://127.0.0.1:8888/?overlay=1#x", ORIGIN), true);
  assert.strictEqual(nav.isSameOrigin("https://127.0.0.1:8888/api/state", ORIGIN), true);
});

test("isSameOrigin: a different scheme, host or port is a different origin", () => {
  assert.strictEqual(nav.isSameOrigin("http://127.0.0.1:8888/", ORIGIN), false);
  assert.strictEqual(nav.isSameOrigin("https://localhost:8888/", ORIGIN), false);
  assert.strictEqual(nav.isSameOrigin("https://127.0.0.1:8860/", ORIGIN), false);
  assert.strictEqual(nav.isSameOrigin("https://evil.example/", ORIGIN), false);
});

test("isSameOrigin: opaque or malformed input fails closed", () => {
  assert.strictEqual(nav.isSameOrigin("about:blank", ORIGIN), false);
  assert.strictEqual(nav.isSameOrigin("data:text/html,x", "data:text/html,x"), false);
  assert.strictEqual(nav.isSameOrigin(ORIGIN, ""), false);
  assert.strictEqual(nav.isSameOrigin(ORIGIN, undefined), false);
  assert.strictEqual(nav.isSameOrigin(undefined, ORIGIN), false);
});

// ---- navigationDecision -----------------------------------------------------

test("navigationDecision: same origin stays in the window", () => {
  assert.deepStrictEqual(nav.navigationDecision(ORIGIN + "/?overlay=1", ORIGIN), {
    allow: true,
    openExternal: false,
  });
});

test("navigationDecision: cross-origin http(s) is blocked and opened externally", () => {
  assert.deepStrictEqual(nav.navigationDecision("https://example.com/", ORIGIN), {
    allow: false,
    openExternal: true,
  });
});

test("navigationDecision: an unsafe scheme is blocked outright", () => {
  assert.deepStrictEqual(nav.navigationDecision("file:///C:/x.exe", ORIGIN), {
    allow: false,
    openExternal: false,
  });
});

test("navigationDecision: a broken configured origin blocks everything (fails closed)", () => {
  assert.strictEqual(nav.navigationDecision(ORIGIN + "/", "").allow, false);
});

// ---- main.js wiring (source contract) ---------------------------------------

test("main.js calls shell.openExternal in exactly one place, behind the guard", () => {
  const calls = MAIN_SRC.match(/shell\.openExternal\(/g) || [];
  assert.strictEqual(calls.length, 1, "one guarded call site only");
  const fn = MAIN_SRC.slice(MAIN_SRC.indexOf("function openExternalSafe("));
  const body = fn.slice(0, fn.indexOf("\n}\n"));
  assert.ok(body.includes("nav.isSafeExternalUrl(url)"), "the call site checks the scheme first");
  assert.ok(body.includes("shell.openExternal(url)"), "the guarded call lives in openExternalSafe");
});

test("main.js guards both bridge-carrying windows (companion + overlay)", () => {
  assert.ok(MAIN_SRC.includes("guardNavigation(mainWindow)"), "companion guarded");
  assert.ok(MAIN_SRC.includes("guardNavigation(overlayWindow)"), "overlay guarded");
  const fn = MAIN_SRC.slice(MAIN_SRC.indexOf("function guardNavigation("));
  const body = fn.slice(0, fn.indexOf("\n}\n"));
  assert.ok(body.includes("setWindowOpenHandler"), "window.open is denied");
  assert.ok(body.includes('"will-navigate"'), "in-window navigation is checked");
  assert.ok(body.includes("nav.navigationDecision("), "through the pure decision");
  assert.ok(body.includes("event.preventDefault()"), "a refused navigation is cancelled");
});

test("main.js has no unguarded window-open handler left", () => {
  // Every setWindowOpenHandler is either the guard's own or the toggle icon's
  // flat deny (a local file page with no links).
  const handlers = MAIN_SRC.match(/setWindowOpenHandler\(/g) || [];
  assert.strictEqual(handlers.length, 2, "guardNavigation + toggle icon only");
  assert.ok(
    MAIN_SRC.includes('toggleWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }))'),
    "the toggle icon keeps its flat deny"
  );
});
