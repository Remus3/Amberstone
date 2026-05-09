// Team Context panel — 5+5 champ-select enrichment row.
//
// Renders the FU02 team-context payload (mains, rank, mastery on locked,
// recent winrate) for both ally and enemy rosters during ChampSelect.
// Until `core/riot_api.py` ships the actual fan-out, every cell renders
// in skeleton mode (champion icon + name placeholder, dashes for the
// enrichment fields). The shape and DOM are stable across that
// transition — the same rows will fill in field-by-field as the
// progressive-reveal poll cadence lands payload.partial=False.
//
// Render rules:
// 1. Hidden when lcu.phase !== "ChampSelect" OR coach.team_context is null.
// 2. Idempotent (sig-on-container) — no flicker on every 500ms /api/state poll.
// 3. Ranked-queue obfuscation gate: when payload.queue_id ∈ {420, 440},
//    summoner_name field is force-blanked at the render layer regardless
//    of what the backend stored. The FU02 ticket calls this out as a
//    Riot-policy compliance requirement (loading-screen reveal only).
// 4. Soft-fail: any single empty field renders as "—" with a .skel class
//    so the user can see the row exists but the data hasn't landed.

import { CHAMPS } from '../lib/items_index.js';
import { idempotentRender, makeSig } from '../lib/idempotent_render.js';

// Queue IDs where Riot obfuscates summoner names until loading screen.
// Match-V5 docs queue list — Ranked Solo (420), Ranked Flex (440).
const _RANKED_BLANK_QUEUES = new Set([420, 440]);

function _champImg(name) {
  if (!name) return "";
  const ver = CHAMPS.version || "latest";
  return `/data/ddragon/${ver}/img/champion/${name}.png`;
}

function _renderSlot(entry, blankNames) {
  // entry: TeamContextEntry shape — see core/coaching_payload.py
  const wrap = document.createElement("div");
  wrap.className = "tc-slot";
  const champ = entry.locked_champion || "";
  const champImg = _champImg(champ);

  const icon = document.createElement("div");
  icon.className = "tc-slot-icon" + (champ ? "" : " skel");
  icon.innerHTML = champImg
    ? `<img src="${champImg}" alt="${champ}" onerror="this.style.display='none'">`
    : "?";
  wrap.appendChild(icon);

  const meta = document.createElement("div");
  meta.className = "tc-slot-meta";

  // Top line: summoner name (or champion-only when blanked) + rank chip.
  const head = document.createElement("div");
  head.className = "tc-slot-head";
  const nameEl = document.createElement("span");
  nameEl.className = "tc-slot-name";
  const showName = !blankNames && entry.summoner_name;
  nameEl.textContent = showName ? entry.summoner_name : (champ || "—");
  if (!showName) nameEl.classList.add("skel");
  head.appendChild(nameEl);

  if (entry.rank) {
    const rank = document.createElement("span");
    rank.className = "tc-slot-rank";
    rank.textContent = entry.rank;
    head.appendChild(rank);
  } else {
    const rank = document.createElement("span");
    rank.className = "tc-slot-rank skel";
    rank.textContent = "—";
    head.appendChild(rank);
  }
  meta.appendChild(head);

  // Sub line: champion (always — even when name is blanked, champion is
  // safe to show) + mastery on locked.
  const sub = document.createElement("div");
  sub.className = "tc-slot-sub";
  if (champ) {
    const c = document.createElement("span");
    c.className = "tc-slot-champ";
    c.textContent = champ;
    sub.appendChild(c);
  }
  if (entry.mastery_on_locked > 0) {
    const m = document.createElement("span");
    m.className = "tc-slot-mastery";
    // Truncate to k for compact display: 287_000 → "287k", 12_400 → "12k".
    const v = entry.mastery_on_locked;
    m.textContent = (v >= 1000 ? Math.round(v / 1000) + "k" : String(v)) + " m";
    m.title = v.toLocaleString() + " mastery points on " + (champ || "locked champ");
    sub.appendChild(m);
  }
  meta.appendChild(sub);

  // Bottom line: mains + winrate. Both skeleton until FU02 fan-out lands.
  const tail = document.createElement("div");
  tail.className = "tc-slot-tail";
  if (entry.mains && entry.mains.length) {
    const mains = document.createElement("span");
    mains.className = "tc-slot-mains";
    mains.textContent = "mains: " + entry.mains.slice(0, 3).join(", ");
    tail.appendChild(mains);
  } else {
    const mains = document.createElement("span");
    mains.className = "tc-slot-mains skel";
    mains.textContent = "mains: —";
    tail.appendChild(mains);
  }
  if (entry.win_rate_recent > 0) {
    const wr = document.createElement("span");
    wr.className = "tc-slot-wr";
    wr.textContent = Math.round(entry.win_rate_recent * 100) + "% wr";
    tail.appendChild(wr);
  }
  if (entry.w_l_streak_7
      && (entry.w_l_streak_7[0] || entry.w_l_streak_7[1])) {
    const streak = document.createElement("span");
    streak.className = "tc-slot-streak";
    streak.textContent = entry.w_l_streak_7[0] + "W " + entry.w_l_streak_7[1] + "L";
    streak.title = "Last 7 games";
    tail.appendChild(streak);
  }
  meta.appendChild(tail);

  wrap.appendChild(meta);
  return wrap;
}

function _renderTeam(containerId, entries, blankNames) {
  const host = document.getElementById(containerId);
  if (!host) return;
  host.innerHTML = "";
  const slots = (entries || []).slice(0, 5);
  // Pad to 5 placeholders so the grid stays aligned even with partial data.
  while (slots.length < 5) slots.push({});
  slots.forEach((entry) => host.appendChild(_renderSlot(entry, blankNames)));
}

function renderTeamContext(state) {
  const block = document.getElementById("cs-team-context-block");
  if (!block) return;
  // Gate 1: only during ChampSelect.
  const phase = state && state.lcu && state.lcu.phase;
  if (phase !== "ChampSelect") {
    block.hidden = true;
    return;
  }
  // Gate 2: payload present in coach.
  const tc = state && state.coach && state.coach.team_context;
  if (!tc) {
    // Render a single "waiting on enrichment…" placeholder so the user
    // knows the panel exists (FU04 screenshot evidence).
    block.hidden = false;
    block.dataset.sig = "";   // force re-render when payload lands
    const status = document.getElementById("tc-status");
    if (status) status.textContent = "waiting for enrichment…";
    const allies = document.getElementById("tc-allies");
    const enemies = document.getElementById("tc-enemies");
    if (allies && !allies._waitingPainted) {
      _renderTeam("tc-allies", [], false);
      allies._waitingPainted = true;
    }
    if (enemies && !enemies._waitingPainted) {
      _renderTeam("tc-enemies", [], false);
      enemies._waitingPainted = true;
    }
    return;
  }

  // We have a payload — clear the waiting paint flag so future renders
  // commit on every change.
  const a = document.getElementById("tc-allies");
  const e = document.getElementById("tc-enemies");
  if (a) a._waitingPainted = false;
  if (e) e._waitingPainted = false;

  block.hidden = false;
  // Sig: ensures we don't repaint on identical poll cycles. partial flag
  // included so the "partial → final" transition forces a repaint.
  const sig = makeSig(
    tc.refreshed_at, tc.partial, tc.queue_id,
    JSON.stringify(tc.allies || []),
    JSON.stringify(tc.enemies || []),
  );
  if (idempotentRender(block, sig)) return;

  const blankNames = _RANKED_BLANK_QUEUES.has(tc.queue_id | 0);
  _renderTeam("tc-allies",  tc.allies  || [], blankNames);
  _renderTeam("tc-enemies", tc.enemies || [], blankNames);

  const status = document.getElementById("tc-status");
  if (status) {
    const bits = [];
    if (tc.partial) bits.push("partial");
    else            bits.push("ready");
    if (blankNames) bits.push("ranked · names hidden");
    if (tc.queue_id) bits.push("queue " + tc.queue_id);
    status.textContent = bits.join(" · ");
  }
}

export { renderTeamContext };
