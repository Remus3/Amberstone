"use strict";
/**
 * Resolve the repo roster the widget observes.
 *
 * Pure: the clock and every filesystem read arrive as parameters. No electron,
 * no top-level IO, no writes ever - this widget is a READ-ONLY observer.
 *
 * LEAK RULE. Sibling identity is host CONFIG, never repo content. It is read at
 * runtime from the gitignored ops/moon_sync_repos.json and rendered as the
 * participant CODE only. A checkout directory BASENAME is itself a sibling
 * name, so an unmapped root gets a POSITIONAL placeholder instead - see
 * `codeFor`. Mirrors the intent of tools/moon_sync_poller.py:206-217, whose own
 * comment says "The leaf name is NEVER used".
 *
 * Schema, from tracked ops/moon_sync_repos.example.json:
 *   { repos: ["<abs path>", ...], participants: { "<CODE>": "<abs path>" } }
 * RC_MOON_SYNC_REPOS (os.pathsep separated) OVERRIDES the file -
 * tools/moon_sync_poller.py:158-165.
 */

// <rcRoot>/ops/moon_sync_repos.json
const REPO_CONFIG_REL = ["ops", "moon_sync_repos.json"];

// os.pathsep on win32. tools/moon_sync_poller.py:161 splits on os.pathsep.
const PATH_DELIM = ";";

const SELF_CODE = "RC";

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Join with whichever separator the root already uses - no path module, so
 *  a POSIX test run produces the same string a Windows one does. */
function joinPath(root, ...parts) {
  const base = String(root === undefined || root === null ? "" : root);
  const sep = base.indexOf("\\") >= 0 || /^[A-Za-z]:$/.test(base) ? "\\" : "/";
  const trimmed = base.replace(/[\\/]+$/, "");
  const tail = parts
    .map((p) => String(p === undefined || p === null ? "" : p).replace(/^[\\/]+|[\\/]+$/g, ""))
    .filter((p) => p.length > 0);
  if (tail.length === 0) return trimmed;
  return [trimmed, ...tail].join(sep);
}

/**
 * The comparison form of a repo root. Case and separators differ freely between
 * the config, an env override and a Path round trip - mirrors
 * tools/moon_sync_poller.py:174-178 `_norm_root`.
 */
function normRoot(path) {
  if (typeof path !== "string") return "";
  const unified = path.replace(/\//g, "\\").replace(/\\+/g, "\\");
  return unified.replace(/\\+$/, "").toLowerCase();
}

function readJson(readFile, absPath) {
  if (typeof readFile !== "function") return null;
  let raw;
  try {
    raw = readFile(absPath);
  } catch (_err) {
    return null; // fail soft - a missing or unreadable config is not an error
  }
  if (typeof raw !== "string" || raw.trim() === "") return null;
  let blob;
  try {
    blob = JSON.parse(raw);
  } catch (_err) {
    return null;
  }
  return isObject(blob) ? blob : null;
}

/** { normalised root -> CODE }. Non-string values are ignored. */
function participantsOf(blob) {
  const map = new Map();
  if (!isObject(blob) || !isObject(blob.participants)) return map;
  for (const [code, path] of Object.entries(blob.participants)) {
    if (typeof path !== "string" || path.trim() === "") continue;
    if (typeof code !== "string" || code.trim() === "") continue;
    map.set(normRoot(path), code);
  }
  return map;
}

function rootsFromEnv(env) {
  if (!isObject(env) && typeof env !== "function") return null;
  const raw = env.RC_MOON_SYNC_REPOS;
  if (typeof raw !== "string") return null;
  const parts = raw.split(PATH_DELIM).map((p) => p.trim()).filter((p) => p !== "");
  return parts.length > 0 ? parts : null;
}

function rootsFromBlob(blob) {
  if (!isObject(blob) || !Array.isArray(blob.repos)) return [];
  return blob.repos
    .filter((p) => typeof p === "string" && p.trim() !== "")
    .map((p) => p.trim());
}

/**
 * The rendered code for a root.
 *
 * A participant match wins. Otherwise the code is the POSITIONAL string
 * "REPO-<n>" where n is the 1-based roster index - never the directory
 * basename, which would leak a sibling name onto a rendered surface.
 */
function codeFor(root, participants, index) {
  const mapped = participants.get(normRoot(root));
  if (typeof mapped === "string" && mapped.trim() !== "") return mapped;
  return index === 0 ? SELF_CODE : `REPO-${index + 1}`;
}

/**
 * resolveRepos({ rcRoot, env, readFile }) -> [ { code, root, isSelf } ]
 *
 * readFile: (absPath) => string | null   (null on any error - fail soft)
 *
 * RC is ALWAYS index 0. A missing or corrupt config yields RC only, which is
 * the CORRECT fresh-clone answer and not an error. Total: every junk shape
 * returns at least the RC row rather than throwing.
 */
function resolveRepos(opts) {
  const o = isObject(opts) ? opts : {};
  const rcRoot = typeof o.rcRoot === "string" ? o.rcRoot : "";
  const env = isObject(o.env) ? o.env : {};
  const readFile = o.readFile;

  const blob = readJson(readFile, joinPath(rcRoot, ...REPO_CONFIG_REL));
  const participants = participantsOf(blob);

  // The env override replaces the FILE's repo list, but the participants map
  // is still the only place a code can come from, so it is read either way.
  const extra = rootsFromEnv(env) || rootsFromBlob(blob);

  const out = [];
  const seen = new Set();

  const rcKey = normRoot(rcRoot);
  seen.add(rcKey);
  out.push({ code: codeFor(rcRoot, participants, 0), root: rcRoot, isSelf: true });

  for (const root of extra) {
    const key = normRoot(root);
    if (seen.has(key)) continue; // dedupe, and RC is never re-added
    seen.add(key);
    out.push({ code: codeFor(root, participants, out.length), root, isSelf: false });
  }
  return out;
}

module.exports = {
  REPO_CONFIG_REL,
  PATH_DELIM,
  SELF_CODE,
  joinPath,
  normRoot,
  codeFor,
  resolveRepos,
};
