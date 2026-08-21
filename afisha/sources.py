"""Сбор событий из городских афиш Усть-Каменогорска.

Каждый источник изолирован: падение одного парсера (сменилась вёрстка,
сайт лёг) не должно ронять весь запуск. Поэтому collect() ловит ошибки
пер-источник и просто продолжает.

Внимание: вёрстка афиш меняется без предупреждения. Селекторы вынесены
в константы наверху каждого парсера, чтобы чинить их за одну правку.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from .models import Event

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TIMEOUT = httpx.Timeout(20.0)

MONTHS_RU_PARSE = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}

CATEGORY_KEYWORDS = {
    "concert": ("концерт", "музык", "джаз", "рок", "симфон", "филармон"),
    "theatre": ("спектакль", "театр", "драм", "комеди", "опер", "балет"),
    "expo": ("выставк", "экспози", "галере", "музей", "арт"),
    "kids": ("детск", "детям", "малыш", "школьн", "семейн", "сказк"),
    "party": ("вечеринк", "party", "диджей", "dj", "клуб"),
}


def guess_category(title: str, hint: str = "") -> str:
    """Определяет категорию по названию — от неё зависит палитра карточки."""
    haystack = f"{title} {hint}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(word in haystack for word in keywords):
            return category
    return "event"


def parse_ru_date(text: str, now: datetime | None = None) -> datetime | None:
    """Разбирает даты вида «12 сентября 19:00» / «12.09 в 19:00».

    Год на афишах обычно не пишут, поэтому берём ближайший будущий:
    «5 января» в декабре означает следующий год, а не прошедший.
    """
    now = now or datetime.now()
    text = text.strip().lower()

    # Дату вырезаем первой: иначе «28.08 20:00» разбирается как время
    # 28:08 — регулярка времени хватает точку в дате.
    day = month = None
    rest = text

    named = re.search(r"(\d{1,2})\s+([а-яё]{3,})", text)
    if named and MONTHS_RU_PARSE.get(named.group(2)[:3]):
        day = int(named.group(1))
        month = MONTHS_RU_PARSE[named.group(2)[:3]]
        rest = text[: named.start()] + text[named.end():]
    else:
        numeric = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./]\d{2,4})?\b", text)
        if numeric:
            day, month = int(numeric.group(1)), int(numeric.group(2))
            rest = text[: numeric.start()] + text[numeric.end():]

    if not day or not month or not 1 <= month <= 12 or not 1 <= day <= 31:
        return None

    # Время ищем только в остатке и только правдоподобное.
    hour, minute = 19, 0
    for candidate in re.finditer(r"\b(\d{1,2})[:.](\d{2})\b", rest):
        h, m = int(candidate.group(1)), int(candidate.group(2))
        if h <= 23 and m <= 59:
            hour, minute = h, m
            break

    for year in (now.year, now.year + 1):
        try:
            candidate = datetime(year, month, day, hour, minute)
        except ValueError:
            continue
        if candidate >= now - timedelta(hours=6):
            return candidate
    return None


def _image_url(card, base: str) -> str:
    """Достаёт URL постера из карточки события.

    Афиши отдают картинку по-разному: обычный src, ленивая загрузка через
    data-src, либо фон в style. Проверяем всё по очереди.
    """
    img = card.select_one("img")
    if img is not None:
        for attr in ("data-src", "data-original", "data-lazy", "src"):
            value = (img.get(attr) or "").strip()
            # Плейсхолдеры ленивой загрузки — прозрачный пиксель в base64.
            if value and not value.startswith("data:"):
                return _absolute(value, base)

    holder = card.select_one("[style*='background-image']")
    if holder is not None:
        style = holder.get("style", "")
        match = re.search(r"url\((['\"]?)(.+?)\1\)", style)
        if match:
            return _absolute(match.group(2).strip(), base)

    return ""


def _absolute(url: str, base: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"{base}{url}"
    return url


def _get(client: httpx.Client, url: str) -> BeautifulSoup | None:
    try:
        response = client.get(url)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except Exception as exc:                       # noqa: BLE001 — источник внешний
        log.warning("не удалось загрузить %s: %s", url, exc)
        return None


def from_ticketon(client: httpx.Client, days_ahead: int = 14) -> list[Event]:
    """ticketon.kz — билетный оператор, самые надёжные дата и цена.

    Сейчас почти всегда пуст: ticketon отвечает 403 на запросы с серверных
    адресов, в том числе с раннеров GitHub Actions. Источник оставлен на
    случай, если доступ появится; на счёт найденных событий он не влияет.
    """
    soup = _get(client, "https://ticketon.kz/ustkamenogorsk")
    if soup is None:
        return []

    events: list[Event] = []
    for card in soup.select("a[href*='/event/'], .event-item, .afisha-item"):
        title_el = card.select_one("h3, h2, .title, .event-title")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        date_el = card.select_one(".date, .event-date, time")
        starts_at = parse_ru_date(date_el.get_text(" ", strip=True)) if date_el else None
        if not starts_at:
            continue

        venue_el = card.select_one(".place, .venue, .event-place")
        price_el = card.select_one(".price, .event-price")
        href = card.get("href") or ""
        if href.startswith("/"):
            href = f"https://ticketon.kz{href}"

        events.append(Event(
            title=title,
            starts_at=starts_at,
            venue=venue_el.get_text(strip=True) if venue_el else "Усть-Каменогорск",
            category=guess_category(title),
            price=price_el.get_text(" ", strip=True) if price_el else "",
            url=href,
            image_url=_image_url(card, "https://ticketon.kz"),
            source="ticketon",
        ))
    return events


SXODIM_BASE = "https://sxodim.com"
SXODIM_CITY = "ustkamenogorsk"

# Карточка события на sxodim. Разведка вёрстки 21.08.2026 показала такую структуру:
#
#   <div class="impression-card" data-id="76769" data-category="Концерты"
#        data-minprice="6 000" data-title="…">
#     <div class="impression-card-image"><a href="…"><picture><img src="/uploads/…">
#     <a class="impression-card-title" href="…">Название</a>
#     <div class="impression-card-info">6000 тенге, 27 октября в 18:00, Филармония, ул. …</div>
#
# Всё нужное лежит либо в data-атрибутах, либо в одной строке info через запятую.
SXODIM_CARD = "div.impression-card"


def _sxodim_pages(days_ahead: int) -> list[str]:
    """Страницы sxodim, которые стоит обойти.

    Первой идёт поиск по диапазону дат — она отдаёт ровно нужный горизонт.
    Остальные подстраховывают: если поиск сменит адрес или вернёт пусто,
    события всё равно наберутся с недельной и главной страницы.
    """
    today = datetime.now()
    until = today + timedelta(days=days_ahead)
    return [
        (f"{SXODIM_BASE}/{SXODIM_CITY}/search-events"
         f"?date_from={today:%d.%m.%Y}&date_to={until:%d.%m.%Y}"),
        f"{SXODIM_BASE}/{SXODIM_CITY}/events/week",
        f"{SXODIM_BASE}/{SXODIM_CITY}",
    ]


def _split_info(info: str) -> tuple[datetime | None, str, str]:
    """Разбирает строку вида «6000 тенге, 27 октября в 18:00, Филармония, ул. …».

    Дату ищем посегментно, а не во всей строке: в цене тоже есть числа,
    и «6000 тенге» разбирается как «00 тен(геден)» — то есть как несуществующий
    месяц. Разделив по запятым, мы гарантированно смотрим только на дату.
    Что до сегмента с датой — цена, что после — площадка.
    """
    parts = [part.strip() for part in info.split(",") if part.strip()]
    for index, part in enumerate(parts):
        starts_at = parse_ru_date(part)
        if starts_at:
            price = ", ".join(parts[:index])
            venue = parts[index + 1] if index + 1 < len(parts) else ""
            return starts_at, price, venue
    return None, "", ""


def _sxodim_card(card) -> Event | None:
    """Собирает событие из одной карточки. None — если это не событие."""
    title_el = card.select_one("a.impression-card-title")
    title = (card.get("data-title") or "").strip()
    if not title and title_el is not None:
        title = title_el.get_text(strip=True)
    if not title:
        return None

    info_el = card.select_one(".impression-card-info")
    info = info_el.get_text(" ", strip=True) if info_el else ""
    starts_at, price_text, venue = _split_info(info)
    if not starts_at:
        # Без даты пост не запланировать, а гадать по названию нельзя.
        return None

    href = ""
    if title_el is not None:
        href = title_el.get("href") or ""
    if not href:
        link = card.select_one(".impression-card-image a[href]")
        href = link.get("href") if link else ""

    # data-minprice чище текста: «6 000» вместо «6000 теңгеден бастап».
    minprice = (card.get("data-minprice") or "").strip()
    price = f"от {minprice} ₸" if minprice else price_text

    return Event(
        title=title,
        starts_at=starts_at,
        venue=venue or "Усть-Каменогорск",
        category=guess_category(title, card.get("data-category") or ""),
        price=price,
        url=_absolute(href, SXODIM_BASE),
        description=info,
        image_url=_image_url(card, SXODIM_BASE),
        source="sxodim",
    )


def from_sxodim(client: httpx.Client, days_ahead: int = 14) -> list[Event]:
    """sxodim.com — основной источник: отдаёт обычный HTML без скриптов."""
    events: dict[str, Event] = {}

    for url in _sxodim_pages(days_ahead):
        soup = _get(client, url)
        if soup is None:
            continue

        cards = soup.select(SXODIM_CARD)
        added = 0
        for card in cards:
            event = _sxodim_card(card)
            if event is None:
                continue
            # data-id — самый надёжный ключ: одно событие попадает
            # и в поиск, и в недельную подборку.
            key = card.get("data-id") or event.fingerprint
            if key not in events:
                events[key] = event
                added += 1

        log.info("sxodim %s: карточек %d, событий %d", url, len(cards), added)
        if not cards:
            log.warning("на %s не нашлось ни одной карточки %s — "
                        "возможно, сменилась вёрстка", url, SXODIM_CARD)

    return list(events.values())


SOURCES = {"ticketon": from_ticketon, "sxodim": from_sxodim}


def collect(days_ahead: int = 14) -> list[Event]:
    """Обходит все источники, дедуплицирует и сортирует по дате."""
    horizon = datetime.now() + timedelta(days=days_ahead)
    collected: dict[str, Event] = {}

    with httpx.Client(headers={"User-Agent": UA}, timeout=TIMEOUT,
                      follow_redirects=True) as client:
        for name, parser in SOURCES.items():
            try:
                found = parser(client, days_ahead)
                log.info("%s: найдено %d событий", name, len(found))
            except Exception as exc:               # noqa: BLE001
                log.warning("источник %s упал: %s", name, exc)
                continue

            for event in found:
                if event.starts_at > horizon:
                    continue
                existing = collected.get(event.fingerprint)
                # При дубле оставляем запись с более полными данными.
                if existing is None or _richness(event) > _richness(existing):
                    collected[event.fingerprint] = event

    return sorted(collected.values(), key=lambda e: e.starts_at)


def _richness(event: Event) -> int:
    """Насколько запись информативна — для выбора между дублями."""
    return sum(bool(value) for value in
               (event.description, event.price, event.url, event.image_url))
