"""Советы тренера по стадиям игры.

Не постоянный поток, а разовые советы в нужный момент матча: «игра началась —
добивайте
крипов», «линия заканчивается — фармите лес», «скоро руны богатства».
Каждый совет звучит один раз за матч (периодические — раз в свой интервал),
между советами минимум MIN_GAP секунд игрового времени.

Тайминги проверены для патча 7.41 (руны богатства — 0:00 и каждые 4 мин, руны
воды —
2:00 и 4:00, сильные руны — с 6:00 каждые 2 мин, стак — на 53–55-й секунде
минуты).
Если Valve их поменяет, советы можно поправить без программирования:
создайте рядом с main.py файл coach_tips.json со списком в том же формате, что
TIPS ниже
(он заменит встроенный список).
"""

import json
from dataclasses import dataclass, field

from .game_state import GameState
from .settings import APP_DIR

MIN_GAP = 25  # сек игрового времени между советами
WINDOW = (
    90  # совет актуален столько секунд после своего времени, потом пропускаем
)
ALL = ("core", "support")


@dataclass
class Tip:
    id: str
    at: int  # игровое время (сек), когда сказать
    text: str
    roles: tuple = ALL
    every: int = 0  # повторять каждые N сек (0 — один раз)
    until: int = 0  # до какого времени повторять
    priority: int = 2  # меньше — важнее

    def occurrences(self) -> list[int]:
        if not self.every:
            return [self.at]
        res, t = [], self.at
        while t <= (self.until or self.at):
            res.append(t)
            t += self.every
        return res


TIPS = [
    Tip(
        "pregame",
        -75,
        "Купите стартовые предметы и идите на свою линию. До горна можно "
        "встать "
        "у руны в реке вместе с командой.",
        priority=1,
    ),
    Tip(
        "start_core",
        0,
        "Игра началась! Главное на линии — добивать крипов последним ударом: "
        "это ваше золото. Не гонитесь за убийствами.",
        ("core",),
        priority=1,
    ),
    Tip(
        "start_support",
        0,
        "Игра началась! Помогайте своему керри: отгоняйте врагов от крипов "
        "и не забирайте у него добивания. Поставьте вард.",
        ("support",),
        priority=1,
    ),
    Tip(
        "denies",
        135,
        "Добивайте и своих крипов, когда у них мало здоровья. Это денай: враг "
        "получит меньше золота и опыта.",
        ("core",),
    ),
    Tip(
        "pull",
        150,
        "Можно отвести крипов из малого лагеря на свою линию — это пул. "
        "Так линия встанет ближе к вашей башне.",
        ("support",),
    ),
    Tip(
        "bounty",
        220,
        "Скоро руны богатства в лесу — они дают золото всей команде. Заберите "
        "ближайшую, если это безопасно.",
        every=240,
        until=700,
    ),
    Tip(
        "minimap",
        260,
        "Чаще смотрите на мини-карту. Если враг пропал с линии — он может "
        "идти "
        "к вам, играйте осторожнее.",
    ),
    Tip(
        "stack",
        285,
        "Время стакать лагерь: на 53-й секунде ударьте крипов в лесу и "
        "уведите их. "
        "В лагере станет вдвое больше крипов для вашего керри.",
        ("support",),
        every=180,
        until=900,
    ),
    Tip(
        "farm_between",
        330,
        "Между волнами крипов забегайте в ближайший лесной лагерь. "
        "Не стойте без дела — фармите лес.",
        ("core",),
    ),
    Tip(
        "power_rune",
        345,
        "В 6:00 в реке появится первая сильная руна: ускорение, невидимость "
        "или урон. Дальше — каждые две минуты.",
    ),
    Tip(
        "rotate",
        420,
        "Если на вашей линии спокойно — помогите другим линиям или поставьте "
        "вард "
        "у вражеского леса.",
        ("support",),
    ),
    Tip(
        "lane_end_core",
        600,
        "Стадия линии заканчивается. Фармите по кругу: волна крипов, потом "
        "лагерь в лесу, потом снова линия. Цель — следующий предмет.",
        ("core",),
        priority=1,
    ),
    Tip(
        "lane_end_support",
        600,
        "Мид-гейм: держитесь рядом с командой, ставьте варды впереди "
        "и покупайте Smoke для неожиданных нападений.",
        ("support",),
        priority=1,
    ),
    Tip(
        "group",
        780,
        "Когда у команды есть сильные предметы, ходите вместе: "
        "вчетвером-впятером "
        "легче ломать башни и выигрывать драки.",
    ),
    Tip(
        "safety",
        960,
        "Не фармите в одиночку на вражеской половине карты, если не видите "
        "врагов "
        "на мини-карте.",
    ),
    Tip(
        "roshan",
        1200,
        "Если ваша команда выигрывает драки — убейте Рошана. Он даёт Аегис: "
        "вторую жизнь.",
        priority=1,
    ),
    Tip(
        "deaths_cost",
        1500,
        "Смерть теперь стоит дорого: враги получают много золота, а вы долго "
        "ждёте. Не рискуйте зря.",
    ),
    Tip(
        "late_core",
        1800,
        "Лейт. Держите золото на выкуп и не фармите там, где вас могут "
        "поймать "
        "одного.",
        ("core",),
        priority=1,
    ),
    Tip(
        "late_support",
        1800,
        "Лейт. Держитесь за спинами своих сильных героев, ставьте варды "
        "и купите Gem, если у врагов невидимки.",
        ("support",),
        priority=1,
    ),
    Tip(
        "late_group",
        2400,
        "Ходите только группой. Одна ошибка сейчас может стоить игры — "
        "дождитесь союзников.",
    ),
]


def load_tips() -> list[Tip]:
    path = APP_DIR / "coach_tips.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [
                Tip(**{**d, "roles": tuple(d.get("roles", ALL))}) for d in data
            ]
        except (OSError, ValueError, TypeError):
            pass
    return list(TIPS)


@dataclass
class CoachMessage:
    text: str
    clock: int
    priority: int = 2


@dataclass
class MatchCoach:
    tips: list[Tip] = field(default_factory=load_tips)
    match_id: str = ""
    fired: set[str] = field(default_factory=set)
    last_clock: int = -10_000
    deaths_base: int | None = (
        None  # смерти на момент, когда мы начали следить за матчем
    )

    def reset(self, match_id: str) -> None:
        self.match_id, self.fired, self.last_clock, self.deaths_base = (
            match_id,
            set(),
            -10_000,
            None,
        )

    def update(
        self, gs: GameState, role: str, level: str = "all"
    ) -> CoachMessage | None:
        """Вернёт CoachMessage, если пора что-то сказать, иначе None.
        level: "all" — все советы, "main" — только главные (priority 1), "off"
        — ничего."""
        if level == "off":
            return None
        if not gs.valid or not gs.match_id or gs.spectating:
            return None
        if gs.match_id != self.match_id:
            self.reset(gs.match_id)
        if self.deaths_base is None:
            self.deaths_base = gs.deaths
        if gs.game_state not in (
            "DOTA_GAMERULES_STATE_PRE_GAME",
            "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
        ):
            return None
        if gs.paused or gs.clock - self.last_clock < MIN_GAP:
            return None

        due = []
        for msg in self._smart(gs, role):
            due.append(msg)
        for tip in self.tips:
            if role not in tip.roles or (level == "main" and tip.priority > 1):
                continue
            for t in tip.occurrences():
                key = f"{tip.id}@{t}"
                if key in self.fired:
                    continue
                if t <= gs.clock <= t + WINDOW:
                    due.append((tip.priority, t, key, tip.text))
                elif gs.clock > t + WINDOW:
                    self.fired.add(key)  # опоздали — пропускаем молча
        if not due:
            return None
        prio, t, key, text = min(due)
        self.fired.add(key)
        self.last_clock = gs.clock
        return CoachMessage(text, gs.clock, prio)

    def _smart(
        self, gs: GameState, role: str
    ) -> list[tuple[int, int, str, str]]:
        """Советы по ситуации, а не по часам."""
        res = []
        if (
            self.deaths_base == 0
            and gs.deaths >= 1
            and not gs.alive
            and "first_death" not in self.fired
        ):
            res.append(
                (
                    1,
                    gs.clock,
                    "first_death",
                    "Вы погибли. Подумайте почему: зашли слишком далеко или "
                    "враги пришли из "
                    "тумана? Пока ждёте — закупитесь.",
                )
            )
        if (
            gs.deaths >= 3
            and gs.clock < 660
            and "many_deaths" not in self.fired
        ):
            res.append(
                (
                    1,
                    gs.clock,
                    "many_deaths",
                    "Вы часто умираете на линии. Стойте дальше от врагов и "
                    "отходите под башню "
                    "уже при половине здоровья.",
                )
            )
        if (
            role == "core"
            and 600 <= gs.clock <= 660
            and "lh10" not in self.fired
        ):
            lh = gs.last_hits
            text = (
                f"Отлично! Добито крипов к десятой минуте: {lh}. Так держать."
                if lh >= 45
                else f"Добито крипов к десятой минуте: {lh}. Хорошая цель — "
                "45 и больше: "
                "сосредоточьтесь на последних ударах."
            )
            res.append((1, gs.clock, "lh10", text))
        return res
