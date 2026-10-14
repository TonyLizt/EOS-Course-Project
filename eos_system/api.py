"""HTTP 边界：浏览器只接触登记场景、正式状态和已提交的结果。"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import VERSION
from .algorithm_registry import get_algorithm, list_algorithms
from .config import Settings, list_scenarios_in, normalise_user_path, require_writable_directory, resolve_scenario_in
from .contracts import DirectoryRegistration, RunConfig, RunRequest
from .controller import Controller
from .deletion import remove_exported_files
from .exporting import render_csv, render_json
from .storage import Database, now
from .visualization import OrbitUnavailable, orbit_cache_path


def _public_run(record: dict) -> dict:
    """隐藏 WSL 文件位置；路径属于服务端配置而不是网页协议。"""
    record["config"].pop("scenario_path", None)
    return record


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    database.ensure_defaults(settings.scenario_dir, settings.runtime_dir)
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
    def scenarios(source_id: str = "runtime"):
        source = database.get_data_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="数据源未登记")
        return {"source_id": source_id, "items": list_scenarios_in(Path(source["root_path"]), source_id)}

    @app.get("/api/data-sources")
    def data_sources():
        return {"items": database.list_data_sources()}

    @app.post("/api/data-sources", status_code=201)
    def register_data_source(request: DirectoryRegistration):
        try:
            root = normalise_user_path(request.path)
            for profile in database.list_output_profiles():
                if profile["root_path"] and (root.is_relative_to(Path(profile["root_path"])) or Path(profile["root_path"]).is_relative_to(root)):
                    raise ValueError("数据源目录不能与已有文件输出目录重叠")
            return database.add_data_source(f"src-{uuid.uuid4().hex[:12]}", request.name.strip(), root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="该数据源目录已登记") from exc

    @app.get("/api/output-profiles")
    def output_profiles():
        return {"items": database.list_output_profiles()}

    @app.post("/api/output-profiles", status_code=201)
    def register_output_profile(request: DirectoryRegistration):
        try:
            root = normalise_user_path(request.path)
            for source in database.list_data_sources():
                source_root = Path(source["root_path"])
                if root.is_relative_to(source_root) or source_root.is_relative_to(root):
                    raise ValueError("文件输出目录不能与已登记数据源目录重叠")
            require_writable_directory(root)
            return database.add_output_profile(f"out-{uuid.uuid4().hex[:12]}", request.name.strip(), root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="该输出目录已登记") from exc

    @app.get("/api/algorithms")
    def algorithms():
        return {"items": list_algorithms()}

    @app.post("/api/runs", status_code=202)
    def submit_run(request: RunRequest, idempotency_key: str | None = Header(default=None)):
        try:
            spec = get_algorithm(request.algorithm_id)
            spec.parse_params(request.algorithm_params)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        source = database.get_data_source(request.source_id)
        profile = database.get_output_profile(request.output_profile_id)
        if source is None or profile is None:
            raise HTTPException(status_code=404, detail="数据源或输出方案未登记")
        try:
            scene, digest = resolve_scenario_in(Path(source["root_path"]), request.scenario_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        config = RunConfig(
            **request.model_dump(), run_id=str(uuid.uuid4()), scenario_sha256=digest,
            scenario_path=str(scene), output_kind=profile["kind"], output_root=profile["root_path"],
            algorithm_version=spec.version, created_at=now(),
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

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str, delete_files: bool = False):
        """永久清理一条终态实验；目录文件由用户明确选择是否同时删除。"""
        try:
            with controller.finalization_lock:
                deleted = database.delete_finished_run(run_id)
                if deleted is None:
                    raise HTTPException(status_code=404, detail="实验不存在")
                files_removed, warnings = remove_exported_files(deleted) if delete_files else (0, [])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            database.compact_after_delete()
            compacted = True
        except sqlite3.OperationalError as exc:
            # 删除已经提交；压缩失败只影响磁盘空间的即时回收，空闲页仍可被后续实验复用。
            compacted = False
            warnings.append(f"数据库暂未压缩：{exc}")
        return {"run_id": run_id, "deleted": True, "files_removed": files_removed,
                "database_compacted": compacted, "warnings": warnings}

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
        with controller.finalization_lock:
            record = database.get_run(run_id)
            if record is None:
                raise HTTPException(status_code=404, detail="实验不存在")
            if record["status"] != "SUCCEEDED" or record["plan"] is None or record["metrics"] is None:
                raise HTTPException(status_code=409, detail="实验尚无正式成功结果")
            public = _public_run(record)
            content = render_json(public) if format == "json" else render_csv(public)
            database.record_export(run_id, format, content)
        name = f"eos-{run_id}.{format}"
        media = "application/json" if format == "json" else "text/csv"
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def successful_run(run_id: str) -> dict:
        record = database.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="实验不存在")
        if record["status"] != "SUCCEEDED" or record["plan"] is None or record["metrics"] is None:
            raise HTTPException(status_code=409, detail="实验尚无正式成功结果")
        return record

    @app.get("/api/runs/{run_id}/visualization/schedule")
    def visualization_schedule(run_id: str):
        """旧页面直接读取的计划 JSON，不将页面查看计为一次文件导出。"""
        return Response(render_json(successful_run(run_id)), media_type="application/json")

    @app.get("/api/runs/{run_id}/visualization/orbit.czml")
    def visualization_orbit(run_id: str):
        record = successful_run(run_id)
        config = record["config"]
        try:
            target = orbit_cache_path(settings, Path(config["scenario_path"]), config["scenario_sha256"])
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail="场景文件已不存在，不能生成回放") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OrbitUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return FileResponse(target, media_type="application/json")

    @app.get("/visualization/gantt-page")
    def gantt_page():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "gantt_viewer.html")

    @app.get("/visualization/cesium-page")
    def cesium_page():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "cesium_viewer.html")

    @app.get("/visualization/gantt/{run_id}")
    def open_gantt(run_id: str):
        successful_run(run_id)
        schedule = f"/api/runs/{run_id}/visualization/schedule"
        return RedirectResponse("/visualization/gantt-page?" + urlencode({"schedule": schedule}))

    @app.get("/visualization/cesium/{run_id}")
    def open_cesium(run_id: str):
        successful_run(run_id)
        schedule = f"/api/runs/{run_id}/visualization/schedule"
        orbit = f"/api/runs/{run_id}/visualization/orbit.czml"
        gantt = f"/visualization/gantt/{run_id}"
        return RedirectResponse("/visualization/cesium-page?" + urlencode({"schedule": schedule, "czml": orbit, "gantt": gantt}))

    return app
