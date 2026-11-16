"""Правила советов в JSON: что советовать, как объяснять, как произносить.

Встроенные правила лежат в coach/data/*.json и обновляются вместе с
программой. Свои правки — в папке rules/ рядом с main.py, файл с тем же
именем (rules/coach_tips.json, rules/items.json …). В нём достаточно
написать только то, что меняете:
  • словари объединяются: свой ключ заменяет встроенный, новый добавляется;
  • списки заменяются целиком;
  • в советах тренера (coach_tips) совет с тем же id заменяет встроенный,
    а {"id": "…", "off": true} выключает его.

Свой файл с ошибкой не ломает программу: он пропускается, а причина видна в
☰ → «Проверить подключение» и в python tools/check_rules.py.
"""

import copy
import json
import logging
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from .settings import APP_DIR

LOG = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
USER_DIR = APP_DIR / "rules"
LEGACY_TIPS = APP_DIR / "coach_tips.json"  # до 0.7: список советов целиком

NAMES = (
    "abilities",
    "coach_tips",
    "enemies",
    "heroes_ru",
    "items",
    "slots",
    "speech_ru",
)
ROLES = ("core", "support")
STAGES = ("start", "lane", "mid", "late")

# Ошибки в своих правилах пользователя: {rules/файл.json: [ошибки]}.
_user_problems: dict[str, list[str]] = {}


# ---------- загрузка ----------
@cache
def load(name: str) -> dict[str, Any]:
    """Правила по имени файла: встроенные + свои из rules/, уже проверенные.

    Результат общий для всех — не изменяйте его.
    """
    builtin = read_json(DATA_DIR / f"{name}.json")
    errors = validate(name, builtin)
    if errors:  # встроенные правила проверяются тестом, сюда не доходит
        raise ValueError(f"coach/data/{name}.json: " + "; ".join(errors))

    _user_problems.pop(name, None)
    user_path = USER_DIR / f"{name}.json"
    if name == "coach_tips" and not user_path.exists():
        user_path = LEGACY_TIPS
    if not user_path.exists():
        return builtin
    try:
        user = read_json(user_path)
        if user_path == LEGACY_TIPS and isinstance(user, list):
            user = {"tips": user, "replace": True}
        merged = merge(name, builtin, user)
        errors = validate(name, user, partial=True) or validate(
            name, merged, merged=True
        )
    except (OSError, ValueError) as e:
        errors = [str(e)]
    if errors:
        _user_problems[label(user_path)] = errors
        LOG.warning("Свои правила %s пропущены: %s", user_path, errors)
        return builtin
    LOG.info("Подключены свои правила %s", user_path)
    return merged


def reload() -> None:
    """Забыть загруженное (для тестов и после правки файлов)."""
    load.cache_clear()
    _user_problems.clear()


def user_problems() -> dict[str, list[str]]:
    """Ошибки в своих правилах rules/*.json: {файл: [ошибки]}."""
    for name in NAMES:
        load(name)
    found = {k: list(v) for k, v in _user_problems.items()}
    for path in user_paths():
        if path.stem not in NAMES:
            found[label(path)] = [
                "такого файла правил нет; бывают: "
                + ", ".join(f"{n}.json" for n in NAMES)
            ]
    return found


def user_paths() -> list[Path]:
    """Все свои файлы правил, которые лежат на диске."""
    paths = sorted(USER_DIR.glob("*.json")) if USER_DIR.is_dir() else []
    if LEGACY_TIPS.exists() and not (USER_DIR / LEGACY_TIPS.name).exists():
        paths.append(LEGACY_TIPS)
    return paths


def user_files() -> list[str]:
    """Свои файлы правил, которые подключились без ошибок."""
    problems = user_problems()
    return [label(p) for p in user_paths() if label(p) not in problems]


def label(path: Path) -> str:
    """Как назвать свой файл человеку: rules/items.json или coach_tips.json."""
    return path.name if path == LEGACY_TIPS else f"rules/{path.name}"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{path.name}: ошибка JSON в строке {e.lineno}: {e.msg}"
        ) from None


def merge(name: str, builtin: Any, user: Any) -> Any:
    if not isinstance(user, dict):
        raise ValueError(f"{name}.json: нужен объект {{…}}, а не список")
    if name == "coach_tips":
        return _merge_tips(builtin, user)
    return _merge(builtin, user)


def _merge(base: Any, extra: Any) -> Any:
    if isinstance(base, dict) and isinstance(extra, dict):
        out = dict(base)
        for k, v in extra.items():
            out[k] = _merge(base[k], v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(extra)


def _merge_tips(builtin: dict[str, Any], user: dict[str, Any]) -> Any:
    tips = user.get("tips", [])
    if not isinstance(tips, list):
        raise ValueError("coach_tips.json: «tips» должен быть списком")
    if user.get("replace"):
        return {"tips": [t for t in tips if not t.get("off")]}
    by_id = {t["id"]: t for t in builtin["tips"]}
    for t in tips:
        if not isinstance(t, dict) or "id" not in t:
            raise ValueError("coach_tips.json: у каждого совета нужен «id»")
        if t.get("off"):
            by_id.pop(t["id"], None)
        else:
            by_id[t["id"]] = {**by_id.get(t["id"], {}), **t}
    return {"tips": list(by_id.values())}


# ---------- удобные формы для модулей ----------
def flat(sections: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """{раздел: {ключ: значение}} → {ключ: значение}. Разделы — для людей."""
    out: dict[str, Any] = {}
    for part in sections.values():
        out.update(part)
    return out


# ---------- проверка формата ----------
class _Check:
    """Собирает ошибки с путём до места: «tips[3].at: нужно целое число»."""

    def __init__(self, merged: bool = False) -> None:
        self.errors: list[str] = []
        # В объединённых правилах свой раздел может повторить встроенный
        # ключ — он стоит последним и побеждает.
        self.merged = merged

    def add(self, where: str, problem: str) -> None:
        self.errors.append(f"{where}: {problem}")

    def obj(self, where: str, value: Any, keys: dict[str, bool]) -> bool:
        """Объект с известными ключами; keys: ключ → обязателен ли."""
        if not isinstance(value, dict):
            self.add(where, "нужен объект {…}")
            return False
        for k in value:
            if k not in keys and not k.startswith("_"):
                self.add(where, f"неизвестный ключ «{k}»")
        for k, required in keys.items():
            if required and k not in value:
                self.add(where, f"нет ключа «{k}»")
        return True

    def text(self, where: str, value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            self.add(where, "нужен непустой текст")

    def integer(self, where: str, value: Any, low: int | None = None) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            self.add(where, "нужно целое число")
        elif low is not None and value < low:
            self.add(where, f"не меньше {low}")

    def str_list(self, where: str, value: Any, empty: bool = False) -> None:
        if not isinstance(value, list) or (not value and not empty):
            self.add(where, "нужен список строк")
            return
        for i, v in enumerate(value):
            self.text(f"{where}[{i}]", v)
        if len(set(value)) != len(value):
            self.add(where, "повторяющиеся значения")

    def text_map(self, where: str, value: Any) -> None:
        if not isinstance(value, dict):
            self.add(where, "нужен объект {ключ: текст}")
            return
        for k, v in value.items():
            self.text(f"{where}.{k}", v)

    def sections(
        self,
        where: str,
        value: Any,
        each: Callable[[str, Any], None],
        partial: bool,
    ) -> None:
        """{раздел: {ключ: значение}}; один ключ — только в одном разделе."""
        if not isinstance(value, dict):
            self.add(where, "нужен объект {раздел: {…}}")
            return
        seen: dict[str, str] = {}
        for sec, part in value.items():
            if not isinstance(part, dict):
                self.add(f"{where}.{sec}", "нужен объект {ключ: …}")
                continue
            for k, v in part.items():
                if k in seen and not (partial or self.merged):
                    self.add(f"{where}.{sec}.{k}", f"уже есть в «{seen[k]}»")
                seen[k] = sec
                each(f"{where}.{sec}.{k}", v)


def validate(
    name: str, data: Any, partial: bool = False, merged: bool = False
) -> list[str]:
    """Ошибки формата.

    partial=True — свой файл из rules/, где ключи можно опускать;
    merged=True — встроенные правила вместе со своими.
    """
    if name not in NAMES:
        return [f"неизвестный файл правил «{name}.json»"]
    c = _Check(merged)
    if not isinstance(data, dict):
        return ["нужен объект {…}"]
    VALIDATORS[name](c, data, partial)
    return c.errors


def _need(partial: bool, *keys: str) -> dict[str, bool]:
    return dict.fromkeys(keys, not partial)


def _v_tips(c: _Check, d: dict[str, Any], partial: bool) -> None:
    if not c.obj("", d, {"tips": True, "replace": False}):
        return
    tips = d["tips"]
    if not isinstance(tips, list):
        c.add("tips", "нужен список советов")
        return
    ids: set[str] = set()
    keys = {
        "id": True,
        "at": not partial,
        "text": not partial,
        "roles": False,
        "every": False,
        "until": False,
        "priority": False,
        "off": False,
    }
    for i, t in enumerate(tips):
        w = f"tips[{i}]"
        if not c.obj(w, t, keys):
            continue
        c.text(f"{w}.id", t.get("id"))
        if t.get("id") in ids:
            c.add(f"{w}.id", f"«{t['id']}» повторяется")
        ids.add(t.get("id"))
        if t.get("off"):
            continue
        if "at" in t:
            c.integer(f"{w}.at", t["at"])
        if "text" in t:
            c.text(f"{w}.text", t["text"])
        if "roles" in t:
            roles = t["roles"]
            if not isinstance(roles, list) or not roles:
                c.add(f"{w}.roles", "нужен список: core и/или support")
            elif set(roles) - set(ROLES):
                c.add(f"{w}.roles", "можно только core и support")
        for k in ("every", "until"):
            if k in t:
                c.integer(f"{w}.{k}", t[k], 0)
        if "priority" in t:
            c.integer(f"{w}.priority", t["priority"], 1)
        if t.get("every") and t.get("until", 0) < t.get("at", 0):
            c.add(f"{w}.until", "должно быть не раньше at")


def _v_items(c: _Check, d: dict[str, Any], partial: bool) -> None:
    if not c.obj(
        "", d, _need(partial, "why", "generic_by_stage", "attributes")
    ):
        return
    if "why" in d:
        c.sections("why", d["why"], c.text, partial)
    if "generic_by_stage" in d:
        g = d["generic_by_stage"]
        if c.obj("generic_by_stage", g, _need(partial, *STAGES)):
            c.text_map("generic_by_stage", g)
    if "attributes" in d:
        c.text_map("attributes", d["attributes"])


def _v_abilities(c: _Check, d: dict[str, Any], partial: bool) -> None:
    keys = _need(partial, "tips", "generic", "tag_order", "keywords")
    if not c.obj("", d, keys):
        return
    generic = d.get("generic")
    if generic is not None:
        c.text_map("generic", generic)
    tags = set(generic or {}) | {"ult"}
    if partial:  # свой файл: теги проверятся на объединённых правилах
        tags = set()

    def tip(where: str, v: Any) -> None:
        if c.obj(where, v, {"text": True, "tags": True}):
            c.text(f"{where}.text", v.get("text"))
            c.str_list(f"{where}.tags", v.get("tags"))
            unknown = set(v.get("tags") or []) - tags if tags else set()
            if unknown and isinstance(v.get("tags"), list):
                c.add(f"{where}.tags", f"неизвестные теги: {sorted(unknown)}")

    if "tips" in d:
        c.sections("tips", d["tips"], tip, partial)
    if "tag_order" in d:
        c.str_list("tag_order", d["tag_order"])
        if tags and isinstance(d["tag_order"], list):
            unknown = set(d["tag_order"]) - tags
            if unknown:
                c.add("tag_order", f"нет текста в generic: {sorted(unknown)}")
    if not partial and generic is not None:
        missing = {"passive", "nuke"} - set(generic)
        if missing:
            c.add("generic", f"нужны тексты для {sorted(missing)}")
    if "keywords" in d:
        kw = d["keywords"]
        if not isinstance(kw, list):
            c.add("keywords", "нужен список")
            return
        for i, k in enumerate(kw):
            w = f"keywords[{i}]"
            if not c.obj(w, k, {"tag": True, "regex": True}):
                continue
            if tags and k.get("tag") not in tags:
                c.add(f"{w}.tag", f"неизвестный тег «{k.get('tag')}»")
            try:
                re.compile(str(k.get("regex")))
            except re.error as e:
                c.add(f"{w}.regex", f"ошибка в выражении: {e}")


def _v_enemies(c: _Check, d: dict[str, Any], partial: bool) -> None:
    if not c.obj("", d, _need(partial, "groups", "counters", "reminders")):
        return
    groups = d.get("groups")
    if groups is not None:
        if not isinstance(groups, dict):
            c.add("groups", "нужен объект {признак: …}")
            groups = {}
        for g, v in groups.items():
            w = f"groups.{g}"
            keys = {"label": True, "role": False, "heroes": False}
            if not c.obj(w, v, {**keys, "count": False}):
                continue
            c.text(f"{w}.label", v.get("label"))
            if ("role" in v) == ("heroes" in v):
                c.add(w, "нужно что-то одно: role или heroes")
            if "role" in v:
                c.text(f"{w}.role", v["role"])
            if "heroes" in v:
                c.str_list(f"{w}.heroes", v["heroes"])
    known = set(groups or {})
    if partial:
        known = set()
    fields = set(known) | {f"{g}_names" for g in known}

    def when(where: str, v: Any) -> None:
        if not isinstance(v, dict) or not v:
            c.add(where, "нужен объект {признак: сколько героев}")
            return
        for g, n in v.items():
            if known and g not in known:
                c.add(f"{where}.{g}", "нет такого признака в groups")
            c.integer(f"{where}.{g}", n, 1)

    def reason(where: str, text: Any) -> None:
        c.text(where, text)
        if not fields or not isinstance(text, str):
            return
        for f in re.findall(r"{([^{}]*)}", text):
            if f not in fields:
                c.add(where, f"неизвестная подстановка {{{f}}}")

    def rules(key: str, advice: Callable[[str, Any], None]) -> None:
        lst = d[key]
        if not isinstance(lst, list):
            c.add(key, "нужен список правил")
            return
        for i, r in enumerate(lst):
            w = f"{key}[{i}]"
            extra = {"exclusive": False} if key == "counters" else {}
            keys = {"when": True, "core": False, "support": False}
            if not c.obj(w, r, {**keys, **extra}):
                continue
            when(f"{w}.when", r.get("when"))
            if "core" not in r and "support" not in r:
                c.add(w, "нужен совет хотя бы для одной роли: core/support")
            for role in ROLES:
                if role in r:
                    advice(f"{w}.{role}", r[role])
            if "exclusive" in r:
                c.text(f"{w}.exclusive", r["exclusive"])

    def counter(where: str, v: Any) -> None:
        keys = {"item": True, "strength": True, "reason": True}
        if not c.obj(where, v, keys):
            return
        c.text(f"{where}.item", v.get("item"))
        s = v.get("strength")
        number = isinstance(s, (int, float)) and not isinstance(s, bool)
        if not number or not 0.1 <= s <= 2:
            c.add(f"{where}.strength", "нужно число от 0.1 до 2")
        reason(f"{where}.reason", v.get("reason"))

    if "counters" in d:
        rules("counters", counter)
    if "reminders" in d:
        rules("reminders", reason)


def _v_speech(c: _Check, d: dict[str, Any], partial: bool) -> None:
    if not c.obj("", d, _need(partial, "abbr", "words")):
        return
    if "abbr" in d:
        c.text_map("abbr", d["abbr"])

    def word(where: str, v: Any) -> None:
        c.text(where, v)
        key = where.rsplit(".", 1)[-1]
        if key != key.lower():
            c.add(where, "слово-ключ пишется маленькими буквами")

    if "words" in d:
        c.sections("words", d["words"], word, partial)


def _v_heroes(c: _Check, d: dict[str, Any], partial: bool) -> None:
    if not c.obj("", d, _need(partial, "aliases")):
        return
    aliases = d.get("aliases")
    if aliases is None:
        return
    if not isinstance(aliases, dict):
        c.add("aliases", "нужен объект {герой: [имена]}")
        return
    for k, v in aliases.items():
        c.str_list(f"aliases.{k}", v)


SLOT_KEYS = (
    "no_slot",
    "use_up",
    "wards",
    "utility",
    "starter_junk",
    "cheap_stats",
)


def _v_slots(c: _Check, d: dict[str, Any], partial: bool) -> None:
    if not c.obj("", d, _need(partial, *SLOT_KEYS)):
        return
    for k in SLOT_KEYS:
        if k in d:
            c.str_list(k, d[k], empty=True)


VALIDATORS: dict[str, Callable[[_Check, dict[str, Any], bool], None]] = {
    "abilities": _v_abilities,
    "coach_tips": _v_tips,
    "enemies": _v_enemies,
    "heroes_ru": _v_heroes,
    "items": _v_items,
    "slots": _v_slots,
    "speech_ru": _v_speech,
}
