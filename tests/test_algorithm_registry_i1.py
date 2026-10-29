"""I1 registry integration; subprocesses and synthetic inputs only, no certification."""
from dataclasses import replace
import asyncio
import hashlib
import importlib.util
import inspect
import json
import os
import pickle
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pydantic import ValidationError

from algorithms.conflict_beam import CAABSParams, ConflictBeamScheduler, VERSION
from algorithms.solver_contracts import AlgorithmParams, SolveContext, Solver
from eos_system import algorithm_registry as registry
from eos_system.contracts import RunConfig, validate_algorithm_params
from eos_system.runner import prepare, run_prepared
from schedulers.constraint_model import Schedule
from test_algorithm_conflict_beam import Fixture


ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = dict(w_profit=0.0, w_completion=1.0, w_timeliness=0.0, w_balance=0.0)
EXPECTED_DEFAULTS = dict(beam_width=8, branch_limit=8, candidate_check_limit=16,
    max_candidates_per_task=16, max_windows_per_task=32, conflict_prefilter=True,
    candidate_diversity=True, task_order="scarcity", greedy_incumbent=True,
    incremental_keys=True, incremental_objective=False,
    dynamic_repair_limit=12, grid_coverage=True, diversity_slots=2)


class FreshImportTests(unittest.TestCase):
    def run_fresh(self, code):
        env = os.environ.copy()
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                                env=env, capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        data = json.loads(result.stdout)
        self.assertNotEqual(data["pid"], os.getpid())
        return data

    def check_order(self, imports):
        data = self.run_fresh(imports + "\n" + '''
import os, json
from eos_system.algorithm_registry import get_algorithm, list_algorithms, make_context
spec = get_algorithm("caabs")
context = make_context(42, 5.0, {"w_profit":0,"w_completion":1,"w_timeliness":0,"w_balance":0}, spec, {"beam_width":2})
solver = spec.build(context)
assert type(context.params).__name__ == "CAABSParams"
assert context.params.beam_width == 2
assert type(solver).__name__ == "NativeObjectiveSolver"
assert type(solver.base).__name__ == "ConflictBeamScheduler"
assert callable(solver.solve)
print(json.dumps({"pid":os.getpid(),"ids":[x["algorithm_id"] for x in list_algorithms()],"version":spec.version,"solver":type(solver).__name__}))
''')
        self.assertEqual(data["ids"], list(registry.COMPARISON_ALGORITHMS))
        self.assertIn('caabs',data['ids'])
        self.assertEqual(data["version"], VERSION + "+objective-v1")

    def test_algorithm_then_registry_in_fresh_process(self):
        self.check_order("import algorithms.conflict_beam\nimport eos_system.algorithm_registry")

    def test_registry_then_algorithm_in_fresh_process(self):
        self.check_order("import eos_system.algorithm_registry\nimport algorithms.conflict_beam")

    def test_registry_alone_can_query_validate_and_build_caabs(self):
        self.check_order("import eos_system.algorithm_registry")

    def test_contract_import_does_not_initialize_registry_or_factory(self):
        self.run_fresh('''
import os, sys, json
import algorithms.solver_contracts
assert "eos_system.algorithm_registry" not in sys.modules
assert "algorithms.factory" not in sys.modules
print(json.dumps({"pid":os.getpid()}))
''')


class RegistryParameterTests(unittest.TestCase):
    def setUp(self):
        self.spec = registry.get_algorithm("caabs")

    def test_public_contract_names_remain_identical_reexports(self):
        self.assertIs(registry.AlgorithmParams, AlgorithmParams)
        self.assertIs(registry.SolveContext, SolveContext)
        self.assertIs(registry.Solver, Solver)
        self.assertTrue(issubclass(CAABSParams, registry.AlgorithmParams))

    def test_old_pickled_contract_type_references_remain_resolvable(self):
        for name in ("AlgorithmParams", "SolveContext", "Solver"):
            with self.subTest(name=name):
                old_reference = ("ceos_system.algorithm_registry\n" + name + "\n.").encode("ascii")
                self.assertIs(pickle.loads(old_reference), getattr(registry, name))

    def test_metadata_schema_defaults_and_version_are_actual_caabs(self):
        info = self.spec.public_info()
        self.assertEqual((info["algorithm_id"], info["owner"], info["category"], info["version"]),
                         ("caabs", "刘懋兴", "traditional", VERSION + "+objective-v1"))
        self.assertIs(self.spec.params_model, CAABSParams)
        self.assertEqual(self.spec.parse_params({}).model_dump(), EXPECTED_DEFAULTS)
        self.assertEqual(set(info["parameters"]["properties"]), set(CAABSParams.model_fields))
        self.assertIs(info["parameters"]["additionalProperties"], False)
        json.dumps(registry.list_algorithms(), allow_nan=False)

    def test_all_parameter_boundaries_are_valid_and_frozen(self):
        for raw in (dict(beam_width=1, branch_limit=1, candidate_check_limit=1, max_candidates_per_task=1, max_windows_per_task=1, conflict_prefilter=False),
                    dict(beam_width=256, branch_limit=64, candidate_check_limit=128, max_candidates_per_task=128, max_windows_per_task=256, conflict_prefilter=True)):
            with self.subTest(raw=raw):
                params = self.spec.parse_params(raw)
                self.assertIs(type(params), CAABSParams)
                self.assertEqual(params.model_dump(), EXPECTED_DEFAULTS | raw)
                with self.assertRaises(ValidationError):
                    params.beam_width = 2

    def test_strict_integer_ranges_and_boolean_validation(self):
        for field, upper in (("beam_width", 256), ("branch_limit", 64),
                             ("candidate_check_limit",128), ("max_candidates_per_task", 128), ("max_windows_per_task", 256)):
            for value in (0, upper + 1, -1, True, 1.0, "2", None):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, field):
                    self.spec.parse_params({field: value})
        for field in ("conflict_prefilter","candidate_diversity","greedy_incumbent","incremental_keys","incremental_objective"):
            for value in (0, 1, "false", None):
                with self.subTest(field=field,value=value), self.assertRaisesRegex(ValueError, field):
                    self.spec.parse_params({field: value})
        for value in ("random", 0, None):
            with self.subTest(order=value), self.assertRaisesRegex(ValueError,"task_order"):
                self.spec.parse_params({"task_order":value})

    def test_unknown_fields_non_objects_and_wrong_parameter_scope_rejected(self):
        for raw in ({"unknown": 1}, {"seed": 42}, {"time_budget_s": 1}, [], None, "{}", 1):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.spec.parse_params(raw)

    def test_context_and_compatibility_validator_use_same_model(self):
        context = registry.make_context(19, 2.5, WEIGHTS, self.spec, {"branch_limit": 3})
        self.assertIs(type(context.params), CAABSParams)
        self.assertEqual((context.seed, context.time_budget_s, context.params.branch_limit), (19, 2.5, 3))
        validate_algorithm_params("caabs", {"branch_limit": 3})
        with self.assertRaisesRegex(ValueError, "branch_limit"):
            validate_algorithm_params("caabs", {"branch_limit": 0})
        for budget in (0, -1, float("nan"), float("inf")):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                registry.make_context(19, budget, WEIGHTS, self.spec, {})

    def test_existing_algorithms_keep_metadata_and_validation(self):
        self.assertEqual([x["model_id"] for x in registry.list_schedule_models()],
                         ["completion_first", "adaptive_repair"])
        for name in ("completion_first", "adaptive_repair"):
            spec = registry.get_algorithm(name)
            self.assertEqual((spec.version, spec.category), ("baseline-1", "baseline"))
            self.assertIsInstance(spec.parse_params({}), AlgorithmParams)
            with self.assertRaises(ValueError):
                spec.parse_params({"unknown": 1})
        adaptive = registry.get_algorithm("adaptive_repair")
        self.assertEqual(adaptive.parse_params({"alns_iterations": 0}).alns_iterations, 0)
        with self.assertRaises(ValueError):
            adaptive.parse_params({"alns_iterations": -1})
        with self.assertRaisesRegex(ValueError, "算法未登记"):
            registry.get_algorithm("unknown")

    def test_runner_prepares_caabs_from_real_config_and_loader(self):
        # Empty synthetic scene proves wiring/serialization only, never exposure certification.
        with tempfile.TemporaryDirectory(prefix="i1-runner-") as folder:
            path = Path(folder) / "synthetic.json"
            scene = dict(scenario_id="I1-UNIT-ONLY", metadata=dict(creation_time="2026-01-01T00:00:00Z",
                         duration=60, time_step=1), satellites=[], missions=[], observation_windows=[])
            path.write_text(json.dumps(scene), encoding="utf-8")
            config = RunConfig(run_id="i1-unit", scenario_id=path.stem, algorithm_id="caabs",
                algorithm_params={"beam_width": 2}, objective_weights=WEIGHTS,
                scenario_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), scenario_path=str(path),
                algorithm_version=VERSION, created_at="2026-01-01T00:00:00Z", time_budget_s=5)
            solver, problem, constraints, context = prepare(config)
            self.assertIs(type(solver), ConflictBeamScheduler)
            self.assertIs(type(context.params), CAABSParams)
            self.assertEqual(context.params.beam_width, 2)
            result, runtime = run_prepared(solver, problem, constraints, context)
            self.assertEqual(result["assignments"], [])
            self.assertGreaterEqual(runtime, 0)
            json.dumps(result, allow_nan=False)

    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "HTTP metadata test requires FastAPI; use project WSL environment")
    def test_http_algorithm_list_exposes_real_caabs_schema(self):
        from eos_system.api import create_app
        from eos_system.config import Settings

        async def query(app):
            # Metadata route only; do not start Controller lifespan or submit a run.
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                messages.append(message)

            await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                       "method": "GET", "scheme": "http", "path": "/api/algorithms",
                       "raw_path": b"/api/algorithms", "query_string": b"", "root_path": "",
                       "headers": [], "client": ("test", 1), "server": ("test", 80)}, receive, send)
            self.assertEqual([m["status"] for m in messages if m["type"] == "http.response.start"], [200])
            payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
            rows = json.loads(payload)["items"]
            self.assertEqual([x["algorithm_id"] for x in rows], list(registry.COMPARISON_ALGORITHMS))
            from eos_system.algorithm_presentation import algorithm_info
            self.assertEqual(next(row for row in rows if row['algorithm_id']=='caabs'), algorithm_info(self.spec))

        with tempfile.TemporaryDirectory(prefix="i1-api-metadata-") as folder:
            root = Path(folder)
            scenarios = root / "scenarios"
            scenarios.mkdir()
            app = create_app(Settings(runtime_dir=root, scenario_dir=scenarios))
            asyncio.run(query(app))


class RegistrySolverTests(Fixture):
    def setUp(self):
        super().setUp()
        self.task("T1", [("S1", 0)])
        self.task("T2", [("S1", 30)])

    def test_registry_solver_replays_nonempty_schedule_through_public_constraints(self):
        spec = registry.get_algorithm("caabs")
        context = registry.make_context(42, 5, WEIGHTS, spec, {"beam_width": 2})
        solver = spec.build(context)
        self.assertIs(type(solver.base), ConflictBeamScheduler)
        self.assertEqual(list(inspect.signature(solver.solve).parameters), ["problem", "constraints", "context"])
        result = solver.solve(self.problem, self.cm, context)
        self.assertIsInstance(result, Schedule)
        self.assertEqual(set(result.assigned_task_ids), {"T1", "T2"})
        self.assert_shared_feasible(result)

    def test_build_does_not_capture_pre_worker_context(self):
        spec = registry.get_algorithm("caabs")
        context = registry.make_context(42, 5, WEIGHTS, spec, {"beam_width": 1})
        solver = spec.build(replace(context, is_cancelled=lambda: True))
        result = solver.solve(self.problem, self.cm, context)
        self.assertEqual(len(result.assignments), 2)
        self.assert_shared_feasible(result)

    def test_existing_registry_solvers_keep_legacy_adapter_and_work(self):
        for name, raw in (("completion_first", {}), ("adaptive_repair", {"alns_iterations": 0})):
            with self.subTest(algorithm=name):
                spec = registry.get_algorithm(name)
                context = registry.make_context(17, 5, WEIGHTS, spec, raw)
                solver = spec.build(context)
                self.assertIsInstance(solver, registry.LegacySearchAdapter)
                self.assertEqual(solver.algorithm.cfg.seed, 17)
                if name == "adaptive_repair":
                    self.assertEqual(solver.algorithm.cfg.time_budget_s, 5)
                    self.assertEqual(solver.algorithm.cfg.alns_iterations, 0)
                result = solver.solve(self.problem, self.cm, context)
                self.assertIsInstance(result, Schedule)
                self.assertEqual(len(result.assignments), 2)
                self.assert_shared_feasible(result)


if __name__ == "__main__":
    unittest.main()
