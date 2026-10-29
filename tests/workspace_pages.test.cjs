// 导航回归：验证真实路由脚本保持已有节点，且浏览器回退不会新增历史记录。
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('eos_system/web/workspace-pages.js','utf8');
function setup(hash) {
  const node = key => ({dataset:{consolePage:key,consoleRoute:key},hidden:false,attrs:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},focus(){}});
  const pages = ['create','records','compare','course'].map(node), links = ['create','records','compare','course'].map(node);
  const title = node(), description = node(), events = {}, clicks = {}, pushes = [];
  const location = {hash}, window = {addEventListener:(key,fn)=>events[key]=fn};
  const document = {querySelectorAll:selector=>selector==='[data-console-page]'?pages:links,getElementById:id=>id==='workspace-page-title'?title:description,addEventListener:(key,fn)=>clicks[key]=fn};
  const history = {pushState:(_a,_b,next)=>{pushes.push(next);location.hash=next;}};
  vm.runInNewContext(source,{document,window,location,history});
  return {pages,links,title,location,events,pushes,show:window.ConsoleWorkspace.showPage};
}
test('legacy links open their intended workspace',()=>{
  for(const [hash,page] of [['#runs-heading','records'],['#detail-heading','records'],['#comparison-heading','compare'],['#create-heading','create'],['#unknown','create']]) {
    const app=setup(hash);
    assert.equal(app.pages.find(node=>!node.hidden).dataset.consolePage,page);
    assert.equal(app.pushes.length,0);
  }
});
test('switching and browser history preserve existing page nodes and entered values',()=>{
  const app=setup('#new-experiment'), original=app.pages[0];
  original.input={value:'73'};
  app.show('records'); app.show('compare');
  assert.equal(app.links[2].attrs['aria-current'],'page');
  app.location.hash='#new-experiment'; app.events.popstate();
  assert.equal(app.pages[0],original);
  assert.equal(original.input.value,'73');
  assert.equal(original.hidden,false);
  assert.equal(app.pushes.length,2);
  app.location.hash='#runs-heading'; app.events.hashchange();
  assert.equal(app.pages[1].hidden,false);
  assert.equal(app.pushes.length,2);
});

test('course landing and direct course link coexist with all existing workspaces',()=>{
  for(const hash of ['', '#course-overview']){
    const app=setup(hash);
    assert.equal(app.pages.find(node=>!node.hidden).dataset.consolePage,'course');
    assert.equal(app.pushes.length,0);
    app.show('create');app.pages[0].input={value:'42'};
    app.show('course');app.show('records');app.show('create');
    assert.equal(app.pages[0].input.value,'42');
    assert.equal(app.pages.filter(node=>!node.hidden).length,1);
  }
});
