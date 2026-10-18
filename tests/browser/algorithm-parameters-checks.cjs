/* Run once in the isolated RABAS fixture, not one scheduling run per algorithm. */
const assert=require('node:assert/strict');
module.exports=async function checkParameters(page){
 await require('./workspace-navigation.cjs').step(page,2);
 const catalog=await page.evaluate(async()=> (await(await fetch('/api/algorithms')).json()).items);
 for(const a of catalog){
  const toggle=page.locator(`[data-toggle="algo-create-${a.algorithm_id}"]`),box=page.locator(`#algo-create-${a.algorithm_id}`);
  const check=page.locator(`[name="batch-algorithm"][value="${a.algorithm_id}"]`),selected=await check.isChecked();
  await toggle.click();assert.equal(await check.isChecked(),selected);
  assert.equal(await toggle.getAttribute('aria-expanded'),'true');
  assert.equal(await box.locator('.parameter-field').count(),Object.keys(a.parameters.properties).length);
  assert.ok(!(await box.innerText()).includes('additionalProperties'));
  assert.ok(!(await box.innerText()).includes('anyOf'));
  assert.deepEqual(await box.locator('.algorithm-parameters').evaluate(b=>b.parameterValues()),{});
  await toggle.click();assert.equal(await toggle.getAttribute('aria-expanded'),'false');
 }
 // MIP: nullable integer, omission, boolean, invalid field, advanced JSON.
 await page.locator('[data-toggle="algo-create-mip"]').click();
 const mip=page.locator('#algo-create-mip .algorithm-parameters');
 const count=mip.locator('[data-key="max_candidates_per_task"]'),verbose=mip.locator('[data-key="verbose"]');
 await count.locator('.parameter-mode').selectOption('null');
 await verbose.locator('.parameter-mode').selectOption('value');await verbose.locator('input').check();
 assert.deepEqual(await mip.evaluate(b=>b.parameterValues()),{max_candidates_per_task:null,verbose:true});
 await count.locator('.parameter-mode').selectOption('value');await count.locator('input').fill('0');
 const invalid=await mip.evaluate(b=>{try{b.parameterValues();return '';}catch(e){return e.message;}});
 assert.ok(invalid.includes('max_candidates_per_task'));assert.ok(await mip.locator('.parameter-error').isVisible());
 await count.locator('input').fill('12');
 await page.locator('[data-toggle="algo-create-mip"]').click();await page.locator('[data-toggle="algo-create-mip"]').click();
 assert.deepEqual(await mip.evaluate(b=>b.parameterValues()),{max_candidates_per_task:12,verbose:true});
 await mip.locator('summary').click();
 await mip.locator('textarea').fill('{"extra":1}');await mip.locator('.parameter-apply').click();
 assert.ok((await mip.locator('.parameter-error').innerText()).includes('extra'));
 await mip.locator('textarea').fill('{"verbose":false,"max_candidates_per_task":null}');await mip.locator('.parameter-apply').click();
 assert.deepEqual(await mip.evaluate(b=>b.parameterValues()),{max_candidates_per_task:null,verbose:false});
 await page.locator('[data-toggle="algo-create-mip"]').click();
 // Real DOM binding of schema shapes not present in today's registry.
 const generic=await page.evaluate(()=>{
  const a={algorithm_id:'test-only',parameters:{type:'object',additionalProperties:false,properties:{
   options:{type:'object',additionalProperties:false,properties:{name:{type:'string'},n:{type:'number'}}},
   union:{oneOf:[{type:'integer'},{type:'string'}]},
   choice:{type:'string',enum:['a','b'],default:'a'},
   fixed:{type:'string',const:'all'},items:{type:'array',items:{type:'integer'}},
  }}};
  const host=document.createElement('div');document.body.append(host);host.innerHTML=AlgorithmParameters.render(a);
  const box=host.firstElementChild;AlgorithmParameters.bind(box,a);
  const set=(key,value)=>{const f=box.querySelector(`[data-key="${key}"]`);f.querySelector('.parameter-mode').value='value';f.querySelector('.parameter-mode').dispatchEvent(new Event('change',{bubbles:true}));const input=f.querySelector('.parameter-value');if(input)input.value=value;};
  set('options');set('name','nested');set('n','1.25');set('union','2');set('choice','1');set('fixed','0');set('items','[1,2]');
  const first=box.parameterValues();const branch=box.querySelector('[data-key="union"] .parameter-branch');branch.value='1';branch.dispatchEvent(new Event('change',{bubbles:true}));box.querySelector('[data-key="union"] input').value='text';
  const second=box.parameterValues();host.remove();return {first,second};
 });
 assert.deepEqual(generic.first,{options:{name:'nested',n:1.25},union:2,choice:'b',fixed:'all',items:[1,2]});
 assert.equal(generic.second.union,'text');
 // Empty params: no pointless editor; unavailable model remains unavailable.
 assert.equal(await page.locator('#algo-create-ppo textarea').count(),0);
 assert.equal(await page.locator('[name="batch-algorithm"][value="ppo"]').isDisabled(),true);
 console.log('ALGORITHM_PARAMETERS_BROWSER_PASS '+catalog.length+' algorithms; null/omit/boolean/number/enum/object/union/array/advanced');
};
