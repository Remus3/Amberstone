"""RM-722 (d): the dated test module name is gone; the DPS stat-sweep tests keep their module.

`tests/test_ds_sweep_2026_05_30.py` carried a date in its name (repo review
B30-02) and tested `agents/daemon_slayer/dps_sweep.py`. It is renamed to
`tests/test_dps_sweep.py`, after the module it covers; the tests inside are
unchanged, so the `--collect-only` count does not move. The historical audit
snapshot `ops/audit/p2w5_slices.json` records a past tree and is left as it is.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OLD = "tests/test_ds_sweep_2026_05_30.py"
NEW = "tests/test_dps_sweep.py"
# Living files whose docstrings named the old module.
CITERS = ("tests/test_ds_sweep_panel_dom.py", "tests/test_routes_ds_sweep.py")


def _tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return set(out.splitlines())


def test_the_dated_name_is_gone_and_the_new_name_is_tracked():
    tracked = _tracked()
    assert tracked, "git ls-files enumerated nothing"
    assert OLD not in tracked, f"{OLD} is still tracked"
    assert NEW in tracked, f"{NEW} is not tracked"


def test_the_renamed_module_still_covers_dps_sweep():
    text = (REPO / NEW).read_text(encoding="ascii")
    assert text.startswith('"""dps_sweep - 1-variable DPS stat-sweep')
    assert "class ArmorAxisTests" in text


def test_docstring_citers_name_the_new_module():
    for rel in CITERS:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "test_ds_sweep_2026_05_30" not in text, f"{rel} still names the old module"
        assert "test_dps_sweep.py" in text, f"{rel} does not name {NEW}"
