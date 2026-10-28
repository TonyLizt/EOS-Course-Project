/* 工作区只切换可见性，始终复用原控件，避免丢失参数、选中实验与临时比较。 */
(() => {
  'use strict';
  const definitions = {
    course: {hash:'course-overview', title:'课程导览', description:'从调度模型出发，理解卫星场景与真实进程执行之间的关系。'},
    create: {hash:'new-experiment', title:'作业提交 · 新建实验', description:'选择作业场景、调度策略与求解预算，提交可复核的对照实验。'},
    records: {hash:'experiments', title:'运行管理 · 实验记录', description:'观察队列与进程执行记录，查看核验结果、导出与回放。'},
    compare: {hash:'comparison', title:'策略评估 · 结果比较', description:'同条件比较经典OS迁移策略、简单基线与小组方法，分析收益与代价。'}
  };
  const aliases = {'create-heading':'create','runs-heading':'records','detail-heading':'records','comparison-heading':'compare','main-content':'create'};
  function pageFromHash(hash) {
    const name = hash.replace(/^#/, '');
    // 空地址进入课程导览；已有实验锚点和未知旧链接仍保留原来的解析规则。
    if (!name) return 'course';
    return Object.keys(definitions).find(key => definitions[key].hash === name) || aliases[name] || 'create';
  }
  function showPage(key, options = {}) {
    const page = definitions[key] ? key : 'create';
    const config = definitions[page];
    for (const section of document.querySelectorAll('[data-console-page]')) section.hidden = section.dataset.consolePage !== page;
    for (const link of document.querySelectorAll('[data-console-route]')) {
      if (link.dataset.consoleRoute === page) link.setAttribute('aria-current','page');
      else link.removeAttribute('aria-current');
    }
    const title = document.getElementById('workspace-page-title');
    title.textContent = config.title;
    document.getElementById('workspace-page-description').textContent = config.description;
    document.title = config.title + ' · 操作系统课程设计';
    // pushState 不引发原生锚点滚动；后退/前进由 popstate 恢复工作区。
    if (options.history !== false && location.hash !== '#' + config.hash) history.pushState(null,'','#' + config.hash);
    if (options.focus !== false) { title.tabIndex = -1; title.focus({preventScroll:true}); }
  }
  document.addEventListener('click', event => {
    const link = event.target.closest('[data-console-route]');
    if (!link || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); showPage(link.dataset.consoleRoute);
  });
  const restore = () => showPage(pageFromHash(location.hash), {history:false, focus:false});
  window.addEventListener('popstate', restore);
  window.addEventListener('hashchange', restore);
  window.ConsoleWorkspace = {showPage};
  restore();
})();
