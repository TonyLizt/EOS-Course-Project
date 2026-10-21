/* 交付入口策略与跨页导出交互，使用真实脚本而非复制其实现。 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const UI=require('../eos_system/web/experiment-ui.js');
test('交付选择入口保留PPO，仅隐藏MIP，其他算法与既有指标保留',()=>{
 const catalog=['mip','ppo','lavis','caabs','rabas','darts','profit_first'].map(algorithm_id=>({algorithm_id}));
 assert.deepEqual(UI.visibleCatalog(catalog).map(a=>a.algorithm_id),['ppo','lavis','caabs','rabas','darts','profit_first']);
 const comparison=require('../eos_system/web/comparison.js');
 assert.deepEqual(comparison.metrics.map(m=>m[0]),['TP','TCR','BD','TM','RT']);
});
test('跨页选择、下载范围与失败恢复不丢失选择',async()=>{
 const events={}, count={textContent:''},all={},messages=[{textContent:''}];
 const button={dataset:{exportScope:'selected',exportFormat:'zip'}}, currentButton={dataset:{exportScope:'current'}};
 const buttons=[button,currentButton];let captured,clicked=0,revoked=0;
 const document={
  addEventListener:(k,f)=>events[k]=f,
  querySelectorAll:s=>s==='[data-stat-export]'?buttons:s==='[data-export-message]'?messages:[],
  getElementById:id=>({'export-selection-count':count,'select-export-page':all,'export-include-removed':{checked:false}}[id]),
  createElement:()=>({click(){clicked++},remove(){}}),body:{append(){}}
 };
 const ctx={document,window:{},ExperimentUI:{E:x=>x},Set,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL:()=>revoked++},
  setTimeout:fn=>fn(),fetch:async(_url,opts)=>{captured=JSON.parse(opts.body);return {ok:true,blob:async()=>({}),headers:{get:()=> 'attachment; filename="eos-statistics.zip"'}}}};
 vm.runInNewContext(fs.readFileSync('eos_system/web/statistics-export.js','utf8'),ctx);
 const api=ctx.window.ExperimentExports;
 api.setPage([{experiment_id:'a'}]);
 events.change({target:{id:'select-export-page',checked:true,matches:()=>false}});
 api.setPage([{experiment_id:'b'}]);
 assert.match(count.textContent,/1/);assert.equal(all.checked,false);
 await events.click({target:{closest:s=>s==='[data-stat-export]'?button:null}});
 assert.deepEqual(captured.experiment_ids,['a']);assert.equal(captured.format,'zip');
 assert.equal(clicked,1);assert.equal(revoked,1);assert.equal(button.disabled,false);
 assert.equal(currentButton.disabled,true);
 ctx.fetch=async()=>({ok:false,json:async()=>({error:{message:'分批导出'}})});
 await events.click({target:{closest:s=>s==='[data-stat-export]'?button:null}});
 assert.equal(messages[0].textContent,'分批导出');assert.equal(button.disabled,false);
 assert.match(count.textContent,/1/);
});


test('R1：不同训练目标模型共享请求目标时同组，目标不同仍隔离',()=>{
 const compare=require('../eos_system/web/comparison.js');
 const goal={w_profit:.5,w_completion:.3,w_timeliness:.1,w_balance:.1};
 const base={scenario_sha256:'a'.repeat(64),algorithm_code_sha:'b'.repeat(64),
  constraints:{agility_profile:'Standard-Agility'},placement_mode:'earliest',seed:42,time_budget_s:5,
  execution_mode:'physical_validation',objective_weights:goal,
  scenario_provenance:{scenario_physics_version:'fresh_epoch_parsed_v1'}};
 const runs=['ppo','lavis','caabs'].map((aid,i)=>({run_id:aid,status:'SUCCEEDED',
  config:{...base,algorithm_id:aid,model_provenance:{model_id:aid+'-real-id'},
   objective_adapter:{training_objective:i===0?'TP':i===1?'TCR':null,requested_objective:goal,effective_objective:goal}},
  metrics:{TP:10,TCR:.5,BD:.8,TM:.2,RT:1,metric_schema_version:'existing'},
  continuous_certification:{status:'INCONCLUSIVE'},ranking_score:{value:null}}));
 assert.equal(compare.groupRuns(runs).length,1);
 assert.equal(compare.best(compare.groupRuns(runs)[0],'TP',1),null);
 assert.equal(compare.groupRuns([runs[0],{...runs[1],config:{...runs[1].config,objective_weights:{...goal,w_profit:1}}}]).length,2);
});
