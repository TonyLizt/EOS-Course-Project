-- 当前数据库结构快照；不含实验数据。
PRAGMA foreign_keys=ON;

CREATE TABLE assignments (
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

CREATE TABLE data_sources (
  source_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  root_path TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE experiment_runs (
  experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
  algorithm_id TEXT NOT NULL,
  removed_at TEXT
);

CREATE TABLE experiments (
  experiment_id TEXT PRIMARY KEY,
  common_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  legacy INTEGER NOT NULL DEFAULT 0,
  idempotency_key TEXT UNIQUE,
  request_sha256 TEXT
);

CREATE TABLE exports (
  export_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  format TEXT NOT NULL CHECK (format IN ('json','csv')),
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED','FAILED')),
  artifact_sha256 TEXT,
  artifact_path TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE metrics (
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

CREATE TABLE output_profiles (
  profile_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('download','directory')),
  root_path TEXT UNIQUE,
  created_at TEXT NOT NULL,
  CHECK ((kind='download' AND root_path IS NULL) OR (kind='directory' AND root_path IS NOT NULL))
);

CREATE TABLE plans (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
  attempt_no INTEGER NOT NULL,
  scenario_id TEXT NOT NULL,
  plan_schema_version INTEGER NOT NULL DEFAULT 1,
  plan_json TEXT NOT NULL,
  plan_sha256 TEXT NOT NULL,
  verified_at TEXT NOT NULL,
  FOREIGN KEY (run_id, attempt_no) REFERENCES run_attempts(run_id,attempt_no)
);

CREATE TABLE replay_artifacts (
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

CREATE TABLE run_attempts (
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

CREATE TABLE run_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  attempt_no INTEGER,
  source TEXT NOT NULL,
  source_seq INTEGER,
  event_type TEXT NOT NULL,
  payload_json TEXT,
  recorded_at TEXT NOT NULL
);

CREATE TABLE runs (
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

CREATE INDEX idx_assignments_sat ON assignments(run_id,satellite_id,sat_start_time);

CREATE INDEX idx_events_run ON run_events(run_id,event_id);

CREATE INDEX idx_experiment_created ON experiments(created_at);

CREATE INDEX idx_replay_run_created ON replay_artifacts(run_id,created_at);

CREATE INDEX idx_replay_status_updated ON replay_artifacts(status,updated_at);

CREATE INDEX idx_runs_scenario_algorithm ON runs(scenario_id,algorithm_id,created_at);

CREATE INDEX idx_runs_status_time ON runs(status,created_at);

CREATE UNIQUE INDEX uq_experiment_active_algorithm
  ON experiment_runs(experiment_id,algorithm_id) WHERE removed_at IS NULL;

CREATE UNIQUE INDEX uq_worker_event ON run_events(run_id,attempt_no,source,source_seq)
  WHERE source_seq IS NOT NULL;

PRAGMA user_version=4;
