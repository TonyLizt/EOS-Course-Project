/* 课程展示层只读取现有 Run 数据；不请求接口、不探测进程，也不改变任何运行状态。 */
(function(root,factory){
  'use strict';
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.OsCourseView=api;
})(typeof window==='undefined'?globalThis:window,()=>{
  'use strict';
  const states={QUEUED:'等待派发',STARTING:'启动进程',RUNNING:'算法求解',VERIFYING:'独立核验',
    SUCCEEDED:'已完成',FAILED:'失败',TIMED_OUT:'超时',CANCELLED:'已取消',CANCELLING:'取消处理中'};
  function seconds(value){return typeof value==='number'&&Number.isFinite(value)&&value>=0?value.toFixed(3)+' s':'—';}
  function describe(run){
    if(!run)return null;
    // attempts 数组可能是历史记录；按真实 attempt_no 选最近项，不把历史 PID 当存活证据。
    const attempts=Array.isArray(run.attempts)?run.attempts.filter(a=>a&&Number.isInteger(a.attempt_no)):[];
    const attempt=attempts.reduce((last,a)=>!last||a.attempt_no>last.attempt_no?a:last,null);
    return {
      pid:Number.isInteger(attempt?.worker_pid)&&attempt.worker_pid>0?String(attempt.worker_pid):'尚未记录',
      attempt:attempt?String(attempt.attempt_no):'尚未开始',
      state:states[run.status]||String(run.status||'未知'),
      exitCode:Number.isInteger(attempt?.exit_code)?String(attempt.exit_code):'尚未记录',
      algorithmTime:seconds(attempt?.algorithm_runtime_s),
      verificationTime:seconds(attempt?.verification_runtime_s),
      note:run.cancel_requested?'后端已记录取消请求；以最终运行状态为准。':'PID 来自最近一次尝试；终态中的 PID 是历史值，不代表进程仍存活。',
    };
  }
  function render(container,run){
    if(!container)return;
    const info=describe(run);
    container.hidden=!info;
    // 只用 textContent 写入后端值，避免实验或状态字符串被解释成 HTML。
    for(const node of container.querySelectorAll('[data-os-process-field]'))node.textContent=info?.[node.dataset.osProcessField]||'—';
  }
  return {describe,render};
});
