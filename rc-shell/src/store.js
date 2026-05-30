// rc-shell/src/store.js
//
// PURE persistence. NO electron import. The file path is passed in so this is
// testable with a tmp path. main.js wires it to app.getPath("userData") +
// "rc-shell-state.json".
//
// Atomic-write discipline (mirrors the RC repo hard rule: write tmp, then
// rename). A corrupt or missing file never throws on read - load() returns the
// provided fallback (or {}). This keeps a partially-written or hand-edited file
// from crashing the shell on launch.

"use strict";

const fs = require("fs");
const path = require("path");

// Read + parse the JSON state file. Never throws:
//   - missing file        -> fallback
//   - unreadable / EACCES  -> fallback
//   - invalid JSON         -> fallback
//   - JSON that is not an object (array / number / null) -> fallback
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
// false on failure (never throws - persistence is best-effort; a failed save
// must not take the window down). Writes to "<file>.tmp" then renames over the
// target so a concurrent reader never sees a half-written file.
function save(filePath, data) {
  try {
    const dir = path.dirname(filePath);
    try {
      fs.mkdirSync(dir, { recursive: true });
    } catch (_mk) {
      // dir may already exist; ignore.
    }
    const tmp = filePath + ".tmp";
    const json = JSON.stringify(data === undefined ? {} : data, null, 2);
    fs.writeFileSync(tmp, json, "utf8");
    fs.renameSync(tmp, filePath);
    return true;
  } catch (_e) {
    return false;
  }
}

module.exports = { load, save };
