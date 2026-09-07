"""Regression guard for the 2026-07-27 skip audit (commit 69c3f848).

That audit converted 51 always-passing skip guards into real failures but
shipped no machine check, so nothing stopped instance #52. This module is that
check: a static AST pass over every module in the RC-owned test trees that
resolves each skip condition to the set of things it actually depends on, and
fails when a skip fires on something a checkout always has.

The rule, restated mechanically:

    A test may skip only when an ENVIRONMENT CAPABILITY is absent - an OS
    feature, an external binary, an optional third-party import, a network
    endpoint, an opt-in env var, a sibling-repo tree, gitignored machine-local
    state, the SHAPE of the checkout the module is running in, or a tracked
    path behind a git-LFS filter. A tracked-in-git artifact is present in
    EVERY checkout, so a skip gated on one can only fire when the thing under
    test is broken - exactly the moment the test must FAIL.

The ONE carve-out is git-LFS, and it is a capability question rather than an
exception to the rule. `git clone` fetches an LFS-filtered blob as a ~130-byte
pointer stub unless the client has git-lfs installed AND smudges it (or the
checkout runs `git lfs pull`). No workflow in `.github/workflows/` passes
`lfs:` to `actions/checkout`, so in CI those paths are pointer stubs BY
DESIGN - permanently, for every run. "The content is not fetched here" is an
environment capability in exactly the sense the rule means, so a skip gated on
a tracked-AND-LFS path is CAPABILITY. Tracked and NOT LFS stays DEFECT, which
is the whole of class B5; see `_is_lfs_chain` for how the two are told apart
and why a chain that reaches even one non-LFS tracked file is not rescued.

Two design constraints come from prior guards in this repo that were green over
the very class they existed to catch:

1. The universe is derived from the PRODUCING side. Test modules are globbed
   out of the trees, never listed. `tests/test_no_console_flash_scheduled_tools.py`
   carried a hand-maintained tuple of spawner modules and silently stopped
   covering every file added after it was written.
2. Conditions are RESOLVED, not grepped. That same predecessor searched for a
   literal `0x08000000`, which a module passing the flag to nothing satisfied.
   Here every condition is parsed, its module-level and function-local bindings
   are followed, calls into first-party modules are opened and read, and path
   expressions are evaluated symbolically before being checked against
   `git ls-files`.
"""
from __future__ import annotations

import ast
import fnmatch
import functools
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent

# Every tree in this repo that pytest collects test modules from. Widened
# 2026-08-06 (RM-119 B5 re-census): the original pair left
# agents/agent3_testing/suite, tools/tests and benchmarks OUTSIDE the guard, so
# a net-new skip gated on a tracked artifact could be added there and no test
# in the repo would notice. The audit this module descends from
# (docs/SKIPIF_AUDIT_2026-07-27.md) already had agent3 in scope; the guard did
# not, which is exactly the producing-side gap constraint 1 warns about.
#
# NARROWED 2026-09-06: "benchmarks" removed because the tree was deleted with
# .github/workflows/codspeed.yml - see docs/OPERATIONS.md "Why CodSpeed was
# dropped". This guard is the reason that deletion could not be silent: it
# failed twice on the missing directory rather than shrinking quietly, which is
# the producing-side property it exists for. Removing a tree means editing this
# tuple, in the same commit, on purpose.
_TEST_TREES = ("tests", "agents/daemon_slayer/tests",
               "agents/agent3_testing/suite", "tools/tests")

_GIT = shutil.which("git")

if _GIT is None:
    pytest.skip("git not on PATH - trackedness is unresolvable without it",
                allow_module_level=True)


# --------------------------------------------------------------------------- #
# Ground truth: what a checkout always has
# --------------------------------------------------------------------------- #
def _git_tracked() -> frozenset[str]:
    out = subprocess.run(
        [_GIT, "ls-files", "-z"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True,
        timeout=180, check=True,
    ).stdout
    return frozenset(p for p in out.split("\0") if p)


def _suffix_index(tracked: frozenset[str]) -> frozenset[str]:
    """Every segment-boundary suffix of every tracked file AND tracked dir.

    Path expressions in test code are almost never rooted at a literal - they
    hang off `__file__` or a helper constant - so trackedness is decided on the
    resolvable TAIL of the chain.
    """
    out: set[str] = set()
    for rel in tracked:
        parts = rel.split("/")
        n = len(parts)
        for end in range(1, n + 1):
            for start in range(end):
                out.add("/".join(parts[start:end]))
    return frozenset(out)


_TRACKED = _git_tracked()
_TRACKED_SUFFIXES = _suffix_index(_TRACKED)


def _git_lfs_tracked(tracked: frozenset[str]) -> frozenset[str]:
    """The subset of `tracked` that git resolves to `filter=lfs`.

    ASKED, never derived. The three alternatives were all rejected:

    * hardcoding `data/daemon_slayer/laning_scenarios/**` pins the guard to
      today's one LFS rule, so the second one added would be misclassified
      silently - the same hand-list failure the module docstring warns about;
    * parsing `.gitattributes` means re-implementing gitattributes semantics
      (nested files down the tree, last-match-wins precedence, negation,
      `!` and `**` globbing) and getting any of it wrong flips a verdict;
    * `git lfs ls-files` needs the git-lfs binary, which is exactly the thing a
      pointer-stub checkout may not have.

    `git check-attr` is core git and answers the real question - what does git
    think this path's filter is - including every attribute source and
    precedence rule. One batched `--stdin` call covers the whole tracked set:
    MEASURED 2026-08-06 at 0.03s for 5220 paths, against one subprocess per
    candidate path had this been asked lazily per chain.

    git being absent is already handled: the module skips at import when `git`
    is not on PATH, because trackedness itself is unresolvable without it.
    """
    if not tracked:
        return frozenset()
    out = subprocess.run(
        [_GIT, "check-attr", "filter", "-z", "--stdin"],
        input="\0".join(sorted(tracked)),
        cwd=str(_REPO_ROOT), capture_output=True, text=True,
        timeout=180, check=True,
    ).stdout
    # `-z` output is a flat NUL-separated stream of (path, attr, value) triples.
    fields = out.split("\0")
    return frozenset(
        fields[i] for i in range(0, len(fields) - 2, 3)
        if fields[i + 2] == "lfs"
    )


_LFS_TRACKED = _git_lfs_tracked(_TRACKED)
_NON_LFS_TRACKED = _TRACKED - _LFS_TRACKED


def _chain_matches_any(chain: str, pool: frozenset[str]) -> bool:
    """Does `chain` name any path in `pool`, under `_is_tracked_chain`'s rule?

    `_is_tracked_chain` asks the same question against a precomputed suffix
    index of the WHOLE tracked set; this asks it against an arbitrary subset,
    so the two must agree on what "names" means. It does: the index is built
    from every contiguous segment slice of every tracked path, which is what
    the loop below tests directly.
    """
    if "*" in chain or "?" in chain or "[" in chain:
        pats = (chain, "*/" + chain)
        return any(fnmatch.fnmatch(rel, p) for rel in pool for p in pats)
    needle = chain.split("/")
    n = len(needle)
    for rel in pool:
        parts = rel.split("/")
        if any(parts[i:i + n] == needle for i in range(len(parts) - n + 1)):
            return True
    return False


@functools.cache
def _is_lfs_chain(chain: str) -> bool:
    """Every tracked path this chain can name is behind an LFS filter.

    The ALL quantifier is the load-bearing half, and inverting it re-opens
    class B5 wholesale. A resolved chain is a suffix (really any contiguous
    segment slice), so it can name many tracked files: `data` names thousands,
    `laning_scenarios_aram.json` names three. Rescuing a chain because SOME
    file it names is LFS would rescue `data` - and with it every B5 defect
    whose gate resolves to a broad directory. So the chain is a capability gate
    only when the LFS set fully covers it: at least one match there, and none
    outside it. `data/daemon_slayer` reaches `current.txt` and stays DEFECT;
    `data/daemon_slayer/laning_scenarios` reaches only the seven LFS tables and
    becomes CAPABILITY.

    Cost: the cheap pool (7 paths today) is tested first, so the full-tracked
    scan only runs for a chain that already looks LFS, and the cache means once
    per distinct chain across all five test trees.
    """
    if not chain or not _LFS_TRACKED:
        return False
    if not _chain_matches_any(chain, _LFS_TRACKED):
        return False
    return not _chain_matches_any(chain, _NON_LFS_TRACKED)


def _git_vanished() -> tuple[frozenset[str], frozenset[str]]:
    """Paths git history shows were tracked once and are NOT tracked at HEAD.

    This is the ground truth for RM-119 class B4 - a skip whose premise ROTTED.
    "Was there and is gone" is the definition of a rotted premise, which is why
    this and not the filesystem is the right oracle: machine-local state
    (`data/rewind_history.db`, `data/fusion_shadow.jsonl`, and gitignored build
    output generally) was never in history by construction, so it cannot be
    flagged here.

    `--diff-filter=DR` is load-bearing, and D alone is the trap that hid the
    headline instance. The `pengu/` stub was RENAMED into
    `docs/_archive/2026-07-07-pengu-stub/` at f08ade78, and git records a
    rename as R with the old path in field 2 - so a D-only scan reports it as
    never deleted and the guard sees nothing. Measured 2026-08-06: D alone
    yields 439 vanished paths and misses pengu entirely; DR yields 857 and
    catches it.
    """
    out = subprocess.run(
        [_GIT, "log", "--all", "--diff-filter=DR", "--name-status", "--format="],
        cwd=str(_REPO_ROOT), capture_output=True, text=True,
        timeout=300, check=True,
    ).stdout
    seen: set[str] = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if parts[0].startswith("D") and len(parts) >= 2:
            seen.add(parts[1].strip())
        elif parts[0].startswith("R") and len(parts) >= 3:
            # field 1 is the OLD path - the one that stopped existing.
            seen.add(parts[1].strip())
    gone = seen - _TRACKED
    dirs: set[str] = set()
    for rel in gone:
        segs = rel.split("/")
        for end in range(1, len(segs)):
            dirs.add("/".join(segs[:end]))
    # A directory that still holds tracked files has not vanished at all.
    dirs = {d for d in dirs
            if not any(t.startswith(d + "/") for t in _TRACKED)}
    return frozenset(gone), frozenset(dirs)


_VANISHED, _VANISHED_DIRS = _git_vanished()


def _is_vanished_chain(chain: str) -> bool:
    """ROOT-ANCHORED, deliberately - suffix matching destroys the precision.

    Unlike `_is_tracked_chain`, this does NOT consult a suffix index. Measured
    2026-08-06: suffix matching flags `16.9.1`, a `tmp_path` fixture directory
    in test_ddragon_mirror_prune.py that collides with the deleted DDragon
    mirror `data/daemon_slayer/16.9.1/`, and the deleted-then-Desktop-relocated
    `monitor.html`. Anchoring at the repo root drops both while still catching
    root-level `pengu/` and `_archive/2026-05-01-audit/**`.
    """
    return bool(chain) and (chain in _VANISHED or chain in _VANISHED_DIRS)


def _is_tracked_chain(chain: str) -> bool:
    if not chain:
        return False
    if "*" in chain or "?" in chain or "[" in chain:
        pats = (chain, "*/" + chain)
        return any(
            fnmatch.fnmatch(rel, pat) for rel in _TRACKED for pat in pats
        )
    return chain in _TRACKED_SUFFIXES


# --------------------------------------------------------------------------- #
# Skip-construct recognition
# --------------------------------------------------------------------------- #
_DECORATOR_SKIPS = {
    "pytest.mark.skipif", "mark.skipif", "skipif",
    "unittest.skipIf", "skipIf",
    "unittest.skipUnless", "skipUnless",
}
_IMPORTORSKIP = "importorskip"
_BODY_SKIPS = {"pytest.skip", "skip"}

# Call tails that ARE a skip decision even though they are not a pytest or
# unittest primitive.
#
# `require_live_engine` added 2026-08-06 (RM-119 B2), and the reason is a
# coverage loss this guard would otherwise have taken silently. B2 moved six
# DS-engine liveness skips out of five modules and behind that one shared
# helper (tests/test_ds_live_route_gate.py). MEASURED before and after at
# 09d9c7a1: this scanner saw 7 sites across those five modules and then saw 1.
# Four modules dropped to ZERO visible sites and
# tests/test_build_orders_family_a_guard.py lost its `network` evidence
# entirely. Nothing was wrong with any of them - they simply stopped LOOKING
# like skips, which is the same disappearing act constraint 1 in the module
# docstring warns about, arriving through a refactor instead of a hand-kept
# list. Recognising the helper restores the population and, because a bare
# site widens to its enclosing function, the `dsc.is_engine_up` call there
# still resolves to a `network` capability signal.
_BODY_SKIP_TAILS = {"skipTest", "require_live_engine"}
_SKIP_EXC_SUFFIXES = ("SkipTest", "Skipped")

# UNCONDITIONAL skips. Added 2026-08-06 after a verifier proved the scanner was
# blind to all four, which is worse than a misclassification: an invisible site
# is not weighed at all, so `_B4_CONVERTED` reported green over a re-injected
# `pytestmark = pytest.mark.skip(...)` - the EXACT spelling of the original
# pengu defect this slice was converting. `_DECORATOR_SKIPS` carried only the
# conditional forms, and `_skip_sites` visited only `ast.Raise` and `ast.Call`,
# so the bare `@pytest.mark.skip` decorator (an `ast.Attribute`, never a Call)
# could not be seen even in principle.
#
# These take NO condition, so they can never gate on an environment capability;
# they are a disabled test by definition and are classified DEFECT outright.
# Measured before shipping: the five RC test trees contain ZERO of them today,
# so recognising them adds no false positives and turns nothing red.
_UNCONDITIONAL_SKIPS = {
    "pytest.mark.skip", "mark.skip", "unittest.skip",
}

_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
           ast.ClassDef, ast.Lambda)
_CALLABLE_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)

CAPABILITY = "CAPABILITY"
DEFECT = "DEFECT"
ROTTED = "ROTTED"
UNRESOLVED = "UNRESOLVED"


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    elif isinstance(cur, ast.Call):
        parts.append("()")
    else:
        return ""
    return ".".join(reversed(parts))


@dataclass
class _Site:
    rel: str
    line: int
    kind: str
    condition: ast.AST | None
    node: ast.AST

    @property
    def label(self) -> str:
        return f"{self.rel}:{self.line} ({self.kind})"


@dataclass
class _Signals:
    """Everything a skip condition was measured to depend on."""

    unconditional: bool = False
    platform: bool = False
    env: bool = False
    binary: bool = False
    optional_import: bool = False
    network: bool = False
    tree_shape: bool = False
    external_tree: bool = False
    tracked: set = field(default_factory=set)
    lfs: set = field(default_factory=set)
    untracked: set = field(default_factory=set)
    vanished: set = field(default_factory=set)
    firstparty_import: set = field(default_factory=set)

    def merge(self, other: "_Signals") -> None:
        self.unconditional |= other.unconditional
        self.platform |= other.platform
        self.env |= other.env
        self.binary |= other.binary
        self.optional_import |= other.optional_import
        self.network |= other.network
        self.tree_shape |= other.tree_shape
        self.external_tree |= other.external_tree
        self.tracked |= other.tracked
        self.lfs |= other.lfs
        self.untracked |= other.untracked
        self.vanished |= other.vanished
        self.firstparty_import |= other.firstparty_import

    @property
    def capability(self) -> bool:
        return (self.platform or self.env or self.binary
                or self.optional_import or self.network
                or self.tree_shape or self.external_tree)

    def evidence(self) -> str:
        bits = [n for n in ("unconditional", "platform", "env", "binary",
                            "optional_import",
                            "network", "tree_shape", "external_tree")
                if getattr(self, n)]
        if self.tracked:
            bits.append("tracked=" + ",".join(sorted(self.tracked)))
        if self.lfs:
            bits.append("tracked-lfs=" + ",".join(sorted(self.lfs)))
        if self.vanished:
            bits.append("was-tracked-now-gone="
                        + ",".join(sorted(self.vanished)))
        if self.untracked:
            bits.append("untracked=" + ",".join(sorted(self.untracked)))
        if self.firstparty_import:
            bits.append("first-party import="
                        + ",".join(sorted(self.firstparty_import)))
        return "; ".join(bits) or "nothing resolvable"


def _prune_prefix_chains(sig: _Signals) -> None:
    """Drop a tracked chain that is only a PREFIX of a longer recorded one.

    `_Ctx.consumed` already enforces "only the outermost path expression is a
    real reference", but it works on node identity and so cannot dedupe across
    a resolution boundary: a helper in another module contributes a TRACKED
    directory prefix while the call site contributes a longer, gitignored path
    underneath it (a generated bundle under a `dist/` subdirectory is the
    shape). The tracked prefix is the same reference seen half-resolved, and
    letting it stand turns a gitignored build artifact into a tracked-artifact
    defect. Surfaced when teaching the resolver `parents[N]` made those inner
    slices resolvable for the first time.
    """
    longer = sig.tracked | sig.lfs | sig.untracked | sig.vanished
    sig.tracked = {c for c in sig.tracked
                   if not any(o != c and o.startswith(c + "/") for o in longer)}
    sig.lfs = {c for c in sig.lfs
               if not any(o != c and o.startswith(c + "/") for o in longer)}
    sig.vanished = {c for c in sig.vanished
                    if not any(o != c and o.startswith(c + "/") for o in longer)}


def _classify(sig: _Signals) -> str:
    _prune_prefix_chains(sig)
    # An unconditional skip takes no condition, so there is nothing it could be
    # gating on. It is a disabled test, and it outranks every other signal -
    # including a capability one that happens to be in the same function.
    if sig.unconditional:
        return DEFECT
    # A capability signal wins: `not SIDECAR.is_dir() or sys.platform != "win32"`
    # cannot fire on a healthy checkout no matter what else it touches.
    #
    # This precedence is also what keeps the B4 rule below precise, and it is
    # not incidental. tests/test_vision_server_bind_rm150.py:210 gates on
    # `monitor.html` / `moon_monitor.html`, both of which really were tracked at
    # the repo root and really were deleted - so the historical oracle flags
    # them correctly - but the test's actual premise is a Desktop file on this
    # box, reached over HTTP, and it already carries a `network` signal. Letting
    # capability win first turns the one measured false positive into a pass
    # with no special-casing.
    if sig.capability:
        return CAPABILITY
    if sig.firstparty_import or sig.tracked:
        return DEFECT
    # RM-119 B4: the gate names something git once tracked and no longer does.
    # The thing under test was REMOVED, so the skip is permanent and the
    # assertion behind it has stopped running - a rotted premise, not an absent
    # environment capability.
    if sig.vanished:
        return ROTTED
    # git-LFS. Placed HERE on purpose - last of the defect-bearing rules, not
    # first. A site whose gate also reaches a tracked non-LFS path, a
    # first-party import, or a deleted path has already been convicted above,
    # so the LFS carve-out can only rescue a site whose ONLY unexplained signal
    # is the unfetchable content itself. Hoisting this above `sig.tracked`
    # would let one LFS chain launder every other defect in the same
    # condition, which is precisely how B5 was re-opened in the design that
    # this ordering rejects.
    if sig.lfs:
        return CAPABILITY
    if sig.untracked:
        return CAPABILITY
    return UNRESOLVED


# --------------------------------------------------------------------------- #
# Module model: parents, scopes, bindings, imports
# --------------------------------------------------------------------------- #
_OPTIONAL_IMPORT_EXC = {"ImportError", "ModuleNotFoundError", "Exception",
                        "OSError", "AttributeError"}


class _Model:
    """Parsed module plus the lookup tables condition resolution needs."""

    def __init__(self, path: Path, source: str) -> None:
        self.path = path
        try:
            self.rel = path.resolve().relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            self.rel = path.name
        self.tree = ast.parse(source, filename=str(path))
        self.parent: dict[ast.AST, ast.AST] = {}
        self.assigns: dict[ast.AST, dict[str, list[ast.expr]]] = {}
        self.funcs: dict[ast.AST, dict[str, ast.AST]] = {}
        self.imports: dict[str, str] = {}
        self.optional_names: set[str] = set()
        self._index()

    # -- indexing ----------------------------------------------------------
    def _index(self) -> None:
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
        for scope in [n for n in ast.walk(self.tree) if isinstance(n, _SCOPES)]:
            assigns: dict[str, list[ast.expr]] = {}
            funcs: dict[str, ast.AST] = {}
            body = getattr(scope, "body", [])
            if not isinstance(body, list):
                body = [body]
            self._scan_body(body, assigns, funcs, guarded=False)
            self.assigns[scope] = assigns
            self.funcs[scope] = funcs

    def _scan_body(self, stmts, assigns, funcs, guarded: bool) -> None:
        for st in stmts:
            if isinstance(st, _CALLABLE_SCOPES):
                funcs[st.name] = st
                continue
            if isinstance(st, ast.ClassDef):
                funcs[st.name] = st
                continue
            if isinstance(st, ast.Assign):
                for tgt in st.targets:
                    if isinstance(tgt, ast.Name):
                        assigns.setdefault(tgt.id, []).append(st.value)
                        if guarded:
                            self.optional_names.add(tgt.id)
            elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                if st.value is not None:
                    assigns.setdefault(st.target.id, []).append(st.value)
                    if guarded:
                        self.optional_names.add(st.target.id)
            elif isinstance(st, (ast.Import, ast.ImportFrom)):
                self._record_import(st, guarded)
            elif isinstance(st, ast.Try):
                inner = guarded or _try_swallows_import(st)
                self._scan_body(st.body, assigns, funcs, inner)
                for h in st.handlers:
                    self._scan_body(h.body, assigns, funcs, inner)
                self._scan_body(st.orelse, assigns, funcs, guarded)
                self._scan_body(st.finalbody, assigns, funcs, guarded)
                continue
            for attr in ("body", "orelse", "finalbody"):
                sub = getattr(st, attr, None)
                if isinstance(sub, list) and not isinstance(st, ast.Try):
                    self._scan_body(sub, assigns, funcs, guarded)

    def _record_import(self, st, guarded: bool) -> None:
        if isinstance(st, ast.Import):
            for a in st.names:
                bound = a.asname or a.name.split(".")[0]
                self.imports[bound] = a.name
                if guarded:
                    self.optional_names.add(bound)
        else:
            base = st.module or ""
            for a in st.names:
                bound = a.asname or a.name
                self.imports[bound] = f"{base}.{a.name}" if base else a.name
                if guarded:
                    self.optional_names.add(bound)

    # -- lookups -----------------------------------------------------------
    def scope_of(self, node: ast.AST) -> ast.AST:
        cur = self.parent.get(node)
        while cur is not None and not isinstance(cur, _SCOPES):
            cur = self.parent.get(cur)
        return cur if cur is not None else self.tree

    def scope_chain(self, node: ast.AST) -> list[ast.AST]:
        chain: list[ast.AST] = []
        cur: ast.AST | None = node
        while cur is not None:
            if isinstance(cur, _SCOPES):
                chain.append(cur)
            cur = self.parent.get(cur)
        if self.tree not in chain:
            chain.append(self.tree)
        return chain

    def lookup(self, name: str, scope: ast.AST) -> list[ast.expr]:
        for sc in self.scope_chain(scope):
            hit = self.assigns.get(sc, {}).get(name)
            if hit:
                return hit
        return []

    def lookup_func(self, name: str, scope: ast.AST):
        for sc in self.scope_chain(scope):
            hit = self.funcs.get(sc, {}).get(name)
            if hit is not None:
                return hit
        return None

    def file_segments(self) -> list[str]:
        return self.rel.split("/")


def _try_swallows_import(node: ast.Try) -> bool:
    if not any(isinstance(s, (ast.Import, ast.ImportFrom))
               for s in ast.walk(node)):
        return False
    for h in node.handlers:
        if h.type is None:
            return True
        for name in _exc_names(h.type):
            if name in _OPTIONAL_IMPORT_EXC:
                return True
    return False


def _exc_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Tuple):
        out: list[str] = []
        for e in node.elts:
            out.extend(_exc_names(e))
        return out
    dotted = _dotted(node)
    return [dotted.rsplit(".", 1)[-1]] if dotted else []


_MODEL_CACHE: dict[Path, _Model | None] = {}


def _model_for(path: Path) -> _Model | None:
    key = path.resolve()
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    model: _Model | None = None
    try:
        model = _Model(key, key.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        model = None
    _MODEL_CACHE[key] = model
    return model


def _first_party_file(dotted: str) -> Path | None:
    """Resolve an import target to a file in THIS repo, or None if third party."""
    if not dotted:
        return None
    parts = dotted.split(".")
    while parts:
        cand = _REPO_ROOT.joinpath(*parts).with_suffix(".py")
        if cand.is_file():
            return cand
        pkg = _REPO_ROOT.joinpath(*parts) / "__init__.py"
        if pkg.is_file():
            return pkg
        parts = parts[:-1]
    return None


# --------------------------------------------------------------------------- #
# Symbolic path evaluation
# --------------------------------------------------------------------------- #
_ABS = "\x00abs\x00"
_PASSTHROUGH_CALLS = {"resolve", "absolute", "expanduser", "as_posix",
                      "abspath", "realpath", "normpath", "strip", "rstrip"}
_PATHY_CALLS = {"Path", "PurePath", "PurePosixPath", "PureWindowsPath",
                "fspath"}


def _is_abs_literal(s: str) -> bool:
    return bool(s) and (s.startswith("/")
                        or (len(s) > 1 and s[1] == ":" and s[0].isalpha()))


def _segments(expr: ast.AST, model: _Model, scope: ast.AST,
              seen: frozenset, depth: int) -> list[str] | None:
    """Evaluate a path expression to segments; None marks an opaque segment."""
    if depth > 12:
        return None

    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        raw = expr.value.replace("\\", "/")
        if _is_abs_literal(raw):
            return [_ABS + raw.rstrip("/")]
        return [p for p in raw.split("/") if p not in ("", ".")]

    if isinstance(expr, ast.JoinedStr):
        out: list[str] = []
        for part in expr.values:
            got = _segments(part, model, scope, seen, depth + 1)
            out.extend(got if got is not None else [None])
        return out

    if isinstance(expr, ast.FormattedValue):
        return [None]

    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        left = _segments(expr.left, model, scope, seen, depth + 1)
        right = _segments(expr.right, model, scope, seen, depth + 1)
        return (left if left is not None else [None]) + \
               (right if right is not None else [None])

    if isinstance(expr, ast.Name):
        if expr.id == "__file__":
            return model.file_segments()
        if expr.id in seen:
            return None
        bound = model.lookup(expr.id, scope)
        if len(bound) == 1:
            return _segments(bound[0], model, scope,
                             seen | {expr.id}, depth + 1)
        return None

    if isinstance(expr, ast.Attribute):
        if expr.attr == "parent":
            base = _segments(expr.value, model, scope, seen, depth + 1)
            return base[:-1] if base else None
        if expr.attr in ("parents", "parts", "name", "stem", "suffix"):
            return None
        return _cross_module_segments(expr, model, scope, seen, depth)

    # NOT handled: ast.Subscript, i.e. `<path>.parents[N]`. RM-119 B5 added a
    # symbolic evaluator for it and then removed it as an equivalent mutant:
    # `_record_chain` already recovers the chain from the trailing literal
    # segments, so `parents[1] / "ops" / "rc_config.json"` yields the same
    # `ops/rc_config.json` whether or not the head resolves. The half of that
    # blind spot that was REAL is in `_collect` - an indexed `parents` used to
    # be credited as a tree-shape capability, which swallowed the site whole.

    if isinstance(expr, ast.Call):
        return _call_segments(expr, model, scope, seen, depth)

    return None


def _cross_module_segments(expr: ast.Attribute, model: _Model, scope,
                           seen: frozenset, depth: int) -> list[str] | None:
    if not isinstance(expr.value, ast.Name):
        return None
    target = _resolve_module(expr.value.id, model)
    if target is None:
        return None
    bound = target.assigns.get(target.tree, {}).get(expr.attr)
    if bound and len(bound) == 1:
        return _segments(bound[0], target, target.tree, seen, depth + 1)
    return None


def _resolve_module(alias: str, model: _Model) -> _Model | None:
    dotted = model.imports.get(alias)
    if not dotted:
        return None
    path = _first_party_file(dotted)
    if path is None or path.resolve() == model.path:
        return None
    return _model_for(path)


def _call_segments(expr: ast.Call, model: _Model, scope,
                   seen: frozenset, depth: int) -> list[str] | None:
    fname = _dotted(expr.func)
    tail = fname.rsplit(".", 1)[-1]
    args = expr.args

    if tail in _PATHY_CALLS and args:
        return _segments(args[0], model, scope, seen, depth + 1)
    if tail == "join" and fname.endswith("path.join"):
        out: list[str] = []
        for a in args:
            got = _segments(a, model, scope, seen, depth + 1)
            out.extend(got if got is not None else [None])
        return out
    if tail == "joinpath" and isinstance(expr.func, ast.Attribute):
        out = _segments(expr.func.value, model, scope, seen, depth + 1) or [None]
        for a in args:
            got = _segments(a, model, scope, seen, depth + 1)
            out = out + (got if got is not None else [None])
        return out
    if tail == "dirname" and args:
        base = _segments(args[0], model, scope, seen, depth + 1)
        return base[:-1] if base else None
    if tail == "basename" and args:
        base = _segments(args[0], model, scope, seen, depth + 1)
        return base[-1:] if base else None
    if tail in _PASSTHROUGH_CALLS:
        if isinstance(expr.func, ast.Attribute):
            return _segments(expr.func.value, model, scope, seen, depth + 1)
        if args:
            return _segments(args[0], model, scope, seen, depth + 1)
    if tail in ("sorted", "list", "next", "str"):
        if args:
            return _segments(args[0], model, scope, seen, depth + 1)
    if tail in ("glob", "iglob", "rglob"):
        if fname.endswith("glob.glob") or fname.endswith("glob.iglob"):
            return _segments(args[0], model, scope, seen, depth + 1) if args else None
        if isinstance(expr.func, ast.Attribute):
            base = _segments(expr.func.value, model, scope, seen, depth + 1) or [None]
            pat = _segments(args[0], model, scope, seen, depth + 1) if args else None
            return base + (pat if pat is not None else [None])
    return None


def _record_chain(segs: list[str] | None, sig: _Signals) -> None:
    """Turn evaluated segments into a tracked / untracked verdict."""
    if not segs:
        return
    for s in segs:
        if s and s.startswith(_ABS):
            root = s[len(_ABS):]
            try:
                inside = _REPO_ROOT.resolve().is_relative_to(Path(root))
            except (OSError, ValueError):
                inside = False
            if not inside:
                sig.external_tree = True
                return
    tail: list[str] = []
    for s in reversed(segs):
        if s is None or s.startswith(_ABS):
            break
        tail.append(s)
    if not tail:
        return
    chain = "/".join(reversed(tail))
    if _is_tracked_chain(chain):
        # Tracked, but the content may not be IN the checkout: an LFS-filtered
        # path clones as a pointer stub unless the client smudged it, and no
        # workflow here fetches LFS. That is a capability, not a defect.
        (sig.lfs if _is_lfs_chain(chain) else sig.tracked).add(chain)
    elif _is_vanished_chain(chain):
        sig.vanished.add(chain)
    else:
        sig.untracked.add(chain)


# --------------------------------------------------------------------------- #
# Condition resolution
# --------------------------------------------------------------------------- #
_PLATFORM_DOTTED = {"sys.platform", "os.name", "platform.system",
                    "platform.machine", "platform.release"}
_ENV_CALLS = {"getenv", "environ"}
_NETWORK_TOKENS = {"urlopen", "urlretrieve", "create_connection", "socket",
                   "gethostbyname", "connect", "getaddrinfo"}
_NETWORK_ROOTS = {"requests", "httpx", "urllib", "socket", "http", "aiohttp"}
_PATH_PREDICATES = {"exists", "is_file", "is_dir", "is_symlink", "isfile",
                    "isdir", "islink", "read_text", "read_bytes", "stat",
                    "listdir", "iterdir", "open"}


class _Ctx:
    """Accumulator plus the set of path expressions already accounted for.

    Without the consumed set, walking `ROOT / "data" / "rewind_history.db"`
    records the inner `ROOT / "data"` slice too, and `data` is a tracked
    directory - so a gitignored corpus reads as a tracked artifact. Only the
    outermost path expression is a real reference.
    """

    def __init__(self, broad_handler: bool = False) -> None:
        self.sig = _Signals()
        self.consumed: set[int] = set()
        # True when this skip sits in an `except Exception` / bare `except`.
        # A handler that catches EVERYTHING cannot be read as evidence that a
        # dynamic import failed for want of an optional dependency - it catches
        # a deleted first-party file and a SyntaxError just as happily.
        self.broad_handler = broad_handler

    def take(self, expr: ast.AST | None, model: _Model, scope: ast.AST,
             seen: frozenset) -> None:
        if expr is None or id(expr) in self.consumed:
            return
        for n in ast.walk(expr):
            self.consumed.add(id(n))
        _record_chain(_segments(expr, model, scope, seen, 0), self.sig)


_MAX_RESOLUTION_DEPTH = 8


def _collect(node: ast.AST, model: _Model, scope: ast.AST, ctx: _Ctx,
             seen: frozenset, depth: int) -> None:
    """Walk a condition (or a whole region) accumulating what it depends on.

    `depth` counts RESOLUTION steps only - following a binding, entering a
    helper, crossing a module. Walking into a child node is free, otherwise a
    gate a few statements deep in a helper falls off the end of the budget and
    silently reads as unresolvable.
    """
    if node is None:
        return
    sig = ctx.sig

    if isinstance(node, ast.Attribute):
        dotted = _dotted(node)
        if dotted in _PLATFORM_DOTTED:
            sig.platform = True
        if dotted.split(".")[-1] == "environ" or dotted.startswith("environ"):
            sig.env = True
        # `.parents` / `.parts` asks about the SHAPE of the checkout (am I in a
        # worktree, am I under a vendored copy of this tree) and that is a real
        # capability question. `.parents[3]` does not: it is a path expression
        # with an index, and crediting it as tree-shape is what made an
        # otherwise-identical B5 invisible when written in the idiomatic form.
        # Only the non-indexed use keeps the signal.
        if (node.attr in ("parents", "parts")
                and not _is_constant_indexed_parents(node, model)
                and _derives_from_file(node.value, model, scope, seen, 0)):
            sig.tree_shape = True
        if node.attr in _PATH_PREDICATES:
            ctx.take(node.value, model, scope, seen)
        _cross_module_attr(node, model, ctx, seen, depth)

    elif isinstance(node, ast.Call):
        _collect_call(node, model, scope, ctx, seen, depth)

    elif isinstance(node, ast.Name):
        # Deliberately NOT narrowed to ast.Load. A Store-context optional name
        # looks like it should be excluded, and RM-119 B5 shipped that
        # narrowing for a day, but it is an EQUIVALENT MUTANT: `optional_names`
        # is only populated by `_try_swallows_import`, which requires a literal
        # import STATEMENT in the try, and in every such try the same name is
        # also read in Load context somewhere in the region. No input
        # distinguishes the two versions, so the narrowing was removed rather
        # than left in the tree unpinned by any test.
        if node.id in model.optional_names:
            sig.optional_import = True
        if node.id not in seen and depth < _MAX_RESOLUTION_DEPTH:
            for bound in model.lookup(node.id, scope):
                _collect(bound, model, scope, ctx, seen | {node.id}, depth + 1)

    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        _collect_import(node, sig, model)
        return

    elif isinstance(node, ast.Try):
        if _try_swallows_import(node):
            for st in node.body:
                if isinstance(st, (ast.Import, ast.ImportFrom)):
                    _collect_import(st, sig)

    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        ctx.take(node, model, scope, seen)

    for child in ast.iter_child_nodes(node):
        _collect(child, model, scope, ctx, seen, depth)


def _is_constant_indexed_parents(node: ast.Attribute, model: _Model) -> bool:
    """True for `<path>.parents[<int>]` - resolvable, so not a shape question."""
    if node.attr != "parents":
        return False
    parent = model.parent.get(node)
    if not isinstance(parent, ast.Subscript) or parent.value is not node:
        return False
    idx = parent.slice
    return (isinstance(idx, ast.Constant) and isinstance(idx.value, int)
            and not isinstance(idx.value, bool) and idx.value >= 0)


def _derives_from_file(expr: ast.AST | None, model: _Model, scope: ast.AST,
                       seen: frozenset, depth: int) -> bool:
    """True when the expression traces back to this module's own __file__."""
    if expr is None or depth > _MAX_RESOLUTION_DEPTH:
        return False
    for n in ast.walk(expr):
        if not isinstance(n, ast.Name):
            continue
        if n.id == "__file__":
            return True
        if n.id in seen:
            continue
        for bound in model.lookup(n.id, scope):
            if _derives_from_file(bound, model, scope, seen | {n.id},
                                  depth + 1):
                return True
    return False


def _collect_import(node: ast.AST, sig: _Signals,
                    model: _Model | None = None) -> None:
    if isinstance(node, ast.Import):
        targets = [a.name for a in node.names]
        bound = [a.asname or a.name.split(".")[0] for a in node.names]
    else:
        base = node.module or ""
        targets = [f"{base}.{a.name}" if base else a.name for a in node.names]
        bound = [a.asname or a.name for a in node.names]
    # A third-party import is evidence of an OPTIONAL dependency only when its
    # failure was actually swallowed. A plain `import importlib` sitting in the
    # same function as the skip is not: the widen-to-function pass would
    # otherwise hand every skip in a module that imports anything from the
    # stdlib a free capability signal, which is how the RM-119 B5 site in
    # tests/test_ports.py read as clean.
    swallowed = model is None or any(b in model.optional_names for b in bound)
    for dotted in targets:
        if _first_party_file(dotted) is not None:
            sig.firstparty_import.add(dotted)
        elif swallowed:
            sig.optional_import = True


def _cross_module_attr(node: ast.Attribute, model: _Model, ctx: _Ctx,
                       seen: frozenset, depth: int) -> None:
    if not isinstance(node.value, ast.Name) or depth >= _MAX_RESOLUTION_DEPTH:
        return
    target = _resolve_module(node.value.id, model)
    if target is None:
        return
    _enter_symbol(target, node.attr, model, ctx, seen, depth)


def _enter_symbol(target: _Model, symbol: str, model: _Model, ctx: _Ctx,
                  seen: frozenset, depth: int) -> None:
    key = f"{target.rel}::{symbol}"
    if key in seen:
        return
    if symbol in target.optional_names:
        ctx.sig.optional_import = True
    fn = target.funcs.get(target.tree, {}).get(symbol)
    if fn is not None:
        _collect(fn, target, fn, ctx, seen | {key}, depth + 1)
        return
    for bound in target.assigns.get(target.tree, {}).get(symbol, []):
        _collect(bound, target, target.tree, ctx, seen | {key}, depth + 1)


def _positional_params(fn: ast.AST) -> list[str]:
    args = getattr(fn, "args", None)
    if args is None:
        return []
    return [a.arg for a in list(args.posonlyargs) + list(args.args)]


def _enter_local_function(fn: ast.AST, call: ast.Call, model: _Model,
                          ctx: _Ctx, seen: frozenset, depth: int) -> None:
    """Descend into a helper with its ARGUMENTS bound to its parameters.

    `if not _lane_counts(LW_ROOT):` says nothing until LW_ROOT reaches the
    parameter the helper joins its paths onto.
    """
    key = f"{model.rel}::{getattr(fn, 'name', '?')}"
    if key in seen or depth >= _MAX_RESOLUTION_DEPTH:
        return
    saved = model.assigns.get(fn, {})
    overlay = dict(saved)
    for param, arg in zip(_positional_params(fn), call.args):
        overlay.setdefault(param, [arg])
    model.assigns[fn] = overlay
    try:
        _collect(fn, model, fn, ctx, seen | {key}, depth + 1)
    finally:
        model.assigns[fn] = saved


def _collect_call(node: ast.Call, model: _Model, scope: ast.AST,
                  ctx: _Ctx, seen: frozenset, depth: int) -> None:
    sig = ctx.sig
    fname = _dotted(node.func)
    tail = fname.rsplit(".", 1)[-1]
    root = fname.split(".")[0]

    if fname in ("shutil.which", "which", "distutils.spawn.find_executable"):
        sig.binary = True
    if tail in _ENV_CALLS or fname.startswith("os.environ"):
        sig.env = True
    if tail in ("find_spec", "import_module", "importorskip", "util.find_spec",
                "__import__"):
        # A DYNAMIC import is only a capability question when the thing being
        # imported is somebody else's. `importlib.import_module("mc.server")`
        # names a TRACKED file, so swallowing its failure into a skip is the
        # same always-pass guard as gating on that file's existence - which is
        # what tests/test_ports.py did until RM-119 B5. Resolve the literal
        # before deciding; a non-literal target stays a capability signal
        # because nothing here can say what it will hold at run time.
        target = node.args[0] if node.args else None
        if (isinstance(target, ast.Constant)
                and isinstance(target.value, str)
                and _first_party_file(target.value) is not None):
            sig.firstparty_import.add(target.value)
        elif tail == "importorskip" or not ctx.broad_handler:
            # `importorskip` is itself a skip primitive - it skips on absence
            # and on nothing else - so it stays honest evidence wherever it is
            # written. The others RETURN a module and leave the caller to
            # decide what a failure meant, which is where the handler width
            # starts to matter.
            sig.optional_import = True
        # else: an unreadable target caught by a catch-everything handler is
        # not evidence of anything, so it resolves to nothing and the site
        # lands in UNRESOLVED - which the guard treats as a defect until a
        # human narrows the handler. tests/test_ports.py was exactly this
        # (RM-119 B5) and read as a clean capability skip for months.
    if tail in _NETWORK_TOKENS or root in _NETWORK_ROOTS:
        sig.network = True
    if tail in _PATH_PREDICATES and isinstance(node.func, ast.Attribute):
        ctx.take(node.func.value, model, scope, seen)
    if tail in _PATH_PREDICATES and node.args and fname.startswith(
            ("os.path.", "path.", "os.")):
        ctx.take(node.args[0], model, scope, seen)
    if tail in ("glob", "iglob", "rglob"):
        ctx.take(node, model, scope, seen)

    # A gate is routinely a helper call; open the helper and read it.
    if isinstance(node.func, ast.Name):
        local = model.lookup_func(node.func.id, scope)
        if local is not None:
            _enter_local_function(local, node, model, ctx, seen, depth)
        else:
            imported = _resolve_module(node.func.id, model)
            if imported is not None:
                _enter_symbol(imported, node.func.id, model, ctx, seen, depth)
    elif isinstance(node.func, ast.Attribute):
        _cross_module_attr(node.func, model, ctx, seen, depth)


# --------------------------------------------------------------------------- #
# Site discovery
# --------------------------------------------------------------------------- #
def _skip_sites(model: _Model) -> list[_Site]:
    sites: list[_Site] = []
    seen_calls: set[int] = set()
    for node in ast.walk(model.tree):
        # Unconditional skips first, and NOT restricted to ast.Call: a bare
        # `@pytest.mark.skip` decorator is an ast.Attribute with no call at all.
        if isinstance(node, ast.Attribute):
            dotted = _canonical_call(_dotted(node), model)
            if dotted in _UNCONDITIONAL_SKIPS:
                parent = model.parent.get(node)
                # `pytest.mark.skip(...)` - record the Call, not the Attribute,
                # so the site is reported once at the call's line.
                target = parent if (isinstance(parent, ast.Call)
                                    and parent.func is node) else node
                if id(target) not in seen_calls:
                    seen_calls.add(id(target))
                    sites.append(_Site(model.rel, target.lineno,
                                       "unconditional " + dotted, None, target))
            continue
        if isinstance(node, ast.Raise):
            exc = node.exc
            target = exc.func if isinstance(exc, ast.Call) else exc
            name = _dotted(target).rsplit(".", 1)[-1] if target is not None else ""
            if name.endswith(_SKIP_EXC_SUFFIXES):
                sites.append(_Site(model.rel, node.lineno, "raise SkipTest",
                                   None, node))
            continue
        if not isinstance(node, ast.Call):
            continue
        fname = _canonical_call(_dotted(node.func), model)
        tail = fname.rsplit(".", 1)[-1]
        if fname in _DECORATOR_SKIPS or tail in ("skipif", "skipIf", "skipUnless"):
            cond = node.args[0] if node.args else _kw(node, "condition")
            sites.append(_Site(model.rel, node.lineno, fname, cond, node))
        elif tail == _IMPORTORSKIP:
            cond = node.args[0] if node.args else None
            sites.append(_Site(model.rel, node.lineno, "importorskip",
                               cond, node))
        elif fname in _BODY_SKIPS or tail in _BODY_SKIP_TAILS:
            sites.append(_Site(model.rel, node.lineno, fname or tail,
                               None, node))
    sites.sort(key=lambda s: (s.rel, s.line))
    return sites


def _canonical_call(fname: str, model: _Model) -> str:
    """Rewrite an aliased module head back to its real name.

    ``pytest.skip`` is matched on the FULL dotted chain rather than the tail,
    because a bare ``.skip`` tail would collect unrelated calls. That makes
    ``import pytest as _p`` + ``_p.skip(...)`` invisible to the scanner - not
    misclassified, absent - which is the one evasion a guard must not have.
    """
    head, sep, rest = fname.partition(".")
    origin = model.imports.get(head)
    if origin and sep:
        return origin + "." + rest
    return fname


def _kw(node: ast.Call, name: str):
    for k in node.keywords:
        if k.arg == name:
            return k.value
    return None


def _context_conditions(model: _Model, node: ast.AST) -> list[ast.AST]:
    """The nearest guards around a bare skip: enclosing if / while / except."""
    out: list[ast.AST] = []
    cur: ast.AST | None = node
    parent = model.parent.get(cur)
    while parent is not None and not isinstance(parent, _SCOPES):
        if isinstance(parent, (ast.If, ast.While)):
            out.append(parent.test)
        elif isinstance(parent, ast.ExceptHandler):
            if parent.type is not None:
                out.append(parent.type)
            grand = model.parent.get(parent)
            if isinstance(grand, ast.Try):
                out.extend(grand.body)
        elif isinstance(parent, ast.Assert):
            out.append(parent.test)
        cur, parent = parent, model.parent.get(parent)
    return out


_BROAD_EXC = {"Exception", "BaseException"}


def _in_catch_everything_handler(model: _Model, node: ast.AST) -> bool:
    """True when the skip sits inside a bare `except:` or `except Exception:`."""
    cur: ast.AST | None = node
    parent = model.parent.get(cur)
    while parent is not None and not isinstance(parent, _SCOPES):
        if isinstance(parent, ast.ExceptHandler):
            if parent.type is None:
                return True
            if any(n in _BROAD_EXC for n in _exc_names(parent.type)):
                return True
        cur, parent = parent, model.parent.get(parent)
    return False


def _signals_for(model: _Model, site: _Site) -> _Signals:
    scope = model.scope_of(site.node)
    broad = _in_catch_everything_handler(model, site.node)

    if site.kind.startswith("unconditional "):
        sig = _Signals()
        sig.unconditional = True
        return sig

    if site.kind == "importorskip":
        sig = _Signals()
        cond = site.condition
        if isinstance(cond, ast.Constant) and isinstance(cond.value, str):
            if _first_party_file(cond.value) is not None:
                sig.firstparty_import.add(cond.value)
            else:
                sig.optional_import = True
        else:
            sig.optional_import = True
        return sig

    if site.condition is not None:
        ctx = _Ctx(broad)
        _collect(site.condition, model, scope, ctx, frozenset(), 0)
        return ctx.sig

    # Bare skip: nearest guards first, then widen to the enclosing function.
    near = _Ctx(broad)
    for cond in _context_conditions(model, site.node):
        _collect(cond, model, scope, near, frozenset(), 0)
    if _classify(near.sig) != UNRESOLVED:
        return near.sig
    if isinstance(scope, _CALLABLE_SCOPES):
        wide = _Ctx(broad)
        _collect(scope, model, scope, wide, frozenset(), 0)
        near.sig.merge(wide.sig)
    return near.sig


# --------------------------------------------------------------------------- #
# The scan
# --------------------------------------------------------------------------- #
def _iter_modules() -> list[Path]:
    out: list[Path] = []
    for tree in _TEST_TREES:
        out.extend(sorted((_REPO_ROOT / tree).rglob("*.py")))
    return out


@dataclass
class _Finding:
    site: _Site
    verdict: str
    evidence: str
    gates_on: frozenset


def scan_source(rel: str, source: str) -> list[_Finding]:
    """Classify every skip construct in one module's source."""
    model = _Model(_REPO_ROOT / rel, source)
    model.rel = rel
    findings: list[_Finding] = []
    for site in _skip_sites(model):
        sig = _signals_for(model, site)
        findings.append(_Finding(
            site, _classify(sig), sig.evidence(),
            frozenset(sig.tracked | sig.firstparty_import | sig.vanished),
        ))
    return findings


def scan_tree() -> list[_Finding]:
    findings: list[_Finding] = []
    for path in _iter_modules():
        rel = path.resolve().relative_to(_REPO_ROOT).as_posix()
        findings.extend(
            scan_source(rel, path.read_text(encoding="utf-8", errors="replace"))
        )
    return findings


# --------------------------------------------------------------------------- #
# Reviewed exemptions
# --------------------------------------------------------------------------- #
# Each entry is a reviewed exemption: the module, the EXACT tracked artifacts
# its skip is excused for, and why. Keyed by module rather than by line so a
# moved site stays covered, but pinned to the artifact set so a NEW skip in the
# same module - or the same skip re-aimed at a different tracked file - still
# fails. The three tests below assert every entry still exists on disk, still
# flags, and is still excusing exactly what it claims, so neither a deleted
# file nor a fixed one can rot an exemption into a silent pass.
_ALLOWLIST: dict[str, tuple[frozenset, str]] = {
    # NARROWED 2026-08-06 (RM-119 B5): was
    # {"data/daemon_slayer", "data/daemon_slayer/current.txt"}. The bare
    # directory was the same reference seen half-resolved and is now pruned as
    # a prefix, so the exemption covers ONE artifact instead of two. Strictly
    # stricter - the entry did not grow, and no new entry was added.
    "tests/test_ds_ability_data_status_rm95.py": (
        frozenset({"data/daemon_slayer/current.txt"}),
        "FUTURE row in docs/SKIPIF_AUDIT_2026-07-27.md - the skip pins an RM-95 "
        "finding to patch 16.14.1 and is decidable against tracked current.txt "
        "today, but converting it turns CI red on the next patch bump. Needs a "
        "re-pin policy, not a mechanical flip.",
    ),
}


def _excused(finding: _Finding) -> bool:
    entry = _ALLOWLIST.get(finding.site.rel)
    if entry is None or not finding.gates_on:
        return False
    return finding.gates_on <= entry[0]


# --------------------------------------------------------------------------- #
# RM-119 class B4: how the rotted-premise rule was arrived at
# --------------------------------------------------------------------------- #
# B4 is the class where the skip fires because the DATA contradicts the test's
# own premise - the tree does not hold what the test assumes - so the assertion
# never runs and the premise rots behind a green suite.
#
# The first attempt at this section was a REFUSAL: a comment arguing no general
# B4 guard was possible, on two measurements. Both measurements were true and
# the conclusion was wrong, which is worth recording because the shape of the
# error is a recurring one - one failed formulation presented as proof that
# none exists.
#
#   * The FILESYSTEM formulation ("flag a skip gated on a path absent from this
#     checkout") really is unusable: it flags 24 sites of which 23 are the
#     reviewed legitimate class - `data/rewind_history.db` alone is nine - and
#     worse, its verdict depends on the tree it runs in, since that DB is
#     1.87 GB in the main tree and absent in every worktree. A guard whose
#     colour changes with the checkout cannot gate anything.
#   * The mistake was concluding from that to "no rule exists". The failing
#     ingredient was the ORACLE, not the idea. Every one of those false
#     positives is UNTRACKED machine-local state, and asking git instead of the
#     disk separates them for free: machine-local state was never in history by
#     construction, while "was tracked and is gone" is the definition of a
#     rotted premise. That is `_git_vanished` above, and it needs no filesystem
#     read at all, so it is identical in every checkout of a commit.
#
# MEASURED on all five test trees, 2026-08-06, with the pre-conversion shapes
# restored so the known instances were present to be found:
#   * 34 untracked-gated chains examined, 11 flagged across 10 sites.
#   * TRUE positives 9/9 - `pengu` (root-level, reached only because renames
#     are counted), the seven `_archive/2026-05-01-audit/**` targets, and
#     `_archive/2026-06-20-rc2-p73`, which two hand passes had classified as
#     legitimate machine-local state and git history contradicted.
#   * FALSE positives 1 site before precedence, 0 after: the
#     `monitor.html` / `moon_monitor.html` pair in test_vision_server_bind_rm150
#     really were tracked and deleted, but the test's premise is a Desktop file
#     reached over HTTP, and its `network` signal already wins in `_classify`.
#   * Not visible to this rule by construction, and correctly so: the two
#     VALUE-gated B4 sites (a pinned patch string, a registry's contents) gate
#     on data CONTENT, not on a path. Recall against path-gated B4 is 9/9;
#     against all 11 B4 control points it is 9/11.
#
# The census this rule was measured against: 11 B4 control points carrying 16
# live skip events, across 130 skip sites in the five trees at 8338ad79. An
# earlier headline of "11 sites / 13 events" did not decompose - it counted the
# CONVERTED subset as if it were the whole class, and it predated this rule
# finding `_archive/2026-06-20-rc2-p73`.
# Cost: one `git log` at import, 0.67s.
#
# Precision against the naive rule it replaces: 9/9 versus 1/24.


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def _discovered_test_trees() -> set[str]:
    """Every directory in the repo that actually holds pytest test modules.

    Derived from the FILESYSTEM, never from `_TEST_TREES`, so it can contradict
    the tuple. Directories are rolled up to their shallowest test-bearing
    ancestor: `tests/snapshot_panels` is part of the `tests` tree, not a tree of
    its own. Vendored / mirrored / archived trees are excluded on the same
    grounds pytest.ini excludes them from collection.
    """
    # "moon_sync_inbox" added 2026-09-07. Sibling repos deliver verbatim source
    # payloads into that gitignored directory, and those payloads carry THEIR
    # test modules. Those are INBOUND MAIL, not RC's test surface: RC does not
    # run them, does not own them, and adding them to _TEST_TREES would assert
    # RC's skip-hygiene rules over another project's code. The guard was right
    # to flag them - a directory holding test_*.py really was outside the scan -
    # and the correct answer is that the inbox is not part of the repo's own
    # tree set, not that the tuple should grow. Same grounds as any vendored
    # copy: it is somebody else's code sitting inside this checkout.
    skip_parts = {".git", ".claude", "__pycache__", "node_modules",
                  "python-embed", "_archive", "docs", ".venv", "venv", "build",
                  "dist", "moon_sync_inbox"}
    holders: set[str] = set()
    for path in _REPO_ROOT.rglob("test_*.py"):
        rel = path.resolve().relative_to(_REPO_ROOT).as_posix()
        parts = rel.split("/")
        if any(p in skip_parts for p in parts):
            continue
        holders.add("/".join(parts[:-1]) or ".")
    rolled: set[str] = set()
    for d in holders:
        segs = d.split("/")
        shallowest = d
        for end in range(1, len(segs)):
            anc = "/".join(segs[:end])
            if anc in holders:
                shallowest = anc
                break
        rolled.add(shallowest)
    return rolled


def test_universe_covers_every_test_bearing_tree_in_the_repo():
    """`_TEST_TREES` is checked against the DISK, not against itself.

    The predecessor of this test looped over `_TEST_TREES` and asserted each
    entry collected something - which is a tautology: deleting a tree from the
    tuple deletes its own assertion too, so reverting the RM-119 B5 widening
    from five trees back to two stayed green. Caught by the verifier's mutation
    pass on 2026-08-06. The set below is discovered by globbing the repo, so a
    tree dropped from the tuple is still found on disk and still fails here.
    """
    discovered = _discovered_test_trees()
    missing = sorted(discovered - set(_TEST_TREES))
    assert not missing, (
        "these directories hold pytest test modules but are OUTSIDE the skip "
        "scan, so a skip gated on a tracked artifact could be added there and "
        f"nothing would notice: {missing} - add them to _TEST_TREES"
    )
    stale = sorted(t for t in _TEST_TREES if not (_REPO_ROOT / t).is_dir())
    assert not stale, f"_TEST_TREES names directories that do not exist: {stale}"


def test_universe_is_globbed_not_listed():
    """The producing side is the glob; a hand list is how a guard goes blind."""
    mods = _iter_modules()
    assert len(mods) > 400, f"only {len(mods)} test modules found - glob broke"
    rels = {m.resolve().relative_to(_REPO_ROOT).as_posix() for m in mods}
    assert "tests/test_skip_condition_hygiene.py" in rels
    for tree in _TEST_TREES:
        assert any(r.startswith(tree + "/") for r in rels), (
            f"no test module collected from {tree} - the glob stopped reaching it"
        )


def test_tracked_index_resolves_known_paths():
    """Trackedness comes from git, and the suffix index must preserve it."""
    assert _is_tracked_chain("data/daemon_slayer/current.txt")
    assert _is_tracked_chain("web/legacy_index.html")
    assert _is_tracked_chain("ops/rc_config.json")
    assert not _is_tracked_chain("data/rewind_history.db")
    assert not _is_tracked_chain("dist/daemon_slayer_bundle.json")
    assert not _is_tracked_chain("_archive/2026-05-01-audit/tft/comp_control.py")


def test_lfs_oracle_comes_from_git_and_covers_only_lfs_paths():
    """The LFS set is git's answer, and it is a strict subset of the tracked set."""
    assert _LFS_TRACKED, (
        "git check-attr reported no LFS-filtered tracked path - either the "
        "attribute was removed or the batched --stdin parse broke; either way "
        "the carve-out below is silently doing nothing"
    )
    assert _LFS_TRACKED < _TRACKED, "the LFS set must be a proper subset of tracked"
    assert _NON_LFS_TRACKED == _TRACKED - _LFS_TRACKED
    # Spot-check both directions against files this repo will not lose.
    assert "ops/rc_config.json" in _NON_LFS_TRACKED
    assert "data/daemon_slayer/current.txt" in _NON_LFS_TRACKED
    assert all(p.endswith(".json") for p in _LFS_TRACKED)


def test_lfs_chain_rule_is_all_not_any():
    """A chain is a capability gate only when EVERY path it names is LFS."""
    # Fully covered: file, patch dir, and the tables root.
    assert _is_lfs_chain(
        "data/daemon_slayer/laning_scenarios/16.13.1/laning_scenarios_aram.json")
    assert _is_lfs_chain("data/daemon_slayer/laning_scenarios")
    assert _is_lfs_chain("laning_scenarios_aram.json")
    # Partially covered: these all reach at least one ordinary tracked file, so
    # the carve-out must NOT rescue them. `data` is the one that matters - if
    # the rule were ANY, every B5 defect gating on a broad data path would pass.
    assert not _is_lfs_chain("data")
    assert not _is_lfs_chain("data/daemon_slayer")
    # Not tracked at all, and ordinary tracked paths.
    assert not _is_lfs_chain("data/rewind_history.db")
    assert not _is_lfs_chain("ops/rc_config.json")
    assert not _is_lfs_chain("")


def test_lfs_chains_do_not_leak_into_the_tracked_defect_signal():
    """`_record_chain` routes an LFS chain away from `sig.tracked`, not into it.

    Asserted on the signal rather than on the verdict because the verdict is
    reachable two ways: a bug that marked the site CAPABILITY for some other
    reason would look identical from outside.
    """
    src = _CAPABILITY_CONTROLS["tracked_artifact_behind_a_git_lfs_filter"]
    model = _Model(_REPO_ROOT / "tests" / "test_mutant.py", src)
    model.rel = "tests/test_mutant.py"
    sites = _skip_sites(model)
    assert len(sites) == 1
    sig = _signals_for(model, sites[0])
    _prune_prefix_chains(sig)
    assert sig.lfs and not sig.tracked, (
        f"expected the LFS path in sig.lfs only, got tracked={sig.tracked} "
        f"lfs={sig.lfs}"
    )
    assert not sig.capability, (
        "the fixture must be rescued by the LFS rule alone - if it already "
        "carries an unrelated capability signal it proves nothing"
    )


def test_every_skip_gates_on_an_environment_capability():
    """The guard itself: no skip may fire on something a checkout always has."""
    bad = [
        f"  {f.site.label} -> {f.verdict}: {f.evidence}"
        for f in scan_tree()
        if f.verdict != CAPABILITY and not _excused(f)
    ]
    assert not bad, (
        "skip constructs that do not gate on an absent environment "
        "capability - a skip here is an always-passing guard, and the thing "
        "under test being absent must FAIL instead (see "
        "docs/SKIPIF_AUDIT_2026-07-27.md):\n" + "\n".join(bad)
    )


def test_allowlisted_modules_still_exist():
    """A deleted file must not rot an exemption into a silent pass."""
    missing = [rel for rel in _ALLOWLIST if not (_REPO_ROOT / rel).is_file()]
    assert not missing, (
        f"allowlisted modules no longer on disk: {missing} - delete the "
        "_ALLOWLIST entries with them"
    )


def test_allowlisted_modules_still_flag():
    """An exemption that no longer excuses anything is dead weight."""
    stale = []
    for rel in _ALLOWLIST:
        src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        if all(f.verdict == CAPABILITY for f in scan_source(rel, src)):
            stale.append(rel)
    assert not stale, (
        f"_ALLOWLIST entries that no longer flag: {stale} - the underlying "
        "skip was fixed or removed, so drop the exemption"
    )


def test_allowlist_excuses_exactly_what_it_claims():
    """The pinned artifact set must still be the one being excused."""
    drifted = []
    for rel, (claimed, _) in _ALLOWLIST.items():
        src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        actual: set = set()
        for f in scan_source(rel, src):
            if f.verdict != CAPABILITY:
                actual |= set(f.gates_on)
        if actual != set(claimed):
            drifted.append(f"{rel}: claims {sorted(claimed)}, flags "
                           f"{sorted(actual)}")
    assert not drifted, (
        "allowlist entries no longer describe the skip they exempt - re-review "
        "each before re-pinning:\n" + "\n".join(drifted)
    )


# --- mutation probes: the teeth, pinned in-suite ---------------------------- #
_DEFECT_MUTATIONS = {
    "mark_skipif_on_tracked_path": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
@pytest.mark.skipif(not (REPO / "data" / "daemon_slayer" / "current.txt").exists(),
                    reason="no patch pointer")
def test_thing():
    assert True
''',
    "bare_skip_on_tracked_path": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "ops" / "rc_config.json"
    if not p.is_file():
        pytest.skip("config absent")
    assert p.read_text()
''',
    "aliased_pytest_bare_skip_on_tracked_path": '''
import pytest as _p
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "ops" / "rc_config.json"
    if not p.is_file():
        _p.skip("config absent")
    assert p.read_text()
''',
    "unittest_skipunless_on_tracked_path": '''
import os
import unittest
class T(unittest.TestCase):
    @unittest.skipUnless(os.path.exists("web/legacy_index.html"), "absent")
    def test_thing(self):
        self.assertTrue(True)
''',
    "helper_gate_reading_a_tracked_file": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def _patch():
    return (REPO / "data" / "daemon_slayer" / "current.txt").read_text().strip()
def test_thing():
    if _patch() != "16.14.1":
        pytest.skip("pinned")
    assert True
''',
    # RM-119 B5, the tests/test_ports.py shape: a first-party module pulled in
    # dynamically and its failure swallowed into a skip. Every module named
    # this way is TRACKED, so the skip can only fire on a broken checkout.
    "dynamic_first_party_import_swallowed": '''
import importlib
import pytest
def test_thing():
    try:
        mod = importlib.import_module("mc.server")
    except Exception:
        pytest.skip("mc.server not importable here")
    assert mod.PORT
''',
    # The verbatim pre-fix tests/test_ports.py shape: a runtime-named dynamic
    # import whose EVERY failure - deleted tracked file, SyntaxError, our own
    # ImportError - is swallowed by `except Exception` and called a missing
    # optional dep. Statically the target is unreadable, so the handler width
    # is the whole signal, and a catch-everything handler is no signal at all.
    # Structure matters here and the first version of this fixture got it
    # wrong: it hoisted `import importlib` to MODULE level, while the real
    # defect had it INSIDE the helper. That one difference made the fixture
    # survive a mutation the real file did not, so it was shaped to pass rather
    # than shaped to the bug (verifier, 2026-08-06). Byte-for-byte the pre-fix
    # tests/test_ports.py `_live` now, import placement included.
    "runtime_named_import_swallowed_by_bare_except": '''
import unittest
class T(unittest.TestCase):
    def _live(self, module_path, attr):
        import importlib
        try:
            mod = importlib.import_module(module_path)
        except Exception as exc:
            self.skipTest(f"{module_path} not importable here: {exc}")
        self.assertTrue(hasattr(mod, attr))
        return getattr(mod, attr)
    def test_thing(self):
        self.assertEqual(8888, self._live("dashboard.server", "PORT"))
''',
    # The same B5 in the idiomatic path spelling. `.parent.parent` was caught
    # and `.parents[1]` was not, in a resolver that treated `parents` as an
    # unanswerable tree-shape question; nine skip-bearing modules already write
    # it this way.
    "skip_on_a_tracked_path_via_parents_index": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
def test_thing():
    p = REPO / "ops" / "rc_config.json"
    if not p.is_file():
        pytest.skip("config absent")
    assert p.read_text()
''',
    "mark_skipif_on_a_tracked_path_via_parents_index": '''
import pytest
from pathlib import Path
_HERE = Path(__file__).resolve()
@pytest.mark.skipif(not (_HERE.parents[1] / "web" / "legacy_index.html").exists(),
                    reason="page absent")
def test_thing():
    assert True
''',
    "dunder_import_of_a_first_party_module": '''
import pytest
def test_thing():
    try:
        mod = __import__("core.ports")
    except ImportError:
        pytest.skip("ports registry not importable")
    assert mod
''',
    "importorskip_on_a_first_party_module": '''
import pytest
mod = pytest.importorskip("core.build_order")
def test_thing():
    assert mod
''',
    "skiptest_raise_on_tracked_path": '''
import unittest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
class T(unittest.TestCase):
    def test_thing(self):
        p = REPO / "data" / "daemon_slayer" / "current.txt"
        if not p.exists():
            raise unittest.SkipTest("no pointer")
        self.assertTrue(p.read_text())
''',
    # --- UNCONDITIONAL skips. The scanner was blind to all four until
    # 2026-08-06, and blindness is worse than misclassification: an invisible
    # site is not weighed at all. The last of these is the exact spelling of
    # the original pengu B4 defect, and a verifier proved a re-injected copy
    # of it left the guard GREEN.
    "bare_unconditional_mark_skip_decorator": '''
import pytest
@pytest.mark.skip
def test_thing():
    assert True
''',
    "unconditional_mark_skip_with_reason": '''
import pytest
@pytest.mark.skip(reason="flaky, will fix later")
def test_thing():
    assert True
''',
    "unconditional_unittest_skip": '''
import unittest
class T(unittest.TestCase):
    @unittest.skip("disabled")
    def test_thing(self):
        self.assertTrue(True)
''',
    "module_level_pytestmark_unconditional_skip": '''
import pytest
pytestmark = pytest.mark.skip(reason="whole module parked")
def test_thing():
    assert True
''',
    # --- RM-119 B4 proper: the gate names something git tracked once and no
    # longer does. `pengu/` is the real instance - renamed into
    # docs/_archive/2026-07-07-pengu-stub/ at f08ade78 - and it is written here
    # in the module-level form the original defect used.
    "skip_gated_on_a_path_git_used_to_track": '''
import pytest
from pathlib import Path
PENGU = Path(__file__).resolve().parent.parent / "pengu"
pytestmark = pytest.mark.skipif(not PENGU.is_dir(), reason="stub relocated")
def test_thing():
    assert (PENGU / "index.js").is_file()
''',
    "bare_skip_gated_on_a_removed_archive_path": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "_archive" / "2026-05-01-audit" / "ui" / "base.py"
    if not p.is_file():
        pytest.skip("archived file absent on this checkout")
    assert p.read_bytes()
''',
    # --- the git-LFS carve-out, from the DEFECT side. Both of these reach an
    # LFS path and neither may be rescued by it, because the LFS rule is
    # "every tracked path this chain names is LFS", not "any".
    #
    # A directory one level above the LFS tables. `data/daemon_slayer` holds
    # `current.txt` and the whole DDragon mirror, none of it LFS, so the gate
    # can only fire on a broken checkout and stays B5.
    "skip_on_a_dir_holding_both_lfs_and_ordinary_tracked_files": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    d = REPO / "data" / "daemon_slayer"
    if not d.is_dir():
        pytest.skip("engine data tree absent")
    assert any(d.iterdir())
''',
    # Laundering: one real LFS gate sitting in the same condition as an
    # ordinary tracked gate. If the LFS signal were allowed to outrank
    # `sig.tracked` in `_classify`, this would read CAPABILITY and every B5
    # defect could be hidden by adding an LFS path to its condition.
    "lfs_path_used_to_launder_a_tracked_non_lfs_path": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    table = (REPO / "data" / "daemon_slayer" / "laning_scenarios"
             / "16.13.1" / "laning_scenarios_aram.json")
    pointer = REPO / "data" / "daemon_slayer" / "current.txt"
    if not table.is_file() or not pointer.is_file():
        pytest.skip("inputs absent on this checkout")
    assert table.stat().st_size and pointer.read_text()
''',
}

_CAPABILITY_CONTROLS = {
    "platform": '''
import sys
import pytest
@pytest.mark.skipif(sys.platform != "win32", reason="win32 only")
def test_thing():
    assert True
''',
    "external_binary": '''
import shutil
import pytest
NODE = shutil.which("node")
def test_thing():
    if not NODE:
        pytest.skip("node not on PATH")
    assert NODE
''',
    "gitignored_artifact": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    db = REPO / "data" / "rewind_history.db"
    if not db.is_file():
        pytest.skip("machine-local corpus absent")
    assert db
''',
    "env_opt_in": '''
import os
import unittest
@unittest.skipUnless(os.environ.get("RC_LIVE_LOBBY"), "opt-in")
class T(unittest.TestCase):
    def test_thing(self):
        self.assertTrue(True)
''',
    "optional_third_party": '''
import pytest
np = pytest.importorskip("numpy")
def test_thing():
    assert np
''',
    # The false-positive side of the parents[N] resolver. Without it the path
    # is opaque, the site lands in UNRESOLVED, and a legitimate gitignored-data
    # skip written in the idiomatic spelling reads as a defect. This control is
    # what makes the resolver itself load-bearing rather than an equivalent
    # mutant: the DEFECT probes above still flag without it (via UNRESOLVED),
    # this one does not survive without it.
    "gitignored_artifact_via_parents_index": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
def test_thing():
    db = REPO / "data" / "rewind_history.db"
    if not db.is_file():
        pytest.skip("machine-local corpus absent")
    assert db
''',
    # The false-positive side of the dynamic-import rule: a target this scan
    # cannot read cannot be called first-party, so it stays a capability skip.
    # tests/test_ports.py is exactly this shape after the RM-119 B5 fix.
    "dynamic_import_of_a_runtime_named_module": '''
import importlib
import pytest
def _live(module_path):
    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        pytest.skip(f"optional dependency absent: {exc.name}")
def test_thing():
    assert _live("some.module")
''',
    # The false-positive side of the historical-trackedness rule, and the two
    # cases that actually shaped it. Neither may flag.
    #
    # `16.9.1` is a tmp_path fixture directory in test_ddragon_mirror_prune.py
    # whose NAME collides with the deleted DDragon mirror
    # `data/daemon_slayer/16.9.1/`. Suffix matching flags it; root-anchored
    # matching does not, which is why `_is_vanished_chain` refuses to consult a
    # suffix index.
    "vanished_name_collision_in_a_tmp_fixture": '''
import os
import pytest
def test_thing(tmp_path):
    os.makedirs(tmp_path / "16.9.1", exist_ok=True)
    if not (tmp_path / "16.9.1").is_dir():
        pytest.skip("fixture tree not created")
    assert True
''',
    # A genuinely deleted repo-root file whose test premise is nevertheless a
    # live machine/network question. The `network` signal must win in
    # `_classify`, which is what makes the B4 rule precise without a
    # special case.
    "vanished_path_but_the_premise_is_a_live_endpoint": '''
import urllib.request
import unittest
class T(unittest.TestCase):
    def test_thing(self):
        with urllib.request.urlopen("http://127.0.0.1:8889/monitor") as r:
            status = r.status
        if status == 200:
            self.skipTest("moon_monitor.html is present on this box")
        self.assertEqual(status, 404)
''',
    # The git-LFS carve-out from the CAPABILITY side, and the shape of the two
    # real sites in tests/test_rm175_aram_table_known_wrong.py. The path is
    # tracked, so the pre-LFS guard called it B5 masking; the content is a
    # pointer stub in any checkout that did not smudge or `git lfs pull`, which
    # is every CI run here, so the gate is an environment capability.
    "tracked_artifact_behind_a_git_lfs_filter": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    t = (REPO / "data" / "daemon_slayer" / "laning_scenarios"
         / "16.13.1" / "laning_scenarios_aram.json")
    if not t.is_file():
        pytest.skip("LFS table not fetched on this checkout")
    assert t.stat().st_size
''',
    # The same carve-out reached through the LFS DIRECTORY rather than a file.
    # Every tracked path under it is LFS, so the ALL quantifier still holds -
    # this is the tests/test_rm175_aram_table_known_wrong.py:257 spelling.
    "git_lfs_directory_every_member_of_which_is_filtered": '''
import pytest
from pathlib import Path
TABLES = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer" / "laning_scenarios"
def test_thing():
    p = TABLES / "16.13.1" / "laning_scenarios_aram.json"
    if not TABLES.is_dir() or not p.is_file():
        pytest.skip("LFS tables not fetched on this checkout")
    assert p.stat().st_size
''',
    # Tree-shape: a module asking WHERE IN THE CHECKOUT it is running from.
    # That is a capability question (the answer changes what the surrounding
    # tree contains), and it must stay one - this is the positive control for
    # the non-indexed `.parents` branch in `_collect`.
    "checkout_tree_shape_path": '''
import unittest
from pathlib import Path
_IN_WORKTREE = "worktrees" in (p.name.lower() for p in Path(__file__).resolve().parents)
@unittest.skipIf(_IN_WORKTREE, "a scratch worktree does not carry data/meta")
class T(unittest.TestCase):
    def test_thing(self):
        self.assertTrue(True)
''',
}


@pytest.mark.parametrize("name", sorted(_DEFECT_MUTATIONS))
def test_mutation_defective_skip_is_flagged(name):
    """Teeth check: each synthetic always-pass guard must be caught.

    The bar is the one the real guard applies - anything that is not a proven
    CAPABILITY fails it. DEFECT and UNRESOLVED are both caught; which of the
    two a site lands in depends on whether the thing it gates on is readable
    statically, and that distinction must not decide whether it ships.
    """
    findings = scan_source("tests/test_mutant.py", _DEFECT_MUTATIONS[name])
    assert findings, f"{name}: no skip site found at all"
    assert any(f.verdict != CAPABILITY for f in findings), (
        f"{name}: the guard did not flag a skip gated on tracked state - "
        + "; ".join(f"{f.verdict}:{f.evidence}" for f in findings)
    )


@pytest.mark.parametrize("name,expected", [
    ("skip_gated_on_a_path_git_used_to_track", ROTTED),
    ("bare_skip_gated_on_a_removed_archive_path", ROTTED),
    ("bare_unconditional_mark_skip_decorator", DEFECT),
    ("unconditional_mark_skip_with_reason", DEFECT),
    ("unconditional_unittest_skip", DEFECT),
    ("module_level_pytestmark_unconditional_skip", DEFECT),
    # Class B5 proper, pinned by NAME rather than by "not CAPABILITY", so the
    # git-LFS carve-out below cannot quietly widen into the whole tracked set.
    # These three gate on ordinary tracked files (ops/rc_config.json,
    # data/daemon_slayer/current.txt, web/legacy_index.html) and must stay
    # DEFECT forever.
    ("bare_skip_on_tracked_path", DEFECT),
    ("mark_skipif_on_tracked_path", DEFECT),
    ("skiptest_raise_on_tracked_path", DEFECT),
    # The two LFS-adjacent defects: a chain that also names non-LFS tracked
    # files, and an LFS gate sharing a condition with an ordinary one.
    ("skip_on_a_dir_holding_both_lfs_and_ordinary_tracked_files", DEFECT),
    ("lfs_path_used_to_launder_a_tracked_non_lfs_path", DEFECT),
])
def test_mutation_lands_in_the_intended_verdict(name, expected):
    """Pin the REASON, not just the colour.

    `test_mutation_defective_skip_is_flagged` accepts anything that is not
    CAPABILITY, which is the right bar for shipping but too loose to protect a
    rule: if the historical-trackedness oracle broke, these two would still be
    caught as UNRESOLVED and the parametrized test above would stay green while
    the B4 rule did nothing. Naming the expected verdict makes that visible.
    """
    findings = scan_source("tests/test_mutant.py", _DEFECT_MUTATIONS[name])
    assert [f.verdict for f in findings] == [expected], (
        f"{name}: expected {expected}, got "
        + "; ".join(f"{f.verdict}:{f.evidence}" for f in findings)
    )


@pytest.mark.parametrize("name", sorted(_CAPABILITY_CONTROLS))
def test_mutation_capability_skip_is_not_flagged(name):
    """False-positive side: a legitimate capability skip must stay green."""
    findings = scan_source("tests/test_mutant.py", _CAPABILITY_CONTROLS[name])
    assert findings, f"{name}: no skip site found at all"
    bad = [f"{f.verdict}:{f.evidence}" for f in findings
           if f.verdict != CAPABILITY]
    assert not bad, f"{name}: legitimate capability skip flagged - {bad}"


def test_mutation_on_a_real_module_goes_red_then_green(tmp_path):
    """The same probe against a REAL module's text, on disk, both ways."""
    real = _REPO_ROOT / "tests" / "test_pro_match_index.py"
    clean = real.read_text(encoding="utf-8")
    baseline = scan_source("tests/test_pro_match_index.py", clean)
    assert baseline, "no skip sites in the control module"
    assert all(f.verdict == CAPABILITY for f in baseline), (
        "control module is not clean: "
        + "; ".join(f"{f.site.label}={f.verdict}" for f in baseline)
    )

    mutant = tmp_path / "test_mutated.py"
    mutant.write_text(clean + _DEFECT_MUTATIONS["bare_skip_on_tracked_path"],
                      encoding="utf-8")
    after = scan_source("tests/test_pro_match_index.py",
                        mutant.read_text(encoding="utf-8"))
    assert any(f.verdict == DEFECT for f in after), (
        "injecting a skip gated on tracked ops/rc_config.json did not flag: "
        + "; ".join(f"{f.site.label}={f.verdict}" for f in after)
    )


def test_allowlist_does_not_excuse_a_different_defect():
    """An exemption covers one reviewed artifact, not the whole module."""
    rel = next(iter(_ALLOWLIST))
    src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    injected = src + _DEFECT_MUTATIONS["unittest_skipunless_on_tracked_path"]
    fresh = [f for f in scan_source(rel, injected)
             if f.verdict != CAPABILITY and not _excused(f)]
    assert fresh, (
        f"injecting a skip on tracked web/legacy_index.html into the "
        f"allowlisted {rel} was swallowed by its exemption"
    )


def test_known_real_sites_classify_as_documented():
    """Anchors from the audit table, so a classifier regression is loud."""
    by_module: dict[str, list[_Finding]] = {}
    for f in scan_tree():
        by_module.setdefault(f.site.rel, []).append(f)

    def verdicts(rel):
        return {f.verdict for f in by_module.get(rel, [])}

    # network liveness, external binary, sibling repo, win32, gitignored data
    #
    # RE-POINTED 2026-08-06 (RM-119 B2). The network-liveness anchor used to
    # be tests/test_build_order_variants.py, whose own `self.skipTest("DS
    # engine ... is down")` moved into the shared gate
    # `tests/test_ds_live_route_gate.require_live_engine`. That module now
    # holds the canonical DS-route gate, and the classifier still reads it as
    # CAPABILITY off the same evidence (`env; network`) because it resolves
    # `core.daemon_slayer_client.is_engine_up` through to `urlopen`. Keeping a
    # DS-route anchor here is the point: B2 asked whether these gates were
    # capability or masking, the answer was capability, and this line is what
    # makes a classifier regression on that answer loud.
    assert verdicts("tests/test_ds_live_route_gate.py") == {CAPABILITY}
    assert verdicts("tests/test_coach_choices_trigger_render.py") == {CAPABILITY}
    assert verdicts("tests/test_loop_concurrency.py") == {CAPABILITY}
    assert verdicts("tests/test_hotkey_lowlevel_decoder.py") == {CAPABILITY}
    assert verdicts("tests/test_pro_match_index.py") == {CAPABILITY}
    # A sixth anchor sat here on
    # agents/daemon_slayer/tests/test_changelog_tracks_engine_version.py, whose
    # only skip gated on a mirror-tree sentinel. That mirror is gone and the
    # skip with it, so the module now has ZERO skip sites and the anchor had no
    # premise left. The tree-shape branch it exercised keeps its positive
    # control in `_CAPABILITY_CONTROLS["checkout_tree_shape_path"]`, so removing
    # the real-site anchor does not leave that classifier rule unasserted.

    # The git-LFS anchor, added 2026-08-06. Both sites in this module gate on
    # an LFS-filtered ARAM laning table, which no workflow fetches, so both are
    # CAPABILITY - and the evidence must say so in the LFS bucket. Asserting
    # the EVIDENCE and not just the verdict is what stops a future widening of
    # the tracked rule from reaching the same green by the wrong route.
    rm175 = by_module.get("tests/test_rm175_aram_table_known_wrong.py", [])
    assert len(rm175) == 2, f"expected 2 skip sites in RM-175, got {len(rm175)}"
    assert {f.verdict for f in rm175} == {CAPABILITY}
    assert all("tracked-lfs=" in f.evidence for f in rm175), (
        "RM-175 sites are CAPABILITY for some reason other than git-LFS: "
        + "; ".join(f.evidence for f in rm175)
    )
    assert all("tracked=" not in f.evidence.replace("tracked-lfs=", "")
               for f in rm175)

    # Guards ABOUT skips must not be mistaken for skip sites.
    stack = by_module.get(
        "agents/daemon_slayer/tests/test_stack_ramp_schema_126.py", [])
    assert not stack, f"BurstSkipTests misread as a skip site: {stack}"
