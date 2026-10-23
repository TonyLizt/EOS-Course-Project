"""Record portable source identities and the real execution environment."""
import argparse
from datetime import datetime,timezone
from importlib import metadata
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.build_shared_dataset import file_sha
from scripts.matrix_journal import atomic_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original-project',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    from utils.certification_identity import SOURCE_NAMES
    from eos_system.config import algorithm_source_sha256
    sources={name:file_sha(ROOT/name) for name in SOURCE_NAMES}
    originals={name:file_sha(args.original_project/name) for name in SOURCE_NAMES}
    assert sources==originals,'production source snapshot differs from working project'
    versions={}
    for name in ('orekit-jpype','JPype1','numpy','torch','scikit-learn','fastapi','pydantic','scipy','PuLP','ortools','ijson','matplotlib'):
        try:versions[name]=metadata.version(name)
        except metadata.PackageNotFoundError:versions[name]='NOT_INSTALLED'
    java=subprocess.run(['java','-version'],capture_output=True,text=True)
    atomic_json(args.output,dict(captured_at_utc=datetime.now(timezone.utc).isoformat(),
        execution_root=str(ROOT),canonical_root=str((ROOT/'data/scenarios/eos-v1').resolve()),
        scenario_copies_created=False,production_sources_match_original=True,
        protected_source_sha256=sources,algorithm_source_sha256=algorithm_source_sha256(),
        harness_sha256=file_sha(ROOT/'scripts/validate_scenarios.py'),journal_sha256=file_sha(ROOT/'scripts/matrix_journal.py'),
        orekit_data_sha256=file_sha(ROOT/'utils/orekit-data.zip'),python=sys.version,platform=platform.platform(),
        packages=versions,java_version=java.stderr.strip()))
    print('EXECUTION_IDENTITY_PASS',len(sources),'protected production sources identical',flush=True)


if __name__=='__main__':main()
