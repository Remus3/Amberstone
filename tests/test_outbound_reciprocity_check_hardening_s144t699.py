"""S144-T-699: hardening of ``tools/outbound_reciprocity_check.py``.

Four findings from the s144 true-audit pass. Each has at least one test here
that failed against the pre-fix module; a few others (named as such) are
regression guards for a neighbouring path that was already right:

1. **An UNREADABLE marker was compared as if it were content.** ``_file_digest``
   returns ``UNREADABLE:<ExcName>`` for a file it cannot read. Two DIFFERENT
   unreadable files carry the SAME marker, so an unreadable local note scored
   DELIVERED against any recipient holding any unreadable file, two distinct
   unreadable notes collapsed into one, an unreadable recipient copy was
   admitted as a note "delivered" to itself, and a directory payload with an
   unreadable member hashed equal on both sides. Every one of those is a
   DELIVERED verdict for bytes nobody compared - the exact failure the tool
   exists to catch. Unreadable content is now UNKNOWN, never a match.
2. **This repo's own root, configured as a recipient, read as delivery.** Its
   inbox IS the local inbox, so every note stranded there scored DELIVERED -
   "a note written into your own inbox is indistinguishable from a note you
   sent", reproduced by the auditor. Such a slot is now UNKNOWN.
3. **Junk per-host config shapes.** A non-object document raised
   ``AttributeError`` (a CLI traceback, exit 1, instead of an inconclusive run);
   a string ``repos`` was iterated as CHARACTERS, each one a recipient root
   (``/`` among them); ``null`` / numeric entries were admitted as the roots
   ``None`` / ``5``; a BOM-prefixed file silently yielded zero roots.
4. **``--names`` could raise on a strict console.** A note name is free text;
   a non-ASCII or surrogate-escaped name went to stdout verbatim. The rendered
   text is now ASCII-only, names backslash-escaped.

All fixtures are synthetic trees under ``tmp_path``; no sibling literal.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import outbound_reciprocity_check as orc  # noqa: E402

SELF = "ZZ"
OTHER = "QQ"


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    return path


def _make_tree(tmp_path: Path, sibling_count: int) -> tuple[Path, list[Path]]:
    local = tmp_path / "local-repo"
    (local / orc.INBOX_DIRNAME).mkdir(parents=True)
    siblings = []
    for i in range(sibling_count):
        s = tmp_path / f"sibling-{i}"
        (s / orc.INBOX_DIRNAME).mkdir(parents=True)
        siblings.append(s)
    return local, siblings


def _check(local: Path, siblings: list[Path]):
    return orc.check(local, roots=list(siblings), self_code=SELF)


@pytest.fixture
def unreadable(monkeypatch):
    """Make ``Path.open`` raise PermissionError for the named basenames, so the
    REAL ``except OSError`` in ``_file_digest`` produces the marker."""
    names: set = set()
    real_open = Path.open

    def fake_open(self, *a, **kw):
        if self.name in names:
            raise PermissionError(13, "denied", str(self.name))
        return real_open(self, *a, **kw)

    monkeypatch.setattr(Path, "open", fake_open)
    return names


# ------------------------------------------------- 1. unreadable markers


def test_unreadable_local_note_is_not_delivered_by_an_unrelated_unreadable_file(
        tmp_path, unreadable):
    local, sibs = _make_tree(tmp_path, 1)
    mine = _write(local / orc.INBOX_DIRNAME / f"2026-11-09-1000-from-{SELF}-a.md", "mine\n")
    theirs = _write(sibs[0] / orc.INBOX_DIRNAME / f"2026-11-09-1001-from-{OTHER}-b.md",
                    "unrelated\n")
    unreadable.update({mine.name, theirs.name})

    rep = _check(local, sibs)

    assert rep.notes_checked == 1
    note = rep.notes[0]
    assert note.per_slot[0] == orc.STATUS_UNKNOWN
    assert note.verdict == orc.STATUS_UNKNOWN
    assert rep.verdict != orc.VERDICT_CLEAN
    assert orc.exit_code(rep) == orc.EXIT_INCONCLUSIVE


def test_two_distinct_unreadable_notes_stay_two_notes(tmp_path, unreadable):
    local, sibs = _make_tree(tmp_path, 1)
    a = _write(local / orc.INBOX_DIRNAME / f"2026-11-09-1000-from-{SELF}-a.md", "a\n")
    b = _write(local / orc.INBOX_DIRNAME / f"2026-11-09-1001-from-{SELF}-b.md", "b\n")
    unreadable.update({a.name, b.name})

    rep = _check(local, sibs)

    assert rep.notes_checked == 2
    assert rep.unknown_count == 2


def test_unreadable_recipient_copy_is_not_delivered_to_itself(tmp_path, unreadable):
    local, sibs = _make_tree(tmp_path, 1)
    copy = _write(sibs[0] / orc.INBOX_DIRNAME / f"2026-11-09-1000-from-{SELF}-a.md", "a\n")
    unreadable.add(copy.name)

    rep = _check(local, sibs)

    assert rep.notes_checked == 1
    assert rep.notes[0].reach == 0
    assert rep.notes[0].verdict == orc.STATUS_UNKNOWN
    assert rep.verdict == orc.VERDICT_UNKNOWN


def test_readable_note_never_matches_an_unreadable_recipient_copy(tmp_path, unreadable):
    """Regression guard (passed before the fix too): a marker never equals a
    hex digest, so a readable note cannot be matched by a renamed copy."""
    local, sibs = _make_tree(tmp_path, 1)
    name = f"2026-11-09-1000-from-{SELF}-a.md"
    _write(local / orc.INBOX_DIRNAME / name, "a\n")
    _write(sibs[0] / orc.INBOX_DIRNAME / f"_held-{name}", "x\n")  # staging, ignored
    blocked = _write(sibs[0] / orc.INBOX_DIRNAME / "renamed-copy.md", "a\n")
    unreadable.add(blocked.name)

    rep = _check(local, sibs)

    local_note = next(n for n in rep.notes if n.in_local)
    assert local_note.per_slot[0] == orc.STATUS_ABSENT
    assert local_note.verdict == orc.STATUS_UNDELIVERED


def test_same_name_unreadable_recipient_copy_is_unknown_not_name_only(
        tmp_path, monkeypatch):
    """The copy's bytes could not be read, so its content is UNKNOWN - not
    known to DIFFER (NAME_ONLY), and the note did not provably reach nobody."""
    local, sibs = _make_tree(tmp_path, 2)
    name = f"2026-11-09-1000-from-{SELF}-a.md"
    _write(local / orc.INBOX_DIRNAME / name, "a\n")
    blocked = _write(sibs[0] / orc.INBOX_DIRNAME / name, "a\n")
    real_open = Path.open

    def fake_open(self, *a, **kw):
        # Only the RECIPIENT copy is unreadable; the local one reads fine.
        if self == blocked:
            raise PermissionError(13, "denied", self.name)
        return real_open(self, *a, **kw)

    monkeypatch.setattr(Path, "open", fake_open)

    rep = _check(local, sibs)

    local_note = next(n for n in rep.notes if n.in_local)
    assert local_note.per_slot[0] == orc.STATUS_UNKNOWN
    assert local_note.per_slot[1] == orc.STATUS_ABSENT
    assert local_note.verdict == orc.STATUS_UNKNOWN
    assert rep.name_mismatch_count == 0
    assert rep.verdict == orc.VERDICT_UNKNOWN


def test_payload_with_an_unlistable_subdirectory_is_unknown(tmp_path, monkeypatch):
    """A difference hidden inside a subdirectory that cannot be LISTED must not
    hash equal: rglob skipped such a directory silently."""
    local, sibs = _make_tree(tmp_path, 1)
    for root, body in ((local, "one\n"), (sibs[0], "two\n")):
        d = root / orc.INBOX_DIRNAME / f"from-{SELF}-verbatim"
        _write(d / "a.py", "print(1)\n")
        _write(d / "locked" / "b.py", body)
    real_scandir = os.scandir

    def fake_scandir(path="."):
        if os.path.basename(os.fspath(path)) == "locked":
            raise PermissionError(13, "denied", "locked")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)

    rep = _check(local, sibs)

    assert rep.notes, "the payload must still be in the universe"
    assert all(n.verdict == orc.STATUS_UNKNOWN for n in rep.notes)
    assert rep.verdict != orc.VERDICT_CLEAN


def test_directory_payload_with_an_unreadable_member_is_unknown(tmp_path, unreadable):
    local, sibs = _make_tree(tmp_path, 1)
    for root in (local, sibs[0]):
        d = root / orc.INBOX_DIRNAME / f"from-{SELF}-verbatim"
        _write(d / "a.py", "print(1)\n")
        _write(d / "locked.py", "print(2)\n")
    unreadable.add("locked.py")

    rep = _check(local, sibs)

    assert rep.notes_checked >= 1
    assert all(n.verdict == orc.STATUS_UNKNOWN for n in rep.notes)
    assert rep.verdict != orc.VERDICT_CLEAN


def test_unknown_note_with_readable_slots_renders_honestly(tmp_path, unreadable):
    local, sibs = _make_tree(tmp_path, 1)
    good = f"2026-11-09-1000-from-{SELF}-good.md"
    _write(local / orc.INBOX_DIRNAME / good, "good\n")
    _write(sibs[0] / orc.INBOX_DIRNAME / good, "good\n")
    bad = _write(local / orc.INBOX_DIRNAME / f"2026-11-09-1001-from-{SELF}-bad.md", "b\n")
    unreadable.add(bad.name)

    rep = _check(local, sibs)
    text = orc.render(rep)

    assert rep.verdict == orc.VERDICT_UNKNOWN
    # One recipient WAS readable, so the text must not claim none was ...
    assert "no recipient inbox was readable" not in text
    # ... and the per-slot line must call the readable slot readable.
    assert "slot 0 (readable)" in text


def test_unreadable_marker_digest_shape_is_stable():
    """The marker the fix keys on is the one _file_digest really emits."""
    assert orc._file_digest(Path("definitely-absent-s144t699.bin")).startswith(
        orc.UNREADABLE_PREFIX)


# --------------------------------------------- 2. own root as a recipient


def test_own_root_configured_as_a_recipient_is_never_delivery(tmp_path):
    local, sibs = _make_tree(tmp_path, 1)
    _write(local / orc.INBOX_DIRNAME / f"2026-11-09-1000-from-{SELF}-stranded.md", "s\n")

    rep = orc.check(local, roots=[local, sibs[0]], self_code=SELF)

    note = rep.notes[0]
    assert note.per_slot[0] == orc.STATUS_UNKNOWN
    assert note.per_slot[1] == orc.STATUS_ABSENT
    assert note.verdict == orc.STATUS_UNDELIVERED
    assert rep.slots_unknown == 1
    assert rep.verdict == orc.VERDICT_UNDELIVERED


def test_own_root_spelled_differently_is_still_recognised(tmp_path):
    local, _ = _make_tree(tmp_path, 0)
    _write(local / orc.INBOX_DIRNAME / f"2026-11-09-1000-from-{SELF}-stranded.md", "s\n")
    alias = tmp_path / "x" / ".." / local.name

    rep = orc.check(local, roots=[alias], self_code=SELF)

    assert rep.slots_readable == 0
    assert rep.verdict == orc.VERDICT_UNKNOWN


def test_own_root_through_a_link_is_still_recognised(tmp_path):
    """Only ``samefile`` sees through a link: the spellings differ even after
    normalisation, so a string compare alone would read the slot."""
    local, _ = _make_tree(tmp_path, 0)
    _write(local / orc.INBOX_DIRNAME / f"2026-11-09-1000-from-{SELF}-stranded.md", "s\n")
    alias = tmp_path / "alias-root"
    try:
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(local), str(alias))
        else:
            alias.symlink_to(local, target_is_directory=True)
    except (OSError, AttributeError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a directory link here: {type(exc).__name__}")

    rep = orc.check(local, roots=[alias], self_code=SELF)

    assert rep.slots_readable == 0
    assert rep.notes[0].per_slot[0] == orc.STATUS_UNKNOWN


# ------------------------------------------------------ 3. junk config


def _cfg(local: Path, raw: bytes) -> None:
    cfg = local / "ops" / "moon_sync_repos.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_bytes(raw)


@pytest.mark.parametrize("doc", [[], ["a", "b"], "a string", 5, None, True])
def test_non_object_config_yields_no_roots_and_never_raises(tmp_path, doc):
    local, _ = _make_tree(tmp_path, 0)
    _cfg(local, json.dumps(doc).encode("ascii"))
    assert orc.load_sibling_roots(local, env={}) == []


def test_string_repos_is_not_iterated_as_characters(tmp_path):
    local, _ = _make_tree(tmp_path, 0)
    _cfg(local, json.dumps({"repos": "/srv/a-sibling"}).encode("ascii"))
    assert orc.load_sibling_roots(local, env={}) == []


def test_non_string_repo_entries_are_skipped(tmp_path):
    local, sibs = _make_tree(tmp_path, 1)
    doc = {"repos": [None, 5, True, {"p": 1}, ["x"], "", "   ", str(sibs[0])]}
    _cfg(local, json.dumps(doc).encode("ascii"))
    assert orc.load_sibling_roots(local, env={}) == [sibs[0]]


def test_bom_prefixed_config_is_read(tmp_path):
    local, sibs = _make_tree(tmp_path, 1)
    _cfg(local, b"\xef\xbb\xbf" + json.dumps({"repos": [str(sibs[0])]}).encode("ascii"))
    assert orc.load_sibling_roots(local, env={}) == [sibs[0]]


def test_cli_on_a_non_object_config_exits_inconclusive(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(orc.REPOS_ENV, raising=False)
    local, _ = _make_tree(tmp_path, 0)
    _cfg(local, b"[1, 2, 3]")

    rc = orc.main(["--root", str(local), "--self-code", SELF])

    assert rc == orc.EXIT_INCONCLUSIVE
    assert "verdict: UNKNOWN" in capsys.readouterr().out


# ----------------------------------------------------- 4. ASCII output


# Built with chr() so this source file stays 7-bit ASCII.
_CAFE = "caf" + chr(0xE9)
_CJK = chr(0x65E5) + chr(0x672C)
_LONE_SURROGATE = "x" + chr(0xDC80) + "y"


@pytest.mark.parametrize("slug", [_CAFE, _CJK, _LONE_SURROGATE])
def test_render_with_names_is_ascii_only(slug):
    note = orc.Note(digest="ab" * 32, names=(f"2026-11-09-1000-from-{SELF}-{slug}.md",),
                    per_slot={0: orc.STATUS_ABSENT}, verdict=orc.STATUS_UNDELIVERED)
    rep = orc.Report(self_code=SELF, slots_configured=1, slots_readable=1,
                     slots_unknown=0, notes=[note], verdict=orc.VERDICT_UNDELIVERED)

    text = orc.render(rep, show_names=True)

    assert text.isascii()
    text.encode("cp1252")  # a strict legacy console codec must not raise
    assert f"from-{SELF}-" in text


def test_render_without_names_is_unchanged_by_the_escaping(tmp_path):
    """Regression guard: the default render still withholds the name."""
    local, sibs = _make_tree(tmp_path, 1)
    _write(local / orc.INBOX_DIRNAME / f"2026-11-09-1000-from-{SELF}-{_CAFE}.md", "c\n")
    text = orc.render(_check(local, sibs), show_names=False)
    assert "caf" not in text
    assert text.isascii()
