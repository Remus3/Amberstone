"""
tests/test_web_element_id_resolution_rm339.py

RM-339 - every literal ``document.getElementById("x")`` in a JS module under
web/ must name an id that something actually creates.

WHY THIS NEEDS A GUARD AT ALL. getElementById on an absent id returns null.
It does not throw and it does not warn, so the panel that depends on it simply
never renders and the page stays superficially healthy. Every one of these
sites greps clean for the id name - the reference is right there in the source
- which is exactly why source review let 21 of them drift. The only way to see
the defect is to resolve the reference against the id supply, and the supply is
in a DIFFERENT LANGUAGE from the reference, so no single-language linter can
do it. That cross-language step is this file's whole reason to exist.

THREE POPULATIONS SUPPLY IDS, AND ALL THREE ARE LOAD-BEARING. Miss any one of
them and the guard invents false positives, which is how a guard gets reverted:

  1. ``id="..."`` in an HTML document under web/. 654 ids today.
  2. ``id="..."`` inside an HTML fragment built as a TEMPLATE STRING in a .js
     file. This is common here and is the easy one to miss. It is not
     hypothetical: #csv-sugg-capability-gap is read at
     web/js/panels/champ_select.js:2055 and is declared nowhere in any HTML
     document - its only declaration is the template string at
     web/js/panels/champ_select.js:984.
     test_an_id_defined_only_in_a_js_template_string_is_not_flagged pins it.
  3. Imperative creation: ``el.id = "..."`` and ``setAttribute("id", "...")``.
     Measured 2026-09-04: no id currently depends on population 3 ALONE (every
     imperatively-set id is also emitted as an attribute somewhere), so this
     population cannot be proven live from the tree. It is covered by a regex
     unit test instead, so it cannot rot into a broken pattern unnoticed.

WHAT THE SCANNER DELIBERATELY DOES NOT MATCH. Three near-misses would each
create a phantom definition and hide a real defect:
  - ``const id = "lane:" + lane`` (web/mc/mc.js:248) is a JS local variable.
  - ``data-ovx-id="w-mmrect"`` (web/index.html:2266 and web/css/overlay.css)
    is a widget key on a data- attribute, not an element id.
  - ``var``/``let`` forms of the first case.
The id-attribute pattern therefore refuses a preceding word char or hyphen and
refuses a preceding const/let/var. The RM-339 census as first measured counted
those two names among "ids emitted by JS" and reported 62; this scanner
reports 60. The UNRESOLVED SET IS IDENTICAL either way, because neither name is
ever passed to getElementById.

REFERENCE SCOPE IS THE JS MODULES, NOT THE HTML PAGES. A .js/.mjs module can be
loaded by any page, so an id it cannot resolve is unresolved against the union
of every document - a whole-tree question. An inline <script> inside a
self-contained page is a per-document question with a different answer, and
folding the two together would report a page-local miss as a tree-wide one.
That boundary is not a silent drop: web/legacy_index.html carries exactly one
such page-local dangling reference (#gl-bld, read at line 2323, declared
nowhere in that file - only the CSS class .gl-bld at line 344 exists), and
test_inline_page_script_residue_is_pinned holds it to exactly that one so the
quarantined page cannot quietly grow more.

THIS GUARD IS RED ON PURPOSE. The 20 ids it names are the live RM-339 residue
minus the one allowlisted design decision; the per-id RESTORE-vs-REMOVE fixes
land in their own slices. Do not silence it by weakening the scanner. If a
merge needs `pytest tests` green before those fixes land, move the named ids
into KNOWN_OPEN below - that keeps the guard live against NEW breakage and
against silent rot in both directions.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

MODULE_SUFFIXES = {".js", ".mjs"}
DOCUMENT_SUFFIXES = {".html"}

# A reference: getElementById with a single quoted literal argument. Computed
# arguments (getElementById(name), getElementById("p-" + k)) are unresolvable
# from source and are counted but never flagged.
_GEBI = re.compile(r"""getElementById\(\s*(["'])([A-Za-z0-9_:.\-]+)\1\s*\)""")
# A literal id= attribute, in HTML markup or inside a JS template string. The
# lookbehinds are the whole difference between a definition and a phantom -
# see "WHAT THE SCANNER DELIBERATELY DOES NOT MATCH" above.
_ID_ATTR = re.compile(
    r"""(?<![-\w])(?<!const )(?<!let )(?<!var )id\s*=\s*(["'])([^"'{}$<>\s]+)\1"""
)
# Imperative creation from JS.
_EL_ID = re.compile(r"""\.id\s*=\s*(["'`])([A-Za-z0-9_:.\-]+)\1""")
_SET_ATTR = re.compile(
    r"""setAttribute\(\s*(["'`])id\1\s*,\s*(["'`])([A-Za-z0-9_:.\-]+)\2"""
)
# Population 4: an id ASSEMBLED at runtime from an interpolated expression plus
# a literal suffix, e.g. `id="${sigKey}-input"`. _ID_ATTR deliberately refuses
# these (its value class excludes $ and {) because the id is not knowable from
# source - but refusing them entirely reports a WORKING panel as dangling. The
# measured case: web/js/panels/ds_combo.js:309 emits id="${sigKey}-input" where
# :296 sets sigKey = blockEl.id, and the block is #csv-sugg-ds-combo
# (web/index.html:2323), so the live element is #csv-sugg-ds-combo-input, read
# at web/js/panels/active_match.js:1489.
#
# We therefore harvest the literal SUFFIX and treat any referenced id ending in
# it as creatable. That is deliberately CONSERVATIVE - it can mask a genuine
# dangling id that happens to share a suffix - and the alternative is executing
# JS. It is scoped tightly by test_interpolated_suffixes_stay_rare below, which
# fails if this population ever grows beyond a handful, so the masking surface
# cannot widen unobserved.
_ID_ATTR_INTERP = re.compile(
    r"""(?<![-\w])id\s*=\s*(["'`])\$\{[^{}]*\}([A-Za-z0-9_:.\-]+)\1"""
)


# ------------------------------------------------------------------ allowlist
# EVERY ENTRY CARRIES A REASON, and the reason must cite the file:line that
# makes the absence deliberate. A bare id with no obligation attached is how an
# exemption outlives the decision behind it; test_allowlist_entries_are_live
# enforces both halves and deletes nothing on its own.
ALLOWLIST: dict[str, str] = {
    "lv-queue-sub": (
        "Optional write target BY DESIGN, not a dangling reference. "
        "web/js/main.js:201-207 documents _lvQueueChangeError as writing into "
        "the #lv-queue-sub line IF PRESENT and console.warn-ing regardless, so "
        "the guarded `if (sub)` write is the designed quiet path. Delete this "
        "entry the moment that guard goes away or the element is mounted."
    ),
    "lm-tl-pending": (
        "Optional write target BY DESIGN. Superseded by #lm-chart-pending in "
        "afbb4822d (s220 S4, 4 tabs to 3). web/index.html:2047-2049 states in "
        "place that _setTimeline still references lm-tl-pending by id and the "
        "lookup just no-ops when absent, so the guard at "
        "web/js/panels/last_match.js:1360 is intentional. Delete this entry if "
        "that guard goes away or the element is mounted."
    ),
    "set-force-scan-btn": (
        "Deliberate visual-only removal per ee2db2ffb, which states the "
        "/api/command force_vision route and its dev.js binder stay for a "
        "possible future re-surfacing. PINNED IN BOTH DIRECTIONS by "
        "tests/test_settings_force_scan_dom.py:42-43 (asserts the id is ABSENT "
        "from web/index.html) and :56 (asserts the binder is PRESENT in "
        "web/js/panels/dev.js), so a restore AND a removal both go red there. "
        "The guarded read is web/js/panels/dev.js:131."
    ),
    "set-force-scan-status": (
        "Same decision and the same both-directions pin as set-force-scan-btn: "
        "ee2db2ffb preserved the binder deliberately, and "
        "tests/test_settings_force_scan_dom.py:42-43,56 fails on either a "
        "restore or a removal. The guarded write is web/js/panels/dev.js:132. "
        "Delete both entries together if that decision is reversed."
    ),
}

# --------------------------------------------------------------- known open
# The RM-339 residue, as an EXPECTED-FAILURE list. Empty today, which is why
# the guard below is red: the 20 remaining ids are real defects awaiting their
# per-id RESTORE-vs-REMOVE slices, and a red guard is the signal that says so.
# If a merge needs the suite green before those land, move each id here WITH a
# reason. It must shrink to zero as RM-339 lands, and
# test_known_open_contains_no_id_that_has_since_been_fixed makes a fixed id
# fail loudly rather than sit here forever as a silent permanent exemption.
KNOWN_OPEN: dict[str, str] = {}

# Page-local dangling references inside a self-contained HTML page's own inline
# script - out of the main guard's scope (see REFERENCE SCOPE above), pinned so
# the set cannot grow unobserved.
INLINE_PAGE_RESIDUE: dict[str, str] = {
    "gl-bld": (
        "web/legacy_index.html:2323 reads #gl-bld from that page's own inline "
        "script; the page declares only the CSS class .gl-bld at line 344. "
        "legacy_index.html is the quarantined pre-ADR-008 snapshot and is not "
        "served (only /js/main.js loads), so this is recorded, not fixed here."
    ),
}


# ------------------------------------------------------------------- scanner
def _modules(web_root: Path) -> list[Path]:
    return sorted(
        p for p in web_root.rglob("*")
        if p.is_file() and p.suffix in MODULE_SUFFIXES
    )


def _documents(web_root: Path) -> list[Path]:
    return sorted(
        p for p in web_root.rglob("*")
        if p.is_file() and p.suffix in DOCUMENT_SUFFIXES
    )


def _rel(web_root: Path, path: Path) -> str:
    return path.relative_to(web_root.parent).as_posix()


def _site(web_root: Path, path: Path, text: str, offset: int) -> str:
    return f"{_rel(web_root, path)}:{text.count(chr(10), 0, offset) + 1}"


def _references(web_root: Path) -> dict[str, list[str]]:
    """{id: [file:line, ...]} for every literal getElementById in a JS module."""
    refs: dict[str, list[str]] = {}
    for path in _modules(web_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _GEBI.finditer(text):
            refs.setdefault(match.group(2), []).append(
                _site(web_root, path, text, match.start())
            )
    return refs


def _definitions(web_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """({id: site} declared in HTML markup, {id: site} created/emitted by JS)."""
    markup: dict[str, str] = {}
    js_made: dict[str, str] = {}
    for path in _documents(web_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _ID_ATTR.finditer(text):
            markup.setdefault(match.group(2), _site(web_root, path, text, match.start()))
    for path in _modules(web_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _ID_ATTR.finditer(text):
            js_made.setdefault(match.group(2), _site(web_root, path, text, match.start()))
        for match in _EL_ID.finditer(text):
            js_made.setdefault(match.group(2), _site(web_root, path, text, match.start()))
        for match in _SET_ATTR.finditer(text):
            js_made.setdefault(match.group(3), _site(web_root, path, text, match.start()))
    return markup, js_made


def _interpolated_suffixes(web_root: Path) -> dict[str, str]:
    """{literal suffix: site} for ids built as `id="${expr}<suffix>"` in JS."""
    found: dict[str, str] = {}
    for path in _modules(web_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _ID_ATTR_INTERP.finditer(text):
            found.setdefault(
                match.group(2), _site(web_root, path, text, match.start())
            )
    return found


def _unresolved(web_root: Path) -> dict[str, list[str]]:
    """{id: [reference site, ...]} for ids nothing in the tree ever creates."""
    refs = _references(web_root)
    markup, js_made = _definitions(web_root)
    suffixes = _interpolated_suffixes(web_root)

    def _creatable(name: str) -> bool:
        if name in markup or name in js_made:
            return True
        # Population 4: an id longer than a harvested suffix and ending in it
        # may be assembled at runtime. See _ID_ATTR_INTERP for why this is
        # deliberately conservative.
        return any(
            name.endswith(suffix) and len(name) > len(suffix)
            for suffix in suffixes
        )

    return {
        name: sites for name, sites in sorted(refs.items())
        if not _creatable(name)
    }


def _report(unresolved: dict[str, list[str]]) -> str:
    return "\n".join(
        f"  {name:<24} {', '.join(sites)}" for name, sites in sorted(unresolved.items())
    )


# ----------------------------------------------------------------- the guard
def test_every_getelementbyid_literal_resolves_to_a_real_id():
    unresolved = _unresolved(WEB)
    flagged = {
        name: sites for name, sites in unresolved.items()
        if name not in ALLOWLIST and name not in KNOWN_OPEN
    }
    assert not flagged, (
        f"{len(flagged)} id(s) are read by document.getElementById in a JS "
        "module under web/ but are declared in no HTML document, built by no "
        "JS template string, and set by no el.id / setAttribute call. "
        "getElementById returns null silently, so each of these is a panel "
        "that never renders and never complains. Fix each one at its source: "
        "restore the missing mount in markup, delete the dead reader, or - if "
        "the write is deliberately optional - add the id to ALLOWLIST above "
        "WITH a reason citing the file:line that makes it optional.\n"
        + _report(flagged)
    )


# ------------------------------------------- the exemptions cannot go stale
def test_allowlist_entries_are_live():
    """An exemption must stay attached to a live reference AND a real reason.

    Both halves matter. An entry whose call site is gone is dead weight that
    silently pre-approves the id if it ever comes back; an entry whose element
    now exists is an exemption for a problem that no longer exists; and a
    reason with no file:line in it is the failure mode where one word waives
    the only artifact the guard was built to catch.
    """
    refs = _references(WEB)
    unresolved = _unresolved(WEB)
    for name, reason in ALLOWLIST.items():
        assert name in refs, (
            f"ALLOWLIST carries {name!r} but no JS module reads it any more - "
            "delete the entry rather than leaving a standing pre-approval"
        )
        assert name in unresolved, (
            f"ALLOWLIST carries {name!r} but the id now resolves (declared at "
            "a real site) - the exemption is obsolete, delete it"
        )
        assert re.search(r"\.(?:js|mjs|html):\d+", reason), (
            f"ALLOWLIST reason for {name!r} cites no file:line. An exemption "
            "has to point at the evidence that makes the absence deliberate."
        )
        assert len(reason) > 80, f"ALLOWLIST reason for {name!r} is too thin to audit"


def test_known_open_contains_no_id_that_has_since_been_fixed():
    """KNOWN_OPEN is an expected-failure list, not a second allowlist.

    The instant a listed id starts resolving, its entry has to go - otherwise
    the list rots into a permanent exemption that keeps the guard green while
    quietly re-approving the id if it ever breaks again.
    """
    unresolved = _unresolved(WEB)
    fixed = sorted(name for name in KNOWN_OPEN if name not in unresolved)
    assert not fixed, (
        f"{len(fixed)} id(s) in KNOWN_OPEN now resolve. RM-339 has moved on; "
        "delete these entries so the list keeps shrinking toward zero: "
        + ", ".join(fixed)
    )
    for name, reason in KNOWN_OPEN.items():
        assert len(reason) > 40, f"KNOWN_OPEN entry {name!r} needs a reason, not a bare id"
    overlap = sorted(set(KNOWN_OPEN) & set(ALLOWLIST))
    assert not overlap, f"id(s) in both ALLOWLIST and KNOWN_OPEN: {overlap}"


# ------------------------------------------------- the three id populations
def test_html_markup_population_is_live():
    markup, _ = _definitions(WEB)
    assert len(markup) > 500, f"markup scan found only {len(markup)} ids - corpus collapsed"
    assert "view-menu" in markup and markup["view-menu"].startswith("web/index.html:")


def test_an_id_defined_only_in_a_js_template_string_is_not_flagged():
    """Population 2, proven on a real id rather than a fixture.

    #csv-sugg-capability-gap is read by getElementById and is declared in NO
    HTML document - its only declaration is an id= attribute inside a template
    string in the same JS module. Drop template-string scanning and this id
    becomes a false positive, which is the fastest way to get the guard
    reverted.
    """
    name = "csv-sugg-capability-gap"
    refs = _references(WEB)
    markup, js_made = _definitions(WEB)
    assert name in refs, f"{name} is no longer read - repoint this test at another such id"
    assert name not in markup, f"{name} is now in HTML markup - it no longer proves population 2"
    assert js_made[name].startswith("web/js/panels/champ_select.js:")
    assert name not in _unresolved(WEB), "template-string declaration was not credited"


def test_imperative_creation_patterns_are_matched():
    """Population 3. No id in the tree depends on it alone today, so the tree
    cannot prove it works - pin the patterns directly instead."""
    assert _EL_ID.findall('  node.id = "made-by-js";') == [('"', "made-by-js")]
    assert _EL_ID.findall("  node.id = `made-by-tpl`;") == [("`", "made-by-tpl")]
    assert _SET_ATTR.findall('el.setAttribute("id", "made-by-setattr");') == [
        ('"', '"', "made-by-setattr")
    ]


def test_scanner_refuses_the_three_known_phantom_shapes():
    """Each of these would register a phantom definition and mask a real
    dangling reference. All three exist verbatim in the tree."""
    assert _ID_ATTR.findall('const id = "lane:" + lane;') == []
    assert _ID_ATTR.findall('let id = "x";') == []
    assert _ID_ATTR.findall('var id = "x";') == []
    assert _ID_ATTR.findall('<div data-ovx-id="w-mmrect">') == []
    # ... while the real attribute shape still registers, in both languages.
    assert _ID_ATTR.findall('<div class="c" id="real-mount"></div>') == [('"', "real-mount")]
    assert _ID_ATTR.findall("html += `<span id='tpl-mount'></span>`;") == [("'", "tpl-mount")]


def test_computed_getelementbyid_arguments_are_not_treated_as_ids():
    """getElementById(name) cannot be resolved from source. It must not be
    read as a reference to the literal text 'name'."""
    assert _GEBI.findall("document.getElementById(name)") == []
    assert _GEBI.findall('document.getElementById("p-" + k)') == []
    assert _GEBI.findall('document.getElementById("real-id")') == [('"', "real-id")]


# ----------------------------------------------------- anti-vacuity, both ways
def _scratch_corpus(tmp_path: Path) -> Path:
    """A scratch copy of the real scanned corpus, so the two probes below run
    against the tree as it actually is rather than a toy fixture."""
    web = tmp_path / "web"
    for src in _modules(WEB) + _documents(WEB):
        dst = web / src.relative_to(WEB)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return web


def test_guard_catches_a_planted_unresolved_id(tmp_path):
    """A guard that cannot fail is not a guard. Plant one and watch it fire."""
    web = _scratch_corpus(tmp_path)
    before = set(_unresolved(web))
    (web / "js" / "rm339_probe.js").write_text(
        'export function probe() {\n'
        '  return document.getElementById("rm339-does-not-exist");\n'
        '}\n',
        encoding="utf-8",
    )
    after = _unresolved(web)
    assert "rm339-does-not-exist" in after, "planted dangling id was not detected"
    assert after["rm339-does-not-exist"] == ["web/js/rm339_probe.js:2"]
    assert set(after) - before == {"rm339-does-not-exist"}, "plant disturbed unrelated ids"


def test_guard_stays_silent_on_an_id_that_resolves(tmp_path):
    """The other direction. A guard that fires on everything is as useless as
    one that fires on nothing, so a NEW reader of an id that really exists must
    move the unresolved set not at all."""
    web = _scratch_corpus(tmp_path)
    before = _unresolved(web)
    markup, _ = _definitions(web)
    assert "view-menu" in markup, "anchor id vanished - repoint this test"
    (web / "js" / "rm339_probe_ok.js").write_text(
        'export function probe() {\n'
        '  return document.getElementById("view-menu");\n'
        '}\n',
        encoding="utf-8",
    )
    after = _unresolved(web)
    assert "view-menu" not in after, "an id declared in web/index.html was flagged"
    assert after == before, f"scanner reacted to a resolving reference: {set(after) ^ set(before)}"


# ------------------------------------------------------- corpus + scope pins
def test_guard_corpus_is_populated():
    """A scan that silently walked zero files would report a clean tree.

    Census measured 2026-09-04 at f2906ce15: 120 JS modules, 10 HTML
    documents, 348 literal getElementById sites, 256 distinct ids referenced,
    654 ids in markup, 60 created or emitted by JS.
    """
    modules = {_rel(WEB, p) for p in _modules(WEB)}
    documents = {_rel(WEB, p) for p in _documents(WEB)}
    assert len(modules) >= 110, f"only {len(modules)} JS modules scanned"
    assert len(documents) >= 8, f"only {len(documents)} HTML documents scanned"
    for must in (
        "web/js/main.js",
        "web/js/panels/dev.js",
        "web/js/panels/champ_select.js",
        "web/js/panels/active_match.js",
        "web/js/panels/last_match.js",
        "web/mc/mc.js",
        "web/index.html",
        "web/ops.html",
    ):
        assert must in modules or must in documents, f"guard corpus missing {must}"
    refs = _references(WEB)
    assert len(refs) >= 240, f"reference scan found only {len(refs)} distinct ids"
    assert sum(len(v) for v in refs.values()) >= 330, "reference site count collapsed"


def test_inline_page_script_residue_is_pinned():
    """The reference scope stops at JS modules (see the module docstring). The
    one page-local dangling reference that boundary excludes is recorded here,
    not dropped, and this test fails if a second one appears - or if the
    recorded one is fixed and the pin is left behind."""
    markup, js_made = _definitions(WEB)
    found: dict[str, list[str]] = {}
    for path in _documents(WEB):
        text = path.read_text(encoding="utf-8", errors="replace")
        own = {m.group(2) for m in _ID_ATTR.finditer(text)}
        for match in _GEBI.finditer(text):
            name = match.group(2)
            if name in own or name in markup or name in js_made:
                continue
            found.setdefault(name, []).append(_site(WEB, path, text, match.start()))
    assert set(found) == set(INLINE_PAGE_RESIDUE), (
        "inline-page-script residue changed. Every entry needs a reason in "
        "INLINE_PAGE_RESIDUE, and a fixed one must be removed from it.\n"
        + _report(found)
    )
def test_an_id_assembled_from_an_interpolated_suffix_is_not_flagged():
    """Population 4, pinned on the real in-repo case rather than a fixture.

    ``web/js/panels/ds_combo.js:296`` sets ``sigKey = blockEl.id`` and ``:309``
    emits ``id="${sigKey}-input"``. The block is ``#csv-sugg-ds-combo``
    (``web/index.html:2323``), so the live element is
    ``#csv-sugg-ds-combo-input``, which
    ``web/js/panels/active_match.js:1489`` reads. A scanner that sees only
    literal ``id=`` attributes reports that WORKING panel as dangling - this
    test is the standing proof that it does not.
    """
    web_root = WEB
    suffixes = _interpolated_suffixes(web_root)
    assert "-input" in suffixes, (
        "expected ds_combo.js to emit an interpolated id ending in '-input'; "
        "if that panel changed, re-derive this population rather than deleting "
        "the test - the masking behaviour it documents is still live"
    )
    unresolved = _unresolved(web_root)
    assert "csv-sugg-ds-combo-input" not in unresolved, (
        "csv-sugg-ds-combo-input is created at runtime by ds_combo.js:309 and "
        "must not be reported as dangling"
    )
    # And the reference really exists, so this is not vacuous.
    assert "csv-sugg-ds-combo-input" in _references(web_root)


def test_interpolated_suffixes_stay_rare():
    """The population-4 escape hatch masks by suffix, so it must stay small.

    Each harvested suffix silently resolves EVERY referenced id ending in it.
    That is an acceptable trade at this size and would not be at ten times it,
    so the surface is pinned rather than left to drift.
    """
    suffixes = _interpolated_suffixes(WEB)
    assert len(suffixes) <= 6, (
        f"interpolated-id suffixes have grown to {len(suffixes)} "
        f"({', '.join(sorted(suffixes))}). Each one masks every referenced id "
        "ending in it - re-check that the escape hatch is still narrow enough "
        "to be honest before raising this bound."
    )
