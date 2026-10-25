"""
ops/rc_state_validator.py

Low-rate validator that compares coaching_data.json and tft_live_data.json
fields against live health.json to catch stuck/stale output.

Validates cheap, high-value fields only:
  - health.json mode is one of client / game / unknown
  - SR: coaching_data.json is not older than staleness_threshold_s during
    an active game
  - TFT: tft_live_data.json and tft_coaching_data.json are not older than
    staleness_threshold_s during an active game
  - TFT: hp is plausible (0-100; 0 is the reset seed, the producer's clamp
    target and an eliminated player) and stage_round parses
  - TFT: the coach artifact's stage / round agrees with live_data within
    one round
  - TFT, only when constructed with ocr_enabled=True and Tesseract is
    present: an OCR read of the HUD round counter agrees with live_data
    within two rounds (rc_supervisor.py never enables it)

Does NOT: take screenshots, call Claude, or run PowerShell.
Records all mismatches to IncidentLog.

Every reader here is fail-soft by design: rc_self_monitor.py swallows any
exception from maybe_run() AFTER _last_run has advanced, so a raise inside
run_once() silently skips every remaining check for the whole cadence
window. Unreadable or wrongly-shaped input is therefore treated as absent,
never raised.
"""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Optional import  -  OCR only if installed and enabled
try:
    from tft.tft_ocr_reader import TftOcrReader as _TftOcrReader  # type: ignore
    _HAS_OCR = True
except Exception:  # noqa: BLE001
    _HAS_OCR = False

# Standard TFT round layout: stage 1 has four rounds (1-1 .. 1-4), every
# later stage seven (2-1 .. 2-7). Used only to measure how far apart two
# stage_round strings are; s*10+r made 2-7 -> 3-1 look four rounds apart.
_STAGE1_ROUNDS = 4
_ROUNDS_PER_STAGE = 7

# The coach artifact and the live file are written by different producers on
# their own cadences, so they "may be legitimately 1 round apart" (Check 4's
# original comment). The OCR read samples the HUD directly and can run ahead
# of the live file; the shipped tolerance of two rounds is kept.
_COACH_ROUND_TOLERANCE = 1
_OCR_ROUND_TOLERANCE = 2


class StateValidator:
    """
    Validates overlay outputs against known-good state sources.
    Runs at a fixed low rate (default 30s).  Thread-safe reads, no tkinter.
    """

    def __init__(
        self,
        project_root: Path,
        incident_log,  # IncidentLog instance
        interval_s: float = 30.0,
        staleness_threshold_s: float = 120.0,
        ocr_enabled: bool = False,
    ) -> None:
        self.project_root        = Path(project_root)
        self.incident_log        = incident_log
        self.interval_s          = max(10.0, float(interval_s))
        self.staleness_threshold = float(staleness_threshold_s)
        self.ocr_enabled         = ocr_enabled and _HAS_OCR

        self._coaching_file   = self.project_root / "coaching_data.json"
        self._tft_live_file   = self.project_root / "data" / "tft_live_data.json"
        self._tft_coach_file  = self.project_root / "data" / "tft_coaching_data.json"
        self._health_file     = self.project_root / "ops" / "runtime" / "health.json"

        self._last_run   = 0.0
        self._mismatch_count = 0
        # One OCR reader per validator: building one per check re-resolved
        # Tesseract and logged "TftOcrReader ready" at INFO every tick.
        self._ocr_reader: Any = None

    #  -  -  Public  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -

    def maybe_run(self) -> Optional[Dict[str, Any]]:
        """Call on every monitor tick. Only runs at self.interval_s cadence."""
        now = time.monotonic()
        if now - self._last_run < self.interval_s:
            return None
        self._last_run = now
        return self.run_once()

    def run_once(self) -> Dict[str, Any]:
        """Run all cheap validators. Returns report dict."""
        report: Dict[str, Any] = {
            "ts":         _ts(),
            "checks":     [],
            "mismatches": [],
            "ok":         True,
        }

        health = self._read_json(self._health_file)
        if not health:
            report["checks"].append("health_file_missing")
            return report

        mode = health.get("mode", "unknown")
        is_tft = health.get("tft_mode", False)
        has_game = health.get("has_game", False)

        #  -  -  Check 1: mode field plausibility  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -
        if mode not in ("client", "game", "unknown"):
            self._mismatch("mode_invalid", f"health mode={mode!r}", report)

        #  -  -  Check 2: coaching data freshness (SR only, during active game)  -  -  -
        if has_game and not is_tft:
            age = _file_age_s(self._coaching_file)
            if age is not None:
                if age > self.staleness_threshold:
                    self._mismatch(
                        "coaching_stale",
                        f"coaching_data.json is {age:.0f}s old (threshold={self.staleness_threshold:.0f}s)",
                        report,
                    )
                report["checks"].append(f"sr_coaching_age={age:.0f}s")

        if not (is_tft and has_game):
            return self._finish(report)

        # One snapshot of each TFT file per run, so checks 3, 4 and 6 judge
        # the same bytes (they used to re-read the live file three times).
        live = self._read_json(self._tft_live_file)
        coach = self._read_json(self._tft_coach_file)

        #  -  -  Check 3: TFT live data freshness + plausibility  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -
        age = _file_age_s(self._tft_live_file)
        if age is not None:
            # The facade seeds this file at every reset and the analysis
            # loop rewrites it only when its payload changes, so an old file
            # is a WARN to look at, not proof of a stall (Check 5 has the
            # same exposure). Measured 2026-10-25: the reset seed sat 13 min
            # into a live TFT game and nothing flagged it.
            if age > self.staleness_threshold:
                self._mismatch(
                    "tft_live_stale",
                    f"tft_live_data.json is {age:.0f}s old (threshold={self.staleness_threshold:.0f}s)",
                    report,
                )
            report["checks"].append(f"tft_live_age={age:.0f}s")
        if live:
            hp = live.get("hp")
            hp_num = _as_finite_float(hp)
            # Only range-check a finite numeric hp. A non-numeric token
            # (stale OCR garbage, the "-" no-data sentinel, NaN/inf) must
            # not raise out of run_once and silently skip the remaining
            # checks - the SelfMonitor caller swallows the exception AND
            # _last_run was already advanced, so every tick would no-op.
            # 0 is in range: it is the reset seed (coaches/tft_coach.py),
            # the producer's clamp target (tft/tft_live_analysis.py
            # _coerce_hp) and an eliminated player.
            if hp_num is not None and not (0 <= hp_num <= 100):
                self._mismatch(
                    "tft_hp_out_of_range",
                    f"tft_live_data.hp={hp} (expected 0-100)",
                    report,
                )
            sr = live.get("stage_round", "")
            if sr and not _valid_stage_round(sr):
                self._mismatch(
                    "tft_stage_round_invalid",
                    f"tft_live_data.stage_round={sr!r}",
                    report,
                )
            report["checks"].append(f"tft_hp={hp} sr={sr}")

        #  -  -  Check 4: TFT coaching vs live stage_round agreement  -  -  -  -  -  -  -  -  -  -  -  -  -  -
        if live and coach:
            live_sr  = live.get("stage_round", "")
            coach_sr = _coach_stage_round(coach)
            dist = _round_distance(live_sr, coach_sr)
            if dist is not None and dist > _COACH_ROUND_TOLERANCE:
                self._mismatch(
                    "tft_round_mismatch",
                    f"live={live_sr} vs coach={coach_sr}",
                    report,
                    severity="WARN",
                )

        #  -  -  Check 5: TFT coaching file freshness  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -
        age = _file_age_s(self._tft_coach_file)
        if age is not None:
            if age > self.staleness_threshold:
                self._mismatch(
                    "tft_coaching_stale",
                    f"tft_coaching_data.json is {age:.0f}s old",
                    report,
                )
            report["checks"].append(f"tft_coaching_age={age:.0f}s")

        #  -  -  Check 6: OCR cross-check (only if enabled + Tesseract present)  -  -  -
        if self.ocr_enabled:
            self._ocr_check(report, live)

        return self._finish(report)

    #  -  -  Internal  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -

    def _finish(self, report: Dict[str, Any]) -> Dict[str, Any]:
        report["mismatch_count"] = len(report["mismatches"])
        report["ok"] = report["mismatch_count"] == 0
        self._mismatch_count += report["mismatch_count"]
        return report

    def _mismatch(
        self,
        trigger: str,
        detail: str,
        report: Dict[str, Any],
        severity: str = "WARN",
    ) -> None:
        report["mismatches"].append({"trigger": trigger, "detail": detail})
        report["ok"] = False
        self.incident_log.record(
            severity  = severity,
            subsystem = "validator",
            trigger   = trigger,
            action    = "none",
            result    = "ok",
            detail    = detail,
        )

    def _get_ocr_reader(self) -> Any:
        """Build the OCR reader once. A reader that cannot be built, or
        reports Tesseract unavailable, turns the OCR check off for the life
        of this validator instead of being retried (and re-logged) every
        tick."""
        if self._ocr_reader is None:
            try:
                reader = _TftOcrReader()
            except Exception as exc:  # noqa: BLE001 - optional subsystem
                logger.warning("validator OCR disabled: reader init failed (%s)",
                               type(exc).__name__)
                self.ocr_enabled = False
                return None
            if not reader.available:
                self.ocr_enabled = False
                return None
            self._ocr_reader = reader
        return self._ocr_reader

    def _ocr_check(self, report: Dict[str, Any], live: Optional[Dict[str, Any]]) -> None:
        """Quick OCR cross-check for stage/round only."""
        reader = self._get_ocr_reader()
        if reader is None:
            return
        try:
            sr_ocr = reader.read_stage_round_only()
        except Exception as exc:  # noqa: BLE001 - optional subsystem
            logger.debug("validator OCR read failed: %s", type(exc).__name__)
            return
        if not sr_ocr or not live:
            return
        live_sr = live.get("stage_round", "")
        dist = _round_distance(sr_ocr, live_sr)
        if dist is not None and dist > _OCR_ROUND_TOLERANCE:
            self._mismatch(
                "ocr_round_mismatch",
                f"OCR={sr_ocr} live={live_sr} diff={dist}",
                report,
            )
        report["checks"].append(f"ocr_sr={sr_ocr}")

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict[str, Any]]:
        """A JSON object from `path`, or None when it is missing, unreadable,
        not JSON, or JSON that is not an object (every caller does .get)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, RecursionError):
            return None
        return data if isinstance(data, dict) else None


def _ts() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _file_age_s(path: Path) -> Optional[float]:
    """Seconds since `path` was modified, or None if it cannot be stat'ed
    (absent, or removed between a reset and this read)."""
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def _valid_stage_round(sr: str) -> bool:
    try:
        parts = str(sr).split("-")
        if len(parts) != 2:
            return False
        s, r = int(parts[0]), int(parts[1])
        return 1 <= s <= 9 and 1 <= r <= 9
    except ValueError:
        return False


def _round_ordinal(sr: Any) -> Optional[int]:
    """Position of a "S-R" string in the game's round sequence, or None if it
    is not a valid stage_round string."""
    if not isinstance(sr, str) or not _valid_stage_round(sr):
        return None
    s, r = (int(p) for p in sr.split("-"))
    if s == 1:
        return r
    return _STAGE1_ROUNDS + (s - 2) * _ROUNDS_PER_STAGE + r


def _round_distance(a: Any, b: Any) -> Optional[int]:
    """How many rounds apart two stage_round strings are, or None when either
    one does not parse (no data is not a disagreement)."""
    oa, ob = _round_ordinal(a), _round_ordinal(b)
    if oa is None or ob is None:
        return None
    return abs(oa - ob)


def _coach_stage_round(coach: Dict[str, Any]) -> str:
    """The coach artifact's round as "S-R". The engine writes a
    "stage_round" string beside INT stage / round (tft/tft_coach_engine.py
    output dict); the string wins. A writer shaped like
    core/coaching_payload.py TftPayload carries only the ints, so they are
    the fallback. 0 means unknown."""
    sr = coach.get("stage_round")
    if isinstance(sr, str) and sr:
        return sr
    s, r = coach.get("stage"), coach.get("round")
    if (isinstance(s, int) and isinstance(r, int)
            and not isinstance(s, bool) and not isinstance(r, bool)
            and s > 0 and r > 0):
        return f"{s}-{r}"
    return ""


def _as_finite_float(value: Any) -> Optional[float]:
    """Coerce a probe value to a finite float, or None if it is missing,
    non-numeric, or non-finite (NaN/inf). Never raises - callers use the
    None result to skip a numeric plausibility check rather than crash."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None
