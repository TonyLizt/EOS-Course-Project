// One isolated synthetic UI acceptance; final certificate is UNIT TEST ONLY.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const coord=process.env.EOS_RABAS_COORD;if(!coord)throw Error('EOS_RABAS_COORD required');
 const info=JSON.parse(fs.readFileSync(coord,'utf8'));assert.equal(info.synthetic_only,true);
 const browser=await chromium.launch({headless:true,executablePath:process.env.EOS_BROWSER_EXECUTABLE,
  args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const errors=[];
 try{
  const context=await browser.newContext({viewport:{width:1500,height:1000}});
  context.on('page',p=>p.on('pageerror',e=>errors.push(String(e))));
  const page=await context.newPage();await page.goto(info.url);
  await page.waitForSelector('[name="batch-algorithm"][value="rabas"]');
  await page.selectOption('#execution-mode','formal');await page.waitForSelector('#scenario option[value="synthetic"]',{state:'attached'});
  await page.selectOption('#scenario','synthetic');
  for(const box of await page.locator('[name="batch-algorithm"]:checked').all())await box.uncheck();
  await page.locator('[name="batch-algorithm"][value="rabas"]').check();
  await page.locator('[name="batch-algorithm"][value="profit_first"]').check();
  const disclosure=page.locator('[data-toggle="algo-create-rabas"]');
  await disclosure.click();assert.equal(await disclosure.getAttribute('aria-expanded'),'true');
  await page.locator('[data-params="rabas"]').fill(JSON.stringify({max_bundle_size:2,opportunity_cost_weight:.5}));
  await page.fill('#budget','5');
  const accepted=page.waitForResponse(r=>r.url().endsWith('/api/experiments')&&r.request().method()==='POST');
  await page.click('#submit');const response=await accepted;assert.equal(response.status(),202);
  const experiment=await response.json();assert.equal(experiment.runs.length,2);
  const rid=experiment.runs.find(r=>r.config.algorithm_id==='rabas').run_id;
  await page.waitForFunction(async id=>{const r=await(await fetch('/api/runs/'+id)).json();return r.status==='SUCCEEDED';},rid,{timeout:30000});
  await page.selectOption('#detail-algorithm',rid);
  await page.waitForFunction(id=>document.querySelector('#selected-run').textContent.includes(id)||
   document.querySelector('#selected-run').textContent.includes('RABAS'),rid);
  await page.waitForFunction(()=>document.querySelectorAll('#comparison-groups tbody tr').length===2);
  const expList=await(await context.request.get(info.url+'/api/experiments')).json();assert.equal(expList.total,1);
  const row=page.locator('#comparison-groups tbody tr').filter({hasText:'RABAS'});
  await page.waitForFunction(()=>[...document.querySelectorAll('#comparison-groups tbody tr')]
    .some(r=>r.textContent.includes('RABAS')&&r.textContent.includes('3 / 3')));
  assert.equal(await row.count(),1);assert.match(await row.innerText(),/3 \/ 3/);
  const gantt=await context.newPage();await gantt.goto(info.url+'/visualization/gantt/'+rid);
  await gantt.waitForFunction(()=>document.querySelectorAll('#ganttContainer button').length>=3);
  await gantt.locator('#ganttContainer button').first().focus();
  await gantt.waitForFunction(()=>!document.querySelector('#task-tooltip').hidden);
  const view=await context.newPage();await view.goto(info.url+'/visualization/cesium/'+rid,{waitUntil:'domcontentloaded',timeout:45000});
  await view.waitForFunction(()=>document.querySelector('#assetStatus').textContent.includes('body model'),null,{timeout:60000});
  await view.waitForFunction(()=>document.querySelectorAll('#assignmentList .assignment-row').length===3);
  await view.waitForFunction(id=>document.querySelector(`#cesium-comparison tr[data-run="${id}"]`)
    ?.getAttribute('aria-current')==='true',rid);
  assert.equal(new URL(view.url()).searchParams.get('run_id'),rid);
  const state=await view.evaluate(()=>({asset:document.querySelector('#assetStatus').textContent,
   replay:document.querySelector('#replayBuildStatus').textContent,
   intervals:document.querySelectorAll('#assignmentList .assignment-row').length}));
  assert.match(state.asset,/2 body model/);assert.equal(errors.length,0,errors.join('\n'));
  console.log('RABAS_BROWSER_PASS '+JSON.stringify({experiment:experiment.experiment_id,run_id:rid,
   algorithms:2,experiments:1,completed:3,gantt_tasks:await gantt.locator('#ganttContainer button').count(),...state,
   physical_certification:'SYNTHETIC_UNIT_TEST_ONLY'}));
 }finally{await browser.close();fs.writeFileSync(coord,JSON.stringify({...info,stop:true}));}
})().catch(e=>{console.error(e);process.exitCode=1;});
