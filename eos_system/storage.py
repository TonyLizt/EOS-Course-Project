"""SQLite 正式结果库。

每次调用独立开连接；写操作显式使用 IMMEDIATE 事务，防止取消与成功提交交叉。
"""

from __future__ import annotations

from utils.continuous_exposure import (CertificationReceipt, CertifiedRecord, _ISSUER, ContinuousCertificationError,
    ExposureStatus, validate_certification, certification_context, check_deadline)
from utils.certification_identity import trusted_context

import hashlib
import json
import sqlite3
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .contracts import RunConfig
from .planning_preview import PreviewReceipt, PreviewRecord, PhysicalValidatedRecord, validate_preview


TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL DEFAULT 'runtime',
  scenario_id TEXT NOT NULL,
  scenario_sha256 TEXT NOT NULL,
  algorithm_id TEXT NOT NULL,
  algorithm_version TEXT NOT NULL,
  output_profile_id TEXT NOT NULL DEFAULT 'download',
  config_json TEXT NOT NULL,
  config_sha256 TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','VERIFYING','SUCCEEDED','FAILED','CANCELLED','TIMED_OUT')),
  current_attempt INTEGER,
  cancel_requested_at TEXT,
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  queued_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS run_attempts (
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
  worker_pid INTEGER,
  worker_start_token TEXT,
  last_seq INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  ended_at TEXT,
  outcome TEXT,
  algorithm_runtime_s REAL,
  verification_runtime_s REAL,
  exit_code INTEGER,
  error_code TEXT,
  PRIMARY KEY (run_id, attempt_no)
);
CREATE TABLE IF NOT EXISTS run_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  attempt_no INTEGER,
  source TEXT NOT NULL,
  source_seq INTEGER,
  event_type TEXT NOT NULL,
  payload_json TEXT,
  recorded_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_worker_event ON run_events(run_id,attempt_no,source,source_seq)
  WHERE source_seq IS NOT NULL;
CREATE TABLE IF NOT EXISTS plans (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
  attempt_no INTEGER NOT NULL,
  scenario_id TEXT NOT NULL,
  plan_schema_version INTEGER NOT NULL DEFAULT 1,
  plan_json TEXT NOT NULL,
  plan_sha256 TEXT NOT NULL,
  verified_at TEXT NOT NULL,
  FOREIGN KEY (run_id, attempt_no) REFERENCES run_attempts(run_id,attempt_no)
);
CREATE TABLE IF NOT EXISTS assignments (
  run_id TEXT NOT NULL REFERENCES plans(run_id),
  ordinal INTEGER NOT NULL,
  task_id TEXT NOT NULL,
  satellite_id TEXT NOT NULL,
  sensor_id TEXT NOT NULL,
  sat_start_time TEXT NOT NULL,
  sat_end_time TEXT NOT NULL,
  ground_station_id TEXT,
  gs_start_time TEXT,
  gs_end_time TEXT,
  assignment_json TEXT NOT NULL,
  PRIMARY KEY (run_id,ordinal),
  UNIQUE (run_id,task_id)
);
CREATE TABLE IF NOT EXISTS metrics (
  run_id TEXT PRIMARY KEY REFERENCES plans(run_id),
  completed_tasks INTEGER NOT NULL CHECK (completed_tasks >= 0),
  total_tasks INTEGER NOT NULL CHECK (total_tasks >= completed_tasks),
  TP REAL NOT NULL,
  TCR REAL NOT NULL CHECK (TCR >= 0 AND TCR <= 1),
  BD REAL NOT NULL,
  TM REAL NOT NULL,
  RT REAL NOT NULL CHECK (RT >= 0),
  RV REAL,
  mip_gap REAL,
  metric_schema_version INTEGER NOT NULL DEFAULT 1,
  computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exports (
  export_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  format TEXT NOT NULL CHECK (format IN ('json','csv')),
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED','FAILED')),
  artifact_sha256 TEXT,
  artifact_path TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_sources (
  source_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  root_path TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS output_profiles (
  profile_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('download','directory')),
  root_path TEXT UNIQUE,
  created_at TEXT NOT NULL,
  CHECK ((kind='download' AND root_path IS NULL) OR (kind='directory' AND root_path IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_runs_status_time ON runs(status,created_at);
CREATE INDEX IF NOT EXISTS idx_runs_scenario_algorithm ON runs(scenario_id,algorithm_id,created_at);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id,event_id);
CREATE INDEX IF NOT EXISTS idx_assignments_sat ON assignments(run_id,satellite_id,sat_start_time);
"""


MIGRATION_1_TO_2 = """
ALTER TABLE runs ADD COLUMN source_id TEXT NOT NULL DEFAULT 'runtime';
ALTER TABLE runs ADD COLUMN output_profile_id TEXT NOT NULL DEFAULT 'download';
ALTER TABLE exports ADD COLUMN artifact_path TEXT;
ALTER TABLE exports ADD COLUMN error_message TEXT;
CREATE TABLE IF NOT EXISTS data_sources (
  source_id TEXT PRIMARY KEY, name TEXT NOT NULL, root_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS output_profiles (
  profile_id TEXT PRIMARY KEY, name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('download','directory')),
  root_path TEXT UNIQUE, created_at TEXT NOT NULL,
  CHECK ((kind='download' AND root_path IS NULL) OR (kind='directory' AND root_path IS NOT NULL))
);
"""


REPLAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_artifacts (
  replay_id TEXT PRIMARY KEY NOT NULL,
  run_id TEXT NOT NULL REFERENCES plans(run_id) ON DELETE RESTRICT,
  scenario_id TEXT NOT NULL,
  scenario_sha256 TEXT NOT NULL CHECK(length(scenario_sha256)=64),
  plan_sha256 TEXT NOT NULL CHECK(length(plan_sha256)=64),
  replay_config_id TEXT NOT NULL,
  replay_config_version TEXT NOT NULL,
  replay_config_json TEXT NOT NULL,
  replay_config_sha256 TEXT NOT NULL CHECK(length(replay_config_sha256)=64),
  algorithm_code_sha TEXT,
  provenance_warning TEXT,
  builder_code_sha TEXT NOT NULL,
  builder_version TEXT NOT NULL,
  propagation_version TEXT NOT NULL,
  attitude_version TEXT NOT NULL,
  geometry_version TEXT NOT NULL,
  cache_key TEXT NOT NULL UNIQUE CHECK(length(cache_key)=64),
  status TEXT NOT NULL CHECK(status IN ('BUILDING','READY','FAILED')),
  build_attempt INTEGER NOT NULL CHECK(build_attempt>=1),
  builder_pid INTEGER,
  builder_start_token TEXT,
  last_seq INTEGER NOT NULL DEFAULT 0 CHECK(last_seq>=0),
  artifact_relative_directory TEXT,
  manifest_json TEXT,
  manifest_sha256 TEXT,
  diagnostics_summary_json TEXT,
  build_runtime_s REAL CHECK(build_runtime_s IS NULL OR build_runtime_s>=0),
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  build_started_at TEXT,
  build_finished_at TEXT,
  CHECK(status!='READY' OR (
    artifact_relative_directory IS NOT NULL AND manifest_json IS NOT NULL
    AND manifest_sha256 IS NOT NULL AND build_runtime_s IS NOT NULL
    AND build_finished_at IS NOT NULL AND error_code IS NULL
  )),
  CHECK(status!='FAILED' OR (error_code IS NOT NULL AND build_finished_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_replay_run_created ON replay_artifacts(run_id,created_at);
CREATE INDEX IF NOT EXISTS idx_replay_status_updated ON replay_artifacts(status,updated_at);
"""


EXPERIMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
  experiment_id TEXT PRIMARY KEY,
  common_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  legacy INTEGER NOT NULL DEFAULT 0,
  idempotency_key TEXT UNIQUE,
  request_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS experiment_runs (
  experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
  algorithm_id TEXT NOT NULL,
  removed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_active_algorithm
  ON experiment_runs(experiment_id,algorithm_id) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_experiment_created ON experiments(created_at);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        try:
            self._certification_context = trusted_context()
            self._certification_context_error = None
        except (OSError, ValueError) as exc:
            self._certification_context = None
            self._certification_context_error = str(exc)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4):
                raise RuntimeError(f"数据库版本 {version} 比当前程序新")
            if version in (1, 2, 3):
                backup = path.with_name(path.name + '.pre-v4.bak')
                try:
                    backup.open('xb').close()
                except FileExistsError:
                    fd, filename = tempfile.mkstemp(prefix=path.name+'.pre-v4.',suffix='.bak',dir=path.parent)
                    os.close(fd); backup = Path(filename)
                with sqlite3.connect(backup) as destination:
                    connection.backup(destination)
            if version in (1, 2):
                # 在线备份会同时读取 WAL 中已提交的页；避免直接复制活跃数据库文件。
                backup = path.with_name(path.name + ".pre-v3.bak")
                if not backup.exists():
                    with sqlite3.connect(backup) as destination:
                        connection.backup(destination)
            if version == 0:
                connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + REPLAY_SCHEMA + "\nPRAGMA user_version=3;\nCOMMIT;")
            elif version == 1:
                # 仅向前增加表和列，保留 v0.1 正式实验与导出记录。
                connection.executescript("BEGIN IMMEDIATE;\n" + MIGRATION_1_TO_2 + REPLAY_SCHEMA + "\nPRAGMA user_version=3;\nCOMMIT;")
            elif version == 2:
                # 回放是正式结果的派生缓存；迁移只增加表和索引。
                connection.executescript("BEGIN IMMEDIATE;\n" + REPLAY_SCHEMA + "\nPRAGMA user_version=3;\nCOMMIT;")
            if version < 4:
                connection.executescript('BEGIN IMMEDIATE;\n' + EXPERIMENT_SCHEMA + '\nPRAGMA user_version=4;\nCOMMIT;')

    def expected_certification_context(self):
        if self._certification_context_error:
            raise ContinuousCertificationError(ExposureStatus.ERROR,
                "CERTIFICATION_STARTUP_IDENTITY_INVALID: " + self._certification_context_error)
        return certification_context(self._certification_context)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def write(self, *, before_commit=None):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                if before_commit is not None:
                    before_commit()
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def ensure_defaults(self, scenario_dir: Path, runtime_dir: Path) -> None:
        """首次启动登记默认位置；环境变量变化后同步默认项的真实路径。"""
        artifacts = runtime_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        with self.write() as db:
            db.execute("INSERT INTO data_sources(source_id,name,root_path,created_at) VALUES ('runtime','运行目录场景',?,?) "
                       "ON CONFLICT(source_id) DO UPDATE SET root_path=excluded.root_path",
                       (str(scenario_dir.resolve()), now()))
            db.execute("INSERT OR IGNORE INTO output_profiles(profile_id,name,kind,root_path,created_at) "
                       "VALUES ('download','仅浏览器下载','download',NULL,?)", (now(),))
            db.execute("INSERT INTO output_profiles(profile_id,name,kind,root_path,created_at) "
                       "VALUES ('runtime-files','WSL 运行目录文件','directory',?,?) "
                       "ON CONFLICT(profile_id) DO UPDATE SET root_path=excluded.root_path",
                       (str(artifacts.resolve()), now()))

    def ensure_catalog_source(self, source_id: str, name: str, root: Path) -> None:
        """内置场景随仓库定位；重复启动/已有手工登记均不产生同路径重复项。"""
        with self.write() as db:
            existing = db.execute("SELECT source_id FROM data_sources WHERE root_path=?",
                                  (str(root),)).fetchone()
            if existing:
                return
            db.execute(
                "INSERT INTO data_sources(source_id,name,root_path,created_at) VALUES (?,?,?,?) "
                "ON CONFLICT(source_id) DO UPDATE SET name=excluded.name,root_path=excluded.root_path",
                (source_id, name, str(root), now()),
            )

    def list_data_sources(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM data_sources ORDER BY created_at,source_id")]

    def get_data_source(self, source_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM data_sources WHERE source_id=?", (source_id,)).fetchone()
            return dict(row) if row else None

    def add_data_source(self, source_id: str, name: str, root: Path) -> dict:
        with self.write() as db:
            db.execute("INSERT INTO data_sources(source_id,name,root_path,created_at) VALUES (?,?,?,?)",
                       (source_id, name, str(root), now()))
        return self.get_data_source(source_id)

    def list_output_profiles(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM output_profiles ORDER BY created_at,profile_id")]

    def get_output_profile(self, profile_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM output_profiles WHERE profile_id=?", (profile_id,)).fetchone()
            return dict(row) if row else None

    def add_output_profile(self, profile_id: str, name: str, root: Path) -> dict:
        with self.write() as db:
            db.execute("INSERT INTO output_profiles(profile_id,name,kind,root_path,created_at) VALUES (?,?,'directory',?,?)",
                       (profile_id, name, str(root), now()))
        return self.get_output_profile(profile_id)

    def enqueue(self, config: RunConfig, max_queued: int, idempotency_key: str | None = None) -> tuple[str, bool]:
        config_json = compact_json(config.model_dump())
        config_sha = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        with self.write() as db:
            if idempotency_key:
                previous = db.execute("SELECT run_id,config_json FROM runs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if previous:
                    # run_id/时间是服务端生成值；比较用户提交部分而非这些值。
                    current = json.loads(previous["config_json"])
                    incoming = config.model_dump()
                    current.setdefault('execution_mode', 'formal')
                    current.setdefault('schedule_model', 'completion_first')
                    for key in ("run_id", "created_at"):
                        current.pop(key, None)
                        incoming.pop(key, None)
                    if current != incoming:
                        raise ValueError("相同 Idempotency-Key 对应不同实验配置")
                    return previous["run_id"], False
            count = db.execute("SELECT COUNT(*) FROM runs WHERE status='QUEUED'").fetchone()[0]
            if count >= max_queued:
                raise OverflowError("实验队列已满")
            db.execute(
                "INSERT INTO runs(run_id,source_id,scenario_id,scenario_sha256,algorithm_id,algorithm_version,output_profile_id,config_json,config_sha256,idempotency_key,status,created_at,updated_at,queued_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (config.run_id, config.source_id, config.scenario_id, config.scenario_sha256, config.algorithm_id,
                 config.algorithm_version, config.output_profile_id, config_json, config_sha, idempotency_key,
                 "QUEUED", config.created_at, config.created_at, config.created_at),
            )
            self._event(db, config.run_id, None, "controller", None, "QUEUED", None)
        return config.run_id, True

    def _event(self, db, run_id: str, attempt: int | None, source: str, seq: int | None, kind: str, payload: dict | None):
        db.execute(
            "INSERT INTO run_events(run_id,attempt_no,source,source_seq,event_type,payload_json,recorded_at) VALUES (?,?,?,?,?,?,?)",
            (run_id, attempt, source, seq, kind, compact_json(payload) if payload is not None else None, now()),
        )

    def record_system_event(self, run_id: str, attempt: int | None, kind: str, payload: dict | None = None) -> None:
        if kind in {"CONTINUOUS_CERTIFIED", "PREVIEW_VALIDATED"}:
            raise ValueError("certification events are reserved for finish_success")
        """记录正式状态之外的诊断事件，例如可选文件导出失败。"""
        with self.write() as db:
            self._event(db, run_id, attempt, "controller", None, kind, payload)

    def record_attempt_exit(self, run_id: str, attempt: int, exit_code: int | None, diagnostics: dict) -> None:
        """在原有 attempt 列和事件表中记录直接 Worker 的退出与回收。"""
        with self.write() as db:
            row = db.execute("SELECT 1 FROM run_attempts WHERE run_id=? AND attempt_no=?",
                             (run_id, attempt)).fetchone()
            if row is None:
                return
            db.execute("UPDATE run_attempts SET exit_code=? WHERE run_id=? AND attempt_no=?",
                       (exit_code, run_id, attempt))
            self._event(db, run_id, attempt, "controller", None, "WORKER_REAP",
                        {"exit_code": exit_code, **diagnostics})

    def next_queued(self) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE status='QUEUED' ORDER BY queued_at,run_id LIMIT 1").fetchone()
            return dict(row) if row else None

    def start_attempt(self, run_id: str) -> tuple[int, dict] | None:
        with self.write() as db:
            row = db.execute("SELECT status,current_attempt,config_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row or row["status"] != "QUEUED":
                return None
            attempt = (row["current_attempt"] or 0) + 1
            db.execute("UPDATE runs SET status='RUNNING',current_attempt=?,updated_at=? WHERE run_id=?", (attempt, now(), run_id))
            db.execute("INSERT INTO run_attempts(run_id,attempt_no,started_at) VALUES (?,?,?)", (run_id, attempt, now()))
            self._event(db, run_id, attempt, "controller", None, "RUNNING", None)
            return attempt, json.loads(row["config_json"])

    def record_worker_event(self, message: dict) -> bool:
        run_id, attempt, seq = message["run_id"], message["attempt"], message["seq"]
        with self.write() as db:
            row = db.execute("SELECT status,current_attempt,cancel_requested_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
            last = db.execute("SELECT last_seq FROM run_attempts WHERE run_id=? AND attempt_no=?", (run_id, attempt)).fetchone()
            if not row or row["current_attempt"] != attempt or row["status"] in TERMINAL or not last or seq <= last["last_seq"]:
                return False
            db.execute("UPDATE run_attempts SET last_seq=?,worker_pid=COALESCE(?,worker_pid),worker_start_token=COALESCE(?,worker_start_token) WHERE run_id=? AND attempt_no=?",
                       (seq, message["payload"].get("worker_pid"), message["payload"].get("worker_start_token"), run_id, attempt))
            payload = message["payload"] if message["kind"] != "candidate_result" else {"algorithm_runtime_s": message["payload"].get("algorithm_runtime_s")}
            if message["kind"] == "candidate_result":
                diagnostics = message["payload"].get("plan", {}).get("solver_diagnostics")
                if isinstance(diagnostics, dict):
                    payload["untrusted_solver_diagnostics"] = diagnostics
            self._event(db, run_id, attempt, "worker", seq, message["kind"], payload)
            return True

    def set_verifying(self, run_id: str, attempt: int) -> bool:
        with self.write() as db:
            result = db.execute("UPDATE runs SET status='VERIFYING',updated_at=? WHERE run_id=? AND current_attempt=? AND status='RUNNING' AND cancel_requested_at IS NULL",
                                (now(), run_id, attempt))
            if result.rowcount:
                self._event(db, run_id, attempt, "controller", None, "VERIFYING", None)
            return bool(result.rowcount)

    def finish_success(self, run_id: str, attempt: int, plan: dict, metrics: dict, verify_s: float,
                       *, certification: CertificationReceipt | None = None, deadline: float | None = None) -> bool:
        plan_json = compact_json(plan)
        guard = None
        def before_commit():
            if guard is not None:
                guard()
        with self.write(before_commit=before_commit) as db:
            row = db.execute("SELECT status,cancel_requested_at,scenario_id,config_json FROM runs WHERE run_id=? AND current_attempt=?", (run_id, attempt)).fetchone()
            if not row or row["status"] != "VERIFYING" or row["cancel_requested_at"] is not None:
                return False
            if not isinstance(certification, CertificationReceipt):
                raise ContinuousCertificationError(ExposureStatus.INCONCLUSIVE, "CERTIFICATION_REQUIRED")
            config = json.loads(row["config_json"])
            evidence = validate_certification(certification.evidence(), run_id=run_id,
                                scenario_sha=config["scenario_sha256"], plan=plan, context=self.expected_certification_context())
            effective_deadline = evidence["deadline_monotonic"] if deadline is None else min(deadline, evidence["deadline_monotonic"])
            def guard():
                check_deadline(effective_deadline)
                self.expected_certification_context()
                check_deadline(effective_deadline)
            guard()
            self._event(db, run_id, attempt, "controller", None, "CONTINUOUS_CERTIFIED", evidence)
            db.execute("INSERT INTO plans(run_id,attempt_no,scenario_id,plan_json,plan_sha256,verified_at) VALUES (?,?,?,?,?,?)",
                       (run_id, attempt, plan["scenario_id"], plan_json, hashlib.sha256(plan_json.encode()).hexdigest(), now()))
            for index, item in enumerate(plan["assignments"]):
                db.execute("INSERT INTO assignments(run_id,ordinal,task_id,satellite_id,sensor_id,sat_start_time,sat_end_time,ground_station_id,gs_start_time,gs_end_time,assignment_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (run_id, index, item["task_id"], item["satellite_id"], item["sensor_id"], item["sat_start_time"], item["sat_end_time"],
                            item.get("ground_station_id"), item.get("gs_start_time"), item.get("gs_end_time"), compact_json(item)))
            db.execute("INSERT INTO metrics(run_id,completed_tasks,total_tasks,TP,TCR,BD,TM,RT,RV,mip_gap,computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (run_id, metrics["completed_tasks"], metrics["total_tasks"], metrics["task_profit"], metrics["task_completion_rate"],
                        metrics["balance_degree"], metrics["timeliness_metric"], metrics["runtime_efficiency"], metrics["robustness_variance"], metrics["mip_gap"], now()))
            guard()
            db.execute("UPDATE run_attempts SET outcome='SUCCEEDED',ended_at=?,algorithm_runtime_s=?,verification_runtime_s=? WHERE run_id=? AND attempt_no=?",
                       (now(), metrics["runtime_efficiency"], verify_s, run_id, attempt))
            db.execute("UPDATE runs SET status='SUCCEEDED',updated_at=?,finished_at=? WHERE run_id=?", (now(), now(), run_id))
            self._event(db, run_id, attempt, "controller", None, "SUCCEEDED", {"completed_tasks": metrics["completed_tasks"]})
            return True

    def finish_failure(self, run_id: str, attempt: int | None, status: str, code: str, message: str) -> None:
        if status not in {"FAILED", "CANCELLED", "TIMED_OUT"}:
            raise ValueError("非法终态")
        with self.write() as db:
            row = db.execute("SELECT status,current_attempt,cancel_requested_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row or row["status"] in TERMINAL or (attempt is not None and row["current_attempt"] != attempt):
                return
            # BEGIN IMMEDIATE serializes this arbitration with request_cancel.
            # Preserve previously decided algorithm timeout and controller stop.
            if (row["status"] == "VERIFYING" and row["cancel_requested_at"] is not None
                    and status == "FAILED" and code not in {"CONTROLLER_STOP", "CONTROLLER_RESTART"}):
                self._event(db, run_id, attempt, "controller", None, "CERTIFICATION_FAILURE_AFTER_CANCEL",
                            {"code": code, "message": message[:300], "requested_status": status})
                status, code, message = "CANCELLED", "CANCELLED_DURING_VERIFY", "Accepted cancellation precedes certification failure"
            db.execute("UPDATE runs SET status=?,error_code=?,error_message=?,updated_at=?,finished_at=? WHERE run_id=?",
                       (status, code, message[:300], now(), now(), run_id))
            if attempt is not None:
                db.execute("UPDATE run_attempts SET outcome=?,error_code=?,ended_at=? WHERE run_id=? AND attempt_no=?",
                           (status, code, now(), run_id, attempt))
            self._event(db, run_id, attempt, "controller", None, status, {"code": code})

    def finish_preview(self, run_id, attempt, plan, metrics, verify_s, *, receipt, deadline):
        """A separate commit path; never issues CONTINUOUS_CERTIFIED or a formal receipt."""
        def guard():
            check_deadline(deadline)
        with self.write(before_commit=guard) as db:
            row = db.execute('SELECT status,cancel_requested_at,config_json FROM runs WHERE run_id=? AND current_attempt=?',
                             (run_id, attempt)).fetchone()
            if not row or row['status'] != 'VERIFYING' or row['cancel_requested_at']:
                return False
            if not isinstance(receipt, PreviewReceipt):
                raise ValueError('Controller preview receipt required')
            evidence = validate_preview(receipt.evidence(), json.loads(row['config_json']), plan)
            guard()
            plan_json = compact_json(plan)
            db.execute('INSERT INTO plans(run_id,attempt_no,scenario_id,plan_json,plan_sha256,verified_at) VALUES (?,?,?,?,?,?)',
                       (run_id, attempt, plan['scenario_id'], plan_json, hashlib.sha256(plan_json.encode()).hexdigest(), now()))
            for index, item in enumerate(plan['assignments']):
                db.execute('INSERT INTO assignments(run_id,ordinal,task_id,satellite_id,sensor_id,sat_start_time,sat_end_time,ground_station_id,gs_start_time,gs_end_time,assignment_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (run_id,index,item['task_id'],item['satellite_id'],item['sensor_id'],item['sat_start_time'],item['sat_end_time'],
                     item.get('ground_station_id'),item.get('gs_start_time'),item.get('gs_end_time'),compact_json(item)))
            db.execute('INSERT INTO metrics(run_id,completed_tasks,total_tasks,TP,TCR,BD,TM,RT,RV,mip_gap,computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (run_id,metrics['completed_tasks'],metrics['total_tasks'],metrics['task_profit'],metrics['task_completion_rate'],
                 metrics['balance_degree'],metrics['timeliness_metric'],metrics['runtime_efficiency'],metrics['robustness_variance'],metrics['mip_gap'],now()))
            kind = json.loads(row['config_json'])['execution_mode']
            self._event(db, run_id, attempt, 'controller', None,
                'PHYSICS_VALIDATED' if kind == 'physical_validation' else 'PREVIEW_VALIDATED', evidence)
            db.execute("UPDATE run_attempts SET outcome='SUCCEEDED',ended_at=?,algorithm_runtime_s=?,verification_runtime_s=? WHERE run_id=? AND attempt_no=?",
                       (now(),metrics['runtime_efficiency'],verify_s,run_id,attempt))
            db.execute("UPDATE runs SET status='SUCCEEDED',updated_at=?,finished_at=? WHERE run_id=?", (now(),now(),run_id))
            self._event(db, run_id, attempt, 'controller', None, 'SUCCEEDED', {'result_kind':kind})
            return True

    def request_cancel(self, run_id: str) -> tuple[str, bool] | None:
        with self.write() as db:
            return self.request_cancel_in(db, run_id)

    def request_cancel_in(self, db, run_id: str):
        """同一事务内移除实验成员并取消，仍沿用原 Controller 协议。"""
        row = db.execute("SELECT status,current_attempt,cancel_requested_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        if row["status"] in TERMINAL:
            return row["status"], False
        if row["status"] == "QUEUED":
            db.execute("UPDATE runs SET status='CANCELLED',cancel_requested_at=?,finished_at=?,updated_at=? WHERE run_id=?",
                       (now(), now(), now(), run_id))
            self._event(db, run_id, None, "api", None, "CANCELLED", None)
            return "CANCELLED", True
        if row["cancel_requested_at"] is None:
            db.execute("UPDATE runs SET cancel_requested_at=?,updated_at=? WHERE run_id=?", (now(), now(), run_id))
            self._event(db, run_id, row["current_attempt"], "api", None, "CANCEL_REQUESTED", None)
        return row["status"], True

    def get_status(self, run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT status,cancel_requested_at,current_attempt FROM runs WHERE run_id=?", (run_id,)).fetchone()
            return dict(row) if row else None

    def recover_interrupted(self) -> None:
        """启动后保留排队任务；旧运行不自动续算，避免重复结果。"""
        with self.connect() as db:
            rows = db.execute("SELECT run_id,current_attempt FROM runs WHERE status IN ('RUNNING','VERIFYING')").fetchall()
        for row in rows:
            self.finish_failure(row["run_id"], row["current_attempt"], "FAILED", "CONTROLLER_RESTART", "Controller 重启，旧 Worker 结果已作废")

    def get_run(self, run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return None
            plan = db.execute("SELECT plan_json,plan_sha256 FROM plans WHERE run_id=?", (run_id,)).fetchone()
            metrics = db.execute("SELECT * FROM metrics WHERE run_id=?", (run_id,)).fetchone()
            attempts = db.execute("SELECT attempt_no,worker_pid,started_at,ended_at,outcome,algorithm_runtime_s,verification_runtime_s,exit_code FROM run_attempts WHERE run_id=? ORDER BY attempt_no", (run_id,)).fetchall()
            events = db.execute("SELECT event_id,attempt_no,source,event_type,payload_json,recorded_at FROM run_events WHERE run_id=? ORDER BY event_id", (run_id,)).fetchall()
            exports = db.execute("SELECT export_id,format,status,artifact_sha256,artifact_path,error_message,created_at FROM exports WHERE run_id=? ORDER BY export_id", (run_id,)).fetchall()
            result = {
                "run_id": run_id, "status": row["status"], "config": json.loads(row["config_json"]),
                "attempt": row["current_attempt"], "cancel_requested": row["cancel_requested_at"] is not None,
                "created_at": row["created_at"], "finished_at": row["finished_at"],
                "error": {"code": row["error_code"], "message": row["error_message"]} if row["error_code"] else None,
                "plan": json.loads(plan["plan_json"]) if plan else None,
                "metrics": dict(metrics) if metrics else None,
                "attempts": [dict(item) for item in attempts],
                "events": [{
                    "event_id": item["event_id"], "attempt_no": item["attempt_no"],
                    "source": item["source"], "event_type": item["event_type"],
                    "recorded_at": item["recorded_at"],
                    "payload": json.loads(item["payload_json"]) if item["payload_json"] else None,
                } for item in events],
                "exports": [dict(item) for item in exports],
            }
            evidence = next((event["payload"] for event in reversed(result["events"])
                             if event["event_type"] == "CONTINUOUS_CERTIFIED"
                             and event["source"] == "controller"), None)
            if result['config'].get('execution_mode') in ('planning_preview', 'physical_validation'):
                preview = next((event['payload'] for event in reversed(result['events'])
                    if event['event_type'] == ('PHYSICS_VALIDATED' if result['config']['execution_mode'] == 'physical_validation' else 'PREVIEW_VALIDATED') and event['source'] == 'controller'), None)
                result['result_kind'] = result['config']['execution_mode']
                result['continuous_certification'] = {'status':'NOT_CERTIFIED', 'reason':'SAMPLED_PHYSICS_ONLY' if result['result_kind'] == 'physical_validation' else 'PLANNING_PREVIEW_ONLY'}
                try:
                    if result['status'] != 'SUCCEEDED' or not plan or hashlib.sha256(plan['plan_json'].encode()).hexdigest() != plan['plan_sha256']:
                        raise ValueError('no valid preview plan')
                    result['preview_validation'] = validate_preview(preview, result['config'], result['plan'])
                    return (PhysicalValidatedRecord if result['result_kind'] == 'physical_validation' else PreviewRecord)(result)
                except (ValueError, TypeError, KeyError):
                    result['plan'] = None
                    return result
            result['result_kind'] = 'formal'
            try:
                if result["status"] != "SUCCEEDED" or result["plan"] is None:
                    raise ValueError("no certified successful plan")
                if hashlib.sha256(plan["plan_json"].encode()).hexdigest() != plan["plan_sha256"]:
                    raise ValueError("stored plan bytes do not match stored SHA")
                validate_certification(evidence, run_id=run_id,
                    scenario_sha=result["config"]["scenario_sha256"], plan=result["plan"],
                    context=self.expected_certification_context())
                result["continuous_certification"] = evidence
                result = CertifiedRecord(result)
                result.certification_context = self.expected_certification_context()
                result.certification_receipt = CertificationReceipt(json.dumps(evidence,sort_keys=True), _ISSUER)
            except (ValueError, TypeError, KeyError, OSError):
                # Keep historical status/events, but never expose its plan as certified.
                result["plan"] = None
                result["continuous_certification"] = {"status":"INCONCLUSIVE",
                    "reason":"MISSING_STALE_OR_MISMATCHED_CERTIFICATION"}
            return result

    def list_runs(self, limit: int = 20, offset: int = 0) -> dict:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            rows = db.execute("SELECT r.run_id,r.source_id,r.scenario_id,r.algorithm_id,r.output_profile_id,r.status,r.created_at,r.finished_at,m.TCR,m.completed_tasks FROM runs r LEFT JOIN metrics m ON r.run_id=m.run_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            items = [dict(row) for row in rows]
        for item in items:
            detail = self.get_run(item["run_id"])
            item['result_kind'] = detail.get('result_kind', 'formal') if detail else 'formal'
            item['schedule_model'] = detail['config'].get('schedule_model', 'legacy_unspecified') if detail else 'legacy_unspecified'
            item['has_plan'] = bool(detail and detail.get('plan') is not None)
            item["continuous_certification_status"] = detail["continuous_certification"]["status"] if detail else "INCONCLUSIVE"
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def get_replay_source(self, run_id: str) -> dict | None:
        """读取正式提交的计划身份；构建进程只接收这个快照，不接触 SQLite。"""
        with self.connect() as db:
            row = db.execute(
                "SELECT r.run_id,r.status,r.source_id,r.scenario_id,r.scenario_sha256,r.algorithm_version,"
                "r.config_json,p.plan_json,p.plan_sha256 FROM runs r "
                "LEFT JOIN plans p ON p.run_id=r.run_id WHERE r.run_id=?", (run_id,)
            ).fetchone()
            result = dict(row) if row else None
        if result is not None:
            verified = self.get_run(run_id)
            if verified is None or verified["plan"] is None:
                result["plan_json"] = None
                result["plan_sha256"] = None
        return result

    def get_replay(self, run_id: str, replay_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM replay_artifacts WHERE run_id=? AND replay_id=?",
                             (run_id, replay_id)).fetchone()
            return dict(row) if row else None

    def latest_replay(self, run_id: str, config_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM replay_artifacts WHERE run_id=? AND replay_config_id=? "
                "ORDER BY created_at DESC LIMIT 1", (run_id, config_id)
            ).fetchone()
            return dict(row) if row else None

    def reserve_replay(self, values: dict) -> tuple[dict, bool]:
        """唯一缓存键串行去重；bool 表示本请求需要启动新的构建 attempt。"""
        with self.write() as db:
            row = db.execute("SELECT * FROM replay_artifacts WHERE cache_key=?",
                             (values["cache_key"],)).fetchone()
            if row:
                if row["status"] != "FAILED":
                    return dict(row), False
                attempt = row["build_attempt"] + 1
                db.execute(
                    "UPDATE replay_artifacts SET status='BUILDING',build_attempt=?,builder_pid=NULL,"
                    "builder_start_token=NULL,last_seq=0,artifact_relative_directory=NULL,"
                    "manifest_json=NULL,manifest_sha256=NULL,diagnostics_summary_json=NULL,"
                    "build_runtime_s=NULL,error_code=NULL,error_message=NULL,"
                    "updated_at=?,build_started_at=?,build_finished_at=NULL WHERE replay_id=?",
                    (attempt, now(), now(), row["replay_id"])
                )
                new_row = db.execute("SELECT * FROM replay_artifacts WHERE replay_id=?",
                                     (row["replay_id"],)).fetchone()
                return dict(new_row), True
            columns = tuple(values)
            db.execute(
                "INSERT INTO replay_artifacts (" + ",".join(columns) + ") VALUES ("
                + ",".join("?" for _ in columns) + ")", tuple(values.values())
            )
            new_row = db.execute("SELECT * FROM replay_artifacts WHERE replay_id=?",
                                 (values["replay_id"],)).fetchone()
            return dict(new_row), True

    def set_replay_process(self, replay_id: str, attempt: int, pid: int, token: str) -> bool:
        with self.write() as db:
            result = db.execute(
                "UPDATE replay_artifacts SET builder_pid=?,builder_start_token=?,updated_at=? "
                "WHERE replay_id=? AND build_attempt=? AND status='BUILDING'",
                (pid, token, now(), replay_id, attempt)
            )
            return result.rowcount == 1

    def publish_replay(self, replay_id: str, attempt: int, relative_dir: str,
                       manifest_json: str, manifest_sha256: str,
                       diagnostics_json: str, runtime_s: float) -> bool:
        """文件先完成，再以当前 attempt 的条件更新发布数据库指针。"""
        with self.write() as db:
            result = db.execute(
                "UPDATE replay_artifacts SET status='READY',artifact_relative_directory=?,"
                "manifest_json=?,manifest_sha256=?,diagnostics_summary_json=?,build_runtime_s=?,"
                "builder_pid=NULL,builder_start_token=NULL,updated_at=?,build_finished_at=? "
                "WHERE replay_id=? AND build_attempt=? AND status='BUILDING'",
                (relative_dir, manifest_json, manifest_sha256, diagnostics_json, runtime_s,
                 now(), now(), replay_id, attempt)
            )
            return result.rowcount == 1

    def fail_replay(self, replay_id: str, attempt: int, code: str, message: str) -> bool:
        with self.write() as db:
            result = db.execute(
                "UPDATE replay_artifacts SET status='FAILED',error_code=?,error_message=?,"
                "builder_pid=NULL,builder_start_token=NULL,updated_at=?,build_finished_at=? "
                "WHERE replay_id=? AND build_attempt=? AND status='BUILDING'",
                (code, message[:300], now(), now(), replay_id, attempt)
            )
            return result.rowcount == 1

    def invalidate_replay(self, replay_id: str, code: str, message: str) -> bool:
        with self.write() as db:
            result = db.execute(
                "UPDATE replay_artifacts SET status='FAILED',error_code=?,error_message=?,"
                "artifact_relative_directory=NULL,manifest_json=NULL,manifest_sha256=NULL,"
                "updated_at=?,build_finished_at=? WHERE replay_id=? AND status='READY'",
                (code, message[:300], now(), now(), replay_id)
            )
            return result.rowcount == 1

    def recover_replays(self) -> None:
        """单实例 Controller 取得锁后将上次未完成的构建标记为失败。"""
        with self.write() as db:
            db.execute(
                "UPDATE replay_artifacts SET status='FAILED',error_code='REPLAY_BUILD_INTERRUPTED',"
                "error_message='Controller 重启，旧构建未发布',builder_pid=NULL,"
                "builder_start_token=NULL,updated_at=?,build_finished_at=? WHERE status='BUILDING'",
                (now(), now())
            )

    def delete_finished_run(self, run_id: str) -> dict | None:
        """仅删除终态实验；所有关联记录在同一写事务内清理。"""
        with self.write() as db:
            row = db.execute("SELECT status,config_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            if row["status"] not in TERMINAL:
                raise ValueError("实验仍在排队或运行；请先取消并等待终态")
            exports = [dict(item) for item in db.execute(
                "SELECT format,status,artifact_path,artifact_sha256 FROM exports WHERE run_id=?", (run_id,)
            )]
            replay_rows = db.execute(
                "SELECT replay_id,status FROM replay_artifacts WHERE run_id=?", (run_id,)
            ).fetchall()
            if any(item["status"] == "BUILDING" for item in replay_rows):
                raise ValueError("回放仍在构建；请等待构建结束后再删除实验")
            # RESTRICT 外键要求先删派生缓存记录，再删正式计划。
            db.execute("DELETE FROM replay_artifacts WHERE run_id=?", (run_id,))
            # 现有模式未启用级联删除；先删子表，最后删 runs，避免悬空正式结果。
            for table in ("exports", "metrics", "assignments", "plans", "run_events", "run_attempts"):
                db.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
            return {"run_id": run_id, "config": json.loads(row["config_json"]), "exports": exports,
                    "replay_ids": [item["replay_id"] for item in replay_rows]}

    def compact_after_delete(self) -> None:
        """删除后回收 SQLite 与 WAL 空间；失败不回滚已经提交的删除。"""
        with self.connect() as db:
            db.execute("VACUUM")
            busy, _, _ = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if busy:
                raise sqlite3.OperationalError("WAL 正由其他连接使用，暂时不能截断")

    def record_export(self, run_id: str, format_name: str, data: bytes | None,
                      artifact_path: str | None = None, error_message: str | None = None) -> None:
        if error_message is None:
            from .exporting import require_exportable_record
            require_exportable_record(self.get_run(run_id))
        with self.write() as db:
            status = "FAILED" if error_message else "SUCCEEDED"
            digest = hashlib.sha256(data).hexdigest() if data is not None else None
            db.execute("INSERT INTO exports(run_id,format,status,artifact_sha256,artifact_path,error_message,created_at) VALUES (?,?,?,?,?,?,?)",
                       (run_id, format_name, status, digest, artifact_path, error_message, now()))
