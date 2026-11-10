"""Загрузка и кэширование данных OpenDota.

Что качаем:
  /constants/patch            — номер текущего патча (для сброса кэша при новом
  патче)
  /constants/items            — все предметы: цена, компоненты, характеристики
  /constants/heroes           — герои: имя, роли, основной атрибут
  /constants/abilities        — способности: название, тип, описание (для
  подсказок)
  /heroes/{id}/itemPopularity — что покупают на герое по стадиям:
        start (до 0:00), early (0–10 мин), mid (10–25 мин, предметы от 2000),
        late (25+ мин, предметы от 4000). Данные по матчам высокого уровня.

Всё сохраняется в data_cache/. Подсказки считаются только из локального кэша,
поэтому сеть никогда не тормозит советы. Обновление идёт в фоне:
  • при смене патча — кэш полностью перекачивается;
  • иначе — если файлу больше cache_max_age_days дней (мелкие патчи вида
    7.41d).
"""

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import USER_AGENT

BASE_URL = "https://api.opendota.com/api"


class DataStore:
    def __init__(
        self,
        cache_dir: Path,
        api_key: str = "",
        max_age_days: float = 3,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or ""
        self.max_age = max_age_days * 86400
        self.on_update = on_update or (lambda: None)
        self.items: dict[str, Any] = {}
        self.heroes: dict[str, Any] = {}
        self.abilities: dict[str, Any] = {}
        self.popularity: dict[int, dict[str, Any]] = {}  # hero_id -> сборки
        self.meta: dict[str, Any] = {}
        self.status = "Данные ещё не загружены"
        self._lock = threading.Lock()
        self._jobs: queue.Queue[tuple] = queue.Queue()
        self._pending: set[tuple] = set()
        self._load_cache()
        threading.Thread(target=self._worker, daemon=True).start()

    # ---------- кэш на диске ----------
    def _path(self, name):
        return self.cache_dir / f"{name}.json"

    def _read(self, name):
        p = self._path(name)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, name, data):
        tmp = self._path(name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path(name))

    def _load_cache(self):
        self.meta = self._read("meta") or {}
        self.items = self._read("items") or {}
        self.heroes = self._read("heroes") or {}
        self.abilities = self._read("abilities") or {}
        if self.items and self.heroes:
            self.status = self._status_text()

    def _status_text(self):
        patch = self.meta.get("patch") or "?"
        ts = self.meta.get("constants_at")
        when = time.strftime("%d.%m %H:%M", time.localtime(ts)) if ts else "?"
        return f"OpenDota: патч {patch}, обновлено {when}"

    # ---------- сеть ----------
    def _get(self, path):
        url = BASE_URL + path
        if self.api_key:
            url += ("&" if "?" in url else "?") + "api_key=" + self.api_key
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))

    # ---------- фоновые задания ----------
    def _enqueue(self, job):
        with self._lock:
            if job in self._pending:
                return
            self._pending.add(job)
        self._jobs.put(job)

    def _worker(self):
        while True:
            job = self._jobs.get()
            try:
                if job == ("constants",):
                    self._refresh_constants(force=False)
                elif job == ("constants_force",):
                    self._refresh_constants(force=True)
                elif job[0] == "pop":
                    self._refresh_popularity(job[1])
            except (urllib.error.URLError, OSError, ValueError) as e:
                self.status = (
                    f"Нет связи с OpenDota ({type(e).__name__}). Работаю по "
                    "кэшу."
                )
                self.on_update()
            finally:
                with self._lock:
                    self._pending.discard(job)

    def refresh(self, force: bool = False) -> None:
        self._enqueue(("constants_force",) if force else ("constants",))

    def _refresh_constants(self, force):
        self.status = "Проверяю патч на OpenDota…"
        self.on_update()
        patches = self._get("/constants/patch")
        latest = ""
        if isinstance(patches, list) and patches:
            # Список идёт от старых патчей к новым; на всякий случай берём
            # максимальный id.
            newest = max(
                enumerate(patches),
                key=lambda p: (
                    p[1].get("id", -1) if isinstance(p[1], dict) else -1,
                    p[0],
                ),
            )[1]
            latest = (
                str(newest.get("name") or "")
                if isinstance(newest, dict)
                else ""
            )
        patch_changed = latest and latest != self.meta.get("patch")
        stale = time.time() - self.meta.get("constants_at", 0) > self.max_age
        if (
            force
            or patch_changed
            or stale
            or not self.items
            or not self.heroes
            or not self.abilities
        ):
            self.status = "Скачиваю предметы и героев…"
            self.on_update()
            items = self._get("/constants/items")
            heroes = self._get("/constants/heroes")
            self._write("items", items)
            self._write("heroes", heroes)
            self.items, self.heroes = items, heroes
            self.status = "Скачиваю описания способностей…"
            self.on_update()
            abilities = self._get("/constants/abilities")
            self._write("abilities", abilities)
            self.abilities = abilities
            if patch_changed:
                # Новый патч — старые сборки выбрасываем.
                for p in self.cache_dir.glob("pop_*.json"):
                    p.unlink(missing_ok=True)
                self.popularity.clear()
            self.meta.update(
                {
                    "patch": latest or self.meta.get("patch", ""),
                    "constants_at": time.time(),
                }
            )
            self._write("meta", self.meta)
        self.status = self._status_text()
        self.on_update()

    def _refresh_popularity(self, hero_id):
        data = self._get(f"/heroes/{hero_id}/itemPopularity")
        if isinstance(data, dict):
            data["_fetched_at"] = time.time()
            self._write(f"pop_{hero_id}", data)
            self.popularity[hero_id] = data
        self.status = self._status_text()
        self.on_update()

    # ---------- доступ для движка ----------
    def get_popularity(self, hero_id: int) -> dict[str, Any] | None:
        """Сразу отдаёт то, что есть в кэше; при необходимости запускает
        фоновое обновление.
        """
        if not hero_id:
            return None
        data = self.popularity.get(hero_id)
        if data is None:
            data = self._read(f"pop_{hero_id}")
            if data:
                self.popularity[hero_id] = data
        if (
            data is None
            or time.time() - data.get("_fetched_at", 0) > self.max_age
        ):
            self._enqueue(("pop", hero_id))
        return data

    def prefetch(self, hero_id: int) -> None:
        self.get_popularity(hero_id)

    def get_benchmarks(
        self, hero_id: int, timeout: float = 10
    ) -> dict[str, Any] | None:
        """Показатели игроков на герое (для разбора матча). Синхронно, с кэшем
        на диске.
        Вызывать из фонового потока. При ошибке сети — кэш или None."""
        name = f"bench_{hero_id}"
        cached = self._read(name)
        if (
            cached
            and time.time() - cached.get("_fetched_at", 0) < self.max_age
        ):
            return cached
        try:
            url = BASE_URL + f"/benchmarks?hero_id={int(hero_id)}"
            if self.api_key:
                url += "&api_key=" + self.api_key
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            if isinstance(data, dict):
                data["_fetched_at"] = time.time()
                self._write(name, data)
                return data
        except (urllib.error.URLError, OSError, ValueError):
            pass
        return cached

    def busy(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def is_loading(self, hero_id: int) -> bool:
        with self._lock:
            return ("pop", hero_id) in self._pending
