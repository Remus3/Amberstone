# arch: pydantic v2 schema for the cross-Claude bridge wire envelope | section=core | frozen=no
"""Pydantic v2 model for the RC↔Peer bridge wire envelope.

Wire format (POST body to peer /api/bridge/inbox):
    {source, summary, kind?, id?, target?, body?, in_reply_to?,
     suggestions?, body_path?, claimed_by?, ttl_at?}

Phase 4.2 partial - envelope model only. The 12 individual bridge CLI
tools remain unchanged (frozen-file approval needed for that step).
See docs/BRIDGE.md for wire-format reference.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

log = logging.getLogger("rc.bridge_envelope")


class BridgeEnvelope(BaseModel):
    """Single message envelope for the RC↔Peer cross-Claude bridge."""
    model_config = ConfigDict(extra="allow")

    # Required
    source: str
    summary: str

    # Core optional
    kind: str = "note"
    id: Optional[str] = None
    target: Optional[str] = None
    body: Optional[dict[str, Any]] = None
    in_reply_to: Optional[str] = None

    # arch: phase 4.2 (2026-05-08) - bridge envelope schema additions (suggestions, body_path, claimed_by, ttl_at)
    suggestions: list[str] = []
    body_path: Optional[str] = None     # path to a local file carrying body content
    claimed_by: Optional[str] = None    # node that has taken ownership (tasks)
    ttl_at: Optional[float] = None      # unix epoch; receiver drops if time.time() > ttl_at

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, v: str) -> str:
        valid = {"note", "task", "result", "lesson", "escalate", "heartbeat"}
        if v not in valid:
            log.warning("bridge_envelope: unknown kind %r (continuing)", v)
        return v

    def is_expired(self) -> bool:
        """True if ttl_at is set and has passed."""
        return self.ttl_at is not None and time.time() > self.ttl_at

    def to_wire(self) -> dict:
        """Return a dict with only non-None/non-empty fields for transmission."""
        raw = self.model_dump(exclude_none=True)
        if not raw.get("suggestions"):
            raw.pop("suggestions", None)
        return raw


def parse_envelope(data: dict) -> Optional[BridgeEnvelope]:
    """Parse and validate a bridge envelope dict. Logs + returns None on failure."""
    try:
        return BridgeEnvelope.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            log.warning("bridge_envelope %s: %s", loc, err["msg"])
        return None
