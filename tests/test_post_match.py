"""Тесты разбора после матча, журнала матча и адресов иконок."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from coach.advisor import Advisor              # noqa: E402
from coach.game_state import parse             # noqa: E402
from coach.icons import IconCache              # noqa: E402
from coach.match_log import MatchLog           # noqa: E402
from coach.post_match import build_report, percentile_of   # noqa: E402
from test_advisor import FakeStore, payload    # noqa: E402


def row(lh=0, gold=0, target="", can_buy=False, d=0, gpm=500, xpm=550):
    return {"gold": gold, "lh": lh, "dn": 0, "level": 10, "k": 3, "d": d, "a": 4,
            "gpm": gpm, "xpm": xpm, "can_buy": can_buy, "target": target}


class PostMatchTest(unittest.TestCase):
    def setUp(self):
        self.db = Advisor(FakeStore()).db

    def base_log(self, **kw):
        log = {"hero": "npc_dota_hero_ursa", "hero_id": 70, "duration": 1500, "first_clock": -90,
               "items_first_seen": {"power_treads": 480, "black_king_bar": 1200},
               "per_minute": {str(m): row(lh=m * 5) for m in range(26)},
               "advice_log": [], "death_clocks": []}
        log.update(kw)
        return log

    def test_percentile(self):
        rows = [{"percentile": p / 10, "value": p * 100} for p in range(1, 10)]
        self.assertEqual(percentile_of(450, rows), 0.4)
        self.assertEqual(percentile_of(50, rows), 0.0)

    def test_late_purchase_and_idle_gold(self):
        pm = {str(m): row(lh=m * 5) for m in range(26)}
        for m in (14, 15, 16, 17, 18, 19):       # 6 минут хватало на BKB, купили в 20:00
            pm[str(m)] = row(lh=m * 5, gold=4500, target="black_king_bar", can_buy=True)
        text, tips = build_report(self.base_log(per_minute=pm), self.db, "Ursa")
        self.assertIn("Black King Bar — 20:00 (золота хватало уже с 14:00 — на 6 мин позже)", text)
        self.assertIn("золота хватало на следующий предмет", text)
        self.assertTrue(any("сразу, как хватает золота" in t for t in tips))

    def test_good_lane_and_no_deaths(self):
        text, tips = build_report(self.base_log(), self.db, "Ursa")
        self.assertIn("Добито крипов к 10-й минуте: 50 ✓", text)
        self.assertIn("Ни одной смерти", text)
        self.assertIn("Power Treads — 8:00", text)
        self.assertTrue(tips)

    def test_bad_lane_tips(self):
        log = self.base_log(per_minute={str(m): row(lh=m * 2) for m in range(26)},
                            death_clocks=[120, 300, 420, 900, 990])
        text, tips = build_report(log, self.db, "Ursa", role="core")
        self.assertIn("Смертей до 10-й минуты: 3", text)
        self.assertIn("Смерти подряд (5:00 и 7:00)", text)
        self.assertLessEqual(len(tips), 3)
        self.assertTrue(any("45+" in t for t in tips))

    def test_benchmarks_section(self):
        bench = {"result": {"gold_per_min": [{"percentile": p / 10, "value": 300 + p * 30} for p in range(1, 10)]}}
        text, _ = build_report(self.base_log(), self.db, "Ursa", bench=bench)
        self.assertIn("Золото в минуту: 500 — лучше, чем примерно у 60%", text)

    def test_joined_late(self):
        text, _ = build_report(self.base_log(first_clock=900), self.db, "Ursa")
        self.assertIn("начало матча в разбор не попало", text)
        self.assertNotIn("Добито крипов к 10-й минуте", text)


class MatchLogTest(unittest.TestCase):
    def test_records_deaths_items_and_saves_at_post_game(self):
        log = MatchLog(pathlib.Path(tempfile.mkdtemp()))
        adv = Advisor(FakeStore())
        saved = None
        for clock, deaths, items in ((-30, 0, ["tango"]), (300, 0, ["tango", "magic_wand"]),
                                     (400, 1, ["magic_wand"]), (900, 2, ["magic_wand", "power_treads"])):
            gs = parse(payload(clock, 500, items=items))
            gs.deaths = deaths
            log.update(gs, adv.advise(gs))
        gs = parse(payload(1000, 0, items=["magic_wand"], state="DOTA_GAMERULES_STATE_POST_GAME"))
        gs.deaths = 2
        saved = log.update(gs, None)
        self.assertIsNotNone(saved)
        data = log.to_dict()
        self.assertEqual(data["death_clocks"], [400, 900])
        self.assertEqual(data["items_first_seen"]["power_treads"], 900)
        self.assertTrue(saved.exists())


class IconTest(unittest.TestCase):
    def test_url(self):
        store = FakeStore()
        store.items["black_king_bar"]["img"] = "/apps/dota2/images/dota_react/items/black_king_bar.png?t=1"
        icons = IconCache(pathlib.Path(tempfile.mkdtemp()), store)
        self.assertEqual(icons.url_for("black_king_bar"),
                         "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/black_king_bar.png")
        self.assertIsNone(icons.url_for("tango"))


if __name__ == "__main__":
    unittest.main()
