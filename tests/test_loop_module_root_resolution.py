r"""No module under ops/loop may hardcode an absolute repo root.

MEASURED 2026-07-27, nightly CI run 30261946219: ops/loop/loop_controller.py
defaulted its config to the literal r"C:\Riot Commander\ops\loop\config.json".
That path resolves on exactly one host. Every other checkout - CI, a fresh
clone, a git worktree - took the not-found branch and ran with CFG = {}, and
nothing said so. The damage surfaced two suites away, as a platform-split test
failure, which is the expensive way to learn it.

The fix for that one line was easy. The reason this file exists is that it was
never one line: a sweep after the fix found ops/loop/done_sentinel.py and
ops/loop/claude_stub.py carrying the same literal, and strictly worse - no CFG
override and no fallback at all. A defect that appears in three modules is a
CLASS, and a class needs a machine guard or the fourth instance lands the week
after everyone stops looking.

Deliberately a source scan rather than an import-and-check. The point is to
fail on the LITERAL, before any resolution logic gets a chance to paper over
it, and to keep failing for a module that cannot be imported on the box the
suite happens to run on.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOOP_DIR = ROOT / "ops" / "loop"

# A Windows drive-letter root, in either slash direction. Narrow on purpose:
# a relative path is fine, and a POSIX absolute path never appears here - the
# thing being caught is "this string names a location on ONE machine".
_DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]")

# Names that denote WHERE THIS CHECKOUT IS. Those always have a __file__-relative
# answer, so a drive-letter literal is simply wrong for them.
#
# Scoped by name rather than by "any drive-letter string" after this guard's
# first run flagged ops/loop/adjudicator.py DEFAULT_CLAUDE_CMD, which is a
# different thing wearing the same shape: an EXTERNAL TOOL location. The Claude
# CLI really does live at an operator-specific path, there is no repo-relative
# answer for it, and adjudicator.py:188 already prefers a config value over the
# default. Widening this guard to cover it would force a fake fix. Out of scope,
# on purpose - if the CLI path ever needs to be portable that is its own change.
_LOCATION_NAMES = re.compile(r"(^|_)(ROOT|CTL|REPO|DIR|HOME)($|_)")


def _loop_modules() -> list[Path]:
    return sorted(p for p in LOOP_DIR.glob("*.py") if p.name != "__init__.py")


def test_the_loop_dir_is_where_we_think_it_is():
    """A scan that silently matches nothing is the failure mode this guard has.

    If ops/loop moves or is renamed, every parametrized case below vanishes and
    the file goes green while checking exactly nothing.
    """
    mods = _loop_modules()
    assert LOOP_DIR.is_dir(), f"{LOOP_DIR} is gone - this guard is scanning nothing"
    assert len(mods) >= 5, f"only {len(mods)} modules found under {LOOP_DIR}"
    names = {p.name for p in mods}
    for expected in ("loop_controller.py", "done_sentinel.py", "claude_stub.py"):
        assert expected in names, f"{expected} vanished from the scanned set"


@pytest.mark.parametrize("mod", _loop_modules(), ids=lambda p: p.name)
def test_no_module_level_absolute_repo_root(mod: Path):
    """Module-level string constants must not name a drive-letter location.

    Scoped to module level and to assignments, so the two legitimate uses
    survive: prose in a docstring or comment (ops/loop/executor.py documents the
    operator's invocation) and a runtime value read from config, which
    loop_controller._cfg_path already gates on is_absolute().
    """
    tree = ast.parse(mod.read_text(encoding="utf-8"), filename=str(mod))
    offenders = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not any(_LOCATION_NAMES.search(n.upper()) for n in names):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str) \
                and _DRIVE_ROOT_RE.match(value.value):
            offenders.append((node.lineno, names, value.value))
    assert not offenders, (
        f"{mod.name} hardcodes an absolute repo root at module level: {offenders}. "
        f"Resolve it from __file__ instead - a drive-letter literal is correct on "
        f"exactly one host and silently wrong everywhere else, including CI.")


@pytest.mark.parametrize("name", ["done_sentinel.py", "claude_stub.py", "loop_controller.py"])
def test_the_three_known_instances_resolve_from_file(name: str):
    """The specific regression, pinned by name.

    The generic scan above would also pass if someone deleted these modules or
    swapped the literal for a different machine-specific mechanism (an env var
    with a Legion default, say). These three are the measured instances, so they
    are asserted to use the resolution that actually works everywhere.
    """
    src = (LOOP_DIR / name).read_text(encoding="utf-8")
    assert "__file__" in src, f"{name} does not resolve anything from __file__"
    assert not _DRIVE_ROOT_RE.search(
        "\n".join(ln for ln in src.splitlines()
                  if ln.startswith(("ROOT", "CTL", "_CFG_ARG")))), \
        f"{name} still assigns a drive-letter path to a top-level location constant"
