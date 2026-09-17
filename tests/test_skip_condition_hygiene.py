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
import operator
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests import _repo_walk

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
_TEST_TREES = (
    "tests",
    "agents/daemon_slayer/tests",
    "agents/agent3_testing/suite",
    "tools/tests",
    "oss/win32_atomic_io/tests",
)

_GIT = shutil.which("git")

if _GIT is None:
    pytest.skip("git not on PATH - trackedness is unresolvable without it", allow_module_level=True)


# --------------------------------------------------------------------------- #
# Ground truth: what a checkout always has
# --------------------------------------------------------------------------- #
def _git_tracked() -> frozenset[str]:
    out = subprocess.run(
        [_GIT, "ls-files", "-z"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
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
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    ).stdout
    # `-z` output is a flat NUL-separated stream of (path, attr, value) triples.
    fields = out.split("\0")
    return frozenset(fields[i] for i in range(0, len(fields) - 2, 3) if fields[i + 2] == "lfs")


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
        if any(parts[i : i + n] == needle for i in range(len(parts) - n + 1)):
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
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
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
    dirs = {d for d in dirs if not any(t.startswith(d + "/") for t in _TRACKED)}
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
        return any(fnmatch.fnmatch(rel, pat) for rel in _TRACKED for pat in pats)
    return chain in _TRACKED_SUFFIXES


# --------------------------------------------------------------------------- #
# Skip-construct recognition
# --------------------------------------------------------------------------- #
_DECORATOR_SKIPS = {
    "pytest.mark.skipif",
    "mark.skipif",
    "skipif",
    "unittest.skipIf",
    "skipIf",
    "unittest.skipUnless",
    "skipUnless",
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
    "pytest.mark.skip",
    "mark.skip",
    "unittest.skip",
}

_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
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
    # RM-440: verdicts forced by a single firing arm of the condition, as
    # "<VERDICT>:<why>". See `_forced_by_arms`.
    forced: set = field(default_factory=set)
    # RM-463: a platform dotted name was READ somewhere under this walk, whether
    # or not a taint then withheld the `platform` credit. Never a capability on
    # its own; only the probe-laundering test (`_reads`) consults it.
    platform_read: bool = False

    def merge(self, other: "_Signals") -> None:
        self.forced |= other.forced
        self.platform_read |= other.platform_read
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
        return (
            self.platform
            or self.env
            or self.binary
            or self.optional_import
            or self.network
            or self.tree_shape
            or self.external_tree
        )

    def evidence(self) -> str:
        bits = [
            n
            for n in (
                "unconditional",
                "platform",
                "env",
                "binary",
                "optional_import",
                "network",
                "tree_shape",
                "external_tree",
            )
            if getattr(self, n)
        ]
        if self.tracked:
            bits.append("tracked=" + ",".join(sorted(self.tracked)))
        if self.lfs:
            bits.append("tracked-lfs=" + ",".join(sorted(self.lfs)))
        if self.vanished:
            bits.append("was-tracked-now-gone=" + ",".join(sorted(self.vanished)))
        if self.untracked:
            bits.append("untracked=" + ",".join(sorted(self.untracked)))
        if self.firstparty_import:
            bits.append("first-party import=" + ",".join(sorted(self.firstparty_import)))
        if self.forced:
            bits.append("forced=" + ",".join(sorted(self.forced)))
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
    sig.tracked = {c for c in sig.tracked if not any(o != c and o.startswith(c + "/") for o in longer)}
    sig.lfs = {c for c in sig.lfs if not any(o != c and o.startswith(c + "/") for o in longer)}
    sig.vanished = {c for c in sig.vanished if not any(o != c and o.startswith(c + "/") for o in longer)}


def _classify(sig: _Signals) -> str:
    _prune_prefix_chains(sig)
    # An unconditional skip takes no condition, so there is nothing it could be
    # gating on. It is a disabled test, and it outranks every other signal -
    # including a capability one that happens to be in the same function.
    if sig.unconditional:
        return DEFECT
    # RM-440: one firing arm of the condition was convicted ON ITS OWN, or the
    # condition is true on every host RC runs on. Checked before capability,
    # because an OR fires when ANY arm does, so a capability in a sibling arm
    # restricts nothing: `shutil.which("node") is None or not TRACKED.exists()`
    # skips on a node-bearing runner exactly when the tracked file is broken.
    if any(f.startswith(DEFECT + ":") for f in sig.forced):
        return DEFECT
    if any(f.startswith(ROTTED + ":") for f in sig.forced):
        return ROTTED
    # A capability signal wins over the WHOLE-condition signal set:
    # `not SIDECAR.is_dir() or sys.platform != "win32"` (SIDECAR gitignored)
    # cannot fire on a healthy checkout no matter what else it touches. The
    # per-arm rule above has already refused the OR shapes where it could.
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
_OPTIONAL_IMPORT_EXC = {"ImportError", "ModuleNotFoundError", "Exception", "OSError", "AttributeError"}


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
    if not any(isinstance(s, (ast.Import, ast.ImportFrom)) for s in ast.walk(node)):
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
_PASSTHROUGH_CALLS = {
    "resolve",
    "absolute",
    "expanduser",
    "as_posix",
    "abspath",
    "realpath",
    "normpath",
    "strip",
    "rstrip",
}
_PATHY_CALLS = {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "fspath"}


def _is_abs_literal(s: str) -> bool:
    return bool(s) and (s.startswith("/") or (len(s) > 1 and s[1] == ":" and s[0].isalpha()))


def _segments(expr: ast.AST, model: _Model, scope: ast.AST, seen: frozenset, depth: int) -> list[str] | None:
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
        return (left if left is not None else [None]) + (right if right is not None else [None])

    if isinstance(expr, ast.Name):
        if expr.id == "__file__":
            return model.file_segments()
        if expr.id in seen:
            return None
        bound = model.lookup(expr.id, scope)
        if len(bound) == 1:
            return _segments(bound[0], model, scope, seen | {expr.id}, depth + 1)
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


def _cross_module_segments(expr: ast.Attribute, model: _Model, scope, seen: frozenset, depth: int) -> list[str] | None:
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


def _call_segments(expr: ast.Call, model: _Model, scope, seen: frozenset, depth: int) -> list[str] | None:
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
            root = s[len(_ABS) :]
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
_PLATFORM_DOTTED = {"sys.platform", "os.name", "platform.system", "platform.machine", "platform.release"}
_ENV_CALLS = {"getenv", "environ"}
_NETWORK_TOKENS = {"urlopen", "urlretrieve", "create_connection", "socket", "gethostbyname", "connect", "getaddrinfo"}
_NETWORK_ROOTS = {"requests", "httpx", "urllib", "socket", "http", "aiohttp"}
_PATH_PREDICATES = {
    "exists",
    "is_file",
    "is_dir",
    "is_symlink",
    "isfile",
    "isdir",
    "islink",
    "read_text",
    "read_bytes",
    "stat",
    "listdir",
    "iterdir",
    "open",
}


# --------------------------------------------------------------------------- #
# RM-440: host evaluation - is a platform expression actually a question?
# --------------------------------------------------------------------------- #
# Naming `os.name` is not the same as depending on it. `os.name in ("nt",
# "posix")` is true on every host RC is tested on, so a skip gated on it is a
# disabled test that the platform vocabulary above used to read as CAPABILITY.
# The fix is to EVALUATE platform expressions under each supported host and
# credit the platform signal only when the answer differs between them.
#
# The hosts are the two RC actually runs its suites on: Windows (Legion) and
# ubuntu (CI). A condition true on both skips everywhere RC is ever tested,
# which is the definition of a disabled test here, whatever it would do on a
# host nobody runs. Only `sys.platform`, `os.name` and `platform.system()` are
# modelled; `platform.machine` / `platform.release` stay opaque, so they keep
# their capability credit exactly as before.
_HOST_PROFILES = (
    {"sys.platform": "win32", "os.name": "nt", "platform.system": "Windows"},
    {"sys.platform": "linux", "os.name": "posix", "platform.system": "Linux"},
)
# RM-449 DECLINED part (1): no off-runner (darwin) host profile. A rescue that
# credits a skip which cannot fire on either runner WIDENS what this guard
# accepts, and it could only be made sound by enumerating every way a module
# can fake a platform read (rebinding, attribute stores, setattr, monkeypatch,
# star imports, globals(), exec, match captures ...) - which never closes. No
# real skip site needs it. Such a skip stays UNRESOLVED, the safe direction.
_UNKNOWN = object()


# RM-463: a value the evaluator REFUSES to model - a list / set display, a bare
# uncalled `platform.system`, or an operation CPython definitely raises on
# (`os.name["a"]`, `sys.platform < 1`). Modelling any of these cannot match
# CPython exactly. A refusal carries NOTHING: no value and no truthiness (round
# 2 - a refusal that kept a truth value was itself a fold, and was refuted:
# `[[f()] or "a"]` read as truthy although `f()` raises). It is never a host
# constant, and a foldable expression that reaches one earns no capability
# credit at all (`_collect`).
_REFUSED = object()
_STR_METHODS = {"startswith", "endswith", "lower", "upper", "casefold", "strip"}
# RM-449: builtins that only re-shape a platform value. `len(sys.platform) > 0`
# and `str(os.name) != "java"` are as constant as the bare reads they wrap.
_WRAPPER_BUILTINS = {"len": len, "str": str}
# RM-467: builtins that are pure, cheap and total enough to ASK whether CPython
# raises. They are never used to VALUE a call - only `_WRAPPER_BUILTINS` above
# do that, and only in the shapes they already did. `int(os.name)` raises on
# every host RC runs on, and reading that as an unknown kept its platform
# credit, so a gate that can only raise graded CAPABILITY.
_RAISE_PROBE_BUILTINS = {
    "int": int,
    "float": float,
    "bool": bool,
    "ord": ord,
    "chr": chr,
    "abs": abs,
    "round": round,
    "hex": hex,
    "oct": oct,
    "bin": bin,
    "divmod": divmod,
}
# RM-467: every binary operator, so `os.name * "a"` / `% "a"` / `** "a"` /
# `/ "a"` are seen. Only the RAISE is recorded; no BinOp is ever valued.
_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.BitAnd: operator.and_,
    ast.MatMult: operator.matmul,
}
_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _name_rebound(name: str, model: _Model) -> bool:
    """True when ANY construct anywhere in the module binds `name`.

    Guards the `len` / `str` fold: a rebound wrapper is not the builtin, so its
    value is never guessed. Deliberately module-wide and scope-blind -
    assignment, loop / with / walrus targets, del, parameters, def / class /
    except-as / match-capture / type-parameter names, and imports all count.
    Missing a form here can only fold a shadowed call as the builtin, which
    makes the guard stricter, never more accepting.
    """
    cache = model.__dict__.setdefault("_rm449_rebound", {})
    if name in cache:
        return cache[name]
    hit = False
    for n in ast.walk(model.tree):
        if isinstance(n, ast.Name):
            hit = n.id == name and not isinstance(n.ctx, ast.Load)
        elif isinstance(n, ast.arg):
            hit = n.arg == name
        elif isinstance(n, ast.alias):
            hit = (n.asname or n.name.split(".")[0]) == name
        else:
            hit = name in (getattr(n, "name", None), getattr(n, "rest", None))
        if hit:
            break
    cache[name] = hit
    return hit


class _Truth:
    """A BoolOp result whose truthiness is known but whose VALUE is not.

    `X or "a"` is truthy on every host, but its value may be X's, so it must
    not compare equal to "a". Compare refuses these; `_host_truth` reads them.
    """

    def __init__(self, value: bool) -> None:
        self.value = value

    def __bool__(self) -> bool:
        return self.value


_TRUTHY, _FALSY = _Truth(True), _Truth(False)


def _plain(v) -> bool:
    """A fully known value: not unknown, not refused, not a truth-only `_Truth`."""
    return v is not _UNKNOWN and v is not _REFUSED and not isinstance(v, _Truth)


def _bounded(v) -> bool:
    """True when running an operator on `v` cannot be expensive.

    RM-467 decides a raise by RUNNING the operation on known operands, which is
    the only way to match CPython exactly. `"a" * 10 ** 9` would match it far
    too well, so an operand this cannot bound is treated as unknown and no
    raise is claimed - the safe direction.
    """
    if v is None or isinstance(v, bool):
        return True
    if isinstance(v, int):
        return abs(v) <= 1024
    if isinstance(v, float):
        return abs(v) <= 1e6
    if isinstance(v, (str, bytes)):
        return len(v) <= 1024
    if isinstance(v, tuple):
        return len(v) <= 64 and all(_bounded(x) for x in v)
    return False


def _raise_probe(fn, args: list):
    """`_REFUSED` when `fn(*args)` definitely raises, else `_UNKNOWN`.

    NEVER a value: a call that succeeds stays unknown, so nothing new is
    folded. An operand that is unknown or unbounded stays unknown too - an
    unproven raise is not a raise.
    """
    if not all(_plain(a) and _bounded(a) for a in args):
        return _UNKNOWN
    try:
        fn(*args)
    except Exception:  # noqa: BLE001 - any raise is the datum
        return _REFUSED
    return _UNKNOWN


def _host_eval(
    node: ast.AST | None, model: _Model, scope: ast.AST, host: dict, seen: frozenset = frozenset(), depth: int = 0
):
    """The value of `node` on `host`, or `_UNKNOWN`. Never guesses."""
    if node is None or depth > _MAX_RESOLUTION_DEPTH:
        return _UNKNOWN
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Set, ast.Dict)):
        # RM-463: REMOVED fold. These were modelled as tuples, which CPython
        # does not do (`str([])`, `[] != ()`, set ordering and duplicates, an
        # unhashable set member that raises). Refused, never valued.
        # RM-467: a dict display joins them. `{"nt": 1}[os.name]` is a KeyError
        # on the linux runner; modelling the mapping to see that would be a new
        # fold, so the display itself is refused and the subscript inherits it.
        return _REFUSED
    if isinstance(node, ast.Tuple):
        vals = [_host_eval(e, model, scope, host, seen, depth + 1) for e in node.elts]
        if any(v is _REFUSED for v in vals):
            return _REFUSED
        if not all(_plain(v) for v in vals):
            return _UNKNOWN
        return tuple(vals)
    if isinstance(node, ast.Attribute):
        dotted = _dotted(node)
        if dotted == "platform.system":
            # RM-463: REMOVED fold. Uncalled, this is a function object, not
            # the string its call returns. Only the call below is modelled.
            return _REFUSED
        if dotted in host:
            return host[dotted]
        # RM-467: an attribute that a KNOWN value does not carry is a definite
        # AttributeError (`sys.platform.nonexistent`). Read as unknown it kept
        # the platform credit of the read underneath it.
        base = _host_eval(node.value, model, scope, host, seen, depth + 1)
        if base is _REFUSED:
            return _REFUSED
        if _plain(base) and not hasattr(base, node.attr):
            return _REFUSED
        return _UNKNOWN
    if isinstance(node, ast.Call):
        if node.keywords:
            return _UNKNOWN
        if _dotted(node.func) == "platform.system" and not node.args:
            return host["platform.system"]
        args = [_host_eval(a, model, scope, host, seen, depth + 1) for a in node.args]
        if any(a is _REFUSED for a in args):
            return _REFUSED
        if isinstance(node.func, ast.Name) and not _name_rebound(node.func.id, model):
            if node.func.id in _WRAPPER_BUILTINS:
                if len(node.args) == 1:
                    arg = args[0]
                    if isinstance(arg, (str, tuple)):
                        return _WRAPPER_BUILTINS[node.func.id](arg)
                    if node.func.id == "len" and _plain(arg) and not hasattr(type(arg), "__len__"):
                        return _REFUSED  # RM-463: `len(1)` raises TypeError in CPython
                    if node.func.id == "str" and _plain(arg):
                        # RM-467: `str(2)` is DECLINED, not folded - the row
                        # forbids valuing anything new. Read as unknown it let
                        # `str(len(os.name)) + 1` pass as a survivable gate
                        # although CPython raises on every host.
                        return _REFUSED
                    return _UNKNOWN
                # RM-467: the wrong arity is a definite raise over known
                # operands (`len(os.name, 1)`, `str(os.name, 1)`, `len()`).
                return _raise_probe(_WRAPPER_BUILTINS[node.func.id], args)
            if node.func.id in _RAISE_PROBE_BUILTINS:
                return _raise_probe(_RAISE_PROBE_BUILTINS[node.func.id], args)
        if isinstance(node.func, ast.Attribute):
            recv = _host_eval(node.func.value, model, scope, host, seen, depth + 1)
            if recv is _REFUSED:
                return _REFUSED
            if _plain(recv) and not hasattr(recv, node.func.attr):
                return _REFUSED  # RM-463: AttributeError, e.g. `(1).lower()`
            if isinstance(recv, str) and all(_plain(a) for a in args) and all(_bounded(a) for a in args):
                try:
                    out = getattr(recv, node.func.attr)(*args)
                except Exception:  # noqa: BLE001 - every operand is known, so CPython raises too
                    # RM-463: `sys.platform.startswith(1)`, `.lower(1)`.
                    return _REFUSED
                if node.func.attr in _STR_METHODS:
                    return out
                # RM-467: the method ran, but its result is not one this
                # evaluator models (a list from `split`, bytes from `encode`).
                # Refused rather than modelled, so `os.name.split()[5]` cannot
                # read as an index into an unknown that might not raise.
                return _REFUSED
        # RM-467: calling a KNOWN non-callable is a definite TypeError
        # (`sys.platform()`).
        fn = _host_eval(node.func, model, scope, host, seen, depth + 1)
        if fn is _REFUSED:
            return _REFUSED
        if _plain(fn) and not callable(fn):
            return _REFUSED
        return _UNKNOWN
    if isinstance(node, ast.Name):
        # A guarded-import sentinel is a capability question by construction,
        # even when each branch binds a literal.
        if node.id in seen or node.id in model.optional_names:
            return _UNKNOWN
        bound = model.lookup(node.id, scope)
        if len(bound) != 1:
            return _UNKNOWN
        return _host_eval(bound[0], model, scope, host, seen | {node.id}, depth + 1)
    if isinstance(node, ast.Subscript):
        recv = _host_eval(node.value, model, scope, host, seen, depth + 1)
        if recv is _REFUSED:
            return _REFUSED
        sl = node.slice
        if isinstance(sl, ast.Slice):
            parts = [
                None if p is None else _host_eval(p, model, scope, host, seen, depth + 1)
                for p in (sl.lower, sl.upper, sl.step)
            ]
            if any(p is _REFUSED for p in parts):
                return _REFUSED
            known_key = all(p is None or _plain(p) for p in parts)
            key = slice(*parts) if known_key else None
        else:
            key = _host_eval(sl, model, scope, host, seen, depth + 1)
            if key is _REFUSED:
                return _REFUSED
            known_key = _plain(key)
        if _plain(recv) and not isinstance(recv, (str, tuple)) and not hasattr(type(recv), "__getitem__"):
            return _REFUSED  # RM-463: `None[0]`, `(1)[0]` raise TypeError
        if not isinstance(recv, (str, tuple)) or not known_key:
            return _UNKNOWN
        # RM-463: receiver and key are both KNOWN here, so an exception is a
        # definite CPython raise - a non-int index or bound (TypeError), a zero
        # step (ValueError), out of range (IndexError). Refused, not unknown.
        try:
            return recv[key]
        except (IndexError, TypeError, ValueError):
            return _REFUSED
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        v = _host_eval(node.operand, model, scope, host, seen, depth + 1)
        return v if v is _UNKNOWN or v is _REFUSED else (not v)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        # RM-449: negative indexes and slice bounds (`os.name[-1]`).
        v = _host_eval(node.operand, model, scope, host, seen, depth + 1)
        if v is _REFUSED:
            return _REFUSED
        if isinstance(v, int):
            return -v
        if _plain(v) and not hasattr(type(v), "__neg__"):
            return _REFUSED  # RM-463: `-os.name` raises TypeError in CPython
        return _UNKNOWN
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Invert, ast.UAdd)):
        # RM-467: `~os.name` and `+os.name` are definite TypeErrors. Neither is
        # valued where it succeeds - only the raise is recorded.
        v = _host_eval(node.operand, model, scope, host, seen, depth + 1)
        if v is _REFUSED:
            return _REFUSED
        fn = operator.invert if isinstance(node.op, ast.Invert) else operator.pos
        return _raise_probe(fn, [v])
    if isinstance(node, ast.BinOp):
        # RM-463: NOT a fold - no BinOp is ever valued. Only a definite CPython
        # raise over two KNOWN operands (`os.name + 1`) is recorded, as a
        # refusal. RM-467 widens + and - to every binary operator; cheapness
        # now comes from `_bounded` rather than from the operator set, so
        # `os.name * "a"`, `% "a"`, `** "a"` and `/ "a"` are seen too.
        left = _host_eval(node.left, model, scope, host, seen, depth + 1)
        right = _host_eval(node.right, model, scope, host, seen, depth + 1)
        if left is _REFUSED or right is _REFUSED:
            return _REFUSED
        fn = _BINOPS.get(type(node.op))
        return _UNKNOWN if fn is None else _raise_probe(fn, [left, right])
    if isinstance(node, ast.BoolOp):
        decides = isinstance(node.op, ast.Or)  # truthiness that short-circuits
        unknown = False
        for part in node.values:
            v = _host_eval(part, model, scope, host, seen, depth + 1)
            if v is _REFUSED:
                # Reached, so CPython may evaluate it; a refusal says nothing
                # about whether it decides, so the whole BoolOp is refused.
                return _REFUSED
            if v is _UNKNOWN:
                unknown = True
            elif bool(v) is decides:
                return (_TRUTHY if decides else _FALSY) if unknown else v
        return _UNKNOWN if unknown else v
    if isinstance(node, ast.Compare):
        left = _host_eval(node.left, model, scope, host, seen, depth + 1)
        if left is _REFUSED:
            return _REFUSED
        for op, comp in zip(node.ops, node.comparators):
            fn = _COMPARE_OPS.get(type(op))
            if isinstance(op, (ast.Is, ast.IsNot)) and not (
                isinstance(comp, ast.Constant) and (comp.value is None or isinstance(comp.value, bool))
            ):
                return _UNKNOWN
            right = _host_eval(comp, model, scope, host, seen, depth + 1)
            if right is _REFUSED:
                return _REFUSED
            if fn is None or not _plain(left) or not _plain(right):
                return _UNKNOWN
            try:
                if not fn(left, right):
                    return False
            except (TypeError, ValueError):
                # RM-463: both operands are known, so CPython raises too
                # (`sys.platform < 1`, `os.name in b"nt"`). `-1 in b"nt"`
                # used to raise straight out of the guard.
                return _REFUSED
            left = right
        return True
    if isinstance(node, ast.IfExp):
        # RM-467: the same reading the BoolOp uses. With an UNKNOWN test either
        # arm may be evaluated, so a refusal in either is reached and the whole
        # expression is refused. With a KNOWN test only the taken arm decides,
        # and its VALUE is still not folded.
        test = _host_eval(node.test, model, scope, host, seen, depth + 1)
        if test is _REFUSED:
            return _REFUSED
        body = _host_eval(node.body, model, scope, host, seen, depth + 1)
        orelse = _host_eval(node.orelse, model, scope, host, seen, depth + 1)
        if test is _UNKNOWN:
            return _REFUSED if (body is _REFUSED or orelse is _REFUSED) else _UNKNOWN
        return _REFUSED if (body if bool(test) else orelse) is _REFUSED else _UNKNOWN
    return _UNKNOWN


def _host_values(node, model: _Model, scope: ast.AST) -> list:
    return [_host_eval(node, model, scope, h) for h in _HOST_PROFILES]


def _constant_values(vals: list) -> bool:
    """True when per-host `vals` are one known value on every supported host."""
    # RM-463: a refusal has no value, so it is never a constant; `_collect`
    # taints it instead.
    if any(v is _UNKNOWN or v is _REFUSED for v in vals):
        return False
    # Values are AST literals, strings and tuples of them, so `==` is plain.
    first = vals[0]
    return all(
        v is first or (not isinstance(v, _Truth) and not isinstance(first, _Truth) and v == first) for v in vals[1:]
    )


def _host_truth(node, model: _Model, scope: ast.AST) -> bool | None:
    """The truthiness of `node` when it is the same on every host, else None."""
    vals = _host_values(node, model, scope)
    if any(v is _UNKNOWN or v is _REFUSED for v in vals):
        return None
    truths = {bool(v) for v in vals}
    return truths.pop() if len(truths) == 1 else None


_HOST_FOLDABLE = (ast.Compare, ast.BoolOp, ast.UnaryOp, ast.Call, ast.Subscript, ast.BinOp, ast.IfExp)


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
        # RM-466 REMOVED: `tainted`. RM-463 used it to fire the probe-laundering
        # refusal only INSIDE a taint; that check is now unconditional, so
        # nothing read the flag any more and a flag nothing reads is a lie in
        # waiting.

    def take(self, expr: ast.AST | None, model: _Model, scope: ast.AST, seen: frozenset) -> None:
        if expr is None or id(expr) in self.consumed:
            return
        for n in ast.walk(expr):
            self.consumed.add(id(n))
        _record_chain(_segments(expr, model, scope, seen, 0), self.sig)


_MAX_RESOLUTION_DEPTH = 8
_RESHAPING_WRAPPERS = frozenset({"bool", "min", "max", "sorted"})


def _is_reshaping_wrapper(node: ast.AST, model: _Model) -> bool:
    if isinstance(node, ast.JoinedStr):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _RESHAPING_WRAPPERS
        and not _name_rebound(node.func.id, model)
    )


def _is_called(node: ast.AST, model: _Model) -> bool:
    parent = model.parent.get(node)
    return isinstance(parent, ast.Call) and parent.func is node


_PROBE_CREDITS = ("platform", "binary", "env", "optional_import")
# RM-466: what a laundered platform read forfeits. `network` joins the probe
# credits because `socket.gethostbyname(sys.platform)` is a platform question
# answered by a network call, and clearing only `_PROBE_CREDITS` left it.
_LAUNDERABLE_CREDITS = (*_PROBE_CREDITS, "network")
# Every signal `_classify` turns into CAPABILITY.
_CAPABILITY_CREDITS = (*_PROBE_CREDITS, "network", "tree_shape", "external_tree", "lfs", "untracked")
_PROBE_IMPORT_TAILS = ("find_spec", "import_module", "importorskip", "__import__")


def _reads(signal: str, node: ast.AST, model: _Model, scope: ast.AST, ctx: _Ctx, seen: frozenset, depth: int) -> bool:
    """True when `signal` is raised anywhere under `node`. Consumes nothing."""
    probe = _Ctx(ctx.broad_handler)
    probe.consumed = set(ctx.consumed)  # a copy: reading here consumes nothing
    _collect(node, model, scope, probe, seen, depth)
    return bool(getattr(probe.sig, signal))


def _probe_keys(node: ast.AST, model: _Model, scope: ast.AST, ctx: _Ctx, seen: frozenset, depth: int) -> list | None:
    """The expressions a capability probe is asked ABOUT, or None.

    A probe is a lookup whose ANSWER `_collect_call` credits as a binary / env
    / optional-import / network capability. Its KEYS are its arguments, or the
    subscript, or the left side of a membership test. RM-466 widens the set of
    recognised probes: recognising MORE of them can only WITHHOLD more credit
    (the one caller refuses), so it is never a grant of any new vocabulary.
    """
    if isinstance(node, ast.Subscript):
        # `os.environ[...]`, and RM-466 `dict(os.environ)[...]`.
        if _dotted(node.value).rsplit(".", 1)[-1] == "environ" or _reads(
            "env", node.value, model, scope, ctx, seen, depth
        ):
            return [node.slice]
        return None
    if isinstance(node, ast.Compare):
        # RM-466: `sys.platform in os.environ` asks the environment a question
        # about the platform, and earned the env credit for it.
        if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops) and any(
            _reads("env", c, model, scope, ctx, seen, depth) for c in node.comparators
        ):
            return [node.left]
        return None
    if not isinstance(node, ast.Call):
        return None
    fname = _dotted(node.func)
    parts = fname.split(".")
    keyed = (
        fname in ("shutil.which", "which", "distutils.spawn.find_executable")
        or parts[-1] in _ENV_CALLS
        or "environ" in parts
        or parts[-1] in _PROBE_IMPORT_TAILS
        # RM-466: a network call is a capability credit too, and `network` sat
        # outside the withheld set, so `socket.gethostbyname(sys.platform)`
        # cleared every taint.
        or parts[-1] in _NETWORK_TOKENS
        or parts[0] in _NETWORK_ROOTS
        # RM-466: a method on anything that reads the environment, which is how
        # `dict(os.environ).get(...)` and `os.environ.copy().get(...)` get past
        # a name-shaped test - `_dotted` reads them as `().get`.
        or (isinstance(node.func, ast.Attribute) and _reads("env", node.func.value, model, scope, ctx, seen, depth))
    )
    return list(node.args) + [k.value for k in node.keywords] if keyed else None


def _collect_tainted(
    node: ast.AST, model: _Model, scope: ast.AST, ctx: _Ctx, seen: frozenset, depth: int, clear: tuple
) -> None:
    """Collect `node`'s children, withholding the `clear` credits (and always
    the platform credit). Every other signal under the node still counts."""
    sub = _Ctx(ctx.broad_handler)
    sub.consumed = ctx.consumed
    for child in ast.iter_child_nodes(node):
        _collect(child, model, scope, sub, seen, depth)
    for name in ("platform", *clear):
        setattr(sub.sig, name, set() if isinstance(getattr(sub.sig, name), set) else False)
    ctx.sig.merge(sub.sig)


def _collect(node: ast.AST, model: _Model, scope: ast.AST, ctx: _Ctx, seen: frozenset, depth: int) -> None:
    """Walk a condition (or a whole region) accumulating what it depends on.

    `depth` counts RESOLUTION steps only - following a binding, entering a
    helper, crossing a module. Walking into a child node is free, otherwise a
    gate a few statements deep in a helper falls off the end of the budget and
    silently reads as unresolvable.
    """
    if node is None:
        return
    sig = ctx.sig

    # RM-440: an expression with one known value on every supported host asks
    # nothing, so nothing under it may be credited - above all not the platform
    # signal its `os.name` would otherwise earn.
    refused = False
    if isinstance(node, _HOST_FOLDABLE):
        vals = _host_values(node, model, scope)
        if _constant_values(vals):
            return
        refused = any(v is _REFUSED for v in vals)

    # RM-458 (refusal taint, NOT a fold): a platform read re-shaped by bool /
    # min / max / sorted or formatted into an f-string earns no platform
    # credit. Two rounds of folding these were refuted on CPython fidelity, so
    # no value is modelled; every OTHER signal under the wrapper still counts.
    # RM-463: an expression that reaches a `_REFUSED` value (a removed fold)
    # takes the same taint, so removing the fold hands no credit back.
    if not refused and isinstance(node, ast.Attribute) and not _is_called(node, model):
        # RM-463: a bare `platform.system` is refused by `_host_eval` but is
        # not a foldable node, so it is tainted here. Its CALL keeps the
        # credit. RM-467 generalises the test from that one name to whatever
        # `_host_eval` refuses, which is what reaches `sys.platform.nonexistent`
        # (a definite AttributeError) and any attribute of a refused value.
        refused = any(v is _REFUSED for v in _host_values(node, model, scope))
    if refused:
        # A removed fold used to VALUE this expression, and whatever it folded
        # to (`len([]) and os.getenv("X")` never fires; `{[]} or ...` always
        # raises) is now unknown - so nothing under it may make the site
        # acceptable. Defect evidence under it still counts.
        _collect_tainted(node, model, scope, ctx, seen, depth, clear=_CAPABILITY_CREDITS)
        return
    if _is_reshaping_wrapper(node, model):
        _collect_tainted(node, model, scope, ctx, seen, depth, clear=("platform",))
        return

    # RM-463: a capability probe whose argument reads the platform
    # (`bool(shutil.which(sys.platform))`) is the platform question in
    # disguise, so it supplies no probe credit either.
    # RM-466: no longer gated on `ctx.tainted`. Four of the six known bypasses
    # carry no wrapper at all - `dict(os.environ).get(sys.platform)`,
    # `os.environ.copy().get(sys.platform)`, `socket.gethostbyname(...)`,
    # `str(os.getenv(sys.platform)) != "None"` - so no taint was ever entered
    # and the taint-gated check could not see them. Dropping the gate only ever
    # WITHHOLDS credit; the known cost is that an unwrapped platform-named
    # probe (`shutil.which(sys.platform)`) is now refused too.
    keys = _probe_keys(node, model, scope, ctx, seen, depth)
    if keys is not None and any(_reads("platform_read", k, model, scope, ctx, seen, depth) for k in keys):
        _collect_tainted(node, model, scope, ctx, seen, depth, clear=_LAUNDERABLE_CREDITS)
        return

    if isinstance(node, ast.Attribute):
        dotted = _dotted(node)
        if dotted in _PLATFORM_DOTTED:
            sig.platform = True
            sig.platform_read = True
        if dotted.split(".")[-1] == "environ" or dotted.startswith("environ"):
            sig.env = True
        # `.parents` / `.parts` asks about the SHAPE of the checkout (am I in a
        # worktree, am I under a vendored copy of this tree) and that is a real
        # capability question. `.parents[3]` does not: it is a path expression
        # with an index, and crediting it as tree-shape is what made an
        # otherwise-identical B5 invisible when written in the idiomatic form.
        # Only the non-indexed use keeps the signal.
        if (
            node.attr in ("parents", "parts")
            and not _is_constant_indexed_parents(node, model)
            and _derives_from_file(node.value, model, scope, seen, 0)
        ):
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
    return (
        isinstance(idx, ast.Constant)
        and isinstance(idx.value, int)
        and not isinstance(idx.value, bool)
        and idx.value >= 0
    )


def _derives_from_file(expr: ast.AST | None, model: _Model, scope: ast.AST, seen: frozenset, depth: int) -> bool:
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
            if _derives_from_file(bound, model, scope, seen | {n.id}, depth + 1):
                return True
    return False


def _collect_import(node: ast.AST, sig: _Signals, model: _Model | None = None) -> None:
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


def _cross_module_attr(node: ast.Attribute, model: _Model, ctx: _Ctx, seen: frozenset, depth: int) -> None:
    if not isinstance(node.value, ast.Name) or depth >= _MAX_RESOLUTION_DEPTH:
        return
    target = _resolve_module(node.value.id, model)
    if target is None:
        return
    _enter_symbol(target, node.attr, model, ctx, seen, depth)


def _enter_symbol(target: _Model, symbol: str, model: _Model, ctx: _Ctx, seen: frozenset, depth: int) -> None:
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


def _enter_local_function(fn: ast.AST, call: ast.Call, model: _Model, ctx: _Ctx, seen: frozenset, depth: int) -> None:
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


def _collect_call(node: ast.Call, model: _Model, scope: ast.AST, ctx: _Ctx, seen: frozenset, depth: int) -> None:
    sig = ctx.sig
    fname = _dotted(node.func)
    tail = fname.rsplit(".", 1)[-1]
    root = fname.split(".")[0]

    if fname in ("shutil.which", "which", "distutils.spawn.find_executable"):
        sig.binary = True
    if tail in _ENV_CALLS or fname.startswith("os.environ"):
        sig.env = True
    if tail in ("find_spec", "import_module", "importorskip", "util.find_spec", "__import__"):
        # A DYNAMIC import is only a capability question when the thing being
        # imported is somebody else's. `importlib.import_module("mc.server")`
        # names a TRACKED file, so swallowing its failure into a skip is the
        # same always-pass guard as gating on that file's existence - which is
        # what tests/test_ports.py did until RM-119 B5. Resolve the literal
        # before deciding; a non-literal target stays a capability signal
        # because nothing here can say what it will hold at run time.
        target = node.args[0] if node.args else None
        if (
            isinstance(target, ast.Constant)
            and isinstance(target.value, str)
            and _first_party_file(target.value) is not None
        ):
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
    if tail in _PATH_PREDICATES and node.args and fname.startswith(("os.path.", "path.", "os.")):
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
                target = parent if (isinstance(parent, ast.Call) and parent.func is node) else node
                if id(target) not in seen_calls:
                    seen_calls.add(id(target))
                    sites.append(_Site(model.rel, target.lineno, "unconditional " + dotted, None, target))
            continue
        if isinstance(node, ast.Raise):
            exc = node.exc
            target = exc.func if isinstance(exc, ast.Call) else exc
            name = _dotted(target).rsplit(".", 1)[-1] if target is not None else ""
            if name.endswith(_SKIP_EXC_SUFFIXES):
                sites.append(_Site(model.rel, node.lineno, "raise SkipTest", None, node))
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
            sites.append(_Site(model.rel, node.lineno, "importorskip", cond, node))
        elif fname in _BODY_SKIPS or tail in _BODY_SKIP_TAILS:
            sites.append(_Site(model.rel, node.lineno, fname or tail, None, node))
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


def _firing_arms(
    node: ast.AST, fires_when_true: bool, model: _Model, scope: ast.AST, seen: frozenset = frozenset(), depth: int = 0
) -> list[tuple[ast.AST, bool]]:
    """Split a condition into arms EACH of which fires the skip on its own.

    `a or b` fires when either is true; `not (a and b)` - the skipUnless and
    else-branch spelling - fires when either is false (De Morgan). An `and`
    in firing polarity is ONE arm: its conjuncts restrict each other, so a
    capability there still gates the tracked half.
    """
    if depth > _MAX_RESOLUTION_DEPTH:
        return [(node, fires_when_true)]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _firing_arms(node.operand, not fires_when_true, model, scope, seen, depth + 1)
    splits = ast.Or if fires_when_true else ast.And
    if isinstance(node, ast.BoolOp) and isinstance(node.op, splits):
        out: list[tuple[ast.AST, bool]] = []
        for part in node.values:
            out.extend(_firing_arms(part, fires_when_true, model, scope, seen, depth + 1))
        return out
    if isinstance(node, ast.Name) and node.id not in seen and node.id not in model.optional_names:
        bound = model.lookup(node.id, scope)
        if len(bound) == 1 and isinstance(bound[0], (ast.BoolOp, ast.UnaryOp, ast.Name)):
            return _firing_arms(bound[0], fires_when_true, model, scope, seen | {node.id}, depth + 1)
    return [(node, fires_when_true)]


def _forced_by_arms(
    tests: list[tuple[ast.AST, bool]], model: _Model, scope: ast.AST, broad: bool, extra: list[ast.AST] = ()
) -> set[str]:
    """RM-440: convict a site on any single firing arm.

    `tests` are the conditions that must ALL hold for the skip to fire, each
    with the truth value that fires it; `extra` is surrounding context that is
    not a boolean test (an except clause, a try body). Two rules:

    * the conjunction is true on every supported host -> DEFECT, constant-true;
    * an arm, together with the OTHER tests and the context, classifies DEFECT
      or ROTTED on its own -> that verdict. A capability in a sibling OR arm
      no longer launders it.

    An arm that is constant-false on every host can never fire and is dropped;
    a constant-true arm contributes no signal and leaves the others to decide.
    """
    forced: set[str] = set()
    if not tests:
        return forced
    truths = []
    for test, fires in tests:
        t = _host_truth(test, model, scope)
        truths.append(None if t is None else (t is fires))
    if any(t is False for t in truths):
        return forced
    if all(t is True for t in truths) and not extra:
        forced.add(DEFECT + ":constant-true")
        return forced
    for i, (test, fires) in enumerate(tests):
        others = [o for j, (o, _) in enumerate(tests) if j != i and truths[j] is not True]
        for arm, arm_fires in _firing_arms(test, fires, model, scope):
            t = _host_truth(arm, model, scope)
            if t is not None and t is not arm_fires:
                continue  # this arm never fires on a supported host
            if t is not None and not others and not extra:
                forced.add(DEFECT + ":constant-true")
                continue
            ctx = _Ctx(broad)
            for n in ([] if t is not None else [arm]) + others + list(extra):
                _collect(n, model, scope, ctx, frozenset(), 0)
            verdict = _classify(ctx.sig)
            if verdict in (DEFECT, ROTTED):
                forced.add(verdict + ":firing-arm")
    return forced


def _polar_context(model: _Model, node: ast.AST) -> list[tuple[ast.AST, bool]]:
    """Enclosing if / while tests with the truth value that reaches `node`."""
    out: list[tuple[ast.AST, bool]] = []
    cur: ast.AST | None = node
    parent = model.parent.get(cur)
    while parent is not None and not isinstance(parent, _SCOPES):
        if isinstance(parent, ast.If):
            if any(s is cur for s in parent.body):
                out.append((parent.test, True))
            elif any(s is cur for s in parent.orelse):
                out.append((parent.test, False))
        elif isinstance(parent, ast.While) and any(s is cur for s in parent.body):
            out.append((parent.test, True))
        cur, parent = parent, model.parent.get(parent)
    return out


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
        fires = site.kind.rsplit(".", 1)[-1] != "skipUnless"
        ctx.sig.forced |= _forced_by_arms([(site.condition, fires)], model, scope, broad)
        return ctx.sig

    # Bare skip: nearest guards first, then widen to the enclosing function.
    near = _Ctx(broad)
    context = _context_conditions(model, site.node)
    for cond in context:
        _collect(cond, model, scope, near, frozenset(), 0)
    polar = _polar_context(model, site.node)
    extra = [c for c in context if not any(c is t for t, _ in polar)]
    near.sig.forced |= _forced_by_arms(polar, model, scope, broad, extra)
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
    forced: frozenset = frozenset()
    # False when the condition folds to a known value on every host, or names
    # a symbol bound more than once. `_REVIEWED_UNRESOLVED` is keyed on the
    # condition TEXT, so without this a reviewed symbol re-bound to a literal
    # keeps its exemption (RM-440).
    condition_pinned: bool = True


def _condition_pinned(model: _Model, site: _Site) -> bool:
    cond = site.condition
    if cond is None:
        return True
    scope = model.scope_of(site.node)
    if any(v is not _UNKNOWN for v in _host_values(cond, model, scope)):
        return False
    for n in ast.walk(cond):
        if not isinstance(n, ast.Name):
            continue
        bound = model.lookup(n.id, scope)
        if len(bound) > 1 or (bound and isinstance(bound[0], ast.Constant)):
            return False
    return True


def scan_source(rel: str, source: str) -> list[_Finding]:
    """Classify every skip construct in one module's source."""
    model = _Model(_REPO_ROOT / rel, source)
    model.rel = rel
    findings: list[_Finding] = []
    for site in _skip_sites(model):
        sig = _signals_for(model, site)
        findings.append(
            _Finding(
                site,
                _classify(sig),
                sig.evidence(),
                frozenset(sig.tracked | sig.firstparty_import | sig.vanished),
                frozenset(sig.forced),
                _condition_pinned(model, site),
            )
        )
    return findings


def scan_tree() -> list[_Finding]:
    findings: list[_Finding] = []
    for path in _iter_modules():
        rel = path.resolve().relative_to(_REPO_ROOT).as_posix()
        findings.extend(scan_source(rel, path.read_text(encoding="utf-8", errors="replace")))
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


# Reviewed UNRESOLVED sites. `_ALLOWLIST` above excuses a tracked ARTIFACT and
# cannot reach a site that gates on nothing the resolver can name, so this is a
# separate, narrower table: (module, exact `ast.unparse` of the skip condition)
# -> written reason. It excuses UNRESOLVED only - never DEFECT or ROTTED - and
# every key must match exactly ONE site (a stale or ambiguous key fails).
#
# Deliberately NOT done: adding the filesystem-codec calls to the platform
# vocabulary. That made `skipif(sys.getfilesystemencoding() == "utf-8")`, true
# on CI and Windows alike, classify CAPABILITY, and let a codec call OR'd onto
# a tracked-file check launder a DEFECT (capability wins in `_classify`).
_REVIEWED_UNRESOLVED: dict[tuple[str, str], str] = {
    ("tests/test_inbox_responder_runner.py", "not FS_LISTS_HIGH_SURROGATE_NAME"): (
        "The mark is shared by the runner grammar arm and the mutants "
        "note-sha12-surrogatepass arm. It fires only where the filesystem codec "
        "cannot encode a lone HIGH surrogate (POSIX surrogateescape), which is "
        "exactly where no directory listing can yield that note name - an "
        "unreachable input, measured on ubuntu CI 2026-09-16. The resolver sees "
        "only a str.encode call. "
        "test_grammar_cases_run_only_where_a_posix_listing_can_yield_them pins "
        "the condition to the predicate."
    ),
}


def _condition_source(finding: _Finding) -> str | None:
    cond = finding.site.condition
    return None if cond is None else ast.unparse(cond)


def _excused(finding: _Finding) -> bool:
    if (
        finding.verdict == UNRESOLVED
        and finding.condition_pinned
        and (finding.site.rel, _condition_source(finding)) in _REVIEWED_UNRESOLVED
    ):
        return True
    # A skip that fires on every supported host is a disabled test; no
    # artifact exemption was ever reviewed for that.
    if DEFECT + ":constant-true" in finding.forced:
        return False
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

    Derived from the TREE, never from `_TEST_TREES`, so it can contradict the
    tuple. Directories are rolled up to their shallowest test-bearing ancestor:
    `tests/snapshot_panels` is part of the `tests` tree, not a tree of its own.
    Enumeration is `tests/_repo_walk`, so "the tree" means the git-tracked set
    when git answers and the shared `EXCLUDED_DIRS` skips when it does not -
    vendored, mirrored, archived and machine-local runtime copies are out on
    the same grounds pytest.ini excludes them from collection.
    """
    # RM-394 (2026-09-09): enumeration moved from a raw `rglob` plus a private
    # hand-list to `tests/_repo_walk`, the repo's canonical walker - git index
    # first, `EXCLUDED_DIRS` segment skips as the backstop when git is absent or
    # the index read fails. The hand-list is GONE, not extended, and there is no
    # local skip set left to drift: every entry it used to carry is either an
    # infrastructure exclusion the shared walker already owns, or the `docs`
    # entry deleted below on purpose.
    #
    # What that fixes here: the inbox responder writes a full COPY OF THE REPO
    # to ops/runtime/responder_export/<sha>/, gitignored and machine-local, so
    # on this box the old rglob reported 8 phantom trees (four per export sha)
    # and this guard was RED here while green in CI. Untracked means not RC's
    # test surface, which is the same reasoning the old hand-list applied to
    # `moon_sync_inbox` on 2026-09-07: sibling repos deliver verbatim source
    # payloads there and those payloads carry THEIR test modules. Those are
    # INBOUND MAIL, not RC's - RC does not run them, does not own them, and
    # adding them to `_TEST_TREES` would assert RC's skip-hygiene rules over
    # another project's code. Neither name is hand-listed here any more; both
    # are untracked, and both are in the shared `EXCLUDED_DIRS` backstop.
    #
    # `docs` DELETED deliberately, and it is the one entry that was genuinely
    # this guard's own scope choice rather than infrastructure - it is not in
    # `_repo_walk.EXCLUDED_DIRS`. Dropping it because: (a) its only plausible
    # target was `docs/_archive` dated artifacts, and `_archive` IS a shared
    # exclusion now, so the motive is served; (b) `pytest.ini` `norecursedirs`
    # does NOT exclude `docs`, so a `test_*.py` landing there would really be
    # collected by a repo-root run and would really belong in this scan -
    # keeping the skip would blind the guard to exactly the class it exists to
    # catch. Measured 2026-09-09: zero `test_*.py` under `docs/`, tracked or on
    # disk, so this removal changes nothing today - it changes tomorrow.
    holders: set[str] = set()
    for path in _repo_walk.repo_files(_REPO_ROOT, patterns=("test_*.py",)):
        rel = _repo_walk.relative_posix(path, _REPO_ROOT)
        parts = rel.split("/")
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
    # ANTI-VACUITY, and this arm is why the RM-394 conversion is not a
    # regression. `discovered - set(_TEST_TREES)` is empty-set-safe: an
    # enumeration that returns NOTHING satisfies it, so after the walk moved
    # behind `tests/_repo_walk` an over-broad EXCLUDED_DIRS, a failed git index
    # read handled wrongly, or a bad pattern would all present as a clean repo.
    # Measured 2026-09-09 by a gate pass: forcing the enumeration empty left
    # this module at 56 passed. The anchor is this file's OWN directory - if
    # discovery cannot see the tree holding the guard that is running, the
    # enumeration is broken, and that is not circular with `_TEST_TREES`
    # because it is asserted against the disk, not against the tuple.
    assert "tests" in discovered, (
        "test-tree discovery did not find the `tests` directory that holds "
        f"this very file - the enumeration is broken, not the repo. Got: "
        f"{sorted(discovered)}"
    )
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
    assert _is_lfs_chain("data/daemon_slayer/laning_scenarios/16.13.1/laning_scenarios_aram.json")
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
        f"expected the LFS path in sig.lfs only, got tracked={sig.tracked} lfs={sig.lfs}"
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
    assert not missing, f"allowlisted modules no longer on disk: {missing} - delete the _ALLOWLIST entries with them"


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
            drifted.append(f"{rel}: claims {sorted(claimed)}, flags {sorted(actual)}")
    assert not drifted, (
        "allowlist entries no longer describe the skip they exempt - re-review "
        "each before re-pinning:\n" + "\n".join(drifted)
    )


# --- mutation probes: the teeth, pinned in-suite ---------------------------- #
_DEFECT_MUTATIONS = {
    "mark_skipif_on_tracked_path": """
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
@pytest.mark.skipif(not (REPO / "data" / "daemon_slayer" / "current.txt").exists(),
                    reason="no patch pointer")
def test_thing():
    assert True
""",
    "bare_skip_on_tracked_path": """
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "ops" / "rc_config.json"
    if not p.is_file():
        pytest.skip("config absent")
    assert p.read_text()
""",
    "aliased_pytest_bare_skip_on_tracked_path": """
import pytest as _p
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "ops" / "rc_config.json"
    if not p.is_file():
        _p.skip("config absent")
    assert p.read_text()
""",
    "unittest_skipunless_on_tracked_path": """
import os
import unittest
class T(unittest.TestCase):
    @unittest.skipUnless(os.path.exists("web/legacy_index.html"), "absent")
    def test_thing(self):
        self.assertTrue(True)
""",
    "helper_gate_reading_a_tracked_file": """
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def _patch():
    return (REPO / "data" / "daemon_slayer" / "current.txt").read_text().strip()
def test_thing():
    if _patch() != "16.14.1":
        pytest.skip("pinned")
    assert True
""",
    # RM-119 B5, the tests/test_ports.py shape: a first-party module pulled in
    # dynamically and its failure swallowed into a skip. Every module named
    # this way is TRACKED, so the skip can only fire on a broken checkout.
    "dynamic_first_party_import_swallowed": """
import importlib
import pytest
def test_thing():
    try:
        mod = importlib.import_module("mc.server")
    except Exception:
        pytest.skip("mc.server not importable here")
    assert mod.PORT
""",
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
    "runtime_named_import_swallowed_by_bare_except": """
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
""",
    # The same B5 in the idiomatic path spelling. `.parent.parent` was caught
    # and `.parents[1]` was not, in a resolver that treated `parents` as an
    # unanswerable tree-shape question; nine skip-bearing modules already write
    # it this way.
    "skip_on_a_tracked_path_via_parents_index": """
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
def test_thing():
    p = REPO / "ops" / "rc_config.json"
    if not p.is_file():
        pytest.skip("config absent")
    assert p.read_text()
""",
    "mark_skipif_on_a_tracked_path_via_parents_index": """
import pytest
from pathlib import Path
_HERE = Path(__file__).resolve()
@pytest.mark.skipif(not (_HERE.parents[1] / "web" / "legacy_index.html").exists(),
                    reason="page absent")
def test_thing():
    assert True
""",
    "dunder_import_of_a_first_party_module": """
import pytest
def test_thing():
    try:
        mod = __import__("core.ports")
    except ImportError:
        pytest.skip("ports registry not importable")
    assert mod
""",
    "importorskip_on_a_first_party_module": """
import pytest
mod = pytest.importorskip("core.build_order")
def test_thing():
    assert mod
""",
    "skiptest_raise_on_tracked_path": """
import unittest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
class T(unittest.TestCase):
    def test_thing(self):
        p = REPO / "data" / "daemon_slayer" / "current.txt"
        if not p.exists():
            raise unittest.SkipTest("no pointer")
        self.assertTrue(p.read_text())
""",
    # --- UNCONDITIONAL skips. The scanner was blind to all four until
    # 2026-08-06, and blindness is worse than misclassification: an invisible
    # site is not weighed at all. The last of these is the exact spelling of
    # the original pengu B4 defect, and a verifier proved a re-injected copy
    # of it left the guard GREEN.
    "bare_unconditional_mark_skip_decorator": """
import pytest
@pytest.mark.skip
def test_thing():
    assert True
""",
    "unconditional_mark_skip_with_reason": """
import pytest
@pytest.mark.skip(reason="flaky, will fix later")
def test_thing():
    assert True
""",
    "unconditional_unittest_skip": """
import unittest
class T(unittest.TestCase):
    @unittest.skip("disabled")
    def test_thing(self):
        self.assertTrue(True)
""",
    "module_level_pytestmark_unconditional_skip": """
import pytest
pytestmark = pytest.mark.skip(reason="whole module parked")
def test_thing():
    assert True
""",
    # --- RM-119 B4 proper: the gate names something git tracked once and no
    # longer does. `pengu/` is the real instance - renamed into
    # docs/_archive/2026-07-07-pengu-stub/ at f08ade78 - and it is written here
    # in the module-level form the original defect used.
    "skip_gated_on_a_path_git_used_to_track": """
import pytest
from pathlib import Path
PENGU = Path(__file__).resolve().parent.parent / "pengu"
pytestmark = pytest.mark.skipif(not PENGU.is_dir(), reason="stub relocated")
def test_thing():
    assert (PENGU / "index.js").is_file()
""",
    "bare_skip_gated_on_a_removed_archive_path": """
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "_archive" / "2026-05-01-audit" / "ui" / "base.py"
    if not p.is_file():
        pytest.skip("archived file absent on this checkout")
    assert p.read_bytes()
""",
    # --- the git-LFS carve-out, from the DEFECT side. Both of these reach an
    # LFS path and neither may be rescued by it, because the LFS rule is
    # "every tracked path this chain names is LFS", not "any".
    #
    # A directory one level above the LFS tables. `data/daemon_slayer` holds
    # `current.txt` and the whole DDragon mirror, none of it LFS, so the gate
    # can only fire on a broken checkout and stays B5.
    "skip_on_a_dir_holding_both_lfs_and_ordinary_tracked_files": """
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    d = REPO / "data" / "daemon_slayer"
    if not d.is_dir():
        pytest.skip("engine data tree absent")
    assert any(d.iterdir())
""",
    # Laundering: one real LFS gate sitting in the same condition as an
    # ordinary tracked gate. If the LFS signal were allowed to outrank
    # `sig.tracked` in `_classify`, this would read CAPABILITY and every B5
    # defect could be hidden by adding an LFS path to its condition.
    "lfs_path_used_to_launder_a_tracked_non_lfs_path": """
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
""",
}

_CAPABILITY_CONTROLS = {
    "platform": """
import sys
import pytest
@pytest.mark.skipif(sys.platform != "win32", reason="win32 only")
def test_thing():
    assert True
""",
    "external_binary": """
import shutil
import pytest
NODE = shutil.which("node")
def test_thing():
    if not NODE:
        pytest.skip("node not on PATH")
    assert NODE
""",
    "gitignored_artifact": """
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    db = REPO / "data" / "rewind_history.db"
    if not db.is_file():
        pytest.skip("machine-local corpus absent")
    assert db
""",
    "env_opt_in": """
import os
import unittest
@unittest.skipUnless(os.environ.get("RC_LIVE_LOBBY"), "opt-in")
class T(unittest.TestCase):
    def test_thing(self):
        self.assertTrue(True)
""",
    "optional_third_party": """
import pytest
np = pytest.importorskip("numpy")
def test_thing():
    assert np
""",
    # The false-positive side of the parents[N] resolver. Without it the path
    # is opaque, the site lands in UNRESOLVED, and a legitimate gitignored-data
    # skip written in the idiomatic spelling reads as a defect. This control is
    # what makes the resolver itself load-bearing rather than an equivalent
    # mutant: the DEFECT probes above still flag without it (via UNRESOLVED),
    # this one does not survive without it.
    "gitignored_artifact_via_parents_index": """
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
def test_thing():
    db = REPO / "data" / "rewind_history.db"
    if not db.is_file():
        pytest.skip("machine-local corpus absent")
    assert db
""",
    # The false-positive side of the dynamic-import rule: a target this scan
    # cannot read cannot be called first-party, so it stays a capability skip.
    # tests/test_ports.py is exactly this shape after the RM-119 B5 fix.
    "dynamic_import_of_a_runtime_named_module": """
import importlib
import pytest
def _live(module_path):
    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        pytest.skip(f"optional dependency absent: {exc.name}")
def test_thing():
    assert _live("some.module")
""",
    # The false-positive side of the historical-trackedness rule, and the two
    # cases that actually shaped it. Neither may flag.
    #
    # `16.9.1` is a tmp_path fixture directory in test_ddragon_mirror_prune.py
    # whose NAME collides with the deleted DDragon mirror
    # `data/daemon_slayer/16.9.1/`. Suffix matching flags it; root-anchored
    # matching does not, which is why `_is_vanished_chain` refuses to consult a
    # suffix index.
    "vanished_name_collision_in_a_tmp_fixture": """
import os
import pytest
def test_thing(tmp_path):
    os.makedirs(tmp_path / "16.9.1", exist_ok=True)
    if not (tmp_path / "16.9.1").is_dir():
        pytest.skip("fixture tree not created")
    assert True
""",
    # A genuinely deleted repo-root file whose test premise is nevertheless a
    # live machine/network question. The `network` signal must win in
    # `_classify`, which is what makes the B4 rule precise without a
    # special case.
    "vanished_path_but_the_premise_is_a_live_endpoint": """
import urllib.request
import unittest
class T(unittest.TestCase):
    def test_thing(self):
        with urllib.request.urlopen("http://127.0.0.1:8889/monitor") as r:
            status = r.status
        if status == 200:
            self.skipTest("moon_monitor.html is present on this box")
        self.assertEqual(status, 404)
""",
    # The git-LFS carve-out from the CAPABILITY side, and the shape of the two
    # real sites in tests/test_rm175_aram_table_known_wrong.py. The path is
    # tracked, so the pre-LFS guard called it B5 masking; the content is a
    # pointer stub in any checkout that did not smudge or `git lfs pull`, which
    # is every CI run here, so the gate is an environment capability.
    "tracked_artifact_behind_a_git_lfs_filter": """
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    t = (REPO / "data" / "daemon_slayer" / "laning_scenarios"
         / "16.13.1" / "laning_scenarios_aram.json")
    if not t.is_file():
        pytest.skip("LFS table not fetched on this checkout")
    assert t.stat().st_size
""",
    # The same carve-out reached through the LFS DIRECTORY rather than a file.
    # Every tracked path under it is LFS, so the ALL quantifier still holds -
    # this is the tests/test_rm175_aram_table_known_wrong.py:257 spelling.
    "git_lfs_directory_every_member_of_which_is_filtered": """
import pytest
from pathlib import Path
TABLES = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer" / "laning_scenarios"
def test_thing():
    p = TABLES / "16.13.1" / "laning_scenarios_aram.json"
    if not TABLES.is_dir() or not p.is_file():
        pytest.skip("LFS tables not fetched on this checkout")
    assert p.stat().st_size
""",
    # Tree-shape: a module asking WHERE IN THE CHECKOUT it is running from.
    # That is a capability question (the answer changes what the surrounding
    # tree contains), and it must stay one - this is the positive control for
    # the non-indexed `.parents` branch in `_collect`.
    "checkout_tree_shape_path": """
import unittest
from pathlib import Path
_IN_WORKTREE = "worktrees" in (p.name.lower() for p in Path(__file__).resolve().parents)
@unittest.skipIf(_IN_WORKTREE, "a scratch worktree does not carry data/meta")
class T(unittest.TestCase):
    def test_thing(self):
        self.assertTrue(True)
""",
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


@pytest.mark.parametrize(
    "name,expected",
    [
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
    ],
)
def test_mutation_lands_in_the_intended_verdict(name, expected):
    """Pin the REASON, not just the colour.

    `test_mutation_defective_skip_is_flagged` accepts anything that is not
    CAPABILITY, which is the right bar for shipping but too loose to protect a
    rule: if the historical-trackedness oracle broke, these two would still be
    caught as UNRESOLVED and the parametrized test above would stay green while
    the B4 rule did nothing. Naming the expected verdict makes that visible.
    """
    findings = scan_source("tests/test_mutant.py", _DEFECT_MUTATIONS[name])
    assert [f.verdict for f in findings] == [expected], f"{name}: expected {expected}, got " + "; ".join(
        f"{f.verdict}:{f.evidence}" for f in findings
    )


@pytest.mark.parametrize("name", sorted(_CAPABILITY_CONTROLS))
def test_mutation_capability_skip_is_not_flagged(name):
    """False-positive side: a legitimate capability skip must stay green."""
    findings = scan_source("tests/test_mutant.py", _CAPABILITY_CONTROLS[name])
    assert findings, f"{name}: no skip site found at all"
    bad = [f"{f.verdict}:{f.evidence}" for f in findings if f.verdict != CAPABILITY]
    assert not bad, f"{name}: legitimate capability skip flagged - {bad}"


def test_mutation_on_a_real_module_goes_red_then_green(tmp_path):
    """The same probe against a REAL module's text, on disk, both ways."""
    real = _REPO_ROOT / "tests" / "test_pro_match_index.py"
    clean = real.read_text(encoding="utf-8")
    baseline = scan_source("tests/test_pro_match_index.py", clean)
    assert baseline, "no skip sites in the control module"
    assert all(f.verdict == CAPABILITY for f in baseline), "control module is not clean: " + "; ".join(
        f"{f.site.label}={f.verdict}" for f in baseline
    )

    mutant = tmp_path / "test_mutated.py"
    mutant.write_text(clean + _DEFECT_MUTATIONS["bare_skip_on_tracked_path"], encoding="utf-8")
    after = scan_source("tests/test_pro_match_index.py", mutant.read_text(encoding="utf-8"))
    assert any(f.verdict == DEFECT for f in after), (
        "injecting a skip gated on tracked ops/rc_config.json did not flag: "
        + "; ".join(f"{f.site.label}={f.verdict}" for f in after)
    )


def test_allowlist_does_not_excuse_a_different_defect():
    """An exemption covers one reviewed artifact, not the whole module."""
    rel = next(iter(_ALLOWLIST))
    src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    injected = src + _DEFECT_MUTATIONS["unittest_skipunless_on_tracked_path"]
    fresh = [f for f in scan_source(rel, injected) if f.verdict != CAPABILITY and not _excused(f)]
    assert fresh, (
        f"injecting a skip on tracked web/legacy_index.html into the allowlisted {rel} was swallowed by its exemption"
    )


def test_reviewed_unresolved_entries_each_match_exactly_one_site():
    """A stale, moved-away or ambiguous reviewed key fails, never rots silently."""
    for (rel, cond), reason in _REVIEWED_UNRESOLVED.items():
        assert reason.strip(), f"{rel}: reviewed entry carries no reason"
        path = _REPO_ROOT / rel
        assert path.is_file(), f"{rel}: reviewed module no longer on disk"
        hits = [f for f in scan_source(rel, path.read_text(encoding="utf-8")) if _condition_source(f) == cond]
        assert len(hits) == 1, f"{rel}: {cond!r} matches {len(hits)} skip sites, not 1"
        assert hits[0].verdict == UNRESOLVED, (
            f"{rel}: {cond!r} now classifies {hits[0].verdict} - drop or re-review the entry"
        )
        assert hits[0].condition_pinned, f"{rel}: {cond!r} now folds to a constant or names a re-bound symbol"


_CODEC_LOOPHOLE_PROBES = {
    # Always true on CI and on Windows alike: a disabled test in disguise.
    "codec_equals_utf8": """
import sys
import pytest
@pytest.mark.skipif(sys.getfilesystemencoding() == "utf-8", reason="codec")
def test_thing():
    assert True
""",
    # The same shape as the reviewed site, but NOT the reviewed condition.
    "unlisted_codec_comparison": """
import sys
import pytest
def _encodable(name):
    try:
        name.encode(sys.getfilesystemencoding(), sys.getfilesystemencodeerrors())
    except UnicodeEncodeError:
        return False
    return True
CAN = _encodable("x")
@pytest.mark.skipif(not CAN, reason="filesystem codec cannot encode the name")
def test_thing():
    assert True
""",
    # A codec call OR'd onto a tracked-file check must not launder the DEFECT.
    "tracked_path_or_codec": """
import sys
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
@pytest.mark.skipif(not (REPO / "data" / "daemon_slayer" / "current.txt").exists()
                    or sys.getfilesystemencodeerrors() == "surrogateescape",
                    reason="no patch pointer")
def test_thing():
    assert True
""",
}


@pytest.mark.parametrize("name", sorted(_CODEC_LOOPHOLE_PROBES))
def test_codec_skips_outside_the_reviewed_table_are_rejected(name):
    """Scanned AS the reviewed module, so the file half of the key cannot excuse them."""
    rel = next(iter(_REVIEWED_UNRESOLVED))[0]
    findings = scan_source(rel, _CODEC_LOOPHOLE_PROBES[name])
    assert findings, f"{name}: no skip site found at all"
    for f in findings:
        assert f.verdict in (UNRESOLVED, DEFECT), f"{name}: classified {f.verdict}"
        assert not _excused(f), f"{name}: excused by the reviewed table"
    if name == "tracked_path_or_codec":
        assert {f.verdict for f in findings} == {DEFECT}


# --- RM-440: constant-true conditions and the OR-laundering loophole -------- #
# Each probe is paired with a control in `_RM440_CONTROLS` that differs ONLY in
# the loophole, so an over-broad fix fails the control and an absent fix fails
# the probe. The supported hosts are the two RC runs on: Windows (Legion) and
# Linux (CI). A condition true on BOTH skips everywhere RC is ever tested.
_RM440_PROBES = {
    # control: platform_equality_differs_by_host
    "os_name_in_every_supported_value": (
        """
import os
import pytest
@pytest.mark.skipif(os.name in ("nt", "posix"), reason="host")
def test_thing():
    assert True
""",
        DEFECT,
    ),
    # control: skipunless_single_host
    "sys_platform_in_every_supported_value": (
        """
import sys
import pytest
@pytest.mark.skipif(sys.platform in ("win32", "linux"), reason="host")
def test_thing():
    assert True
""",
        DEFECT,
    ),
    # control: platform_equality_differs_by_host
    "platform_compare_or_truthy_literal": (
        """
import os
import pytest
@pytest.mark.skipif(os.name == "nt" or 1, reason="host")
def test_thing():
    assert True
""",
        DEFECT,
    ),
    # control: sys_platform_startswith_one_host
    "constant_true_hidden_behind_a_module_binding": (
        """
import sys
import pytest
_ANY = sys.platform.startswith(("win", "linux"))
@pytest.mark.skipif(_ANY, reason="host")
def test_thing():
    assert True
""",
        DEFECT,
    ),
    # control: skipunless_single_host
    "skipunless_on_a_host_neither_runner_is": (
        """
import sys
import unittest
class T(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "sunos5", "solaris only")
    def test_thing(self):
        self.assertTrue(True)
""",
        DEFECT,
    ),
    # control: capability_or_capability
    "capability_or_constant_platform": (
        """
import os
import shutil
import pytest
@pytest.mark.skipif(shutil.which("node") is None or os.name in ("nt", "posix"),
                    reason="node")
def test_thing():
    assert True
""",
        DEFECT,
    ),
    # control: bare_skip_under_a_host_specific_if
    "bare_skip_under_a_constant_true_platform_if": (
        """
import os
import pytest
def test_thing():
    if os.name in ("nt", "posix"):
        pytest.skip("host")
    assert True
""",
        DEFECT,
    ),
    # control: platform_equality_differs_by_host. A constant conjunct
    # restricts nothing, so it must not supply the capability signal.
    "constant_platform_conjunct_launders_an_opaque_gate": (
        """
import os
import pytest
def _flag():
    return int("1")
@pytest.mark.skipif(os.name in ("nt", "posix") and _flag(), reason="opaque")
def test_thing():
    assert True
""",
        UNRESOLVED,
    ),
    # control: capability_or_gitignored_artifact
    "capability_or_tracked_file": (
        """
import shutil
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
@pytest.mark.skipif(shutil.which("node") is None
                    or not (REPO / "ops" / "rc_config.json").is_file(),
                    reason="node or config")
def test_thing():
    assert True
""",
        DEFECT,
    ),
    # control: capability_or_capability
    "platform_or_tracked_file": (
        """
import sys
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
@pytest.mark.skipif(sys.platform != "win32"
                    or not (REPO / "data" / "daemon_slayer" / "current.txt").exists(),
                    reason="win32 or pointer")
def test_thing():
    assert True
""",
        DEFECT,
    ),
    # control: bare_skip_env_or_gitignored_artifact
    "bare_skip_env_or_tracked_file": (
        """
import os
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "ops" / "rc_config.json"
    if not os.environ.get("RC_LIVE") or not p.is_file():
        pytest.skip("opt-in or config absent")
    assert p.read_text()
""",
        DEFECT,
    ),
    # control: skipunless_capability_and_gitignored_artifact (De Morgan: the
    # skip fires when EITHER arm is false, so the tracked arm fires alone)
    "skipunless_capability_and_tracked_file": (
        """
import os
import shutil
import unittest
class T(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node")
                         and os.path.exists("web/legacy_index.html"), "absent")
    def test_thing(self):
        self.assertTrue(True)
""",
        DEFECT,
    ),
}

_RM440_CONTROLS = {
    "platform_equality_differs_by_host": """
import os
import pytest
@pytest.mark.skipif(os.name != "nt", reason="host")
def test_thing():
    assert True
""",
    "sys_platform_startswith_one_host": """
import sys
import pytest
_WIN = sys.platform.startswith("win")
@pytest.mark.skipif(_WIN, reason="host")
def test_thing():
    assert True
""",
    "skipunless_single_host": """
import sys
import unittest
class T(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "win32 only")
    def test_thing(self):
        self.assertTrue(True)
""",
    "capability_or_capability": """
import shutil
import sys
import pytest
@pytest.mark.skipif(shutil.which("node") is None or sys.platform != "win32",
                    reason="node")
def test_thing():
    assert True
""",
    "bare_skip_under_a_host_specific_if": """
import os
import pytest
def test_thing():
    if os.name == "nt":
        pytest.skip("host")
    assert True
""",
    "capability_or_gitignored_artifact": """
import shutil
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
@pytest.mark.skipif(shutil.which("node") is None
                    or not (REPO / "data" / "rewind_history.db").is_file(),
                    reason="node or corpus")
def test_thing():
    assert True
""",
    "bare_skip_env_or_gitignored_artifact": """
import os
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "data" / "rewind_history.db"
    if not os.environ.get("RC_LIVE") or not p.is_file():
        pytest.skip("opt-in or corpus absent")
    assert p.stat()
""",
    "skipunless_capability_and_gitignored_artifact": """
import os
import shutil
import unittest
class T(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node")
                         and os.path.exists("data/rewind_history.db"), "absent")
    def test_thing(self):
        self.assertTrue(True)
""",
    # A guarded-import sentinel has ONE binding per branch but is a capability
    # question, so constant evaluation must never read through it.
    "optional_import_sentinel_compared_to_none": """
import pytest
try:
    import numpy as np
except ImportError:
    np = None
@pytest.mark.skipif(np is None, reason="numpy absent")
def test_thing():
    assert np
""",
}


@pytest.mark.parametrize("name", sorted(_RM440_PROBES))
def test_rm440_loophole_probe_is_rejected(name):
    src, expected = _RM440_PROBES[name]
    findings = scan_source("tests/test_mutant.py", src)
    assert findings, f"{name}: no skip site found at all"
    assert [f.verdict for f in findings] == [expected], f"{name}: expected {expected}, got " + "; ".join(
        f"{f.verdict}:{f.evidence}" for f in findings
    )


@pytest.mark.parametrize("name", sorted(_RM440_CONTROLS))
def test_rm440_control_differing_only_in_the_loophole_stays_capability(name):
    findings = scan_source("tests/test_mutant.py", _RM440_CONTROLS[name])
    assert findings, f"{name}: no skip site found at all"
    bad = [f"{f.verdict}:{f.evidence}" for f in findings if f.verdict != CAPABILITY]
    assert not bad, f"{name}: legitimate capability skip flagged - {bad}"


def test_rm440_rm150_measured_false_positive_is_still_accepted():
    """The precedence comment in `_classify` names this case; it must survive.

    The real module no longer carries the skip, so the control is its recorded
    shape: a deleted repo-root file named in the reason, a live endpoint as the
    premise, a bare skip whose own condition resolves to nothing.
    """
    src = _CAPABILITY_CONTROLS["vanished_path_but_the_premise_is_a_live_endpoint"]
    findings = scan_source("tests/test_vision_server_bind_rm150.py", src)
    assert [f.verdict for f in findings] == [CAPABILITY], "; ".join(f"{f.verdict}:{f.evidence}" for f in findings)


_RM440_REVIEWED_DEF = "FS_LISTS_HIGH_SURROGATE_NAME = filesystem_can_list_note_name(HIGH_SURROGATE_NOTE_NAME)"


def _reviewed_site_flags(src: str) -> bool:
    rel, cond = next(iter(_REVIEWED_UNRESOLVED))
    hits = [f for f in scan_source(rel, src) if _condition_source(f) == cond]
    assert len(hits) == 1, f"{cond!r} matched {len(hits)} sites"
    f = hits[0]
    return f.verdict != CAPABILITY and not _excused(f)


@pytest.mark.parametrize("variant", ["replaced_by_false", "replaced_by_true", "rebound_after_definition"])
def test_rm440_reviewed_symbol_redefined_as_a_constant_is_refused(variant):
    rel = next(iter(_REVIEWED_UNRESOLVED))[0]
    clean = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    assert clean.count(_RM440_REVIEWED_DEF) == 1, "reviewed definition moved"
    # Control first, in the same test: the unmodified module is excused, so a
    # guard that refused everything could not pass the probe below.
    assert not _reviewed_site_flags(clean)
    new = {
        "replaced_by_false": "FS_LISTS_HIGH_SURROGATE_NAME = False",
        "replaced_by_true": "FS_LISTS_HIGH_SURROGATE_NAME = True",
        "rebound_after_definition": (_RM440_REVIEWED_DEF + "\nFS_LISTS_HIGH_SURROGATE_NAME = False"),
    }[variant]
    assert _reviewed_site_flags(clean.replace(_RM440_REVIEWED_DEF, new))


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
        "RM-175 sites are CAPABILITY for some reason other than git-LFS: " + "; ".join(f.evidence for f in rm175)
    )
    assert all("tracked=" not in f.evidence.replace("tracked-lfs=", "") for f in rm175)

    # Guards ABOUT skips must not be mistaken for skip sites.
    stack = by_module.get("agents/daemon_slayer/tests/test_stack_ramp_schema_126.py", [])
    assert not stack, f"BurstSkipTests misread as a skip site: {stack}"


# --- RM-449: residuals of RM-440 -------------------------------------------- #
def _verdicts(src: str) -> list[str]:
    findings = scan_source("tests/test_mutant.py", src)
    assert findings, "no skip site found at all"
    return [f.verdict for f in findings]


# (1) DECLINED (merger ruling, round 3). A skip that cannot fire on either
# runner is NOT credited as an off-runner platform gate: that rescue widened
# the guard and could not be closed against faked platform reads. These pin
# the decline - each darwin-only gate keeps the verdict it had before RM-449
# (UNRESOLVED, or DEFECT where the bare-skip scan reads the tracked body), and
# none may classify CAPABILITY. The remaining rows are controls on the runner
# constant-true rule.
_RM449_OFF_RUNNER = {
    "skipif_darwin_only": (
        """
import sys
import pytest
@pytest.mark.skipif(sys.platform == "darwin", reason="darwin only")
def test_thing():
    assert True
""",
        UNRESOLVED,
    ),
    "skipif_platform_system_neither_runner": (
        """
import platform
import pytest
@pytest.mark.skipif(platform.system().lower() not in ("windows", "linux"),
                    reason="runners only")
def test_thing():
    assert True
""",
        UNRESOLVED,
    ),
    # The site gets no verdict of its own, so the scan widens to the whole
    # function and reads the tracked config the body opens.
    "bare_skip_under_a_darwin_if_with_a_tracked_body": (
        """
import sys
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    if sys.platform == "darwin":
        pytest.skip("darwin")
    assert (REPO / "ops" / "rc_config.json").read_text()
""",
        DEFECT,
    ),
    "darwin_and_opaque_flag": (
        """
import sys
import pytest
def _flag():
    return int("1")
@pytest.mark.skipif(sys.platform == "darwin" and _flag(), reason="darwin")
def test_thing():
    assert True
""",
        UNRESOLVED,
    ),
    "skipunless_not_darwin_or_opaque_flag": (
        """
import sys
import unittest
def _flag():
    return int("1")
class T(unittest.TestCase):
    @unittest.skipUnless(sys.platform != "darwin" or _flag(), "not darwin")
    def test_thing(self):
        self.assertTrue(True)
""",
        UNRESOLVED,
    ),
    # control: fires on both runners, so darwin being different saves nothing.
    "skipunless_darwin_only": (
        """
import sys
import unittest
class T(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "darwin only")
    def test_thing(self):
        self.assertTrue(True)
""",
        DEFECT,
    ),
    # control: true on every modelled host.
    "platform_system_in_all_three": (
        """
import platform
import pytest
@pytest.mark.skipif(platform.system().lower() in ("windows", "linux", "darwin"),
                    reason="host")
def test_thing():
    assert True
""",
        DEFECT,
    ),
    # control: a 3-host rule would call this CAPABILITY, because it is false on
    # darwin. It fires on both runners, so it is a disabled test.
    "runner_constant_true_but_false_on_darwin": (
        """
import sys
import pytest
@pytest.mark.skipif(sys.platform.startswith(("win", "linux")), reason="host")
def test_thing():
    assert True
""",
        DEFECT,
    ),
    # control: a runner-constant conjunct must still not supply a capability.
    "runner_constant_conjunct_false_on_darwin_launders_nothing": (
        """
import sys
import pytest
def _flag():
    return int("1")
@pytest.mark.skipif(sys.platform in ("win32", "linux") and _flag(), reason="x")
def test_thing():
    assert True
""",
        UNRESOLVED,
    ),
    # control: fires on no modelled host - a dead gate, still not judged.
    "skipif_on_a_host_nobody_models": (
        """
import sys
import pytest
@pytest.mark.skipif(sys.platform == "sunos5", reason="solaris only")
def test_thing():
    assert True
""",
        UNRESOLVED,
    ),
    # control: the darwin arm is dropped, the tracked arm convicts on its own.
    "darwin_or_tracked_file": (
        """
import sys
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
@pytest.mark.skipif(sys.platform == "darwin"
                    or not (REPO / "ops" / "rc_config.json").is_file(),
                    reason="darwin or config")
def test_thing():
    assert True
""",
        DEFECT,
    ),
}


@pytest.mark.parametrize("name", sorted(_RM449_OFF_RUNNER))
def test_rm449_off_runner_platform_gates_are_not_rescued(name):
    src, expected = _RM449_OFF_RUNNER[name]
    assert _verdicts(src) == [expected], name
    assert expected != CAPABILITY


# (2) The constant-true refusal in `_excused` must beat an artifact exemption.
_RM449_ALLOWLISTED_POINTER = '(_RM449_R / "data" / "daemon_slayer" / "current.txt").exists()'


def _rm449_allowlisted_injection(condition: str) -> str:
    return f"""

import sys
from pathlib import Path as _RM449_Path
_RM449_R = _RM449_Path(__file__).resolve().parent.parent
@pytest.mark.skipif({condition}, reason="pointer")
def test_rm449_injected():
    assert True
"""


def test_rm449_constant_true_skip_is_not_excused_by_the_artifact_allowlist():
    rel = "tests/test_ds_ability_data_status_rm95.py"
    claimed = _ALLOWLIST[rel][0]
    clean = (_REPO_ROOT / rel).read_text(encoding="utf-8")

    def injected(condition):
        want = ast.unparse(ast.parse(condition, mode="eval").body)
        src = clean + _rm449_allowlisted_injection(condition)
        found = [f for f in scan_source(rel, src) if _condition_source(f) == want]
        assert len(found) == 1, [f.site.label for f in found]
        return found[0]

    # Control: the same pointer without the constant-true wrapper IS excused,
    # so the allowlist genuinely reaches this site and only the refusal below
    # can be what keeps the probe out.
    control = injected(f"not {_RM449_ALLOWLISTED_POINTER}")
    assert control.verdict == DEFECT and control.gates_on == claimed
    assert _excused(control)

    # `sys.platform` is truthy on every runner, so this skips everywhere RC is
    # tested - yet it gates on exactly the allowlisted artifact.
    probe = injected(f"sys.platform or not {_RM449_ALLOWLISTED_POINTER}")
    assert DEFECT + ":constant-true" in probe.forced
    assert probe.gates_on and probe.gates_on <= claimed
    assert not _excused(probe)


# (3) Wrapped platform reads. Each probe is always true on both runners; its
# control differs only in the literal and genuinely differs per host.
_RM449_WRAPPED = {
    "len_of_sys_platform": ("len(sys.platform) > 0", "len(os.name) == 2"),
    "slice_of_sys_platform": ('sys.platform[:3] != "xyz"', 'sys.platform[:3] == "win"'),
    "index_of_os_name": ('os.name[0] in ("n", "p")', 'os.name[0] == "n"'),
    "str_of_os_name": ('str(os.name) != "java"', 'str(os.name) == "nt"'),
}


def _rm449_wrapped_source(condition: str, prelude: str = "") -> str:
    return f"""
import os
import sys
import pytest
{prelude}
@pytest.mark.skipif({condition}, reason="host")
def test_thing():
    assert True
"""


@pytest.mark.parametrize("name", sorted(_RM449_WRAPPED))
def test_rm449_wrapped_constant_true_platform_check_is_refused(name):
    probe, _ = _RM449_WRAPPED[name]
    findings = scan_source("tests/test_mutant.py", _rm449_wrapped_source(probe))
    assert [f.verdict for f in findings] == [DEFECT], name
    assert all(DEFECT + ":constant-true" in f.forced for f in findings)


@pytest.mark.parametrize("name", sorted(_RM449_WRAPPED))
def test_rm449_wrapped_check_that_differs_by_host_stays_capability(name):
    _, control = _RM449_WRAPPED[name]
    assert _verdicts(_rm449_wrapped_source(control)) == [CAPABILITY], name


def test_rm449_constant_subscript_disjunct_supplies_no_capability():
    """`os.name[:0]` is "" on every host: it asks nothing, so it credits nothing.

    The control differs only in the slice bounds and genuinely varies by host.
    """
    prelude = 'def _flag():\n    return int("1")\n'
    assert _verdicts(_rm449_wrapped_source("os.name[:0] or _flag()", prelude)) == [UNRESOLVED]
    assert _verdicts(_rm449_wrapped_source('os.name[1:2] == "t" or _flag()', prelude)) == [CAPABILITY]


@pytest.mark.parametrize("builtin", ["len", "str"])
def test_rm449_shadowed_builtin_is_not_folded(builtin):
    """A module-bound `len` / `str` is not the builtin; never guess its value.

    Each shadow makes the probe GENUINELY differ by host, so CAPABILITY is the
    correct verdict and folding it as the builtin would be a false DEFECT. The
    unshadowed text is asserted DEFECT alongside, so the pair cannot pass by
    the fold being absent altogether.
    """
    probe, prelude = {
        "len": ("len(sys.platform) > 0", 'def len(x):\n    return 0 if x == "win32" else 1\n'),
        "str": ('str(os.name) != "java"', 'def str(x):\n    return "java" if x == "nt" else x\n'),
    }[builtin]
    assert _verdicts(_rm449_wrapped_source(probe, prelude)) == [CAPABILITY]
    assert _verdicts(_rm449_wrapped_source(probe)) == [DEFECT]


# --- RM-449 round 2 --------------------------------------------------------- #
# (a) Faked platform reads, from the two refute rounds against the withdrawn
# off-runner rescue. With no rescue none of these can be accepted; each pins
# the verdict the guard gave before RM-449 and must never be CAPABILITY.
_RM449_HDR = "import pytest\nfrom pathlib import Path\nREPO = Path(__file__).resolve().parent.parent\n"


def _rm449_fake_bare(prelude: str, cond: str = 'sys.platform == "darwin"', local: str = "", params: str = "") -> str:
    return (
        _RM449_HDR
        + prelude
        + f"\ndef test_thing({params}):\n"
        + (f"    {local}\n" if local else "")
        + f"    if {cond}:\n        pytest.skip('darwin')\n"
        "    assert (REPO / 'ops' / 'rc_config.json').read_text()\n"
    )


_RM449_FAKE_BARE = {
    "real_import_control": ("import sys", "", ""),
    "module_rebinding": ("import sys, types\nsys = types.SimpleNamespace(platform='darwin')", "", ""),
    "local_rebinding": ("import sys, types", "sys = types.SimpleNamespace(platform='darwin')", ""),
    "aliased_import": ("import sys\nimport fakesys as sys", "", ""),
    "match_capture": (
        "import sys, types\nmatch types.SimpleNamespace(platform='darwin'):\n    case sys:\n        pass",
        "",
        "",
    ),
    "match_as": ("import sys\nmatch 1:\n    case object() as sys:\n        pass", "", ""),
    "monkeypatch_setattr": ("import sys", "monkeypatch.setattr(sys, 'platform', 'darwin')", "monkeypatch"),
    "attribute_store": ("import sys\nsys.platform = 'darwin'", "", ""),
    "setattr_call": ("import sys\nsetattr(sys, 'platform', 'darwin')", "", ""),
    "star_import": ("import sys\nfrom fakeplat import *", "", ""),
    "globals_store": ("import sys, types\nglobals()['sys'] = types.SimpleNamespace(platform='darwin')", "", ""),
    "exec_rebinding": ("import sys\nexec(\"sys = type('S', (), {'platform': 'darwin'})\")", "", ""),
}
_RM449_FAKE_PLATFORM = {
    **{
        name: (_rm449_fake_bare(pre, local=local, params=params), DEFECT)
        for name, (pre, local, params) in _RM449_FAKE_BARE.items()
    },
    "platform_system_patched": (
        _rm449_fake_bare("import platform\nplatform.system = lambda: 'Darwin'", 'platform.system() == "Darwin"'),
        DEFECT,
    ),
    "from_import_of_a_fake_platform": (
        _rm449_fake_bare("from fakeplat import platform", 'platform.system() == "Darwin"'),
        DEFECT,
    ),
    "short_circuit_past_a_fake_read": (
        _rm449_fake_bare(
            "import sys\nfrom fakeplat import platform", 'sys.platform == "darwin" or platform.system() == "Nope"'
        ),
        DEFECT,
    ),
    "fake_read_behind_a_darwin_conjunct": (
        _rm449_fake_bare(
            "import sys\nfrom fakeplat import platform", 'sys.platform == "darwin" and platform.system() == "Darwin"'
        ),
        DEFECT,
    ),
    "module_rebinding_skipif_and_tracked": (
        """
import sys
import types
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys = types.SimpleNamespace(platform="darwin")
@pytest.mark.skipif(sys.platform == "darwin"
                    and not (REPO / "ops" / "rc_config.json").is_file(),
                    reason="darwin")
def test_thing():
    assert True
""",
        UNRESOLVED,
    ),
}


@pytest.mark.parametrize("name", sorted(_RM449_FAKE_PLATFORM))
def test_rm449_faked_platform_reads_are_never_capability(name):
    src, expected = _RM449_FAKE_PLATFORM[name]
    assert expected != CAPABILITY
    assert _verdicts(src) == [expected], name


# (b) Ordering comparisons, each operator pinned in both directions. Runner
# lengths: sys.platform 5 / 5, os.name 2 / 5. A condition false on both runners
# fires nowhere RC is tested and stays UNRESOLVED (part 1 declined).
_RM449_ORDERING = {
    "len(os.name) < 9": DEFECT,
    "len(os.name) < 3": CAPABILITY,
    "len(sys.platform) < 5": UNRESOLVED,
    "len(sys.platform) <= 5": DEFECT,
    "len(os.name) <= 2": CAPABILITY,
    "len(sys.platform) > 5": UNRESOLVED,
    "len(os.name) > 2": CAPABILITY,
    "len(sys.platform) >= 5": DEFECT,
    "len(os.name) >= 5": CAPABILITY,
    "len(os.name) >= 9": UNRESOLVED,
}


@pytest.mark.parametrize("condition", sorted(_RM449_ORDERING))
def test_rm449_ordering_comparisons_evaluate_per_host(condition):
    assert _verdicts(_rm449_wrapped_source(condition)) == [_RM449_ORDERING[condition]]


# (c) Negative indexes and slices are always-true on both runners here.
_RM449_NEGATIVE = {
    'os.name[-1] in "tx"': 'os.name[-1] == "t"',
    'sys.platform[-1:] != "q"': 'sys.platform[-1:] == "2"',
}


@pytest.mark.parametrize("probe", sorted(_RM449_NEGATIVE))
def test_rm449_negative_index_and_slice_are_folded(probe):
    assert _verdicts(_rm449_wrapped_source(probe)) == [DEFECT]
    assert _verdicts(_rm449_wrapped_source(_RM449_NEGATIVE[probe])) == [CAPABILITY]


# (d) Inputs the evaluator cannot fold must read as unresolved, never raise:
# a non-int index or slice bound, a zero slice step, an out-of-range index on
# one runner, and arithmetic negation of a string.
@pytest.mark.parametrize(
    "condition",
    [
        'os.name["a"] == "n"',
        'os.name["a":] == "n"',
        'os.name[::0] == "n"',
        'os.name[3] == "i"',
        "(-os.name) == 1",
    ],
)
def test_rm449_unfoldable_subscripts_do_not_raise(condition):
    # The guard must not crash on these. UPDATED by RM-463 round 2: each is a
    # DEFINITE CPython raise over known operands on at least one runner (a str
    # key or bound, a zero step, index 3 of "nt", unary minus of a str). They
    # used to read as unknown and keep the platform credit of `os.name`, so an
    # always-erroring gate classified CAPABILITY; a raise is now a refusal and
    # earns no credit.
    assert _verdicts(_rm449_wrapped_source(condition)) == [UNRESOLVED]


# (e) Every way a module can rebind a builtin wrapper blocks the fold. The
# rebound `len` makes the probe genuinely differ by host, so CAPABILITY is
# right; the unrebound probe is DEFECT (asserted in the shadow test above).
_RM449_LEN = 'lambda x: 0 if x == "win32" else 1'
_RM449_REBIND_FORMS = {
    "for_loop_target": f"for len in ({_RM449_LEN},):\n    pass\n",
    "import_binding": "from fakebuiltins import len\n",
    "function_parameter": "def _helper(len):\n    return len\n",
    "except_handler_name": ("try:\n    pass\nexcept Exception as len:\n    pass\n"),
    "class_definition": "class len:\n    pass\n",
    "match_capture": "match 1:\n    case len:\n        pass\n",
    "match_mapping_rest": "match {}:\n    case {**len}:\n        pass\n",
    "dotted_import": "import len.sub\n",
    "aliased_import": "from fakebuiltins import measure as len\n",
}


@pytest.mark.parametrize("form", sorted(_RM449_REBIND_FORMS))
def test_rm449_any_rebinding_of_a_builtin_wrapper_blocks_the_fold(form):
    src = _rm449_wrapped_source("len(sys.platform) > 0", _RM449_REBIND_FORMS[form])
    assert _verdicts(src) == [CAPABILITY], form


# --- RM-458: refusal taint, after two refuted fold attempts ------------------ #
# Folding bool / min / max / sorted / f-strings was refuted twice on CPython
# fidelity (list and set literals are modelled as tuples) and reverted. What
# remains is a pure refusal: a platform read under one of those wrappers earns
# no platform credit. MEASURED against c3cde5dc6 over 5609 generated and
# verifier-authored conditions: 0 refused-then-accepted, and all 179 real skip
# sites keep their verdicts. The cost is deliberate: a genuinely host-varying
# wrapped read (`bool(sys.platform == "win32")`) is refused too - write the
# bare comparison instead.
_RM458_TAINTED = [
    "bool(sys.platform)",
    "bool(os.name[:1])",
    'bool(sys.platform == "win32")',
    'min(os.name) != "z"',
    'max(os.name) == "t"',
    'sorted(os.name) == ["n", "t"]',
    'f"{os.name}" != "java"',
    'f"{os.name!r:>9}" == "nt"',
]


@pytest.mark.parametrize("condition", _RM458_TAINTED)
def test_rm458_wrapped_platform_read_earns_no_capability(condition):
    assert _verdicts(_rm449_wrapped_source(condition)) == [UNRESOLVED], condition


@pytest.mark.parametrize(
    "condition, control",
    [
        ('bool(sys.platform == "win32")', 'sys.platform == "win32"'),
        ('min(os.name) == "n"', 'os.name[0] == "n"'),
        ('f"{os.name}" == "nt"', 'os.name == "nt"'),
    ],
)
def test_rm458_the_same_read_unwrapped_keeps_its_capability(condition, control):
    """Control: only the wrapper differs, so the taint is what refuses it."""
    assert _verdicts(_rm449_wrapped_source(control)) == [CAPABILITY]
    assert _verdicts(_rm449_wrapped_source(condition)) != [CAPABILITY]


def test_rm458_taint_removes_only_the_platform_signal():
    """A non-platform capability under a wrapper still counts."""
    prelude = "import shutil\n"
    assert _verdicts(_rm449_wrapped_source('bool(shutil.which("git"))', prelude)) == [CAPABILITY]


def test_rm458_a_shadowed_wrapper_is_not_tainted():
    prelude = "def bool(x):\n    return x\n"
    assert _verdicts(_rm449_wrapped_source("bool(sys.platform)", prelude)) == [CAPABILITY]


# The verifier's refuting snippets against both fold rounds. Each was DEFECT at
# c3cde5dc6, became CAPABILITY under a fold, and must stay DEFECT.
_RM458_REFUTATIONS = [
    '(sorted(os.name[:0]) != () and not TR.exists()) or shutil.which("git") is None',
    '(str(sorted(os.name[:0])) != "()" and not TR.exists()) or shutil.which("git") is None',
    "(bool(sorted(os.name[:0])) or True) and not TR.exists()",
    '(f"{sorted(os.name[:0])}" != "()" and not TR.exists()) or shutil.which("git") is None',
    '(not (max([{"a","z"},{"b"}]) == ("b",)) and not TR.exists()) or shutil.which("git") is None',
    '(not (str(max([[]])) == "()") and not TR.exists()) or shutil.which("git") is None',
]


@pytest.mark.parametrize("condition", _RM458_REFUTATIONS)
def test_rm458_refuted_fold_snippets_stay_refused(condition):
    src = f"""
import os
import shutil
import pytest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TR = ROOT / "core" / "match_db.py"
@pytest.mark.skipif({condition}, reason="h")
def test_x():
    pass
"""
    findings = scan_source("tests/test_mutant.py", src)
    assert [f.verdict for f in findings] == [DEFECT], condition
    assert not any(_excused(f) for f in findings)


# --- RM-463: unsound RM-449 folds REMOVED, probe laundering refused ---------- #
# The evaluator modelled list and set literals as tuples and a bare
# `platform.system` (a function) as its return value, so it VALUED forms CPython
# values differently or raises on. Per the second-refute rule those folds are
# removed, not patched. A removed fold must not turn a formerly refused site
# into an accepted one, so the value it used to supply is replaced by a
# refusal (`_REFUSED`) that is a taint like the RM-458 wrapper taint: the
# expression folds to nothing and earns no capability credit. Round 2: the
# refusal carries NO truthiness either (a truth-carrying refusal was a fold and
# was refuted), and a definite CPython raise over known operands is a refusal.
def _rm463_cpython(expr: str) -> list:
    out = []
    for plat, name, system in (("win32", "nt", "Windows"), ("linux", "posix", "Linux")):
        ns = {
            "sys": types.SimpleNamespace(platform=plat),
            "os": types.SimpleNamespace(name=name),
            "platform": types.SimpleNamespace(system=lambda s=system: s),
        }
        try:
            out.append(("V", eval(expr, ns)))  # noqa: S307 - literal test corpus
        except Exception as exc:  # noqa: BLE001 - any raise is the datum
            out.append(("RAISE", type(exc).__name__))
    return out


def _rm463_model(expr: str) -> list:
    model = _Model(_REPO_ROOT / "tests" / "test_mutant.py", f"import os\nimport sys\nimport platform\nX = ({expr})\n")
    node = model.tree.body[-1].value
    return _host_values(node, model, model.tree)


def _rm463_is_value(v) -> bool:
    return _plain(v)


def _rm463_assert_faithful(expr: str, model: list, real: list) -> None:
    """Every VALUE the evaluator returns must equal CPython's in type, value
    and repr. `_UNKNOWN` and `_REFUSED` claim nothing; a `_Truth` claims only
    its truthiness."""
    for got, (kind, want) in zip(model, real):
        if isinstance(got, _Truth):
            assert kind == "V" and bool(want) is got.value, (expr, got.value, want)
        elif _plain(got):
            assert kind == "V", f"{expr}: modelled {got!r}, CPython raises {want}"
            assert type(got) is type(want) and got == want and repr(got) == repr(want), (expr, got, want)


# Each was VALUED at 23e20e810 where CPython differs in type, value or repr, or
# raises. Found by an exhaustive sweep of atoms x unary x binary forms (4008
# mismatches over 67014 expressions, every one a list / set literal or a bare
# `platform.system`, plus a guard crash on bytes containment).
_RM463_UNSOUND = [
    "str([])",
    "[] != ()",
    '["nt"] == ("nt",)',
    'not ({"b"} > {"a", "z"})',
    "not len({[]})",
    'len({"nt", "nt"})',
    '"" or ["nt"]',
    'sys.platform.startswith(["win", "lin"])',
    'os.name in {"nt", []}',
    'platform.system == "Windows"',
    "len(platform.system) > 0",
    'platform.system < ""',
    "-1 in b'nt'",
]


@pytest.mark.parametrize("expr", _RM463_UNSOUND)
def test_rm463_evaluator_never_values_a_form_cpython_does_not(expr):
    _rm463_assert_faithful(expr, _rm463_model(expr), _rm463_cpython(expr))


# Round 2: a refusal carries NO truthiness, however obvious it looks. Each of
# these reached an enclosing expression as a truth value in round 1; the
# verifier showed `[[f()] or "a"]` read truthy while `f()` raises.
@pytest.mark.parametrize(
    "expr",
    [
        '["nt"]',
        "[]",
        '{"a", "a"}',
        "platform.system",
        '"" or ["nt"]',
        "sys.platform and []",
        '(["a"],)',
        "not []",
        "{[]}",
        "not len({[]})",
        '[[os.name] or "a"]',
        "-1 in b'nt'",
    ],
)
def test_rm463_refusal_carries_no_truthiness(expr):
    model = _rm463_model(expr)
    assert all(v is _REFUSED for v in model), (expr, model)
    m = _Model(_REPO_ROOT / "tests" / "test_mutant.py", f"import os\nimport sys\nimport platform\nX = ({expr})\n")
    assert _host_truth(m.tree.body[-1].value, m, m.tree) is None, expr


# MUST-FIX 3: a DEFINITE CPython raise over known operands is a refusal, not an
# unknown. As an unknown it kept its platform credit, so an always-raising gate
# classified CAPABILITY.
_RM463_DEFINITE_RAISES = [
    'os.name["a"]',
    "sys.platform[1.5]",
    'os.name[:"a"]',
    'os.name in b"nt"',
    "sys.platform < 1",
    "sys.platform.startswith(1)",
    "sys.platform.lower(1)",
    'os.name + 1 == "x"',
    "len(len(os.name)) > 0",
    "-os.name == 1",
    "os.name[::0]",
    "len(os.name)[0] == 2",
    'len(os.name).lower() == "x"',
    "os.name + 1",
    'os.name["a"] or shutil.which("git") is None',
]


@pytest.mark.parametrize("condition", _RM463_DEFINITE_RAISES)
def test_rm463_definite_cpython_raise_earns_no_credit(condition):
    expr = condition.split(" or shutil")[0]
    model, real = _rm463_model(expr), _rm463_cpython(expr)
    assert all(kind == "RAISE" for kind, _ in real), (expr, real)
    assert all(v is _REFUSED for v in model), (expr, model)
    got = _rm463_verdicts(condition)
    assert got and all(v != CAPABILITY and not ex for v, ex in got), (condition, got)


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("os.name[3]", [_REFUSED, "i"]),
        ('sys.platform.startswith(("win", 1))', [True, _REFUSED]),
        ('sys.platform + "x"', [_UNKNOWN, _UNKNOWN]),  # a BinOp is never valued
        ('os.name < "o"', [True, False]),
    ],
)
def test_rm463_raise_is_per_host_and_success_keeps_its_value(expr, expected):
    """Control: a host where CPython succeeds keeps its exact value."""
    model = _rm463_model(expr)
    _rm463_assert_faithful(expr, model, _rm463_cpython(expr))
    assert model == expected, (expr, model)


def test_rm463_unknown_key_is_not_a_definite_raise():
    src = "import os\nX = os.name[_k()]\n"
    m = _Model(_REPO_ROOT / "tests" / "test_mutant.py", src)
    assert _host_values(m.tree.body[-1].value, m, m.tree) == [_UNKNOWN, _UNKNOWN]


# MUST-FIX 1: the verifier's 17 round-1 acceptances. Each was DEFECT at
# 23e20e810 and CAPABILITY at the round-1 head, because a refusal handed a
# truthiness through a BoolOp whose other operand could raise.
_RM463_V4_PRELUDE = "L = ['a']\nE = []\nT = ('nt',)\nB = b'nt'\nZ = 0\nN = None\ndef f():\n    raise ValueError('x')\n"
_RM463_V4_REFUTATIONS = [
    '(not ([((f(),) or [E])] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([(0 or {L} and 0)] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([(E or {f()} and E)] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([([] or f() and [])] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([([f()] and 0)] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([([f()] or -1)] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([([f()] or 1)] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([(f() or L)] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([(f() or platform.system)] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([({f()} and None)] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([({f()} or "nt")] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([({f()} or ([],))] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([({f()} or [E])] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([({f()} or [platform.system])] and 1) and not TR.exists()) or shutil.which("git") is None',
    '(not ([({f()} or b"nt")] and 1) and not TR.exists()) or shutil.which("git") is None',
    "(not ([[f()] or 'a']) and not TR.exists()) or shutil.which(\"git\") is None",
    "(not ([[os.getenv('X')[0]] or 'a']) and not TR.exists()) or shutil.which(\"git\") is None",
]


@pytest.mark.parametrize("condition", _RM463_V4_REFUTATIONS)
def test_rm463_round1_truth_carrying_refusal_acceptances_stay_refused(condition):
    src = _RM463_HDR + _RM463_V4_PRELUDE + f"@pytest.mark.skipif({condition}, reason='h')\ndef test_x():\n    pass\n"
    got = [(f.verdict, _excused(f)) for f in scan_source("tests/test_mutant.py", src)]
    assert got == [(DEFECT, False)], (condition, got)


# Control: the sound half stays folded, so the test above cannot pass by the
# evaluator refusing everything.
_RM463_SOUND = [
    "len(sys.platform)",
    "os.name[-1]",
    "sys.platform[:3]",
    'sys.platform.startswith(("win", "lin"))',
    'str(("nt", 1))',
    '(os.name, 1) == ("nt", 1)',
    "not os.name[:0]",
    'platform.system().lower() in ("windows", "linux")',
]


@pytest.mark.parametrize("expr", _RM463_SOUND)
def test_rm463_sound_folds_are_kept_and_match_cpython(expr):
    model, real = _rm463_model(expr), _rm463_cpython(expr)
    assert all(_rm463_is_value(v) for v in model), (expr, model)
    assert [("V", v) for v in model] == real
    assert [repr(v) for v in model] == [repr(w) for _, w in real]


_RM463_HDR = """
import os
import sys
import shutil
import platform
import importlib.util
import pytest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TR = ROOT / "core" / "match_db.py"
HOSTS = ["win32", "linux"]
PLAT = sys.platform
"""


def _rm463_verdicts(condition: str) -> list:
    src = _RM463_HDR + f"@pytest.mark.skipif({condition}, reason='h')\ndef test_x():\n    pass\n"
    return [(f.verdict, _excused(f)) for f in scan_source("tests/test_mutant.py", src)]


# Mutation / positive controls: each laundered a tracked-file arm at 23e20e810.
# The unsound fold valued the left arm constant-FALSE, so it was dropped as
# never firing and the `shutil.which` arm made the site CAPABILITY. In CPython
# the arm fires (or raises), so the tracked check is live and the site is DEFECT.
_RM463_LAUNDERED = {
    "str_of_empty_list": 'str([]) != "()"',
    "list_vs_tuple": "[] != ()",
    "set_superset": 'not ({"b"} > {"a", "z"})',
    "len_of_unhashable_set": "not len({[]})",
    "bare_platform_system_attribute": 'platform.system < ""',
}


@pytest.mark.parametrize("name", sorted(_RM463_LAUNDERED))
def test_rm463_removed_fold_no_longer_launders_a_tracked_arm(name):
    arm = _RM463_LAUNDERED[name]
    cond = f'({arm} and not TR.exists()) or shutil.which("git") is None'
    assert _rm463_verdicts(cond) == [(DEFECT, False)], name


def test_rm463_a_sound_constant_false_arm_is_still_dropped():
    """Control: the arm-dropping machinery still works when the fold is sound."""
    cond = '(os.name[:0] != "" and not TR.exists()) or shutil.which("git") is None'
    assert _rm463_verdicts(cond) == [(CAPABILITY, False)]


# Refused at 23e20e810 THROUGH a removed fold (it valued them constant-true).
# Removal alone would hand the bare platform read its credit back and accept
# them; the `_REFUSED` taint keeps every one out.
_RM463_NO_NEW_ACCEPTANCE = [
    'sys.platform in ["win32", "linux"]',
    'os.name in {"nt", "posix"}',
    "sys.platform in HOSTS",
    "len([sys.platform]) == 1",
    'sys.platform.startswith(["win", "lin"])',
    "len(platform.system) > 0",
    "platform.system",
    'sys.platform in ("win32",) or ["x"]',
    'not (os.name not in ["nt", "posix"])',
    # Short-circuit through a refusal. A draft whose taint withheld only the
    # platform credit accepted every one of these; the refusal now carries no
    # truthiness, so the taint withholding ALL capability credit is what holds.
    '(os.getenv("X") in ["a"] or True) and not TR.exists()',
    'os.getenv("X") or ["a"]',
    'os.getenv("X") in ["a"] and False',
    'os.getenv("X") or (["a"],)',
    'not not (os.getenv("X") in ["a"] and False)',
    'os.getenv("X") or {"a"}',
    'os.getenv("X") or platform.system',
    '(os.getenv("X") or ["a"]) and not TR.exists()',
    '(["a"] or sys.platform) == "win32"',
    # A raising display reached only when the probe does not short-circuit:
    # it either skips or errors, so it is still constant-true where it runs.
    'os.getenv("X") or {([],)}',
    '((os.getenv("X") or {[]}) and not TR.exists()) or shutil.which("git") is None',
    # Found by a widened adversarial corpus (probe x display x shape): the old
    # fold decided these (`len([])` is 0; `{[]}` was valued truthy), so no
    # capability under a refusal may make them acceptable.
    'len([]) and os.getenv("X")',
    '{[]} or os.getenv("X")',
    '[{[]}] or shutil.which("git")',
    '({([],)} or os.getenv("X")) and not TR.exists()',
    'os.getenv("X") or {[]}',
    # Documented cost: a genuine env gate compared against a list display is
    # refused too - spell the display as a tuple.
    'sys.platform == "win32" and os.getenv("X") in ["1"]',
]


@pytest.mark.parametrize("condition", _RM463_NO_NEW_ACCEPTANCE)
def test_rm463_removed_fold_does_not_create_an_acceptance(condition):
    got = _rm463_verdicts(condition)
    assert got and all(v != CAPABILITY and not ex for v, ex in got), (condition, got)


def test_rm463_the_tuple_spelling_is_still_constant_true():
    """Control: the strict half - a tuple literal still folds and convicts."""
    assert _rm463_verdicts('sys.platform in ("win32", "linux")') == [(DEFECT, False)]


# (2) A capability probe fed a platform read launders the RM-458 taint: the
# wrapper drops the platform credit, and the probe re-supplies binary / env /
# optional-import credit for what is still a question about the platform.
_RM463_PROBE_LAUNDERING = [
    "bool(shutil.which(sys.platform))",
    "bool(shutil.which(cmd=sys.platform))",
    "bool(shutil.which(PLAT))",
    'f"{shutil.which(sys.platform)}" != "None"',
    "bool(os.environ.get(sys.platform))",
    "bool(os.environ[os.name])",
    "bool(os.getenv(os.name))",
    "bool(importlib.util.find_spec(os.name))",
    'min(os.getenv(sys.platform, "a"))',
]


@pytest.mark.parametrize("condition", _RM463_PROBE_LAUNDERING)
def test_rm463_capability_probe_cannot_launder_a_tainted_platform_read(condition):
    got = _rm463_verdicts(condition)
    assert got and all(v != CAPABILITY and not ex for v, ex in got), (condition, got)


@pytest.mark.parametrize(
    "condition",
    [
        'bool(shutil.which("git"))',
        'bool(os.environ.get("CI"))',
        'bool(os.getenv("CI"))',
        'bool(importlib.util.find_spec("numpy"))',
        # RM-466 MOVED, not deleted: `shutil.which(sys.platform)` used to sit
        # here as "an UNWRAPPED platform-named probe still reads the platform,
        # as it did at base". RM-466 makes the probe-laundering refusal
        # unconditional, so it is now refused with the rest of its class and is
        # pinned in `_RM466_LAUNDERED` below. Strict direction: an acceptance
        # became a refusal, which is the only direction allowed here.
        'sys.platform == "win32" and os.getenv("X") in ("1",)',
    ],
)
def test_rm463_probe_controls_keep_their_capability(condition):
    """A probe on a literal keeps its credit under a wrapper."""
    assert _rm463_verdicts(condition) == [(CAPABILITY, False)]


# --------------------------------------------------------------------------- #
# RM-466: probe-laundering bypasses the RM-463 taint does not reach
# --------------------------------------------------------------------------- #
# RM-463 refused a capability probe fed a platform read, but ONLY inside an
# existing refusal taint, and only for the four `_PROBE_CREDITS`. Four of the
# six known bypasses carry no wrapper at all, so no taint is ever entered, and
# a network call earns a credit the taint never clears. The class is closed by
# REFUSAL in three strictly-narrowing steps, never by widening what is
# accepted: the check no longer needs a taint to fire, the set of shapes
# recognised as a PROBE grows (recognising more probes can only withhold more
# credit - it is never a grant), and the withheld set gains `network`.
_RM466_HDR = _RM463_HDR + "import socket\n"


def _rm466_verdicts(condition: str) -> list:
    src = _RM466_HDR + f"@pytest.mark.skipif({condition}, reason='h')\ndef test_x():\n    pass\n"
    return [(f.verdict, _excused(f)) for f in scan_source("tests/test_mutant.py", src)]


_RM466_LAUNDERED = [
    # The six shapes named in the row.
    "bool(sys.platform in os.environ)",
    "min(sys.platform in os.environ, 1)",
    "dict(os.environ).get(sys.platform)",
    "os.environ.copy().get(sys.platform)",
    "socket.gethostbyname(sys.platform)",
    'str(os.getenv(sys.platform)) != "None"',
    # Siblings of each, found by varying the wrapper, the probe and the read.
    "sys.platform not in os.environ",
    "os.name in os.environ",
    "bool(dict(os.environ).get(sys.platform))",
    "len(os.environ.copy().get(os.name, ()))",
    "socket.gethostbyname(os.name)",
    "urllib.request.urlopen(sys.platform)",
    'os.getenv(sys.platform, "a")',
    'os.environ.get(f"RC_{sys.platform}")',
    "dict(os.environ)[sys.platform]",
    "shutil.which(sys.platform)",
]


@pytest.mark.parametrize("condition", _RM466_LAUNDERED)
def test_rm466_laundered_platform_read_earns_no_capability(condition):
    got = _rm466_verdicts(condition)
    assert got and all(v != CAPABILITY and not ex for v, ex in got), (condition, got)


_RM466_CONTROLS = [
    'bool("CI" in os.environ)',
    '"CI" in os.environ',
    'dict(os.environ).get("CI")',
    'os.environ.copy().get("CI")',
    'dict(os.environ)["CI"]',
    'socket.gethostbyname("localhost")',
    'urllib.request.urlopen("http://localhost")',
    'str(os.getenv("CI")) != "None"',
    'len(os.environ.copy().get("CI", ()))',
]


@pytest.mark.parametrize("condition", _RM466_CONTROLS)
def test_rm466_the_same_probe_on_a_literal_keeps_its_capability(condition):
    """Negative control: the refusal is aimed at the laundered PLATFORM read,
    not at environment, network or copy shapes in general."""
    assert _rm466_verdicts(condition) == [(CAPABILITY, False)]


# --------------------------------------------------------------------------- #
# RM-467: definite-raise credit residuals
# --------------------------------------------------------------------------- #
# RM-463 round 2 made a definite CPython raise over KNOWN operands a refusal
# for compare, known-key subscript, str methods, 1-arg `len`, unary minus and
# binary + / -. Everything else still fell through to `_UNKNOWN`, which keeps
# its platform credit, so a gate that can only raise graded CAPABILITY.
#
# The rule here is narrow on purpose: a raise is recorded only where every
# operand is KNOWN on at least one host. An UNKNOWN operand is never read as a
# raise - that would convict on a guess. Nothing new is VALUED: where CPython
# succeeds the answer stays `_UNKNOWN`, or `_REFUSED` where the evaluator
# declines to model the result at all (`str(2)`, a list from `split`).
_RM467_RAISING = [
    "len(os.name, 1) > 0",
    'str(os.name, 1) == "nt"',
    'os.name * "a"',
    'os.name % "a"',
    'os.name ** "a"',
    'os.name / "a"',
    "~os.name",
    "+os.name",
    "sys.platform()",
    "sys.platform.nonexistent",
    "int(os.name)",
    "os.name.split()[5]",
    '{"nt": 1}[os.name]',
    "str(len(os.name)) + 1",
]


@pytest.mark.parametrize("expr", _RM467_RAISING)
def test_rm467_a_definite_cpython_raise_is_refused_not_unknown(expr):
    real, model = _rm463_cpython(expr), _rm463_model(expr)
    assert any(kind == "RAISE" for kind, _ in real), (expr, real)
    for got, (kind, want) in zip(model, real):
        if kind == "RAISE":
            assert got is _REFUSED, f"{expr}: modelled {got!r}, CPython raises {want}"
    # Where CPython succeeds the evaluator must still not have invented a value.
    _rm463_assert_faithful(expr, model, real)


# `os.name["a"]` raises wherever it is reached, but the IfExp test is UNKNOWN,
# so the arm's reachability is not known - the refusal comes from "either arm
# may be evaluated", the same reading the BoolOp already uses.
_RM467_DEFECTS = [*_RM467_RAISING, 'os.name["a"] if shutil.which("git") else 1']


@pytest.mark.parametrize("condition", _RM467_DEFECTS)
def test_rm467_a_gate_that_can_only_raise_earns_no_credit(condition):
    got = _rm466_verdicts(condition)
    assert got and all(v != CAPABILITY and not ex for v, ex in got), (condition, got)


_RM467_CONTROLS = [
    'str(os.name) == "nt"',
    'sys.platform.startswith("win")',
    'sys.platform.lower() != "linux"',
    'os.name[0] == "n"',
    'os.name + "x" != "y"',
    'os.name * 2 != "x"',
    "len(os.name) > 3",
    'int(os.getenv("N", "1")) > 0',
    'os.name["a"] if False else shutil.which("git")',
]


@pytest.mark.parametrize("condition", _RM467_CONTROLS)
def test_rm467_a_gate_cpython_does_not_raise_on_keeps_its_capability(condition):
    """Negative control: only a DEFINITE raise over known operands refuses.

    The last row is the IfExp discriminator - with a KNOWN test only the taken
    arm decides, so the refused arm is unreachable and supplies nothing.
    """
    assert _rm466_verdicts(condition) == [(CAPABILITY, False)]


@pytest.mark.parametrize(
    "expr",
    [
        'os.name + "x"',
        "os.name * 2",
        'str(os.getenv("X"))',
        "int(len(os.name))",
        'os.name.split("t")',
    ],
)
def test_rm467_a_call_that_succeeds_is_never_newly_valued(expr):
    """No new fold: every added raise probe returns `_UNKNOWN` or `_REFUSED`
    where CPython succeeds, never the value CPython computes."""
    assert all(not _plain(v) for v in _rm463_model(expr)), expr


def test_rm467_a_conditional_expression_inherits_a_refused_arm():
    """The ONE real-site difference this change makes, pinned deliberately.

    `tests/test_vision_anchor_model_rm26.py:81` binds
    `list(d.glob(...)) if d.is_dir() else []`. With the test UNKNOWN both arms
    are reachable, so the `[]` display - refused since RM-463 because a list is
    not modelled - now taints the conditional, exactly as it already would
    inside a BoolOp. The site's VERDICT is unchanged (CAPABILITY, on the
    untracked directory it names); what it loses is the glob chain as
    evidence. Strict direction, and the documented RM-463 cost: spell a
    display in a gate as a tuple.
    """
    src = "import os\nX = (os.getenv('A') if _t() else [])\n"
    m = _Model(_REPO_ROOT / "tests" / "test_mutant.py", src)
    assert _host_values(m.tree.body[-1].value, m, m.tree) == [_REFUSED, _REFUSED]
    tup = _Model(_REPO_ROOT / "tests" / "test_mutant.py", "import os\nX = (os.getenv('A') if _t() else ())\n")
    assert _host_values(tup.tree.body[-1].value, tup, tup.tree) == [_UNKNOWN, _UNKNOWN]


def test_rm467_an_unknown_operand_is_never_read_as_a_raise():
    """`os.name[_k()]` and `os.name * _n()` cannot be proved to raise."""
    for src in ("X = os.name[_k()]", "X = os.name * _n()", "X = ~_n()", "X = _f()()"):
        m = _Model(_REPO_ROOT / "tests" / "test_mutant.py", f"import os\n{src}\n")
        assert _host_values(m.tree.body[-1].value, m, m.tree) == [_UNKNOWN, _UNKNOWN], src


def test_rm467_boolop_truth_over_an_unknown_operand_is_recorded_not_refused():
    """DECISION (RM-467, the `_Truth` half): an UNKNOWN operand does NOT refuse
    the BoolOp, and `"" or f() and ""` still reads falsy although `f()` raises.

    The row asks for a decision either way. Refusing here would read an unknown
    as a raise, which the same row forbids. The residual unsoundness runs in
    the STRICT direction only: a BoolOp with one truth value on every host is
    a constant, and `_collect` returns on a constant BEFORE any credit is
    taken, so the site can only lose credit, never gain it - which the verdict
    assertion below pins.
    """
    src = 'import os\nimport shutil\ndef f():\n    raise ValueError("x")\nX = ("" or f() and "")\n'
    m = _Model(_REPO_ROOT / "tests" / "test_mutant.py", src)
    assert _host_truth(m.tree.body[-1].value, m, m.tree) is False
    got = _rm466_verdicts('("" or f() and "") and os.getenv("X")')
    assert got and all(v != CAPABILITY for v, _ in got), got
