# 0001. Delivery to doctors is a web application on our server, not a desktop exe

Status: accepted
Date: 2026-09-19

## Context

Doctors' workstations: Intel Core i3-5xxx (Broadwell-U, 2 cores), HDD, 4–8 GB
RAM, **Windows 7 / 8.1**. A record is a 259 MB `raw.scp` for 24 h. The
owner's first intention was to build a single `.exe` (Tauri or Electrobun) and,
for that, to rewrite the parser and the backend in Rust.

What was measured on the current code (i9-14900KF, SSD):

- the parser is an `np.memmap` over an int16 matrix, there is nothing to speed up;
- the heavy analysis pass (`State._heavy`) takes 1.2 s on a 24-hour record, it is
  computed once and cached;
- a warm import of `numpy + fastapi + uvicorn + pydantic` takes 0.8 s; the venv is
  1816 files, 58 MB: from a cold HDD that is tens of seconds `[assumption]`;
- leads are stored lead by lead with a stride of 21.6 MB, and the heavy pass reads only
  8 independent channels: on an HDD every 12-lead ECG window costs 12 cold-disk
  seeks.

## Decision

The doctor needs only a browser. The backend (Python, as it is) runs on our
server; the doctor opens a record over HTTPS. Data is uploaded from the clinic's
PC (in chunks, compressed), SCP section 1 is pseudonymised in the browser before
sending (tags 0/1/5/30 are zeroed out with the same length, tag 2 becomes a
pseudonym of the same length; 4/8/25/26 stay — the protocol needs age, sex and
the acquisition time). Protocol printing is server-side, headless Chromium ≥ 131
(`@page` margin boxes), and the doctor downloads a PDF. The record registry,
accounts, the access log and the retention period are separate ADRs before the
code.

## Rejected alternatives

- **Tauri / Electrobun + Rust or a TS port of the backend.** WebView2 is not
  supported on Windows 7/8.1 since January 2023; the shell will not start on the
  target machines. Without that constraint Rust would not have given a win in
  analysis speed — the hot code is already in numpy (C), and `report.py`/`protocol.py`
  are text; the win would only have been in size and startup.
- **Electron ≤ 22 (Chromium 108).** The only exe path on Win7 — 150 MB of
  browser without security updates, in medical software.
- **Tauri + a Python sidecar (PyInstaller).** The same cold start from an HDD,
  plus antivirus false positives on PyInstaller builds.
- **A local installation of the Python application on the doctor's PC.** Cold
  start, HDD seeks, a cache in the installation directory (not writable under
  `Program Files`), a cache key by mtime that is lost on copying.

## Consequences

- Doctors' browsers are frozen at Chrome 109 / Firefox ESR 115: `vite` builds
  for that target, `@page` margin boxes in CSS do not work there — hence
  server-side printing.
- The frontend does not call out to third parties (fonts are in the bundle, not
  from Google Fonts).
- The backend stays on Python; the move to the common stack ([ADR 0002](0002-stack.md))
  prepares it for multi-record mode, access guards and DI.
- Pseudonymisation must be length-preserving: the section 0 pointers are
  absolute offsets; the section and file CRCs are recomputed in the browser, and
  on the server they become an upload integrity check.
