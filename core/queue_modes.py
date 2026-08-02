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

ID coverage is conservative - Arena (1750 live, 1700/1710 legacy) and
the ARAM family (450/720/920 plus the 2400 Mayhem set) are the cases
that actually deliver a coach payload pre-game today;
SR ranked/draft IDs are mapped because the SR draft profile already
keys off the same set in `coaches/sr_draft_profile.py`.

RM-140 (2026-08-02) reconciled this map against Riot's own catalog for
the first time. The reconcile runs BOTH ways now: `tests/
test_queue_map_grounding_rm128.py` already asserted every mapped id
still exists upstream, and its RM-140 half asserts the converse - that
no client-visible kARAM / kSummonersRift queue is missing from this
map. `tools/upstream_drift_check.py --refresh-queue-snapshot` is what
re-grounds both. Editing this dict WITHOUT re-running that command
turns the suite red on purpose.

Brawl IDs (2300-2305) stay unmapped: Brawl was retired from champ-select
in s214 and its backend is deadcode pending a cleanup pass. RM-141
(2026-08-02) mapped the kJade "Classic" throwback group to the new "jade"
mode_key; only its kCustom members stay unmapped.
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
    710:  "sr",   # Ranked 5s
    830:  "sr",   # Co-op vs AI Intro (legacy id)
    840:  "sr",   # Co-op vs AI Beginner (legacy id)
    850:  "sr",   # Co-op vs AI Intermediate (legacy id)
    870:  "sr",   # Co-op vs AI Intro - RM-140. 870/880/890 outrank
    880:  "sr",   # Co-op vs AI Beginner - 830/840/850 in the client's own
    890:  "sr",   # Co-op vs AI Intermediate - gameSelectPriority order, so
    893:  "sr",   # Bots Easy 1v1 - these are the ids a bot game uses today.
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
    # RM-140 (2026-08-02): 2400 was the only Mayhem id RC mapped, but the live
    # catalog carries a whole client-visible family under that name. If Riot
    # rotates the live Mayhem queue onto a sibling id, an unmapped id silently
    # loses the pre-game flip - the same failure the 2400 discovery fixed once.
    2401: "aram", # ARAM Mayhem (variant)
    2403: "aram", # ARAM Mayhem (variant)
    2405: "aram", # ARAM Mayhem (variant)
    2410: "aram", # ARAM Mayhem Tournament
    2450: "aram", # ARAM Mayhem Classic-ish (limited-time)
    # 3280 "ARAM: Mayhem Classic-ish" is DELIBERATELY unmapped: its
    # gameSelectCategory is kCustom, and RC treats custom lobbies as no-coach
    # (see mode_key_from_queue_id on queue_id=0). The RM-140 census in
    # tools/upstream_drift_check.py excludes kCustom for the same reason.
    # Arena
    1750: "arena",  # Arena 3x6 (CHERRY mapId 30) - live ID confirmed 2026-05-24 via /lol-game-queues/v1/queues catalog (#89 verification).
    1700: "arena",  # Legacy Arena - retained for replay/history match data pre-16.10.
    1710: "arena",  # Legacy Arena variant - retained for replay/history match data pre-16.10.
    # TFT - RM-140, operator-directed 2026-08-02. Only the three queues the
    # client actually shows (gameSelectPriority > 0 and a real display name).
    # The catalog also carries 1101 "1v0 (Ranked)" and 1102 "2v0 (Ranked)";
    # those are deliberately left out and are NOT an oversight.
    1090: "tft",  # TFT Normal
    1100: "tft",  # TFT Ranked
    1130: "tft",  # TFT Hyper Roll
    # Jade ("League Classic" throwback) - RM-141, 2026-08-02. Ids enumerated
    # from the refreshed CDragon catalog: every kJade row whose
    # gameSelectCategory is kPvP or kVersusAI. The whole group is genuinely
    # one mode, which is the discriminator COVERAGE_GROUPS documents, so the
    # census in tools/upstream_drift_check.py watches kJade from now on.
    4300: "jade",  # 5v5 Jade
    4301: "jade",  # 1v1 Jade
    4302: "jade",  # 2v2 Jade
    4303: "jade",  # 3v3 Jade
    4304: "jade",  # 4v4 Jade
    4305: "jade",  # 5v5 Jade Sydney
    4306: "jade",  # 1v1 Jade Sydney
    4307: "jade",  # 2v2 Jade Sydney
    4308: "jade",  # 3v3 Jade Sydney
    4309: "jade",  # 4v4 Jade Sydney
    4310: "jade",  # kPvP, blank display name upstream - mapped anyway so a
                   # rotation onto it cannot silently lose the pre-game flip.
    4311: "jade",  # 1v1 Jade Ranked. gameSelectPriority is 0 today, so the
                   # client does not show it and the coverage census skips it
                   # by design - mapped for the same fail-safe reason as 4310.
    4320: "jade",  # Jade (Co-op vs AI)
    4321: "jade",  # Jade (Co-op vs AI)
    # 3260 "Classic Rift", 3261 "Jade Sydney" and 3262 "Classic Rift" are the
    # kJade rows whose gameSelectCategory is kCustom, and they are
    # DELIBERATELY unmapped. Same precedent as 3280 directly above: RC treats
    # custom lobbies as no-coach, which is why mode_key_from_queue_id returns
    # None for queue_id=0. Do not "fix" these - mapping them would pre-flip a
    # custom lobby at a coach payload that is never produced.
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
