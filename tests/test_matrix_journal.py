import json
from pathlib import Path
import tempfile
import unittest
from scripts.matrix_journal import MatrixJournal


class MatrixJournalTests(unittest.TestCase):
    def test_recovers_transitions_after_checkpoint_without_losing_failed_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'matrix.json';models={'ppo':'actual-ID'}
            report=dict(source_sha256='source',models=models,cases=[],expected_generated_combinations=1)
            journal=MatrixJournal(path,'source',models)
            case=dict(key='scene/algorithm/TP',run_id='first',terminal=False)
            report['cases'].append(case);journal.persist(report)
            case.update(terminal=True,run_status='FAILED',failure_reason='actual failure')
            journal.persist(report)
            self.assertFalse(json.loads(path.read_text())['cases'][0]['terminal'])
            recovered=MatrixJournal(path,'source',models).load(dict(report,cases=[]))
            self.assertEqual(recovered['cases'][0]['run_status'],'FAILED')
            recovered['cases'][0].update(attempt_history=[dict(run_status='FAILED',run_id='first')],
                run_id='retry',terminal=True,run_status='SUCCEEDED',assigned_task_count=1)
            journal.persist(recovered,force=True)
            again=MatrixJournal(path,'source',models).load(dict(report,cases=[]))
            self.assertEqual(again['cases'][0]['attempt_history'][0]['run_status'],'FAILED')
            self.assertTrue(path.with_suffix('.csv').exists())

    def test_identity_change_and_incomplete_journal_never_become_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'matrix.json';base=dict(source_sha256='A',models={},cases=[],expected_generated_combinations=0)
            MatrixJournal(path,'A',{}).persist(base)
            with self.assertRaisesRegex(ValueError,'identity'):
                MatrixJournal(path,'B',{}).load(base)
            with path.with_suffix('.jsonl').open('a') as stream:stream.write('{incomplete')
            with self.assertRaises(json.JSONDecodeError):MatrixJournal(path,'A',{}).load(base)
            viewer=MatrixJournal(path,'A',{}).load(base,allow_incomplete_tail=True)
            self.assertEqual(viewer['cases'],[])
            # A corrupt completed record is never hidden by a progress viewer.
            with path.with_suffix('.jsonl').open('a') as stream:stream.write('\n')
            with self.assertRaises(json.JSONDecodeError):
                MatrixJournal(path,'A',{}).load(base,allow_incomplete_tail=True)


if __name__=='__main__':unittest.main()
