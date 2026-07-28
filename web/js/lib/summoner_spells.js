// Summoner spell ID -> DDragon slug + friendly name. Shared by the
// champ-select build chooser (rune+spell strip), the active-match
// minimap legend, and any other surface that renders summoner-spell
// icons keyed by Riot's numeric spell IDs.
//
// Source: hand-curated from /lol-summoner-spells/v1/summoner-spells.
// Resurrected from the s209-deleted loading.js panel; live at
// `web/js/lib/summoner_spells.js` so callers don't reach across panels.
// Local files live at data/icons/spells/<slug>.png (served by
// dashboard/routes_static.py:191 -> /icons/spells/<slug>.png).

export const SUM_SPELLS = {
  1:  "SummonerBoost",        // Cleanse
  3:  "SummonerExhaust",
  4:  "SummonerFlash",
  6:  "SummonerHaste",        // Ghost
  7:  "SummonerHeal",
  11: "SummonerSmite",
  12: "SummonerTeleport",
  13: "SummonerMana",         // Clarity (ARAM)
  14: "SummonerDot",          // Ignite
  21: "SummonerBarrier",
  32: "SummonerSnowball",     // ARAM Mark
};

export const SUM_NAMES = {
  1:  "Cleanse",
  3:  "Exhaust",
  4:  "Flash",
  6:  "Ghost",
  7:  "Heal",
  11: "Smite",
  12: "Teleport",
  13: "Clarity",
  14: "Ignite",
  21: "Barrier",
  32: "Mark",
};

// Returns "/icons/spells/<slug>.png" for known spell IDs; "" for unknown.
export function sumImg(spellId) {
  const slug = SUM_SPELLS[spellId | 0];
  return slug ? `/icons/spells/${slug}.png` : "";
}

// Returns "Flash" / "Heal" / etc. - empty string for unknown spell IDs.
export function sumName(spellId) {
  return SUM_NAMES[spellId | 0] || "";
}
