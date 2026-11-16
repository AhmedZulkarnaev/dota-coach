"""Русские и сленговые названия героев: используются для поиска при вводе
врагов.

Ключ — внутреннее имя героя без префикса npc_dota_hero_ (так его присылают GSI
и OpenDota).
Английское название берётся из OpenDota, поэтому поиск по-английски работает
для всех героев,
даже если здесь героя нет.
"""

from . import rules

ALIASES: dict[str, list[str]] = rules.load("heroes_ru")["aliases"]


NPC_PREFIX = "npc_dota_hero_"


def short_name(npc_name: str) -> str:
    """npc_dota_hero_ursa → ursa."""
    return npc_name.removeprefix(NPC_PREFIX)


def ru_title(short: str) -> str:
    names = ALIASES.get(short)
    return names[0].capitalize() if names else ""
