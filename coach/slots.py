"""Учёт места в инвентаре.

В Dota 6 активных слотов + 3 слота рюкзака (предметы в рюкзаке не работают)
+ тайник на базе. TP-свиток и нейтральный предмет живут в отдельных слотах.

Новый предмет должен попасть в 6 активных слотов. Предметы из тайника
тоже придут в инвентарь, поэтому считаются вместе с ним. То, что уже лежит
в рюкзаке, активные слоты не занимает.

Когда места нет, решаем, что убрать и КАК:
  • расходники (Tango, Flask, Clarity…) — «используйте»;
  • варды — «поставьте»;
  • стартовые мелочи и дешёвые статы — «продайте» (Dota возвращает половину
    цены);
  • дорогие вещи — «переложите в рюкзак», если там есть место;
  • ботинки не трогаем, кроме покупки других ботинок взамен.
"""

from collections import Counter
from collections.abc import Iterable, Sequence

from .item_db import BOOTS, ItemDB

Items = Sequence[str]

MAIN_SLOTS = 6
BACKPACK_SLOTS = 3

# Покупаются и сразу «съедаются» — слот не занимают.
NO_SLOT = {"aghanims_shard", "tome_of_knowledge"}

USE_UP = {
    "tango",
    "tango_single",
    "flask",
    "clarity",
    "faerie_fire",
    "enchanted_mango",
    "famango",
    "great_famango",
    "greater_famango",
    "blood_grenade",
}
WARDS = {"ward_observer", "ward_sentry", "ward_dispenser"}
# Носят специально — убираем в последнюю очередь.
UTILITY = {"dust", "smoke_of_deceit", "gem", "bottle"}

STARTER_JUNK = {
    "branches",
    "quelling_blade",
    "magic_stick",
    "orb_of_venom",
    "blight_stone",
    "gauntlets",
    "slippers",
    "mantle",
    "circlet",
    "ring_of_protection",
    "sobi_mask",
    "ring_of_regen",
    "ring_of_tarrasque",
    "fluffy_hat",
    "wind_lace",
    "infused_raindrop",
    "headdress",
    "buckler",
}
CHEAP_STATS = {
    "bracer",
    "wraith_band",
    "null_talisman",
    "magic_wand",
    "soul_ring",
    "falcon_blade",
    "orb_of_corrosion",
    "urn_of_shadows",
    "ring_of_basilius",
    "hand_of_midas",
}

VERB_USE, VERB_WARD, VERB_SELL, VERB_PARK = (
    "используйте",
    "поставьте",
    "продайте",
    "в рюкзак",
)
VERB_SELL_BP, VERB_USE_BP = "продайте из рюкзака", "используйте из рюкзака"


def sell_rank(item: str, db: ItemDB, target: str) -> tuple[int, int] | None:
    """Чем меньше — тем раньше стоит убрать предмет. None — не трогать."""
    cost = db.cost(item)
    if item in BOOTS:
        # Старые ботинки убираем только если покупаем другие ботинки.
        return (-1, cost) if target in BOOTS and item != target else None
    if item in USE_UP or item in WARDS:
        return (0, cost)
    if item in STARTER_JUNK or cost <= 300:
        return (1, cost)
    if item in CHEAP_STATS:
        return (2, cost)
    if item in UTILITY:
        return (4, cost)
    return (3, cost)


def _after(
    inventory: Items, backpack: Items, stash: Items, used: Items, target: str
) -> tuple[list[str], list[str]]:
    """(активные предметы, предметы в рюкзаке) после покупки target."""
    active_count = Counter(list(inventory) + list(stash))
    parked_count = Counter(backpack)
    for u in used:  # компоненты исчезают при сборке
        if parked_count[u] > 0:
            parked_count[u] -= 1
        elif active_count[u] > 0:
            active_count[u] -= 1
    active = list(active_count.elements())
    if target not in NO_SLOT:
        active.append(target)
    return active, list(parked_count.elements())


class SlotPlan:
    """Что сделать с инвентарём ради покупки target.

    actions      — [(глагол, предмет)] по порядку;
    removed      — предметы, которые уходят из АКТИВНЫХ слотов (для оценки «не
    ухудшение ли»);
    refund       — золото за продажу (половина цены);
    overflow     — сколько предметов не помещается в 6 слотов (<= 0 — место
    есть);
    stuck        — убрать нечего, всё ценное;
    free_after   — сколько мест (из 9: 6 слотов + рюкзак) останется свободным
    после действий.
    """

    def __init__(self) -> None:
        self.actions: list[tuple[str, str]] = []
        self.removed: list[str] = []
        self.refund = 0
        self.overflow = 0
        self.stuck = False
        self.free_after = 0


def plan_slots(
    inventory: Items,
    backpack: Items,
    stash: Items,
    used: Items,
    target: str,
    db: ItemDB,
    parts_to_buy: int = 0,
) -> SlotPlan:
    """parts_to_buy — сколько отдельных частей ещё нужно купить: пока предмет
    не собран,
    каждая часть тоже занимает место (иначе останется в тайнике и не будет
    работать)."""
    plan = SlotPlan()
    active, parked = _after(inventory, backpack, stash, used, target)
    plan.overflow = len(active) - MAIN_SLOTS

    def rank(x: str) -> tuple[int, int] | None:
        return sell_rank(x, db, target)

    def sell(x: str, from_backpack: bool = False) -> None:
        plan.actions.append((VERB_SELL_BP if from_backpack else VERB_SELL, x))
        plan.refund += db.cost(x) // 2

    # 1) освобождаем активные слоты
    pool = list(active)
    if target in pool:
        pool.remove(target)
    for _ in range(max(0, plan.overflow)):
        cands = sorted((r, x) for x in pool if (r := rank(x)) is not None)
        if not cands:
            plan.stuck = True
            break
        (cat, _cost), x = cands[0]
        pool.remove(x)
        plan.removed.append(x)
        if x in WARDS:
            plan.actions.append((VERB_WARD, x))
        elif x in USE_UP:
            plan.actions.append((VERB_USE, x))
        elif cat >= 3:
            # Дорогую вещь жалко продавать: кладём в рюкзак, а если он полон —
            # продаём оттуда самое дешёвое (оно всё равно не работает).
            if len(parked) >= BACKPACK_SLOTS:
                x_rank = (cat, _cost)
                bp = sorted(
                    (r, y)
                    for y in parked
                    if (r := rank(y)) is not None and r < x_rank
                )
                if bp:
                    y = bp[0][1]
                    parked.remove(y)
                    sell(y, from_backpack=True)
            if len(parked) < BACKPACK_SLOTS:
                parked.append(x)
                plan.actions.append((VERB_PARK, x))
            else:
                sell(x)
        else:
            sell(x)

    # 2) места под части: всё занято — продаём мусор из рюкзака
    carried = len(pool) + (0 if target in NO_SLOT else 1) + len(parked)
    need_free = max(
        0, parts_to_buy - 1
    )  # первая часть встанет на место будущего предмета
    while carried + need_free > MAIN_SLOTS + BACKPACK_SLOTS:
        bp = sorted(
            (r, y) for y in parked if (r := rank(y)) is not None and r[0] <= 2
        )
        if not bp:
            break
        y = bp[0][1]
        parked.remove(y)
        if y in USE_UP:
            plan.actions.append((VERB_USE_BP, y))
        else:
            sell(y, from_backpack=True)
        carried -= 1
    plan.free_after = MAIN_SLOTS + BACKPACK_SLOTS - carried
    return plan


def is_downgrade(
    inventory: Items,
    backpack: Items,
    stash: Items,
    used: Items,
    target: str,
    db: ItemDB,
) -> bool:
    """Если ради предмета придётся убрать вещь почти такой же цены — это не
    улучшение.
    """
    plan = plan_slots(inventory, backpack, stash, used, target, db)
    if plan.overflow <= 0:
        return False
    if plan.stuck:
        return True  # убрать нечего — всё ценное
    weakest = max(db.cost(x) for x in plan.removed)
    return weakest >= 0.6 * db.cost(target)


def describe(actions: Iterable[tuple[str, str]], db: ItemDB) -> str:
    """'используйте Tango; продайте Iron Branch; из рюкзака продайте Wraith
    Band' — для окна и голоса.
    """
    groups: dict[str, list[str]] = {}
    for verb, x in actions:
        groups.setdefault(verb, []).append(db.dname(x))
    parts = []
    for verb in (
        VERB_USE,
        VERB_USE_BP,
        VERB_WARD,
        VERB_SELL_BP,
        VERB_SELL,
        VERB_PARK,
    ):
        if verb in groups:
            names = ", ".join(groups[verb])
            if verb == VERB_PARK:
                parts.append(f"переложите {names} в рюкзак")
            elif verb == VERB_SELL_BP:
                parts.append(f"продайте из рюкзака {names}")
            elif verb == VERB_USE_BP:
                parts.append(f"используйте из рюкзака {names}")
            else:
                parts.append(f"{verb} {names}")
    return "; ".join(parts)
