"""Формы запросов и ответов HTTP: имена полей совпадают с ключами JSON."""

from typing import Any

from msgspec import Struct

from holtering.analysis.protocol import AutoStrip, HourlyRow, ProtocolHeader, SummaryRow
from holtering.analysis.rhythm import Episode, Hrv
from holtering.analysis.state import (
    BeatInfo,
    Counts,
    Criterion,
    EventContext,
    HeartRate,
    NoiseWindow,
    Patient,
    QualitySpan,
    Record,
)


class LabelBody(Struct):
    label: str | None


class AddBody(Struct):
    t_ms: int
    label: str = "N"


class QualityBody(Struct):
    t0_ms: int
    t1_ms: int
    value: str | None


class EventBody(Struct):
    t_ms: int
    text: str = ""


class OkView(Struct):
    ok: bool


class BeatsView(Struct):
    start: float
    dur: float
    first_index: int
    t_ms: list[int]
    rr_ms: list[int]
    label: list[int]
    cls: list[int]
    noise_windows: list[NoiseWindow]


class EcgView(Struct):
    start: float
    fs: int
    leads: list[str]
    data: list[list[float]]
    lead_noise: list[float]
    lead_drift: list[float]
    drift_thr_mv: float
    beats: list[BeatInfo]
    noise_windows: list[NoiseWindow]
    quality_manual: list[QualitySpan]


class ReportView(Struct):
    generated: dict[str, str]
    titles: dict[str, str]
    order: list[str]
    header: ProtocolHeader
    summary: list[SummaryRow]
    hourly: list[HourlyRow]
    auto_strips: list[AutoStrip]
    # Правок ещё не было — пустой объект: разбор формы врача идёт по отдельному Struct.
    saved: dict[str, Any]


class TemplateBeatsView(Struct):
    total: int
    beats: list[BeatInfo]


class TemplateLabelView(Struct):
    template: int
    beats: int
    label: str | None


class AnnotationsView(Struct):
    labels: dict[str, str]
    added: dict[str, str]
    quality: list[QualitySpan]


class QualityView(Struct):
    spans: list[QualitySpan]


class ExportBeat(Struct):
    t_ms: int
    label: str
    device: str | None


class ManualView(Struct):
    labels: dict[int, str]
    added: dict[int, str]
    quality: list[QualitySpan]


class ExportView(Struct):
    """Всё, что нужно отчёту: сводка, эпизоды и каждый комплекс с итоговой меткой."""

    record: Record
    patient: Patient
    hr: HeartRate
    hrv: Hrv
    counts: Counts
    episodes: list[Episode]
    criteria: list[Criterion]
    events: list[EventContext]
    manual: ManualView
    beats: list[ExportBeat]
