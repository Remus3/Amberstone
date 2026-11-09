"""S144-P-332 - a sixth bundle of ruff rules that are not in ``ruff.toml``, held at zero over the tracked ``.py``.

``ruff.toml`` selects only E, F, I, UP, B and BLE. Bundles 1-5 (S144-P-319, -321, -328, -329, -330) and the older
single-family ratchets hold most stable codes at zero; this one adds 27 codes that measured zero on 2026-11-07
(``ruff check --isolated --target-version py39``, every tracked ``.py``, ruff 0.17.3) and that no file under ``tests/``
names yet:

- Module naming: A005 (a module file named like a standard-library module, which shadows it for every script run from
  that directory).
- Shebang hygiene: EXE003 (a shebang that is not a Python one in a ``.py``), EXE004 (leading whitespace before the
  shebang, so the kernel ignores it), EXE005 (a shebang that is not on line 1).
- Async blocking: ASYNC250 (``input()`` inside ``async def`` blocks the whole loop).
- Typing misuse: PLC0105 (a ``TypeVar`` whose variance does not match its name suffix), TC004 (a name imported under
  ``TYPE_CHECKING`` and used at runtime, which is a ``NameError`` at import), TC010 (a string annotation in a ``|``
  union, a ``TypeError`` at runtime).
- Names: N816 (mixedCase global), N817 (a CamelCase import aliased to an acronym), PLC2403 (a non-ASCII import alias).
- Control-flow shapes: RET507 / RET508 (an ``else`` after ``continue`` / ``break``).
- Suppression comments: RUF103 (an invalid ``ruff: disable`` suppression comment).
- Quoting and docstrings: Q004 (an unnecessary backslash escape in a string), D300 (``'''`` where ``\"\"\"`` is the
  convention), D419 (an empty docstring).
- Path APIs: PTH124 (the legacy ``py.path`` library).
- Framework misuse (no tracked file imports ``fastapi`` today, so these guard a future import of it): FAST001 (a
  redundant ``response_model``), FAST003 (a path parameter the handler never reads).
- Insecure-call families that the repo currently avoids: S305 (an ECB cipher mode), S315 / S316 (XML expat parsing of
  untrusted input), S505 (a weak crypto key size), S508 / S509 (insecure SNMP), S702 (a Mako template built from
  input).

Left out on purpose: the library-specific families PD, NPY, DJ, AIR and PYI, the config-dependent TID25x and W505, and
every code whose probe did not fire under ``--isolated`` or that ruff has removed (S303, S304, S308, S320, S410,
S601, S610, S611, PLR1706, ANN101, PGH001, PGH002, ASYNC212, PLC0131, RUF011, RUF035, RUF053, RUF104, TC007).
Each rule below carries a positive control, so a rule a future ruff stops firing (or removes) fails loudly instead of
passing for nothing. The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding. Nothing is
grandfathered: fix a hit, never widen the list.
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

# code -> (stdin filename, source). The filename matters for A005 only.
_PROBES: dict[str, tuple[str, str]] = {
    "A005": ("json.py", "x = 1\n"),
    "ASYNC250": ("probe.py", "async def f():\n    input('x')\n"),
    "EXE003": ("probe.py", "#!/bin/sh\nx = 1\n"),
    "EXE004": ("probe.py", " #!/usr/bin/env python\nx = 1\n"),
    "EXE005": ("probe.py", "x = 1\n#!/usr/bin/env python\n"),
    "PLC0105": ("probe.py", "from typing import TypeVar\nT = TypeVar('T', covariant=True)\n"),
    "PLC2403": ("probe.py", "import os as \u00e9\n"),
    "PTH124": ("probe.py", "import py\np = py.path.local('x')\n"),
    "Q004": ("probe.py", "x = '\\\"'\n"),
    "RET507": ("probe.py",
               "def f(xs):\n    for x in xs:\n        if x:\n            continue\n        else:\n"
               "            print(x)\n"),
    "RET508": ("probe.py",
               "def f(xs):\n    for x in xs:\n        if x:\n            break\n        else:\n"
               "            print(x)\n"),
    "RUF103": ("probe.py", "x = 1  # ruff: disable[F401]\n"),
    "N816": ("probe.py", "mixedCase = 1\n"),
    "N817": ("probe.py", "from collections import OrderedDict as OD\n"),
    "S305": ("probe.py",
             "from cryptography.hazmat.primitives.ciphers import modes\nmodes.ECB()\n"),
    "S315": ("probe.py", "import xml.sax.expatreader\nxml.sax.expatreader.create_parser()\n"),
    "S316": ("probe.py", "import xml.dom.expatbuilder\nxml.dom.expatbuilder.parse('x')\n"),
    "S505": ("probe.py",
             "from cryptography.hazmat.primitives.asymmetric import rsa\n"
             "rsa.generate_private_key(public_exponent=65537, key_size=512)\n"),
    "S508": ("probe.py", "from pysnmp.hlapi import CommunityData\nCommunityData('public', mpModel=0)\n"),
    "S509": ("probe.py", "from pysnmp.hlapi import UsmUserData\nUsmUserData('u', 'p')\n"),
    "S702": ("probe.py", "from mako.template import Template\nTemplate('x')\n"),
    "TC004": ("probe.py", "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import os\nos.getcwd()\n"),
    "TC010": ("probe.py", "x: 'int' | None = None\n"),
    "D300": ("probe.py", "def f():\n    '''x'''\n"),
    "D419": ("probe.py", "def f():\n    ''\n"),
    "FAST001": ("probe.py",
                "from fastapi import FastAPI\napp = FastAPI()\n\n\n@app.get('/', response_model=int)\n"
                "def f() -> int:\n    return 1\n"),
    "FAST003": ("probe.py",
                "from fastapi import FastAPI\napp = FastAPI()\n\n\n@app.get('/{x}')\ndef f():\n    return 1\n"),
}
_RULES = ",".join(_PROBES)
_EARLIER = (
    "test_bug_class_lint_bundle_zero_ratchet_s144p319.py",
    "test_bug_class_lint_bundle2_zero_ratchet_s144p321.py",
    "test_bug_class_lint_bundle3_zero_ratchet_s144p328.py",
    "test_bug_class_lint_bundle4_zero_ratchet_s144p329.py",
    "test_bug_class_lint_bundle5_zero_ratchet_s144p330.py",
)


def _ruff(rules: str, args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", rules, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure (for instance a removed rule code).
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_no_tracked_py_trips_a_bundle_rule():
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
    assert not hits, f"ruff rule hit (fix the site, do not widen the list): {sorted(hits)}"


@pytest.mark.parametrize("code", sorted(_PROBES))
def test_every_rule_in_the_bundle_fires_on_its_pattern(code):
    """A positive control per rule: a rule that silently stopped firing would pass the ratchet for nothing."""
    filename, source = _PROBES[code]
    found = _ruff(code, ["--stdin-filename", filename, "-"], stdin=source)
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
    """One owner per rule: a code already in bundles 1-5 would make two guards fail for one hit."""
    others = set()
    for name in _EARLIER:
        text = (REPO_ROOT / "tests" / name).read_text(encoding="utf-8")
        others |= set(re.findall(r'"([A-Z]{1,6}[0-9]{3,4})"', text))
    assert others, "the earlier bundles named no rule code"
    assert not (set(_PROBES) & others), sorted(set(_PROBES) & others)
