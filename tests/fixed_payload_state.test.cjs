const assert = require('node:assert/strict');
const state = require('../draw/fixed-payload-state.js');

function close(a, b, epsilon = 1e-9) {
  assert.equal(a.length, b.length);
  a.forEach((value, index) => assert.ok(Math.abs(value - b[index]) < epsilon, `${value} != ${b[index]}`));
}

const q = state.pointingQuaternion([7000000, 0, 0], [6378137, 0, 0]);
close(state.rotate(q, [0, 0, -1]), [-1, 0, 0]);
close(state.slerp([0, 0, 0, 1], [0, 0, 0, -1], 0.5), [0, 0, 0, 1]);

const segments = [{satellite_id: 'S1', phase: 'OBSERVING', start_time: '2026-01-01T00:00:00Z', end_time: '2026-01-01T00:00:10Z'}];
assert.equal(state.phaseAt(segments, 'S1', '2026-01-01T00:00:00Z').phase, 'OBSERVING');
assert.equal(state.phaseAt(segments, 'S1', '2026-01-01T00:00:10Z'), null);
assert.equal(state.phaseAt(segments, 'S1', '2025-12-31T23:59:59Z'), null);
console.log('fixed payload state tests passed');
