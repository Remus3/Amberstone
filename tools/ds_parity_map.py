"""RM-143 P1 - build the DS route-vs-engine parity map.

Answers, per HTTP route, three questions no existing guard asks:

  * which engine parameters does this route actually FORWARD (``carried``),
  * which body keys does it parse and then NEVER forward (``dropped``),
  * which engine parameters can no caller reach through it (``unreachable``).

The two shipped guards
(``agents/daemon_slayer/tests/test_route_seams_reach_the_client.py`` and its
``_per_route`` sibling) ask the server-vs-CLIENT question and filter body keys
to seam-shaped names (``apply_`` / ``assume_`` / ``gate_`` / ``exclude_``)
first. Transport keys carry none of those prefixes, so both are blind to the
RM-118 failure shape by construction: a flag wired onto a route whose body
cannot carry the flag's input is settable, guard-green and arithmetically
inert.

Method: AST over ``server.py`` for what each handler parses and forwards, plus
``inspect.signature`` of each engine callee for what the engine accepts. The
signature is authoritative and the docstring is not - the RM-118 ownership
prose was measured wrong in BOTH directions in one 2026-07-30 run.

Usage:
  python tools/ds_parity_map.py            # human summary
  python tools/ds_parity_map.py --json     # write ops/runtime/ds_parity_map.json
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = ROOT / "agents" / "daemon_slayer" / "server.py"
DEFAULT_OUT = ROOT / "ops" / "runtime" / "ds_parity_map.json"

# Body-parse helpers in server.py. Each takes ``body`` first and the key second,
# except _coerce_str_list which is fed ``body.get("key")`` directly.
_PARSE_HELPERS = {
    "_opt_int", "_opt_str", "_opt_float", "_opt_bool",
    "_required_str", "_required_int", "_required_float",
}

# A seam flag and the body key(s) it reads. A route that parses the flag but
# not the transport ships an inert seam. Sourced from measured incidents, not
# from prose: RM-118 (rune offense lane, /dps carried the flag and not
# ``rune_ids``) and its four sibling routes wired in R136.
FLAG_TRANSPORTS: dict[str, tuple[str, ...]] = {
    "apply_rune_offense_grants": ("rune_ids",),
    "apply_rune_health_grants": ("rune_ids",),
    "apply_rune_resist_grants": ("rune_ids",),
}


def _server_module():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from agents.daemon_slayer import server  # noqa: PLC0415
    return server


def _body_key(node: ast.AST) -> str | None:
    """Return the body key a parse-helper call reads, else None."""
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    # body.get("key")
    if (isinstance(fn, ast.Attribute) and fn.attr == "get"
            and isinstance(fn.value, ast.Name) and fn.value.id == "body"
            and node.args and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)):
        return node.args[0].value
    # _opt_bool(body, "key", default)
    if (isinstance(fn, ast.Name) and fn.id in _PARSE_HELPERS
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name) and node.args[0].id == "body"
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)):
        return node.args[1].value
    return None


def _collect_parses(fn: ast.FunctionDef) -> tuple[dict[str, set[str]], list[str]]:
    """Map local variable -> body keys it carries, and list every key parsed.

    Taint is TRANSITIVE and reaches through containers, because two measured
    false positives came from assuming otherwise: ``_route_rank_tank`` builds
    ``assumed_share_kwargs["assume_item_crit_dr"] = ...`` and splats it with
    ``**``, and ``_route_matchup`` aliases ``sequence`` through a second local
    before forwarding. A direct-assignment-only reading calls both DROPPED,
    which would have written a false ledger entry against working code.
    """
    keys: list[str] = []
    for node in ast.walk(fn):
        key = _body_key(node)
        if key is not None and key not in keys:
            keys.append(key)

    taint: dict[str, set[str]] = {}

    def _names(expr: ast.AST) -> set[str]:
        return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}

    def _keys_of(expr: ast.AST) -> set[str]:
        found = {k for sub in ast.walk(expr)
                 if (k := _body_key(sub)) is not None}
        for name in _names(expr):
            found |= taint.get(name, set())
        return found

    # iterate to a fixpoint so order of statements does not matter
    for _ in range(6):
        before = {k: set(v) for k, v in taint.items()}
        for node in ast.walk(fn):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                got = _keys_of(node.value)
                if not got:
                    continue
                for target in targets:
                    # x = ... / x, y = ... / d["k"] = ...
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name):
                            taint.setdefault(sub.id, set()).update(got)
        if taint == before:
            break
    return taint, keys


def _engine_calls(fn: ast.FunctionDef, server) -> list[tuple[str, ast.Call]]:
    """Calls to a public engine function imported into server.py."""
    out: list[tuple[str, ast.Call]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        if name.startswith("_"):
            continue
        obj = getattr(server, name, None)
        if obj is None or not callable(obj):
            continue
        mod = getattr(obj, "__module__", "") or ""
        if not mod.startswith("agents.daemon_slayer") or mod == server.__name__:
            continue
        out.append((name, node))
    return out


def _params(obj) -> list[str]:
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError):
        return []
    return [p for p in sig.parameters if not p.startswith("_")]


def build_map() -> dict[str, dict]:
    server = _server_module()
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
    handlers = {
        node.name: node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_route_")
    }

    out: dict[str, dict] = {}
    for route, handler_fn in server._POST_ROUTES.items():
        fn = handlers.get(handler_fn.__name__)
        if fn is None:
            out[route] = {"handler": handler_fn.__name__, "engines": [],
                          "body_keys": [], "carried": {}, "dropped": [],
                          "unreachable": []}
            continue

        taint, body_keys = _collect_parses(fn)
        carried: dict[str, str] = {}
        engine_params: list[str] = []
        engines: list[str] = []
        forwarded_keys: set[str] = set()

        def _keys_in(expr: ast.AST, taint: dict[str, set[str]] = taint) -> set[str]:
            found = {k for sub in ast.walk(expr)
                     if (k := _body_key(sub)) is not None}
            for n in ast.walk(expr):
                if isinstance(n, ast.Name):
                    found |= taint.get(n.id, set())
            return found

        for name, call in _engine_calls(fn, server):
            engines.append(name)
            params = _params(getattr(server, name))
            for p in params:
                if p not in engine_params:
                    engine_params.append(p)

            for i, arg in enumerate(call.args):
                got = _keys_in(arg)
                forwarded_keys |= got
                if i < len(params):
                    carried[params[i]] = sorted(got)[0] if got else ""
            for kw in call.keywords:
                got = _keys_in(kw.value)
                forwarded_keys |= got
                if kw.arg is not None:
                    carried[kw.arg] = sorted(got)[0] if got else ""
                else:
                    # ``**splat`` - attribute by name, the only sound rule
                    # without evaluating the dict (see _route_rank_tank).
                    for key in got:
                        if key in params:
                            carried[key] = key

        out[route] = {
            "handler": handler_fn.__name__,
            "engines": sorted(set(engines)),
            "body_keys": body_keys,
            "carried": carried,
            "dropped": [k for k in body_keys if k not in forwarded_keys],
            "unreachable": [p for p in engine_params if p not in carried],
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="write the JSON map")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    m = build_map()
    if args.json:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(out)
        print(f"map: {out}")

    drop = sum(len(e["dropped"]) for e in m.values())
    unreach = sum(len(e["unreachable"]) for e in m.values())
    print(f"routes: {len(m)}  dropped-keys: {drop}  unreachable-params: {unreach}")
    for route, e in sorted(m.items()):
        if e["dropped"] or e["unreachable"]:
            print(f"  {route:26s} dropped={e['dropped']} unreachable={e['unreachable']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
