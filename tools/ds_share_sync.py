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

It also keeps the authored handoff docs' MECHANICAL version/patch anchors fresh:
the ``ENGINE_VERSION = "X"`` literal and the explicit ``data patch `X` `` /
``"patch": "X"`` anchor phrases in ``Share/README.md`` + ``Share/docs/*.md`` are
rewritten to the live values on a plain run and verified by ``--check`` - the
same hard gate as the ``src`` mirror, so an engine bump that forgets the docs
fails CI. Only those literal anchors are auto-maintained; the SEMANTIC prose
(shipped-vs-staged, test counts, the dated CHANGELOG entry) is a hand step in the
/done ritual, and a doc that describes a now-complete one-off effort is updated
to its done-state or archived there.

Usage:
  python tools/ds_share_sync.py            # sync Share/src + stamp MANIFEST
                                           # + refresh authored-doc anchors
  python tools/ds_share_sync.py --check    # CI guard: exit 1 if Share/src OR an
                                           # authored-doc anchor drifts (no writes)

The ``--check`` mode compares ``Share/src`` (the deterministic mirror) AND the
authored-doc version/patch anchors; ``Share/MANIFEST.md`` carries a sync
timestamp and is not part of the drift check. CI runs ``--check`` so any DS
change that forgets to re-sync (src or doc anchors) fails.
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

# Authored docs whose mechanical version/patch anchors must track the live
# engine. The CHANGELOG (release history, legitimately full of OLD versions) and
# the machine-generated MANIFEST are excluded. These are NOT part of the
# deterministic ``src`` mirror; this script keeps their version/patch anchors
# fresh (write mode) and verifies them (``--check``) the same way it restamps and
# guards MANIFEST/src, so an engine bump that forgets the docs fails CI.
_DOC_FILES: tuple[str, ...] = (
    "README.md",
    "docs/01_OVERVIEW.md",
    "docs/02_FUNCTION_REFERENCE.md",
    "docs/03_DATA_AND_SOURCES.md",
    "docs/04_GAPS_AND_ROADMAP.md",
    "docs/05_AUDIT_AND_REFACTOR.md",
)
_SEMVER = r"\d+\.\d+\.\d+"

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
        # The live engine CHANGELOG.md is the repo-internal release history
        # relocated out of __init__.py (item 241). The Share package carries its
        # own authored Share/CHANGELOG.md and a stubbed __init__, so the engine
        # changelog is intentionally not mirrored. CC_CONDITIONAL_NOTES.md is the
        # repo-internal authoring source + REJECT rationale relocated out of the
        # cc_conditional.py builders (item 245 A3); it carries dev-context (wave /
        # item numbers) and is not read at runtime (the loader reads the mirrored
        # cc_conditional_registry.json), so it is intentionally not mirrored.
        # cc_output_registry_notes.json (item 294) is the same: provenance source
        # quotes for the cc_output.py CC-kind registry, not read at runtime (the
        # registry is baked into cc_output.py), so it too is not mirrored.
        # mobility_registry_notes.json (item 297) is the mobility.py analog.
        # sustain_registry_notes.json (item 298) is the sustain.py analog.
        # scaling_registry_notes.json (item 299) is the scaling.py analog.
        # waveclear_registry_notes.json (item 300) is the waveclear.py analog.
        # threatrange_registry_notes.json (item 301) is the threatrange.py analog.
        # zonecontrol_registry_notes.json (item 302) is the zonecontrol.py analog.
        # objdamage_registry_notes.json (item 303) is the objdamage.py analog.
        if p.name in (
            "CHANGELOG.md",
            "CC_CONDITIONAL_NOTES.md",
            "cc_output_registry_notes.json",
            "mobility_registry_notes.json",
            "sustain_registry_notes.json",
            "scaling_registry_notes.json",
            "waveclear_registry_notes.json",
            "threatrange_registry_notes.json",
            "zonecontrol_registry_notes.json",
            "objdamage_registry_notes.json",
        ) and p.parent == eng:
            continue
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


def _doc_anchor_rules() -> tuple[tuple[str, "re.Pattern[str]", str], ...]:
    """Mechanical version/patch anchor rules for the authored docs.

    Each rule is ``(label, pattern, live_value)``. The pattern matches ONLY the
    version/patch token (via fixed-width look-around), so ``pattern.sub(live,
    text)`` rewrites just the token and ``pattern.finditer(text)`` yields the
    tokens to verify. Deliberately scoped to unambiguous anchor forms so it never
    rewrites a file path, the CommunityDragon two-segment patch pin, the
    ``current.txt`` content description, or a changelog history entry. The
    semantic prose (shipped-vs-staged, test counts) is refreshed by hand per the
    /done ritual - only these literal anchors are auto-maintained.
    """
    version = _engine_version()
    patch = _PATCH
    return (
        ("engine version", re.compile(rf'(?<=ENGINE_VERSION = ")(?:{_SEMVER})(?=")'), version),
        ("data patch", re.compile(rf'(?<=data patch `)(?:{_SEMVER})(?=`)'), patch),
        ("active data patch", re.compile(rf'(?<=Active data patch: `)(?:{_SEMVER})(?=`)'), patch),
        ("game patch", re.compile(rf'(?<=game patch `)(?:{_SEMVER})(?=`)'), patch),
        ("health-example patch", re.compile(rf'(?<="patch": ")(?:{_SEMVER})(?=")'), patch),
    )


def _rewrite_doc_anchors() -> list[str]:
    """Write mode: rewrite the mechanical version/patch anchors in the authored
    docs to the live values. Returns the relpaths changed."""
    rules = _doc_anchor_rules()
    changed: list[str] = []
    for rel in _DOC_FILES:
        p = _SHARE / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        new = text
        for _label, pat, live in rules:
            new = pat.sub(live, new)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed.append(rel)
    return changed


def _check_doc_anchors() -> int:
    """--check: count drifted version/patch anchors in the authored docs, each
    printed as ``file:line``. Returns the drift count (0 == fresh)."""
    rules = _doc_anchor_rules()
    drift = 0
    for rel in _DOC_FILES:
        p = _SHARE / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for label, pat, live in rules:
            for m in pat.finditer(text):
                if m.group(0) != live:
                    line = text.count("\n", 0, m.start()) + 1
                    drift += 1
                    print(f"  DOC ANCHOR DRIFT ({label}): {rel}:{line} "
                          f"has '{m.group(0)}', live is '{live}'")
    return drift


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync the DS Share review package.")
    ap.add_argument("--check", action="store_true",
                    help="verify Share/src matches the live engine; exit 1 on drift")
    args = ap.parse_args(argv)

    expected = _build_expected()
    version = _engine_version()

    if args.check:
        drift = _check(expected) + _check_doc_anchors()
        if drift:
            print(f"ds_share_sync: {drift} path(s)/anchor(s) drifted - run "
                  f"`python tools/ds_share_sync.py` and commit Share/.")
            return 1
        print(f"ds_share_sync: Share/src + doc anchors in sync (engine {version}, "
              f"{len(expected)} files).")
        return 0

    n = _write(expected)
    _stamp_manifest(version, n)
    docs_changed = _rewrite_doc_anchors()
    doc_note = (f" + refreshed {len(docs_changed)} doc anchor file(s)"
                if docs_changed else " + doc anchors already fresh")
    print(f"ds_share_sync: wrote {n} files to Share/src (engine {version}, "
          f"patch {_PATCH}) + stamped MANIFEST{doc_note}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
