/* 交付入口策略与跨页导出交互，使用真实脚本而非复制其实现。 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const UI=require('../eos_system/web/experiment-ui.js');
test('交付选择入口隐藏MIP/PPO，其他算法与既有指标保留',()=>{
 const catalog=['mip','ppo','lavis','caabs','rabas','darts','profit_first'].map(algorithm_id=>({algorithm_id}));
 assert.deepEqual(UI.visibleCatalog(catalog).map(a=>a.algorithm_id),['lavis','caabs','rabas','darts','profit_first']);
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
