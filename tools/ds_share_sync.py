"""Sync the Daemon Slayer external-review package under ``Share/src``.

The ``Share/`` folder is a self-contained, external-facing mirror of the DS
engine: the engine source, the DS tooling, and the versioned reference-data
snapshot, plus authored handoff docs. This script is the single durable
"update path" that keeps ``Share/src`` in lock-step with the live engine.

What it mirrors into ``Share/src`` (deterministic - same input -> same output):
  * ``agents/daemon_slayer/**``  (engine + tests, less the host-dependent test
    modules - see ``_is_host_dependent_test``) -> ``Share/src/agents/daemon_slayer/``
  * a curated set of DS tools     -> ``Share/src/tools/``
  * ``data/daemon_slayer/<patch>/**`` (less ``_EXCLUDED_SNAPSHOT_FILES``),
    ``current.txt``, and the patch-independent engine tables in
    ``_ROOT_DATA_FILES`` -> ``Share/src/data/daemon_slayer/``
  * the host assets in ``_HOST_ASSET_FILES``, at their SAME repo-relative path
    (currently ``web/data/champion_aliases.json`` -> ``Share/src/web/data/``),
    because the mirrored tooling resolves them off the package root

Two transforms are applied to copied ``.py`` text so the package presents the
engine on its own technical merits:
  1. ``__init__.py`` is replaced by a clean stub (a neutral package docstring +
     the ``ENGINE_VERSION`` constant). The live ``__init__.py`` is a ~4600-line
     embedded changelog with no functional code beyond the version constant;
     the package's release history lives in ``Share/CHANGELOG.md`` instead.
  2. ``_SCRUB`` rewrites a small, bounded set of development-context comment
     phrases to neutral wording. Data JSON is copied verbatim (it is data).

It also keeps the authored handoff docs' MECHANICAL version/patch anchors fresh:
the ``ENGINE_VERSION = "X"`` literal, the explicit ``data patch `X` `` /
``"patch": "X"`` anchor phrases, the ``Share/README.md`` header line, the
``current.txt`` prose mention, and the manifest path citation in
``Share/README.md`` + ``Share/docs/*.md`` are rewritten to the live values on a
plain run and verified by ``--check`` - the same hard gate as the ``src``
mirror, so an engine bump that forgets the docs fails CI. See
``_doc_anchor_rules`` for the covered/excluded split (the excluded forms are
placeholders and frozen history, not gaps).
Only those literal anchors are auto-maintained; the SEMANTIC prose
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
import ast
import json
import re
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SHARE = _REPO / "Share"
_SRC = _SHARE / "src"
_INGEST = _SHARE / "lolmath_ingest"
_PATCH = "16.15.1"

# Sentinel that tells a mirrored test it is running inside the SHIPPED package
# rather than the host repo, so the handful of guards whose subject is a host
# artifact (the engine CHANGELOG, the data/meta and data/meta_build upstream
# feeds) can skip instead of failing.
#
# RM-221: the discriminator those tests used to carry was
# ``"share" in (p.name.lower() for p in Path(__file__).resolve().parents)`` - it
# keyed on an ANCESTOR DIRECTORY NAME, which is the one thing about a downloaded
# package the recipient controls and routinely changes. Measured 2026-08-16 on
# the same clean copy: 58 failures when the directory is still called ``Share``,
# 73 when it is not, from identical bytes. A file the generator emits travels
# with the package and cannot be renamed out from under it. Presence (not
# absence) is the signal, so deleting a host artifact in the main tree still
# fails there, which is what those guards exist to catch.
#
# The four sites look for it by walking ``Path(__file__).resolve().parents``
# rather than indexing to a fixed depth. Deliberate on two counts: it survives a
# layout change, and ``tests/test_skip_condition_hygiene.py`` credits a
# NON-indexed ``.parents`` walk as a tree-shape capability question - which its
# own source names "is this the Share mirror" - so the four skips stay legal
# there on the guard's own terms, with no reviewed exemption bought for them.
_MIRROR_MARKER_REL = "SHARE_MIRROR"
_MIRROR_MARKER_BODY = (
    "This directory is the generated Daemon Slayer review mirror.\n"
    "Written by tools/ds_share_sync.py. Its presence is how the engine's own\n"
    "tests tell the shipped package apart from the host repository.\n"
)

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

# Calculator-ingest slice (Share/lolmath_ingest). Its authored files pin the
# engine version + patch as plain semver tokens, and dist/ carries the one-shot
# bundle built from the Share/src data snapshot. Both are kept in lock-step by
# write mode and guarded by --check (item-378 sidequest: the subdir went 12
# engine minors + 1 patch stale because the check did not cover it). Engine
# versions are single-leading-digit semvers (1.x.y); data patches are
# two-plus-digit (16.x.y) - disjoint shapes, so two generic token rules cover
# every anchor in these files (verified: the only semver-shaped tokens present
# are the engine + patch pins).
_INGEST_DOC_FILES: tuple[str, ...] = (
    "README.md",
    "INGEST_SPEC.md",
    "daemon_slayer_bundle.d.ts",
    "build_bundle.py",
)
_INGEST_BUNDLE_REL = "dist/daemon_slayer_bundle.json"
_INGEST_GENERATED_NOTE = "static one-shot export"

# DS engine tooling copied into the package (extractors + serving + the
# patch-bump prefilter/inspect scanners). This script is intentionally NOT in
# the list (it is repo-internal maintenance tooling).
#
# ``ds_feed_index.py`` is NOT optional tooling, it is a TEST DEPENDENCY:
# ``agents/daemon_slayer/tests/test_artifact_patch_marker_guard.py`` loads it by
# absolute path off the package root to read ``KNOWN_STAMP_LAG``, deliberately
# importing the known-stamp-lag exception list rather than restating it. It was
# absent from this tuple, so two of that module's tests raised
# ``FileNotFoundError`` inside the shipped package while ``Share/README.md``
# advertised the suite as exiting green offline. It is stdlib-only and does no
# file I/O at import time, so the ``.py`` alone is sufficient - its sidecar
# ``tools/ds_feed_index.json`` is a generated index guarded by
# ``_INDEX_PATH.exists()`` and is deliberately not mirrored (``--check`` in the
# package prints "run --write" instead of raising).
_DS_TOOLS: tuple[str, ...] = (
    "ds_feed_index.py",
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

# Mirrored-test exclusions, applied only inside ``agents/daemon_slayer/tests/``.
#
# RM-221 (2026-08-16): this frozenset is now the BY-NAME half of
# ``_is_host_dependent_test``. The other half is two rules keyed on what a
# module imports or reads, and the rules are the part that stops the list
# falling behind the suite again - which is exactly what happened here. Add a
# name only when no rule covers the case, and say in the comment why.
#
# These nine modules cannot pass inside an engine-only package by construction:
# eight import the host application's ``core.*`` wrappers (build_order,
# build_planner.coherence, daemon_slayer_client, daemon_slayer_resolver), and
# ``test_abilities_content_freshness.py`` reaches host-only ability-source data
# through its extractor import. ``core/`` is host-repo-only by design and is
# deliberately not shipped, so all nine raise at IMPORT time.
#
# HISTORICAL NOTE: the ninth was originally attributed to the missing web asset
# ``web/data/champion_aliases.json``. That asset now ships (see
# ``_HOST_ASSET_FILES``), so the extractor import itself is no longer the
# blocker; the module stays excluded on its remaining host-data reach, and
# re-admitting it is a separate, measured decision rather than a side effect of
# this fix.
#
# That is what makes them a shipped defect rather than an accepted gap: a pytest
# import failure is a COLLECTION error, and a collection error aborts the whole
# session. The command the package README hands an external reviewer
# (``python -m pytest agents/daemon_slayer/tests -q``) therefore ran ZERO of the
# ~9000 tests and exited ``Interrupted: 9 errors during collection``. Excluding
# them costs the package nothing it could otherwise have: they pin the host-side
# integration seam, not engine math.
_HOST_DEPENDENT_TESTS: frozenset[str] = frozenset({
    # -- Collection-aborting host imports (the original nine, item R154) --
    "test_abilities_content_freshness.py",
    "test_build_recommendation_p1l5.py",
    "test_coherence_burst_score_l1.py",
    "test_double_pen_mutex.py",
    "test_r144_mirror_slice_b.py",
    "test_r144_mirror_slice_c.py",
    "test_r144_mirror_slice_d.py",
    "test_r144_mirror_slice_e.py",
    "test_unique_passive_key_phase4d.py",
    # -- RM-115 (ENGINE 1.250.0, 2026-07-25): the seam-reachability pair. Both
    # import core.daemon_slayer_client at module level, and that is inherent to
    # what they assert rather than incidental - their whole subject is whether
    # an engine seam parsed by server.py is expressible through the HOST client
    # dispatcher. The client is host-only by design (the shipped package is the
    # engine, not RC's integration layer), so these can never be mirror-safe
    # and are excluded by name rather than refactored.
    "test_assumed_share_exposure.py",
    "test_route_seams_reach_the_client.py",
    "test_route_seams_reach_the_client_per_route.py",
    # -- RM-201 (ENGINE 1.278.0, 2026-08-15): same class again. The CC-floor
    # route seam's guard asserts the seam is expressible through the HOST
    # client, and its third gate is precisely that the client carries the
    # ``include_conditional`` axis the floor is inert without - so the
    # core.daemon_slayer_client import IS its subject. Note its RM-200 sibling
    # is deliberately NOT listed: that file reaches the client only inside a
    # function body, so it mirrors safely and excluding it would be a
    # cargo-culted pair.
    "test_cc_floor_route_seam_rm201.py",
    # -- R193 (ENGINE 1.255.0, 2026-07-26): same class as the RM-115 pair. It
    # asserts that the omnivamp EHP seam parsed by server.py is expressible
    # through the HOST client, so importing core.daemon_slayer_client is its
    # subject rather than an accident.
    "test_route_omnivamp_seam_r193.py",
    # -- R194 slice A (RM-116 part a): the RANKER lane of the same omnivamp
    # seam, plus the score_by="sustain" transport. Same class again - it asserts
    # the (route, seam) pair is expressible through the HOST client, so the
    # core.daemon_slayer_client import is its subject, not an accident.
    "test_r194_sustain_ranker_seam.py",
    # -- RM-118 (ENGINE 1.264.0, 2026-07-29): the RANKER lane of the wielder HSP
    # item amp. Exact same class as the R194 sibling above - it asserts the
    # ('/rank-tank', 'assume_hsp_amp') pair is expressible through the HOST client
    # (rank_tank_for) and imports core.daemon_slayer_client plus the per-route
    # reachability helper at module level, so the import is its subject, not an
    # accident. Host-only; the shipped package is the engine, not RC's client.
    "test_rank_ehp_hsp_amp_rm118.py",
    # -- RM-118 (ENGINE 1.270.0, 2026-08-02): the TRANSPORT half of the mana ->
    # damage coupling lever. Same class as every entry above it - it asserts the
    # ('/rank-tank', 'apply_mana_damage_coupling') pair is reachable end to end
    # through the HOST client (rank_tank_for) as well as the route, so importing
    # core.daemon_slayer_client is its subject rather than an accident. The
    # registry + engine half (test_mana_damage_coupling_rm118.py) imports no host
    # package and DOES ship in the mirror.
    "test_mana_coupling_transport_rm118.py",
    # -- RM-118 (ENGINE 1.265.0, 2026-07-29): the HYBRID (bruiser) ranker half of
    # the same wielder HSP item-amp wire. Asserts the ('/rank-bruiser',
    # 'assume_hsp_amp') pair is expressible through the HOST client
    # (rank_bruiser_for) and imports core.daemon_slayer_client plus the per-route
    # reachability helper at module level - the import is its subject, not an
    # accident. Host-only, same reason as its EHP-ranker sibling above.
    "test_rank_hybrid_hsp_amp_rm118.py",
    # -- RM-118 residual (ENGINE 1.266.0, 2026-07-29): the four EHP survivability
    # seams (assume_passive_flat_mitigation / assume_passive_health_stacks /
    # assume_item_revive / assume_item_stasis). Same class as the two RM-118
    # siblings above - it asserts each (route, seam) pair is expressible through
    # the HOST client (ehp_for / rank_tank_for) and, just as load-bearing, that
    # rank_tank_for does NOT express the three scalar-only seams; it imports
    # core.daemon_slayer_client plus the per-route reachability helper at module
    # level, so the host import is its subject, not an accident.
    "test_ehp_survivability_route_seams_rm118.py",
    # -- RM-118 residual (ENGINE 1.267.0, 2026-07-30): the three RUNE lanes
    # (apply_rune_offense_grants / apply_rune_self_heal / apply_rune_shield_grants)
    # across /dps, /ehp, /rank-tank, /hybrid and /rank-bruiser. Same class as the
    # RM-118 sibling above - it asserts each (route, seam) pair is expressible
    # through the HOST client (dps_for / ehp_for / rank_tank_for / hybrid_for /
    # rank_bruiser_for) and, just as load-bearing, that the two EHP-family clients
    # do NOT express the damage-axis offense lane; it imports
    # core.daemon_slayer_client plus the per-route reachability helper at module
    # level, so the host import is its subject, not an accident.
    "test_rune_lane_route_seams_rm118.py",
    # -- RM-118 residual (ENGINE 1.268.0, 2026-07-30): the two VAMP lanes
    # (assume_crit_weighted_vamp / assume_cleave_lifesteal) plus the
    # ``targets_in_rotation`` transport the cleave lane needs, all on /ehp alone.
    # Same class as the RM-118 sibling above - it asserts each (route, seam) pair
    # is expressible through the HOST client (ehp_for) and, just as load-bearing,
    # that rank_tank_for / hybrid_for / rank_bruiser_for / dps_for / sustain_for
    # do NOT express either seam, since compute_ehp is their sole engine owner;
    # it imports core.daemon_slayer_client plus the per-route reachability helper
    # at module level, so the host import is its subject, not an accident.
    "test_vamp_lane_route_seams_rm118.py",
    # -- RM-118 residual: the FIVE per-item shield opt-ins (assume_kaenic_shield
    # / assume_eclipse_shield / assume_chainlaced_shield / assume_seraphs_shield
    # / assume_fimbulwinter_shield) on /ehp alone. Same class as the RM-118
    # sibling above - it asserts each (route, seam) pair is expressible through
    # the HOST client (ehp_for) and, just as load-bearing, that rank_tank_for /
    # hybrid_for / rank_bruiser_for / dps_for / sustain_for do NOT express any of
    # the five, since compute_ehp is their sole engine owner; it imports
    # core.daemon_slayer_client plus the per-route reachability helper at module
    # level, so the host import is its subject, not an accident.
    "test_per_item_shield_route_seams_rm118.py",
    # -- RM-118 residual (ENGINE 1.271.0, 2026-08-04): the four genuinely
    # wireable stranded seams (apply_crit_chance_overrides on /dps,
    # apply_ability_hsp_amp on /hps, apply_cast_rate_propensity_prior +
    # assume_ms_utility on /hybrid and /rank-bruiser). Same class as every
    # entry above - it asserts each (route, seam) pair is expressible through
    # the HOST client (dps_for / hps_for / hybrid_for / rank_bruiser_for) and,
    # just as load-bearing, that the non-owning routes do NOT carry the keys;
    # it imports core.daemon_slayer_client plus the per-route reachability
    # helper at module level, so the host import is its subject, not an
    # accident.
    "test_stranded_lane_route_seams_rm118.py",
    # The behavioural half of the same drain: it drives the HOST client against
    # the live engine to prove each EHP-family seam actually does something.
    # Host-only for the same reason as its two siblings - the shipped package is
    # the engine, not RC's integration layer.
    "test_ehp_family_seams_reach_the_client_rm115.py",
    # The same behavioural half for the RM-115 TAIL block (/dps, /ability-dps,
    # /burst, /rank, /rank-mage, /rank-assassin). Host-only for the identical
    # reason - it drives the HOST client against the live engine.
    "test_rm115_tail_seams_reach_the_client.py",
    # -- RM-112 (2026-07-23): runtime host-data reaches. These COLLECT clean
    # but FAIL at run time inside the engine-only, current-patch package,
    # because they load a HISTORICAL patch snapshot (16.10.1 / 16.11.1 /
    # 16.13.1 - the mirror ships only 16.14.1; a full prior snapshot is ~11 MB
    # and carries the license-excluded mayhem_augment_stats.json, so shipping
    # it is out) or reach the host core.* / host-meta layer at RUN time. A
    # cross-patch regression anchor is a host-CI seam, not portable engine math
    # at the shipped patch. Named per-file, not by predicate, so the > 300
    # scope guard stays honest.
    # historical 16.10.1 snapshot loads:
    "test_abilities_extract_descriptions.py",
    "test_arena_augment_e2e_p1l26.py",
    "test_beam.py",
    "test_beam_ranker_p1l18.py",
    "test_dps.py",
    "test_effects_expansion.py",
    "test_enemy_item_modeling_p1l1.py",
    "test_gold_efficiency_p1l13.py",
    "test_rank.py",
    "test_cc_conditional_wave14.py",
    "test_cc_conditional_wave15.py",
    "test_cc_conditional_wave16.py",
    "test_cc_conditional_wave17.py",
    "test_cc_conditional_wave19.py",
    "test_cc_conditional_wave20.py",
    "test_cc_conditional_wave21.py",
    "test_cc_conditional_wave22.py",
    "test_cc_conditional_wave23.py",
    # historical 16.11.1 snapshot loads:
    "test_mana_sim_ammo.py",
    "test_passive_damage_bilinear_item248.py",
    "test_passive_damage_caster_resist_item513.py",
    "test_passive_damage_conditional_gate_item255.py",
    "test_passive_damage_exotic_item247.py",
    "test_passive_damage_overrides_2026_05_31.py",
    "test_passive_damage_per_stack_item249.py",
    # historical 16.13.1 snapshot loads:
    "test_guinsoo_seething_strike_r66.py",
    "test_item_active_magic_burst_r69.py",
    "test_item_dsv9_r75.py",
    "test_item_hydra_active_burst_r113.py",
    "test_item_magic_burst_zekes_r70.py",
    "test_item_missing_hp_ad_r111.py",
    "test_item_physical_burst_r74.py",
    "test_item_reflect_thornmail_r68.py",
    "test_item_takedown_eruption_r70.py",
    "test_passive_damage_all_out_bonus_r50.py",
    "test_terminus_juxtaposition_r67.py",
    # host core.* / host-meta reads at run time:
    "test_jhin_whisper_as_lock.py",
    "test_r144_mirror_slice_a.py",
    "test_engine_math_correctness_pipeline_c.py",
    "test_cast_rate_canonical_keys.py",
    # A-39 (2026-07-25, ENGINE 1.247.0): the boot-utility v2 CC-input test
    # asserts the seam end-to-end, so it imports the HOST caller
    # ``core.build_order._select_boots`` / ``_select_boots_utility`` at module
    # level. The engine-side half (``boot_utility.comp_cc_signal``) is portable;
    # the boots CHOICE lives host-side, so this module cannot collect in an
    # engine-only package.
    "test_boot_utility_cc_v2_a39.py",
    # -- RM-221 (2026-08-16): a HOST-TREE POPULATION scan. Its axis-read guard
    # walks ``_REPO_ROOT.rglob("*.py")`` and asserts at least 15 non-test
    # modules mention antitank - 16 host consumers plus the module itself. An
    # engine-only package has no host consumers, so the floor can never be met
    # (measured in the clean copy: 0 candidates, not 15). Same class as
    # ``test_engine_math_correctness_pipeline_c.py`` above. Named rather than
    # predicated on purpose: five OTHER mirrored modules walk the tree the same
    # way and pass, because they assert on what they FIND rather than on how
    # much of the host tree exists, and no honest static rule separates the two.
    "test_antitank_axis_score_invariance_r196.py",
})

# Patch-shaped snapshot directory names, e.g. ``16.14.1``. Engine versions are
# single-leading-digit (1.x.y) and can never collide with this shape.
_PATCH_LITERAL = re.compile(r"^\d{2}\.\d+\.\d+$")

# Column-0 OR indented ``from core... import`` / ``import core...``.
#
# RM-221: this deliberately does NOT anchor at column 0. The earlier rule did,
# on the reasoning that only an import-time failure aborts collection and a
# DEFERRED import merely fails one test. That is true and it is the wrong bar:
# the reviewer's measured result is what the README promises, and five deferred
# ``import core.daemon_slayer_client`` calls inside test bodies produced five
# ``ModuleNotFoundError: No module named 'core'`` failures in the shipped
# package. A guard whose domain is narrower than its name is how they shipped.
_CORE_IMPORT_ANY_INDENT = re.compile(
    r"^[ \t]*(?:from|import)\s+core\b", re.MULTILINE
)


def _module_str_constants(tree: ast.Module) -> dict[str, str]:
    """{name: value} for module-level ``NAME = "literal"`` bindings."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _literal_text(node: ast.AST | None, consts: dict[str, str]) -> str | None:
    """Resolve a node to its string value, following module-level constants."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def _flatten_path_join(node: ast.AST, consts: dict[str, str],
                       acc: list[str | None]) -> None:
    """Collect the operands of a ``a / b / c`` pathlib join chain."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        _flatten_path_join(node.left, consts, acc)
        _flatten_path_join(node.right, consts, acc)
    else:
        acc.append(_literal_text(node, consts))


def _reads_unshipped_snapshot(source: str) -> bool:
    """True when the module resolves a data snapshot the package does not ship.

    The mirror carries exactly ONE per-patch snapshot (``_PATCH``). A test
    pinned to a HISTORICAL patch therefore cannot pass inside the package -
    measured 2026-08-16, this was 55 of the clean copy's 63 red results
    (``SnapshotNotFound: .../data/daemon_slayer/16.14.1`` x50 and
    ``FileNotFoundError: .../16.14.1/items_meraki.json`` x5).

    Two shapes, and only two, because a blunter rule is provably wrong here:
    ten mirrored modules name a non-shipped patch in code and EIGHT of them
    pass, because they build the snapshot themselves (``data_root=tmp``, a
    ``DataSnapshot(...)`` constructor with inline dicts) or carry the literal as
    an inert table entry. Keyed on the READ, not on the mention:

    * a pathlib join naming both ``daemon_slayer`` and a non-shipped patch, and
    * a ``.load(patch=...)`` call that does NOT re-root with ``data_root=``.

    Measured against the live generate set: exactly the two offending modules,
    zero false positives.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    consts = _module_str_constants(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts: list[str | None] = []
            _flatten_path_join(node, consts, parts)
            texts = [p for p in parts if p]
            if "daemon_slayer" in texts and any(
                _PATCH_LITERAL.match(t) and t != _PATCH for t in texts
            ):
                return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "load":
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            if "data_root" in keywords:
                continue
            value = _literal_text(keywords.get("patch"), consts)
            if value and _PATCH_LITERAL.match(value) and value != _PATCH:
                return True
    return False


def _is_host_dependent_test(name: str, source: str) -> bool:
    """Should this ``tests/`` module be kept OUT of the shipped package?

    Two RULES keyed on what the module imports or reads, plus the by-name set
    for the cases no honest rule covers. The rules are what stop this from
    recurring: a newly added test that reaches for the host application or for
    a snapshot the package does not ship is dropped the day it lands, instead
    of turning up as a failure in the next reviewer's first command.
    """
    if name in _HOST_DEPENDENT_TESTS:
        return True
    if _CORE_IMPORT_ANY_INDENT.search(source):
        return True
    return _reads_unshipped_snapshot(source)

# PATCH-INDEPENDENT engine data tables, which live at the ``data/daemon_slayer/``
# ROOT rather than inside the per-patch snapshot directory. They must ship, or
# the package's own test suite cannot pass.
#
# The mirror originally copied ``current.txt`` plus ``<patch>/**`` only, which
# silently dropped both files below. ``ult_rates.py:60-63`` joins them directly
# onto the data root, and four production call sites read through it
# (``ability_dps.py`` spell rates + ult item procs, ``dps.py`` Malignance,
# ``ability_hps.py`` HPS). The lookup is fail-soft, so the engine still LOADED -
# which is exactly why the omission survived: nothing crashed, it just answered
# with ``global_fallback`` everywhere. MEASURED consequence in the shipped
# package: 8802 passed / 108 failed / 16 skipped / 172 errors, while the package
# README advertised a clean offline run.
#
# The set is EMPIRICAL, not a guess: every ``data/daemon_slayer/*.json`` at the
# root was checked against the engine source, and only these two are read.
# ``sr_draft_presets.json``, ``vision_atlas_manifest.json``,
# ``vision_region_atlas.json`` and ``user_builds.json`` are RC-host files the
# engine never opens, so they are deliberately NOT shipped.
# ``tests/test_ds_share_data_snapshot_scope.py`` re-derives the engine's actual
# root-level reads from source and fails if a new one is not declared here.
_ROOT_DATA_FILES: tuple[str, ...] = (
    "spell_cast_rates.json",
    "ult_cast_rates.json",
)

# HOST ASSETS the mirrored TOOLING reads by package-root-relative path. Declared
# as repo-relative relpaths and mirrored at the IDENTICAL relpath, because that
# is how the reading code resolves them - rewriting the layout would break the
# very resolution this exists to satisfy.
#
# Same failure shape as ``_ROOT_DATA_FILES`` above, one layer out.
# ``tools/daemon_slayer_extract.py`` IS mirrored, and it executes
# ``_LOLMATH_TO_DDRAGON_ALIAS = _load_champion_aliases()`` at MODULE level
# (``daemon_slayer_extract.py:892``), which reads ``_CANONICAL_ALIAS_PATH`` =
# ``<root>/web/data/champion_aliases.json``. No ``web/`` tree shipped, so the
# read raised at import: the extractor was not merely untested in the package
# but UNIMPORTABLE, while ``README.md`` and ``MANIFEST.md`` both advertise
# ``src/tools/`` as the offline data extractors. Two tests in
# ``test_artifact_patch_marker_guard.py`` import that module to exercise
# ``stamp_patch`` and failed for exactly this reason.
#
# The file is 81 bytes of lolmath-name -> DDragon-id aliases, RC-authored, with
# no third-party licensing question. Making ``_load_champion_aliases`` fail-soft
# was the alternative and was rejected: it would silently change extractor
# behaviour to hide a packaging gap. ``tests/test_ds_share_mirror_self_contained``
# re-derives this class from the mirrored source, so a new host-asset reach
# fails there until it is declared here.
_HOST_ASSET_FILES: tuple[str, ...] = (
    "web/data/champion_aliases.json",
)

# Per-patch snapshot files EXCLUDED from the public package.
#
# ``mayhem_augment_stats.json`` is a Overlay App E dataset - its own ``endpoint``
# field is ``https://data.v2.iesdev.com/api/v1/query_objects/prod/lol/
# aram_mayhem_augments`` - carrying ``win_rate`` / ``num_games`` / ``pick_rate``
# / ``tier`` for 199 ARAM Mayhem augments. Three reasons it is not
# redistributed, and the first alone is sufficient:
#
#   1. NO LICENSE GRANT. It is a third party's aggregate play data, fetched from
#      an unauthenticated public endpoint. Shipping it in a package handed to an
#      external reviewer redistributes it under terms nobody granted.
#   2. THE ENGINE NEVER READS IT. Verified by grep: zero references anywhere
#      under ``agents/daemon_slayer/``, tests included. The only consumers are
#      ``core/augment_external_source.py`` (host-only, never mirrored) and
#      ``tools/ds_feed_index.py``, which DOES now ship - but only NAMES the file
#      in its ``KNOWN_STAMP_LAG`` provenance table and reaches it through a
#      ``glob`` of the snapshot dir, so a mirror without the file simply has one
#      fewer feed row. Excluding it costs the package no capability at all.
#   3. IT FALSIFIED THE PACKAGE'S OWN DOCS. ``Share/README.md`` states that DS
#      does not scrape win-rate aggregators and that the shipped mode sidecars
#      carry pick-rate-class data, which Riot developer policy permits where win
#      rate does not. Both statements were false while this file shipped.
#
# It is NOT deleted from ``data/daemon_slayer/`` - it is a live RC runtime feed
# on the host. This excludes it from the public mirror only.
_EXCLUDED_SNAPSHOT_FILES: frozenset[str] = frozenset({
    "mayhem_augment_stats.json",
})

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
against a target's defensive profile, and ranks item builds for seven archetypes
(carry / tank / bruiser / mage / assassin / enchanter / on-hit). It reads a versioned
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


def _is_transient(path: Path) -> bool:
    """Transient, gitignored run-artifacts that must never enter the mirror:
    bytecode caches (__pycache__ / *.pyc) and the pytest cache dir
    (.pytest_cache - rglob otherwise leaks it from agents/daemon_slayer/tests/
    into the deterministic generate set; slice-3 of the D1 de-dup)."""
    return (
        "__pycache__" in path.parts
        or ".pytest_cache" in path.parts
        or path.suffix == ".pyc"
    )


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

    # Mirror sentinel (see _MIRROR_MARKER_REL).
    out[_MIRROR_MARKER_REL] = _MIRROR_MARKER_BODY.encode("utf-8")

    # Engine package: copy every file; scrub .py text; clean-stub __init__.py.
    eng = _REPO / "agents" / "daemon_slayer"
    for p in sorted(eng.rglob("*")):
        if p.is_dir() or _is_transient(p):
            continue
        rel = f"agents/daemon_slayer/{p.relative_to(eng).as_posix()}"
        # The live engine CHANGELOG.md is the repo-internal release history
        # relocated out of __init__.py (item 241). The Share package carries its
        # own authored Share/CHANGELOG.md and a stubbed __init__, so the engine
        # changelog is intentionally not mirrored. CC_CONDITIONAL_NOTES.md WAS
        # excluded on the same "not read at runtime" reasoning, but RM-112
        # (2026-07-23) ships it: six cc_conditional wave tests
        # (test_cc_conditional_wave9/10/11/12/13/18) assert it exists + is
        # ASCII-clean as a maintained engine-provenance artifact, so the package
        # cannot pass its own suite without it. It carries 0 scrub-target phrases
        # (its wave / item provenance is the same class already shipped in the
        # mirrored .py comments), so it mirrors verbatim like any other doc.
        # cc_output_registry_notes.json (item 294) stays excluded: provenance source
        # quotes for the cc_output.py CC-kind registry, not read at runtime (the
        # registry is baked into cc_output.py), so it too is not mirrored.
        # mobility_registry_notes.json (item 297) is the mobility.py analog.
        # sustain_registry_notes.json (item 298) is the sustain.py analog.
        # scaling_registry_notes.json (item 299) is the scaling.py analog.
        # waveclear_registry_notes.json (item 300) is the waveclear.py analog.
        # threatrange_registry_notes.json (item 301) is the threatrange.py analog.
        # zonecontrol_registry_notes.json (item 302) is the zonecontrol.py analog.
        # objdamage_registry_notes.json (item 303) is the objdamage.py analog.
        # allyamp_registry_notes.json (item 304) is the allyamp.py analog.
        # antitank_registry_notes.json (item 308) is the antitank.py analog.
        # extendedduel_registry_notes.json (item 309) is the extendedduel.py analog.
        if p.name in (
            "CHANGELOG.md",
            "cc_output_registry_notes.json",
            "mobility_registry_notes.json",
            "sustain_registry_notes.json",
            "scaling_registry_notes.json",
            "waveclear_registry_notes.json",
            "threatrange_registry_notes.json",
            "zonecontrol_registry_notes.json",
            "objdamage_registry_notes.json",
            "allyamp_registry_notes.json",
            "antitank_registry_notes.json",
            "extendedduel_registry_notes.json",
        ) and p.parent == eng:
            continue
        if p.name == "__init__.py" and p.parent == eng:
            out[rel] = _CLEAN_INIT.format(version=version).encode("utf-8")
        elif p.suffix == ".py":
            text = p.read_text(encoding="utf-8")
            if p.parent == eng / "tests" and _is_host_dependent_test(p.name, text):
                continue
            out[rel] = _scrub(text).encode("utf-8")
        else:
            out[rel] = p.read_bytes()

    # DS tooling.
    tools = _REPO / "tools"
    for name in _DS_TOOLS:
        src = tools / name
        if src.exists():
            out[f"tools/{name}"] = _scrub(src.read_text(encoding="utf-8")).encode("utf-8")

    # Host assets the mirrored tooling resolves off the package root. Copied
    # verbatim, at the SAME relpath (see _HOST_ASSET_FILES).
    for rel in _HOST_ASSET_FILES:
        src = _REPO / rel
        if src.exists():
            out[rel] = src.read_bytes()

    # Reference-data snapshot (verbatim - it is data).
    data = _REPO / "data" / "daemon_slayer"
    cur = data / "current.txt"
    if cur.exists():
        out["data/daemon_slayer/current.txt"] = cur.read_bytes()
    for name in _ROOT_DATA_FILES:
        p = data / name
        if p.exists():
            out[f"data/daemon_slayer/{name}"] = p.read_bytes()
    snap = data / _PATCH
    for p in sorted(snap.rglob("*")):
        if p.is_dir():
            continue
        if p.name in _EXCLUDED_SNAPSHOT_FILES:
            continue
        out[f"data/daemon_slayer/{_PATCH}/{p.relative_to(snap).as_posix()}"] = p.read_bytes()

    return out


def _write(expected: dict[str, bytes]) -> int:
    """Write expected content under Share/src, removing stale files. Returns
    the number of files written.

    STAGE-THEN-SWAP, deliberately - do NOT "simplify" this back to
    ``rmtree(_SRC)`` followed by a write loop.

    INCIDENT 2026-07-19 (commit 6464532e): the previous shape deleted the live
    mirror FIRST and rebuilt it second, so Share/src spent the entire rebuild
    (~483 files) in a deleted state. This runs on a precommit hook, so an
    interruption or a race anywhere in that window left the tree empty and the
    commit captured it as intent - 501 deletions, 596,900 lines, ZERO additions,
    pushed to main.

    Here the new tree is built in a sibling scratch dir and swapped in with two
    renames, so the live mirror is only ever the old tree or the new one. The
    unsafe window shrinks from "hundreds of file writes" to "one rename".

    An EMPTY ``expected`` is refused outright: the mirror is never legitimately
    empty, so an empty build set means the builder failed, and honouring it
    would destroy the mirror for exactly the reason above.
    """
    if not expected:
        raise ValueError(
            "ds_share_sync: refusing to write an EMPTY Share/src - the mirror "
            "is never legitimately empty, so this means _build_expected() "
            "failed. The live mirror has been left untouched.")

    staging = _SRC.with_name(_SRC.name + ".tmp")
    previous = _SRC.with_name(_SRC.name + ".old")

    # Clear scratch left by a prior crashed run before reusing the names.
    for scratch in (staging, previous):
        if scratch.exists():
            shutil.rmtree(scratch)

    try:
        for rel, data in expected.items():
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
    except BaseException:
        # Nothing has touched the live mirror yet - drop the partial staging
        # tree and re-raise so the caller sees the real failure.
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # Swap. os.replace cannot overwrite a non-empty directory on Windows, so
    # the live tree is moved aside first and only removed once the new tree is
    # in place. If the second rename fails the old tree is put straight back.
    had_previous = _SRC.exists()
    if had_previous:
        os.replace(_SRC, previous)
    try:
        os.replace(staging, _SRC)
    except BaseException:
        if had_previous:
            os.replace(previous, _SRC)
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if had_previous:
        shutil.rmtree(previous, ignore_errors=True)
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
            if p.is_dir() or _is_transient(p) or p.suffix == ".log" or "logs" in p.parts:
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


def _manifest_body(version: str, n_files: int, eng_files: int, ts: str) -> str:
    """Render Share/MANIFEST.md.

    Split out of ``_stamp_manifest`` so the rendered text is testable without a
    filesystem write and so determinism is provable: every varying input is a
    parameter, therefore two syncs of an unchanged mirror can differ only in the
    timestamp line. Kept ASCII-only - the repo-wide no-em-dash/no-smart-quote
    rule applies to generated text exactly as it does to authored text, and this
    file ships to external readers.
    """
    return f"""# Daemon Slayer review package - MANIFEST

Daemon Slayer is an offline, deterministic engine that scores League of Legends
item builds for a champion at a given level and game mode against a target's
defensive profile. This folder is a self-contained snapshot of it, packaged for
external technical review: the engine source, the DS data tooling, the versioned
reference-data snapshot, and the authored documentation.

This file is the machine record of that snapshot - the exact engine revision,
data patch, and file counts everything else here was generated from. Where any
other file in the package disagrees with the numbers below, these are the
authoritative ones.

The reference-data snapshot is derived from public upstream sources - Riot Games
Data Dragon, CommunityDragon, and Meraki Analytics, plus a small set of fields
from the League community wiki and lolmath.net. Each keeps its own separate
terms: see `LICENSE.md` for the package terms and the credits, and
`docs/03_DATA_AND_SOURCES.md` for per-file provenance.

## Package stamp

- ENGINE_VERSION: {version}
- data patch: {_PATCH}
- files mirrored under src/: {n_files}
- engine .py modules: {eng_files}
- last synced: {ts}

`last synced` is the UTC time the mirror was last regenerated - a sync stamp,
not a release date; it moves whenever the sync runs, even if nothing changed.
`files mirrored under src/` counts every file in the mirror - engine, tooling,
and the reference-data snapshot. `engine .py modules` counts only the Python
files of the engine package itself, so the two are expected to differ.

## Generated vs authored

Paths are relative to this folder, the package root.

| Path | Origin |
|---|---|
| `src/**` | GENERATED - a mirror of the live engine, tooling, and data snapshot |
| `MANIFEST.md` | GENERATED - this file, rewritten in full on every sync |
| `README.md` | authored - version/patch tokens auto-restamped |
| `docs/*.md` | authored - version/patch tokens auto-restamped |
| `CHANGELOG.md` | authored |
| `LICENSE.md` | authored |

Everything marked GENERATED is rewritten wholesale by the upstream sync step
that builds this package - a maintenance tool in the engine's own repository,
which is not shipped here. A hand edit to a generated path is therefore
silently reverted by the next sync; the live engine or the generator is what
changes instead. The authored files are safe to edit, with the exception of
their engine-version and patch tokens, which the same step restamps to the live
values.

## Where to start

`README.md` is the entry point, and this file does not repeat it: it states what
the engine does, credits the upstream data sources, and explains how to read and
run the package. Read it first.

The five authored documents in `docs/` are then meant to be read in order, and
`README.md` says what each one covers: `docs/01_OVERVIEW.md`,
`docs/02_FUNCTION_REFERENCE.md`, `docs/03_DATA_AND_SOURCES.md`,
`docs/04_GAPS_AND_ROADMAP.md`, `docs/05_AUDIT_AND_REFACTOR.md`.

Terms of use and the upstream data credits are in `LICENSE.md`.

## Layout

```
(package root)
  README.md                 entry point + how to read / run the package
  LICENSE.md                terms of use + upstream data credits
  CHANGELOG.md              authored release notes + sync history
  MANIFEST.md               this file (machine record)
  docs/                     authored handoff docs (overview, function
                            reference, data + sources, gaps + roadmap, audit)
  src/
    agents/daemon_slayer/   the engine package (source + tests)
    tools/                  DS extractors, the server launcher, patch-bump scanners
    data/daemon_slayer/     the versioned reference-data snapshot ({_PATCH})
    web/data/               the champion-name alias map the extractors read
```

## Running the engine from this package

The full instructions, including the health check, are in `README.md`. The short
form, from this folder:

```
cd src
set PYTHONPATH=.                       # Windows;  export PYTHONPATH=. on POSIX
python -m pytest agents/daemon_slayer/tests -q
python tools/start_daemon_slayer.py    # serves the engine on http://127.0.0.1:8860
```

Inline source comments reference the engine's internal incremental-development
tags (version anchors, registry "wave" numbers, internal change identifiers).
These are historical development markers, not part of the engine's public
contract or any external dependency.
"""


def _stamp_manifest(version: str, n_files: int) -> None:
    """Write Share/MANIFEST.md (timestamped machine record of the sync)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    eng_files = sum(1 for r in _build_expected() if r.startswith("agents/daemon_slayer/") and r.endswith(".py"))
    body = _manifest_body(version, n_files, eng_files, ts)
    # write_bytes, not write_text: text mode emits CRLF on Windows, and
    # MANIFEST.md is a TRACKED .md now pinned to LF by `.gitattributes`
    # (RM-284) and asserted by tests/test_md_line_endings.py.
    (_SHARE / "MANIFEST.md").write_bytes(body.encode("utf-8"))


def _doc_anchor_rules() -> tuple[tuple[str, "re.Pattern[str]", str], ...]:
    """Mechanical version/patch anchor rules for the authored docs.

    Each rule is ``(label, pattern, live_value)``. The pattern matches ONLY the
    version/patch token (via fixed-width look-around), so ``pattern.sub(live,
    text)`` rewrites just the token and ``pattern.finditer(text)`` yields the
    tokens to verify. Deliberately scoped to unambiguous anchor forms. The
    semantic prose (shipped-vs-staged, test counts) is refreshed by hand per the
    /done ritual - only these literal anchors are auto-maintained.

    COVERED (each keyed on its own unambiguous prefix/suffix):
      * the ``ENGINE_VERSION = "X"`` literal
      * the ``data patch `X` `` / ``Active data patch: `X` `` / ``game patch
        `X` `` phrases and the ``"patch": "X"`` health example
      * the ``Share/README.md`` header (``**Engine version:** X`` /
        ``**Patch:** Y``)
      * the ``current.txt`` PROSE mention (``names the active patch (currently
        `X`)``)
      * the snapshot-dir segment of the manifest path citation
        (``data/daemon_slayer/X/manifest.json``)

    The last three were added by Phase-2 item (c): they track the live engine but
    had no rule, so ``--check`` read GREEN while the README header sat 72 engine
    minors stale (1.149.0 vs 1.221.0) and the prose + path citation sat at an old
    patch. A guard test pins coverage of every form
    (``tests/test_ds_share_anchor_rule_coverage.py``).

    STILL EXCLUDED by design - these are placeholders or frozen history, and a
    rule that grabbed one would corrupt it:
      * the ``data/daemon_slayer/<patch>/`` (and ``<prev>`` / ``<new>``) path
        placeholders - only the concrete ``/manifest.json`` citation is a real
        anchor
      * the CommunityDragon two-segment patch pin (``/16.11/`` vs ``/16.11.1/``)
      * the ``current.txt`` CONTENT description in the data-file table (a
        separate hand-maintained cell, not this prose anchor)
      * the copy-forward authoring patches of the hand-curated files
      * loopback addresses (``127.0.0.1`` is semver-shaped)
      * changelog history entries, incl. the README's "Changelog (recent)" list

    That last exclusion is correct but leaves a hole this tool cannot see: it
    means nothing here fails when a shipped ENGINE_VERSION never gets a release
    entry at all (measured twice - ORCHESTRATION_PLAN row R139, then again at
    1.238.0 with the newest entry still at 1.236.0). Freshness of the release
    history itself is guarded from the test suite instead, by
    ``tests/test_ds_share_changelog_freshness.py``.
    """
    version = _engine_version()
    patch = _PATCH
    return (
        ("engine version", re.compile(rf'(?<=ENGINE_VERSION = ")(?:{_SEMVER})(?=")'), version),
        ("data patch", re.compile(rf'(?<=data patch `)(?:{_SEMVER})(?=`)'), patch),
        ("active data patch", re.compile(rf'(?<=Active data patch: `)(?:{_SEMVER})(?=`)'), patch),
        ("game patch", re.compile(rf'(?<=game patch `)(?:{_SEMVER})(?=`)'), patch),
        ("health-example patch", re.compile(rf'(?<="patch": ")(?:{_SEMVER})(?=")'), patch),
        # Phase-2 item (c): the three previously-uncovered anchor forms.
        ("readme header version",
         re.compile(rf'(?<=\*\*Engine version:\*\* )(?:{_SEMVER})(?![\d.])'), version),
        ("readme header patch",
         re.compile(rf'(?<=\*\*Patch:\*\* )(?:{_SEMVER})(?![\d.])'), patch),
        ("current.txt prose patch",
         re.compile(rf'(?<=names the active patch \(currently\s`)(?:{_SEMVER})(?=`)'), patch),
        ("manifest path patch",
         re.compile(rf'(?<=data/daemon_slayer/)(?:{_SEMVER})(?=/manifest\.json)'), patch),
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


def _ingest_anchor_rules() -> tuple[tuple[str, "re.Pattern[str]", str], ...]:
    """Version/patch token rules for the lolmath_ingest authored files.

    Engine semvers have a single leading digit (1.x.y); data patches have two
    or more (16.x.y). The shapes are disjoint, so each rule rewrites exactly
    its own token kind anywhere in the file.
    """
    return (
        ("ingest engine version",
         re.compile(r"\b\d\.\d+\.\d+\b"), _engine_version()),
        ("ingest data patch",
         re.compile(r"\b\d{2,}\.\d+\.\d+\b"), _PATCH),
    )


def _rewrite_ingest_anchors() -> list[str]:
    """Write mode: restamp the ingest authored files to live values. Returns
    the relpaths changed."""
    rules = _ingest_anchor_rules()
    changed: list[str] = []
    for rel in _INGEST_DOC_FILES:
        p = _INGEST / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        new = text
        for _label, pat, live in rules:
            new = pat.sub(live, new)
        if new != text:
            # newline="" keeps the in-memory \n as LF on disk (the default
            # translates to CRLF on Windows, tripping the *.py eol=lf guard).
            p.write_text(new, encoding="utf-8", newline="")
            changed.append(rel)
    return changed


def _check_ingest_anchors() -> int:
    """--check: count drifted version/patch tokens in the ingest authored
    files, each printed as ``file:line``. Returns the drift count."""
    rules = _ingest_anchor_rules()
    drift = 0
    for rel in _INGEST_DOC_FILES:
        p = _INGEST / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for label, pat, live in rules:
            for m in pat.finditer(text):
                if m.group(0) != live:
                    line = text.count("\n", 0, m.start()) + 1
                    drift += 1
                    print(f"  INGEST ANCHOR DRIFT ({label}): "
                          f"Share/lolmath_ingest/{rel}:{line} has '{m.group(0)}', "
                          f"live is '{live}'")
    return drift


def _build_expected_bundle() -> bytes:
    """Replicate build_bundle.py's output for the live engine version + the
    Share/src data snapshot at ``_PATCH``. Deterministic - the basis for both
    the rebuild and the --check byte-compare."""
    snap = _SRC / "data" / "daemon_slayer" / _PATCH
    sources: dict[str, object] = {}
    for p in sorted(snap.iterdir() if snap.is_dir() else ()):
        if p.suffix == ".json":
            with p.open(encoding="utf-8") as fh:
                sources[p.stem] = json.load(fh)
    bundle = {
        "engine_version": _engine_version(),
        "patch": _PATCH,
        "generated_note": _INGEST_GENERATED_NOTE,
        "sources": sources,
    }
    text = json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True)
    return text.encode("utf-8")


def _rebuild_ingest_bundle() -> None:
    """Write mode: rebuild dist/daemon_slayer_bundle.json atomically."""
    target = _INGEST / _INGEST_BUNDLE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(_build_expected_bundle())
    tmp.replace(target)


def _check_ingest_bundle() -> int:
    """--check: byte-compare the on-disk dist bundle against a rebuild from
    the live Share/src snapshot. Returns drift count (0 or 1).

    The bundle is a gitignored build artifact (.gitignore ``dist/``), so a
    clean checkout (CI) has no file - that is a SKIP, not drift; write mode
    rebuilds it. A present-but-stale bundle is drift."""
    target = _INGEST / _INGEST_BUNDLE_REL
    if not target.exists():
        return 0
    if target.read_bytes() != _build_expected_bundle():
        print(f"  INGEST BUNDLE DRIFT: Share/lolmath_ingest/{_INGEST_BUNDLE_REL} "
              f"differs from a rebuild of the live snapshot (engine "
              f"{_engine_version()}, patch {_PATCH})")
        return 1
    return 0


# Staged-path prefixes that mean a commit actually changes the mirror, so the
# pre-commit hook must run the sync. A commit that touches none of these (a
# pure web / coach / dashboard / docs commit) cannot change Share/src, so the
# hook can skip the sync entirely - that skip is what removes the per-commit
# MANIFEST re-stamp churn AND the spurious external gist upload that fired on
# EVERY commit (D1). Manual `python tools/ds_share_sync.py` and CI `--check`
# stay the hard gates; this only gates the convenience hook.
_SYNC_TRIGGER_DIR_PREFIXES: tuple[str, ...] = (
    "agents/daemon_slayer/",
    "data/daemon_slayer/",
    "Share/",
)


def _should_sync(staged: list[str]) -> bool:
    """True if any staged path is a mirrored DS source (engine package, data
    snapshot, a curated DS tool, a mirrored host asset, or the Share package
    itself).

    The host assets are matched here as exact paths for the same reason the
    tools are: they live under repo trees (``web/``) that are overwhelmingly
    NOT mirrored, so a directory prefix would re-arm the hook for every
    dashboard commit and undo the D1 churn fix.
    """
    exact_paths = {f"tools/{name}" for name in _DS_TOOLS} | set(_HOST_ASSET_FILES)
    for s in staged:
        if s in exact_paths:
            return True
        if any(s.startswith(p) for p in _SYNC_TRIGGER_DIR_PREFIXES):
            return True
    return False


def _staged_files() -> list[str]:
    """Staged paths (POSIX-style) from `git diff --cached --name-only`. Returns
    [] on any git error; a sync is then skipped, which is safe because the
    manual run and CI `--check` remain the authoritative gates."""
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(_REPO), capture_output=True, text=True, check=True)
    except Exception:
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync the DS Share review package.")
    ap.add_argument("--check", action="store_true",
                    help="verify Share/src matches the live engine; exit 1 on drift")
    ap.add_argument("--precommit", action="store_true",
                    help="hook mode: sync only when staged files include mirrored "
                         "DS source (engine / data snapshot / curated tools / "
                         "Share); otherwise a no-op so non-DS commits do not "
                         "re-stamp MANIFEST or fire the external gist upload")
    args = ap.parse_args(argv)

    if args.precommit and not _should_sync(_staged_files()):
        print("ds_share_sync: no mirrored DS source staged - "
              "skipping Share sync (no MANIFEST churn).")
        return 0

    expected = _build_expected()
    version = _engine_version()

    if args.check:
        drift = (_check(expected) + _check_doc_anchors()
                 + _check_ingest_anchors() + _check_ingest_bundle())
        if drift:
            print(f"ds_share_sync: {drift} path(s)/anchor(s) drifted - run "
                  "`python tools/ds_share_sync.py` to rebuild, then commit the "
                  "tracked Share/ files it changes. The dist bundle is a "
                  "gitignored build artifact, so it is rebuilt in place and "
                  "never committed.")
            return 1
        print(f"ds_share_sync: Share/src + doc anchors + lolmath_ingest in "
              f"sync (engine {version}, {len(expected)} files).")
        return 0

    n = _write(expected)
    _stamp_manifest(version, n)
    docs_changed = _rewrite_doc_anchors()
    ingest_changed = _rewrite_ingest_anchors()
    _rebuild_ingest_bundle()
    doc_note = (f" + refreshed {len(docs_changed)} doc anchor file(s)"
                if docs_changed else " + doc anchors already fresh")
    ing_note = (f" + restamped {len(ingest_changed)} ingest file(s)"
                if ingest_changed else " + ingest anchors already fresh")
    print(f"ds_share_sync: wrote {n} files to Share/src (engine {version}, "
          f"patch {_PATCH}) + stamped MANIFEST{doc_note}{ing_note} + rebuilt "
          f"ingest bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
