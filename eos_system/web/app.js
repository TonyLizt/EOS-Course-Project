// 页面只调用 HTTP API；正式计划与指标由 Controller 核验后提供。
const $ = (id) => document.getElementById(id);
let selectedId = null;
let currentAlgorithms = [];

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
    const [health, scenarios, algorithms] = await Promise.all([
      api("/api/health"), api("/api/scenarios"), api("/api/algorithms")
    ]);
    $("health").textContent = `服务已连接 · ${health.version}`;
    $("scenario").innerHTML = scenarios.items.map((s) => `<option value="${escapeHtml(s.scenario_id)}">${escapeHtml(s.name)}</option>`).join("");
    currentAlgorithms = algorithms.items;
    $("algorithm").innerHTML = currentAlgorithms.map((a) => `<option value="${escapeHtml(a.algorithm_id)}">${escapeHtml(a.name)}</option>`).join("");
    if (!scenarios.items.length) $("form-message").textContent = "尚无登记场景，请先按启动说明生成固定小实例。";
    await refresh();
  } catch (error) {
    $("health").textContent = "服务连接失败";
    $("form-message").textContent = error.message;
  }
}

function buildRequest() {
  const params = JSON.parse($("params").value || "{}");
  if (params === null || Array.isArray(params) || typeof params !== "object") throw new Error("算法参数必须是 JSON 对象");
  return {
    scenario_id: $("scenario").value,
    algorithm_id: $("algorithm").value,
    algorithm_params: params,
    seed: Number($("seed").value),
    placement_mode: $("placement").value,
    constraints: {
      unassigned_penalty: Number($("penalty").value),
      downlink_duration_ratio: Number($("downlink").value),
      agility_profile: $("agility").value,
      non_agile_transition_s: Number($("transition").value)
    },
    objective_weights: {w_profit: 0, w_completion: 1, w_timeliness: 0, w_balance: 0},
    time_budget_s: Number($("budget").value)
  };
}

$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
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
  try {
    const list = await api("/api/runs?limit=30");
    $("runs").innerHTML = list.items.map((r) => `<tr data-id="${escapeHtml(r.run_id)}" class="${r.run_id === selectedId ? "selected" : ""}">
      <td>${escapeHtml(new Date(r.created_at).toLocaleString())}</td><td>${escapeHtml(r.scenario_id)}</td>
      <td>${escapeHtml(r.algorithm_id)}</td><td>${escapeHtml(r.status)}</td>
      <td>${r.TCR == null ? "—" : (Number(r.TCR) * 100).toFixed(1) + "%"}</td></tr>`).join("");
    document.querySelectorAll("#runs tr[data-id]").forEach((row) => row.addEventListener("click", () => {
      selectedId = row.dataset.id; refresh();
    }));
    if (selectedId) await showDetail(await api(`/api/runs/${encodeURIComponent(selectedId)}`));
  } catch (error) { $("form-message").textContent = error.message; }
}

function showDetail(run) {
  $("selected-run").textContent = run.run_id;
  $("detail-status").textContent = run.status;
  $("detail-status").className = `badge ${["FAILED","CANCELLED","TIMED_OUT"].includes(run.status) ? "failed" : ["RUNNING","QUEUED","VERIFYING"].includes(run.status) ? "running" : ""}`;
  $("actions").hidden = false;
  $("cancel").disabled = ["SUCCEEDED","FAILED","CANCELLED","TIMED_OUT"].includes(run.status) || run.cancel_requested;
  $("export-json").hidden = run.status !== "SUCCEEDED";
  $("export-csv").hidden = run.status !== "SUCCEEDED";
  $("export-json").href = `/api/runs/${encodeURIComponent(run.run_id)}/export?format=json`;
  $("export-csv").href = `/api/runs/${encodeURIComponent(run.run_id)}/export?format=csv`;
  $("detail-error").textContent = run.error ? `${run.error.code}: ${run.error.message}` : "";
  const m = run.metrics;
  $("metrics").innerHTML = m ? [
    ["完成任务", `${m.completed_tasks} / ${m.total_tasks}`], ["TCR", `${(m.TCR * 100).toFixed(1)}%`],
    ["TP", Number(m.TP).toFixed(2)], ["算法耗时", `${Number(m.RT).toFixed(3)} s`]
  ].map(([label, value]) => `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("") : "";
  $("events").innerHTML = run.events.map((e) => `<li>${escapeHtml(e.recorded_at)} · ${escapeHtml(e.event_type)}</li>`).join("");
  const assignments = run.plan?.assignments || [];
  $("assignment-count").textContent = `(${assignments.length})`;
  $("assignments").innerHTML = assignments.slice(0, 100).map((a) => `<tr><td>${escapeHtml(a.task_id)}</td><td>${escapeHtml(a.satellite_id)}</td><td>${escapeHtml(a.sat_start_time)}</td><td>${escapeHtml(a.sat_end_time)}</td></tr>`).join("");
}

$("cancel").addEventListener("click", async () => {
  if (!selectedId) return;
  try { await api(`/api/runs/${encodeURIComponent(selectedId)}/cancel`, {method:"POST"}); await refresh(); }
  catch (error) { $("detail-error").textContent = error.message; }
});
$("refresh").addEventListener("click", refresh);
bootstrap();
setInterval(refresh, 2000);
