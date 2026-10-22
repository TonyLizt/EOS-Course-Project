const {test}=require('node:test');
const assert=require('node:assert/strict');
const UI=require('../eos_system/web/experiment-ui.js');
const P=require('../eos_system/web/algorithm-parameters.js');

test('basic algorithms remain selectable alongside existing algorithms with truthful policy descriptions',()=>{
  const ids=['fcfs','sjf','priority','edf','llf','hrrn'];
  const rows=ids.map(algorithm_id=>({algorithm_id,name:algorithm_id.toUpperCase(),category:'basic',availability:'ready',
    objectives:'公共权重仅用于同序放置',limitations:'不使用初始模型解',
    parameters:{type:'object',additionalProperties:false,properties:{max_candidates_per_task:{type:'integer',minimum:1,maximum:512,default:128}}}}));
  UI.setCatalog([...rows,{algorithm_id:'dartis',name:'DARTIS',availability:'ready'},{algorithm_id:'mip'}]);
  assert.equal(UI.getCatalog().length,7);
  for(const a of rows){
    assert.equal(UI.name(a.algorithm_id),a.name);
    assert.match(UI.description(a),/非抢占式/);
    assert.match(UI.description(a),/公共权重仅用于同序放置/);
    assert.deepEqual(P.validate(a.parameters,{}),[]);
    assert.ok(P.validate(a.parameters,{max_candidates_per_task:0}).length);
    assert.match(P.render(a),new RegExp(`data-algorithm="${a.algorithm_id}"`));
  }
});
