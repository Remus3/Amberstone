"""S144-P-329 - a fourth bundle of bug-class ruff rules that are not in ``ruff.toml``, held at zero over the tracked ``.py``.

``ruff.toml`` selects only E, F, I, UP, B and BLE. Bundles 1-3 (S144-P-319, S144-P-321, S144-P-328) and the older
single-family ratchets hold most stable bug-class codes at zero; this one adds 31 codes that measured zero on
2026-11-07 (``ruff check --isolated --target-version py39``, every tracked ``.py``) and that no guard under ``tests/``
names yet:

- Logging misuse: G001 / G002 (a message built with ``str.format`` / ``%`` instead of lazy arguments), G101 (an
  ``extra=`` key that collides with a ``LogRecord`` attribute, which raises ``KeyError`` at log time), G201 / G202
  (``exc_info=True`` next to ``logging.error`` / ``logging.exception``), LOG009 (the undocumented ``logging.WARN``
  alias).
- Class layout: SLOT001 (``__slots__`` missing on a ``tuple`` subclass), SLOT002 (the same on a ``namedtuple`` one).
- Async blocking: ASYNC100 (a ``trio`` / ``anyio`` timeout scope with no checkpoint inside), ASYNC105 (an un-awaited
  ``trio`` call), ASYNC110 (a ``sleep`` loop that should wait on an event), ASYNC210 (a blocking HTTP call inside
  ``async def``), ASYNC222 (``os.wait*`` inside ``async def``), ASYNC230 (a blocking ``open`` inside ``async def``), ASYNC109 (a ``timeout`` parameter on an
  ``async def``, which should be a timeout scope), ASYNC115 (``sleep(0)``, which should be ``checkpoint``), ASYNC116
  (a ``sleep`` longer than a day), ASYNC220 / ASYNC221 (a ``subprocess`` call inside ``async def``).
- Version checks: YTT201 (``sys.version_info[0] == 3``), YTT202 (``six.PY3``), YTT203 (``sys.version_info[1]`` compared),
  YTT204 (``sys.version_info.minor``).
- Naive datetimes: DTZ002 (``datetime.today``), DTZ003 (``utcnow``), DTZ004 (``utcfromtimestamp``), DTZ012
  (``date.fromtimestamp``).
- i18n misuse: INT001 / INT002 / INT003 (an f-string, ``.format`` or ``%`` result passed to ``gettext``).
- A004: an import that shadows a Python builtin.

Left out on purpose: ICN002 (it needs configured banned import aliases, which ``--isolated`` removes, so it has no
positive control). Each rule below carries a positive
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
    "G001": "import logging\nlogging.info('a {}'.format(1))\n",
    "G002": "import logging\nlogging.info('a %s' % 1)\n",
    "G101": "import logging\nlogging.info('x', extra={'name': 1})\n",
    "G201": "import logging\ntry:\n    pass\nexcept Exception:\n    logging.error('x', exc_info=True)\n",
    "G202": "import logging\ntry:\n    pass\nexcept Exception:\n    logging.exception('x', exc_info=True)\n",
    "LOG009": "import logging\nlogging.WARN\n",
    "SLOT001": "class A(tuple):\n    pass\n",
    "SLOT002": "from collections import namedtuple\n\n\nclass A(namedtuple('A', 'x')):\n    pass\n",
    "ASYNC100": "import trio\n\n\nasync def f():\n    with trio.fail_after(1):\n        pass\n",
    "ASYNC105": "import trio\n\n\nasync def f():\n    trio.sleep(1)\n",
    "ASYNC109": "import trio\n\n\nasync def f(timeout=1):\n    pass\n",
    "ASYNC110": "import asyncio\n\n\nasync def f():\n    while True:\n        await asyncio.sleep(1)\n",
    "ASYNC115": "import trio\n\n\nasync def f():\n    await trio.sleep(0)\n",
    "ASYNC116": "import trio\n\n\nasync def f():\n    await trio.sleep(86401)\n",
    "ASYNC210": "import httpx\n\n\nasync def f():\n    httpx.get('x')\n",
    "ASYNC220": "import subprocess\n\n\nasync def f():\n    subprocess.Popen('x')\n",
    "ASYNC221": "import subprocess\n\n\nasync def f():\n    subprocess.run('x')\n",
    "ASYNC222": "import os\n\n\nasync def f():\n    os.waitpid(0, 0)\n",
    "ASYNC230": "async def f():\n    open('x')\n",
    "YTT201": "import sys\nsys.version_info[0] == 3\n",
    "YTT202": "from six import PY3\nPY3\n",
    "YTT203": "import sys\nsys.version_info[1] >= 5\n",
    "YTT204": "import sys\nsys.version_info.minor > 3\n",
    "DTZ002": "import datetime\ndatetime.datetime.today()\n",
    "DTZ003": "import datetime\ndatetime.datetime.utcnow()\n",
    "DTZ004": "import datetime\ndatetime.datetime.utcfromtimestamp(0)\n",
    "DTZ012": "import datetime\ndatetime.date.fromtimestamp(0)\n",
    "INT001": "import gettext\ngettext.gettext(f'a{1}')\n",
    "INT002": "import gettext\ngettext.gettext('a'.format(1))\n",
    "INT003": "import gettext\ngettext.gettext('a' % 1)\n",
    "A004": "from os import open\n",
}
_RULES = ",".join(_PROBES)
_EARLIER = (
    "test_bug_class_lint_bundle_zero_ratchet_s144p319.py",
    "test_bug_class_lint_bundle2_zero_ratchet_s144p321.py",
    "test_bug_class_lint_bundle3_zero_ratchet_s144p328.py",
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
    # A selector covers a code only inside the SAME linter: ruff's "I" (isort) is not "INT" (gettext).
    def _linter(name: str) -> str:
        return re.match(r"[A-Z]+", name).group()

    overlap = sorted(c for c in _PROBES
                     if any(c.startswith(s) and _linter(c) == _linter(s) for s in chosen))
    assert not overlap, f"ruff.toml already selects these bundle rules: {overlap}"


def test_the_bundle_does_not_repeat_a_rule_an_earlier_bundle_holds():
    """One owner per rule: a code already in bundle 1, 2 or 3 would make two guards fail for one hit."""
    others = set()
    for name in _EARLIER:
        text = (REPO_ROOT / "tests" / name).read_text(encoding="utf-8")
        others |= set(re.findall(r'"([A-Z]{1,6}[0-9]{3,4})"', text))
    assert not (set(_PROBES) & others), sorted(set(_PROBES) & others)
