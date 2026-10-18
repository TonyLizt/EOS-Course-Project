"""Temporary UI/Worker test server; synthetic certification fixture ONLY."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT));sys.path.insert(0,str(PROJECT/'tests'))
from rabas_integration_fixture import write_scene,cache_orbits
from eos_system.config import Settings,sha256_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coord',type=Path,required=True)
    args=parser.parse_args()
    if args.coord.exists():raise ValueError('coord exists; refusing overwrite')
    with tempfile.TemporaryDirectory(prefix='rabas-browser-') as directory:
        root=Path(directory);scenes=root/'scenes';scenes.mkdir()
        scene=scenes/'synthetic.json';write_scene(scene)
        settings=Settings(root/'runtime',scenes);cache_orbits(settings,sha256_file(scene))
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'EOS_RUNTIME_DIR':str(settings.runtime_dir),'EOS_SCENARIO_DIR':str(scenes),
             'PYTHONPATH':str(PROJECT/'tests')+os.pathsep+str(PROJECT)}
        with (root/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','rabas_integration_fixture:make_app',
                '--factory','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=PROJECT,env=env,
                stdout=log,stderr=subprocess.STDOUT)
            try:
                base=f'http://127.0.0.1:{port}'
                for _ in range(100):
                    if server.poll() is not None:raise RuntimeError((root/'server.log').read_text())
                    try:
                        with urlopen(base+'/api/health',timeout=1):break
                    except OSError:time.sleep(.1)
                else:raise TimeoutError('test server startup')
                args.coord.write_text(json.dumps({'url':base,'stop':False,'synthetic_only':True}))
                print('RABAS_BROWSER_READY '+base,flush=True)
                deadline=time.monotonic()+180
                while time.monotonic()<deadline and args.coord.exists() and not json.loads(args.coord.read_text()).get('stop'):
                    time.sleep(.2)
            finally:
                server.terminate()
                try:server.wait(timeout=12)
                except subprocess.TimeoutExpired:server.kill();server.wait(timeout=3)
                args.coord.unlink(missing_ok=True)
                print('RABAS_BROWSER_CLEANED',flush=True)


if __name__=='__main__':main()
