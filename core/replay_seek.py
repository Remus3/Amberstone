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
import ssl
import time
import urllib.request
from dataclasses import dataclass, field

from core.replay_analysis import FrameSample, Timeline

BASE = "https://127.0.0.1:2999"

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


@dataclass(frozen=True)
class SeekSample:
    t_s: float
    players: list = field(default_factory=list)


class ReplayClient:
    """Thin HTTP client for the local replay API."""

    def __init__(self, base: str = BASE, timeout_s: float = 5.0,
                 settle_s: float = 2.5):
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
        body = json.dumps({"time": float(t_s), "paused": True}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/replay/playback", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=self.timeout_s, context=_CTX).read()
        # The client needs a moment to render the sought frame; reading too
        # early returns the PREVIOUS frame's state.
        time.sleep(self.settle_s)

    def get_allgamedata(self) -> dict:
        req = urllib.request.Request(
            f"{self.base}/liveclientdata/allgamedata",
            headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s,
                                    context=_CTX) as r:
            return json.loads(r.read().decode("utf-8"))


def _player_from(raw: dict) -> PlayerState:
    scores = raw.get("scores") or {}
    items = []
    for slot in raw.get("items") or []:
        # `items` is null in a LIVE game (only items_display populates); in a
        # replay it does populate, but tolerate either shape.
        if isinstance(slot, dict) and slot.get("itemID"):
            items.append(int(slot["itemID"]))
    return PlayerState(
        champion=str(raw.get("championName") or ""),
        summoner=str(raw.get("summonerName") or ""),
        level=int(raw.get("level") or 0),
        role=str(raw.get("position") or ""),
        team=str(raw.get("team") or ""),
        kills=int(scores.get("kills") or 0),
        deaths=int(scores.get("deaths") or 0),
        assists=int(scores.get("assists") or 0),
        cs=int(scores.get("creepScore") or 0),
        item_ids=items)


def sample_at(client, t_s: float) -> SeekSample:
    """Seek to *t_s* and read the full 10-player state there."""
    try:
        client.post_playback(float(t_s))
    except Exception as exc:  # noqa: BLE001 - transport-agnostic by design
        raise SeekError(f"seek to {t_s}s failed: {exc}") from exc
    try:
        blob = client.get_allgamedata()
    except Exception as exc:  # noqa: BLE001
        raise SeekError(f"read at {t_s}s failed: {exc}") from exc
    observed = ((blob.get("gameData") or {}).get("gameTime"))
    return SeekSample(
        t_s=float(observed if observed is not None else t_s),
        players=[_player_from(p) for p in blob.get("allPlayers") or []])


def sample_series(client, times) -> list:
    """Sample every requested timestamp. Raises on the first failure."""
    return [sample_at(client, t) for t in times]


def sample_series_lenient(client, times):
    """Sample what we can; return (samples, failed_times).

    A long sweep across a whole game should not lose 40 good samples because
    one seek landed badly - but the failures are RETURNED, never dropped.
    """
    out, failed = [], []
    for t in times:
        try:
            out.append(sample_at(client, t))
        except SeekError:
            failed.append(t)
    return out, failed


def to_timeline(samples) -> Timeline:
    """Seek samples -> the neutral Timeline the derivations consume.

    Participant ids are assigned by ORDER within a sample, matching the
    convention used everywhere else in the replay lane (the .rofl sidecar joins
    on participant order too - a raw uuid is not joinable).

    x and y are ZERO because :2999 has no coordinates, and the timeline is
    flagged so that any position-based derivation refuses it outright.
    """
    samples = list(samples)
    interval = 60000
    if len(samples) >= 2:
        interval = int(round(abs(samples[1].t_s - samples[0].t_s) * 1000)) or 60000
    tl = Timeline(frame_interval_ms=interval, positions_available=False)
    for sample in samples:
        for idx, player in enumerate(sample.players, 1):
            tl.frames.append(FrameSample(
                t_ms=int(sample.t_s * 1000), participant_id=idx,
                x=0, y=0, level=player.level, cs=player.cs,
                item_ids=list(player.item_ids)))
    return tl
