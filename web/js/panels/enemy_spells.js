// web/js/panels/enemy_spells.js
//
// Overlay-only enemy summoner-spell tap-tracker (operator 2026-06-28). The Live
// Client API exposes WHICH spells each enemy carries (allPlayers[].summonerSpells
// -> liveclient.enemy_spells) but NO live cooldown, and no ping/recap feed (both
// confirmed absent from :2999). So this is a MANUAL tracker: tap a spell the
// instant you see/hear it used and it counts down the base cooldown; tap again to
// reset (mis-tap correction). The panel is a click-through ZONE (w-enemyspells),
// so the taps land mid-game in PASSIVE without the ACTIVE toggle.
//
// State is GAME-SCOPED (keyed by game_id) in localStorage so it survives the
// per-tick re-render + an overlay reload, but never bleeds a stale timer into the
// next game. Render is idempotent: the row DOM is rebuilt only when the enemy
// roster changes; every tick just refreshes the countdown text in place (no
// node churn -> no flicker).

const LS_KEY = "rc-enemy-spell-cd";

// Summoner-spell base cooldowns in seconds (patch ~16.x). Keys match the Live
// Client displayName. An unknown spell falls back to 0 -> a plain used/UP toggle
// with no countdown (still useful as a "burned" marker).
const SPELL_CD = {
  Flash: 300, Heal: 240, Barrier: 180, Exhaust: 210, Ignite: 180,
  Cleanse: 210, Ghost: 210, Teleport: 360, "Unleashed Teleport": 360,
  Smite: 90, Clarity: 240, Mark: 80, Dash: 80, Snowball: 80, "To the King!": 80,
};

let _store = null;     // { gameId, map: { "champ|slot": tapEpochSec } }
let _rosterSig = "";

function _now() {
  return Date.now() / 1000;
}

function _load(gameId) {
  const gid = String(gameId || "");
  if (_store && _store.gameId === gid) return _store;
  let map = {};
  try {
    const raw = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    if (raw && String(raw.gameId) === gid && raw.map && typeof raw.map === "object") {
      map = raw.map;
    }
  } catch (_e) {
    // corrupt / absent -> fresh map for this game.
  }
  _store = { gameId: gid, map };
  return _store;
}

function _persist() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(_store));
  } catch (_e) {
    // best-effort; a disabled store must not break the tracker.
  }
}

function _key(champ, slot) {
  return champ + "|" + slot;
}

// Toggle a spell: UP -> mark used now (start the countdown); counting/used ->
// back to UP (the operator mis-tapped or the enemy never actually used it).
function _toggle(champ, slot) {
  if (!_store) return;
  const k = _key(champ, slot);
  if (_store.map[k]) delete _store.map[k];
  else _store.map[k] = _now();
  _persist();
}

// Remaining seconds, or null when UP. Auto-clears an expired entry so a finished
// countdown reads UP again without a tap.
function _remaining(champ, slot, spellName) {
  if (!_store) return null;
  const k = _key(champ, slot);
  const t = _store.map[k];
  if (!t) return null;
  const cd = SPELL_CD[spellName] || 0;
  const rem = Math.ceil(t + cd - _now());
  if (rem <= 0) {
    delete _store.map[k];
    _persist();
    return null;
  }
  return rem;
}

function _shortChamp(name) {
  const n = String(name || "");
  return n.length > 9 ? n.slice(0, 9) : n;
}

// Build the row DOM once per roster. Each spell is a <button> chip carrying its
// champ + slot so the delegated click can toggle it.
function _buildRows(mount, enemies) {
  mount.innerHTML = "";
  const head = document.createElement("div");
  head.className = "es-head";
  head.textContent = "ENEMY SPELLS";
  mount.appendChild(head);

  for (const e of enemies) {
    const row = document.createElement("div");
    row.className = "es-row";
    const name = document.createElement("span");
    name.className = "es-champ";
    name.textContent = _shortChamp(e.champion);
    row.appendChild(name);
    (e.spells || []).forEach((spell, slot) => {
      if (!spell) return;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "es-chip";
      chip.dataset.champ = e.champion;
      chip.dataset.slot = String(slot);
      chip.dataset.spell = spell;
      row.appendChild(chip);
    });
    mount.appendChild(row);
  }

  // One delegated click handler (survives the per-tick timer refresh; the row DOM
  // is only rebuilt on roster change, so this binds once per roster).
  mount.onclick = (ev) => {
    const chip = ev.target && ev.target.closest ? ev.target.closest(".es-chip") : null;
    if (!chip) return;
    _toggle(chip.dataset.champ, chip.dataset.slot);
    _updateTimers(mount);
  };
}

// Refresh every chip's label + state from the live countdown. Called every tick
// (and right after a tap) - text-only, no node churn.
function _updateTimers(mount) {
  const chips = mount.querySelectorAll(".es-chip");
  for (const chip of chips) {
    const spell = chip.dataset.spell;
    const rem = _remaining(chip.dataset.champ, chip.dataset.slot, spell);
    if (rem == null) {
      chip.textContent = spell + " UP";
      chip.classList.remove("es-down");
      chip.classList.add("es-up");
    } else {
      chip.textContent = spell + " " + rem + "s";
      chip.classList.remove("es-up");
      chip.classList.add("es-down");
    }
  }
}

// Self-gated on the overlay shell + a live enemy roster. lc.enemy_spells is the
// per-enemy { champion, spells:[name,name] } list from the backend.
export function renderEnemySpells(lc) {
  const mount = document.getElementById("am-enemyspells");
  if (!mount) return;
  if (!document.body || document.body.dataset.shell !== "overlay") {
    mount.hidden = true;
    return;
  }
  const enemies = lc && Array.isArray(lc.enemy_spells)
    ? lc.enemy_spells.filter((e) => e && e.champion && Array.isArray(e.spells))
    : [];
  if (!enemies.length) {
    mount.hidden = true;
    mount.innerHTML = "";
    _rosterSig = "";
    return;
  }
  _load(lc.game_id || lc.gameId || "");
  const sig = enemies.map((e) => e.champion + ":" + (e.spells || []).join(",")).join("|");
  if (sig !== _rosterSig || !mount.innerHTML) {
    _rosterSig = sig;
    _buildRows(mount, enemies);
  }
  _updateTimers(mount);
  mount.hidden = false;
}

// Test seam: reset module state between cases.
export function _resetEnemySpells() {
  _store = null;
  _rosterSig = "";
  try {
    localStorage.removeItem(LS_KEY);
  } catch (_e) {
    // best-effort.
  }
}

export const _esInternals = { SPELL_CD, _key, _toggle, _remaining, _load };
