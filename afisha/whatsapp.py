"""Выгрузка постов под WhatsApp-канал.

У каналов WhatsApp нет официального API — Meta его не даёт, постить может
только админ из приложения. Поэтому здесь не «публикация», а подготовка:
на каждый пост кладём готовый текст и картинку в outbox/whatsapp/, тебе
остаётся открыть канал, вставить и отправить.

Тридцать секунд на пост, ноль риска для номера. Когда объём станет
болезненным, сюда добавляется отправка через WAHA — интерфейс уже
подходящий, менять придётся только последний шаг.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .compose import WHATSAPP, build_caption
from .models import Draft

# Читается человеком, а не машиной: имя файла должно быть понятно
# в списке, когда постов за день накопилось десять.
INDEX_NAME = "README.txt"


def export(drafts: list[Draft], outbox: Path, footer: str = "") -> list[Path]:
    """Складывает посты в outbox/whatsapp/, возвращает пути к текстам."""
    outbox.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    lines = [
        "Готовые посты для WhatsApp-канала",
        "=" * 40,
        "",
        "Порядок: открыть канал → приложить .jpg/.png → вставить текст из .txt.",
        "Текст уже в разметке WhatsApp: *жирный*, _курсив_.",
        "",
    ]

    for index, draft in enumerate(drafts, start=1):
        event = draft.event
        slug = f"{index:02d}-{event.starts_at:%m-%d}-{_safe(event.title)}"

        caption = build_caption(event, footer=footer, fmt=WHATSAPP)
        text_path = outbox / f"{slug}.txt"
        text_path.write_text(caption, encoding="utf-8")
        written.append(text_path)

        card = Path(draft.card_path)
        if card.exists():
            shutil.copy2(card, outbox / f"{slug}{card.suffix}")

        lines.append(f"{index:02d}. {event.starts_at:%d.%m %H:%M}  {event.title}")
        lines.append(f"    {slug}.txt  +  {slug}{card.suffix if card.exists() else ' (без карточки)'}")

    (outbox / INDEX_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def _safe(title: str) -> str:
    """Короткий кусок названия, пригодный для имени файла."""
    keep = [ch if ch.isalnum() or ch in " -_" else " " for ch in title]
    words = "".join(keep).split()
    return "-".join(words[:4]).lower()[:48] or "post"
