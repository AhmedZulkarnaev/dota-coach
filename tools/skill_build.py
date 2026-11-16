"""Порядок прокачки героя по свежим матчам сильных игроков (OpenDota).

    python tools/skill_build.py ursa
    python tools/skill_build.py "Phantom Assassin"
    python tools/skill_build.py 70 --fresh     скачать заново, не из кэша

Печатает план, который программа будет подсказывать в игре: уровень героя,
что качать и сколько игроков сделали так же. Данные сохраняются в
data_cache/ — программа возьмёт их оттуда.
"""

import argparse
import sys
import urllib.error
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coach import settings as settings_mod  # noqa: E402
from coach.data_store import DataStore  # noqa: E402
from coach.skill_builds import consensus, talent_title  # noqa: E402

NPC_PREFIX = "npc_dota_hero_"


def find_hero(heroes: dict[str, Any], query: str) -> tuple[int, str] | None:
    """Герой по id, внутреннему имени (ursa) или английскому названию."""
    q = query.strip().lower().replace(" ", "_")
    for h in heroes.values():
        if not isinstance(h, dict):
            continue
        short = str(h.get("name", "")).removeprefix(NPC_PREFIX)
        title = str(h.get("localized_name", ""))
        if q in (str(h.get("id")), short, title.lower().replace(" ", "_")):
            return int(h["id"]), title
    return None


def format_plan(
    builds: list[list[str]], abilities: dict[str, Any] | None
) -> str:
    plan = consensus(builds)
    if not plan:
        return "Мало разобранных матчей — план не построить."
    lines = [f"Матчей: {len(builds)}", ""]
    for step in plan:
        mark = "★" if step.is_talent else " "
        title = talent_title(step.name, abilities)
        share = f"{step.votes}/{step.total}"
        lines.append(f"  {step.level:>2} ур. {mark} {title:<32} {share:>5}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("hero", help="ursa, «Phantom Assassin» или id героя")
    ap.add_argument("--fresh", action="store_true", help="скачать заново")
    args = ap.parse_args()

    store = DataStore(settings_mod.CACHE_DIR)
    try:
        if not store.heroes or not store.ability_ids:
            print("Скачиваю героев и способности OpenDota…")
            store._refresh_constants(force=False)
        found = find_hero(store.heroes, args.hero)
        if not found:
            print(f"✗ Герой «{args.hero}» не найден.")
            return 1
        hero_id, title = found
        # Кэш читаем напрямую: get_skill_builds запустил бы ещё и фоновую
        # загрузку параллельно с нашей.
        cached = None if args.fresh else store._read(f"skills_{hero_id}")
        builds = (cached or {}).get("builds")
        if not builds:
            print(f"Скачиваю матчи {title} (~20 секунд)…")
            store._refresh_skills(hero_id)
            builds = store.skills[hero_id]["builds"]
    except (urllib.error.URLError, OSError) as e:
        print(f"✗ Нет связи с OpenDota: {e}")
        return 1
    print(f"{title} — порядок прокачки (★ — талант)\n")
    print(format_plan(builds, store.abilities))
    return 0


if __name__ == "__main__":
    sys.exit(main())
