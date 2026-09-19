"""Разбор SCP-ECG: то, на чём спотыкаются сторонние ридеры, и границы чтения."""

from pathlib import Path

import numpy as np
import pytest

from scp_holter import CHEST_ASC, LIMB6, ScpHolter, to_edf
from scp_holter.leads import relabel_chest
from scp_holter.patient import parse_patient
from scp_holter.sections import read_body, read_container, u16
from scp_holter.signal import META_FIXED_LEN, SAMPLE_BYTES, sample_window
from tests.synth import Synthetic

N_LEADS = 12
PATIENT_SECTION = 1
RHYTHM_SECTION = 6
EDF_SIGNAL_HEADER_WIDTH = 16 + 80 + 8 + 8 + 8 + 8 + 8 + 80


def test_section6_length_wins_over_overflowed_byte_counters(record: Synthetic) -> None:
    with record.scp.open("rb") as fh:
        container = read_container(fh)
        meta = read_body(fh, container[RHYTHM_SECTION])[: META_FIXED_LEN + SAMPLE_BYTES * N_LEADS]

    true_bytes = record.n_samples * SAMPLE_BYTES
    declared = [u16(meta, META_FIXED_LEN + SAMPLE_BYTES * i) for i in range(N_LEADS)]
    assert declared == [true_bytes & 0xFFFF] * N_LEADS
    assert declared[0] != true_bytes

    assert ScpHolter(str(record.scp)).n_samples == record.n_samples


def test_read_lead_matches_the_memmap_row_for_a_later_lead(record: Synthetic) -> None:
    rec = ScpHolter(str(record.scp))
    mm = rec.memmap()
    assert mm.shape == (N_LEADS, record.n_samples)
    assert np.array_equal(rec.read_lead(7, 1000, 1500), mm[7, 1000:1500])
    assert np.array_equal(rec.read_lead(11, record.n_samples - 10, record.n_samples), mm[11, -10:])


def test_sample_window_clamps_both_ends(record: Synthetic) -> None:
    rec = ScpHolter(str(record.scp))
    assert sample_window(rec.meta, -5.0, 2.0) == (0, 2 * record.fs)
    assert sample_window(rec.meta, record.seconds - 1, 10.0) == (
        record.n_samples - record.fs,
        record.n_samples,
    )
    assert sample_window(rec.meta, record.seconds + 100, 5.0) == (
        record.n_samples,
        record.n_samples,
    )


def test_invert_negates_every_sample(record: Synthetic) -> None:
    plain = ScpHolter(str(record.scp)).read(10.0, 2.0)
    flipped = ScpHolter(str(record.scp), invert=True).read(10.0, 2.0)
    assert np.array_equal(flipped, -plain)


def test_patient_section_decodes_cp1251_and_drops_nul_padding(record: Synthetic) -> None:
    with record.scp.open("rb") as fh:
        patient = parse_patient(read_body(fh, read_container(fh)[PATIENT_SECTION]))

    assert patient["last_name"] == "Тестов"
    assert patient["first_name"] == "Тест"
    assert patient["patient_id"] == "T-0001"
    assert patient["dob"] == "1972-03-09"
    assert patient["sex"] == "M"
    assert patient["age"] == 54
    assert patient["acq_date"] == "2026-09-17"
    assert patient["acq_time"] == "09:30:00"


def test_relabel_chest_wants_exactly_the_chest_channels() -> None:
    with pytest.raises(ValueError, match="expected 6 chest labels, got 2"):
        relabel_chest(N_LEADS, ["V1", "V2"])
    assert relabel_chest(N_LEADS, CHEST_ASC) == [*LIMB6, *CHEST_ASC]


def test_read_container_rejects_a_file_shorter_than_the_preamble(tmp_path: Path) -> None:
    stub = tmp_path / "short.scp"
    stub.write_bytes(b"\x00\x01\x02")
    with stub.open("rb") as fh, pytest.raises(ValueError, match="preamble"):
        read_container(fh)


def test_to_edf_header_is_readable_back(record: Synthetic, tmp_path: Path) -> None:
    rec = ScpHolter(str(record.scp))
    out, nrec = to_edf(rec, str(tmp_path / "five.edf"), 0.0, 5.0)
    head = Path(out).read_bytes()

    n_signals = int(head[252:256])
    assert n_signals == N_LEADS
    assert nrec == 5
    assert int(head[236:244]) == 5
    assert float(head[244:252]) == 1.0

    header_bytes = int(head[184:192])
    assert header_bytes == 256 * (n_signals + 1)

    rates_at = 256 + n_signals * EDF_SIGNAL_HEADER_WIDTH
    rates = [int(head[rates_at + 8 * i : rates_at + 8 * (i + 1)]) for i in range(n_signals)]
    assert rates == [record.fs] * n_signals
    assert len(head) == header_bytes + nrec * n_signals * record.fs * SAMPLE_BYTES
