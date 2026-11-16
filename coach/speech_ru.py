"""Подготовка текста для русского голоса.

Русский синтезатор читает английские слова плохо («Black King Bar» превращается
в кашу).
Поэтому перед озвучкой английские названия заменяются русским звучанием:
«Black King Bar» → «блэк кинг бар», «Magic Wand» → «мэджик ванд».
На экране названия остаются английскими — как в игре.

1) words — звучание частых слов из названий предметов и способностей;
2) abbr — аббревиатуры (TP, BKB…);
   оба словаря — в coach/data/speech_ru.json, их можно дополнять;
3) всё остальное латиницей — простая транслитерация по правилам английского
   чтения.
"""

import re

from . import rules

_RULES = rules.load("speech_ru")
ABBR: dict[str, str] = _RULES["abbr"]

WORDS: dict[str, str] = rules.flat(_RULES["words"])

# Порядок важен: сначала длинные сочетания букв.
_TRANSLIT = [
    ("tion", "шн"),
    ("sion", "жн"),
    ("ight", "айт"),
    ("igh", "ай"),
    ("ough", "оу"),
    ("sch", "ск"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("th", "т"),
    ("ph", "ф"),
    ("ck", "к"),
    ("qu", "кв"),
    ("wh", "у"),
    ("wr", "р"),
    ("ee", "и"),
    ("ea", "и"),
    ("oo", "у"),
    ("ou", "ау"),
    ("ow", "оу"),
    ("ai", "эй"),
    ("ay", "эй"),
    ("ey", "ей"),
    ("oa", "оу"),
    ("oi", "ой"),
    ("oy", "ой"),
    ("au", "о"),
    ("aw", "о"),
    ("ie", "и"),
    ("ue", "ю"),
    ("x", "кс"),
    ("j", "дж"),
    ("ce", "се"),
    ("ci", "си"),
    ("cy", "си"),
    ("a", "а"),
    ("b", "б"),
    ("c", "к"),
    ("d", "д"),
    ("e", "е"),
    ("f", "ф"),
    ("g", "г"),
    ("h", "х"),
    ("i", "и"),
    ("k", "к"),
    ("l", "л"),
    ("m", "м"),
    ("n", "н"),
    ("o", "о"),
    ("p", "п"),
    ("q", "к"),
    ("r", "р"),
    ("s", "с"),
    ("t", "т"),
    ("u", "у"),
    ("v", "в"),
    ("w", "у"),
    ("y", "и"),
    ("z", "з"),
]


def transliterate(word: str) -> str:
    w = word.lower().replace("'", "")
    if w.endswith("dge"):
        w = w[:-3] + "дж"  # edge → эдж
    elif w.endswith("ge"):
        w = w[:-2] + "дж"  # charge → чардж
    elif len(w) > 3 and w.endswith("e") and not w.endswith(("ee", "ie")):
        w = w[:-1]  # немая «e» на конце: blade → блейд
    if w.startswith("kn"):
        w = w[1:]  # knight → найт
    if w.startswith("y"):
        w = "й" + w[1:]
    out, i = [], 0
    while i < len(w):
        for lat, cyr in _TRANSLIT:
            if w.startswith(lat, i):
                out.append(cyr)
                i += len(lat)
                break
        else:
            out.append(w[i])
            i += 1
    return "".join(out)


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")


def speakable(text: str) -> str:
    """Текст для русского голоса: английские слова → русское звучание."""
    if not text:
        return text
    for abbr, ru in ABBR.items():
        text = re.sub(rf"\b{re.escape(abbr)}\b", ru, text)

    def repl(m: re.Match[str]) -> str:
        w = m.group(0)
        return WORDS.get(w.lower()) or transliterate(w)

    text = _WORD_RE.sub(repl, text)
    return text.replace("№", "номер ").replace("»", "").replace("⚠", "")
