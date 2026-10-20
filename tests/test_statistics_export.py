"""统计导出验收：保留失败行、核验门禁、可复算汇总和包内校验。"""
import csv
import hashlib
import io
import json
import unittest
import zipfile
from test_integrated_replay import fixture
from eos_system.statistics_export import aggregate_rows, build_row, csv_bytes, render_statistics

class StatisticsExportTests(unittest.TestCase):
    def test_verified_export_and_zip_manifest(self):
        with fixture() as f:
            eid='legacy-'+f.run_id
            response=f.client.post('/api/statistics/export',json={'experiment_ids':[eid,eid], 'format':'zip'})
            self.assertEqual(response.status_code,200,response.text)
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                self.assertEqual(len(z.namelist()),6)
                manifest=json.loads(z.read('manifest.json'))
                self.assertEqual(manifest['run_count'],1)
                self.assertEqual(manifest['usable_result_count'],1)
                for name,entry in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),entry['sha256'])
                rows=list(csv.DictReader(io.StringIO(z.read('summary.csv').decode('utf-8-sig'))))
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['completed_tasks'],'2')
                self.assertNotIn('RV',rows[0])
                self.assertEqual(len(list(csv.DictReader(io.StringIO(z.read('assignments.csv').decode('utf-8-sig'))))),2)
                config=json.loads(z.read('configurations.json'))[0]['config']
                self.assertNotIn('scenario_path',config)
                self.assertNotIn('output_root',config)
                aggregates=list(csv.DictReader(io.StringIO(z.read('aggregates.csv').decode('utf-8-sig'))))
                self.assertEqual(aggregates[0]['TCR_std_sample'],'')
            self.assertEqual(f.client.post('/api/statistics/export',json={'experiment_ids':[]}).status_code,422)
            self.assertEqual(f.client.post('/api/statistics/export',json={'experiment_ids':['missing']}).status_code,404)
            f.app.state.experiments.remove(eid,f.config.algorithm_id)
            active=f.client.post('/api/statistics/export',json={'experiment_ids':[eid]}).content
            self.assertEqual(len(list(csv.DictReader(io.StringIO(active.decode('utf-8-sig'))))),0)
            history=f.client.post('/api/statistics/export',json={'experiment_ids':[eid],'include_removed':True}).content
            self.assertTrue(list(csv.DictReader(io.StringIO(history.decode('utf-8-sig'))))[0]['removed_at'])

    def test_failed_and_untrusted_rows_do_not_supply_metrics(self):
        with fixture() as f:
            record=dict(f.db.get_run(f.run_id))
            record['status']='FAILED'
            row=build_row({'record':record,'experiment_id':'e'})
            self.assertFalse(row['metrics_usable'])
            self.assertIsNone(row['TCR'])
            # 普通字典丢失Storage核验身份，即使写着SUCCEEDED也不能冒充可信结果。
            record['status']='SUCCEEDED'
            row=build_row({'record':record,'experiment_id':'e'})
            self.assertFalse(row['metrics_usable'])

    def test_aggregate_zero_failures_and_metric_schema_isolation(self):
        def row(seed,value,status='SUCCEEDED',version='v1'):
            return dict(replicate_group_id='r',seed=seed,status=status,metrics_usable=status=='SUCCEEDED',
                        metric_schema_version=version,TCR=value,TP=value,BD=value,TM=value,RT=value,ranking_score=value)
        rows,fields=aggregate_rows([row(1,0),row(2,1),row(3,None,'FAILED')])
        self.assertEqual(rows[0]['run_count'],3)
        self.assertEqual(rows[0]['valid_result_count'],2)
        self.assertEqual(rows[0]['failed_count'],1)
        self.assertEqual(rows[0]['TCR_mean'],.5)
        self.assertAlmostEqual(rows[0]['TCR_std_sample'],2**-.5)
        rows,_=aggregate_rows([row(1,0),row(2,1,version='v2')])
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['TCR_n']==1 for r in rows))

    def test_excel_formula_text_is_escaped_without_changing_numbers(self):
        data=csv_bytes([{'text':'=1+1','value':-2}],['text','value'])
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        row=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))[0]
        self.assertEqual(row['text'],"'=1+1")
        self.assertEqual(row['value'],'-2')

if __name__=='__main__':unittest.main()
