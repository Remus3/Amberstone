"""RM-399 - tests for ``tools/sibling_name_sweep.py``, RC's sibling-name sweep.

THE ONE RULE THIS FILE MUST NEVER BREAK
---------------------------------------
**No sibling literal may appear in this file.** The sweep exists because this
repo is PUBLIC and ``ops/moon_sync_repos.json`` is gitignored per-host config -
it is the only artifact resolving a counterparty CODE to a real project name and
a real checkout path. A test that pastes a real name in "to make the assertion
concrete" publishes exactly the byte the gate exists to stop, and it publishes
it permanently. Every positive control below is therefore CONSTRUCTED AT RUN TIME
from whatever the loader returns, and never spelled out.

The names spelled out literally in this file are SYNTHETIC placeholders invented
for the test (``_SYNTH_*``, ``_SENTINEL_*``). They resolve to nothing.

WHY THE POSITIVE CONTROLS LOOK THE WAY THEY DO
----------------------------------------------
P1-P5 are the five shapes that were MEASURED as real escapes in this tree before
the sweep existed, restated as SHAPES rather than as the strings that leaked. P4
is the load-bearing one: a name split across a wrapped comment line, invisible to
any contiguous search. Every whole-token search is a claim about CONTIGUITY, not
about presence, so a sweep that has never been run against a split form is not
evidence of anything. The remaining families are synthesised for shapes that have
not been observed here yet.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# A HARD import, deliberately. `pytest.importorskip` here would turn "the guard
# does not exist" into a green run, which is the same vacuity ADR-015 exists to
# stop: an absent sweep and a clean tree must never produce the same verdict.
from tools import sibling_name_sweep as sweep  # noqa: E402


# --------------------------------------------------------------------------
# Synthetic configs. Two disjoint sets, deliberately.
#
# _SYNTH_* drives the positive-control arm, so those literals DO appear in this
# file - which is precisely why the guard-guards-itself test must NOT use them.
# _SENTINEL_* appears only inside a control blob built in that one test, so a
# zero-hit assertion over this file under the sentinel config is non-vacuous:
# the same test proves the sentinel needle fires on a blob that contains it.
# --------------------------------------------------------------------------
# The drive prefix is ASSEMBLED rather than spelled, and this is not fussiness:
# a literal `C:\<segment>` anywhere in this file is a live hit for the STRUCTURAL
# arm, so spelling the synthetic paths out makes the gate halt on its own test
# file. Measured: nine structural hits from exactly that. Built at run time the
# strings are identical and the file text carries no drive-rooted path at all.
_D = "C:" + "\\"
_SYNTH_NAMES = ["Zephyr Quarry", "Marble Trench", "Quicksilt", "Flarnwick"]
_SYNTH_REPOS = [_D + n for n in _SYNTH_NAMES]
_SYNTH_PARTICIPANTS = {
    "ZQ": _SYNTH_REPOS[0],
    "MT": _SYNTH_REPOS[1],
    "QS": _SYNTH_REPOS[2],
    "FLK": _SYNTH_REPOS[3],
}
def _sentinel_parts():
    """Sentinel needles are GENERATED, never spelled.

    A literal sentinel name would appear in this file, and the very test that
    uses it asserts this file is clean - so a spelled sentinel makes that test
    fail for a reason that has nothing to do with the defect it guards. Random
    letters cannot collide with either file's bytes, and the same test proves
    the sentinel arm is not vacuous by firing it on a control blob.
    """
    import random
    import string

    def word(n):
        return "".join(random.choice(string.ascii_uppercase) for _ in range(n))

    two = word(1) + word(6).lower() + " " + word(1) + word(6).lower()
    one = word(1) + word(8).lower()
    repos = [_D + two, _D + one]
    participants = {word(2): repos[0], word(3): repos[1]}
    return repos, participants


def _write_config(tmp_path: Path, blob: dict) -> Path:
    root = tmp_path / "fakeroot"
    (root / "ops").mkdir(parents=True, exist_ok=True)
    (root / "ops" / "moon_sync_repos.json").write_text(
        json.dumps(blob), encoding="utf-8"
    )
    return root


@pytest.fixture()
def synth_cfg(tmp_path: Path):
    root = _write_config(
        tmp_path, {"repos": _SYNTH_REPOS, "participants": _SYNTH_PARTICIPANTS}
    )
    return sweep.load_config(root=root, env={})


@pytest.fixture()
def synth_needles(synth_cfg):
    return sweep.build_needles(synth_cfg)


def _hits(cfg, needles, text: str):
    return sweep.scan_text(
        needles, cfg.codes, text, path="probe.txt", source="TEST", status="A"
    )


# --------------------------------------------------------------------------
# Loader + mode classification
# --------------------------------------------------------------------------
def test_armed_when_config_parses_with_paths(synth_cfg):
    assert synth_cfg.mode == sweep.MODE_ARMED
    assert len(synth_cfg.names) == 4
    assert len(synth_cfg.codes) == 4


def test_armed_via_env_override_paths_only(tmp_path: Path):
    root = tmp_path / "noconfig"
    (root / "ops").mkdir(parents=True)
    cfg = sweep.load_config(
        root=root,
        env={"RC_MOON_SYNC_REPOS": os.pathsep.join(_SYNTH_REPOS)},
    )
    assert cfg.mode == sweep.MODE_ARMED
    assert len(cfg.names) == 4
    # An override carries paths ONLY, so S8 has nothing to pair against.
    assert cfg.codes == ()


def test_env_override_survives_a_posix_pathsep_on_a_windows_path_list(
    monkeypatch, tmp_path: Path
):
    """CI-RED regression, run 34538335778 on the ubuntu runner.

    ``os.pathsep`` is ``;`` on Windows and ``:`` on POSIX, and a drive-letter
    path CONTAINS a colon. So the same override string that loads four names on
    Windows severed into eight fragments on Linux, and the leading ``C`` of each
    path became a fifth NAME. That is not a cosmetic miscount: a one-character
    needle compiles to ``(?<![A-Za-z0-9])C(?![A-Za-z0-9])``, which matches a
    standalone ``C`` anywhere in the tree and would halt every push.

    Forced here rather than left to the runner, so this case is exercised on
    Windows too - the defect was invisible on the machine that shipped it.
    """
    root = tmp_path / "posixsep"
    (root / "ops").mkdir(parents=True)
    monkeypatch.setattr(os, "pathsep", ":")
    cfg = sweep.load_config(
        root=root, env={"RC_MOON_SYNC_REPOS": ":".join(_SYNTH_REPOS)}
    )
    assert cfg.mode == sweep.MODE_ARMED
    assert len(cfg.names) == 4, cfg.names
    assert "C" not in cfg.names, cfg.names


def test_split_repo_list_rejoins_a_severed_drive_letter():
    parts = sweep.split_repo_list(":".join(_SYNTH_REPOS), sep=":")
    assert len(parts) == 4, parts
    assert all(p.startswith(_D) for p in parts), parts


def test_split_repo_list_leaves_posix_paths_alone():
    """The repair must not glue an ordinary POSIX list back together."""
    assert sweep.split_repo_list("/srv/one:/srv/two", sep=":") == [
        "/srv/one",
        "/srv/two",
    ]
    assert sweep.split_repo_list("/srv/one:" + _D + "Two", sep=":") == [
        "/srv/one",
        _D + "Two",
    ]


def test_split_repo_list_does_not_repair_on_a_windows_pathsep():
    """With ``;`` as the separator a colon is never a delimiter, so nothing is
    severed and nothing needs rejoining.

    The second assertion is the DISCRIMINATING one. The first cannot fail
    either way - a ``;``-joined Windows list yields no lone-letter fragment, so
    the repair clause never fires on it and a mutant that dropped the
    separator check survives. A lone letter followed by a rooted fragment is
    the only input that tells the two apart.
    """
    assert sweep.split_repo_list(";".join(_SYNTH_REPOS), sep=";") == _SYNTH_REPOS
    assert sweep.split_repo_list("A;\\shared\\x", sep=";") == ["A", "\\shared\\x"]


def test_split_repo_list_does_not_glue_a_lone_letter_to_an_unrooted_fragment():
    """The rooted-fragment requirement, tested on its own.

    Without it ``A:Bee`` glues into one path. That clause is what keeps the
    repair to things that actually look like a severed drive, so it needs a
    case of its own rather than being carried by the drive-letter tests.
    """
    assert sweep.split_repo_list("A:Bee", sep=":") == ["A:", "Bee"]


def test_split_repo_list_accepts_a_windows_shaped_list_on_a_posix_separator():
    """The under-detect hole, found by an adversarial pass on the first fix.

    A Windows-shaped VALUE usually arrives inside a Windows-shaped LIST. Split
    on ``:`` alone, ``<drive>:<pathA>;<drive>:<pathB>`` leaves the first name
    buried mid-fragment and it is NEVER needled - a silent under-detect, which
    is the one direction a leak gate must not fail in.
    """
    parts = sweep.split_repo_list(";".join(_SYNTH_REPOS), sep=":")
    assert parts == _SYNTH_REPOS, parts
    cfg = sweep.config_from_parts(parts, {})
    assert len(cfg.names) == 4, cfg.names


def test_split_repo_list_restores_a_bare_drive_that_lost_its_colon(tmp_path: Path):
    """A lone drive letter must never become a one-character NEEDLE.

    ``C:`` splits to ``["C", ""]`` on a POSIX separator with nothing rooted to
    rejoin it. Handing ``C`` on to the loader compiles a needle that matches a
    standalone ``C`` anywhere in the tree; handing back ``C:`` lets ``_leaf``
    discard it by the bare-drive rule it already has. FAULT is the correct
    verdict for an override that names no project, and it is not a clean one.
    """
    assert sweep.split_repo_list("C:", sep=":") == ["C:"]
    assert sweep._leaf("C:") == ""
    root = tmp_path / "baredrive"
    (root / "ops").mkdir(parents=True)
    cfg = sweep.load_config(root=root, env={"RC_MOON_SYNC_REPOS": "C:"})
    assert cfg.mode == sweep.MODE_FAULT
    assert cfg.names == ()


def test_env_override_accepts_platform_native_paths(tmp_path: Path):
    """The other half: on each host the NATIVE convention must still work.

    The regression test above feeds Windows-shaped values through a POSIX
    separator on purpose. This one feeds whatever this host actually produces,
    so a repair that only worked for drive letters could not pass both.
    """
    root = tmp_path / "native"
    (root / "ops").mkdir(parents=True)
    native = [str(tmp_path / "siblings" / n) for n in _SYNTH_NAMES]
    cfg = sweep.load_config(
        root=root, env={"RC_MOON_SYNC_REPOS": os.pathsep.join(native)}
    )
    assert cfg.mode == sweep.MODE_ARMED
    assert len(cfg.names) == 4, cfg.names
    assert set(cfg.names) == set(_SYNTH_NAMES), cfg.names


def test_degraded_when_config_absent(tmp_path: Path):
    root = tmp_path / "noconfig2"
    (root / "ops").mkdir(parents=True)
    cfg = sweep.load_config(root=root, env={})
    assert cfg.mode == sweep.MODE_DEGRADED
    assert cfg.names == ()


def test_fault_when_config_present_but_unparseable(tmp_path: Path):
    root = tmp_path / "badroot"
    (root / "ops").mkdir(parents=True)
    (root / "ops" / "moon_sync_repos.json").write_text("{not json", encoding="utf-8")
    cfg = sweep.load_config(root=root, env={})
    assert cfg.mode == sweep.MODE_FAULT


def test_fault_when_config_present_with_zero_usable_paths(tmp_path: Path):
    root = _write_config(tmp_path, {"repos": [], "participants": {}})
    cfg = sweep.load_config(root=root, env={})
    assert cfg.mode == sweep.MODE_FAULT


# --------------------------------------------------------------------------
# Anti-vacuity anchors (ADR-015: an empty enumeration must never PASS)
# --------------------------------------------------------------------------
def test_needle_set_is_non_empty(synth_needles):
    assert synth_needles
    sweep.assert_non_vacuous(synth_needles)


def test_every_variant_family_is_non_empty(synth_needles):
    for needle in synth_needles:
        assert set(needle.variants) == set(sweep.VARIANT_FAMILIES)
        for family, fragment in needle.variants.items():
            assert fragment, f"empty variant fragment for {family}"
        assert needle.patterns


def test_assert_non_vacuous_rejects_an_empty_needle_set():
    with pytest.raises(AssertionError):
        sweep.assert_non_vacuous([])


# --------------------------------------------------------------------------
# POSITIVE CONTROLS - the five measured escape shapes, plus synthesised ones.
# Every needle is built from the loaded config; nothing is spelled out.
# --------------------------------------------------------------------------
def test_p1_drive_plus_separator_plus_name(synth_cfg, synth_needles):
    for name in synth_cfg.names:
        blob = "somewhere under C:\\" + name + "\\ops\\loop\\slots.py today"
        assert _hits(synth_cfg, synth_needles, blob), name


def test_p2_code_adjacent_to_a_path_hit_is_higher_severity(synth_cfg, synth_needles):
    code, path = next(iter(synth_cfg.participants.items()))
    name = Path(path.replace("\\", "/")).name
    blob = "counterparty " + code + " lives at C:\\" + name + "\\inbox"
    found = _hits(synth_cfg, synth_needles, blob)
    assert found
    assert any(f.severity == sweep.SEV_RESOLUTION for f in found), (
        "a code sitting next to a path hit publishes the RESOLUTION and must "
        "outrank a bare name hit"
    )


def test_p3_bare_name_in_prose(synth_cfg, synth_needles):
    for name in synth_cfg.names:
        assert _hits(synth_cfg, synth_needles, "we synced with " + name + " today")


def test_p4_name_split_across_a_wrapped_comment_line(synth_cfg, synth_needles):
    """The escape that is invisible to any contiguous search.

    Measured live in this tree: a name broken over a line wrap with a comment
    continuation prefix on the second line. If this test cannot be made to pass
    the sweep is CONTIGUITY-ONLY and the artifact must say so.
    """
    for name in synth_cfg.names:
        tokens = name.split()
        if len(tokens) > 1:
            split = tokens[0] + "\n# " + " ".join(tokens[1:])
        else:
            half = len(name) // 2
            split = name[:half] + "\n# " + name[half:]
        blob = "# the pinned pair is shared with the " + split + " checkout\n"
        assert _hits(synth_cfg, synth_needles, blob), (
            "P4 split form missed for a needle - the sweep is contiguity-only"
        )


def test_p4_split_across_other_continuation_prefixes(synth_cfg, synth_needles):
    name = synth_cfg.names[0]
    tokens = name.split()
    head, tail = (tokens[0], " ".join(tokens[1:])) if len(tokens) > 1 else (
        name[: len(name) // 2],
        name[len(name) // 2:],
    )
    for prefix in ("//", "*", ">", "-", "#"):
        blob = "wrapped " + head + "\n   " + prefix + " " + tail + " end"
        assert _hits(synth_cfg, synth_needles, blob), prefix


def test_p5_hyphen_slug_inside_a_filename_token(synth_cfg, synth_needles):
    for name in synth_cfg.names:
        slug = "-".join(name.split())
        blob = "moon_sync_inbox/from-" + slug + "-verbatim/note.md"
        assert _hits(synth_cfg, synth_needles, blob), name


@pytest.mark.parametrize(
    "builder",
    [
        lambda n: "C:/" + n + "/tools",
        lambda n: "C:\\\\" + n + "\\\\tools",
        lambda n: "C:\\" + n + "/tools",
        lambda n: "c:\\" + n.lower() + "\\tools",
        lambda n: "_".join(n.split()) + "/ops",
        lambda n: "".join(n.split()) + " checkout",
        lambda n: "%20".join(n.split()) + "%20notes",
        lambda n: "https://github.com/some-owner/" + "-".join(n.split()),
        lambda n: "[the sibling](https://github.com/o/" + "-".join(n.split()) + ")",
        lambda n: "```\nC:\\" + n + "\\ops\n```",
        lambda n: "fix(sync): re-pin the shared pair with " + n,
    ],
)
def test_synthesised_shape_families_all_fire(synth_cfg, synth_needles, builder):
    for name in synth_cfg.names:
        assert _hits(synth_cfg, synth_needles, builder(name)), builder(name)


# --------------------------------------------------------------------------
# NEGATIVE CONTROLS - the sweep must be silent on all of these.
#
# A sweep that fires on every push is disabled within a day. Measured on this
# tree: one two-letter code naive-substring-matches 6,184,366 times, and a
# single word of one name hits 13,333 times across 1235 files. Codes are matched
# ONLY as the second half of S8; single words of a multi-word name never.
# --------------------------------------------------------------------------
def test_a_code_alone_in_prose_never_fires(synth_cfg, synth_needles):
    for code in synth_cfg.codes:
        blob = "the " + code + " counterparty replied, and " + code + " agreed"
        assert _hits(synth_cfg, synth_needles, blob) == [], code


def test_individual_words_of_a_multi_word_name_never_fire(synth_cfg, synth_needles):
    multi = [n for n in synth_cfg.names if len(n.split()) > 1]
    assert multi, "fixture must contain a multi-word name or this proves nothing"
    single_word_names = {n.lower() for n in synth_cfg.names if len(n.split()) == 1}
    for name in multi:
        for word in name.split():
            if word.lower() in single_word_names:
                continue
            blob = "a paragraph mentioning " + word + " on its own"
            assert _hits(synth_cfg, synth_needles, blob) == [], word


def test_the_example_config_template_is_clean(synth_cfg, synth_needles):
    """If the sweep reddens on its own shipped template it is unusable."""
    text = (REPO_ROOT / "ops" / "moon_sync_repos.example.json").read_text(
        encoding="utf-8"
    )
    assert _hits(synth_cfg, synth_needles, text) == []
    assert sweep.structural_findings(
        text, path="ops/moon_sync_repos.example.json", source="TEST", status="A"
    ) == []


@pytest.mark.parametrize(
    "blob",
    [
        "C:\\Riot Commander\\tools\\sibling_name_sweep.py",
        "the RC dashboard at https://legion-rc:8888/",
        "https://github.com/some-owner/Riot-Commander",
        "C:\\Riot Games\\League of Legends",
        "C:\\rc-worktrees\\rc-lane-ds",
        "C:\\RC-Agent\\logs",
        "C:\\RC-CIWatchdog\\state.json",
        "C:\\RC-Recordings\\2026-09-09.mkv",
        "C:\\Peer-Bridge\\outbox",
        "C:\\Users\\Administrator\\AppData\\Local",
        "C:\\Program Files\\Git\\bin",
        "C:\\ProgramData\\chocolatey",
        "C:\\Windows\\System32",
        "Sibling-A and Sibling-B re-pinned; Sibling-C is archived",
        "Sibling-E was never a participant",
        "an unquoted -File C:\\Some Repo\\tools\\x.ps1 reads as C:\\Some",
        "ordinary prose about the scheduler and the overlay",
        'the lockfile lives beside the client, cooldown:\\nUse Recall',
    ],
)
def test_known_clean_shapes_never_fire(synth_cfg, synth_needles, blob):
    assert _hits(synth_cfg, synth_needles, blob) == [], blob
    assert sweep.structural_findings(
        blob, path="probe.txt", source="TEST", status="A"
    ) == [], blob


def test_path_shaped_test_fixtures_in_the_tree_are_clean(synth_cfg, synth_needles):
    for rel in ("tests/test_moon_sync_poller.py", "tests/test_lcu_lockfile_log_once.py"):
        target = REPO_ROOT / rel
        if not target.exists():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        assert _hits(synth_cfg, synth_needles, text) == [], rel


# --------------------------------------------------------------------------
# STRUCTURAL ARM - config-free, so it is NOT inert in a fresh clone or in CI.
# --------------------------------------------------------------------------
def test_structural_arm_fires_on_an_unknown_drive_rooted_first_segment():
    found = sweep.structural_findings(
        "see " + _D + "Wholly Unknown Project\\ops for the pin",
        path="probe.txt",
        source="TEST",
        status="A",
    )
    assert found
    assert found[0].shape == sweep.SHAPE_STRUCTURAL


def test_structural_lookbehind_is_load_bearing():
    """Without ``(?<![A-Za-z0-9_])`` this parses as drive ``n:``."""
    blob = 'coach.say("cooldown:\\nUse Recall when low")'
    assert sweep.structural_findings(
        blob, path="probe.txt", source="TEST", status="A"
    ) == []
    assert sweep.STRUCTURAL_RE.pattern.startswith("(?<![A-Za-z0-9_])")


def test_structural_arm_runs_in_degraded_mode(tmp_path: Path):
    root = tmp_path / "degraded"
    (root / "ops").mkdir(parents=True)
    cfg = sweep.load_config(root=root, env={})
    assert cfg.mode == sweep.MODE_DEGRADED
    banner = sweep.mode_banner(cfg)
    assert "proved NOTHING" in banner or "proved nothing" in banner.lower()


# --------------------------------------------------------------------------
# PUSH RANGE RESOLVER
# --------------------------------------------------------------------------
_Z = "0" * 40


def test_ref_deletion_is_skipped_and_is_not_an_error():
    spec = sweep.resolve_push_range(
        f"refs/heads/gone {_Z} refs/heads/gone deadbeef" + "0" * 32,
        "origin",
        have=lambda sha: True,
    )
    assert spec is None


def test_first_push_uses_not_remotes():
    spec = sweep.resolve_push_range(
        f"refs/heads/new {'a' * 40} refs/heads/new {_Z}", "origin", have=lambda s: True
    )
    assert spec is not None
    assert spec.args == ["a" * 40, "--not", "--remotes=origin"]


def test_normal_push_excludes_the_remote_tip():
    spec = sweep.resolve_push_range(
        f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}",
        "origin",
        have=lambda s: True,
    )
    assert spec is not None
    assert spec.args == ["a" * 40, "--not", "b" * 40]


def test_unknown_remote_sha_falls_back_to_scanning_more_not_less():
    spec = sweep.resolve_push_range(
        f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}",
        "origin",
        have=lambda s: False,
    )
    assert spec is not None
    assert spec.args == ["a" * 40, "--not", "--remotes=origin"]


# --------------------------------------------------------------------------
# REPORTER - it must never relocate the leak into a CI log
# --------------------------------------------------------------------------
def test_report_never_prints_a_matched_literal(synth_cfg, synth_needles):
    blob = "C:\\" + synth_cfg.names[0] + "\\ops\\loop\\slots.py"
    findings = _hits(synth_cfg, synth_needles, blob)
    assert findings
    stats = sweep.ScanStats()
    stats.scanned_bytes = len(blob)
    text = sweep.render_report(findings, stats, synth_cfg)
    for name in synth_cfg.names:
        assert name not in text
        assert name.lower() not in text.lower()
    for code in synth_cfg.codes:
        assert f" {code} " not in text
    assert "slot" in text.lower()
    assert "halted" in text.lower()
    assert "LFS upload did not run" in text


def test_report_carries_the_blind_spot_and_bypass_language(synth_cfg, synth_needles):
    findings = _hits(
        synth_cfg, synth_needles, "C:\\" + synth_cfg.names[0] + "\\x"
    )
    stats = sweep.ScanStats()
    stats.scanned_bytes = 40
    stats.binary_blobs = 3
    text = sweep.render_report(findings, stats, synth_cfg)
    assert "3 binary/LFS blobs not content-scanned" in text
    assert "--no-verify" in text
    assert "RC_SIBLING_SWEEP_BYPASS" in text


def test_explain_resolves_one_finding_to_its_literal(synth_cfg, synth_needles):
    blob = "C:\\" + synth_cfg.names[0] + "\\ops"
    findings = _hits(synth_cfg, synth_needles, blob)
    text = sweep.explain_finding(findings, 0)
    assert synth_cfg.names[0] in text


# --------------------------------------------------------------------------
# GUARD GUARDS ITSELF
# --------------------------------------------------------------------------
_GUARD_FILES = (
    "tools/sibling_name_sweep.py",
    "tests/test_sibling_name_sweep.py",
)


def test_the_guard_and_its_test_carry_no_sibling_literal():
    """A future maintainer pasting a real name in "to make it concrete" is the
    failure this catches. Runs against the REAL config when this machine has
    one; otherwise against a sentinel config, with a non-vacuity proof.
    """
    real = sweep.load_config()
    if real.mode == sweep.MODE_ARMED:
        needles = sweep.build_needles(real)
        for rel in _GUARD_FILES:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            found = sweep.scan_text(
                needles, real.codes, text, path=rel, source="SELF", status="M"
            )
            assert found == [], f"{rel} carries a sibling literal"
        return

    # Unarmed here (fresh clone / CI / a worktree without the per-host config).
    # The sentinel arm still proves the matcher is wired and the two files are
    # clean of the sentinel needles - a weaker claim, stated as such.
    sentinel_repos, sentinel_participants = _sentinel_parts()
    cfg = sweep.config_from_parts(sentinel_repos, sentinel_participants)
    needles = sweep.build_needles(cfg)
    control = "C:\\" + cfg.names[0] + "\\ops"
    assert sweep.scan_text(
        needles, cfg.codes, control, path="control", source="SELF", status="A"
    ), "sentinel arm is vacuous"
    for rel in _GUARD_FILES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        assert sweep.scan_text(
            needles, cfg.codes, text, path=rel, source="SELF", status="M"
        ) == [], rel


@pytest.mark.parametrize("rel", _GUARD_FILES + (".githooks/pre-push",))
def test_the_guard_does_not_trip_its_own_structural_arm(rel):
    """The needle arm is not the only way to red-line yourself.

    The structural arm is config-free, so a literal ``C:\\<segment>`` written
    into the guard or its test halts the very push that ships the guard. Nine
    such hits existed in this file on the first pass; the fix was to assemble
    the synthetic drive prefix at run time instead of spelling it.
    """
    text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    found = sweep.structural_findings(text, path=rel, source="SELF", status="M")
    assert found == [], [(f.line, f.literal) for f in found]


def test_a_halting_runs_full_stderr_contains_no_literal(tmp_path: Path, synth_cfg):
    root = _write_config(
        tmp_path, {"repos": _SYNTH_REPOS, "participants": _SYNTH_PARTICIPANTS}
    )
    blob_path = tmp_path / "leak.txt"
    blob_path.write_text(
        "C:\\" + _SYNTH_REPOS[0].split("\\")[-1] + "\\ops\\loop\\slots.py\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "sibling_name_sweep.py"),
            "--scan-file",
            str(blob_path),
            "--config-root",
            str(root),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == sweep.EXIT_HALT, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    for repo in _SYNTH_REPOS:
        leaf = repo.split("\\")[-1]
        assert leaf not in combined
        assert "".join(leaf.split()) not in combined


# --------------------------------------------------------------------------
# EXIT CODES - 2 and 3 must never collapse into one another
# --------------------------------------------------------------------------
def test_exit_codes_are_distinct():
    codes = {
        sweep.EXIT_CLEAN,
        sweep.EXIT_USAGE,
        sweep.EXIT_HALT,
        sweep.EXIT_FAULT,
    }
    assert codes == {0, 1, 2, 3}


def test_usage_error_exits_one():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "sibling_name_sweep.py")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == sweep.EXIT_USAGE


def test_an_argparse_argument_error_exits_one_and_not_two():
    """A MISTYPED FLAG must not alias onto HALT.

    argparse's own default exit for an argument error is 2, and 2 here means
    "sibling-identifying bytes are in this push". The tool's hand-rolled usage
    check (test above) always returned 1; argparse's did not, so a typo and a
    leak produced the same status for anything reading the exit code. Both
    halts are fail-closed - this is about the two codes staying legible.
    """
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "sibling_name_sweep.py"),
            "--no-such-flag",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == sweep.EXIT_USAGE, proc.stdout + proc.stderr
    assert proc.returncode != sweep.EXIT_HALT
    assert "usage error" in (proc.stdout + proc.stderr)


def test_bypass_env_proceeds_but_still_prints_the_report(tmp_path: Path):
    root = _write_config(
        tmp_path, {"repos": _SYNTH_REPOS, "participants": _SYNTH_PARTICIPANTS}
    )
    blob_path = tmp_path / "leak2.txt"
    blob_path.write_text("C:\\" + _SYNTH_REPOS[1].split("\\")[-1] + "\\x\n", "utf-8")
    env = dict(os.environ)
    env["RC_SIBLING_SWEEP_BYPASS"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "sibling_name_sweep.py"),
            "--scan-file",
            str(blob_path),
            "--config-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == sweep.EXIT_CLEAN
    assert "BYPASS" in (proc.stdout + proc.stderr)


# --------------------------------------------------------------------------
# ANTI-VACUITY ANCHOR - a non-empty push that scanned ZERO bytes is a FAULT
#
# This is the check that stops the sweep reporting clean when it scanned
# nothing, so leaving it unguarded is exactly the shape ADR-015 exists to
# prevent: an unguarded anti-vacuity guard. The condition is forced through the
# real main(), by handing it blobs that are non-empty as a LIST (so the push is
# a non-empty diff) while carrying no text (so the scanner sees no bytes) - the
# in-tree shape of a collector that enumerated a push and yielded nothing.
# --------------------------------------------------------------------------
def _fault_probe(monkeypatch, tmp_path: Path, blob_text: str) -> int:
    root = _write_config(
        tmp_path, {"repos": _SYNTH_REPOS, "participants": _SYNTH_PARTICIPANTS}
    )

    def _fake_collect(_root, _ref_lines, _remote, _stats):
        return [sweep.Blob("HUNK", "some/tracked/file.py", "M", blob_text)]

    monkeypatch.setattr(sweep, "collect_push_blobs", _fake_collect)
    monkeypatch.setattr(sys, "stdin", io.StringIO("refs/heads/main a1 refs/heads/main b2\n"))
    return sweep.main(["--pre-push", "origin", "--config-root", str(root)])


def test_zero_bytes_scanned_on_a_nonempty_diff_is_a_fault(monkeypatch, tmp_path, capsys):
    rc = _fault_probe(monkeypatch, tmp_path, "")
    err = capsys.readouterr().err
    assert rc == sweep.EXIT_FAULT, err
    assert "scanned ZERO bytes" in err
    assert "ADR-015" in err


def test_the_zero_bytes_fault_is_not_vacuous(monkeypatch, tmp_path, capsys):
    """The control arm: the SAME shape with bytes in it must not FAULT.

    Without this, the assertion above would still pass if main() returned
    EXIT_FAULT unconditionally on the pre-push arm.
    """
    rc = _fault_probe(monkeypatch, tmp_path, "an ordinary line of tracked code\n")
    err = capsys.readouterr().err
    assert rc == sweep.EXIT_CLEAN, err
    assert "scanned ZERO bytes" not in err


# --------------------------------------------------------------------------
# HOOK WIRING - two traps the naive reading misses
# --------------------------------------------------------------------------
def test_pre_push_hook_preserves_the_lfs_invocation_byte_for_byte():
    hook = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert "git lfs pre-push \"$@\"" in hook
    for line in (
        "# Git LFS. PORTED to .githooks 2026-07-26 for the same reason as post-checkout.",
        "# This is the hook that UPLOADS LFS objects - losing it means pushes that look",
        "# clean while LFS content never reaches the remote.",
    ):
        assert line in hook, line


def test_pre_push_runs_the_sweep_before_lfs_and_leaves_lfs_last():
    hook = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    body = [ln.strip() for ln in hook.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert body[-1] == 'git lfs pre-push "$@"', body[-1]
    sweep_idx = next(i for i, ln in enumerate(body) if "sibling_name_sweep.py" in ln)
    lfs_idx = len(body) - 1
    assert sweep_idx < lfs_idx
    # Anchored on the EXECUTABLE body, not on the whole file: the hook's own
    # comments explain why `set -e` is absent, and a naive substring check on
    # the file text fails on that prose.
    assert not any(ln == "set -e" for ln in body)
    # stdin is captured ONCE, because `git lfs pre-push` DRAINS it.
    assert 'REFS="$(cat)"' in hook


def test_pre_push_hook_is_ascii():
    raw = (REPO_ROOT / ".githooks" / "pre-push").read_bytes()
    assert all(b < 128 for b in raw)


# --------------------------------------------------------------------------
# KNOWN OPEN HIT - declared, named and visible; never a silent allowlist entry
# --------------------------------------------------------------------------
def test_the_known_open_hit_is_declared_with_its_reason():
    assert sweep.KNOWN_EXCEPTIONS
    rel, reason = next(iter(sweep.KNOWN_EXCEPTIONS.items()))
    assert rel == "tests/test_loop_concurrency.py"
    assert "joint" in reason.lower()
    assert "byte" in reason.lower()


def test_known_exceptions_are_reported_not_suppressed(synth_cfg, synth_needles):
    findings = _hits(synth_cfg, synth_needles, "C:\\" + synth_cfg.names[0] + "\\x")
    for f in findings:
        f.path = "tests/test_loop_concurrency.py"
    stats = sweep.ScanStats()
    stats.scanned_bytes = 10
    text = sweep.render_report(findings, stats, synth_cfg, known_ok=True)
    assert "KNOWN" in text
    assert "test_loop_concurrency.py" in text


# --------------------------------------------------------------------------
# ASCII hygiene on both new files (repo-wide hard rule)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rel", _GUARD_FILES)
def test_new_files_are_seven_bit_ascii(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    bad = [i for i, b in enumerate(raw) if b > 127]
    assert not bad, f"{rel} carries non-ASCII at byte offsets {bad[:5]}"
