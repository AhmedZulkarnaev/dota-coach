"""Офлайн-тесты движка советов на фикстурах. Запуск: python -m unittest discover tests"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coach.advisor import Advisor            # noqa: E402
from coach.game_state import parse           # noqa: E402
from coach.item_db import ItemDB             # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures"


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


def payload(clock, gold, items=(), stash=(), tp=True, state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"):
    slots = {f"slot{i}": {"name": "empty"} for i in range(9)}
    for i, it in enumerate(items):
        slots[f"slot{i}"] = {"name": "item_" + it}
    for i, it in enumerate(stash):
        slots[f"stash{i}"] = {"name": "item_" + it}
    slots["teleport0"] = {"name": "item_tpscroll" if tp else "empty"}
    return {
        "map": {"matchid": "123", "game_state": state, "clock_time": clock},
        "player": {"team_name": "radiant", "gold": gold, "kills": 1, "deaths": 0, "assists": 2, "last_hits": 40},
        "hero": {"id": 70, "name": "npc_dota_hero_ursa", "level": 8, "alive": True},
        "items": slots,
        "auth": {"token": "x"},
    }


class ItemDBTest(unittest.TestCase):
    def setUp(self):
        self.db = ItemDB(FakeStore().items)

    def test_plan_with_owned_component(self):
        leaves, used = self.db.plan("black_king_bar", ["ogre_axe"])
        self.assertEqual(used, ["ogre_axe"])
        self.assertIn("mithril_hammer", leaves)
        self.assertIn("recipe_black_king_bar", leaves)
        self.assertEqual(self.db.remaining_cost("black_king_bar", ["ogre_axe"]), 3050)

    def test_nested_plan(self):
        # Abyssal = Basher(belt + hammer + рецепт) + Vitality + рецепт
        leaves, _ = self.db.plan("abyssal_blade", ["belt_of_strength"])
        self.assertNotIn("belt_of_strength", leaves)
        self.assertIn("mithril_hammer", leaves)
        self.assertEqual(sum(self.db.cost(x) for x in leaves), 6250 - 450)

    def test_duplicate_components(self):
        leaves, used = self.db.plan("magic_wand", ["branches"])
        self.assertEqual(used, ["branches"])
        self.assertEqual(leaves.count("branches"), 1)

    def test_neutral_not_in_shop(self):
        self.assertFalse(self.db.is_shop_item("trusty_shovel"))
        self.assertFalse(self.db.is_shop_item("recipe_black_king_bar"))


class AdvisorTest(unittest.TestCase):
    def setUp(self):
        self.adv = Advisor(FakeStore())

    def advise(self, *a, enemies=(), **kw):
        return self.adv.advise(parse(payload(*a, **kw)), enemies)

    def test_start(self):
        a = self.advise(-80, 600, state="DOTA_GAMERULES_STATE_PRE_GAME")
        self.assertEqual(a.status, "start")
        self.assertLessEqual(sum(c for _, c in a.start_bundle), 600)
        self.assertNotIn("Observer Ward", [t for t, _ in a.start_bundle])

    def test_lane_first_item(self):
        a = self.advise(120, 300, items=["tango", "quelling_blade", "wraith_band"])
        self.assertEqual(a.status, "ok")
        self.assertIn(a.target, ("magic_wand", "power_treads"))
        self.assertTrue(a.why)

    def test_owned_not_recommended_and_boots_once(self):
        a = self.advise(480, 900, items=["magic_wand", "power_treads", "wraith_band"])
        self.assertNotIn(a.target, ("magic_wand", "power_treads", "phase_boots", "boots"))

    def test_partial_build_preferred(self):
        a = self.advise(900, 500, items=["magic_wand", "power_treads", "ogre_axe"])
        self.assertEqual(a.target, "black_king_bar")
        self.assertEqual(a.remaining, 3050)
        self.assertFalse(a.can_buy_full)
        self.assertIn("Уже есть Ogre Axe", a.why)
        self.assertIn("Иммунитет", a.what)

    def test_buy_now(self):
        a = self.advise(900, 1700, items=["magic_wand", "power_treads", "ogre_axe"])
        self.assertIn(("Mithril Hammer", 1600), a.buy_now)
        a = self.advise(900, 3100, items=["magic_wand", "power_treads", "ogre_axe"])
        self.assertTrue(a.can_buy_full)

    def test_components_hidden(self):
        a = self.advise(900, 0, items=["magic_wand", "power_treads"])
        self.assertNotIn(a.target, ("ogre_axe", "mithril_hammer", "gloves"))

    def test_enemy_disables_push_bkb(self):
        a = self.advise(1000, 0, items=["magic_wand", "power_treads", "blink"],
                        enemies=["lion", "shadow_shaman", "earthshaker"])
        self.assertEqual(a.target, "black_king_bar")
        self.assertIn("контрол", a.why)

    def test_evasion_situational(self):
        a = self.advise(1000, 0, items=["magic_wand", "power_treads"], enemies=["phantom_assassin"])
        titles = [t for t, _ in a.situational] + [a.target_title]
        self.assertIn("Monkey King Bar", titles)

    def test_reminders(self):
        a = self.advise(400, 1000, items=["magic_wand"], tp=False)
        text = " ".join(a.reminders)
        self.assertIn("TP", text)
        self.assertIn("ботинок", text)

    def test_stash_counts_as_owned(self):
        a = self.advise(900, 0, items=["magic_wand", "power_treads"], stash=["ogre_axe"])
        self.assertEqual(a.target, "black_king_bar")


class SlotsTest(unittest.TestCase):
    def setUp(self):
        self.adv = Advisor(FakeStore())

    def test_full_of_junk_suggests_what_to_remove(self):
        items = ["tango", "branches", "quelling_blade", "wraith_band", "magic_wand", "power_treads"]
        a = self.adv.advise(parse(payload(1000, 500, items=items)))
        self.assertEqual(a.slots_main, 6)
        self.assertTrue(a.free_up, "должен подсказать, что убрать")
        removed = [t for _, t in a.free_up]
        self.assertNotIn("Power Treads", removed)          # ботинки не трогаем
        self.assertEqual(a.free_up[0], ("используйте", "Tango"))   # Tango не продают, а съедают
        self.assertIn("используйте Tango", a.free_up_text)

    def test_full_of_strong_items_no_cheap_advice(self):
        items = ["power_treads", "black_king_bar", "abyssal_blade", "satanic", "skadi", "butterfly"]
        a = self.adv.advise(parse(payload(2400, 3000, items=items)))
        # Shard слот не занимает — его советовать можно, остальное было бы ухудшением
        self.assertEqual(a.target, "aghanims_shard")
        self.assertEqual(a.free_up, [])
        p = payload(2400, 3000, items=items)
        p["hero"]["aghanims_shard"] = True
        a = self.adv.advise(parse(p))
        self.assertEqual(a.status, "done")
        self.assertIn("6 слотов", a.why)

    def test_component_in_sixth_slot_needs_no_space(self):
        items = ["magic_wand", "power_treads", "wraith_band", "blink", "quelling_blade", "ogre_axe"]
        a = self.adv.advise(parse(payload(1000, 500, items=items)))
        self.assertEqual(a.target, "black_king_bar")
        self.assertEqual(a.free_up, [])                   # Ogre Axe уйдёт в сборку

    def test_sell_makes_it_affordable(self):
        items = ["branches", "branches", "quelling_blade", "wraith_band", "magic_wand", "power_treads"]
        a = self.adv.advise(parse(payload(1000, 2240, items=items)))
        self.assertEqual(a.target, "blink")               # 2250, не хватает 10
        self.assertFalse(a.can_buy_full)
        self.assertTrue(a.can_buy_with_sell)              # продажа Iron Branch даёт +25

    def test_backpack_does_not_block_active_slots(self):
        # 5 активных + мусор в рюкзаке: шестой слот свободен, ничего убирать не надо
        p = payload(1000, 500, items=["magic_wand", "power_treads", "wraith_band", "blink", "quelling_blade"])
        p["items"]["slot6"] = {"name": "item_branches"}
        p["items"]["slot7"] = {"name": "item_branches"}
        a = self.adv.advise(parse(p))
        self.assertEqual(a.slots_main, 5)
        self.assertEqual(a.free_up, [])

    def test_wards_are_placed_not_sold(self):
        items = ["ward_observer", "magic_wand", "power_treads", "wraith_band", "blink", "quelling_blade"]
        a = self.adv.advise(parse(payload(1000, 500, items=items)))
        self.assertIn(("поставьте", "Ward Observer"), a.free_up)

    def test_shard_already_eaten(self):
        p = payload(1000, 0, items=["magic_wand", "power_treads", "black_king_bar", "blink", "basher"])
        p["hero"]["aghanims_shard"] = True
        a = self.adv.advise(parse(p))
        self.assertNotIn("Aghanim's Shard", [a.target_title] + a.next_items)


class ParseTest(unittest.TestCase):
    def test_spectator_detected(self):
        gs = parse({"map": {"clock_time": 5}, "player": {"team2": {"player0": {}}}})
        self.assertTrue(gs.spectating)
        self.assertFalse(gs.valid)

    def test_player_with_team_name_is_valid(self):
        gs = parse(payload(100, 500))
        self.assertTrue(gs.valid)
        self.assertFalse(gs.spectating)

    def test_stage(self):
        self.assertEqual(parse(payload(-30, 0)).stage, "start")
        self.assertEqual(parse(payload(599, 0)).stage, "lane")
        self.assertEqual(parse(payload(600, 0)).stage, "mid")
        self.assertEqual(parse(payload(1800, 0)).stage, "late")


def with_abilities(p, abil, hp=100, mana=100):
    p["hero"]["health_percent"], p["hero"]["mana_percent"] = hp, mana
    p["abilities"] = {f"ability{i}": dict(a) for i, a in enumerate(abil)}
    return p


URSA = [
    {"name": "ursa_earthshock", "level": 2, "can_cast": True, "passive": False, "cooldown": 0, "ultimate": False},
    {"name": "ursa_overpower", "level": 1, "can_cast": False, "passive": False, "cooldown": 7, "ultimate": False},
    {"name": "ursa_fury_swipes", "level": 2, "can_cast": False, "passive": True, "cooldown": 0, "ultimate": False},
    {"name": "ursa_enrage", "level": 1, "can_cast": True, "passive": False, "cooldown": 0, "ultimate": True},
    {"name": "special_bonus_unique_ursa", "level": 0, "can_cast": False, "passive": True, "cooldown": 0},
]


class AbilityTest(unittest.TestCase):
    def setUp(self):
        self.adv = Advisor(FakeStore())

    def test_curated_lines_and_states(self):
        a = self.adv.advise(parse(with_abilities(payload(700, 0), URSA)))
        titles = [t for t, _, _ in a.ability_lines]
        self.assertEqual(titles, ["Earthshock", "Overpower", "Fury Swipes", "Enrage (ульт)"])  # без талантов
        states = {t: st for t, _, st in a.ability_lines}
        self.assertEqual(states["Overpower"], "перезарядка 7 с")
        self.assertEqual(states["Fury Swipes"], "пассивная")
        self.assertTrue(any("Ульт Enrage готов" in x for x in a.ability_live))

    def test_low_hp_suggests_defensive(self):
        a = self.adv.advise(parse(with_abilities(payload(700, 0), URSA, hp=20)))
        self.assertIn("нажмите Enrage", a.ability_live[0])

    def test_low_mana(self):
        a = self.adv.advise(parse(with_abilities(payload(700, 0), URSA, mana=10)))
        self.assertTrue(any("Мало маны" in x for x in a.ability_live))

    def test_generic_classification(self):
        from coach.abilities import tip_for, classify
        ab = FakeStore().abilities
        self.assertIn("disable", classify("mirana_arrow", ab))
        self.assertIn("Контроль", tip_for("mirana_arrow", ab))
        self.assertIn("escape", classify("mirana_leap", ab))
        self.assertTrue(tip_for("mirana_starfall", ab, ultimate=True).startswith("Ульт"))


if __name__ == "__main__":
    unittest.main()
