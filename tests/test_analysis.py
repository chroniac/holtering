from pathlib import Path

import numpy as np
import pytest

from holtering.analysis import State, build
from holtering.analysis.rhythm import KEEP, estimate_sleep, nn_intervals, runs
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
