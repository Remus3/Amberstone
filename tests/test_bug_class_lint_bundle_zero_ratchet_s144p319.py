"""S144-P-319 - a bundle of bug-class ruff rules that are not in ``ruff.toml``, held at zero over the tracked ``.py``.

``ruff.toml`` selects only E, F, I, UP, B and BLE, so every rule below is simply not looked at. Measured 2026-11-07
with ``ruff check --isolated --target-version py39`` (ruff 0.17.3) over every tracked ``.py``: zero findings for each
of them, so a NEW hit of any shape lands unseen. They are grouped by what they catch:

- Pylint warnings that are a real mistake, not style: PLW0120 (loop ``else`` with no ``break``), PLW0127 (a variable
  assigned to itself), PLW0129 (``assert`` on a non-empty string, always true), PLW0131 (a bare ``(x := 1)``), PLW0177
  (comparison to ``nan``), PLW0211 (a ``@staticmethod`` whose first argument is ``self``), PLW0245 (``super`` with no
  call), PLW0711 (``except A or B``), PLW1501 (an ``open`` mode that does not exist), PLW1508 (a non-string
  ``os.getenv`` default), PLW1509 (``preexec_fn``, unsafe with threads), PLW3301 (nested ``min`` / ``max``), PLC0414
  (``import x as x``), PLR1704 (a function argument redefined by a loop), PLR1722 (``exit()`` where ``sys.exit`` is the
  one that always exists).
- Duplicate or redundant syntax: PIE794 (a class field assigned twice), PIE796 (a duplicated ``Enum`` value), PIE800
  (``{**{...}}``), PIE804 (``f(**{"a": 1})``).
- Container and dataclass traps: RUF008 (a mutable ``dataclass`` default), RUF009 (a call-built ``dataclass`` default), RUF016 (a non-integer index), RUF024
  (``dict.fromkeys(keys, [])`` shares one list), RUF026 (``defaultdict(default_factory=...)`` is a key, not the
  factory), RUF028 (a malformed ``# fmt:`` suppression), RUF033 (a ``__post_init__`` default).
- Security and hygiene: S306 (``tempfile.mktemp``), S507 (an ``AutoAddPolicy`` host-key policy), S604 (``shell=True``
  on a non-subprocess call), S701 (Jinja2 ``autoescape=False``), S313 / S317 (a stdlib XML parser on untrusted
  input), T100 (``breakpoint()``), TRY002 (``raise Exception``), PGH004 (a blanket ``# noqa``), PGH005 (a mock call
  spelled as a bare attribute).

Rules left out on purpose: RUF018 / RUF030 (silent on every probe shape in this ruff, so a zero would be vacuous), S301 / S302 / S602 (pinned by the literal-call guard S144-P-316), and any preview-only rule. Each rule
carries a positive control below, so a rule a future ruff stops firing (or removes) fails loudly instead of passing
for nothing. The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding. Nothing is
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
    "PLW0120": "for x in []:\n    pass\nelse:\n    pass\n",
    "PLW0127": "def f():\n    a = 1\n    a = a\n    return a\n",
    "PLW0129": "assert 'x'\n",
    "PLW0131": "(a := 1)\n",
    "PLW0177": "def f(x):\n    return x == float('nan')\n",
    "PLW0211": "class A:\n    @staticmethod\n    def f(self):\n        pass\n",
    "PLW0245": "class A:\n    def __init__(self):\n        super.__init__()\n",
    "PLW0711": "try:\n    pass\nexcept ValueError or TypeError:\n    pass\n",
    "PLW1501": "open('f', 'rz')\n",
    "PLW1508": "import os\nos.getenv('X', 1)\n",
    "PLW1509": "import subprocess\nsubprocess.Popen(['a'], preexec_fn=print)\n",
    "PLW3301": "min(1, min(2, 3))\n",
    "PLC0414": "import os as os\n",
    "PLR1704": "def f(a):\n    for a in range(3):\n        pass\n",
    "PLR1722": "exit(1)\n",
    "PIE794": "class A:\n    x = 1\n    x = 2\n",
    "PIE796": "import enum\n\n\nclass E(enum.Enum):\n    A = 1\n    B = 1\n",
    "PIE800": "d = {**{'a': 1}}\n",
    "PIE804": "def f(**k):\n    pass\n\n\nf(**{'a': 1})\n",
    "RUF008": "from dataclasses import dataclass\n\n\n@dataclass\nclass A:\n    x: list = []\n",
    "RUF009": "from dataclasses import dataclass\n\n\n@dataclass\nclass A:\n    x: list = list()\n",
    "RUF016": "[1][1.5]\n",
    "RUF024": "d = dict.fromkeys(['a'], [])\n",
    "RUF026": "from collections import defaultdict\nd = defaultdict(default_factory=list)\n",
    "RUF028": "# fmt: skip\nx = 1\n",
    "RUF033": ("from dataclasses import dataclass\n\n\n@dataclass\nclass A:\n    x: int = 1\n\n"
               "    def __post_init__(self, y: int = 1):\n        pass\n"),
    "S306": "import tempfile\ntempfile.mktemp()\n",
    "S507": ("import paramiko\nc = paramiko.SSHClient()\n"
             "c.set_missing_host_key_policy(paramiko.AutoAddPolicy())\n"),
    "S604": "def f(x):\n    return x\n\n\nf(shell=True)\n",
    "S701": "import jinja2\njinja2.Environment(autoescape=False)\n",
    "S313": "from xml.etree.cElementTree import parse\nparse('f')\n",
    "S317": "import xml.sax\nxml.sax.make_parser()\n",
    "T100": "breakpoint()\n",
    "TRY002": "raise Exception('x')\n",
    "PGH004": "x = 1  # noqa\n",
    "PGH005": "m.assert_called_once\n",
}
_RULES = ",".join(_PROBES)


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
