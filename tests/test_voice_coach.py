"""Тесты произношения и советов тренера по стадиям."""

import unittest
from itertools import pairwise

from coach.game_state import parse
from coach.match_coach import MatchCoach
from coach.speech_ru import speakable
from tests.helpers import IN_PROGRESS, PRE_GAME, payload


class SpeechTest(unittest.TestCase):
    def test_items_become_russian(self):
        self.assertEqual(
            speakable("Следующий предмет: Black King Bar"),
            "Следующий предмет: блэк кинг бар",
        )
        self.assertEqual(speakable("Eye of Skadi"), "ай оф скади")
        self.assertEqual(speakable("Aghanim's Shard"), "аганимс шард")

    def test_abbreviations(self):
        self.assertIn("тэ-пэ", speakable("Нет свитка (TP)"))

    def test_unknown_words_transliterated(self):
        out = speakable("Spirit Breaker Charge of Darkness")
        self.assertEqual(out, "спирит брейкер чардж оф даркнесс")
        self.assertFalse(
            any(
                "a" <= ch.lower() <= "z"
                for ch in speakable("Consecrated Wraps Bulwark")
            )
        )

    def test_russian_untouched(self):
        self.assertEqual(speakable("Игра началась!"), "Игра началась!")


def run_match(role, level="all", deaths_at=None, lh_per_min=4.3, start=-90):
    c, said = MatchCoach(), []
    for clock in range(start, 2500, 5):
        p = payload(clock, 500, state=PRE_GAME if clock < 0 else IN_PROGRESS)
        p["player"]["last_hits"] = int(max(0, clock) / 60 * lh_per_min)
        if deaths_at is not None and clock >= deaths_at:
            p["player"]["deaths"] = 1
            p["hero"]["alive"] = clock > deaths_at + 30
        m = c.update(parse(p), role, level)
        if m:
            said.append((m.clock, m.text))
    return said


class CoachTest(unittest.TestCase):
    def test_stage_tips_in_order_and_spaced(self):
        said = run_match("core")
        texts = [t for _, t in said]
        self.assertTrue(texts[0].startswith("Купите стартовые"))
        self.assertTrue(any(t.startswith("Игра началась") for t in texts))
        self.assertTrue(any("Стадия линии заканчивается" in t for t in texts))
        self.assertTrue(any(t.startswith("Лейт") for t in texts))
        clocks = [c for c, _ in said]
        self.assertTrue(
            all(b - a >= 25 for a, b in pairwise(clocks)),
            "советы не должны идти подряд",
        )
        self.assertLessEqual(len(said), 20)

    def test_roles_get_different_tips(self):
        core = " ".join(t for _, t in run_match("core"))
        sup = " ".join(t for _, t in run_match("support"))
        self.assertIn("стакать", sup)
        self.assertNotIn("стакать", core)
        self.assertIn("фармите лес", core)

    def test_main_level_is_short(self):
        said = run_match("core", level="main")
        self.assertLessEqual(len(said), 8)
        self.assertEqual(run_match("core", level="off"), [])

    def test_first_death_and_lh(self):
        texts = " ".join(
            t for _, t in run_match("core", deaths_at=400, lh_per_min=3)
        )
        self.assertIn("Вы погибли", texts)
        self.assertIn("Хорошая цель — 45", texts)
        texts = " ".join(t for _, t in run_match("core", lh_per_min=6))
        self.assertIn("Отлично!", texts)

    def test_joining_mid_game_does_not_dump_old_tips(self):
        said = run_match("core", start=1300)
        self.assertTrue(all(c >= 1300 for c, _ in said))
        self.assertFalse(any("Игра началась" in t for _, t in said))
        self.assertFalse(
            any(
                "Вы погибли" in t
                for _, t in run_match("core", deaths_at=1400, start=1500)
            )
        )


if __name__ == "__main__":
    unittest.main()
