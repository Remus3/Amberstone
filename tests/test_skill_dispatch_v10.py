"""FLEET-KIT v10 (MAIN 2026-10-08 0839 ORDER step 4): /done and every skill
that runs tools is dispatched WHOLE to ONE sub-agent; the main session relays
only its final output.

Every slash-command doc carries the same DISPATCH blockquote byte-identical,
and tools/done.md also carries the /done DISPATCH PROTOCOL that says what the
main session hands the executor and what it relays back.

Universe: `tools/*.md` is the TRACKED source of the slash commands;
`.claude/commands/*.md` is a gitignored byte mirror (`tools/drift_guard.py`
MIRROR_PAIRS) that a worktree or a fresh clone does not carry. The command set
is anchored by name (an empty enumeration cannot pass), every tracked doc that
carries the SUBAGENT-FIRST protocol block is swept in (a new skill cannot slip
past), and the mirror, when present, may hold no command outside the set.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TRACKED = _REPO / "tools"
_MIRROR = _REPO / ".claude" / "commands"

# The 23 slash-command docs mirrored into .claude/commands (measured
# 2026-10-08). tools/caveman.md and tools/diagnose.md are FROZEN and are not
# mirrored commands; the other tools/*.md files are reference docs or the CI
# watchdog's headless prompt, not skills.
COMMANDS = (
    "RC2-Continue.md", "directed-headless-upgrade.md", "done.md",
    "game-monitor.md", "headless-ds.md", "headless-gated.md",
    "headless-queue.md", "headless-repo.md", "headless-research.md",
    "headless-true-audit.md", "headless-uiux.md", "headless-upgrade.md",
    "live-gated-drain.md", "orchestrated-run.md", "overlay-build-continue.md",
    "repo-insights.md", "root-cause-fix.md", "section-j-dispatch.md",
    "ship-batch.md", "sync-all-md.md", "test-driven-development.md",
    "test-first-autopilot.md", "weekly-hygiene.md",
)

DISPATCH_BLOCK = "\n".join((
    "> **DISPATCH (FLEET-KIT v10 banner; MAIN 2026-10-08 0839 ORDER step 4).** "
    "In an interactive main session this skill is never run inline.",
    "> 1. The main session dispatches the WHOLE skill to ONE sub-agent (Agent tool): "
    "this file plus the invocation arguments. It relays only that agent's final output "
    "- the line(s) this skill names as its chat output, nothing when it names none - "
    "with no narration around it.",
    "> 2. No quick-read or trivial-edit exception in the main thread; this supersedes "
    "any \"may inline\" line in this file. Its Bash / PowerShell / Read / Edit / Write / "
    "Grep / Glob / NotebookEdit calls meet the kit PreToolUse hook "
    "`ops/fleet_kit/fleet_subagent_first.py` (gitignored mode file "
    "`ops/loop/control/subagent_first.mode`: log first, then deny).",
    "> 3. The dispatched sub-agent, and a headless run (the kit's `spawn()` sets "
    "`FLEET_SUBAGENT_FIRST=off`), execute this skill directly and never re-dispatch "
    "the whole of it.",
))


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _blocks(text: str) -> list[str]:
    """Every blockquote in the doc, as its joined '>' lines."""
    out, cur = [], []
    for line in text.split("\n"):
        if line.startswith(">"):
            cur.append(line)
        elif cur:
            out.append("\n".join(cur))
            cur = []
    if cur:
        out.append("\n".join(cur))
    return out


def test_the_command_set_is_anchored():
    missing = [f for f in COMMANDS if not (_TRACKED / f).is_file()]
    assert not missing, f"tracked command docs missing: {missing}"


def test_every_command_carries_the_dispatch_block_byte_identical():
    bad = [f for f in COMMANDS if DISPATCH_BLOCK not in _blocks(_text(_TRACKED / f))]
    assert not bad, "DISPATCH block missing or edited in tools/: " + ", ".join(bad)


def test_the_block_is_its_own_blockquote_once():
    # A blank line must separate it from the SUBAGENT-FIRST block above it, so
    # that block keeps its own pinned digest (tests/test_skill_probe_recipes.py).
    for f in COMMANDS:
        text = _text(_TRACKED / f)
        assert text.count("> **DISPATCH (FLEET-KIT v10") == 1, f
        assert ("\n" + DISPATCH_BLOCK + "\n\n") in text, f


def test_every_doc_with_the_subagent_first_block_is_a_dispatched_command():
    swept = [p.name for p in sorted(_TRACKED.glob("*.md"))
             if "> **SUBAGENT-FIRST" in _text(p)]
    assert len(swept) >= 21, f"sweep found only {len(swept)} protocol docs"
    stray = [n for n in swept if n not in COMMANDS]
    assert not stray, f"a skill doc outside the dispatched set: {stray}"


def test_the_mirror_holds_no_command_outside_the_set():
    if not _MIRROR.is_dir():
        return  # worktree / fresh clone: the gitignored mirror is absent
    stray = [p.name for p in sorted(_MIRROR.glob("*.md")) if p.name not in COMMANDS]
    assert not stray, f".claude/commands carries an undispatched command: {stray}"


def test_done_md_dispatches_the_whole_ritual_to_one_executor():
    text = _text(_TRACKED / "done.md")
    assert "**/done DISPATCH PROTOCOL (FLEET-KIT v10" in text
    for needle in (
        "The WHOLE ritual - sections 0 through 10 - runs in ONE sub-agent",
        "NOT worktree-isolated",
        "never re-dispatch the whole ritual",
        "Your FINAL message is exactly one line: `Done ritual complete, safe to clear` "
        "or `/done stopped: <reason>`",
        "relay its final line VERBATIM as the only chat output",
        "`/done stopped: done executor returned no final line`",
    ):
        assert needle in text, needle
    # The protocol comes before section 0, so the executor reads it first.
    assert text.index("/done DISPATCH PROTOCOL") < text.index("### 0. Local check gate")


def test_the_docs_stay_ascii_and_lf():
    for f in COMMANDS:
        data = (_TRACKED / f).read_bytes()
        assert b"\r\n" not in data, f
    for f in COMMANDS:
        text = _text(_TRACKED / f)
        start = text.index("> **DISPATCH (FLEET-KIT v10")
        assert text[start:start + len(DISPATCH_BLOCK)].isascii(), f
