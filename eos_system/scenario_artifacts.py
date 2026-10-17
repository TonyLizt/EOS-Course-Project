"""R1-02 artifact inventory checks; no registration, approval or publication IO.

All paths are explicit: repository-relative or relative to a caller-bound local
evidence root. A matching digest establishes bytes, never historical authorship,
ML independence, continuous exposure certification or release authorization.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat

SCHEMA_VERSION = "scenario_artifact_index_v1"
STATIC_HASH_VERSION = "exclude_two_window_fields_canonical_json_v1"
LEVELS = {"PASS": 0, "WARN": 1, "FAIL": 2}
EVIDENCE_LEVELS = {"MEASURED_BYTES", "DECLARED_CORROBORATED", "DECLARED_ONLY", "FILENAME_ONLY", "NOT_VERIFIED"}


def _pairs(items):
    obj = {}
    for key, value in items:
        if key in obj:
            raise ValueError("duplicate JSON key: " + key)
        obj[key] = value
    return obj


def _constant(value):
    raise ValueError("non-finite JSON constant: " + value)


def load_index(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_pairs, parse_constant=_constant)


def is_sha256(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def file_sha256(path: Path) -> str:
    """Hash only ordinary files, detecting changes across the complete read."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("symlink files are not accepted")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("expected a regular file")
    fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        if fingerprint(before) != fingerprint(os.fstat(stream.fileno())):
            raise ValueError("file changed before opening")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        if fingerprint(before) != fingerprint(os.fstat(stream.fileno())):
            raise ValueError("file changed during read")
    if fingerprint(before) != fingerprint(path.stat()):
        raise ValueError("file changed during read")
    return h.hexdigest()


def resolve_location(location: dict, repo_root: Path, evidence_roots: dict[str, Path]) -> Path:
    """Never interpret a recorded producer path as a portable locator."""
    if not isinstance(location, dict):
        raise ValueError("location must be an object")
    kind, value = location.get("kind"), location.get("path")
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("location.path must be a canonical POSIX relative path")
    rel = PurePosixPath(value)
    if rel.is_absolute() or PureWindowsPath(value).drive or ".." in rel.parts or rel.as_posix() != value or value == ".":
        raise ValueError("absolute, escaping or noncanonical location")
    if kind == "repo_relative":
        base = Path(repo_root).resolve()
    elif kind == "local_evidence":
        name = location.get("root")
        if not isinstance(name, str) or not name:
            raise ValueError("local evidence requires a root name")
        if name not in evidence_roots:
            raise LookupError("local evidence root is not bound: " + name)
        base = Path(evidence_roots[name]).resolve()
    else:
        raise ValueError("unknown location kind")
    path = base
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("symlink component is not accepted")
    resolved = path.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError("location escapes its root")
    return resolved


def inspect_scenario(path: Path) -> dict:
    """Use the existing bounded/streaming reader without changing Manifest.

    Discard dynamic windows one outer item at a time; retain ALL other fields,
    including unknown fields. This works with the 149 MiB Legacy on ijson hosts.
    The existing reader refuses >16 MiB if ijson is unavailable.
    """
    from scripts.build_scenario_manifest import read_pass
    static_data = {}

    def consume(key, kind, value):
        if key in {"observation_windows", "communication_windows"}:
            return
        if kind == "array":
            static_data[key] = []
        elif kind == "item":
            static_data[key].append(value)
        else:
            static_data[key] = value

    digest, stamp, mode = read_pass(Path(path), consume)
    meta = static_data.get("metadata")
    if not isinstance(meta, dict):
        raise ValueError("scenario requires metadata")
    duration = meta.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("scenario requires a finite positive duration")
    if not isinstance(static_data.get("satellites"), list) or not isinstance(static_data.get("missions"), list):
        raise ValueError("scenario satellites and missions must be arrays")
    n, m = len(static_data["satellites"]), len(static_data["missions"])
    sid = static_data.get("scenario_id")
    if not isinstance(sid, str) or not sid:
        raise ValueError("missing internal scenario ID")
    canonical = json.dumps(static_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"sha256": digest, "size_bytes": stamp[2], "static_data_sha256": hashlib.sha256(canonical).hexdigest(),
            "registry_id": f"s{n}_m{m}_t{duration / 86400:g}d_{digest}", "internal_scenario_id": sid,
            "satellite_count": n, "mission_count": m, "duration_days": duration / 86400, "parser_mode": mode}


def verify_index(index: dict, *, repo_root: Path, evidence_roots: dict[str, Path] | None = None) -> dict:
    """Return scoped PASS/WARN/FAIL checks. No output files or external writes."""
    roots = evidence_roots or {}
    checks, nodes, available, details = [], {}, {}, {}

    def note(level, category, code, subject, reason):
        checks.append(dict(level=level, category=category, code=code, subject=subject, reason=reason))

    def invalid(subject, reason):
        note("FAIL", "INVALID_IDENTITY", "INVALID_INDEX", subject, reason)

    def finish():
        level = max((x["level"] for x in checks), key=LEVELS.get, default="PASS")
        return {"schema_version": "scenario_artifact_check_v1", "scope": "read-only artifact identity and declared lineage; no approval or continuity certification",
                "status": level, "counts": {l: sum(x["level"] == l for x in checks) for l in LEVELS},
                "checks": checks, "scenario_details": details}

    if not isinstance(index, dict) or index.get("schema_version") != SCHEMA_VERSION:
        invalid("$", "unsupported or missing index schema_version")
        return finish()
    for collection in ("raw_inputs", "scenario_artifacts", "evidence"):
        records = index.get(collection)
        if not isinstance(records, list):
            invalid(collection, "expected a list")
            continue
        for row in records:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row.get("id"):
                invalid(collection, "expected an object with a nonempty id")
                continue
            key = row["id"]
            if key in nodes:
                invalid(key, "duplicate indexed id")
                continue
            nodes[key] = row
            typ = row.get("artifact_type")
            if (collection == "raw_inputs" and typ not in ("raw_satellites", "raw_cities") or
                    collection == "scenario_artifacts" and typ not in ("legacy", "candidate") or
                    collection == "evidence" and typ != "evidence"):
                invalid(key, "artifact type does not belong in this collection")
            if not is_sha256(row.get("sha256")):
                invalid(key, "expected a complete lowercase SHA-256")
                continue
            size = row.get("size_bytes")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                invalid(key, "expected nonnegative integer size_bytes")
                continue
            location = row.get("location")
            try:
                path = resolve_location(location, repo_root, roots)
                actual = file_sha256(path)
                if actual != row["sha256"] or path.stat().st_size != size:
                    note("FAIL", "CONTRADICTORY_EVIDENCE", "FILE_IDENTITY_MISMATCH", key, "actual SHA/size differs from index")
                    continue
                available[key] = path
                note("PASS", "VERIFIED", "FILE_IDENTITY", key, "actual complete file SHA and size match")
                if typ in ("legacy", "candidate"):
                    info = inspect_scenario(path)
                    fields = ("sha256", "static_data_sha256", "registry_id", "internal_scenario_id", "satellite_count", "mission_count", "duration_days")
                    if any(info.get(field) != row.get(field) for field in fields):
                        note("FAIL", "CONTRADICTORY_EVIDENCE", "SCENARIO_IDENTITY_MISMATCH", key, "actual content identity or static projection differs")
                        available.pop(key)
                    else:
                        details[key] = info
                        note("PASS", "VERIFIED", "SCENARIO_IDENTITY", key, "content-derived registry ID and static SHA match; no provenance inference")
            except (LookupError, FileNotFoundError) as exc:
                note("WARN", "MISSING_EVIDENCE", "FILE_UNAVAILABLE", key, str(exc))
            except PermissionError as exc:
                note("WARN", "MISSING_EVIDENCE", "FILE_UNREADABLE", key, str(exc))
            except (OSError, ValueError, TypeError) as exc:
                invalid(key, str(exc))

    scenarios = index.get("scenario_artifacts", [])
    if not isinstance(scenarios, list):
        scenarios = []
    registry_ids = {}
    candidates = []
    for row in scenarios:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        key = row["id"]
        rid = row.get("registry_id")
        if not isinstance(rid, str) or not rid.endswith("_" + str(row.get("sha256"))) or key != rid:
            invalid(key, "id must equal content registry_id ending in complete scenario SHA")
        if isinstance(rid, str) and rid in registry_ids and registry_ids[rid] != row.get("sha256"):
            invalid(key, "same registry ID refers to different content")
        registry_ids[str(rid)] = row.get("sha256")
        if row.get("static_hash_version") != STATIC_HASH_VERSION or not is_sha256(row.get("static_data_sha256")):
            invalid(key, "invalid static hash identity/version")
        if row.get("lineage_group_id") is not None:
            invalid(key, "this historical collection has no certified ML lineage_group_id")
        if row.get("missing_fields"):
            note("WARN", "MISSING_EVIDENCE", "HISTORICAL_FIELDS_UNKNOWN", key, ", ".join(map(str, row["missing_fields"])))
        if row.get("distribution_evidence") == "FILENAME_ONLY":
            note("WARN", "MISSING_EVIDENCE", "DISTRIBUTION_FILENAME_ONLY", key, "distribution label is not authenticated historical generation evidence")
        refs = row.get("evidence_refs", [])
        if not isinstance(refs, list):
            invalid(key, "evidence_refs must be a list")
            refs = []
        for ref in refs:
            if not isinstance(ref, str) or ref not in nodes or nodes[ref].get("artifact_type") != "evidence":
                invalid(key, "unknown or wrongly typed evidence reference: " + str(ref))
        if row.get("artifact_type") != "candidate":
            continue
        candidates.append(row.get("sha256"))
        if row.get("publication_status") != "candidate_only" or row.get("formal_release_eligible") is not False:
            invalid(key, "frozen candidates must remain candidate_only and ineligible for release")
        continuity = row.get("continuous_exposure", {})
        if not isinstance(continuity, dict) or continuity.get("status") != "INCONCLUSIVE" or continuity.get("reason") != "NO_CONTINUITY_CERTIFICATE":
            invalid(key, "frozen exposure findings must remain INCONCLUSIVE / NO_CONTINUITY_CERTIFICATE")
        side_id = row.get("sidecar_ref")
        side_node = nodes.get(side_id) if isinstance(side_id, str) else None
        if not side_node or side_node.get("role") != "producer_sidecar":
            invalid(key, "candidate requires a referenced producer sidecar identity")
        elif side_id not in available:
            note("WARN", "MISSING_EVIDENCE", "SIDECAR_UNAVAILABLE", key, "cannot verify declared parent without the original sidecar")
        else:
            try:
                side_path = available[side_id]
                if side_path.stat().st_size > 1024 * 1024:
                    raise ValueError("sidecar exceeds 1 MiB")
                side = load_index(side_path)
                if file_sha256(side_path) != side_node["sha256"]:
                    raise ValueError("sidecar changed while parsing")
                expected = {"scenario_sha256": row["sha256"], "registry_id": rid,
                            "parent_scenario_sha256": row.get("parent_scenario_sha256"),
                            "static_data_sha256": row.get("static_data_sha256"),
                            "legacy_static_sha256": row.get("static_data_sha256"),
                            "publication_status": "candidate_only", "formal_release_eligible": False, "completion_status": "complete"}
                if not isinstance(side, dict) or any(side.get(k) != v for k, v in expected.items()):
                    note("FAIL", "CONTRADICTORY_EVIDENCE", "SIDECAR_BINDING_MISMATCH", key, "sidecar does not match indexed result/parent/static/registry/completion/state")
                elif not isinstance(row.get("producer_identity"), dict) or side.get("source_files_sha256") != row["producer_identity"].get("source_files_sha256"):
                    note("FAIL", "CONTRADICTORY_EVIDENCE", "PRODUCER_IDENTITY_MISMATCH", key, "sidecar source digest map differs from indexed producer identity")
                else:
                    note("PASS", "VERIFIED", "SIDECAR_BINDING", key, "original sidecar binds result, parent, static data and production source map; not release approval")
            except (OSError, ValueError, TypeError) as exc:
                invalid(key, str(exc))
        roles = {nodes[r].get("role") for r in refs if isinstance(r, str) and r in nodes}
        for role in ("e3_report", "e3_summary", "e4_review"):
            if role not in roles:
                note("WARN", "MISSING_EVIDENCE", "EVIDENCE_ROLE_MISSING", key, role)

    frozen = index.get("frozen_candidate_sha256")
    if not isinstance(frozen, list) or any(not is_sha256(x) for x in frozen) or len(set(frozen)) != len(frozen):
        invalid("frozen_candidate_sha256", "expected unique full SHA list")
    elif set(candidates) != set(frozen) or len(candidates) != len(frozen):
        invalid("scenario_artifacts", "candidate membership differs from the frozen cohort; no old/intermediate candidates")
    relations = index.get("lineage_edges")
    if not isinstance(relations, list):
        invalid("lineage_edges", "expected list")
        relations = []
    parent_counts = {}
    for edge in relations:
        if not isinstance(edge, dict):
            invalid("lineage_edges", "edge must be an object")
            continue
        subject = str(edge.get("child_id"))
        child_id, parent_id = edge.get("child_id"), edge.get("parent_id")
        if not isinstance(child_id, str) or not isinstance(parent_id, str):
            invalid(subject, "lineage identities must be strings")
            continue
        child, parent = nodes.get(child_id), nodes.get(parent_id)
        if child is None or parent is None:
            invalid(subject, "lineage edge references a missing indexed identity")
            continue
        relation, level = edge.get("relationship"), edge.get("evidence_level")
        if level not in EVIDENCE_LEVELS:
            invalid(subject, "unknown evidence reliability level")
        if relation == "raw_input_hypothesis":
            if child.get("artifact_type") != "legacy" or parent.get("artifact_type") not in ("raw_satellites", "raw_cities"):
                invalid(subject, "raw hypotheses require Legacy -> Raw")
            if level not in ("FILENAME_ONLY", "NOT_VERIFIED", "DECLARED_ONLY"):
                invalid(subject, "unrecovered historical Raw source cannot be certified by static fields or names")
            note("WARN", "MISSING_EVIDENCE", "RAW_ORIGIN_NOT_VERIFIED", subject, "candidate Raw association only; historical seed/generator/target provenance not recovered")
        elif relation == "recomputed_from":
            if level != "DECLARED_CORROBORATED":
                invalid(subject, "parent relation requires an original sidecar and corroborating content checks")
            parent_counts[subject] = parent_counts.get(subject, 0) + 1
            if child.get("artifact_type") != "candidate" or parent.get("artifact_type") != "legacy":
                invalid(subject, "recomputed_from requires Candidate -> Legacy")
            elif child.get("parent_scenario_sha256") != parent.get("sha256") or child.get("static_data_sha256") != parent.get("static_data_sha256"):
                note("FAIL", "CONTRADICTORY_EVIDENCE", "PARENT_IDENTITY_MISMATCH", subject, "declared parent SHA/static identity differs from the referenced Legacy")
            elif child["id"] in details and parent["id"] in details:
                note("PASS", "VERIFIED", "PARENT_STATIC_LINK", subject, "actual Candidate/Legacy static identity agrees with declared parent SHA; not proof of full Raw ancestry")
            else:
                note("WARN", "MISSING_EVIDENCE", "PARENT_LINK_NOT_VERIFIED", subject, "actual scenario bytes are unavailable")
        else:
            invalid(subject, "unsupported lineage relationship")
    for row in scenarios:
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("artifact_type") == "candidate" and parent_counts.get(row["id"]) != 1:
            invalid(str(row.get("id")), "candidate must have exactly one declared Legacy parent")

    internal_ids = {}
    for row in scenarios:
        if isinstance(row, dict) and isinstance(row.get("internal_scenario_id"), str):
            internal_ids.setdefault(row["internal_scenario_id"], []).append(row.get("sha256"))
    for name, hashes in internal_ids.items():
        if len(set(h for h in hashes if isinstance(h, str))) > 1:
            note("WARN", "MISSING_EVIDENCE", "INTERNAL_ID_REUSE", name, "internal name spans multiple content identities and is not a unique lineage/registry key")

    # Only subject identity is read from E3 JSON; approval/review schemas stay opaque.
    for key, row in nodes.items():
        bindings = row.get("subject_bindings", [row["subject_binding"]] if "subject_binding" in row else [])
        if not bindings or key not in available:
            continue
        if not isinstance(bindings, list):
            invalid(key, "subject_bindings must be a list")
            continue
        for binding in bindings:
            try:
                if not isinstance(binding, dict) or not is_sha256(binding.get("scenario_sha256")) or not isinstance(binding.get("field"), str):
                    raise ValueError("invalid subject binding")
                obj = load_index(available[key])
                selector = binding.get("selector")
                if selector is not None:
                    if not isinstance(selector, dict) or not selector or not isinstance(obj, list):
                        raise ValueError("selector requires a nonempty object and a JSON list")
                    selected = [x for x in obj if isinstance(x, dict) and all(x.get(k) == v for k, v in selector.items())]
                    if len(selected) != 1:
                        raise ValueError("subject selector must identify exactly one evidence record")
                    obj = selected[0]
                if not isinstance(obj, dict) or obj.get(binding["field"]) != binding["scenario_sha256"]:
                    note("FAIL", "CONTRADICTORY_EVIDENCE", "E3_SUBJECT_MISMATCH", key, "evidence binds a different candidate SHA")
                elif file_sha256(available[key]) != row["sha256"]:
                    invalid(key, "evidence changed while parsing")
                else:
                    note("PASS", "VERIFIED", "E3_SUBJECT_BINDING", key, "subject SHA matches; report status is not release approval or certification")
            except (OSError, ValueError, TypeError) as exc:
                invalid(key, str(exc))
    return finish()
