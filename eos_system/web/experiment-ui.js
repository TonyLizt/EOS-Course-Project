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
  let rows=experiments.flatMap((experiment,ei)=>experiment.runs.map(run=>({experiment,run,ei})));
  if(order!==null){const rank=new Map([...new Set(order)].map((id,i)=>[id,i]));rows=rows.filter(r=>rank.has(r.run.run_id)).sort((a,b)=>rank.get(a.run.run_id)-rank.get(b.run.run_id));}
  if(mode==='experiment')return rows.sort((a,b)=>a.ei-b.ei);
  const ids=[...new Set(rows.map(r=>r.run.config.algorithm_id))];
  return rows.sort((a,b)=>ids.indexOf(a.run.config.algorithm_id)-ids.indexOf(b.run.config.algorithm_id));
 }
 function results(experiments,selected,mode='algorithm',order=null){
  const rows=orderedRows(experiments,mode,order);
  if(!rows.length)return '<p>暂无已选择结果；请在上方选择需要比较的算法结果。</p>';
  return `<div class="table-wrap" tabindex="0" aria-label="算法比较"><table><thead><tr><th scope="col">算法</th><th scope="col">实验 / 初始模型</th><th scope="col">状态 / 核验</th><th scope="col">完成任务</th>${metrics.map(([m,d])=>`<th scope="col">${m} ${d>0?'↑':'↓'}</th>`).join('')}<th scope="col">查看</th></tr></thead><tbody>${rows.map(({experiment,run,ei})=>{
   const m=usable(run)?run.metrics:null;
   const validation=run.result_kind==='planning_preview'?'曝光采样通过 · 未认证预览':run.continuous_certification?.status||'未提供';
   const status=run.status==='SUCCEEDED'&&!m?'SUCCEEDED · 计划不可用 / '+(run.continuous_certification?.status||'核验未提供'):run.status;
   return `<tr class="${run.run_id===selected?'selected':''}" ${run.run_id===selected?'aria-current="true"':''} data-run="${E(run.run_id)}"><th scope="row"><button type="button" class="select-algorithm" data-experiment="${E(experiment.experiment_id)}" data-run="${E(run.run_id)}">${E(name(run.config.algorithm_id))}</button></th><td>实验 ${ei+1} · ${E(model(run.config.schedule_model))}</td><td>${E(status)}${m?'<br>'+E(validation):''}${run.error?'<br>'+E(run.error.message):''}</td><td>${m?`${m.completed_tasks} / ${m.total_tasks}`:'—'}</td>${metrics.map(([k])=>`<td>${format(k,m?.[k])}</td>`).join('')}<td>${usable(run)?`<a href="/visualization/gantt/${E(run.run_id)}" target="_blank" rel="noopener">Gantt</a>`:'尚无计划'}</td></tr>`;
  }).join('')}</tbody></table></div>`;
 }
 function comparison(container,select,orderBox,onSelect){
  let records=[],selected=null,order=null,scope='',chosen=null;
  const groupKey=r=>select.value==='experiment'?r.experiment.experiment_id:r.run.config.algorithm_id;
  function render(){
   const all=orderedRows(records,'experiment'),ids=all.map(r=>r.run.run_id);
   if(order!==null)order=order.filter(id=>ids.includes(id));
   const complete=[...(order??ids),...ids.filter(id=>!(order??ids).includes(id))];
   const arranged=orderedRows(records,select.value,complete),active=arranged.filter(r=>chosen===null||chosen.has(r.run.run_id)).map(r=>r.run.run_id);
   update(container,results(records,selected,select.value,active));
   orderBox.hidden=false;
   const groups=new Map();for(const row of arranged){const k=groupKey(row);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(row);}
   update(orderBox,'<p class="hint">选择比较结果，使用箭头调整组内顺序。</p><div class="result-groups">'+[...groups.values()].map(rows=>{
    const first=rows[0],title=select.value==='experiment'?`实验 ${first.ei+1} · ${model(first.run.config.schedule_model)}`:name(first.run.config.algorithm_id);
    const enabled=rows.filter(r=>active.includes(r.run.run_id)).map(r=>r.run.run_id);
    return `<fieldset class="result-group"><legend>${E(title)}</legend>${rows.map(({run,ei})=>{
     const id=run.run_id,isChecked=active.includes(id),i=enabled.indexOf(id),label=`${name(run.config.algorithm_id)} · 实验 ${ei+1} · ${model(run.config.schedule_model)}`;
     return `<div class="result-choice ${isChecked?'is-chosen':''}"><label><input type="checkbox" data-result-id="${E(id)}" data-focus-key="check-${E(id)}" ${isChecked?'checked':''}><span><strong>${E(name(run.config.algorithm_id))}</strong><small>实验 ${ei+1} · ${E(model(run.config.schedule_model))}</small></span></label><span class="result-position" aria-label="比较顺序">${isChecked?active.indexOf(id)+1:'—'}</span><div class="result-moves"><button type="button" data-move="${E(id)}" data-delta="-1" data-focus-key="up-${E(id)}" aria-label="上移 ${E(label)}" ${i<=0?'disabled':''}>↑</button><button type="button" data-move="${E(id)}" data-delta="1" data-focus-key="down-${E(id)}" aria-label="下移 ${E(label)}" ${!isChecked||i===enabled.length-1?'disabled':''}>↓</button></div></div>`;
    }).join('')}</fieldset>`;
   }).join('')+'</div>');
  }
  select.addEventListener('change',render);
  orderBox.addEventListener('change',event=>{
   const input=event.target.closest('[data-result-id]');if(!input)return;
   chosen=chosen??new Set(orderedRows(records,'experiment').map(r=>r.run.run_id));
   if(input.checked)chosen.add(input.dataset.resultId);else chosen.delete(input.dataset.resultId);render();
  });
  orderBox.addEventListener('click',event=>{
   const button=event.target.closest('[data-move]');if(!button)return;
   const ids=orderedRows(records,'experiment').map(r=>r.run.run_id),complete=[...(order??ids),...ids.filter(id=>!(order??ids).includes(id))];
   const all=orderedRows(records,select.value,complete),row=all.find(r=>r.run.run_id===button.dataset.move);if(!row)return;
   const same=all.filter(r=>groupKey(r)===groupKey(row)&&(chosen===null||chosen.has(r.run.run_id))).map(r=>r.run.run_id);
   const i=same.indexOf(button.dataset.move),j=i+Number(button.dataset.delta);
   if(i>=0&&j>=0&&j<same.length){order=all.map(r=>r.run.run_id);const a=order.indexOf(same[i]),b=order.indexOf(same[j]);[order[a],order[b]]=[order[b],order[a]];}render();
  });
  container.addEventListener('click',event=>{const b=event.target.closest('.select-algorithm');if(b)onSelect(b.dataset.experiment,b.dataset.run);});
  return {set(next,id){const key=next.map(e=>e.experiment_id).join('|');if(key!==scope){scope=key;order=null;chosen=null;}records=next;selected=id;render();}};
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
 const api={E,name,model,format,usable,results,available,update,orderedRows,comparison,card,bindCards,description,setCatalog:v=>{catalog=v;},getCatalog:()=>catalog};
 if(typeof module==='object'&&module.exports)module.exports=api;else root.ExperimentUI=api;
})(typeof window==='undefined'?globalThis:window);
