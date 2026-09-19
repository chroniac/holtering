# AGENTS.md — rules for AI agents and humans in this repository

A short set of rules for whoever writes code here. If a rule here conflicts
with a habit, the rule wins.

## What this is

`holtering` is a review tool for Holter annotations: a parser for the SCP-ECG
export of LabTech EC-12H / CardioSpy (`packages/scp-holter`), an audit of the
device labels and the printed protocol (`packages/holtering`, Litestar + numpy,
Python 3.14, `uv`), and the reviewer interface (`frontend`, Vite + TypeScript,
Bun + Biome). It ships as a web application on our server, not as a desktop exe
([ADR 0001](docs/adr/0001-web-app-not-desktop-exe.md)); the stack and its rules
are [ADR 0002](docs/adr/0002-stack.md).

Read first: [docs/README.md](docs/README.md) → [docs/adr/README.md](docs/adr/README.md)
→ [docs/modules/](docs/modules/). A decision that is not in an ADR has not been
made; propose it as an ADR, not as code.

## Boundaries that are not crossed

- Numerical analysis (`holtering/analysis`) is deterministic; thresholds and
  formulas change only together with an entry in `docs/modules/analysis.md` and
  a line in the CHANGELOG. A refactor must produce byte-identical API answers on
  the synthetic record (`tests/synth.py`).
- Real records (`*.scp`, `qrs.txt`, `*.overrides.json`) never enter the
  repository (`.gitignore`); tests and smoke runs use synthetic data only.
- Only `holtering/settings.py` reads the environment; `os.environ` elsewhere is
  forbidden by ruff (`TID251`).
- `scp_holter` does not import `holtering`; inside the application
  `holtering.cli` → `holtering.api` → `holtering.analysis` — enforced by
  `lint-imports`.
- Reviewer browsers are Chrome 109 / Firefox ESR 115 (Windows 7/8.1): the
  frontend is built for that target, and new CSS/JS features are checked
  against it.

## Code

- Handlers are thin: guard → service → response. `State` and the analysis know
  nothing about the framework.
- Types everywhere: `msgspec.Struct` for responses and the cache, pydantic only
  for `Settings`. `ruff` and `ty` must be clean.
- **Comments explain "why", never "what".** Banners and separators (`# ----`,
  `// ====`), comment blocks longer than 6 lines, commented-out code and
  `# TODO` without a task link are forbidden. Enforced by
  `scripts/check_comment_blocks.py`, `frontend/scripts/check-comments.ts`
  and `ruff` (`ERA001`).
- A docstring is one line and only where the name is not enough. Knowledge
  about formats and methodology lives in `docs/modules/*.md`.
- Tests cover behaviour and boundaries, not wiring.

## Commits and documentation

Conventional Commits; the subject is in English, lowercase after the colon,
imperative, ≤ 72 characters, no trailing period (`scripts/check_commits.py`).
A behaviour change means a line in `docs/CHANGELOG.md` under "Unreleased" and an
edit to the matching `docs/modules/*.md` or `docs/operations/*.md`; a
cross-cutting decision with alternatives means a new ADR. If you changed code in
`packages/`, bump the package version:
`uv version --package holtering --bump patch|minor|major`
(the parser is `--package scp-holter`, when it is the one that changed).

## Commands

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
