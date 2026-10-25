"""tft/sources - the passive per-round file feeds of the standalone TFT client
(docs/TFT_PROGRAM.md section 0 items 2 and 4, section 3.2 stage 0, slice TFT-02).

Two local, read-only sources, no network and no injection, written into the
TFT-01 round store (`tft/rounds`):

  * `eog_file` - `TFTEoGStats.json`, rewritten once per round at planning
    start: HP, standing and board (units / star / items) for all 8 players,
    src `eog_file`, conf 1.0. Path seam, freshness and parse helpers come from
    the P0 module `tft/tft_standalone.py`.
  * `tft_log` - `TFT.log`, the live Unreal log: phase transitions, VO hints
    (purchase / star-up / combat victory, partial by nature), planner saves and
    carousel music, src `tft_log`. Read by a bounded offset tail and parsed by
    an anchored allowlist; every other line (auth, chat, telemetry, ids) is
    dropped unread.

Privacy (section 1.2): no Riot id, summoner name, PUUID, playerId or account
id leaves these modules. Players become `tft.rounds.player_key` HMAC keys in
memory; nothing else of a player's identity is copied.

LLM-free, stdlib only. The live wiring (which poll thread calls these, and the
fusion of round boundaries across sources) is TFT-07's.
"""
from tft.sources.eog_file import (  # noqa: F401
    EogFileSource,
    EogIngest,
    EogPlayer,
    EogSnapshot,
    EogUnit,
    match_id_for,
    parse_eog,
)
from tft.sources.tft_log import (  # noqa: F401
    LogEvent,
    LogIngest,
    TftLogTail,
    parse_line,
    tft_log_path,
)
