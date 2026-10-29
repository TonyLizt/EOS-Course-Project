/* 所有进程身份由服务端保存；浏览器只发送固定动作，不传PID、命令或路径。 */
(()=>{'use strict';
const $=id=>document.getElementById(id),buttons=[...document.querySelectorAll('[data-action]')];
const states={IDLE:'未启动',STARTING:'正在启动',HEALTHY:'健康',RECOVERING:'故障恢复中',BACKOFF:'退避等待',STOPPING:'正在停止',STOPPED:'已停止',EXHAUSTED:'恢复次数耗尽',ERROR:'启动或恢复失败',BLOCKED:'恢复受阻'};
const names={DAEMON_STARTED:'Daemon 已启动',CONTROLLER_STARTED:'新 Controller 启动',CONTROLLER_HEALTHY:'Controller 健康',RECOVERY_ATTEMPT:'安排恢复与退避',RESTART_LIMIT_REACHED:'达到恢复上限',DAEMON_STOPPED:'Daemon 已停止',CONTROLLER_ORDERLY_STOP:'Controller 正常停止',CONTROLLER_SHUTDOWN_INTENT:'收到正常关闭意图'};
let busy=false,snapshot={};
function element(tag,text){const el=document.createElement(tag);el.textContent=text;return el;}
function render(data){snapshot=data;$('state').textContent=states[data.state]||data.state;
for(const name of ['daemon','controller','worker'])$(name).textContent=data[name+'_pid']?(data.active?'PID ':'历史 PID ')+data[name+'_pid']:'—';
$('alive').textContent=data.daemon_alive?'Daemon 身份确认存活':data.active?'等待或已退出':'当前无活动演示进程';
$('restarts').textContent=(data.restarts||0)+' / 3';
for(const button of buttons){const a=button.dataset.action;button.disabled=busy||(a==='start'?data.active:a==='stop'?!data.active:!data.daemon_alive||data.state!=='HEALTHY'||(a==='worker'&&!data.worker_pid));}
const runs=$('runs');runs.replaceChildren();for(const run of data.runs||[]){const div=element('div','');div.className='run';div.append(element('strong',run.name),element('span',run.status));const last=run.attempts.at(-1);div.append(element('small',`${run.error?.code||'尚无故障'} · 尝试 ${last?.attempt_no||0} · Worker PID ${last?.worker_pid||'—'}`));runs.append(div);}
if(!data.runs?.length)runs.textContent='尚未创建演示作业';
const events=$('events');events.replaceChildren();for(const item of [...(data.events||[])].reverse()){const li=element('li',names[item.event]||(item.event.startsWith('CONTROLLER_EXIT:')?'Controller 异常退出（'+item.event.split(':')[1]+'）':item.event));li.prepend(element('time',item.time));if(item.pid)li.append(element('small',' · PID '+item.pid));if(item.delay_s)li.append(element('small',` · 等待 ${item.delay_s} 秒`));events.append(li);}if(!data.events?.length)events.append(element('li','等待真实事件'));}
async function refresh(){if(busy)return;try{const response=await fetch('/api/daemon-demo',{cache:'no-store'});if(!response.ok)throw Error('状态读取失败');render(await response.json());}catch(error){$('message').textContent='主平台连接中断，暂不能确认演示状态；恢复连接后继续读取。';$('message').className='error';buttons.forEach(b=>b.disabled=true);}}
for(const button of buttons)button.addEventListener('click',async()=>{busy=true;render(snapshot);$('message').className='';$('message').textContent='正在执行，请稍候…';try{const response=await fetch('/api/daemon-demo/'+button.dataset.action,{method:'POST',headers:{'X-EOS-Demo':'1'}});const data=await response.json();if(!response.ok)throw Error(data.error?.message||data.detail||'操作失败');render(data);$('message').textContent=button.dataset.action==='stop'?'已正常停止并清理临时目录。':'操作已执行，请观察真实状态和事件变化。';}catch(error){$('message').textContent=error.message;$('message').className='error';}finally{busy=false;render(snapshot);}});
refresh();setInterval(refresh,800);
})();
