const assert = require('node:assert/strict');
const state = require('../draw/fixed-payload-state.js');
const base=Date.UTC(2025,10,18,12,0,0);
function iso(seconds) {
  const us=BigInt(Math.round(seconds*1000000))+123456n;
  return new Date(base+Number(us/1000n)).toISOString().replace(/\.\d{3}Z$/,'.'+String(us%1000000n).padStart(6,'0')+'Z');
}
const position=s=>[7000000*Math.cos(.0012*s),7000000*Math.sin(.0012*s),300000*Math.sin(.0012*s)];
const replay={satellites:[{id:'S1',sensors:[{sensor_id:'camera',sensor_mount_quaternion_xyzw:[0,0,0,1]}]}],
 segments:[],warnings:[],samples:Array.from({length:11},(_,i)=>({satellite_id:'S1',time:iso(i*60),
 position_ecef_m:position(i*60),body_to_ecef_quaternion_xyzw:[0,0,0,1],quality:'illustration_only'}))};
const forbidden=()=>{throw new Error('READY must not propagate or solve another pose');};
for(const seconds of [0,1,30,37.5,147.3,150,225,300,375,449.3,450,599,600]) {
 const result=state.evaluateSatelliteState(replay,'S1',iso(seconds),forbidden,forbidden);
 const error=Math.hypot(...result.position_ecef_m.map((x,i)=>x-position(seconds)[i]));
 assert.ok(error<.1,'curved position error at '+seconds+': '+error);
 assert.equal(result.phase,'IDLE');
 assert.deepEqual(result.body_to_ecef_quaternion_xyzw,[0,0,0,1]);
}
for(let i=0;i<11;i++) {
 const result=state.evaluateSatelliteState(replay,'S1',iso(i*60),forbidden,forbidden);
 assert.deepEqual(result.position_ecef_m,position(i*60),'exact knot must be unchanged');
}
assert.equal(state.evaluateSatelliteState(replay,'S1',iso(601),forbidden,forbidden).quality,'missing');
console.log('independent orbit interpolation checks passed');

if(process.argv.includes('--fixture')) {
 const fs=require('node:fs');
 const input=JSON.parse(fs.readFileSync(process.argv[process.argv.indexOf('--fixture')+1],'utf8'));
 let maximum=0;
 for(const query of input.queries) {
  const actual=state.evaluateSatelliteState(input.replay,query.satellite,query.time,forbidden,forbidden);
  assert.ok(actual.position_ecef_m,'missing READY position at '+query.time);
  const error=Math.hypot(...actual.position_ecef_m.map((x,i)=>x-query.truth_m[i]));
  assert.ok(error<input.max_error_m,query.satellite+' at '+query.offset_s+': '+error+' >= '+input.max_error_m);
  maximum=Math.max(maximum,error);
 }
 console.log(JSON.stringify({queries:input.queries.length,max_error_m:maximum,tolerance_m:input.max_error_m}));
}
