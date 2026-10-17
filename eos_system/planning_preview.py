"""Controller-owned sampled preview evidence, explicitly separate from certification."""
from dataclasses import dataclass
import hashlib
import json
import time
from pathlib import Path

from utils.continuous_exposure import (PlanExposureAuditor, plan_digest,
    ContinuousCertificationError, ExposureStatus)

PREVIEW_VERSION = 'sampled-planning-preview-v1'
_PREVIEW_ISSUER = object()


@dataclass(frozen=True)
class PreviewReceipt:
    evidence_json: str
    authority: object

    def evidence(self):
        if self.authority is not _PREVIEW_ISSUER:
            raise ValueError('untrusted preview receipt')
        return json.loads(self.evidence_json)


class PreviewRecord(dict):
    """Storage-issued preview; never a CertifiedRecord."""


def validate_preview(evidence, config, plan):
    if (config.get('execution_mode') != 'planning_preview'
            or not isinstance(evidence, dict)
            or evidence.get('status') != 'SAMPLED_PREVIEW'
            or evidence.get('preview_version') != PREVIEW_VERSION
            or evidence.get('run_id') != config['run_id']
            or evidence.get('scenario_sha256') != config['scenario_sha256']
            or evidence.get('plan_sha256') != plan_digest(plan)
            or evidence.get('completed_tasks') != len(plan['assignments'])):
        raise ValueError('preview evidence does not match this run and plan')
    return evidence


def audit_preview(config, official, *, deadline):
    """Use the actual Orekit predicate over every exposure; no continuity claim."""
    path = Path(config.scenario_path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != config.scenario_sha256:
        raise ValueError('preview scenario SHA changed')
    scene = json.loads(raw)
    settings = scene.get('metadata', {}).get('extra', {}).get('visibility_settings', {})
    minimum = float(settings.get('min_elevation_deg', 5.0))
    if official['assignments']:
        auditor = PlanExposureAuditor(scene, data_path=(Path(__file__).resolve().parents[1]/'utils/orekit-data.zip'),
                                      min_elevation_deg=minimum, step_s=.05)
        auditor.deadline = deadline
        result = auditor.audit(official)
        if len(result.get('rows', [])) != len(official['assignments']) or any(
                r.get('sampled_boundaries_status') != 'PASS' for r in result.get('rows', [])):
            raise ContinuousCertificationError(ExposureStatus.REJECTED,
                'PREVIEW_PHYSICS_CHECK_FAILED: ' + json.dumps(result.get('rows', []), ensure_ascii=False)[:1500])
    else:
        result = {'rows': [], 'reason': 'EMPTY_PREVIEW_PLAN'}
    if time.monotonic() >= deadline:
        raise ValueError('preview verification deadline exceeded')
    evidence = dict(status='SAMPLED_PREVIEW', preview_version=PREVIEW_VERSION,
        run_id=config.run_id, scenario_sha256=config.scenario_sha256,
        plan_sha256=plan_digest(official), completed_tasks=len(official['assignments']),
        step_s=.05, min_elevation_deg=minimum, audit_summary=result,
        warning='规划预览：已检查来源窗口、资源、转向及曝光全时段采样；未取得连续区间证明，不是正式认证计划。')
    return PreviewReceipt(json.dumps(evidence, ensure_ascii=False), _PREVIEW_ISSUER)


def require_preview_record(record):
    if not isinstance(record, PreviewRecord) or record.get('status') != 'SUCCEEDED' or not record.get('plan'):
        raise ValueError('a Storage-issued completed preview is required')
    validate_preview(record.get('preview_validation'), record['config'], record['plan'])


def preview_schedule(record):
    require_preview_record(record)
    return {**record['plan'], 'metrics': {k: record['metrics'][k] for k in ('TP','TCR','BD','TM','RT','RV')},
        'result_kind': 'planning_preview', 'preview_validation': record['preview_validation'],
        'provenance': {'run_id': record['run_id'], 'scenario_sha256': record['config']['scenario_sha256'],
            'execution_mode': 'planning_preview', 'continuous_certification': record['continuous_certification']}}
