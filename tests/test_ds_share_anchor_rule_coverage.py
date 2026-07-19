"""Guard: the ds_share_sync anchor-rule set COVERS every mechanical
version/patch anchor form the authored Share docs actually carry.

Phase-2 item (c). ``_doc_anchor_rules()`` (``tools/ds_share_sync.py``) shipped
with five rules - the ``ENGINE_VERSION = "X"`` literal plus the ``data patch
`X` `` / ``Active data patch: `X` `` / ``game patch `X` `` / ``"patch": "X"``
phrases. Three further anchor forms in the same docs DO track the live engine
but had no rule, so ``--check`` reported GREEN while they rotted:

  1. the ``Share/README.md`` header line - sat at ``1.149.0`` / ``16.12.1`` for
     72 engine minors while live was ``1.221.0`` / ``16.14.1``
  2. the ``current.txt`` prose mention (03_DATA_AND_SOURCES.md) - sat at ``16.11.1``
  3. the manifest path citation (01_OVERVIEW.md) - sat at ``16.11.1``

All three were repaired by hand in the last docs-sync commit; nothing in the
tool would have caught them. That is a silent-failure guard - green exactly
where it was blind - so this test pins COVERAGE of each form rather than the
freshness of today's values (``test_ds_share_doc_anchors.py`` pins freshness).

Every sample below is transcribed verbatim from the committed doc at the cited
line, with the live tokens swapped for ``{v}`` / ``{p}``, so the rules are
proven against real text instead of a guessed shape.
``test_committed_docs_still_carry_each_form`` re-derives that transcription from
disk, so a doc reflow that silently disarms a rule fails HERE rather than going
undetected for another 72 minors.

The carve-out cases pin the DELIBERATE exclusions named in the
``_doc_anchor_rules`` docstring: a file-path placeholder, the CommunityDragon
two-segment patch pin, the ``current.txt`` CONTENT description, the
copy-forward authoring patches, loopback addresses, and changelog history must
all stay unmatched.
"""
from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import agents.daemon_slayer as ds
from tools import ds_share_sync as sync

# The values these forms actually rotted at before the hand-repair. Used only as
# planted drift; asserted != live so the test cannot silently no-op.
_STALE_V = "1.149.0"
_STALE_P = "16.11.1"

# (form label, doc relpath, verbatim template, cited site)
_ANCHOR_FORMS: tuple[tuple[str, str, str, str], ...] = (
    (
        "README header",
        "README.md",
        "**Engine version:** {v}  -  **Patch:** {p}\n",
        "Share/README.md:3",
    ),
    (
        "current.txt prose",
        "docs/03_DATA_AND_SOURCES.md",
        "file, `data/daemon_slayer/current.txt`, names the active patch (currently\n"
        "`{p}`); the loader reads that pointer first, then the patch directory it names.\n",
        "Share/docs/03_DATA_AND_SOURCES.md:76-77",
    ),
    (
        "manifest path citation",
        "docs/01_OVERVIEW.md",
        "(`data/daemon_slayer/{p}/manifest.json:5`).\n",
        "Share/docs/01_OVERVIEW.md:10",
    ),
)

# (label, verbatim text that must survive a rewrite untouched, cited site)
_CARVE_OUTS: tuple[tuple[str, str, str], ...] = (
    (
        "current.txt CONTENT description",
        "| `current.txt` | 7 B | pointer | flipped by the primary extractor "
        "| plain text: `16.11.1` | patch resolver |\n",
        "Share/docs/03_DATA_AND_SOURCES.md:101",
    ),
    (
        "CommunityDragon two-segment pin",
        "`raw.communitydragon.org/<MAJOR.MINOR>/...` (a two-segment patch pin - "
        "`/16.11/` resolves, `/16.11.1/` does not).\n",
        "Share/docs/03_DATA_AND_SOURCES.md:24",
    ),
    (
        "copy-forward authoring patch",
        "  (`16.9.1` for enchanter items, `16.10.1` for the two augment files) as proof of\n",
        "Share/docs/03_DATA_AND_SOURCES.md:117",
    ),
    (
        "snapshot path placeholder",
        "All snapshot data lives under `data/daemon_slayer/<patch>/`. A one-line pointer\n",
        "Share/docs/03_DATA_AND_SOURCES.md:75",
    ),
    (
        "loopback address",
        "python tools/start_daemon_slayer.py                # serves http://127.0.0.1:8893\n",
        "Share/README.md:71",
    ),
    (
        "changelog history entry",
        "- 1.148.0 -> 1.149.0 - all-source target-vulnerability mark registry (default-off).\n",
        "Share/README.md:91",
    ),
)


@contextmanager
def _share_root(root: Path):
    """Point the tool at a throwaway Share/ tree for the duration."""
    orig = sync._SHARE
    sync._SHARE = root
    try:
        yield
    finally:
        sync._SHARE = orig


def _plant(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class StaleValuesAreDistinctTests(unittest.TestCase):
    def test_planted_stale_values_differ_from_live(self):
        """If live ever equals the planted stale token the drift tests would
        pass vacuously."""
        self.assertNotEqual(_STALE_V, ds.ENGINE_VERSION)
        self.assertNotEqual(_STALE_P, sync._PATCH)


class TranscriptionFidelityTests(unittest.TestCase):
    def test_committed_docs_still_carry_each_form(self):
        """Each template, rendered with LIVE values, appears verbatim in the real
        committed doc. Proves the patterns below are matched against real text,
        and fails loudly if a doc reflow disarms a rule."""
        live_v, live_p = ds.ENGINE_VERSION, sync._PATCH
        for label, rel, template, site in _ANCHOR_FORMS:
            with self.subTest(form=label):
                text = (sync._SHARE / rel).read_text(encoding="utf-8")
                self.assertIn(
                    template.format(v=live_v, p=live_p), text,
                    f"{site} no longer carries the '{label}' form verbatim - the "
                    f"anchor rule for it is now disarmed; re-transcribe the template",
                )


class AnchorFormCoverageTests(unittest.TestCase):
    """The core gap: --check must FAIL on a stale value in each form."""

    def test_check_detects_stale_value_in_each_form(self):
        live_v, live_p = ds.ENGINE_VERSION, sync._PATCH
        for label, rel, template, site in _ANCHOR_FORMS:
            with self.subTest(form=label):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    _plant(root, rel, template.format(v=_STALE_V, p=_STALE_P))
                    with _share_root(root):
                        drift = sync._check_doc_anchors()
                self.assertGreater(
                    drift, 0,
                    f"'{label}' ({site}) is an UNCOVERED anchor form: a stale "
                    f"value there is invisible to --check. Live is "
                    f"{live_v}/{live_p}; planted {_STALE_V}/{_STALE_P}. "
                    f"Add a rule to _doc_anchor_rules().",
                )

    def test_rewrite_repairs_each_form(self):
        live_v, live_p = ds.ENGINE_VERSION, sync._PATCH
        for label, rel, template, site in _ANCHOR_FORMS:
            with self.subTest(form=label):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    doc = _plant(root, rel, template.format(v=_STALE_V, p=_STALE_P))
                    with _share_root(root):
                        changed = sync._rewrite_doc_anchors()
                        residual = sync._check_doc_anchors()
                    text = doc.read_text(encoding="utf-8")
                self.assertIn(rel, changed, f"'{label}' ({site}) was not rewritten")
                self.assertEqual(
                    text, template.format(v=live_v, p=live_p),
                    f"'{label}' ({site}) did not restamp to the live values exactly",
                )
                self.assertEqual(residual, 0, f"'{label}' still drifts after rewrite")

    def test_rewrite_of_fresh_form_is_a_noop(self):
        """Idempotence: a rule must not churn a doc that is already live."""
        live_v, live_p = ds.ENGINE_VERSION, sync._PATCH
        for label, rel, template, _site in _ANCHOR_FORMS:
            with self.subTest(form=label):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    _plant(root, rel, template.format(v=live_v, p=live_p))
                    with _share_root(root):
                        self.assertEqual(
                            sync._rewrite_doc_anchors(), [],
                            f"'{label}' rewrote an already-fresh doc",
                        )


class CarveOutTests(unittest.TestCase):
    """The deliberate exclusions must stay excluded - a rule that grabs one of
    these would corrupt a frozen historical value or a placeholder."""

    def test_excluded_forms_survive_a_rewrite_untouched(self):
        for label, text, site in _CARVE_OUTS:
            with self.subTest(carve_out=label):
                for rel in ("README.md", "docs/03_DATA_AND_SOURCES.md"):
                    with tempfile.TemporaryDirectory() as td:
                        root = Path(td)
                        doc = _plant(root, rel, text)
                        with _share_root(root):
                            sync._rewrite_doc_anchors()
                        self.assertEqual(
                            doc.read_text(encoding="utf-8"), text,
                            f"a rule rewrote the '{label}' carve-out ({site}) in "
                            f"{rel}; it is frozen by design",
                        )

    def test_excluded_forms_are_not_reported_as_drift(self):
        for label, text, site in _CARVE_OUTS:
            with self.subTest(carve_out=label):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    _plant(root, "docs/03_DATA_AND_SOURCES.md", text)
                    with _share_root(root):
                        drift = sync._check_doc_anchors()
                self.assertEqual(
                    drift, 0,
                    f"the '{label}' carve-out ({site}) was reported as drift",
                )


class LiveTreeStaysGreenTests(unittest.TestCase):
    def test_new_rules_do_not_fire_on_the_committed_tree(self):
        """The committed docs were hand-refreshed; a correct rule set reports
        zero drift. A failure here is a FALSE POSITIVE in a new rule (or a
        genuinely stale doc) - investigate before editing any doc."""
        self.assertEqual(
            sync._check_doc_anchors(), 0,
            "an anchor rule fires on the committed tree - suspect a rule that is "
            "too broad (a placeholder, a loopback IP, or frozen history)",
        )


class AsciiHygieneTests(unittest.TestCase):
    def test_tool_and_test_are_ascii(self):
        for p in (Path(sync.__file__), Path(__file__)):
            raw = p.read_bytes()
            self.assertTrue(
                all(b < 128 for b in raw), f"{p.name} carries a non-ASCII byte"
            )


if __name__ == "__main__":
    unittest.main()
