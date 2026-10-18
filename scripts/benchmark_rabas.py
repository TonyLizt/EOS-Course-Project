"""Small reproducible 2x2 RABAS ablation; no benchmark winner claims.

Default inputs are synthetic planning fixtures, not physical certificates.
--scenario reads an existing JSON unchanged; --mode planning_preview is explicit.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.auction_bundle import RABASParams, ResourceAwareBundleAuctionScheduler, VERSION
from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.evaluation_metrics import compute_evaluation_metrics
from schedulers.scenario_loader import (SchedulingProblem, SchedulingSatellite, SchedulingTask,
                                      TaskWindow, SensorSpec, load_scheduling_problem_from_json)


def synthetic(name):
    start=datetime(2026,1,1)
    problem=SchedulingProblem(name,start,start+timedelta(hours=1),
        {sid:SchedulingSatellite(sid,maneuverability_type='non_agile',
            sensors={'cam':SensorSpec('cam',819.2,1)}) for sid in ('S1','S2')},{},{},[])
    rows=([('T1',10,[('S1',0),('S2',0)]),('T2',1,[('S1',0)])]
          if name=='B1-exclusive' else [(f'T{i}',1,[('S1',i*30)]) for i in range(3)])
    index=0
    for tid,priority,placements in rows:
        windows=[]
        for sid,offset in placements:
            index+=1
            windows.append(TaskWindow(index,sid,tid,'cam',1,start+timedelta(seconds=offset),
                start+timedelta(seconds=offset+10), non_agile_data={'roll_angle':0.,'pitch_angle':0.,'yaw_angle':0.},
                planning_evidence={'trusted':True,'version':'visibility_exit_refined_v3','step_s':1.,
                                   'evidence_sha256':'RABAS_ABLATION_SYNTHETIC_ONLY'}))
        problem.tasks[tid]=SchedulingTask(tid,priority,10,windows)
    return problem


def run(problem, budget):
    rows=[]
    for size in (1,2):
        for opportunity in (0.,.5):
            params=RABASParams(max_bundle_size=size,opportunity_cost_weight=opportunity)
            cm=ConstraintModel(problem,non_agile_transition_s=0)
            context=SolveContext(42,budget,ObjectiveWeights(),params)
            begin=time.perf_counter()
            plan=ResourceAwareBundleAuctionScheduler().solve(problem,cm,context)
            elapsed=time.perf_counter()-begin
            replay=Schedule()
            for assignment in plan.assignments:
                if not cm.is_feasible_assignment(assignment,replay):
                    raise AssertionError('public replay rejected ablation result')
                replay.assignments.append(assignment)
            metric=asdict(compute_evaluation_metrics(problem,plan,elapsed))
            rows.append({'max_bundle_size':size,'opportunity_cost_weight':opportunity,
                'completed_tasks':len(plan.assignments),'total_tasks':len(problem.tasks),
                'metrics':metric,**plan.metadata['rabas'], 'params':params.model_dump()})
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',type=Path)
    parser.add_argument('--mode',choices=('formal','planning_preview'),default='formal')
    parser.add_argument('--budget',type=float,default=5)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.scenario:
        path=args.scenario.resolve()
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        problem=load_scheduling_problem_from_json(path)
        problem.execution_mode=args.mode
        results={problem.scenario_id:run(problem,args.budget)}
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise AssertionError('source scenario changed')
        identity={'scenario_sha256':digest,'mode':args.mode,'synthetic':False}
    else:
        results={name:run(synthetic(name),args.budget) for name in ('B1-exclusive','B3-bundle')}
        identity={'mode':'synthetic_public_planning_only','synthetic':True}
    output={'algorithm_id':'rabas','version':VERSION,'seed':42,'budget_s':args.budget,
            'physical_certification':'NOT_RUN','identity':identity,'results':results}
    data=json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)
    if args.output:
        with args.output.open('x',encoding='utf-8') as stream: stream.write(data+'\n')
    print(data)


if __name__=='__main__':main()
