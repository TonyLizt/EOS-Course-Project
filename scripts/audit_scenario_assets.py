"""Read-only asset audit; reports are new artifacts, never input rewrites."""
import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_scenario_manifest import audit_file
from scripts.build_shared_dataset import file_sha, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = dict(head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  raw_inputs=[], scenarios=[], archives=[], protected_final_test=[])
    for count in (10,20,50,100):
        path = ROOT/f'input/{count}_satellites.json'
        raw = json.loads(path.read_text())
        report['raw_inputs'].append(dict(path=str(path.relative_to(ROOT)), expected=count,
            count=len(raw), unique_ids=len(set(raw)), sha256=file_sha(path)))
    roots = [ROOT/'experiments/scenarios',
             ROOT/'全组统一场景数据_eos-course-v1_测试/eos-course-v1/development/scenarios']
    for root in roots:
        for path in sorted(root.rglob('*.json')):
            if 'provenance' in path.relative_to(root).parts:
                continue
            audited = audit_file(path)
            audited['record']['path'] = path.relative_to(ROOT).as_posix()
            audited['provenance_present'] = (path.parent/'provenance'/(path.name+'.provenance.json')).is_file()
            report['scenarios'].append(audited)
            print(path.name, audited['status'], flush=True)
    for path in (ROOT/'experiments/scenarios.zip',
                 ROOT/'全组统一场景数据_eos-course-v1_测试/eos-course-v1-development.zip'):
        if path.is_file():
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                report['archives'].append(dict(path=path.relative_to(ROOT).as_posix(),
                    bytes=path.stat().st_size, sha256=file_sha(path), entries=len(entries),
                    uncompressed_bytes=sum(x.file_size for x in entries)))
    # Record frozen test locations only; never parse their tasks or outcomes.
    for path in (ROOT/'全组统一场景数据_eos-course-v1_测试').rglob('*final_test*'):
        report['protected_final_test'].append(path.relative_to(ROOT).as_posix())
    write_json(args.output, report)


if __name__ == '__main__':
    main()
