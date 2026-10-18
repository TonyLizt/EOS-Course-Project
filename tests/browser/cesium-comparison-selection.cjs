/* Read-only UI verification against the existing two-satellite isolated fixture. */
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const info=JSON.parse(fs.readFileSync(process.env.EOS_BROWSER_QA_COORD,'utf8'));
 const proxy=process.env.EOS_BROWSER_PROXY||process.env.HTTPS_PROXY;
 const browser=await chromium.launch({headless:true,
  ...(proxy?{proxy:{server:proxy,bypass:'127.0.0.1,localhost'}}:{}),
  args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1536,height:1080},ignoreHTTPSErrors:true});
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(info.url+'/visualization/cesium/'+info.runs[0],{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('#assetStatus').textContent.includes('2 body model'),null,{timeout:60000});
  const choices=page.locator('#cesium-comparison-choices'),table=page.locator('#cesium-comparison');
  await page.waitForSelector('#cesium-comparison-choices input[type="checkbox"]');
  assert.equal(await choices.locator('input[type="checkbox"]').count(),2);
  assert.equal(await choices.locator('fieldset,legend,.result-group,.result-choice,[data-move],.result-position').count(),0);
  assert.equal(await choices.locator('.comparison-options > label.add-algorithm-option').count(),2);
  const names=await choices.locator('label span').allTextContents();assert.equal(new Set(names).size,2);
  assert.doesNotMatch(names.join(' '),/正式实验|临时对照|完成率优先|SUCCEEDED|console-/);
  const first=choices.locator(`[data-result-id="${info.runs[0]}"]`);
  await first.focus();await first.press('Space');
  assert.equal(await table.locator('tbody tr').count(),1);
  assert.equal(await first.isChecked(),false);
  await choices.locator('label').first().click();
  assert.equal(await table.locator('tbody tr').count(),2);
  const order=await choices.locator('input').evaluateAll(nodes=>nodes.map(n=>n.dataset.resultId));
  await page.selectOption('#cesium-comparison-mode','experiment');
  assert.deepEqual(await choices.locator('input').evaluateAll(nodes=>nodes.map(n=>n.dataset.resultId)),order);
  assert.equal(await choices.locator('fieldset,legend').count(),0);
  await page.selectOption('#cesium-comparison-mode','algorithm');
  assert.equal(await table.locator(`tr.selected[data-run="${info.runs[0]}"]`).count(),1);
  assert.equal(await page.evaluate(()=>document.querySelector('#cesium-comparison-section').parentElement.id),'rightPanel');
  assert.equal(await page.evaluate(()=>document.querySelector('#cesium-comparison-section').previousElementSibling.querySelector('h2').textContent),'Observation Intervals');
  assert.equal(await page.evaluate(()=>document.querySelector('#experiment-controls').parentElement.id),'leftPanel');
  assert.equal(await page.locator('.payload-tile').count(),2);
  await table.locator(`button[data-run="${info.runs[1]}"]`).click();
  await page.waitForURL(url=>url.searchParams.get('run_id')===info.runs[1],{timeout:60000});
  await page.waitForSelector(`#cesium-comparison tr.selected[data-run="${info.runs[1]}"]`);
  await page.waitForFunction(()=>document.querySelector('#metrics').textContent.includes('0.020')&&document.querySelector('#assignmentList').textContent.includes('00:00:50'),null,{timeout:60000});
  assert.match(await page.locator('#metrics').innerText(),/0\.020/);
  assert.match(await page.locator('#assignmentList').innerText(),/00:00:50/);
  assert.equal(await page.locator('#cesium-comparison tr.selected').count(),1);
  assert.equal(await page.locator('#cesium-comparison-choices fieldset').count(),0);
  await page.locator('#cesium-comparison-section').screenshot({path:'/tmp/eos-cesium-compact-comparison.png'});
  assert.deepEqual(errors,[]);
  console.log('CESIUM_COMPACT_SELECTION_OK '+JSON.stringify({algorithms:names,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
