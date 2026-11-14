"""Воспроизведение записанного матча без игры и без окна.

replay() прогоняет пакеты записи через советника и тренера так же, как это
делает программа во время матча, и возвращает:
  • ленту событий — когда сменился совет, когда хватило золота, что сказал
    тренер; по ней видно, как программа вела себя в этом матче;
  • нарушения — ситуации, которых не должно быть никогда (совет купить уже
    купленный предмет, «купить сейчас» дороже, чем есть золота, и т. п.).

Нарушения — это проверка программы на реальных матчах: после любой правки
можно прогнать все записи и убедиться, что ничего не сломалось.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from .advisor import Advice, Advisor
from .commitment import _real_items
from .engine import CoachEngine, VoiceLine
from .game_state import GameState, parse
from .match_coach import MIN_GAP
from .recorder import Recording


@dataclass
class Event:
    clock: int  # игровое время, сек
    kind: str  # "предмет" | "золото" | "место" | "тренер" | "статус"
    text: str


@dataclass
class Violation:
    clock: int
    rule: str  # короткое имя правила
    text: str


@dataclass
class ReplayResult:
    events: list[Event] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    packets: int = 0
    hero: str = ""
    duration: int = 0  # игровое время последнего пакета
    voice: list[tuple[int, VoiceLine]] = field(default_factory=list)


def fmt_clock(sec: int) -> str:
    sign = "-" if sec < 0 else ""
    return f"{sign}{abs(sec) // 60}:{abs(sec) % 60:02d}"


def check_advice(gs: GameState, a: Advice, advisor: Advisor) -> list[str]:
    """Правила, которые совет не должен нарушать никогда.

    Возвращает список вида "правило: пояснение".
    """
    problems: list[str] = []
    if a.status != "ok":
        return problems
    db = advisor.db
    owned = gs.owned
    if a.target in owned:
        problems.append(f"owned: советует уже купленный {a.target}")
    elif a.target in db.covered(owned):
        problems.append(
            f"component: {a.target} уже входит в купленный предмет"
        )
    if a.remaining < 0:
        problems.append(f"negative: осталось потратить {a.remaining}")
    spend = sum(cost for _, cost in a.buy_now)
    if not a.can_buy_full and spend > gs.gold:
        problems.append(
            f"overspend: «купить сейчас» на {spend} при золоте {gs.gold}"
        )
    owned_titles = {db.dname(x) for x in owned}
    for _verb, title in a.free_up:
        if title not in owned_titles:
            problems.append(
                f"phantom: предлагает убрать {title}, которого нет"
            )
    return problems


def replay(
    recording: Recording,
    advisor: Advisor,
    enemies: Sequence[str] = (),
    role_setting: str = "auto",
) -> ReplayResult:
    """Прогоняет запись через ядро программы — тем же путём, что и в игре."""
    result = ReplayResult()
    engine = CoachEngine(advisor.store, advisor=advisor)
    engine.role_setting = role_setting
    started = False
    last_key: tuple[str, str] | None = None
    last_full = False
    last_coach_clock: int | None = None
    seen: set[tuple[str, str]] = set()
    # (цель, купленные предметы в момент, когда она стала целью)
    history: list[tuple[str, frozenset[str]]] = []

    def violate(clock: int, problem: str) -> None:
        rule, _, text = problem.partition(": ")
        if (rule, text) not in seen:  # одно и то же нарушение — один раз
            seen.add((rule, text))
            result.violations.append(Violation(clock, rule, text))

    for _t, payload in recording.packets:
        gs = parse(payload)
        if not gs.valid or gs.spectating:
            continue
        if not started:
            engine.start_match(gs.match_id, enemies)
            started = True
        result.packets += 1
        result.duration = gs.clock
        try:
            frame = engine.process(gs)
        except Exception as e:  # падение ядра — тоже нарушение
            violate(gs.clock, f"crash: {type(e).__name__}: {e}")
            continue
        a = frame.advice
        if a.hero_title:
            result.hero = a.hero_title
        for problem in check_advice(gs, a, advisor):
            violate(gs.clock, problem)
        result.voice += [(gs.clock, line) for line in frame.voice]

        if a.switch_note:
            result.events.append(Event(gs.clock, "смена", a.switch_note))
        key = (a.status, a.target)
        if key != last_key:
            if a.status == "ok":
                items = _real_items(gs.owned, advisor.db)
                if (a.target, items) in history:
                    # Вернулись к прежней цели, хотя игрок ничего не купил:
                    # совет «качается» туда-сюда.
                    violate(
                        gs.clock,
                        f"flip: совет вернулся к {a.target_title} "
                        "без покупок — качели",
                    )
                history.append((a.target, items))
                text = f"{a.target_title} — {a.target_cost}"
                if a.owned_value:
                    text += f" (осталось {a.remaining})"
                result.events.append(Event(gs.clock, "предмет", text))
            elif a.status in ("start", "done"):
                result.events.append(Event(gs.clock, "статус", a.target_title))
            last_key, last_full = key, False
        if a.status == "ok" and a.can_buy_full and not last_full:
            result.events.append(
                Event(gs.clock, "золото", f"хватает на {a.target_title}")
            )
        last_full = a.status == "ok" and a.can_buy_full
        if a.free_up and a.free_up_text:
            ev = Event(gs.clock, "место", a.free_up_text)
            if not any(
                e.kind == "место" and e.text == ev.text for e in result.events
            ):
                result.events.append(ev)

        msg = frame.coach_message
        if msg:
            if (
                last_coach_clock is not None
                and msg.clock - last_coach_clock < MIN_GAP
            ):
                violate(gs.clock, "coach-spam: советы тренера идут подряд")
            last_coach_clock = msg.clock
            result.events.append(Event(gs.clock, "тренер", msg.text))
    return result


def format_result(result: ReplayResult, voice: bool = False) -> str:
    """Текст для терминала. voice=True — показать и фразы голоса."""
    lines = [
        f"Герой: {result.hero or '?'} · пакетов: {result.packets} · "
        f"длительность: {fmt_clock(result.duration)}",
        "",
    ]
    events = [(e.clock, e.kind, e.text) for e in result.events]
    if voice:
        events += [(c, "голос", v.text) for c, v in result.voice]
        events.sort(
            key=lambda e: e[0]
        )  # sort устойчив: порядок внутри секунды
    for clock, kind, text in events:
        lines.append(f"{fmt_clock(clock):>7}  [{kind}] {text}")
    lines.append("")
    if result.violations:
        lines.append(f"НАРУШЕНИЯ: {len(result.violations)}")
        for v in result.violations:
            lines.append(f"{fmt_clock(v.clock):>7}  {v.rule}: {v.text}")
    else:
        lines.append("Нарушений нет ✓")
    return "\n".join(lines)
