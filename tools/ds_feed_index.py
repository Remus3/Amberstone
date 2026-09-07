"""DS feed provenance index - content-addressed body hashes + declared stamps.

Three design points that MUST survive any later "simplification":

(a) The index is CONTENT-ADDRESSED and is deliberately NOT a payload-patch
    compare. The sanctioned patch-refresh ritual sed-flips `_patch` on
    copied-forward wiki_stats / wiki_ability_stats, so a stamp-only compare
    passes a feed whose body never actually moved. Only a body hash that
    ignores the stamp can tell "refreshed" from "relabelled".

(b) For AUTHORED files the correct invariant is "body changed implies stamp
    changed" - NOT "stamp equals directory". An authored feed can sit
    unchanged and correct in a newer patch dir while still declaring the
    patch it was authored against. That is why enchanter_items.json is
    exception-listed in known_stamp_lag rather than reported red.

(c) An unchanged BODY is likewise not a defect on its own - only an unchanged
    body under a REWRITTEN vintage stamp is. KNOWN_STATIC_BODY is the
    reasoned-innocent set for the former, and it carries a per-row remedy so it
    cannot decay into a decorative allowlist. Its hygiene tests live in
    tests/test_ds_feed_index.py and are what force a row back out again.

Modes:
    python tools/ds_feed_index.py --write    regenerate the index
    python tools/ds_feed_index.py --check    recompute + diff, exit 1 on any
                                             disagreement

Read-only in --check. Exit 0 = in sync, exit 1 = drift, exit 2 = bad usage.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DATA = ROOT / "data" / "daemon_slayer"
_CURRENT_TXT = _DATA / "current.txt"
_INDEX_PATH = Path(__file__).resolve().parent / "ds_feed_index.json"

SEMVER_DIR = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

# Stripped BY KEY NAME ONLY. Never a value-shape regex: wiki_ability_stats
# carries bare numeric strings (speed_raw='1800', cast_time_raw fractions) that
# any "looks like a version or a number" matcher would eat.
_WALL_CLOCK = (
    "fetched_at", "generated_at", "extracted_at", "_generated_at",
    "source_generated_at", "timestamp",
)
_PROSE = ("generated_note", "_note")
_STAMP = (
    "version", "patch", "_patch", "rc_patch", "source_patch", "ddragon_version",
    "patch_segment", "_patch_segment", "meraki_content_patch",
    "_meraki_content_patch", "content_patch",
)
_STRIP = frozenset(_WALL_CLOCK + _PROSE + _STAMP)

# Measured facts (2026-07-19), each verified against the 16.14.1 dir on disk.
KNOWN_STAMP_LAG = {
    "cherry_augments.json":
        "declares rc_patch 16.10.1 - Arena augment set copied forward unchanged "
        "since 16.10.1; authored feed, body has not moved",
}
# mayhem_augment_stats.json was dropped 2026-09-07: the six snapshots were
# untracked and purged from history ahead of the public flip (a vendor's dataset
# this repo has no right to redistribute - the Share package's own licence had
# already said so). The file is now a LOCAL cache that core/augment_external_
# source.py fetches and degrades without, so it is not a shipped feed and cannot
# carry an index row. Its old entry read: "declares rc_patch 16.10.1 - Mayhem
# augment stats sourced at 16.10 and carried forward; event-mode feed with no
# newer upstream."
# enchanter_items.json was dropped 2026-07-26: the 16.14.1 copy declares
# _meta.patch 16.14.1 (restamped at ENGINE 1.230.0, commit f7c49de5), so it is
# no longer lagging and the guard test correctly rejected the stale entry. The
# 16.10.1 through 16.13.1 copies still declare 16.9.1; that is historical-dir
# lag, which this list does not track.

# An UNCHANGED canonical body is not by itself a defect - it is only a defect
# when the feed's vintage stamp was rewritten with no re-run behind it. This
# registry is the reasoned-innocent set: the feeds whose static body is the
# CORRECT result. Everything not listed is reported red.
#
# The body-identical set splits three ways and only the third needs an
# exemption. Re-derive it from the enforcing group in
# tests/test_ds_feed_index.py rather than trusting a census written here - a
# recited count goes stale on the next regen, which is exactly how the previous
# version of this comment became wrong inside a single session.
#
# NOT listed, deliberately, and each for a different reason:
#
#   champion_abilities.json / items_meraki.json - innocent and PROVABLE from
#     their own body, so there is nothing to exempt. fetched_at moved
#     2026-07-16 -> 2026-07-30 in both, i.e. a genuine re-run that returned
#     identical bytes. A moved vintage stamp is exactly the evidence the
#     pending-vintage rows below cannot produce.
#
#   ability_staleness.json - the FOUNDING instance of the defect class, and no
#     longer a live finding. Its generator tools/ds_wiki_staleness_check.py
#     writes _generated_at in the SAME dict literal as _patch (around :454-455),
#     so the stamp cannot be absent from a real run - yet at 16.15.1 it sat
#     frozen at 2026-07-18T11:59:22Z across both dirs. A frozen stamp from a
#     generator that always stamps is positive proof of a copy-forward, not
#     absence of proof. Exempting it would have been dishonest, so it was
#     REGENERATED instead (2026-08-16, RM-213); it now carries a moved stamp and
#     needs no entry. It is named here because it is why this registry exists,
#     NOT because it is currently red - if it ever reads frozen again, that is a
#     regression and the answer is another regen, never an exemption.
KNOWN_STATIC_BODY: dict[str, tuple[str, str]] = {
    # filename: (kind, remedy)
    #   kind in {"authored", "upstream-static", "pending-vintage"}
    #   remedy: "none" for authored / upstream-static, else the repo-relative
    #           generator path that must start emitting a vintage key.

    # Arena augment set fetched once at 16.10.1 and carried forward since.
    # fetched_at is frozen at 2026-05-18T03:58:33 in BOTH dirs, which is
    # consistent rather than suspicious: there is no newer upstream to fetch,
    # which is the same root cause that already puts it in KNOWN_STAMP_LAG.
    "cherry_augments.json": ("upstream-static", "none"),

    # mayhem_augment_stats.json was dropped here too on 2026-09-07, for the
    # reason recorded above KNOWN_STAMP_LAG: it is no longer a shipped feed.

    # AUTHORED curation, verified this session: there is NO generator for it
    # anywhere. A grep of tools/ for the filename returns only this module's
    # own prose and the generated index sidecar, and every other reference in
    # the repo READS it (agents/daemon_slayer/hps.py:181 loads the snapshot;
    # the enchanter tests read the same path). It is 34 hand-curated rows, so
    # an unchanged body between patches is its normal, correct state and it can
    # never acquire a vintage stamp.
    "enchanter_items.json": ("authored", "none"),

    # Genuinely INNOCENT but unprovable from its own body, which carries no
    # vintage key at all. Verified this session: it is named in the 16.15.1
    # manifest "outputs", its mtime (2026-07-30T18:24:22) matches that
    # manifest's extracted_at to the second, and BOTH manifests record the
    # identical sources.lolmath_scenarios_chunk (370vfc_ounngn.js, 734373
    # bytes), so the upstream SPA bundle did not rebuild between extracts and a
    # byte-identical body is the CORRECT extract result. The remedy is a
    # vintage stamp in the extractor, not a regen: the extractor writes this
    # file only as part of a whole-snapshot run, never in isolation.
    "scenarios.json": ("pending-vintage", "tools/daemon_slayer_extract.py"),

    # The two feeds named in point (a) of this module's docstring: the
    # sanctioned patch-refresh ritual sed-flips _patch on them while the body
    # is copied forward, so a still body is expected. Neither payload carries a
    # vintage key, so a real re-run cannot be told from a relabel - which is
    # precisely the gap the remedy closes.
    "wiki_ability_stats.json":
        ("pending-vintage", "tools/daemon_slayer_wiki_ability_extract.py"),
    "wiki_stats.json":
        ("pending-vintage", "tools/daemon_slayer_wiki_stats_extract.py"),

    # CDragon per-spell stat sidecar. Body carries no vintage key, so the same
    # relabel-vs-refresh ambiguity applies.
    "cdragon_spell_stats.json":
        ("pending-vintage", "tools/daemon_slayer_cdragon_spell_extract.py"),
}


def live_patch() -> str:
    """Default patch, resolved from current.txt. NEVER a literal."""
    return _CURRENT_TXT.read_text(encoding="utf-8").strip()


def semver_dirs(root: Path, retired: frozenset[str]) -> list[str]:
    """Top-level semver dirs only. iterdir(), never rglob().

    This is what keeps data/daemon_slayer/build_orders/ and the LFS-tracked
    data/daemon_slayer/laning_scenarios/ out of the index.
    """
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and SEMVER_DIR.match(p.name) and p.name not in retired
    )


def canonical_body(obj):
    """Recursively drop wall-clock, prose, and stamp keys by NAME."""
    if isinstance(obj, dict):
        return {k: canonical_body(v) for k, v in obj.items() if k not in _STRIP}
    if isinstance(obj, list):
        return [canonical_body(v) for v in obj]
    return obj


def body_md5(obj) -> str:
    blob = json.dumps(canonical_body(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:8]


def extract_stamp(obj) -> tuple[str | None, str | None]:
    """Computed, not tabulated: the declared patch stamp and the key it came from.

    Collects every stamp-group key at the top level plus one level down (this
    is what reaches _meta.patch and meraki_items.content_patch), keeps only
    values with exactly 3 dot-separated segments, and tie-breaks
    lexicographically by key name. Measured: zero ties across all 20 feeds.
    """
    if not isinstance(obj, dict):
        return None, None
    found: dict[str, str] = {}
    for key, val in obj.items():
        if key in _STAMP and isinstance(val, str):
            found[key] = val
        if isinstance(val, dict):
            for k2, v2 in val.items():
                if k2 in _STAMP and isinstance(v2, str):
                    found[f"{key}.{k2}"] = v2
    ok = {k: v for k, v in found.items() if len(v.split(".")) == 3}
    if not ok:
        return None, None
    name = sorted(ok)[0]
    return name, ok[name]


def _tracked_feeds() -> set[str]:
    """Repo-relative posix paths of the feed files git actually tracks.

    The index is a provenance baseline for what this repository SHIPS, so it
    must enumerate tracked files rather than whatever happens to be on this
    disk. An untracked feed is a local cache - it exists on the machine that
    fetched it and nowhere else - and indexing one makes `--check` pass locally
    and fail in CI, where the file was never checked out. That is exactly what
    happened when the vendor augment snapshots were untracked ahead of the
    public flip.

    Returns an empty set if git cannot answer, and the caller then falls back to
    the on-disk enumeration: degrading to the old behaviour is better than
    emitting an EMPTY index, which would read as "no drift" forever.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "data/daemon_slayer"],
            capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def build_index() -> dict:
    sys.path.insert(0, str(ROOT / "tests"))
    from test_ds_fixture_policy import RETIRED_FIXTURES  # type: ignore

    tracked = _tracked_feeds()
    dirs: dict[str, dict] = {}
    for patch in semver_dirs(_DATA, frozenset(RETIRED_FIXTURES)):
        feeds: dict[str, dict] = {}
        for path in sorted((_DATA / patch).glob("*.json")):
            if tracked and path.relative_to(ROOT).as_posix() not in tracked:
                continue
            obj = json.loads(path.read_text(encoding="utf-8"))
            field, declared = extract_stamp(obj)
            feeds[path.name] = {
                "body_md5": body_md5(obj),
                "stamp_field": field,
                "declared_patch": declared,
            }
        dirs[patch] = feeds
    return {
        "generated_from_current_txt": live_patch(),
        "known_stamp_lag": dict(KNOWN_STAMP_LAG),
        # Emitted as LISTS, not tuples, and that is load-bearing rather than
        # stylistic: --check compares the stored index (parsed from JSON, where
        # a tuple has already become a list) against this freshly built one. A
        # dict of tuples would therefore never compare equal and the guard
        # below would report drift on every single run, which is the same as
        # having no guard at all.
        "known_static_body": {k: list(v) for k, v in KNOWN_STATIC_BODY.items()},
        "dirs": dirs,
    }


def _dump(index: dict) -> str:
    return json.dumps(index, indent=2, sort_keys=True) + "\n"


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if mode not in ("--write", "--check"):
        print(f"usage: {Path(__file__).name} [--write|--check]", file=sys.stderr)
        return 2

    fresh = build_index()
    rows = sum(len(v) for v in fresh["dirs"].values())

    if mode == "--write":
        tmp = _INDEX_PATH.with_suffix(".json.tmp")
        # newline="" so Python does NOT translate to CRLF on Windows. The index
        # is a tracked .json and .gitattributes pins it to eol=lf, so a default
        # write makes tests/test_text_line_endings.py red on the machine that
        # regenerated it - measured 2026-09-07, one --write did exactly that.
        tmp.write_text(_dump(fresh), encoding="utf-8", newline="")
        tmp.replace(_INDEX_PATH)
        print(f"WROTE {_INDEX_PATH.name}: {len(fresh['dirs'])} dirs, {rows} rows")
        return 0

    if not _INDEX_PATH.exists():
        print(f"NO index at {_INDEX_PATH} - run --write", file=sys.stderr)
        return 1
    stored = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))

    drift: list[str] = []
    if stored.get("generated_from_current_txt") != fresh["generated_from_current_txt"]:
        drift.append(
            f"  current.txt: stored={stored.get('generated_from_current_txt')} "
            f"-> live={fresh['generated_from_current_txt']}"
        )
    if stored.get("known_stamp_lag") != fresh["known_stamp_lag"]:
        drift.append("  known_stamp_lag: stored differs from tool-declared")
    if stored.get("known_static_body") != fresh["known_static_body"]:
        drift.append("  known_static_body: stored differs from tool-declared")

    s_dirs, f_dirs = stored.get("dirs", {}), fresh["dirs"]
    for patch in sorted(set(s_dirs) | set(f_dirs)):
        s_feeds, f_feeds = s_dirs.get(patch, {}), f_dirs.get(patch, {})
        for feed in sorted(set(s_feeds) | set(f_feeds)):
            s_row, f_row = s_feeds.get(feed), f_feeds.get(feed)
            if s_row is None:
                drift.append(f"  {patch}/{feed}: MISSING from index")
            elif f_row is None:
                drift.append(f"  {patch}/{feed}: in index, gone from disk")
            elif s_row != f_row:
                drift.append(f"  {patch}/{feed}: {s_row} -> {f_row}")

    print(f"index {len(f_dirs)} dirs / {rows} rows | patch {fresh['generated_from_current_txt']}")
    if drift:
        print("\n-- DRIFT --")
        for line in drift:
            print(line)
    print("\nRESULT:", "DRIFT" if drift else "IN SYNC")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
