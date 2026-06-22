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
// name, so it is bridged to the canonical id via _resolveChampId ->
// CHAMPS.byId[numericKey].

import { CHAMPS, _resolveChampId } from '../lib/items_index.js';

const _AB_CONTAINER_ID = "aram-balance-panel";

// Cached champions map from /api/aram-balance: { champId: {field: value} }.
// null = not yet fetched; {} = fetched-empty (fail-soft). The patch is
// cached alongside for the head caption.
const _AB = {
  champions: null,
  patch: "",
  fetching: false,
};

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
// tick picks up the populated cache. Re-fetches only if a prior attempt
// failed (champions stayed null) and none is in flight.
function _abEnsureFetched(onLand) {
  if (_AB.champions !== null || _AB.fetching) return;
  _AB.fetching = true;
  fetch("/api/aram-balance", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      _AB.fetching = false;
      if (j && j.ok && j.champions && typeof j.champions === "object") {
        _AB.champions = j.champions;
        _AB.patch = String(j.patch || "");
      } else {
        _AB.champions = {};
      }
      if (typeof onLand === "function") onLand();
    })
    .catch(() => {
      _AB.fetching = false;
      _AB.champions = {};
    });
}

// Resolve a liveclient display name (or a coach slug) to the canonical
// DDragon champ id used as the /api/aram-balance map key. The coach
// payload already carries a slug; liveclient names ("Tahm Kench",
// "Kha'Zix") round-trip slug -> numeric key -> canonical slug.
function _abCanonicalId(name) {
  if (!name) return "";
  // Direct hit: already a canonical id present in the map.
  if (_AB.champions && Object.prototype.hasOwnProperty.call(_AB.champions, name)) {
    return name;
  }
  const numKey = _resolveChampId(name);
  if (numKey && CHAMPS.byId && CHAMPS.byId[numKey]) {
    return CHAMPS.byId[numKey];
  }
  return "";
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
      const nm = pl.rawChampionName || pl.championName || "";
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
    if (host.dataset.abSig !== "__loading__") {
      host.dataset.abSig = "__loading__";
      host.replaceChildren(_abHead("loading ARAM balance..."),
        _abEmpty("Fetching per-champion ARAM modifiers..."));
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
    const neutral = document.createElement("span");
    neutral.className = "ab-neutral";
    neutral.textContent = "neutral";
    deltas.appendChild(neutral);
  }
  el.appendChild(deltas);
  return el;
}
