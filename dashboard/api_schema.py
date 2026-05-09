# arch: pydantic v2 schemas for RC dashboard HTTP API shapes | section=dashboard | frozen=no
"""Pydantic v2 models for RC dashboard HTTP API request/response shapes.

GETs use extra="allow" (forward-compat — new fields never break validation).
POST body models use extra="forbid" (strict input gates).

The coaching payload inside StateResponse.coach is validated separately by
core.coaching_payload.validate_coaching_payload(), which handles per-mode
discrimination.

Route table: see docs/API.md.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class _AllowExtra(BaseModel):
    model_config = ConfigDict(extra="allow")


class _ForbidExtra(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── /api/state ─────────────────────────────────────────────────────────

class HealthBlock(_AllowExtra):
    alive: Optional[bool] = None
    pid: Optional[int] = None
    mode: Optional[str] = None
    has_game: Optional[bool] = None
    ui_pulse_age_s: Optional[float] = None
    game_poll_age_s: Optional[float] = None


class StateResponse(_AllowExtra):
    """Shape returned by GET /api/state (polled at 500 ms by the dashboard)."""
    mode_key: str = "client"
    coach_source: str = ""
    health: HealthBlock = HealthBlock()
    coach: dict[str, Any] = {}
    liveclient: Optional[dict[str, Any]] = None
    lcu: Optional[dict[str, Any]] = None


# ── /api/health ─────────────────────────────────────────────────────────

class HealthResponse(_AllowExtra):
    alive: Optional[bool] = None
    pid: Optional[int] = None
    mode: Optional[str] = None
    rc_version: str = ""


class PeerHealth(_AllowExtra):
    age_s: Optional[float] = None
    stale: bool = False
    watcher_alive: bool = False
    status: str = "no_data"


class HealthAllResponse(_AllowExtra):
    """Shape returned by GET /api/health/all."""
    status: str = "unknown"  # "green" | "yellow" | "red" | "unknown"
    rc: dict[str, Any] = {}
    vision: dict[str, Any] = {}
    daemon_slayer: dict[str, Any] = {}
    supervisor: dict[str, Any] = {}
    cost: dict[str, Any] = {}
    bridge: dict[str, Any] = {}
    peers: dict[str, Any] = {}
    rc_version: str = ""


# ── POST /api/input ──────────────────────────────────────────────────────

class InputRequest(_ForbidExtra):
    text: str


# ── POST /api/command ────────────────────────────────────────────────────

class CommandRequest(_ForbidExtra):
    """Valid commands: "force_vision" | "refresh" | "clear_pregame"."""
    command: str


# ── POST /api/ds-preview ─────────────────────────────────────────────────

class DsPreviewRequest(_AllowExtra):
    champion: str
    mode: str = "SR"
    level: int = 6
    items: list[str] = []


class DsPreviewItem(_AllowExtra):
    item_id: str
    item_name: str
    delta_dps: float
    gold: int


class DsPreviewResponse(_AllowExtra):
    ok: bool
    ranked: list[DsPreviewItem] = []
    error: str = ""


# ── POST /api/bridge/inbox ────────────────────────────────────────────────

class BridgeInboxRequest(_AllowExtra):
    """Cross-Claude bridge envelope received at /api/bridge/inbox."""
    source: str
    summary: str
    kind: str = "note"
    id: Optional[str] = None
    target: Optional[str] = None
    body: Optional[dict[str, Any]] = None
    in_reply_to: Optional[str] = None


# ── POST /api/speak ───────────────────────────────────────────────────────

class SpeakRequest(_AllowExtra):
    text: str
    voice: str = ""


# ── Common ───────────────────────────────────────────────────────────────

class OkResponse(_ForbidExtra):
    ok: bool = True


class ErrorResponse(_ForbidExtra):
    error: str
