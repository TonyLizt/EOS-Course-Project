const assert = require('node:assert/strict');
const view = require('../draw/fixed-payload-view.js');

const pose = view.cameraPose({
  position_ecef_m: [1, 2, 3],
  direction_ecef: [0, 0, -1],
  up_ecef: [0, 1, 0],
  body_to_ecef_quaternion_xyzw: [0, 0, 0, 1],
  camera_to_ecef_quaternion_xyzw: [0, 0.5, 0, 0.5],
  phase: 'SLEWING',
  task_id: 'M1',
  sensor_id: 'C1',
  target_visibility: 'EARTH_OCCLUDED',
  geometry_valid: false,
  quality: 'geometry_pointing_illustration'
});
assert.deepEqual(pose.position_ecef_m, [1, 2, 3]);
assert.deepEqual(pose.body_to_ecef_quaternion_xyzw, [0, 0, 0, 1]);
assert.deepEqual(pose.camera_to_ecef_quaternion_xyzw, [0, 0.5, 0, 0.5]);
assert.equal(view.statusText('S1', pose), 'S1 | SLEWING | task M1 | EARTH OCCLUDED | geometry_pointing_illustration');
assert.equal(pose.geometry_valid, false);
assert.equal(view.cameraPose(null), null);

assert.deepEqual(view.missionDisplay({
  id: 'M1',
  target_location: { latitude: 22.302711, longitude: 114.177216, altitude_km: 0.15 }
}), {
  id: 'M1',
  latitude: 22.302711,
  longitude: 114.177216,
  altitude_m: 150,
  label: 'M1\n22.3027°, 114.1772°'
});
assert.equal(view.missionDisplay({ id: 'broken' }), null);

const square = view.opticalFrustum({
  horizontal_full_fov_deg: 45,
  vertical_full_fov_deg: 45,
  fov_interpretation: 'square_full_angle_display_assumption'
});
assert.ok(Math.abs(square.aspect_ratio - 1) < 1e-12);
assert.deepEqual(view.viewportBox(320, 180, square.aspect_ratio), {
  width: 180, height: 180, left: 70, top: 0
});
assert.deepEqual(view.viewportBox(180, 320, square.aspect_ratio), {
  width: 180, height: 180, left: 0, top: 70
});
assert.throws(() => view.opticalFrustum({ horizontal_full_fov_deg: 0, vertical_full_fov_deg: 45 }));
console.log('fixed payload view tests passed');
