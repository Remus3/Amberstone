# arch: RM-108 unresolved-template-token detector over vendored feeds | section=tools | frozen=no
"""RM-108 - detect unresolved template tokens in the vendored JSON feeds.

WHAT THE HARM ACTUALLY IS (measured 2026-07-19, and it is NOT what the
ROADMAP entry assumes). ROADMAP.md:305 frames the risk as "a naive parser
reads 0.0 and ships it silently". A full walk of the three vendored roots
found 56,896 token occurrences across 874 files, and EVERY one lands in a
display-prose key - ``desc`` / ``tooltip`` / ``longDesc`` / ``description`` /
``plaintext`` / ``resource`` / ``costType`` / leveltip ``effect`` + ``label``
/ ``name`` / a wiki ``*_raw`` passthrough. NONE lands in a key the engine
reads numerically. ``longDesc``, ``plaintext``, ``leveltip`` and ``costType``
have ZERO runtime readers at all.

So the real harm is UPSTREAM of any parser. It is a HUMAN transcribing
vendored prose into a hand-pinned registry - the way ``_rune_health_grants``,
``rune_procs``, ``enemy_runes`` and ``_per_spell_cc`` are all authored - who
hits a token where a number should be and has to decide what to do. R136 hit
exactly that on Font of Life 8463 and correctly pinned it at zero rather than
guessing, but left ``@f3@`` and ``@HealAmount@`` undocumented next door.

Hence the PRIMARY product of this tool is the ``documented_instances``
registry in ``tools/data/unresolved_template_tokens.json``, which serves
registry AUTHORS. The numeric-key tripwire is the cheap secondary, and it is
empty today by measurement.

Two token grammars, both deliberately narrow:

  AT  ``@[A-Za-z_][A-Za-z0-9_]*@``     DDragon rune/item substitution vars
  CU  ``{{ *[A-Za-z_][A-Za-z0-9_]* *}}``  DDragon tooltip + wiki template vars

CU is NOT lowercase-only (the ROADMAP's ``{{ *[a-z_]+ *}}`` misses every
curly token in ``items.json`` - they are Capitalized, e.g.
``{{ Item_Cooldown }}``), and CU deliberately forbids ``|``. Widening it to
allow a pipe would swallow ~2,493 MediaWiki call forms per
``wiki_ability_stats.json`` (``{{fd|0.25}}``, ``{{tip|er|icononly = true}}``),
which are correct-by-design passthroughs, not unresolved anything.

PATCH + CHAMPION NORMALIZATION IS LOAD-BEARING, not cosmetic. Emitted paths
replace ``/<major.minor.patch>/`` with ``/<patch>/`` and
``champion_detail/<Name>.json`` with ``champion_detail/<champ>.json``. That
collapses 874 concrete files onto 82 stable keys, so a DDragon bump or a
champion rework does not redden the guard.

DELIBERATELY NOT PRODUCED: occurrence counts as a pinned assertion. 33,293 of
the 56,896 occurrences are in ``champion_detail``, which moves on every
champion ship or rework.

Usage::

    python tools/unresolved_token_scan.py
    python tools/unresolved_token_scan.py --json out.json
    python tools/unresolved_token_scan.py --regen-allowlist

Structured so collection is import-safe: all I/O lives under functions and
``main(argv=None)`` returns an int.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "tools" / "data" / "unresolved_template_tokens.json"

#: The three vendored roots, repo-relative. ~874 JSON files today.
DEFAULT_ROOTS = (
    "data/daemon_slayer",
    "data/meta_build",
    "data/meta",
)

#: DDragon ``@Var@`` substitution tokens.
AT_TOKEN = re.compile(r"@[A-Za-z_][A-Za-z0-9_]*@")
#: ``{{ Var }}`` tokens. Case-insensitive on the first letter; NO pipe allowed.
CURLY_TOKEN = re.compile(r"\{\{ *[A-Za-z_][A-Za-z0-9_]* *\}\}")

#: A path segment that is a patch directory, e.g. ``16.14.1``.
_PATCH_SEGMENT = re.compile(r"^\d+\.\d+\.\d+$")
#: ``champion_detail/Morgana.json`` -> ``champion_detail/<champ>.json``.
_CHAMPION_DETAIL = re.compile(r"champion_detail/[^/]+\.json$")
#: Tokenizer for a json_path such as ``[3].slots[1].runes[1].longDesc``.
_PATH_STEP = re.compile(r"\.([^.\[\]]+)|\[(\d+)\]")

PATCH_PLACEHOLDER = "<patch>"
CHAMP_PLACEHOLDER = "<champ>"

logger = logging.getLogger("unresolved_token_scan")


@dataclass(frozen=True)
class Finding:
    """One token occurrence, keyed patch- and champion-invariantly.

    ``feed_glob`` is the NORMALIZED repo-relative path (``<patch>`` /
    ``<champ>`` substituted). ``patch`` carries the concrete patch the
    occurrence was observed in, or None for an unpatched feed.
    """

    feed_glob: str
    json_path: str
    leaf_key: str
    token: str
    patch: str | None


# --------------------------------------------------------------------------- paths
def normalize_feed_path(rel_posix: str) -> tuple[str, str | None]:
    """Return ``(normalized_path, patch)`` for a repo-relative posix path.

    The normalization is what stops patch-bump churn - see the module
    docstring. It is not optional.
    """
    patch: str | None = None
    parts = []
    for seg in rel_posix.split("/"):
        if _PATCH_SEGMENT.match(seg):
            patch = seg
            parts.append(PATCH_PLACEHOLDER)
        else:
            parts.append(seg)
    joined = "/".join(parts)
    joined = _CHAMPION_DETAIL.sub(
        f"champion_detail/{CHAMP_PLACEHOLDER}.json", joined
    )
    return joined, patch


def newest_patch_dir(parent: Path) -> str | None:
    """Newest patch-shaped subdirectory of ``parent``, ranked numerically."""
    if not parent.is_dir():
        return None
    found = [p.name for p in parent.iterdir() if p.is_dir() and _PATCH_SEGMENT.match(p.name)]
    if not found:
        return None
    return max(found, key=lambda n: tuple(int(x) for x in n.split(".")))


def resolve_feed_glob(
    glob: str, *, root: Path | None = None, champion: str | None = None
) -> list[Path]:
    """Expand a normalized feed path back to concrete file(s) on disk.

    ``<patch>`` resolves to the NEWEST patch directory present (so a bump is
    picked up for free); ``<champ>`` resolves to ``champion``. Returns [] when
    the placeholder cannot be resolved - callers treat that as "absent", never
    as a failure, because ``data/daemon_slayer/16.10.1`` is missing 10 of its
    20 feeds (measured).
    """
    base = Path(root) if root is not None else ROOT
    rel = glob
    if PATCH_PLACEHOLDER in rel:
        head = rel.split("/" + PATCH_PLACEHOLDER, 1)[0]
        patch = newest_patch_dir(base / head)
        if patch is None:
            return []
        rel = rel.replace(PATCH_PLACEHOLDER, patch)
    if CHAMP_PLACEHOLDER in rel:
        if not champion:
            return []
        rel = rel.replace(CHAMP_PLACEHOLDER, champion)
    return [base / rel]


# --------------------------------------------------------------------------- json
def load_json(path: Path) -> object | None:
    """Parse a JSON file, fail-soft to None. Never raises on bad input."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("unparseable feed %s: %s", path, exc)
        return None


def value_at(doc: object, json_path: str) -> object | None:
    """Look up ``json_path`` (``.key`` / ``[i]`` steps) inside ``doc``."""
    node = doc
    for key, idx in _PATH_STEP.findall(json_path):
        if idx:
            if not isinstance(node, list):
                return None
            pos = int(idx)
            if pos >= len(node):
                return None
            node = node[pos]
        else:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
    return node


def iter_vendored_json(
    roots: Iterable[str] | None = None, *, root: Path | None = None
) -> Iterator[tuple[str, object]]:
    """Yield ``(normalized_path, parsed_doc)`` for every vendored JSON file.

    Exposed separately from :func:`scan` on purpose: the provenance feed index
    can share this single ``json.load`` pass instead of walking the same 874
    files twice. Unparseable files are skipped fail-soft.
    """
    base = Path(root) if root is not None else ROOT
    for rel_root in roots if roots is not None else DEFAULT_ROOTS:
        for path in sorted((base / rel_root).glob("**/*.json")):
            doc = load_json(path)
            if doc is None:
                continue
            normalized, _patch = normalize_feed_path(
                path.relative_to(base).as_posix()
            )
            yield normalized, doc


def _walk(node: object, path: str, leaf: str) -> Iterator[tuple[str, str, str]]:
    """Yield ``(json_path, leaf_key, token)`` for every token in ``node``."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}", str(key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]", leaf)
    elif isinstance(node, str):
        for match in AT_TOKEN.findall(node):
            yield path, leaf, match
        for match in CURLY_TOKEN.findall(node):
            yield path, leaf, match


def scan(roots: Iterable[str] | None = None, *, root: Path | None = None) -> list[Finding]:
    """Walk the vendored feeds and return every token occurrence as a Finding."""
    base = Path(root) if root is not None else ROOT
    out: list[Finding] = []
    for rel_root in roots if roots is not None else DEFAULT_ROOTS:
        for path in sorted((base / rel_root).glob("**/*.json")):
            doc = load_json(path)
            if doc is None:
                continue
            normalized, patch = normalize_feed_path(path.relative_to(base).as_posix())
            for json_path, leaf, token in _walk(doc, "", ""):
                out.append(Finding(normalized, json_path, leaf, token, patch))
    return out


# --------------------------------------------------------------------------- registry
def load_registry(path: Path | None = None) -> dict:
    """Load the RM-108 registry. Raises if it is missing - it is required."""
    target = Path(path) if path is not None else REGISTRY_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def _write_atomic(target: Path, payload: str) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)


def regen_allowlist(
    findings: list[Finding], path: Path | None = None
) -> tuple[list[str], bool]:
    """Rewrite ``display_key_allowlist.keys`` from a live scan. Atomic.

    Returns ``(keys, wrote)``. NO-OP when the keys already match, because
    writing normalizes away the hand-authored blank-line grouping in the
    registry - and that grouping is what makes the ``_comment`` blocks
    readable, which is the whole point of the file.
    """
    target = Path(path) if path is not None else REGISTRY_PATH
    registry = load_registry(target)
    keys = sorted({f.leaf_key for f in findings})
    if registry["display_key_allowlist"]["keys"] == keys:
        return keys, False
    registry["display_key_allowlist"]["keys"] = keys
    _write_atomic(target, json.dumps(registry, indent=2, ensure_ascii=True) + "\n")
    return keys, True


# --------------------------------------------------------------------------- report
def _table(findings: list[Finding]) -> str:
    by_key = Counter(f.leaf_key for f in findings)
    by_feed = Counter(f.feed_glob for f in findings)
    distinct = {f.token for f in findings}

    lines = [
        "RM-108 unresolved-template-token scan",
        f"  occurrences   {len(findings)}",
        f"  distinct      {len(distinct)}",
        f"  feed keys     {len(by_feed)} (patch- and champion-normalized)",
        "",
        "  leaf key                        occurrences",
        "  " + "-" * 44,
    ]
    for key, count in by_key.most_common():
        lines.append(f"  {key:<32}{count:>11}")
    lines += ["", "  feed (normalized)                       occurrences", "  " + "-" * 54]
    for feed, count in by_feed.most_common(20):
        lines.append(f"  {feed:<48}{count:>7}")
    return "\n".join(lines)


def _as_dicts(findings: list[Finding]) -> list[dict]:
    return [
        {
            "feed_glob": f.feed_glob,
            "json_path": f.json_path,
            "leaf_key": f.leaf_key,
            "token": f.token,
            "patch": f.patch,
        }
        for f in findings
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RM-108 unresolved-template-token detector over vendored feeds."
    )
    parser.add_argument("--json", dest="json_path", help="dump the full report to PATH")
    parser.add_argument(
        "--roots", nargs="*", default=None, help="override the vendored roots"
    )
    parser.add_argument(
        "--regen-allowlist",
        action="store_true",
        help="rewrite display_key_allowlist.keys from this scan",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    findings = scan(args.roots)
    print(_table(findings))

    if args.regen_allowlist:
        keys, wrote = regen_allowlist(findings)
        verb = "rewrote" if wrote else "unchanged;"
        print(f"\n{verb} display_key_allowlist.keys -> {len(keys)} keys")

    if args.json_path:
        target = Path(args.json_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(
            target,
            json.dumps(
                {
                    "occurrences": len(findings),
                    "distinct_tokens": len({f.token for f in findings}),
                    "findings": _as_dicts(findings),
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
        )
        print(f"\nwrote {target}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
