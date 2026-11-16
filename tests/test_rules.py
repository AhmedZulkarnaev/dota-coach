"""Правила в JSON: встроенные корректны, свои подключаются и не ломают
программу."""

import copy
import json
import logging
import pathlib
import tempfile
import unittest

from coach import enemies, match_coach, rules
from coach.diagnostics import OK, WARN, run_checks
from tools.check_rules import unknown_names


def builtin(name):
    return rules.read_json(rules.DATA_DIR / f"{name}.json")


class BuiltinRulesTest(unittest.TestCase):
    def test_every_file_is_valid(self):
        for name in rules.NAMES:
            with self.subTest(name):
                self.assertEqual(rules.validate(name, builtin(name)), [])

    def test_no_stray_files(self):
        files = {p.stem for p in rules.DATA_DIR.glob("*.json")}
        self.assertEqual(files, set(rules.NAMES))

    def test_files_are_readable_by_people(self):
        """Отступы и кириллица как есть — чтобы файл правили руками."""
        for name in rules.NAMES:
            text = (rules.DATA_DIR / f"{name}.json").read_text(
                encoding="utf-8"
            )
            self.assertIn('\n  "', text, name)
            self.assertNotIn("\\u04", text, name)
            self.assertIn('"_about"', text, name)


class UserRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.saved = rules.USER_DIR, rules.LEGACY_TIPS
        rules.USER_DIR = root / "rules"
        rules.LEGACY_TIPS = root / "coach_tips.json"
        rules.USER_DIR.mkdir()
        rules.reload()
        self.log = logging.getLogger(rules.__name__)
        self.log.setLevel(logging.ERROR)  # пропуски файлов — ожидаемые

    def tearDown(self):
        self.log.setLevel(logging.NOTSET)
        rules.USER_DIR, rules.LEGACY_TIPS = self.saved
        rules.reload()
        self.tmp.cleanup()

    def write(self, name, data, folder=None):
        path = (folder or rules.USER_DIR) / name
        text = data if isinstance(data, str) else json.dumps(data)
        path.write_text(text, encoding="utf-8")
        rules.reload()

    def test_dicts_merge_key_by_key(self):
        self.write("items.json", {"why": {"Мои": {"tango": "Мой текст."}}})
        why = rules.flat(rules.load("items")["why"])
        self.assertEqual(why["tango"], "Мой текст.")
        self.assertEqual(
            why["black_king_bar"],
            rules.flat(builtin("items")["why"])["black_king_bar"],
        )
        self.assertEqual(rules.user_files(), ["rules/items.json"])

    def test_tips_merge_by_id(self):
        self.write(
            "coach_tips.json",
            {
                "tips": [
                    {"id": "denies", "text": "Денайте!"},
                    {"id": "pregame", "off": True},
                    {"id": "my_tip", "at": 420, "text": "Свой совет."},
                ]
            },
        )
        tips = {t.id: t for t in match_coach.load_tips()}
        self.assertEqual(tips["denies"].text, "Денайте!")
        self.assertEqual(tips["denies"].roles, ("core",))  # осталось своё
        self.assertNotIn("pregame", tips)
        self.assertEqual(tips["my_tip"].roles, match_coach.ALL)
        self.assertEqual(len(tips), len(builtin("coach_tips")["tips"]))

    def test_legacy_coach_tips_still_work(self):
        self.write(
            "coach_tips.json",
            [{"id": "only", "at": 0, "text": "Единственный."}],
            folder=rules.LEGACY_TIPS.parent,
        )
        self.assertEqual([t.id for t in match_coach.load_tips()], ["only"])
        self.assertEqual(rules.user_files(), ["coach_tips.json"])

    def test_broken_file_is_skipped_and_reported(self):
        self.write("speech_ru.json", '{"abbr": {"TP": "тэ-пэ",}}')
        self.assertEqual(rules.load("speech_ru"), builtin("speech_ru"))
        problems = rules.user_problems()
        self.assertIn("строке 1", problems["rules/speech_ru.json"][0])
        checks = run_checks(
            port=1,
            server_error=None,
            config_status="ok",
            payload_age=1,
            rules_problems=problems,
        )
        self.assertEqual(checks[-1].mark, WARN)
        self.assertIn("rules/speech_ru.json", checks[-1].title)

    def test_invalid_content_is_skipped(self):
        bad = {"keywords": [{"tag": "nuke", "regex": "(oops"}]}
        self.write("abilities.json", bad)
        self.assertEqual(rules.load("abilities"), builtin("abilities"))
        self.assertIn(
            "regex", rules.user_problems()["rules/abilities.json"][0]
        )
        self.assertEqual(rules.user_files(), [])

    def test_unknown_tag_is_caught_after_merge(self):
        tip = {"text": "Совет.", "tags": ["mana"]}
        self.write("abilities.json", {"tips": {"Lion": {"x": tip}}})
        found = rules.user_problems()["rules/abilities.json"]
        self.assertTrue(any("mana" in p for p in found), found)

    def test_unknown_file_name_is_reported(self):
        self.write("item.json", {})
        found = rules.user_problems()["rules/item.json"][0]
        self.assertIn("items.json", found)

    def test_ok_rules_shown_in_diagnostics(self):
        self.write("slots.json", {"utility": ["dust", "gem"]})
        self.assertEqual(rules.load("slots")["utility"], ["dust", "gem"])
        checks = run_checks(
            port=1,
            server_error=None,
            config_status="ok",
            payload_age=1,
            user_rules=rules.user_files(),
        )
        self.assertEqual(checks[-1].mark, OK)
        self.assertIn("rules/slots.json", checks[-1].title)


class ValidateTest(unittest.TestCase):
    def errors(self, name, change):
        data = copy.deepcopy(builtin(name))
        change(data)
        return rules.validate(name, data)

    def test_typical_mistakes(self):
        def tip(**kw):
            return lambda d: d["tips"][0].update(kw)

        cases = {
            "coach_tips": [
                (tip(colour="red"), "неизвестный ключ"),
                (tip(at="1:30"), "целое число"),
                (tip(roles=["carry"]), "core и support"),
                (tip(every=60, until=10, at=100), "не раньше at"),
                (lambda d: d["tips"].append(d["tips"][0]), "повторяется"),
            ],
            "items": [
                (
                    lambda d: d["why"]["Защита"].update(tango="x"),
                    "уже есть",
                ),
                (lambda d: d["generic_by_stage"].pop("late"), "late"),
            ],
            "speech_ru": [
                (
                    lambda d: d["words"]["Предметы"].update(Blink="блинк"),
                    "маленькими",
                ),
            ],
            "enemies": [
                (
                    lambda d: d["counters"][0]["when"].update(tanks=2),
                    "нет такого признака",
                ),
                (
                    lambda d: d["counters"][3]["core"].update(
                        reason="Против {evasion_list}."
                    ),
                    "{evasion_list}",
                ),
                (
                    lambda d: d["counters"][0]["core"].update(strength=5),
                    "от 0.1 до 2",
                ),
                (lambda d: d["counters"][0].pop("core"), None),
                (
                    lambda d: d["groups"]["invis"].update(role="Initiator"),
                    "что-то одно",
                ),
            ],
            "heroes_ru": [
                (lambda d: d["aliases"].update(ursa=[]), "список строк"),
            ],
        }
        for name, items in cases.items():
            for change, expected in items:
                with self.subTest(name=name, expected=expected):
                    found = self.errors(name, change)
                    if expected is None:  # правило без core — допустимо
                        self.assertEqual(found, [])
                    else:
                        self.assertTrue(
                            any(expected in e for e in found), found
                        )


class EnemiesFromDataTest(unittest.TestCase):
    HEROES = {
        "tinker": {"localized_name": "Tinker", "roles": ["Nuker"]},
        "lion": {"localized_name": "Lion", "roles": ["Disabler", "Nuker"]},
    }

    def test_new_group_and_exclusive_rules(self):
        data = copy.deepcopy(builtin("enemies"))
        data["groups"]["push"] = {"label": "пуш", "heroes": ["tinker"]}
        data["counters"] = [
            {
                "exclusive": "x",
                "when": {"push": 1},
                "core": {
                    "item": "hurricane_pike",
                    "strength": 0.6,
                    "reason": "Пушер: {push_names}, всего {push}.",
                },
            },
            {
                "exclusive": "x",
                "when": {"nuker": 1},
                "core": {"item": "pipe", "strength": 0.5, "reason": "Нюк."},
            },
        ]
        self.assertEqual(rules.validate("enemies", data), [])
        counters, _, summary = enemies.analyze(
            ["tinker", "lion"], self.HEROES, "core", data
        )
        self.assertEqual([c.item for c in counters], ["hurricane_pike"])
        self.assertEqual(counters[0].reason, "Пушер: Tinker, всего 1.")
        self.assertIn("пуш", summary)
        self.assertIn("магия ×2", summary)
        counters, _, _ = enemies.analyze(["tinker"], self.HEROES, "support")
        self.assertEqual(counters, [])  # для саппорта правила нет


class UnknownNamesTest(unittest.TestCase):
    def all_names(self):
        items = set(rules.flat(rules.load("items")["why"]))
        for key in rules.SLOT_KEYS:
            items |= set(rules.load("slots")[key])
        for r in rules.load("enemies")["counters"]:
            items |= {r[role]["item"] for role in rules.ROLES if role in r}
        heroes = set(rules.load("heroes_ru")["aliases"])
        for g in rules.load("enemies")["groups"].values():
            heroes |= set(g.get("heroes", []))
        abilities = set(rules.flat(rules.load("abilities")["tips"]))
        return items, heroes, abilities

    def test_renamed_item_is_reported(self):
        items, heroes, abilities = self.all_names()
        self.assertEqual(unknown_names(items, heroes, abilities), [])
        found = unknown_names(items - {"glimmer_cape"}, heroes, abilities)
        self.assertTrue(any("glimmer_cape" in f for f in found), found)

    def test_no_cache_means_no_warnings(self):
        self.assertEqual(unknown_names([], [], []), [])


if __name__ == "__main__":
    unittest.main()
