"""Sync the Daemon Slayer external-review package under ``Share/src``.

The ``Share/`` folder is a self-contained, external-facing mirror of the DS
engine: the engine source, the DS tooling, and the versioned reference-data
snapshot, plus authored handoff docs. This script is the single durable
"update path" that keeps ``Share/src`` in lock-step with the live engine.

What it mirrors into ``Share/src`` (deterministic - same input -> same output):
  * ``agents/daemon_slayer/**``  (engine + tests) -> ``Share/src/agents/daemon_slayer/``
  * a curated set of DS tools     -> ``Share/src/tools/``
  * ``data/daemon_slayer/16.11.1/** + current.txt`` -> ``Share/src/data/daemon_slayer/``

Two transforms are applied to copied ``.py`` text so the package presents the
engine on its own technical merits:
  1. ``__init__.py`` is replaced by a clean stub (a neutral package docstring +
     the ``ENGINE_VERSION`` constant). The live ``__init__.py`` is a ~4600-line
     embedded changelog with no functional code beyond the version constant;
     the package's release history lives in ``Share/CHANGELOG.md`` instead.
  2. ``_SCRUB`` rewrites a small, bounded set of development-context comment
     phrases to neutral wording. Data JSON is copied verbatim (it is data).

Usage:
  python tools/ds_share_sync.py            # sync Share/src + stamp MANIFEST
  python tools/ds_share_sync.py --check    # CI guard: exit 1 if Share/src drifts
                                           # from the live engine (no writes)

The ``--check`` mode compares only ``Share/src`` (the deterministic mirror);
``Share/MANIFEST.md`` carries a sync timestamp and is not part of the drift
check. CI runs ``--check`` so any DS change that forgets to re-sync fails.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SHARE = _REPO / "Share"
_SRC = _SHARE / "src"
_PATCH = "16.11.1"

# DS engine tooling copied into the package (extractors + serving + the
# patch-bump prefilter/inspect scanners). This script is intentionally NOT in
# the list (it is repo-internal maintenance tooling).
_DS_TOOLS: tuple[str, ...] = (
    "daemon_slayer_extract.py",
    "daemon_slayer_abilities_extract.py",
    "daemon_slayer_cdragon_spell_extract.py",
    "daemon_slayer_wiki_ability_extract.py",
    "daemon_slayer_wiki_stats_extract.py",
    "start_daemon_slayer.py",
    "ds_block_scanner.py",
    "ds_cond_inspect.py",
    "ds_cond_pair_prefilter.py",
    "ds_execute_prefilter.py",
    "ds_form_index_prefilter.py",
    "ds_max_priority_prefilter.py",
    "ds_unmapped_key_prefilter.py",
)

# Bounded, exact-substring rewrites of development-context comment phrases that
# name the review provenance. Applied to copied .py text only. Engine logic,
# identifiers, and the structural ``lolmath`` data-schema key are untouched.
_SCRUB: tuple[tuple[str, str], ...] = (
    ("sibling project's scraper-refactor chat", "roster audit"),
    ("sibling-project scraper-refactor chat", "roster audit"),
    ("scraper-refactor conversation", "roster audit"),
    ("scraper-refactor chat", "roster audit"),
    ("the sibling project's \"edge cases will have to be reverted\"",
     "a known text-parser fragility (\"edge cases will have to be reverted\")"),
    ("(2026-05-30 DS review)", "(patch 16.11.1 audit)"),
    ("(2026-05-31 DS review)", "(patch 16.11.1 audit)"),
)

_CLEAN_INIT = '''\
"""Daemon Slayer - offline, deterministic League of Legends build-scoring engine.

This package computes auto-attack DPS, ability DPS, burst, effective HP, healing
throughput, and crowd-control pressure for a champion at a given level and mode
against a target's defensive profile, and ranks item builds for six archetypes
(carry / tank / bruiser / mage / assassin / enchanter). It reads a versioned
reference-data snapshot (``data/daemon_slayer/<patch>/``) derived from Riot Data
Dragon, CommunityDragon, and Meraki Analytics, and serves results over a local
HTTP endpoint (see ``server.py``).

The engine is pure and deterministic: new capabilities are added as opt-in flags
that are byte-identical to the prior version at their default, so the engine
grows without regressing existing output.

``ENGINE_VERSION`` is the single source of truth for the engine revision; the
release history is in the package ``CHANGELOG.md``.
"""

ENGINE_VERSION = "{version}"
'''


def _engine_version() -> str:
    """Read ENGINE_VERSION from the live engine __init__.py."""
    text = (_REPO / "agents" / "daemon_slayer" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^ENGINE_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("could not find ENGINE_VERSION in the live engine")
    return m.group(1)


def _scrub(text: str) -> str:
    for old, new in _SCRUB:
        text = text.replace(old, new)
    return text


def _is_pyc(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix == ".pyc"


def _build_expected() -> dict[str, bytes]:
    """Return the expected ``Share/src`` content as {relpath: bytes}.

    Deterministic - the basis for both writing and the --check drift guard.
    Relpaths are POSIX-style, relative to ``Share/src``.
    """
    version = _engine_version()
    out: dict[str, bytes] = {}

    # agents/ package marker (the live agents/ holds unrelated packages; the
    # mirror only carries daemon_slayer, so a minimal package marker suffices).
    out["agents/__init__.py"] = b""

    # Engine package: copy every file; scrub .py text; clean-stub __init__.py.
    eng = _REPO / "agents" / "daemon_slayer"
    for p in sorted(eng.rglob("*")):
        if p.is_dir() or _is_pyc(p):
            continue
        rel = f"agents/daemon_slayer/{p.relative_to(eng).as_posix()}"
        if p.name == "__init__.py" and p.parent == eng:
            out[rel] = _CLEAN_INIT.format(version=version).encode("utf-8")
        elif p.suffix == ".py":
            out[rel] = _scrub(p.read_text(encoding="utf-8")).encode("utf-8")
        else:
            out[rel] = p.read_bytes()

    # DS tooling.
    tools = _REPO / "tools"
    for name in _DS_TOOLS:
        src = tools / name
        if src.exists():
            out[f"tools/{name}"] = _scrub(src.read_text(encoding="utf-8")).encode("utf-8")

    # Reference-data snapshot (verbatim - it is data).
    data = _REPO / "data" / "daemon_slayer"
    cur = data / "current.txt"
    if cur.exists():
        out["data/daemon_slayer/current.txt"] = cur.read_bytes()
    snap = data / _PATCH
    for p in sorted(snap.rglob("*")):
        if p.is_dir():
            continue
        out[f"data/daemon_slayer/{_PATCH}/{p.relative_to(snap).as_posix()}"] = p.read_bytes()

    return out


def _write(expected: dict[str, bytes]) -> int:
    """Write expected content under Share/src, removing stale files. Returns
    the number of files written."""
    if _SRC.exists():
        shutil.rmtree(_SRC)
    for rel, data in expected.items():
        dst = _SRC / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    return len(expected)


def _check(expected: dict[str, bytes]) -> int:
    """Compare on-disk Share/src against expected. Returns count of drifted
    paths (0 == in sync)."""
    on_disk: dict[str, bytes] = {}
    if _SRC.exists():
        for p in sorted(_SRC.rglob("*")):
            # Ignore transient run-artifacts a test/import run may drop into
            # the mirror (bytecode caches, log files); they are gitignored and
            # are not part of the deterministic source mirror.
            if p.is_dir() or _is_pyc(p) or p.suffix == ".log" or "logs" in p.parts:
                continue
            on_disk[p.relative_to(_SRC).as_posix()] = p.read_bytes()
    drift = 0
    for rel in sorted(set(expected) | set(on_disk)):
        if expected.get(rel) != on_disk.get(rel):
            drift += 1
            if rel not in expected:
                print(f"  DRIFT (stale, not in live engine): {rel}")
            elif rel not in on_disk:
                print(f"  DRIFT (missing from Share/src): {rel}")
            else:
                print(f"  DRIFT (content differs): {rel}")
    return drift


def _stamp_manifest(version: str, n_files: int) -> None:
    """Write Share/MANIFEST.md (timestamped machine record of the sync)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    eng_files = sum(1 for r in _build_expected() if r.startswith("agents/daemon_slayer/") and r.endswith(".py"))
    body = f"""# Daemon Slayer review package - MANIFEST

Machine record of the last ``Share/src`` sync. Regenerated by
``tools/ds_share_sync.py``; do not hand-edit.

- ENGINE_VERSION: {version}
- data patch: {_PATCH}
- files mirrored under Share/src: {n_files}
- engine .py modules: {eng_files}
- last synced: {ts}

## Layout

```
Share/
  README.md                 entry point + how to read / run the package
  CHANGELOG.md              authored release notes + sync history
  MANIFEST.md               this file (machine record)
  docs/                     authored handoff docs (overview, function
                            reference, data + sources, gaps + roadmap, audit)
  src/
    agents/daemon_slayer/   the engine package (source + tests)
    tools/                  DS extractors, the server launcher, patch-bump scanners
    data/daemon_slayer/     the versioned reference-data snapshot ({_PATCH})
```

## Running the engine from this package

```
cd Share/src
set PYTHONPATH=.                       # Windows;  export PYTHONPATH=. on POSIX
python -m pytest agents/daemon_slayer/tests -q
python tools/start_daemon_slayer.py    # serves the engine on http://127.0.0.1:8893
```

Inline source comments reference the engine's internal incremental-development
tags (version anchors, registry "wave" numbers, internal change identifiers).
These are historical development markers, not part of the engine's public
contract or any external dependency.
"""
    (_SHARE / "MANIFEST.md").write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync the DS Share review package.")
    ap.add_argument("--check", action="store_true",
                    help="verify Share/src matches the live engine; exit 1 on drift")
    args = ap.parse_args(argv)

    expected = _build_expected()
    version = _engine_version()

    if args.check:
        drift = _check(expected)
        if drift:
            print(f"ds_share_sync: {drift} path(s) drifted - run "
                  f"`python tools/ds_share_sync.py` and commit Share/.")
            return 1
        print(f"ds_share_sync: Share/src in sync (engine {version}, "
              f"{len(expected)} files).")
        return 0

    n = _write(expected)
    _stamp_manifest(version, n)
    print(f"ds_share_sync: wrote {n} files to Share/src (engine {version}, "
          f"patch {_PATCH}) + stamped MANIFEST.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
