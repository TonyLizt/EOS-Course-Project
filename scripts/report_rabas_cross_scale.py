"""Render preserved study evidence; pass the evidence directory as argv[1]."""
import json,statistics,collections,sys
from pathlib import Path
base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp/rabas-cross-scale-evidence')

def avg(v):return statistics.mean(v) if v else float('nan')
def std(v):return statistics.pstdev(v) if v else float('nan')
def fmt(v,d=2):return f'{v:.{d}f}' if v==v else '—'
def report_held(directory="heldout"):
 rows=json.loads((base/directory/'results.json').read_text());out=[]
 for r in rows:
  if r['status']=='PUBLIC_PASS' and r.get('runtime',0)>r['budget']:
   r['diagnostic_returned_count']=r['completed'];r['completed']=None;r['status']='OVER_BUDGET'
 (base/directory/'results-classified.json').write_text(json.dumps(rows,indent=2))
 out+=['## 独立合成测试完整结果','', '注意：以下全部是 **PUBLIC_MODEL_ONLY，非正式物理认证**。每规模预选2个独立采样结构族，确定性算法各1次；Completion First、SA、GA、ACO每实例使用41/43/47三个种子。均值/标准差只对成功返回且公共重放通过的运行计算；分母及所有超时/不可用行完整保留，缺失值不算0完成，也不算被RABAS击败。RT为实际Solver时间。','', '| 规模 | 算法 | 有效/总运行 | 完成数均值±σ | TCR均值±σ | TP均值±σ | TM均值±σ | BD均值±σ | RT均值±σ(s) | ≥95%预算 | 超时 |', '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
 for n in (20,100,300):
  for aid in dict.fromkeys(r['algorithm'] for r in rows):
   rr=[r for r in rows if r['n']==n and r['algorithm']==aid];valid=[r for r in rr if r['status']=='PUBLIC_PASS']
   comp=[r['completed'] for r in valid];tcr=[100*r['metrics']['task_completion_rate'] for r in valid];tp=[r['metrics']['task_profit'] for r in valid];rt=[r['runtime'] for r in valid]
   ms=lambda vals:f'{fmt(avg(vals))}±{fmt(std(vals))}' if vals else '—'
   out.append(f"| { {20:'Small',100:'Medium',300:'Large'}[n]} | {aid} | {len(valid)}/{len(rr)} | {ms(comp)} | {ms(tcr)}% | {ms(tp)} | {ms([r['metrics']['timeliness_metric'] for r in valid])} | {ms([r['metrics']['balance_degree'] for r in valid])} | {ms(rt)} | {sum(r.get('budget_used',0)>=.95 for r in rr)}/{len(rr)} | {sum(r['status']=='TIMED_OUT' for r in rr)} |")
 out+=['','初始解分组：SA/GA/ACO消费 completion_first 初始解；其他算法空计划或自行重建。旧Adapter也可能计算随后被算法丢弃的初始解，其时间仍计入预算，未修改基线以消除此项目既有行为。','', '### 每个预选实例及全部运行', '', '| 族 | 任务 | 算法 | seed:完成数/状态 |','|---|---:|---|---|']
 for (fam,n,aid),group in __import__('itertools').groupby(rows,key=lambda r:(r['family'],r['n'],r['algorithm'])):
  rr=list(group);out.append(f"| {fam} | {n} | {aid} | "+'; '.join(f"{r['seed']}:{r.get('completed','—')}/{r['status']}" for r in rr)+' |')
 out+=['','### RABAS对各算法的完成数胜/平/负（按实例、先平均种子）','','只有该实例双方所有预定种子都有效时才计比较；否则记不可比。共2实例/规模，样本很少，不宣称统计显著。','','| 算法 | Small 胜/平/负/不可比 | Medium | Large |','|---|---|---|---|']
 for aid in dict.fromkeys(r['algorithm'] for r in rows):
  if aid=='rabas':continue
  cells=[]
  for n in (20,100,300):
   counts=[0,0,0,0]
   for fam in dict.fromkeys(r['family'] for r in rows):
    aa=[r for r in rows if r['algorithm']=='rabas' and r['n']==n and r['family']==fam];bb=[r for r in rows if r['algorithm']==aid and r['n']==n and r['family']==fam]
    if any(r['status']!='PUBLIC_PASS' for r in aa+bb):counts[3]+=1;continue
    diff=avg([r['completed'] for r in aa])-avg([r['completed'] for r in bb]);counts[0 if diff>0 else 2 if diff<0 else 1]+=1
   cells.append('/'.join(map(str,counts)))
  out.append('| '+aid+' | '+' | '.join(cells)+' |')
 out+=['','### 场景身份与结构','','| 族/任务数 | 星数 | 窗口数 | 共享任务数 | 地面站 | SHA-256 |','|---|---:|---:|---:|---:|---|']
 seen=set()
 for r in rows:
  key=r['family'],r['n']
  if key in seen or 'sha256' not in r:continue
  seen.add(key);out.append(f"| {key[0]}/{key[1]} | {r['satellites']} | {r['windows']} | {r['shared_tasks']} | {r['ground_stations']} | `{r['sha256']}` |")
 return '\n'.join(out)+'\n'

def report_val():
 rows=json.loads((base/'val_freeze.json').read_text());out=['## 验证集完整消融（冻结前）','','这些是最终默认调整前的同版本机制消融：参考行 `default` 使用 future_aware_rank=true。根据 old_rank 行选择最终默认false。各项为单因素开关；不是完全因子分析，不能将差值直接相加。300任务受墙钟影响，即使不改变实际自适应配置的开关也出现波动，因此不能把每一个差异都归因于机制。','','| 族 | 任务 | 变体 | 完成 | RT(s) | 公共核验 | 机会估算检查 | 构造器调用 | 中标 |','|---|---:|---|---:|---:|---:|---:|---:|---:|']
 for r in rows:
  s=r['stats']['rabas']['stats'];out.append(f"| {r['family']} | {r['n']} | {r['variant']} | {r['completed']} | {r['metrics']['runtime_efficiency']:.3f} | {s['public_constraint_checks']} | {s.get('opportunity_discrete_checks',0)} | {s['constructor_calls']} | {s['awards']} |")
 return '\n'.join(out)+'\n'
if __name__=='__main__':
 if (base/'heldout/results.json').exists():(base/'heldout-tables.md').write_text(report_held())
 if (base/'heldout-final/results.json').exists():(base/'heldout-final-tables.md').write_text(report_held('heldout-final'))
 (base/'validation-tables.md').write_text(report_val())
