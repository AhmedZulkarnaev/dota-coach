"""Иконки предметов — такие же, как в магазине Dota.

Адрес картинки берётся из данных OpenDota (поле "img") на CDN Steam.
Каждая иконка скачивается один раз в фоне и хранится в data_cache/icons/.
Если интернета нет — просто нет иконки, на работу программы это не влияет.
"""

import queue
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import USER_AGENT

CDN = "https://cdn.cloudflare.steamstatic.com"


class IconCache:
    def __init__(
        self,
        cache_dir: Path,
        store: Any,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        self.dir = cache_dir / "icons"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.on_ready = on_ready or (lambda: None)
        self._q: queue.Queue[str] = queue.Queue()
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True).start()

    def url_for(self, item: str) -> str | None:
        img = ((self.store.items or {}).get(item) or {}).get("img") or ""
        if not img:
            return None
        if img.startswith("http"):
            return img.split("?")[0]
        return CDN + img.split("?")[0]

    def path_for(self, item: str) -> Path:
        safe = "".join(ch for ch in item if ch.isalnum() or ch == "_")
        return self.dir / f"{safe}.png"

    def get_path(self, item: str | None) -> Path | None:
        """Путь к иконке, если она уже скачана; иначе ставит загрузку в очередь
        и вернёт None.
        """
        if not item:
            return None
        path = self.path_for(item)
        if path.exists() and path.stat().st_size > 0:
            return path
        with self._lock:
            if item in self._pending or item in self._failed:
                return None
            self._pending.add(item)
        self._q.put(item)
        return None

    def _worker(self) -> None:
        while True:
            item = self._q.get()
            try:
                url = self.url_for(item)
                if not url:
                    raise ValueError("нет адреса картинки")
                req = urllib.request.Request(
                    url, headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = r.read()
                if not data.startswith(b"\x89PNG"):
                    raise ValueError("не PNG")
                tmp = self.path_for(item).with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(self.path_for(item))
                self.on_ready()
            except (urllib.error.URLError, OSError, ValueError):
                with self._lock:
                    self._failed.add(item)
            finally:
                with self._lock:
                    self._pending.discard(item)
