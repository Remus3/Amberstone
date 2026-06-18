"""Registry for mapping alternative game modes to coach modules and policies.
Extracted from app/_game_lifecycle.py (D5)."""

MODE_COACH_MAP = {
    "_tft_mode":   ("coaches.tft_coach",   "Coach", "tft_coaching_data.json"),
    "_arena_mode": ("coaches.arena_coach",  "Coach", "arena_coaching_data.json"),
    "_brawl_mode": ("coaches.brawl_coach",  "Coach", "brawl_coaching_data.json"),
    "_aram_mode":  ("coaches.aram_coach",   "Coach", "aram_coaching_data.json"),
}

MODE_POLICY_MAP = {
    "_tft_mode":   ("tft",   "live_coaching"),
    "_arena_mode": ("arena", "live_coaching"),
    "_brawl_mode": ("brawl", "live_coaching"),
    "_aram_mode":  ("aram",  "live_coaching"),
}
