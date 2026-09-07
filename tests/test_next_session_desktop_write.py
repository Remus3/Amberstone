"""Every /done writes Desktop/RC-NEXT-SESSION.txt, not just the rare ones.

MEASURED 2026-09-06. The Desktop hand-off file was three days stale while every
sibling project's was current the same day:

    RSC-NEXT-SESSION.txt  21:31 today
    LW-NEXT-SESSION.txt   20:47 today
    CS-NEXT-SESSION.txt   19:57 today
    LL-NEXT-SESSION.txt   17:55 today
    RC-NEXT-SESSION.txt   Sep 3            <- three days

The cause was structural, not a broken write. `tools/done.md` section 10 makes
the next-session prompt MANDATORY, but it only PRINTS it. The one line that
writes the Desktop file lives in section 10b, whose heading gates the whole
section: "only when section 0 found one pending". `intents.consume()` is the
sole writer and it returns `no_pending_intent` when nothing is queued - a
refusal, correctly, since consuming an intent that does not exist would be
wrong. So an ordinary /done printed the prompt into chat and never touched the
file. The stale copy's own header says it was written "by lane 5", a headless
lane that went through the intent path; interactive sessions never did.

The fix separates two things that were conflated: WRITING the hand-off (always)
and CONSUMING a queued intent (only when one is pending). `write_prompt()` does
the first without the second.

Deliberately reusing `resolve_next_session_path` and `_awrite` rather than
opening the path directly. The Desktop is SHARED between five projects and the
namespacing rule - RC- prefix, no absolute paths, no `..` - is exactly the kind
of rule that rots when a second caller re-implements it. One reading, two
callers. That is the same lesson this repo learned tonight from the gate and its
hygiene guards disagreeing about one CLAUDE.md rule.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _intents():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "intents_under_test", _REPO / "ops" / "loop" / "intents.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_write_prompt_exists_and_needs_no_pending_intent(tmp_path: Path):
    """The whole point: it must work on an ordinary /done, with nothing queued."""
    intents = _intents()
    assert hasattr(intents, "write_prompt"), (
        "ops/loop/intents.py has no write_prompt(). Without it the only writer "
        "of the Desktop hand-off is consume(), which refuses when no intent is "
        "pending - which is the normal state at the end of a session.")
    res = intents.write_prompt(prompt="NEXT SESSION\nTask: x\n", base=tmp_path)
    assert res["ok"] is True, res
    target = tmp_path / "RC-NEXT-SESSION.txt"
    assert target.is_file(), f"nothing written to {target}"
    assert target.read_text(encoding="utf-8").startswith("NEXT SESSION")
    assert res["bytes"] == len(target.read_bytes())


def test_write_prompt_lands_in_this_repos_namespace(tmp_path: Path):
    """The Desktop is shared with four sibling projects. An RC session must
    never write a sibling's file, so the filename is not caller-supplied."""
    intents = _intents()
    intents.write_prompt(prompt="hand-off\n", base=tmp_path)
    written = [p.name for p in tmp_path.iterdir()]
    assert written == [f"{intents.REPO_PREFIX}-NEXT-SESSION.txt"], written


def test_write_prompt_refuses_an_empty_hand_off(tmp_path: Path):
    """An empty file looks exactly like a successful hand-off and silently loses
    the session - same reasoning as consume()'s ValueError."""
    intents = _intents()
    for bad in ("", "   ", "\n"):
        try:
            intents.write_prompt(prompt=bad, base=tmp_path)
        except ValueError:
            continue
        raise AssertionError(f"empty prompt {bad!r} was accepted")
    assert not list(tmp_path.iterdir()), "an empty prompt still created a file"


def test_write_prompt_overwrites_rather_than_accumulates(tmp_path: Path):
    """One well-known filename the operator re-reads, not a pile of dated ones."""
    intents = _intents()
    intents.write_prompt(prompt="first\n", base=tmp_path)
    intents.write_prompt(prompt="second\n", base=tmp_path)
    target = tmp_path / "RC-NEXT-SESSION.txt"
    assert target.read_text(encoding="utf-8") == "second\n"
    assert len(list(tmp_path.iterdir())) == 1


def test_done_ritual_always_writes_the_desktop_file():
    """The guard that would have caught the original defect.

    Section 10 is the ALWAYS section. It must carry the write command itself,
    not defer it to 10b - which is gated on a pending intent and therefore skips
    on an ordinary session.
    """
    done = (_REPO / "tools" / "done.md").read_text(encoding="utf-8")
    start = done.find("### 10. Next-session prompt")
    assert start != -1, "tools/done.md has no section 10 - has it been renamed?"
    end = done.find("#### 10b.", start)
    assert end != -1, "tools/done.md has no section 10b - has it been renamed?"
    always = done[start:end]
    assert "--write-prompt" in always, (
        "tools/done.md section 10 does not invoke the unconditional Desktop "
        "write. If the only writer is section 10b's --consume, the file is "
        "written ONLY when an intent is queued, and an ordinary /done leaves it "
        "stale - which is exactly what happened between 2026-09-03 and "
        "2026-09-06.")


def test_done_ritual_and_its_slash_command_mirror_agree():
    """`.claude/commands/done.md` is the copy the slash command actually loads.

    tools/drift_guard.py MIRROR_PAIRS covers this, but that runs as a separate
    tool; a fix applied to only the tracked half would leave the live prompt
    unchanged and the file still stale.
    """
    mirror = _REPO / ".claude" / "commands" / "done.md"
    if not mirror.is_file():
        return  # gitignored and absent on a fresh clone; drift_guard owns parity
    assert "--write-prompt" in mirror.read_text(encoding="utf-8"), (
        ".claude/commands/done.md is missing the unconditional Desktop write "
        "that tools/done.md carries. The slash command loads THIS copy.")


def test_the_stale_docstring_names_the_prefixed_file():
    """`tools/session_intent.py` said it writes `Desktop/NEXT-SESSION.txt`.

    The implementation always wrote the RC- prefixed path
    (`intents.DEFAULT_NEXT_SESSION_PATH`), so the docstring was merely wrong -
    but it is the first thing a reader sees, and an unprefixed name on a shared
    Desktop reads as a cross-repo collision that does not exist.
    """
    src = (_REPO / "tools" / "session_intent.py").read_text(encoding="utf-8")
    assert not re.search(r"(?<![A-Z-])Desktop/NEXT-SESSION\.txt", src), (
        "tools/session_intent.py still names an unprefixed Desktop/NEXT-SESSION.txt")


def test_the_write_gate_cannot_silently_become_a_no_op():
    """Assert the gate is ACTIVE on this path, not merely that it exits clean.

    Caution from Sibling-E 2026-09-06, credited. CS measured the same
    `precommit_gate` invocation reporting `5 skipped` on ubuntu and `4 skipped`
    on Windows - both GREEN - because its PII checks skip themselves when the
    thing they inspect is not discoverable on that machine. Their conclusion is
    the general one: **a gate that skips its checks reports PASS**, and that is
    indistinguishable from a clean run.

    `_glyph_hits` has exactly that shape: it returns `[]` immediately when
    `_ascii_exempt(path)` matches, before inspecting a single character. So if
    `.txt` were ever added to `_ASCII_EXEMPT_SUFFIXES`, or the hand-off moved
    under an exempt prefix, `write_prompt`'s pre-write gate would keep returning
    "clean" while checking nothing - and the tracked, pushed hand-off would be
    ungated with no signal anywhere.

    This asserts the negative directly rather than inferring it from a pass.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gate_exemption_probe", _REPO / "tools" / "precommit_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)

    assert not gate._ascii_exempt("RC-NEXT-SESSION.txt"), (
        "the hand-off path is EXEMPT from the glyph gate, so write_prompt's "
        "pre-write check inspects nothing and reports clean. Remove the "
        "exemption, or the tracked hand-off is ungated.")

    # And prove it actually fires on that exact path, not just that it is
    # un-exempt - the exemption is one of two ways this could go quiet.
    hits = gate._glyph_hits("an em" + chr(0x2014) + "dash", "RC-NEXT-SESSION.txt")
    assert hits, "the glyph engine returned no hits for a banned glyph"
