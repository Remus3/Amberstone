import os
import stat
from pathlib import Path

def main():
    repo_root = Path(__file__).resolve().parent.parent
    hook_dir = repo_root / ".git" / "hooks"
    if not hook_dir.exists():
        print("Not a git repository.")
        return
    
    hook_path = hook_dir / "pre-commit"
    hook_content = """#!/bin/sh
echo "Running Share/ mirror sync..."
python tools/ds_share_sync.py

# Stage any changes the sync script made to the Share/ directory
git add Share/
"""
    hook_path.write_text(hook_content, encoding="utf-8")
    
    # Make executable
    st = os.stat(hook_path)
    os.chmod(hook_path, st.st_mode | stat.S_IEXEC)
    print("Installed pre-commit hook to automate Share/ sync.")

if __name__ == "__main__":
    main()
