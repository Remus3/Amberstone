import py_compile
import shutil
import os
files = {
    "tft/tft_vision_reader.py":  "ops/staging/tft/tft_vision_reader.py",
    "tft/tft_live_analysis.py":  "ops/staging/tft/tft_live_analysis.py",
    "tft/tft_coach_engine.py":   "ops/staging/tft/tft_coach_engine.py",
}
ok = True
for src, dst in files.items():
    try:
        py_compile.compile(src, doraise=True); print(f"OK {src}")
    except py_compile.PyCompileError as e:
        print(f"FAIL {src}: {e}"); ok = False
if ok:
    for src, dst in files.items():
        os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(src, dst)
    print("STAGED OK")
else:
    print("STAGE ABORTED")
