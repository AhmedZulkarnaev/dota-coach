"""Учёт состава врагов (игрок вводит героев вручную — GSI их не даёт).

Угрозы определяются двумя способами:
  • роли героя из OpenDota (Disabler — много контроля, Nuker — много магического урона);
  • короткие списки ниже — особенности наборов способностей, которые редко меняются.
"""

INVIS = {"riki", "bounty_hunter", "clinkz", "weaver", "nyx_assassin", "invoker",
         "mirana", "treant", "templar_assassin"}
EVASION = {"phantom_assassin", "windrunner"}
ILLUSIONS = {"phantom_lancer", "naga_siren", "chaos_knight", "terrorblade", "meepo", "spectre"}
HEALING = {"necrolyte", "alchemist", "huskar", "dazzle", "oracle", "omniknight", "warlock",
           "chen", "wisp", "witch_doctor", "abaddon", "juggernaut", "treant", "enchantress",
           "life_stealer", "undying"}


class EnemyCounter:
    """Ситуативный предмет против врагов."""

    def __init__(self, item, reason, strength):
        self.item, self.reason, self.strength = item, reason, strength


def analyze(enemy_shorts, heroes_by_short, my_role):
    """Возвращает (counters, reminders, summary).

    enemy_shorts — внутренние имена героев врага ("lion", "phantom_assassin"...)
    heroes_by_short — словарь short -> данные героя OpenDota (нужны roles)
    my_role — "core" или "support"
    """
    counters, reminders, summary = [], [], []
    if not enemy_shorts:
        return counters, reminders, summary

    def roles(s):
        return set((heroes_by_short.get(s) or {}).get("roles") or [])

    def names(lst):
        return ", ".join((heroes_by_short.get(s) or {}).get("localized_name") or s for s in lst)

    disablers = [s for s in enemy_shorts if "Disabler" in roles(s)]
    nukers = [s for s in enemy_shorts if "Nuker" in roles(s)]
    invis = [s for s in enemy_shorts if s in INVIS]
    evasion = [s for s in enemy_shorts if s in EVASION]
    illusions = [s for s in enemy_shorts if s in ILLUSIONS]
    healers = [s for s in enemy_shorts if s in HEALING]

    if disablers:
        summary.append(f"контроль ×{len(disablers)}")
    if nukers:
        summary.append(f"магия ×{len(nukers)}")
    if invis:
        summary.append("невидимость")
    if evasion:
        summary.append("уклонение")
    if illusions:
        summary.append("иллюзии")
    if healers:
        summary.append("лечение")

    core = my_role == "core"
    if len(disablers) >= 3 or (len(disablers) >= 2 and len(nukers) >= 3):
        if core:
            counters.append(EnemyCounter(
                "black_king_bar",
                f"У врагов {len(disablers)} героя с контролем (оглушения, хексы, сайленсы). "
                "BKB даёт иммунитет к большинству заклинаний — без него в драке вас просто "
                "застанят и убьют.",
                1.0))
        else:
            counters.append(EnemyCounter(
                "glimmer_cape",
                f"У врагов много контроля и магии. Glimmer Cape делает вас (или союзника) "
                "невидимым и даёт защиту от магии — главный спасательный предмет саппорта.",
                0.8))
    elif len(nukers) >= 3:
        if core:
            counters.append(EnemyCounter(
                "black_king_bar",
                f"У врагов {len(nukers)} героя с сильной магией. BKB спасает от магического "
                "урона в драках.", 0.8))
        else:
            counters.append(EnemyCounter(
                "glimmer_cape",
                "У врагов много магического урона: Glimmer Cape даёт сопротивление магии "
                "и невидимость, чтобы спастись.", 0.7))

    if evasion and core:
        counters.append(EnemyCounter(
            "monkey_king_bar",
            "У врагов есть уклонение от атак (" + names(evasion) + "). "
            "Monkey King Bar даёт атакам точность — без него вы будете промахиваться.",
            0.9))

    if illusions and core:
        counters.append(EnemyCounter(
            "maelstrom",
            "У врагов иллюзии/клоны. Maelstrom бьёт молниями по нескольким целям "
            "и помогает быстро сносить иллюзии.", 0.5))

    if healers:
        counters.append(EnemyCounter(
            "spirit_vessel",
            "Во вражеской команде есть лечение. Spirit Vessel снижает лечение и регенерацию "
            "цели — враги перестанут «отхиливаться».", 0.5 if core else 0.8))

    if invis:
        reminders.append("У врагов невидимость: держите Dust of Appearance, "
                         + ("ставьте Sentry Ward" if not core else "попросите саппортов про Sentry Ward")
                         + ".")
    return counters, reminders, summary
