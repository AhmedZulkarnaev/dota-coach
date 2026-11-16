"""Проверка правил советов: встроенных (coach/data) и своих (rules/).

    python tools/check_rules.py

Что проверяется:
  • формат каждого файла: нужные ключи, типы, теги, регулярные выражения,
    подстановки в текстах;
  • свои файлы из rules/ — подключатся ли они (ошибка = файл пропускается);
  • имена предметов, героев и способностей — есть ли они в данных OpenDota
    (если программа уже скачала их в data_cache/). После патча Valve так
    видно, что предмет переименовали или убрали.

Код выхода 1 — есть ошибки формата; предупреждения об именах не ошибка.
"""

import logging
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coach import rules  # noqa: E402
from coach import settings as settings_mod  # noqa: E402

NPC_PREFIX = "npc_dota_hero_"


def unknown_names(
    items: Iterable[str],
    heroes: Iterable[str],
    abilities: Iterable[str],
) -> list[str]:
    """Имена из правил, которых нет в данных OpenDota.

    items — внутренние имена предметов (tango, black_king_bar);
    heroes — имена героев без npc_dota_hero_ (ursa);
    abilities — имена способностей (ursa_earthshock).
    """
    known_items, known_heroes = set(items), set(heroes)
    known_abilities = set(abilities)
    found: list[str] = []

    def check(where: str, names: Iterable[str], known: set[str]) -> None:
        if not known:  # этих данных нет в кэше — проверять не с чем
            return
        missing = sorted(set(names) - known)
        if missing:
            found.append(f"{where}: нет в OpenDota — {', '.join(missing)}")

    it = rules.load("items")
    check("items.json → why", rules.flat(it["why"]), known_items)
    sl = rules.load("slots")
    for key in rules.SLOT_KEYS:
        check(f"slots.json → {key}", sl[key], known_items)
    en = rules.load("enemies")
    counter_items = [
        r[role]["item"]
        for r in en["counters"]
        for role in rules.ROLES
        if role in r
    ]
    check("enemies.json → counters", counter_items, known_items)
    for name, g in en["groups"].items():
        check(f"enemies.json → {name}", g.get("heroes", []), known_heroes)
    check(
        "heroes_ru.json → aliases",
        rules.load("heroes_ru")["aliases"],
        known_heroes,
    )
    ab = rules.flat(rules.load("abilities")["tips"])
    check("abilities.json → tips", ab, known_abilities)
    return found


def cache_names(cache: Path) -> tuple[list[str], list[str], list[str]]:
    """Имена из data_cache/ программы (пусто, если данных ещё нет)."""

    def read(name: str) -> dict[str, Any]:
        path = cache / f"{name}.json"
        try:
            data = rules.read_json(path)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    heroes = [
        str(h.get("name", "")).removeprefix(NPC_PREFIX)
        for h in read("heroes").values()
        if isinstance(h, dict)
    ]
    return list(read("items")), heroes, list(read("abilities"))


def main() -> int:
    # Ошибки своих правил печатаются ниже, журнал их не дублирует.
    logging.getLogger(rules.__name__).setLevel(logging.ERROR)
    errors = 0
    print("Встроенные правила (coach/data):")
    for name in rules.NAMES:
        path = rules.DATA_DIR / f"{name}.json"
        try:
            found = rules.validate(name, rules.read_json(path))
        except (OSError, ValueError) as e:
            found = [str(e)]
        errors += len(found)
        print(f"  {'✗' if found else '✓'} {name}.json")
        for problem in found:
            print(f"      {problem}")

    problems = rules.user_problems()
    paths = rules.user_paths()
    print("\nСвои правила (rules/ рядом с main.py):")
    if not paths:
        print("  нет — работают встроенные")
    for path in paths:
        found = problems.get(rules.label(path), [])
        errors += len(found)
        mark = "✗ пропущен" if found else "✓ подключён"
        print(f"  {mark}: {rules.label(path)}")
        for problem in found:
            print(f"      {problem}")

    items, heroes, abilities = cache_names(settings_mod.CACHE_DIR)
    print("\nИмена по данным OpenDota (data_cache/):")
    if not (items or heroes or abilities):
        print("  данных ещё нет — запустите программу один раз")
    else:
        warnings = unknown_names(items, heroes, abilities)
        for w in warnings:
            print(f"  ! {w}")
        if not warnings:
            print("  ✓ все предметы, герои и способности на месте")

    print("\n✓ Ошибок нет." if not errors else f"\n✗ Ошибок: {errors}.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
