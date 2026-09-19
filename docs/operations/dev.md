# Локальная разработка

Требования: `uv` ≥ 0.9, Python 3.14 (uv скачает сам), Bun для фронтенда.

```bash
uv sync --group dev
uv run python tests/synth.py data 600     # синтетическая запись: data/raw.scp + data/qrs.txt
uv run holtering serve --data data --start "2026-09-17 09:30:00"
cd frontend && bun install && bun run build && cd ..   # статика для http://127.0.0.1:8790/
cd frontend && bun run dev                              # dev-сервер с proxy /api → :8790
```

Реальная запись — `--data <каталог с raw.scp и qrs.txt>` или `--scp`/`--qrs`;
кэш тяжёлого прохода и ручные правки пишутся рядом с записью
([config](config.md)). Реальные записи в git не попадают (`.gitignore`).

## Проверки перед коммитом

Те же, что в CI (`.github/workflows/check.yml`):

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run lint-imports
uv run pytest -q
python scripts/check_comment_blocks.py
python scripts/check_commits.py --range origin/main..HEAD
cd frontend && bun run check && bun run comments && bun run typecheck && bun run build
```

`uvx pre-commit install --hook-type pre-commit --hook-type commit-msg` ставит
те же проверки хуками.

Рефакторинг анализа или API проверяется снимком ответов на синтетической
записи: `uv run python scripts/snapshot_api.py capture before` до правок,
`… capture after` после и `… compare before after` — тела 2xx обязаны
совпасть побайтно (кроме `computed_s`), у ошибок сравниваются статусы.

## Устройство репозитория

```
pyproject.toml              корень uv-workspace: dev-группа, контракты import-linter, ty, pytest
packages/scp-holter         scp_holter — парсер SCP-ECG LabTech, экспорт EDF+/SVG/CSV/NPY, CLI scp-holter
packages/holtering          holtering — settings.py, cli.py, api/, analysis/
frontend/                   Vite + TypeScript, Bun + Biome; сборка в frontend/dist
tests/                      pytest; synth.py — генератор синтетической записи
scripts/                    проверки комментариев и коммитов
docs/                       ADR, модули, операции, CHANGELOG
```

Границы держит `lint-imports`: `scp_holter` не импортирует `holtering`;
`holtering.cli` → `holtering.api` → `holtering.analysis`.
