"""Ядро программы: данные игры на входе — готовый «кадр» на выходе.

Ядро ничего не рисует и ничего не произносит само. Оно решает:
  • что посоветовать (советник, верность цели, список покупок);
  • что сказать тренеру по стадии матча;
  • что качать на новом уровне (по матчам сильных игроков);
  • какие фразы произнести голосом и с какой важностью;
  • когда матч закончился и можно строить разбор.

Интерфейс (сейчас tkinter, в 1.0 — PySide6) только показывает кадр и
передаёт фразы в динамик. Ту же логику прогоняет tools/replay.py по
записанным матчам, поэтому проверка на записях = проверка программы.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import shopping as shop_mod
from .advisor import Advice, Advisor
from .game_state import GameState
from .match_coach import CoachMessage, MatchCoach
from .match_log import MatchLog
from .skill_builds import SkillHint, Step, consensus, skill_hint
from .speech_ru import speakable
from .voice import PRIORITY_HIGH, PRIORITY_LOW, PRIORITY_NORMAL


@dataclass
class VoiceLine:
    """Фраза для голоса. key + cooldown — чтобы не повторять её часто."""

    text: str
    key: str
    cooldown: float = 15
    priority: int = PRIORITY_NORMAL


@dataclass
class Frame:
    """Всё, что нужно интерфейсу для одного обновления."""

    gs: GameState
    advice: Advice
    new_match: bool = False
    coach_message: CoachMessage | None = None  # новый совет тренера
    skill: SkillHint | None = None  # что качать
    voice: list[VoiceLine] = field(default_factory=list)
    match_log: Path | None = None  # матч окончен, журнал сохранён


class CoachEngine:
    def __init__(
        self,
        store: Any,
        log_dir: Path | None = None,
        advisor: Advisor | None = None,
    ) -> None:
        """log_dir — куда писать журнал матча (None — не писать, для replay).

        advisor — свой советник (для тестов); по умолчанию Advisor(store).
        """
        self.store = store
        self.advisor = advisor or Advisor(store)
        self.coach = MatchCoach()
        self.log = MatchLog(log_dir) if log_dir else None
        self.role_setting = "auto"  # "auto" | "core" | "support"
        self.tips_level = "all"  # "all" | "main" | "off"
        self.match_id = ""
        self._enemies: list[str] = []
        self._plan: tuple[int, int, list[Step]] = (0, 0, [])
        self._spoken_skill = ""  # последнее сказанное очко прокачки
        self._reset_voice()

    # ---------- настройки матча ----------
    @property
    def enemies(self) -> list[str]:
        return list(self._enemies)

    def set_enemies(self, shorts: Sequence[str]) -> None:
        self._enemies = list(shorts)[:5]

    def start_match(self, match_id: str, enemies: Sequence[str] = ()) -> None:
        """Начать матч заранее, с уже известными врагами (для replay)."""
        self.match_id = match_id
        self._enemies = list(enemies)[:5]
        self._reset_voice()

    def role(self, gs: GameState) -> str:
        if gs.hero_id <= 0:
            return "core"
        return self.advisor.role(gs, self.role_setting)

    # ---------- главный шаг ----------
    def process(self, gs: GameState, new_packet: bool = True) -> Frame:
        """Один шаг: свежие данные игры → кадр.

        new_packet=False — данные те же, но изменились настройки или
        загрузились данные OpenDota: совет пересчитывается, а тренер и
        журнал не трогаются.
        """
        new_match = bool(gs.match_id) and gs.match_id != self.match_id
        if new_match:
            self.match_id = gs.match_id
            self._enemies = []
            self._reset_voice()
        if gs.hero_id > 0:
            self.store.prefetch(gs.hero_id)

        advice = self.advisor.advise(gs, self._enemies, self.role_setting)
        frame = Frame(gs, advice, new_match=new_match)
        if self.log is not None:
            frame.match_log = self.log.update(gs, advice)
        frame.voice = self._advice_voice(advice)
        frame.skill = skill_hint(
            gs, self.skill_plan(gs.hero_id), self.store.abilities
        )
        frame.voice += self._skill_voice(frame.skill)
        if new_packet:
            msg = self.coach.update(gs, self.role(gs), self.tips_level)
            if msg:
                frame.coach_message = msg
                frame.voice.append(
                    VoiceLine(
                        msg.text,
                        key="coach:" + msg.text,
                        cooldown=120,
                        priority=(
                            PRIORITY_HIGH
                            if msg.priority <= 1
                            else PRIORITY_NORMAL
                        ),
                    )
                )
        return frame

    # ---------- прокачка ----------
    def skill_plan(self, hero_id: int) -> list[Step]:
        """План прокачки героя; пересчитывается, только когда данные новые."""
        get = getattr(self.store, "get_skill_builds", None)
        builds = get(hero_id) if get and hero_id > 0 else None
        if not builds:
            return []
        key = (hero_id, id(builds))
        if self._plan[:2] != key:
            self._plan = (*key, consensus(builds))
        return self._plan[2]

    def _skill_voice(self, hint: SkillHint | None) -> list[VoiceLine]:
        """Одна фраза на каждое новое очко прокачки — когда его можно взять."""
        if not hint or not hint.learn_now:
            return []
        key = f"skill:{hint.step.level}:{hint.step.name}"
        if key == self._spoken_skill:
            return []
        self._spoken_skill = key
        if hint.step.is_talent:
            text = f"Новый талант: {speakable(hint.title)}"
        else:
            text = f"Качайте {speakable(hint.title)}"
        return [VoiceLine(text, key=key, cooldown=600, priority=PRIORITY_LOW)]

    # ---------- голос ----------
    def _reset_voice(self) -> None:
        self._spoken_target: str | None = None
        self._was_full = False
        self._spoken_parts: set[str] = set()
        self._start_spoken = False
        self._spoken_skill = ""

    def _advice_voice(self, a: Advice) -> list[VoiceLine]:
        """Что сказать по совету. Помнит сказанное, чтобы не повторяться."""
        lines: list[VoiceLine] = []
        if a.status == "start" and a.start_bundle and not self._start_spoken:
            self._start_spoken = True
            names = ", ".join(t for t, _ in a.start_bundle[:4])
            lines.append(VoiceLine(f"Стартовая закупка: {names}", "start"))
        if a.status != "ok":
            return lines

        low_hp = next(
            (x for x in a.ability_live if x.startswith("Мало здоровья")), None
        )
        if low_hp:
            lines.append(
                VoiceLine(
                    low_hp.split(" — ", 1)[-1],
                    key="lowhp",
                    cooldown=25,
                    priority=PRIORITY_HIGH,
                )
            )

        now_parts = {p.title for p in a.parts if p.state == shop_mod.NOW}
        if a.target != self._spoken_target:
            self._spoken_target = a.target
            self._was_full = a.can_buy_full
            self._spoken_parts = now_parts
            extra = ". Сначала освободите место" if a.free_up else ""
            text = a.switch_note or f"Следующий предмет: {a.target_title}."
            lines.append(
                VoiceLine(
                    text.rstrip(".") + extra,
                    key="target:" + a.target,
                    cooldown=60,
                )
            )
            return lines

        # Стало хватать на часть предмета — скажем один раз.
        new_parts = now_parts - self._spoken_parts
        if new_parts and not a.can_buy_full and not a.parts_no_room:
            name = sorted(new_parts)[0]
            lines.append(
                VoiceLine(
                    f"Можно купить {name}",
                    key=f"part:{a.target}:{name}",
                    cooldown=120,
                )
            )
        self._spoken_parts = now_parts

        if a.can_buy_full and not self._was_full:
            extra = ", но сначала освободите слот" if a.free_up else ""
            lines.append(
                VoiceLine(
                    f"Хватает золота на {a.target_title}{extra}",
                    key="full:" + a.target,
                    cooldown=45,
                )
            )
        self._was_full = a.can_buy_full
        return lines
