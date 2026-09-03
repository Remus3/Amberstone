"""RM-335 - the Share-sync drift messages must print a path the reader can open.

`ds_share_sync.py` resolves the ingest slice as ``_SHARE / "lolmath_ingest"``
where ``_SHARE = _REPO / "Share"``, but two drift messages printed a bare
``lolmath_ingest/...`` prefix. That path does not resolve from the repo root,
so the reader the message is addressed to cannot `ls` the file it names. It
cost a merger two failed probes and a wrong conclusion that the artifact was
absent from every tree, when it was present in both.

The remedy sentence had the matching problem: it said to run the sync "and
commit Share/", but the dist bundle is a gitignored build artifact
(`.gitignore` ``dist/``) tracked nowhere, so the commit half is unsatisfiable
for that path. The rebuild half is correct and is preserved.

**The drift BEHAVIOUR is deliberate and is not under test here.** An absent
bundle is a SKIP (the clean-checkout / CI case) and a present-but-stale bundle
is drift, cleared by write mode - documented in `_check_ingest_bundle`. These
tests assert message TEXT only.
"""
from __future__ import annotations

import io
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tools import ds_share_sync as sync

# The real on-disk location of the ingest slice, captured independently of the
# module constant so a monkeypatched `_INGEST` cannot make these tests vacuous.
_REAL_INGEST = sync._REPO / "Share" / "lolmath_ingest"

# Pulls the printed path token out of a drift line. Stops at ":" so the
# "file:line" suffix on the anchor message is not swallowed.
_PATH_RE = re.compile(r"(?P<path>[^\s:]*lolmath_ingest[^\s:]*)")

# The exact unsatisfiable remedy literal removed by RM-335. Anchoring on the
# literal keeps the guard from passing on a reworded-but-equally-wrong string.
_UNSATISFIABLE_REMEDY = "and commit Share/."


def _printed_path(output: str) -> str:
    m = _PATH_RE.search(output)
    assert m is not None, f"no lolmath_ingest path in output: {output!r}"
    return m.group("path")


class BundleDriftMessagePathTests(unittest.TestCase):
    """The INGEST BUNDLE DRIFT line names a path that resolves from the root."""

    def _drift_output(self) -> str:
        with TemporaryDirectory() as td:
            ingest = Path(td) / "lolmath_ingest"
            target = ingest / sync._INGEST_BUNDLE_REL
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"stale")
            buf = io.StringIO()
            with mock.patch.object(sync, "_INGEST", ingest), \
                    mock.patch.object(sync, "_build_expected_bundle",
                                      return_value=b"fresh"), \
                    redirect_stdout(buf):
                drift = sync._check_ingest_bundle()
            self.assertEqual(drift, 1, "planted stale bundle did not register as drift")
            return buf.getvalue()

    def test_printed_path_is_share_rooted(self):
        self.assertTrue(
            _printed_path(self._drift_output()).startswith("Share/"),
            "bundle drift path must be rooted at Share/ to resolve from the repo root",
        )

    def test_printed_path_resolves_to_the_real_bundle_location(self):
        printed = _printed_path(self._drift_output())
        self.assertEqual(
            (sync._REPO / printed).resolve(),
            (_REAL_INGEST / sync._INGEST_BUNDLE_REL).resolve(),
        )

    def test_printed_paths_parent_directory_exists(self):
        """Resolution proof that survives a clean checkout: the bundle itself
        is gitignored and may be absent, but its directory is real."""
        printed = _printed_path(self._drift_output())
        self.assertTrue((sync._REPO / printed).parent.parent.is_dir())


class AnchorDriftMessagePathTests(unittest.TestCase):
    """The INGEST ANCHOR DRIFT line names a path that resolves from the root."""

    def _drift_output(self) -> str:
        with TemporaryDirectory() as td:
            ingest = Path(td) / "lolmath_ingest"
            ingest.mkdir(parents=True, exist_ok=True)
            # A single-leading-digit semver matches the engine rule and is not
            # the live engine version, so exactly one anchor drifts.
            (ingest / "README.md").write_text("engine 9.9.9\n", encoding="utf-8")
            buf = io.StringIO()
            with mock.patch.object(sync, "_INGEST", ingest), redirect_stdout(buf):
                drift = sync._check_ingest_anchors()
            self.assertEqual(drift, 1, "planted stale anchor did not register as drift")
            return buf.getvalue()

    def test_printed_path_is_share_rooted(self):
        self.assertTrue(
            _printed_path(self._drift_output()).startswith("Share/"),
            "anchor drift path must be rooted at Share/ to resolve from the repo root",
        )

    def test_printed_path_exists_on_disk(self):
        """README.md is tracked, so the strongest form of the acceptance
        applies here: the printed path can actually be opened."""
        printed = _printed_path(self._drift_output())
        self.assertEqual(printed, "Share/lolmath_ingest/README.md")
        self.assertTrue(
            (sync._REPO / printed).is_file(),
            f"printed path does not resolve to a file: {printed}",
        )


class RemedySentenceTests(unittest.TestCase):
    """The remedy must be achievable: rebuild yes, commit-the-gitignored no."""

    def _check_output(self) -> tuple[int, str]:
        buf = io.StringIO()
        with mock.patch.object(sync, "_build_expected", return_value={}), \
                mock.patch.object(sync, "_engine_version", return_value="1.0.0"), \
                mock.patch.object(sync, "_check", return_value=1), \
                mock.patch.object(sync, "_check_doc_anchors", return_value=0), \
                mock.patch.object(sync, "_check_ingest_anchors", return_value=0), \
                mock.patch.object(sync, "_check_ingest_bundle", return_value=0), \
                redirect_stdout(buf):
            rc = sync.main(["--check"])
        return rc, buf.getvalue()

    def test_check_still_exits_one_on_drift(self):
        """Behaviour is unchanged - only the wording moves."""
        rc, _ = self._check_output()
        self.assertEqual(rc, 1)

    def test_remedy_keeps_the_rebuild_half(self):
        _, out = self._check_output()
        self.assertIn("python tools/ds_share_sync.py", out)

    def test_remedy_drops_the_unsatisfiable_commit_instruction(self):
        """The dist bundle is gitignored and tracked nowhere, so a blanket
        "and commit Share/." cannot be carried out for that path."""
        _, out = self._check_output()
        self.assertNotIn(_UNSATISFIABLE_REMEDY, out)

    def test_remedy_says_the_bundle_is_not_committed(self):
        """The reader is told why the commit half does not cover everything."""
        _, out = self._check_output()
        self.assertIn("gitignored", out.lower())


class AsciiHygieneTests(unittest.TestCase):
    def test_test_file_is_ascii(self):
        text = Path(__file__).read_text(encoding="utf-8")
        bad = [(i, c) for i, c in enumerate(text) if ord(c) > 126]
        self.assertEqual(bad, [], f"non-ASCII in {Path(__file__).name}: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
