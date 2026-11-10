"""Журнал матча: когда появился каждый предмет, золото, ласт-хиты и смерти по
минутам,
что советовала программа. По нему строится разбор после матча (post_match.py).
Файлы сохраняются в match_logs/ в формате JSON.
"""

import json
import time
from pathlib import Path
from typing import Any

from .game_state import POST_GAME, GameState


class MatchLog:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.reset("")

    def reset(self, match_id: str) -> None:
        self.match_id = match_id
        self.hero = ""
        self.hero_id = 0
        self.team = ""  # "radiant" / "dire"
        self.win_team = ""
        self.items_first_seen: dict[
            str, int
        ] = {}  # предмет -> игровое время (сек)
        # минута -> {gold, lh, dn, level, k, d, a, gpm, xpm, can_buy, target}
        self.per_minute: dict[int, dict[str, Any]] = {}
        self.advice_log: list[
            tuple[int, str]
        ] = []  # [(время, рекомендованный предмет)]
        self.death_clocks: list[int] = []  # игровое время каждой смерти
        self.duration = 0
        self.first_clock: int | None = None  # с какого момента мы видели матч
        self._deaths: int | None = None
        self.saved = False

    def update(self, gs: GameState, advice: Any = None) -> Path | None:
        """Возвращает путь к сохранённому журналу в момент окончания матча,
        иначе None.
        """
        if not gs.valid or not gs.match_id:
            return None
        if gs.match_id != self.match_id:
            self.reset(gs.match_id)
        self.hero = gs.hero_npc or self.hero
        self.hero_id = gs.hero_id or self.hero_id
        self.team = gs.team or self.team
        if self.first_clock is None:
            self.first_clock = gs.clock
        self.duration = max(self.duration, gs.clock)
        for it in gs.owned:
            self.items_first_seen.setdefault(it, gs.clock)
        if self._deaths is not None and gs.deaths > self._deaths:
            self.death_clocks.extend([gs.clock] * (gs.deaths - self._deaths))
        self._deaths = gs.deaths
        target = getattr(advice, "target", "") or ""
        if gs.clock >= 0:
            minute = gs.clock // 60
            prev = self.per_minute.get(minute, {})
            self.per_minute[minute] = {
                "gold": gs.gold,
                "lh": gs.last_hits,
                "dn": gs.denies,
                "level": gs.hero_level,
                "k": gs.kills,
                "d": gs.deaths,
                "a": gs.assists,
                "gpm": gs.gpm,
                "xpm": gs.xpm,
                # хватало ли золота на рекомендованный предмет хоть раз за эту
                # минуту
                "can_buy": bool(prev.get("can_buy"))
                or bool(getattr(advice, "can_buy_full", False) and gs.alive),
                "target": target or prev.get("target", ""),
            }
        if target and (
            not self.advice_log or self.advice_log[-1][1] != target
        ):
            self.advice_log.append((gs.clock, target))
        result_known = bool(gs.win_team) and not self.win_team
        self.win_team = gs.win_team or self.win_team
        if gs.game_state == POST_GAME:
            if not self.saved:
                return self.save()
            if result_known:
                # победитель стал известен позже — дописываем в журнал
                self.save()
        return None

    @property
    def result(self) -> str:
        """ "win", "loss" или "" (если победитель неизвестен)."""
        if not self.team or not self.win_team:
            return ""
        return "win" if self.team == self.win_team else "loss"

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "hero": self.hero,
            "hero_id": self.hero_id,
            "result": self.result,
            "saved_at": time.strftime("%Y-%m-%d %H:%M"),
            "duration": self.duration,
            "first_clock": self.first_clock,
            "items_first_seen": dict(
                sorted(self.items_first_seen.items(), key=lambda kv: kv[1])
            ),
            "per_minute": {
                str(k): v for k, v in sorted(self.per_minute.items())
            },
            "advice_log": self.advice_log,
            "death_clocks": self.death_clocks,
        }

    def save(self) -> Path | None:
        if not self.match_id:
            return None
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"match_{self.match_id}.json"
        try:
            path.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            self.saved = True
            return path
        except OSError:
            return None
