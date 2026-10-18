// REAL generated scenes only. No mock routes, injected Worker or certificates.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const info=JSON.parse(fs.readFileSync(process.env.EOS_CAABS_P7_COORD,'utf8'));
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const results=[],errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1500,height:1100}});
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(info.url);
  await page.waitForSelector('[name="batch-algorithm"][value="caabs"]',{state:'attached'});
  await require('./algorithm-parameters-checks.cjs')(page);
  for(const [name,source,sha] of [['no-ground','runtime',info.no_ground_sha],['ground',info.ground_source,info.ground_sha]]){
   await require('./workspace-navigation.cjs').step(page,1);
   await page.selectOption('#source',source);
   await page.waitForFunction(()=>document.querySelector('#scenario-hint').textContent.includes('development_planning_only'));
   assert.equal(await page.locator('#execution-mode-control').isVisible(),true);
   if(name==='no-ground'){
    assert.equal(await page.inputValue('#execution-mode'),'physical_validation');
    assert.equal(await page.locator('#submit').isDisabled(),true);
   }
   await page.selectOption('#execution-mode','planning_preview');
   await page.waitForFunction(()=>!document.querySelector('#submit').disabled);
   await require('./workspace-navigation.cjs').step(page,2);
   for(const box of await page.locator('[name="batch-algorithm"]:checked').all())await box.uncheck();
   await page.locator('[name="batch-algorithm"][value="caabs"]').check();
   const toggle=page.locator('[data-toggle="algo-create-caabs"]');
   if(await toggle.getAttribute('aria-expanded')!=='true')await toggle.click();
   const params=page.locator('#algo-create-caabs .algorithm-parameters');
   for(const [key,value] of [['beam_width','4'],['branch_limit','4'],['max_candidates_per_task','8']]){
    const field=params.locator(`[data-key="${key}"]`);
    await field.locator('.parameter-mode').selectOption('value');
    await field.locator('.parameter-value').fill(value);
   }
   await require('./workspace-navigation.cjs').step(page,3);
   await page.fill('#budget','2');await page.selectOption('#placement','center');
   const responsePromise=page.waitForResponse(r=>r.url()===info.url+'/api/experiments'&&r.request().method()==='POST');
   await page.click('#submit');const response=await responsePromise;
   assert.equal(response.status(),202,await response.text());
   const sent=response.request().postDataJSON().runs[0];
   assert.equal(sent.execution_mode,'planning_preview');assert.equal(sent.algorithm_params.beam_width,4);
   const exp=await response.json();assert.equal(exp.runs.length,1);const id=exp.runs[0].run_id;
   let run;
   for(let i=0;i<400;i++){
    run=await(await page.request.get(info.url+'/api/runs/'+id)).json();
    if(['SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'].includes(run.status))break;
    await page.waitForTimeout(250);
   }
   assert.equal(run.status,'SUCCEEDED',JSON.stringify(run.error));
   assert.equal(run.result_kind,'planning_preview');assert.equal(run.config.scenario_sha256,sha);
   assert.ok(run.metrics.completed_tasks>0);assert.equal(run.continuous_certification.status,'NOT_CERTIFIED');
   assert.ok(run.plan.assignments.every(a=>Number.isInteger(a.sat_window_id)));
   if(name==='ground')assert.ok(run.plan.assignments.every(a=>Number.isInteger(a.gs_window_id)&&a.ground_station_id&&a.gs_start_time>a.sat_end_time));
   for(const format of ['json','csv'])assert.equal((await page.request.get(info.url+`/api/runs/${id}/export?format=${format}`)).status(),409);
   for(const execution_mode of ['formal','physical_validation'])assert.equal((await page.request.post(info.url+'/api/runs',{data:{...sent,execution_mode}})).status(),422);
   assert.equal((await page.request.post(info.url+'/api/runs',{data:{...sent,algorithm_params:{beam_width:0}}})).status(),422);
   await page.locator('nav [data-console-route="records"]').click();
   await page.waitForFunction(()=>document.querySelector('#detail-status').textContent.includes('SUCCEEDED'));
   assert.match(await page.locator('#detail-status').innerText(),/规划预览/);
   assert.match(await page.locator('#scenario-provenance').innerText(),/development_planning_only/);
   assert.equal(await page.locator('#export-json').isVisible(),false);
   await page.screenshot({path:info.output+`/${name}-console.png`,fullPage:true});
   const gantt=await browser.newPage();gantt.on('pageerror',e=>errors.push(String(e)));
   await gantt.goto(info.url+'/visualization/gantt/'+id);
   await gantt.waitForSelector('.gantt-bar',{state:'attached'});
   assert.match(await gantt.locator('#sourceLabel').innerText(),/未取得.*连续认证/);
   await gantt.screenshot({path:info.output+`/${name}-gantt.png`,fullPage:true});await gantt.close();
   results.push({name,run_id:id,scenario_sha256:sha,completed:run.metrics.completed_tasks,total:run.metrics.total_tasks,
    result_kind:run.result_kind,continuous:run.continuous_certification.status,params:sent.algorithm_params});
  }
  assert.deepEqual(errors,[]);
  fs.writeFileSync(info.output+'/browser-results.json',JSON.stringify({cases:results,page_errors:errors},null,2),{flag:'wx'});
  console.log('CAABS_REAL_BROWSER_PASS '+JSON.stringify(results));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
