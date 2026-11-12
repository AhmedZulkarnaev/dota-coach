"""Тесты записи матчей (coach/recorder.py) и воспроизведения (replay.py)."""

import gzip
import json
import pathlib
import tempfile
import unittest

from coach.advisor import Advice, Advisor
from coach.game_state import parse
from coach.recorder import (
    POST_GAME_TAIL,
    MatchRecorder,
    load_recording,
    redact,
)
from coach.replay import check_advice, format_result, replay
from tests.helpers import POST_GAME, PRE_GAME, FakeStore, payload
from tools.simulate_gsi import build_payload

TOKEN = "секрет"


def sim_packet(clock):
    p = build_payload(clock, 400 + (clock % 300) * 6, TOKEN)
    p["player"].update(
        steamid="76561190000000000", accountid="12345", name="Ник"
    )
    return p


def record_sim_match(folder, step=15, until=2800):
    """Записывает матч из симулятора; время записи — 1 c на пакет."""
    rec = MatchRecorder(folder)
    now = 0.0
    for clock in range(-90, until, step):
        rec.add(sim_packet(clock), now=now)
        now += 1.0
    rec.close()
    return rec.path


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())

    def test_records_whole_match_without_secrets(self):
        path = record_sim_match(self.dir)
        self.assertTrue(path.name.endswith("_9999000111_ursa.jsonl.gz"))
        rec = load_recording(path)
        self.assertEqual(rec.header["format"], "dota-coach-recording")
        self.assertEqual(rec.header["match_id"], "9999000111")
        self.assertFalse(rec.truncated)
        self.assertGreater(len(rec.packets), 150)
        with gzip.open(path, "rt", encoding="utf-8") as f:
            raw = f.read()
        for secret in (TOKEN, "76561190000000000", "12345", "Ник"):
            self.assertNotIn(secret, raw)
        first_t = [t for t, _ in rec.packets[:3]]
        self.assertEqual(first_t, [0.0, 1.0, 2.0])

    def test_redact_keeps_game_data(self):
        p = sim_packet(600)
        clean = redact(p)
        self.assertNotIn("auth", clean)
        self.assertEqual(clean["player"]["gold"], p["player"]["gold"])
        self.assertIn("auth", p)  # исходный пакет не тронут

    def test_waits_for_hero_and_ignores_menu(self):
        rec = MatchRecorder(self.dir)
        no_hero = payload(-60, 600, state=PRE_GAME)
        no_hero["hero"] = {}
        rec.add(no_hero, now=0)
        rec.add({"provider": {"name": "Dota 2"}}, now=1)  # главное меню
        self.assertFalse(rec.recording)
        self.assertEqual(list(self.dir.glob("*")), [])

    def test_spectator_mode_not_recorded(self):
        rec = MatchRecorder(self.dir)
        rec.add(
            {"map": {"clock_time": 5}, "player": {"team2": {"player0": {}}}},
            now=0,
        )
        self.assertFalse(rec.recording)

    def test_new_match_new_file_and_stop_after_post_game(self):
        rec = MatchRecorder(self.dir)
        rec.add(payload(100, 500), now=0)
        first = rec.path
        other = payload(50, 500)
        other["map"]["matchid"] = "777"
        rec.add(other, now=1)
        self.assertNotEqual(rec.path, first)
        end = payload(1900, 0, state=POST_GAME)
        end["map"]["matchid"] = "777"
        rec.add(end, now=2)
        rec.add(end, now=2 + POST_GAME_TAIL)
        self.assertFalse(rec.recording)
        rec.add(end, now=3 + POST_GAME_TAIL)  # тот же матч дальше не пишем
        self.assertFalse(rec.recording)
        self.assertEqual(len(list(self.dir.glob("*.jsonl.gz"))), 2)

    def test_reconnect_to_same_match_continues_in_new_file(self):
        rec = MatchRecorder(self.dir)
        rec.add(payload(300, 500), now=0)
        rec.add({"provider": {"name": "Dota 2"}}, now=1)  # вылет в меню
        self.assertFalse(rec.recording)
        rec.add(payload(420, 500), now=2)
        self.assertTrue(rec.recording)

    def test_disabled(self):
        rec = MatchRecorder(self.dir, enabled=False)
        rec.add(payload(100, 500), now=0)
        self.assertFalse(rec.recording)

    def test_keeps_only_last_n(self):
        rec = MatchRecorder(self.dir, keep=2)
        for i in range(4):
            p = payload(100, 500)
            p["map"]["matchid"] = str(1000 + i)
            rec.add(p, now=i)
        rec.close()
        self.assertEqual(len(list(self.dir.glob("*.jsonl.gz"))), 2)

    def test_truncated_file_is_readable(self):
        path = record_sim_match(self.dir, until=900)
        full = load_recording(path)
        data = path.read_bytes()
        path.write_bytes(data[: len(data) * 2 // 3])  # «программа упала»
        cut = load_recording(path)
        self.assertTrue(cut.truncated)
        self.assertGreater(len(cut.packets), 10)
        self.assertLess(len(cut.packets), len(full.packets))

    def test_readable_while_match_in_progress(self):
        rec = MatchRecorder(self.dir)
        for i, clock in enumerate(range(0, 120, 10)):
            rec.add(sim_packet(clock), now=float(i))
        live = load_recording(rec.path)  # файл ещё открыт на запись
        self.assertEqual(live.header["match_id"], "9999000111")
        self.assertTrue(live.truncated)
        rec.close()
        self.assertEqual(len(load_recording(rec.path).packets), 12)

    def test_rejects_foreign_file(self):
        path = self.dir / "x.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(json.dumps({"hello": 1}) + "\n")
        with self.assertRaises(ValueError):
            load_recording(path)


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.advisor = Advisor(FakeStore())

    def test_sim_match_has_no_violations(self):
        result = replay(
            load_recording(record_sim_match(self.dir)), self.advisor
        )
        self.assertEqual(result.violations, [], format_result(result))
        kinds = {e.kind for e in result.events}
        self.assertTrue({"предмет", "золото", "тренер", "статус"} <= kinds)
        self.assertIn("Ursa", result.hero)
        clocks = [e.clock for e in result.events]
        self.assertEqual(clocks, sorted(clocks))
        self.assertIn("Нарушений нет", format_result(result))

    def test_violations_are_detected(self):
        class BrokenAdvisor(Advisor):
            def advise(self, gs, enemy_shorts=(), role_setting="auto"):
                a = super().advise(gs, enemy_shorts, role_setting)
                if a.status == "ok" and gs.inventory:
                    a.target = gs.inventory[0]  # «советует» уже купленное
                return a

        rec = load_recording(record_sim_match(self.dir, until=1200))
        result = replay(rec, BrokenAdvisor(FakeStore()))
        self.assertIn("owned", {v.rule for v in result.violations})
        self.assertIn("НАРУШЕНИЯ", format_result(result))

    def test_crash_is_a_violation(self):
        class CrashingAdvisor(Advisor):
            def advise(self, gs, enemy_shorts=(), role_setting="auto"):
                raise KeyError("boom")

        rec = load_recording(record_sim_match(self.dir, until=300))
        result = replay(rec, CrashingAdvisor(FakeStore()))
        self.assertEqual([v.rule for v in result.violations], ["crash"])

    def test_check_advice_rules(self):
        gs = parse(payload(900, 100, items=["magic_wand", "ogre_axe"]))
        bad = Advice(
            status="ok",
            target="black_king_bar",
            remaining=-5,
            buy_now=[("Mithril Hammer", 1600)],
            free_up=[("продайте", "Butterfly")],
        )
        rules = {p.split(":")[0] for p in check_advice(gs, bad, self.advisor)}
        self.assertEqual(rules, {"negative", "overspend", "phantom"})
        bad.target = "ogre_axe"
        rules = {p.split(":")[0] for p in check_advice(gs, bad, self.advisor)}
        self.assertIn("owned", rules)


if __name__ == "__main__":
    unittest.main()
