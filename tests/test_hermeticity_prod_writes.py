# arch: RF5 test-hermeticity regression - prod write-target globals + suite guard | section=tests | frozen=no
"""RF5 (test hermeticity sibling sweep) regression.

The RF5 sweep (full RC + DS suites, before/after prod-artifact snapshot) found
NO test that actively pollutes a production artifact - the suite is hermetic.
But two production writers hardcode a module-global prod path and take NO
``path`` parameter, so a caller has no tmp seam at all and the ONLY defense is
redirecting the global:

  core/coach_trace.py     ``append()``      -> _TRACE_FILE = data/coach_trace.jsonl
  core/ds_calibration.py  ``log_ds_run()``  -> _LOG_PATH   = data/ds_calibration.jsonl

(contrast the shadow writers, which the conftest SHADOW_PATH net already
redirects, and ds_coach_shadow / decision_detector / loop_controller, which
every caller already drives with an explicit path= or its own monkeypatch.)

These tests pin the conftest ``redirect_prod_write_paths_to_tmp`` autouse net:
the two globals must resolve OFF the real data/ dir during any test, and calling
the no-path writers must land in tmp - never the production jsonl. Mirrors the
conftest SHADOW_PATH precedent (item 386) + the loop_controller CTL redirect
(test_p2w4_hw2_b, OPEN2).
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_PROD_DATA = (_REPO / "data").resolve()


def _under(child, parent: Path) -> bool:
    try:
        Path(child).resolve().relative_to(parent)
        return True
    except ValueError:
        return False


class TestProdWriteGlobalsRedirectedOffProd:
    """The autouse net must point each hardcoded no-path writer's global off
    the real data/ dir, so a default-path write cannot touch production."""

    @pytest.mark.parametrize(
        "mod_name,attr",
        [
            ("core.coach_trace", "_TRACE_FILE"),
            ("core.ds_calibration", "_LOG_PATH"),
        ],
    )
    def test_global_points_off_prod_data(self, mod_name, attr):
        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr)
        assert not _under(val, _PROD_DATA), (
            mod_name + "." + attr + " still resolves under prod data/ ("
            + str(val) + "); the conftest redirect net must point it at tmp")


class TestNoPathWritersLandInTmp:
    """With the net active, the no-path writers append to the redirected tmp
    target and leave the production artifact byte-for-byte unchanged."""

    def test_coach_trace_append_off_prod(self):
        import core.coach_trace as ct

        prod = _PROD_DATA / "coach_trace.jsonl"
        before = prod.stat().st_size if prod.exists() else -1
        ct.append(mode="ARAM", model="m", user_prompt="u", response="r")
        after = prod.stat().st_size if prod.exists() else -1
        assert after == before, "coach_trace.append polluted prod coach_trace.jsonl"
        assert Path(ct._TRACE_FILE).exists(), "append did not write the redirected tmp log"

    def test_ds_calibration_log_off_prod(self):
        import core.ds_calibration as dc

        prod = _PROD_DATA / "ds_calibration.jsonl"
        before = prod.stat().st_size if prod.exists() else -1
        dc.log_ds_run("Ahri", "ARAM", 9, [3157], [{"item_id": 3089, "delta_dps": 1.0}])
        after = prod.stat().st_size if prod.exists() else -1
        assert after == before, "ds_calibration.log_ds_run polluted prod ds_calibration.jsonl"
        assert Path(dc._LOG_PATH).exists(), "log_ds_run did not write the redirected tmp log"
