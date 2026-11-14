"""Смена версии во всех местах сразу: код, README, CHANGELOG.

    python tools/bump_version.py 0.7.0.dev3   следующая сборка в разработке
    python tools/bump_version.py 0.7.0        релиз (дата в CHANGELOG — сама)
    python tools/bump_version.py --check      проверить, что всё совпадает

Где живёт версия:
  • coach/__init__.py — __version__ (главный источник);
  • README.md — строка статуса между <!-- version --> и <!-- /version -->;
  • CHANGELOG.md — первый заголовок: «## 0.7.0 (в работе)» или
    «## 0.7.0 — дата».

Тест tests/test_version.py проверяет то же самое, так что CI не пропустит
забытую версию.
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "coach" / "__init__.py"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
REPO = "https://github.com/AhmedZulkarnaev/dota-coach"

VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+)(?:\.(dev|rc)(\d+))?$")
INIT_RE = re.compile(r'^__version__ = "([^"]+)"$', re.M)
README_BLOCK_RE = re.compile(r"<!-- version -->.*?<!-- /version -->", re.S)
CHANGELOG_HEAD_RE = re.compile(r"^## (\d+\.\d+\.\d+)(.*)$", re.M)
IN_PROGRESS = " (в работе)"


def parse(version: str) -> tuple[str, bool]:
    """'0.7.0.dev2' → ('0.7.0', True); '0.7.0' → ('0.7.0', False)."""
    m = VERSION_RE.match(version)
    if not m:
        raise ValueError(
            f"Версия «{version}» не по формату: "
            "0.7.0, 0.7.0.dev3 или 0.7.0.rc1"
        )
    return m.group(1), m.group(2) is not None


def readme_block(version: str) -> str:
    _base, unstable = parse(version)
    if unstable:
        status = (
            "в разработке, в ветке `main`. Стабильная версия — "
            f"[последний релиз]({REPO}/releases/latest)"
        )
    else:
        status = (
            f"стабильная, [релиз v{version}]({REPO}/releases/tag/v{version})"
        )
    return (
        "<!-- version -->\n"
        f"> **Текущая версия: {version}** — {status}. "
        "Что нового — в [CHANGELOG](CHANGELOG.md).\n"
        "<!-- /version -->"
    )


def changelog_heading(version: str, today: datetime.date) -> str:
    base, unstable = parse(version)
    return f"## {base}" + (IN_PROGRESS if unstable else f" — {today:%Y-%m-%d}")


# ---------- чтение ----------
def read_init(text: str) -> str:
    m = INIT_RE.search(text)
    if not m:
        raise ValueError('В coach/__init__.py нет строки __version__ = "…"')
    return m.group(1)


def problems(
    init_text: str, readme_text: str, changelog_text: str
) -> list[str]:
    """Что не совпадает. Пустой список — всё в порядке."""
    found = []
    version = read_init(init_text)
    try:
        base, unstable = parse(version)
    except ValueError as e:
        return [str(e)]
    block = README_BLOCK_RE.search(readme_text)
    if not block:
        found.append(
            "README.md: нет блока <!-- version --> … <!-- /version -->"
        )
    elif block.group(0) != readme_block(version):
        found.append(
            f"README.md: строка статуса не для версии {version} "
            "(запустите tools/bump_version.py)"
        )
    head = CHANGELOG_HEAD_RE.search(changelog_text)
    if not head:
        found.append("CHANGELOG.md: нет ни одного заголовка «## X.Y.Z»")
    else:
        if head.group(1) != base:
            found.append(
                f"CHANGELOG.md: первый раздел — {head.group(1)}, "
                f"а версия {base}"
            )
        in_progress = head.group(2) == IN_PROGRESS
        if unstable and not in_progress:
            found.append(f"CHANGELOG.md: у {base} должно быть «(в работе)»")
        if not unstable and in_progress:
            found.append(f"CHANGELOG.md: у релиза {base} должна стоять дата")
    return found


# ---------- запись ----------
def bump(
    version: str,
    init_text: str,
    readme_text: str,
    changelog_text: str,
    today: datetime.date,
) -> tuple[str, str, str]:
    """Возвращает новые тексты (init, README, CHANGELOG)."""
    base, _unstable = parse(version)
    init_text = INIT_RE.sub(f'__version__ = "{version}"', init_text, count=1)

    if README_BLOCK_RE.search(readme_text):
        readme_text = README_BLOCK_RE.sub(
            lambda _m: readme_block(version), readme_text, count=1
        )
    else:  # первый запуск: блок встаёт после строки со ссылками
        anchor = "[Помочь проекту](CONTRIBUTING.md)\n"
        if anchor not in readme_text:
            raise ValueError(
                "README.md: не нашёл, куда вставить строку статуса"
            )
        readme_text = readme_text.replace(
            anchor, anchor + "\n" + readme_block(version) + "\n", 1
        )

    heading = changelog_heading(version, today)
    head = CHANGELOG_HEAD_RE.search(changelog_text)
    if head and head.group(1) == base:
        changelog_text = (
            changelog_text[: head.start()]
            + heading
            + changelog_text[head.end() :]
        )
    else:  # новая версия — новый раздел сверху
        marker = "# История изменений\n"
        if marker not in changelog_text:
            raise ValueError(
                "CHANGELOG.md: нет заголовка «# История изменений»"
            )
        changelog_text = changelog_text.replace(
            marker, f"{marker}\n{heading}\n- …\n", 1
        )
    return init_text, readme_text, changelog_text


def main() -> None:
    ap = argparse.ArgumentParser(description="Смена версии Dota Coach")
    ap.add_argument(
        "version", nargs="?", help="новая версия, например 0.7.0.dev3"
    )
    ap.add_argument("--check", action="store_true", help="только проверить")
    args = ap.parse_args()
    files = (INIT, README, CHANGELOG)
    init, readme, changelog = (p.read_text(encoding="utf-8") for p in files)
    texts = [init, readme, changelog]

    if args.check or not args.version:
        found = problems(init, readme, changelog)
        for p in found:
            print("✗", p)
        if not found:
            print(f"✓ Версия {read_init(texts[0])} везде совпадает.")
        sys.exit(1 if found else 0)

    try:
        new = bump(
            args.version, init, readme, changelog, datetime.date.today()
        )
    except ValueError as e:
        sys.exit(f"✗ {e}")
    for path, old, text in zip(files, texts, new, strict=True):
        if text != old:
            path.write_text(text, encoding="utf-8")
            print(f"обновлён {path.relative_to(ROOT)}")
    leftover = problems(*new)  # bump() отдаёт ровно три текста
    if leftover:
        sys.exit("✗ " + "; ".join(leftover))
    print(f"✓ Версия {args.version}.")
    _base, unstable = parse(args.version)
    if not unstable:
        print(
            "Релиз: допишите раздел в CHANGELOG, закоммитьте, запушьте и "
            "создайте релиз:\n"
            f"  gh release create v{args.version} --target main "
            f'--title "Dota Coach {args.version}" --notes "кратко: что нового"'
        )


if __name__ == "__main__":
    main()
