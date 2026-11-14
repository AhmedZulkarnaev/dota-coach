"""Ядро программы: один и тот же путь для окна и для replay."""

import gzip
import json
import pathlib
import tempfile
import unittest

from coach.advisor import Advisor
from coach.engine import CoachEngine
from coach.game_state import parse
from coach.recorder import load_recording
from coach.replay import replay
from tests.helpers import POST_GAME, PRE_GAME, FakeStore, payload


def gs_at(clock, gold, items=("tango",), **kw):
    return parse(payload(clock, gold, items, **kw))


def keys(frame):
    return [line.key.split(":")[0] for line in frame.voice]


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = CoachEngine(FakeStore())

    def test_first_packet_starts_match(self):
        frame = self.engine.process(gs_at(300, 600))
        self.assertTrue(frame.new_match)
        self.assertEqual(frame.advice.status, "ok")
        self.assertIsNone(frame.match_log)  # журнал не включён
        self.assertFalse(self.engine.process(gs_at(301, 600)).new_match)

    def test_target_is_spoken_once(self):
        first = self.engine.process(gs_at(300, 100))
        self.assertIn("target", keys(first))
        again = self.engine.process(gs_at(301, 110))
        self.assertNotIn("target", keys(again))

    def test_enough_gold_is_spoken_when_it_appears(self):
        frame = self.engine.process(gs_at(300, 100))
        target_cost = frame.advice.target_cost
        rich = self.engine.process(gs_at(305, target_cost + 500))
        self.assertTrue(rich.advice.can_buy_full)
        self.assertIn("full", keys(rich))
        self.assertNotIn("full", keys(self.engine.process(gs_at(306, 9999))))

    def test_start_bundle_spoken_once_per_match(self):
        pre = self.engine.process(gs_at(-80, 600, items=(), state=PRE_GAME))
        self.assertEqual(pre.advice.status, "start")
        self.assertIn("start", keys(pre))
        later = self.engine.process(gs_at(-70, 600, items=(), state=PRE_GAME))
        self.assertNotIn("start", keys(later))

    def test_new_match_resets_enemies_and_voice(self):
        self.engine.set_enemies(["lion", "pudge", "axe", "zuus", "lina", "x"])
        self.assertEqual(len(self.engine.enemies), 5)
        self.engine.process(gs_at(300, 100))
        other = payload(300, 100, ("tango",))
        other["map"]["matchid"] = "456"
        frame = self.engine.process(parse(other))
        self.assertTrue(frame.new_match)
        self.assertEqual(self.engine.enemies, [])
        self.assertIn("target", keys(frame))  # в новом матче — снова

    def test_settings_change_does_not_step_coach(self):
        gs = gs_at(-80, 600, items=(), state=PRE_GAME)
        self.engine.process(gs)
        self.engine.coach.update = lambda *a, **kw: self.fail("тренер")
        self.engine.role_setting = "support"
        self.engine.process(gs, new_packet=False)

    def test_tips_off_means_no_coach(self):
        self.engine.tips_level = "off"
        for clock in range(-80, 900, 30):
            frame = self.engine.process(gs_at(clock, 300))
            self.assertIsNone(frame.coach_message)
            self.assertNotIn("coach", keys(frame))

    def test_coach_message_goes_to_voice(self):
        messages = []
        for clock in range(-80, 900, 30):
            frame = self.engine.process(gs_at(clock, 300))
            if frame.coach_message:
                messages.append(frame)
        self.assertTrue(messages)
        self.assertIn("coach", keys(messages[0]))

    def test_match_log_saved_at_the_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = CoachEngine(FakeStore(), pathlib.Path(tmp))
            engine.process(gs_at(300, 100))
            frame = engine.process(gs_at(1500, 100, state=POST_GAME))
            self.assertIsNotNone(frame.match_log)
            self.assertTrue(frame.match_log.exists())


class ReplayUsesEngineTest(unittest.TestCase):
    def test_replay_voice_equals_engine_voice(self):
        packets = [payload(-80, 600, (), state=PRE_GAME)]
        packets += [
            payload(c, 100 + c, ("tango",)) for c in range(0, 1200, 20)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "m.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as f:
                header = {"format": "dota-coach-recording", "version": 1}
                f.write(json.dumps(header) + "\n")
                for i, p in enumerate(packets):
                    f.write(json.dumps({"t": i, "payload": p}) + "\n")
            store = FakeStore()
            result = replay(load_recording(path), Advisor(store))

        engine = CoachEngine(store)
        expected = []
        for p in packets:
            gs = parse(p)
            expected += [(gs.clock, v) for v in engine.process(gs).voice]
        self.assertEqual(result.voice, expected)
        self.assertTrue(any(v.key.startswith("target") for _, v in expected))


if __name__ == "__main__":
    unittest.main()
