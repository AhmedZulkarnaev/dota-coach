"""Симулятор матча: отправляет программе такие же данные, как Dota 2 через GSI.

Нужен, чтобы проверить окно подсказок без запуска игры.
Запустите Dota Coach, затем в другом окне:

    python tools/simulate_gsi.py            (матч на Урсе, 1 сек = 30 сек игры)
    python tools/simulate_gsi.py --speed 60
"""

import argparse
import json
import pathlib
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (время, что купили к этому моменту) — упрощённая сборка Урсы
PURCHASES = [
    (-80, ["tango", "quelling_blade", "branches", "branches", "slippers", "circlet"]),
    (150, ["tango", "quelling_blade", "branches", "branches", "wraith_band"]),
    (240, ["quelling_blade", "branches", "branches", "wraith_band", "magic_stick"]),
    (330, ["quelling_blade", "wraith_band", "magic_wand", "boots"]),
    (500, ["quelling_blade", "wraith_band", "magic_wand", "power_treads"]),
    (720, ["quelling_blade", "wraith_band", "magic_wand", "power_treads", "blades_of_attack"]),
    (900, ["wraith_band", "magic_wand", "power_treads", "ogre_axe"]),
    (1140, ["wraith_band", "magic_wand", "power_treads", "black_king_bar"]),
    (1500, ["wraith_band", "magic_wand", "power_treads", "black_king_bar", "blink"]),
    (1900, ["magic_wand", "power_treads", "black_king_bar", "blink", "basher"]),
    (2400, ["power_treads", "black_king_bar", "blink", "abyssal_blade", "magic_wand", "skadi",
            "quelling_blade", "branches", "wraith_band"]),   # забит и рюкзак — проверка советов «нет места»
]

URSA_SKILLS = ["ursa_earthshock", "ursa_overpower", "ursa_fury_swipes", "ursa_enrage"]


def abilities_at(clock, level):
    """Уровни способностей и перезарядки, похожие на настоящие."""
    res = {}
    for i, name in enumerate(URSA_SKILLS):
        if name == "ursa_enrage":
            lvl = min(3, max(0, (level - 1) // 5))
        else:
            lvl = min(4, (level + (2 - i)) // 3)
        cd = 0 if (int(clock) // 30 + i) % 3 else 6 + i * 3
        res[f"ability{i}"] = {"name": name, "level": lvl, "can_cast": lvl > 0 and cd == 0 and name != "ursa_fury_swipes",
                              "passive": name == "ursa_fury_swipes", "ability_active": True,
                              "cooldown": cd if lvl else 0, "ultimate": name == "ursa_enrage"}
    res["ability4"] = {"name": "special_bonus_unique_ursa", "level": 0, "can_cast": False, "passive": True,
                       "cooldown": 0, "ultimate": False}
    return res


# сколько золота «потрачено» к каждому моменту (грубо, для правдоподобного остатка)
SPENT = {-80: 490, 150: 490, 240: 690, 330: 1590, 500: 2490, 720: 2940, 900: 3490,
         1140: 6540, 1500: 8790, 1900: 11665, 2400: 20840}


def load_settings():
    p = ROOT / "settings.json"
    if not p.exists():
        raise SystemExit("Сначала запустите Dota Coach (он создаст settings.json).")
    return json.loads(p.read_text(encoding="utf-8"))


def items_at(clock):
    current = []
    for t, items in PURCHASES:
        if clock >= t:
            current = items
    return current


def build_payload(clock, gold, token):
    state = "DOTA_GAMERULES_STATE_PRE_GAME" if clock < 0 else "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"
    if clock > 2700:
        state = "DOTA_GAMERULES_STATE_POST_GAME"
    inv = items_at(clock)
    slots = {f"slot{i}": {"name": "empty"} for i in range(9)}
    for i, it in enumerate(inv[:9]):
        slots[f"slot{i}"] = {"name": "item_" + it}
    slots["teleport0"] = {"name": "item_tpscroll" if clock < 400 or clock > 700 else "empty"}
    minutes = max(0, clock) / 60
    level = min(30, 1 + int(minutes / 1.4))
    hp = 22 if (int(clock) // 60) % 4 == 3 else 85     # раз в 4 минуты — неудачная драка
    mana = 15 if (int(clock) // 60) % 5 == 2 else 70
    return {
        "provider": {"name": "Dota 2", "appid": 570, "version": 47},
        "map": {"name": "start", "matchid": "9999000111", "game_time": clock + 90, "clock_time": clock,
                "game_state": state, "paused": False, "daytime": True},
        "player": {"steamid": "0", "name": "Тест", "activity": "playing",
                   "kills": int(minutes / 4), "deaths": int(minutes / 7), "assists": int(minutes / 3),
                   "last_hits": int(minutes * 6), "denies": int(minutes), "gold": max(0, gold),
                   "gold_reliable": max(0, gold) // 3, "gpm": 520, "xpm": 600, "team_name": "radiant"},
        "hero": {"id": 70, "name": "npc_dota_hero_ursa", "level": level,
                 "alive": True, "respawn_seconds": 0, "buyback_cost": 200 + int(minutes * 60),
                 "health_percent": hp, "mana_percent": mana},
        "abilities": abilities_at(clock, level),
        "items": slots,
        "auth": {"token": token},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=30, help="игровых секунд за 1 реальную")
    args = ap.parse_args()
    s = load_settings()
    url = f"http://127.0.0.1:{s['port']}/"
    clock, step = -90, args.speed / 2
    print(f"Отправляю данные на {url}. Ctrl+C — остановить.")
    while clock <= 2760:
        income = 600 + max(0, clock) * 520 / 60
        last = max([t for t in SPENT if t <= clock], default=None)
        gold = int(income - (SPENT[last] if last is not None else 0))
        data = json.dumps(build_payload(int(clock), gold, s["token"])).encode("utf-8")
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=data,
                                   headers={"Content-Type": "application/json"}), timeout=3)
        except OSError as e:
            print("Не удалось отправить (программа запущена?):", e)
        print(f"\rвремя {int(clock) // 60:>3}:{abs(int(clock)) % 60:02d}  золото {gold:>6}", end="")
        time.sleep(0.5)
        clock += step
    print("\nМатч окончен.")


if __name__ == "__main__":
    main()
