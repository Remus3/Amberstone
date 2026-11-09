# arch: ONE cited Summoner's Rift objective schedule | section=core | frozen=no
"""The single authoritative Summoner's Rift objective schedule (s156 S5, C7).

Pure data, stdlib only, no I/O. Every SR timer in the repo reads THIS module:
  - core/event_callouts.py  (served callouts, `_SR_OBJECTIVES`, SR_* constants)
  - game_reader/snapshot_normalizer.py  (obj_timers / obj_timers_dict)
  - core/decision_detector.py, core/macro_context.py  (via event_callouts)
  - web/js/panels/objective_gauges.js  (a literal mirror, pinned by
    tests/test_sr_schedule_s156.py)

Before this module two copies disagreed (event_callouts: Herald 14:00;
snapshot_normalizer: Herald 8:00, Baron and Atakhan both 20:00) and neither
cited a patch. Every row below carries a status and a source.

STATUS VOCABULARY
  official    a Riot patch note or dev post states the value.
  recorded    no patch note value found; consistent with RC's OWN recorded
              Match-V5 timelines (data/rewind_history.db, patch family 16.x
              = season 2026, queues 420/440, 49 matches measured 2026-11-08).
              A minimum observed kill/gap is a LOWER BOUND on the spawn, not
              the spawn itself, so a `recorded` value is consistent, not proven.
  unverified  neither a patch note nor a recorded bound settles it. Kept as a
              best-effort legacy value and said so; never presented as fact.
  removed     the objective no longer exists (value_s is None).

SOURCES (official). Wiki pages are gated by ruling 51 / RM-1227 and were NOT
used.
  P2509  Patch 25.09 notes, published 2025-04-29
         https://www.leagueoflegends.com/en-us/news/game-updates/patch-25-09-notes/
         "Void Grubs: Spawn timer: 6:00 => 8:00 minutes", "No longer respawns",
         "Rift Herald: Now spawns at 15:00 minutes."
  P261   Patch 26.1 notes, published 2026-01-07
         https://www.leagueoflegends.com/en-us/news/game-updates/patch-26-1-notes/
         "Atakhan has been removed from the game and will no longer spawn.",
         "Baron Nashor: Spawn timer: 25m => 20m", "Epic Monster spawn times are
         unchanged unless noted above.", "Plates are now permanent instead of
         falling off at 14 minutes."
  D261   /dev: 2026 Season One Gameplay Preview, published 2025-12-01
         https://www.leagueoflegends.com/en-us/news/dev/dev-2026-season-one-gameplay-preview/
         "With Atakhan Ata-gone, Baron will now return to spawning at 20 minutes."
Baron history: Baron spawned at 25:00 from 25.S1.1 through 25.24 (the
Atakhan era, the "25m" side of P261's "25m => 20m"); 26.1 restored 20:00.
Patch 26.1's Swiftplay values are EXCLUDED here: this schedule is the
Summoner's Rift ranked / normal draft timer set only.
Patches 26.2 through 26.22 were searched for a later change to these values and
none was found (26.11 buffed Grub damage only; 26.12 fixed Herald turret damage
type). That is an absence in search results, not a proof - re-check on a patch
that names an epic monster timer.

Game-time axis: seconds on the Live Client `gameTime` clock (the same clock the
Match-V5 timeline timestamps use).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

STATUS_OFFICIAL = "official"
STATUS_RECORDED = "recorded"
STATUS_UNVERIFIED = "unverified"
STATUS_REMOVED = "removed"
STATUSES = frozenset({STATUS_OFFICIAL, STATUS_RECORDED,
                      STATUS_UNVERIFIED, STATUS_REMOVED})

# Patch family this schedule was established against (patch-note numbering).
SCHEDULE_PATCH = "26.22"
SCHEDULE_ESTABLISHED = "2026-11-08"


@dataclass(frozen=True)
class Timing:
    key: str
    value_s: Optional[float]
    status: str
    source: str


def _t(key: str, value_s: Optional[float], status: str, source: str) -> Timing:
    return Timing(key, value_s, status, source)


_ROWS: tuple[Timing, ...] = (
    _t("dragon_first", 300.0, STATUS_RECORDED,
       "P261 'Epic Monster spawn times are unchanged unless noted' (no value "
       "stated); recorded 16.x first-drake kill min 328.6s n=49"),
    _t("dragon_respawn", 300.0, STATUS_RECORDED,
       "recorded 16.x drake-to-drake gap min 307.9s n=167; no patch note value "
       "found"),
    _t("voidgrubs_first", 480.0, STATUS_OFFICIAL,
       "P2509 'Spawn timer: 6:00 => 8:00'; recorded 16.x first grub kill min "
       "488.9s n=49"),
    _t("voidgrubs_respawn", None, STATUS_OFFICIAL,
       "P2509 'No longer respawns' (one encounter per game); recorded 16.x: "
       "3 grub kills per match, no second wave"),
    _t("voidgrubs_window_end", 900.0, STATUS_UNVERIFIED,
       "no patch note despawn time found; bounded by the Herald spawn (shared "
       "pit); recorded 16.x latest grub kill 754.9s"),
    _t("herald_first", 900.0, STATUS_OFFICIAL,
       "P2509 'Now spawns at 15:00 minutes'; P261 leaves it unchanged; "
       "recorded 16.x first herald kill min 922.2s n=48. The old 14:00 in "
       "event_callouts and 8:00 in snapshot_normalizer were both wrong"),
    _t("herald_despawn", 1200.0, STATUS_UNVERIFIED,
       "no patch note despawn time found; the legacy 19:45 is REFUTED by a "
       "recorded 16.x herald kill at 1186.1s, so 1200 (Baron spawn) is used "
       "as the weakest consistent bound"),
    _t("baron_first", 1200.0, STATUS_OFFICIAL,
       "P261 'Spawn timer: 25m => 20m' (2026-01-07), D261 (2025-12-01); "
       "recorded 16.x first baron kill min 1234.9s n=43"),
    _t("baron_respawn", 360.0, STATUS_RECORDED,
       "recorded 16.x baron-to-baron gap min 377.3s n=20; no patch note value "
       "found"),
    _t("elder_after_soul", 360.0, STATUS_UNVERIFIED,
       "no patch note value found; recorded 16.x 4th-drake to Elder gap min "
       "376.2s n=6 is consistent with 360 but is only a lower bound"),
    _t("elder_respawn", 360.0, STATUS_UNVERIFIED,
       "no patch note value found; assumed equal to elder_after_soul"),
    _t("baron_buff", 180.0, STATUS_UNVERIFIED,
       "legacy Hand of Baron duration; P261 states no duration"),
    _t("elder_buff", 150.0, STATUS_UNVERIFIED,
       "legacy Aspect of the Dragon duration; P261 states no duration"),
    _t("inhib_respawn", 300.0, STATUS_UNVERIFIED,
       "legacy inhibitor respawn; no patch note value found in P261"),
    _t("plates_fall", None, STATUS_OFFICIAL,
       "P261 'Plates are now permanent instead of falling off at 14 minutes' "
       "- there is NO fall time any more (the 14:00 callout was removed)"),
    _t("atakhan_first", None, STATUS_REMOVED,
       "P261 'Atakhan has been removed from the game and will no longer "
       "spawn' - nothing to schedule or un-skip"),
)

SCHEDULE: dict[str, Timing] = {r.key: r for r in _ROWS}


def value(key: str) -> Optional[float]:
    """Seconds for `key`, or None for a removed / never-respawning row."""
    return SCHEDULE[key].value_s


def _req(key: str) -> float:
    v = SCHEDULE[key].value_s
    assert v is not None, key
    return v


# Named seconds constants (the only place these literals live).
DRAGON_FIRST_S = _req("dragon_first")
DRAGON_RESPAWN_S = _req("dragon_respawn")
VOIDGRUBS_FIRST_S = _req("voidgrubs_first")
VOIDGRUBS_WINDOW_END_S = _req("voidgrubs_window_end")
HERALD_FIRST_S = _req("herald_first")
HERALD_DESPAWN_S = _req("herald_despawn")
BARON_FIRST_S = _req("baron_first")
BARON_RESPAWN_S = _req("baron_respawn")
ELDER_AFTER_SOUL_S = _req("elder_after_soul")
ELDER_RESPAWN_S = _req("elder_respawn")
BARON_BUFF_S = _req("baron_buff")
ELDER_BUFF_S = _req("elder_buff")
INHIB_RESPAWN_S = _req("inhib_respawn")
# Removed / one-shot-only rows.
PLATES_FALL_S: Optional[float] = None
ATAKHAN_FIRST_S: Optional[float] = None
VOIDGRUBS_RESPAWN_S: Optional[float] = None
# Soul is the 4th elemental drake of one side; Elder pit follows.
SOUL_SECURED_STACKS = 4


def as_dict() -> dict:
    """JSON-friendly dump (key -> value_s/status/source) for tests and docs."""
    return {k: {"value_s": r.value_s, "status": r.status, "source": r.source}
            for k, r in SCHEDULE.items()}
