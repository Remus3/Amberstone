"""Round 38 — autonomous digest-driven advisory filer.

Cold-streak detection (round 31) only surfaces one kind of insight.
This module runs the whole ``coaching_digest`` and files an advisory
task for every insight above ``SEVERITY_FLOOR`` — covering
worst-hour slumps, weak weekdays, bad duration tiers, hot streaks,
etc. — so the dashboard queue becomes a live coaching feed.

Uses a distinct op (``coaching-insight-advisory``) from the cold
detector's (``cold-streak-advisory``) to keep the two streams
dedupable. Content-keyed cooldowns per (type, scope) live at
``data/insight_cooldowns.json`` and are atomically rewritten per
CLAUDE.md's hard rule.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from coaches.adaptation_hint import SUPPORTED_MODES, coaching_digest

logger = logging.getLogger("agent4.insight_detector")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COOLDOWN_FILE = _PROJECT_ROOT / "data" / "insight_cooldowns.json"

SEVERITY_FLOOR = 0.7
COOLDOWN_HOURS = 24
ADVISORY_OP = "coaching-insight-advisory"

# Cold-streak advisories are already handled by cold_streak_detector —
# skip them here so we don't duplicate filings on top of an existing op.
SKIP_TYPES = frozenset({"cold_streak"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cooldowns() -> dict[str, str]:
    if not COOLDOWN_FILE.exists():
        return {}
    try:
        raw = COOLDOWN_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("cooldown file unreadable (%s); treating as empty", e)
    return {}


def _save_cooldowns(cooldowns: dict[str, str]) -> None:
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOLDOWN_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cooldowns, indent=2), encoding="utf-8")
    os.replace(tmp, COOLDOWN_FILE)


def _cooldown_key(insight: dict) -> str:
    """Content-addressed key so the same insight stays on cooldown
    across detector runs, but distinct scopes (different champions,
    different hours) don't collide."""
    t = insight["type"]
    mode = insight.get("mode", "?")
    parts = [t, mode]
    # Per-type scope field.
    champ = insight.get("champion")
    if champ:
        parts.append(champ)
    data = insight.get("data", {}) or {}
    # Time-of-day / day-of-week / duration scope.
    for field in ("hour", "weekday", "tier"):
        if field in data:
            parts.append(f"{field}={data[field]}")
    return ":".join(parts)


def detect_insights_and_file(
    scheduler,
    modes: Iterable[str] = SUPPORTED_MODES,
    severity_floor: float = SEVERITY_FLOOR,
    cooldown_hours: float = COOLDOWN_HOURS,
    top_n: int = 10,
) -> dict:
    """Scan ``coaching_digest`` per mode; file advisories for every
    insight at ``severity >= severity_floor`` not already on cooldown.

    Returns ``{filed, skipped_cooldown, skipped_type, skipped_severity}``.
    Never raises on scheduler errors.
    """
    cooldowns = _load_cooldowns()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cooldown_hours)

    filed: list[dict] = []
    skipped_cd: list[dict] = []
    skipped_type = 0
    skipped_sev = 0

    def _in_cooldown(key: str) -> bool:
        last = cooldowns.get(key)
        if not last:
            return False
        try:
            return datetime.fromisoformat(last.replace("Z", "+00:00")) > cutoff
        except ValueError:
            return False

    for mode in modes:
        digest = coaching_digest(mode=mode, top_n=top_n)
        for insight in digest.get("insights", []):
            if insight["type"] in SKIP_TYPES:
                skipped_type += 1
                continue
            if insight["severity"] < severity_floor:
                skipped_sev += 1
                continue
            key = _cooldown_key(insight)
            if _in_cooldown(key):
                skipped_cd.append({"key": key, **insight})
                continue
            payload = {
                "insight_type": insight["type"],
                "severity": insight["severity"],
                "mode": insight.get("mode"),
                "champion": insight.get("champion"),
                "message": insight["message"],
                "data": insight.get("data"),
                "detected_at": _now_iso(),
            }
            try:
                t = scheduler.file_task(
                    op=ADVISORY_OP,
                    owner_agent="1",      # deterministic lead — no LLM dispatch
                    priority=65,
                    categories=[4],       # coaching insight
                    payload=payload,
                    user_override=True,
                )
                filed.append({
                    "key": key,
                    "type": insight["type"],
                    "task_id": getattr(t, "id", None),
                })
                cooldowns[key] = _now_iso()
            except Exception as e:       # noqa: BLE001
                logger.warning("insight file failed for %s: %s", key, e)

    if filed:
        _save_cooldowns(cooldowns)
    summary = {
        "filed": filed,
        "skipped_cooldown": skipped_cd,
        "skipped_type": skipped_type,
        "skipped_severity": skipped_sev,
    }
    if filed or skipped_cd:
        logger.info("insight detector: filed=%d skipped_cd=%d",
                    len(filed), len(skipped_cd))
    return summary
