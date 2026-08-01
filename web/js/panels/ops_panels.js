// Ops panels - ADDENDUM A concepts 3 (Seam Map), 4 (Drift Strip), 5 (Gated Queue).
//
// Real panels fed by real routes: /api/ops/seam-map, /api/ops/drift-strip and
// /api/ops/gated-queue. All compute lives in core/ops_panels.py; this module
// only renders and never derives a number, so a disagreement between panel and
// engine is impossible by construction rather than by discipline.
//
// Render contract: renderOpsPanels() fetches all three concurrently and paints
// into #seam-map-panel / #drift-strip-panel / #gated-queue-panel. Idempotent -
// it fully replaces each body, so repeated calls converge rather than append
// (feedback_dashboard_render_idempotency).
//
// Failure posture: each panel degrades INDEPENDENTLY. A dead route paints that
// one card as unavailable and leaves the other two live, because these panels
// exist to report trouble and a blank grid would hide exactly what they are for.
// A failed fetch NEVER renders as an empty-but-healthy state - "no seams" and
// "could not read seams" are different claims and are rendered differently.

const ENDPOINTS = {
  seam:  "/api/ops/seam-map",
  drift: "/api/ops/drift-strip",
  gated: "/api/ops/gated-queue",
};

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function _body(id) {
  const host = document.getElementById(id);
  if (!host) return null;
  let body = host.querySelector(".ops-body");
  if (!body) {
    body = _el("div", "ops-body");
    host.appendChild(body);
  }
  body.replaceChildren();
  return body;
}

function _fail(id, reason) {
  const body = _body(id);
  if (!body) return;
  const msg = _el("p", "ops-fail");
  msg.textContent = "unavailable - " + (reason || "route did not answer");
  body.appendChild(msg);
}

async function _get(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// ---------------------------------------------------------------- seam map
export function renderSeamMap(data) {
  const body = _body("seam-map-panel");
  if (!body) return;
  if (!data || data.ok === false) {
    return _fail("seam-map-panel", data && data.reason);
  }

  const cap = _el("p", "ops-cap");
  cap.textContent = `${data.wired_count} wired, ${data.inert_count} inert of ${data.seams.length}`;
  body.appendChild(cap);

  const table = _el("table", "seams");
  const thead = _el("thead");
  const hrow = _el("tr");
  ["DS seam", "flag set", "transport carries", "route consumes"].forEach((h, i) => {
    const th = _el("th", i ? "gate" : null, h);
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  table.appendChild(thead);

  const tbody = _el("tbody");
  // Inert first: the panel's job is the problem, not the inventory.
  const rows = data.seams.slice().sort((a, b) =>
    (b.inert - a.inert) || a.seam.localeCompare(b.seam));
  for (const r of rows) {
    const tr = _el("tr", r.inert ? "inert" : null);
    tr.appendChild(_el("td", "seam", r.seam));
    for (const gate of ["flag", "transport", "route"]) {
      const v = r[gate];
      // The literal word is carried in text, never colour alone.
      const td = _el("td", "gate " + (v === "yes" ? "g-yes" : v === "no" ? "g-no" : "g-na"),
                     v === "no" ? "NO" : v);
      tr.appendChild(td);
    }
    if (r.reason) tr.title = r.reason;
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  body.appendChild(table);
}

// ------------------------------------------------------------- drift strip
export function renderDriftStrip(data) {
  const body = _body("drift-strip-panel");
  if (!body) return;
  if (!data || data.ok === false) {
    return _fail("drift-strip-panel", data && data.reason);
  }

  const strip = _el("div", "strip");
  for (const p of data.pills) {
    const cls = p.state === "ok" ? "pill"
      : p.state === "amber" ? "pill amber"
      : p.state === "red" ? "pill red" : "pill unknown";
    const pill = _el("div", cls);
    pill.appendChild(_el("span", "k", p.label));
    pill.appendChild(_el("span", "v", p.value));
    if (p.reason) pill.title = p.reason;
    strip.appendChild(pill);
  }
  body.appendChild(strip);

  const cap = _el("p", "ops-cap");
  cap.textContent = data.amber_count === 0
    ? "all sources agree"
    : `${data.amber_count} pill(s) out of agreement`;
  body.appendChild(cap);
}

// ------------------------------------------------------------- gated queue
export function renderGatedQueue(data) {
  const body = _body("gated-queue-panel");
  if (!body) return;
  if (!data || data.ok === false) {
    return _fail("gated-queue-panel", data && data.reason);
  }

  const q = _el("div", "q");
  for (const b of data.buckets) {
    if (!b.open && !b.done) continue;
    const mode = _el("span", "mode " + b.mode.toLowerCase().replace(/[^a-z]/g, ""), b.mode);
    q.appendChild(mode);
    q.appendChild(_el("span", "what", b.label));
    q.appendChild(_el("span", "n", `${b.open} open / ${b.done} done`));
  }
  body.appendChild(q);

  const foot = _el("div", "countdown");
  foot.appendChild(_el("span", "cd-label", "Open, gated on a real game"));
  const right = _el("span");
  right.appendChild(_el("span", "big", String(data.total_open)));
  right.appendChild(_el("span", "cd-label", ` of ${data.total_open + data.total_done} rows`));
  foot.appendChild(right);
  body.appendChild(foot);
}

// --------------------------------------------------------------- entrypoint
export async function renderOpsPanels() {
  // Settled, not all - one dead route must not blank the other two panels.
  const [seam, drift, gated] = await Promise.allSettled([
    _get(ENDPOINTS.seam), _get(ENDPOINTS.drift), _get(ENDPOINTS.gated),
  ]);

  seam.status === "fulfilled"
    ? renderSeamMap(seam.value) : _fail("seam-map-panel", String(seam.reason));
  drift.status === "fulfilled"
    ? renderDriftStrip(drift.value) : _fail("drift-strip-panel", String(drift.reason));
  gated.status === "fulfilled"
    ? renderGatedQueue(gated.value) : _fail("gated-queue-panel", String(gated.reason));
}
