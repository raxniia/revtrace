from __future__ import annotations

import json
from functools import lru_cache

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool

from .config import ROOT
from .service import Service, ServiceError

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class InvestigationRequest(BaseModel):
    question: str
    dataset: str | None = None
    mode: str = "auto"
    current: str | None = None
    baseline: str | None = None


class Decision(BaseModel):
    approve: bool


@lru_cache
def get_service() -> Service:
    return Service()


def create_app() -> FastAPI:
    app = FastAPI(title="RevTrace", version="0.1.0")

    @app.exception_handler(ServiceError)
    async def service_error(_, exc: ServiceError):
        raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/config")
    def config(service: Service = Depends(get_service)):
        return service.config()

    @app.get("/api/overview")
    def overview(
        dataset: str | None = None,
        current: str | None = None,
        baseline: str | None = None,
        service: Service = Depends(get_service),
    ):
        return _guard(lambda: service.overview(dataset, current, baseline))

    @app.post("/api/investigations", status_code=202)
    def start(body: InvestigationRequest, service: Service = Depends(get_service)):
        investigation_id = _guard(
            lambda: service.investigate(body.question, body.dataset, body.mode, body.current, body.baseline)
        )
        return {"id": investigation_id}

    @app.get("/api/investigations")
    def history(dataset: str | None = None, service: Service = Depends(get_service)):
        return service.store.investigations(dataset)

    @app.get("/api/investigations/{investigation_id}")
    def investigation(investigation_id: str, service: Service = Depends(get_service)):
        return _guard(lambda: service.investigation(investigation_id), status=404)

    @app.get("/api/investigations/{investigation_id}/events")
    async def events(investigation_id: str, service: Service = Depends(get_service)):
        if investigation_id not in service._live and service.store.investigation(investigation_id) is None:
            raise HTTPException(status_code=404, detail="Investigation not found.")

        def frames():
            for event in service.stream(investigation_id):
                yield ": keep-alive\n\n" if event is None else f"data: {json.dumps(event)}\n\n"
            yield "event: end\ndata: {}\n\n"

        return StreamingResponse(
            iterate_in_threadpool(frames()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/actions")
    def actions(service: Service = Depends(get_service)):
        return {"actions": service.store.actions(), "outbox": service.store.outbox()}

    @app.post("/api/actions/{action_id}/decision")
    def decide(action_id: str, body: Decision, service: Service = Depends(get_service)):
        return _guard(lambda: service.decide(action_id, body.approve))

    @app.post("/api/datasets", status_code=201)
    async def upload(
        name: str = Form(...),
        files: list[UploadFile] = File(...),
        service: Service = Depends(get_service),
    ):
        contents: dict[str, bytes] = {}
        total = 0
        for file in files:
            data = await file.read()
            total += len(data)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Upload is larger than 25 MB.")
            contents[file.filename or ""] = data
        return _guard(lambda: service.add_dataset(name, contents))

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="app")
    return app


def _guard(fn, status: int = 400):
    try:
        return fn()
    except ServiceError as exc:
        raise HTTPException(status_code=status, detail=str(exc)) from exc


app = create_app()
