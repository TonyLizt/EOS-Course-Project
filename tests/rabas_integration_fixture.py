"""Isolated integration ONLY: synthetic JSON and test-only final certificate.

No production code can select this factory. Physical certification is NOT tested
by this fixture. Worker/registry/constraints/Controller/transactions remain real.
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path

from certification_fixtures import unit_certify
from utils.continuous_exposure import window_generation_record


def write_scene(path):
    start=datetime(2026,1,1)
    scene={'scenario_id':'rabas-synthetic-integration',
        'metadata':{'creation_time':start.isoformat(),'duration':180,
            'extra':{'window_generation':window_generation_record(1,5,60),
                     'fixture_note':'SYNTHETIC_UNIT_TEST_ONLY_NOT_PHYSICAL_CERTIFICATION'}},
        'satellites':[{'id':sid,'maneuverability_capability':{'maneuverability_type':'non_agile'},
            'satellite_specs':{'max_data_storage_GB':20,'max_power_W':20},
            'observation_capability':{'sensors':[{'sensor_id':'cam','data_rate_Mbps':81.92,
                'power_consumption_W':1,'field_of_view_deg':45}]}} for sid in ('S1','S2')],
        'ground_stations':[], 'missions':[], 'observation_windows':[]}
    for i in range(3):
        tid=f'M{i+1}'
        scene['missions'].append({'id':tid,'priority':3-i,'observation_requirement':{'duration_s':10},
                                  'target_location':{'latitude':1,'longitude':i+1,'altitude_km':0}})
        for sid in ('S1','S2'):
            begin=start+timedelta(seconds=10+40*i)
            scene['observation_windows'].append({'satellite_id':sid,'mission_id':tid,'sensor_id':'cam',
                'time_windows':[{'start_time':begin.isoformat(),'end_time':(begin+timedelta(seconds=10)).isoformat(),
                    'orbit_number':1,'time_step':1,'non_agile_data':{'roll_angle':0,'pitch_angle':0,'yaw_angle':0}}]})
    path.write_text(json.dumps(scene),encoding='utf-8')


def cache_orbits(settings,sha):
    from eos_system.visualization import orbit_cache_file
    cache=orbit_cache_file(settings,sha)
    cache.parent.mkdir(parents=True,exist_ok=True)
    cache.write_text(json.dumps([{'id':'document','version':'1.0','clock':{
        'interval':'2026-01-01T00:00:00Z/2026-01-01T00:03:00Z',
        'currentTime':'2026-01-01T00:00:00Z','multiplier':1}},
        *[{'id':sid,'position':{'epoch':'2026-01-01T00:00:00Z',
            'cartographicDegrees':[0,0,0,600000,90,40,10,600000,180,80,0,600000]}}
          for sid in ('S1','S2')]]))


def make_app():
    # Same explicit UNIT TEST ONLY certificate injection as existing I2 tests.
    # Applied in this test server process, never in production configuration.
    from eos_system import verification
    from eos_system.api import create_app
    verification.certify_schedule=unit_certify
    return create_app()
