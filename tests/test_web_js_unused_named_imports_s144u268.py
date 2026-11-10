"""
tests/test_web_js_unused_named_imports_s144u268.py
S144-U-268 (s144 uiux): every name a web/js module imports by name is used
by that module.

THE DEFECT. The panel retirements of S144-U-254..267 removed callers but
left their import names behind, and older ones had piled up before them.
MEASURED at lane/uiux 414d25b93 (a whole-tree scan of web/js/**/*.js, the
same check as below): 57 named imports in 7 modules were referenced
nowhere else in their own module outside comments (8 of them appeared
only in comments, 5 in two stale main.js "X imported from ..." lines).
main.js imported
11 names from panels/item_build.js and used 2 (IB, renderItemBuild);
panels/champ_select.js imported 6 `_ib*` names from item_build.js and used
none; main.js imported renderCoachDecisions and renderRecentCoachCalls and
called neither; the rest were helpers.js / items_index.js /
idempotent_render.js / map_state.js / dev.js / state.js names in main.js,
champ_select.js, coach_decisions.js, dev.js, item_build.js, map_state.js
and right_now.js.
A dead import name reads as a live dependency: it is what made
item_build.js look wired into champ select when no champ-select byte
calls it.

THE FIX. The 57 names go. Three import statements emptied out and are
dropped: champ_select.js -> item_build.js (main.js still loads
item_build.js), and coach_decisions.js -> web/js/lib/state.js and dev.js ->
web/js/lib/state.js (many modules load state.js). main.js -> panels/coach_decisions.js becomes a bare
side-effect import, because that module runs its /api/decisions poll at
load (setInterval at module scope) and dropping the statement would stop
loading it. Whether that poll still has a visible consumer is a separate
question, not decided here.

Also: map_state.js no longer re-assigns `state.spellCds = {}` at module
load; web/js/lib/state.js already creates it (a reset at load could only wipe a
cooldown written before map_state.js evaluated), and main.js's stale
"spellCds is added to state at runtime below" comment goes.

THE CHECK (a ratchet, not a proof). For every `import { ... } from '...'`
statement in web/js/**/*.js, each local binding (the `as` name when
aliased) must appear as a whole identifier somewhere else in the module,
with comments blanked by the web_ascii_sweep tokenizer. String text is NOT
blanked, so a name used only inside a string counts as used: the limits
can only produce a false green, never a false red. Default imports and
`import * as` namespaces are not checked.
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.web_ascii_sweep import COMMENT, scan

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

_NAMED_IMPORT = re.compile(
    r"^import\s*\{([^}]*)\}\s*from\s*(['\"])([^'\"]+)\2\s*;?", re.M
)


def _blank_comments(text: str) -> str:
    out = []
    for span in scan(text, "js"):
        chunk = text[span.start:span.end]
        if span.kind == COMMENT:
            chunk = re.sub(r"[^\n]", " ", chunk)
        out.append(chunk)
    return "".join(out)


def _unused_named_imports(text: str) -> list[tuple[str, str]]:
    """(specifier, local name) for every named import the module never uses."""
    live = _blank_comments(text)
    found: list[tuple[str, str]] = []
    for m in _NAMED_IMPORT.finditer(live):
        rest = live[:m.start()] + " " + live[m.end():]
        for part in m.group(1).split(","):
            spec = part.strip()
            if not spec:
                continue
            local = re.split(r"\s+as\s+", spec)[-1].strip()
            pat = r"(?<![\w$])" + re.escape(local) + r"(?![\w$])"
            if not re.search(pat, rest):
                found.append((m.group(3), local))
    return found


def _modules() -> list[Path]:
    return sorted(WEB_JS.rglob("*.js"))


def test_the_walk_sees_the_modules_and_their_imports():
    mods = _modules()
    rels = {p.relative_to(ROOT).as_posix() for p in mods}
    assert "web/js/main.js" in rels
    assert "web/js/panels/champ_select.js" in rels
    statements = sum(
        len(_NAMED_IMPORT.findall(_blank_comments(p.read_text(encoding="utf-8"))))
        for p in mods
    )
    # An empty enumeration must not pass: main.js alone carries dozens.
    assert statements >= 100, statements


def test_no_web_js_module_imports_a_name_it_never_uses():
    bad = []
    for p in _modules():
        rel = p.relative_to(ROOT).as_posix()
        for spec, name in _unused_named_imports(p.read_text(encoding="utf-8")):
            bad.append(f"{rel}: {name} from {spec}")
    assert bad == [], "\n".join(bad)


def test_main_js_still_loads_coach_decisions_for_its_poll():
    main = (WEB_JS / "main.js").read_text(encoding="utf-8")
    assert re.search(r"^import '\./panels/coach_decisions\.js';", main, re.M)
    cd = (WEB_JS / "panels" / "coach_decisions.js").read_text(encoding="utf-8")
    assert re.search(r"^setInterval\(pollCoachDecisions,", cd, re.M)


def test_main_js_still_loads_item_build():
    main = (WEB_JS / "main.js").read_text(encoding="utf-8")
    assert re.search(
        r"^import \{ IB, renderItemBuild \} from '\./panels/item_build\.js';",
        main, re.M,
    )


def test_spell_cds_is_created_once_by_lib_state_only():
    state_js = (WEB_JS / "lib" / "state.js").read_text(encoding="utf-8")
    assert re.search(r"^\s+spellCds: \{\},", state_js, re.M)
    for p in _modules():
        live = _blank_comments(p.read_text(encoding="utf-8"))
        assert not re.search(r"\bstate\.spellCds\s*=[^=]", live), p
    main = (WEB_JS / "main.js").read_text(encoding="utf-8")
    assert "spellCds is added to state at runtime" not in main


# -- positive controls: the check itself can go red ------------------------

def test_control_flags_an_unused_name():
    src = "import { a, b } from './x.js';\nexport function f() { return a(); }\n"
    assert _unused_named_imports(src) == [("./x.js", "b")]


def test_control_a_name_only_in_a_comment_is_unused():
    src = "import { a } from './x.js';\n// a() was here\n/* a */\n"
    assert _unused_named_imports(src) == [("./x.js", "a")]


def test_control_alias_checks_the_local_name():
    src = "import { a as b } from './x.js';\nb();\n"
    assert _unused_named_imports(src) == []
    src2 = "import { a as b } from './x.js';\na();\n"
    assert _unused_named_imports(src2) == [("./x.js", "b")]


def test_control_multiline_statement_and_prefix_names():
    src = (
        "import {\n  _ibPush, _ibPushItems,\n} from './ib.js';\n"
        "_ibPushItems();\n"
    )
    assert _unused_named_imports(src) == [("./ib.js", "_ibPush")]


def test_control_bare_side_effect_import_is_not_checked():
    assert _unused_named_imports("import './x.js';\n") == []
