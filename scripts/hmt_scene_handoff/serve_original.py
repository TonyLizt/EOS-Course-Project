"""Explicit recipient-only original Web launcher; never runs during handoff verify.

Every spawn interpreter installs the original protocol hooks through the supplied
sitecustomize module. Service binding itself is protected by __main__.
"""
from pathlib import Path
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--scenarios', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8920)
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=1)
    args = parser.parse_args()
    from cli import runtime_check, read, ARTIFACTS
    if runtime_check(args.project)['status'] != 'PASS':
        raise RuntimeError('EXACT_PRE_SCENE_RUNTIME_REQUIRED')
    runtime = args.runtime.resolve()
    if runtime.exists():
        raise FileExistsError('Choose a NEW recipient Runtime; existing databases are not touched.')
    runtime.mkdir(parents=True)
    project, scenes = args.project.resolve(), args.scenarios.resolve()
    for key in ('EOS_PHYSICAL_EVIDENCE_DIR', 'EOS_PILOT_INTEGRATION_CONFIG', 'EOS_READONLY_ARCHIVE_DIR'):
        os.environ.pop(key, None)
    hook = Path(__file__).resolve().parent / 'runtime_hook'
    os.environ.update(EOS_RUNTIME_DIR=str(runtime), EOS_SCENARIO_DIR=str(scenes),
        EOS_MAX_WORKERS=str(args.workers), EOS_PREINITIALIZE_OREKIT='1',
        EOS_STAGE19D_DEPLOYMENT_SHA=read(ARTIFACTS / 'runtime_requirement.json')['pre_scene_deployment_sha256'],
        PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
        MKL_NUM_THREADS='1', PYTHONPATH=os.pathsep.join((str(hook), str(project))))
    sys.path.insert(0, str(project))
    os.chdir(project)
    from eos_system.web_runtime_hooks import install
    install()
    import uvicorn
    uvicorn.run('eos_system.api:create_app', factory=True, host='127.0.0.1',
                port=args.port, workers=1)


if __name__ == '__main__':
    main()
