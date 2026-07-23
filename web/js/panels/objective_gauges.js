// web/js/panels/objective_gauges.js
//
// OQ16 (OQ3 variant A "Radial Ring Cluster"): peripheral objective gauge
// cluster - a row of full ring dials (DRAKE / BARON / ELDER) with the exact
// ETA in each ring center; the ring arc fills toward ready (full ring = UP).
// Source mockup: web/mock/oq3_variant_a.html; hues per the operator OQ3 pick
// over docs/OVERLAY_DOCTRINE.md sec 5: BARON gold #C8AA6E (--ovx-gold), DRAKE
// warn #E8A33D, ELDER red #E84057 (--ovx-red). CSS:
// web/css/panels/objective_gauges.css. (SUMMS dial removed 2026-07-05: the
// Live Client API exposes no summoner cooldowns, so it always read UP.)
//
// Data (all EXISTING /api/state fields - nothing added server-side):
//   - mode (mode_key)                      -> the SR-only gate.
//   - liveclient.game_time_s               -> dashboard/_liveclient.py:97.
//   - liveclient.objective_events          -> dashboard/_liveclient.py:265-301
//     ({name, killer_team, down_at_s, dragon_type?}).
//
// The objective schedule MIRRORS core/event_callouts.py exactly - no timer
// is fabricated beyond that canonical schedule + game_time arithmetic:
//   SR_DRAGON_FIRST_S/RESPAWN_S 300/300, SR_BARON_FIRST_S/RESPAWN_S 1200/360
//   (:66-69), _SR_ELDER_NOMINAL_S 2100 (:77), _OBJ_ACTIVE_WINDOW_S 30 (:193),
//   _SOUL_SECURED_STACKS 4 (:623). tests/test_objective_gauges_oq16.py pins
//   these copies against the Python constants so drift fails CI.
// Path mirror (core/event_callouts.py:231-336):
//   - drake: soul secured (>= 4 elemental drakes one side) -> the pit is
//     Elder, elemental row suppressed -> "-"; else a real elemental take
//     anchors last_kill + 300; else the static 300s cadence (UP inside the
//     30s active window).
//   - baron: a real take anchors last_kill + 360; else the static one-shot
//     at 1200 (UP inside the 30s window, then dropped -> "-", :334-335).
//   - elder: the canonical source encodes ONLY the nominal 2100 late marker
//     (one-shot) and NO post-kill elder respawn - so after an Elder take,
//     or once the nominal marker is long past, the dial is honestly "-".
//   - kill-anchored respawns keep UP until the next kill event lands (the
//     objective really is up - same convention as objective_chips.js:66-67).
//
// DOUBLE-ALERT CADENCE (BACKLOG "Overlay HUD micro-lifts"): each counting-down
// dial also carries an alert tier - "soon" at eta <= 90s, "imminent" at
// eta <= 10s - emitted as data-og-alert and styled in the CSS (steady tint
// then a slow pulse). Derived from the SAME etaS the ring already shows, so it
// adds no data source and cannot drift from the schedule mirror. UP and "-"
// dials never alert (UP is already the loud green state; "-" has no clock).
//
// HONEST NO-DATA: outside a live SR game (mode not "sr", or no liveclient
// game clock) the widget hides ENTIRELY - no placeholder ghosts. A single
// dial without data mid-game renders the approved "-" sentinel.
//
// Discipline (mirrors objective_chips.js / ward_cue.js): pure ESM, ASCII
// only, sig-dedup so an unchanged tick does not thrash the DOM, self-gates
// on body[data-shell="overlay"] - a cheap no-op on the 1920 dashboard.

// Canonical SR schedule mirror - see the module head + the CI drift pin.
const OG_SCHED = {
  drakeFirstS: 300,
  drakeRespawnS: 300,
  baronFirstS: 1200,
  baronRespawnS: 360,
  elderNominalS: 2100,
  activeWindowS: 30,
  soulSecuredStacks: 4,
  // Double-alert cadence (BACKLOG "Overlay HUD micro-lifts"): a dial that is
  // counting down crosses two precomputed thresholds - 90s (rotate/reset, the
  // window where a team actually starts walking) then 10s (contest now). Pure
  // arithmetic on the SAME etaS the ring already shows: nothing fetched, no
  // new field, no timer invented beyond the canonical schedule mirror above.
  alertSoonS: 90,
  alertImminentS: 10,
};

// Ring geometry: r=36 in an 88x88 viewBox; circumference = 2*pi*36.
const OG_RING_C = 226.19;

// Render order matches the mockup: DRAKE, BARON, ELDER.
const OG_ORDER = ["drake", "baron", "elder"];
const OG_LABEL = { drake: "DRAKE", baron: "BARON", elder: "ELDER" };

// --- pure helpers -------------------------------------------------------------

// Elemental (soul-counting) drake: a dragon kill that is NOT the Elder
// (mirror of core/event_callouts._is_elemental_drake:671-677).
function _isElementalDrake(ev) {
  if (!ev || typeof ev !== "object" || ev.name !== "dragon") return false;
  const dt = ev.dragon_type;
  return !(typeof dt === "string" && dt.trim().toLowerCase() === "elder");
}

// Latest down_at_s of a kill matching pred, or null (fail-soft on garbage).
function _lastKillT(events, pred) {
  if (!Array.isArray(events)) return null;
  let last = null;
  for (const ev of events) {
    if (!ev || typeof ev !== "object" || !pred(ev)) continue;
    const t = Number(ev.down_at_s);
    if (!Number.isFinite(t)) continue;
    if (last === null || t > last) last = t;
  }
  return last;
}

// Elemental-drake kills per side (mirror _elemental_drake_counts:680-691).
function _elementalCounts(events) {
  const counts = { ally: 0, enemy: 0 };
  if (!Array.isArray(events)) return counts;
  for (const ev of events) {
    if (!_isElementalDrake(ev)) continue;
    if (ev.killer_team === "ally" || ev.killer_team === "enemy") {
      counts[ev.killer_team] += 1;
    }
  }
  return counts;
}

// Static cadence ETA (mirror _objective_callouts:292-311): before the first
// spawn count down to it; after, count to the next cadence boundary, except
// inside the 30s post-spawn active window where eta <= 0 means UP now.
function _staticCadenceEta(gt, firstS, cadenceS) {
  if (gt < firstS) return firstS - gt;
  const elapsed = gt - firstS;
  const nPassed = Math.floor(elapsed / cadenceS);
  const lastSpawn = firstS + nPassed * cadenceS;
  if (gt - lastSpawn <= OG_SCHED.activeWindowS) return lastSpawn - gt; // <= 0
  return firstS + (nPassed + 1) * cadenceS - gt;
}

// Double-alert tier for a counting-down dial: "" (quiet) | "soon" (<= 90s)
// | "imminent" (<= 10s). Only an "eta" dial alerts - an UP dial is already the
// loud green state and a "-" dial has no clock, so neither escalates.
function _alertTier(state, etaS) {
  if (state !== "eta") return "";
  const t = Number(etaS);
  if (!Number.isFinite(t) || t <= 0) return "";
  if (t <= OG_SCHED.alertImminentS) return "imminent";
  if (t <= OG_SCHED.alertSoonS) return "soon";
  return "";
}

// One dial descriptor: state "eta" (counting down) | "up" | "none" ("-").
// frac = ring fill toward ready in [0,1] (up = 1, none = 0).
// alert = the double-alert tier (see _alertTier).
function _dial(key, state, etaS, windowS) {
  if (state === "eta") {
    const w = Number.isFinite(windowS) && windowS > 0 ? windowS : etaS;
    const frac = Math.max(0, Math.min(1, 1 - etaS / (w > 0 ? w : 1)));
    return {
      key, label: OG_LABEL[key], state, etaS, frac,
      alert: _alertTier(state, etaS),
    };
  }
  return {
    key, label: OG_LABEL[key], state, etaS: 0,
    frac: state === "up" ? 1 : 0, alert: "",
  };
}

function _drakeDial(events, gt) {
  const counts = _elementalCounts(events);
  if (Math.max(counts.ally, counts.enemy) >= OG_SCHED.soulSecuredStacks) {
    return _dial("drake", "none"); // soul locked: pit is Elder (ec.py:254-255)
  }
  const last = _lastKillT(events, _isElementalDrake);
  if (last !== null) {
    const eta = last + OG_SCHED.drakeRespawnS - gt;
    return eta > 0
      ? _dial("drake", "eta", eta, OG_SCHED.drakeRespawnS)
      : _dial("drake", "up");
  }
  const eta = _staticCadenceEta(gt, OG_SCHED.drakeFirstS, OG_SCHED.drakeRespawnS);
  return eta > 0 ? _dial("drake", "eta", eta, OG_SCHED.drakeFirstS) : _dial("drake", "up");
}

function _baronDial(events, gt) {
  const last = _lastKillT(events, (ev) => ev.name === "baron");
  if (last !== null) {
    const eta = last + OG_SCHED.baronRespawnS - gt;
    return eta > 0
      ? _dial("baron", "eta", eta, OG_SCHED.baronRespawnS)
      : _dial("baron", "up");
  }
  // Static one-shot (ec.py:318-335): UP inside the active window, "-" after.
  const eta = OG_SCHED.baronFirstS - gt;
  if (eta > 0) return _dial("baron", "eta", eta, OG_SCHED.baronFirstS);
  if (eta >= -OG_SCHED.activeWindowS) return _dial("baron", "up");
  return _dial("baron", "none");
}

function _elderDial(events, gt) {
  // The canonical source has NO post-kill elder respawn constant - after an
  // Elder take the dial is honestly "-" rather than an invented timer.
  const lastElder = _lastKillT(events, (ev) =>
    ev.name === "dragon" && !_isElementalDrake(ev));
  if (lastElder !== null) return _dial("elder", "none");
  const eta = OG_SCHED.elderNominalS - gt; // nominal late marker (ec.py:77,111)
  if (eta > 0) return _dial("elder", "eta", eta, OG_SCHED.elderNominalS);
  if (eta >= -OG_SCHED.activeWindowS) return _dial("elder", "up");
  return _dial("elder", "none");
}

// Compute all 3 dials, or null when the widget must hide entirely
// (HONEST NO-DATA: not SR, or no live game clock).
function computeGauges(mode, lc) {
  if (mode !== "sr") return null;
  const block = lc && typeof lc === "object" ? lc : {};
  const gt = Number(block.game_time_s);
  if (!Number.isFinite(gt)) return null;
  const events = Array.isArray(block.objective_events)
    ? block.objective_events
    : [];
  const elder = _elderDial(events, gt);
  // Operator 2026-07-05: once Elder is up (available) or has been taken, the
  // pit is Elder - the elemental drake dial is redundant, so suppress it to "-".
  const elderTaken = _lastKillT(
    events, (ev) => ev.name === "dragon" && !_isElementalDrake(ev)) !== null;
  const drake = (elder.state === "up" || elderTaken)
    ? _dial("drake", "none")
    : _drakeDial(events, gt);
  return [drake, _baronDial(events, gt), elder];
}

// M:SS, floored, never negative (objective_chips.js fmtEta idiom).
function fmtEta(etaS) {
  const s = Math.max(0, Math.floor(Number(etaS) || 0));
  const m = Math.floor(s / 60);
  const ss = String(s % 60).padStart(2, "0");
  return `${m}:${ss}`;
}

// Render one dial (pure). No untrusted strings flow in - key/label come
// from our own constant maps, everything else is a number - so the markup
// is safe to assemble directly.
function dialHtml(d) {
  const arc = (Math.max(0, Math.min(1, d.frac)) * OG_RING_C).toFixed(1);
  const eta = d.state === "up" ? "UP" : d.state === "none" ? "-" : fmtEta(d.etaS);
  return (
    `<div class="og-dial og-${d.key}" data-obj="${d.key}" data-og-state="${d.state}"`
    + ` data-og-alert="${d.alert || ""}">`
    + `<svg viewBox="0 0 88 88" width="88" height="88" aria-hidden="true">`
    + `<circle class="og-track" cx="44" cy="44" r="36"></circle>`
    + `<circle class="og-arc" cx="44" cy="44" r="36"`
    + ` stroke-dasharray="${arc} ${OG_RING_C}"></circle>`
    + `</svg>`
    + `<div class="og-inner"><div class="og-label">${d.label}</div>`
    + `<div class="og-eta${d.state === "up" ? " is-up" : ""}">${eta}</div>`
    + `</div></div>`
  );
}

function gaugesHtml(dials) {
  return `<div class="og-grid">${dials.map(dialHtml).join("")}</div>`;
}

// Signature over the rendered dials so an unchanged tick skips the DOM write.
function gaugesSig(dials) {
  return dials
    .map((d) => `${d.key}:${d.state}:${Math.round(d.etaS)}:${d.frac.toFixed(2)}`
      + `:${d.alert || ""}`)
    .join("|");
}

// --- DOM render (overlay-only) -------------------------------------------------
let _sig = null;

// env = { mode, liveclient, cooldowns } - threaded by main.js at both the
// ui_mock and live active-match dispatch sites (beside renderObjectiveChips).
export function renderObjectiveGauges(env) {
  const mount = document.getElementById("am-obj-gauges");
  if (!mount) return;
  if (!document.body || document.body.dataset.shell !== "overlay") {
    mount.hidden = true;
    return;
  }
  const e = env && typeof env === "object" ? env : {};
  const dials = computeGauges(e.mode, e.liveclient);
  if (!dials) {
    if (_sig !== "_hidden") {
      mount.innerHTML = "";
      mount.hidden = true;
      _sig = "_hidden";
    }
    return;
  }
  const sig = gaugesSig(dials);
  if (sig === _sig) return;
  _sig = sig;
  mount.innerHTML = gaugesHtml(dials);
  mount.hidden = false;
}

// Test reset (module-scope sig).
export function _resetObjectiveGauges() {
  _sig = null;
}

export const __test = {
  OG_SCHED,
  OG_RING_C,
  computeGauges,
  _alertTier,
  _drakeDial,
  fmtEta,
  dialHtml,
  gaugesHtml,
  gaugesSig,
};
