"""受控模型制品：只接受登记ID，固定清单与权重字节后才加载团队训练模型。"""
from __future__ import annotations
import hashlib
import io
import json
import os
import re
from importlib import metadata
from pathlib import Path
from .protocol import FEATURE_VERSION,FEATURE_NAMES,CANDIDATE_VERSION,LABEL_VERSION,POOL_CONFIG,DOMAIN

MODEL_LIMIT=50*1024*1024

def digest(raw):return hashlib.sha256(raw).hexdigest()

def inference_code_sha():
    root=Path(__file__).resolve().parents[2]
    paths=list((root/'algorithms/lavis').glob('*.py'))
    # 标签/训练实现有独立训练身份；在线模型只绑定影响候选、特征、推理与约束的源码。
    paths=[p for p in paths if p.name not in ('labels.py','training.py')]
    paths += [root/name for name in ('schedulers/assignment_building.py','schedulers/constraint_model.py',
        'schedulers/source_windows.py','schedulers/observation_geometry.py','schedulers/transition_utils.py',
        'schedulers/preview_exposure.py','utils/continuous_exposure.py','utils/visibility.py','utils/time_parsing.py')]
    h=hashlib.sha256()
    for p in sorted(paths):
        h.update(p.relative_to(root).as_posix().encode());h.update(b'\0');h.update(p.read_bytes().replace(b'\r\n',b'\n'));h.update(b'\0')
    return h.hexdigest()

def model_root():
    return Path(os.environ.get('EOS_RUNTIME_DIR','~/eos-course-runtime')).expanduser().resolve()/'models'/'lavis'

def dependencies():
    return {name:metadata.version(name) for name in ('scikit-learn','numpy','scipy','joblib')}

def read_artifact(model_id):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}',model_id):raise ValueError('LAVIS_INVALID_MODEL_ID')
    root=model_root();directory=root/model_id
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):raise ValueError('LAVIS_MODEL_PATH')
    manifest=directory/'manifest.json';weights=directory/'model.joblib'
    if not manifest.is_file() or manifest.is_symlink() or manifest.stat().st_size>128*1024:raise ValueError('LAVIS_MODEL_NOT_REGISTERED')
    raw=manifest.read_bytes();record=json.loads(raw)
    if (record.get('model_id')!=model_id or record.get('format')!='team-joblib-v1'
        or record.get('feature_version')!=FEATURE_VERSION or record.get('features')!=list(FEATURE_NAMES)
        or record.get('candidate_version')!=CANDIDATE_VERSION or record.get('label_version')!=LABEL_VERSION
        or record.get('pool_config')!=POOL_CONFIG or record.get('domain')!=DOMAIN
        or record.get('inference_code_sha256_lf')!=inference_code_sha()):raise ValueError('LAVIS_INCOMPATIBLE_MODEL')
    if not weights.is_file() or weights.is_symlink() or not 0<weights.stat().st_size<=MODEL_LIMIT:raise ValueError('LAVIS_MODEL_SIZE_OR_PATH')
    data=weights.read_bytes()
    if digest(data)!=record.get('model_sha256'):raise ValueError('LAVIS_MODEL_SHA_MISMATCH')
    return record|{'manifest_sha256':digest(raw)},data

def freeze(model_id):
    record,_=read_artifact(model_id)
    return record

def list_models():
    root=model_root()
    if not root.exists():return []
    items=[]
    for directory in sorted(root.iterdir())[:100]:
        if not directory.is_dir():continue
        try:
            record,_=read_artifact(directory.name)
            items.append({'model_id':record['model_id'],'model_version':record['model_version'],
                          'model_sha256':record['model_sha256'],'feature_version':record['feature_version']})
        except (ValueError,OSError,KeyError):continue
    return items

def verify_snapshot(snapshot):
    if not snapshot or not isinstance(snapshot.get('model_id'),str):raise ValueError('LAVIS_MODEL_SNAPSHOT_REQUIRED')
    current,data=read_artifact(snapshot['model_id'])
    if current!=snapshot:raise ValueError('LAVIS_MODEL_CHANGED_AFTER_SUBMISSION')
    return data

class FrozenPredictor:
    def __init__(self,snapshot):
        import time
        started=time.perf_counter();data=verify_snapshot(snapshot)
        if dependencies()!=snapshot['dependencies']:raise ValueError('LAVIS_DEPENDENCY_VERSION_MISMATCH')
        import joblib
        # 仅加载管理员用离线训练CLI生成的本地受控制品；joblib不是不可信上传格式。
        self.model=joblib.load(io.BytesIO(data))
        if getattr(self.model,'n_features_in_',None)!=len(FEATURE_NAMES):raise ValueError('LAVIS_FEATURE_DIMENSION')
        self.load_seconds=time.perf_counter()-started

    def predict(self,rows):
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=1):return self.model.predict(rows)
