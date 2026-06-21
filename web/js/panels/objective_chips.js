// web/js/panels/objective_chips.js
//
// QA4 (RC2 overlay): objective respawn-timer chips. A compact glance strip in
// the overlay CALL pane - "BARON 1:30 / DRAKE UP" - so the operator sees when
// the next neutral objective comes back up without opening the (overlay-hidden)
// map pane. The "biggest glance win" item.
//
// Data: dashboard/_liveclient.py ships liveclient.objective_events, the neutral
// objective KILL events Live Client emits ({name: dragon|baron|herald,
// killer_team, down_at_s}). The respawn ETA is the latest kill of each objective
// plus its spawn cycle (the same constants map_state.js uses). Live Client emits
// NO jungle-camp events, so camps are intentionally out of scope here (the same
// event gap that blocks live ward tracking) - this is objective-only.
//
// No local countdown timer: the /api/state-stream SSE re-pushes ~every second
// (game_time_s changes the payload hash), so a per-push render already gives ~1s
// chip granularity - consistent with the other overlay panels and GPU-light.
//
// Discipline (mirrors ward_cue.js / overlay_ds_controls.js): pure ESM, ASCII
// only, sig-dedup so an unchanged tick does not thrash the DOM, self-gates on
// body[data-shell="overlay"] - a cheap no-op on the 1920 dashboard.

// Spawn-cycle seconds after a kill. Matches map_state.js _OBJ_CYCLE so the two
// objective surfaces never disagree (dragon 5:00, baron 6:00, herald approx).
const OBJ_CYCLE = { dragon: 300, baron: 360, herald: 360 };
const OBJ_LABEL = { dragon: "DRAKE", baron: "BARON", herald: "HERALD" };
// Render order: baron + dragon are the high-value glances, herald last.
const OBJ_ORDER = ["baron", "dragon", "herald"];

// Compute the respawn ETA per objective that has been taken at least once.
// objectiveEvents is liveclient.objective_events; gameTimeS is the live game
// clock (liveclient.game_time_s). Returns [{name, label, etaS, up}] in
// OBJ_ORDER. Defensive: garbage in -> [] (this rides the per-tick render).
function objectiveEtas(objectiveEvents, gameTimeS) {
  const now = Number(gameTimeS);
  if (!Array.isArray(objectiveEvents) || !Number.isFinite(now)) {
    return [];
  }
  // Latest kill time per tracked objective name.
  const latest = Object.create(null);
  for (const ev of objectiveEvents) {
    if (!ev || typeof ev !== "object") {
      continue;
    }
    const name = ev.name;
    if (!OBJ_CYCLE[name]) {
      continue;
    }
    const t = Number(ev.down_at_s);
    if (!Number.isFinite(t)) {
      continue;
    }
    if (latest[name] === undefined || t > latest[name]) {
      latest[name] = t;
    }
  }
  const out = [];
  for (const name of OBJ_ORDER) {
    if (latest[name] === undefined) {
      continue;
    }
    const eta = latest[name] + OBJ_CYCLE[name] - now;
    out.push({
      name,
      label: OBJ_LABEL[name],
      etaS: eta > 0 ? Math.round(eta) : 0,
      up: eta <= 0,
    });
  }
  return out;
}

// M:SS, floored, never negative.
function fmtEta(etaS) {
  const s = Math.max(0, Math.floor(Number(etaS) || 0));
  const m = Math.floor(s / 60);
  const ss = String(s % 60).padStart(2, "0");
  return `${m}:${ss}`;
}

// Render the chip markup (pure). Empty string when nothing is pending. No
// untrusted strings flow in (name/label are from our own constant maps; etaS is
// a number), so the markup is safe to assemble directly.
function objectiveChipsHtml(chips) {
  if (!Array.isArray(chips) || !chips.length) {
    return "";
  }
  return chips
    .map(
      (c) =>
        `<span class="obj-chip ${c.name}${c.up ? " is-up" : ""}" data-obj="${c.name}">` +
        `<span class="obj-label">${c.label}</span>` +
        `<span class="obj-eta">${c.up ? "UP" : fmtEta(c.etaS)}</span></span>`
    )
    .join("");
}

// Signature over the rendered chips so an unchanged tick skips the DOM write.
function objectiveChipsSig(chips) {
  if (!Array.isArray(chips) || !chips.length) {
    return "_empty";
  }
  return chips.map((c) => `${c.name}:${c.up ? "up" : c.etaS}`).join("|");
}

// --- DOM render (overlay-only) -----------------------------------------------
let _sig = null;

// Render from the raw liveclient block (lc.objective_events + lc.game_time_s).
// Hidden everywhere except the overlay shell; the 1920 dashboard shows objective
// timing in the full map pane instead.
export function renderObjectiveChips(lc) {
  const mount = document.getElementById("am-obj-chips");
  if (!mount) {
    return;
  }
  if (!document.body || document.body.dataset.shell !== "overlay") {
    mount.hidden = true;
    return;
  }
  const block = lc && typeof lc === "object" ? lc : {};
  const chips = objectiveEtas(block.objective_events, block.game_time_s);
  const sig = objectiveChipsSig(chips);
  if (sig === _sig) {
    return;
  }
  _sig = sig;
  if (!chips.length) {
    mount.innerHTML = "";
    mount.hidden = true;
    return;
  }
  mount.innerHTML = objectiveChipsHtml(chips);
  mount.hidden = false;
}

// Test reset (module-scope sig).
export function _resetObjectiveChips() {
  _sig = null;
}

export const __test = {
  OBJ_CYCLE,
  OBJ_LABEL,
  objectiveEtas,
  fmtEta,
  objectiveChipsHtml,
  objectiveChipsSig,
};
