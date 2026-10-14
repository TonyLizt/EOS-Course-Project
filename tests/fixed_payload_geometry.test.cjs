const assert = require('node:assert/strict');
const geometry = require('../draw/fixed-payload-geometry.js');
const state = require('../draw/fixed-payload-state.js');

function close(left, right, epsilon = 1e-9) {
  assert.equal(left.length, right.length);
  left.forEach((value, index) => {
    assert.ok(Math.abs(value - right[index]) < epsilon, `${value} != ${right[index]}`);
  });
}

function unitSphereIntersection(origin, direction) {
  const b = 2 * origin.reduce((sum, value, index) => sum + value * direction[index], 0);
  const c = origin.reduce((sum, value) => sum + value * value, 0) - 1;
  const discriminant = b * b - 4 * c;
  if (discriminant < 0) return null;
  const roots = [(-b - Math.sqrt(discriminant)) / 2, (-b + Math.sqrt(discriminant)) / 2]
    .filter((value) => value >= 0)
    .sort((left, right) => left - right);
  return roots.length ? origin.map((value, index) => value + roots[0] * direction[index]) : null;
}

const sensor = {
  sensor_offset_body_m: [0, 0, 0],
  horizontal_full_fov_deg: 20,
  vertical_full_fov_deg: 20,
  fov_interpretation: 'square_full_angle_display_assumption'
};
const payloadState = {
  position_ecef_m: [2, 0, 0],
  body_to_ecef_quaternion_xyzw: state.pointingQuaternion([2, 0, 0], [0, 0, 0]),
  camera_to_ecef_quaternion_xyzw: state.pointingQuaternion([2, 0, 0], [0, 0, 0])
};
const frame = geometry.sensorFrame(payloadState, sensor, state.rotate, 3);
assert.equal(frame.boundary_directions_ecef.length, 12);
close(frame.center_direction_ecef, [-1, 0, 0]);
const complete = geometry.intersectFrame(frame, unitSphereIntersection);
assert.equal(complete.status, 'COMPLETE');
assert.equal(complete.coverage_ecef_m.length, 12);
assert.equal(complete.frustum_boundary_ecef_m.length, 12);
assert.ok(complete.frustum_range_m > 0);
close(complete.center_hit_ecef_m, [1, 0, 0]);

let call = 0;
const partial = geometry.intersectFrame(frame, (origin, direction) => {
  call += 1;
  return call % 3 === 0 ? null : unitSphereIntersection(origin, direction);
});
assert.equal(partial.status, 'PARTIAL_HORIZON');
assert.equal(partial.coverage_ecef_m, null);
assert.equal(partial.frustum_boundary_ecef_m.length, 12);
assert.ok(partial.boundary_hits_ecef_m.some(Boolean));
assert.ok(partial.boundary_hits_ecef_m.some((value) => value === null));

const none = geometry.intersectFrame(frame, () => null);
assert.equal(none.status, 'NO_BOUNDARY_INTERSECTION');
assert.equal(none.center_hit_ecef_m, null);
assert.equal(none.coverage_ecef_m, null);
assert.equal(none.frustum_boundary_ecef_m.length, 12);
assert.equal(none.frustum_range_m, 750000);

assert.equal(geometry.phaseStyle('SLEWING').name, 'slewing');
assert.equal(geometry.phaseStyle('OBSERVING').name, 'observing');
assert.equal(geometry.phaseStyle('IDLE').visible, false);

const phases = [
  { satellite_id: 'S1', phase: 'SLEWING', start_time: '2026-01-01T00:00:00Z', end_time: '2026-01-01T00:00:05Z' },
  { satellite_id: 'S1', phase: 'OBSERVING', start_time: '2026-01-01T00:00:05Z', end_time: '2026-01-01T00:00:10Z' },
  { satellite_id: 'S2', phase: 'OBSERVING', start_time: '2026-01-01T00:00:03Z', end_time: '2026-01-01T00:00:08Z' }
];
assert.equal(geometry.phaseStyle(state.phaseAt(phases, 'S1', '2026-01-01T00:00:00Z').phase).name, 'slewing');
assert.equal(geometry.phaseStyle(state.phaseAt(phases, 'S1', '2026-01-01T00:00:05Z').phase).name, 'observing');
assert.equal(state.phaseAt(phases, 'S1', '2026-01-01T00:00:10Z'), null);
assert.equal(state.phaseAt(phases, 'S2', '2026-01-01T00:00:04Z').phase, 'OBSERVING');
assert.equal(state.phaseAt(phases, 'S1', '2026-01-01T00:00:04Z').phase, 'SLEWING');
console.log('fixed payload geometry tests passed');
