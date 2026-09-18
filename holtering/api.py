"""HTTP surface: summary / overview / ecg window / beats / episodes / templates /
manual labels, plus the built frontend."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import json

from .analysis import State
from .analysis.protocol import SECTION_TITLES, SECTIONS, Protocol
from .analysis.report import _json_default
from .analysis.quality import WANDER_MIN_MV, WANDER_RATIO, baseline, hf_residual

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
MAX_ECG_S = 120.0
MAX_BEATS_S = 3 * 3600.0


class LabelBody(BaseModel):
    label: str | None


class AddBody(BaseModel):
    t_ms: int
    label: str = "N"


class QualityBody(BaseModel):
    t0_ms: int
    t1_ms: int
    value: str | None


class EventBody(BaseModel):
    t_ms: int
    text: str = ""


class StripBody(BaseModel):
    id: str
    t0_ms: int
    dur_s: float
    caption: str = ""
    leads: list[str] | None = None


class ReportBody(BaseModel):
    text: dict[str, str] = {}              # section -> edited text (absent = generated)
    meta: dict[str, str] = {}              # clinic, doctor, referral, medication
    strips: list[StripBody] = []           # reviewer-added strips
    captions: dict[str, str] = {}          # auto strip id -> edited caption
    hidden: list[str] = []                 # auto strip ids left out
    include: dict[str, bool] = {}          # trends, hourly, strips


def create_app(st: State) -> FastAPI:
    app = FastAPI(title="holtering")
    total_s = st.mm.shape[1] / st.fs
    w = st.analysis["overview"]["noise_window_s"]

    def noise_windows(start: float, dur: float, thr: float = 0.35):
        n10 = st.analysis["overview"]["noise10"]
        wa, wb = int(start // w), int((start + dur) // w) + 1
        return [{"t0": i * w, "t1": (i + 1) * w, "score": n10[i]} for i in range(max(0, wa), min(wb, len(n10))) if n10[i] >= thr]

    def beats_in(start: float, dur: float) -> list[dict]:
        lo = int(np.searchsorted(st.t_ms, start * 1000)); hi = int(np.searchsorted(st.t_ms, (start + dur) * 1000))
        return [st.beat_info(k) for k in range(lo, hi)]

    @app.get("/api/summary")
    def summary():
        an = st.analysis
        return {k: an[k] for k in ("patient", "record", "hr", "hrv", "counts", "calibration", "computed_s", "criteria", "morphologies")}

    @app.get("/api/overview")
    def overview():
        return st.analysis["overview"]

    @app.get("/api/episodes")
    def episodes():
        return st.analysis["episodes"]

    @app.get("/api/beats")
    def beats(start: float = Query(0.0, ge=0.0), dur: float = Query(300.0, gt=0.0, le=MAX_BEATS_S)):
        """Compact columnar form for the context strip: parallel arrays, no per-beat dicts."""
        lo = int(np.searchsorted(st.t_ms, start * 1000)); hi = int(np.searchsorted(st.t_ms, (start + dur) * 1000))
        t = st.t_ms[lo:hi]
        rr = np.diff(st.t_ms[max(0, lo - 1):hi]) if hi > lo else np.array([], np.int64)
        if lo == 0 and len(rr) < len(t):
            rr = np.r_[0, rr]
        return {"start": start, "dur": dur, "first_index": lo,
                "t_ms": t.tolist(), "rr_ms": rr.tolist(),
                "label": st.code_label[lo:hi].tolist(), "cls": st.code_class[lo:hi].tolist(),
                "noise_windows": noise_windows(start, dur)}

    @app.get("/api/raw")
    def raw(start: float = Query(0.0, ge=0.0), dur: float = Query(3600.0, gt=0.0, le=3600.0), lead: str = "II"):
        """Raw int16 LE samples of one lead (application/octet-stream) for full disclosure."""
        names = st.rec.leads
        if lead not in names:
            raise HTTPException(400, f"unknown lead {lead}")
        a = int(round(start * st.fs)); b = min(st.mm.shape[1], a + int(round(dur * st.fs)))
        blk = np.ascontiguousarray(st.mm[names.index(lead), a:b], dtype="<i2")
        return Response(blk.tobytes(), media_type="application/octet-stream",
                        headers={"X-Fs": str(st.fs), "X-Start": str(start), "X-Mv-Per-Lsb": str(st.mv)})

    @app.get("/api/ecg")
    def ecg(start: float = Query(0.0, ge=0.0), dur: float = Query(10.0, gt=0.0, le=MAX_ECG_S), leads: str | None = None):
        if start >= total_s:
            raise HTTPException(400, "start beyond record")
        names = st.rec.leads
        pick = list(range(len(names)))
        if leads:
            try:
                pick = [names.index(x) for x in leads.split(",")]
            except ValueError as exc:
                raise HTTPException(400, f"unknown lead: {exc}") from exc
        a = int(round(start * st.fs)); b = min(st.mm.shape[1], a + int(round(dur * st.fs)))
        raw = np.asarray(st.mm[pick, a:b]).astype(np.float32) * st.mv
        sig = raw - np.median(raw, axis=1, keepdims=True)
        noise = hf_residual(sig, st.fs).std(axis=1) / st.analysis["calibration"]["noise_base_ii_mv"]
        slow = baseline(sig, st.fs); drift = slow.max(axis=1) - slow.min(axis=1)
        drift_thr = max(WANDER_MIN_MV, WANDER_RATIO * st.analysis["calibration"]["wander_base_ii_mv"])
        return {"start": start, "fs": st.fs, "leads": [names[i] for i in pick],
                "data": [np.round(row, 3).tolist() for row in sig],
                "lead_noise": [round(float(x), 2) for x in noise],
                "lead_drift": [round(float(x), 2) for x in drift], "drift_thr_mv": round(drift_thr, 2),
                "beats": beats_in(start, dur), "noise_windows": noise_windows(start, dur),
                "quality_manual": [q for q in st.quality if q["t1_ms"] > start * 1000 and q["t0_ms"] < (start + dur) * 1000]}

    @app.get("/api/beat/{index}")
    def beat(index: int):
        if not 0 <= index < len(st.t_ms):
            raise HTTPException(404, "no such beat")
        return st.beat_info(index)

    @app.get("/api/report")
    def report():
        """Generated protocol content plus the reviewer's saved edits (text, strips, options)."""
        pr = Protocol(st)
        return {"generated": pr.sections(), "titles": SECTION_TITLES, "order": SECTIONS, "header": pr.header(),
                "summary": pr.summary_rows(), "hourly": pr.hourly(), "auto_strips": pr.auto_strips(),
                "saved": st.report}

    @app.post("/api/report")
    def save_report(body: ReportBody):
        st.set_report(body.model_dump())
        return {"ok": True}

    @app.get("/api/export")
    def export():
        """Everything a report needs: summary, episodes, and every beat with its final label."""
        an = st.analysis
        beats = [{"t_ms": int(t), "label": str(l), "device": (str(st.dev_labels[o]) if o >= 0 else None)}
                 for t, l, o in zip(st.t_ms, st.labels, st.origin)]
        payload = {"record": an["record"], "patient": an["patient"], "hr": an["hr"], "hrv": an["hrv"], "counts": an["counts"],
                   "episodes": an["episodes"], "criteria": an["criteria"], "events": st.events_with_context(),
                   "manual": {"labels": st.relabels, "added": st.added, "quality": st.quality},
                   "beats": beats}
        return Response(json.dumps(payload, ensure_ascii=False, default=_json_default), media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=holtering-export.json"})

    @app.get("/api/templates")
    def templates():
        return st.templates()

    @app.get("/api/templates/{tid}/beats")
    def template_beats(tid: int, offset: int = 0, limit: int = Query(200, le=2000)):
        members = np.where(st.dev_template == tid)[0]
        if not len(members):
            raise HTTPException(404, "no such template")
        sel = st.dev_to_merged[members[offset:offset + limit]]
        return {"total": int(len(members)), "beats": [st.beat_info(int(k)) for k in sel]}

    @app.get("/api/annotations")
    def annotations():
        return {"labels": {str(k): v for k, v in st.relabels.items()}, "added": {str(k): v for k, v in st.added.items()}, "quality": st.quality}

    @app.get("/api/events")
    def events():
        return st.events_with_context()

    @app.post("/api/events")
    def add_event(body: EventBody):
        if not 0 <= body.t_ms <= st.total_ms:
            raise HTTPException(400, "time outside the record")
        return st.add_event(body.t_ms, body.text)

    @app.delete("/api/events/{eid}")
    def del_event(eid: int):
        st.remove_event(eid)
        return {"ok": True}

    @app.post("/api/quality")
    def quality(body: QualityBody):
        try:
            st.set_quality(body.t0_ms, body.t1_ms, body.value)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"spans": st.quality}

    @app.post("/api/beats/add")
    def add_beat(body: AddBody):
        try:
            k = st.add_beat(body.t_ms, body.label)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return st.beat_info(k)

    @app.post("/api/annotations/{index}")
    def annotate(index: int, body: LabelBody):
        if not 0 <= index < len(st.t_ms):
            raise HTTPException(404, "no such beat")
        try:
            st.set_label(index, body.label)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return st.beat_info(index)

    @app.post("/api/templates/{tid}/label")
    def annotate_template(tid: int, body: LabelBody):
        try:
            n = st.set_template_label(tid, body.label)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if n == 0:
            raise HTTPException(404, "no such template")
        return {"template": tid, "beats": n, "label": body.label}

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(DIST / "index.html")

    return app
