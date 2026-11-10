"""Движок советов: какой предмет покупать следующим и почему.

Жёсткие правила + статистика OpenDota, никаких сетевых запросов во время
расчёта,
поэтому совет готов за миллисекунды.

Алгоритм:
 1. Берём популярность предметов на герое для текущей стадии (вес 1.0),
    следующей стадии (0.6, чтобы заранее копить на нужное) и предыдущей (0.5,
    если отстаёте).
 2. Выкидываем: расходники, нейтралки, рецепты, то что уже куплено или входит в
    купленное,
    вторые ботинки, дешёвые компоненты (они появятся в плане сборки),
    компоненты других кандидатов.
 3. Добавляем бонусы: за уже начатую сборку (не бросать на полпути) и за
    предметы
    против состава врагов.
 4. Для лучшего кандидата считаем, каких частей не хватает, сколько золота
    нужно и что
    можно купить прямо сейчас.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from . import enemies as enemies_mod
from . import slots as slots_mod
from .abilities import ability_advice
from .explanations import GENERIC_BY_STAGE, essence
from .game_state import POST_GAME, STAGE_TITLES, STAGES, GameState
from .heroes_ru import ru_title, short_name
from .item_db import BOOTS, CONSUMABLES, TIER2_BOOTS, USEFUL_CHEAP, ItemDB

Pairs = list[tuple[str, int]]  # [(название, цена)]

BUCKETS = {
    "start": "start_game_items",
    "lane": "early_game_items",
    "mid": "mid_game_items",
    "late": "late_game_items",
}


@dataclass
class Advice:
    status: str = "wait"  # wait | no_data | loading | start | ok | done
    message: str = ""
    hero_title: str = ""
    stage: str = ""
    stage_title: str = ""
    target: str = ""  # внутреннее имя предмета
    target_title: str = ""
    target_cost: int = 0
    remaining: int = 0  # сколько ещё потратить на предмет
    owned_value: int = 0  # стоимость уже имеющихся компонентов
    missing: Pairs = field(default_factory=list)
    buy_now: Pairs = field(default_factory=list)
    can_buy_full: bool = False
    why: str = ""  # почему именно сейчас
    next_items: list[str] = field(default_factory=list)
    situational: list[tuple[str, str]] = field(
        default_factory=list
    )  # [(предмет, причина)]
    reminders: list[str] = field(default_factory=list)
    enemy_summary: str = ""
    start_bundle: Pairs = field(default_factory=list)  # стартовая закупка
    slots_main: int = 0  # занято активных слотов (из 6)
    slots_backpack: int = 0  # занято в рюкзаке (из 3)
    slots_stash: int = 0
    free_up: list[tuple[str, str]] = field(
        default_factory=list
    )  # [(глагол, предмет)]
    free_up_text: str = ""
    free_up_refund: int = 0
    can_buy_with_sell: bool = False
    parts_no_room: bool = (
        False  # части некуда положить — копить на предмет целиком
    )
    what: str = ""  # что даёт предмет (кратко)
    ability_live: list[str] = field(
        default_factory=list
    )  # срочные: ульт готов, мало HP
    ability_lines: list[tuple[str, str, str]] = field(default_factory=list)


class Advisor:
    def __init__(self, store: Any) -> None:
        self.store = store
        self._db = ItemDB(None)
        self._db_src: Any = None
        self._heroes_src: Any = None
        self._heroes_by_short: dict[str, dict[str, Any]] = {}

    # ---------- данные ----------
    @property
    def db(self) -> ItemDB:
        if self._db_src is not self.store.items:
            self._db = ItemDB(self.store.items)
            self._db_src = self.store.items
        return self._db

    @property
    def heroes_by_short(self) -> dict[str, dict[str, Any]]:
        if self._heroes_src is not self.store.heroes:
            self._heroes_by_short = {}
            for h in (self.store.heroes or {}).values():
                if isinstance(h, dict) and h.get("name"):
                    self._heroes_by_short[short_name(h["name"])] = h
            self._heroes_src = self.store.heroes
        return self._heroes_by_short

    def hero_info(self, gs: GameState) -> dict[str, Any]:
        h = (self.store.heroes or {}).get(str(gs.hero_id))
        if not h and gs.hero_npc:
            h = self.heroes_by_short.get(short_name(gs.hero_npc))
        return h or {}

    def hero_title(self, gs: GameState) -> str:
        h = self.hero_info(gs)
        short = short_name(gs.hero_npc or h.get("name", ""))
        en = h.get("localized_name") or short.replace("_", " ").title()
        ru = ru_title(short)
        return f"{en} ({ru})" if ru and ru.lower() != en.lower() else en

    def role(self, gs: GameState, setting: str) -> str:
        if setting in ("core", "support"):
            return setting
        roles = set(self.hero_info(gs).get("roles") or [])
        if "Carry" in roles:
            return "core"
        if "Support" in roles:
            return "support"
        return "core"

    # ---------- основной расчёт ----------
    def advise(
        self,
        gs: GameState,
        enemy_shorts: Sequence[str] = (),
        role_setting: str = "auto",
    ) -> Advice:
        adv = Advice()
        if not gs.valid:
            adv.message = "Жду данные от Dota 2…"
            return adv
        if gs.game_state == POST_GAME:
            adv.message = (
                "Матч окончен. Журнал матча сохранён в папку match_logs."
            )
            return adv
        if gs.hero_id <= 0 and not gs.hero_npc:
            adv.message = "Герой ещё не выбран."
            return adv

        db = self.db
        adv.hero_title = self.hero_title(gs)
        adv.ability_live, adv.ability_lines = ability_advice(
            gs, getattr(self.store, "abilities", {})
        )
        adv.stage = gs.stage
        adv.stage_title = STAGE_TITLES[gs.stage]
        if not db:
            busy = getattr(self.store, "busy", lambda: False)()
            adv.status = "loading" if busy else "no_data"
            adv.message = (
                "Скачиваю данные OpenDota (только при первом запуске)…"
                if busy
                else (
                    "Нет данных о предметах. Нужен интернет при первом "
                    "запуске."
                )
            )
            return adv

        pop = self.store.get_popularity(gs.hero_id)
        if not pop:
            adv.status = (
                "loading" if self.store.is_loading(gs.hero_id) else "no_data"
            )
            adv.message = (
                "Загружаю сборки для героя…"
                if adv.status == "loading"
                else "Нет данных о сборках героя (нет связи с OpenDota?)."
            )
            return adv

        role = self.role(gs, role_setting)
        counters, enemy_rem, summary = enemies_mod.analyze(
            list(enemy_shorts), self.heroes_by_short, role
        )
        adv.enemy_summary = ", ".join(summary)
        owned = gs.owned
        covered = db.covered(owned)
        if gs.has_shard:
            covered.add("aghanims_shard")
        if gs.has_scepter_buff:
            covered.add("ultimate_scepter")
        adv.slots_main, adv.slots_backpack, adv.slots_stash = (
            len(gs.inventory),
            len(gs.backpack),
            len(gs.stash),
        )
        if len(gs.inventory) + len(gs.stash) > slots_mod.MAIN_SLOTS:
            adv.reminders.append(
                "Тайник не влезет в инвентарь: освободите место перед тем, "
                "как отправлять курьера."
            )

        if gs.stage == "start":
            self._start_bundle(adv, gs, pop, db)
        else:
            self._pick_target(adv, gs, pop, db, owned, covered, counters)

        # ситуативные предметы против врагов, если они не стали основной целью
        for c in counters:
            if (
                c.item == adv.target
                or c.item in covered
                or not db.is_shop_item(c.item)
            ):
                continue
            adv.situational.append((db.dname(c.item), c.reason))
        adv.situational = adv.situational[:2]
        adv.reminders += self._reminders(gs, db, owned, role) + enemy_rem
        return adv

    # ---------- старт ----------
    def _start_bundle(self, adv, gs, pop, db):
        bucket = pop.get(BUCKETS["start"]) or {}
        ranked = sorted(bucket.items(), key=lambda kv: -kv[1])
        budget = gs.gold if gs.gold > 0 else 600
        owned = set(gs.owned)
        spent = 0
        for item_id, _cnt in ranked:
            name = db.name_for_id(item_id)
            if (
                not name
                or name in owned
                or db.is_neutral(name)
                or name.startswith("recipe_")
            ):
                continue
            if (
                name in ("ward_observer", "ward_sentry")
                or db.cost(name) <= 0
                and name != "tango"
            ):
                continue
            cost = db.cost(name)
            if spent + cost > budget:
                continue
            adv.start_bundle.append((db.dname(name), cost))
            spent += cost
            if len(adv.start_bundle) >= 6:
                break
        adv.status = "start"
        adv.target_title = "Стартовая закупка"
        adv.target_cost = spent
        adv.why = (
            "Самые популярные стартовые предметы на этом герое у сильных "
            "игроков: "
            "реген на линию и немного статов. Купите до начала игры."
        )
        if not adv.start_bundle:
            adv.why = "Вы уже закупились на старт. Удачной линии!"
        # что копить дальше
        lane = pop.get(BUCKETS["lane"]) or {}
        nxt = [
            db.name_for_id(i)
            for i, _ in sorted(lane.items(), key=lambda kv: -kv[1])
        ]
        adv.next_items = [
            db.dname(n)
            for n in nxt
            if n
            and db.is_shop_item(n)
            and n not in CONSUMABLES
            and db.cost(n) >= 450
        ][:3]

    # ---------- кандидаты ----------
    def candidate_scores(self, gs, pop, db, owned, covered, counters):
        i = STAGES.index(gs.stage)
        scores: dict[str, float] = {}
        for j, w in ((i, 1.0), (i + 1, 0.6), (i - 1, 0.5)):
            if j < 1 or j >= len(
                STAGES
            ):  # стартовые предметы после 0:00 не советуем
                continue
            bucket = pop.get(BUCKETS[STAGES[j]]) or {}
            mx = max(bucket.values(), default=0)
            if not mx:
                continue
            for item_id, cnt in bucket.items():
                name = db.name_for_id(item_id)
                if name:
                    scores[name] = max(scores.get(name, 0.0), w * cnt / mx)

        owned_set = set(owned)
        owned_t2_boots = owned_set & TIER2_BOOTS

        def allowed(name):
            if (
                not db.is_shop_item(name)
                or name in CONSUMABLES
                or name in covered
            ):
                return False
            # Вторые ботинки не нужны — кроме улучшения уже имеющихся.
            second_boots = (
                name in BOOTS
                and owned_t2_boots
                and name != "travel_boots"
                and not (db.subtree(name) & owned_t2_boots)
            )
            if second_boots:
                return False
            if db.cost(name) < 450 and name not in USEFUL_CHEAP:
                return False
            return not (name == "magic_stick" and gs.stage != "lane")

        scores = {n: s for n, s in scores.items() if allowed(n)}

        # бонус против врагов
        reasons = {}
        for c in counters:
            if c.item in covered or not db.is_shop_item(c.item):
                continue
            if c.item in scores:
                scores[c.item] += 0.5 * c.strength
                reasons[c.item] = c.reason
            elif c.strength >= 0.9 and gs.stage in ("mid", "late"):
                scores[c.item] = 0.6 * c.strength
                reasons[c.item] = c.reason

        # убираем компоненты других сильных кандидатов
        for name in list(scores):
            for other, s in scores.items():
                if (
                    other != name
                    and s >= 0.5 * scores[name]
                    and name in db.subtree(other)
                ):
                    scores[name] = -1
                    break
        scores = {n: s for n, s in scores.items() if s >= 0}

        # нет места: не советуем то, ради чего пришлось бы выкинуть почти такую
        # же ценную вещь
        for name in list(scores):
            if name in reasons:
                continue
            _leaves, used = db.plan(name, owned)
            if slots_mod.is_downgrade(
                gs.inventory, gs.backpack, gs.stash, used, name, db
            ):
                del scores[name]

        # бонус за начатую сборку
        for name in scores:
            cost = db.cost(name)
            if cost > 0:
                done = cost - db.remaining_cost(name, owned)
                if done > 0:
                    # Начатую сборку почти всегда стоит закончить: компонент в
                    # рюкзаке
                    # не даёт и половины пользы готового предмета.
                    scores[name] += 0.25 + 0.5 * done / cost
        return scores, reasons

    def _pick_target(self, adv, gs, pop, db, owned, covered, counters):
        scores, reasons = self.candidate_scores(
            gs, pop, db, owned, covered, counters
        )
        if not scores:
            adv.status = "done"
            adv.target_title = "Основная сборка собрана"
            full = len(gs.inventory) + len(gs.stash) >= slots_mod.MAIN_SLOTS
            adv.why = (
                "Все 6 слотов заняты сильными предметами — новые покупки "
                "сейчас их не улучшат. "
                "Копите золото на выкуп (buyback) и докупайте расходники: "
                "TP, Dust, Smoke."
                if full
                else "Популярные предметы на этом этапе у вас уже есть. "
                "Копите на выкуп "
                "или берите ситуативные предметы против врагов."
            )
            return
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        target = ranked[0][0]
        leaves, used = db.plan(target, owned)
        remaining = sum(db.cost(x) for x in leaves)
        parts = [x for x in leaves if not x.startswith("recipe_")]
        sp = slots_mod.plan_slots(
            gs.inventory,
            gs.backpack,
            gs.stash,
            used,
            target,
            db,
            parts_to_buy=len(parts),
        )
        adv.free_up = [(verb, db.dname(x)) for verb, x in sp.actions]
        adv.free_up_text = slots_mod.describe(sp.actions, db)
        adv.free_up_refund = sp.refund
        cost = db.cost(target)

        adv.status = "ok"
        adv.target = target
        adv.target_title = db.dname(target)
        adv.target_cost = cost
        adv.remaining = remaining
        adv.owned_value = max(0, cost - remaining)
        adv.can_buy_full = gs.gold >= remaining
        adv.can_buy_with_sell = (
            not adv.can_buy_full
            and sp.refund > 0
            and gs.gold + sp.refund >= remaining
        )
        adv.missing = [(db.dname(x), db.cost(x)) for x in leaves]
        adv.buy_now = self._affordable(leaves, db, gs.gold)
        # Части покупаются по одной и до сборки тоже занимают места. Если места
        # нет —
        # они останутся в тайнике и не будут работать: лучше копить на предмет
        # целиком.
        adv.parts_no_room = (
            not adv.can_buy_full
            and bool(adv.buy_now)
            and len(parts) - 1 > sp.free_after
        )
        if adv.parts_no_room:
            adv.buy_now = []
        adv.what = essence(target, db)
        adv.why = self._why_now(
            gs, pop, db, target, reasons.get(target), used, remaining
        )

        target_tree = db.subtree(target) | {target}
        nxt = [
            n
            for n, _ in ranked[1:]
            if n not in target_tree and target not in db.subtree(n)
        ]
        adv.next_items = [db.dname(n) for n in nxt[:3]]

    STAGE_WHEN = {
        "start": "на старте",
        "lane": "на линии",
        "mid": "в мид-гейме",
        "late": "в лейте",
    }
    STAGE_SHORT = {
        "start": "старт",
        "lane": "лайнинг",
        "mid": "мид-гейм",
        "late": "лейт",
    }

    def _pop_rank(self, pop, db, name, stage):
        """(стадия, место) предмета в популярности на герое: сначала текущая
        стадия,
        потом следующая и предыдущая."""
        i = STAGES.index(stage)
        for j in (i, i + 1, i - 1):
            if j < 1 or j >= len(STAGES):
                continue
            bucket = pop.get(BUCKETS[STAGES[j]]) or {}
            ranked = []
            for item_id, _cnt in sorted(bucket.items(), key=lambda kv: -kv[1]):
                n = db.name_for_id(item_id)
                if (
                    n
                    and db.is_shop_item(n)
                    and n not in CONSUMABLES
                    and db.cost(n) >= 450
                ):
                    ranked.append(n)
            if name in ranked:
                return STAGES[j], ranked.index(name) + 1
        return None, None

    def _why_now(self, gs, pop, db, target, enemy_reason, used, remaining):
        hero = self.hero_info(gs).get("localized_name") or "этом герое"
        parts = []
        if enemy_reason:
            parts.append(enemy_reason)
        else:
            st, rank = self._pop_rank(pop, db, target, gs.stage)
            if st == gs.stage:
                parts.append(
                    f"№{rank} по популярности на {hero} "
                    f"{self.STAGE_WHEN[st]} у сильных игроков."
                )
            elif st and STAGES.index(st) > STAGES.index(gs.stage):
                parts.append(
                    f"Его берут на {hero} в следующей стадии "
                    f"({self.STAGE_SHORT[st]}) — "
                    "копите заранее."
                )
            elif st:
                parts.append(
                    f"Обычно его берут на {hero} раньше — вы чуть отстаёте, "
                    "но он всё ещё нужен."
                )
            else:
                parts.append(GENERIC_BY_STAGE.get(gs.stage, ""))
        real_used = [u for u in used if u not in CONSUMABLES]
        if real_used:
            have = ", ".join(dict.fromkeys(db.dname(u) for u in real_used))
            parts.append(
                f"Уже есть {have} — сборку лучше закончить, осталось "
                f"{remaining} золота."
            )
        return " ".join(p for p in parts if p)

    @staticmethod
    def _affordable(leaves, db, gold):
        """Что купить прямо сейчас на имеющееся золото: сначала самые дорогие
        части,
        рецепт — в последнюю очередь (сам по себе он ничего не даёт)."""
        if not leaves:
            return []
        total = sum(db.cost(x) for x in leaves)
        if gold >= total:
            return [(db.dname(x), db.cost(x)) for x in leaves]
        parts = sorted(
            (x for x in leaves if not x.startswith("recipe_")),
            key=lambda x: -db.cost(x),
        )
        picked, left = [], gold
        for x in parts:
            c = db.cost(x)
            if c <= left:
                picked.append((db.dname(x), c))
                left -= c
        return picked

    # ---------- напоминания ----------
    def _reminders(self, gs, db, owned, role):
        rem: list[str] = []
        if gs.stage == "start":
            return rem
        if not gs.has_tp and gs.clock > 60:
            rem.append(
                "Нет свитка телепорта (TP) — купите, "
                f"{db.cost('tpscroll') or 100} золота."
            )
        if gs.clock > 300 and not (set(owned) & BOOTS):
            rem.append(
                "Нет ботинок — скорость передвижения сейчас важнее всего."
            )
        if not gs.alive and gs.gold >= 500:
            rem.append("Вы мертвы — самое время закупиться.")
        if gs.stage == "late" and role == "core" and gs.buyback_cost:
            if gs.buyback_cooldown > 0:
                rem.append(
                    f"Выкуп перезаряжается ещё {gs.buyback_cooldown} с — не "
                    "рискуйте."
                )
            elif gs.gold < gs.buyback_cost:
                rem.append(f"Копите на выкуп: нужно {gs.buyback_cost} золота.")
        if (
            role == "support"
            and gs.ward_cooldown == 0
            and gs.clock > 0
            and "ward_observer" not in owned
            and "ward_dispenser" not in owned
        ):
            rem.append(
                "В лавке есть Observer Ward — купите и поставьте: обзор "
                "спасает от засад."
            )
        return rem
