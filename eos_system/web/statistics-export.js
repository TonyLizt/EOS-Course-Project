/* 持久实验统计下载：跨页保留选择，下载Blob后及时释放，不在浏览器累积临时文件。 */
(() => {
  'use strict';
  const selected = new Set();
  let current = null, page = [], busy = false;
  function update() {
    document.querySelectorAll('[data-stat-export]').forEach(button => {
      button.disabled = busy || (button.dataset.exportScope === 'selected' ? selected.size === 0 : !current);
    });
    const count = document.getElementById('export-selection-count');
    if (count) count.textContent = `已选 ${selected.size} 个实验`;
    const all = document.getElementById('select-export-page');
    if (all) {
      all.checked = page.length > 0 && page.every(id => selected.has(id));
      all.indeterminate = page.some(id => selected.has(id)) && !all.checked;
    }
    document.querySelectorAll('[data-select-experiment]').forEach(input => { input.checked = selected.has(input.dataset.selectExperiment); });
  }
  document.addEventListener('change', event => {
    const input = event.target;
    if (input.matches('[data-select-experiment]')) {
      if (input.checked) selected.add(input.dataset.selectExperiment); else selected.delete(input.dataset.selectExperiment);
      update();
    } else if (input.id === 'select-export-page') {
      for (const id of page) { if (input.checked) selected.add(id); else selected.delete(id); }
      update();
    }
  });
  document.addEventListener('click', async event => {
    if (event.target.closest('#clear-export-selection')) { selected.clear(); update(); return; }
    const button = event.target.closest('[data-stat-export]');
    if (!button || busy) return;
    const ids = button.dataset.exportScope === 'selected' ? [...selected] : [current].filter(Boolean);
    if (!ids.length) return;
    const message = text => document.querySelectorAll('[data-export-message]').forEach(node => { node.textContent = text; });
    busy = true; update(); message('正在整理统计快照…');
    try {
      const response = await fetch('/api/statistics/export', {method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({experiment_ids:ids,format:button.dataset.exportFormat,
          include_removed:!!document.getElementById('export-include-removed')?.checked})});
      if (!response.ok) {
        const data = await response.json(); throw Error(data.error?.message || '统计导出失败');
      }
      const blob = await response.blob(), url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] || 'eos-statistics.'+button.dataset.exportFormat;
      document.body.append(link); link.click(); link.remove();
      // 留出浏览器开始下载的时间，再释放对象URL，避免连续导出泄漏内存。
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      message(`已下载 ${ids.length} 个实验的统计快照；CSV 每行一次算法运行，ZIP 另含分组统计与任务明细。`);
    } catch (error) { message(error.message); }
    finally { busy = false; update(); }
  });
  window.ExperimentExports = {
    checkbox(id) { return `<input type="checkbox" data-select-experiment="${ExperimentUI.E(id)}" aria-label="选择实验 ${ExperimentUI.E(id.slice(0,8))} 用于统计导出" ${selected.has(id)?'checked':''}>`; },
    setPage(items) { page = items.map(item=>item.experiment_id); update(); },
    setCurrent(id) { current = id; update(); }
  };
})();
