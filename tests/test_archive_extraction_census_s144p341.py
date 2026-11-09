"""S144-P-341 - every production archive extraction is a named, reasoned site, and a tar one passes ``filter="data"``.

Unpacking an archive writes files at paths the archive chose: a member named ``../x`` or an absolute path, a link that
points out of the target, or a device node, lands outside the directory the caller meant (CWE-22, "zip slip" / "tar
slip"). The S144-P-316 unsafe-call census covers ``pickle`` / ``eval`` / ``shell=True``; ruff S202 sees only a literal
``tarfile.extractall`` with no filter. Neither names the ZIP and ``shutil`` shapes, so the set was unmeasured.

Measured 2026-11-07 by AST over every tracked production ``.py`` (outside ``tests/``, ``docs/`` and the vendored
``ops/fleet_kit/``): 3 extraction sites in 3 files, listed in ``_SITES`` with the archive kind, the scope they sit in and
why each is safe. ``ops/launcher/updater.py`` unpacks by hand, member by member, after its own checks (no ``extractall``),
so it is not a site.

Detector: a call of ``.extractall(...)`` or ``.extract(...)`` (receiver other than ``self`` / ``cls``, so a class's own
``extract`` method is not a hit), or of ``shutil.unpack_archive`` (resolved through the file's own imports). A hit is keyed
``(file, scope, call)``: scope is ``"module"`` or the enclosing function's dotted qualname. The set is exact: a new site
fails until it is added with a reason, and a site that goes away must be dropped.

Rule on top of the census: a site registered as ``tar`` must pass the keyword ``filter="data"`` (the stdlib's safe preset:
no absolute or escaping path, no link out of the target, no device node, modes stripped). Python 3.12-3.13 default to the
unsafe ``fully_trusted`` filter, so the keyword is the version-independent spelling. A ZIP site has no such keyword;
``ZipFile.extractall`` itself drops ``..`` components and drive letters from a member name, and ``extract_embed`` also
refuses an escaping name up front.

Named blind spots (measured absent from the tree 2026-11-07, so not a live gap): an archive library other than zipfile /
tarfile / shutil (``py7zr``, ``rarfile``, an ``os.system("tar ...")``), a ``ZipFile.open`` + manual write loop (the
updater's pattern, which carries its own member checks), a method reached through ``getattr``, a ``self.extractall`` on a ZipFile / TarFile subclass (the ``self`` / ``cls`` receiver
rule skips it), and a file that fails to
parse (skipped, as in the sibling censuses).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")

# (file, scope, call) -> (archive kind, why this extraction is safe where it is).
_SITES = {
    ("tools/build_python_embed.py", "extract_embed", "extractall"): (
        "zip",
        "build-time unpack of the pinned, hash-checked CPython embeddable zip; every member name is resolved against the "
        "target and refused with EmbedError if it escapes, before extractall runs",
    ),
    ("tools/inbox_responder_export.py", "ensure_export", "extractall"): (
        "tar",
        "unpacks `git archive` output of the operator's own repo into a private .tmp- directory, with filter='data' and a "
        "size cap checked first; the directory is renamed into place only after a clean extract",
    ),
    ("tools/run_packaged_smoke.py", "run", "extractall"): (
        "zip",
        "operator CLI smoke check: unpacks the portable bundle this tree just built into a fresh mkdtemp directory it "
        "removes afterwards; PKG-owned file, so no containment check is added here (ZipFile.extractall sanitises names)",
    ),
}

_CALLS = frozenset({"extractall", "extract"})


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Name):
        return node.id
    return None


def _aliases(tree: ast.AST) -> dict[str, str]:
    """local name -> the dotted path it stands for, from this file's own imports."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _resolve(name: str, aliases: dict[str, str]) -> str:
    head, _, rest = name.partition(".")
    real = aliases.get(head, head)
    return f"{real}.{rest}" if rest else real


def _filter_value(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "filter":
            return kw.value.value if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str) else "<dynamic>"
    return None


def _scan(source: str) -> list[tuple[int, str, str, str | None]]:
    """``(lineno, scope, call, filter)`` per extraction call; filter is the ``filter=`` keyword's literal or None."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    hits: list[tuple[int, str, str, str | None]] = []

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            s = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                s = [*scope, child.name]
            if isinstance(child, ast.Call):
                f = child.func
                where = ".".join(s) or "module"
                if isinstance(f, ast.Attribute) and f.attr in _CALLS:
                    recv = _dotted(f.value)
                    if recv not in {"self", "cls"}:
                        hits.append((child.lineno, where, f.attr, _filter_value(child)))
                else:
                    d = _dotted(f)
                    if d is not None and _resolve(d, aliases) == "shutil.unpack_archive":
                        hits.append((child.lineno, where, "unpack_archive", _filter_value(child)))
            visit(child, s)

    visit(tree, [])
    return sorted(hits, key=lambda h: h[:3])


def _production_files():
    return [p for p in repo_files(REPO_ROOT, ("*.py",))
            if not relative_posix(p).startswith(_SKIP_PREFIXES) and "/tests/" not in relative_posix(p)]


def _measure():
    found: dict[tuple[str, str, str], str | None] = {}
    for p in _production_files():
        rel = relative_posix(p)
        try:
            hits = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for _line, scope, call, flt in hits:
            found[(rel, scope, call)] = flt
    return found


def test_every_production_archive_extraction_is_a_named_site():
    assert len(_production_files()) > 100, "the tracked-file walk returned almost nothing"
    found = _measure()
    assert len(found) >= 2, "the walk saw almost no site, so an empty difference proves nothing"
    new = sorted(set(found) - set(_SITES))
    gone = sorted(set(_SITES) - set(found))
    assert not new, (
        "new archive extraction (add it to _SITES with a reason; a tar one needs filter='data'): " + repr(new))
    assert not gone, f"stale _SITES entry (drop it): {gone}"


def test_every_tar_extraction_passes_the_data_filter():
    found = _measure()
    bad = sorted(k for k, flt in found.items() if _SITES.get(k, ("", ""))[0] == "tar" and flt != "data")
    assert not bad, f"a tar extractall without filter='data': {bad}"
    assert any(_SITES[k][0] == "tar" for k in found if k in _SITES), "no tar site seen, so the filter rule proved nothing"


def test_every_site_carries_a_kind_and_a_reason():
    assert all(kind in {"zip", "tar"} and len(why) > 40 for kind, why in _SITES.values())


def test_the_detector_flags_each_shape():
    cases = {
        "import zipfile\nwith zipfile.ZipFile('a') as z:\n    z.extractall('d')\n": [(3, "module", "extractall", None)],
        "import tarfile\ndef f(t):\n    t.extractall('d', filter='data')\n": [(3, "f", "extractall", "data")],
        "def f(t, n):\n    t.extract(n, 'd')\n": [(2, "f", "extract", None)],
        "import shutil\ndef f():\n    shutil.unpack_archive('a', 'd')\n": [(3, "f", "unpack_archive", None)],
        "from shutil import unpack_archive as ua\nua('a', 'd')\n": [(2, "module", "unpack_archive", None)],
        "import shutil as sh\nsh.unpack_archive('a', 'd')\n": [(2, "module", "unpack_archive", None)],
        "class C:\n    def m(self, t):\n        t.extractall('d', filter=f)\n": [(3, "C.m", "extractall", "<dynamic>")],
        "def f(t):\n    t.extractall('d', filter='fully_trusted')\n": [(2, "f", "extractall", "fully_trusted")],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_the_detector_ignores_a_class_own_method_and_look_alikes():
    clean = (
        "doc = 'z.extractall(d)'\n"
        "# z.extractall('d')\n"
        "class C:\n"
        "    def extract(self, x):\n"
        "        return self.extract(x)\n"
        "    def run(self):\n"
        "        return self.extractall()\n"
        "def extract_embed(a):\n"
        "    return extractall_names(a)\n"
        "import zipfile\n"
        "names = zipfile.ZipFile('a').namelist()\n"
    )
    assert _scan(clean) == []


def test_the_filter_rule_catches_a_missing_or_weak_filter():
    # Positive control for the rule itself: the scan reports None / a non-"data" literal, which the census test rejects.
    assert _scan("def f(t):\n    t.extractall('d')\n")[0][3] is None
    assert _scan("def f(t):\n    t.extractall('d', filter='tar')\n")[0][3] == "tar"
