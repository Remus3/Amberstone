// rc-shell/test/config.test.js
//
// Pure-logic tests for config.js. NO electron. Run with: node --test test/

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const {
  DEFAULT_ORIGIN,
  DEFAULT_PRESET,
  SIZE_PRESETS,
  defaultConfig,
  applyPreset,
  resolveConfig,
  clampPosition,
  originHost,
  isLoopbackHost,
  allowedOriginHosts,
  validateOrigin,
} = require("../src/config");

// ---- defaultConfig ----------------------------------------------------------

test("defaultConfig returns the standard preset dims + RC default origin", () => {
  const c = defaultConfig();
  assert.strictEqual(c.origin, DEFAULT_ORIGIN);
  assert.strictEqual(c.sizePreset, DEFAULT_PRESET);
  assert.strictEqual(c.width, SIZE_PRESETS[DEFAULT_PRESET].width);
  assert.strictEqual(c.height, SIZE_PRESETS[DEFAULT_PRESET].height);
  assert.strictEqual(c.alwaysOnTop, true);
  assert.strictEqual(c.x, null);
  assert.strictEqual(c.y, null);
});

test("DEFAULT_ORIGIN is the Legion dashboard origin over loopback", () => {
  assert.strictEqual(DEFAULT_ORIGIN, "https://127.0.0.1:8888");
});

// ---- resolveConfig precedence ----------------------------------------------

test("resolveConfig: defaults when saved + env are empty", () => {
  const c = resolveConfig({}, {});
  assert.strictEqual(c.origin, DEFAULT_ORIGIN);
  assert.strictEqual(c.width, SIZE_PRESETS.standard.width);
  assert.strictEqual(c.height, SIZE_PRESETS.standard.height);
});

test("resolveConfig: saved origin beats default", () => {
  const c = resolveConfig({ origin: "https://127.0.0.1:9000" }, {});
  assert.strictEqual(c.origin, "https://127.0.0.1:9000");
  assert.strictEqual(c.originSource, "saved");
});

test("resolveConfig: env RC_ORIGIN beats saved AND default (highest precedence)", () => {
  const c = resolveConfig(
    { origin: "https://127.0.0.1:9000" },
    { RC_ORIGIN: "https://127.0.0.1:8888" }
  );
  assert.strictEqual(c.origin, "https://127.0.0.1:8888");
  assert.strictEqual(c.originSource, "env");
});

test("resolveConfig: env RC_ORIGIN beats default when no saved origin", () => {
  const c = resolveConfig({}, { RC_ORIGIN: "https://127.0.0.1:8888" });
  assert.strictEqual(c.origin, "https://127.0.0.1:8888");
});

test("resolveConfig: blank/whitespace env RC_ORIGIN is ignored (does not wipe)", () => {
  const c1 = resolveConfig({ origin: "https://127.0.0.1:9000" }, { RC_ORIGIN: "" });
  assert.strictEqual(c1.origin, "https://127.0.0.1:9000");
  const c2 = resolveConfig({ origin: "https://127.0.0.1:9000" }, { RC_ORIGIN: "   " });
  assert.strictEqual(c2.origin, "https://127.0.0.1:9000");
  assert.deepStrictEqual(c2.originRejected, []);
});

test("resolveConfig: env RC_ORIGIN is trimmed", () => {
  const c = resolveConfig({}, { RC_ORIGIN: "  https://localhost:8888  " });
  assert.strictEqual(c.origin, "https://localhost:8888");
});

test("resolveConfig: saved width/height win over preset dims", () => {
  const c = resolveConfig({ width: 444, height: 999 }, {});
  assert.strictEqual(c.width, 444);
  assert.strictEqual(c.height, 999);
});

test("resolveConfig: saved sizePreset selects preset dims when width/height absent", () => {
  const c = resolveConfig({ sizePreset: "tall" }, {});
  assert.strictEqual(c.sizePreset, "tall");
  assert.strictEqual(c.width, SIZE_PRESETS.tall.width);
  assert.strictEqual(c.height, SIZE_PRESETS.tall.height);
});

test("resolveConfig: unknown saved sizePreset falls back to default preset", () => {
  const c = resolveConfig({ sizePreset: "ginormous" }, {});
  assert.strictEqual(c.sizePreset, DEFAULT_PRESET);
  assert.strictEqual(c.width, SIZE_PRESETS[DEFAULT_PRESET].width);
});

test("resolveConfig: garbage saved (null) does not throw, returns defaults", () => {
  const c = resolveConfig(null, null);
  assert.strictEqual(c.origin, DEFAULT_ORIGIN);
  assert.strictEqual(c.width, SIZE_PRESETS.standard.width);
});

test("resolveConfig: saved x/y kept when numeric; null otherwise", () => {
  const c1 = resolveConfig({ x: 100, y: 200 }, {});
  assert.strictEqual(c1.x, 100);
  assert.strictEqual(c1.y, 200);
  const c2 = resolveConfig({ x: "nope", y: undefined }, {});
  assert.strictEqual(c2.x, null);
  assert.strictEqual(c2.y, null);
});

test("resolveConfig: alwaysOnTop saved boolean wins, else default true", () => {
  assert.strictEqual(resolveConfig({ alwaysOnTop: false }, {}).alwaysOnTop, false);
  assert.strictEqual(resolveConfig({}, {}).alwaysOnTop, true);
});

test("resolveConfig: non-positive saved width/height fall back to preset", () => {
  const c = resolveConfig({ width: 0, height: -5 }, {});
  assert.strictEqual(c.width, SIZE_PRESETS.standard.width);
  assert.strictEqual(c.height, SIZE_PRESETS.standard.height);
});

// ---- applyPreset ------------------------------------------------------------

test("applyPreset: sets width/height/sizePreset from SIZE_PRESETS", () => {
  const c = applyPreset(defaultConfig(), "compact");
  assert.strictEqual(c.sizePreset, "compact");
  assert.strictEqual(c.width, SIZE_PRESETS.compact.width);
  assert.strictEqual(c.height, SIZE_PRESETS.compact.height);
});

test("applyPreset: all three presets resolve to their declared dims", () => {
  for (const name of ["compact", "standard", "tall"]) {
    const c = applyPreset(defaultConfig(), name);
    assert.strictEqual(c.width, SIZE_PRESETS[name].width);
    assert.strictEqual(c.height, SIZE_PRESETS[name].height);
  }
});

test("applyPreset: unknown preset returns config unchanged (no throw)", () => {
  const base = defaultConfig();
  const c = applyPreset(base, "nope");
  assert.strictEqual(c.width, base.width);
  assert.strictEqual(c.height, base.height);
  assert.strictEqual(c.sizePreset, base.sizePreset);
});

test("applyPreset: preserves other config fields (origin, alwaysOnTop, x/y)", () => {
  const base = Object.assign(defaultConfig(), {
    origin: "https://x:1",
    alwaysOnTop: false,
    x: 12,
    y: 34,
  });
  const c = applyPreset(base, "tall");
  assert.strictEqual(c.origin, "https://x:1");
  assert.strictEqual(c.alwaysOnTop, false);
  assert.strictEqual(c.x, 12);
  assert.strictEqual(c.y, 34);
});

// ---- clampPosition ----------------------------------------------------------

const DISPLAY = { x: 0, y: 0, width: 1920, height: 1080 };

test("clampPosition: in-bounds position is unchanged", () => {
  const r = clampPosition({ x: 100, y: 100, width: 520, height: 900 }, DISPLAY);
  assert.strictEqual(r.x, 100);
  assert.strictEqual(r.y, 100);
});

test("clampPosition: off the right/bottom edge is pulled back on-screen", () => {
  // window 520x900 at x=1800 would hang off the right; clamp to 1920-520=1400.
  const r = clampPosition({ x: 1800, y: 900, width: 520, height: 900 }, DISPLAY);
  assert.strictEqual(r.x, 1920 - 520);
  assert.strictEqual(r.y, 1080 - 900);
});

test("clampPosition: negative coords are pulled to the display origin", () => {
  const r = clampPosition({ x: -300, y: -50, width: 520, height: 900 }, DISPLAY);
  assert.strictEqual(r.x, 0);
  assert.strictEqual(r.y, 0);
});

test("clampPosition: far off-screen saved coords (stale 2nd monitor) clamp on", () => {
  // simulate a saved coord from a now-disconnected monitor at x=5000
  const r = clampPosition({ x: 5000, y: 3000, width: 380, height: 720 }, DISPLAY);
  assert.ok(r.x >= 0 && r.x <= 1920 - 380, "x within display");
  assert.ok(r.y >= 0 && r.y <= 1080 - 720, "y within display");
});

test("clampPosition: honors a non-zero display origin (multi-monitor offset)", () => {
  const right = { x: 1920, y: 0, width: 1920, height: 1080 };
  const r = clampPosition({ x: 1950, y: 100, width: 520, height: 900 }, right);
  assert.strictEqual(r.x, 1950); // in-bounds on the right display
  assert.strictEqual(r.y, 100);
  // and an x below that display's origin is pinned to it
  const r2 = clampPosition({ x: 0, y: 100, width: 520, height: 900 }, right);
  assert.strictEqual(r2.x, 1920);
});

test("clampPosition: window larger than display pins to origin (no NaN)", () => {
  const r = clampPosition({ x: 50, y: 50, width: 3000, height: 2000 }, DISPLAY);
  assert.strictEqual(r.x, 0);
  assert.strictEqual(r.y, 0);
});

test("clampPosition: null/missing x or y returns {x:null,y:null} (center me)", () => {
  assert.deepStrictEqual(clampPosition({ x: null, y: null }, DISPLAY), {
    x: null,
    y: null,
  });
  assert.deepStrictEqual(clampPosition({ width: 520, height: 900 }, DISPLAY), {
    x: null,
    y: null,
  });
});

test("clampPosition: garbage display bounds fall back to 1920x1080 (no throw)", () => {
  const r = clampPosition({ x: 100, y: 100, width: 520, height: 900 }, null);
  assert.strictEqual(r.x, 100);
  assert.strictEqual(r.y, 100);
});

// ---- originHost -------------------------------------------------------------

test("originHost: extracts host:port from an origin URL", () => {
  assert.strictEqual(originHost("https://rc-host:8888"), "rc-host:8888");
  assert.strictEqual(originHost("https://127.0.0.1:8888"), "127.0.0.1:8888");
});

test("originHost: malformed origin returns empty string (no throw)", () => {
  assert.strictEqual(originHost("not a url"), "");
  assert.strictEqual(originHost(""), "");
});

// ---- PKG-3 / S2: origin validation ------------------------------------------
//
// docs/PACKAGING_PLAN.md S2: RC_ORIGIN or a saved origin used to accept ANY
// scheme and host, and the preload bridge plus the cert trust followed it.
// Now: http(s) on loopback, or https on a host named in the per-host
// ops/local_hosts.json (rc-host / example-tailnet / 100.64.0.x / 192.0.2.x
// placeholders below - never real values).

const LOCAL_HOSTS = {
  tailnet_name: "rc-host",
  tailnet_fqdn: "rc-host.example-tailnet.ts.net",
  tailnet_ipv4: "100.64.0.7",
  lan_ipv4: "192.0.2.10",
  cert_sans: ["rc-alias", "*.example-tailnet.ts.net", "a/b", "bad host", 7, "rc-host"],
};

test("isLoopbackHost: localhost, 127.0.0.0/8 and ::1 only", () => {
  for (const h of ["localhost", "LOCALHOST", "127.0.0.1", "127.1.2.3", "127.255.255.255", "[::1]", "::1"]) {
    assert.strictEqual(isLoopbackHost(h), true, h);
  }
  for (const h of ["0.0.0.0", "128.0.0.1", "127.0.0.256", "localhost.", "rc-host", "192.0.2.1", "[::]", "", null, 5]) {
    assert.strictEqual(isLoopbackHost(h), false, String(h));
  }
});

test("allowedOriginHosts: per-host names, tailnet IPv4 only inside 100.64.0.0/10", () => {
  assert.deepStrictEqual(allowedOriginHosts(LOCAL_HOSTS), [
    "rc-host",
    "rc-host.example-tailnet.ts.net",
    "100.64.0.7",
    "192.0.2.10",
    "rc-alias",
  ]);
  // mirrors core/local_hosts.py tailnet_ipv4: outside the CGNAT range is ignored
  assert.deepStrictEqual(allowedOriginHosts({ tailnet_ipv4: "100.128.0.1" }), []);
  assert.deepStrictEqual(allowedOriginHosts({ tailnet_ipv4: "100.127.255.254" }), ["100.127.255.254"]);
  // a leading-zero octet (octal under WHATWG URL) is not a valid address here
  assert.deepStrictEqual(allowedOriginHosts({ lan_ipv4: "010.0.0.1" }), []);
});

test("allowedOriginHosts: absent / malformed per-host config is loopback-only", () => {
  for (const v of [undefined, null, {}, [], "x", 42, { cert_sans: "rc-host" }]) {
    assert.deepStrictEqual(allowedOriginHosts(v), [], JSON.stringify(v));
  }
});

test("validateOrigin: http and https on loopback are accepted and normalised", () => {
  const cases = {
    "https://127.0.0.1:8888": "https://127.0.0.1:8888",
    "http://127.0.0.1:8888": "http://127.0.0.1:8888",
    "https://127.0.0.1:8888/": "https://127.0.0.1:8888",
    "  https://LOCALHOST:8888  ": "https://localhost:8888",
    "http://[::1]:8888": "http://[::1]:8888",
    "https://127.0.0.2:8888": "https://127.0.0.2:8888",
  };
  for (const [input, want] of Object.entries(cases)) {
    assert.deepStrictEqual(validateOrigin(input), { ok: true, origin: want, reason: "ok" }, input);
  }
});

test("validateOrigin: DEFAULT_ORIGIN is itself valid", () => {
  assert.strictEqual(validateOrigin(DEFAULT_ORIGIN).ok, true);
});

test("validateOrigin: only http(s) schemes", () => {
  for (const o of [
    "file:///x.html",
    "ftp://127.0.0.1:8888",
    "ws://127.0.0.1:8888",
    "javascript:alert(1)",
    "data:text/html,x",
    "chrome://settings",
    "devtools://devtools",
  ]) {
    assert.strictEqual(validateOrigin(o).reason, "bad-scheme", o);
  }
});

test("validateOrigin: credentials, paths, queries and fragments are refused", () => {
  assert.strictEqual(validateOrigin("https://u:p@127.0.0.1:8888").reason, "credentials"); // rc-credential-scan: allow-fixture
  assert.strictEqual(validateOrigin("https://u@127.0.0.1:8888").reason, "credentials");
  for (const o of ["https://127.0.0.1:8888/x", "https://127.0.0.1:8888/?a=1", "https://127.0.0.1:8888/#x"]) {
    assert.strictEqual(validateOrigin(o).reason, "not-an-origin", o);
  }
});

test("validateOrigin: a non-loopback host is refused without the per-host config", () => {
  for (const o of [
    "https://rc-host:8888",
    "https://example.com",
    "https://192.0.2.10:8888",
    "https://0.0.0.0:8888",
    "https://100.64.0.7:8888",
    "https://localhost.:8888",
  ]) {
    const v = validateOrigin(o);
    assert.deepStrictEqual(v, { ok: false, origin: null, reason: "host-not-allowed" }, o);
  }
});

test("validateOrigin: https on a host named in local_hosts.json is accepted", () => {
  const opts = { localHosts: LOCAL_HOSTS };
  for (const o of [
    "https://rc-host:8888",
    "https://RC-HOST:8888",
    "https://rc-host.example-tailnet.ts.net:8888",
    "https://100.64.0.7:8888",
    "https://192.0.2.10:8888",
    "https://rc-alias:8888",
  ]) {
    assert.strictEqual(validateOrigin(o, opts).ok, true, o);
  }
  // wildcard SANs never widen the allow-list
  assert.strictEqual(validateOrigin("https://x.example-tailnet.ts.net:8888", opts).reason, "host-not-allowed");
  assert.strictEqual(validateOrigin("https://example.com", opts).reason, "host-not-allowed");
});

test("validateOrigin: plain http to a non-loopback host is refused (TLS required off-box)", () => {
  const v = validateOrigin("http://rc-host:8888", { localHosts: LOCAL_HOSTS });
  assert.deepStrictEqual(v, { ok: false, origin: null, reason: "insecure-remote" });
});

test("validateOrigin: garbage never throws", () => {
  for (const v of [undefined, null, 42, {}, [], "", "   ", "not a url", "//127.0.0.1:8888"]) {
    const r = validateOrigin(v, { localHosts: "junk" });
    assert.strictEqual(r.ok, false, String(v));
    assert.strictEqual(r.origin, null);
  }
});

test("resolveConfig: an invalid env RC_ORIGIN is skipped and reported, saved wins", () => {
  const c = resolveConfig({ origin: "https://127.0.0.1:9000" }, { RC_ORIGIN: "https://example.com" });
  assert.strictEqual(c.origin, "https://127.0.0.1:9000");
  assert.strictEqual(c.originSource, "saved");
  assert.deepStrictEqual(c.originRejected, [{ source: "env", reason: "host-not-allowed" }]);
});

test("resolveConfig: an invalid saved origin falls back to the default", () => {
  const c = resolveConfig({ origin: "file:///x.html" }, {});
  assert.strictEqual(c.origin, DEFAULT_ORIGIN);
  assert.strictEqual(c.originSource, "default");
  assert.deepStrictEqual(c.originRejected, [{ source: "saved", reason: "bad-scheme" }]);
});

test("resolveConfig: rejection records never echo the refused value", () => {
  const c = resolveConfig({ origin: "https://secret-name-xyz:8888" }, { RC_ORIGIN: "https://other-xyz" });
  assert.ok(!JSON.stringify(c).includes("xyz"));
  assert.strictEqual(c.originRejected.length, 2);
});

test("resolveConfig: a tailnet RC_ORIGIN works when local_hosts names it", () => {
  const c = resolveConfig({}, { RC_ORIGIN: "https://rc-host:8888" }, { localHosts: LOCAL_HOSTS });
  assert.strictEqual(c.origin, "https://rc-host:8888");
  assert.strictEqual(c.originSource, "env");
});

test("resolveConfig: the host-served origin beats saved + default, env still wins", () => {
  // section 3.6: the launcher reports the origin it actually serves (plain
  // http on loopback on a fresh machine, M4) and the shell uses exactly that.
  const served = { servedOrigin: "http://127.0.0.1:8888" };
  const c1 = resolveConfig({ origin: "https://127.0.0.1:9000" }, {}, served);
  assert.strictEqual(c1.origin, "http://127.0.0.1:8888");
  assert.strictEqual(c1.originSource, "served");
  const c2 = resolveConfig({}, { RC_ORIGIN: "https://localhost:8888" }, served);
  assert.strictEqual(c2.origin, "https://localhost:8888");
  assert.strictEqual(c2.originSource, "env");
  // an invalid served origin is skipped like any other candidate
  const c3 = resolveConfig({}, {}, { servedOrigin: "https://example.com" });
  assert.strictEqual(c3.origin, DEFAULT_ORIGIN);
  assert.deepStrictEqual(c3.originRejected, [{ source: "served", reason: "host-not-allowed" }]);
});

test("resolveConfig: two-argument calls (today's main.js) still resolve", () => {
  const c = resolveConfig({}, {});
  assert.strictEqual(c.origin, DEFAULT_ORIGIN);
  assert.strictEqual(c.originSource, "default");
  assert.deepStrictEqual(c.originRejected, []);
});
