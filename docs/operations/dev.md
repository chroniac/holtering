# Local development

Requirements: `uv` ≥ 0.9, Python 3.14 (uv downloads it itself), Bun for the
frontend.

```bash
uv sync --group dev
uv run python tests/synth.py data 600     # synthetic record: data/raw.scp + data/qrs.txt
uv run holtering serve --data data --start "2026-09-17 09:30:00"
cd frontend && bun install && bun run build && cd ..   # static files for http://127.0.0.1:8790/
cd frontend && bun run dev                              # dev server with proxy /api → :8790
```

For a real record use `--data <directory with raw.scp and qrs.txt>` or
`--scp`/`--qrs`; the heavy-pass cache and the reviewer overrides are written
next to the record ([config](config.md)). Real records never enter git
(`.gitignore`).

## Checks before a commit

The same ones as in CI (`.github/workflows/check.yml`):

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run lint-imports
uv run pytest -q
python scripts/check_comment_blocks.py
python scripts/check_commits.py --range origin/main..HEAD
cd frontend && bun run check && bun run comments && bun run typecheck && bun run build
```

`uvx pre-commit install --hook-type pre-commit --hook-type commit-msg` installs
the same checks as hooks.

A refactor of the analysis or the API is verified by a snapshot of the answers
on the synthetic record: `uv run python scripts/snapshot_api.py capture before`
before the edits, `… capture after` afterwards and
`… compare before after` — the 2xx bodies must match byte for byte (except
`computed_s`), and for errors the statuses are compared.

Timings for the README come from `uv run python tests/synth.py bench 86400 && uv run python scripts/bench.py bench`
(a 24-hour synthetic record; `bench/` is ignored by git).

## Repository layout

```
pyproject.toml              uv workspace root: dev group, import-linter contracts, ty, pytest
packages/scp-holter         scp_holter — LabTech SCP-ECG parser, EDF+/SVG/CSV/NPY export, scp-holter CLI
packages/holtering          holtering — settings.py, cli.py, api/, analysis/
frontend/                   Vite + TypeScript, Bun + Biome; build output in frontend/dist
  src/main.ts               fonts + boot()
  src/app/                  composition root: state.ts, actions.ts, keyboard.ts, stats.ts, boot.ts
  src/api/                  wire types (types.ts) and the fetch client (client.ts)
  src/lib/                  pure, DOM-free logic: time, nav (ranges/zoom), verdict, leads
  src/ui/                   shared DOM widgets: dom (el/svg), tabs, segbar, dumbbell
  src/views/<name>/         one folder per view: model.ts (types + pure logic), render.ts (DOM), index.ts
  tests/                    bun test for lib/, views/*/model.ts and app/state.ts
  plugins/prefer-arrow.grit Biome plugin: no function declarations
tests/                      pytest; synth.py — synthetic record generator
scripts/                    comment and commit checks
docs/                       ADRs, modules, operations, CHANGELOG
```

The boundaries are held by `lint-imports`: `scp_holter` does not import
`holtering`; `holtering.cli` → `holtering.api` → `holtering.analysis`.
