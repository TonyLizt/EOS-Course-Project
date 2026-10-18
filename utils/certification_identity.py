"""Process-frozen deployment and dataset identity. Restart after changing sources.

Trusted local deployment, not hostile-filesystem attestation. Endpoint hashes
cannot rule out temporary changes restored between checks.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import types
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = (
    "scripts/generate_caabs_development_scene.py",
    "utils/attitude_frames.py",
    "utils/certification_identity.py", "utils/continuous_exposure.py",
    "utils/visibility.py", "utils/time_parsing.py", "core/models.py",
    "schedulers/scenario_loader.py", "schedulers/constraint_model.py",
    "schedulers/source_windows.py",
    "schedulers/transition_utils.py", "schedulers/evaluation_metrics.py",
    "eos_system/verification.py", "eos_system/controller.py", "eos_system/storage.py",
    "eos_system/exporting.py", "eos_system/contracts.py", "eos_system/config.py",
    "eos_system/provenance.py", "eos_system/runner.py", "schedulers/schedule_output.py",
    "schedulers/balance_utils.py", "schedulers/timeliness_utils.py",
)
MODEL = {"propagation": "Orekit-Keplerian", "inertial_frame": "EME2000",
         "terrestrial_frame": "ITRF-IERS2010-simpleEOP", "ellipsoid": "WGS84",
         "attitude": "NadirRelative-TargetPointing-fixedBodyZ-v1", "time_scale": "UTC",
         "predicate": "elevation_and_stored_axis_limits_v1"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _code_key(code):
    def value(c):
        if isinstance(c, types.CodeType):
            return ("code", _code_key(c))
        if isinstance(c, frozenset):
            return ("frozenset", tuple(sorted((value(x) for x in c), key=repr)))
        if isinstance(c, tuple):
            return ("tuple", tuple(value(x) for x in c))
        return repr(c)
    return (code.co_code.hex(), tuple(value(c) for c in code.co_consts), code.co_names,
            code.co_varnames, code.co_freevars, code.co_cellvars, code.co_argcount,
            code.co_posonlyargcount, code.co_kwonlyargcount, code.co_flags, code.co_name,
            getattr(code, "co_exceptiontable", b"").hex())


def _compiled_keys(code):
    result = {_code_key(code)}
    for child in code.co_consts:
        if isinstance(child, types.CodeType):
            result.update(_compiled_keys(child))
    return result


def _capture_sources():
    result = {}
    for name in SOURCE_NAMES:
        path = ROOT/name
        raw = path.read_bytes()
        module = sys.modules.get(name[:-3].replace("/", "."))
        # Detect already imported A vs on-disk B at bootstrap. Initializing
        # modules execute the same trusted startup snapshot; no live reload.
        if module is not None:
            keys = _compiled_keys(compile(raw, str(path), "exec", dont_inherit=True))
            if getattr(getattr(module, "__spec__", None), "_initializing", False):
                # Include our own and continuous_exposure's executing module
                # frames: import-time disk B must never relabel compiled A.
                frame = sys._getframe()
                while frame is not None and not (frame.f_globals.get("__name__") == module.__name__
                                                  and frame.f_code.co_name == "<module>"):
                    frame = frame.f_back
                if frame is None or _code_key(frame.f_code) not in keys:
                    raise ValueError("INITIALIZING_MODULE_DIFFERS_FROM_DEPLOYMENT: " + name)
            functions = []
            for obj in vars(module).values():
                if getattr(obj, "__module__", None) != module.__name__:
                    continue
                if isinstance(obj, types.FunctionType):
                    functions.append(obj)
                elif isinstance(obj, type):
                    for member in vars(obj).values():
                        member = member.__func__ if isinstance(member, (staticmethod, classmethod)) else member
                        if isinstance(member, types.FunctionType) and member.__code__.co_filename == str(path):
                            functions.append(member)
            for function in functions:
                if _code_key(function.__code__) not in keys:
                    raise ValueError("LOADED_MODULE_DIFFERS_FROM_DEPLOYMENT: " + name)
        result[name] = hashlib.sha256(raw).hexdigest()
    return tuple(sorted(result.items()))


try:
    _SOURCES = _capture_sources()
    _BOOT_ERROR = None
except (OSError, ValueError, SyntaxError) as exc:
    _SOURCES = ()
    _BOOT_ERROR = str(exc)
_PID = os.getpid()
_GENERATION = uuid.uuid4().hex
_DEPLOYMENT = _digest(dict(_SOURCES))
_CONTEXTS = {}
_INVALIDATED_REASON = None
_REVOKED_DATA = set()
_LOCK = threading.Lock()


def disk_sources():
    return tuple(sorted((name, hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
                        for name in SOURCE_NAMES))


def assert_code_current():
    global _INVALIDATED_REASON
    if _INVALIDATED_REASON is None:
        try:
            if _BOOT_ERROR or os.getpid() != _PID or not _SOURCES or disk_sources() != _SOURCES:
                _INVALIDATED_REASON = str(_BOOT_ERROR or "identity mismatch")
        except OSError as exc:
            _INVALIDATED_REASON = "source unavailable: " + str(exc)
    if _INVALIDATED_REASON is not None:
        raise ValueError("CERTIFICATION_PROCESS_CODE_CHANGED_RESTART_REQUIRED: " + _INVALIDATED_REASON)


def source_identity():
    assert_code_current()
    return dict(_SOURCES)


@dataclass(frozen=True)
class CertificationContext:
    data_path: str
    data_sha256: str
    data_source: str
    source_files: tuple
    deployment_sha256: str
    process_generation: str
    model_json: str

    def identity(self):
        return dict(orekit_data_sha256=self.data_sha256, orekit_data_source=self.data_source,
                    source_files_sha256=dict(self.source_files), deployment_sha256=self.deployment_sha256,
                    process_generation=self.process_generation, model_parameters=json.loads(self.model_json))

    def check(self):
        assert_code_current()
        if (self.source_files != _SOURCES or self.deployment_sha256 != _DEPLOYMENT
                or self.process_generation != _GENERATION
                or self.model_json != json.dumps(MODEL, sort_keys=True)):
            raise ValueError("CERTIFICATION_CONTEXT_DEPLOYMENT_MISMATCH")
        try:
            if (self.data_source != Path(self.data_path).resolve().as_uri()
                    or hashlib.sha256(Path(self.data_path).read_bytes()).hexdigest() != self.data_sha256):
                _REVOKED_DATA.add(self.data_path)
        except OSError:
            _REVOKED_DATA.add(self.data_path)
            raise
        if self.data_path in _REVOKED_DATA:
            raise ValueError("OREKIT_DATA_IDENTITY_CHANGED_RESTART_REQUIRED")
        return self


def trusted_context(data_path=None):
    """Freeze a configured dataset independently of any untrusted receipt.

    Install configuration before Controller/Storage startup. Changed files at a
    previously frozen path are never adopted by the same running process.
    """
    assert_code_current()
    path = Path(data_path or os.environ.get("EOS_OREKIT_DATA") or ROOT/"utils/orekit-data.zip").resolve()
    with _LOCK:
        key = str(path)
        if key not in _CONTEXTS:
            _CONTEXTS[key] = CertificationContext(key, hashlib.sha256(path.read_bytes()).hexdigest(),
                path.as_uri(), _SOURCES, _DEPLOYMENT, _GENERATION, json.dumps(MODEL, sort_keys=True))
        context = _CONTEXTS[key]
    return context.check()
