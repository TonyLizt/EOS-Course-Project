(() => {
  'use strict';
  let offset=0,catalog=[];
  const $=id=>document.getElementById(id);
  async function read(path){const r=await fetch(path);const body=await r.json();if(!r.ok)throw Error(body.error?.message||'读取失败');return body;}
  async function load(){
    $('older').disabled=$('newer').disabled=true;
    try{
      const data=await read(`/api/experiments?limit=30&offset=${offset}`);
      $('gantt-runs').replaceChildren();
      for(const exp of data.items){
        const li=document.createElement('li'),details=document.createElement('details'),summary=document.createElement('summary'),list=document.createElement('ul');
        summary.textContent=`${exp.config.scenario_id} · ${exp.algorithms.length} 种算法 · ${exp.status} · ${exp.experiment_id}`;
        details.append(summary,list);li.append(details);$('gantt-runs').append(li);
        details.addEventListener('toggle',async()=>{
          if(!details.open||list.dataset.loaded)return;list.dataset.loaded='true';
          try{const detail=await read('/api/experiments/'+encodeURIComponent(exp.experiment_id));
            for(const run of detail.runs){const item=document.createElement('li');const text=(catalog.find(a=>a.algorithm_id===run.config.algorithm_id)?.name||run.config.algorithm_id)+' · '+run.status;
              if(run.status==='SUCCEEDED'&&run.plan){const a=document.createElement('a');a.href='/visualization/gantt/'+encodeURIComponent(run.run_id);a.textContent=text;item.append(a);}else item.textContent=text+'（尚无可用计划）';list.append(item);}
          }catch(error){list.textContent=error.message;delete list.dataset.loaded;}
        });
      }
      $('run-message').textContent=`共 ${data.total} 个实验；展开后选择算法。`;
      $('older').disabled=offset+30>=data.total;$('newer').disabled=offset===0;
    }catch(error){$('run-message').textContent=error.message;}
  }
  $('older').addEventListener('click',()=>{offset+=30;load();});$('newer').addEventListener('click',()=>{offset=Math.max(0,offset-30);load();});
  (async()=>{try{catalog=(await read('/api/algorithms')).items;}finally{await load();}})();
})();
