(() => {
  'use strict';
  let offset = 0;
  const $ = id => document.getElementById(id);
  async function load() {
    $('older').disabled = $('newer').disabled = true;
    try {
      const response = await fetch(`/api/runs?limit=30&offset=${offset}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message || '读取失败');
      $('gantt-runs').replaceChildren();
      for (const run of data.items) {
        const li = document.createElement('li');
        const text = `${run.scenario_id} · ${run.algorithm_id} · ${run.schedule_model} · ${run.status} · ${run.result_kind === 'planning_preview' ? '未认证规划预览' : '正式模式'} · ${run.run_id}`;
        if (run.status === 'SUCCEEDED' && run.has_plan) {
          const link = document.createElement('a');
          link.href = '/visualization/gantt/' + encodeURIComponent(run.run_id);
          link.textContent = text; li.append(link);
        } else { li.textContent = text + '（尚无可查看计划）'; }
        $('gantt-runs').append(li);
      }
      $('run-message').textContent = `共 ${data.total} 次运行；显示 ${data.items.length} 条。`;
      $('older').disabled = offset + 30 >= data.total;
      $('newer').disabled = offset === 0;
    } catch (error) { $('run-message').textContent = error.message; }
  }
  $('older').addEventListener('click', () => { offset += 30; load(); });
  $('newer').addEventListener('click', () => { offset = Math.max(0, offset - 30); load(); });
  load();
})();
