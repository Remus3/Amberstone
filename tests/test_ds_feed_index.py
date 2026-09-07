"""Guard: the DS feed provenance index (tools/ds_feed_index.json) stays honest.

Three groups. The first five tests guard the index itself; T1 is their
META-GUARD, because without it an index that walked nothing would leave T2/T3
iterating an empty set and CI would stay green with the capability gone.

The second group guards ``fi.KNOWN_STATIC_BODY``, the reasoned-innocent set of
feeds whose canonical body is ALLOWED to sit unchanged between patch dirs. An
exemption list is worth exactly as much as the pressure that removes rows from
it, so every row is required to keep earning its place: its body must still be
static, its kind must come from the closed set, its remedy must point at a real
generator that still lacks a vintage stamp, and the population these tests
iterate is itself asserted non-empty. The day a generator starts stamping, the
row's own test reds and names it.

Critically, ALL THREE kinds carry their own falsifiable obligation, and that is
a deliberate repair rather than symmetry for its own sake. Until it landed only
``pending-vintage`` was checked against anything, so ``authored`` was a
one-word escape hatch: MEASURED, relabelling a feed with a real generator to
``("authored", "none")`` - or adding a brand new feed under that kind - left
this whole file green, including in the pre-regen state RM-213 exists to catch.
An exemption kind that asserts nothing is worse than no kind at all, because it
reads as a reasoned judgement. So ``authored`` must now prove no generator
writes the feed, ``upstream-static`` must prove the feed's own vintage stamp is
genuinely frozen across the two dirs, and ``pending-vintage`` keeps its
existing generator scan.

The third group is the one that guards the SHIPPED DATA rather than the
registry describing it (RM-213). Everything above can be green while every feed
in the live dir was copied forward from the previous patch and relabelled -
that is precisely the failure the index was built to expose, and until this
group existed nothing actually asserted it. It states the rule once: an
unchanged body requires a moved vintage, or a reasoned exemption.

That assertion is a NEGATIVE one - it proves an offender set is empty - so it
carries a POSITIVE CONTROL beside it. An empty offender set is produced just as
readily by a working guard as by a broken verdict pipeline, and that is not
hypothetical: MEASURED, swapping ``artifact_body_fingerprint`` for a
non-stripping hash turns every feed into 'body-moved', empties the offender set
and leaves this file green. The control pins the other side of the pipeline by
requiring the exempt feeds to still classify as unrefreshed.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ds_feed_index as fi  # noqa: E402

from agents.daemon_slayer.abilities import (  # noqa: E402
    artifact_refresh_verdict,
    artifact_vintage,
)
from test_ds_fixture_policy import RETIRED_FIXTURES  # noqa: E402

_DATA = _ROOT / "data" / "daemon_slayer"
_INDEX = json.loads((_ROOT / "tools" / "ds_feed_index.json").read_text(encoding="utf-8"))

# 16.14.1 is the live dir and is deliberately NOT hash-frozen here (see T2).
FROZEN_DIRS = ("16.10.1", "16.11.1", "16.12.1", "16.13.1")


def _live_patch() -> str:
    return (_DATA / "current.txt").read_text(encoding="utf-8").strip()


def test_index_covers_every_semver_dir_and_feed():
    """META-GUARD: the index must describe the whole SHIPPED feed surface.

    Shipped, not on-disk. A gitignored feed is a local cache that exists only on
    the machine that fetched it, so indexing one makes this pass here and fail
    in CI where it was never checked out - which is exactly what happened when
    the vendor augment snapshots were untracked on 2026-09-07. The generator
    filters the same way, so this compares like with like.
    """
    on_disk = {
        p.name
        for p in _DATA.iterdir()
        if p.is_dir() and fi.SEMVER_DIR.match(p.name)
    } - set(RETIRED_FIXTURES)
    assert set(_INDEX["dirs"]) == on_disk

    tracked = fi._tracked_feeds()
    assert tracked, "git could not list tracked feeds - this guard would be vacuous"

    rows = 0
    for patch, feeds in _INDEX["dirs"].items():
        expected = {
            p.name for p in (_DATA / patch).glob("*.json")
            if p.relative_to(fi.ROOT).as_posix() in tracked
        }
        assert set(feeds) == expected
        rows += len(feeds)
    assert rows > 0


def test_frozen_body_hashes_recompute():
    """Frozen dirs ONLY - deliberate.

    A hash lock on the live dir would red on ordinary work: commit e1b42e89
    moves 5 canonical bodies in the live dir alone. That trains the rubber
    stamp, so the lock covers only dirs that must never move again.
    """
    for patch in FROZEN_DIRS:
        for feed, row in _INDEX["dirs"][patch].items():
            got = fi.body_md5(json.loads((_DATA / patch / feed).read_text(encoding="utf-8")))
            assert got == row["body_md5"], f"{patch}/{feed} body moved"


def test_live_dir_stamps_match_their_directory():
    live = _live_patch()
    lag = set(_INDEX["known_stamp_lag"])
    for feed, row in _INDEX["dirs"][live].items():
        if row["stamp_field"] is None or feed in lag:
            continue
        assert row["declared_patch"] == live, f"{feed} declares {row['declared_patch']}"


def test_known_stamp_lag_entries_are_still_lagging():
    """A fixed feed must not sit in the exception list forever."""
    live = _live_patch()
    assert _INDEX["known_stamp_lag"], "exception list vanished"
    for feed in _INDEX["known_stamp_lag"]:
        row = _INDEX["dirs"][live][feed]
        assert row["stamp_field"] is not None, f"{feed} lost its stamp"
        assert row["declared_patch"] != live, (
            f"{feed} now declares {live} - it is fixed; drop it from known_stamp_lag"
        )


def test_walk_is_not_recursive():
    """Key-shape invariant: iterdir(), never rglob().

    No byte-ratio assertion - the semver dirs contain ZERO subdirectories, so
    any rglob-vs-iterdir ratio is 1.0 and would prove nothing.
    """
    for patch, feeds in _INDEX["dirs"].items():
        assert "/" not in patch and "\\" not in patch
        for feed in feeds:
            assert "/" not in feed and "\\" not in feed
    # NOTE (spec contradiction, disk wins): the spec said the literal string
    # "build_orders" must appear NOWHERE in the index. It cannot - the semver
    # dirs legitimately contain build_orders_sr/aram/arena.json feeds. The real
    # invariant is that the non-semver sibling DIRS are absent as keys, which
    # is what a stray rglob would have dragged in.
    excluded = {"build_orders", "laning_scenarios"}
    assert not (set(_INDEX["dirs"]) & excluded)
    for patch, feeds in _INDEX["dirs"].items():
        assert not (set(feeds) & excluded)
        for feed in feeds:
            assert not any(feed.startswith(x + ".") for x in excluded)


# --- KNOWN_STATIC_BODY hygiene ----------------------------------------------

_KINDS = frozenset({"authored", "upstream-static", "pending-vintage"})

# Read off the module rather than restated, so the guard cannot drift away from
# the stripper it is meant to track. _WALL_CLOCK IS the vintage-key set: these
# are exactly the keys canonical_body() removes before hashing, which is why a
# feed carrying one can prove its own re-run and a feed carrying none cannot.
_VINTAGE = frozenset(fi._WALL_CLOCK)


def _dir_key(name: str) -> tuple[int, ...]:
    """Semver order, not lexicographic - '16.9.1' must sort BELOW '16.10.1'."""
    return tuple(int(p) for p in name.split("."))


def _two_most_recent() -> tuple[str, str]:
    ordered = sorted(_INDEX["dirs"], key=_dir_key)
    return ordered[-2], ordered[-1]


def _body_md5(patch: str, feed: str) -> str:
    """Recomputed from DISK, deliberately not read out of the stored index.

    The stored sidecar is a generated artifact that goes stale between --write
    runs (it was measurably stale on three build_orders_* rows when this guard
    landed). A staleness check that trusts the possibly-stale artifact is the
    vacuity this whole module exists to prevent, so the bytes win.
    """
    return fi.body_md5(json.loads((_DATA / patch / feed).read_text(encoding="utf-8")))


def _feed_vintage_keys(patch: str, feed: str) -> set[str]:
    """Vintage keys present in a feed's own body, top level plus one down.

    Same reach as fi.extract_stamp, which is what makes _meta / meraki_items
    style nesting visible.
    """
    obj = json.loads((_DATA / patch / feed).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        return set()
    found = {k for k in obj if k in _VINTAGE}
    for val in obj.values():
        if isinstance(val, dict):
            found |= {k for k in val if k in _VINTAGE}
    return found


def _vintage_write_sites(rel: str) -> list[tuple[str, int]]:
    """Places a generator WRITES a vintage key, never places it merely names one.

    HOW PROSE IS EXCLUDED, which is the whole point of using ast over grep: only
    three positions count, and all three are places a key lands in a payload.
      * a string literal used as a KEY of a dict literal   {"fetched_at": ...}
      * the slice of a Store-context subscript             payload["fetched_at"] = ...
      * a call keyword                                     dict(fetched_at=...)
    A comment never reaches the AST at all, and a docstring or any other prose
    string is an ast.Constant in an expression position, never a key position,
    so neither can satisfy this scan.

    That distinction is load-bearing here rather than theoretical. MEASURED:
    tools/daemon_slayer_wiki_stats_extract.py:331 and
    tools/daemon_slayer_cdragon_spell_extract.py:270 both discuss ``fetched_at``
    in a docstring while writing no such key. A grep would call both generators
    fixed and red their exemptions; this scan returns zero sites for both.
    """
    tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
    sites: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value in _VINTAGE:
                    sites.append((str(key.value), key.lineno))
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            if isinstance(node.slice, ast.Constant) and node.slice.value in _VINTAGE:
                sites.append((str(node.slice.value), node.lineno))
        elif isinstance(node, ast.keyword) and node.arg in _VINTAGE:
            sites.append((node.arg, node.lineno))
    return sites


def _manifest_outputs(patch: str) -> set[str]:
    """Feed names the extractor itself declares it produced, off the live manifest.

    Machine-generated on-disk ground truth, not a hand-maintained allowlist.
    """
    obj = json.loads((_DATA / patch / "manifest.json").read_text(encoding="utf-8"))
    return {
        str(v).replace("\\", "/").rsplit("/", 1)[-1]
        for v in obj.get("outputs", {}).values()
    }


def _of_kind(kind: str) -> dict[str, str]:
    """Registry rows of one kind, as ``{feed: remedy}``."""
    return {
        feed: remedy
        for feed, (this_kind, remedy) in fi.KNOWN_STATIC_BODY.items()
        if this_kind == kind
    }


def _pending() -> dict[str, str]:
    return _of_kind("pending-vintage")


_TOOLS = _ROOT / "tools"


def _filename_write_sites(feed: str) -> list[str]:
    """Places under tools/ that name FEED in a path-construction position.

    The sibling of ``_vintage_write_sites`` on the other axis: that one asks
    which generator writes a KEY, this one asks which generator writes a FILE.
    Same reason for using ast over grep - a filename is discussed in prose all
    over this repo, and only two positions actually name an output path:

      * the RIGHT operand of a ``/`` join     patch_dir / "wiki_stats.json"
      * a bare assignment to a module name    REPORT_NAME = "ability_staleness.json"

    Both are exact-equality matches on a string CONSTANT, which is what excludes
    the near misses measured on this data. A comment never reaches the AST.
    A docstring or an argparse ``help=`` string mentioning the filename is a
    longer string and so never compares equal - MEASURED,
    tools/daemon_slayer_cdragon_spell_extract.py:685 and
    tools/daemon_slayer_wiki_stats_extract.py:868 both name their output file
    inside a help= string and neither is returned here. Nor is a dict KEY, which
    is what keeps tools/ds_feed_index.py - the registry under audit, where every
    exempted filename appears verbatim - from matching all seven of its own
    rows. A plain list element naming a feed is likewise excluded.

    KNOWN LIMIT, stated rather than hidden: a generator that assembles its
    output name dynamically (an f-string, a loop over a name list) is invisible
    to this scan. No generator in this repo does that today - the positive
    control in the pending-vintage test below is what keeps that measured rather
    than assumed.
    """
    sites: list[str] = []
    for py in sorted(_TOOLS.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - none today
            continue
        rel = py.relative_to(_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                right = node.right
                if isinstance(right, ast.Constant) and right.value == feed:
                    sites.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if node.value.value == feed and any(
                    isinstance(t, ast.Name) for t in node.targets
                ):
                    sites.append(f"{rel}:{node.lineno}")
    return sorted(set(sites))


def _vintage_value(patch: str, feed: str) -> str | None:
    """FEED's own generation-stamp VALUE in PATCH, or None.

    Read through ``abilities.artifact_vintage`` - the same extractor the RM-213
    verdict uses - so the frozen check below and the verdict cannot disagree
    about which key counts as the vintage.
    """
    path = _DATA / patch / feed
    if not path.is_file():
        return None
    return artifact_vintage(json.loads(path.read_text(encoding="utf-8")))[1]


def test_the_filename_write_site_scan_actually_finds_generators():
    """META-GUARD for ``_filename_write_sites``, and it is the load-bearing one.

    The authored obligation is a NEGATIVE assertion - it passes on an empty
    result - so a scanner that silently returned nothing would satisfy it for
    every feed on earth while proving nothing. That is the same vacuity class
    the authored hole itself belonged to, and re-introducing it one layer down
    would be no repair at all.

    The control is derived from the registry rather than hardcoded, so it cannot
    rot into a literal that stops describing this repo: every pending-vintage
    row NAMES a generator, which is a standing claim that the feed is machine
    written. The scan must therefore find a write site for each of them. If it
    finds none, the scan is broken - not the data - and the authored obligation
    above is worthless until it is fixed.

    The parse-count half catches the other way this goes quiet: a bad root, a
    renamed tools/ dir, or an rglob that matched nothing walks zero files and
    also returns no sites.
    """
    parsed = 0
    for py in sorted(_TOOLS.rglob("*.py")):
        try:
            ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - none today
            continue
        parsed += 1
    assert parsed >= 50, (
        f"the write-site scan walked only {parsed} parseable files under "
        f"{_TOOLS} - it is not looking at this repo, so every 'authored' row "
        "below is passing vacuously"
    )

    for feed in _pending():
        assert _filename_write_sites(feed), (
            f"{feed} is exempted as 'pending-vintage', which NAMES a generator "
            "and so asserts the feed is machine-written, yet the write-site "
            "scan finds nothing that writes it. The scan is broken (a generator "
            "that builds its output name dynamically is the known blind spot) - "
            "repair it before trusting test_authored_exemptions_have_no_"
            "generator_at_all, whose pass condition is an empty result"
        )


def test_authored_exemptions_have_no_generator_at_all():
    """An 'authored' row claims the feed is hand-curated. Prove it.

    This is the obligation that makes 'authored' a claim rather than an escape
    hatch. A hand-authored feed has no generator, so an unchanged body between
    patch dirs is its normal correct state and there is nothing to regenerate -
    but that reasoning only holds if the "no generator" half is true, and until
    this test landed nothing checked it. MEASURED before it did: relabelling
    cdragon_spell_stats.json to ('authored', 'none') left the file green, as did
    adding items_meraki.json under the same kind, and both are machine-written.

    FALSIFIED BY: any tools/**/*.py naming the feed in a path-construction
    position (see ``_filename_write_sites``). The moment a feed acquires a
    generator, this reds and prints the file:line that writes it - at which
    point the row is either pending-vintage with that generator as its remedy,
    or not exempt at all.

    NOT falsified by prose. The scan is deliberately blind to comments,
    docstrings and help= strings, because every one of those exists on this data
    and none of them writes a file.
    """
    authored = _of_kind("authored")
    assert authored, (
        "no 'authored' rows left in KNOWN_STATIC_BODY, so this obligation is "
        "vacuous - if the kind is genuinely retired, drop it from the closed set"
    )
    for feed in authored:
        sites = _filename_write_sites(feed)
        assert not sites, (
            f"{feed} is exempted as 'authored' - i.e. hand-curated with no "
            f"generator - but tools/ writes that filename at {sites}. It is "
            "machine-generated, so it cannot be authored: either re-file it as "
            "pending-vintage naming that generator as its remedy, or drop it "
            "from KNOWN_STATIC_BODY and regenerate the feed"
        )


def test_upstream_static_exemptions_have_a_genuinely_frozen_vintage():
    """An 'upstream-static' row claims there is nothing newer to fetch. Prove it.

    The observable that makes that claim honest is the feed's OWN generation
    stamp sitting byte-identical across the two dirs: the fetch is re-run, the
    upstream has not moved, so the stamp does not move either. That is a
    strictly stronger statement than 'the body did not move', which the row
    already had to satisfy, and it is what separates upstream-static from the
    items_meraki shape - identical body, but ``fetched_at`` MOVED
    2026-07-16 -> 2026-07-30, which is a genuine re-run and belongs out of the
    registry rather than in it under this kind.

    FALSIFIED BY, in either direction:
      * no vintage stamp in the live or the previous dir. A feed that cannot
        show a stamp at all is 'unprovable', not 'frozen' - it has no evidence
        to offer and must not borrow this kind's reasoning.
      * a stamp present in both and DIFFERENT. The vintage moved, so a real
        re-run happened; the feed is refreshed, not static.
    """
    prev, live = _two_most_recent()
    upstream = _of_kind("upstream-static")
    assert upstream, (
        "no 'upstream-static' rows left in KNOWN_STATIC_BODY, so this "
        "obligation is vacuous - if the kind is genuinely retired, drop it "
        "from the closed set"
    )
    for feed in upstream:
        before, after = _vintage_value(prev, feed), _vintage_value(live, feed)
        assert before is not None and after is not None, (
            f"{feed} is exempted as 'upstream-static', which asserts a FROZEN "
            f"vintage stamp, but it carries none in "
            f"{prev if before is None else live}. With no stamp there is "
            "nothing to freeze - the honest kind for a feed that cannot prove "
            "its own re-run is pending-vintage"
        )
        assert before == after, (
            f"{feed} is exempted as 'upstream-static' but its vintage MOVED "
            f"{before} -> {after} between {prev} and {live}. A moved stamp is "
            "proof of a real re-run, so the feed is refreshed rather than "
            "static and needs no exemption at all - drop it from "
            "KNOWN_STATIC_BODY"
        )


def test_static_body_exemptions_are_still_static():
    """A feed whose body MOVED must be dropped from the exemption list.

    Same shape as test_known_stamp_lag_entries_are_still_lagging: iterate the
    exception list and make each row prove the condition it claims, so a fixed
    feed cannot sit in the list forever.
    """
    prev, live = _two_most_recent()
    for feed in fi.KNOWN_STATIC_BODY:
        for patch in (prev, live):
            assert (_DATA / patch / feed).is_file(), (
                f"{feed} is exempted but absent from {patch}"
            )
        assert _body_md5(prev, feed) == _body_md5(live, feed), (
            f"{feed} body MOVED {prev} -> {live} - it is no longer static; "
            "drop it from KNOWN_STATIC_BODY"
        )


def test_static_body_exemption_kinds_are_from_the_closed_set():
    """No inventing a fourth category to make an awkward row fit."""
    for feed, (kind, _remedy) in fi.KNOWN_STATIC_BODY.items():
        assert kind in _KINDS, f"{feed} declares unknown kind {kind!r}"


def test_pending_vintage_exemptions_name_a_generator_that_still_lacks_a_vintage():
    """A pending-vintage row is a promise that the fix has NOT landed yet.

    Three checks, and the second is the one that makes the exemption
    self-refuting rather than permanent.

    1. The remedy must resolve to a real .py file. A remedy naming a
       non-existent generator is worse than no remedy - it reads as a plan
       while pointing nowhere.
    2. The FEED's own body must still carry no vintage key. This is the exact,
       per-feed observable: the moment the generator starts stamping this feed,
       the key appears in the body and this test reds, naming the row.
    3. The generator source must contain no vintage WRITE site, by the ast scan
       in _vintage_write_sites (see there for how prose is excluded).

    GRANULARITY, and this is a deliberate correction to the obvious design:
    check 3 is applied per-FEED, not per-FILE. A blanket "the generator emits no
    vintage key anywhere" rule is measurably WRONG on this data.
    tools/daemon_slayer_extract.py is a multi-output monolith: it writes 5
    declared outputs and already stamps manifest.json (extracted_at) plus
    arena_augments.json and items_meraki.json (fetched_at), while leaving
    scenarios.json unstamped. The file-level rule would red a correct exemption
    on day one. Nor can the write be attributed by enclosing function - the
    extracted_at write lives in build_manifest, whose outputs dict names
    scenarios.json alongside two other feeds.

    So attribution is decided by the manifest the extractor itself wrote: a feed
    co-produced with a sibling output that ALREADY carries a vintage stamp
    cannot have a source-level write attributed to it, and check 2 - which is
    exact and strictly stronger - carries it alone. Every other feed gets the
    full scan. The split is asserted below so it cannot quietly swallow the
    whole population.
    """
    _prev, live = _two_most_recent()
    outputs = _manifest_outputs(live)
    scanned: list[str] = []

    for feed, remedy in _pending().items():
        path = _ROOT / remedy
        assert path.is_file() and path.suffix == ".py", (
            f"{feed} names remedy {remedy!r}, which is not a file in this repo"
        )

        present = _feed_vintage_keys(live, feed)
        assert not present, (
            f"{feed} now carries vintage key(s) {sorted(present)} in {live} - its "
            "body can prove its own re-run, so drop it from KNOWN_STATIC_BODY"
        )

        siblings = outputs - {feed}
        co_stamped = feed in outputs and any(
            _feed_vintage_keys(live, s) for s in siblings
            if (_DATA / live / s).is_file()
        )
        if co_stamped:
            continue
        sites = _vintage_write_sites(remedy)
        assert not sites, (
            f"{remedy} now writes a vintage key {sites} - the stamp for {feed} "
            "has landed; drop it from KNOWN_STATIC_BODY"
        )
        scanned.append(feed)

    assert len(scanned) >= 2, (
        "the manifest co-production carve-out swallowed nearly every "
        f"pending-vintage row (only {scanned} got the source scan) - check 3 is "
        "close to vacuous, re-derive the attribution rule"
    )


def test_authored_and_upstream_static_entries_carry_no_remedy():
    """Kind and remedy must agree, in both directions.

    An authored or upstream-static feed has nothing to fix, so a remedy on one
    is a category error. A pending-vintage feed is defined by having a pending
    fix, so "none" on one is an empty promise.
    """
    for feed, (kind, remedy) in fi.KNOWN_STATIC_BODY.items():
        if kind in ("authored", "upstream-static"):
            assert remedy == "none", (
                f"{feed} is {kind} but names remedy {remedy!r}"
            )
        else:
            assert remedy != "none", f"{feed} is {kind} with no remedy"


def test_known_static_body_round_trips_into_the_index_json():
    """build_index() must emit the registry, and emit it JSON-STABLY.

    The emission is what lets --check drift-guard stored-vs-declared. The
    round-trip half is not ceremony: --check compares a stored index parsed
    from JSON against a freshly built one, so emitting tuples would compare
    unequal on every run and the guard would be permanently red, which is
    indistinguishable from having no guard. Serialization goes through the
    tool's own _dump, not a local json.dumps, so the test cannot pass against a
    serializer the tool does not use.
    """
    fresh = fi.build_index()
    assert "known_static_body" in fresh, "build_index() stopped emitting the registry"

    expected = {k: list(v) for k, v in fi.KNOWN_STATIC_BODY.items()}
    assert fresh["known_static_body"] == expected

    reparsed = json.loads(fi._dump(fresh))
    assert reparsed["known_static_body"] == fresh["known_static_body"], (
        "the registry does not survive the tool's own serialize/parse cycle, so "
        "--check would report drift on every run"
    )


def test_static_body_registry_and_index_population_are_non_empty():
    """META-GUARD for the whole group above, in the style of T1.

    Every KNOWN_STATIC_BODY test iterates the registry, and two of them read the
    live dir's feed rows. Empty either one and all of them pass while proving
    nothing, which is precisely how an exemption list rots into decoration.
    """
    assert len(fi.KNOWN_STATIC_BODY) >= 5, (
        f"registry collapsed to {len(fi.KNOWN_STATIC_BODY)} entries - the "
        "hygiene tests above are now near-vacuous"
    )
    assert _pending(), "no pending-vintage rows left, so the generator scan is vacuous"

    live = _two_most_recent()[1]
    assert len(_INDEX["dirs"][live]) >= 15, (
        f"the index carries only {len(_INDEX['dirs'][live])} rows for {live}"
    )
    assert len(_INDEX["dirs"]) >= 2, "need two dirs to compare bodies across"


# --- the shipped data itself: refreshed, or relabelled? (RM-213) ------------

# The two verdicts that mean "no re-generation evidence". Named rather than
# inlined so the meta-guard below can assert what is NOT in the set: a caller
# that quietly folded 'no-baseline' in here would turn every unpaired feed into
# a failure, and one that folded 'vintage-moved' in would red the two feeds that
# carry the strongest possible proof.
_OFFENDING_VERDICTS = frozenset({"frozen", "unprovable"})


def _prev_baseline(prev: str, feed: str) -> tuple[str | None, str | None]:
    """``(prior_body, prior_vintage)`` for FEED in the dir before the live one.

    SPLIT SOURCE, and each half is deliberate.

    The BODY baseline comes from the STORED index, not from a recompute off
    disk, so pruning an old patch dir cannot silently blind the guard: the row
    outlives the bytes, and a feed whose baseline vanished would otherwise
    quietly downgrade to 'no-baseline' and PASS. This is the opposite choice to
    ``_body_md5`` above, and both are right for what they measure - that helper
    asks "does the sidecar still describe the bytes on disk", so the bytes must
    win there; this one asks "what did the PREVIOUS patch look like", which is
    exactly the history the sidecar exists to preserve. The meta-guard below
    keeps the two honest by asserting the stored row still recomputes while the
    dir is present.

    The VINTAGE has no such choice available: the index stores only body_md5 /
    stamp_field / declared_patch, so it holds NO vintage at all and this half
    MUST be read from the previous dir's file on disk. It is read through
    ``abilities.artifact_vintage`` - the same extractor the verdict uses on the
    live doc - so the two sides of the comparison cannot disagree about which
    key counts. A pruned previous dir therefore yields a real body baseline and
    a None vintage, which reads as 'unprovable' rather than as a free pass.

    Comparability is not assumed: ``artifact_body_fingerprint`` and
    ``fi.body_md5`` strip the same key names at the same depth and truncate to
    the same 8 hex chars, which is why an index row can be handed straight in as
    ``prior_body``.
    """
    row = _INDEX["dirs"].get(prev, {}).get(feed)
    if row is None:
        return None, None
    path = _DATA / prev / feed
    if not path.is_file():
        return row["body_md5"], None
    return row["body_md5"], artifact_vintage(
        json.loads(path.read_text(encoding="utf-8"))
    )[1]


def _refresh_verdicts(prev: str, live: str) -> dict[str, str]:
    """Verdict per feed in the LIVE dir, computed by the engine helper."""
    verdicts: dict[str, str] = {}
    for feed in sorted(_INDEX["dirs"][live]):
        doc = json.loads((_DATA / live / feed).read_text(encoding="utf-8"))
        body, vintage = _prev_baseline(prev, feed)
        verdicts[feed] = artifact_refresh_verdict(
            doc, prior_body=body, prior_vintage=vintage
        )
    return verdicts


def test_previous_dir_supplies_a_usable_refresh_baseline():
    """META-GUARD for the assertion below, in the style of T1.

    The refresh test is a comparison, so it is only worth the baseline it
    compares against. Empty the index, prune the previous dir, or land a patch
    dir whose feeds share no names with the one before it, and every row
    degrades to 'no-baseline' - which PASSES by contract. The assertion would
    then be green, iterating a population of nothing, on the exact day the feed
    surface was disturbed enough to need it.

    So the pairing is asserted, not the row count: a live feed must have a row
    under the PREVIOUS patch specifically. The second half keeps the stored
    baseline honest while the dir it describes is still on disk, which is the
    one staleness window ``test_frozen_body_hashes_recompute`` does not cover -
    that test locks the four archived dirs and deliberately leaves the live and
    previous ones free to move.
    """
    prev, live = _two_most_recent()
    assert prev != live, "the two most recent dirs resolved to the same patch"

    paired = sorted(set(_INDEX["dirs"][live]) & set(_INDEX["dirs"].get(prev, {})))
    assert len(paired) >= 15, (
        f"only {len(paired)} of the {len(_INDEX['dirs'][live])} feeds in {live} "
        f"have a baseline row under {prev} ({paired}) - the refresh assertion "
        "is running on a near-empty population and proves almost nothing"
    )

    for feed in paired:
        if not (_DATA / prev / feed).is_file():
            continue
        assert _body_md5(prev, feed) == _INDEX["dirs"][prev][feed]["body_md5"], (
            f"the stored index row for {prev}/{feed} no longer recomputes off "
            "disk - the refresh baseline is stale, so re-run "
            "tools/ds_feed_index.py --write before trusting the verdicts"
        )


def test_an_unchanged_body_requires_a_moved_vintage():
    """THE ASSERTION (RM-213): a still body must carry proof it was re-run.

    For every feed in the live patch dir, classify it against the previous dir
    with ``abilities.artifact_refresh_verdict``. A feed OFFENDS when its body is
    byte-identical to the previous patch's and it cannot show a re-run behind
    that: verdict 'frozen' (the vintage stamp is there and did not move) or
    'unprovable' (there is no vintage stamp to move). Membership of
    ``fi.KNOWN_STATIC_BODY`` clears a feed, and the hygiene group above is what
    stops that list from turning into a rubber stamp.

    Why an unchanged body is NOT the defect on its own: champion_abilities.json
    and items_meraki.json both hold a byte-identical body across the current
    pair and both are innocent - their ``fetched_at`` moved, so a real fetch ran
    and returned identical bytes. Only body AND vintage together separate that
    from a copy-forward, which is why this test asserts on the verdict and never
    on the hash alone.

    'no-baseline' is an explicit PASS, never a skip, and it is exercised
    directly below rather than left to chance: every live feed happens to have a
    prior row today, so the branch is unreachable from disk data and would sit
    unasserted - and an unasserted pass-by-default branch is exactly how this
    guard would rot into a no-op the first time a dir is pruned.
    """
    prev, live = _two_most_recent()

    probe = sorted(_INDEX["dirs"][live])[0]
    doc = json.loads((_DATA / live / probe).read_text(encoding="utf-8"))
    assert artifact_refresh_verdict(
        doc, prior_body=None, prior_vintage=None
    ) == "no-baseline"
    assert artifact_refresh_verdict(
        doc, prior_body=None, prior_vintage="2026-01-01T00:00:00Z"
    ) == "no-baseline", "prior_body alone decides 'no-baseline', not the vintage"
    assert "no-baseline" not in _OFFENDING_VERDICTS, (
        "'no-baseline' means the caller supplied no baseline, which is a PASS "
        "by contract - folding it into the offending set punishes new dirs"
    )
    assert not _OFFENDING_VERDICTS & {"body-moved", "vintage-moved"}, (
        "a feed that MOVED has produced the re-generation evidence this test "
        "asks for and can never be an offender"
    )

    verdicts = _refresh_verdicts(prev, live)
    offenders = {
        feed: verdict
        for feed, verdict in verdicts.items()
        if verdict in _OFFENDING_VERDICTS and feed not in fi.KNOWN_STATIC_BODY
    }
    assert not offenders, (
        f"{len(offenders)} artifact(s) in {live} carry a body byte-identical to "
        f"{prev} with no evidence of a re-run: "
        + ", ".join(f"{feed}={verdict}" for feed, verdict in sorted(offenders.items()))
        + " ('frozen' = the generation stamp is present and did NOT move, so the "
        "file was copied forward and relabelled; 'unprovable' = the payload "
        "carries no generation stamp at all). Regenerate the feed, or - only "
        "with a written reason - add it to tools/ds_feed_index.KNOWN_STATIC_BODY"
    )


def test_exempt_feeds_still_classify_as_unrefreshed():
    """POSITIVE CONTROL for the assertion above. Without it that test is a no-op.

    The RM-213 assertion proves an offender set is EMPTY, and an empty set is
    exactly what a broken verdict pipeline produces too. MEASURED, and this is
    why this test exists rather than being belt-and-braces: replacing
    ``artifact_body_fingerprint`` with a non-stripping hash makes every live
    feed's fingerprint disagree with its stored ``prior_body``, so all 20 read
    'body-moved', the offender set empties, and every other test in this file
    stays green. The capability was gone and nothing here noticed.

    So this pins the other side. The seven exempt feeds are exempt precisely
    BECAUSE they cannot show a re-run - that is the entire content of their
    registry rows - so each one must still come back 'frozen' or 'unprovable'
    through the same ``_refresh_verdicts`` path the assertion above uses. Shared
    path is the point: a baseline-resolution break moves both together.

    FALSIFIED BY, each a real regression this catches:
      * a fingerprint that stops stripping vintage / prose / stamp keys, or a
        prior_body that stops being comparable with it - everything becomes
        'body-moved'.
      * ``artifact_vintage`` failing to parse a stamp it used to read - 'frozen'
        silently degrades to 'unprovable'.
      * the verdict ladder inverting or short-circuiting.

    BOTH verdicts are required to appear, and that is not decoration. 'frozen'
    is the only one that exercises the vintage comparison at all (body identical
    AND a stamp present that did not move); 'unprovable' is the only one that
    exercises the no-stamp branch. Assert only the union and either branch could
    rot away unnoticed.
    """
    prev, live = _two_most_recent()
    verdicts = _refresh_verdicts(prev, live)

    exempt = sorted(fi.KNOWN_STATIC_BODY)
    assert len(exempt) >= 5, (
        f"only {len(exempt)} exempt feeds - this control is near-vacuous"
    )

    seen: dict[str, str] = {}
    for feed in exempt:
        assert feed in verdicts, (
            f"{feed} is exempted but carries no verdict in {live} - the control "
            "population is not what the registry says it is"
        )
        seen[feed] = verdicts[feed]

    wrong = {f: v for f, v in seen.items() if v not in _OFFENDING_VERDICTS}
    assert not wrong, (
        "the RM-213 verdict pipeline is not classifying the exempt feeds as "
        "unrefreshed, so the assertion above is proving nothing: "
        + ", ".join(f"{f}={v}" for f, v in sorted(wrong.items()))
        + f". Every feed in KNOWN_STATIC_BODY is there BECAUSE it reads "
        f"{sorted(_OFFENDING_VERDICTS)} against the previous dir. A feed that "
        "now reads 'body-moved' or 'vintage-moved' either genuinely refreshed - "
        "drop its row - or, far more likely, the fingerprint / vintage / verdict "
        "logic broke and this whole file went quietly vacuous"
    )

    assert set(seen.values()) == _OFFENDING_VERDICTS, (
        f"the exempt feeds cover only {sorted(set(seen.values()))} of the two "
        f"offending verdicts {sorted(_OFFENDING_VERDICTS)}. 'frozen' is the "
        "only verdict that exercises the vintage comparison and 'unprovable' "
        "the only one that exercises the no-stamp branch, so losing either "
        "leaves half the pipeline unasserted"
    )
