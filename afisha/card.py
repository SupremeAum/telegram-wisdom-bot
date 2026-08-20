"""Генерация карточки события.

Правило: на изображении — только латиница. Русские названия
транслитерируются (см. afisha.translit). Полный русский текст живёт
в подписи к посту, где типографика не ломается.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import Event
from .translit import latin_only

CARD_W, CARD_H = 1080, 1350
MARGIN = 84

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Палитра по категориям: фон-градиент + акцент.
# Тёмная база выбрана намеренно — карточка должна читаться как единый
# бренд в ленте, где вокруг светлые пользовательские фото.
PALETTE = {
    "concert": {"top": (26, 22, 58), "bottom": (72, 28, 92), "accent": (255, 122, 89)},
    "theatre": {"top": (28, 20, 26), "bottom": (92, 30, 44), "accent": (240, 190, 110)},
    "expo":    {"top": (18, 34, 44), "bottom": (26, 74, 86), "accent": (118, 220, 200)},
    "kids":    {"top": (24, 40, 70), "bottom": (28, 96, 120), "accent": (255, 205, 90)},
    "party":   {"top": (34, 16, 44), "bottom": (96, 24, 78), "accent": (255, 105, 160)},
    "event":   {"top": (22, 26, 40), "bottom": (44, 54, 86), "accent": (126, 168, 255)},
}

MONTHS_LAT = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}
WEEKDAYS_LAT = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

BRAND = "KUDA V UST-KE"


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONTS_DIR / f"Inter-{weight}.ttf"
    if path.exists():
        return ImageFont.truetype(str(path), size)
    # Фолбэк на системный шрифт, чтобы рендер не падал на голой машине.
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)


def _gradient(top: tuple, bottom: tuple) -> Image.Image:
    """Вертикальный градиент во всю карточку."""
    base = Image.new("RGB", (1, CARD_H))
    draw = ImageDraw.Draw(base)
    for y in range(CARD_H):
        ratio = y / (CARD_H - 1)
        draw.point(
            (0, y),
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3)),
        )
    return base.resize((CARD_W, CARD_H), Image.Resampling.BILINEAR)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
          max_width: int) -> list[str]:
    """Перенос по словам под заданную ширину."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_title(draw: ImageDraw.ImageDraw, text: str, max_width: int,
               max_lines: int = 4) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Подбирает кегль так, чтобы заголовок уложился в max_lines строк."""
    for size in range(96, 47, -4):
        font = _font("Black", size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font("Black", 48)
    lines = _wrap(draw, text, font, max_width)[:max_lines]
    return font, lines


def render(event: Event, output_dir: Path) -> Path:
    """Рисует карточку события и возвращает путь к PNG."""
    colors = PALETTE.get(event.category, PALETTE["event"])
    accent = colors["accent"]

    image = _gradient(colors["top"], colors["bottom"]).convert("RGBA")

    # Диагональная акцентная полоса — держит композицию и делает карточку
    # узнаваемой в ленте. Кладём полупрозрачным слоем, а не сплошной
    # заливкой: непрозрачный акцент поверх градиента даёт грязный цвет.
    band_top_left, band_top_right = CARD_H - 300, CARD_H - 470
    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).polygon(
        [(0, band_top_left), (CARD_W, band_top_right), (CARD_W, CARD_H), (0, CARD_H)],
        fill=(*accent, 38),
    )
    image = Image.alpha_composite(image, overlay)

    draw = ImageDraw.Draw(image)
    # Тонкая линия по кромке полосы — делает диагональ намеренной.
    draw.line([(0, band_top_left), (CARD_W, band_top_right)], fill=(*accent, 190), width=3)

    content_w = CARD_W - MARGIN * 2

    # --- Шапка: бренд ---
    brand_font = _font("Bold", 30)
    draw.text((MARGIN, MARGIN), BRAND, font=brand_font, fill=accent)
    brand_w = draw.textlength(BRAND, font=brand_font)
    draw.line(
        [(MARGIN, MARGIN + 46), (MARGIN + brand_w, MARGIN + 46)],
        fill=accent, width=3,
    )

    # --- Блок даты ---
    date_y = MARGIN + 130
    day_font = _font("Black", 150)
    day_text = f"{event.starts_at.day:02d}"
    draw.text((MARGIN, date_y), day_text, font=day_font, fill=(255, 255, 255))
    day_w = draw.textlength(day_text, font=day_font)

    month_font = _font("Bold", 46)
    draw.text(
        (MARGIN + day_w + 24, date_y + 26),
        MONTHS_LAT[event.starts_at.month],
        font=month_font, fill=accent,
    )
    meta_font = _font("Medium", 32)
    draw.text(
        (MARGIN + day_w + 24, date_y + 88),
        f"{WEEKDAYS_LAT[event.starts_at.weekday()]}  ·  "
        f"{event.starts_at.strftime('%H:%M')}",
        font=meta_font, fill=(215, 215, 225),
    )

    # --- Заголовок ---
    # Центрируем блок в свободной зоне между датой и диагональю: при
    # фиксированном отступе короткие названия оставляли дыру в середине.
    title = latin_only(event.title).upper()
    title_font, title_lines = _fit_title(draw, title, content_w)
    line_h = int(title_font.size * 1.08)

    zone_top, zone_bottom = date_y + 200, band_top_right - 60
    title_h = len(title_lines) * line_h
    title_y = max(zone_top, zone_top + (zone_bottom - zone_top - title_h) // 2)

    for index, line in enumerate(title_lines):
        draw.text((MARGIN, title_y + index * line_h), line,
                  font=title_font, fill=(255, 255, 255))

    # --- Низ карточки: собираем снизу вверх, чтобы блоки не наезжали ---
    city_font = _font("Medium", 26)
    city_y = CARD_H - MARGIN - 26
    draw.text((MARGIN, city_y), "UST-KAMENOGORSK  ·  OSKEMEN",
              font=city_font, fill=(235, 235, 245))

    cursor = city_y - 42

    # Плашка есть всегда: «бесплатно» — такой же значимый сигнал, как цена.
    price_font = _font("Bold", 34)
    price = _format_price(event.price) if event.price else "FREE ENTRY"
    pad_x, pad_y = 26, 15
    price_w = draw.textlength(price, font=price_font)
    chip_h = 34 + pad_y * 2
    chip_y = cursor - chip_h
    draw.rounded_rectangle(
        [MARGIN, chip_y, MARGIN + price_w + pad_x * 2, chip_y + chip_h],
        radius=14, fill=accent,
    )
    draw.text((MARGIN + pad_x, chip_y + pad_y - 2), price,
              font=price_font, fill=(22, 20, 32))
    cursor = chip_y - 30

    venue_font = _font("SemiBold", 38)
    venue_lines = _wrap(draw, latin_only(event.venue), venue_font, content_w)[:2]
    venue_y = cursor - len(venue_lines) * 48
    for index, line in enumerate(venue_lines):
        draw.text((MARGIN, venue_y + index * 48), line,
                  font=venue_font, fill=(255, 255, 255))

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{event.starts_at.date().isoformat()}-{event.fingerprint}.png"
    image.convert("RGB").save(path, "PNG", optimize=True)
    return path


def _format_price(price: str) -> str:
    """Готовит цену для плашки: латиница, верхний регистр, «₸» → KZT."""
    text = latin_only(price).replace("₸", "KZT").replace("тг", "KZT")
    text = text.replace("ot ", "FROM ").replace("Ot ", "FROM ")
    if "KZT" not in text.upper() and any(ch.isdigit() for ch in text):
        text = f"{text} KZT"
    return " ".join(text.upper().split())
