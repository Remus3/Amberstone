"""S144-D-338..341 - no DS test, and no build-order table test, calls a 32xxxx
item id "ARAM".

WHY. S144-D-334..337 relabelled the DS modules: every ``32xxxx`` row in the
live feed carries map 11 (Summoner's Rift) only, and the ARAM (map 12) copies
are the ``12xxxx`` rows. That guard scanned ``agents/daemon_slayer/*.py`` only,
so the test files kept the old label: 34 flagged lines, seven constants named
``*_ARAM`` holding a ``32xxxx`` id, and two calls that paired a ``32xxxx`` id
with ``mode="ARAM"`` as if it were the ARAM item. Two RC build-order tests
went further and said the ARAM tables "use 32xxxx mirror ids" and that those
ids are "absent from the base catalog". Measured 2026-11-09 at 16.22.1: both
ARAM tables (precompute + variants) carry ZERO ``32xxxx`` ids and one
``12xxxx`` id, and every id in all six tables is in the catalog.

* S144-D-338: DS test docstrings, comments and messages relabel every
  ``32xxxx`` id as the map-11 copy.
* S144-D-339: the seven ``*_ARAM`` constants, one ``aram_dmg`` local and the
  twenty ``aram``-named test methods that hold or probe a ``32xxxx`` id are
  renamed ``*_MAP11`` / ``copy_dmg`` / ``map11``. Assertions are unchanged.
  The name check flags an ``aram``-named test or local whose own line or
  next four lines use a ``32xxxx`` id.
* S144-D-340: the two ``mode="ARAM"`` pairings with a ``32xxxx`` id (Dawncore
  326621 in the First Light AP test, Redemption 323107 in test_hps) now pass
  ``mode="SR"``, the only map the id is legal on. Expected values unchanged.
* S144-D-341: this guard, plus the build-order table prose fix
  (``tests/test_build_order_map_legality.py``,
  ``tests/test_build_order_content_freshness.py``) and a live premise test:
  no shipped ARAM build-order table carries a ``32xxxx`` id.

The line checker is the S144-D-337 one, imported, so both guards flag the
same shapes. Blind spot (inherited): a label spread over three lines is not
caught; ``test_enchanter_hsp_magnitude_drift_r197.py`` names its ``32``
prefix ``ARAM_PREFIX`` and labels it "aram", which neither check reads (a
bare two-digit prefix, not a six-digit id) - left for a later pass because
another lane holds an unlanded edit to that file.
"""

from __future__ import annotations

import re
from pathlib import Path

from agents.daemon_slayer.tests.test_ds_32xxxx_map11_label_s144d334 import (
    _line_problems,
)
from core import build_order_precompute as bop
from core import build_order_variants as bov

_ROOT = Path(__file__).resolve().parents[3]
_DS_TESTS = _ROOT / "agents" / "daemon_slayer" / "tests"
_RC_TESTS = _ROOT / "tests"

# The two guard files carry planted ARAM labels on purpose.
_SELF_FIXTURES = frozenset({
    "test_ds_32xxxx_map11_label_s144d334.py",
    "test_ds_32xxxx_map11_label_tests_s144d338.py",
})

_ARAM_NAMED_32_CONST = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*=\s*\(?\s*[\"']32\d{4}[\"']"
)


_ARAM_NAMED_DEF_OR_LOCAL = re.compile(
    r"^\s*(?:def\s+test_(?:\w*_)?aram\w*\s*\(|(?:\w*_)?aram\w*\s*=[^=])",
    re.IGNORECASE,
)
_ID32_ONLY = re.compile(r"\b32\d{4}\b")
_NAME_WINDOW = 5


def _name_problems(lines: list[str]) -> list[tuple[int, str]]:
    """An ``aram``-named test method or local whose own line or next lines
    use a ``32xxxx`` id."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if not _ARAM_NAMED_DEF_OR_LOCAL.match(line):
            continue
        if any(_ID32_ONLY.search(x) for x in lines[i:i + _NAME_WINDOW]):
            out.append((i + 1, line.strip()))
    return out


def _test_files() -> list[Path]:
    files = list(_DS_TESTS.glob("*.py")) + list(_RC_TESTS.glob("*.py"))
    return sorted(p for p in files if p.is_file() and p.name not in _SELF_FIXTURES)


def _const_problems(lines: list[str]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _ARAM_NAMED_32_CONST.match(line)
        if m and "ARAM" in m.group(1).upper():
            out.append((i + 1, line.strip()))
    return out


def test_scan_is_not_empty() -> None:
    files = _test_files()
    names = {p.name for p in files}
    assert sum(1 for p in files if p.parent == _DS_TESTS) > 500, len(files)
    assert sum(1 for p in files if p.parent == _RC_TESTS) > 500, len(files)
    assert "test_fimbulwinter_shield_r129.py" in names
    assert "test_build_order_map_legality.py" in names


def test_no_test_file_labels_a_32xxxx_id_aram() -> None:
    problems: list[str] = []
    for path in _test_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        hits = dict(
            _line_problems(lines) + _const_problems(lines) + _name_problems(lines)
        )
        for lineno, text in sorted(hits.items()):
            problems.append(f"{path.relative_to(_ROOT).as_posix()}:{lineno}: {text}")
    assert not problems, (
        "32xxxx ids are map 11 (SR) only in the live feed; relabel these lines:\n"
        + "\n".join(problems)
    )


def test_const_checker_flags_planted_names() -> None:
    planted = [
        '_FIMB_ARAM = "323121"     # map-11 copy',
        'FROZEN_HEART_ARAM = "323110"',
        '_HR_ARAM_PHANTOM = "326664"',
        '_aram_id = ("322501")',
    ]
    assert {n for n, _ in _const_problems(planted)} == {1, 2, 3, 4}


def test_const_checker_passes_honest_names() -> None:
    clean = [
        '_FIMB_MAP11 = "323121"',
        'ARAM_PREFIX = "32"',
        '_SPATULA_ARAM = "994403"',
        '_HUBRIS_ARAM = "126697"',
    ]
    assert _const_problems(clean) == []


def test_name_checker_flags_planted_names() -> None:
    planted = [
        "    def test_aram_mirror_id_is_not_registered(self) -> None:",
        "        # 324633 is NOT in the DS item index.",
        '        self.assertNotIn("324633", _ITEM_OMNIVAMP)',
        '        aram_dmg = ITEM_EFFECTS["323042"].periodics[0]',
        "    def test_323003_archangel_aram(self) -> None:",
        '        e = ITEM_EFFECTS.get("323003")',
    ]
    assert {n for n, _ in _name_problems(planted)} == {1, 4, 5}


def test_name_checker_passes_honest_names() -> None:
    clean = [
        "    def test_map11_copy_id_is_not_registered(self) -> None:",
        '        self.assertNotIn("324633", _ITEM_OMNIVAMP)',
        "    def test_aram_modifiers_scale_heal(self) -> None:",
        '        r = compute_hps(snap, "Soraka", item_ids=["3107"], mode="ARAM")',
        "        is_aram = mode == 'ARAM'",
        "",
        "",
        "",
        "",
        '        x = "323107"',
        '        params = {"item_ids": ["323107"]}',
        "    def test_param_sweep_keeps_323107(self) -> None:",
    ]
    assert _name_problems(clean) == []


def test_live_aram_build_order_tables_carry_no_32xxxx_id() -> None:
    patch = bop.resolve_patch()
    for name, loader in (
        ("precompute", bop.load_build_order_precompute),
        ("variants", bov.load_build_order_variants),
    ):
        content = loader(mode="aram", patch=patch).get("build_orders") or {}
        ids: set[str] = set()
        _collect(content, ids)
        assert len(ids) >= 20, f"{name} aram: only {len(ids)} ids - walk is vacuous"
        bad = sorted(i for i in ids if len(i) == 6 and i.startswith("32"))
        assert not bad, f"{name} aram table carries map-11-only 32xxxx ids: {bad}"


def _collect(node: object, out: set[str]) -> None:
    if isinstance(node, dict):
        for v in node.values():
            _collect(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect(v, out)
    elif isinstance(node, str) and node.isdigit() and 4 <= len(node) <= 6:
        out.add(node)
