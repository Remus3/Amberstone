"""RM-864 (a): `core/log_rotation._move_no_clobber` never overwrites.

As shipped (RM-718 a) it checked `dst.exists()` and then called `os.rename`.
Windows `os.rename` refuses an existing destination, so the check-then-rename
was safe there; POSIX `os.rename` silently REPLACES one, so a file created at
`dst` between the check and the rename was overwritten. recover_orphans() and
try_rotate() rely on the "never overwrites" promise to preserve crash orphans.

The POSIX path is exercised on any host by forcing `_NO_REPLACE_BY_LINK` and
standing in POSIX rename semantics (`os.replace`) for `os.rename`. Every
"race" below creates the destination after the exists() check, inside the
primitive call, which is exactly the window the check cannot close.

Every test works in tmp_path; none touches the live logs/ dir.
"""
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import log_rotation  # noqa: E402

_REAL_LINK = os.link
_REAL_UNLINK = os.unlink


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "a.log.rotating.4242.deadbeef"
    src.write_bytes(b"ORPHAN")
    return src, tmp_path / "a.log.1"


@pytest.fixture
def posix(monkeypatch):
    """POSIX semantics: the link path is selected and os.rename replaces."""
    monkeypatch.setattr(log_rotation, "_NO_REPLACE_BY_LINK", True, raising=False)
    monkeypatch.setattr(log_rotation.os, "rename", os.replace)


def test_default_selects_the_link_path_off_windows_only():
    assert log_rotation._NO_REPLACE_BY_LINK is (os.name != "nt")


def test_a_destination_created_after_the_check_is_never_overwritten(
    tmp_path, monkeypatch, posix
):
    src, dst = _pair(tmp_path)

    def racing_rename(a, b):  # POSIX rename: replaces whatever is at b
        Path(b).write_bytes(b"SQUATTER")
        os.replace(a, b)

    def racing_link(a, b):  # link refuses an existing b on every platform
        Path(b).write_bytes(b"SQUATTER")
        _REAL_LINK(a, b)

    monkeypatch.setattr(log_rotation.os, "rename", racing_rename)
    monkeypatch.setattr(log_rotation.os, "link", racing_link)

    assert log_rotation._move_no_clobber(src, dst) is False
    assert dst.read_bytes() == b"SQUATTER"
    assert src.read_bytes() == b"ORPHAN"


def test_the_link_path_moves_the_file(tmp_path, posix):
    src, dst = _pair(tmp_path)

    assert log_rotation._move_no_clobber(src, dst) is True
    assert not src.exists()
    assert dst.read_bytes() == b"ORPHAN"


def test_the_link_path_refuses_an_existing_destination(tmp_path, posix):
    src, dst = _pair(tmp_path)
    dst.write_bytes(b"ONE")

    assert log_rotation._move_no_clobber(src, dst) is False
    assert dst.read_bytes() == b"ONE"
    assert src.read_bytes() == b"ORPHAN"


def test_a_refused_unlink_of_the_source_undoes_the_link(tmp_path, monkeypatch, posix):
    """Both names would otherwise survive; the next recovery would then copy
    the same orphan again under a fresh recovered name. The link is removed
    and the move reported as not done - the source is where it was."""
    src, dst = _pair(tmp_path)

    def refusing_unlink(p, *a, **kw):
        if Path(p) == src:
            raise PermissionError(13, "held", str(p))
        return _REAL_UNLINK(p, *a, **kw)

    monkeypatch.setattr(log_rotation.os, "unlink", refusing_unlink)

    assert log_rotation._move_no_clobber(src, dst) is False
    assert src.read_bytes() == b"ORPHAN"
    assert not dst.exists()


def test_a_filesystem_without_hard_links_leaves_the_source_in_place(
    tmp_path, monkeypatch, posix
):
    """No fallback to rename: on such a filesystem the orphan keeps its own
    unique scratch name, which recover_orphans() documents as acceptable."""
    src, dst = _pair(tmp_path)

    def no_links(a, b):
        raise OSError(1, "Operation not permitted", str(a))

    monkeypatch.setattr(log_rotation.os, "link", no_links)

    assert log_rotation._move_no_clobber(src, dst) is False
    assert src.read_bytes() == b"ORPHAN"
    assert not dst.exists()


def _fail_final_step(monkeypatch, log: Path, before_raise=None):
    """os.replace that refuses try_rotate's last step (staged -> `.1`)."""
    real_replace = os.replace
    one = log.with_name(log.name + ".1")

    def replace(a, b):
        if Path(b) == one and ".rotating." in Path(a).name:
            if before_raise:
                before_raise()
            raise PermissionError(13, "held", str(a))
        return real_replace(a, b)

    monkeypatch.setattr(log_rotation.os, "replace", replace)


def _contents(tmp_path: Path) -> list[bytes]:
    return sorted(p.read_bytes() for p in tmp_path.iterdir() if p.is_file())


def test_the_roll_back_never_overwrites_a_recreated_base(tmp_path, monkeypatch, posix):
    """A writer recreates the base log while the rotation is in flight; the
    rotation then fails. Rolling `staged -> base` back must not replace the
    new file (verifier finding on the first RM-864 slice: the roll-back used
    plain os.rename, which replaces off Windows)."""
    log = tmp_path / "a.log"
    log.write_bytes(b"BASE")
    (tmp_path / "a.log.1").write_bytes(b"ONE")
    _fail_final_step(monkeypatch, log, lambda: log.write_bytes(b"NEW"))

    assert log_rotation.try_rotate(log, backup_count=2) is not None

    assert log.read_bytes() == b"NEW"
    assert (tmp_path / "a.log.1").read_bytes() == b"ONE"
    staged = sorted(tmp_path.glob("a.log.rotating.*"))
    assert [p.read_bytes() for p in staged] == [b"BASE"]


def test_a_refused_roll_back_step_is_not_overwritten_by_a_later_one(
    tmp_path, monkeypatch, posix
):
    """The first roll-back rename (`.2 -> .1`) is refused, so `.2` still holds
    generation ONE when the next one (`.3 -> .2`) runs. A replacing rename
    would drop ONE; the no-clobber one leaves each file a slot higher."""
    log = tmp_path / "a.log"
    log.write_bytes(b"BASE")
    for i, body in ((1, b"ONE"), (2, b"TWO"), (3, b"THREE")):
        (tmp_path / f"a.log.{i}").write_bytes(body)
    one = tmp_path / "a.log.1"
    _fail_final_step(monkeypatch, log)
    rename, link = log_rotation.os.rename, log_rotation.os.link

    def refuse_onto_one(real):
        def call(a, b):
            if Path(b) == one:
                raise PermissionError(13, "held", str(b))
            return real(a, b)
        return call

    monkeypatch.setattr(log_rotation.os, "rename", refuse_onto_one(rename))
    monkeypatch.setattr(log_rotation.os, "link", refuse_onto_one(link))

    assert log_rotation.try_rotate(log, backup_count=4) is not None

    assert _contents(tmp_path) == sorted([b"BASE", b"ONE", b"TWO", b"THREE"])
    assert log.read_bytes() == b"BASE"
    assert not one.exists()


def test_recovery_under_posix_semantics_keeps_both_files(tmp_path, monkeypatch, posix):
    """End to end: a staged orphan whose `.1` slot is taken between the check
    and the move goes to a recovered name instead; nothing is overwritten."""
    log = tmp_path / "a.log"
    log.write_bytes(b"NEWBASE")
    orphan = tmp_path / "a.log.rotating.4242.deadbeef"
    orphan.write_bytes(b"BASE")
    one = tmp_path / "a.log.1"
    calls = []

    def racing_link(a, b):
        if Path(b) == one and not calls:
            calls.append(b)
            one.write_bytes(b"ONE")
        _REAL_LINK(a, b)

    monkeypatch.setattr(log_rotation.os, "link", racing_link)

    assert log_rotation.recover_orphans(log) == 1
    assert one.read_bytes() == b"ONE"
    recovered = sorted(tmp_path.glob("a.log.recovered-staged.*"))
    assert [p.read_bytes() for p in recovered] == [b"BASE"]
    assert not orphan.exists()
    assert log.read_bytes() == b"NEWBASE"
