"""S144-P-330 - a fifth bundle of ruff rules that are not in ``ruff.toml``, held at zero over the tracked ``.py``.

``ruff.toml`` selects only E, F, I, UP, B and BLE. Bundles 1-4 (S144-P-319, -321, -328, -329) and the older
single-family ratchets hold the bug-class codes of other families at zero; this one adds 68 codes that measured zero on
2026-11-07 (``ruff check --isolated --target-version py39``, every tracked ``.py``, ruff 0.17.3) and that no file
under ``tests/`` or ``tools/`` names yet. They are the "the code says it twice" and "the code is a latent trap" rules
that the repo already satisfies, so a regression is a real new defect and not churn:

- Comprehension shapes (C4): C403 / C404 (a list comprehension wrapped in ``set`` / ``dict``), C406 (``dict`` of a
  list literal), C409 / C410 (``tuple`` / ``list`` of a literal), C411 (``list`` of a comprehension), C413 (``list``
  around ``sorted``), C415 (a reversed subscript inside ``set`` / ``sorted``), C417 (``map`` with a ``lambda``), C418
  (``dict`` of a dict literal), C419 (a list comprehension inside ``any`` / ``all``).
- Simplify (SIM): SIM113 (a hand-kept loop counter), SIM116 (an if/elif chain that is a dict lookup), SIM202 / SIM208
  (``not a != b`` / ``not (not a)``), SIM210 / SIM211 (``True if a else False`` and its mirror), SIM401 (an
  ``if k in d`` that is ``d.get``), SIM911 (``zip(d.keys(), d.values())``).
- Return flow: RET506 (an ``else`` after ``raise``).
- Refurb: FURB116 (``bin(n)[2:]``), FURB129 (``for x in f.readlines()``), FURB163 (``math.log(x, 2)``), FURB164
  (``Fraction.from_float``), FURB166 (``int(s[2:], 16)``), FURB177 (``Path().resolve()``), FURB181 (``md5().digest()``
  then ``.hex()``), FURB187 (``a = a[::-1]``).
- Pylint: PLC1802 (``if len(x):``), PLR1716 (``a < b and b < c``), PLR2044 (an empty ``#`` comment), PLE0115 (a name
  declared both ``global`` and ``nonlocal``), PLE1142 (``await`` in a plain ``def``), PLE2514 (a NUL in the source).
- Pycodestyle outside the selected ``E`` family: W191 (tab indentation), W605 (an invalid escape sequence).
- Ruff-specific: RUF032 (``Decimal(0.5)``), RUF037 (``deque([])``), RUF041 (``Literal[Literal[..]]``), RUF048
  (``tuple(map(int, __version__.split(".")))``), RUF049 (a dataclass that is an ``Enum``), RUF058 (``starmap`` over
  ``zip``), RUF071 (``os.path.commonprefix``, which compares characters and not path parts).
- Pathlib / pytest: PTH203 / PTH205 (``os.path.getatime`` / ``getctime``), PTH206 (``str.split(os.sep)``), PTH210 (a
  ``with_suffix`` argument with no dot), PT016 (``pytest.fail()`` with no message), PT023 (parentheses on a bare
  mark), PT031 (several statements inside ``pytest.warns``).
- Security (S): S113 (``requests`` call with no timeout), S201 (``debug=True`` on a Flask app), S312 (``telnetlib``),
  S318 / S319 (``minidom`` / ``pulldom`` parsing), S321 (``ftplib``), S503 / S504 (an SSLv2 default / ``wrap_socket``),
  S606 (``os.exec*`` with no shell), S609 (a wildcard in a ``chmod`` / ``chown`` command).
- Naming and typing: A006 (a lambda argument that shadows a builtin), N804 (a ``classmethod`` whose first argument is
  not ``cls``), N807 (a ``__name__`` style function), TC005 (an empty ``TYPE_CHECKING`` block), TC006 (``cast`` with
  an unquoted type), DTZ901 (``datetime.min`` / ``max``), Q002 (single-quoted docstring), T203 (``pprint``).

Left out on purpose: the rules that need configuration (ICN003, I002, TID251), that look at file modes (EXE001 /
EXE002, which differ on Windows), that depend on the target version (FURB161 needs py310, FURB162 py311), and the
pydocstyle / flake8-pyi / Django / pandas families, which the repo does not use. Each rule below carries a positive
control, so a rule a future ruff stops firing (or removes) fails loudly instead of passing for nothing. The run
uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding. Nothing is grandfathered: fix a hit,
never widen the list.
"""
from __future__ import annotations

import importlib.util
import json
import re
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
    "C403": "set([x for x in [1]])\n",
    "C404": "dict([(x, 1) for x in [1]])\n",
    "C406": "dict([(1, 2)])\n",
    "C409": "tuple([1, 2])\n",
    "C410": "list([1, 2])\n",
    "C411": "list([x for x in [1]])\n",
    "C413": "list(sorted([3, 1]))\n",
    "C415": "set([1, 2][::-1])\n",
    "C417": "list(map(lambda x: x, [1]))\n",
    "C418": "dict({'a': 1})\n",
    "C419": "any([x for x in [1]])\n",
    "SIM113": "i = 0\nfor x in [1]:\n    i += 1\n    print(x, i)\n",
    "SIM116": "def f(x):\n    if x == 1:\n        return 'a'\n    elif x == 2:\n        return 'b'\n"
             "    elif x == 3:\n        return 'c'\n    else:\n        return 'd'\n",
    "SIM202": "a = b = 1\nif not a != b:\n    pass\n",
    "SIM208": "a = 1\nif not (not a):\n    pass\n",
    "SIM210": "a = 1\nb = True if a else False\n",
    "SIM211": "a = 1\nb = False if a else True\n",
    "SIM401": "d = {}\nk = 1\nif k in d:\n    v = d[k]\nelse:\n    v = 1\n",
    "SIM911": "d = {}\nzip(d.keys(), d.values())\n",
    "RET506": "def f(a):\n    if a:\n        raise ValueError\n    else:\n        return 1\n",
    "FURB116": "bin(5)[2:]\n",
    "FURB129": "f = open('x')\nfor line in f.readlines():\n    pass\n",
    "FURB163": "import math\nmath.log(5, 2)\n",
    "FURB164": "from fractions import Fraction\nFraction.from_float(1.0)\n",
    "FURB166": "s = '0x1'\nint(s[2:], 16)\n",
    "FURB177": "from pathlib import Path\nPath().resolve()\n",
    "FURB181": "import hashlib\nhashlib.md5().digest().hex()\n",
    "FURB187": "a = [1]\na = a[::-1]\n",
    "PLC1802": "x = [1]\nif len(x):\n    pass\n",
    "PLR1716": "a = b = c = 1\nif a < b and b < c:\n    pass\n",
    "PLR2044": "#\nx = 1\n",
    "PLE0115": "def f():\n    x = 1\n\n    def g():\n        global x\n        nonlocal x\n",
    "PLE1142": "def f():\n    await g()\n",
    "PLE2514": "x = '\x00'\n",
    "W191": "if 1:\n\tpass\n",
    "W605": "x = '\\d'\n",
    "RUF032": "from decimal import Decimal\nDecimal(0.5)\n",
    "RUF037": "from collections import deque\ndeque([])\n",
    "RUF041": "from typing import Literal\nx: Literal[Literal[1]]\n",
    "RUF048": "__version__ = '1.0'\ntuple(map(int, __version__.split('.')))\n",
    "RUF049": "from dataclasses import dataclass\nfrom enum import Enum\n\n\n@dataclass\nclass E(Enum):\n    A = 1\n",
    "RUF058": "from itertools import starmap\nstarmap(print, zip([1], [2]))\n",
    "RUF071": "import os\nos.path.commonprefix(['a', 'b'])\n",
    "PTH203": "import os\nos.path.getatime('x')\n",
    "PTH205": "import os\nos.path.getctime('x')\n",
    "PTH206": "import os\n'a/b'.split(os.sep)\n",
    "PTH210": "from pathlib import Path\nPath('x').with_suffix('py')\n",
    "PT016": "import pytest\n\n\ndef test_x():\n    pytest.fail()\n",
    "PT023": "import pytest\n\n\n@pytest.mark.foo()\ndef test_x():\n    pass\n",
    "PT031": "import pytest\n\n\ndef test_x():\n    with pytest.warns(UserWarning):\n        a = 1\n        b = 2\n",
    "S113": "import requests\nrequests.get('x')\n",
    "S201": "from flask import Flask\napp = Flask('x')\napp.run(debug=True)\n",
    "S312": "import telnetlib\ntelnetlib.Telnet('x')\n",
    "S318": "from xml.dom import minidom\nminidom.parseString('x')\n",
    "S319": "from xml.dom import pulldom\npulldom.parse('x')\n",
    "S321": "import ftplib\nftplib.FTP('x')\n",
    "S503": "import ssl\n\n\ndef f(protocol=ssl.PROTOCOL_SSLv2):\n    pass\n",
    "S504": "import ssl\nssl.wrap_socket()\n",
    "S606": "import os\nos.execv('/bin/ls', ['ls'])\n",
    "S609": "import os\nos.popen('chmod 777 *')\n",
    "DTZ901": "import datetime\ndatetime.datetime.min\n",
    "A006": "f = lambda list: 1\n",
    "N804": "class A:\n    @classmethod\n    def f(self):\n        pass\n",
    "N807": "def __foo__():\n    pass\n",
    "TC005": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    pass\n",
    "TC006": "from typing import cast\ncast(int, 1)\n",
    "Q002": "def f():\n    '''doc'''\n",
    "T203": "from pprint import pprint\npprint(1)\n",
}
_RULES = ",".join(_PROBES)
_EARLIER = (
    "test_bug_class_lint_bundle_zero_ratchet_s144p319.py",
    "test_bug_class_lint_bundle2_zero_ratchet_s144p321.py",
    "test_bug_class_lint_bundle3_zero_ratchet_s144p328.py",
    "test_bug_class_lint_bundle4_zero_ratchet_s144p329.py",
)


def _ruff(rules: str, args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", rules, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure (for instance a removed rule code).
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_no_tracked_py_trips_a_bundle_rule():
    # The whole tree on one command line is too long for Windows: lint ".", keep the tracked files.
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 500, "the tracked-file walk returned almost nothing"
    found = _ruff(_RULES, [".", "--exclude", "data,logs,ops/runtime,_scratch"])
    hits = []
    for d in found:
        try:
            rel = relative_posix(Path(d["filename"]).resolve())
        except ValueError:
            continue
        if rel in tracked:
            hits.append(f"{rel}:{d['location']['row']} {d['code']}")
    assert not hits, f"bundle ruff rule hit (fix the site, do not widen the list): {sorted(hits)}"


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

    # A selector covers a code only inside the SAME linter: ruff's "I" (isort) is not "INT" (gettext).
    def _linter(name: str) -> str:
        return re.match(r"[A-Z]+", name).group()

    overlap = sorted(c for c in _PROBES
                     if any(c.startswith(s) and _linter(c) == _linter(s) for s in chosen))
    assert not overlap, f"ruff.toml already selects these bundle rules: {overlap}"


def test_the_bundle_does_not_repeat_a_rule_an_earlier_bundle_holds():
    """One owner per rule: a code already in bundle 1, 2, 3 or 4 would make two guards fail for one hit."""
    others = set()
    for name in _EARLIER:
        text = (REPO_ROOT / "tests" / name).read_text(encoding="utf-8")
        others |= set(re.findall(r'"([A-Z]{1,6}[0-9]{3,4})"', text))
    assert others, "the earlier bundles named no rule code"
    assert not (set(_PROBES) & others), sorted(set(_PROBES) & others)
