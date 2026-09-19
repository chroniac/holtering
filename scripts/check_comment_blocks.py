"""Ловит то, что ruff не ловит: баннеры и простыни комментариев.

Правила (AGENTS.md → «Код»): блок подряд идущих `#`-строк не длиннее
MAX_BLOCK; строки-разделители вроде `# ----` или `# ====` запрещены;
`# TODO`/`# FIXME` — только со ссылкой на задачу.
"""

import re
import subprocess
import sys
from pathlib import Path

MAX_BLOCK = 6
BANNER = re.compile(r"^\s*#\s*[-=*#~_]{4,}\s*$")
TODO = re.compile(r"^\s*#\s*(TODO|FIXME|XXX)\b(?!.*(#\d+|https?://))", re.I)
DIRECTIVE = re.compile(r"^\s*#\s*(noqa|type:|ruff:|pyright:|fmt:|!/)")


def scan(path: Path) -> list[str]:
    errors: list[str] = []
    run_start = 0
    run = 0
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.lstrip()
        is_comment = stripped.startswith("#") and not DIRECTIVE.match(line)
        if is_comment:
            run_start = run_start or n
            run += 1
            if BANNER.match(line):
                errors.append(f"{path}:{n}: баннер-разделитель")
            if TODO.match(line):
                errors.append(f"{path}:{n}: TODO без ссылки на задачу")
        else:
            if run > MAX_BLOCK:
                errors.append(
                    f"{path}:{run_start}: блок комментариев на {run} строк (максимум {MAX_BLOCK})"
                )
            run_start, run = 0, 0
    if run > MAX_BLOCK:
        errors.append(
            f"{path}:{run_start}: блок комментариев на {run} строк (максимум {MAX_BLOCK})"
        )
    return errors


def tracked_python_files() -> list[Path]:
    # Только отслеживаемые файлы: кэш uv, venv и артефакты сборки не линтуются по определению.
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"], check=True, capture_output=True
    ).stdout
    return [p for name in out.decode().split("\0") if name and (p := Path(name)).exists()]


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] or tracked_python_files()
    errors = [e for f in files for e in scan(f)]
    print("\n".join(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
