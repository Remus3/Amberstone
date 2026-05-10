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
export const VIEW_IDS = [
  "home", "lobby", "active-match", "last-match", "session", "history", "replay",
  "user-builds", "settings", "dev",
];

export const VIEW_LABELS = {
  "home": "Home", "lobby": "Pre-Game Lobby",
  "active-match": "Active Match",
  "last-match": "Last Match",
  "session": "Session", "history": "History", "replay": "Replay",
  "user-builds": "User Builds",
  "settings": "Settings",
  "dev": "Dev",
};

// View-router mutable state (current + manual override + banner tracking).
export const _VIEW = {
  current: null,
  manual: null,
  bannerDismissed: null,
};
