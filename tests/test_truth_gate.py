"""Tests for tools/truth_gate.py - pure reconciliation logic, no live suite runs."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.truth_gate import (
    parse_pytest_summary,
    check_file_claims,
    reconcile,
)


# --- parse_pytest_summary ---

def test_parse_summary_all_passed():
    s = parse_pytest_summary("1397 passed, 2 skipped, 1 xfailed in 61.32s")
    assert s["passed"] == 1397
    assert s["failed"] == 0
    assert s["errors"] == 0
    assert s["skipped"] == 2


def test_parse_summary_failures():
    s = parse_pytest_summary("2 failed, 1395 passed in 60.1s")
    assert s["failed"] == 2
    assert s["passed"] == 1395


def test_parse_summary_error():
    s = parse_pytest_summary("1 error in 0.5s")
    assert s["errors"] == 1
    assert s["passed"] == 0


def test_parse_summary_banner_form():
    s = parse_pytest_summary("==== 5629 passed, 3 warnings in 120.00s ====")
    assert s["passed"] == 5629
    assert s["failed"] == 0


def test_parse_summary_no_tests_ran():
    s = parse_pytest_summary("no tests ran in 0.01s")
    assert s["passed"] == 0
    assert s["no_tests_ran"] is True


def test_parse_summary_takes_last_line(tmp_path):
    text = "FAILED tests/x.py::t - boom\n1 failed, 9 passed in 2.0s\n"
    s = parse_pytest_summary(text)
    assert s["failed"] == 1
    assert s["passed"] == 9


# --- check_file_claims ---

def test_file_claim_missing_path(tmp_path):
    obs = check_file_claims(
        [{"path": str(tmp_path / "ghost.py"), "must_contain": []}]
    )
    assert obs[0]["exists"] is False


def test_file_claim_content_hit_and_miss(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def real_method():\n    return 1\n", encoding="utf-8")
    obs = check_file_claims(
        [{"path": str(f), "must_contain": ["real_method", "phantom_field"]}]
    )
    assert obs[0]["exists"] is True
    assert obs[0]["missing_snippets"] == ["phantom_field"]


def test_file_claim_all_present(tmp_path):
    f = tmp_path / "ok.py"
    f.write_text("alpha beta\n", encoding="utf-8")
    obs = check_file_claims([{"path": str(f), "must_contain": ["alpha"]}])
    assert obs[0]["missing_snippets"] == []


# --- reconcile ---

def _claims(**over):
    base = {
        "run_id": "t",
        "slices": [
            {
                "id": "S1",
                "claim": "did thing",
                "files": [{"path": "x.py", "must_contain": ["y"]}],
                "claimed_passed": 10,
                "claimed_failed": 0,
            }
        ],
    }
    base.update(over)
    return base


def _green_suite():
    return {"passed": 10, "failed": 0, "errors": 0, "skipped": 0,
            "no_tests_ran": False, "exit_code": 0, "cmd": "py -m pytest -q"}


def _ok_files():
    return [{"path": "x.py", "exists": True, "missing_snippets": []}]


def test_reconcile_all_confirm_proceeds():
    rep = reconcile(_claims(), _green_suite(), {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "PROCEED"
    assert rep["slices"][0]["verdict"] == "CONFIRM"
    assert rep["quarantined"] == []


def test_reconcile_missing_file_quarantines():
    files = [{"path": "x.py", "exists": False, "missing_snippets": []}]
    rep = reconcile(_claims(), _green_suite(), {"S1": files},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "REFUSE"
    assert rep["slices"][0]["verdict"] == "QUARANTINE"
    assert "S1" in rep["quarantined"]


def test_reconcile_missing_snippet_quarantines():
    files = [{"path": "x.py", "exists": True, "missing_snippets": ["y"]}]
    rep = reconcile(_claims(), _green_suite(), {"S1": files},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "REFUSE"


def test_reconcile_count_mismatch_quarantines():
    suite = dict(_green_suite(), passed=9)
    rep = reconcile(_claims(), suite, {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["slices"][0]["verdict"] == "QUARANTINE"
    assert any("claimed_passed" in d for d in rep["slices"][0]["discrepancies"])


def test_reconcile_suite_failures_refuse_even_if_slices_confirm():
    claims = _claims()
    claims["slices"][0]["claimed_passed"] = None  # slice makes no count claim
    suite = dict(_green_suite(), failed=2, exit_code=1)
    rep = reconcile(claims, suite, {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "REFUSE"


def test_reconcile_ci_failure_refuses():
    rep = reconcile(_claims(), _green_suite(), {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"},
                    ci_obs={"status": "failure"})
    assert rep["verdict"] == "REFUSE"
    assert any("ci" in d.lower() for d in rep["global_discrepancies"])


def test_reconcile_ci_unavailable_is_warning_not_refusal():
    rep = reconcile(_claims(), _green_suite(), {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"},
                    ci_obs={"status": "unavailable"})
    assert rep["verdict"] == "PROCEED"


def test_reconcile_report_is_json_serializable():
    rep = reconcile(_claims(), _green_suite(), {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    json.dumps(rep)
