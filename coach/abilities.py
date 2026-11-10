"""Подсказки «когда использовать способности».

Откуда берутся:
  1. Список способностей, их уровень, перезарядка и готовность — из GSI (вашего
     героя видно).
  2. Короткий совет:
     • для популярных героев — написан вручную ниже (TIPS);
     • для остальных — собирается автоматически по описанию способности из
       OpenDota
       (/constants/abilities): ищем в описании оглушение, замедление, урон,
       побег и т.п.
  3. «Живые» подсказки по текущей ситуации: ульт готов, мало здоровья — нажмите
     защиту,
     мало маны — не тратьте способности на крипов.
"""

import re
from typing import Any

from .game_state import GameState

Abilities = dict[str, Any] | None

# Ручные советы: ключ — внутреннее имя способности, как его присылает GSI.
# (теги нужны для живых подсказок: defend/escape — спасают при низком здоровье)
TIPS = {
    # Ursa
    "ursa_earthshock": (
        "Прыгайте прямо на врага: замедление не даст ему убежать, пока вы "
        "бьёте.",
        {"slow"},
    ),
    "ursa_overpower": (
        "Включайте перед атакой героя или Рошана — следующие удары будут "
        "очень быстрыми.",
        {"buff"},
    ),
    "ursa_fury_swipes": (
        "Пассивная: каждый удар по одной цели бьёт сильнее. Не "
        "переключайтесь между целями.",
        {"passive"},
    ),
    "ursa_enrage": (
        "Резко снижает получаемый урон и снимает часть эффектов. Жмите, "
        "когда вас начали бить.",
        {"defend", "ult"},
    ),
    # Juggernaut
    "juggernaut_blade_fury": (
        "Вращение с иммунитетом к магии: защита от контроля, побег или урон "
        "по линии крипов.",
        {"defend", "escape"},
    ),
    "juggernaut_healing_ward": (
        "Ставьте за спиной в драке или после размена — лечит союзников рядом.",
        {"heal"},
    ),
    "juggernaut_blade_dance": (
        "Пассивная: шанс критического удара.",
        {"passive"},
    ),
    "juggernaut_omni_slash": (
        "Используйте, когда рядом с целью мало крипов и героев — иначе удары "
        "разлетятся.",
        {"ult"},
    ),
    # Phantom Assassin
    "phantom_assassin_stifling_dagger": (
        "Кинжал с замедлением: добивайте крипов издалека и догоняйте "
        "убегающих.",
        {"nuke", "slow"},
    ),
    "phantom_assassin_phantom_strike": (
        "Мгновенный прыжок к цели: догнать врага или сбежать к своему крипу.",
        {"escape"},
    ),
    "phantom_assassin_blur": (
        "Уклонение от атак. Держите для отхода, если есть активная часть.",
        {"defend", "passive"},
    ),
    "phantom_assassin_coup_de_grace": (
        "Пассивная: шанс огромного критического удара.",
        {"passive", "ult"},
    ),
    # Wraith King
    "skeleton_king_hellfire_blast": (
        "Оглушение: используйте, чтобы начать драку или не дать врагу уйти.",
        {"disable"},
    ),
    "skeleton_king_vampiric_spirit": (
        "Вампиризм и призыв скелетов: включайте в драке и на фарме.",
        {"buff"},
    ),
    "skeleton_king_vampiric_aura": (
        "Пассивный вампиризм: лечит вас ударами.",
        {"passive"},
    ),
    "skeleton_king_mortal_strike": (
        "Пассивная: шанс критического удара.",
        {"passive"},
    ),
    "skeleton_king_reincarnation": (
        "После смерти вы воскреснете на месте — следите за маной, чтобы ульт "
        "сработал.",
        {"ult", "passive"},
    ),
    # Sniper
    "sniper_shrapnel": (
        "Ставьте на путь врага или на крипов — замедляет и наносит урон по "
        "площади.",
        {"slow", "nuke"},
    ),
    "sniper_headshot": (
        "Пассивная: атаки иногда отталкивают и замедляют.",
        {"passive"},
    ),
    "sniper_take_aim": (
        "Увеличивает дальность — бейте из-за спин союзников.",
        {"buff"},
    ),
    "sniper_assassinate": (
        "Добивание издалека врага с низким здоровьем.",
        {"nuke", "ult"},
    ),
    # Drow Ranger
    "drow_ranger_frost_arrows": (
        "Включите автокаст — каждая стрела замедляет.",
        {"slow"},
    ),
    "drow_ranger_wave_of_silence": (
        "Отталкивает и заставляет молчать: отбросьте врага, который прыгнул "
        "на вас.",
        {"disable", "escape"},
    ),
    "drow_ranger_multishot": (
        "Залп стрел по площади: фарм пачек и урон в драке.",
        {"nuke"},
    ),
    "drow_ranger_marksmanship": (
        "Пассивная: сильный бонус к ловкости, пока враги не рядом.",
        {"passive", "ult"},
    ),
    # Lion
    "lion_impale": (
        "Шипы оглушают всех на линии: цельтесь через нескольких врагов.",
        {"disable"},
    ),
    "lion_voodoo": (
        "Превращение в лягушку: выключите самого опасного врага в начале "
        "драки.",
        {"disable"},
    ),
    "lion_mana_drain": (
        "Тянет ману. Можно снять с себя иллюзии и щиты врагов. Пополняйте "
        "ману между драками.",
        {"mana"},
    ),
    "lion_finger_of_death": (
        "Огромный урон по одной цели — добивайте, а не начинайте им драку.",
        {"nuke", "ult"},
    ),
    # Crystal Maiden
    "crystal_maiden_crystal_nova": (
        "Замедление по площади: помогает догнать или убежать.",
        {"slow", "nuke"},
    ),
    "crystal_maiden_frostbite": (
        "Сковывает врага на месте: ловите убегающих или выключайте "
        "атакующего керри.",
        {"disable"},
    ),
    "crystal_maiden_brilliance_aura": (
        "Пассивная: мана для команды.",
        {"passive"},
    ),
    "crystal_maiden_freezing_field": (
        "Встаньте за союзниками в безопасном месте: вас легко прервать.",
        {"ult"},
    ),
    # Pudge
    "pudge_meat_hook": (
        "Крюк: цельтесь туда, где враг будет, и из тумана войны. Не бросайте "
        "через крипов.",
        {"disable"},
    ),
    "pudge_rot": (
        "Включайте рядом с врагами — урон и замедление. Выключайте, когда "
        "отходите.",
        {"slow", "nuke"},
    ),
    "pudge_dismember": (
        "Удерживает цель — используйте сразу после крюка.",
        {"disable", "ult"},
    ),
    # Axe
    "axe_berserkers_call": (
        "Заставляет врагов бить вас — прыгайте в толпу, но сначала проверьте "
        "своё здоровье.",
        {"disable"},
    ),
    "axe_battle_hunger": (
        "Повесьте на врага на линии — он теряет здоровье, пока не убьёт "
        "крипа.",
        {"nuke"},
    ),
    "axe_counter_helix": ("Пассивная: крутится, когда вас бьют.", {"passive"}),
    "axe_culling_blade": (
        "Мгновенно добивает врага с низким здоровьем — следите за полоской "
        "HP врага.",
        {"nuke", "ult"},
    ),
    # Sven
    "sven_storm_bolt": (
        "Оглушение по площади: начните драку или остановите убегающего.",
        {"disable"},
    ),
    "sven_great_cleave": (
        "Пассивная: урон по всем врагам перед вами.",
        {"passive"},
    ),
    "sven_warcry": (
        "Скорость и броня команде: жмите в начале драки или для отхода.",
        {"buff", "defend"},
    ),
    "sven_gods_strength": (
        "Огромный урон: включайте прямо перед драками и для быстрого фарма.",
        {"buff", "ult"},
    ),
    # Lina
    "lina_dragon_slave": (
        "Урон по линии: бейте врага на линии и фармите крипов.",
        {"nuke"},
    ),
    "lina_light_strike_array": (
        "Оглушение с задержкой: цельтесь в стоящего или уже оглушённого "
        "врага.",
        {"disable", "nuke"},
    ),
    "lina_fiery_soul": (
        "Пассивная: каждое заклинание ускоряет атаки.",
        {"passive"},
    ),
    "lina_laguna_blade": (
        "Огромный урон по одной цели — добивайте врага.",
        {"nuke", "ult"},
    ),
    # Zeus
    "zuus_arc_lightning": (
        "Дешёвый урон с перескоком: фарм и размены.",
        {"nuke"},
    ),
    "zuus_lightning_bolt": (
        "Урон и короткое оглушение, показывает невидимых рядом.",
        {"nuke", "disable"},
    ),
    "zuus_heavenly_jump": (
        "Прыжок назад с замедлением врагов — главный способ сбежать.",
        {"escape"},
    ),
    "zuus_thundergods_wrath": (
        "Бьёт всех врагов на карте: добивайте убегающих с низким здоровьем.",
        {"nuke", "ult"},
    ),
    # Witch Doctor
    "witch_doctor_paralyzing_cask": (
        "Отскакивающее оглушение: лучше всего, когда враги стоят рядом с "
        "крипами.",
        {"disable"},
    ),
    "witch_doctor_voodoo_restoration": (
        "Лечит союзников вокруг, тратит ману. Выключайте, когда не нужно.",
        {"heal"},
    ),
    "witch_doctor_maledict": (
        "Проклятие по площади: урон растёт от уже полученного. Хорошо в "
        "начале драки.",
        {"nuke"},
    ),
    "witch_doctor_death_ward": (
        "Стойте в безопасности за союзниками — вас легко прервать.",
        {"ult"},
    ),
    # Dragon Knight
    "dragon_knight_breathe_fire": (
        "Урон по конусу и меньше урона от врагов: фарм и драки.",
        {"nuke"},
    ),
    "dragon_knight_dragon_tail": (
        "Оглушение: прерывает заклинания и держит цель.",
        {"disable"},
    ),
    "dragon_knight_dragon_blood": (
        "Пассивная: регенерация и броня.",
        {"passive"},
    ),
    "dragon_knight_elder_dragon_form": (
        "Включайте для драк и снятия башен.",
        {"buff", "ult"},
    ),
    # Bristleback
    "bristleback_viscous_nasal_goo": (
        "Замедляет и снимает броню: не дайте врагу уйти.",
        {"slow"},
    ),
    "bristleback_quill_spray": (
        "Главный урон: жмите часто, урон растёт с каждым попаданием.",
        {"nuke"},
    ),
    "bristleback_bristleback": (
        "Поворачивайтесь к врагам спиной — урон сзади сильно снижается.",
        {"defend", "passive"},
    ),
    "bristleback_warpath": (
        "Пассивная: каждое заклинание ускоряет вас и усиливает атаки.",
        {"passive", "ult"},
    ),
    # Earthshaker
    "earthshaker_fissure": (
        "Стена и оглушение: перекройте врагу путь отхода.",
        {"disable"},
    ),
    "earthshaker_enchant_totem": (
        "Сильный удар; с Aghanim's Scepter — прыжок в толпу.",
        {"buff"},
    ),
    "earthshaker_aftershock": (
        "Пассивная: каждое заклинание оглушает врагов вокруг.",
        {"passive"},
    ),
    "earthshaker_echo_slam": (
        "Лучше всего в толпе врагов: чем больше целей, тем больше урон. "
        "Хорошо с Blink Dagger.",
        {"nuke", "ult"},
    ),
    # Faceless Void
    "faceless_void_time_walk": (
        "Рывок, который отменяет недавно полученный урон: для побега и "
        "нападения.",
        {"escape", "defend"},
    ),
    "faceless_void_time_dilation": (
        "Замораживает перезарядки врагов вокруг — жмите в начале драки.",
        {"disable"},
    ),
    "faceless_void_time_lock": (
        "Пассивная: шанс оглушить ударом.",
        {"passive"},
    ),
    "faceless_void_chronosphere": (
        "Останавливает всех внутри (и союзников!). Ловите как можно больше "
        "врагов.",
        {"disable", "ult"},
    ),
    # Anti-Mage
    "antimage_mana_break": (
        "Пассивная: атаки сжигают ману врага.",
        {"passive"},
    ),
    "antimage_blink": (
        "Короткий телепорт: побег и быстрый переход между лагерями.",
        {"escape"},
    ),
    "antimage_counterspell": (
        "Отражает направленное заклинание: жмите, когда в вас летит "
        "способность.",
        {"defend"},
    ),
    "antimage_mana_void": (
        "Урон тем больше, чем меньше маны у цели — используйте после атак.",
        {"nuke", "ult"},
    ),
    # Shadow Shaman
    "shadow_shaman_ether_shock": (
        "Урон по конусу: размены на линии и добивание.",
        {"nuke"},
    ),
    "shadow_shaman_voodoo": (
        "Превращение в животное: выключите опасного врага.",
        {"disable"},
    ),
    "shadow_shaman_shackles": (
        "Удерживает цель, но и вас тоже — стойте в безопасности.",
        {"disable"},
    ),
    "shadow_shaman_mass_serpent_ward": (
        "Змеи сносят башни и окружают героев — ставьте вокруг врага.",
        {"ult"},
    ),
    # Legion Commander
    "legion_commander_overwhelming_odds": (
        "Урон по площади: фарм пачек и ускорение для догона.",
        {"nuke"},
    ),
    "legion_commander_press_the_attack": (
        "Лечение и скорость атаки: снимает негативные эффекты.",
        {"heal", "defend"},
    ),
    "legion_commander_moment_of_courage": (
        "Пассивная: иногда отвечает ударом с вампиризмом.",
        {"passive"},
    ),
    "legion_commander_duel": (
        "Начинайте дуэль, только если уверены, что победите: проверьте "
        "здоровье врага.",
        {"disable", "ult"},
    ),
    # Viper
    "viper_poison_attack": (
        "Включите автокаст на героев — замедляет и снижает сопротивление "
        "магии.",
        {"slow"},
    ),
    "viper_nethertoxin": (
        "Ставьте под врага: урон и отключение пассивных способностей.",
        {"nuke"},
    ),
    "viper_corrosive_skin": (
        "Пассивная: вредит тем, кто вас бьёт.",
        {"passive"},
    ),
    "viper_viper_strike": (
        "Сильное замедление и урон по одной цели: не дайте ей уйти.",
        {"slow", "ult"},
    ),
    # Ogre Magi
    "ogre_magi_fireblast": (
        "Оглушение: используйте сразу, когда враг подходит.",
        {"disable"},
    ),
    "ogre_magi_ignite": ("Урон и замедление по цели.", {"slow", "nuke"}),
    "ogre_magi_bloodlust": (
        "Повесьте на союзного керри перед драками и фармом.",
        {"buff"},
    ),
    "ogre_magi_multicast": (
        "Пассивная: иногда повторяет заклинание.",
        {"passive", "ult"},
    ),
}

GENERIC = {
    "disable": (
        "Контроль: ловите врага или сбивайте его заклинание. Лучше, когда "
        "союзники рядом и успеют убить."
    ),
    "slow": (
        "Замедление: применяйте, когда враг убегает или нужно его догнать."
    ),
    "nuke": (
        "Урон: добивайте героев с низким здоровьем; на линии — когда враг "
        "подходит к крипам. Следите за маной."
    ),
    "escape": (
        "Перемещение: держите для побега, если вы в опасности; иначе — чтобы "
        "догнать."
    ),
    "defend": (
        "Защита: нажимайте, когда вас начали бить или контролить, а не "
        "заранее."
    ),
    "heal": "Лечение: используйте после размена, а не на полном здоровье.",
    "buff": "Усиление: включайте прямо перед драками или фармом.",
    "summon": (
        "Призыв: используйте для фарма и давления, отправляйте юнитов вперёд "
        "вместо себя."
    ),
    "passive": "Пассивная — работает сама.",
}
TAG_ORDER = [
    "disable",
    "escape",
    "defend",
    "heal",
    "nuke",
    "slow",
    "summon",
    "buff",
]

KEYWORDS = [
    (
        "disable",
        r"\bstun|silence|hex|\broot|ensnare|sleep|taunt|fear|cyclone|banish|"
        r"disarm",
    ),
    (
        "escape",
        r"invisib|teleport|blink|leap|jump|dash|moves? "
        r"(?:quickly|rapidly)|rushes|charges",
    ),
    (
        "defend",
        r"invulnerab|spell immunity|debuff immunity|damage "
        r"reduction|reduces? (?:all )?incoming damage|dispel|shield|barrier",
    ),
    ("heal", r"\bheal|restores? health|regenerat"),
    ("summon", r"summon|spawns?|illusion|ward|creates? .* unit"),
    ("slow", r"\bslow"),
    (
        "buff",
        r"bonus attack speed|bonus damage|increases? (?:your|his|her|its) "
        r"attack",
    ),
    ("nuke", r"damage"),
]


def _behavior(data: dict[str, Any]) -> str:
    b = data.get("behavior") or ""
    return " ".join(b) if isinstance(b, list) else str(b)


def classify(name: str, abilities_const: Abilities) -> set[str]:
    """Теги способности: из ручного списка или по описанию OpenDota."""
    if name in TIPS:
        return TIPS[name][1]
    data = (abilities_const or {}).get(name) or {}
    if "Passive" in _behavior(data):
        return {"passive"}
    desc = (data.get("desc") or "").lower()
    tags = {tag for tag, rx in KEYWORDS if re.search(rx, desc)}
    return tags or {"nuke"}


def tip_for(
    name: str, abilities_const: Abilities, ultimate: bool = False
) -> str:
    if name in TIPS:
        return TIPS[name][0]
    tags = classify(name, abilities_const)
    if "passive" in tags:
        return GENERIC["passive"]
    main = next((t for t in TAG_ORDER if t in tags), "nuke")
    text = GENERIC[main]
    if ultimate:
        text = (
            "Ульт — берегите для командной драки или верного убийства. " + text
        )
    return text


def title_for(name: str, abilities_const: Abilities) -> str:
    data = (abilities_const or {}).get(name) or {}
    return (
        data.get("dname") or name.split("_", 1)[-1].replace("_", " ").title()
    )


def ability_advice(
    gs: GameState, abilities_const: Abilities
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Возвращает (live, lines).

    live  — срочные подсказки по ситуации (их видно первыми);
    lines — [(название, совет, состояние)] для каждой способности героя.
    """
    live: list[str] = []
    lines: list[tuple[str, str, str]] = []
    abil = [a for a in gs.abilities if a.get("name")]
    if not abil:
        return live, lines
    learned = [a for a in abil if a.get("level", 0) > 0] or abil

    for a in learned:
        name = a["name"]
        title = title_for(name, abilities_const)
        tags = classify(name, abilities_const)
        if (
            a.get("passive")
            or "passive" in tags
            and not ({"defend", "buff"} & tags)
        ):
            state = "пассивная"
        elif a.get("level", 0) == 0:
            state = "не изучена"
        elif a.get("cooldown", 0) > 0:
            state = f"перезарядка {a['cooldown']} с"
        elif a.get("can_cast"):
            state = "готова"
        else:
            state = "нет маны" if gs.mana_pct < 100 else "недоступна"
        tip = tip_for(name, abilities_const, a.get("ultimate", False))
        if a.get("ultimate") or "ult" in tags:
            title += " (ульт)"
        lines.append((title, tip, state))

    ready = [
        a
        for a in learned
        if a.get("can_cast")
        and a.get("level", 0) > 0
        and a.get("cooldown", 0) == 0
    ]
    ult = [
        a
        for a in ready
        if a.get("ultimate") or "ult" in classify(a["name"], abilities_const)
    ]
    if gs.alive and 0 < gs.hp_pct <= 35:
        saver = [
            a
            for a in ready
            if {"defend", "escape", "heal"}
            & classify(a["name"], abilities_const)
        ]
        if saver:
            live.append(
                f"Мало здоровья ({gs.hp_pct}%) — нажмите "
                f"{title_for(saver[0]['name'], abilities_const)}, "
                "чтобы выжить."
            )
        else:
            live.append(
                f"Мало здоровья ({gs.hp_pct}%) — отходите к своим, не "
                "начинайте драку."
            )
    if ult and gs.alive and not any(a.get("passive") for a in ult):
        live.append(
            f"Ульт {title_for(ult[0]['name'], abilities_const)} готов — "
            "берегите его для драки."
        )
    if (
        gs.alive
        and 0 < gs.mana_pct <= 20
        and any(not a.get("passive") for a in learned)
    ):
        live.append(
            "Мало маны — не тратьте способности на крипов, оставьте на драку."
        )
    return live, lines
