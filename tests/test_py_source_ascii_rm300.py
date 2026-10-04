"""RM-300: every tracked authored .py file is 7-bit ASCII - a CENSUS, not an allowlist.

Two rules enforced CLAUDE.md's 7-bit rule and neither could find an EXISTING
violator: `tools/precommit_gate.py` scans only ADDED diff lines, and
`tests/test_u2500_hygiene.py` walks an allowlist, which cannot discover a file
nobody enrolled. Measured 2026-08-31: 28 files / 640 codepoints; re-measured
2026-10-04 at 3fdb79305: 22 files / 482 codepoints.

This guard enumerates the git index (tests/_repo_walk, ADR-015) and honours the
SAME exemption predicate the commit gate uses (`precommit_gate._ascii_exempt`),
so the gate and the census cannot drift into two readings again. There is no
per-file allowlist: a file is either exempt by the gate's predicate or it is
held to ASCII. A non-ASCII VALUE belongs in an escape (`"\\u2192"`), which keeps
the source ASCII and the runtime string identical - `tools/ascii_escape_py.py`
does that rewrite and proves it with an AST comparison.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, tracked_relpaths


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_GATE = _load("precommit_gate_rm300", "tools/precommit_gate.py")
_TOOL = _load("ascii_escape_py_rm300", "tools/ascii_escape_py.py")


def _universe() -> list[str]:
    idx = tracked_relpaths()
    assert idx is not None, "git index unreadable - the census would be empty"
    return sorted(r for r in idx if r.endswith(".py") and not _GATE._ascii_exempt(r))


def _violations(rels: list[str], root: Path = REPO_ROOT) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for rel in rels:
        p = root / rel
        if not p.is_file():
            continue
        raw = p.read_bytes()
        bad = sorted({b for b in raw if b > 127})
        if bad:
            text = raw.decode("utf-8", errors="replace")
            out[rel] = sorted({f"U+{ord(c):04X}" for c in text if ord(c) > 127})
    return out


def test_census_is_not_vacuous():
    """An empty enumeration would pass; anchor it to the real tree size."""
    files = _universe()
    assert len(files) > 1000, f"census selected only {len(files)} .py files"
    assert "tools/precommit_gate.py" in files


def test_every_tracked_authored_py_file_is_ascii():
    bad = _violations(_universe())
    assert not bad, (
        f"{len(bad)} tracked .py file(s) carry non-ASCII:\n"
        + "\n".join(f"    {f}  {g}" for f, g in sorted(bad.items()))
        + "\n  Fix: python tools/ascii_escape_py.py --apply <file> (escapes string"
          " values, transliterates comments/docstrings). If the file is genuinely"
          " external data, exempt it in tools/precommit_gate._ascii_exempt.")


def test_census_catches_a_reintroduced_glyph(tmp_path: Path):
    """Mutation control: the census must flag a glyph it was never told about."""
    probe = tmp_path / "probe_rm300.py"
    probe.write_bytes(('x = "a' + chr(0x2192) + 'b"\n').encode("utf-8"))
    assert _violations(["probe_rm300.py"], tmp_path) == {"probe_rm300.py": ["U+2192"]}
    clean = tmp_path / "clean_rm300.py"
    clean.write_bytes(b'x = "a -> b"\n')
    assert _violations(["clean_rm300.py"], tmp_path) == {}


def test_tool_escape_preserves_value_and_transliterates_prose():
    src = (
        '"""Doc ' + chr(0x2192) + ' arrow."""\n'
        "# note " + chr(0x00B7) + " dot\n"
        'A = "x ' + chr(0x2192) + ' y"\n'
        'B = f"{1} ' + chr(0x6211) + '"\n'
        'D = "' + chr(0x1F525) + '"\n'
    )
    out = _TOOL.convert(src)
    assert all(ord(c) < 128 for c in out)
    ns_old: dict = {}
    ns_new: dict = {}
    exec(src, ns_old)
    exec(out, ns_new)
    for k in "ABD":
        assert ns_old[k] == ns_new[k], k
    assert "Doc -> arrow." in out
    assert "# note / dot" in out


def test_tool_refuses_raw_strings_and_fstring_expressions():
    # Raw: an escape would change the value. Nested in an f-string field: a
    # backslash there is a SyntaxError before 3.12 (ruff target py39).
    for src in ('P = r"[' + chr(0x2192) + ',]"\n',
                "C = f\"{'" + chr(0x2713) + "' if True else ''}\"\n"):
        with pytest.raises(_TOOL.RawStringError):
            _TOOL.convert(src)


def test_ascii_files_are_returned_unchanged():
    src = 'x = "plain"\n'
    assert _TOOL.convert(src) is src


def test_smart_quote_tool_and_guard_agree_on_external_data():
    """The strip tool and its drift guard each carry `_is_external_data`. They
    diverged (the tool lacked the three DDragon catalogs), so the tool's
    --apply would have rewritten Riot's item text. Same reading, both sides."""
    tool = _load("strip_smart_quotes_rm300", "tools/strip_smart_quotes.py")
    guard = _load("smart_quote_guard_rm300", "tests/test_smart_quote_hygiene.py")
    idx = tracked_relpaths()
    assert idx
    probes = sorted(r for r in idx if r.startswith("data/"))
    assert len(probes) > 10
    diff = [r for r in probes
            if tool._is_external_data(r) != guard._is_external_data(r)]
    assert not diff, f"tool and guard disagree on: {diff[:20]}"
