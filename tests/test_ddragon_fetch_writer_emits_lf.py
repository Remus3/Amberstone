"""``lib.ddragon.fetch._atomic_write_json`` must emit LF bytes, atomically.

WHAT IS ALREADY COVERED, AND BY WHAT (RM-410, 2026-09-11). The class guard
``tests/test_tracked_json_producers_emit_lf_bytes.py`` DOES call this writer.
Its ``_PRODUCERS`` table carries the row at ``:66-67``
``("lib.ddragon.fetch", "_atomic_write_json", "json", ...)``, and the
parametrised behavioural half - its own ``:132`` docstring reads "The
behavioural half - run the real function, read the real bytes" - invokes it at
``:115`` ``fn(target, _PAYLOAD)``, reads ``:137`` ``raw = out.read_bytes()``,
then asserts ``:141`` ``pairs == 0`` and ``:146`` ``b"\\r" not in raw``.
Measured: ``pytest tests/test_tracked_json_producers_emit_lf_bytes.py -q
-p no:randomly -k fetch`` -> 3 passed, 17 deselected.

``test_atomic_write_json_emits_no_crlf`` below therefore DUPLICATES green
coverage on purpose. It is kept as a deliberate LOCAL ANCHOR so a regression
names this one writer and this one file, instead of surfacing only as a
parametrised id inside a six-row table. It is overlap, not a gap, and it should
not be cited as this file's reason to exist.

WHAT IS NET-NEW HERE - the actual reason this file exists. The class guard
asserts NONE of the following five:
  1. The exact compact-encoding byte pin - ``raw`` equals
     ``json.dumps(payload, separators=(",", ":")).encode("utf-8")``, which fixes
     the separators, the encoding and the absence of a trailing newline. The
     guard only round-trips through ``json.loads``, so it stays green against
     any re-formatting that still parses.
  2. The measured finding that a compact dump contains no literal LF, which is
     why the HISTORICAL pre-fix ``write_text`` line was byte-identical to
     today's ``write_bytes`` and why the class guard could never have caught a
     revert to it. The reachable regression is an ``indent=``, not a revert.
     See ``test_compact_separators_emit_no_literal_newline``.
  3. The ``indent=2`` positive control, which measures 20 CRLF pairs on this
     machine against the real writer's 0.
  4. The no-surviving-``.tmp`` assertion.
  5. The ``os.replace``-raises fault injection, proving a pre-existing target
     keeps its bytes when the swap fails.

HONESTY NOTE, kept deliberately. An earlier draft of this docstring claimed the
producer had no direct caller and that this file was the first to call it. That
was FALSE - refuted by a verifier and by an independent re-probe before merge.
The paragraph above is the corrected account.

Sibling precedent in style: ``tests/test_ddragon_mirror_writes_bytes.py``, the
direct test of ``tools/ddragon_mirror_refresh._atomic_write_json``.

WRITER GROUND TRUTH, verified against the tree this test ships with:
``lib/ddragon/fetch.py:33`` ``def _atomic_write_json(path: Path, data: Any)``,
``:34`` ``mkdir(parents=True, exist_ok=True)``, ``:35`` ``.tmp`` sibling,
``:43`` ``tmp.write_bytes(json.dumps(data, separators=(",", ":")).encode(...))``,
``:44`` ``os.replace(tmp, path)``. ``json``/``os``/``Path`` are imported at
``lib/ddragon/fetch.py:16-19``, so ``os`` is a module global and is the stdlib
module itself - that is the fault-injection handle used below.

THE RED-PROOF HONESTY NOTE - read this before "improving" the teeth.
The pre-fix line (commit ``c00b9af89``, which replaced it) was
``tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")``.
Reverting to it CANNOT be made to fail with a JSON payload, so any claim of a
red-proof against the historical line would be FALSE. Reason: compact
separators emit no literal newline for any payload (newlines inside strings are
escaped to backslash-n), so text mode has nothing to translate and write_text is
byte-identical to write_bytes even on Windows. ``lib/ddragon/fetch.py:37-42``
says this in its own comment and names the reachable regression: adding an
``indent=``. ``test_compact_separators_emit_no_literal_newline`` below pins that
measured fact so the reasoning is not just prose.

Teeth therefore come from a POSITIVE CONTROL rather than a revert: a sibling
file written with the named regression shape (``indent=2`` through
``write_text``) is asserted to carry the platform line ending. OBSERVED on this
machine (Windows, ``os.linesep == "\\r\\n"``): the control file carries 20 CRLF
pairs, against 0 for the real writer's output. The control assertion is written
portably, so it stays green where ``os.linesep`` is LF while still proving the
byte assertions are not vacuous here.

Every assertion is on BYTES. ``read_text`` is never used: it translates CRLF
back to LF on Windows, so a version of this test written that way would pass
against the broken writer by construction.
"""
from __future__ import annotations

import json
import os

import pytest

import lib.ddragon.fetch as fetch_mod
from lib.ddragon.fetch import _atomic_write_json

# Multi-key and nested, matching the sibling test's shape. An indent= regression
# needs structure to have anything to indent, which is what the positive control
# below exercises.
_PAYLOAD = {
    "bundles": ["champion", "item", "runesReforged", "summoner"],
    "latest_pulled": "16.18.1",
    "locale": "en_US",
    "nested": {"a": 1, "b": [2, 3, 4], "c": {"d": "e"}},
}

_SENTINEL = b'{"pre-existing":"do not clobber"}'


def test_atomic_write_json_emits_no_crlf(tmp_path):
    target = tmp_path / "champion.json"
    _atomic_write_json(target, _PAYLOAD)
    raw = target.read_bytes()
    pairs = raw.count(b"\r\n")
    assert pairs == 0, f"{target.name} carries {pairs} CRLF pairs on disk"
    assert b"\r" not in raw


def test_atomic_write_json_bytes_are_exactly_the_compact_encoding(tmp_path):
    """Pins compact separators, utf-8, and NO trailing newline."""
    target = tmp_path / "item.json"
    _atomic_write_json(target, _PAYLOAD)
    raw = target.read_bytes()
    assert raw == json.dumps(_PAYLOAD, separators=(",", ":")).encode("utf-8")
    assert json.loads(raw.decode("utf-8")) == _PAYLOAD


def test_compact_separators_emit_no_literal_newline():
    """MEASURED FINDING - why a "revert to write_text" red-proof would lie.

    With compact separators the encoded payload holds no literal newline, so
    text mode has nothing to rewrite and the historical pre-fix line is
    byte-identical to today's write_bytes. Only an ``indent=`` change can
    reintroduce the defect, which is exactly what the positive control below
    demonstrates.
    """
    compact = json.dumps(_PAYLOAD, separators=(",", ":"))
    assert "\n" not in compact
    assert "\r" not in compact
    # The regression shape does carry newlines - the defect is reachable, it is
    # just not reachable through the separators the writer uses today.
    assert json.dumps(_PAYLOAD, indent=2).count("\n") > 0


def test_positive_control_write_text_indent_carries_platform_line_endings(tmp_path):
    """The teeth: prove the byte assertions above are not vacuous here.

    Writes a sibling control file with the regression shape named by
    ``lib/ddragon/fetch.py:37-42`` and asserts the on-disk bytes carry
    ``os.linesep``. OBSERVED on this machine: 20 CRLF pairs.
    """
    target = tmp_path / "real.json"
    _atomic_write_json(target, _PAYLOAD)

    control = tmp_path / "control.json"
    indented = json.dumps(_PAYLOAD, indent=2)
    control.write_text(indented, encoding="utf-8")

    control_raw = control.read_bytes()
    assert control_raw == indented.replace("\n", os.linesep).encode("utf-8")
    if os.linesep == "\r\n":
        pairs = control_raw.count(b"\r\n")
        assert pairs > 0, "positive control proved nothing on a CRLF platform"
        assert target.read_bytes().count(b"\r\n") == 0
        assert len(control_raw) > len(indented.encode("utf-8"))


def test_atomic_write_json_leaves_no_tmp_behind(tmp_path):
    target = tmp_path / "summoner.json"
    _atomic_write_json(target, _PAYLOAD)
    assert list(tmp_path.glob("*.tmp")) == []
    assert target.exists()


def test_atomic_write_json_leaves_target_intact_when_replace_fails(
    tmp_path, monkeypatch
):
    """A failed ``os.replace`` must not leave a partially written TARGET.

    ``lib/ddragon/fetch.py:43-44`` writes the payload to a ``.tmp`` sibling and
    only then swaps it in, so the target either holds its old bytes or the new
    ones - never a half-written file. Fault-injected at the module's own ``os``
    handle (``lib/ddragon/fetch.py:18``).
    """
    target = tmp_path / "runesReforged.json"
    target.write_bytes(_SENTINEL)

    def _boom(src, dst):
        raise OSError("injected: replace failed")

    monkeypatch.setattr(fetch_mod.os, "replace", _boom)

    with pytest.raises(OSError, match="injected"):
        _atomic_write_json(target, _PAYLOAD)

    assert target.read_bytes() == _SENTINEL
