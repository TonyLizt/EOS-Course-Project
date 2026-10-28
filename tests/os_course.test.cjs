// 展示字段来自既有Run尝试记录；缺失字段与历史PID不得伪装成实时监控。
const {test}=require('node:test'),assert=require('node:assert/strict');
const View=require('../eos_system/web/os-course.js');
test('missing historical fields remain unknown, while zero timings and exit code remain visible',()=>{
  const info=View.describe({status:'SUCCEEDED',attempts:[{attempt_no:1,worker_pid:123,exit_code:0,algorithm_runtime_s:0,verification_runtime_s:.125}]});
  assert.equal(info.pid,'123');assert.equal(info.exitCode,'0');assert.equal(info.algorithmTime,'0.000 s');
  assert.equal(info.verificationTime,'0.125 s');assert.ok(info.note.includes('历史值'));
  assert.equal(View.describe({status:'QUEUED',attempts:[]}).pid,'尚未记录');
  assert.equal(View.describe({status:'QUEUED',attempts:[]}).attempt,'尚未开始');
});
test('latest numbered attempt wins even if API array order changes',()=>{
  const info=View.describe({status:'RUNNING',cancel_requested:true,attempts:[{attempt_no:2,worker_pid:222},{attempt_no:1,worker_pid:111}]});
  assert.equal(info.pid,'222');assert.equal(info.state,'算法求解');assert.ok(info.note.includes('取消请求'));
  assert.equal(View.describe({status:'VERIFYING',attempts:[{attempt_no:1,worker_pid:-1,algorithm_runtime_s:NaN}]}).algorithmTime,'—');
});
test('clear detail hides the card and render writes only textContent',()=>{
  const nodes=['pid','state','note'].map(key=>({dataset:{osProcessField:key},textContent:''}));
  const root={hidden:false,querySelectorAll:()=>nodes};
  View.render(root,{status:'<script>malicious</script>',attempts:[]});
  assert.equal(nodes[1].textContent,'<script>malicious</script>');
  View.render(root,null);assert.equal(root.hidden,true);assert.ok(nodes.every(n=>n.textContent==='—'));
});
