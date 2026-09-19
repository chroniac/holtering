"""Команда `holtering`: запуск просмотрщика и проверка конфигурации."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from holtering.logging import configure_logging, get_logger
from holtering.settings import (
    Settings,
    config_dir_from_env,
    explain_sources,
    load_settings,
    use_config_dir,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holtering", description="Проверка холтеровской разметки")
    _add_config_dir(parser, default=None)
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="поднять просмотрщик записи")
    _add_config_dir(serve, default=argparse.SUPPRESS)
    serve.add_argument("--data", help="каталог с raw.scp и qrs.txt")
    serve.add_argument("--scp")
    serve.add_argument("--qrs")
    serve.add_argument(
        "--start", help="начало записи «ГГГГ-ММ-ДД ЧЧ:ММ:СС»; иначе из имени файла или секции 1"
    )
    serve.add_argument("--chest", help="метки каналов 6.., например V1,V2,V3,V4,V5,V6")
    serve.add_argument(
        "--invert",
        action="store_true",
        help="сменить знак всех отсчётов (docs/modules/scp-holter.md)",
    )
    serve.add_argument(
        "--gain",
        type=float,
        help="множитель к заявленным мВ/LSB, снятый с распечатки CardioSpy; "
        "без него масштаб напряжения считается некалиброванным",
    )
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)

    config = commands.add_parser("config", help="конфигурация")
    _add_config_dir(config, default=argparse.SUPPRESS)
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("check", help="собрать конфигурацию и показать, что откуда пришло")

    args = parser.parse_args(argv)
    if args.config_dir:
        use_config_dir(args.config_dir)
    if args.command == "serve":
        return run_serve(args)
    return config_check()


def _add_config_dir(parser: argparse.ArgumentParser, default: Any) -> None:
    parser.add_argument(
        "--config-dir",
        default=default,
        help=f"каталог с holtering.toml (по умолчанию {config_dir_from_env()})",
    )


def _overrides(args: argparse.Namespace) -> dict[str, Any]:
    record: dict[str, Any] = {}
    if args.data:
        record["scp"] = Path(args.data) / "raw.scp"
        record["qrs"] = Path(args.data) / "qrs.txt"
    for name in ("scp", "qrs", "start", "gain"):
        if getattr(args, name) is not None:
            record[name] = getattr(args, name)
    if args.chest:
        record["chest"] = args.chest.split(",")
    if args.invert:
        record["invert"] = True
    api = {
        name: getattr(args, name) for name in ("host", "port") if getattr(args, name) is not None
    }
    out: dict[str, Any] = {}
    if record:
        out["record"] = record
    if api:
        out["api"] = api
    return out


def run_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from holtering.analysis import build
    from holtering.api import create_app

    try:
        settings = load_settings(**_overrides(args))
    except ValidationError as exc:
        return _report_invalid(exc)
    configure_logging(settings.log)
    log = get_logger("holtering.cli")
    record = settings.record
    if _missing(settings, sys.stderr):
        return 2
    log.info("record.open", scp=str(record.scp), cache=str(record.cache_root))
    state = build(record)
    log.info(
        "analysis.ready",
        computed_s=state.analysis.summary.computed_s,
        episodes=len(state.analysis.episodes),
        url=f"http://{settings.api.host}:{settings.api.port}",
    )
    uvicorn.run(
        create_app(settings, state),
        host=settings.api.host,
        port=settings.api.port,
        log_config=None,
        access_log=False,
    )
    return 0


def config_check() -> int:
    out = sys.stdout
    out.write(f"каталог конфигурации: {config_dir_from_env()}\n")
    for name, path, data in explain_sources():
        where = str(path) if path else ("окружение" if name == "env" else "нет файла")
        out.write(f"\n[{name}] {where}\n")
        if data:
            out.write(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")
    try:
        settings = Settings()
    except ValidationError as exc:
        return _report_invalid(exc)
    out.write("\nитоговая конфигурация:\n")
    out.write(json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n")
    out.write(f"кэш и правки: {settings.record.cache_root}\n")
    return 1 if _missing(settings, out) else 0


def _missing(settings: Settings, out: TextIO) -> bool:
    absent = [str(p) for p in (settings.record.scp, settings.record.qrs) if not p.exists()]
    if absent:
        out.write(f"нет файлов записи: {', '.join(absent)}\n")
    return bool(absent)


def _report_invalid(exc: ValidationError) -> int:
    sys.stderr.write("конфигурация не собирается:\n")
    for error in exc.errors(include_url=False):
        sys.stderr.write(f"  {'.'.join(str(part) for part in error['loc'])}: {error['msg']}\n")
    return 1
