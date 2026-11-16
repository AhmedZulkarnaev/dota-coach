"""Порядок прокачки способностей и талантов — по настоящим матчам.

Откуда данные: OpenDota хранит разобранные матчи сильных игроков, и в каждом
записан порядок прокачки — players[].ability_upgrades_arr: номера способностей
по очереди, как игрок тратил очки. Берём 15 свежих матчей на героя (раз в
патч) и строим общий план: на каждом шаге — самый частый выбор, который
допустим после предыдущих шагов.

Важно: N-й элемент — это N-е очко прокачки, а не N-й уровень героя. На уровнях
17, 19 и 21–24 Dota очков не даёт.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .game_state import GameState

# На каких уровнях героя дают очко прокачки (по порядку очков).
POINT_LEVELS = [*range(1, 17), 18, 20, *range(25, 31)]
MIN_BUILDS = 3  # меньше матчей на шаге — дальше план не строим
TALENT_PREFIX = "special_bonus"
ATTRIBUTES = "special_bonus_attributes"


@dataclass(frozen=True)
class Step:
    """Один шаг плана: на уровне level взять способность name."""

    level: int
    name: str
    votes: int  # сколько игроков сделали так на этом шаге
    total: int  # из скольких

    @property
    def is_talent(self) -> bool:
        return self.name.startswith(TALENT_PREFIX) and self.name != ATTRIBUTES


@dataclass(frozen=True)
class SkillHint:
    """Что подсказать игроку про прокачку."""

    step: Step
    title: str  # «Earthshock» или «+25 Attack Speed»
    new_level: int  # какой уровень способности будет после прокачки
    learn_now: bool  # есть свободное очко и способность можно взять сейчас
    free_points: int | None  # None — по данным игры не понять

    @property
    def text(self) -> str:
        if self.step.is_talent:
            what = f"талант {self.step.level}-го уровня: {self.title}"
        elif self.step.name == ATTRIBUTES:
            what = "бонус к атрибутам"
        else:
            what = f"{self.title} ({self.new_level}-й уровень)"
        head = "Качайте сейчас" if self.learn_now else "Следующая прокачка"
        return f"{head}: {what}"

    @property
    def why(self) -> str:
        s = self.step
        if not s.votes:
            return "Так сильные игроки качают в ближайшие уровни."
        return f"Так делают {s.votes} из {s.total} сильных игроков."


# ---------- данные OpenDota ----------
def build_from_match(
    match: Mapping[str, Any], hero_id: int, ability_ids: Mapping[str, str]
) -> list[str] | None:
    """Порядок прокачки героя hero_id в матче (None — матч не разобран)."""
    for p in match.get("players") or []:
        if not isinstance(p, dict) or p.get("hero_id") != hero_id:
            continue
        ups = p.get("ability_upgrades_arr")
        if not isinstance(ups, list) or not ups:
            return None
        names = [ability_ids.get(str(x), "") for x in ups]
        return names if all(names) else None
    return None


def consensus(
    builds: Iterable[Sequence[str]], min_builds: int = MIN_BUILDS
) -> list[Step]:
    """Общий план: на каждом шаге — самый частый допустимый выбор.

    Допустимый выбор:
      • после этого шага способность прокачана не больше раз, чем у
        кого-нибудь из игроков к этому же шагу — так план не нарушит правила
        Dota (ульт до 6-го уровня, вторая ступень раньше 3-го и т. п.);
      • он встречался вместе со всем, что уже есть в плане, хотя бы у
        одного игрока — так не возьмутся оба таланта одной ступени.
    Правила Dota для этого знать не нужно: всё следует из самих матчей.
    """
    builds = [list(b) for b in builds if b]
    together = [set(b) for b in builds]
    plan: list[Step] = []
    taken: Counter[str] = Counter()
    for i, level in enumerate(POINT_LEVELS):
        here = [b for b in builds if len(b) > i]
        if len(here) < min_builds:
            break
        caps: Counter[str] = Counter()
        for b in here:
            for name, n in Counter(b[: i + 1]).items():
                caps[name] = max(caps[name], n)
        votes = Counter(b[i] for b in here)
        # Запасные варианты: что игроки берут в ближайшие шаги, потом —
        # что они уже взяли к этому моменту (например, талант, который
        # каждый взял на своём уровне и ни на одном шаге не был первым).
        soon = Counter(x for b in here for x in b[i : i + 4])
        before = Counter(x for b in here for x in b[: i + 1])
        options = [name for name, _ in votes.most_common()]
        for name, _ in [*soon.most_common(), *before.most_common()]:
            if name not in options:
                options.append(name)
        for name in options:
            n = votes[name]
            fits = all(
                any(name in s and other in s for s in together)
                for other in taken
            )
            if fits and taken[name] + 1 <= caps[name]:
                plan.append(Step(level, name, n, len(here)))
                taken[name] += 1
                break
        else:  # ничего не подошло — дальше данные слишком разные
            break
    return plan


# ---------- что делать сейчас ----------
TIER_LEVELS = {10: 1, 15: 2, 20: 3, 25: 4}


def current_levels(gs: GameState, plan: Sequence[Step]) -> dict[str, int]:
    """Уровни способностей и талантов, сверенные с планом.

    Если игра присылает таланты флажками talent_N (без имён), талант плана
    считается взятым, когда взята его ступень.
    """
    levels = dict(gs.ability_levels)
    for step in plan:
        tier = TIER_LEVELS.get(step.level)
        if step.is_talent and tier in gs.talent_tiers:
            levels.setdefault(step.name, 1)
    return levels


def points_spent(gs: GameState) -> int:
    talents = sum(
        1
        for name, lv in gs.ability_levels.items()
        if name.startswith(TALENT_PREFIX) and name != ATTRIBUTES and lv > 0
    )
    other = sum(
        lv
        for name, lv in gs.ability_levels.items()
        if not name.startswith(TALENT_PREFIX) or name == ATTRIBUTES
    )
    # Таланты флажками: если имён талантов нет, считаем ступени.
    return other + max(talents, len(gs.talent_tiers))


def points_earned(hero_level: int) -> int:
    return sum(1 for lv in POINT_LEVELS if lv <= hero_level)


def free_points(gs: GameState) -> int | None:
    """Сколько очков прокачки не потрачено (None — не понять по данным).

    С 10-го уровня нужны данные о талантах: без них потраченное не сосчитать.
    """
    if gs.hero_level <= 0 or not gs.ability_levels:
        return None
    if gs.hero_level >= 10 and not gs.talents_known:
        return None
    free = points_earned(gs.hero_level) - points_spent(gs)
    return free if 0 <= free <= 5 else None


def can_learn(
    step: Step, levels: Mapping[str, int], hero_level: int, ultimate: bool
) -> bool:
    """Позволяет ли Dota взять этот шаг на текущем уровне героя."""
    new = levels.get(step.name, 0) + 1
    if step.name.startswith(TALENT_PREFIX):
        return hero_level >= step.level
    if ultimate:
        return hero_level >= 6 * new
    return new <= (hero_level + 1) // 2


def next_step(
    plan: Sequence[Step],
    levels: Mapping[str, int],
    hero_level: int,
    ultimates: Iterable[str] = (),
) -> tuple[Step, int, bool] | None:
    """Следующий шаг плана, который игрок ещё не сделал.

    Возвращает (шаг, новый уровень способности, можно ли взять сейчас).
    Если игрок качался по-своему, план всё равно продолжается: берётся
    первый невыполненный шаг, который Dota разрешит сейчас, а если такого
    нет — просто первый невыполненный.
    """
    ult = set(ultimates)
    need: Counter[str] = Counter()
    first: tuple[Step, int] | None = None
    for step in plan:
        need[step.name] += 1
        if levels.get(step.name, 0) >= need[step.name]:
            continue
        new = levels.get(step.name, 0) + 1
        if first is None:
            first = (step, new)
        if can_learn(step, levels, hero_level, step.name in ult):
            return step, new, True
    return (*first, False) if first else None


def talent_title(name: str, abilities_const: Mapping[str, Any] | None) -> str:
    """Название таланта или способности из OpenDota, без служебных вставок."""
    if name == ATTRIBUTES:
        return "бонус к атрибутам"
    data = (abilities_const or {}).get(name) or {}
    title = str(data.get("dname") or "")
    title = re.sub(r"\{s:[^}]*\}", "", title).replace("  ", " ").strip()
    if title:
        return title
    return name.split("_", 1)[-1].replace("_", " ").title()


def skill_hint(
    gs: GameState,
    plan: Sequence[Step],
    abilities_const: Mapping[str, Any] | None,
) -> SkillHint | None:
    """Подсказка прокачки для текущего состояния игры."""
    if not plan or gs.hero_level <= 0 or not gs.ability_levels:
        return None
    ultimates = {a["name"] for a in gs.abilities if a.get("ultimate")}
    levels = current_levels(gs, plan)
    found = next_step(plan, levels, gs.hero_level, ultimates)
    if not found:
        return None
    step, new, allowed = found
    free = free_points(gs)
    return SkillHint(
        step=step,
        title=talent_title(step.name, abilities_const),
        new_level=new,
        learn_now=allowed and bool(free),
        free_points=free,
    )
