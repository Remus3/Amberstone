// rc-shell/src/nav_guard.js
//
// PURE navigation / external-link policy. NO electron import - the testable
// core behind two main.js hooks (PKG Q/A 2026-10-26, docs/PACKAGING_PLAN.md):
//
//   1. setWindowOpenHandler used to hand ANY url to shell.openExternal. That
//      call launches whatever protocol handler Windows has registered for the
//      scheme (file:, ms-settings:, search-ms:, a custom app scheme), so a
//      target=_blank link or window.open() on the loaded page could start an
//      arbitrary local handler. Electron's security checklist: never pass
//      untrusted content to openExternal. Only http: and https: go out now.
//
//   2. The companion and overlay windows carry the rcShell preload bridge, and
//      nothing stopped an in-window navigation to another origin, which would
//      have kept the bridge (IPC to main) on a foreign page. will-navigate now
//      keeps every window on the RC origin; a cross-origin link opens in the
//      default browser instead (when it is http/https), never in the shell.
//
// Same origin = same scheme + host + port (URL.origin). Hash / query changes
// and same-origin route changes stay in the window, so the dashboard's own
// navigation is untouched.

"use strict";

const EXTERNAL_SCHEMES = Object.freeze(["http:", "https:"]);

// Parse a string URL or return null (never throws).
function parseUrl(value) {
  if (typeof value !== "string" || !value.trim()) {
    return null;
  }
  try {
    return new URL(value.trim());
  } catch (_e) {
    return null;
  }
}

// True only for an absolute http(s) URL with a host - the one shape that is
// safe to hand to shell.openExternal (it opens the default browser and
// nothing else).
function isSafeExternalUrl(url) {
  const u = parseUrl(url);
  if (!u) {
    return false;
  }
  return EXTERNAL_SCHEMES.includes(u.protocol) && u.hostname !== "";
}

// True when url is on exactly the same origin (scheme + host + port) as
// origin. A malformed or opaque ("null") origin on either side is never a
// match, so a bad configuration fails closed.
function isSameOrigin(url, origin) {
  const a = parseUrl(url);
  const b = parseUrl(origin);
  if (!a || !b) {
    return false;
  }
  if (a.origin === "null" || b.origin === "null") {
    return false;
  }
  return a.origin === b.origin;
}

// The decision main.js applies on will-navigate:
//   { allow: true }                       - stay in the window (same origin)
//   { allow: false, openExternal: true }  - block, open in the default browser
//   { allow: false, openExternal: false } - block outright (unsafe scheme)
function navigationDecision(url, origin) {
  if (isSameOrigin(url, origin)) {
    return { allow: true, openExternal: false };
  }
  return { allow: false, openExternal: isSafeExternalUrl(url) };
}

module.exports = {
  EXTERNAL_SCHEMES,
  isSafeExternalUrl,
  isSameOrigin,
  navigationDecision,
};
