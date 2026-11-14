"""Версия совпадает в коде, README и CHANGELOG — CI не пропустит забытую.

Если тест упал: python tools/bump_version.py <версия>.
"""

import datetime
import unittest

from coach import USER_AGENT, __version__
from tools.bump_version import (
    CHANGELOG,
    INIT,
    README,
    bump,
    parse,
    problems,
)

TODAY = datetime.date(2026, 11, 20)
INIT_TEXT = '"""Dota Coach."""\n\n__version__ = "0.7.0.dev2"\n'
README_TEXT = "# Dota Coach\n\n[Помочь проекту](CONTRIBUTING.md)\n\nТекст.\n"
CHANGELOG_TEXT = (
    "# История изменений\n\n## 0.7.0 (в работе)\n- запись\n\n## 0.6.1\n"
)


def read(path):
    return path.read_text(encoding="utf-8")


class ProjectVersionTest(unittest.TestCase):
    def test_version_matches_everywhere(self):
        found = problems(read(INIT), read(README), read(CHANGELOG))
        self.assertEqual(
            found, [], "Запустите: python tools/bump_version.py " + __version__
        )

    def test_user_agent_has_version(self):
        self.assertIn(__version__, USER_AGENT)


class BumpTest(unittest.TestCase):
    def apply(
        self, version, init=INIT_TEXT, readme=README_TEXT, log=CHANGELOG_TEXT
    ):
        return bump(version, init, readme, log, TODAY)

    def test_parse(self):
        self.assertEqual(parse("0.7.0.dev2"), ("0.7.0", True))
        self.assertEqual(parse("0.7.0.rc1"), ("0.7.0", True))
        self.assertEqual(parse("1.0.0"), ("1.0.0", False))
        for bad in ("0.7", "v0.7.0", "0.7.0-dev", "0.7.0.beta1"):
            with self.assertRaises(ValueError):
                parse(bad)

    def test_next_dev_build(self):
        init, readme, log = self.apply("0.7.0.dev3")
        self.assertIn('__version__ = "0.7.0.dev3"', init)
        self.assertIn("**Текущая версия: 0.7.0.dev3** — в разработке", readme)
        self.assertIn("## 0.7.0 (в работе)\n- запись", log)
        self.assertEqual(problems(init, readme, log), [])

    def test_release_puts_date_and_stable_status(self):
        init, readme, log = self.apply("0.7.0")
        self.assertIn("## 0.7.0 — 2026-11-20\n- запись", log)
        self.assertIn("— стабильная, [релиз v0.7.0]", readme)
        self.assertNotIn("в разработке", readme)
        self.assertEqual(problems(init, readme, log), [])

    def test_new_version_gets_new_changelog_section(self):
        init, readme, log = self.apply("0.8.0.dev1")
        self.assertTrue(
            log.startswith("# История изменений\n\n## 0.8.0 (в работе)\n- …\n")
        )
        self.assertIn("## 0.7.0 (в работе)", log)  # старый раздел на месте
        self.assertEqual(problems(init, readme, log), [])

    def test_status_block_is_replaced_not_duplicated(self):
        _, readme, _ = self.apply("0.7.0.dev3")
        _, readme, _ = self.apply("0.7.0.dev4", readme=readme)
        self.assertEqual(readme.count("<!-- version -->"), 1)
        self.assertIn("0.7.0.dev4", readme)
        self.assertNotIn("0.7.0.dev3", readme)

    def test_problems_are_reported(self):
        init, readme, log = self.apply("0.7.0.dev3")
        stale_init = init.replace("0.7.0.dev3", "0.7.0.dev4")
        found = problems(stale_init, readme, log)
        self.assertTrue(any("README.md" in p for p in found), found)
        released = log.replace("(в работе)", "— 2026-11-20")
        self.assertTrue(
            any("(в работе)" in p for p in problems(init, readme, released))
        )
        self.assertTrue(problems(init, "без блока", log))


if __name__ == "__main__":
    unittest.main()
