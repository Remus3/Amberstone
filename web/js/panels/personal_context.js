// Personal context surface (ADR-007 phase 2 follow-up; CLAUDE.md item 124).
//
// Fetches /api/personal-context and paints the top-3 recurring death
// patterns inside the Right Now panel - the same top-3 the mode coaches
// inject into their system prompts via core.death_patterns_loader.
// Hidden when no data; muted empty-state when the file is missing.
//
// Each card: pattern label + count chip + rate% chip stacked over a
// muted single-line description. Card border tint derives from the
// pattern key (positioning -> warn, solo -> info, time-window -> dim).
//
// Refresh cadence: 60s polling on the home view. The backend's 60s
// mtime-keyed cache means most polls are cheap.

const SECTION_ID = "personal-context-section";
const LIST_ID    = "personal-context-list";
const EMPTY_ID   = "personal-context-empty";
const RG_SECTION_ID  = "personal-context-rolegrade";
const RG_SCORE_ID    = "personal-context-rolegrade-score";
const RG_COUNT_ID    = "personal-context-rolegrade-count";
const RG_TIERS_ID    = "personal-context-rolegrade-tiers";
const RG_BYROLE_ID   = "personal-context-rolegrade-byrole";

const RG_TIER_ORDER = ["S+", "S", "A", "B", "C", "D"];
const RG_CANONICAL_ROLES = ["TOP", "JG", "MID", "ADC", "SUP"];

const REFRESH_INTERVAL_MS = 60 * 1000;

let _pollTimer = null;
let _lastSig   = "";

// Map pattern key -> semantic kind for border tinting. New keys fall
// through to "default" which is a single muted tint.
const KIND_BY_KEY = {
  caught_4plus:   "warn",
  solo_1v1_loss:  "info",
  early_pre_3min: "dim",
  solo_pickoff:   "info",
  late_throw:     "dim",
  rapid_repeat:   "warn",
};

function _kindFor(key) {
  return KIND_BY_KEY[key] || "default";
}

function _formatPct(rate) {
  if (typeof rate !== "number" || isNaN(rate)) return "";
  const pct = Math.round(rate * 100);
  return pct + "%";
}

function _formatCount(n) {
  if (typeof n !== "number" || isNaN(n)) return "0";
  // Thin space separators for thousands keep the chip narrow at 1920x1080.
  if (n >= 1000) {
    return n.toLocaleString("en-US");
  }
  return String(n);
}

function _escape(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function _cardHtml(p) {
  const key   = p && p.key   ? String(p.key)   : "";
  const label = p && p.label ? String(p.label) : key || "?";
  const desc  = p && p.description ? String(p.description) : "";
  const count = p && typeof p.count === "number" ? p.count : 0;
  const rate  = p && typeof p.rate  === "number" ? p.rate  : 0;
  const kind  = _kindFor(key);
  return `
    <div class="personal-context-card" data-kind="${_escape(kind)}" data-key="${_escape(key)}"
         title="${_escape(desc)}">
      <div class="personal-context-row">
        <span class="personal-context-label">${_escape(label)}</span>
        <span class="personal-context-count tabular-nums">${_escape(_formatCount(count))}</span>
        <span class="personal-context-rate tabular-nums">${_escape(_formatPct(rate))}</span>
      </div>
      <div class="personal-context-desc">${_escape(desc)}</div>
    </div>`;
}

function _signature(data) {
  if (!data || !data.ok) return data && data.reason ? "empty:" + data.reason : "";
  const top3 = Array.isArray(data.top3) ? data.top3 : [];
  const top3Sig = top3.map((p) => `${p.key}:${p.count}:${p.rate}`).join("|");
  const rg = data.role_grades;
  if (!rg || typeof rg !== "object") return top3Sig;
  const overall = rg.overall || {};
  const byRole = rg.by_role || {};
  const rolesSig = RG_CANONICAL_ROLES
    .map((r) => `${r}:${(byRole[r] && byRole[r].count) || 0}:${(byRole[r] && byRole[r].median_score) || 0}`)
    .join(",");
  const rgSig = `rg:${rg.total_matches_scored || 0}:${overall.median_score || 0}:${rolesSig}`;
  return `${top3Sig}::${rgSig}`;
}

function _scoreTier(score) {
  if (typeof score !== "number" || isNaN(score)) return "D";
  if (score >= 85) return "S+";
  if (score >= 75) return "S";
  if (score >= 65) return "A";
  if (score >= 50) return "B";
  if (score >= 35) return "C";
  return "D";
}

function _tierChipHtml(tier, count) {
  const safeTier = String(tier);
  const safeCount = typeof count === "number" ? count : 0;
  return `<span class="personal-context-rolegrade-tier" data-tier="${_escape(safeTier)}">
    <span class="personal-context-rolegrade-tier-label">${_escape(safeTier)}</span>
    <span class="personal-context-rolegrade-tier-count tabular-nums">${_escape(String(safeCount))}</span>
  </span>`;
}

function _roleRowHtml(role, bucket) {
  const count = (bucket && typeof bucket.count === "number") ? bucket.count : 0;
  const score = (bucket && typeof bucket.median_score === "number") ? bucket.median_score : 0;
  const tier = _scoreTier(score);
  return `<div class="personal-context-rolegrade-role" data-role="${_escape(role)}" data-tier="${_escape(tier)}">
    <span class="personal-context-rolegrade-role-name">${_escape(role)}</span>
    <span class="personal-context-rolegrade-role-score tabular-nums">${_escape(String(score))}</span>
    <span class="personal-context-rolegrade-role-count tabular-nums">${_escape(String(count))}</span>
  </div>`;
}

function _renderRoleGrades(rg) {
  const section = document.getElementById(RG_SECTION_ID);
  if (!section) return;
  if (!rg || typeof rg !== "object") {
    section.hidden = true;
    return;
  }
  const overall = rg.overall || {};
  const totalScored = overall.count || rg.total_matches_scored || 0;
  if (totalScored <= 0) {
    section.hidden = true;
    return;
  }
  const scoreEl = document.getElementById(RG_SCORE_ID);
  const countEl = document.getElementById(RG_COUNT_ID);
  const tiersEl = document.getElementById(RG_TIERS_ID);
  const byRoleEl = document.getElementById(RG_BYROLE_ID);
  if (!scoreEl || !countEl || !tiersEl || !byRoleEl) return;
  const medianScore = typeof overall.median_score === "number" ? overall.median_score : 0;
  scoreEl.textContent = String(medianScore);
  scoreEl.setAttribute("data-tier", _scoreTier(medianScore));
  countEl.textContent = totalScored === 1 ? "1 match" : `${totalScored} matches`;
  const tiers = overall.tier_distribution || {};
  tiersEl.innerHTML = RG_TIER_ORDER
    .map((t) => _tierChipHtml(t, tiers[t] || 0))
    .join("");
  const byRole = rg.by_role || {};
  const rows = RG_CANONICAL_ROLES
    .filter((role) => {
      const bucket = byRole[role];
      return bucket && typeof bucket.count === "number" && bucket.count > 0;
    })
    .map((role) => _roleRowHtml(role, byRole[role]));
  byRoleEl.innerHTML = rows.join("");
  section.hidden = false;
}

export function renderPersonalContext(data) {
  const section = document.getElementById(SECTION_ID);
  if (!section) return;
  const list  = document.getElementById(LIST_ID);
  const empty = document.getElementById(EMPTY_ID);
  if (!list || !empty) return;

  const sig = _signature(data);
  if (sig === _lastSig) return;
  _lastSig = sig;

  if (!data || !data.ok) {
    // Empty state: muted single chip explaining why nothing is here.
    // Only render the section + empty chip when the loader has been
    // queried at least once (data present but ok=false); a completely
    // missing fetch keeps the section hidden.
    if (data && data.reason === "no_data") {
      list.innerHTML = "";
      empty.textContent = "No personal context yet - postmortem hasn't run, or you haven't been the victim in any tracked matches.";
      empty.hidden = false;
      section.hidden = false;
    } else {
      section.hidden = true;
      list.innerHTML = "";
      empty.hidden = true;
    }
    _renderRoleGrades(null);
    return;
  }

  const top3 = Array.isArray(data.top3) ? data.top3 : [];
  if (top3.length === 0) {
    section.hidden = true;
    list.innerHTML = "";
    empty.hidden = true;
    _renderRoleGrades(null);
    return;
  }
  list.innerHTML = top3.map(_cardHtml).join("");
  empty.hidden = true;
  section.hidden = false;
  _renderRoleGrades(data.role_grades);
}

export async function loadPersonalContext() {
  try {
    const r = await fetch("/api/personal-context", { cache: "no-store" });
    if (!r.ok) {
      // 500 or similar: keep prior state, do nothing. The next poll
      // will retry.
      return;
    }
    const data = await r.json();
    renderPersonalContext(data);
  } catch (e) {
    // Network / parse: same fail-soft contract as the backend.
    console.warn("personal-context fetch error:", e);
  }
}

export function startPersonalContextPolling() {
  if (_pollTimer !== null) return;
  loadPersonalContext();
  _pollTimer = setInterval(loadPersonalContext, REFRESH_INTERVAL_MS);
}

export function stopPersonalContextPolling() {
  if (_pollTimer !== null) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

// Test seam.
export const _internals = {
  SECTION_ID,
  LIST_ID,
  EMPTY_ID,
  RG_SECTION_ID,
  RG_SCORE_ID,
  RG_COUNT_ID,
  RG_TIERS_ID,
  RG_BYROLE_ID,
  RG_TIER_ORDER,
  RG_CANONICAL_ROLES,
  REFRESH_INTERVAL_MS,
  KIND_BY_KEY,
  _cardHtml,
  _signature,
  _formatPct,
  _formatCount,
  _kindFor,
  _scoreTier,
  _tierChipHtml,
  _roleRowHtml,
  _renderRoleGrades,
};
