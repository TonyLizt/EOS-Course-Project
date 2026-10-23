"""Rehash only the audited public assets and existing model artifacts."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.build_shared_dataset import file_sha
from scripts.matrix_journal import atomic_json


def main():
    audit=json.loads((ROOT/'data/registry/eos-v1-asset-audit-20261023.json').read_text())
    rows=[dict(path=r['record']['path'],sha256=r['record']['sha256'],role='original_scenario') for r in audit['scenarios']]
    rows += [dict(r,role=role) for role in ('raw_inputs','archives') for r in audit[role]]
    checked=[]
    for row in rows:
        actual=file_sha(ROOT/row['path'])
        checked.append(dict(path=row['path'],role=row['role'],expected_sha256=row['sha256'],actual_sha256=actual,unchanged=actual==row['sha256']))
    installed=json.loads((ROOT/'experiments/runs/eos-v1/model-installation.json').read_text())
    for path,sha in installed['protected_existing_sha256'].items():
        actual=file_sha(Path(path))
        checked.append(dict(path=path,role='previous_model',expected_sha256=sha,actual_sha256=actual,unchanged=actual==sha))
    git=lambda *args:subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
    branch=git('branch','--show-current');head=git('rev-parse','HEAD')
    restored=['utils/orekit-data.zip','docs/organize.jpg','docs/visualisation.gif']
    restored_unchanged=not git('diff','--numstat','--',*restored)
    result=dict(branch=branch,head=head,expected_head=audit['head'],
        branch_and_head_unchanged=branch=='test/basic-algorithms-web-acceptance-20261023' and head==audit['head'],
        restored_assets=restored,restored_assets_match_head=restored_unchanged,
        frozen_final_test_content_read=False,checked=checked,all_original_asset_hashes_unchanged=all(r['unchanged'] for r in checked))
    atomic_json(ROOT/'experiments/runs/eos-v1/preservation-check.json',result)
    assert result['all_original_asset_hashes_unchanged'] and result['branch_and_head_unchanged'] and restored_unchanged,result
    print('PRESERVATION_PASS',len(checked),'original assets/models; branch/HEAD/restored files unchanged',flush=True)


if __name__=='__main__':main()
