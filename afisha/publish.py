"""Публикация в Telegram и диагностика канала."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramAPIError

from .models import Draft

log = logging.getLogger(__name__)


def make_bot(token: str) -> Bot:
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def _send_alert(token: str, chat_id: str, text: str) -> None:
    bot = make_bot(token)
    try:
        await bot.send_message(chat_id=chat_id, text=text,
                               disable_web_page_preview=True)
    finally:
        await bot.session.close()


def send_alert(text: str) -> bool:
    """Шлёт тревогу в чат из TELEGRAM_ALERT_CHAT_ID. True — если ушла.

    Канал сюда намеренно не подставляется: «афиша не собралась» — весть
    для хозяина бота, подписчикам её видеть незачем. Без токена или без
    адреса чата молча возвращаем False: тревога не должна ронять запуск
    сильнее, чем уже уронила его причина.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_ALERT_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    try:
        asyncio.run(_send_alert(token, chat_id, text))
        return True
    except Exception as exc:                       # noqa: BLE001 — сеть внешняя
        log.warning("не удалось отправить тревогу: %s", exc)
        return False


async def publish_draft(bot: Bot, channel_id: str, draft: Draft) -> int:
    """Отправляет пост в канал, возвращает message_id."""
    card = Path(draft.card_path)
    if card.exists():
        message = await bot.send_photo(
            chat_id=channel_id,
            photo=FSInputFile(card),
            caption=draft.caption,
        )
    else:
        log.warning("карточка %s не найдена, публикую текстом", card)
        message = await bot.send_message(
            chat_id=channel_id,
            text=draft.caption,
            disable_web_page_preview=False,
        )
    return message.message_id


async def diagnose(token: str, channel_id: str, send_test: bool = True) -> list[str]:
    """Полная проверка связки бот → канал.

    Возвращает список строк отчёта. Каждый шаг проверяется отдельно,
    чтобы было видно, на каком именно звене рвётся цепочка.
    """
    report: list[str] = []
    bot = make_bot(token)

    try:
        # 1. Токен
        try:
            me = await bot.get_me()
            report.append(f"✅ Токен валиден: бот @{me.username} (id {me.id})")
        except TelegramAPIError as exc:
            report.append(f"❌ Токен не работает: {exc}")
            report.append("   → Возьми новый токен у @BotFather и положи в .env")
            return report

        # 2. Канал существует и бот его видит
        try:
            chat = await bot.get_chat(channel_id)
            report.append(f"✅ Канал найден: «{chat.title}» ({chat.type}, id {chat.id})")
        except TelegramAPIError as exc:
            report.append(f"❌ Канал {channel_id} недоступен: {exc}")
            report.append("   → Проверь формат: должно быть @username, а не ссылка t.me/...")
            report.append("   → И добавь бота в администраторы канала")
            return report

        # 3. Права на публикацию
        try:
            member = await bot.get_chat_member(chat.id, me.id)
            if member.status not in ("administrator", "creator"):
                report.append(f"❌ Бот не админ канала (статус: {member.status})")
                report.append("   → Канал → Администраторы → Добавить → выбрать бота")
                return report
            can_post = getattr(member, "can_post_messages", None)
            if can_post is False:
                report.append("❌ У бота нет права «Публикация сообщений»")
                report.append("   → Включи это право в настройках админа")
                return report
            report.append("✅ Бот — администратор с правом публикации")
        except TelegramAPIError as exc:
            report.append(f"⚠️  Не удалось проверить права: {exc}")

        # 4. Реальная отправка
        if send_test:
            try:
                message = await bot.send_message(
                    chat_id=channel_id,
                    text="🔧 <b>Проверка связи</b>\n\n"
                         "Бот подключён к каналу и умеет публиковать. "
                         "Это тестовое сообщение — можно удалить.",
                )
                report.append(f"✅ Тестовый пост отправлен (message_id {message.message_id})")
                report.append("   → Проверь канал на телефоне")
            except TelegramAPIError as exc:
                report.append(f"❌ Отправка не прошла: {exc}")
    finally:
        await bot.session.close()

    return report


def run_diagnose(token: str, channel_id: str, send_test: bool = True) -> list[str]:
    return asyncio.run(diagnose(token, channel_id, send_test))
