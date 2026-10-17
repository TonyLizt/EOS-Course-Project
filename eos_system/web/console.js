/* Runs remain independent API resources; a batch is a browser-side selection. */
(() => {
  'use strict';
  const selected = new Set();
  const cache = new Map();
  const params = new Map();
  const terminal = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT']);
  const E = escapeHtml;
  const verification = run => run.status === 'SUCCEEDED'
    ? `Controller 已提交 · 连续认证 ${run.continuous_certification?.status || '未提供'}`
    : (run.error?.message || '未提交正式计划');
  let activeAlgorithm = '', detailRun = null, comparing = false, submitting = false;
  try { JSON.parse(sessionStorage.getItem('eos-comparison') || '[]').slice(0, 12).forEach(id => selected.add(id)); } catch (_) { /* Optional storage. */ }
  function persist() {
    try { sessionStorage.setItem('eos-comparison', JSON.stringify([...selected])); } catch (_) { /* Private browsing may deny storage. */ }
  }
  function catalog(algorithms) {
    $('algorithm-choices').innerHTML = algorithms.map((a, i) => `<label class="check-label"><input type="checkbox" name="batch-algorithm" value="${E(a.algorithm_id)}" ${i === 0 ? 'checked' : ''} ${a.availability && a.availability !== 'ready' ? 'disabled' : ''}><span>${E(a.name)} <small>${E(a.version)} · ${E(a.availability || 'ready')}</small></span></label>`).join('');
    activeAlgorithm = $('algorithm').value;
  }
  $('algorithm').addEventListener('change', () => {
    if (activeAlgorithm) params.set(activeAlgorithm, $('params').value);
    activeAlgorithm = $('algorithm').value;
    $('params').value = params.get(activeAlgorithm) || '{}';
  });
  function showAlgorithm(id, run = null) {
    const a = currentAlgorithms.find(item => item.algorithm_id === id);
    $('algorithm-dialog-title').textContent = a?.name || id;
    const rows = a ? [['ID / 类型 / 版本', `${a.algorithm_id} · ${a.category} · ${a.version}`], ['简介', a.description], ['调度策略', a.strategy || '注册表未提供'], ['优化目标', a.objectives || '注册表未提供'], ['适用与限制', a.limitations || '注册表未提供'], ['参数定义（来自注册表）', JSON.stringify(a.parameters, null, 2)]] : [['算法', '历史算法当前未注册；下方保留该次运行的固化参数。']];
    if (run) rows.push(['本次 Run / 算法版本', `${run.run_id} · ${run.config.algorithm_version}`], ['本次参数', JSON.stringify(run.config, null, 2)]);
    $('algorithm-description').innerHTML = `<dl>${rows.map(([k, v]) => `<dt>${E(k)}</dt><dd><pre>${E(v)}</pre></dd>`).join('')}</dl>`;
    $('algorithm-dialog').showModal();
  }
  $('algorithm-info').addEventListener('click', () => showAlgorithm($('algorithm').value));
  $('run-algorithm-info').addEventListener('click', () => { if (detailRun) showAlgorithm(detailRun.config.algorithm_id, detailRun); });
  $('close-algorithm-dialog').addEventListener('click', () => $('algorithm-dialog').close());
  function detail(run) {
    detailRun = run;
    $('run-algorithm-info').hidden = !run;
    $('run-config').textContent = run ? JSON.stringify({config: run.config, continuous_certification: run.continuous_certification || null}, null, 2) : '';
    const last = run?.attempts?.at(-1);
    $('run-summary').textContent = run ? `${run.config.algorithm_id} ${run.config.algorithm_version} · ${run.config.scenario_id} · 提交 ${run.created_at} · 开始 ${last?.started_at || '尚未开始'} · 结束 ${run.finished_at || '尚未结束'} · ${verification(run)}` : '';
    if (run) cache.set(run.run_id, run);
  }
  async function submit() {
    if (submitting) return;
    const ids = [...document.querySelectorAll('[name="batch-algorithm"]:checked')].map(el => el.value);
    if (!ids.length) { $('form-message').textContent = '请至少选择一个已注册算法。'; return; }
    let requests;
    try {
      params.set($('algorithm').value, $('params').value);
      const common = buildRequest();
      requests = ids.map(id => {
        const value = JSON.parse(params.get(id) || '{}');
        if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error(`${id} 的参数必须是 JSON 对象`);
        return {...common, algorithm_id: id, algorithm_params: value};
      });
    } catch (error) { $('form-message').textContent = error.message; return; }
    submitting = true;
    $('submit').disabled = true;
    $('form-message').textContent = '正在提交独立运行；已接受的运行会立即进入现有队列。';
    $('submission-results').replaceChildren();
    let accepted = 0;
    // Sequential HTTP submission avoids a burst against the existing queue limit.
    for (const request of requests) {
      const li = document.createElement('li');
      $('submission-results').append(li);
      try {
        const result = await api('/api/runs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(request)});
        accepted++;
        selectedId = result.run_id;
        if (selected.size < 12) selected.add(result.run_id);
        li.textContent = `${request.algorithm_id}：已接受 · ${result.run_id}`;
      } catch (error) { li.textContent = `${request.algorithm_id}：提交失败 · ${error.message}。可稍后单独重试；已接受的任务不受影响。`; }
    }
    persist();
    pageOffset = 0;
    await refresh();
    $('form-message').textContent = `提交完成：${accepted}/${requests.length} 个已接受。队列满或参数错误会逐项显示。`;
    submitting = false;
    $('submit').disabled = !currentScenarios.some(s => s.scenario_id === $('scenario').value && (!s.availability || s.availability === 'ready'));
  }
  function formatMetric(key, value) {
    if (value == null) return '—';
    return key === 'TCR' ? `${(value * 100).toFixed(1)}%` : Number(value).toFixed(3);
  }
  async function refreshComparison() {
    if (comparing) return;
    comparing = true;
    try {
      const errors = [];
      const results = await Promise.all([...selected].map(async id => {
        try {
          const old = cache.get(id);
          const run = old && terminal.has(old.status) ? old : await api(`/api/runs/${encodeURIComponent(id)}`);
          cache.set(id, run);
          return run;
        } catch (error) { errors.push(`${id}: ${error.message}`); return null; }
      }));
      const groups = RunComparison.groupRuns(results.filter(Boolean));
      $('comparison-status').textContent = `${selected.size}/12 个已选运行 · ${groups.length} 个条件组${errors.length ? ' · 部分记录无法读取：' + errors.join('；') : ''}`;
      const comparisonHtml = groups.map((group, i) => `<section class="comparison-group"><h3>条件组 ${i + 1} · ${E(group.runs[0].config.scenario_id)}</h3><p class="hint">${group.identified ? `场景 SHA ${E(group.conditions.scenario_sha256.slice(0, 12))} · seed ${group.conditions.seed} · 预算 ${group.conditions.time_budget_s}s` : '条件来源不完整：单独展示，不标记指标最佳值。'}</p><details><summary>比较条件与差异</summary><pre>${E(JSON.stringify(group.conditions, null, 2))}</pre><p>算法及其参数有意允许不同，各 Run 分别列出。不同 SHA、代码／约束、种子、预算、放置模式、权重和指标版本自动分组；这不是重复种子的统计结论。</p></details><div class="table-wrap" tabindex="0" aria-label="条件组 ${i + 1} 结果"><table><caption class="sr-only">同条件指标比较</caption><thead><tr><th>算法 / 运行</th><th>状态 / 核验</th><th>完成 / 未完成</th>${RunComparison.metrics.map(([k, d]) => `<th scope="col">${k} ${d > 0 ? '↑' : '↓'}</th>`).join('')}<th scope="col">查看</th></tr></thead><tbody>${group.runs.map(run => `<tr><th scope="row"><button class="run-select" data-detail="${E(run.run_id)}">${E(run.config.algorithm_id)} · ${E(run.config.algorithm_version)}</button><small class="run-id">${E(run.run_id)}</small><details><summary>算法参数</summary><pre>${E(JSON.stringify(run.config.algorithm_params, null, 2))}</pre></details></th><td>${E(run.status)}<br>${E(verification(run))}</td><td>${run.metrics ? `${run.metrics.completed_tasks} / ${run.metrics.total_tasks - run.metrics.completed_tasks}` : '—'}</td>${RunComparison.metrics.map(([k, d]) => { const value = run.metrics?.[k]; const winner = run.status === 'SUCCEEDED' && value != null && value === RunComparison.best(group, k, d); return `<td class="${winner ? 'metric-best' : ''}">${formatMetric(k, value)}${winner ? ' ★' : ''}</td>`; }).join('')}<td><button type="button" class="secondary" data-algorithm="${E(run.run_id)}">算法详情</button> ${run.status === 'SUCCEEDED' && run.plan ? `<a href="/visualization/gantt/${encodeURIComponent(run.run_id)}">Gantt</a> · <a href="/visualization/cesium/${encodeURIComponent(run.run_id)}">Cesium</a>` : `<button class="secondary" type="button" data-detail="${E(run.run_id)}">运行详情 / 取消</button>`}<button class="secondary" type="button" data-remove="${E(run.run_id)}" aria-label="移出比较 ${E(run.run_id)}">移出</button></td></tr>`).join('')}</tbody></table></div></section>`).join('') || '<p>选择算法提交一次运行，或从历史记录勾选要比较的实验。</p>';
      if ($('comparison-groups').dataset.rendered !== comparisonHtml) {
        $('comparison-groups').innerHTML = comparisonHtml;
        $('comparison-groups').dataset.rendered = comparisonHtml;
      }
    } finally { comparing = false; }
  }
  $('runs').addEventListener('change', event => {
    const input = event.target.closest('.compare-run');
    if (!input) return;
    if (input.checked && selected.size >= 12) { input.checked = false; $('list-message').textContent = '一次最多比较 12 个运行，请先移出已有记录。'; return; }
    if (input.checked) selected.add(input.dataset.run); else selected.delete(input.dataset.run);
    persist(); refreshComparison();
  });
  $('comparison-groups').addEventListener('click', event => {
    const action = event.target.closest('button');
    if (!action) return;
    if (action.dataset.detail) { selectedId = action.dataset.detail; refresh(); $('detail-heading').scrollIntoView({block: 'start'}); }
    if (action.dataset.algorithm) { const run = cache.get(action.dataset.algorithm); if (run) showAlgorithm(run.config.algorithm_id, run); }
    if (action.dataset.remove) { selected.delete(action.dataset.remove); persist(); refresh(); }
  });
  $('clear-comparison').addEventListener('click', () => { selected.clear(); persist(); refresh(); });
  window.ConsoleUI = {catalog, detail, submit, refreshComparison, has: id => selected.has(id)};
})();
