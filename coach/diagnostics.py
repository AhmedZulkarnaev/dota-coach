"""Проверка подключения: почему программа не получает данные от Dota 2.

Чистая функция без обращения к окну и сети — её легко тестировать.
"""

from dataclasses import dataclass

OK, WARN, FAIL = "✓", "!", "✗"


@dataclass
class Check:
    """Результат одной проверки."""

    mark: str  # OK / WARN / FAIL
    title: str
    detail: str = ""
    fix: str = ""


def run_checks(
    *,
    port: int,
    server_error: str | None,
    config_status: str,
    payload_age: float | None,
    spectating: bool = False,
    items_count: int = 0,
    heroes_count: int = 0,
    store_status: str = "",
    voice_enabled: bool = True,
    has_russian_voice: bool | None = None,
) -> list[Check]:
    """Возвращает список проверок по порядку: от сервера до голоса.

    config_status — результат gsi_installer.config_status();
    payload_age — сколько секунд назад пришли последние данные от игры (None —
    ни разу).
    """
    checks: list[Check] = []

    if server_error:
        checks.append(
            Check(
                FAIL,
                "Локальный сервер не запущен",
                server_error,
                "Поменяйте «port» в settings.json, перезапустите программу и "
                "заново "
                "установите GSI-конфиг.",
            )
        )
    else:
        checks.append(
            Check(OK, f"Локальный сервер работает (127.0.0.1:{port})")
        )

    config_texts = {
        "ok": Check(OK, "GSI-конфиг установлен в папку Dota 2"),
        "stale": Check(
            FAIL,
            "GSI-конфиг устарел",
            "В файле другой порт или токен.",
            "Нажмите «Установить GSI-конфиг» и перезапустите Dota 2.",
        ),
        "missing": Check(
            FAIL,
            "GSI-конфиг не установлен",
            "В папке Dota 2 нет файла gamestate_integration_dotacoach.cfg.",
            "Нажмите «Установить GSI-конфиг» и перезапустите Dota 2.",
        ),
        "no_dota": Check(
            WARN,
            "Папка Dota 2 не найдена автоматически",
            "Возможно, игра стоит в нестандартной библиотеке Steam.",
            "Нажмите «Установить GSI-конфиг» и укажите папку «dota 2 beta» "
            "вручную.",
        ),
    }
    checks.append(config_texts.get(config_status, config_texts["missing"]))

    if payload_age is None:
        checks.append(
            Check(
                FAIL,
                "Данные от Dota 2 ещё не приходили",
                "",
                "1) В Steam: Dota 2 → Свойства → Параметры запуска: "
                "-gamestateintegration. "
                "2) Полностью перезапустите Dota 2. "
                "3) Зайдите в матч или в «Демо-герой»: в главном меню данных "
                "нет.",
            )
        )
    elif spectating:
        checks.append(
            Check(
                WARN,
                "Dota 2 в режиме зрителя или реплея",
                "Советы работают только когда вы играете сами.",
            )
        )
    elif payload_age > 40:
        checks.append(
            Check(
                WARN,
                f"Данные от Dota 2 не приходят уже {int(payload_age)} с",
                "Это нормально в главном меню.",
                "Зайдите в матч или в «Демо-герой».",
            )
        )
    else:
        checks.append(Check(OK, "Dota 2 присылает данные"))

    if items_count and heroes_count:
        checks.append(
            Check(
                OK,
                f"Данные OpenDota загружены (предметов: {items_count}, "
                f"героев: {heroes_count})",
                store_status,
            )
        )
    else:
        checks.append(
            Check(
                FAIL,
                "Нет данных OpenDota",
                store_status,
                "Нужен интернет при первом запуске. Меню ☰ → «Обновить "
                "данные OpenDota».",
            )
        )

    if not voice_enabled:
        checks.append(
            Check(
                WARN,
                "Озвучка выключена",
                "",
                "Включить: кнопка 🔊 в окне программы.",
            )
        )
    elif has_russian_voice is None:
        checks.append(Check(WARN, "Голоса Windows ещё проверяются"))
    elif has_russian_voice:
        checks.append(Check(OK, "Русский голос Windows найден"))
    else:
        checks.append(
            Check(
                FAIL,
                "Русский голос Windows не найден",
                "Озвучка будет молчать.",
                "Параметры → Время и язык → Речь → «Добавить голоса» → "
                "Русский.",
            )
        )
    return checks


def format_checks(checks: list[Check]) -> str:
    """Текст для окна «Проверка подключения»."""
    lines = ["ПРОВЕРКА ПОДКЛЮЧЕНИЯ", ""]
    for check in checks:
        lines.append(f"{check.mark} {check.title}")
        if check.detail:
            lines.append(f"    {check.detail}")
        if check.fix:
            lines.append(f"    Что сделать: {check.fix}")
    failed = sum(1 for c in checks if c.mark == FAIL)
    warned = sum(1 for c in checks if c.mark == WARN)
    if failed:
        summary = f"Нужно исправить: {failed}."
    elif warned:
        summary = "Ошибок нет, но есть замечания (отмечены «!»)."
    else:
        summary = "Всё в порядке."
    lines += [
        "",
        summary,
    ]
    return "\n".join(lines)
