"""验证 v0.2 的扩展接口、旧库迁移和按实验隔离的文件输出。"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pydantic import Field

from eos_system.algorithm_registry import AlgorithmParams, AlgorithmSpec, get_algorithm
from eos_system.config import Settings, list_scenarios_in, normalise_user_path, resolve_scenario_in
from eos_system.contracts import RunConfig
from eos_system.exporting import persist_directory_exports
from eos_system.storage import Database, now
from eos_system.visualization import ORBIT_CACHE_VERSION, ORBIT_STEP_S, orbit_cache_path


class RegistryTests(unittest.TestCase):
    def test_custom_algorithm_can_define_its_own_nested_parameters(self):
        class OwnParams(AlgorithmParams):
            beam_width: int = Field(default=8, ge=1, le=256)
            priorities: list[float] = Field(default_factory=list)

        spec = AlgorithmSpec("example", "示例", "traditional", "组员", "1", OwnParams, lambda context: object())
        parsed = spec.parse_params({"beam_width": 16, "priorities": [0.5, 1.0]})
        self.assertEqual(parsed.beam_width, 16)
        with self.assertRaises(ValueError):
            spec.parse_params({"unknown": 1})
        self.assertEqual(get_algorithm("completion_first").version, "baseline-1")


class CatalogTests(unittest.TestCase):
    def test_scenario_registration_stays_inside_selected_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "demo.json").write_text("{}", encoding="utf-8")
            (root / "half-0.25d.json").write_text("{}", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "hidden.json").write_text("{}", encoding="utf-8")
            self.assertEqual(normalise_user_path(str(root)), root.resolve())
            listed = list_scenarios_in(root, "sample")
            self.assertEqual([(row["source_id"], row["scenario_id"]) for row in listed],
                             [("sample", "demo"), ("sample", "half-0.25d")])
            self.assertEqual(resolve_scenario_in(root, "demo")[0], root / "demo.json")
            self.assertEqual(resolve_scenario_in(root, "half-0.25d")[0], root / "half-0.25d.json")
            with self.assertRaises(ValueError):
                resolve_scenario_in(root, "../hidden")


class MigrationAndExportTests(unittest.TestCase):
    def test_v1_database_is_migrated_without_dropping_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.sqlite3"
            with sqlite3.connect(path) as db:
                db.executescript("""
                CREATE TABLE runs(run_id TEXT PRIMARY KEY);
                CREATE TABLE exports(export_id INTEGER PRIMARY KEY,run_id TEXT);
                INSERT INTO runs(run_id) VALUES ('old-run');
                PRAGMA user_version=1;
                """)
            Database(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT run_id FROM runs").fetchone()[0], "old-run")
                fields = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
                self.assertTrue({"source_id", "output_profile_id"}.issubset(fields))

    def test_successful_plan_is_saved_under_its_run_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "exports"
            output.mkdir()
            database = Database(root / "results.sqlite3")
            config = RunConfig(
                run_id="00000000-0000-4000-8000-000000000002",
                source_id="sample", scenario_id="fixture", scenario_sha256="0" * 64,
                scenario_path=str(root / "fixture.json"), algorithm_id="completion_first",
                algorithm_version="baseline-1", output_profile_id="files",
                output_kind="directory", output_root=str(output), created_at=now(),
            )
            database.enqueue(config, max_queued=8)
            attempt, _ = database.start_attempt(config.run_id)
            self.assertTrue(database.set_verifying(config.run_id, attempt))
            plan = {"scenario_id": "fixture", "assignments": [], "unassigned_tasks": []}
            metrics = {"completed_tasks": 0, "total_tasks": 0, "task_profit": 0.0,
                       "task_completion_rate": 0.0, "balance_degree": 0.0,
                       "timeliness_metric": 0.0, "runtime_efficiency": 0.01,
                       "robustness_variance": None, "mip_gap": None}
            self.assertTrue(database.finish_success(config.run_id, attempt, plan, metrics, 0.001))
            persist_directory_exports(database, config)
            folder = output / config.run_id
            json_path = folder / f"eos-{config.run_id}.json"
            csv_path = folder / f"eos-{config.run_id}.csv"
            self.assertTrue(json_path.is_file())
            self.assertTrue(csv_path.is_file())
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["provenance"]["source_id"], "sample")
            self.assertEqual(len(database.get_run(config.run_id)["exports"]), 2)
            self.assertFalse(any(folder.glob(".pending-*")))


class ReplayTests(unittest.TestCase):
    def test_cached_orbit_survives_missing_original_scenario(self):
        """场景登记目录移动后，已有缓存仍能按提交时哈希回放。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(runtime_dir=root, scenario_dir=root / "scenarios")
            digest = "a" * 64
            cache = root / "visualizations" / "scenes" / f"{digest}-v{ORBIT_CACHE_VERSION}-s{ORBIT_STEP_S}.czml"
            cache.parent.mkdir(parents=True)
            cache.write_text("[]", encoding="utf-8")
            self.assertEqual(orbit_cache_path(settings, root / "scenarios" / "missing.json", digest), cache)


if __name__ == "__main__":
    unittest.main()
