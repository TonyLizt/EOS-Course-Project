"""Real-model R1 search ablation in fresh processes; never inserts official results.

Takes --runtime (an existing isolated integration runtime), --scenarios and a NEW
--artifacts directory. Both variants use identical frozen models and 5s budget.
The model-only variant disables the adapter's alternative search only; metadata
labels the intervention explicitly. Candidate plans pass the real Verifier.
"""
import argparse
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import shutil
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from r1_objective_integration import GOALS,tree


def trial(config,adapt,output):
    try:
        from eos_system.contracts import RunConfig
        from eos_system.runner import prepare,run_prepared
        from eos_system.verification import verify_candidate
        config=RunConfig(**config)
        solver,problem,cm,context=prepare(config);solver.adapt=adapt
        candidate,runtime=run_prepared(solver,problem,cm,context)
        official,metrics,receipt=verify_candidate(config,candidate,runtime)
        from algorithms.objectives import ObjectiveModel
        from schedulers.constraint_model import Schedule
        from schedulers.source_windows import SourceWindowIndex
        sources=SourceWindowIndex(problem);plan=Schedule()
        for item in official['assignments']:plan.assignments.append(sources.restore(item,cm))
        record=dict(kind='INDEPENDENT_ABLATION_NOT_OFFICIAL_RUN',adapt=adapt,pid=os.getpid(),
                    model=config.model_provenance,requested_objective=config.objective_weights.model_dump(),
                    objective_score=ObjectiveModel(problem,context.objective_weights).score(plan),
                    candidate=candidate,verified_plan=official,metrics=metrics,
                    physical_evidence=receipt.evidence(),runtime_s=runtime)
    except BaseException:record=dict(error=traceback.format_exc())
    Path(output).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('runtime','scenarios','artifacts'):parser.add_argument('--'+arg,type=Path,required=True)
    args=parser.parse_args();args.artifacts.mkdir(parents=True,exist_ok=False)
    runtime=args.artifacts.resolve()/'runtime'
    shutil.copytree(args.runtime/'models',runtime/'models')
    os.environ.update(EOS_RUNTIME_DIR=str(runtime),EOS_OREKIT_DATA=str(ROOT/'utils/orekit-data.zip'),
                      TMPDIR=str(args.artifacts.resolve()),MPLCONFIGDIR=str(args.artifacts.resolve()/'mpl'),PYTHONDONTWRITEBYTECODE='1')
    for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[name]='1'
    from eos_system.api import create_app
    from eos_system.config import Settings
    from test_replay_backend import _DirectClient
    before=tree(args.runtime/'models')
    app=create_app(Settings(runtime,args.scenarios));client=_DirectClient(app);summary=[]
    try:
        for scene,seed in (('EOS-G0034',7),('EOS-G0087',101)):
            for goal,weights in GOALS.items():
                for aid,model in (('ppo','ppo-dev-20261020-01'),('lavis','lavis-v1')):
                    req=dict(algorithm_id=aid,scenario_id=scene,algorithm_params={'model_id':model},
                             objective_weights=weights,seed=seed,time_budget_s=5.,execution_mode='physical_validation')
                    response=client.post('/api/experiments',json={'runs':[req]});assert response.status_code==202,response.text
                    rid=response.json()['runs'][0]['run_id'];config=app.state.database.get_run(rid)['config'];app.state.database.request_cancel(rid)
                    # Keep the intervention outside public params and production Runs.
                    for adapt in (False,True):
                        output=args.artifacts/(scene+'-'+goal+'-'+aid+'-'+str(adapt)+'.json')
                        child=mp.get_context('spawn').Process(target=trial,args=(config,adapt,str(output)))
                        child.start();child.join(80)
                        if child.is_alive():child.terminate();child.join(5);raise RuntimeError('Ablation process timeout')
                        assert child.exitcode==0 and output.exists(),(child.exitcode,output)
                        record=json.loads(output.read_text());assert 'error' not in record,record
                        assert record['runtime_s']<=5.,record['runtime_s']
                        summary.append(dict(scene=scene,seed=seed,goal=goal,algorithm=aid,adapt=adapt,
                            objective_score=record['objective_score'],metrics=record['metrics'],runtime_s=record['runtime_s'],pid=record['pid'],artifact=str(output)))
                        (args.artifacts/'summary.json').write_text(json.dumps(summary,indent=2));print('ABLATION',scene,goal,aid,adapt,record['objective_score'],record['metrics']['completed_tasks'],flush=True)
        assert before==tree(args.runtime/'models')
    finally:app.state.replay.close()


if __name__=='__main__':main()
