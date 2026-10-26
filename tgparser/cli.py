"""Командная строка: python -m tgparser {words,short,check} ..."""
from __future__ import annotations

import argparse
import asyncio
import itertools
import os
import sys
from pathlib import Path
from typing import Iterable, Iterator

from . import statuses as st
from .generators import BUILTIN_LISTS, SHORT_PRESETS, iter_short, iter_words, read_wordlist
from .pipeline import Result, TooManyErrors, UsernameChecker, run_checks
from .rules import MAX_LEN, MIN_LEN_COLLECTIBLE, MIN_LEN_REGULAR, normalize
from .storage import ResultStore


def _csv_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tgparser",
        description="Поиск свободных юзернеймов Telegram: слова, бренды, крипта и 4-символьные.",
    )
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("общие настройки")
    g.add_argument("--out", type=Path, default=Path("results"), help="папка для результатов (по умолчанию results)")
    g.add_argument("--limit", type=int, help="проверить не больше N новых юзернеймов")
    g.add_argument("--dry-run", action="store_true", help="только показать кандидатов, ничего не проверять")
    g.add_argument("--recheck", action="store_true", help="перепроверить уже проверенные")
    g.add_argument("--concurrency", type=int, default=4, help="параллельных проверок (по умолчанию 4)")
    g.add_argument("--tme-delay", type=float, default=0.35, help="секунд между запросами к t.me (0.35)")
    g.add_argument("--fragment-delay", type=float, default=0.6, help="секунд между запросами к fragment.com (0.6)")
    g.add_argument("--no-fragment", action="store_true", help="не проверять fragment.com для 5+ символов")
    g.add_argument("--proxy", help="прокси, например http://user:pass@host:port или socks5://host:port")
    g.add_argument("--api", action="store_true", help="подтверждать находки через Telegram API (нужен .env)")
    g.add_argument("--api-delay", type=float, default=2.0, help="секунд между запросами к API (2.0)")
    g.add_argument("--max-flood-wait", type=int, default=900, help="при FloodWait дольше N секунд отключить API (900)")
    g.add_argument("--session", default="tgparser", help="файл сессии Telethon (tgparser.session)")

    sub = parser.add_subparsers(dest="command", required=True)

    words = sub.add_parser(
        "words",
        parents=[common],
        help="реальные слова, крипта и компании (5+ символов)",
        description="Проверка реальных слов, крипто-терминов и названий компаний.",
    )
    words.add_argument(
        "--lists",
        type=_csv_list,
        default=["crypto", "companies", "en", "ru"],
        help=f"списки через запятую: {', '.join(BUILTIN_LISTS)} или путь к своему .txt "
        "(по умолчанию crypto,companies,en,ru)",
    )
    words.add_argument("--min-len", type=int, default=MIN_LEN_REGULAR, help="минимальная длина (5)")
    words.add_argument("--max-len", type=int, default=12, help="максимальная длина (12)")

    short = sub.add_parser(
        "short",
        parents=[common],
        help="4-символьные юзернеймы (только через Fragment)",
        description="4-символьные юзернеймы. Шаблоны: L буква, V гласная, C согласная, D цифра, "
        "A буква или цифра; строчные буквы и цифры — как есть (например xDDD, LLLa, CVCV).",
    )
    short.add_argument(
        "--preset",
        type=_csv_list,
        help=f"пресеты через запятую: {', '.join(SHORT_PRESETS)} "
        "(по умолчанию pretty,pronounceable,letters, если не задан --pattern)",
    )
    short.add_argument("--pattern", action="append", default=[], help="свой шаблон, можно несколько раз")
    short.add_argument("--shuffle", action="store_true", help="проверять в случайном порядке")
    short.add_argument("--seed", type=int, help="seed для --shuffle, чтобы порядок повторялся")

    check = sub.add_parser(
        "check",
        parents=[common],
        help="свой список юзернеймов (файлы и/или имена)",
        description="Проверка своих юзернеймов: имена через пробел и/или .txt файлы (по одному в строке).",
    )
    check.add_argument("items", nargs="+", help="юзернеймы или пути к файлам")
    return parser


def collect_candidates(args: argparse.Namespace) -> Iterator[tuple[str, str]]:
    if args.command == "words":
        return iter_words(args.lists, args.min_len, min(args.max_len, MAX_LEN))
    if args.command == "short":
        presets = args.preset if args.preset is not None else ([] if args.pattern else ["pretty", "pronounceable", "letters"])
        return iter_short(presets, args.pattern, args.shuffle, args.seed)
    return _iter_custom(args.items)


def _iter_custom(items: Iterable[str]) -> Iterator[tuple[str, str]]:
    seen: set[str] = set()
    for item in items:
        path = Path(item)
        if path.is_file():
            names, source = read_wordlist(path), path.stem
        else:
            names, source = [normalize(item)], "manual"
        for name in names:
            if name and name not in seen and MIN_LEN_COLLECTIBLE <= len(name) <= MAX_LEN:
                seen.add(name)
                yield name, source


def print_result(result: Result) -> None:
    if result.status in st.FINDINGS:
        label = st.LABELS[result.status]
        print(f"[{label}] @{result.username}  ({result.source})  {result.detail}", flush=True)


async def check_all(args: argparse.Namespace, candidates: list[tuple[str, str]], store: ResultStore):
    from .web import FragmentChecker, TmeChecker, make_client

    api = None
    if args.api:
        api = _make_api_checker(args)
        await api.start()
    try:
        async with make_client(args.proxy) as client:
            checker = UsernameChecker(
                tme=TmeChecker(client, args.tme_delay),
                fragment=FragmentChecker(client, args.fragment_delay),
                api=api,
                fragment_for_long=not args.no_fragment,
            )

            def on_result(result: Result) -> None:
                store.add(result)
                print_result(result)

            return await run_checks(candidates, checker, on_result, max(1, args.concurrency), total=len(candidates))
    finally:
        if api:
            await api.stop()


def _make_api_checker(args: argparse.Namespace):
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    api_id, api_hash = os.environ.get("TG_API_ID"), os.environ.get("TG_API_HASH")
    if not api_id or not api_hash or not api_id.isdigit():
        raise SystemExit(
            "Для --api нужны TG_API_ID и TG_API_HASH (https://my.telegram.org → API development tools). "
            "Скопируйте .env.example в .env и заполните."
        )
    from .telegram_api import TelegramApiChecker

    return TelegramApiChecker(int(api_id), api_hash, args.session, args.api_delay, args.max_flood_wait)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    args = build_parser().parse_args(argv)
    try:
        candidates = collect_candidates(args)
    except (ValueError, OSError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        count = 0
        try:
            for name, source in itertools.islice(candidates, args.limit):
                print(f"{name}\t{source}")
                count += 1
        except BrokenPipeError:  # вывод обрезали через | head
            sys.stderr.close()
            return 0
        print(f"Всего кандидатов: {count}", file=sys.stderr)
        return 0

    store = ResultStore(args.out)
    try:
        todo = ((n, s) for n, s in candidates if args.recheck or not store.is_done(n))
        todo_list = list(itertools.islice(todo, args.limit))
        if not todo_list:
            print("Нечего проверять: всё уже есть в результатах (используйте --recheck).", file=sys.stderr)
            return 0
        print(f"К проверке: {len(todo_list)}. Результаты: {store.path}", file=sys.stderr)
        stats = asyncio.run(check_all(args, todo_list, store))
    except KeyboardInterrupt:
        print("\nОстановлено. Уже проверенное сохранено — при следующем запуске продолжу с этого места.", file=sys.stderr)
        stats = None
    except TooManyErrors as e:
        print(
            f"\nОстановлено: {e}\nПроверьте интернет, увеличьте --tme-delay или используйте --proxy. "
            "Уже проверенное сохранено.",
            file=sys.stderr,
        )
        return 1
    finally:
        written = store.write_findings()
        store.close()

    for status, path in written.items():
        print(f"{st.LABELS[status]}: {path}", file=sys.stderr)
    if stats and stats.get(st.ERROR):
        print(f"Ошибок: {stats[st.ERROR]} — они перепроверятся при следующем запуске.", file=sys.stderr)
    return 0
