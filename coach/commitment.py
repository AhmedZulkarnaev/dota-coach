"""«Верность цели»: совет не прыгает с предмета на предмет.

Без этого цель менялась от малейшего изменения весов: на 10:00 (смена
стадии) или когда купленная часть подходила сразу к двум предметам. Игрок
копил на одно, а программа вдруг советовала другое.

Теперь выбранный предмет держится, пока он не собран. Цель меняется только
по понятной причине, и эта причина показывается игроку:
  • предмет собран — «BKB собран — следующий: Blink Dagger»;
  • игрок сам купил часть другого предмета — совет следует за ним;
  • изменился состав врагов или роль — совет пересчитывается;
  • предмет больше не подходит (стадия прошла, некуда положить);
  • другой предмет стал заметно важнее (в SWITCH_MARGIN раз).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from .item_db import CONSUMABLES, ItemDB

SWITCH_MARGIN = 1.5  # во сколько раз новый предмет должен быть важнее
MIN_PURCHASE = 300  # дешевле — не считаем осознанной покупкой (ветки, танго)


@dataclass
class Commitment:
    match_id: str
    target: str
    clock: int
    owned: frozenset[str]
    enemies: tuple[str, ...]
    role: str


@dataclass
class Choice:
    target: str
    note: str = ""  # почему совет сменился (пусто — не менялся)
    commitment: Commitment | None = field(default=None, repr=False)


def _real_items(owned: Sequence[str], db: ItemDB) -> frozenset[str]:
    return frozenset(
        x for x in owned if x not in CONSUMABLES and db.cost(x) >= MIN_PURCHASE
    )


def choose_target(
    ranked: Sequence[tuple[str, float]],
    prev: Commitment | None,
    *,
    match_id: str,
    clock: int,
    owned: Sequence[str],
    enemies: Sequence[str],
    role: str,
    db: ItemDB,
) -> Choice:
    """Выбирает цель с учётом прошлого выбора.

    ranked — кандидаты по убыванию важности (не пустой список).
    """
    best, best_score = ranked[0]
    scores = dict(ranked)
    items = _real_items(owned, db)
    enemies_t = tuple(sorted(enemies))

    def fresh(note: str = "") -> Choice:
        commit = Commitment(match_id, best, clock, items, enemies_t, role)
        return Choice(best, note, commit)

    if (
        prev is None
        or prev.match_id != match_id
        or clock < prev.clock - 30  # время пошло назад: другой матч/запись
    ):
        return fresh()

    old, new = db.dname(prev.target), db.dname(best)
    if prev.target in owned or prev.target in db.covered(owned):
        return fresh(f"{old} собран — следующий: {new}.")
    if prev.enemies != enemies_t:
        note = "" if best == prev.target else "Совет пересчитан под врагов."
        return fresh(note)
    if prev.role != role:
        note = "" if best == prev.target else "Совет пересчитан под роль."
        return fresh(note)

    # Игрок сам купил что-то, что не входит в текущую цель, — следуем за ним.
    bought = items - prev.owned - db.subtree(prev.target) - {prev.target}
    if bought:
        if best == prev.target:
            return fresh()
        piece = next(
            (x for x in sorted(bought) if x in db.subtree(best)), None
        )
        if piece:
            return fresh(
                f"Вы купили {db.dname(piece)} — проще закончить {new}."
            )
        return fresh("Совет пересчитан после вашей покупки.")

    if prev.target not in scores:
        return fresh(f"{old} уже не в приоритете — следующий: {new}.")
    if (
        best != prev.target
        and best_score >= SWITCH_MARGIN * scores[prev.target]
    ):
        return fresh(f"Сейчас важнее {new}, чем {old}.")

    # Держим прежнюю цель.
    commit = Commitment(match_id, prev.target, clock, items, enemies_t, role)
    return Choice(prev.target, "", commit)
