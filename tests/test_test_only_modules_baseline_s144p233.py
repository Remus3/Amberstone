"""RM-1736 - a library module whose only consumers are tests is a NAMED, shrinking set.

Several `core/` modules were written ahead of their wiring (a Match-V5 substitute, a
replay seeker, a highlight clipper, a Mayhem magnitude source). Each is documented and
tested, but nothing in the shipped code imports it, so the next reader cannot tell
"parked on purpose" from "orphaned and rotting" without redoing the grep. That grep
was done by hand in the past (ORPHAN_SUITE_AUDIT, the item-195 / RM-227 script
orphans); this makes it a ratchet.

Rule: every tracked `.py` module under the library packages below must have its module
NAME (a whole-word match of the file stem) in at least one tracked non-test code file
(`.py`, `.ps1`, `.bat`, `.cmd`, `.sh`, `.yml`, `.yaml`, `.toml`) other than itself, or
sit in `_TEST_ONLY_BASELINE`. The match is deliberately loose (a bare word, not an
import statement), so a name collision can only HIDE an unwired module, never invent
one: every baseline row is genuinely unreferenced by shipped code. A new module
that nothing ships a reference to fails `test_no_new_test_only_modules`; a baseline
row that gains a consumer (or is deleted) fails `test_baseline_is_exact` until it is
dropped. The set only shrinks. Documented-as-unwired is a state, not a licence to
delete: removal needs the prove-it-dead bar and the owner row (see the reason per row).

Measured 2026-11-06 at local main plus this lane's commits: 9 modules.
"""
from __future__ import annotations

import re

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_LIBRARY_PACKAGES = (
    "core", "coaches", "modes", "dashboard", "tft", "game_reader", "lcu", "app",
    "lib", "vision_server", "coach_integration",
)
_CODE_PATTERNS = ("*.py", "*.ps1", "*.bat", "*.cmd", "*.sh", "*.yml", "*.yaml", "*.toml")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# module -> why it has no shipped consumer yet. Only shrinks.
_TEST_ONLY_BASELINE = {
    "core/anthropic_client.py": "tracked_anthropic shim; shipped call sites record via cost_tracker directly",
    "core/highlight_reel.py": "RM-639 death-reel clipper; ffmpeg is an external binary the operator installs",
    "core/lcu_mastery.py": "key-free champion mastery for any PUUID via the LCU; consumer not wired",
    "core/mayhem_augment_source.py": "RM-866 Mayhem augment magnitudes from CommunityDragon; surfaces not wired",
    "core/meta_crawl.py": "participant-graph crawler for event-mode stats; kill-switch gated, not scheduled",
    "core/pro_match_index.py": "marked unwired in its own docstring (RM-1732)",
    "core/provider_cascade.py": "marked unwired in its own docstring (RM-1732)",
    "core/replay_seek.py": "second producer of replay_analysis.Timeline; no live caller yet",
    "core/sgp_client.py": "SGP match-history client for event modes (RM-106); no shipped caller yet",
}


def _is_test_code(rel: str) -> bool:
    return (rel.startswith(("tests/", "tools/tests/", "agents/agent3_testing/suite/"))
            or "/tests/" in rel)


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text))


def _unreferenced(modules: list[str], corpus: dict[str, set[str]]) -> list[str]:
    """Modules whose file stem is a word in no OTHER corpus file."""
    out = []
    for mod in modules:
        stem = mod.rsplit("/", 1)[-1][:-3]
        if not any(stem in words for rel, words in corpus.items() if rel != mod):
            out.append(mod)
    return sorted(out)


def _tree() -> tuple[list[str], dict[str, set[str]]]:
    modules: list[str] = []
    corpus: dict[str, set[str]] = {}
    for path in repo_files(REPO_ROOT, _CODE_PATTERNS):
        rel = relative_posix(path)
        if _is_test_code(rel):
            continue
        try:
            corpus[rel] = _words(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if (rel.endswith(".py") and rel.split("/", 1)[0] in _LIBRARY_PACKAGES
                and "/" in rel and not rel.endswith("__init__.py")):
            modules.append(rel)
    assert len(corpus) > 300 and len(modules) > 100, (
        f"the tracked-file walk collapsed ({len(corpus)} files, {len(modules)} modules)")
    return modules, corpus


def test_scanner_reads_a_whole_word_reference_in_another_file_only():
    corpus = {
        "core/a.py": _words("import b_mod\nx = 1"),
        "core/b_mod.py": _words("def f(): pass"),
        "core/c_mod.py": _words("c_mod_helper = 1  # c_mod_x"),
        "app/run.ps1": _words("python -m core.b_mod"),
    }
    mods = ["core/b_mod.py", "core/c_mod.py"]
    # b_mod is named by a.py and run.ps1; c_mod only by itself (and as a prefix of
    # other words, which is not a whole-word hit).
    assert _unreferenced(mods, corpus) == ["core/c_mod.py"]
    # A mention in the module itself does not count.
    corpus["core/c_mod.py"] = _words("c_mod = 1")
    assert _unreferenced(mods, corpus) == ["core/c_mod.py"]


def test_no_new_test_only_modules():
    modules, corpus = _tree()
    extra = sorted(set(_unreferenced(modules, corpus)) - set(_TEST_ONLY_BASELINE))
    assert not extra, (
        "library modules named by no shipped code file (only tests, if anything): "
        f"{extra}. Wire a consumer, or add a row to _TEST_ONLY_BASELINE with the reason.")


def test_baseline_is_exact():
    modules, corpus = _tree()
    found = set(_unreferenced(modules, corpus))
    stale = sorted(set(_TEST_ONLY_BASELINE) - found)
    assert not stale, f"baseline rows that now have a consumer or are gone - drop them: {stale}"
