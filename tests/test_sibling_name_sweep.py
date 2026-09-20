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
# KNOWN OPEN HITS - declared, named and visible; never a silent allowlist entry
# --------------------------------------------------------------------------
def test_the_known_hit_register_is_empty_and_any_entry_carries_a_reason():
    """DELIBERATELY REWRITTEN when the one declared exception was retired.

    It previously asserted the entry was keyed to `tests/test_loop_concurrency.py`
    with a "joint" + "byte" justification. That justification was false: the
    `SHARED_SHA256` dict pins `ops/loop/slots.py` and `ops/loop/winmutex.py`
    only, hashed as `ROOT / "ops" / "loop" / name`, so the pinning file never
    pinned itself and the hit was RC's to redact alone. It was redacted in
    86e4d4f0f without moving either pinned digest.

    Emptiness here is a MEASUREMENT - a tree-scope sweep returns zero findings -
    so it is asserted directly. The per-entry shape is asserted too, so the test
    does not go quietly vacuous the moment someone adds a row back.
    """
    assert isinstance(sweep.KNOWN_EXCEPTIONS, dict)
    assert not sweep.KNOWN_EXCEPTIONS, (
        "an exception is declared while the tree scans clean. An entry must "
        "correspond to a LIVE finding RC cannot remediate alone, never to a "
        "file that has nothing to find.")
    for rel, reason in sweep.KNOWN_EXCEPTIONS.items():
        assert (REPO_ROOT / rel).exists(), f"{rel} is declared but not on disk"
        assert len(reason) > 40, f"{rel} is declared without a real reason"


def test_known_exceptions_are_reported_not_suppressed(
    synth_cfg, synth_needles, monkeypatch
):
    """The never-suppressed property, proven against a SYNTHETIC entry.

    The real register is empty, so this monkeypatches one in rather than
    depending on a live declaration - otherwise retiring the last exception
    would silently retire the guard on the property as well.
    """
    rel = "tests/test_loop_concurrency.py"
    monkeypatch.setattr(
        sweep,
        "KNOWN_EXCEPTIONS",
        {rel: "synthetic entry, this test only - long enough to be a real reason"},
    )
    findings = _hits(synth_cfg, synth_needles, "C:\\" + synth_cfg.names[0] + "\\x")
    assert findings, "the synthetic probe produced no finding to annotate"
    for f in findings:
        f.path = rel
    stats = sweep.ScanStats()
    stats.scanned_bytes = 10
    text = sweep.render_report(findings, stats, synth_cfg, known_ok=True)
    assert "KNOWN" in text
    assert rel in text
    # ANNOTATED, not dropped: the finding row itself is still printed, and it
    # is flagged. A suppression list would have removed the row instead.
    assert "[KNOWN]" in text
    for f in findings:
        assert f"{rel}:{f.line}" in text


# --------------------------------------------------------------------------
# WORKTREES - the per-host config lives in the MAIN working tree only
#
# MEASURED: `core.hooksPath` is shared by every worktree, but the hook resolves
# the sweep through `git rev-parse --show-toplevel`, so a push from a worktree
# runs the WORKTREE's copy of this tool. The config is gitignored, so it exists
# only in the main checkout, and every worktree push ran DEGRADED - the needle
# arm silently skipped - while still exiting 0. Two fixes, each guarded below:
#   (a) resolve the config from the main working tree when it is absent here;
#   (b) on the --pre-push path ONLY, a DEGRADED run halts instead of passing.
# --------------------------------------------------------------------------
def _git_in(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    hooks = cwd.parent / "_no_hooks"
    hooks.mkdir(exist_ok=True)
    return subprocess.run(
        [
            "git",
            "-c", f"core.hooksPath={hooks}",
            "-c", "user.name=sweep-test",
            "-c", "user.email=sweep-test@example.invalid",
            "-c", "commit.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def _main_with_worktree(tmp_path: Path, with_config: bool):
    main = tmp_path / "mainrepo"
    main.mkdir()
    _git_in(main, "init", "-q")
    (main / "README.txt").write_text("fixture\n", encoding="utf-8")
    _git_in(main, "add", "README.txt")
    _git_in(main, "commit", "-q", "--no-verify", "-m", "fixture")
    if with_config:
        (main / "ops").mkdir()
        (main / "ops" / "moon_sync_repos.json").write_text(
            json.dumps({"repos": _SYNTH_REPOS, "participants": _SYNTH_PARTICIPANTS}),
            encoding="utf-8",
        )
    wt = tmp_path / "linkedwt"
    _git_in(main, "worktree", "add", "-q", "--detach", str(wt))
    return main, wt


def test_worktree_resolves_config_from_the_main_working_tree(tmp_path: Path):
    _main, wt = _main_with_worktree(tmp_path, with_config=True)
    assert not (wt / "ops" / "moon_sync_repos.json").exists()
    cfg = sweep.load_config(root=wt, env={})
    assert cfg.mode == sweep.MODE_ARMED, (cfg.mode, cfg.detail)
    assert len(cfg.names) == len(_SYNTH_NAMES)
    assert len(cfg.codes) == len(_SYNTH_PARTICIPANTS)


def test_worktree_without_a_main_config_stays_degraded(tmp_path: Path):
    """Control arm: the fallback borrows a file that EXISTS, never a guess."""
    _main, wt = _main_with_worktree(tmp_path, with_config=False)
    cfg = sweep.load_config(root=wt, env={})
    assert cfg.mode == sweep.MODE_DEGRADED


def test_a_non_toplevel_subdirectory_does_not_borrow_the_enclosing_config(tmp_path: Path):
    """Only a real worktree ROOT resolves upward. An arbitrary directory that
    merely sits inside a checkout keeps its own answer, so a --config-root
    pointed somewhere odd cannot silently arm from a repository it is not."""
    main, _wt = _main_with_worktree(tmp_path, with_config=True)
    sub = main / "nested"
    sub.mkdir()
    cfg = sweep.load_config(root=sub, env={})
    assert cfg.mode == sweep.MODE_DEGRADED


def test_worktree_cli_reports_armed(tmp_path: Path):
    _main, wt = _main_with_worktree(tmp_path, with_config=True)
    probe = tmp_path / "probe.txt"
    probe.write_text("an ordinary line\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("RC_MOON_SYNC_REPOS", None)
    env.pop(sweep.BYPASS_ENV, None)
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "sibling_name_sweep.py"),
            "--scan-file", str(probe),
            "--config-root", str(wt),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == sweep.EXIT_CLEAN, proc.stderr
    assert "ARMED" in proc.stderr
    assert "DEGRADED" not in proc.stderr


def _degraded_root(tmp_path: Path) -> Path:
    root = tmp_path / "noconfig"
    root.mkdir()
    return root


def test_pre_push_halts_when_degraded(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.delenv("RC_MOON_SYNC_REPOS", raising=False)
    monkeypatch.delenv(sweep.BYPASS_ENV, raising=False)
    monkeypatch.setattr(sweep, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    rc = sweep.main(["--pre-push", "origin", "--config-root", str(_degraded_root(tmp_path))])
    err = capsys.readouterr().err
    assert rc != sweep.EXIT_CLEAN, err
    assert rc == sweep.EXIT_FAULT, err
    assert "DEGRADED" in err
    assert "RC_MOON_SYNC_REPOS" in err
    assert sweep.BYPASS_ENV in err


def test_pre_push_degraded_bypass_proceeds_reports_and_logs(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.delenv("RC_MOON_SYNC_REPOS", raising=False)
    monkeypatch.setenv(sweep.BYPASS_ENV, "1")
    monkeypatch.setattr(sweep, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    rc = sweep.main(["--pre-push", "origin", "--config-root", str(_degraded_root(tmp_path))])
    err = capsys.readouterr().err
    assert rc == sweep.EXIT_CLEAN, err
    assert "BYPASS" in err
    assert "DEGRADED" in err
    log = tmp_path / sweep.BYPASS_LOG
    assert log.is_file()
    assert "DEGRADED" in log.read_text(encoding="utf-8")


def test_non_push_modes_still_pass_when_degraded(monkeypatch, tmp_path: Path, capsys):
    """CI runs the TREE arm on a runner with no config and must stay green in
    DEGRADED, so the halt is scoped to --pre-push and nothing else."""
    monkeypatch.delenv("RC_MOON_SYNC_REPOS", raising=False)
    monkeypatch.delenv(sweep.BYPASS_ENV, raising=False)
    root = _degraded_root(tmp_path)
    probe = tmp_path / "probe.txt"
    probe.write_text("an ordinary line\n", encoding="utf-8")
    assert sweep.main(["--scan-file", str(probe), "--config-root", str(root)]) == sweep.EXIT_CLEAN

    def _fake_tree(_root, stats):
        stats.files = 1
        return [sweep.Blob("TREE", "some/tracked/file.py", "T", "an ordinary line\n")]

    monkeypatch.setattr(sweep, "collect_tree_blobs", _fake_tree)
    assert sweep.main(["--tree", "--config-root", str(root)]) == sweep.EXIT_CLEAN
    assert "DEGRADED" in capsys.readouterr().err


# --------------------------------------------------------------------------
# ASCII hygiene on both new files (repo-wide hard rule)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rel", _GUARD_FILES)
def test_new_files_are_seven_bit_ascii(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    bad = [i for i, b in enumerate(raw) if b > 127]
    assert not bad, f"{rel} carries non-ASCII at byte offsets {bad[:5]}"


# --------------------------------------------------------------------------
# PER-SLOT NARROWING for a participant whose checkout basename is an ordinary
# English word.
#
# WHY THIS EXISTS. The needle arm matches a name in THREE shapes: a drive-rooted
# path, a github URL, and the BARE spelling anywhere in prose. The bare arm is
# the right default, because a sibling name is normally a coined word that has
# no business appearing in RC's own source. It is the WRONG arm for a
# participant whose basename is a dictionary word: that word occurs hundreds of
# times in RC's own charters, schedulers and roadmap prose, none of which
# identifies anybody, and a gate that halts on all of them is a gate that gets
# switched off.
#
# FOUR PROPERTIES, and the tests below exist to pin each one:
#   1. Narrowing is DECLARED, never inferred. No heuristic anywhere asks whether
#      a name "looks like" a dictionary word.
#   2. The declaration lives ONLY in the gitignored per-host config (or its env
#      companion). No real name reaches a tracked file.
#   3. A narrowed slot loses the BARE arm in BOTH views and KEEPS the drive and
#      URL arms in both. The path-shaped and repo-adjacent forms are the ones
#      that actually identify a counterparty, and they stay armed.
#   4. The default is UNCHANGED full strength. A slot with no declaration keeps
#      every arm it has today.
#
# Every literal below is INVENTED for this test and resolves to nothing. The
# drive prefix is assembled through `_D` for the reason given at the top of this
# file: a spelled drive-rooted path is a live hit for the structural arm.
# --------------------------------------------------------------------------
_NARROW_ONE = "Grommet"           # one word - the generic-noun case itself
_NARROW_TWO = "Tindal Sprocket"   # two words, so HYPHEN/UNDER/PCT20/CONCAT differ
_FULL_NAME = "Widget Foundry"     # NOT declared - the regression control


def _narrow_blob(narrowed):
    return {
        "repos": [_D + _NARROW_ONE, _D + _NARROW_TWO, _D + _FULL_NAME],
        "participants": {"GRM": _D + _NARROW_ONE},
        "narrowed_names": list(narrowed),
    }


@pytest.fixture()
def narrow_cfg(tmp_path: Path):
    root = _write_config(tmp_path, _narrow_blob([_NARROW_ONE, _NARROW_TWO]))
    return sweep.load_config(root=root, env={})


@pytest.fixture()
def narrow_needles(narrow_cfg):
    return sweep.build_needles(narrow_cfg)


def _needle_for(needles, name: str):
    for needle in needles:
        if needle.name == name:
            return needle
    raise AssertionError(f"no needle for {name!r}")


def _shape_families(needle) -> set:
    return {s.shape.split("/", 1)[0] for s in needle.patterns}


# --- the declaration itself -----------------------------------------------
def test_narrowed_names_load_from_the_per_host_config(narrow_cfg):
    assert narrow_cfg.mode == sweep.MODE_ARMED
    assert len(narrow_cfg.names) == 3
    assert set(narrow_cfg.narrowed_names) == {_NARROW_ONE, _NARROW_TWO}


def test_a_slot_is_narrowed_only_because_the_config_says_so(narrow_needles):
    """Property 1. No inference, no "looks like a dictionary word" heuristic."""
    assert _needle_for(narrow_needles, _NARROW_ONE).narrowed is True
    assert _needle_for(narrow_needles, _NARROW_TWO).narrowed is True
    assert _needle_for(narrow_needles, _FULL_NAME).narrowed is False


def test_the_same_generic_word_is_full_strength_without_a_declaration(tmp_path: Path):
    """Property 4. The ONLY difference between the two configs is the key."""
    root = _write_config(tmp_path, _narrow_blob([]))
    cfg = sweep.load_config(root=root, env={})
    needles = sweep.build_needles(cfg)
    assert _needle_for(needles, _NARROW_ONE).narrowed is False
    assert _hits(cfg, needles, "an ordinary " + _NARROW_ONE + " in prose"), (
        "an UNDECLARED slot must keep the bare arm - narrowing must be "
        "impossible to create by accident"
    )


def test_an_absent_narrowed_names_key_is_full_strength(tmp_path: Path):
    """An existing per-host config that predates this key must not change."""
    root = _write_config(
        tmp_path, {"repos": [_D + _NARROW_ONE], "participants": {}}
    )
    cfg = sweep.load_config(root=root, env={})
    assert cfg.narrowed_names == ()
    needles = sweep.build_needles(cfg)
    assert _hits(cfg, needles, "an ordinary " + _NARROW_ONE + " in prose")


def test_a_declaration_naming_no_slot_narrows_nothing(tmp_path: Path):
    """A typo in the declaration fails CLOSED, at full strength."""
    root = _write_config(tmp_path, _narrow_blob(["No Such Slot Here"]))
    cfg = sweep.load_config(root=root, env={})
    needles = sweep.build_needles(cfg)
    assert all(n.narrowed is False for n in needles)
    assert _hits(cfg, needles, "an ordinary " + _NARROW_ONE + " in prose")


def test_narrowing_is_declarable_through_the_env_companion(tmp_path: Path):
    """RC_MOON_SYNC_REPOS carries PATHS only and cannot express a declaration,
    so the companion variable is the env path's equivalent."""
    root = tmp_path / "noconfig"
    (root / "ops").mkdir(parents=True)
    cfg = sweep.load_config(
        root=root,
        env={
            "RC_MOON_SYNC_REPOS": os.pathsep.join([_D + _NARROW_ONE, _D + _FULL_NAME]),
            "RC_MOON_SYNC_NARROWED_NAMES": _NARROW_ONE,
        },
    )
    assert cfg.mode == sweep.MODE_ARMED
    assert cfg.narrowed_names == (_NARROW_ONE,)
    needles = sweep.build_needles(cfg)
    assert _needle_for(needles, _NARROW_ONE).narrowed is True
    assert _needle_for(needles, _FULL_NAME).narrowed is False


# --- POSITIVE CONTROLS: a NARROWED name must still halt on every path-shaped
# --- and repo-adjacent form. Each is asserted on its own, so a regression
# --- names the exact shape it broke rather than reddening one omnibus case.
def test_narrowed_still_halts_on_a_backslash_drive_path(narrow_cfg, narrow_needles):
    assert _hits(narrow_cfg, narrow_needles, "see " + _D + _NARROW_ONE + " today")


def test_narrowed_still_halts_on_a_forward_slash_drive_path(narrow_cfg, narrow_needles):
    assert _hits(narrow_cfg, narrow_needles, "see C:/" + _NARROW_ONE + "/tools")


def test_narrowed_still_halts_on_the_double_separator_drive_path(
    narrow_cfg, narrow_needles
):
    assert _hits(narrow_cfg, narrow_needles, "see C:" + "\\\\" + _NARROW_ONE + "\\\\ops")


def test_narrowed_still_halts_on_a_github_url(narrow_cfg, narrow_needles):
    assert _hits(
        narrow_cfg, narrow_needles, "https://github.com/some-owner/" + _NARROW_ONE
    )


def test_narrowed_still_halts_on_a_hyphenated_drive_path(narrow_cfg, narrow_needles):
    assert _hits(
        narrow_cfg, narrow_needles, "at " + _D + "-".join(_NARROW_TWO.split()) + "\\ops"
    )


def test_narrowed_still_halts_on_an_underscored_drive_path(narrow_cfg, narrow_needles):
    assert _hits(
        narrow_cfg, narrow_needles, "at " + _D + "_".join(_NARROW_TWO.split()) + "\\ops"
    )


def test_narrowed_still_halts_on_a_percent20_drive_path(narrow_cfg, narrow_needles):
    assert _hits(
        narrow_cfg,
        narrow_needles,
        "at " + _D + "%20".join(_NARROW_TWO.split()) + "\\ops",
    )


def test_narrowed_still_halts_on_a_concatenated_drive_path(narrow_cfg, narrow_needles):
    assert _hits(
        narrow_cfg, narrow_needles, "at " + _D + "".join(_NARROW_TWO.split()) + "\\ops"
    )


def test_narrowed_still_halts_on_a_hyphenated_github_url(narrow_cfg, narrow_needles):
    assert _hits(
        narrow_cfg,
        narrow_needles,
        "https://github.com/o/" + "-".join(_NARROW_TWO.split()),
    )


def test_narrowed_still_halts_on_an_underscored_github_url(narrow_cfg, narrow_needles):
    assert _hits(
        narrow_cfg,
        narrow_needles,
        "https://github.com/o/" + "_".join(_NARROW_TWO.split()),
    )


def test_narrowed_still_halts_on_a_percent20_github_url(narrow_cfg, narrow_needles):
    assert _hits(
        narrow_cfg,
        narrow_needles,
        "https://github.com/o/" + "%20".join(_NARROW_TWO.split()),
    )


def test_narrowed_still_halts_on_a_concatenated_github_url(narrow_cfg, narrow_needles):
    assert _hits(
        narrow_cfg,
        narrow_needles,
        "https://github.com/o/" + "".join(_NARROW_TWO.split()),
    )


def test_narrowed_still_halts_on_a_drive_path_split_across_a_wrapped_line(
    narrow_cfg, narrow_needles
):
    """The TIGHT view, which is the arm no contiguous search can replace.

    Two details are load-bearing and both cost a red run to learn.

    The split is MID-TOKEN, not at the space. A split at the space is also
    visible to the SPACE view (whose SPACED fragment tolerates the separator),
    and `scan_text` keeps one finding per line and slot - so the space-view hit
    wins the tie and the tight arm is never proved. Cutting inside a word leaves
    the tight view as the ONLY arm that can see it.

    The drive letter must also sit after a non-alphanumeric character IN THE
    TIGHT TEXT, because that view has no whitespace left to satisfy the
    lookbehind - hence the leading `path:` rather than a bare word.
    """
    whole = "".join(_NARROW_TWO.split())
    head, tail = whole[:5], whole[5:]
    blob = "path: " + _D + head + "\n#   " + tail + "\\ops\n"
    found = _hits(narrow_cfg, narrow_needles, blob)
    assert found, "the narrowed slot lost its TIGHT-view drive arm"
    assert any(f.shape.startswith(sweep.SHAPE_DRIVE) for f in found)
    assert any(f.view == sweep.VIEW_TIGHT for f in found), [
        (f.shape, f.view) for f in found
    ]


# --- NEGATIVE CONTROL: the whole point of the narrowing ---------------------
def test_narrowed_does_not_halt_on_the_bare_word_in_prose(narrow_cfg, narrow_needles):
    for name in (_NARROW_ONE, _NARROW_TWO):
        blob = "the " + name + " scheduler charter mentions the " + name + " lane"
        assert _hits(narrow_cfg, narrow_needles, blob) == [], name


def test_narrowed_does_not_halt_on_the_bare_slug_spellings(narrow_cfg, narrow_needles):
    """The bare arm is suppressed for EVERY variant family, not just SPACED."""
    for joiner in ("-", "_", "%20", ""):
        blob = "a token " + joiner.join(_NARROW_TWO.split()) + " in prose"
        assert _hits(narrow_cfg, narrow_needles, blob) == [], joiner


def test_narrowed_does_not_halt_on_a_bare_word_split_across_a_wrapped_line(
    narrow_cfg, narrow_needles
):
    """Suppression covers BOTH views, so the tight bare arm goes too."""
    head, tail = _NARROW_TWO.split()
    blob = "# wrapped " + head + "\n#   " + tail + " end\n"
    assert _hits(narrow_cfg, narrow_needles, blob) == []


# --- REGRESSION CONTROL: an undeclared slot is untouched -------------------
def test_a_non_narrowed_slot_still_halts_on_the_bare_prose_form(
    narrow_cfg, narrow_needles
):
    assert _hits(narrow_cfg, narrow_needles, "we synced with " + _FULL_NAME + " today")


def test_a_non_narrowed_slot_keeps_every_bare_variant(narrow_cfg, narrow_needles):
    for joiner in ("-", "_", "%20", ""):
        blob = "a token " + joiner.join(_FULL_NAME.split()) + " in prose"
        assert _hits(narrow_cfg, narrow_needles, blob) != [], joiner


def test_a_non_narrowed_slot_keeps_its_tight_bare_arm(narrow_cfg, narrow_needles):
    head, tail = _FULL_NAME.split()
    blob = "# wrapped " + head + "\n#   " + tail + " end\n"
    assert _hits(narrow_cfg, narrow_needles, blob)


def test_narrowing_one_slot_does_not_narrow_its_neighbours(narrow_needles):
    full = _needle_for(narrow_needles, _FULL_NAME)
    assert sweep.SHAPE_BARE in _shape_families(full)
    for name in (_NARROW_ONE, _NARROW_TWO):
        assert sweep.SHAPE_BARE not in _shape_families(_needle_for(narrow_needles, name))


# --- shape inventory, asserted directly rather than only through behaviour --
def test_a_narrowed_needle_keeps_its_drive_and_url_shapes(narrow_needles):
    for name in (_NARROW_ONE, _NARROW_TWO):
        families = _shape_families(_needle_for(narrow_needles, name))
        assert sweep.SHAPE_DRIVE in families, name
        assert sweep.SHAPE_URL in families, name


def test_a_narrowed_needle_keeps_the_tight_drive_shape(narrow_needles):
    for name in (_NARROW_ONE, _NARROW_TWO):
        needle = _needle_for(narrow_needles, name)
        tight_drive = [
            s
            for s in needle.patterns
            if s.view == sweep.VIEW_TIGHT and s.shape.startswith(sweep.SHAPE_DRIVE)
        ]
        assert tight_drive, name


# --- assert_non_vacuous is EXTENDED, never bypassed ------------------------
def test_assert_non_vacuous_accepts_a_narrowed_needle(narrow_needles):
    sweep.assert_non_vacuous(narrow_needles)


def test_assert_non_vacuous_rejects_a_narrowed_to_nothing_needle(narrow_needles):
    empty = sweep.Needle(
        slot=9, name=_NARROW_ONE, variants=_needle_for(narrow_needles, _NARROW_ONE).variants,
        patterns=(), narrowed=True,
    )
    with pytest.raises(AssertionError):
        sweep.assert_non_vacuous([empty])


def test_assert_non_vacuous_rejects_a_needle_that_lost_its_drive_shape(narrow_needles):
    """Mutation probe, kept as a permanent control: strip the drive arm from a
    NARROWED slot and the anti-vacuity bound must refuse it. Without this, a
    future edit could narrow a slot all the way down to a URL-only needle and
    every behavioural test above would still be green for the wrong reason."""
    needle = _needle_for(narrow_needles, _NARROW_ONE)
    stripped = sweep.Needle(
        slot=needle.slot,
        name=needle.name,
        variants=needle.variants,
        patterns=tuple(
            s for s in needle.patterns if not s.shape.startswith(sweep.SHAPE_DRIVE)
        ),
        narrowed=True,
    )
    assert stripped.patterns, "the probe must not be vacuous"
    with pytest.raises(AssertionError):
        sweep.assert_non_vacuous([stripped])


def test_assert_non_vacuous_rejects_a_needle_that_lost_its_url_shape(narrow_needles):
    needle = _needle_for(narrow_needles, _NARROW_ONE)
    stripped = sweep.Needle(
        slot=needle.slot,
        name=needle.name,
        variants=needle.variants,
        patterns=tuple(
            s for s in needle.patterns if not s.shape.startswith(sweep.SHAPE_URL)
        ),
        narrowed=True,
    )
    assert stripped.patterns
    with pytest.raises(AssertionError):
        sweep.assert_non_vacuous([stripped])


def test_assert_non_vacuous_still_rejects_a_missing_variant_family(narrow_needles):
    """The pre-existing per-family bound must keep working for a normal slot."""
    needle = _needle_for(narrow_needles, _FULL_NAME)
    broken = sweep.Needle(
        slot=needle.slot,
        name=needle.name,
        variants={**needle.variants, "PCT20": ""},
        patterns=needle.patterns,
    )
    with pytest.raises(AssertionError):
        sweep.assert_non_vacuous([broken])


def test_assert_non_vacuous_rejects_a_non_narrowed_needle_missing_its_bare_shape(
    narrow_needles,
):
    """A silent narrowing - the arm gone with no declaration behind it - is the
    exact accident property 4 forbids, so the bound refuses it too."""
    needle = _needle_for(narrow_needles, _FULL_NAME)
    silent = sweep.Needle(
        slot=needle.slot,
        name=needle.name,
        variants=needle.variants,
        patterns=tuple(
            s for s in needle.patterns if not s.shape.startswith(sweep.SHAPE_BARE)
        ),
    )
    with pytest.raises(AssertionError):
        sweep.assert_non_vacuous([silent])


# --- NOT SILENT: every surface that prints the armed line says so ----------
def test_the_armed_banner_states_how_many_slots_are_narrowed(narrow_cfg):
    banner = sweep.mode_banner(narrow_cfg)
    assert "ARMED" in banner
    assert "3 name slot(s)" in banner
    assert "2 NARROWED" in banner


def test_the_armed_banner_explains_what_a_narrowed_slot_lost(narrow_cfg):
    banner = sweep.mode_banner(narrow_cfg)
    assert "bare" in banner.lower()
    assert "WEAKENED" in banner


def test_the_armed_banner_states_zero_when_nothing_is_narrowed(tmp_path: Path):
    root = _write_config(tmp_path, _narrow_blob([]))
    banner = sweep.mode_banner(sweep.load_config(root=root, env={}))
    assert "0 NARROWED" in banner
    assert "WEAKENED" not in banner


def test_the_banner_never_names_a_narrowed_slot(narrow_cfg):
    banner = sweep.mode_banner(narrow_cfg)
    for name in (_NARROW_ONE, _NARROW_TWO, _FULL_NAME):
        assert name not in banner
        assert "".join(name.split()) not in banner


def test_the_halting_report_carries_the_narrowing_count(narrow_cfg, narrow_needles):
    findings = _hits(narrow_cfg, narrow_needles, "at " + _D + _NARROW_ONE + "\\ops")
    report = sweep.render_report(findings, sweep.ScanStats(), narrow_cfg)
    assert "2 NARROWED" in report


def test_the_ci_gate_report_carries_the_narrowing_count(narrow_cfg):
    # A PLAIN import, deliberately. tools/sibling_sweep_ci.py is FIRST-PARTY and
    # is present in every checkout, so importorskip here would gate the skip on
    # the thing under test rather than on an absent environment capability - if
    # the CI gate module ever went missing, this guard would go quietly green
    # instead of red, on the leak gate of a public repo. Caught by
    # tests/test_skip_condition_hygiene.py; see docs/SKIPIF_AUDIT_2026-07-27.md.
    from tools import sibling_sweep_ci as sweep_ci

    stats = sweep.ScanStats(files=10**6, scanned_bytes=10**9)
    _ok, lines = sweep_ci.evaluate(narrow_cfg, stats, [])
    assert any("2 NARROWED" in ln for ln in lines)


def test_the_cli_announces_the_narrowing_on_stderr(tmp_path: Path):
    root = _write_config(tmp_path, _narrow_blob([_NARROW_ONE, _NARROW_TWO]))
    blob_path = tmp_path / "clean.txt"
    blob_path.write_text("ordinary prose with no path in it\n", encoding="utf-8")
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
    assert proc.returncode == sweep.EXIT_CLEAN, proc.stdout + proc.stderr
    assert "2 NARROWED" in proc.stderr


def test_the_pre_push_path_announces_the_narrowing(monkeypatch, tmp_path: Path, capsys):
    """Requirement named explicitly: the HOOK surface must say it too.

    The hook shells out to this CLI, so the banner it shows is whatever
    `main` emits before it scans - which is exactly what is asserted here.
    """
    monkeypatch.delenv("RC_MOON_SYNC_REPOS", raising=False)
    monkeypatch.delenv(sweep.NARROWED_ENV, raising=False)
    monkeypatch.delenv(sweep.BYPASS_ENV, raising=False)
    root = _write_config(tmp_path, _narrow_blob([_NARROW_ONE, _NARROW_TWO]))
    monkeypatch.setattr(sweep, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    rc = sweep.main(["--pre-push", "origin", "--config-root", str(root)])
    err = capsys.readouterr().err
    assert rc == sweep.EXIT_CLEAN, err
    assert "ARMED" in err
    assert "2 NARROWED" in err
    assert "WEAKENED" in err


def test_the_ci_workflow_passes_the_narrowing_declaration_as_a_secret():
    """Arming the needle arm in CI without this halts on 339 lines of RC's own
    prose, so the env companion must reach the job the same way the path list
    does - from a SECRET, never a literal."""
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert sweep.NARROWED_ENV in text
    for line in text.splitlines():
        if line.strip().startswith(sweep.NARROWED_ENV + ":"):
            assert "secrets." in line, line
            break
    else:
        raise AssertionError(f"{sweep.NARROWED_ENV} is named but never bound")


def test_the_example_template_documents_the_narrowing_key():
    """The key shape is DISCOVERABLE without reading the gitignored file, and
    the tracked template carries a PLACEHOLDER only."""
    text = (REPO_ROOT / "ops" / "moon_sync_repos.example.json").read_text(
        encoding="utf-8"
    )
    blob = json.loads(text)
    assert "narrowed_names" in blob
    assert "_narrowed_names_doc" in blob
    assert isinstance(blob["narrowed_names"], list) and blob["narrowed_names"]
