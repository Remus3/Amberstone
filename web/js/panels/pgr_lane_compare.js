/* Post-Game lane / role comparison (PGR reframe S4 -
 * docs/PGR_REFRAME_S2.md staging S4).
 *
 * Operator vs lane opponent (same role slot): final gold / cs / damage /
 * kill-participation, each as a head-to-head bar with a +/- delta.
 *
 * IMPORTANT data note (verified live 2026-06-02): the /api/last-match
 * payload carries NO team_position field and NO per-participant @N
 * timeline. enriched.timeline.series is a TEAM-AGGREGATE diff (operator
 * team minus enemy, signed) - not per-lane. So the lane pairing uses the
 * Riot participant-slot convention (roster is in canonical participant
 * order: pid 1-5 = team A in role order TOP/JG/MID/ADC/SUP, 6-10 = team B
 * same order; the same-role enemy is the cross-team slot, pid +/- 5), and
 * the comparison uses FINAL-game stats.
 *
 *   @N (gold@10 / cs@10) is DEFERRED honestly: there is no per-participant
 *   timeline frame in this payload to source it from. When the route grows
 *   a per-participant @N series this panel can add a gold@10 / cs@10 row;
 *   until then it shows final stats and says so. Do NOT fabricate @N
 *   numbers from the team-aggregate diff.
 *
 * Mode-aware: SR-style modes pair lanes; ARAM / Arena have no role slots,
 * so the panel hides (fail-soft). Mounts inside the PGR view (Build tab).
 * Idempotent render.
 */
import { CHAMPS } from "../lib/items_index.js";

const MOUNT_ID = "pgr-lane-compare-mount";

// Modes with a lane-opponent pairing. Mirrors the _setPhases SR gate in
// last_match.js - the win-prob model + lane pairing both apply to SR-shape
// games only (CLASSIC / Ranked / Draft / Normal).
const _LANE_MODE_RE = /CLASSIC|SR|RANKED|DRAFT|NORMAL/i;

function _isMock() {
  return !!(document.body && document.body.dataset.uiMock === "1");
}

function _escHtml(s) {
  const div = document.createElement("div");
  div.textContent = String(s == null ? "" : s);
  return div.innerHTML;
}

function _ddragonVer() {
  return (CHAMPS && CHAMPS.version) || "16.11.1";
}

function _champKey(cid) {
  return (CHAMPS && CHAMPS.byId && CHAMPS.byId[String(cid)]) || "";
}

function _champIconTag(cid) {
  const key = _champKey(cid);
  if (!key) return '<span class="plc-champ-noimg"></span>';
  const ver = _ddragonVer();
  const local = `/data/ddragon/${ver}/img/champion/${key}.png`;
  const cdn = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/champion/${key}.png`;
  const onErr =
    `if(this.dataset.cdn){this.style.display='none';}` +
    `else{this.dataset.cdn='1';this.src='${cdn}';}`;
  return `<img class="plc-champ-icon" src="${local}" alt="${_escHtml(key)}" loading="lazy" onerror="${onErr}">`;
}

function _fmtThousands(n) {
  const v = Math.round(Number(n) || 0);
  return v.toLocaleString("en-US");
}

/** Total kills for a team_id across the roster (for KP). */
function _teamKills(roster, teamId) {
  return (roster || []).reduce(
    (acc, p) => acc + (p.team_id === teamId ? Number(p.kills) || 0 : 0),
    0,
  );
}

/** Kill participation percent for one participant against its team total. */
function _kpPct(p, roster) {
  const teamK = _teamKills(roster, p.team_id);
  if (teamK <= 0) return 0;
  const involved = (Number(p.kills) || 0) + (Number(p.assists) || 0);
  return Math.round((involved / teamK) * 100);
}

/**
 * Pick the lane opponent for the operator via the participant-slot
 * convention. Returns the enemy participant at the same role slot, or
 * null when it cannot be resolved (no is_me / no cross-slot match).
 */
function _laneOpponent(roster) {
  const rs = roster || [];
  const me = rs.find((p) => p && p.is_me);
  if (!me) return null;
  const pid = Number(me.participant_id);
  if (!pid) return null;
  // Cross-team same-role slot: 1-5 <-> 6-10. The enemy slot is the one
  // on the OTHER team sharing the within-team index.
  const targetPid = pid <= 5 ? pid + 5 : pid - 5;
  const opp =
    rs.find((p) => Number(p.participant_id) === targetPid && p.team_id !== me.team_id) ||
    null;
  return opp;
}

/** Build one comparison row: label + two values + a split bar + delta. */
function _rowHtml(label, mineRaw, oppRaw, opts) {
  const o = opts || {};
  const mine = Number(mineRaw) || 0;
  const opp = Number(oppRaw) || 0;
  const total = mine + opp;
  const minePct = total > 0 ? (mine / total) * 100 : 50;
  const oppPct = 100 - minePct;
  const fmt = o.thousands ? _fmtThousands : (n) => String(Math.round(n));
  const delta = mine - opp;
  const lead = delta > 0 ? "ahead" : delta < 0 ? "behind" : "even";
  const suffix = o.suffix || "";
  const deltaStr =
    delta === 0
      ? "even"
      : (delta > 0 ? "+" : "") + fmt(delta) + suffix;
  return (
    `<div class="plc-row" data-lead="${lead}">` +
    `<span class="plc-row-label">${_escHtml(label)}</span>` +
    `<div class="plc-row-body">` +
    `<span class="plc-val plc-val-mine">${_escHtml(fmt(mine) + suffix)}</span>` +
    `<div class="plc-bar">` +
    `<span class="plc-bar-mine" style="width:${minePct.toFixed(1)}%"></span>` +
    `<span class="plc-bar-opp" style="width:${oppPct.toFixed(1)}%"></span>` +
    `</div>` +
    `<span class="plc-val plc-val-opp">${_escHtml(fmt(opp) + suffix)}</span>` +
    `</div>` +
    `<span class="plc-delta plc-${lead}">${_escHtml(deltaStr)}</span>` +
    `</div>`
  );
}

/** Build the full card markup for a resolved (me, opponent) pair. */
function _cardHtml(me, opp, roster) {
  const myKda = `${me.kills}/${me.deaths}/${me.assists}`;
  const opKda = `${opp.kills}/${opp.deaths}/${opp.assists}`;
  const myKp = _kpPct(me, roster);
  const opKp = _kpPct(opp, roster);
  const rows =
    _rowHtml("Gold", me.gold, opp.gold, { thousands: true }) +
    _rowHtml("CS", me.cs, opp.cs, {}) +
    _rowHtml("Damage", me.damage_to_champs, opp.damage_to_champs, { thousands: true }) +
    _rowHtml("Kill part.", myKp, opKp, { suffix: "%" });
  return (
    `<div class="plc-card">` +
    `<div class="plc-head">` +
    `<span class="plc-title">LANE MATCHUP</span>` +
    `<span class="plc-sub">you vs your role opponent . final stats (gold@10 / cs@10 deferred - no per-player timeline)</span>` +
    `</div>` +
    `<div class="plc-vs">` +
    `<div class="plc-side plc-side-mine">` +
    _champIconTag(me.champion_id) +
    `<span class="plc-name">${_escHtml(me.game_name || "You")}</span>` +
    `<span class="plc-kda">${_escHtml(myKda)}</span>` +
    `</div>` +
    `<span class="plc-vs-sep">vs</span>` +
    `<div class="plc-side plc-side-opp">` +
    _champIconTag(opp.champion_id) +
    `<span class="plc-name">${_escHtml(opp.game_name || "Opponent")}</span>` +
    `<span class="plc-kda">${_escHtml(opKda)}</span>` +
    `</div>` +
    `</div>` +
    `<div class="plc-rows">${rows}</div>` +
    `</div>`
  );
}

/**
 * Render the lane comparison from the /api/last-match payload. Idempotent.
 * Hides for non-SR modes (no lane pairing) or when the opponent slot
 * cannot be resolved (missing roster / no is_me).
 */
export function renderPgrLaneCompare(data) {
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  const draw = (payload) => {
    try {
      if (!payload || !payload.found || !payload.match) {
        mount.innerHTML = "";
        mount.hidden = true;
        return;
      }
      const m = payload.match;
      const mode = m.mode || "";
      // Mode gate: only SR-shape modes pair lanes.
      if (mode && !_LANE_MODE_RE.test(mode)) {
        mount.innerHTML = "";
        mount.hidden = true;
        return;
      }
      const enriched = m.enriched || {};
      const roster = enriched.roster || [];
      const me = roster.find((p) => p && p.is_me);
      const opp = _laneOpponent(roster);
      if (!me || !opp) {
        mount.innerHTML = "";
        mount.hidden = true;
        return;
      }
      const html = _cardHtml(me, opp, roster);
      mount.innerHTML = html;
      mount.hidden = !html;
    } catch (_e) {
      mount.innerHTML = "";
      mount.hidden = true;
    }
  };
  // Under ?ui_mock=1 the audit capture renders the local fixture so the
  // panel stands even when the live last-match is ARAM/Arena (no lanes).
  if (_isMock()) {
    fetch("/data/ui_mock/pgr_lane_compare.json", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((mock) => draw(mock || data))
      .catch(() => draw(data));
    return;
  }
  draw(data);
}

// --- test hooks -----------------------------------------------------
export const __test = {
  _laneOpponent,
  _teamKills,
  _kpPct,
  _rowHtml,
  _cardHtml,
  _fmtThousands,
  _LANE_MODE_RE,
};
