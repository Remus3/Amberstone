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
// Client displayName - including UPGRADED forms, because the API reports the
// current tier name (RM-05: the jungle-pet Smite tiers were missing, so the
// enemy jungler's chip fell into the unknown-name path mid-game and never
// counted down). An unknown spell falls back to 0 -> a plain used/UP toggle
// with no countdown (still useful as a "burned" marker).
const SPELL_CD = {
  Flash: 300, Heal: 240, Barrier: 180, Exhaust: 210, Ignite: 180,
  Cleanse: 210, Ghost: 210, Teleport: 360, "Unleashed Teleport": 360,
  Smite: 90, "Unleashed Smite": 90, "Primal Smite": 90,
  Clarity: 240, Mark: 80, Dash: 80, Snowball: 80, "To the King!": 80,
};

// Compact 2-letter spell labels (operator 2026-06-29: the full displayName +
// state - "Flash UP" / "Unleashed Teleport 142s" - overran the chip and clipped
// to "Fla..."/"Unl...", unreadable; A5's "unname" intent is a compact tag). Keys
// match the Live Client displayName; an unknown spell falls back to its first two
// letters uppercased so it still renders short, never an ellipsis.
const SPELL_ABBR = {
  Flash: "FL", Heal: "HL", Barrier: "BR", Exhaust: "EX", Ignite: "IG",
  Cleanse: "CL", Ghost: "GH", Teleport: "TP", "Unleashed Teleport": "TP",
  Smite: "SM", "Unleashed Smite": "SM", "Primal Smite": "SM",
  Clarity: "CY", Mark: "MK", Dash: "DA", Snowball: "SB",
  "To the King!": "TK",
};

function _abbr(spell) {
  if (SPELL_ABBR[spell]) return SPELL_ABBR[spell];
  return String(spell || "?").replace(/[^A-Za-z]/g, "").slice(0, 2).toUpperCase() || "?";
}

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

// Remaining seconds, Infinity for a no-CD "burned" marker, or null when UP.
// Auto-clears an expired entry so a finished countdown reads UP again without
// a tap.
function _remaining(champ, slot, spellName) {
  if (!_store) return null;
  const k = _key(champ, slot);
  const t = _store.map[k];
  if (!t) return null;
  const cd = SPELL_CD[spellName] || 0;
  // Unknown spell -> the header's sticky used/UP toggle. Without this the
  // cd=0 entry hit the expiry branch below on the very next read and the tap
  // was silently erased (RM-05 "chip starts no cooldown timer").
  if (!cd) return Infinity;
  const rem = Math.ceil(t + cd - _now());
  if (rem <= 0) {
    delete _store.map[k];
    _persist();
    return null;
  }
  return rem;
}

// Build the row DOM once per roster. Each spell is a <button> chip carrying its
// champ + slot so the delegated click can toggle it.
function _buildRows(mount, enemies) {
  mount.innerHTML = "";
  // Shared champ-name column width = the longest name in this roster (+1 char of
  // proportional-font slack) so every row's chips align and no name is clipped -
  // the .es-champ rule reads it as `var(--es-champ-ch)`.
  const maxLen = enemies.reduce(
    (m, e) => Math.max(m, String(e.champion || "").length), 0);
  mount.style.setProperty("--es-champ-ch", String(maxLen + 1));

  for (const e of enemies) {
    const row = document.createElement("div");
    row.className = "es-row";
    const name = document.createElement("span");
    name.className = "es-champ";
    name.textContent = e.champion;
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
    const tag = _abbr(spell);
    chip.title = spell;  // full name on hover (the chip text is the compact tag)
    if (rem == null) {
      chip.textContent = tag + " UP";
      chip.classList.remove("es-down");
      chip.classList.add("es-up");
    } else if (!Number.isFinite(rem)) {
      // Burned marker (unknown base CD): mark used with no countdown; the
      // next tap toggles it back to UP.
      chip.textContent = tag + " USED";
      chip.classList.remove("es-up");
      chip.classList.add("es-down");
    } else {
      chip.textContent = tag + " " + rem + "s";
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

export const _esInternals = { SPELL_CD, _key, _toggle, _remaining, _load, _abbr, SPELL_ABBR };
