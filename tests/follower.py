"""«Послушный игрок»: проходит матч, покупая ровно то, что советует программа.

Нужен, чтобы мерить скачки совета: если игрок ничего лишнего не покупал,
а цель сменилась до того, как предмет собран, — совет «прыгнул».
"""

from dataclasses import dataclass, field

from coach.advisor import Advisor
from coach.game_state import parse
from tests.helpers import payload


@dataclass
class FollowerRun:
    targets: list[tuple[int, str]] = field(
        default_factory=list
    )  # (время, цель)
    completed: list[tuple[int, str]] = field(default_factory=list)
    jumps: list[tuple[int, str, str]] = field(
        default_factory=list
    )  # (время, было, стало)
    inventory: list[str] = field(default_factory=list)


def combine(inventory, target, db):
    """Как в Dota: все части и рецепт на руках — предмет собирается сам."""
    items = [x for x in inventory if not x.startswith("recipe_")]
    recipes = [x for x in inventory if x.startswith("recipe_")]
    leaves, used = db.plan(target, items)
    if sorted(leaves) != sorted(r for r in recipes if r in leaves):
        return inventory, False
    for r in leaves:
        recipes.remove(r)
    for u in used:
        items.remove(u)
    return items + recipes + [target], True


def follow(
    advisor: Advisor,
    enemies=(),
    gpm=450,
    until=2700,
    step=10,
    start_items=("tango", "quelling_blade", "branches", "branches"),
):
    db = advisor.db
    run = FollowerRun()
    inventory = list(start_items)
    gold, current = 0, ""
    for clock in range(0, until, step):
        gold += gpm * step // 60
        shown = [x for x in inventory if not x.startswith("recipe_")]
        p = payload(clock, gold, items=shown[:9])
        a = advisor.advise(parse(p), enemies)
        if a.status != "ok":
            continue
        if a.target != current:
            if current and current not in inventory:
                run.jumps.append((clock, current, a.target))
            run.targets.append((clock, a.target))
            current = a.target
        # покупаем, как советуют: всё сразу, если хватает, иначе — части
        if a.can_buy_full:
            leaves, _ = db.plan(a.target, inventory)
            to_buy = leaves
        else:
            titles = {t for t, _ in a.buy_now}
            leaves, _ = db.plan(a.target, inventory)
            to_buy = [x for x in leaves if db.dname(x) in titles]
        for x in to_buy:
            cost = db.cost(x)
            if cost <= gold:
                gold -= cost
                inventory.append(x)
        inventory, done = combine(inventory, a.target, db)
        if done:
            run.completed.append((clock, a.target))
        # слоты: мусор выкидываем, как подсказывает программа
        while len(inventory) > 9:
            junk = min(inventory, key=db.cost)
            inventory.remove(junk)
    run.inventory = inventory
    return run
