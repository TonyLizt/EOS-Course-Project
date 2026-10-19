"""课程旧版兼容合同：保留原数据和权重字节，不冒充新版物理认证。"""
from pathlib import Path
import hashlib

LEGACY_ATTITUDE = 'target_pointing_inertial_euler_v1'
NADIR_ATTITUDE = 'nadir_relative_fixed_camera_v1'
LEGACY_INFERENCE_SHA = '4b93a1323a8660c8634c45543e4945336fb85d74c7e582f7b74b14233b57adbc'
# 50660f3 对应的实际生成源码，必须与旧侧车逐项一致，不能仅凭版本名放行。
LEGACY_WINDOW_SOURCES = {
    'utils/visibility.py': 'c003fffdef52ef81b3cd994ac2463142783a5c6519ccb9d490f180b66950c2f2',
    'utils/time_parsing.py': '66fa6c4fa0371dab4e5cba0707aa5ebf14da6d7b6b2bd61876086ba2786846f9',
}


def legacy_window_record(record):
    """识别已审查的原共享/高冲突数据；未知生成器不自动降级。"""
    return (isinstance(record, dict)
        and record.get('physics_provenance_schema') == 'orekit-window-physics-lf-v1'
        and record.get('physics_sources_sha256_lf') == LEGACY_WINDOW_SOURCES
        and not record.get('attitude_model_version'))


def engineering_attitude(scene, provenance):
    """按场景生成合同选择解释，禁止把 v2 数据的角度解释成旧角度。"""
    record = scene.get('metadata', {}).get('extra', {}).get('window_generation', {})
    if record.get('attitude_model_version') == NADIR_ATTITUDE:
        return NADIR_ATTITUDE
    if legacy_window_record(record) or provenance.get('attitude_model_version') == LEGACY_ATTITUDE:
        return LEGACY_ATTITUDE
    # 六个已完成历元修复的历史场景没有 window_generation。
    if not record and provenance.get('scenario_physics_version') == 'epoch_fixed_v1':
        return LEGACY_ATTITUDE
    return NADIR_ATTITUDE


def model_scene_compatible(model, provenance):
    """同一旧课程合同允许跨历史版本名使用，仍限制原权重训练的物理域。"""
    if model.get('runtime_compatibility'):
        return (provenance.get('attitude_model_version') == LEGACY_ATTITUDE
            and provenance.get('scenario_physics_version') in ('fresh_epoch_parsed_v1', 'epoch_fixed_v1'))
    return provenance.get('scenario_physics_version') == model.get('scenario_physics_version')
