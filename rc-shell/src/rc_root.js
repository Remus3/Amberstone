// rc-shell/src/rc_root.js
//
// Backend-root resolution. NO electron import - the testable core behind
// PACKAGING_PLAN MUST-FIX M3 (docs/PACKAGING_PLAN.md, slice PKG-3).
//
// The bug it closes: main.js resolved the three Win32 hotkey signal files as
// <main.js dir>/../../ops/runtime/*. In a packaged build main.js lives inside
// resources/app.asar/src, so that path points into the installer's resources
// folder, the listener's files are never found, and Ctrl+Shift+A / B / O
// silently stop working in-game. The backend root must be HANDED IN by the
// launcher, never derived from where the shell code happens to sit.
//
// Precedence (first candidate that passes checkRoot wins):
//
//   1. argv   --rc-root=<abs> or --rc-root <abs> (last occurrence wins)
//   2. env    RC_ROOT=<abs> (the name ops/launch_new_system.bat already uses)
//   3. bundled  the caller's packaged backend dir (e.g. resources/backend),
//               consulted ONLY when isPackaged === true
//   4. dev    devDir/../.. where devDir is main.js's own directory, consulted
//             ONLY when isPackaged === false (strictly; an unknown value gets
//             no fallback)
//
// A packaged build with no valid root resolves to NULL - the caller then runs
// with the hotkey signal watches off rather than polling a wrong path. This
// module never reads its own location: the caller passes devDir in.
//
// A candidate must be an absolute local path (no UNC / device path: no
// backend over a network share), must not sit inside an .asar archive, and
// must carry the backend markers main.py + ops/. Rejections are reported as
// {source, reason} only - never the candidate path, so a caller can log them
// without writing a machine path into a log.

"use strict";

const fs = require("fs");
const path = require("path");

const RC_ROOT_ENV = "RC_ROOT";
const RC_ROOT_ARG = "--rc-root";

// What makes a directory an RC backend root. Both are tracked in the repo and
// carried by the packaged bundle (PKG-4).
const ROOT_MARKERS = Object.freeze([
  Object.freeze({ rel: "main.py", kind: "file" }),
  Object.freeze({ rel: "ops", kind: "dir" }),
]);

// The hotkey signal files tools/hotkey_listener.py writes under ops/runtime
// (TOGGLE_SIGNAL_FILE, PANEL_CYCLE_SIGNAL_FILE, VISIBLE_TOGGLE_SIGNAL_FILE)
// and main.js polls: Ctrl+Shift+A, Ctrl+Shift+B, Ctrl+Shift+O.
const SIGNAL_FILES = Object.freeze({
  activeToggle: "overlay_active_toggle.txt",
  panelCycle: "overlay_panel_cycle.txt",
  visibleToggle: "overlay_visible_toggle.txt",
});

// ops/local_hosts.json is a handful of short strings; anything this large is
// not a per-host config and is refused rather than parsed.
const MAX_LOCAL_HOSTS_BYTES = 64 * 1024;

// Real-filesystem probe: "file" | "dir" | null. Never throws.
function defaultProbe(p) {
  if (typeof p !== "string" || !p) {
    return null;
  }
  try {
    const st = fs.statSync(p);
    if (st.isDirectory()) {
      return "dir";
    }
    if (st.isFile()) {
      return "file";
    }
    return null;
  } catch (_e) {
    return null;
  }
}

function safeProbe(probe, p) {
  try {
    return probe(p);
  } catch (_e) {
    return null;
  }
}

// The --rc-root value from an argv array, or null. Both the joined
// (--rc-root=<p>) and the split (--rc-root <p>) form are read; the last
// occurrence wins. A blank value, a dangling flag, or a value that is itself
// a flag counts as not given.
function argRoot(argv) {
  if (!Array.isArray(argv)) {
    return null;
  }
  let found = null;
  for (let i = 0; i < argv.length; i += 1) {
    const tok = argv[i];
    if (typeof tok !== "string") {
      continue;
    }
    if (tok === RC_ROOT_ARG) {
      const next = argv[i + 1];
      if (typeof next === "string" && next.trim() && !next.startsWith("--")) {
        found = next.trim();
        i += 1;
      } else {
        found = null;
      }
    } else if (tok.startsWith(RC_ROOT_ARG + "=")) {
      const v = tok.slice(RC_ROOT_ARG.length + 1).trim();
      found = v || null;
    }
  }
  return found;
}

// True when any path segment is an .asar archive (case-insensitive).
function isInsideAsar(p) {
  return p
    .split(/[\\/]+/)
    .some((seg) => /\.asar$/i.test(seg));
}

// True for a UNC or device path (\\server\share, //server/share, \\?\, \\.\).
function isUncOrDevice(p) {
  return /^[\\/]{2}/.test(p);
}

// Validate one candidate root. Returns {ok, root, reason}; root is the
// resolved absolute path when ok, else null. Never throws.
function checkRoot(candidate, probe) {
  const pr = typeof probe === "function" ? probe : defaultProbe;
  if (typeof candidate !== "string" || !candidate.trim()) {
    return { ok: false, root: null, reason: "empty" };
  }
  const raw = candidate.trim();
  if (isUncOrDevice(raw)) {
    return { ok: false, root: null, reason: "unc-path" };
  }
  if (!path.isAbsolute(raw)) {
    return { ok: false, root: null, reason: "not-absolute" };
  }
  const root = path.resolve(raw);
  if (isInsideAsar(root)) {
    return { ok: false, root: null, reason: "inside-asar" };
  }
  for (const m of ROOT_MARKERS) {
    if (safeProbe(pr, path.join(root, m.rel)) !== m.kind) {
      return { ok: false, root: null, reason: "missing-marker:" + m.rel };
    }
  }
  return { ok: true, root, reason: "ok" };
}

// Resolve the backend root. opts:
//   argv        process.argv
//   env         process.env (only RC_ROOT is read)
//   isPackaged  app.isPackaged (dev fallback only when exactly false)
//   bundledRoot the packaged backend dir (used only when isPackaged === true)
//   devDir      main.js's own directory (used only when isPackaged === false)
//   probe       injectable (path) -> "file" | "dir" | null
// Returns {root, source, rejected}: root null when nothing valid was found.
function resolveRcRoot(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const probe = typeof o.probe === "function" ? o.probe : defaultProbe;
  const env = o.env && typeof o.env === "object" ? o.env : {};
  const rejected = [];

  const candidates = [];
  const a = argRoot(o.argv);
  if (a !== null) {
    candidates.push({ source: "argv", value: a });
  }
  if (typeof env[RC_ROOT_ENV] === "string" && env[RC_ROOT_ENV].trim()) {
    candidates.push({ source: "env", value: env[RC_ROOT_ENV].trim() });
  }
  if (o.isPackaged === true && typeof o.bundledRoot === "string" && o.bundledRoot.trim()) {
    candidates.push({ source: "bundled", value: o.bundledRoot.trim() });
  }
  if (o.isPackaged === false && typeof o.devDir === "string" && o.devDir.trim()) {
    const devDir = o.devDir.trim();
    if (isInsideAsar(devDir)) {
      // resources/app.asar/src/../.. is resources/, which is NOT itself in
      // the asar - so the asar test has to run on devDir, not on the result.
      rejected.push({ source: "dev", reason: "inside-asar" });
    } else if (isUncOrDevice(devDir) || !path.isAbsolute(devDir)) {
      rejected.push({ source: "dev", reason: "not-absolute" });
    } else {
      candidates.push({ source: "dev", value: path.resolve(devDir, "..", "..") });
    }
  }

  for (const c of candidates) {
    const r = checkRoot(c.value, probe);
    if (r.ok) {
      return { root: r.root, source: c.source, rejected };
    }
    rejected.push({ source: c.source, reason: r.reason });
  }
  return { root: null, source: null, rejected };
}

function usableRoot(root) {
  return typeof root === "string" && root.trim() !== "" && path.isAbsolute(root);
}

// <root>/ops/runtime, or null for a missing / relative root.
function runtimeDir(root) {
  return usableRoot(root) ? path.join(root, "ops", "runtime") : null;
}

// <root>/ops/runtime/<name> for a PLAIN file name (no separator, not . / ..),
// else null.
function runtimeFile(root, name) {
  const dir = runtimeDir(root);
  if (!dir || typeof name !== "string") {
    return null;
  }
  const n = name.trim();
  if (!n || n !== name || n === "." || n === ".." || /[\\/]/.test(n)) {
    return null;
  }
  return path.join(dir, n);
}

// The three hotkey signal file paths (frozen), or null without a root.
function signalPaths(root) {
  if (!runtimeDir(root)) {
    return null;
  }
  return Object.freeze({
    activeToggle: runtimeFile(root, SIGNAL_FILES.activeToggle),
    panelCycle: runtimeFile(root, SIGNAL_FILES.panelCycle),
    visibleToggle: runtimeFile(root, SIGNAL_FILES.visibleToggle),
  });
}

// <root>/ops/local_hosts.json (gitignored per-host config, core/local_hosts.py).
function localHostsPath(root) {
  return usableRoot(root) ? path.join(root, "ops", "local_hosts.json") : null;
}

// <root>/ops/tls/rc.pem - the leaf the dashboard serves (dashboard/server.py
// cert_path); tls_pin.js derives the install's pin from it.
function tlsCertPath(root) {
  return usableRoot(root) ? path.join(root, "ops", "tls", "rc.pem") : null;
}

// The per-host config as an object; {} when the root is missing, the file is
// absent / unreadable / oversized / malformed, or the JSON is not an object
// (mirrors core/local_hosts.py load()). readFile is injectable:
// (path) -> string, may throw.
function readLocalHosts(root, readFile) {
  const p = localHostsPath(root);
  if (!p) {
    return {};
  }
  const read = typeof readFile === "function" ? readFile : (f) => fs.readFileSync(f, "utf8");
  try {
    const text = read(p);
    if (typeof text !== "string" || text.length > MAX_LOCAL_HOSTS_BYTES) {
      return {};
    }
    const doc = JSON.parse(text);
    return doc && typeof doc === "object" && !Array.isArray(doc) ? doc : {};
  } catch (_e) {
    return {};
  }
}

module.exports = {
  RC_ROOT_ENV,
  RC_ROOT_ARG,
  ROOT_MARKERS,
  SIGNAL_FILES,
  MAX_LOCAL_HOSTS_BYTES,
  defaultProbe,
  argRoot,
  checkRoot,
  resolveRcRoot,
  runtimeDir,
  runtimeFile,
  signalPaths,
  localHostsPath,
  tlsCertPath,
  readLocalHosts,
};
