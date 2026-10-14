"""SQLite 正式结果库。

每次调用独立开连接；写操作显式使用 IMMEDIATE 事务，防止取消与成功提交交叉。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .contracts import RunConfig


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


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise RuntimeError(f"数据库版本 {version} 比当前程序新")
            if version == 0:
                connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nPRAGMA user_version=2;\nCOMMIT;")
            elif version == 1:
                # 仅向前增加表和列，保留 v0.1 正式实验与导出记录。
                connection.executescript("BEGIN IMMEDIATE;\n" + MIGRATION_1_TO_2 + "\nPRAGMA user_version=2;\nCOMMIT;")

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
    def write(self):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
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
        """记录正式状态之外的诊断事件，例如可选文件导出失败。"""
        with self.write() as db:
            self._event(db, run_id, attempt, "controller", None, kind, payload)

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
            row = db.execute("SELECT status,current_attempt FROM runs WHERE run_id=?", (run_id,)).fetchone()
            last = db.execute("SELECT last_seq FROM run_attempts WHERE run_id=? AND attempt_no=?", (run_id, attempt)).fetchone()
            if not row or row["current_attempt"] != attempt or row["status"] in TERMINAL or not last or seq <= last["last_seq"]:
                return False
            db.execute("UPDATE run_attempts SET last_seq=?,worker_pid=COALESCE(?,worker_pid),worker_start_token=COALESCE(?,worker_start_token) WHERE run_id=? AND attempt_no=?",
                       (seq, message["payload"].get("worker_pid"), message["payload"].get("worker_start_token"), run_id, attempt))
            payload = message["payload"] if message["kind"] != "candidate_result" else {"algorithm_runtime_s": message["payload"].get("algorithm_runtime_s")}
            self._event(db, run_id, attempt, "worker", seq, message["kind"], payload)
            return True

    def set_verifying(self, run_id: str, attempt: int) -> bool:
        with self.write() as db:
            result = db.execute("UPDATE runs SET status='VERIFYING',updated_at=? WHERE run_id=? AND current_attempt=? AND status='RUNNING' AND cancel_requested_at IS NULL",
                                (now(), run_id, attempt))
            if result.rowcount:
                self._event(db, run_id, attempt, "controller", None, "VERIFYING", None)
            return bool(result.rowcount)

    def finish_success(self, run_id: str, attempt: int, plan: dict, metrics: dict, verify_s: float) -> bool:
        plan_json = compact_json(plan)
        with self.write() as db:
            row = db.execute("SELECT status,cancel_requested_at,scenario_id FROM runs WHERE run_id=? AND current_attempt=?", (run_id, attempt)).fetchone()
            if not row or row["status"] != "VERIFYING" or row["cancel_requested_at"] is not None:
                return False
            db.execute("INSERT INTO plans(run_id,attempt_no,scenario_id,plan_json,plan_sha256,verified_at) VALUES (?,?,?,?,?,?)",
                       (run_id, attempt, plan["scenario_id"], plan_json, hashlib.sha256(plan_json.encode()).hexdigest(), now()))
            for index, item in enumerate(plan["assignments"]):
                db.execute("INSERT INTO assignments(run_id,ordinal,task_id,satellite_id,sensor_id,sat_start_time,sat_end_time,ground_station_id,gs_start_time,gs_end_time,assignment_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (run_id, index, item["task_id"], item["satellite_id"], item["sensor_id"], item["sat_start_time"], item["sat_end_time"],
                            item.get("ground_station_id"), item.get("gs_start_time"), item.get("gs_end_time"), compact_json(item)))
            db.execute("INSERT INTO metrics(run_id,completed_tasks,total_tasks,TP,TCR,BD,TM,RT,RV,mip_gap,computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (run_id, metrics["completed_tasks"], metrics["total_tasks"], metrics["task_profit"], metrics["task_completion_rate"],
                        metrics["balance_degree"], metrics["timeliness_metric"], metrics["runtime_efficiency"], metrics["robustness_variance"], metrics["mip_gap"], now()))
            db.execute("UPDATE run_attempts SET outcome='SUCCEEDED',ended_at=?,algorithm_runtime_s=?,verification_runtime_s=? WHERE run_id=? AND attempt_no=?",
                       (now(), metrics["runtime_efficiency"], verify_s, run_id, attempt))
            db.execute("UPDATE runs SET status='SUCCEEDED',updated_at=?,finished_at=? WHERE run_id=?", (now(), now(), run_id))
            self._event(db, run_id, attempt, "controller", None, "SUCCEEDED", {"completed_tasks": metrics["completed_tasks"]})
            return True

    def finish_failure(self, run_id: str, attempt: int | None, status: str, code: str, message: str) -> None:
        if status not in {"FAILED", "CANCELLED", "TIMED_OUT"}:
            raise ValueError("非法终态")
        with self.write() as db:
            row = db.execute("SELECT status,current_attempt FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row or row["status"] in TERMINAL or (attempt is not None and row["current_attempt"] != attempt):
                return
            db.execute("UPDATE runs SET status=?,error_code=?,error_message=?,updated_at=?,finished_at=? WHERE run_id=?",
                       (status, code, message[:300], now(), now(), run_id))
            if attempt is not None:
                db.execute("UPDATE run_attempts SET outcome=?,error_code=?,ended_at=? WHERE run_id=? AND attempt_no=?",
                           (status, code, now(), run_id, attempt))
            self._event(db, run_id, attempt, "controller", None, status, {"code": code})

    def request_cancel(self, run_id: str) -> tuple[str, bool] | None:
        with self.write() as db:
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
            plan = db.execute("SELECT plan_json FROM plans WHERE run_id=?", (run_id,)).fetchone()
            metrics = db.execute("SELECT * FROM metrics WHERE run_id=?", (run_id,)).fetchone()
            attempts = db.execute("SELECT attempt_no,worker_pid,started_at,ended_at,outcome,algorithm_runtime_s,verification_runtime_s,exit_code FROM run_attempts WHERE run_id=? ORDER BY attempt_no", (run_id,)).fetchall()
            events = db.execute("SELECT event_id,attempt_no,source,event_type,payload_json,recorded_at FROM run_events WHERE run_id=? ORDER BY event_id", (run_id,)).fetchall()
            exports = db.execute("SELECT export_id,format,status,artifact_sha256,artifact_path,error_message,created_at FROM exports WHERE run_id=? ORDER BY export_id", (run_id,)).fetchall()
            return {
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

    def list_runs(self, limit: int = 20, offset: int = 0) -> dict:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            rows = db.execute("SELECT r.run_id,r.source_id,r.scenario_id,r.algorithm_id,r.output_profile_id,r.status,r.created_at,r.finished_at,m.TCR,m.completed_tasks FROM runs r LEFT JOIN metrics m ON r.run_id=m.run_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def record_export(self, run_id: str, format_name: str, data: bytes | None,
                      artifact_path: str | None = None, error_message: str | None = None) -> None:
        with self.write() as db:
            status = "FAILED" if error_message else "SUCCEEDED"
            digest = hashlib.sha256(data).hexdigest() if data is not None else None
            db.execute("INSERT INTO exports(run_id,format,status,artifact_sha256,artifact_path,error_message,created_at) VALUES (?,?,?,?,?,?,?)",
                       (run_id, format_name, status, digest, artifact_path, error_message, now()))
