# arch: queue_id -> dashboard mode_key | section=core | frozen=no
"""LCU lobby/champ-select queue_id -> dashboard mode_key resolver.

Used by `dashboard/_state_builder.py` to pre-flip the dashboard's
mode_key (and therefore which `*_coaching_data.json` it reads) once the
LCU agent reports a Lobby/ChampSelect queue, BEFORE the in-game
LiveClient mode flag (`arena_mode`/`aram_mode`/`tft_mode`/`has_game`)
goes live. Once LiveClient is up, its flags take precedence.

Returns lowercase keys matching the keys in
`dashboard._state_builder.MODE_TO_FILE` (`aram`, `arena`, `tft`,
`brawl`, `sr`) or `None` for unknown queue IDs (caller falls back to
`client`).

ID coverage is conservative - Arena (1700/1710) and ARAM (450/720/920)
are the cases that actually deliver a coach payload pre-game today;
SR ranked/draft IDs are mapped because the SR draft profile already
keys off the same set in `coaches/sr_draft_profile.py`. Add TFT/Brawl
IDs once those modes have a corresponding pre-game coach panel.
"""
from __future__ import annotations

from typing import Optional


# Riot queue_id -> dashboard mode_key (lowercase, matches MODE_TO_FILE).
QUEUE_ID_TO_MODE_KEY: dict[int, str] = {
    # Summoner's Rift
    400:  "sr",   # Normal Draft
    420:  "sr",   # Ranked Solo/Duo
    430:  "sr",   # Blind
    440:  "sr",   # Ranked Flex
    480:  "sr",   # Swiftplay
    490:  "sr",   # Quickplay (Riot retired 2024 but kept for safety)
    700:  "sr",   # Clash
    830:  "sr",   # Co-op vs AI Intro
    840:  "sr",   # Co-op vs AI Beginner
    850:  "sr",   # Co-op vs AI Intermediate
    900:  "sr",   # ARURF (single-lane URF on Rift)
    1020: "sr",   # One for All
    1400: "sr",   # Ultimate Spellbook
    1900: "sr",   # URF pick
    # ARAM
    450:  "aram", # ARAM
    720:  "aram", # ARAM Clash
    920:  "aram", # Legend of the Poro King
    2400: "aram", # ARAM Mayhem (KIWI gameMode) - queueId confirmed s220
                  # from the operator's stashed post-game LCU match payload.
    # Arena
    1700: "arena",  # Arena
    1710: "arena",  # Arena variant
}


def mode_key_from_queue_id(queue_id: Optional[int]) -> Optional[str]:
    """Return the lowercase dashboard mode_key for a Riot LCU queue_id.

    Returns ``None`` for unknown / unmapped queues so the caller can
    fall back to ``"client"``. ``0`` and missing values also return
    ``None`` -- LCU reports ``queue_id=0`` for custom games and
    Practice Tool, neither of which has a coach payload.
    """
    if queue_id is None:
        return None
    try:
        qid = int(queue_id)
    except (TypeError, ValueError):
        return None
    if qid <= 0:
        return None
    return QUEUE_ID_TO_MODE_KEY.get(qid)
