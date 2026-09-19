"""Снимок ответов API на синтетической записи и сравнение двух снимков.

  snapshot_api.py capture <каталог>          # до и после рефакторинга
  snapshot_api.py compare <каталог1> <каталог2>
Тела 2xx обязаны совпасть, у ошибок сравниваются только статусы (ADR 0002).
"""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from litestar.testing import TestClient

from holtering.analysis import build
from holtering.api import create_app
from holtering.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests.synth import write_record  # noqa: E402

SKIP_FIELDS = {"computed_s"}
START = "2026-09-17 09:30:00"


def capture(out: Path, work: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    record = write_record(work, seconds=600)
    settings = Settings(
        record={"scp": record.scp, "qrs": record.qrs, "start": START, "cache_dir": work},
        api={"static_dir": None},
    )
    client = TestClient(create_app(settings, build(settings.record)))

    def dump(name: str, response) -> None:
        body = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else response.content.hex()
        )
        (out / f"{name}.json").write_text(
            json.dumps(
                {"status": response.status_code, "body": body},
                ensure_ascii=False,
                sort_keys=True,
                indent=1,
            ),
            "utf-8",
        )

    dump("summary", client.get("/api/summary"))
    dump("overview", client.get("/api/overview"))
    dump("episodes", client.get("/api/episodes"))
    dump("beats", client.get("/api/beats"))
    dump("beats-window", client.get("/api/beats", params={"start": 60, "dur": 120}))
    dump("ecg-0", client.get("/api/ecg", params={"start": 0, "dur": 10}))
    dump("ecg-leads", client.get("/api/ecg", params={"start": 100, "dur": 30, "leads": "II,ch7"}))
    dump("ecg-bad-lead", client.get("/api/ecg", params={"start": 100, "dur": 30, "leads": "II,V9"}))
    dump("ecg-beyond", client.get("/api/ecg", params={"start": 10_000, "dur": 10}))
    dump("raw", client.get("/api/raw", params={"start": 5, "dur": 2, "lead": "II"}))
    dump("beat-0", client.get("/api/beat/0"))
    dump("beat-80", client.get("/api/beat/80"))
    dump("beat-404", client.get("/api/beat/99999"))
    dump("report", client.get("/api/report"))
    dump("export", client.get("/api/export"))
    dump("templates", client.get("/api/templates"))
    dump("template-0-beats", client.get("/api/templates/0/beats", params={"limit": 5}))
    dump("template-404", client.get("/api/templates/999/beats"))
    dump("annotations", client.get("/api/annotations"))
    dump("events", client.get("/api/events"))

    dump("post-annotate", client.post("/api/annotations/81", json={"label": "N"}))
    dump("post-annotate-bad", client.post("/api/annotations/81", json={"label": "Q"}))
    dump("post-add", client.post("/api/beats/add", json={"t_ms": 300_000, "label": "V"}))
    dump(
        "post-quality",
        client.post("/api/quality", json={"t0_ms": 1000, "t1_ms": 5000, "value": "noise"}),
    )
    dump("post-event", client.post("/api/events", json={"t_ms": 120_000, "text": "сердцебиение"}))
    dump("post-event-bad", client.post("/api/events", json={"t_ms": 99_999_999, "text": "x"}))
    dump("post-template-label", client.post("/api/templates/0/label", json={"label": "S"}))
    dump(
        "post-report",
        client.post("/api/report", json={"text": {"conclusion": "тест"}, "meta": {"doctor": "Д"}}),
    )
    dump("summary-after", client.get("/api/summary"))
    dump("episodes-after", client.get("/api/episodes"))
    dump("annotations-after", client.get("/api/annotations"))
    dump("events-after", client.get("/api/events"))
    dump("report-after", client.get("/api/report"))
    dump("delete-event", client.delete("/api/events/1"))
    dump("post-annotate-clear", client.post("/api/annotations/81", json={"label": None}))
    dump("summary-final", client.get("/api/summary"))
    sys.stdout.write(f"{len(list(out.glob('*.json')))} ответов -> {out}\n")


def strip(value):
    """Поля, которые меняются от прогона к прогону, из сравнения исключены."""
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in SKIP_FIELDS}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


def compare(left: Path, right: Path) -> int:
    names = sorted({p.stem for p in left.glob("*.json")} | {p.stem for p in right.glob("*.json")})
    problems: list[str] = []
    for name in names:
        a, b = left / f"{name}.json", right / f"{name}.json"
        if not a.exists() or not b.exists():
            problems.append(f"{name}: нет в {a.parent if not a.exists() else b.parent}")
            continue
        da, db = json.loads(a.read_text("utf-8")), json.loads(b.read_text("utf-8"))
        if da["status"] != db["status"]:
            problems.append(f"{name}: статус {da['status']} != {db['status']}")
            continue
        if da["status"] >= 400:
            continue
        if strip(da["body"]) != strip(db["body"]):
            problems.append(f"{name}: тело различается")
    for line in problems:
        sys.stdout.write(f"{line}\n")
    sys.stdout.write(f"{len(names)} ответов, расхождений: {len(problems)}\n")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    match argv:
        case ["capture", out]:
            # На Windows memmap записи держит raw.scp открытым до конца процесса.
            with TemporaryDirectory(ignore_cleanup_errors=True) as work:
                capture(Path(out), Path(work))
            return 0
        case ["compare", left, right]:
            return compare(Path(left), Path(right))
    sys.stdout.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
