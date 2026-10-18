"""Pre-implementation mathematical counterexamples; not physical certificates."""
from fractions import Fraction as Q
import unittest
from datetime import datetime,timedelta,timezone
from utils.continuous_exposure import audit_interval


class IntervalDesignTests(unittest.TestCase):
    def test_visible_endpoints_hide_an_exact_negative_interior(self):
        # g=(t-1/2)^2-1/100: endpoints positive, midpoint negative.
        g=lambda t:(t-Q(1,2))**2-Q(1,100)
        self.assertGreater(g(Q(0)),0);self.assertGreater(g(Q(1)),0)
        self.assertLess(g(Q(1,2)),0)

    def test_point_derivatives_are_not_a_global_bound(self):
        # smooth cubic derivative zero at both ends, nonzero inside
        d=lambda t:6*t*(1-t)
        self.assertEqual(d(Q(0)),0);self.assertEqual(d(Q(1)),0)
        self.assertEqual(d(Q(1,2)),Q(3,2))

    def test_mean_value_radius_requires_numeric_error_too(self):
        # proven model interval [9/10,11/10], |g'|<=2, radius1/10
        lower=Q(9,10)-2*Q(1,10)
        self.assertEqual(lower,Q(7,10))
        self.assertLess(Q(1,100)-Q(1,10),0)  # ignoring input error falsely passes

    def test_strict_boundary_zero_is_not_certifiable(self):
        self.assertFalse(Q(0)>0);self.assertTrue(Q(0)>=0)

    def test_nearest_float_is_not_an_outward_bound(self):
        self.assertEqual(float(Q(1)-Q(1,10**30)),1.)
        self.assertLess((Q(1)-Q(1,10**30))-1,0)
        self.assertEqual(float(Q(1)-Q(1,10**30))-1,0.)

    def test_dense_point_audit_cannot_issue_a_missing_interval_proof(self):
        start=datetime(2025,11,18,12,tzinfo=timezone.utc)
        # A real-valued open hidden interval lies between audit points.
        def evaluator(t):
            x=(t-start).total_seconds()
            return dict(visible=not .011<x<.012)
        result=audit_interval(evaluator,start,start+timedelta(seconds=1),1)
        self.assertEqual(result['sampled_boundaries_status'],'PASS')
        self.assertEqual(result['status'],'INCONCLUSIVE')

    def test_endpoint_slew_budget_does_not_imply_tracking_trajectory(self):
        # endpoint angles0->0 satisfy any positive-time minimum. Yet a
        # commanded trajectory 100*t*(1-t) has speed100 at t=0.
        required_time=Q(0)/Q(1)
        self.assertLessEqual(required_time,1)
        self.assertGreater(abs(Q(100)),1)
