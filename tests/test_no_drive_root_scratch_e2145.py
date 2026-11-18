# arch: guard - no drive-root scratch / temp / worktree path in code, CLAUDE.md, prompts or helpers (MAIN ORDER 2145) | section=tests | frozen=no
"""MAIN ORDER 2026-11-16 2145 (E-ROOT), section 4.

MAIN found 23 RC items at the drive root: an agent ran `mkdir -p` with a
four-deep `..` climb from a `.claude/worktrees/<agent>` cwd, an MSYS path lost
its leading slash and resolved against a drive-root cwd, agents improvised
drive-root tmp / scratch / `_verify_*` dirs, a WSL command wrote through
`/mnt/<x>/`, and `ops/loop/lane_launcher.py` fell back to
`<repo parent>/rc-worktrees` - the drive root for a checkout that sits
directly under one.

This guard fails when this tree's code, CLAUDE.md, prompts or helper scripts
name a drive-root scratch, temp or worktree path (a path whose parent is a
drive root, other than the repo root and the sidecar root), and checks that
the paths the tree DERIVES at runtime (lane worktree base, scratch root) lie
under the sidecar's RC folder or refuse.

Every drive-rooted literal below is built from parts, so this file does not
trip the sibling-name sweep's structural arm or its own scan (tests/ is not in
the scan set anyway: it holds the controls).
"""
from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check

launcher = importlib.import_module("ops.loop.lane_launcher")
kit = importlib.import_module("ops.fleet_kit.fleet_lanes")

BS = chr(92)
D = "E" + ":" + BS                     # a drive root, built from parts
MAIN_NAME = Path(launcher.REPO_ROOT).name  # the main checkout's folder name

# --------------------------------------------------------------------------- scan set
PATTERNS = ("*.md", "*.py", "*.ps1", "*.psm1", "*.bat", "*.cmd", "*.sh",
            "*.json", "*.txt", "*.yml", "*.yaml", "*.vbs")
_INCLUDE_PREFIXES = ("tools/", "ops/loop/", "ops/migrate/", "ops/launcher/",
                     "scripts/", ".github/")
_EXCLUDE_PREFIXES = ("ops/loop/reports/", "ops/loop/control/", "ops/fleet_kit/",
                     "ops/runtime/", "tests/", "docs/", "data/")
_INCLUDE_EXACT = ("CLAUDE.md", "dashboard/routes_loop_control.py")
_OPS_TOP_SUFFIXES = (".py", ".json", ".ps1")

ANCHOR_FILES = (
    "CLAUDE.md",
    "tools/done.md",
    "tools/headless-repo.md",
    "ops/loop/lane_launcher.py",
    "ops/loop/prompts/lane_research_prompt.md",
    "ops/loop/director_prompt.md",
)
SCAN_FLOOR = 60


def _in_scan_set(rel: str) -> bool:
    if rel.endswith(".jsonl"):
        return False
    if rel in _INCLUDE_EXACT:
        return True
    if rel.startswith(_EXCLUDE_PREFIXES):
        return False
    if rel.startswith(_INCLUDE_PREFIXES):
        return True
    return (rel.startswith("ops/") and rel.count("/") == 1
            and rel.endswith(_OPS_TOP_SUFFIXES))


def _scan_set() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in iter_repo_files(REPO_ROOT, PATTERNS):
        rel = relative_posix(p)
        if _in_scan_set(rel):
            out[rel] = p.read_text(encoding="utf-8", errors="replace")
    return out


# --------------------------------------------------------------------------- rules
_SEG = r"(?:tmp[\w.-]*|temp[\w.-]*|scratch[\w.-]*|_[\w.-]+|[\w.-]*worktrees?[\w.-]*|e)"
R1 = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]+(?P<seg>" + _SEG + r")(?=[\\/\s\"'`)]|$)",
    re.IGNORECASE)
R2_MSYS = re.compile(
    r"(?<![\w/.:\\])/(?:mnt/)?[a-z]/(?:tmp[\w.-]*|temp[\w.-]*|scratch[\w.-]*"
    r"|_[\w.-]+|[\w.-]*worktrees?)\b")
R2_MNT = re.compile(r"/mnt/[a-z]/")
R2_NOSLASH = re.compile(r"(?<![/\\\w:.])[a-z]/" + re.escape(MAIN_NAME))
R3_DEEP = re.compile(r"(?:\.\.[\\/]){3,}")
R3_CREATE = re.compile(
    r"(?:^|[\s`;&|(])(?:mkdir|md|ni|New-Item|Move-Item|Copy-Item|cp|mv|touch"
    r"|git\s+worktree\s+(?:add|move))\s[^\n]*?(?<![\w.])\.\.[\\/]")
R4 = re.compile(
    r"\.parent\s*/\s*f?[\"'][^\"'\n]*(?:worktrees?|tmp|temp|scratch)[^\"'\n]*[\"']",
    re.IGNORECASE)

RULES = (("R1 drive-root child", R1), ("R2 msys/wsl", R2_MSYS),
         ("R2 /mnt write", R2_MNT), ("R2 missing leading slash", R2_NOSLASH),
         ("R3 deep climb", R3_DEEP), ("R3 creating .. arg", R3_CREATE))

# (rel, substring of the hit line) -> why it is allowed. Each entry must still
# match a real hit, so a stale exception fails. Starts EMPTY on purpose.
KNOWN: dict[tuple[str, str], str] = {}


def _hits(text: str, *, py: bool = False) -> list[tuple[int, str, str]]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for name, rx in RULES:
            if rx.search(line):
                out.append((n, name, line.strip()))
        if py and R4.search(line):
            out.append((n, "R4 runtime parent child", line.strip()))
    return out


def _fires(sample: str) -> bool:
    return bool(_hits(sample, py=True))


# --------------------------------------------------------------------------- non-vacuity
def test_walker_and_scan_set_are_not_vacuous():
    self_check()
    files = _scan_set()
    assert len(files) >= SCAN_FLOOR, f"scan set collapsed to {len(files)} files"
    for rel in ANCHOR_FILES:
        assert rel in files, f"anchor {rel} missing from the scan set"
        assert len(files[rel]) > 0, f"anchor {rel} read empty"


@pytest.mark.parametrize("sample", [
    D + "tmp_ignore",
    D + "_verify_rm787" + BS + "x",
    D + "rc-worktrees" + BS + "lane-1",
    D + "e" + BS + "Riot Commander",
    "/e/tmp/x",
    "mkdir /mnt/" + "e" + "/Riot.err",
    "e/" + MAIN_NAME + "/.claude",
    "mkdir -p ../../../../tmp_ignore",
    "mkdir ../x",
    'Path(r).parent / "rc-worktrees"',
])
def test_positive_controls_fire(sample):
    assert _fires(sample), sample


@pytest.mark.parametrize("sample", [
    D + "Sidecars" + BS + "RC" + BS + "Scratch" + BS + "x",
    D + MAIN_NAME + BS + "x",
    "<scratch>" + BS + "x",
    "C:" + BS + "Users" + BS + "a" + BS + "AppData" + BS + "Local" + BS + "Temp" + BS + "x",
    "/e/Sidecars/RC/Scratch",
    "see ../README",
])
def test_negative_controls_do_not_fire(sample):
    assert not _fires(sample), sample


# --------------------------------------------------------------------------- the scan
def test_no_drive_root_scratch_temp_or_worktree_path():
    findings = []
    used = set()
    for rel, text in sorted(_scan_set().items()):
        for n, name, line in _hits(text, py=rel.endswith(".py")):
            key = next((k for k in KNOWN if k[0] == rel and k[1] in line), None)
            if key is not None:
                used.add(key)
                continue
            findings.append(f"{rel}:{n}: [{name}] {line[:160]}")
    assert not findings, "drive-root scratch/temp/worktree paths:\n" + "\n".join(findings)
    stale = sorted(set(KNOWN) - used)
    assert not stale, f"stale KNOWN exceptions (no longer hit): {stale}"


def test_launcher_fallback_parent_child_is_guarded_by_anchor_check():
    text = (REPO_ROOT / "ops" / "loop" / "lane_launcher.py").read_text(encoding="ascii")
    body = text.split("def resolve_worktree_base", 1)[1].split("\ndef ", 1)[0]
    assert ".anchor" in body, "resolve_worktree_base must refuse a drive-root parent"


# --------------------------------------------------------------------------- runtime derivation
def _scratch_mod():
    return importlib.import_module("ops.loop.scratch_root")


def test_worktree_base_derives_under_the_sidecar_rc_folder(tmp_path):
    sc = tmp_path / "sc"
    (sc / "RC").mkdir(parents=True)
    got = launcher.resolve_worktree_base(
        env={"FLEET_SIDECAR_ROOT": str(sc)}, config=tmp_path / "absent.json",
        repo_root=tmp_path / "x" / "repo")
    assert got == sc / "RC" / "Worktree"
    assert Path(got).is_relative_to(sc / "RC")


@pytest.mark.skipif(os.name != "nt", reason="drive roots are a Windows shape")
def test_worktree_base_never_a_drive_root_child(tmp_path):
    repo = Path(D + MAIN_NAME)
    assert repo.parent == Path(repo.anchor)
    with pytest.raises(RuntimeError):
        launcher.resolve_worktree_base(
            env={"FLEET_SIDECAR_ROOT": ""}, config=tmp_path / "absent.json",
            repo_root=repo)


def test_live_worktree_base_is_not_a_drive_root_child():
    base = launcher.WORKTREE_BASE
    if base is None:
        return  # unresolved: worktree_path refuses at use, never a root child
    base = Path(base)
    assert base.parent != Path(base.anchor), base


def test_scratch_root_derivation(tmp_path):
    mod = _scratch_mod()
    sc = tmp_path / "sc"
    (sc / "RC").mkdir(parents=True)
    assert mod.scratch_root(env={"FLEET_SIDECAR_ROOT": str(sc)}) == sc / "RC" / "Scratch"
    with pytest.raises(RuntimeError):
        mod.scratch_root(env={"RC_SCRATCH_DIR": D + "tmp"})
    with pytest.raises(RuntimeError):
        mod.scratch_root(env={"RC_SCRATCH_DIR": "relative" + BS + "x"})
    with pytest.raises(RuntimeError):
        mod.scratch_root(env={"FLEET_SIDECAR_ROOT": ""})
    deep = tmp_path / "a" / "b"
    assert mod.scratch_root(env={"RC_SCRATCH_DIR": str(deep)}) == deep


def test_machine_derived_paths_lie_under_the_sidecar_rc_folder():
    env = {"FLEET_SIDECAR_ROOT": kit.SIDECAR_DEFAULT}
    has_sidecar = bool(kit.SIDECAR_DEFAULT) and Path(kit.SIDECAR_DEFAULT, "RC").is_dir()
    if not has_sidecar:
        # No sidecar RC folder on this host (e.g. CI): the scratch root must
        # refuse rather than invent a fallback, and the worktree base must
        # still never be a drive-root child.
        with pytest.raises(RuntimeError):
            _scratch_mod().scratch_root(env=env)
        try:
            wt = launcher.resolve_worktree_base(
                env=env, config=Path(os.devnull), repo_root=Path(launcher.REPO_ROOT))
        except RuntimeError:
            return
        assert Path(wt).parent != Path(Path(wt).anchor), wt
        return
    rc = Path(kit.SIDECAR_DEFAULT) / "RC"
    scratch = _scratch_mod().scratch_root(env=env)
    assert str(scratch).startswith(kit.SIDECAR_DEFAULT + os.sep + "RC"), scratch
    assert Path(scratch).is_relative_to(rc)
    wt = launcher.resolve_worktree_base(
        env=env, config=Path(os.devnull), repo_root=Path(launcher.REPO_ROOT))
    assert Path(wt).is_relative_to(rc), wt


def test_operations_doc_names_the_archive_sidecar_location():
    text = (REPO_ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    row = next(ln for ln in text.splitlines() if ln.startswith("| `RC-RoflArchive`"))
    assert "RC sidecar `Archive` folder" in row, row


@pytest.mark.skipif(os.name != "nt", reason="HKCU is Windows-only")
def test_registry_archive_root_is_not_a_drive_root_child():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "RC_ROFL_ARCHIVE_DIR")
    except OSError:
        pytest.skip("RC_ROFL_ARCHIVE_DIR not set in HKCU")
    p = Path(str(value).strip().strip('"'))
    assert p.parent != Path(p.anchor), "replay archive root sits at a drive root"
    rc = Path(kit.SIDECAR_DEFAULT) / "RC" if kit.SIDECAR_DEFAULT else None
    if rc is not None and rc.is_dir():
        assert p.is_relative_to(rc), "replay archive root is outside the sidecar RC folder"
