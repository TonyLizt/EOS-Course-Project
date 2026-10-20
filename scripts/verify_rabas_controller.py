"""Actual reference Worker -> Controller -> SQLite check; no verifier patches."""
import argparse, sys, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from eos_system.api import create_app
from eos_system.config import Settings,sha256_file
from test_replay_backend import _DirectClient
from scripts.benchmark_rabas_real import SCENES

def main():
 parser = argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output', type=Path, required=True)
 root = parser.parse_args().output
 root.mkdir(parents=True, exist_ok=False)
 rows=[]
 # One preselected real scene per scale; both preview and formal are accounted for.
 for i,(scale,relative) in enumerate([SCENES[0],SCENES[2],SCENES[3]]):
  path=ROOT/relative;digest=sha256_file(path)
  app=create_app(Settings(root/f'runtime-{i}',path.parent))
  app.state.controller.start()
  try:
   with _DirectClient(app) as client:
    for mode in ('planning_preview','formal'):
     request=dict(scenario_id=path.stem,algorithm_id='rabas',execution_mode=mode,time_budget_s=3,
                  seed=41,objective_weights={'w_profit':0,'w_completion':1})
     response=client.post('/api/runs',json=request)
     if response.status_code!=202:
      row=dict(scale=scale,mode=mode,status='SUBMISSION_REJECTED',http_status=response.status_code,detail=response.json(),sha256=digest)
     else:
      rid=response.json()['run_id'];deadline=time.monotonic()+100
      while time.monotonic()<deadline:
       record=app.state.database.get_run(rid)
       if record['status'] in ('SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'):break
       time.sleep(.05)
      row=dict(scale=scale,mode=mode,run_id=rid,status=record['status'],sha256=digest,
               metrics=record.get('metrics'),error=record.get('error'),preview_validation=record.get('preview_validation'),
               continuous_certification=record.get('continuous_certification'),attempts=record.get('attempts'))
     rows.append(row);(root/'results.json').write_text(json.dumps(rows,indent=2,default=str))
     print(scale, mode, row['status'], flush=True)
     assert sha256_file(path)==digest
  finally:
   app.state.temporary_controls.close();app.state.replay.close();app.state.controller.stop()
if __name__=='__main__':main()
