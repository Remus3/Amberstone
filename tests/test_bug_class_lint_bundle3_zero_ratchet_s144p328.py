"""S144-P-328 - a third bundle of bug-class ruff rules that are not in ``ruff.toml``, held at zero over the tracked ``.py``.

``ruff.toml`` selects only E, F, I, UP, B and BLE. The first two bundles (S144-P-319, S144-P-321) and the older
single-family ratchets already hold most of the stable bug-class codes at zero; this one adds the 19 stable codes that
measured zero on 2026-11-07 (``ruff check --isolated --target-version py39``, ruff 0.17.3, every tracked ``.py``) and
that no guard under ``tests/`` names yet:

- Scope and binding errors: PLE0117 (``nonlocal`` with no enclosing binding), PLE0118 (a name used before its
  ``global`` declaration), PLC0132 (a ``TypeVar`` whose string name differs from the variable it is assigned to).
- ``functools`` dispatch misuse: PLE1519 (``@singledispatch`` on a method, which dispatches on ``self``), PLE1520
  (``@singledispatchmethod`` on a plain function).
- Redundant lookups that hide a stale index: PLR1733 (``d[k]`` inside ``for k, v in d.items()``), PLR1736
  (``l[i]`` inside ``for i, v in enumerate(l)``).
- Type and pytest slips: RUF020 (``NoReturn | T``), RUF057 (``round`` of an ``int``), RUF061 (the non-context
  ``pytest.raises(Exc, fn, ...)`` form), RUF101 (a ``noqa`` naming a redirected rule code), PT003 (a ``scope=
  "function"`` that is the default), RUF063 (``A.__dict__["__annotations__"]``, which skips the annotation
  lookup rules of Python 3.10+), PT020 (the deprecated ``pytest.yield_fixture``), PT024 (``asyncio`` mark on a
  fixture), PT025 (``usefixtures`` mark on a fixture), PT026 (``usefixtures()`` with no argument).
- Security: S612 (``logging.config.listen``, which ``eval``s what it receives), S704 (``markupsafe.Markup`` built from
  an f-string or ``%`` / ``.format`` result).

Left out on purpose: PLE1141 / RUF056 / RUF065 / RUF069 (preview-only in this ruff, so selecting them has no effect),
RUF007 (only fires for a Python 3.10+ target, and this project targets 3.9). Each
rule carries a positive control below, so a rule a future ruff stops firing (or removes) fails loudly instead of
passing for nothing. The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding. Nothing is
grandfathered: fix a hit, never widen the list.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_PROBES = {
    "PLE0117": "def f():\n    def g():\n        nonlocal x\n    return g\n",
    "PLE0118": "def f():\n    print(x)\n    global x\n    x = 1\n",
    "PLC0132": "from typing import TypeVar\nT = TypeVar('U')\n",
    "PLE1519": ("from functools import singledispatch\n\n\nclass A:\n    @singledispatch\n"
                "    def f(self, a):\n        pass\n"),
    "PLE1520": "from functools import singledispatchmethod\n\n\n@singledispatchmethod\ndef f(a):\n    pass\n",
    "PLR1733": "d = {}\nfor k, v in d.items():\n    print(d[k])\n",
    "PLR1736": "l = []\nfor i, v in enumerate(l):\n    print(l[i])\n",
    "RUF020": "from typing import NoReturn\nx: NoReturn | int\n",
    "RUF057": "round(1)\n",
    "RUF061": "import pytest\n\n\ndef test_a():\n    pytest.raises(ValueError, int, 'x')\n",
    "RUF063": "class A:\n    pass\n\n\nA.__dict__['__annotations__']\n",
    "RUF101": "import os  # noqa: PLR1701\n",
    "PT003": "import pytest\n\n\n@pytest.fixture(scope='function')\ndef f():\n    pass\n",
    "PT020": "import pytest\n\n\n@pytest.yield_fixture\ndef f():\n    yield 1\n",
    "PT024": "import pytest\n\n\n@pytest.mark.asyncio()\n@pytest.fixture\nasync def f():\n    pass\n",
    "PT025": "import pytest\n\n\n@pytest.mark.usefixtures('a')\n@pytest.fixture\ndef f():\n    pass\n",
    "PT026": "import pytest\n\n\n@pytest.mark.usefixtures()\ndef test_a():\n    pass\n",
    "S612": "import logging.config\nlogging.config.listen(1)\n",
    "S704": "from markupsafe import Markup\nx = ''\nMarkup(f'<b>{x}</b>')\n",
}
_RULES = ",".join(_PROBES)


def _ruff(rules: str, args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", rules, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure (for instance a removed rule code).
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_no_tracked_py_trips_a_bug_class_rule():
    # The whole tree on one command line is too long for Windows: lint ".", keep the tracked files.
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 500, "the tracked-file walk returned almost nothing"
    found = _ruff(_RULES, [".", "--exclude", "data,logs,ops/runtime"])
    hits = []
    for d in found:
        try:
            rel = relative_posix(Path(d["filename"]).resolve())
        except ValueError:
            continue
        if rel in tracked:
            hits.append(f"{rel}:{d['location']['row']} {d['code']}")
    assert not hits, f"bug-class ruff rule hit (fix the site, do not widen the list): {sorted(hits)}"


@pytest.mark.parametrize("code", sorted(_PROBES))
def test_every_rule_in_the_bundle_fires_on_its_pattern(code):
    """A positive control per rule: a rule that silently stopped firing would pass the ratchet for nothing."""
    found = _ruff(code, ["--stdin-filename", "probe.py", "-"], stdin=_PROBES[code])
    assert code in {d["code"] for d in found}, (code, found)


def test_the_bundle_is_not_in_ruff_toml_select():
    """If ruff.toml ever selects one of these, this ratchet is redundant for it - say so instead of drifting."""
    text = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
    select = text.split("select = [", 1)[1].split("]", 1)[0]
    chosen = {line.split('"')[1] for line in select.splitlines() if '"' in line}
    overlap = sorted(c for c in _PROBES if any(c.startswith(s) for s in chosen))
    assert not overlap, f"ruff.toml already selects these bundle rules: {overlap}"


def test_the_bundle_does_not_repeat_a_rule_an_earlier_bundle_holds():
    """One owner per rule: a code already in bundle 1 or 2 would make two guards fail for one hit."""
    import re

    others = set()
    for name in ("test_bug_class_lint_bundle_zero_ratchet_s144p319.py",
                 "test_bug_class_lint_bundle2_zero_ratchet_s144p321.py"):
        text = (REPO_ROOT / "tests" / name).read_text(encoding="utf-8")
        others |= set(re.findall(r'"([A-Z]{1,4}[0-9]{3,4})"', text))
    assert not (set(_PROBES) & others), sorted(set(_PROBES) & others)
