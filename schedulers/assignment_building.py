"""单个来源窗口的有界配置放置；复用来源角度切片，不展开整段时间网格。"""
from datetime import timedelta
import math
from schedulers.constraint_model import Assignment
from schedulers.source_windows import slice_source_angles

def configured_observation(problem, task, window, mode):
    satellite = problem.satellites[window.satellite_id]
    step = float(window.time_step)
    duration = float(task.required_duration)
    slack = (window.end_time-window.start_time).total_seconds()-duration
    if not math.isfinite(step) or step <= 0 or duration <= 0 or slack < 0: return None
    last = math.floor((slack+1e-9)/step)
    center = satellite.maneuverability_type == 'non_agile' or mode == 'center'
    k = max(0,min(last,round(slack/(2*step)))) if center else 0
    start = window.start_time+timedelta(seconds=k*step)
    end = start+timedelta(seconds=duration)
    angles = (window.non_agile_data if satellite.maneuverability_type=='non_agile'
              else slice_source_angles(window.agile_data,k,max(1,math.ceil(duration/step-1e-9))))
    sensor = satellite.sensors.get(window.sensor_id)
    if sensor is None: return None
    return Assignment(task_id=task.id,satellite_id=window.satellite_id,
        sat_start_time=start,sat_end_time=end,sat_window_id=window.window_id,
        sensor_id=window.sensor_id,orbit_number=window.orbit_number,
        data_volume_GB=sensor.data_rate_Mbps*duration/(8*1024),
        power_cost_W=sensor.power_consumption_W,sat_angles=angles)
