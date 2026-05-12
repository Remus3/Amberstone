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

// In-game build chooser state (`_ibBuilds`) used to live here but the
// references all moved to panels/item_build.js during the Phase 3 ESM
// split — the orphaned const lingered. Now declared next to its callers
// in item_build.js so the symbol is reachable.
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
      if (cid > 0) {
        // 2026-05-09 (s155): surface the agent's reply so failures aren't
        // silent. Common cases user can't otherwise diagnose:
        //   - "no pending pick action" → clicked before pick slot active
        //   - "no session" → LCU agent disconnected
        //   - http 4xx/5xx from LCU PATCH
        // Briefly stamps the cs-my-state line ("⌛ HOVERING — lock to confirm")
        // with a status, then restores the live state on next render tick.
        lcuCmd({ cmd: "lock_pick", championId: cid }).then((resp) => {
          const id = resp && resp.id;
          if (!id) return;
          lcuPollResult(id, (result) => {
            const stateEl = document.getElementById("cs-my-state");
            if (!stateEl) return;
            if (result && result.ok) {
              stateEl.textContent = result.note === "already locked"
                ? "✓ ALREADY LOCKED"
                : "✓ LOCK SENT";
            } else {
              const err = (result && result.err) || "no response";
              stateEl.textContent = "✗ Lock failed: " + err;
            }
            // Live render restores the canonical state ~1s later.
          });
        });
      }
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
  // s162: cache the LCU snapshot on state.latest so view-lobby's
  // _lobbyViewRefresh (which reads state.latest.lcu) sees the same data
  // as the overlay. Pre-fix the lobby sub-page rendered empty in
  // production because no upstream path ever assigned state.latest.lcu.
  state.latest.lcu = lcu || null;
  // Render the interactive overlay (champ-select-specific surface).
  renderChampSelectPanel(lcu);
  // s162 bug fix (2026-05-10): renderLobbyPanel / renderHomePanel /
  // _viewResolveAndApply / _maybeRefreshLobbyView USED to be called
  // here, but they're defined in main.js's module scope and were never
  // imported into champ_select.js — every call threw ReferenceError
  // silently caught by the SSE try/catch, so post-refresh the lobby
  // view never re-rendered with newly-arrived lcu data. Orchestration
  // now lives in main.js's handleLcuEnvelope wrapper.
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

// ── Champ Select VIEW (s164 — Phase 3 step 3 scaffold) ─────────────
// New top-level <section id="view-champ-select"> page (distinct from
// the legacy #cs-overlay). Auto-promotes on phase=ChampSelect when
// champSelectViewEnabled() — same flag pattern as activeMatchEnabled.

// s171.7: flipped opt-in → opt-out. The new champ-select view is the
// canonical surface — it ships the lock button, DS build chooser,
// P&B Recommendations panel, ARAM bench, Arena duo+augments, and
// Brawl 5v5 layouts. Operator opts OUT via ``?cs=0`` /
// ``localStorage.csView === '0'`` to fall back to the legacy
// floating #cs-overlay on top of view-lobby.
export function champSelectViewEnabled() {
  try {
    if (typeof location !== "undefined" && location.search) {
      if (location.search.includes("cs=0")) {
        try { localStorage.setItem("csView", "0"); } catch (_) {}
        return false;
      }
      if (location.search.includes("cs=1")) {
        try { localStorage.setItem("csView", "1"); } catch (_) {}
        return true;
      }
    }
    const stored = localStorage.getItem("csView");
    if (stored === "0") return false;
    return true;
  } catch (_) {
    return true;
  }
}

function _csvSetText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text || "";
}

// LCU command helper for the trade/swap clicks below.
function _csvFireCmd(cmd) {
  return fetch("/api/lcu-cmd", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cmd),
  }).then((r) => (r && r.ok ? r.json() : null)).catch(() => null);
}
function _csvOnLaneSwap(cellId) {
  if (cellId == null) return;
  _csvFireCmd({ cmd: "request_position_swap", cell_id: cellId });
}
function _csvOnChampTrade(cellId) {
  if (cellId == null) return;
  _csvFireCmd({ cmd: "trade_request", cell_id: cellId });
}
function _csvOnPickOrderSwap(cellId) {
  if (cellId == null) return;
  _csvFireCmd({ cmd: "request_pick_order_swap", cell_id: cellId });
}
// Quick-select handlers for Pick & Ban panel icons. Tracks the active
// selection client-side so the colored border stays on the picked
// icon across re-renders, and a "locked" flag so subsequent clicks
// can't re-target a different ban/pick once the first has been sent.
const _csvSelection = { ban: 0, pick: 0, banLocked: false, pickLocked: false };
function _csvOnBanSelect(championId) {
  if (!championId) return;
  if (_csvSelection.banLocked) return;  // ban already committed
  _csvSelection.ban = championId;
  _csvSelection.banLocked = true;
  _csvFireCmd({ cmd: "set_ban_intent", championId: championId });
}
function _csvOnPickSelect(championId) {
  if (!championId) return;
  if (_csvSelection.pickLocked) return;  // pick already committed
  _csvSelection.pick = championId;
  _csvSelection.pickLocked = true;
  _csvFireCmd({ cmd: "set_pick_intent", championId: championId });
}
// 1 → "1st", 2 → "2nd", 3 → "3rd", 4 → "4th", etc.
function _csvOrdinal(n) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
// Full role names used in the trade popup AND in the ally/enemy
// position pip. Operator wanted them spelled out rather than the
// 3-letter abbreviations the panel previously showed.
const _CSV_SHORT_ROLE = {
  TOP: "TOP", JUNGLE: "JUNGLE", MIDDLE: "MID",
  BOTTOM: "BOTTOM", UTILITY: "SUPPORT",
};
function _csvShortRole(pos) {
  return _CSV_SHORT_ROLE[pos] || pos || "—";
}
// Singleton popup that appears when the operator clicks an ally's
// summoner name. Structure: a SWAP / TRADE header row above three
// equal-width choice buttons:
//   1) <CHAMPION NAME>  → champion trade
//   2) <Nth Pick>       → pick-order swap (only when showPickOrder)
//   3) <ROLE LABEL>     → lane swap (uses ally's actual short role)
// Positioned so the MIDDLE button's center sits on the username's
// center (when middle is hidden, falls back to the champion button).
function _csvShowTradeChoice(cellId, anchorEl, opts) {
  const champName    = (opts && opts.champName)    || "Champion";
  const pickOrderLbl = (opts && opts.pickOrderLbl) || "";
  const roleLbl      = (opts && opts.roleLbl)      || "—";
  const showPickOrd  = !!(opts && opts.showPickOrder);

  let popup = document.getElementById("csv-trade-popup");
  if (!popup) {
    popup = document.createElement("div");
    popup.id = "csv-trade-popup";
    popup.className = "csv-trade-popup";
    popup.innerHTML =
      '<div class="csv-trade-header">SWAP / TRADE</div>' +
      '<div class="csv-trade-buttons">' +
        '<button type="button" class="csv-trade-choice" data-action="champion"></button>' +
        '<button type="button" class="csv-trade-choice" data-action="pick-order"></button>' +
        '<button type="button" class="csv-trade-choice" data-action="role"></button>' +
      '</div>';
    // Append to <html> instead of <body> — body has zoom:1.33 (see
    // base.css), and any position:fixed descendant of a zoomed element
    // has its top/left values scaled by that zoom, which was offsetting
    // the popup ~33% below where the click landed. The popup gets a
    // matching zoom in CSS so its visual size still matches the rest
    // of the dashboard.
    document.documentElement.appendChild(popup);
    document.addEventListener("click", (ev) => {
      if (!popup.classList.contains("is-open")) return;
      if (popup.contains(ev.target)) return;
      popup.classList.remove("is-open");
    });
    popup.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".csv-trade-choice");
      if (!btn) return;
      const cid = parseInt(popup.dataset.cellId, 10);
      const action = btn.dataset.action;
      popup.classList.remove("is-open");
      if (action === "role")       _csvOnLaneSwap(cid);
      else if (action === "champion") _csvOnChampTrade(cid);
      else if (action === "pick-order") _csvOnPickOrderSwap(cid);
    });
  }
  const champBtn = popup.querySelector('[data-action="champion"]');
  if (champBtn) champBtn.textContent = champName.toUpperCase();
  const pickBtn  = popup.querySelector('[data-action="pick-order"]');
  if (pickBtn) {
    pickBtn.textContent = pickOrderLbl;
    pickBtn.style.display = showPickOrd ? "" : "none";
  }
  const roleBtn  = popup.querySelector('[data-action="role"]');
  if (roleBtn) roleBtn.textContent = roleLbl.toUpperCase();
  popup.dataset.cellId = String(cellId);
  // Render-then-measure: show the popup with visibility:hidden so we
  // can read its actual rendered width via getBoundingClientRect, then
  // compute final left so the popup is horizontally centered on the
  // ALLIES panel and its top edge sits just under the clicked username.
  // Avoids the transform-based positioning that was producing the
  // wrong offset on lower rows.
  popup.style.visibility = "hidden";
  popup.style.left = "0px";
  popup.style.top  = "0px";
  popup.style.transform = "";
  popup.classList.add("is-open");
  const popupRect = popup.getBoundingClientRect();
  const userRect  = anchorEl.getBoundingClientRect();
  const panel = anchorEl.closest(".csv-card-allies");
  const panelRect = panel ? panel.getBoundingClientRect() : userRect;
  const targetLeft = panelRect.left + panelRect.width / 2 - popupRect.width / 2;
  const targetTop  = userRect.bottom + 2;  // 2px breathing room
  popup.style.left = Math.round(targetLeft) + "px";
  popup.style.top  = Math.round(targetTop) + "px";
  popup.style.visibility = "visible";
}

// Module-level cache: { type: "ban"|"pick", cellSet: Set<cellId> } —
// derived from cs.active_round and consulted by _csvRenderTeam to
// apply the pulsating border class to cells whose cellId is in the
// active round. Reset on each renderChampSelectView call.
let _csvActiveRound = null;

// Mode classifier for the champ-select view. SR draft is the historical
// default; ARAM (450/920), Arena (1700/1710), and Brawl (480 + the
// `is_brawl` LCU flag where available) get distinct central + enemies
// layouts because the LCU surface they expose differs structurally —
// ARAM has a bench but no roles/bans, Arena has 2v2v2v2 + augments and
// no enemy-team field, Brawl is 5v5 random with no roles/bans.
function _csvDetectMode(cs) {
  if (!cs) return "sr";
  const q = (cs.queue_id | 0);
  if (cs.is_brawl || q === 480) return "brawl";
  if (q === 1700 || q === 1710) return "arena";
  if (cs.is_aram || q === 450 || q === 920) return "aram";
  return "sr";
}

// Renders a team cell list. Backward-compatible 5-positional signature
// — the 6th `opts` arg adds mode-aware behavior: `cellCount` (default
// 5), `showGuess` (default true for enemy lists), and `allowRolePip`
// (default true). ARAM/Brawl pass `showGuess: false` since roles are
// random and the (guess) annotation is meaningless; Arena uses a
// dedicated 2-cell ally renderer instead.
function _csvRenderTeam(listId, team, myCid, timerEndMs, showPickOrder, opts) {
  const list = document.getElementById(listId);
  if (!list) return;
  list.innerHTML = "";
  const cellCount   = (opts && opts.cellCount) || 5;
  const isEnemyList = (listId === "csv-enemies-list");
  const showGuess   = !opts || opts.showGuess !== false;
  const allowRole   = !opts || opts.allowRolePip !== false;
  const arr = (team || []).slice(0, cellCount);
  while (arr.length < cellCount) arr.push(null);
  arr.forEach((p, idx) => {
    const cid = (p && p.championId) | 0;
    const isMe = !!(myCid && cid === myCid);
    const champNm = _csChampName(cid) || (cid ? "cid:" + cid : "—");
    const summ = (p && p.summonerName) || "";
    const pos = (p && p.assignedPosition) || "";
    const stateCls = !cid ? "empty" : ((p && p.completed) ? "locked" : "hovering");
    const url = _csChampImg(cid);

    // Lock/timer marker for the champ-name col (right-aligned within
    // that col so the marker sits at the end of the champ name, just
    // before the summoner-name col). Locked → green padlock; still
    // picking → red live countdown using cs.timer.remaining_ms.
    let lockHtml = "";
    if (cid) {
      if (p && p.completed) {
        lockHtml = '<span class="csv-team-cell-lock">🔒</span>';
      } else if (timerEndMs) {
        const secs = Math.max(0, Math.ceil((timerEndMs - Date.now()) / 1000));
        // "s" suffix dropped — double-digit times like "22s" were
        // overflowing the lock-aligned slot. Display the bare number.
        lockHtml = `<span class="csv-team-cell-timer" data-end="${timerEndMs}">${secs}</span>`;
      }
    }

    // Hoist peer-cell identity ABOVE the li.className use — referencing
    // peerCellId before its const declaration would throw a TDZ
    // ReferenceError and crash the whole forEach (no cells rendered).
    const isAllyOther = (listId === "csv-allies-list") && !isMe && cid;
    const peerCellId = (p && typeof p.cellId === "number") ? p.cellId : null;

    const li = document.createElement("li");
    let activeCls = "";
    if (_csvActiveRound && _csvActiveRound.cellSet
        && peerCellId != null && _csvActiveRound.cellSet.has(peerCellId)) {
      activeCls = (_csvActiveRound.type === "ban") ? " is-banning" : " is-picking";
    }
    li.className = "csv-team-cell " + stateCls + (isMe ? " me" : "") + activeCls;

    const icon = document.createElement("div");
    icon.className = "csv-team-cell-icon";
    icon.innerHTML = url
      ? `<img src="${url}" alt="" onerror="this.style.display='none'">`
      : "";
    // Per operator: champion-icon and pos-pip no longer initiate
    // trades directly — the only click target for trades is the
    // summoner name (which opens the SWAP / TRADE popup).
    li.appendChild(icon);

    // Champ name col is plain text again — lock/timer moved out.
    const nm = document.createElement("div");
    nm.className = "csv-team-cell-nm";
    nm.textContent = champNm;
    li.appendChild(nm);

    // Summoner col leads with the lock/timer (left-aligned at the col
    // start, which the JS aligner positions at "A of Allies"), then
    // the summoner name sits immediately to its right.
    const sm = document.createElement("div");
    sm.className = "csv-team-cell-summ";
    sm.innerHTML = lockHtml +
      `<span class="csv-team-cell-summ-text">${summ ? summ.slice(0, 22) : ""}</span>`;
    if (isAllyOther && peerCellId != null) {
      const summText = sm.querySelector(".csv-team-cell-summ-text");
      if (summText) {
        summText.classList.add("is-clickable");
        summText.addEventListener("click", (ev) => {
          ev.stopPropagation();
          _csvShowTradeChoice(peerCellId, summText, {
            champName: champNm,
            pickOrderLbl: _csvOrdinal(idx + 1) + " Pick",
            roleLbl: _csvShortRole(pos),
            showPickOrder: !!showPickOrder,
          });
        });
      }
    }
    li.appendChild(sm);

    if (pos && allowRole) {
      const posEl = document.createElement("span");
      posEl.className = "csv-team-cell-pos";
      posEl.textContent = _csvShortRole(pos);
      // Pos pip is now display-only — trades go through the popup.
      li.appendChild(posEl);
    }
    // Enemy cells get a small "(guess)" tag between the centered
    // lock/timer and the role pip — reminds the operator that the
    // role assignment for enemies is inferred, not confirmed by LCU.
    // Suppressed in ARAM/Brawl where there are no roles to guess at.
    if (isEnemyList && cid && showGuess) {
      const guessEl = document.createElement("span");
      guessEl.className = "csv-team-cell-guess";
      guessEl.textContent = "(guess)";
      li.appendChild(guessEl);
    }
    list.appendChild(li);
  });
}

export function renderChampSelectView(lcu) {
  // Section may not exist yet on older cached HTML — bail out cleanly.
  const section = document.getElementById("view-champ-select");
  const grid = section && section.querySelector(".csv-grid");
  if (!grid) return;
  if (!lcu || lcu.phase !== "ChampSelect") {
    _csvSetText("csv-sub", "waiting for champ-select…");
    return;
  }
  if (!CHAMPS.ready) return;  // names not loaded yet — wait next tick

  const cs = lcu.champ_select || {};
  const mode = _csvDetectMode(cs);
  const myCid = (cs.my_champion | 0);
  const myName = _csChampName(myCid) || "—";
  const locked = !!cs.my_completed;

  // Stamp the section with data-cs-mode so CSS can branch (hide
  // pickban panel for non-SR, swap enemies/allies layout for Arena,
  // adjust grid template, etc).
  section.dataset.csMode = mode;

  // Sub-line: mode + queue + inner phase + timer
  const bits = [];
  const modeLabel = { sr: "SR DRAFT", aram: "ARAM", arena: "ARENA", brawl: "BRAWL" }[mode] || "";
  if (modeLabel) bits.push(modeLabel);
  if (cs.queue_id) bits.push("queue " + cs.queue_id);
  if (cs.phase) bits.push(String(cs.phase).toUpperCase());
  if (cs.timer && cs.timer.remaining_ms != null) {
    bits.push(Math.max(0, Math.round(cs.timer.remaining_ms / 1000)) + "s");
  }
  _csvSetText("csv-sub", bits.join(" · ") || "—");

  // Cache absolute timer end timestamp on the cs object so re-renders
  // (every 2s state envelope) don't reset the countdown — important
  // for sim mode where the lcu envelope only fires once.
  let timerEndMs = 0;
  if (cs.timer && typeof cs.timer.remaining_ms === "number") {
    if (!cs.timer._end) cs.timer._end = Date.now() + cs.timer.remaining_ms;
    timerEndMs = cs.timer._end;
  }
  // Pick-order swap button shows only on modes where pick order is
  // structural (SR draft queues). ARAM/Arena/Brawl don't have a
  // meaningful pick order — operator wanted the middle button hidden.
  const showPickOrder = !!cs.sr_draft;
  // Compute active-round set (cells currently banning or picking) so
  // _csvRenderTeam can stamp the pulsing border class on them.
  if (cs.active_round && Array.isArray(cs.active_round.cell_ids)) {
    _csvActiveRound = {
      type: cs.active_round.type === "ban" ? "ban" : "pick",
      cellSet: new Set(cs.active_round.cell_ids),
    };
  } else {
    _csvActiveRound = null;
  }

  // Allies render — Arena renders only 2 cells (me + duo); SR/ARAM/Brawl
  // render 5. ARAM/Brawl also suppress the (guess) tag and role pip
  // since there are no role assignments to display.
  const allyOpts = (mode === "arena")
    ? { cellCount: 2, showGuess: false, allowRolePip: false }
    : (mode === "aram" || mode === "brawl")
      ? { cellCount: 5, showGuess: false, allowRolePip: false }
      : { cellCount: 5, showGuess: true,  allowRolePip: true };
  _csvRenderTeam("csv-allies-list", cs.my_team, myCid, timerEndMs, showPickOrder, allyOpts);

  // Enemies render — Arena uses a dedicated 3-team layout (3 enemy
  // duos stacked vertically). SR keeps the 5-cell list with (guess);
  // ARAM/Brawl render 5 cells but suppress (guess) + role pip.
  if (mode === "arena") {
    _csvRenderEnemiesArena(cs, timerEndMs);
  } else {
    const enemyOpts = (mode === "sr")
      ? { cellCount: 5, showGuess: true,  allowRolePip: true }
      : { cellCount: 5, showGuess: false, allowRolePip: false };
    _csvRenderTeam("csv-enemies-list", cs.their_team, myCid, timerEndMs, showPickOrder, enemyOpts);
  }

  _csvSetupTimerTick();
  _csvRenderCentralPane(cs, mode, myCid, myName, locked);

  // Pick & Ban panel — SR-only. Other modes hide it via CSS rule
  // [data-cs-mode] but we skip the render entirely to save work and
  // keep the body empty (it's display:none anyway).
  if (mode === "sr") {
    _csvRenderPickBan(cs, myCid);
  } else {
    const body = document.getElementById("csv-pickban-body");
    if (body) body.innerHTML = "";
  }
  // _csvAlignAllies() disabled — JS measurement kept returning wrong
  // values; champname col width is hardcoded in CSS instead.
}

// Renders the center column (My Pick + mode-specific extras). Rebuilds
// the .csv-card-mypick body each call so we can vary header + content
// per mode without leaving stale elements behind. SR/ARAM/Brawl get a
// build chooser variant list; Arena gets the duo header + augments.
function _csvRenderCentralPane(cs, mode, myCid, myName, locked) {
  const card = document.querySelector("#view-champ-select .csv-card-mypick");
  if (!card) return;
  const head = card.querySelector(".csv-card-head");
  const body = card.querySelector(".csv-card-body");
  if (!head || !body) return;

  if (mode === "arena") {
    head.textContent = "My Duo + Augments";
    body.innerHTML = _csvArenaPaneHtml(cs, myCid, myName);
    _csvWireArenaAugments(body, cs);
    return;
  }

  head.textContent = "My Pick";
  const iconCls = myCid ? (locked ? "locked" : "hovering") : "empty";
  const iconUrl = _csChampImg(myCid);
  const iconHtml = (myCid && iconUrl)
    ? `<img src="${iconUrl}" alt="${myName}" onerror="this.style.display='none'">`
    : "?";
  const stateCls = myCid ? (locked ? "locked" : "hovering") : "";
  const stateTxt = locked ? "✓ LOCKED" : (myCid ? "⌛ HOVERING" : "no pick yet");

  // s171: lock button — shown only when a champion is hovered but not
  // yet locked. Click fires the LCU lock_pick command and surfaces the
  // result inline via lcuPollResult, mirroring the legacy overlay's
  // #cs-lock-btn (champ_select.js:818). Hidden after lock since there's
  // nothing left to do; LCU re-emits `my_completed=true` and the next
  // render re-renders without the button.
  const lockBtnHtml = (myCid && !locked)
    ? `<button class="csv-lock-btn" id="csv-lock-btn" data-cid="${myCid}">LOCK IN ${myName.toUpperCase()}</button>`
    : "";

  let extraHtml = "";
  if (mode === "aram") {
    extraHtml = _csvBenchHtml(cs);
  }
  const variants = _csvBuildVariantsFor(myCid, myName, mode);
  const buildsTitle = mode === "aram" ? "ARAM build chooser"
                    : mode === "brawl" ? "Brawl build chooser"
                    : "SR build chooser";
  const buildsHtml = `
    <div class="csv-builds" data-champion="${myName || ""}">
      <div class="csv-builds-title">${buildsTitle}</div>
      <div class="csv-builds-body" id="csv-builds-body">
        ${_csvBuildVariantRowsHtml(variants, _csvSavedChoice(myName))}
      </div>
    </div>`;

  body.className = "csv-card-body csv-mypick";
  body.innerHTML = `
    <div class="csv-mypick-icon ${iconCls}" id="csv-mypick-icon">${iconHtml}</div>
    <div class="csv-mypick-name" id="csv-mypick-name">${myName}</div>
    <div class="csv-mypick-state ${stateCls}" id="csv-mypick-state">${stateTxt}</div>
    ${lockBtnHtml}
    ${extraHtml}
    ${buildsHtml}`;

  // Wire bench cells to fire bench_swap on click. Only ARAM renders
  // the bench block; the wiring is idempotent under re-render since
  // we replace innerHTML and re-attach each tick.
  if (mode === "aram") _csvWireBench(body);
  _csvWireBuildVariants(body);
  _csvWireLockButton(body);
}

// s171: lock button click handler — same shape as the legacy overlay's
// #cs-lock-btn. Disables the button on click to prevent double-fire,
// stamps the state line with the agent's response, then re-enables on
// timeout so a real failure can be retried.
function _csvWireLockButton(scope) {
  const btn = scope.querySelector("#csv-lock-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    const cid = (btn.dataset.cid | 0);
    if (!(cid > 0)) { btn.disabled = false; return; }
    lcuCmd({ cmd: "lock_pick", championId: cid }).then((resp) => {
      const id = resp && resp.id;
      if (!id) { btn.disabled = false; return; }
      lcuPollResult(id, (result) => {
        const stateEl = document.getElementById("csv-mypick-state");
        if (stateEl) {
          if (result && result.ok) {
            stateEl.textContent = result.note === "already locked"
              ? "✓ ALREADY LOCKED" : "✓ LOCK SENT";
            stateEl.classList.remove("hovering");
            stateEl.classList.add("locked");
          } else {
            const err = (result && result.err) || "no response";
            stateEl.textContent = "✗ Lock failed: " + err;
          }
        }
      });
    });
    setTimeout(() => { btn.disabled = false; }, 1500);
  });
}

// HTML for the ARAM bench strip (5 horizontal champion cells). Click
// fires lcu bench_swap which bypasses the 5s client-side cooldown.
function _csvBenchHtml(cs) {
  const bench = (cs && Array.isArray(cs.bench)) ? cs.bench.slice(0, 5) : [];
  if (!bench.length) {
    return `
      <div class="csv-bench">
        <div class="csv-bench-title">Bench</div>
        <div class="csv-bench-empty">no bench champs yet — wait for a teammate to reroll</div>
      </div>`;
  }
  const ver = CHAMPS.version || "latest";
  const cells = bench.map((cid) => {
    const nm = _csChampName(cid) || ("cid:" + cid);
    const img = (cid && CHAMPS.byId[String(cid)])
      ? `<img src="/data/ddragon/${ver}/img/champion/${CHAMPS.byId[String(cid)]}.png" alt="${nm}" onerror="this.style.display='none'">`
      : "?";
    return `
      <div class="csv-bench-cell is-clickable" data-bench-id="${cid}" data-bench-name="${nm}" title="Swap to ${nm}">
        <div class="csv-bench-cell-icon">${img}</div>
        <div class="csv-bench-cell-name">${nm}</div>
      </div>`;
  }).join("");
  return `
    <div class="csv-bench">
      <div class="csv-bench-title">Bench · click to swap</div>
      <div class="csv-bench-row">${cells}</div>
    </div>`;
}

function _csvWireBench(scope) {
  scope.querySelectorAll(".csv-bench-cell.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      const cid = parseInt(cell.dataset.benchId, 10);
      if (!cid) return;
      lcuCmd({ cmd: "bench_swap", champion_id: cid });
      // Visual feedback — pulse the cell so the operator sees the click
      // registered before the LCU agent confirms via state push.
      cell.classList.add("is-pending");
      setTimeout(() => cell.classList.remove("is-pending"), 500);
    });
  });
}

// Placeholder build variants. Phase B replaces this with real loadout
// data from /api/loadout/list keyed on champion + mode.
// s171: DS engine cache for the new champ-select view's build chooser.
// Keyed by `${champion}|${dsMode}` — drafts don't change build order so
// caching across the whole champ-select session is safe. Cleared on
// CHAMPS.ready transition (handled implicitly — page reload clears).
const _CSV_DS_CACHE    = Object.create(null);
const _CSV_DS_INFLIGHT = Object.create(null);

// s171.8: parallel cache for user-curated variants from /api/loadout/list.
// User variants are persisted to disk via loadout_resolver, so different
// modes for the same champion can carry different variant sets.
const _CSV_USER_CACHE    = Object.create(null);
const _CSV_USER_INFLIGHT = Object.create(null);

// s171.8: shared storage key with item_build.js (_ibStorageKey). Picking
// a variant here in champ-select pre-selects the same row in the in-game
// build chooser without a separate plumbing layer.
function _csvStorageKey(champion) { return "rc-ingame-build-" + (champion || ""); }
function _csvSavedChoice(champion) {
  try { return localStorage.getItem(_csvStorageKey(champion)) || ""; }
  catch (_) { return ""; }
}
function _csvSaveChoice(champion, variantKey) {
  try { localStorage.setItem(_csvStorageKey(champion), variantKey); }
  catch (_) {}
}

// Convert the view's adapt-mode to the DS engine's mode label.
function _csvDsModeFor(mode) {
  if (mode === "aram")  return "ARAM";
  if (mode === "arena") return "ARENA";
  if (mode === "brawl") return "BRAWL";
  return "SR";
}

// Fire the DS engine for this champion + mode. Non-blocking — the next
// renderChampSelectView tick (~1Hz from the LCU state push) picks up
// the cached result. ``level=6`` matches the legacy overlay's preview
// level so the rankings match between views.
function _csvFetchDsBuilds(champion, dsMode) {
  if (!champion || !dsMode) return;
  const key = `${champion}|${dsMode}`;
  if (_CSV_DS_CACHE[key] || _CSV_DS_INFLIGHT[key]) return;
  _CSV_DS_INFLIGHT[key] = true;
  fetch("/api/ds-preview", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ champion, mode: dsMode, level: 6, items: [] }),
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_DS_INFLIGHT[key] = false;
      if (data && data.ok && Array.isArray(data.ranked) && data.ranked.length) {
        _CSV_DS_CACHE[key] = data.ranked;
      }
    })
    .catch(() => { _CSV_DS_INFLIGHT[key] = false; });
}

// s171.8: fetch user-curated variants (loadout_resolver). Mode label is
// the lower-case form ("sr"/"aram"/"arena"/"brawl") matching the legacy
// chooser's contract — `/api/loadout/list` normalises internally.
function _csvFetchUserVariants(champion, mode) {
  if (!champion || !mode) return;
  const key = `${champion}|${mode}`;
  if (_CSV_USER_CACHE[key] !== undefined || _CSV_USER_INFLIGHT[key]) return;
  _CSV_USER_INFLIGHT[key] = true;
  fetch("/api/loadout/list", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ champion, mode }),
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_USER_INFLIGHT[key] = false;
      // Mark "empty" with [] (truthy in lookup) so we don't refetch
      // forever for champions/modes with no user variants saved.
      _CSV_USER_CACHE[key] = (data && Array.isArray(data.variants))
        ? data.variants : [];
    })
    .catch(() => {
      _CSV_USER_INFLIGHT[key] = false;
      _CSV_USER_CACHE[key] = [];
    });
}

// Build chooser variants for the central pane. s171: returns DS-engine-
// ranked items when available (cached per champion+mode), otherwise a
// "computing…" placeholder. Mode-specific keystone hints distinguish
// the 3 rows visually — same items in each row for now (Phase B-2 will
// produce per-keystone variants once the loadout resolver is wired).
function _csvBuildVariantsFor(cid, name, mode) {
  if (!cid || !name) {
    return [{ key: "empty", label: "no champion yet — hover or lock to see DS picks",
              keystone: "—", item_ids: [], is_default: true }];
  }
  const dsMode = _csvDsModeFor(mode);
  const ranked = _CSV_DS_CACHE[`${name}|${dsMode}`];
  // Always trigger the user-variant fetch in parallel — independent
  // cache from the DS engine call.
  _csvFetchUserVariants(name, mode || "sr");
  if (!ranked || !ranked.length) {
    _csvFetchDsBuilds(name, dsMode);
    return [{ key: "ds-pending", label: `${name} · DS engine computing…`,
              keystone: "—", item_ids: [], is_default: true }];
  }
  const top6 = ranked.slice(0, 6).map((r) => r.item_id).filter((x) => x);
  const reasons = {};
  ranked.slice(0, 6).forEach((r) => {
    if (r.item_id) reasons[r.item_id] = "+" + Math.round(r.delta_dps || 0) + " dps";
  });
  const keystoneLabel = (mode === "aram") ? "ARAM curve"
                     : (mode === "arena") ? "Arena targets"
                     : (mode === "brawl") ? "Brawl curve"
                     : "SR targets";
  // s171.8: combine the DS engine top-picks row (default) with any
  // user-curated variants from /api/loadout/list. Selection persists
  // across CS → in-game via the shared rc-ingame-build-<champion>
  // localStorage key (read by item_build.js:_ibSavedChoice).
  const dsRow = {
    key: "ds-engine",
    label: `${name} · DS engine top picks`,
    keystone: `based on ${keystoneLabel}`,
    item_ids: top6, reasons, is_default: true,
  };
  const userVariants = _CSV_USER_CACHE[`${name}|${mode || "sr"}`] || [];
  // User-variant rows carry their own `keystone`/`item_ids` from the
  // loadout file. Normalise the shape so the row renderer can treat
  // them uniformly. Map `key` through unchanged so the save↔restore
  // round-trip stays stable.
  const userRows = userVariants.map((v) => ({
    key: v.key,
    label: v.label || v.key,
    keystone: v.keystone || "user variant",
    item_ids: v.item_ids || [],
    reasons: {},
    is_default: false,
    is_user: true,
  }));
  return [dsRow].concat(userRows);
}

function _csvBuildVariantRowsHtml(variants, savedChoice) {
  if (!variants || !variants.length) {
    return '<div class="csv-empty">no build variants for this champion / mode yet</div>';
  }
  const ver = (ITEMS && ITEMS.version) || "latest";
  // s171.8: pre-select the saved choice if present; else default to
  // the first row (DS engine top picks). Matches what the in-game
  // chooser does via _ibSavedChoice on the same localStorage key.
  let selectedIdx = 0;
  if (savedChoice) {
    const found = variants.findIndex((v) => v && v.key === savedChoice);
    if (found >= 0) selectedIdx = found;
  }
  return variants.map((v, idx) => {
    const reasons = v.reasons || {};
    const items = (v.item_ids || []).slice(0, 6).map((iid) => {
      const reason = reasons[iid] ? ` title="${reasons[iid]}"` : "";
      return `
      <div class="csv-build-item"${reason}>
        <img src="/data/ddragon/${ver}/img/item/${iid}.png"
             onerror="if(!this.dataset.cdn){this.dataset.cdn=1;this.src='https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${iid}.png'}else{this.style.display='none'}"
             alt="">
      </div>`;
    }).join("") || '<div class="csv-empty">—</div>';
    const cb = `<div class="csv-build-checkbox"></div>`;
    const tag = v.is_default
      ? ' <span class="csv-build-default-tag">default</span>'
      : (v.is_user ? ' <span class="csv-build-user-tag">saved</span>' : '');
    return `
      <div class="csv-build-row${idx === selectedIdx ? " selected" : ""}" data-variant="${v.key}">
        ${cb}
        <div class="csv-build-meta">
          <div class="csv-build-label">${v.label}${tag}</div>
          <div class="csv-build-runes">${v.keystone || "—"}</div>
        </div>
        <div class="csv-build-items">${items}</div>
      </div>`;
  }).join("");
}

function _csvWireBuildVariants(scope) {
  // s171.8: read champion from the wrapper's data-champion so the click
  // handler can persist the selection. Falls back to no-save if absent
  // (defensive — keeps the visual toggle working in unit-test fixtures).
  const wrap = scope.querySelector(".csv-builds");
  const champion = wrap ? (wrap.dataset.champion || "") : "";
  const rows = scope.querySelectorAll(".csv-build-row");
  rows.forEach((row) => {
    row.addEventListener("click", () => {
      rows.forEach((r) => r.classList.toggle("selected", r === row));
      const variantKey = row.dataset.variant;
      if (champion && variantKey
          && variantKey !== "empty"
          && variantKey !== "ds-pending") {
        _csvSaveChoice(champion, variantKey);
      }
    });
  });
}

// Arena central pane: duo header (me + partner) + 3 augment slots
// (silver/gold/prismatic) + the current-round augment options.
function _csvArenaPaneHtml(cs, myCid, myName) {
  const teams = (cs && Array.isArray(cs.arena_teams)) ? cs.arena_teams : [];
  const myTeam = teams.find((t) => t && t.is_me) || (cs.my_team ? { cells: cs.my_team } : null);
  const cells = (myTeam && Array.isArray(myTeam.cells)) ? myTeam.cells : (cs.my_team || []);
  const me = cells.find((c) => (c && c.championId) === myCid) || cells[0] || null;
  const partner = cells.find((c) => c && c.championId && c.championId !== myCid) || null;
  const ver = CHAMPS.version || "latest";
  const cellHtml = (c, isMe) => {
    if (!c || !c.championId) {
      return `<div class="csv-duo-cell is-empty">
        <div class="csv-duo-cell-icon">?</div>
        <div class="csv-duo-cell-tag">${isMe ? "ME" : "DUO"}</div>
        <div class="csv-duo-cell-name">waiting…</div>
      </div>`;
    }
    const nm = _csChampName(c.championId) || ("cid:" + c.championId);
    const img = CHAMPS.byId[String(c.championId)]
      ? `<img src="/data/ddragon/${ver}/img/champion/${CHAMPS.byId[String(c.championId)]}.png" alt="${nm}" onerror="this.style.display='none'">`
      : "?";
    const lockCls = c.completed ? "locked" : "hovering";
    return `<div class="csv-duo-cell ${lockCls}${isMe ? " is-me" : ""}">
      <div class="csv-duo-cell-icon">${img}</div>
      <div class="csv-duo-cell-tag">${isMe ? "ME" : "DUO"}</div>
      <div class="csv-duo-cell-name">${nm}</div>
      <div class="csv-duo-cell-summ">${(c.summonerName || "").slice(0, 22) || "—"}</div>
    </div>`;
  };

  const aug = cs.augments || {};
  const slots = Array.isArray(aug.my_slots) ? aug.my_slots : [];
  const curTier = aug.current_round || "silver";
  const slotHtml = ["silver", "gold", "prismatic"].map((tier) => {
    const s = slots.find((x) => x && x.tier === tier);
    const filled = !!(s && s.id);
    const isActive = tier === curTier;
    return `<div class="csv-augment-slot ${tier}${filled ? " filled" : ""}${isActive ? " is-active" : ""}">
      <div class="csv-augment-slot-grade">${tier.toUpperCase()}</div>
      <div class="csv-augment-slot-name">${filled ? s.name : (isActive ? "PICKING…" : "—")}</div>
    </div>`;
  }).join("");

  const options = Array.isArray(aug.options) ? aug.options : [];
  const optionsHtml = options.length
    ? options.map((o) => `
        <div class="csv-augment-option is-clickable ${o.tier || ""}" data-augment-id="${o.id}" data-augment-name="${o.name}">
          <div class="csv-augment-option-name">${o.name}</div>
          <div class="csv-augment-option-blurb">${o.blurb || ""}</div>
        </div>`).join("")
    : '<div class="csv-empty">no augment options yet</div>';

  return `
    <div class="csv-duo-row">
      ${cellHtml(me, true)}
      ${cellHtml(partner, false)}
    </div>
    <div class="csv-augments">
      <div class="csv-augments-title">My augments</div>
      <div class="csv-augment-slots">${slotHtml}</div>
    </div>
    <div class="csv-augment-options">
      <div class="csv-augments-title">${curTier.toUpperCase()} round · pick one</div>
      ${optionsHtml}
    </div>`;
}

function _csvWireArenaAugments(scope, cs) {
  scope.querySelectorAll(".csv-augment-option.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      const id = parseInt(cell.dataset.augmentId, 10);
      if (!id) return;
      // Mark selected (visual only — LCU push is Phase B once we have
      // the right LCU verb / payload schema for arena augments).
      scope.querySelectorAll(".csv-augment-option").forEach((c) =>
        c.classList.toggle("is-selected", c === cell));
      lcuCmd({ cmd: "set_augment_intent", augment_id: id });
    });
  });
}

// Arena enemies: 3 sub-team cards stacked vertically inside the enemies
// column. Each sub-team shows its 2 champion cells side-by-side.
function _csvRenderEnemiesArena(cs, timerEndMs) {
  const list = document.getElementById("csv-enemies-list");
  if (!list) return;
  list.innerHTML = "";
  const teams = (cs && Array.isArray(cs.arena_teams)) ? cs.arena_teams : [];
  const others = teams.filter((t) => t && !t.is_me).slice(0, 3);
  while (others.length < 3) others.push(null);
  const ver = CHAMPS.version || "latest";
  others.forEach((t, idx) => {
    const li = document.createElement("li");
    li.className = "csv-arena-team";
    const label = (t && t.label) || `TEAM ${idx + 2}`;
    const cells = (t && Array.isArray(t.cells)) ? t.cells.slice(0, 2) : [];
    while (cells.length < 2) cells.push(null);
    const cellsHtml = cells.map((c) => {
      if (!c || !c.championId) {
        return `<div class="csv-arena-cell is-empty">
          <div class="csv-arena-cell-icon">?</div>
          <div class="csv-arena-cell-name">—</div>
        </div>`;
      }
      const nm = _csChampName(c.championId) || ("cid:" + c.championId);
      const img = CHAMPS.byId[String(c.championId)]
        ? `<img src="/data/ddragon/${ver}/img/champion/${CHAMPS.byId[String(c.championId)]}.png" alt="${nm}" onerror="this.style.display='none'">`
        : "?";
      let lockHtml = "";
      if (c.completed) {
        lockHtml = '<span class="csv-arena-cell-lock">🔒</span>';
      } else if (timerEndMs) {
        const secs = Math.max(0, Math.ceil((timerEndMs - Date.now()) / 1000));
        lockHtml = `<span class="csv-arena-cell-timer" data-end="${timerEndMs}">${secs}</span>`;
      }
      const stateCls = c.completed ? "locked" : "hovering";
      return `<div class="csv-arena-cell ${stateCls}">
        <div class="csv-arena-cell-icon">${img}</div>
        <div class="csv-arena-cell-mark">${lockHtml}</div>
        <div class="csv-arena-cell-name">${nm}</div>
      </div>`;
    }).join("");
    li.innerHTML = `
      <div class="csv-arena-team-head">${label}</div>
      <div class="csv-arena-team-row">${cellsHtml}</div>`;
    list.appendChild(li);
  });
}

// Live countdown tick — updates the red ".csv-team-cell-timer" text
// every 250ms based on each element's data-end timestamp. Locked
// cells (green padlock) have no data-end so they're skipped.
let _csvTimerIntervalActive = false;
function _csvSetupTimerTick() {
  if (_csvTimerIntervalActive) return;
  _csvTimerIntervalActive = true;
  setInterval(() => {
    document.querySelectorAll(".csv-team-cell-timer[data-end]").forEach((el) => {
      const end = parseInt(el.dataset.end, 10);
      if (!end) return;
      const remaining = Math.max(0, end - Date.now());
      el.textContent = String(Math.ceil(remaining / 1000));
    });
  }, 250);
}

// Align summoner-name column with the "A" of the centered "Allies"
// header.
//
// Strategy: canvas measureText() — DOM-based measurement (Range API,
// inline span, cloned head off-screen) all gave wrong values across
// attempts (returning end-of-text or end-of-line positions, likely
// browser-specific quirks). Canvas is text-only, no layout quirks.
// We manually apply text-transform and letter-spacing since canvas
// doesn't honor those CSS properties on its own.
const _csvCanvas =
  (typeof document !== "undefined") ? document.createElement("canvas") : null;
function _csvMeasureText(text, cs) {
  if (!_csvCanvas) return 0;
  const ctx = _csvCanvas.getContext("2d");
  // Apply CSS text-transform manually (canvas ignores it).
  const tt = cs.textTransform;
  let s = text;
  if (tt === "uppercase") s = s.toUpperCase();
  else if (tt === "lowercase") s = s.toLowerCase();
  else if (tt === "capitalize") {
    s = s.replace(/\b\w/g, (c) => c.toUpperCase());
  }
  ctx.font = (cs.fontStyle || "") + " " + (cs.fontWeight || "400") + " " +
             cs.fontSize + " " + cs.fontFamily;
  let w = ctx.measureText(s).width;
  // Letter-spacing adds (n-1) gaps; canvas doesn't apply it.
  const ls = parseFloat(cs.letterSpacing) || 0;
  if (ls && s.length > 1) w += ls * (s.length - 1);
  return w;
}

function _csvAlignAllies() {
  const card = document.querySelector(".csv-card-allies");
  const head = card && card.querySelector(".csv-card-head");
  if (!card || !head) return;
  const headRect = head.getBoundingClientRect();
  if (!headRect.width) return;
  const text = (head.textContent || "").trim();
  if (!text) return;
  const cs = getComputedStyle(head);
  const textWidth = _csvMeasureText(text, cs);
  if (!textWidth) return;
  const padL = parseFloat(cs.paddingLeft) || 0;
  const padR = parseFloat(cs.paddingRight) || 0;
  const innerW = headRect.width - padL - padR;
  const aLeftAbs = headRect.left + padL + (innerW - textWidth) / 2;
  const cardRect = card.getBoundingClientRect();
  const aFromCardLeft = aLeftAbs - cardRect.left;
  // Summ col left from card outer edge:
  //   card border (1) + card padding-left (10) + cell border (1)
  //   + cell padding-left (6) + icon-col (36) + gap (8)
  //   + champname-col + gap (8) = 70 + col
  const champnameCol = Math.max(60, Math.round(aFromCardLeft - 70));
  card.style.setProperty("--csv-champname-col", champnameCol + "px");
}

// ── Pick & Ban Recommendations (s164 scaffold) ─────────────────────
// Layout: role chip + 3 pick-rows (performance / mastery / meta) each
// with [icon+name | reason | 3 ban suggestions] + mood toggle.
// Real data wiring (perf scoring from rewind_history.db, mastery from
// LCU, counter matrix, 500ms blocker poll, mode-conditional behavior)
// is Phase B. This stub uses hardcoded placeholders so the operator
// can review the visual scaffold before backend integration.

const _ROLE_FROM_LCU = {
  TOP: "TOP", JUNGLE: "JNG", MIDDLE: "MID",
  BOTTOM: "BOT", UTILITY: "SUP",
};

function _csvResolveRole(cs) {
  // Mode-specific labels for non-SR queues.
  if (cs.queue_id === 1700 || cs.queue_id === 1710) return "ARENA";
  if (cs.queue_id === 450) return "ARAM";
  if (cs.queue_id === 920) return "MAYHEM";
  // SR: read assignedPosition from my local cell.
  const myCell = cs.local_cell;
  const me = (cs.my_team || []).find((p) => p && p.cellId === myCell);
  const pos = (me && me.assignedPosition) || "";
  return _ROLE_FROM_LCU[pos.toUpperCase()] || "—";
}

// Placeholder pick/ban data per role. Phase B replaces this with
// computed values from rewind_history.db + counter matrix + LCU mastery.
const _PB_PLACEHOLDERS = {
  BOT: {
    performance: {
      champId: 51, champName: "Caitlyn",
      reason: "62% WR · 14 BOT games · early lane-bully matchups favor you",
      bans: [
        { champId: 119, name: "Draven",  pct: 78 },
        { champId: 236, name: "Lucian",  pct: 64 },
        { champId: 555, name: "Pyke",    pct: 71 },
      ],
    },
    mastery: {
      champId: 67, champName: "Vayne",
      reason: "M8 · 388k pts · 47 ranked games · highest mastery on role",
      bans: [
        { champId: 51,  name: "Caitlyn", pct: 81 },
        { champId: 81,  name: "Ezreal",  pct: 58 },
        { champId: 53,  name: "Overlay App E",   pct: 76 },
      ],
    },
    meta: {
      champId: 145, champName: "Kai'Sa",
      reason: "S+ tier ADC this patch · 53% global WR · scales well vs comp",
      bans: [
        { champId: 15,  name: "Sivir",   pct: 72 },
        { champId: 222, name: "Jinx",    pct: 61 },
        { champId: 89,  name: "Leona",   pct: 69 },
      ],
    },
  },
  // Other roles inherit BOT placeholders until backend lands.
};

function _pbPlaceholdersFor(role) {
  return _PB_PLACEHOLDERS[role] || _PB_PLACEHOLDERS.BOT;
}

function _csvMoodGet() {
  try { return sessionStorage.getItem("csv-mood") || "comfort"; }
  catch (_) { return "comfort"; }
}
function _csvMoodSet(v) {
  try { sessionStorage.setItem("csv-mood", v); } catch (_) {}
}

// s170 item #4: live pick&ban recommendations from
// /api/champ-select/pickban-recs. Cached per (role, queue_id) and
// refreshed at most every 60s — operator history isn't changing
// during a single champ-select session, so this is just an in-memory
// dedupe to keep the panel responsive.
const _CSV_PB_CACHE = {};   // {`${role}|${queue}`: {data, fetchedAt}}
const _CSV_PB_INFLIGHT = {};
const _CSV_PB_TTL_MS = 60_000;

function _csvFetchPickBanRecs(role, queueId, onLoad) {
  // Role here is the dashboard form ("BOT"/"JNG"/etc.) — the endpoint
  // accepts both forms via its _ROLE_ALIASES map.
  if (!role || role === "—") return null;
  const cacheKey = `${role}|${queueId || 0}`;
  const now = Date.now();
  const cached = _CSV_PB_CACHE[cacheKey];
  if (cached && (now - cached.fetchedAt) < _CSV_PB_TTL_MS) {
    return cached.data;
  }
  if (_CSV_PB_INFLIGHT[cacheKey]) return cached ? cached.data : null;
  _CSV_PB_INFLIGHT[cacheKey] = true;
  const url = `/api/champ-select/pickban-recs?role=${encodeURIComponent(role)}`
            + (queueId ? `&queue=${queueId}` : "");
  fetch(url)
    .then((r) => r.ok ? r.json() : null)
    .then((j) => {
      _CSV_PB_INFLIGHT[cacheKey] = false;
      if (j && j.ok) {
        _CSV_PB_CACHE[cacheKey] = { data: j, fetchedAt: Date.now() };
        if (typeof onLoad === "function") onLoad();
      }
    })
    .catch(() => { _CSV_PB_INFLIGHT[cacheKey] = false; });
  return cached ? cached.data : null;
}

function _csvMergePickBanData(role, liveRecs, placeholder) {
  // Layer live performance over placeholder mastery/meta. When the
  // live performance row is missing (operator has no SR history at
  // this role), keep the placeholder so the panel doesn't go blank.
  const out = {
    performance: placeholder.performance,
    mastery:     placeholder.mastery,
    meta:        placeholder.meta,
  };
  if (liveRecs && liveRecs.performance) {
    const p = liveRecs.performance;
    out.performance = {
      champId:   p.champId,
      champName: p.champName,
      reason:    p.reason,
      bans:      (liveRecs.performance_bans || placeholder.performance.bans).map((b) => ({
        champId: b.champId,
        name:    b.name,
        pct:     b.pct,
      })),
    };
    // Backfill bans from placeholder if live returned fewer than 3.
    while (out.performance.bans.length < 3 && placeholder.performance.bans[out.performance.bans.length]) {
      out.performance.bans.push(placeholder.performance.bans[out.performance.bans.length]);
    }
  }
  return out;
}

function _csvRenderPickBan(cs, myCid) {
  const body = document.getElementById("csv-pickban-body");
  if (!body) return;
  if (!cs) {
    body.innerHTML = '<div class="csv-empty">waiting for champ-select data…</div>';
    return;
  }
  const role = _csvResolveRole(cs);
  const ver = CHAMPS.version || "latest";
  const ph = _pbPlaceholdersFor(role);
  // s170 item #4: fetch live recs (cached). Re-renders this panel when
  // the fetch lands so the user sees the swap from placeholder → live.
  const liveRecs = _csvFetchPickBanRecs(role, cs.queue_id, () => {
    _csvRenderPickBan(cs, myCid);
  });
  const merged = _csvMergePickBanData(role, liveRecs, ph);
  const sources = [
    { key: "performance", label: "Performance", data: merged.performance },
    { key: "mastery",     label: "Mastery",     data: merged.mastery },
    { key: "meta",        label: "Meta",        data: merged.meta },
  ];
  // Pick clicks are safe whenever we're past the ban phase (phase
  // FINALIZATION) or the user has already locked their pick. Disabling
  // during active BAN_PICK avoids the "accidentally banned my own
  // champ" trap the operator flagged.
  const pickClickEnabled = cs.phase === "FINALIZATION" || cs.my_completed === true;

  const champImg = (cid) =>
    cid && CHAMPS.byId[String(cid)]
      ? `<img src="/data/ddragon/${ver}/img/champion/${CHAMPS.byId[String(cid)]}.png" onerror="this.style.display='none'" alt="">`
      : "?";

  // Role row column-header strip: PICK on the left and BAN on the
  // right. Operator removed the centered ROLE chip — the user's role
  // is already shown on their ally row (gold "BOT" pip), so the
  // duplicate chip here was redundant.
  let html = `
    <div class="csv-pb-role-row">
      <div class="csv-pb-pick-header">PICK</div>
      <div class="csv-pb-bans-header-slot">
        <div class="csv-pb-bans-header">BAN</div>
      </div>
    </div>`;

  sources.forEach((src) => {
    const d = src.data;
    const banCells = d.bans.map((b, i) => {
      const role3 = ["counter", "struggle", "terror"][i] || "";
      const isSelected = (_csvSelection.ban === b.champId);
      // Once a ban is locked, every OTHER ban becomes disabled so the
      // operator can't switch their committed ban.
      const isDisabled = _csvSelection.banLocked && !isSelected;
      const banCls = "csv-pb-ban is-clickable"
                   + (isSelected ? " is-selected" : "")
                   + (isDisabled ? " is-disabled" : "");
      return `
        <div class="${banCls}" data-ban-id="${b.champId}" data-ban-name="${b.name}" title="${role3} ban candidate">
          <span class="csv-pb-ban-pct">${b.pct}%</span>
          <div class="csv-pb-ban-icon">${champImg(b.champId)}</div>
          <div class="csv-pb-ban-name">${b.name}</div>
        </div>`;
    }).join("");
    const isPickSelected = pickClickEnabled && _csvSelection.pick === d.champId;
    const isPickDisabled = pickClickEnabled && _csvSelection.pickLocked && !isPickSelected;
    const pickIconCls = pickClickEnabled
      ? "csv-pb-pick-icon is-clickable"
        + (isPickSelected ? " is-selected" : "")
        + (isPickDisabled ? " is-disabled" : "")
      : "csv-pb-pick-icon";
    const pickDataAttr = pickClickEnabled ? ` data-pick-id="${d.champId}" data-pick-name="${d.champName}"` : "";
    html += `
      <div class="csv-pb-pick-row" data-source="${src.key}">
        <div class="csv-pb-pick-col">
          <div class="${pickIconCls}"${pickDataAttr}>${champImg(d.champId)}</div>
          <div class="csv-pb-pick-name">${d.champName}</div>
        </div>
        <div class="csv-pb-reason-col">
          <div class="csv-pb-source-label">${src.label.toUpperCase()}</div>
          <div class="csv-pb-reason-text">${d.reason}</div>
        </div>
        <div class="csv-pb-bans-col">${banCells}</div>
      </div>`;
  });

  const mood = _csvMoodGet();
  // Each button now stacks two spans for the 2-line layout the
  // operator asked for (frees horizontal space for the 4th button).
  const moodBtn = (k, l1, l2) =>
    `<button class="csv-pb-mood-btn${mood === k ? " is-active" : ""}" data-mood="${k}">` +
    `<span>${l1}</span><span>${l2}</span></button>`;
  html += `
    <div class="csv-pb-mood-row">
      <span class="csv-pb-mood-label"><span>PICK</span><span>ONE</span></span>
      ${moodBtn("comfort", "Comfort", "Pick")}
      ${moodBtn("limit",   "Limit",   "Test")}
      ${moodBtn("new",     "Something", "New")}
      ${moodBtn("synergy", "Comp",    "Synergy")}
    </div>`;

  body.innerHTML = html;

  // Wire mood toggle (event delegation; idempotent on re-render since
  // we replace innerHTML each time and re-attach).
  body.querySelectorAll(".csv-pb-mood-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const m = btn.dataset.mood;
      if (!m) return;
      _csvMoodSet(m);
      body.querySelectorAll(".csv-pb-mood-btn").forEach((b) =>
        b.classList.toggle("is-active", b.dataset.mood === m));
    });
  });
  // Ban quick-select: click any non-disabled ban icon → set ban intent.
  // Once one is clicked, the others become disabled (lock); the chosen
  // one keeps its red border via .is-selected.
  body.querySelectorAll(".csv-pb-ban.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      if (cell.classList.contains("is-disabled")) return;
      if (_csvSelection.banLocked) return;
      const cid = parseInt(cell.dataset.banId, 10);
      body.querySelectorAll(".csv-pb-ban").forEach((el) => {
        el.classList.toggle("is-selected", el === cell);
        el.classList.toggle("is-disabled", el !== cell);
      });
      _csvOnBanSelect(cid);
    });
  });
  // Pick quick-select: click the recommended pick icon → set pick
  // intent. Locks subsequent pick changes (operator: "once locked
  // don't allow the border to be changed to another champion").
  body.querySelectorAll(".csv-pb-pick-icon.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      if (cell.classList.contains("is-disabled")) return;
      if (_csvSelection.pickLocked) return;
      const cid = parseInt(cell.dataset.pickId, 10);
      body.querySelectorAll(".csv-pb-pick-icon").forEach((el) => {
        el.classList.toggle("is-selected", el === cell);
        el.classList.toggle("is-disabled", el !== cell);
      });
      _csvOnPickSelect(cid);
    });
  });
}

export { handleChampSelect, renderChampSelectPanel, renderChampSelectCoach };
