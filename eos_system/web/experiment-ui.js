/* Shared algorithm names, disclosure controls and stable comparison groups. */
(function(root){
 'use strict';
 let catalog=[];
 // 保留MIP的交付隐藏策略；PPO与其他算法统一按后端可用性显示和禁用。
 const visibleCatalog=items=>items.filter(item=>item.algorithm_id!=='mip');
 const Rules = typeof module==='object' && module.exports ? require('./comparison.js') : root.RunComparison;
 const E=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const metrics=[['TP',1],['TCR',1],['BD',1],['TM',-1],['RT',-1]];
 const name=id=>catalog.find(a=>a.algorithm_id===id)?.name||({completion_first:'完成率优先',adaptive_repair:'自适应修复'}[id])||id;
 const model=id=>({completion_first:'完成率优先',adaptive_repair:'自适应修复'}[id]||'历史未记录');
 const format=(k,v)=>v==null?'—':k==='TCR'?(v*100).toFixed(1)+'%':Number(v).toFixed(3);
 const usable=r=>r.status==='SUCCEEDED'&&!!(r.plan||(r.temporary&&r.has_plan))&&!!r.metrics;
 function update(box,html){
  if(box.dataset.html===html)return;
  const active=box.contains(document.activeElement)?document.activeElement:null;
  const key=active?.dataset.focusKey,rid=active?.dataset.run,eid=active?.dataset.experiment;
  box.innerHTML=html;box.dataset.html=html;
  const selector=key?`[data-focus-key="${CSS.escape(key)}"]`:rid?`button[data-run="${CSS.escape(rid)}"]`:eid?`button[data-experiment="${CSS.escape(eid)}"]`:null;
  if(selector)box.querySelector(selector)?.focus({preventScroll:true});
 }
 function orderedRows(experiments,mode='algorithm',selectedIds=null,sortMetric='',direction='desc'){
  let rows=experiments.flatMap((experiment,ei)=>experiment.runs.map(run=>({experiment,run,ei})));
  if(selectedIds!==null){const chosen=new Set(selectedIds);rows=rows.filter(r=>chosen.has(r.run.run_id));}
  const ids=[...new Set(rows.map(r=>r.run.config.algorithm_id))];
  rows.sort(mode==='experiment'?(a,b)=>a.ei-b.ei:(a,b)=>ids.indexOf(a.run.config.algorithm_id)-ids.indexOf(b.run.config.algorithm_id));
  if(!sortMetric)return rows;
  // 不跨场景、预算、初始模型或并发合同争夺名次；未知条件不强行合组。
  const groups=new Map();
  for(const row of rows){
    const key=Rules.identified(row.run)?JSON.stringify(Rules.conditions(row.run)):'unknown:'+row.run.run_id;
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);
  }
  const value=row=>{
    if(!usable(row.run)||(row.run.continuous_certification?.status==='INCONCLUSIVE'&&!row.run.temporary))return null;
    const v=sortMetric==='SCORE'?row.run.ranking_score?.value:row.run.metrics?.[sortMetric];
    return typeof v==='number'&&Number.isFinite(v)?v:null;
  };
  return [...groups.values()].flatMap(group=>group.sort((a,b)=>{
    const x=value(a),y=value(b);
    if(x===null||y===null)return x===y?0:x===null?1:-1;
    return (direction==='asc'?1:-1)*(x-y);
  }));
 }
 function results(experiments,selected,mode='algorithm',selectedIds=null,sortMetric='',direction='desc'){
  const rows=orderedRows(experiments,mode,selectedIds,sortMetric,direction);
  if(!rows.length)return '<p>暂无已选择结果；请在上方选择需要比较的算法结果。</p>';
  const cohortKey=run=>Rules.identified(run)?JSON.stringify(Rules.conditions(run)):'unknown:'+run.run_id;
  const cohorts=new Map();for(const {run} of rows){const key=cohortKey(run);if(!cohorts.has(key))cohorts.set(key,cohorts.size+1);}
  let previousCohort=null;
  // 原生表头按钮支持键盘，aria-sort和箭头同步表达当前方向。
  const sortHeader=(key,label)=>{
   const active=sortMetric===key, state=active?(direction==='asc'?'ascending':'descending'):'none';
   const next=active&&direction==='desc'?'升序':active?'降序':['TM','RT'].includes(key)?'升序':'降序';
   return `<th scope="col" aria-sort="${state}"><button type="button" class="column-sort" data-sort-metric="${key}" data-focus-key="sort-${key}" aria-label="${E(label)}，点击按${next}排序">${E(label)} <span aria-hidden="true">${active?(direction==='asc'?'↑':'↓'):'↕'}</span></button></th>`;
  };
  return `<div class="table-wrap comparison-results" tabindex="0" aria-label="算法比较"><table><thead><tr><th scope="col">算法</th><th scope="col">来源 / 初始模型</th><th scope="col">状态 / 核验</th>${sortHeader('completed_tasks','完成任务')}${sortHeader('SCORE','综合分 / 100')}${metrics.map(([m])=>sortHeader(m,m)).join('')}<th scope="col">查看</th></tr></thead><tbody>${rows.map(({experiment,run})=>{
   const m=usable(run)?run.metrics:null;
   const validation=run.result_kind==='physical_validation'?'工程物理采样通过':run.result_kind==='planning_preview'?'采样通过 · 未认证':run.continuous_certification?.status||'核验未提供';
   const status=run.status==='SUCCEEDED'&&!m?'计划不可用':run.status;
   const note=m?validation:run.status==='SUCCEEDED'?(run.continuous_certification?.status||'核验未提供'):'';
   const source=experiment.temporary?'临时':'已保存';
   const gantt=experiment.temporary?`/visualization/temporary-gantt/${encodeURIComponent(experiment.experiment_id)}/${encodeURIComponent(run.run_id)}`:`/visualization/gantt/${encodeURIComponent(run.run_id)}`;
   const cohort=cohortKey(run);
   const divider=sortMetric&&cohorts.size>1&&cohort!==previousCohort?`<tr class="condition-group"><th colspan="${6+metrics.length}">${Rules.identified(run)?'同条件组 '+cohorts.get(cohort):'条件记录不完整'} · 不同组之间不作名次比较</th></tr>`:'';
   previousCohort=cohort;
   return divider+`<tr class="${run.run_id===selected?'selected':''}" ${run.run_id===selected?'aria-current="true"':''} data-run="${E(run.run_id)}"><th scope="row">${experiment.temporary?E(name(run.config.algorithm_id)):`<button type="button" class="select-algorithm" data-experiment="${E(experiment.experiment_id)}" data-run="${E(run.run_id)}">${E(name(run.config.algorithm_id))}</button>`}</th><td><span class="result-source">${source}</span> ${E(model(run.config.schedule_model))}</td><td><span>${E(status)}</span>${note?'<small class="validation-note">'+E(note)+'</small>':''}${run.error?'<small class="validation-note">'+E(run.error.message)+'</small>':''}</td><td>${m?`${m.completed_tasks} / ${m.total_tasks}`:'—'}</td><td>${m&&Number.isFinite(run.ranking_score?.value)?run.ranking_score.value.toFixed(2):'—'}</td>${metrics.map(([k])=>`<td>${format(k,m?.[k])}</td>`).join('')}<td>${usable(run)?`<a href="${E(gantt)}" target="_blank" rel="noopener">${experiment.temporary?'临时 Gantt':'Gantt'}</a>`:'尚无计划'}</td></tr>`;
  }).join('')}</tbody></table></div>`;
 }
 function compactChoices(rows,active){
  const checked=new Set(active);
  return '<p class="hint">选择要比较的算法</p><div class="comparison-options" role="group" aria-label="选择要比较的算法">'+rows.map(({run})=>{
   const id=run.run_id,isChecked=checked.has(id);
   return `<label class="add-algorithm-option ${isChecked?'is-chosen':''}"><input type="checkbox" data-result-id="${E(id)}" data-focus-key="check-${E(id)}" ${isChecked?'checked':''}><span>${E(name(run.config.algorithm_id))}</span></label>`;
  }).join('')+'</div>';
 }
 function filterChoices(records,active){
  const checked=new Set(active);
  return '<p class="hint">选择要比较的结果</p><div class="comparison-filters">'+records.map(experiment=>{
   const source=(experiment.temporary?'临时对照':'已保存实验')+' · '+model(experiment.config?.schedule_model||experiment.runs[0]?.config.schedule_model);
   return `<div class="comparison-filter-group"><p class="filter-source">${E(source)}</p><div class="filter-options" role="group" aria-label="${E(source)}">${experiment.runs.map(run=>{
    const id=run.run_id;
    return `<label class="result-choice ${checked.has(id)?'is-chosen':''}"><input type="checkbox" data-result-id="${E(id)}" data-focus-key="check-${E(id)}" ${checked.has(id)?'checked':''}><span>${E(name(run.config.algorithm_id))}</span></label>`;
   }).join('')}</div></div>`;
  }).join('')+'</div>';
 }
 function comparison(container,select,orderBox,onSelect,{compactSelection=false}={}){
  let records=[],selected=null,scope='',chosen=null,sortMetric='',sortDirection='desc';
  function render(){
   const arranged=orderedRows(records,select.value),active=arranged.filter(r=>chosen===null||chosen.has(r.run.run_id)).map(r=>r.run.run_id);
   update(container,results(records,selected,select.value,active,sortMetric,sortDirection));
   orderBox.hidden=false;
   if(compactSelection){update(orderBox,compactChoices(orderedRows(records,'experiment'),active));return;}
   update(orderBox,filterChoices(records,active));
  }
  select.addEventListener('change',render);
  orderBox.addEventListener('change',event=>{
   const input=event.target.closest('[data-result-id]');if(!input)return;
   chosen=chosen??new Set(orderedRows(records,'experiment').map(r=>r.run.run_id));
   if(input.checked)chosen.add(input.dataset.resultId);else chosen.delete(input.dataset.resultId);render();
  });
  container.addEventListener('click',event=>{
   const header=event.target.closest('[data-sort-metric]');
   if(header){
    const key=header.dataset.sortMetric;
    // 首次点击优先显示更优值；再次点击反转。轮询和筛选保留排序状态。
    sortDirection=key===sortMetric?(sortDirection==='asc'?'desc':'asc'):['TM','RT'].includes(key)?'asc':'desc';
    sortMetric=key;render();return;
   }
   const b=event.target.closest('.select-algorithm');if(b)onSelect(b.dataset.experiment,b.dataset.run);
  });
  return {set(next,id){const key=next.map(e=>e.experiment_id).join('|');if(key!==scope){scope=key;chosen=null;}records=next;selected=id;render();}};
 }
 function card(prefix,id,heading,content,extra=''){
  const control=`algo-${prefix}-${id}`;
  return `<div class="algorithm-card ${extra}"><div class="algorithm-heading">${heading}<button type="button" class="algorithm-toggle" data-toggle="${E(control)}" aria-expanded="false" aria-controls="${E(control)}" aria-label="展开或收起 ${E(name(id))} 的参数和说明"><span aria-hidden="true">▶</span></button></div><div class="algorithm-content" id="${E(control)}" hidden>${content}</div></div>`;
 }
 function bindCards(box){
  if(box.dataset.disclosuresBound)return;box.dataset.disclosuresBound='true';
  box.addEventListener('click',event=>{const b=event.target.closest('[data-toggle]');if(!b)return;const content=document.getElementById(b.dataset.toggle);if(!content)return;const open=b.getAttribute('aria-expanded')!=='true';b.setAttribute('aria-expanded',String(open));content.hidden=!open;});
 }
 function description(a){
  const sections=[['简介',a.description],['调度机制',a.strategy!==a.description?a.strategy:''],['目标',a.objectives],['限制',a.limitations],['可用性',a.availability_message]].filter(([,text])=>text);
  return '<div class="algorithm-description">'+sections.map(([title,text])=>`<p><strong>${E(title)}</strong><span>${E(text)}</span></p>`).join('')+'</div>';
 }
 function available(box,experiment,add,{hideIncluded=false}={}){
  if(box.dataset.adding==='true')return;
  const ids=new Set(experiment.runs.map(r=>r.config.algorithm_id)),key=experiment.experiment_id+JSON.stringify([...ids]);
  if(box.dataset.key===key)return;box.dataset.key=key;
  box.innerHTML='<h3>完整算法列表 · 新增算法</h3><p class="hint" role="status">勾选算法后确认添加，使用默认算法参数。</p><div class="add-algorithm-options">'+catalog.filter(a=>!hideIncluded||!ids.has(a.algorithm_id)).map(a=>{
   const included=ids.has(a.algorithm_id),disabled=included||a.availability!=='ready';
   return `<label class="add-algorithm-option ${included?'included':''}"><input type="checkbox" data-add-choice="${E(a.algorithm_id)}" ${disabled?'disabled':''}><span>${E(a.name)}${included?'<small>已添加</small>':disabled?`<small>${E(a.availability_message||'不可用')}</small>`:''}</span></label>`;
  }).join('')+'</div><button type="button" class="confirm-algorithms" disabled>添加所选算法</button>';
  const submit=box.querySelector('.confirm-algorithms');let busy=false;
  box.onchange=()=>{box.querySelectorAll('.add-algorithm-option').forEach(label=>label.classList.toggle('is-chosen',label.querySelector('input').checked));submit.disabled=busy||!box.querySelector('[data-add-choice]:checked');};
  submit.onclick=async()=>{
   if(busy)return;const choices=[...box.querySelectorAll('[data-add-choice]:checked')].map(input=>input.dataset.addChoice);if(!choices.length)return;
   busy=true;box.dataset.adding='true';submit.disabled=true;box.querySelectorAll('input').forEach(i=>i.disabled=true);
   let failure='';
   try{for(const id of choices)await add(id,{});}
   catch(error){failure=error.message;}
   finally{busy=false;box.dataset.adding='false';box.dataset.key='';try{await add(null,null);}catch(error){failure=error.message;}if(failure)box.querySelector('.hint').textContent='部分算法未添加：'+failure;}
  };
 }
 const api={E,name,model,format,usable,results,available,update,orderedRows,compactChoices,filterChoices,comparison,card,bindCards,description,visibleCatalog,setCatalog:v=>{catalog=visibleCatalog(v);},getCatalog:()=>catalog};
 if(typeof module==='object'&&module.exports)module.exports=api;else root.ExperimentUI=api;
})(typeof window==='undefined'?globalThis:window);
