"""RM-155 regression: the suite must never write data/fusion_shadow.jsonl.

The corpus is gitignored, so in a fresh tree run 1 SKIPPED
`test_real_fusion_shadow_corpus_invariants` and passed - while the suite itself
appended one record to the production path. Run 2 then found a 1-record corpus,
no longer skipped, and failed `assert narrowed > 0`. A test writing production
state that another test reads makes the whole suite non-idempotent, which in
turn makes every later audit cycle's "green" untrustworthy.

Root fix: the autouse `redirect_fusion_shadow_to_tmp` fixture in
tests/conftest.py points `RC_FUSION_SHADOW_PATH` at a tmp dir for EVERY test,
so no test can reach the production path whether or not it remembers to set the
env var itself. These tests pin that fixture.
"""
from __future__ import annotations

import os
from pathlib import Path

from modes.shared_vision import _fusion_shadow_path

_PROD_CORPUS = (Path(__file__).resolve().parent.parent
                / "data" / "fusion_shadow.jsonl")


def test_env_override_is_set_for_every_test():
    """The autouse fixture must be active without the test opting in."""
    override = os.getenv("RC_FUSION_SHADOW_PATH")
    assert override, "RC_FUSION_SHADOW_PATH is not set - autouse fixture missing"
    assert Path(override).resolve() != _PROD_CORPUS.resolve()


def test_resolved_shadow_path_is_not_the_production_corpus():
    """Resolve through the real production helper, not a reimplementation."""
    resolved = Path(_fusion_shadow_path()).resolve()
    assert resolved != _PROD_CORPUS.resolve(), (
        f"fusion shadow would be written to the production corpus: {resolved}"
    )


def test_shadow_writes_land_under_a_temp_directory():
    resolved = Path(_fusion_shadow_path()).resolve()
    assert "fusionshadow" in str(resolved).lower() or "tmp" in str(resolved).lower(), (
        f"unexpected shadow target {resolved}"
    )
