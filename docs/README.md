# holtering — documentation

Verification of Holter annotation: what the device (LabTech EC-12H, CardioSpy)
labelled incorrectly, before a cardiologist reads the record. The input is a
`raw.scp` export (SCP-ECG, 12 leads, 125 Hz, up to 24 h) and `qrs.txt`
(device labels); the output is an audit of every ectopic label with a verdict
and reasons, episodes for triage, a noise map, reviewer overrides and a
printed protocol.

## How to read this

| Document | About | For whom |
|---|---|---|
| [adr/](adr/README.md) | decisions with their rejected alternatives: delivery, stack | anyone about to propose "let's do it differently" |
| [modules/scp-holter](modules/scp-holter.md) | file format, vendor deviations from SCP-ECG, montage and polarity, export | parser developer |
| [modules/analysis](modules/analysis.md) | method: signal quality, label audit, morphology families, episodes, reading criteria | developer, reviewing cardiologist |
| [operations/dev](operations/dev.md) | local development, checks, repository layout | developer |
| [operations/config](operations/config.md) | `holtering.toml` settings, `HOLTERING_*` variables, CLI flags | operator |
| [CHANGELOG](CHANGELOG.md) | changes by version | everyone |

## What comes next

Delivery to doctors is a web application on our server ([ADR 0001](adr/0001-web-app-not-desktop-exe.md)),
and that server is one workstation in Kazakhstan: the registry, the upload and
the accounts are decided in [ADR 0003](adr/0003-registry-on-a-personal-host.md),
and what the data is protected from — the operator of that machine included —
in [ADR 0004](adr/0004-what-the-data-is-protected-from.md). The code has none of
it yet: one process is still one record, there is no upload, no accounts and no
server-side PDF printing.

## Conventions

- ADRs are Nygard-lite (Status, Date, Context, Decision, Rejected
  alternatives, Consequences). An accepted ADR is not edited on substance:
  a reversal is a new ADR.
- Facts about the device and the format are given with a reference to a
  measurement (record, value, rmse). A statement without a measurement is
  marked `[assumption]`.
- Documentation language is English; code identifiers are as in the code.
