# arch: queue_id -> dashboard mode_key | section=core | frozen=no
"""LCU lobby/champ-select queue_id -> dashboard mode_key resolver.

Used by `dashboard/_state_builder.py` to pre-flip the dashboard's
mode_key (and therefore which `*_coaching_data.json` it reads) once the
LCU agent reports a Lobby/ChampSelect queue, BEFORE the in-game
LiveClient mode flag (`arena_mode`/`aram_mode`/`tft_mode`/`has_game`)
goes live. Once LiveClient is up, its flags take precedence.

Returns lowercase keys matching the keys in
`dashboard._state_builder.MODE_TO_FILE` (`aram`, `arena`, `jade`, `sr`,
`tft`) or `None` for unknown queue IDs (caller falls back to `client`).
`brawl` is a MODE_TO_FILE key too, but no queue id maps to it (below).

Input contract (lane 8 s144t177): a queue id or map id is accepted as an
int, an integral finite float (a JSON round trip can turn 450 into
450.0) or a plain ASCII decimal string with optional sign and
surrounding whitespace. Everything else - inf / nan (Python's json.loads
yields inf for `1e400` and `Infinity`), a fractional float, bytes, an
`int()`-only spelling such as "4_50" or non-ASCII digits, any other
type - resolves to "unmapped", never to a truncated id and never to an
exception.

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
in s214. Its in-game backend is NOT dead - URF / ARURF / ONEFORALL /
GAMEMODEX / NEXUSBLITZ still route to MODE_BRAWL by gameMode string
(CLAUDE.md Settled: "unexercised, not unreachable"); only the pre-game
queue-id flip skips it. RM-141
(2026-08-02) mapped the kJade "Classic" throwback group to the new "jade"
mode_key; only its kCustom members stay unmapped.
"""
from __future__ import annotations

import numbers
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Optional

# A plain ASCII decimal: optional sign, digits only. `int()` alone is looser
# (it takes "4_50", non-ASCII digits and bytes), and `\d` without re.ASCII
# matches non-ASCII digits, so the class is spelled out. The digit count is
# capped because int() raises ValueError past sys.int_info's 4300-digit
# string limit; no Riot queue or map id is anywhere near 18 digits.
_DECIMAL_RE = re.compile(r"[+-]?[0-9]{1,18}")


# Riot queue_id -> dashboard mode_key (lowercase, matches MODE_TO_FILE).
# Built as a dict literal here and published read-only below: every importer
# shares this one object, so a stray write would re-route every caller.
_QUEUE_ID_TO_MODE_KEY: dict[int, str] = {
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
    # S134 (2026-10-25): the live LCU inventory (gitignored
    # ops/runtime/tft_qa/LCU_TFT_INVENTORY.md, docs/TFT_PROGRAM.md TFT-09 and
    # risk 10) measured the client OFFERING four more TFT queues, which
    # reverses the "only three" note above for these ids. Every one is
    # present in CDragon queues.json with gameSelectModeGroup
    # kTeamfightTactics (gameSelectPriority 0 there, so the CDragon census
    # alone would never have surfaced them). 1101 / 1102 stay out as before.
    1160: "tft",  # TFT Double Up (CDragon name "Teamfight Tactics (Double Up)")
    1220: "tft",  # TFT event queue (CDragon name "Tocker's Trials")
    1230: "tft",  # TFT event queue (CDragon name "Choncc or Treat")
    6110: "tft",  # TFT Set 17 revival (CDragon name "Set 17 (Normal)")
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
    4310: "jade",  # kPvP, blank display name upstream, but gameSelectPriority
                   # is 40, so it IS client-visible and the census REQUIRES it
                   # to be mapped. Not a judgment call.
    4311: "jade",  # 1v1 Jade Ranked. gameSelectPriority is 0 today, so the
                   # client does not show it and the coverage census skips it
                   # by design. Mapped anyway, and this one IS a judgment call:
                   # the map is a deliberate superset of the census (no guard
                   # asserts the converse), so if Riot raises this priority in
                   # a rotation the pre-game flip cannot silently go missing.
    4320: "jade",  # Jade (Co-op vs AI)
    4321: "jade",  # Jade (Co-op vs AI)
    # 3260 "Classic Rift", 3261 "Jade Sydney" and 3262 "Classic Rift" are the
    # kJade rows whose gameSelectCategory is kCustom, and they are
    # DELIBERATELY unmapped. Same precedent as 3280 directly above: RC treats
    # custom lobbies as no-coach, which is why mode_key_from_queue_id returns
    # None for queue_id=0. Do not "fix" these - mapping them would pre-flip a
    # custom lobby at a coach payload that is never produced.
}

QUEUE_ID_TO_MODE_KEY: Mapping[int, str] = MappingProxyType(_QUEUE_ID_TO_MODE_KEY)


def _as_id(value: object) -> Optional[int]:
    """Coerce a queue / map id per the module's input contract, else None.

    Never raises for a builtin value or a subclass of one: the int / float /
    str branches call the BASE-class methods (``int.__int__``,
    ``float.is_integer``, ``str.strip``), so a subclass override that raises
    is never reached. ``float.is_integer`` is False for inf and nan, which
    also keeps them away from the OverflowError ``int()`` raises on inf. A
    non-int ``numbers.Integral`` (a numpy integer) goes through ``int()``
    with its expected failures caught; a registered class whose own
    ``__int__`` raises something else is out of contract and propagates.
    """
    if isinstance(value, int):
        return int.__int__(value)
    if isinstance(value, float):
        return float.__int__(value) if float.is_integer(value) else None
    if isinstance(value, str):
        text = str.strip(value)
        return int(text) if _DECIMAL_RE.fullmatch(text) else None
    if isinstance(value, numbers.Integral):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def mode_key_from_queue_id(queue_id: object) -> Optional[str]:
    """Return the lowercase dashboard mode_key for a Riot LCU queue_id.

    Returns ``None`` for unknown / unmapped queues so the caller can
    fall back to ``"client"``. ``0`` and missing values also return
    ``None`` -- LCU reports ``queue_id=0`` for custom games and
    Practice Tool, neither of which has a coach payload. Malformed input
    (see the module docstring's input contract) also returns ``None``;
    this never raises.
    """
    qid = _as_id(queue_id)
    if qid is None or qid <= 0:
        return None
    return QUEUE_ID_TO_MODE_KEY.get(qid)


# S134 N2 / N3 (2026-10-25): the ONE predicate every League-only side effect
# (rune / spell / item-set writes, Match-V5 fetches, the League rating) asks
# before it fires. Measured: RC wrote a League rune page and summoner spells
# into the account during BOTH TFT queues that day, because the RuneWriter had
# no queue gate at all. TFT reaches RC through three independent signals and
# any ONE is enough, because each can be missing on its own: the queue id
# (absent when the lobby read fails), the gameMode string "TFT" (present for
# TFT queues this map does not list), and map id 22 (the TFT board).
TFT_MAP_ID = 22


def is_tft_queue(queue_id: object) -> bool:
    """True when ``queue_id`` is a mapped TFT queue."""
    return mode_key_from_queue_id(queue_id) == "tft"


def is_tft_game_mode(game_mode: object) -> bool:
    """True for a TFT gameMode string ("TFT", and the TFT_* spellings).

    Only a ``str`` (or subclass, read through the base methods) counts: the
    old ``str(game_mode or "")`` ran the value's own ``__bool__`` and
    ``__str__``, and ``str()`` of a 5000-digit int raises ValueError.
    """
    if not isinstance(game_mode, str):
        return False
    return str.upper(str.strip(game_mode)).startswith("TFT")


def is_tft_context(
    *,
    queue_id: object = None,
    game_mode: object = None,
    map_id: object = None,
) -> bool:
    """True when ANY of queue id, gameMode or map id says TFT. Never raises."""
    if is_tft_queue(queue_id) or is_tft_game_mode(game_mode):
        return True
    return _as_id(map_id) == TFT_MAP_ID
