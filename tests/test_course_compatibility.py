"""旧课程合同与新版合同的边界：不修改真实数据、不伪造物理通过。"""
import unittest
from utils.course_compatibility import (LEGACY_ATTITUDE, NADIR_ATTITUDE,
    LEGACY_WINDOW_SOURCES, legacy_window_record, engineering_attitude, model_scene_compatible)


class CourseCompatibilityTests(unittest.TestCase):
    def test_only_reviewed_old_generation_sources_are_accepted(self):
        record = {'physics_provenance_schema': 'orekit-window-physics-lf-v1',
                  'physics_sources_sha256_lf': dict(LEGACY_WINDOW_SOURCES)}
        self.assertTrue(legacy_window_record(record))
        record['physics_sources_sha256_lf']['utils/visibility.py'] = 'changed'
        self.assertFalse(legacy_window_record(record))
        self.assertFalse(legacy_window_record({}))

    def test_new_nadir_scene_never_silently_uses_legacy_angles(self):
        provenance = {'attitude_model_version': LEGACY_ATTITUDE}
        scene = {'metadata': {'extra': {'window_generation': {'attitude_model_version': NADIR_ATTITUDE}}}}
        self.assertEqual(engineering_attitude(scene, provenance), NADIR_ATTITUDE)
        self.assertEqual(engineering_attitude({}, provenance), LEGACY_ATTITUDE)
        self.assertEqual(engineering_attitude({}, {}), NADIR_ATTITUDE)

    def test_reused_model_is_restricted_to_supported_legacy_scenes(self):
        model = {'runtime_compatibility': {'schema': 'lavis-course-compat-v1'}}
        for version in ('fresh_epoch_parsed_v1', 'epoch_fixed_v1'):
            self.assertTrue(model_scene_compatible(model, {'scenario_physics_version': version,
                'attitude_model_version': LEGACY_ATTITUDE}))
        self.assertFalse(model_scene_compatible(model, {'scenario_physics_version': 'fresh_epoch_parsed_v1',
            'attitude_model_version': NADIR_ATTITUDE}))
        self.assertFalse(model_scene_compatible(model, {'scenario_physics_version': 'unknown',
            'attitude_model_version': LEGACY_ATTITUDE}))


if __name__ == '__main__':
    unittest.main()
