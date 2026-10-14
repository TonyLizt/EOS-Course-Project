"""验证正式结果的事务边界与排队取消，而非重复实现业务逻辑。"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from eos_system.contracts import RunConfig
from eos_system.storage import Database, now


class StorageTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.sqlite3")
        self.config = RunConfig(
            run_id="00000000-0000-4000-8000-000000000001",
            scenario_id="fixture", scenario_sha256="0" * 64, scenario_path="/tmp/fixture.json",
            algorithm_id="completion_first", algorithm_version="test", created_at=now(),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_failed_metric_rolls_back_plan_and_assignments(self):
        self.database.enqueue(self.config, max_queued=8)
        attempt, _ = self.database.start_attempt(self.config.run_id)
        self.assertTrue(self.database.set_verifying(self.config.run_id, attempt))
        plan = {"scenario_id": "fixture", "assignments": [{
            "task_id": "M1", "satellite_id": "S1", "sensor_id": "sensor",
            "sat_start_time": "2026-01-01T00:00:00", "sat_end_time": "2026-01-01T00:00:10",
        }], "unassigned_tasks": []}
        metrics = {
            "completed_tasks": 2, "total_tasks": 1, "task_profit": 1.0,
            "task_completion_rate": 2.0, "balance_degree": 1.0,
            "timeliness_metric": 1.0, "runtime_efficiency": 0.1,
            "robustness_variance": None, "mip_gap": None,
        }
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.finish_success(self.config.run_id, attempt, plan, metrics, 0.01)
        with self.database.connect() as db:
            for table in ("plans", "assignments", "metrics"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(self.database.get_run(self.config.run_id)["status"], "VERIFYING")

    def test_queued_cancel_never_starts_worker(self):
        self.database.enqueue(self.config, max_queued=8)
        self.assertEqual(self.database.request_cancel(self.config.run_id), ("CANCELLED", True))
        self.assertIsNone(self.database.next_queued())
        self.assertIsNone(self.database.start_attempt(self.config.run_id))

    def test_repeated_worker_sequence_is_ignored(self):
        self.database.enqueue(self.config, max_queued=8)
        attempt, _ = self.database.start_attempt(self.config.run_id)
        message = {"run_id": self.config.run_id, "attempt": attempt, "seq": 1,
                   "kind": "heartbeat", "payload": {"phase": "SEARCHING"}}
        self.assertTrue(self.database.record_worker_event(message))
        self.assertFalse(self.database.record_worker_event(message))
        with self.database.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM run_events WHERE source='worker'").fetchone()[0]
        self.assertEqual(count, 1)

    def test_cancel_during_verification_blocks_success(self):
        """核验与取消交错时不能留下正式计划，也不能卡在 VERIFYING。"""
        self.database.enqueue(self.config, max_queued=8)
        attempt, _ = self.database.start_attempt(self.config.run_id)
        self.assertTrue(self.database.set_verifying(self.config.run_id, attempt))
        self.assertEqual(self.database.request_cancel(self.config.run_id), ("VERIFYING", True))
        self.assertFalse(self.database.finish_success(self.config.run_id, attempt,
                                                      {"scenario_id": "fixture", "assignments": [], "unassigned_tasks": []},
                                                      {}, 0.01))
        self.database.finish_failure(self.config.run_id, attempt, "CANCELLED", "CANCELLED_DURING_VERIFY", "核验期间已取消")
        self.assertEqual(self.database.get_run(self.config.run_id)["status"], "CANCELLED")
        with self.database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM plans").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
