"""LAVIS在线构造：原始模型分数决定选择，完整扫描未完成则保留上一轮计划。"""
import math
import time
from schedulers.constraint_model import Schedule
from .candidates import build_pool,feasible,key
from .features import extract
from .protocol import Control,BudgetExpired,validate_weights
from .model import FrozenPredictor

class LavisScheduler:
    def __init__(self,predictor):self.predictor=predictor

    def solve(self,problem,constraints,context):
        if context.params.search_mode == 'multistart':
            from .multistart import solve_multistart
            return solve_multistart(self, problem, constraints, context)
        return self._greedy_solve(problem, constraints, context)

    def _greedy_solve(self,problem,constraints,context):
        validate_weights(context.objective_weights)
        plan=Schedule();trace=[];stats={};started=time.monotonic()
        reserve=max(.1,.05*context.time_budget_s)
        if context.time_budget_s<=reserve:raise ValueError('LAVIS_BUDGET_TOO_SMALL')
        control=Control(deadline=started+context.time_budget_s-reserve,cancelled=context.is_cancelled)
        try:
            pool,stats=build_pool(problem,constraints,control,strategy=context.params.candidate_strategy)
            for _ in problem.tasks:
                current=feasible(pool,plan,constraints,control)
                if not current:break
                features=extract(problem,plan,pool,current,control)
                scores=[]
                for offset in range(0,len(current),256):
                    control.checkpoint();scores.extend(map(float,self.predictor.predict(features[offset:offset+256])))
                control.checkpoint()
                if len(scores)!=len(current) or not all(math.isfinite(x) for x in scores):raise ValueError('LAVIS_NONFINITE_OR_MISSING_PREDICTION')
                winner=min(range(len(current)),key=lambda i:(-scores[i],key(current[i])))
                a=current[winner]
                if not control.check(constraints,a,plan,static=True):raise ValueError('LAVIS_FEASIBILITY_CHANGED')
                # 仅在整轮扫描、特征与预测均完成后提交一个新任务。
                plan.assignments.append(a);trace.append({'assignment':key(a),'score':scores[winner],'feasible_count':len(current)})
        except BudgetExpired:stats['budget_exit']=True
        plan.metadata={'lavis':{'trace':trace,'pool':stats,'checks':control.checks,
                               'model_load_seconds':getattr(self.predictor,'load_seconds',0.)}}
        return plan

def build(context):
    validate_weights(context.objective_weights)
    return LavisScheduler(FrozenPredictor(context.model_provenance))
