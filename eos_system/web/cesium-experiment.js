/* Incremental controls inside the existing Metrics sidebar, never an outer viewer. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id),UI=ExperimentUI,query=new URLSearchParams(location.search);
 const rid=query.get('run_id')||(query.get('schedule')||'').match(/^\/api\/runs\/([^/]+)\//)?.[1];
 if(!rid)return;
 let exp=null,peer='',generation=0;
 async function api(url,options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw Error(data.error?.message||'请求失败');return data;}
 function navigate(eid,id){
  try{const state=window.EOSReplayState?.capture();if(state)sessionStorage.setItem('eos-replay-navigation-state',JSON.stringify({...state,experiment_id:eid,saved_at:Date.now()}));}catch(_){/* Optional. */}
  location.assign('/visualization/cesium/'+encodeURIComponent(id));
 }
 const comparison=UI.comparison($('cesium-comparison'),$('cesium-comparison-mode'),$('cesium-mixed-order'),async(eid,id)=>{
  try{const run=exp?.runs.find(r=>r.run_id===id)||await api('/api/runs/'+encodeURIComponent(id));
   if(!UI.usable(run)){$('cesium-experiment-status').textContent='该算法尚无可用计划，不能回放。';return;}
   if(id!==rid)navigate(eid,id);
  }catch(error){$('cesium-experiment-status').textContent=error.message;}
 });
 function currentAlgorithms(){
  const box=$('cesium-current-algorithms'),key=exp.experiment_id+JSON.stringify(exp.runs.map(r=>[r.run_id,r.status]));
  if(box.dataset.key===key)return;box.dataset.key=key;
  box.innerHTML=exp.runs.map(run=>{
   const aid=run.config.algorithm_id,a=UI.getCatalog().find(a=>a.algorithm_id===aid)||{description:'历史算法'};
   const heading=`<button type="button" class="algorithm-choice choose-replay ${run.run_id===rid?'active':''}" data-replay="${UI.E(run.run_id)}" ${run.run_id===rid?'aria-current="true"':''} ${UI.usable(run)?'':'disabled'}>${UI.E(UI.name(aid))} · ${UI.E(run.status)}${run.run_id===rid?' · 当前回放':''}</button>`;
   return UI.card(box.id,aid,heading,UI.description(a)+`<label>本次参数 JSON<textarea readonly rows="3">${UI.E(JSON.stringify(run.config.algorithm_params,null,2))}</textarea></label><button type="button" data-remove="${UI.E(aid)}">移除此算法（保留历史）</button>`);
  }).join('');UI.bindCards(box);
 }
 async function refresh(){
  const token=++generation;
  try{
   const next=exp?await api('/api/experiments/'+encodeURIComponent(exp.experiment_id)):await api('/api/runs/'+encodeURIComponent(rid)+'/experiment');
   if(token!==generation)return;exp=next;$('experiment-controls').hidden=false;
   if(!exp.runs.some(r=>r.run_id===rid)){
    const replacement=exp.runs.find(UI.usable);
    if(replacement)navigate(exp.experiment_id,replacement.run_id);
    else location.assign('/?experiment_id='+encodeURIComponent(exp.experiment_id)+'#detail-heading');
    return;
   }
   $('cesium-experiment-status').textContent=`${exp.config.scenario_id} · ${UI.model(exp.config.schedule_model)} · ${UI.name(exp.runs.find(r=>r.run_id===rid).config.algorithm_id)}`;
   currentAlgorithms();
   UI.available($('cesium-add-algorithms'),exp,async(algorithm_id,algorithm_params)=>{
    await api('/api/experiments/'+encodeURIComponent(exp.experiment_id)+'/algorithms',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({algorithm_id,algorithm_params})});await refresh();
   });
   const peers=await api('/api/experiments/'+encodeURIComponent(exp.experiment_id)+'/peers');if(token!==generation)return;
   const options='<option value="">仅当前实验</option>'+peers.items.map(p=>`<option value="${UI.E(p.experiment_id)}">${UI.E(UI.model(p.schedule_model))} · ${UI.E(new Date(p.created_at).toLocaleString('zh-CN'))}</option>`).join('');
   if($('cesium-peer').innerHTML!==options)$('cesium-peer').innerHTML=options;
   if(!peers.items.some(p=>p.experiment_id===peer))peer='';$('cesium-peer').value=peer;
   const records=peer?(await api(`/api/experiments/${encodeURIComponent(exp.experiment_id)}/compare/${encodeURIComponent(peer)}`)).items:[exp];
   if(token===generation)comparison.set(records,rid);
  }catch(error){$('cesium-experiment-status').textContent=error.message;}
 }
 $('cesium-current-algorithms').addEventListener('click',async event=>{
  const replay=event.target.closest('[data-replay]');if(replay){if(replay.dataset.replay!==rid)navigate(exp.experiment_id,replay.dataset.replay);return;}
  const remove=event.target.closest('[data-remove]');if(!remove)return;
  if(!confirm(`移除「${UI.name(remove.dataset.remove)}」？未完成运行将取消；历史及文件保留。`))return;
  try{await api(`/api/experiments/${encodeURIComponent(exp.experiment_id)}/algorithms/${encodeURIComponent(remove.dataset.remove)}`,{method:'DELETE'});await refresh();}
  catch(error){$('cesium-experiment-status').textContent=error.message;}
 });
 $('cesium-peer').addEventListener('change',()=>{peer=$('cesium-peer').value;refresh();});
 (async()=>{try{UI.setCatalog((await api('/api/algorithms')).items);await refresh();}catch(error){$('cesium-experiment-status').textContent=error.message;}})();
 setInterval(refresh,2500);
})();
