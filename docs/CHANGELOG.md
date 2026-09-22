# Changelog

The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions are semver by Conventional Commits. Every change adds a line under
"Unreleased"; on release the section gets a number and a date.

## Unreleased

### Added
- ADR 0001 (delivery is a web application, not an exe) and ADR 0002 (stack: Litestar,
  uv workspace, ruff/ty, msgspec, Dishka, pydantic-settings).
- ADR 0003 (a record registry on one personal machine: the four-file upload, SQLite,
  one open record per process) and ADR 0004 (what the doctor's data is protected from:
  pseudonymisation in the browser, the print path, the exposure, accounts, retention —
  and the operator of the host, who cannot be locked out and is told so).
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
- README with screenshots of the four views (`docs/img/`) and measurements on a synthetic
  24-hour record; `scripts/bench.py` reproduces the table (cold/warm start, recompute,
  endpoints, working set).
- The synthetic record has a circadian heart rate (night dip to ~54/min), so sleep estimation
  and day/night statistics are exercised on a 24-hour run.
- The note answers the same list of questions the recorder's own protocol prints: the
  duration of the monitoring and the number of analysed complexes, the ectopy split into
  single, paired and group beats, and a new section "Интервалы PQ, QT, сегмент ST".
  QT is measured there (`analysis/intervals.py`): an hourly median complex of lead II
  built from up to 400 steady sinus beats, QRS bounds by the 15 % slope threshold, end of
  T by the tangent at its steepest descent, QTc by Bazett — QT 401 ms / QTc 426 ms on the
  reference record against the device's 420 ms. PQ and ST are declared unmeasured with
  the reason: two reasonable rules for the onset of P disagree by up to 70 ms on that
  record, and an ST shift in millimetres needs the millivolt scale to be calibrated.

### Fixed
- Heart rate now matches what the recorder's own protocol prints, because both numbers are
  defined the same way: the mean comes from the Malik-filtered NN intervals (it was the
  unfiltered mean, 70 against the device's 72 on the reference record), and the minimum and
  maximum are the extremes of a sliding 15 s window instead of per-minute averages, which
  compressed both tails (44/148 against 48/141; the times land within 3 s of the device's
  strips). Calibrated against the CardioSpy protocol of a real 24-hour record — see
  `docs/modules/analysis.md`.
- An explicit `cache_dir` that does not exist yet is created on start instead of crashing on
  the first cache write (regression of the settings move; covered by a test).

### Changed
- Four checks in the label audit, each of which the reference record showed the device
  violating in bulk: prematurity is now required of a `V` label as well (an extrasystole is
  premature by definition — it used to be asked of `S` only), a measured QRS wider than
  240 ms is `too-wide` (no complex lasts that long; the ceiling leaves room for the width
  estimator, which reads the same synthetic shape as 160 and 208 ms), local noise above 25 %
  of the hour's QRS amplitude is `noisy` (the width is read off a 15 % slope threshold, so
  noise of that size eats the feature), and a label that arrives on the sinus schedule right
  after a rejected label is `on-schedule` — it is the ordinary sinus beat, made "premature"
  by its bogus neighbour. On the reference record the audit keeps 32 V and 58 S out of the
  device's 412 and 264, where it used to keep 104 and 117; the cardiologist's own reading of
  that record is 13 and 9, and the single ventricular pair and the absence of pauses, runs
  and AF now agree with his protocol exactly.
- The heavy-pass cache file carries the number of the audit rules (`-a2`): the cache stores
  verdicts, and its key was only the record's size, mtime, gain and inversion, so after a
  threshold change an existing cache would have kept serving the old verdicts.
- The rhythm reference for prematurity falls back to 20 intervals when no N→N pair is found
  within the usual six: inside a run of ectopic labels the reference disappeared exactly
  where it was needed, and a whole run of mislabelled sinus beats stayed `likely`.
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
- Frontend restructured into layers: `api/` (types + client), `lib/` (pure logic), `ui/`
  (shared widgets), `views/<name>/{model,render,index}.ts`, `app/` (state, actions, keyboard,
  boot) instead of 14 flat files; the 712-line `main.ts` is gone. Every `function` declaration
  became an arrow const, enforced by the Biome plugin `plugins/prefer-arrow.grit`;
  `verbatimModuleSyntax` in tsconfig. 61 `bun test` cases for the pure parts (time, nav,
  leads, overview binning, ecg auto-gain, templates scoring, report strips, app state
  transitions). DOM output of every view and the relabel flow are byte-identical to the
  previous build on the synthetic record.
- Frontend: Bun + Biome, `scripts/check-comments.ts`; the build targets Chrome 109 / Firefox ESR 115
  (doctors run Windows 7/8.1); the Inter and JetBrains Mono fonts are in the bundle instead of Google Fonts —
  there are no external requests.

## 0.1.0 — 2026-09-18

- Prototype: LabTech SCP-ECG parser, audit of device labels, episodes, morphology families,
  noise map, reviewer overrides, printed protocol; FastAPI + Vite/TS.
