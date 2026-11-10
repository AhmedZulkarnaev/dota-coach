"""Тесты истории матчей, прогресса, проверки подключения, напоминаний."""

import json
import pathlib
import tempfile
import unittest

from coach import gsi_installer
from coach.advisor import Advisor
from coach.diagnostics import FAIL, OK, WARN, format_checks, run_checks
from coach.game_state import parse
from coach.history import (
    MatchSummary,
    history_table,
    load_history,
    progress_lines,
    summarize,
)
from coach.match_log import MatchLog
from coach.post_match import build_report
from coach.theme import line_style
from tests.helpers import POST_GAME, FakeStore, payload


def make_log(
    match_id="1", lh10=40, gpm=450, deaths=5, result="win", duration=1800
):
    minutes = duration // 60
    per_minute = {
        str(m): {
            "lh": m * lh10 // 10,
            "k": 4,
            "d": deaths,
            "a": 7,
            "gpm": gpm,
            "xpm": 500,
            "gold": 0,
            "can_buy": False,
            "target": "",
        }
        for m in range(minutes + 1)
    }
    return {
        "match_id": match_id,
        "hero": "npc_dota_hero_ursa",
        "hero_id": 70,
        "result": result,
        "saved_at": "2026-11-10 12:00",
        "duration": duration,
        "first_clock": -80,
        "items_first_seen": {},
        "per_minute": per_minute,
        "advice_log": [],
        "death_clocks": [],
    }


class HistoryTest(unittest.TestCase):
    def test_summarize(self):
        s = summarize(make_log(lh10=40, gpm=450, deaths=5))
        self.assertEqual(
            (s.lh10, s.gpm, s.deaths, s.result, s.kills),
            (40, 450, 5, "win", 4),
        )

    def test_lh10_unknown_when_joined_late(self):
        log = make_log()
        log["first_clock"] = 900
        self.assertIsNone(summarize(log).lh10)

    def test_progress_better_and_worse(self):
        previous = [
            MatchSummary(lh10=30, gpm=400, deaths=8, result="loss"),
            MatchSummary(lh10=34, gpm=420, deaths=6, result="win"),
        ]
        lines = progress_lines(
            MatchSummary(lh10=45, gpm=410, deaths=10), previous
        )
        text = "\n".join(lines)
        self.assertIn(
            "Добито к 10-й минуте: 45 (в среднем было 32) — лучше вашего "
            "обычного ↑",
            text,
        )
        self.assertIn(
            "Золото в минуту: 410 (в среднем было 410) — на вашем обычном "
            "уровне",
            text,
        )
        self.assertIn(
            "Смертей за матч: 10.0 (в среднем было 7.0) — хуже вашего "
            "обычного ↓",
            text,
        )
        self.assertIn("Побед в прошлых 2 матчах: 1", text)

    def test_no_progress_without_previous(self):
        self.assertEqual(progress_lines(MatchSummary(lh10=45), []), [])

    def test_load_history_skips_short_broken_and_excluded(self):
        folder = pathlib.Path(tempfile.mkdtemp())
        for match_id, duration in (("1", 1800), ("2", 2000), ("3", 120)):
            (folder / f"match_{match_id}.json").write_text(
                json.dumps(make_log(match_id, duration=duration))
            )
        (folder / "match_bad.json").write_text("{не json")
        matches = load_history(folder, exclude="2")
        self.assertEqual([m.match_id for m in matches], ["1"])
        self.assertEqual(load_history(folder / "нет такой папки"), [])

    def test_history_table(self):
        table = history_table(
            [
                summarize(make_log(result="win")),
                summarize(make_log(result="loss")),
            ],
            lambda npc: "Ursa",
        )
        self.assertIn("Ursa", table)
        self.assertIn("победа", table)
        self.assertIn("Побед: 1 из 2", table)
        self.assertIn("Пока нет", history_table([]))

    def test_report_has_result_and_progress(self):
        db = Advisor(FakeStore()).db
        previous = [
            summarize(make_log(lh10=20, gpm=300, deaths=9, result="loss"))
        ]
        text, _ = build_report(
            make_log(lh10=50, gpm=520, deaths=2, result="win"),
            db,
            "Ursa",
            previous=previous,
        )
        self.assertIn("Итог: Победа · KDA", text)
        self.assertIn("ПРОГРЕСС", text)
        self.assertIn("лучше вашего обычного", text)
        self.assertNotIn("ПРОГРЕСС", build_report(make_log(), db, "Ursa")[0])


class MatchResultTest(unittest.TestCase):
    def run_match(self, win_team):
        log = MatchLog(pathlib.Path(tempfile.mkdtemp()))
        log.update(parse(payload(600, 500)))
        end = payload(1900, 500, state=POST_GAME)
        end["map"]["win_team"] = win_team
        saved = log.update(parse(end))
        return json.loads(saved.read_text())["result"]

    def test_win_loss_unknown(self):
        self.assertEqual(
            self.run_match("radiant"), "win"
        )  # в payload мы за radiant
        self.assertEqual(self.run_match("dire"), "loss")
        self.assertEqual(self.run_match("none"), "")

    def test_result_written_when_winner_arrives_later(self):
        log = MatchLog(pathlib.Path(tempfile.mkdtemp()))
        saved = log.update(parse(payload(1900, 0, state=POST_GAME)))
        self.assertEqual(json.loads(saved.read_text())["result"], "")
        late = payload(1901, 0, state=POST_GAME)
        late["map"]["win_team"] = "dire"
        self.assertIsNone(
            log.update(parse(late))
        )  # второй разбор не запускается
        self.assertEqual(json.loads(saved.read_text())["result"], "loss")


class DiagnosticsTest(unittest.TestCase):
    BASE = {
        "port": 47113,
        "server_error": None,
        "config_status": "ok",
        "payload_age": 2.0,
        "items_count": 400,
        "heroes_count": 126,
        "has_russian_voice": True,
    }

    def marks(self, **kw):
        return [c.mark for c in run_checks(**{**self.BASE, **kw})]

    def test_all_ok(self):
        checks = run_checks(**self.BASE)
        self.assertTrue(all(c.mark == OK for c in checks))
        self.assertIn("Всё в порядке.", format_checks(checks))

    def test_problems(self):
        self.assertEqual(self.marks(server_error="порт занят")[0], FAIL)
        self.assertEqual(self.marks(config_status="missing")[1], FAIL)
        self.assertEqual(self.marks(config_status="stale")[1], FAIL)
        self.assertEqual(self.marks(config_status="no_dota")[1], WARN)
        self.assertEqual(self.marks(payload_age=None)[2], FAIL)
        self.assertEqual(self.marks(payload_age=300)[2], WARN)
        self.assertEqual(self.marks(items_count=0)[3], FAIL)
        self.assertEqual(self.marks(has_russian_voice=False)[4], FAIL)
        self.assertEqual(self.marks(voice_enabled=False)[4], WARN)
        text = format_checks(run_checks(**{**self.BASE, "payload_age": None}))
        self.assertIn("-gamestateintegration", text)
        self.assertIn("Нужно исправить: 1.", text)

    def test_config_status(self):
        root = pathlib.Path(tempfile.mkdtemp())
        cfg = root / "cfg"
        cfg.mkdir()
        original = gsi_installer.find_cfg_dirs
        try:
            gsi_installer.find_cfg_dirs = list
            self.assertEqual(
                gsi_installer.config_status(47113, "tok"), "no_dota"
            )
            gsi_installer.find_cfg_dirs = lambda: [cfg]
            self.assertEqual(
                gsi_installer.config_status(47113, "tok"), "missing"
            )
            gsi_installer.install(cfg, 47113, "tok")
            self.assertEqual(gsi_installer.config_status(47113, "tok"), "ok")
            self.assertEqual(
                gsi_installer.config_status(47113, "другой"), "stale"
            )
            self.assertTrue(gsi_installer.is_installed(47113, "tok"))
        finally:
            gsi_installer.find_cfg_dirs = original


class LineStyleTest(unittest.TestCase):
    def test_line_tags(self):
        tag = line_style
        self.assertEqual(tag(0, "РАЗБОР МАТЧА", ""), "title")
        self.assertEqual(tag(3, "ЛИНИЯ (0–10 мин)", ""), "h")
        self.assertIsNone(tag(4, "• Смертей: 1", "ЛИНИЯ"))
        self.assertIsNone(tag(9, "1. Совет", ""))
        self.assertEqual(tag(2, "✓ Сервер работает", ""), "ok")
        self.assertEqual(tag(3, "✗ Конфиг не найден", "✓ ..."), "fail")
        self.assertEqual(tag(5, "! Режим зрителя", ""), "warn")
        self.assertIsNone(tag(4, "    Что сделать: ...", "✗ ..."))


class ReminderTest(unittest.TestCase):
    def setUp(self):
        self.adv = Advisor(FakeStore())

    def reminders(
        self,
        role,
        clock=700,
        ward_cooldown=0,
        items=("magic_wand", "boots"),
        **hero,
    ):
        p = payload(clock, 100, items=list(items))
        if ward_cooldown is not None:
            p["map"]["ward_purchase_cooldown"] = ward_cooldown
        p["hero"].update(hero)
        return " ".join(self.adv.advise(parse(p), role_setting=role).reminders)

    def test_ward_reminder_only_for_support_when_available(self):
        self.assertIn("Observer Ward", self.reminders("support"))
        self.assertNotIn("Observer Ward", self.reminders("core"))
        self.assertNotIn(
            "Observer Ward", self.reminders("support", ward_cooldown=75)
        )
        self.assertNotIn(
            "Observer Ward", self.reminders("support", ward_cooldown=None)
        )
        self.assertNotIn(
            "Observer Ward",
            self.reminders(
                "support", items=("magic_wand", "boots", "ward_observer")
            ),
        )

    def test_buyback_cooldown(self):
        text = self.reminders(
            "core", clock=2000, buyback_cost=900, buyback_cooldown=120
        )
        self.assertIn("Выкуп перезаряжается ещё 120 с", text)
        text = self.reminders(
            "core", clock=2000, buyback_cost=900, buyback_cooldown=0
        )
        self.assertIn("Копите на выкуп", text)


if __name__ == "__main__":
    unittest.main()
