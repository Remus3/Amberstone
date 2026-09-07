"""CI sweeps every tracked source file through the SAME engine the hook uses.

Ported from Sibling-B 2026-09-06, credited. RSC found the shape in its own
tree first: the 7-bit ASCII rule is a CLAUDE.md hard rule, it is enforced in
`.githooks/pre-commit`, and the same CLAUDE.md section says `core.hooksPath` is
local config and IS NOT CLONED. So the rule had no enforcement for anyone who had
not run `scripts/install_hooks.py` - a fresh clone, a CI sandbox, an agent in a
new worktree.

RC's variant of the hole was different and worse in one specific way, measured
2026-09-06 rather than assumed. RC was NOT uncovered: `ci.yml`'s
"authored-source hygiene" step already runs three pytest guards over tracked
content. But those guards define their own narrower banned set
(`tests/test_smart_quote_hygiene.py:61` lists six codepoints) while
`tools/precommit_gate.py._glyph_hits` is a CATCH-ALL over every codepoint > 127.
Two rules enforcing one CLAUDE.md hard rule, disagreeing about what it means -
which is, verbatim, the defect the gate's own docstring at
`tools/precommit_gate.py:152` was written to close after U+00D7 reached the repo
that way on 2026-07-28. It closed it between the gate's two arms and left the
gate-versus-tests divergence open.

This module closes that one by calling the gate engine directly, so there is one
reading of the rule and CI exercises it.

WHY A RATCHET AND NOT A FLAT BAN. Measured when this landed: 50 tracked source
files carry non-ASCII, and they are not all mistakes. `web/` uses arrows and
status glyphs in rendered UI text, `tests/test_replay_roster.py` carries CJK
summoner names as fixture data, and several are deliberate. Flipping the sweep to
blocking would have shipped a red CI and pressured someone into a 50-file
rewrite of user-visible output under time pressure. So the baseline below is
frozen and the guard is a RATCHET: net-new violations fail, and a file that gets
cleaned must be removed from the baseline in the same commit.

The set-equality shape is deliberate and matches
`tests/test_citation_drift_guard_rm171.py`: it fails in BOTH directions, so the
baseline cannot rot into a blanket pass by quietly accumulating, and a fix that
is not recorded is also a failure.

NOT a licence to keep adding. The baseline is debt with a number on it. Two
entries in it are latent bugs rather than styling, and are worth a look by
whoever next touches those files: `ops/phase3_install.ps1` and
`ops/phase3_install_periodic_audit.ps1` carry U+FEFF, a BOM, in a `.ps1` - which
is the exact PowerShell 5.1 hazard the CLAUDE.md dash rule exists for - and
`web/legacy_index.html` carries U+0081, a C1 control character that is almost
certainly mojibake rather than an intended glyph.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

# Source extensions that carry AUTHORED text. Markdown is excluded because
# docs-guards.yml already covers tracked .md on exactly the pushes ci.yml
# declines, and duplicating it here would double-report every doc finding.
_PATTERNS = ("*.py", "*.toml", "*.ini", "*.yml", "*.yaml", "*.json",
             "*.js", "*.sh", "*.ps1", "*.bat", "*.cmd", "*.css",
             "*.html", "*.ahk")

# Frozen 2026-09-06. file -> the non-ASCII codepoints it currently carries.
# Keyed by codepoint rather than by count so that a NEW glyph in an
# already-listed file still fails, while re-wording a line that keeps the same
# glyph does not churn the baseline.
_BASELINE: dict[str, tuple[str, ...]] = {
    ".github/workflows/patch-day-ddragon-sync.yml": ("U+2192", "U+2713", "U+2717"),
    "agents/agent0_gatekeeper/allowed_ops.json": ("U+00A7",),
    "agents/agent0_gatekeeper/target_allowlist.json": ("U+00A7",),
    "agents/agent3_testing/suite/test_round19.py": ("U+2192",),
    "agents/agent3_testing/suite/test_round32.py": ("U+2192",),
    "agents/agent4_coach_mentor/cold_streak_detector.py": ("U+2192",),
    "agents/agent7_context/ui_feedback.py": ("U+00D7", "U+2192"),
    "coaches/adaptation_hint_digest.py": ("U+2192",),
    "coaches/aram_coach.py": ("U+2192", "U+2265", "U+2550"),
    "coaches/arena_coach.py": ("U+2192", "U+2550"),
    "coaches/brawl_coach.py": ("U+2192", "U+2550"),
    "coaches/experimental_builder.py": ("U+2192", "U+2697"),
    "composition_advisor.py": ("U+2192", "U+2717"),
    "core/aftergame_summary.py": ("U+26A0", "U+2713"),
    "dashboard/builders.py": ("U+00B7", "U+2192"),
    "dashboard/routes_adaptive_summoners.py": ("U+00B7",),
    "lib/http/blocklist.json": ("U+00A7",),
    "ops/audit/p2w5_sweep_sliceA.py": (
        "U+00D7", "U+2192", "U+2194", "U+2212", "U+2248", "U+2264", "U+2265",
        "U+2500"),
    "ops/audit/p3c24_b1b_sweep.py": (
        "U+00B7", "U+00D7", "U+00F7", "U+03B1", "U+03B2", "U+2022", "U+2192",
        "U+2212", "U+2248", "U+2260", "U+2264", "U+2265", "U+2713"),
    "ops/phase3_install.ps1": ("U+00A7", "U+FEFF"),
    "ops/phase3_install_periodic_audit.ps1": ("U+FEFF",),
    "scripts/audit_ddragon_items.py": ("U+2192", "U+26A0"),
    "scripts/db_size_monitor.py": ("U+26A0",),
    "scripts/download_aram_icons.py": ("U+2713", "U+2717"),
    "scripts/rebuild_sim_fixtures.py": (
        "U+00B7", "U+00D7", "U+1F525", "U+2191", "U+2192", "U+2193", "U+2212",
        "U+2265", "U+2605", "U+2744"),
    "scripts/retrofill_match_metrics.py": ("U+00B7",),
    "tests/phase2_smoke/test_aram_coach_item_class_peers.py": ("U+2192",),
    "tests/snapshot_panels/fixtures/sr.json": ("U+00B7", "U+2192"),
    "tests/snapshot_panels/fixtures/tft.json": ("U+00B7", "U+2605"),
    "tests/test_last_match_ascii_item427.py": ("U+26A0", "U+2713"),
    "tests/test_replay_roster.py": (
        "U+4E03", "U+4E0D", "U+4F9D", "U+6211", "U+65B9", "U+6771", "U+6811",
        "U+7136", "U+7231"),
    "tft/tft_vision_reader.py": ("U+2550",),
    "tools/preflight.cmd": ("U+2500",),
    "tools/usage-mcp-server.js": ("U+2192", "U+2500"),
    "web/css/panels/header.css": ("U+26A0", "U+2715", "U+27F3"),
    "web/css/panels/input_activity.css": ("U+203A",),
    "web/css/panels/map_state.css": ("U+2212", "U+27E8", "U+27E9"),
    "web/index.html": (
        "U+00B7", "U+00D7", "U+0394", "U+1F507", "U+2191", "U+2192", "U+2193",
        "U+21BB", "U+25BE", "U+2665", "U+2715", "U+2795"),
    "web/js/lib/helpers.js": (
        "U+03A3", "U+2022", "U+2261", "U+25B6", "U+25C9", "U+25E7", "U+265B",
        "U+2697", "U+26A0", "U+2726"),
    "web/js/lib/items_index.js": ("U+2192",),
    "web/js/main.js": (
        "U+00B7", "U+00D7", "U+1F507", "U+1F50A", "U+2190", "U+2191", "U+2192",
        "U+2193", "U+22EF", "U+25B2", "U+25B6", "U+25BA", "U+25BC", "U+2605",
        "U+2665", "U+26A0", "U+2713", "U+2715", "U+2795", "U+2B06", "U+FE0F"),
    "web/js/panels/augment_reco.js": ("U+00B7",),
    "web/js/panels/item_build.js": ("U+00B7", "U+2192", "U+2713"),
    "web/js/panels/last_match.js": ("U+00B7",),
    "web/js/panels/map_state.js": ("U+00B7", "U+26A0", "U+26D4", "U+2713"),
    "web/js/panels/next.js": ("U+00B7", "U+2192", "U+25B6", "U+2713", "U+2717"),
    "web/js/panels/right_now.js": (
        "U+00B7", "U+1F6A8", "U+2022", "U+2192", "U+2212", "U+25B6", "U+25BA",
        "U+25C9", "U+26A0", "U+26A1", "U+26D4", "U+2713", "U+2733"),
    "web/js/panels/team_context.js": ("U+00B7",),
    "web/legacy_index.html": (
        "U+0081", "U+00B7", "U+00D7", "U+1F33F", "U+1F3AF", "U+1F4CA",
        "U+1F4DD", "U+1F6AB", "U+2192", "U+2194", "U+2212", "U+2248", "U+231B",
        "U+2694", "U+26A1", "U+2713", "U+2728", "U+FE0F"),
}


def _gate():
    """The SAME module the git hook runs. Imported by path because tools/ is not
    a package - see tests/test_laning_verdict_flip_retired.py for the pattern."""
    spec = importlib.util.spec_from_file_location(
        "precommit_gate_under_test", _REPO / "tools" / "precommit_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tracked_source() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "--", *_PATTERNS],
        cwd=str(_REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, f"git ls-files failed: {proc.stderr.strip()}"
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def _observed() -> dict[str, tuple[str, ...]]:
    gate = _gate()
    out: dict[str, tuple[str, ...]] = {}
    for rel in _tracked_source():
        path = _REPO / rel
        if not path.is_file() or gate._ascii_exempt(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if gate._glyph_hits(text, rel):
            out[rel] = tuple(sorted({f"U+{ord(c):04X}" for c in text if ord(c) > 127}))
    return out


def test_the_sweep_selects_something():
    """RSC's guard, and it is the one most people leave out: a sweep that
    selects nothing passes vacuously and looks identical to a clean tree."""
    files = _tracked_source()
    assert len(files) > 500, (
        f"the sweep selected {len(files)} files; it is meant to cover the whole "
        f"tracked source tree and would pass vacuously at this size. Check "
        f"_PATTERNS and that this ran inside the repo."
    )


def test_the_ds_data_tree_is_exempt_from_the_gate():
    """The gate and the hygiene tests must agree on what is EXTERNAL data.

    `tests/test_smart_quote_hygiene.py` (`_is_external_data`) excludes
    `data/daemon_slayer/**/*.json` as DDragon-derived data RC did not author.
    The gate must exempt the same tree, or one CLAUDE.md hard rule gets two
    readings: that data genuinely carries em-dashes and bullets from upstream,
    so a DS batch re-extracting a patch would have its commit blocked by a gate
    enforcing an authored-content rule against content nobody here authored.
    """
    gate = _gate()
    assert gate._ascii_exempt(
        "data/daemon_slayer/16.15.1/items.json"), (
        "the DS data tree is not exempt in the gate but is excluded by "
        "tests/test_smart_quote_hygiene.py - one rule, two readings, which is "
        "the exact defect tools/precommit_gate.py `_glyph_hits` documents."
    )


def _run_scan(*paths: Path) -> int:
    import sys
    proc = subprocess.run(
        [sys.executable, str(_REPO / "tools" / "precommit_gate.py"),
         "--scan-files", *[str(p) for p in paths]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode


def test_scan_files_refuses_a_banned_glyph(tmp_path: Path):
    bad = tmp_path / "probe.py"
    # Written as an ESCAPE, never as a literal. A literal here would make this
    # very file a banned-glyph hit - it would trip the commit gate it tests, and
    # add itself to the ratchet baseline below. Same reason
    # tests/test_doc_action_ref_hygiene.py builds its incident token by
    # concatenation instead of quoting it.
    bad.write_text('x = "em' + chr(0x2014) + 'dash"\n', encoding="utf-8")
    assert _run_scan(bad) == 1, "--scan-files passed a file containing an em-dash"


def test_scan_files_accepts_clean_ascii(tmp_path: Path):
    """The POSITIVE control, and it is the one that matters.

    A scanner that refuses EVERYTHING passes the refusal test above while being
    catastrophically broken, and the broken version is the one that looks safest.
    Same reasoning as the positive control in tests/test_git_hook_gate_e2e.py.
    """
    good = tmp_path / "probe.py"
    good.write_text('x = "plain ascii - no glyphs"\n', encoding="utf-8")
    assert _run_scan(good) == 0, "--scan-files rejected a clean 7-bit ASCII file"


def test_no_net_new_non_ascii_in_tracked_source():
    """Ratchet, both directions - see the module docstring."""
    observed = _observed()
    new = {f: g for f, g in observed.items() if f not in _BASELINE}
    gone = sorted(f for f in _BASELINE if f not in observed)
    changed = {
        f: (_BASELINE[f], g) for f, g in observed.items()
        if f in _BASELINE and g != _BASELINE[f]
    }

    msg = []
    if new:
        msg.append(
            "NET-NEW non-ASCII in tracked source:\n" + "\n".join(
                f"    {f}  {list(g)}" for f, g in sorted(new.items()))
            + "\n  The repo rule is 7-bit ASCII in authored content (CLAUDE.md). "
              "Use ' - ' for a clause break, '->' for an arrow, and a word for a "
              "status glyph. If the file is genuinely external data, exempt it in "
              "tools/precommit_gate.py so the gate and this guard keep ONE reading.")
    if gone:
        msg.append(
            "CLEANED but still in the baseline: " + ", ".join(gone)
            + "\n  Good - now delete those entries from _BASELINE in this same "
              "commit. The baseline is not allowed to rot into a blanket pass.")
    if changed:
        msg.append(
            "CHANGED glyph set in a baselined file:\n" + "\n".join(
                f"    {f}\n      was {list(w)}\n      now {list(n)}"
                for f, (w, n) in sorted(changed.items())))
    assert not msg, "\n\n".join(msg)
