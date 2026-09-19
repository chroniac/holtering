from collections.abc import Iterator
from pathlib import Path

import pytest
from litestar.testing import TestClient

from holtering.analysis import build
from holtering.api import create_app
from holtering.settings import CONFIG_DIR_ENV, Settings
from tests.synth import Synthetic


@pytest.fixture
def settings(record: Synthetic, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    return Settings(
        record={"scp": record.scp, "qrs": record.qrs, "cache_dir": tmp_path},
        api={"static_dir": None},
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, build(settings.record))) as client:
        yield client


def first_ventricular(client: TestClient) -> int:
    beats = client.get("/api/beats", params={"dur": 600}).json()
    return beats["first_index"] + beats["label"].index(1)


def test_ecg_window_past_the_record_is_rejected(client: TestClient, record: Synthetic) -> None:
    assert client.get("/api/ecg", params={"start": record.seconds + 1}).status_code == 400
    assert client.get("/api/ecg", params={"start": record.seconds - 5}).status_code == 200


def test_ecg_unknown_lead_is_rejected(client: TestClient) -> None:
    rejected = client.get("/api/ecg", params={"leads": "II,V9"})

    assert rejected.status_code == 400
    assert rejected.headers["content-type"].startswith("application/problem+json")
    assert rejected.json()["title"] == "Bad Request"
    assert rejected.json()["detail"].startswith("unknown lead")
    assert client.get("/api/ecg", params={"leads": "II,ch7"}).status_code == 200


def test_window_length_limits_are_enforced(client: TestClient) -> None:
    assert client.get("/api/ecg", params={"dur": 121}).status_code == 400
    assert client.get("/api/beats", params={"dur": 10801}).status_code == 400
    assert client.get("/api/raw", params={"dur": 3601}).status_code == 400
    assert client.get("/api/ecg", params={"dur": 0}).status_code == 400


def test_beat_outside_the_record_is_not_found(client: TestClient) -> None:
    assert client.get("/api/beat/0").status_code == 200

    missing = client.get("/api/beat/999999")

    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json() == {"status": 404, "title": "Not Found", "detail": "no such beat"}


def test_manual_label_changes_the_verdict_and_survives_restart(
    settings: Settings, client: TestClient
) -> None:
    index = first_ventricular(client)
    before = client.get(f"/api/beat/{index}").json()
    updated = client.post(f"/api/annotations/{index}", json={"label": "N"}).json()

    assert before["verdict"] != "manual-N"
    assert updated["verdict"] == "manual-N"
    assert updated["manual"] == "N"
    assert client.get("/api/summary").json()["counts"]["manual"] == 1

    with TestClient(create_app(settings, build(settings.record))) as restarted:
        kept = restarted.get(f"/api/beat/{index}").json()
        assert kept["verdict"] == "manual-N"
        assert restarted.get("/api/summary").json()["counts"]["manual"] == 1


def test_added_beat_lands_in_time_order(client: TestClient, record: Synthetic) -> None:
    # The middle of the known 2.5 s pause: an insert closer than 120 ms to a beat is refused.
    assert record.pause_ms is not None
    t_ms = sum(record.pause_ms) // 2

    response = client.post("/api/beats/add", json={"t_ms": t_ms, "label": "V"})

    assert response.status_code == 200
    info = response.json()
    assert info["added"] is True
    assert info["t_ms"] == t_ms
    assert info["manual"] == "V"
    window = client.get("/api/beats", params={"start": t_ms / 1000 - 3, "dur": 6}).json()
    assert window["t_ms"] == sorted(window["t_ms"])
    assert t_ms in window["t_ms"]
    assert window["first_index"] + window["t_ms"].index(t_ms) == info["index"]


def test_manual_noise_span_marks_windows_and_can_be_cleared(client: TestClient) -> None:
    client.post("/api/quality", json={"t0_ms": 10_000, "t1_ms": 20_000, "value": "noise"})
    marked = client.get("/api/ecg", params={"start": 10, "dur": 10}).json()

    assert marked["quality_manual"] == [{"t0_ms": 10000, "t1_ms": 20000, "v": "noise"}]
    assert [w["t0"] for w in marked["noise_windows"]] == list(range(10, 20, 2))

    client.post("/api/quality", json={"t0_ms": 10_000, "t1_ms": 20_000, "value": None})
    cleared = client.get("/api/ecg", params={"start": 10, "dur": 10}).json()

    assert cleared["quality_manual"] == []
    assert cleared["noise_windows"] == []


def test_diary_event_gets_the_surrounding_rhythm(client: TestClient) -> None:
    created = client.post("/api/events", json={"t_ms": 120_000, "text": "сердцебиение"}).json()

    assert 60 <= created["hr"] <= 80
    assert created["hr_min"] <= created["hr"] <= created["hr_max"]
    assert created["text"] == "сердцебиение"
    assert client.post("/api/events", json={"t_ms": 99_999_999}).status_code == 400


def test_raw_returns_exactly_the_requested_int16_window(
    client: TestClient, record: Synthetic
) -> None:
    response = client.get("/api/raw", params={"start": 5, "dur": 2, "lead": "II"})

    assert response.status_code == 200
    assert response.headers["X-Fs"] == str(record.fs)
    assert len(response.content) == 2 * 2 * record.fs
