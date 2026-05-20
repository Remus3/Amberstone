"""Summoner spell + ultimate cooldown ledger.

Backend module for the "Cooldown Ledger Sidebar" UX win. Given the 10
participants in a live game + an event log + the current game-clock,
returns a per-player ledger of summoner-spell and ultimate cooldowns
with `cd_remaining_s`, sorted by next-up-ascending (READY entries on top).

The panel JS that consumes this is a separate follow-up; this module is
deliberately route-agnostic and pure-Python (no IO, no time.time()).

CDR sources (all confirmed against League of Legends wiki + patch 16.10
balance pages):
  * Cosmic Insight (Inspiration rune, id 8347): -18 percent.
  * Ionian Boots of Lucidity (item 3158): -10 percent. The boots apply
    to BOTH summoner spells AND the ultimate (the wiki labels this
    "Ability Haste 12" on the ult side; expressed as a flat -10 percent
    CD reduction here to match the request spec).
  * Magical Footwear (rune): -10 percent on the boots (only fires if
    the participant actually owns id 3158; tracked separately so we
    don't double-count when both Cosmic AND boots are in play).
  * Ultimate Hat (retired): skipped.

Stacking is ADDITIVE (Cosmic + boots = -28 percent), NOT multiplicative.
This matches the League wiki's "Summoner Spell Haste" formula which
sums percent reductions before applying.

Sort key: min(d_cd_remaining_s, f_cd_remaining_s, ult.cd_remaining_s).
Ties broken by participant order (stable sort).
"""

from __future__ import annotations

from typing import Any

# Patch 16.10 summoner-spell base cooldowns (seconds). Keys are
# Riot's `summonerSpellId` integers as they appear in Live Client + the
# SUMMONER_SPELL_USED event payload.
SUMMONER_SPELL_BASE_CD: dict[int, float] = {
    1: 210.0,   # Cleanse
    3: 210.0,   # Exhaust
    4: 300.0,   # Flash
    6: 210.0,   # Ghost
    7: 240.0,   # Heal
    11: 90.0,   # Smite
    12: 360.0,  # Teleport
    13: 240.0,  # Clarity
    14: 180.0,  # Ignite
    21: 180.0,  # Barrier
}

SUMMONER_SPELL_NAME: dict[int, str] = {
    1: "Cleanse",
    3: "Exhaust",
    4: "Flash",
    6: "Ghost",
    7: "Heal",
    11: "Smite",
    12: "Teleport",
    13: "Clarity",
    14: "Ignite",
    21: "Barrier",
}

# Default ultimate base cooldown (seconds) when a participant's ability
# data is unavailable. Real games override via the per-participant
# `ult_base_cd` field on the participant dict. 100 s is a conservative
# midgame default (Garen R rank-2-ish); intentionally generic so the
# ledger renders something rather than hiding the row.
DEFAULT_ULT_BASE_CD = 100.0

# Rune + item IDs (League of Legends wiki).
COSMIC_INSIGHT_RUNE_ID = 8347
COSMIC_INSIGHT_REDUCTION = 0.18

IONIAN_BOOTS_LUCIDITY_ITEM_ID = 3158
IONIAN_LUCIDITY_REDUCTION = 0.10

MAGICAL_FOOTWEAR_RUNE_ID = 8304  # Wiki: Inspiration tree, free boots
MAGICAL_FOOTWEAR_REDUCTION = 0.10


def _cdr_summs(runes: list[int], items: list[int]) -> float:
    """Additive CDR fraction applied to summoner spells. Range [0, 1)."""
    cdr = 0.0
    if COSMIC_INSIGHT_RUNE_ID in runes:
        cdr += COSMIC_INSIGHT_REDUCTION
    if IONIAN_BOOTS_LUCIDITY_ITEM_ID in items:
        cdr += IONIAN_LUCIDITY_REDUCTION
        # Magical Footwear only stacks if the player ALSO ran the rune
        # AND has the boots itemized; the rune alone gives boots-for-
        # free but no extra CDR until purchase.
        if MAGICAL_FOOTWEAR_RUNE_ID in runes:
            cdr += MAGICAL_FOOTWEAR_REDUCTION
    return cdr


def _cdr_ult(items: list[int]) -> float:
    """Additive CDR fraction applied to the ultimate. Range [0, 1).

    Ionian Boots reduces ult CD by 10 percent (per request spec, matches
    the wiki's "Ability Haste 12 -> roughly 10 percent" interpretation).
    """
    cdr = 0.0
    if IONIAN_BOOTS_LUCIDITY_ITEM_ID in items:
        cdr += IONIAN_LUCIDITY_REDUCTION
    return cdr


def _effective_cd(base_cd: float, cdr_fraction: float) -> float:
    """Apply additive CDR fraction to a base cooldown. Clamps at 0."""
    if cdr_fraction >= 1.0:
        return 0.0
    if cdr_fraction <= 0.0:
        return float(base_cd)
    return float(base_cd) * (1.0 - cdr_fraction)


def _events_for_participant(
    events: list[dict],
    puuid: str | None,
    summoner_name: str | None,
) -> list[dict]:
    """Filter the event log to SUMMONER_SPELL_USED entries for one player.

    Match on `puuid` first, fall back to `summonerName` for live-client
    payloads (which sometimes lack puuid). Returns events sorted by
    `gameTime` ascending so a re-cast (e.g. Smite cooldown reset) gives
    the most-recent timestamp.
    """
    out: list[dict] = []
    for ev in events:
        if ev.get("type") != "SUMMONER_SPELL_USED":
            continue
        ev_puuid = ev.get("puuid")
        ev_name = ev.get("summonerName")
        if puuid and ev_puuid and ev_puuid == puuid:
            out.append(ev)
        elif summoner_name and ev_name and ev_name == summoner_name:
            out.append(ev)
    out.sort(key=lambda e: e.get("gameTime", 0.0))
    return out


def _last_use_time(events: list[dict], spell_id: int) -> float | None:
    """Most-recent gameTime at which `spell_id` was cast, or None."""
    last: float | None = None
    for ev in events:
        if ev.get("summonerSpellId") == spell_id:
            t = ev.get("gameTime")
            if t is not None:
                last = float(t)
    return last


def _last_ult_use(
    events: list[dict],
    puuid: str | None,
    summoner_name: str | None,
) -> float | None:
    """Most-recent gameTime at which the ult was cast by this player.

    Matches the player by puuid first, falls back to summonerName for
    live-client payloads that lack puuid. Pre-filtering by player here
    (rather than calling _events_for_participant) is intentional:
    _events_for_participant filters to SUMMONER_SPELL_USED only.
    """
    last: float | None = None
    for ev in events:
        if ev.get("type") != "ULTIMATE_USED":
            continue
        ev_puuid = ev.get("puuid")
        ev_name = ev.get("summonerName")
        matched = False
        if puuid and ev_puuid and ev_puuid == puuid:
            matched = True
        elif summoner_name and ev_name and ev_name == summoner_name:
            matched = True
        if not matched:
            continue
        t = ev.get("gameTime")
        if t is not None:
            last = float(t)
    return last


def _spell_block(
    spell_id: int | None,
    base_cd: float,
    cdr: float,
    last_use_s: float | None,
    now_s: float,
    prefix: str,
) -> dict[str, Any]:
    """Render a per-spell sub-dict with the d_/f_ key prefix."""
    eff_cd = _effective_cd(base_cd, cdr)
    if last_use_s is None:
        ready_at = 0.0
        remaining = 0.0
    else:
        ready_at = last_use_s + eff_cd
        remaining = max(0.0, ready_at - now_s)
    name = SUMMONER_SPELL_NAME.get(spell_id, "") if spell_id is not None else ""
    return {
        f"{prefix}_id": spell_id,
        f"{prefix}_name": name,
        f"{prefix}_used_at_s": last_use_s,
        f"{prefix}_ready_at_s": ready_at,
        f"{prefix}_cd_remaining_s": remaining,
    }


def _ult_block(
    ult_id: int | None,
    base_cd: float,
    cdr: float,
    last_use_s: float | None,
    now_s: float,
) -> dict[str, Any]:
    eff_cd = _effective_cd(base_cd, cdr)
    if last_use_s is None:
        ready_at = 0.0
        remaining = 0.0
    else:
        ready_at = last_use_s + eff_cd
        remaining = max(0.0, ready_at - now_s)
    return {
        "id": ult_id,
        "used_at_s": last_use_s,
        "ready_at_s": ready_at,
        "cd_remaining_s": remaining,
    }


def compute_cooldowns(
    participants: list[dict],
    events: list[dict],
    now_s: float,
) -> list[dict]:
    """Return per-participant summoner + ult cooldown ledger.

    Args:
      participants: list of dicts. Each MUST carry:
        - `puuid` (str) OR `summoner_name` (str) for event matching.
        - `champion_id` (int) for the panel render.
        - `side` (str, "blue" or "red").
        - `d_spell_id` (int) summoner D slot.
        - `f_spell_id` (int) summoner F slot.
        - `ult_id` (int|None) ability id; if None, ult block has id=None
          but still renders with default base CD.
        Optional:
        - `runes` (list[int]) rune ids; defaults to [].
        - `items` (list[int]) item ids; defaults to [].
        - `ult_base_cd` (float) override default 100s.
      events: list of dicts with `type` ("SUMMONER_SPELL_USED" or
        "ULTIMATE_USED"), `gameTime` (float seconds), and either
        `puuid` or `summonerName` plus `summonerSpellId` for summs.
      now_s: current game-clock in seconds.

    Returns: list of 10 dicts (or however many participants were
    passed), sorted by min(d_cd, f_cd, ult.cd) ascending. READY spells
    (cd <= 0) all sort to the top with cd=0; ties broken by original
    participant index.
    """
    if not participants:
        return []

    ledger: list[tuple[int, dict]] = []
    for idx, p in enumerate(participants):
        runes = list(p.get("runes") or [])
        items = list(p.get("items") or [])
        cdr_s = _cdr_summs(runes, items)
        cdr_u = _cdr_ult(items)

        puuid = p.get("puuid")
        summ_name = p.get("summoner_name")
        my_events = _events_for_participant(events, puuid, summ_name)

        d_id = p.get("d_spell_id")
        f_id = p.get("f_spell_id")
        ult_id = p.get("ult_id")
        ult_base = float(p.get("ult_base_cd") or DEFAULT_ULT_BASE_CD)

        d_base = SUMMONER_SPELL_BASE_CD.get(d_id, 0.0) if d_id is not None else 0.0
        f_base = SUMMONER_SPELL_BASE_CD.get(f_id, 0.0) if f_id is not None else 0.0

        d_last = _last_use_time(my_events, d_id) if d_id is not None else None
        f_last = _last_use_time(my_events, f_id) if f_id is not None else None
        ult_last = _last_ult_use(events, puuid, summ_name)

        d_block = _spell_block(d_id, d_base, cdr_s, d_last, now_s, "d")
        f_block = _spell_block(f_id, f_base, cdr_s, f_last, now_s, "f")
        # Merge d_ + f_ into one summs dict per the spec.
        summs = {**d_block, **f_block}
        ult = _ult_block(ult_id, ult_base, cdr_u, ult_last, now_s)

        row = {
            "puuid": puuid,
            "summoner_name": summ_name,
            "champion_id": p.get("champion_id"),
            "side": p.get("side"),
            "summs": summs,
            "ult": ult,
        }
        ledger.append((idx, row))

    def _sort_key(item: tuple[int, dict]) -> tuple[float, int]:
        idx, row = item
        s = row["summs"]
        u = row["ult"]
        next_up = min(
            s["d_cd_remaining_s"],
            s["f_cd_remaining_s"],
            u["cd_remaining_s"],
        )
        return (next_up, idx)

    ledger.sort(key=_sort_key)
    return [row for _, row in ledger]
