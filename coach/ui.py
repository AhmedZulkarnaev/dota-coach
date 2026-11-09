"""Окно подсказок (tkinter).

Два режима:
  • «Обычное окно» — с рамкой, удобно держать на втором мониторе;
  • «Оверлей» — без рамки, полупрозрачное, поверх игры (Dota в режиме «Окно без рамки»).
Перетаскивание в оверлее — мышью за любое место окна. Все настройки — кнопка ☰ или правый клик.
"""

import logging
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import gsi_installer, settings as settings_mod
from .advisor import Advisor
from .data_store import DataStore
from .game_state import parse
from .gsi_server import GSIServer
from .heroes_ru import ALIASES
from .match_log import MatchLog
from .icons import IconCache
from .match_coach import MatchCoach
from .post_match import build_report, load_log
from .voice import PRIORITY_HIGH, PRIORITY_NORMAL, Speaker
from . import __version__

LOG = logging.getLogger("dota_coach")

BG = "#14171c"
BG2 = "#1d2229"
FG = "#e6e6e6"
DIM = "#8a93a0"
GOLD = "#f2c94c"
GREEN = "#5cd65c"
RED = "#ff6b6b"
ORANGE = "#ffa94d"
CYAN = "#66d9e8"
FONT = "Segoe UI"


def fmt_gold(n):
    return f"{n:,}".replace(",", " ")


class CoachApp:
    def __init__(self):
        self.s = settings_mod.load()
        self.root = tk.Tk()
        self.root.title(f"Dota Coach {__version__}")
        self.root.report_callback_exception = self._on_tk_error
        self.root.configure(bg=BG)
        self.root.geometry(self.s.get("geometry") or "420x780+60+40")
        self.root.minsize(300, 260)

        self._payload = None
        self._payload_seq = 0
        self._seen_seq = 0
        self._last_payload_time = 0.0
        self._lock = threading.Lock()
        self._data_dirty = True
        self.gs = parse(None)
        self.advice = None
        self.enemies = []
        self.match_id = ""
        self._spoken_target = None
        self._was_full = False
        self._start_spoken_for = None
        self._drag = None
        self._log_note = ""

        self.store = DataStore(settings_mod.CACHE_DIR, self.s.get("opendota_api_key", ""),
                               self.s.get("cache_max_age_days", 3), on_update=self._mark_dirty)
        self.advisor = Advisor(self.store)
        self.icons = IconCache(settings_mod.CACHE_DIR, self.store, on_ready=self._mark_dirty)
        self._icon_imgs = {}
        self.speaker = Speaker(enabled=self.s.get("voice", True), rate=float(self.s.get("voice_rate", 1.0)),
                               voice_name=self.s.get("voice_name", ""))
        self.coach = MatchCoach()
        self._coach_msg = None
        self._coach_at = 0.0
        self._voice_warned = False
        self._report_ready = None
        self.log = MatchLog(settings_mod.LOG_DIR)
        self.server = GSIServer(int(self.s["port"]), self.s["token"], self._on_payload)

        self._build_vars()
        self._build_ui()
        self._build_menu()
        self._apply_window_mode()

        if not self.server.start():
            messagebox.showerror("Dota Coach", self.server.error)
        self.store.refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(400, self._first_run_check)
        self.root.after(200, self._tick)

    # ---------- связь с другими потоками ----------
    def _on_payload(self, data):          # поток GSI-сервера
        with self._lock:
            self._payload = data
            self._payload_seq += 1
            self._last_payload_time = time.time()

    def _mark_dirty(self):                # поток загрузки данных
        self._data_dirty = True

    # ---------- построение интерфейса ----------
    def _build_vars(self):
        self.v_topmost = tk.BooleanVar(value=self.s.get("topmost", True))
        self.v_voice = tk.BooleanVar(value=self.s.get("voice", True))
        self.v_mode = tk.StringVar(value=self.s.get("mode", "window"))
        self.v_alpha = tk.DoubleVar(value=float(self.s.get("alpha", 0.92)))
        self.v_role = tk.StringVar(value=self.s.get("role", "auto"))
        self.v_compact = tk.BooleanVar(value=self.s.get("compact", False))
        self.v_tips = tk.StringVar(value=self.s.get("tips_level", "all"))
        self.v_rate = tk.DoubleVar(value=float(self.s.get("voice_rate", 1.0)))
        self.v_voice_name = tk.StringVar(value=self.s.get("voice_name", ""))

    def _label(self, parent, size=10, color=FG, bold=False, wrap=True, **kw):
        lbl = tk.Label(parent, bg=kw.pop("bg", BG), fg=color, anchor="w", justify="left",
                       font=(FONT, size, "bold" if bold else "normal"), **kw)
        if wrap:
            self._wrapped.append(lbl)
        return lbl

    def _build_ui(self):
        self._wrapped = []
        r = self.root
        top = tk.Frame(r, bg=BG2)
        top.pack(fill="x")
        self.lbl_status = self._label(top, 9, DIM, bg=BG2, wrap=False, text="● запуск…")
        self.lbl_status.pack(side="left", padx=8, pady=4)
        for txt, cmd in (("☰", self._show_menu), ("🔊", self._toggle_voice), ("Враги", self.open_enemies)):
            b = tk.Button(top, text=txt, command=cmd, bg=BG2, fg=FG, bd=0, relief="flat",
                          activebackground="#2b323c", activeforeground=FG, font=(FONT, 9),
                          padx=8, cursor="hand2")
            b.pack(side="right", padx=2, pady=2)
            if txt == "🔊":
                self.btn_voice = b

        body = tk.Frame(r, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        self.body = body

        self.lbl_hero = self._label(body, 12, FG, bold=True, text="Dota Coach")
        self.lbl_hero.pack(fill="x")
        self.lbl_clock = self._label(body, 9, DIM, text="Жду данные от Dota 2…")
        self.lbl_clock.pack(fill="x")
        self.lbl_gold = self._label(body, 11, GOLD, bold=True, text="")
        self.lbl_gold.pack(fill="x", pady=(4, 0))
        self.lbl_slots = self._label(body, 9, DIM, text="")
        self.lbl_slots.pack(fill="x", pady=(0, 6))
        self.lbl_coach = tk.Label(body, bg="#1f3326", fg="#c9f2c7", anchor="w", justify="left",
                                  font=(FONT, 10), padx=6, pady=4, text="")
        self._wrapped.append(self.lbl_coach)
        self.coach_anchor = tk.Frame(body, bg=BG)
        self.coach_anchor.pack(fill="x")

        # Плашка «нет места» — над целью, красным, чтобы её нельзя было пропустить.
        self.lbl_free = tk.Label(body, bg="#4a1f24", fg="#ffd7d7", anchor="w", justify="left",
                                 font=(FONT, 10, "bold"), padx=6, pady=4, text="")
        self._wrapped.append(self.lbl_free)
        self._label(body, 8, DIM, text="СЛЕДУЮЩИЙ ПРЕДМЕТ", wrap=False).pack(fill="x")
        self.free_anchor = tk.Frame(body, bg=BG)      # место, куда встаёт плашка
        self.free_anchor.pack(fill="x")
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x")
        self.lbl_icon = tk.Label(row, bg=BG, bd=0)
        self.lbl_icon.pack(side="left", padx=(0, 8))
        self.lbl_target = self._label(row, 15, GOLD, bold=True, text="—")
        self.lbl_target.pack(side="left", fill="x", expand=True)
        self.bar = tk.Canvas(body, height=10, bg="#2b323c", highlightthickness=0)
        self.bar.pack(fill="x", pady=(4, 2))
        self.lbl_need = self._label(body, 11, FG, bold=True, text="")
        self.lbl_need.pack(fill="x")
        self.lbl_buy = self._label(body, 10, GREEN, text="")
        self.lbl_buy.pack(fill="x", pady=(2, 0))
        self.lbl_parts = self._label(body, 9, DIM, text="")
        self.lbl_parts.pack(fill="x")
        # Срочные подсказки по способностям видны даже в компактном режиме.
        self.lbl_ab_live = self._label(body, 10, CYAN, bold=True, text="")
        self.lbl_ab_live.pack(fill="x", pady=(4, 0))

        self.detail = tk.Frame(body, bg=BG)
        self.detail.pack(fill="both", expand=True)
        self._label(self.detail, 8, DIM, text="ЧТО ДАЁТ", wrap=False).pack(fill="x", pady=(8, 0))
        self.lbl_what = self._label(self.detail, 10, FG, text="")
        self.lbl_what.pack(fill="x")
        self._label(self.detail, 8, DIM, text="ПОЧЕМУ СЕЙЧАС", wrap=False).pack(fill="x", pady=(6, 0))
        self.lbl_why = self._label(self.detail, 10, FG, text="")
        self.lbl_why.pack(fill="x")
        self.lbl_situ = self._label(self.detail, 9, ORANGE, text="")
        self.lbl_situ.pack(fill="x", pady=(6, 0))
        self.lbl_rem = self._label(self.detail, 9, CYAN, text="")
        self.lbl_rem.pack(fill="x", pady=(4, 0))
        self.lbl_next = self._label(self.detail, 9, DIM, text="")
        self.lbl_next.pack(fill="x", pady=(6, 0))
        self.lbl_enemies = self._label(self.detail, 9, DIM, text="", cursor="hand2")
        self.lbl_enemies.pack(fill="x", pady=(4, 0))
        self.lbl_enemies.bind("<Button-1>", lambda e: self.open_enemies())
        self.ab_title = self._label(self.detail, 8, DIM, text="", wrap=False)
        self.ab_title.pack(fill="x", pady=(10, 0))
        self.ab_text = tk.Text(self.detail, bg=BG, fg=FG, relief="flat", wrap="word", height=6,
                               font=(FONT, 9), highlightthickness=0, cursor="arrow")
        self.ab_text.tag_configure("name", foreground=GOLD, font=(FONT, 9, "bold"))
        self.ab_text.tag_configure("state", foreground=DIM)
        self.ab_text.tag_configure("ready", foreground=GREEN)
        self.ab_text.pack(fill="both", expand=True)

        foot = tk.Frame(r, bg=BG2)
        foot.pack(fill="x", side="bottom")
        self.lbl_data = self._label(foot, 8, DIM, bg=BG2, wrap=False, text="")
        self.lbl_data.pack(side="left", padx=8, pady=2)
        ttk.Sizegrip(foot).pack(side="right")

        r.bind("<Configure>", self._on_resize)
        r.bind_all("<Button-3>", lambda e: self._show_menu(e))
        r.bind_all("<ButtonPress-1>", self._drag_start, add="+")
        r.bind_all("<B1-Motion>", self._drag_move, add="+")
        r.bind_all("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None), add="+")
        self._apply_compact()

    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Враги в этом матче…", command=self.open_enemies)
        m.add_separator()
        m.add_radiobutton(label="Обычное окно (второй монитор)", variable=self.v_mode,
                          value="window", command=self._apply_window_mode)
        m.add_radiobutton(label="Оверлей поверх игры", variable=self.v_mode,
                          value="overlay", command=self._apply_window_mode)
        m.add_checkbutton(label="Поверх всех окон", variable=self.v_topmost, command=self._apply_window_mode)
        m.add_checkbutton(label="Компактно (без объяснений)", variable=self.v_compact,
                          command=self._apply_compact)
        alpha = tk.Menu(m, tearoff=0)
        for a in (1.0, 0.92, 0.85, 0.75, 0.65, 0.5):
            alpha.add_radiobutton(label=f"{int(a * 100)}%", variable=self.v_alpha, value=a,
                                  command=self._apply_window_mode)
        m.add_cascade(label="Непрозрачность", menu=alpha)
        role = tk.Menu(m, tearoff=0)
        for val, txt in (("auto", "Определять автоматически"), ("core", "Кор (керри, мид, оффлейн)"),
                         ("support", "Саппорт")):
            role.add_radiobutton(label=txt, variable=self.v_role, value=val, command=self._save_and_redraw)
        m.add_cascade(label="Моя роль", menu=role)
        tips = tk.Menu(m, tearoff=0)
        for val, txt in (("all", "Все советы по стадиям и таймингам"),
                         ("main", "Только главные (смена стадий, ошибки)"), ("off", "Выключить")):
            tips.add_radiobutton(label=txt, variable=self.v_tips, value=val, command=self._save)
        m.add_cascade(label="Советы тренера", menu=tips)
        m.add_checkbutton(label="Озвучка голосом", variable=self.v_voice, command=self._apply_voice)
        self.voice_menu = tk.Menu(m, tearoff=0, postcommand=self._fill_voice_menu)
        m.add_cascade(label="Голос", menu=self.voice_menu)
        m.add_separator()
        m.add_command(label="Установить GSI-конфиг в Dota 2…", command=self.install_gsi)
        m.add_command(label="Обновить данные OpenDota", command=lambda: self.store.refresh(force=True))
        m.add_command(label="Разбор последнего матча", command=self.open_last_report)
        m.add_command(label="Папка с разборами матчей", command=self.open_reports_folder)
        m.add_separator()
        m.add_command(label="Как подключить Dota 2", command=self.show_help)
        m.add_separator()
        m.add_command(label="Выход", command=self.quit)
        self.menu = m

    # ---------- окно ----------
    def _show_menu(self, event=None):
        x = event.x_root if event else self.root.winfo_pointerx()
        y = event.y_root if event else self.root.winfo_pointery()
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def _apply_window_mode(self):
        overlay = self.v_mode.get() == "overlay"
        if overlay != getattr(self, "_overlay_now", None):
            # В Windows смена рамки применяется надёжно только через скрытие/показ окна.
            geo = self.root.geometry()
            self.root.withdraw()
            self.root.overrideredirect(overlay)
            self.root.geometry(geo)
            self.root.deiconify()
            self._overlay_now = overlay
        self.root.attributes("-topmost", bool(self.v_topmost.get() or overlay))
        self.root.attributes("-alpha", float(self.v_alpha.get()))
        self._save()

    def _apply_compact(self):
        if self.v_compact.get():
            self.detail.pack_forget()
        else:
            self.detail.pack(fill="both", expand=True)
        self._save()

    def _apply_voice(self):
        self.speaker.enabled = bool(self.v_voice.get())
        self.btn_voice.configure(text="🔊" if self.speaker.enabled else "🔇")
        if self.speaker.enabled and self.speaker.has_russian is False:
            self._warn_no_voice()
        self._save()

    def _warn_no_voice(self):
        self._voice_warned = True
        messagebox.showinfo("Озвучка", NO_VOICE_HELP)

    def _fill_voice_menu(self):
        vm = self.voice_menu
        vm.delete(0, "end")
        vm.add_command(label="▶ Проверить голос", command=self.speaker.test)
        vm.add_separator()
        for val, txt in ((0.8, "Медленно"), (1.0, "Обычная скорость"), (1.2, "Быстрее"), (1.4, "Быстро")):
            vm.add_radiobutton(label=txt, variable=self.v_rate, value=val, command=self._apply_voice_opts)
        vm.add_separator()
        voices = self.speaker.russian_voices()
        if not voices:
            vm.add_command(label="Русских голосов не найдено — как установить", command=self._warn_no_voice)
        else:
            vm.add_radiobutton(label="Автоматически (лучший)", variable=self.v_voice_name, value="",
                               command=self._apply_voice_opts)
            for engine, name in voices:
                kind = "современный" if engine == "ONECORE" else "старый"
                vm.add_radiobutton(label=f"{name} ({kind})", variable=self.v_voice_name, value=name,
                                   command=self._apply_voice_opts)
        vm.add_command(label="Обновить список голосов",
                       command=lambda: threading.Thread(target=self.speaker.refresh_voices, daemon=True).start())

    def _apply_voice_opts(self):
        self.speaker.rate = float(self.v_rate.get())
        self.speaker.voice_name = self.v_voice_name.get()
        self.speaker.onecore_ok = True
        self._save()
        self.speaker.test()

    def _toggle_voice(self):
        self.v_voice.set(not self.v_voice.get())
        self._apply_voice()

    def _on_resize(self, event):
        if event.widget is self.root:
            w = max(200, self.body.winfo_width() - 4)
            for lbl in self._wrapped:
                lbl.configure(wraplength=w)
            self._draw_bar()

    def _drag_start(self, event):
        w = event.widget
        if self.v_mode.get() != "overlay" or not hasattr(w, "winfo_toplevel") \
                or isinstance(w, (tk.Button, ttk.Sizegrip)):
            return
        if w.winfo_toplevel() is not self.root:
            return
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event):
        if self._drag and self.v_mode.get() == "overlay":
            dx, dy = self._drag
            self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _save_and_redraw(self):
        self._save()
        self._data_dirty = True

    def _save(self):
        self.s.update({"topmost": bool(self.v_topmost.get()), "voice": bool(self.v_voice.get()),
                       "mode": self.v_mode.get(), "alpha": float(self.v_alpha.get()),
                       "role": self.v_role.get(), "compact": bool(self.v_compact.get()),
                       "tips_level": self.v_tips.get(), "voice_rate": float(self.v_rate.get()),
                       "voice_name": self.v_voice_name.get(),
                       "geometry": self.root.geometry()})
        settings_mod.save(self.s)

    def quit(self):
        self._save()
        self.server.stop()
        self.root.destroy()

    # ---------- основной цикл ----------
    def _tick(self):
        try:
            self._process()
        except Exception:
            # Не падаем молча: пишем в coach.log и продолжаем работать.
            LOG.exception("Ошибка в основном цикле")
            self._log_note = "Произошла ошибка — подробности в файле coach.log"
        finally:
            self.root.after(200, self._tick)

    def _on_tk_error(self, exc, val, tb):
        LOG.error("Ошибка интерфейса", exc_info=(exc, val, tb))
        self._log_note = "Произошла ошибка — подробности в файле coach.log"

    def _process(self):
        with self._lock:
            payload, seq, last_t = self._payload, self._payload_seq, self._last_payload_time
        new_data = seq != self._seen_seq
        if new_data:
            self._seen_seq = seq
            self.gs = parse(payload)
            if self.gs.match_id and self.gs.match_id != self.match_id:
                self._new_match(self.gs.match_id)
            if self.gs.hero_id > 0:
                self.store.prefetch(self.gs.hero_id)
        if new_data or self._data_dirty:
            self._data_dirty = False
            self.advice = self.advisor.advise(self.gs, self.enemies, self.v_role.get())
            saved = self.log.update(self.gs, self.advice)
            if saved:
                self._log_note = "Матч окончен — готовлю разбор…"
                self._start_report(saved)
            self._render()
            self._voice()
            if new_data:
                self._coach_step()
        self._render_coach()
        self._render_status(last_t)
        if self._report_ready:
            title, text = self._report_ready
            self._report_ready = None
            self._log_note = "Разбор матча готов (☰ → Разбор последнего матча)"
            ReportWindow(self.root, title, text, self.open_reports_folder)
            self.speaker.say("Матч окончен. Разбор готов.", key="report", cooldown=60)
        if (not self._voice_warned and self.speaker.enabled and self.speaker.has_russian is False
                and not self.s.get("no_voice_warned")):
            self.s["no_voice_warned"] = True
            settings_mod.save(self.s)
            self._warn_no_voice()

    # ---------- разбор после матча ----------
    def _start_report(self, log_path):
        role = self.advisor.role(self.gs, self.v_role.get()) if self.gs.hero_id > 0 else "core"
        hero_title = self.advisor.hero_title(self.gs) if self.gs.hero_id > 0 else ""
        hero_id = self.gs.hero_id

        def work():
            try:
                bench = self.store.get_benchmarks(hero_id) if hero_id > 0 else None
                text, _tips = build_report(load_log(log_path), self.advisor.db, hero_title, role, bench)
                log_path.with_suffix(".txt").write_text(text, encoding="utf-8")
                self._report_ready = ("Разбор матча", text)
            except Exception:
                LOG.exception("Не удалось построить разбор матча")
        threading.Thread(target=work, daemon=True).start()

    def open_last_report(self):
        files = sorted(settings_mod.LOG_DIR.glob("match_*.json"), key=lambda p: p.stat().st_mtime) \
            if settings_mod.LOG_DIR.exists() else []
        if not files:
            messagebox.showinfo("Разбор матча", "Пока нет ни одного сыгранного матча с программой.")
            return
        path = files[-1]
        txt = path.with_suffix(".txt")
        if txt.exists():
            text = txt.read_text(encoding="utf-8")
        else:
            text, _ = build_report(load_log(path), self.advisor.db)
        ReportWindow(self.root, "Разбор матча", text, self.open_reports_folder)

    def open_reports_folder(self):
        settings_mod.LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(settings_mod.LOG_DIR))
            else:
                subprocess.Popen(["xdg-open", str(settings_mod.LOG_DIR)])
        except OSError:
            messagebox.showinfo("Папка с разборами", str(settings_mod.LOG_DIR))

    # ---------- советы тренера ----------
    def _coach_step(self):
        role = self.advisor.role(self.gs, self.v_role.get()) if self.gs.hero_id > 0 else "core"
        msg = self.coach.update(self.gs, role, self.v_tips.get())
        if not msg:
            return
        self._coach_msg, self._coach_at = msg, time.time()
        self.speaker.say(msg.text, key="coach:" + msg.text, cooldown=120,
                         priority=PRIORITY_HIGH if msg.priority <= 1 else PRIORITY_NORMAL)

    def _render_coach(self):
        msg = self._coach_msg
        age = time.time() - self._coach_at
        if not msg or age > 180 or self.v_tips.get() == "off":
            if self.lbl_coach.winfo_ismapped():
                self.lbl_coach.pack_forget()
            return
        clock = f"{msg.clock // 60}:{msg.clock % 60:02d}" if msg.clock >= 0 else "до горна"
        self.lbl_coach.configure(text=f"💬 Тренер ({clock}): {msg.text}",
                                 fg="#c9f2c7" if age < 60 else DIM)
        if not self.lbl_coach.winfo_ismapped():
            self.lbl_coach.pack(in_=self.coach_anchor, fill="x", pady=(0, 6))

    def _new_match(self, match_id):
        self.match_id = match_id
        self.enemies = []
        self._spoken_target = None
        self._was_full = False
        self._log_note = ""
        self._coach_msg = None

    # ---------- отрисовка ----------
    def _render_status(self, last_t):
        age = time.time() - last_t if last_t else None
        if self.server.error:
            txt, col = "● сервер не запущен", RED
        elif age is None:
            txt, col = "● нет данных от Dota", RED
        elif age > 40:
            txt, col = f"● нет данных {int(age)} с", ORANGE
        elif self.gs.spectating:
            txt, col = "● режим зрителя не поддерживается", ORANGE
        else:
            txt, col = "● Dota подключена", GREEN
        self.lbl_status.configure(text=txt, fg=col)
        self.lbl_data.configure(text=self._log_note or self.store.status)

    def _set_free(self, text):
        """Показать/спрятать красную плашку «нет места»."""
        self.lbl_free.configure(text=text)
        if text:
            self.lbl_free.pack(in_=self.free_anchor, fill="x", pady=(2, 4))
        else:
            self.lbl_free.pack_forget()

    def _render_abilities(self, a):
        self.lbl_ab_live.configure(text="\n".join("» " + x for x in a.ability_live))
        self.ab_title.configure(text="СПОСОБНОСТИ — КОГДА ИСПОЛЬЗОВАТЬ" if a.ability_lines else "")
        t = self.ab_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for title, tip, state in a.ability_lines:
            t.insert("end", title, "name")
            t.insert("end", f"  {state}\n", "ready" if state == "готова" else "state")
            t.insert("end", tip + "\n")
        t.configure(state="disabled", height=max(1, min(14, 2 * len(a.ability_lines))))

    def _render(self):
        a, gs = self.advice, self.gs
        if a is None:
            return
        if not gs.valid or not a.hero_title:
            self.lbl_hero.configure(text="Dota Coach")
            self.lbl_clock.configure(text=a.message or "Жду данные от Dota 2…")
            for lbl in (self.lbl_gold, self.lbl_slots, self.lbl_need, self.lbl_buy,
                        self.lbl_parts, self.lbl_what, self.lbl_why,
                        self.lbl_situ, self.lbl_rem, self.lbl_next, self.lbl_enemies):
                lbl.configure(text="")
            self._set_free("")
            self._show_icon(None)
            self.lbl_target.configure(text="—")
            self._draw_bar(0)
            self._render_abilities(a)
            return

        pause = "  (пауза)" if gs.paused else ""
        dead = f"  · мёртв, {gs.respawn_seconds} с" if not gs.alive else ""
        self.lbl_hero.configure(text=f"{a.hero_title} · ур. {gs.hero_level}")
        self.lbl_clock.configure(text=f"{gs.clock_str} · {a.stage_title}{pause}{dead}   "
                                      f"KDA {gs.kills}/{gs.deaths}/{gs.assists} · LH {gs.last_hits}")
        self.lbl_gold.configure(text=f"Золото: {fmt_gold(gs.gold)}")
        slots = f"Слоты: {a.slots_main}/6 · рюкзак {a.slots_backpack}/3"
        if a.slots_stash:
            slots += f" · в тайнике {a.slots_stash}"
        full = a.slots_main >= 6
        self.lbl_slots.configure(text=slots + ("  — мест нет" if full and a.slots_backpack >= 3 else ""),
                                 fg=RED if full and a.slots_backpack >= 3 else ORANGE if full else DIM)
        free_text = ""

        if a.status in ("no_data", "loading", "wait"):
            self.lbl_target.configure(text="…")
            self.lbl_need.configure(text=a.message, fg=DIM)
            for lbl in (self.lbl_buy, self.lbl_parts, self.lbl_what, self.lbl_why, self.lbl_next):
                lbl.configure(text="")
            self._draw_bar(0)
        elif a.status == "start":
            self.lbl_target.configure(text=a.target_title)
            self.lbl_need.configure(text=f"Итого: {fmt_gold(a.target_cost)} из {fmt_gold(gs.gold)}", fg=FG)
            self.lbl_buy.configure(text="Купить: " + ", ".join(t for t, _ in a.start_bundle) if a.start_bundle else "")
            self.lbl_parts.configure(text="")
            self.lbl_what.configure(text="Реген, чтобы стоять на линии, и немного статов.")
            self.lbl_why.configure(text=a.why)
            self.lbl_next.configure(text="Потом копите на: " + " → ".join(a.next_items) if a.next_items else "")
            self._draw_bar(1.0 if a.start_bundle else 0)
        elif a.status == "done":
            self.lbl_target.configure(text=a.target_title)
            self.lbl_need.configure(text="", fg=FG)
            self.lbl_buy.configure(text="")
            self.lbl_parts.configure(text="")
            self.lbl_what.configure(text="")
            self.lbl_why.configure(text=a.why)
            self.lbl_next.configure(text="")
            self._draw_bar(1.0)
        else:
            self.lbl_target.configure(text=f"{a.target_title} — {fmt_gold(a.target_cost)}")
            if a.can_buy_full:
                self.lbl_need.configure(text="Золота хватает — купите сейчас!", fg=GREEN)
            elif a.can_buy_with_sell:
                self.lbl_need.configure(text=f"Хватит, если продать лишнее (+{fmt_gold(a.free_up_refund)})",
                                        fg=GREEN)
            else:
                self.lbl_need.configure(text=f"Не хватает: {fmt_gold(a.remaining - gs.gold)} "
                                             f"(осталось потратить {fmt_gold(a.remaining)})", fg=FG)
            if a.can_buy_full:
                self.lbl_buy.configure(text="Купить: " + ", ".join(t for t, _ in a.buy_now), fg=GREEN)
            elif a.parts_no_room:
                self.lbl_buy.configure(text="Части пока некуда положить: они останутся в тайнике и не будут "
                                            "работать. Копите и купите предмет целиком.", fg=ORANGE)
            elif a.buy_now:
                self.lbl_buy.configure(text="Можно купить уже сейчас: "
                                            + ", ".join(f"{t} ({fmt_gold(c)})" for t, c in a.buy_now), fg=GREEN)
            else:
                self.lbl_buy.configure(text="")
            if a.free_up:
                refund = f" (+{fmt_gold(a.free_up_refund)} золота)" if a.free_up_refund else ""
                free_text = f"⚠ Сначала освободите место: {a.free_up_text}{refund}."
            self.lbl_parts.configure(text="Осталось собрать: " + ", ".join(t for t, _ in a.missing))
            self.lbl_what.configure(text=a.what)
            self.lbl_why.configure(text=a.why)
            self.lbl_next.configure(text="Дальше по плану: " + " → ".join(a.next_items) if a.next_items else "")
            frac = (a.owned_value + gs.gold) / a.target_cost if a.target_cost else 0
            self._draw_bar(min(1.0, frac))

        self._set_free(free_text)
        self._show_icon(a.target if a.status == "ok" else None)
        self.lbl_situ.configure(text="\n".join(f"⚠ {t}: {r}" for t, r in a.situational))
        self.lbl_rem.configure(text="\n".join("• " + x for x in a.reminders))
        if self.enemies:
            names = [self._hero_title(s) for s in self.enemies]
            extra = f" — {a.enemy_summary}" if a.enemy_summary else ""
            self.lbl_enemies.configure(text="Враги: " + ", ".join(names) + extra + "  (изменить)")
        else:
            self.lbl_enemies.configure(text="Враги не указаны — нажмите, чтобы ввести (советы станут точнее)")
        self._render_abilities(a)

    def _show_icon(self, item):
        path = self.icons.get_path(item) if item else None
        img = None
        if path:
            img = self._icon_imgs.get(item)
            if img is None:
                try:
                    img = tk.PhotoImage(file=str(path))
                    if img.width() > 64:                 # иконки 88×64 → 44×32
                        img = img.subsample(2)
                    self._icon_imgs[item] = img          # Tk теряет картинку без ссылки на неё
                except tk.TclError:
                    img = None
        if img is not None:
            self.lbl_icon.configure(image=img)
            if not self.lbl_icon.winfo_ismapped():
                self.lbl_icon.pack(side="left", padx=(0, 8), before=self.lbl_target)
        else:
            self.lbl_icon.configure(image="")
            self.lbl_icon.pack_forget()

    def _draw_bar(self, frac=None):
        if frac is not None:
            self._bar_frac = frac
        frac = getattr(self, "_bar_frac", 0)
        self.bar.delete("all")
        w = self.bar.winfo_width()
        if w > 1 and frac > 0:
            self.bar.create_rectangle(0, 0, int(w * frac), 10, fill=GREEN if frac >= 1 else GOLD, width=0)

    def _hero_title(self, short):
        h = self.advisor.heroes_by_short.get(short) or {}
        return h.get("localized_name") or short.replace("_", " ").title()

    # ---------- голос ----------
    def _voice(self):
        a = self.advice
        if not a or not self.speaker.enabled:
            return
        if a.status == "start" and a.start_bundle and self._start_spoken_for != self.match_id:
            self._start_spoken_for = self.match_id
            self.speaker.say("Стартовая закупка: " + ", ".join(t for t, _ in a.start_bundle[:4]))
        if a.status != "ok":
            return
        low_hp = next((x for x in a.ability_live if x.startswith("Мало здоровья")), None)
        if low_hp:
            self.speaker.say(low_hp.split(" — ", 1)[-1], key="lowhp", cooldown=25, priority=PRIORITY_HIGH)
        if a.target != self._spoken_target:
            self._spoken_target = a.target
            self._was_full = a.can_buy_full
            extra = ". Сначала освободите место" if a.free_up else ""
            self.speaker.say(f"Следующий предмет: {a.target_title}{extra}", key="target:" + a.target, cooldown=60)
            return
        if a.can_buy_full and not self._was_full:
            extra = ", но сначала освободите слот" if a.free_up else ""
            self.speaker.say(f"Хватает золота на {a.target_title}{extra}", key="full:" + a.target, cooldown=45)
        self._was_full = a.can_buy_full

    # ---------- враги ----------
    def open_enemies(self):
        EnemyPicker(self)

    def set_enemies(self, shorts):
        self.enemies = list(shorts)[:5]
        self._data_dirty = True

    # ---------- настройка GSI ----------
    def _first_run_check(self):
        if self.s.get("gsi_ok_shown"):
            return
        if gsi_installer.is_installed(self.s["port"], self.s["token"]):
            self.s["gsi_ok_shown"] = True
            settings_mod.save(self.s)
            return
        if messagebox.askyesno("Dota Coach — первый запуск",
                               "Нужно один раз установить конфиг Game State Integration в папку Dota 2 "
                               "(официальный способ Valve, безопасен для аккаунта).\n\nСделать это сейчас?"):
            self.install_gsi()

    def install_gsi(self):
        dirs = gsi_installer.find_cfg_dirs()
        target = None
        if dirs:
            if len(dirs) == 1 or messagebox.askyesno("Папка Dota 2", f"Найдена папка:\n{dirs[0]}\n\nИспользовать её?"):
                target = dirs[0]
        if target is None:
            messagebox.showinfo("Папка Dota 2",
                                "Укажите папку игры, например:\n"
                                r"C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta")
            chosen = filedialog.askdirectory(title="Папка dota 2 beta")
            if not chosen:
                return
            target = gsi_installer.normalize_cfg_dir(chosen)
            if target is None:
                messagebox.showerror("Dota Coach", "В этой папке не найдено game\\dota\\cfg. "
                                                   "Выберите папку «dota 2 beta».")
                return
        try:
            path = gsi_installer.install(target, self.s["port"], self.s["token"])
        except OSError as e:
            messagebox.showerror("Dota Coach", f"Не удалось записать файл: {e}\n"
                                               "Попробуйте запустить программу от имени администратора.")
            return
        self.s["gsi_ok_shown"] = True
        settings_mod.save(self.s)
        messagebox.showinfo("Готово", f"Конфиг установлен:\n{path}\n\n" + LAUNCH_HELP)

    def show_help(self):
        messagebox.showinfo("Как подключить Dota 2", LAUNCH_HELP)

    def run(self):
        self.root.mainloop()


NO_VOICE_HELP = (
    "Русский голос в Windows не найден, поэтому озвучка молчит "
    "(русский текст английским голосом звучит как каша).\n\n"
    "Как установить (бесплатно, 1–2 минуты):\n"
    "1. Параметры → Время и язык → Речь.\n"
    "2. «Голоса» → «Добавить голоса» → выберите «Русский» → Добавить.\n"
    "3. Перезапустите Dota Coach.\n\n"
    "Потом в меню ☰ → Голос можно выбрать голос (Ирина или Павел) и скорость."
)


LAUNCH_HELP = (
    "Остался один шаг — параметр запуска:\n"
    "1. Steam → Библиотека → правый клик по Dota 2 → Свойства.\n"
    "2. Вкладка «Общие» → «Параметры запуска».\n"
    "3. Впишите:  -gamestateintegration\n"
    "4. Перезапустите Dota 2 (если она была открыта).\n\n"
    "Для оверлея поверх игры: Dota → Настройки → Видео → «Окно без рамки».\n"
    "С двумя мониторами проще держать окно программы на втором."
)


class ReportWindow:
    """Окно с разбором матча."""

    def __init__(self, root, title, text, open_folder):
        win = tk.Toplevel(root)
        win.title(title)
        win.configure(bg=BG)
        win.geometry("620x640")
        win.attributes("-topmost", True)
        frame = tk.Frame(win, bg=BG)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        sb = tk.Scrollbar(frame)
        sb.pack(side="right", fill="y")
        t = tk.Text(frame, bg=BG, fg=FG, wrap="word", relief="flat", font=(FONT, 10),
                    yscrollcommand=sb.set, highlightthickness=0, padx=6, pady=6)
        t.pack(side="left", fill="both", expand=True)
        sb.configure(command=t.yview)
        t.tag_configure("h", foreground=GOLD, font=(FONT, 10, "bold"))
        t.tag_configure("title", foreground=GOLD, font=(FONT, 13, "bold"))
        lines = text.splitlines()
        for i, line in enumerate(lines):
            is_header = i > 0 and not lines[i - 1].strip() and line.strip() \
                and not line.lstrip().startswith(("•", "1.", "2.", "3.", "("))
            tag = "title" if i == 0 else "h" if is_header else None
            t.insert("end", line + "\n", tag or ())
        t.configure(state="disabled")
        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        for txt, cmd in (("Закрыть", win.destroy), ("Открыть папку с разборами", open_folder)):
            tk.Button(btns, text=txt, command=cmd, bg=BG2, fg=FG, relief="flat", padx=10,
                      activebackground="#2b323c", activeforeground=FG).pack(side="right", padx=3)


class EnemyPicker:
    """Окно выбора героев врага: поиск по-английски, по-русски и по сленгу (па, ам, сф…)."""

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("Враги в этом матче")
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)
        self.win.geometry("470x380")
        self.selected = list(app.enemies)
        self.heroes = self._hero_list()

        tk.Label(self.win, text="Начните вводить имя (можно по-русски: «па», «лион», «сф»). "
                                "Enter или двойной клик — добавить.",
                 bg=BG, fg=DIM, font=(FONT, 9), wraplength=440, justify="left").pack(fill="x", padx=10, pady=(8, 4))
        self.q = tk.StringVar()
        e = tk.Entry(self.win, textvariable=self.q, font=(FONT, 11), bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        e.pack(fill="x", padx=10)
        e.focus_set()
        self.q.trace_add("write", lambda *a: self._filter())

        lists = tk.Frame(self.win, bg=BG)
        lists.pack(fill="both", expand=True, padx=10, pady=8)
        self.lb = tk.Listbox(lists, bg=BG2, fg=FG, selectbackground="#3a4250", font=(FONT, 10),
                             relief="flat", activestyle="none")
        self.lb.pack(side="left", fill="both", expand=True)
        right = tk.Frame(lists, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tk.Label(right, text="Выбрано (до 5):", bg=BG, fg=DIM, font=(FONT, 9)).pack(anchor="w")
        self.sel = tk.Listbox(right, bg=BG2, fg=GOLD, font=(FONT, 10), relief="flat", height=6, activestyle="none")
        self.sel.pack(fill="both", expand=True)

        btns = tk.Frame(self.win, bg=BG)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        for txt, cmd in (("Готово", self._done), ("Очистить", self._clear), ("Убрать выбранного", self._remove)):
            tk.Button(btns, text=txt, command=cmd, bg=BG2, fg=FG, relief="flat", padx=10,
                      activebackground="#2b323c", activeforeground=FG).pack(side="right", padx=3)

        e.bind("<Return>", lambda ev: self._add_first())
        e.bind("<Down>", lambda ev: (self.lb.focus_set(), self.lb.selection_set(0)))
        self.lb.bind("<Double-Button-1>", lambda ev: self._add_selected())
        self.lb.bind("<Return>", lambda ev: self._add_selected())
        self.sel.bind("<Double-Button-1>", lambda ev: self._remove())
        self.win.bind("<Escape>", lambda ev: self._done())
        self._filter()
        self._refresh_sel()

    def _hero_list(self):
        res = []
        heroes = self.app.advisor.heroes_by_short
        shorts = set(heroes) or set(ALIASES)
        for s in shorts:
            en = (heroes.get(s) or {}).get("localized_name") or s.replace("_", " ").title()
            aliases = ALIASES.get(s, [])
            label = f"{en} ({aliases[0]})" if aliases else en
            keys = [en.lower(), s.lower()] + [a.lower() for a in aliases]
            res.append((en, s, label, keys))
        res.sort()
        return res

    def _filter(self):
        q = self.q.get().strip().lower()
        self.shown = []
        exact, starts, contains = [], [], []
        for en, s, label, keys in self.heroes:
            if s in self.selected:
                continue
            if not q:
                contains.append((s, label))
            elif q in keys:
                exact.append((s, label))
            elif any(k.startswith(q) or any(w.startswith(q) for w in k.split()) for k in keys):
                starts.append((s, label))
            elif any(q in k for k in keys):
                contains.append((s, label))
        self.shown = exact + starts + contains
        self.lb.delete(0, "end")
        for _, label in self.shown:
            self.lb.insert("end", label)

    def _refresh_sel(self):
        self.sel.delete(0, "end")
        for s in self.selected:
            self.sel.insert("end", self.app._hero_title(s))
        self.app.set_enemies(self.selected)

    def _add(self, s):
        if s not in self.selected and len(self.selected) < 5:
            self.selected.append(s)
            self.q.set("")
            self._refresh_sel()
            self._filter()

    def _add_first(self):
        if self.shown:
            self._add(self.shown[0][0])

    def _add_selected(self):
        cur = self.lb.curselection()
        if cur:
            self._add(self.shown[cur[0]][0])

    def _remove(self):
        cur = self.sel.curselection()
        if cur:
            self.selected.pop(cur[0])
            self._refresh_sel()
            self._filter()

    def _clear(self):
        self.selected = []
        self._refresh_sel()
        self._filter()

    def _done(self):
        self.app.set_enemies(self.selected)
        self.win.destroy()
