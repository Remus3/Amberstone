"""RM-1305 - the vision token bucket in core/cost_tracker.py stays removed.

Why it was dead, measured on every source surface before the removal:

- CostTracker.acquire_vision_token had no production caller. Its last one, in
  modes/shared_vision.py GameVisionReader._extract, was removed on purpose by
  b3f7939d5 (operator directive 2026-06-03: stop throttling vision capture; the
  coach vision-loop interval paces calls and the daily spend cap stays as the
  cost backstop).
- The config keys vision_calls_per_min and vision_burst had no reader but the
  bucket, and no tracked config, schema or example carried them.
- Nothing reads the metrics rc_vision_token_granted_total and
  rc_vision_token_denied_total: no tracked file names them, and a counter
  nothing bumps could only ever report zero.

It was not inert either. CostTracker.__init__ ran float(vision_burst), so a key
malformed at first construction made get_tracker() raise for every caller, and
the singleton stayed unset, so it raised again on the next call.
GameVisionReader._extract, BaseCoach._maybe_coach and the SR coach gate in
coach_integration/_coach.py all swallow that raise before they reach allow_call,
so a bad key for a limiter nothing uses also turned off the daily spend cap on
those paths.

If you find yourself adding any of this back, re-decide b3f7939d5 first.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from core import cost_tracker, prom_metrics
from tests import _repo_walk

_ROOT = Path(__file__).resolve().parent.parent
_LAST_CALLER_REMOVED = "b3f7939d5"

_GONE_MODULE = ("CFG_VISION_RATE_PER_MIN", "CFG_VISION_BURST",
                "DEFAULT_VISION_RATE", "DEFAULT_VISION_BURST",
                "_M_VISION_TOKEN_GRANTED", "_M_VISION_TOKEN_DENIED")
_GONE_TRACKER = ("acquire_vision_token", "_vb_lock", "_vb_tokens", "_vb_last")
_GONE_KEYS = ("vision_calls_per_min", "vision_burst")
_GONE_METRICS = ("rc_vision_token_granted_total",
                 "rc_vision_token_denied_total")
_GONE_NAMES = _GONE_MODULE + _GONE_TRACKER + _GONE_KEYS + _GONE_METRICS

_SOURCE_GLOBS = ("*.py", "*.js", "*.mjs", "*.html", "*.ps1", "*.bat", "*.cmd",
                 "*.sh", "*.vbs", "*.ahk", "*.yml", "*.yaml", "*.toml", "*.ini")
# Must be walked: the tracked half of _read_config (ops/rc_config.json), the
# tracked example of its gitignored half (config/coach_settings.json, which this
# guard cannot see) and both schemas.
_CONFIG_ANCHORS = {"config/coach_settings.example.json",
                   "config/schema/coach_settings.schema.json",
                   "config/schema/rc_config.schema.json",
                   "ops/rc_config.json"}


def _production_sources():
    """(rel, text) for tracked non-test, non-doc source files."""
    for path in _repo_walk.iter_repo_files(_ROOT, _SOURCE_GLOBS):
        rel = _repo_walk.relative_posix(path, _ROOT)
        if rel.startswith(("tests/", "docs/")) or "/tests/" in rel:
            continue
        try:
            yield rel, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue


def test_no_production_source_names_the_bucket():
    """A name match, so a getattr or a comment cannot escape it. The live
    neighbours in the same module anchor the walk: an empty one fails."""
    hits: list[tuple[str, str]] = []
    dedupe_users: set[str] = set()
    scanned = 0
    for rel, text in _production_sources():
        scanned += 1
        hits.extend((rel, n) for n in _GONE_NAMES if n in text)
        if "vision_dedupe_get" in text:
            dedupe_users.add(rel)
    assert scanned > 100, scanned
    assert {"core/cost_tracker.py", "core/moon_proxy.py"} <= dedupe_users
    assert hits == []


def test_no_tracked_config_carries_the_keys():
    """Every tracked JSON under config/ and ops/ (a leftover key would read as a
    live setting). The anchors keep an empty walk from passing."""
    hits: list[tuple[str, str]] = []
    walked: set[str] = set()
    for path in _repo_walk.iter_repo_files(_ROOT, ("*.json",)):
        rel = _repo_walk.relative_posix(path, _ROOT)
        if not rel.startswith(("config/", "ops/")):
            continue
        walked.add(rel)
        text = path.read_text(encoding="utf-8", errors="replace")
        hits.extend((rel, k) for k in _GONE_KEYS if k in text)
    assert walked >= _CONFIG_ANCHORS, sorted(_CONFIG_ANCHORS - walked)
    assert hits == []


def test_the_module_and_the_tracker_lost_the_surface(tmp_path):
    tracker = cost_tracker.CostTracker(config_provider=dict, spend_dir=tmp_path)
    assert [n for n in _GONE_MODULE if hasattr(cost_tracker, n)] == []
    assert [n for n in _GONE_TRACKER if hasattr(tracker, n)] == []
    # The neighbours this removal has to leave alone.
    assert hasattr(cost_tracker, "_M_VISION_DEDUPE_HITS")
    assert callable(tracker.vision_dedupe_get)
    assert callable(tracker.allow_call)


def test_the_metrics_are_not_registered():
    names = {m.name for m in prom_metrics._REGISTRY}
    assert "rc_vision_dedupe_hits_total" in names
    assert not names & set(_GONE_METRICS)


@pytest.mark.parametrize("bad", ["not-a-number", [1], {"a": 1}, None])
def test_a_malformed_burst_key_cannot_break_construction(tmp_path, bad):
    """The live half of the defect: a key for a limiter nothing used raised out
    of every get_tracker(), and the callers that swallow it skip allow_call."""
    tracker = cost_tracker.CostTracker(
        config_provider=lambda: {"vision_burst": bad, "daily_budget_usd": 1.0},
        spend_dir=tmp_path)
    assert tracker.allow_call() is True
    tracker.record_call(model="claude-sonnet-5-5", input_tokens=1_000_000,
                        purpose="vision_direct")
    assert tracker.allow_call() is False


def _calls_attribute(fn: ast.AST, attr: str) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == attr for n in ast.walk(fn))


def test_the_backstop_the_directive_kept_still_stands():
    """b3f7939d5 dropped the bucket only because the daily cap stayed."""
    tree = ast.parse((_ROOT / "modes" / "shared_vision.py")
                     .read_text(encoding="utf-8"))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "GameVisionReader")
    extract = next(n for n in cls.body
                   if isinstance(n, ast.FunctionDef) and n.name == "_extract")
    assert _calls_attribute(extract, "allow_call")
    assert not _calls_attribute(extract, "acquire_vision_token")


def test_the_named_commit_really_removed_the_last_caller():
    have = subprocess.run(
        ["git", "cat-file", "-e", f"{_LAST_CALLER_REMOVED}^{{commit}}"],
        cwd=_ROOT, capture_output=True, check=False)
    # Fails, never skips, on a shallow clone: tests/test_ci_checkout_history_depth.py.
    assert have.returncode == 0, f"{_LAST_CALLER_REMOVED} absent from this clone"
    diff = subprocess.run(
        ["git", "show", "--format=", _LAST_CALLER_REMOVED, "--",
         "modes/shared_vision.py"],
        cwd=_ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    assert any(line.startswith("-") and "acquire_vision_token" in line
               for line in diff.splitlines())
