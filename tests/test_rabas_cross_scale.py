"""RABAS generic mechanisms. Synthetic fixtures are not physical certificates."""
from dataclasses import replace
from unittest.mock import patch
from test_algorithm_auction_bundle import RABASFixture, ObservedAuction
from algorithms.auction_bundle import _Auction, _Control, RABASParams, RABASCancelled
from algorithms.objectives import ObjectiveWeights, ObjectiveModel
from algorithms.solver_contracts import SolveContext
from schedulers.constraint_model import Schedule

class CrossScaleMechanisms(RABASFixture):
    def auction(self, **params):
        ctx=SolveContext(42,5,ObjectiveWeights(.2,.3,.4,.1),RABASParams(**params))
        c=_Control(ctx,lambda:0.);c.check_limit=100000
        return _Auction(self.problem,self.cm,ctx,ctx.params,c)

    def test_dynamic_shared_task_becomes_single_satellite(self):
        self.task('block',[('S2',0)],100)
        self.task('shared',[('S1',0),('S2',0)],1)
        self.task('competitor',[('S1',0)],10)
        auction=self.auction()
        base=Schedule([next(auction.options('S2','block',Schedule()))])
        witnesses=auction.witnesses('shared',base)
        self.assertEqual([choices[0].satellite_id for choices in witnesses],['S1'])
        a=next(auction.options('S1','competitor',base))
        bid=auction.bid('S1',1,base,Schedule(base.assignments+[a]),(a,),{'shared','competitor'},
                        {'balance':auction.objective.balance_score(base),'transition':{'S1':0.}})
        self.assertGreater(bid.opportunity_cost,0.)
        self.assertGreater(auction.control.stats['dynamic_scarce'],0)

    def test_exact_incremental_objective_including_balance(self):
        self.task('a',[('S1',0)],7);self.task('b',[('S1',40)],2)
        auction=self.auction(opportunity_cost_weight=0.)
        base=Schedule([next(auction.options('S1','a',Schedule()))])
        a=next(auction.options('S1','b',base));candidate=Schedule(base.assignments+[a])
        bid=auction.bid('S1',1,base,candidate,(a,),{'b'},
            {'balance':auction.objective.balance_score(base),'transition':{'S1':auction.transition_total('S1',base)}})
        self.assertAlmostEqual(bid.utility_gain,auction.objective.score(candidate)-auction.objective.score(base))

    def test_objective_fallback_preserves_clipped_negative_profit(self):
        self.task('negative',[('S1',0)],-2)
        self.task('positive',[('S1',30)],1)
        auction=self.auction(opportunity_cost_weight=0.)
        base=Schedule()
        a=next(auction.options('S1','negative',base))
        candidate=Schedule([a])
        bid=auction.bid('S1',0,base,candidate,(a,),{'negative','positive'},
                        {'balance':auction.objective.balance_score(base),'transition':{'S1':0.}})
        self.assertAlmostEqual(bid.utility_gain,auction.objective.score(candidate)-auction.objective.score(base))
        self.assertEqual(auction.control.stats['objective_full_calls'],3)

    def test_original_grid_latest_and_gap_available(self):
        self.problem.satellites['S1'].maneuverability_type='agile'
        self.task('wide',[('S1',0)],width=100)
        self.task('block',[('S1',0)],width=10)
        auction=self.auction(max_positions_per_window=8)
        base=Schedule([next(auction.options('S1','block',Schedule()))])
        result=list(auction.options('S1','wide',base))
        offsets={(a.sat_start_time-self.start).total_seconds() for a in result}
        self.assertIn(90.,offsets)
        self.assertIn(22.,offsets)
        self.assertEqual(self.problem.tasks['wide'].windows[0].start_time,self.start)
        for a in result:self.assertTrue(self.cm.is_feasible_assignment(a,base))

    def test_templates_rechecked_for_new_plan_and_custom_constraint(self):
        self.task('a',[('S1',0)])
        auction=self.auction();self.assertTrue(list(auction.options('S1','a',Schedule())))
        auction.option_cache.clear()
        with patch.object(self.cm,'is_feasible_assignment',return_value=False) as check:
            self.assertEqual(list(auction.options('S1','a',Schedule())),[])
            self.assertTrue(check.called)
        self.assertGreater(auction.control.stats['template_cache_hits'],0)

    def test_distinct_multistart_chains_and_real_bundle(self):
        for i in range(4):self.task(str(i),[('S1',i*30)])
        solver,plan=self.solve(multi_starts=2,adaptive_search=False,max_rounds=1)
        pairs=[b for b in solver.bids if len(b.additions)==2]
        self.assertGreaterEqual(len({b.additions[0].task_id for b in pairs}),2)
        self.assertEqual(len(plan.assignments),2)

    def test_repair_bounded_and_strictly_increases_count(self):
        self.task('long',[('S1',0)],10,width=30).required_duration=30
        self.task('left',[('S1',0)],1)
        self.task('right',[('S1',20)],1)
        auction=self.auction()
        base=Schedule([next(auction.options('S1','long',Schedule()))])
        result=ObservedAuction()._repair(auction,base,{'left','right'},1)
        self.assertEqual(len(result.assignments),2)
        self.assertEqual(len(base.assignments),1)
        self.assertEqual(auction.control.stats['repair_attempts'],1)
        self.feasible(result)

    def test_budget_between_complete_bids_uses_finalization_reserve(self):
        for i in range(3):self.task(str(i),[('S1',i*30)])
        clock=[0.]
        class Stop(ObservedAuction):
            def _observe_bid(self,bid):
                super()._observe_bid(bid);clock[0]=.96
        ctx=SolveContext(42,1,ObjectiveWeights(),RABASParams(opportunity_cost_weight=0.))
        plan=Stop(clock=lambda:clock[0]).solve(self.problem,self.cm,ctx)
        self.assertEqual(len(plan.assignments),1)
        self.assertEqual(plan.metadata['rabas']['stop_reason'],'budget')
        self.feasible(plan)

    def test_downlink_center_latest_and_gap_are_real_public_candidates(self):
        from datetime import timedelta
        from schedulers.scenario_loader import SchedulingGroundStation, CommWindow
        from schedulers.constraint_model import ConstraintModel
        self.problem.ground_stations['G']=SchedulingGroundStation('G')
        self.problem.comm_windows=[CommWindow(1,'S1','G',self.start+timedelta(seconds=200),
                                                    self.start+timedelta(seconds=300))]
        self.cm=ConstraintModel(self.problem,non_agile_transition_s=0)
        for i in range(4):self.task(str(i),[('S1',30*i)])
        _,plan=self.solve()
        self.assertEqual(len(plan.assignments),4)
        starts={(a.gs_start_time-self.start).total_seconds() for a in plan.assignments}
        self.assertEqual(len(starts),4)
        self.assertTrue(any(value not in (200.,245.,290.) for value in starts))
        self.feasible(plan)

    def test_identity_renaming_preserves_non_tied_quality(self):
        self.task('a',[('S1',0)],4);self.task('b',[('S1',30)],2)
        _,p=self.solve();self.problem.scenario_id='unknown-name-and-sha'
        _,q=self.solve();self.assertEqual(p,q)
