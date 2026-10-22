"""C6 F3 / F4 (plan C1b-3 slice S2): the Game-PC SMB push module is deleted
and the locked topology decision is the 1-PC (ADR-011) record.

F4: the retired Game-PC SMB push module under ``agents/agent2_backend/`` was
dead code since 2026-06-28 (phase3-d026 Path A defer-delete: share probe
hard-False, push and forwarder-restart raise). Its only consumers were its own
retirement test and three label-helper tests in the agent3 suite. It is now
removed (git rm; recoverable from history), and no LIVE file may name it again.
History / record files keep their mentions (they describe what happened).

F3: ``phase3-d011`` described a 3-machine topology (Legion + Game-PC + Peer).
ADR-011 (phase3-d021) made Legion the only runtime host and ADR-012
(phase3-d024) decommissioned the Peer bridge, so d011 now names Legion as the
only runtime host, in placeholders only, with no live Game-PC / Peer role.

The module name is assembled at runtime so this guard does not itself become a
``git grep`` hit for the token it forbids.
"""
from __future__ import annotations

import importlib.util
import ipaddress
import json
import re

from tests import _repo_walk

REPO_ROOT = _repo_walk.REPO_ROOT
_MOD = "smb" + "_push"
_DECISIONS = REPO_ROOT / "agents" / "state" / "resolved_decisions.json"

# History / record files: they describe the module's past and keep the name.
_RECORD_FILES = frozenset({
    "BACKLOG.md",
    "RC-NEXT-SESSION.txt",  # hand-off record, rewritten whole at /done
    "docs/LEDGER.md",
    "docs/history_notes.md",
    "docs/OVERLAY_BUILD_MASTER_PLAN.md",
})
_RECORD_PREFIXES = (
    "agents/agent6_auditor/proposals/",
    "agents/agent6_auditor/reports/",
    "docs/audits/",
    "ops/loop/reports/",
)
_TEXT_PATTERNS = (
    "*.py", "*.md", "*.json", "*.txt", "*.ps1", "*.psm1", "*.bat", "*.cmd",
    "*.toml", "*.ini", "*.cfg", "*.yml", "*.yaml", "*.xml", "*.vbs", "*.ahk",
    "*.spec", "*.js", "*.html",
)


def _is_record(rel: str) -> bool:
    return rel in _RECORD_FILES or rel.startswith(_RECORD_PREFIXES)


def _decision(decision_id: str) -> dict:
    data = json.loads(_DECISIONS.read_text(encoding="utf-8"))
    for entry in data["decisions"]:
        if entry["id"] == decision_id:
            return entry
    raise AssertionError(f"{decision_id} missing from {_DECISIONS.name}")


# ---------------------------------------------------------------- F4 -------

def test_module_file_is_deleted() -> None:
    path = REPO_ROOT / "agents" / "agent2_backend" / f"{_MOD}.py"
    assert not path.exists(), f"retired module still on disk: {path}"
    assert importlib.util.find_spec(f"agents.agent2_backend.{_MOD}") is None


def test_retirement_suite_test_is_deleted() -> None:
    path = REPO_ROOT / "agents" / "agent3_testing" / "suite" / f"test_{_MOD}.py"
    assert not path.exists(), f"retirement test of a deleted module: {path}"


def test_quality_pass_keeps_port_tests_without_label_helper() -> None:
    # The label-helper tests went with the module; the _port_available tests
    # in the same file are the only coverage of that helper and stay.
    src = (REPO_ROOT / "agents" / "agent3_testing" / "suite"
           / "test_quality_pass.py").read_text(encoding="utf-8")
    assert "_sanitise_label" not in src
    assert "def test_port_available_returns_true_for_random_high_port" in src
    assert "def test_port_available_detects_taken_port" in src


def test_no_live_file_names_the_module() -> None:
    _repo_walk.self_check()
    scanned = 0
    record_hits = 0
    offenders: list[str] = []
    for path in _repo_walk.iter_repo_files(REPO_ROOT, _TEXT_PATTERNS):
        rel = _repo_walk.relative_posix(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        if _MOD not in text:
            continue
        if _is_record(rel):
            record_hits += 1
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _MOD in line:
                offenders.append(f"{rel}:{lineno}")
    # Not vacuous: the walk reached the tree, and the record files that DO
    # carry the name were read (docs/LEDGER.md item 652 names it).
    assert scanned > 500, f"walk collapsed: {scanned} files scanned"
    assert record_hits > 0, "no record file carried the name - scan is blind"
    assert not offenders, (
        "live files still name the deleted module (update or remove them): "
        + ", ".join(offenders)
    )


# ---------------------------------------------------------------- F3 -------

def test_decisions_version_pin_unchanged() -> None:
    data = json.loads(_DECISIONS.read_text(encoding="utf-8"))
    assert data["version"] == "phase3-1.1"


def test_decisions_file_is_ascii_lf() -> None:
    raw = _DECISIONS.read_bytes()
    assert b"\r" not in raw
    assert max(raw) < 128


def test_d011_names_legion_as_only_runtime_host() -> None:
    d011 = _decision("phase3-d011")
    text = d011["title"] + " " + d011["summary"]
    assert "Legion" in text
    assert "only runtime host" in text
    assert "rc-host" in text
    assert "100.64.0.x" in text
    # The old 3-machine live roles are gone.
    for stale in ("3 machines", "All three in tailnet", "runs League + Chrome",
                  "cross-Claude peer for", "peer-host"):
        assert stale not in text, f"d011 still carries a live role: {stale!r}"
    for name in ("Game-PC", "Peer"):
        if name in text:
            assert "retired" in text or "decommissioned" in text


def test_d011_uses_placeholder_addresses_only() -> None:
    d011 = _decision("phase3-d011")
    text = d011["title"] + " " + d011["summary"]
    for raw in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
        ip = ipaddress.ip_address(raw)
        assert ip.is_loopback or ip in ipaddress.ip_network("192.0.2.0/24"), (
            f"d011 carries a non-placeholder address {raw}"
        )


def test_d026_records_deletion_and_kept_guard() -> None:
    d026 = _decision("phase3-d026")
    text = d026["title"] + " " + d026["summary"]
    assert "pending cleanup" not in d026["title"]
    assert "deleted" in text
    assert "evaluator.py" in text and "KEPT" in text
    assert _MOD not in text
