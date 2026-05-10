// Active Match panel module (s159 — step 1 scaffold).
//
// Step 1 ships the empty render shell wired into the main dispatcher.
// The render() entrypoint runs on every onState envelope when the
// active-match view is current AND the game mode is in-game. It
// updates the sub-line and a small set of placeholder fields so the
// pane is visibly responsive to live data — but doesn't yet render
// the curated CALL / BUILD / MAP content. Those land in steps 2-4.
//
// Auto-promote behavior (gating in main.js _viewAutoDerive):
//   activeMatchEnabled() AND mode in {sr, aram, arena, brawl}
//     → "active-match"
// Otherwise the existing in-game default ("last-match") wins, so
// nothing changes for users who haven't opted in.

const _AM = {
  sub:        () => document.getElementById("am-sub"),
  callBody:   () => document.getElementById("am-call-body"),
  buildBody:  () => document.getElementById("am-build-body"),
  mapBody:    () => document.getElementById("am-map-body"),
};

// Flag check used by main.js view-router. Two opt-in paths so the
// preference survives a refresh:
//   1. ?am=1 in the URL — one-shot for testing.
//   2. localStorage.activeMatch === '1' — sticky for daily use.
export function activeMatchEnabled() {
  try {
    if (typeof location !== "undefined"
        && location.search
        && location.search.includes("am=1")) {
      // Sticky-promote when the URL flag fires so the next load
      // doesn't need the query string. Operator can clear via
      // localStorage.removeItem('activeMatch').
      try { localStorage.setItem("activeMatch", "1"); } catch (_) {}
      return true;
    }
    return localStorage.getItem("activeMatch") === "1";
  } catch (_) {
    return false;
  }
}

export function renderActiveMatch(payload, ctx) {
  // ctx: { mode: state.mode, lcuPhase: lcu.phase }
  // Defensive: every getter is null-safe so a missing pane in DOM
  // (older HTML cache) doesn't crash the dispatcher chain.
  const p = payload || {};
  const mode = (ctx && ctx.mode) || "—";
  const phase = (ctx && ctx.lcuPhase) || "—";

  const sub = _AM.sub();
  if (sub) {
    const champ = p.champion || "—";
    const time = p.game_time || "—";
    sub.textContent = `${mode.toUpperCase()} · ${champ} · ${time} · phase ${phase}`;
  }

  // Step 1 placeholders — surface a few raw fields so the user can
  // confirm data is reaching the view before steps 2-4 fill in the
  // curated layout. Plain text only; no DOM scaffolding promised by
  // the final design (CALL fold, DS icons, static map) yet.
  const call = _AM.callBody();
  if (call) {
    const action = p.action || "";
    const next = p.next || "";
    const objective = p.objective || "";
    if (action || next || objective) {
      call.innerHTML = ""; // clear placeholder
      if (action)    call.appendChild(_line("ACTION",    action));
      if (objective) call.appendChild(_line("OBJECTIVE", objective));
      if (next)      call.appendChild(_line("NEXT",      next));
    }
  }

  const build = _AM.buildBody();
  if (build) {
    const picks = Array.isArray(p.daemon_slayer_picks) ? p.daemon_slayer_picks : [];
    const owned = Array.isArray(p.items) ? p.items : [];
    if (picks.length || owned.length) {
      build.innerHTML = "";
      if (picks.length) {
        const dsLine = picks.slice(0, 5)
          .map((r) => `${r.name || r.item_name || "?"} +${(r.delta_dps || 0).toFixed(0)}dps`)
          .join("  ·  ");
        build.appendChild(_line("DS ENGINE", dsLine));
      }
      if (owned.length) {
        build.appendChild(_line("OWNED", owned.join(" · ")));
      }
    }
  }

  const map = _AM.mapBody();
  if (map) {
    // Step 1 placeholder — step 4 swaps in the static SR/ARAM/Arena
    // map image + ZOI/threat overlay layer.
    const enemyComp = Array.isArray(p.enemy_comp) ? p.enemy_comp : [];
    if (enemyComp.length) {
      map.innerHTML = "";
      map.appendChild(_line("ENEMY", enemyComp.join(" / ")));
    }
  }
}

function _line(label, value) {
  const row = document.createElement("div");
  row.style.cssText = "margin-bottom:10px;font-size:13px;line-height:1.45;";
  const lbl = document.createElement("span");
  lbl.style.cssText = "color:var(--text-faint);letter-spacing:0.12em;font-size:10px;font-weight:700;display:block;margin-bottom:2px;";
  lbl.textContent = label;
  const val = document.createElement("span");
  val.style.cssText = "color:var(--text);";
  val.textContent = value;
  row.appendChild(lbl);
  row.appendChild(val);
  return row;
}
