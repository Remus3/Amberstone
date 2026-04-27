# RIOT COMMANDER — TFT OVERHAUL DESIGN DOCUMENT
# Created: 2026-04-09

## SUMMARY
Replace 3 empty panels (PENCIL/GRAPH/RESERVED) with 2 functional panels:
1. COMP CONTROL — meta comp selector with emblem awareness
2. CHAMP/ITEM CONTROL — BIS items with built-state tracking

Modify bottom strip:
- Center: Final build (Lv9) with green outlines for owned units
- Right: Split Lv4 (left) / Lv7 (right) with red divider

## META DATABASE: data/meta/tft_set17_meta.json (created)
- 7 S-tier, 8 A-tier, 6 B-tier, 5 C-tier comps
- Full BIS items + alt items per carry
- Lv4/Lv7/Lv9 positioning per comp
- Leveling plans (fast_8, fast_9, lv5/6/7_slowroll)
- Emblem value per comp
- Item component recipes
