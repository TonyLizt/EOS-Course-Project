/* Isolated real Chromium/Cesium UI. Seeded successful schedules use explicitly
   synthetic UNIT_TEST_INJECTION_ONLY receipts, not physical certification. */
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const info=JSON.parse(fs.readFileSync(process.env.EOS_BROWSER_QA_COORD,'utf8'));
 const proxyValue=process.env.EOS_BROWSER_PROXY||process.env.HTTPS_PROXY;
 const browser=await chromium.launch({headless:true,
  ...(proxyValue?{proxy:{server:proxyValue,bypass:'127.0.0.1,localhost'}}:{}),
  args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const errors=[];
 try{
  const context=await browser.newContext({viewport:{width:1536,height:1080},ignoreHTTPSErrors:true});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(info.url);await page.waitForFunction(()=>document.querySelectorAll('[name="batch-algorithm"]').length===9);
  assert.equal(await page.locator('#algorithm').count(),0);
  const initial=page.locator('.algorithm-card').filter({has:page.locator('[name="batch-algorithm"][value="profit_first"]')});
  const triangle=initial.locator('.algorithm-toggle');assert.equal(await triangle.count(),1);
  const checked=await initial.locator('input').isChecked();await triangle.click();
  assert.equal(await triangle.getAttribute('aria-expanded'),'true');assert.equal(await initial.locator('input').isChecked(),checked);
  await triangle.press('Space');assert.equal(await triangle.getAttribute('aria-expanded'),'false');
  await page.locator(`button.experiment-select[data-experiment="${info.experiment}"]`).click();
  await page.waitForFunction(()=>document.querySelectorAll('#comparison-groups tbody tr').length===2);
  assert.equal(await page.locator('#runs tr[data-experiment="'+info.experiment+'"]').count(),1);
  assert.match(await page.locator('.experiment-select').first().innerText(),/^实验 /);
  assert.doesNotMatch(await page.locator('#comparison-groups').innerText(),/条件组|profit_first|console-1/);
  const ids=()=>page.locator('#comparison-groups tbody tr').evaluateAll(bs=>bs.map(b=>b.dataset.run));
  assert.deepEqual(await ids(),info.runs);
  await page.selectOption('#comparison-mode','experiment');assert.deepEqual(await ids(),info.runs);
  assert.equal(await page.locator('#comparison-mode option').count(),2);
  await page.locator(`[data-result-id="${info.runs[0]}"]`).uncheck();
  assert.deepEqual(await ids(),[info.runs[1]]);
  assert.equal(await page.locator('[data-move],.result-position,.result-moves').count(),0);
  const checkSize=await page.locator('[data-result-id]').first().boundingBox();assert.ok(checkSize.width<=20&&checkSize.height<=20);
  const action=await page.locator('#create-control').boundingBox(),heading=await page.locator('#comparison-heading').boundingBox();assert.ok(action.x>heading.x&&Math.abs(action.y-heading.y)<60);
  await page.selectOption('#comparison-mode','algorithm');
  assert.deepEqual(await ids(),[info.runs[1]]);
  await page.locator(`[data-result-id="${info.runs[0]}"]`).check();
  // Detail addition uses checkboxes only; checking then cancelling does not submit.
  const detailAdd=page.locator('#experiment-algorithm-add');assert.equal(await detailAdd.locator('.algorithm-toggle,textarea').count(),0);
  await detailAdd.locator('[data-add-choice="sa"]').check();await detailAdd.locator('[data-add-choice="sa"]').uncheck();
  assert.equal(await detailAdd.locator('.confirm-algorithms').isDisabled(),true);
  const dbBefore=await(await context.request.get(info.url+'/api/runs')).json();
  const experimentsBefore=await(await context.request.get(info.url+'/api/experiments')).json();
  const cloneResponse=page.waitForResponse(r=>r.url().endsWith('/temporary-control')&&r.request().method()==='POST');
  await page.click('#create-control');const clone=await(await cloneResponse).json();
  assert.equal(clone.source_experiment_id,info.experiment);assert.equal(clone.temporary,true);assert.equal(clone.runs.length,2);
  assert.ok(clone.runs.every(r=>!info.runs.includes(r.run_id)));
  await page.waitForFunction(()=>document.querySelectorAll('#comparison-groups tbody tr').length===4);
  assert.equal(await page.locator('#create-control').innerText(),'移除临时对照');
  assert.equal((await(await context.request.get(info.url+'/api/runs')).json()).total,dbBefore.total);
  assert.equal((await(await context.request.get(info.url+'/api/experiments')).json()).total,experimentsBefore.total);
  assert.equal(await page.locator('#comparison-groups a[href*="temporary-"]').count(),0);
  await page.click('#create-control');await page.waitForFunction(()=>document.querySelector('#create-control').textContent==='一键创建对照实验');
  assert.equal(await page.locator('#comparison-groups tbody tr').count(),2);
  assert.equal((await context.request.get(info.url+'/api/temporary-controls/'+clone.experiment_id)).status(),404);
  // A normal multi-algorithm submission adds one parent list entry.
  const before=await(await context.request.get(info.url+'/api/experiments')).json();
  await page.selectOption('#execution-mode','formal');await page.waitForSelector('#scenario option[value="empty"]',{state:'attached'});
  await page.selectOption('#scenario','empty');await page.fill('#budget','1');
  await page.locator('[name="batch-algorithm"][value="sa"]').check();
  const sa=page.locator('.algorithm-card').filter({has:page.locator('[name="batch-algorithm"][value="sa"]')});
  await sa.locator('.algorithm-toggle').click();await sa.locator('textarea').fill('{"max_iterations":2}');
  const submitted=page.waitForResponse(r=>r.url()===info.url+'/api/experiments'&&r.request().method()==='POST');
  await page.click('#submit');const created=await(await submitted).json();assert.equal(created.runs.length,2);
  const after=await(await context.request.get(info.url+'/api/experiments')).json();assert.equal(after.total,before.total+1);
  // Actual existing Cesium page and rendering engine, not an iframe shell.
  const view=await context.newPage();view.on('pageerror',e=>errors.push(String(e)));
  await view.goto(info.url+'/visualization/cesium/'+info.runs[0],{waitUntil:'domcontentloaded',timeout:60000});
  async function rendered(runId,runtime,start){
   await view.waitForFunction(()=>document.querySelector('#assetStatus').textContent.includes('2 body model'),null,{timeout:60000});
   await view.waitForSelector(`#cesium-comparison tr.selected[data-run="${runId}"]`);
   assert.match(await view.locator('#metrics').innerText(),new RegExp(runtime));
   assert.match(await view.locator('#assignmentList').innerText(),new RegExp(start));
   const url=new URL(view.url());assert.equal(url.searchParams.get('run_id'),runId);
   assert.equal(url.searchParams.get('schedule'),`/api/runs/${runId}/visualization/schedule`);
   assert.equal(url.searchParams.get('replay_status'),`/api/runs/${runId}/replay`);
   assert.equal(url.searchParams.get('gantt'),`/visualization/gantt/${runId}`);
   // Cesium itself owns an InfoBox iframe; only the old outer scene iframe is forbidden.
   assert.equal(await view.locator('#algorithm-frame').count(),0);assert.equal(await view.locator('.payload-tile').count(),2);
   assert.equal(await view.evaluate(()=>document.querySelector('#experiment-controls').parentElement.id),'leftPanel');
   assert.equal(await view.evaluate(()=>document.querySelector('#cesium-comparison-section').parentElement.id),'rightPanel');
   assert.equal(await view.evaluate(()=>document.querySelector('#cesium-comparison-section').previousElementSibling.querySelector('h2').textContent),'Observation Intervals');
   assert.equal(await view.locator('[data-move],.result-position,.result-moves,#cesium-peer').count(),0);
   assert.equal(await view.locator('#cesium-comparison tbody tr').count(),2);
   assert.doesNotMatch(await view.locator('#cesium-comparison').innerText(),/临时对照/);
   const parentOrder=await view.evaluate(()=>[...document.querySelector('#leftPanel').children].map(n=>n.id||n.querySelector('h2')?.textContent));
   assert.ok(parentOrder.indexOf('Metrics')<parentOrder.indexOf('experiment-controls'));
   assert.equal(await view.locator('#cesiumContainer canvas').count()>0,true);
  }
  await rendered(info.runs[0],'0.010','00:00:40');
  await view.locator(`[data-replay="${info.runs[1]}"]`).click();
  await view.waitForURL(url=>url.searchParams.get('run_id')===info.runs[1],{timeout:60000});
  await rendered(info.runs[1],'0.020','00:00:50');
  assert.equal(await view.locator('#cesium-comparison tr.selected').count(),1);
  assert.equal(await view.locator('#cesium-add-algorithms [data-add-choice]').count(),7);
  assert.equal(await view.locator('#cesium-add-algorithms [data-add-choice="profit_first"]').count(),0);
  assert.doesNotMatch(await view.locator('#cesium-current-algorithms .algorithm-heading').allInnerTexts().then(x=>x.join(' ')),/SUCCEEDED|当前回放/);
  assert.equal(await view.locator('#cesium-current-algorithms [aria-current="true"]').count(),1);
  assert.equal(await view.locator('#cesium-add-algorithms').evaluate(e=>getComputedStyle(e).maxHeight),'none');
  assert.equal(await view.locator('#cesium-add-algorithms').evaluate(e=>getComputedStyle(e).overflowY),'visible');
  // Hide/show with a selected 2x2 tile: no stale frame, time or selection reset.
  await view.locator('.payload-tile').first().click();
  const tileId=await view.locator('.payload-tile.is-selected').getAttribute('data-satellite-id');
  await view.click('#togglePayloadView');assert.equal(await view.locator('#payloadSatelliteGrid').isVisible(),false);
  assert.equal(await view.locator('#togglePayloadView').getAttribute('aria-expanded'),'false');
  assert.match(await view.locator('#togglePayloadView').innerText(),/Show grid/);
  await view.click('#togglePayloadView');assert.equal(await view.locator('#payloadSatelliteGrid').isVisible(),true);
  assert.equal(await view.locator('.payload-tile.is-selected').getAttribute('data-satellite-id'),tileId);
  await view.waitForFunction(()=>[...document.querySelectorAll('.payload-tile canvas')].every(c=>c.dataset.renderSequence&&c.style.visibility!=='hidden'),null,{timeout:60000});
  await view.locator('#cesium-add-algorithms [data-add-choice="sa"]').check();await view.locator('#cesium-add-algorithms .confirm-algorithms').click();
  await view.waitForFunction(()=>document.querySelectorAll('#cesium-current-algorithms .algorithm-card').length===3);
  assert.equal(await view.locator('#cesium-add-algorithms [data-add-choice="sa"]').count(),0);
  const exp=await(await context.request.get(info.url+'/api/experiments/'+info.experiment)).json();
  const added=exp.runs.find(r=>r.config.algorithm_id==='sa');assert.ok(added);
  const remove=view.locator('#cesium-current-algorithms .algorithm-card').filter({has:view.locator('[data-remove="sa"]')});
  await remove.locator('.algorithm-toggle').click();view.on('dialog',d=>d.accept());await remove.locator('[data-remove]').click();
  await view.waitForFunction(()=>document.querySelectorAll('#cesium-current-algorithms .algorithm-card').length===2);
  await view.waitForSelector('#cesium-add-algorithms [data-add-choice="sa"]');
  assert.equal((await context.request.get(info.url+'/api/runs/'+added.run_id)).status(),200);
  assert.equal(new URL(view.url()).searchParams.get('run_id'),info.runs[1]);
  // Gantt remains bound to the chosen Run, with magnetic hits outside tiny bars.
  const gantt=await context.newPage();gantt.on('pageerror',e=>errors.push(String(e)));
  await gantt.goto(info.url+'/visualization/gantt/'+info.runs[1]);await gantt.waitForSelector('.gantt-bar');
  const original=await gantt.locator('.gantt-bar[data-index="1"]').getAttribute('aria-label');assert.match(original,/00:00:50/);
  const tiny=gantt.locator('.gantt-bar[data-index="1"]'),rect=await tiny.boundingBox();
  assert.ok(rect.width<12);await gantt.mouse.move(rect.x+rect.width+5,rect.y+rect.height/2);
  await gantt.waitForSelector('.gantt-bar[data-index="1"].is-snapped');
  assert.match(await gantt.locator('#task-tooltip').innerText(),/M2/);
  await gantt.mouse.click(rect.x+rect.width+5,rect.y+rect.height/2);assert.match(await gantt.locator('#task-detail').innerText(),/00:00:50/);
  await gantt.mouse.move(rect.x+100,rect.y+rect.height/2);assert.equal(await gantt.locator('#task-tooltip').isVisible(),false);
  await gantt.selectOption('#task-select','1');const bar=gantt.locator('.gantt-bar[data-index="1"]');
  assert.ok((await bar.boundingBox()).width>24);assert.equal(await bar.getAttribute('aria-label'),original);
  await bar.focus();await gantt.keyboard.press('Enter');assert.match(await gantt.locator('#task-detail').innerText(),/M2/);
  await gantt.click('#zoom-out');await gantt.click('#pan-right');await gantt.click('#pan-left');
  assert.match(await gantt.locator('#cesium-link').getAttribute('href'),new RegExp(info.runs[1]));
  const traditional=/[實驗衛場狀顯視圖載關開與設標軌隨觀選務啟體護動暫兩時聯連計畫細捲結輸僅繼續頁報錯誤覽數據檔讀寫運]/;
  for(const p of [page,view,gantt])assert.equal(traditional.test(await p.locator('body').innerText()),false);
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.deepEqual(errors,[]);
  console.log('UNIFIED_INTERACTIONS_OK '+JSON.stringify({experiment:info.experiment,clone:clone.experiment_id,newExperiment:created.experiment_id,cesium:'real Chromium/SwiftShader, 2 satellites',errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
