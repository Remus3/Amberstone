"""Pin: an empty parametrize list must fail at collection, not skip.

Without this, a guard parametrized over a data table (for example the
cross-repo digest check over ``sorted(SHARED_SHA256)`` in
``tests/test_loop_concurrency.py``) silently degrades to a skip when the table
is emptied, and a skip reads as green. The option lives in ``pytest.ini``.

Three distinct failure modes, and they come apart - which is why this file
carries both a string check and a behavioural probe:

1. the ini line is deleted            -> caught by the string assertion
2. pytest never finds ``pytest.ini``  -> caught by the string assertion, since
   ``getini`` then returns the built-in default (``skip``)
3. pytest changes what the value DOES, or a future version keeps returning the
   value from ``getini`` while ignoring it -> caught ONLY by a real
   behavioural probe, because reading the value back proves the STRING IS
   PRESENT, not that the BEHAVIOUR HOLDS

Measured 2026-09-30 on pytest 9.0.3 / CPython 3.14.4 (win32).
"""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# The probe module. Parametrized over an EMPTY list, so the ini value decides
# whether collecting it is an error or a skip. The body must never execute.
_PROBE_SOURCE = '''import pytest


@pytest.mark.parametrize("value", [])
def test_probe_body(value):
    raise AssertionError("the probe body must never execute")
'''

_PROBE_MODULE_NAME = "test_probe_empty.py"
_PROBE_REPORT_NAME = "report.xml"


def _build_probe_tree(tmp_path, ini_value):
    """Lay down a self-contained probe tree and return its directory.

    The tree carries its OWN ``pytest.ini``, which is how the two arms are
    guaranteed to differ only by the ``-o`` override. See ``_run_probe``.
    """
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "pytest.ini").write_text(
        f"[pytest]\nempty_parameter_set_mark = {ini_value}\n",
        encoding="ascii",
    )
    (probe_dir / _PROBE_MODULE_NAME).write_text(_PROBE_SOURCE, encoding="ascii")
    return probe_dir


def _run_probe(probe_dir, *extra_args):
    """Run the probe module in a subprocess. Returns (returncode, output, testsuite).

    How the two arms are guaranteed to differ ONLY by the ``-o`` override:

    * Both arms call THIS function, so argv, cwd and environment are built by
      one code path; ``extra_args`` is the only input that differs.
    * The probe tree carries its own ``pytest.ini``. pytest anchors rootdir by
      searching upward from the args / cwd, and ``probe_dir`` sits under the
      session tmp dir, far outside the repo, so RC's own ``pytest.ini`` is
      never a candidate in EITHER arm. That is asserted below off the
      ``rootdir:`` and ``configfile:`` header lines rather than assumed - if
      RC's ini were in play, the control arm would be meaningless.
    * ``PYTEST_ADDOPTS`` and ``PYTEST_PLUGINS`` are stripped, so an ambient
      ``-o empty_parameter_set_mark=...`` in the parent environment cannot
      reach in and decide the outcome for us.
    """
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    env.pop("PYTEST_CURRENT_TEST", None)

    popen_kwargs = {}
    if sys.platform == "win32":
        # Keep a console-subsystem child of a windowless parent from flashing.
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            _PROBE_MODULE_NAME,
            "-p",
            "no:cacheprovider",
            f"--junit-xml={_PROBE_REPORT_NAME}",
            *extra_args,
        ],
        cwd=str(probe_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        **popen_kwargs,
    )
    output = proc.stdout + proc.stderr

    # Prove the probe read its OWN ini, not RC's. Without this the control arm
    # could silently be testing the wrong config file.
    assert "configfile: pytest.ini" in output, output
    rootdir_lines = [ln for ln in output.splitlines() if ln.startswith("rootdir:")]
    assert len(rootdir_lines) == 1, output
    reported_rootdir = Path(rootdir_lines[0].split(":", 1)[1].strip())
    assert reported_rootdir.resolve() == probe_dir.resolve(), output

    report = probe_dir / _PROBE_REPORT_NAME
    assert report.is_file(), output
    root = ET.parse(report).getroot()
    testsuite = root if root.tag == "testsuite" else root.find("testsuite")
    assert testsuite is not None, output
    return proc.returncode, output, testsuite


def test_empty_parameter_set_fails_at_collect(pytestconfig):
    assert pytestconfig.getini("empty_parameter_set_mark") == "fail_at_collect"


def test_empty_parameter_set_mark_behaviourally_errors_at_collect(
    pytestconfig, tmp_path
):
    """The configured value must actually PRODUCE a collection error.

    Asserted on the collection-error outcome itself - a JUnit ``<error>``
    element whose text names the empty parameter set - never on a bare nonzero
    exit code, which any unrelated failure would also satisfy.
    """
    probe_dir = _build_probe_tree(
        tmp_path, pytestconfig.getini("empty_parameter_set_mark")
    )
    returncode, output, testsuite = _run_probe(probe_dir)

    assert testsuite.get("tests") == "1", output
    assert testsuite.get("errors") == "1", output
    assert testsuite.get("skipped") == "0", output
    assert testsuite.get("failures") == "0", output

    testcase = testsuite.find("testcase")
    assert testcase is not None, output
    error = testcase.find("error")
    assert error is not None, output
    assert testcase.find("skipped") is None, output
    # Only the empty-parametrize path emits this; an unrelated collection
    # failure (a bad import, say) would also be errors="1" but would not say so.
    assert "Empty parameter set" in (error.text or ""), output
    assert "Empty parameter set in 'test_probe_body'" in output, output
    # Measured as exit code 2 (INTERRUPTED). Kept loose on purpose: the JUnit
    # assertions above are the load-bearing ones.
    assert returncode != 0, output


def test_empty_parameter_set_probe_negative_control_skips(pytestconfig, tmp_path):
    """Negative control: the SAME probe must SKIP when the mark says ``skip``.

    This is what makes the probe above meaningful. Without it, a probe that
    errors for some reason unrelated to ``empty_parameter_set_mark`` - a broken
    probe module, a missing pytest, a bad argv, a plugin blowing up at
    collection - reads as the guard working. The control shows the error arm is
    caused by the setting and nothing else, because the only difference between
    the two runs is the ``-o`` override.
    """
    probe_dir = _build_probe_tree(
        tmp_path, pytestconfig.getini("empty_parameter_set_mark")
    )
    returncode, output, testsuite = _run_probe(
        probe_dir, "-o", "empty_parameter_set_mark=skip"
    )

    assert testsuite.get("tests") == "1", output
    assert testsuite.get("skipped") == "1", output
    assert testsuite.get("errors") == "0", output
    assert testsuite.get("failures") == "0", output

    testcase = testsuite.find("testcase")
    assert testcase is not None, output
    skipped = testcase.find("skipped")
    assert skipped is not None, output
    assert testcase.find("error") is None, output
    assert "empty parameter set" in (skipped.get("message") or ""), output
    assert returncode == 0, output
