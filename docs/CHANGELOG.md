# Изменения

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии —
semver по Conventional Commits. Каждое изменение добавляет строку под
«Unreleased»; при релизе раздел получает номер и дату.

## Unreleased

### Добавлено
- ADR 0001 (поставка — web-приложение, не exe) и ADR 0002 (стек: Litestar, uv-workspace,
  ruff/ty, msgspec, Dishka, pydantic-settings).
- Правила разработки: `AGENTS.md`, `docs/`, `ruff.toml`, `.editorconfig`, pre-commit,
  `scripts/check_{comment_blocks,commits}.py`, CI GitHub Actions (`hygiene`, `python`, `web`).
- Синтетическая запись `tests/synth.py` (12 отведений, 125 Гц, известные удары и ошибки
  прибора) как основа тестов и смоука без реальных данных; `scripts/snapshot_api.py` —
  снимок ответов API и сравнение двух снимков.
- Тесты: парсер (переполнение u16 в секции 6, раскладка lead-by-lead, границы окон,
  инверсия, cp1251-паспорт, монтаж, заголовок EDF), API (границы окон и лимиты, 404,
  ручные метки и их сохранение, вставка удара, ручное качество, дневник, `/api/raw`),
  анализ (NN-интервалы, серии, сон, вердикты на синтетике).
- Документация методики `docs/modules/analysis.md` и формата `docs/modules/scp-holter.md`,
  настроек `docs/operations/config.md`, разработки `docs/operations/dev.md`.

### Изменено
- uv-workspace из двух пакетов: `packages/scp-holter` (парсер, CLI `scp-holter`) и
  `packages/holtering` (анализ, API, CLI `holtering`); Python ≥ 3.14; границы держит
  `import-linter` (`holtering.cli` → `holtering.api` → `holtering.analysis`).
- HTTP-слой переписан с FastAPI на Litestar + Dishka (`holtering/api/{app,routes,views}.py`);
  ошибки — `application/problem+json`; пути, query-параметры и тела 2xx не изменились
  (снимок 36 ответов совпадает побайтно).
- Анализ переведён на `msgspec.Struct`: `analysis/report.py` → `analysis/state.py`,
  типизированные `Analysis`, `HeavyPass`, `BeatAudit`, `Episode`, `Overrides`; кэш и файл
  правок кодируются `msgspec.json`. Формулы, пороги и порядок вычислений не менялись.
- Конфигурация — pydantic-settings: `holtering.toml` + `HOLTERING_*` + флаги CLI, окружение
  читает только `holtering/settings.py`. Кэш тяжёлого прохода и правки врача лежат рядом с
  записью, а не в каталоге установки. Начало записи разрешается в слое записи
  (настройка → штамп `DATE…` в имени → секция 1).
- CLI: `holtering serve` и `holtering config check` вместо `python -m holtering`; structlog
  вместо `print`.
- Парсер: знания о формате и монтаже — в `docs/modules/scp-holter.md`, докстринги в одну
  строку, типы под `ty`; поведение и выгрузки побайтно те же.
- Фронтенд: Bun + Biome, `scripts/check-comments.ts`; сборка под Chrome 109 / Firefox ESR 115
  (Windows 7/8.1 у врачей); шрифты Inter и JetBrains Mono в сборке вместо Google Fonts —
  внешних запросов нет.

## 0.1.0 — 2026-09-18

- Прототип: парсер SCP-ECG LabTech, аудит меток прибора, эпизоды, семейства морфологии,
  шумовая карта, ручные правки, печатный протокол; FastAPI + Vite/TS.
