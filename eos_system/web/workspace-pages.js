/* 工作区只切换可见性，始终复用原控件，避免丢失参数、选中实验与临时比较。 */
(() => {
  'use strict';
  const definitions = {
    create: {hash:'new-experiment', title:'新建实验', description:'选择场景与算法，设置预算后开始运行。'},
    records: {hash:'experiments', title:'实验管理', description:'浏览运行记录，检查计划与指标，导出或打开三维回放。'},
    compare: {hash:'comparison', title:'结果比较', description:'在同一实验中比较算法，也可添加临时模型对照。'}
  };
  const aliases = {'create-heading':'create','runs-heading':'records','detail-heading':'records','comparison-heading':'compare','main-content':'create'};
  function pageFromHash(hash) {
    const name = hash.replace(/^#/, '');
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
    document.title = config.title + ' · 统一调度控制台';
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
