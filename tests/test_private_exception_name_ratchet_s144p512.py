"""N818 - a PRIVATE exception class named without an ``Error`` suffix (S144-P-512).

ruff.toml does not select N818, and the 49 public names it reports are API (``SlotTimeout``,
``RouteRefused``, ``ResponseTooLarge`` ...) that other modules, tests and the byte-pinned pair import: not a
rename a breadth lane makes. A name with a leading underscore is a different class: it is module-private by
contract, so the rename is closed over one file (plus a same-package importer), and a ratchet can hold it.

Measured 2026-11-09 with ``ruff check --isolated --select N818`` over every tracked ``.py`` file: 11 private
production names. Seven are renamed here, each after a ``git grep -w`` showed no consumer outside the listed
files and no test, doc or log assertion on the old spelling:
``_UnusableLLMReply`` (agents/agent7_context/input_parser.py, imported by ui_feedback.py),
``_SkipDeterministic`` (dashboard/_state_builder.py), ``_BadSince`` (dashboard/routes_events.py),
``_BlocklistInvalid`` (lib/http/client.py), ``_Refused`` (core/operator_push.py), ``_Invalid``
(tft/rounds/store.py), ``_Fallback`` (tools/daemon_slayer_cdragon_ratio_extract.py); each now ends in ``Error``.

Four stay as the baseline, each for a stated reason, and the baseline only shrinks:
- agents/_supervisor_http.py ``_BadJsonBody``: tests/test_rm835_dashboard_reply_scrub.py embeds the
  handler's source text (``except _BadJsonBody as e:``) in a string it checks the code against.
- dashboard/_lcu_inprocess.py ``_SnapshotBudgetExceeded``: tests/rc2_l3/test_lcu_inprocess_true_audit_s144.py
  asserts the class name appears in the logged warning.
- vision_server/_http.py ``_BadBody``: tests/test_rm838_reply_scrub_non_ds.py raises it by name and asserts the
  class name appears in the logged line.
- ops/launcher/update_cycle.py ``_Interrupted``: ops/launcher/** is owned by the main session this session.

Test-tree classes (``tests/``, ``*/tests/``) are out of scope, and so is ``ops/fleet_kit`` (vendored
byte-for-byte). The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULE = "N818"
_OUT_OF_SCOPE = ("ops/fleet_kit/",)
_NAME = re.compile(r"Exception name `(\w+)`")
# file -> the private names that stay (reasons in the module docstring). Only shrinks.
_BASELINE = {
    "agents/_supervisor_http.py": {"_BadJsonBody"},
    "dashboard/_lcu_inprocess.py": {"_SnapshotBudgetExceeded"},
    "vision_server/_http.py": {"_BadBody"},
    "ops/launcher/update_cycle.py": {"_Interrupted"},
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _is_test_tree(rel: str) -> bool:
    parts = rel.split("/")
    return "tests" in parts[:-1]


@pytest.fixture(scope="module")
def private_names() -> dict[str, set[str]]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found: dict[str, set[str]] = collections.defaultdict(set)
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel not in tracked or rel.startswith(_OUT_OF_SCOPE) or _is_test_tree(rel):
            continue
        m = _NAME.search(d["message"])
        assert m, d["message"]
        if m.group(1).startswith("_"):
            found[rel].add(m.group(1))
    return dict(found)


def test_no_new_private_names(private_names):
    extra = {f: sorted(n - _BASELINE.get(f, set())) for f, n in private_names.items()
             if n - _BASELINE.get(f, set())}
    assert not extra, f"private exception classes without an Error suffix beyond the baseline: {extra}"


def test_baseline_is_exact(private_names):
    """A baseline name that no longer offends must be dropped."""
    stale = {f: sorted(n - private_names.get(f, set())) for f, n in _BASELINE.items()
             if n - private_names.get(f, set())}
    assert not stale, f"baseline names to drop: {stale}"


def test_baseline_names_only_tracked_files():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert set(_BASELINE) <= tracked, set(_BASELINE) - tracked


def test_the_seven_renamed_classes_exist_under_their_new_names():
    """Pins the rename itself: the old spelling is gone from the module, the new one is defined there."""
    cases = {
        "agents/agent7_context/input_parser.py": ("_UnusableLLMReply", "_UnusableLLMReplyError"),
        "dashboard/_state_builder.py": ("_SkipDeterministic", "_SkipDeterministicError"),
        "dashboard/routes_events.py": ("_BadSince", "_BadSinceError"),
        "lib/http/client.py": ("_BlocklistInvalid", "_BlocklistInvalidError"),
        "core/operator_push.py": ("_Refused", "_RefusedError"),
        "tft/rounds/store.py": ("_Invalid", "_InvalidError"),
        "tools/daemon_slayer_cdragon_ratio_extract.py": ("_Fallback", "_FallbackError"),
    }
    for rel, (old, new) in cases.items():
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert re.search(rf"^class {new}\(", src, re.M), (rel, new)
        assert not re.search(rf"\b{old}\b", src), (rel, old)


def test_probe_is_live():
    """The isolated run reports a private name without the suffix, so an empty tree result is a real scan."""
    out = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"],
                stdin="class _Oops(Exception):\n    pass\n")
    assert [d["code"] for d in out] == [_RULE]
    assert _NAME.search(out[0]["message"]).group(1) == "_Oops"


def test_an_error_suffix_is_quiet():
    out = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"],
                stdin="class _OopsError(Exception):\n    pass\n")
    assert out == []
