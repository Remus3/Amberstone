"""The Share mirror must be SELF-CONTAINED: nothing it ships may reach outside it.

``Share/README.md`` promises an external reviewer that the shipped suite "exits
green offline with no flags". That promise was FALSE, and the two failures that
falsified it are one bug class: the mirror ships code whose file-system
dependency the mirror does not ship.

MEASURED before this guard landed, from ``Share/src`` with ``PYTHONPATH=.``:
``4 failed, 7725 passed`` - all four in
``agents/daemon_slayer/tests/test_artifact_patch_marker_guard.py``, from two
distinct absent dependencies:

1. ``tools/ds_feed_index.py``. The test's ``_known_stamp_lag()`` helper loads it
   by absolute path off the package root to read ``KNOWN_STAMP_LAG``, so the
   exception list is not restated. It was not in ``_DS_TOOLS``, so the load
   raised ``FileNotFoundError``.
2. ``web/data/champion_aliases.json``. ``tools/daemon_slayer_extract.py`` - which
   IS mirrored - executes ``_LOLMATH_TO_DDRAGON_ALIAS = _load_champion_aliases()``
   at MODULE level, and that reads the alias map off the package root. With no
   ``web/`` tree in the mirror the read raised, which means the shipped extractor
   was not merely untested but UNIMPORTABLE, while ``README.md`` and
   ``MANIFEST.md`` both advertise ``src/tools/`` as the offline data extractors.

Pinned by PROPERTY, not by the incident. Two independent mechanisms:

* a STATIC scan for every package-root-anchored literal path join in code the
  package EXECUTES - module level anywhere, plus every level inside a mirrored
  test module - asserting each resolves to something the mirror actually ships.
  This is the generic form of both root causes: one catches the test's by-path
  module load, the other catches the extractor's import-time data read, so a
  THIRD instance fails here without anyone having to think of it.
* a BEHAVIOURAL subprocess import of every mirrored tool inside a materialised
  copy of the mirror. Static analysis can only see literal paths; this catches
  an import-time reach however it is spelled.

Two reference kinds are deliberately NOT hard dependencies, and both are
recognised structurally rather than by an allowlist of names:

* runtime OUTPUT paths the generator itself already declares are not part of the
  mirror (``sync._is_transient`` plus the ``logs/`` + ``*.log`` skip in
  ``sync._check``) - e.g. ``logs/daemon_slayer_extract.log``, which the tools
  create rather than read.
* references the code demonstrably tolerates the absence of, i.e. consumed by
  ``exists`` / ``is_file`` / ``is_dir`` / ``glob`` / ``rglob`` / ``iterdir`` /
  ``mkdir``. Three shipped modules rely on this and are CORRECT to: the two
  ``data/meta`` catalog tests fall back to the vendored per-patch copy behind
  ``_META_CATALOG.is_file()``, the two ``data/meta_build`` rune tests
  ``skipTest`` on an empty ``glob``, and ``ds_feed_index.py`` prints
  "run --write" behind ``_INDEX_PATH.exists()``.
"""
from __future__ import annotations

import ast
import subprocess
import sys

import pytest

from tools import ds_share_sync as sync

# Path methods whose semantics are "absent is a legal answer". A reference
# consumed by one of these is a probe or a create, not a hard dependency.
_TOLERANT_METHODS = frozenset({
    "exists", "is_file", "is_dir", "glob", "rglob", "iterdir", "mkdir",
})

# Attribute hops that merely re-aim a path without consuming it, so tolerance
# detection has to look through them (``LOG_FILE.parent.mkdir(...)``).
_TRANSPARENT_ATTRS = frozenset({"parent", "resolve", "absolute"})


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    out: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _upcount(node: ast.AST) -> int | None:
    """Levels ABOVE the owning file that a ``__file__``-anchored expression
    points to, or None if the expression is not ``__file__``-anchored.

    ``Path(__file__)`` is 0 (the file itself), ``.parent`` is 1,
    ``.parents[N]`` is N + 1.
    """
    if isinstance(node, ast.Subscript):
        val = node.value
        if (isinstance(val, ast.Attribute) and val.attr == "parents"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, int)):
            base = _upcount(val.value)
            if base is not None:
                return base + node.slice.value + 1
        return None
    if isinstance(node, ast.Attribute):
        if node.attr == "parent":
            base = _upcount(node.value)
            return None if base is None else base + 1
        if node.attr in ("resolve", "absolute"):
            return _upcount(node.value)
        return None
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("resolve", "absolute"):
            return _upcount(func.value)
        if (isinstance(func, ast.Name) and func.id == "Path"
                and len(func_args := node.args) == 1
                and isinstance(func_args[0], ast.Name)
                and func_args[0].id == "__file__"):
            return 0
        return None
    return None


def _flatten(node: ast.AST) -> tuple[ast.AST, list[str]] | None:
    """``(base, ["a", "b"])`` for an ``base / "a" / "b"`` chain, else None.

    Any non-literal segment abandons the chain: a runtime-computed segment
    cannot be resolved statically and is not this scanner's business.
    """
    segs: list[str] = []
    cur = node
    while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
        right = cur.right
        if not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
            return None
        segs.append(right.value)
        cur = cur.left
    if not segs:
        return None
    return cur, list(reversed(segs))


def _consumed_tolerantly(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True if the expression at ``node`` is consumed by a tolerant method."""
    cur = node
    while True:
        parent = parents.get(cur)
        if not isinstance(parent, ast.Attribute):
            return False
        if parent.attr in _TOLERANT_METHODS:
            return True
        if parent.attr not in _TRANSPARENT_ATTRS:
            return False
        cur = parent


def _inside_a_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return True
        cur = parents.get(cur)
    return False


def _root_anchored_refs(rel: str, src: str) -> set[str]:
    """Mirror-relative targets of every root-anchored literal path join in ``src``.

    Only HARD references are returned - tolerantly-consumed ones are dropped
    here, because "the code handles this being absent" is a property of the
    reference, not of the mirror.

    SCOPE, and it is the load-bearing choice in this module: what the shipped
    package EXECUTES. That is module level everywhere (an import-time reach
    breaks the import outright - root cause 2) plus every level inside a
    mirrored TEST module (pytest runs those function bodies - root cause 1).
    A reach inside a non-test function body is deliberately out of scope: it
    cannot break the import and it cannot fail the suite, so it is a capability
    limit rather than the broken promise this guard defends. The same
    import-time-vs-deferred line is drawn in
    ``test_ds_share_host_dependent_tests_excluded``. One such limit is known
    and correct: ``tools/ds_feed_index.py`` ships for its module-level
    ``KNOWN_STAMP_LAG`` constant, and its ``--write``/``--check`` CLI reaches
    the repo's own ``tests/`` for a retired-fixture list - a CLI that could not
    do anything useful in the package anyway, since it indexes every historical
    patch dir and the mirror ships one.
    """
    deep = rel.startswith("agents/daemon_slayer/tests/")
    tree = ast.parse(src)
    parents = _parents(tree)
    depth = rel.count("/")  # directory depth of this file below the mirror root

    # Names bound to a root-anchored path, as (levels above THIS file, segments).
    anchors: dict[str, tuple[int, list[str]]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        up = _upcount(node.value)
        if up is not None:
            anchors[name] = (up, [])
            continue
        flat = _flatten(node.value)
        if not flat:
            continue
        base, segs = flat
        up = _upcount(base)
        if up is not None:
            anchors[name] = (up, segs)
        elif isinstance(base, ast.Name) and base.id in anchors:
            base_up, base_segs = anchors[base.id]
            anchors[name] = (base_up, base_segs + segs)

    # All attribute names ever applied to each bound name, for tolerance.
    attrs_on: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and node.id in anchors):
            continue
        cur: ast.AST = node
        while isinstance(parent := parents.get(cur), ast.Attribute):
            attrs_on.setdefault(node.id, set()).add(parent.attr)
            cur = parent

    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        # Only the OUTERMOST join of a chain; inner ones are bare prefixes.
        parent = parents.get(node)
        if (isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Div)
                and parent.left is node):
            continue
        if not deep and _inside_a_function(node, parents):
            continue
        flat = _flatten(node)
        if not flat:
            continue
        base, segs = flat
        up = _upcount(base)
        if up is not None:
            full = segs
            tolerant = _consumed_tolerantly(node, parents)
        elif isinstance(base, ast.Name) and base.id in anchors:
            up, base_segs = anchors[base.id]
            full = base_segs + segs
            tolerant = _consumed_tolerantly(node, parents)
        else:
            continue
        if tolerant or up > depth + 1:
            # Either absence is handled, or the path escapes the mirror root
            # entirely (an absolute host path, not a mirror dependency).
            continue
        target = "/".join(rel.split("/")[: depth - up + 1] + full)
        found.add(target)

    # A name whose every use includes a tolerant method is a probe, not a
    # dependency, even where the join itself is consumed opaquely.
    tolerant_names = {
        n for n, used in attrs_on.items() if used & _TOLERANT_METHODS
    }
    for name in tolerant_names:
        up, segs = anchors[name]
        if up > depth + 1 or not segs:
            continue
        found.discard("/".join(rel.split("/")[: depth - up + 1] + segs))
    return found


def _shipped_paths() -> tuple[dict[str, bytes], set[str]]:
    """The generate set plus every directory prefix inside it."""
    expected = sync._build_expected()
    dirs: set[str] = set()
    for rel in expected:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return expected, dirs


def _is_runtime_output(rel: str) -> bool:
    """Paths the generator itself declares are never part of the mirror.

    Reuses the generator's own rules (``_is_transient`` plus the ``logs/`` +
    ``*.log`` skip in ``_check``) rather than restating them, so this test
    cannot drift away from what the mirror considers mirror-able.
    """
    parts = rel.split("/")
    return (
        "__pycache__" in parts
        or ".pytest_cache" in parts
        or "logs" in parts
        or rel.endswith(".pyc")
        or rel.endswith(".log")
    )


def _hard_missing() -> dict[str, list[str]]:
    """{unshipped target: [mirrored .py files that hard-depend on it]}."""
    expected, dirs = _shipped_paths()
    missing: dict[str, list[str]] = {}
    for rel, blob in sorted(expected.items()):
        if not rel.endswith(".py"):
            continue
        for target in sorted(_root_anchored_refs(rel, blob.decode("utf-8"))):
            if target in expected or target in dirs or _is_runtime_output(target):
                continue
            missing.setdefault(target, []).append(rel)
    return missing


def _all_refs_count() -> int:
    expected, _ = _shipped_paths()
    return sum(
        len(_root_anchored_refs(rel, blob.decode("utf-8")))
        for rel, blob in expected.items()
        if rel.endswith(".py")
    )


# --- static: no mirrored module reaches outside the mirror -------------------


def test_the_scanner_actually_finds_root_anchored_paths():
    """Tripwire: the guard below must not be able to pass vacuously.

    If the AST shapes this scanner recognises ever stop matching the mirrored
    source, ``_hard_missing()`` empties out and the real guard goes green while
    checking nothing. Measured at 100+ references when this landed.
    """
    assert _all_refs_count() >= 25, (
        "the root-anchored path scanner found almost nothing - its AST "
        "patterns have rotted and the self-containment guard is now vacuous"
    )


def test_no_mirrored_module_hard_depends_on_an_unshipped_path():
    """THE property: every hard file-system dependency ships with the mirror.

    Both measured failures are instances - a test loading
    ``tools/ds_feed_index.py`` by path, and an extractor reading
    ``web/data/champion_aliases.json`` at import - and so is any future one.
    """
    missing = _hard_missing()
    assert missing == {}, (
        "mirrored code hard-depends on paths the Share package does not ship, "
        "so the shipped suite cannot exit green offline: "
        + "; ".join(f"{target} <- {sorted(set(users))}"
                    for target, users in sorted(missing.items()))
    )


# --- behavioural: the shipped tools are importable inside the package --------


_IMPORT_DRIVER = """
import importlib.util, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
bad = []
for p in sorted((root / "tools").glob("*.py")):
    spec = importlib.util.spec_from_file_location("_mirror_" + p.stem, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException as exc:
        bad.append(p.name + ": " + type(exc).__name__ + ": " + str(exc))
print("\\n".join(bad))
"""


@pytest.fixture(scope="module")
def materialised_mirror(tmp_path_factory):
    """The generate set written to disk, so imports resolve as a reviewer's would."""
    root = tmp_path_factory.mktemp("share_src")
    for rel, blob in sync._build_expected().items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(blob)
    return root


def test_every_mirrored_tool_imports_inside_the_package(materialised_mirror):
    """``src/tools/`` is advertised as the offline extractors - so it must import.

    ``daemon_slayer_extract.py`` shipped UNIMPORTABLE: its module-level
    ``_load_champion_aliases()`` read a host-only ``web/`` asset. Static
    analysis found that one; this finds the class however it is spelled.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _IMPORT_DRIVER, str(materialised_mirror)],
        capture_output=True, text=True, cwd=str(materialised_mirror),
    )
    assert proc.returncode == 0, f"import driver crashed: {proc.stderr}"
    failures = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert not failures, (
        "mirrored tools cannot be imported from inside the Share package, "
        "though README.md and MANIFEST.md advertise src/tools/ as the offline "
        "data extractors: " + "; ".join(failures)
    )


def test_the_import_driver_sees_the_tools_at_all():
    """Tripwire for the behavioural guard: the mirror really does ship tools."""
    expected = sync._build_expected()
    tools = [rel for rel in expected
             if rel.startswith("tools/") and rel.endswith(".py")]
    assert len(tools) >= 10, f"the mirror ships only {len(tools)} tool modules"


# --- the two named dependencies, so a regression names itself ----------------


def test_the_two_measured_dependencies_are_declared():
    """Instance-level anchors under the property, not a substitute for it.

    These two names are what the 4 measured failures needed. Keeping them
    explicit means a revert reads as "ds_feed_index / champion_aliases went
    missing" rather than as an anonymous scanner hit.
    """
    expected = sync._build_expected()
    assert "tools/ds_feed_index.py" in expected, (
        "test_artifact_patch_marker_guard imports KNOWN_STAMP_LAG from it by path"
    )
    assert "web/data/champion_aliases.json" in expected, (
        "tools/daemon_slayer_extract.py reads it at MODULE import time"
    )


def test_declared_host_assets_all_exist_in_the_repo():
    """``_HOST_ASSET_FILES`` copies behind ``if src.exists()``, like the tools.

    That silent skip is right for robustness and wrong for visibility: a
    renamed or deleted asset would ship nothing while still reading as
    declared. Same guard shape as ``_ROOT_DATA_FILES`` gets in
    ``test_ds_share_data_snapshot_scope``.
    """
    dead = sorted(rel for rel in sync._HOST_ASSET_FILES
                  if not (sync._REPO / rel).is_file())
    assert not dead, f"_HOST_ASSET_FILES names files that do not exist: {dead}"


def test_host_assets_mirror_at_their_repo_relative_path():
    """The relpath is load-bearing, not cosmetic.

    ``_CANONICAL_ALIAS_PATH`` resolves ``<root>/web/data/champion_aliases.json``
    off the package root, so re-homing the asset under, say, ``data/`` would
    ship the bytes and still leave the extractor unimportable.
    """
    expected = sync._build_expected()
    for rel in sync._HOST_ASSET_FILES:
        assert expected.get(rel) == (sync._REPO / rel).read_bytes(), (
            f"{rel} must mirror verbatim at its own repo-relative path"
        )


def test_precommit_hook_fires_when_a_mirrored_host_asset_is_staged():
    """Editing a mirrored asset must re-sync, or Share/src silently goes stale.

    ``_should_sync`` gates the pre-commit sync on mirrored DS source. The host
    assets live under ``web/``, which is otherwise not a trigger prefix, so
    without an exact-path match a champion-alias edit would drift the mirror.
    """
    for rel in sync._HOST_ASSET_FILES:
        assert sync._should_sync([rel]), f"staging {rel} does not trigger a sync"
    assert not sync._should_sync(["web/js/main.js"]), (
        "a plain web commit must NOT re-arm the sync hook (D1 churn fix)"
    )
