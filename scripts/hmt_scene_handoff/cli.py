"""Portable handoff entry points. Importing this module starts no service or solver.

verify is strictly offline: it checks bytes and invokes the original Loader only.
generate/register/serve are explicit future user actions, never part of verification.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import types
import urllib.request

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / 'artifacts'
ROOT = HERE.parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def bounded(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root):
        raise ValueError('MANIFEST_PATH_OUTSIDE_ROOT')
    return path


def runtime_check(project):
    project = Path(project).resolve()
    expected = read(ARTIFACTS / 'runtime_requirement.json')
    differences = [name for name, digest in expected['files'].items()
                   if not (project / name).is_file() or sha(project / name) != digest]
    return dict(status='PASS' if not differences else 'RUNTIME_PREREQUISITE_REQUIRED',
                project=str(project), differences=differences,
                required_deployment=expected['pre_scene_deployment_sha256'])


def verify_bytes(scenes):
    scenes = Path(scenes).resolve()
    manifest = read(scenes / 'MANIFEST.json')
    for row in manifest['scenarios']:
        for name, digest in row['files'].items():
            if sha(bounded(scenes, name)) != digest:
                raise ValueError('SCENE_SHA_MISMATCH:' + name)
        raw = read(bounded(scenes, row['relative_path']))
        actual = (len(raw['satellites']), len(raw['missions']),
                  sum(len(w['time_windows']) for w in raw['observation_windows']))
        if actual != (row['satellites'], row['tasks'], row['windows']):
            raise ValueError('SCENE_COUNTS_MISMATCH:' + row['scenario_id'])
    return manifest


def verify(project, scenes, require_runtime=False):
    manifest = verify_bytes(scenes)
    identity = runtime_check(project)
    if require_runtime and identity['status'] != 'PASS':
        raise RuntimeError(json.dumps(identity))
    # Dedicated process: no accidental import of the sender's live project.
    code = '''import sys,json,socket
from pathlib import Path
project=Path(sys.argv[1]).resolve();root=Path(sys.argv[2]).resolve()
sys.path.insert(0,str(project))
def denied(*a,**k):raise RuntimeError("OFFLINE_VERIFY_NETWORK_FORBIDDEN")
socket.create_connection=denied
from schedulers import scenario_loader
from eos_system.config import list_scenarios_in,resolve_scenario_in
assert Path(scenario_loader.__file__).resolve().is_relative_to(project)
manifest=json.loads((root/'MANIFEST.json').read_text())
listed=list_scenarios_in(root,'handoff-local');rows=[]
for expected in manifest['scenarios']:
 path,digest=resolve_scenario_in(root,expected['scenario_id'])
 assert digest==expected['sha256']
 p=scenario_loader.load_scheduling_problem_from_json(path)
 assert len(p.satellites)==expected['satellites'] and len(p.tasks)==expected['tasks']
 assert any(r['scenario_id']==expected['scenario_id'] for r in listed)
 rows.append(dict(id=expected['scenario_id'],satellites=len(p.satellites),tasks=len(p.tasks),sha256=digest))
print(json.dumps(dict(status='PASS',Loader=scenario_loader.__file__,scenarios=rows,Solver_calls=0,Verifier_calls=0,Controller_submissions=0)))
'''
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'EOS_PHYSICAL_EVIDENCE_DIR', 'EOS_RUNTIME_DIR',
                'EOS_PILOT_INTEGRATION_CONFIG', 'EOS_READONLY_ARCHIVE_DIR'):
        env.pop(key, None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([sys.executable, '-B', '-c', code, str(Path(project).resolve()),
                             str(Path(scenes).resolve())], env=env, cwd=scenes,
                            text=True, capture_output=True, check=True)
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    return dict(status='PASS', byte_manifest_sha256=sha(Path(scenes) / 'MANIFEST.json'),
                runtime=identity, original_Loader=loaded,
                physical_validation='NOT_EXECUTED_THIS_HANDOFF',
                scope='Structural readback only; historical sampled evidence stays historical.')


def register(url, scenes):
    """Use the original API. Reuse existing roots, respecting UNIQUE(root_path)."""
    root = str(Path(scenes).resolve())
    def request(method, endpoint, body=None):
        req = urllib.request.Request(url.rstrip('/') + endpoint,
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    rows = request('GET', '/api/data-sources')['items']
    for row in rows:
        if Path(row['root_path']).resolve() == Path(root):
            return dict(action='REUSED_EXISTING_ROOT', source=row)
    return dict(action='REGISTERED_NEW_ROOT', source=request('POST', '/api/data-sources',
        {'name': 'HMT 10/30 scenes (development)', 'path': root}))


def relocate_generator(source, replacements):
    """Change only four top-level path assignments; scientific function ASTs unchanged."""
    tree = ast.parse(source)
    changed = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in replacements:
                node.value = ast.parse('Path(' + repr(str(replacements[target.id])) + ')', mode='eval').body
                changed.add(target.id)
    if changed != set(replacements):
        raise ValueError('GENERATOR_PATH_ASSIGNMENT_CONTRACT_CHANGED')
    return ast.fix_missing_locations(tree)


def generate(project, output, scenario_id):
    """Explicit future regeneration; never called by verify/tests/package acceptance."""
    identity = runtime_check(project)
    if identity['status'] != 'PASS':
        raise RuntimeError(json.dumps(identity))
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Use a NEW output directory; immutable deliveries are never overwritten.')
    recipe = read(ARTIFACTS / 'recipes.json')[scenario_id]
    output.mkdir(parents=True)
    import shutil
    for name in ('source_header.json', 'source_identity.json', 'design_plan_before_generation.json'):
        shutil.copyfile(ARTIFACTS / name, output / name)
    bridge = types.ModuleType('inventory')
    bridge.read, bridge.save, bridge.sha = read, save, sha
    def forbidden(*a, **k):
        raise RuntimeError('LEGACY_NETWORK_DATABASE_FUNCTION_NOT_AVAILABLE_IN_PORTABLE_GENERATOR')
    bridge.http = bridge.backup = bridge.tables = forbidden
    bridge.RUNTIME, bridge.PY = output / 'unused-runtime', sys.executable
    previous = sys.modules.get('inventory')
    sys.modules['inventory'] = bridge
    sys.path.insert(0, str(Path(project).resolve()))
    try:
        def load(digest):
            path = ARTIFACTS / 'generators' / (digest + '.py')
            if sha(path) != digest:
                raise ValueError('ORIGINAL_GENERATOR_SHA_MISMATCH')
            tree = relocate_generator(path.read_text(), dict(ROOT=Path(project).resolve(),
                OUT=output, WORK=output / 'work', DATA=output / 'scenarios'))
            namespace = {'__file__': str(path), '__name__': 'portable_original_generator'}
            exec(compile(tree, str(path), 'exec'), namespace)
            return namespace
        load(recipe['bank_generator_sha256'])['bank'](recipe['satellite_count'])
        build = load(recipe['build_generator_sha256'])['build']
        kwargs = dict(sid=scenario_id, count=recipe['satellite_count'],
                      task_count=recipe['task_count'], kind=recipe['kind'])
        if recipe['fixed_slots']:
            kwargs['fixed_slots'] = True
        build(**kwargs)
        save(output / 'portable_generation_receipt.json', dict(recipe=recipe,
            adapter_sha256=sha(__file__), original_scripts_unchanged=True,
            regenerated_bytes_may_differ='origin paths and new environment are recorded, not hidden'))
    finally:
        if previous is None:
            sys.modules.pop('inventory', None)
        else:
            sys.modules['inventory'] = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('verify', 'register', 'generate'))
    parser.add_argument('--project', type=Path,
                        default=ROOT / 'baseline_runtime' if (ROOT / 'baseline_runtime').is_dir() else ROOT)
    parser.add_argument('--scenarios', type=Path,
                        default=ROOT / 'scenarios' if (ROOT / 'scenarios').is_dir()
                        else ROOT / 'data/scenarios/hmt-web-10-30-v1')
    parser.add_argument('--require-runtime', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--url', help='Explicit recipient server URL; no implicit sender service')
    parser.add_argument('--id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'verify':
        result = verify(args.project, args.scenarios, args.require_runtime)
    elif args.action == 'register':
        if not args.url:
            parser.error('register requires explicit --url')
        verify(args.project, args.scenarios, True)
        result = register(args.url, args.scenarios)
    else:
        if not args.output or not args.id:
            parser.error('generate requires --id and NEW --output')
        generate(args.project, args.output, args.id)
        result = dict(status='GENERATED_NEW_CANDIDATE_NOT_CONTROLLER_CERTIFIED')
    if args.report:
        save(args.report, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
