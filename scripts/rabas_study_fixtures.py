"""Separate generator families for algorithm-only stress tests; not orbital certification."""
import random
from datetime import datetime, timedelta
from schedulers.scenario_loader import (SchedulingSatellite, SensorSpec, SchedulingProblem, SchedulingGroundStation, CommWindow, TaskWindow, SchedulingTask)

def fixture(n, family, seed):
    if family in ('orbit_bands','station_network'):
        return independent_fixture(n, family, seed)
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

def independent_fixture(n, family, seed):
    """New source families: independently generated, never derived from old cases.

    Defined before the second implementation freeze. No results are used here.
    Orbit-band contention and a two-station network differ from prior uniform,
    clustered, capacity, hub, and one-station downlink generator branches.
    These remain synthetic mathematical cases, not orbital certificates.
    """
    rng=random.Random(seed); start=datetime(2026,2,1); ns=max(2,n//20)
    sats={f'V{i}':SchedulingSatellite(f'V{i}',maneuverability_type='agile' if i%2 else 'non_agile',
          max_data_storage_GB=4.+i%5,max_power_W=8.+i%7,
          sensors={'sensor':SensorSpec('sensor',256.+128*(i%4),1.+.25*(i%3))}) for i in range(ns)}
    p=SchedulingProblem('INDEPENDENT_SYNTHETIC_NOT_PHYSICAL',start,start+timedelta(seconds=1800),sats,{}, {},[])
    if family=='station_network':
        p.ground_stations={f'G{j}':SchedulingGroundStation(f'G{j}') for j in range(2)}
        for si,sid in enumerate(sats):
            for pass_no in range(7):
                offset=180+pass_no*180+10*(si%3)
                p.comm_windows.append(CommWindow(len(p.comm_windows)+1,sid,f'G{(si+pass_no)%2}',
                    start+timedelta(seconds=offset),start+timedelta(seconds=offset+90)))
    wid=0
    for i in range(n):
        tid=f'J{i:04}';duration=rng.choice([6.,12.,24.]);windows=[]
        owners=rng.sample(list(sats),1 if i%4==0 else min(ns,rng.randint(2,5)))
        band=rng.randrange(6)
        for sid in owners:
            si=int(sid[1:])
            for visit in range(1+rng.randrange(3)):
                # Periodic opportunities, heterogeneous phase, independently sampled mission offsets.
                offset=45+180*((band+visit)%7)+rng.randrange(0,36)+7*(si%4)
                width=duration+rng.choice([0.,12.,48.,96.])
                angle=float(rng.choice([-10,0,10,25]));wid+=1
                windows.append(TaskWindow(wid,sid,tid,'sensor',1+((band+visit)%3),
                    start+timedelta(seconds=offset),start+timedelta(seconds=offset+width),
                    agile_data={key:[angle]*(int(width)+1) for key in ('pitch_angles','roll_angles','yaw_angles')},
                    non_agile_data={key:angle for key in ('pitch_angle','roll_angle','yaw_angle')},
                    planning_evidence={'trusted':True,'version':'visibility_exit_refined_v3','step_s':1.,'evidence_sha256':'SYNTHETIC_ONLY'}))
        p.tasks[tid]=SchedulingTask(tid,1+rng.randrange(20),duration,windows)
    return p
