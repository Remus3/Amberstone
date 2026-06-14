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
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from coaches.adaptation_hint import SUPPORTED_MODES, kda_trends

if TYPE_CHECKING:
    from agents.agent1_lead.scheduler import Scheduler

logger = logging.getLogger("agent4.cold_streak")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COOLDOWN_FILE = _PROJECT_ROOT / "data" / "cold_advisories.json"

COLD_DELTA_FLOOR = 1.0     # |recent - baseline| >= 1.0 KDA points
COLD_SAMPLE_FLOOR = 10     # need a full last-10 window
COOLDOWN_HOURS = 24


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cooldowns() -> dict[str, str]:
    """Load the mode:champion -> last_filed_iso map. Returns {} on any
    parse error so a corrupt file doesn't block fresh advisories."""
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
    """Atomic write: tmp -> replace. Per CLAUDE.md hard rule."""
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOLDOWN_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cooldowns, indent=2), encoding="utf-8")
    os.replace(tmp, COOLDOWN_FILE)


def _in_cooldown(cooldowns: dict[str, str], key: str, now: datetime) -> bool:
    last = cooldowns.get(key)
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - last_dt) < timedelta(hours=COOLDOWN_HOURS)


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
    "below_threshold": int}`` for logging.
    """
    cooldowns = _load_cooldowns()
    now = datetime.now(timezone.utc)
    filed: list[dict] = []
    skipped: list[dict] = []
    below_threshold = 0

    for mode in modes:
        trends = kda_trends(mode, n=20, min_sample=sample_floor)
        for entry in trends.get("cold", []):
            if abs(entry["delta"]) < delta_floor:
                below_threshold += 1
                continue
            if entry["sample"] < sample_floor:
                below_threshold += 1
                continue
            key = f"{mode}:{entry['champion']}"
            # Keep in-cooldown check consistent with the module-level
            # constant but allow tests to override.
            cutoff = now - timedelta(hours=cooldown_hours)
            last = cooldowns.get(key)
            in_cd = False
            if last:
                try:
                    last_dt = datetime.fromisoformat(
                        last.replace("Z", "+00:00")
                    )
                    in_cd = last_dt > cutoff
                except ValueError:
                    in_cd = False
            if in_cd:
                skipped.append({"mode": mode, **entry})
                continue

            payload = {
                "mode": mode,
                "champion": entry["champion"],
                "baseline_kda_ratio": entry["baseline_ratio"],
                "recent_kda_ratio": entry["recent_ratio"],
                "delta": entry["delta"],
                "sample": entry["sample"],
                "detected_at": _now_iso(),
                "message": (
                    f"{entry['champion']} ({mode}) KDA dropped "
                    f"{entry['baseline_ratio']:.2f} → {entry['recent_ratio']:.2f} "
                    f"({entry['delta']:+.2f}) over last {entry['sample']} games."
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
                cooldowns[key] = _now_iso()
            except Exception as e:      # noqa: BLE001
                logger.warning("advisory file failed for %s/%s: %s",
                               mode, entry["champion"], e)

    if filed:
        _save_cooldowns(cooldowns)

    summary = {
        "filed": filed,
        "skipped_cooldown": skipped,
        "below_threshold": below_threshold,
    }
    if filed or skipped:
        logger.info("cold-streak detector: %s", summary)
    return summary
