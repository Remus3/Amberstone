"""S144-P-273 - a production .py never cites a repo module that no longer exists as if it were live.

A docstring or comment naming ``tools/foo.py`` reads as a pointer to working code. When ``foo.py`` was quarantined or
deleted, the cite stays and sends the next reader hunting (``agents/daemon_slayer/_item_ability_haste.py`` records the
cost: an earlier docstring cited a generator that never existed). Measured 2026-11-06 over the tracked production tree
(tests and the vendored fleet kit excluded): 19 cites of an untracked ``.py`` path in 12 files. Twelve say so in plain
words nearby (quarantined, removed, retired, never existed, ...); that is a history note, not a dangling pointer, and
the guard accepts it. Three were bare and are fixed with this guard (tools/champion_loadout_validate_meta.py,
tools/hotfix_kaisa_aram_ashe_sr_item263.py, tools/champion_loadout_align.py). The rest are the named exceptions below.

S144-P-288 widens the scan to ``.ps1`` / ``.bat`` / ``.sh`` / ``.mjs`` / ``.js`` cites in the same production ``.py``
prose: measured 2026-11-06, two bare cites (both in tools/build_portable.py, PKG-owned, named in ``_ALLOWED``).

S144-P-484 adds ``web`` and ``mc`` to the top dirs and ``.css`` / ``.html`` to the extensions: measured 2026-11-08,
eight production ``.py`` cites of an untracked ``web/`` path (``web/js/dashboard.js``, ``web/js/sim.js``,
``web/mc/mc.js``, ``web/mc/arm_confirm.js``, ``web/js/panels/spike_cue.js``) in four files. Seven sat inside a sentence
that says the file was deleted, quarantined or removed; the eighth (the second ``web/mc/mc.js`` in
dashboard/_arm_confirm.py, eleven lines from its history word) is fixed with this guard. Three more are test inputs
in the agent3 suite and are named in ``_ALLOWED``. A ``.json`` data cite is deliberately not scanned: the end-of-path
lookahead stops ``items_index.json`` reading as ``items_index.js``.
"""
from __future__ import annotations

import re
import subprocess

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_TOP_DIRS = (
    "core|tools|ops|app|lcu|dashboard|coaches|modes|agents|scripts|vision_server|coach_integration|lib|tft|web|mc"
)
_CITE_RE = re.compile(
    rf"(?<![\w./-])((?:{_TOP_DIRS})/[A-Za-z0-9_./-]*[A-Za-z0-9_]\.(?:py|ps1|bat|sh|mjs|js|css|html))(?![\w])"
)
_HISTORY_RE = re.compile(
    r"quarantin|remov|delet|retired|never existed|no longer|\bgone\b|was dropped|deprecat|superseded",
    re.IGNORECASE,
)
_WINDOW = 3
_OUT_OF_SCOPE_PREFIXES = ("tests/", "ops/fleet_kit/", "docs/")

# (file, cited path) -> why it is not a dangling pointer. Only shrinks.
_ALLOWED = {
    # DS package, lane/ds territory (a docstring edit there is a FILING): mirrors the removed summoner-cooldown module.
    ("agents/daemon_slayer/ability_dps.py", "core/summoner_cooldowns.py"),
    # Illustrative placeholder paths inside the citation checker's own docs / the impact selector's examples.
    ("tools/ci_impact_selector.py", "core/x.py"),
    ("tools/ci_impact_selector.py", "tools/y.py"),
    ("tools/citation_audit.py", "tools/x.py"),
    ("tools/citation_audit.py", "core/NOSUCHFILE_zzz.py"),
    # A gitignored runtime artefact the tool writes at run time, not a tracked module.
    ("tools/pseudo_screen_overlay.py", "ops/runtime/ui_recon/recon.py"),
    ("tools/citation_audit.py", "ops/runtime/ui_recon/recon.py"),
    # A file of the other repo this one adopted a helper from (S144-P-287: only the word "sibling" marked it before).
    ("core/ports.py", "tools/lw_ports.py"),
    # S144-P-288: tools/build_portable.py (PKG, main session owns it, so a lane cannot edit the docstring) names two
    # startup scripts that were never tracked. FILED for the PKG owner; drop these when the cites are marked or absent.
    ("tools/build_portable.py", "ops/autostart_on_login.bat"),
    ("tools/build_portable.py", "ops/launch_new_system.bat"),
    # S144-P-484: test inputs. test_round42 feeds ui_applier paths of UI files that no longer exist and asserts each is
    # REJECTED, so the cites are the fixture, not a pointer to working code (the suite lives under agents/, which this
    # scan covers, unlike tests/).
    ("agents/agent3_testing/suite/test_round42.py", "web/js/dashboard.js"),
    ("agents/agent3_testing/suite/test_round42.py", "web/js/sim.js"),
    ("agents/agent3_testing/suite/test_round42.py", "web/js/panels/sub/x.js"),
}


def scan_source(src: str, tracked: frozenset[str]) -> list[tuple[int, str]]:
    """(line, path) of every untracked repo .py cite with no history word within the window."""
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


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    found: set[tuple[str, str]] = set()
    for path in repo_files(patterns=("*.py",)):
        rel = relative_posix(path)
        if rel.startswith(_OUT_OF_SCOPE_PREFIXES) or rel not in tracked:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for _line, cited in scan_source(src, tracked):
            found.add((rel, cited))
    return found


def test_no_bare_cite_of_a_missing_module():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, (
        "cite of a repo .py that is not tracked and carries no history word within "
        f"{_WINDOW} lines (say it was quarantined / removed, or drop the cite): {new}"
    )


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a bare cite - drop them: {stale}"


def test_scanner_is_live():
    tracked = frozenset({"tools/real.py"})
    assert scan_source("see tools/absent.py for the merge\n", tracked) == [(1, "tools/absent.py")]
    assert scan_source("see tools/absent.py\n# it was quarantined in P7.3\n", tracked) == []
    assert scan_source("see tools/real.py\n", tracked) == []
    far = "see tools/absent.py\n" + "x\n" * 4 + "removed\n"
    assert scan_source(far, tracked) == [(1, "tools/absent.py")]
    assert scan_source("see core/a/b/absent_two.py now\n", tracked) == [(1, "core/a/b/absent_two.py")]


def test_non_py_script_cites_are_scanned_too():
    """S144-P-288: a production docstring that names a ``.ps1`` / ``.bat`` / ``.sh`` / ``.mjs`` / ``.js`` script is a
    pointer like a ``.py`` one (tools/build_portable.py cited two startup ``.bat`` files that were never tracked, and
    the ``.py``-only scan never saw them)."""
    tracked = frozenset({"ops/real.ps1"})
    for ext in ("ps1", "bat", "sh", "mjs", "js"):
        assert scan_source(f"run ops/absent.{ext} first\n", tracked) == [(1, f"ops/absent.{ext}")], ext
        assert scan_source(f"run ops/absent.{ext} (removed)\n", tracked) == [], ext
    assert scan_source("run ops/real.ps1 first\n", tracked) == []
    assert scan_source("config tools/data.json here\n", tracked) == []


def test_a_weak_word_does_not_mark_a_cite_as_history():
    """S144-P-287: a word that merely sits near a cite is not a history note. ``history`` (a ``history_notes.md``
    path), ``old``, ``earlier``, ``former``, ``legacy``, ``replaced`` and ``sibling`` each masked a bare cite of a
    missing script in the shared window; only a word that says the file is gone counts."""
    tracked = frozenset({"tools/real.py"})
    for weak in ("history_notes", "the old way", "earlier", "former", "legacy", "replaced by", "sibling repo"):
        assert scan_source(f"see tools/absent.py ({weak})\n", tracked) == [(1, "tools/absent.py")], weak
    for strong in ("quarantined", "removed", "deleted", "retired", "never existed", "no longer", "gone",
                   "was dropped", "deprecated", "superseded"):
        assert scan_source(f"see tools/absent.py ({strong})\n", tracked) == [], strong


def test_web_ui_cites_are_scanned_too():
    """S144-P-484: ``web/`` and ``mc/`` paths are repo top dirs like ``core/``. Production docstrings cite
    ``web/js/...`` and ``web/mc/...`` files (dashboard/_arm_confirm.py, mc/handler.py and agents/agent4_coach_mentor/
    ui_applier.py cite removed ones, each with a history word), and the earlier top-dir list left that whole prefix
    unscanned: a bare cite of a deleted panel module passed."""
    tracked = frozenset({"web/js/main.js", "web/css/panels/base.css", "web/index.html"})
    for cite in ("web/js/panels/absent.js", "web/mc/mc.js", "web/css/panels/absent.css", "web/absent.html", "mc/absent.js"):
        assert scan_source(f"see {cite} for the wiring\n", tracked) == [(1, cite)], cite
        assert scan_source(f"see {cite} (deleted)\n", tracked) == [], cite
    for live in ("web/js/main.js", "web/css/panels/base.css", "web/index.html"):
        assert scan_source(f"see {live} for the wiring\n", tracked) == [], live
    # A data file is not a script cite: web/data/items_index.json must not read as web/data/items_index.js.
    assert scan_source("loads web/data/items_index.json first\n", tracked) == []
