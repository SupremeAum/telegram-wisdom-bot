"""CLI полуавтомата.

Рабочий цикл:
    python -m afisha.cli check      — диагностика бота и канала (+ тестовый пост)
    python -m afisha.cli draft      — собрать события, сделать карточки, сложить в drafts/
    python -m afisha.cli list       — показать, что готово к публикации
    python -m afisha.cli publish    — опубликовать утверждённое в Telegram
    python -m afisha.cli wa         — выгрузить посты для WhatsApp-канала

Ничего не уходит в канал без явной команды publish.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .card import render
from .compose import HTML, WHATSAPP, build_caption
from .models import Draft
from .poster import try_build as try_poster
from .publish import make_bot, publish_draft, run_diagnose, send_alert
from .whatsapp import export as export_whatsapp

ROOT = Path(__file__).resolve().parent.parent
DRAFTS_DIR = ROOT / "drafts"
CARDS_DIR = DRAFTS_DIR / "cards"
POSTERS_DIR = DRAFTS_DIR / "posters"
OUTBOX_WA = ROOT / "outbox" / "whatsapp"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("afisha")


def _telegram_footer() -> str:
    channel = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not channel:
        return ""
    handle = channel if channel.startswith("@") else f"@{channel}"
    return f"{handle} — куда сходить в Усть-Каменогорске"


def _whatsapp_footer() -> str:
    name = os.getenv("WHATSAPP_CHANNEL_NAME", "").strip()
    url = os.getenv("WHATSAPP_CHANNEL_URL", "").strip()

    # Название канала читатель и так видит над постом, повторять его
    # с расшифровкой — тавтология. Нужен призыв поделиться.
    lines: list[str] = []
    if name:
        lines.append(f"*{name}* — вся афиша города в одном канале")
    if url:
        lines.append(f"Поделись с теми, кто ищет куда сходить:\n{url}")
    return "\n".join(lines)


def _env(name: str, required: bool = True) -> str:
    value = os.getenv(name, "").strip()
    if required and not value:
        sys.exit(
            f"Не задана переменная {name}.\n"
            f"Скопируй .env.example в .env и заполни."
        )
    return value


def cmd_check(args: argparse.Namespace) -> None:
    token = _env("TELEGRAM_BOT_TOKEN")
    channel = _env("TELEGRAM_CHANNEL_ID")

    print(f"\nПроверяю связку бот → {channel}\n" + "─" * 52)
    for line in run_diagnose(token, channel, send_test=not args.no_post):
        print(line)
    print("─" * 52 + "\n")


def cmd_draft(args: argparse.Namespace) -> None:
    from .sources import collect

    events = collect(days_ahead=args.days)

    if not events:
        # Пустой результат — самая опасная поломка. Раньше запуск на нём
        # заканчивался зелёной галочкой, и неделю тишины в канале было
        # видно только по самому каналу. Теперь он падает и зовёт.
        print("Событий не найдено. Возможные причины:")
        print("  • сменилась вёрстка источника — проверь селекторы в afisha/sources.py")
        print("  • нет доступа к сайтам афиш из этой сети")

        if send_alert("⚠️ Афиша: сбор не нашёл ни одного события.\n"
                      "Скорее всего сменилась вёрстка источника — "
                      "загляни в лог последнего запуска."):
            print("Тревога отправлена в чат из TELEGRAM_ALERT_CHAT_ID.")
        else:
            print("Тревога никуда не ушла: задай секреты TELEGRAM_BOT_TOKEN "
                  "и TELEGRAM_ALERT_CHAT_ID, чтобы получать её в Telegram.")

        raise SystemExit(1)

    prefer_poster = os.getenv("PREFER_SOURCE_POSTER", "1").strip() != "0"
    created = posters = 0

    for event in events[: args.limit]:
        image_path, origin = _pick_image(event, prefer_poster)
        posters += origin == "постер"

        draft = Draft(
            event=event,
            caption=build_caption(event, footer=_telegram_footer(), fmt=HTML),
            card_path=str(image_path),
        )
        path = draft.save(DRAFTS_DIR)
        created += 1
        print(f"  ✓ {event.starts_at:%d.%m %H:%M}  {event.title[:48]}  [{origin}]")
        log.debug("черновик сохранён: %s", path)

    print(f"\nГотово черновиков: {created} → {DRAFTS_DIR}")
    print(f"Из них с постером источника: {posters}, со своей карточкой: {created - posters}")
    print("Просмотри картинки, затем: python -m afisha.cli publish")


def _pick_image(event, prefer_poster: bool) -> tuple[Path, str]:
    """Выбирает картинку для поста: постер организатора или своя карточка.

    Постер приоритетнее: его рисовали, чтобы на него смотрели, и
    организатор заинтересован в репосте. Своя карточка — запасной
    вариант, когда постера нет или он не проходит проверку.
    """
    if prefer_poster and event.image_url:
        poster_path = try_poster(
            event.image_url, POSTERS_DIR,
            f"{event.starts_at.date().isoformat()}-{event.fingerprint}",
        )
        if poster_path is not None:
            return poster_path, "постер"

    return render(event, CARDS_DIR), "карточка"


def _iter_drafts() -> list[tuple[Path, Draft]]:
    if not DRAFTS_DIR.exists():
        return []
    items = []
    for path in sorted(DRAFTS_DIR.glob("*.json")):
        try:
            items.append((path, Draft.load(path)))
        except Exception as exc:                   # noqa: BLE001
            log.warning("битый черновик %s: %s", path.name, exc)
    return items


def cmd_list(_: argparse.Namespace) -> None:
    drafts = _iter_drafts()
    if not drafts:
        print("Черновиков нет. Сначала: python -m afisha.cli draft")
        return

    print(f"\nЧерновиков: {len(drafts)}\n" + "─" * 52)
    for path, draft in drafts:
        mark = "опубликован" if draft.published else "ждёт"
        print(f"[{mark:>12}] {draft.event.starts_at:%d.%m %H:%M}  {draft.event.title}")
        print(f"{'':>15}карточка: {draft.card_path}")
        print(f"{'':>15}файл:     {path.name}")
    print("─" * 52 + "\n")


def cmd_publish(args: argparse.Namespace) -> None:
    token = _env("TELEGRAM_BOT_TOKEN")
    channel = _env("TELEGRAM_CHANNEL_ID")

    pending = [(p, d) for p, d in _iter_drafts() if not d.published]
    if args.only:
        pending = [(p, d) for p, d in pending if args.only in p.name]
    if not pending:
        print("Нечего публиковать.")
        return

    if args.limit:
        pending = pending[: args.limit]

    print(f"К публикации в {channel}: {len(pending)}")
    for _, draft in pending:
        print(f"  • {draft.event.starts_at:%d.%m %H:%M}  {draft.event.title}")

    if not args.yes:
        answer = input("\nПубликуем? [y/N] ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return

    asyncio.run(_publish_all(token, channel, pending, args.delay))


async def _publish_all(token: str, channel: str,
                       pending: list[tuple[Path, Draft]], delay: float) -> None:
    bot = make_bot(token)
    try:
        for index, (path, draft) in enumerate(pending):
            try:
                message_id = await publish_draft(bot, channel, draft)
                draft.published = True
                draft.save(DRAFTS_DIR)
                print(f"  ✓ опубликовано (message_id {message_id}): {draft.event.title}")
            except Exception as exc:               # noqa: BLE001
                print(f"  ✗ не удалось: {draft.event.title} — {exc}")
            # Пауза между постами: Telegram ограничивает частоту
            # сообщений в канал, пачка без задержки ловит 429.
            if delay and index < len(pending) - 1:
                await asyncio.sleep(delay)
    finally:
        await bot.session.close()


def cmd_wa(args: argparse.Namespace) -> None:
    """Готовит посты для ручной вставки в WhatsApp-канал.

    По умолчанию берёт всё, что ещё не опубликовано; --all выгружает и
    уже ушедшее в Telegram — Telegram и WhatsApp живут своими темпами,
    и «опубликовано» относится только к Telegram.
    """
    drafts = [d for _, d in _iter_drafts()]
    if not args.all:
        drafts = [d for d in drafts if not d.published]
    if args.limit:
        drafts = drafts[: args.limit]

    if not drafts:
        print("Нечего выгружать. Сначала: python -m afisha.cli draft")
        return

    written = export_whatsapp(drafts, OUTBOX_WA, footer=_whatsapp_footer())

    print(f"\nГотово постов: {len(written)} → {OUTBOX_WA}\n" + "─" * 52)
    for draft in drafts:
        print(f"  • {draft.event.starts_at:%d.%m %H:%M}  {draft.event.title}")
    print("─" * 52)
    print("У каналов WhatsApp нет API — открой канал, приложи картинку")
    print("и вставь текст из соответствующего .txt. Порядок в README.txt.\n")


def main(argv: list[str] | None = None) -> None:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(
        prog="afisha", description="Полуавтомат афиши Усть-Каменогорска")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="проверить бота и канал")
    p_check.add_argument("--no-post", action="store_true",
                         help="не отправлять тестовое сообщение")
    p_check.set_defaults(func=cmd_check)

    p_draft = sub.add_parser("draft", help="собрать события и сделать карточки")
    p_draft.add_argument("--days", type=int, default=14, help="горизонт в днях")
    p_draft.add_argument("--limit", type=int, default=10, help="сколько черновиков")
    p_draft.set_defaults(func=cmd_draft)

    p_list = sub.add_parser("list", help="показать черновики")
    p_list.set_defaults(func=cmd_list)

    p_pub = sub.add_parser("publish", help="опубликовать утверждённое")
    p_pub.add_argument("--yes", action="store_true", help="без подтверждения")
    p_pub.add_argument("--limit", type=int, default=0, help="максимум постов за раз")
    p_pub.add_argument("--only", default="", help="подстрока имени файла черновика")
    p_pub.add_argument("--delay", type=float, default=3.0,
                       help="пауза между постами, сек")
    p_pub.set_defaults(func=cmd_publish)

    p_wa = sub.add_parser("wa", help="выгрузить посты для WhatsApp-канала")
    p_wa.add_argument("--all", action="store_true",
                      help="включая уже опубликованные в Telegram")
    p_wa.add_argument("--limit", type=int, default=0, help="максимум постов")
    p_wa.set_defaults(func=cmd_wa)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
