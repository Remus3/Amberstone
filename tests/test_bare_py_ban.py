"""Guard: no bare ``py`` launcher usage on tracked runnable/doc surfaces.

Regression for the deep-audit P2 interpreter pin (gemini-ruled OPTION 4):
bare ``py`` on Legion resolves via PEP 514 to a pymanager runtime
(AppData/Local/Python/pythoncore-3.14-64) that has NO third-party packages,
so a launcher-spelled pytest invocation silently runs a pytest-less
interpreter (a past incident zeroed the test suite). Runnable and doc
surfaces must pin the canonical interpreter by absolute path:

    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe

The allowlist below names the surfaces that may keep historical or
machine-foreign bare-py text; everything else tracked by git is scanned.
"""
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Bare launcher followed by a runnable argument (module flag, version flag,
# drive-letter path, repo-relative script path, or any *.py target).
# The prefix class excludes "." so multi-file commands like
# "pytest a.py b.py" do not false-positive on the trailing "py" of a
# previous .py argument (ci.yml multi-file pytest lines are legitimate).
_BARE_PY = re.compile(
    r"""(^|[^\w.-])py(\.exe)?\s+(-m\s|-3|["']?[A-Za-z]:|tools[\\/]|scripts[\\/]|ops[\\/]|[\w.\\/-]+\.py\b)"""
)

_MANDATE = (
    "bare py resolves to a dep-less pymanager runtime; use the canonical "
    "absolute interpreter path - see docs/OPERATIONS.md interpreter section"
)

# fnmatch patterns against posix-style repo-relative paths.
_ALLOWLIST = (
    "docs/_archive/**",          # immutable dated artifacts - never swept
    "docs/history_notes.md",     # deep archive (items 1-324) - history quotes
    "docs/LEDGER.md",            # append-only per-item ledger - history quotes
    "docs/ROADMAP_HISTORY.md",   # dated roadmap snapshots - history quotes
    "agents/agent*/reports/**",    # phase-3 agent task-log artifacts
    "agents/agent*/proposals/**",  # phase-3 agent proposal artifacts
    "WAKEUP_NOTES.md",           # rolling session history quotes
    "docs io RC peer/**",         # Peer machine docs - foreign interpreter universe
    "tools/wrap-gamepc.md",      # gamepc-machine surface, retired - P3 prunes
    "tools/done-gamepc.md",      # gamepc-machine surface, retired - P3 prunes
    "tools/GAMEPC_CLAUDE.md",    # gamepc-machine surface, retired - P3 prunes
    "bootstrap_riot_commander_dev.ps1",  # fresh-machine bootstrap; canonical interpreter absent there
    "ops/loop/control/**",       # loop scratch/control surfaces
    "tests/test_bare_py_ban.py",  # this guard - carries the banned pattern itself
    "*.log",                     # immutable logs
    "*.jsonl",                   # immutable ledgers
    # --- P2b: deferred tail SWEPT (cycle 6, item 400); residue below is
    # gamepc-foreign or quotes the banned pattern by design ---
    "tools/phase_watcher_install.ps1",  # Legion-local installer surface (carries bare py)
    "ROADMAP.md",                # gamepc-machine historical recipes - P3 gamepc prune removes them
    "ops/audit/P0_WORKMAP.md",   # P0 audit workmap - quotes the banned pattern by design
    "ops/tls/_bridge_msg.txt",   # gamepc-era bridge message artifact (foreign C:/RC-Agent path)
    "tests/test_precommit_gate.py",   # characterization fixtures - bare py IS the tested input
    "tests/test_truth_gate.py",       # incident-characterization fixture + docstring
    "_scratch/**",               # untracked scratch; sweep/probe tooling carries the pattern
)

_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".zip", ".gz", ".7z", ".rar", ".jar",
    ".exe", ".dll", ".pyd", ".pyc", ".so",
    ".db", ".sqlite", ".sqlite3", ".bin", ".dat",
    ".pdf", ".xlsx", ".docx", ".pptx",
    ".mp3", ".mp4", ".wav", ".ogg", ".webm",
}


def _tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_REPO_ROOT, capture_output=True, check=True,
    ).stdout
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def _is_allowlisted(rel_posix):
    return any(fnmatch(rel_posix, pattern) for pattern in _ALLOWLIST)


def test_no_bare_py_launcher_on_tracked_surfaces():
    offenders = []
    for rel in _tracked_files():
        if _is_allowlisted(rel):
            continue
        if Path(rel).suffix.lower() in _BINARY_EXTS:
            continue
        path = _REPO_ROOT / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if b"\x00" in raw[:8192]:
            continue  # binary sniff
        text = raw.decode("utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            m = _BARE_PY.search(line)
            if m:
                offenders.append(f"{rel}:{i}: {line.strip()[:120]}")
    assert not offenders, (
        f"{_MANDATE}\n"
        f"{len(offenders)} bare-py occurrence(s):\n" + "\n".join(offenders)
    )
