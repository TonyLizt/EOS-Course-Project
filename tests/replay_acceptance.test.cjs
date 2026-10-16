const assert = require('node:assert/strict');
const state = require('../draw/fixed-payload-state.js');
const geometry = require('../draw/fixed-payload-geometry.js');
const payloadView = require('../draw/fixed-payload-view.js');

const identitySensor = (satelliteId) => ({
  satellite_id: satelliteId,
  sensor_id: satelliteId + '-sensor',
  sensor_mount_quaternion_xyzw: [0, 0, 0, 1],
  sensor_offset_body_m: [0, 0, 0],
  horizontal_full_fov_deg: 45,
  vertical_full_fov_deg: 45,
  fov_interpretation: 'square_full_angle_display_assumption'
});
const replay = {
  manifest: { attitude_source: 'geometry_pointing_illustration' },
  warnings: ['display only'],
  satellites: [
    { id: 'S1', maneuverability_type: 'agile', sensors: [identitySensor('S1')] },
    { id: 'S2', maneuverability_type: 'agile', sensors: [identitySensor('S2')] },
    { id: 'S3', maneuverability_type: 'non-agile', sensors: [identitySensor('S3')] }
  ],
  segments: [
    { satellite_id: 'S1', task_id: 'M1', sensor_id: 'S1-sensor', phase: 'OBSERVING',
      start_time: '2026-01-01T23:59:40Z', end_time: '2026-01-01T23:59:50Z', assignment_ordinal: 0 },
    { satellite_id: 'S1', task_id: 'M2', sensor_id: 'S1-sensor', phase: 'SLEWING',
      start_time: '2026-01-01T23:59:50Z', end_time: '2026-01-02T00:00:00Z',
      activation_time: '2026-01-01T23:59:50Z', from_assignment_ordinal: 0, assignment_ordinal: 1 },
    { satellite_id: 'S1', task_id: 'M2', sensor_id: 'S1-sensor', phase: 'OBSERVING',
      start_time: '2026-01-02T00:00:00Z', end_time: '2026-01-02T00:00:10Z', assignment_ordinal: 1 },
    { satellite_id: 'S2', task_id: 'M3', sensor_id: 'S2-sensor', phase: 'OBSERVING',
      start_time: '2026-01-01T23:59:45Z', end_time: '2026-01-02T00:00:05Z', assignment_ordinal: 2 }
  ]
};
const positions = {
  S1: [7000000, 0, 0],
  S2: [0, 7000000, 0],
  S3: [0, 0, 7000000]
};
const targets = { M1: [6378137, 0, 0], M2: [-6378137, 1000, 0], M3: [0, 6378137, 0] };
const positionAt = (satelliteId) => positions[satelliteId] || null;
const targetAt = (taskId) => targets[taskId];

const timestamp = '2026-01-01T23:59:47Z';
const first = state.evaluateSatelliteState(replay, 'S1', timestamp, positionAt, targetAt);
state.evaluateSatelliteState(replay, 'S2', '2026-01-02T00:00:01Z', positionAt, targetAt);
const repeated = state.evaluateSatelliteState(replay, 'S1', timestamp, positionAt, targetAt);
assert.deepEqual(repeated, first, 'state must not depend on call order or history');
assert.equal(first.phase, 'OBSERVING');
assert.equal(state.evaluateSatelliteState(
  replay, 'S1', '2026-01-01T23:59:55Z', positionAt, targetAt
).phase, 'SLEWING');
assert.equal(state.evaluateSatelliteState(
  replay, 'S1', '2026-01-02T00:00:00Z', positionAt, targetAt
).phase, 'OBSERVING');
assert.equal(state.evaluateSatelliteState(
  replay, 'S1', '2026-01-02T00:00:10Z', positionAt, targetAt
).phase, 'IDLE');
assert.equal(state.evaluateSatelliteState(
  replay, 'S2', '2026-01-02T00:00:01Z', positionAt, targetAt
).phase, 'OBSERVING', 'multiple satellites must remain independently active');

const noTask = state.evaluateSatelliteState(replay, 'S3', timestamp, positionAt, targetAt);
assert.equal(noTask.phase, 'IDLE');
assert.equal(noTask.task_id, null);
assert.equal(payloadView.cameraPose(noTask).quality, 'geometry_pointing_illustration');
const missing = state.evaluateSatelliteState(replay, 'S3', timestamp, () => null, targetAt);
assert.equal(missing.quality, 'missing');
assert.deepEqual(missing.warnings, ['ORBIT_DATA_MISSING']);

const frame = geometry.sensorFrame(first, replay.satellites[0].sensors[0], state.rotate, 4);
assert.equal(frame.boundary_directions_ecef.length, 16);
assert.ok(frame.boundary_directions_ecef.every((direction) => direction.every(Number.isFinite)));
assert.equal(frame.fov_interpretation, 'square_full_angle_display_assumption');
console.log('replay acceptance tests passed');
