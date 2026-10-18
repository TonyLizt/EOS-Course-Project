"""Controller-owned sampled preview evidence, explicitly separate from certification."""
from dataclasses import dataclass
import hashlib
import json
import time
import os
import shutil
import subprocess
import sys
import tempfile
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


class PhysicalValidatedRecord(PreviewRecord):
    """工程物理采样通过的存储记录，明确不是连续认证记录。"""


def validate_preview(evidence, config, plan):
    if (config.get('execution_mode') not in ('planning_preview', 'physical_validation')
            or not isinstance(evidence, dict)
            or evidence.get('status') != ('SAMPLED_PHYSICAL_PASS' if config.get('execution_mode') == 'physical_validation' else 'SAMPLED_PREVIEW')
            or evidence.get('preview_version') != PREVIEW_VERSION
            or evidence.get('run_id') != config['run_id']
            or evidence.get('scenario_sha256') != config['scenario_sha256']
            or evidence.get('plan_sha256') != plan_digest(plan)
            or evidence.get('completed_tasks') != len(plan['assignments'])):
        raise ValueError('preview evidence does not match this run and plan')
    return evidence


def _audit_preview_local(config, official, *, deadline, data_path):
    """Use the actual Orekit predicate over every exposure; no continuity claim."""
    path = Path(config.scenario_path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != config.scenario_sha256:
        raise ValueError('preview scenario SHA changed')
    scene = json.loads(raw)
    settings = scene.get('metadata', {}).get('extra', {}).get('visibility_settings', {})
    minimum = float(settings.get('min_elevation_deg', 5.0))
    if official['assignments']:
        auditor = PlanExposureAuditor(scene, data_path=data_path,
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
    evidence = dict(status=('SAMPLED_PHYSICAL_PASS' if config.execution_mode == 'physical_validation' else 'SAMPLED_PREVIEW'), preview_version=PREVIEW_VERSION,
        run_id=config.run_id, scenario_sha256=config.scenario_sha256,
        plan_sha256=plan_digest(official), completed_tasks=len(official['assignments']),
        step_s=.05, min_elevation_deg=minimum, audit_summary=result,
        validation_scope='Orekit full-exposure 0.05s sampled physics; not a continuous interval proof',
        warning='已检查来源窗口、资源、转向及曝光全时段采样；未取得连续区间证明。')
    return PreviewReceipt(json.dumps(evidence, ensure_ascii=False), _PREVIEW_ISSUER)


def audit_preview(config, official, *, deadline):
    """由 Controller 启动隔离核验；JVM 超时可回收，不占用下一次核验。"""
    source = Path(os.environ.get('EOS_OREKIT_DATA') or
                  Path(__file__).resolve().parents[1] / 'utils/orekit-data.zip')
    # 空计划不需要启动 JVM；仍检查场景 SHA、截止时间和预览身份。
    if not official['assignments']:
        return _audit_preview_local(config, official, deadline=deadline, data_path=source)
    # 临时目录归父进程所有：子进程被限时终止后也能清理；不向仓库写缓存。
    with tempfile.TemporaryDirectory(prefix='eos-preview-data-') as directory:
        local = Path(directory) / 'orekit-data.zip'
        shutil.copyfile(source, local)
        if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(local.read_bytes()).digest():
            raise ValueError('Orekit 临时数据包与原包 SHA 不符')
        # 留出回收和凭据检查时间，早于 Controller 外层期限终止子进程。
        remaining = deadline - time.monotonic() - .5
        if remaining <= 0:
            raise ContinuousCertificationError(ExposureStatus.ERROR, 'PREVIEW_VERIFICATION_TIMEOUT')
        payload = dict(config=config.model_dump(mode='json'), plan=official,
                       deadline=deadline, data_path=str(local))
        try:
            completed = subprocess.run(
                [sys.executable, '-B', '-m', 'eos_system.preview_audit_process'],
                input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
                timeout=remaining, check=False,
                cwd=Path(__file__).resolve().parents[1])
        except subprocess.TimeoutExpired as exc:
            # subprocess.run 会 kill 并 wait；临时副本随后由上下文管理器删除。
            raise ContinuousCertificationError(ExposureStatus.ERROR, 'PREVIEW_VERIFICATION_TIMEOUT') from exc
        if completed.returncode != 0:
            raise ContinuousCertificationError(ExposureStatus.ERROR,
                'PREVIEW_VERIFIER_PROCESS_FAILED: ' + completed.stderr[-1500:])
        try:
            response = json.loads(completed.stdout)
        except (ValueError, TypeError) as exc:
            raise ContinuousCertificationError(ExposureStatus.ERROR, 'PREVIEW_INVALID_RESPONSE') from exc
        if response.get('error'):
            try:
                status = ExposureStatus(response['status'])
            except (KeyError, ValueError):
                status = ExposureStatus.ERROR
            raise ContinuousCertificationError(status, response['error'])
        evidence = response.get('evidence')
        # 子进程是 Controller 自己的核验入口，不接收 Worker 伪造的“成功凭据”。
        # 跨进程只传普通数据，预览凭据必须由父进程绑定当前配置和计划后签发。
        validate_preview(evidence, config.model_dump(), official)
        if time.monotonic() >= deadline:
            raise ContinuousCertificationError(ExposureStatus.ERROR, 'PREVIEW_VERIFICATION_TIMEOUT')
        return PreviewReceipt(json.dumps(evidence, ensure_ascii=False), _PREVIEW_ISSUER)


def require_preview_record(record):
    if not isinstance(record, PreviewRecord) or record.get('status') != 'SUCCEEDED' or not record.get('plan'):
        raise ValueError('a Storage-issued completed preview is required')
    validate_preview(record.get('preview_validation'), record['config'], record['plan'])


def preview_schedule(record):
    require_preview_record(record)
    return {**record['plan'], 'metrics': {k: record['metrics'][k] for k in ('TP','TCR','BD','TM','RT','RV')},
        'result_kind': record['config'].get('execution_mode', 'planning_preview'), 'preview_validation': record['preview_validation'],
        'provenance': {'run_id': record['run_id'], 'scenario_sha256': record['config']['scenario_sha256'],
            'execution_mode': record['config'].get('execution_mode', 'planning_preview'), 'continuous_certification': record['continuous_certification']}}
