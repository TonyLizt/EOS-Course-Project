"""End-to-end fail-closed tests. PASS auditor below is UNIT TEST INJECTION ONLY."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from functools import partial

from algorithms.candidate_pool import enumerate_task_candidates
from schedulers.scenario_loader import load_scheduling_problem_from_json
from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from utils.continuous_exposure import (
    ExposureStatus, ContinuousCertificationError, planning_window, planning_exposure,
    window_generation_record, GRID_V2_SOURCE_SHA256, certify_schedule, source_identity)
from eos_system import controller as controller_module
from eos_system.config import Settings
from eos_system.contracts import RunConfig
from eos_system.storage import Database, now, compact_json
from eos_system.exporting import render_json, render_csv, persist_directory_exports
from eos_system.api import create_app
from test_continuous_exposure import fixture, CASES, START
from certification_fixtures import storage_receipt


def _fixed_worker(plan, run_id, attempt, events, control):
    # Real spawn / handshake / process-group machinery; only solver output is a stub.
    from eos_system import worker_reference as worker
    def prepare(config):
        from eos_system.algorithm_registry import SolveContext, CompletionParams
        from algorithms.objectives import ObjectiveWeights
        context=SolveContext(config.seed,config.time_budget_s,ObjectiveWeights(),CompletionParams())
        return None, load_scheduling_problem_from_json(config.scenario_path), None, context
    with patch.object(worker, "prepare", side_effect=prepare), patch.object(
            worker, "run_prepared", return_value=(plan,.001)):
        worker.worker_main(run_id,attempt,events,control)


class _AuditFixture:
    """Never installed by production; all output explicitly identifies the mock."""
    def __init__(self, status, **kwargs):
        self.status=status
        self.data_path=kwargs["data_path"]
    def audit(self, plan):
        if self.status=="exception":
            raise RuntimeError("UNIT_TEST_VERIFIER_EXCEPTION")
        if self.status=="hang":
            time.sleep(.2)
        status="PASS" if self.status=="hang" else self.status
        reason={"PASS":"CERTIFIED_INTERVAL","FAIL":"NONVISIBLE_EXPOSURE_POINT",
                "INCONCLUSIVE":"NO_CONTINUITY_CERTIFICATE"}[status]
        return dict(status=status, rows=[dict(status=status,reason=reason)],
                    model="UNIT_TEST_INJECTION_ONLY",scan_step_s=.05,boundary_precision_us=1,
                    predicate="UNIT_TEST_ONLY",orekit_data_sha256=hashlib.sha256(Path(self.data_path).read_bytes()).hexdigest())


class PlanningGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"scene.json"

    def load(self,scene,version="visibility_grid_v2"):
        if version=="visibility_exit_refined_v3":
            scene["metadata"]["extra"]={"window_generation":window_generation_record(1.,5.,60.)}
        self.path.write_text(json.dumps(scene))
        if version=="visibility_grid_v2":
            folder=self.path.parent/"provenance";folder.mkdir(exist_ok=True)
            (folder/(self.path.name+".provenance.json")).write_text(json.dumps(dict(
                scenario_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),completion_status="complete",
                calculator_kind="orekit",window_boundary_version=version,
                source_files_sha256={"utils/visibility.py":GRID_V2_SOURCE_SHA256},
                calculation_settings={"time_step":1.,"min_elevation_deg":5.})))
        return load_scheduling_problem_from_json(self.path)

    def test_both_known_old_acceptances_rejected_by_both_new_entries(self):
        for mid,sid,start,duration,root in CASES:
            from utils.time_parsing import parse_orbit_epoch
            scene,plan=fixture(mid,sid,parse_orbit_epoch(start),duration)
            problem=self.load(scene);task=problem.tasks[mid];w=task.windows[0]
            a=Assignment(mid,sid,w.start_time,w.end_time,w.window_id,sensor_id="camera",sat_angles=w.agile_data)
            model=ConstraintModel(problem)
            # Unchanged legacy discrete predicate really accepts both bad intervals.
            self.assertTrue(model.check_discrete_assignment(a,Schedule()))
            self.assertFalse(model.is_feasible_assignment(a,Schedule()))
            self.assertEqual(enumerate_task_candidates(problem,task,seed=42),[])
            self.assertIsNone(model.build_feasible_assignment_for_task(task,Schedule()))

    def test_v3_budget_not_deducted_twice_and_exact_microsecond(self):
        scene,_=fixture(duration=2);problem=self.load(scene,"visibility_exit_refined_v3")
        w=problem.tasks["M"].windows[0]
        self.assertEqual(planning_window(w).safe_end.replace(tzinfo=None),w.end_time)
        d=planning_exposure(w,w.start_time,w.end_time,2)
        self.assertIs(d.status,ExposureStatus.PLANNING_FEASIBLE)
        self.assertIs(planning_exposure(w,w.start_time,w.end_time+timedelta(microseconds=1),2.000001).status,ExposureStatus.REJECTED)
        aware=w.start_time.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8)))
        self.assertIs(planning_exposure(w,aware,w.end_time,2).status,ExposureStatus.PLANNING_FEASIBLE)

    def test_unknown_step_and_forged_or_stale_source_fail_closed(self):
        scene,_=fixture();problem=self.load(scene,"visibility_exit_refined_v3");w=problem.tasks["M"].windows[0]
        w.time_step=.5
        self.assertIs(planning_window(w).status,ExposureStatus.ERROR)
        w.planning_evidence=None
        self.assertIs(planning_window(w).status,ExposureStatus.INCONCLUSIVE)
        self.assertFalse(enumerate_task_candidates(problem,problem.tasks["M"]))
        source=scene["metadata"]["extra"]["window_generation"]["source_files_sha256"]
        source["utils/visibility.py"]="0"*64
        self.path.write_text(json.dumps(scene))
        loaded=load_scheduling_problem_from_json(self.path)
        self.assertIsNone(loaded.tasks["M"].windows[0].planning_evidence)

    def test_v2_threshold_comes_from_verified_lineage_not_embedded_claim(self):
        scene,_=fixture()
        scene["metadata"]["extra"]={"window_generation":window_generation_record(1.,70.,60.)}
        problem=self.load(scene)
        self.assertEqual(problem.tasks["M"].windows[0].planning_evidence["min_elevation_deg"],5.)

    def test_crossing_discontinuous_windows_rejected(self):
        scene,_=fixture(duration=4)
        w=scene["observation_windows"][0]["time_windows"][0]
        w["end_time"]=(START+timedelta(seconds=2)).isoformat()
        other=deepcopy(w);other["start_time"]=(START+timedelta(seconds=3)).isoformat()
        other["end_time"]=(START+timedelta(seconds=5)).isoformat()
        scene["observation_windows"][0]["time_windows"].append(other)
        problem=self.load(scene,"visibility_exit_refined_v3");task=problem.tasks["M"]
        self.assertFalse(enumerate_task_candidates(problem,task))
        w=task.windows[0];a=Assignment("M","S",w.start_time,w.start_time+timedelta(seconds=4),w.window_id,sensor_id="camera")
        self.assertFalse(ConstraintModel(problem).is_feasible_assignment(a,Schedule()))


class FormalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);scenes=self.root/"scenes";scenes.mkdir()
        self.settings=Settings(runtime_dir=self.root/"runtime",scenario_dir=scenes,
                               startup_timeout_s=5,transfer_timeout_s=5,stop_grace_s=.3)
        self.scene,self.plan=fixture()
        self.scene["metadata"]["extra"]={"window_generation":window_generation_record(1.,5.,60.)}
        self.path=scenes/"fixture.json";self.path.write_text(json.dumps(self.scene))
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.db=Database(self.settings.database_path)
        self.config=RunConfig(run_id=str(uuid.uuid4()),scenario_id="fixture",scenario_path=str(self.path),
                              scenario_sha256=self.sha,algorithm_id="completion_first",algorithm_version="test",created_at=now())
        self.controller=None

    def tearDown(self):
        if self.controller:self.controller.stop()

    def run_controller(self,status,forged=False,timeout=3):
        plan=deepcopy(self.plan)
        if forged:
            plan["continuous_verified"]=True
            plan["continuous_certification"]={"status":"CONTINUOUS_PASS","audit_version":"forged"}
        self.db.enqueue(self.config,max_queued=8)
        self.controller=controller_module.Controller(self.settings,self.db)
        auditor=lambda *a,**kw:_AuditFixture(status,**kw)
        with patch.object(controller_module,"worker_main",partial(_fixed_worker,plan)), patch(
                "utils.continuous_exposure.PlanExposureAuditor",side_effect=auditor), patch.object(
                controller_module,"VERIFICATION_TIMEOUT_S",timeout):
            with patch.object(self.db,"finish_success",wraps=self.db.finish_success) as success:
                self.controller.start()
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    record=self.db.get_run(self.config.run_id)
                    if record["status"] in {"FAILED","SUCCEEDED","TIMED_OUT","CANCELLED"}:break
                    time.sleep(.02)
                else:self.fail("Controller did not finish")
                self.controller.stop()
                self.assertEqual(success.call_count,1 if status=="PASS" else 0)
        return self.db.get_run(self.config.run_id)

    def assert_no_formal_plan(self,record):
        self.assertEqual(record["status"],"FAILED");self.assertIsNone(record["plan"])
        with self.db.connect() as db:
            for table in ("plans","assignments","metrics"):
                self.assertEqual(db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0],0)
        self.assertFalse(any(x["event_type"]=="SUCCEEDED" for x in record["events"]))

    def test_controller_fail_never_persists_success(self):
        r=self.run_controller("FAIL");self.assert_no_formal_plan(r)
        self.assertIn("REJECTED",r["error"]["message"])

    def test_controller_inconclusive_never_persists_success(self):
        r=self.run_controller("INCONCLUSIVE");self.assert_no_formal_plan(r)
        self.assertIn("INCONCLUSIVE",r["error"]["message"])

    def test_controller_exception_never_persists_success(self):
        self.assert_no_formal_plan(self.run_controller("exception"))

    def test_controller_timeout_and_late_pass_cannot_commit(self):
        r=self.run_controller("hang",timeout=.03);self.assert_no_formal_plan(r)
        self.assertIn("TIMEOUT",r["error"]["message"])
        time.sleep(.25)
        self.assert_no_formal_plan(self.db.get_run(self.config.run_id))

    def test_worker_forged_certification_ignored(self):
        self.assert_no_formal_plan(self.run_controller("INCONCLUSIVE",forged=True))

    def test_positive_unit_injection_reaches_real_transaction_and_export(self):
        r=self.run_controller("PASS",forged=True)
        self.assertEqual(r["status"],"SUCCEEDED");self.assertIsNotNone(r["plan"])
        self.assertEqual(r["continuous_certification"]["status"],"CONTINUOUS_PASS")
        self.assertNotIn("continuous_verified",r["plan"])
        exported=json.loads(render_json(r))
        self.assertEqual(exported["provenance"]["continuous_certification"]["evidence_kind"],"UNIT_TEST_INJECTION_ONLY")
        self.assertTrue(render_csv(r))
        self.assertTrue(self.db.get_replay_source(self.config.run_id)["plan_json"])
        # Even a copied JSON object with valid-looking fields is not a Storage capability.
        with self.assertRaises(ValueError):render_json(dict(r))
        changed=deepcopy(r["plan"]);changed["unassigned_tasks"].append("forged")
        with self.db.write() as db:
            raw=compact_json(changed)
            db.execute("UPDATE plans SET plan_json=?,plan_sha256=? WHERE run_id=?",
                (raw,hashlib.sha256(raw.encode()).hexdigest(),self.config.run_id))
        self.assertIsNone(self.db.get_run(self.config.run_id)["plan"])
        self.assertFalse(self.db.get_replay_source(self.config.run_id)["plan_json"])


    def test_storage_rejects_missing_forged_and_reused_receipt_atomically(self):
        self.db.enqueue(self.config,max_queued=8);attempt,_=self.db.start_attempt(self.config.run_id)
        self.db.set_verifying(self.config.run_id,attempt)
        metrics={}
        for receipt in [None,{"status":"CONTINUOUS_PASS"}]:
            with self.assertRaises(ValueError):
                self.db.finish_success(self.config.run_id,attempt,self.plan,metrics,.001,certification=receipt)
        receipt=storage_receipt(self.db,self.config.run_id,self.plan)
        changed=deepcopy(self.plan);changed["assignments"][0]["sat_end_time"]="2025-11-18T12:00:03Z"
        with self.assertRaises(ValueError):
            self.db.finish_success(self.config.run_id,attempt,changed,metrics,.001,certification=receipt)
        with self.db.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM plans").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM run_events WHERE event_type='CONTINUOUS_CERTIFIED'").fetchone()[0],0)
        with self.assertRaises(ValueError):
            self.db.record_system_event(self.config.run_id,attempt,"CONTINUOUS_CERTIFIED",{})

    def test_historical_succeeded_storage_api_and_file_exports_fail_closed(self):
        self.db.enqueue(self.config,max_queued=8);attempt,_=self.db.start_attempt(self.config.run_id)
        # Historical record in a TEMP database only; no certification event exists.
        with self.db.write() as db:
            raw=compact_json(self.plan)
            db.execute("INSERT INTO plans(run_id,attempt_no,scenario_id,plan_json,plan_sha256,verified_at) VALUES(?,?,?,?,?,?)",
                       (self.config.run_id,attempt,"fixture",raw,hashlib.sha256(raw.encode()).hexdigest(),now()))
            db.execute("UPDATE runs SET status='SUCCEEDED' WHERE run_id=?",(self.config.run_id,))
        r=self.db.get_run(self.config.run_id)
        self.assertEqual(r["status"],"SUCCEEDED");self.assertIsNone(r["plan"])
        self.assertIsNone(self.db.get_replay_source(self.config.run_id)["plan_json"])
        for render in (render_json,render_csv):
            with self.assertRaises(ValueError):render(r)
        output=self.root/"export";output.mkdir()
        config=self.config.model_copy(update={"output_kind":"directory","output_root":str(output)})
        with self.assertRaises(ValueError):persist_directory_exports(self.db,config)
        self.assertEqual(list(output.iterdir()),[])
        with self.assertRaises(ValueError):self.db.record_export(self.config.run_id,"json",b"forged")
        app=create_app(self.settings)
        from urllib.parse import urlsplit
        async def check(url):
            parts=urlsplit(url);messages=[]
            async def receive():return {"type":"http.request","body":b"","more_body":False}
            async def send(message):messages.append(message)
            scope={"type":"http","asgi":{"version":"3.0"},"http_version":"1.1",
                   "method":"GET","scheme":"http","path":parts.path,
                   "raw_path":parts.path.encode(),"query_string":parts.query.encode(),"headers":[],
                   "client":("127.0.0.1",0),"server":("127.0.0.1",80)}
            await app(scope,receive,send)
            status=next(m["status"] for m in messages if m["type"]=="http.response.start")
            data=b"".join(m.get("body",b"") for m in messages if m["type"]=="http.response.body")
            self.assertEqual(status,409);self.assertEqual(json.loads(data)["error"]["code"],"HTTP_409")
        try:
            for suffix in ("export?format=json","export?format=csv","visualization/schedule"):
                asyncio.run(check('/api/runs/'+self.config.run_id+'/'+suffix))
        finally:
            app.state.replay.close()

    def test_formal_verifier_keeps_missing_provenance_inconclusive(self):
        from eos_system.verification import verify_candidate
        scene=deepcopy(self.scene);scene["metadata"].pop("extra")
        self.path.write_text(json.dumps(scene));sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        config=self.config.model_copy(update={"scenario_sha256":sha})
        with self.assertRaises(ContinuousCertificationError) as error:
            verify_candidate(config,self.plan,.001)
        self.assertIs(error.exception.status,ExposureStatus.INCONCLUSIVE)
        self.assertIn("UNTRUSTED_WINDOW_PROVENANCE",str(error.exception))

    def test_real_certifier_missing_evidence_is_not_a_pass(self):
        scene=deepcopy(self.scene);scene["metadata"].pop("extra")
        self.path.write_text(json.dumps(scene));sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(ContinuousCertificationError) as error:
            certify_schedule(self.path,self.plan,run_id=self.config.run_id,scenario_sha=sha)
        self.assertIs(error.exception.status,ExposureStatus.INCONCLUSIVE)


class AdditionalEvidenceTests(unittest.TestCase):
    def test_ordinary_generation_records_precision_separately_from_certification(self):
        from types import SimpleNamespace
        from core.scenario import Scenario, ScenarioMetadata
        with tempfile.TemporaryDirectory() as directory:
            scene=Scenario.__new__(Scenario)
            scene.id="fixture";scene.scenario_type=SimpleNamespace(value="fixture")
            scene.metadata=ScenarioMetadata(name="fixture",creation_time=START,duration=60,time_step=1)
            scene.satellites=[];scene.missions=[];scene.ground_stations=[];scene.mission_info=SimpleNamespace()
            with patch("core.scenario.calculate_windows_orekit",return_value=([],[],[])):
                scene.calculate_visibility_windows()
            target=Path(directory)/"scene.json";scene.export_to_json(str(target))
            record=json.loads(target.read_bytes())["metadata"]["extra"]["window_generation"]
            self.assertEqual(record["window_algorithm_version"],"visibility_exit_refined_v3")
            self.assertEqual(record["exit_precision_us"],1)
            self.assertEqual(record["precision_scope"],"detected_exit_brackets_only")
            self.assertEqual(record["continuous_certification"]["status"],"NOT_RUN")

    def test_stale_completed_sidecar_cannot_fall_back_to_metadata(self):
        scene,_=fixture();scene["metadata"]["extra"]={"window_generation":window_generation_record(1.,5.,60.)}
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"scene.json";p.write_text(json.dumps(scene))
            d=p.parent/"provenance";d.mkdir()
            (d/(p.name+".provenance.json")).write_text(json.dumps(dict(scenario_sha256="0"*64,completion_status="complete")))
            self.assertIsNone(load_scheduling_problem_from_json(p).tasks["M"].windows[0].planning_evidence)
            sidecar=d/(p.name+".provenance.json")
            sidecar.write_bytes(b"x"*(1024*1024+1))
            self.assertIsNone(load_scheduling_problem_from_json(p).tasks["M"].windows[0].planning_evidence)
            sidecar.unlink();sidecar.symlink_to(p)
            self.assertIsNone(load_scheduling_problem_from_json(p).tasks["M"].windows[0].planning_evidence)
