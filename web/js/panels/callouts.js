// Deterministic objective/spike CALLOUTS + macro LEAD projection.
//
// Haiku-elimination wave 3 (item 265 W3E): both surfaces are computed
// server-side with ZERO LLM and shipped in /api/state as top-level
// state.callouts (list) + state.lead_projection (dict). This module is
// render-only - it never fetches, never posts, never computes; it just
// paints what the deterministic generators already produced.
//
// Two mounts inside the RIGHT NOW panel:
//   #rn-lead     - one macro-read pill (state.lead_projection.line) with a
//                  state-colored accent (ahead=green / behind=amber-red /
//                  even=neutral) + a small state + magnitude tag. Hidden
//                  when lead_projection is empty.
//   #rn-callouts - up to 3 compact callout rows; each row = the line + an
//                  ETA chip. ETA: eta_s<=0 -> "NOW" (highlight);
//                  eta_s>0 -> "Mm:Ss" (e.g. 90 -> "1:30"); eta_s null ->
//                  no chip. Hidden when callouts is empty.
//
// Render is idempotent (sig-dedup, mirrors coach_choices.js) + fail-soft
// (a missing mount or a malformed state never throws). The chip UI for
// state.coach.choices (coach_choices.js -> #rn-choices) is UNCHANGED.

const LEAD_MOUNT_ID = "rn-lead";
const CALLOUTS_MOUNT_ID = "rn-callouts";

// Module-level dedup signatures so a steady state-tick re-render is a
// no-op (the deterministic generators bucket game_time to ~5s, so the
// payload is stable across many ticks).
let _lastLeadSig = "";
let _lastCalloutsSig = "";

// --- Lead projection ------------------------------------------------------

function _leadSig(lead) {
  if (!lead || typeof lead !== "object") return "";
  const line = lead.line || "";
  if (!line) return "";
  return `${lead.state || ""}:${lead.magnitude || ""}:${line}`;
}

// Map the lead state to a CSS state class. Only "ahead" / "behind" /
// "even" are valid; anything else falls to neutral.
function _leadStateClass(state) {
  if (state === "ahead") return "rc-lead-ahead";
  if (state === "behind") return "rc-lead-behind";
  return "rc-lead-even";
}

// Every class this module owns on the lead mount. overlay_layout.js writes its
// OWN classes onto that same node - ovx-widget (the position:fixed Hextech
// frame), ovx-hidden (the operator's per-widget hide), ovx-dragging - so a
// wholesale `className =` here drops the frame and un-hides a hidden widget
// until the debounced re-place pass repairs it up to 150ms later. Add + remove
// only what we own.
const LEAD_CLASSES = ["rc-lead", "rc-lead-ahead", "rc-lead-behind", "rc-lead-even"];

function _applyLeadClasses(mount, stateClass) {
  for (const c of LEAD_CLASSES) mount.classList.remove(c);
  if (stateClass) mount.classList.add("rc-lead", stateClass);
}

function _leadHtml(lead) {
  const line = (lead.line || "").slice(0, 120);
  const state = (lead.state || "even").slice(0, 16);
  const mag = (lead.magnitude || "").slice(0, 16);
  const tag = mag ? `${state} - ${mag}` : state;
  return `
    <span class="rc-lead-line">${_escape(line)}</span>
    <span class="rc-lead-tag">${_escape(tag)}</span>`;
}

// --- Callouts -------------------------------------------------------------

// Format an ETA in seconds as a chip string. eta_s <= 0 -> "NOW";
// eta_s > 0 -> "Mm:Ss" (e.g. 90 -> "1:30", 605 -> "10:05"); eta_s null /
// undefined / non-finite -> "" (caller omits the chip).
function _fmtEta(eta_s) {
  if (eta_s === null || eta_s === undefined) return "";
  const n = Number(eta_s);
  if (!Number.isFinite(n)) return "";
  if (n <= 0) return "NOW";
  const total = Math.round(n);
  const mm = Math.floor(total / 60);
  const ss = total % 60;
  return `${mm}:${ss < 10 ? "0" : ""}${ss}`;
}

function _calloutsSig(callouts) {
  if (!Array.isArray(callouts) || callouts.length === 0) return "";
  return callouts
    .slice(0, 3)
    .map((c) => `${c.tag || ""}:${c.kind || ""}:${c.line || ""}:${c.eta_s}`)
    .join("|");
}

function _calloutRowHtml(c) {
  const line = (c.line || "").slice(0, 120);
  const kind = (c.kind || "").slice(0, 24);
  const etaStr = _fmtEta(c.eta_s);
  const now = etaStr === "NOW";
  const chip = etaStr
    ? `<span class="rc-co-eta${now ? " rc-co-now" : ""}">${_escape(etaStr)}</span>`
    : "";
  return `
    <div class="rc-co-row" data-kind="${_escape(kind)}">
      <span class="rc-co-line">${_escape(line)}</span>
      ${chip}
    </div>`;
}

// --- Shared ---------------------------------------------------------------

// Minimal HTML-escape for the text fields. The deterministic generators
// emit ASCII directive text, but escape defensively so a future change
// to those tables can never inject markup here.
function _escape(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function renderLead(state) {
  const mount = document.getElementById(LEAD_MOUNT_ID);
  if (!mount) return;
  const lead = (state && state.lead_projection) || {};
  const sig = _leadSig(lead);
  if (sig === "") {
    if (_lastLeadSig !== "") {
      mount.innerHTML = "";
      mount.hidden = true;
      _applyLeadClasses(mount, "");
      _lastLeadSig = "";
    }
    return;
  }
  if (sig === _lastLeadSig) return;
  _lastLeadSig = sig;
  mount.hidden = false;
  _applyLeadClasses(mount, _leadStateClass(lead.state));
  mount.innerHTML = _leadHtml(lead);
}

export function renderCallouts(state) {
  const mount = document.getElementById(CALLOUTS_MOUNT_ID);
  if (!mount) return;
  const callouts = (state && Array.isArray(state.callouts)) ? state.callouts : [];
  const sig = _calloutsSig(callouts);
  if (sig === "") {
    if (_lastCalloutsSig !== "") {
      mount.innerHTML = "";
      mount.hidden = true;
      _lastCalloutsSig = "";
    }
    return;
  }
  if (sig === _lastCalloutsSig) return;
  _lastCalloutsSig = sig;
  mount.hidden = false;
  mount.innerHTML = callouts.slice(0, 3).map(_calloutRowHtml).join("");
}

// Test seam.
export const _internals = {
  _fmtEta,
  _leadSig,
  _leadStateClass,
  _calloutsSig,
  _escape,
  LEAD_MOUNT_ID,
  CALLOUTS_MOUNT_ID,
};
