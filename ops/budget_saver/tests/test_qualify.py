import importlib.util
import pathlib
spec = importlib.util.spec_from_file_location("qualify", pathlib.Path(__file__).resolve().parents[1] / "qualify.py")
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)

def test_oracle_py_exec_pass():
    code = "def slug(s):\n    return s.lower().replace(' ','-')\n"
    assert q.grade({"kind":"py_exec","call":"slug('Hello World')","expect":"hello-world"}, code) is True
def test_oracle_py_exec_fail():
    assert q.grade({"kind":"py_exec","call":"slug('Hi There')","expect":"hi-there"}, "def slug(s): return s") is False
