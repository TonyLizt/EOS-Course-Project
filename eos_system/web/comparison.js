/* Shared comparison rules: no synthetic aggregate score, no cross-condition winners. */
(function (root) {
  'use strict';
  const metrics = [
    ['TP', 1, '总收益'], ['TCR', 1, '完成率'], ['BD', 1, '负载均衡度'],
    ['TM', -1, '归一化等待时间'], ['RT', -1, '算法耗时 / 秒'], ['RV', -1, '收益样本方差']
  ];
  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])]));
    return value;
  }
  function conditions(run) {
    const c = run.config || {};
    return canonical({scenario_sha256: c.scenario_sha256, scenario_physics_version: c.scenario_provenance?.scenario_physics_version,
      algorithm_code_sha: c.algorithm_code_sha, constraints: c.constraints, placement_mode: c.placement_mode,
      seed: c.seed, time_budget_s: c.time_budget_s, objective_weights: c.objective_weights,
      metric_schema_version: run.metrics?.metric_schema_version ?? null,
      continuous_certification_status: run.continuous_certification?.status ?? 'unknown',
      audit_version: run.continuous_certification?.audit_version ?? null,
      certification_evidence_kind: run.continuous_certification?.evidence_kind ?? null});
  }
  function identified(run) {
    const c = run.config || {};
    return !!(c.scenario_sha256 && c.algorithm_code_sha && c.constraints && c.objective_weights &&
      c.placement_mode && c.seed != null && c.time_budget_s != null && c.scenario_provenance?.scenario_physics_version);
  }
  function groupRuns(runs) {
    const groups = new Map();
    for (const run of runs) {
      const key = identified(run) ? JSON.stringify(conditions(run)) : 'unknown:' + run.run_id;
      if (!groups.has(key)) groups.set(key, {identified: identified(run), conditions: conditions(run), runs: []});
      groups.get(key).runs.push(run);
    }
    return [...groups.values()];
  }
  function best(group, metric, direction) {
    if (!group.identified || group.runs.some(r => r.continuous_certification?.status === 'INCONCLUSIVE') || group.runs.filter(r => r.status === 'SUCCEEDED').length < 2) return null;
    const values = group.runs.filter(r => r.status === 'SUCCEEDED').map(r => r.metrics?.[metric]).filter(v => typeof v === 'number' && Number.isFinite(v));
    if (values.length < 2) return null;
    return direction > 0 ? Math.max(...values) : Math.min(...values);
  }
  const api = {metrics, canonical, conditions, identified, groupRuns, best};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RunComparison = api;
})(typeof window === 'undefined' ? globalThis : window);
