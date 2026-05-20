// CD Ledger panel module (2026-05-20).
//
// Renders the per-player summoner-spell + ultimate cooldown ledger from
// /api/state.summoner_cooldowns. The backend (core/summoner_cooldowns.py +
// dashboard/_state_cooldowns.py) computes effective cooldowns + CDR
// stacking + sorts by next-up-ascending; this module is render-only.
//
// Mount point: #cd-ledger-body inside the active_match view's am-pane-cd
// (a compact right rail next to the map pane).
//
// Wire shape (one entry per resolvable player; backend keeps order):
//   {
//     puuid: null | string,
//     summoner_name: string,
//     champion_id: int | null,        // null on Live Client path
//     side: "blue" | "red" | "",
//     summs: {
//       d_id, d_name, d_used_at_s, d_ready_at_s, d_cd_remaining_s,
//       f_id, f_name, f_used_at_s, f_ready_at_s, f_cd_remaining_s,
//     },
//     ult: { id, used_at_s, ready_at_s, cd_remaining_s }
//   }
//
// Backend drops champion_name from the row, but the Live Client path
// surfaces championName per player on ctx.liveclient.allPlayers - we
// thread it via ctx so portraits resolve. When liveclient is missing
// (fixtures / lobby), the row falls back to a champion-initial badge.
//
// Collapse state is persisted in localStorage as "cdLedgerCollapsed"
// (string "1" = collapsed). Default = expanded.

import { idempotentRender, makeSig } from '../lib/idempotent_render.js';

const _CD = {
  body:   () => document.getElementById("cd-ledger-body"),
  pane:   () => document.querySelector("#view-active-match .am-pane-cd"),
  head:   () => document.getElementById("cd-ledger-head"),
};

const _LS_COLLAPSED = "cdLedgerCollapsed";

// Build a fast champion-name lookup from ctx.liveclient.allPlayers, keyed
// by summoner_name. Returns "" for unknown summoners.
function _buildChampNameLookup(liveclient) {
  const m = new Map();
  if (!liveclient || typeof liveclient !== "object") return m;
  const all = liveclient.allPlayers;
  if (!Array.isArray(all)) return m;
  for (const pl of all) {
    if (!pl || typeof pl !== "object") continue;
    const summ = pl.summonerName || pl.riotIdGameName || "";
    if (!summ) continue;
    // Prefer rawChampionName (canonical Riot id form) over championName
    // (display name); fall back to championName for older payloads.
    const champ = pl.rawChampionName || pl.championName || "";
    if (champ) m.set(summ, champ);
  }
  return m;
}

// Round a cd seconds value for chip display: < 10s -> "Xs" with no
// decimal; >= 10s -> "Xs" rounded. READY is rendered as the literal
// string "READY" by the caller, not via this helper.
function _fmtCd(cd) {
  if (cd == null || isNaN(cd)) return "?";
  const n = Math.max(0, Math.round(+cd));
  return `${n}s`;
}

// Resolve the DDragon champion portrait URL. champName here is the
// canonical Riot id form (e.g. "Aatrox", "MissFortune"); the alphanum
// strip mirrors the existing active_match.js threat-row pattern in case
// a payload includes display-name punctuation.
function _portraitUrl(champName, version) {
  const ver = version || "16.10.1";
  const clean = String(champName || "").replace(/[^a-zA-Z0-9]/g, "");
  if (!clean) return "";
  return `/data/ddragon/${ver}/img/champion/${clean}.png`;
}

// Resolve the summoner-spell icon URL. spellId is the Riot integer id.
// We hardcode the canonical filename map here; the existing
// spells_index.json is fetched lazily by other modules but pulling it
// in here just for these 10 icons would add a network dep for no gain.
const _SPELL_IMG = {
  1:  "SummonerBoost.png",       // Cleanse
  3:  "SummonerExhaust.png",     // Exhaust
  4:  "SummonerFlash.png",       // Flash
  6:  "SummonerHaste.png",       // Ghost
  7:  "SummonerHeal.png",        // Heal
  11: "SummonerSmite.png",       // Smite
  12: "SummonerTeleport.png",    // Teleport
  13: "SummonerMana.png",        // Clarity
  14: "SummonerDot.png",         // Ignite
  21: "SummonerBarrier.png",     // Barrier
};

function _spellIconUrl(spellId, version) {
  if (spellId == null) return "";
  const fname = _SPELL_IMG[spellId];
  if (!fname) return "";
  const ver = version || "16.10.1";
  return `/data/ddragon/${ver}/img/spell/${fname}`;
}

// One CD chip: spell icon (24px) + countdown label. Returns a span.
// kind: "d" / "f" (summoner spell) or "ult" (ultimate). ult has no
// icon (Live Client doesn't expose ult id), so we render a "R" sigil
// in its place.
function _chip(label, iconUrl, cdSec, kind) {
  const chip = document.createElement("span");
  chip.className = `cd-chip cd-chip-${kind}`;
  const ready = (cdSec != null && cdSec <= 0);
  if (ready) chip.classList.add("cd-chip-ready");
  // Icon (or letter sigil for ult)
  if (iconUrl) {
    const img = document.createElement("img");
    img.src = iconUrl;
    img.alt = label;
    img.title = label;
    img.className = "cd-chip-icon";
    img.onerror = () => { img.style.visibility = "hidden"; };
    chip.appendChild(img);
  } else {
    const sigil = document.createElement("span");
    sigil.className = "cd-chip-sigil";
    sigil.textContent = (kind === "ult") ? "R" : (label || "?").charAt(0);
    chip.appendChild(sigil);
  }
  const txt = document.createElement("span");
  txt.className = "cd-chip-text";
  txt.textContent = ready ? "READY" : _fmtCd(cdSec);
  chip.appendChild(txt);
  return chip;
}

// One ledger row. cooldown is a single backend row dict; champLookup
// is the Map built from liveclient.
function _renderRow(cooldown, champLookup, version) {
  const li = document.createElement("li");
  li.className = "cd-row";
  const side = cooldown.side || "";
  if (side === "blue") li.classList.add("cd-row-blue");
  else if (side === "red") li.classList.add("cd-row-red");

  // Portrait column.
  const portWrap = document.createElement("span");
  portWrap.className = "cd-row-portrait";
  const summ = cooldown.summoner_name || "";
  const champ = champLookup.get(summ) || "";
  const portUrl = _portraitUrl(champ, version);
  if (portUrl) {
    const img = document.createElement("img");
    img.src = portUrl;
    img.alt = champ;
    img.title = `${champ} (${summ})`;
    img.className = "cd-row-portrait-img";
    img.onerror = () => {
      img.style.display = "none";
      portWrap.appendChild(_initialBadge(champ || summ));
    };
    portWrap.appendChild(img);
  } else {
    portWrap.appendChild(_initialBadge(champ || summ));
  }
  li.appendChild(portWrap);

  // Name column.
  const name = document.createElement("span");
  name.className = "cd-row-name";
  name.title = summ;
  name.textContent = _shortName(summ);
  li.appendChild(name);

  // Chips column - D summ, F summ, Ult.
  const chips = document.createElement("span");
  chips.className = "cd-row-chips";
  const s = cooldown.summs || {};
  const u = cooldown.ult || {};
  chips.appendChild(_chip(s.d_name || "D", _spellIconUrl(s.d_id, version), s.d_cd_remaining_s, "d"));
  chips.appendChild(_chip(s.f_name || "F", _spellIconUrl(s.f_id, version), s.f_cd_remaining_s, "f"));
  chips.appendChild(_chip("Ult", "", u.cd_remaining_s, "ult"));
  li.appendChild(chips);

  return li;
}

function _initialBadge(text) {
  const b = document.createElement("span");
  b.className = "cd-row-initial";
  b.textContent = (text || "?").charAt(0).toUpperCase();
  return b;
}

// Trim long summoner names for the narrow rail; full name is on hover.
function _shortName(s) {
  if (!s) return "-";
  const bare = String(s).split("#", 1)[0];
  if (bare.length <= 12) return bare;
  return bare.slice(0, 11) + "...";
}

// Compute a coarse signature for the cooldown list so we can skip
// rebuilding the DOM when nothing meaningful changed. Buckets CDs to
// the nearest second so sub-second jitter doesn't churn the render.
function _ledgerSig(cooldowns) {
  if (!Array.isArray(cooldowns) || !cooldowns.length) return "empty";
  const parts = cooldowns.map((c) => {
    const s = c.summs || {};
    const u = c.ult || {};
    return [
      c.summoner_name || "",
      c.side || "",
      Math.round(+s.d_cd_remaining_s || 0),
      Math.round(+s.f_cd_remaining_s || 0),
      Math.round(+u.cd_remaining_s || 0),
      s.d_id == null ? "" : s.d_id,
      s.f_id == null ? "" : s.f_id,
    ].join(",");
  });
  return parts.join("|");
}

// Public render. parentEl is the container we own; cooldowns is the
// /api/state.summoner_cooldowns array (null/empty allowed).
// ctx.liveclient is threaded by the caller so we can resolve champion
// portraits. ctx.version overrides the DDragon patch (defaults 16.10.1).
export function renderCooldownLedger(parentEl, cooldowns, ctx) {
  if (!parentEl) return;
  const ctxLive = (ctx && ctx.liveclient) || null;
  const version = (ctx && ctx.version) || "16.10.1";

  // Sig dedup - if the cooldowns list hashes identical AND the
  // collapse state hasn't changed since last render, bail out so we
  // don't churn the DOM 1 Hz.
  const collapsed = _isCollapsed();
  const sig = makeSig(_ledgerSig(cooldowns), collapsed ? "c" : "e");
  if (idempotentRender(parentEl, sig)) return;

  parentEl.innerHTML = "";

  // Empty / null - render placeholder, hide the rail's content but
  // keep the header visible so the rail doesn't collapse to 0 width.
  if (!Array.isArray(cooldowns) || !cooldowns.length) {
    const empty = document.createElement("div");
    empty.className = "cd-empty";
    empty.textContent = "no live game";
    parentEl.appendChild(empty);
    _applyCollapseState();
    return;
  }

  const champLookup = _buildChampNameLookup(ctxLive);

  const ul = document.createElement("ul");
  ul.className = "cd-ledger";
  for (const c of cooldowns) {
    ul.appendChild(_renderRow(c, champLookup, version));
  }
  parentEl.appendChild(ul);
  _applyCollapseState();
}

// --- Collapse / expand --------------------------------------------------

function _isCollapsed() {
  try {
    return localStorage.getItem(_LS_COLLAPSED) === "1";
  } catch (_) {
    return false;
  }
}

function _setCollapsed(v) {
  try {
    localStorage.setItem(_LS_COLLAPSED, v ? "1" : "0");
  } catch (_) {}
}

function _applyCollapseState() {
  const pane = _CD.pane();
  const head = _CD.head();
  if (!pane) return;
  const collapsed = _isCollapsed();
  pane.classList.toggle("cd-collapsed", collapsed);
  if (head) {
    const chev = head.querySelector(".cd-chev");
    if (chev) chev.textContent = collapsed ? "+" : "-";
  }
}

// Wire the collapse header click handler. Idempotent - safe to call on
// every render; if the listener is already attached, skips re-binding.
export function attachCooldownLedgerHandlers() {
  const head = _CD.head();
  if (!head) return;
  if (head.dataset.cdBound === "1") return;
  head.dataset.cdBound = "1";
  head.addEventListener("click", () => {
    _setCollapsed(!_isCollapsed());
    _applyCollapseState();
    // Re-render so the dataset.sig invalidates and the next state
    // tick picks up the new collapse state.
    const body = _CD.body();
    if (body) body.dataset.sig = "";
  });
  _applyCollapseState();
}

// Test hooks - exported so unit tests can poke the helpers without
// faking the full DOM. Not part of the public surface.
export const __test = {
  _fmtCd,
  _ledgerSig,
  _buildChampNameLookup,
  _portraitUrl,
  _spellIconUrl,
  _shortName,
  _SPELL_IMG,
};
