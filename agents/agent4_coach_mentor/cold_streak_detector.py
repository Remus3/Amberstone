"""Round 31 - autonomous cold-streak advisory filer.

After each analyze pass completes, scan ``kda_trends`` for every mode.
For any champion whose last-10 KDA has tanked meaningfully relative to
the all-time baseline (``|delta_ratio| >= COLD_DELTA_FLOOR`` and sample
size >= ``COLD_SAMPLE_FLOOR``), file a ``cold-streak-advisory`` task so
the user sees it in the dashboard queue/activity feed.

**No LLM dispatch** - these are notifications, not audits. Owner agent
is ``"1"`` (deterministic lead) so the task sits in READY state until
the user acts on it. A content-addressed cooldown (24 h by default,
keyed on ``mode:champion``) prevents the same advisory firing every
two minutes after the analyze pass. The cooldown map lives at
``data/cold_advisories.json`` and is atomically rewritten.

The detector never raises on scheduler errors - it logs and keeps
going so a flaky filer can't break the analyze loop.

Hardened (s144 true-audit cycle 149, RM-1868..RM-1875): a junk cooldown
file (non-UTF-8, nested past the recursion limit, non-str or naive
stamps) never raises and never blocks; a stamp in the future (beyond a
small clock-skew allowance) never silences a champion; a bad mode or a
failed cooldown save never raises out of the pass, and the stamps of the
advisories already filed are always written; a kda_trends entry with a
non-finite or non-numeric delta / ratio / sample, a non-negative delta
or a non-str champion is counted in ``invalid_entries`` and never filed;
a champion name is one printable line capped at 64 chars; the payload is
strict JSON, and its message template is 7-bit ASCII (" -> ", not an
arrow glyph). ``modes`` may be one mode string; None means every
supported mode; a non-iterable or a non-str element is skipped.
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

from coaches.adaptation_hint import SUPPORTED_MODES, kda_trends
from core.polled_json import atomic_write_text

if TYPE_CHECKING:
    from agents.agent1_lead.scheduler import Scheduler

logger = logging.getLogger("agent4.cold_streak")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COOLDOWN_FILE = _PROJECT_ROOT / "data" / "cold_advisories.json"

COLD_DELTA_FLOOR = 1.0     # |recent - baseline| >= 1.0 KDA points
COLD_SAMPLE_FLOOR = 10     # need a full last-10 window
COOLDOWN_HOURS = 24

# A stamp this far past "now" is still honoured (clock skew between the
# write and the next pass); one further in the future is not a real
# filing time and would otherwise silence the champion until that date.
_FUTURE_SKEW = timedelta(minutes=5)
_MAX_NAME = 64
_MAX_ABS = 1e12
_CTRL_OR_SPACE = re.compile(r"[\x00-\x20\x7f-\x9f\u2028\u2029]+")

# What kda_trends can raise on a drifted mode DB or aggregates row (it is
# not hardened against a non-object aggregates_json or a junk count): the
# mode is skipped and logged, the pass goes on.
_TRENDS_ERRORS = (sqlite3.Error, OSError, ValueError, TypeError,
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
    """Load the mode:champion -> last_filed_iso map. Returns {} on any
    read or parse error so a corrupt file doesn't block fresh advisories;
    an entry whose stamp is not a parseable string is dropped."""
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
    """Atomic write: tmp -> replace. Per CLAUDE.md hard rule."""
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
    """A finite real (bool and str excluded) within +-1e12, else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) and abs(f) <= _MAX_ABS else None


def _count(v: Any) -> Optional[int]:
    """A non-negative int sample (an int-valued finite float is accepted),
    else None."""
    f = _finite(v)
    if f is None or f < 0 or not f.is_integer():
        return None
    return int(f)


def _name(v: Any) -> Optional[str]:
    """One printable line, capped at ``_MAX_NAME``, or None."""
    if not isinstance(v, str):
        return None
    s = _CTRL_OR_SPACE.sub(" ", v).strip()[:_MAX_NAME].rstrip()
    return s or None


def _clean_entry(entry: Any) -> Optional[dict]:
    """A kda_trends cold entry with every field validated, or None."""
    if not isinstance(entry, dict):
        return None
    champion = _name(entry.get("champion"))
    delta = _finite(entry.get("delta"))
    baseline = _finite(entry.get("baseline_ratio"))
    recent = _finite(entry.get("recent_ratio"))
    sample = _count(entry.get("sample"))
    if None in (champion, delta, baseline, recent, sample) or delta >= 0:
        return None
    return {"champion": champion, "baseline_ratio": baseline,
            "recent_ratio": recent, "delta": delta, "sample": sample}


def _cold_entries(mode: str, sample_floor: int) -> list:
    try:
        trends = kda_trends(mode, n=20, min_sample=sample_floor)
    except _TRENDS_ERRORS as e:
        logger.warning("kda_trends failed for %s (%s); mode skipped",
                       mode, type(e).__name__)
        return []
    cold = trends.get("cold") if isinstance(trends, dict) else None
    return cold if isinstance(cold, list) else []


def detect_and_file(
    scheduler: "Scheduler",
    modes: Iterable[str] = SUPPORTED_MODES,
    delta_floor: float = COLD_DELTA_FLOOR,
    sample_floor: int = COLD_SAMPLE_FLOOR,
    cooldown_hours: float = COOLDOWN_HOURS,
) -> dict:
    """Inspect every mode's ``kda_trends().cold`` list; file advisory
    tasks for entries that clear the threshold AND aren't on cooldown.

    Returns ``{"filed": [...], "skipped_cooldown": [...],
    "below_threshold": int, "invalid_entries": int}`` for logging.
    """
    if modes is None:
        modes = SUPPORTED_MODES
    elif isinstance(modes, str):
        modes = (modes,)
    try:
        modes = tuple(m for m in modes if isinstance(m, str))
    except TypeError:
        modes = ()
    cooldowns = _load_cooldowns()
    now = datetime.now(timezone.utc)
    filed: list[dict] = []
    skipped: list[dict] = []
    below_threshold = 0
    invalid = 0

    try:
        for mode in modes:
            for raw in _cold_entries(mode, sample_floor):
                entry = _clean_entry(raw)
                if entry is None:
                    invalid += 1
                    continue
                if (abs(entry["delta"]) < delta_floor
                        or entry["sample"] < sample_floor):
                    below_threshold += 1
                    continue
                key = f"{mode}:{entry['champion']}"
                if _in_cooldown(cooldowns, key, now, cooldown_hours):
                    skipped.append({"mode": mode, **entry})
                    continue

                stamp = now.isoformat()
                payload = {
                    "mode": mode,
                    "champion": entry["champion"],
                    "baseline_kda_ratio": entry["baseline_ratio"],
                    "recent_kda_ratio": entry["recent_ratio"],
                    "delta": entry["delta"],
                    "sample": entry["sample"],
                    "detected_at": stamp,
                    "message": (
                        f"{entry['champion']} ({mode}) KDA dropped "
                        f"{entry['baseline_ratio']:.2f} -> "
                        f"{entry['recent_ratio']:.2f} "
                        f"({entry['delta']:+.2f}) over last "
                        f"{entry['sample']} games."
                    ),
                }
                try:
                    t = scheduler.file_task(
                        op="cold-streak-advisory",
                        owner_agent="1",       # deterministic lead - no LLM dispatch
                        priority=70,
                        categories=[4],        # coaching insight
                        payload=payload,
                        user_override=True,    # system-filed, no frozen-file hits expected
                    )
                    filed.append({
                        "mode": mode, "champion": entry["champion"],
                        "task_id": getattr(t, "id", None),
                    })
                    cooldowns[key] = stamp
                except Exception as e:      # noqa: BLE001
                    logger.warning("advisory file failed for %s/%s: %s",
                                   mode, entry["champion"], e)
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
        "skipped_cooldown": skipped,
        "below_threshold": below_threshold,
        "invalid_entries": invalid,
    }
    if filed or skipped or invalid:
        logger.info("cold-streak detector: %s", summary)
    return summary
