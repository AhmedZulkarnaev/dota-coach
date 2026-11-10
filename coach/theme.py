"""Оформление окна: цвета, шрифты и мелкие функции форматирования."""

BG = "#14171c"
BG2 = "#1d2229"
BG_HOVER = "#2b323c"
FG = "#e6e6e6"
DIM = "#8a93a0"
GOLD = "#f2c94c"
GREEN = "#5cd65c"
RED = "#ff6b6b"
ORANGE = "#ffa94d"
CYAN = "#66d9e8"
FONT = "Segoe UI"
FONT_MONO = "Consolas"


def fmt_gold(amount: int) -> str:
    """1234567 → «1 234 567»."""
    return f"{amount:,}".replace(",", " ")


MARK_STYLES = {"✓": "ok", "✗": "fail", "!": "warn"}
NOT_HEADER_PREFIXES = ("•", "1.", "2.", "3.", "(", "-")


def line_style(index: int, line: str, previous: str) -> str | None:
    """Стиль строки в текстовом окне: title, h (подзаголовок), ok/fail/warn или
    None.

    Первая строка — заголовок; строка после пустой — подзаголовок раздела;
    строки, начинающиеся с ✓ / ✗ / !, подсвечиваются цветом.
    """
    stripped = line.strip()
    if index == 0:
        return "title"
    if stripped[:1] in MARK_STYLES:
        return MARK_STYLES[stripped[0]]
    is_header = (
        bool(stripped)
        and not previous.strip()
        and not line.startswith(" ")
        and not stripped.startswith(NOT_HEADER_PREFIXES)
    )
    return "h" if is_header else None
