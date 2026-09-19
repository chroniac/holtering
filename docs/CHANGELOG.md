# Changelog

The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions are semver by Conventional Commits. Every change adds a line under
"Unreleased"; on release the section gets a number and a date.

## Unreleased

### Added
- ADR 0001 (delivery is a web application, not an exe) and ADR 0002 (stack: Litestar,
  uv workspace, ruff/ty, msgspec, Dishka, pydantic-settings).
- Development rules: `AGENTS.md`, `docs/`, `ruff.toml`, `.editorconfig`, pre-commit,
  `scripts/check_{comment_blocks,commits}.py`, CI GitHub Actions (`hygiene`, `python`, `web`).
- Synthetic record `tests/synth.py` (12 leads, 125 Hz, known beats and device
  errors) as the basis for tests and smoke runs without real data; `scripts/snapshot_api.py` —
  a snapshot of API responses and a comparison of two snapshots.
- Tests: parser (u16 overflow in section 6, lead-by-lead layout, window boundaries,
  inversion, cp1251 patient record, montage, EDF header), API (window boundaries and limits, 404,
  manual labels and their persistence, beat insertion, manual quality, diary, `/api/raw`),
  analysis (NN intervals, runs, sleep, verdicts on the synthetic record).
- Documentation of the method in `docs/modules/analysis.md` and of the format in `docs/modules/scp-holter.md`,
  of the settings in `docs/operations/config.md`, of development in `docs/operations/dev.md`.

### Changed
- uv workspace of two packages: `packages/scp-holter` (parser, CLI `scp-holter`) and
  `packages/holtering` (analysis, API, CLI `holtering`); Python ≥ 3.14; the boundaries are held by
  `import-linter` (`holtering.cli` → `holtering.api` → `holtering.analysis`).
- The HTTP layer was rewritten from FastAPI to Litestar + Dishka (`holtering/api/{app,routes,views}.py`);
  errors are `application/problem+json`; paths, query parameters and 2xx bodies did not change
  (a snapshot of 36 responses matches byte for byte).
- Analysis moved to `msgspec.Struct`: `analysis/report.py` → `analysis/state.py`,
  typed `Analysis`, `HeavyPass`, `BeatAudit`, `Episode`, `Overrides`; the cache and the
  overrides file are encoded with `msgspec.json`. Formulas, thresholds and the order of
  computation did not change.
- Configuration via pydantic-settings: `holtering.toml` + `HOLTERING_*` + CLI flags, the
  environment is read only by `holtering/settings.py`. The heavy-pass cache and reviewer
  overrides live next to the record, not in the installation directory. The record start is
  resolved in the record layer (setting → `DATE…` stamp in the file name → section 1).
- CLI: `holtering serve` and `holtering config check` instead of `python -m holtering`; structlog
  instead of `print`.
- Parser: knowledge of the format and the montage lives in `docs/modules/scp-holter.md`, docstrings are
  single-line, types pass `ty`; behaviour and exports are byte for byte the same.
- Frontend: Bun + Biome, `scripts/check-comments.ts`; build targets Chrome 109 / Firefox ESR 115
  (doctors run Windows 7/8.1); the Inter and JetBrains Mono fonts are in the bundle instead of Google Fonts —
  there are no external requests.

## 0.1.0 — 2026-09-18

- Prototype: LabTech SCP-ECG parser, audit of device labels, episodes, morphology families,
  noise map, reviewer overrides, printed protocol; FastAPI + Vite/TS.
