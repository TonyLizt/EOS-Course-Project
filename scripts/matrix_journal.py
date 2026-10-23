"""Append actual case transitions; checkpoint large reports without quadratic IO."""
import csv
import io
import json
from pathlib import Path
import time
import uuid


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    pending=path.with_name(path.name+'.pending-'+uuid.uuid4().hex)
    with pending.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
    pending.replace(path)


class MatrixJournal:
    def __init__(self,path,source,models):
        self.path=Path(path);self.journal=self.path.with_suffix('.jsonl')
        self.source=source;self.models=models;self.versions={};self.last_checkpoint=0

    def load(self,fallback,*,allow_incomplete_tail=False):
        has_checkpoint=self.path.exists()
        report=json.loads(self.path.read_text()) if has_checkpoint else fallback
        by_key={c['key']:c for c in report['cases']}
        if self.journal.exists():
            with self.journal.open(encoding='utf-8') as stream:
                for line in stream:
                    try:record=json.loads(line)
                    except json.JSONDecodeError:
                        # Read-only progress viewers may observe an append in flight.
                        # Resume/append callers keep the strict default and stop.
                        if allow_incomplete_tail and not line.endswith('\n'):break
                        raise
                    if record['source_sha256']!=self.source or record['models']!=self.models:
                        raise ValueError('matrix journal source/model identity mismatch')
                    if 'metadata' in record and not has_checkpoint:
                        report.update(record['metadata'])
                    if 'case' in record:by_key[record['case']['key']]=record['case']
        report['cases']=list(by_key.values())
        if report['source_sha256']!=self.source or report['models']!=self.models:
            raise ValueError('matrix checkpoint identity mismatch')
        return report

    def persist(self,report,*,force=False):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        base=dict(source_sha256=self.source,models=self.models)
        fresh=not self.journal.exists()
        with self.journal.open('a',encoding='utf-8') as stream:
            if fresh:
                stream.write(json.dumps(dict(base,metadata={k:v for k,v in report.items() if k!='cases'}),ensure_ascii=False)+'\n')
            for case in report['cases']:
                version=(case.get('run_id'),case.get('terminal'),case.get('run_status'),len(case.get('attempt_history',[])))
                if self.versions.get(case['key'])!=version:
                    stream.write(json.dumps(dict(base,case=case),ensure_ascii=False,allow_nan=False)+'\n')
                    self.versions[case['key']]=version
        report['completed_combinations']=sum(c.get('terminal',False) for c in report['cases'])
        report['unexecuted_combinations']=report['expected_generated_combinations']-report['completed_combinations']
        counts={}
        for c in report['cases']:
            if c.get('terminal'):counts[c['run_status']]=counts.get(c['run_status'],0)+1
        atomic_json(self.path.with_suffix('.progress.json'),dict(source_sha256=self.source,
            completed=report['completed_combinations'],expected=report['expected_generated_combinations'],
            pending=report['unexecuted_combinations'],statuses=counts,journal=self.journal.name))
        if force or time.monotonic()-self.last_checkpoint>=300:
            atomic_json(self.path,report);self.last_checkpoint=time.monotonic()
        if force:
            flat=[{k:v for k,v in c.items() if k!='detail'} for c in report['cases']]
            if flat:
                keys=list(dict.fromkeys(k for c in flat for k in c));text=io.StringIO();writer=csv.DictWriter(text,keys)
                writer.writeheader();writer.writerows([{k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in c.items()} for c in flat])
                self.path.with_suffix('.csv').write_text(text.getvalue(),encoding='utf-8-sig')
