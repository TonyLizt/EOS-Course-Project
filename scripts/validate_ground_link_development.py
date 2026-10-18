"""Generate and validate a REAL development GS chain, NEVER formal release."""
from pathlib import Path
import argparse
import json
import os
import sys


def execute(output,data):
    root=Path(__file__).resolve().parents[1]
    output=output.absolute()
    if any(p.is_symlink() for p in (output,*output.parents)) or '..' in output.parts:
        raise ValueError('unsafe output')
    if root==output or root in output.parents or output in root.parents:raise ValueError('output must be outside repo')
    output.mkdir(parents=True,exist_ok=False)
    os.environ['EOS_OREKIT_DATA']=str(data.resolve())
    from utils.visibility import ensure_orekit
    ensure_orekit(str(data))
    from scripts.generate_caabs_development_scene import generate
    from scripts.validate_caabs_real_integration import make_config,runner_case,wait_run,write
    from scripts.audit_continuous_proof_readiness import audit
    from eos_system.config import Settings
    from eos_system.storage import Database
    from eos_system.controller import Controller
    from eos_system.exporting import render_json,render_csv
    generated=generate(output/'scene',root/'input/10_satellites.json','ALOS-2_39766',str(data),with_ground_station=True)
    scene=Path(generated['scenario'])
    assert generated['communication_windows']>0 and generated['ground_stations']==1
    config=make_config(scene)
    runner=runner_case(config,output/'runner.json')
    assert all(type(a['gs_window_id']) is int and a['gs_start_time']>a['sat_end_time'] for a in runner['official']['assignments'])
    database=Database(output/'runtime/results.sqlite3')
    settings=Settings(output/'runtime',scene.parent)
    database.ensure_defaults(scene.parent,settings.runtime_dir)
    controller=Controller(settings,database);controller.start()
    try:
        config=make_config(scene)
        database.enqueue(config,max_queued=8)
        record=wait_run(database,config.run_id)
        write(output/'controller.json',record)
        assert record['status']=='SUCCEEDED' and record['result_kind']=='planning_preview',record['error']
        assert record['metrics']['completed_tasks']>0
        for exporter in (render_json,render_csv):
            try:exporter(record)
            except ValueError:pass
            else:raise AssertionError('formal export accepted an uncertified development source')
    finally:controller.stop()
    readiness=audit(scene,data)
    write(output/'interval-readiness.json',readiness)
    result=dict(generation=generated,runner_metrics=runner['metrics'],
        controller_status=record['status'],result_kind=record['result_kind'],
        continuous_certification=record['continuous_certification'],readiness=readiness,
        downlink_rows=[r.get('downlink_audit') for r in runner['preview']['audit_summary']['rows']],
        scope='IDEAL_ANTENNA_REAL_GEOMETRY_NOT_RF_LINK_BUDGET_OR_INTERVAL_CERTIFICATE')
    assert all(r and r['sampled_boundaries_status']=='PASS' and r['status']=='INCONCLUSIVE' for r in result['downlink_rows'])
    write(output/'acceptance.json',result)
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--orekit-data',required=True,type=Path)
    args=parser.parse_args();execute(args.output,args.orekit_data)
