"""Что именно покупать в лавке: список частей и один понятный следующий шаг.

Раньше окно показывало сразу три списка («осталось собрать», «можно купить
уже сейчас», «не хватает… осталось потратить…»), и было непонятно, что
делать. Теперь у каждой части предмета одно состояние, а сверху — одна
фраза: что купить прямо сейчас или на что копить.

  ✓ Ogre Axe        есть
  ▶ Mithril Hammer  1 600   купите сейчас
  ○ Рецепт          1 450   последним — соберёт предмет
"""

from dataclasses import dataclass

from .item_db import ItemDB

HAVE, NOW, LATER, RECIPE = "есть", "купите сейчас", "позже", "последним"


@dataclass
class Part:
    title: str
    cost: int
    state: str  # HAVE | NOW | LATER | RECIPE
    is_recipe: bool = False


@dataclass
class ShoppingList:
    parts: list[Part]
    next_step: str  # одна фраза: что делать сейчас
    buy_now: list[tuple[str, int]]  # что покупать прямо сейчас
    remaining: int  # сколько ещё потратить на предмет


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def shopping_list(
    target: str,
    owned: list[str],
    gold: int,
    db: ItemDB,
    no_room: bool = False,
) -> ShoppingList:
    """Список покупок для target.

    no_room — частям некуда лечь в инвентарь: копим на предмет целиком.
    """
    leaves, used = db.plan(target, owned)
    remaining = sum(db.cost(x) for x in leaves)
    parts = [Part(db.dname(u), db.cost(u), HAVE) for u in dict.fromkeys(used)]
    title = db.dname(target)
    recipes = [x for x in leaves if x.startswith("recipe_")]
    pieces = [x for x in leaves if not x.startswith("recipe_")]

    def part(x: str, state: str) -> Part:
        is_recipe = x.startswith("recipe_")
        name = "Рецепт" if is_recipe else db.dname(x)
        return Part(name, db.cost(x), state, is_recipe)

    if gold >= remaining:
        parts += [part(x, NOW) for x in leaves]
        buy = [(db.dname(x), db.cost(x)) for x in leaves]
        if len(leaves) == 1 and not used:
            step = f"Купите {title} — {_fmt(remaining)}."
        else:
            step = (
                f"Хватает на {title}: купите всё отмеченное ▶ — "
                "предмет соберётся сам."
            )
        return ShoppingList(parts, step, buy, remaining)

    lacking = remaining - gold
    if no_room:
        parts += [part(x, LATER) for x in pieces] + [
            part(x, RECIPE) for x in recipes
        ]
        step = (
            f"Копите на {title} целиком: не хватает {_fmt(lacking)}. "
            "По частям некуда положить."
        )
        return ShoppingList(parts, step, [], remaining)

    # Сначала самые дорогие части, на которые хватает; рецепт — последним:
    # сам по себе он ничего не даёт.
    now, left = [], gold
    for x in sorted(pieces, key=lambda x: -db.cost(x)):
        if db.cost(x) <= left:
            now.append(x)
            left -= db.cost(x)
    later = sorted((x for x in pieces if x not in now), key=db.cost)
    parts += [part(x, NOW) for x in now]
    parts += [part(x, LATER) for x in later]
    parts += [part(x, RECIPE) for x in recipes]
    buy = [(db.dname(x), db.cost(x)) for x in now]

    if now:
        names = ", ".join(db.dname(x) for x in now)
        step = f"Купите сейчас: {names}."
    elif later:
        cheapest = later[0]
        step = (
            f"Копите на {db.dname(cheapest)}: "
            f"не хватает {_fmt(db.cost(cheapest) - gold)}."
        )
    else:
        step = f"Осталось купить рецепт: не хватает {_fmt(lacking)}."
    return ShoppingList(parts, step, buy, remaining)
