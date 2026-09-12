"""Tests for ``tools/outbound_reciprocity_check.py`` - RC's outbound delivery check.

THE ONE RULE THIS FILE MUST NEVER BREAK
---------------------------------------
**No sibling literal may appear in this file**, for the same reason
``tests/test_sibling_name_sweep.py`` carries the rule: this repo is PUBLIC and
``ops/moon_sync_repos.json`` is gitignored per-host config - the only artifact
resolving a counterparty CODE to a real project name and a real checkout path.
Every fixture below is a SYNTHETIC tree built at run time under ``tmp_path``
with invented names (``slot0``, ``sibling-alpha``); they resolve to nothing.

THE DEFECT UNDER TEST
---------------------
Measured in a sibling tree 2026-09-12: seven outbound notes written over two
days reached ZERO recipients. They sat in the SENDER'S OWN ``moon_sync_inbox/``
and were never copied anywhere. The watcher classifies by FILENAME, so a
``from-<SELF>`` prefix made each look outbound and answered from the sender's
side while every recipient saw silence - and on this channel silence reads as
dissent. The generalisable root cause is that **a note written into your own
inbox directory is indistinguishable from a note you sent.**

THREE PROPERTIES THE ASSERTIONS BELOW EXIST TO PIN
--------------------------------------------------
1. **The filename is not the evidence.** The whole defect is a name that lied
   about delivery, so delivery is scored on a CONTENT DIGEST. A copy that
   carries the right name and the wrong bytes (renamed, truncated, half-written)
   must score NOT delivered - ``test_same_name_different_content_is_not_delivered``.
2. **Degrade honestly.** An absent, unreadable or unconfigured sibling root is
   UNKNOWN. It is never "delivered" and never "missing", because a false MISSING
   on this channel is as damaging as a missed real one - it accuses a recipient
   of dropping mail that was never sent.
3. **An empty universe must never pass as clean.** This repo's standing rule is
   that an empty enumeration satisfying an assertion is how a guard turns
   silently always-green. ``0 undelivered out of 0 checked`` is reported as
   EMPTY with its own exit code, never as CLEAN -
   ``test_empty_universe_is_empty_never_clean``.

AND THE BOUNDARY: the tool READS a sibling inbox and writes nothing outside this
repository root. That is a standing halt boundary in CLAUDE.md, so it is pinned
twice over - once by a snapshot of the sibling tree taken before and after, and
once by a ``sys.addaudithook`` that records every write-shaped syscall the
process makes during the call. The snapshot alone would miss a lock file created
and removed inside the window; the audit hook alone is easier to get subtly
wrong. Two arms, two failure modes.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import outbound_reciprocity_check as orc  # noqa: E402

SELF = "ZZ"  # synthetic self code; resolves to nothing real
OTHER = "QQ"  # synthetic counterparty code


# --------------------------------------------------------------- fixtures


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def _note(inbox: Path, stamp: str, code: str, slug: str, body: str) -> Path:
    return _write(inbox / f"{stamp}-from-{code}-{slug}.md", body)


def _make_tree(tmp_path: Path, sibling_count: int) -> tuple[Path, list[Path]]:
    """A local repo root plus `sibling_count` sibling roots, each with an inbox."""
    local = tmp_path / "local-repo"
    (local / orc.INBOX_DIRNAME).mkdir(parents=True)
    siblings: list[Path] = []
    for i in range(sibling_count):
        s = tmp_path / f"sibling-{i}"
        (s / orc.INBOX_DIRNAME).mkdir(parents=True)
        siblings.append(s)
    return local, siblings


def _check(local: Path, siblings: list[Path], **kw):
    return orc.check(local, roots=list(siblings), self_code=SELF, **kw)


# ------------------------------------------------------- delivery scoring


def test_note_delivered_to_all_configured_recipients_is_clean(tmp_path):
    local, sibs = _make_tree(tmp_path, 3)
    body = "# From ZZ - broadcast\n\nsame bytes everywhere\n"
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-0900", SELF, "broadcast", body)
    for s in sibs:
        _note(s / orc.INBOX_DIRNAME, "2026-09-12-0900", SELF, "broadcast", body)

    rep = _check(local, sibs)

    assert rep.verdict == orc.VERDICT_CLEAN
    assert rep.notes_checked == 1
    assert rep.undelivered_count == 0
    assert rep.slots_readable == 3
    assert rep.slots_unknown == 0
    note = rep.notes[0]
    assert note.verdict == orc.STATUS_DELIVERED
    assert note.reach == 3
    assert set(note.per_slot.values()) == {orc.STATUS_DELIVERED}


def test_note_delivered_to_none_is_undelivered(tmp_path):
    """The measured defect, reproduced: authored, in the sender's own inbox,
    zero copies anywhere. Seven of these went unnoticed for two days."""
    local, sibs = _make_tree(tmp_path, 3)
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-1000", SELF, "stranded",
          "# From ZZ - never left the tree\n")

    rep = _check(local, sibs)

    assert rep.verdict == orc.VERDICT_UNDELIVERED
    assert rep.notes_checked == 1
    assert rep.undelivered_count == 1
    note = rep.notes[0]
    assert note.verdict == orc.STATUS_UNDELIVERED
    assert note.reach == 0
    assert note.in_local is True
    assert set(note.per_slot.values()) == {orc.STATUS_ABSENT}
    assert orc.exit_code(rep) == orc.EXIT_UNDELIVERED


def test_note_delivered_to_some_is_delivered_and_reports_reach(tmp_path):
    """A targeted reply is legitimately a fan-out of one. Reaching SOME
    recipients is DELIVERED - reporting it as a failure would bury the real
    zero-reach notes under noise - but the reach count is carried so a
    broadcast that fell short is still visible to a reader."""
    local, sibs = _make_tree(tmp_path, 3)
    body = "# From ZZ - targeted reply\n"
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-1100", SELF, "targeted", body)
    _note(sibs[1] / orc.INBOX_DIRNAME, "2026-09-12-1100", SELF, "targeted", body)

    rep = _check(local, sibs)

    assert rep.verdict == orc.VERDICT_CLEAN
    assert rep.undelivered_count == 0
    note = rep.notes[0]
    assert note.verdict == orc.STATUS_DELIVERED
    assert note.reach == 1
    assert note.per_slot[1] == orc.STATUS_DELIVERED
    assert note.per_slot[0] == orc.STATUS_ABSENT
    assert note.per_slot[2] == orc.STATUS_ABSENT
    assert rep.reach_histogram == {1: 1}


def test_same_name_different_content_is_not_delivered(tmp_path):
    """THE FILENAME IS NOT THE EVIDENCE. A copy with the expected name and
    different bytes - a truncated write, a stale revision, an edit in place -
    is NOT the note that was authored, and scoring it as delivered would
    reproduce the exact class of error the tool exists to catch."""
    local, sibs = _make_tree(tmp_path, 2)
    name_stamp, slug = "2026-09-12-1200", "mismatch"
    _note(local / orc.INBOX_DIRNAME, name_stamp, SELF, slug, "# From ZZ - full body\n\nall of it\n")
    _note(sibs[0] / orc.INBOX_DIRNAME, name_stamp, SELF, slug, "# From ZZ - full body\n")  # truncated

    rep = _check(local, sibs)

    note = next(n for n in rep.notes if n.in_local)
    assert note.per_slot[0] == orc.STATUS_NAME_ONLY
    assert note.per_slot[1] == orc.STATUS_ABSENT
    assert note.verdict == orc.STATUS_UNDELIVERED
    assert rep.name_mismatch_count >= 1
    assert rep.verdict == orc.VERDICT_UNDELIVERED


def test_copy_under_underscore_staging_in_a_sibling_is_not_delivery(tmp_path):
    """A `_`-prefixed entry is staging, and every watcher on this channel skips
    it by construction (``tools/rc_facts.py`` ``_inbox_entries``). A note parked
    in a recipient's own staging directory has therefore not been delivered TO
    them - their watcher will never report it - so it must not score as reach."""
    local, sibs = _make_tree(tmp_path, 2)
    body = "# From ZZ - parked in their staging\n"
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-1300", SELF, "parked", body)
    staged = sibs[0] / orc.INBOX_DIRNAME / "_outbox"
    _note(staged, "2026-09-12-1300", SELF, "parked", body)

    rep = _check(local, sibs)

    note = rep.notes[0]
    assert note.reach == 0
    assert note.verdict == orc.STATUS_UNDELIVERED


def test_local_underscore_staging_counts_as_authored_but_not_as_sent(tmp_path):
    """A draft the sender staged locally is exactly the population the defect
    hid in. It belongs in the universe; it is not evidence of delivery."""
    local, sibs = _make_tree(tmp_path, 2)
    _note(local / orc.INBOX_DIRNAME / "_sent", "2026-09-12-1400", SELF, "kept-copy",
          "# From ZZ - kept copy only\n")

    rep = _check(local, sibs)

    assert rep.notes_checked == 1
    assert rep.undelivered_count == 1
    assert rep.notes[0].in_local is True


def test_directory_payload_is_one_entry_keyed_by_content(tmp_path):
    """Verbatim source arrives as a DIRECTORY drop. It is one unit of mail, and
    its identity is the contents, so a payload that grows is not silently equal
    to the one already sent."""
    local, sibs = _make_tree(tmp_path, 2)
    for root in (local, sibs[0]):
        d = root / orc.INBOX_DIRNAME / f"from-{SELF}-verbatim"
        _write(d / "a.py", "print(1)\n")
        _write(d / "nested" / "b.py", "print(2)\n")
    # sibling 1 gets a payload that is one file short
    d = sibs[1] / orc.INBOX_DIRNAME / f"from-{SELF}-verbatim"
    _write(d / "a.py", "print(1)\n")

    rep = _check(local, sibs)

    local_note = next(n for n in rep.notes if n.in_local)
    assert local_note.per_slot[0] == orc.STATUS_DELIVERED
    assert local_note.per_slot[1] == orc.STATUS_NAME_ONLY
    assert local_note.verdict == orc.STATUS_DELIVERED
    assert local_note.reach == 1


def test_foreign_authored_notes_are_not_in_the_universe(tmp_path):
    """Inbound mail is not RC's outbound set. Scoring a sibling's note against
    RC's delivery obligation would manufacture undelivered rows out of their
    correspondence."""
    local, sibs = _make_tree(tmp_path, 2)
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-1500", OTHER, "their-note", "# From QQ\n")

    rep = _check(local, sibs)

    assert rep.notes_checked == 0
    assert rep.verdict == orc.VERDICT_EMPTY


# ------------------------------------------------------- honest degradation


def test_missing_sibling_root_is_unknown_never_missing(tmp_path):
    """A configured root that is not on disk tells you NOTHING about delivery.
    Reporting it as missing accuses a recipient of dropping mail; reporting it
    as delivered hides a real loss. It is UNKNOWN, and the note inherits the
    doubt rather than a verdict."""
    local, sibs = _make_tree(tmp_path, 2)
    body = "# From ZZ - one readable recipient\n"
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-1600", SELF, "half-known", body)
    _note(sibs[0] / orc.INBOX_DIRNAME, "2026-09-12-1600", SELF, "half-known", body)
    absent = tmp_path / "sibling-not-on-disk"

    rep = _check(local, [sibs[0], absent])

    assert rep.slots_configured == 2
    assert rep.slots_readable == 1
    assert rep.slots_unknown == 1
    note = rep.notes[0]
    assert note.per_slot[0] == orc.STATUS_DELIVERED
    assert note.per_slot[1] == orc.STATUS_UNKNOWN
    assert note.verdict == orc.STATUS_DELIVERED


def test_root_present_but_inbox_absent_is_unknown(tmp_path):
    local, sibs = _make_tree(tmp_path, 1)
    bare = tmp_path / "sibling-no-inbox"
    bare.mkdir()
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-1700", SELF, "solo", "# From ZZ\n")

    rep = _check(local, [bare])

    assert rep.slots_unknown == 1
    assert rep.slots_readable == 0
    assert rep.notes[0].per_slot[0] == orc.STATUS_UNKNOWN


def test_zero_readable_slots_is_unknown_not_undelivered(tmp_path):
    """With nothing readable to compare against, a stranded note and a
    perfectly delivered one are indistinguishable. Saying UNDELIVERED here
    would be a fabricated finding."""
    local, _ = _make_tree(tmp_path, 0)
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-1800", SELF, "unknowable", "# From ZZ\n")

    rep = orc.check(local, roots=[tmp_path / "nope"], self_code=SELF)

    assert rep.verdict == orc.VERDICT_UNKNOWN
    assert rep.undelivered_count == 0
    assert rep.notes[0].verdict == orc.STATUS_UNKNOWN
    assert orc.exit_code(rep) == orc.EXIT_INCONCLUSIVE


def test_no_configured_siblings_is_unknown_not_clean(tmp_path):
    local, _ = _make_tree(tmp_path, 0)
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-1900", SELF, "lonely", "# From ZZ\n")

    rep = orc.check(local, roots=[], self_code=SELF)

    assert rep.slots_configured == 0
    assert rep.verdict == orc.VERDICT_UNKNOWN
    assert orc.exit_code(rep) == orc.EXIT_INCONCLUSIVE


# ------------------------------------------------------ the empty-set anchor


def test_empty_universe_is_empty_never_clean(tmp_path):
    """THE ANCHOR. Ask whether an EMPTY enumeration would PASS the assertion -
    here it would, and that is precisely how a guard goes silently always-green.
    Zero authored notes is not a clean bill of health, it is an absence of
    evidence, and it reports and exits as its own third state."""
    local, sibs = _make_tree(tmp_path, 3)

    rep = _check(local, sibs)

    assert rep.notes_checked == 0
    assert rep.undelivered_count == 0
    assert rep.verdict == orc.VERDICT_EMPTY
    assert rep.verdict != orc.VERDICT_CLEAN
    assert orc.exit_code(rep) == orc.EXIT_INCONCLUSIVE
    text = orc.render(rep)
    assert "0 undelivered out of 0 checked" in text


def test_clean_report_states_the_denominator(tmp_path):
    """"0 undelivered" is meaningless without N. The rendered line must carry
    the denominator so a reader cannot mistake an empty run for a clean one."""
    local, sibs = _make_tree(tmp_path, 2)
    body = "# From ZZ - delivered\n"
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-2000", SELF, "ok", body)
    for s in sibs:
        _note(s / orc.INBOX_DIRNAME, "2026-09-12-2000", SELF, "ok", body)

    text = orc.render(_check(local, sibs))

    assert "0 undelivered out of 1 checked" in text


# ----------------------------------------------------- the write boundary


def _snapshot(root: Path) -> dict:
    """Every path under `root`, with size and content digest. Catches a create,
    a delete, a truncate and an in-place edit alike."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_dir():
            out[rel] = "<dir>"
        else:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_tool_does_not_mutate_any_sibling_tree(tmp_path):
    local, sibs = _make_tree(tmp_path, 3)
    body = "# From ZZ - boundary\n"
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-2100", SELF, "boundary", body)
    _note(sibs[0] / orc.INBOX_DIRNAME, "2026-09-12-2100", SELF, "boundary", body)
    before = {i: _snapshot(s) for i, s in enumerate(sibs)}

    _check(local, sibs)

    after = {i: _snapshot(s) for i, s in enumerate(sibs)}
    assert after == before
    # The anchor for THIS assertion: an empty snapshot would compare equal to an
    # empty snapshot, so prove the fixture actually had something to protect.
    assert before[0], "fixture produced an empty sibling tree; the comparison proves nothing"


class _WriteAuditor:
    """Records every write-shaped audit event raised while `armed`.

    A ``sys.addaudithook`` hook cannot be removed once installed, so this one is
    written to be inert - a single attribute test - whenever it is not armed.
    """

    WRITE_EVENTS = (
        "os.mkdir", "os.rmdir", "os.remove", "os.unlink", "os.rename",
        "os.replace", "os.link", "os.symlink", "os.truncate", "os.chmod",
        "shutil.copyfile", "shutil.move", "msvcrt.locking",
    )

    def __init__(self) -> None:
        self.armed = False
        self.hits: list[tuple[str, str]] = []

    def __call__(self, event: str, args: tuple) -> None:
        if not self.armed:
            return
        if event == "open":
            path, mode = args[0], args[1]
            if path is None or not mode or not any(c in mode for c in "wxa+"):
                return
            self.hits.append((event, str(path)))
        elif event in self.WRITE_EVENTS:
            for a in args:
                if isinstance(a, (str, bytes, os.PathLike)):
                    self.hits.append((event, str(a)))


_AUDITOR = _WriteAuditor()
sys.addaudithook(_AUDITOR)


def test_tool_performs_no_write_outside_the_repository_root(tmp_path):
    """The standing halt boundary: the tool READS across the boundary and
    writes nothing outside this repository root. Pinned at the syscall, not by
    inspection of the source - a snapshot cannot see a lock file that is created
    and removed inside the call, and that is a write across the boundary too."""
    local, sibs = _make_tree(tmp_path, 3)
    body = "# From ZZ - audited\n"
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-2200", SELF, "audited", body)
    _note(sibs[0] / orc.INBOX_DIRNAME, "2026-09-12-2200", SELF, "audited", body)

    _AUDITOR.hits.clear()
    _AUDITOR.armed = True
    try:
        rep = _check(local, sibs)
        orc.render(rep)
    finally:
        _AUDITOR.armed = False

    outside = [h for h in _AUDITOR.hits if not _is_within(h[1], local)]
    assert outside == [], f"tool wrote outside the repository root: {outside}"
    # Positive control: the hook must actually be capable of seeing a write,
    # otherwise the empty list above proves only that the hook is broken.
    _AUDITOR.hits.clear()
    _AUDITOR.armed = True
    try:
        (tmp_path / "control.txt").write_text("x", encoding="utf-8")
    finally:
        _AUDITOR.armed = False
    assert _AUDITOR.hits, "audit hook recorded nothing for a known write; the arm above is inert"


def _is_within(candidate: str, root: Path) -> bool:
    try:
        Path(candidate).resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


# --------------------------------------------------------- output hygiene


def test_default_render_carries_no_path_and_no_filename(tmp_path):
    """This repo is PUBLIC and the sweep gates every push. The report is meant
    to be pasteable, so it names slots and digests - never a configured path,
    and not even a note filename, since a slug is free text a sender chose."""
    local, sibs = _make_tree(tmp_path, 2)
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-2300", SELF, "some-private-slug",
          "# From ZZ\n")

    text = orc.render(_check(local, sibs))

    assert "some-private-slug" not in text
    for s in sibs:
        assert s.name not in text
        assert str(s) not in text
    assert "slot 0" in text


def test_names_are_shown_only_on_explicit_request(tmp_path):
    local, sibs = _make_tree(tmp_path, 2)
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-2330", SELF, "some-private-slug",
          "# From ZZ\n")

    text = orc.render(_check(local, sibs), show_names=True)

    assert "some-private-slug" in text


# --------------------------------------------------------- config plumbing


def test_roots_come_from_the_gitignored_per_host_config(tmp_path):
    """The roots are per-host CONFIG, never repo content. Same file and same
    keys as ``tools/moon_sync_poller.py`` ``_load_repo_roots``."""
    local, sibs = _make_tree(tmp_path, 2)
    cfg = local / "ops" / "moon_sync_repos.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"repos": [str(s) for s in sibs]}), encoding="utf-8")

    roots = orc.load_sibling_roots(local, env={})

    assert [str(r) for r in roots] == [str(s) for s in sibs]


def test_env_override_wins_over_the_config_file(tmp_path):
    local, sibs = _make_tree(tmp_path, 2)
    cfg = local / "ops" / "moon_sync_repos.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"repos": ["ignored"]}), encoding="utf-8")

    roots = orc.load_sibling_roots(
        local, env={orc.REPOS_ENV: os.pathsep.join(str(s) for s in sibs)})

    assert [str(r) for r in roots] == [str(s) for s in sibs]


def test_absent_config_yields_no_roots_rather_than_a_guess(tmp_path):
    local, _ = _make_tree(tmp_path, 0)
    assert orc.load_sibling_roots(local, env={}) == []


def test_unparseable_config_yields_no_roots(tmp_path):
    local, _ = _make_tree(tmp_path, 0)
    cfg = local / "ops" / "moon_sync_repos.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("{ not json", encoding="utf-8")
    assert orc.load_sibling_roots(local, env={}) == []


def test_no_sibling_literal_is_embedded_in_the_tool_or_this_test():
    """The tool must not spell what it reports on. Both files are checked
    against the live per-host config when there is one; when there is not, the
    assertion is ANCHORED so an absent config cannot pass it silently."""
    cfg_path = REPO_ROOT / "ops" / "moon_sync_repos.json"
    if not cfg_path.exists():
        pytest.skip("no per-host config on this machine; nothing to compare against")
    blob = json.loads(cfg_path.read_text(encoding="utf-8"))
    leaves = set()
    for raw in list(blob.get("repos") or []) + list((blob.get("participants") or {}).values()):
        leaf = Path(str(raw)).name.strip()
        if leaf:
            leaves.add(leaf)
    assert leaves, "config parsed to zero names; the comparison below would be vacuous"
    for path in (REPO_ROOT / "tools" / "outbound_reciprocity_check.py", Path(__file__)):
        text = path.read_text(encoding="utf-8")
        for leaf in leaves:
            for spelling in (leaf, leaf.replace(" ", "-"), leaf.replace(" ", "_"),
                             leaf.replace(" ", "")):
                assert spelling.lower() not in text.lower(), (
                    f"{path.name} embeds a configured sibling name")


# -------------------------------------------------------- grammar probing


@pytest.mark.parametrize(
    "name,expected",
    [
        ("2026-09-12-0900-from-ZZ-slug.md", "ZZ"),
        (f"from-{SELF}-verbatim", "ZZ"),
        ("winmutex.py.from-zz", "ZZ"),
        ("2026-09-12-0900-from-QQ-slug.md", "QQ"),
        ("no-grammar-here.md", None),
        ("fromZZ-missing-hyphen.md", None),
    ],
)
def test_author_code_extraction(name, expected):
    got = orc.author_code(name)
    assert (got.upper() if got else None) == expected


def test_author_match_is_case_insensitive():
    assert orc.is_authored_by("winmutex.py.from-zz", "ZZ") is True
    assert orc.is_authored_by("2026-01-01-0000-from-ZZ-x.md", "zz") is True
    assert orc.is_authored_by("2026-01-01-0000-from-QQ-x.md", "ZZ") is False


# ------------------------------------------------------------------ cli


def test_cli_exits_inconclusive_on_an_empty_universe(tmp_path, capsys):
    local, sibs = _make_tree(tmp_path, 2)
    rc = orc.main([
        "--root", str(local),
        "--self-code", SELF,
        *sum((["--repo", str(s)] for s in sibs), []),
    ])
    assert rc == orc.EXIT_INCONCLUSIVE
    assert "0 undelivered out of 0 checked" in capsys.readouterr().out


def test_cli_exits_undelivered_when_a_note_reached_nobody(tmp_path, capsys):
    local, sibs = _make_tree(tmp_path, 2)
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-2359", SELF, "stranded", "# From ZZ\n")
    rc = orc.main([
        "--root", str(local),
        "--self-code", SELF,
        *sum((["--repo", str(s)] for s in sibs), []),
    ])
    assert rc == orc.EXIT_UNDELIVERED
    assert "UNDELIVERED" in capsys.readouterr().out


def test_cli_json_output_is_machine_readable(tmp_path, capsys):
    local, sibs = _make_tree(tmp_path, 2)
    body = "# From ZZ\n"
    _note(local / orc.INBOX_DIRNAME, "2026-09-12-0800", SELF, "ok", body)
    for s in sibs:
        _note(s / orc.INBOX_DIRNAME, "2026-09-12-0800", SELF, "ok", body)
    rc = orc.main([
        "--root", str(local), "--self-code", SELF, "--json",
        *sum((["--repo", str(s)] for s in sibs), []),
    ])
    blob = json.loads(capsys.readouterr().out)
    assert rc == orc.EXIT_CLEAN
    assert blob["verdict"] == orc.VERDICT_CLEAN
    assert blob["notes_checked"] == 1
    assert blob["undelivered_count"] == 0
    assert blob["slots_readable"] == 2
