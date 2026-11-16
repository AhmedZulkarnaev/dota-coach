"""Учёт состава врагов (игрок вводит героев вручную — GSI их не даёт).

Угрозы определяются двумя способами:
  • роли героя из OpenDota (Disabler — много контроля, Nuker — много
    магического урона);
  • короткие списки героев — особенности наборов способностей, которые редко
    меняются.
Сами признаки и советы — в coach/data/enemies.json.
"""

from collections.abc import Sequence
from typing import Any

from . import rules

_RULES = rules.load("enemies")


class EnemyCounter:
    """Ситуативный предмет против врагов."""

    def __init__(self, item: str, reason: str, strength: float) -> None:
        self.item, self.reason, self.strength = item, reason, strength


def analyze(
    enemy_shorts: Sequence[str],
    heroes_by_short: dict[str, dict[str, Any]],
    my_role: str,
    data: dict[str, Any] | None = None,
) -> tuple[list[EnemyCounter], list[str], list[str]]:
    """Возвращает (counters, reminders, summary).

    enemy_shorts — внутренние имена героев врага ("lion",
    "phantom_assassin"...)
    heroes_by_short — словарь short -> данные героя OpenDota (нужны roles)
    my_role — "core" или "support"
    data — правила (по умолчанию coach/data/enemies.json)
    """
    data = data or _RULES
    counters: list[EnemyCounter] = []
    reminders: list[str] = []
    summary: list[str] = []
    if not enemy_shorts:
        return counters, reminders, summary

    def roles(s: str) -> set[str]:
        return set((heroes_by_short.get(s) or {}).get("roles") or [])

    def names(lst: list[str]) -> str:
        return ", ".join(
            (heroes_by_short.get(s) or {}).get("localized_name") or s
            for s in lst
        )

    found: dict[str, list[str]] = {}
    for name, g in data["groups"].items():
        if "role" in g:
            found[name] = [s for s in enemy_shorts if g["role"] in roles(s)]
        else:
            heroes = set(g["heroes"])
            found[name] = [s for s in enemy_shorts if s in heroes]
        if found[name]:
            n = len(found[name])
            summary.append(
                f"{g['label']} ×{n}" if g.get("count") else g["label"]
            )

    # Подстановки в текст: {disabler} — сколько героев, {evasion_names} — кто.
    fill: dict[str, int | str] = {k: len(v) for k, v in found.items()}
    fill |= {f"{k}_names": names(v) for k, v in found.items()}
    role = "core" if my_role == "core" else "support"

    def matches(rule: dict[str, Any]) -> bool:
        return all(len(found[g]) >= n for g, n in rule["when"].items())

    taken: set[str] = set()  # exclusive-группы, где правило уже сработало
    for rule in data["counters"]:
        group = rule.get("exclusive")
        if group in taken or not matches(rule):
            continue
        if group:
            taken.add(group)
        advice = rule.get(role)
        if advice:
            text = advice["reason"].format_map(fill)
            counters.append(
                EnemyCounter(advice["item"], text, advice["strength"])
            )
    for rule in data["reminders"]:
        if matches(rule) and rule.get(role):
            reminders.append(rule[role].format_map(fill))
    return counters, reminders, summary
