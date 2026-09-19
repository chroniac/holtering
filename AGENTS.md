# AGENTS.md — правила для ИИ-агентов и людей в этом репозитории

Короткий свод правил для того, кто пишет код здесь. Если правило отсюда
противоречит привычке — побеждает правило.

## Что это

`holtering` — проверка холтеровской разметки: парсер SCP-ECG экспорта
LabTech EC-12H / CardioSpy (`packages/scp-holter`), аудит меток прибора и
печатный протокол (`packages/holtering`, Litestar + numpy, Python 3.14, `uv`),
интерфейс врача (`frontend`, Vite + TypeScript, Bun + Biome). Поставка —
web-приложение на нашем сервере, не desktop-exe ([ADR 0001](docs/adr/0001-web-app-not-desktop-exe.md));
стек и правила — [ADR 0002](docs/adr/0002-stack.md).

Сначала читать: [docs/README.md](docs/README.md) → [docs/adr/README.md](docs/adr/README.md)
→ [docs/modules/](docs/modules/). Решение, которого нет в ADR, — не принято;
предлагай его как ADR, а не как код.

## Границы, которые не переходят

- Численный анализ (`holtering/analysis`) детерминирован; пороги и формулы
  меняются только вместе с записью в `docs/modules/analysis.md` и строкой в
  CHANGELOG. Рефакторинг обязан давать побайтно те же ответы API на
  синтетической записи (`tests/synth.py`).
- Реальные записи (`*.scp`, `qrs.txt`, `*.overrides.json`) в репозиторий не
  попадают (`.gitignore`); тесты и смоук — только на синтетике.
- Окружение читает только `holtering/settings.py`; `os.environ` в остальном
  коде запрещён ruff'ом (`TID251`).
- `scp_holter` не импортирует `holtering`; внутри приложения
  `holtering.cli` → `holtering.api` → `holtering.analysis` — держит `lint-imports`.
- Браузеры врачей — Chrome 109 / Firefox ESR 115 (Windows 7/8.1): фронтенд
  собирается под этот target, новые CSS/JS-возможности проверяются по нему.

## Код

- Обработчик тонкий: guard → сервис → ответ. `State` и анализ не знают о
  фреймворке.
- Типы везде: `msgspec.Struct` для ответов и кэша, pydantic — только для
  `Settings`. `ruff` и `ty` — без замечаний.
- **Комментарии — только «почему», никогда «что».** Запрещены баннеры и
  разделители (`# ----`, `// ====`), блоки комментариев длиннее 6 строк,
  закомментированный код, `# TODO` без ссылки на задачу. Проверяют
  `scripts/check_comment_blocks.py`, `frontend/scripts/check-comments.ts`
  и `ruff` (`ERA001`).
- Docstring — одна строка и только там, где имени недостаточно. Знания о
  формате и методике живут в `docs/modules/*.md`.
- Тесты — на поведение и границы, не на проводку.

## Коммиты и документация

Conventional Commits, тема ≤ 72 символов, без точки, повелительное
наклонение, один язык в теме (`scripts/check_commits.py`). Изменение
поведения — строка в `docs/CHANGELOG.md` под «Unreleased» и правка
соответствующего `docs/modules/*.md` или `docs/operations/*.md`; сквозное
решение с альтернативами — новый ADR. Изменил код в `packages/` — подними
версию пакета: `uv version --package holtering --bump patch|minor|major`
(парсер — `--package scp-holter`, когда меняется сам).

## Команды

```bash
uv sync --group dev
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run lint-imports
uv run pytest -q
python scripts/check_comment_blocks.py
python scripts/check_commits.py --range origin/main..HEAD
uvx pre-commit install --hook-type pre-commit --hook-type commit-msg
uv run holtering serve --data data          # data/raw.scp + data/qrs.txt
cd frontend && bun install && bun run check && bun run comments && bun run typecheck && bun run build
```
