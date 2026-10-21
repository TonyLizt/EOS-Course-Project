"""Actual Orekit source-chain tests; no mocked windows or certification."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
import time
import socket
import subprocess
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


@unittest.skipUnless(os.environ.get("EOS_RUN_GEN02_PHYSICS") == "1", "real Orekit opt-in")
class RealDevelopmentSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils.visibility import ensure_orekit
        from scripts.generate_caabs_development_scene import generate
        ensure_orekit(os.environ["EOS_OREKIT_DATA"])
        cls.temp = tempfile.TemporaryDirectory(prefix="caabs-real-source-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.generated = cls.root / "generated"
        repository = Path(__file__).resolve().parents[1]
        cls.result = generate(cls.generated, repository / "input/10_satellites.json",
                              "ALOS-2_39766", os.environ["EOS_OREKIT_DATA"])

    def setUp(self):
        self.temp_case = tempfile.TemporaryDirectory(prefix="caabs-real-source-case-")
        self.addCleanup(self.temp_case.cleanup)
        self.directory = Path(self.temp_case.name)
        self.path = self.directory / "scene.json"
        self.path.write_bytes((self.generated / "scene.json").read_bytes())
        (self.directory / "provenance").mkdir()
        self.sidecar = self.directory / "provenance/scene.json.provenance.json"
        self.sidecar.write_bytes((self.generated / "provenance/scene.json.provenance.json").read_bytes())

    def load(self):
        from schedulers.scenario_loader import load_scheduling_problem_from_json
        return load_scheduling_problem_from_json(self.path)

    def config(self):
        from eos_system.contracts import RunConfig
        from eos_system.algorithm_registry import get_algorithm
        from eos_system.provenance import capture_development_provenance
        sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        return RunConfig(run_id=str(uuid.uuid4()), scenario_id="scene", scenario_path=str(self.path),
            scenario_sha256=sha, algorithm_id="caabs", algorithm_version=get_algorithm("caabs").version,
            seed=42, placement_mode="center", time_budget_s=1., execution_mode="planning_preview",
            scenario_provenance=capture_development_provenance(self.path, sha),
            created_at=datetime.now(timezone.utc).isoformat())

    def assert_untrusted(self):
        from utils.continuous_exposure import planning_window, ExposureStatus
        windows = [w for t in self.load().tasks.values() for w in t.windows]
        self.assertTrue(windows)
        self.assertTrue(all(planning_window(w).status is ExposureStatus.INCONCLUSIVE for w in windows))

    def test_real_generation_has_three_trusted_windows_and_nonempty_candidate(self):
        from utils.continuous_exposure import planning_window, ExposureStatus
        from eos_system.runner import calculate
        windows = [w for t in self.load().tasks.values() for w in t.windows]
        self.assertEqual(len(windows), 3)
        self.assertTrue(all(planning_window(w).status is ExposureStatus.PLANNING_FEASIBLE for w in windows))
        plan, runtime = calculate(self.config())
        self.assertGreater(len(plan["assignments"]), 0)
        self.assertLess(runtime, 1.)
        self.assertTrue(all(type(a["sat_window_id"]) is int for a in plan["assignments"]))

    def test_formal_provenance_gate_does_not_accept_development_record(self):
        from eos_system.provenance import capture_provenance, verify_provenance
        config = self.config()
        with self.assertRaises(ValueError):
            capture_provenance(self.path, config.scenario_sha256)
        with self.assertRaisesRegex(ValueError, "not eligible for formal"):
            verify_provenance(config.model_copy(update={"execution_mode": "formal"}))

    def test_completion_first_real_candidates_keep_n_plus_one_boundary_states(self):
        from eos_system.runner import calculate
        from eos_system.algorithm_registry import get_algorithm
        from eos_system.verification import verify_candidate
        config = self.config().model_copy(update={"algorithm_id": "completion_first",
            "algorithm_version": get_algorithm("completion_first").version, "algorithm_params": {}})
        plan, runtime = calculate(config)
        self.assertGreater(len(plan["assignments"]), 0)
        for a in plan["assignments"]:
            self.assertEqual(len(a["sat_angles"]["boundary_quaternions_xyzw"]), 11)
        _, metrics, _ = verify_candidate(config, plan, runtime)
        self.assertGreater(metrics["completed_tasks"], 0)

    def test_deleted_sidecar_cannot_fall_back_to_embedded_record(self):
        self.sidecar.unlink()  # Owned negative-test copy only.
        self.assert_untrusted()

    def test_wrong_generator_version_is_not_trusted(self):
        record = json.loads(self.sidecar.read_bytes())
        record['generator_version'] = 'unrecognized-generator-999'
        self.sidecar.write_text(json.dumps(record))
        self.assert_untrusted()

    def test_non_object_sidecar_fails_closed_without_loader_crash(self):
        self.sidecar.write_text('[]')
        self.assert_untrusted()

    def test_truncated_sidecar_is_not_trusted(self):
        self.sidecar.write_text('{')
        self.assert_untrusted()

    def test_symlink_sidecar_is_not_trusted(self):
        saved = self.directory / 'owned-sidecar-copy.json'
        saved.write_bytes(self.sidecar.read_bytes())
        self.sidecar.unlink()
        self.sidecar.symlink_to(saved)
        self.assert_untrusted()

    def test_window_and_attitude_byte_tampering_rejected(self):
        scene = json.loads(self.path.read_bytes())
        scene["observation_windows"][0]["time_windows"][0]["agile_data"]["roll_angles"][0] += .5
        self.path.write_text(json.dumps(scene))
        self.assert_untrusted()

    def test_current_source_hash_mismatch_rejected(self):
        record = json.loads(self.sidecar.read_bytes())
        record["source_files_sha256"]["utils/visibility.py"] = "0" * 64
        self.sidecar.write_text(json.dumps(record))
        self.assert_untrusted()

    def test_raw_input_identity_tampering_rejected(self):
        record = json.loads(self.sidecar.read_bytes())
        record["raw_satellite_sha256"] = "0" * 64
        self.sidecar.write_text(json.dumps(record))
        self.assert_untrusted()

    def test_source_id_tampering_rejected_by_independent_verifier(self):
        from eos_system.runner import calculate
        from eos_system.verification import verify_candidate
        config = self.config()
        plan, runtime = calculate(config)
        self.assertTrue(plan["assignments"])
        plan["assignments"][0]["sat_window_id"] = 99999
        with self.assertRaisesRegex(ValueError, "UNKNOWN_SAT_WINDOW_ID"):
            verify_candidate(config, plan, runtime)

    def test_real_nonempty_plan_independent_preview_is_not_continuous_pass(self):
        from eos_system.runner import calculate
        from eos_system.verification import verify_candidate
        config = self.config()
        plan, runtime = calculate(config)
        official, metrics, receipt = verify_candidate(config, plan, runtime)
        self.assertGreater(metrics["completed_tasks"], 0)
        self.assertEqual(receipt.evidence()["status"], "SAMPLED_PREVIEW")
        summary = receipt.evidence()["audit_summary"]
        self.assertEqual(summary["status"], "INCONCLUSIVE")
        self.assertTrue(all(r["reason"] == "NO_CONTINUITY_CERTIFICATE" for r in summary["rows"]))
        self.assertEqual(len(official["assignments"]), len(plan["assignments"]))

    def test_http_real_spawn_development_preview_and_formal_export_gate(self):
        runtime_temp = tempfile.TemporaryDirectory(prefix="caabs-http-runtime-")
        self.addCleanup(runtime_temp.cleanup)
        runtime = Path(runtime_temp.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        environment = os.environ | dict(EOS_PORT=str(port), EOS_RUNTIME_DIR=str(runtime),
            EOS_SCENARIO_DIR=str(self.directory), EOS_PREINITIALIZE_OREKIT="1")
        def request_api(path, data=None):
            request = Request(f"http://127.0.0.1:{port}{path}",
                data=json.dumps(data).encode() if data is not None else None,
                headers={"Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=10) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                return exc.code, json.load(exc)
        log = (self.directory / "http.log").open("w+")
        server = subprocess.Popen([sys.executable, "-B", "-m", "eos_system"],
            cwd=Path(__file__).resolve().parents[1], env=environment, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    code, body = request_api("/api/algorithms")
                    break
                except (URLError, ConnectionError):
                    if server.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        self.fail(log.read())
                    time.sleep(.1)
            self.assertEqual(code, 200)
            algorithms = body["items"]
            caabs = next(a for a in algorithms if a["algorithm_id"] == "caabs")
            from algorithms.conflict_beam import VERSION
            self.assertEqual(caabs["version"], VERSION)
            self.assertIn("beam_width", caabs["parameters"]["properties"])
            listing = request_api("/api/scenarios?execution_mode=planning_preview")[1]["items"]
            row = next(r for r in listing if r["scenario_id"] == "scene")
            self.assertEqual(row["availability"], "ready")
            self.assertEqual(row["execution_modes"], ["planning_preview"])
            request = dict(scenario_id="scene", algorithm_id="caabs", placement_mode="center",
                execution_mode="planning_preview", time_budget_s=1.,
                algorithm_params=dict(beam_width=4, branch_limit=4, max_candidates_per_task=8))
            self.assertEqual(request_api("/api/runs", request | dict(execution_mode="formal"))[0], 422)
            code, response = request_api("/api/runs", request)
            self.assertEqual(code, 202, response)
            run_id = response["run_id"]
            deadline = time.monotonic() + 80
            while time.monotonic() < deadline:
                record = request_api(f"/api/runs/{run_id}")[1]
                if record["status"] in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}:
                    break
                time.sleep(.05)
            self.assertEqual(record["status"], "SUCCEEDED", record["error"])
            self.assertGreater(record["metrics"]["completed_tasks"], 0)
            self.assertEqual(record["continuous_certification"]["status"], "NOT_CERTIFIED")
            telemetry = next(e["payload"] for e in record["events"] if e["event_type"] == "candidate_result")
            self.assertEqual(telemetry["untrusted_solver_diagnostics"]["caabs"]["stop_reason"], "completed")
            self.assertEqual(request_api(f"/api/runs/{run_id}/export?format=json")[0], 409)
            self.assertEqual(request_api(f"/api/runs/{run_id}/export?format=csv")[0], 409)
            code, view = request_api(f"/api/runs/{run_id}/visualization/schedule")
            self.assertEqual(code, 200, view)
            self.assertEqual(view["result_kind"], "planning_preview")
        finally:
            server.terminate()
            try:
                server.wait(timeout=25)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
                self.fail("real HTTP Controller did not gracefully shut down; http.log retained until cleanup")
            finally:
                log.close()


if __name__ == "__main__":
    unittest.main()
