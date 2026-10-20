"""从正式数据库记录生成下载内容和可选的服务器文件。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

from .contracts import RunConfig
from utils.continuous_exposure import validate_certification, CertifiedRecord, CertificationReceipt
from .storage import Database


def require_certified_record(record):
    if not record or record.get("status") != "SUCCEEDED" or record.get("plan") is None:
        raise ValueError("no continuously certified successful plan")
    receipt = getattr(record, "certification_receipt", None)
    if not isinstance(record, CertifiedRecord) or not isinstance(receipt, CertificationReceipt):
        raise ValueError("formal exports require a Storage-issued certified record")
    if receipt.evidence() != record.get("continuous_certification"):
        raise ValueError("record certification was modified")
    validate_certification(receipt.evidence(),run_id=record["run_id"],
        scenario_sha=record["config"]["scenario_sha256"],plan=record["plan"],
        context=getattr(record,"certification_context",None))


def require_exportable_record(record):
    """工程结果可导出且必须带采样标识；旧formal仍要求原连续凭据。"""
    from .planning_preview import PhysicalValidatedRecord, require_preview_record
    if isinstance(record, PhysicalValidatedRecord):
        require_preview_record(record)
        if record['config'].get('execution_mode') != 'physical_validation':
            raise ValueError('engineering record mode mismatch')
    else:
        require_certified_record(record)


def render_json(record: dict) -> bytes:
    """仅使用 Controller 已提交的计划与指标，不读取 Worker 临时结果。"""
    require_exportable_record(record)
    plan = dict(record["plan"])
    metric = record["metrics"]
    from .result_scoring import score_run
    plan['ranking_score'] = record.get('ranking_score') or score_run(record)
    plan['execution_resources'] = record.get('execution_resources') or next(
        (e['payload'] for e in reversed(record.get('events', []))
         if e['event_type'] == 'EXECUTION_RESOURCES'), None)
    plan["metrics"] = {
        "TP": metric["TP"], "TCR": metric["TCR"], "BD": metric["BD"],
        "TM": metric["TM"], "RT": metric["RT"], "RV": metric["RV"],
    }
    if record.get('result_kind') == 'physical_validation':
        plan['result_kind'] = 'physical_validation'
        plan['physical_validation'] = record['preview_validation']
    plan["provenance"] = {
        "run_id": record["run_id"],
        "continuous_certification": record["continuous_certification"],
        "source_id": record["config"].get("source_id", "runtime"),
        "scenario_sha256": record["config"]["scenario_sha256"],
        "algorithm_id": record["config"]["algorithm_id"],
        "algorithm_version": record["config"]["algorithm_version"],
        "seed": record["config"]["seed"],
        "scenario_provenance": record["config"].get("scenario_provenance", {}),
        "model_provenance": record["config"].get("model_provenance", {}),
    }
    return (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def render_csv(record: dict) -> bytes:
    require_exportable_record(record)
    output = io.StringIO(newline="")
    fields = ["run_id", "source_id", "scenario_id", "algorithm_id", "task_id", "satellite_id", "sensor_id",
              "sat_window_id", "orbit_number", "gs_window_id",
              "sat_start_time", "sat_end_time", "ground_station_id", "gs_start_time", "gs_end_time",
              "completed_tasks", "total_tasks", "TP", "TCR", "BD", "TM", "RT",
              "scenario_sha256", "scenario_physics_version", "parent_scenario_sha256", "algorithm_code_sha",
              "continuous_certification_status", "continuous_audit_version", "certified_plan_sha256", "result_kind", "physical_validation_status", "validated_plan_sha256", "validation_scope", "ranking_score", "ranking_policy"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    metrics = record["metrics"]
    certificate = record["continuous_certification"]
    from .result_scoring import score_run
    score = record.get('ranking_score') or score_run(record)
    base = {
        'ranking_score': score['value'] if score else None,
        'ranking_policy': score['policy'] if score else None,
        "continuous_certification_status":certificate["status"],
        "continuous_audit_version":certificate.get("audit_version", ""),
        "certified_plan_sha256":certificate.get("plan_sha256", ""),
        "result_kind":record.get('result_kind', 'formal'),
        "physical_validation_status":record.get('preview_validation', {}).get('status', ''),
        "validated_plan_sha256":record.get('preview_validation', {}).get('plan_sha256', ''),
        "validation_scope":record.get('preview_validation', {}).get('validation_scope', ''),
        "run_id": record["run_id"], "source_id": record["config"].get("source_id", "runtime"),
        "scenario_id": record["config"]["scenario_id"],
        "algorithm_id": record["config"]["algorithm_id"],
        "scenario_sha256": record["config"]["scenario_sha256"],
        "algorithm_code_sha": record["config"].get("algorithm_code_sha"),
        "scenario_physics_version": record["config"].get("scenario_provenance",{}).get("scenario_physics_version","legacy_unknown"),
        "parent_scenario_sha256": record["config"].get("scenario_provenance",{}).get("parent_scenario_sha256"),
        **{key: metrics[key] for key in ("completed_tasks", "total_tasks", "TP", "TCR", "BD", "TM", "RT")},
    }
    # 空计划也保留一行实验摘要，避免只得到 CSV 表头。
    for assignment in record["plan"]["assignments"] or [{}]:
        writer.writerow({key: value for key, value in {**base, **assignment}.items() if key in fields})
    return output.getvalue().encode("utf-8-sig")


def _write_immutable(path: Path, data: bytes) -> None:
    """同名正式文件若内容一致则复用；内容不同绝不覆盖。"""
    digest = hashlib.sha256(data).digest()
    if path.exists():
        if hashlib.sha256(path.read_bytes()).digest() != digest:
            raise FileExistsError(f"正式导出文件内容冲突：{path}")
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".pending-", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def persist_directory_exports(database: Database, config: RunConfig) -> None:
    """成功入库后按实验快照保存文件；写文件失败不撤销已核验的正式计划。"""
    if config.output_kind != "directory" or not config.output_root:
        return
    record = database.get_run(config.run_id)
    if record is None or record["status"] != "SUCCEEDED":
        raise ValueError("只有成功实验可保存正式导出")
    require_exportable_record(record)
    root = Path(config.output_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("实验选定的输出目录已不可用")
    run_dir = root / config.run_id
    run_dir.mkdir(exist_ok=True)
    for format_name, render in (("json", render_json), ("csv", render_csv)):
        try:
            content = render(record)
            target = run_dir / f"eos-{config.run_id}.{format_name}"
            _write_immutable(target, content)
            database.record_export(config.run_id, format_name, content, artifact_path=str(target))
        except (OSError, ValueError) as exc:
            database.record_export(config.run_id, format_name, None, error_message=str(exc)[:300])
