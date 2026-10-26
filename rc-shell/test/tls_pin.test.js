// rc-shell/test/tls_pin.test.js
//
// PKG-3 (docs/PACKAGING_PLAN.md, SHOULD S1): the leaf-fingerprint pin that
// replaces "trust ANY certificate for the origin host" in the
// certificate-error handler and the `rejectUnauthorized: false` /api/state
// poll. The certificate fixture is one of Node's own bundled root CAs
// (tls.rootCertificates), so no PEM file is committed and no network is used;
// the expected fingerprint is computed independently from the DER bytes.
// NO electron. Run with: npm test

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const tls = require("tls");

const pin = require("../src/tls_pin");

const PEM = tls.rootCertificates[0];
const PEM_2 = tls.rootCertificates[1];

function derOf(pem) {
  const body = pem
    .replace(/-----BEGIN CERTIFICATE-----/, "")
    .replace(/-----END CERTIFICATE-----[\s\S]*$/, "")
    .replace(/\s+/g, "");
  return Buffer.from(body, "base64");
}

const DER = derOf(PEM);
const HEX = crypto.createHash("sha256").update(DER).digest("hex");
const HEX_2 = crypto.createHash("sha256").update(derOf(PEM_2)).digest("hex");
const COLON = HEX.toUpperCase().match(/../g).join(":");
const B64 = "sha256/" + Buffer.from(HEX, "hex").toString("base64");

const ORIGIN = "https://127.0.0.1:8888";
const URL_OK = "https://127.0.0.1:8888/api/state";

// ---- normalizeFingerprint ----------------------------------------------------

test("normalizeFingerprint: colon-hex, bare hex and sha256/base64 agree", () => {
  assert.strictEqual(pin.normalizeFingerprint(COLON), HEX);
  assert.strictEqual(pin.normalizeFingerprint(COLON.toLowerCase()), HEX);
  assert.strictEqual(pin.normalizeFingerprint(HEX.toUpperCase()), HEX);
  assert.strictEqual(pin.normalizeFingerprint("  " + HEX + "  "), HEX);
  assert.strictEqual(pin.normalizeFingerprint(B64), HEX);
});

test("normalizeFingerprint: SHA-1, truncated, ragged or garbage values are null", () => {
  const sha1 = crypto.createHash("sha1").update(DER).digest("hex");
  const bad = [
    sha1,
    sha1.toUpperCase().match(/../g).join(":"),
    HEX.slice(0, 62),
    HEX + "00",
    COLON.replace(":", ""), // one separator missing = ragged
    COLON.replace(":", "::"),
    "sha1/" + Buffer.from(sha1, "hex").toString("base64"),
    "sha256/" + Buffer.from(sha1, "hex").toString("base64"),
    "sha256/not base64!",
    "zz".repeat(32),
    "",
    "   ",
    undefined,
    null,
    42,
    {},
    [],
  ];
  for (const v of bad) {
    assert.strictEqual(pin.normalizeFingerprint(v), null, String(v));
  }
});

// ---- fingerprintFromPem -----------------------------------------------------

test("fingerprintFromPem: the leaf DER sha256, independent of the parser", () => {
  assert.strictEqual(pin.fingerprintFromPem(PEM), HEX);
});

test("fingerprintFromPem: the FIRST certificate of a chain is the pin (the leaf)", () => {
  assert.strictEqual(pin.fingerprintFromPem(PEM + "\n" + PEM_2), HEX);
  assert.strictEqual(pin.fingerprintFromPem(PEM_2 + "\n" + PEM), HEX_2);
});

test("fingerprintFromPem: a PEM with a private-key block first still pins the cert", () => {
  // A fake, empty-bodied key block (no key material). rc-credential-scan: allow-fixture
  const keyBlock = "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"; // rc-credential-scan: allow-fixture
  assert.strictEqual(pin.fingerprintFromPem(keyBlock + PEM), HEX);
});

test("fingerprintFromPem: garbage / no cert / oversized is null, never throws", () => {
  const big = PEM + "\n" + "x".repeat(pin.MAX_PEM_BYTES);
  for (const v of [undefined, null, 42, "", "not a pem", "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----", big]) {
    assert.strictEqual(pin.fingerprintFromPem(v), null);
  }
});

test("pinFromFile: reads through the injected reader; any failure is null", () => {
  assert.strictEqual(pin.pinFromFile("rc.pem", () => PEM), HEX);
  assert.strictEqual(
    pin.pinFromFile("rc.pem", () => {
      throw new Error("ENOENT");
    }),
    null
  );
  assert.strictEqual(pin.pinFromFile(null, () => PEM), null);
  assert.strictEqual(pin.pinFromFile("", () => PEM), null);
});

// ---- certFingerprint (every shape a caller can hold) -------------------------

test("certFingerprint: Node peer cert (raw DER) wins over its fingerprint256 text", () => {
  assert.strictEqual(pin.certFingerprint({ raw: DER, fingerprint256: COLON }), HEX);
  // raw is ground truth: a lying fingerprint256 is ignored when raw is present
  assert.strictEqual(pin.certFingerprint({ raw: DER, fingerprint256: "00:".repeat(31) + "00" }), HEX);
  assert.strictEqual(pin.certFingerprint({ fingerprint256: COLON }), HEX);
});

test("certFingerprint: Electron Certificate (PEM data) wins over its fingerprint text", () => {
  assert.strictEqual(pin.certFingerprint({ data: PEM, fingerprint: "sha256/garbage" }), HEX);
  assert.strictEqual(pin.certFingerprint({ fingerprint: B64 }), HEX);
});

test("certFingerprint: unparsable PEM bytes are a miss, never a fall-back to the text field", () => {
  const broken = "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----";
  assert.strictEqual(pin.certFingerprint({ data: broken, fingerprint: B64 }), null);
  assert.strictEqual(pin.certFingerprint({ data: broken, fingerprint256: COLON }), null);
});

test("certFingerprint: a bare string or a DER buffer", () => {
  assert.strictEqual(pin.certFingerprint(COLON), HEX);
  assert.strictEqual(pin.certFingerprint(DER), HEX);
  assert.strictEqual(pin.certFingerprint(new Uint8Array(DER)), HEX);
});

test("certFingerprint: an empty / unknown shape is null", () => {
  for (const v of [undefined, null, 5, {}, { raw: Buffer.alloc(0) }, { data: "x" }, Buffer.alloc(0)]) {
    assert.strictEqual(pin.certFingerprint(v), null);
  }
});

// ---- normalizePins -----------------------------------------------------------

test("normalizePins: string or list, normalised, de-duplicated, invalid dropped", () => {
  assert.deepStrictEqual(pin.normalizePins(COLON), [HEX]);
  assert.deepStrictEqual(pin.normalizePins([COLON, HEX, B64, "junk", null, HEX_2]), [HEX, HEX_2]);
  assert.deepStrictEqual(pin.normalizePins(undefined), []);
  assert.deepStrictEqual(pin.normalizePins({}), []);
});

// ---- pinDecision -------------------------------------------------------------

test("pinDecision: the RC origin presenting the pinned leaf is trusted", () => {
  assert.deepStrictEqual(pin.pinDecision({ url: URL_OK, origin: ORIGIN, cert: { data: PEM }, pins: HEX }), {
    trust: true,
    reason: "pin-match",
  });
  // rotation: any listed pin matches
  assert.strictEqual(
    pin.pinDecision({ url: URL_OK, origin: ORIGIN, cert: { raw: DER }, pins: [HEX_2, COLON] }).trust,
    true
  );
});

test("pinDecision: a different leaf on the RC origin is NOT trusted (S1)", () => {
  const d = pin.pinDecision({ url: URL_OK, origin: ORIGIN, cert: { data: PEM_2 }, pins: HEX });
  assert.deepStrictEqual(d, { trust: false, reason: "pin-mismatch" });
});

test("pinDecision: no usable pin fails closed (never 'trust any cert')", () => {
  for (const pins of [undefined, null, "", [], ["junk"]]) {
    const d = pin.pinDecision({ url: URL_OK, origin: ORIGIN, cert: { data: PEM }, pins });
    assert.deepStrictEqual(d, { trust: false, reason: "no-pin" });
  }
});

test("pinDecision: a cert with no readable fingerprint is not trusted", () => {
  const d = pin.pinDecision({ url: URL_OK, origin: ORIGIN, cert: {}, pins: HEX });
  assert.deepStrictEqual(d, { trust: false, reason: "no-fingerprint" });
});

test("pinDecision: any other origin falls through to normal validation", () => {
  const others = [
    "https://127.0.0.1:8889/latest-frame", // other port
    "https://localhost:8888/", // other host spelling
    "https://example.com/",
    "http://127.0.0.1:8888/", // other scheme
    "not a url",
    "",
  ];
  for (const url of others) {
    const d = pin.pinDecision({ url, origin: ORIGIN, cert: { data: PEM }, pins: HEX });
    assert.deepStrictEqual(d, { trust: false, reason: "not-rc-origin" }, url);
  }
});

test("pinDecision: an http (or malformed) RC origin never trusts a cert", () => {
  for (const origin of ["http://127.0.0.1:8888", "nope", "", undefined]) {
    const d = pin.pinDecision({ url: URL_OK, origin, cert: { data: PEM }, pins: HEX });
    assert.deepStrictEqual(d, { trust: false, reason: "origin-not-https" }, String(origin));
  }
});

test("pinDecision: garbage input never throws", () => {
  for (const v of [undefined, null, 42, "x", []]) {
    assert.strictEqual(pin.pinDecision(v).trust, false);
  }
});

// ---- source contract ----------------------------------------------------------

test("contract: tls_pin.js is electron-free and uses only node built-ins + nav_guard", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "src", "tls_pin.js"), "utf8");
  const reqs = [...src.matchAll(/require\(["']([^"']+)["']\)/g)].map((m) => m[1]).sort();
  assert.deepStrictEqual(reqs, ["./nav_guard", "crypto", "fs"]);
});
