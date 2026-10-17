/* Existing synthetic two-star history + ONE memory-only control, UI/lease QA.
   Use serve_console_fixture.py --synthetic-temporary; not a physical benchmark. */
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const info=JSON.parse(fs.readFileSync(process.env.EOS_BROWSER_QA_COORD,'utf8'));
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const errors=[];
 try{
  const context=await browser.newContext({viewport:{width:1536,height:1080}});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(info.url);
  await page.locator(`.experiment-select[data-experiment="${info.experiment}"]`).click();
  await page.waitForSelector('#comparison-choices input');
  const filters=page.locator('#comparison-choices');
  assert.equal(await filters.locator('fieldset,legend').count(),0);
  assert.doesNotMatch(await filters.innerText(),/SUCCEEDED|FAILED|曝光|TCR|TP|Gantt/);
  const first=filters.locator('input').first();await first.uncheck();
  assert.equal(await page.locator('#comparison-groups tbody tr').count(),1);
  await first.check();assert.equal(await page.locator('#comparison-groups tbody tr').count(),2);
  assert.equal(await page.locator('#comparison-groups a[href^="/visualization/gantt/"]').count(),2);
  const counts=async()=>Promise.all(['/api/experiments','/api/runs'].map(async path=>(await(await context.request.get(info.url+path)).json()).total));
  const before=await counts();
  await page.click('#create-control');
  await page.waitForSelector('#comparison-groups a[href^="/visualization/temporary-gantt/"]');
  const link=page.locator('#comparison-groups a[href^="/visualization/temporary-gantt/"]').last();
  const href=await link.getAttribute('href');const [,sid,rid]=href.match(/temporary-gantt\/([^/]+)\/([^/]+)/);
  const popup=context.waitForEvent('page');await link.click();const gantt=await popup;
  gantt.on('pageerror',e=>errors.push(String(e)));await gantt.waitForSelector('.gantt-bar');
  assert.match(await gantt.locator('#sourceLabel').innerText(),/临时对照/);
  assert.equal(await gantt.locator('#cesium-link').isVisible(),false);
  const bar=gantt.locator('.gantt-bar[data-index="1"]'),rect=await bar.boundingBox();
  await gantt.mouse.move(rect.x+rect.width+5,rect.y+rect.height/2);
  await gantt.waitForSelector('.gantt-bar[data-index="1"].is-snapped');
  assert.match(await gantt.locator('#task-tooltip').innerText(),/00:00:50/);
  await gantt.selectOption('#task-select','1');assert.ok((await bar.boundingBox()).width>20);
  await bar.focus();await bar.press('Enter');assert.match(await gantt.locator('#task-detail').innerText(),/5 秒/);
  await gantt.click('#zoom-out');await gantt.click('#pan-right');await gantt.click('#pan-left');
  assert.deepEqual(await counts(),before);
  assert.equal((await context.request.get(info.url+'/api/runs/'+rid)).status(),404);
  assert.equal((await context.request.get(info.url+'/visualization/cesium/'+rid)).status(),404);
  const current=await(await context.request.get(info.url+'/api/experiments/'+info.experiment)).json();
  assert.deepEqual(current.runs.map(r=>r.run_id),info.runs);
  await page.click('#create-control');
  await gantt.waitForFunction(()=>document.querySelector('#sourceLabel').textContent.includes('已失效'),null,{timeout:15000});
  assert.equal(await gantt.locator('.gantt-bar').count(),0);
  assert.equal(await gantt.locator('#zoom-in').isDisabled(),true);
  assert.equal((await context.request.get(info.url+`/api/temporary-controls/${sid}/runs/${rid}/schedule`)).status(),404);
  await gantt.reload();await gantt.waitForFunction(()=>document.querySelector('#sourceLabel').textContent.includes('已失效'));
  assert.equal(await gantt.locator('.gantt-bar').count(),0);
  await page.reload();await page.waitForFunction(()=>document.querySelector('#create-control').textContent==='一键创建对照实验');
  assert.deepEqual(await counts(),before);assert.deepEqual(errors,[]);
  console.log('TEMPORARY_GANTT_OK '+JSON.stringify({counts:before,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
