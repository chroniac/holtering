# 0003. A record registry on one personal machine: upload, SQLite, one open record

Status: accepted
Date: 2026-09-22

## Context

[ADR 0001](0001-web-app-not-desktop-exe.md) put the application on a server and
left the registry, the upload and the accounts to separate ADRs. The server
turns out to be a single workstation in Kazakhstan (i9-14900KF, SSD, always on),
and the first user is one cardiologist who reads Holter records on a
Windows 7/8.1 machine with Chrome 109.

Today one process is one record: `RecordProvider` (`api/app.py`) is an
`APP`-scoped Dishka provider built from `Settings.record`, and the paths come
from `holtering.toml`. The doctor cannot put a record in, and there is nothing
to list.

What she exports from CardioSpy is four files. Measured on the reference
record (101 535 beats, 23 h 59 min):

| File | Size | What it is |
|---|---|---|
| `raw.scp` | 259.1 MB | the signal, 12 leads, 125 Hz — needed |
| `qrs.txt` | 1.2 MB | the device's annotation, `t_ms<TAB>label` — needed |
| `rr.txt` | 0.5 MB | RR intervals: the same numbers as `diff(qrs.txt)`, 101 470 of the 101 534 |
| `nn.txt` | 0.5 MB | a subset of `rr.txt` (100 326 rows), the device's own NN filter |

`rr.txt` and `nn.txt` are derived from the annotation, and the analysis derives
its own NN series (`rhythm.nn_intervals`, with the Malik filter for HRV), so
nothing in the code reads them.

## Decision

- **The upload takes the whole export, the registry keeps two files.** She drops
  all four; `rr.txt` and `nn.txt` are accepted and discarded with a line in the
  upload result, so that she never has to remember which two matter. A record is
  `raw.scp` + `qrs.txt`; either one missing is a rejected upload.
- **The browser pseudonymises section 1 before the first byte goes out**
  (ADR 0001) and the server verifies it: an upload whose tags 0/1/5/30 are not
  empty is rejected with 422. What the pseudonymisation protects against, and
  what it does not, is [ADR 0004](0004-what-the-data-is-protected-from.md).
- **Chunked, resumable upload.** 8 MiB parts, `PUT /api/uploads/{id}/{part}`,
  each part with its SHA-256; the server assembles them and checks the SCP
  section CRCs recomputed by the browser. 259 MB over a clinic uplink does not
  survive a single-request timeout, and a re-upload of 259 MB after a dropped
  Wi-Fi is not acceptable.
- **The registry is SQLite** (`<data>/registry.db`, stdlib `sqlite3`, WAL): one
  row per record — id (ULID), pseudonym, sex, age, acquisition start, duration,
  beats, upload time, status, `deleted_at`. No name, no diagnosis: the row is
  what the list view shows. Migrations are numbered `.sql` files applied on
  start.
- **On disk a record is a directory**: `<data>/records/<id>/{raw.scp,qrs.txt}`
  plus the heavy-pass cache and `*.overrides.json`, which already live next to
  the record (ADR 0002). Deleting a record is deleting the directory and setting
  `deleted_at`.
- **One open record per process.** `RecordProvider` becomes request-scoped and
  keyed by the record id, over an LRU of size one: opening a record is an
  `np.memmap` plus a 1.1 MB JSON cache, the heavy pass is 1.2 s if the cache is
  cold, and the reader works on one record at a time. A per-record `asyncio.Lock`
  serialises the overrides so that two tabs cannot interleave a write.

## Rejected alternatives

- **A manifest file per record and a directory scan.** No transactions, no
  index, and the list view becomes a `stat` storm on a few hundred records; the
  first concurrent delete corrupts it. SQLite is a file too, and it is in the
  standard library.
- **PostgreSQL.** A service to install, back up and update on a workstation, for
  a table that will hold hundreds of rows for one user.
- **Keeping one record per process and starting a process per record.** 250 MB
  of address space and a Python interpreter per open record on a machine that
  also has to render PDFs; and the registry would still be needed.
- **Storing all four files.** 1 MB of derived numbers per record that nothing
  reads, and a second annotation source that would eventually disagree with
  `qrs.txt`.
- **Accepting the record unpseudonymised and stripping the name on the server.**
  Then the name is on the operator's disk for the duration of the upload, which
  is exactly what ADR 0004 says must not happen.

## Consequences

- `Settings.record` stops being the way a record is chosen; `holtering serve`
  gets `--data <dir>` for the registry root, and the single-record flags stay for
  development and the synthetic record.
- The API grows a record dimension (`/api/records`, `/api/records/{id}/…`); the
  frontend grows a list view and an upload view. Existing handlers keep their
  shape under the record prefix.
- The heavy-pass cache key already contains the size, mtime, gain, inversion and
  the audit-rules number, so a re-upload of the same file reuses nothing and
  needs nothing invalidated — the record id is new.
- Disk: 260 MB per record. A year of two records a week is 27 GB; the retention
  rule is in ADR 0004.
