/* Schema-driven parameter UI. Omitted keys, null and explicit values stay distinct. */
(function(root){
 'use strict';
 const E=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
 const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
 function resolve(s,rootSchema){
  if(s.$ref){if(!s.$ref.startsWith('#/'))throw Error('不支持外部参数引用');
   const target=s.$ref.slice(2).split('/').reduce((o,k)=>o?.[k.replace(/~1/g,'/').replace(/~0/g,'~')],rootSchema);
   if(!target)throw Error('参数引用不存在');return {...target,...Object.fromEntries(Object.entries(s).filter(([k])=>k!=='$ref'))};}
  return s;
 }
 function shape(raw,rootSchema){
  const s=resolve(raw,rootSchema),variants=s.anyOf||s.oneOf||(Array.isArray(s.type)?s.type.map(type=>({...s,type})):[s]);
  const choices=variants.map(v=>resolve(v,rootSchema)).filter(v=>v.type!=='null');
  return {s,choices,nullable:variants.some(v=>v.type==='null')||s.type==='null'};
 }
 function validate(raw,value,rootSchema=raw,path='参数'){
  const s=resolve(raw,rootSchema),errors=[];
  const fail=message=>errors.push(`${path}：${message}`);
  if(Array.isArray(s.type))return validate({...s,type:undefined,anyOf:s.type.map(type=>({...s,type}))},value,rootSchema,path);
  if(s.anyOf||s.oneOf){
   const matches=(s.anyOf||s.oneOf).filter(v=>!validate(v,value,rootSchema,path).length).length;
   if(!matches||(s.oneOf&&matches!==1))fail('类型或取值不符合允许的选项');return errors;
  }
  if(s.const!==undefined&&!equal(value,s.const))fail('必须为 '+JSON.stringify(s.const));
  if(s.enum&&!s.enum.some(v=>equal(v,value)))fail('请选择允许的值');
  const t=s.type;
  if(t==='null'){if(value!==null)fail('必须为空值');return errors;}
  if(t==='object'){
   if(!object(value)){fail('必须是对象');return errors;}
   for(const k of s.required||[])if(!own(value,k))errors.push(`${path}.${k}：必填`);
   for(const [k,v] of Object.entries(value)){
    if(own(s.properties||{},k))errors.push(...validate(s.properties[k],v,rootSchema,`${path}.${k}`));
    else if(s.additionalProperties===false)errors.push(`${path}.${k}：不允许额外字段`);
    else if(object(s.additionalProperties))errors.push(...validate(s.additionalProperties,v,rootSchema,`${path}.${k}`));
   }
  }else if(t==='array'){
   if(!Array.isArray(value)){fail('必须是数组');return errors;}
   if(s.minItems!==undefined&&value.length<s.minItems)fail(`至少 ${s.minItems} 项`);
   if(s.maxItems!==undefined&&value.length>s.maxItems)fail(`最多 ${s.maxItems} 项`);
   if(s.items)value.forEach((v,i)=>errors.push(...validate(s.items,v,rootSchema,`${path}[${i}]`)));
  }else if(t==='integer'||t==='number'){
   if(typeof value!=='number'||!Number.isFinite(value)||(t==='integer'&&!Number.isSafeInteger(value))){fail(t==='integer'?'请输入安全整数':'请输入有限数值');return errors;}
   for(const [key,ok,label] of [['minimum',v=>value>=v,'不小于'],['maximum',v=>value<=v,'不大于'],['exclusiveMinimum',v=>value>v,'大于'],['exclusiveMaximum',v=>value<v,'小于']])
    if(s[key]!==undefined&&!ok(s[key]))fail(`${label} ${s[key]}`);
  }else if(t==='boolean'&&typeof value!=='boolean')fail('必须是布尔值');
  else if(t==='string'){
   if(typeof value!=='string'){fail('必须是文本');return errors;}
   if(s.minLength!==undefined&&value.length<s.minLength)fail(`至少 ${s.minLength} 个字符`);
   if(s.maxLength!==undefined&&value.length>s.maxLength)fail(`最多 ${s.maxLength} 个字符`);
   if(s.pattern&&!new RegExp(s.pattern).test(value))fail('文本格式不符合要求');
  }
  return errors;
 }
 function hints(raw,rootSchema){
  const {s,choices}=shape(raw,rootSchema),v=choices[0]||s;
  const type=v.enum||own(v,'const')?'选项':({integer:'整数',number:'数值',boolean:'开关',string:'文本',object:'分组',array:'数组'}[v.type]||'高级配置');
  const range=[['minimum','≥'],['exclusiveMinimum','>'],['maximum','≤'],['exclusiveMaximum','<']].filter(([k])=>v[k]!==undefined).map(([k,label])=>label+' '+v[k]);
  const def=own(s,'default')?(s.default===null?'默认：null（未设置时省略字段）':'默认：'+JSON.stringify(s.default)):'未指定默认值';
  return [type,...range,def].join(' · ');
 }
 function fields(s,values,rootSchema,readonly){
  return Object.entries(s.properties||{}).map(([key,raw])=>{
   const {s:field,choices,nullable}=shape(raw,rootSchema),present=own(values,key),value=present?values[key]:field.default;
   const required=(s.required||[]).includes(key),mode=present?(value===null?'null':'value'):'omit';
   const branch=Math.max(0,choices.findIndex(c=>!validate(c,value,rootSchema).length));
   return `<div class="parameter-field" data-key="${E(key)}"><div class="parameter-label"><strong>${E(field.title||key)}</strong><code>${E(key)}</code></div>
    ${field.description?`<p class="parameter-help">${E(field.description)}</p>`:''}<p class="parameter-help">${E(hints(raw,rootSchema))}</p>
    <label class="parameter-mode-label">取值方式<select class="parameter-mode" ${readonly?'disabled':''} aria-label="${E(key)} 取值方式"><option value="omit" ${mode==='omit'?'selected':''}>${required?'未设置（必填）':readonly?'未显式设置（使用默认配置）':'使用默认配置（不提交字段）'}</option>${nullable?`<option value="null" ${mode==='null'?'selected':''}>显式空值 null</option>`:''}<option value="value" ${mode==='value'?'selected':''}>${readonly?'已记录值':'自定义值'}</option></select></label>
    <div class="parameter-value-area" ${mode!=='value'?'hidden':''}>${choices.length>1?`<label>值类型<select class="parameter-branch" ${readonly?'disabled':''}>${choices.map((c,i)=>`<option value="${i}" ${i===branch?'selected':''}>${E(c.title||c.type||'选项 '+(i+1))}</option>`).join('')}</select></label>`:''}<div class="parameter-control">${control(choices[branch]||{type:'null'},value,rootSchema,readonly,key)}</div></div></div>`;
  }).join('');
 }
 function control(s,value,rootSchema,readonly,key){
  const disabled=readonly?'disabled':'',label=`aria-label="${E(key)}"`;
  const options=s.enum||(own(s,'const')?[s.const]:null);
  if(options)return `<select class="parameter-value" ${label} ${disabled}>${options.map((v,i)=>`<option value="${i}" ${equal(v,value)?'selected':''}>${E(typeof v==='string'?v:JSON.stringify(v))}</option>`).join('')}</select>`;
  if(s.type==='object'&&s.properties&&s.additionalProperties===false)return `<div class="parameter-nested">${fields(s,object(value)?value:{},rootSchema,readonly)}</div>`;
  if(s.type==='boolean')return `<label class="parameter-boolean"><input class="parameter-value" type="checkbox" ${label} ${value===true?'checked':''} ${disabled}>启用</label>`;
  if(['integer','number'].includes(s.type))return `<input class="parameter-value" type="number" ${label} step="${s.type==='integer'?'1':'any'}" ${s.minimum!==undefined?'min="'+E(s.minimum)+'"':''} ${s.maximum!==undefined?'max="'+E(s.maximum)+'"':''} value="${E(value??'')}" ${disabled}>`;
  if(s.type==='string')return `<input class="parameter-value" type="text" ${label} value="${E(value??'')}" ${disabled}>`;
  if(s.type==='null')return '<span>空值 null</span>';
  return `<label>结构化值 JSON<textarea class="parameter-value parameter-json" ${label} rows="3" ${disabled}>${E(JSON.stringify(value??(s.type==='array'?[]:{}),null,2))}</textarea></label>`;
 }
 function render(a,values={},readonly=false){
  const schema=a.parameters||{type:'object',properties:{},additionalProperties:false};
  const content=fields(schema,values,schema,readonly),unknown=Object.keys(values).filter(k=>!own(schema.properties||{},k));
  return `<div class="algorithm-parameters" data-algorithm="${E(a.algorithm_id)}" ${readonly?'data-readonly="true"':''}><h4>${readonly?'本次运行参数':'参数配置'}</h4>${content?`<div class="parameter-fields">${content}</div>`:'<p class="parameter-help">无额外可配置参数。</p>'}${unknown.length?`<p class="parameter-help">历史参数（仅展示）</p><pre>${E(JSON.stringify(Object.fromEntries(unknown.map(k=>[k,values[k]])),null,2))}</pre>`:''}${!readonly&&content?'<details class="parameter-advanced"><summary>高级：编辑参数 JSON</summary><p class="parameter-help">仅编辑参数值，不是 Schema。修改后请点击应用；后端仍会进行最终校验。</p><textarea class="parameter-raw" rows="5" aria-label="高级参数 JSON"></textarea><button type="button" class="parameter-apply">应用 JSON</button></details>':''}<p class="parameter-error" role="alert" hidden></p></div>`;
 }
 function readFields(box,s,rootSchema){
  const result={};
  for(const field of [...box.children].filter(n=>n.classList.contains('parameter-field'))){
   const key=field.dataset.key,mode=field.querySelector('.parameter-mode').value;
   if(mode==='omit')continue;if(mode==='null'){result[key]=null;continue;}
   const {choices}=shape(s.properties[key],rootSchema),branch=field.querySelector(':scope > .parameter-value-area > label > .parameter-branch');
   const v=choices[branch?Number(branch.value):0]||{type:'null'},c=field.querySelector('.parameter-control'),input=c.querySelector('.parameter-value');
   if(v.enum||own(v,'const'))result[key]=(v.enum||[v.const])[Number(input.value)];
   else if(v.type==='object'&&v.properties&&v.additionalProperties===false)result[key]=readFields(c.querySelector('.parameter-nested'),v,rootSchema);
   else if(v.type==='boolean')result[key]=input.checked;
   else if(v.type==='number'||v.type==='integer'){if(!input.value.trim())throw Error(`${key}：请输入数值`);result[key]=Number(input.value);}
   else if(v.type==='string')result[key]=input.value;
   else if(v.type==='null')result[key]=null;
   else{try{result[key]=JSON.parse(input.value);}catch{throw Error(`${key}：JSON 格式无效`);}}
  }
  return result;
 }
 function bind(box,a,initial={}){
  const s=a.parameters||{type:'object',properties:{},additionalProperties:false};
  const error=message=>{const p=box.querySelector('.parameter-error');p.textContent=message;p.hidden=!message;};
  const raw=()=>box.querySelector('.parameter-raw');let rawBaseline='';
  function get(){
   try{
    if(raw()&&raw().value!==rawBaseline)throw Error('高级 JSON 尚未应用，请先点击“应用 JSON”');
    const value=readFields(box.querySelector('.parameter-fields')||box,s,s),errors=validate(s,value);
    if(errors.length)throw Error(errors.join('；'));error('');return value;
   }catch(e){error(e.message);const content=box.closest('.algorithm-content');if(content?.hidden){content.hidden=false;document.querySelector(`[aria-controls="${CSS.escape(content.id)}"]`)?.setAttribute('aria-expanded','true');}throw Error(`${a.name||a.algorithm_id}：${e.message}`);}
  }
  box.addEventListener('change',event=>{
   const field=event.target.closest('.parameter-field');if(!field)return;
   if(event.target.matches('.parameter-mode'))field.querySelector('.parameter-value-area').hidden=event.target.value!=='value';
   if(event.target.matches('.parameter-branch')){
    const parent=field.parentElement,findSchema=(container,schema)=>{
     if(container===parent)return schema;
     for(const f of container.children){if(!f.dataset.key)continue;const nested=f.querySelector('.parameter-nested');if(nested?.contains(parent)){
      const options=shape(schema.properties[f.dataset.key],s).choices,b=f.querySelector(':scope > .parameter-value-area > label > .parameter-branch');return findSchema(nested,options[b?Number(b.value):0]);}}
    };
    const owner=findSchema(box.querySelector('.parameter-fields'),s),v=shape(owner.properties[field.dataset.key],s).choices[Number(event.target.value)];
    field.querySelector('.parameter-control').innerHTML=control(v,v.default,s,false,field.dataset.key);
   }
   error('');
  });
  box.querySelector('.parameter-advanced')?.addEventListener('toggle',event=>{
   if(!event.target.open)return;
   if(raw().value!==rawBaseline)return;
   try{raw().value=rawBaseline=JSON.stringify(get(),null,2);}catch{/* Inline error; keep editable JSON. */}
  });
  box.querySelector('.parameter-apply')?.addEventListener('click',()=>{
   try{const value=JSON.parse(raw().value),errors=validate(s,value);if(errors.length)throw Error(errors.join('；'));
    box.querySelector('.parameter-fields').innerHTML=fields(s,value,s,false);raw().value=rawBaseline=JSON.stringify(value,null,2);error('');
   }catch(e){error(e.message);}
  });
  if(raw())raw().value=rawBaseline=JSON.stringify(initial,null,2);
  box.parameterValues=get;return get;
 }
 const api={validate,resolve,shape,hints,render,bind};
 if(typeof module==='object'&&module.exports)module.exports=api;else root.AlgorithmParameters=api;
})(typeof window==='undefined'?globalThis:window);
