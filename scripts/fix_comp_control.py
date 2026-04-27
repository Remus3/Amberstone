"""Fix orphaned return False in comp_control.py after patch."""
from pathlib import Path

f = Path(r"C:\Riot Commander\tft\comp_control.py")
content = f.read_text(encoding="utf-8")

# Remove the orphaned indented return False that got left behind
BAD = "_lcu_import_team_code = _lcu_import_units  # backwards compat alias\n\n        return False\n\ndef _lcu_get_team_id"
GOOD = "_lcu_import_team_code = _lcu_import_units  # backwards compat alias\n\ndef _lcu_get_team_id"

if BAD in content:
    content = content.replace(BAD, GOOD)
    print("Fixed orphaned return False")
else:
    # Try to find what's actually there
    idx = content.find("_lcu_import_team_code = _lcu_import_units")
    if idx >= 0:
        snippet = content[idx:idx+200]
        print("Context:", repr(snippet))
    else:
        print("Alias not found either")

f.write_text(content, encoding="utf-8")
print("Done.")
