"""The shipped Share/src suite must actually RUN for an external reviewer.

Nine mirrored test modules could not be IMPORTED inside the engine-only package:
eight pull in the host application's ``core.*`` wrappers at module level, and
``test_abilities_content_freshness.py`` reaches the host-only web asset
``web/data/champion_aliases.json`` through its extractor import. A pytest import
failure is a COLLECTION error, and a collection error aborts the entire session,
so the command the package README hands a reviewer
(``python -m pytest agents/daemon_slayer/tests -q`` from ``Share/src`` with
``PYTHONPATH=.``) ran ZERO of the ~9000 tests and exited ``Interrupted: 9 errors
during collection``. ``tools.ds_share_sync._is_host_dependent_test`` keeps them
out of the mirror.

Pinned by PROPERTY, not by a snapshot count. Generic guards carry the weight: a
static scan for ``core`` imports, a static scan for reads of a snapshot patch the
package does not ship, and an actual ``--collect-only`` run of the shipped
mirror. A NEW host-coupled test added to the engine therefore fails here rather
than silently re-breaking the package for the next reviewer.

RM-221 (2026-08-16) widened two of those guards after measuring what the package
actually did in a reviewer's hands - 58 failures and 5 errors on a clean copy,
73 if the copy was renamed - and both misses were the same shape, a guard whose
domain was narrower than its name:

* the ``core``-import scan anchored at column 0, on the reasoning that only an
  import-time failure aborts collection. True, and the wrong bar: five DEFERRED
  ``import core.daemon_slayer_client`` calls inside test bodies each produced a
  ``ModuleNotFoundError`` the reviewer had to read past. The scan is now
  indentation-agnostic.
* nothing checked the DATA side at all, so two modules pinned to the historical
  16.14.1 snapshot contributed 50 failures and 5 errors by themselves.

The named-list guards below stay: the rules do not cover every case (a host-tree
POPULATION scan cannot be told apart from a healthy tree walk statically), and a
name with a written reason is the honest way to carry those.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

from tools import ds_share_sync as sync

_TESTS_PREFIX = "agents/daemon_slayer/tests/"

# ``from core... import`` / ``import core...`` at ANY indentation. Column-0 fails
# collection and takes the whole session with it; an indented one fails only its
# own test - but the reviewer's measured result is what the package README
# promises, so both are defects. See the module docstring.
_CORE_IMPORT = re.compile(r"^[ \t]*(?:from|import)\s+core\b", re.MULTILINE)


def _mirrored_test_modules() -> dict[str, str]:
    """{relpath: decoded source} for every test .py in the generate set."""
    return {
        rel: data.decode("utf-8")
        for rel, data in sync._build_expected().items()
        if rel.startswith(_TESTS_PREFIX) and rel.endswith(".py")
    }


def test_named_host_dependent_modules_are_not_mirrored():
    """None of the named collection-aborting modules reach the package."""
    expected = sync._build_expected()
    leaked = [
        name for name in sorted(sync._HOST_DEPENDENT_TESTS)
        if f"{_TESTS_PREFIX}{name}" in expected
    ]
    assert not leaked, (
        "host-dependent test modules leaked into Share/src - the shipped suite "
        f"will abort at collection again: {leaked}"
    )


def test_no_mirrored_test_imports_the_host_core_package():
    """The generic invariant: nothing mirrored imports ``core.*``, ever.

    Stronger than the by-name list above - a newly added host-coupled test is
    caught here, at the property, instead of after the package ships broken.
    """
    offenders = sorted(
        rel for rel, src in _mirrored_test_modules().items()
        if _CORE_IMPORT.search(src)
    )
    assert not offenders, (
        "mirrored test modules import the host-only 'core' package and will "
        "raise ModuleNotFoundError inside Share/src; the ds_share_sync rule "
        f"should already have dropped them: {offenders}"
    )


def test_no_mirrored_test_reads_a_snapshot_the_package_does_not_ship():
    """The DATA-side invariant: nothing mirrored pins a historical patch.

    The mirror carries exactly one per-patch snapshot. A test pinned to an older
    one raises ``SnapshotNotFound`` or ``FileNotFoundError`` in the package while
    passing perfectly well in the repo, which is why this went unnoticed for as
    long as it did - 55 of the clean copy's 63 red results came from two such
    modules.
    """
    offenders = sorted(
        rel for rel, src in _mirrored_test_modules().items()
        if sync._reads_unshipped_snapshot(src)
    )
    assert not offenders, (
        "mirrored test modules resolve a data/daemon_slayer snapshot other than "
        f"the shipped {sync._PATCH}; they cannot pass inside the package: "
        f"{offenders}"
    )


def test_mirrored_reads_of_the_upstream_feeds_are_tolerant_of_their_absence():
    """``data/meta`` and ``data/meta_build`` are not vendored - reads must skip.

    Unlike the two rules above this is a TRIPWIRE, not a proof. It finds the
    modules that build a path under an unshipped upstream feed and checks each
    one carries at least one tolerance idiom somewhere in its source; it cannot
    tell that the idiom guards THAT read. Its job is to make a new unguarded
    feed read impossible to add silently, so a human looks at it. Measured
    2026-08-16: five mirrored modules join such a path and all five are tolerant,
    so it starts green rather than being asserted into greenness.
    """
    import ast

    tolerance = ("_IS_SHARE_MIRROR", ".is_file()", ".exists()", "skipTest",
                 "SkipTest", "glob(")

    def joins_an_unshipped_feed(source: str) -> bool:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        consts = sync._module_str_constants(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                parts: list[str | None] = []
                sync._flatten_path_join(node, consts, parts)
                texts = [p for p in parts if p]
                if "data" in texts and (
                    "meta" in texts or "meta_build" in texts
                ):
                    return True
        return False

    offenders = sorted(
        rel for rel, src in _mirrored_test_modules().items()
        if joins_an_unshipped_feed(src)
        and not any(token in src for token in tolerance)
    )
    assert not offenders, (
        "mirrored test modules read data/meta or data/meta_build with no way to "
        "skip when it is absent; the package does not vendor either feed, so "
        f"these fail for every reviewer: {offenders}"
    )


def test_the_mirror_ships_the_sentinel_its_own_tests_key_on():
    """The host-artifact skips must not key on a directory NAME.

    Four mirrored guards (the engine CHANGELOG, data/meta, data/meta_build x2)
    legitimately skip inside the package. They discriminate on the SHARE_MIRROR
    file the generator emits, because the ancestor-directory-name check they used
    to carry turned 58 failures into 73 the moment a reviewer renamed the folder
    they unpacked into. Both halves are asserted: the sentinel ships, and it does
    NOT exist in the host repo (or every one of those guards would go dark here).
    """
    expected = sync._build_expected()
    assert sync._MIRROR_MARKER_REL in expected, (
        "the mirror no longer ships its SHARE_MIRROR sentinel - every "
        "host-artifact guard inside the package will fail instead of skipping"
    )
    assert not (sync._REPO / sync._MIRROR_MARKER_REL).exists(), (
        "the host repo now carries a SHARE_MIRROR sentinel, which silently "
        "disables the CHANGELOG / data/meta / data/meta_build guards in the "
        "main tree - exactly what keying on presence was meant to prevent"
    )
    keyed_on_it = sorted(
        rel for rel, src in _mirrored_test_modules().items()
        if sync._MIRROR_MARKER_REL in src
    )
    assert len(keyed_on_it) >= 4, (
        f"only {len(keyed_on_it)} mirrored guards key on the sentinel; the "
        "others have reverted to a name check: " + str(keyed_on_it)
    )
    stale = sorted(
        rel for rel, src in _mirrored_test_modules().items()
        if '"share" in (p.name.lower()' in src
    )
    assert not stale, (
        f"mirrored guards still discriminate on a directory NAME: {stale}"
    )


def test_shipped_mirror_collects_without_error():
    """End-to-end: the README's own command must not abort at collection.

    The guards above reason about the generate set; this one runs pytest the
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
    directory, which would also make the reviewer's command pass vacuously. The
    RM-221 rules made this load-bearing rather than decorative: a blunter
    stale-patch rule than the one shipped would have dropped eight healthy
    modules that merely MENTION an old patch.
    """
    mirrored = _mirrored_test_modules()
    assert len(mirrored) > 300, (
        f"the shipped test suite collapsed to {len(mirrored)} modules"
    )
    # Scoped to the tests dir, so engine source is untouched.
    assert "agents/daemon_slayer/rank.py" in sync._build_expected()
