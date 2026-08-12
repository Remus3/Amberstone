"""Rename guard: Riot Commander -> Amberstone.

Riot's third-party developer policy forbids their trademarks in a project name,
website, advertising or domain without a written licence, so the product name
had to change. Name locked 2026-08-11: **Amberstone** (product) + Daemon Slayer
(engine, internal, unchanged). Plan: docs/RENAME_SWEEP_AMBERSTONE.md.

THIS SUITE GUARDS BOTH FAILURE MODES, and the second one is the one that
actually threatens the repo:

  UNDER-FIRE  a Tier-0 surface still carries the old product name.
  OVER-FIRE   a blind find-replace ate the NOMINATIVE references. About 77
              percent of the 4163 "riot" occurrences in this tree name Riot
              Games the company, the Riot API, the Riot Live Client, or real
              League items ("Hextech Gunblade"). Those are legitimate and
              REQUIRED - the disclaimer Riot's own policy mandates must
              literally contain the words "Riot Games". A sweep that scores
              100 percent on the under-fire guard by deleting the over-fire
              guard's subjects has destroyed the repo, not renamed it.

Tier 1 (653 prose hits across 258 files) is NOT in scope here yet - widen
TIER0_FILES as those land. Historical records (docs/LEDGER.md,
docs/history_notes.md, docs/ROADMAP_HISTORY.md, docs/_archive/**) are a
PERMANENT carve-out: they are append-only accounts of what was true at the time
and renaming inside them rewrites history.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Every spelling of the OLD product name.
PRODUCT_NAME_FORMS = (
    "Riot Commander",
    "riot-commander",
    "RiotCommander",
    "riot_commander",
)

# Surfaces that must be clean NOW (Tier 0 - public-facing / packaging).
TIER0_FILES = (
    "rc-shell/electron-builder.yml",
    "rc-shell/package.json",
    "web/index.html",
)

# The GitHub repo rename is an operator action (it changes a public URL), so
# `riot-commander` inside a github.com URL is EXEMPT until that lands. Tracked
# by test_github_urls_are_the_only_remaining_old_slug below, which fails loudly
# once they are gone so this exemption cannot rot into a blanket pass.
_GITHUB_URL_RE = re.compile(r"github\.com/[^\s)\"']*riot-commander[^\s)\"']*")

# Same exemption, different shape: electron-builder's `publish.repo` slug must
# equal the REAL GitHub repo name or electron-updater loses its feed, so it
# moves in the same step as the repo rename and not before.
_PUBLISH_SLUG_RE = re.compile(r"^\s*repo:\s*riot-commander\s*$", re.M)


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


class Tier0IsClean(unittest.TestCase):
    """No Tier-0 surface may carry the old product name."""

    def test_tier0_files_have_no_old_product_name(self) -> None:
        for rel in TIER0_FILES:
            text = _PUBLISH_SLUG_RE.sub("", _GITHUB_URL_RE.sub("", _read(rel)))
            for form in PRODUCT_NAME_FORMS:
                with self.subTest(file=rel, form=form):
                    self.assertNotIn(
                        form, text,
                        f"{rel} still carries the old product name {form!r}",
                    )

    def test_app_id_is_amberstone(self) -> None:
        # Operator-approved 2026-08-11. Changing appId is a BREAKING install
        # identity change on Windows - an existing install will not upgrade, it
        # co-installs - so this pin exists to make any future drift deliberate.
        yml = _read("rc-shell/electron-builder.yml")
        self.assertIn("appId: com.amberstone.shell", yml)
        self.assertNotIn("com.riotcommander", yml)

    def test_product_name_and_window_title_are_amberstone(self) -> None:
        self.assertIn("productName: Amberstone Shell",
                      _read("rc-shell/electron-builder.yml"))
        self.assertIn("Amberstone", _read("web/index.html"))


class NominativeReferencesSurvive(unittest.TestCase):
    """THE IMPORTANT HALF. A blind replace would silently kill these."""

    def test_riot_games_the_company_is_still_named(self) -> None:
        self.assertIn("Riot Games", _read("README.md"))

    def test_riot_api_surfaces_still_named(self) -> None:
        # If these vanish the sweep over-fired into technical prose.
        readme = _read("README.md")
        self.assertTrue(
            any(t in readme for t in ("Riot API", "Live Client", "Riot Live Client")),
            "README no longer names the Riot API / Live Client - the sweep "
            "over-fired into nominative technical references",
        )

    def test_real_league_item_names_survive(self) -> None:
        # "Hextech" is Riot IP as a THEME, but Hextech Gunblade is the actual
        # name of a real item the engine must model. Nominative, keep.
        effects = _read("agents/daemon_slayer/_effects_data.py")
        self.assertIn("Hextech Gunblade", effects)


class DisclaimerIsCorrect(unittest.TestCase):
    """Riot's policy requires a readily visible non-endorsement notice."""

    def test_disclaimer_names_the_new_product_and_riot_games(self) -> None:
        readme = _read("README.md")
        m = re.search(r"^.*not endorsed by Riot Games.*$", readme, re.M)
        self.assertIsNotNone(m, "README has no non-endorsement disclaimer")
        line = m.group(0)
        self.assertIn("Amberstone", line,
                      "the disclaimer still names the OLD product")
        self.assertIn("Riot Games", line,
                      "the disclaimer must literally name Riot Games")


class RepoRenameIsStillPending(unittest.TestCase):
    """Operator action, deliberately not automated - it changes a public URL."""

    def test_github_urls_are_the_only_remaining_old_slug(self) -> None:
        # Once `gh repo rename` lands and the URLs are updated, this test goes
        # RED and should be DELETED along with _GITHUB_URL_RE. That is the
        # point: the exemption cannot outlive the thing it exempts.
        readme = _read("README.md")
        stripped = _GITHUB_URL_RE.sub("", readme)
        for form in PRODUCT_NAME_FORMS:
            with self.subTest(form=form):
                self.assertNotIn(
                    form, stripped,
                    f"README carries {form!r} outside a github.com URL",
                )


if __name__ == "__main__":
    unittest.main()
