"""回放派生服务：把正式结果、独立构建进程和受控资源串成一条可恢复链路。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Settings, resolve_scenario_in, sha256_file
from .storage import Database, compact_json, now
from .worker_process import read_proc, WorkerGroup, reap_worker
from .visualization import propagation_identity
from replay.scene import load_display_scene
from replay.runtime import CONFIG_ID, display_config, source_bundle_sha, validate_document

REPLAY_CONFIG_ID = CONFIG_ID
LEGACY_CONFIG_ID = "geometry-illustration-v2"
BUILDER_VERSION = "integrated-fixed-payload-v1"
ATTITUDE_VERSION = "geometry-pointing-illustration-v1"
GEOMETRY_VERSION = "wgs84-ray-ellipsoid-v1"
RESOURCE_KEYS = frozenset({"orbit_display", "attitude_samples", "segments",
                           "diagnostics", "replay_config"})


class ReplayError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _digest(value: object) -> str:
    return hashlib.sha256(compact_json(value).encode("utf-8")).hexdigest()


def _path_inside(parent: Path, child: Path) -> bool:
    resolved_parent, resolved_child = parent.resolve(), child.resolve()
    return resolved_child == resolved_parent or resolved_parent in resolved_child.parents


def _legacy_config_for_scene(scene: dict) -> dict:
    """登记配置 ID 固定；每颗星的载荷快照由只读场景生成，并进入配置哈希。"""
    sensors = []
    for satellite in scene.get("satellites", []):
        satellite_id = satellite["id"]
        for sensor in satellite.get("observation_capability", {}).get("sensors", []):
            fov = float(sensor["field_of_view_deg"])
            if not 0.0 < fov < 180.0:
                raise ReplayError(409, "REPLAY_CONFIG_INCOMPATIBLE", "场景载荷视场角无效")
            sensors.append({
                "satellite_id": satellite_id, "sensor_id": sensor["sensor_id"],
                "sensor_mount_quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
                "sensor_offset_body_m": [0.0, 0.0, 0.0],
                "fov_interpretation": "square_full_angle_display_assumption",
                "horizontal_full_fov_deg": fov, "vertical_full_fov_deg": fov,
                "source": "scenario.field_of_view_deg_as_display_assumption",
            })
    sensors.sort(key=lambda item: (item["satellite_id"], item["sensor_id"]))
    return {
        "schema_version": 2, "replay_config_id": LEGACY_CONFIG_ID, "config_version": "1",
        "attitude_mode": "body_pointing_fixed_sensor",
        "attitude_source": "geometry_pointing_illustration",
        "idle_attitude_policy": "hold_ecef_v1",
        "initial_display_policy": "first_task_start_attitude",
        "sensors": sensors, "earth_model": "WGS84_ellipsoid",
        "display_sampling_policy": {"orbit_step_s": 300.0,
                                    "include_assignment_boundaries": True},
        "models": [], "thruster_effect_mode": "disabled",
        "quality_warning": "固定安装和视场均为展示假设；目标指向不是调度姿态",
    }



class _ChildProcess:
    """把 Popen 接到已验收的 W2 回收器，复用 pidfd/同 session 保护。"""
    def __init__(self, process):
        self.process = process
        self.pid = process.pid
    @property
    def exitcode(self):
        return self.process.poll()
    def is_alive(self):
        return self.process.poll() is None
    def join(self, timeout=None):
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
    def terminate(self):
        self.process.terminate()
    def kill(self):
        self.process.kill()

class ReplayService:
    def __init__(self, settings: Settings, database: Database):
        self.settings, self.database = settings, database
        self.root = settings.replay_dir
        self.root.mkdir(parents=True, exist_ok=True)
        for source in database.list_data_sources():
            protected = Path(source["root_path"])
            if _path_inside(protected, self.root) or _path_inside(self.root, protected):
                raise RuntimeError("回放缓存目录不能与登记的数据源重叠")
        # 创建/删除共用锁，防止删除正式计划后再插入回放引用。
        self.mutation_lock = threading.RLock()
        self._request_lock = self.mutation_lock
        self._process_lock = threading.Lock()
        self._resource_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eos-replay")
        self._slots = threading.BoundedSemaphore(settings.max_replay_queued + 1)
        self._active: tuple[subprocess.Popen, str] | None = None
        self._closing = False
        self._project = Path(__file__).resolve().parent.parent
        self._builder_sha = source_bundle_sha(self._project)

    def recover(self) -> None:
        """Controller 已持有实例锁；只回收 PID 身份仍匹配的旧构建。"""
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT builder_pid,builder_start_token FROM replay_artifacts WHERE status='BUILDING'"
            ).fetchall()
        for row in rows:
            if row["builder_pid"] and row["builder_start_token"]:
                self._terminate_pid(row["builder_pid"], row["builder_start_token"])
        self.database.recover_replays()

    @staticmethod
    def _identity(pid: int) -> str | None:
        current = read_proc(pid)
        return f"{current.boot_id}:{current.starttime}" if current else None

    @classmethod
    def _terminate_pid(cls, pid: int, token: str) -> None:
        """重启恢复仅处理身份仍匹配的组长；无法识别的历史孤儿不猜测 kill。"""
        if cls._identity(pid) != token:
            return
        group = WorkerGroup(pid)
        try:
            group.refresh()
            group.signal_group(signal.SIGTERM)
            group.signal_members(signal.SIGTERM)
            for _ in range(10):
                if not group.live_members() and cls._identity(pid) != token:
                    return
                time.sleep(0.1)
            group.signal_group(signal.SIGKILL)
            group.signal_members(signal.SIGKILL)
        finally:
            group.close()

    def close(self) -> None:
        with self._request_lock:
            self._closing = True
        # 构建循环每 0.1 秒查看停机；只有构建线程操作它拥有的进程与 pidfd。
        self._executor.shutdown(wait=True, cancel_futures=True)
        self.database.recover_replays()

    def _source(self, run_id: str) -> dict:
        row = self.database.get_replay_source(run_id)
        if row is None:
            raise ReplayError(404, "RUN_NOT_FOUND", "实验不存在")
        if row["status"] != "SUCCEEDED" or not row["plan_json"]:
            raise ReplayError(409, "RUN_NOT_SUCCEEDED", "实验尚无正式成功计划")
        return row

    @staticmethod
    def _known_config(config_id: str) -> None:
        if config_id not in {REPLAY_CONFIG_ID, LEGACY_CONFIG_ID}:
            raise ReplayError(404, "REPLAY_CONFIG_NOT_FOUND", "展示配置未登记")

    def _scenario_path(self, source: dict, run_config: dict) -> Path:
        """在已登记数据源中按正式 SHA 重定位被搬移的场景。"""
        original = Path(run_config["scenario_path"])
        mismatched = False
        if not original.is_symlink() and original.is_file():
            if sha256_file(original) == source["scenario_sha256"]:
                return original
            mismatched = True

        sources = self.database.list_data_sources()
        sources.sort(key=lambda item: item["source_id"] != source["source_id"])
        for item in sources:
            try:
                candidate, digest = resolve_scenario_in(
                    Path(item["root_path"]), source["scenario_id"]
                )
            except (FileNotFoundError, ValueError):
                continue
            if candidate == original:
                continue
            if digest == source["scenario_sha256"]:
                return candidate
            mismatched = True
        if mismatched:
            raise ReplayError(409, "SCENARIO_CHANGED", "正式场景文件哈希已改变")
        raise ReplayError(409, "SCENARIO_UNAVAILABLE", "正式场景文件已不存在")

    def _snapshot(self, source: dict, config_id: str) -> tuple[dict, Path]:
        run_config = json.loads(source["config_json"])
        scene_path = self._scenario_path(source, run_config)
        try:
            scene = load_display_scene(scene_path)
            config = (display_config(scene, self._project, json.loads(source["plan_json"])) if config_id == REPLAY_CONFIG_ID
                      else _legacy_config_for_scene(scene))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ReplayError(409, "REPLAY_CONFIG_INCOMPATIBLE", str(exc)) from exc
        return config, scene_path

    def request(self, run_id: str, config_id: str) -> tuple[dict, int]:
        self._known_config(config_id)
        if self._closing:
            raise ReplayError(503, "REPLAY_SERVICE_STOPPING", "回放服务正在停止")
        source = self._source(run_id)
        config, scene_path = self._snapshot(source, config_id)
        cfg_sha = _digest(config)
        versions = {
            "builder_version": BUILDER_VERSION + "-" + self._builder_sha[:12],
            "propagation_version": propagation_identity(),
            "attitude_version": ATTITUDE_VERSION,
            "geometry_version": GEOMETRY_VERSION,
        }
        cache_key = _digest({
            "run_id": run_id, "scenario_sha256": source["scenario_sha256"],
            "plan_sha256": source["plan_sha256"],
            "replay_config_sha256": cfg_sha, **versions,
        })
        with self._request_lock:
            if self._closing:
                raise ReplayError(503, "REPLAY_SERVICE_STOPPING", "回放服务正在停止")
            self._source(run_id)  # 与删除共用锁后重新核对，拒绝已删除的快照。
            with self.database.connect() as db:
                existing = db.execute(
                    "SELECT * FROM replay_artifacts WHERE cache_key=?", (cache_key,)
                ).fetchone()
            if existing and existing["status"] == "READY":
                record = dict(existing)
                directory = self._ready_directory(record)
                with self._resource_lock:
                    try:
                        if directory is None:
                            raise ValueError("已发布目录丢失")
                        self._validate_manifest(directory, record)
                        return record, 200
                    except (OSError, ValueError, KeyError, TypeError):
                        self.database.invalidate_replay(record["replay_id"],
                                                        "REPLAY_RESOURCE_UNAVAILABLE", "已发布资源缺失或校验失败")
            elif existing and existing["status"] == "BUILDING":
                return dict(existing), 202
            if not self._slots.acquire(blocking=False):
                raise ReplayError(429, "REPLAY_QUEUE_FULL", "独立回放队列已满")
            values = {
                "replay_id": str(uuid.uuid4()), "run_id": run_id,
                "scenario_id": source["scenario_id"],
                "scenario_sha256": source["scenario_sha256"],
                "plan_sha256": source["plan_sha256"],
                "replay_config_id": config_id, "replay_config_version": config["config_version"],
                "replay_config_json": compact_json(config),
                "replay_config_sha256": cfg_sha,
                "algorithm_code_sha": json.loads(source["config_json"]).get("algorithm_code_sha"),
                "provenance_warning": (None if json.loads(source["config_json"]).get("algorithm_code_sha")
                                       else "历史实验未保存可验证的算法代码 SHA"),
                "builder_code_sha": self._builder_sha, **versions,
                "cache_key": cache_key, "status": "BUILDING", "build_attempt": 1,
                "created_at": now(), "updated_at": now(), "build_started_at": now(),
            }
            record, needed = None, False
            try:
                record, needed = self.database.reserve_replay(values)
                if not needed:
                    self._slots.release()
                    return record, 200 if record["status"] == "READY" else 202
                self._executor.submit(self._build, record, source, config, scene_path)
            except BaseException as exc:
                # executor 提交失败也必须结束已占用的 BUILDING 记录。
                if record is not None and needed:
                    self.database.fail_replay(record["replay_id"], record["build_attempt"],
                                              "REPLAY_SUBMIT_FAILED", str(exc))
                self._slots.release()
                raise
            return record, 202

    def current(self, run_id: str, config_id: str | None) -> dict | None:
        self._source(run_id)
        self._known_config(config_id or REPLAY_CONFIG_ID)
        record = self.database.latest_replay(run_id, config_id or REPLAY_CONFIG_ID)
        if record and (record["builder_version"] != BUILDER_VERSION + "-" + self._builder_sha[:12]
                       or record["propagation_version"] != propagation_identity()):
            return None
        return record

    def exact(self, run_id: str, replay_id: str) -> dict:
        self._source(run_id)
        record = self.database.get_replay(run_id, replay_id)
        if record is None:
            raise ReplayError(404, "REPLAY_NOT_FOUND", "回放不存在或不属于该实验")
        return record

    @staticmethod
    def public(run_id: str, record: dict | None, config_id: str | None = None) -> dict:
        if record is None:
            return {"run_id": run_id, "replay_id": None, "replay_status": "NOT_REQUESTED",
                    "replay_config_id": config_id or REPLAY_CONFIG_ID, "build_attempt": 0,
                    "status_url": None, "manifest": None, "error": None}
        replay_id = record["replay_id"]
        manifest = json.loads(record["manifest_json"]) if record["status"] == "READY" else None
        if manifest is not None:
            for key, item in manifest["resources"].items():
                item["url"] = f"/api/runs/{run_id}/replays/{replay_id}/resources/{key}"
        return {
            "run_id": run_id, "replay_id": replay_id, "replay_status": record["status"],
            "replay_config_id": record["replay_config_id"],
            "build_attempt": record["build_attempt"],
            "status_url": f"/api/runs/{run_id}/replays/{replay_id}",
            "manifest": manifest,
            "diagnostics_summary": (json.loads(record["diagnostics_summary_json"])
                                    if record["diagnostics_summary_json"] else None),
            "timings": {"build_runtime_s": record["build_runtime_s"]},
            "error": ({"code": record["error_code"], "message": record["error_message"],
                       "retryable": True} if record["status"] == "FAILED" else None),
        }

    def _ready_directory(self, record: dict) -> Path | None:
        relative = record["artifact_relative_directory"]
        if not relative:
            return None
        expected = self.root / record["replay_id"] / f"build-{record['build_attempt']}"
        if relative != str(Path(record["replay_id"]) / expected.name):
            return None
        if expected.parent.is_symlink() or expected.is_symlink() or not expected.is_dir() or not _path_inside(self.root, expected):
            return None
        return expected

    def resource(self, run_id: str, replay_id: str, key: str) -> tuple[Path, dict]:
        record = self.exact(run_id, replay_id)
        if key not in RESOURCE_KEYS:
            raise ReplayError(404, "REPLAY_RESOURCE_NOT_FOUND", "未知回放资源键")
        if record["status"] != "READY":
            raise ReplayError(409, "REPLAY_NOT_READY", "回放尚未发布")
        directory = self._ready_directory(record)
        manifest = json.loads(record["manifest_json"])
        descriptor = manifest.get("resources", {}).get(key)
        if directory is None or descriptor is None:
            self.database.invalidate_replay(replay_id, "REPLAY_RESOURCE_UNAVAILABLE", "回放目录或清单丢失")
            raise ReplayError(503, "REPLAY_RESOURCE_UNAVAILABLE", "回放资源不可用")
        filename = descriptor["filename"]
        if Path(filename).name != filename:
            raise ReplayError(503, "REPLAY_RESOURCE_UNAVAILABLE", "资源文件名不安全")
        target = directory / filename
        if target.is_symlink() or not target.is_file() or not _path_inside(directory, target):
            self.database.invalidate_replay(replay_id, "REPLAY_RESOURCE_UNAVAILABLE", "回放文件丢失")
            raise ReplayError(503, "REPLAY_RESOURCE_UNAVAILABLE", "回放资源不可用")
        if target.stat().st_size != descriptor["size_bytes"] or sha256_file(target) != descriptor["sha256"]:
            self.database.invalidate_replay(replay_id, "REPLAY_RESOURCE_UNAVAILABLE", "回放文件哈希不符")
            raise ReplayError(503, "REPLAY_RESOURCE_UNAVAILABLE", "回放资源校验失败")
        return target, descriptor

    def read_resource(self, run_id: str, replay_id: str, key: str) -> tuple[bytes, dict]:
        """在删除锁内完成受控读取；响应使用已读入内存的不可变字节。"""
        with self._resource_lock:
            target, descriptor = self.resource(run_id, replay_id, key)
            if descriptor["size_bytes"] > 64 * 1024 * 1024:
                raise ReplayError(503, "REPLAY_RESOURCE_TOO_LARGE", "回放资源超过首版读取上限")
            return target.read_bytes(), descriptor

    def document(self, run_id: str) -> dict:
        record = self.current(run_id, REPLAY_CONFIG_ID)
        if record is None or record["status"] != "READY":
            raise ReplayError(409, "REPLAY_NOT_READY", "请先 POST 申请回放并等待 READY")
        data, _ = self.read_resource(run_id, record["replay_id"], "attitude_samples")
        return json.loads(data)

    def _validate_manifest(self, directory: Path, record: dict) -> tuple[str, str, str]:
        path = directory / "manifest.json"
        content = path.read_bytes()
        manifest = json.loads(content)
        for name in ("replay_id", "run_id", "scenario_id", "scenario_sha256",
                     "plan_sha256", "replay_config_sha256", "cache_key", "builder_code_sha",
                     "builder_version", "propagation_version", "attitude_version", "geometry_version"):
            if manifest.get(name) != record[name]:
                raise ValueError("回放清单身份不匹配：" + name)
        if manifest.get("build_attempt") != record["build_attempt"]:
            raise ValueError("回放清单 attempt 不匹配")
        resources = manifest.get("resources", {})
        if set(resources) != RESOURCE_KEYS:
            raise ValueError("回放资源键不完整")
        for item in resources.values():
            filename = item["filename"]
            if Path(filename).name != filename:
                raise ValueError("回放文件名不安全")
            resource = directory / filename
            if resource.is_symlink() or not resource.is_file() or not _path_inside(directory, resource):
                raise ValueError("回放资源不存在或越界")
            if (resource.stat().st_size > 64*1024*1024 or resource.stat().st_size != item["size_bytes"]
                    or sha256_file(resource) != item["sha256"]):
                raise ValueError("回放资源哈希不一致")
        if record["replay_config_id"] == REPLAY_CONFIG_ID:
            document = json.loads((directory/resources["attitude_samples"]["filename"]).read_bytes())
            validate_document(document, record)
        return content.decode("utf-8"), hashlib.sha256(content).hexdigest(), compact_json(manifest["diagnostics_summary"])

    def _build(self, record: dict, source: dict, config: dict, scene_path: Path) -> None:
        replay_id, attempt = record["replay_id"], record["build_attempt"]
        parent = self.root / replay_id
        temporary = parent / f".build-{attempt}"
        final = parent / f"build-{attempt}"
        started = time.monotonic()
        process = group = None
        try:
            if self._closing:
                raise RuntimeError("回放服务停机，排队构建未启动")
            if parent.is_symlink() or not _path_inside(self.root, parent):
                raise ValueError("回放目录越界")
            parent.mkdir(parents=True, exist_ok=True)
            temporary.mkdir()
            job = {
                "replay_id": replay_id, "run_id": record["run_id"],
                "build_attempt": attempt, "scenario_id": record["scenario_id"],
                "scenario_path": str(scene_path),
                "scenario_sha256": record["scenario_sha256"],
                "plan": json.loads(source["plan_json"]),
                "plan_sha256": record["plan_sha256"],
                "run_config": json.loads(source["config_json"]),
                "replay_config": config, "replay_config_sha256": record["replay_config_sha256"],
                "cache_key": record["cache_key"],
                "algorithm_code_sha": record["algorithm_code_sha"],
                "provenance_warning": record["provenance_warning"],
                "builder_code_sha": record["builder_code_sha"],
                "builder_version": record["builder_version"],
                "propagation_version": record["propagation_version"],
                "attitude_version": record["attitude_version"],
                "geometry_version": record["geometry_version"],
                "orekit_data": str(self._project / "utils" / "orekit-data.zip"),
                "runtime_dir": str(self.settings.runtime_dir),
            }
            job_path = temporary / "job.json"
            job_path.write_text(compact_json(job), encoding="utf-8")
            with (temporary / "build.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "eos_system.replay_builder", "--job", str(job_path)],
                    cwd=self._project, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                group = WorkerGroup(process.pid)
                group.refresh()
                token = self._identity(process.pid)
                if not token or not group.confirmed:
                    raise RuntimeError("无法固定回放构建进程的 Linux 身份")
                with self._process_lock:
                    self._active = (process, token)
                if not self.database.set_replay_process(replay_id, attempt, process.pid, token):
                    raise RuntimeError("构建状态已过期")
                deadline = time.monotonic() + self.settings.replay_build_timeout_s
                while process.poll() is None:
                    group.refresh()
                    if self._closing:
                        raise RuntimeError("回放构建因服务停机中断")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("回放构建超时")
                    time.sleep(0.1)
                cleanup = reap_worker(_ChildProcess(process), group, 0, self.settings.stop_grace_s)
                if cleanup["alive"] or cleanup["live_members"] or cleanup["scan_limited"]:
                    raise RuntimeError("回放后代进程尚未确认回收")
                if process.returncode != 0:
                    tail = (temporary/"build.log").read_text(encoding="utf-8", errors="replace").splitlines()
                    raise RuntimeError("回放构建失败：" + (tail[-1][-220:] if tail else str(process.returncode)))
            if (self._closing or source_bundle_sha(self._project) != record["builder_code_sha"]
                    or propagation_identity() != record["propagation_version"]):
                raise RuntimeError("构建期间服务停止或源码/传播环境发生变化")
            if sha256_file(scene_path) != record["scenario_sha256"]:
                raise RuntimeError("构建期间正式场景被修改")
            manifest_json, manifest_sha, summary = self._validate_manifest(temporary, record)
            # 作业含服务器路径和完整计划，不作为可发布资源保留。
            job_path.unlink()
            (temporary/"build.log").unlink()
            os.replace(temporary, final)
            if not self.database.publish_replay(
                replay_id, attempt, str(Path(replay_id)/final.name), manifest_json, manifest_sha,
                summary, time.monotonic()-started):
                raise RuntimeError("过期构建尝试被拒绝发布")
        except BaseException as exc:
            self.database.fail_replay(replay_id, attempt, type(exc).__name__, str(exc))
        finally:
            try:
                if process is not None and group is not None:
                    try:
                        reap_worker(_ChildProcess(process), group, 0, self.settings.stop_grace_s)
                    finally:
                        group.close()
                elif process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            finally:
                # 即使回收/清理遇到异常，也必须归还排队名额，防止队列永久耗尽。
                with self._process_lock:
                    self._active = None
                try:
                    if temporary.exists() and not temporary.is_symlink() and _path_inside(self.root, temporary):
                        shutil.rmtree(temporary)
                finally:
                    self._slots.release()

    def cleanup_deleted(self, replay_ids: list[str]) -> list[str]:
        """仅删除已从数据库解绑的 UUID 目录；正式场景和导出路径不在此树下。"""
        warnings = []
        for replay_id in replay_ids:
            try:
                if str(uuid.UUID(replay_id)) != replay_id:
                    raise ValueError("回放 ID 无效")
                directory = self.root / replay_id
                if directory.is_symlink() or not _path_inside(self.root, directory):
                    raise ValueError("回放目录越界")
                with self._resource_lock:
                    if directory.exists():
                        shutil.rmtree(directory)
            except (OSError, ValueError) as exc:
                warnings.append(f"回放缓存 {replay_id} 未清理：{exc}")
        return warnings
