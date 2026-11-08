"""S144-P-433 - the two blind spots the S144-P-372 / -334 / -347 / -374 censuses name, held at zero.

1. ``open()``-family text-mode handles that leave ``encoding=`` to the locale code page. The sibling
   ``tests/test_path_text_io_encoding_census_s144p372.py`` reads ``.read_text()`` / ``.write_text()`` only, and ruff
   PLW1514 (``tests/test_unspecified_encoding_prod_ratchet_s144p303.py``) fires only where it can TYPE the receiver,
   so ``lock_path.open("w")`` on an inferred-unknown receiver, ``tempfile.NamedTemporaryFile("w")``,
   ``os.fdopen(fd, "w")``, ``io.open(p)`` and ``codecs.open`` were unread. Without ``encoding=`` a UTF-8 file holding
   one non-ASCII byte is decoded with cp1252 on a stock Windows box (or raises on 0x81 / 0x8D / 0x8F / 0x90 / 0x9D),
   and the script behaves differently under ``PYTHONUTF8=1``.
2. ``os.popen`` / ``os.system`` / ``asyncio.create_subprocess_*``: shell-out spellings that bypass the subprocess
   censuses (no ``CREATE_NO_WINDOW`` argument exists to audit, no ``encoding=``, no Popen lifecycle row).

Measured 2026-11-08 over every tracked non-test ``*.py`` (ops/fleet_kit excluded, vendored): ZERO sites of either
kind, so both baselines are EMPTY on purpose and this is a floor, not a backlog.

Shapes read for (1): an attribute call ``.open(...)`` whose first positional (Path.open) or ``mode=`` is a string
constant without ``b``, or that takes no mode at all (default ``"r"``) and no argument but ``newline`` / ``errors``;
``tempfile.NamedTemporaryFile`` / ``TemporaryFile`` / ``SpooledTemporaryFile`` with a text ``mode``; ``os.fdopen`` with
a text mode; ``io.open`` / ``codecs.open`` with a text mode or none. A positional encoding (the 3rd argument of
``Path.open`` / ``codecs.open`` / tempfile, the 4th of ``io.open`` / ``os.fdopen``) counts as named. A receiver
containing the WORD image, opener, zf, zip, tar, tarfile, gzip, urllib, sqlite or ``webbrowser`` is not a file handle
and is skipped (whole words only: ``target`` is read), as is a call carrying
``**kwargs`` (it may carry the encoding). Stated limits: a bare name (``from tempfile import NamedTemporaryFile``) or a module alias (``import os as _os``) is
not followed for (1), and the module alias is not followed for (2); a mode held in a variable is not read (the open-mode census
S144-P-373 covers the builtin ``open``), a handle returned by a helper is not followed, and ``tempfile.NamedTemporaryFile``
defaults to binary so only an explicit text mode is a hit. Out of scope, stated: ``ops/fleet_kit/`` and every test
tree.
"""
from __future__ import annotations

import ast
import re

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")
_NOT_A_FILE = re.compile(
    r"(?<![a-z0-9])(image|opener|zf|zip|zipfile|tar|tarfile|roundstore|webbrowser|gzip|wave|sqlite3?|urllib|bz2|lzma)"
    r"(?![a-z0-9])"
)
_TEMPFILES = frozenset({"NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"})

# rel path -> count. EMPTY on purpose: the measured floor, only ever stays empty.
_OPEN_BASELINE: dict[str, int] = {}
_SHELLOUT_BASELINE: dict[str, int] = {}


def _is_str(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _mode_is_text(mode_node: ast.AST | None) -> bool | None:
    """True text, False binary, None unknown (a variable)."""
    if mode_node is None:
        return None
    if not _is_str(mode_node):
        return None
    return "b" not in mode_node.value  # type: ignore[attr-defined]


def open_hits(src: str) -> list[tuple[int, str]]:
    """(line, spelling) of each text-mode handle that leaves the encoding to the locale."""
    hits: list[tuple[int, str]] = []
    for n in ast.walk(ast.parse(src)):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        attr = n.func.attr
        recv = ast.unparse(n.func.value)
        kws = {k.arg: k.value for k in n.keywords}
        if None in kws or "encoding" in kws:
            continue  # **kwargs may carry it
        if attr == "open" and recv in ("io", "codecs"):
            # io.open(file, mode, buffering, encoding): the fourth positional is the encoding;
            # codecs.open(file, mode, encoding): the third.
            if len(n.args) >= (4 if recv == "io" else 3):
                continue
            mode = kws.get("mode") or (n.args[1] if len(n.args) > 1 else None)
            if mode is None or _mode_is_text(mode):
                hits.append((n.lineno, f"{recv}.open"))
        elif attr == "open":
            if _NOT_A_FILE.search(recv.lower()) or recv == "os":
                continue
            if len(n.args) >= 3:  # Path.open(mode, buffering, encoding)
                continue
            mode = kws.get("mode") or (n.args[0] if n.args else None)
            if mode is not None:
                if _mode_is_text(mode):
                    hits.append((n.lineno, ".open"))
            elif not (set(kws) - {"newline", "errors"}):
                hits.append((n.lineno, ".open"))  # Path.open() default mode "r"
        elif attr in _TEMPFILES:
            if len(n.args) >= 3:  # (mode, buffering, encoding)
                continue
            mode = kws.get("mode") or (n.args[0] if n.args else None)
            if mode is not None and _mode_is_text(mode):
                hits.append((n.lineno, attr))
        elif attr == "fdopen" and recv == "os":
            if len(n.args) >= 4:  # (fd, mode, buffering, encoding)
                continue
            mode = kws.get("mode") or (n.args[1] if len(n.args) > 1 else None)
            if mode is not None and _mode_is_text(mode):
                hits.append((n.lineno, "os.fdopen"))
    return sorted(hits)


def shellout_hits(src: str) -> list[tuple[int, str]]:
    """(line, spelling) of ``os.popen`` / ``os.system`` / ``asyncio.create_subprocess_*`` calls."""
    tree = ast.parse(src)
    bare: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "asyncio":
            bare.update((a.asname or a.name) for a in n.names if a.name.startswith("create_subprocess_"))
        elif isinstance(n, ast.ImportFrom) and n.module == "os":
            bare.update((a.asname or a.name) for a in n.names if a.name in ("popen", "system"))
    hits: list[tuple[int, str]] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if (f.value.id == "os" and f.attr in ("popen", "system")) or (
                f.value.id == "asyncio" and f.attr.startswith("create_subprocess_")
            ):
                hits.append((n.lineno, f"{f.value.id}.{f.attr}"))
        elif isinstance(f, ast.Name) and f.id in bare:
            hits.append((n.lineno, f.id))
    return sorted(hits)


def test_scanners_are_live():
    """Each unsafe shape is reported and each safe spelling is quiet (an empty scan proves nothing alone)."""
    bad = (
        "lock.open('w')\n",
        "p.open(mode='a')\n",
        "p.open()\n",
        "p.open(newline='')\n",
        "import tempfile\ntempfile.NamedTemporaryFile('w')\n",
        "import tempfile\ntempfile.TemporaryFile(mode='w+')\n",
        "import os\nos.fdopen(fd, 'w')\n",
        "import io\nio.open(p)\n",
        "import io\nio.open(p, 'r')\n",
        "import codecs\ncodecs.open(p, 'w')\n",
        "target.open('w')\n",
        "start.open('w')\n",
    )
    for src in bad:
        assert open_hits(src), src
    safe = (
        "p.open('w', encoding='utf-8')\n",
        "p.open('rb')\n",
        "p.open(mode='ab')\n",
        "p.open('w', **kw)\n",
        "p.open(mode)\n",
        "Image.open(buf)\n",
        "opener.open(req, timeout=3)\n",
        "zf.open(name)\n",
        "import tempfile\ntempfile.NamedTemporaryFile()\n",
        "import tempfile\ntempfile.NamedTemporaryFile('w', encoding='utf-8')\n",
        "import os\nos.fdopen(fd, 'wb')\n",
        "import os\nos.open(p, 0)\n",
        "import io\nio.open(p, 'r', -1, 'utf-8')\n",
        "import io\nio.open(p, 'rb')\n",
        "import codecs\ncodecs.open(p, 'w', 'utf-8')\n",
        "p.open('r', -1, 'utf-8')\n",
        "import os\nos.fdopen(fd, 'w', -1, 'utf-8')\n",
        "import tempfile\ntempfile.NamedTemporaryFile('w', -1, 'utf-8')\n",
        "tarfile.open(p)\n",
    )
    for src in safe:
        assert open_hits(src) == [], src
    for src in (
        "import os\nos.popen('x')\n",
        "import os\nos.system('x')\n",
        "import asyncio\nasyncio.create_subprocess_exec('x')\n",
        "from asyncio import create_subprocess_shell\ncreate_subprocess_shell('x')\n",
        "from os import system as sh\nsh('x')\n",
    ):
        assert shellout_hits(src), src
    for src in (
        "import os\nos.path.join('a', 'b')\n",
        "import subprocess\nsubprocess.run(['x'])\n",
        "system('x')\n",
        "asyncio.sleep(1)\n",
    ):
        assert shellout_hits(src) == [], src


def _tree(scan) -> dict[str, int]:
    out: dict[str, int] = {}
    for path in repo_files():
        rel = relative_posix(path)
        if not rel.endswith(".py") or rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            hits = scan((REPO_ROOT / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        if hits:
            out[rel] = len(hits)
    return out


def test_no_locale_encoded_text_handle():
    hits = _tree(open_hits)
    new = {r: n for r, n in hits.items() if n > _OPEN_BASELINE.get(r, 0)}
    assert not new, f"text-mode open()-family handle with no encoding= (locale code page on Windows): {new}"


def test_no_shellout_spelling():
    hits = _tree(shellout_hits)
    new = {r: n for r, n in hits.items() if n > _SHELLOUT_BASELINE.get(r, 0)}
    assert not new, f"os.popen / os.system / asyncio.create_subprocess_* bypass the subprocess censuses: {new}"


def test_baselines_are_exact():
    for name, scan, base in (("open", open_hits, _OPEN_BASELINE), ("shellout", shellout_hits, _SHELLOUT_BASELINE)):
        hits = _tree(scan)
        stale = {r: n for r, n in base.items() if hits.get(r, 0) < n}
        assert not stale, f"{name} baseline rows that no longer offend, drop them: {stale}"


def test_walk_reaches_the_file_openers():
    """The walk must reach known .open() users, or an empty result would be a scan that saw nothing."""
    seen = {relative_posix(p) for p in repo_files()}
    for rel in ("core/anvil_shadow.py", "tools/inbox_responder_runner.py", "agents/agent1_lead/scheduler.py"):
        assert rel in seen, rel
