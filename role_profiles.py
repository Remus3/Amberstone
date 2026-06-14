"""
role_profiles.py
Challenger-level coaching context for all roles, not just ADC.
Used by coach_integration.py when the player's role is detected.

Covers:
  - Mid lane mages
  - Bot lane APC (mage ADC)
  - Bot lane marksman (ADC - primary pool)
  - Bot lane support (tank + enchanter)
  - Vayne top lane
  - ARAM itemization by damage type / comp
"""

# -- Mid Lane Mages -------------------------------------------------------------
MID_MAGE_PROFILES = {
    "Ahri": (
        "Mid Ahri. Roam threat: E charm enables free kill in side lanes. "
        "R (3 dashes) = engage, escape, or follow-up. "
        "Spikes: Luden's (1-item poke), Shadowflame+Rabadon (burst cap). "
        "Macro: shove wave, roam bot at 6. Force drake setup with R mobility. "
        "Exploit: charm through minion wall at lane brush position."
    ),
    "Syndra": (
        "Mid Syndra. Mechanics: W throw orb/minion, E stun. 7-orb R execute. "
        "Spikes: Luden's (poke), Shadowflame (burst), Rabadon (execute). "
        "Macro: priority lane - shove and roam or shove and control vision. "
        "Exploit: E stun from max range after E+W orb stack setup."
    ),
    "Lux": (
        "Mid Lux. E snare two targets if aimed correctly. "
        "R global cooldown - use for picks and objective setup. "
        "Spikes: Luden's (waveclear), Shadowflame (burst), Rabadon. "
        "Macro: priority lane; R from range on escaping enemies. "
        "Exploit: E through minion line to double-snare bot lane brush."
    ),
    "Viktor": (
        "Mid Viktor. Evolve Q→E→W. W gravity stuns after 1.5s - drop on group. "
        "Fully evolved E+R = lane clear machine and fight controller. "
        "Spikes: Luden's (waveclear), Zhonya's (teamfight). "
        "Macro: hard to roam - control mid, scale, group for objectives. "
        "Exploit: W→Q auto for max DPS in short trades."
    ),
    "Zed": (
        "Mid Zed. W shadow stays for return dash. R death mark - auto+Q+E then R-back. "
        "Spikes: Duskblade (1-item lethality), Serylda's (slow+pen). "
        "Macro: shove wave, roam side lanes at level 6. "
        "Kill window: R when target is below 50% HP for execute combo. "
        "Exploit: W to wall, Q to poke, return W for safe retreat."
    ),
    "Orianna": (
        "Mid Orianna. Ball placement is everything. R Shockwave from ball position. "
        "Spikes: Shadowflame (poke), Rabadon (teamfight). "
        "Macro: priority lane; set up R with flash or ally engage. "
        "Exploit: W shield ball to an ally who engages, then R from inside enemy team."
    ),
    "Azir": (
        "Mid Azir. Soldiers attack simultaneously on Q. R wall repositions enemies. "
        "Spikes: Nashor's Tooth (attack speed), Rabadon (AP). "
        "Macro: hard-shove with soldiers, safe R-walling dive attempts. "
        "Exploit: R pushes enemies into your team - coordinate with a frontline."
    ),
}

# -- Bot Lane APC (Mage ADC) ----------------------------------------------------
APC_BOT_PROFILES = {
    "Seraphine": (
        "Bot APC Seraphine. Note passive echoes nearby ally casts. "
        "R extends from allies hit - position BEHIND your team for max range. "
        "Spikes: Luden's (poke), Shadowflame, Rabadon. "
        "Macro: team-fight oriented; your ult wins objective fights. "
        "Exploit: R through your whole team extends the hit range massively."
    ),
    "Ziggs": (
        "Bot APC Ziggs. W Satchel can self-reposition over walls. "
        "Passive demolishes towers - attack weakened tower autos. "
        "Spikes: Luden's (clear), Shadowflame (burst). "
        "Macro: best split-push mage - clear bot, take tower, reset. "
        "Exploit: Q bounces - fire at feet of enemy, not directly at them."
    ),
    "Heimerdinger": (
        "Bot APC Heimerdinger. Three turrets focus nearest target - "
        "place in bushes for ambush, in lane for zone. R+E = guaranteed stun combo. "
        "Spikes: first turret component, Nashor's (attack speed for turrets). "
        "Macro: turret waveclear is strongest in game. Don't overextend without turrets."
    ),
    "Veigar": (
        "Bot APC Veigar. E cage stuns edges - place ON enemies. "
        "Stack AP every CS; R execute scales with your AP. "
        "Spikes: Luden's (first item), Rabadon (high AP). "
        "Macro: stall game, scale, hard-win late. Never die early. "
        "Exploit: E cage from fog of war before enemy can react."
    ),
    "Swain": (
        "Bot APC Swain. E root→detonate for hard pull onto team. "
        "R sustain heals massively - activate mid-fight, not before. "
        "Spikes: Rod of Ages (sustain tank), Rylai's (perma-slow). "
        "Macro: melee range - needs peel support. Value 5v5 grouped fights."
    ),
    "Karthus": (
        "Bot APC Karthus. Spam Q on grouped enemies continuously. "
        "R global - fires regardless of your position or death state. "
        "Spikes: Luden's (clear), Rabadon (R damage). "
        "Macro: play passive early, scale, spam R after every fight. "
        "Exploit: die after using R for free global damage - passive still fires."
    ),
}

# -- Bot Lane Tank / Engage Supports -------------------------------------------
TANK_SUPPORT_PROFILES = {
    "Nautilus": (
        "Support Nautilus. Q hook pulls self to wall or champion. "
        "Passive roots every 1st auto on each target - proc on support items. "
        "R single-target hard CC that chains through enemies in path. "
        "Macro: hook + R to set up kills; peel with R if ADC dived. "
        "Itemization: Locket, Zeke's (if ADC is crit), Warmog's, Knight's Vow."
    ),
    "Leona": (
        "Support Leona. All abilities apply Sunlight for ally bonus hit. "
        "E+Q = E gap-close then Q stun immediately. R stuns center, slows edge. "
        "Macro: hardest engage in bot lane. Only go in when ADC is ready. "
        "Itemization: Locket, Zeke's, Warmog's, Shurelya's for chase."
    ),
    "Thresh": (
        "Support Thresh. Q hook separates one target. W lantern saves ally. "
        "E flay direction matters - pull in for kill or push away for peel. "
        "Macro: hook priority targets; W lantern when ADC is being dived. "
        "Itemization: Imperial Mandate, Knight's Vow, Locket, Redemption. "
        "No mana - never buy mana items."
    ),
    "Blitzcrank": (
        "Support Blitzcrank. Q grab separates squishy targets. E+Q timing - "
        "W speed boost before grab increases hook range window. "
        "Passive mana shield. R silences in a ring. "
        "Macro: hook the ADC not the tank. Win lane by isolating squishy targets. "
        "Itemization: Locket, Zeke's, Warmog's, Mercury Treads."
    ),
    "Alistar": (
        "Support Alistar. W→Q combo = headbutt then knockup. "
        "R reduces all damage by 75% - use when dove or when catching someone. "
        "Macro: best in-fight peel. Use R to tank tower dives. "
        "Itemization: Locket, Knight's Vow, Warmog's, Frozen Heart."
    ),
    "Rell": (
        "Support Rell. Mount Q knockup, dismount E stun. "
        "R Ferromancy pulls all nearby enemies. W mounted = hard engage. "
        "Macro: chain CC machine - engage, peel, re-engage. "
        "Itemization: Locket, Zeke's, Warmog's, Sunfire."
    ),
}

# -- Bot Lane Enchanter Supports ------------------------------------------------
ENCHANTER_SUPPORT_PROFILES = {
    "Lulu": (
        "Support Lulu. W polymorph is the hardest ADC-peel ability in the game. "
        "R on your ADC = instant knockup + huge HP buffer vs dive. "
        "E shield adds bonus AD to ally. "
        "Macro: always R when ADC is being dived; W the engaging enemy immediately. "
        "Itemization: Moonstone, Staff of Flowing Water, Ardent Censer, Redemption."
    ),
    "Soraka": (
        "Support Soraka. Q Starcall heals if hitting enemy. "
        "R global heal - use BEFORE allies die, not after. E silence stops channeled ults. "
        "Macro: stand behind ADC, poke with Q for heal refund. "
        "Itemization: Moonstone, Redemption, Ardent Censer, Mikael's."
    ),
    "Nami": (
        "Support Nami. Q bubble is powerful CC - hard to land, crucial to master. "
        "W bounces heal+damage. E empowers ally autos with slow. "
        "Macro: E your ADC before every trade window. "
        "Itemization: Imperial Mandate, Ardent Censer, Staff of Flowing Water."
    ),
    "Karma": (
        "Support Karma. Mantra (R) amplifies any ability. "
        "Best use: R+E for AoE shield on whole team. R+Q for strong slow. "
        "Macro: R+E before every objective fight to shield the team. "
        "Itemization: Shurelya's (for R+Q chase), Ardent Censer, Redemption."
    ),
    "Janna": (
        "Support Janna. W tornado max range = guaranteed engage interrupt. "
        "R heals everyone nearby instantly - use in losing fights to reset. "
        "E shield grants bonus AD to shielded champion. "
        "Macro: best peel in the game. R to disengage, W to interrupt engage. "
        "Itemization: Shurelya's, Ardent Censer, Staff of Flowing Water, Redemption."
    ),
    "Yuumi": (
        "Support Yuumi. Attach to highest-damage ally and heal/speed them. "
        "R stuns multiple - jump off ally first so R can hit enemies. "
        "Macro: attach to ADC in lane, swap to frontline in fights. "
        "Itemization: Moonstone, Ardent Censer, Staff of Flowing Water."
    ),
    "Milio": (
        "Support Milio. W extends ally attack range - attach to ADC. "
        "R AoE cleanse + heal - use to remove all CC in a teamfight. "
        "Macro: R timing is the skill expression - cleanse just as CC lands. "
        "Itemization: Moonstone, Ardent Censer, Redemption, Staff of Flowing Water."
    ),
    "Seraphine": (
        "Support Seraphine. Note echoes nearby ally casts. "
        "R extends range through each ally hit - position behind team. "
        "Macro: poke phase + teamfight ult. "
        "Itemization: Moonstone (heal), Redemption, Ardent Censer."
    ),
}

# -- Vayne Top Lane (special case) ---------------------------------------------
VAYNE_TOP_PROFILE = """
Vayne Top. High-risk high-reward matchup pick. Wins vs tanks late; loses vs most early.

EARLY GAME (levels 1-9): SURVIVAL ONLY.
• Do not fight. Do not trade unless you have level + item advantage.
• Q tumble away from all-ins. Condemn into wall only when 100% safe.
• CS under tower. Freeze if possible - force enemy to take tower aggro.
• Back at 1100g minimum (BotRK component + Long Sword).

IF BEHIND (losing CS by 20+, or died once):
• Freeze wave at YOUR tower - let enemy push. They waste time, you CS safely.
• Ping jungler to avoid your lane - no dive available.
• Buy BotRK FIRST item regardless - it's your only path back into relevance.
• Respect the enemy: do not trade until BotRK is complete.
• Your comeback condition: enemy isolates themselves near a wall. One condemn stun = kill.
• Do NOT split if your team needs you for dragon/baron. You are weaker early.

IF VERY BEHIND (died 2+ times, item gap 1 full item):
• Stop fighting your lane opponent. Farm jungle camps on your side.
• Ward enemy jungle, look for the jungler to countergank.
• Target: krugs + raptors on resets if uncontested.
• Tell team via ping: you are playing for late game.
• NEVER recall with less than 1100g unless dying.
• Your recovery timeline: 3 items (BotRK + PD + IE) = you win any 1v1.

REGAINING MOMENTUM WITH ALLIES:
• Ask jungler for a gank only AFTER you've set up a wall-condemn angle.
• Best setup: enemy at T2 tower, you stand between them and their tower escape angle.
• Coordinate with mid/jg: walk away to bait, then R invis re-engage when they follow.
• Cross-map value: even when behind, your 3-stack Silver Bolts kills any tank.

POWER SPIKES: BotRK (survivable), BotRK+PD (duel anyone), BotRK+PD+IE (win game).
"""

# -- ARAM Itemization Guide (comp-aware) ----------------------------------------

ARAM_ITEM_RULES = """
ARAM ITEMIZATION RULES:
ARAM fights are continuous - survival stats have higher value than in SR.
Items are discounted ~20% in ARAM. Fights never stop - sustain beats burst timing.

AD/MARKSMAN ARAM (GENERAL):
• 1st item: Immortal Shieldbow (safety) OR Kraken Slayer (vs tanks)
• 2nd item: Runaan's Hurricane (AoE) OR Phantom Dancer (mobility/crit)
• 3rd+: Lord Dominik's (vs armor stacking), Bloodthirster (sustain)
• Boots: Plated Steelcaps vs heavy AD, Mercury Treads vs heavy AP/CC
• AVOID: Collector / lethality builds (enemy teams stack HP in ARAM)

AP/MAGE ARAM (GENERAL):
• 1st item: Luden's Companion (poke) OR Shadowflame (burst vs shields)
• 2nd item: Rabadon's Deathcap (if winning) OR Zhonya's (if being focused)
• 3rd+: Void Staff (vs MR stackers), Rylai's (perma-slow in corridor)
• AVOID: Tear / Seraph's unless champion NEEDS mana (Ryze, Anivia, Azir)

TANK/FIGHTER ARAM:
• 1st item: Heartsteel (HP scaling) OR Sunfire Aegis (DPS tank)
• 2nd item: Warmog's Armor (HP threshold) OR Thornmail (vs healing heavy)
• 3rd+: Force of Nature (vs AP), Frozen Heart (vs AD auto-attackers)
• Boots: Plated Steelcaps almost always

SUPPORT/ENCHANTER ARAM:
• 1st item: Moonstone Renewer (sustained healing) OR Imperial Mandate (poke comp)
• 2nd item: Ardent Censer (if ally has on-hit/AS), Redemption (AoE healing)
• 3rd+: Staff of Flowing Water, Mikael's (cleanse for key ally)

GRIEVOUS WOUNDS PRIORITY:
• Buy if enemy has 2+ healing champions (Soraka, Warwick, Aatrox, Vladimir, etc.)
• AD: Mortal Reminder  AP: Shadowflame  Tank: Thornmail

% ARMOR/MAGIC PEN:
• Buy Lord Dominik's / Void Staff if enemy team has 3+ items of armor/MR each
"""

def get_role_profile(champion: str, role: str = "bot") -> str:
    """Return the best matching coaching profile string for a champion+role combo."""
    role = (role or "bot").lower()

    # Vayne top is a special case
    if champion == "Vayne" and role == "top":
        return VAYNE_TOP_PROFILE.strip()

    # Role lookups
    if role == "mid":
        if champion in MID_MAGE_PROFILES:
            return MID_MAGE_PROFILES[champion]
    if role in ("apc", "bot_apc"):
        if champion in APC_BOT_PROFILES:
            return APC_BOT_PROFILES[champion]
    if role in ("support", "sup"):
        if champion in TANK_SUPPORT_PROFILES:
            return TANK_SUPPORT_PROFILES[champion]
        if champion in ENCHANTER_SUPPORT_PROFILES:
            return ENCHANTER_SUPPORT_PROFILES[champion]

    # Fall through - caller will use champion_profiles.py
    return ""

def aram_item_context(enemy_champs: list, ally_champs: list, champion: str) -> str:
    """Return ARAM-specific item guidance based on team compositions."""
    try:
        from composition_advisor import enemy_damage_profile
        profile = enemy_damage_profile(enemy_champs)
        ad  = profile["ad"]
        ap  = profile["ap"]
        tanks = profile["tank_count"]
        sustain = profile["sustain_count"]
    except Exception:
        ad, ap, tanks, sustain = 0.5, 0.5, 1, 0

    lines = ["ARAM ITEM GUIDANCE:"]
    if ad >= 0.7:
        lines.append(f"  Enemy {ad:.0%} AD \u2192 Plated Steelcaps + Randuin's/Frozen Heart")
    elif ap >= 0.7:
        lines.append(f"  Enemy {ap:.0%} AP \u2192 Mercury Treads + Force of Nature/Banshee's")
    else:
        lines.append("  Mixed damage \u2192 versatile boots, favor whichever damage type leads")

    if tanks >= 3:
        lines.append(f"  {tanks} tanks \u2192 Kraken Slayer (AD) / Void Staff (AP) mandatory")
    if sustain >= 2:
        lines.append(f"  {sustain} healers \u2192 Grievous Wounds item early (Mortal Reminder / Shadowflame / Thornmail)")

    lines.append("  ARAM: always build 1 survival item (Shieldbow/Zhonya's/Sterak's) regardless of comp")
    return "\n".join(lines)
