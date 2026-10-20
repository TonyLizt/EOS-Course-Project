"""面向实验统计的只读导出：一行一次运行，明细与汇总分离，不改动原结果。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
import statistics
import zipfile
from typing import Literal

from pydantic import Field
from .contracts import StrictModel
from .exporting import require_exportable_record
from .result_scoring import score_run, POLICY

SCHEMA = 'eos-statistics-v1'
MAX_RUNS = 500
MAX_ASSIGNMENTS = 100000
MAX_BYTES = 64 * 1024 * 1024
METRICS = ('completed_tasks', 'total_tasks', 'TP', 'TCR', 'BD', 'TM', 'RT')
SUMMARY_FIELDS = (
    'schema_version', 'experiment_id', 'run_id', 'removed_at', 'created_at', 'started_at', 'finished_at',
    'status', 'metrics_usable', 'metrics_unavailable_reason', 'error_code', 'error_message',
    'source_id', 'scenario_id', 'scenario_sha256', 'lineage_group_id', 'scenario_physics_version',
    'attitude_model_version', 'algorithm_id', 'algorithm_version', 'algorithm_code_sha',
    'model_id', 'model_version', 'model_sha256', 'seed', 'time_budget_s', 'schedule_model',
    'placement_mode', 'worker_limit', 'active_at_dispatch', 'execution_mode', 'result_kind',
    'physical_validation_status', 'continuous_certification_status', 'validation_scope',
    'metric_schema_version', 'condition_group_id', 'replicate_group_id',
    'algorithm_params_sha256', 'algorithm_params_json', 'objective_weights_json', 'constraints_json',
    *METRICS, 'ranking_score', 'ranking_policy', 'score_total_priority',
)
ASSIGNMENT_FIELDS = ('experiment_id', 'run_id', 'scenario_id', 'algorithm_id', 'task_id', 'satellite_id',
    'sensor_id', 'sat_window_id', 'orbit_number', 'sat_start_time', 'sat_end_time',
    'ground_station_id', 'gs_window_id', 'gs_start_time', 'gs_end_time')


class StatisticsExportRequest(StrictModel):
    experiment_ids: list[str] = Field(min_length=1, max_length=100)
    format: Literal['csv', 'zip'] = 'csv'
    include_removed: bool = False


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def safe_cell(value):
    """Excel将不可信文本视为文本；真实数值（含负数）保持数值类型。"""
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def csv_bytes(rows, fields):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({k: safe_cell(v) for k, v in row.items()})
        if stream.tell() > MAX_BYTES:
            raise OverflowError('导出超过64MB，请减少所选实验分批导出')
    result = stream.getvalue().encode('utf-8-sig')
    if len(result) > MAX_BYTES:
        raise OverflowError('导出超过64MB，请减少所选实验分批导出')
    return result


def execution_resources(record):
    events = [e.get('payload') or {} for e in record.get('events', [])
              if e.get('event_type') == 'EXECUTION_RESOURCES']
    return events[-1] if events else record.get('execution_resources') or {}


def build_row(item):
    """失败/取消/历史无可信凭据仍占一行，但其指标留空，不能伪造零分。"""
    record = item['record']; config = record['config']
    source = config.get('scenario_provenance') or {}; model = config.get('model_provenance') or {}
    physical = record.get('preview_validation') or {}; continuous = record.get('continuous_certification') or {}
    resources = execution_resources(record); params = config.get('algorithm_params') or {}
    usable = False; reason = ''
    if record['status'] != 'SUCCEEDED':
        reason = '运行未成功结束'
    else:
        try:
            require_exportable_record(record)
            metrics = record.get('metrics') or {}
            if not all(isinstance(metrics.get(k), (int, float)) and math.isfinite(metrics[k]) for k in METRICS):
                raise ValueError('缺少有限的完整指标')
            usable = True
        except (ValueError, TypeError, KeyError) as exc:
            reason = str(exc)
    metrics = (record.get('metrics') or {}) if usable else {}
    score = score_run(record) if usable else None
    row = dict(schema_version=SCHEMA, experiment_id=item['experiment_id'], run_id=record['run_id'],
        removed_at=item.get('removed_at'), created_at=record.get('created_at'),
        started_at=(record.get('attempts') or [{}])[0].get('started_at'), finished_at=record.get('finished_at'),
        status=record['status'], metrics_usable=usable, metrics_unavailable_reason=reason,
        error_code=(record.get('error') or {}).get('code'), error_message=(record.get('error') or {}).get('message'),
        source_id=config.get('source_id'), scenario_id=config.get('scenario_id'), scenario_sha256=config.get('scenario_sha256'),
        lineage_group_id=source.get('lineage_group_id'), scenario_physics_version=source.get('scenario_physics_version'),
        attitude_model_version=physical.get('attitude_model_version') or source.get('attitude_model_version'),
        algorithm_id=config.get('algorithm_id'), algorithm_version=config.get('algorithm_version'),
        algorithm_code_sha=config.get('algorithm_code_sha'), model_id=model.get('model_id'),
        model_version=model.get('model_version'), model_sha256=model.get('model_sha256'),
        seed=config.get('seed'), time_budget_s=config.get('time_budget_s'), schedule_model=config.get('schedule_model'),
        placement_mode=config.get('placement_mode'), worker_limit=resources.get('worker_limit'),
        active_at_dispatch=resources.get('active_at_dispatch'), execution_mode=config.get('execution_mode'),
        result_kind=record.get('result_kind'), physical_validation_status=physical.get('status'),
        continuous_certification_status=continuous.get('status'), validation_scope=physical.get('validation_scope'),
        metric_schema_version=metrics.get('metric_schema_version'),
        algorithm_params_sha256=fingerprint(params), algorithm_params_json=canonical(params),
        objective_weights_json=canonical(config.get('objective_weights') or {}),
        constraints_json=canonical(config.get('constraints') or {}),
        ranking_score=score['value'] if score else None, ranking_policy=score['policy'] if score else POLICY,
        score_total_priority=score['total_priority'] if score else None,
        **{k: metrics.get(k) for k in METRICS})
    # 同条件组用于成对比较；重复组仅去掉种子，再加入算法参数/权重身份。
    conditions = {k: row.get(k) for k in ('source_id', 'scenario_sha256', 'scenario_physics_version',
        'attitude_model_version', 'algorithm_code_sha', 'schedule_model', 'placement_mode', 'worker_limit', 'execution_mode',
        'objective_weights_json', 'constraints_json', 'time_budget_s')}
    row['condition_group_id'] = fingerprint(conditions | {'seed': row['seed']})
    row['replicate_group_id'] = fingerprint(conditions | {k: row[k] for k in
        ('algorithm_id', 'algorithm_version', 'algorithm_params_sha256', 'model_sha256')})
    return row


def aggregate_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['replicate_group_id']].append(row)
    # 指标口径变更时拆组；单一口径下保留失败行计数，避免只报告成功样本。
    separated = []
    for members in groups.values():
        versions = {r.get('metric_schema_version') for r in members if r['metrics_usable']}
        if len(versions) <= 1:
            separated.append((next(iter(versions), None), members))
        else:
            by_version = defaultdict(list)
            for row in members:
                by_version[row.get('metric_schema_version')].append(row)
            separated.extend(by_version.items())
    result = []
    keys = ('replicate_group_id', 'source_id', 'scenario_id', 'scenario_sha256', 'lineage_group_id',
            'algorithm_id', 'algorithm_version', 'algorithm_params_sha256', 'model_id', 'model_sha256',
            'schedule_model', 'time_budget_s', 'worker_limit', 'execution_mode', 'algorithm_code_sha',
            'attitude_model_version', 'metric_schema_version')
    for version, members in separated:
        valid = [r for r in members if r['metrics_usable']]
        row = {k: members[0].get(k) for k in keys}
        row['metric_schema_version'] = version
        row.update(run_count=len(members), valid_result_count=len(valid),
            success_status_count=sum(r['status'] == 'SUCCEEDED' for r in members),
            failed_count=sum(r['status'] in ('FAILED', 'TIMED_OUT') for r in members),
            cancelled_count=sum(r['status'] == 'CANCELLED' for r in members),
            unfinished_count=sum(r['status'] not in ('SUCCEEDED','FAILED','TIMED_OUT','CANCELLED') for r in members),
            unique_seed_count=len({r['seed'] for r in members}),
            seeds_json=canonical(sorted({r['seed'] for r in members if r['seed'] is not None})))
        for metric in ('TP', 'TCR', 'BD', 'TM', 'RT', 'ranking_score'):
            values = [r[metric] for r in valid if isinstance(r.get(metric), (int, float)) and math.isfinite(r[metric])]
            row[metric+'_n'] = len(values)
            row[metric+'_mean'] = statistics.mean(values) if values else None
            row[metric+'_std_sample'] = statistics.stdev(values) if len(values) > 1 else None
        result.append(row)
    fields = [*keys, 'run_count','valid_result_count','success_status_count','failed_count',
              'cancelled_count','unfinished_count','unique_seed_count','seeds_json']
    fields += [metric+suffix for metric in ('TP','TCR','BD','TM','RT','ranking_score')
               for suffix in ('_n','_mean','_std_sample')]
    return result, fields


EXPORT_README = '''# EOS 实验统计包 v1

summary.csv：每次算法运行一行，包括失败、取消及未完成状态。指标只来自成功且具有有效核验凭据的结果；缺失用空值，真实0保留。
aggregates.csv：同场景、代码、约束、预算、初始模型、并发上限及算法/参数/模型权重分组；仅跨种子合并。提供总记录数、有效结果数、状态计数、均值、样本标准差及各指标样本数。少于2个有效值时标准差留空。同种子重复运行不是独立随机重复；请检查unique_seed_count。不要把不同场景/谱系的行直接视为独立论文重复。
assignments.csv：有效结果的逐任务明细，不重复汇总指标；不要用它的行数重复累加summary中的TP/TCR。
configurations.json：运行配置快照，含模型和源码身份，省略本机输入/输出绝对路径。配置JSON没有Excel文本转义。
manifest.json：时间、范围、数量及包内各文件的SHA-256。

CSV为UTF-8 BOM，Excel可直接打开；英文稳定列名便于pandas。TCR/BD/TM为原始比例，RT单位秒；created_at/started_at/finished_at保留ISO时间。统计未纳入RV。文本公式前缀经转义，数值类型不受影响。
综合分=70*TCR+20*TP/场景总优先级+10*(1-TM)，耗时不计分，总优先级0时收益项0。不同条件不可混排，比较耗时请串行运行。
工程结果为物理采样通过，不是连续认证。历史无有效凭据结果仍列出状态和原因，但不进入均值。临时对照不入库，不在该持久统计包内。默认仅导出当前成员，可显式选择包含已移除历史；请通过removed_at筛选后再作正式统计。
该包不包含原始场景或模型权重；它们请按谱系与SHA另行分发。
'''


def render_statistics(items, format_name, experiment_ids, include_removed=False):
    if len(items) > MAX_RUNS:
        raise OverflowError('一次最多导出500次算法运行，请分批选择实验')
    rows = [build_row(item) for item in items]
    summary = csv_bytes(rows, SUMMARY_FIELDS)
    if format_name == 'csv':
        return summary
    aggregate, fields = aggregate_rows(rows)
    assignment_rows = []; configurations = []
    for item, row in zip(items, rows):
        record = item['record']; config = dict(record['config'])
        for field in ('scenario_path', 'output_root'):
            config.pop(field, None)
        configurations.append(dict(experiment_id=item['experiment_id'], run_id=record['run_id'],
            removed_at=item.get('removed_at'), config=config))
        if row['metrics_usable']:
            for assignment in record['plan']['assignments']:
                assignment_rows.append({**{k: row[k] for k in ('experiment_id','run_id','scenario_id','algorithm_id')},
                    **{k: assignment.get(k) for k in ASSIGNMENT_FIELDS if k not in ('experiment_id','run_id','scenario_id','algorithm_id')}})
                if len(assignment_rows) > MAX_ASSIGNMENTS:
                    raise OverflowError('任务明细超过10万行，请分批导出')
    files = {'summary.csv': summary, 'aggregates.csv': csv_bytes(aggregate, fields),
             'assignments.csv': csv_bytes(assignment_rows, ASSIGNMENT_FIELDS),
             'configurations.json': (json.dumps(configurations, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode(),
             'README.md': EXPORT_README.encode()}
    if sum(map(len, files.values())) > MAX_BYTES:
        raise OverflowError('导出超过64MB，请分批选择实验')
    manifest = dict(schema_version=SCHEMA, exported_at=datetime.now(timezone.utc).isoformat(),
        experiment_ids=experiment_ids, include_removed=include_removed, run_count=len(rows),
        usable_result_count=sum(r['metrics_usable'] for r in rows), assignment_count=len(assignment_rows),
        scope='persisted experiment snapshot; finite physical sampling is not continuous certification',
        files={name: {'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()})
    files['manifest.json'] = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,data in files.items():
            archive.writestr(name,data)
    return stream.getvalue()
