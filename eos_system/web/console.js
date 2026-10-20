/* One persistent experiment owns its algorithm Runs; no arbitrary condition groups. */
(() => {
  'use strict';
  const UI=ExperimentUI, E=UI.E;
  let experimentId=new URLSearchParams(location.search).get('experiment_id'), experiment=null, temporary=null, pending=false, generation=0;
  let submitKey=null, submitPayload=null;
  let controlPending=false,controlKey=null,controlSignature=null;
  const comparison=UI.comparison($('comparison-groups'),$('comparison-mode'),$('comparison-choices'),(eid,rid)=>{
    if(eid!==experimentId)showExperiment(eid,rid);else{selectedId=rid;refreshExperiments();}
  },{sortSelect:$('result-sort'),directionSelect:$('result-direction')});
  function catalog(algorithms) {
    UI.setCatalog(algorithms);
    const first=algorithms.find(a=>a.availability==='ready')?.algorithm_id;
    $('algorithm-choices').innerHTML=algorithms.map(a=>UI.card('create',a.algorithm_id,
      `<label class="check-label algorithm-choice"><input type="checkbox" name="batch-algorithm" value="${E(a.algorithm_id)}" ${a.algorithm_id===first?'checked':''} ${a.availability!=='ready'?'disabled':''}>${E(a.name)}</label>`,
      UI.description(a)+AlgorithmParameters.render(a))).join('');
    for(const a of algorithms)AlgorithmParameters.bind($('algorithm-choices').querySelector(`[data-algorithm="${CSS.escape(a.algorithm_id)}"]`),a);
    UI.bindCards($('algorithm-choices'));
  }
  async function submit() {
    if(pending)return;
    try {
      const common=buildRequest();
      const runs=[...document.querySelectorAll('[name="batch-algorithm"]:checked')].map(input=>{
        const params=$('algorithm-choices').querySelector(`[data-algorithm="${CSS.escape(input.value)}"]`).parameterValues();
        return {...common,algorithm_id:input.value,algorithm_params:params};
      });
      if(!runs.length)throw Error('请至少选择一种算法');
      const payload=JSON.stringify({runs});
      if(payload!==submitPayload){submitKey=crypto.randomUUID();submitPayload=payload;}
      pending=true;$('submit').disabled=true;
      const result=await api('/api/experiments',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':submitKey},body:payload});
      await discardControl();experimentId=result.experiment_id;selectedId=result.runs[0]?.run_id||null;pageOffset=0;
      $('form-message').textContent=`已创建一个实验，包含 ${result.runs.length} 种算法。`;
      $('submission-results').innerHTML=result.runs.map(r=>`<li>${E(UI.name(r.config.algorithm_id))}：已接受</li>`).join('');
      submitKey=submitPayload=null;
      await refreshExperiments();
      // 提交成功才切到管理页；失败留在原表单，便于修正且不丢配置。
      window.ConsoleWorkspace?.showPage('records');
    } catch(error){$('form-message').textContent=error.message;}
    finally{pending=false;$('submit').disabled=false;}
  }
  function detail(run) {
    $('run-algorithm-info').hidden=!run;
    $('run-config').textContent=run?JSON.stringify({config:run.config,continuous_certification:run.continuous_certification,preview_validation:run.preview_validation},null,2):'';
    $('run-summary').textContent=run?`${UI.name(run.config.algorithm_id)} · ${UI.model(run.config.schedule_model)} · ${run.config.scenario_id}`:'';
  }
  function renderResults(records) {
    comparison.set(records,selectedId);
    $('comparison-status').textContent=experiment?`实验 ${experiment.experiment_id} · ${experiment.runs.length} 种算法${temporary?' · 临时对照 '+temporary.status:''}`:'请选择一个实验';
  }
  function controlButton(){
    $('create-control').textContent=controlPending?(temporary?'删除中…':'创建中…'):temporary?'移除临时对照':'一键创建对照实验';
    $('create-control').disabled=controlPending||!experiment||(!temporary&&(experiment.legacy||!experiment.runs.length));
    $('control-model').disabled=controlPending||!!temporary;
  }
  async function discardControl(){
    if(temporary){const id=temporary.experiment_id;await api('/api/temporary-controls/'+encodeURIComponent(id),{method:'DELETE'});temporary=null;}
    controlKey=controlSignature=null;
  }
  async function showExperiment(id, rid=null) {
    try{await discardControl();}catch(error){$('control-status').textContent=error.message;return;}
    experimentId=id;if(rid)selectedId=rid;
    await refreshExperiments();
  }
  async function refreshExperiments() {
    const token=++generation;
    try {
      let [list,execution]=await Promise.all([
        api(`/api/experiments?limit=${pageSize}&offset=${pageOffset}`),api('/api/execution-settings')]);
      if(pageOffset>0&&pageOffset>=list.total){pageOffset=0;list=await api(`/api/experiments?limit=${pageSize}&offset=0`);}
      if(token!==generation)return;
      const workerStatus=$('worker-status'),workerInput=$('worker-limit');
      if(workerStatus)workerStatus.textContent=`最多 ${execution.max_workers} 个 Worker · 当前占用 ${execution.active_runs} 个槽位（含核验）`;
      if(workerInput&&document.activeElement!==workerInput&&!$('apply-worker-limit')?.disabled)workerInput.value=execution.max_workers;
      $('run-count').textContent=`共 ${list.total} 个实验（每行包含多个算法）`;
      $('page-label').textContent=list.total?`${pageOffset+1}–${Math.min(pageOffset+pageSize,list.total)} / ${list.total}`:'0 / 0';
      $('previous-page').disabled=pageOffset===0;$('next-page').disabled=pageOffset+pageSize>=list.total;
      const html=list.items.map(item=>`<tr data-experiment="${E(item.experiment_id)}" class="${item.experiment_id===experimentId?'selected':''}"><td><button class="experiment-select" type="button" data-experiment="${E(item.experiment_id)}">实验 ${E(item.experiment_id.slice(0,8))}</button><small class="experiment-date">${E(new Date(item.created_at).toLocaleString('zh-CN'))}</small>${item.legacy?'<small>历史单次运行（无批次证据）</small>':''}</td><td>${E(item.config.scenario_id)}</td><td>${E(UI.model(item.config.schedule_model))}</td><td>${E(item.algorithms.map(a=>UI.name(a.algorithm_id)).join('、')||'暂无算法')}</td><td>${E(item.status)}</td></tr>`).join('');
      UI.update($('runs'),html);
      if(!experimentId){renderResults([]);return;}
      const exp=await api(`/api/experiments/${encodeURIComponent(experimentId)}`);
      if(token!==generation)return;
      experiment=exp;
      controlButton();
      for(const option of $('control-model').options)option.disabled=option.value===exp.config.schedule_model;
      $('control-model').value=exp.config.schedule_model==='completion_first'?'adaptive_repair':'completion_first';
      if(!exp.runs.some(r=>r.run_id===selectedId))selectedId=exp.runs.find(UI.usable)?.run_id||exp.runs[0]?.run_id||null;
      const options=exp.runs.map(r=>`<option value="${E(r.run_id)}">${E(UI.name(r.config.algorithm_id))} · ${E(r.status)}</option>`).join('');
      if($('detail-algorithm').innerHTML!==options)$('detail-algorithm').innerHTML=options;
      $('detail-algorithm').value=selectedId||'';$('detail-algorithm').disabled=!exp.runs.length;
      const run=exp.runs.find(r=>r.run_id===selectedId);
      if(run){showDetail(run);$('selected-run').textContent=`实验 ${exp.experiment_id} · 当前算法：${UI.name(run.config.algorithm_id)}`;$('open-cesium').href=`/visualization/experiments/${encodeURIComponent(exp.experiment_id)}/cesium?run_id=${encodeURIComponent(run.run_id)}`;$('delete-run').disabled=false;$('delete-option').hidden=true;}
      else{clearDetail();$('selected-run').textContent=exp.experiment_id+' · 暂无算法';}
      UI.available($('experiment-algorithm-add'),exp,async(id,params)=>{
        if(!id){await refreshExperiments();return;}
        await api(`/api/experiments/${encodeURIComponent(exp.experiment_id)}/algorithms`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({algorithm_id:id,algorithm_params:params})});
      });
      let records=[exp];
      if(temporary){
        const sid=temporary.experiment_id;
        try{const next=await api('/api/temporary-controls/'+encodeURIComponent(sid));if(token!==generation||temporary?.experiment_id!==sid)return;
          const members=e=>JSON.stringify(e.runs.map(r=>[r.config.algorithm_id,r.config.algorithm_params]).sort((a,b)=>a[0].localeCompare(b[0])));
          if(members(next)!==members(exp)){await discardControl();$('control-status').textContent='正式实验算法集合已变化，临时对照已移除，请重新创建。';}
          else{temporary=next;records.push(next);}
        }
        catch(error){if(token!==generation)return;if(temporary?.experiment_id===sid){temporary=null;$('control-status').textContent='临时对照已失效，请重新创建。';}}
      }
      controlButton();
      if(token===generation)renderResults(records);
    }catch(error){$('list-message').textContent=error.message;}
  }
  async function removeSelectedAlgorithm() {
    const run=experiment?.runs.find(r=>r.run_id===selectedId);
    if(!run||!confirm(`从实验移除「${UI.name(run.config.algorithm_id)}」？未完成运行会取消，已生成历史和文件保留。`))return;
    try{await api(`/api/experiments/${encodeURIComponent(experimentId)}/algorithms/${encodeURIComponent(run.config.algorithm_id)}`,{method:'DELETE'});await refreshExperiments();}
    catch(error){$('detail-error').textContent=error.message;}
  }
  $('runs').addEventListener('click',event=>{const b=event.target.closest('[data-experiment]');if(b)showExperiment(b.dataset.experiment);});
  $('detail-algorithm').addEventListener('change',()=>{selectedId=$('detail-algorithm').value;refreshExperiments();});
  $('create-control').addEventListener('click',async()=>{
    if(!experiment||controlPending)return;controlPending=true;controlButton();
    const source=experimentId;
    try{
      if(temporary){await discardControl();$('control-status').textContent='临时对照已移除；正式实验和历史记录未修改。';await refreshExperiments();return;}
      const signature=experimentId+'|'+$('control-model').value;
      if(signature!==controlSignature){controlSignature=signature;controlKey=crypto.randomUUID();}
      const result=await api(`/api/experiments/${encodeURIComponent(source)}/temporary-control`,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':controlKey},body:JSON.stringify({schedule_model:$('control-model').value})});
      if(source!==experimentId){await api('/api/temporary-controls/'+encodeURIComponent(result.experiment_id),{method:'DELETE'});return;}
      controlKey=controlSignature=null;
      temporary=result;
      $('control-status').textContent='临时对照已创建，等待计算；仅驻留内存，不保存或用于 Cesium。刷新或离开页面后清理。';
      await refreshExperiments();
    }catch(error){$('control-status').textContent=error.message;}
    finally{controlPending=false;controlButton();}
  });
  window.addEventListener('pagehide',()=>{if(temporary)fetch('/api/temporary-controls/'+encodeURIComponent(temporary.experiment_id),{method:'DELETE',keepalive:true}).catch(()=>{});});
  $('run-algorithm-info').addEventListener('click',()=>{
    const run=experiment?.runs.find(r=>r.run_id===selectedId);if(!run)return;
    const spec=currentAlgorithms.find(a=>a.algorithm_id===run.config.algorithm_id);
    $('algorithm-dialog-title').textContent=UI.name(run.config.algorithm_id);
    $('algorithm-description').innerHTML=UI.description(spec||{description:'历史算法'})+AlgorithmParameters.render(spec||{algorithm_id:run.config.algorithm_id},run.config.algorithm_params||{},true);
    $('algorithm-dialog').showModal();
  });
  $('close-algorithm-dialog').addEventListener('click',()=>$('algorithm-dialog').close());
  window.ConsoleUI={catalog,detail,submit,refreshExperiments,removeSelectedAlgorithm};
})();
