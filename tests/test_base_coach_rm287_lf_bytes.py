"""RM-287 (LANE 8, Tier-1) - coaches/_base_coach.safe_write must emit LF bytes.

MEASURED live 2026-08-30: data/tft_coaching_data.json was 176 bytes on disk
carrying 11 CRLF pairs. The cause is coaches/_base_coach.py `safe_write`,
which handed the serialized string to Path.write_text. On Windows that
rewrites every LF as CRLF, and Path.read_text translates it back on the way
in, so the extra bytes are invisible to every reader that goes through
read_text (reference_windows_write_text_crlf_byte_count).

Scope, stated honestly: nothing mis-counts TODAY. The JSON parses either way,
and agents/agent2_backend/file_ingest.py:73 caps ingested payloads at 128 KB,
far above these ~2 KB artifacts. The exposure is that any FUTURE size cap,
digest, or byte-length comparison over a coaching artifact is silently wrong
by exactly the artifact's line count.

Every guard below drives the REAL writer and reads the REAL bytes back. The
defect lives in the writer, so a hand-rolled string would prove nothing - and
each assertion is on raw bytes, because read_text is precisely the call that
hides the fault.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from coaches import _base_coach  # noqa: E402

# Shaped like a real coaching artifact: nested + multi-key, so json.dumps
# with indent=2 emits many newlines. A flat single-key payload would put only
# a couple of newlines on disk and would under-exercise the defect.
_ARTIFACT = {
    "mode": "tft",
    "updated": 1756512000,
    "coach": {
        "action": "hold",
        "immediate": "roll at 50",
        "next": "level 8",
    },
    "board": ["Anivia D4", "Swain C3"],
}


def _write_artifact(target: Path) -> bytes:
    """Drive safe_write for real and hand back the bytes that landed."""
    ok = _base_coach.safe_write(target, _ARTIFACT)
    assert ok is True, "safe_write reported failure; the guard needs a real write"
    return target.read_bytes()


class TestSafeWriteEmitsLfBytes(unittest.TestCase):
    """RM-287 - the byte half. No CR may reach a coaching artifact."""

    def test_written_artifact_contains_no_carriage_return_byte(self):
        with tempfile.TemporaryDirectory() as td:
            raw = _write_artifact(Path(td) / "tft_coaching_data.json")
        n_cr = raw.count(b"\r")
        self.assertEqual(
            raw.count(b"\r"), 0,
            f"safe_write put {n_cr} CR bytes (0x0D) on disk; coaching"
            f" artifacts must be LF only")

    def test_byte_length_equals_the_serialized_payload(self):
        """The exposure itself: a size cap or digest over the file must agree
        with the payload the caller serialized."""
        expected = json.dumps(_ARTIFACT, indent=2).encode("utf-8")
        with tempfile.TemporaryDirectory() as td:
            raw = _write_artifact(Path(td) / "aram_coaching_data.json")
        self.assertEqual(len(raw), len(expected))
        self.assertEqual(raw, expected)

    def test_every_newline_is_bare_lf(self):
        """Mirrors the measured live case - 11 CRLF pairs in one artifact."""
        with tempfile.TemporaryDirectory() as td:
            raw = _write_artifact(Path(td) / "arena_coaching_data.json")
        self.assertEqual(raw.count(b"\r\n"), 0)
        self.assertGreater(raw.count(b"\n"), 0, "payload must be multi-line")


class TestSafeWriteRemainsAtomicAndReadable(unittest.TestCase):
    """The byte fix must not cost the tmp + replace the writer already had."""

    def test_payload_round_trips_as_json(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "brawl_coaching_data.json"
            raw = _write_artifact(target)
            self.assertEqual(json.loads(raw.decode("utf-8")), _ARTIFACT)

    def test_replace_still_happens_and_leaves_no_scratch_file(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "sr_coaching_data.json"
            _write_artifact(target)
            self.assertTrue(target.exists())
            leftovers = sorted(p.name for p in Path(td).glob("*.tmp"))
            self.assertEqual(leftovers, [], "scratch file survived the replace")

    def test_overwrites_an_existing_artifact_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "tft_coaching_data.json"
            self.assertIs(_base_coach.safe_write(target, {"stale": True}), True)
            raw = _write_artifact(target)
            self.assertEqual(json.loads(raw.decode("utf-8")), _ARTIFACT)
            self.assertEqual(raw.count(b"\r"), 0)


if __name__ == "__main__":
    unittest.main()


class TestCoachesDirectoryHasNoTextModeJsonWriter(unittest.TestCase):
    """The sibling half of RM-287, closed in the same pass.

    ``safe_write`` was the filed site, but the sibling sweep found the identical
    defect live in ``coaches/experimental_builder.py`` ``_save`` (measured: 6 CR
    bytes on a small payload) and latent in ``mark_active``, which carries no
    ``indent`` today and so translates nothing until someone adds one. Fixing
    only the filed site would have left the class half-open in the same
    directory - `root-cause-fix` calls for the sibling grep, and this pins it.

    The scan is AST, not grep: after the fix the string ``write_text`` still
    appears in ``experimental_builder.py`` inside the explanatory comment, so a
    text search reports a false positive. A grep and an AST sweep answer
    different questions (LEDGER 1323).
    """

    def test_no_pathlib_write_text_call_survives_in_coaches(self):
        import ast

        offenders = []
        for path in sorted((_REPO_ROOT / "coaches").rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - a broken file is another test's problem
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "write_text"
                ):
                    offenders.append(f"{path.relative_to(_REPO_ROOT).as_posix()}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            "Path.write_text writes CRLF on Windows and read_text hides it, so "
            "any byte count or digest over the artifact is wrong by the line "
            "count. Use write_bytes with an explicit .encode('utf-8'), as "
            "coaches/_base_coach.safe_write and core/polled_json."
            "atomic_write_json both do. Offending call sites: " + str(offenders),
        )
