"""Воспроизведение записанного матча.

Записи лежат в папке recordings/ (программа пишет каждый матч сама).

    python tools/replay.py               последняя запись: советы + проверка
    python tools/replay.py ФАЙЛ          конкретная запись
    python tools/replay.py --all         проверить все записи (кратко)
    python tools/replay.py --list        список записей
    python tools/replay.py ФАЙЛ --to-app проиграть в запущенную программу
                                         (--speed 10 — в 10 раз быстрее)

Дополнительно: --role core|support, --enemies lion,pudge,phantom_assassin.
Код выхода 1, если найдены нарушения, — удобно для автоматических проверок.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coach import settings as settings_mod  # noqa: E402
from coach.advisor import Advisor  # noqa: E402
from coach.data_store import DataStore  # noqa: E402
from coach.game_state import parse  # noqa: E402
from coach.recorder import SUFFIX, Recording, load_recording  # noqa: E402
from coach.replay import format_result, replay  # noqa: E402


def recordings() -> list[Path]:
    folder = settings_mod.RECORD_DIR
    if not folder.exists():
        return []
    return sorted(folder.glob(f"*{SUFFIX}"), key=lambda p: p.stat().st_mtime)


def make_advisor(rec: Recording) -> Advisor:
    """Советник на данных из data_cache/; недостающее докачивает из сети."""
    store = DataStore(settings_mod.CACHE_DIR, max_age_days=10_000)
    if not store.items or not store.heroes:
        print("Скачиваю данные OpenDota…")
        store._refresh_constants(force=False)
    hero_ids = {parse(p).hero_id for _, p in rec.packets[-50:]} - {0}
    for hero_id in hero_ids:
        if store.get_popularity(hero_id) is None:
            print(f"Скачиваю сборки героя {hero_id}…")
            store._refresh_popularity(hero_id)
    return Advisor(store)


def run_check(path: Path, args: argparse.Namespace, brief: bool) -> int:
    rec = load_recording(path)
    advisor = make_advisor(rec)
    enemies = [e.strip() for e in args.enemies.split(",") if e.strip()]
    result = replay(rec, advisor, enemies, args.role)
    if brief:
        count = len(result.violations)
        mark = f"✗ {count}" if count else "✓"
        print(
            f"{mark:>5}  {path.name}  ({result.hero}, {result.packets} пак.)"
        )
        for v in result.violations:
            print(f"         {v.rule}: {v.text}")
    else:
        print(path.name)
        if rec.truncated:
            print(
                "(запись не закончена: матч ещё идёт или программа закрылась)"
            )
        print(format_result(result))
    return 1 if result.violations else 0


def send_to_app(path: Path, speed: float) -> None:
    rec = load_recording(path)
    s = json.loads(settings_mod.SETTINGS_PATH.read_text(encoding="utf-8"))
    url = f"http://127.0.0.1:{s['port']}/"
    print(f"Проигрываю {path.name} в программу ({speed}x). Ctrl+C — стоп.")
    start, first = time.monotonic(), rec.packets[0][0] if rec.packets else 0
    for t, payload in rec.packets:
        delay = (t - first) / speed - (time.monotonic() - start)
        if delay > 0:
            time.sleep(delay)
        payload = {**payload, "auth": {"token": s["token"]}}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=3)
        except OSError as e:
            sys.exit(f"Не удалось отправить (программа запущена?): {e}")
        clock = (payload.get("map") or {}).get("clock_time", 0)
        print(f"\rвремя {clock // 60:>3}:{abs(clock) % 60:02d}", end="")
    print("\nГотово.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "file", nargs="?", help="файл записи (по умолчанию — последняя)"
    )
    ap.add_argument("--all", action="store_true", help="проверить все записи")
    ap.add_argument("--list", action="store_true", help="список записей")
    ap.add_argument(
        "--to-app", action="store_true", help="проиграть в программу"
    )
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument(
        "--role", default="auto", choices=["auto", "core", "support"]
    )
    ap.add_argument("--enemies", default="", help="через запятую: lion,pudge")
    args = ap.parse_args()

    files = recordings()
    if args.list:
        for p in files:
            print(f"{p.stat().st_size / 1e6:6.1f} МБ  {p.name}")
        print(f"Всего: {len(files)} · папка: {settings_mod.RECORD_DIR}")
        return
    if args.all:
        if not files:
            sys.exit(
                "Записей пока нет: сыграйте матч с запущенной программой."
            )
        code = max(run_check(p, args, brief=True) for p in files)
        sys.exit(code)
    path = Path(args.file) if args.file else (files[-1] if files else None)
    if path is None:
        sys.exit("Записей пока нет: сыграйте матч с запущенной программой.")
    if args.to_app:
        send_to_app(path, args.speed)
    else:
        sys.exit(run_check(path, args, brief=False))


if __name__ == "__main__":
    main()
