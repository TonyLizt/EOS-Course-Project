/* Shared algorithm names, independent disclosure controls and comparison ordering. */
(function(root){
 'use strict';
 let catalog=[];
 const E=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const metrics=[['TP',1],['TCR',1],['BD',1],['TM',-1],['RT',-1],['RV',-1]];
 const name=id=>catalog.find(a=>a.algorithm_id===id)?.name||({completion_first:'完成率优先',adaptive_repair:'自适应修复'}[id])||id;
 const model=id=>({completion_first:'完成率优先',adaptive_repair:'自适应修复'}[id]||'历史未记录');
 const format=(k,v)=>v==null?'—':k==='TCR'?(v*100).toFixed(1)+'%':Number(v).toFixed(3);
 const usable=r=>r.status==='SUCCEEDED'&&!!r.plan&&!!r.metrics;
 function update(box,html){
  if(box.dataset.html===html)return;
  const active=box.contains(document.activeElement)?document.activeElement:null;
  const key=active?.dataset.focusKey,rid=active?.dataset.run,eid=active?.dataset.experiment;
  box.innerHTML=html;box.dataset.html=html;
  const selector=key?`[data-focus-key="${CSS.escape(key)}"]`:rid?`button[data-run="${CSS.escape(rid)}"]`:eid?`button[data-experiment="${CSS.escape(eid)}"]`:null;
  if(selector)box.querySelector(selector)?.focus({preventScroll:true});
 }
 function orderedRows(experiments,mode='algorithm',order=null){
  const rows=experiments.flatMap((experiment,ei)=>experiment.runs.map(run=>({experiment,run,ei})));
  if(mode==='experiment')return rows;
  if(mode==='mixed'){
   if(order===null)return rows;
   const byId=new Map(rows.map(r=>[r.run.run_id,r]));
   return [...new Set(order)].filter(id=>byId.has(id)).map(id=>byId.get(id));
  }
  const ids=[...new Set(rows.map(r=>r.run.config.algorithm_id))];
  return rows.sort((a,b)=>ids.indexOf(a.run.config.algorithm_id)-ids.indexOf(b.run.config.algorithm_id)||a.ei-b.ei);
 }
 function results(experiments,selected,mode='algorithm',order=null){
  const rows=orderedRows(experiments,mode,order);
  if(!rows.length)return '<p>暂无已选择结果；可添加算法，或在混合视图勾选结果。</p>';
  return `<div class="table-wrap" tabindex="0" aria-label="算法比较"><table><thead><tr><th scope="col">算法</th><th scope="col">实验 / 初始模型</th><th scope="col">状态 / 核验</th><th scope="col">完成任务</th>${metrics.map(([m,d])=>`<th scope="col">${m} ${d>0?'↑':'↓'}</th>`).join('')}<th scope="col">查看</th></tr></thead><tbody>${rows.map(({experiment,run,ei})=>{
   const m=usable(run)?run.metrics:null;
   const validation=run.result_kind==='planning_preview'?'曝光采样通过 · 未认证预览':run.continuous_certification?.status||'未提供';
   const status=run.status==='SUCCEEDED'&&!m?'SUCCEEDED · 计划不可用 / '+(run.continuous_certification?.status||'核验未提供'):run.status;
   return `<tr class="${run.run_id===selected?'selected':''}" ${run.run_id===selected?'aria-current="true"':''} data-run="${E(run.run_id)}"><th scope="row"><button type="button" class="select-algorithm" data-experiment="${E(experiment.experiment_id)}" data-run="${E(run.run_id)}">${E(name(run.config.algorithm_id))}</button></th><td>实验 ${ei+1} · ${E(model(run.config.schedule_model))}</td><td>${E(status)}${m?'<br>'+E(validation):''}${run.error?'<br>'+E(run.error.message):''}</td><td>${m?`${m.completed_tasks} / ${m.total_tasks}`:'—'}</td>${metrics.map(([k])=>`<td>${format(k,m?.[k])}</td>`).join('')}<td>${usable(run)?`<a href="/visualization/gantt/${E(run.run_id)}" target="_blank" rel="noopener">Gantt</a>`:'尚无计划'}</td></tr>`;
  }).join('')}</tbody></table></div>`;
 }
 function comparison(container,select,orderBox,onSelect){
  let records=[],selected=null,order=null,scope='';
  function render(){
   const all=orderedRows(records,'experiment'),ids=all.map(r=>r.run.run_id);
   if(order!==null)order=order.filter(id=>ids.includes(id));
   update(container,results(records,selected,select.value,order));
   orderBox.hidden=select.value!=='mixed';
   const active=order??ids;
   const arranged=[...active,...ids.filter(id=>!active.includes(id))];
   const map=new Map(all.map(r=>[r.run.run_id,r]));
   update(orderBox,'<p class="hint">勾选需要比较的结果；用上下箭头调整顺序。仅限当前实验及已核验的对照实验。</p>'+arranged.map(id=>{
    const {run,ei}=map.get(id),label=`${name(run.config.algorithm_id)} · 实验 ${ei+1} · ${model(run.config.schedule_model)}`;
    return `<div class="mixed-choice"><label><input type="checkbox" data-mixed-id="${E(id)}" data-focus-key="check-${E(id)}" ${active.includes(id)?'checked':''}>${E(label)}</label><button type="button" data-move="${E(id)}" data-delta="-1" data-focus-key="up-${E(id)}" aria-label="上移 ${E(label)}" ${active.indexOf(id)<=0?'disabled':''}>↑</button><button type="button" data-move="${E(id)}" data-delta="1" data-focus-key="down-${E(id)}" aria-label="下移 ${E(label)}" ${!active.includes(id)||active.indexOf(id)===active.length-1?'disabled':''}>↓</button></div>`;
   }).join(''));
  }
  select.addEventListener('change',render);
  orderBox.addEventListener('change',event=>{
   const input=event.target.closest('[data-mixed-id]');if(!input)return;
   order=order??orderedRows(records,'experiment').map(r=>r.run.run_id);
   order=order.filter(id=>id!==input.dataset.mixedId);if(input.checked)order.push(input.dataset.mixedId);render();
  });
  orderBox.addEventListener('click',event=>{
   const button=event.target.closest('[data-move]');if(!button)return;
   order=order??orderedRows(records,'experiment').map(r=>r.run.run_id);
   const i=order.indexOf(button.dataset.move),j=i+Number(button.dataset.delta);
   if(i>=0&&j>=0&&j<order.length)[order[i],order[j]]=[order[j],order[i]];render();
  });
  container.addEventListener('click',event=>{const b=event.target.closest('.select-algorithm');if(b)onSelect(b.dataset.experiment,b.dataset.run);});
  return {set(next,id){const key=next.map(e=>e.experiment_id).join('|');if(key!==scope){scope=key;order=null;}records=next;selected=id;render();}};
 }
 function card(prefix,id,heading,content,extra=''){
  const control=`algo-${prefix}-${id}`;
  return `<div class="algorithm-card ${extra}"><div class="algorithm-heading">${heading}<button type="button" class="algorithm-toggle" data-toggle="${E(control)}" aria-expanded="false" aria-controls="${E(control)}" aria-label="展开或收起 ${E(name(id))} 的参数和说明"><span aria-hidden="true">▶</span></button></div><div class="algorithm-content" id="${E(control)}" hidden>${content}</div></div>`;
 }
 function bindCards(box){
  if(box.dataset.disclosuresBound)return;box.dataset.disclosuresBound='true';
  box.addEventListener('click',event=>{const b=event.target.closest('[data-toggle]');if(!b)return;const content=document.getElementById(b.dataset.toggle);if(!content)return;const open=b.getAttribute('aria-expanded')!=='true';b.setAttribute('aria-expanded',String(open));content.hidden=!open;});
 }
 function description(a){return `<p>${E(a.strategy||a.description||'')}</p><p>${E(a.objectives||'')}</p><p>${E(a.availability_message||a.limitations||'')}</p>`;}
 function available(box,experiment,add){
  const ids=new Set(experiment.runs.map(r=>r.config.algorithm_id)),key=experiment.experiment_id+JSON.stringify([...ids]);
  if(box.dataset.key===key)return;box.dataset.key=key;
  box.innerHTML='<h3>完整算法列表 · 新增算法</h3><p class="hint" role="status">已选择的算法显示为灰色，不可重复添加。移除保留历史及文件。</p>'+catalog.map(a=>{
   const included=ids.has(a.algorithm_id),disabled=included||a.availability!=='ready';
   return card(box.id,a.algorithm_id,`<span class="algorithm-choice">${E(a.name)} · ${included?'已选择':disabled?'不可用':'可新增'}</span>`,description(a)+`<label>算法参数 JSON<textarea data-params="${E(a.algorithm_id)}" rows="2" ${disabled?'disabled':''}>{}</textarea></label><button type="button" data-add="${E(a.algorithm_id)}" ${disabled?'disabled':''}>${included?'已在实验中':'新增此算法'}</button>`,included?'included':'');
  }).join('');
  bindCards(box);
  box.querySelectorAll('[data-add]').forEach(button=>button.addEventListener('click',async()=>{
   button.disabled=true;
   try{const raw=JSON.parse(box.querySelector(`[data-params="${CSS.escape(button.dataset.add)}"]`).value);if(!raw||Array.isArray(raw)||typeof raw!=='object')throw Error('算法参数必须是 JSON 对象');await add(button.dataset.add,raw);}
   catch(error){box.querySelector('.hint').textContent=error.message;}
   finally{if(button.isConnected)button.disabled=false;}
  }));
 }
 const api={E,name,model,format,usable,results,available,update,orderedRows,comparison,card,bindCards,description,setCatalog:v=>{catalog=v;},getCatalog:()=>catalog};
 if(typeof module==='object'&&module.exports)module.exports=api;else root.ExperimentUI=api;
})(typeof window==='undefined'?globalThis:window);
