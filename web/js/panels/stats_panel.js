// web/js/panels/stats_panel.js
//
// Overlay-only stats mini-panel (operator 2026-06-28). An AUGMENTING readout
// beside the native HUD (a HUD *replacement* is impossible - the Live Client API
// exposes no live ability/summoner cooldowns, buffs, or wards). It shows ONLY the
// API-backed ground truth: HP + resource bars, level, CS, and the key stats the
// native HUD does not surface at a glance (ability haste, move speed, armor, MR).
//
// The scaffold is built once; every tick updates bar widths + numbers IN PLACE
// (no innerHTML churn) so the bars never flicker.

function _pct(cur, max) {
  const c = Number(cur) || 0;
  const m = Number(max) || 0;
  if (m <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((c / m) * 100)));
}

function _ensureScaffold(mount) {
  if (mount.dataset.built === "1") return;
  mount.dataset.built = "1";
  mount.innerHTML =
    '<div class="sp-head">STATS</div>' +
    '<div class="sp-bar sp-hp"><span class="sp-fill"></span><span class="sp-bar-txt"></span></div>' +
    '<div class="sp-bar sp-mp"><span class="sp-fill"></span><span class="sp-bar-txt"></span></div>' +
    '<div class="sp-grid">' +
    '<span class="sp-kv" data-k="lvl">LV -</span>' +
    '<span class="sp-kv" data-k="cs">CS -</span>' +
    '<span class="sp-kv" data-k="ah">AH -</span>' +
    '<span class="sp-kv" data-k="ms">MS -</span>' +
    '<span class="sp-kv" data-k="ar">AR -</span>' +
    '<span class="sp-kv" data-k="mr">MR -</span>' +
    "</div>";
}

function _set(mount, k, text) {
  const el = mount.querySelector('.sp-kv[data-k="' + k + '"]');
  if (el) el.textContent = text;
}

function _setBar(mount, cls, cur, max, label) {
  const bar = mount.querySelector("." + cls);
  if (!bar) return;
  const fill = bar.querySelector(".sp-fill");
  const txt = bar.querySelector(".sp-bar-txt");
  if (fill) fill.style.width = _pct(cur, max) + "%";
  if (txt) txt.textContent = label + " " + (Number(cur) || 0) + "/" + (Number(max) || 0);
}

// Self-gated on the overlay shell + a live player block (hp/mana/level present).
export function renderStatsPanel(lc) {
  const mount = document.getElementById("am-statspanel");
  if (!mount) return;
  if (!document.body || document.body.dataset.shell !== "overlay") {
    mount.hidden = true;
    return;
  }
  // hp_max is the cheapest "are we actually in a game" gate (0 out of game).
  if (!lc || !Number(lc.hp_max)) {
    mount.hidden = true;
    return;
  }
  _ensureScaffold(mount);
  _setBar(mount, "sp-hp", lc.hp, lc.hp_max, "HP");
  const st = lc.stats || {};
  const rtype = (st.resource_type || "MP").slice(0, 2).toUpperCase();
  _setBar(mount, "sp-mp", lc.mana, lc.mana_max, rtype);
  _set(mount, "lvl", "LV " + (lc.level == null ? "-" : lc.level));
  _set(mount, "cs", "CS " + (lc.cs == null ? "-" : lc.cs));
  _set(mount, "ah", "AH " + (st.ability_haste == null ? "-" : st.ability_haste));
  _set(mount, "ms", "MS " + (st.move_speed == null ? "-" : st.move_speed));
  _set(mount, "ar", "AR " + (st.armor == null ? "-" : st.armor));
  _set(mount, "mr", "MR " + (st.magic_resist == null ? "-" : st.magic_resist));
  mount.hidden = false;
}

// Test seam: drop the built-scaffold flag so a fresh render rebuilds.
export function _resetStatsPanel() {
  const mount = document.getElementById("am-statspanel");
  if (mount) {
    mount.dataset.built = "";
    mount.innerHTML = "";
  }
}
