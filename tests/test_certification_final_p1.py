"""Final P1 regression: deterministic clocks, real SQLite, complete identities.

All positive receipts/auditors are explicitly UNIT_TEST_INJECTION_ONLY. Frozen
acceptance files are never opened for writing or passed to a solver.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_continuous_pipeline as pipeline
from certification_fixtures import storage_receipt, unit_receipt
import eos_system.controller as controller_module
from eos_system.storage import Database
import utils.continuous_exposure as ce
import utils.certification_identity as identity


class Fixture(unittest.TestCase):
    def setUp(self):
        # Source fault tests latch production revocation. Isolate that process
        # state per test, just as each real deployment requires a fresh process.
        latch=patch.object(identity,"_INVALIDATED_REASON",None);latch.start();self.addCleanup(latch.stop)
        pipeline.FormalPipelineTests.setUp(self)
        self.db.enqueue(self.config,max_queued=8)
        self.attempt,_=self.db.start_attempt(self.config.run_id)
        self.assertTrue(self.db.set_verifying(self.config.run_id,self.attempt))
        self.context=self.db.expected_certification_context()
        self.receipt=storage_receipt(self.db,self.config.run_id,self.plan)
        self.metrics=dict(completed_tasks=1,total_tasks=1,task_profit=1,task_completion_rate=1,
            balance_degree=1,timeliness_metric=1,runtime_efficiency=.001,robustness_variance=0,mip_gap=None)

    def assert_empty(self):
        with self.db.connect() as db:
            for table in ("plans","assignments","metrics"):
                self.assertEqual(db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM run_events WHERE event_type IN ('CONTINUOUS_CERTIFIED','SUCCEEDED')").fetchone()[0],0)

    def finish(self,**kwargs):
        return self.db.finish_success(self.config.run_id,self.attempt,self.plan,self.metrics,.001,
                                      certification=self.receipt,**kwargs)


class DeadlineTests(Fixture):
    def exercise(self,*,get_at=1,created_at=0,validated_at=1):
        clock=[0.]
        owner=controller_module.Controller(self.settings,self.db)
        supplied=(True,(self.plan,self.metrics,self.receipt))
        class Thread:
            def __init__(self,**kwargs):pass
            def start(self):pass
        class Queue:
            gets=0
            def __init__(self,**kwargs):clock[0]=created_at
            def get(self,**kwargs):
                Queue.gets+=1;clock[0]=get_at;return supplied
        real=ce.validate_certification
        def validate(*args,**kwargs):
            result=real(*args,**kwargs);clock[0]=validated_at;return result
        with patch.object(controller_module.threading,"Thread",Thread), patch.object(
                controller_module.queue,"Queue",Queue), patch("time.monotonic",side_effect=lambda:clock[0]), patch.object(
                controller_module,"validate_certification",side_effect=validate), patch.object(
                controller_module,"VERIFICATION_TIMEOUT_S",30):
            result=owner._verify_with_deadline(self.config,self.plan,.001)
        return result,Queue.gets

    def test_before_deadline_can_continue(self):
        result,gets=self.exercise()
        self.assertEqual(result[:3],(self.plan,self.metrics,self.receipt));self.assertEqual(result[3],30)
        self.assertEqual(gets,1)

    def test_expired_before_wait_does_not_read_ready_queue(self):
        with self.assertRaisesRegex(ce.ContinuousCertificationError,"TIMEOUT"):
            self.exercise(created_at=30)
        self.assert_empty()

    def test_already_queued_pass_retrieved_after_deadline_rejected(self):
        with self.assertRaisesRegex(ce.ContinuousCertificationError,"TIMEOUT"):
            self.exercise(get_at=30)
        self.assert_empty()

    def test_expiry_during_credential_validation_rejected(self):
        with self.assertRaisesRegex(ce.ContinuousCertificationError,"TIMEOUT"):
            self.exercise(validated_at=30)
        self.assert_empty()

    def test_expired_between_validation_and_success_transaction(self):
        with patch("time.monotonic",return_value=30),self.assertRaisesRegex(ce.ContinuousCertificationError,"TIMEOUT"):
            self.finish(deadline=30)
        self.assertEqual(self.db.get_status(self.config.run_id)["status"],"VERIFYING");self.assert_empty()

    def test_expiry_inside_transaction_rolls_back_every_result_table(self):
        clock=[0.];original=self.db._event
        def event(*args,**kwargs):
            result=original(*args,**kwargs)
            if args[5]=="SUCCEEDED":clock[0]=30
            return result
        with patch("time.monotonic",side_effect=lambda:clock[0]),patch.object(self.db,"_event",side_effect=event):
            with self.assertRaisesRegex(ce.ContinuousCertificationError,"TIMEOUT"):self.finish(deadline=30)
        self.assert_empty();self.assertEqual(self.db.get_status(self.config.run_id)["status"],"VERIFYING")

    def test_late_pass_cannot_replace_timeout_terminal(self):
        self.db.finish_failure(self.config.run_id,self.attempt,"FAILED","CONTINUOUS_ERROR","CERTIFICATION_TIMEOUT")
        self.assertFalse(self.finish())
        self.assertEqual(self.db.get_run(self.config.run_id)["error"]["message"],"CERTIFICATION_TIMEOUT");self.assert_empty()


class CancellationTests(Fixture):
    def cancelled_failure(self,reason):
        self.assertEqual(self.db.request_cancel(self.config.run_id),("VERIFYING",True))
        self.db.finish_failure(self.config.run_id,self.attempt,"FAILED","CONTINUOUS_"+reason,reason)
        r=self.db.get_run(self.config.run_id)
        self.assertEqual(r["status"],"CANCELLED")
        self.assertEqual(r["error"]["code"],"CANCELLED_DURING_VERIFY")
        self.assertTrue(any(e["event_type"]=="CERTIFICATION_FAILURE_AFTER_CANCEL" and
            e["payload"]["message"]==reason for e in r["events"]))
        with self.db.connect() as db:
            self.assertEqual(db.execute("SELECT outcome FROM run_attempts").fetchone()[0],"CANCELLED")
        self.assert_empty()

    def test_accepted_cancel_beats_inconclusive(self):self.cancelled_failure("INCONCLUSIVE")
    def test_accepted_cancel_beats_rejected(self):self.cancelled_failure("REJECTED")
    def test_accepted_cancel_beats_error(self):self.cancelled_failure("ERROR")
    def test_accepted_cancel_beats_certification_timeout(self):self.cancelled_failure("CERTIFICATION_TIMEOUT")

    def ordered_transactions(self,cancel_first):
        other=Database(self.settings.database_path)
        entered=threading.Event();release=threading.Event();started=threading.Event();errors=[];results=[]
        first=self.db;second=other
        original=first._event
        def hold(*args,**kwargs):
            value=original(*args,**kwargs);entered.set()
            if not release.wait(5):raise RuntimeError("test transaction release timed out")
            return value
        def cancel(db):return db.request_cancel(self.config.run_id)
        def failure(db):return db.finish_failure(self.config.run_id,self.attempt,"FAILED","CONTINUOUS_ERROR","unit failure")
        def invoke(action,db,mark=False):
            try:
                if mark:started.set()
                results.append(action(db))
            except BaseException as exc:errors.append(exc)
        with patch.object(first,"_event",side_effect=hold):
            a=threading.Thread(target=invoke,args=(cancel if cancel_first else failure,first))
            b=threading.Thread(target=invoke,args=(failure if cancel_first else cancel,second,True))
            a.start();self.assertTrue(entered.wait(5));b.start();self.assertTrue(started.wait(5))
            release.set();a.join(5);b.join(5)
            self.assertFalse(a.is_alive());self.assertFalse(b.is_alive())
        self.assertEqual(errors,[])
        self.assertEqual(self.db.get_run(self.config.run_id)["status"],"CANCELLED" if cancel_first else "FAILED")
        if not cancel_first:self.assertIn(("FAILED",False),results)
        self.assert_empty()

    def test_cancel_transaction_commits_before_failure_transaction(self):self.ordered_transactions(True)
    def test_failure_transaction_commits_before_cancel_transaction(self):self.ordered_transactions(False)

    def test_cancel_terminal_rejects_late_success(self):
        self.cancelled_failure("ERROR");self.assertFalse(self.finish());self.assert_empty()

    def test_no_cancel_normal_failure_retained(self):
        self.db.finish_failure(self.config.run_id,self.attempt,"FAILED","CONTINUOUS_INCONCLUSIVE","missing proof")
        self.assertEqual(self.db.get_run(self.config.run_id)["status"],"FAILED");self.assert_empty()

    def test_stop_and_search_timeout_priorities_preserved(self):
        self.db.request_cancel(self.config.run_id)
        self.db.finish_failure(self.config.run_id,self.attempt,"FAILED","CONTROLLER_STOP","stop")
        self.assertEqual(self.db.get_run(self.config.run_id)["error"]["code"],"CONTROLLER_STOP")
        self.db.finish_failure(self.config.run_id,self.attempt,"CANCELLED","late","late")
        self.assertEqual(self.db.get_run(self.config.run_id)["status"],"FAILED")


class DataIdentityTests(Fixture):
    def validate(self,evidence,**kwargs):
        return ce.validate_certification(evidence,run_id=self.config.run_id,scenario_sha=self.sha,
                                        plan=self.plan,context=kwargs.get("context",self.context))

    def test_complete_context_matching_positive(self):
        self.assertEqual(self.validate(self.receipt.evidence())["orekit_data_sha256"],self.context.data_sha256)
        self.assertTrue(self.finish());self.assertIsNotNone(self.db.get_run(self.config.run_id)["plan"])

    def test_complete_empty_unit_plan_receipt_preserves_lifecycle_contract(self):
        # A complete zero-count UNIT TEST receipt is not a certificate for any
        # nonempty exposure. Real certify_schedule still requires certified rows.
        plan=deepcopy(self.plan);plan["assignments"]=[]
        receipt=unit_receipt(self.config.run_id,self.sha,plan,context=self.context)
        result=ce.validate_certification(receipt.evidence(),run_id=self.config.run_id,
            scenario_sha=self.sha,plan=plan,context=self.context)
        self.assertEqual(result["certified_tasks"],0)
        with self.assertRaises(ce.ContinuousCertificationError):self.validate(receipt.evidence())

    def test_missing_orekit_sha_rejected(self):
        e=self.receipt.evidence();del e["orekit_data_sha256"]
        with self.assertRaises(ce.ContinuousCertificationError):self.validate(e)

    def test_wrong_orekit_sha_rejected(self):
        e=self.receipt.evidence();e["orekit_data_sha256"]="f"*64
        with self.assertRaises(ce.ContinuousCertificationError):self.validate(e)

    def test_malformed_sha_and_missing_schema_fields_rejected(self):
        for value in (None,123,True,"",[],"F"*64,"z"*64,"a"*63,"a"*65):
            e=self.receipt.evidence();e["orekit_data_sha256"]=value
            with self.subTest(value=value),self.assertRaises(ce.ContinuousCertificationError):self.validate(e)
        for field in ("orekit_data_source","receipt_schema_version","process_generation","deployment_sha256",
                      "model_parameters","scan_step_s","audit_result_sha256","certified_tasks","deadline_monotonic"):
            e=self.receipt.evidence();del e[field]
            with self.subTest(field=field),self.assertRaises(ce.ContinuousCertificationError):self.validate(e)

    def test_scene_plan_version_and_dataset_combinations_rejected(self):
        for field,value in (("scenario_sha256","f"*64),("plan_sha256","f"*64),("run_id","other"),
                            ("audit_version","continuous_exposure_audit_v2"),("orekit_data_source","file:///other"),
                            ("model_parameters",{"propagation":"other"}),("min_elevation_deg",6.),
                            ("process_generation","0"*32),("deployment_sha256","0"*64)):
            e=self.receipt.evidence();e[field]=value
            with self.subTest(field=field),self.assertRaises(ce.ContinuousCertificationError):self.validate(e)

    def test_data_changed_after_freeze_not_silently_reaccepted(self):
        path=self.root/"dataset.zip";path.write_bytes(b"A")
        context=identity.trusted_context(path)
        receipt=unit_receipt(self.config.run_id,self.sha,self.plan,context=context)
        path.write_bytes(b"B")
        with self.assertRaises(ce.ContinuousCertificationError):self.validate(receipt.evidence(),context=context)
        with self.assertRaises(ValueError):identity.trusted_context(path)

    def test_detected_data_change_remains_revoked_after_restore(self):
        path=self.root/"latched.zip";path.write_bytes(b"A");context=identity.trusted_context(path)
        path.write_bytes(b"B")
        with self.assertRaises(ValueError):context.check()
        path.write_bytes(b"A")
        with self.assertRaises(ValueError):context.check()

    def test_storage_rejects_changed_dataset_receipt_atomically(self):
        evidence=self.receipt.evidence();evidence["orekit_data_sha256"]="f"*64
        self.receipt=ce.CertificationReceipt(json.dumps(evidence),ce._ISSUER)
        with self.assertRaises(ce.ContinuousCertificationError):self.finish()
        self.assert_empty()

    def test_unreadable_data_fails_closed(self):
        path=self.root/"dataset.zip";path.write_bytes(b"A");context=identity.trusted_context(path)
        receipt=unit_receipt(self.config.run_id,self.sha,self.plan,context=context);path.unlink()
        with self.assertRaises(ce.ContinuousCertificationError):self.validate(receipt.evidence(),context=context)

    def test_data_change_during_real_signing_path_rejected(self):
        path=self.root/"dataset.zip";path.write_bytes(b"A");context=identity.trusted_context(path)
        class Auditor:
            def __init__(self,*args,**kwargs):pass
            def audit(self,plan):
                path.write_bytes(b"B")
                return dict(status="PASS",rows=[dict(status="PASS",reason="CERTIFIED_INTERVAL")],
                    orekit_data_sha256=context.data_sha256,model="UNIT_TEST_INJECTION_ONLY",
                    scan_step_s=.05,boundary_precision_us=1,predicate="UNIT_TEST_ONLY")
        with self.assertRaisesRegex(ce.ContinuousCertificationError,"IDENTITY_INVALID"):
            ce.certify_schedule(self.path,self.plan,run_id=self.config.run_id,scenario_sha=self.sha,
                                context=context,auditor_factory=Auditor,min_elevation_deg=5.)

    def test_legacy_receipt_never_certified(self):
        e={k:self.receipt.evidence()[k] for k in ("status","run_id","scenario_sha256","plan_sha256","audit_version","source_files_sha256")}
        with self.assertRaises(ce.ContinuousCertificationError):self.validate(e)

    def test_storage_read_source_oserror_hides_plan_not_http500(self):
        self.assertTrue(self.finish())
        with patch.object(identity,"disk_sources",side_effect=OSError("unit unreadable source")):
            r=self.db.get_run(self.config.run_id)
            self.assertIsNone(r["plan"]);self.assertEqual(r["continuous_certification"]["status"],"INCONCLUSIVE")
            from eos_system.exporting import render_json
            with self.assertRaises(ValueError):render_json(r)


class ProcessIdentityTests(Fixture):
    def test_process_deployment_and_disk_agree(self):
        self.assertEqual(ce.source_identity(),dict(self.context.source_files))
        self.assertEqual(ce.validate_certification(self.receipt.evidence(),run_id=self.config.run_id,
            scenario_sha=self.sha,plan=self.plan,context=self.context)["process_generation"],self.context.process_generation)

    def test_disk_changed_during_certification_rejected(self):
        class Auditor:
            def __init__(self,*args,**kwargs):pass
            def audit(inner,plan):
                bad=list(identity._SOURCES);bad[0]=(bad[0][0],"0"*64)
                self.changed=patch.object(identity,"disk_sources",return_value=tuple(bad));self.changed.start()
                return dict(status="PASS",rows=[dict(status="PASS",reason="CERTIFIED_INTERVAL")],
                    orekit_data_sha256=self.context.data_sha256,model="UNIT_TEST_INJECTION_ONLY",
                    scan_step_s=.05,boundary_precision_us=1,predicate="UNIT_TEST_ONLY")
        try:
            with self.assertRaisesRegex(ce.ContinuousCertificationError,"RESTART_REQUIRED"):
                ce.certify_schedule(self.path,self.plan,run_id=self.config.run_id,scenario_sha=self.sha,
                    min_elevation_deg=5.,context=self.context,auditor_factory=Auditor)
        finally:
            if hasattr(self,"changed"):self.changed.stop()

    def test_source_unreadable_before_issuing_rejected(self):
        with patch.object(identity,"disk_sources",side_effect=OSError("unit unavailable")):
            with self.assertRaisesRegex(ce.ContinuousCertificationError,"IDENTITY_INVALID"):
                ce.validate_certification(self.receipt.evidence(),run_id=self.config.run_id,scenario_sha=self.sha,
                    plan=self.plan,context=self.context)

    def test_observed_source_change_stays_revoked_after_restore(self):
        bad=list(identity._SOURCES);bad[0]=(bad[0][0],"0"*64)
        with patch.object(identity,"disk_sources",return_value=tuple(bad)):
            with self.assertRaises(ValueError):identity.assert_code_current()
        with self.assertRaises(ValueError):identity.assert_code_current()

    def test_context_from_other_generation_rejected(self):
        other=replace(self.context,process_generation="other-process")
        with self.assertRaises(ce.ContinuousCertificationError):ce.certification_context(other)

    def test_real_other_process_cannot_reuse_receipt(self):
        script='''import json,sys
from utils.continuous_exposure import validate_certification,ContinuousCertificationError
e=json.load(sys.stdin)
try:validate_certification(e["evidence"],run_id=e["run"],scenario_sha=e["sha"],plan=e["plan"])
except ContinuousCertificationError:print("REJECTED_OTHER_PROCESS")
else:raise SystemExit("old process receipt was reused")
'''
        result=subprocess.run([sys.executable,"-B","-c",script],input=json.dumps(dict(evidence=self.receipt.evidence(),
            run=self.config.run_id,sha=self.sha,plan=self.plan)),capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn("REJECTED_OTHER_PROCESS",result.stdout)

    def isolated_sources(self,script):
        root=self.root/"deployment";root.mkdir()
        for name in identity.SOURCE_NAMES:
            dst=root/name;dst.parent.mkdir(exist_ok=True,parents=True);dst.write_bytes((identity.ROOT/name).read_bytes())
            (dst.parent/"__init__.py").touch()
        env=dict(os.environ);env.pop("PYTHONPATH",None)
        result=subprocess.run([sys.executable,"-B","-c",script],cwd=root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_loaded_A_then_disk_B_rejected_and_new_process_required(self):
        self.isolated_sources('''from pathlib import Path
from utils.continuous_exposure import source_identity
p=Path("utils/time_parsing.py");p.write_bytes(p.read_bytes()+b"\\n# deployment B\\n")
try:source_identity()
except ValueError:pass
else:raise SystemExit("loaded A accepted disk B")
''')

    def test_module_loaded_A_before_bootstrap_disk_B_rejected(self):
        self.isolated_sources('''from pathlib import Path
import utils.time_parsing
p=Path("utils/time_parsing.py");raw=p.read_bytes();assert b"raise ValueError(" in raw
p.write_bytes(raw.replace(b"raise ValueError(",b"raise RuntimeError("))
from utils.certification_identity import source_identity
try:source_identity()
except ValueError:pass
else:raise SystemExit("bootstrap accepted already loaded A against B")
''')

    def test_preloaded_transition_with_set_constants_matches_same_source(self):
        self.isolated_sources('''import schedulers.transition_utils
from utils.certification_identity import source_identity
assert source_identity()["schedulers/transition_utils.py"]
''')

    def test_initializing_module_compiled_A_disk_B_rejected(self):
        self.isolated_sources('''import builtins
from pathlib import Path
original=builtins.__import__
def intercept(name,*args,**kwargs):
    if name=="utils.certification_identity":
        p=Path("utils/continuous_exposure.py")
        raw=p.read_bytes();assert b'continuous_exposure_audit_v3' in raw
        p.write_bytes(raw.replace(b'continuous_exposure_audit_v3',b'continuous_exposure_audit_DIFFERENT'))
    return original(name,*args,**kwargs)
builtins.__import__=intercept
import utils.continuous_exposure as ce
try:ce.source_identity()
except ValueError:pass
else:raise SystemExit("initializing compiled A accepted disk B")
''')

    def test_new_deployment_new_process_old_receipt_invalid(self):
        self.isolated_sources('''from pathlib import Path
import subprocess,sys
from utils.certification_identity import source_identity
old=source_identity()
p=Path("utils/time_parsing.py");p.write_bytes(p.read_bytes()+b"\\n# deployment B\\n")
result=subprocess.run([sys.executable,"-B","-c","from utils.certification_identity import source_identity; print(source_identity())"],capture_output=True,text=True)
assert result.returncode==0,result.stderr
assert repr(old)!=result.stdout.strip(),"new process retained old deployment"
''')


if __name__=="__main__":unittest.main()
