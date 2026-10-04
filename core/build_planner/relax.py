# arch: constraint-relaxing recommender - auto-relax ladder reports dropped soft constraints | section=coaching | frozen=no
"""core.build_planner.relax - constraint-relaxing recommender (P2-10).

An exhaustive search over caller-enumerated candidates (single items or whole
builds / combinations), scored by several named terms. When the user's filters
leave NO result, an auto-relax ladder drops SOFT constraints one rung at a
time, in the declared ladder order, and the result reports exactly which ones
it dropped (``Result.relaxed``).

HARD constraints are never relaxed:
  * the built-in ``LEGALITY`` constraint - an injected ``legal(candidate)``
    predicate (patch / mode legality). This module does NOT import the DS
    engine (build_planner split-brain guard, tests/test_planner_beam_search.py
    StructuralGuardTests); core/build_planner_legality.py builds the predicate
    from the DS rank.py pool filter.
  * any ``Constraint(..., hard=True)``.
A ladder that names a hard constraint (or ``LEGALITY``, or an unknown name) is
REFUSED with ValueError at the API boundary. If the hard constraints alone
leave nothing, the result is empty with ``relaxed == []`` and a reason.

Every scored candidate carries its per-term contributions (weight * raw term)
whose sum IS the score, and ``Result.explain`` says why the winner wins
(per-term margin over the runner-up). Ties break on the candidate key
(ascending) so the ranking never depends on input order.

Constraints (+ ladder) serialise to a stable, shareable state string:
canonical JSON (sorted keys, compact separators) -> urlsafe base64 without
padding. ``encode_state(*decode_state(s)) == s`` and
``decode_state(encode_state(c, l)) == (c, l)``.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import base64
import binascii
import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

# Reserved name of the built-in hard (legality) constraint.
LEGALITY = "legal"

# State-string schema version (bump on an incompatible layout change).
STATE_VERSION = 1

DEFAULT_TOP_N = 5


def _cmp(op: str) -> Callable[[Any, Any], bool]:
    return {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "lt": lambda a, b: a < b,
        "le": lambda a, b: a <= b,
        "gt": lambda a, b: a > b,
        "ge": lambda a, b: a >= b,
        "in": lambda a, b: a in b,
        "not_in": lambda a, b: a not in b,
        "contains": lambda a, b: b in a,
        "not_contains": lambda a, b: b not in a,
    }[op]


OPS: frozenset = frozenset({
    "eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "contains",
    "not_contains",
})


def _freeze(value: Any) -> Any:
    """Lists -> tuples (recursively) so a Constraint is hashable and a JSON
    round-trip compares equal to the original."""
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, dict):
        raise ValueError("constraint value may not be a mapping")
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class Constraint:
    """``candidate[field] <op> value``. A missing field or an incomparable
    value FAILS the constraint (never raises)."""

    name: str
    field: str
    op: str
    value: Any
    hard: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("constraint name must be a non-empty str")
        if self.name == LEGALITY:
            raise ValueError(f"constraint name {LEGALITY!r} is reserved")
        if not isinstance(self.field, str) or not self.field:
            raise ValueError("constraint field must be a non-empty str")
        if self.op not in OPS:
            raise ValueError(f"unknown constraint op {self.op!r}")
        if not isinstance(self.hard, bool):
            raise ValueError("constraint hard flag must be a bool")
        object.__setattr__(self, "value", _freeze(self.value))

    def holds(self, candidate: Mapping) -> bool:
        if self.field not in candidate:
            return False
        try:
            return bool(_cmp(self.op)(candidate[self.field], self.value))
        except TypeError:
            return False

    def to_dict(self) -> dict:
        return {"name": self.name, "field": self.field, "op": self.op,
                "value": _thaw(self.value), "hard": self.hard}


@dataclass(frozen=True)
class Scored:
    """One ranked candidate with its per-term breakdown."""

    key: str
    candidate: Mapping
    score: float
    contributions: tuple  # ((term_name, weight * raw), ...) sorted by name


@dataclass(frozen=True)
class Result:
    results: tuple  # tuple[Scored, ...], best first
    relaxed: list  # soft constraint names dropped, in ladder order
    reason: str
    explain: dict


def _validate(constraints: Sequence[Constraint],
              ladder: Sequence[str]) -> tuple:
    cons = tuple(constraints)
    for c in cons:
        if not isinstance(c, Constraint):
            raise ValueError(f"not a Constraint: {c!r}")
    names = [c.name for c in cons]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate constraint names in {names!r}")
    by_name = {c.name: c for c in cons}
    rungs = tuple(ladder)
    if len(set(rungs)) != len(rungs):
        raise ValueError(f"duplicate ladder rung in {list(rungs)!r}")
    for rung in rungs:
        if rung == LEGALITY:
            raise ValueError(
                f"refused: ladder names the hard {LEGALITY!r} constraint")
        if rung not in by_name:
            raise ValueError(f"refused: ladder names unknown constraint {rung!r}")
        if by_name[rung].hard:
            raise ValueError(f"refused: ladder names hard constraint {rung!r}")
    return cons, rungs


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)


def _key_of(candidate: Mapping, key_field: str) -> str:
    if key_field in candidate:
        return str(candidate[key_field])
    return _canonical(candidate)


def _score(candidate: Mapping, terms: Mapping[str, Callable],
           weights: Mapping[str, float]) -> tuple:
    contribs = []
    for name in sorted(terms):
        raw = float(terms[name](candidate))
        contribs.append((name, float(weights.get(name, 1.0)) * raw))
    return tuple(contribs), math.fsum(c for _, c in contribs)


def _explain(ranked: Sequence[Scored], relaxed: list) -> dict:
    if not ranked:
        return {}
    win = ranked[0]
    out = {
        "winner": win.key,
        "score": win.score,
        "terms": dict(win.contributions),
        "relaxed": list(relaxed),
        "runner_up": None,
        "margin": None,
        "margin_by_term": {},
    }
    if len(ranked) > 1:
        ru = ranked[1]
        ru_terms = dict(ru.contributions)
        out["runner_up"] = ru.key
        out["margin"] = win.score - ru.score
        out["margin_by_term"] = {
            n: c - ru_terms.get(n, 0.0) for n, c in win.contributions}
    return out


def recommend(
    candidates: Iterable[Mapping],
    constraints: Sequence[Constraint],
    ladder: Sequence[str] = (),
    *,
    terms: Mapping[str, Callable[[Mapping], float]],
    weights: Optional[Mapping[str, float]] = None,
    legal: Optional[Callable[[Mapping], bool]] = None,
    top_n: int = DEFAULT_TOP_N,
    key_field: str = "id",
) -> Result:
    """Rank ``candidates`` under ``constraints``, relaxing soft ones along
    ``ladder`` only while the result is empty. See the module docstring."""
    cons, rungs = _validate(constraints, ladder)
    if not terms:
        raise ValueError("at least one scoring term is required")
    w = dict(weights or {})
    unknown = sorted(set(w) - set(terms))
    if unknown:
        raise ValueError(f"weights name unknown terms {unknown!r}")
    if top_n < 1:
        raise ValueError("top_n must be >= 1")

    pool = list(candidates)
    hard = [c for c in cons if c.hard]
    hard_ok = [
        cand for cand in pool
        if (legal is None or legal(cand)) and all(c.holds(cand) for c in hard)
    ]
    if not hard_ok:
        hard_names = ([LEGALITY] if legal is not None else []) + [
            c.name for c in hard]
        why = ("no candidates supplied" if not pool else
               f"hard constraints {hard_names!r} leave no candidate")
        return Result((), [], why, {})

    active = [c for c in cons if not c.hard]
    relaxed: list = []
    remaining = list(rungs)
    while True:
        survivors = [cand for cand in hard_ok
                     if all(c.holds(cand) for c in active)]
        if survivors or not remaining:
            break
        drop = remaining.pop(0)
        relaxed.append(drop)
        active = [c for c in active if c.name != drop]

    if not survivors:
        left = [c.name for c in active]
        return Result((), relaxed,
                      f"ladder exhausted after dropping {relaxed!r}; "
                      f"unrelaxable soft constraints {left!r} leave no candidate",
                      {})

    scored = []
    for cand in survivors:
        contribs, total = _score(cand, terms, w)
        scored.append(Scored(_key_of(cand, key_field), cand, total, contribs))
    scored.sort(key=lambda s: (-s.score, s.key))
    ranked = tuple(scored[:top_n])
    reason = ("strict constraints satisfied" if not relaxed
              else f"relaxed {relaxed!r} to find a result")
    return Result(ranked, relaxed, reason, _explain(ranked, relaxed))


def encode_state(constraints: Sequence[Constraint],
                 ladder: Sequence[str] = ()) -> str:
    """Constraints + ladder -> stable urlsafe base64 (no padding) string."""
    cons, rungs = _validate(constraints, ladder)
    doc = {"v": STATE_VERSION, "c": [c.to_dict() for c in cons],
           "l": list(rungs)}
    try:
        raw = json.dumps(doc, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"constraint value is not JSON-serialisable: {exc}")
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def decode_state(state: str) -> tuple:
    """Inverse of ``encode_state`` -> (tuple[Constraint, ...], tuple[str, ...])."""
    try:
        pad = "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode((state + pad).encode("ascii"))
        doc = json.loads(raw.decode("ascii"))
    except (binascii.Error, UnicodeError, ValueError, TypeError) as exc:
        raise ValueError(f"malformed state string: {exc}")
    if not isinstance(doc, dict) or doc.get("v") != STATE_VERSION:
        raise ValueError("unsupported state string version")
    try:
        cons = tuple(Constraint(**c) for c in doc["c"])
        rungs = tuple(doc["l"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed state string: {exc}")
    _validate(cons, rungs)
    return cons, rungs
