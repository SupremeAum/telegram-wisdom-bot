"""Telegram-бот канала.

Что было сломано в прежней версии и почему канал молчал:

1. TOKEN = os.getenv("7143553038:AAE...") — в os.getenv передаётся ИМЯ
   переменной окружения, а не значение. Возвращался None, Bot(token=None)
   падал на старте. Плюс сам токен лежал в публичном репозитории.
2. CHANNEL_ID = "@t.me/prosvetlyaka" — невалидный chat_id. Нужен либо
   @username, либо числовой -100...
3. Не было никакого планировщика: post_quote() вызывался только из
   обработчика команды /post. Автопубликации не существовало в принципе —
   поэтому канал и не постил сам по себе.
4. aiogram.utils.executor — API aiogram 2.x. На aiogram 3.x это
   ImportError на этапе импорта.
5. requests в асинхронном обработчике блокировал event loop.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import random
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
# Цитаты идут в свой канал. Если он не задан, падаем на общий — но это
# смешает цитаты с афишей, поэтому в .env.example автопостинг выключен.
CHANNEL_ID = (os.getenv("QUOTES_CHANNEL_ID", "").strip()
              or os.getenv("TELEGRAM_CHANNEL_ID", "").strip())
UNSPLASH_API_KEY = os.getenv("UNSPLASH_API_KEY", "").strip()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()

# Интервал автопубликации; 0 — выключить автопостинг.
POST_INTERVAL_HOURS = float(os.getenv("POST_INTERVAL_HOURS", "0"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

if not CHANNEL_ID:
    raise SystemExit(
        "Не задан канал для цитат.\n"
        "Заполни QUOTES_CHANNEL_ID (или TELEGRAM_CHANNEL_ID) в .env."
    )

if not TOKEN:
    raise SystemExit(
        "Не задан TELEGRAM_BOT_TOKEN.\n"
        "Скопируй .env.example в .env и вставь токен от @BotFather."
    )

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def load_quotes() -> list[tuple[str, str]]:
    """Читает цитаты из CSV, пропуская битые строки."""
    path = ROOT / "quotes.csv"
    if not path.exists():
        log.error("quotes.csv не найден")
        return []

    quotes: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) >= 2 and row[0].strip():
                quotes.append((row[0].strip(), row[1].strip()))
    return quotes


QUOTES = load_quotes()


async def fetch_image(query: str) -> str | None:
    """Ищет фото по очереди в трёх стоках; пропускает те, где нет ключа."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        if UNSPLASH_API_KEY:
            try:
                response = await client.get(
                    "https://api.unsplash.com/photos/random",
                    params={"query": query, "client_id": UNSPLASH_API_KEY},
                )
                response.raise_for_status()
                return response.json()["urls"]["regular"]
            except Exception as exc:               # noqa: BLE001
                log.debug("unsplash не ответил: %s", exc)

        if PEXELS_API_KEY:
            try:
                response = await client.get(
                    "https://api.pexels.com/v1/search",
                    params={"query": query, "per_page": 1},
                    headers={"Authorization": PEXELS_API_KEY},
                )
                response.raise_for_status()
                return response.json()["photos"][0]["src"]["large"]
            except Exception as exc:               # noqa: BLE001
                log.debug("pexels не ответил: %s", exc)

        if PIXABAY_API_KEY:
            try:
                response = await client.get(
                    "https://pixabay.com/api/",
                    params={"key": PIXABAY_API_KEY, "q": query, "image_type": "photo"},
                )
                response.raise_for_status()
                return response.json()["hits"][0]["largeImageURL"]
            except Exception as exc:               # noqa: BLE001
                log.debug("pixabay не ответил: %s", exc)

    return None


def build_caption(quote: str, author: str) -> str:
    handle = CHANNEL_ID if CHANNEL_ID.startswith("@") else f"@{CHANNEL_ID}"
    return f"📜 <i>{quote}</i>\n\n— <b>{author}</b>\n\n{handle}"


async def post_quote() -> bool:
    """Публикует случайную цитату. True — если ушло в канал."""
    if not QUOTES:
        log.error("нет цитат для публикации")
        return False

    quote, author = random.choice(QUOTES)
    caption = build_caption(quote, author)
    image_url = await fetch_image(author) or await fetch_image("wisdom nature")

    try:
        if image_url:
            await bot.send_photo(CHANNEL_ID, photo=image_url, caption=caption)
        else:
            await bot.send_message(CHANNEL_ID, caption)
        log.info("опубликовано: %s", quote[:40])
        return True
    except Exception as exc:                       # noqa: BLE001
        log.error("публикация не удалась: %s", exc)
        return False


@dp.message(Command("post"))
async def manual_post(message: Message) -> None:
    ok = await post_quote()
    await message.reply("Опубликовано ✅" if ok else "Не получилось, смотри логи ❌")


@dp.message(Command("ping"))
async def ping(message: Message) -> None:
    me = await bot.get_me()
    await message.reply(f"Живой. Я @{me.username}, канал: {CHANNEL_ID}")


@dp.message(F.text == "/start")
async def start(message: Message) -> None:
    await message.reply(
        "Бот канала.\n\n"
        "/post — опубликовать цитату сейчас\n"
        "/ping — проверить, что бот жив"
    )


async def scheduler() -> None:
    """Автопубликация по таймеру — того, чего в старой версии не было."""
    if POST_INTERVAL_HOURS <= 0:
        log.info("автопостинг выключен (POST_INTERVAL_HOURS=0)")
        return

    interval = POST_INTERVAL_HOURS * 3600
    log.info("автопостинг раз в %s ч", POST_INTERVAL_HOURS)
    while True:
        await asyncio.sleep(interval)
        await post_quote()


async def main() -> None:
    me = await bot.get_me()
    log.info("бот @%s запущен, канал %s", me.username, CHANNEL_ID)
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
