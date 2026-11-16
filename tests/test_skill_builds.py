"""Прокачка: из матчей OpenDota — в подсказку «что качать сейчас»."""

import json
import random
import tempfile
import unittest
import urllib.error
from pathlib import Path

from coach.data_store import DataStore
from coach.engine import CoachEngine
from coach.game_state import parse
from coach.skill_builds import (
    ATTRIBUTES,
    POINT_LEVELS,
    Step,
    build_from_match,
    can_learn,
    consensus,
    free_points,
    next_step,
    points_earned,
    skill_hint,
)
from coach.speech_ru import speakable
from tests.helpers import URSA, FakeStore, payload, with_abilities
from tools.skill_build import find_hero, format_plan

Q, W, E, R = (
    "ursa_earthshock",
    "ursa_overpower",
    "ursa_fury_swipes",
    "ursa_enrage",
)
T10, T10B = "special_bonus_unique_ursa_10", "special_bonus_attack_speed_25"
T15, T15B = "special_bonus_unique_ursa_15", "special_bonus_hp_250"
URSA_BUILD = [E, Q, E, W, E, R, E, W, W, T10, W, R, Q, Q, T15, Q, R]
IDS = {"5357": Q, "5358": W, "5359": E, "5360": R, "6000": T10, "6001": T15}


def rules_ok(build):
    """Не нарушает ли порядок правила Dota (для обычного героя)."""
    seen: dict[str, int] = {}
    tiers: set[int] = set()
    for i, name in enumerate(build):
        level = POINT_LEVELS[i]
        seen[name] = seen.get(name, 0) + 1
        n = seen[name]
        if name.startswith("special_bonus"):
            tier = int(name.rsplit("_", 1)[-1].rstrip("lr"))
            if level < tier or tier in tiers:
                return False
            tiers.add(tier)
        elif name == R:
            if level < 6 * n or n > 3:
                return False
        elif n > 4 or n > (level + 1) // 2:
            return False
    return True


def random_build(rng, length=19):
    """Случайный допустимый порядок прокачки с «любимой» способностью."""
    order = rng.sample([Q, W, E], 3)
    build: list[str] = []
    for i in range(length):
        level = POINT_LEVELS[i]
        talents = [
            f"special_bonus_x_{t}{side}"
            for t in (10, 15, 20, 25)
            for side in "lr"
            if t <= level
            and not any(b.startswith(f"special_bonus_x_{t}") for b in build)
        ]
        options = [R] + talents + order
        options = [o for o in options if rules_ok([*build, o])]
        weights = [6 if o == R else 4 if o in talents else 1 for o in options]
        if order[0] in options:
            weights[options.index(order[0])] += 3
        build.append(rng.choices(options, weights)[0])
    return build


def gs_with(levels, hero_level, hero_extra=None):
    p = payload(300, 600, ("tango",))
    p["hero"]["level"] = hero_level
    p["hero"].update(hero_extra or {})
    abil = [dict(a) for a in URSA]
    for a in abil:
        a["level"] = levels.get(a["name"], 0)
    return parse(with_abilities(p, abil))


class ConsensusTest(unittest.TestCase):
    def test_build_from_match(self):
        match = {
            "players": [
                {"hero_id": 1, "ability_upgrades_arr": [1, 2]},
                {"hero_id": 70, "ability_upgrades_arr": [5359, 5357, 6000]},
            ]
        }
        self.assertEqual(build_from_match(match, 70, IDS), [E, Q, T10])
        self.assertIsNone(build_from_match(match, 2, IDS))  # нет героя
        match["players"][1]["ability_upgrades_arr"] = None  # не разобран
        self.assertIsNone(build_from_match(match, 70, IDS))
        match["players"][1]["ability_upgrades_arr"] = [9999]
        self.assertIsNone(build_from_match(match, 70, IDS))

    def test_unanimous_builds_give_the_same_plan(self):
        plan = consensus([URSA_BUILD] * 5)
        self.assertEqual([s.name for s in plan], URSA_BUILD)
        self.assertEqual((plan[0].votes, plan[0].total), (5, 5))
        self.assertEqual(plan[16].level, 18)  # на 17-м уровне очка нет

    def test_majority_wins_and_short_tails_are_dropped(self):
        other = [Q, *URSA_BUILD[1:]]
        plan = consensus([URSA_BUILD] * 3 + [other] * 2 + [URSA_BUILD[:5]])
        self.assertEqual(plan[0].name, E)
        self.assertEqual((plan[0].votes, plan[0].total), (4, 6))
        self.assertEqual(consensus([URSA_BUILD[:3]] * 2), [])

    def test_plan_never_breaks_dota_rules(self):
        rng = random.Random(7)
        for _ in range(300):
            builds = [random_build(rng) for _ in range(rng.randint(3, 15))]
            self.assertTrue(all(rules_ok(b) for b in builds))
            plan = [s.name for s in consensus(builds)]
            self.assertTrue(rules_ok(plan), plan)
            self.assertEqual(len(plan), 19)


class NextStepTest(unittest.TestCase):
    PLAN = consensus([URSA_BUILD] * 5)

    def test_follows_the_plan(self):
        step, new, now = next_step(self.PLAN, {E: 1}, 2, [R])
        self.assertEqual((step.name, new, now), (Q, 1, True))

    def test_player_went_own_way(self):
        # Взял Overpower вместо Earthshock — план продолжается дальше.
        step, new, now = next_step(self.PLAN, {E: 1, W: 1}, 2, [R])
        self.assertEqual((step.name, new, now), (Q, 1, True))
        # На 3-м уровне: Fury Swipes 2 по плану, а Earthshock можно и позже.
        step, _, _ = next_step(self.PLAN, {E: 1, W: 1, Q: 1}, 3, [R])
        self.assertEqual(step.name, E)

    def test_nothing_allowed_yet(self):
        levels = {E: 4, Q: 1, W: 1}  # уровень 5, но очки потрачены вперёд
        step, new, now = next_step(self.PLAN, levels, 5, [R])
        self.assertEqual((step.name, now), (W, True))
        step, new, now = next_step(self.PLAN, {E: 4, Q: 4, W: 4}, 5, [R])
        self.assertEqual((step.name, new, now), (R, 1, False))

    def test_done(self):
        levels = {E: 4, Q: 4, W: 4, R: 3, T10: 1, T15: 1}
        self.assertIsNone(next_step(self.PLAN, levels, 18, [R]))

    def test_can_learn(self):
        talent = Step(10, T10, 1, 1)
        self.assertFalse(can_learn(talent, {}, 9, False))
        self.assertTrue(can_learn(talent, {}, 10, False))
        self.assertFalse(can_learn(Step(6, R, 1, 1), {}, 5, True))
        self.assertTrue(can_learn(Step(6, R, 1, 1), {R: 1}, 12, True))
        self.assertFalse(can_learn(Step(3, E, 1, 1), {E: 1}, 2, False))


class GameStateTest(unittest.TestCase):
    def test_levels_from_abilities(self):
        gs = gs_with({E: 2, Q: 1}, 3)
        self.assertEqual(gs.ability_levels[E], 2)
        self.assertIn("special_bonus_unique_ursa", gs.ability_levels)
        self.assertTrue(gs.talents_known)
        self.assertEqual(free_points(gs), 0)
        self.assertEqual([a["name"] for a in gs.abilities], [Q, W, E, R])

    def test_points_and_talent_flags(self):
        self.assertEqual(points_earned(16), 16)
        self.assertEqual(points_earned(17), 16)
        self.assertEqual(points_earned(18), 17)
        p = payload(300, 600)
        p["hero"]["level"] = 11
        p["abilities"] = {
            f"ability{i}": {"name": n, "level": lv}
            for i, (n, lv) in enumerate([(Q, 2), (W, 3), (E, 4), (R, 1)])
        }
        gs = parse(p)
        self.assertFalse(gs.talents_known)
        self.assertIsNone(free_points(gs))  # с 10-го уровня без талантов — ?
        p["hero"].update({f"talent_{i}": i == 2 for i in range(1, 9)})
        gs = parse(p)
        self.assertEqual(gs.talent_tiers, {1})
        self.assertEqual(free_points(gs), 0)
        p["hero"]["attributes_level"] = 1
        self.assertEqual(parse(p).ability_levels[ATTRIBUTES], 1)


class HintTest(unittest.TestCase):
    PLAN = consensus([URSA_BUILD] * 4 + [URSA_BUILD[:9] + [T10B]])

    def test_ability_hint(self):
        hint = skill_hint(gs_with({E: 1}, 2), self.PLAN, {})
        self.assertTrue(hint.learn_now)
        self.assertEqual(hint.text, "Качайте сейчас: Earthshock (1-й уровень)")
        self.assertEqual(hint.why, "Так делают 5 из 5 сильных игроков.")
        hint = skill_hint(gs_with({E: 1, Q: 1}, 2), self.PLAN, {})
        self.assertFalse(hint.learn_now)  # очков нет — только «следующая»
        self.assertTrue(hint.text.startswith("Следующая прокачка:"))

    def test_talent_hint(self):
        levels = {E: 4, Q: 1, W: 3, R: 1}
        consts = {T10: {"dname": "+{s:value} Fury Swipes Damage"}}
        hint = skill_hint(gs_with(levels, 10), self.PLAN, consts)
        self.assertTrue(hint.step.is_talent)
        self.assertEqual(hint.title, "+ Fury Swipes Damage")
        self.assertIn("талант 10-го уровня", hint.text)
        self.assertEqual(hint.why, "Так делают 4 из 5 сильных игроков.")
        # Игра присылает таланты флажками: ступень взята — идём дальше.
        gs = gs_with(levels, 10, {"talent_2": True, "talent_1": False})
        self.assertEqual(skill_hint(gs, self.PLAN, consts).step.name, W)


class SkillStore(FakeStore):
    def __init__(self, builds):
        super().__init__()
        self.builds = builds

    def get_skill_builds(self, hero_id):
        return self.builds


class EngineSkillTest(unittest.TestCase):
    def frame(self, engine, levels, hero_level, clock=300):
        p = payload(clock, 600, ("tango",))
        p["hero"]["level"] = hero_level
        abil = [dict(a, level=levels.get(a["name"], 0)) for a in URSA]
        return engine.process(parse(with_abilities(p, abil)))

    def voice(self, frame):
        return [v.text for v in frame.voice if v.key.startswith("skill:")]

    def test_voice_once_per_point(self):
        engine = CoachEngine(SkillStore([URSA_BUILD] * 5))
        first = self.frame(engine, {}, 1)
        swipes, shock = speakable("Fury Swipes"), speakable("Earthshock")
        self.assertEqual(self.voice(first), [f"Качайте {swipes}"])
        self.assertEqual(self.voice(self.frame(engine, {}, 1, 301)), [])
        self.assertEqual(self.voice(self.frame(engine, {E: 1}, 1, 302)), [])
        self.assertEqual(
            self.voice(self.frame(engine, {E: 1}, 2, 303)),
            [f"Качайте {shock}"],
        )

    def test_no_data_no_hint(self):
        engine = CoachEngine(SkillStore(None))
        self.assertIsNone(self.frame(engine, {}, 1).skill)
        self.assertIsNone(CoachEngine(FakeStore()).skill_plan(70) or None)

    def test_plan_is_cached(self):
        engine = CoachEngine(SkillStore([URSA_BUILD] * 5))
        self.assertIs(engine.skill_plan(70), engine.skill_plan(70))


class StoreSkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name))
        self.store.request_gap = 0
        self.store.ability_ids = IDS
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_get(self, answers):
        def get(path):
            self.calls.append(path)
            answer = answers[path]
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.store._get = get

    def match(self, build_ids):
        return {
            "players": [{"hero_id": 70, "ability_upgrades_arr": build_ids}]
        }

    def test_refresh_collects_parsed_matches(self):
        not_found = urllib.error.HTTPError("u", 404, "nf", None, None)
        self.fake_get(
            {
                "/heroes/70/matches": [{"match_id": i} for i in (1, 2, 3, 4)],
                "/matches/1": self.match([5359, 5357]),
                "/matches/2": {"players": [{"hero_id": 70}]},  # не разобран
                "/matches/3": not_found,
                "/matches/4": self.match([5357, 5359]),
            }
        )
        self.store._refresh_skills(70)
        data = json.loads(
            (Path(self.tmp.name) / "skills_70.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(data["builds"], [[E, Q], [Q, E]])
        self.store.skills.clear()
        self.assertEqual(self.store.get_skill_builds(70), [[E, Q], [Q, E]])

    def test_rate_limit_stops_early(self):
        limit = urllib.error.HTTPError("u", 429, "slow down", None, None)
        self.fake_get(
            {
                "/heroes/70/matches": [{"match_id": i} for i in (1, 2, 3)],
                "/matches/1": self.match([5359]),
                "/matches/2": limit,
            }
        )
        self.store._refresh_skills(70)
        self.assertNotIn("/matches/3", self.calls)
        self.assertEqual(self.store.skills[70]["builds"], [[E]])

    def test_prefetch_asks_for_skills(self):
        jobs = []
        self.store._enqueue = jobs.append
        self.store.prefetch(70)
        self.assertIn(("skills", 70), jobs)
        self.assertIsNone(self.store.get_skill_builds(0))


class ToolTest(unittest.TestCase):
    def test_find_hero_and_format(self):
        heroes = FakeStore().heroes
        self.assertEqual(find_hero(heroes, "ursa"), (70, "Ursa"))
        self.assertEqual(find_hero(heroes, "70"), (70, "Ursa"))
        self.assertIsNone(find_hero(heroes, "pudge_2"))
        text = format_plan([URSA_BUILD] * 3, {Q: {"dname": "Earthshock"}})
        self.assertIn("Матчей: 3", text)
        self.assertIn("Earthshock", text)
        self.assertIn("★", text)
        self.assertIn("не построить", format_plan([], {}))


if __name__ == "__main__":
    unittest.main()
