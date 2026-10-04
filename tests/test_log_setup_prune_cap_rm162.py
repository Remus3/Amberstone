"""RM-162: `core/log_setup._prune_old_logs` must refuse a non-positive cap.

Fourth instance of the RM-161 arithmetic: `cutoff = now - days * 86400`, so a
cap of 0 or below puts the cutoff at or after now and every `*.log*` in the
directory is "older" than it - the retention knob would erase the corpus.
The only caller (`setup()`) passes the 30-day default and already degrades
any exception to "0 pruned", so raising cannot break logging startup.
"""

from __future__ import annotations

import os
import time

import pytest

from core import log_setup


def _seed(tmp_path, n=3, age_s=60):
    old = time.time() - age_s
    paths = []
    for i in range(n):
        p = tmp_path / f"2026-01-0{i + 1}.log"
        p.write_text("x", encoding="ascii")
        os.utime(p, (old, old))
        paths.append(p)
    return paths


@pytest.mark.parametrize("bad", [0, -1, -30])
def test_non_positive_cap_raises_and_deletes_nothing(tmp_path, bad):
    paths = _seed(tmp_path)
    with pytest.raises(ValueError):
        log_setup._prune_old_logs(tmp_path, retention_days=bad)
    assert all(p.exists() for p in paths)


def test_positive_cap_still_prunes_only_old_files(tmp_path):
    old = _seed(tmp_path, n=2, age_s=40 * 86400)
    fresh = tmp_path / "2026-10-04.log"
    fresh.write_text("x", encoding="ascii")
    assert log_setup._prune_old_logs(tmp_path, retention_days=30) == 2
    assert not any(p.exists() for p in old)
    assert fresh.exists()

