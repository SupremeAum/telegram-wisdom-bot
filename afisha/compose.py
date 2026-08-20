"""Сборка текста поста под Telegram и WhatsApp.

На карточке остаётся только латиница, поэтому вся смысловая нагрузка
ложится на подпись.

Форматы разметки у площадок разные и несовместимые:
  Telegram — HTML (<b>, <i>, <a href>), сущности экранируются;
  WhatsApp — свой лёгкий синтаксис (*жирный*, _курсив_), ссылок в
             разметке нет вообще, URL кладётся голым текстом.
Поэтому текст собирается под каждую площадку отдельно, а не
конвертируется из одной в другую: HTML→WhatsApp неизбежно теряет ссылки.
"""

from __future__ import annotations

from .models import Event

HTML = "html"
WHATSAPP = "whatsapp"

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября",
    12: "декабря",
}
WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница",
               "суббота", "воскресенье"]

CATEGORY_EMOJI = {
    "concert": "🎵", "theatre": "🎭", "expo": "🖼",
    "kids": "🧸", "party": "🎉", "event": "📌",
}

CATEGORY_TAG = {
    "concert": "#концерт", "theatre": "#театр", "expo": "#выставка",
    "kids": "#детям", "party": "#вечеринка", "event": "#событие",
}

# Telegram режет подпись к фото на 1024 символах. У WhatsApp лимит выше,
# но держим общий: пост, который не читается с одного экрана, всё равно
# плохой пост.
CAPTION_LIMIT = 1024


def _escape(text: str, fmt: str) -> str:
    if fmt == HTML:
        return (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))
    return text


def _bold(text: str, fmt: str) -> str:
    return f"<b>{text}</b>" if fmt == HTML else f"*{text}*"


def _link(url: str, label: str, fmt: str) -> str:
    if fmt == HTML:
        return f'🎟 <a href="{url}">{label}</a>'
    # WhatsApp сам делает URL кликабельным; разметки для ссылок у него нет.
    return f"🎟 {label}:\n{url}"


def format_when(event: Event) -> str:
    return (
        f"{event.starts_at.day} {MONTHS_RU[event.starts_at.month]}, "
        f"{WEEKDAYS_RU[event.starts_at.weekday()]} "
        f"в {event.starts_at.strftime('%H:%M')}"
    )


def build_caption(event: Event, footer: str = "", fmt: str = HTML) -> str:
    """Формирует подпись к посту для указанной площадки.

    footer — подпись канала, у Telegram и WhatsApp она разная.
    """
    if fmt not in (HTML, WHATSAPP):
        raise ValueError(f"неизвестный формат: {fmt}")

    emoji = CATEGORY_EMOJI.get(event.category, "📌")
    parts = [f"{emoji} {_bold(_escape(event.title, fmt), fmt)}", ""]

    if event.description:
        parts.extend([_escape(event.description.strip(), fmt), ""])

    parts.append(f"🗓 {format_when(event)}")
    parts.append(f"📍 {_escape(event.venue, fmt)}")
    parts.append(f"💸 {_escape(event.price, fmt) if event.price else 'вход свободный'}")

    if event.url:
        parts.append("\n" + _link(_escape(event.url, fmt), "Билеты и подробности", fmt))

    tags = [CATEGORY_TAG.get(event.category, "#событие"), "#УстьКаменогорск", "#Өскемен"]
    parts.append("\n" + " ".join(tags))

    if footer:
        parts.append(f"\n{footer}")

    caption = "\n".join(parts)

    if len(caption) > CAPTION_LIMIT:
        # Ужимаем описание, а не хвост: ссылка и теги важнее подробностей.
        overflow = len(caption) - CAPTION_LIMIT + 1
        if event.description and len(event.description) > overflow:
            trimmed = event.description[: len(event.description) - overflow].rstrip()
            trimmed = trimmed.rsplit(" ", 1)[0] + "…"
            shortened = Event(**{**event.__dict__, "description": trimmed})
            return build_caption(shortened, footer, fmt)
        caption = caption[: CAPTION_LIMIT - 3] + "…"

    return caption
