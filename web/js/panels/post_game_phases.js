/* s220 PGR S2: phases-that-mattered panel.
 *
 * Renders the top-3 timeline events ranked by absolute Win Probability
 * Added (WPA) for the most-recent match. WPA is computed server-side
 * by core.post_game_score over the Match-V5 timeline cached in
 * rewind_history.db. Backend endpoint: GET /api/post-game-wpa.
 *
 * The panel mounts inside #lm-wpa-wrap which lives under the AI
 * Analysis tab of the Last Match (Post Game Review) view (s220 S4
 * reframe; pre-S4 it was the Timeline tab). Stays hidden until a
 * non-empty response lands - the route fails-soft to ok=false on
 * matches without timeline coverage (event modes, very old matches,
 * pre-Match-V5 imports), in which case the panel stays out of the way.
 *
 * Card layout per phase:
 *   [#1] [game_time]  EVENT TYPE  +X.X% wpa
 *        prob: P_before -> P_after
 *        actor team 100/200 (ally/enemy if we knew the operator's side)
 *
 * Actor-team -> "ally"/"enemy" mapping is derived from the operator's
 * team in /api/last-match (data.match.tracked_side is 100 or 200).
 */

function _escHtml(s) {
  const div = document.createElement("div");
  div.textContent = String(s == null ? "" : s);
  return div.innerHTML;
}

function _fmtMmSs(seconds) {
  const n = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(n / 60);
  const s = n % 60;
  return `${m}:${s < 10 ? "0" : ""}${s}`;
}

function _fmtPct(p) {
  const n = Math.round(Number(p) * 100);
  return `${n}%`;
}

function _fmtWpa(wpa) {
  const n = Number(wpa) || 0;
  const sign = n > 0 ? "+" : (n < 0 ? "-" : "");
  const abs = Math.abs(n) * 100;
  // One decimal for sub-percent precision; >=10% drops the decimal.
  if (abs >= 10) return `${sign}${Math.round(abs)}%`;
  return `${sign}${abs.toFixed(1)}%`;
}

function _typeLabel(t, subtype) {
  switch (t) {
    case "CHAMPION_KILL":     return "Kill";
    case "BUILDING_KILL": {
      if (subtype && /INHIB/i.test(subtype)) return "Inhibitor";
      return "Tower";
    }
    case "ELITE_MONSTER_KILL": {
      if (!subtype) return "Objective";
      const s = String(subtype).toUpperCase();
      if (s.includes("BARON"))    return "Baron";
      if (s.includes("HERALD"))   return "Herald";
      if (s.includes("HORDE"))    return "Grubs";
      if (s.includes("DRAGON"))   return "Dragon";
      return "Objective";
    }
    default: return String(t || "Event");
  }
}

/**
 * Map actor team (100/200) to "ally" / "enemy" relative to the
 * operator's side. Returns "neutral" when either side is unknown.
 */
function _teamSide(actorTeam, operatorTeam) {
  if (!actorTeam || !operatorTeam) return "neutral";
  return Number(actorTeam) === Number(operatorTeam) ? "ally" : "enemy";
}

/**
 * Render the top phases into #lm-wpa-list. Idempotent - safe to call
 * repeatedly; cleans up the container each invocation.
 */
export function renderPhases(payload, operatorTeam) {
  const wrap = document.getElementById("lm-wpa-wrap");
  const list = document.getElementById("lm-wpa-list");
  const foot = document.getElementById("lm-wpa-foot");
  if (!wrap || !list) return;

  const ok = payload && payload.ok;
  const phases = (payload && payload.top_phases) || [];
  if (!ok || !phases.length) {
    wrap.hidden = true;
    list.innerHTML = "";
    if (foot) foot.textContent = "";
    return;
  }
  wrap.hidden = false;

  const rows = phases.map((p, idx) => {
    const rank      = idx + 1;
    const clock     = _fmtMmSs(p.game_time);
    const label     = _typeLabel(p.type, p.subtype);
    const wpaStr    = _fmtWpa(p.wpa);
    const probLine  = `${_fmtPct(p.prob_before)} -> ${_fmtPct(p.prob_after)}`;
    const side      = _teamSide(p.actor_team, operatorTeam);
    const sideLabel = side === "ally" ? "Ally"
                    : (side === "enemy" ? "Enemy" : "");
    const sign      = (p.wpa || 0) > 0 ? "pos"
                    : ((p.wpa || 0) < 0 ? "neg" : "zero");
    // Sign is from the team-100 perspective. When the operator was on
    // team 200, flip the visual so green/red still mean "good for us".
    let visualSign = sign;
    if (operatorTeam && Number(operatorTeam) === 200 && sign !== "zero") {
      visualSign = sign === "pos" ? "neg" : "pos";
    }
    return `<li class="lm-wpa-row" data-side="${side}" data-sign="${visualSign}">
      <span class="lm-wpa-rank">#${rank}</span>
      <span class="lm-wpa-clock">${_escHtml(clock)}</span>
      <span class="lm-wpa-label">${_escHtml(label)}</span>
      <span class="lm-wpa-wpa">${_escHtml(wpaStr)}</span>
      <span class="lm-wpa-prob">${_escHtml(probLine)}</span>
      <span class="lm-wpa-side">${_escHtml(sideLabel)}</span>
    </li>`;
  }).join("");
  list.innerHTML = rows;

  if (foot) {
    const modelTag = (payload.model === "trained")
      ? `model v${payload.model_version || "?"} (n=${(payload.n_samples != null ? payload.n_samples : "?")})`
      : "fallback estimator";
    const evCount = payload.event_count != null ? payload.event_count : "?";
    foot.textContent = `${evCount} events analyzed - ${modelTag}`;
  }
}

/**
 * Fetch /api/post-game-wpa for the given match id and render. The
 * operatorTeam (100 or 200) lets the panel label phases ally/enemy.
 * Caller is expected to know operatorTeam from the /api/last-match
 * response (data.match.tracked_side).
 */
export function fetchAndRenderPhases(matchId, operatorTeam) {
  if (!matchId) {
    renderPhases({ ok: false }, operatorTeam);
    return;
  }
  const url = `/api/post-game-wpa?match_id=${encodeURIComponent(matchId)}`;
  fetch(url, { headers: { "Accept": "application/json" } })
    .then((r) => r.json())
    .then((data) => renderPhases(data, operatorTeam))
    .catch((err) => {
      try { console.warn("[post-game-phases] fetch failed:", err); } catch (_) {}
      renderPhases({ ok: false }, operatorTeam);
    });
}

/**
 * Hide the panel. Used when the operator switches to a non-SR match
 * (TFT / Arena) where WPA is not meaningful.
 */
export function clearPhases() {
  renderPhases({ ok: false });
}
