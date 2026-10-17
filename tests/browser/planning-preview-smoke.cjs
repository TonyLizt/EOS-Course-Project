/* Connect only to an isolated QA runtime with real 10-satellite scenarios. */
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const base = process.env.EOS_PREVIEW_QA_URL;
  assert.ok(base, 'EOS_PREVIEW_QA_URL must identify an isolated runtime');
  const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport:{width:1480,height:1050}}), errors=[];
    page.on('pageerror',error=>errors.push(String(error)));
    const response = await page.goto(base);
    assert.match(response.headers()['cache-control'], /no-store/);
    await page.waitForFunction(()=>document.querySelectorAll('[name="batch-algorithm"]').length===9);
    assert.equal(await page.inputValue('#execution-mode'),'planning_preview');
    assert.match(await page.locator('h1').innerText(),/统一调度控制台/);
    await page.selectOption('#scenario','small/Scenario_S2_Sats10_M20_T1.0d_dist0_epoch_fixed_v1');
    await page.selectOption('#schedule-model', 'adaptive_repair');
    await page.locator('[name="batch-algorithm"][value="timeliness_first"]').check();
    await page.fill('#budget','5'); await page.click('#submit');
    await page.waitForFunction(()=>document.querySelector('#form-message').textContent.includes('2/2'));
    const ids=(await page.locator('#submission-results li').allTextContents()).map(s=>s.match(/[0-9a-f]{8}-[0-9a-f-]{27,}/)[0]);
    const runs=[];
    for(const id of ids){
      let run;
      for(let i=0;i<100;i++){
        run=await(await page.request.get(base+'/api/runs/'+id)).json();
        if(['SUCCEEDED','FAILED','CANCELLED','TIMED_OUT'].includes(run.status))break;
        await page.waitForTimeout(300);
      }
      assert.equal(run.status,'SUCCEEDED',JSON.stringify(run.error));
      assert.equal(run.result_kind,'planning_preview');
      assert.equal(run.config.schedule_model, 'adaptive_repair');
      assert.equal(run.continuous_certification.status,'NOT_CERTIFIED');
      assert.ok(run.metrics.completed_tasks>0);
      assert.equal((await page.request.get(base+'/api/runs/'+id+'/export?format=json')).status(),409);
      runs.push({id,algorithm:run.config.algorithm_id,completed:run.metrics.completed_tasks,total:run.metrics.total_tasks,TCR:run.metrics.TCR});
    }
    await page.waitForFunction(()=>document.querySelectorAll('#comparison-groups .metric-best').length>0);
    assert.match(await page.locator('#comparison-groups').innerText(),/规划预览完成/);
    const gantt = await browser.newPage();
    await gantt.goto(base+'/visualization/gantt/'+ids[0]);
    await gantt.waitForSelector('.gantt-bar',{state:'attached'});
    assert.match(await gantt.locator('#sourceLabel').innerText(),/未取得正式连续认证/);
    await gantt.selectOption('#task-select','0');
    await gantt.locator('.gantt-bar[data-index="0"]').hover();
    assert.equal(await gantt.locator('#task-tooltip').isVisible(),true);
    assert.deepEqual(errors,[]);
    console.log('REAL_PREVIEW_BROWSER_OK '+JSON.stringify(runs));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1)});
