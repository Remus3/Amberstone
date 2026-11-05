"""RM-1031: the cc_conditional override file path does not depend on the CWD.

``cc_conditional._OVERRIDES_PATH`` was ``Path("data") / ...``, which resolves
against the process working directory. A DS process started from any other
directory (a service host, a tool run) silently read no overrides, or read a
decoy file in that directory. The path is anchored on ``__file__`` now.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.daemon_slayer import cc_conditional as ccc

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_overrides_path_is_absolute_and_under_the_repo_root() -> None:
    assert ccc._OVERRIDES_PATH.is_absolute()
    assert ccc._OVERRIDES_PATH == (
        _REPO_ROOT / "data" / "cc_conditional_calibration.json"
    )


def test_a_decoy_file_in_the_foreign_cwd_is_ignored(tmp_path, monkeypatch) -> None:
    decoy_dir = tmp_path / "data"
    decoy_dir.mkdir()
    (decoy_dir / "cc_conditional_calibration.json").write_text(
        json.dumps({"default_condition_probability": {"decoy_tag": 0.01}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    real = ccc._OVERRIDES_PATH
    expected = json.loads(real.read_text(encoding="utf-8")) if real.is_file() else {}
    assert ccc._load_overrides() == expected
    assert "decoy_tag" not in json.dumps(ccc._load_overrides())
