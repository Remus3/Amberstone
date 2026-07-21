"""The shipped Share/src suite must actually RUN for an external reviewer.

Nine mirrored test modules could not be IMPORTED inside the engine-only package:
eight pull in the host application's ``core.*`` wrappers at module level, and
``test_abilities_content_freshness.py`` reaches the host-only web asset
``web/data/champion_aliases.json`` through its extractor import. A pytest import
failure is a COLLECTION error, and a collection error aborts the entire session,
so the command the package README hands a reviewer
(``python -m pytest agents/daemon_slayer/tests -q`` from ``Share/src`` with
``PYTHONPATH=.``) ran ZERO of the ~9000 tests and exited ``Interrupted: 9 errors
during collection``. ``tools.ds_share_sync._HOST_DEPENDENT_TESTS`` keeps them out
of the mirror.

Pinned by PROPERTY, not by a snapshot count. Two generic guards carry the weight:
a static scan for module-level ``core`` imports, and an actual ``--collect-only``
run of the shipped mirror. A NEW host-coupled test added to the engine therefore
fails here rather than silently re-breaking the package for the next reviewer.

Deferred (in-function) ``core`` imports are deliberately NOT covered: they raise
at run time, which pytest reports as a single test error and keeps going. Only an
import-time failure aborts collection, and only that class is the defect.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

from tools import ds_share_sync as sync

_TESTS_PREFIX = "agents/daemon_slayer/tests/"

# Column-0 ``from core... import`` / ``import core...`` - executed at import
# time, so it fails COLLECTION. Indentation is excluded on purpose (see the
# module docstring): a deferred import fails one test, not the whole session.
_CORE_IMPORT = re.compile(r"^(?:from|import)\s+core\b", re.MULTILINE)


def _mirrored_test_modules() -> dict[str, str]:
    """{relpath: decoded source} for every test .py in the generate set."""
    return {
        rel: data.decode("utf-8")
        for rel, data in sync._build_expected().items()
        if rel.startswith(_TESTS_PREFIX) and rel.endswith(".py")
    }


def test_named_host_dependent_modules_are_not_mirrored():
    """None of the nine collection-aborting modules reach the package."""
    expected = sync._build_expected()
    leaked = [
        name for name in sorted(sync._HOST_DEPENDENT_TESTS)
        if f"{_TESTS_PREFIX}{name}" in expected
    ]
    assert not leaked, (
        "host-dependent test modules leaked into Share/src - the shipped suite "
        f"will abort at collection again: {leaked}"
    )


def test_no_mirrored_test_imports_the_host_core_package_at_import_time():
    """The generic invariant: nothing mirrored imports ``core.*`` at module level.

    Stronger than the by-name list above - a newly added host-coupled test is
    caught here, at the property, instead of after the package ships broken.
    """
    offenders = sorted(
        rel for rel, src in _mirrored_test_modules().items()
        if _CORE_IMPORT.search(src)
    )
    assert not offenders, (
        "mirrored test modules import the host-only 'core' package at module "
        "level and will abort collection inside Share/src; add them to "
        f"ds_share_sync._HOST_DEPENDENT_TESTS: {offenders}"
    )


def test_shipped_mirror_collects_without_error():
    """End-to-end: the README's own command must not abort at collection.

    The two guards above reason about the generate set; this one runs pytest the
    way the external reviewer does, against the mirror on disk. It is the only
    check that would also catch a NON-``core`` import-time dependency (the way
    ``test_abilities_content_freshness.py`` failed - a host ``web/`` asset read
    through an extractor import, invisible to any import-name scan).

    Byte-code and cache writes are suppressed, so the run leaves no
    ``__pycache__``. It does still leave ``src/logs/`` behind: the extractor
    modules open their log file at import time, which is the same artifact a
    reviewer following the package README produces, and both paths are
    gitignored.
    """
    src = sync._SRC
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "agents/daemon_slayer/tests",
         "-q", "--collect-only", "-p", "no:cacheprovider"],
        cwd=str(src), env=env, capture_output=True, text=True,
    )
    assert "errors during collection" not in proc.stdout, (
        "the shipped package aborts at collection - an external reviewer gets "
        f"ZERO tests:\n{proc.stdout[-4000:]}"
    )
    assert proc.returncode == 0, (
        f"collect-only exited {proc.returncode}:\n{proc.stdout[-4000:]}"
    )


def test_exclusion_entries_all_exist_in_the_live_engine():
    """Every excluded name is a real live test file.

    A rename or deletion upstream would otherwise leave a dead entry that
    silently excludes nothing while reading as covered.
    """
    live = sync._REPO / "agents" / "daemon_slayer" / "tests"
    dead = [name for name in sorted(sync._HOST_DEPENDENT_TESTS)
            if not (live / name).is_file()]
    assert not dead, (
        f"_HOST_DEPENDENT_TESTS names files that no longer exist: {dead}"
    )


def test_exclusion_is_scoped_to_the_tests_directory():
    """The mirror still ships the engine suite - this is a surgical drop.

    Guards against an over-broad predicate quietly emptying the shipped tests
    directory, which would also make the reviewer's command pass vacuously.
    """
    mirrored = _mirrored_test_modules()
    assert len(mirrored) > 300, (
        f"the shipped test suite collapsed to {len(mirrored)} modules"
    )
    # Scoped to the tests dir, so engine source is untouched.
    assert "agents/daemon_slayer/rank.py" in sync._build_expected()
