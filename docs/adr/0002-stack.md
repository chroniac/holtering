# 0002. Stack and rules: Litestar, uv workspace, ruff/ty, msgspec, Dishka, pydantic-settings

Status: accepted
Date: 2026-09-19

## Context

A prototype in four commits: FastAPI in a single file, argparse + `os.environ`
in `config.py`, `print` instead of logs, dicts instead of types, no tests,
essay-length docstrings, `# ----` banners. Ahead is a web application with a
record registry, uploads, accounts and an access log
([ADR 0001](0001-web-app-not-desktop-exe.md)). The maintainers already have
production services on one stack (Litestar, Dishka, route guards, `Settings`
from TOML, logs) and one set of code rules; a second dialect for the sake of a
small repository costs more than repeating that set in full.

## Decision

The same stack and the same rules, with no adaptation "for a small project":

- a uv workspace of two packages: `packages/scp-holter` (parser, its own CLI
  `scp-holter`) and `packages/holtering` (analysis, API, CLI `holtering`);
  the boundaries are held by `import-linter`;
- Litestar 2.x, async handlers with `@inject` from Dishka, `msgspec.Struct`
  for responses, the heavy-pass cache and the overrides file; problem+json for
  errors; frontend static files from the same process;
- `Settings` (pydantic-settings) from `holtering.toml` + `HOLTERING_*`;
  `os.environ` only in `settings.py`; `secrets.toml` will appear with the first
  secret;
- `ruff` (the full rule set from `ruff.toml`), `ty`, pytest on behaviour,
  structlog instead of `print`;
- comments only about "why", single-line docstrings, Conventional Commits,
  documentation in the same change; the checks
  `scripts/check_comment_blocks.py`, `scripts/check_commits.py`, and on the
  frontend Biome and `scripts/check-comments.ts`.

The numerical analysis does not change with the move: the API responses on the
synthetic record (`tests/synth.py`) match the prototype's responses byte for byte
(a snapshot of 36 responses before and after, `scripts/snapshot_api.py`).

## Rejected alternatives

- **Keep FastAPI.** It works, but guards, scoped DI, SSE and problem+json are
  built into Litestar, and the multi-record version with access control will need
  all of them. Moving 20 handlers costs a day, later it would cost a week.
- **Rewrite the backend in Rust.** Rust does not speed up numpy; half of the code
  is the Russian text of the protocol; the thresholds are still being calibrated,
  and a port would freeze them in two languages. The motive (a single exe) is
  removed by ADR 0001.
- **Rewrite the backend in TypeScript (one language with the frontend).** The same
  argument about calibration; the parser and the method stay the reference
  implementation in Python.
- **The same stack but "lightweight": no Dishka, no workspace.** A second dialect
  of the rules costs more than one extra provider.

## Consequences

- Handlers are async, computations are inline: the application is single-user, and
  blocking the event loop for tens to hundreds of milliseconds is acceptable;
  a per-record lock will appear together with the record registry.
- The heavy-pass cache and the overrides live next to the record (`scp.parent`) and
  not in the installation directory: they travel with the patient, and the
  directory is writable by definition.
- Every change to the method is a line in `docs/modules/analysis.md` and the
  CHANGELOG; refactoring is verified by the same snapshot of responses.
