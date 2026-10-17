const test=require('node:test'),assert=require('node:assert/strict');
const UI=require('../eos_system/web/experiment-ui.js'),T=require('../eos_system/web/timeline.js');
const run=(id,algorithm)=>({run_id:id,config:{algorithm_id:algorithm},status:'FAILED',metrics:{TP:99}});
const experiments=[{experiment_id:'one',runs:[run('a','sa'),run('b','ga')]},{experiment_id:'two',runs:[run('c','sa'),run('d','ga')]}];
test('two grouped views select and reorder a bounded result set without changing records',()=>{
 const before=JSON.stringify(experiments),ids=(mode,order)=>UI.orderedRows(experiments,mode,order).map(r=>r.run.run_id);
 assert.deepEqual(ids('algorithm'),['a','c','b','d']);assert.deepEqual(ids('experiment'),['a','b','c','d']);
 assert.deepEqual(ids('algorithm',['c','a','outside','d','b','c']),['c','a','d','b']);
 assert.deepEqual(ids('experiment',['b','a','outside','d','c']),['b','a','d','c']);assert.deepEqual(ids('algorithm',[]),[]);
 assert.equal(JSON.stringify(experiments),before);
});
test('failed or unavailable plans cannot display successful metrics',()=>{
 UI.setCatalog([{algorithm_id:'sa',name:'模拟退火 SA'},{algorithm_id:'ga',name:'遗传算法 GA'}]);
 const html=UI.results(experiments,'a');assert.match(html,/模拟退火 SA/);assert.doesNotMatch(html,/99\.000/);
 assert.doesNotMatch(html,/console-1|条件组/);assert.match(html,/aria-current="true"/);
});
test('one independently labelled triangle controls the card, not its checkbox',()=>{
 const html=UI.card('test','sa','<label><input type="checkbox">模拟退火 SA</label>','details');
 assert.equal((html.match(/<button/g)||[]).length,1);assert.match(html,/aria-expanded="false"/);
 assert.match(html,/aria-controls="algo-test-sa"/);assert.match(html,/aria-hidden="true">▶/);
});
test('magnetic hit uses screen distance, exact hits and lanes, with bounded radius',()=>{
 const bars=[{id:'a',left:10,right:11,top:10,bottom:36},{id:'b',left:22,right:23,top:10,bottom:36},
             {id:'c',left:10,right:11,top:44,bottom:70}];
 assert.equal(T.magneticHit({x:8,y:20},bars),'a');assert.equal(T.magneticHit({x:22.5,y:20},bars),'b');
 assert.equal(T.magneticHit({x:10.5,y:50},bars),'c');assert.equal(T.magneticHit({x:100,y:20},bars),null);
 assert.equal(T.magneticHit({x:16.5,y:20},bars),null); // Ambiguous midpoint.
 const before=JSON.stringify(bars);T.magneticHit({x:8,y:20},bars);assert.equal(JSON.stringify(bars),before);
});
