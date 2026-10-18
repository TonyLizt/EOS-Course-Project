#!/usr/bin/env python3
"""从真实生成源码快照提取可移植窗口指纹；不修改场景或冒充重新生成。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from utils.continuous_exposure import window_physics_sources,WINDOW_PHYSICS_SCHEMA
from scripts.build_shared_dataset import file_sha,write_json
from scripts.audit_shared_dataset_samples import replace_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--generation-base-commit',required=True)
    args=parser.parse_args();root=args.dataset.resolve()
    spec=json.loads((root/'dataset_spec.json').read_text())
    for usage in ('development','final_test'):
        folder=root/usage;snapshot=folder/'generation_source'
        # 首次生成后现场保存的快照必须与每份配置的实际源文件哈希一致。
        for name,sha in spec['source_files_sha256'].items():
            if file_sha(snapshot/name)!=sha:raise ValueError('generation snapshot mismatch '+name)
        normalized=window_physics_sources(snapshot)
        if normalized!=window_physics_sources():raise ValueError('current geometry differs from actual generator')
        write_json(snapshot/'source_snapshot.json',dict(generation_base_git_sha=args.generation_base_commit,
            actual_generation_code_sha256=spec['generation_code_sha256'],
            actual_source_files_sha256=spec['source_files_sha256'],
            physics_provenance_schema=WINDOW_PHYSICS_SCHEMA,physics_sources_sha256_lf=normalized,
            identity_kind='exact uncommitted generation source bytes plus base commit; snapshot is not current upgraded runtime'))
        for sidecar in sorted((folder/'scenarios'/'provenance').glob('*.provenance.json')):
            record=json.loads(sidecar.read_text())
            scene=sidecar.parent.parent/sidecar.name.removesuffix('.provenance.json')
            if file_sha(scene)!=record['scenario_sha256']:raise ValueError('scene changed')
            window=record['window_generation']
            if window.get('source_files_sha256')!={k:v for k,v in spec['source_files_sha256'].items() if k!='scripts/build_shared_dataset.py'}:
                raise ValueError('historical producer source record mismatch')
            window['physics_provenance_schema']=WINDOW_PHYSICS_SCHEMA
            window['physics_sources_sha256_lf']=normalized
            record['portability_evidence']=dict(tool_sha256=file_sha(Path(__file__)),
                method='derive normalized geometry fingerprints from SHA-checked actual generation source snapshot',
                scene_bytes_changed=False,physics_recomputed=False)
            replace_json(sidecar,record)
    print('PORTABLE_SOURCE_EVIDENCE_100_SCENES_READY')


if __name__=='__main__':main()
