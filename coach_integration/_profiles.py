# arch: SR champion profile constants + GAME_SENSE_VOCAB | section=coaching | frozen=no
"""Champion profiles, GENERIC_PROFILE, GAME_SENSE_VOCAB used by SR and non-SR coaches."""

try:
    from role_profiles import get_role_profile, aram_item_context, ARAM_ITEM_RULES
    HAS_ROLE_PROFILES = True
except Exception:  # noqa: BLE001
    HAS_ROLE_PROFILES = False
    def get_role_profile(champ, role="bot") -> str: return ""
    def aram_item_context(e, a, c) -> str: return ""
    ARAM_ITEM_RULES = ""

CHAMPION_PROFILES = {
    "Jinx": (
        "Jinx. Mechanics: flip Pow-Pow->Fishbones at objectives/grouped fights; "
        "passive reset = free second kill - always find the follow-up target. "
        "Spikes: Yun Tal (1 item), Runaan's (2-item AoE), IE (3-item crit cap). "
        "Positioning: absolute max range, front-to-back always. "
        "Ult: pick/cleanup at 30%+ HP targets; never the primary damage tool in fights. "
        "Exploit: super-long ult range confirms at 20%+ HP threshold."
    ),
    "Vayne": (
        "Vayne. Mechanics: Q before every auto for bonus damage; 3-stack Silver Bolts "
        "priority on tanks; Condemn wall-stun = 1.5s - know every wall near lane. "
        "Final Hour invis = reposition tool, not just a DPS cooldown. "
        "Spikes: BotRK (1-item), PD+BotRK (2-item sustained), IE (damage cap). "
        "Macro: play for late, avoid 5v5 before 3 items. "
        "Exploit: BotRK+3-stack = solo-kills any tank post-2-items."
    ),
    "Tristana": (
        "Tristana. Mechanics: stack E on tower for plates, on enemies for trade dmg; "
        "E reset from kills - commit only in reset windows; W (jump) = escape, not engage when behind. "
        "Spikes: Yun Tal (all-in burst), Stormrazor+IE (guaranteed proc combo). "
        "Macro: crash waves fast, abuse plate gold pre-14min, tower tempo control. "
        "Exploit: kill a tower in 2 waves at level 7+ with E stacked."
    ),
    "Caitlyn": (
        "Caitlyn. Mechanics: Headshot combos from trap hits and net shots; "
        "trap bushes pre-6 for zone deny; E (net) is also primary escape - never burn offensively with dive risk. "
        "Spikes: Hexoptics C44 (lane domination), IE (crit-cap finisher). "
        "Macro: zone with traps 30s before objective spawns; shove for plate gold. "
        "Exploit: Q bounce off minion standing behind enemy ADC."
    ),
    "Nilah": (
        "Nilah. Mechanics: all-in ONLY on confirmed CC chain; E (flip) = engage AND escape - "
        "never burn without CC locked. W reduces healing - priority vs sustain enemies. "
        "Passive shares assists - value grouped play over split dueling. "
        "Spikes: BotRK (1-item), Bloodthirster (sustain), Phantom Dancer (crit + MS). "
        "Macro: force 2v2s, avoid extended poke. "
        "Exploit: E to a tagged enemy ignores terrain - use through walls."
    ),
    "Miss Fortune": (
        "Miss Fortune. Mechanics: E (rain) slows first, then ult for guaranteed full channel; "
        "ult angle = perpendicular to enemy team, from behind cover; Strut MS - don't take hits. "
        "Spikes: Lethality first (poke dominance), Lord Dominik's (vs tanks). "
        "Macro: group for objectives, punish in MF ult-angle windows. "
        "Exploit: Q bounce target = minion standing directly behind enemy ADC."
    ),
    "Lucian": (
        "Lucian. Mechanics: Trinity Force Spellblade procs on every Q - Q fires Spellblade "
        "AND Lightslinger simultaneously (3 hits per ability cycle). "
        "E (Relentless Pursuit) is the repositioning tool - keep it for engage AND escape. "
        "Never use RFC - he gaps-close and bursts, does not siege. "
        "Spikes: Trinity Force (Spellblade burst), Essence Reaver (mana + CDR), Navori (E refresh). "
        "Macro: dash in on isolated carry, burst, dash out before peel arrives. "
        "Exploit: Q activates Spellblade AND Lightslinger: Q-proc + empowered auto + second auto."
    ),
    "Ezreal": (
        "Ezreal. Mechanics: Q (Mystic Shot) reduces all CDs by 1.5s - spam every wave for haste. "
        "Trinity Force Spellblade on Q for bonus damage. Manamune stacks via Q spam. "
        "Arcane Shift (E) is your ONLY escape - never burn offensively without backup. "
        "Spikes: Trinity Force + Manamune fully stacked (Muramana), Serylda's Grudge (armor pen). "
        "Macro: stay mid-to-long range, Q poke every wave, ult across map at grouped enemies. "
        "Exploit: Q applies on-hit effects including Muramana - every Q is a ranged attack."
    ),
    "Jhin": (
        "Jhin. Mechanics: 4 shots then reload - plan your 4th shot as the crit execute. "
        "W (Deadly Flourish) roots enemies recently hit by minions/allies - set up in trades. "
        "RFC headshot at max range crits for 30%+ HP on squishies. "
        "Spikes: Hexoptics C44 (25% crit + 55 AD), RFC (max-range headshot), IE (crit cap). "
        "Macro: position behind ally frontline, use W roots from fog of war, R to finish. "
        "Exploit: Reload window forces him to reposition - abuse his reload with all-in timing."
    ),
    "Ashe": (
        "Ashe. Mechanics: every auto is a slow (Frost Shot) - perma-slow kites any enemy. "
        "Ranger's Focus (Q) at 4+ stacks: cone of arrows that AOE slows. "
        "Crystal Arrow (R) is global - throw at fight start, always on CD. "
        "Spikes: RFC (max-range frost shot), The Collector (25% crit), IE (75% crit cap). "
        "Macro: stay at absolute max range, perma-slow tanks for team, R to initiate from range. "
        "Exploit: RFC headshot crits from 850+ range without closing distance."
    ),
    "Draven": (
        "Draven. Mechanics: catch BOTH Spinning Axes on every throw for permanent double-proc. "
        "League of Draven stacks: every kill multiplies R damage - use R to finish grouped low-HP enemies. "
        "Stand (E) blocks and returns any projectile. "
        "Spikes: The Collector (early execute), Bloodthirster (sustain + crit), Navori (25% crit). "
        "Macro: dominate early kills for stack generation, convert stack gold on R reset. "
        "Exploit: Stand (E) can block Lux R, Caitlyn R, any targeted projectile for free trade."
    ),
    "Xayah": (
        "Xayah. Mechanics: autos plant feathers, E (Bladecaller) pulls them back rooting caught enemies. "
        "Fire Q (Double Daggers) before E for maximum feathers. "
        "R (Featherstorm) INVINCIBLE during channel - dodge any burst or CC with R timing. "
        "Spikes: Yun Tal (AS), RFC (25% crit), The Collector (50% crit before IE). "
        "Macro: plant feathers with autos in extended trades, E-root for kills, R to dodge burst. "
        "Exploit: time R to dodge Malphite ult, Lux R, or any burst window."
    ),
    "Zeri": (
        "Zeri. Mechanics: Q (Burst Fire) passes through terrain - chip enemies through minion walls. "
        "E (Spark Surge) wall-hop for repositioning or escape. "
        "R (Lightning Crash) overcharges: every kill extends duration - snowball through grouped fights. "
        "Spikes: Kraken Slayer (on-hit), Navori (25% crit), Runaan (AoE on-hit spread). "
        "Macro: wall-hop for unexpected angles, Q poke through minions, R into 2+ enemies. "
        "Exploit: empowered Q auto after ability crits at 60%+ crit for burst window."
    ),
    "Samira": (
        "Samira. Mechanics: Style rank D->S requires alternating melee/ranged combos and using ally CC. "
        "R (Inferno Trigger) only unlocks at S rank - time it after building rank in a fight. "
        "Daredevil Impulse passive dashes through/over enemies on autos. "
        "Spikes: The Collector (25% crit), Navori (25% crit), ISB (75% before IE). "
        "Macro: build rank on multiple enemies before R, never R single isolated target. "
        "Exploit: weave through grouped enemies with passive dashes to hit all 5 with R spin."
    ),
    "Sivir": (
        "Sivir. Mechanics: Ricochet (W) bounces autos for AOE - activate before every teamfight. "
        "Spell Shield (E) blocks one incoming ability - save for hard CC or burst finisher. "
        "R gives entire team movement speed - use for disengage or initiation. "
        "Spikes: Navori (25% crit, reduces Q/W CD on crit), RFC (25% crit), IE (75% cap). "
        "Macro: crash waves fast with Q/W, R to move team between objectives. "
        "Exploit: E Spell Shield on Malphite R or Amumu R negates engage entirely."
    ),
    "Varus": (
        "Varus. Mechanics: W (Blighted Quiver) passive - 3 stacks of blight on target, "
        "then E root detonates stacks for bonus % max HP damage. "
        "R (Chain of Corruption) root jumps between enemies - throw into grouped cluster. "
        "Spikes: Kraken Slayer (vs tanks), Phantom Dancer (20% crit + ghost), The Collector (crit + execute). "
        "Macro: Q long-range poke to apply blight stacks, E to root + detonate, R on grouped. "
        "Exploit: apply 3 blight stacks with W-passive autos before using any ability for max detonation."
    ),
    "Kalista": (
        "Kalista. Mechanics: every auto hops to a new position - never stand still, always move. "
        "Rend (E) pulls ALL spears from ALL targets simultaneously - detonate when 4+ stacked. "
        "Fate's Call (R) throws your support at enemies for a targeted knockup. "
        "Spikes: Kraken Slayer (on-hit spread via Runaan), Navori (25% crit), Runaan (AoE spear stack). "
        "Macro: stack spears on 3+ enemies simultaneously with Runaan, E to AOE rend the group. "
        "Exploit: R is your support's initiation tool - coordinate the throw for gap-close into their team."
    ),
}

GENERIC_PROFILE = (
    "ADC. Priorities: safe uptime, wave tempo, item spikes, objective windows. "
    "Never die without purpose. Always know where the next wave crashes."
)



# -- Game Sense vocabulary -------------------------------------------------
# Approved 12-word vocabulary for the aftergame GAME SENSE panel. Early / Mid /
# Late game phases each receive one descriptor drawn from this list. The
# dashboard renders these in the adaptation panel (client mode) and persists
# them to match_metrics with metric_key in {game_sense_early, _mid, _late}
# under milestone_tag='game_end'. Valence colors in the UI map accordingly.
GAME_SENSE_VOCAB: dict[str, dict[str, str]] = {
    # Negative (coral)
    "Chaotic":      {"valence": "bad",  "hint": "Scattered, reactive, losing every skirmish."},
    "Tilted":       {"valence": "bad",  "hint": "Emotional play, forcing engagements."},
    "Drowning":     {"valence": "bad",  "hint": "Tempo-starved, falling behind objective-to-objective."},
    "Scattered":    {"valence": "bad",  "hint": "Missing obvious play windows."},
    # Warning (gold)
    "Hesitant":     {"valence": "warn", "hint": "Winning the duel, losing the map."},
    "Reactive":     {"valence": "warn", "hint": "Responding, never initiating."},
    # Neutral
    "Steady":       {"valence": "ok",   "hint": "No mistakes, no standout plays."},
    # Positive (mint)
    "Composed":     {"valence": "good", "hint": "Traceable decisions, no panic."},
    "Patient":      {"valence": "good", "hint": "Waited for the right window."},
    "Opportunistic":{"valence": "good", "hint": "Capitalized on enemy mistakes."},
    "Dominant":     {"valence": "good", "hint": "Dictated tempo, enemy reacted to you."},
    "On Point":     {"valence": "good", "hint": "Read plays before they committed."},
}

