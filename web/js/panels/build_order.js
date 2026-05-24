// DS vs Enemy Comp panel (2026-05-17, OVERNIGHT RUN-1 follow-up; plan §6b B+C).
//
// Renders the contextual, match-specific DS-backed item BUILD ORDER from
// POST /api/build-order (core/build_order.py plan_build_order). Two
// surfaces:
//   (B) a collapsible "DS vs Enemy Comp" block inside the champ-select My Pick
//       card - mode-agnostic (sr/aram/arena), since a build order matters
//       just as much in ARAM/Arena. buildOrderCardHtml() returns an HTML
//       string; champ_select.js injects it after the build chooser,
//       passing the DDragon ver + its rAF re-render callback.
//   (C) the in-game #ds-pill glance - buildOrderPill(state) returns the
//       next-2-in-order + a full-order rich tooltip; item_build.js (which
//       owns #ds-pill) consumes it and falls back to its top-pick render
//       when this returns null.
//
// Cost discipline: the route is N sequential engine calls (opt-in / NOT
// per-tick - see the plan + archetype_dispatch.with_build_order). A build
// order is a full-game plan, not a per-level snapshot, so we cache per
// (champion|dsMode|archetype) at a FIXED planning level. Net = exactly one
// fetch per champ+mode+arch per session - mirrors champ_select.js's
// _csvFetchDsBuilds caching discipline (presence-guarded, inflight-gated).
//
// The hard no-double rule (never two items sharing a unique passive) is
// engine-authoritative - the route already enforces it; this module only
// renders `unique_passive_safe` + any per-slot excluded_family signal.

const BO_PLAN_LEVEL = 13; // full-build planning level (matches the plan's curl example)
const BO_SLOTS = 6;

const _BO_CACHE = Object.create(null); // key -> route JSON
const _BO_INFLIGHT = Object.create(null); // key -> true while fetching
let _boExpanded = false; // session-ephemeral expander state (progressive disclosure)

function _boKey(champion, dsMode, archetype) {
  return `${champion}|${dsMode}|${archetype || ""}`;
}

// Escape for both text nodes and attribute values (data-tt-html / title).
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _deltaTxt(o) {
  const unit = o.unit || "dps";
  const d = Math.round(o.delta || 0);
  return (d >= 0 ? "+" : "") + d + unit;
}

// Fire the build-order route once per (champion, dsMode, archetype). The
// onLand callback re-renders the consuming view (champ-select passes
// _csvScheduleRender; in-game the next item_build tick picks up the cache,
// so null is fine there).
function fetchBuildOrder(champion, dsMode, archetype, onLand) {
  if (!champion || !dsMode) return;
  const key = _boKey(champion, dsMode, archetype);
  if (_BO_CACHE[key] || _BO_INFLIGHT[key]) return;
  _BO_INFLIGHT[key] = true;
  const body = {
    champion,
    mode: dsMode,
    level: BO_PLAN_LEVEL,
    items: [],
    slots: BO_SLOTS,
  };
  if (archetype) body.archetype = archetype;
  fetch("/api/build-order", {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _BO_INFLIGHT[key] = false;
      if (data && data.ok && Array.isArray(data.order) && data.order.length) {
        _BO_CACHE[key] = data;
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => {
      _BO_INFLIGHT[key] = false;
    });
}

export function getCachedBuildOrder(champion, dsMode, archetype) {
  return _BO_CACHE[_boKey(champion, dsMode, archetype)] || null;
}

// ── (B) champ-select card ─────────────────────────────────────────────

// `opts`: { ver, scheduleRender }. Returns an HTML string for injection
// into the My Pick card body (after the build chooser). Returns "" when
// there's no champion yet so the card simply doesn't appear.
export function buildOrderCardHtml(champion, dsMode, archetype, opts) {
  opts = opts || {};
  if (!champion || champion === "-" || !dsMode) return "";
  const key = _boKey(champion, dsMode, archetype);
  const data = _BO_CACHE[key];
  if (!data) {
    fetchBuildOrder(champion, dsMode, archetype, opts.scheduleRender);
    return `
      <div class="bo-card" data-bo-state="loading">
        <div class="bo-line"><span class="bo-tag">DS vs Enemy Comp</span><span class="bo-msg">computing...</span></div>
      </div>`;
  }
  const order = Array.isArray(data.order) ? data.order : [];
  if (!order.length) {
    return `
      <div class="bo-card" data-bo-state="empty">
        <div class="bo-line"><span class="bo-tag">DS vs Enemy Comp</span><span class="bo-msg">no ordered build</span></div>
      </div>`;
  }
  const ver = opts.ver || "latest";
  const ctx = data.context || {};
  const ctxBits = [];
  if (ctx.target_armor != null) ctxBits.push(`${Math.round(ctx.target_armor)} armor`);
  if (ctx.target_mr != null) ctxBits.push(`${Math.round(ctx.target_mr)} MR`);
  if (ctx.target_max_hp != null) ctxBits.push(`${Math.round(ctx.target_max_hp)} HP`);
  const ctxLine = ctxBits.length ? `vs ${ctxBits.join(" · ")}` : "";

  const safeChip = data.unique_passive_safe
    ? `<span class="bo-safe" title="no two items share a unique passive - engine-enforced">no-double ✓</span>`
    : `<span class="bo-unsafe" title="unique-passive collision - engine guard did not hold">⚠ double</span>`;

  // Full numbered order + per-slot math - also the collapsed-line hover
  // (so the dense default still gives the operator the deeper math).
  const fullTip =
    order
      .map(
        (o) =>
          `${o.slot}. ${_esc(o.item_name)} - ${_esc(_deltaTxt(o))}, ${o.gold || 0}g` +
          (o.excluded_family ? ` · locks ${_esc(o.excluded_family)}` : ""),
      )
      .join("<br>") +
    (ctxLine ? `<br>${_esc(ctxLine)}` : "");

  // Collapsed (default) - ONE dense line: tag · ordered-name chain
  // (ellipsis-clips, full order in the tooltip) · no-double chip ·
  // expander. This is the density-optimal default for the tight My Pick
  // card (trim content, not font - feedback_font_size_viewing_distance).
  if (!_boExpanded) {
    const chain = order.map((o) => _esc(o.item_name)).join(" → ");
    return `
    <div class="bo-card" data-bo-state="ready" data-bo-collapsed="1">
      <div class="bo-line">
        <span class="bo-tag">DS vs Enemy Comp</span>
        <span class="bo-chain" data-tt-html="${fullTip}">${chain}</span>
        ${safeChip}
        <button type="button" class="bo-expander" data-bo-toggle="1" title="show full ordered build">▾</button>
      </div>
    </div>`;
  }

  // Expanded - full numbered vertical list, readable fonts, per-slot
  // delta + excluded-family signal + a deeper-math tooltip per slot.
  const rows = order
    .map((o) => {
      const dt = _deltaTxt(o);
      const excl = o.excluded_family
        ? `<div class="bo-excl">locks ${_esc(o.excluded_family)}` +
          (o.excluded_example ? ` · ${_esc(o.excluded_example)} dropped` : "") +
          `</div>`
        : "";
      const tip =
        `Slot ${o.slot}: ${_esc(o.item_name)} - ${_esc(dt)}, ${o.gold || 0}g` +
        (ctxLine ? ` (${_esc(ctxLine)})` : "") +
        (o.scorer ? ` · scorer ${_esc(o.scorer)}` : "") +
        (o.excluded_family
          ? ` · locks the ${_esc(o.excluded_family)} unique-passive family`
          : "");
      return `
      <div class="bo-slot" data-tt-html="${tip}">
        <span class="bo-num">${o.slot}</span>
        <img class="bo-icon" src="/data/ddragon/${ver}/img/item/${o.item_id}.png"
             onerror="if(!this.dataset.cdn){this.dataset.cdn=1;this.src='https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${o.item_id}.png'}else{this.style.visibility='hidden'}"
             alt="">
        <span class="bo-name">${_esc(o.item_name)}</span>
        <span class="bo-delta">${_esc(dt)}</span>
        ${excl}
      </div>`;
    })
    .join("");

  return `
    <div class="bo-card" data-bo-state="ready">
      <div class="bo-line">
        <span class="bo-tag">DS vs Enemy Comp</span>
        ${ctxLine ? `<span class="bo-ctx">${_esc(ctxLine)}</span>` : ""}
        ${safeChip}
        <button type="button" class="bo-expander" data-bo-toggle="1" title="collapse">▴</button>
      </div>
      <div class="bo-slots">${rows}</div>
    </div>`;
}

// One delegated click handler for the expander. The card HTML is
// re-injected on every champ-select render, so a per-element listener
// won't survive - delegate on document, wired once at module load (same
// idiom as archetype_nudge_chip.js's X-button). champ_select.js listens
// for the dispatched event and schedules a re-render.
document.addEventListener("click", (ev) => {
  const btn =
    ev.target && ev.target.closest && ev.target.closest("[data-bo-toggle]");
  if (!btn) return;
  ev.stopPropagation();
  _boExpanded = !_boExpanded;
  document.dispatchEvent(new CustomEvent("rc:build-order-toggle"));
});

// ── (C) in-game #ds-pill glance ───────────────────────────────────────

// Returns { html, tt } for the pill, or null when not applicable (not
// in-game, no champion, or order not cached yet). item_build.js owns
// #ds-pill; on null it falls back to its existing top-pick render.
export function buildOrderPill(stateObj) {
  if (!stateObj) return null;
  const champ =
    stateObj.champion ||
    (stateObj.coach && stateObj.coach.champion) ||
    "";
  if (!champ || champ === "-") return null;
  // In-game we don't have the CS queue id; map from mode flags. Default
  // SR (the route is still valid; the card (B) is the mode-correct
  // planned-build surface - this pill is the glance companion).
  let dsMode = "SR";
  if (stateObj.aram_mode) dsMode = "ARAM";
  else if (stateObj.arena_mode) dsMode = "ARENA";
  const archetype = ""; // backend auto-resolves via core.archetype_picks
  const data = getCachedBuildOrder(champ, dsMode, archetype);
  if (!data) {
    fetchBuildOrder(champ, dsMode, archetype, null);
    return null;
  }
  const order = Array.isArray(data.order) ? data.order : [];
  if (!order.length) return null;
  // Advance the cursor past items already owned (client-side; v1 plans
  // from empty - live re-derivation is the plan's Phase 4).
  const owned = Array.isArray(stateObj.owned_item_ids)
    ? stateObj.owned_item_ids.map((x) => String(x))
    : [];
  const remaining = order.filter((o) => owned.indexOf(String(o.item_id)) < 0);
  const next2 = (remaining.length ? remaining : order).slice(0, 2);
  const html = `▸ ${next2.map((o) => _esc(o.item_name)).join(" → ")}`;
  const full = order
    .map(
      (o) =>
        `${o.slot}. ${_esc(o.item_name)} (${_esc(_deltaTxt(o))}, ${o.gold || 0}g)`,
    )
    .join("<br>");
  const tt = `Build order${
    data.unique_passive_safe ? " · no-double ✓" : ""
  }:<br>${full}`;
  return { html, tt };
}

// Test/diagnostic helper - clears caches + collapses the card so the next
// render fetches + writes unconditionally (mirrors _resetArchetypeNudgeSig).
export function _resetBuildOrder() {
  for (const k of Object.keys(_BO_CACHE)) delete _BO_CACHE[k];
  for (const k of Object.keys(_BO_INFLIGHT)) delete _BO_INFLIGHT[k];
  _boExpanded = false;
}
