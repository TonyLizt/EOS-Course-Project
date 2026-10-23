// Execute the real picker code with minimal DOM controls; not a browser E2E.
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('eos_system/web/app.js','utf8');
function picker(rows) {
  const nodes={};
  const labels={'scenario-scale':'全部规模','scenario-difficulty':'全部难度','scenario-satellites':'全部数量','scenario-tasks':'全部数量'};
  for(const id of [...Object.keys(labels),'scenario','submit','scenario-filter-count','form-message']) {
    let value='';
    nodes[id]={options:[{value:'',textContent:labels[id]||''}],textContent:'',disabled:false,listeners:{},
      addEventListener(event,fn){this.listeners[event]=fn;},
      get value(){return value;},set value(next){value=String(next);},
      set innerHTML(html){this.html=html;this.options=[...html.matchAll(/<option value="([^"]*)"[^>]*>(.*?)<\/option>/g)].map(m=>({value:m[1],textContent:m[2]}));value=this.options[0]?.value||'';}};
  }
  nodes['reset-scenario-filters']={listeners:{},addEventListener(event,fn){this.listeners[event]=fn;}};
  let hintCalls=0;
  const context={currentScenarios:rows,$:id=>nodes[id],updateScenarioHint(){hintCalls++;}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function escapeHtml'),source.indexOf('async function api'))+
    source.slice(source.indexOf('const scenarioFilterFields'),source.indexOf('function updateScenarioHint')),context);
  context.populateScenarioFilters();context.renderScenarioChoices();
  return {nodes,context,get hintCalls(){return hintCalls;}};
}
const rows=[{scenario_id:'small',name:'small',scale:'S1',difficulty_profile:'low_conflict',satellite_count:10,mission_count:10},
  {scenario_id:'large',name:'large',scale:'S8',difficulty_profile:'high_conflict',satellite_count:100,mission_count:200},
  {scenario_id:'unready',name:'unready',scale:'S8',difficulty_profile:'mixed',satellite_count:100,mission_count:200,availability:'invalid'}];
test('filters combine actual metadata and prevent submitting an unmatched or unavailable scene',()=>{
  const app=picker(rows),n=app.nodes;
  n['scenario-scale'].value='S8';n['scenario-scale'].listeners.change();
  assert.equal(n.scenario.value,'large');assert.equal(n.submit.disabled,false);
  n['scenario-difficulty'].value='low_conflict';n['scenario-difficulty'].listeners.change();
  assert.equal(n.scenario.value,'');assert.equal(n.submit.disabled,true);
  assert.match(n['form-message'].textContent,/没有符合条件/);
  n['scenario-difficulty'].value='mixed';n['scenario-difficulty'].listeners.change();
  assert.equal(n.submit.disabled,true);assert.match(n.scenario.html,/disabled/);
  n['reset-scenario-filters'].listeners.click();
  assert.equal(n.scenario.value,'small');assert.equal(n.submit.disabled,false);
  assert.equal(n['scenario-filter-count'].textContent,'显示 3 / 3 个场景');
});
test('refresh preserves a compatible selection and legacy rows remain selectable',()=>{
  const app=picker(rows),n=app.nodes;
  n.scenario.value='large';app.context.renderScenarioChoices();assert.equal(n.scenario.value,'large');
  app.context.currentScenarios=[{scenario_id:'old',name:'old & safe'}];
  app.context.populateScenarioFilters();app.context.renderScenarioChoices();
  assert.equal(n.scenario.value,'old');assert.equal(n['scenario-scale'].disabled,true);
  assert.match(n.scenario.html,/old &amp; safe/);assert.equal(n.submit.disabled,false);
});
