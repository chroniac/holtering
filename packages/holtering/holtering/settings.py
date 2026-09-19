"""Конфигурация: `holtering.toml` и переменные `HOLTERING_*`; таблица — docs/operations/config.md.

Единственный модуль, которому разрешено читать окружение; остальной код получает
готовый `Settings` из контейнера зависимостей.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

CONFIG_DIR_ENV = "HOLTERING_CONFIG_DIR"
DEFAULT_CONFIG_DIR = Path()
CONFIG_FILE = "holtering.toml"
DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class Section(BaseModel):
    """Секция конфигурации: незнакомый ключ — ошибка, а не молча проигнорированная опечатка."""

    model_config = ConfigDict(extra="forbid")


class RecordSettings(Section):
    scp: Path
    qrs: Path
    # Пусто — время съёма берётся из имени файла, затем из секции 1 (см. analysis.state.resolve_start).
    start: datetime | None = None
    chest: list[str] | None = None
    invert: bool = False
    # Множитель к заявленным мВ/LSB, снятый с распечатки CardioSpy; пусто — масштаб не калиброван.
    gain: float | None = None
    cache_dir: Path | None = None

    @property
    def cache_root(self) -> Path:
        """Пусто — рядом с записью: кэш и правки едут вместе с пациентом, каталог заведомо писаемый."""
        return self.cache_dir or self.scp.parent

    @property
    def cache_file(self) -> Path:
        stat = self.scp.stat()
        gain = f"-g{self.gain:g}" if self.gain is not None else ""
        invert = "-inv" if self.invert else ""
        name = f"{self.scp.stem}-{stat.st_size}-{int(stat.st_mtime)}{gain}{invert}.json"
        return self.cache_root / name


class ApiSettings(Section):
    host: str = "127.0.0.1"
    port: int = 8790
    static_dir: Path | None = DEFAULT_STATIC_DIR


class LogSettings(Section):
    level: str = "INFO"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HOLTERING_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    record: RecordSettings
    api: ApiSettings = ApiSettings()
    log: LogSettings = LogSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Ранний источник побеждает; секции сливаются, поэтому флаг `--gain` не стирает
        # остальной `[record]` из файла.
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=config_dir_from_env() / CONFIG_FILE),
        )


def config_dir_from_env() -> Path:
    return Path(os.environ.get(CONFIG_DIR_ENV, DEFAULT_CONFIG_DIR))


def use_config_dir(path: str | Path) -> None:
    """Флаг `--config-dir`: источники читают каталог сами, до сборки `Settings`."""
    os.environ[CONFIG_DIR_ENV] = str(path)


def load_settings(**overrides: Any) -> Settings:
    return Settings(**overrides)


def explain_sources() -> list[tuple[str, Path | None, dict[str, Any]]]:
    """Что и откуда пришло — для `holtering config check`."""
    path = config_dir_from_env() / CONFIG_FILE
    data = TomlConfigSettingsSource(Settings, toml_file=path)() if path.exists() else {}
    env = {k: v for k, v in os.environ.items() if k.startswith("HOLTERING_")}
    return [(CONFIG_FILE, path if path.exists() else None, data), ("env", None, env)]
