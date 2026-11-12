"""Совет не прыгает с предмета на предмет, а список покупок понятен.

Тесты «верности цели» (coach/commitment.py), плавных весов стадий, списка
покупок (coach/shopping.py) и «послушного игрока» (tests/follower.py),
который проходит матч, покупая ровно то, что советует программа.
"""

import unittest

from coach.advisor import Advisor, stage_weight
from coach.commitment import SWITCH_MARGIN, Commitment, choose_target
from coach.game_state import parse
from coach.item_db import ItemDB
from coach.recorder import Recording
from coach.replay import replay
from coach.shopping import HAVE, LATER, NOW, RECIPE, shopping_list
from tests.follower import follow
from tests.helpers import FakeStore, payload

ENEMY_SETS = (
    (),
    ("lion", "shadow_shaman", "earthshaker"),
    ("phantom_assassin", "necrolyte"),
)


def db():
    return ItemDB(FakeStore().items)


class StageWeightTest(unittest.TestCase):
    def test_no_jumps_at_stage_borders(self):
        for stage in ("lane", "mid", "late"):
            for border in (600, 1800):
                before = stage_weight(stage, border - 1)
                after = stage_weight(stage, border)
                self.assertLess(abs(before - after), 0.01, (stage, border))

    def test_shape(self):
        self.assertEqual(stage_weight("mid", 900), 1.0)
        self.assertAlmostEqual(stage_weight("mid", 0), 0.6)
        self.assertAlmostEqual(stage_weight("lane", 1200), 0.5)
        self.assertEqual(stage_weight("lane", 2400), 0.0)
        self.assertEqual(stage_weight("late", 0), 0.0)


class ChooseTargetTest(unittest.TestCase):
    def choose(
        self, ranked, prev=None, owned=(), enemies=(), role="core", clock=900
    ):
        return choose_target(
            ranked,
            prev,
            match_id="1",
            clock=clock,
            owned=list(owned),
            enemies=enemies,
            role=role,
            db=db(),
        )

    def commit(self, target, owned=(), enemies=(), role="core", clock=880):
        return self.choose(
            [(target, 1.0)],
            owned=owned,
            enemies=enemies,
            role=role,
            clock=clock,
        ).commitment

    def test_first_choice_is_best(self):
        c = self.choose([("blink", 1.0), ("black_king_bar", 0.9)])
        self.assertEqual((c.target, c.note), ("blink", ""))

    def test_keeps_target_when_other_slightly_better(self):
        prev = self.commit("blink")
        c = self.choose([("black_king_bar", 1.4), ("blink", 1.0)], prev)
        self.assertEqual((c.target, c.note), ("blink", ""))

    def test_switches_when_much_better(self):
        prev = self.commit("blink")
        c = self.choose(
            [("black_king_bar", SWITCH_MARGIN + 0.01), ("blink", 1.0)], prev
        )
        self.assertEqual(c.target, "black_king_bar")
        self.assertIn("Сейчас важнее Black King Bar", c.note)

    def test_completed_target_says_so(self):
        prev = self.commit("blink")
        c = self.choose([("black_king_bar", 1.0)], prev, owned=["blink"])
        self.assertEqual(
            c.note, "Blink Dagger собран — следующий: Black King Bar."
        )

    def test_follows_players_own_purchase(self):
        prev = self.commit("blink", owned=["magic_wand"])
        c = self.choose(
            [("black_king_bar", 1.1), ("blink", 1.0)],
            prev,
            owned=["magic_wand", "ogre_axe"],
        )
        self.assertEqual(c.target, "black_king_bar")
        self.assertIn("Вы купили Ogre Axe", c.note)

    def test_buying_parts_of_target_is_not_deviation(self):
        prev = self.commit("black_king_bar")
        c = self.choose(
            [("blink", 1.3), ("black_king_bar", 1.0)], prev, owned=["ogre_axe"]
        )
        self.assertEqual(c.target, "black_king_bar")

    def test_cheap_consumables_are_not_deviation(self):
        prev = self.commit("blink")
        c = self.choose(
            [("black_king_bar", 1.3), ("blink", 1.0)],
            prev,
            owned=["tango", "ward_observer", "branches"],
        )
        self.assertEqual(c.target, "blink")

    def test_enemies_or_role_change_reevaluates(self):
        prev = self.commit("blink")
        c = self.choose(
            [("black_king_bar", 1.2), ("blink", 1.0)], prev, enemies=("lion",)
        )
        self.assertEqual(c.target, "black_king_bar")
        self.assertEqual(c.note, "Совет пересчитан под врагов.")
        c = self.choose(
            [("black_king_bar", 1.2), ("blink", 1.0)], prev, role="support"
        )
        self.assertEqual(c.note, "Совет пересчитан под роль.")

    def test_target_no_longer_candidate(self):
        prev = self.commit("magic_wand")
        c = self.choose([("blink", 1.0)], prev)
        self.assertIn("Magic Wand уже не в приоритете", c.note)

    def test_new_match_or_time_backwards_starts_fresh(self):
        prev = Commitment("другой", "blink", 880, frozenset(), (), "core")
        c = self.choose([("black_king_bar", 1.1), ("blink", 1.0)], prev)
        self.assertEqual((c.target, c.note), ("black_king_bar", ""))
        prev = self.commit("blink", clock=1500)
        c = self.choose(
            [("black_king_bar", 1.1), ("blink", 1.0)], prev, clock=300
        )
        self.assertEqual((c.target, c.note), ("black_king_bar", ""))


class FollowerTest(unittest.TestCase):
    """Игрок покупает ровно то, что советуют: цель не должна прыгать."""

    def test_no_jumps_across_scenarios(self):
        for enemies in ENEMY_SETS:
            for gpm in (350, 450, 600):
                run = follow(Advisor(FakeStore()), enemies, gpm=gpm)
                self.assertEqual(run.jumps, [], (enemies, gpm))
                self.assertGreaterEqual(len(run.completed), 3, (enemies, gpm))

    def test_boots_before_bkb_even_against_disables(self):
        run = follow(Advisor(FakeStore()), ENEMY_SETS[1], gpm=450)
        order = [t for _, t in run.targets]
        self.assertLess(
            order.index("power_treads"), order.index("black_king_bar")
        )
        bkb_at = {t: c for c, t in run.targets}["black_king_bar"]
        self.assertLess(
            bkb_at, 600
        )  # но против контроля BKB всё равно до 10:00

    def test_assembled_items_stay_candidates(self):
        # Skull Basher — сам по себе предмет, а не «деталь» Abyssal Blade.
        run = follow(Advisor(FakeStore()), gpm=600)
        self.assertIn("basher", [t for _, t in run.completed])


class ReplayFlipTest(unittest.TestCase):
    def test_flip_flop_is_a_violation(self):
        class Swinging(Advisor):
            def advise(self, gs, enemy_shorts=(), role_setting="auto"):
                a = super().advise(gs, enemy_shorts, role_setting)
                if a.status == "ok":  # каждые 30 с меняет цель туда-сюда
                    a.target = (
                        "blink" if gs.clock // 30 % 2 else "black_king_bar"
                    )
                    a.target_title = a.target
                return a

        packets = [
            (float(c), payload(c, 100, items=["magic_wand"]))
            for c in range(600, 800, 10)
        ]
        result = replay(
            Recording({"format": "x"}, packets), Swinging(FakeStore())
        )
        self.assertIn("flip", {v.rule for v in result.violations})

    def test_switch_note_in_events(self):
        packets = [
            (0.0, payload(900, 300, items=["magic_wand", "power_treads"])),
            (
                1.0,
                payload(
                    910, 300, items=["magic_wand", "power_treads", "blink"]
                ),
            ),
        ]
        result = replay(
            Recording({"format": "x"}, packets), Advisor(FakeStore())
        )
        notes = [e.text for e in result.events if e.kind == "смена"]
        self.assertTrue(
            any("Blink Dagger собран" in n for n in notes), result.events
        )


class ShoppingListTest(unittest.TestCase):
    def states(self, shop):
        return [(p.title, p.state) for p in shop.parts]

    def test_saving_for_cheapest_part(self):
        shop = shopping_list("black_king_bar", ["ogre_axe"], 300, db())
        self.assertEqual(
            self.states(shop),
            [
                ("Ogre Axe", HAVE),
                ("Mithril Hammer", LATER),
                ("Рецепт", RECIPE),
            ],
        )
        self.assertEqual(
            shop.next_step, "Копите на Mithril Hammer: не хватает 1 300."
        )
        self.assertEqual(shop.buy_now, [])
        self.assertEqual(shop.remaining, 3050)

    def test_buy_part_now_recipe_last(self):
        shop = shopping_list("black_king_bar", ["ogre_axe"], 1700, db())
        self.assertEqual(self.states(shop)[1], ("Mithril Hammer", NOW))
        self.assertEqual(self.states(shop)[2], ("Рецепт", RECIPE))
        self.assertEqual(shop.next_step, "Купите сейчас: Mithril Hammer.")
        self.assertEqual(shop.buy_now, [("Mithril Hammer", 1600)])

    def test_enough_for_everything(self):
        shop = shopping_list("black_king_bar", ["ogre_axe"], 3100, db())
        self.assertTrue(all(p.state in (HAVE, NOW) for p in shop.parts))
        self.assertIn("предмет соберётся сам", shop.next_step)

    def test_single_item(self):
        self.assertEqual(
            shopping_list("blink", [], 2300, db()).next_step,
            "Купите Blink Dagger — 2 250.",
        )
        self.assertEqual(
            shopping_list("blink", [], 250, db()).next_step,
            "Копите на Blink Dagger: не хватает 2 000.",
        )

    def test_only_recipe_left(self):
        shop = shopping_list(
            "black_king_bar", ["ogre_axe", "mithril_hammer"], 100, db()
        )
        self.assertEqual(
            shop.next_step, "Осталось купить рецепт: не хватает 1 350."
        )

    def test_no_room_means_save_for_whole(self):
        shop = shopping_list(
            "black_king_bar", ["ogre_axe"], 1700, db(), no_room=True
        )
        self.assertEqual(shop.buy_now, [])
        self.assertIn("целиком", shop.next_step)

    def test_advice_carries_shopping_list(self):
        a = Advisor(FakeStore()).advise(
            parse(
                payload(
                    900, 1700, items=["magic_wand", "power_treads", "ogre_axe"]
                )
            )
        )
        self.assertEqual(a.target, "black_king_bar")
        self.assertEqual(a.next_step, "Купите сейчас: Mithril Hammer.")
        self.assertEqual([p.state for p in a.parts], [HAVE, NOW, RECIPE])


if __name__ == "__main__":
    unittest.main()
