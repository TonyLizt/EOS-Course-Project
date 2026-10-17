/* One persistent experiment owns its algorithm Runs; no arbitrary condition groups. */
(() => {
  'use strict';
  const UI=ExperimentUI, E=UI.E;
  let experimentId=new URLSearchParams(location.search).get('experiment_id'), experiment=null, peerId='', pending=false, generation=0;
  let submitKey=null, submitPayload=null;
  let controlPending=false,controlKey=null,controlSignature=null;
  const comparison=UI.comparison($('comparison-groups'),$('comparison-mode'),$('comparison-choices'),(eid,rid)=>{
    if(eid!==experimentId)showExperiment(eid,rid);else{selectedId=rid;refreshExperiments();}
  });
  function catalog(algorithms) {
    UI.setCatalog(algorithms);
    const first=algorithms.find(a=>a.availability==='ready')?.algorithm_id;
    $('algorithm-choices').innerHTML=algorithms.map(a=>UI.card('create',a.algorithm_id,
      `<label class="check-label algorithm-choice"><input type="checkbox" name="batch-algorithm" value="${E(a.algorithm_id)}" ${a.algorithm_id===first?'checked':''} ${a.availability!=='ready'?'disabled':''}>${E(a.name)}</label>`,
      UI.description(a)+`<label>算法参数 JSON<textarea aria-label="${E(a.name)}参数" data-params="${E(a.algorithm_id)}" rows="2" ${a.availability!=='ready'?'disabled':''}>{}</textarea></label><pre>${E(JSON.stringify(a.parameters,null,2))}</pre>`)).join('');
    UI.bindCards($('algorithm-choices'));
  }
  async function submit() {
    if(pending)return;
    try {
      const common=buildRequest();
      const runs=[...document.querySelectorAll('[name="batch-algorithm"]:checked')].map(input=>{
        const params=JSON.parse($('algorithm-choices').querySelector(`[data-params="${CSS.escape(input.value)}"]`).value);
        if(!params||Array.isArray(params)||typeof params!=='object')throw Error('算法参数必须是 JSON 对象');
        return {...common,algorithm_id:input.value,algorithm_params:params};
      });
      if(!runs.length)throw Error('请至少选择一种算法');
      const payload=JSON.stringify({runs});
      if(payload!==submitPayload){submitKey=crypto.randomUUID();submitPayload=payload;}
      pending=true;$('submit').disabled=true;
      const result=await api('/api/experiments',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':submitKey},body:payload});
      experimentId=result.experiment_id;selectedId=result.runs[0]?.run_id||null;peerId='';pageOffset=0;
      $('form-message').textContent=`已创建一个实验，包含 ${result.runs.length} 种算法。`;
      $('submission-results').innerHTML=result.runs.map(r=>`<li>${E(UI.name(r.config.algorithm_id))}：已接受</li>`).join('');
      submitKey=submitPayload=null;
      await refreshExperiments();
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
    $('comparison-status').textContent=experiment?`实验 ${experiment.experiment_id} · ${experiment.runs.length} 种算法${peerId?' · 与另一初始模型实验对照':''}`:'请选择一个实验';
  }
  async function showExperiment(id, rid=null) {
    experimentId=id;peerId='';if(rid)selectedId=rid;
    await refreshExperiments();
  }
  async function refreshExperiments() {
    const token=++generation;
    try {
      let list=await api(`/api/experiments?limit=${pageSize}&offset=${pageOffset}`);
      if(pageOffset>0&&pageOffset>=list.total){pageOffset=0;list=await api(`/api/experiments?limit=${pageSize}&offset=0`);}
      if(token!==generation)return;
      $('run-count').textContent=`共 ${list.total} 个实验（每行包含多个算法）`;
      $('page-label').textContent=list.total?`${pageOffset+1}–${Math.min(pageOffset+pageSize,list.total)} / ${list.total}`:'0 / 0';
      $('previous-page').disabled=pageOffset===0;$('next-page').disabled=pageOffset+pageSize>=list.total;
      const html=list.items.map(item=>`<tr data-experiment="${E(item.experiment_id)}" class="${item.experiment_id===experimentId?'selected':''}"><td><button class="experiment-select" type="button" data-experiment="${E(item.experiment_id)}">实验 ${E(item.experiment_id.slice(0,8))}</button><small class="experiment-date">${E(new Date(item.created_at).toLocaleString('zh-CN'))}</small>${item.legacy?'<small>历史单次运行（无批次证据）</small>':''}</td><td>${E(item.config.scenario_id)}</td><td>${E(UI.model(item.config.schedule_model))}</td><td>${E(item.algorithms.map(a=>UI.name(a.algorithm_id)).join('、')||'暂无算法')}</td><td>${E(item.status)}</td></tr>`).join('');
      UI.update($('runs'),html);
      if(!experimentId){renderResults([]);return;}
      const exp=await api(`/api/experiments/${encodeURIComponent(experimentId)}`);
      if(token!==generation)return;
      experiment=exp;
      $('create-control').disabled=controlPending||exp.legacy||!exp.runs.length;
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
      const peers=await api(`/api/experiments/${encodeURIComponent(exp.experiment_id)}/peers`);
      if(token!==generation)return;
      const peerOptions='<option value="">仅当前实验</option>'+peers.items.map(p=>`<option value="${E(p.experiment_id)}">${E(UI.model(p.schedule_model))} · ${E(new Date(p.created_at).toLocaleString())}</option>`).join('');
      if($('model-comparison').innerHTML!==peerOptions)$('model-comparison').innerHTML=peerOptions;
      if(!peers.items.some(p=>p.experiment_id===peerId))peerId='';
      $('model-comparison').value=peerId;
      let records=[exp];
      if(peerId)records=(await api(`/api/experiments/${encodeURIComponent(exp.experiment_id)}/compare/${encodeURIComponent(peerId)}`)).items;
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
  $('model-comparison').addEventListener('change',()=>{peerId=$('model-comparison').value;refreshExperiments();});
  $('create-control').addEventListener('click',async()=>{
    if(!experiment||controlPending)return;controlPending=true;$('create-control').disabled=true;
    try{
      const signature=experimentId+'|'+$('control-model').value;
      if(signature!==controlSignature){controlSignature=signature;controlKey=crypto.randomUUID();}
      const result=await api(`/api/experiments/${encodeURIComponent(experimentId)}/control`,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':controlKey},body:JSON.stringify({schedule_model:$('control-model').value})});
      controlKey=controlSignature=null;
      peerId=result.experiment_id;
      $('list-message').textContent=`已创建对照实验 ${result.experiment_id}；仅改变初始排程模型，原实验未覆盖。`;
      await refreshExperiments();
    }catch(error){$('list-message').textContent=error.message;}
    finally{controlPending=false;$('create-control').disabled=!experiment||experiment.legacy||!experiment.runs.length;}
  });
  $('run-algorithm-info').addEventListener('click',()=>{
    const run=experiment?.runs.find(r=>r.run_id===selectedId);if(!run)return;
    const spec=currentAlgorithms.find(a=>a.algorithm_id===run.config.algorithm_id);
    $('algorithm-dialog-title').textContent=UI.name(run.config.algorithm_id);
    $('algorithm-description').textContent=(spec?.strategy||'历史算法')+'\n'+(spec?.limitations||'')+'\n'+JSON.stringify(run.config,null,2);
    $('algorithm-dialog').showModal();
  });
  $('close-algorithm-dialog').addEventListener('click',()=>$('algorithm-dialog').close());
  window.ConsoleUI={catalog,detail,submit,refreshExperiments,removeSelectedAlgorithm};
})();
