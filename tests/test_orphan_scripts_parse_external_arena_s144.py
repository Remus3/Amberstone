"""Dead-code drift guard: scripts/parse_external_arena.py stays deleted (s144 repo lane).

scripts/parse_external_arena.py was a patch 26.9 (2026-05-03) one-shot that
regex-parsed saved tool-result captures of a third-party Arena stats page into
summary dicts printed to stdout, for a hand-merged Arena build refresh. It was
removed in session 144 because it was dead on two independent facts:

  1. ZERO consumers. No .py / .js / .ps1 / .bat / .json / .yml / .html /
     .xml / CI / scheduled-task reference outside dated history
     (docs/history_notes.md, docs/LEDGER.md, docs/audits/, docs/_archive/).
     The repo review
     filed it as a finished one-shot (B27-02, RM-721); the atlas.html mention
     that review cited is gone too.
  2. Its contract is spent at BOTH ends. Input: session tool-result .txt
     captures that nothing in the tree produces or tracks. Output: JSON on
     stdout whose distinctive keys (champ_url_key, best_duo_1,
     best_duos_summary, recommended_prismatic) occur in no other tracked
     file, so nothing reads what it emits. (Its generic top_duos key is left
     out of that list: unrelated duo-synergy code names top_duos_for_bot /
     top_duos_for_sup, and history prose mentions the word.) The Arena builds it fed were merged by
     scripts/merge_refresh_builds.py from refresh files, not from this output.

Its regexes also hard-coded that site's page prose, which a public tree does
not need to carry.

Same shape as tests/test_orphan_scripts_extract_css_panels_s144.py and
tests/test_orphan_scripts_item195.py. If you find yourself adding it back,
first confirm a real consumer exists.
"""
from __future__ import annotations

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix

_DELETED = "scripts/parse_external_arena.py"


def test_parse_external_arena_one_shot_stays_deleted() -> None:
    assert not (REPO_ROOT / _DELETED).exists(), (
        f"{_DELETED} reappeared. It is a spent one-shot with no producer for "
        "its input and no reader for its output. Confirm a real consumer "
        "before restoring it."
    )


def test_no_tracked_text_still_invokes_the_one_shot() -> None:
    """No runnable tracked file may call the deleted script.

    Prose history (docs/, *.md) and tests/ (this guard names the file) are
    out of scope; data/ and web/data/ are bulk game data, not callers.
    *.xml covers the tracked scheduled-task definitions.
    """
    patterns = ("*.py", "*.ps1", "*.bat", "*.cmd", "*.json", "*.yml",
                "*.yaml", "*.js", "*.mjs", "*.html", "*.xml")
    skip = ("tests/", "docs/", "data/", "web/data/")
    scanned = 0
    offenders = []
    for path in iter_repo_files(REPO_ROOT, patterns):
        rel = relative_posix(path)
        if rel.startswith(skip) or "/tests/" in rel:
            continue
        scanned += 1
        raw = path.read_bytes()
        # The tracked scheduled-task XMLs are UTF-16; decode them as such so
        # a reference inside one is not missed.
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
        if "parse_external_arena" in text:
            offenders.append(rel)
    # An empty walk would pass vacuously; the tree holds thousands of these.
    assert scanned > 500, f"walk saw only {scanned} files - the scan is broken"
    assert offenders == [], f"live references to the deleted one-shot: {offenders}"
