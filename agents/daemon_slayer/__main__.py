"""Enable ``python -m agents.daemon_slayer ...``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
