// Map State panel - minimap canvas, game clock, spell CDs, gold diff,
// objective countdowns.
import { el, safe, fmtList, _formatRelativeAge } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { CHAMPS, SPELLS, _resolveChampId, _resolveSpell } from '../lib/items_index.js';

// State slots initialised here (map_state owns the clock + spell tracking).
state.gameClock = { startedAt: 0, anchorS: 0, raw: "" };
state.spellCds = {};

const MM = {
  root: el("minimap"),
  status: el("mm-state"),
  staleness: document.querySelector('.staleness[data-for="minimap"]'),
  dragon: el("mm-dragon"),
  baron: el("mm-baron"),
  herald: el("mm-herald"),
  towers: el("mm-towers"),
  score: el("mm-score"),
  gameTime: el("mm-gametime"),
  imgWrap: el("mm-img-wrap"),
  img: el("mm-img"),
  imgCaption: el("mm-img-caption"),
};

function _updateGameClock(p) {
  const s = (typeof p.game_time_s === "number") ? p.game_time_s : null;
  if (s != null) {
    state.gameClock.startedAt = Date.now();
    state.gameClock.anchorS = s;
    state.gameClock.raw = p.game_time || "";
    _applyGamePhase(s);
  } else if (p.game_time) {
    state.gameClock.raw = p.game_time;
  }
}
// Three phases mapped to body[data-phase] so CSS can tint subtly:
//   early  < 15:00   (calm blue)
//   mid    15-25:00  (engaged gold)
//   late   25:00+    (urgent coral)
let _lastPhase = null;
function _applyGamePhase(gtS) {
  const phase = gtS < 900 ? "early" : gtS < 1500 ? "mid" : "late";
  const strip = el("phase-strip"), marker = el("phase-marker");
  if (phase !== _lastPhase) {
    _lastPhase = phase;
    document.body.dataset.phase = phase;
    // Mark transition - briefly pulse the marker + announce via status.
    if (marker && _lastPhase) {
      marker.classList.remove("phase-transition");
      void marker.offsetWidth;
      marker.classList.add("phase-transition");
    }
  }
  if (strip && marker) {
    strip.classList.remove("hidden");
    // Match-length denominator by mode. ARAM games are much shorter.
    const typicalS = state.mode === "aram" ? 1200   // ~20min
                   : state.mode === "arena" ? 900   // ~15min per lobby avg
                   : state.mode === "tft"   ? 1800  // ~30min
                   : 2280;                          // SR ~38min
    const ratio = Math.max(0, Math.min(1, gtS / typicalS));
    marker.style.left = (ratio * 100).toFixed(1) + "%";
  }
}
function _currentGameTimeS() {
  if (!state.gameClock.startedAt) return null;
  return state.gameClock.anchorS + (Date.now() - state.gameClock.startedAt) / 1000;
}
function _fmtMMSS(s) {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60), ss = s % 60;
  return `${m}:${ss.toString().padStart(2, "0")}`;
}
// Extract "spawns MM:SS" or "next MM:SS" or "in N:SS" from objective text
// so we can surface a live countdown chip alongside the narrative state.
function _extractSpawnTime(text) {
  if (!text) return null;
  const m = String(text).match(/\b(?:spawns?|next|in)\s+(\d{1,2}):(\d{2})\b/i);
  if (!m) return null;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

// Tick every second - pull current cd from state.spellCds and update
// each header self-spell cell's display.
function _tickSpellCooldowns() {
  if (document.hidden) return;
  document.querySelectorAll(".self-spell[data-cd-key]").forEach(cell => {
    const key = cell.dataset.cdKey;
    const rem = _currentSpellCd(key);
    const label = cell.querySelector(".cd-label");
    if (rem > 0) {
      cell.classList.add("on-cd");
      if (label) label.textContent = rem >= 60 ? Math.round(rem/60) + "m" : rem;
      cell.title = (cell.title.split(" - ")[0]) + ` - ${rem}s`;
    } else {
      // If the cell was on cooldown last tick, briefly flash "ready".
      if (cell.classList.contains("on-cd")) {
        cell.classList.add("cd-ready-flash");
        setTimeout(() => cell.classList.remove("cd-ready-flash"), 1100);
      }
      cell.classList.remove("on-cd");
      if (label) label.textContent = "";
    }
  });
}
setInterval(_tickSpellCooldowns, 1000);

// Default spawn-cycle durations per objective (seconds) used as the
// progress-bar denominator. Not scientific - Riot timings shift - but
// gives a glanceable "how close are we" feel.
const _OBJ_CYCLE = {
  dragon: 300,  // 5:00 between drakes
  baron:  360,  // 6:00 respawn after take
  herald: 360,
  atakhan: 300,
};
function _kindOf(elm) {
  if (!elm || !elm.id) return null;
  if (elm.id === "mm-dragon")  return "dragon";
  if (elm.id === "mm-baron")   return "baron";
  if (elm.id === "mm-herald")  return "herald";
  if (elm.id === "mm-atakhan") return "atakhan";
  return null;
}
// Minimap canvas renderer - Zone of Influence (ZOI) + position dots.
//
// ZOI: for each pixel, compute net "pressure" = Σ ally_pressure − Σ enemy_pressure.
// Each champion contributes a compact-support "bubble" of influence - peaks
// at 1 at the champ, falls smoothly to exactly 0 at radius R. Beyond R the
// champion contributes nothing, so the DMZ (the low-|net| band) visibly
// fills gaps between bubbles and bulges where opposing bubbles press into
// each other. Positive pressure renders in my-team color, negative in
// enemy color.
//
// Pressure math (Wendland-style, quadratic compact support):
//   d² = (dist / RADIUS)²
//   contribution = (1 - d²)²   when d < R,   else 0
//   Multiple same-team champs in proximity stack (sum).
//   Opposing team subtracts.
//
// Performance: render at 80×80 then upscale to canvas intrinsic size.
// Re-runs on every state envelope (~3s in sim, whenever coach emits live).
const ZOI = (() => {
  const q = new URLSearchParams(location.search);
  const pf = (k, d) => {
    const v = parseFloat(q.get(k));
    return isNaN(v) ? d : v;
  };
  return {
    loRes: 80,
    // Each champion influences within ~0.35 of map width. Tunable.
    radius: pf("zoi-R", 0.32),
    // Small deadband around net=0 stays transparent (the "DMZ").
    deadband: pf("zoi-DB", 0.10),
    // Baseline diagonal bias - top-left to bottom-right split (SR map).
    // Blue base is bot-left, red base is top-right. Champion pressure
    // warps this default. Keep weak so ganks + split-push still read.
    baselineStrength: pf("zoi-BL", 0.55),
  };
})();
// Phase-aware radius - early game champs are lane-contained, late game
// they rotate freely. Called with game_time_s from the state envelope.
function _zoiRadius(gtS) {
  if (typeof gtS !== "number") return ZOI.radius;
  if (gtS < 600)  return 0.22;   // <10:00 - tight lanes
  if (gtS < 1200) return 0.28;   // 10-20 - grouping phase
  if (gtS < 1800) return 0.34;   // 20-30 - rotations
  return 0.40;                    // 30+ - pure teamfight / split
}
// Compact-support influence bubble. d2 is (dist/R)² - already normalized
// by the caller. Outside the bubble (d2 >= 1) the champion contributes
// nothing, so the DMZ forms naturally in gaps and is pushed/pulled by
// wherever bubbles actually reach.
function _bubbleKernel(d2) {
  if (d2 >= 1) return 0;
  const t = 1 - d2;
  return t * t;
}

function _drawZoi(ctx, W, H, allies, enemies, myTeam, gtS) {
  const lo = ZOI.loRes;
  const off = document.createElement("canvas");
  off.width = lo; off.height = lo;
  const offCtx = off.getContext("2d");
  const img = offCtx.createImageData(lo, lo);
  const myIsRed = myTeam === "red";
  // Team color RGB.
  const myRGB    = myIsRed ? [240, 126, 139] : [138, 140, 240];   // coral vs lavender
  const enemyRGB = myIsRed ? [138, 140, 240] : [240, 126, 139];
  // Keep weights flat but summable. Radius in normalized units -
  // scales with game phase so late-game teamfights read wider.
  const R = _zoiRadius(gtS);
  const DB = ZOI.deadband;

  // Pre-flatten position arrays for tight inner loop.
  const A = Object.values(allies || {}).filter(Boolean);
  const E = Object.values(enemies || {}).filter(Boolean);

  // Baseline diagonal bias: SR blue base = bottom-left, red = top-right.
  // Diagonal from top-left (0,0) to bottom-right (1,1) is the neutral
  // line. For blue team, positive baseline on points BELOW the diagonal
  // (y > x). For red team, invert. Champion contributions add/subtract
  // from this, producing a warped curve.
  const BL = ZOI.baselineStrength;
  const baselineSign = myIsRed ? -1 : 1;
  // First pass: compute net-pressure at each low-res pixel into a temp
  // Float32 buffer so pass 2 can emit color with edge-line highlight.
  const netBuf = new Float32Array(lo * lo);
  for (let py = 0; py < lo; py++) {
    const ny = (py + 0.5) / lo;
    for (let px = 0; px < lo; px++) {
      const nx = (px + 0.5) / lo;
      // Baseline: (ny - nx) ∈ [-1, 1]; times sign+strength.
      let baseline = (ny - nx) * BL * baselineSign;
      let allyP = 0, enemyP = 0;
      for (let i = 0; i < A.length; i++) {
        const dx = nx - A[i].x, dy = ny - A[i].y;
        const d2 = (dx*dx + dy*dy) / (R*R);
        if (d2 < 1) { const t = 1 - d2; allyP += t * t; }
      }
      for (let i = 0; i < E.length; i++) {
        const dx = nx - E[i].x, dy = ny - E[i].y;
        const d2 = (dx*dx + dy*dy) / (R*R);
        if (d2 < 1) { const t = 1 - d2; enemyP += t * t; }
      }
      netBuf[py * lo + px] = baseline + allyP - enemyP;
    }
  }
  // Second pass: color + boundary line (edge where sign flips).
  for (let py = 0; py < lo; py++) {
    for (let px = 0; px < lo; px++) {
      const idx = py * lo + px;
      const net = netBuf[idx];
      const mag = Math.abs(net);
      // Detect sign-change neighbors for the boundary-line hint.
      let edge = false;
      if (mag < DB * 2) {
        const s = Math.sign(net);
        if (px+1 < lo && Math.sign(netBuf[idx+1]) !== s) edge = true;
        else if (py+1 < lo && Math.sign(netBuf[idx+lo]) !== s) edge = true;
      }
      let r, g, b, a;
      // Smooth exponential ramp: light pressure = subtle tint, heavy
      // concentration (3+ champs stacked) = near-cap saturation.
      // Scale chosen so 1 champion at influence radius ≈ half-cap.
      // Opacity caps tuned for SR underlay - 0.42/0.22 lets the map
      // read through the tint while still clearly team-coded.
      if (net > DB) {
        r = myRGB[0]; g = myRGB[1]; b = myRGB[2];
        a = 0.42 * (1 - Math.exp(-(mag - DB) / 0.7));
      } else if (net < -DB) {
        r = enemyRGB[0]; g = enemyRGB[1]; b = enemyRGB[2];
        a = 0.22 * (1 - Math.exp(-(mag - DB) / 0.7));
      } else {
        r = g = b = 0; a = 0;
      }
      if (edge) {
        // Boundary line between ally/enemy pressure - a soft gold stripe
        // that reads against both tinted zones without blend-mode tricks.
        r = 245; g = 184; b = 124; a = 0.75;
      }
      const p = idx * 4;
      img.data[p]   = r;
      img.data[p+1] = g;
      img.data[p+2] = b;
      img.data[p+3] = Math.round(a * 255);
    }
  }
  offCtx.putImageData(img, 0, 0);
  // Upscale with soft interpolation - looks like a gradient, not pixels.
  ctx.clearRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(off, 0, 0, W, H);
}

function renderMinimapCanvases(p) {
  const stack = el("mm-canvas-stack");
  const zoiCanvas = el("mm-zoi-canvas");
  const posCanvas = el("mm-pos-canvas");
  if (!stack || !posCanvas || !zoiCanvas) return;
  if (!p.positions || (!p.positions.allies && !p.positions.enemies)) {
    stack.classList.add("hidden");
    return;
  }
  stack.classList.remove("hidden");
  // Skip the 64k-pixel math + paint when the tab is not visible.
  // Latest state is still captured; next visibilitychange will redraw.
  if (document.hidden) {
    state.pendingZoi = p;
    return;
  }
  const myTeam = (p.my_team || "blue").toLowerCase();
  document.body.dataset.myteam = myTeam;
  const myColor = myTeam === "red" ? "#F07E8B" : "#8A8CF0";
  const enemyColor = myTeam === "red" ? "#8A8CF0" : "#F07E8B";

  // Drop positions for dead champions - they're not exerting pressure.
  // *_respawns keys → remaining seconds; >0 = dead, skip contribution.
  const deadE = new Set(Object.entries(p.enemy_respawns || {})
      .filter(([, s]) => typeof s === "number" && s > 0)
      .map(([n]) => n));
  const deadA = new Set(Object.entries(p.ally_respawns || {})
      .filter(([, s]) => typeof s === "number" && s > 0)
      .map(([n]) => n));
  const allies = Object.fromEntries(
    Object.entries(p.positions.allies || {}).filter(([n]) => !deadA.has(n)));
  const enemies = Object.fromEntries(
    Object.entries(p.positions.enemies || {}).filter(([n]) => !deadE.has(n)));

  // Paint ZOI layer first, dots on top.
  const zctx = zoiCanvas.getContext("2d");
  _drawZoi(zctx, zoiCanvas.width, zoiCanvas.height, allies, enemies, myTeam, p.game_time_s);

  const ctx = posCanvas.getContext("2d");
  const W = posCanvas.width, H = posCanvas.height;
  ctx.clearRect(0, 0, W, H);
  // Objective spawn markers - approximate SR positions. Draws a small
  // translucent icon glyph so the user has map landmarks without the
  // live PNG. ARAM doesn't have these; skip if mode differs.
  if (state.mode === "sr") {
    const marks = [
      { x: 0.68, y: 0.70, label: "D", color: "rgba(240,126,139,0.55)" },  // Dragon - bot-right river
      { x: 0.32, y: 0.30, label: "B", color: "rgba(192,139,150,0.55)" },  // Baron - top-left river
      { x: 0.32, y: 0.30, label: "H", color: "rgba(245,184,124,0.45)", offset: true },  // Herald - same pit pre-20
    ];
    ctx.save();
    ctx.font = "bold 11px Lato, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const m of marks) {
      const cx = Math.round(m.x * W), cy = Math.round(m.y * H) + (m.offset ? 16 : 0);
      ctx.fillStyle = "rgba(23,24,33,0.5)";
      ctx.beginPath();
      ctx.arc(cx, cy, 9, 0, Math.PI*2);
      ctx.fill();
      ctx.fillStyle = m.color;
      ctx.fillText(m.label, cx, cy);
    }
    ctx.restore();
  }
  function drawDot(x, y, color, isSelf) {
    const cx = Math.round(x * W), cy = Math.round(y * H);
    if (isSelf) {
      // Champion sight-range halo - ~1200 units on a 15000-unit SR map
      // ≈ 0.08 normalized. Thin gold stroke + soft glow. Gives the user
      // a "what can I actually see" read without flipping to the minimap.
      const vR = 0.085 * W;
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, vR, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(245,184,124,0.55)";
      ctx.lineWidth = 1.5;
      ctx.shadowColor = "rgba(245,184,124,0.5)";
      ctx.shadowBlur = 8;
      ctx.stroke();
      ctx.restore();
    }
    ctx.beginPath();
    ctx.arc(cx, cy, isSelf ? 8 : 6, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    if (isSelf) {
      ctx.strokeStyle = "#F5B87C";
      ctx.lineWidth = 2.5;
      ctx.stroke();
      // "YOU" label above the dot (or below if too close to top).
      ctx.font = "bold 13px Lato, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const labelY = cy < 30 ? cy + 20 : cy - 18;
      const inDeep = document.body.dataset.zone === "deep";
      const labelBg = inDeep ? "rgba(74,42,49,0.95)" : "rgba(23,24,33,0.9)";
      const labelFg = inDeep ? "#F07E8B" : "#F5B87C";
      // Rounded backing when available (Chromium 99+), else fallback rect.
      if (ctx.roundRect) {
        ctx.fillStyle = labelBg;
        ctx.beginPath();
        ctx.roundRect(cx - 20, labelY - 9, 40, 18, 6);
        ctx.fill();
        ctx.strokeStyle = labelFg;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(cx - 20, labelY - 9, 40, 18, 6);
        ctx.stroke();
      } else {
        ctx.fillStyle = labelBg;
        ctx.fillRect(cx - 20, labelY - 9, 40, 18);
      }
      ctx.fillStyle = labelFg;
      ctx.fillText("YOU", cx, labelY);
    } else {
      ctx.strokeStyle = "rgba(0,0,0,0.65)";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }
  const selfKey = String(p.champion || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  let selfPos = null;
  for (const name of Object.keys(allies)) {
    const pos = allies[name]; if (!pos) continue;
    const isSelf = String(name).toLowerCase().replace(/[^a-z0-9]/g, "") === selfKey;
    if (isSelf) selfPos = pos;
    drawDot(pos.x, pos.y, myColor, isSelf);
  }
  // Compute pressure at user's position to surface a "zone" chip.
  if (selfPos) {
    const myIsRed = myTeam === "red";
    const baselineSign = myIsRed ? -1 : 1;
    let netAtSelf = (selfPos.y - selfPos.x) * ZOI.baselineStrength * baselineSign;
    const _R = _zoiRadius(p.game_time_s);
    for (const key of Object.keys(allies)) {
      const q = allies[key]; if (!q || key.toLowerCase().replace(/[^a-z0-9]/g,"") === selfKey) continue;
      const dx = selfPos.x - q.x, dy = selfPos.y - q.y;
      const d2 = (dx*dx + dy*dy) / (_R * _R);
      netAtSelf += _bubbleKernel(d2);
    }
    for (const key of Object.keys(enemies)) {
      const q = enemies[key]; if (!q) continue;
      const dx = selfPos.x - q.x, dy = selfPos.y - q.y;
      const d2 = (dx*dx + dy*dy) / (_R * _R);
      netAtSelf -= _bubbleKernel(d2);
    }
    // ?debug=1 - show ZOI pressure readouts under the legend.
    if (/[?&]debug=1/.test(location.search)) {
      const dbg = el("zoi-debug");
      if (dbg) {
        dbg.classList.remove("hidden");
        dbg.textContent =
          `R=${_zoiRadius(p.game_time_s).toFixed(2)} · baseline ${ZOI.baselineStrength}` +
          ` · deadband ${ZOI.deadband} · self-pressure ${netAtSelf.toFixed(2)}`;
      }
    }
    const zonePill = el("zone-pill"), zoneLabel = el("zone-label");
    if (zonePill && zoneLabel) {
      zonePill.classList.remove("hidden");
      if (netAtSelf < -ZOI.deadband) {
        // Deep-enemy-territory escalation: < -3*DB is the "you are
        // clearly deeper than just adjacent to enemy influence" bar.
        // Empirically: sr_gank_scenario (3 enemies stacked, 1 isolated ally)
        // clears the bar; teamfight (5v5) does NOT.
        const deep = netAtSelf < -ZOI.deadband * 3;
        zoneLabel.textContent = deep ? "⛔ DEEP ENEMY" : "⚠ ENEMY ZONE";
        zonePill.className = "zone-pill zone-enemy" + (deep ? " zone-deep" : "");
        document.body.dataset.zone = deep ? "deep" : "enemy";
      } else if (netAtSelf > ZOI.deadband) {
        zoneLabel.textContent = "✓ SAFE";
        zonePill.className = "zone-pill zone-safe";
        document.body.dataset.zone = "safe";
      } else {
        zoneLabel.textContent = "- DMZ";
        zonePill.className = "zone-pill zone-dmz";
        document.body.dataset.zone = "dmz";
      }
    }
  } else {
    delete document.body.dataset.zone;
    const zonePill = el("zone-pill");
    if (zonePill) zonePill.classList.add("hidden");
  }
  // Ghost-marker bookkeeping (2026-04-26 user request): when an enemy
  // dot hasn't moved in a few seconds, fade it and ring it with a
  // clock-face age sweep so the user can read at-a-glance "this enemy
  // is roaming / missing, not actually here." Positions are floats
  // 0-1; we treat <0.005 movement (≈3.6px on the 720-canvas) as
  // "stationary." Entries are dropped when the enemy leaves the frame.
  state.lastEnemyPos ||= {};
  for (const k of Object.keys(state.lastEnemyPos)) {
    if (!(k in enemies)) delete state.lastEnemyPos[k];
  }
  const _ghostNow   = Date.now();
  const _ghostStart = 4000;   // ms before fade begins
  const _ghostEnd   = 12000;  // ms after which dot is hidden entirely
  for (const name of Object.keys(enemies)) {
    const pos = enemies[name]; if (!pos) continue;
    const prev = state.lastEnemyPos[name];
    const dx = prev ? Math.abs(pos.x - prev.x) : 1;
    const dy = prev ? Math.abs(pos.y - prev.y) : 1;
    if (!prev || dx > 0.005 || dy > 0.005) {
      state.lastEnemyPos[name] = { x: pos.x, y: pos.y, t: _ghostNow };
    }
    const age = _ghostNow - state.lastEnemyPos[name].t;
    if (age >= _ghostEnd) continue;  // too stale to draw
    if (age > _ghostStart) {
      const fadeT = (age - _ghostStart) / (_ghostEnd - _ghostStart);
      ctx.save();
      ctx.globalAlpha = 1 - fadeT * 0.7;  // 1.0 → 0.3
      drawDot(pos.x, pos.y, enemyColor, false);
      const cx = Math.round(pos.x * W), cy = Math.round(pos.y * H);
      ctx.beginPath();
      ctx.arc(cx, cy, 11, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * fadeT);
      ctx.strokeStyle = enemyColor;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.restore();
    } else {
      drawDot(pos.x, pos.y, enemyColor, false);
    }
  }
}

function renderGoldDiff(p) {
  const wrap = el("gold-diff");
  const fill = el("gold-diff-fill");
  const lbl = el("gold-diff-val");
  if (!wrap || !fill || !lbl) return;
  const diff = typeof p.team_gold_diff === "number" ? p.team_gold_diff : null;
  if (diff == null) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  // Clamp to ±10k for the fill bar scale.
  const clamp = Math.max(-10000, Math.min(10000, diff));
  const pct = Math.abs(clamp) / 10000;
  // Left edge is 50% (center). Fill extends right (ahead) or left (behind).
  if (clamp >= 0) {
    fill.style.left = "50%";
    fill.style.right = `${50 - pct * 50}%`;
    fill.classList.remove("behind");
    fill.classList.add("ahead");
  } else {
    fill.style.right = "50%";
    fill.style.left = `${50 - pct * 50}%`;
    fill.classList.remove("ahead");
    fill.classList.add("behind");
  }
  const signed = clamp >= 0 ? `+${clamp.toLocaleString()}` : clamp.toLocaleString();
  lbl.textContent = signed;
  lbl.className = clamp >= 0 ? "gd-ahead" : "gd-behind";
}

function _tickObjectiveCountdowns() {
  const nowS = _currentGameTimeS();
  for (const elm of [MM.dragon, MM.baron, MM.herald]) {
    if (!elm) continue;
    const raw = elm.dataset.raw || "-";
    if (nowS == null) { elm.textContent = raw; continue; }
    const target = _extractSpawnTime(raw);
    // Find (or lazy-create) the tick progress bar on the containing .kv row.
    const row = elm.closest(".kv");
    let bar = row && row.querySelector(".obj-bar");
    if (row && !bar) {
      bar = document.createElement("i");
      bar.className = "obj-bar";
      row.appendChild(bar);
    }
    if (target == null) {
      elm.textContent = raw;
      if (bar) bar.style.setProperty("--pct", "0%");
      continue;
    }
    const remaining = target - nowS;
    const cycle = _OBJ_CYCLE[_kindOf(elm)] || 300;
    // Ratio of progress toward spawn (0 = just went down, 1 = up now).
    const progress = Math.max(0, Math.min(1, 1 - (remaining / cycle)));
    if (bar) bar.style.setProperty("--pct", (progress * 100).toFixed(1) + "%");
    if (remaining <= 0) {
      elm.textContent = raw.replace(/\b(?:spawns?|next|in)\s+\d{1,2}:\d{2}\b/i, "UP NOW");
      elm.classList.add("obj-up");
      if (bar) bar.classList.add("full");
    } else {
      elm.textContent = raw.replace(
        /\b(?:spawns?|next|in)\s+\d{1,2}:\d{2}\b/i,
        `in ${_fmtMMSS(remaining)}`
      );
      elm.classList.toggle("obj-soon", remaining < 45);
      elm.classList.remove("obj-up");
      if (bar) bar.classList.remove("full");
    }
  }
}
// Tick every 1s - objective countdowns are the primary live pulse.
// Skip work entirely when the tab is hidden (iPad battery / CPU).
setInterval(() => {
  if (document.hidden) return;
  _tickObjectiveCountdowns();
  const s = _currentGameTimeS();
  if (s != null) {
    const str = _fmtMMSS(s);
    if (MM.gameTime) MM.gameTime.textContent = str;
  }
}, 1000);

function renderMinimap(p) {
  _updateGameClock(p);
  // Coaching-JSON fields surface objective state when the coach has
  // computed it. When absent, keep the placeholder. Fields queried:
  //   p.dragon_state / p.dragon_stack / p.soul - if the coach computed them
  //   p.baron_alive / p.baron_timer
  //   p.herald_alive / p.atakhan_state
  //   p.my_tower_hp / p.enemy_tower_hp (ARAM) or towers_us/towers_them (SR)
  //   p.kda_aggregate (team score)
  //   p.game_time / p.game_time_s
  // Store the raw state text in data-raw so the countdown tick can
  // re-render from it without a fresh state envelope.
  // Strip "(Cloud taken 12:04)" / "(Chemtech taken 8:30)" style parentheticals
  // - the kill count + next-spawn line already convey the important bits;
  // the parenthetical just eats horizontal space.
  const _cleanObj = s => String(s || "-")
    .replace(/\s*\([^)]*taken[^)]*\)\s*/gi, " ")
    .replace(/  +/g, " ")
    .trim() || "-";
  for (const [elm, val] of [
    [MM.dragon,  _cleanObj(p.dragon_state  || p.dragon)],
    [MM.baron,   _cleanObj(p.baron_state   || p.baron)],
    [MM.herald,  _cleanObj(p.herald_state  || p.herald)],
  ]) {
    if (elm) elm.dataset.raw = val;
  }
  _tickObjectiveCountdowns();
  // Keep self-spell CDs current - feeds the header summoner-spell pill.
  _snapshotSpells(p.ally_spells);
  _tickSpellCooldowns();
  renderGoldDiff(p);
  renderMinimapCanvases(p);
  // Tower count / team kills / game time chips were removed from the
  // Map State panel 2026-04-23 - those signals live on the header row 2.
  // Guarded writes so the removal doesn't require touching MM init.
  if (MM.towers) {
    const tUs = p.towers_us ?? p.my_tower_hp;
    const tThem = p.towers_them ?? p.enemy_tower_hp;
    MM.towers.textContent = (tUs != null && tThem != null) ? `${tUs} / ${tThem}` : "-";
  }
  if (MM.score) MM.score.textContent = p.score || p.team_score || p.kda_aggregate || "-";
  if (MM.gameTime) {
    MM.gameTime.textContent = (typeof p.game_time_s === "number")
      ? _fmtMMSS(p.game_time_s) : (p.game_time || "-");
  }

  // Live marker when we have ANY real datum; otherwise scaffold.
  const hasAny = !!(p.dragon_state || p.baron_state || p.herald_state
                   || p.atakhan_state || p.my_tower_hp != null
                   || p.towers_us != null || p.game_time);
  MM.status.className = "minimap-state" + (hasAny ? " live" : "");
  // Dynamic status line - more actionable than the old dev-y scaffold text.
  // 2026-04-26: hide the pill entirely when we have liveclient AND the
  // minimap image is showing - the live cropped minimap is the primary
  // signal; "waiting on positions" is just noise that overlaps the map
  // visually. Only show the pill when there's something useful to say
  // (ZOI populated) or no data at all (offline state).
  // Shared-vision modes (ARAM/KIWI per core/vision_tracker._SHARED_VISION_MODES)
  // have no Live Client positions - refreshVisionOverlay populates this
  // pill from /api/vision-state.summary instead. Don't clobber its text.
  const sharedVision = state.mode === "aram";
  if (sharedVision) {
    if (!hasAny) {
      MM.status.textContent = "awaiting liveclient data…";
      MM.status.classList.remove("hidden");
    }
    // else: leave whatever the vision-overlay tick last wrote (or empty
    // until its 500ms tick populates).
  } else if (hasAny) {
    // Mode swap can leave a stale shared-vision signature on the pill;
    // clear so re-entering shared-vision later forces a fresh render.
    delete MM.status._sharedSig;
    const allyCount = p.positions?.allies ? Object.keys(p.positions.allies).length : 0;
    const enemyCount = p.positions?.enemies ? Object.keys(p.positions.enemies).length : 0;
    if (allyCount || enemyCount) {
      _renderMmStateLine(MM.status, `${allyCount} ally · ${enemyCount} enemy`);
      MM.status.classList.remove("hidden");
    } else {
      // Liveclient up but no positions yet - hide the pill so it
      // doesn't sit on top of the minimap image.
      MM.status.textContent = "";
      MM.status.classList.add("hidden");
    }
  } else {
    MM.status.textContent = "awaiting liveclient data…";
    MM.status.classList.remove("hidden");
  }
  state.lastTouch.minimap = Date.now() / 1000;
}

// Heartbeat-styled live state line. Builds a ♥-pulse + counts +
// self-aging "Xs ago" suffix so the user reads "this is live" without
// having to compare numbers across renders. The pulse re-fires every
// call by removing then re-adding the .pulse class on the next frame.
// The age suffix is auto-updated by a 1s setInterval (registered once).
function _renderMmStateLine(host, countText) {
  if (!host) return;
  if (!host._wired) {
    host._wired = true;
    host.innerHTML = '<span class="mm-heart" aria-hidden="true"></span>'
      + '<span class="mm-counts">- · -</span>'
      + '<span class="mm-age">0s ago</span>';
    // Single global timer; re-uses host._lastT as the source of truth.
    setInterval(() => {
      const ageEl = host.querySelector(".mm-age");
      if (!ageEl || !host._lastT) return;
      const dt = Math.max(0, Math.round((Date.now() - host._lastT) / 1000));
      ageEl.textContent = dt + "s ago";
      // Fade the heartbeat as data goes stale (>15s = no live signal).
      const heart = host.querySelector(".mm-heart");
      if (heart) heart.style.opacity = dt > 15 ? "0.18" : (dt > 5 ? "0.4" : "");
    }, 1000);
  }
  host._lastT = Date.now();
  const counts = host.querySelector(".mm-counts");
  if (counts) counts.textContent = countText;
  const age = host.querySelector(".mm-age");
  if (age) age.textContent = "0s ago";
  const heart = host.querySelector(".mm-heart");
  if (heart) {
    heart.style.opacity = "";
    heart.classList.remove("pulse");
    // Force reflow so the next addClass restarts the animation.
    void heart.offsetWidth;
    heart.classList.add("pulse");
  }
}

// Lightweight ephemeral burst above the KDA pill - kill/assist/death
// surfaces briefly then fades. One-shot DOM elements so overlaps

// Live spell-cooldown state. Each key is champion|spell, value is
// {remaining: seconds, anchor: Date.now()}. On state re-emit we
// snapshot, on tick we recompute visible remaining time.
state.spellCds = {};
function _spellKey(champ, spell) {
  return (champ || "") + "|" + (spell || "");
}
function _snapshotSpells(spellsMap) {
  // Merge fresh spell cooldowns from the state payload.
  // Only overwrite when the incoming timer is meaningfully different
  // to avoid resetting a smooth tick on every 3s re-emit.
  const now = Date.now();
  for (const champ of Object.keys(spellsMap || {})) {
    const slots = spellsMap[champ] || [];
    slots.forEach(s => {
      if (typeof s !== "object" || !s.spell) return;
      const key = _spellKey(champ, s.spell);
      const incoming = typeof s.cd_remaining_s === "number" ? s.cd_remaining_s : 0;
      const prev = state.spellCds[key];
      if (!prev || Math.abs(prev.remaining - _currentSpellCd(key)) > 2) {
        state.spellCds[key] = { remaining: incoming, anchor: now };
      }
    });
  }
}
function _currentSpellCd(key) {
  const rec = state.spellCds[key];
  if (!rec) return 0;
  const elapsed = (Date.now() - rec.anchor) / 1000;
  return Math.max(0, Math.round(rec.remaining - elapsed));
}


export {
  MM,
  renderMinimap,
  _tickSpellCooldowns, _tickObjectiveCountdowns,
  _updateGameClock, _applyGamePhase,
  _snapshotSpells, _fmtMMSS, _renderMmStateLine,
};
