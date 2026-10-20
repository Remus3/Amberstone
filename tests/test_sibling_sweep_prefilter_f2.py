"""F2 (session 124, RM-695 runtime half): the needle arm's SOUND prefilter.

THE FAILURE THIS MODULE PINS
----------------------------
``tests/test_ci_sibling_sweep_tree_wiring.py::test_the_gate_runs_green_on_this_tree``
runs ``tools/sibling_sweep_ci.py`` over the whole tree. MEASURED on Legion at
01e951302 (session 124): 5469 files, ~687 M characters, of which the seven
SMUDGED ``data/daemon_slayer/laning_scenarios/*/*.json`` LFS payloads are
~463 M. ARMED, ``scan_text`` ran ``build_views`` plus 113 compiled regexes over
EVERY window of EVERY blob: ~1.3 s per MB, 84-85 s per 66 MB payload, ~750 s for
the tree - past the suite's 300 s per-test timeout on every run, which then
crashed xdist workers and wedged the loadfile scheduler.

The suspected cause - a harness worktree nested at ``.claude/worktrees/`` - was
REFUTED by measurement: ``.claude/`` is gitignored and the walk is
``git ls-files`` (index + untracked-not-ignored), so the nested tree contributed
zero files. ``test_the_tree_walk_never_descends_into_a_nested_worktree`` pins
that even an UN-ignored nested worktree stays out.

THE FIX, AND WHY IT CANNOT LOSE A FINDING
-----------------------------------------
Exclusion is ruled out (RM-477: windowing, never exclusion). Instead each
window first asks a NECESSARY condition per needle: after deleting every
whitespace character and every comment-continuation prefix character from both
sides, does the window contain the name spelled in some variant family
(case-insensitively, by the same regex engine)? Both views are the raw text
minus a subset of exactly those characters, and every needle shape embeds one
family fragment, so a window that fails the check cannot produce a match in
either view. A needle whose families are not all known gets NO prefilter and
takes the full path - fail-safe, never fail-blind.

No literal of a real sibling appears here: every name below is a SYNTHETIC
placeholder, and the drive prefix is assembled at run time so this file carries
no drive-rooted path for the structural arm to halt on.
"""
from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import sibling_name_sweep as sweep  # noqa: E402

_D = "C:" + "\\"
# Synthetic. Two tokens with an `s` (the long-s re.I trap), one single token,
# and one whose token carries a continuation-prefix character (`-`) that the
# prefilter deletes from both sides.
_NAMES = ["Velsk Quandary", "Brontolith", "Kirn-Vossa"]
_PARTS = {"VQZ": _D + _NAMES[0], "BRZ": _D + _NAMES[1], "KVZ": _D + _NAMES[2]}

_FILLER_LINE = (
    '    {"champion": "Annie", "lane": "mid", "trade": 0.42, "note": '
    '"short trade then back"},  # filler / not a name > 3 * 4 - 1\n'
)


@pytest.fixture()
def cfg(tmp_path: Path):
    root = tmp_path / "fakeroot"
    (root / "ops").mkdir(parents=True)
    (root / "ops" / "moon_sync_repos.json").write_text(
        json.dumps({"repos": list(_PARTS.values()), "participants": _PARTS}),
        encoding="utf-8",
    )
    loaded = sweep.load_config(root=root, env={})
    assert loaded.mode == sweep.MODE_ARMED
    return loaded


@pytest.fixture()
def needles(cfg):
    built = sweep.build_needles(cfg)
    assert len(built) == len(_NAMES)
    return built


def _scan(cfg, needles, text):
    return sweep.scan_text(
        needles, cfg.codes, text, path="probe.txt", source="TEST", status="A"
    )


def _unfiltered(needles):
    return [dataclasses.replace(n, prefilter=None) for n in needles]


def _filler(n_chars: int) -> str:
    reps = n_chars // len(_FILLER_LINE) + 1
    return (_FILLER_LINE * reps)[:n_chars]


# ---------------------------------------------------------------------------
# The red-first reproduction: the cost, made deterministic.
# ---------------------------------------------------------------------------
def test_a_window_no_needle_can_match_never_builds_views(cfg, needles, monkeypatch):
    """The tree is clean, so almost every window is needle-free. Before F2 each
    one still paid `build_views` plus every compiled shape (~1.3 s/MB)."""
    calls = []
    real = sweep.build_views

    def counting(text, at_blob_start=True):
        calls.append(len(text))
        return real(text, at_blob_start=at_blob_start)

    monkeypatch.setattr(sweep, "build_views", counting)
    text = _filler(int(2.5 * sweep.CHUNK_STEP))
    windows = len(list(sweep._scan_windows(text)))
    assert windows >= 3, "the probe must span several windows to mean anything"
    assert _scan(cfg, needles, text) == []
    assert calls == [], f"{len(calls)} of {windows} needle-free windows were normalised"


def test_only_the_window_holding_a_name_is_normalised(cfg, needles, monkeypatch):
    """Non-vacuity anchor for the test above: the filter must still OPEN the
    window that carries a name, and the finding must come out."""
    calls = []
    real = sweep.build_views

    def counting(text, at_blob_start=True):
        calls.append(len(text))
        return real(text, at_blob_start=at_blob_start)

    monkeypatch.setattr(sweep, "build_views", counting)
    text = _filler(int(2.5 * sweep.CHUNK_STEP)) + "\nsee " + _NAMES[1] + " docs\n"
    found = _scan(cfg, needles, text)
    assert [f.slot for f in found] == [1], found
    assert len(calls) == 1, calls


# ---------------------------------------------------------------------------
# Soundness: the filtered path returns EXACTLY what the full path returns.
# ---------------------------------------------------------------------------
_SEPARATORS = {"SPACED": " ", "HYPHEN": "-", "UNDER": "_", "CONCAT": "", "PCT20": "%20"}


def _spellings(name: str):
    toks = name.split()
    out = []
    for sep in _SEPARATORS.values():
        s = sep.join(toks)
        out += [s, s.upper(), s.lower()]
    return out


def _corpus():
    docs = []
    for code, name in zip(_PARTS, _NAMES):
        for s in _spellings(name):
            docs.append(f"prose mentions {s} here.\n")
            docs.append(f"path {_D}{s}\\tools\\x.py\n")
            docs.append(f"url https://github.com/someone/{s}/blob\n")
            docs.append(f"{code}: lives at {s}\n")
            docs.append(f"inside a word x{s}x stays quiet\n")
        half = len(name) // 2
        # P4 split forms: a name wrapped across comment continuation lines.
        docs.append(f"# see {name[:half]}\n#   {name[half:]} for details\n")
        docs.append(f"// {name[:half]}\n// {name[half:]}\n")
        docs.append(f"> {name[:half]}\n> {name[half:]}\n")
        docs.append(f"x = 1  # {_D}{name[:half]}\n# {name[half:]}\\y\n")
        # re.I equivalence traps: long s and the Kelvin sign.
        docs.append("odd " + name.replace("s", "\u017f") + " spelling\n")
        docs.append("odd " + name.replace("K", "\u212a") + " spelling\n")
    docs.append("Kirn-\n# Vossa split on its own hyphen\n")
    return docs


def test_the_prefilter_never_changes_a_finding(cfg, needles):
    full = _unfiltered(needles)
    seen_slots, seen_views, seen_sev = set(), set(), set()
    for doc in _corpus():
        got = _scan(cfg, needles, doc)
        want = _scan(cfg, full, doc)
        assert got == want, doc
        seen_slots |= {f.slot for f in want}
        seen_views |= {f.view for f in want}
        seen_sev |= {f.severity for f in want}
    # Anchors: a corpus that produced nothing would make the equality vacuous.
    assert seen_slots == {0, 1, 2}, seen_slots
    assert seen_views == {sweep.VIEW_SPACE, sweep.VIEW_TIGHT}, seen_views
    assert {sweep.SEV_NAME, sweep.SEV_RESOLUTION} <= seen_sev, seen_sev


def test_the_prefilter_is_exact_across_window_seams(cfg, needles):
    """Names planted on, just before and just after every core seam of a
    multi-window blob, plus one split across a seam by a comment wrap."""
    step = sweep.CHUNK_STEP
    text = list(_filler(3 * step + 5000))
    plants = []
    for seam in (step, 2 * step, 3 * step):
        for delta in (-40, -7, 0, 3, sweep.CHUNK_GUARD - 20):
            plants.append((seam + delta, f" {_NAMES[(seam + delta) % 3]} "))
    plants.append((2 * step - 6, "\n# Velsk Qua\n# ndary\n"))
    for pos, s in sorted(plants, reverse=True):
        text[pos:pos] = list(s)
    blob = "".join(text)
    got = _scan(cfg, needles, blob)
    want = _scan(cfg, _unfiltered(needles), blob)
    assert want, "the seam probe must produce findings to compare"
    assert got == want


# ---------------------------------------------------------------------------
# The premises the soundness argument rests on, each pinned.
# ---------------------------------------------------------------------------
def test_every_family_has_a_prefilter_separator():
    assert set(sweep._FAMILY_SEPARATORS) == set(sweep.VARIANT_FAMILIES)


@pytest.mark.parametrize("name", ["Velsk Quandary", "Brontolith", "A Bc Def", "Kirn-Vossa"])
def test_the_separator_table_matches_the_fragment_construction(name):
    """If a family fragment changes shape, the prefilter literal for it must be
    re-derived. This fails first so the change cannot land silently."""
    toks = [t for t in re.split(r"\s+", name.strip()) if t]
    esc = [re.escape(t) for t in toks]
    frags = sweep._variant_fragments(name)
    for family, sep in sweep._FAMILY_SEPARATORS.items():
        joiner = " ?" if family == "SPACED" else sep
        assert frags[family] == joiner.join(esc), family
        assert re.fullmatch(frags[family], sep.join(toks), re.I), family


def test_every_shape_is_a_prefix_plus_one_family_fragment(needles):
    """Soundness needs every match of every shape to CONTAIN a whole family
    fragment match. True for `prefix + fragment [+ right edge]` with no
    alternation in the prefix; a new shape of another form fails here."""
    for n in needles:
        toks = [t for t in re.split(r"\s+", n.name.strip()) if t]
        tight = "".join(re.escape(t) for t in toks)
        frags = set(n.variants.values()) | {tight}
        for shape in n.patterns:
            pat = shape.regex.pattern
            body = pat[: -len(sweep._RIGHT_EDGE)] if pat.endswith(sweep._RIGHT_EDGE) else pat
            owners = [f for f in frags if f and body.endswith(f)]
            assert owners, (n.slot, shape.shape)
            prefix = body[: -len(max(owners, key=len))]
            assert "|" not in prefix, (n.slot, shape.shape)


def test_build_needles_attaches_a_prefilter_to_every_needle(needles):
    assert all(n.prefilter is not None for n in needles)


def test_an_unknown_family_disables_the_prefilter():
    assert sweep.build_prefilter("Velsk Quandary", {"SPACED": "x", "NEWFAM": "y"}) is None


def test_a_name_made_only_of_deleted_characters_disables_the_prefilter():
    assert sweep.build_prefilter("-- #", {"SPACED": "x"}) is None


def test_backslash_s_is_exactly_str_isspace():
    """The views collapse `str.isspace()` runs; the prefilter deletes `\\s`.
    Equal sets make the deletion exact."""
    every = "".join(chr(c) for c in range(0x110000))
    by_regex = set(re.findall(r"\s", every))
    by_method = {ch for ch in every if ch.isspace()}
    assert by_regex == by_method


def test_no_other_character_case_folds_onto_a_deleted_one():
    """re.I could otherwise let a letter in the text stand for a deleted
    character in the pattern, and the deletion would desynchronise."""
    every = "".join(chr(c) for c in range(0x110000))
    deleted = {ch for ch in every if ch.isspace()} | set(sweep._CONT_PREFIX)
    for ch in deleted:
        assert re.findall(re.escape(ch), every, re.I) == [ch], hex(ord(ch))


# ---------------------------------------------------------------------------
# The refuted hypothesis, pinned so it stays refuted.
# ---------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_the_tree_walk_never_descends_into_a_nested_worktree(tmp_path: Path):
    """A linked worktree under an UNTRACKED, NOT-ignored directory. git lists
    it as one `dir/` entry and never recurses, so none of its files reach the
    scan - the property a filesystem walk (rglob / os.walk) would lose."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@example.invalid")
    (repo / "a.txt").write_text("tracked\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "base")
    (repo / "nested").mkdir()
    _git(repo, "worktree", "add", "-q", "--detach", "nested/wt")
    (repo / "nested" / "wt" / "only_in_worktree.txt").write_text("x\n", encoding="utf-8")
    (repo / "loose.txt").write_text("untracked\n", encoding="utf-8")
    try:
        stats = sweep.ScanStats()
        paths = {b.path for b in sweep.iter_tree_blobs(repo, stats)}
        assert paths == {"a.txt", "loose.txt"}, paths
    finally:
        _git(repo, "worktree", "remove", "--force", "nested/wt")
