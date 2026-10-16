// 连接 serve_bundled_fixture.py 的真实 50 星结果，不使用合成轨道。
const fs=require('node:fs');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
  const coord=process.env.EOS_BROWSER_QA_COORD;
  if(!coord) throw new Error('请提供 EOS_BROWSER_QA_COORD');
  const info=JSON.parse(fs.readFileSync(coord,'utf8'));
  let browser;
  try {
    browser=await chromium.launch({
      headless:true,
      ...(process.env.EOS_BROWSER_EXECUTABLE ? {executablePath:process.env.EOS_BROWSER_EXECUTABLE} : {}),
      ...(process.env.EOS_BROWSER_PROXY ? {proxy:{server:process.env.EOS_BROWSER_PROXY,bypass:'127.0.0.1,localhost'}} : {}),
      args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']
    });
    const context=await browser.newContext({viewport:{width:1600,height:1000},timezoneId:'Asia/Shanghai'});
    const errors=[],failedResponses=[],posts=[];
    context.on('page',p=>{
      p.on('pageerror',e=>errors.push(String(e)));
      p.on('console',m=>{if(m.type()==='error') errors.push(m.text()+' '+JSON.stringify(m.location()));});
      p.on('response',r=>{if(r.status()>=400) failedResponses.push({url:r.url(),status:r.status()});});
      p.on('request',r=>{if(r.method()==='POST') posts.push(r.url());});
    });
    const page=await context.newPage();
    await page.goto(info.url);
    await page.waitForFunction(()=>document.querySelector('#health').textContent.includes('服务已连接'));
    await page.selectOption('#source','bundled-small');
    await page.waitForFunction(()=>document.querySelector('#scenario').options.length===4);
    const smallCount=await page.locator('#scenario option').count();
    await page.selectOption('#source',info.source_id);
    await page.waitForFunction(()=>document.querySelector('#scenario').options.length===2);
    await page.selectOption('#scenario',info.scenario_id);
    const hint=await page.locator('#scenario-hint').innerText();
    assert.ok(hint.includes('50 颗卫星')&&hint.includes('135 秒')&&hint.includes('legacy_unknown'),hint);
    await page.locator('tr[data-id="'+info.run_id+'"]').click();
    await page.waitForFunction(()=>document.querySelector('#replay-status').textContent.includes('135 秒'));
    const view=await context.newPage();
    const started=Date.now();
    await view.goto(info.url+await page.locator('#open-cesium').getAttribute('href'),{waitUntil:'domcontentloaded',timeout:90000});
    await view.waitForFunction(()=>document.querySelector('#assetStatus').textContent.includes('50 body model'),null,{timeout:120000});
    await view.locator('.assignment-row').first().click();
    await view.waitForTimeout(3000);
    const result=await view.evaluate(()=>{
      const assignment=viewer._scenarioAssignments[0],ds=viewer.dataSources.get(0);
      const now=viewer.clock.currentTime,body=ds.entities.getById(assignment.satellite_id);
      return {time:Cesium.JulianDate.toIso8601(now),expected:Cesium.JulianDate.toIso8601(assignment.start),
        satelliteCount:viewer._satelliteEntities.length,hasBodyPosition:!!body.position.getValue(now),
        hasBodyOrientation:!!body.orientation.getValue(now),shouldAnimate:viewer.clock.shouldAnimate,
        secondaryShouldAnimate:viewer._payloadViewer.clock.shouldAnimate,
        secondaryTime:Cesium.JulianDate.toIso8601(viewer._payloadViewer.clock.currentTime),
        payload:document.querySelector('#payloadViewStatus').textContent,
        models:document.querySelector('#assetStatus').textContent,
        sampling:document.querySelector('#replayBuildStatus').textContent,
        sceneFrame:viewer.scene.frameState?.frameNumber ?? viewer.scene._frameState?.frameNumber};
    });
    assert.equal(result.time,result.expected);
    assert.equal(result.secondaryTime,result.time);
    assert.equal(result.satelliteCount,50);
    assert.equal(result.hasBodyPosition,true);
    assert.equal(result.hasBodyOrientation,true);
    assert.equal(result.shouldAnimate,false);
    assert.equal(result.secondaryShouldAnimate,false);
    assert.ok(result.payload.includes('OBSERVING'),JSON.stringify(result));
    assert.ok(result.sampling.includes('135 秒'),result.sampling);
    assert.equal(posts.length,0,'只打开 READY 结果不得触发额外 POST');
    assert.equal(errors.length,0,JSON.stringify({errors,failedResponses}));
    assert.equal(failedResponses.length,0,JSON.stringify(failedResponses));
    console.log('REAL_50_SATELLITE_BROWSER_PASS '+JSON.stringify({
      smallOptions:smallCount,mediumOptions:2,scenario:info.scenario_id,
      sceneHint:hint,viewerElapsedMs:Date.now()-started,result,errors,failedResponses,posts
    }));
  } finally {
    if(browser) await browser.close();
    if(fs.existsSync(coord)) fs.writeFileSync(coord,JSON.stringify({...info,stop:true}));
  }
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
