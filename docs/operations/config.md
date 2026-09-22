# Configuration

Settings are assembled by the `holtering.settings` module; it is the only place
that reads the environment — the rest of the code receives a ready `Settings`
from the dependency container.

## Sources and precedence

The earlier source wins, sections are merged:

1. command-line arguments (`holtering serve --port 8791`);
2. `HOLTERING_*` environment variables;
3. the `holtering.toml` file in the configuration directory;
4. the defaults.

The configuration directory is the current directory; it is overridden by the
`HOLTERING_CONFIG_DIR` variable or the `--config-dir` flag. The application has
no secrets and no separate secrets file.

Nesting is expressed in the environment with a double underscore:
`HOLTERING_RECORD__GAIN=1.35`, `HOLTERING_API__PORT=8791`, `HOLTERING_LOG__LEVEL=DEBUG`.

An unknown key in the file or in a section is an error, not a silently ignored
typo.

## Settings

### `[record]` — the record

| Key | Type | Default | Meaning |
|---|---|---|---|
| `scp` | path | — (required) | SCP-ECG file with the signal |
| `qrs` | path | — (required) | export of the device labels, TSV "time⇥label", cp1251 |
| `start` | date and time | from the record | start of the record; empty — the `DATE…` stamp in the file name, then section 1 |
| `chest` | list of strings | none | names of channels 6…, for example `["V1","V2","V3","V4","V5","V6"]` |
| `invert` | yes/no | `false` | flip the sign of all samples (see docs/modules/scp-holter.md) |
| `gain` | number | none | multiplier for the mV/LSB stated on the CardioSpy printout; empty — the scale is uncalibrated |
| `cache_dir` | path | next to the record | where to put the heavy-pass cache and the reviewer overrides |

An empty `cache_dir` means the directory of the record itself. That way the
cache and the overrides travel with the patient, and the directory is known to
be writable. Two files appear in it: the heavy-pass cache (the name includes the
size, mtime, `gain`, `invert` and the number of the audit rules — the cache holds
verdicts, so changing the thresholds must not leave the old ones in place) and
`<name>.<patient id>.<date>.overrides.json` with the manual labels, the diary
and the protocol edits.

Without `gain` the amplitudes on the printouts are shown without a scale, and
ST, T and voltage are declared unassessed in the protocol.

### `[api]` — the server

| Key | Type | Default | Meaning |
|---|---|---|---|
| `host` | string | `127.0.0.1` | listening address |
| `port` | number | `8790` | port |
| `static_dir` | path | the repository's `frontend/dist` | the built frontend; empty or a missing directory — only the API is served |

### `[log]` — logs

| Key | Type | Default | Meaning |
|---|---|---|---|
| `level` | string | `INFO` | level of the root logger; uvicorn records go the same way |

## Example `holtering.toml`

```toml
[record]
scp = "C:/holter/2026-09-17/raw.scp"
qrs = "C:/holter/2026-09-17/qrs.txt"
start = "2026-09-17 09:30:00"
chest = ["V1", "V2", "V3", "V4", "V5", "V6"]
gain = 1.35

[api]
port = 8790

[log]
level = "INFO"
```

## Command line

```
holtering serve [--config-dir DIR] [--data DIR] [--scp FILE] [--qrs FILE]
                [--start "YYYY-MM-DD HH:MM:SS"] [--chest V1,V2,V3,V4,V5,V6]
                [--invert] [--gain X] [--host HOST] [--port PORT]
holtering config [--config-dir DIR] check
```

`--data DIR` is a shorthand for `DIR/raw.scp` and `DIR/qrs.txt`. Any flag
overrides both the environment and the file, but only its own field: `--gain`
does not erase the rest of `[record]`.

`holtering config check` prints the configuration directory, the contents of
`holtering.toml`, the `HOLTERING_*` variables, the resulting configuration and
the cache directory. It returns 1 if the configuration does not assemble or the
record files are missing.

## Quick start

```bash
uv run python tests/synth.py data 600     # synthetic record
uv run holtering serve --data data --start "2026-09-17 09:30:00"
```
