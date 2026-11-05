"""RM-1417 - four ruff rules are held at zero across the tree.

None of these is selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree: 4 rules, 21 sites in 12 files. 10 files
were fixed by that slice and the three coach files by RM-1541, so ``_WAIVED``
is empty and any new site fails.

- TRY203 ``except X: raise``: a handler that only re-raises is dead code. Six DS
  test helpers and dashboard/routes_loop_control.py dropped theirs (the
  PermissionError still propagates; the comment now says so on purpose).
- TRY201 ``raise exc`` inside a handler for ``exc``: bare ``raise`` keeps the
  traceback honest.
- LOG014 ``exc_info=True`` outside a handler: it logs ``NoneType: None`` unless
  the caller happens to sit inside an except block. The anvil / augment shadow
  ``_note_failure`` helpers already receive the exception, so they pass it.
- SIM910 ``dict.get(key, None)``: ``None`` is already the default.

Waived: nothing. coaches/{aram,arena,brawl}_coach.py used to carry an outer
``try: ... except Exception: raise`` around the whole of ``_run_coach`` (about
900 lines with prompt strings inside); RM-1541 removed it by an AST-checked
dedent that leaves every string constant byte-identical. Reverses if: a handler
that only re-raises is deliberately wanted somewhere - then add a named
``_WAIVED`` entry with the reason (a waiver that no longer matches a live
finding fails as stale).

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore
cannot hide a finding, and keeps only tracked files.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = "TRY203,TRY201,LOG014,SIM910"
_WAIVED: set[tuple[str, str]] = set()
_FIXED = (
    "agents/daemon_slayer/tests/test_ability_dps.py",
    "agents/daemon_slayer/tests/test_burst.py",
    "agents/daemon_slayer/tests/test_hps.py",
    "agents/daemon_slayer/tests/test_rank_assassin.py",
    "agents/daemon_slayer/tests/test_rank_enchanter.py",
    "agents/daemon_slayer/tests/test_rank_mage.py",
    "core/anvil_shadow.py",
    "core/augment_shadow.py",
    "dashboard/routes_loop_control.py",
    "tft/tft_coach_engine.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_tree_has_no_new_reraise_exc_info_or_get_none_finding():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found = []
    seen_waived = set()
    for d in _ruff(["--select", _RULES, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel not in tracked:
            continue
        if (rel, d["code"]) in _WAIVED:
            seen_waived.add((rel, d["code"]))
            continue
        found.append(f"{rel}:{d['location']['row']} {d['code']}")
    assert not found, f"ruff {_RULES}: {found}"
    # A waiver for a site that no longer exists is stale: drop it.
    assert seen_waived == _WAIVED, f"stale waiver: {_WAIVED - seen_waived}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("module", ["core.anvil_shadow", "core.augment_shadow"])
def test_note_failure_logs_the_exception_it_was_handed(module, caplog):
    """LOG014: exc_info=True outside a handler logs 'NoneType: None'. The helper
    is handed the exception, so it must log THAT one even when called from
    outside any except block (first failure per target = WARNING, then DEBUG)."""
    mod = importlib.import_module(module)
    mod._WARNED.clear()
    boom = ValueError("synthetic shadow write failure")
    with caplog.at_level(logging.DEBUG, logger=mod.log.name):
        mod._note_failure("probe-target-a", boom)
        mod._note_failure("probe-target-a", boom)
    records = [r for r in caplog.records if r.name == mod.log.name]
    assert len(records) == 2
    assert {r.levelno for r in records} == {logging.WARNING, logging.DEBUG}
    for r in records:
        assert r.exc_info is not None and r.exc_info[1] is boom, r.exc_info
    mod._WARNED.clear()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("def f():\n    try:\n        g()\n    except ValueError:\n        raise\n", "TRY203"),
        ("def f():\n    try:\n        g()\n    except ValueError as e:\n        raise e\n", "TRY201"),
        ("import logging\nlog = logging.getLogger('x')\n\n\ndef f(e):\n"
         "    log.warning('m', exc_info=True)\n", "LOG014"),
        ("D = {'k': 1}\n\n\ndef f():\n    return D.get('k', None)\n", "SIM910"),
    ],
)
def test_each_probe_is_live(code, expected):
    """Each rule flags a minimal offender - so an empty tree result is a clean
    tree, not a dead probe."""
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=code)
    assert expected in {d["code"] for d in found}, found
