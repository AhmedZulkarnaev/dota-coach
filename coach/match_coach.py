"""Советы тренера по стадиям игры.

Не постоянный поток, а разовые советы в нужный момент матча: «игра началась —
добивайте
крипов», «линия заканчивается — фармите лес», «скоро руны богатства».
Каждый совет звучит один раз за матч (периодические — раз в свой интервал),
между советами минимум MIN_GAP секунд игрового времени.

Тайминги проверены для патча 7.41 (руны богатства — 0:00 и каждые 4 мин, руны
воды — 2:00 и 4:00, сильные руны — с 6:00 каждые 2 мин, стак — на 53–55-й
секунде минуты). Сами советы — в coach/data/coach_tips.json. Если Valve
поменяет тайминги, их можно поправить без программирования: файл
rules/coach_tips.json рядом с main.py (см. coach/rules.py).
"""

from dataclasses import dataclass, field, fields

from . import rules
from .game_state import GameState

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

    def with_roles(self) -> "Tip":
        """В JSON роли — список; внутри — кортеж."""
        self.roles = tuple(self.roles)
        return self

    def occurrences(self) -> list[int]:
        if not self.every:
            return [self.at]
        res, t = [], self.at
        while t <= (self.until or self.at):
            res.append(t)
            t += self.every
        return res


TIP_FIELDS = {f.name for f in fields(Tip)}


def load_tips() -> list[Tip]:
    """Советы из coach/data/coach_tips.json (+ свои из rules/)."""
    return [
        Tip(
            **{k: v for k, v in d.items() if k in TIP_FIELDS},
        ).with_roles()
        for d in rules.load("coach_tips")["tips"]
    ]


TIPS = load_tips()


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
