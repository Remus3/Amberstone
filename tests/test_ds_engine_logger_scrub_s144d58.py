"""RM-1280: every DS engine logger carries the core.log_scrub backstop.

RM-1279 installed ``core.log_scrub.ScrubFilter`` on the
``daemon_slayer.server`` logger, but a logger's filters see only the records
created on THAT logger, never a child's or a sibling's. The engine modules
log on their own names (``logging.getLogger(__name__)`` in abilities,
ability_dps, burst, cc_conditional, combo, effects, fight_report,
focus_board, mana_sim, scenario_matrix, _ability_base_overrides), and none
of them carried the filter, in either process that runs the engine: the DS
server on :8860 and the :8888 dashboard, whose routes (routes_ds_combo and
the rest) call the engine in-process. Measured before the fix: a record with
``exc_info`` on ``agents.daemon_slayer.effects`` (effects.py logs the RM-186
fallback with ``exc_info=True``) rendered the exception text raw, so a
newline in it forged a log line and an ESC reached the log, and a 100k text
was one 100k line.

The fix keeps the engine core-free: ``agents/daemon_slayer/_log_names.py``
lists the package's logger names as plain data, and the two installers that
already import ``core.log_scrub`` - ``agents/daemon_slayer/server.py`` and
``dashboard/__init__.py`` - attach the filter to every one of them. The list
is enumerated from source here, so a new engine logger fails this guard
until it is listed.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "agents" / "daemon_slayer"

# Every engine module that logs, by the name its getLogger call resolves to.
# A floor for the source enumeration: an empty or shrunken walk can never
# read as "every logger covered".
_KNOWN = {
    "agents.daemon_slayer.abilities",
    "agents.daemon_slayer.ability_dps",
    "agents.daemon_slayer.burst",
    "agents.daemon_slayer.cc_conditional",
    "agents.daemon_slayer.combo",
    "agents.daemon_slayer.effects",
    "agents.daemon_slayer.fight_report",
    "agents.daemon_slayer.focus_board",
    "agents.daemon_slayer.mana_sim",
    "agents.daemon_slayer.scenario_matrix",
    "agents.daemon_slayer._ability_base_overrides",
    "daemon_slayer.server",
    "rc.cli",
}


def _source_logger_names() -> dict[str, str]:
    """name -> file:line for every getLogger call in the engine package,
    its own tests excluded (the git index via tests/_repo_walk, ADR-015)."""
    from tests._repo_walk import repo_files
    files = [p for p in repo_files(PKG, ("*.py",))
             if "tests" not in p.relative_to(PKG).parts]
    assert len(files) >= 50, len(files)
    out: dict[str, str] = {}
    for p in files:
        rel = p.relative_to(ROOT).with_suffix("")
        module = ".".join(rel.parts[:-1] if rel.name == "__init__"
                          else rel.parts)
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and n.args
                    and isinstance(n.func, (ast.Attribute, ast.Name))
                    and getattr(n.func, "attr",
                                getattr(n.func, "id", None)) == "getLogger"):
                continue
            arg = n.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                name = arg.value
            elif isinstance(arg, ast.Name) and arg.id == "__name__":
                name = module
            else:
                raise AssertionError(f"{rel}:{n.lineno}: a getLogger name "
                                     "this guard cannot resolve")
            out.setdefault(name, f"{rel.as_posix()}:{n.lineno}")
    return out


def test_source_enumeration_finds_every_known_engine_logger():
    names = _source_logger_names()
    assert set(names) >= _KNOWN, sorted(_KNOWN - set(names))


def test_the_name_list_matches_the_source_exactly():
    """A new logger fails until listed; a removed one fails until unlisted."""
    from agents.daemon_slayer import _log_names
    names = _source_logger_names()
    listed = set(_log_names.LOGGER_NAMES)
    assert len(listed) == len(_log_names.LOGGER_NAMES), "duplicate entry"
    assert listed == set(names), {
        "unlisted": {n: names[n] for n in set(names) - listed},
        "stale": sorted(listed - set(names)),
    }


def test_the_name_module_stays_core_free():
    """The engine package does not import core in production; the list is
    plain data and imports nothing."""
    tree = ast.parse((PKG / "_log_names.py").read_text(encoding="utf-8"))
    imports = [n for n in ast.walk(tree)
               if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert all(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               for n in imports), [ast.dump(n) for n in imports]


# The probe runs in a FRESH interpreter per installer, because a filter
# installed by one import is process-global and would mask the other.
_PROBE = r'''
import importlib, json, logging, sys
importlib.import_module(sys.argv[1])
from core.log_scrub import ScrubFilter
names = json.loads(sys.argv[2])
ESC, NEL, LS = chr(0x1B), chr(0x85), chr(0x2028)
evil = "bad " + ESC + "[31mX\r\nFORGED-LINE" + NEL + LS + "Y"
fmt = logging.Formatter("%(name)s %(levelname)s %(message)s")
out = {}
for name in names:
    if name.startswith("agents."):
        importlib.import_module(name)
    lg = logging.getLogger(name)
    texts = []

    class Cap(logging.Handler):
        def emit(self, record):
            texts.append(fmt.format(record))

    cap = Cap(level=logging.DEBUG)
    prior, prop = lg.level, lg.propagate
    lg.addHandler(cap)
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    try:
        lg.warning("probe %s", evil)
        try:
            raise ValueError(evil + "Z" * 100000)
        except ValueError:
            lg.warning("fallback", exc_info=True)
    finally:
        lg.removeHandler(cap)
        lg.setLevel(prior)
        lg.propagate = prop
    out[name] = {
        "filtered": any(isinstance(f, ScrubFilter) for f in lg.filters),
        "texts": texts,
    }
print(json.dumps(out))
'''

_CTRL = ({chr(c) for c in range(0x20)}
         | {chr(c) for c in range(0x7F, 0xA0)} | {chr(0x2028), chr(0x2029)})


def _probe(installer: str) -> dict:
    names = sorted(_KNOWN)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, installer, json.dumps(names)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module", params=["agents.daemon_slayer.server",
                                        "dashboard"])
def probed(request):
    return request.param, _probe(request.param)


def test_every_engine_logger_carries_the_filter(probed):
    installer, out = probed
    missing = sorted(n for n, r in out.items() if not r["filtered"])
    assert missing == [], (installer, missing)


def test_a_message_cannot_forge_a_line_or_carry_a_control(probed):
    installer, out = probed
    for name, r in out.items():
        msg = r["texts"][0]
        assert "\n" not in msg, (installer, name, msg)
        assert not ({*msg} & _CTRL), (installer, name, repr(msg))
        assert "FORGED-LINE" in msg


def test_a_traceback_keeps_frames_but_cannot_forge_a_line(probed):
    installer, out = probed
    for name, r in out.items():
        text = r["texts"][1]
        lines = text.split("\n")
        assert lines[0].endswith("fallback"), (installer, name, lines[0])
        assert any(line.startswith("Traceback") for line in lines)
        assert not any(line.lstrip().startswith("FORGED") for line in lines), (
            installer, name)
        for line in lines:
            assert not ({*line} & _CTRL), (installer, name, repr(line[:200]))
            assert len(line) <= 4096 + 40, (installer, name, len(line))
