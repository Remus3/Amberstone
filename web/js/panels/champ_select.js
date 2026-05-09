// Champ Select panel — interactive overlay during ChampSelect phase,
// SR draft build chooser, champ-select analyzer.
// _ib* functions live in item_build.js (avoid circular dep).
import { el, safe, fmtList, isArenaPayload } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, CHAMPS, _normItemName, _resolveItemId, _resolveChampId } from '../lib/items_index.js';
import {
  _ibPushItems, _ibFetchAndRender, _ibSetStatus,
  _ibRenderRows, _ibMarkSelectedRow, _ibSaveChoice,
} from './item_build.js';

// ── Champ-select panel (Phase 1, 2026-04-25) ────────────────────────
// Interactive overlay shown only during phase=ChampSelect. Renders
// my pick + 5 ally + 5 enemy cells + ARAM bench. Click bench → fires
// bench_swap (LCU bypasses the 5s client cooldown so it's instant).
// Click reroll/lock → fires the corresponding LCU command.
function lcuCmd(cmdObj) {
  // Endpoint expects FLAT shape: {cmd: "name", ...args} — not wrapped.
  return fetch("/api/lcu-cmd", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cmdObj),
  }).then((r) => (r && r.ok ? r.json() : null)).catch(() => null);
}

// Poll /api/lcu-cmd-result for the agent's response to a queued LCU
// command (the POST itself returns immediately with just the queue id).
// Calls onResult({ok, err}) once the agent reports back, or once after
// ~3s of pending if the agent is unreachable. Used by the lobby Find
// Match / Cancel / Change-queue buttons so non-leader 400s and other
// LCU errors surface as a status line instead of vanishing silently.
function lcuPollResult(id, onResult) {
  if (!id) { onResult && onResult({ ok: false, err: "no_queue_id" }); return; }
  let tries = 0;
  const tick = () => {
    tries += 1;
    fetch("/api/lcu-cmd-result?id=" + id, { cache: "no-store" })
      .then((r) => r.json().then((j) => ({ status: r.status, body: j })))
      .then(({ status, body }) => {
        if (status === 200 && body && body.result) {
          onResult && onResult(body.result);
        } else if (tries < 6) {
          setTimeout(tick, 500);
        } else {
          onResult && onResult({ ok: false, err: "timeout" });
        }
      })
      .catch(() => {
        if (tries < 6) setTimeout(tick, 500);
        else onResult && onResult({ ok: false, err: "fetch_failed" });
      });
  };
  setTimeout(tick, 300);  // give agent one poll cycle to drain
}

function _csChampImg(cid) {
  if (!cid) return "";
  const nm = CHAMPS.byId[String(cid)];
  if (!nm) return "";
  return `/data/ddragon/${CHAMPS.version}/img/champion/${nm}.png`;
}
function _csChampName(cid) {
  return (cid && CHAMPS.byId[String(cid)]) || "";
}

// Loadout state — tracks what we've applied to avoid spam-pushing on
// every 2s poll. Re-pushes when champion or variant key changes, or
// when the user explicitly picks a different variant from the selector.
const _csLoadout = {
  lastChamp: 0,        // championId we last pushed for
  lastMode:  "",       // mode we last pushed for
  variants:  [],       // [{key,label,is_default}] for current champion+mode
  chosen:    "",       // user-chosen variant key (sticky until champ change)
  inflight:  false,    // POST in flight — block re-entry
  lastAppliedKey: "",  // `${champ}|${mode}|${variant}` of last successful push
};

function _csNormalizeMode(cs) {
  if (!cs) return "sr";
  const q = cs.queue_id | 0;
  if (q === 450 || q === 920 || cs.is_aram) return "aram";
  if (q === 1700 || q === 1710) return "arena";
  if (q === 400) return "sr";  // SR draft
  if (q === 420 || q === 430 || q === 440) return "sr";  // SR ranked / blind
  return "sr";
}

function _csSetStatus(text, cls) {
  const el = document.getElementById("cs-loadout-status");
  if (!el) return;
  el.className = "cs-loadout-status" + (cls ? " " + cls : "");
  el.textContent = text || "";
}

// Build the set of item_ids that appear in some variants but NOT all
// — these are the "differing" items that distinguish one build from
// another. Used by both renderers to mark items with .cs-build-item--diff
// so the user's eye lands on exactly what trades off between variants.
// Returns an empty set when there's only one variant (nothing to diff).
function _csDiffItemIds(variants) {
  const out = new Set();
  if (!variants || variants.length < 2) return out;
  const sets = variants.map((v) =>
    new Set((v.item_ids || []).slice(0, 6).map(String)));
  // Union of all item ids across variants
  const union = new Set();
  sets.forEach((s) => s.forEach((id) => union.add(id)));
  // An id is "diff" if it isn't present in EVERY variant's set.
  union.forEach((id) => {
    if (!sets.every((s) => s.has(id))) out.add(id);
  });
  return out;
}

// Render the variant list as selectable rows. Each row carries inline
// keystone + first-N item icons so the user can compare builds at a
// glance. Clicking a row selects it (radio-style) and triggers an
// /api/loadout/apply push. Rebuilt 2026-04-26 — the old <select>
// dropdown hid alternate builds behind a click and gave the user the
// impression there was only one choice. 2026-05-01: items that differ
// across variants get .cs-build-item--diff so the eye lands on the
// tradeoffs (Tier 4 #17 side-by-side comparison).
function _csRenderBuildList(variants, chosen) {
  const wrap = document.getElementById("cs-build-list");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!variants || !variants.length) {
    wrap.innerHTML =
      '<div class="cs-loadout-empty">No builds defined for this champion ' +
      'in this mode — add one to data/champion_loadouts.json</div>';
    return;
  }
  const ver = CHAMPS.version || "latest";
  const diffIds = _csDiffItemIds(variants);
  variants.forEach((v) => {
    const row = document.createElement("div");
    const isExp = v.key === "experimental";
    row.className = "cs-build-row" + (v.key === chosen ? " selected" : "")
      + (isExp ? " experimental" : "");
    row.dataset.variant = v.key;

    const cb = document.createElement("div");
    cb.className = "cs-build-checkbox";
    row.appendChild(cb);

    const meta = document.createElement("div");
    meta.className = "cs-build-meta";
    const label = document.createElement("div");
    label.className = "cs-build-label";
    label.textContent = v.label || v.key;
    if (v.is_default) {
      const tag = document.createElement("span");
      tag.className = "default-tag";
      tag.textContent = "default";
      label.appendChild(tag);
    }
    meta.appendChild(label);
    const runes = document.createElement("div");
    runes.className = "cs-build-runes";
    const ks = v.keystone || (isExp ? "auto-generated on pick" : "—");
    const tree = v.primary ? ` · ${v.primary}${v.secondary ? "/" + v.secondary : ""}` : "";
    runes.textContent = ks + tree;
    meta.appendChild(runes);
    row.appendChild(meta);

    const items = document.createElement("div");
    items.className = "cs-build-items";
    const ids = (v.item_ids || []).slice(0, 6);
    if (!ids.length) {
      for (let i = 0; i < 6; i++) {
        const ph = document.createElement("div");
        ph.className = "cs-build-item placeholder";
        items.appendChild(ph);
      }
    } else {
      ids.forEach((iid, idx) => {
        const cell = document.createElement("div");
        const isDiff = diffIds.has(String(iid));
        cell.className = "cs-build-item" + (isDiff ? " cs-build-item--diff" : "");
        const nm = (v.item_names || [])[idx] || ("item " + iid);
        cell.title = isDiff ? `${nm} (differs across variants)` : nm;
        cell.innerHTML = `<img src="/data/ddragon/${ver}/img/item/${iid}.png" onerror="this.style.display='none'" alt="">`;
        items.appendChild(cell);
      });
    }
    row.appendChild(items);

    row.addEventListener("click", () => _csOnBuildRowClick(v.key));
    wrap.appendChild(row);
  });
}

function _csMarkSelectedRow(variantKey) {
  const wrap = document.getElementById("cs-build-list");
  if (!wrap) return;
  wrap.querySelectorAll(".cs-build-row").forEach((r) => {
    if (r.dataset.variant === variantKey) r.classList.add("selected");
    else r.classList.remove("selected");
  });
}

// ── In-game build chooser (2026-04-26) ───────────────────────────
// Lives inside #item-build, NOT the champ-select overlay. Pre-game
// selection is persisted in localStorage so this chooser highlights
// the same row by default. Mid-game pushes items only (runes +
// summoners are locked at game start).
const _ibBuilds = {
  lastChamp:  "",
  lastMode:   "",
  variants:   [],
  chosen:     "",
  inflight:   false,
  lastAppliedKey: "",
};
function _csOnBuildRowClick(variant) {
  if (!variant) return;
  _csLoadout.chosen = variant;
  _csLoadout.lastAppliedKey = "";  // force push
  _csMarkSelectedRow(variant);
  const champName = _csChampName(_csLoadout.lastChamp);
  if (!champName) return;
  if (variant === "experimental") {
    _csSetStatus("generating experimental…", "busy");
    fetch("/api/experimental/get", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ champion: champName, mode: _csLoadout.lastMode }),
    })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        if (!data || !data.ok || !data.current) {
          _csSetStatus("experimental gen failed", "err");
          return;
        }
        _csApplyLoadout(champName, "experimental", _csLoadout.lastMode);
        fetch("/api/experimental/mark", {
          method: "POST", cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ champion: champName, mode: _csLoadout.lastMode }),
        }).catch(() => {});
      })
      .catch(() => _csSetStatus("experimental fetch failed", "err"));
  } else {
    _csApplyLoadout(champName, variant, _csLoadout.lastMode);
  }
}

// Force-summoners override (2026-04-26 user request). When the
// checkbox is on, _csApplyLoadout suppresses the variant's summoner
// push (push_summoners:false) and instead sends a separate
// set_summoners {d:4, f:32} via /api/lcu-cmd. State persists in
// localStorage rc-force-flash-snowball.
function _csForceSummsOn() {
  try { return localStorage.getItem("rc-force-flash-snowball") === "1"; }
  catch (_) { return false; }
}
function _csWireForceSummsOnce() {
  const cb = document.getElementById("cs-force-flash-snowball");
  if (!cb || cb._wired) return;
  cb._wired = true;
  cb.checked = _csForceSummsOn();
  cb.addEventListener("change", () => {
    try { localStorage.setItem("rc-force-flash-snowball", cb.checked ? "1" : "0"); }
    catch (_) {}
    // Force re-push so the override takes effect immediately on the
    // currently-selected build (no need to re-click the row).
    _csLoadout.lastAppliedKey = "";
    const champ = _csChampName(_csLoadout.lastChamp);
    if (champ && _csLoadout.chosen) {
      _csApplyLoadout(champ, _csLoadout.chosen, _csLoadout.lastMode);
    }
  });
}

function _csApplyLoadout(champion, variant, mode) {
  if (!champion || !variant) return;
  const force = _csForceSummsOn();
  const key = champion + "|" + mode + "|" + variant + (force ? "|F" : "");
  if (key === _csLoadout.lastAppliedKey) return;  // already pushed
  if (_csLoadout.inflight) return;
  _csLoadout.inflight = true;
  _csSetStatus("pushing…", "busy");
  fetch("/api/loadout/apply", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      champion: champion, variant: variant, mode: mode,
      push_summoners: !force,  // skip variant summoners when override is on
    }),
  })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((data) => {
      _csLoadout.inflight = false;
      if (!data || !data.ok) {
        _csSetStatus("push failed", "err");
        return;
      }
      _csLoadout.lastAppliedKey = key;
      if (force) {
        // Send the override AFTER the build apply — set_summoners is
        // its own LCU command path, doesn't conflict with item/rune push.
        lcuCmd({ cmd: "set_summoners", d: 4, f: 32 });
      }
      // Persist this pre-game choice so the in-game build chooser
      // (renderItemBuild → _ibMaybeRenderBuilds) can pre-select it.
      try { localStorage.setItem("rc-ingame-build-" + champion, variant); }
      catch (_) {}
      const queued = (data.queued || []).join(", ") || "nothing";
      const tag = force ? " · F+S forced" : "";
      _csSetStatus("✓ pushed: " + queued + tag, "ok");
      _csMarkSelectedRow(variant);
      // Clear the OK flash after a few seconds
      setTimeout(() => {
        if (_csLoadout.lastAppliedKey === key) _csSetStatus("✓ active: " + (data.label || variant) + tag, "ok");
      }, 2400);
    })
    .catch(() => {
      _csLoadout.inflight = false;
      _csSetStatus("push failed", "err");
    });
}

function _csOnChampionOrModeChange(championName, championId, mode) {
  // Reset chosen variant — sticky only within same champion.
  _csLoadout.lastChamp = championId;
  _csLoadout.lastMode  = mode;
  _csLoadout.chosen    = "";
  _csLoadout.lastAppliedKey = "";
  fetch("/api/loadout/list", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ champion: championName, mode: mode }),
  })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((data) => {
      const block = document.getElementById("cs-loadout-block");
      if (!data || !data.variants || !data.variants.length) {
        if (block) block.hidden = true;
        _csSetStatus("");
        return;
      }
      if (block) block.hidden = false;
      _csLoadout.variants = data.variants;
      _csLoadout.chosen   = data.default || data.variants[0].key;
      _csRenderBuildList(data.variants, _csLoadout.chosen);
      _csApplyLoadout(championName, _csLoadout.chosen, mode);
    })
    .catch(() => {
      const block = document.getElementById("cs-loadout-block");
      if (block) block.hidden = true;
    });
}

// ── SR Draft Theatre chooser (Phase 8 step 5, 2026-05-04) ──────────
// Gated on cs.sr_draft (true for queue ids 400/420/430/440 — Normal
// Draft, Ranked Solo/Duo, Normal Blind, Ranked Flex). Pulls 3 engine-
// generated profiles + N user-curated additive builds from
// /api/sr-draft/profile, renders them as .cs-build-row siblings, and
// pushes a chosen profile via /api/sr-draft/apply (which uses a unique
// RC: page name per variant so concurrent picks don't clobber each
// other through the rune writer's delete-all-RC-pages step).
//
// Operator-additive invariant: engine and user profiles are merged at
// the route layer (see dashboard/routes_sr_draft._serve_sr_draft_profile_post);
// the frontend just renders whatever order they arrive in.
const _srDraft = {
  lastChamp:  0,        // championId — dedupe key
  lastSig:    "",       // (champ|role|allies|enemies|queue) — dedupe key
  profiles:   [],
  chosen:     "",
  inflight:   false,
  debounceTimer: null,
  lastAppliedKey: "",
  userEdited: false,    // P8-5.5: chip seeded from LCU until user touches it
};
const _SRDRAFT_DEBOUNCE_MS = 1500;  // bench/team churn during draft

function _srDraftSetStatus(text, cls) {
  const el = document.getElementById("cs-srdraft-status");
  if (!el) return;
  el.className = "cs-loadout-status" + (cls ? " " + cls : "");
  el.textContent = text || "";
}

function _srDraftRoleChoice() {
  try {
    const saved = localStorage.getItem("rc-srdraft-role") || "";
    const sel = document.getElementById("cs-srdraft-role");
    if (sel && sel.value !== saved) sel.value = saved;
    return saved;
  } catch (_) { return ""; }
}
function _srDraftSaveRoleChoice(v) {
  try { localStorage.setItem("rc-srdraft-role", v || ""); }
  catch (_) {}
}
function _srDraftWireRoleSelectOnce() {
  const sel = document.getElementById("cs-srdraft-role");
  if (!sel || sel._wired) return;
  sel._wired = true;
  sel.value = _srDraftRoleChoice();
  sel.addEventListener("change", () => {
    _srDraftSaveRoleChoice(sel.value);
    // P8-5.5: explicit operator choice locks out LCU pre-population
    // for the rest of this session.
    _srDraft.userEdited = true;
    // Force a re-fetch with the new role hint.
    _srDraft.lastSig = "";
    _srDraft.lastAppliedKey = "";
  });
}

// P8-5.5: read assignedPosition for the local player from the LCU
// champ_select payload (surfaced via gamepc_lcu_agent.py _team_picks).
// Returns one of TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY (uppercased to match
// the role chip <option value=…>) or "" when LCU didn't assign a position
// (blind pick, ARAM, etc).
function _srDraftRoleFromLcu(cs) {
  if (!cs || !Array.isArray(cs.my_team)) return "";
  const cell = cs.local_cell;
  const me = cs.my_team.find((p) => p && p.cellId === cell);
  const pos = (me && typeof me.assignedPosition === "string")
    ? me.assignedPosition.trim().toUpperCase() : "";
  if (!pos) return "";
  // LCU emits TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY directly; coerce
  // common aliases just in case.
  const aliases = { MID: "MIDDLE", BOT: "BOTTOM", ADC: "BOTTOM",
                    SUPPORT: "UTILITY", SUP: "UTILITY", JG: "JUNGLE" };
  const norm = aliases[pos] || pos;
  if (norm === "TOP" || norm === "JUNGLE" || norm === "MIDDLE"
      || norm === "BOTTOM" || norm === "UTILITY") return norm;
  return "";
}

function _srDraftSig(championId, role, my_team, their_team, queue_id) {
  const a = (my_team    || []).map((p) => p && p.championId | 0).join(",");
  const e = (their_team || []).map((p) => p && p.championId | 0).join(",");
  return `${championId}|${role || ""}|${a}|${e}|${queue_id | 0}`;
}

function _srDraftRenderRows(profiles, chosen) {
  const wrap = document.getElementById("cs-srdraft-list");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!profiles || !profiles.length) {
    wrap.innerHTML =
      '<div class="cs-loadout-empty">No engine profiles available — ' +
      'is the Daemon Slayer engine running on :8893?</div>';
    return;
  }
  const ver = CHAMPS.version || "latest";
  const diffIds = _csDiffItemIds(profiles);
  profiles.forEach((p) => {
    const row = document.createElement("div");
    const isExp = p.key === "experimental";
    row.className = "cs-build-row" + (p.key === chosen ? " selected" : "")
                  + (isExp ? " experimental" : "");
    row.dataset.variant = p.key;

    const cb = document.createElement("div");
    cb.className = "cs-build-checkbox";
    row.appendChild(cb);

    const meta = document.createElement("div");
    meta.className = "cs-build-meta";
    const label = document.createElement("div");
    label.className = "cs-build-label";
    label.textContent = p.label || p.key;
    // engine vs user tag — surface so the user knows which row is
    // their own curated build vs the auto-generated profiles.
    const tag = document.createElement("span");
    tag.className = "cs-build-kind " + (p.kind === "user" ? "user" : "engine");
    tag.textContent = p.kind === "user" ? "user" : "engine";
    label.appendChild(tag);
    meta.appendChild(label);

    const runes = document.createElement("div");
    runes.className = "cs-build-runes";
    const ks = (p.runes && p.runes.keystone) || p.keystone || "—";
    const tree = (p.runes && p.runes.primary)
      ? ` · ${p.runes.primary}${p.runes.secondary ? "/" + p.runes.secondary : ""}`
      : "";
    runes.textContent = ks + tree;
    meta.appendChild(runes);

    // Engine stat line — quick "why this build" scan: dps + gold.
    // Hidden for user profiles (no engine eval available).
    if (p.kind !== "user" && p.engine) {
      const stats = document.createElement("div");
      stats.className = "cs-build-engine-stats";
      const dps = p.engine.final_dps != null
        ? Math.round(p.engine.final_dps).toLocaleString() : "—";
      const gold = p.engine.total_gold != null
        ? (p.engine.total_gold / 1000).toFixed(1) + "k" : "—";
      stats.textContent = `${dps} dps · ${gold} gold`;
      meta.appendChild(stats);
    }
    row.appendChild(meta);

    const items = document.createElement("div");
    items.className = "cs-build-items";
    const ids = (p.item_ids || []).slice(0, 6);
    if (!ids.length) {
      for (let i = 0; i < 6; i++) {
        const ph = document.createElement("div");
        ph.className = "cs-build-item placeholder";
        items.appendChild(ph);
      }
    } else {
      ids.forEach((iid, idx) => {
        const cell = document.createElement("div");
        const isDiff = diffIds.has(String(iid));
        cell.className = "cs-build-item" + (isDiff ? " cs-build-item--diff" : "");
        const nm = (p.build_path || [])[idx] || ("item " + iid);
        cell.title = isDiff ? `${nm} (differs across profiles)` : nm;
        cell.innerHTML = `<img src="/data/ddragon/${ver}/img/item/${iid}.png" onerror="this.style.display='none'" alt="">`;
        items.appendChild(cell);
      });
    }
    row.appendChild(items);

    row.addEventListener("click", () => _srDraftOnRowClick(p));
    wrap.appendChild(row);
  });
}

function _srDraftMarkSelectedRow(variantKey) {
  const wrap = document.getElementById("cs-srdraft-list");
  if (!wrap) return;
  wrap.querySelectorAll(".cs-build-row").forEach((r) => {
    if (r.dataset.variant === variantKey) r.classList.add("selected");
    else r.classList.remove("selected");
  });
}

function _srDraftOnRowClick(profile) {
  if (!profile || !profile.champion || !profile.key) return;
  _srDraft.chosen = profile.key;
  _srDraftMarkSelectedRow(profile.key);
  const key = profile.champion + "|" + profile.key;
  if (key === _srDraft.lastAppliedKey) return;
  if (_srDraft.inflight) return;
  _srDraft.inflight = true;
  _srDraftSetStatus("pushing…", "busy");
  fetch("/api/sr-draft/apply", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      champion: profile.champion,
      key:      profile.key,
      kind:     profile.kind,
      label:    profile.label,
      runes:    profile.runes || {},
      summoner_spells: profile.summoner_spells || [],
      item_ids: profile.item_ids || [],
    }),
  })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((data) => {
      _srDraft.inflight = false;
      if (!data || !data.ok) {
        _srDraftSetStatus("push failed", "err");
        return;
      }
      _srDraft.lastAppliedKey = key;
      const queued = (data.queued || []).join(", ") || "nothing";
      _srDraftSetStatus("✓ pushed: " + queued, "ok");
    })
    .catch(() => {
      _srDraft.inflight = false;
      _srDraftSetStatus("push failed", "err");
    });
}

function _srDraftFetchProfile(championName, championId, role,
                               my_team, their_team, queue_id) {
  const sig = _srDraftSig(championId, role, my_team, their_team, queue_id);
  if (sig === _srDraft.lastSig) return;       // dedupe identical comp
  if (_srDraft.debounceTimer) clearTimeout(_srDraft.debounceTimer);
  _srDraft.debounceTimer = setTimeout(() => {
    _srDraft.lastSig = sig;
    _srDraftSetStatus("fetching…", "busy");
    fetch("/api/sr-draft/profile", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        champion:   championName,
        role:       role || null,
        my_team:    my_team || [],
        their_team: their_team || [],
        queue_id:   queue_id | 0,
      }),
    })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        if (!data) {
          _srDraftSetStatus("fetch failed", "err");
          return;
        }
        // Profiles arrive engine-first then user-additive — render in
        // the order the route returns (operator-additive invariant).
        const profiles = data.profiles || [];
        _srDraft.profiles = profiles;
        // Default selection: keep prior choice if still valid, else first row.
        const stillValid = _srDraft.chosen
          && profiles.some((p) => p.key === _srDraft.chosen);
        _srDraft.chosen = stillValid ? _srDraft.chosen
          : (profiles[0] && profiles[0].key) || "";
        _srDraftRenderRows(profiles, _srDraft.chosen);
        const eng = profiles.filter((p) => p.kind !== "user").length;
        const usr = profiles.filter((p) => p.kind === "user").length;
        if (data.notes && data.notes.length) {
          _srDraftSetStatus("ready · " + eng + " engine + " + usr + " user (notes)", "");
        } else if (!profiles.length) {
          _srDraftSetStatus("no profiles", "err");
        } else {
          _srDraftSetStatus("ready · " + eng + " engine + " + usr + " user", "");
        }
      })
      .catch(() => _srDraftSetStatus("fetch failed", "err"));
  }, _SRDRAFT_DEBOUNCE_MS);
}

function _srDraftMaybeRender(cs, myCid, myName) {
  const block = document.getElementById("cs-srdraft-block");
  if (!block) return;
  // Gate: sr_draft flag from _state_builder + champion picked.
  if (!cs.sr_draft) {
    block.hidden = true;
    // Reset state so the next time we enter draft, the first render
    // forces a fresh fetch (not blocked by stale lastSig).
    _srDraft.lastChamp = 0;
    _srDraft.lastSig   = "";
    return;
  }
  _srDraftWireRoleSelectOnce();
  if (!myCid || !myName || myName === "—") {
    // Show the block with a placeholder so the user knows the chooser
    // exists during early draft phases (banning, hovering).
    block.hidden = false;
    const list = document.getElementById("cs-srdraft-list");
    if (list && !list.children.length) {
      list.innerHTML =
        '<div class="cs-loadout-empty">Pick a champion to see ' +
        'engine + user builds for this draft.</div>';
    }
    _srDraftSetStatus("waiting for pick", "");
    return;
  }
  block.hidden = false;
  // P8-5.5: prefer LCU assignedPosition until the operator manually
  // changes the chip. This makes the chooser pre-populate to the
  // drafted role instead of the localStorage default for queues that
  // surface assignedPosition (Ranked Solo/Flex, Draft Pick).
  const lcuRole = _srDraftRoleFromLcu(cs);
  let role;
  const sel = document.getElementById("cs-srdraft-role");
  if (!_srDraft.userEdited && lcuRole) {
    if (sel && sel.value !== lcuRole) sel.value = lcuRole;
    role = lcuRole;
  } else {
    role = sel ? sel.value : _srDraftRoleChoice();
  }
  _srDraftFetchProfile(myName, myCid, role,
                       cs.my_team, cs.their_team, cs.queue_id);
}

// ── Team-comp analyzer (Phase 3, 2026-04-26) ────────────────────────
// Debounced AI call that recommends swap / variant / stay based on
// current team comp. Only runs in ARAM and only when bench has options
// OR the user has multiple variants available. Result drives:
//   - verdict badge + reason text in cs-analyzer-block
//   - star highlight on the recommended bench cell
//   - glow on the variant dropdown when variant change is recommended
const _csAnalyzer = {
  lastKey: "",            // dedupe key for comp+bench+champ+variant
  inflight: false,
  lastResult: null,       // last response payload
  debounceTimer: null,
};

function _csAnalyzerFireDebounced(payload, key) {
  if (key === _csAnalyzer.lastKey) return;
  if (_csAnalyzer.inflight) return;
  if (_csAnalyzer.debounceTimer) clearTimeout(_csAnalyzer.debounceTimer);
  // 4s debounce — bench/team churn during active draft shouldn't burn calls
  _csAnalyzer.debounceTimer = setTimeout(() => {
    _csAnalyzer.lastKey = key;
    _csAnalyzer.inflight = true;
    const block = document.getElementById("cs-analyzer-block");
    const verdictEl = document.getElementById("cs-analyzer-verdict");
    const reasonEl = document.getElementById("cs-analyzer-reason");
    if (block) block.hidden = false;
    if (verdictEl) {
      verdictEl.className = "cs-analyzer-verdict busy";
      verdictEl.textContent = "analyzing…";
    }
    if (reasonEl) reasonEl.textContent = "asking the coach…";
    fetch("/api/aram-analyze", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        _csAnalyzer.inflight = false;
        _csAnalyzer.lastResult = data;
        _csRenderAnalyzerResult(data);
      })
      .catch(() => {
        _csAnalyzer.inflight = false;
        if (verdictEl) {
          verdictEl.className = "cs-analyzer-verdict";
          verdictEl.textContent = "error";
        }
        if (reasonEl) reasonEl.textContent = "analyzer call failed";
      });
  }, 4000);
}

function _csRenderAnalyzerResult(data) {
  const block = document.getElementById("cs-analyzer-block");
  const verdictEl = document.getElementById("cs-analyzer-verdict");
  const confEl = document.getElementById("cs-analyzer-conf");
  const reasonEl = document.getElementById("cs-analyzer-reason");
  if (!data || !data.ok) {
    if (verdictEl) { verdictEl.className = "cs-analyzer-verdict"; verdictEl.textContent = "—"; }
    if (reasonEl) reasonEl.textContent = (data && data.reason) || "analyzer unavailable";
    return;
  }
  const rec = data.recommendation || "stay";
  const verdictText = rec === "swap"    ? `SWAP → ${data.swap_to || "?"}`
                    : rec === "variant" ? `VARIANT → ${data.variant_to || "?"}`
                    :                     "STAY (comp ok)";
  if (verdictEl) {
    verdictEl.className = "cs-analyzer-verdict " + rec;
    verdictEl.textContent = verdictText;
  }
  if (confEl) confEl.textContent = (data.confidence || "") + " conf";
  if (reasonEl) reasonEl.textContent = data.reason || "";

  // Apply highlights — bench cell for swap, build row for variant.
  document.querySelectorAll(".cs-bench-cell.recommended").forEach(
    (el) => el.classList.remove("recommended")
  );
  document.querySelectorAll(".cs-build-row.has-recommendation").forEach(
    (el) => {
      el.classList.remove("has-recommendation");
      const t = el.querySelector(".cs-build-label .reco-tag");
      if (t) t.remove();
    }
  );

  if (rec === "swap" && data.swap_to) {
    document.querySelectorAll(".cs-bench-cell").forEach((cell) => {
      const title = cell.title || "";
      if (title.startsWith("Swap to " + data.swap_to + " ")) {
        cell.classList.add("recommended");
      }
    });
  } else if (rec === "variant" && data.variant_to) {
    const row = document.querySelector(
      '.cs-build-row[data-variant="' + CSS.escape(data.variant_to) + '"]'
    );
    if (row) {
      row.classList.add("has-recommendation");
      const lbl = row.querySelector(".cs-build-label");
      if (lbl && !lbl.querySelector(".reco-tag")) {
        const tag = document.createElement("span");
        tag.className = "reco-tag";
        tag.textContent = "★ recommended";
        lbl.appendChild(tag);
      }
    }
  }
}

function _csMaybeRunAnalyzer(cs, myCid, myName, mode) {
  // Only in ARAM (or ARAM Mayhem). Other modes don't have bench/swap
  // and the analyzer prompt is ARAM-tuned. Mayhem queue_ids don't
  // always set cs.is_aram (LCU agent only flags 450/920) — fall back
  // to "bench present" or mode === aram as additional ARAM signals
  // so Mayhem games surface the analyzer too. (2026-04-26 user-
  // reported regression: analyzer never rendered during Mayhem.)
  const _aramish = !!(cs && (cs.is_aram
                             || (Array.isArray(cs.bench) && cs.bench.length > 0)
                             || mode === "aram"));
  if (!_aramish) {
    const block = document.getElementById("cs-analyzer-block");
    if (block) block.hidden = true;
    return;
  }
  if (!myCid || !myName || myName === "—") return;
  if (!CHAMPS.ready) return;
  const myTeam = (cs.my_team || [])
    .map((p) => CHAMPS.byId[String(p && p.championId)])
    .filter(Boolean);
  const theirTeam = (cs.their_team || [])
    .map((p) => CHAMPS.byId[String(p && p.championId)])
    .filter(Boolean);
  const bench = (cs.bench || [])
    .map((id) => CHAMPS.byId[String(id)])
    .filter(Boolean);
  // Skip when there's no swap target AND no variant alternatives —
  // analyzer won't have anything to recommend.
  if (!bench.length && (!_csLoadout.variants || _csLoadout.variants.length <= 1)) {
    const block = document.getElementById("cs-analyzer-block");
    if (block) block.hidden = true;
    return;
  }
  const key = [myName, myTeam.join("|"), theirTeam.join("|"),
               bench.join("|"), _csLoadout.chosen || ""].join("/");
  _csAnalyzerFireDebounced({
    my_champion: myName,
    my_team:     myTeam,
    their_team:  theirTeam,
    bench:       bench,
    current_variant: _csLoadout.chosen || "",
    mode:        mode,
  }, key);
}

function _csWireButtonsOnce() {
  const r = document.getElementById("cs-reroll-btn");
  if (r && !r._wired) {
    r._wired = true;
    r.addEventListener("click", () => {
      if (r.disabled) return;
      r.disabled = true;
      lcuCmd({ cmd: "reroll" });
      setTimeout(() => { r.disabled = false; }, 1500);
    });
  }
  const l = document.getElementById("cs-lock-btn");
  if (l && !l._wired) {
    l._wired = true;
    l.addEventListener("click", () => {
      if (l.disabled) return;
      l.disabled = true;
      // Pull current pick from cached state (cs.my_champion).
      const cid = (l._currentCid | 0);
      if (cid > 0) lcuCmd({ cmd: "lock_pick", championId: cid });
      setTimeout(() => { l.disabled = false; }, 1500);
    });
  }
}

function renderChampSelectPanel(lcu) {
  const overlay = document.getElementById("cs-overlay");
  if (!overlay) return;
  // Diagnostic dump (?dbg=1 in URL): one-line console.log of cs.*
  // fields per state poll so we can see what the LCU agent forwards
  // during Mayhem pre-pick (benchChampions vs championPickIntent vs
  // something else). Throttled by a "last-keys" comparison so the
  // console doesn't get spammed on every 2s tick. (2026-04-26 Issue B.)
  if (/[?&]dbg=1/.test(location.search) && lcu && lcu.champ_select) {
    const cs = lcu.champ_select;
    const sig = JSON.stringify({
      phase: lcu.phase,
      keys:  Object.keys(cs).sort(),
      my_champion: cs.my_champion,
      bench_n: (cs.bench || []).length,
      my_team_n: (cs.my_team || []).length,
      their_team_n: (cs.their_team || []).length,
    });
    if (window.__rcLastCsSig !== sig) {
      window.__rcLastCsSig = sig;
      console.log("[rc-dbg] champ_select sig:", sig, "full:", cs);
    }
  }
  if (!lcu || lcu.phase !== "ChampSelect") {
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
    // Reset DS preview key so next champ-select session fires fresh.
    // _CS_DS is defined later in the same scope; safe at poll-time.
    _CS_DS.lastKey = "";
    return;
  }
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
  _csWireButtonsOnce();
  _csWireForceSummsOnce();
  if (!CHAMPS.ready) return;  // names not loaded yet — wait next tick

  const cs = lcu.champ_select || {};
  // ARAM-style mode? Used to hide the enemy team block + collapse the
  // ally row to full width since ARAM doesn't reveal enemies pre-game.
  // Mayhem queue_ids don't always set cs.is_aram, so accept "bench
  // present" as an additional ARAM signal — same fallback used by the
  // bench renderer + analyzer.
  {
    const _aramish = !!(cs.is_aram
                        || (Array.isArray(cs.bench) && cs.bench.length > 0));
    overlay.classList.toggle("aram-mode", _aramish);
  }
  const myCid = cs.my_champion | 0;
  const myName = _csChampName(myCid) || "—";
  const locked = !!cs.my_completed;
  const csMode = _csNormalizeMode(cs);

  // Champion/mode change detection — re-fetches variant list and fires
  // a fresh apply with the default variant. Skipped when champion is
  // unset (null/0) so we don't push during the brief pre-pick window.
  if (myCid > 0 && myName && myName !== "—" &&
      (myCid !== _csLoadout.lastChamp || csMode !== _csLoadout.lastMode)) {
    _csOnChampionOrModeChange(myName, myCid, csMode);
  }
  // SR Draft Theatre chooser — debounced fetch keyed on (champ, role,
  // allies, enemies, queue). The block is always visible-or-hidden
  // based on cs.sr_draft, so the call is idempotent on every poll.
  _srDraftMaybeRender(cs, myCid, myName);
  // (2026-04-26) Always surface the loadout block while in champ-select
  // so the user knows the build chooser exists. Show a placeholder
  // row until they pick a champion. Without this, the block is hidden
  // when myCid===0 and the user reports "no area to select runes/items".
  {
    const _lb = document.getElementById("cs-loadout-block");
    if (_lb && (!myCid || myCid <= 0)) {
      _lb.hidden = false;
      const _list = document.getElementById("cs-build-list");
      if (_list && !_list.children.length) {
        _list.innerHTML =
          '<div class="cs-loadout-empty">Pick a champion above ' +
          '(or click one of the rolled options below) to see build choices</div>';
      }
      _csSetStatus && _csSetStatus("waiting for pick", "");
    }
  }

  // Run the team-comp analyzer (ARAM only) — debounced internally so
  // bench churn during teammate rerolls doesn't burn API calls.
  _csMaybeRunAnalyzer(cs, myCid, myName, csMode);

  const subBits = [];
  if (cs.is_aram) subBits.push("ARAM");
  if (cs.phase) subBits.push(String(cs.phase).toUpperCase());
  if (cs.queue_id) subBits.push("queue " + cs.queue_id);
  const sub = document.getElementById("cs-phase-sub");
  if (sub) sub.textContent = subBits.join(" · ") || "—";

  const iconEl = document.getElementById("cs-my-icon");
  if (iconEl) {
    const cls = myCid ? (locked ? "locked" : "hovering") : "empty";
    iconEl.className = "cs-my-icon " + cls;
    const url = _csChampImg(myCid);
    iconEl.innerHTML = (myCid && url)
      ? `<img src="${url}" alt="${myName}" onerror="this.style.display='none'">`
      : "?";
  }
  const nameEl = document.getElementById("cs-my-name");
  if (nameEl) nameEl.textContent = myName;
  const stateEl = document.getElementById("cs-my-state");
  if (stateEl) {
    stateEl.textContent = locked ? "✓ LOCKED"
      : (myCid ? "⌛ HOVERING — lock to confirm" : "no pick yet");
  }

  const rerollBtn = document.getElementById("cs-reroll-btn");
  // Same is_aram-fallback as the bench: if bench exists, treat as ARAM.
  const _aramish = cs.is_aram || (Array.isArray(cs.bench) && cs.bench.length > 0);
  if (rerollBtn) rerollBtn.hidden = !_aramish;
  const lockBtn = document.getElementById("cs-lock-btn");
  if (lockBtn) {
    lockBtn._currentCid = myCid;
    lockBtn.hidden = locked || !myCid;
  }

  // Build a quick lookup from cellId -> trade record so we can render
  // trade-state badges + decide which allies are click-tradable.
  const tradesByCell = {};
  (cs.trades || []).forEach((t) => {
    if (t && typeof t.cellId === "number") tradesByCell[t.cellId] = t;
  });

  const renderTeam = (containerId, team, includeMe, isAllies) => {
    const el = document.getElementById(containerId);
    if (!el) return;
    // Allies render vertically (top-to-bottom matches in-game ARAM
    // screen orientation). Enemies stay horizontal — no interaction.
    el.className = "cs-team-row" + (isAllies ? " cs-team-vert" : "");
    el.innerHTML = "";
    const arr = (team || []).slice(0, 5);
    while (arr.length < 5) arr.push(null);
    arr.forEach((p) => {
      const cell = document.createElement("div");
      const cid = (p && p.championId) | 0;
      const isMe = !!(includeMe && cid && cid === myCid);
      const baseStateCls = !cid ? "empty" : (p.completed ? "locked" : "hovering");
      const champNm = _csChampName(cid) || (cid ? "cid:" + cid : "—");
      const summ = (p && p.summonerName) || "";
      const url = _csChampImg(cid);

      // Trade interaction — only for ARAM, only for allies, never for me,
      // and only when the cell has a champion.
      let tradeCls = "";
      const trade = (p && typeof p.cellId === "number") ? tradesByCell[p.cellId] : null;
      if (cs.is_aram && isAllies && !isMe && cid) {
        const tstate = (trade && String(trade.state || "").toUpperCase()) || "AVAILABLE";
        if (tstate === "BUSY")            tradeCls = " trade-busy";
        else if (tstate === "SENT")        tradeCls = " trade-sent";
        else if (tstate === "RECEIVED")    tradeCls = " trade-received";
        else                                tradeCls = " trade-able";
      }

      cell.className = "cs-team-cell " + baseStateCls + (isMe ? " me" : "") + tradeCls;
      cell.title = summ ? `${summ} → ${champNm}` : champNm;

      // Vertical (allies) layout uses a side text column for name+summ;
      // horizontal (enemies) keeps the name+summ stacked under the icon.
      if (isAllies) {
        cell.innerHTML =
          (url
            ? `<img src="${url}" alt="" onerror="this.style.display='none'">`
            : '<div style="width:48px;height:48px"></div>') +
          `<div class="cs-cell-text">` +
            `<div class="nm">${champNm}</div>` +
            (summ ? `<div class="summ">${summ.slice(0, 18)}</div>` : "") +
          `</div>`;
      } else {
        cell.innerHTML =
          (url
            ? `<img src="${url}" alt="" onerror="this.style.display='none'">`
            : '<div style="width:48px;height:48px"></div>') +
          `<div class="nm">${champNm.slice(0, 11)}</div>` +
          (summ ? `<div class="summ">${summ.slice(0, 12)}</div>` : "");
      }

      if (tradeCls === " trade-able" && p && typeof p.cellId === "number") {
        const cellId = p.cellId;
        cell.addEventListener("click", () => {
          cell.classList.add("trade-sent");
          cell.classList.remove("trade-able");
          lcuCmd({ cmd: "trade_request", cell_id: cellId });
        });
      } else if (tradeCls === " trade-received" && p && typeof p.cellId === "number") {
        // Incoming offer — append accept-pill + decline-× into the cell.
        // Click anywhere on the cell (except the × button) accepts the
        // trade; the cell's ::after badge is replaced by inline actions.
        const cellId = p.cellId;
        const actions = document.createElement("div");
        actions.className = "cs-trade-actions";
        actions.innerHTML = `<span class="accept-pill">ACCEPT</span>` +
          `<button type="button" class="decline-x" title="Decline trade">×</button>`;
        cell.appendChild(actions);
        // Suppress the ::after badge once we've put real buttons in.
        cell.style.setProperty("--no-after", "1");
        cell.addEventListener("click", (ev) => {
          // Skip if user hit the decline button.
          if (ev.target && ev.target.closest && ev.target.closest(".decline-x")) return;
          lcuCmd({ cmd: "accept_trade", cell_id: cellId });
          cell.classList.remove("trade-received");
          cell.classList.add("trade-sent");  // visual feedback while LCU swaps
        });
        actions.querySelector(".decline-x").addEventListener("click", (ev) => {
          ev.stopPropagation();
          lcuCmd({ cmd: "decline_trade", cell_id: cellId });
          cell.classList.remove("trade-received");
          cell.style.opacity = "0.55";
        });
      }
      el.appendChild(cell);
    });
  };
  renderTeam("cs-allies",  cs.my_team,    true,  true);
  renderTeam("cs-enemies", cs.their_team, false, false);

  const benchBlock = document.getElementById("cs-bench-block");
  if (!benchBlock) return;
  // (2026-04-26) The LCU agent sets cs.is_aram only when queue_id is
  // 450/920. Mayhem variants get other queue ids and slip through, hiding
  // the bench even though it's clearly populated. Treat "has bench" as
  // an authoritative ARAM-style signal — bench champ selection only
  // exists in ARAM modes regardless of queue id.
  // (2026-04-26 v2) Mayhem rolled options surface in cs.rolled_options
  // (extracted from action.championOptions / myTeam[].championOptions /
  // top-level championOptions etc by the agent). When my_champion is
  // 0 AND bench is empty, fall back to rolled_options as the
  // pickable cards. Click fires lock_pick instead of bench_swap since
  // there's no current pick to swap from.
  const _benchPresent = Array.isArray(cs.bench) && cs.bench.length > 0;
  const _rolls = Array.isArray(cs.rolled_options) ? cs.rolled_options : [];
  const _showAsRolls = !_benchPresent && _rolls.length > 0 && (cs.my_champion | 0) === 0;
  const _anyClickable = _benchPresent || _showAsRolls;
  if (!cs.is_aram && !_anyClickable) {
    benchBlock.hidden = true;
    return;
  }
  benchBlock.hidden = false;
  const grid = document.getElementById("cs-bench-grid");
  if (!grid) return;
  // Update the section label to telegraph what these are.
  const benchLabel = benchBlock.querySelector(".cs-bench-label");
  if (benchLabel) {
    benchLabel.textContent = _showAsRolls
      ? "Rolled options — click to pick"
      : "Bench — click for instant swap (no cooldown)";
  }
  const list = _showAsRolls ? _rolls : (cs.bench || []);
  if (!list.length) {
    grid.innerHTML = '<div class="cs-bench-empty">No bench champs yet — wait for a teammate to reroll</div>';
    return;
  }
  grid.innerHTML = "";
  list.forEach((cid) => {
    const champNm = _csChampName(cid) || "cid:" + cid;
    const cell = document.createElement("div");
    cell.className = "cs-bench-cell";
    cell.title = _showAsRolls
      ? "Pick " + champNm
      : "Swap to " + champNm + " (instant)";
    const url = _csChampImg(cid);
    cell.innerHTML =
      (url ? `<img src="${url}" alt="" onerror="this.style.display='none'">` : "") +
      `<div class="nm">${champNm.slice(0, 11)}</div>`;
    cell.addEventListener("click", () => {
      cell.classList.add("swapping");
      // For Mayhem rolled options (no current pick), use lock_pick to
      // commit. For bench rerolls (active pick), bench_swap is instant.
      const cmd = _showAsRolls
        ? { cmd: "lock_pick", championId: cid }
        : { cmd: "bench_swap", championId: cid };
      lcuCmd(cmd);
      setTimeout(() => cell.classList.remove("swapping"), 1200);
    });
    grid.appendChild(cell);
  });
}

// 2026-04-25: Cold-start champ-select coaching. When LCU phase is
// ChampSelect and we have a locked-in champion + enemy team, surface
// the user's historical adaptation data BEFORE the game starts.
// Resolves championId integers to names via the CHAMPS byId index.
const _CS_LIVE = { lastKey: "", inflight: false, lastFetch: 0, lastResult: null };

// DS Engine preview — fires once per (champion, dsMode) pair during
// champ-select. Keyed separately from _CS_LIVE so drafting ally/enemy
// changes don't re-hit DS (build order doesn't change mid-draft).
const _CS_DS = { lastKey: "", inflight: false };
function _fetchDsPreview(champion, dsMode) {
  const key = champion + "/" + dsMode;
  if (key === _CS_DS.lastKey || _CS_DS.inflight) return;
  _CS_DS.lastKey = key;
  _CS_DS.inflight = true;
  const dsEl = document.getElementById("cs-ds-block");
  const subEl = document.getElementById("cs-ds-sub");
  const tilesEl = document.getElementById("cs-ds-tiles");
  fetch("/api/ds-preview", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ champion, mode: dsMode, level: 6, items: [] }),
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CS_DS.inflight = false;
      if (!data || !data.ok || !Array.isArray(data.ranked)) return;
      const names = data.ranked.map((r) => r.item_name);
      const reasons = {};
      data.ranked.forEach((r) => { reasons[r.item_name] = "+" + Math.round(r.delta_dps) + " dps"; });
      if (subEl) subEl.textContent = champion + " · " + dsMode;
      if (tilesEl) renderItemTiles(tilesEl, names, { cap: 8, reasons });
      if (dsEl) dsEl.removeAttribute("hidden");
    })
    .catch(() => { _CS_DS.inflight = false; });
}
function handleChampSelect(lcu) {
  // Render the interactive overlay first (drives visibility on every poll).
  renderChampSelectPanel(lcu);
  renderLobbyPanel(lcu);
  renderHomePanel(lcu);
  // View router: re-resolve view based on current lcu.phase + state.mode.
  // Fires the auto-promote banner if manual blocks an urgent target.
  _viewResolveAndApply(lcu);
  // If view-lobby is active, refresh its content from the new envelope
  // so members / queue / Find Match state update without a manual nav.
  _maybeRefreshLobbyView();
  if (!lcu || lcu.phase !== "ChampSelect") return;
  const cs = lcu.champ_select || {};
  if (!cs.my_champion || cs.my_champion <= 0) return;
  if (!CHAMPS.ready) return;  // wait for champion-name resolver
  const myName = CHAMPS.byId[String(cs.my_champion)];
  if (!myName) return;
  const allies = (cs.my_team || [])
    .map((p) => CHAMPS.byId[String(p && p.championId)])
    .filter(Boolean);
  const enemies = (cs.their_team || [])
    .map((p) => CHAMPS.byId[String(p && p.championId)])
    .filter(Boolean);
  const bench = (cs.bench || [])
    .map((id) => CHAMPS.byId[String(id)])
    .filter(Boolean);
  // Map queue_id to adaptation mode. ARAM = 450/920, Arena = 1700, etc.
  const modeMap = {
    450: "aram", 920: "aram",        // ARAM + ARAM Mayhem
    1700: "arena", 1710: "arena",    // Arena + variants
    400: "sr_draft", 420: "sr_ranked", 430: "sr_ranked", 440: "sr_ranked",
    830: "sr_ranked", 840: "sr_ranked", 850: "sr_ranked",   // co-op vs AI
  };
  const adaptMode = modeMap[cs.queue_id] || "aram";
  fetchAdaptation(myName, adaptMode === "sr_draft" ? "sr" : adaptMode, enemies);

  // DS Engine pre-game build preview — fires once per (champion, mode)
  // pair; keyed separately from Haiku so draft changes don't re-hit DS.
  const dsMode = (adaptMode === "aram") ? "ARAM"
               : (adaptMode === "arena") ? "ARENA"
               : "SR";
  _fetchDsPreview(myName, dsMode);

  // Live Haiku coaching — debounced + key-deduped so we only fire when
  // the actual pick state changes (champion or team comp), not on every
  // 2 s state poll. ~1 Haiku call per ~10 s of active drafting.
  const liveKey = [
    myName, cs.queue_id, allies.join("|"), enemies.join("|"), bench.join("|"),
  ].join("/");
  const now = Date.now();
  if (liveKey === _CS_LIVE.lastKey) return;
  if (now - _CS_LIVE.lastFetch < 6000) return;   // 6 s minimum spacing
  if (_CS_LIVE.inflight) return;
  _CS_LIVE.lastKey = liveKey;
  _CS_LIVE.lastFetch = now;
  _CS_LIVE.inflight = true;
  fetch("/api/champ-select-coach", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      is_aram: !!cs.is_aram,
      queue_id: cs.queue_id,
      my_champion: myName,
      my_team: allies,
      their_team: enemies,
      bench: bench,
    }),
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CS_LIVE.inflight = false;
      if (!data || !data.ok) return;
      _CS_LIVE.lastResult = data;
      renderChampSelectCoach(data);
    })
    .catch(() => { _CS_LIVE.inflight = false; });
}

// Light renderer — drops the Haiku output into the Right Now action +
// immediate slots while in champ-select. Keeps the existing in-game
// UI surface; switches content when phase=ChampSelect.
function renderChampSelectCoach(data) {
  if (!RN.action || !RN.immediate) return;
  const head = data.advice || "(no advice)";
  RN.action.innerHTML = "▶ " + head;
  const lines = [];
  if (data.summoners) lines.push("Summoners: " + data.summoners);
  if (data.swap)      lines.push("Swap: " + data.swap);
  if (data.watchout)  lines.push("Watch: " + data.watchout);
  _rnImmediate.textContent = lines.join("  •  ");
}

export { handleChampSelect, renderChampSelectPanel, renderChampSelectCoach };
