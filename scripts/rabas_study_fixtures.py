"""Separate generator families for algorithm-only stress tests; not orbital certification."""
import random
from datetime import datetime, timedelta
from schedulers.scenario_loader import (SchedulingSatellite, SensorSpec, SchedulingProblem, SchedulingGroundStation, CommWindow, TaskWindow, SchedulingTask)

def fixture(n, family, seed):
    rng=random.Random(seed); start=datetime(2026,1,1); ns=max(2,n//20)
    sats={f'S{i}':SchedulingSatellite(f'S{i}', maneuverability_type='non_agile' if i%3==0 else 'agile',
        max_data_storage_GB=(12+i%3 if family in ('capacity','hub') else 0),max_power_W=(14 if family=='capacity' else 0),
        sensors={'cam':SensorSpec('cam',819.2,1)}) for i in range(ns)}
    p=SchedulingProblem('SYNTHETIC_NOT_PHYSICAL',start,start+timedelta(seconds=1200),sats,{}, {},[])
    if family=='downlink':
        p.ground_stations={'G':SchedulingGroundStation('G')}
        for i,s in enumerate(sats):
            for j in range(8):p.comm_windows.append(CommWindow(len(p.comm_windows)+1,s,'G',start+timedelta(seconds=100+j*100),start+timedelta(seconds=180+j*100)))
    wid=0
    for i in range(n):
        tid=f'T{i:04}'; windows=[]; dur=rng.choice([5,10,15])
        k=1 if rng.random()<.35 else min(ns,rng.randint(2,4)); owners=rng.sample(list(sats),k)
        if family=='hub' and k>1: owners[0]='S0';owners=list(dict.fromkeys(owners))
        for sid in owners:
            for j in range(rng.randint(1,3)):
                off=rng.randrange(0,500) if family=='uniform' else rng.choice([60,160,300])+rng.randrange(0,50)
                width=dur+rng.choice([0,5,20,40]); wid+=1
                angle=float(rng.choice([0,5,15]))
                windows.append(TaskWindow(wid,sid,tid,'cam',1,start+timedelta(seconds=off),start+timedelta(seconds=off+width),
                    agile_data={x:[angle]*(int(width)+1) for x in ('pitch_angles','roll_angles','yaw_angles')},
                    non_agile_data={x:angle for x in ('pitch_angle','roll_angle','yaw_angle')},
                    planning_evidence={'trusted':True,'version':'visibility_exit_refined_v3','step_s':1.,'evidence_sha256':'SYNTHETIC_ONLY'}))
        p.tasks[tid]=SchedulingTask(tid,rng.randint(1,10),dur,windows)
    return p
