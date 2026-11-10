"""Поиск папки Dota 2 и установка конфиг-файла Game State Integration.

Файл кладётся в  ...\\steamapps\\common\\dota 2
beta\\game\\dota\\cfg\\gamestate_integration\\
Это официальный механизм Valve: игра сама отправляет данные программе.
Кроме файла нужен параметр запуска Dota 2:  -gamestateintegration
"""

import re
import sys
from pathlib import Path

CFG_NAME = "gamestate_integration_dotacoach.cfg"
DOTA_REL = (
    Path("steamapps") / "common" / "dota 2 beta" / "game" / "dota" / "cfg"
)

CFG_TEMPLATE = """"Dota Coach"
{{
    "uri"           "http://127.0.0.1:{port}/"
    "timeout"       "5.0"
    "buffer"        "0.1"
    "throttle"      "0.5"
    "heartbeat"     "30.0"
    "data"
    {{
        "provider"      "1"
        "map"           "1"
        "player"        "1"
        "hero"          "1"
        "abilities"     "1"
        "items"         "1"
    }}
    "auth"
    {{
        "token"         "{token}"
    }}
}}
"""


def _steam_roots() -> list[Path]:
    roots = []
    if sys.platform == "win32":
        try:
            import winreg

            for hive, key, value in (
                (
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Valve\Steam",
                    "SteamPath",
                ),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\WOW6432Node\Valve\Steam",
                    "InstallPath",
                ),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Valve\Steam",
                    "InstallPath",
                ),
            ):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(Path(winreg.QueryValueEx(k, value)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
        ]
    else:
        roots += [
            Path.home() / ".steam" / "steam",
            Path.home() / ".local" / "share" / "Steam",
        ]
    uniq = []
    for r in roots:
        if r not in uniq:
            uniq.append(r)
    return uniq


def _library_folders(steam_root: Path) -> list[Path]:
    libs = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
        except OSError:
            pass
    return libs


def find_cfg_dirs() -> list[Path]:
    found = []
    for root in _steam_roots():
        for lib in _library_folders(root):
            p = lib / DOTA_REL
            if p.is_dir() and p not in found:
                found.append(p)
    return found


def normalize_cfg_dir(chosen: str | Path) -> Path | None:
    """Пользователь мог выбрать папку 'dota 2 beta' или 'cfg' — приводим к
    папке cfg.
    """
    p = Path(chosen)
    for cand in (
        p,
        p / "game" / "dota" / "cfg",
        p / "dota" / "cfg",
        p / "cfg",
    ):
        if cand.name == "cfg" and cand.is_dir():
            return cand
        if cand.name == "gamestate_integration" and cand.parent.name == "cfg":
            return cand.parent
    return None


def install(cfg_dir: str | Path, port: int, token: str) -> Path:
    target_dir = Path(cfg_dir) / "gamestate_integration"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / CFG_NAME
    path.write_text(
        CFG_TEMPLATE.format(port=port, token=token), encoding="utf-8"
    )
    return path


def config_status(port: int, token: str) -> str:
    """Состояние GSI-конфига: "ok", "stale" (другой порт/токен), "missing" или
    "no_dota".
    """
    dirs = find_cfg_dirs()
    if not dirs:
        return "no_dota"
    found = False
    for d in dirs:
        p = d / "gamestate_integration" / CFG_NAME
        if not p.exists():
            continue
        found = True
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if f":{port}/" in text and token in text:
            return "ok"
    return "stale" if found else "missing"


def is_installed(port: int, token: str) -> bool:
    return config_status(port, token) == "ok"
