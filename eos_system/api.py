"""HTTP 边界：浏览器只接触登记场景、正式状态和已提交的结果。"""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlsplit, unquote

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import VERSION
from .algorithm_registry import get_algorithm, list_algorithms, list_schedule_models, COMPARISON_ALGORITHMS, availability
from .config import Settings, algorithm_source_sha256, list_scenarios_in, normalise_user_path, require_writable_directory, resolve_scenario_in
from .contracts import DirectoryRegistration, ReplayRequest, RunConfig, RunRequest, ExperimentRequest, ExperimentAlgorithm, ControlExperimentRequest
from .experiments import Experiments
from .controller import Controller
from .temporary_controls import TemporaryControls
from .deletion import remove_exported_files
from .exporting import render_csv, render_json, require_certified_record, require_exportable_record
from .storage import Database, now
from .statistics_export import StatisticsExportRequest
from .replay_service import ReplayError, ReplayService, REPLAY_CONFIG_ID
from .visualization import OrbitUnavailable, orbit_cache_path
from .provenance import capture_execution_provenance
from .scenario_catalog import ScenarioCatalog
from .config import sha256_file
from .planning_preview import require_preview_record, preview_schedule


def _public_run(record: dict) -> dict:
    """隐藏 WSL 文件位置；路径属于服务端配置而不是网页协议。"""
    from .result_scoring import score_run
    record['ranking_score'] = record.get('ranking_score') or score_run(record)
    resources = [e['payload'] for e in record.get('events', [])
                 if e['event_type'] == 'EXECUTION_RESOURCES']
    record['execution_resources'] = resources[-1] if resources else record.get('execution_resources')
    record["config"].pop("scenario_path", None)
    return record


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    database.ensure_defaults(settings.scenario_dir, settings.runtime_dir)
    experiments = Experiments(database)
    catalog = ScenarioCatalog(Path(__file__).resolve().parent.parent)
    catalog_warnings = catalog.register_sources(database)
    controller = Controller(settings, database)
    temporary = TemporaryControls(database.expected_certification_context, settings.max_queued)
    controller.transient = temporary
    replay = ReplayService(settings, database)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        controller.start()
        try:
            replay.recover()
            yield
        finally:
            controller.announce_stopping()
            temporary.close()
            try:
                replay.close()
            finally:
                controller.stop()

    app = FastAPI(title="EOS 课程调度系统", version=VERSION, lifespan=lifespan)
    app.state.replay = replay
    app.state.controller = controller
    app.state.database = database
    app.state.experiments = experiments
    app.state.temporary_controls = temporary
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
        if request.url.path == "/" or request.url.path.startswith(("/static/", "/visualization/experiments/", "/api/temporary-controls/", "/visualization/temporary-gantt/")) or request.url.path in {"/visualization/gantt-page", "/visualization/gantt", "/visualization/cesium-page"}:
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
        heartbeat = controller.heartbeat()
        # The watchdog applies its configurable monotonic progress timeout.
        return {"status": "ok", "version": VERSION, "controller_instance_id": controller.instance_id, "time": now(),
                "controller": heartbeat,
                "ui": {"name": "统一调度控制台", "build_id": ui_build_id}}

    @app.get('/api/execution-settings')
    def execution_settings():
        return controller.execution_status()

    @app.put('/api/execution-settings')
    async def update_execution_settings(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict) or set(payload) != {'max_workers'}:
                raise ValueError('只允许指定 max_workers')
            return controller.set_max_workers(payload['max_workers'])
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/scenarios")
    def scenarios(source_id: str = "runtime", execution_mode: Literal['formal','planning_preview','physical_validation'] = 'physical_validation'):
        source = database.get_data_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="数据源未登记")
        return {"source_id": source_id, "items": catalog.list_scenarios(Path(source["root_path"]), source_id,
            planning_preview=execution_mode in ('planning_preview', 'physical_validation'))}

    @app.get("/api/models")
    def models():
        from algorithms.lavis.model import list_models
        return {"algorithm_id": "lavis", "items": list_models()}

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
        from .algorithm_presentation import list_presented_algorithms
        return {"items": list_presented_algorithms(), "models": list_schedule_models()}

    def build_run_config(request: RunRequest):
        try:
            spec = get_algorithm(request.algorithm_id)
            if request.algorithm_id not in COMPARISON_ALGORITHMS:
                raise ValueError('请选择已注册的比较算法；完成率优先和自适应修复请在初始排程模型中选择。')
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
            provenance = capture_execution_provenance(scene, digest, request.execution_mode)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        model_provenance = {}
        if request.algorithm_id == 'lavis':
            from algorithms.lavis.model import freeze
            from algorithms.objective_adapters.protocol import validate_model_request
            try:
                model_provenance = freeze(spec.parse_params(request.algorithm_params).model_id)
                validate_model_request('lavis', request, model_provenance)
                from utils.course_compatibility import model_scene_compatible
                if not model_scene_compatible(model_provenance, provenance):
                    raise ValueError('LAVIS_SCENARIO_PHYSICS_DOMAIN_MISMATCH')
            except (ValueError,OSError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if request.algorithm_id == 'ppo':
            from algorithms.ppo.model import freeze
            from algorithms.ppo.protocol import validate_scene
            from algorithms.objective_adapters.protocol import validate_model_request
            try:
                model_provenance = freeze(spec.parse_params(request.algorithm_params).model_id)
                validate_model_request('ppo', request, model_provenance)
                raw_scene = json.loads(scene.read_bytes())
                if raw_scene.get('ground_stations'):
                    raise ValueError('PPO_MODEL_DOMAIN_MISMATCH: ground stations unsupported')
                validate_scene(raw_scene, provenance, model_provenance)
            except (ValueError, OSError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        from algorithms.objective_adapters.protocol import freeze_adapter
        objective_adapter = freeze_adapter(request.algorithm_id, spec.version, request.objective_weights, model_provenance)
        config = RunConfig(
            objective_adapter=objective_adapter,
            **request.model_dump(), model_provenance=model_provenance, run_id=str(uuid.uuid4()), scenario_sha256=digest,
            scenario_path=str(scene), output_kind=profile["kind"], output_root=profile["root_path"],
            algorithm_version=spec.version,
            algorithm_code_sha=algorithm_source_sha256(), scenario_provenance=provenance, created_at=now(),
        )
        return config

    @app.post("/api/runs", status_code=202)
    def submit_run(request: RunRequest, idempotency_key: str | None = Header(default=None)):
        config = build_run_config(request)
        try:
            run_id, _ = database.enqueue(config, settings.max_queued, idempotency_key)
        except OverflowError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        experiments.adopt_legacy()
        return {"run_id": run_id, "status": database.get_status(run_id)["status"], "url": f"/api/runs/{run_id}"}

    def experiment_call(func, *args):
        try:
            return func(*args)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    def public_experiment(record):
        record['config'].pop('scenario_path', None)
        record['config'].pop('output_root', None)
        for run in record.get('runs', []):
            _public_run(run)
        return record

    @app.post('/api/experiments', status_code=202)
    def create_experiment(request: ExperimentRequest, idempotency_key: str | None = Header(default=None)):
        configs = [build_run_config(item) for item in request.runs]
        eid = experiment_call(experiments.create, configs, settings.max_queued, idempotency_key)
        return public_experiment(experiments.detail(eid))

    @app.get('/api/experiments')
    def list_experiments(limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        result = experiments.listing(limit, offset)
        result['items'] = [public_experiment(item) for item in result['items']]
        return result

    @app.get('/api/experiments/{experiment_id}')
    def experiment_detail(experiment_id: str):
        return public_experiment(experiment_call(experiments.detail, experiment_id))

    @app.get('/api/experiments/{experiment_id}/compare/{other_id}')
    def compare_experiments(experiment_id: str, other_id: str):
        records = experiment_call(experiments.compare, experiment_id, other_id)
        return {'items': [public_experiment(r) for r in records]}

    def control_configs(experiment_id, request):
        original=experiment_call(experiments.detail,experiment_id)
        if original['legacy'] or not original['runs']:
            raise HTTPException(status_code=409,detail='旧记录无完整实验身份或实验没有算法，请新建实验')
        shared=experiment_call(experiments.common,experiment_id)
        if shared.get('schedule_model')==request.schedule_model:
            raise HTTPException(status_code=422,detail='请选择不同的初始排程模型')
        configs=[]
        for run in original['runs']:
            raw={k:v for k,v in run['config'].items() if k in RunRequest.model_fields}
            raw['schedule_model']=request.schedule_model
            config=build_run_config(RunRequest.model_validate(raw))
            if config.model_provenance != run['config'].get('model_provenance', {}):
                raise HTTPException(status_code=409,detail='冻结模型已变化，不能创建单变量对照')
            expected=dict(shared);expected['schedule_model']=request.schedule_model
            from .experiments import common_config
            if common_config(config.model_dump())!=expected:
                raise HTTPException(status_code=409,detail='场景、代码或来源配置已变化，不能创建单变量对照实验')
            configs.append(config)
        current = experiment_call(experiments.detail, experiment_id)
        if [(r['run_id'],r['config']) for r in original['runs']] != [(r['run_id'],r['config']) for r in current['runs']]:
            raise HTTPException(status_code=409,detail='原实验算法已变化，请刷新后重试')
        return configs

    @app.post('/api/experiments/{experiment_id}/temporary-control',status_code=202)
    def create_temporary_control(experiment_id: str, request: ControlExperimentRequest,
                                 idempotency_key: str | None = Header(default=None)):
        configs = control_configs(experiment_id, request)
        return experiment_call(temporary.create, experiment_id, configs, idempotency_key)

    @app.get('/api/temporary-controls/{control_id}')
    def temporary_control_detail(control_id: str):
        return experiment_call(temporary.detail, control_id)

    @app.delete('/api/temporary-controls/{control_id}',status_code=202)
    def delete_temporary_control(control_id: str):
        temporary.delete(control_id)
        return {'removed':True, 'temporary':True}

    @app.get('/api/temporary-controls/{control_id}/runs/{run_id}/schedule')
    def temporary_gantt_schedule(control_id: str, run_id: str):
        schedule = experiment_call(temporary.schedule, control_id, run_id)
        schedule['algorithm_name'] = get_algorithm(schedule['algorithm_id']).name
        return schedule

    @app.get('/visualization/temporary-gantt/{control_id}/{run_id}')
    def temporary_gantt_page(control_id: str, run_id: str):
        experiment_call(temporary.schedule, control_id, run_id)
        url = f'/api/temporary-controls/{control_id}/runs/{run_id}/schedule'
        return RedirectResponse('/visualization/gantt-page?' + urlencode({'schedule':url}),status_code=303)

    # Compatibility API for explicit persistent model-only experiments; no UI uses it.
    @app.post('/api/experiments/{experiment_id}/control',status_code=202)
    def create_control_experiment(experiment_id: str, request: ControlExperimentRequest,
                                  idempotency_key: str | None = Header(default=None)):
        configs = control_configs(experiment_id, request)
        eid=experiment_call(experiments.create,configs,settings.max_queued,idempotency_key,experiment_id)
        return public_experiment(experiments.detail(eid))

    @app.get('/api/experiments/{experiment_id}/peers')
    def experiment_peers(experiment_id: str):
        base = experiment_call(experiments.common, experiment_id)
        base_model = base.pop('schedule_model', None)
        items = []
        # Only explicit compatible model-only pairs, never arbitrary condition groups.
        with database.connect() as conn:
            ids = conn.execute('SELECT experiment_id,created_at,common_json FROM experiments WHERE legacy=0 ORDER BY created_at DESC').fetchall()
        for row in ids:
            try:
                candidate = json.loads(row['common_json'])
                candidate_model = candidate.pop('schedule_model', None)
                if candidate_model == base_model or candidate != base:
                    continue
                experiments.assert_comparable(experiment_id, row['experiment_id'])
                common = experiments.common(row['experiment_id'])
                items.append({'experiment_id': row['experiment_id'], 'schedule_model': common['schedule_model'], 'created_at':row['created_at']})
            except ValueError:
                pass
        return {'items': items}

    @app.post('/api/experiments/{experiment_id}/algorithms', status_code=202)
    def add_experiment_algorithm(experiment_id: str, request: ExperimentAlgorithm):
        shared = experiment_call(experiments.common, experiment_id)
        raw = {k: v for k, v in shared.items() if k in RunRequest.model_fields}
        raw.update(request.model_dump())
        config = build_run_config(RunRequest.model_validate(raw))
        experiment_call(experiments.add, experiment_id, config, settings.max_queued)
        return public_experiment(experiments.detail(experiment_id))

    @app.delete('/api/experiments/{experiment_id}/algorithms/{algorithm_id}')
    def remove_experiment_algorithm(experiment_id: str, algorithm_id: str):
        rid = experiment_call(experiments.remove, experiment_id, algorithm_id)
        return {'removed': True, 'run_id': rid, 'retained_history': True}

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

    @app.post('/api/statistics/export')
    def statistics_export(request: StatisticsExportRequest):
        # 先读取受保护的结果快照，压缩在锁外进行，避免阻塞Worker终态提交。
        from .statistics_export import MAX_RUNS, render_statistics
        ids = list(dict.fromkeys(request.experiment_ids))
        items = []
        with controller.finalization_lock:
            with database.connect() as conn:
                for eid in ids:
                    if conn.execute('SELECT 1 FROM experiments WHERE experiment_id=?', (eid,)).fetchone() is None:
                        raise HTTPException(status_code=404, detail='所选实验已不存在，请刷新列表')
                    links = conn.execute('SELECT run_id,removed_at FROM experiment_runs WHERE experiment_id=? '
                        + ('' if request.include_removed else 'AND removed_at IS NULL ') + 'ORDER BY rowid', (eid,)).fetchall()
                    for link in links:
                        if len(items) >= MAX_RUNS:
                            raise HTTPException(status_code=413, detail='一次最多导出500次算法运行，请分批选择实验')
                        record = database.get_run(link['run_id'])
                        if record is not None:
                            items.append({'experiment_id': eid, 'removed_at': link['removed_at'], 'record': record})
        try:
            content = render_statistics(items, request.format, ids, request.include_removed)
        except OverflowError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        from datetime import datetime, timezone
        name = 'eos-statistics-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.' + request.format
        media = 'text/csv' if request.format == 'csv' else 'application/zip'
        return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="{name}"',
            'Cache-Control': 'no-store', 'X-EOS-Statistics-Schema': 'eos-statistics-v1'})

    @app.get("/api/runs/{run_id}/export")
    def export_run(run_id: str, format: str = Query(pattern="^(json|csv)$")):
        with controller.finalization_lock:
            record = database.get_run(run_id)
            if record is None:
                raise HTTPException(status_code=404, detail="实验不存在")
            if record["status"] != "SUCCEEDED" or record["plan"] is None or record["metrics"] is None:
                raise HTTPException(status_code=409, detail="实验尚无正式成功结果")
            try:
                require_exportable_record(record)
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
            if allow_preview and record['config'].get('execution_mode') in ('planning_preview', 'physical_validation'):
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
        schedule = (preview_schedule(record) if record.get('result_kind') in ('planning_preview', 'physical_validation')
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
    def cesium_page(schedule: str | None = None):
        if schedule and urlsplit(unquote(schedule)).path.startswith('/api/temporary-controls/'):
            raise HTTPException(status_code=409, detail='临时比较结果仅支持 Gantt，不支持 Cesium 回放')
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
        eid = experiments.for_run(run_id)
        schedule = f"/api/runs/{run_id}/visualization/schedule"
        # 页面先读取构建状态，只有显式点击构建/重试才 POST；保留独立旧 orbit GET。
        status_url = f"/api/runs/{run_id}/replay"
        gantt = f"/visualization/gantt/{run_id}"
        return RedirectResponse("/visualization/cesium-page?" + urlencode({
            "run_id":run_id, "schedule":schedule, "replay_status":status_url, "gantt":gantt,
            "experiment_id":eid or ''}))

    @app.get('/visualization/experiments/{experiment_id}/cesium')
    def experiment_cesium(experiment_id: str, run_id: str | None = None):
        record=experiment_call(experiments.detail, experiment_id)
        selected=next((r for r in record['runs'] if r['run_id']==run_id),None)
        selected=selected or next((r for r in record['runs'] if r['status']=='SUCCEEDED' and r['plan']),None)
        if selected and selected['status']=='SUCCEEDED' and selected['plan']:
            return open_cesium(selected['run_id'])
        return RedirectResponse('/?' + urlencode({'experiment_id':experiment_id}) + '#detail-heading')

    @app.get('/api/runs/{run_id}/experiment')
    def run_experiment(run_id: str):
        eid=experiments.for_run(run_id)
        if not eid:
            raise HTTPException(status_code=404,detail='此运行不属于活动实验算法')
        return public_experiment(experiments.detail(eid))

    return app
