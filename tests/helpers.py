"""Общие заготовки для тестов: подставное хранилище данных и JSON «как от
Dota».
"""

import json
import pathlib

FIX = pathlib.Path(__file__).parent / "fixtures"
IN_PROGRESS = "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"
PRE_GAME = "DOTA_GAMERULES_STATE_PRE_GAME"
POST_GAME = "DOTA_GAMERULES_STATE_POST_GAME"


class FakeStore:
    def __init__(self):
        self.items = json.loads((FIX / "items.json").read_text())
        self.heroes = json.loads((FIX / "heroes.json").read_text())
        self.pop = {70: json.loads((FIX / "pop_70.json").read_text())}
        self.abilities = json.loads((FIX / "abilities.json").read_text())

    def get_popularity(self, hero_id):
        return self.pop.get(hero_id)

    def is_loading(self, hero_id):
        return False


def payload(clock, gold, items=(), stash=(), tp=True, state=IN_PROGRESS):
    slots = {f"slot{i}": {"name": "empty"} for i in range(9)}
    for i, it in enumerate(items):
        slots[f"slot{i}"] = {"name": "item_" + it}
    for i, it in enumerate(stash):
        slots[f"stash{i}"] = {"name": "item_" + it}
    slots["teleport0"] = {"name": "item_tpscroll" if tp else "empty"}
    return {
        "map": {"matchid": "123", "game_state": state, "clock_time": clock},
        "player": {
            "team_name": "radiant",
            "gold": gold,
            "kills": 1,
            "deaths": 0,
            "assists": 2,
            "last_hits": 40,
        },
        "hero": {
            "id": 70,
            "name": "npc_dota_hero_ursa",
            "level": 8,
            "alive": True,
        },
        "items": slots,
        "auth": {"token": "x"},
    }


def with_abilities(p, abil, hp=100, mana=100):
    p["hero"]["health_percent"], p["hero"]["mana_percent"] = hp, mana
    p["abilities"] = {f"ability{i}": dict(a) for i, a in enumerate(abil)}
    return p


URSA = [
    {
        "name": "ursa_earthshock",
        "level": 2,
        "can_cast": True,
        "passive": False,
        "cooldown": 0,
        "ultimate": False,
    },
    {
        "name": "ursa_overpower",
        "level": 1,
        "can_cast": False,
        "passive": False,
        "cooldown": 7,
        "ultimate": False,
    },
    {
        "name": "ursa_fury_swipes",
        "level": 2,
        "can_cast": False,
        "passive": True,
        "cooldown": 0,
        "ultimate": False,
    },
    {
        "name": "ursa_enrage",
        "level": 1,
        "can_cast": True,
        "passive": False,
        "cooldown": 0,
        "ultimate": True,
    },
    {
        "name": "special_bonus_unique_ursa",
        "level": 0,
        "can_cast": False,
        "passive": True,
        "cooldown": 0,
    },
]
