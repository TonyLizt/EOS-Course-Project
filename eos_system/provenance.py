"""场景来源的最小接入：读取外部证据，不补写或改造原场景。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

def sidecar_path(scene: Path) -> Path:
    return scene.parent / "provenance" / (scene.name + ".provenance.json")

def capture_provenance(scene: Path, scenario_sha: str) -> dict:
    """Legacy 允许流程演示；E2 candidate 不能通过目录登记自动变成正式数据。"""
    sidecar = sidecar_path(scene)
    if not sidecar.exists():
        if "epoch_fixed_v1" in scene.name:
            raise ValueError("修复场景缺少匹配的来源与正式验收记录")
        return {"scenario_physics_version":"legacy_unknown", "provenance_status":"unknown",
                "scenario_sha256":scenario_sha, "parent_scenario_sha256":None,
                "warning":"历史生成版本与物理验收未证实；不得混入修复模型的正式比较"}
    if sidecar.is_symlink() or sidecar.stat().st_size > 1024*1024:
        raise ValueError("来源记录必须是小于 1 MiB 的普通文件")
    raw = sidecar.read_bytes()
    evidence = json.loads(raw)
    if not isinstance(evidence,dict) or not isinstance(evidence.get("physical_validation", {}),dict):
        raise ValueError("场景来源记录结构无效")
    if evidence.get("scenario_sha256") != scenario_sha or evidence.get("completion_status") != "complete":
        raise ValueError("场景来源记录的哈希或完成标记不匹配")
    if evidence.get('artifact_kind') == 'fresh_generated_shared_v1':
        # 新任务来源没有父场景；生成可信度与连续认证分开，不伪造正式发布PASS。
        from utils.continuous_exposure import planning_evidence
        lineage = planning_evidence({'metadata': {}}, scene, scenario_sha)
        physical = evidence.get('physical_validation', {})
        if (lineage is None or evidence.get('provenance_status') != 'verified_generation'
                or physical.get('status') != 'SAMPLED_PASS'
                or physical.get('continuous_status') != 'INCONCLUSIVE'
                or evidence.get('publication_status') != 'development'
                or evidence.get('formal_release_eligible') is not False
                or not evidence.get('lineage_group_id')):
            raise ValueError('新场景缺少匹配的生成来源/采样检查记录')
        return {key: evidence.get(key) for key in (
            'scenario_physics_version','epoch_parser_version','propagation_version',
            'parent_scenario_sha256','scenario_sha256','provenance_status','lineage_group_id')} | {
            'sidecar_sha256': hashlib.sha256(raw).hexdigest(),
            'attitude_model_version': lineage['attitude_model_version'],
            'physical_validation_status': 'SAMPLED_PASS',
            'continuous_certification_status': 'INCONCLUSIVE',
            'publication_status': 'development'}
    if (evidence.get("publication_status") == "candidate_only"
            or evidence.get("formal_release_eligible") is not True
            or evidence.get("physical_validation", {}).get("status") != "PASS"):
        raise ValueError("该场景仍是待验收候选，请先完成 E3/E4 正式发布")
    for key in ("scenario_physics_version","epoch_parser_version","propagation_version"):
        if not isinstance(evidence.get(key),str) or not evidence[key]:
            raise ValueError("正式修复场景缺少版本字段："+key)
    parent = evidence.get("parent_scenario_sha256")
    if not isinstance(parent,str) or not re.fullmatch("[0-9a-f]{64}",parent):
        raise ValueError("修复场景缺少可追溯的父场景 SHA-256")
    return {key:evidence.get(key) for key in (
        "scenario_physics_version","epoch_parser_version","propagation_version",
        "parent_scenario_sha256","scenario_sha256","registry_id","provenance_status")} | {
        "sidecar_sha256":hashlib.sha256(raw).hexdigest(), "physical_validation_status":"PASS",
        "attitude_model_version": (
            "target_pointing_inertial_euler_v1" if evidence.get('scenario_physics_version') == 'epoch_fixed_v1'
            and evidence.get('source_files_sha256', {}).get('utils/visibility.py') ==
                '6a0a6bb58076f26667318521affa2c51eda1ad64fae94114d52035b4ff5db177'
            else None)}

def verify_provenance(config) -> None:
    """运行与独立核验都复查提交时的 sidecar，不接受提交后替换来源文件。"""
    from algorithms.objective_adapters.protocol import verify_adapter, validate_model_request
    verify_adapter(config)
    if config.objective_adapter and config.algorithm_id in ('ppo', 'lavis'):
        validate_model_request(config.algorithm_id, config, config.model_provenance)
    if config.algorithm_id == 'lavis':
        from algorithms.lavis.model import verify_snapshot
        verify_snapshot(config.model_provenance)
    if config.algorithm_id == 'ppo':
        from algorithms.ppo.model import verify_snapshot
        from algorithms.ppo.protocol import validate_request, validate_scene
        verify_snapshot(config.model_provenance)
        if config.model_provenance['model_id'] != config.algorithm_params.get('model_id', 'ppo-v1'):
            raise ValueError('PPO_MODEL_ID_MISMATCH')
        if not config.objective_adapter:
            validate_request(config, config.model_provenance)
        raw_scene = json.loads(Path(config.scenario_path).read_bytes())
        if raw_scene.get('ground_stations'):
            raise ValueError('PPO_MODEL_DOMAIN_MISMATCH: ground stations unsupported')
        validate_scene(raw_scene, config.scenario_provenance, config.model_provenance)
    snapshot = config.scenario_provenance
    if snapshot.get("provenance_status") == "development_planning_only":
        if config.execution_mode != "planning_preview":
            raise ValueError("development source is not eligible for formal execution")
        if capture_development_provenance(Path(config.scenario_path), config.scenario_sha256) != snapshot:
            raise ValueError("development provenance changed after submission")
        return
    if snapshot.get("sidecar_sha256"):
        current = capture_provenance(Path(config.scenario_path), config.scenario_sha256)
        if current != snapshot:
            raise ValueError("场景来源记录与本次实验快照不一致")


def capture_development_provenance(scene: Path, scenario_sha: str) -> dict:
    """Explicit development-only contract; never accepted by capture_provenance.

    Threat model is the same trusted local producer/deployment as existing
    provenance: bind actual scenario, immutable source installation and data
    bytes; not a signature against a malicious same-user filesystem owner.
    """
    from utils.certification_identity import source_identity, trusted_context
    sidecar = sidecar_path(scene)
    if scene.is_symlink() or sidecar.is_symlink() or not sidecar.is_file() or sidecar.stat().st_size > 1024 * 1024:
        raise ValueError("invalid development sidecar")
    payload = scene.read_bytes()
    raw = sidecar.read_bytes()
    data, model = json.loads(raw), json.loads(payload)
    if not isinstance(data, dict) or not isinstance(model, dict):
        raise ValueError("development scene and sidecar must be JSON objects")
    record = model.get("metadata", {}).get("extra", {}).get("window_generation")
    if not isinstance(record, dict):
        raise ValueError("development window generation record must be an object")
    source = Path(data.get("raw_satellite_path", ""))
    tasks = (json.dumps(model.get("missions"), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if (hashlib.sha256(payload).hexdigest() != scenario_sha
            or data.get("schema_version") != "gen02.development.v1"
            or data.get("generator_version") != "gen02-dev-1.0.0"
            or model.get("metadata", {}).get("extra", {}).get("generator_version") != "gen02-dev-1.0.0"
            or data.get("scenario_sha256") != scenario_sha
            or data.get("completion_status") != "complete"
            or data.get("calculator_kind") != "orekit"
            or data.get("publication_status") != "development_only"
            or data.get("formal_release_eligible") is not False
            or data.get("parent_scenario_sha256") is not None
            or source.is_symlink() or not source.is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest() != data.get("raw_satellite_sha256")
            or data.get("raw_satellite_sha256") != model.get("metadata", {}).get("extra", {}).get("raw_satellite_sha256")
            or data.get("task_semantic_sha256") != hashlib.sha256(tasks).hexdigest()
            or data.get("generator_sha256") != source_identity().get("scripts/generate_caabs_development_scene.py")
            or data.get("source_files_sha256") != source_identity()
            or data.get("window_generation") != record
            or data.get("orekit_data_sha256") != trusted_context().data_sha256
            or model.get("metadata", {}).get("extra", {}).get("development_generation_contract") != "gen02.development.v1"):
        raise ValueError("development evidence does not match current scenario/deployment/data")
    return {"provenance_status": "development_planning_only", "scenario_sha256": scenario_sha,
            "parent_scenario_sha256": None, "formal_release_eligible": False,
            "sidecar_sha256": hashlib.sha256(raw).hexdigest(), "physical_validation_status": "NOT_CERTIFIED"}


def capture_execution_provenance(scene: Path, scenario_sha: str, execution_mode: str) -> dict:
    if sidecar_path(scene).is_file():
        data = json.loads(sidecar_path(scene).read_bytes())
        if not isinstance(data, dict):
            raise ValueError("scenario sidecar must be a JSON object")
        if data.get("schema_version") == "gen02.development.v1":
            if execution_mode != "planning_preview":
                raise ValueError("development source is only eligible for planning_preview")
            return capture_development_provenance(scene, scenario_sha)
    model = json.loads(scene.read_bytes())
    if (isinstance(model, dict) and model.get("metadata", {}).get("extra", {}).get(
            "development_generation_contract") == "gen02.development.v1"):
        raise ValueError("development scene requires its matching development sidecar")
    return capture_provenance(scene, scenario_sha)
