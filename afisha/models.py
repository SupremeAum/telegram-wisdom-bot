"""Модель события и черновика поста."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class Event:
    """Одно событие городской афиши."""

    title: str
    starts_at: datetime
    venue: str
    category: str = "event"          # concert / theatre / expo / kids / party
    price: str = ""                  # "от 3000 ₸" или "" если бесплатно/неизвестно
    url: str = ""
    description: str = ""
    source: str = ""                 # ticketon / sxodim / yandex / manual
    image_url: str = ""

    @property
    def fingerprint(self) -> str:
        """Ключ дедупликации: одно событие в трёх афишах — один пост.

        Берём нормализованное название и дату (без времени): площадки часто
        расходятся во времени начала на 15-30 минут и в написании зала.
        """
        norm_title = "".join(ch for ch in self.title.lower() if ch.isalnum())
        key = f"{norm_title}|{self.starts_at.date().isoformat()}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["starts_at"] = self.starts_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        data = dict(data)
        data["starts_at"] = datetime.fromisoformat(data["starts_at"])
        return cls(**data)


@dataclass
class Draft:
    """Готовый пост, ожидающий утверждения."""

    event: Event
    caption: str
    card_path: str
    created_at: datetime = field(default_factory=datetime.now)
    published: bool = False

    @property
    def slug(self) -> str:
        return f"{self.event.starts_at.date().isoformat()}-{self.event.fingerprint}"

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.slug}.json"
        payload = {
            "event": self.event.to_dict(),
            "caption": self.caption,
            "card_path": self.card_path,
            "created_at": self.created_at.isoformat(),
            "published": self.published,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Draft":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            event=Event.from_dict(payload["event"]),
            caption=payload["caption"],
            card_path=payload["card_path"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            published=payload.get("published", False),
        )
