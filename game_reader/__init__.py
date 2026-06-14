# arch: GameReader facade - composes poller + normalizer mixins | section=vision | frozen=no
"""game_reader - Reads League of Legends game state from Riot's local APIs.

Live Client Data API (in-game): https://{RC_GAME_HOST}:2999/liveclientdata/
  - No auth required, runs automatically during any game.
  - Provides: champion stats, items, levels, CS, all players, events, game time.

LCU API (client/champ select): https://{RC_GAME_HOST}:{port}/
  - Auth from LeagueClientUx process command line / lockfile.
  - Provides: champ select picks/bans, summoner data.

Phase 2.2 split (was 1474-line monolith):
  poller.py             - Live Client / LCU / vision-relay IO
  snapshot_normalizer.py - raw JSON -> coaching state dict + derived fields
  mode_router.py        - TFT detection + mode-keyed helpers

Public surface preserved:
  GameReader              - instantiated by app/__init__.py (frozen),
                            core/sr_aram_worker.py, tests, tools/run_phase2_perf.py
  GameReader.to_rift_snapshot / to_aram_snapshot
                          - used as class-static factories by tests
  RELAY_MAX_AGE_S         - referenced in coaches/_base_coach.py docstring

No external dependencies - uses urllib + ssl from stdlib.
"""

import ssl

from .poller import (
    LCU_RELAY_MAX_AGE,
    LCU_RELAY_URL,
    LIVE_API,
    RELAY_MAX_AGE_S,
    RELAY_TOKEN,
    RELAY_URL,
    _PollerMixin,
)
from .snapshot_normalizer import (
    BARON_RESPAWN,
    DRAGON_RESPAWN,
    FIRST_ATAKHAN,
    FIRST_BARON,
    FIRST_DRAGON,
    FIRST_RIFT_HERALD,
    _NormalizerMixin,
    _normalize_name,
)


class GameReader(_PollerMixin, _NormalizerMixin):
    """Reads cached liveclient + frames; produces coaching snapshots.

    Method resolution order: poller methods (relay/HTTP/LCU/champ_select)
    sit before normalizer methods so `read_game` can invoke
    `self._process_game` via MRO into `_NormalizerMixin`. Cross-mixin
    calls (e.g. `_read_my_runes` -> `self._get`) resolve symmetrically.
    """

    def __init__(self):
        self._ssl = ssl.create_default_context()
        self._ssl.check_hostname = False
        self._ssl.verify_mode = ssl.CERT_NONE

        self.is_in_game = False
        self.raw = None

        # Enemy position tracking: {champ_name: {zone, time, x, z, dead}}
        self._enemy_last_seen: dict = {}
        # Enemy death time for respawn calculation: {champ_name: game_time_at_death}
        self._enemy_death_time: dict = {}

        # LCU connection
        self._lcu_port = None
        self._lcu_auth = None


__all__ = [
    "GameReader",
    "LIVE_API",
    "RELAY_URL",
    "RELAY_TOKEN",
    "RELAY_MAX_AGE_S",
    "LCU_RELAY_URL",
    "LCU_RELAY_MAX_AGE",
    "DRAGON_RESPAWN",
    "BARON_RESPAWN",
    "FIRST_DRAGON",
    "FIRST_RIFT_HERALD",
    "FIRST_BARON",
    "FIRST_ATAKHAN",
    "_normalize_name",
]
