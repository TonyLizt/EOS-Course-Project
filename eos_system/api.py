"""HTTP 边界：浏览器只接触登记场景、正式状态和已提交的结果。"""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import VERSION
from .algorithm_registry import get_algorithm, list_algorithms, list_schedule_models, COMPARISON_ALGORITHMS, availability
from .config import Settings, algorithm_source_sha256, list_scenarios_in, normalise_user_path, require_writable_directory, resolve_scenario_in
from .contracts import DirectoryRegistration, ReplayRequest, RunConfig, RunRequest
from .controller import Controller
from .deletion import remove_exported_files
from .exporting import render_csv, render_json, require_certified_record
from .storage import Database, now
from .replay_service import ReplayError, ReplayService, REPLAY_CONFIG_ID
from .visualization import OrbitUnavailable, orbit_cache_path
from .provenance import capture_provenance
from .scenario_catalog import ScenarioCatalog
from .config import sha256_file
from .planning_preview import require_preview_record, preview_schedule


def _public_run(record: dict) -> dict:
    """隐藏 WSL 文件位置；路径属于服务端配置而不是网页协议。"""
    record["config"].pop("scenario_path", None)
    return record


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    database.ensure_defaults(settings.scenario_dir, settings.runtime_dir)
    catalog = ScenarioCatalog(Path(__file__).resolve().parent.parent)
    catalog_warnings = catalog.register_sources(database)
    controller = Controller(settings, database)
    replay = ReplayService(settings, database)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        controller.start()
        try:
            replay.recover()
            yield
        finally:
            try:
                replay.close()
            finally:
                controller.stop()

    app = FastAPI(title="EOS 课程调度系统", version=VERSION, lifespan=lifespan)
    app.state.replay = replay
    app.state.controller = controller
    app.state.database = database
    web_dir = Path(__file__).parent / "web"
    web_digest = hashlib.sha256()
    for asset in sorted(web_dir.iterdir()):
        if asset.suffix in {".html", ".js", ".css"}:
            web_digest.update(asset.name.encode())
            web_digest.update(asset.read_bytes())
    ui_build_id = web_digest.hexdigest()[:12]
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.middleware("http")
    async def current_ui(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/") or request.url.path in {"/visualization/gantt-page", "/visualization/gantt"}:
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-EOS-UI-Build"] = ui_build_id
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": {
            "code": f"HTTP_{exc.status_code}", "message": str(exc.detail), "details": {},
        }})

    @app.exception_handler(ReplayError)
    async def replay_error(_: Request, exc: ReplayError):
        return JSONResponse(status_code=exc.status, content={"error": {
            "code": exc.code, "message": exc.message, "details": {},
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
        return {"status": "ok", "version": VERSION, "controller_instance_id": controller.instance_id, "time": now(),
                "ui": {"name": "统一调度控制台", "build_id": ui_build_id}}

    @app.get("/api/scenarios")
    def scenarios(source_id: str = "runtime", execution_mode: Literal['formal','planning_preview'] = 'formal'):
        source = database.get_data_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="数据源未登记")
        return {"source_id": source_id, "items": catalog.list_scenarios(Path(source["root_path"]), source_id,
            planning_preview=execution_mode == 'planning_preview')}

    @app.get("/api/data-sources")
    def data_sources():
        return {"items": database.list_data_sources(), "catalog_warnings": catalog_warnings}

    @app.post("/api/data-sources", status_code=201)
    def register_data_source(request: DirectoryRegistration):
        try:
            root = normalise_user_path(request.path)
            replay_root = settings.replay_dir.resolve()
            if root.is_relative_to(replay_root) or replay_root.is_relative_to(root):
                raise ValueError("数据源目录不能包含回放运行缓存")
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
            replay_root = settings.replay_dir.resolve()
            if root.is_relative_to(replay_root) or replay_root.is_relative_to(root):
                raise ValueError("正式输出目录不能与回放缓存重叠")
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
        return {"items": list_algorithms(), "models": list_schedule_models()}

    @app.post("/api/runs", status_code=202)
    def submit_run(request: RunRequest, idempotency_key: str | None = Header(default=None)):
        try:
            spec = get_algorithm(request.algorithm_id)
            if request.algorithm_id not in COMPARISON_ALGORITHMS:
                raise ValueError('请选择九种比较算法之一；完成率优先和自适应修复请在初始排程模型中选择。')
            state, message = availability(request.algorithm_id)
            if state != 'ready':
                raise ValueError(message)
            spec.parse_params(request.algorithm_params)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        source = database.get_data_source(request.source_id)
        profile = database.get_output_profile(request.output_profile_id)
        if source is None or profile is None:
            raise HTTPException(status_code=404, detail="数据源或输出方案未登记")
        if request.execution_mode == 'planning_preview' and profile['kind'] != 'download':
            raise HTTPException(status_code=422, detail='规划预览不能写入正式输出目录，请选择仅浏览器下载。')
        try:
            scene, digest = resolve_scenario_in(Path(source["root_path"]), request.scenario_id)
            catalog.verify_identity(scene, digest)
            provenance = capture_provenance(scene, digest)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        config = RunConfig(
            **request.model_dump(), run_id=str(uuid.uuid4()), scenario_sha256=digest,
            scenario_path=str(scene), output_kind=profile["kind"], output_root=profile["root_path"],
            algorithm_version=spec.version,
            algorithm_code_sha=algorithm_source_sha256(), scenario_provenance=provenance, created_at=now(),
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
            with replay.mutation_lock, controller.finalization_lock:
                deleted = database.delete_finished_run(run_id)
                if deleted is None:
                    raise HTTPException(status_code=404, detail="实验不存在")
                files_removed, warnings = remove_exported_files(deleted) if delete_files else (0, [])
                warnings.extend(replay.cleanup_deleted(deleted["replay_ids"]))
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
            try:
                require_certified_record(record)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            public = _public_run(record)
            content = render_json(public) if format == "json" else render_csv(public)
            database.record_export(run_id, format, content)
        name = f"eos-{run_id}.{format}"
        media = "application/json" if format == "json" else "text/csv"
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def successful_run(run_id: str, *, allow_preview: bool = True) -> dict:
        record = database.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="实验不存在")
        if record["status"] != "SUCCEEDED" or record["plan"] is None or record["metrics"] is None:
            raise HTTPException(status_code=409, detail="实验尚无正式成功结果")
        try:
            if allow_preview and record['config'].get('execution_mode') == 'planning_preview':
                require_preview_record(record)
            else:
                require_certified_record(record)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return record

    @app.get("/api/runs/{run_id}/visualization/schedule")
    def visualization_schedule(run_id: str):
        """保持旧页面使用的顶层计划结构，只附加正式计划的身份摘要。"""
        record = successful_run(run_id)
        source = database.get_replay_source(run_id)
        schedule = (preview_schedule(record) if record.get('result_kind') == 'planning_preview'
                    else json.loads(render_json(record)))
        schedule["plan_sha256"] = source["plan_sha256"]
        schedule["provenance"]["plan_sha256"] = source["plan_sha256"]
        return Response(json.dumps(schedule, ensure_ascii=False), media_type="application/json")

    @app.get("/api/replay-configs")
    def replay_configs():
        return {"default_id": REPLAY_CONFIG_ID, "items": [{
            "replay_config_id":REPLAY_CONFIG_ID, "name":"固定载荷回放（几何示意）",
            "supports_viewer":True, "attitude_source":"geometry_pointing_illustration",
            # 兼容旧客户端的字段，但明确它是首选值；实际步长读 READY manifest。
            "attitude_step_s":5, "attitude_step_is_preferred":True,
            "sampling_strategy":"adaptive_budget_v1", "preferred_attitude_step_s":5,
            "target_samples":100000, "max_samples":200000, "max_attitude_step_s":300,
        }]}

    @app.post("/api/runs/{run_id}/replay")
    def create_replay(run_id: str, request: ReplayRequest):
        record, status = replay.request(run_id, request.replay_config_id)
        return JSONResponse(status_code=status, content=replay.public(run_id, record))

    @app.get("/api/runs/{run_id}/replay")
    def current_replay(run_id: str, replay_config_id: str | None = None):
        record = replay.current(run_id, replay_config_id)
        return replay.public(run_id, record, replay_config_id)

    @app.get("/api/runs/{run_id}/replays/{replay_id}")
    def exact_replay(run_id: str, replay_id: str):
        return replay.public(run_id, replay.exact(run_id, replay_id))

    @app.get("/api/runs/{run_id}/replays/{replay_id}/resources/{resource_key}")
    def replay_resource(run_id: str, replay_id: str, resource_key: str,
                        if_none_match: str | None = Header(default=None)):
        content, descriptor = replay.read_resource(run_id, replay_id, resource_key)
        etag = '"' + descriptor["sha256"] + '"'
        if if_none_match == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return Response(content, media_type=descriptor["mime"], headers={
            "ETag": etag, "Cache-Control": "private, max-age=0, must-revalidate",
        })

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

    @app.get("/api/runs/{run_id}/visualization/replay")
    def visualization_replay(run_id: str):
        """过渡读取层复用 READY 文件；GET 不再隐式构建另一套侧车。"""
        return replay.document(run_id)

    @app.get("/visualization/gantt-page")
    def gantt_page():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "gantt_viewer.html")

    @app.get("/visualization/cesium-page")
    def cesium_page():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "cesium_viewer.html")

    @app.get("/visualization/fixed-payload-state.js")
    def fixed_payload_state_script():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "fixed-payload-state.js",
                            media_type="text/javascript")

    @app.get("/visualization/fixed-payload-geometry.js")
    def fixed_payload_geometry_script():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "fixed-payload-geometry.js",
                            media_type="text/javascript")

    @app.get("/visualization/fixed-payload-view.js")
    def fixed_payload_view_script():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "fixed-payload-view.js",
                            media_type="text/javascript")

    @app.get("/visualization/fixed-payload-renderer.js")
    def fixed_payload_renderer_script():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "fixed-payload-renderer.js",
                            media_type="text/javascript")

    @app.get("/visualization/trackpad-zoom.js")
    def trackpad_zoom_script():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "trackpad-zoom.js",
                            media_type="text/javascript")

    @app.get("/visualization/satellite-follow.js")
    def satellite_follow_script():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "satellite-follow.js",
                            media_type="text/javascript")

    @app.get("/visualization/camera-diagnostics.js")
    def camera_diagnostics_script():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "camera-diagnostics.js",
                            media_type="text/javascript")

    @app.get("/visualization/replay-build-policy.js")
    def replay_build_policy_script():
        return FileResponse(Path(__file__).resolve().parent.parent / "draw" / "replay-build-policy.js",
                            media_type="text/javascript")

    @app.get("/visualization/assets/satellites/landsat8.glb")
    def landsat8_model(sha: str | None = None):
        model_path = Path(__file__).resolve().parent.parent / "assets/satellites/landsat8.glb"
        if sha is not None and sha != sha256_file(model_path):
            raise HTTPException(status_code=409, detail="模型资产版本已变化，请重新构建回放")
        return FileResponse(model_path,
                            media_type="model/gltf-binary")

    @app.get("/visualization/gantt/{run_id}")
    def open_gantt(run_id: str):
        successful_run(run_id)
        schedule = f"/api/runs/{run_id}/visualization/schedule"
        return RedirectResponse("/visualization/gantt-page?" + urlencode({"schedule": schedule}))

    @app.get("/visualization/gantt")
    def gantt_entry(run_id: str | None = None):
        if run_id:
            return open_gantt(run_id)
        return FileResponse(Path(__file__).resolve().parent / "web" / "gantt-runs.html")

    @app.get("/visualization/cesium/{run_id}")
    def open_cesium(run_id: str):
        successful_run(run_id)
        schedule = f"/api/runs/{run_id}/visualization/schedule"
        # 页面先读取构建状态，只有显式点击构建/重试才 POST；保留独立旧 orbit GET。
        status_url = f"/api/runs/{run_id}/replay"
        gantt = f"/visualization/gantt/{run_id}"
        return RedirectResponse("/visualization/cesium-page?" + urlencode({
            "run_id":run_id, "schedule":schedule, "replay_status":status_url, "gantt":gantt}))

    return app
