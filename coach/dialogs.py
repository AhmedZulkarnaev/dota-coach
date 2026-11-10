"""Дополнительные окна: текстовые отчёты (разбор, история, проверка) и выбор
врагов.
"""

import tkinter as tk

from .heroes_ru import ALIASES
from .theme import (
    BG,
    BG2,
    BG_HOVER,
    DIM,
    FG,
    FONT,
    FONT_MONO,
    GOLD,
    GREEN,
    ORANGE,
    RED,
    line_style,
)

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


def _button(parent, text, command):
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=BG2,
        fg=FG,
        relief="flat",
        padx=10,
        activebackground=BG_HOVER,
        activeforeground=FG,
    )


class TextWindow:
    """Окно с прокручиваемым текстом: разбор матча, история, проверка
    подключения.

    Первая строка — заголовок; строка после пустой — подзаголовок раздела;
    строки, начинающиеся с ✓ / ✗ / !, подсвечиваются цветом.
    buttons — [(надпись, функция)]; refresh — функция, возвращающая свежий
    текст
    (тогда появляется кнопка «Обновить»).
    """

    def __init__(
        self,
        root,
        title,
        text,
        buttons=(),
        refresh=None,
        mono=False,
        size="620x640",
    ):
        self.refresh = refresh
        self.font = FONT_MONO if mono else FONT
        self.mono = mono
        win = tk.Toplevel(root)
        self.win = win
        win.title(title)
        win.configure(bg=BG)
        win.geometry(size)
        win.attributes("-topmost", True)
        frame = tk.Frame(win, bg=BG)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        self.text = tk.Text(
            frame,
            bg=BG,
            fg=FG,
            wrap="none" if mono else "word",
            relief="flat",
            font=(self.font, 10),
            yscrollcommand=scrollbar.set,
            highlightthickness=0,
            padx=6,
            pady=6,
        )
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.text.yview)
        self.text.tag_configure(
            "h", foreground=GOLD, font=(self.font, 10, "bold")
        )
        self.text.tag_configure(
            "title", foreground=GOLD, font=(self.font, 13, "bold")
        )
        self.text.tag_configure("ok", foreground=GREEN)
        self.text.tag_configure("fail", foreground=RED)
        self.text.tag_configure("warn", foreground=ORANGE)
        self.set_text(text)

        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=10, pady=(0, 10))
        _button(row, "Закрыть", win.destroy).pack(side="right", padx=3)
        if refresh:
            _button(row, "Обновить", self.reload).pack(side="right", padx=3)
        for label, command in buttons:
            _button(row, label, command).pack(side="right", padx=3)
        win.bind("<Escape>", lambda event: win.destroy())

    def set_text(self, text):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if self.mono:
                tag = "h" if i == 0 else None
            else:
                tag = line_style(i, line, lines[i - 1] if i else "")
            self.text.insert("end", line + "\n", tag or ())
        self.text.configure(state="disabled")

    def reload(self):
        if self.refresh:
            self.set_text(self.refresh())


class EnemyPicker:
    """Окно выбора героев врага: поиск по-английски, по-русски и по сленгу (па,
    ам, сф…).
    """

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("Враги в этом матче")
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)
        self.win.geometry("470x380")
        self.selected = list(app.enemies)
        self.heroes = self._hero_list()

        tk.Label(
            self.win,
            text="Начните вводить имя (можно по-русски: «па», «лион», «сф»). "
            "Enter или двойной клик — добавить.",
            bg=BG,
            fg=DIM,
            font=(FONT, 9),
            wraplength=440,
            justify="left",
        ).pack(fill="x", padx=10, pady=(8, 4))
        self.q = tk.StringVar()
        e = tk.Entry(
            self.win,
            textvariable=self.q,
            font=(FONT, 11),
            bg=BG2,
            fg=FG,
            insertbackground=FG,
            relief="flat",
        )
        e.pack(fill="x", padx=10)
        e.focus_set()
        self.q.trace_add("write", lambda *a: self._filter())

        lists = tk.Frame(self.win, bg=BG)
        lists.pack(fill="both", expand=True, padx=10, pady=8)
        self.lb = tk.Listbox(
            lists,
            bg=BG2,
            fg=FG,
            selectbackground="#3a4250",
            font=(FONT, 10),
            relief="flat",
            activestyle="none",
        )
        self.lb.pack(side="left", fill="both", expand=True)
        right = tk.Frame(lists, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tk.Label(
            right, text="Выбрано (до 5):", bg=BG, fg=DIM, font=(FONT, 9)
        ).pack(anchor="w")
        self.sel = tk.Listbox(
            right,
            bg=BG2,
            fg=GOLD,
            font=(FONT, 10),
            relief="flat",
            height=6,
            activestyle="none",
        )
        self.sel.pack(fill="both", expand=True)

        btns = tk.Frame(self.win, bg=BG)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        for txt, cmd in (
            ("Готово", self._done),
            ("Очистить", self._clear),
            ("Убрать выбранного", self._remove),
        ):
            tk.Button(
                btns,
                text=txt,
                command=cmd,
                bg=BG2,
                fg=FG,
                relief="flat",
                padx=10,
                activebackground=BG_HOVER,
                activeforeground=FG,
            ).pack(side="right", padx=3)

        e.bind("<Return>", lambda ev: self._add_first())
        e.bind("<Down>", lambda ev: self._focus_list())
        self.lb.bind("<Double-Button-1>", lambda ev: self._add_selected())
        self.lb.bind("<Return>", lambda ev: self._add_selected())
        self.sel.bind("<Double-Button-1>", lambda ev: self._remove())
        self.win.bind("<Escape>", lambda ev: self._done())
        self._filter()
        self._refresh_sel()

    def _focus_list(self):
        self.lb.focus_set()
        self.lb.selection_set(0)

    def _hero_list(self):
        res = []
        heroes = self.app.advisor.heroes_by_short
        shorts = set(heroes) or set(ALIASES)
        for s in shorts:
            en = (heroes.get(s) or {}).get("localized_name") or s.replace(
                "_", " "
            ).title()
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
        for _en, s, label, keys in self.heroes:
            if s in self.selected:
                continue
            if not q:
                contains.append((s, label))
            elif q in keys:
                exact.append((s, label))
            elif any(
                k.startswith(q) or any(w.startswith(q) for w in k.split())
                for k in keys
            ):
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
            self.sel.insert("end", self.app.hero_name(s))
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
