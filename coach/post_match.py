"""Разбор после матча: что получилось, что купили поздно, где «простаивало»
золото.

Источники:
  • журнал матча (match_log.py): предметы, золото, ласт-хиты, смерти, советы
    программы;
  • OpenDota /benchmarks?hero_id=… — показатели других игроков на этом герое
    (золото, опыт и добивания в минуту по процентилям). Если интернета нет —
    разбор строится без сравнения;
  • ваши прошлые матчи (history.py) — раздел «Прогресс».

Каждый раздел разбора — отдельная функция, которая возвращает (строки, советы).
"""

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

from .heroes_ru import short_name
from .history import RESULT_RU, MatchSummary, progress_lines, summarize
from .item_db import ItemDB

KEY_EXTRA = {"blink", "aghanims_shard", "ultimate_scepter", "hand_of_midas"}
LH10_GOAL = 45  # цель по добитым крипам к 10-й минуте для кора
MAX_TIPS = 3

Log = dict[str, Any]
Section = tuple[
    list[str], list[str]
]  # (строки раздела, советы на следующий матч)


def fmt_clock(sec: float) -> str:
    sec = int(sec)
    sign = "-" if sec < 0 else ""
    return f"{sign}{abs(sec) // 60}:{abs(sec) % 60:02d}"


def percentile_of(value: float, rows: list[dict] | None) -> float:
    """Доля игроков, которых вы обошли (0..1).

    rows — список вида [{"percentile": 0.1, "value": 350}, ...] из OpenDota.
    """
    best = 0.0
    for row in rows or []:
        try:
            if value >= float(row["value"]):
                best = max(best, float(row["percentile"]))
        except (KeyError, TypeError, ValueError):
            continue
    return best


def _bench_line(
    title: str, value: float, rows: list[dict] | None, fmt: str = "{:.0f}"
) -> str | None:
    if not rows:
        return None
    p = percentile_of(value, rows)
    if p == 0:
        verdict = "ниже, чем у 90% игроков на этом герое"
    elif p >= 0.9:
        verdict = "лучше, чем у 90% игроков на этом герое — отлично!"
    else:
        verdict = (
            f"лучше, чем примерно у {int(p * 100)}% игроков на этом герое"
        )
    return f"{title}: {fmt.format(value)} — {verdict}"


def key_items(log: Log, db: ItemDB) -> list[tuple[str, int]]:
    """Готовые (собранные) предметы и важные одиночные — в порядке покупки."""
    res = []
    seen = log.get("items_first_seen") or {}
    for item, clock in sorted(seen.items(), key=lambda kv: kv[1]):
        if not db.exists(item):
            continue
        assembled = bool(db.components(item)) and db.cost(item) >= 1000
        if assembled or item in KEY_EXTRA:
            res.append((item, clock))
    return res


def _per_minute(log: Log) -> dict[int, dict]:
    return {int(k): v for k, v in (log.get("per_minute") or {}).items()}


def _joined_late(log: Log) -> bool:
    first_clock = log.get("first_clock")
    return first_clock is not None and first_clock > 60


def _benchmarks_section(
    summary: MatchSummary, bench: dict | None, role: str
) -> Section:
    result = (bench or {}).get("result") or {}
    if not result:
        return [], []
    minutes = max(1, summary.duration / 60)
    lines = ["", "СРАВНЕНИЕ С ДРУГИМИ ИГРОКАМИ (OpenDota)"]
    for title, value, key, fmt in (
        ("Золото в минуту", summary.gpm, "gold_per_min", "{:.0f}"),
        ("Опыт в минуту", summary.xpm, "xp_per_min", "{:.0f}"),
        (
            "Добито крипов в минуту",
            summary.last_hits / minutes,
            "last_hits_per_min",
            "{:.1f}",
        ),
    ):
        line = _bench_line(title, value, result.get(key), fmt)
        if line:
            lines.append("• " + line)
    tips = []
    if (
        role == "core"
        and percentile_of(summary.gpm, result.get("gold_per_min")) < 0.3
    ):
        tips.append(
            "Фармите больше: между волнами крипов забегайте в лесные лагеря, "
            "не стойте без дела."
        )
    return lines, tips


def _lane_section(
    summary: MatchSummary, deaths: list[int], role: str
) -> Section:
    lines: list[str] = ["", "ЛИНИЯ (0–10 мин)"]
    tips: list[str] = []
    if summary.lh10 is not None:
        mark = "✓" if summary.lh10 >= LH10_GOAL else f"— цель {LH10_GOAL}+"
        lines.append(f"• Добито крипов к 10-й минуте: {summary.lh10} {mark}")
        if role == "core" and summary.lh10 < LH10_GOAL:
            tips.append(
                "Тренируйте добивание: в режиме «Демо-герой» постарайтесь "
                f"добить {LH10_GOAL}+ "
                "крипов за 10 минут."
            )
    early_deaths = [d for d in deaths if d < 600]
    lines.append(f"• Смертей до 10-й минуты: {len(early_deaths)}")
    if len(early_deaths) >= 3:
        tips.append(
            "На линии отходите под башню уже при половине здоровья и следите "
            "за мини-картой."
        )
    return lines, tips


def _affordable_since(
    per_min: dict[int, dict], item: str, bought: int
) -> int | None:
    """С какого момента перед покупкой предмет был целью и золота на него
    хватало.
    """
    since = None
    for minute in sorted(per_min):
        if minute * 60 >= bought:
            break
        row = per_min[minute]
        if row.get("target") != item:
            since = None  # покупали что-то другое — отсчёт заново
        elif row.get("can_buy") and since is None:
            since = minute * 60
    return since


def _items_section(log: Log, db: ItemDB) -> tuple[list[str], list[str]]:
    """Возвращает (строки раздела, названия предметов, купленных позже
    возможного).
    """
    per_min = _per_minute(log)
    first_clock = log.get("first_clock")
    lines: list[str] = ["", "КЛЮЧЕВЫЕ ПРЕДМЕТЫ"]
    late: list[str] = []
    items = key_items(log, db)
    if not items:
        lines.append("• Крупных предметов не было.")
    for item, clock in items:
        if _joined_late(log) and clock == first_clock:
            lines.append(f"• {db.dname(item)} — уже был при подключении")
            continue
        line = f"• {db.dname(item)} — {fmt_clock(clock)}"
        rich_at = _affordable_since(per_min, item, clock)
        if rich_at is not None and clock - rich_at >= 120:
            line += (
                f" (золота хватало уже с {fmt_clock(rich_at)} — "
                f"на {(clock - rich_at) // 60} мин позже)"
            )
            late.append(db.dname(item))
        lines.append(line)
    return lines, late


def _idle_gold(per_min: dict[int, dict]) -> tuple[int, int | None, int]:
    """Минуты, когда золота хватало на цель, а покупки не было.

    Возвращает (всего минут, начало самого длинного простоя, его длина).
    """
    idle = streak = best = 0
    best_start = cur_start = None
    for minute in sorted(per_min):
        row, nxt = per_min[minute], per_min.get(minute + 1)
        waiting = (
            row.get("can_buy")
            and nxt
            and nxt.get("can_buy")
            and nxt.get("target") == row.get("target")
        )
        if not waiting:
            streak = 0
            continue
        idle += 1
        if streak == 0:
            cur_start = minute
        streak += 1
        if streak > best:
            best, best_start = streak, cur_start
    return idle, best_start, best


def _gold_section(log: Log, late: list[str]) -> Section:
    lines: list[str] = ["", "ЗОЛОТО"]
    tips: list[str] = []
    idle, start, length = _idle_gold(_per_minute(log))
    if idle >= 2 and start is not None:
        lines.append(
            f"• {idle} мин золота хватало на следующий предмет, но покупки "
            "не было "
            f"(дольше всего: с {start}-й по {start + length + 1}-ю минуту)."
        )
        tips.append(
            "Покупайте предмет сразу, как хватает золота: программа говорит "
            "«Хватает золота». "
            "Предмет в инвентаре сильнее золота в кармане."
        )
    else:
        lines.append("• Золото тратилось вовремя ✓")
    if late:
        lines.append("• Куплено позже, чем могли: " + ", ".join(late) + ".")
    return lines, tips


def _deaths_section(deaths: list[int]) -> Section:
    lines: list[str] = ["", "СМЕРТИ"]
    tips: list[str] = []
    if not deaths:
        lines.append("• Ни одной смерти — отлично ✓")
        return lines, tips
    lines.append(
        f"• Всего {len(deaths)}: " + ", ".join(fmt_clock(d) for d in deaths)
    )
    repeats = [(a, b) for a, b in pairwise(deaths) if b - a <= 150]
    if repeats:
        a, b = repeats[0]
        lines.append(
            f"• Смерти подряд ({fmt_clock(a)} и {fmt_clock(b)}): после "
            "возрождения "
            "не спешите сразу в ту же драку."
        )
        tips.append(
            "После смерти не бегите сразу обратно в драку — дождитесь "
            "союзников."
        )
    if len(deaths) >= 8:
        tips.append(
            "Умирайте реже: перед тем как зайти в драку, посмотрите на "
            "мини-карту — "
            "где враги, которых не видно?"
        )
    return lines, tips


def _progress_section(
    summary: MatchSummary, previous: list[MatchSummary] | None
) -> Section:
    progress = progress_lines(summary, previous or [])
    if not progress:
        return [], []
    return ["", "ПРОГРЕСС (по сравнению с вашими прошлыми матчами)"] + [
        "• " + p for p in progress
    ], []


def build_report(
    log: Log,
    db: ItemDB,
    hero_title: str = "",
    role: str = "core",
    bench: dict | None = None,
    previous: list[MatchSummary] | None = None,
) -> tuple[str, list[str]]:
    """Возвращает (текст разбора, список советов на следующий матч).

    previous — итоги прошлых матчей (от новых к старым) для раздела «Прогресс».
    """
    summary = summarize(log)
    deaths = list(log.get("death_clocks") or [])
    hero = (
        hero_title
        or short_name(log.get("hero", "")).replace("_", " ").title()
        or "герой"
    )
    result = (
        f"{RESULT_RU[summary.result].capitalize()} · "
        if summary.result in ("win", "loss")
        else ""
    )

    lines = [
        f"РАЗБОР МАТЧА — {hero}, {fmt_clock(summary.duration)}",
        f"Итог: {result}KDA "
        f"{summary.kills}/{summary.deaths}/{summary.assists} · "
        f"добито крипов {summary.last_hits} · золото в минуту {summary.gpm} · "
        f"опыт в минуту {summary.xpm}",
    ]
    if _joined_late(log):
        lines.append(
            f"(Программа подключилась на {fmt_clock(log['first_clock'])} — "
            "начало матча в разбор не попало.)"
        )

    item_lines, late = _items_section(log, db)
    sections = [
        _benchmarks_section(summary, bench, role),
        _lane_section(summary, deaths, role),
        (item_lines, []),
        _gold_section(log, late),
        _deaths_section(deaths),
        _progress_section(summary, previous),
    ]
    tips: list[str] = []
    for section_lines, section_tips in sections:
        lines += section_lines
        tips += section_tips
    if not tips:
        tips.append(
            "Хороший матч! Попробуйте собрать главный предмет на пару минут "
            "быстрее."
        )
    tips = tips[:MAX_TIPS]
    lines += ["", "НА СЛЕДУЮЩИЙ МАТЧ"] + [
        f"{i}. {tip}" for i, tip in enumerate(tips, 1)
    ]
    return "\n".join(lines), tips


def load_log(path: Path) -> Log:
    return json.loads(path.read_text(encoding="utf-8"))
