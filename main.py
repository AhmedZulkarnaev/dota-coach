"""Dota Coach — запуск программы.

    python main.py
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging():
    """Ошибки пишутся в coach.log рядом с программой — его можно приложить к issue на GitHub."""
    path = Path(__file__).resolve().parent / "coach.log"
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    sys.excepthook = lambda *exc: logging.getLogger("dota_coach").critical("Необработанная ошибка",
                                                                            exc_info=exc)


def main():
    if sys.version_info < (3, 10):
        print("Нужен Python 3.10 или новее.")
        sys.exit(1)
    setup_logging()
    from coach import __version__
    logging.getLogger("dota_coach").info("Запуск Dota Coach %s, Python %s", __version__, sys.version.split()[0])
    if sys.platform == "win32":
        try:  # чёткий текст на экранах с масштабированием 125–150%
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    try:
        from coach.ui import CoachApp
    except ImportError as e:
        logging.getLogger("dota_coach").exception("Не удалось загрузить интерфейс")
        print("Не удалось загрузить интерфейс:", e)
        print("Переустановите Python с python.org и оставьте галочку «tcl/tk and IDLE».")
        input("Нажмите Enter для выхода…")
        sys.exit(1)
    CoachApp().run()


if __name__ == "__main__":
    main()
