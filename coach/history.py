"""История матчей и прогресс: сравнение свежего матча с вашими предыдущими.

Данные берутся из журналов match_logs/match_*.json — тех же, по которым
строится разбор.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .heroes_ru import short_name

RESULT_RU = {"win": "победа", "loss": "поражение", "": "—"}
COMPARE_LAST = 5  # с каким числом прошлых матчей сравниваем


@dataclass
class MatchSummary:
    """Краткий итог одного матча."""

    match_id: str = ""
    saved_at: str = ""
    hero: str = ""  # внутреннее имя: npc_dota_hero_ursa
    duration: int = 0
    result: str = ""  # "win" | "loss" | ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    lh10: int | None = None  # добито крипов к 10-й минуте (None — нет данных)
    gpm: int = 0
    xpm: int = 0


def summarize(log: dict[str, Any]) -> MatchSummary:
    """Собирает MatchSummary из журнала матча (см. MatchLog.to_dict)."""
    per_min = {int(k): v for k, v in (log.get("per_minute") or {}).items()}
    last = per_min[max(per_min)] if per_min else {}
    duration = int(
        log.get("duration") or (max(per_min) * 60 if per_min else 0)
    )
    first_clock = log.get("first_clock")
    lh10 = None
    if first_clock is None or first_clock <= 60:
        for minute in (10, 9, 8):
            if minute in per_min:
                lh10 = int(per_min[minute].get("lh") or 0)
                break
    return MatchSummary(
        match_id=str(log.get("match_id") or ""),
        saved_at=str(log.get("saved_at") or ""),
        hero=str(log.get("hero") or ""),
        duration=duration,
        result=str(log.get("result") or ""),
        kills=int(last.get("k") or 0),
        deaths=int(last.get("d") or 0),
        assists=int(last.get("a") or 0),
        last_hits=int(last.get("lh") or 0),
        lh10=lh10,
        gpm=int(last.get("gpm") or 0),
        xpm=int(last.get("xpm") or 0),
    )


def load_history(
    log_dir: Path | str, limit: int = 20, exclude: str = ""
) -> list[MatchSummary]:
    """Последние матчи, от новых к старым.

    exclude — номер матча, который пропустить.
    """
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return []
    files = sorted(
        log_dir.glob("match_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    result = []
    for path in files:
        try:
            summary = summarize(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, AttributeError):
            continue  # повреждённый журнал не должен ломать историю
        if exclude and summary.match_id == exclude:
            continue
        if summary.duration < 300:
            continue  # демо-режим и брошенные матчи в статистику не идут
        result.append(summary)
        if len(result) >= limit:
            break
    return result


def _average(values: Iterable[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


def _compare(
    title: str,
    value: float | None,
    average: float | None,
    higher_is_better: bool = True,
    fmt: str = "{:.0f}",
) -> str | None:
    if value is None or average is None:
        return None
    diff = value - average
    if abs(diff) < max(1.0, abs(average) * 0.05):
        verdict = "на вашем обычном уровне"
    elif (diff > 0) == higher_is_better:
        verdict = "лучше вашего обычного ↑"
    else:
        verdict = "хуже вашего обычного ↓"
    return (
        f"{title}: {fmt.format(value)} (в среднем было "
        f"{fmt.format(average)}) — {verdict}"
    )


def progress_lines(
    current: MatchSummary, previous: Iterable[MatchSummary]
) -> list[str]:
    """Строки раздела «Прогресс»: текущий матч против среднего за прошлые
    матчи.
    """
    previous = list(previous)[:COMPARE_LAST]
    if not previous:
        return []
    compared = [
        _compare(
            "Добито к 10-й минуте",
            current.lh10,
            _average(m.lh10 for m in previous),
        ),
        _compare(
            "Золото в минуту", current.gpm, _average(m.gpm for m in previous)
        ),
        _compare(
            "Смертей за матч",
            current.deaths,
            _average(m.deaths for m in previous),
            higher_is_better=False,
            fmt="{:.1f}",
        ),
    ]
    lines = [line for line in compared if line]
    known = [m for m in previous if m.result]
    if known:
        wins = sum(1 for m in known if m.result == "win")
        lines.append(f"Побед в прошлых {len(known)} матчах: {wins}")
    return lines


def history_table(
    matches: list[MatchSummary], hero_title: Callable[[str], str] | None = None
) -> str:
    """Текстовая таблица истории матчей (для моноширинного шрифта)."""
    if not matches:
        return "Пока нет ни одного сыгранного матча с программой."
    hero_title = hero_title or (
        lambda npc: short_name(npc).replace("_", " ").title()
    )
    header = (
        f"{'Дата':<17}{'Герой':<20}{'Итог':<11}{'KDA':<10}{'Мин':>4}"
        f"{'LH@10':>7}{'GPM':>6}"
    )
    rows = [header, "-" * len(header)]
    for m in matches:
        kda = f"{m.kills}/{m.deaths}/{m.assists}"
        lh10 = "—" if m.lh10 is None else str(m.lh10)
        rows.append(
            f"{m.saved_at:<17}{hero_title(m.hero)[:19]:<20}"
            f"{RESULT_RU.get(m.result, '—'):<11}"
            f"{kda:<10}{m.duration // 60:>4}{lh10:>7}{m.gpm:>6}"
        )
    known = [m for m in matches if m.result]
    rows.append("")
    if known:
        wins = sum(1 for m in known if m.result == "win")
        rows.append(f"Побед: {wins} из {len(known)}")
    avg_lh = _average(m.lh10 for m in matches)
    if avg_lh is not None:
        rows.append(
            f"В среднем добито к 10-й минуте: {avg_lh:.0f} (цель для кора — "
            "45+)"
        )
    rows.append(
        f"В среднем смертей за матч: {_average(m.deaths for m in matches):.1f}"
    )
    return "\n".join(rows)
