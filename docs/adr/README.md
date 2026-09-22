# Architecture decision records (ADR)

Cross-cutting decisions — the ones that would otherwise be proposed again in
six months. Each one names its rejected alternatives and their price. The
format is Nygard-lite: `Status:`, `Date:`, **Context**, **Decision**,
**Rejected alternatives**, **Consequences**. An accepted ADR is not edited on
substance: a reversal is a new ADR, and the old one gets a changed `Status:`
line with a link.

## List

| Number | Title | Status | Date |
|---|---|---|---|
| [0001](0001-web-app-not-desktop-exe.md) | Delivery to doctors is a web application on our server, not a desktop exe | accepted | 2026-09-19 |
| [0002](0002-stack.md) | Stack and rules: Litestar, uv workspace, ruff/ty, msgspec, Dishka, pydantic-settings | accepted | 2026-09-19 |
| [0003](0003-registry-on-a-personal-host.md) | A record registry on one personal machine: upload, SQLite, one open record | accepted | 2026-09-22 |
| [0004](0004-what-the-data-is-protected-from.md) | What the doctor's data is protected from, and what it is not | accepted | 2026-09-22 |
