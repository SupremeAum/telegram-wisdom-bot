"""Тесты без внешних зависимостей: python tests.py

Покрывают то, что реально ломается: разбор дат с афиш, транслитерацию
для карточек, дедупликацию и лимит длины подписи Telegram.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

from afisha.compose import HTML, WHATSAPP, build_caption
from afisha.models import Draft, Event
from afisha.whatsapp import export as export_whatsapp
from afisha.sources import guess_category, parse_ru_date
from afisha.translit import is_cyrillic, latin_only

NOW = datetime(2026, 8, 20, 12, 0)
failures: list[str] = []


def check(name: str, got, expected) -> None:
    if got == expected:
        print(f"  ok   {name}")
    else:
        failures.append(name)
        print(f"  FAIL {name}: получили {got!r}, ждали {expected!r}")


def test_dates() -> None:
    print("разбор дат:")
    cases = {
        "12 сентября 19:00": "2026-09-12 19:00",
        "5 января в 18:30": "2027-01-05 18:30",   # год перекатывается вперёд
        "28.08 20:00": "2026-08-28 20:00",        # точка в дате != время
        "30 авг 18.30": "2026-08-30 18:30",
        "01.09.2026 12:00": "2026-09-01 12:00",
        "3 марта": "2027-03-03 19:00",            # время по умолчанию 19:00
        "белиберда": None,
        "13 месяца": None,                        # 13-го месяца не бывает
    }
    for text, expected in cases.items():
        got = parse_ru_date(text, NOW)
        check(repr(text), got.strftime("%Y-%m-%d %H:%M") if got else None, expected)


def test_translit() -> None:
    print("транслитерация:")
    check("Усть-Каменогорск", latin_only("Усть-Каменогорск"), "Ust-Kamenogorsk")
    check("Щукин", latin_only("Щукин"), "Shchukin")
    check("Ёлка", latin_only("Ёлка"), "Elka")
    check("нет кириллицы на выходе",
          is_cyrillic(latin_only("Концерт «Времена года» — Вивальди")), False)


def test_category() -> None:
    print("категории:")
    check("концерт", guess_category("Концерт органной музыки"), "concert")
    check("театр", guess_category("Спектакль «Ревизор»"), "theatre")
    check("выставка", guess_category("Выставка пейзажа"), "expo")
    check("прочее", guess_category("Городская ярмарка"), "event")


def test_dedupe() -> None:
    print("дедупликация:")
    a = Event(title="Концерт Кино", starts_at=datetime(2026, 9, 1, 19, 0),
              venue="Филармония", source="ticketon")
    b = Event(title="концерт  кино", starts_at=datetime(2026, 9, 1, 19, 30),
              venue="Обл. филармония", source="sxodim")
    c = Event(title="Концерт Кино", starts_at=datetime(2026, 9, 2, 19, 0),
              venue="Филармония", source="ticketon")
    check("одно событие в двух афишах = один ключ", a.fingerprint == b.fingerprint, True)
    check("другая дата = другой ключ", a.fingerprint == c.fingerprint, False)


def test_caption_limit() -> None:
    print("лимит подписи Telegram:")
    event = Event(
        title="Т" * 80, starts_at=NOW, venue="В" * 60, category="concert",
        price="от 1000 ₸", url="https://example.com/" + "x" * 80,
        description="Описание. " * 300,
    )
    caption = build_caption(event, footer="@channel")
    check("подпись <= 1024", len(caption) <= 1024, True)
    check("ссылка не потеряна", "Билеты" in caption, True)
    check("теги не потеряны", "#концерт" in caption, True)


def test_formats() -> None:
    print("разметка под площадки:")
    event = Event(
        title="Концерт «Кино» & Ко", starts_at=NOW, venue="Филармония",
        category="concert", price="от 1000 ₸", url="https://example.com/x",
        description="Описание <вечера>",
    )

    tg = build_caption(event, footer="@kuda_v_ustke", fmt=HTML)
    check("TG: жирный тегом", "<b>" in tg, True)
    check("TG: ссылка тегом", '<a href="https://example.com/x">' in tg, True)
    check("TG: амперсанд экранирован", "&amp;" in tg, True)
    check("TG: угловые скобки экранированы", "&lt;вечера&gt;" in tg, True)

    wa = build_caption(event, footer="*Куда в Усть-Кам*", fmt=WHATSAPP)
    check("WA: жирный звёздочками", "*Концерт «Кино» & Ко*" in wa, True)
    check("WA: нет HTML-тегов", "<b>" in wa or "<a href" in wa, False)
    check("WA: URL голым текстом", "https://example.com/x" in wa, True)
    check("WA: ничего не экранировано", "&amp;" in wa, False)

    try:
        build_caption(event, fmt="markdown")
        check("неизвестный формат отвергнут", False, True)
    except ValueError:
        check("неизвестный формат отвергнут", True, True)


def test_whatsapp_export(tmp_root: Path) -> None:
    print("выгрузка для WhatsApp:")
    event = Event(title="Спектакль «Ревизор»", starts_at=NOW,
                  venue="Драмтеатр", category="theatre", price="от 2000 ₸")
    card = tmp_root / "card.png"
    card.write_bytes(b"\x89PNG\r\n\x1a\n")          # достаточно для копирования
    draft = Draft(event=event, caption="ignored", card_path=str(card))

    outbox = tmp_root / "outbox"
    written = export_whatsapp([draft], outbox, footer="*Куда в Усть-Кам*")

    check("создан один текст", len(written), 1)
    check("текст на месте", written[0].exists(), True)
    check("картинка скопирована",
          any(p.suffix == ".png" for p in outbox.iterdir()), True)
    check("есть README", (outbox / "README.txt").exists(), True)

    body = written[0].read_text(encoding="utf-8")
    check("в тексте разметка WhatsApp", "*Спектакль «Ревизор»*" in body, True)
    check("в тексте нет HTML", "<b>" in body, False)


def test_poster_filter() -> None:
    print("отбор постеров:")
    from PIL import Image
    from afisha.poster import CANVAS_H, CANVAS_W, PosterRejected, _validate, normalize

    def accepted(size: tuple[int, int]) -> bool:
        try:
            _validate(Image.new("RGB", size))
            return True
        except PosterRejected:
            return False

    check("афиша 800x1200 принята", accepted((800, 1200)), True)
    check("квадрат 1000x1000 принят", accepted((1000, 1000)), True)
    check("логотип 120x120 отсеян", accepted((120, 120)), False)
    check("превью 300x300 отсеяно", accepted((300, 300)), False)
    check("широкий баннер 2000x600 отсеян", accepted((2000, 600)), False)
    check("узкая полоса 500x1400 отсеяна", accepted((500, 1400)), False)

    # Чужую афишу нельзя кадрировать: обрежется имя артиста или дата.
    for size in ((800, 1200), (1000, 1000), (1200, 800)):
        out = normalize(Image.new("RGB", size, (200, 60, 60)))
        check(f"{size[0]}x{size[1]} → формат ленты", out.size, (CANVAS_W, CANVAS_H))


def test_poster_url_extraction() -> None:
    print("извлечение URL постера:")
    from bs4 import BeautifulSoup
    from afisha.sources import _image_url

    def extract(html: str) -> str:
        return _image_url(BeautifulSoup(html, "html.parser"), "https://ticketon.kz")

    check("обычный src",
          extract('<div><img src="/img/a.jpg"></div>'), "https://ticketon.kz/img/a.jpg")
    check("ленивая загрузка data-src",
          extract('<div><img data-src="//cdn.kz/b.jpg" src="data:image/gif;base64,R0lG"></div>'),
          "https://cdn.kz/b.jpg")
    check("фон в style",
          extract("<div style=\"background-image:url('/c.jpg')\"></div>"),
          "https://ticketon.kz/c.jpg")
    check("абсолютный URL не трогаем",
          extract('<div><img src="https://x.kz/d.jpg"></div>'), "https://x.kz/d.jpg")
    check("картинки нет", extract("<div><p>нет</p></div>"), "")


def test_roundtrip() -> None:
    print("сериализация события:")
    event = Event(title="Тест", starts_at=NOW, venue="Зал", price="от 500 ₸")
    restored = Event.from_dict(event.to_dict())
    check("event -> dict -> event", restored, event)


if __name__ == "__main__":
    for suite in (test_dates, test_translit, test_category, test_dedupe,
                  test_caption_limit, test_formats, test_poster_filter,
                  test_poster_url_extraction, test_roundtrip):
        suite()

    with tempfile.TemporaryDirectory() as tmp:
        test_whatsapp_export(Path(tmp))

    print()
    if failures:
        print(f"ПРОВАЛЕНО: {len(failures)} — {', '.join(failures)}")
        sys.exit(1)
    print("все тесты прошли")
