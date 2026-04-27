"""
champion_profiles.py
Per-champion data for all ~170 League of Legends champions (SR + ARAM).

Fields per champion:
  dmg      : primary damage type — 'ad', 'ap', 'hybrid'
  role     : tank / fighter / mage / assassin / marksman / support
  mana     : True = mana-dependent, False = energy/fury/none/rage
  sustain  : True = significant self-heal or lifesteal (Grievous Wounds value)
  mechanic : 1-2 sentence key mechanic for coaching
  aram     : 1 sentence ARAM-specific tip

Used by composition_advisor.py to:
  - Profile enemy damage type (AD vs AP) for resistance choices
  - Flag mana items on non-mana champs in ARAM
  - Identify sustain-heavy comps (Grievous Wounds priority)
  - Identify tank-heavy comps (armor pen priority)
"""

CHAMPIONS: dict[str, dict] = {
    # ── A ─────────────────────────────────────────────────────────────
    "Aatrox": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "Three-zone W for max knockup damage; R heals on kill. Always land sweet-spot W.",
        "aram": "Sustained frontline; abuse W range to poke then trade all-in.",
    },
    "Ahri": {
        "dmg": "ap", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "E charm enables free Q+W burst. R gives three dashes — save for escape or chase.",
        "aram": "Poke with Q, charm to lock a target for team, use R for repositioning.",
    },
    "Akali": {
        "dmg": "ap", "role": "assassin", "mana": False, "sustain": False,
        "mechanic": "Passive ring proc maximises damage. W smoke shroud breaks targeting.",
        "aram": "Dive squishy backline through frontline. W vs targeted spells, not AoE.",
    },
    "Akshan": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Passive revives slain allies via villain kills. W grapple loop for sustained poke.",
        "aram": "W around terrain for infinite poke; revive allies to instantly swing team fights.",
    },
    "Alistar": {
        "dmg": "ad", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "W→Q combo = knockup into headbutt displacement. R reduces incoming damage 75%.",
        "aram": "Headbutt enemies away from your carry; R makes you nearly unkillable.",
    },
    "Ambessa": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": False,
        "mechanic": "Passive dash resets on ability casts. High mobility frontline fighter.",
        "aram": "Dash aggressively through enemies; chain resets for maximum damage uptime.",
    },
    "Amumu": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "Q bandage toss lands, E tantrum resets. R mass root changes team fights instantly.",
        "aram": "Stack AP for tankier R hits. Land R first then let your team follow up.",
    },
    "Anivia": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Glacial Storm (R) zone control wins sieges. R + W wall traps enemy for Q stun.",
        "aram": "Mana-hungry — Lost Chapter is mandatory. R zones entire ARAM corridor.",
    },
    "Annie": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "4-stack stun on next spell. Pre-stack with Q/W, release on R or flash-bear.",
        "aram": "Flash-Tibbers into backline. Molten Shield (E) reflects on-hit; cast before trading.",
    },
    "Aphelios": {
        "dmg": "ad", "role": "marksman", "mana": False, "sustain": False,
        "mechanic": "5 weapon combos; Calibrum+Infernum AoE pull is strongest engage. No mana — no mana items.",
        "aram": "Learn weapon priority; Severum (healing gun) is your lifeline in sustained fights.",
    },
    "Ashe": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Q empowered autos slow; always stacked before trading. R global arrow — use at choke or on escaping enemies.",
        "aram": "Permanent slow makes you a lockdown machine. R down the corridor for guaranteed stun.",
    },
    "Aurelion Sol": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Stardust stacks → bigger spells. Roam to stack mid-game; breached nexus = massive power spike.",
        "aram": "Stack fast with Q poke. Breathe (E) across the ARAM bridge for free stacks.",
    },
    "Aurora": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Spirit mechanic reduces incoming damage. R repositions enemies.",
        "aram": "Use terrain to your advantage; R displacement in tight ARAM corridor is high value.",
    },
    "Azir": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "W soldiers attack together with Q. R Emperor's Divide wall changes positions.",
        "aram": "Soldiers do AoE poke across the lane. R wall blocks entire bridge path.",
    },
    # ── B ─────────────────────────────────────────────────────────────
    "Bard": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "Meeps deal bonus magic damage; collect chimes for AP. R Cosmic Binding freezes all targets hit.",
        "aram": "R stasis on whole enemy team is a teamfight reset. Poke with Q+W between fights.",
    },
    "Bel'Veth": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "E stacks attacks speed stacks. R True Form gives bonus attacks.",
        "aram": "Build attack speed; heal sustains you in extended ARAM fights.",
    },
    "Blitzcrank": {
        "dmg": "ad", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "Q hook separates targets. EQ combo = grab→knockup for full CC chain.",
        "aram": "Hook the fed carry or key target. W boosts your hook speed — use it before hooking.",
    },
    "Brand": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Passive blaze + abilities trigger Sear stun. R bounces harder on full-blaze targets.",
        "aram": "R bounces endlessly in grouped ARAM. Always blaze a target first for bonus R bounces.",
    },
    "Braum": {
        "dmg": "ad", "role": "support", "mana": True, "sustain": False,
        "mechanic": "Passive 4-stack stun from ally procs. W Unbreakable blocks projectiles from the front.",
        "aram": "Walk in front of your ADC. W blocks the whole team's poke from one direction.",
    },
    "Briar": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "No mana. R launches at target, then AoE fear. Pillory (W) gives extended healing.",
        "aram": "Build AD+sustain. R on grouped enemies terrifies the whole team.",
    },
    # ── C ─────────────────────────────────────────────────────────────
    "Caitlyn": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Headshot procs from trap hits and net. E (net) = primary escape, never burn offensively if dive risk.",
        "aram": "Lay traps on choke points. R finishes fleeing targets; use Q+passive combos for sustained poke.",
    },
    "Camille": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": False,
        "mechanic": "W outer ring true damage, inner ring heals. E hook grapple, second click launches. R isolates a target.",
        "aram": "Gap close with E, isolate with R. Build Goredrinker for sustain fights.",
    },
    "Cassiopeia": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "E Twin Fang resets on poisoned targets — spam only when Q/W poisoned. R stun if facing you.",
        "aram": "Q W poison then spam E resets. Position to turn your R toward enemies at engage.",
    },
    "Cho'Gath": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "Feast stacks HP permanently. Q knock-up, W slow, E silence; build Warmog's for HP scaling.",
        "aram": "R kills grant permanent HP — Feast every cooldown for free tank stats.",
    },
    "Corki": {
        "dmg": "hybrid", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Passive applies magic damage to all attacks (60-80%). Big One package Q is best poke tool.",
        "aram": "Your autos deal magic damage — build hybrid/AP items. Grab The Package ASAP.",
    },
    # ── D ─────────────────────────────────────────────────────────────
    "Darius": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "Q outer ring deals max damage and heals. 5-stack Hemorrhage enables Noxian Guillotine resets.",
        "aram": "Build Black Cleaver for shred + armor. Q outer edge is priority — never stand in center of your own Q.",
    },
    "Diana": {
        "dmg": "ap", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "Q moonlight then R gap closes. Q+R→E AoE combo in grouped fights. Passive charges on 3-hit.",
        "aram": "R resets on shielded (Q-marked) kills. Chain dive for resets across grouped enemies.",
    },
    "Dr. Mundo": {
        "dmg": "ad", "role": "tank", "mana": False, "sustain": True,
        "mechanic": "No mana — uses HP as resource. R massive HP regen. Build Warmog's for HP threshold.",
        "aram": "Near-immortal with R + Warmog's. Build pure HP; enemy needs Grievous Wounds or can't kill you.",
    },
    "Draven": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Catch spinning axes (Q) for bonus damage stacking. League of Draven passive converts kills to gold.",
        "aram": "Axes bounce predictably in ARAM lane. Stack early; R for shutdown gold if ahead.",
    },
    # ── E ─────────────────────────────────────────────────────────────
    "Ekko": {
        "dmg": "ap", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "W time zone stuns if you stay. R rewinds 3s and heals — use R to survive burst.",
        "aram": "W in the enemy cluster for teamfight stun. R after taking burst to reset position.",
    },
    "Elise": {
        "dmg": "ap", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "Human E cocoon stun, then spider form rappel. Cocoon hit enables free W spider bite.",
        "aram": "Land E stun for your team. Spider form W for sustained damage on a stunned target.",
    },
    "Evelynn": {
        "dmg": "ap", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "Level 6 camo. Lash Out last-hit empowers W allure charm. R execute plus retreat camo.",
        "aram": "Camo less useful here. W charm then burst target. R to delete a carry and escape.",
    },
    "Ezreal": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Q reduces all CDs by 1.5s — spam Q every wave. E blink is your only escape.",
        "aram": "Spam Q for CD reduction; never waste E offensively without a second escape plan.",
    },
    # ── F ─────────────────────────────────────────────────────────────
    "Fiddlesticks": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": True,
        "mechanic": "W Drain sustains in fights. R Crowstorm from brush — terrifying in cramped spaces.",
        "aram": "R from brush or off-screen bush. W drain on a CC'd target heals massively.",
    },
    "Fiora": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "Riposte (W) parries any CC into stun. Vital system: hit 4 vitals on a champion for massive heal.",
        "aram": "Vital locations are fixed — memorize them. W parry high-impact CC for game-changing stun.",
    },
    "Fizz": {
        "dmg": "ap", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "E Playful/Trickster dodges any projectile or CC. R Chum the Waters shark roots and deals massive damage.",
        "aram": "R into grouped enemies then E dodge the retaliation. W applies on-hits during auto burst.",
    },
    # ── G ─────────────────────────────────────────────────────────────
    "Galio": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "W taunt charges for AoE attack. R global, taunts all nearby on landing.",
        "aram": "W into grouped enemies for mass taunt. Build Abyssal for bonus MR aura vs AP teams.",
    },
    "Gangplank": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "Q applies silver serpents. Eat oranges (W) to cleanse CC. R global slow from barrels.",
        "aram": "Barrel chain explosions across the corridor. W cleanses every CC in game.",
    },
    "Garen": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "Passive regenerates HP out of combat. Q silences; E spins deal true damage on 6th tick.",
        "aram": "Spin into grouped enemies for consistent AoE. Q silence key casters before their combo.",
    },
    "Gnar": {
        "dmg": "hybrid", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "Rage builds to Mega Gnar. Mega R GNAR! slam then wall = mass knockup combo.",
        "aram": "Build rage with autos then all-in as Mega. R into wall knocks up whole team.",
    },
    "Gragas": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": True,
        "mechanic": "W passive reduces damage. R Explosive Cask displaces — use to throw enemies into your team.",
        "aram": "R to scatter enemies or push carry into your team. W reduces incoming damage in skirmishes.",
    },
    "Graves": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Short-range shotgun pellets. Reload (passive) after 2 shots. E dodge ability. True Grit armor stacks.",
        "aram": "Stay point-blank for max shotgun damage. Build armor items — True Grit makes you a pseudo-tank.",
    },
    "Gwen": {
        "dmg": "ap", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "W Hallowed Mist blocks enemy abilities from outside. Q hits count as true damage in center.",
        "aram": "W to negate poke in fights. Sustain makes her hard to kill. Build Riftmaker+BORK.",
    },
    # ── H ─────────────────────────────────────────────────────────────
    "Hecarim": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "W heals on damage dealt nearby. R fear on landing — use from off-screen for full terror.",
        "aram": "Run at them. W sustains through sustained fights. R from flanks.",
    },
    "Heimerdinger": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Turrets focus nearest target. E stun. R empowers any ability — R+E is best CC.",
        "aram": "Place three turrets at the front. R+E for guaranteed stun setup into your turrets.",
    },
    "Hwei": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Three ability books: QQ poke, WW despair zone, EE chain. Combo books for max damage.",
        "aram": "EE chain pull bunches enemies for QQ poke or WW despair. Mana-hungry — Lost Chapter first.",
    },
    # ── I ─────────────────────────────────────────────────────────────
    "Illaoi": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "W Spirit extraction, then hit spirits for healing. R tentacle spawn on hit each enemy.",
        "aram": "Max range Q tentacle slap. R in grouped enemies spawns tentacles on all — near-unkillable.",
    },
    "Irelia": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "Q resets on low-HP targets. Passive mark stacks; 4-stack Q slows. E disarm.",
        "aram": "Farm low-HP minions for Q resets, then dive into resets on kills.",
    },
    "Ivern": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "E Triggerseed shield detonates nearby. Daisy golem provides secondary frontline.",
        "aram": "Spam E shields on your frontline. Daisy soaks a ton of damage.",
    },
    # ── J ─────────────────────────────────────────────────────────────
    "Janna": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "W tornado stuns at max range. R heals all nearby allies instantly. E shield grants AD bonus.",
        "aram": "R in a losing fight to heal everyone and reposition. W to interrupt engages.",
    },
    "Jarvan IV": {
        "dmg": "ad", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "EQ combo = flag knock-up. R Cataclysm creates arena — use to isolate or trap.",
        "aram": "EQ knock-up is reliable CC. R traps a key target; your team follows up inside.",
    },
    "Jax": {
        "dmg": "hybrid", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "E Counter Strike dodges autos then stuns. Power spike: Titanic Hydra + Trinity.",
        "aram": "E dodge a key auto-attack burst, then stun. Build Trinity for fast dueling.",
    },
    "Jayce": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "Cannon form for ranged poke; hammer form for melee CC and dash. No mana threshold issues.",
        "aram": "Poke with cannon, trade with hammer. Gate→Mercury Hammer combo is your engage.",
    },
    "Jhin": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "4-shot reload; 4th shot crits harder. W traps root. R 4-shot snipe for finishes.",
        "aram": "W root into R snipe for easy kills. 4th shot empowered — always position to hit it on a champion.",
    },
    "Jinx": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Flip rockets/minigun for AoE/DPS. Passive reset on kill. R global execute at 20%+ HP.",
        "aram": "Rockets hit everyone in the ARAM corridor. Passive reset = chain kill machine.",
    },
    # ── K ─────────────────────────────────────────────────────────────
    "K'Sante": {
        "dmg": "ad", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "Ntofos (Q) stack for empowered slam. R removes tank stats but enables assassin burst.",
        "aram": "Q stun into E displacement. R only when you want to burst someone — you lose tank stats.",
    },
    "Kai'Sa": {
        "dmg": "hybrid", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Void passive stacks; 5 stacks deals bonus magic damage. W marks target; R gap closes to marked.",
        "aram": "W mark → R gap close on isolated target. Stack passive with Q for burst combo.",
    },
    "Kalista": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Passive sidestep on every auto. Stack spears, E rend for slow. Oathsworn R launches support.",
        "aram": "Rend (E) pokes permanently. R launch support for surprise engage/CC.",
    },
    "Karma": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "Mantra charges abilities. R+Q: AoE slow. R+W: root. R+E: AoE shield. Use Mantra wisely.",
        "aram": "R+E AoE shield your whole team. R+Q poke for waveclear and slow.",
    },
    "Karthus": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Passive death-timer = last burst window. R global damage to all enemies.",
        "aram": "Spam Q constantly on grouped enemies. R cleans up after any big fight regardless of your position.",
    },
    "Kassadin": {
        "dmg": "ap", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "Passive 15% reduced magic damage. R Riftwalk blinks + scales with use.",
        "aram": "Good vs AP-heavy ARAM. Riftwalk through enemy lines for disruptive positioning.",
    },
    "Katarina": {
        "dmg": "ap", "role": "assassin", "mana": False, "sustain": False,
        "mechanic": "Daggers on ground reset E. Shunpo to champion = reduced damage taken. R channels on nearby enemies.",
        "aram": "Throw daggers, Shunpo to them for burst resets. E to a champion to reduce damage taken mid-combo.",
    },
    "Kayle": {
        "dmg": "hybrid", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Level 11: ranged AoE autos. Level 16: flame autos. R Intervention invulnerability on ally or self.",
        "aram": "Reach level 11 before going ham. R saves your carry from burst.",
    },
    "Kayn": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "Two forms: Darkin (AD sustain) vs SA (AP assassin). Form choice based on enemy comp.",
        "aram": "Darkin form vs tanky teams; SA form vs squishy teams. W sustain is extremely strong.",
    },
    "Kennen": {
        "dmg": "ap", "role": "mage", "mana": False, "sustain": False,
        "mechanic": "3-mark stun from abilities. R Slicing Maelstrom AoE stun in fights. E speed boost.",
        "aram": "R into grouped enemies for chain stuns. Flash+R or Zhonya's inside enemy team.",
    },
    "Kha'Zix": {
        "dmg": "ad", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "Isolation bonus damage on Q. Evolutions in order: Q→E→W for most lanes.",
        "aram": "Isolation is hard in ARAM but Q still bursts. Evolved E for engage/escape.",
    },
    "Kindred": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Mark hunted targets for bonus stacks (AD/AS). R Lamb's Respite prevents killing blow for all.",
        "aram": "R saves your whole team from executes. Time R just before anyone dies.",
    },
    "Kled": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": False,
        "mechanic": "Skaarl mount = extra HP bar. Scarlett Q hooks then dismounts → remount on Q2 hit.",
        "aram": "Stay mounted for max HP. Q hook + remount combo is your trade pattern.",
    },
    "Kog'Maw": {
        "dmg": "hybrid", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "W Bio-Arcane gives long range + %HP damage. Passive death pew-pew. R global slow.",
        "aram": "W range makes you a turret. Stay back, spam R as zoning tool.",
    },
    # ── L ─────────────────────────────────────────────────────────────
    "LeBlanc": {
        "dmg": "ap", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "Passive mimic creates decoy. W returns you to origin. Sigil+W detonation is core burst.",
        "aram": "W→W-return is your escape. Land E chain before full burst combo.",
    },
    "Lee Sin": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "W shield on ally/ward. R Insec: kick→ward jump→kick back into team.",
        "aram": "Insec kick carries into your team. W to wards or allies for mobility.",
    },
    "Leona": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "All abilities apply Sunlight for ally bonus damage. R Solar Flare stuns at center, slows outside.",
        "aram": "Engage with E+Q. R at max range into grouped enemies for double stun.",
    },
    "Lillia": {
        "dmg": "ap", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "Q and W apply dream dust. R puts all dust-affected enemies to sleep.",
        "aram": "Q around grouped enemies endlessly. R when multiple enemies are dusted for mass sleep.",
    },
    "Lissandra": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "E blink through terrain. R freezes self or target. Q+W chains, then R. True Ice passive reduces CD.",
        "aram": "R on yourself inside enemy team + Zhonya's = frozen AoE bomb.",
    },
    "Lucian": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Passive double-shot after any ability. Ability→auto rhythm maximizes DPS.",
        "aram": "Constant dash + double-shot rhythm. Cleanse gives bonus dashes — worth in CC-heavy ARAM.",
    },
    "Lulu": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "W polymorph hard CC. R Wildgrowth knock-up + huge HP to ally. Shield peel.",
        "aram": "R your highest-damage ally going in. W polymorph the biggest threat.",
    },
    "Lux": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "E snare on two targets if aimed through. Passive Luminescence auto for bonus burst.",
        "aram": "E snare perpendicular to enemy line for double-snare. R global range cleanup.",
    },
    # ── M ─────────────────────────────────────────────────────────────
    "Malphite": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "Passive rock shield regenerates. R Unstoppable Force AoE knockup — best dive engage in game.",
        "aram": "Build full AP: R+E one-shots squishy targets. Activate Flash-R for surprise engage.",
    },
    "Malzahar": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Passive spellshield every 10s. R Nether Grasp suppresses — untargetable with Zhonya's during R.",
        "aram": "E voidlings poke constantly. R suppress carry — use Zhonya's after to channel safely.",
    },
    "Maokai": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": True,
        "mechanic": "Passive heals on nearby spells. Saplings deal bonus damage in brush.",
        "aram": "Stack brambleback (W root). Saplings in bushes do massive bonus damage.",
    },
    "Master Yi": {
        "dmg": "ad", "role": "assassin", "mana": True, "sustain": True,
        "mechanic": "Q dodge autos; W heals and blocks damage. R Highlander resets on kills.",
        "aram": "Q through burst spells. R reset chain with kills; build on-hit for AoE Q damage.",
    },
    "Mel": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Passive reflects one spell. R massive AoE slow + damage.",
        "aram": "Passive reflects big spells — bait them. R catches grouped enemies perfectly.",
    },
    "Milio": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "W extend ally range. R AoE heal + cleanse. E shield.",
        "aram": "R is the best teamfight reset. W your carry to extend their poke range.",
    },
    "Miss Fortune": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "E (Make It Rain) slows; ult channels perpendicular to enemy team from behind cover.",
        "aram": "E→R in the cramped ARAM corridor deletes everyone. Build crit for max Bullet Time.",
    },
    "Mordekaiser": {
        "dmg": "ap", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "Passive Darkness Rise: moving AoE damage field. R Death Realm: 1v1 dimension. Build AP+health.",
        "aram": "R removes their best champion from fight. Build AP: Riftmaker, Rylai's, Nashor's.",
    },
    "Morgana": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "Q root — longest range skillshot root in game. E spellshield blocks all CC.",
        "aram": "Q root shuts down one engage. E your carry vs everything. R tether into mass stun.",
    },
    # ── N ─────────────────────────────────────────────────────────────
    "Naafiri": {
        "dmg": "ad", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "Pack leader spawns packmates. R empowered dash with dog pack.",
        "aram": "R through enemies; dogs add damage. Straightforward burst assassin.",
    },
    "Nami": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "W bounces three times for heal/damage. Q bubble — aim carefully. E empowers ally autos.",
        "aram": "E your ADC for consistent bounce poke. Q bubble at choke for easy landing.",
    },
    "Nasus": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "Q stacks on last-hits — need 300+ to be relevant. W slows movement+attack speed.",
        "aram": "Stack Q on minions. 400+ stacks = delete anything. W slows whole team.",
    },
    "Nautilus": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "Q hook pulls self to wall or pulls target to you. Passive root on first hit each target.",
        "aram": "Q + passive root chain CC. R single-target hard CC that goes through whole team.",
    },
    "Neeko": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Passive disguise as ally. R stasis then AoE root if nearby — use from surprise.",
        "aram": "R from fog of war. Disguise as ally until in range then detonate.",
    },
    "Nidalee": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Hit spear = move to Cougar form with bonus. Pounce resets on marked targets.",
        "aram": "Throw spears then leap onto marked target. Cougar form at 35% HP for burst+heal.",
    },
    "Nilah": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": False,
        "mechanic": "Passive shares assists. E to enemy on CC = engage+escape. W reduces healing on target.",
        "aram": "Melee in ARAM requires ally CC first. Exceptional with hook/CC support.",
    },
    "Nocturne": {
        "dmg": "ad", "role": "assassin", "mana": True, "sustain": True,
        "mechanic": "W spellshield blocks one ability. E fear. R global — removes vision and gaps close.",
        "aram": "W block the key CC, then fear and kill. Build attack speed for sustained damage.",
    },
    "Nunu & Willump": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": True,
        "mechanic": "Q consume heals. W snowball momentum + engage. R channels for AoE root.",
        "aram": "W roll full-speed into grouped enemies for knockup. R then snowball again.",
    },
    # ── O ─────────────────────────────────────────────────────────────
    "Olaf": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "E true damage. R becomes CC-immune. Low HP = faster attack speed via passive.",
        "aram": "R makes you unkillable vs CC comps. Run straight at them at 30% HP.",
    },
    "Orianna": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Ball is all hitboxes. Q move to location, W AoE from ball, R Shockwave from ball.",
        "aram": "Maneuver ball to grouped enemies then R. Shield your carry with W.",
    },
    "Ornn": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "W forge zone, E ram. R Living Forge upgrades your items, then others' items.",
        "aram": "R upgrades give huge stats — use on carries first. CC chain with Q+E.",
    },
    # ── P ─────────────────────────────────────────────────────────────
    "Pantheon": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "Empowered E blocks attacks from front. W stun. Mortal Will passively stacks.",
        "aram": "E block key burst then all-in. Build lethality for burst; shield blocks autos in fights.",
    },
    "Poppy": {
        "dmg": "ad", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "W Steadfast prevents dashes when active. E wall slam stun. R knocks enemies away.",
        "aram": "W prevents ALL dashes in range — huge vs mobile teams. R to throw divers off your carry.",
    },
    "Pyke": {
        "dmg": "ad", "role": "support", "mana": True, "sustain": True,
        "mechanic": "W invisibility+speed. Passive HP over health turns excess to AD. R kills share gold.",
        "aram": "W to stalk then hook. E+Q combo. R execute shares gold with whole team.",
    },
    # ── Q ─────────────────────────────────────────────────────────────
    "Qiyana": {
        "dmg": "ad", "role": "assassin", "mana": False, "sustain": False,
        "mechanic": "Element-imbued Q: river = slow, wall = stun, grass = invisible. R sends elemental wave.",
        "aram": "Imbue river/wall for CC. R stun entire grouped team by bouncing off terrain.",
    },
    "Quinn": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Q blind. E vault marks, auto to proc. R Skystrike in/out for burst repositioning.",
        "aram": "Vault a target, auto-proc for burst. Q blind disables auto-attack heavy enemies.",
    },
    # ── R ─────────────────────────────────────────────────────────────
    "Rammus": {
        "dmg": "ad", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "Thornmail passive + W Defensive Ball Curl reflects damage. Q accelerate then stop.",
        "aram": "W+Thornmail kills auto-attackers. Taunt (E) your biggest AD threat.",
    },
    "Rek'Sai": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "Underground tunnels. W knocks up from below. Fury resource for Q.",
        "aram": "No mana — no mana items. W knockup into Q burst. Build Sunderer for sustain.",
    },
    "Rell": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "Mount/dismount changes CC. W mounted = knockup, dismounted = stun lock.",
        "aram": "R Ferromancy pull grouped enemies. Dismount W for stun in extended fights.",
    },
    "Renata Glasc": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "Passive Bailout: ally lives if kill while under effect. R Hostile Takeover makes enemies attack each other.",
        "aram": "R into grouped enemies makes them AoE each other — game-winning ability in ARAM.",
    },
    "Renekton": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "Empowered (50 fury) abilities. Empowered W stun, empowered E double dash.",
        "aram": "Build fury to 50 before trading. Empowered W into grouped enemies.",
    },
    "Rengar": {
        "dmg": "ad", "role": "assassin", "mana": False, "sustain": False,
        "mechanic": "4 stacks of ferocity empower next ability. Leap from brush. R Thrill of the Hunt reveals.",
        "aram": "Jump from brushes. 4-stack empowered W heal mid-fight. R to reveal then hunt.",
    },
    "Riven": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": False,
        "mechanic": "3-Q animation cancels with autos for CDR. W stun. R empowers then executes at low HP.",
        "aram": "Q3→auto animation cancel for max damage. R execute when below 50% HP.",
    },
    "Rumble": {
        "dmg": "ap", "role": "fighter", "mana": False, "sustain": False,
        "mechanic": "Overheat at 100 heat deals bonus magic damage. R Equalizer flame carpet is best AoE poke.",
        "aram": "R across the ARAM corridor for constant DoT. Stay at 80 heat for empowered abilities.",
    },
    "Ryze": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Flux (E) interacts with Q/W. Q reset on R-level. Build Seraph's first for mana scaling.",
        "aram": "Mana scales damage — max mana items. E+Q+W burst combo on a single target.",
    },
    # ── S ─────────────────────────────────────────────────────────────
    "Samira": {
        "dmg": "ad", "role": "marksman", "mana": False, "sustain": False,
        "mechanic": "Style grade A-S enables R Inferno Trigger. Mix melee and ranged for grade stacking.",
        "aram": "Grade up in skirmishes then R into grouped enemies. Build Immortal Shieldbow for safety.",
    },
    "Sejuani": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "W stacks frost on enemies hit. 4-hit by ally or E stuns frosted target. R mass stun.",
        "aram": "R mass stun is decisive. Stack frost with W, let team stun. Build Sunfire+Heartsteel.",
    },
    "Senna": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": True,
        "mechanic": "Passive stacks on kills/mists give AD/range/crit. R global shield + damage beam.",
        "aram": "Stack souls from kills. R global to save allies or pick low HP targets.",
    },
    "Seraphine": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "Note passive repeats ability near ally. R extends range from hitting allies.",
        "aram": "Chain R through allies for maximum range. Stage Presence notes amplify all abilities.",
    },
    "Sett": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "W Haymaker uses Grit HP for massive true damage. R Facebreaker slams grabbed target.",
        "aram": "Tank damage to build Grit, release W for burst. R grabs isolated carry into your team.",
    },
    "Shaco": {
        "dmg": "ad", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "Q blink and invisible for 3.5s. Boxes fear. R clone explodes on death.",
        "aram": "Boxes at chokepoints fear everything. Q from fog then burst. Clone baits abilities.",
    },
    "Shen": {
        "dmg": "ad", "role": "tank", "mana": False, "sustain": False,
        "mechanic": "Spirit Blade follows and empowers Q. W blocks all projectiles. R global shield.",
        "aram": "W blocks entire poke phase if aimed correctly. R to save a dying ally instantly.",
    },
    "Shyvana": {
        "dmg": "hybrid", "role": "fighter", "mana": False, "sustain": False,
        "mechanic": "Dragon Form on R. Dragon Q persistent AoE. AP build → dragon form AoE fireball burst.",
        "aram": "AP Shyvana is a mage in dragon form. R into grouped enemies with fireball AoE.",
    },
    "Singed": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": True,
        "mechanic": "Poison Trail: run through enemies. Fling throws target behind. R Insanity Potion.",
        "aram": "Run around in the corridor with poison on. Fling carries into your team.",
    },
    "Sion": {
        "dmg": "ad", "role": "tank", "mana": True, "sustain": False,
        "mechanic": "Q channels for bigger shield+knockup. W shield explodes for AoE. R unstoppable charge.",
        "aram": "R from behind for max speed. Q channel for full knockup combo. Build pure HP.",
    },
    "Sivir": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Q Boomerang Blade bounces back for double hit. W ricochets on multiple targets. R gives team MS.",
        "aram": "Spam Q for waveclear and poke. R gives your whole team MS for chase/escape.",
    },
    "Smolder": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Q stacks empowerment. Empowered abilities at 25/125/225 stacks.",
        "aram": "Stack Q aggressively. At 225+ stacks your AoE Q deletes grouped enemies.",
    },
    "Sona": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "Power Chord passive: 3 spell casts stacks for bonus auto effect. R Crescendo mass stun.",
        "aram": "R Crescendo stuns everyone in ARAM corridor. Spam Q poke; auto for Power Chord procs.",
    },
    "Soraka": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": True,
        "mechanic": "Q Starcall gives healing if hits enemy. R Wish global healing. Silence (E).",
        "aram": "E silence stops channeled ults. R global heal saves allies across the map.",
    },
    "Swain": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": True,
        "mechanic": "E roots then detonates for pull. R Demonic Ascension drains nearby enemies + heals.",
        "aram": "E root into team for pull onto grouped enemies. R in the middle of a fight heals you massively.",
    },
    "Sylas": {
        "dmg": "ap", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "Heals on Q double-hit. R Hijack steals enemy R. Best steal: Malphite, Orianna, Fiddle R.",
        "aram": "Steal the most impactful enemy R. Leash chained targets together with E.",
    },
    "Syndra": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "W throw orb or enemy minion. E stun. R Unleashed Power: max orbs → execute.",
        "aram": "Q spam to place orbs. E stun combo. R execute when 7 orbs are nearby.",
    },
    # ── T ─────────────────────────────────────────────────────────────
    "Tahm Kench": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": True,
        "mechanic": "W Devour: eat ally to protect or enemy to neutralize. Passive stacks on Q.",
        "aram": "W eat a carry who is about to die, then spit them out safe. W enemy carry neutralizes them.",
    },
    "Taliyah": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Q more powerful on worked ground. W seismic shove. R surfs on walls.",
        "aram": "Worked Ground punishes staying in place. W displacement is strong in ARAM.",
    },
    "Talon": {
        "dmg": "ad", "role": "assassin", "mana": True, "sustain": False,
        "mechanic": "W boomerang leaves bleed. Jump walls freely. R Shadow Assault invisible engage.",
        "aram": "R into backline then W+Q burst. W boomerang in corridor hits everyone going and coming back.",
    },
    "Taric": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": True,
        "mechanic": "All abilities chain to nearby linked ally. R Cosmic Radiance: invulnerability on self+linked ally.",
        "aram": "Link to highest-damage ally. R timed perfectly makes your carry unkillable.",
    },
    "Teemo": {
        "dmg": "ap", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "W run fast. Passive camouflage while still. Shrooms invisible AoE slow/damage.",
        "aram": "Shrooms at key chokepoints punish face-walking. Q blind disables ADCs. Build AP.",
    },
    "Thresh": {
        "dmg": "ap", "role": "support", "mana": False, "sustain": False,
        "mechanic": "Q hook-and-leap. W lantern for ally dash. E Flay in or out of hook. Build AP or tank.",
        "aram": "Hook carries; W lantern saves allies. E can interrupt engages. No mana — no mana items.",
    },
    "Tristana": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Stack E on tower/enemy. W jump = escape. E reset on kill. Range grows with level.",
        "aram": "Stack E on a target then all-in. W over enemy team for surprise burst.",
    },
    "Trundle": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "Q enhances next auto. W Frozen Domain. R Subjugate steals target's resistances.",
        "aram": "R on the enemy tank steals all their armor/MR. Build Sunfire for AoE damage.",
    },
    "Tryndamere": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": True,
        "mechanic": "Fury gives crit at max. R Undying Rage: cannot die for 5s. Play to full rage before trading.",
        "aram": "R when you would die — use those 5s to deal maximum damage. Build pure crit.",
    },
    "Twisted Fate": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Pick a Card: gold card stuns. R gate reveal + teleport globally.",
        "aram": "Gold Card W stun enables big combo. R for cross-map pressure even in ARAM.",
    },
    "Twitch": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Q go invisible, re-emerge with attack speed. E AoE expunge on stacked targets. R extended range + bonus AD.",
        "aram": "Q then R for extended range mowing through grouped enemies. Stack poison passively in corridor.",
    },
    # ── U ─────────────────────────────────────────────────────────────
    "Udyr": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "Phoenix stance AoE. Bear stance stun. Build tank+Sunfire for sustained fighter.",
        "aram": "Phoenix AoE is constant damage in ARAM. Bear stance stun to chain with teammates.",
    },
    "Urgot": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "Kneel passive shreds armor. W Purge minigun. R Fear Beyond Death hooks low HP target.",
        "aram": "W minigun mode in fights. R grab low HP targets for execute. Build Sunderer.",
    },
    # ── V ─────────────────────────────────────────────────────────────
    "Varus": {
        "dmg": "hybrid", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Q channel longer = more damage. E stacks blight for W detonation. R chains enemies together.",
        "aram": "R group root chains in ARAM. Stack blight with E+W burst. Q poke across bridge.",
    },
    "Vayne": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Q tumble before autos. 3-stack Silver Bolts vs tanks. Condemn into wall = stun. R invisibility.",
        "aram": "Every wall is a potential condemn stun. Focus healing/shields; Silver Bolts shreds tanks.",
    },
    "Veigar": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Stacks AP from kills and CS. E Event Horizon cage stuns edges.",
        "aram": "Place cage ON enemies to stun. R execute scales with your AP stacks.",
    },
    "Vel'Koz": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Q splitter: two projectiles at right angle. Research stacks = true damage passive.",
        "aram": "Spam Q/W across the corridor. True damage passive punishes beefy ARAM teamcomps.",
    },
    "Vex": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Passive fear on dash enemies near her. R resets on kills of marked targets.",
        "aram": "Fear dashes with passive — punishes mobile champions hard. R chain on low HP targets.",
    },
    "Vi": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "Q charge-knockback. R Assault and Battery: locked-onto target gets knocked up + team KU.",
        "aram": "R on carry then Q knockback anyone who touches you. Build Black Cleaver.",
    },
    "Viego": {
        "dmg": "ad", "role": "assassin", "mana": False, "sustain": True,
        "mechanic": "Possess dead enemies. Passive heals on possession. Abilities reset on possessing.",
        "aram": "Possess the most impactful enemy on death. Chain possessions in teamfights.",
    },
    "Viktor": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Evolve Q→E→W in order for most damage. W gravity field stuns after 1.5s.",
        "aram": "W in corridor entrance for guaranteed stun. Fully evolved E+R deletes grouped enemies.",
    },
    "Vladimir": {
        "dmg": "ap", "role": "mage", "mana": False, "sustain": True,
        "mechanic": "Q sustain + poke. No mana — never buy mana items. R marks, bonus damage on expiry.",
        "aram": "Free sustain with Q poke. R before team bursts for bonus damage multiplier.",
    },
    "Volibear": {
        "dmg": "ap", "role": "tank", "mana": True, "sustain": True,
        "mechanic": "R lightning strike disables turrets briefly. W bite stun. Passive massive HP regen at low HP.",
        "aram": "Passive regen at low HP makes you incredibly hard to kill. W bite frontliners.",
    },
    # ── W ─────────────────────────────────────────────────────────────
    "Warwick": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "Q Jaws of the Beast sustain. W trails low HP. R Infinite Duress full suppress.",
        "aram": "R suppress on a carry then W bite. Nearly unkillable with heal — enemy needs Grievous.",
    },
    "Wukong": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": False,
        "mechanic": "W clone decoy + invisibility. R Cyclone knock-up spins into crowd then resets.",
        "aram": "R twice into grouped enemies for two knockup waves. W to dodge key burst.",
    },
    # ── X ─────────────────────────────────────────────────────────────
    "Xayah": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Q+E feathers; W haste. Recall (R) is untargetable + recalls feathers for mass root.",
        "aram": "Scatter feathers in corridor then E pull through all of them for mass root.",
    },
    "Xerath": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Everything is skillshots. Max Q range. R infinite range artillery.",
        "aram": "R infinite-range from base. Q poke across bridge at max range. W AoE stun.",
    },
    "Xin Zhao": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "Q third hit knockup. R knocks back everyone but target. E airborne.",
        "aram": "R to knock back the whole enemy team except your chosen target. Build Shojin.",
    },
    # ── Y ─────────────────────────────────────────────────────────────
    "Yasuo": {
        "dmg": "ad", "role": "fighter", "mana": False, "sustain": False,
        "mechanic": "Windwall blocks all projectiles. E dash through minions/champions. R requires knockup.",
        "aram": "Windwall blocks entire poke in ARAM corridor. Coordinate R with any knockup ally.",
    },
    "Yone": {
        "dmg": "hybrid", "role": "fighter", "mana": False, "sustain": False,
        "mechanic": "E soul form for brief dash + armor. Q third hit knock-up. R AoE CC+teleport back.",
        "aram": "R from the back of your team for surprise engage across the whole corridor.",
    },
    "Yorick": {
        "dmg": "ad", "role": "fighter", "mana": True, "sustain": True,
        "mechanic": "Q heal when killing graves. E cage traps. Maiden autonomous lane pusher. R on Maiden.",
        "aram": "Spawn ghouls continuously. Maiden fights alongside you — near-unkillable in extended fights.",
    },
    "Yuumi": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "Attach to ally, untargetable while attached. Q slows. R stuns multiple enemies.",
        "aram": "Attach to your highest-damage champion. R stuns whole enemy team for your ADC to clean up.",
    },
    # ── Z ─────────────────────────────────────────────────────────────
    "Zac": {
        "dmg": "ap", "role": "tank", "mana": False, "sustain": True,
        "mechanic": "Passive blobs revive him at low HP. W slam. R Elastic Slingshot AoE bounces.",
        "aram": "R bounce through enemies for AoE knockups. Collect blobs or die permanently.",
    },
    "Zed": {
        "dmg": "ad", "role": "assassin", "mana": False, "sustain": False,
        "mechanic": "W shadow teleport, E slows. R Death Mark creates shadow; return to it after burst.",
        "aram": "W+R combo to burst a carry then escape with R shadow. Q in shadow clones hits all.",
    },
    "Zeri": {
        "dmg": "ad", "role": "marksman", "mana": True, "sustain": False,
        "mechanic": "Passive charges from shields. Q lightning reloads. E dash through walls. R Lighting Crash.",
        "aram": "E through terrain to reposition. R empowers whole team briefly.",
    },
    "Ziggs": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Q bounces. W Satchel Charge repositions self or enemies. R Mega Inferno Bomb from far.",
        "aram": "W self-reposition over walls. Q + W AoE demolishes grouped enemies. R from off-screen.",
    },
    "Zilean": {
        "dmg": "ap", "role": "support", "mana": True, "sustain": False,
        "mechanic": "Double bomb detonates. E speeds ally. R Chronoshift revives ally on death.",
        "aram": "R on your carry saves them from death. E speed to outrun or chase. Bombs slow + AoE.",
    },
    "Zoe": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "W picks up dropped summoner spells. Q arc amplifies on sleeping targets. E sleeps.",
        "aram": "Hit E sleep for guaranteed Q follow-up. Pick up summ spells for double Flash/Ignite.",
    },
    "Zyra": {
        "dmg": "ap", "role": "mage", "mana": True, "sustain": False,
        "mechanic": "Passive seeds spawned by abilities. Seed hit by Q/E grows plants.",
        "aram": "Seed entire corridor for plant wall. E+R = mass root+knockup for team cleanup.",
    },
}

# ── Role/damage category helpers ──────────────────────────────────────────────

TANKS   = {n for n, d in CHAMPIONS.items() if d["role"] == "tank"}
FIGHTERS = {n for n, d in CHAMPIONS.items() if d["role"] == "fighter"}
MAGES   = {n for n, d in CHAMPIONS.items() if d["role"] == "mage"}
ASSASSINS = {n for n, d in CHAMPIONS.items() if d["role"] == "assassin"}
MARKSMEN = {n for n, d in CHAMPIONS.items() if d["role"] == "marksman"}
SUPPORTS = {n for n, d in CHAMPIONS.items() if d["role"] == "support"}

AD_CHAMPS  = {n for n, d in CHAMPIONS.items() if d["dmg"] == "ad"}
AP_CHAMPS  = {n for n, d in CHAMPIONS.items() if d["dmg"] == "ap"}
HYBRID_CHAMPS = {n for n, d in CHAMPIONS.items() if d["dmg"] == "hybrid"}
SUSTAIN_CHAMPS = {n for n, d in CHAMPIONS.items() if d.get("sustain")}
MANA_CHAMPS = {n for n, d in CHAMPIONS.items() if d.get("mana")}
