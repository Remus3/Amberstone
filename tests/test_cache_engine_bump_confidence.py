"""Regression (headless audit 2026-06-03): CacheEngine.bump_confidence had two
defects - the success path always emitted a false "Bad advice flagged" INFO log
(line was at method scope, copy-pasted from flag_bad), and the except branch
referenced `conn` which is out of scope outside the `with self._conn()` block,
raising NameError on any DB error instead of logging the warning."""
import logging

from modules.cache_engine import CacheEngine


def _state():
    return {"champion": "Ahri", "patch_version": "16.11.1", "game_time_s": 100}


def test_bump_confidence_success_emits_no_bad_advice_log(tmp_path, caplog):
    eng = CacheEngine(tmp_path / "c.db")
    eng.set(_state(), "resp")
    with caplog.at_level(logging.INFO, logger="cache"):
        eng.bump_confidence(_state(), 1.5, flag="grade_S")
    msgs = [r.getMessage() for r in caplog.records]
    assert not any("Bad advice flagged" in m for m in msgs), msgs


def test_bump_confidence_db_error_does_not_raise(tmp_path):
    eng = CacheEngine(tmp_path / "c.db")

    def _boom():
        raise RuntimeError("simulated db failure")

    eng._conn = _boom
    # Must not propagate (the except branch must not reference an out-of-scope conn).
    eng.bump_confidence(_state(), 1.5, flag="grade_A")
