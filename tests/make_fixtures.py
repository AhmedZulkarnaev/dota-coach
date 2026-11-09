"""Генерирует небольшой набор данных в формате OpenDota для офлайн-тестов и симулятора."""
import json, pathlib
here = pathlib.Path(__file__).parent / "fixtures"
here.mkdir(exist_ok=True)

I = {}  # name -> (id, cost, components, dname, attrib)
def add(name, id_, cost, comps=None, dname=None, attrib=None, tier=None):
    d = {"id": id_, "cost": cost, "dname": dname or name.replace("_"," ").title(),
         "components": comps, "created": bool(comps), "attrib": attrib or []}
    if tier: d["tier"] = tier
    I[name] = d
    if comps:
        rc = cost - sum(I[c]["cost"] for c in comps)
        if rc > 0:
            I["recipe_" + name] = {"id": id_ + 1000, "cost": rc, "dname": d["dname"] + " Recipe", "components": None, "created": False}

add("tango", 44, 90); add("flask", 39, 110); add("clarity", 38, 50); add("faerie_fire", 237, 65)
add("tpscroll", 46, 100, dname="Town Portal Scroll"); add("ward_observer", 42, 0); add("ward_sentry", 43, 50)
add("dust", 40, 80); add("branches", 16, 50, dname="Iron Branch")
add("quelling_blade", 11, 100); add("slippers", 14, 140, dname="Slippers of Agility")
add("circlet", 20, 155); add("gauntlets", 13, 140, dname="Gauntlets of Strength")
add("magic_stick", 34, 200); add("boots", 29, 500, dname="Boots of Speed")
add("gloves", 25, 450, dname="Gloves of Haste"); add("belt_of_strength", 26, 450)
add("boots_of_elves", 18, 450, dname="Band of Elvenskin"); add("blades_of_attack", 2, 450)
add("ogre_axe", 21, 1000, attrib=[{"key":"bonus_strength","value":"10","display":"+ {value} Strength"}])
add("mithril_hammer", 23, 1600); add("broadsword", 3, 1000); add("blade_of_alacrity", 19, 1000)
add("ultimate_orb", 24, 2800); add("demon_edge", 51, 2200); add("javelin", 7, 900)
add("vitality_booster", 47, 1000); add("point_booster", 22, 1500); add("platemail", 6, 1400)
add("hyperstone", 27, 2000); add("claymore", 4, 1350); add("reaver", 49, 2800)
add("morbid_mask", 52, 900); add("quarterstaff", 12, 875); add("robe", 17, 450)
add("magic_wand", 36, 450, ["magic_stick", "branches", "branches"])
add("wraith_band", 75, 505, ["slippers", "circlet"])
add("power_treads", 63, 1400, ["boots", "gloves", "belt_of_strength"],
    attrib=[{"key":"bonus_attack_speed","value":"25"}])
add("phase_boots", 50, 1500, ["boots", "blades_of_attack", "blades_of_attack"])
add("orb_of_venom", 181, 275)
add("orb_of_corrosion", 640, 925)
add("black_king_bar", 116, 4050, ["ogre_axe", "mithril_hammer"], dname="Black King Bar")
add("blink", 1, 2250, dname="Blink Dagger")
add("basher", 143, 2875, ["belt_of_strength", "mithril_hammer"], dname="Skull Basher")
add("abyssal_blade", 208, 6250, ["basher", "vitality_booster"], dname="Abyssal Blade")
add("diffusal_blade", 174, 2500, ["blade_of_alacrity", "robe", "robe"], dname="Diffusal Blade")
add("sange", 162, 2050, ["belt_of_strength", "ogre_axe"])
add("yasha", 170, 2050, ["blade_of_alacrity", "boots_of_elves"])
add("sange_and_yasha", 154, 4100, ["sange", "yasha"], dname="Sange and Yasha")
add("satanic", 156, 5050, ["morbid_mask", "claymore", "reaver"], dname="Satanic")
add("skadi", 160, 5300, ["ultimate_orb", "point_booster"], dname="Eye of Skadi")
add("monkey_king_bar", 135, 5000, ["demon_edge", "javelin"], dname="Monkey King Bar")
add("maelstrom", 166, 2950, ["gloves", "mithril_hammer"], dname="Maelstrom")
add("spirit_vessel", 267, 2780, ["vitality_booster", "robe"], dname="Spirit Vessel")
add("glimmer_cape", 254, 2150, ["robe", "quarterstaff"], dname="Glimmer Cape")
add("aghanims_shard", 609, 1400, dname="Aghanim's Shard")
add("ultimate_scepter", 108, 4200, ["point_booster", "ogre_axe", "blade_of_alacrity"], dname="Aghanim's Scepter")
add("butterfly", 139, 5450, ["blade_of_alacrity", "claymore", "javelin"], dname="Butterfly")
add("trusty_shovel", 1600, 0, tier=1)
(here / "items.json").write_text(json.dumps(I, indent=0))

heroes = {
 "70": {"id":70,"name":"npc_dota_hero_ursa","localized_name":"Ursa","primary_attr":"agi","roles":["Carry","Durable","Disabler"]},
 "26": {"id":26,"name":"npc_dota_hero_lion","localized_name":"Lion","primary_attr":"int","roles":["Support","Disabler","Nuker","Initiator"]},
 "27": {"id":27,"name":"npc_dota_hero_shadow_shaman","localized_name":"Shadow Shaman","primary_attr":"int","roles":["Support","Pusher","Disabler","Nuker","Initiator"]},
 "7":  {"id":7,"name":"npc_dota_hero_earthshaker","localized_name":"Earthshaker","primary_attr":"str","roles":["Support","Initiator","Disabler","Nuker"]},
 "44": {"id":44,"name":"npc_dota_hero_phantom_assassin","localized_name":"Phantom Assassin","primary_attr":"agi","roles":["Carry","Escape"]},
 "36": {"id":36,"name":"npc_dota_hero_necrolyte","localized_name":"Necrophos","primary_attr":"int","roles":["Carry","Nuker","Durable","Disabler"]},
 "32": {"id":32,"name":"npc_dota_hero_riki","localized_name":"Riki","primary_attr":"agi","roles":["Carry","Escape","Disabler"]},
}
(here / "heroes.json").write_text(json.dumps(heroes, indent=0))

def ids(*names): return {str(I[n]["id"]): c for n, c in names}
pop = {
 "start_game_items": ids(("tango",900),("quelling_blade",850),("branches",800),("slippers",500),("flask",450),("circlet",300),("ward_observer",100)),
 "early_game_items": ids(("magic_wand",700),("power_treads",650),("phase_boots",300),("wraith_band",400),("orb_of_corrosion",350),("boots",600),("blink",200),("gloves",250),("ogre_axe",150)),
 "mid_game_items": ids(("blink",600),("basher",560),("black_king_bar",520),("diffusal_blade",300),("sange_and_yasha",250),("aghanims_shard",200),("monkey_king_bar",50)),
 "late_game_items": ids(("abyssal_blade",500),("satanic",420),("skadi",300),("butterfly",200),("ultimate_scepter",180),("monkey_king_bar",120)),
}
(here / "pop_70.json").write_text(json.dumps(pop, indent=0))
print("ok", len(I), "items")

abilities = {
 "ursa_earthshock": {"dname": "Earthshock", "behavior": ["No Target", "AOE"], "dmg_type": "Magical",
                     "desc": "Ursa slams the earth, causing a powerful shock to damage and slow all enemies in a nearby radius."},
 "ursa_overpower": {"dname": "Overpower", "behavior": "No Target", "desc": "Gives bonus attack speed for a number of attacks."},
 "ursa_fury_swipes": {"dname": "Fury Swipes", "behavior": "Passive", "desc": "Each attack deals more damage."},
 "ursa_enrage": {"dname": "Enrage", "behavior": "No Target", "desc": "Reduces incoming damage and applies a strong dispel."},
 "mirana_arrow": {"dname": "Sacred Arrow", "behavior": ["Point Target"], "dmg_type": "Magical",
                  "desc": "Fires a long-range arrow that will stun and damage the first enemy unit it strikes."},
 "mirana_leap": {"dname": "Leap", "behavior": "No Target", "desc": "Mirana leaps forward into battle."},
 "mirana_starfall": {"dname": "Starfall", "behavior": "No Target", "desc": "Calls down a wave of meteors to damage nearby enemy units."},
}
(here / "abilities.json").write_text(json.dumps(abilities, indent=0))
