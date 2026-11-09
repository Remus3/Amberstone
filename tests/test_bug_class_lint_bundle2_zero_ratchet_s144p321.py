"""S144-P-321 - a second bundle of bug-class ruff rules that are not in ``ruff.toml``, held at zero over the tracked ``.py``.

Companion to the S144-P-319 bundle (``test_bug_class_lint_bundle_zero_ratchet_s144p319.py``): ``ruff.toml`` selects only
E, F, I, UP, B and BLE, so a rule outside those is simply not looked at. Measured 2026-11-07 with
``ruff check --isolated --target-version py39`` (ruff 0.17.3) over every tracked ``.py``: ``--select ALL`` reports
nothing for any rule below, and none of them appears in any other test, so a NEW hit of any shape lands unseen. By
what each catches:

- Pylint errors that raise or misbehave at run time: PLE0100 / PLE0101 (``yield`` / ``return`` value in ``__init__``),
  PLE0237 (an attribute outside ``__slots__``), PLE0241 (duplicate bases), PLE0302 and PLE0303 / 0304 / 0305 / 0308 /
  0309 (a dunder with the wrong signature or return type), PLE0604 / 0605 (a malformed ``__all__``), PLE0704 (a bare
  ``raise`` outside a handler), PLE1132 (a repeated keyword), PLE1205 / 1206 (a logging call with too many or too few
  arguments), PLE1300 / 1307 / 1310 (a bad ``%`` format character or type, a multi-character ``strip``), PLE1507 (a
  non-string ``getenv`` key), PLE1700 (``yield from`` in an async function), PLR0206 (a property with parameters),
  PLR1708 (``raise StopIteration`` in a generator).
- Statements that do nothing or never run: PLW0128 (``a, a = ...``), PLW0133 (``ValueError("x")`` with no ``raise``),
  PLW0604 (``global`` at module level), PLW0642 (assigning ``self``), PLW1507 (a shallow copy of ``os.environ``),
  PLW1641 (``__eq__`` with no ``__hash__``), PLW2101 (``with threading.Lock():``, which locks nothing), PLC0205 (a
  string ``__slots__``), RUF040 (an assert message that is a bare literal), RUF060 (``in`` an empty container), RUF064
  (``os.chmod(f, 755)``, a decimal read as an octal mode), RUF068 (a repeated ``__all__`` entry), COM818 (a trailing
  comma that makes a tuple), SIM101 / SIM107 / SIM220 / SIM221 (a duplicated ``isinstance``, a ``return`` in
  ``finally``, ``a and not a``, ``a or not a``), FURB132 / 168 / 169.
- Source-text traps: PLE2502 (a bidirectional control), PLE2510 / 2512 / 2513 / 2515 (a backspace, SUB, ESC or
  zero-width space in a literal), PLC2401 (a non-ASCII identifier), RUF001 / 002 / 003 (a look-alike letter in a
  string, docstring or comment). These sit beside the ASCII sweeps, which see a glyph but cannot say it is a
  homoglyph of a Latin letter.
- Logging and version checks: LOG002 / 004 / 007 / 015 (``getLogger(__file__)``, ``exception`` outside a handler, a
  ``exc_info=False`` beside ``exception``, a root-logger call), G003 / G010 (string concatenation in a logging call,
  ``warn``), YTT101 / 102 / 103 / 301 / 302 / 303 (``sys.version`` read as a string).
- Security and tests: S107 (a hard-coded password default), S202 (``tarfile.extractall``), S501 / S502 (a request with
  no certificate validation, an old SSL version), S506 (``yaml.load``), PT010 / PT014 / PT015 (``raises()`` with no
  exception, a duplicated parametrize case, ``assert False``).

Rules probed and left out because they do not fire in this ruff (a zero would be vacuous): PLE0116, PLE0643, SIM109,
SIM222, SIM223, TRY200. Each rule carries a positive control below, so a rule a future ruff stops firing (or removes)
fails loudly instead of passing for nothing. The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a
finding. Nothing is grandfathered: fix a hit, never widen the list.
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

# Source-text probes are built from code points so this file stays 7-bit ASCII.
_BIDI = chr(0x202E)
_BACKSPACE = chr(8)
_SUB = chr(0x1A)
_ESC = chr(0x1B)
_ZERO_WIDTH = chr(0x200B)
_CYRILLIC_A = chr(0x0430)

_PROBES = {
    "PLE0100": "class A:\n    def __init__(self):\n        yield 1\n",
    "PLE0101": "class A:\n    def __init__(self):\n        return 1\n",
    "PLE0237": "class A:\n    __slots__ = ('a',)\n\n    def __init__(self):\n        self.b = 1\n",
    "PLE0241": "class B:\n    pass\n\n\nclass A(B, B):\n    pass\n",
    "PLE0302": "class A:\n    def __bool__(self, x):\n        return True\n",
    "PLE0303": "class A:\n    def __len__(self):\n        return 'a'\n",
    "PLE0304": "class A:\n    def __bool__(self):\n        return 1\n",
    "PLE0305": "class A:\n    def __index__(self):\n        return 'a'\n",
    "PLE0308": "class A:\n    def __bytes__(self):\n        return 'a'\n",
    "PLE0309": "class A:\n    def __hash__(self):\n        return 'a'\n",
    "PLE0604": "__all__ = [1]\n",
    "PLE0605": "__all__ = 1\n",
    "PLE0704": "def f():\n    raise\n",
    "PLE1132": "def f(**k):\n    pass\n\n\nf(a=1, **{'a': 2})\n",
    "PLE1205": "import logging\nlogging.info('%s', 1, 2)\n",
    "PLE1206": "import logging\nlogging.info('%s %s', 1)\n",
    "PLE1300": "'%z' % 1\n",
    "PLE1307": "'%d' % 'a'\n",
    "PLE1310": "'abc'.strip('aa')\n",
    "PLE1507": "import os\nos.getenv(1)\n",
    "PLE1700": "async def f():\n    yield from []\n",
    "PLE2502": "x = '" + _BIDI + "'\n",
    "PLE2510": "x = '" + _BACKSPACE + "'\n",
    "PLE2512": "x = '" + _SUB + "'\n",
    "PLE2513": "x = '" + _ESC + "'\n",
    "PLE2515": "x = '" + _ZERO_WIDTH + "'\n",
    "PLR0206": "class A:\n    @property\n    def p(self, x):\n        return x\n",
    "PLR1708": "def f():\n    yield 1\n    raise StopIteration\n",
    "PLW0128": "a, a = 1, 2\n",
    "PLW0133": "ValueError('x')\n",
    "PLW0604": "global x\nx = 1\n",
    "PLW0642": "class A:\n    def f(self):\n        self = 1\n",
    "PLW1507": "import copy\nimport os\ncopy.copy(os.environ)\n",
    "PLW1641": "class A:\n    def __eq__(self, o):\n        return True\n",
    "PLW2101": "import threading\nwith threading.Lock():\n    pass\n",
    "PLC0205": "class A:\n    __slots__ = 'a'\n",
    "PLC2401": "x" + _CYRILLIC_A + " = 1\n",
    "RUF001": "x = '" + _CYRILLIC_A + "'\n",
    "RUF002": "def f():\n    '''" + _CYRILLIC_A + "'''\n",
    "RUF003": "# " + _CYRILLIC_A + "\nx = 1\n",
    "RUF040": "x = 1\nassert x, 1\n",
    "RUF060": "x = 1 in []\n",
    "RUF064": "import os\nos.chmod('f', 755)\n",
    "RUF068": "__all__ = ['a', 'a']\n",
    "S107": "def f(password='x'):\n    pass\n",
    "S202": "import tarfile\ntarfile.open('f').extractall()\n",
    "S501": "import requests\nrequests.get('u', verify=False)\n",
    "S502": "import ssl\nssl.wrap_socket(None, ssl_version=ssl.PROTOCOL_SSLv2)\n",
    "S506": "import yaml\nyaml.load('x')\n",
    "COM818": "x = 1,\n",
    "LOG002": "import logging\nlogging.getLogger(__file__)\n",
    "LOG004": "import logging\nlogging.exception('x')\n",
    "LOG007": "import logging\ntry:\n    pass\nexcept ValueError:\n    logging.exception('x', exc_info=False)\n",
    "LOG015": "import logging\nlogging.info('x')\n",
    "G003": "import logging\nlogger = logging.getLogger('a')\nlogger.info('a' + 'b')\n",
    "G010": "import logging\nlogger = logging.getLogger('a')\nlogger.warn('a')\n",
    "SIM101": "def f(a):\n    return isinstance(a, int) or isinstance(a, str)\n",
    "SIM107": "def f():\n    try:\n        return 1\n    finally:\n        return 2\n",
    "SIM220": "def f(a):\n    return a and not a\n",
    "SIM221": "def f(a):\n    return a or not a\n",
    "PT010": "import pytest\n\n\ndef test_a():\n    with pytest.raises():\n        pass\n",
    "PT014": "import pytest\n\n\n@pytest.mark.parametrize('x', [1, 1])\ndef test_a(x):\n    pass\n",
    "PT015": "def test_a():\n    assert False\n",
    "YTT101": "import sys\nsys.version[:3]\n",
    "YTT102": "import sys\nsys.version[2]\n",
    "YTT103": "import sys\nsys.version >= '3.5'\n",
    "YTT301": "import sys\nsys.version[0]\n",
    "YTT302": "import sys\nsys.version >= '3'\n",
    "YTT303": "import sys\nsys.version[:1]\n",
    "FURB132": "s = set()\nif 1 in s:\n    s.remove(1)\n",
    "FURB168": "isinstance(1, type(None))\n",
    "FURB169": "type(1) is type(None)\n",
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


def test_no_tracked_py_trips_a_second_bundle_bug_class_rule():
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
def test_every_rule_in_the_second_bundle_fires_on_its_pattern(code):
    """A positive control per rule: a rule that silently stopped firing would pass the ratchet for nothing."""
    found = _ruff(code, ["--stdin-filename", "probe.py", "-"], stdin=_PROBES[code])
    assert code in {d["code"] for d in found}, (code, found)


def test_the_second_bundle_is_not_in_ruff_toml_select():
    """If ruff.toml ever selects one of these, this ratchet is redundant for it - say so instead of drifting."""
    text = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
    select = text.split("select = [", 1)[1].split("]", 1)[0]
    chosen = {line.split('"')[1] for line in select.splitlines() if '"' in line}
    # A selector is a whole family ("F" is pyflakes, not FURB) or a full code ("F401").
    overlap = sorted(
        c for c in _PROBES
        if any(c == s or (s.isalpha() and re.match(r"[A-Z]+", c).group() == s) for s in chosen)
    )
    assert not overlap, f"ruff.toml already selects these bundle rules: {overlap}"


def test_the_second_bundle_does_not_repeat_the_first():
    """Two bundles that both hold a rule are two places to forget to update: keep the sets disjoint."""
    from tests.test_bug_class_lint_bundle_zero_ratchet_s144p319 import _PROBES as first

    assert not sorted(set(_PROBES) & set(first))
