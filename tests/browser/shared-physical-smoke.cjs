// Real build_shared_dataset pilot, isolated HTTP runtime. Never a certificate.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const info=JSON.parse(fs.readFileSync(process.env.EOS_SHARED_P7_COORD,'utf8'));
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(info.url);await page.waitForSelector('[name="batch-algorithm"][value="caabs"]',{state:'attached'});
  await page.waitForFunction(()=>document.querySelector('#scenario-hint').textContent.includes('verified_generation'));
  assert.equal(await page.inputValue('#execution-mode'),'physical_validation');
  assert.equal(await page.locator('#execution-mode-control').isVisible(),false);
  await require('./workspace-navigation.cjs').step(page,2);
  for(const input of await page.locator('[name="batch-algorithm"]:checked').all())await input.uncheck();
  await page.locator('[name="batch-algorithm"][value="caabs"]').check();
  await require('./workspace-navigation.cjs').step(page,3);await page.fill('#budget','10');
  const response=page.waitForResponse(r=>r.url()===info.url+'/api/experiments'&&r.request().method()==='POST');
  await page.click('#submit');const accepted=await response;assert.equal(accepted.status(),202,await accepted.text());
  const sent=accepted.request().postDataJSON().runs[0];
  const exp=await accepted.json();const id=exp.runs[0].run_id;
  async function wait(id){let run;for(let n=0;n<500;n++){
   run=await(await page.request.get(info.url+'/api/runs/'+id)).json();
   if(['SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'].includes(run.status))return run;
   await page.waitForTimeout(250);
  }throw Error('bounded shared pilot wait expired '+JSON.stringify(run.error));}
  const run=await wait(id);
  assert.equal(run.status,'SUCCEEDED',JSON.stringify(run.error));assert.ok(run.metrics.completed_tasks>0);
  assert.equal(run.config.scenario_sha256,info.sha);assert.equal(run.result_kind,'physical_validation');
  assert.equal(run.continuous_certification.status,'NOT_CERTIFIED');
  const json=await page.request.get(info.url+`/api/runs/${id}/export?format=json`);
  assert.equal(json.status(),200);const exported=await json.json();
  assert.equal(exported.result_kind,'physical_validation');assert.equal(exported.physical_validation.status,'SAMPLED_PHYSICAL_PASS');
  assert.match(exported.physical_validation.validation_scope,/not a continuous/);
  const csv=await page.request.get(info.url+`/api/runs/${id}/export?format=csv`);
  assert.equal(csv.status(),200);assert.match(await csv.text(),/SAMPLED_PHYSICAL_PASS/);
  await page.locator('nav [data-console-route="records"]').click();
  await page.waitForFunction(()=>document.querySelector('#detail-status').textContent.includes('SUCCEEDED'));
  assert.match(await page.locator('#detail-status').innerText(),/工程物理核验/);
  await page.screenshot({path:info.output+'/shared-console.png',fullPage:true});
  const gantt=await browser.newPage();await gantt.goto(info.url+'/visualization/gantt/'+id);
  await gantt.waitForSelector('.gantt-bar',{state:'attached'});
  const label=await gantt.locator('#sourceLabel').innerText();
  assert.match(label,/工程物理核验通过/);assert.match(label,/非严格连续证明/);
  assert.doesNotMatch(label,/连续认证通过/);
  await gantt.screenshot({path:info.output+'/shared-gantt.png',fullPage:true});
  const formalResponse=await page.request.post(info.url+'/api/runs',{data:{...sent,execution_mode:'formal'}});
  assert.equal(formalResponse.status(),202);
  const formal=await wait((await formalResponse.json()).run_id);
  assert.equal(formal.status,'FAILED',JSON.stringify(formal.error));assert.equal(formal.plan,null);
  assert.match(JSON.stringify(formal.error),/CONTINUOUS|CONTINUITY|INCONCLUSIVE/);
  const listing=await(await page.request.get(info.url+'/api/experiments')).json();
  let formalExperiment;
  for(const item of listing.items){
   const detail=await(await page.request.get(info.url+'/api/experiments/'+item.experiment_id)).json();
   if(detail.runs.some(r=>r.run_id===formal.run_id)){formalExperiment=item.experiment_id;break;}
  }
  assert.ok(formalExperiment);
  await page.goto(info.url+'/?experiment_id='+encodeURIComponent(formalExperiment)+'#experiments');
  await page.waitForFunction(()=>document.querySelector('#detail-status').textContent.includes('FAILED'));
  assert.match(await page.locator('#detail-error').innerText(),/NO_CONTINUITY_CERTIFICATE/);
  assert.equal(await page.locator('#export-json').isVisible(),false);
  await page.screenshot({path:info.output+'/formal-rejection-console.png',fullPage:true});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(info.output+'/browser-results.json',JSON.stringify({run,formal,page_errors:errors},null,2),{flag:'wx'});
  console.log('SHARED_REAL_BROWSER_PASS '+JSON.stringify({run_id:id,completed:run.metrics.completed_tasks,total:run.metrics.total_tasks,formal:formal.status}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
