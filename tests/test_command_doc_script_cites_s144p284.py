"""S144-P-284 - a tools/*.md command doc never names a repo script that no longer exists as if it were live.

The tools/*.md files are the lane and slash-command prompts a worker obeys verbatim. A bare cite of
``coaches/foo.py`` sends the worker looking for a file that is gone (tools/headless-true-audit.md listed the
deleted ``coaches/tft_pbe_coach.py`` among the "measured readers" of the API key). The sibling guard
test_dangling_py_cite_ratchet_s144p273 covers production ``.py`` and skips ``docs/``; this one covers the command
docs, and also ``.ps1`` / ``.bat`` / ``.sh`` / ``.js`` / ``.mjs`` cites.

Measured 2026-11-06 over the 31 tracked ``tools/*.md``: 13 cites of an untracked script. Eight say so in plain words
nearby (the ADR-012 bridge removal, a file that is gone); that is history, not a dangling pointer, and the scan
accepts it. One was a real dangling cite and is fixed with this guard. The other four (three distinct pairs) are
placeholders or a gitignored scratch path, named in ``_ALLOWED``.

The rule: every cite of an untracked ``<top-dir>/<path>.<ext>`` needs a history word within three lines either side,
or an entry in ``_ALLOWED`` (file, path) with the reason. ``_ALLOWED`` only shrinks (``test_allowlist_is_exact``).
``test_scanner_is_live`` proves the scan reports a bare cite, so an empty enumeration cannot pass for any reason.
"""
from __future__ import annotations

import re
import subprocess

from tests._repo_walk import REPO_ROOT

_TOP_DIRS = (
    "core|tools|ops|app|lcu|dashboard|coaches|modes|agents|scripts|vision_server|coach_integration|lib|tft"
)
_CITE_RE = re.compile(
    rf"(?<![\w./-])((?:{_TOP_DIRS})/[A-Za-z0-9_./-]*[A-Za-z0-9_]\.(?:py|ps1|bat|sh|mjs|js))(?![\w])"
)
_HISTORY_RE = re.compile(
    r"quarantin|remov|delet|retired|never existed|no longer|\bgone\b|was dropped|deprecat|sibling|history|"
    r"superseded|replaced|\bold\b|former|earlier|legacy",
    re.IGNORECASE,
)
_WINDOW = 3

# (file, cited path) -> why it is not a dangling pointer. Only shrinks.
_ALLOWED = {
    # An illustrative command (`python -u tools/x.py --check`) in the RM-817 push-shape note, not a file.
    ("tools/done.md", "tools/x.py"),
    # A placeholder module name in the "record the negatives" instruction, not a file.
    ("tools/headless-true-audit.md", "core/X.py"),
    # A gitignored scratch recon script the UIUX lane may write at run time, not a tracked module.
    ("tools/headless-uiux.md", "ops/runtime/ui_recon/recon.py"),
}


def scan_source(src: str, tracked: frozenset[str]) -> list[tuple[int, str]]:
    """(line, path) of every untracked repo script cite with no history word within the window."""
    lines = src.split("\n")
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        for m in _CITE_RE.finditer(line):
            path = m.group(1)
            if path in tracked:
                continue
            window = "\n".join(lines[max(0, i - _WINDOW): i + _WINDOW + 1])
            if not _HISTORY_RE.search(window):
                hits.append((i + 1, path))
    return hits


def _tracked() -> frozenset[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(line for line in out.split("\n") if line)


def _command_docs(tracked: frozenset[str]) -> list[str]:
    return sorted(p for p in tracked if p.startswith("tools/") and p.count("/") == 1 and p.endswith(".md"))


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    found: set[tuple[str, str]] = set()
    for rel in _command_docs(tracked):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for _line, cited in scan_source(src, tracked):
            found.add((rel, cited))
    return found


def test_command_docs_are_enumerated():
    docs = _command_docs(_tracked())
    assert "tools/headless-repo.md" in docs and "tools/done.md" in docs
    assert len(docs) >= 20


def test_no_bare_cite_of_a_missing_script():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, (
        "command doc cites a repo script that is not tracked and carries no history word within "
        f"{_WINDOW} lines (say it was removed, or drop the cite): {new}"
    )


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a bare cite - drop them: {stale}"


def test_scanner_is_live():
    tracked = frozenset({"tools/real.py"})
    assert scan_source("see coaches/absent.py for the merge\n", tracked) == [(1, "coaches/absent.py")]
    assert scan_source("run tools/absent.ps1 now\n", tracked) == [(1, "tools/absent.ps1")]
    assert scan_source("see tools/absent.py\nit was removed in P7\n", tracked) == []
    assert scan_source("see tools/real.py\n", tracked) == []
    far = "see tools/absent.py\n" + "x\n" * 4 + "removed\n"
    assert scan_source(far, tracked) == [(1, "tools/absent.py")]
