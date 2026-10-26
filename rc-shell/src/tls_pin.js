// rc-shell/src/tls_pin.js
//
// Leaf-certificate fingerprint pinning for the RC origin. NO electron import -
// the testable core behind PACKAGING_PLAN SHOULD S1 (docs/PACKAGING_PLAN.md,
// slice PKG-3; wired into main.js by PKG-6).
//
// The gap it closes: main.js's certificate-error handler trusts ANY
// certificate presented for the origin host, and the /api/state poll runs
// with rejectUnauthorized: false for any origin. Anything answering on that
// host:port with any self-signed cert was trusted. The install's own leaf is
// known (the dashboard serves <root>/ops/tls/rc.pem, dashboard/server.py
// cert_path; rc_root.tlsCertPath builds that path), so trust exactly that
// leaf's SHA-256 fingerprint and nothing else.
//
// Wiring recipe for PKG-6 (both paths share pinDecision):
//   pins = [pinFromFile(rcRoot.tlsCertPath(root))]   (null entries are dropped)
//   certificate-error (url, certificate):
//     d = pinDecision({url, origin, cert: certificate, pins})
//     d.trust ? (event.preventDefault(), callback(true)) : callback(false)
//   https poll: keep rejectUnauthorized: false (the mkcert leaf does not chain
//   to Node's CA store) but, on the response, run
//     pinDecision({url, origin, cert: res.socket.getPeerCertificate(), pins})
//   and drop the response (req.destroy(), count a failure) unless d.trust.
//
// Fail closed everywhere: no usable pin, an unreadable certificate, an http
// origin or a different origin is never "trusted" here - the caller falls
// back to Chromium's / Node's normal validation.
//
// Fingerprint shapes accepted (all normalise to 64 lower-case hex chars):
//   - Node peer cert / X509Certificate fingerprint256: "AB:CD:..." (32 pairs)
//   - Electron Certificate.fingerprint: "sha256/<base64 of 32 bytes>"
//   - bare hex
// When the certificate object carries its bytes (Node `raw` DER, Electron
// `data` PEM) the fingerprint is computed from those bytes and the text field
// is ignored.

"use strict";

const crypto = require("crypto");
const fs = require("fs");
const nav = require("./nav_guard");

// rc.pem is one leaf (plus at most a short chain); anything larger is refused.
const MAX_PEM_BYTES = 64 * 1024;

const CERT_BLOCK_RE = /-----BEGIN CERTIFICATE-----([A-Za-z0-9+/=\s]+?)-----END CERTIFICATE-----/;

function sha256Hex(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

// One fingerprint string -> 64 lower-case hex chars, or null.
function normalizeFingerprint(v) {
  if (typeof v !== "string") {
    return null;
  }
  const s = v.trim();
  if (!s) {
    return null;
  }
  const b64 = /^sha256\/([A-Za-z0-9+/]{43}=)$/.exec(s);
  if (b64) {
    const buf = Buffer.from(b64[1], "base64");
    return buf.length === 32 ? buf.toString("hex") : null;
  }
  if (/^[0-9a-fA-F]{64}$/.test(s)) {
    return s.toLowerCase();
  }
  if (/^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){31}$/.test(s)) {
    return s.replace(/:/g, "").toLowerCase();
  }
  return null;
}

// The SHA-256 of the FIRST certificate in a PEM text (the leaf), or null.
// The block must parse as an X.509 certificate.
function fingerprintFromPem(pem) {
  if (typeof pem !== "string" || !pem || pem.length > MAX_PEM_BYTES) {
    return null;
  }
  const m = CERT_BLOCK_RE.exec(pem);
  if (!m) {
    return null;
  }
  const block = "-----BEGIN CERTIFICATE-----" + m[1] + "-----END CERTIFICATE-----";
  try {
    if (typeof crypto.X509Certificate === "function") {
      const x = new crypto.X509Certificate(block);
      return sha256Hex(x.raw);
    }
    const der = Buffer.from(m[1].replace(/\s+/g, ""), "base64");
    return der.length > 0 ? sha256Hex(der) : null;
  } catch (_e) {
    return null;
  }
}

// Read a PEM file through an injectable reader ((path) -> string) and pin its
// leaf; null on any failure.
function pinFromFile(certPath, readFile) {
  if (typeof certPath !== "string" || !certPath) {
    return null;
  }
  const read = typeof readFile === "function" ? readFile : (p) => fs.readFileSync(p, "utf8");
  try {
    return fingerprintFromPem(read(certPath));
  } catch (_e) {
    return null;
  }
}

// The fingerprint of whatever certificate shape the caller holds, or null:
//   string                  - a fingerprint (any accepted shape)
//   Buffer / Uint8Array     - DER bytes
//   {raw: Buffer}           - Node getPeerCertificate() (bytes win)
//   {data: "<PEM>"}         - Electron Certificate (bytes win)
//   {fingerprint256}        - Node, no bytes
//   {fingerprint}           - Electron, no bytes ("sha256/<base64>")
function certFingerprint(cert) {
  if (typeof cert === "string") {
    return normalizeFingerprint(cert);
  }
  if (cert instanceof Uint8Array) {
    return cert.length > 0 ? sha256Hex(cert) : null;
  }
  if (!cert || typeof cert !== "object") {
    return null;
  }
  if (cert.raw instanceof Uint8Array && cert.raw.length > 0) {
    return sha256Hex(cert.raw);
  }
  if (typeof cert.data === "string" && cert.data.includes("-----BEGIN CERTIFICATE-----")) {
    // The bytes are present: they are the truth. An unparsable PEM is a
    // miss, never a fall-back to the (unverifiable) text field.
    return fingerprintFromPem(cert.data);
  }
  if (typeof cert.fingerprint256 === "string") {
    return normalizeFingerprint(cert.fingerprint256);
  }
  if (typeof cert.fingerprint === "string") {
    return normalizeFingerprint(cert.fingerprint);
  }
  return null;
}

// A pin or a list of pins -> unique normalised fingerprints (invalid dropped).
// A list allows a planned leaf rotation (old + new pinned together).
function normalizePins(pins) {
  const list = Array.isArray(pins) ? pins : [pins];
  const out = [];
  for (const p of list) {
    const fp = normalizeFingerprint(p);
    if (fp && !out.includes(fp)) {
      out.push(fp);
    }
  }
  return out;
}

// The trust decision for one presented certificate:
//   {url, origin, cert, pins} -> {trust, reason}
// reason: "pin-match" (the only trust: true), "origin-not-https",
// "not-rc-origin", "no-pin", "no-fingerprint", "pin-mismatch".
function pinDecision(opts) {
  const o = opts && typeof opts === "object" && !Array.isArray(opts) ? opts : {};
  let originUrl = null;
  try {
    originUrl = typeof o.origin === "string" ? new URL(o.origin) : null;
  } catch (_e) {
    originUrl = null;
  }
  if (!originUrl || originUrl.protocol !== "https:") {
    return { trust: false, reason: "origin-not-https" };
  }
  if (!nav.isSameOrigin(o.url, o.origin)) {
    return { trust: false, reason: "not-rc-origin" };
  }
  const list = normalizePins(o.pins);
  if (list.length === 0) {
    return { trust: false, reason: "no-pin" };
  }
  const fp = certFingerprint(o.cert);
  if (!fp) {
    return { trust: false, reason: "no-fingerprint" };
  }
  return list.includes(fp)
    ? { trust: true, reason: "pin-match" }
    : { trust: false, reason: "pin-mismatch" };
}

module.exports = {
  MAX_PEM_BYTES,
  normalizeFingerprint,
  fingerprintFromPem,
  pinFromFile,
  certFingerprint,
  normalizePins,
  pinDecision,
};
