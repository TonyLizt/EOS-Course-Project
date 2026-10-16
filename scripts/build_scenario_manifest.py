#!/usr/bin/env python3
"""Read completed, archived EOS scenarios without importing the simulator.

Two complete reads bind validation to a SHA-256 and detect changes between
passes. ijson retains one top-level array item at a time; without it the stdlib
fallback is limited to 16 MiB. Neither method proves producer completion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import sys
from datetime import datetime, timedelta, timezone

try:
    import ijson
except ImportError:
    ijson = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SMALL_FILE_LIMIT = 16 * 1024 * 1024
BLOCK_SIZE = 1024 * 1024
REPORT_NAMES = ("scenario_manifest.csv", "scenario_manifest.json", "scenario_validation_report.json")
ARRAY_FIELDS = {"satellites", "missions", "ground_stations", "observation_windows", "communication_windows"}
FIELDS = (
    "registry_id", "internal_scenario_id", "filename", "source_path", "sha256", "file_size_bytes",
    "satellite_count", "mission_count", "duration_days", "start_time", "end_time", "time_step_s",
    "observation_entry_count", "observation_segment_count", "missions_with_windows", "window_coverage_ratio",
    "communication_window_count", "communication_entry_count", "distribution_type", "distribution_evidence",
    "validation_status", "generator_version", "generator_seed", "source_dataset", "source_group_id",
    "provenance_evidence", "parser_mode",
)


class AuditError(ValueError):
    pass


class UniqueDict(dict):
    """Reject duplicate JSON keys before a decoder can silently overwrite IDs."""
    def __setitem__(self, key, value):
        if key in self:
            raise AuditError(f"duplicate JSON key: {key}")
        super().__setitem__(key, value)


def unique_pairs(pairs):
    result = UniqueDict()
    for key, value in pairs:
        result[key] = value
    return result


def reject_constant(value):
    raise AuditError(f"non-finite JSON number: {value}")


def within(path, root):
    return path == root or root in path.parents


def checked_path(path, *, directory=False):
    """Check lexical and resolved paths BEFORE enumerating/opening any data."""
    lexical = Path(os.path.abspath(Path(path).expanduser()))
    protected = (PROJECT_ROOT / "input", PROJECT_ROOT / "output")
    for root in protected:
        if within(lexical, root) or (directory and within(root, lexical)):
            raise AuditError(f"protected directory: {lexical}")
    resolved = lexical.resolve()
    for root in protected:
        if within(resolved, root) or (directory and within(root, resolved)):
            raise AuditError(f"protected directory alias: {lexical}")
    return resolved


def fingerprint(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


class HashReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, size=-1):
        block = self.stream.read(min(size, BLOCK_SIZE) if size >= 0 else BLOCK_SIZE)
        self.digest.update(block)
        self.count += len(block)
        return block


def _stream_records(reader):
    """Yield (field, kind, value), retaining at most one outer array item.

    Parse all fields, even unused ones, so trailing data and malformed JSON fail.
    ObjectBuilder's map_type preserves duplicate-key rejection at every depth.
    """
    events = iter(ijson.parse(reader, use_float=True))
    first = next(events, None)
    if first != ("", "start_map", None):
        raise AuditError("JSON root must be an object")
    seen = set()

    def value_from(event):
        builder = ijson.common.ObjectBuilder(map_type=UniqueDict)
        _, event_type, value = event
        builder.event(event_type, value)
        depth = int(event_type in ("start_map", "start_array"))
        while depth:
            _, event_type, value = next(events)
            builder.event(event_type, value)
            depth += int(event_type in ("start_map", "start_array"))
            depth -= int(event_type in ("end_map", "end_array"))
        return builder.value

    while True:
        event = next(events)
        if event == ("", "end_map", None):
            break
        if event[0:2] != ("", "map_key") or event[2] in seen:
            raise AuditError(f"invalid/duplicate top-level key: {event[2]}")
        key = event[2]
        seen.add(key)
        event = next(events)
        if key in ARRAY_FIELDS and event[1] == "start_array":
            yield key, "array", None
            while True:
                event = next(events)
                if event[1] == "end_array":
                    break
                yield key, "item", value_from(event)
        else:
            yield key, "value", value_from(event)
    if next(events, None) is not None:
        raise AuditError("trailing JSON data")


def read_pass(path, consume, *, force_small=False):
    supplied = Path(path)
    path = checked_path(supplied)
    if supplied.is_symlink():
        raise AuditError("scenario file symlinks are not accepted; specify a completed regular file archive")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise AuditError("not a regular file")
    small = force_small or ijson is None
    if small and before.st_size > SMALL_FILE_LIMIT:
        raise AuditError("file exceeds 16 MiB stdlib limit; use an environment with ijson>=3.3 (not installed automatically)")
    with path.open("rb") as stream:
        if fingerprint(os.fstat(stream.fileno())) != fingerprint(before):
            raise AuditError("file changed before opening")
        reader = HashReader(stream)
        if small:
            # Bounded fallback. The buffer is released before object validation.
            buffer = io.BytesIO()
            while True:
                block = reader.read(BLOCK_SIZE)
                if not block:
                    break
                if reader.count > SMALL_FILE_LIMIT:
                    raise AuditError("file grew beyond the 16 MiB fallback limit")
                buffer.write(block)
            data = json.loads(buffer.getvalue(), object_pairs_hook=unique_pairs, parse_constant=reject_constant)
            buffer.close()
            if not isinstance(data, dict):
                raise AuditError("JSON root must be an object")
            for key, value in data.items():
                if key in ARRAY_FIELDS and isinstance(value, list):
                    consume(key, "array", None)
                    for item in value:
                        consume(key, "item", item)
                else:
                    consume(key, "value", value)
        else:
            for record in _stream_records(reader):
                consume(*record)
        if (reader.count != before.st_size or
                fingerprint(os.fstat(stream.fileno())) != fingerprint(before) or
                fingerprint(path.stat()) != fingerprint(before)):
            raise AuditError("file changed during reading")
    return reader.digest.hexdigest(), fingerprint(before), "stdlib-bounded" if small else "ijson-outer-item"


def parse_time(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected ISO timestamp string")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    # Match scenario_loader: aware -> UTC naive; naive retains wall time.
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def registry_id(row):
    # Content-only identity: no filename label or guessed historical provenance.
    return f"s{row['satellite_count']}_m{row['mission_count']}_t{row['duration_days']:g}d_{row['sha256']}"


class Validator:
    def __init__(self, path):
        self.path = path
        self.issues = []
        self.level = "PASS"
        self.suppressed = 0
        self.top = {}
        self.present = set()
        self.sats, self.missions, self.stations = {}, {}, {}
        self.covered = set()
        self.start = self.end = None
        self.step = 1.0
        self.row = dict.fromkeys(FIELDS)
        self.row.update(filename=path.name, source_path=str(path), observation_entry_count=0,
                        observation_segment_count=0, communication_entry_count=0, communication_window_count=0)

    def issue(self, level, check, field, reason):
        if {"PASS": 0, "WARN": 1, "FAIL": 2}[level] > {"PASS": 0, "WARN": 1, "FAIL": 2}[self.level]:
            self.level = level
        if len(self.issues) < 1000:
            self.issues.append(dict(check=check, level=level, reason=reason, file=str(self.path), field=field))
        else:
            self.suppressed += 1

    def number(self, value, field, *, positive=False, nonnegative=False):
        try:
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError()
            number = float(value)
            if not math.isfinite(number) or (positive and number <= 0) or (nonnegative and number < 0):
                raise ValueError()
            return number
        except (ValueError, TypeError, OverflowError):
            self.issue("FAIL", "numeric", field, "expected finite " + ("positive" if positive else "nonnegative" if nonnegative else "numeric") + " value")
            return None

    def mapping(self, value, field):
        if not isinstance(value, dict):
            self.issue("FAIL", "schema", field, "expected object")
            return {}
        return value

    def identifier(self, value, field):
        if not isinstance(value, str) or not value.strip():
            self.issue("FAIL", "identifier", field, "expected nonempty string ID")
            return None
        return value

    def first(self, key, kind, value):
        self.present.add(key)
        if kind != "array":
            self.finite_json(value, key)
        if key in ARRAY_FIELDS:
            if kind == "value":
                self.issue("FAIL", "schema", key, "expected array")
            elif kind == "item" and key in ("satellites", "missions", "ground_stations"):
                self.entity(key, value)
        elif kind == "value":
            # Unknown top-level values are parsed but not retained.
            if key in ("scenario_id", "metadata", "distribution_type"):
                self.top[key] = value

    def finite_json(self, value, field):
        """Also catch overflow (1e999) in fields outside the scheduler subset."""
        if isinstance(value, float) and not math.isfinite(value):
            self.issue("FAIL", "numeric", field, "non-finite JSON number")
        elif isinstance(value, dict):
            for key, item in value.items():
                self.finite_json(item, field + "." + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.finite_json(item, f"{field}[{index}]")

    def entity(self, key, value):
        value = self.mapping(value, key)
        ident = self.identifier(value.get("id"), key + ".id")
        if ident is None:
            return
        field = f"{key}[id={ident}]"
        target = {"satellites": self.sats, "missions": self.missions, "ground_stations": self.stations}[key]
        if ident in target:
            self.issue("FAIL", "duplicate_id", field, "duplicate entity ID in list; loader would overwrite it")
        target[ident] = {}
        if key == "missions":
            self.number(value.get("priority", 1), field + ".priority", nonnegative=True)
            req = value.get("observation_requirement")
            duration = self.number(self.mapping(req, field + ".observation_requirement").get("duration_s", 0),
                                   field + ".duration_s", nonnegative=True) if req is not None else 0
            target[ident] = duration
            if duration == 0:
                self.issue("WARN", "duration", field, "zero/missing duration is loader-compatible but candidate builder cannot schedule it")
        elif key == "satellites":
            specs = self.mapping(value.get("satellite_specs") or {}, field + ".satellite_specs")
            man = self.mapping(value.get("maneuverability_capability") or {}, field + ".maneuverability_capability")
            for group, prefix in ((specs, "satellite_specs"), (man, "maneuverability_capability")):
                for name, number in group.items():
                    if name.startswith(("max_", "slew_rate", "stabilization_time")) and number is not None:
                        self.number(number, field + "." + prefix + "." + name, nonnegative=True)
            for capability, member, id_key in (("observation_capability", "sensors", "sensor_id"),
                                               ("communication_capability", "antennas", "antenna_id")):
                cap = self.mapping(value.get(capability) or {}, field + "." + capability)
                items = cap.get(member) or []
                if not isinstance(items, list):
                    self.issue("FAIL", "schema", field + "." + member, "expected list")
                    continue
                seen = set()
                for item in items:
                    item = self.mapping(item, field + "." + member)
                    item_id = self.identifier(item.get(id_key), field + "." + id_key)
                    if item_id in seen:
                        self.issue("FAIL", "duplicate_id", field + "." + id_key, str(item_id))
                    if item_id is not None:
                        seen.add(item_id)
                    for name in ("data_rate_Mbps", "power_consumption_W", "field_of_view_deg", "observation_swath_width_km"):
                        if item.get(name) is not None:
                            self.number(item[name], field + "." + member + "." + name, nonnegative=True)
                if member == "sensors":
                    target[ident] = seen

    def prepare(self):
        if "metadata" not in self.top:
            self.issue("FAIL", "required", "metadata", "loader requires metadata")
        meta = self.mapping(self.top.get("metadata"), "metadata")
        sid = self.top.get("scenario_id")
        if "scenario_id" in self.top:
            self.identifier(sid, "scenario_id")
        else:
            self.issue("WARN", "internal_id", "scenario_id", "missing; loader falls back to filename stem")
        self.row["internal_scenario_id"] = sid if isinstance(sid, str) else None
        duration = self.number(meta.get("duration"), "metadata.duration", positive=True)
        self.step = self.number(meta.get("time_step", 1), "metadata.time_step", positive=True)
        if "time_step" not in meta:
            self.issue("WARN", "sampling", "metadata.time_step", "not recorded; loader defaults to 1 s")
        try:
            self.start = parse_time(meta.get("creation_time"))
            self.end = self.start + timedelta(seconds=duration) if duration is not None else None
            self.row["start_time"] = meta["creation_time"]
            # Preserve explicit offset in presentation; calculations follow loader.
            original = datetime.fromisoformat(meta["creation_time"].strip().replace("Z", "+00:00"))
            self.row["end_time"] = (original + timedelta(seconds=duration)).isoformat() if duration is not None else None
        except (ValueError, TypeError, OverflowError):
            self.issue("FAIL", "time", "metadata.creation_time/duration", "invalid or unrepresentable scene interval")
        self.row.update(duration_days=duration / 86400 if duration is not None else None,
                        time_step_s=self.step, satellite_count=len(self.sats), mission_count=len(self.missions))
        for key in ("satellites", "missions", "observation_windows"):
            if key not in self.present:
                self.issue("WARN", "missing_collection", key, "loader defaults to empty list")
        extra = self.mapping(meta.get("extra") or {}, "metadata.extra")
        for name in ("generator_version", "generator_seed", "source_dataset", "source_group_id"):
            val = extra.get(name)
            if val is not None and (isinstance(val, bool) or not isinstance(val, (str, int))):
                self.issue("WARN", "provenance", "metadata.extra." + name, "unsupported provenance value; left empty")
            else:
                self.row[name] = val
        self.row["provenance_evidence"] = "metadata.extra (file-declared; not independently verified)"
        missing = [k for k in ("generator_version", "generator_seed", "source_dataset", "source_group_id") if self.row[k] is None]
        if missing:
            self.issue("WARN", "provenance", "metadata.extra", "not recorded: " + ", ".join(missing))
        distribution = extra.get("distribution_type", self.top.get("distribution_type"))
        if isinstance(distribution, (str, int)) and not isinstance(distribution, bool):
            self.row.update(distribution_type=str(distribution), distribution_evidence="file-declared")
        else:
            # Filename is only a label, never input to content identity.
            import re
            match = re.search(r"(?:^|_)dist([01])(?:_|$)", self.path.stem)
            self.row.update(distribution_type="dist" + match[1] if match else None,
                            distribution_evidence="filename only; unverified" if match else "not recorded")
            self.issue("WARN", "distribution", "distribution_type", self.row["distribution_evidence"])

    def attitude(self, tw, ow, field, seconds, step):
        agile = tw.get("agile_data", ow.get("agile_data"))
        fixed = tw.get("non_agile_data", ow.get("non_agile_data"))
        if agile is None:
            self.issue("WARN", "attitude_missing", field + ".agile_data", "agile transitions may fall back to 11.66 s; formal verification may reject")
        elif isinstance(agile, dict) and any(k in agile for k in ("pitch_angles", "yaw_angles", "roll_angles")):
            arrays = []
            for key in ("pitch_angles", "yaw_angles", "roll_angles"):
                val = agile.get(key)
                if val is None:
                    self.issue("WARN", "attitude_partial", field + "." + key, "missing axis; current transition extraction fails")
                elif not isinstance(val, list) or not val:
                    self.issue("FAIL", "attitude_array", field + "." + key, "expected nonempty angle array")
                else:
                    arrays.append(val)
                    for angle in val:
                        self.number(angle, field + "." + key)
            if len({len(a) for a in arrays}) > 1:
                self.issue("FAIL", "attitude_length", field, "angle array lengths differ")
            if arrays and seconds is not None and step:
                n = len(arrays[0])
                ratio = seconds / step
                if not math.isfinite(ratio):
                    self.issue("FAIL", "sampling", field, "sample count overflows")
                elif n not in {max(1, math.ceil(ratio - 1e-9)), math.floor(ratio + 1e-9) + 1}:
                    self.issue("WARN", "sampling_length", field, "sample count incompatible with interval/step; endpoint and legacy sampling require review")
        else:
            self.legacy_attitude(agile, field + ".agile_data")
        if fixed is None:
            self.issue("WARN", "attitude_missing", field + ".non_agile_data", "fixed representative attitude not recorded")
        elif isinstance(fixed, dict):
            for key in ("pitch_angle", "yaw_angle", "roll_angle"):
                if key not in fixed:
                    self.issue("WARN", "attitude_partial", field + ".non_agile_data." + key, "missing representative axis")
                else:
                    self.number(fixed[key], field + ".non_agile_data." + key)
        else:
            self.issue("FAIL", "attitude_schema", field + ".non_agile_data", "expected object")

    def legacy_attitude(self, value, field):
        # Mirror the documented formats of extract_attitude_from_angles without
        # importing project packages. Check ALL samples, not only endpoints.
        if not isinstance(value, (dict, list)):
            self.issue("FAIL", "attitude_schema", field, "expected angle object or legacy record list")
            return
        records = None
        if isinstance(value, list) and value:
            records = value
        elif isinstance(value, dict):
            for keys in (("roll", "pitch", "yaw"), ("gamma", "pi", "psi")):
                if all(k in value for k in keys):
                    arrays = [value[k] for k in keys]
                    if all(isinstance(a, list) and a for a in arrays):
                        if len({len(a) for a in arrays}) != 1:
                            self.issue("FAIL", "attitude_length", field, "legacy axis lengths differ")
                        records = zip(*arrays)
                        for a in arrays:
                            for n in a:
                                self.number(n, field)
                    break
            if records is None:
                records = [v for v in value.values() if isinstance(v, dict)] or None
        valid = bool(records)
        for record in records or []:
            if isinstance(record, dict):
                keys = next((k for k in (("roll", "pitch", "yaw"), ("gamma", "pi", "psi")) if all(x in record for x in k)), None)
                numbers = [record[k] for k in keys] if keys else []
            elif isinstance(record, (list, tuple)) and len(record) >= 3:
                numbers = record[:3]
            else:
                numbers = []
            valid = bool(numbers) and valid
            for n in numbers:
                self.number(n, field)
        self.issue("WARN", "legacy_attitude", field, "legacy angle representation; sampling needs review" if valid else "current transition extractor cannot parse attitude")

    def second(self, key, kind, value):
        if key not in ("observation_windows", "communication_windows") or kind != "item":
            return
        observation = key == "observation_windows"
        count_key = "observation_entry_count" if observation else "communication_entry_count"
        segment_key = "observation_segment_count" if observation else "communication_window_count"
        index = self.row[count_key]
        self.row[count_key] += 1
        field = f"{key}[{index}]"
        ow = self.mapping(value, field)
        sid = self.identifier(ow.get("satellite_id"), field + ".satellite_id")
        other_key = "mission_id" if observation else "ground_station_id"
        other = self.identifier(ow.get(other_key), field + "." + other_key)
        exists = sid in self.sats and other in (self.missions if observation else self.stations)
        if sid not in self.sats:
            self.issue("FAIL", "reference", field + ".satellite_id", f"unknown satellite: {sid}")
        if other not in (self.missions if observation else self.stations):
            self.issue("FAIL", "reference", field + "." + other_key, f"unknown reference: {other}")
        if observation:
            sensor = self.identifier(ow.get("sensor_id"), field + ".sensor_id")
            if sensor not in self.sats.get(sid, set()):
                self.issue("FAIL", "reference", field + ".sensor_id", f"unknown sensor on satellite {sid}: {sensor}")
                exists = False
        segments = ow.get("time_windows", [])
        if not isinstance(segments, list):
            self.issue("FAIL", "schema", field + ".time_windows", "expected list")
            return
        for i, raw in enumerate(segments):
            self.row[segment_key] += 1
            loc = f"{field}.time_windows[{i}] (satellite={sid}, {other_key}={other})"
            tw = self.mapping(raw, loc)
            seconds = None
            interval_ok = False
            try:
                start, end = parse_time(tw.get("start_time")), parse_time(tw.get("end_time"))
                seconds = (end - start).total_seconds()
                if end <= start:
                    raise ValueError("end must be after start")
                if self.start is not None and self.end is not None and not (self.start <= start < end <= self.end):
                    raise ValueError("window outside scenario interval")
                interval_ok = self.start is not None and self.end is not None
            except (ValueError, TypeError, OverflowError) as exc:
                self.issue("FAIL", "window_time", loc, str(exc))
            if observation:
                step = self.number(tw.get("time_step", ow.get("time_step", self.step)), loc + ".time_step", positive=True)
                orbit = tw.get("orbit_number", ow.get("orbit_number", 0))
                if orbit is not None:
                    number = self.number(orbit, loc + ".orbit_number", nonnegative=True)
                    if number is not None and not number.is_integer():
                        self.issue("FAIL", "orbit_number", loc, "expected integral orbit number")
                self.attitude(tw, ow, loc, seconds, step)
                required = self.missions.get(other)
                if exists and interval_ok and required is not None and required > 0 and seconds >= required and step:
                    self.covered.add(other)

    def finish(self):
        self.row["missions_with_windows"] = len(self.covered)
        self.row["window_coverage_ratio"] = len(self.covered) / len(self.missions) if self.missions else 0.0
        if not self.sats or not self.missions or len(self.covered) < len(self.missions) or not self.covered:
            self.issue("WARN", "coverage", "observation_windows", "empty entities or missions without a time-valid, sufficiently long referenced window; not a scheduling feasibility test")
        if self.level == "PASS":
            self.issue("PASS", "basic_validation", "$", "current schema, references, time intervals and inspected numeric/attitude fields passed; no physics feasibility claim")
        self.row["validation_status"] = self.level
        if self.level != "FAIL":
            self.row["registry_id"] = registry_id(self.row)


def audit_file(path, *, force_small=False):
    path = Path(os.path.abspath(Path(path).expanduser()))
    audit = Validator(path)
    try:
        digest, stamp, mode = read_pass(path, audit.first, force_small=force_small)
        audit.prepare()
        digest2, stamp2, _ = read_pass(path, audit.second, force_small=force_small)
        if digest != digest2 or stamp != stamp2:
            raise AuditError("file changed between complete reads")
        audit.row.update(sha256=digest, file_size_bytes=stamp[2], parser_mode=mode)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, StopIteration) as exc:
        audit.issue("FAIL", "read_or_parse", "$", str(exc))
    except Exception as exc:
        # Optional ijson backends have different parse exception base classes.
        if ijson is not None and isinstance(exc, ijson.JSONError):
            audit.issue("FAIL", "read_or_parse", "$", str(exc))
        else:
            raise
    audit.finish()
    return dict(record=audit.row, status=audit.level, checks=audit.issues, suppressed_checks=audit.suppressed)


def reconcile(results):
    def note(result, level, check, reason):
        result["checks"].append(dict(check=check, level=level, reason=reason,
                                     file=result["record"]["source_path"], field="registry_id"))
        if result["status"] != "FAIL":
            result["status"] = result["record"]["validation_status"] = level
        if level == "FAIL":
            result["record"]["registry_id"] = None

    for field, check in (("registry_id", "registry_collision"), ("filename", "filename_conflict"),
                         ("internal_scenario_id", "internal_id_reuse"), ("sha256", "duplicate_content")):
        groups = {}
        for result in results:
            row = result["record"]
            if row[field] is not None and row["sha256"] is not None:
                groups.setdefault(row[field], []).append(result)
        for value, group in groups.items():
            if len(group) < 2:
                continue
            different = len({r["record"]["sha256"] for r in group}) > 1
            if field == "registry_id" and not different:
                continue
            if field == "filename" and not different:
                continue
            for result in group:
                note(result, "FAIL" if field == "registry_id" else "WARN", check,
                     f"{field}={value}: {len(group)} files; " + ("different content" if different else "identical bytes; shared registry identity, paths retained"))
    return results


def build_manifest(scenario_dirs, out_dir, *, force_small=False):
    roots = [checked_path(p, directory=True) for p in scenario_dirs]
    out = checked_path(out_dir, directory=True)
    for root in roots:
        if within(out, root) or within(root, out):
            raise AuditError("report and scenario directories must be disjoint (including ancestors)")
        if not root.is_dir():
            raise AuditError(f"scenario directory does not exist: {root}")
    if out.exists() and not out.is_dir():
        raise AuditError("report output is not a directory")
    if any((out / name).exists() or (out / name).is_symlink() for name in REPORT_NAMES):
        raise AuditError("report files already exist; choose a fresh output directory")
    # No recursion. The dedicated directories explicitly identify all input JSONs.
    paths = sorted({p for root in roots for p in root.iterdir() if p.suffix.lower() == ".json"})
    if not paths:
        raise AuditError("no JSON files in the explicitly supplied completed directories")
    results = reconcile([audit_file(p, force_small=force_small) for p in paths])
    records = [r["record"] for r in results if r["status"] != "FAIL"]
    report = dict(schema_version=1, scope="basic data validation; not schedule/physics feasibility",
                  completion_limit="stable stat/hash cannot prove producer completion; use completed immutable archives",
                  registered_file_count=len(records), unique_registry_count=len({r['registry_id'] for r in records}),
                  results=results)
    out.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also refuses symlinks and concurrent report replacement.
    # Reports are not a three-file transaction: a disk error leaves a partial run.
    with (out / REPORT_NAMES[0]).open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    with (out / REPORT_NAMES[1]).open("x", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    with (out / REPORT_NAMES[2]).open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit and register completed EOS scenario archives (read-only, non-recursive).",
                                     epilog="Never scan running output/. No simulator/JVM imports. Exit: 0 PASS/WARN, 1 file FAIL, 2 usage/I/O error.")
    parser.add_argument("--scenario-dir", required=True, action="append", type=Path,
                        help="completed archive directory; reads direct *.json only; repeat for multiple archives")
    parser.add_argument("--out-dir", required=True, type=Path,
                        help="separate report directory; refuses protected paths and existing report files")
    args = parser.parse_args(argv)
    try:
        report = build_manifest(args.scenario_dir, args.out_dir)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    counts = {level: sum(r["status"] == level for r in report["results"]) for level in ("PASS", "WARN", "FAIL")}
    print(json.dumps(dict(counts=counts, registered_file_count=report["registered_file_count"],
                          unique_registry_count=report["unique_registry_count"], reports=str(args.out_dir.resolve()))))
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
