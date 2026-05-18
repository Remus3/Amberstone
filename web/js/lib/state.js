// Shared mutable state and view-routing constants.
// Panels import `state` and mutate its properties; they never re-assign the binding.

export const state = {
  mode: "client",      // current game mode tag
  frames: 0,
  logCount: 0,
  lastTouch: {         // epoch seconds per panel (drives staleness indicators)
    right_now: 0,
    next: 0,
    item_build: 0,
    minimap: 0,
  },
  latest: {},          // mode → latest coaching payload cache
  lastSseTs: 0,        // ms timestamp of last SSE event (dedup vs. HTTP fallback)
  // /api/state.mode_key is the canonical preflip/in-game resolver
  // (resolve_mode_key + cs_retention). onState records it here so
  // onHealth can defer to it instead of flapping body[data-mode] when
  // its own health source isn't preflip-mirrored. See onHealth in main.js.
  lastStateMode: "",   // last env.mode (mode_key) seen by onState
  lastStateModeTs: 0,  // ms timestamp of that observation
  spellCds: {},        // champion|spell → {remaining, anchor} cooldown state
  deadUntil: 0,        // ms timestamp when respawn timer expires
};

// Staleness thresholds per panel (seconds from spec §5).
export const CADENCE = {
  right_now:  { stale: 4,   severe: 12 },
  next:       { stale: 16,  severe: 48 },
  item_build: { stale: 90,  severe: 300 },
  minimap:    { stale: 4,   severe: 12 },
};

// All navigable view IDs (matches data-view attribute and URL hash).
// s209: dropped "loading" — games load too fast for the screen to be
// useful; ChampSelect now transitions directly to active-match.
export const VIEW_IDS = [
  "home", "lobby", "champ-select", "active-match", "last-match",
  "session", "history", "replay",
  "user-builds", "settings", "dev",
];

export const VIEW_LABELS = {
  "home": "Home", "lobby": "Pre-Game Lobby",
  "champ-select": "Champ Select",
  "active-match": "Active Match",
  "last-match": "Post Game Review",
  "session": "Session", "history": "History", "replay": "Replay",
  "user-builds": "User Builds",
  "settings": "Settings",
  "dev": "Dev",
};

// View-router mutable state (current + manual override + banner tracking).
//
// s171 added ``gameStarted`` — a sticky "highest game-state we've seen
// this session" flag (champ-select | game-start | in-progress | null).
// Used by _viewAutoDerive to ride through transient LCU phase=null /
// phase=Lobby blips during the CS→loading→game flip without flushing
// the view back to home/lobby. Cleared on stable post-game phases.
export const _VIEW = {
  current: null,
  manual: null,
  bannerDismissed: null,
  gameStarted: null,
};
