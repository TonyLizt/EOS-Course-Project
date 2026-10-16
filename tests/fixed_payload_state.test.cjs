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

// READY 样本是唯一数据源：不能再调用轨道/目标回调重新推导另一套姿态。
const replay = {
  samples: [
    {satellite_id:'S1',time:'2026-01-01T00:00:00Z',position_ecef_m:[7000000,0,0],body_to_ecef_quaternion_xyzw:[0,0,0,1],quality:'illustration_only'},
    {satellite_id:'S1',time:'2026-01-01T00:00:10Z',position_ecef_m:[7000100,0,0],body_to_ecef_quaternion_xyzw:[0,0,0,-1],quality:'illustration_only'}
  ],
  satellites:[{id:'S1',sensors:[{sensor_id:'camera',sensor_mount_quaternion_xyzw:[0,0,0,1]}]}],
  segments, warnings:[]
};
const forbidden=() => {throw new Error('READY 不应重新求轨道/目标');};
const middle=state.evaluateSatelliteState(replay,'S1','2026-01-01T00:00:05Z',forbidden,forbidden);
close(middle.position_ecef_m,[7000050,0,0]);
close(middle.body_to_ecef_quaternion_xyzw,[0,0,0,1]);
assert.equal(middle.phase,'OBSERVING');
assert.equal(middle.cone_visible,true);
const end=state.evaluateSatelliteState(replay,'S1','2026-01-01T00:00:10Z',forbidden,forbidden);
assert.equal(end.phase,'IDLE');
assert.equal(end.cone_visible,false);
assert.equal(state.evaluateSatelliteState(replay,'S1','2026-01-01T00:00:11Z',forbidden,forbidden).quality,'missing');
console.log('authoritative READY sample interpolation and half-open boundary tests passed');
