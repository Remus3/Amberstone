"""Seek-and-sample a playing replay over the local `:2999` replay API.

This is the SECOND producer of the neutral `replay_analysis.Timeline`. A
derivation validated against archived Match-V5 timelines runs unchanged on
whatever this emits - that is the entire point of sharing the shape.

WHAT THIS LANE UNIQUELY BUYS, and it is narrower than it first appears:
per-timestamp ITEM and LEVEL state for modes Match-V5 refuses outright (ARAM
Mayhem / KIWI 403s on the match route, so its timeline does not exist). For an
ordinary ranked SR match the Match-V5 timeline already carries sub-second
ITEM_PURCHASED events and 60 s coordinates, and is one headless call - it
dominates this lane on every axis. Reach for the seek sampler when there is no
timeline to be had, not as an upgrade to one.

WHAT IT CANNOT DO, measured live (items 391/392), do not plan around it:
`allPlayers[].position` is a ROLE STRING ('JUNGLE' / 'MIDDLE' / ...), never map
coordinates. Riot exposes NO champion coordinates on `:2999` in SR, ARAM or
Practice Tool. So this producer cannot improve positional resolution, and the
Timeline it emits is flagged `positions_available=False` so that a distance
derivation REFUSES it instead of quietly measuring from the map origin.
Sub-minute positions exist only inside the .rofl chunk stream (Layer-2).

LIVE-VALIDATED 2026-07-26 against NA1_5607614664 playing on Legion:
  - Seek is EXACT when playback is PAUSED first: request 600.0 -> time 600.0.
    An earlier "3 s drift" reading was my own error - playback was still
    running at speed 1.0 during the read. ALWAYS POST {"paused": true, "time":
    t} and let the client settle before sampling, or the sample is from
    wherever playback drifted to.
  - Inventory is GROUND TRUTH, checked against the match blob's final item
    slots: [2019, 3078, 3111, 3133, 3364, 6610, 6695] sampled == the same 7
    from Match-V5, level 16 == 16, cs 210 vs 212 (sampled 5 s before the end).
  - Reconstructing inventory from Match-V5 ITEM_PURCHASED events instead is
    ERROR-PRONE - it has to model component consumption on upgrade, starting
    trinkets, and ITEM_UNDO. A naive replay of those events disagreed with the
    client at every timestamp tried. So the seek lane is not merely an
    event-mode fallback: it is the only source that reports the inventory the
    game itself had.

A CAMERA ROUTE TO MAP POSITIONS EXISTS AND IS UNPROVEN - do not treat the
"no positions" line above as final without testing it. `/replay/render` exposes
`cameraPosition` in MAP coordinates (the map is the x/z plane; y is height),
plus `cameraRotation`, `fieldOfView` (40.0), and a `fogOfWar` toggle. Each
player carries `screenPositionCenter` / `screenPositionBottom`, which hold a
real screen projection for VISIBLE champions and FLT_MAX (3.4e38) when off
screen. Back-projecting a screen position through a known camera would yield
map coordinates at ARBITRARY time resolution, which is exactly what Match-V5's
60 s sampling cannot give.
BLOCKER measured today: `EnableDirectedCamera=1` in game.cfg `[Replay]`
auto-drives the camera to follow the action, so a POST to `cameraPosition`
returns 200 and is then immediately overridden. Disabling it is the first step
of any attempt.

LIVE PREREQUISITES - none of this works headless:
  1. `EnableReplayApi=1` in the client's `game.cfg`. CONFIRMED PRESENT on
     Legion 2026-07-26, line 18 under `[General]`, at the INSTALL dir:
     `C:/Riot Games/League of Legends/Config/game.cfg`.
     It is NOT under Documents - `<userprofile>/Documents/League of Legends/
     Config/` does not exist at all. Probing there with a shell fallback made a
     missing FILE print the same message as a missing FLAG, and that miss got
     recorded as a false ABSENT reading in this file's first version. A missing
     file and a missing flag are not the same measurement.
  2. A replay actually PLAYING - the routes 404 otherwise.
  3. The client on the replay's own patch; playback is hard patch-locked, so
     only a current-patch .rofl plays. Our whole corpus is 16.14, so it is
     currently replayable.
Transport is injected, so everything except those three is testable headless.
"""
from __future__ import annotations

import json
import math
import re
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from core.replay_analysis import FrameSample, Timeline

BASE = "https://127.0.0.1:2999"

# Largest response body read from the client. A full 10-player allgamedata
# blob with its event list is tens of KB; 8 MiB is far above any real frame
# and still bounds what one misbehaving local listener can make us buffer.
MAX_BODY_BYTES = 8 * 1024 * 1024

# Riot ids and scoreboard counts are int32 on the wire.
_INT32_MAX = 2**31 - 1

# The client serves a self-signed cert; this is loopback to a local process.
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


class SeekError(RuntimeError):
    """A seek or read failed. Never swallowed - a missing sample would show up
    downstream as a gap in the item timeline that looks like a real one."""


@dataclass(frozen=True)
class PlayerState:
    champion: str
    summoner: str = ""
    level: int = 0
    role: str = ""          # a ROLE STRING from :2999, never a coordinate
    team: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    cs: int = 0
    item_ids: list = field(default_factory=list)
    # 1-based index of this player's entry in the RAW allPlayers list, so a
    # skipped malformed entry never shifts the seats after it (0 = unknown,
    # for a hand-built PlayerState; to_timeline then seats by list order).
    seat: int = 0


@dataclass(frozen=True)
class SeekSample:
    t_s: float
    players: list = field(default_factory=list)


def _is_real(value: object) -> bool:
    """A finite int / float that is not a bool."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _valid_time(t_s: object) -> float:
    """A requested playback time: a finite real number >= 0, else ValueError.

    A caller error, so it raises ValueError rather than SeekError: the
    lenient sampler must not record a typo as a failed seek, and a NaN would
    otherwise be posted to the client as the non-JSON token NaN.
    """
    if not _is_real(t_s) or t_s < 0:
        raise ValueError(f"replay time must be a finite number >= 0, "
                         f"got {t_s!r}")
    return float(t_s)


def _read_capped(resp) -> bytes:
    body = resp.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise SeekError(f"replay API body exceeds {MAX_BODY_BYTES} bytes")
    return body


class ReplayClient:
    """Thin HTTP client for the local replay API."""

    def __init__(self, base: str = BASE, timeout_s: float = 5.0,
                 settle_s: float = 2.5):
        if not isinstance(base, str):
            raise ValueError(f"base must be a string, got {base!r}")
        parts = urllib.parse.urlsplit(base)
        # urlopen also opens file:// and ftp:// URLs, and the unverified TLS
        # context is only meant for the client's own HTTP(S) listener.
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"base must be an http(s) URL with a host, "
                             f"got {base!r}")
        if not _is_real(timeout_s) or timeout_s <= 0:
            raise ValueError(f"timeout_s must be a finite number > 0, "
                             f"got {timeout_s!r}")
        if not _is_real(settle_s) or settle_s < 0:
            raise ValueError(f"settle_s must be a finite number >= 0, "
                             f"got {settle_s!r}")
        self.base = base.rstrip("/")
        self.timeout_s = timeout_s
        self.settle_s = settle_s

    def post_playback(self, t_s: float) -> None:
        """Seek to *t_s*, PAUSED.

        The pause is not optional and is not politeness. Live-measured: with
        playback running at speed 1.0, a seek to 400.0 followed by a 3 s read
        reported 403.0 - the sample silently came from 3 s past where it was
        asked for. Pausing makes the seek exact (600.0 -> 600.0).
        """
        body = json.dumps({"time": _valid_time(t_s), "paused": True},
                          allow_nan=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/replay/playback", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s,
                                    context=_CTX) as r:
            _read_capped(r)
        # The client needs a moment to render the sought frame; reading too
        # early returns the PREVIOUS frame's state.
        time.sleep(self.settle_s)

    def get_allgamedata(self) -> dict:
        req = urllib.request.Request(
            f"{self.base}/liveclientdata/allgamedata",
            headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s,
                                    context=_CTX) as r:
            return json.loads(_read_capped(r).decode("utf-8"))


# RM-415: the envelope coercion seam for this module. ``x.get(k) or {}`` only
# substitutes for a MISSING / falsey value and forwards a RETYPED one, and a
# bare ``int()`` raises on a non-numeric string. Nothing above
# ``sample_series_lenient`` catches anything but SeekError, so one malformed
# inner field used to abort the whole sweep. A retyped INNER field now
# degrades; a non-object FRAME is still a typed SeekError (see sample_at).
def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


# A plain decimal number: no underscores ("1_000" parses in Python, never on
# the wire), no "nan" / "inf" words, no hex.
_NUMERIC = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _as_num(value: object) -> float | None:
    """A finite number from an int / float / numeric string, else None.
    ``bool`` is rejected rather than read as 0 / 1."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not _NUMERIC.fullmatch(text):
            return None
        f = float(text)
    else:
        return None
    return f if math.isfinite(f) else None


def _as_whole(value: object) -> int | None:
    """An integral value in 0..int32 max (12, 12.0 or "12"), else None.
    A fraction, a negative or an out-of-range number is malformed, never
    truncated or wrapped into a plausible count."""
    n = _as_num(value)
    if n is None or n < 0 or n > _INT32_MAX or n != int(n):
        return None
    return int(n)


def _as_int(value: object) -> int:
    """A scoreboard count / level; malformed reads as 0 (RM-415 degrade)."""
    n = _as_whole(value)
    return n if n is not None else 0


def _as_text(value: object) -> str:
    """A string field; anything else reads empty, never as its repr."""
    return value if isinstance(value, str) else ""


def _player_from(raw: dict, seat: int = 0) -> PlayerState:
    scores = _as_dict(raw.get("scores"))
    items = []
    for slot in _as_list(raw.get("items")):
        # `items` is null in a LIVE game (only items_display populates); in a
        # replay it does populate, but tolerate either shape.
        if isinstance(slot, dict):
            iid = _as_whole(slot.get("itemID"))
            if iid:
                items.append(iid)
    # summonerName first, then riotIdGameName - the order every other
    # allPlayers reader in core/ uses (core/decision_detector.py).
    summoner = (_as_text(raw.get("summonerName"))
                or _as_text(raw.get("riotIdGameName")))
    return PlayerState(
        champion=_as_text(raw.get("championName")),
        summoner=summoner,
        level=_as_int(raw.get("level")),
        role=_as_text(raw.get("position")),
        team=_as_text(raw.get("team")),
        kills=_as_int(scores.get("kills")),
        deaths=_as_int(scores.get("deaths")),
        assists=_as_int(scores.get("assists")),
        cs=_as_int(scores.get("creepScore")),
        item_ids=items,
        seat=seat)


def sample_at(client, t_s: float) -> SeekSample:
    """Seek to *t_s* and read the full 10-player state there.

    A bad *t_s* raises ValueError before anything is sent; a failed seek or
    read raises SeekError.
    """
    t_s = _valid_time(t_s)
    try:
        client.post_playback(t_s)
    except Exception as exc:  # transport-agnostic by design
        raise SeekError(f"seek to {t_s}s failed: {exc}") from exc
    try:
        blob = client.get_allgamedata()
    except Exception as exc:
        raise SeekError(f"read at {t_s}s failed: {exc}") from exc
    if not isinstance(blob, dict):
        # A non-object frame is a failed READ, not a degradable field: raise
        # the typed error so the lenient sampler records it as failed.
        raise SeekError(f"read at {t_s}s returned a non-object frame "
                        f"({type(blob).__name__})")
    observed = _as_num(_as_dict(blob.get("gameData")).get("gameTime"))
    if observed is not None and observed < 0:
        observed = None           # no replay instant is before 0 s
    # The seat is the RAW list position, so a skipped malformed entry does
    # not move every later player onto the wrong seat (and team).
    players = [_player_from(p, seat)
               for seat, p in enumerate(_as_list(blob.get("allPlayers")), 1)
               if isinstance(p, dict)]
    return SeekSample(t_s=observed if observed is not None else t_s,
                      players=players)


def sample_series(client, times) -> list:
    """Sample every requested timestamp. Raises on the first failure.

    Every time is validated BEFORE the first seek, so a bad time late in the
    list does not cost a sweep of 2.5 s seeks first.
    """
    times = [_valid_time(t) for t in times]
    return [sample_at(client, t) for t in times]


def sample_series_lenient(client, times):
    """Sample what we can; return (samples, failed_times).

    A long sweep across a whole game should not lose 40 good samples because
    one seek landed badly - but the failures are RETURNED, never dropped.
    A bad requested time is a caller error and raises ValueError before the
    first seek; it is not recorded as a failed seek.
    """
    times = [_valid_time(t) for t in times]
    out, failed = [], []
    for t in times:
        try:
            out.append(sample_at(client, t))
        except SeekError:
            failed.append(t)
    return out, failed


def _sample_ms(sample: object) -> int:
    if not isinstance(sample, SeekSample):
        raise TypeError(f"to_timeline takes SeekSample objects, got "
                        f"{type(sample).__name__}")
    t_s = sample.t_s
    if not _is_real(t_s) or t_s < 0:
        raise ValueError(f"sample time must be a finite number >= 0, "
                         f"got {t_s!r}")
    # round, never int(): 1.001 * 1000 is 1000.9999999999999.
    return round(t_s * 1000)


def to_timeline(samples) -> Timeline:
    """Seek samples -> the neutral Timeline the derivations consume.

    Participant ids are the player's SEAT - its 1-based position in the raw
    allPlayers list (list order for a hand-built PlayerState with seat 0) -
    matching the convention used everywhere else in the replay lane (the
    .rofl sidecar joins on participant order too - a raw uuid is not
    joinable). Because the join is by order, a seat whose champion changes
    between samples raises ValueError instead of silently mixing two
    players' rows under one id.

    frame_interval_ms is the smallest gap between distinct sample times, so
    the sweep order and a repeated time do not change it; 60000 when fewer
    than two distinct times exist.

    x and y are ZERO because :2999 has no coordinates: every frame carries
    has_position=False and the timeline is flagged so that any
    position-based derivation refuses it outright.
    """
    samples = list(samples)
    stamps = [_sample_ms(s) for s in samples]
    distinct = sorted(set(stamps))
    gaps = [b - a for a, b in zip(distinct, distinct[1:])]
    interval = min(gaps) if gaps else 60000
    tl = Timeline(frame_interval_ms=interval, positions_available=False)
    champion_at = {}
    for sample, t_ms in zip(samples, stamps):
        for idx, player in enumerate(sample.players, 1):
            pid = player.seat if player.seat > 0 else idx
            # An unreadable (empty) name is not evidence of a reorder.
            seen = (champion_at.setdefault(pid, player.champion)
                    if player.champion else "")
            if seen and seen != player.champion:
                raise ValueError(
                    f"seat {pid} is {seen!r} in an earlier sample and "
                    f"{player.champion!r} at {t_ms} ms: the roster order "
                    f"changed, so participant ids would mix two players")
            tl.frames.append(FrameSample(
                t_ms=t_ms, participant_id=pid,
                x=0, y=0, level=player.level, cs=player.cs,
                item_ids=list(player.item_ids), has_position=False))
    return tl
