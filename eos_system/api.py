"""HTTP 边界：浏览器只接触登记场景、正式状态和已提交的结果。"""

from __future__ import annotations

import csv
import io
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import VERSION
from .config import Settings, list_scenarios, resolve_scenario
from .contracts import RunConfig, RunRequest, list_algorithms, validate_algorithm_params
from .controller import Controller
from .storage import Database, now


def _public_run(record: dict) -> dict:
    """隐藏 WSL 文件位置；路径属于服务端配置而不是网页协议。"""
    record["config"].pop("scenario_path", None)
    return record


def _export_json(record: dict) -> bytes:
    plan = dict(record["plan"])
    metric = record["metrics"]
    plan["metrics"] = {
        "TP": metric["TP"], "TCR": metric["TCR"], "BD": metric["BD"],
        "TM": metric["TM"], "RT": metric["RT"], "RV": metric["RV"],
    }
    plan["provenance"] = {
        "run_id": record["run_id"], "scenario_sha256": record["config"]["scenario_sha256"],
        "algorithm_id": record["config"]["algorithm_id"],
        "algorithm_version": record["config"]["algorithm_version"],
        "seed": record["config"]["seed"],
    }
    return (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _export_csv(record: dict) -> bytes:
    output = io.StringIO(newline="")
    fields = ["run_id", "scenario_id", "algorithm_id", "task_id", "satellite_id", "sensor_id",
              "sat_start_time", "sat_end_time", "ground_station_id", "gs_start_time", "gs_end_time",
              "completed_tasks", "total_tasks", "TP", "TCR", "BD", "TM", "RT"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    metrics = record["metrics"]
    base = {
        "run_id": record["run_id"], "scenario_id": record["config"]["scenario_id"],
        "algorithm_id": record["config"]["algorithm_id"],
        **{key: metrics[key] for key in ("completed_tasks", "total_tasks", "TP", "TCR", "BD", "TM", "RT")},
    }
    # 空计划也要保留一行实验摘要，避免 CSV 导出成只有表头的文件。
    for assignment in record["plan"]["assignments"] or [{}]:
        writer.writerow({key: value for key, value in {**base, **assignment}.items() if key in fields})
    return output.getvalue().encode("utf-8-sig")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    controller = Controller(settings, database)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        controller.start()
        try:
            yield
        finally:
            controller.stop()

    app = FastAPI(title="EOS 课程调度系统", version=VERSION, lifespan=lifespan)
    web_dir = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": {
            "code": f"HTTP_{exc.status_code}", "message": str(exc.detail), "details": {},
        }})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(map(str, error["loc"])), "message": error["msg"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {
            "code": "VALIDATION_ERROR", "message": "请求字段校验失败", "details": details,
        }})

    @app.get("/")
    def home():
        return FileResponse(web_dir / "index.html")

    @app.get("/api/health")
    def health():
        with database.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "version": VERSION, "controller_instance_id": controller.instance_id, "time": now()}

    @app.get("/api/scenarios")
    def scenarios():
        return {"items": list_scenarios(settings)}

    @app.get("/api/algorithms")
    def algorithms():
        return {"items": list_algorithms()}

    @app.post("/api/runs", status_code=202)
    def submit_run(request: RunRequest, idempotency_key: str | None = Header(default=None)):
        try:
            validate_algorithm_params(request.algorithm_id, request.algorithm_params)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            scene, digest = resolve_scenario(settings, request.scenario_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        config = RunConfig(
            **request.model_dump(), run_id=str(uuid.uuid4()), scenario_sha256=digest,
            scenario_path=str(scene), algorithm_version=VERSION, created_at=now(),
        )
        try:
            run_id, _ = database.enqueue(config, settings.max_queued, idempotency_key)
        except OverflowError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run_id": run_id, "status": database.get_status(run_id)["status"], "url": f"/api/runs/{run_id}"}

    @app.get("/api/runs")
    def runs(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        return database.list_runs(limit, offset)

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        record = database.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="实验不存在")
        return _public_run(record)

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: str):
        result = database.request_cancel(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="实验不存在")
        status, accepted = result
        if not accepted:
            raise HTTPException(status_code=409, detail=f"实验已结束：{status}")
        return {"run_id": run_id, "status": status, "cancel_requested": True}

    @app.get("/api/runs/{run_id}/export")
    def export_run(run_id: str, format: str = Query(pattern="^(json|csv)$")):
        record = database.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="实验不存在")
        if record["status"] != "SUCCEEDED" or record["plan"] is None or record["metrics"] is None:
            raise HTTPException(status_code=409, detail="实验尚无正式成功结果")
        public = _public_run(record)
        content = _export_json(public) if format == "json" else _export_csv(public)
        database.record_export(run_id, format, content)
        name = f"eos-{run_id}.{format}"
        media = "application/json" if format == "json" else "text/csv"
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    return app
