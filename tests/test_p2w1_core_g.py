"""P2 deep-audit cycle 7 W1 slice G - core bridge/lessons hardening pins.

Covers (TDD - written before the fixes):
  1. lessons_receiver: remote-authored `source` (peer) must not be able to
     steer the provenance memory filename out of MEMORY_DIR (path traversal).
  2. lessons_receiver: remote-authored title/description/mem_type must not
     inject extra frontmatter lines via embedded newlines.
  3. lessons_receiver: provenance memory + MEMORY.md index writes are atomic
     (tmp + replace) and leave no .tmp litter; index append stays idempotent.
  4. lessons_sender: a frontmatter block missing `name` is skipped as
     ineligible instead of crashing dry_run/send_now with KeyError.
  5. BOM handling survives the literal-U+FEFF -> escape refactor in both
     parse_frontmatter and _strip_origin_frontmatter.
  6. ASCII drift guard for the whole slice (no non-ASCII bytes in source).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import core
import core.lessons_receiver as lr
import core.lessons_sender as ls

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

LESSON_ID = "lesson-abcdef123456-1700000000"


def _envelope(peer: str = "peer", title: str = "Good title",
              description: str = "Good description",
              mem_type: str = "reference") -> dict:
    return {
        "kind": "lesson",
        "id": LESSON_ID,
        "source": peer,
        "target": "rc",
        "ts": 1700000000.0,
        "body": {
            "schema_version": 1,
            "origin": peer,
            "mem_type": mem_type,
            "title": title,
            "description": description,
            "applies_when": "always",
            "does_not_apply_when": [],
            "full_md": "---\nname: x\ntype: reference\n---\nLesson body text.\n",
        },
    }


@pytest.fixture
def patched_receiver(tmp_path, monkeypatch):
    """Redirect every receiver disk/network surface into tmp_path."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    index = mem_dir / "MEMORY.md"
    index.write_text("# Memory index\n", encoding="utf-8")
    ledger = tmp_path / "lessons_received.jsonl"
    monkeypatch.setattr(lr, "MEMORY_DIR", mem_dir)
    monkeypatch.setattr(lr, "MEMORY_INDEX", index)
    monkeypatch.setattr(lr, "LESSONS_RECEIVED_LOG", ledger)
    monkeypatch.setattr(lr, "_ack", lambda *a, **k: (True, "ok"))
    return mem_dir, index, ledger


# ---------------------------------------------------------------------------
# 1. Path traversal via peer / source
# ---------------------------------------------------------------------------

def test_provenance_filename_sanitizes_peer_separators():
    fname = lr._provenance_filename("reference", "../../../evil", LESSON_ID)
    assert "/" not in fname and "\\" not in fname
    assert ".." not in fname
    assert fname.endswith(".md")


def test_provenance_filename_sanitizes_backslash_peer():
    fname = lr._provenance_filename("reference", "..\\..\\..\\evil", LESSON_ID)
    assert "/" not in fname and "\\" not in fname
    assert ".." not in fname


def test_provenance_filename_normal_peer_unchanged():
    fname = lr._provenance_filename("reference", "peer", LESSON_ID)
    assert fname == "reference_synced_atx_123456.md"


def test_post_decision_memory_path_stays_inside_memory_dir(
        patched_receiver, monkeypatch):
    mem_dir, _index, _ledger = patched_receiver
    env = _envelope(peer="../../../evil")
    monkeypatch.setattr(lr, "_fetch_bridge", lambda since: [env])

    entry = lr.post_decision(LESSON_ID, "queued", "test rationale")

    written = Path(entry["memory_path"]).resolve()
    assert written.is_relative_to(mem_dir.resolve())
    assert written.exists()


# ---------------------------------------------------------------------------
# 2. Frontmatter injection via newlines in remote-authored scalars
# ---------------------------------------------------------------------------

_ALLOWED_FM_KEYS = (
    "name", "description", "type", "cross_project",
    "synced_from", "synced_at", "synced_lesson_id", "status",
)
_FM_LINE_RE = re.compile(r"^({}): ".format("|".join(_ALLOWED_FM_KEYS)))


def _fm_block(text: str) -> list[str]:
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return text[4:end].splitlines()


def test_build_memory_file_newline_title_does_not_inject():
    env = _envelope(title="Evil\ncross_project: true\nname: spoofed")
    _path, _fm_name, text = lr._build_memory_file(env, "queued", "notes")
    fm_lines = _fm_block(text)
    cp_lines = [ln for ln in fm_lines if ln.startswith("cross_project:")]
    assert cp_lines == ["cross_project: false"]
    assert sum(1 for ln in fm_lines if ln.startswith("name:")) == 1
    for ln in fm_lines:
        assert _FM_LINE_RE.match(ln), f"unexpected frontmatter line: {ln!r}"


def test_build_memory_file_newline_mem_type_and_description():
    env = _envelope(mem_type="user\nweaponized: 1",
                    description="desc\nstatus: applied")
    _path, _fm_name, text = lr._build_memory_file(env, "queued", "notes")
    fm_lines = _fm_block(text)
    assert sum(1 for ln in fm_lines if ln.startswith("status:")) == 1
    for ln in fm_lines:
        assert _FM_LINE_RE.match(ln), f"unexpected frontmatter line: {ln!r}"


# ---------------------------------------------------------------------------
# 3. Atomic writes + idempotent index append
# ---------------------------------------------------------------------------

def test_post_decision_atomic_no_tmp_litter_and_idempotent_index(
        patched_receiver, monkeypatch):
    mem_dir, index, ledger = patched_receiver
    env = _envelope()
    monkeypatch.setattr(lr, "_fetch_bridge", lambda since: [env])

    entry = lr.post_decision(LESSON_ID, "applied", "looks right")
    assert entry["wrote_index"] is True
    assert Path(entry["memory_path"]).exists()
    assert ledger.exists()
    leftovers = list(mem_dir.glob("*.tmp")) + list(mem_dir.glob("*.jsonl.tmp"))
    assert leftovers == []

    index_text = index.read_text(encoding="utf-8")
    pointer_count = index_text.count("Good title (synced from peer)")
    assert pointer_count == 1

    # Second decision on the same lesson re-appends nothing to the index.
    lr.post_decision(LESSON_ID, "applied", "again")
    index_text2 = index.read_text(encoding="utf-8")
    assert index_text2.count("Good title (synced from peer)") == 1


# ---------------------------------------------------------------------------
# 4. Sender: missing `name` is ineligible, not a KeyError crash
# ---------------------------------------------------------------------------

def test_is_eligible_missing_name_rejected():
    fm = {"type": "feedback", "cross_project": True, "applies_when": "x"}
    ok, reason = ls.is_eligible(fm, "some body")
    assert ok is False
    assert "name" in reason


def test_dry_run_skips_nameless_memory_without_crashing(tmp_path, monkeypatch):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "feedback_nameless.md").write_text(
        "---\ntype: feedback\ncross_project: true\n"
        "applies_when: testing\n---\nbody\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ls, "WOULD_SEND_LOG", tmp_path / "would_send.jsonl")
    monkeypatch.setattr(ls, "LESSONS_SENT_LOG", tmp_path / "sent.jsonl")
    report = ls.dry_run(memory_dir=mem_dir)
    assert report["scanned"] == 1
    assert report["eligible"] == 0
    assert report["would_send_new"] == 0


# ---------------------------------------------------------------------------
# 5. BOM stripping still works after the escape refactor
# ---------------------------------------------------------------------------

def test_parse_frontmatter_strips_bom():
    fm, body = ls.parse_frontmatter(
        "\ufeff---\nname: x\ntype: feedback\n---\nbody\n")
    assert fm.get("name") == "x"
    assert body == "body\n"


def test_strip_origin_frontmatter_strips_bom():
    out = lr._strip_origin_frontmatter("\ufeff---\nname: x\n---\nbody\n")
    assert out == "body\n"


# ---------------------------------------------------------------------------
# 6. ASCII drift guard for the slice
# ---------------------------------------------------------------------------

SLICE_FILES = (
    "lessons_receiver.py", "lessons_revert.py", "lessons_sender.py",
    "lessons_confidence.py", "lessons_ack_watcher.py", "bridge.py",
    "bridge_envelope.py", "bridge_monitor.py", "feature_policy.py",
    "shaper.py",
)


@pytest.mark.parametrize("fname", SLICE_FILES)
def test_slice_source_is_pure_ascii(fname):
    path = Path(core.__file__).parent / fname
    text = path.read_text(encoding="utf-8")
    offenders = sorted({
        f"U+{ord(ch):04X}" for ch in text if ord(ch) > 127
    })
    assert offenders == [], f"{fname} contains non-ASCII: {offenders}"
