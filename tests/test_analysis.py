from pathlib import Path

import numpy as np
import pytest

from holtering.analysis import State, build
from holtering.analysis.beats import BeatAudit, apply_schedule_evidence
from holtering.analysis.intervals import measure_qt
from holtering.analysis.rhythm import KEEP, estimate_sleep, hr_extremes, nn_intervals, runs
from holtering.settings import RecordSettings
from tests.synth import Synthetic


@pytest.fixture(scope="module")
def state(record: Synthetic, tmp_path_factory: pytest.TempPathFactory) -> State:
    cache: Path = tmp_path_factory.mktemp("analysis")
    return build(RecordSettings(scp=record.scp, qrs=record.qrs, cache_dir=cache))


def test_nn_intervals_keep_only_plausible_sinus_pairs() -> None:
    t_ms = np.array([0, 800, 1600, 1700, 2500, 5000], np.int64)

    t_nn, nn = nn_intervals(t_ms, np.array(["N"] * 6))

    assert nn.tolist() == [800, 800, 800]  # 100 мс и 2500 мс отброшены
    assert t_nn.tolist() == [0, 800, 1700]

    _, with_ectopy = nn_intervals(t_ms, np.array(["N", "N", "V", "N", "N", "N"]))

    assert with_ectopy.tolist() == [800, 800]  # пары с меткой V не в счёт


def test_hr_extremes_report_the_window_not_the_minute() -> None:
    slow = np.arange(0, 60_000, 1000)  # 60 уд/мин
    fast = slow[-1] + np.arange(1, 41) * 375  # 15 с по 160 уд/мин
    tail = fast[-1] + np.arange(1, 61) * 1000

    lo, _, hi, at = hr_extremes(np.concatenate([slow, fast, tail]).astype(np.int64))

    assert round(lo) == 60
    assert round(hi) == 160  # поминутное среднее на этой записи не превысило бы 100
    assert abs(at - (slow[-1] + 7500)) < 1500


def test_on_schedule_label_after_a_rejected_one_is_not_an_extrasystole() -> None:
    t = np.array([0, 800, 1600, 2000, 2400, 3200, 4000], np.int64)
    labels = np.array(["N", "N", "N", "S", "S", "N", "N"])
    intruder = BeatAudit(index=3, t_ms=2000, label="S", verdict="on-wave", confidence=0.9)
    on_time = BeatAudit(index=4, t_ms=2400, label="S", verdict="likely", confidence=0.8)

    apply_schedule_evidence([intruder, on_time], t, labels)

    assert on_time.verdict == "on-schedule"  # 2400 = 1600 + один синусовый цикл

    couplet = [
        BeatAudit(index=3, t_ms=2000, label="S", verdict="likely", confidence=0.8),
        BeatAudit(index=4, t_ms=2400, label="S", verdict="likely", confidence=0.8),
    ]
    apply_schedule_evidence(couplet, t, labels)

    assert [a.verdict for a in couplet] == ["likely", "likely"]  # соседка настоящая — это куплет


def test_measure_qt_finds_the_end_of_a_triangular_t_wave() -> None:
    w = np.zeros(121, np.float32)
    w[50:54] = [0.3, 1.0, -0.4, 0.0]  # QRS начинается на 50-м отсчёте
    w[70:80] = np.linspace(0, 0.3, 10)  # T: линейный подъём
    w[80:90] = np.linspace(0.3, 0, 10)  # и линейный спуск в изолинию на 90-м
    got = measure_qt(w, 125, 800.0)

    assert got is not None
    qt, qtc = got
    assert abs(qt - 320) <= 16  # 40 отсчётов по 8 мс, допуск — один отсчёт на границу
    assert round(qtc) == round(qt / 800.0**0.5 * 1000**0.5)


def test_intervals_are_measured_on_the_record(state: State) -> None:
    iv = state.analysis.summary.intervals

    assert iv.hours >= 1
    assert iv.qtc_ms is not None
    assert 300 <= iv.qtc_ms <= 500


def test_runs_groups_consecutive_indices_of_minimum_length() -> None:
    idx = np.array([1, 2, 3, 7, 9, 10])

    assert [g.tolist() for g in runs(idx, 2)] == [[1, 2, 3], [9, 10]]
    assert [g.tolist() for g in runs(idx, 3)] == [[1, 2, 3]]
    assert [g.tolist() for g in runs(idx, 4)] == []
    assert runs(np.array([], np.int64), 1) == []


def test_estimate_sleep_needs_two_hours_of_heart_rate() -> None:
    day: list[float | None] = [75.0] * 300
    night: list[float | None] = [50.0] * 120

    assert estimate_sleep(day[:119]) == []
    assert estimate_sleep(day + night + day) == [[300, 420]]


def test_false_ventricular_label_is_rejected(record: Synthetic, state: State) -> None:
    false_v = next(b for b in record.beats if b.kind == "N" and b.label == "V")

    k = int(np.searchsorted(state.t_ms, false_v.t_ms))

    assert int(state.t_ms[k]) == false_v.t_ms
    assert state.audits[k].verdict not in KEEP


def test_real_ventricular_pair_is_kept(record: Synthetic, state: State) -> None:
    pair = [b for b in record.beats if b.kind == "V"]

    assert len(pair) == 2
    for beat in pair:
        k = int(np.searchsorted(state.t_ms, beat.t_ms))
        assert state.audits[k].verdict == "likely"
    assert state.analysis.summary.counts.audited.V == 2
