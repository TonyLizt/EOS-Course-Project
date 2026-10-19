"""Read-only continuous-exposure audit; point samples are never a continuity proof."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import time

from utils.time_parsing import parse_orbit_epoch
from utils.certification_identity import trusted_context, source_identity
from contextlib import contextmanager
import threading

AUDIT_VERSION = "continuous_exposure_audit_v3"
LIMITATION = ("Finite point evaluations and detected-exit bisection cannot rule out "
              "hidden sub-step invisible gaps; no analytic interval certificate is available.")


def exposure_times(start, end, required_s):
    """Exact positive duration at datetime microsecond resolution; legacy naive is UTC."""
    if not isinstance(start, (str, datetime)) or not isinstance(end, (str, datetime)):
        raise ValueError("exposure start/end must be datetime or ISO time")
    first = parse_orbit_epoch(start, field_name="exposure.start")
    last = parse_orbit_epoch(end, field_name="exposure.end")
    try:
        if isinstance(required_s, bool):
            raise ValueError("boolean duration")
        micros = Decimal(str(required_s)) * 1000000
        if not micros.is_finite() or micros <= 0 or micros != micros.to_integral_value():
            raise ValueError("duration must be positive and representable in integer microseconds")
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("invalid exposure duration") from exc
    if last <= first or last - first != timedelta(microseconds=int(micros)):
        raise ValueError("exposure duration does not exactly match required duration")
    return first, last


def audit_interval(evaluate, start, end, required_s, *, step_s=0.05, certificate=None):
    """Re-evaluate ACTUAL exposure, ignoring serialized observation window ends.

    PASS requires a trusted in-process interval certificate for every partition,
    not a JSON flag, two visible endpoints, or dense samples. Production Orekit
    currently provides no such certificate, so an all-visible scan is INCONCLUSIVE.
    A false point/detected conservative-end violation is sufficient for FAIL.
    """
    from utils.visibility import _refine_visibility_exit, EXIT_BOUNDARY_PRECISION_US
    first, last = exposure_times(start, end, required_s)
    if isinstance(step_s,bool) or not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("audit step_s must be finite and positive")
    step = timedelta(seconds=step_s)
    if step <= timedelta(0):
        raise ValueError("audit step_s is below datetime microsecond resolution")
    count = 0
    def point(moment):
        nonlocal count
        sample = evaluate(moment)
        count += 1
        if type(sample.get("visible")) is not bool:
            raise ValueError("visibility evaluator did not return a boolean")
        if sample.get("evaluation_error"):
            raise RuntimeError("visibility evaluation unavailable: " + str(sample["evaluation_error"]))
        return sample
    previous = None
    partitions = []
    moment = first
    while True:
        if not point(moment)["visible"]:
            result = dict(status="FAIL", reason="NONVISIBLE_EXPOSURE_START" if previous is None
                          else "NONVISIBLE_EXPOSURE_POINT", witness_utc=moment.isoformat())
            if previous is not None:
                lower, upper = _refine_visibility_exit(previous, moment, point)
                result.update(safe_exit_lower=lower.isoformat(), exit_upper=upper.isoformat(),
                              boundary_precision_us=EXIT_BOUNDARY_PRECISION_US,
                              overrun_lower_s=(last-upper).total_seconds(),
                              overrun_upper_s=(last-lower).total_seconds())
            result.update(evaluations=count, sampled_boundaries_status="FAIL")
            return result
        if previous is not None:
            partitions.append((previous, moment))
        if moment == last:
            break
        previous = moment
        moment = min(last, moment + step)
    certified = certificate is not None and all(certificate(a,b) is True for a,b in partitions)
    return dict(status="PASS" if certified else "INCONCLUSIVE",
                reason="CERTIFIED_INTERVAL" if certified else "NO_CONTINUITY_CERTIFICATE",
                sampled_boundaries_status="PASS", evaluations=count,
                limitation=None if certified else LIMITATION)


class PlanExposureAuditor:
    """Bounded per-instance state; no disk cache or cross-input global audit cache."""
    def __init__(self, scene, *, data_path=None, min_elevation_deg, step_s=0.05,
                 evaluator_factory=None, max_pairs=8, max_evaluations=100000,
                 attitude_contract="nadir_relative_fixed_camera_v1"):
        self.scene = deepcopy(scene)
        self.attitude_contract = attitude_contract
        self.scene_digest = hashlib.sha256(json.dumps(scene,sort_keys=True,allow_nan=False).encode()).hexdigest()
        if isinstance(min_elevation_deg,bool) or not math.isfinite(min_elevation_deg) or not -90 <= min_elevation_deg <= 90:
            raise ValueError("invalid min_elevation_deg")
        if isinstance(step_s,bool) or not math.isfinite(step_s) or step_s < 0.000001:
            raise ValueError("invalid audit step_s")
        if not isinstance(max_pairs,int) or max_pairs<1 or max_evaluations<1:
            raise ValueError("invalid audit cache/evaluation budget")
        self.minimum, self.step_s = min_elevation_deg, step_s
        self.factory = evaluator_factory
        self.data_path = Path(data_path) if data_path else None
        self.data_sha = None
        self.context_ready = False
        self.deadline = float("inf")
        self.pairs = OrderedDict()
        self.max_pairs, self.budget = max_pairs, max_evaluations
        self.propagations = self.pair_builds = self.cache_hits = 0

    @staticmethod
    def number(mapping, key):
        if key not in mapping:
            raise KeyError(key)
        value = mapping[key]
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
            raise ValueError("invalid numeric physical field: " + key)
        return float(value)

    def evaluator(self, satellite, mission):
        from utils.visibility import create_visibility_evaluator, ensure_orekit, effective_minimum_elevation
        op = satellite["orbital_params"]
        location = mission["target_location"]
        limits = satellite["maneuverability_capability"]
        n = self.number
        params = dict(a_m=n(op,"semi_major_axis_km")*1000, e=n(op,"eccentricity"),
            i_deg=n(op,"inclination_deg"), raan_deg=n(op,"right_ascension_of_ascending_node_deg"),
            argp_deg=n(op,"argument_of_perigee_deg"), m_deg=n(op,"mean_anomaly_deg"),
            epoch_dt=parse_orbit_epoch(op["epoch"],satellite_id=satellite["id"]),
            target_lat_deg=n(location,"latitude"),target_lon_deg=n(location,"longitude"),
            target_alt_m=n(location,"altitude_km")*1000,
            max_yaw_deg=n(limits,"max_yaw_angle_deg"),max_pitch_deg=n(limits,"max_pitch_angle_deg"),
            max_roll_deg=n(limits,"max_roll_angle_deg"),min_elevation_deg=self.minimum)
        sensors = satellite.get("observation_capability", {}).get("sensors", [])
        if len(sensors) != 1 and self.factory is None:
            raise ValueError("physical audit requires one explicit fixed camera")
        params.update(field_of_view_deg=(sensors[0].get("field_of_view_deg", 45.0) if sensors else 45.0),
                      maneuverability_type=limits.get("maneuverability_type", "agile"),
                      max_tracking_rate_deg_s=limits.get("slew_rate_deg_per_s"))
        params['min_elevation_deg']=effective_minimum_elevation(self.minimum,
            sensors[0].get('min_elevation_angle_deg') if sensors else None,
            mission.get('observation_requirement',{}).get('min_elevation_angle_deg'))
        from utils.course_compatibility import LEGACY_ATTITUDE
        if self.attitude_contract == LEGACY_ATTITUDE:
            # 完整复用历史姿态/仰角合同；不追溯新增 FOV/跟踪限制到旧窗口。
            params['attitude_contract'] = LEGACY_ATTITUDE
            params['min_elevation_deg'] = self.minimum
        if (params["a_m"]<=0 or not 0<=params["e"]<1 or not -90<=params["target_lat_deg"]<=90
                or any(params[k]<0 for k in ("max_yaw_deg","max_pitch_deg","max_roll_deg"))):
            raise ValueError("physical inputs outside supported Keplerian/target/attitude domain")
        if self.factory is None and not self.context_ready:
            if self.data_path is None or not self.data_path.is_file():
                raise FileNotFoundError("Orekit data ZIP is required")
            self.data_sha = hashlib.sha256(self.data_path.read_bytes()).hexdigest()
            try:
                ensure_orekit(str(self.data_path))
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            self.context_ready = True
        identity = json.dumps([self.scene_digest,self.data_sha,AUDIT_VERSION,
                               satellite["id"],mission["id"],params],sort_keys=True,default=str)
        if identity in self.pairs:
            self.cache_hits += 1
            self.pairs.move_to_end(identity)
            return self.pairs[identity]
        raw = (self.factory or create_visibility_evaluator)(**params)
        self.pair_builds += 1
        @lru_cache(maxsize=256)
        def evaluate(moment):
            if time.monotonic() > self.deadline:
                raise RuntimeError("certification deadline exceeded")
            if self.propagations >= self.budget:
                raise RuntimeError("audit evaluation budget exhausted")
            self.propagations += 1
            return raw(moment)
        value = evaluate, getattr(raw,"certify_interval",None)
        self.pairs[identity] = value
        if len(self.pairs)>self.max_pairs:
            _,(old,_) = self.pairs.popitem(last=False)
            old.cache_clear()
        return value

    def ground_evaluator(self,satellite,station):
        """Independent real communication geometry, no optical attitude proxy."""
        from utils.visibility import create_communication_evaluator
        n=self.number;op=satellite['orbital_params'];loc=station['location']
        params=dict(a_m=n(op,'semi_major_axis_km')*1000,e=n(op,'eccentricity'),
            i_deg=n(op,'inclination_deg'),raan_deg=n(op,'right_ascension_of_ascending_node_deg'),
            argp_deg=n(op,'argument_of_perigee_deg'),m_deg=n(op,'mean_anomaly_deg'),
            epoch_dt=parse_orbit_epoch(op['epoch']),target_lat_deg=n(loc,'latitude'),
            target_lon_deg=n(loc,'longitude'),target_alt_m=n(loc,'altitude_km')*1000,
            min_elevation_deg=self.minimum)
        key=json.dumps(['ground_link',self.scene_digest,self.data_sha,params],sort_keys=True,default=str)
        if key in self.pairs:
            self.cache_hits+=1;self.pairs.move_to_end(key)
            return self.pairs[key][0]
        raw=create_communication_evaluator(**params)
        self.pair_builds+=1
        @lru_cache(maxsize=256)
        def evaluate(moment):
            if time.monotonic()>self.deadline or self.propagations>=self.budget:
                raise RuntimeError('communication audit deadline/evaluation budget exceeded')
            self.propagations+=1
            return raw(moment)
        self.pairs[key]=(evaluate,None)
        if len(self.pairs)>self.max_pairs:
            _,(old,_)=self.pairs.popitem(last=False);old.cache_clear()
        return evaluate

    def audit(self, plan):
        begin = time.perf_counter()
        rows = []
        if not isinstance(plan,dict) or not isinstance(plan.get("assignments"),list) or not plan["assignments"]:
            return dict(status="INCONCLUSIVE",reason="NO_ASSIGNMENTS_TO_AUDIT",rows=[],
                        counts={"PASS":0,"FAIL":0,"INCONCLUSIVE":0},task_count=0)
        satellites = {s["id"]:s for s in self.scene.get("satellites",[])}
        missions = {m["id"]:m for m in self.scene.get("missions",[])}
        stations = {g['id']:g for g in self.scene.get('ground_stations',[])}
        seen = set()
        for index,a in enumerate(plan.get("assignments",[])):
            row = dict(index=index,task_id=a.get("task_id") if isinstance(a,dict) else None,
                       satellite_id=a.get("satellite_id") if isinstance(a,dict) else None)
            try:
                if not isinstance(a,dict) or any(k not in a for k in (
                        "task_id","satellite_id","sensor_id","sat_start_time","sat_end_time")):
                    raise ValueError("missing assignment fields")
                if plan.get("scenario_id") != self.scene["scenario_id"]:
                    raise ValueError("plan/scenario id mismatch")
                if a["task_id"] in seen:
                    raise ValueError("duplicate scheduled task")
                seen.add(a["task_id"])
                satellite,mission = satellites[a["satellite_id"]],missions[a["task_id"]]
                sensors=satellite["observation_capability"]["sensors"]
                if not any(s["sensor_id"]==a["sensor_id"] for s in sensors):
                    raise ValueError("sensor is not defined by satellite")
                required=mission["observation_requirement"]["duration_s"]
                start,end=exposure_times(a["sat_start_time"],a["sat_end_time"],required)
                meta=self.scene["metadata"]
                horizon=parse_orbit_epoch(meta["creation_time"])
                duration=self.number(meta,"duration")
                if duration<=0 or not horizon<=start<end<=horizon+timedelta(seconds=duration):
                    raise ValueError("exposure outside scenario time range")
                evaluate,certificate=self.evaluator(satellite,mission)
                row.update(audit_interval(evaluate,start,end,required,step_s=self.step_s,certificate=certificate))
                row.update(start_utc=start.isoformat(),end_utc=end.isoformat(),required_s=required)
                if stations:
                    station=stations[a['ground_station_id']]
                    gs_start=parse_orbit_epoch(a['gs_start_time']);gs_end=parse_orbit_epoch(a['gs_end_time'])
                    if not end<gs_start<gs_end<=horizon+timedelta(seconds=duration):
                        raise ValueError('invalid physical downlink interval')
                    ground=self.ground_evaluator(satellite,station)
                    link=audit_interval(ground,gs_start,gs_end,(gs_end-gs_start).total_seconds(),step_s=self.step_s)
                    row['downlink_audit']=link
                    if link['sampled_boundaries_status']!='PASS':
                        row.update(status='FAIL',reason='DOWNLINK_'+link['reason'],sampled_boundaries_status='FAIL')
                    elif row['status']=='PASS':
                        # Ground geometry currently has no interval provider.
                        row.update(status='INCONCLUSIVE',reason='NO_GROUND_LINK_CONTINUITY_CERTIFICATE')
            except KeyError as exc:
                row.update(status="INCONCLUSIVE",reason="MISSING_PHYSICAL_INPUT",detail=str(exc),sampled_boundaries_status='UNAVAILABLE')
            except (OSError,ImportError,RuntimeError) as exc:
                row.update(status="INCONCLUSIVE",reason="PHYSICS_UNAVAILABLE",detail=str(exc),sampled_boundaries_status='UNAVAILABLE')
            except (ValueError,TypeError,OverflowError) as exc:
                row.update(status="FAIL",reason="INVALID_INPUT",detail=str(exc),sampled_boundaries_status='FAIL')
            rows.append(row)
        counts={k:sum(r["status"]==k for r in rows) for k in ("PASS","FAIL","INCONCLUSIVE")}
        if not isinstance(plan.get("assignments"),list) or not rows:
            return dict(status="INCONCLUSIVE",reason="NO_ASSIGNMENTS_TO_AUDIT",rows=rows,counts=counts)
        return dict(audit_version=AUDIT_VERSION,status="FAIL" if counts["FAIL"] else
                    ("INCONCLUSIVE" if counts["INCONCLUSIVE"] else "PASS"),
                    rows=rows,counts=counts,task_count=len(rows),scan_step_s=self.step_s,
                    boundary_precision_us=1,orekit_data_sha256=self.data_sha,
                    predicate="existing Orekit Keplerian/TargetPointing; elevation and stored three-axis bounds",
                    min_elevation_deg=self.minimum,model="Orekit" if self.factory is None else "custom trusted evaluator",
                    propagation_calls=self.propagations,evaluator_builds=self.pair_builds,
                    pair_cache_hits=self.cache_hits,max_cached_pairs=self.max_pairs,point_cache_per_pair=256,
                    wall_s=time.perf_counter()-begin,limitation=LIMITATION)


# Shared contract: planning acceptance is never a physical certificate.
from dataclasses import dataclass
from enum import Enum


class ExposureStatus(str, Enum):
    REJECTED = "REJECTED"
    PLANNING_FEASIBLE = "PLANNING_FEASIBLE"
    CONTINUOUS_PASS = "CONTINUOUS_PASS"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ExposureDecision:
    status: ExposureStatus
    reason: str
    safe_start: datetime | None = None
    safe_end: datetime | None = None


# Reviewed historical v2 implementation used by the four frozen candidates.
# A matching scene SHA + completed sidecar + actual step are ALSO required.
GRID_V2_SOURCE_SHA256 = "401cf0ae4989af5ac088de9ac9f74dfb58f279018d44b506fa9e61bca0d4aae3"



WINDOW_PHYSICS_FILES = ('utils/visibility.py', 'utils/time_parsing.py', 'utils/attitude_frames.py')
WINDOW_PHYSICS_SCHEMA = 'orekit-window-physics-lf-v2'


def window_physics_sources(root=None):
    """窗口来源只绑定实际几何/Epoch实现；仅统一CRLF/LF，不忽略代码差异。"""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    return {name: hashlib.sha256((root/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for name in WINDOW_PHYSICS_FILES}


def window_generation_record(step_s, min_elevation_deg, coarse_step_min):
    from utils.visibility import VISIBILITY_ALGORITHM_VERSION, EXIT_BOUNDARY_PRECISION_US
    from utils.attitude_frames import ATTITUDE_MODEL_VERSION, CAMERA_TO_BODY_XYZW
    return dict(window_algorithm_version=VISIBILITY_ALGORITHM_VERSION,
                attitude_model_version=ATTITUDE_MODEL_VERSION,
                attitude_reference="nominal_nadir", body_optical_axis="+Z",
                camera_to_body_quaternion_xyzw=list(CAMERA_TO_BODY_XYZW),
                field_of_view_semantics="square_full_angle",
                boundary_refinement_version="visible_side_bisection_v1",
                exit_precision_us=EXIT_BOUNDARY_PRECISION_US,
                endpoint_semantics="visible_side_exit_or_evaluated_horizon",
                entry_semantics="first_visible_grid_sample",
                precision_scope="detected_exit_brackets_only",
                horizon_semantics="evaluated_endpoint_not_interval_proof",
                scan_step_s=step_s, min_elevation_deg=min_elevation_deg,
                coarse_step_min=coarse_step_min, interval_semantics="half_open",
                continuous_certification=dict(status="NOT_RUN", audit_version=AUDIT_VERSION),
                source_files_sha256=source_identity(),
                physics_provenance_schema=WINDOW_PHYSICS_SCHEMA,
                physics_sources_sha256_lf=window_physics_sources())


def planning_evidence(scene, path, scene_sha):
    """Only loader-produced evidence is used; window/Worker JSON flags are ignored.

    The local generator/source installation and completed lineage sidecars are
    trusted inputs, not cryptographic attestations against a hostile filesystem.
    """
    sidecar = Path(path).parent/'provenance'/(Path(path).name+'.provenance.json')
    record = scene.get("metadata",{}).get("extra",{}).get("window_generation",{})
    fresh = False
    development = scene.get("metadata", {}).get("extra", {}).get("development_generation_contract")
    if development == "gen02.development.v1":
        try:
            from eos_system.provenance import capture_development_provenance
            capture_development_provenance(Path(path), scene_sha)
        except (OSError, ValueError, TypeError):
            return None
    if sidecar.exists() or sidecar.is_symlink():
        if sidecar.is_symlink() or not sidecar.is_file() or sidecar.stat().st_size > 1024*1024:
            return None
        raw = sidecar.read_bytes()
        data = json.loads(raw)
        fresh = data.get('artifact_kind') == 'fresh_generated_shared_v1'
        version = data.get("window_boundary_version")
        code = data.get("source_files_sha256",{}).get("utils/visibility.py")
        settings = data.get("calculation_settings",{})
        if (data.get("scenario_sha256")==scene_sha and data.get("completion_status")=="complete"
                and data.get("calculator_kind")=="orekit"):
            if version=="visibility_grid_v2" and code==GRID_V2_SOURCE_SHA256:
                return dict(trusted=True, version=version, step_s=settings.get("time_step"),
                            min_elevation_deg=settings.get("min_elevation_deg"),
                            evidence_sha256=hashlib.sha256(raw).hexdigest())
            if version != "visibility_exit_refined_v3":
                return None
            record = data.get("window_generation",{})
        else:
            return None
    # 仍检查当前进程没有加载A后偷偷换盘上B。新共享数据把窗口生成身份
    # 与API/Controller/Storage部署身份分开，完整生产源码快照另行留存。
    current_sources = source_identity()
    source_matches = isinstance(record,dict) and record.get('source_files_sha256') == current_sources
    if fresh and isinstance(record,dict) and 'physics_sources_sha256_lf' in record:
        source_matches = (record.get('physics_provenance_schema') == WINDOW_PHYSICS_SCHEMA
                          and record.get('physics_sources_sha256_lf') == window_physics_sources())
        from utils.course_compatibility import legacy_window_record
        # 旧来源保留原 SHA；接纳明确的历史合同，不声称符合新 Nadir 模型。
        source_matches = source_matches or legacy_window_record(record)
    if (isinstance(record,dict) and record.get("window_algorithm_version")=="visibility_exit_refined_v3"
            and source_matches
            and record.get("endpoint_semantics")=="visible_side_exit_or_evaluated_horizon"
            and record.get("interval_semantics")=="half_open"
            and record.get("boundary_refinement_version")=="visible_side_bisection_v1"
            and type(record.get("exit_precision_us")) is int and record["exit_precision_us"]==1):
        from utils.course_compatibility import legacy_window_record, LEGACY_ATTITUDE, NADIR_ATTITUDE
        return dict(trusted=True, version="visibility_exit_refined_v3", step_s=record.get("scan_step_s"),
                    min_elevation_deg=record.get("min_elevation_deg"),
                    attitude_model_version=(LEGACY_ATTITUDE if legacy_window_record(record) else NADIR_ATTITUDE),
                    evidence_sha256=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest())
    return None


def planning_window(window):
    """Conservative PLANNING bounds only, never exclusion of hidden sub-step gaps."""
    try:
        start=parse_orbit_epoch(window.start_time); end=parse_orbit_epoch(window.end_time)
        evidence=getattr(window,"planning_evidence",None)
        if not evidence or evidence.get("trusted") is not True or not evidence.get("evidence_sha256"):
            return ExposureDecision(ExposureStatus.INCONCLUSIVE,"UNTRUSTED_WINDOW_PROVENANCE")
        step=Decimal(str(window.time_step))*1000000
        declared=Decimal(str(evidence.get("step_s")))*1000000
        if not step.is_finite() or step<=0 or step!=step.to_integral_value() or step!=declared:
            return ExposureDecision(ExposureStatus.ERROR,"INVALID_OR_MISMATCHED_SCAN_STEP")
        version=evidence.get("version")
        if version=="visibility_grid_v2":
            # v2 serializes the first invisible point (or unchecked horizon).
            # One ACTUAL step returns to/before the last visible sample.
            end-=timedelta(microseconds=int(step))
        elif version!="visibility_exit_refined_v3":
            return ExposureDecision(ExposureStatus.INCONCLUSIVE,"UNKNOWN_WINDOW_SEMANTICS")
        if end<=start:
            return ExposureDecision(ExposureStatus.REJECTED,"NO_POSITIVE_PLANNING_INTERVAL")
        return ExposureDecision(ExposureStatus.PLANNING_FEASIBLE,"CONSERVATIVE_WINDOW_ONLY",start,end)
    except (ValueError,TypeError,InvalidOperation,OverflowError):
        return ExposureDecision(ExposureStatus.ERROR,"INVALID_WINDOW_INPUT")


def planning_exposure(window, start, end, required_s):
    try:
        first,last=exposure_times(start,end,required_s)
    except (ValueError,TypeError,OverflowError):
        return ExposureDecision(ExposureStatus.ERROR,"INVALID_EXPOSURE")
    bounds=planning_window(window)
    if bounds.status is not ExposureStatus.PLANNING_FEASIBLE:
        return bounds
    if not bounds.safe_start<=first<last<=bounds.safe_end:
        return ExposureDecision(ExposureStatus.REJECTED,"OUTSIDE_CONSERVATIVE_WINDOW",bounds.safe_start,bounds.safe_end)
    return bounds


class ContinuousCertificationError(ValueError):
    def __init__(self,status,reason):
        self.status=status
        super().__init__(str(status)+": "+reason)


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan,ensure_ascii=False,sort_keys=True,
                                    separators=(",",":"),allow_nan=False).encode()).hexdigest()


_ISSUER = object()


@dataclass(frozen=True)
class CertificationReceipt:
    # In-process authority. A Worker dict can never supply this capability.
    payload_json: str
    _authority: object

    def evidence(self):
        if self._authority is not _ISSUER:
            raise ContinuousCertificationError(ExposureStatus.ERROR,"UNTRUSTED_RECEIPT")
        return json.loads(self.payload_json)


class CertifiedRecord(dict):
    """Storage-issued in-process record; its receipt is never serialized to JSON."""
    pass


_RUNTIME = threading.local()


@contextmanager
def certification_runtime(deadline, context):
    old = getattr(_RUNTIME, "value", None)
    _RUNTIME.value = (deadline, context)
    try:
        yield
    finally:
        _RUNTIME.value = old


def check_deadline(deadline):
    if not math.isfinite(deadline) or time.monotonic() >= deadline:
        raise ContinuousCertificationError(ExposureStatus.ERROR, "CERTIFICATION_TIMEOUT")


def certification_context(context=None, *, data_path=None):
    try:
        return (context or (getattr(_RUNTIME, "value", None) or (None, None))[1]
                or trusted_context(data_path)).check()
    except (OSError, ValueError) as exc:
        raise ContinuousCertificationError(ExposureStatus.ERROR, "CERTIFICATION_IDENTITY_INVALID: " + str(exc)) from exc


def validate_certification(evidence, *, run_id, scenario_sha, plan, context=None):
    expected = certification_context(context)
    identity = expected.identity()
    if (not isinstance(evidence, dict) or evidence.get("receipt_schema_version") != 3
            or evidence.get("status") != "CONTINUOUS_PASS" or evidence.get("audit_version") != AUDIT_VERSION
            or evidence.get("run_id") != run_id or evidence.get("scenario_sha256") != scenario_sha
            or evidence.get("plan_sha256") != plan_digest(plan)
            or any(evidence.get(key) != value for key, value in identity.items())
            or not isinstance(evidence.get("orekit_data_sha256"), str)
            or len(evidence["orekit_data_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in evidence["orekit_data_sha256"])
            or evidence.get("settings_sha256") != plan_digest({key:evidence.get(key) for key in
                ("scan_step_s", "boundary_precision_us", "predicate", "min_elevation_deg", "model_parameters")})
            or type(evidence.get("certified_tasks")) is not int
            or evidence["certified_tasks"] != len(plan.get("assignments", []))
            or evidence["certified_tasks"] < 0
            or type(evidence.get("scan_step_s")) not in (int, float) or evidence["scan_step_s"] != .05
            or type(evidence.get("boundary_precision_us")) is not int or evidence["boundary_precision_us"] != 1
            or type(evidence.get("min_elevation_deg")) not in (int, float)
            or not math.isfinite(evidence["min_elevation_deg"])
            or not -90 <= evidence["min_elevation_deg"] <= 90
            or not isinstance(evidence.get("audit_result_sha256"), str)
            or len(evidence["audit_result_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in evidence["audit_result_sha256"])
            or type(evidence.get("deadline_monotonic")) not in (int, float)
            or not math.isfinite(evidence["deadline_monotonic"])):
        raise ContinuousCertificationError(ExposureStatus.INCONCLUSIVE,"MISSING_STALE_OR_MISMATCHED_CERTIFICATION")
    return evidence


def certify_schedule(scene_path, plan, *, run_id, scenario_sha, data_path=None,
                     min_elevation_deg=None, timeout_s=30.0, auditor_factory=None,
                     context=None, deadline=None):
    """Controller-owned certification; never trusts assertions embedded in a plan.

    Cooperative deadline is checked on every physical evaluation and around the
    audit. Controller also executes this in its background thread. No HTTP work.
    Test injection is a Python callable only, never an env/JSON bypass.
    """
    begin=time.monotonic(); path=Path(scene_path)
    runtime=getattr(_RUNTIME, "value", None)
    deadline = deadline if deadline is not None else (runtime[0] if runtime else begin+timeout_s)
    check_deadline(deadline)
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=scenario_sha:
        raise ContinuousCertificationError(ExposureStatus.ERROR,"SCENARIO_SHA_MISMATCH")
    scene=json.loads(raw)
    if min_elevation_deg is None:
        lineage=planning_evidence(scene,path,scenario_sha)
        if lineage is None:
            raise ContinuousCertificationError(ExposureStatus.INCONCLUSIVE,"UNTRUSTED_PHYSICAL_SETTINGS")
        min_elevation_deg=lineage.get("min_elevation_deg")
        if min_elevation_deg is None:
            raise ContinuousCertificationError(ExposureStatus.INCONCLUSIVE,"MISSING_MIN_ELEVATION")
    context=certification_context(context or (runtime[1] if runtime else None), data_path=data_path)
    if data_path is not None and Path(data_path).resolve() != Path(context.data_path):
        raise ContinuousCertificationError(ExposureStatus.ERROR, "OREKIT_DATA_SOURCE_MISMATCH")
    data_path=context.data_path
    check_deadline(deadline)
    auditor=(auditor_factory or PlanExposureAuditor)(scene,data_path=data_path,
                    min_elevation_deg=min_elevation_deg,step_s=.05)
    # Audit owns the deadline and checks it before each row and every evaluation.
    auditor.deadline=deadline
    try:
        result=auditor.audit(deepcopy(plan))
    except Exception as exc:
        raise ContinuousCertificationError(ExposureStatus.ERROR, "AUDIT_EXECUTION_ERROR: "+str(exc)) from exc
    check_deadline(deadline)
    certification_context(context)
    if result.get("status")!="PASS":
        status={"FAIL":ExposureStatus.REJECTED,"INCONCLUSIVE":ExposureStatus.INCONCLUSIVE}.get(result.get("status"),ExposureStatus.ERROR)
        reasons=sorted({r.get("reason","UNKNOWN") for r in result.get("rows",[])})
        if "PHYSICS_UNAVAILABLE" in reasons or "INVALID_INPUT" in reasons:
            status=ExposureStatus.ERROR
        raise ContinuousCertificationError(status,",".join(reasons) or result.get("reason","AUDIT_NOT_PASS"))
    if (len(result.get("rows",[])) != len(plan.get("assignments",[]))
            or not result.get("rows")
            or any(r.get("status")!="PASS" or r.get("reason")!="CERTIFIED_INTERVAL" for r in result["rows"])):
        raise ContinuousCertificationError(ExposureStatus.ERROR,"INCOMPLETE_CERTIFICATION_RESULT")
    if hashlib.sha256(path.read_bytes()).hexdigest()!=scenario_sha:
        raise ContinuousCertificationError(ExposureStatus.ERROR,"SCENARIO_CHANGED_DURING_AUDIT")
    if result.get("orekit_data_sha256") != context.data_sha256:
        raise ContinuousCertificationError(ExposureStatus.ERROR,"OREKIT_DATA_CHANGED_DURING_AUDIT")
    evidence=dict(status="CONTINUOUS_PASS",receipt_schema_version=3,run_id=run_id,scenario_sha256=scenario_sha,
                  plan_sha256=plan_digest(plan),audit_version=AUDIT_VERSION,
                  **context.identity(),deadline_monotonic=deadline,
                  scan_step_s=result.get("scan_step_s"),boundary_precision_us=result.get("boundary_precision_us"),
                  predicate=result.get("predicate"),min_elevation_deg=min_elevation_deg,
                  evidence_kind=result.get("model"),
                  audit_result_sha256=plan_digest(result),certified_tasks=len(result["rows"]))
    evidence["settings_sha256"] = plan_digest({key:evidence[key] for key in
        ("scan_step_s", "boundary_precision_us", "predicate", "min_elevation_deg", "model_parameters")})
    validate_certification(evidence,run_id=run_id,scenario_sha=scenario_sha,plan=plan,context=context)
    check_deadline(deadline)
    return CertificationReceipt(json.dumps(evidence,sort_keys=True,allow_nan=False),_ISSUER)
