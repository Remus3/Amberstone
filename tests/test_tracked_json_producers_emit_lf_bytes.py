"""RM-406 sibling sweep - every producer of a tracked, eol=lf-pinned artifact
must serialize to BYTES, never hand a str to ``Path.write_text``.

WHY A CLASS GUARD AND NOT ANOTHER PER-FILE TEST
-----------------------------------------------
The root cause is not "``tools/ddragon_mirror_refresh`` used write_text". It is
that on Windows ``Path.write_text`` rewrites every LF as CRLF while
``read_text`` translates it back, so the extra bytes are invisible to every
reader yet real on disk - and for a TRACKED file that git normalizes in the
index, ``git status`` stays clean the whole time. The defect is therefore
invisible from BOTH directions at once, which is why it survived in six
shipped bundles. RM-287 fixed two instances of this shape
(``coaches/_base_coach.safe_write``, ``core/polled_json.atomic_write_json``)
and a third was still on disk on 2026-09-11, so a per-file test is measurably
not enough.

An adversarial pass over the 2026-09-11 fix found two MORE producers with the
identical shape that the narrow fix missed - ``tools/daemon_slayer_extract``
and ``tools/daemon_slayer_abilities_extract``, both writing tracked
``data/daemon_slayer/**`` JSON pinned ``eol=lf`` by ``.gitattributes``. This
table is the answer to that: adding a producer to it is cheaper than
rediscovering the class a fourth time.

WHAT THIS GUARD CANNOT DO
-------------------------
It cannot find a producer nobody added to the table. The static half below
narrows that gap by rejecting ``write_text`` inside any listed function, but a
brand-new writer in a brand-new module is invisible here until someone lists
it. It also says nothing about whether a given call site's TARGET is really
tracked - that is asserted separately, against ``git check-attr``, so a row
whose premise rots fails loudly instead of testing nothing.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import subprocess
import textwrap

import pytest

from tests import _repo_walk

REPO_ROOT = _repo_walk.REPO_ROOT

# Multi-line by construction. A single-line payload cannot expose the defect,
# because text mode only rewrites newlines that are already there - a test
# written with a flat payload would pass against every broken producer here.
_PAYLOAD = {
    "alpha": [1, 2, 3],
    "beta": {"nested": True, "name": "Kai'Sa"},
    "gamma": "line one",
}

# (module, callable, kind, one representative tracked target it writes)
#
# `kind` says how the callable is invoked: "json" takes (path, obj), "text"
# takes (path, str). The target is what makes each row falsifiable - it is
# re-checked against git below, so renaming or untracking it reds this file
# rather than quietly reducing the guard to a tmp-file exercise.
_PRODUCERS = (
    ("tools.ddragon_mirror_refresh", "_atomic_write_json", "json",
     "data/meta_build/ddragon/_index.json"),
    ("lib.ddragon.fetch", "_atomic_write_json", "json",
     "data/meta_build/ddragon/16.18.1/champion.json"),
    ("tools.daemon_slayer_extract", "_atomic_write_json", "json",
     "data/daemon_slayer/16.15.1/champions.json"),
    ("tools.daemon_slayer_extract", "_atomic_write_text", "text",
     "data/daemon_slayer/current.txt"),
    ("tools.daemon_slayer_abilities_extract", "_atomic_write_json", "json",
     "data/daemon_slayer/16.15.1/champion_abilities.json"),
    # The RM-287 pair, kept in the table rather than trusted: they are the two
    # instances of this class that were already fixed, so they double as the
    # positive control that the assertions below can be satisfied at all.
    ("core.polled_json", "atomic_write_json", "json",
     "data/daemon_slayer/16.15.1/items.json"),
)

_TEXT_PAYLOAD = "first\nsecond\nthird\n"


def _executable_source(fn) -> str:
    """The function's source with comments AND its docstring removed.

    Both have to go. `core.polled_json.atomic_write_json` explains this very
    defect in its docstring and names `Path.write_text` while doing so, and
    every fixed producer here carries a `# Bytes, not write_text` comment - a
    naive substring search over `inspect.getsource` reports all of them as
    offenders, which is a false positive in the direction that makes the
    correct fix look like the bug.
    """
    src = inspect.getsource(fn)
    tree = ast.parse(textwrap.dedent(src))
    func = tree.body[0]
    if (func.body and isinstance(func.body[0], ast.Expr)
            and isinstance(func.body[0].value, ast.Constant)
            and isinstance(func.body[0].value.value, str)):
        func.body = func.body[1:]
    # ast.unparse drops comments and the docstring node in one step, and it
    # cannot accidentally keep a string that only LOOKS like code.
    return ast.unparse(func) if func.body else ""


def _resolve(mod_name, attr):
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, attr, None)
    assert fn is not None, f"{mod_name} no longer defines {attr}"
    return fn


def _invoke(fn, kind, target):
    if kind == "json":
        fn(target, _PAYLOAD)
    else:
        fn(target, _TEXT_PAYLOAD)


def test_producer_table_is_not_empty():
    """Anchor. Every parametrisation below is driven off this tuple, so an
    empty table would turn the whole file green by not looking."""
    assert len(_PRODUCERS) == 6, (
        "the producer table changed size - raise this number when a real "
        "producer is added, never lower it to make a deletion green"
    )


@pytest.mark.parametrize(
    "row", _PRODUCERS, ids=[f"{m.split('.')[-1]}.{a}" for m, a, _k, _t in _PRODUCERS])
def test_producer_writes_lf_bytes(row, tmp_path):
    """The behavioural half - run the real function, read the real bytes."""
    mod_name, attr, kind, _target = row
    fn = _resolve(mod_name, attr)
    out = tmp_path / f"{mod_name.replace('.', '_')}_{attr}.json"
    _invoke(fn, kind, out)
    raw = out.read_bytes()
    assert raw, f"{mod_name}.{attr} wrote nothing - the assertion below would "\
                "pass for the wrong reason"
    pairs = raw.count(b"\r\n")
    assert pairs == 0, (
        f"{mod_name}.{attr} put {pairs} CRLF pairs on disk. Its targets are "
        "tracked and pinned eol=lf, so git normalizes them in the index and "
        "`git status` will stay CLEAN while the working tree is wrong."
    )
    assert b"\r" not in raw
    if kind == "json":
        assert json.loads(raw.decode("utf-8")) == _PAYLOAD
    else:
        assert raw == _TEXT_PAYLOAD.encode("utf-8")


@pytest.mark.parametrize(
    "row", _PRODUCERS, ids=[f"{m.split('.')[-1]}.{a}" for m, a, _k, _t in _PRODUCERS])
def test_producer_source_does_not_call_write_text(row):
    """The static half. The behavioural test above passes on Linux even
    against a broken producer, because the CRLF rewrite is a Windows-only
    property of text mode - so CI would go green on exactly the platform the
    defect does not occur on. This assertion is platform-independent.
    """
    mod_name, attr, _kind, _target = row
    fn = _resolve(mod_name, attr)
    body = _executable_source(fn)
    # The CALL, not the bare word: `tools.daemon_slayer_extract` names one of
    # these functions `_atomic_write_text`, so a substring search for
    # "write_text" flags the correct, already-fixed function by its own name.
    assert ".write_text(" not in body, (
        f"{mod_name}.{attr} calls write_text. Encode to bytes instead - see "
        "this file's docstring for why the defect is invisible to both "
        "`read_text` and `git status`."
    )


@pytest.mark.parametrize(
    "row", _PRODUCERS, ids=[f"{m.split('.')[-1]}.{a}" for m, a, _k, _t in _PRODUCERS])
def test_named_target_is_tracked_and_eol_pinned(row):
    """The premise check. Each row claims its producer writes a TRACKED,
    eol=lf-pinned file; if that stops being true the row is testing nothing
    and should be removed deliberately rather than left to rot.
    """
    _mod_name, _attr, _kind, target = row
    listed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", target],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert listed.returncode == 0, f"{target} is not tracked by git"
    attrs = subprocess.run(
        ["git", "check-attr", "eol", "--", target],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert attrs.returncode == 0, attrs.stderr
    assert attrs.stdout.strip().endswith("eol: lf"), (
        f"{target} is no longer pinned eol=lf ({attrs.stdout.strip()!r}) - "
        "without that pin git does not normalize it and this row's premise "
        "is gone"
    )


def test_no_tracked_eol_pinned_file_currently_carries_crlf():
    """Outcome, not mechanism. The producers above can all be correct while
    the tree still holds bytes an earlier broken run left behind.

    The `-text` exemption is real and documented by
    `tests/test_text_line_endings.py`: the LFS payloads under
    `data/laning_scenarios/` carry `-text` on purpose, so git never normalizes
    them and their CRLF is not this defect.
    """
    tracked = _repo_walk.repo_files()
    assert len(tracked) >= 1000, (
        f"enumeration collapsed to {len(tracked)} files - fix the walker"
    )
    offenders = []
    for path in tracked:
        rel = _repo_walk.relative_posix(path)
        if not rel.endswith((".json", ".txt")):
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\r\n" not in raw:
            continue
        attrs = subprocess.run(
            ["git", "check-attr", "text", "--", rel],
            cwd=REPO_ROOT, capture_output=True, text=True)
        if attrs.stdout.strip().endswith("text: set"):
            offenders.append((rel, raw.count(b"\r\n")))
    assert not offenders, (
        "tracked, git-normalized file(s) carry CRLF on disk while `git "
        f"status` reports them clean: {offenders}"
    )
