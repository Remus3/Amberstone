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

// Remove every <...> tag. The removal repeats until nothing changes, so a tag
// can never be spliced back together by removing another one (CodeQL
// js/incomplete-multi-character-sanitization). For this pattern one pass
// already reaches the fixpoint - [^>]* consumes any inner "<" - so the loop
// costs one extra scan and changes no output. The result is TEXT, not safe
// HTML: an unterminated "<x" survives, so escape it (escHtml) or assign it
// via textContent / a DOM property before it reaches the page.
export function stripTags(s) {
  let out = String(s == null ? "" : s);
  let prev;
  do {
    prev = out;
    out = out.replace(/<[^>]*>/g, "");
  } while (out !== prev);
  return out;
}

// LoL / DDragon HTML (rune shortDesc etc.) -> plain text for a title= hover:
// strip every tag, decode the handful of entities DDragon emits, collapse
// whitespace. &amp; is decoded LAST so "&amp;lt;" decodes once to the literal
// text "&lt;" instead of twice to "<" (CodeQL js/double-escaping). Null-safe.
// Callers escape the result (escHtml) or assign it as text.
export function htmlToText(s) {
  return stripTags(s || "")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

// Rich app tooltip (main.js data-tt-html): build the tooltip DOM from an HTML
// string WITHOUT handing the string to innerHTML (CodeQL js/xss-through-dom).
// Only the tags the producers emit are rebuilt - lib/lol_descriptions item +
// keystone tips, the main.js games-by-mode tip, the last_match Quick Review
// `why` - which is div / span / b / i / br, each keeping at most its class
// attribute. Any other tag is dropped but its text is kept (script / style
// and the other raw-text elements lose their content too); text is inserted
// as text nodes with the entities escHtml emits, &apos; / &nbsp; and numeric
// references decoded (any other named entity stays literal - no producer
// emits one). Nothing in the attribute can execute, whoever wrote it, and the
// producers' markup rebuilds exactly.
const _TT_TAGS = { div: "div", span: "span", b: "b", i: "i", br: "br" };
const _TT_VOID = { br: true };
const _TT_SKIP = { script: true, style: true, template: true, textarea: true, title: true,
  iframe: true, noscript: true, noembed: true, noframes: true, object: true, xmp: true };
// nbsp built from its code point (160) so the source carries no glyph escape.
const _TT_ENT = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: String.fromCharCode(160) };

function _ttDecode(s) {
  return s.replace(/&(#[xX][0-9a-fA-F]+|#[0-9]+|[A-Za-z]+);/g, (m, e) => {
    if (e[0] === "#") {
      const hex = e[1] === "x" || e[1] === "X";
      const cp = parseInt(e.slice(hex ? 2 : 1), hex ? 16 : 10);
      const ok = cp > 0 && cp <= 0x10ffff && !(cp >= 0xd800 && cp <= 0xdfff);
      return ok ? String.fromCodePoint(cp) : m;
    }
    return Object.prototype.hasOwnProperty.call(_TT_ENT, e) ? _TT_ENT[e] : m;
  });
}

export function renderTooltipHtml(target, html) {
  if (!target) return;
  const doc = target.ownerDocument || document;
  while (target.firstChild) target.removeChild(target.firstChild);
  const src = String(html == null ? "" : html);
  const nodes = [target];
  const names = [""];
  const tagRe = /<!--[\s\S]*?-->|<(\/?)([A-Za-z][A-Za-z0-9-]*)([^>]*)>/g;
  let skip = "";
  let last = 0;
  const addText = (t) => {
    if (t && !skip) nodes[nodes.length - 1].appendChild(doc.createTextNode(_ttDecode(t)));
  };
  let m;
  while ((m = tagRe.exec(src)) !== null) {
    addText(src.slice(last, m.index));
    last = tagRe.lastIndex;
    if (m[2] === undefined) continue;            // comment
    const name = m[2].toLowerCase();
    const closing = m[1] === "/";
    if (skip) {
      if (closing && name === skip) skip = "";
      continue;
    }
    if (_TT_SKIP[name]) {
      if (!closing) skip = name;
      continue;
    }
    const tag = _TT_TAGS[name];
    if (!tag) continue;                          // not allowlisted: drop the tag, keep its text
    if (closing) {
      const at = names.lastIndexOf(tag);
      if (at > 0) { nodes.length = at; names.length = at; }
      continue;
    }
    const node = doc.createElement(tag);
    const cls = /(?:^|\s)class\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/i.exec(m[3]);
    if (cls) node.setAttribute("class", _ttDecode(cls[1] ?? cls[2] ?? cls[3]));
    nodes[nodes.length - 1].appendChild(node);
    if (!_TT_VOID[tag]) { nodes.push(node); names.push(tag); }
  }
  addText(src.slice(last));
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
