(() => {
  'use strict';
  const $ = id => document.getElementById(id), T = ScheduleTimeline;
  let data = [], filtered = [], domain = [0, 1000], range = domain, chosen = null, tooltipOwner = null;
  let magneticBar = null;
  const scheduleUrl = new URLSearchParams(location.search).get('schedule') || '../output/schedules/Scenario_S1_schedule.json';
  const match = scheduleUrl.match(/^\/api\/runs\/([^/]+)\/visualization\/schedule(?:\?|$)/);
  if (match) { $('cesium-link').href = '/visualization/cesium/' + encodeURIComponent(decodeURIComponent(match[1])); $('cesium-link').hidden = false; }
  $('sourceLabel').textContent = '正式排程：' + scheduleUrl;
  const localInput = value => new Date(value).toISOString().slice(0, 19);
  function setRange(next) { range = T.clampRange(next[0], next[1], domain); render(); }
  function detailsText(a) { return `卫星：${a.satellite_id}\n任务：${a.task_id}\n开始：${T.fmt(a.start)}\n结束：${T.fmt(a.end)}\n曝光：${(a.end - a.start) / 1000} 秒${a.priority == null ? '' : '\n优先级：' + a.priority}`; }
  function hideTooltip() { magneticBar?.classList.remove('is-snapped'); magneticBar=null; tooltipOwner?.removeAttribute('aria-describedby'); tooltipOwner = null; $('task-tooltip').hidden = true; }
  function showTooltip(a, button) {
    hideTooltip(); tooltipOwner = button;
    const box = $('task-tooltip'); box.textContent = detailsText(a); box.hidden = false;
    button.setAttribute('aria-describedby', 'task-tooltip');
    const rect = button.getBoundingClientRect();
    box.style.left = Math.max(12, Math.min(rect.left, innerWidth - box.offsetWidth - 12)) + 'px';
    box.style.top = Math.max(12, rect.bottom + box.offsetHeight + 8 < innerHeight ? rect.bottom + 8 : rect.top - box.offsetHeight - 8) + 'px';
  }
  function showDetails(a) {
    chosen = a; $('focus-task').disabled = false; $('task-select').value = String(a.index);
    const dl = document.createElement('dl');
    for (const [key, value] of [['卫星', a.satellite_id], ['任务', a.task_id], ['开始 / UTC', T.fmt(a.start)], ['结束 / UTC', T.fmt(a.end)], ['曝光时长', (a.end - a.start) / 1000 + ' 秒'], ['优先级', a.priority ?? '未提供']]) {
      const pair = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = key; dd.textContent = value; pair.append(dt, dd); dl.append(pair);
    }
    $('task-detail').replaceChildren(dl);
    document.querySelectorAll('.gantt-bar').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.index) === a.index)));
  }
  function focusTask(a) {
    showDetails(a);
    const padding = Math.max(10000, a.end - a.start);
    setRange([a.start - padding, a.end + padding]);
    document.querySelector(`.gantt-bar[data-index="${a.index}"]`)?.scrollIntoView({block: 'nearest'});
  }
  function render() {
    hideTooltip();
    const span = range[1] - range[0];
    $('range-start').value = localInput(range[0]); $('range-end').value = localInput(range[1]);
    $('timeRangeLabel').textContent = `${T.fmt(range[0])} — ${T.fmt(range[1])} · 当前跨度 ${(span / 1000).toFixed(1)} 秒`;
    const travel = domain[1] - domain[0] - span;
    $('time-navigator').disabled = travel <= 0;
    $('time-navigator').value = travel <= 0 ? 0 : Math.round((range[0] - domain[0]) / travel * 1000);
    $('time-navigator').setAttribute('aria-valuetext', T.fmt(range[0]) + ' 至 ' + T.fmt(range[1]));
    $('pan-left').disabled = range[0] <= domain[0]; $('pan-right').disabled = range[1] >= domain[1];
    const axis = $('timeAxis'); axis.replaceChildren();
    const step = T.tickStep(span, axis.clientWidth || 800);
    for (let t = Math.ceil(range[0] / step) * step; t < range[1]; t += step) {
      const tick = document.createElement('span'); tick.className = 'axis-tick'; tick.style.left = ((t - range[0]) / span * 100) + '%';
      tick.textContent = new Date(t).toISOString().slice(0, 19).replace('T', '\n'); axis.append(tick);
    }
    const bySatellite = new Map();
    for (const a of filtered) { if (!bySatellite.has(a.satellite_id)) bySatellite.set(a.satellite_id, []); bySatellite.get(a.satellite_id).push(a); }
    const fragment = document.createDocumentFragment(); let visible = 0;
    for (const [sat, tasks] of [...bySatellite].sort(([a], [b]) => a.localeCompare(b))) {
      const row = document.createElement('div'), label = document.createElement('div'), track = document.createElement('div');
      row.className = 'gantt-row'; label.className = 'gantt-sat-label'; label.textContent = sat; track.className = 'gantt-timeline';
      const laneEnds = [];
      for (const a of tasks) {
        if (a.end <= range[0] || a.start >= range[1]) continue;
        visible++;
        let lane = laneEnds.findIndex(end => end <= a.start); if (lane < 0) lane = laneEnds.length; laneEnds[lane] = a.end;
        const bar = document.createElement('button'); bar.type = 'button'; bar.className = 'gantt-bar'; bar.dataset.index = a.index;
        const start = Math.max(range[0], a.start), end = Math.min(range[1], a.end);
        bar.style.left = (start - range[0]) / span * 100 + '%'; bar.style.width = (end - start) / span * 100 + '%'; bar.style.top = (lane * 34 + 7) + 'px';
        bar.textContent = a.task_id; bar.setAttribute('aria-label', detailsText(a).replace(/\n/g, '；')); bar.setAttribute('aria-pressed', String(chosen?.index === a.index));
        bar.addEventListener('pointerenter', () => showTooltip(a, bar));
        bar.addEventListener('pointerleave', event => { if (!event.relatedTarget || !$('task-tooltip').contains(event.relatedTarget)) hideTooltip(); });
        bar.addEventListener('focus', () => showTooltip(a, bar)); bar.addEventListener('blur', hideTooltip);
        bar.addEventListener('click', () => { showDetails(a); showTooltip(a, bar); }); track.append(bar);
      }
      function hit(event) {
        const direct=event.target.closest('.gantt-bar');
        if(direct&&track.contains(direct))return direct;
        const bars=[...track.querySelectorAll('.gantt-bar')];
        const id=T.magneticHit({x:event.clientX,y:event.clientY},bars.map(bar=>{
          const r=bar.getBoundingClientRect();return {id:bar.dataset.index,left:r.left,right:r.right,top:r.top,bottom:r.bottom};
        }),12);
        return id==null?null:bars.find(b=>b.dataset.index===id);
      }
      track.addEventListener('pointermove',event=>{
        if(event.pointerType==='touch')return;
        const bar=hit(event);
        if(!bar){hideTooltip();return;}
        if(magneticBar!==bar||$('task-tooltip').hidden){
          showTooltip(data.find(a=>String(a.index)===bar.dataset.index),bar);
          magneticBar=bar;bar.classList.add('is-snapped');
        }
      });
      track.addEventListener('pointerleave',event=>{if(!event.relatedTarget||!$('task-tooltip').contains(event.relatedTarget))hideTooltip();});
      track.addEventListener('click',event=>{
        if(event.target.closest('.gantt-bar'))return;
        const bar=hit(event);if(!bar)return;
        const a=data.find(a=>String(a.index)===bar.dataset.index);showDetails(a);showTooltip(a,bar);
        magneticBar=bar;bar.classList.add('is-snapped');
      });
      track.style.height = Math.max(40, laneEnds.length * 34 + 8) + 'px'; row.append(label, track); fragment.append(row);
    }
    $('ganttContainer').replaceChildren(fragment);
    $('chart-status').textContent = `筛选 ${filtered.length}/${data.length} 条观测 · 当前窗口可见 ${visible} 条 · ${bySatellite.size} 颗卫星`;
  }
  function filter() {
    const search = $('task-search').value.trim().toLowerCase(), sat = $('satellite-filter').value;
    filtered = data.filter(a => (!sat || a.satellite_id === sat) && `${a.task_id} ${a.satellite_id}`.toLowerCase().includes(search));
    $('task-select').replaceChildren(new Option(`定位观测记录（${filtered.length} 条）`, ''), ...filtered.map(a => new Option(`${a.task_id} · ${a.satellite_id} · ${T.fmt(a.start)}`, String(a.index))));
    if (chosen && filtered.some(a => a.index === chosen.index)) $('task-select').value = String(chosen.index);
    render();
  }
  function zoom(factor) { const anchor = chosen && chosen.start >= range[0] && chosen.end <= range[1] ? (chosen.start + chosen.end) / 2 : (range[0] + range[1]) / 2; setRange(T.zoom(range, factor, anchor, domain)); }
  function pan(direction) { const shift = (range[1] - range[0]) * .5 * direction; setRange([range[0] + shift, range[1] + shift]); }
  $('zoom-in').onclick = () => zoom(.5); $('zoom-out').onclick = () => zoom(2);
  $('pan-left').onclick = () => pan(-1); $('pan-right').onclick = () => pan(1);
  $('fit-all').onclick = () => setRange(domain);
  $('fit-tasks').onclick = () => { if (filtered.length) setRange([Math.min(...filtered.map(a => a.start)) - 1000, Math.max(...filtered.map(a => a.end)) + 1000]); };
  $('focus-task').onclick = () => { if (chosen) focusTask(chosen); };
  $('task-select').onchange = () => { const value = $('task-select').value; if (value !== '') { const a = data.find(a => String(a.index) === value); if (a) focusTask(a); } };
  $('satellite-filter').onchange = filter; $('task-search').oninput = filter;
  $('apply-range').onclick = () => {
    const start = T.parseTime($('range-start').value), end = T.parseTime($('range-end').value);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || end <= domain[0] || start >= domain[1]) { $('errorBox').hidden = false; $('errorBox').textContent = '请输入周期内有效的 UTC 起止时间，结束时间必须晚于开始。'; return; }
    $('errorBox').hidden = true; setRange([start, end]);
  };
  $('time-navigator').oninput = () => { const span = range[1] - range[0], left = domain[0] + (domain[1] - domain[0] - span) * Number($('time-navigator').value) / 1000; setRange([left, left + span]); };
  $('mainArea').addEventListener('keydown', event => {
    if (event.target !== $('mainArea')) return;
    const actions = {'+': () => zoom(.5), '=': () => zoom(.5), '-': () => zoom(2), ArrowLeft: () => pan(-1), ArrowRight: () => pan(1), Home: () => setRange(domain)};
    if (actions[event.key]) { event.preventDefault(); actions[event.key](); }
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hideTooltip(); });
  $('task-tooltip').addEventListener('pointerleave', hideTooltip);
  window.addEventListener('scroll', hideTooltip, true);
  let resizeFrame; new ResizeObserver(() => { cancelAnimationFrame(resizeFrame); resizeFrame = requestAnimationFrame(() => { if (data.length) render(); }); }).observe($('timeAxis'));
  fetch(scheduleUrl).then(async r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }).then(schedule => {
    if (schedule.result_kind === 'planning_preview') $('sourceLabel').textContent = '规划预览 · 未取得正式连续认证 · ' + scheduleUrl;
    data = T.normalize(schedule.assignments || []);
    if (!data.length) throw new Error('此排程没有有效观测记录。');
    const first = Math.min(...data.map(a => a.start)), last = Math.max(...data.map(a => a.end));
    const horizonStart = T.parseTime(schedule.start_time), horizonEnd = T.parseTime(schedule.end_time);
    domain = [Number.isFinite(horizonStart) ? Math.min(first, horizonStart) : first, Number.isFinite(horizonEnd) ? Math.max(last, horizonEnd) : last];
    if (domain[1] - domain[0] < 1000) domain[1] = domain[0] + 1000;
    range = domain.slice();
    $('satellite-filter').append(...[...new Set(data.map(a => a.satellite_id))].sort().map(s => new Option(s, s)));
    filter();
  }).catch(error => { $('errorBox').hidden = false; $('errorBox').textContent = '无法读取排程：' + error.message; $('chart-status').textContent = '暂无可显示的观测。'; });
})();
