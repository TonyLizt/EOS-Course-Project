"""Exact mathematical kernel tests. No synthetic proof is physical evidence."""
from fractions import Fraction as Q
import unittest
from utils.interval_proofs import Bounds,Cell,lipschitz_enclosure,verify_partition

SHA='a'*64
REQUIRED=tuple((name,strict) for name,strict in (
    ('earth_clear',False),('elevation',True),('camera_front',True),
    ('fov_x',False),('fov_y',False),('yaw',False),('pitch',False),
    ('roll',False),('angular_rate',False),('slew_trajectory',False)))


def cell(a=0,b=1000000,changes=None,sha=SHA):
    values={n:Bounds(1,2) for n,s in REQUIRED}
    values.update(changes or {})
    return Cell(a,b,sha,tuple(values.items()))


class ExactIntervalTests(unittest.TestCase):
    def verify(self,cells,**kw):
        return verify_partition(0,1000000,tuple(cells),REQUIRED,identity_sha256=SHA,**kw)

    def test_positive_model_enclosures_are_only_conditional_not_certification(self):
        result=self.verify([cell()])
        self.assertEqual(result.status,'PROVED_INEQUALITIES')
        self.assertIn('NOT_PHYSICAL_CERTIFICATION',result.scope)
        self.assertNotIn(result.status,('CONTINUOUS_PASS','SUCCEEDED'))

    def test_shared_endpoints_cover_real_time_and_preserve_microseconds(self):
        result=self.verify([cell(500001,1000000),cell(0,500001)])
        self.assertEqual(result.status,'PROVED_INEQUALITIES')

    def test_one_microsecond_gap_overlap_and_outside_are_not_proofs(self):
        for cells in ([cell(0,500000),cell(500001,1000000)],
                      [cell(0,500001),cell(500000,1000000)],
                      [cell(-1,1000000)],[cell(0,1000001)],[cell(0,999999)]):
            with self.subTest(cells=cells):self.assertEqual(self.verify(cells).status,'INCONCLUSIVE')

    def test_strict_and_inclusive_boundary(self):
        self.assertEqual(self.verify([cell(changes={'fov_x':Bounds(0,1)})]).status,'PROVED_INEQUALITIES')
        self.assertEqual(self.verify([cell(changes={'elevation':Bounds(0,1)})]).status,'INCONCLUSIVE')
        self.assertEqual(self.verify([cell(changes={'elevation':Bounds(0,0)})]).status,'REFUTED_INEQUALITY')

    def test_negative_and_uncertain_bounds_cannot_be_proved(self):
        for name,strict in REQUIRED:
            self.assertEqual(self.verify([cell(changes={name:Bounds(-2,-1)})]).status,'REFUTED_INEQUALITY')
            self.assertEqual(self.verify([cell(changes={name:Bounds(-1,1)})]).status,'INCONCLUSIVE')

    def test_missing_each_required_margin_fails_closed(self):
        for missing,s in REQUIRED:
            c=cell();c=Cell(c.first_us,c.last_us,SHA,tuple(r for r in c.margins if r[0]!=missing))
            self.assertEqual(self.verify([c]).status,'INCONCLUSIVE')

    def test_identity_and_cell_budget(self):
        self.assertEqual(self.verify([cell(sha='b'*64)]).reason,'MODEL_INPUT_IDENTITY_MISMATCH')
        self.assertEqual(self.verify([]).status,'INCONCLUSIVE')
        self.assertEqual(self.verify([cell(0,500000),cell(500000,1000000)],max_cells=1).status,'INCONCLUSIVE')

    def test_lipschitz_radius_has_exact_error_enclosure(self):
        bound=lipschitz_enclosure(Bounds(Q(9,10),Q(11,10)),2,Q(1,10))
        self.assertEqual(bound,Bounds(Q(7,10),Q(13,10)))

    def test_hidden_substep_gap_not_missed_by_theorem(self):
        # g=(t-1/2)^2-1/100. Proven |g'|<=1 on[0,1].
        bound=lipschitz_enclosure(Bounds(Q(-1,100),Q(-1,100)),1,Q(1,2))
        self.assertLess(bound.lower,0)
        self.assertNotEqual(self.verify([cell(changes={'camera_front':bound})]).status,'PROVED_INEQUALITIES')

    def test_float_nonfinite_bool_and_reversed_bounds_rejected(self):
        for value in (1.,float('nan'),float('inf'),True):
            with self.subTest(value=value),self.assertRaises(TypeError):Bounds(value,2)
        with self.assertRaises(ValueError):Bounds(2,1)
        with self.assertRaises(ValueError):lipschitz_enclosure(Bounds(1,1),-1,1)
        with self.assertRaises(ValueError):lipschitz_enclosure(Bounds(1,1),1,-1)
        with self.assertRaises(ValueError):Cell(True,5,SHA,())

    def test_mutable_or_duplicate_claims_are_rejected(self):
        with self.assertRaises(TypeError):Cell(0,1,SHA,[])
        with self.assertRaises(ValueError):Cell(0,1,SHA,(('a',Bounds(1,1)),('a',Bounds(1,1))))
        with self.assertRaises(ValueError):verify_partition(0,1,(cell(0,1),),(),identity_sha256=SHA)
