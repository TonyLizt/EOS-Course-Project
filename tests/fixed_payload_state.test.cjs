const assert = require('node:assert/strict');
const state = require('../draw/fixed-payload-state.js');

function close(a, b, epsilon = 1e-9) {
  assert.equal(a.length, b.length);
  a.forEach((value, index) => assert.ok(Math.abs(value - b[index]) < epsilon, `${value} != ${b[index]}`));
}

const q = state.pointingQuaternion([7000000, 0, 0], [6378137, 0, 0]);
close(state.rotate(q, [0, 0, -1]), [-1, 0, 0]);
close(state.slerp([0, 0, 0, 1], [0, 0, 0, -1], 0.5), [0, 0, 0, 1]);

const segments = [{satellite_id: 'S1', task_id: 'M1', sensor_id: 'camera', phase: 'OBSERVING', start_time: '2026-01-01T00:00:00Z', end_time: '2026-01-01T00:00:10Z'}];
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
const forbiddenPosition=() => {throw new Error('READY 不应重新求轨道');};
const visibleTarget=() => [6378137,0,0];
const middle=state.evaluateSatelliteState(replay,'S1','2026-01-01T00:00:05Z',forbiddenPosition,visibleTarget);
close(middle.position_ecef_m,[7000050,0,0]);
close(middle.body_to_ecef_quaternion_xyzw,[0,0,0,1]);
assert.equal(middle.phase,'OBSERVING');
assert.equal(middle.cone_visible,true);
assert.equal(middle.target_visibility,'VISIBLE');
const end=state.evaluateSatelliteState(replay,'S1','2026-01-01T00:00:10Z',forbiddenPosition,visibleTarget);
assert.equal(end.phase,'IDLE');
assert.equal(end.cone_visible,false);
assert.equal(state.evaluateSatelliteState(replay,'S1','2026-01-01T00:00:11Z',forbiddenPosition,visibleTarget).quality,'missing');
assert.equal(state.targetVisibility([7000000,0,0],[6378137,0,0]),'VISIBLE');
assert.equal(state.targetVisibility([-3650549,-1177802,-5524624],[-1916648,-4895487,3599165]),'EARTH_OCCLUDED');
const occluded=state.evaluateSatelliteState(replay,'S1','2026-01-01T00:00:05Z',
  forbiddenPosition,() => [-6378137,0,0]);
assert.equal(occluded.target_visibility,'EARTH_OCCLUDED');
assert.equal(occluded.geometry_valid,false);
assert.equal(occluded.cone_visible,false);
assert.ok(occluded.warnings.includes('TARGET_EARTH_OCCLUDED'));
console.log('authoritative READY sample interpolation and half-open boundary tests passed');

// 多星索引不得串星，二分阶段须维持左闭右开；未知星不能借用上一颗星。
const many={samples:[],satellites:[],segments:[],warnings:[]};
for(let i=0;i<50;i++) {
  const id='sat-'+i;
  many.satellites.push({id,sensors:[{sensor_id:'camera',sensor_mount_quaternion_xyzw:[0,0,0,1]}]});
  for(const seconds of [0,10]) many.samples.push({
    satellite_id:id,time:'2026-01-01T00:00:'+String(seconds).padStart(2,'0')+'Z',
    position_ecef_m:[7000000,i,0],body_to_ecef_quaternion_xyzw:[0,0,0,1],quality:'illustration_only'});
  many.segments.push({satellite_id:id,phase:'OBSERVING',task_id:'task-'+i,sensor_id:'camera',
    start_time:'2026-01-01T00:00:02Z',end_time:'2026-01-01T00:00:04Z'});
}
for(let i=0;i<50;i++) {
  const value=state.evaluateSatelliteState(many,'sat-'+i,'2026-01-01T00:00:03Z',forbiddenPosition,visibleTarget);
  assert.equal(value.task_id,'task-'+i);
  close([value.position_ecef_m[1]],[i]);
  assert.equal(state.evaluateSatelliteState(many,'sat-'+i,'2026-01-01T00:00:04Z',forbiddenPosition,visibleTarget).phase,'IDLE');
}
assert.equal(state.evaluateSatelliteState(many,'absent','2026-01-01T00:00:03Z',forbiddenPosition,visibleTarget).quality,'missing');
console.log('50-satellite indexed state isolation passed');

// Microsecond phase boundaries and READY interpolation must not pass through
// Date's millisecond truncation. These are new regressions, not changed oracles.
const microSegments=[{satellite_id:'S1',phase:'OBSERVING',task_id:'micro',sensor_id:'camera',
 start_time:'2025-11-18T12:00:00.123456Z',end_time:'2025-11-18T12:00:00.123458Z'}];
assert.equal(state.phaseAt(microSegments,'S1','2025-11-18T12:00:00.123455Z'),null);
assert.equal(state.phaseAt(microSegments,'S1','2025-11-18T20:00:00.123456+08:00').task_id,'micro');
assert.equal(state.phaseAt(microSegments,'S1','2025-11-18T12:00:00.123457Z').task_id,'micro');
assert.equal(state.phaseAt(microSegments,'S1','2025-11-18T12:00:00.123458Z'),null);
const microReplay={...replay,segments:microSegments,samples:[
 {...replay.samples[0],time:'2025-11-18T12:00:00.123456Z',position_ecef_m:[7000000,0,0]},
 {...replay.samples[1],time:'2025-11-18T12:00:00.123458Z',position_ecef_m:[7000002,0,0]}
]};
const microMiddle=state.evaluateSatelliteState(microReplay,'S1','2025-11-18T12:00:00.123457Z',forbidden,forbidden);
close(microMiddle.position_ecef_m,[7000001,0,0]);
assert.equal(microMiddle.phase,'OBSERVING');
assert.equal(state.evaluateSatelliteState(microReplay,'S1','2025-11-18T12:00:00.123458Z',forbidden,forbidden).phase,'IDLE');
assert.throws(()=>state.phaseAt(microSegments,'S1','not-a-time'),/time/i);
console.log('microsecond phase and READY interpolation passed');
