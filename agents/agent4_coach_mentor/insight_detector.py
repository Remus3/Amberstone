"""Round 38 - autonomous digest-driven advisory filer.

Cold-streak detection (round 31) only surfaces one kind of insight.
This module runs the whole ``coaching_digest`` and files an advisory
task for every insight above ``SEVERITY_FLOOR`` - covering
worst-hour slumps, weak weekdays, bad duration tiers, hot streaks,
etc. - so the dashboard queue becomes a live coaching feed.

Uses a distinct op (``coaching-insight-advisory``) from the cold
detector's (``cold-streak-advisory``) to keep the two streams
dedupable. Content-keyed cooldowns per (type, scope) live at
``data/insight_cooldowns.json`` and are atomically rewritten per
CLAUDE.md's hard rule.

Hardened (s144 true-audit cycle 151, RM-1886..RM-1892): a junk cooldown
file (non-UTF-8, nested past the recursion limit, non-str or naive
stamps) never raises and never blocks; a stamp in the future (beyond a
small clock-skew allowance) never silences an insight; a mode whose
digest raises a data / IO error is skipped, and whatever ends the pass,
the stamps of the advisories already filed are written (a failed save is
logged, never raised); a malformed insight (missing or non-str type /
message, a non-finite, bool or non-numeric severity, a non-str champion
or mode, a non-dict data) is counted in ``invalid_insights`` and never
filed; champion and message are one printable line (champion capped at
64 chars, message at 300); a non-finite float at the top level of
``data`` becomes None, so the payload is strict JSON for the flat data
dicts the digest emits. ``modes`` may be one mode string; None
means every supported mode; a non-iterable or a non-str element is
skipped. A non-finite or non-numeric ``severity_floor`` or
``cooldown_hours`` (or a negative one) uses the module default.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional

from coaches.adaptation_hint import SUPPORTED_MODES, coaching_digest
from core.polled_json import atomic_write_text

if TYPE_CHECKING:
    from agents.agent1_lead.scheduler import Scheduler

logger = logging.getLogger("agent4.insight_detector")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COOLDOWN_FILE = _PROJECT_ROOT / "data" / "insight_cooldowns.json"

SEVERITY_FLOOR = 0.7
COOLDOWN_HOURS = 24
ADVISORY_OP = "coaching-insight-advisory"

# Cold-streak advisories are already handled by cold_streak_detector -
# skip them here so we don't duplicate filings on top of an existing op.
SKIP_TYPES = frozenset({"cold_streak"})

# A stamp this far past "now" is still honoured (clock skew between the
# write and the next pass); one further in the future is not a real
# filing time and would otherwise silence the insight until that date.
_FUTURE_SKEW = timedelta(minutes=5)
_MAX_NAME = 64
_MAX_MESSAGE = 300
# timedelta(hours=x) overflows past ~2.4e10 hours; a year-scale cap is
# far beyond any real cooldown and keeps the cutoff arithmetic finite.
_MAX_COOLDOWN_HOURS = 24.0 * 366 * 100
_CTRL_OR_SPACE = re.compile(r"[\x00-\x20\x7f-\x9f\u2028\u2029]+")

# What coaching_digest can raise on a drifted mode DB (it isolates its
# own producers against the measured row errors, but lets an IO / DB /
# recursion failure through): the mode is skipped and logged, the pass
# goes on. Anything else is a real bug and raises - after the stamps of
# the advisories already filed are saved.
_DIGEST_ERRORS = (sqlite3.Error, OSError, ValueError, TypeError,
                  AttributeError, KeyError, RecursionError, ArithmeticError)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_stamp(v: Any) -> Optional[datetime]:
    """An aware datetime from an ISO stamp, or None. A naive stamp is read
    as UTC (this module only ever writes aware UTC ones)."""
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _load_cooldowns() -> dict[str, str]:
    """Load the key -> last_filed_iso map. Returns {} on any read or parse
    error so a corrupt file doesn't block fresh advisories; an entry whose
    stamp is not a parseable string, or lies in the future, is dropped."""
    try:
        data = json.loads(COOLDOWN_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError) as e:
        # ValueError covers JSONDecodeError and UnicodeDecodeError.
        logger.warning("cooldown file unreadable (%s); treating as empty",
                       type(e).__name__)
        return {}
    if not isinstance(data, dict):
        return {}
    horizon = datetime.now(timezone.utc) + _FUTURE_SKEW
    out: dict[str, str] = {}
    for k, v in data.items():
        dt = _parse_stamp(v)
        if dt is not None and dt <= horizon:
            out[str(k)] = v
    return out


def _save_cooldowns(cooldowns: dict[str, str]) -> None:
    atomic_write_text(COOLDOWN_FILE, json.dumps(cooldowns, indent=2))


def _in_cooldown(cooldowns: dict[str, str], key: str, now: datetime,
                 hours: float = COOLDOWN_HOURS) -> bool:
    """True while ``key`` was filed less than ``hours`` before ``now``. A
    missing, junk or far-future stamp is not a cooldown."""
    last = _parse_stamp(cooldowns.get(key))
    if last is None or last > now + _FUTURE_SKEW:
        return False
    return (now - last) < timedelta(hours=hours)


def _finite(v: Any) -> Optional[float]:
    """A finite float from a real (non-bool) int / float, else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


def _line(v: Any, cap: int) -> Optional[str]:
    """One printable line, capped at ``cap`` chars, or None."""
    if not isinstance(v, str):
        return None
    s = _CTRL_OR_SPACE.sub(" ", v[:4 * cap]).strip()[:cap].rstrip()
    return s or None


def _scrubbed(d: dict) -> dict:
    """Shallow copy with every non-finite float replaced by None."""
    return {
        str(k): (None if isinstance(v, float) and not math.isfinite(v)
                 else v)
        for k, v in d.items()
    }


def _clean_insight(raw: Any, queried_mode: str) -> Optional[dict]:
    """A digest insight with every field validated, or None."""
    if not isinstance(raw, dict):
        return None
    type_ = _line(raw.get("type"), _MAX_NAME)
    severity = _finite(raw.get("severity"))
    message = _line(raw.get("message"), _MAX_MESSAGE)
    mode = raw.get("mode", queried_mode)
    mode = _line(mode, _MAX_NAME) if mode is not None else queried_mode
    champion = raw.get("champion")
    if champion is not None:
        champion = _line(champion, _MAX_NAME)
        if champion is None:
            return None
    data = raw.get("data")
    if data is None:
        data = {}
    if (None in (type_, severity, message, mode)
            or not isinstance(data, dict)):
        return None
    return {"type": type_, "severity": severity, "message": message,
            "mode": mode, "champion": champion, "data": _scrubbed(data)}


def _cooldown_key(insight: dict) -> str:
    """Content-addressed key so the same insight stays on cooldown
    across detector runs, but distinct scopes (different champions,
    different hours) don't collide."""
    parts = [insight["type"], insight.get("mode") or "?"]
    # Per-type scope field.
    champ = insight.get("champion")
    if champ:
        parts.append(champ)
    data = insight.get("data") or {}
    # Time-of-day / day-of-week / duration scope.
    for field in ("hour", "weekday", "tier"):
        if field in data:
            parts.append(f"{field}={data[field]}")
    return _CTRL_OR_SPACE.sub(" ", ":".join(parts))


def _digest_insights(mode: str, top_n: int) -> list:
    try:
        digest = coaching_digest(mode=mode, top_n=top_n)
    except _DIGEST_ERRORS as e:
        logger.warning("coaching_digest failed for %s (%s); mode skipped",
                       mode, type(e).__name__)
        return []
    insights = digest.get("insights") if isinstance(digest, dict) else None
    return insights if isinstance(insights, list) else []


def _number_or(v: Any, default: float) -> float:
    f = _finite(v)
    return default if f is None or f < 0 else f


def _modes_tuple(modes: Any) -> tuple:
    if modes is None:
        return tuple(SUPPORTED_MODES)
    if isinstance(modes, str):
        return (modes,)
    try:
        return tuple(m for m in modes if isinstance(m, str) and m)
    except TypeError:
        return ()


def detect_insights_and_file(
    scheduler: "Scheduler",
    modes: Iterable[str] = SUPPORTED_MODES,
    severity_floor: float = SEVERITY_FLOOR,
    cooldown_hours: float = COOLDOWN_HOURS,
    top_n: int = 10,
) -> dict:
    """Scan ``coaching_digest`` per mode; file advisories for every
    insight at ``severity >= severity_floor`` not already on cooldown.

    Returns ``{filed, skipped_cooldown, skipped_type, skipped_severity,
    invalid_insights}``. Never raises on scheduler, data or save errors.
    """
    modes = _modes_tuple(modes)
    severity_floor = _number_or(severity_floor, SEVERITY_FLOOR)
    cooldown_hours = min(_number_or(cooldown_hours, COOLDOWN_HOURS),
                         _MAX_COOLDOWN_HOURS)
    cooldowns = _load_cooldowns()
    now = datetime.now(timezone.utc)

    filed: list[dict] = []
    skipped_cd: list[dict] = []
    skipped_type = 0
    skipped_sev = 0
    invalid = 0

    try:
        for mode in modes:
            for raw in _digest_insights(mode, top_n):
                insight = _clean_insight(raw, mode)
                if insight is None:
                    invalid += 1
                    continue
                if insight["type"] in SKIP_TYPES:
                    skipped_type += 1
                    continue
                if insight["severity"] < severity_floor:
                    skipped_sev += 1
                    continue
                key = _cooldown_key(insight)
                if _in_cooldown(cooldowns, key, now, cooldown_hours):
                    skipped_cd.append({**insight, "key": key})
                    continue
                stamp = _now_iso()
                payload = {
                    "insight_type": insight["type"],
                    "severity": insight["severity"],
                    "mode": insight["mode"],
                    "champion": insight["champion"],
                    "message": insight["message"],
                    "data": insight["data"],
                    "detected_at": stamp,
                }
                try:
                    t = scheduler.file_task(
                        op=ADVISORY_OP,
                        owner_agent="1",      # deterministic lead - no LLM dispatch
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
                    cooldowns[key] = stamp
                except Exception as e:       # noqa: BLE001
                    logger.warning("insight file failed for %s: %s", key, e)
    finally:
        # Even if the pass raises part-way, the advisories already filed
        # keep their stamps - otherwise each is re-filed every pass.
        if filed:
            try:
                _save_cooldowns(cooldowns)
            except OSError as e:
                logger.warning("cooldown save failed (%s); %d advisory "
                               "stamp(s) not persisted",
                               type(e).__name__, len(filed))

    summary = {
        "filed": filed,
        "skipped_cooldown": skipped_cd,
        "skipped_type": skipped_type,
        "skipped_severity": skipped_sev,
        "invalid_insights": invalid,
    }
    if filed or skipped_cd or invalid:
        logger.info("insight detector: filed=%d skipped_cd=%d invalid=%d",
                    len(filed), len(skipped_cd), invalid)
    return summary
