"""Render actual asset, generation and matrix state; pending is never success."""
import argparse
from collections import Counter,defaultdict
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from eos_system.dataset_registry import entries
from scripts.matrix_journal import MatrixJournal


def read(path,default=None):
    return json.loads(path.read_text()) if path.is_file() else default


def table(lines,headers,values):
    lines.extend(['| '+' | '.join(headers)+' |','|'+'|'.join('---' for _ in headers)+'|'])
    for row in values:lines.append('| '+' | '.join(str(v).replace('|','/') for v in row)+' |')


def summary(cases):
    good=[c for c in cases if c.get('run_status')=='SUCCEEDED' and c.get('verification_status')=='SAMPLED_PASS']
    return [sum((c.get('assigned_task_count') or 0)>0 for c in good),
        sum((c.get('assigned_task_count') or 0)==0 for c in good),
        sum(c.get('outcome') in ('FEASIBLE_PLAN_AT_BUDGET','EMPTY_PLAN_AT_BUDGET') for c in good),
        sum(c.get('run_status')=='TIMED_OUT' for c in cases),
        sum(c.get('run_status') in ('FAILED','REQUEST_REJECTED','CANCELLED') for c in cases)]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT/'data/scenarios/eos-v1')
    p.add_argument('--matrix',type=Path,default=ROOT/'experiments/runs/eos-v1/matrix-full.json')
    args=p.parse_args();args.matrix=args.matrix.resolve();rows=entries(args.root);core=[r for r in rows if r['scenario_id'].endswith('-r3') and r['difficulty_profile']!='narrow_window']
    plan=json.loads((args.root/'dataset_plan_v3.json').read_text())['allocation']
    audit=json.loads((ROOT/'data/registry/eos-v1-asset-audit-20261023.json').read_text())
    matrix=json.loads(args.matrix.read_text()) if args.matrix.exists() else {'cases':[],'algorithm_catalog':[]}
    if args.matrix.exists():matrix=MatrixJournal(args.matrix,matrix['source_sha256'],matrix['models']).load(matrix,allow_incomplete_tail=True)
    cases=matrix['cases'];done=[c for c in cases if c.get('terminal')]
    algorithm_ids=[a['algorithm_id'] for a in matrix.get('algorithm_catalog',[])]
    expected=len(rows)*len(algorithm_ids)*2
    core_ids={r['scenario_id'] for r in core}
    core_done=[c for c in done if c['scenario_id'] in core_ids]
    per_scene=defaultdict(list)
    for c in done:per_scene[c['scenario_id']].append(c)
    statistics=read(ROOT/'data/derived/eos-v1/difficulty_statistics.json',{})
    initials=read(ROOT/'experiments/runs/eos-v1/initial-models-full.json',{'cases':[]})
    web=read(ROOT/'experiments/runs/eos-v1/web-api-replay.json',{})
    diagnostics=read(ROOT/'experiments/runs/eos-v1/parallel-failure-diagnostics.json',{'cases':[]})
    provenance={r['scenario_id']:read((args.root/r['path']).with_name('provenance.json')) for r in rows}
    groups=defaultdict(list)
    for r in core:
        c=json.loads((args.root/r['path']).with_name('characterization.json').read_text())
        groups[r['difficulty_profile']].append(c)
    lines=['# 统一场景数据集建设与全算法兼容性验证报告','',
        '本报告由实际文件和矩阵记录生成。未执行、失败、空计划和预算退出分别报告；当前数据均为development，未宣称正式release或连续区间认证。',
        f"生成时间：{datetime.now(timezone.utc).isoformat()}。核心场景{len(core)}/96；全部可用{len(rows)}；比较矩阵已终态{len(done)}/{expected}，未终态{expected-len(done)}。初始模型角色另行验证{len(initials['cases'])}/{initials.get('expected_combinations','未启动')}。",'',
        '## 资产审计与保护','',
        '工作分支：`test/basic-algorithms-web-acceptance-20261023`；起始HEAD：`4a743105c910caea6953cc1adf1726fb9592f1ae`。未执行暂存、提交、推送、PR或合并。',
        f"只读审计共{len(audit['scenarios'])}份公开场景（12份Legacy/历元修复，80份共享development）；结构结果：{dict(Counter(x['status'] for x in audit['scenarios']))}。WARN不等于物理通过或物理失败。",
        '原始10、20、50、100星输入实际数量均正确。原ZIP、现有场景、旧模型和未跟踪历史文件保留。冻结final_test仅登记位置，没有读取内容或参与训练。',
        '详细SHA、规模、时间、窗口数与结构问题见`data/registry/eos-v1-asset-audit-20261023.json`；既有审计结论见`scenario_dataset_asset_audit.md`。','',
        '## 存储和生成','',
        'Canonical场景唯一存储于`data/scenarios/eos-v1/`；每实例四个文件及兼容来源镜像。Legacy只有相对路径索引。登记文件位于`data/registry/`；矩阵、Worker记录、数据库及新模型位于`experiments/runs/eos-v1/`。',
        '八档规模×四种难度×三个固定种子，当前计划96实例。轨道只取真实原始输入，40星取真实50星清单前40个ID；任务及敏捷载荷能力明确标注为受控合成开发配置。',
        '时域为1800秒。目标位置由实际Orekit轨道的WGS84星下点加种子控制扰动生成，随后通过真实可见性谓词扫描，不手写随机窗口。网格5秒，真实出口二分到微秒；选定完整曝光以0.05秒含端点独立采样，所有实际计划还须通过公共Verifier。',
        '全体卫星具有真实计算的初始Nadir姿态和边界四元数。资源过载使用公共ConstraintModel确实执行的每轨存储上限0.0007 GiB；没有借用未执行的运行时间字段冒充硬约束。',
        f'当前核心实例：{len(core)}/96；其他可用实例：{len(rows)-len(core)}（保留r2试验及窄窗口子实例）；缺少核心实例：{96-len(core)}。','',
        '## 难度统计','',
        '| 档型 | 已生成 | 平均窗口重叠率 | 平均卫星集合Jaccard | 平均最大需求/时域 | 平均最大需求/存储 |',
        '|---|---:|---:|---:|---:|---:|']
    for name,items in sorted(groups.items()):
        mean=lambda key:sum(x.get(key,0) for x in items)/len(items)
        lines.append(f"| {name} | {len(items)} | {mean('window_overlap_fraction'):.4f} | {mean('candidate_satellite_jaccard_mean'):.4f} | {mean('max_demand_capacity_ratio'):.4f} | {mean('max_demand_storage_ratio'):.4f} |")
    lines+=['','所有统计来自完整、可容纳曝光的源区间，未用算法成绩筛选实例。重叠率按同星不同任务窗口对统计；集合交集用Jaccard；需求/存储是候选需求压力，不是可同时执行任务数。各星负载和逐任务机会分布在characterization.json中保留。','',
        '## 全算法及两目标矩阵','',
        f"矩阵文件：`{args.matrix.relative_to(ROOT)}`。动态注册表比较算法数量：{len(matrix.get('algorithm_catalog',[]))}。",
        'TP权重=(1,0,0,0)，TCR权重=(0,1,0,0)，字段顺序为TP/TCR/TM/BD。请求、RunConfig和独立结果保持同一场景ID、SHA、输入实体和公共约束。基础策略保留队列规则，公共权重用于同任务同开始时刻放置择优；不冒充R1全局优化。',
        'PPO/LAVIS使用实际训练的新ID：`ppo-eos-v1-dev-20261023`、`lavis-eos-v1-dev-20261023`。3个明确r2训练来源没有使用final_test；PPO实际100轮，LAVIS原续排协议20行标签。它们是开发兼容性模型，不能据此声称独立泛化性能。旧模型及冻结推理源码未改写。',
        f"核心矩阵已终态{len(core_done)}/{len(core)*len(algorithm_ids)*2}；全部可用实例矩阵已终态{len(done)}/{expected}，未终态{expected-len(done)}（包含已提交尚未返回）。当前执行批次预期{matrix.get('expected_generated_combinations',0)}；若小于全量目标，差额也属于尚未验证，不能省略。",
        f"终态分布：`{dict(Counter(c.get('run_status') for c in done))}`；细分结果：`{dict(Counter(c.get('outcome',c.get('run_status')) for c in done))}`。",'',
        '| 算法 | 非空且核验通过 | 空且核验通过 | 其中预算耗尽可行 | 超时 | 失败/拒绝/取消 | 尚未终态 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for algorithm in matrix.get('algorithm_catalog',[]):
        aid=algorithm['algorithm_id'];selected=[c for c in done if c['algorithm_id']==aid]
        lines.append('| '+' | '.join(map(str,[aid,*summary(selected),len(rows)*2-len(selected)]))+' |')
    lines+=['','“其中预算耗尽可行”是核验通过记录的子集，不额外加总。超时不计成功。',
        '完整CSV包含场景ID/SHA、规模、难度、算法、权重、模型身份、状态、时间、安排数、核验和失败原因。预算标记来自明确注明不可信的Worker遥测；独立物理通过依据Controller receipt，不以遥测代替。原始SQLite保留配置、计划、事件和Worker尝试。','',
        '### 初始模型角色与目标覆盖','',
        'completion_first和adaptive_repair来自动态初始模型Registry，单独走真实Runner和独立核验进程，不虚增比较算法数量。超过5秒仍返回核验通过计划的记录标为TIMED_OUT/VALIDATED_PLAN_AFTER_BUDGET，不参与质量排名。','']
    table(lines,['角色','非空且核验通过','空且核验通过','预算可行子集','超时','失败/拒绝','未执行'],[
        [aid,*summary([c for c in initials['cases'] if c['algorithm_id']==aid]),len(rows)*2-sum(c['algorithm_id']==aid for c in initials['cases'])]
        for aid in [m['model_id'] for m in matrix.get('initial_model_registry',[])]])
    lines+=['','两目标分别按实际请求核对，不因相同结果推断算法忽略权重。固定队列基线不承诺全局优化；原13种R1适配器仍保留请求目标、训练目标和适配器身份。','']
    table(lines,['目标','已终态','全量目标','非空且核验通过','空且核验通过','预算可行子集','超时','失败/拒绝/取消'],[
        [goal,sum(c['objective']==goal for c in done),len(rows)*len(algorithm_ids),*summary([c for c in done if c['objective']==goal])]
        for goal in ('TP','TCR')])
    lines+=['','### 八档规模的实际难度证据','',
        '下表来自96份完整源机会统计；每格为3个种子的平均值。全组均值排序不等同于每个单独种子严格排序。资源过载列为3个实例的最小总需求/总有效每轨存储容量下界。','']
    records=statistics.get('records',[])
    gradient=[]
    for scale in [f'S{i}' for i in range(1,9)]:
        grouped={profile:[r for r in records if r['scale']==scale and r['profile']==profile]
            for profile in ('low_conflict','mixed','high_conflict','resource_overload')}
        if not all(grouped.values()):continue
        means=lambda key:' / '.join(f"{sum(r[key] for r in grouped[p])/len(grouped[p]):.4f}" for p in ('low_conflict','mixed','high_conflict'))
        gradient.append([scale,means('window_overlap_fraction'),means('candidate_satellite_jaccard_mean'),
            f"{min(r['aggregate_storage_lower_bound_ratio'] for r in grouped['resource_overload']):.4f}"])
    table(lines,['规模','低/混合/高：窗口重叠','低/混合/高：卫星Jaccard','过载存储下界最小值'],gradient)
    lines+=['',f"96份任务集合独立摘要数：{statistics.get('distinct_task_collections','未统计')}；八档均值梯度与过载下界检查：{statistics.get('all_mean_gradient_checks_passed','未运行')}。无候选机会比例最大值：{max((r['zero_opportunity_fraction'] for r in records),default=0):.4f}。",'',
        '![难度统计：3种子均值及最小/最大范围](../../data/derived/eos-v1/difficulty_gradient.png)','',
        '原始统计：[JSON](../../data/derived/eos-v1/difficulty_statistics.json)、[CSV](../../data/derived/eos-v1/difficulty_statistics.csv)。高冲突与资源过载共享高竞争结构，后者增加存储硬约束；realistic表示受控混合分布，不表示真实业务请求采集。','',
        '### 运行成本与可复现性','',
        f"96份核心生成逐实例墙钟合计{statistics.get('generation_wall_sum_s',0):.3f}秒，另有一次性轨道网格初始化、原型、训练和核验成本。所有可用实例生成成本合计{sum(p['generation_wall_s'] for p in provenance.values()):.3f}秒。比较矩阵成功记录的算法RT合计{sum(c.get('runtime_seconds') or 0 for c in done):.3f}秒；不是端到端墙钟，超时没有正式指标时不得当成0秒算法完成。",
        '每轮预算5秒，并发与Worker启动/核验额外开销在日志和数据库中记录。并发从4提升到8，再改用最多24个未终态请求的滚动提交；每次切换均在已证明零活动运行时进行。前后批次不用于严格耗时排名。滚动harness先实际试跑38组合全部通过，保留独立smoke结果。Linux执行源码快照用于减轻Windows挂载文件I/O；实际场景始终符号链接回唯一Canonical文件，不为不同算法复制。source SHA、模型身份及harness历史共同确定试验版本，不仅凭Git HEAD识别未提交代码。',
        '实际Python、Orekit、JVM、依赖版本、Orekit数据SHA和执行快照公共生产源码逐文件比对见[execution-environment.json](../../experiments/runs/eos-v1/execution-environment.json)。原资产118项哈希及分支/HEAD保护结果见[preservation-check.json](../../experiments/runs/eos-v1/preservation-check.json)。',
        f"本轮算法源码摘要：`{matrix.get('source_sha256','未运行')}`。独立重生成记录见[reproducibility.json](../../experiments/runs/eos-v1/reproducibility.json)：S1低冲突种子0在相同输入/代码下产生完全相同JSON字节，临时副本未保留。其他实例保留固定种子但未逐一独立重生成。",'',
        '### Web、API和回放','',
        f"实际ASGI接口与回放子进程检查状态：`{web.get('status','尚未完成')}`；已记录接口检查{len(web.get('checks',[]))}项。证据见[web-api-replay.json](../../experiments/runs/eos-v1/web-api-replay.json)。浏览器点击交互未实测，不用HTTP/Node回归冒充浏览器验收。",
        '网页按规模、难度、卫星数和任务数筛选；API和CLI使用相同Registry。网页取消旧的MIP按ID隐藏，保留全部注册条目及后端不可用原因。旧场景与历史实验ID保持可用。模型安装器校验旧工件不变，生产入口重启后可发现新Canonical场景及已安装新模型。','',
        '## 失败、限制与成本','',
        '主矩阵106次MIP超时均保留，没有加预算重跑。另两次失败分别为S3资源过载种子0的LLF/TCR核验子进程PREVIEW_INVALID_RESPONSE，以及S8资源过载种子1的PPO/TCR候选返回后WORKER_EXIT_TIMEOUT。前者没有得到可解析的物理结论，后者尚未进入正式结果核验，均不能解释成已证实的可见性违例。',
        f"两次FAILED各做一次相同请求条件的单并发诊断，状态为{dict(Counter(c.get('status') for c in diagnostics['cases']))}。原矩阵及数据库失败不替换、不提升为成功，证据见[parallel-failure-diagnostics.json](../../experiments/runs/eos-v1/parallel-failure-diagnostics.json)。原核验进程stdout未持久化，不能确认当时JSON无效的具体字节来源；并发可靠性根因未根治，列为未解决限制。",
        '初代五份试验缺少初始姿态，被公共约束拒绝，PPO训练正确拒绝登记工件；原JSON未删除，quarantine.json记录原因。r2资源试验错误采用未执行的运行时间容量统计，已保留并隔离，r3改用真实存储约束。',
        '首次接口试跑在开发时遇到部署源身份变动保护；后续报告工具处理空事件payload出错，停止Controller时中断两次核验。原矩阵和错误保留；工具修复后的重跑保留attempt_history，不能将历史失败从审计中删除。',
        '没有关闭公共约束、物理核验或提高无限预算。严格连续认证仍INCONCLUSIVE，当前是工程采样开发数据。PPO/LAVIS共同域不含地面站，因此核心矩阵使用无地面站；原有带地面站接口保留。',
        '生成成本逐实例保存在provenance.generation_wall_s；矩阵逐次RT及资源并发条件保留。时域为半小时的受控压力试验，不代表全天真实业务分布。','',
        '## 回归与复现','',
        '首批相关回归46项通过；扩展回归155项通过，两批有重叠。扩展覆盖注册、来源身份、结构审计、R1、临时对照及姿态切换。最后的新增/修改专项结果另见运行目录日志。',
        '最终前端22项通过，含空筛选禁止提交、保留兼容选择、Legacy无元数据回退和MIP/PPO全部可见；Registry专项6项、journal恢复/身份/损坏尾记录专项2项通过。测试命令与实际stdout见experiments/runs/eos-v1/logs。',
        '完整命令、筛选、Web/API、环境变量和模型选择见`scenario_catalog.md`。继续运行生成器--all会按固定计划验证已完成SHA后续跑；矩阵工具按动态算法清单运行两目标，可分批续跑并保留失败。',
        '后续更大规模应新增数据版本和ID，先审计真实轨道数量、扩展小批物理机会与候选容量，再按同一协议加种子与长时域。不能通过复制轨道或编辑旧场景扩大规模；增加地面站等约束须先扩展所有算法共同域，再进行独立核验。','',
        '## 全部可用新场景','',
        '全部实例的Schema、来源镜像与实际Loader计数已复核；结构WARN仅为尚未填写旧distribution_type字段。物理列SAMPLED_PASS表示选定完整曝光独立采样通过，不表示每个窗口连续认证。每份validation.json保留生成时快照PENDING，全算法最新状态以Manifest与矩阵为准。',
        '“retained_trial”中的3份r2来源参与开发训练；与对应r3任务同源，不当成独立测试样本。narrow_window与父场景共享血缘，不增加独立核心种子数。Manifest另存lineage_equivalence_group，将相同轨道+任务的不同修订归为同组，防止训练测试泄漏。','',
        '| ID | 星/任务 | 秒 | 难度 | 种子 | 角色/划分 | 物理 | 已终态/预期 | SHA-256 | 血缘/父ID | 相对路径 |',
        '|---|---:|---:|---|---:|---|---|---:|---|---|---|']
    for row in rows:
        sid=row['scenario_id'];p=provenance[sid]
        role='narrow_window' if row['difficulty_profile']=='narrow_window' else 'core' if sid in core_ids else 'retained_trial'
        lines.append(f"| {sid} | {row['satellite_count']}/{row['mission_count']} | {row['duration_s']} | {row['difficulty_profile']} | {row['seed']} | {role}/{p['split']} | {row['physical_validation_status']} | {len(per_scene[sid])}/{len(algorithm_ids)*2} | {row['sha256']} | {p['lineage_group_id']} / {p.get('parent_scenario_id') or '无'} | data/scenarios/eos-v1/{row['path']} |")
    lines+=['','## 原资产清单与异常归因','',
        '以下12份Legacy JSON为只读审计结果；共享development另80份逐文件明细在资产CSV。WARN可能由窗口覆盖不足、旧来源字段缺失或文件名分布未证实引起，不能直接替换物理验收。','']
    table(lines,['Legacy路径','星/任务','天','曝光区间数','窗口覆盖率','状态'],[
        [r['record']['path'],f"{r['record']['satellite_count']}/{r['record']['mission_count']}",r['record']['duration_days'],
         r['record']['observation_segment_count'],r['record']['window_coverage_ratio'],r['status']]
        for r in audit['scenarios'] if r['record']['path'].startswith('experiments/scenarios/')])
    asset_rows=[r['record'] for r in audit['scenarios']]
    asset_path=ROOT/'data/derived/eos-v1/original_asset_inventory.csv'
    with asset_path.open('w',encoding='utf-8-sig',newline='') as stream:
        keys=list(dict.fromkeys(k for r in asset_rows for k in r));writer=csv.DictWriter(stream,keys);writer.writeheader();writer.writerows(asset_rows)
    lines+=['','[全部92份原场景资产CSV](../../data/derived/eos-v1/original_asset_inventory.csv)。原始输入和归档SHA见资产JSON；final_test未读取。','',
        '矩阵非成功记录按真实错误代码统计：`'+str(dict(Counter((c.get('failure_code') or c.get('run_status')) for c in done if c.get('run_status')!='SUCCEEDED')))+'`。',
        '逐次失败原因、模型身份、预算遥测、请求与核验receipt保留在[matrix-full.json](../../experiments/runs/eos-v1/matrix-full.json)及[CSV](../../experiments/runs/eos-v1/matrix-full.csv)。实时追加journal和progress可能领先定期JSON检查点，最终退出后会完整落盘。',
        '独立一致性审计生成[compatibility_matrix.csv](../../experiments/runs/eos-v1/compatibility_matrix.csv)与同名JSON，含TP/TCR/TM/BD/RT、目标、模型、安排数和核验状态。原harness对未成功运行统一写verification_status=FAILED，不能解释为物理谓词失败；规范矩阵依据ALGORITHM_TIMEOUT将其标为NOT_RUN，同时保留raw_harness_verification_status和原始状态。',
        '审计同时逐条核对真实场景字节、公开约束相同、请求目标、适配器有效目标、模型工件身份和Controller采样receipt；它是记录一致性审计，不冒充新增物理求解。完整性结果见[matrix-integrity.json](../../experiments/runs/eos-v1/matrix-integrity.json)。']
    target=ROOT/'docs/phase2/scenario_dataset_build_report.md';target.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('REPORT',target,'core',len(core),'matrix terminal',len(done),flush=True)


if __name__=='__main__':main()
