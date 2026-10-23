"""Registry identity and conflict measurements; fixtures are not physics evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eos_system.config import list_scenarios_in,resolve_scenario_in
from eos_system.dataset_registry import entries
from scripts.generate_scenarios import plan,satellites
from scripts.characterize_scenarios import characterize


class CanonicalRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'dataset_plan_v2.json').write_text('{}')

    def bundle(self,name='SCN-A',satellites=10,tasks=20):
        folder=self.root/'standard'/name;folder.mkdir(parents=True)
        scene=folder/'scenario.json';scene.write_text('{}')
        p=dict(scenario_id=name,scenario_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),
            difficulty_profile='low_conflict',scale='S2',seed=7,lineage_group_id=name,
            publication_status='development',physical_validation=dict(status='SAMPLED_PASS'))
        (folder/'provenance.json').write_text(json.dumps(p))
        (folder/'validation.json').write_text('{}')
        (folder/'characterization.json').write_text(json.dumps(dict(satellite_count=satellites,task_count=tasks,duration_s=1800)))
        return folder

    def test_identity_filters_resolution_and_no_sidecars_in_picker(self):
        a=self.bundle();self.bundle('SCN-B',20,40)
        self.assertEqual(len(list_scenarios_in(self.root,'canonical')),2)
        self.assertEqual(entries(self.root,satellite_count=20)[0]['scenario_id'],'SCN-B')
        self.assertEqual(entries(self.root,task_count=99),[])
        self.assertEqual(resolve_scenario_in(self.root,'SCN-A')[0],a/'scenario.json')
        with self.assertRaises(FileNotFoundError):resolve_scenario_in(self.root,'../SCN-A')
        (a/'scenario.json').write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError,'SHA'):resolve_scenario_in(self.root,'SCN-A')

    def test_quarantine_and_incomplete_are_not_silently_exposed(self):
        a=self.bundle();(a/'quarantine.json').write_text('{"reason":"failed"}')
        b=self.bundle('SCN-B');(b/'validation.json').unlink()
        self.assertEqual(entries(self.root),[])

    def test_planned_resolution_avoids_corpus_scan_and_keeps_identity_guards(self):
        folder=self.bundle()
        (self.root/'dataset_plan_v3.json').write_text(json.dumps(dict(allocation=[dict(
            scenario_id='SCN-A',relative_path='standard/SCN-A/scenario.json')])))
        with patch('eos_system.dataset_registry.entries',side_effect=AssertionError('unnecessary full scan')):
            self.assertEqual(resolve_scenario_in(self.root,'SCN-A')[0],folder/'scenario.json')
            (folder/'scenario.json').write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'SHA'):resolve_scenario_in(self.root,'SCN-A')
        (self.root/'dataset_plan_v3.json').write_text(json.dumps(dict(allocation=[dict(
            scenario_id='SCN-A',relative_path='../outside/scenario.json')])))
        with self.assertRaisesRegex(ValueError,'escapes'):resolve_scenario_in(self.root,'SCN-A')

    def test_duplicate_identity_is_rejected(self):
        self.bundle();b=self.bundle('SCN-B')
        p=json.loads((b/'provenance.json').read_text());p['scenario_id']='SCN-A'
        (b/'provenance.json').write_text(json.dumps(p))
        with self.assertRaisesRegex(ValueError,'duplicate'):entries(self.root)

    def test_all_96_slots_and_real_40_satellite_subset(self):
        rows=plan();self.assertEqual(len(rows),96)
        self.assertEqual(len({r['scenario_id'] for r in rows}),96)
        self.assertEqual({(r['satellite_count'],r['task_count']) for r in rows},
            {(10,10),(10,20),(20,30),(20,40),(40,80),(50,80),(50,100),(100,200)})
        sats,source=satellites(40,'low_conflict')
        raw=json.loads((Path(__file__).resolve().parents[1]/source['path']).read_text())
        self.assertEqual({s['id'] for s in sats},set(sorted(raw)[:40]))

    def test_conflict_and_pressure_measurements_use_actual_intervals(self):
        scene=dict(metadata=dict(duration=100),satellites=[dict(id='S',satellite_specs=dict(max_operation_time_s=10))],
            missions=[dict(id=t,observation_requirement=dict(duration_s=10)) for t in ('A','B')],
            observation_windows=[dict(satellite_id='S',mission_id=t,time_windows=[dict(start_time='2026-01-01T00:00:10',end_time='2026-01-01T00:00:30')]) for t in ('A','B')])
        result=characterize(scene)
        self.assertEqual(result['window_overlap_fraction'],1)
        self.assertEqual(result['max_demand_capacity_ratio'],.2)
        scene['observation_windows'][1]['time_windows'][0]=dict(start_time='2026-01-01T00:00:40',end_time='2026-01-01T00:01:00')
        self.assertEqual(characterize(scene)['window_overlap_fraction'],0)


if __name__=='__main__':unittest.main()
