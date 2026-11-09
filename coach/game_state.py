"""Разбор JSON, который присылает Dota 2 через Game State Integration (режим игрока)."""

from dataclasses import dataclass, field

PRE_GAME_STATES = {
    "DOTA_GAMERULES_STATE_INIT",
    "DOTA_GAMERULES_STATE_WAIT_FOR_PLAYERS_TO_LOAD",
    "DOTA_GAMERULES_STATE_HERO_SELECTION",
    "DOTA_GAMERULES_STATE_STRATEGY_TIME",
    "DOTA_GAMERULES_STATE_TEAM_SHOWCASE",
    "DOTA_GAMERULES_STATE_WAIT_FOR_MAP_TO_LOAD",
    "DOTA_GAMERULES_STATE_PRE_GAME",
}
IN_GAME = "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"
POST_GAME = "DOTA_GAMERULES_STATE_POST_GAME"

STAGES = ["start", "lane", "mid", "late"]
STAGE_TITLES = {
    "start": "Старт",
    "lane": "Лайнинг (0–10 мин)",
    "mid": "Мид-гейм (10–30 мин)",
    "late": "Лейт (30+ мин)",
}


@dataclass
class GameState:
    valid: bool = False          # пришли ли вообще данные матча
    spectating: bool = False     # режим зрителя/реплея — не поддерживаем
    match_id: str = ""
    game_state: str = ""
    clock: int = 0               # игровые часы, сек (до горна отрицательные)
    paused: bool = False
    hero_id: int = 0
    hero_npc: str = ""           # "npc_dota_hero_ursa"
    hero_level: int = 0
    alive: bool = True
    respawn_seconds: int = 0
    buyback_cost: int = 0
    gold: int = 0
    gold_reliable: int = 0
    gpm: int = 0
    xpm: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    denies: int = 0
    team: str = ""
    inventory: list = field(default_factory=list)   # слоты 0–5
    backpack: list = field(default_factory=list)    # слоты 6–8
    stash: list = field(default_factory=list)
    has_tp: bool = False
    neutral: str = ""
    hp_pct: int = 100
    mana_pct: int = 100
    abilities: list = field(default_factory=list)   # [{name, level, can_cast, passive, cooldown, ultimate}]
    has_shard: bool = False      # Aghanim's Shard съедается при покупке, в слотах его нет
    has_scepter_buff: bool = False  # Aghanim's Blessing / съеденный Scepter

    @property
    def owned(self):
        """Всё купленное: инвентарь + рюкзак + тайник (курьер GSI не показывает)."""
        return self.inventory + self.backpack + self.stash

    @property
    def stage(self):
        if self.game_state in PRE_GAME_STATES or self.clock < 0:
            return "start"
        if self.clock < 600:
            return "lane"
        if self.clock < 1800:
            return "mid"
        return "late"

    @property
    def in_match(self):
        return self.game_state in PRE_GAME_STATES or self.game_state in (IN_GAME, POST_GAME)

    @property
    def clock_str(self):
        sign = "-" if self.clock < 0 else ""
        t = abs(self.clock)
        return f"{sign}{t // 60}:{t % 60:02d}"


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _item_name(slot):
    if not isinstance(slot, dict):
        return ""
    name = slot.get("name") or ""
    if not name or name == "empty":
        return ""
    return name[5:] if name.startswith("item_") else name


def parse(payload):
    gs = GameState()
    if not isinstance(payload, dict):
        return gs
    m = payload.get("map") or {}
    player = payload.get("player") or {}
    hero = payload.get("hero") or {}
    items = payload.get("items") or {}

    # В режиме зрителя player/hero вложены по командам: {"team2": {"player0": {...}}}
    if isinstance(player, dict) and any(k in ("team2", "team3") and isinstance(v, dict)
                                        for k, v in player.items()):
        gs.spectating = True
        return gs
    if not m:
        return gs

    gs.valid = True
    gs.match_id = str(m.get("matchid") or "")
    gs.game_state = m.get("game_state") or ""
    gs.clock = _int(m.get("clock_time"))
    gs.paused = bool(m.get("paused"))

    gs.hero_id = _int(hero.get("id"))
    gs.hero_npc = hero.get("name") or ""
    gs.hero_level = _int(hero.get("level"))
    gs.alive = bool(hero.get("alive", True))
    gs.respawn_seconds = _int(hero.get("respawn_seconds"))
    gs.buyback_cost = _int(hero.get("buyback_cost"))
    gs.has_shard = bool(hero.get("aghanims_shard"))
    gs.has_scepter_buff = bool(hero.get("aghanims_scepter"))

    gs.hp_pct = _int(hero.get("health_percent"), 100)
    gs.mana_pct = _int(hero.get("mana_percent"), 100)
    abilities = payload.get("abilities") or {}
    for key in sorted(abilities, key=lambda k: _int(k.replace("ability", ""), 99)):
        a = abilities.get(key)
        if not isinstance(a, dict):
            continue
        name = a.get("name") or ""
        if not name or name.startswith(("special_bonus", "generic_", "plus_", "ability_")):
            continue
        gs.abilities.append({"name": name, "level": _int(a.get("level")),
                             "can_cast": bool(a.get("can_cast")), "passive": bool(a.get("passive")),
                             "cooldown": _int(a.get("cooldown")), "ultimate": bool(a.get("ultimate"))})

    gs.gold = _int(player.get("gold"))
    gs.gold_reliable = _int(player.get("gold_reliable"))
    gs.gpm = _int(player.get("gpm"))
    gs.xpm = _int(player.get("xpm"))
    gs.kills = _int(player.get("kills"))
    gs.deaths = _int(player.get("deaths"))
    gs.assists = _int(player.get("assists"))
    gs.last_hits = _int(player.get("last_hits"))
    gs.denies = _int(player.get("denies"))
    gs.team = player.get("team_name") or ""

    for i in range(9):
        n = _item_name(items.get(f"slot{i}"))
        if n:
            (gs.inventory if i < 6 else gs.backpack).append(n)
    for i in range(6):
        n = _item_name(items.get(f"stash{i}"))
        if n:
            gs.stash.append(n)
    tp = _item_name(items.get("teleport0"))
    gs.has_tp = tp == "tpscroll" or "tpscroll" in gs.owned
    gs.neutral = _item_name(items.get("neutral0"))
    # TP и нейтралку в список купленного не включаем — они живут в своих слотах.
    gs.inventory = [x for x in gs.inventory if x != "tpscroll"]
    return gs
