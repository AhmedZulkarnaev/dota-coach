"""Подсказки «когда использовать способности».

Откуда берутся:
  1. Список способностей, их уровень, перезарядка и готовность — из GSI (вашего
     героя видно).
  2. Короткий совет:
     • для популярных героев — написан вручную в coach/data/abilities.json;
     • для остальных — собирается автоматически по описанию способности из
       OpenDota
       (/constants/abilities): ищем в описании оглушение, замедление, урон,
       побег и т.п.
  3. «Живые» подсказки по текущей ситуации: ульт готов, мало здоровья — нажмите
     защиту,
     мало маны — не тратьте способности на крипов.
"""

import re
from typing import Any

from . import rules
from .game_state import GameState

Abilities = dict[str, Any] | None

# Ручные советы: ключ — внутреннее имя способности, как его присылает GSI.
# (теги нужны для живых подсказок: defend/escape — спасают при низком здоровье)
_RULES = rules.load("abilities")
# Ручные советы (coach/data/abilities.json): ключ — внутреннее имя способности,
# как его присылает GSI. Теги нужны для живых подсказок: defend/escape —
# спасают при низком здоровье.
TIPS: dict[str, tuple[str, set[str]]] = {
    name: (tip["text"], set(tip["tags"]))
    for name, tip in rules.flat(_RULES["tips"]).items()
}

GENERIC: dict[str, str] = _RULES["generic"]
TAG_ORDER: list[str] = _RULES["tag_order"]

KEYWORDS: list[tuple[str, str]] = [
    (k["tag"], k["regex"]) for k in _RULES["keywords"]
]


def _behavior(data: dict[str, Any]) -> str:
    b = data.get("behavior") or ""
    return " ".join(b) if isinstance(b, list) else str(b)


def classify(name: str, abilities_const: Abilities) -> set[str]:
    """Теги способности: из ручного списка или по описанию OpenDota."""
    if name in TIPS:
        return TIPS[name][1]
    data = (abilities_const or {}).get(name) or {}
    if "Passive" in _behavior(data):
        return {"passive"}
    desc = (data.get("desc") or "").lower()
    tags = {tag for tag, rx in KEYWORDS if re.search(rx, desc)}
    return tags or {"nuke"}


def tip_for(
    name: str, abilities_const: Abilities, ultimate: bool = False
) -> str:
    if name in TIPS:
        return TIPS[name][0]
    tags = classify(name, abilities_const)
    if "passive" in tags:
        return GENERIC["passive"]
    main = next((t for t in TAG_ORDER if t in tags), "nuke")
    text = GENERIC[main]
    if ultimate:
        text = (
            "Ульт — берегите для командной драки или верного убийства. " + text
        )
    return text


def title_for(name: str, abilities_const: Abilities) -> str:
    data = (abilities_const or {}).get(name) or {}
    return (
        data.get("dname") or name.split("_", 1)[-1].replace("_", " ").title()
    )


def ability_advice(
    gs: GameState, abilities_const: Abilities
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Возвращает (live, lines).

    live  — срочные подсказки по ситуации (их видно первыми);
    lines — [(название, совет, состояние)] для каждой способности героя.
    """
    live: list[str] = []
    lines: list[tuple[str, str, str]] = []
    abil = [a for a in gs.abilities if a.get("name")]
    if not abil:
        return live, lines
    learned = [a for a in abil if a.get("level", 0) > 0] or abil

    for a in learned:
        name = a["name"]
        title = title_for(name, abilities_const)
        tags = classify(name, abilities_const)
        if (
            a.get("passive")
            or "passive" in tags
            and not ({"defend", "buff"} & tags)
        ):
            state = "пассивная"
        elif a.get("level", 0) == 0:
            state = "не изучена"
        elif a.get("cooldown", 0) > 0:
            state = f"перезарядка {a['cooldown']} с"
        elif a.get("can_cast"):
            state = "готова"
        else:
            state = "нет маны" if gs.mana_pct < 100 else "недоступна"
        tip = tip_for(name, abilities_const, a.get("ultimate", False))
        if a.get("ultimate") or "ult" in tags:
            title += " (ульт)"
        lines.append((title, tip, state))

    ready = [
        a
        for a in learned
        if a.get("can_cast")
        and a.get("level", 0) > 0
        and a.get("cooldown", 0) == 0
    ]
    ult = [
        a
        for a in ready
        if a.get("ultimate") or "ult" in classify(a["name"], abilities_const)
    ]
    if gs.alive and 0 < gs.hp_pct <= 35:
        saver = [
            a
            for a in ready
            if {"defend", "escape", "heal"}
            & classify(a["name"], abilities_const)
        ]
        if saver:
            live.append(
                f"Мало здоровья ({gs.hp_pct}%) — нажмите "
                f"{title_for(saver[0]['name'], abilities_const)}, "
                "чтобы выжить."
            )
        else:
            live.append(
                f"Мало здоровья ({gs.hp_pct}%) — отходите к своим, не "
                "начинайте драку."
            )
    if ult and gs.alive and not any(a.get("passive") for a in ult):
        live.append(
            f"Ульт {title_for(ult[0]['name'], abilities_const)} готов — "
            "берегите его для драки."
        )
    if (
        gs.alive
        and 0 < gs.mana_pct <= 20
        and any(not a.get("passive") for a in learned)
    ):
        live.append(
            "Мало маны — не тратьте способности на крипов, оставьте на драку."
        )
    return live, lines
