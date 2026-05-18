// Item Build panel - owned/recommended tiles, DS picks, in-game build switcher.
import { el, safe, fmtList, isArenaPayload } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, ITEM_COSTS, _resolveItemId, _splitItemList, diffVariantItemIds } from '../lib/items_index.js';
import { formatDsDelta } from '../lib/scorer_units.js';
import { buildOrderPill } from './build_order.js';

const IB = {
  root: el("item-build"),
  owned: el("ib-owned"),
  recommended: el("ib-recommended"),
  dsBlock: el("ib-ds-block"),
  dsPicks: el("ib-ds-picks"),
  // Augments element lives in the header now (#augments-pill), not in the
  // Item Build panel, to keep info-panel layout stable across modes.
  augments: el("augments-pill"),
  // DS pill (header) - peripheral-vision surface for the engine's top
  // pick. Populated alongside the in-panel #ib-ds-picks chips so the
  // operator can read the call without scanning down to Item Build.
  dsPill: el("ds-pill"),
  staleness: document.querySelector('.staleness[data-for="item-build"]'),
};

// ITEMS, ITEM_COSTS, CHAMPS, SPELLS + all resolvers imported from lib/items_index.js.
// Re-drive item-build render after async index load (avoids circular dep).
let _lastItemBuildState = null;
document.addEventListener("rc:items-ready", () => {
  if (_lastItemBuildState) { try { renderItemBuild(_lastItemBuildState); } catch (_) {} }
});

function renderItemTiles(container, names, opts) {
  opts = opts || {};
  // Idempotency: every coach state push hits this path, even when the
  // item list is unchanged. Without this guard the IMG nodes get torn
  // down and recreated each tick, which flashes the panel (especially
  // visible when an item id 404s and the broken-image icon flickers).
  const sig = JSON.stringify([
    names, opts.cap || 6, !!opts.withArrows,
    opts.currentGold || 0, opts.reasons || null,
  ]);
  if (container.dataset.tilesSig === sig) return;
  container.dataset.tilesSig = sig;
  container.innerHTML = "";
  if (!names.length) {
    container.textContent = "-";
    return;
  }
  const CAP = opts.cap || 6;   // glance-read cap - extra tiles summarized as "+N"
  const shown = names.slice(0, CAP);
  const extra = names.length - shown.length;
  const ver = ITEMS.version;
  shown.forEach((name, i) => {
    const tile = document.createElement("div");
    tile.className = "item-tile";
    const iid = _resolveItemId(name);
    // Tooltip: item name + cost + (if provided) coach's reason for the
    // build choice. Reasons are looked up from opts.reasons[name] - the
    // coach populates this via p.item_build_reasons (or equivalent)
    // when available; otherwise the tooltip just shows name + cost.
    const reason = opts.reasons && opts.reasons[name];
    const cost = iid && ITEM_COSTS.byId[iid] ? `${ITEM_COSTS.byId[iid]}g` : "";
    const parts = [name];
    if (cost) parts.push(cost);
    if (reason) parts.push(reason);
    tile.title = parts.join(" - ");
    const iconWrap = document.createElement("div");
    iconWrap.className = "item-icon";
    if (iid) {
      const img = document.createElement("img");
      // Local-first: use cached asset under /data/ddragon/<ver>/img/item;
      // fall back to the CDN if the cache miss. Keeps us match-proof
      // against ISP/CDN hiccups.
      img.src = `/data/ddragon/${ver}/img/item/${iid}.png`;
      img.alt = name;
      img.loading = "lazy";
      img.onerror = () => {
        if (!img.dataset.cdnRetry) {
          img.dataset.cdnRetry = "1";
          img.src = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${iid}.png`;
        } else {
          iconWrap.classList.add("no-icon");
          img.remove();
        }
      };
      iconWrap.appendChild(img);
    } else {
      iconWrap.classList.add("no-icon");
    }
    const label = document.createElement("div");
    label.className = "item-name";
    // (2026-04-26) Per-item display overrides for names that wrap awkwardly
    // in the 70px tile. Use `\n` to force a clean break at a syllable
    // boundary; CSS `white-space: pre-line` on .item-name honors it while
    // -webkit-line-clamp still caps total lines.
    const _ITEM_DISPLAY = { "Morellonomicon": "Morello\nnomicon" };
    label.textContent = _ITEM_DISPLAY[name] || name;
    // Highlight the first tile in a path as "next to buy", and attach a
    // gold/cost caption if we have both numbers.
    if (opts.withArrows && i === 0) {
      tile.classList.add("next-up");
      if (iid && ITEM_COSTS.byId[iid] && typeof opts.currentGold === "number") {
        const cost = ITEM_COSTS.byId[iid];
        const pct = Math.max(0, Math.min(1, opts.currentGold / cost));
        tile.style.setProperty("--buy-pct", (pct * 100).toFixed(0) + "%");
        if (pct >= 1) tile.classList.add("can-afford");
        // Gold caption: "need N" = remaining gold to complete the buy.
        // TODO: subtract owned sub-item values once items_recipes.json is
        // generated - for now N = cost − currentGold, clamped to 0 for
        // the can-afford case.
        const need = Math.max(0, Math.round(cost - opts.currentGold));
        const cap = document.createElement("div");
        cap.className = "item-cost";
        cap.textContent = need === 0 ? "ready" : ("need " + need);
        tile.appendChild(cap);
      }
    }
    tile.appendChild(iconWrap);
    tile.appendChild(label);
    container.appendChild(tile);
    if (opts.withArrows && i < shown.length - 1) {
      const arrow = document.createElement("div");
      arrow.className = "item-arrow";
      arrow.textContent = "→";
      container.appendChild(arrow);
    }
  });
  if (extra > 0) {
    const more = document.createElement("div");
    more.className = "item-tile item-more";
    more.title = names.slice(CAP).join(", ");
    more.innerHTML = `<div class="item-icon no-icon">+${extra}</div><div class="item-name">more</div>`;
    container.appendChild(more);
  }
}

// 2026-04-26: Track the active loadout label per (champion+mode) so the
// ITEM BUILD header can show "<Champion> · <Variant Label>" instead of
// the static "Recommended · next to buy". Cache + lazy-fetch from
// /api/loadout/list so we don't hammer the endpoint on every render.
const _itemBuildLabelCache = {};
function _updateItemBuildHeader(champion, mode) {
  const labelEl = document.getElementById("ib-build-label");
  if (!labelEl) return;
  if (!champion) {
    labelEl.textContent = "Recommended · next to buy";
    return;
  }
  const cacheKey = champion + "|" + (mode || "");
  const cached = _itemBuildLabelCache[cacheKey];
  if (cached !== undefined) {
    labelEl.textContent = cached
      ? `${champion} · ${cached}`
      : `${champion} · Build`;
    return;
  }
  // Lazy fetch
  _itemBuildLabelCache[cacheKey] = null;   // mark in-flight
  fetch("/api/loadout/list", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ champion: champion, mode: mode || "aram" }),
  })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((data) => {
      let activeLabel = "";
      if (data && data.variants && data.variants.length) {
        const defaultKey = data.default || "";
        const matchKey = defaultKey || data.variants[0].key;
        const found = data.variants.find((v) => v.key === matchKey);
        activeLabel = (found && found.label) || "";
      }
      _itemBuildLabelCache[cacheKey] = activeLabel;
      labelEl.textContent = activeLabel
        ? `${champion} · ${activeLabel}`
        : `${champion} · Build`;
    })
    .catch(() => {
      _itemBuildLabelCache[cacheKey] = "";
      labelEl.textContent = `${champion} · Build`;
    });
}

function renderItemBuild(p) {
  _lastItemBuildState = p;
  const arena = isArenaPayload(p);
  // Update header label with champion + active variant.
  _updateItemBuildHeader(p.champion, state.mode);
  // In-game multi-build picker (2026-04-26 user request) - mirrors the
  // cs-build-list inside ITEM BUILD, lets the user hot-swap the item
  // set mid-game. Runes + summoners are locked at game start so we
  // only push items; the LCU agent updates the recommended shop order.
  _ibMaybeRenderBuilds(p);
  const owned = _splitItemList(p.items_display || p.items || p.owned_items, false);
  // SR coach doesn't emit item_build - fall back to sr_items (liveclient-derived
  // build path overlaid by _state_builder) when available.
  const _srItemPath = Array.isArray(p.sr_items)
    ? p.sr_items.filter(i => i && i.next).map(i => i.name)
    : [];
  const path = _splitItemList(p.item_build, true).length
    ? _splitItemList(p.item_build, true)
    : _srItemPath;
  // Defensive dedup: a coach payload occasionally leaves an already-owned
  // item at the front of the build-path array (e.g. Zhonya's appears in
  // both Owned and Recommended → "next to buy" highlights a completed
  // item). Strip anything already owned from the Recommended path so the
  // UI can never surface that logic error.
  // Matching is substring-both-ways because the coach uses short forms
  // in build-path ("Zhonya's") and long forms in items_display
  // ("Zhonya's Hourglass"). Exact-match would let the dupe through.
  const _norm = s => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const ownedNorm = owned.map(_norm).filter(s => s.length >= 3);
  const pathDedup = path.filter(n => {
    const pn = _norm(n);
    if (pn.length < 3) return true;
    return !ownedNorm.some(o => o.includes(pn) || pn.includes(o));
  });
  // Coach can emit per-item reasons via p.item_build_reasons (a map from
  // item name → short one-liner). Passed to the Recommended tiles so
  // hover shows the "why this next" coaching note. Owned tiles just
  // show name + cost (no reason - it's already bought).
  const itemReasons = (p && p.item_build_reasons) || {};
  renderItemTiles(IB.owned, owned, { withArrows: false });
  renderItemTiles(IB.recommended, pathDedup, {
    withArrows: true, currentGold: p.gold, reasons: itemReasons,
  });
  // Augments pill (header row 2) - always-visible per the static-pill
  // rule. Content = comma-separated list of augments the player
  // currently possesses (not advice). Mode-gated:
  //   arena → always has augments (3 picks per game)
  //   aram  → assumes Mayhem (user's default ARAM; internal mode code is
  //           KIWI - see core/game_snapshot.py where KIWI → MODE_ARAM)
  //   tft   → Set 17+ adds gods + augments; gated later when TFT returns
  //   other → static "Mode does not support Augments" placeholder
  if (IB.augments) {
    const mode = state.mode;
    const modeSupportsAugments = arena || mode === "aram";   // TODO: tft set 17+
    let content = "";
    if (modeSupportsAugments) {
      const owned = fmtList(p.augments);
      content = owned || "(none picked yet)";
      content = content.replace(/\s*\n+\s*/g, ", ").trim();
    } else {
      content = "Mode does not have augments";
    }
    IB.augments.textContent = content;
    IB.augments.classList.toggle("hidden", !modeSupportsAugments);
    IB.augments.classList.toggle("no-support", !modeSupportsAugments);
    // Data-driven ranking (CLAUDE #88) surfaces in the tooltip - visible
    // pill text stays the owned-augments glance (static-pill / no-reflow
    // rule). Confidence = blend weight (how much own-history is trusted;
    // low early by design - external Mayhem prior dominates cold-start).
    let augTitle = "";
    if (modeSupportsAugments && Array.isArray(p.aug_reco) && p.aug_reco.length) {
      const conf = Math.round((p.aug_reco_conf || 0) * 100);
      const head = `Pick: ${p.aug_reco_top} (conf ${conf}%)`;
      const meta = `${p.aug_reco_mode || "?"}`
        + (p.aug_reco_stage ? ` · stage ${p.aug_reco_stage}` : "")
        + ` · ${p.aug_reco_n_matches || 0} own games`;
      const rows = p.aug_reco.slice(0, 4).map((r, i) => {
        const ext = (r.ext_wr == null) ? "-" : `${Math.round(r.ext_wr * 100)}%`;
        return `${i + 1}. ${r.name}  ${r.score}  own ${Math.round(r.own_wr * 100)}% / ext ${ext} (n${r.n_own})`;
      });
      augTitle = [head, meta, ...rows].join("\n");
    }
    IB.augments.title = modeSupportsAugments ? augTitle : content;
  }
  // DS Engine picks - daemon_slayer_picks: [{id, name, delta_dps, gold, scorer?}, ...]
  // scorer (s182+) flips the unit suffix per archetype (dps/ehp/%/adps/burst/hps).
  const dsPicks = Array.isArray(p.daemon_slayer_picks) ? p.daemon_slayer_picks : [];
  if (IB.dsBlock) {
    if (dsPicks.length) {
      IB.dsPicks.innerHTML = dsPicks.map(r => {
        const delta = formatDsDelta(r);
        return `<span class="ds-chip" title="${r.name} · ${delta} · ${r.gold}g">`
             + `${r.name}<em>${delta}</em></span>`;
      }).join('');
      IB.dsBlock.hidden = false;
    } else {
      IB.dsBlock.hidden = true;
    }
  }
  // Header DS pill. (C) plan §6b: when an in-game build ORDER is cached,
  // show the next-2-in-order + a full-order rich tooltip; otherwise fall
  // back to the flat top-pick render. build_order.js owns the order
  // fetch + cache - this only consumes it. Mode-gated to in-game via CSS
  // (hidden client/tft); JS hides when there's nothing to show. The
  // "BO|" sig prefix guarantees a DOM rewrite when switching modes.
  if (IB.dsPill) {
    const bo = buildOrderPill(p);
    if (bo) {
      const sig = `BO|${bo.html}`;
      if (IB.dsPill.dataset.dsSig !== sig) {
        IB.dsPill.dataset.dsSig = sig;
        IB.dsPill.innerHTML = bo.html;
        IB.dsPill.dataset.ttHtml = bo.tt; // app tooltip reads data-tt-html first
        IB.dsPill.removeAttribute("title");
      }
      IB.dsPill.hidden = false;
    } else {
      const top = dsPicks[0];
      if (top && top.name) {
        const delta = formatDsDelta(top);
        const sig = `${top.name}|${delta}`;
        if (IB.dsPill.dataset.dsSig !== sig) {
          IB.dsPill.dataset.dsSig = sig;
          IB.dsPill.innerHTML = `${top.name}<em>${delta}</em>`;
          if (IB.dsPill.dataset.ttHtml) delete IB.dsPill.dataset.ttHtml;
          IB.dsPill.title = `${top.name} · ${delta}` + (top.gold ? ` · ${top.gold}g` : '');
        }
        IB.dsPill.hidden = false;
      } else {
        IB.dsPill.hidden = true;
        IB.dsPill.dataset.dsSig = "";
      }
    }
  }
  state.lastTouch.item_build = Date.now() / 1000;
}

// In-game build chooser state. Lives inside #item-build (NOT the
// champ-select overlay). Pre-game variant selection persists in
// localStorage so this chooser highlights the same row by default.
// Mid-game pushes items only (runes + summoners are locked at game
// start). Declared here so the helpers below can reach it - moved out
// of panels/champ_select.js where the const was orphaned post-split
// (referenced only from this module, throwing ReferenceError on every
// SR/ARAM/Brawl state push).
const _ibBuilds = {
  lastChamp:  "",
  lastMode:   "",
  variants:   [],
  chosen:     "",
  inflight:   false,
  lastAppliedKey: "",
};

function _ibSetStatus(text, cls) {
  const el = document.getElementById("ib-builds-status");
  if (!el) return;
  el.className = "ib-builds-status" + (cls ? " " + cls : "");
  el.textContent = text || "";
}
function _ibStorageKey(champion) { return "rc-ingame-build-" + (champion || ""); }
function _ibSavedChoice(champion) {
  try { return localStorage.getItem(_ibStorageKey(champion)) || ""; }
  catch (_) { return ""; }
}
function _ibSaveChoice(champion, variant) {
  try { localStorage.setItem(_ibStorageKey(champion), variant); }
  catch (_) {}
}
function _ibRenderRows(variants, chosen) {
  const wrap = document.getElementById("ib-build-list");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!variants || !variants.length) return;
  const ver = CHAMPS.version || "latest";
  const diffIds = diffVariantItemIds(variants);
  variants.forEach((v) => {
    const row = document.createElement("div");
    const isExp = v.key === "experimental";
    row.className = "cs-build-row" + (v.key === chosen ? " selected" : "")
      + (isExp ? " experimental" : "");
    row.dataset.variant = v.key;
    const cb = document.createElement("div");
    cb.className = "cs-build-checkbox"; row.appendChild(cb);
    const meta = document.createElement("div");
    meta.className = "cs-build-meta";
    const label = document.createElement("div");
    label.className = "cs-build-label";
    label.textContent = v.label || v.key;
    meta.appendChild(label);
    const runes = document.createElement("div");
    runes.className = "cs-build-runes";
    runes.textContent = (v.keystone || "-");
    meta.appendChild(runes);
    row.appendChild(meta);
    const items = document.createElement("div");
    items.className = "cs-build-items";
    (v.item_ids || []).slice(0, 4).forEach((iid, idx) => {
      const cell = document.createElement("div");
      const isDiff = diffIds.has(String(iid));
      cell.className = "cs-build-item" + (isDiff ? " cs-build-item--diff" : "");
      const nm = (v.item_names || [])[idx] || ("item " + iid);
      cell.title = isDiff ? `${nm} (differs across variants)` : nm;
      cell.innerHTML = `<img src="/data/ddragon/${ver}/img/item/${iid}.png" onerror="this.style.display='none'" alt="">`;
      items.appendChild(cell);
    });
    row.appendChild(items);
    row.addEventListener("click", () => _ibOnRowClick(v.key));
    wrap.appendChild(row);
  });
}
function _ibMarkSelectedRow(variantKey) {
  const wrap = document.getElementById("ib-build-list");
  if (!wrap) return;
  wrap.querySelectorAll(".cs-build-row").forEach((r) => {
    if (r.dataset.variant === variantKey) r.classList.add("selected");
    else r.classList.remove("selected");
  });
}
function _ibPushItems(champion, variant, mode) {
  if (!champion || !variant) return;
  const key = champion + "|" + mode + "|" + variant;
  if (key === _ibBuilds.lastAppliedKey) return;
  if (_ibBuilds.inflight) return;
  _ibBuilds.inflight = true;
  _ibSetStatus("pushing…", "busy");
  fetch("/api/loadout/apply", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      champion: champion, variant: variant, mode: mode,
      push_runes: false, push_summoners: false, push_items: true,
    }),
  })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((data) => {
      _ibBuilds.inflight = false;
      if (!data || !data.ok) { _ibSetStatus("push failed", "err"); return; }
      _ibBuilds.lastAppliedKey = key;
      _ibSetStatus("✓ " + (data.label || variant), "ok");
      _ibMarkSelectedRow(variant);
      _ibSaveChoice(champion, variant);
    })
    .catch(() => { _ibBuilds.inflight = false; _ibSetStatus("push failed", "err"); });
}
function _ibOnRowClick(variant) {
  if (!variant) return;
  _ibBuilds.chosen = variant;
  _ibBuilds.lastAppliedKey = "";
  _ibMarkSelectedRow(variant);
  if (_ibBuilds.lastChamp && _ibBuilds.lastMode) {
    _ibPushItems(_ibBuilds.lastChamp, variant, _ibBuilds.lastMode);
  }
}
function _ibFetchAndRender(champion, mode) {
  fetch("/api/loadout/list", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ champion: champion, mode: mode }),
  })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((data) => {
      const block = document.getElementById("ib-builds-block");
      if (!data || !data.variants || data.variants.length < 2) {
        // <2 variants is uninteresting (just "default + experimental")
        // - hide rather than clutter the small panel.
        if (block) block.hidden = true;
        return;
      }
      if (block) block.hidden = false;
      _ibBuilds.variants = data.variants;
      // Default highlight: persisted pre-game choice if it's still a valid
      // variant for this champion+mode; otherwise the resolver's default.
      const saved = _ibSavedChoice(champion);
      const valid = data.variants.some((v) => v.key === saved);
      _ibBuilds.chosen = (saved && valid) ? saved : (data.default || data.variants[0].key);
      _ibRenderRows(data.variants, _ibBuilds.chosen);
      _ibSetStatus("ready · " + data.variants.length + " builds", "");
    })
    .catch(() => {});
}
function _ibMaybeRenderBuilds(p) {
  // Only show in modes where loadout variants make sense + the live
  // champion is known. Skip Arena/TFT (no fixed builds) and client mode.
  const mode = state.mode;
  const champion = p && p.champion;
  if (!champion || !["sr","aram","brawl"].includes(mode)) {
    const block = document.getElementById("ib-builds-block");
    if (block) block.hidden = true;
    return;
  }
  if (champion === _ibBuilds.lastChamp && mode === _ibBuilds.lastMode
      && _ibBuilds.variants.length) {
    // Already rendered for this champion+mode; nothing to do.
    return;
  }
  _ibBuilds.lastChamp = champion;
  _ibBuilds.lastMode  = mode;
  _ibBuilds.lastAppliedKey = "";
  _ibFetchAndRender(champion, mode);
}

// Single click handler shared by every row (no per-row delegation
// needed since we re-render the whole list on champion/variant change).

export {
  IB,
  renderItemBuild, renderItemTiles, _updateItemBuildHeader,
  _ibPushItems, _ibMaybeRenderBuilds, _ibFetchAndRender,
  _ibSetStatus, _ibRenderRows, _ibMarkSelectedRow, _ibSaveChoice,
};
