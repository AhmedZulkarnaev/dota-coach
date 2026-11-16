"""Короткие объяснения «почему этот предмет» на русском.

Сюда же в будущем можно подключить языковую модель: функция explain() —
единственная
точка, которую для этого нужно заменить (с фолбэком на шаблон при задержке > 1
с).
"""

from typing import Any

from . import rules
from .item_db import ItemDB

_RULES = rules.load("items")
# Зачем предмет: coach/data/items.json, раздел why.
WHY: dict[str, str] = rules.flat(_RULES["why"])

GENERIC_BY_STAGE: dict[str, str] = _RULES["generic_by_stage"]

ATTR_RU: dict[str, str] = _RULES["attributes"]


def stats_summary(item_data: dict[str, Any] | None, limit: int = 3) -> str:
    parts = []
    for a in (item_data or {}).get("attrib") or []:
        if not isinstance(a, dict):
            continue
        ru = ATTR_RU.get(str(a.get("key")))
        val = a.get("value")
        if not ru or val in (None, "", "0"):
            continue
        if isinstance(val, list):
            val = val[0]
        val = str(val).split(" ")[0]
        sep = "" if ru.startswith("%") else " "
        parts.append(f"+{val}{sep}{ru}")
        if len(parts) >= limit:
            break
    return ", ".join(parts)


def essence(item: str, item_db: ItemDB) -> str:
    """Кратко: что даёт предмет.

    Ручной текст (если есть) + кнопка + основные статы.
    """
    data = item_db.items.get(item) or {}
    text = WHY.get(item, "")
    active = [
        a.get("title")
        for a in data.get("abilities") or []
        if isinstance(a, dict) and a.get("type") == "active" and a.get("title")
    ]
    if active and not text:
        text = f"Активная способность: {active[0]}."
    stats = stats_summary(data, limit=3)
    if stats:
        text = (text + " " if text else "") + f"Статы: {stats}."
    return text or "Популярный предмет на этом герое."


def explain(
    item: str,
    item_db: ItemDB,
    stage: str,
    hero_title: str = "",
    partial: bool = False,
) -> str:
    text = WHY.get(item)
    if not text:
        text = GENERIC_BY_STAGE.get(stage, "")
        stats = stats_summary(item_db.items.get(item))
        if stats:
            text += f" Даёт: {stats}."
    if partial:
        text += (
            " Часть компонентов уже есть — закончите сборку, прежде чем "
            "начинать новую."
        )
    return text.strip()
