"""Озвучка через голоса Windows — без установки программ и без интернета.

Два движка, используется лучший доступный:
  1. OneCore (Windows.Media.SpeechSynthesis) — современные голоса Windows 10/11
     («Microsoft Irina», «Microsoft Pavel»). Звучат заметно лучше.
  2. SAPI (System.Speech) — старый движок, запасной вариант.

Русский голос ставится так: Параметры → Время и язык → Речь → «Добавить голоса»
→ Русский.
Если русского голоса нет совсем, программа молчит (русский текст английским
голосом —
бессмысленная каша) и показывает подсказку.

Перед озвучкой текст проходит через speech_ru.speakable(): английские названия
предметов превращаются в русское звучание.
"""

import base64
import heapq
import itertools
import subprocess
import sys
import threading
import time

from .powershell_scripts import LIST_PS, ONECORE_PS, SAPI_PS
from .speech_ru import speakable

PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH = 3, 2, 1  # меньше — важнее
STALE_AFTER = 25  # фразу, которая ждала дольше, уже нет смысла говорить


def _run_ps(script: str, timeout: float = 30) -> tuple[int | None, str]:
    """Возвращает (код выхода, stdout) или (None, '') если PowerShell
    недоступен.
    """
    if sys.platform != "win32":
        return None, ""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return None, ""


def _ps_quote(text: str) -> str:
    return text.replace("'", "''").replace("\n", " ").replace("\r", " ")


class Speaker:
    def __init__(
        self,
        enabled: bool = True,
        volume: int = 90,
        rate: float = 1.0,
        voice_name: str = "",
    ) -> None:
        self.enabled = enabled
        self.volume = volume
        self.rate = rate  # 0.7 — медленно, 1.0 — обычно, 1.3 — быстро
        self.voice_name = voice_name  # пусто — первый русский голос
        self.available = sys.platform == "win32"
        self.voices: list[tuple[str, str, str]] = []  # [(движок, язык, имя)]
        self.has_russian: bool | None = None  # None — ещё не проверили
        self.onecore_ok = True
        self._heap: list[tuple[int, int, float, str, str]] = []
        self._seq = itertools.count()
        self._cv = threading.Condition()
        self._last: dict[str, float] = {}
        if self.available:
            threading.Thread(target=self._worker, daemon=True).start()
            threading.Thread(target=self.refresh_voices, daemon=True).start()

    # ---------- голоса ----------
    def refresh_voices(self) -> None:
        _code, out = _run_ps(LIST_PS)
        voices: list[tuple[str, str, str]] = []
        for line in (out or "").splitlines():
            parts = line.strip().split("|", 2)
            if len(parts) == 3:
                voices.append((parts[0], parts[1], parts[2]))
        self.voices = voices
        self.has_russian = any(
            lang.lower().startswith("ru") for _, lang, _ in voices
        )

    def russian_voices(self) -> list[tuple[str, str]]:
        seen, res = set(), []
        for engine, lang, name in self.voices:
            if lang.lower().startswith("ru") and name not in seen:
                seen.add(name)
                res.append((engine, name))
        # Современные (OneCore) — первыми
        return sorted(res, key=lambda v: v[0] != "ONECORE")

    # ---------- очередь ----------
    def say(
        self,
        text: str,
        key: str | None = None,
        cooldown: float = 15,
        priority: int = PRIORITY_NORMAL,
    ) -> None:
        """key + cooldown — чтобы одна и та же фраза не повторялась слишком
        часто.
        Фразы встают в очередь по важности и не обрывают друг друга."""
        if not (self.enabled and self.available and text):
            return
        now = time.time()
        k = key or text
        if now - self._last.get(k, 0) < cooldown:
            return
        self._last[k] = now
        with self._cv:
            # фразу с тем же ключом заменяем свежей
            self._heap = [e for e in self._heap if e[3] != k]
            heapq.heapify(self._heap)
            heapq.heappush(
                self._heap, (priority, next(self._seq), now, k, text)
            )
            while len(self._heap) > 4:  # не копим длинный хвост
                self._heap.remove(max(self._heap))
                heapq.heapify(self._heap)
            self._cv.notify()

    def test(self) -> None:
        self.say(
            "Голос работает. Следующий предмет: Black King Bar.",
            key="test",
            cooldown=0,
            priority=PRIORITY_HIGH,
        )

    def _worker(self):
        while True:
            with self._cv:
                while not self._heap:
                    self._cv.wait()
                _prio, _n, created, _k, text = heapq.heappop(self._heap)
            if time.time() - created > STALE_AFTER or not self.enabled:
                continue
            self._speak(speakable(text))

    def _speak(self, text):
        if self.has_russian is None:
            self.refresh_voices()
        if self.has_russian is False:
            return
        q = _ps_quote(text)
        chosen_engines = {
            e for e, _l, n in self.voices if n == self.voice_name
        }
        use_onecore = (
            self.onecore_ok
            and any(
                e == "ONECORE" and lang.lower().startswith("ru")
                for e, lang, _ in self.voices
            )
            and (not chosen_engines or "ONECORE" in chosen_engines)
        )
        if use_onecore:
            script = (
                ONECORE_PS.replace("__TEXT__", q)
                .replace("__VOICE__", _ps_quote(self.voice_name))
                .replace("__RATE__", f"{max(0.5, min(3.0, self.rate)):.2f}")
                .replace("__VOL__", f"{self.volume / 100:.2f}")
            )
            code, _ = _run_ps(script, timeout=60)
            if code == 0:
                return
            self.onecore_ok = False  # что-то не так с OneCore — дальше SAPI
        sapi_rate = int(round(max(-10, min(10, (self.rate - 1.0) * 10))))
        script = (
            SAPI_PS.replace("__TEXT__", q)
            .replace("__VOICE__", _ps_quote(self.voice_name))
            .replace("__SAPIRATE__", str(sapi_rate))
            .replace("__SAPIVOL__", str(int(self.volume)))
        )
        _run_ps(script, timeout=60)
