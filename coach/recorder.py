"""Запись матчей: все пакеты GSI из настоящей игры сохраняются в файл.

Зачем: по записи можно проиграть матч заново (tools/replay.py) — посмотреть,
что советовала программа, проверить её на ошибки и убедиться, что правки
ничего не сломали. Записью можно поделиться в issue на GitHub.

Формат — сжатый JSON Lines (.jsonl.gz):
  1-я строка — заголовок {"format": "dota-coach-recording", "version": 1, ...};
  дальше по строке на пакет: {"t": секунды от начала записи, "payload": {...}}.

Приватность: перед записью из пакета убираются секретный токен GSI,
SteamID, accountid и ник игрока.

Запись надёжна при сбоях: если программа упала посреди матча, всё, что
успело записаться, читается (load_recording пропускает оборванный хвост).
"""

import contextlib
import copy
import gzip
import json
import logging
import threading
import time
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .game_state import POST_GAME, parse
from .heroes_ru import short_name

LOG = logging.getLogger("dota_coach.recorder")

FORMAT = "dota-coach-recording"
FORMAT_VERSION = 1
SUFFIX = ".jsonl.gz"
FLUSH_EVERY = 30.0  # сек: как часто сбрасывать запись на диск
POST_GAME_TAIL = 60.0  # сек: сколько писать после конца матча (ждём итог)
PRIVATE_PLAYER_KEYS = ("steamid", "accountid", "name")


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Копия пакета без секретного токена и личных данных игрока."""
    clean = copy.deepcopy(payload)
    clean.pop("auth", None)
    player = clean.get("player")
    if isinstance(player, dict):
        for key in PRIVATE_PLAYER_KEYS:
            player.pop(key, None)
    return clean


def _safe(text: str) -> str:
    return "".join(ch for ch in text if ch.isalnum() or ch in "-_") or "x"


class MatchRecorder:
    """Пишет пакеты GSI в файл: один файл на матч.

    add() вызывается из потока GSI-сервера на каждый пакет. Запись
    начинается сама, когда приходит матч, и заканчивается при смене матча,
    выходе в меню или через минуту после конца игры.
    """

    def __init__(
        self, folder: Path, enabled: bool = True, keep: int = 50
    ) -> None:
        self.folder = folder
        self.enabled = enabled
        self.keep = keep
        self.path: Path | None = None
        self._file: TextIO | None = None
        self._match_id = ""
        self._started = 0.0
        self._last_flush = 0.0
        self._ended_at: float | None = None
        self._done_match = ""  # матч, записанный до конца (после итогов)
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._file is not None

    def add(self, payload: Any, now: float | None = None) -> None:
        if not isinstance(payload, dict):
            return
        now = time.monotonic() if now is None else now
        with self._lock:
            try:
                self._add(payload, now)
            except OSError:
                # Диск полон или нет прав: игра важнее записи.
                LOG.exception("Не удалось записать пакет, запись остановлена")
                self._close()

    def _add(self, payload: dict[str, Any], now: float) -> None:
        gs = parse(payload)
        in_match = gs.valid and not gs.spectating and gs.in_match
        match_id = gs.match_id or "demo"
        if self._file and (not in_match or match_id != self._match_id):
            self._close()  # вышли в меню или начался другой матч
        if not self.enabled or not in_match:
            return
        if self._file is None:
            if match_id == self._done_match:
                return  # этот матч уже записан до конца
            if gs.hero_id <= 0 and not gs.hero_npc:
                return  # героя ещё не выбрали — ждём
            self._open(match_id, gs.hero_npc, now)
        if self._file is None:
            return
        record = {
            "t": round(now - self._started, 3),
            "payload": redact(payload),
        }
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        if now - self._last_flush >= FLUSH_EVERY:
            self._file.flush()
            self._last_flush = now
        if gs.game_state == POST_GAME:
            if self._ended_at is None:
                self._ended_at = now
            elif now - self._ended_at >= POST_GAME_TAIL:
                self._done_match = match_id
                self._close()

    def _open(self, match_id: str, hero_npc: str, now: float) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H-%M")
        hero = _safe(short_name(hero_npc)) if hero_npc else "hero"
        name = f"{stamp}_{_safe(match_id)}_{hero}{SUFFIX}"
        path = self.path = self.folder / name
        # Файл открыт на весь матч и закрывается в _close(): контекстный
        # менеджер здесь не подходит.
        self._file = gzip.open(path, "wt", encoding="utf-8")  # noqa: SIM115
        self._match_id = match_id
        self._started = self._last_flush = now
        self._ended_at = None
        header = {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "app_version": __version__,
            "match_id": match_id,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._file.write(json.dumps(header, ensure_ascii=False) + "\n")
        # Заголовок — сразу на диск: запись читается и во время матча,
        # и после сбоя в первые секунды.
        self._file.flush()
        LOG.info("Запись матча: %s", self.path.name)
        self._cleanup()

    def _close(self) -> None:
        if self._file is not None:
            with contextlib.suppress(OSError):
                self._file.close()
            LOG.info("Запись матча закончена: %s", self.path)
        self._file = None

    def close(self) -> None:
        """Закрыть текущую запись (при выходе из программы)."""
        with self._lock:
            self._close()

    def _cleanup(self) -> None:
        """Оставить только последние self.keep записей."""
        files = sorted(
            self.folder.glob(f"*{SUFFIX}"), key=lambda p: p.stat().st_mtime
        )
        for old in files[: max(0, len(files) - self.keep)]:
            if old != self.path:
                with contextlib.suppress(OSError):
                    old.unlink()


@dataclass
class Recording:
    """Загруженная запись матча."""

    header: dict[str, Any] = field(default_factory=dict)
    packets: list[tuple[float, dict[str, Any]]] = field(default_factory=list)
    # Запись не закончена: матч ещё идёт или программа упала посреди матча.
    truncated: bool = False

    @property
    def duration(self) -> float:
        return self.packets[-1][0] if self.packets else 0.0


def _lines(path: Path) -> Iterator[str]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        yield from f


def load_recording(path: Path) -> Recording:
    """Читает запись. Оборванный хвост (сбой посреди матча) пропускается."""
    rec = Recording()
    try:
        for i, line in enumerate(_lines(path)):
            try:
                item = json.loads(line)
            except ValueError:
                rec.truncated = True  # недописанная последняя строка
                break
            if i == 0:
                if item.get("format") != FORMAT:
                    raise ValueError(f"{path.name}: это не запись Dota Coach")
                rec.header = item
                continue
            rec.packets.append((float(item["t"]), item["payload"]))
    except (EOFError, zlib.error, gzip.BadGzipFile):
        rec.truncated = True
    if not rec.header:
        raise ValueError(f"{path.name}: пустая или повреждённая запись")
    return rec
