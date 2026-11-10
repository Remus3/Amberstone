"""S144-P-523 - ruff RUF055 and RUF039 held at zero outside the DS tree.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 13 findings in 11 test files, none in
production code, none in the vendored kit.

RUF055 (unnecessary-regular-expression): ``re.search(r'model: str = "claude-haiku', live)`` is a substring test
spelled as a regex; seven sites became ``needle in haystack`` (``test_cost_health_watchdog_vision_lever_s144p58`` x2,
``test_gated_g312_aram_debounce_lag``, ``test_gated_g506_debounce_lag`` - whose ``import re`` had no other use and
went - ``test_stale_fade_gentle_t12``, ``snapshot_panels/test_overlay_hidden_display_contract``) and the one
``re.finditer("%", line)`` loop in ``test_arena_augment_playline`` became an ``enumerate`` over the characters
(same index, same prefix slice, same message).

RUF039 (unraw-re-pattern): the two ``re.compile("[\\u2013...]")`` dash-glyph bans
(``test_champ_select_pick_placeholder_provenance``, ``test_stats_panel_kp_live``) are now raw strings
(``r"[\\u2013...]"``; ``re`` reads the ``\\uXXXX`` escape itself, so the compiled pattern is identical, which
``test_the_raw_dash_ban_compiles_to_the_same_pattern`` pins), and the three one-letter / dotted literals in
``test_regex_flag_alias_ratchet_s144p152`` (x2) and ``test_regex_match_and_implicit_optional_ratchet_s144p113`` are
``r"..."`` so a reader sees at a glance that no Python escape is in play.

The held scope is every tracked ``.py`` file NOT under the two fences below; ``_BASELINE`` is empty, so ANY new finding
fails ``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a
finding, and ``--preview`` because both rules are preview-only in this ruff.
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

_RULES = "RUF055,RUF039"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "agents/daemon_slayer/": "the DS lane's tree (one RUF039 site, tests/test_effects_expansion.py)",
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {}
_FIXED = (
    "tests/snapshot_panels/test_overlay_hidden_display_contract.py",
    "tests/test_arena_augment_playline.py",
    "tests/test_champ_select_pick_placeholder_provenance.py",
    "tests/test_cost_health_watchdog_vision_lever_s144p58.py",
    "tests/test_gated_g312_aram_debounce_lag.py",
    "tests/test_gated_g506_debounce_lag.py",
    "tests/test_regex_flag_alias_ratchet_s144p152.py",
    "tests/test_regex_match_and_implicit_optional_ratchet_s144p113.py",
    "tests/test_stale_fade_gentle_t12.py",
    "tests/test_stats_panel_kp_live.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return not any(rel.startswith(prefix) for prefix in _NOT_THIS_SCOPE)


@pytest.fixture(scope="module")
def held_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if _in_scope(t)}
    assert len(held) > 500, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in held:
            counts[rel] += 1
    return dict(counts)


def test_no_file_exceeds_its_baseline(held_counts):
    over = {f: n for f, n in held_counts.items() if n > _BASELINE.get(f, 0)}
    assert not over, f"ruff {_RULES} findings above the baseline, file: count: {over}"


def test_the_baseline_only_shrinks(held_counts):
    stale = {f: n for f, n in _BASELINE.items() if held_counts.get(f, 0) < n}
    assert not stale, f"baseline entries to lower or remove (fixed since): {stale}"


def test_the_fixed_modules_are_clean_tracked_and_in_scope(held_counts):
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel
        assert rel not in _BASELINE, rel
        assert held_counts.get(rel, 0) == 0, rel


def test_the_fence_is_not_empty_of_findings_by_accident():
    """A positive control: each rule does fire on the pattern it exists for."""
    plain = _ruff(["--stdin-filename", "probe.py", "-"], stdin='import re\nassert re.search(r"needle", hay)\n')
    assert [d["code"] for d in plain] == ["RUF055"]
    unraw = _ruff(["--stdin-filename", "probe.py", "-"], stdin='import re\nre.compile("[\\\\u2013]")\n')
    assert [d["code"] for d in unraw] == ["RUF039"]


def test_the_raw_dash_ban_compiles_to_the_same_pattern():
    """Behaviour pin: the raw spelling is the same regex as the old escaped one."""
    escaped = "[\\u2013\\u2014\\u2018\\u2019\\u201c\\u201d]"
    old = re.compile(escaped)
    new = re.compile(r"[\u2013\u2014\u2018\u2019\u201c\u201d]")
    for ch in ("\u2013", "\u2014", "\u2018", "\u2019", "\u201c", "\u201d"):
        assert old.search(ch) and new.search(ch)
    assert not new.search("plain ascii - and 'quotes'")


def test_the_percent_scan_matches_the_finditer_it_replaced():
    """Behaviour pin: an enumerate over characters sees the same indexes as re.finditer."""
    for line in ("40%", "%i:StatAnvil%", "a%b%%", "", "no sign"):
        old = [m.start() for m in re.finditer(re.escape("%"), line)]
        assert [at for at, char in enumerate(line) if char == "%"] == old
