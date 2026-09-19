"""Проверка сообщений коммитов по Conventional Commits.

Использование:
  check_commits.py --file <путь к сообщению>     # hook commit-msg
  check_commits.py --range <base>..<head>         # CI по диапазону
"""

import argparse
import re
import subprocess
import sys

TYPES = "feat|fix|docs|refactor|perf|test|build|ci|chore|revert"
SUBJECT = re.compile(rf"^({TYPES})(\([a-z0-9._/-]+\))?!?: (?P<text>\S.*)$")
SUBJECT_MAX = 72
BODY_LINE_MAX = 100
SKIP = re.compile(r"^(Merge |Revert \"|fixup! |squash! )")


def check(message: str) -> list[str]:
    lines = message.rstrip("\n").split("\n")
    subject = lines[0]
    if SKIP.match(subject):
        return [f"служебный коммит не допускается в main: {subject!r}"]
    errors: list[str] = []
    m = SUBJECT.match(subject)
    if not m:
        errors.append(f"тема не по формату `тип(область): текст`: {subject!r}")
    else:
        text = m.group("text")
        if text.endswith("."):
            errors.append("тема заканчивается точкой")
        if text[0].isupper() and text[:2].isupper() is False and text.isascii():
            errors.append("тема начинается с заглавной буквы (латиница)")
    if len(subject) > SUBJECT_MAX:
        errors.append(f"тема длиннее {SUBJECT_MAX} символов ({len(subject)})")
    if len(lines) > 1 and lines[1].strip():
        errors.append("между темой и телом нужна пустая строка")
    for i, line in enumerate(lines[2:], start=3):
        if len(line) > BODY_LINE_MAX and not line.startswith(("http", "Refs", "See")):
            errors.append(f"строка {i} тела длиннее {BODY_LINE_MAX} символов")
    return errors


def report(label: str, message: str) -> bool:
    errors = check(message)
    for e in errors:
        print(f"{label}: {e}")
    return not errors


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--file")
    g.add_argument("--range")
    a = p.parse_args()

    if a.file:
        with open(a.file, encoding="utf-8") as f:
            body = "\n".join(line for line in f.read().split("\n") if not line.startswith("#"))
        return 0 if report("commit", body.strip()) else 1

    log = subprocess.run(
        ["git", "log", "--format=%H%x00%B%x1e", a.range],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    ok = True
    for raw in log.split("\x1e"):
        entry = raw.strip()
        if not entry:
            continue
        sha, _, msg = entry.partition("\x00")
        ok &= report(sha[:8], msg.strip())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
