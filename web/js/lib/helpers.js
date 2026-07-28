// Shared pure-utility functions - no DOM side-effects, no module state.
// Import specific exports; tree-shake unused helpers as needed.

// 12-hour clock. Accepts a Date or "HH:MM"/"HH:MM:SS" string.
// Duration formats (game time, cooldowns) stay as-is - only wall-clock.
export function _to12(input) {
  let h, m, s = null;
  if (input instanceof Date) {
    h = input.getHours(); m = input.getMinutes(); s = input.getSeconds();
  } else if (typeof input === "string") {
    const parts = input.split(":");
    if (parts.length < 2) return input;
    h = parseInt(parts[0], 10);
    m = parseInt(parts[1], 10);
    if (parts.length >= 3) s = parseInt(parts[2], 10);
    if (Number.isNaN(h) || Number.isNaN(m)) return input;
  } else { return ""; }
  const ampm = h >= 12 ? "PM" : "AM";
  let h12 = h % 12; if (h12 === 0) h12 = 12;
  const mm = String(m).padStart(2, "0");
  if (s !== null && !Number.isNaN(s)) {
    return `${h12}:${mm}:${String(s).padStart(2, "0")} ${ampm}`;
  }
  return `${h12}:${mm} ${ampm}`;
}

// Convenience wrapper for document.getElementById.
export const el = (id) => document.getElementById(id);

// Join an array or coerce a scalar to string.
export function fmtList(v) {
  if (Array.isArray(v)) return v.filter(Boolean).join(", ");
  return (v == null ? "" : String(v));
}

// Strip the coach inline bracket-markup tags - timer tags like [t]14s[/t]
// and sibling single-letter tags [x]...[/x] - that are an internal authoring
// convention, not display text. The paired form removes the WHOLE tag
// including its inner content (so [t]14s[/t] disappears, "14s" and all), then
// any stray/unclosed single-letter tag goes, then the whitespace the removal
// left behind is collapsed. Only single LOWERCASE-letter tags match, so item
// refs like [Kraken Slayer] and digit refs like [3153] are preserved. A
// no-tag string is returned byte-identical (internal whitespace kept) so
// folding this into safe() never alters non-coach values.
export function stripCoachTags(s) {
  if (s == null) return "";
  const str = String(s);
  const out = str
    .replace(/\[[a-z]\].*?\[\/[a-z]\]/gi, " ")
    .replace(/\[\/?[a-z]\]/gi, " ");
  return out === str ? str : out.replace(/\s+/g, " ").trim();
}

// Null-safe string trim. Also strips the coach bracket-timer tags (a no-op
// for non-coach values, which carry no single-letter bracket tags), so every
// render sink that already routes through safe() - right_now.js + next.js -
// inherits a tag-free, untruncated coach string and a clean clipboard copy.
export function safe(s) {
  if (s == null) return "";
  return stripCoachTags(String(s)).trim();
}

// Escape the five HTML-significant characters so an untrusted string can
// be safely interpolated into an innerHTML template literal. Use for any
// value sourced from the live client / LCU / a remote player (e.g.
// summoner names) before it lands inside an innerHTML build. A plain
// ASCII string is returned unchanged, so escaping is a no-op for normal
// inputs and only differs when the source carries < > & " ' (the XSS
// vector). Prefer element.textContent when building a single text node;
// this helper is for the template-literal innerHTML sites.
export function escHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Shrink font-size until content fits the element. <=0.5ms per call.
// Idempotent: skips if text + params haven't changed since last call.
export function fitText(elm, text, { max = 48, min = 16, step = 2, lines = null } = {}) {
  if (!elm) return;
  const fitKey = text + "|" + max + "|" + min + "|" + (lines ?? "");
  if (elm.dataset.fitKey === fitKey) return;
  elm.dataset.fitKey = fitKey;
  elm.textContent = text;
  if (!text || text === "-") return;
  elm.style.fontSize = max + "px";
  let size = max;
  const budget = () => lines
    ? Math.ceil(lines * size * 1.15)
    : elm.clientHeight + 1;
  while (size > min && elm.scrollHeight > budget()) {
    size -= step;
    elm.style.fontSize = size + "px";
  }
  while (size > min && elm.scrollWidth > elm.clientWidth + 1) {
    size -= step;
    elm.style.fontSize = size + "px";
  }
}

// No-op stub kept so call-sites compile after the Event Log panel was removed.
export function logLine(_src, _body, _cls) {}

// True when the coaching payload belongs to Arena mode.
export function isArenaPayload(p) {
  if (!p) return false;
  if (p.mode === "arena") return true;
  if (Array.isArray(p.teams) && p.teams.length &&
      p.teams.some(t => t && (t.is_partner || t.is_next_opponent))) return true;
  if (p.augment_advice || p.anvil_advice || p.round_strategy) return true;
  return false;
}

// Map the action headline to a CSS class: "urgent" | "fight" | "good".
export function classifyAction(text) {
  const t = (text || "").toUpperCase();
  if (/\b(DEAD|DANGER|DISENGAGE|FLEE|RECALL|RETREAT|BACK|BAIT|SURRENDER|GANK|COLLAPSE|DIVE|BOXED|CAUGHT|TRAPPED|RUN|ABORT|EMERGENCY|LOW HP|LOW MANA)\b/.test(t)
      || /^(BACK|FLEE|RECALL|DEAD|RUN|ABORT|GANK|DISENGAGE)/.test(t)) return "urgent";
  if (/\b(SAFE|WON|PUSH|CLEAR|OBJECTIVE|SECURED|FREE|SOUL|ACED|DOUBLE|TRIPLE|QUADRA|PENTA)\b/.test(t)) return "good";
  return "fight";
}

// Activity-event glyph prefix for fast peripheral-vision pattern matching.
export function _opGlyph(op) {
  const o = String(op || "").toLowerCase();
  if (o.includes("advisory"))        return "⚠";
  if (o.includes("analyze"))         return "⚗";
  if (o.includes("summary"))         return "Σ";
  if (o.includes("prime"))           return "✦";
  if (o.includes("digest"))          return "≡";
  if (o.includes("vision") || o.includes("screen")) return "◉";
  if (o.includes("game"))            return "▶";
  if (o.includes("file") || o.includes("ingest")) return "◧";
  if (o.includes("champ") || o.includes("pick")) return "♛";
  return "•";
}

// Human-readable relative age from a Unix timestamp (seconds).
export function _formatRelativeAge(unixSec) {
  if (!unixSec) return "-";
  const ageS = Math.max(0, (Date.now() / 1000) - unixSec);
  if (ageS < 60)    return `${Math.round(ageS)}s ago`;
  if (ageS < 3600)  return `${Math.round(ageS / 60)}m ago`;
  if (ageS < 86400) return `${(ageS / 3600).toFixed(1)}h ago`;
  return `${Math.round(ageS / 86400)}d ago`;
}
