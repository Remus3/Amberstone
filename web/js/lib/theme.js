// Theme resolution + apply - the single source of truth for the DS2 palette
// swap (web/css/themes.css). Everything that reads or writes the theme goes
// through here; applyTheme is the ONLY writer of
// document.documentElement.dataset.theme.
//
// KEEP IN SYNC: the inline FOUC guard in web/index.html <head> duplicates the
// THEMES whitelist + the precedence below so the first paint is already
// themed. Changing THEMES here means changing that guard too (and the
// <option> list in the DISPLAY settings-card).

// hextech FIRST: it is the base palette (base.css :root owns the gold Hextech
// tokens) and is represented by the ABSENCE of the data-theme attribute.
export const THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"];

// Operator-chosen default (2026-07-22).
export const DEFAULT_THEME = "arcane";

// kebab-case, matching the rc-view-manual / rc-home-mode-tab / rc-ui-mock
// localStorage convention.
export const THEME_KEY = "rc-theme";

/** Stamp (or clear) <html data-theme>. Non-whitelisted names are ignored. */
export function applyTheme(name) {
  if (!THEMES.includes(name)) return;
  const root = document.documentElement;
  if (name === "hextech") {
    // Base palette: leave the attribute ABSENT so base.css :root wins.
    root.removeAttribute("data-theme");
  } else {
    root.dataset.theme = name;
  }
}

/** Whitelisted theme from localStorage, or null on miss / garbage / throw. */
export function readStoredTheme() {
  let v = null;
  try {
    v = localStorage.getItem(THEME_KEY);
  } catch (_) {
    return null;
  }
  return THEMES.includes(v) ? v : null;
}

/** Persist a whitelisted theme. Storage-disabled browsers degrade silently. */
export function saveTheme(name) {
  if (!THEMES.includes(name)) return;
  try {
    localStorage.setItem(THEME_KEY, name);
  } catch (_) {}
}

/** Whitelisted ?theme= override, or null when absent / not whitelisted. */
export function queryTheme() {
  const m = String(location.search || "").match(/[?&]theme=([A-Za-z]+)/);
  if (!m) return null;
  return THEMES.includes(m[1]) ? m[1] : null;
}

/** Precedence: ?theme= (session only) > stored preference > default. */
export function resolveBootTheme() {
  return queryTheme() || readStoredTheme() || DEFAULT_THEME;
}
