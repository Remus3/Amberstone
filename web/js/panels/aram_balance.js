// ARAM balance-adjustment grid panel.
//
// Surfaces Riot's per-champion ARAM modifiers (aramDamageDealt / Taken /
// Healing / Shielding / Tenacity / AttackSpeed multipliers + the additive
// aramAbilityHaste) that RC already loads into the DS snapshot but never
// displayed. Renders SELF always (from the coach payload's champion) plus
// ally + enemy rows when the liveclient roster is present.
//
// Render contract (mirrors active_match.js dispatch): renderAramBalance(p,
// ctx) where p is the live coach payload (p.champion is the operator's
// champion slug) and ctx carries { mode, liveclient }. Renders ONLY when
// ctx.mode resolves to ARAM; otherwise hides the container idempotently.
//
// Data source: GET /api/aram-balance, fetched ONCE and cached client-side
// (the map is immutable per patch). Keys are canonical DDragon champ ids
// (e.g. "Aatrox", "TahmKench"); the liveclient championName is a display
// name, so it is bridged to the canonical id via _resolveChampId, which
// (despite its name) returns the canonical NAME - champions_index.json
// byName maps normalized-name -> "Aatrox". See _abCanonicalId.

import { _resolveChampId } from '../lib/items_index.js';

const _AB_CONTAINER_ID = "aram-balance-panel";

// Cached champions map from /api/aram-balance: { champId: {field: value} }.
// null = not resolved (never fetched, or the last attempt failed); {} = the
// route answered and no champion carries a modifier this patch. The patch is
// cached alongside for the head caption. `failedAt` is the epoch-ms stamp of
// the last failed attempt and is what separates "not yet" from "tried and
// could not" - a failure must never masquerade as a resolved empty map, or
// every row renders the positive claim "no ARAM changes" off a dead route.
const _AB = {
  champions: null,
  patch: "",
  fetching: false,
  failedAt: 0,
};

// Cooldown between failed attempts. The render tick runs ~every 2s, so an
// ungated retry would turn one dead route into a fetch storm.
const _AB_RETRY_MS = 30000;

// Field -> short label + whether it is a flat-additive (AH) vs multiplier.
// Order here is the render order within a row.
const _AB_FIELDS = [
  { key: "aramDamageDealt",  label: "DMG dealt",  flat: false, goodWhenUp: true },
  { key: "aramDamageTaken",  label: "DMG taken",  flat: false, goodWhenUp: false },
  { key: "aramHealing",      label: "Healing",    flat: false, goodWhenUp: true },
  { key: "aramShielding",    label: "Shielding",  flat: false, goodWhenUp: true },
  { key: "aramTenacity",     label: "Tenacity",   flat: false, goodWhenUp: true },
  { key: "aramAttackSpeed",  label: "Atk speed",  flat: false, goodWhenUp: true },
  { key: "aramAbilityHaste", label: "AH",         flat: true,  goodWhenUp: true },
];

const _AB_ARAM_MODES = new Set(["aram", "kiwi"]);

function _abContainer() {
  return document.getElementById(_AB_CONTAINER_ID);
}

function _abIsAram(ctx) {
  const mode = String((ctx && ctx.mode) || "").toLowerCase();
  return _AB_ARAM_MODES.has(mode);
}

// One-shot fetch of the balance map. Returns immediately; the next render
// tick picks up the populated cache. Re-fetches if a prior attempt failed
// (champions stays null) once the retry cooldown has expired and none is in
// flight. Every terminal branch calls onLand so the panel repaints - the
// failure branch has a state of its own to show.
function _abEnsureFetched(onLand) {
  if (_AB.champions !== null || _AB.fetching) return;
  if (_AB.failedAt && (Date.now() - _AB.failedAt) < _AB_RETRY_MS) return;
  _AB.fetching = true;
  fetch("/api/aram-balance", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      _AB.fetching = false;
      if (j && j.ok && j.champions && typeof j.champions === "object") {
        _AB.champions = j.champions;
        _AB.patch = String(j.patch || "");
        _AB.failedAt = 0;
      } else {
        _AB.failedAt = Date.now();
      }
      if (typeof onLand === "function") onLand();
    })
    .catch(() => {
      _AB.fetching = false;
      _AB.failedAt = Date.now();
      if (typeof onLand === "function") onLand();
    });
}

// Live Client `rawChampionName` is a LOCALIZATION KEY, not a name:
// "game_character_displayname_Singed". It normalizes to
// "gamecharacterdisplaynamesinged" and resolves to null, so it must be
// stripped back to the canonical tail before any lookup. Measured live
// 2026-07-20 (ARAM Mayhem, queue 2400): the unstripped form killed every
// ally + enemy row.
const _AB_RAW_PREFIX = /^game_character_displayname_/i;

function _abStripRawName(name) {
  return String(name || "").replace(_AB_RAW_PREFIX, "");
}

// Resolve a liveclient display name (or a coach slug) to the canonical
// DDragon champ id used as the /api/aram-balance map key. The coach
// payload already carries a slug; liveclient names ("Tahm Kench",
// "Kha'Zix") normalize into the same canonical id.
//
// _resolveChampId returns the canonical NAME ("Aatrox"), NOT a numeric id -
// items_index CHAMPS.byName maps normalized-name -> NAME. Feeding that
// return into CHAMPS.byId (an id -> name map) never hit and yielded "",
// which is what emptied this panel for the whole game.
function _abCanonicalId(name) {
  const nm = _abStripRawName(name);
  if (!nm) return "";
  // Direct hit: already a canonical id present in the map.
  if (_AB.champions && Object.prototype.hasOwnProperty.call(_AB.champions, nm)) {
    return nm;
  }
  // A champion legitimately ABSENT from the balance map (no ARAM changes
  // this patch) still resolves here, so it keeps its row; only a name that
  // resolves to nothing at all returns "" and is dropped.
  return _resolveChampId(nm) || "";
}

// Build the ordered row set: SELF first, then allies, then enemies.
// Each row = { id, label, kind }. Dedups by canonical id (self wins).
function _abBuildRows(p, ctx) {
  const rows = [];
  const seen = new Set();
  const push = (rawName, kind) => {
    const id = _abCanonicalId(rawName);
    if (!id || seen.has(id)) return;
    seen.add(id);
    rows.push({ id: id, kind: kind });
  };

  // SELF always (coach payload slug).
  push((p && p.champion) || "", "self");

  const lc = (ctx && ctx.liveclient) || null;
  if (lc && Array.isArray(lc.allPlayers) && lc.allPlayers.length) {
    const myTeam = _abResolveMyTeam(lc);
    for (const pl of lc.allPlayers) {
      if (!pl || typeof pl !== "object") continue;
      // championName is the DISPLAY name and resolves directly;
      // rawChampionName is the localization-key form, usable only after
      // _abCanonicalId strips its prefix - so it is the FALLBACK, never the
      // preference.
      const nm = pl.championName || pl.rawChampionName || "";
      if (!nm) continue;
      // Unknown team -> treat as ally (no worse than mislabeling enemy).
      const kind = (myTeam && pl.team && pl.team !== myTeam) ? "enemy" : "ally";
      push(nm, kind);
    }
  }
  return rows;
}

// Local copy of active_match.js _resolveMyTeam (kept self-contained so the
// panel has no cross-panel import coupling).
function _abResolveMyTeam(lc) {
  if (!lc || typeof lc !== "object") return null;
  const ap = lc.activePlayer || {};
  const me = ap.summonerName || ap.riotIdGameName || "";
  if (!me) return null;
  for (const pl of (lc.allPlayers || [])) {
    if (!pl || typeof pl !== "object") continue;
    const rid = pl.riotIdGameName || pl.summonerName || "";
    if (rid === me || me.startsWith(rid + "#") || rid === me.split("#", 1)[0]) {
      return pl.team || null;
    }
  }
  return null;
}

// Signed-percent for a multiplier (1.05 -> "+5%"); signed flat for AH
// (3 -> "+3 AH"). Returns { text, dir } where dir is +1 / -1 / 0.
function _abDelta(field, value) {
  if (field.flat) {
    const n = Math.round(value);
    return { text: (n >= 0 ? "+" : "") + n + " AH", dir: Math.sign(n) };
  }
  const pct = Math.round((value - 1.0) * 100);
  return { text: (pct >= 0 ? "+" : "") + pct + "%", dir: Math.sign(pct) };
}

// A buff vs nerf reads off the field's goodWhenUp + the signed direction.
// "DMG taken -10%" is a BUFF (good) even though the number is negative.
function _abStatusClass(field, dir) {
  if (dir === 0) return "";
  const isGood = field.goodWhenUp ? dir > 0 : dir < 0;
  return isGood ? "ab-good" : "ab-bad";
}

// Build a stable signature of the rendered content so we skip the DOM
// rewrite when nothing changed (feedback_dashboard_render_idempotency).
function _abSignature(rows) {
  const parts = [];
  for (const row of rows) {
    const fields = (_AB.champions && _AB.champions[row.id]) || {};
    const fieldSig = _AB_FIELDS
      .filter((f) => fields[f.key] != null)
      .map((f) => f.key + ":" + fields[f.key])
      .join(",");
    parts.push(row.kind + "|" + row.id + "|" + fieldSig);
  }
  return _AB.patch + "::" + parts.join(";");
}

function _abKindLabel(kind) {
  if (kind === "self") return "YOU";
  if (kind === "enemy") return "ENEMY";
  return "ALLY";
}

export function renderAramBalance(p, ctx) {
  const host = _abContainer();
  if (!host) return;  // older HTML cache - no container

  // Mode gate: hide + clear when not ARAM (idempotent).
  if (!_abIsAram(ctx)) {
    if (host.dataset.abState !== "hidden") {
      host.dataset.abState = "hidden";
      host.style.display = "none";
      host.replaceChildren();
      host.dataset.abSig = "";
    }
    return;
  }
  host.style.display = "";
  host.dataset.abState = "live";

  // Fetch the map once; replay this render when it lands.
  _abEnsureFetched(() => renderAramBalance(p, ctx));
  if (_AB.champions === null) {
    // Unresolved splits two ways and the operator must be able to tell them
    // apart: still landing, versus tried and could not. Neither may render a
    // grid, because an empty grid reads as "no champion is adjusted".
    const down = _AB.failedAt !== 0;
    const sig = down ? "__unavailable__" : "__loading__";
    if (host.dataset.abSig !== sig) {
      host.dataset.abSig = sig;
      host.replaceChildren(
        _abHead(down ? "ARAM balance unavailable" : "loading ARAM balance..."),
        _abEmpty(down
          ? "Balance data did not load - retrying."
          : "Fetching per-champion ARAM modifiers..."));
    }
    return;
  }

  const rows = _abBuildRows(p, ctx);
  const sig = _abSignature(rows);
  if (host.dataset.abSig === sig) return;  // unchanged - skip rewrite
  host.dataset.abSig = sig;

  const frag = document.createDocumentFragment();
  const caption = _AB.patch ? ("ARAM balance - patch " + _AB.patch) : "ARAM balance";
  frag.appendChild(_abHead(caption));

  if (!rows.length) {
    frag.appendChild(_abEmpty("Waiting for champion data..."));
    host.replaceChildren(frag);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "ab-grid";
  for (const row of rows) {
    grid.appendChild(_abRow(row));
  }
  frag.appendChild(grid);
  host.replaceChildren(frag);
}

function _abHead(text) {
  const head = document.createElement("div");
  head.className = "ab-head";
  head.textContent = text;
  return head;
}

function _abEmpty(text) {
  const el = document.createElement("div");
  el.className = "ab-empty";
  el.textContent = text;
  return el;
}

function _abRow(row) {
  const el = document.createElement("div");
  el.className = "ab-row ab-row-" + row.kind;

  const tag = document.createElement("span");
  tag.className = "ab-kind ab-kind-" + row.kind;
  tag.textContent = _abKindLabel(row.kind);
  el.appendChild(tag);

  const name = document.createElement("span");
  name.className = "ab-name";
  name.textContent = row.id;
  el.appendChild(name);

  const fields = (_AB.champions && _AB.champions[row.id]) || {};
  const deltas = document.createElement("span");
  deltas.className = "ab-deltas";

  let any = false;
  for (const field of _AB_FIELDS) {
    const v = fields[field.key];
    if (v == null) continue;
    any = true;
    const d = _abDelta(field, v);
    const chip = document.createElement("span");
    chip.className = "ab-chip " + _abStatusClass(field, d.dir);
    const lbl = document.createElement("span");
    lbl.className = "ab-chip-label";
    lbl.textContent = field.label;
    const val = document.createElement("span");
    val.className = "ab-chip-val";
    val.textContent = d.text;
    chip.appendChild(lbl);
    chip.appendChild(val);
    deltas.appendChild(chip);
  }
  if (!any) {
    // Resolved fine, just carries no modifiers this patch. Saying so beats
    // a bare "neutral" - the operator must be able to tell an unadjusted
    // champion from a panel that failed to resolve anyone (an unresolvable
    // name produces NO row at all).
    const neutral = document.createElement("span");
    neutral.className = "ab-neutral";
    neutral.textContent = "no ARAM changes";
    deltas.appendChild(neutral);
  }
  el.appendChild(deltas);
  return el;
}

// Test seam: the fetch state machine is driven directly by
// tests/test_aram_balance_fetch_failure.py with a stubbed globalThis.fetch,
// so the failure branches are exercised rather than read.
export const __test = { _AB, _AB_RETRY_MS, _abEnsureFetched };
