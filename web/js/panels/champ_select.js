// Champ Select panel — full-page view rendered during ChampSelect
// phase: pick&ban + build chooser + SR Draft Theatre + analyzer.
// _ib* functions live in item_build.js (avoid circular dep).
import { el, safe, fmtList, isArenaPayload } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, CHAMPS, _normItemName, _resolveItemId, _resolveChampId } from '../lib/items_index.js';
import { scorerUnit } from '../lib/scorer_units.js';
import { sumImg, sumName } from '../lib/summoner_spells.js';
import { itemTooltipHtml, keystoneTooltipHtml, preloadLolDescriptions } from '../lib/lol_descriptions.js';
import { championTags, preloadChampionTags } from '../lib/champion_tags.js';
import {
  _ibPushItems, _ibFetchAndRender, _ibSetStatus,
  _ibRenderRows, _ibMarkSelectedRow, _ibSaveChoice,
} from './item_build.js';

// ── LCU command helper (used by champ-select + build chooser) ──────
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

function _csApplyLoadout(champion, variant, mode) {
  if (!champion || !variant) return;
  const key = champion + "|" + mode + "|" + variant;
  if (key === _csLoadout.lastAppliedKey) return;  // already pushed
  if (_csLoadout.inflight) return;
  _csLoadout.inflight = true;
  _csSetStatus("pushing…", "busy");
  fetch("/api/loadout/apply", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      champion: champion, variant: variant, mode: mode,
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
      // Persist this pre-game choice so the in-game build chooser
      // (renderItemBuild → _ibMaybeRenderBuilds) can pre-select it.
      try { localStorage.setItem("rc-ingame-build-" + champion, variant); }
      catch (_) {}
      const queued = (data.queued || []).join(", ") || "nothing";
      _csSetStatus("✓ pushed: " + queued, "ok");
      _csMarkSelectedRow(variant);
      // Clear the OK flash after a few seconds
      setTimeout(() => {
        if (_csLoadout.lastAppliedKey === key) _csSetStatus("✓ active: " + (data.label || variant), "ok");
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

// 2026-04-25: Cold-start champ-select coaching. When LCU phase is
// ChampSelect and we have a locked-in champion + enemy team, surface
// the user's historical adaptation data BEFORE the game starts.
// Resolves championId integers to names via the CHAMPS byId index.
const _CS_LIVE = { lastKey: "", inflight: false, lastFetch: 0, lastResult: null };

function handleChampSelect(lcu) {
  // s162: cache the LCU snapshot on state.latest so view-lobby's
  // _lobbyViewRefresh (which reads state.latest.lcu) sees the same data
  // as the new champ-select view. Pre-fix the lobby sub-page rendered
  // empty in production because no upstream path ever assigned
  // state.latest.lcu.
  state.latest.lcu = lcu || null;
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
// Top-level <section id="view-champ-select"> page rendered while
// lcu.phase === "ChampSelect". Auto-promoted by main.js's view router.

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
// s212 v6: dropped the banLocked / pickLocked gates. Pre-s212v6 the
// first click committed and disabled the other 2 cells in the row,
// modeling "one-time intent". Operator's new flow: every click fires
// `set_ban_intent` / `set_pick_intent` to LCU; the agent itself
// decides whether to accept the change. Dashboard tracks only the
// latest clicked id for `.is-selected` highlight purposes.
const _csvSelection = { ban: 0, pick: 0 };
function _csvOnBanSelect(championId) {
  if (!championId) return;
  _csvSelection.ban = championId;
  _csvFireCmd({ cmd: "set_ban_intent", championId: championId });
}
function _csvOnPickSelect(championId) {
  if (!championId) return;
  _csvSelection.pick = championId;
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
// default; ARAM (450/920), Arena (1700/1710) get distinct central +
// enemies layouts because the LCU surface they expose differs
// structurally — ARAM has a bench but no roles/bans, Arena has 2v2v2v2
// + augments and no enemy-team field. s214 v2: Brawl mode retired from
// the live League rotation; brawl branches dropped from this classifier.
function _csvDetectMode(cs) {
  if (!cs) return "sr";
  const q = (cs.queue_id | 0);
  if (q === 1700 || q === 1710) return "arena";
  if (cs.is_aram || q === 450 || q === 920) return "aram";
  return "sr";
}

// s209: queue_id → human label for the CS sub-line. Mirrors the agent's
// `_LOBBY_QUEUE_NAMES` map in tools/gamepc_lcu_agent.py:205 — the agent
// forwards `queue_name` on the lobby envelope but not the champ-select
// envelope, so the dashboard needs its own local mapping. Unknown IDs
// fall through to "queue <N>" for visibility.
const _CSV_QUEUE_NAMES = {
  400:  "Normal Draft",
  420:  "Ranked Solo/Duo",
  430:  "Normal Blind",
  440:  "Ranked Flex",
  450:  "ARAM",
  480:  "Swiftplay",
  490:  "Quickplay",
  700:  "Clash",
  900:  "URF",
  920:  "ARAM Mayhem",
  1020: "One for All",
  1300: "Nexus Blitz",
  1400: "Ultimate Spellbook",
  1700: "Arena",
  1710: "Arena",
};
function _csvQueueLabel(queueId) {
  const q = queueId | 0;
  return _CSV_QUEUE_NAMES[q] || (q ? "queue " + q : "");
}

// s209: rune-tree icon paths. Files live at data/icons/runes/<slug>.png
// and ride the numeric-prefix convention DDragon ships them with. The
// "Whimsy" file is Riot's Arena-tier rebrand of the Inspiration tree —
// it's the only Inspiration art the icon set carries.
const _CSV_RUNE_TREE_FILES = {
  Precision:   "7201_Precision",
  Domination:  "7200_Domination",
  Sorcery:     "7202_Sorcery",
  Resolve:     "7204_Resolve",
  Inspiration: "7203_Whimsy",
};
function _csvTreeIcon(treeName) {
  const slug = _CSV_RUNE_TREE_FILES[String(treeName || "").trim()];
  return slug ? `/icons/runes/${slug}.png` : "";
}
// Keystone slug overrides for keystones whose icon filename doesn't
// match the TitleCase-no-spaces derivation. Riot has shipped a couple
// of mid-rebrand assets with "Temp" / "Veteran" prefixes that haven't
// been renamed back. Keep this map small — add entries only when a
// concrete file mismatch is observed.
const _CSV_KEYSTONE_SLUG_OVERRIDES = {
  "Lethal Tempo": "LethalTempoTemp",
  "Aftershock":   "VeteranAftershock",
};
// Keystone slug — TitleCase each word + strip spaces. ("Press the Attack"
// → "PressTheAttack", "Grasp of the Undying" → "GraspOfTheUndying").
// Matches the file naming convention in data/icons/runes/.
function _csvKeystoneIcon(keystoneName) {
  const raw = String(keystoneName || "").trim();
  if (!raw) return "";
  if (_CSV_KEYSTONE_SLUG_OVERRIDES[raw]) {
    return `/icons/runes/${_CSV_KEYSTONE_SLUG_OVERRIDES[raw]}.png`;
  }
  const slug = raw
    .split(/\s+/)
    .map((w) => w ? w[0].toUpperCase() + w.slice(1).toLowerCase() : "")
    .join("")
    .replace(/[^A-Za-z0-9]/g, "");
  return slug ? `/icons/runes/${slug}.png` : "";
}

// s209: LCU's `cs.phase` is shouty-snake-case ("BAN_PICK", "FINALIZATION",
// "GAME_STARTING"). Convert to Title Case with spaces for the sub-line.
// Unknown phases fall through as-is so anything new lands legibly.
const _CSV_PHASE_LABELS = {
  PLANNING:      "Planning",
  BAN_PICK:      "Ban & Pick",
  FINALIZATION: "Finalizing",
  GAME_STARTING: "Starting",
};
function _csvHumanPhase(phase) {
  if (!phase) return "";
  const upper = String(phase).toUpperCase();
  if (_CSV_PHASE_LABELS[upper]) return _CSV_PHASE_LABELS[upper];
  return upper.replace(/_/g, " ").toLowerCase()
              .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Renders a team cell list. Backward-compatible 5-positional signature
// — the 6th `opts` arg adds mode-aware behavior: `cellCount` (default
// 5), `showGuess` (default true for enemy lists), and `allowRolePip`
// (default true). ARAM passes `showGuess: false` since roles are
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

    // s213 v2: lock icon (🔒) removed per operator. The cell's overall
    // outline already encodes lock state (green border for locked,
    // amber for hovering) so the per-cell padlock was redundant.
    // s214: countdown timer also removed for allies + enemies — same
    // signal already lives in the global champ-select header timer +
    // the active-round border indicator. Per-cell timer added too
    // much visual noise without a unique payload.
    const lockHtml = "";

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
    // s213 v2: enemy cells now carry a 2-piece comp identifier + role
    // confidence instead of the bare "(guess)" tag. Pulls tags from
    // /api/dictionary/champion-tags (DDragon info + curated CC/burst
    // sets). Confidence is derived from LCU state: 100% if locked,
    // 85% if assignedPosition is present but not committed, 50% if
    // LCU hasn't classified the cell yet. Renders BEFORE the role pip
    // in the cell so the visual reading order is: champ → tags → role.
    if (isEnemyList && cid && showGuess) {
      const champTags = championTags(champNm);
      if (champTags && Array.isArray(champTags.tags) && champTags.tags.length) {
        const tagsEl = document.createElement("span");
        tagsEl.className = "csv-team-cell-tags";
        tagsEl.innerHTML = champTags.tags.slice(0, 2)
          .map((t) => `<span class="csv-team-cell-tag csv-team-cell-tag--${t.toLowerCase()}">${t}</span>`)
          .join("");
        li.appendChild(tagsEl);
      }
      // Confidence pill: 100% when locked, 85% when LCU assigned a
      // position but the pick isn't committed, 50% otherwise.
      const confPct = (p && p.completed) ? 100 : (pos ? 85 : 50);
      const confEl = document.createElement("span");
      confEl.className = "csv-team-cell-confidence";
      if (confPct >= 95) confEl.classList.add("is-high");
      else if (confPct >= 80) confEl.classList.add("is-med");
      else confEl.classList.add("is-low");
      confEl.textContent = `${confPct}%`;
      confEl.title = (confPct >= 95) ? "champion locked — role confirmed"
                    : (confPct >= 80) ? "LCU role guess — pick not yet committed"
                    : "no role assigned yet";
      li.appendChild(confEl);
    }
    list.appendChild(li);
  });
}

export function renderChampSelectView(lcu) {
  // Section may not exist yet on older cached HTML — bail out cleanly.
  const section = document.getElementById("view-champ-select");
  const grid = section && section.querySelector(".csv-grid");
  if (!grid) return;
  // s213: warm the DDragon item + rune description caches on first
  // mount so the first hover already has tooltip content ready.
  // Idempotent — subsequent calls are no-ops once cache is ready.
  preloadLolDescriptions();
  // s213 v2: warm champion-tags cache for the enemies-panel 2-piece
  // identifier + confidence pill.
  preloadChampionTags();
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

  // s209 v2: idempotent render gate. The state envelope re-fires every
  // 2s in live, and the sim FakeSocket tick re-fires every 3s — each
  // tick triggers a full renderChampSelectView which rebuilds three
  // panels worth of innerHTML. The operator saw the build chooser
  // flicker every ~3s on cold load. Skip the render when nothing
  // observable has changed since the last tick.
  const sig = _csvComputeSig(cs, mode, myCid, myName);
  if (section.dataset.csvSig === sig) return;
  section.dataset.csvSig = sig;

  // Stamp the section with data-cs-mode so CSS can branch (hide
  // pickban panel for non-SR, swap enemies/allies layout for Arena,
  // adjust grid template, etc).
  section.dataset.csMode = mode;

  // Sub-line: mode + queue + inner phase + timer.
  // s209: humanize the LCU phase enum ("BAN_PICK" → "Ban & Pick",
  // "FINALIZATION" → "Finalization", etc.). Raw shouty-snake-case
  // looked like a debug log line in the live sub-line.
  const bits = [];
  const modeLabel = { sr: "SR DRAFT", aram: "ARAM", arena: "ARENA" }[mode] || "";
  if (modeLabel) bits.push(modeLabel);
  if (cs.queue_id) bits.push(_csvQueueLabel(cs.queue_id));
  if (cs.phase) bits.push(_csvHumanPhase(cs.phase));
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
  // structural (SR draft queues). ARAM/Arena don't have a meaningful
  // pick order — operator wanted the middle button hidden.
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

  // Allies render — Arena renders only 2 cells (me + duo); SR/ARAM
  // render 5. ARAM also suppresses the (guess) tag and role pip since
  // there are no role assignments to display.
  const allyOpts = (mode === "arena")
    ? { cellCount: 2, showGuess: false, allowRolePip: false }
    : (mode === "aram")
      ? { cellCount: 5, showGuess: false, allowRolePip: false }
      : { cellCount: 5, showGuess: true,  allowRolePip: true };
  _csvRenderTeam("csv-allies-list", cs.my_team, myCid, timerEndMs, showPickOrder, allyOpts);

  // Enemies render — Arena uses a dedicated 3-team layout (3 enemy
  // duos stacked vertically). SR keeps the 5-cell list with (guess);
  // ARAM renders 5 cells but suppresses (guess) + role pip.
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
  // s210: render the new Suggestions panel (row 2 right). Has its own
  // fetch path for ban-suggestions; pick-order + DS items pull from
  // local state. SR-only — the panel is hidden on ARAM/Arena via CSS
  // (no bans, no pick order, no DS-engine concept of "next").
  if (mode === "sr") {
    _csvRenderSuggestions(cs, myCid, myName, mode);
  } else {
    const sbg = document.getElementById("csv-sugg-bans-grid");
    if (sbg) sbg.innerHTML = '<div class="csv-sugg-empty">non-SR mode</div>';
    const sib = document.getElementById("csv-sugg-items-body");
    if (sib) sib.innerHTML = '<div class="csv-sugg-empty">non-SR mode</div>';
    const spo = document.getElementById("csv-sugg-pickorder-body");
    if (spo) spo.innerHTML = '<div class="csv-sugg-empty">non-SR mode</div>';
  }

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
// per mode without leaving stale elements behind. SR/ARAM get a build
// chooser variant list; Arena gets the duo header + augments.
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
  // Phase 3 (s176): trigger an async fetch for the persisted pick so the
  // picker re-renders with overridden state once the server replies.
  // No-op if already cached / inflight. Renders synchronously below.
  if (myName) _csvFetchArchetype(myName);
  const archetypeHtml = _csvArchetypePickerHtml(myName);
  const variants = _csvBuildVariantsFor(myCid, myName, mode, cs);
  const buildsTitle = mode === "aram" ? "ARAM build chooser"
                    : mode === "arena" ? "Arena build chooser"
                    : "SR build chooser";
  const buildsHtml = `
    <div class="csv-builds" data-champion="${myName || ""}" data-mode="${mode || "sr"}">
      <div class="csv-builds-title">${buildsTitle}</div>
      <div class="csv-builds-body" id="csv-builds-body">
        ${_csvBuildVariantRowsHtml(variants, _csvSavedChoice(myName))}
      </div>
    </div>`;

  // s214 v2: LOCKED state sits to the LEFT of the champion icon now
  // (per operator follow-up). Pre-s214v2 it was centered below; pre-
  // s214 it was inline-right inside .csv-mypick-text. New layout:
  //   [LOCKED state] [icon] [name]
  // The state column is fixed-width so the icon stays in roughly the
  // same X position whether locked / hovering / empty.
  body.className = "csv-card-body csv-mypick";
  body.innerHTML = `
    <div class="csv-mypick-portrait-row">
      <div class="csv-mypick-state ${stateCls}" id="csv-mypick-state">${stateTxt}</div>
      <div class="csv-mypick-icon ${iconCls}" id="csv-mypick-icon">${iconHtml}</div>
      <div class="csv-mypick-text">
        <div class="csv-mypick-name" id="csv-mypick-name">${myName}</div>
      </div>
    </div>
    ${lockBtnHtml}
    ${extraHtml}
    ${archetypeHtml}
    ${buildsHtml}`;

  // Wire bench cells to fire bench_swap on click. Only ARAM renders
  // the bench block; the wiring is idempotent under re-render since
  // we replace innerHTML and re-attach each tick.
  if (mode === "aram") _csvWireBench(body);
  _csvWireBuildVariants(body);
  _csvWireLockButton(body);
  _csvWireArchetypePicker(body);
}

// s210: Suggestions panel renderer (row 2 right).
//   Row 1 (header)         → static "Suggestions" from .csv-card-head
//   Row 2 (bans grid)      → 4 cards, top globally-banned, filtered by
//                            already-banned from either team
//   Row 3 (pick order)     → static lane-based advisory for the operator's
//                            assigned role (jungle picks 2nd-last, ADC
//                            picks last, etc.). Future: dynamic based on
//                            counter-pick implications.
//   Row 4 (DS items)       → DS engine top-6 for the operator's champion;
//                            mirrors what the build chooser used to show
//                            as the "DS engine top picks" pseudo-row.
function _csvRenderSuggestions(cs, myCid, myName, mode) {
  // ---- Row 2: bans block ----
  // Phase-aware: during the ban phase show 4 suggested bans for the
  // operator to commit; once active_round.type === "pick" (bans
  // committed, picks underway) switch to a 2-row 5-cell grid showing
  // ally bans (top) + enemy bans (bottom).
  // s214: title row dropped — `.csv-sugg-row-label` no longer in the
  // DOM. The grid alone communicates state via the ALLY / ENEMY side
  // labels in the banned-list rows + the icon strip in suggestion mode.
  const bansGrid = document.getElementById("csv-sugg-bans-grid");
  if (bansGrid) {
    const allyBans  = (cs.bans && Array.isArray(cs.bans.my_team)) ? cs.bans.my_team : [];
    const enemyBans = (cs.bans && Array.isArray(cs.bans.their_team)) ? cs.bans.their_team : [];
    const isPickPhase = !!(cs.active_round && cs.active_round.type === "pick")
                       || (cs.phase && cs.phase !== "BAN_PICK" && cs.phase !== "PLANNING");
    if (isPickPhase && (allyBans.length || enemyBans.length)) {
      bansGrid.classList.add("is-banned-grid");
      bansGrid.classList.remove("is-suggestions-grid");
      bansGrid.innerHTML = _csvBannedListRow(allyBans, "ALLY")
                         + _csvBannedListRow(enemyBans, "ENEMY");
    } else {
      bansGrid.classList.add("is-suggestions-grid");
      bansGrid.classList.remove("is-banned-grid");
      // Collect already-banned ids so the suggestion fetch can skip them.
      const banned = new Set();
      allyBans.forEach((id) => banned.add(id | 0));
      enemyBans.forEach((id) => banned.add(id | 0));
      const excludedIds = Array.from(banned).filter((x) => x > 0);
      _csvFetchBanSuggestions(excludedIds);
      const cached = _CSV_BANSUGG_CACHE[_csvBanSuggKey(excludedIds)];
      if (cached && Array.isArray(cached.suggestions) && cached.suggestions.length) {
        bansGrid.innerHTML = cached.suggestions.map((s) => {
          const isBanned = banned.has(s.champId);
          return `
            <div class="csv-sugg-ban-card${isBanned ? " is-banned" : ""}"
                 data-champ-id="${s.champId}"
                 title="${isBanned ? `${s.name} already banned` : `Suggest ban: ${s.name}`}">
              <div class="csv-sugg-ban-icon">
                <img src="${s.icon}" alt="${s.name}" onerror="this.style.display='none'">
              </div>
              <div class="csv-sugg-ban-name">${s.name}</div>
            </div>`;
        }).join("");
        bansGrid.querySelectorAll(".csv-sugg-ban-card:not(.is-banned)").forEach((card) => {
          card.addEventListener("click", () => {
            const cid = parseInt(card.dataset.champId, 10) | 0;
            if (cid > 0) lcuCmd({ cmd: "set_ban_intent", championId: cid });
          });
        });
      } else {
        bansGrid.innerHTML = '<div class="csv-sugg-empty">loading global top bans…</div>';
      }
    }
  }
  // ---- Row 3: pick-order tips (no header label per s213 v3) ----
  // Static advisory keyed on operator's assigned role. 3 tips per role
  // — the third row is the "consider" / strategic depth tip beyond
  // basic "pick after / pick first" logic.
  const pickOrderBody = document.getElementById("csv-sugg-pickorder-body");
  if (pickOrderBody) {
    const role = _csvResolveRole(cs);
    const tips = (_CSV_PICKORDER_TIPS[role] || _CSV_PICKORDER_TIPS.DEFAULT).slice();
    // s214: swap row 3 for a comp-aware tip once at least one ally lock
    // or enemy commit is visible. Static role tip is preserved as the
    // fallback when comp data is too thin to derive signal.
    const compTip = _csvCompAwareTip(cs, role);
    if (compTip) tips[2] = compTip;
    pickOrderBody.innerHTML = tips.map((tip, idx) => `
      <div class="csv-sugg-pickorder-cell">
        <span class="csv-sugg-pickorder-idx">${idx + 1}</span>
        <span>${tip}</span>
      </div>`).join("");
  }
  // s211: DS engine item output row removed — the Experimental build
  // chooser row now carries DS top picks in a richer rune+spell+item
  // layout, making the duplicate strip here visual noise.
}

// s213 v3: helper — render a single-row 5-cell banned-list strip for
// the Suggestions panel's post-ban-phase view. Banned ids come from
// LCU's cs.bans.my_team / cs.bans.their_team arrays. Pads to 5 cells
// with placeholder slots when fewer than 5 bans are committed (Riot
// draft modes vary: 3 bans/side classic, 5 bans/side ranked).
function _csvBannedListRow(banIds, sideLabel) {
  const cells = [];
  for (let i = 0; i < 5; i++) {
    const cid = banIds[i] | 0;
    if (cid > 0) {
      const champ = (CHAMPS && CHAMPS.byId && CHAMPS.byId[String(cid)]) || `cid:${cid}`;
      const img = _csChampImg(cid);
      cells.push(`
        <div class="csv-sugg-ban-card is-banned" data-champ-id="${cid}" title="${champ} banned">
          <div class="csv-sugg-ban-icon">
            ${img ? `<img src="${img}" alt="${champ}" onerror="this.style.display='none'">` : ""}
          </div>
          <div class="csv-sugg-ban-name">${champ}</div>
        </div>`);
    } else {
      cells.push(`
        <div class="csv-sugg-ban-card is-empty">
          <div class="csv-sugg-ban-icon"></div>
          <div class="csv-sugg-ban-name">—</div>
        </div>`);
    }
  }
  return `<div class="csv-sugg-banned-row"
               data-side="${sideLabel.toLowerCase()}">
            <span class="csv-sugg-banned-side">${sideLabel}</span>
            <div class="csv-sugg-banned-cells">${cells.join("")}</div>
          </div>`;
}

// s211: variant key → badge CSS class. Each known variant gets a
// distinct hue so the operator can read the row identity at a glance
// without a separate trailing tag. Unknown variant keys fall through
// to a neutral grey pill. Experimental's amber matches the pre-s211
// tag color (operator already learned that hue means "auto-built").
function _csvVariantBadgeClass(v) {
  if (v.is_experimental) return "csv-build-badge csv-build-badge-experimental";
  const key = (v.key || "").toLowerCase();
  if (key === "on-hit" || key === "onhit")  return "csv-build-badge csv-build-badge-onhit";
  if (key === "crit")                       return "csv-build-badge csv-build-badge-crit";
  if (key === "ap-burst" || key === "ap")   return "csv-build-badge csv-build-badge-ap";
  if (key === "tank" || key === "bruiser")  return "csv-build-badge csv-build-badge-tank";
  if (key === "lethality" || key.includes("lethality")
      || key === "lethality-poke")          return "csv-build-badge csv-build-badge-lethality";
  if (key === "adc-crit")                   return "csv-build-badge csv-build-badge-crit";
  if (key.startsWith("support") || key === "enchanter")
                                            return "csv-build-badge csv-build-badge-support";
  return "csv-build-badge csv-build-badge-default";
}

// s210 v2: archetype → (keystone, primary tree, secondary tree) for
// the experimental row's auto-built rune page. Mirrors the standard
// "default keystone per archetype" consensus — operator can refine
// per-champion later via a JSON override file. The keystone slug is
// converted to /icons/runes/<slug>.png via _csvKeystoneIcon().
const _CSV_EXPERIMENTAL_RUNES = {
  carry:     { keystone: "Lethal Tempo",  primary: "Precision",  secondary: "Domination"  },
  bruiser:   { keystone: "Conqueror",     primary: "Precision",  secondary: "Resolve"     },
  tank:      { keystone: "Aftershock",    primary: "Resolve",    secondary: "Inspiration" },
  mage:      { keystone: "Arcane Comet",  primary: "Sorcery",    secondary: "Inspiration" },
  assassin:  { keystone: "Electrocute",   primary: "Domination", secondary: "Precision"   },
  enchanter: { keystone: "Summon Aery",   primary: "Sorcery",    secondary: "Inspiration" },
};
function _csvExperimentalRunesFor(archetypeKey) {
  return _CSV_EXPERIMENTAL_RUNES[archetypeKey] || _CSV_EXPERIMENTAL_RUNES.carry;
}

// s210: pick-order advisory blurbs per role. Short tips, ordered from
// "what to do first" to "what to do at lock-in". s214: row 3 is now
// dynamically swapped for a comp-aware tip when ally + enemy comps
// have enough locks to read — see _csvCompAwareTip below. Rows 1+2
// stay static so the operator always sees the role's "pick order"
// constants regardless of comp readability.
const _CSV_PICKORDER_TIPS = {
  TOP: [
    "Counterpick — wait for enemy top lock",
    "Then commit to your matchup pick",
    "Watch enemy jungler — a gank-heavy comp punishes weak-early lane picks",
  ],
  JNG: [
    "Pick early — clear path matters more than counter",
    "Avoid blind-picking weak-early junglers",
    "Match enemy team's tempo — vs poke comp pick gank, vs engage pick disengage",
  ],
  MID: [
    "Flex picks have leverage — hover late",
    "Lock when enemy team comp is readable",
    "Save assassins for after enemy ADC + sup lock so you confirm dive targets",
  ],
  BOT: [
    "Pick after support locks — synergy > counter",
    "Lethality vs squishy comps, crit vs draft",
    "Hard-CC enemy support? Hover Cleanse before lock-in",
  ],
  SUP: [
    "Lock support pick first — your ADC counts on it",
    "Engage vs poke comp; peel vs assassin comp",
    "Vision-heavy supports (Bard, Senna) scale with map awareness — pair carefully",
  ],
  DEFAULT: [
    "Watch enemy hovers before locking",
    "Comfort > counterpick if matchup is unclear",
    "Hover your pick to telegraph intent — see if enemy adapts before you commit",
  ],
};

// s214: derive a comp-aware tip from the locked allies + enemies tag
// distribution. Returns null when neither side has any locks (early
// CS) so the caller falls through to the static row-3 tip. Uses the
// championTags cache (DDragon Fighter/Mage/Marksman/Tank/Support/
// Assassin classifications) — same source the enemy-row tag chips
// + adaptive-summoner classifier read from.
function _csvCompAwareTip(cs, role) {
  if (!cs || !championTags) return null;
  const tagOf = (cid) => {
    if (!cid) return [];
    const t = championTags(cid);
    return Array.isArray(t) ? t : [];
  };
  const allyIds = (cs.my_team || [])
    .filter((p) => p && p.completed && p.championId)
    .map((p) => p.championId | 0);
  const enemyIds = (cs.their_team || [])
    .filter((p) => p && p.championId)
    .map((p) => p.championId | 0);
  // Need at least 1 locked ally + 1 enemy commit for the tip to have
  // signal. Pre-lock state: caller fall-through to static tip.
  if (!allyIds.length && !enemyIds.length) return null;
  const tagCount = (ids) => {
    const c = { Fighter: 0, Mage: 0, Marksman: 0, Tank: 0, Support: 0, Assassin: 0 };
    ids.forEach((cid) => tagOf(cid).forEach((t) => { if (c[t] != null) c[t] += 1; }));
    return c;
  };
  const ally = tagCount(allyIds);
  const enemy = tagCount(enemyIds);

  // Damage-profile read: enemy AD = Fighter+Marksman+Assassin (Tank
  // partial); enemy AP = Mage. When one side is heavily skewed the
  // tip surfaces a defensive item or summoner spell suggestion.
  const enemyAD = enemy.Fighter + enemy.Marksman + enemy.Assassin;
  const enemyAP = enemy.Mage;
  const enemyCC = enemy.Tank + enemy.Support;  // proxy — full CC scoring lives in adaptive-summoner classifier
  const allyHasFrontline = (ally.Tank + ally.Fighter) >= 1;
  const allyHasCarry = (ally.Marksman + ally.Mage + ally.Assassin) >= 1;

  // Role-conditional tip selection — surface the highest-priority
  // observation for the operator's chosen role.
  if (role === "BOT") {
    if (enemyCC >= 3) return "Enemy has 3+ CC threats — hover Cleanse before lock-in";
    if (enemyAD > enemyAP + 1) return "Enemy comp leans AD — Plated Steelcaps / Tabis path opens up";
    if (enemyAP > enemyAD) return "Enemy comp leans AP — Mercury's + Maw of Malmortius";
    if (!allyHasFrontline) return "No locked frontline yet — wait or shift to a self-peeling ADC";
  } else if (role === "SUP") {
    if (!allyHasCarry) return "Carry slots still open — hover engage to telegraph aggression";
    if (enemyAD >= 3) return "Heavy AD enemy comp — Knight's Vow / Locket of Iron Solari shine";
    if (enemy.Assassin >= 1) return "Enemy has assassin pressure — peel-first supports beat engage here";
  } else if (role === "TOP") {
    if (enemy.Marksman + enemy.Mage >= 3) return "Enemy heavy on ranged damage — tank + MR rush";
    if (enemyAD >= 3) return "Heavy AD top side — armor first (Plated / Randuin's / Sunfire)";
    if (!allyHasCarry) return "Allies lack scaling carry — consider a self-scaling top (Nasus / Kayle)";
  } else if (role === "JNG") {
    if (enemy.Tank >= 2) return "Enemy fields 2+ tanks — bring %-HP or true-damage jungler";
    if (enemyCC >= 3) return "CC-heavy enemy comp — duelist > engage jungler";
    if (!allyHasFrontline) return "Allies lack frontline — pick an engage/tank jungler";
  } else if (role === "MID") {
    if (enemy.Assassin >= 1) return "Enemy assassin commits to dive — bring Zhonya's window";
    if (enemyAP >= 2) return "Enemy double-AP — Mercury's first; Maw of Malmortius if you're AD";
    if (!allyHasCarry) return "No locked carry yet — flex pick keeps options open";
  } else if (role === "ARAM" || role === "MAYHEM") {
    if (enemyCC >= 3) return "ARAM CC bomb risk — Mercury's + Cleanse if any ranged carry locks";
    if (enemyAP > enemyAD + 1) return "Enemy ARAM is AP-heavy — Force of Nature / Spirit Visage";
    if (enemyAD > enemyAP + 1) return "Enemy ARAM is AD-heavy — Plated / Randuin's path";
  }
  // Generic fall-through when nothing above triggered (mixed comp).
  if (allyHasFrontline && allyHasCarry) {
    return "Comp shaping up balanced — comfort > counterpick from here";
  }
  return null;
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
// s209 v2 fix: cs.bans comes through as `{my_team: [ids], their_team: [ids]}`
// from the LCU agent (a dict), not the array shape my first sig assumed.
// Old code did `(cs.bans || []).map(...)` which threw `.map is not a
// function` and aborted renderChampSelectView entirely (page stayed on
// the scaffold "waiting for champ-select data" text). Tolerant decode:
// arrays of {championId} (legacy shape), {my_team, their_team} arrays of
// ids (LCU agent shape), or missing → empty string.
function _csvBansSig(bans) {
  if (!bans) return "";
  if (Array.isArray(bans)) {
    return bans.map((b) => (b && b.championId) | 0).join(",");
  }
  if (typeof bans === "object") {
    const a = Array.isArray(bans.my_team)    ? bans.my_team.join(",")    : "";
    const b = Array.isArray(bans.their_team) ? bans.their_team.join(",") : "";
    return `${a}|${b}`;
  }
  return "";
}

// s209 v2: idempotent render sig. Captures everything renderChampSelectView
// reads to draw the three panels (allies / center / enemies + pickban).
// Timer remaining_ms is deliberately excluded — _csvSetupTimerTick owns
// the countdown text and updates it independently of the innerHTML
// rebuild. DS / user-variant / archetype caches are folded in as a
// 1-or-0 presence stamp so the render fires once when each cache lands.
function _csvComputeSig(cs, mode, myCid, myName) {
  const teamSig = (t) => (t || []).map((p) => {
    if (!p) return "_";
    return `${p.cellId|0}:${p.championId|0}:${p.championPickIntent|0}`;
  }).join(",");
  // s214: DS cache key folds in the archetype primary alongside mode,
  // so the sig changes when operator flips archetype mid-CS and the
  // build chooser re-renders with fresh items.
  const archForKey = (_CSV_ARCH_CACHE[myName] && _CSV_ARCH_CACHE[myName].primary)
    || _csvSavedArchetype(myName) || "";
  const dsKey   = _CSV_DS_CACHE[_csvDsCacheKey(myName, _csvDsModeFor(mode), archForKey)] ? "1" : "0";
  const userKey = _CSV_USER_CACHE[`${myName}|${mode || "sr"}`] !== undefined ? "1" : "0";
  // s211 v4: include the archetype's primary + source in the sig so a
  // mid-session swap (operator clicks Bruiser → Tank, or clicks AUTO
  // to revert to DDragon-tag default) actually re-renders the picker.
  // Pre-s211v4 the sig was presence-only ("1" once cached, never
  // changing) which meant the "overridden" pill + AUTO button state
  // stayed frozen on the first cached value until a full reload.
  const archCached = _CSV_ARCH_CACHE[myName];
  const archKey = archCached
    ? `1:${archCached.primary || ""}:${archCached.source || ""}`
    : "0::";
  // s209 v2: include adaptive-summoners cache state so the render fires
  // once when the recommendation lands per enemy roster. Just count the
  // cached keys for this champion — granular enough to detect "new
  // recommendation arrived" without hashing the whole cache.
  const adaptCount = Object.keys(_CSV_ADAPT_CACHE)
    .filter((k) => k.startsWith(`${myName}|`)).length;
  // s210: ban-suggestions cache state — count keys so the Suggestions
  // panel re-renders when the global top-bans fetch lands.
  const banSuggCount = Object.keys(_CSV_BANSUGG_CACHE).length;
  return [
    cs.phase || "",
    myCid | 0,
    cs.my_completed ? "1" : "0",
    teamSig(cs.my_team),
    teamSig(cs.their_team),
    _csvBansSig(cs.bans),
    cs.active_round
      ? `${cs.active_round.type}|${(cs.active_round.cell_ids || []).join(",")}`
      : "",
    cs.queue_id | 0,
    mode,
    `ds:${dsKey}|usr:${userKey}|arch:${archKey}|adapt:${adaptCount}|bsugg:${banSuggCount}`,
  ].join("|");
}

// s209 v2: coalesce post-fetch re-renders into a single rAF tick.
// _csvFetchDsBuilds / _csvFetchUserVariants / _csvFetchArchetype each
// fire their own .then() re-render, and on a cold-cache champion they
// can all land within the same frame — back-to-back synchronous
// renderChampSelectView() calls rebuild innerHTML three times in a
// row, which the operator sees as flicker in the build chooser. This
// helper queues one rAF, runs at most once per frame, and re-reads
// state.latest.lcu at fire time (in case the LCU envelope changed
// between the fetch landing and the frame rendering).
let _csvScheduledRenderRaf = 0;
function _csvScheduleRender() {
  if (_csvScheduledRenderRaf) return;
  _csvScheduledRenderRaf = requestAnimationFrame(() => {
    _csvScheduledRenderRaf = 0;
    if (state.latest && state.latest.lcu) {
      // s213: bump the section sig so the idempotent gate at the top
      // of renderChampSelectView doesn't bail. The sig already
      // captures DS/user/arch/adapt/bsugg cache state, but not the
      // lol-descriptions cache — events that fire `_csvScheduleRender`
      // (DS land, adaptive land, ban-sugg land, lol-desc land) need
      // to defeat the sig either by changing one of its inputs OR by
      // clearing the stamp explicitly. Clearing is safer than coupling
      // every fire site to the sig schema.
      const sec = document.getElementById("view-champ-select");
      if (sec) sec.dataset.csvSig = "";
      renderChampSelectView(state.latest.lcu);
    }
  });
}

// s213: re-render champ-select once the DDragon item/rune description
// cache lands so item + keystone elements pick up `data-tt-html`.
document.addEventListener("rc:lol-descriptions-ready", () => {
  _csvScheduleRender();
});
// s213 v2: same for champion-tags — enemy cells get the 2-piece tag +
// confidence pill once the cache resolves.
document.addEventListener("rc:champion-tags-ready", () => {
  _csvScheduleRender();
});

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

// s209 v2: adaptive-summoners cache (per champion + enemy-roster sig
// + base summoner pair). Refetches when enemies lock new champs.
const _CSV_ADAPT_CACHE    = Object.create(null);
const _CSV_ADAPT_INFLIGHT = Object.create(null);

// s210: ban-suggestions cache keyed on already-banned-set sig. Top-4
// globally-banned champions filtered against already-banned. Refetches
// when bans change so the panel stays in sync with the draft.
const _CSV_BANSUGG_CACHE    = Object.create(null);
const _CSV_BANSUGG_INFLIGHT = Object.create(null);

function _csvBanSuggKey(excludedIds) {
  return (excludedIds || []).slice().sort((a, b) => a - b).join(",");
}

function _csvFetchBanSuggestions(excludedIds) {
  const key = _csvBanSuggKey(excludedIds);
  if (_CSV_BANSUGG_CACHE[key] || _CSV_BANSUGG_INFLIGHT[key]) return;
  _CSV_BANSUGG_INFLIGHT[key] = true;
  const url = `/api/champ-select/ban-suggestions?exclude=${encodeURIComponent(key)}&top=4`;
  fetch(url, { cache: "no-store" })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_BANSUGG_INFLIGHT[key] = false;
      if (data && data.ok) {
        _CSV_BANSUGG_CACHE[key] = data;
        _csvScheduleRender();
      }
    })
    .catch(() => { _CSV_BANSUGG_INFLIGHT[key] = false; });
}

function _csvAdaptKey(champion, enemyIds, baseSummoners, role) {
  return [
    champion || "",
    (enemyIds || []).join(","),
    (baseSummoners || []).join(","),
    role || "",
  ].join("|");
}

function _csvFetchAdaptiveSummoners(champion, enemyIds, baseSummoners, role) {
  if (!champion) return;
  const key = _csvAdaptKey(champion, enemyIds, baseSummoners, role);
  if (_CSV_ADAPT_CACHE[key] || _CSV_ADAPT_INFLIGHT[key]) return;
  _CSV_ADAPT_INFLIGHT[key] = true;
  const url = `/api/champ-select/adaptive-summoners`
            + `?champion=${encodeURIComponent(champion)}`
            + `&enemy_ids=${encodeURIComponent((enemyIds || []).join(","))}`
            + `&base=${encodeURIComponent((baseSummoners || []).join(","))}`
            + `&role=${encodeURIComponent(role || "")}`;
  fetch(url, { cache: "no-store" })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_ADAPT_INFLIGHT[key] = false;
      if (data && data.ok) {
        _CSV_ADAPT_CACHE[key] = data;
        _csvScheduleRender();
      }
    })
    .catch(() => { _CSV_ADAPT_INFLIGHT[key] = false; });
}

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

// ─── Phase 3 (s176, 2026-05-12) — archetype scorer picker ───────────────
//
// Six canonical archetypes; carry/bruiser/tank have real scorers today
// (ds.dps / ds.hybrid / ds.ehp), the rest are placeholders for Phases
// 4-6. Order matches core/archetype_picks.ARCHETYPES so the UI is stable
// across language changes and re-renders. Implemented set tracked
// separately so we can gray-out the unimplemented ones without removing
// them — operator sees the full taxonomy.
// s209: all 6 scorers shipped — flipped `implemented: false → true` for
// mage/assassin/enchanter and pointed to their dedicated scorers
// (ability DPS / burst / HPS) per Phases 4-6 (s179/s180/s181). Pre-s209
// the dispatcher routed these to ds.dps as a placeholder; that fallback
// path is gone. Source of truth for unit suffixes is web/js/lib/scorer_units.js.
const _CSV_ARCHETYPES = [
  { key: "carry",     label: "Carry",     implemented: true, scorer: "DPS" },
  { key: "bruiser",   label: "Bruiser",   implemented: true, scorer: "Hybrid" },
  { key: "tank",      label: "Tank",      implemented: true, scorer: "EHP" },
  { key: "mage",      label: "Mage",      implemented: true, scorer: "Ability DPS" },
  { key: "assassin",  label: "Assassin",  implemented: true, scorer: "Burst" },
  { key: "enchanter", label: "Enchanter", implemented: true, scorer: "HPS" },
];

function _csvArchetypeStorageKey(champion) { return "rc-cs-archetype-" + (champion || ""); }
function _csvSavedArchetype(champion) {
  try { return localStorage.getItem(_csvArchetypeStorageKey(champion)) || ""; }
  catch (_) { return ""; }
}
function _csvSaveArchetype(champion, key) {
  try { localStorage.setItem(_csvArchetypeStorageKey(champion), key); }
  catch (_) {}
}

// Per-champion cached pick from /api/cs-archetype-pick. Map keyed by
// champion display name. Fetched once per champion change; the picker
// re-renders when the fetch lands. Same pattern as _CSV_DS_CACHE.
const _CSV_ARCH_CACHE = Object.create(null);
const _CSV_ARCH_INFLIGHT = Object.create(null);

function _csvFetchArchetype(champion) {
  if (!champion) return;
  if (_CSV_ARCH_CACHE[champion] || _CSV_ARCH_INFLIGHT[champion]) return;
  _CSV_ARCH_INFLIGHT[champion] = true;
  fetch("/api/cs-archetype-pick?champion=" + encodeURIComponent(champion), {
    cache: "no-store",
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_ARCH_INFLIGHT[champion] = false;
      if (data && data.ok && data.pick) {
        _CSV_ARCH_CACHE[champion] = data.pick;
        // s209 v2: rAF-coalesced — see _csvScheduleRender.
        _csvScheduleRender();
      }
    })
    .catch(() => { _CSV_ARCH_INFLIGHT[champion] = false; });
}

// Resolve which archetype to highlight. Priority: localStorage (instant)
// → cached fetch (server-side override) → "" (no selection yet, picker
// shows nothing pre-selected and the row is dim).
function _csvResolveArchetype(champion) {
  if (!champion) return { key: "", source: "" };
  const local = _csvSavedArchetype(champion);
  if (local && _CSV_ARCHETYPES.some((a) => a.key === local)) {
    return { key: local, source: "local" };
  }
  const fetched = _CSV_ARCH_CACHE[champion];
  if (fetched && fetched.primary) {
    return { key: fetched.primary, source: fetched.source || "default" };
  }
  return { key: "", source: "" };
}

function _csvArchetypePickerHtml(champion) {
  if (!champion) return "";
  const resolved = _csvResolveArchetype(champion);
  const buttons = _CSV_ARCHETYPES.map((a) => {
    const cls = ["csv-arch-btn"];
    if (a.key === resolved.key) cls.push("active");
    if (!a.implemented) cls.push("placeholder");
    return `<button class="${cls.join(" ")}" data-arch="${a.key}"`
         + ` title="${a.label} → ds.${a.scorer.toLowerCase().split(" ")[0]}">`
         + `<span class="csv-arch-label">${a.label}</span>`
         + `<span class="csv-arch-scorer">${a.scorer}</span>`
         + `</button>`;
  }).join("");
  // s212 v3: dropped the "overridden" / "auto" source pill — duplicate
  // of the AUTO button's active state (green-active = auto, grey =
  // overridden). The AUTO button alone carries both signals: when
  // green it's the active mode; when grey-clickable it means "click
  // to revert from override". Audit must-fix #2 closed.
  const isAuto = (resolved.source === "default" || resolved.source === "");
  const autoBtn = `<button class="csv-arch-auto${isAuto ? " is-active" : ""}"
                           data-champion="${champion}"
                           title="${isAuto ? 'currently auto-derived from DDragon tags' : 'click to revert to DDragon-tag default'}">AUTO</button>`;
  return `
    <div class="csv-archetype-picker" data-champion="${champion}">
      <div class="csv-archetype-title">
        <span>Daemon Slayer build archetype</span>
        ${autoBtn}
      </div>
      <div class="csv-archetype-buttons">${buttons}</div>
    </div>`;
}

function _csvWireArchetypePicker(scope) {
  const wrap = scope.querySelector(".csv-archetype-picker");
  if (!wrap) return;
  const champion = wrap.dataset.champion || "";
  if (!champion) return;
  wrap.querySelectorAll(".csv-arch-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const arch = btn.dataset.arch || "";
      if (!arch) return;
      // Save locally for instant subsequent renders, then POST to
      // persist server-side. Match the existing build-chooser pattern.
      _csvSaveArchetype(champion, arch);
      // Optimistic update of the cached pick so the next render shows
      // the active state without waiting for the POST round-trip.
      _CSV_ARCH_CACHE[champion] = Object.assign(
        {}, _CSV_ARCH_CACHE[champion] || {},
        { primary: arch, source: "user_cs", champion },
      );
      // s214: invalidate any cached DS entries for OTHER archetypes
      // on this champion so the experimental row's items refresh with
      // the new scorer. The DS cache key is `${champion}|${dsMode}|${arch}`
      // so we drop every entry whose champion+dsMode matches but arch
      // does not. Net effect: clicking Tank → Bruiser drops the cached
      // Tank ranking and triggers a fresh `/api/ds-preview` POST with
      // `archetype: "bruiser"` next render.
      Object.keys(_CSV_DS_CACHE).forEach((k) => {
        if (k.startsWith(`${champion}|`) && !k.endsWith(`|${arch}`)) {
          delete _CSV_DS_CACHE[k];
        }
      });
      Object.keys(_CSV_DS_INFLIGHT).forEach((k) => {
        if (k.startsWith(`${champion}|`) && !k.endsWith(`|${arch}`)) {
          delete _CSV_DS_INFLIGHT[k];
        }
      });
      fetch("/api/cs-archetype-pick", {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ champion, primary: arch, source: "user_cs" }),
      })
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          if (data && data.ok && data.pick) {
            _CSV_ARCH_CACHE[champion] = data.pick;
          }
        })
        .catch(() => { /* localStorage already saved; next reload retries */ });
      // Update DOM directly so the operator sees the click respond
      // before the next render tick.
      wrap.querySelectorAll(".csv-arch-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.arch === arch);
      });
      _csvScheduleRender();
    });
  });
  // s211: AUTO button → revert to DDragon-tag default. Clears the
  // local override, POSTs `{clear: true}` to drop the server-side
  // record, and re-fetches so the picker re-renders with source="default".
  const autoBtn = wrap.querySelector(".csv-arch-auto");
  if (autoBtn) {
    autoBtn.addEventListener("click", () => {
      if (autoBtn.classList.contains("is-active")) return;  // already on AUTO
      try { localStorage.removeItem(_csvArchetypeStorageKey(champion)); } catch (_) {}
      // s214: drop the user-archetype DS cache so the experimental row
      // re-fetches with the about-to-be-resolved default archetype.
      // We don't know which archetype the server will default to yet,
      // so blow away everything for this champion + dsMode pair.
      Object.keys(_CSV_DS_CACHE).forEach((k) => {
        if (k.startsWith(`${champion}|`)) delete _CSV_DS_CACHE[k];
      });
      Object.keys(_CSV_DS_INFLIGHT).forEach((k) => {
        if (k.startsWith(`${champion}|`)) delete _CSV_DS_INFLIGHT[k];
      });
      // Drop server-side; the endpoint accepts `{champion, clear: true}`.
      fetch("/api/cs-archetype-pick", {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ champion, clear: true }),
      })
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          // Clear our cache so the next fetch reloads the default.
          delete _CSV_ARCH_CACHE[champion];
          delete _CSV_ARCH_INFLIGHT[champion];
          if (data && data.ok && data.pick) {
            _CSV_ARCH_CACHE[champion] = data.pick;
          }
          _csvScheduleRender();
        })
        .catch(() => {
          delete _CSV_ARCH_CACHE[champion];
          _csvScheduleRender();
        });
    });
  }
}

// Convert the view's adapt-mode to the DS engine's mode label.
function _csvDsModeFor(mode) {
  if (mode === "aram")  return "ARAM";
  if (mode === "arena") return "ARENA";
  return "SR";
}

// s214: cache key extended to include the active archetype so a
// mid-CS swap (Tank → Bruiser via the archetype picker) invalidates
// the experimental row's items and re-fetches with the new scorer.
// Pre-s214 the experimental row served stale ds.dps rankings for the
// full champ-select session regardless of archetype clicks. Helper
// returns the key + archetype string so callers can pass it through
// to /api/ds-preview (the s184 backend dispatcher already routes
// `archetype` → rank_for_primary_archetype).
function _csvDsCacheKey(champion, dsMode, archetype) {
  const a = archetype || "";
  return `${champion}|${dsMode}|${a}`;
}

// Fire the DS engine for this champion + mode + archetype. Non-blocking
// — the next renderChampSelectView tick (~1Hz from the LCU state push)
// picks up the cached result. ``level=6`` matches the legacy overlay's
// preview level so the rankings match between views.
function _csvFetchDsBuilds(champion, dsMode, archetype) {
  if (!champion || !dsMode) return;
  const key = _csvDsCacheKey(champion, dsMode, archetype);
  if (_CSV_DS_CACHE[key] || _CSV_DS_INFLIGHT[key]) return;
  _CSV_DS_INFLIGHT[key] = true;
  const body = { champion, mode: dsMode, level: 6, items: [] };
  if (archetype) body.archetype = archetype;
  fetch("/api/ds-preview", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_DS_INFLIGHT[key] = false;
      if (data && data.ok && Array.isArray(data.ranked) && data.ranked.length) {
        _CSV_DS_CACHE[key] = data.ranked;
        // s209: trigger a CS re-render so the build chooser picks up
        // the fresh cache. s209 v2: routed through _csvScheduleRender so
        // simultaneous fetches don't trigger N back-to-back innerHTML
        // rebuilds (the visible build-chooser flicker on cold load).
        _csvScheduleRender();
      }
    })
    .catch(() => { _CSV_DS_INFLIGHT[key] = false; });
}

// s171.8: fetch user-curated variants (loadout_resolver). Mode label is
// the lower-case form ("sr"/"aram"/"arena") matching the legacy
// chooser's contract — `/api/loadout/list` normalises internally.
// s214 v2: "brawl" dropped from the mode set (mode retired from rotation).
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
      const variants = (data && Array.isArray(data.variants))
        ? data.variants : [];
      _CSV_USER_CACHE[key] = variants;
      // s209 v2: rAF-coalesced — see _csvScheduleRender.
      if (variants.length) _csvScheduleRender();
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
function _csvBuildVariantsFor(cid, name, mode, cs) {
  if (!cid || !name) {
    return [{ key: "empty", label: "no champion yet — hover or lock to see builds",
              keystone: "—", item_ids: [], is_default: true }];
  }
  const dsMode = _csvDsModeFor(mode);
  // s214: include the resolved archetype primary in the DS cache key so
  // a mid-CS archetype swap (operator clicks Tank → Bruiser) re-fetches
  // with the new scorer. Empty archetype string defaults to ds.dps (the
  // dispatcher's `fell_back=True` path for unimplemented archetypes pre-
  // s182 — preserves behavior for callers that don't pass archetype).
  const archResolved = _csvResolveArchetype(name);
  const archKey = (archResolved && archResolved.key) || "";
  // s211 v2 fix: default to empty array when cache is cold — pre-fix
  // `ranked.slice(0, 6)` below threw "Cannot read properties of
  // undefined (reading 'slice')" and aborted the whole render.
  const ranked = _CSV_DS_CACHE[_csvDsCacheKey(name, dsMode, archKey)] || [];
  // Always trigger the user-variant fetch + DS fetch in parallel. s210
  // dropped the DS pseudo-row from the build chooser — DS engine output
  // now renders in the Suggestions panel — but we still need DS data
  // for the experimental row's item set (DS top picks under the hood)
  // and for `/api/champ-select/adaptive-summoners` enemy classification.
  _csvFetchUserVariants(name, mode || "sr");
  if (!ranked.length) {
    _csvFetchDsBuilds(name, dsMode, archKey);
  }
  // s209 v2: pull enemy ids + role for the adaptive-summoner pipeline.
  // Empty enemy_ids during early CS is fine — the recommendation will
  // be the base pair (no swap) until enemies lock.
  const enemyIds = cs
    ? ((cs.their_team || []).map((p) => (p && p.championId) | 0).filter((x) => x > 0))
    : [];
  const role = cs ? _csvResolveRole(cs) : "";
  const top6 = ranked.slice(0, 6).map((r) => r.item_id).filter((x) => x);
  const reasons = {};
  ranked.slice(0, 6).forEach((r) => {
    if (r.item_id) {
      const u = scorerUnit(r.scorer);
      reasons[r.item_id] = "+" + Math.round(r.delta_dps || 0) + " " + u;
    }
  });
  const userVariants = _CSV_USER_CACHE[`${name}|${mode || "sr"}`] || [];
  // User-variant rows carry their own keystone / primary / secondary /
  // summoners / item_ids from the loadout file. s209 preserves all four
  // fields through the mapper so the row renderer can show the full
  // rune + spell strip; pre-s209 the mapper dropped primary/secondary/
  // summoners and the strip rendered only the keystone caption.
  const userRows = userVariants.map((v) => {
    const baseSumm = Array.isArray(v.summoners) ? v.summoners : [];
    // s209 v2: fetch adaptive summoners keyed on (variant base summoners,
    // enemy roster, role). When the recommendation lands, the rendered
    // row swaps to it + stamps swap metadata for the visual cue. The
    // variant's stored base is preserved on the row so a future "revert
    // to stored" toggle has a value to fall back to.
    _csvFetchAdaptiveSummoners(name, enemyIds, baseSumm, role);
    const adapt = _CSV_ADAPT_CACHE[_csvAdaptKey(name, enemyIds, baseSumm, role)];
    const summoners = (adapt && Array.isArray(adapt.summoners))
      ? adapt.summoners
      : baseSumm;
    return {
      key:        v.key,
      label:      v.label || v.key,
      keystone:   v.keystone  || "user variant",
      primary:    v.primary   || "",
      secondary:  v.secondary || "",
      summoners,
      summoners_base: baseSumm,
      adapt:      adapt || null,   // {swapped, swap_from, swap_to, reason}
      item_ids:   v.item_ids  || [],
      reasons:    {},
      is_default: false,
      is_user:    true,
    };
  });
  // s210: experimental auto-build row appended to every champion's
  // chooser. Pulls DS engine top-6 items + adaptive summoners (when
  // available). Keystone is left blank — operator can copy a curated
  // variant's rune page if they want runes too; experimental is items+
  // spells only. Click pushes runes:false / items:true / summoners:true.
  let experimentalRow = null;
  if (top6.length) {
    // s210 v2: archetype → keystone / primary / secondary derived from
    // the operator's active scorer archetype pick (or the DDragon-tag
    // default). This gives the experimental row a real keystone icon +
    // tree pair so the visual matches the curated rows. The apply
    // pipeline pushes these via override_runes.
    const arch = _csvResolveArchetype(name);
    const archKey = (arch && arch.key) || "carry";
    const expRunes = _csvExperimentalRunesFor(archKey);
    const expBaseSumm = [4, 7];  // Flash + Heal baseline; adaptive overrides.
    _csvFetchAdaptiveSummoners(name, enemyIds, expBaseSumm, role);
    const expAdapt = _CSV_ADAPT_CACHE[_csvAdaptKey(name, enemyIds, expBaseSumm, role)];
    const expSumm = (expAdapt && Array.isArray(expAdapt.summoners))
      ? expAdapt.summoners : expBaseSumm;
    experimentalRow = {
      key:        "experimental",
      label:      "Experimental",
      keystone:   expRunes.keystone,
      primary:    expRunes.primary,
      secondary:  expRunes.secondary,
      summoners:  expSumm,
      summoners_base: expBaseSumm,
      adapt:      expAdapt || null,
      item_ids:   top6,
      reasons,
      is_default: false,
      is_experimental: true,
      // s210 v2: extra fields surfaced to the click handler so apply
      // can push override_runes + override_items without re-deriving.
      experimental_archetype: archKey,
      experimental_item_ids:  top6,
    };
  }
  // s210: experimental row goes LAST so the curated rows are the
  // operator's default eye-line. Drop the DS pseudo-row (now in the
  // Suggestions panel) and the [saved] tag (every non-experimental
  // row is curated — the tag was redundant once the DS row left).
  return experimentalRow ? userRows.concat([experimentalRow]) : userRows;
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
      // s213: rich item tooltip from DDragon item description. Falls
      // back to scorer reason (e.g., "+18 dps") when DDragon load
      // hasn't completed yet OR when the item id isn't in the cache.
      // app-wide tooltip reads `data-tt-html` first, `title` second.
      const lolHtml = itemTooltipHtml(iid);
      const reasonAttr = reasons[iid] ? ` title="${reasons[iid]}"` : "";
      const ttAttr = lolHtml ? ` data-tt-html="${lolHtml.replace(/"/g, "&quot;")}"` : "";
      return `
      <div class="csv-build-item"${ttAttr}${reasonAttr}>
        <img src="/data/ddragon/${ver}/img/item/${iid}.png"
             onerror="if(!this.dataset.cdn){this.dataset.cdn=1;this.src='https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${iid}.png'}else{this.style.display='none'}"
             alt="">
      </div>`;
    }).join("") || '<div class="csv-empty">—</div>';
    const cb = `<div class="csv-build-checkbox"></div>`;
    // s211: variant badge replaces the row tag. Each row's label is
    // rendered as a colored pill in the same visual style as the
    // pre-s211 [experimental] tag. The color is keyed off the variant
    // key so On-Hit / Crit / Experimental each get a distinct hue.
    // No separate trailing tag — the badge IS the label.
    const tag = '';
    const badgeClass = _csvVariantBadgeClass(v);

    // s211 v3: rune line 2 is just the KEYSTONE — icon on the left,
    // keystone name spelled out as text on the right. The primary tree
    // icon (round tree-shield symbol) was dropped per operator request;
    // the keystone art IS already in the primary tree visually, so
    // showing both was redundant. Tree info still rides through the
    // apply payload — just visually elided.
    // s213: keystone gets a rich tooltip from DDragon runesReforged
    // (name + tree + short description). Falls back silently to bare
    // `title` until the JSON loads on first hover.
    const keystoneIcon = _csvKeystoneIcon(v.keystone);
    const ksHtml = keystoneTooltipHtml(v.keystone);
    // s214: rich tooltip lives ONLY on the wrapper so hovering either
    // the icon OR the spelled-out keystone name fires the same
    // DDragon-backed tooltip. Pre-s214 the img carried a bare `title`
    // (browser native tooltip) which intercepted hover and gave a
    // different/weaker UX than the wrapper's app-tooltip. Removing
    // `title` from the child lets the wrapper's data-tt-html win.
    // Fallback `title` on the wrapper for the brief window before the
    // DDragon descriptions cache resolves.
    const ksFallbackTitle = v.keystone ? ` title="${v.keystone}"` : "";
    const ksTtAttr = ksHtml ? ` data-tt-html="${ksHtml.replace(/"/g, "&quot;")}"` : ksFallbackTitle;
    const runeMainHtml = (keystoneIcon || v.keystone)
      ? `<div class="csv-build-rune-main"${ksTtAttr}>
           ${keystoneIcon ? `<img class="csv-build-rune-keystone" src="${keystoneIcon}" onerror="this.style.display='none'" alt="">` : ""}
           ${v.keystone   ? `<span class="csv-build-rune-tree-name">${v.keystone}</span>` : ""}
         </div>`
      : "";
    // s209 v2: render summoners + an adaptive-swap badge when the row's
    // adaptive recommendation differs from the variant's stored pair.
    // The displayed summoners are already overridden by the recommendation
    // (see _csvBuildVariantsFor); the badge surfaces *why* the swap fired
    // (CC threat / burst threat / etc.) so the operator can sanity-check.
    const summoners = Array.isArray(v.summoners) ? v.summoners.slice(0, 2) : [];
    const adapt = v.adapt || null;
    const swappedSecondary = adapt && adapt.swapped;
    const spellTooltip = (sid, isSecondary) => {
      const nm = sumName(sid) || `spell ${sid}`;
      if (isSecondary && swappedSecondary && adapt) {
        return `${nm} (swapped from ${adapt.swap_from || "?"} · ${adapt.reason || ""})`;
      }
      return nm;
    };
    const spellsHtml = summoners.length
      ? `<span class="csv-build-spells">${summoners.map((sid, idx) => {
          const isSecondary = idx === 1;
          const url = sumImg(sid);
          const tip = spellTooltip(sid, isSecondary);
          const cls = "csv-build-spell" + (isSecondary && swappedSecondary ? " is-swapped" : "");
          return url
            ? `<img class="${cls}" src="${url}" title="${tip}" onerror="this.style.display='none'">`
            : `<span class="${cls} empty" title="${tip}">?</span>`;
        }).join("")}</span>`
      : "";
    // s211: runes-text caption removed — rune main + sub icons replace
    // it visually, and the redundant "Keystone · Primary / Secondary"
    // line was eating row height. Hovering the icons still shows the
    // tree names via title attrs.
    const runesText = "";

    // s209 v2: stash the adaptive override on the row dataset so the
    // click handler can read it without going through the cache twice.
    // Empty when no swap applied (click uses variant's stored summoners).
    // For experimental rows we ALWAYS pass the recommended summoners
    // (adaptive when available; baseline Flash+Heal otherwise) so the
    // apply pipeline pushes them — variant isn't in the loadouts file
    // so there's no "stored" pair to fall back to.
    const summOverride = (v.is_experimental || swappedSecondary) && Array.isArray(v.summoners)
      ? v.summoners.join(",")
      : "";
    const summAttr = summOverride ? ` data-override-summoners="${summOverride}"` : "";
    // s210 v2: experimental rows carry override_runes + override_items
    // so the backend bypasses the variant resolver and builds the LCU
    // command payloads inline.
    let expAttrs = "";
    if (v.is_experimental && v.keystone && v.primary && v.secondary) {
      const itemList = (v.experimental_item_ids || v.item_ids || []).join(",");
      expAttrs = ` data-exp-keystone="${v.keystone}"`
               + ` data-exp-primary="${v.primary}"`
               + ` data-exp-secondary="${v.secondary}"`
               + ` data-exp-items="${itemList}"`;
    }
    // s211: 4-column row — checkbox / meta (3 stacked rows: badge, main
    // tree, sub tree) / summoners (stacked vertically) / items (larger).
    // Label rendered as a colored pill via csv-build-badge so the row
    // identity reads at a glance without a trailing tag.
    // s211 v2: 2-row card — badge label on row 1, rune main (keystone
    // + primary icon + primary tree name) on row 2. Subtree row dropped;
    // freed vertical room rolls into the larger icon sizes.
    return `
      <div class="csv-build-row${idx === selectedIdx ? " selected" : ""}" data-variant="${v.key}"${summAttr}${expAttrs}>
        ${cb}
        <div class="csv-build-meta">
          <div class="${badgeClass}">${v.label}</div>
          ${runeMainHtml}
        </div>
        ${spellsHtml}
        <div class="csv-build-items">${items}</div>
      </div>`;
  }).join("");
}

// s209: in-flight guard on the loadout-apply call so a rapid double-click
// doesn't fire two LCU pushes back-to-back. Keyed per
// (champion, variant, mode) — cleared when the response lands.
const _CSV_APPLY_INFLIGHT = Object.create(null);

function _csvApplyLoadout(champion, variantKey, mode, overrideSummoners, overrideRunes, overrideItems) {
  if (!champion || !variantKey) return;
  // Empty/pending pseudo-rows aren't backed by anything pushable.
  if (variantKey === "empty" || variantKey === "ds-pending") return;
  const key = `${champion}|${variantKey}|${mode || "sr"}|${(overrideSummoners||[]).join(",")}`;
  if (_CSV_APPLY_INFLIGHT[key]) return;
  _CSV_APPLY_INFLIGHT[key] = true;
  const body = {
    champion, variant: variantKey, mode: mode || "sr",
    push_runes:     true,
    push_items:     true,
    push_summoners: true,
  };
  if (Array.isArray(overrideSummoners) && overrideSummoners.length === 2) {
    body.override_summoners = overrideSummoners.map((x) => x | 0);
  }
  // s210 v2: experimental row passes a complete override package
  // (keystone+trees + DS engine item ids). Backend bypasses the variant
  // resolver and builds rune_cmd/item_cmd/summ_cmd inline.
  if (overrideRunes
      && overrideRunes.keystone && overrideRunes.primary && overrideRunes.secondary) {
    body.override_runes = {
      keystone:  overrideRunes.keystone,
      primary:   overrideRunes.primary,
      secondary: overrideRunes.secondary,
    };
  }
  if (Array.isArray(overrideItems) && overrideItems.length) {
    body.override_items = overrideItems.map((x) => String(x));
  }
  fetch("/api/loadout/apply", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
    .then((r) => (r && r.ok ? r.json() : null))
    .catch(() => null)
    .finally(() => { _CSV_APPLY_INFLIGHT[key] = false; });
}

function _csvWireBuildVariants(scope) {
  // s171.8: read champion + mode from the wrapper's data-* so the click
  // handler can persist the selection AND fire the loadout push. Falls
  // back to no-save if absent (defensive — keeps the visual toggle
  // working in unit-test fixtures).
  const wrap = scope.querySelector(".csv-builds");
  const champion = wrap ? (wrap.dataset.champion || "") : "";
  const mode     = wrap ? (wrap.dataset.mode || "sr") : "sr";
  const rows = scope.querySelectorAll(".csv-build-row");
  rows.forEach((row) => {
    row.addEventListener("click", () => {
      rows.forEach((r) => r.classList.toggle("selected", r === row));
      const variantKey = row.dataset.variant;
      if (champion && variantKey
          && variantKey !== "empty"
          && variantKey !== "ds-pending") {
        _csvSaveChoice(champion, variantKey);
        // s209: fire the actual LCU push — runes + items + summoners.
        // s209 v2 / s210 v2: read override data stamped on the row.
        // Curated rows pass override_summoners only (when adaptive
        // swapped). Experimental rows additionally pass override_runes
        // + override_items so the backend builds LCU cmds inline.
        const summRaw = row.dataset.overrideSummoners || "";
        const overrideSummoners = summRaw
          ? summRaw.split(",").map((x) => x | 0)
          : null;
        let overrideRunes = null;
        let overrideItems = null;
        if (row.dataset.expKeystone) {
          overrideRunes = {
            keystone:  row.dataset.expKeystone,
            primary:   row.dataset.expPrimary || "",
            secondary: row.dataset.expSecondary || "",
          };
          const itemsRaw = row.dataset.expItems || "";
          overrideItems = itemsRaw
            ? itemsRaw.split(",").filter((x) => x)
            : null;
        }
        _csvApplyLoadout(champion, variantKey, mode,
                         overrideSummoners, overrideRunes, overrideItems);
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
      // s214: per-cell timer removed for Arena teams too — same
      // rationale as SR/ARAM. Lock glyph kept for arena since the
      // sub-team card visual is denser and the cell's own outline
      // doesn't carry the lock signal as cleanly. `timerEndMs` arg
      // retained on the function for ABI continuity with SR's caller
      // signature, but no longer rendered.
      const lockHtml = c.completed ? '<span class="csv-arena-cell-lock">🔒</span>' : "";
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

// s214: per-cell countdown ticker retired alongside the per-cell timers
// in SR/ARAM/Arena (operator: too much visual noise; the global header
// timer + active-round border indicator already convey "round ticking
// down"). Kept as a no-op so existing callers don't error.
function _csvSetupTimerTick() { /* no-op since s214 */ }

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
// s211: mood-keyed row title for the Pick & Ban PERFORMANCE row.
// Mirrors the mood-button labels so the operator can correlate the
// active button with the row above it.
const _CSV_MOOD_LABELS = {
  comfort: "Performance",
  limit:   "Limit Test",
  new:     "Something New",
  synergy: "Comp Synergy",
};

// s170 item #4: live pick&ban recommendations from
// /api/champ-select/pickban-recs. Cached per (role, queue_id) and
// refreshed at most every 60s — operator history isn't changing
// during a single champ-select session, so this is just an in-memory
// dedupe to keep the panel responsive.
const _CSV_PB_CACHE = {};   // {`${role}|${queue}`: {data, fetchedAt}}
const _CSV_PB_INFLIGHT = {};
const _CSV_PB_TTL_MS = 60_000;

function _csvFetchPickBanRecs(role, queueId, mood, opts, onLoad) {
  // Role here is the dashboard form ("BOT"/"JNG"/etc.) — the endpoint
  // accepts both forms via its _ROLE_ALIASES map. s209: mood is
  // included in the cache key + query string so each toggle change
  // surfaces a distinct rec without invalidating others. s214: opts
  // adds {exclude:[ids], allies:[ids], top:N} for cascade-filtered
  // multi-row queries on LIMIT/NEW/SYNERGY moods. The full opts payload
  // folds into the cache key so a re-fetch with different excludes
  // doesn't return stale top-N from the prior call.
  if (!role || role === "—") return null;
  const m = mood || "comfort";
  const o = opts || {};
  const exclude = Array.isArray(o.exclude) ? o.exclude.slice().sort((a, b) => a - b) : [];
  const allies  = Array.isArray(o.allies)  ? o.allies.slice().sort((a, b) => a - b)  : [];
  const top     = Math.max(1, Math.min(5, o.top | 0 || 1));
  const cacheKey = [
    role, queueId || 0, m, top,
    `e:${exclude.join(",")}`, `a:${allies.join(",")}`,
  ].join("|");
  const now = Date.now();
  const cached = _CSV_PB_CACHE[cacheKey];
  if (cached && (now - cached.fetchedAt) < _CSV_PB_TTL_MS) {
    return cached.data;
  }
  if (_CSV_PB_INFLIGHT[cacheKey]) return cached ? cached.data : null;
  _CSV_PB_INFLIGHT[cacheKey] = true;
  let url = `/api/champ-select/pickban-recs?role=${encodeURIComponent(role)}`
          + (queueId ? `&queue=${queueId}` : "")
          + `&mood=${encodeURIComponent(m)}`
          + `&top=${top}`;
  if (exclude.length) url += `&exclude=${encodeURIComponent(exclude.join(","))}`;
  if (allies.length)  url += `&allies=${encodeURIComponent(allies.join(","))}`;
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
  const mood = _csvMoodGet();
  const perfLabel = _CSV_MOOD_LABELS[mood] || "Performance";

  // s214: build the cascade exclude-set — every champion already
  // committed in the draft is off-limits as a recommendation. Source
  // ids:
  //   - bans (ally + enemy) from cs.bans
  //   - picks (ally + enemy) from cs.my_team[].championId,
  //     cs.their_team[].championId (BOTH intent + locked)
  //   - the operator's own current pick intent (don't recommend
  //     yourself a champ you're already hovering)
  // Plus the row-cascade: as we render rows 1..N for LIMIT/NEW/SYNERGY,
  // each row's pick id is added to the exclude-set for the next row's
  // backend call so we never duplicate within the panel.
  const collectIds = (arr) => (arr || []).map((p) => {
    if (typeof p === "number") return p | 0;
    return (p && (p.championId | 0)) || 0;
  }).filter((x) => x > 0);
  const baseExclude = new Set();
  if (cs.bans) {
    collectIds(cs.bans.my_team).forEach((x) => baseExclude.add(x));
    collectIds(cs.bans.their_team).forEach((x) => baseExclude.add(x));
  }
  collectIds(cs.my_team).forEach((x) => baseExclude.add(x));
  collectIds(cs.their_team).forEach((x) => baseExclude.add(x));
  // Also exclude championPickIntent (hover state, not yet locked).
  (cs.my_team || []).concat(cs.their_team || []).forEach((p) => {
    const intent = p && p.championPickIntent;
    if (intent && intent > 0) baseExclude.add(intent | 0);
  });

  // Ally ids (LOCKED only — hovers don't count toward team-comp synergy
  // because they can swap) for the SYNERGY mood backend query.
  const allyIds = (cs.my_team || [])
    .filter((p) => p && p.completed && p.championId)
    .map((p) => p.championId | 0)
    .filter((x) => x > 0);

  // ── Mood branch ────────────────────────────────────────────────
  // COMFORT: keep the legacy 3-source layout (perf|mastery|meta).
  // LIMIT/NEW/SYNERGY: render 3 rows all of the same mood, cascading
  // through `exclude` so each row surfaces the next-best pick.
  let sources;
  if (mood === "comfort") {
    const liveRecs = _csvFetchPickBanRecs(
      role, cs.queue_id, mood,
      { exclude: Array.from(baseExclude), top: 1 },
      () => _csvRenderPickBan(cs, myCid),
    );
    const merged = _csvMergePickBanData(role, liveRecs, ph);
    sources = [
      { key: "performance", label: perfLabel, data: merged.performance },
      { key: "mastery",     label: "Mastery", data: merged.mastery },
      { key: "meta",        label: "Meta",    data: merged.meta },
    ];
  } else {
    // Single fetch — backend returns top-3 picks with the exclude-set
    // already applied. Cascade dedupe across rows happens server-side
    // (each result is the next-best after the previously-yielded ones).
    const opts = {
      exclude: Array.from(baseExclude),
      top: 3,
    };
    if (mood === "synergy") opts.allies = allyIds;
    const liveRecs = _csvFetchPickBanRecs(
      role, cs.queue_id, mood, opts,
      () => _csvRenderPickBan(cs, myCid),
    );
    const picks = (liveRecs && Array.isArray(liveRecs.performance_picks))
      ? liveRecs.performance_picks : [];
    // Backend can return fewer than 3 when history is thin; pad with
    // placeholder so the panel keeps its 3-row geometry rather than
    // collapsing. Placeholder reuses the role's perf/mastery/meta data.
    const fallbacks = [ph.performance, ph.mastery, ph.meta];
    const moodBans = (liveRecs && Array.isArray(liveRecs.performance_bans))
      ? liveRecs.performance_bans : ph.performance.bans;
    sources = [0, 1, 2].map((i) => {
      const p = picks[i];
      if (p) {
        return {
          key: i === 0 ? "performance" : (i === 1 ? "mastery" : "meta"),
          label: i === 0 ? perfLabel : `${perfLabel} · #${i + 1}`,
          data: {
            champId: p.champId,
            champName: p.champName,
            reason: p.reason,
            bans: moodBans.map((b) => ({
              champId: b.champId,
              name:    b.name,
              pct:     b.pct,
            })),
          },
        };
      }
      const fb = fallbacks[i];
      // s214 v3: short prefix tag so the reason stays ≤3 lines under
      // the .csv-pb-reason-text clamp. Pre-s214v3 the prefix was
      // "(no <mood> data — showing fallback) " which bloated the row
      // to 4 lines on tight viewports per operator feedback.
      return {
        key: i === 0 ? "performance" : (i === 1 ? "mastery" : "meta"),
        label: i === 0 ? perfLabel : (i === 1 ? "Mastery" : "Meta"),
        data: { ...fb, reason: `[no ${mood} data] ${fb.reason}` },
      };
    });
  }
  // s214: pick-click safety — only disable when an actual BAN round is
  // active so the operator can't accidentally fire `set_pick_intent`
  // during a ban (the trap the original gate addressed). Pre-s214 the
  // gate was `cs.phase === "FINALIZATION" || cs.my_completed === true`,
  // which under-enabled clicks during pick rounds (the operator
  // couldn't set pick intent until either the round was over OR they
  // had locked, which is itself a "click to lock" decision).
  //
  // Per-queue confirmation that the active_round resolver covers all
  // SR draft variants the operator cares about:
  //   400 Normal Draft  — one simultaneous ban round, then alt picks
  //   420 Ranked Solo   — same ban shape, alt picks
  //   430 Normal Blind  — no bans, alt picks only
  //   440 Ranked Flex   — same as 420
  //   490 Quickplay     — no bans, alt picks
  // ARAM (450/920) + Arena (1700/1710) don't show the P&B panel
  // (CSS hides it via data-cs-mode), so this gate is SR-only in practice.
  // s214 v2: Brawl branch retired from this list (mode removed).
  const inActiveBanRound = !!(cs.active_round
                              && cs.active_round.type === "ban");
  const pickClickEnabled = !inActiveBanRound;

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
      // s212 v6: no more `is-disabled` lockout — every cell stays
      // clickable so operator can re-fire `set_ban_intent` to LCU as
      // many times as they want during draft (LCU decides what sticks).
      // `.is-selected` still marks the most recent click for visual
      // continuity but doesn't gate the other cells.
      const isSelected = (_csvSelection.ban === b.champId);
      const banCls = "csv-pb-ban is-clickable"
                   + (isSelected ? " is-selected" : "");
      return `
        <div class="${banCls}" data-ban-id="${b.champId}" data-ban-name="${b.name}" title="${role3} ban candidate">
          <span class="csv-pb-ban-pct">${b.pct}%</span>
          <div class="csv-pb-ban-icon">${champImg(b.champId)}</div>
          <div class="csv-pb-ban-name">${b.name}</div>
        </div>`;
    }).join("");
    const isPickSelected = pickClickEnabled && _csvSelection.pick === d.champId;
    const pickIconCls = pickClickEnabled
      ? "csv-pb-pick-icon is-clickable"
        + (isPickSelected ? " is-selected" : "")
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

  // s212 v5: single-word ALL-CAPS labels for the mood toggle. Pre-s212v5
  // each button stacked two spans (e.g., "Comfort"/"Pick") to keep
  // total horizontal footprint small; operator's request to simplify
  // landed after the row got more horizontal room via other layout
  // changes. Width parity comes from the parent grid's 1fr 1fr 1fr 1fr
  // template (already in place); each label is centered inside its
  // cell via the existing flex-column align/justify on .csv-pb-mood-btn.
  const moodBtn = (k, l) =>
    `<button class="csv-pb-mood-btn${mood === k ? " is-active" : ""}" data-mood="${k}">${l}</button>`;
  html += `
    <div class="csv-pb-mood-row">
      <span class="csv-pb-mood-label"><span>MOOD</span></span>
      ${moodBtn("comfort", "COMFORT")}
      ${moodBtn("limit",   "LIMIT")}
      ${moodBtn("new",     "NEW")}
      ${moodBtn("synergy", "SYNERGY")}
    </div>`;

  body.innerHTML = html;

  // Wire mood toggle. s209: re-render the panel after persisting so the
  // performance row reflects the new mood (comfort / limit / new /
  // synergy). The fetch helper caches per (role, queue, mood) so a
  // toggle back to a previously-loaded mood is instant.
  body.querySelectorAll(".csv-pb-mood-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const m = btn.dataset.mood;
      if (!m) return;
      _csvMoodSet(m);
      body.querySelectorAll(".csv-pb-mood-btn").forEach((b) =>
        b.classList.toggle("is-active", b.dataset.mood === m));
      _csvRenderPickBan(cs, myCid);
    });
  });
  // Ban quick-select: every click fires `set_ban_intent` to LCU. The
  // most-recent click gets `.is-selected` red border via the selection
  // tracker on `_csvSelection.ban`; siblings stay fully clickable so
  // the operator can re-target as draft state shifts. s212 v6: dropped
  // the one-shot lockout that pre-s212v6 grayed out the other 2 cells.
  body.querySelectorAll(".csv-pb-ban.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      const cid = parseInt(cell.dataset.banId, 10);
      body.querySelectorAll(".csv-pb-ban").forEach((el) => {
        el.classList.toggle("is-selected", el === cell);
      });
      _csvOnBanSelect(cid);
    });
  });
  // Pick quick-select: same flow as bans — every click fires
  // `set_pick_intent`; latest-click gets the green border highlight,
  // siblings stay clickable.
  body.querySelectorAll(".csv-pb-pick-icon.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      const cid = parseInt(cell.dataset.pickId, 10);
      body.querySelectorAll(".csv-pb-pick-icon").forEach((el) => {
        el.classList.toggle("is-selected", el === cell);
      });
      _csvOnPickSelect(cid);
    });
  });
}

export { handleChampSelect, renderChampSelectCoach };
