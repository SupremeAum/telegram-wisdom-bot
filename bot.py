import os
import random
import csv
import requests
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# Настройки
TOKEN = os.getenv("7143553038:AAE6zb78AiVbS8zHpgNeltw_jnWJKiCEGWU")
UNSPLASH_API_KEY = os.getenv("UNSPLASH_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")
CHANNEL_ID = "@t.me/prosvetlyaka"

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# Функция загрузки цитат из CSV
def load_quotes():
    with open("quotes.csv", "r", encoding="utf-8") as file:
        reader = csv.reader(file)
        return list(reader)

quotes = load_quotes()

# Функция поиска фото
def get_image(query):
    sources = [
        (f"https://api.unsplash.com/photos/random?query={query}&client_id={UNSPLASH_API_KEY}", "urls", "regular"),
        (f"https://api.pexels.com/v1/search?query={query}&per_page=1", "photos", "src", "large"),
        (f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={query}&image_type=photo", "hits", 0, "largeImageURL")
    ]
    
    for url, *keys in sources:
        headers = {"Authorization": PEXELS_API_KEY} if "pexels" in url else {}
        response = requests.get(url, headers=headers).json()
        try:
            img_url = response
            for key in keys:
                img_url = img_url[key]
            return img_url
        except (KeyError, IndexError, TypeError):
            continue
    return None

# Функция публикации поста
async def post_quote():
    quote, author = random.choice(quotes)
    caption = f"📜 *{quote}*\n\n— {author}\n\n🔗 [Подписаться на канал](https://t.me/{CHANNEL_ID.strip('@')})"
    image_url = get_image(author) or get_image("wisdom")
    
    if image_url:
        await bot.send_photo(CHANNEL_ID, photo=image_url, caption=caption, parse_mode="Markdown")
    else:
        await bot.send_message(CHANNEL_ID, caption, parse_mode="Markdown")

# Команда для запуска публикации вручную
@dp.message_handler(commands=["post"])
async def manual_post(message: types.Message):
    await post_quote()
    await message.reply("Цитата опубликована!")

# Запуск бота
if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
