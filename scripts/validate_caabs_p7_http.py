#!/usr/bin/env python3
"""Bounded REAL HTTP/Console acceptance over fresh generated development scenes.

Uses the existing generator/Runner acceptance outputs; never modifies scenes or
sidecars. Start a new server, database and browser; no production runtime access.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError


def execute(args):
    repository = Path(__file__).resolve().parents[1]
    output = args.output.absolute()
    if (repository == output or repository in output.parents or output in repository.parents
            or '..' in output.parts or any(p.is_symlink() for p in (output, *output.parents))):
        raise ValueError('new isolated output outside repository required')
    output.mkdir(parents=True, exist_ok=False)
    originals = {p: p.read_bytes() for p in (args.no_ground, args.ground)}
    runtime = output / 'runtime'
    with socket.socket() as stream:
        stream.bind(('127.0.0.1', 0))
        port = stream.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    env = os.environ | dict(EOS_PORT=str(port), EOS_RUNTIME_DIR=str(runtime),
        EOS_SCENARIO_DIR=str(args.no_ground.parent), EOS_OREKIT_DATA=str(args.orekit_data),
        EOS_PREINITIALIZE_OREKIT='1', PYTHONHASHSEED='0', MPLBACKEND='Agg')
    def api(path, data=None):
        request = Request(url + path, data=None if data is None else json.dumps(data).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    def write(name, value):
        with (output/name).open('x') as file:
            json.dump(value, file, indent=2)
    with (output/'server.log').open('x') as log:
        server = subprocess.Popen([sys.executable, '-B', '-m', 'eos_system'], cwd=repository,
                                  env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 80
            while True:
                try:
                    api('/api/health')
                    break
                except (URLError, ConnectionError):
                    if server.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('isolated HTTP startup failed; see server.log')
                    time.sleep(.1)
            ground = api('/api/data-sources', {'name': 'P7 real GS', 'path': str(args.ground.parent)})
            info = dict(url=url, output=str(output), ground_source=ground['source_id'],
                no_ground_sha=hashlib.sha256(originals[args.no_ground]).hexdigest(),
                ground_sha=hashlib.sha256(originals[args.ground]).hexdigest())
            write('coord.json', info)
            browser_env = env | dict(EOS_CAABS_P7_COORD=str(output/'coord.json'),
                                    PLAYWRIGHT_MODULE=str(args.playwright_module))
            with (output/'browser.log').open('x') as browser_log:
                result = subprocess.run(['node', 'tests/browser/caabs-real-preview-smoke.cjs'],
                    cwd=repository, env=browser_env, stdout=browser_log, stderr=browser_log, timeout=240)
            if result.returncode:
                raise RuntimeError('real browser acceptance failed; see browser.log')
            cases = json.loads((output/'browser-results.json').read_text())['cases']
            for case in cases:
                write(case['name']+'-http-record.json', api('/api/runs/'+case['run_id']))
            assert all(p.read_bytes() == raw for p, raw in originals.items())
        finally:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait(timeout=5)
                write('forced-stop.json', {'reason': 'owned server failed graceful shutdown'})
                raise RuntimeError('HTTP server did not gracefully stop')
            from eos_system.process_state import lock_held
            clean = not lock_held(runtime/'controller.lock')
            write('shutdown.json', {'exit_code': server.returncode, 'controller_lock_released': clean,
                'worker_journal_absent': not (runtime/'worker-lease.json').exists()})
            assert clean and not (runtime/'worker-lease.json').exists()
    return info


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'no-ground', 'ground', 'orekit-data', 'playwright-module'):
        parser.add_argument('--'+name, required=True, type=Path)
    execute(parser.parse_args())
