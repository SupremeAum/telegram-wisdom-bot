"""Загрузка и подготовка официального постера события.

Постер организатора почти всегда лучше сгенерированной карточки: его
рисовали, чтобы на него посмотрели, и организатор заинтересован в
репосте — ради этого афиша и делается яркой. Лента из одинаковых
градиентов, наоборот, читается как машинная.

Поэтому порядок такой: есть годный постер — берём его, нет — рисуем свою
карточку (afisha.card).

Что здесь происходит помимо скачивания: отсев мусора (логотипы, иконки,
заглушки «нет фото») и приведение к единому формату ленты без обрезки
содержимого — недостающее место добирается размытой копией самого
постера, как это делают в соцсетях.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageFilter

log = logging.getLogger(__name__)

CANVAS_W, CANVAS_H = 1080, 1350

# Мельче этого — почти наверняка логотип площадки или превью-заглушка,
# а не афиша. Растягивать такое до 1080px бессмысленно: будет каша.
MIN_SIDE = 400
MIN_PIXELS = 400 * 400

# Полосы и баннеры: в вертикальной ленте выглядят как ошибка вёрстки.
MIN_ASPECT, MAX_ASPECT = 0.4, 2.6

MAX_BYTES = 12 * 1024 * 1024
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class PosterRejected(Exception):
    """Постер есть, но не годится — причина в тексте исключения."""


def fetch(url: str, client: httpx.Client | None = None) -> Image.Image:
    """Скачивает постер и проверяет, что это действительно афиша."""
    owns_client = client is None
    client = client or httpx.Client(headers={"User-Agent": UA}, timeout=25.0,
                                    follow_redirects=True)
    try:
        response = client.get(url)
        response.raise_for_status()

        if len(response.content) > MAX_BYTES:
            raise PosterRejected(f"слишком большой файл: {len(response.content)} байт")

        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.startswith("image/"):
            raise PosterRejected(f"это не изображение: {content_type}")

        try:
            image = Image.open(BytesIO(response.content))
            image.load()
        except Exception as exc:                   # noqa: BLE001
            raise PosterRejected(f"не разбирается как картинка: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    _validate(image)
    return image.convert("RGB")


def _validate(image: Image.Image) -> None:
    width, height = image.size
    if min(width, height) < MIN_SIDE or width * height < MIN_PIXELS:
        raise PosterRejected(f"слишком мелкий: {width}x{height}")

    aspect = width / height
    if not MIN_ASPECT <= aspect <= MAX_ASPECT:
        raise PosterRejected(f"негодные пропорции: {width}x{height}")


def normalize(image: Image.Image) -> Image.Image:
    """Вписывает постер в формат ленты, ничего не обрезая.

    Кадрировать чужую афишу нельзя: обрежется имя артиста или дата.
    Поэтому постер вписывается целиком, а поля заполняются размытой
    увеличенной копией его же — фон получается в цветах самого постера.
    """
    if image.size == (CANVAS_W, CANVAS_H):
        return image

    # Фон: заполняем канву с обрезкой, потом размываем — детали не важны.
    background = _cover(image, CANVAS_W, CANVAS_H)
    background = background.filter(ImageFilter.GaussianBlur(38))
    # Приглушаем, чтобы фон не спорил с постером за внимание.
    background = Image.blend(background, Image.new("RGB", background.size,
                                                   (16, 16, 22)), 0.45)

    scale = min(CANVAS_W / image.width, CANVAS_H / image.height)
    fitted = image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    background.paste(
        fitted,
        ((CANVAS_W - fitted.width) // 2, (CANVAS_H - fitted.height) // 2),
    )
    return background


def _cover(image: Image.Image, width: int, height: int) -> Image.Image:
    """Масштабирует с заполнением всей области и центральной обрезкой."""
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(width, int(image.width * scale)), max(height, int(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def save(image: Image.Image, output_dir: Path, name: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}.jpg"
    # JPEG, а не PNG: фотопостер в PNG весит втрое больше без выигрыша.
    image.save(path, "JPEG", quality=88, optimize=True)
    return path


def try_build(url: str, output_dir: Path, name: str,
              client: httpx.Client | None = None) -> Path | None:
    """Постер → готовый файл. None, если постера нет или он не годится."""
    if not url:
        return None
    try:
        return save(normalize(fetch(url, client)), output_dir, name)
    except PosterRejected as exc:
        log.info("постер отклонён (%s): %s", exc, url)
    except Exception as exc:                       # noqa: BLE001 — источник внешний
        log.info("постер не загрузился (%s): %s", exc, url)
    return None
