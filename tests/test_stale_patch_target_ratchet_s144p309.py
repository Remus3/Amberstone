"""S144-P-309 - a test that patches an attribute its repo module never mentions is held at zero.

``monkeypatch.setattr(mod, "name", v)`` and ``patch("pkg.mod.name")`` raise when ``name`` does not exist, so a stale
seam is loud. The two escape hatches are ``raising=False`` and ``create=True``: they exist so a TDD "red" run can
reset a pre-fix attribute name and a post-fix one side by side, and they outlive the fix. Measured 2026-11-06: three
such lines reset caches (``_champ_names_loaded``, ``_champ_names_by_id``, ``_NAME_TO_ID``) that the hardened modules
no longer own, so the fixture claimed to isolate state it could not reach and a reader hunting for the cache found
nothing. They are removed here and the escape hatch is not a place to park a dead name.

The detector is an AST walk over every tracked ``tests/`` / ``*/tests/`` ``.py``. It resolves a patch target only
when it is a repo module (a ``tests`` file's top-level ``import`` / ``from ... import`` alias, or the dotted string of
``patch``) and asks one question: does the word appear anywhere in that module's source? A stdlib or third-party target
(``signal``, ``ctypes``) cannot be resolved here and is skipped, so is a repo module reached through a ``sys.path``
insert; the baseline is empty.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files


def _is_test_file(rel: str) -> bool:
    return rel.startswith("tests/") or "/tests/" in rel


def _hatch(call: ast.Call, name: str) -> bool:
    """``raising=False`` or ``create=True``: the keyword that lets a patch name an attribute that is not there."""
    want = name == "create"
    return any(k.arg == name and isinstance(k.value, ast.Constant) and k.value.value is want
               for k in call.keywords)


def _module_path(dotted: str) -> Path | None:
    base = REPO_ROOT.joinpath(*dotted.split("."))
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        if cand.is_file():
            return cand
    return None


def _resolve(dotted: str) -> Path | None:
    """The repo module that owns ``dotted`` (a module, or a module plus trailing class / attribute parts)."""
    parts = dotted.split(".")
    while parts:
        found = _module_path(".".join(parts))
        if found is not None:
            return found
        parts = parts[:-1]
    return None


def _aliases(tree: ast.AST) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _targets(source: str) -> list[tuple[int, str, str]]:
    """``(lineno, dotted module, attribute)`` for every escape-hatch patch call that names a resolvable target."""
    tree = ast.parse(source)
    alias = _aliases(tree)
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        first = node.args[0] if node.args else None
        second = node.args[1] if len(node.args) > 1 else None
        if fname == "setattr" and _hatch(node, "raising"):
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value:
                mod, attr = first.value.rsplit(".", 1)
                out.append((node.lineno, mod, attr))
            elif (isinstance(first, ast.Name) and first.id in alias and isinstance(second, ast.Constant)
                  and isinstance(second.value, str)):
                out.append((node.lineno, alias[first.id], second.value))
        elif fname == "object" and _hatch(node, "create"):
            if (isinstance(first, ast.Name) and first.id in alias and isinstance(second, ast.Constant)
                    and isinstance(second.value, str)):
                out.append((node.lineno, alias[first.id], second.value))
        elif fname == "patch" and _hatch(node, "create"):
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value:
                mod, attr = first.value.rsplit(".", 1)
                out.append((node.lineno, mod, attr))
    return out


def _stale(source: str, module_source=None) -> list[tuple[int, str]]:
    read = module_source or (lambda p: p.read_text(encoding="utf-8"))
    hits = []
    for lineno, mod, attr in _targets(source):
        path = _resolve(mod)
        if path is None:
            continue
        if not re.search(r"\b" + re.escape(attr) + r"\b", read(path)):
            hits.append((lineno, f"{mod}.{attr}"))
    return hits


def test_no_escape_hatch_patch_of_a_name_its_module_never_mentions():
    files = repo_files(REPO_ROOT, ("*.py",))
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    hits = []
    seen = 0
    for p in files:
        rel = relative_posix(p)
        if not _is_test_file(rel):
            continue
        try:
            src = p.read_text(encoding="utf-8")
            found = _stale(src)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        seen += 1
        hits.extend(f"{rel}:{n} {target}" for n, target in found)
    assert seen > 100, "the test-file walk returned almost nothing"
    assert not hits, f"raising=False / create=True patch of a name the module never mentions: {hits}"


def test_the_detector_sees_every_escape_hatch_shape():
    """Positive control: each spelling is flagged against a repo module, and a live name is not."""
    mod = "core.aram_item_interaction"
    gone = "zz_not_a_real_name_309"
    live = "_CHAMP_NAMES"
    for line in (
        f'monkeypatch.setattr("{mod}.{gone}", 1, raising=False)',
        f'monkeypatch.setattr(aii, "{gone}", 1, raising=False)',
        f'patch.object(aii, "{gone}", create=True)',
        f'patch("{mod}.{gone}", create=True)',
    ):
        src = f"import core.aram_item_interaction as aii\n{line}\n"
        assert _stale(src) == [(2, f"{mod}.{gone}")], line
    for line in (
        f'monkeypatch.setattr("{mod}.{live}", 1, raising=False)',
        f'monkeypatch.setattr(aii, "{live}", 1)',
        f'patch("{mod}.{gone}")',
    ):
        assert _stale(f"import core.aram_item_interaction as aii\n{line}\n") == [], line


def test_a_stdlib_or_unresolvable_target_is_skipped_not_flagged():
    src = 'import signal\nmonkeypatch.setattr(signal, "SIGKILL", 9, raising=False)\n'
    assert _stale(src) == []
