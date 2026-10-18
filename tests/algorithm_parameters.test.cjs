const {test}=require('node:test'),assert=require('node:assert/strict');
const P=require('../eos_system/web/algorithm-parameters.js');
const UI=require('../eos_system/web/experiment-ui.js');
const schema={type:'object',additionalProperties:false,properties:{
 count:{anyOf:[{type:'integer',minimum:1,maximum:5},{type:'null'}],default:null},
 rate:{type:'number',exclusiveMinimum:0,maximum:1,default:.5},
 enabled:{type:'boolean',default:false},mode:{type:'string',enum:['a','b'],default:'a'},
 nested:{$ref:'#/$defs/options'},choice:{oneOf:[{type:'integer'},{type:'string'}]},
 values:{type:'array',items:{type:'number'},minItems:1},
},$defs:{options:{type:'object',additionalProperties:false,required:['name'],properties:{name:{type:'string',minLength:1}}}}};
test('types, null, omission and nested values remain distinct',()=>{
 assert.deepEqual(P.validate(schema,{}),[]);
 assert.deepEqual(P.validate(schema,{count:null,rate:.3,enabled:false,mode:'b',nested:{name:'ok'},choice:2,values:[1,2]}),[]);
 for(const value of [{count:'2'},{count:1.5},{count:0},{count:6},{rate:0},{rate:Infinity},{enabled:'false'},{mode:'c'},{nested:{}},{nested:{name:'',extra:1}},{choice:true},{values:[]},{values:['1']},{extra:2}])assert.ok(P.validate(schema,value).length,JSON.stringify(value));
});
test('form contains typed controls and modes, not raw Schema',()=>{
 const html=P.render({algorithm_id:'fixture',parameters:schema});
 for(const word of ['type="number"','type="checkbox"','parameter-branch','parameter-nested','显式空值 null','不提交字段','高级：编辑参数 JSON'])assert.ok(html.includes(word),word);
 for(const word of ['additionalProperties','anyOf','oneOf','"$defs"'])assert.ok(!html.includes(word),word);
 assert.ok(P.render({algorithm_id:'empty',parameters:{type:'object',properties:{}}}).includes('无额外可配置参数'));
 assert.ok(!P.render({algorithm_id:'empty',parameters:{type:'object',properties:{}}}).includes('<textarea'));
});
test('defaultless required field does not invent a value',()=>{
 const s={type:'object',required:['n'],properties:{n:{type:'integer'}}};
 assert.ok(P.render({parameters:s}).includes('未设置（必填）'));
 assert.ok(P.validate(s,{}).length);
});
test('typed maps and nullable type arrays validate without dropping nested fields',()=>{
 const s={type:'object',properties:{map:{type:'object',additionalProperties:{type:'integer'}},maybe:{type:['string','null']}}};
 assert.deepEqual(P.validate(s,{map:{a:1},maybe:null}),[]);
 assert.ok(P.validate(s,{map:{a:'1'}}).length);
 assert.ok(P.validate(s,{maybe:false}).length);
 assert.ok(P.render({parameters:s}).includes('parameter-json'));
 assert.equal(P.shape(s.properties.maybe,s).nullable,true);
});
test('description deduplicates repeated strategy and keeps limitations plus dependency',()=>{
 const html=UI.description({description:'same',strategy:'same',objectives:'goal',limitations:'limit',availability_message:'dependency'});
 assert.equal(html.split('same').length-1,1);assert.ok(html.includes('limit'));assert.ok(html.includes('dependency'));
 assert.ok(!UI.description({description:'<script>'}).includes('<script>'));
});
test('readonly preserves explicitly recorded null and false and is not an editor',()=>{
 const html=P.render({parameters:schema},{count:null,enabled:false},true);
 assert.ok(html.includes('value="null" selected'));assert.ok(html.includes('data-readonly="true"'));
 assert.ok(!html.includes('parameter-raw'));
});
