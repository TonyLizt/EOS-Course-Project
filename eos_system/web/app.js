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
let deletingRunId = null;
let autoRefresh = true;
let refreshGeneration = 0;

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
    $("health").textContent = `服务已连接 · ${health.version}`;
    $("source").innerHTML = sources.items.map((s) => `<option value="${escapeHtml(s.source_id)}">${escapeHtml(s.name)}</option>`).join("");
    outputProfiles = profiles.items;
    $("output-profile").innerHTML = profiles.items.map((p) => `<option value="${escapeHtml(p.profile_id)}">${escapeHtml(p.name)}</option>`).join("");
    replayConfigId = replayConfigs.default_id;
    currentAlgorithms = algorithms.items;
    $("algorithm").innerHTML = currentAlgorithms.map((a) => `<option value="${escapeHtml(a.algorithm_id)}">${escapeHtml(a.name)}</option>`).join("");
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
  const sourceId = $("source").value;
  if (!sourceId) return;
  const scenarios = await api(`/api/scenarios?source_id=${encodeURIComponent(sourceId)}`);
  currentScenarios=scenarios.items;
  $("scenario").innerHTML = currentScenarios.map(s => {
    const unavailable=s.availability && s.availability!=='ready';
    const suffix=s.satellite_count ? " · "+s.satellite_count+"星/"+s.mission_count+"任务" : "";
    return '<option value="'+escapeHtml(s.scenario_id)+'"'+(unavailable ? ' disabled' : '')+'>'
      +escapeHtml(s.name+suffix+(unavailable ? "（文件未就绪）" : ""))+'</option>';
  }).join("");
  const ready=currentScenarios.find(s => !s.availability || s.availability==='ready');
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
  const algorithm = currentAlgorithms.find((a) => a.algorithm_id === $("algorithm").value);
  const properties = Object.keys(algorithm?.parameters?.properties || {});
  $("algorithm-hint").textContent = algorithm ? `${algorithm.description || ""} 参数：${properties.length ? properties.join("、") : "无"}` : "";
  const profile = outputProfiles.find((p) => p.profile_id === $("output-profile").value);
  $("output-hint").textContent = profile?.kind === "directory"
    ? `正式 JSON/CSV 将保存到 ${profile.root_path}/<run_id>/；浏览器仍可下载。`
    : "只提供浏览器下载；数据库与运行状态仍保存在 WSL 运行目录。";
}

$("source").addEventListener("change", () => loadScenarios().catch((error) => { $("form-message").textContent = error.message; }));
$("algorithm").addEventListener("change", updateHints);
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
  const params = JSON.parse($("params").value || "{}");
  if (params === null || Array.isArray(params) || typeof params !== "object") throw new Error("算法参数必须是 JSON 对象");
  return {
    source_id: $("source").value,
    scenario_id: $("scenario").value,
    algorithm_id: $("algorithm").value,
    output_profile_id: $("output-profile").value,
    algorithm_params: params,
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
  $("submit").disabled = true;
  $("form-message").textContent = "正在提交…";
  try {
    const result = await api("/api/runs", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(buildRequest())});
    selectedId = result.run_id;
    $("form-message").textContent = `已创建实验 ${result.run_id}`;
    await refresh();
  } catch (error) { $("form-message").textContent = error.message; }
  finally { $("submit").disabled = false; }
});

async function refresh() {
  const generation = ++refreshGeneration;
  try {
    let list = await api(`/api/runs?limit=${pageSize}&offset=${pageOffset}`);
    if (pageOffset > 0 && pageOffset >= list.total) {
      pageOffset = Math.max(0, Math.floor((list.total - 1) / pageSize) * pageSize);
      list = await api(`/api/runs?limit=${pageSize}&offset=${pageOffset}`);
    }
    if (generation !== refreshGeneration) return;
    $("run-count").textContent = `共 ${list.total} 条实验 · ${autoRefresh ? '状态每两秒刷新' : '自动更新已暂停'}`;
    $("page-label").textContent = list.total ? `${pageOffset + 1}–${Math.min(pageOffset + pageSize, list.total)} / ${list.total}` : "0 / 0";
    $("previous-page").disabled = pageOffset === 0;
    $("next-page").disabled = pageOffset + pageSize >= list.total;
    const listHtml = list.items.map((r) => `<tr data-id="${escapeHtml(r.run_id)}" class="${r.run_id === selectedId ? "selected" : ""}">
      <td><input class="compare-run" type="checkbox" data-run="${escapeHtml(r.run_id)}" aria-label="比较实验 ${escapeHtml(r.run_id)}" ${window.ConsoleUI?.has(r.run_id) ? 'checked' : ''}></td>
      <td><button type="button" class="run-select" data-id="${escapeHtml(r.run_id)}"${r.run_id === selectedId ? ' aria-current="true"' : ''}>${escapeHtml(new Date(r.created_at).toLocaleString())}</button></td><td>${escapeHtml(r.scenario_id)}</td>
      <td>${escapeHtml(r.algorithm_id)}</td><td>${escapeHtml(r.status)}</td>
      <td>${r.TCR == null ? "—" : (Number(r.TCR) * 100).toFixed(1) + "%"}</td></tr>`).join("");
    if ($("runs").dataset.rendered !== listHtml) {
      const active = document.activeElement;
      const focusSelector = $("runs").contains(active)
        ? active.matches('.compare-run') ? `.compare-run[data-run="${CSS.escape(active.dataset.run)}"]`
          : active.matches('.run-select') ? `.run-select[data-id="${CSS.escape(active.dataset.id)}"]` : null
        : null;
      $("runs").innerHTML = listHtml;
      $("runs").dataset.rendered = listHtml;
      if (focusSelector) $("runs").querySelector(focusSelector)?.focus({preventScroll: true});
      document.querySelectorAll("#runs tr[data-id]").forEach((row) => row.addEventListener("click", (event) => {
      if (event.target.closest('.compare-run')) return;
      if (selectedId !== row.dataset.id) $("delete-files").checked = false;
      selectedId = row.dataset.id; refresh();
      }));
    }
    if (selectedId) {
      const requestedId = selectedId;
      try { const run = await api(`/api/runs/${encodeURIComponent(requestedId)}`); if (selectedId === requestedId && generation === refreshGeneration) showDetail(run); }
      catch (error) { if (selectedId === requestedId) $("detail-error").textContent = error.message; }
    }
    window.ConsoleUI?.refreshComparison();
  } catch (error) { $("form-message").textContent = error.message; }
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
  $("detail-status").textContent = run.status;
  $("detail-status").className = `badge ${["FAILED","CANCELLED","TIMED_OUT"].includes(run.status) ? "failed" : ["RUNNING","QUEUED","VERIFYING"].includes(run.status) ? "running" : ""}`;
  $("actions").hidden = false;
  $("cancel").disabled = ["SUCCEEDED","FAILED","CANCELLED","TIMED_OUT"].includes(run.status) || run.cancel_requested;
  $("delete-run").disabled = deletingRunId === run.run_id || !["SUCCEEDED","FAILED","CANCELLED","TIMED_OUT"].includes(run.status);
  $("delete-option").hidden = !(run.exports || []).some((item) => item.artifact_path);
  if ($("delete-option").hidden) $("delete-files").checked = false;
  $("export-json").hidden = run.status !== "SUCCEEDED" || !run.plan;
  $("export-csv").hidden = run.status !== "SUCCEEDED" || !run.plan;
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
    : "<li>此实验没有服务器目录文件；可使用上方浏览器下载。</li>";
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
  if (!selectedId) return;
  const runId = selectedId;
  const deleteFiles = $("delete-files").checked;
  const filesNote = deleteFiles ? "同时删除未被修改的正式 JSON/CSV 文件。" : "服务器导出文件将保留。";
  if (!window.confirm(`确定永久删除实验 ${runId} 的数据库记录吗？此操作无法撤销。${filesNote}`)) return;
  deletingRunId = runId;
  $("delete-run").disabled = true;
  try {
    const result = await api(`/api/runs/${encodeURIComponent(runId)}?delete_files=${deleteFiles}`, {method:"DELETE"});
    selectedId = null;
    clearDetail();
    $("list-message").textContent = `已删除实验 ${runId}；${result.database_compacted ? "数据库已压缩" : "数据库空闲页可复用"}。${result.files_removed ? `已删除 ${result.files_removed} 个导出文件。` : ""}${result.warnings.join("；")}`;
    await refresh();
  } catch (error) { $("detail-error").textContent = error.message; }
  finally { deletingRunId = null; if (selectedId) $("delete-run").disabled = false; }
});
$("refresh").addEventListener("click", refresh);
$("toggle-refresh").addEventListener("click", () => {
  autoRefresh = !autoRefresh;
  $("toggle-refresh").setAttribute("aria-pressed", autoRefresh ? "false" : "true");
  $("toggle-refresh").textContent = autoRefresh ? "暫停自動更新" : "繼續自動更新";
  $("run-count").textContent = autoRefresh ? "狀態每兩秒刷新一次。" : "自動更新已暫停。";
});
$("previous-page").addEventListener("click", () => { pageOffset = Math.max(0, pageOffset - pageSize); refresh(); });
$("next-page").addEventListener("click", () => { pageOffset += pageSize; refresh(); });
bootstrap();
setInterval(() => { if (autoRefresh) refresh(); }, 2000);
