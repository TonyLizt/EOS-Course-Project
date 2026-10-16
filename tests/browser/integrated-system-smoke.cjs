// 可选真实浏览器验收：仅连接 serve_integrated_fixture.py 创建的隔离服务。
// 环境变量传入 Playwright、浏览器路径和协调文件；本机路径不进入仓库。
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const coord = process.env.EOS_BROWSER_QA_COORD;
  if (!coord) throw new Error('请设置 EOS_BROWSER_QA_COORD');
  const info = JSON.parse(fs.readFileSync(coord,'utf8'));
  const browser = await chromium.launch({
    headless:true,
    ...(process.env.EOS_BROWSER_EXECUTABLE ? {executablePath:process.env.EOS_BROWSER_EXECUTABLE} : {}),
    ...(process.env.EOS_BROWSER_PROXY ? {proxy:{server:process.env.EOS_BROWSER_PROXY,bypass:'127.0.0.1,localhost'}} : {}),
    args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']
  });
  const errors=[], failedResponses=[], requests=[];
  try {
    const context = await browser.newContext({viewport:{width:1600,height:1000},timezoneId:'Asia/Shanghai'});
    context.on('page',p => {
      p.on('pageerror',e => errors.push(String(e)));
      p.on('console',m => {if(m.type()==='error') errors.push(m.text()+' '+JSON.stringify(m.location()));});
      p.on('request',r => requests.push({method:r.method(),url:r.url()}));
      p.on('response',r => {if(r.status()>=400) failedResponses.push({status:r.status(),url:r.url()});});
    });
    const page = await context.newPage();
    await page.goto(info.url);
    await page.waitForFunction(() => document.querySelector('#health').textContent.includes('服务已连接'));
    await page.click('details.location-setup > summary');
    await page.selectOption('#register-kind','output');
    await page.fill('#register-name','隔离浏览器测试输出');
    await page.fill('#register-path',info.output);
    await page.click('#register-location');
    await page.waitForFunction(() => document.querySelector('#register-message').textContent.startsWith('已登记'));
    await page.selectOption('#scenario','empty');
    await page.fill('#budget','1');
    await page.click('#submit');
    await page.waitForFunction(() => document.querySelector('#detail-status').textContent==='SUCCEEDED',null,{timeout:30000});
    const emptyRun = await page.locator('#selected-run').innerText();
    const exports = await page.locator('#files').innerText();
    assert.ok(exports.includes('.json') && exports.includes('.csv'), exports);
    const downloadPromise = page.waitForEvent('download');
    await page.click('#export-json');
    const download = await downloadPromise;
    assert.ok(download.suggestedFilename().endsWith('.json'));
    console.log('ROOT_UI_OK '+JSON.stringify({emptyRun,exports,download:download.suggestedFilename()}));
    await page.locator('tr[data-id="'+info.run_id+'"]').click();
    await page.waitForFunction(id => document.querySelector('#selected-run').textContent===id,info.run_id);
    const view = await context.newPage();
    await view.goto(info.url+await page.locator('#open-cesium').getAttribute('href'),{waitUntil:'domcontentloaded',timeout:60000});
    await view.waitForFunction(() => document.querySelector('#assetStatus').textContent.includes('2 body model'),null,{timeout:60000});
    await view.locator('.assignment-row').first().click();
    await view.waitForTimeout(1200);
    const result = await view.evaluate(() => {
      const ds=viewer.dataSources.get(0), now=viewer.clock.currentTime;
      const body=ds.entities.getById('sat-a');
      const cone=viewer.entities.getById('fixed-payload-frustum-cap-sat-a');
      return {
        time:Cesium.JulianDate.toIso8601(now), animate:viewer.clock.shouldAnimate,
        bodyPosition:!!body.position.getValue(now),bodyOrientation:!!body.orientation.getValue(now),
        satellitePoint:Cesium.defined(body.point),satellitePath:Cesium.defined(body.path),
        trackingFrame:body.trackingReferenceFrame,
        enuTrackingFrame:Cesium.TrackingReferenceFrame.ENU,
        selectedId:viewer.selectedEntity && viewer.selectedEntity.id,
        cone:typeof cone.show==='boolean' ? cone.show : cone.show.getValue(now),
        payload:document.querySelector('#payloadViewStatus').textContent,
        models:document.querySelector('#assetStatus').textContent,
        secondaryAnimate:viewer._payloadViewer.clock.shouldAnimate
      };
    });
    assert.ok(result.time.startsWith('2026-01-01T00:00:10'),JSON.stringify(result));
    assert.equal(result.animate,false);
    assert.equal(result.secondaryAnimate,false);
    assert.equal(result.bodyPosition,true);
    assert.equal(result.bodyOrientation,true);
    assert.equal(result.satellitePoint,false);
    assert.equal(result.satellitePath,true);
    assert.equal(result.trackingFrame,result.enuTrackingFrame);
    assert.equal(result.selectedId,'sat-a');
    assert.equal(result.cone,true);
    assert.ok(result.payload.includes('OBSERVING'),JSON.stringify(result));
    await view.evaluate(() => {
      viewer.clock.currentTime=Cesium.JulianDate.fromIso8601('2026-01-01T00:00:15Z');
      viewer.clock.tick();viewer.scene.requestRender();
    });
    await view.waitForTimeout(300);
    const endpoint = await view.evaluate(() => document.querySelector('#payloadViewStatus').textContent);
    assert.ok(endpoint.includes('IDLE'),endpoint);
    assert.equal(requests.filter(r => r.url.includes('/visualization/orbit.czml')).length,0);
    assert.equal(requests.filter(r => r.method==='POST' && r.url.endsWith('/replay')).length,1);
    // 首次打开自动申请一次；视图的播放、跳转均不得触发第二次构建。
    console.log('CESIUM_UI_OK '+JSON.stringify({result,endpoint,legacyOrbitRequests:0,errors,failedResponses}));
    assert.equal(errors.length,0,JSON.stringify({errors,failedResponses}));
    await view.close();
    await page.locator('tr[data-id="'+emptyRun+'"]').click();
    await page.waitForFunction(id => document.querySelector('#selected-run').textContent===id,emptyRun);
    await page.check('#delete-files');
    page.once('dialog',d => d.accept());
    await page.click('#delete-run');
    await page.waitForFunction(id => !document.querySelector('tr[data-id="'+id+'"]'),emptyRun);
    console.log('DELETE_UI_OK');
  } finally {
    await browser.close();
    // 请求 fixture 进程退出；它负责结束服务并清理临时库、场景与缓存。
    if (fs.existsSync(coord)) fs.writeFileSync(coord,JSON.stringify({...info,stop:true}));
  }
})().catch(error => {console.error(error.stack);process.exitCode=1;});
