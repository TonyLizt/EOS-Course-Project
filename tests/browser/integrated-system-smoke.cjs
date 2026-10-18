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
    await require('./workspace-navigation.cjs').step(page,3);
    await page.fill('#budget','1');
    await page.click('#submit');
    await page.waitForFunction(() => document.querySelector('#detail-status').textContent==='SUCCEEDED',null,{timeout:30000});
    const emptyRun = await page.locator('#selected-run').innerText();
    await page.locator('details').filter({has:page.locator('#files')}).locator('summary').click();
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
    await view.waitForFunction(() => document.querySelector('#assetStatus').textContent.includes('2 body model'),null,{timeout:60000})
      .catch(async error => {
        const pageState=await view.evaluate(() => ({
          asset:document.querySelector('#assetStatus')?.textContent,
          replay:document.querySelector('#replayBuildStatus')?.textContent
        }));
        throw new Error(error.message+' '+JSON.stringify({pageState,errors,failedResponses}));
      });
    const payloadTiles = view.locator('.payload-tile');
    assert.equal(await payloadTiles.count(),2);
    assert.equal(await view.locator('.payload-tile.is-selected').count(),0);
    await view.locator('.assignment-select').first().click();
    await view.waitForFunction(
      () => document.querySelector('#payloadViewStatus').textContent.includes('OBSERVING'),
      null, {timeout:30000}
    );
    const result = await view.evaluate(() => {
      const ds=viewer.dataSources.get(0), now=viewer.clock.currentTime;
      const body=ds.entities.getById('sat-a');
      const cone=viewer.entities.getById('fixed-payload-frustum-cap-sat-a');
      const nodeTransforms=body.model.nodeTransformations.getValue(now);
      const recenter=nodeTransforms['Pivot-Layer_0'].translation;
      return {
        time:Cesium.JulianDate.toIso8601(now), animate:viewer.clock.shouldAnimate,
        bodyPosition:!!body.position.getValue(now),bodyOrientation:!!body.orientation.getValue(now),
        satellitePoint:Cesium.defined(body.point),satellitePath:Cesium.defined(body.path),
        trackingFrame:body.trackingReferenceFrame,
        modelRecenter:[recenter.x,recenter.y,recenter.z],
        enuTrackingFrame:Cesium.TrackingReferenceFrame.ENU,
        selectedId:viewer.selectedEntity && viewer.selectedEntity.id,
        cone:typeof cone.show==='boolean' ? cone.show : cone.show.getValue(now),
        payload:document.querySelector('#payloadViewStatus').textContent,
        models:document.querySelector('#assetStatus').textContent,
        secondaryAnimate:viewer._payloadViewer.clock.shouldAnimate,
        payloadTileCount:document.querySelectorAll('.payload-tile').length,
        selectedPayloadTile:document.querySelector('.payload-tile.is-selected')?.dataset.satelliteId,
        selectedPayloadPressed:document.querySelector('.payload-tile.is-selected')?.getAttribute('aria-pressed'),
        geometryStatus:document.querySelector('.assignment-visibility')?.textContent
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
    assert.ok(Math.abs(result.modelRecenter[1]-3.6797085867)<1e-9,JSON.stringify(result));
    assert.ok(Math.abs(result.modelRecenter[2]+3.6108138651)<1e-9,JSON.stringify(result));
    assert.equal(result.selectedId,'sat-a');
    assert.equal(result.payloadTileCount,2);
    assert.equal(result.selectedPayloadTile,'sat-a');
    assert.equal(result.selectedPayloadPressed,'true');
    assert.equal(result.geometryStatus,'Visible');
    assert.equal(result.cone,true);
    assert.ok(result.payload.includes('OBSERVING'),JSON.stringify(result));
    await view.evaluate(() => {
      viewer.clock.currentTime=Cesium.JulianDate.fromIso8601('2026-01-01T00:00:15Z');
      viewer.clock.tick();viewer.scene.requestRender();
    });
    await view.waitForFunction(
      () => document.querySelector('#payloadViewStatus').textContent.includes('IDLE'),
      null, {timeout:30000}
    );
    const endpoint = await view.evaluate(() => document.querySelector('#payloadViewStatus').textContent);
    assert.ok(endpoint.includes('IDLE'),endpoint);
    await view.keyboard.press('Escape');
    await view.waitForTimeout(400);
    assert.equal(await view.locator('.payload-tile.is-selected').count(),0);
    assert.ok((await view.locator('#payloadViewStatus').innerText()).includes('1 × 1'));
    await payloadTiles.first().click();
    await view.waitForTimeout(800);
    const autoFollow = await view.evaluate(() => {
      const tile=document.querySelector('.payload-tile.is-selected');
      const entity=viewer.trackedEntity;
      const position=entity.position.getValue(viewer.clock.currentTime);
      return {
        trackedId:entity && entity.id,
        selectedId:viewer.selectedEntity && viewer.selectedEntity.id,
        gridColumnStart:getComputedStyle(tile).gridColumnStart,
        gridRowStart:getComputedStyle(tile).gridRowStart,
        range:Cesium.Cartesian3.distance(viewer.camera.positionWC,position),
        cameraBeforeEscape:Cesium.Cartesian3.clone(viewer.camera.positionWC)
      };
    });
    assert.equal(autoFollow.trackedId,'sat-a');
    assert.equal(autoFollow.selectedId,'sat-a');
    assert.equal(autoFollow.gridColumnStart,'span 2');
    assert.equal(autoFollow.gridRowStart,'span 2');
    assert.ok(autoFollow.range<500,JSON.stringify(autoFollow));
    await view.keyboard.press('Escape');
    await view.waitForTimeout(400);
    const released = await view.evaluate(before => ({
      trackedId:viewer.trackedEntity && viewer.trackedEntity.id,
      selectedTiles:document.querySelectorAll('.payload-tile.is-selected').length,
      cameraDelta:Cesium.Cartesian3.distance(viewer.camera.positionWC,before)
    }),autoFollow.cameraBeforeEscape);
    assert.equal(released.trackedId,undefined);
    assert.equal(released.selectedTiles,0);
    assert.ok(released.cameraDelta<1,JSON.stringify(released));
    assert.equal(requests.filter(r => r.url.includes('/visualization/orbit.czml')).length,0);
    assert.equal(requests.filter(r => r.method==='POST' && r.url.endsWith('/replay')).length,1);
    // 首次打开自动申请一次；视图的播放、跳转均不得触发第二次构建。
    console.log('CESIUM_UI_OK '+JSON.stringify({result,endpoint,autoFollow,released,legacyOrbitRequests:0,errors,failedResponses}));
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
