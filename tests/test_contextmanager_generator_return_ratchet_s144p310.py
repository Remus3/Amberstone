"""S144-P-310 - a ``@contextmanager`` generator is annotated ``Generator``, not ``Iterator``, and is held at zero.

``contextlib.contextmanager`` wraps a GENERATOR function: the body ``yield``s once and may receive an exception at
that yield. ``Iterator[X]`` is a true statement about the call result but hides that it is a generator (ruff
UP052, preview-only, so ``ruff.toml`` never enforced it). Measured 2026-11-06: five sites carried the weaker
annotation (``core/decision_detector.py`` plus four test helpers); they now say ``Generator[X, None, None]``.

The detector is an AST walk over every tracked ``.py``: a function decorated ``contextmanager`` /
``contextlib.contextmanager`` / ``asynccontextmanager`` whose return annotation is ``Iterator[...]``,
``Iterable[...]`` (or the ``typing.`` / ``collections.abc.`` spelling, or the string form). ``AsyncIterator`` on an
``asynccontextmanager`` is the async twin and is flagged the same way (it wants ``AsyncGenerator``). The baseline is
empty.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_CM = {"contextmanager": {"Iterator", "Iterable"},
       "asynccontextmanager": {"AsyncIterator", "AsyncIterable"}}


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _ann_head(ann: ast.AST | None) -> str | None:
    """The outermost type name of a return annotation, string form included."""
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        try:
            ann = ast.parse(ann.value, mode="eval").body
        except SyntaxError:
            return None
    if isinstance(ann, ast.Subscript):
        ann = ann.value
    return _name(ann) if ann is not None else None


def _weak(source: str) -> list[tuple[int, str]]:
    """``(lineno, function name)`` for each context-manager generator annotated with an iterator type."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        head = _ann_head(node.returns)
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            weak = _CM.get(_name(target) or "")
            if weak and head in weak:
                out.append((node.lineno, node.name))
    return out


def test_no_contextmanager_generator_is_annotated_as_a_bare_iterator():
    files = repo_files(REPO_ROOT, ("*.py",))
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    hits = []
    seen = 0
    for p in files:
        try:
            found = _weak(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        seen += 1
        hits.extend(f"{relative_posix(p)}:{n} {name}" for n, name in found)
    assert seen > 100, "the parse walk returned almost nothing"
    assert not hits, f"@contextmanager generator annotated Iterator / Iterable (use Generator): {hits}"


def test_the_detector_sees_each_spelling():
    for ann in ("Iterator[None]", "typing.Iterator[int]", "collections.abc.Iterator[int]",
                "Iterable[None]", "'Iterator[None]'"):
        for dec in ("contextmanager", "contextlib.contextmanager", "contextlib.contextmanager()"):
            src = f"@{dec}\ndef f() -> {ann}:\n    yield\n"
            assert _weak(src) == [(2, "f")], (dec, ann)
    async_src = "@asynccontextmanager\nasync def g() -> AsyncIterator[None]:\n    yield\n"
    assert _weak(async_src) == [(2, "g")]


def test_a_generator_annotation_or_a_plain_iterator_function_is_not_flagged():
    assert _weak("@contextmanager\ndef f() -> Generator[None, None, None]:\n    yield\n") == []
    assert _weak("@contextmanager\ndef f():\n    yield\n") == []
    assert _weak("def f() -> Iterator[int]:\n    yield 1\n") == []
    assert _weak("@property\ndef f() -> Iterator[int]:\n    yield 1\n") == []
    assert _weak("@asynccontextmanager\nasync def g() -> AsyncGenerator[None, None]:\n    yield\n") == []
