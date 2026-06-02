/* Post-Game win-prob "phases that mattered" graph (PGR reframe S3 -
 * docs/PGR_REFRAME_S2.md staging S3).
 *
 * The aggregator-G-style "what swung the game" curve. post_game_phases.js
 * already renders the top-3 swing events as CARDS under the AI Analysis
 * tab; this panel adds the GRAPH - an inline SVG line of the team win
 * probability over game time, with the high-impact swing events plotted
 * as annotated dots.
 *
 * Source: GET /api/post-game-wpa (the same route post_game_phases.js
 * fetches). It returns events[] (each {game_time, type, wpa, prob_before,
 * prob_after, actor_team, victim, subtype}), top_phases[], frame_count,
 * model. prob_after is the team-100 win-probability AFTER the event.
 *
 * Win-prob is intrinsically team-100 from the model. We map team-100 ->
 * ally/enemy via the operator's side so the curve reads "MY win prob":
 * when the operator is on team 200 we plot 1 - prob_after (and the
 * baseline stays at 50%). The shade above/below 50% is therefore always
 * "ahead / behind for US".
 *
 * Inline SVG only - no external chart lib. Idempotent render. Fail-soft
 * hidden when ok=false or events empty (event modes, very old matches,
 * pre-Match-V5 imports) - the same fail-soft contract as the phases
 * cards next to it.
 */

const MOUNT_ID = "pgr-winprob-mount";

// SVG viewBox geometry (unitless; CSS scales it responsively).
const VB_W = 600;
const VB_H = 180;
const PAD_L = 40; // y-axis labels
const PAD_R = 12;
const PAD_T = 12;
const PAD_B = 22; // x-axis time labels
const PLOT_W = VB_W - PAD_L - PAD_R;
const PLOT_H = VB_H - PAD_T - PAD_B;

// A swing event is "annotatable" when its absolute WPA clears this. The
// top_phases the route already ranks always qualify; this catches extra
// big swings if the route did not surface enough.
const _DOT_ABS_WPA = 0.03;
const _MAX_DOTS = 6;

function _escHtml(s) {
  const div = document.createElement("div");
  div.textContent = String(s == null ? "" : s);
  return div.innerHTML;
}

function _isMock() {
  return !!(document.body && document.body.dataset.uiMock === "1");
}

function _fmtMmSs(seconds) {
  const n = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(n / 60);
  const s = n % 60;
  return `${m}:${s < 10 ? "0" : ""}${s}`;
}

function _fmtSignedPP(wpa) {
  const pp = Number(wpa) * 100;
  const sign = pp >= 0 ? "+" : "";
  return `${sign}${pp.toFixed(1)}pp`;
}

function _typeLabel(t, subtype) {
  switch (t) {
    case "CHAMPION_KILL":
      return "Kill";
    case "BUILDING_KILL":
      return subtype && /INHIB/i.test(subtype) ? "Inhibitor" : "Tower";
    case "ELITE_MONSTER_KILL": {
      if (!subtype) return "Objective";
      const s = String(subtype).toUpperCase();
      if (s.includes("BARON")) return "Baron";
      if (s.includes("HERALD")) return "Herald";
      if (s.includes("HORDE")) return "Grubs";
      if (s.includes("DRAGON")) return "Dragon";
      return "Objective";
    }
    default:
      return String(t || "Event");
  }
}

/**
 * Map an event's actor team to "ally" / "enemy" relative to the operator.
 * Returns "neutral" when either side is unknown.
 */
function _eventSide(actorTeam, operatorTeam) {
  if (!actorTeam || !operatorTeam) return "neutral";
  return Number(actorTeam) === Number(operatorTeam) ? "ally" : "enemy";
}

/**
 * Convert the model's team-100 win-prob into the operator's "MY win prob".
 * When the operator is on team 200 the value is mirrored about 0.5.
 */
function _myWinProb(prob100, operatorTeam) {
  const p = Number(prob100);
  if (!isFinite(p)) return 0.5;
  if (Number(operatorTeam) === 200) return 1 - p;
  return p;
}

/** Build the {x,y} pixel point for a (game_time, win_prob) pair. */
function _point(t, prob, tMin, tSpan) {
  const fx = tSpan > 0 ? (t - tMin) / tSpan : 0;
  const x = PAD_L + fx * PLOT_W;
  // y inverted: prob 1.0 at top, 0.0 at bottom.
  const y = PAD_T + (1 - Math.max(0, Math.min(1, prob))) * PLOT_H;
  return { x, y };
}

/**
 * Build the SVG markup string for the win-prob curve.
 * `events` is the ascending-by-time event list; operatorTeam 100/200/0.
 */
function _svgHtml(events, topPhases, operatorTeam) {
  const evs = (events || [])
    .filter((e) => e && e.game_time != null && e.prob_after != null)
    .slice()
    .sort((a, b) => Number(a.game_time) - Number(b.game_time));
  if (evs.length < 2) return "";

  const times = evs.map((e) => Number(e.game_time));
  const tMin = Math.min(...times, 0);
  const tMax = Math.max(...times);
  const tSpan = tMax - tMin || 1;

  // Curve points (operator-perspective win prob over time).
  const pts = evs.map((e) =>
    _point(Number(e.game_time), _myWinProb(e.prob_after, operatorTeam), tMin, tSpan),
  );
  const polyPts = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

  // 50% baseline.
  const yMid = PAD_T + 0.5 * PLOT_H;

  // Two area fills - above 50% (ally-favoured) and below (enemy-favoured)
  // are split by clipping the polyline area against the midline. We
  // approximate with one filled area to the baseline tinted by the final
  // value, plus the midline; a precise crossing-split is overkill for the
  // single-match read.
  const lastProb = _myWinProb(evs[evs.length - 1].prob_after, operatorTeam);
  const areaCls = lastProb >= 0.5 ? "pwp-area-ally" : "pwp-area-enemy";
  const areaPts =
    `${PAD_L},${yMid.toFixed(1)} ` +
    polyPts +
    ` ${(PAD_L + PLOT_W).toFixed(1)},${yMid.toFixed(1)}`;

  // Swing dots: top_phases first, then any extra big swing not already in.
  const dotSrc = [];
  const seen = new Set();
  (topPhases || []).forEach((p) => {
    if (p && p.game_time != null) {
      dotSrc.push(p);
      seen.add(p.game_time);
    }
  });
  evs.forEach((e) => {
    if (dotSrc.length >= _MAX_DOTS) return;
    if (seen.has(e.game_time)) return;
    if (Math.abs(Number(e.wpa) || 0) >= _DOT_ABS_WPA) {
      dotSrc.push(e);
      seen.add(e.game_time);
    }
  });

  const dots = dotSrc
    .slice(0, _MAX_DOTS)
    .map((e) => {
      const p = _point(
        Number(e.game_time),
        _myWinProb(e.prob_after, operatorTeam),
        tMin,
        tSpan,
      );
      const side = _eventSide(e.actor_team, operatorTeam);
      // good for us when our prob rose: ally-killed or enemy-objective
      // is already encoded in the wpa sign from team-100 perspective.
      const wpaMine =
        Number(operatorTeam) === 200 ? -(Number(e.wpa) || 0) : Number(e.wpa) || 0;
      const sign = wpaMine > 0 ? "pos" : wpaMine < 0 ? "neg" : "zero";
      const label = _typeLabel(e.type, e.subtype);
      const title = `${label} ${_fmtMmSs(e.game_time)} ${_fmtSignedPP(wpaMine)}`;
      return (
        `<circle class="pwp-dot pwp-dot-${sign}" cx="${p.x.toFixed(1)}" ` +
        `cy="${p.y.toFixed(1)}" r="4"><title>${_escHtml(title)}</title></circle>`
      );
    })
    .join("");

  // y-axis gridline labels at 0 / 50 / 100.
  const yTop = PAD_T;
  const yBot = PAD_T + PLOT_H;
  // x-axis end-time label.
  const tMaxLabel = _fmtMmSs(tMax);

  return (
    `<svg class="pwp-svg" viewBox="0 0 ${VB_W} ${VB_H}" ` +
    `preserveAspectRatio="none" role="img" ` +
    `aria-label="win probability over game time">` +
    // axis frame
    `<line class="pwp-axis" x1="${PAD_L}" y1="${yTop}" x2="${PAD_L}" y2="${yBot}"></line>` +
    `<line class="pwp-axis" x1="${PAD_L}" y1="${yBot}" x2="${PAD_L + PLOT_W}" y2="${yBot}"></line>` +
    // 50% baseline
    `<line class="pwp-baseline" x1="${PAD_L}" y1="${yMid.toFixed(1)}" ` +
    `x2="${(PAD_L + PLOT_W).toFixed(1)}" y2="${yMid.toFixed(1)}"></line>` +
    // shaded area
    `<polygon class="pwp-area ${areaCls}" points="${areaPts}"></polygon>` +
    // the curve
    `<polyline class="pwp-line" points="${polyPts}"></polyline>` +
    // swing dots
    dots +
    // y labels
    `<text class="pwp-ylab" x="4" y="${(yTop + 4).toFixed(0)}">100%</text>` +
    `<text class="pwp-ylab" x="4" y="${(yMid + 4).toFixed(0)}">50%</text>` +
    `<text class="pwp-ylab" x="4" y="${(yBot).toFixed(0)}">0%</text>` +
    // x labels
    `<text class="pwp-xlab" x="${PAD_L}" y="${(VB_H - 6).toFixed(0)}">0:00</text>` +
    `<text class="pwp-xlab pwp-xlab-end" x="${(PAD_L + PLOT_W).toFixed(0)}" ` +
    `y="${(VB_H - 6).toFixed(0)}">${_escHtml(tMaxLabel)}</text>` +
    `</svg>`
  );
}

function _cardHtml(payload, operatorTeam) {
  const events = (payload && payload.events) || [];
  const topPhases = (payload && payload.top_phases) || [];
  const svg = _svgHtml(events, topPhases, operatorTeam);
  if (!svg) return "";
  const modelTag =
    payload.model === "trained"
      ? `model v${payload.model_version || "?"}`
      : "fallback estimator";
  const evCount = payload.event_count != null ? payload.event_count : events.length;
  const sideNote =
    operatorTeam === 100 || operatorTeam === 200
      ? "your win probability"
      : "team-100 win probability";
  return (
    `<div class="pwp-card">` +
    `<div class="pwp-head">` +
    `<span class="pwp-title">WIN PROBABILITY - PHASES THAT MATTERED</span>` +
    `<span class="pwp-sub">${_escHtml(sideNote)} over the match . ${evCount} events . ${_escHtml(modelTag)}</span>` +
    `</div>` +
    `<div class="pwp-chart pwp-${operatorTeam === 100 || operatorTeam === 200 ? "sided" : "neutral"}">` +
    svg +
    `</div>` +
    `<div class="pwp-legend">` +
    `<span class="pwp-legend-item pwp-ally">above 50% = ahead</span>` +
    `<span class="pwp-legend-item pwp-enemy">below 50% = behind</span>` +
    `<span class="pwp-legend-hint">hover a dot for the swing</span>` +
    `</div>` +
    `</div>`
  );
}

/**
 * Render the win-prob graph from a /api/post-game-wpa payload. Idempotent.
 * operatorTeam (100/200/0) controls the ally/enemy perspective.
 */
export function renderWinprob(payload, operatorTeam) {
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  const ok = payload && payload.ok;
  const events = (payload && payload.events) || [];
  if (!ok || events.length < 2) {
    mount.innerHTML = "";
    mount.hidden = true;
    return;
  }
  try {
    const html = _cardHtml(payload, operatorTeam);
    mount.innerHTML = html;
    mount.hidden = !html;
  } catch (_e) {
    mount.innerHTML = "";
    mount.hidden = true;
  }
}

/**
 * Fetch /api/post-game-wpa for the given match + render the graph. Under
 * ?ui_mock=1 the fetch short-circuits to the local fixture so the audit
 * capture stands without a populated corpus. operatorTeam (100/200) lets
 * the curve read as "MY win prob"; caller derives it from the
 * /api/last-match enriched.team_id (the reliable operator-side source).
 */
export function renderPgrWinprob(matchId, operatorTeam) {
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  if (_isMock()) {
    fetch("/data/ui_mock/pgr_winprob.json", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => renderWinprob(data || { ok: false }, operatorTeam))
      .catch(() => renderWinprob({ ok: false }, operatorTeam));
    return;
  }
  if (!matchId) {
    renderWinprob({ ok: false }, operatorTeam);
    return;
  }
  const url = `/api/post-game-wpa?match_id=${encodeURIComponent(matchId)}`;
  fetch(url, { headers: { Accept: "application/json" } })
    .then((r) => r.json())
    .then((data) => renderWinprob(data, operatorTeam))
    .catch((err) => {
      try {
        console.warn("[pgr-winprob] fetch failed:", err);
      } catch (_) {}
      renderWinprob({ ok: false }, operatorTeam);
    });
}

/** Hide the panel (non-SR modes / no timeline). */
export function clearWinprob() {
  renderWinprob({ ok: false }, 0);
}

// --- test hooks -----------------------------------------------------
export const __test = {
  _myWinProb,
  _eventSide,
  _point,
  _svgHtml,
  _cardHtml,
  _typeLabel,
  _fmtMmSs,
  _fmtSignedPP,
  VB_W,
  VB_H,
};
