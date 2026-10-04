/* RM-641 (directive X-41, ADR-016): S5 Replay video lane.
 *
 * Thin DOM layer over review_player_model.js (all logic lives there and is
 * node-tested). Shows the local OBS recording of the selected match when an
 * RM-637 sidecar names one, with:
 *   - a marker lane from the sidecar bookmarks (origin-anchored clusters,
 *     priority-table icon), rendered ONCE per match and then only
 *     class-toggled as the playhead moves (no innerHTML repaint, so a
 *     focused marker keeps focus);
 *   - a second lane of PGR cost moments from /api/post-game-wpa (the
 *     tracked team's biggest win-probability drops), mapped onto video time
 *     through the sidecar's game_time_offset_s;
 *   - typing-aware hotkeys: [ ] marker, d / D death, Space play/pause,
 *     ctrl/alt/meta+Space from inside a field, Escape hands focus back.
 * Opens at the aligned game start minus 2 s; the file is never trimmed.
 *
 * Hidden entirely when there is no sidecar or no servable video
 * (GET /api/recordings/<id> -> has_video false or 404).
 *
 * Sources: GET /api/recordings/<id> and /api/recordings/<id>/video
 * (dashboard/routes_recordings.py), GET /api/post-game-wpa?match_id=<id>
 * (dashboard/routes_post_game_wpa.py).
 * Behaviour observed in external reference E; re-implemented clean-room.
 */

import {
  clusterMarkers, markersFromSidecar, openTimeS, videoTimeFor,
  hotkeyAction, seekTarget, costMoments,
} from './review_player_model.js';

const _RP = {
  matchId: null,      // id the current load was issued for
  sidecar: null,
  markers: [],
  deaths: [],
  renderedKey: null,  // signature of the marker lane currently in the DOM
  costKey: null,
  cost: null,         // [{game_time, cost, type}] or null until fetched
  trackedTeam: null,
  wired: false,
  seq: 0,
};

function _el(id) { return document.getElementById(id); }

function _clock(s) {
  const n = Math.max(0, Math.floor(Number(s) || 0));
  return String(Math.floor(n / 60)).padStart(2, "0") + ":" + String(n % 60).padStart(2, "0");
}

function _hide() {
  const sec = _el("replay-video-section");
  if (sec) sec.hidden = true;
  const v = _el("replay-video");
  if (v && v.getAttribute("src")) {
    try { v.pause(); } catch (_) {}
    v.removeAttribute("src");
    try { v.load(); } catch (_) {}
  }
}

function _visible() {
  const sec = _el("replay-video-section");
  const view = _el("view-replay");
  return !!(sec && !sec.hidden && view && !view.hidden);
}

function _describe(el) {
  if (!el) return null;
  return {
    tag: el.tagName,
    type: el.getAttribute ? el.getAttribute("type") : null,
    editable: !!el.isContentEditable,
    marker: !!(el.classList && el.classList.contains("replay-video-marker")),
  };
}

function _markerButton(cluster, kind) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "replay-video-marker";
  b.dataset.icon = cluster.icon || kind;
  b.dataset.t = String(cluster.t);
  b.style.left = "0%";
  const names = cluster.members.map((m) => m.label || m.name || "event");
  const label = `${_clock(cluster.t)} ${names.join(", ")}`;
  b.title = label;
  b.setAttribute("aria-label", label);
  b.textContent = cluster.members.length > 1 ? String(cluster.members.length) : "";
  b.addEventListener("click", () => {
    const v = _el("replay-video");
    if (v) v.currentTime = cluster.t;
  });
  return b;
}

// Builds a lane's buttons once for a given signature. Positions are percent
// of the lane, so a resize needs no rebuild.
function _renderLane(laneEl, clusters, duration, kind) {
  const frag = document.createDocumentFragment();
  for (const c of clusters) {
    const b = _markerButton(c, kind);
    b.style.left = `${Math.min(100, Math.max(0, (c.t / duration) * 100))}%`;
    frag.appendChild(b);
  }
  laneEl.replaceChildren(frag);
}

function _renderMarkersOnce() {
  const v = _el("replay-video");
  const lane = _el("replay-video-lane");
  if (!v || !lane || !_RP.sidecar) return;
  const duration = Number(v.duration);
  if (!Number.isFinite(duration) || duration <= 0) return;
  const key = `${_RP.matchId}|${Math.round(duration)}`;
  if (_RP.renderedKey === key) return;
  const width = lane.clientWidth || 600;
  _renderLane(lane, clusterMarkers(_RP.markers, duration, width), duration, "event");
  _RP.renderedKey = key;
  _renderCostOnce();
}

function _renderCostOnce() {
  const v = _el("replay-video");
  const lane = _el("replay-video-cost");
  if (!v || !lane || !_RP.sidecar || !_RP.cost) return;
  const duration = Number(v.duration);
  if (!Number.isFinite(duration) || duration <= 0) return;
  const key = `${_RP.matchId}|${Math.round(duration)}|${_RP.cost.length}`;
  if (_RP.costKey === key) return;
  const off = _RP.sidecar.game_time_offset_s;
  const pts = _RP.cost.map((c) => ({
    t: videoTimeFor(c.game_time, off),
    name: "cost",
    label: `-${Math.round(c.cost * 100)}% win chance (${c.type.replace(/_/g, " ").toLowerCase()})`,
  })).filter((p) => p.t !== null);
  const clusters = clusterMarkers(pts, duration, lane.clientWidth || 600);
  for (const c of clusters) c.icon = "cost";
  _renderLane(lane, clusters, duration, "cost");
  lane.hidden = clusters.length === 0;
  _RP.costKey = key;
}

// Playhead tick: toggle classes only.
function _syncPlayhead() {
  const v = _el("replay-video");
  if (!v) return;
  const now = v.currentTime;
  for (const id of ["replay-video-lane", "replay-video-cost"]) {
    const lane = _el(id);
    if (!lane) continue;
    for (const b of lane.children) {
      const t = Number(b.dataset.t);
      b.classList.toggle("is-past", t <= now);
    }
  }
}

function _onKeydown(ev) {
  if (!_visible()) return;
  const target = _describe(document.activeElement);
  if (target && target.tag === "VIDEO") return;  // native controls own it
  const action = hotkeyAction({
    key: ev.key, ctrlKey: ev.ctrlKey, altKey: ev.altKey, metaKey: ev.metaKey,
    shiftKey: ev.shiftKey, target,
  });
  if (!action) return;
  const v = _el("replay-video");
  if (!v) return;
  if (action.type === "release-focus") {
    const sec = _el("replay-video-section");
    if (document.activeElement && document.activeElement !== sec) {
      try { document.activeElement.blur(); } catch (_) {}
    }
    if (sec) sec.focus({ preventScroll: true });
    return;
  }
  ev.preventDefault();
  if (action.type === "toggle-play") {
    if (v.paused) { const p = v.play(); if (p && p.catch) p.catch(() => {}); } else { v.pause(); }
    return;
  }
  const t = seekTarget(action, { markers: _RP.markers.map((m) => m.t),
                                 deaths: _RP.deaths, current: v.currentTime });
  if (t !== null) v.currentTime = t;
}

// A focused marker button would activate (and re-seek) on Space keyup.
function _onKeyup(ev) {
  if ((ev.key === " " || ev.key === "Spacebar") && _visible()) {
    const t = _describe(document.activeElement);
    if (t && t.marker) ev.preventDefault();
  }
}

function _wireOnce() {
  if (_RP.wired) return;
  const v = _el("replay-video");
  if (!v) return;
  _RP.wired = true;
  v.addEventListener("loadedmetadata", () => {
    const start = openTimeS(_RP.sidecar);
    if (start > 0 && start < v.duration) v.currentTime = start;
    _renderMarkersOnce();
  });
  v.addEventListener("timeupdate", _syncPlayhead);
  v.addEventListener("seeked", _syncPlayhead);
  document.addEventListener("keydown", _onKeydown);
  document.addEventListener("keyup", _onKeyup);
}

function _loadCost(matchId, seq) {
  if (_RP.trackedTeam !== 100 && _RP.trackedTeam !== 200) return;
  fetch("/api/post-game-wpa?match_id=" + encodeURIComponent(matchId))
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => {
      if (seq !== _RP.seq || !d || !Array.isArray(d.events)) return;
      _RP.cost = costMoments(d.events, _RP.trackedTeam);
      _renderCostOnce();
    })
    .catch(() => {});
}

/* Entry point, called by dev.js _replayLoadMatch once the match resolves.
 * trackedTeam: 100 / 200 for the reviewed player's side, or null. */
export function loadReviewPlayer(matchId, trackedTeam) {
  _wireOnce();
  if (matchId && matchId === _RP.matchId) {
    // Same match (dev.js calls once on click, again when the team is
    // known): keep the in-flight / loaded sidecar, only fill the cost lane.
    if (trackedTeam !== _RP.trackedTeam) {
      _RP.trackedTeam = trackedTeam;
      if (_RP.sidecar) _loadCost(matchId, _RP.seq);
    }
    return;
  }
  const seq = ++_RP.seq;
  _RP.matchId = matchId;
  _RP.sidecar = null;
  _RP.markers = [];
  _RP.deaths = [];
  _RP.cost = null;
  _RP.renderedKey = null;
  _RP.costKey = null;
  _RP.trackedTeam = trackedTeam;
  _hide();
  const lane = _el("replay-video-lane");
  if (lane) lane.replaceChildren();
  const cost = _el("replay-video-cost");
  if (cost) { cost.replaceChildren(); cost.hidden = true; }
  if (!matchId || (document.body && document.body.dataset.uiMock === "1")) return;
  fetch("/api/recordings/" + encodeURIComponent(matchId))
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => {
      if (seq !== _RP.seq || !d || !d.has_video || !d.video_url) return;
      _RP.sidecar = d;
      _RP.markers = markersFromSidecar(d);
      _RP.deaths = _RP.markers.filter((m) => m.own_death).map((m) => m.t);
      const v = _el("replay-video");
      const sec = _el("replay-video-section");
      if (!v || !sec) return;
      v.src = d.video_url;
      sec.hidden = false;
      _loadCost(matchId, seq);
    })
    .catch(() => {});
}
