"""UNIT TEST INJECTION ONLY. No real physical certificate is issued here.

Complete identities preserve positive lifecycle/storage coverage. Nothing in
HTTP, Worker JSON or production configuration can install this Python fixture.
"""
import json
import time
from utils.continuous_exposure import (CertificationReceipt, _ISSUER, AUDIT_VERSION,
    plan_digest, certification_context, _RUNTIME)


def unit_receipt(run_id, scenario_sha, plan, *, context=None):
    context=certification_context(context)
    runtime=getattr(_RUNTIME,"value",None)
    evidence=dict(status="CONTINUOUS_PASS",receipt_schema_version=3,run_id=run_id,
        scenario_sha256=scenario_sha,plan_sha256=plan_digest(plan),audit_version=AUDIT_VERSION,
        **context.identity(),deadline_monotonic=runtime[0] if runtime else time.monotonic()+30,
        scan_step_s=.05,boundary_precision_us=1,min_elevation_deg=5.,
        predicate="UNIT_TEST_ONLY",certified_tasks=len(plan.get("assignments",[])),
        audit_result_sha256=plan_digest({"UNIT_TEST_INJECTION_ONLY":True}),
        evidence_kind="UNIT_TEST_INJECTION_ONLY")
    evidence["settings_sha256"]=plan_digest({key:evidence[key] for key in
        ("scan_step_s","boundary_precision_us","predicate","min_elevation_deg","model_parameters")})
    return CertificationReceipt(json.dumps(evidence,sort_keys=True),_ISSUER)


def unit_certify(path, plan, *, run_id, scenario_sha, **kwargs):
    return unit_receipt(run_id,scenario_sha,plan)


def storage_receipt(database, run_id, plan):
    return unit_receipt(run_id,database.get_run(run_id)["config"]["scenario_sha256"],plan,
                        context=database.expected_certification_context())
