"""Настройки программы: хранятся в settings.json рядом с main.py."""

import json
import secrets
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
SETTINGS_PATH = APP_DIR / "settings.json"
CACHE_DIR = APP_DIR / "data_cache"
LOG_DIR = APP_DIR / "match_logs"

DEFAULTS = {
    # Порт локального сервера, куда Dota присылает данные. Если занят — поменяйте
    # и заново нажмите «Установить GSI-конфиг».
    "port": 47113,
    # Секретный токен: сервер принимает данные только с ним.
    "token": "",
    # "window" — обычное окно (удобно на втором мониторе), "overlay" — без рамки поверх игры.
    "mode": "window",
    "topmost": True,
    "alpha": 0.92,
    "voice": True,
    "voice_rate": 1.0,          # 0.8 — медленно, 1.0 — обычно, 1.2–1.4 — быстрее
    "voice_name": "",           # пусто — лучший русский голос автоматически
    # Советы тренера по стадиям: "all", "main" (только главные) или "off".
    "tips_level": "all",
    # "auto" — по ролям героя из OpenDota, "core" или "support" — вручную.
    "role": "auto",
    "geometry": "420x780+60+40",
    # Необязательный ключ OpenDota (без него лимит ~2000 запросов в день — этого хватает).
    "opendota_api_key": "",
    # Как часто перекачивать данные о сборках, даже если номер патча не поменялся.
    "cache_max_age_days": 3,
}


def load():
    data = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            data.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    if not data.get("token"):
        data["token"] = secrets.token_hex(12)
        save(data)
    return data


def save(data):
    try:
        SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
