"""
ops/rc_state_validator.py

Low-rate validator that compares coaching_data.json and tft_live_data.json
fields against live health.json to catch stuck/stale output.

Validates cheap, high-value fields only:
  - Overlay mode matches health.json reported mode
  - Coaching data is not older than staleness_threshold_s
  - TFT: stage_round from coaching matches live_data
  - TFT: health value is plausible (1-100)
  - SR: last coaching timestamp is recent enough during active game

Does NOT: take screenshots, run OCR, call Claude, or run PowerShell.
Records all mismatches to IncidentLog.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Optional import â€” OCR only if installed and enabled
try:
    from tft.tft_ocr_reader import TftOcrReader as _TftOcrReader  # type: ignore
    _HAS_OCR = True
except Exception:
    _HAS_OCR = False


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

    # â”€â”€ Public â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

        # â”€â”€ Check 1: mode field plausibility â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if mode not in ("client", "game", "unknown"):
            self._mismatch("mode_invalid", f"health mode={mode!r}", report)

        # â”€â”€ Check 2: coaching data freshness (SR only, during active game) â”€â”€â”€
        if has_game and not is_tft and self._coaching_file.exists():
            age = time.time() - self._coaching_file.stat().st_mtime
            if age > self.staleness_threshold:
                self._mismatch(
                    "coaching_stale",
                    f"coaching_data.json is {age:.0f}s old (threshold={self.staleness_threshold:.0f}s)",
                    report,
                )
            report["checks"].append(f"sr_coaching_age={age:.0f}s")

        # â”€â”€ Check 3: TFT live data plausibility â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if is_tft and has_game:
            live = self._read_json(self._tft_live_file)
            if live:
                hp = live.get("hp")
                if hp is not None and not (1 <= float(hp) <= 100):
                    self._mismatch(
                        "tft_hp_out_of_range",
                        f"tft_live_data.hp={hp} (expected 1-100)",
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

        # â”€â”€ Check 4: TFT coaching vs live stage_round agreement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if is_tft and has_game:
            live  = self._read_json(self._tft_live_file)
            coach = self._read_json(self._tft_coach_file)
            if live and coach:
                live_sr  = live.get("stage_round", "")
                coach_sr = coach.get("stage_round", "")
                if live_sr and coach_sr and live_sr != coach_sr:
                    # Warn only â€” they may be legitimately 1 round apart
                    self._mismatch(
                        "tft_round_mismatch",
                        f"live={live_sr} vs coach={coach_sr}",
                        report,
                        severity="WARN",
                    )

        # â”€â”€ Check 5: TFT coaching file freshness â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if is_tft and has_game and self._tft_coach_file.exists():
            age = time.time() - self._tft_coach_file.stat().st_mtime
            if age > self.staleness_threshold:
                self._mismatch(
                    "tft_coaching_stale",
                    f"tft_coaching_data.json is {age:.0f}s old",
                    report,
                )
            report["checks"].append(f"tft_coaching_age={age:.0f}s")

        # â”€â”€ Check 6: OCR cross-check (only if enabled + Tesseract present) â”€â”€â”€
        if self.ocr_enabled and is_tft and has_game:
            self._ocr_check(report)

        report["mismatch_count"] = len(report["mismatches"])
        report["ok"] = report["mismatch_count"] == 0
        self._mismatch_count += report["mismatch_count"]
        return report

    # â”€â”€ Internal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    def _ocr_check(self, report: Dict[str, Any]) -> None:
        """Quick OCR cross-check for stage/round only â€” â‰¤2ms."""
        try:
            reader = _TftOcrReader()
            if not reader.available:
                return
            sr_ocr = reader.read_stage_round_only()
            if not sr_ocr:
                return
            live = self._read_json(self._tft_live_file)
            if not live:
                return
            live_sr = live.get("stage_round", "")
            if live_sr and sr_ocr != live_sr:
                # Difference of 1 round is normal (OCR ahead); >1 is suspect
                try:
                    ocr_s, ocr_r   = map(int, sr_ocr.split("-"))
                    live_s, live_r = map(int, live_sr.split("-"))
                    diff = abs((ocr_s * 10 + ocr_r) - (live_s * 10 + live_r))
                    if diff > 2:
                        self._mismatch(
                            "ocr_round_mismatch",
                            f"OCR={sr_ocr} live={live_sr} diff={diff}",
                            report,
                        )
                except Exception:
                    pass
            report["checks"].append(f"ocr_sr={sr_ocr}")
        except Exception:
            pass

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict[str, Any]]:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
        return None


def _ts() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _valid_stage_round(sr: str) -> bool:
    try:
        parts = str(sr).split("-")
        if len(parts) != 2:
            return False
        s, r = int(parts[0]), int(parts[1])
        return 1 <= s <= 9 and 1 <= r <= 9
    except Exception:
        return False

