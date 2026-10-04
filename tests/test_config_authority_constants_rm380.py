"""RM-380(b): guard the "Constants That Must Agree" table in
config/CONFIG_AUTHORITY.md.

That table used to say its pairs were "NOT automatically detected" and
existed "for audit and manual review purposes only" - a doc line that
declared an agreement and that no code read, so it could drift silently.
This guard reads the VALUES (source text, never an import of the frozen
modules, so nothing here executes supervisor code) and fails when a
"must match" pair stops matching.

Covered pairs (the two the table marks as a hard relationship):
  1. supervisor startup_heartbeat_timeout_s (rc_config.json value, else the
     default literal in ops/rc_supervisor.py) == ops/rc_self_monitor.py
     self._startup_grace_s.
  2. ops/rc_self_monitor.py _BOOTSTRAP_GRACE_S == 2 x that startup grace
     ("bootstrap grace is 2x startup grace by design").

Not covered, by the table's own text: max_heartbeat_age_seconds is read
straight from rc_config.json by the supervisor and handed to the monitor
(no second copy to disagree), and max_restart_attempts may legitimately
differ between the two subsystems.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUPERVISOR = ROOT / "ops" / "rc_supervisor.py"
MONITOR = ROOT / "ops" / "rc_self_monitor.py"
RC_CONFIG = ROOT / "ops" / "rc_config.json"
DOC = ROOT / "config" / "CONFIG_AUTHORITY.md"

_SUP_DEFAULT = re.compile(
    r"""get\(\s*["']startup_heartbeat_timeout_s["']\s*,\s*([0-9.]+)\s*\)""")
_MON_GRACE = re.compile(r"self\._startup_grace_s\s*:\s*float\s*=\s*([0-9.]+)")
_MON_BOOT = re.compile(r"_BOOTSTRAP_GRACE_S\s*:\s*float\s*=\s*([0-9.]+)")


def _one(pattern: re.Pattern, path: Path) -> float:
    hits = pattern.findall(path.read_text(encoding="utf-8"))
    # Anchor: an empty match must FAIL, not pass vacuously.
    assert len(hits) == 1, f"{path.name}: expected exactly 1 match for {pattern.pattern!r}, got {hits}"
    return float(hits[0])


def _supervisor_startup_timeout() -> float:
    cfg = json.loads(RC_CONFIG.read_text(encoding="utf-8"))
    default = _one(_SUP_DEFAULT, SUPERVISOR)
    return float(cfg.get("startup_heartbeat_timeout_s", default))


def test_startup_grace_matches_supervisor_timeout():
    assert _one(_MON_GRACE, MONITOR) == _supervisor_startup_timeout()


def test_bootstrap_grace_is_twice_startup_grace():
    assert _one(_MON_BOOT, MONITOR) == 2 * _one(_MON_GRACE, MONITOR)


def test_extractor_sees_a_disagreement():
    """Ablation: the same extractor applied to a mutated copy must report a
    different value, so a green run is not a regex that reads nothing."""
    text = MONITOR.read_text(encoding="utf-8")
    mutated = _MON_GRACE.sub("self._startup_grace_s: float = 31.0", text, count=1)
    assert mutated != text
    assert float(_MON_GRACE.findall(mutated)[0]) != _supervisor_startup_timeout()


def test_doc_no_longer_claims_pairs_are_unchecked():
    doc = DOC.read_text(encoding="utf-8")
    assert "NOT automatically detected" not in doc
    assert "test_config_authority_constants_rm380.py" in doc


def test_doc_names_every_feature_flags_parser():
    """RM-380(a): the doc said feature_flags.json was 'Read ONLY by'
    core/feature_policy.py; core/config_validator.py parses it too."""
    doc = DOC.read_text(encoding="utf-8")
    assert "Read ONLY by" not in doc
    parsers = []
    for py in ROOT.glob("core/*.py"):
        src = py.read_text(encoding="utf-8", errors="replace")
        if "feature_flags.json" in src and "json.load" in src:
            parsers.append(f"core/{py.name}")
    assert parsers, "anchor: no parser found - the scan itself is broken"
    for rel in parsers:
        assert rel in doc, f"{rel} parses feature_flags.json but CONFIG_AUTHORITY.md does not name it"
