# arch: every bare call in a web/js module resolves to a local declaration or an import | section=tests | frozen=no
"""Repo-wide guard: no web/js module calls another module's function bare.

WHY THIS EXISTS (RM-1211, filed by queue cycle 67, shipped by cycle 68).
The Phase 3.1 ESM split (b278337e8, 2026-05-08) cut main.js into panel and
lib modules. A function that used to share one script scope with its caller
now lives in a different module, and a module only sees what it declares or
imports. A bare call to anything else is a ReferenceError at RUN time - it
parses fine, so `node --check` and tests/test_web_js_esm_parse.py (a real
module parse) both stay green. Measured at local main fc123ec87, three sites:

- web/js/panels/champ_select.js `handleChampSelect` called `fetchAdaptation`,
  which is module-local to main.js (panels never import main.js). It threw
  once a champion was picked, and because `handleChampSelect` is the FIRST
  call in main.js `handleLcuEnvelope`, the rest of that function (auto-accept
  sync, the Home phase chip, the view re-derive, the lobby refresh, the
  champ-select view render) was skipped on every LCU envelope of a pick.
- web/js/main.js called `_spellKey` (the self-spell cell's cooldown key).
- web/js/main.js called `renderMinimapCanvases` (the deferred ZOI redraw when
  the tab returns to the foreground).
  Both are module-local to web/js/panels/map_state.js and were not exported.

s162 (2026-05-10) fixed four calls of this exact class in the same function
(see the comment in `handleChampSelect`) and missed `fetchAdaptation`, which
is the argument for a tree-wide guard over a one-site fix.

THE CHECK. Every function name declared by `function NAME` in ANY web/js
module is a candidate. In each module, a bare call `NAME(` (not `.NAME(`,
not a method-shorthand definition `NAME(...) {`) to a candidate the module
neither declares nor imports is a violation. Source is first blanked of
comments, strings, template-literal text and regex literals by a small
tokenizer, so a name inside prose or a URL is not a call.

KNOWN LIMITS (a ratchet, not a proof). Declarations are collected per MODULE,
not per scope, so a local of the same name anywhere in the module masks a
bare call elsewhere in it (a false negative). Only names some web/js module
declares with `function` are candidates, so a call to a name nothing declares
at all is not seen. Only CALLS are checked: a non-call reference to another
module's binding (`RN.action`, `_rnImmediate.textContent` in champ_select.js
renderChampSelectCoach, measured this cycle and left to RM-1212, whose live
caller is switched off) is not seen. None of these limits can produce a false
red.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUM = re.compile(r"[\w.]+")
_FUNC_DECL = re.compile(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)")
# A bare call: an identifier not preceded by a name character or a `.`.
_BARE_CALL = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")
# A `/` after one of these starts a regex literal, not a division.
_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^") | {""}
_REGEX_KW = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "throw", "case", "do", "else", "yield", "await",
}


def blank(src: str) -> str:
    """Return `src` with comment, string, template-text and regex bodies
    replaced by spaces (newlines kept, so offsets and line numbers hold).
    Template `${...}` expressions stay code, nested to any depth."""
    out = list(src)
    n = len(src)
    i = 0
    stack: list[int] = []  # open-brace depth inside each `${ ... }`
    prev_sig = ""
    prev_word = ""

    def wipe(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    def read_template(j: int) -> tuple[int, bool]:
        # j sits just after a backtick or after the `}` closing a `${`.
        while j < n:
            c = src[j]
            if c == "\\":
                j += 2
                continue
            if c == "`":
                return j + 1, False
            if c == "$" and j + 1 < n and src[j + 1] == "{":
                return j + 2, True
            j += 1
        return n, False

    def template_from(j: int) -> int:
        end, opened = read_template(j)
        wipe(j, end - (2 if opened else 1))
        if opened:
            stack.append(0)
        return end

    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            wipe(i, j)
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            wipe(i, j)
            i = j
            continue
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            wipe(i + 1, min(j, n))
            i = j + 1
            prev_sig, prev_word = c, ""
            continue
        if c == "`":
            i = template_from(i + 1)
            prev_sig, prev_word = "`", ""
            continue
        if c == "/" and (prev_sig in _REGEX_PREV or prev_word in _REGEX_KW):
            j = i + 1
            in_class = False
            while j < n and src[j] != "\n":
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
                j += 1
            wipe(i + 1, min(j, n))
            i = j + 1
            while i < n and src[i].isalnum():
                i += 1
            prev_sig, prev_word = "/", ""
            continue
        if c == "{":
            if stack:
                stack[-1] += 1
            i += 1
            prev_sig, prev_word = c, ""
            continue
        if c == "}":
            if stack:
                if stack[-1] == 0:
                    stack.pop()
                    i = template_from(i + 1)
                    prev_sig, prev_word = "`", ""
                    continue
                stack[-1] -= 1
            i += 1
            prev_sig, prev_word = c, ""
            continue
        m = _IDENT.match(src, i)
        if m:
            prev_sig, prev_word = "w", m.group(0)
            i = m.end()
            continue
        if c.isdigit():
            i = _NUM.match(src, i).end()
            prev_sig, prev_word = "0", ""
            continue
        prev_sig, prev_word = c, ""
        i += 1
    return "".join(out)


def declared_names(code: str) -> set[str]:
    """Every name a blanked module binds anywhere: function / class / var
    declarations, imports, parameters, destructuring, arrow params, catch."""
    names = set(_FUNC_DECL.findall(code))
    names |= set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", code))
    names |= set(re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)", code))
    for m in re.finditer(r"\bimport\s*\{([^}]*)\}", code):
        for raw_part in m.group(1).split(","):
            part = raw_part.strip()
            if part:
                names.add(part.split(" as ")[-1].strip())
    names |= set(re.findall(r"\bimport\s+([A-Za-z_$][\w$]*)\s*(?:,|from)", code))
    names |= set(re.findall(r"\bimport\s*\*\s*as\s+([A-Za-z_$][\w$]*)", code))
    for m in re.finditer(r"\(([^()]*)\)\s*(?:=>|\{)", code):
        names |= set(_IDENT.findall(m.group(1)))
    for m in re.finditer(r"\b(?:const|let|var)\s*[\{\[]([^}\]]*)[\}\]]", code):
        names |= set(_IDENT.findall(m.group(1)))
    names |= set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*=>", code))
    return names


def _is_method_definition(code: str, open_paren: int) -> bool:
    """True when `NAME(` at open_paren is `NAME(...) {` - a method shorthand
    in an object literal or class body, which defines rather than calls."""
    depth = 0
    j = open_paren
    while j < len(code):
        ch = code[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    k = j + 1
    while k < len(code) and code[k] in " \t\r\n":
        k += 1
    return k < len(code) and code[k] == "{"


def unimported_calls(modules: dict[str, str]) -> list[str]:
    """modules: name -> raw source. Returns "name:line: call (declared in X)"."""
    blanked = {name: blank(src) for name, src in modules.items()}
    owners: dict[str, list[str]] = {}
    for name, code in blanked.items():
        for fn in set(_FUNC_DECL.findall(code)):
            owners.setdefault(fn, []).append(name)
    found = []
    for name, code in sorted(blanked.items()):
        local = declared_names(code)
        for m in _BARE_CALL.finditer(code):
            fn = m.group(1)
            if fn not in owners or fn in local:
                continue
            if _is_method_definition(code, m.end() - 1):
                continue
            line = code.count("\n", 0, m.start()) + 1
            found.append(f"{name}:{line}: {fn} (declared in {sorted(owners[fn])})")
    return sorted(found, key=lambda s: (s.split(":")[0], int(s.split(":")[1]), s))


def _tree() -> dict[str, str]:
    return {
        p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(WEB_JS.rglob("*.js"))
    }


def test_no_web_js_module_calls_another_modules_function_unimported():
    modules = _tree()
    # 90 modules measured 2026-09-20 (tests/test_web_js_esm_parse.py); a floor,
    # not a pin, so a collapsed glob cannot pass on an empty corpus.
    assert len(modules) >= 80, f"only {len(modules)} web/js modules found"
    found = unimported_calls(modules)
    assert not found, (
        "bare calls to a function this module neither declares nor imports "
        "(a runtime ReferenceError; export it from its owner and import it, "
        "or move the call into the module that owns it):\n  "
        + "\n  ".join(found))


def test_the_tokenizer_still_sees_the_anchor_declarations():
    """Positive control: if the blanker ate code, the candidate set would
    shrink and the guard above would pass on nothing. The three functions of
    the RM-1211 sites must stay visible as declarations in their owners."""
    tree = _tree()
    main = set(_FUNC_DECL.findall(blank(tree["web/js/main.js"])))
    map_state = set(_FUNC_DECL.findall(blank(tree["web/js/panels/map_state.js"])))
    assert "fetchAdaptation" in main
    assert "handleLcuEnvelope" in main
    assert {"_spellKey", "renderMinimapCanvases"} <= map_state
    # Measured 238 at local main fc123ec87; a floor well below it.
    assert len(main) >= 150, f"only {len(main)} function declarations in main.js"


def test_the_check_flags_an_unimported_call_and_clears_an_imported_one():
    owner = "export function shared(a) { return a; }\nfunction privy() {}\n"
    caller_bad = "import { other } from './x.js';\nexport function go() { shared(1); privy(); }\n"
    caller_ok = (
        "import { shared } from './owner.js';\n"
        "const s = `shared(${'privy('})`; // privy( in prose\n"
        "const re = /privy\\(/;\n"
        "const obj = { privy(x) { return x; } };\n"
        "export function go() { shared(1); obj.privy(); return s + re; }\n"
    )
    bad = unimported_calls({"owner.js": owner, "caller.js": caller_bad})
    assert [b.split(" (")[0] for b in bad] == [
        "caller.js:2: privy", "caller.js:2: shared"]
    assert unimported_calls({"owner.js": owner, "caller.js": caller_ok}) == []


def test_cs_adaptation_node_tests_pass():
    """Runs web/js/lib/cs_adaptation.test.mjs. tests/test_web_panels_node_suite.py
    globs web/js/panels only, so a lib .test.mjs runs nowhere unless a pytest
    module names it. Asserts, never skips, when node is absent (same reason as
    that harness: a gate that excuses itself reports green over nothing)."""
    node = shutil.which("node")
    assert node, "node is not on PATH; the cs_adaptation contract would run nowhere"
    mjs = WEB_JS / "lib" / "cs_adaptation.test.mjs"
    assert mjs.is_file(), mjs
    out = subprocess.run(
        [node, "--test", str(mjs)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120, cwd=str(ROOT),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tally = {k: int(v) for k, v in re.findall(
        r"^\s*(?:#\s*|\S\s+)?(pass|fail)[ \t]+(\d+)[ \t]*$", out.stdout, re.M)}
    assert out.returncode == 0, out.stdout[-1500:] + out.stderr[-800:]
    assert tally.get("fail") == 0, tally
    assert tally.get("pass", 0) >= 3, tally


def test_blank_keeps_template_expressions_as_code():
    src = "const a = `x ${f(`y ${g(1)} z`)} w`; h(2);\n"
    code = blank(src)
    assert len(code) == len(src)
    for call in ("f(", "g(", "h("):
        assert call in code, call
    assert "x " not in code and " w" not in code
