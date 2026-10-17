"""Isolated console QA server. Historical success uses UNIT_TEST_INJECTION_ONLY receipts.

New submissions execute real Controller/Worker and the unchanged certification gate.
No production database or scenario is modified.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import threading
import uvicorn
from urllib.request import urlopen

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "tests"))
from test_integrated_replay import fixture
from certification_fixtures import storage_receipt, unit_receipt
from eos_system.config import algorithm_source_sha256
from eos_system.storage import now
from eos_system.provenance import capture_provenance
from eos_system.visualization import orbit_cache_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coord', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18769)
    parser.add_argument('--synthetic-temporary', action='store_true', help='UNIT_TEST_INJECTION_ONLY temporary schedules for Gantt UI')
    args = parser.parse_args()
    with fixture(duration_s=3600) as f:
        cache=orbit_cache_file(f.settings,f.sha)
        packets=json.loads(cache.read_text())
        clock=packets[0]['clock'];clock.update(currentTime='2026-01-01T00:00:00Z',multiplier=1)
        for packet in packets[1:]:
            packet.update(name=packet['id'],availability=clock['interval'],
                path={'show':True,'width':2,'material':{'solidColor':{'color':{'rgba':[0,255,255,255]}}}})
        for tid,lon in (('M1',1),('M2',2)):
            packets.append({'id':tid,'name':tid,'position':{'cartographicDegrees':[lon,1,0]},'point':{'pixelSize':6}})
        cache.write_text(json.dumps(packets))
        ids, experiments = [], []
        for model_index, model in enumerate(('completion_first','adaptive_repair')):
            configs=[]
            for i, algorithm in enumerate(('profit_first','timeliness_first')):
                rid=f'00000000-0000-4000-8000-{90+model_index*2+i:012d}'
                configs.append(f.config.model_copy(update=dict(run_id=rid,algorithm_id=algorithm,
                    algorithm_version='console-1',schedule_model=model,
                    algorithm_code_sha=algorithm_source_sha256(),
                    scenario_provenance=capture_provenance(f.scene,f.sha),created_at=now())))
            experiments.append(f.app.state.experiments.create(configs,8))
            for i,cfg in enumerate(configs):
                rid=cfg.run_id
                attempt,_=f.db.start_attempt(rid);f.db.set_verifying(rid,attempt)
                plan=json.loads(json.dumps(f.db.get_run(f.run_id)['plan']))
                if i==1:
                    plan['assignments'][1]['sat_start_time']='2026-01-01T00:00:50'
                    plan['assignments'][1]['sat_end_time']='2026-01-01T00:00:55'
                metrics=dict(completed_tasks=2,total_tasks=2,task_profit=2,
                    task_completion_rate=1,balance_degree=1,timeliness_metric=.3-i*.1,
                    runtime_efficiency=.01+i*.01,robustness_variance=None,mip_gap=None)
                f.db.finish_success(rid,attempt,plan,metrics,.001,certification=storage_receipt(f.db,rid,plan))
                if model_index==0:ids.append(rid)
        empty = f.scene.parent / 'empty.json'
        empty.write_text(json.dumps({'scenario_id': 'empty', 'metadata': {
            'creation_time': '2026-01-01T00:00:00Z', 'duration': 60},
            'satellites': [], 'missions': [], 'observation_windows': []}))
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        os.environ['MPLCONFIGDIR'] = '/tmp/eos-console-mpl'
        if args.synthetic_temporary:
            original_execute=f.app.state.controller._execute
            def execute(config, attempt, store=None):
                if store is not f.app.state.temporary_controls:
                    return original_execute(config,attempt,store)
                plan=json.loads(json.dumps(f.db.get_run(ids[0])['plan']))
                plan['assignments'][1].update(sat_start_time='2026-01-01T00:00:50',sat_end_time='2026-01-01T00:00:55')
                if not store.set_verifying(config.run_id,attempt):return
                receipt=unit_receipt(config.run_id,config.scenario_sha256,plan,context=store.expected_certification_context())
                store.finish_success(config.run_id,attempt,plan,metrics,.001,certification=receipt,deadline=time.monotonic()+20)
            f.app.state.controller._execute=execute
        base = f'http://127.0.0.1:{args.port}'
        # Receipts are process-bound: seed and serve inside the same trusted process.
        server = uvicorn.Server(uvicorn.Config(f.app, host='127.0.0.1', port=args.port,
                                             log_level='warning'))
        thread = threading.Thread(target=server.run)
        thread.start()
        try:
            for _ in range(100):
                if not thread.is_alive():
                    raise RuntimeError('QA server stopped')
                try:
                    urlopen(base+'/api/health', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise TimeoutError('QA server not ready')
            args.coord.write_text(json.dumps({'url':base,'runs':ids,'gantt_run':f.run_id,
                                             'experiment':experiments[0],'peer':experiments[1]}))
            print('CONSOLE_QA_READY ' + str(args.coord), flush=True)
            deadline = time.monotonic()+240
            while args.coord.exists() and time.monotonic() < deadline:
                time.sleep(.5)
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            args.coord.unlink(missing_ok=True)
            print('CONSOLE_QA_STOPPED', flush=True)


if __name__ == '__main__':
    main()
