// 以Cesium真实HTML的脚本顺序初始化浏览器全局，防止Node require掩盖缺失依赖。
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
test('Cesium依次加载共用比较规则及界面，能渲染有真实指标的结果',()=>{
 const html=fs.readFileSync('draw/cesium_viewer.html','utf8');
 const paths=[...html.matchAll(/<script[^>]*src="(\/static\/[^"]+)"[^>]*>/g)].map(x=>x[1]);
 const rules=paths.indexOf('/static/comparison.js'),ui=paths.indexOf('/static/experiment-ui.js');
 assert.ok(rules>=0&&rules<ui);
 assert.ok(ui<paths.indexOf('/static/cesium-experiment.js'));
 const browser={window:{}};vm.createContext(browser);
 for(const path of paths.slice(0,ui+1))vm.runInContext(fs.readFileSync('eos_system/web/'+path.split('/').pop(),'utf8'),browser);
 const API=browser.window.ExperimentUI;
 API.setCatalog([{algorithm_id:'lavis',name:'LAVIS 学习调度'}]);
 const row={run_id:'r',status:'SUCCEEDED',plan:{assignments:[]},
  config:{algorithm_id:'lavis',scenario_sha256:'s',algorithm_code_sha:'c',constraints:{},objective_weights:{},placement_mode:'earliest',seed:1,time_budget_s:10,scenario_provenance:{scenario_physics_version:'v1'}},
  metrics:{completed_tasks:1,total_tasks:2,TP:1,TCR:.5,BD:1,TM:.5,RT:1}};
 const result=API.results([{experiment_id:'e',runs:[row]}],null);
 assert.match(result,/LAVIS 学习调度/);
 assert.match(result,/50.0%/);
 assert.match(result,/data-sort-metric="TCR"/);
});
