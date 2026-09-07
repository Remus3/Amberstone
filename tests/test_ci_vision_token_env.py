"""CI must supply a vision token, and it must be an obvious throwaway.

MEASURED 2026-09-06. `f8323887e` untracked `config/vision_token.txt`, which had
been a live 32-hex `X-RC-Token` committed to the repo since creation. That was
the right call. But nothing replaced it for CI, and `core/vision_token._resolve`
raises rather than defaulting - deliberately, so a misconfigured DEPLOY fails
loud instead of authenticating every request with a known constant. The runner
has neither the env var nor the file, so main went red on the next push:

    RuntimeError: vision_token: no token configured
    120 failed, 30785 passed, 255 skipped, 53 errors

That is 320 error lines from one missing value, and it is not a flake: every
push after that commit fails identically until CI is given a token.

WHY A DUMMY IS THE RIGHT FIX HERE, stated so it is not "hardened" later into a
repo secret by someone who reads only the variable name. The token authenticates
`http://127.0.0.1:8889`, a LOOPBACK relay that exists only on Legion. CI never
starts that listener; the tests import the resolver, read a value and assert on
plumbing. So the value's only job on a runner is to be non-empty. Putting a real
secret in GitHub to satisfy an assertion about non-emptiness buys nothing and
adds a credential to a second system.

The two things this pins, and they pull in opposite directions on purpose:

1. The value EXISTS, so the red above cannot silently return by someone tidying
   the `env:` block away.
2. The value is NOT shaped like the real token. `_resolve` does no format
   validation at all - any non-empty string resolves - so nothing except this
   test stops the next person from "fixing" a CI failure by pasting the live
   32-hex token back into a tracked file. That is precisely the state
   `f8323887e` removed, and it would land wearing the costume of a bug fix.

Deliberately NOT asserted: that `docs-guards.yml` carries the variable. That
workflow is green without it because its selector currently picks no module that
imports the resolver. Pinning a value it does not need would be cargo cult; if
its selection ever widens, it fails loudly and honestly and this docstring is
the pointer.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CI = _REPO / ".github" / "workflows" / "ci.yml"

# The shape of the token that used to be tracked, and of any real one minted by
# the documented rotation procedure: 32 hex characters.
_REAL_TOKEN_SHAPE = re.compile(r"\A[0-9a-fA-F]{32}\Z")


def _yaml():
    return pytest.importorskip("yaml", reason="PyYAML absent - see pyyaml in CI installs")


def _ci_doc() -> dict:
    return _yaml().safe_load(_CI.read_text(encoding="utf-8"))


def _declared_vision_tokens() -> dict[str, str]:
    """Every RC_VISION_TOKEN visible to a job in ci.yml, keyed by where it came
    from. Workflow-level `env` covers every job, so one entry there is enough."""
    doc = _ci_doc()
    found: dict[str, str] = {}
    top = (doc.get("env") or {}).get("RC_VISION_TOKEN")
    if top is not None:
        found["workflow"] = str(top)
    for job_name, job in (doc.get("jobs") or {}).items():
        val = ((job or {}).get("env") or {}).get("RC_VISION_TOKEN")
        if val is not None:
            found[f"job:{job_name}"] = str(val)
    return found


def test_ci_supplies_a_vision_token_to_every_job():
    """Without this the whole tests/ tree errors at import, not at assert."""
    found = _declared_vision_tokens()
    assert found, (
        "ci.yml declares no RC_VISION_TOKEN. core/vision_token._resolve raises "
        "when neither the env var nor config/vision_token.txt is present, and "
        "the config file is gitignored, so the runner has neither: every module "
        "that imports the resolver errors at COLLECTION. Measured 2026-09-06 on "
        "f8323887e - 120 failed, 53 errors, all one cause.")
    assert "workflow" in found, (
        f"RC_VISION_TOKEN is declared per-job {sorted(found)} rather than at "
        f"workflow level. Both jobs run the same suite and both need it, so a "
        f"third job added later would inherit the outage. Declare it once under "
        f"the top-level `env:`.")


def test_the_ci_vision_token_is_not_a_real_one():
    """A real token in a tracked file is the state f8323887e removed."""
    for where, value in _declared_vision_tokens().items():
        assert value.strip(), f"{where}: RC_VISION_TOKEN is empty; _resolve treats that as absent"
        assert not _REAL_TOKEN_SHAPE.match(value.strip()), (
            f"{where}: RC_VISION_TOKEN is 32 hex characters, which is the shape "
            f"of a REAL vision token. f8323887e untracked exactly such a value; "
            f"do not re-commit one to satisfy CI. The token guards a loopback "
            f"listener that no runner starts - any obvious throwaway works, and "
            f"it should read as a throwaway to whoever opens the file next.")


def test_the_resolver_still_refuses_to_default_on_its_own():
    """The dummy belongs in CI config, NOT in core/vision_token.

    If someone ever "fixes" this by giving _resolve a built-in fallback, the
    loud-on-misconfiguration property dies for real deploys too - which is the
    2026-04-28 audit finding (proposal 1.7) that retired the previous hardcoded
    fallback. This asserts the resolver is still strict.
    """
    src = (_REPO / "core" / "vision_token.py").read_text(encoding="utf-8")
    assert "raise RuntimeError(" in src, (
        "core/vision_token._resolve no longer raises when unconfigured. A "
        "silent default authenticates every request with a known constant.")
