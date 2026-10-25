"""tft/rounds - the per-round TFT store (docs/TFT_PROGRAM.md sections 1-2, slice TFT-01).

Every on-screen TFT category, saved per round with a confidence + source
envelope per value, in gitignored `data/tft/tft_rounds.db` (stdlib sqlite3,
WAL, one writer thread). LLM-free. `schema` holds the contract (tables, closed
enums, migrations); `store` holds the writer / read / export API.
"""
from tft.rounds.schema import SCHEMA_VERSION, SRC_VALUES  # noqa: F401
from tft.rounds.store import (  # noqa: F401
    Env,
    RoundStore,
    ScrubError,
    default_db_path,
    load_salt,
    player_key,
    scrub_violations,
)
