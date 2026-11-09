"""База предметов: стоимость, компоненты, сборка из частей.

Источник — /api/constants/items OpenDota (это зеркало dotaconstants, данные из файлов игры).
Ключи словаря — имена предметов без префикса "item_" (например "black_king_bar").
"""

from collections import Counter

# Расходники: их не советуем как «следующий предмет», о важных напоминаем отдельно.
CONSUMABLES = {
    "tango", "tango_single", "flask", "clarity", "faerie_fire", "enchanted_mango",
    "ward_observer", "ward_sentry", "ward_dispenser", "dust", "smoke_of_deceit",
    "tpscroll", "blood_grenade", "famango", "great_famango", "greater_famango",
    "bottle", "tome_of_knowledge", "cheese", "aegis", "refresher_shard",
}

# Предметы, которые нельзя купить в лавке (дроп Рошана, события и т.п.).
NOT_IN_SHOP_MARKERS = ("roshan", "aegis", "cheese", "refresher_shard", "river_painter",
                       "mutation", "pocket", "winter", "halloween", "greevil", "present")

BOOTS = {
    "boots", "power_treads", "phase_boots", "arcane_boots", "tranquil_boots",
    "travel_boots", "travel_boots_2", "guardian_greaves", "boots_of_bearing",
}
TIER2_BOOTS = BOOTS - {"boots"}

# Дешёвые предметы, которые всё же имеет смысл советовать после старта.
USEFUL_CHEAP = {"magic_stick", "magic_wand", "boots", "wind_lace", "infused_raindrop",
                "orb_of_venom", "blight_stone", "quelling_blade"}


class ItemDB:
    def __init__(self, items_const):
        self.items = {}
        for key, data in (items_const or {}).items():
            if not isinstance(data, dict):
                continue
            name = key[5:] if key.startswith("item_") else key
            self.items[name] = data
        self.by_id = {}
        for name, data in self.items.items():
            item_id = data.get("id")
            if isinstance(item_id, int) and not name.startswith("recipe_"):
                self.by_id[item_id] = name
        self._closure_cache = {}

    def __bool__(self):
        return bool(self.items)

    # --- базовые свойства ---
    def name_for_id(self, item_id):
        try:
            return self.by_id.get(int(item_id))
        except (TypeError, ValueError):
            return None

    def exists(self, name):
        return name in self.items

    def cost(self, name):
        if name.startswith("recipe_"):
            return self.recipe_cost(name[7:])
        c = self.items.get(name, {}).get("cost")
        return int(c) if isinstance(c, (int, float)) else 0

    def dname(self, name):
        if name.startswith("recipe_"):
            return "Рецепт " + self.dname(name[7:])
        data = self.items.get(name)
        if data and data.get("dname"):
            return data["dname"]
        return name.replace("_", " ").title()

    def components(self, name):
        comps = self.items.get(name, {}).get("components") or []
        return [c[5:] if c.startswith("item_") else c for c in comps if isinstance(c, str)]

    def recipe_cost(self, name):
        total = self.cost(name)
        parts = sum(self.cost(c) for c in self.components(name))
        return max(0, total - parts) if self.components(name) else 0

    def is_neutral(self, name):
        data = self.items.get(name, {})
        return data.get("tier") is not None or data.get("qual") == "neutral" \
            or bool(data.get("is_neutral_item"))

    def is_shop_item(self, name):
        if name not in self.items or name.startswith("recipe_"):
            return False
        if self.cost(name) <= 0 or self.is_neutral(name):
            return False
        return not any(m in name for m in NOT_IN_SHOP_MARKERS)

    # --- сборка ---
    def subtree(self, name):
        """Все предметы, входящие в name на любой глубине (без самого name)."""
        if name in self._closure_cache:
            return self._closure_cache[name]
        result, stack, seen = set(), list(self.components(name)), set()
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            result.add(c)
            stack.extend(self.components(c))
        self._closure_cache[name] = result
        return result

    def covered(self, owned):
        """Купленные предметы и всё, из чего они собраны: это уже не нужно советовать."""
        cov = set()
        for o in owned:
            cov.add(o)
            cov |= self.subtree(o)
        return cov

    def plan(self, target, owned):
        """Что докупить, чтобы собрать target, с учётом имеющихся компонентов.

        Возвращает (leaves, used): leaves — список имён для покупки (рецепт как "recipe_x"),
        used — какие из имеющихся предметов уйдут в сборку.
        """
        pool = Counter(owned)
        leaves, used = [], []

        def need(item, top=False):
            if not top and pool[item] > 0:
                pool[item] -= 1
                used.append(item)
                return
            comps = self.components(item)
            if not comps:
                leaves.append(item)
                return
            for c in comps:
                need(c)
            if self.recipe_cost(item) > 0:
                leaves.append("recipe_" + item)

        need(target, top=True)
        return leaves, used

    def remaining_cost(self, target, owned):
        leaves, _ = self.plan(target, owned)
        return sum(self.cost(x) for x in leaves)
