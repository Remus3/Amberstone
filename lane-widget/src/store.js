// lane-widget/src/store.js
//
// PURE persistence for the lane widget. NO electron import - the file path is
// passed in, so this is testable against a tmp path. main.js wires it to
// app.getPath("userData") + STATE_FILE_NAME.
//
// This is deliberately the same shape as rc-shell/src/store.js (atomic tmp +
// rename, a load() that never throws) applied to a DIFFERENT state file. The two
// apps must never share one file: each has its own userData directory and its
// own single-instance lock.
//
// normalizeState is here rather than in main.js so the persisted schema has a
// unit-tested home - main.js stays electron glue with no logic of its own.

"use strict";

const fs = require("fs");
const path = require("path");

const STATE_FILE_NAME = "lane-widget-state.json";

// Cadence floor. The fast tick reads 2 small lock files per repo, so it is
// cheap, but nothing good comes of letting an operator set it to 1 ms.
const MIN_FAST_MS = 500;
const MAX_FAST_MS = 60000;

// Exactly the persisted keys - the guard test pins this list.
const DEFAULTS = Object.freeze({
  x: null,
  y: null,
  width: 420,
  height: 320,
  opacity: 0.94,
  alwaysOnTop: true,
  showFree: true,
  fastMs: 2000,
});

// Read + parse the JSON state file. Never throws:
//   - missing file        -> fallback
//   - unreadable / EACCES -> fallback
//   - invalid JSON        -> fallback
//   - JSON that is not a plain object (array / number / null) -> fallback
// fallback defaults to {} so callers can always spread it safely.
function load(filePath, fallback) {
  const fb = fallback === undefined ? {} : fallback;
  try {
    const raw = fs.readFileSync(filePath, "utf8");
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed;
    }
    return fb;
  } catch (_e) {
    return fb;
  }
}

// Atomically write the state object as pretty JSON. Returns true on success,
// false on failure (never throws - persistence is best effort; a failed save
// must not take the window down). Writes "<file>.tmp" then renames over the
// target so a concurrent reader never sees a half-written file.
function save(filePath, data) {
  const tmp = filePath + ".tmp";
  try {
    const dir = path.dirname(filePath);
    try {
      fs.mkdirSync(dir, { recursive: true });
    } catch (_mk) {
      // dir may already exist; ignore.
    }
    const json = JSON.stringify(data === undefined ? {} : data, null, 2);
    fs.writeFileSync(tmp, json, "utf8");
    fs.renameSync(tmp, filePath);
    return true;
  } catch (_e) {
    // Best effort cleanup so a failed write leaves no .tmp turd behind.
    try {
      fs.unlinkSync(tmp);
    } catch (_u) {
      // nothing to clean up.
    }
    return false;
  }
}

function numOr(v, fallback) {
  return typeof v === "number" && isFinite(v) ? v : fallback;
}

function posOr(v, fallback) {
  return typeof v === "number" && isFinite(v) && v > 0 ? v : fallback;
}

function boolOr(v, fallback) {
  return typeof v === "boolean" ? v : fallback;
}

// Coerce whatever is on disk into exactly the DEFAULTS shape. Unknown keys are
// dropped, junk values fall back, ranges are clamped. Never throws.
function normalizeState(raw) {
  const s = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  const opacity = numOr(s.opacity, DEFAULTS.opacity);
  const fastMs = posOr(s.fastMs, DEFAULTS.fastMs);
  return {
    // x/y stay null until the window has actually been placed (centre me).
    x: typeof s.x === "number" && isFinite(s.x) ? s.x : null,
    y: typeof s.y === "number" && isFinite(s.y) ? s.y : null,
    width: posOr(s.width, DEFAULTS.width),
    height: posOr(s.height, DEFAULTS.height),
    opacity: Math.min(1, Math.max(0.1, opacity)),
    alwaysOnTop: boolOr(s.alwaysOnTop, DEFAULTS.alwaysOnTop),
    showFree: boolOr(s.showFree, DEFAULTS.showFree),
    fastMs: Math.min(MAX_FAST_MS, Math.max(MIN_FAST_MS, fastMs)),
  };
}

module.exports = {
  STATE_FILE_NAME,
  DEFAULTS,
  MIN_FAST_MS,
  MAX_FAST_MS,
  load,
  save,
  normalizeState,
};
