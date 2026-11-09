"""Разбор после матча: что получилось, что купили поздно, где «простаивало» золото.

Источники:
  • журнал матча (match_log.py): предметы, золото, ласт-хиты, смерти, советы программы;
  • OpenDota /benchmarks?hero_id=… — показатели других игроков на этом герое
    (золото, опыт и добивания в минуту по процентилям). Если интернета нет —
    разбор строится без сравнения.
"""

import json

from .heroes_ru import short_name

KEY_EXTRA = {"blink", "aghanims_shard", "ultimate_scepter", "hand_of_midas"}


def fmt_clock(sec):
    sec = int(sec)
    sign = "-" if sec < 0 else ""
    return f"{sign}{abs(sec) // 60}:{abs(sec) % 60:02d}"


def percentile_of(value, rows):
    """rows: [{"percentile": 0.1, "value": 350}, ...] → доля игроков, которых вы обошли (0..1)."""
    best = 0.0
    for r in rows or []:
        try:
            if value >= float(r["value"]):
                best = max(best, float(r["percentile"]))
        except (KeyError, TypeError, ValueError):
            continue
    return best


def _bench_line(title, value, rows, fmt="{:.0f}"):
    if not rows:
        return None
    p = percentile_of(value, rows)
    if p == 0:
        verdict = "ниже, чем у 90% игроков на этом герое"
    elif p >= 0.9:
        verdict = "лучше, чем у 90% игроков на этом герое — отлично!"
    else:
        verdict = f"лучше, чем примерно у {int(p * 100)}% игроков на этом герое"
    return f"{title}: {fmt.format(value)} — {verdict}"


def key_items(log, db):
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


def build_report(log, db, hero_title="", role="core", bench=None):
    """Возвращает (текст разбора, список советов на следующий матч)."""
    per_min = {int(k): v for k, v in (log.get("per_minute") or {}).items()}
    duration = int(log.get("duration") or (max(per_min) * 60 if per_min else 0))
    minutes = max(1, duration / 60)
    last = per_min[max(per_min)] if per_min else {}
    first_clock = log.get("first_clock")
    joined_late = first_clock is not None and first_clock > 60
    deaths = list(log.get("death_clocks") or [])
    hero = hero_title or short_name(log.get("hero", "")).replace("_", " ").title() or "герой"

    lines = [f"РАЗБОР МАТЧА — {hero}, {fmt_clock(duration)}",
             f"Итог: KDA {last.get('k', 0)}/{last.get('d', 0)}/{last.get('a', 0)} · "
             f"добито крипов {last.get('lh', 0)} · золото в минуту {last.get('gpm', 0)} · "
             f"опыт в минуту {last.get('xpm', 0)}"]
    if joined_late:
        lines.append(f"(Программа подключилась на {fmt_clock(first_clock)} — начало матча в разбор не попало.)")
    tips = []

    # --- сравнение с другими игроками ---
    result = (bench or {}).get("result") or {}
    if result:
        lines += ["", "СРАВНЕНИЕ С ДРУГИМИ ИГРОКАМИ (OpenDota)"]
        lh_pm = last.get("lh", 0) / minutes
        for title, val, key, fmt in (
            ("Золото в минуту", last.get("gpm", 0), "gold_per_min", "{:.0f}"),
            ("Опыт в минуту", last.get("xpm", 0), "xp_per_min", "{:.0f}"),
            ("Добито крипов в минуту", lh_pm, "last_hits_per_min", "{:.1f}"),
        ):
            line = _bench_line(title, val, result.get(key), fmt)
            if line:
                lines.append("• " + line)
        if role == "core" and percentile_of(last.get("gpm", 0), result.get("gold_per_min")) < 0.3:
            tips.append("Фармите больше: между волнами крипов забегайте в лесные лагеря, "
                        "не стойте без дела.")

    # --- линия ---
    lines += ["", "ЛИНИЯ (0–10 мин)"]
    lh10 = None
    for m in (10, 9):
        if m in per_min:
            lh10 = per_min[m].get("lh")
            break
    if lh10 is not None and not joined_late:
        mark = "✓" if lh10 >= 45 else "— цель 45+"
        lines.append(f"• Добито крипов к 10-й минуте: {lh10} {mark}")
        if role == "core" and lh10 < 45:
            tips.append("Тренируйте добивание: в режиме «Демо-герой» постарайтесь добить 45+ крипов "
                        "за 10 минут.")
    early_deaths = [d for d in deaths if d < 600]
    lines.append(f"• Смертей до 10-й минуты: {len(early_deaths)}")
    if len(early_deaths) >= 3:
        tips.append("На линии отходите под башню уже при половине здоровья и следите за мини-картой.")

    # --- предметы ---
    lines += ["", "КЛЮЧЕВЫЕ ПРЕДМЕТЫ"]
    def affordable_since(item, bought):
        """Первая минута до покупки, когда этот предмет был целью и золота на него хватало."""
        since = None
        for m in sorted(per_min):
            if m * 60 >= bought:
                break
            row = per_min[m]
            if row.get("target") != item:
                since = None              # покупали что-то другое — отсчёт заново
            elif row.get("can_buy") and since is None:
                since = m * 60
        return since

    late = []
    items = key_items(log, db)
    if not items:
        lines.append("• Крупных предметов не было.")
    for item, clock in items:
        if joined_late and clock == first_clock:
            lines.append(f"• {db.dname(item)} — уже был при подключении")
            continue
        line = f"• {db.dname(item)} — {fmt_clock(clock)}"
        rich_at = affordable_since(item, clock)
        if rich_at is not None and clock - rich_at >= 120:
            line += f" (золота хватало уже с {fmt_clock(rich_at)} — на {(clock - rich_at) // 60} мин позже)"
            late.append(db.dname(item))
        lines.append(line)

    # --- золото ---
    lines += ["", "ЗОЛОТО"]
    idle, streak, best, best_start, cur_start = 0, 0, 0, None, None
    for m in sorted(per_min):
        nxt = per_min.get(m + 1)
        if per_min[m].get("can_buy") and nxt and nxt.get("can_buy") \
                and nxt.get("target") == per_min[m].get("target"):
            idle += 1
            if streak == 0:
                cur_start = m
            streak += 1
            if streak > best:
                best, best_start = streak, cur_start
        else:
            streak = 0
    if idle >= 2:
        lines.append(f"• {idle} мин золота хватало на следующий предмет, но покупки не было "
                     f"(дольше всего: с {best_start}-й по {best_start + best + 1}-ю минуту).")
        tips.append("Покупайте предмет сразу, как хватает золота: программа говорит «Хватает золота». "
                    "Предмет в инвентаре сильнее золота в кармане.")
    else:
        lines.append("• Золото тратилось вовремя ✓")
    if late:
        lines.append("• Куплено позже, чем могли: " + ", ".join(late) + ".")

    # --- смерти ---
    lines += ["", "СМЕРТИ"]
    if deaths:
        lines.append(f"• Всего {len(deaths)}: " + ", ".join(fmt_clock(d) for d in deaths))
        repeats = [(a, b) for a, b in zip(deaths, deaths[1:]) if b - a <= 150]
        if repeats:
            a, b = repeats[0]
            lines.append(f"• Смерти подряд ({fmt_clock(a)} и {fmt_clock(b)}): после возрождения "
                         "не спешите сразу в ту же драку.")
            tips.append("После смерти не бегите сразу обратно в драку — дождитесь союзников.")
        if len(deaths) >= 8:
            tips.append("Умирайте реже: перед тем как зайти в драку, посмотрите на мини-карту — "
                        "где враги, которых не видно?")
    else:
        lines.append("• Ни одной смерти — отлично ✓")

    if not tips:
        tips.append("Хороший матч! Попробуйте собрать главный предмет на пару минут быстрее.")
    lines += ["", "НА СЛЕДУЮЩИЙ МАТЧ"] + [f"{i}. {t}" for i, t in enumerate(tips[:3], 1)]
    return "\n".join(lines), tips[:3]


def load_log(path):
    return json.loads(path.read_text(encoding="utf-8"))
