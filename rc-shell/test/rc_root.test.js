// rc-shell/test/rc_root.test.js
//
// PKG-3 (docs/PACKAGING_PLAN.md, MUST-FIX M3): the backend-root resolver that
// replaces main.js's `__dirname/../../ops/runtime/*` hotkey signal paths. In a
// packaged build __dirname sits inside resources/app.asar/src, so those paths
// pointed nowhere and Ctrl+Shift+A / B / O stopped working in-game.
//
// Every path here is COMPUTED at runtime (os.tmpdir() based) - no drive-root
// literal lives in this file (pre-push sweep). The filesystem is a fake probe,
// so nothing is created or read on disk except the tracked listener source
// for the cross-language contract check. NO electron. Run with: npm test

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const rr = require("../src/rc_root");

// A computed absolute base that exists on every platform's path grammar.
const BASE = path.join(os.tmpdir(), "rc-pkg3-fixture");
const ROOT_A = path.join(BASE, "backend-a");
const ROOT_B = path.join(BASE, "backend-b");
const ROOT_C = path.join(BASE, "backend-c");
const DEV_SRC = path.join(BASE, "checkout", "rc-shell", "src");
const DEV_ROOT = path.join(BASE, "checkout");

// Fake probe: a map of absolute path -> "file" | "dir". Anything else is
// absent. Mirrors rr.defaultProbe's contract.
function fakeFs(roots) {
  const map = new Map();
  for (const r of roots) {
    map.set(path.join(r, "main.py"), "file");
    map.set(path.join(r, "ops"), "dir");
  }
  return (p) => map.get(p) || null;
}

const ALL = fakeFs([ROOT_A, ROOT_B, ROOT_C, DEV_ROOT]);

// ---- argRoot ----------------------------------------------------------------

test("argRoot: --rc-root=<p> and --rc-root <p> forms are read", () => {
  assert.strictEqual(rr.argRoot(["exe", "--rc-root=" + ROOT_A]), ROOT_A);
  assert.strictEqual(rr.argRoot(["exe", ".", "--rc-root", ROOT_B]), ROOT_B);
});

test("argRoot: the last occurrence wins (later overrides earlier)", () => {
  assert.strictEqual(
    rr.argRoot(["exe", "--rc-root=" + ROOT_A, "--rc-root", ROOT_B]),
    ROOT_B
  );
});

test("argRoot: absent, blank, dangling or flag-valued forms are null", () => {
  assert.strictEqual(rr.argRoot(["exe", "."]), null);
  assert.strictEqual(rr.argRoot(["exe", "--rc-root="]), null);
  assert.strictEqual(rr.argRoot(["exe", "--rc-root=   "]), null);
  assert.strictEqual(rr.argRoot(["exe", "--rc-root"]), null);
  assert.strictEqual(rr.argRoot(["exe", "--rc-root", "--inspect"]), null);
  assert.strictEqual(rr.argRoot(["exe", "--rc-rootx=" + ROOT_A]), null);
});

test("argRoot: garbage argv never throws", () => {
  for (const v of [undefined, null, 42, "str", {}, [null, 5, {}]]) {
    assert.strictEqual(rr.argRoot(v), null);
  }
});

// ---- checkRoot --------------------------------------------------------------

test("checkRoot: an absolute dir carrying main.py + ops/ is a backend root", () => {
  const r = rr.checkRoot(ROOT_A, ALL);
  assert.deepStrictEqual(r, { ok: true, root: path.resolve(ROOT_A), reason: "ok" });
});

test("checkRoot: a relative path is refused (cwd-dependent)", () => {
  const r = rr.checkRoot(path.join("relative", "backend"), ALL);
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.reason, "not-absolute");
});

test("checkRoot: any path segment ending in .asar is refused (packaged __dirname)", () => {
  const inAsar = path.join(BASE, "resources", "app.asar", "backend");
  const probe = fakeFs([inAsar]);
  const r = rr.checkRoot(inAsar, probe);
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.reason, "inside-asar");
  const upper = path.join(BASE, "resources", "APP.ASAR");
  assert.strictEqual(rr.checkRoot(upper, fakeFs([upper])).reason, "inside-asar");
});

test("checkRoot: a UNC / device path is refused (no network share backend)", () => {
  for (const p of ["\\\\server\\share\\rc", "//server/share/rc", "\\\\?\\X\\rc"]) {
    const r = rr.checkRoot(p, () => "dir");
    assert.strictEqual(r.ok, false, p);
    assert.strictEqual(r.reason, "unc-path", p);
  }
});

test("checkRoot: a missing marker is refused and named", () => {
  const onlyOps = (p) => (p === path.join(ROOT_A, "ops") ? "dir" : null);
  assert.strictEqual(rr.checkRoot(ROOT_A, onlyOps).reason, "missing-marker:main.py");
  const onlyMain = (p) => (p === path.join(ROOT_A, "main.py") ? "file" : null);
  assert.strictEqual(rr.checkRoot(ROOT_A, onlyMain).reason, "missing-marker:ops");
  // the right name with the wrong kind is still a miss
  const swapped = (p) =>
    p === path.join(ROOT_A, "main.py") ? "dir" : p === path.join(ROOT_A, "ops") ? "dir" : null;
  assert.strictEqual(rr.checkRoot(ROOT_A, swapped).reason, "missing-marker:main.py");
});

test("checkRoot: a throwing probe is a miss, never a throw", () => {
  const boom = () => {
    throw new Error("EACCES");
  };
  assert.strictEqual(rr.checkRoot(ROOT_A, boom).ok, false);
});

test("checkRoot: garbage input is refused, never throws", () => {
  for (const v of [undefined, null, "", "   ", 42, {}, []]) {
    const r = rr.checkRoot(v, ALL);
    assert.strictEqual(r.ok, false, String(v));
    assert.strictEqual(r.root, null);
  }
});

// ---- resolveRcRoot ----------------------------------------------------------

test("resolveRcRoot: argv beats env beats the dev fallback", () => {
  const r = rr.resolveRcRoot({
    argv: ["exe", "--rc-root=" + ROOT_A],
    env: { RC_ROOT: ROOT_B },
    isPackaged: false,
    devDir: DEV_SRC,
    probe: ALL,
  });
  assert.strictEqual(r.root, path.resolve(ROOT_A));
  assert.strictEqual(r.source, "argv");
});

test("resolveRcRoot: env RC_ROOT is used when argv names none", () => {
  const r = rr.resolveRcRoot({
    argv: ["exe"],
    env: { RC_ROOT: "  " + ROOT_B + "  " },
    isPackaged: true,
    probe: ALL,
  });
  assert.strictEqual(r.root, path.resolve(ROOT_B));
  assert.strictEqual(r.source, "env");
});

test("resolveRcRoot: an invalid explicit candidate falls through and is reported", () => {
  const r = rr.resolveRcRoot({
    argv: ["exe", "--rc-root", path.join("not", "absolute")],
    env: { RC_ROOT: ROOT_B },
    isPackaged: true,
    probe: ALL,
  });
  assert.strictEqual(r.source, "env");
  assert.deepStrictEqual(r.rejected, [{ source: "argv", reason: "not-absolute" }]);
});

test("resolveRcRoot: rejection records never echo the candidate path", () => {
  const secret = path.join(BASE, "private-name-xyz");
  const r = rr.resolveRcRoot({ env: { RC_ROOT: secret }, isPackaged: true, probe: ALL });
  assert.strictEqual(r.root, null);
  assert.ok(!JSON.stringify(r.rejected).includes("private-name-xyz"));
});

test("resolveRcRoot: packaged with a valid bundled root uses it", () => {
  const r = rr.resolveRcRoot({
    argv: ["exe"],
    env: {},
    isPackaged: true,
    bundledRoot: ROOT_C,
    devDir: DEV_SRC,
    probe: ALL,
  });
  assert.strictEqual(r.root, path.resolve(ROOT_C));
  assert.strictEqual(r.source, "bundled");
});

test("resolveRcRoot: PACKAGED WITH NO ROOT IS NULL, never __dirname/../..", () => {
  // devDir is what main.js's __dirname is; a packaged build must not use it
  // even when that location happens to look like a backend root.
  const r = rr.resolveRcRoot({
    argv: ["exe"],
    env: {},
    isPackaged: true,
    devDir: DEV_SRC,
    probe: ALL,
  });
  assert.strictEqual(r.root, null);
  assert.strictEqual(r.source, null);
});

test("resolveRcRoot: isPackaged unknown (not exactly false) gets no dev fallback", () => {
  for (const isPackaged of [undefined, null, "false", 0]) {
    const r = rr.resolveRcRoot({ devDir: DEV_SRC, isPackaged, probe: ALL });
    assert.strictEqual(r.root, null, String(isPackaged));
  }
});

test("resolveRcRoot: dev (unpackaged) falls back to devDir/../..", () => {
  const r = rr.resolveRcRoot({ argv: ["exe", "."], env: {}, isPackaged: false, devDir: DEV_SRC, probe: ALL });
  assert.strictEqual(r.root, path.resolve(DEV_ROOT));
  assert.strictEqual(r.source, "dev");
});

test("resolveRcRoot: a devDir inside an asar is refused even if isPackaged lies", () => {
  // resources/app.asar/src -> ../.. = resources, which is NOT itself inside
  // the asar; the devDir check must catch it.
  const asarSrc = path.join(BASE, "resources", "app.asar", "src");
  const resources = path.join(BASE, "resources");
  const r = rr.resolveRcRoot({ isPackaged: false, devDir: asarSrc, probe: fakeFs([resources]) });
  assert.strictEqual(r.root, null);
  assert.deepStrictEqual(r.rejected, [{ source: "dev", reason: "inside-asar" }]);
});

test("resolveRcRoot: bundled root is ignored when not packaged", () => {
  const r = rr.resolveRcRoot({ isPackaged: false, bundledRoot: ROOT_C, probe: ALL });
  assert.strictEqual(r.root, null);
});

test("resolveRcRoot: no options at all is null, never throws", () => {
  for (const v of [undefined, null, 42, "x"]) {
    const r = rr.resolveRcRoot(v);
    assert.strictEqual(r.root, null);
    assert.ok(Array.isArray(r.rejected));
  }
});

// ---- path builders ----------------------------------------------------------

test("runtimeDir / runtimeFile: under <root>/ops/runtime; null root -> null", () => {
  assert.strictEqual(rr.runtimeDir(ROOT_A), path.join(ROOT_A, "ops", "runtime"));
  assert.strictEqual(rr.runtimeDir(null), null);
  assert.strictEqual(rr.runtimeDir(""), null);
  assert.strictEqual(rr.runtimeDir(path.join("rel", "x")), null);
  assert.strictEqual(
    rr.runtimeFile(ROOT_A, "launcher_status.json"),
    path.join(ROOT_A, "ops", "runtime", "launcher_status.json")
  );
  assert.strictEqual(rr.runtimeFile(null, "x.txt"), null);
});

test("runtimeFile: refuses anything that is not a plain file name", () => {
  for (const bad of ["", " ", "..", ".", "a/b.txt", "a\\b.txt", "../x.txt", null, 5]) {
    assert.strictEqual(rr.runtimeFile(ROOT_A, bad), null, String(bad));
  }
});

test("signalPaths: the three hotkey signal files under <root>/ops/runtime (M3)", () => {
  const s = rr.signalPaths(ROOT_A);
  const rt = path.join(ROOT_A, "ops", "runtime");
  assert.deepStrictEqual(Object.assign({}, s), {
    activeToggle: path.join(rt, "overlay_active_toggle.txt"),
    panelCycle: path.join(rt, "overlay_panel_cycle.txt"),
    visibleToggle: path.join(rt, "overlay_visible_toggle.txt"),
  });
  assert.ok(Object.isFrozen(s));
  assert.strictEqual(rr.signalPaths(null), null);
});

test("localHostsPath / tlsCertPath: the per-host config + dashboard cert", () => {
  assert.strictEqual(rr.localHostsPath(ROOT_A), path.join(ROOT_A, "ops", "local_hosts.json"));
  assert.strictEqual(rr.tlsCertPath(ROOT_A), path.join(ROOT_A, "ops", "tls", "rc.pem"));
  assert.strictEqual(rr.localHostsPath(null), null);
  assert.strictEqual(rr.tlsCertPath(undefined), null);
});

// ---- readLocalHosts ---------------------------------------------------------

test("readLocalHosts: the parsed object; {} when absent / malformed / non-object", () => {
  const want = path.join(ROOT_A, "ops", "local_hosts.json");
  const reader = (body) => (p) => {
    if (p !== want) {
      throw new Error("ENOENT");
    }
    return body;
  };
  assert.deepStrictEqual(rr.readLocalHosts(ROOT_A, reader('{"tailnet_name": "rc-host"}')), {
    tailnet_name: "rc-host",
  });
  assert.deepStrictEqual(rr.readLocalHosts(ROOT_A, reader("{ nope")), {});
  assert.deepStrictEqual(rr.readLocalHosts(ROOT_A, reader("[1,2]")), {});
  assert.deepStrictEqual(rr.readLocalHosts(ROOT_A, reader("null")), {});
  assert.deepStrictEqual(rr.readLocalHosts(ROOT_B, reader("{}")), {}); // ENOENT
  assert.deepStrictEqual(rr.readLocalHosts(null, reader("{}")), {});
});

test("readLocalHosts: an oversized file is refused", () => {
  const big = '{"x":"' + "a".repeat(rr.MAX_LOCAL_HOSTS_BYTES + 1) + '"}';
  assert.deepStrictEqual(rr.readLocalHosts(ROOT_A, () => big), {});
});

// ---- defaultProbe (the one real-fs helper) -----------------------------------

test("defaultProbe: reports file / dir / null against the real filesystem", () => {
  assert.strictEqual(rr.defaultProbe(__filename), "file");
  assert.strictEqual(rr.defaultProbe(__dirname), "dir");
  assert.strictEqual(rr.defaultProbe(path.join(__dirname, "no-such-file-pkg3.txt")), null);
  assert.strictEqual(rr.defaultProbe(null), null);
});

test("defaultProbe: THIS checkout resolves as a dev backend root", () => {
  // rc-shell/test -> devDir rc-shell/src -> ../.. = the repo root, which
  // carries main.py + ops/ (both tracked).
  const r = rr.resolveRcRoot({ isPackaged: false, devDir: path.join(__dirname, "..", "src") });
  assert.strictEqual(r.root, path.resolve(__dirname, "..", ".."));
  assert.strictEqual(r.source, "dev");
});

// ---- source contracts --------------------------------------------------------

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "rc_root.js"), "utf8");

test("contract: rc_root.js never derives a path from its own __dirname", () => {
  // Strip comments, then assert no live __dirname use: the module's whole
  // point is that the CALLER hands in devDir (dev only).
  const code = SRC.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
  assert.ok(!/__dirname/.test(code), "rc_root.js must not use __dirname");
  assert.ok(!/require\(["']electron["']\)/.test(code), "rc_root.js must stay electron-free");
});

test("contract: the signal file names match the writer, tools/hotkey_listener.py", () => {
  const listener = fs.readFileSync(
    path.join(__dirname, "..", "..", "tools", "hotkey_listener.py"),
    "utf8"
  );
  for (const name of Object.values(rr.SIGNAL_FILES)) {
    const re = new RegExp('"ops"\\s*/\\s*"runtime"\\s*/\\s*"' + name.replace(/\./g, "\\.") + '"');
    assert.match(listener, re, name + " is written by the listener under ops/runtime");
  }
});

test("contract: SIGNAL_FILES and ROOT_MARKERS are frozen", () => {
  assert.ok(Object.isFrozen(rr.SIGNAL_FILES));
  assert.ok(Object.isFrozen(rr.ROOT_MARKERS));
  assert.strictEqual(rr.RC_ROOT_ENV, "RC_ROOT");
  assert.strictEqual(rr.RC_ROOT_ARG, "--rc-root");
});
