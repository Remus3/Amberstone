"""
tests/snapshot_panels/test_icon_stand_in_seam_rm2041.py
RM-2041 (s154): the snapshot mock stands in a 1x1 PNG for a missing icon
(conftest.py _is_missing_icon), but never inside a directory with tracked
files. A tracked icon that goes missing (web/icons/positions/, web/icons/
lobby/) must still answer 404: no snapshot test reads those icons (measured
with top.png hidden: the five lobby modules that render them still passed),
so the stand-in would hide the loss entirely. No browser here.
"""
from tests._repo_walk import tracked_relpaths
from tests.snapshot_panels.conftest import _is_missing_icon


def _tracked_icons():
    tracked = tracked_relpaths() or frozenset()
    return sorted(rel for rel in tracked
                  if rel.startswith("web/icons/") and rel.endswith(".png"))


def test_a_tracked_icon_directory_is_never_stood_in_for():
    icons = _tracked_icons()
    # Anchor: the seven tracked position / lobby icons are found.
    assert len(icons) >= 7, icons
    for rel in icons:
        url = "/" + rel.removeprefix("web/")
        assert not _is_missing_icon(url), url
        missing = url.rsplit("/", 1)[0] + "/rm2041-not-a-file.png"
        assert not _is_missing_icon(missing), missing


def test_an_untracked_mirror_icon_is_stood_in_for():
    # The positive control: the trees the pages ask for are not tracked.
    for url in ("/icons/champions/rm2041-not-a-file.png",
                "/icons/spells/rm2041-not-a-file.png",
                "/data/ddragon/0.0.0/img/item/rm2041-not-a-file.png"):
        assert _is_missing_icon(url), url
