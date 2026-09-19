"""Маршруты просмотра: сводка, окно ЭКГ, комплексы, эпизоды, шаблоны, ручные метки."""

from typing import Annotated

import msgspec
import numpy as np
from dishka.integrations.litestar import FromDishka, inject
from litestar import Response, Router, delete, get, post
from litestar.exceptions import ClientException, NotFoundException
from litestar.params import FromPath, FromQuery, QueryParameter

from holtering.analysis import State
from holtering.analysis.protocol import SECTION_TITLES, SECTIONS, Protocol
from holtering.analysis.quality import WANDER_MIN_MV, WANDER_RATIO, baseline, hf_residual
from holtering.analysis.rhythm import Episode
from holtering.analysis.state import (
    BeatInfo,
    EventContext,
    Overview,
    ReportEdits,
    Summary,
    TemplateView,
    enc_hook,
)
from holtering.api.views import (
    AddBody,
    AnnotationsView,
    BeatsView,
    EcgView,
    EventBody,
    ExportBeat,
    ExportView,
    LabelBody,
    ManualView,
    OkView,
    QualityBody,
    QualityView,
    ReportView,
    TemplateBeatsView,
    TemplateLabelView,
)

MAX_ECG_S = 120.0
MAX_BEATS_S = 3 * 3600.0
MAX_RAW_S = 3600.0
MAX_TEMPLATE_BEATS = 2000

Start = Annotated[float, QueryParameter(ge=0.0)]


@get("/summary")
@inject
async def summary(state: FromDishka[State]) -> Summary:
    return state.analysis.summary


@get("/overview")
@inject
async def overview(state: FromDishka[State]) -> Overview:
    return state.analysis.overview


@get("/episodes")
@inject
async def episodes(state: FromDishka[State]) -> list[Episode]:
    return state.analysis.episodes


@get("/beats")
@inject
async def beats(
    state: FromDishka[State],
    start: Start = 0.0,
    dur: Annotated[float, QueryParameter(gt=0.0, le=MAX_BEATS_S)] = 300.0,
) -> BeatsView:
    """Колоночная форма для полосы контекста: параллельные массивы вместо словаря на комплекс."""
    lo = int(np.searchsorted(state.t_ms, start * 1000))
    hi = int(np.searchsorted(state.t_ms, (start + dur) * 1000))
    t = state.t_ms[lo:hi]
    rr = np.diff(state.t_ms[max(0, lo - 1) : hi]) if hi > lo else np.array([], np.int64)
    if lo == 0 and len(rr) < len(t):
        rr = np.r_[0, rr]
    return BeatsView(
        start=start,
        dur=dur,
        first_index=lo,
        t_ms=t.tolist(),
        rr_ms=rr.tolist(),
        label=state.code_label[lo:hi].tolist(),
        cls=state.code_class[lo:hi].tolist(),
        noise_windows=state.noise_windows(start, dur),
    )


@get("/raw")
@inject
async def raw(
    state: FromDishka[State],
    start: Start = 0.0,
    dur: Annotated[float, QueryParameter(gt=0.0, le=MAX_RAW_S)] = MAX_RAW_S,
    lead: FromQuery[str] = "II",
) -> Response[bytes]:
    """Сырые отсчёты int16 LE одного отведения — полное раскрытие записи."""
    names = state.rec.leads
    if lead not in names:
        raise ClientException(f"unknown lead {lead}")
    a = round(start * state.fs)
    b = min(state.mm.shape[1], a + round(dur * state.fs))
    blk = np.ascontiguousarray(state.mm[names.index(lead), a:b], dtype="<i2")
    return Response(
        blk.tobytes(),
        media_type="application/octet-stream",
        headers={"X-Fs": str(state.fs), "X-Start": str(start), "X-Mv-Per-Lsb": str(state.mv)},
    )


@get("/ecg")
@inject
async def ecg(
    state: FromDishka[State],
    start: Start = 0.0,
    dur: Annotated[float, QueryParameter(gt=0.0, le=MAX_ECG_S)] = 10.0,
    leads: FromQuery[str | None] = None,
) -> EcgView:
    if start >= state.total_s:
        raise ClientException("start beyond record")
    names = state.rec.leads
    pick = list(range(len(names)))
    if leads:
        try:
            pick = [names.index(x) for x in leads.split(",")]
        except ValueError as exc:
            raise ClientException(f"unknown lead: {exc}") from exc
    a = round(start * state.fs)
    b = min(state.mm.shape[1], a + round(dur * state.fs))
    cal = state.analysis.summary.calibration
    samples = np.asarray(state.mm[pick, a:b]).astype(np.float32) * state.mv
    sig = samples - np.median(samples, axis=1, keepdims=True)
    noise = hf_residual(sig, state.fs).std(axis=1) / cal.noise_base_ii_mv
    slow = baseline(sig, state.fs)
    drift = slow.max(axis=1) - slow.min(axis=1)
    drift_thr = max(WANDER_MIN_MV, WANDER_RATIO * cal.wander_base_ii_mv)
    return EcgView(
        start=start,
        fs=state.fs,
        leads=[names[i] for i in pick],
        data=[np.round(row, 3).tolist() for row in sig],
        lead_noise=[round(float(x), 2) for x in noise],
        lead_drift=[round(float(x), 2) for x in drift],
        drift_thr_mv=round(drift_thr, 2),
        beats=state.beats_in(start, dur),
        noise_windows=state.noise_windows(start, dur),
        quality_manual=[
            q for q in state.quality if q.t1_ms > start * 1000 and q.t0_ms < (start + dur) * 1000
        ],
    )


@get("/beat/{index:int}")
@inject
async def beat(state: FromDishka[State], index: FromPath[int]) -> BeatInfo:
    if not 0 <= index < len(state.t_ms):
        raise NotFoundException("no such beat")
    return state.beat_info(index)


@get("/report")
@inject
async def report(state: FromDishka[State]) -> ReportView:
    """Сгенерированный протокол плюс сохранённые правки врача."""
    pr = Protocol(state)
    return ReportView(
        generated=pr.sections(),
        titles=SECTION_TITLES,
        order=SECTIONS,
        header=pr.header(),
        summary=pr.summary_rows(),
        hourly=pr.hourly(),
        auto_strips=pr.auto_strips(),
        saved=state.saved_report,
    )


@post("/report", status_code=200)
@inject
async def save_report(state: FromDishka[State], data: ReportEdits) -> OkView:
    state.set_report(data)
    return OkView(ok=True)


@get("/export")
@inject
async def export(state: FromDishka[State]) -> Response[bytes]:
    an = state.analysis.summary
    payload = ExportView(
        record=an.record,
        patient=an.patient,
        hr=an.hr,
        hrv=an.hrv,
        counts=an.counts,
        episodes=state.analysis.episodes,
        criteria=an.criteria,
        events=state.events_with_context(),
        manual=ManualView(labels=state.relabels, added=state.added, quality=state.quality),
        beats=[
            ExportBeat(
                t_ms=int(t),
                label=str(lab),
                device=(str(state.dev_labels[o]) if o >= 0 else None),
            )
            for t, lab, o in zip(state.t_ms, state.labels, state.origin, strict=True)
        ],
    )
    return Response(
        msgspec.json.encode(payload, enc_hook=enc_hook),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=holtering-export.json"},
    )


@get("/templates")
@inject
async def templates(state: FromDishka[State]) -> list[TemplateView]:
    return state.templates()


@get("/templates/{tid:int}/beats")
@inject
async def template_beats(
    state: FromDishka[State],
    tid: FromPath[int],
    offset: FromQuery[int] = 0,
    limit: Annotated[int, QueryParameter(le=MAX_TEMPLATE_BEATS)] = 200,
) -> TemplateBeatsView:
    members = np.where(state.dev_template == tid)[0]
    if not len(members):
        raise NotFoundException("no such template")
    sel = state.dev_to_merged[members[offset : offset + limit]]
    return TemplateBeatsView(total=len(members), beats=[state.beat_info(int(k)) for k in sel])


@get("/annotations")
@inject
async def annotations(state: FromDishka[State]) -> AnnotationsView:
    return AnnotationsView(
        labels={str(k): v for k, v in state.relabels.items()},
        added={str(k): v for k, v in state.added.items()},
        quality=state.quality,
    )


@get("/events")
@inject
async def events(state: FromDishka[State]) -> list[EventContext]:
    return state.events_with_context()


@post("/events", status_code=200)
@inject
async def add_event(state: FromDishka[State], data: EventBody) -> EventContext:
    if not 0 <= data.t_ms <= state.total_ms:
        raise ClientException("time outside the record")
    return state.add_event(data.t_ms, data.text)


@delete("/events/{eid:int}", status_code=200)
@inject
async def del_event(state: FromDishka[State], eid: FromPath[int]) -> OkView:
    state.remove_event(eid)
    return OkView(ok=True)


@post("/quality", status_code=200)
@inject
async def quality(state: FromDishka[State], data: QualityBody) -> QualityView:
    try:
        state.set_quality(data.t0_ms, data.t1_ms, data.value)
    except ValueError as exc:
        raise ClientException(str(exc)) from exc
    return QualityView(spans=state.quality)


@post("/beats/add", status_code=200)
@inject
async def add_beat(state: FromDishka[State], data: AddBody) -> BeatInfo:
    try:
        k = state.add_beat(data.t_ms, data.label)
    except ValueError as exc:
        raise ClientException(str(exc)) from exc
    return state.beat_info(k)


@post("/annotations/{index:int}", status_code=200)
@inject
async def annotate(state: FromDishka[State], index: FromPath[int], data: LabelBody) -> BeatInfo:
    if not 0 <= index < len(state.t_ms):
        raise NotFoundException("no such beat")
    try:
        state.set_label(index, data.label)
    except ValueError as exc:
        raise ClientException(str(exc)) from exc
    return state.beat_info(index)


@post("/templates/{tid:int}/label", status_code=200)
@inject
async def annotate_template(
    state: FromDishka[State], tid: FromPath[int], data: LabelBody
) -> TemplateLabelView:
    try:
        n = state.set_template_label(tid, data.label)
    except ValueError as exc:
        raise ClientException(str(exc)) from exc
    if n == 0:
        raise NotFoundException("no such template")
    return TemplateLabelView(template=tid, beats=n, label=data.label)


api_router = Router(
    "/api",
    route_handlers=[
        summary,
        overview,
        episodes,
        beats,
        raw,
        ecg,
        beat,
        report,
        save_report,
        export,
        templates,
        template_beats,
        annotations,
        events,
        add_event,
        del_event,
        quality,
        add_beat,
        annotate,
        annotate_template,
    ],
)
