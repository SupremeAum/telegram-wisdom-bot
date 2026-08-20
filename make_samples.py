"""Генератор ДЕМО-образцов постов — для утверждения формата.

Данные событий здесь вымышленные (площадки настоящие, но афиши
не сверены с источниками). Результат кладётся в samples/, а не в
drafts/, поэтому команда `afisha.cli publish` его никогда не подхватит:
случайно опубликовать выдуманное событие нельзя.

Реальные посты делает `python -m afisha.cli draft`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from afisha.card import render
from afisha.compose import build_caption
from afisha.models import Event

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
CHANNEL = "@prosvetlyaka"

DEMO_EVENTS = [
    Event(
        title="Вечер органной музыки: Бах и Вивальди",
        starts_at=datetime(2026, 8, 28, 19, 0),
        venue="Восточно-Казахстанская областная филармония",
        category="concert",
        price="от 3 500 ₸",
        description=(
            "Камерная программа из барочной классики. Полтора часа "
            "органа под сводами зала на Протозанова — редкий для города "
            "формат, который стоит услышать живьём."
        ),
        url="https://ticketon.kz/ustkamenogorsk",
        source="demo",
    ),
    Event(
        title="Спектакль «Ревизор»",
        starts_at=datetime(2026, 8, 30, 18, 30),
        venue="Театр драмы имени Джамбула, ВКО",
        category="theatre",
        price="от 2 000 ₸",
        description=(
            "Гоголевская классика в постановке областного драмтеатра. "
            "Идёт два действия с антрактом."
        ),
        url="https://vko-teatr.kz/ru/afisha/",
        source="demo",
    ),
    Event(
        title="Выставка «Алтай: свет и камень»",
        starts_at=datetime(2026, 9, 5, 11, 0),
        venue="Областной музей искусств",
        category="expo",
        price="",
        description=(
            "Пейзажная живопись и минералы Рудного Алтая из фондов музея. "
            "Вход свободный, экспозиция работает до конца сентября."
        ),
        source="demo",
    ),
]


def main() -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)
    cards_dir = SAMPLES_DIR / "cards"

    for index, event in enumerate(DEMO_EVENTS, start=1):
        card_path = render(event, cards_dir)
        caption = build_caption(event, CHANNEL)

        text_path = SAMPLES_DIR / f"post-{index}.txt"
        text_path.write_text(caption, encoding="utf-8")

        print(f"[{index}] {event.title}")
        print(f"    карточка: {card_path}")
        print(f"    текст:    {text_path}")
        print(f"    длина подписи: {len(caption)} / 1024")
        print()


if __name__ == "__main__":
    main()
