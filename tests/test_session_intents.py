# arch: tests for the S3 intent CONSUMER half (halt_save / done_continue) | section=tests | frozen=no
"""S3 - the running session picks a queued intent up at its next safe boundary.

S2 (shipped) is the PRODUCER: POST /api/loop-control ``queue_intent`` writes
``control/INTENT_HALT_SAVE.json`` or ``control/INTENT_DONE_CONTINUE.json`` and,
for halt_save, also raises ``control/STOP``. Nothing consumed those files.

``ops.loop.intents`` is the CONSUMER. Two behaviours carry the whole stage:

1. ``pending()`` answers "is there an operator intent waiting", reading the
   SAME filenames the route writes. The seam is asserted against the route
   module itself rather than against a copied literal, because a divergence
   there is silent: both halves would pass their own tests while the producer
   wrote a file the consumer never looks at.
2. ``consume()`` writes the bootstrap prompt to ``Desktop/NEXT-SESSION.txt``
   with OVERWRITE semantics (operator decision 2026-07-30) and only THEN marks
   the intent consumed. That order is deliberate: a crash between the two steps
   leaves ``consumed: false``, so the retry rewrites the same bytes. The reverse
   order would lose the prompt with no way to ask for it again.

Replay is tested from both directions - a second ``consume()`` and a replayed
idempotency key through the real route - because "must not write twice" is the
acceptance criterion, and a route replay that re-wrote the intent file would
silently resurrect a consumed intent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ops.loop import intents
from dashboard import routes_loop_control as route

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT = "NEXT SESSION\n------------\nTask: finish Mission Control S4.\n"

KEY_A = "a1b2c3d4-0000-4000-8000-000000000001"
KEY_B = "a1b2c3d4-0000-4000-8000-000000000002"


@pytest.fixture
def ctl(tmp_path):
    """An isolated control dir; never the live ops/loop/control."""
    d = tmp_path / "control"
    d.mkdir()
    return d


@pytest.fixture
def home(tmp_path):
    """A fake repo root so the hand-off write never touches the real one.

    Named `home` for history: until 2026-09-06 the target was under the user
    profile. It is now the REPO ROOT, and the artifact is tracked - see
    ops/loop/intents.REPO_ROOT.
    """
    h = tmp_path / "home"
    h.mkdir(parents=True)
    return h


@pytest.fixture
def routed(ctl, monkeypatch):
    """Drive the REAL S2 route against the isolated control dir."""
    monkeypatch.setattr(route, "CONTROL_DIR", ctl)
    from dashboard import _idempotency as idem

    idem.clear()
    return route


def _queue(routed, intent, key):
    status, payload = routed.apply_action(
        "queue_intent", {"intent": intent, "idempotency_key": key})
    assert status == 200, payload
    return payload


# --------------------------------------------------------------------------
# The producer/consumer seam
# --------------------------------------------------------------------------

def test_filenames_match_the_route_not_a_copy():
    """The consumer reads exactly the names the shipped producer writes."""
    assert intents.INTENT_FILES == route._INTENT_FILES


def test_default_control_dir_matches_the_route():
    assert intents.control_dir().resolve() == route.CONTROL_DIR.resolve()


def test_default_next_session_path_matches_the_route():
    assert intents.DEFAULT_NEXT_SESSION_PATH == route.NEXT_SESSION_PATH


# --------------------------------------------------------------------------
# pending()
# --------------------------------------------------------------------------

def test_pending_is_none_when_nothing_queued(ctl):
    assert intents.pending(root=ctl) is None


def test_pending_reads_what_the_route_wrote(routed, ctl):
    _queue(routed, "halt_save", KEY_A)
    doc = intents.pending(root=ctl)
    assert doc is not None
    assert doc["intent"] == "halt_save"
    assert doc["key"] == KEY_A
    assert doc["consumed"] is False


def test_halt_save_outranks_done_continue(routed, ctl):
    _queue(routed, "done_continue", KEY_A)
    _queue(routed, "halt_save", KEY_B)
    assert intents.pending(root=ctl)["intent"] == "halt_save"


def test_consumed_intents_are_invisible(routed, ctl, home):
    _queue(routed, "done_continue", KEY_A)
    assert intents.consume(prompt=PROMPT, root=ctl, base=home)["ok"] is True
    assert intents.pending(root=ctl) is None


def test_unparseable_intent_file_is_skipped_not_raised(ctl):
    (ctl / intents.INTENT_FILES["halt_save"]).write_text("{ not json",
                                                         encoding="utf-8")
    assert intents.pending(root=ctl) is None


# --------------------------------------------------------------------------
# consume() - the Desktop write
# --------------------------------------------------------------------------

def test_consume_writes_the_bootstrap_prompt_to_desktop(routed, ctl, home):
    _queue(routed, "halt_save", KEY_A)
    result = intents.consume(prompt=PROMPT, root=ctl, base=home)
    target = home / "RC-NEXT-SESSION.txt"
    assert result["ok"] is True
    assert result["intent"] == "halt_save"
    assert Path(result["wrote"]) == target
    assert target.read_text(encoding="utf-8") == PROMPT


def test_consume_overwrites_rather_than_accumulating(routed, ctl, home):
    target = home / "RC-NEXT-SESSION.txt"
    target.write_text("PRIOR SESSION PROMPT\n", encoding="utf-8")
    _queue(routed, "halt_save", KEY_A)
    intents.consume(prompt=PROMPT, root=ctl, base=home)
    assert target.read_text(encoding="utf-8") == PROMPT
    siblings = sorted(p.name for p in target.parent.iterdir())
    assert siblings == ["RC-NEXT-SESSION.txt"]


def test_consume_marks_the_intent_file_consumed(routed, ctl, home):
    _queue(routed, "halt_save", KEY_A)
    intents.consume(prompt=PROMPT, root=ctl, base=home)
    doc = json.loads((ctl / intents.INTENT_FILES["halt_save"]).read_text(
        encoding="utf-8"))
    assert doc["consumed"] is True
    assert doc["key"] == KEY_A
    assert doc["consumed_ts"] > 0
    assert doc["next_session_written"].endswith("RC-NEXT-SESSION.txt")


def test_consume_leaves_no_tmp_files(routed, ctl, home):
    _queue(routed, "halt_save", KEY_A)
    intents.consume(prompt=PROMPT, root=ctl, base=home)
    for d in (ctl, home):
        assert [p.name for p in d.glob("*.tmp")] == []


def test_consume_does_not_clear_stop(routed, ctl, home):
    """halt_save raises STOP; consuming the intent must not lower it."""
    _queue(routed, "halt_save", KEY_A)
    assert (ctl / "STOP").exists()
    intents.consume(prompt=PROMPT, root=ctl, base=home)
    assert (ctl / "STOP").exists()


def test_consume_without_a_pending_intent_is_a_refusal(ctl, home):
    result = intents.consume(prompt=PROMPT, root=ctl, base=home)
    assert result == {"ok": False, "reason": "no_pending_intent"}
    assert not (home / "RC-NEXT-SESSION.txt").exists()


def test_consume_rejects_an_empty_prompt(routed, ctl, home):
    _queue(routed, "halt_save", KEY_A)
    with pytest.raises(ValueError):
        intents.consume(prompt="   ", root=ctl, base=home)
    assert not (home / "RC-NEXT-SESSION.txt").exists()
    assert intents.pending(root=ctl) is not None


# --------------------------------------------------------------------------
# Replay - the acceptance criterion
# --------------------------------------------------------------------------

def test_second_consume_writes_nothing(routed, ctl, home):
    _queue(routed, "halt_save", KEY_A)
    intents.consume(prompt=PROMPT, root=ctl, base=home)
    target = home / "RC-NEXT-SESSION.txt"
    before = (target.read_bytes(), target.stat().st_mtime_ns)

    again = intents.consume(prompt="A DIFFERENT PROMPT\n", root=ctl, base=home)

    assert again["ok"] is False
    assert again["reason"] == "already_consumed"
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before


def test_replayed_route_key_does_not_resurrect_a_consumed_intent(routed, ctl,
                                                                 home):
    """The producer replay path must not overwrite a consumed marker."""
    _queue(routed, "halt_save", KEY_A)
    intents.consume(prompt=PROMPT, root=ctl, base=home)
    path = ctl / intents.INTENT_FILES["halt_save"]
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    status, payload = routed.apply_action(
        "queue_intent", {"intent": "halt_save", "idempotency_key": KEY_A})

    assert status == 200
    assert payload.get("replayed") is True
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert intents.pending(root=ctl) is None


def test_a_fresh_key_queues_a_new_intent_after_one_was_consumed(routed, ctl,
                                                                home):
    """A new operator ARM mints a new key and must work again."""
    _queue(routed, "halt_save", KEY_A)
    intents.consume(prompt=PROMPT, root=ctl, base=home)
    _queue(routed, "halt_save", KEY_B)
    doc = intents.pending(root=ctl)
    assert doc is not None and doc["key"] == KEY_B


# --------------------------------------------------------------------------
# next_session_path resolution - a doctored intent file may not escape home
# --------------------------------------------------------------------------

@pytest.mark.parametrize("hostile", [
    "C:\\Windows\\System32\\RC-evil.txt",
    "/etc/RC-passwd",
    "../../RC-evil.txt",
    "Desktop/../../RC-evil.txt",
    "",
    None,
    123,
    # Another repo's namespace. The Desktop is shared with Sibling-A and
    # RM; an RC session may never write their hand-off file, however the intent
    # doc asks. Cross-repo writes are a deliberate operator act.
    "Desktop/LW-NEXT-SESSION.txt",
    "Desktop/RM-NEXT-SESSION.txt",
    "Desktop/NEXT-SESSION.txt",
    "LW-NEXT-SESSION.txt",
])
def test_hostile_next_session_path_falls_back_to_the_default(home, hostile):
    resolved = intents.resolve_next_session_path({"next_session_path": hostile},
                                                 base=home)
    assert resolved == home / "RC-NEXT-SESSION.txt"


def test_relative_next_session_path_is_honoured(home):
    resolved = intents.resolve_next_session_path(
        {"next_session_path": "RC-OTHER.txt"}, base=home)
    assert resolved == home / "RC-OTHER.txt"


def test_the_repo_prefix_namespaces_every_desktop_artifact():
    """Three repos, one Desktop, no collisions."""
    assert intents.REPO_PREFIX == "RC"
    # Repo-root relative since 2026-09-06 - no "Desktop/" segment any more.
    assert intents.DEFAULT_NEXT_SESSION_PATH.startswith("RC-")


def test_consume_writes_only_inside_this_repos_namespace(routed, ctl, home):
    """A doctored intent doc cannot redirect the write at a sibling repo."""
    _queue(routed, "halt_save", KEY_A)
    path = ctl / intents.INTENT_FILES["halt_save"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["next_session_path"] = "Desktop/LW-NEXT-SESSION.txt"
    path.write_text(json.dumps(doc), encoding="utf-8")

    intents.consume(prompt=PROMPT, root=ctl, base=home)

    assert (home / "RC-NEXT-SESSION.txt").read_text(
        encoding="utf-8") == PROMPT
    assert not (home / "Desktop" / "LW-NEXT-SESSION.txt").exists()


def test_a_sibling_repos_handoff_is_left_untouched(routed, ctl, home):
    """A sibling's file survives an RC consume byte for byte.

    Since the 2026-09-06 move each repo writes into its OWN root, so this is no
    longer the collision it was built for - the Desktop shared surface is gone.
    Kept, and pointed at a sibling-named file in the same directory, because the
    property under test is the namespace guard in resolve_next_session_path, not
    the directory layout: a doctored intent doc still must not be able to name
    someone else's file.
    """
    sibling = home / "LW-NEXT-SESSION.txt"
    sibling.write_bytes(b"SIBLING-A SESSION PROMPT\n")
    before = (sibling.read_bytes(), sibling.stat().st_mtime_ns)
    _queue(routed, "halt_save", KEY_A)

    intents.consume(prompt=PROMPT, root=ctl, base=home)

    assert (sibling.read_bytes(), sibling.stat().st_mtime_ns) == before


def test_a_stale_peeked_doc_cannot_clobber_a_fresh_handoff(routed, ctl, home):
    """The caller's snapshot is re-read; a consumed intent stays consumed.

    Found REFUTED by the S3 adversarial pass: every other test calls
    ``consume()`` with ``doc=None``, so ``pending()`` filtered the consumed
    intent out before the guard was ever reached and the guard was unreachable
    in-suite. The real sequence is peek -> (someone consumes) -> consume(peek),
    and without the re-read the mutant returned ok:true and OVERWROTE the
    Desktop hand-off with the stale prompt.
    """
    _queue(routed, "halt_save", KEY_A)
    peeked = intents.pending(root=ctl)
    assert intents.consume(prompt="FIRST\n", root=ctl, base=home)["ok"] is True
    target = home / "RC-NEXT-SESSION.txt"
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    marker_before = (ctl / intents.INTENT_FILES["halt_save"]).read_bytes()

    result = intents.consume(peeked, prompt="SECOND - CLOBBER\n", root=ctl,
                             base=home)

    assert result["ok"] is False
    assert result["reason"] == "already_consumed"
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    assert (ctl / intents.INTENT_FILES["halt_save"]).read_bytes() == marker_before


def test_consume_creates_a_missing_target_dir(routed, ctl, tmp_path):
    """Renamed from ..._missing_desktop_dir 2026-09-06 with the target itself.

    The write still must not require its parent to exist - a fresh clone or a
    worktree can be missing intermediate directories.
    """
    bare = tmp_path / "bare_root" / "nested"
    _queue(routed, "done_continue", KEY_A)
    result = intents.consume(prompt=PROMPT, root=ctl, base=bare)
    assert result["ok"] is True
    assert (bare / "RC-NEXT-SESSION.txt").read_text(
        encoding="utf-8") == PROMPT


# --------------------------------------------------------------------------
# The CLI the done ritual calls
# --------------------------------------------------------------------------

def _cli(*args, env_base, ctl):
    env = dict(os.environ)
    env["RC_INTENT_CONTROL_DIR"] = str(ctl)
    env["RC_INTENT_BASE"] = str(env_base)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "session_intent.py"), *args],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT))
    return proc


def test_cli_peek_reports_no_intent(ctl, home):
    proc = _cli("--peek", env_base=home, ctl=ctl)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["pending"] is None


def test_cli_peek_then_consume_end_to_end(routed, ctl, home, tmp_path):
    _queue(routed, "halt_save", KEY_A)
    peek = _cli("--peek", env_base=home, ctl=ctl)
    assert json.loads(peek.stdout)["pending"]["intent"] == "halt_save"

    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(PROMPT, encoding="utf-8")
    done = _cli("--consume", "--prompt-file", str(prompt_file),
                env_base=home, ctl=ctl)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["ok"] is True
    assert (home / "RC-NEXT-SESSION.txt").read_text(
        encoding="utf-8") == PROMPT


def test_cli_consume_without_intent_exits_nonzero(ctl, home, tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(PROMPT, encoding="utf-8")
    proc = _cli("--consume", "--prompt-file", str(prompt_file),
                env_base=home, ctl=ctl)
    assert proc.returncode != 0
    assert json.loads(proc.stdout)["reason"] == "no_pending_intent"


def test_module_and_cli_are_ascii():
    for rel in ("ops/loop/intents.py", "tools/session_intent.py"):
        raw = (REPO_ROOT / rel).read_bytes()
        assert raw.decode("ascii")


def test_prompt_written_verbatim_including_trailing_newline(routed, ctl, home):
    """The bootstrap prompt is a machine hand-off; do not reflow or strip it."""
    body = "line one\n\n    indented\nlast line no newline"
    _queue(routed, "done_continue", KEY_A)
    intents.consume(prompt=body, root=ctl, base=home)
    assert (home / "RC-NEXT-SESSION.txt").read_text(
        encoding="utf-8") == body


def test_desktop_file_is_byte_exact_and_the_count_is_truthful(routed, ctl,
                                                              home):
    """No CRLF translation, and result['bytes'] equals the file on disk.

    `Path.write_text` opens in text mode; on Windows that turns every LF into
    CRLF. A read_text round-trip translates it back, so an assertion on the
    STRING passes while the byte count in the status line is wrong (measured
    live: 1375 reported, 1395 on disk).
    """
    body = "alpha\nbeta\ngamma\n"
    _queue(routed, "halt_save", KEY_A)
    result = intents.consume(prompt=body, root=ctl, base=home)
    target = home / "RC-NEXT-SESSION.txt"
    assert target.read_bytes() == body.encode("utf-8")
    assert result["bytes"] == target.stat().st_size


def test_consume_is_fast_enough_to_sit_in_a_done_ritual(routed, ctl, home):
    _queue(routed, "halt_save", KEY_A)
    t0 = time.perf_counter()
    intents.consume(prompt=PROMPT, root=ctl, base=home)
    assert time.perf_counter() - t0 < 2.0
