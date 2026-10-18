// 页面只调用 HTTP API；正式计划与指标由 Controller 核验后提供。
const $ = (id) => document.getElementById(id);
let selectedId = null;
let currentAlgorithms = [];
let currentScenarios = [];
let outputProfiles = [];
let replayConfigId = null;
let replayPendingId = null;
const pageSize = 30;
let pageOffset = 0;
let autoRefresh = true;
let scenarioGeneration = 0;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || JSON.stringify(body));
  return body;
}

async function bootstrap() {
  try {
    const [health, sources, profiles, algorithms, replayConfigs] = await Promise.all([
      api("/api/health"), api("/api/data-sources"), api("/api/output-profiles"), api("/api/algorithms"), api("/api/replay-configs")
    ]);
    $("health").textContent = `服务已连接 · ${health.version} · 控制台 ${health.ui?.build_id || '版本未提供'}`;
    $("source").innerHTML = sources.items.map((s) => `<option value="${escapeHtml(s.source_id)}">${escapeHtml(s.name)}</option>`).join("");
    outputProfiles = profiles.items;
    $("output-profile").innerHTML = profiles.items.map((p) => `<option value="${escapeHtml(p.profile_id)}">${escapeHtml(p.name)}</option>`).join("");
    replayConfigId = replayConfigs.default_id;
    currentAlgorithms = algorithms.items;
    $("schedule-model").innerHTML = algorithms.models.map(m => `<option value="${escapeHtml(m.model_id)}">${escapeHtml(m.name)}</option>`).join('');
    window.ConsoleUI?.catalog(currentAlgorithms);
    await loadScenarios();
    if(sources.catalog_warnings?.length) $("register-message").textContent=sources.catalog_warnings.join("；");
    updateHints();
    await refresh();
  } catch (error) {
    $("health").textContent = "服务连接失败";
    $("form-message").textContent = error.message;
  }
}

async function loadScenarios() {
  const generation = ++scenarioGeneration;
  const sourceId = $("source").value;
  const previous = $("scenario").value;
  if (!sourceId) return;
  const scenarios = await api(`/api/scenarios?source_id=${encodeURIComponent(sourceId)}&execution_mode=${encodeURIComponent($("execution-mode").value)}`);
  if (generation !== scenarioGeneration) return;
  currentScenarios=scenarios.items;
  $("scenario").innerHTML = currentScenarios.map(s => {
    const unavailable=s.availability && s.availability!=='ready';
    const suffix=s.satellite_count ? " · "+s.satellite_count+"星/"+s.mission_count+"任务" : "";
    return '<option value="'+escapeHtml(s.scenario_id)+'"'+(unavailable ? ' disabled' : '')+'>'
      +escapeHtml(s.name+suffix+(unavailable ? "（文件未就绪）" : ""))+'</option>';
  }).join("");
  const available = currentScenarios.filter(s => !s.availability || s.availability === 'ready');
  const ready = available.find(s => s.scenario_id === previous || s.scenario_id === previous + '_epoch_fixed_v1')
    || [...available].sort((a,b) => (a.satellite_count ?? Infinity) - (b.satellite_count ?? Infinity)
      || (a.mission_count ?? Infinity) - (b.mission_count ?? Infinity))[0];
  if(ready) $("scenario").value=ready.scenario_id;
  $("submit").disabled=!ready;
  updateScenarioHint();
  $("form-message").textContent = currentScenarios.length ? (ready ? "" : "场景文件未就绪，请完成 Git LFS 下载并核对 SHA。") : "该数据源没有直接存放的 JSON 场景文件。";
}

function updateScenarioHint() {
  const scene=currentScenarios.find(s => s.scenario_id===$("scenario").value);
  if(!scene) { $("scenario-hint").textContent="";return; }
  $("scenario-hint").textContent=`${scene.satellite_count ?? '未知'} 颗卫星 · ${scene.mission_count ?? '未知'} 个任务 · ${scene.duration_s == null ? '未知时长' : (scene.duration_s/3600).toFixed(2)+' 小时'} · ${scene.scenario_physics_version || 'legacy_unknown'} · 来源 ${scene.provenance_status || 'unknown'} · 物理验证 ${scene.physical_validation_status || 'UNKNOWN'} · ${scene.availability || 'ready'}。${scene.validation_message || ''} 提交时重新核对场景 SHA：${scene.sha256 || '未知'}`;
}
$("scenario").addEventListener("change",updateScenarioHint);

function updateHints() {
  if ($("execution-mode").value === 'planning_preview') {
    for (const option of $("output-profile").options) option.disabled = outputProfiles.find(p => p.profile_id === option.value)?.kind === 'directory';
    $("output-profile").value = outputProfiles.find(p => p.kind === 'download')?.profile_id || '';
  }
  const profile = outputProfiles.find((p) => p.profile_id === $("output-profile").value);
  $("output-hint").textContent = profile?.kind === "directory"
    ? `正式 JSON/CSV 将保存到 ${profile.root_path}/<run_id>/；浏览器仍可下载。`
    : "只提供浏览器下载；数据库与运行状态仍保存在 WSL 运行目录。";
  if ($("execution-mode").value === 'planning_preview') $("output-hint").textContent = '规划预览保存数据库记录并支持比较和回放；不生成正式认证 JSON/CSV 文件。';
}

$("source").addEventListener("change", () => loadScenarios().catch((error) => { $("form-message").textContent = error.message; }));
$("execution-mode").addEventListener("change", () => {
  const preview = $("execution-mode").value === 'planning_preview';
  $("mode-hint").textContent = preview
    ? '规划预览：可比较和回放；曝光采样检查不构成连续区间证明，不得作为正式认证计划导出。'
    : '正式认证：保留严格连续认证门禁；缺少可信物理来源或连续区间证明时不会发布成功计划。';
  for (const option of $("output-profile").options) {
    option.disabled = preview && outputProfiles.find(p => p.profile_id === option.value)?.kind === 'directory';
  }
  if (preview) $("output-profile").value = outputProfiles.find(p => p.kind === 'download')?.profile_id || '';
  loadScenarios().catch(error => { $("form-message").textContent = error.message; });
});
$("output-profile").addEventListener("change", updateHints);

$("register-location").addEventListener("click", async () => {
  const kind = $("register-kind").value;
  const endpoint = kind === "source" ? "/api/data-sources" : "/api/output-profiles";
  $("register-location").disabled = true;
  try {
    const added = await api(endpoint, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({
      name: $("register-name").value.trim(), path: $("register-path").value.trim()
    })});
    $("register-message").textContent = `已登记 ${added.name}：${added.root_path}`;
    if (kind === "source") {
      const sources = await api("/api/data-sources");
      $("source").innerHTML = sources.items.map((s) => `<option value="${escapeHtml(s.source_id)}">${escapeHtml(s.name)}</option>`).join("");
      $("source").value = added.source_id;
      await loadScenarios();
    } else {
      const profiles = await api("/api/output-profiles");
      outputProfiles = profiles.items;
      $("output-profile").innerHTML = profiles.items.map((p) => `<option value="${escapeHtml(p.profile_id)}">${escapeHtml(p.name)}</option>`).join("");
      $("output-profile").value = added.profile_id;
      updateHints();
    }
  } catch (error) { $("register-message").textContent = error.message; }
  finally { $("register-location").disabled = false; }
});

function buildRequest() {
  return {
    execution_mode: $("execution-mode").value,
    source_id: $("source").value,
    scenario_id: $("scenario").value,
    algorithm_id: currentAlgorithms.find(a=>a.availability==='ready')?.algorithm_id,
    schedule_model: $("schedule-model").value,
    output_profile_id: $("output-profile").value,
    algorithm_params: {},
    seed: Number($("seed").value),
    placement_mode: $("placement").value,
    constraints: {
      unassigned_penalty: Number($("penalty").value),
      downlink_duration_ratio: Number($("downlink").value),
      agility_profile: $("agility").value,
      non_agile_transition_s: Number($("transition").value)
    },
    objective_weights: {w_profit: Number($("weight-profit").value), w_completion: Number($("weight-completion").value), w_timeliness: Number($("weight-timeliness").value), w_balance: Number($("weight-balance").value)},
    time_budget_s: Number($("budget").value)
  };
}

$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (window.ConsoleUI) return window.ConsoleUI.submit();
  $("form-message").textContent = '实验控制台组件未加载，请刷新页面；没有创建运行。';
});

async function refresh() {
  if (window.ConsoleUI?.refreshExperiments) return window.ConsoleUI.refreshExperiments();
}

function clearDetail() {
  if (window.ConsoleUI) window.ConsoleUI.detail(null);
  $("replay-status").textContent = "";
  $("scenario-provenance").textContent = "";
  $("build-replay").hidden = true;
  $("selected-run").textContent = "选择列表中的实验";
  $("detail-status").textContent = "尚未选择";
  $("detail-status").className = "badge muted";
  $("actions").hidden = true;
  $("delete-option").hidden = true;
  $("delete-files").checked = false;
  $("detail-error").textContent = "";
  $("metrics").innerHTML = "";
  $("files").innerHTML = "";
  $("events").innerHTML = "";
  $("assignments").innerHTML = "";
  $("assignment-count").textContent = "";
}

function showDetail(run) {
  if (window.ConsoleUI) window.ConsoleUI.detail(run);
  $("selected-run").textContent = run.run_id;
  $("detail-status").textContent = run.status + (run.result_kind === 'planning_preview' ? ' · 规划预览' : '');
  $("detail-status").className = `badge ${["FAILED","CANCELLED","TIMED_OUT"].includes(run.status) ? "failed" : ["RUNNING","QUEUED","VERIFYING"].includes(run.status) ? "running" : ""}`;
  $("actions").hidden = false;
  $("cancel").disabled = ["SUCCEEDED","FAILED","CANCELLED","TIMED_OUT"].includes(run.status) || run.cancel_requested;
  $("delete-run").disabled = false;
  $("delete-option").hidden = !(run.exports || []).some((item) => item.artifact_path);
  if ($("delete-option").hidden) $("delete-files").checked = false;
  $("export-json").hidden = run.status !== "SUCCEEDED" || !run.plan || run.result_kind === 'planning_preview';
  $("export-csv").hidden = run.status !== "SUCCEEDED" || !run.plan || run.result_kind === 'planning_preview';
  $("open-gantt").hidden = run.status !== "SUCCEEDED" || !run.plan;
  $("open-cesium").hidden = run.status !== "SUCCEEDED" || !run.plan;
  $("export-json").href = `/api/runs/${encodeURIComponent(run.run_id)}/export?format=json`;
  $("export-csv").href = `/api/runs/${encodeURIComponent(run.run_id)}/export?format=csv`;
  $("open-gantt").href = `/visualization/gantt/${encodeURIComponent(run.run_id)}`;
  $("open-cesium").href = `/visualization/cesium/${encodeURIComponent(run.run_id)}`;
  $("scenario-provenance").textContent = "场景物理版本："+(run.config.scenario_provenance?.scenario_physics_version || "legacy_unknown")+"；来源："+(run.config.scenario_provenance?.provenance_status || "unknown");
  $("build-replay").hidden = run.status !== "SUCCEEDED" || !run.plan;
  if (run.status === "SUCCEEDED" && run.plan) refreshReplay(run.run_id);
  else $("replay-status").textContent = "";
  $("detail-error").textContent = run.error ? `${run.error.code}: ${run.error.message}` : "";
  const files = (run.exports || []).filter((item) => item.artifact_path || item.error_message);
  $("files").innerHTML = files.length ? files.map((item) => `<li>${escapeHtml(item.format.toUpperCase())} · ${escapeHtml(item.artifact_path || item.error_message)}</li>`).join("")
    : run.result_kind === 'planning_preview' ? '<li>规划预览不生成正式输出文件；请使用 Gantt / Cesium 分析结果。</li>'
      : run.status === 'SUCCEEDED' && run.plan ? '<li>此实验没有服务器目录文件；可使用上方浏览器下载。</li>'
      : '<li>此实验没有可下载的正式结果。</li>';
  const m = run.metrics;
  $("metrics").innerHTML = m ? [
    ["完成任务", `${m.completed_tasks} / ${m.total_tasks}`], ["TCR", `${(m.TCR * 100).toFixed(1)}%`],
    ["TP ↑", Number(m.TP).toFixed(2)], ["BD ↑", Number(m.BD).toFixed(3)], ["TM ↓", Number(m.TM).toFixed(3)], ["RV ↓", m.RV == null ? '未提供' : Number(m.RV).toFixed(3)], ["算法耗时 RT ↓", `${Number(m.RT).toFixed(3)} s`]
  ].map(([label, value]) => `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("") : "";
  $("events").innerHTML = run.events.map((e) => `<li>${escapeHtml(e.recorded_at)} · ${escapeHtml(e.event_type)}</li>`).join("");
  const assignments = run.plan?.assignments || [];
  $("assignment-count").textContent = `(${assignments.length})`;
  $("assignments").innerHTML = assignments.slice(0, 100).map((a) => `<tr><td>${escapeHtml(a.task_id)}</td><td>${escapeHtml(a.satellite_id)}</td><td>${escapeHtml(a.sat_start_time)}</td><td>${escapeHtml(a.sat_end_time)}</td></tr>`).join("");
}

// 轮询只 GET；独立按钮才 POST，避免页面刷新、选星触发昂贵构建。
async function refreshReplay(runId) {
  try {
    const state=await api('/api/runs/'+encodeURIComponent(runId)+'/replay');
    if (selectedId!==runId) return;
    const labels={NOT_REQUESTED:'尚未构建',BUILDING:'正在构建',READY:'已就绪',FAILED:'构建失败'};
    const sampling=state.manifest?.sampling_policy;
    const summary=sampling ? ' · 展示采样 '+sampling.attitude_step_s+' 秒，保留任务端点' : '';
    $("replay-status").textContent='回放：'+labels[state.replay_status]+summary+(state.error ? ' · '+state.error.message : '');
    $("build-replay").disabled=state.replay_status==='BUILDING' || replayPendingId===runId;
    $("build-replay").textContent=state.replay_status==='FAILED' ? '重试构建回放' : state.replay_status==='READY' ? '复用已就绪回放' : '构建回放';
  } catch(error) {
    if(selectedId===runId) $("replay-status").textContent='回放查询失败：'+error.message;
  }
}
$("build-replay").addEventListener("click",async () => {
  if(!selectedId || !replayConfigId) return;
  const runId=selectedId;
  replayPendingId=runId;
  $("build-replay").disabled=true;
  let requestError=null;
  try {
    await api('/api/runs/'+encodeURIComponent(runId)+'/replay',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({replay_config_id:replayConfigId})
    });
    await refreshReplay(runId);
  } catch(error) {
    requestError=error;
  } finally {
    replayPendingId=null;
    if(selectedId===runId) {
      await refreshReplay(runId);
      if(requestError) $("replay-status").textContent='构建申请失败：'+requestError.message;
    }
  }
});
$("cancel").addEventListener("click", async () => {
  if (!selectedId) return;
  try { await api(`/api/runs/${encodeURIComponent(selectedId)}/cancel`, {method:"POST"}); await refresh(); }
  catch (error) { $("detail-error").textContent = error.message; }
});
$("delete-run").addEventListener("click", async () => {
  if (window.ConsoleUI?.removeSelectedAlgorithm) return window.ConsoleUI.removeSelectedAlgorithm();
});
$("refresh").addEventListener("click", refresh);
$("toggle-refresh").addEventListener("click", () => {
  autoRefresh = !autoRefresh;
  $("toggle-refresh").setAttribute("aria-pressed", autoRefresh ? "false" : "true");
  $("toggle-refresh").textContent = autoRefresh ? "暂停自动更新" : "继续自动更新";
  $("run-count").textContent = autoRefresh ? "状态每两秒刷新一次。" : "自动更新已暂停。";
});
$("previous-page").addEventListener("click", () => { pageOffset = Math.max(0, pageOffset - pageSize); refresh(); });
$("next-page").addEventListener("click", () => { pageOffset += pageSize; refresh(); });
bootstrap();
setInterval(() => { if (autoRefresh) refresh(); }, 2000);
