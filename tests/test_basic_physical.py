"""Opt-in real Orekit validation for both source families and ground links."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('EOS_RUN_BASIC_PHYSICS') == '1', 'real Orekit opt-in')
class BasicPhysicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils.visibility import ensure_orekit
        ensure_orekit(os.environ['EOS_OREKIT_DATA'])
        cls.temp = tempfile.TemporaryDirectory(prefix='eos-basic-physical-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(__file__).resolve().parents[1]
        cls.scenes = {}

    def generated_scene(self, ground):
        from scripts.generate_caabs_development_scene import generate
        if ground not in self.scenes:
            result = generate(Path(self.temp.name)/str(ground), self.root/'input/10_satellites.json',
                'ALOS-2_39766', os.environ['EOS_OREKIT_DATA'], with_ground_station=ground)
            self.scenes[ground] = Path(result['scenario'])
        return self.scenes[ground]

    def validate(self, scene, ground, placements=('earliest','center')):
        from algorithms.basic import BASIC_ALGORITHMS
        from eos_system.runner import calculate
        from eos_system.verification import verify_candidate
        from scripts.validate_caabs_real_integration import make_config
        before = hashlib.sha256(scene.read_bytes()).hexdigest()
        for aid in BASIC_ALGORITHMS:
            for placement in placements:
                with self.subTest(scene=scene.name, algorithm=aid, placement=placement):
                    config = make_config(scene, algorithm=aid, budget=5).model_copy(update={'placement_mode':placement})
                    candidate, runtime = calculate(config)
                    official, metrics, receipt = verify_candidate(config,candidate,runtime)
                    self.assertGreater(metrics['completed_tasks'],0)
                    self.assertLessEqual(runtime,5)
                    if ground:
                        self.assertTrue(all(a['gs_window_id'] and a['gs_start_time'] > a['sat_end_time']
                                            for a in official['assignments']))
                        for row in receipt.evidence()['audit_summary']['rows']:
                            self.assertEqual(row['downlink_audit']['sampled_boundaries_status'],'PASS')
        self.assertEqual(hashlib.sha256(scene.read_bytes()).hexdigest(),before)

    def test_generated_nadir_source_and_both_placements(self):
        self.validate(self.generated_scene(False),False)

    def test_real_ground_link_and_both_placements(self):
        self.validate(self.generated_scene(True),True)

    def test_epoch_fixed_source_format(self):
        self.validate(self.root/'experiments/scenarios/small'/
            'Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1.json',False,('earliest',))

    def test_legacy_source_loads_but_does_not_bypass_physical_rejection(self):
        from algorithms.basic import BASIC_ALGORITHMS
        from eos_system.runner import calculate
        from eos_system.verification import verify_candidate
        from scripts.validate_caabs_real_integration import make_config
        from utils.continuous_exposure import ContinuousCertificationError, ExposureStatus
        scene = self.root/'experiments/scenarios/small/Scenario_S1_Sats10_M20_T1.0d_dist1.json'
        before = hashlib.sha256(scene.read_bytes()).hexdigest()
        # The unchanged legacy parent is not the epoch-recomputed physical data.
        # Check an existing baseline too: this rejection is independent of the
        # newly introduced dispatch policies, not an excuse to weaken auditing.
        for aid in ('completion_first',) + BASIC_ALGORITHMS:
            with self.subTest(algorithm=aid):
                config = make_config(scene, algorithm=aid, budget=5).model_copy(update={'placement_mode':'earliest'})
                candidate, runtime = calculate(config)
                self.assertTrue(candidate['assignments'])
                self.assertLessEqual(runtime,5)
                with self.assertRaisesRegex(ContinuousCertificationError,'NONVISIBLE_EXPOSURE_START') as caught:
                    verify_candidate(config,candidate,runtime)
                self.assertEqual(caught.exception.status,ExposureStatus.REJECTED)
        self.assertEqual(hashlib.sha256(scene.read_bytes()).hexdigest(),before)


if __name__ == '__main__':
    unittest.main()
