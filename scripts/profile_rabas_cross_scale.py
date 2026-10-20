"""Paired development-set cProfile; profile overhead is not benchmark RT."""
import argparse, cProfile, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.benchmark_rabas_cross_scale import module_at
from scripts.rabas_study_fixtures import fixture
from schedulers.constraint_model import ConstraintModel, Schedule
from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
rows=[]
for n in (20,100,300):
 for variant in ('baseline','optimized'):
  p=fixture(n,'uniform',101);cm=ConstraintModel(p);external={'full_plan_deepcopies':0}
  if variant=='baseline':
   mod=module_at('89dff80f881ed4c2a49b43906071ba07012be46c');original=mod.deepcopy
   def counted(value):
    if isinstance(value,list):external['full_plan_deepcopies']+=1
    return original(value)
   mod.deepcopy=counted;params=mod.RABASParams();solver=mod.ResourceAwareBundleAuctionScheduler()
  else:
   from algorithms.auction_bundle import ResourceAwareBundleAuctionScheduler,RABASParams
   params=RABASParams();solver=ResourceAwareBundleAuctionScheduler()
  ctx=SolveContext(41,2,ObjectiveWeights(w_profit=0,w_completion=1),params)
  profile=cProfile.Profile();profile.enable();t=time.perf_counter();plan=solver.solve(p,cm,ctx);rt=time.perf_counter()-t;profile.disable()
  file=args.output / f'final-{variant}-{n}.prof';profile.dump_stats(str(file))
  replay=Schedule()
  for a in sorted(plan.assignments,key=lambda a:a.sat_start_time):
   assert cm.is_feasible_assignment(a,replay);replay.assignments.append(a)
  rows.append(dict(n=n,variant=variant,completed=len(plan.assignments),rt=rt,stats=plan.metadata['rabas']['stats'],external=external))
  print(n,variant,len(plan.assignments),rt,external,flush=True)
(args.output / 'profile-frozen.json').write_text(json.dumps(rows,indent=2))
