# 0004. What the doctor's data is protected from, and what it is not

Status: accepted
Date: 2026-09-22

## Context

The host is one person's workstation ([ADR 0003](0003-registry-on-a-personal-host.md)),
and that person has root on it. The doctor asked for her records to be protected
from him as well — not out of suspicion, but because a Holter record is medical
secrecy: in Kazakhstan medical data is personal data of restricted access under
the law "О персональных данных и их защите" (№ 94-V, 21.05.2013), and the duty
of secrecy of a medical worker is article 273 of the Health Code
(№ 360-VI). The operator is not the doctor's employer and has no lawful reason
to read a patient's name. (Pointers, not legal advice; the deployment needs a
lawyer's reading before it takes a real patient.)

What cannot be promised has to be said first: the operator serves the
JavaScript, runs the process and owns the RAM. Any design where the analysis
runs on his machine can be defeated by an operator who changes the code. The
useful question is therefore not "can he be locked out" but "what does he see if
he does nothing special, and what does it cost him to see more".

## Decision

**1. The identity never arrives.** The browser pseudonymises SCP section 1
before the upload (ADR 0001: tags 0/1/5/30 zeroed at the same length, tag 2
replaced by a pseudonym of the same length, CRCs recomputed), and the server
rejects an upload that still carries them. The map pseudonym → patient lives in
the doctor's browser (IndexedDB) and, so that she can move between machines, is
also stored on the server as a blob encrypted in the browser: AES-GCM with a key
derived from her passphrase by PBKDF2-SHA-256 (WebCrypto, 600 000 iterations —
Argon2 would need a wasm bundle that Chrome 109 has to download on every cold
start). The server stores ciphertext, a salt and an IV.

**2. What the operator sees when he does nothing special**: the de-identified
signal, sex, age, the acquisition timestamps, the audit verdicts and the text of
the conclusion. That is not anonymous data — a 24-hour ECG with a date
re-identifies a person to anyone who knows who wore the recorder that day — so
the disk is encrypted (BitLocker) and so are the backups. It is pseudonymous
data, and the honest claim is exactly that.

**3. Printing decides where the name goes.** The protocol is rendered on the
server (ADR 0001: Chrome 109 has no `@page` margin boxes), so a named PDF means
the name reaches the process. The setting `print.identity`:

- `none` — the PDF carries the pseudonym; the name never leaves the browser;
- `request` — the browser sends the name with the print request, the process
  holds it in RAM for the render, and it is written neither to disk nor to the
  log (the access log records the record id, never the payload).

The default is `request`, because a protocol without a name is not a document a
clinic can file, and the price is stated here rather than hidden. The name is in
the operator's RAM for the duration of one render.

**4. The exposure must not add a third party.** Options for reaching a
workstation behind a home ISP:

| Path | Who terminates TLS | Windows 7 client | Verdict |
|---|---|---|---|
| Public IP, port 443, Caddy + Let's Encrypt | the host | browser only | preferred |
| Cloudflare Tunnel | Cloudflare | browser only | allowed with `print.identity = none` |
| Tailscale / WireGuard | nobody | needs Windows 10+ | excluded by the client constraint of ADR 0001 |

`holtering serve` refuses to start on `api.exposure = "cloudflare"` together
with `print.identity = "request"`: a third party that terminates TLS must not
receive patient names, and that combination is a configuration mistake, not a
runtime risk to be documented.

**5. Accounts.** One account per doctor, created by the operator
(`holtering user add`), no self-registration: a public page with a registration
form on a home IP is a liability with no user. Password hashed with Argon2id
(`argon2-cffi`), session cookie `HttpOnly; Secure; SameSite=Lax`, 12 hours,
invalidated on password change; ten failed attempts lock the account for an
hour. Records belong to the account that uploaded them; the operator has no
account and no read route — he has root instead, which is the point of 1–3.

**6. Retention and the access log.** Every open, edit, print and delete is
logged as (time, account, record id, action) — on the operator's disk, so it is
an aid to the doctor's own audit, not a guarantee against him. A record
untouched for `retention_days` (default 180) is swept: the signal, the cache and
the overrides are deleted, the registry row stays as a tombstone. She can delete
any record at once.

## Rejected alternatives

- **End-to-end encryption of the signal itself.** The server analyses the
  record — 259 MB through numpy, a memmap and a 1.2 s heavy pass. Encrypted, it
  could only be stored, not read; the analysis would have to move into the
  browser, onto a Windows 7 machine with 4–8 GB of RAM and Chrome 109. That is
  ADR 0001 in reverse.
- **Encrypting the record at rest with a key the doctor holds.** The key has to
  be in the process to decrypt the file, the process is the operator's, and she
  is not online when a background job touches the record. It buys protection
  against a stolen disk, which BitLocker already gives.
- **Promising protection from an active operator** (reproducible frontend
  builds, subresource integrity, published bundle hashes). The operator serves
  the page that would do the checking. Publishing the bundle hash outside the
  host is still worth doing, but it is a deterrent, not a control, and this ADR
  refuses to describe it as one.
- **Keeping the name out of the system entirely and printing with a pseudonym.**
  Correct and unusable: she would write the name on every printout by hand. Kept
  as `print.identity = none` for the Cloudflare deployment.
- **A clinic-hosted install.** The right answer whenever the clinic will have
  it: the operator disappears from the threat model. It does not remove any of
  the decisions above, which is why they are taken now.

## Consequences

- The doctor's passphrase is not recoverable: losing it loses the mapping from
  pseudonyms to patients, not the records. The interface says so at the point
  where the passphrase is set, and offers an exported key file.
- The operator can honestly tell a patient that the name is not on his disk, and
  cannot honestly tell them that a determined operator could not have read it.
  Both sentences belong in the doctor-facing documentation.
- The host is in Kazakhstan, which is what the localisation requirement of
  № 94-V asks for `[assumption: article not verified with counsel]`.
- Always-on hosting on Windows means a scheduled task, a UPS-grade assumption
  about power, and an update window the doctor is told about: this is a personal
  machine, not a data centre, and the SLA is "best effort" in writing.
