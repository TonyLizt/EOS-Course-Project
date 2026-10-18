/* 仅管理页面展示与导航；请求、默认值、参数校验和运行行为继续由原模块负责。 */
(() => {
  'use strict';
  const form=document.getElementById('run-form');
  const panels=[...form.querySelectorAll('.workflow-panel')];
  const tabs=[...form.querySelectorAll('[data-workspace-step]')];
  let active=1;
  function showStep(step,focus=false){
    active=Number(step);
    for(const panel of panels)panel.hidden=panel.id!==`workspace-step-${active}`;
    for(const tab of tabs){
      if(Number(tab.dataset.workspaceStep)===active)tab.setAttribute('aria-current','step');
      else tab.removeAttribute('aria-current');
    }
    if(focus)document.getElementById(`workspace-heading-${active}`).focus({preventScroll:true});
  }
  const selectedAlgorithms=()=>[...form.querySelectorAll('[name="batch-algorithm"]:checked')];
  function selectedText(id){const select=document.getElementById(id);return select.selectedOptions[0]?.textContent||'等待加载…';}
  function updateSummary(){
    const selected=selectedAlgorithms();
    document.getElementById('workspace-selection-count').textContent=selected.length?`已选 ${selected.length} 种算法`:'选择要比较的算法';
    document.getElementById('workspace-scene-summary').textContent=selectedText('scenario');
    document.getElementById('workspace-algorithm-summary').textContent=selected.length?selected.map(input=>input.closest('label').textContent.trim()).join('、'):'尚未选择算法，请返回步骤 2';
    if(selected.length)document.getElementById('workspace-step-error').textContent='';
  }
  // 保持同一份表单和控件，不复制输入，切换步骤不会重建或重置算法参数。
  for(const tab of tabs)tab.addEventListener('click',()=>{showStep(tab.dataset.workspaceStep,true);updateSummary();});
  for(const button of form.querySelectorAll('[data-workspace-next]'))button.addEventListener('click',()=>{
    const next=Number(button.dataset.workspaceNext);
    if(next>active){
      const invalid=panels[active-1].querySelector('input:invalid,select:invalid,textarea:invalid');
      if(invalid){invalid.reportValidity();return;}
      if(active===2&&!selectedAlgorithms().length){document.getElementById('workspace-step-error').textContent='请至少勾选一种可用算法，再确认运行设置。';return;}
    }
    updateSummary();showStep(next,true);
    form.querySelector('.workflow-tabs').scrollIntoView({block:'nearest',behavior:'auto'});
  });
  function revealField(field){
    window.ConsoleWorkspace?.showPage('create', {focus:false});
    const panel=field.closest('.workflow-panel');
    if(panel)showStep(panels.indexOf(panel)+1);
    const content=field.closest('.algorithm-content');
    if(content?.hidden)content.closest('.algorithm-card').querySelector('.algorithm-toggle').click();
    for(let parent=field.parentElement;parent&&parent!==form;parent=parent.parentElement){
      if(parent.tagName==='DETAILS')parent.open=true;
    }
  }
  // 浏览器发现隐藏步骤中的无效字段时，先展示所属步骤，让原生错误提示可见。
  form.addEventListener('invalid',event=>{
    revealField(event.target);
  },true);
  form.addEventListener('change',updateSummary);
  // 使用原提示函数同步模式说明，避免正式模式仍显示预览输出文案。
  document.getElementById('execution-mode').addEventListener('change',()=>updateHints());
  const parameterErrors=new MutationObserver(records=>{
    const error=records.map(record=>record.target).find(node=>node.classList?.contains('parameter-error')&&!node.hidden&&node.textContent);
    if(error){revealField(error);error.scrollIntoView({block:'nearest',behavior:'auto'});}
  });
  parameterErrors.observe(document.getElementById('algorithm-choices'),{attributes:true,attributeFilter:['hidden'],subtree:true});
  const observer=new MutationObserver(updateSummary);
  for(const id of ['source','scenario','algorithm-choices'])observer.observe(document.getElementById(id),{childList:true,subtree:true});
  const health=document.getElementById('health');
  function updateService(){
    const connected=health.textContent.includes('服务已连接');
    const failed=health.textContent.includes('失败');
    document.getElementById('workspace-service-label').textContent=connected?'服务已连接':failed?'连接失败':'正在连接';
    document.querySelector('.status-dot').dataset.state=connected?'online':failed?'offline':'pending';
  }
  new MutationObserver(updateService).observe(health,{childList:true,subtree:true,characterData:true});
  updateService();showStep(1);updateSummary();
})();