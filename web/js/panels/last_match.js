/* s219: Last Match panel.
 *
 * Renders the post-game review for the most-recent non-TFT match
 * captured in data/match_history.db. Wired into main.js via
 * applyView("last-match") → wireLastMatchOnce() + fetchAndRenderLastMatch().
 *
 * Data shape from /api/last-match (see dashboard/builders._build_last_match):
 *   {
 *     found, match: {id, mode, champion, grade, kda_str, kda_ratio,
 *                    duration_s, kills/deaths/assists, cs, cs_per_min,
 *                    gold, gold_per_min, kp_pct, ds_picks: [...]},
 *     history_count, quick_review: {right, wrong_team, my_chronic}
 *   }
 * Each Quick Review item is {text, why} — `why` becomes the data-tt-html
 * tooltip on hover so the analysis stays explainable.
 *
 * Champion deep-link: clicking the champion name stashes the champion to
 * sessionStorage.rc-history-focus-champion and routes to view-history
 * (mirrors the s218 Home Tonight's Pick "Jinx" name behavior).
 *
 * Deep Review button: stashes the match id to
 * sessionStorage.rc-review-focus-match and routes to view-review (placeholder
 * for the future deep-analysis page).
 */

let _wired = false;

/** One-time DOM wiring — click handlers, etc. Idempotent. */
export function wireLastMatchOnce() {
  if (_wired) return;
  _wired = true;

  const champEl = document.getElementById("lm-champion-name");
  if (champEl) {
    const goHistory = () => {
      const champ = champEl.dataset.champion || "";
      if (!champ) return;
      try { sessionStorage.setItem("rc-history-focus-champion", champ); } catch (_) {}
      try { location.hash = "#history"; } catch (_) {}
      if (typeof window._viewSaveManual === "function") window._viewSaveManual("history");
      if (typeof window._viewResolveAndApply === "function") window._viewResolveAndApply();
    };
    champEl.addEventListener("click", goHistory);
    champEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goHistory(); }
    });
  }

  const reviewBtn = document.getElementById("lm-go-to-review");
  if (reviewBtn) {
    reviewBtn.addEventListener("click", () => {
      const mid = reviewBtn.dataset.matchId || "";
      if (mid) {
        try { sessionStorage.setItem("rc-review-focus-match", mid); } catch (_) {}
      }
      try { location.hash = "#review"; } catch (_) {}
      if (typeof window._viewSaveManual === "function") window._viewSaveManual("review");
      if (typeof window._viewResolveAndApply === "function") window._viewResolveAndApply();
    });
  }
}

/** Fetch latest match + render into DOM. Safe to call repeatedly. */
export function fetchAndRenderLastMatch() {
  fetch("/api/last-match", { headers: { "Accept": "application/json" } })
    .then((r) => r.json())
    .then((data) => renderLastMatch(data))
    .catch((err) => {
      // Surface in console; leave any pre-existing rendered state in place.
      try { console.warn("[last-match] fetch failed:", err); } catch (_) {}
    });
}

function renderLastMatch(data) {
  if (!data || !data.found) {
    _setEmptyState(data && data.error);
    return;
  }
  const m = data.match || {};
  const qr = data.quick_review || {};

  _setHero(m);
  _setStatsGrid(m);
  _setDsPicks(m.ds_picks || []);
  _setQuickReview(qr);
  _setReviewButton(m);
  _setMeta(m, data.history_count);
}

function _setMeta(m, historyCount) {
  const meta = document.getElementById("lm-meta");
  if (!meta) return;
  const when = _fmtAgo(m.timestamp);
  const parts = [m.mode || "—", _fmtDuration(m.duration_s), when];
  if (typeof historyCount === "number" && historyCount > 0) {
    parts.push(`baseline · ${historyCount} prior games`);
  }
  meta.textContent = parts.filter(Boolean).join(" · ");
}

function _setHero(m) {
  const portrait = document.getElementById("lm-portrait");
  const champEl = document.getElementById("lm-champion-name");
  const modeTag = document.getElementById("lm-mode-tag");
  const kdaText = document.getElementById("lm-kda-text");
  const kdaRatio = document.getElementById("lm-kda-ratio");
  const grade = document.getElementById("lm-grade-badge");
  const heroBox = document.querySelector(".lm-hero");

  const champion = m.champion || "?";
  const champKey = _resolveChampKey(champion);
  if (portrait) {
    portrait.src = champKey ? `/icons/champions/${champKey}.png` : "";
    portrait.alt = champion;
  }
  if (champEl) {
    champEl.textContent = champion;
    champEl.dataset.champion = champion;
  }
  if (modeTag) modeTag.textContent = m.mode || "—";
  if (kdaText) kdaText.textContent = m.kda_str || "—/—/—";
  if (kdaRatio) {
    const r = m.kda_ratio;
    kdaRatio.textContent = (typeof r === "number") ? `${r.toFixed(2)} KDA` : "—";
  }
  const g = (m.grade || "—").toUpperCase().trim();
  if (grade) {
    grade.textContent = g || "—";
    grade.dataset.grade = (g && g !== "—") ? g : "";
  }
  if (heroBox) {
    heroBox.dataset.grade = (g && g !== "—") ? g : "";
  }
}

function _setStatsGrid(m) {
  const cs = document.getElementById("lm-cs");
  const cspm = document.getElementById("lm-cs-per-min");
  const gold = document.getElementById("lm-gold");
  const gpm = document.getElementById("lm-gold-per-min");
  const kp = document.getElementById("lm-kp");
  const dur = document.getElementById("lm-duration");
  const when = document.getElementById("lm-when");

  if (cs) cs.textContent = (m.cs != null && m.cs > 0) ? String(m.cs) : "—";
  if (cspm) cspm.textContent = (typeof m.cs_per_min === "number")
    ? `${m.cs_per_min.toFixed(1)} CS/min` : "—";
  if (gold) gold.textContent = (m.gold != null && m.gold > 0)
    ? _fmtGold(m.gold) : "—";
  if (gpm) gpm.textContent = (typeof m.gold_per_min === "number" && m.gold_per_min > 0)
    ? `${Math.round(m.gold_per_min)} / min` : "—";
  if (kp) kp.textContent = (typeof m.kp_pct === "number") ? `${Math.round(m.kp_pct)}%` : "—";
  if (dur) dur.textContent = _fmtDuration(m.duration_s);
  if (when) when.textContent = _fmtAgo(m.timestamp);
}

function _setDsPicks(picks) {
  const root = document.getElementById("lm-ds-picks");
  if (!root) return;
  if (!picks || !picks.length) {
    root.innerHTML = '<span class="lm-empty">no DS data captured for this match</span>';
    return;
  }
  const html = picks.slice(0, 5).map((p) => {
    const name = String(p.name || "?");
    const id = String(p.id || "");
    const delta = (typeof p.delta === "number") ? p.delta
                 : (typeof p.delta_dps === "number") ? p.delta_dps : null;
    const scorer = p.scorer || "dps";
    const unit = _scorerUnit(scorer);
    const deltaTxt = (delta != null) ? `+${Math.round(delta)}${unit}` : "";
    const iconSrc = id ? `/data/ddragon/img/item/${id}.png` : "";
    const safeName = _escHtml(name);
    return `<div class="lm-build-item" title="${safeName} (${scorer})">
      <img src="${iconSrc}" alt="${safeName}" loading="lazy" onerror="this.style.visibility='hidden'">
      <span class="lm-build-item-name">${safeName}</span>
      <span class="lm-build-item-delta">${deltaTxt}</span>
    </div>`;
  }).join("");
  root.innerHTML = html;
}

function _setQuickReview(qr) {
  _renderQrColumn("lm-qr-right", qr.right);
  _renderQrColumn("lm-qr-wrong", qr.wrong_team);
  _renderQrColumn("lm-qr-chronic", qr.my_chronic);
}

function _renderQrColumn(elementId, items) {
  const ul = document.getElementById(elementId);
  if (!ul) return;
  if (!items || !items.length) {
    ul.innerHTML = '<li class="lm-qr-empty">no signal</li>';
    return;
  }
  const html = items.map((it) => {
    const text = String(it && it.text || "");
    const why  = String(it && it.why  || "");
    const safeText = _escHtml(text);
    const safeWhy  = _escHtml(why);
    return `<li data-tt-html="${safeWhy.replace(/"/g, "&quot;")}">${safeText}</li>`;
  }).join("");
  ul.innerHTML = html;
}

function _setReviewButton(m) {
  const btn = document.getElementById("lm-go-to-review");
  if (!btn) return;
  btn.dataset.matchId = String(m.id || "");
  btn.disabled = !m.id;
}

function _setEmptyState(errMsg) {
  const heroBox = document.querySelector(".lm-hero");
  if (heroBox) heroBox.dataset.grade = "";
  const meta = document.getElementById("lm-meta");
  if (meta) {
    meta.textContent = errMsg
      ? `no match data — ${errMsg}`
      : "no matches captured yet";
  }
  const champEl = document.getElementById("lm-champion-name");
  if (champEl) { champEl.textContent = "—"; champEl.dataset.champion = ""; }
  ["lm-mode-tag","lm-kda-text","lm-kda-ratio","lm-grade-badge",
   "lm-cs","lm-cs-per-min","lm-gold","lm-gold-per-min",
   "lm-kp","lm-duration","lm-when"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.textContent = "—";
  });
  const dsRoot = document.getElementById("lm-ds-picks");
  if (dsRoot) dsRoot.innerHTML = '<span class="lm-empty">no match yet</span>';
  ["lm-qr-right","lm-qr-wrong","lm-qr-chronic"].forEach((id) => {
    const ul = document.getElementById(id);
    if (ul) ul.innerHTML = '<li class="lm-qr-empty">no signal yet</li>';
  });
}

/* ── helpers ───────────────────────────────────────────────────────── */

function _fmtDuration(s) {
  const t = Number(s) || 0;
  if (t <= 0) return "—";
  const mm = Math.floor(t / 60);
  const ss = Math.floor(t % 60);
  return `${mm}:${ss.toString().padStart(2, "0")}`;
}

function _fmtGold(g) {
  const n = Number(g) || 0;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function _fmtAgo(timestamp) {
  if (!timestamp) return "—";
  // match_history.db uses "YYYY-MM-DD HH:MM:SS" local time
  const t = Date.parse(String(timestamp).replace(" ", "T"));
  if (isNaN(t)) return "—";
  const delta = (Date.now() - t) / 1000;
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  const days = Math.floor(delta / 86400);
  return `${days}d ago`;
}

function _resolveChampKey(name) {
  // Mirror of main.js _resolveChampId — try the window-level resolver
  // if available, else best-effort capitalize+strip-spaces.
  if (typeof window._resolveChampId === "function") {
    try { return window._resolveChampId(name) || ""; } catch (_) {}
  }
  if (!name) return "";
  return String(name).replace(/[^A-Za-z]/g, "");
}

function _scorerUnit(scorer) {
  // Mirror of scorer_units.js scorerUnit — kept local to avoid an
  // import cycle on the rare chance that file moves.
  switch ((scorer || "").toLowerCase()) {
    case "ehp":     return "ehp";
    case "hybrid":  return "%";
    case "ability": return "adps";
    case "burst":   return "burst";
    case "hps":     return "hps";
    case "dps":
    default:        return "dps";
  }
}

function _escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
