"""RM-141 S1: the "jade" mode key resolves to the SR coaching artifact.

JADE (League Classic throwback) reuses the SR coach path, so it shares
coaching_data.json rather than gaining a writer of its own. The explicit
MODE_TO_FILE entry exists because the queue-map grounding tests assert that
every mapped mode_key is a KEY of MODE_TO_FILE - the :348 resolution was
already correct by fallback, so a fallback-only wiring would pass here and
fail there.

The negative pins matter as much as the positive one: map 453 has no minimap
grid and no ZOI geometry, and no live game has yet proven the client tab is
reachable, so a later slice must not quietly widen those gates.
"""

from pathlib import Path

from dashboard import _state_builder
from dashboard._state_builder import MODE_FILES, MODE_TO_FILE


_REPO_ROOT = Path(__file__).resolve().parent.parent


class TestJadeResolvesToSrArtifact:
    def test_jade_maps_to_root_coaching_data(self) -> None:
        assert MODE_TO_FILE["jade"] == "coaching_data.json"

    def test_jade_shares_the_sr_artifact(self) -> None:
        assert MODE_TO_FILE["jade"] == MODE_TO_FILE["sr"]

    def test_resolution_seam_agrees_with_the_map(self) -> None:
        assert MODE_TO_FILE.get("jade", "coaching_data.json") == "coaching_data.json"


class TestModeFilesDedupeUnchanged:
    """The dict.fromkeys dedupe must absorb the new entry with no artifact."""

    _PRE_EDIT = (
        "data/aram_coaching_data.json",
        "data/arena_coaching_data.json",
        "data/brawl_coaching_data.json",
        "data/tft_coaching_data.json",
        "coaching_data.json",
    )

    def test_mode_files_content_is_byte_unchanged(self) -> None:
        assert MODE_FILES == self._PRE_EDIT

    def test_mode_files_length_is_unchanged(self) -> None:
        assert len(MODE_FILES) == 5

    def test_every_mapped_mode_resolves_into_mode_files(self) -> None:
        assert set(MODE_TO_FILE.values()) == set(MODE_FILES)


class TestJadeIsPinnedOutOfMapGeometryGates:
    """Map 453 has no minimap grid, so neither geometry gate may learn jade."""

    def _source(self) -> str:
        return Path(_state_builder.__file__).read_text(encoding="utf-8")

    def test_minimap_rect_gate_is_exactly_sr_aram_brawl(self) -> None:
        assert 'mode_key in ("sr", "aram", "brawl")' in self._source()

    def test_zoi_gate_is_exactly_sr_aram(self) -> None:
        assert 'minimap_dots and mode_key in ("sr", "aram")' in self._source()

    def test_no_gate_tuple_mentions_jade(self) -> None:
        for line in self._source().splitlines():
            if "mode_key in (" in line:
                assert "jade" not in line


class TestJadeIsPinnedOutOfTheOtherSurfaces:
    """RM-141 adds ZERO writers and ZERO tabs. Cross-module absence pins."""

    def test_theme_tab_colors_has_no_jade_entry(self) -> None:
        from core.theme import TAB_COLORS

        assert "JADE" not in TAB_COLORS
        assert "jade" not in TAB_COLORS

    def test_coach_registry_has_no_jade_writer(self) -> None:
        from core.coach_registry import MODE_COACH_MAP, MODE_POLICY_MAP

        assert not [k for k in MODE_COACH_MAP if "jade" in k.lower()]
        assert not [k for k in MODE_POLICY_MAP if "jade" in k.lower()]

    def test_no_jade_coaching_artifact_is_introduced(self) -> None:
        assert not list((_REPO_ROOT / "data").glob("*jade*coaching_data.json"))
