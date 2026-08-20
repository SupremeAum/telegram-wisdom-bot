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
    "kids": ("детск", "малыш", "школьн", "семейн", "сказк"),
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


def from_ticketon(client: httpx.Client) -> list[Event]:
    """ticketon.kz — билетный оператор, самые надёжные дата и цена."""
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


def from_sxodim(client: httpx.Client) -> list[Event]:
    """sxodim.com — лучшие описания, много неконцертных событий."""
    soup = _get(client, "https://sxodim.com/ustkamenogorsk")
    if soup is None:
        return []

    events: list[Event] = []
    for card in soup.select("article, .event-card, .card"):
        title_el = card.select_one("h2, h3, .card-title")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)

        date_el = card.select_one("time, .date, .card-date")
        starts_at = parse_ru_date(date_el.get_text(" ", strip=True)) if date_el else None
        if not starts_at:
            continue

        link = card.select_one("a[href]")
        href = link.get("href", "") if link else ""
        if href.startswith("/"):
            href = f"https://sxodim.com{href}"

        desc_el = card.select_one("p, .card-description")
        venue_el = card.select_one(".place, .location")

        events.append(Event(
            title=title,
            starts_at=starts_at,
            venue=venue_el.get_text(strip=True) if venue_el else "Усть-Каменогорск",
            category=guess_category(title),
            url=href,
            description=desc_el.get_text(" ", strip=True)[:300] if desc_el else "",
            image_url=_image_url(card, "https://sxodim.com"),
            source="sxodim",
        ))
    return events


SOURCES = {"ticketon": from_ticketon, "sxodim": from_sxodim}


def collect(days_ahead: int = 14) -> list[Event]:
    """Обходит все источники, дедуплицирует и сортирует по дате."""
    horizon = datetime.now() + timedelta(days=days_ahead)
    collected: dict[str, Event] = {}

    with httpx.Client(headers={"User-Agent": UA}, timeout=TIMEOUT,
                      follow_redirects=True) as client:
        for name, parser in SOURCES.items():
            try:
                found = parser(client)
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
