// Riot Commander - Pengu Loader plugin (Electron Phase 6, Surface C stub).
//
// Runs INSIDE the League client UX via Pengu Loader (https://pengu.lol).
// It fetches RC_ORIGIN/api/state from the local Riot Commander dashboard
// (:8888) and renders a compact coach panel styled with the dashboard's
// own design tokens (web/css/tokens.css, served at RC_ORIGIN/css/tokens.css).
//
// CORS: the client UX origin (https://127.0.0.1:<port>) is cross-origin to
// RC_ORIGIN, so the dashboard echoes that loopback Origin in
// Access-Control-Allow-Origin (OVL2 gate in dashboard/_handler.py).
//
// CODE-ONLY STUB: live in-client validation is OWED (no League client in the
// headless run). The structural contract is pinned by
// tests/test_pengu_plugin_skeleton.py.

const PANEL_ID = "rc-pengu-panel";
const DEFAULT_ORIGIN = "https://127.0.0.1:8888";
const POLL_MS = 2000; // 2 Hz, matches the dashboard; never sub-500ms (cost rule).

// RC_ORIGIN is operator-overridable from the client console:
//   window.localStorage.setItem("rc_origin", "https://legion-rc:8888")
function rcOrigin() {
  try {
    const v = window.localStorage && window.localStorage.getItem("rc_origin");
    if (v) return v.replace(/\/+$/, "");
  } catch (_e) { /* localStorage may be unavailable in some contexts */ }
  return DEFAULT_ORIGIN;
}

function injectStylesheet(href, id) {
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
}

function buildPanel() {
  let panel = document.getElementById(PANEL_ID);
  if (panel) return panel;
  panel = document.createElement("div");
  panel.id = PANEL_ID;
  panel.className = "rc-pengu";
  panel.innerHTML =
    '<header class="rc-pengu-head">Riot Commander</header>' +
    '<div class="rc-pengu-body">' +
    '<div class="rc-pengu-row"><span class="rc-pengu-k">mode</span>' +
    '<span class="rc-pengu-v" data-field="mode">-</span></div>' +
    '<div class="rc-pengu-row"><span class="rc-pengu-k">champion</span>' +
    '<span class="rc-pengu-v" data-field="champion">-</span></div>' +
    '<div class="rc-pengu-row"><span class="rc-pengu-k">coach</span>' +
    '<span class="rc-pengu-v" data-field="coach">-</span></div>' +
    '</div>' +
    '<footer class="rc-pengu-foot" data-field="status">connecting</footer>';
  document.body.appendChild(panel);
  return panel;
}

function setField(panel, name, value) {
  const el = panel.querySelector('[data-field="' + name + '"]');
  if (el) el.textContent = value == null || value === "" ? "-" : String(value);
}

async function refresh(panel, origin) {
  try {
    const res = await fetch(origin + "/api/state", { method: "GET", mode: "cors" });
    if (!res.ok) throw new Error("http " + res.status);
    const s = await res.json();
    setField(panel, "mode", s.mode_key || s.mode || "-");
    const lc = s.liveclient || {};
    setField(panel, "champion", lc.champion || (s.coach && s.coach.champion) || "-");
    setField(panel, "coach", (s.coach && (s.coach.action || s.coach.immediate)) || "-");
    setField(panel, "status", "live");
    panel.classList.remove("rc-pengu-offline");
  } catch (_e) {
    // Fail-soft: never throw into the client UX. Never surface a raw API
    // error string (RC error-handling rule) - show a friendly degraded note.
    setField(panel, "status", "RC offline - retrying");
    panel.classList.add("rc-pengu-offline");
  }
}

let _started = false;
function init() {
  if (_started) return;
  _started = true;
  const origin = rcOrigin();
  injectStylesheet(origin + "/css/tokens.css", "rc-pengu-tokens");
  // Panel stylesheet is a sibling of this module; resolve via import.meta.url
  // so it loads regardless of where Pengu mounts the plugin.
  try {
    injectStylesheet(new URL("./panel.css", import.meta.url).href, "rc-pengu-panel-css");
  } catch (_e) { /* import.meta unavailable -> token vars still apply inline */ }
  const panel = buildPanel();
  refresh(panel, origin);
  setInterval(() => refresh(panel, origin), POLL_MS);
}

// Pengu Loader calls the default export (if present) on plugin load and also
// runs top-level module code. Guard so either entry path mounts exactly once.
if (typeof window !== "undefined" && window.document) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
}

export default init;
