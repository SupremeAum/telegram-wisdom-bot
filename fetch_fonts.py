"""Загружает шрифт Inter для карточек: python fetch_fonts.py

Шрифт не хранится в репозитории (бинарники ~1.6 МБ), поэтому его нужно
один раз скачать. Без него карточки всё равно отрисуются — card.py
откатится на системный DejaVu, — но выглядеть будут заметно хуже.

Inter распространяется по SIL Open Font License 1.1.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import httpx

RELEASE_URL = "https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip"
NEEDED = ("Inter-Black.ttf", "Inter-Bold.ttf", "Inter-SemiBold.ttf", "Inter-Medium.ttf")
FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)

    if all((FONTS_DIR / name).exists() for name in NEEDED):
        print(f"Шрифты уже на месте: {FONTS_DIR}")
        return 0

    print(f"Качаю Inter ({RELEASE_URL}) …")
    try:
        response = httpx.get(RELEASE_URL, follow_redirects=True, timeout=120.0)
        response.raise_for_status()
    except Exception as exc:                       # noqa: BLE001
        print(f"Не удалось скачать: {exc}", file=sys.stderr)
        print("Карточки будут собираться системным шрифтом DejaVu.", file=sys.stderr)
        return 1

    saved = 0
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for entry in archive.namelist():
            name = Path(entry).name
            if name in NEEDED:
                (FONTS_DIR / name).write_bytes(archive.read(entry))
                print(f"  ✓ {name}")
                saved += 1
        for entry in archive.namelist():
            if Path(entry).name.upper().startswith("LICENSE"):
                (FONTS_DIR / "Inter-LICENSE.txt").write_bytes(archive.read(entry))
                break

    if saved < len(NEEDED):
        print(f"Найдено {saved} из {len(NEEDED)} — структура архива изменилась.",
              file=sys.stderr)
        return 1

    print(f"Готово: {FONTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
