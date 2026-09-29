"""Typed downstream authority extensions for Paper 1 G06.4.

This module authenticates three frozen, prefit interfaces only: retrospective
realized weather, response-boundary filter metadata, and benchmark identities.
It contains no estimator calls, prediction generation, scoring, or model
execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import subprocess
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from src import paper1_g06_3_runtime as _g063
from src import paper1_g06_3a_runtime as _previous


for _export_name in dir(_previous):
    if not _export_name.startswith("_"):
        globals()[_export_name] = getattr(_previous, _export_name)


G06_4_GATE_VERSION = "PAPER1_G06.4"
G06_4_AUTHORITY_SCHEMA_VERSION = "PAPER1_G06.4_ACCEPTED_AUTHORITY_V1"
G06_4_AUTHORITY_PATH = "documentation/PAPER1_G06_4_ACCEPTED_AUTHORITY.json"
G06_4_AUTHORITY_SHA256 = (
    "c1ba141798210b1bc6bdcce38133b7761001a7abdc2edba02c34ba2869e4093a"
)
G06_4_PRODUCTION_FACADE = "src.paper1_g06_2_runtime"
G06_4_IMPLEMENTATION_MODULE = "src.paper1_g06_4_runtime"
G06_4_ACCEPTED_IMPLEMENTATION = "src.paper1_g06_2g_runtime"
G06_4_PRODUCTION_FACADE_SHA256 = (
    "216fbb048d56293a115df1cf5881d1128aa613742a58e2ed65e3287236aac143"
)

REALIZED_WEATHER_FIELDS = (
    "realized_hrrr_u10_mean_earth_ms",
    "realized_hrrr_v10_mean_earth_ms",
    "realized_hrrr_gust_max_ms",
    "realized_hrrr_temperature_2m_mean_c",
    "realized_hrrr_relative_humidity_2m_min_pct",
)
REALIZED_WEATHER_UNITS = ("m s-1", "m s-1", "m s-1", "degrees C", "percent")
BOUNDARY_FILTER_FIELDS = (
    "within_either_boundary_500m",
    "within_either_boundary_1000m",
)
GEOMETRY_BENCHMARK_FIELDS = (
    "distance_active_front_km",
    "distance_cumulative_perimeter_km",
    "hybrid_membership",
    "log1p_t0_area_km2",
)
BENCHMARK_TYPES = ("TRAINING_PREVALENCE", "GEOMETRY_LOGISTIC")
BENCHMARK_PREDICTION_SCHEMA_VERSION = "PAPER1_G06.4_BENCHMARK_PREDICTION_V1"
BENCHMARK_RECEIPT_SCHEMA_VERSION = "PAPER1_G06.4_BENCHMARK_RECEIPT_V1"

_CONTRACT_PAIR_CACHE: dict[
    tuple[str, str], tuple[tuple[str, str], ...]
] = {}


@dataclass(frozen=True)
class RealizedWeatherAuthority:
    schema_version: str
    gate_version: str
    relative_path: str
    expected_sha256: str
    manifest_path: str
    manifest_sha256: str
    row_count: int
    risk_set_id: str
    resolution_m: int
    key_fields: tuple[str, ...]
    interval_field: str
    fields: tuple[str, ...]
    units: tuple[str, ...]
    canonical_key_sha256: str
    key_interval_value_sha256: str
    semantic_role: str
    temporal_rule: str
    spatial_rule: str
    missingness_rule: str
    status: str


@dataclass(frozen=True)
class AuthenticatedRealizedWeatherArtifact:
    schema_version: str
    gate_version: str
    project_root: str
    authority: RealizedWeatherAuthority
    observed_sha256: str
    observed_manifest_sha256: str
    observed_row_count: int
    observed_key_sha256: str
    observed_key_interval_value_sha256: str
    columns: tuple[str, ...]
    dtypes: tuple[str, ...]
    records: tuple[tuple[object, ...], ...]
    governed_contract_sha256: str
    authentication_result: str = "PASS"

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame.from_records(self.records, columns=self.columns)


@dataclass(frozen=True)
class BoundaryFilterAuthority:
    schema_version: str
    gate_version: str
    relative_path: str
    expected_sha256: str
    row_count: int
    risk_set_id: str
    resolution_m: int
    response_field: str
    key_fields: tuple[str, ...]
    interval_field: str
    flag_fields: tuple[str, ...]
    canonical_key_sha256: str
    key_interval_flag_sha256: str
    semantic_role: str
    missingness_rule: str


@dataclass(frozen=True)
class AuthenticatedBoundaryFilterArtifact:
    schema_version: str
    gate_version: str
    project_root: str
    authority: BoundaryFilterAuthority
    observed_sha256: str
    observed_row_count: int
    observed_key_sha256: str
    observed_key_interval_flag_sha256: str
    columns: tuple[str, ...]
    dtypes: tuple[str, ...]
    records: tuple[tuple[object, ...], ...]
    governed_threshold_m: int
    governed_flag_field: str
    governed_contract_sha256: str
    predictor_use: str = "PROHIBITED"
    authentication_result: str = "PASS"

    def to_filter_frame(self) -> pd.DataFrame:
        return pd.DataFrame.from_records(self.records, columns=self.columns)


@dataclass(frozen=True)
class BenchmarkContract:
    schema_version: str
    gate_version: str
    benchmark_id: str
    benchmark_type: str
    model_family: str
    model_role: str
    scope_identity: str
    risk_set_id: str
    resolution_m: int
    evaluation_identity: str
    training_intervals: tuple[int, ...]
    heldout_intervals: tuple[int, ...]
    predictor_path: str
    predictor_sha256: str
    predictor_key_sha256: str
    predictor_fields: tuple[str, ...]
    support_identity: str
    support_path: str
    support_sha256: str
    outcome_path: str
    outcome_sha256: str
    outcome_key_sha256: str
    outcome_key_interval_value_sha256: str
    response_field: str
    preprocessing_identity: str
    estimator_identity: str
    tuning_identity: str
    metric_authority_sha256: str
    prediction_schema_version: str
    receipt_schema_version: str
    execution_universe_relationship: str
    contract_sha256: str


@dataclass(frozen=True)
class BenchmarkPredictionReceipt:
    schema_version: str
    gate_version: str
    prediction_schema_version: str
    benchmark_contract_sha256: str
    benchmark_id: str
    benchmark_type: str
    model_family: str
    model_role: str
    evaluation_identity: str
    risk_set_id: str
    resolution_m: int
    artifact_path: str
    artifact_sha256: str
    artifact_bytes: int
    row_count: int
    canonical_prediction_key_sha256: str
    outcome_key_interval_value_sha256: str
    run_id: str
    generation_id: str
    selected_primary_hyperparameter_receipt_sha256: str
    metric_authority_sha256: str
    publication_state: str
    receipt_sha256: str


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False
    )
    if check and result.returncode != 0:
        raise ContractError(f"ERR_G06_4_GIT:{' '.join(arguments)}:{result.stderr.strip()}")
    return result


def _git_blob(root: Path, commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"], cwd=root,
        capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise ContractError(f"ERR_G06_4_ACCEPTED_BLOB_MISSING:{relative_path}")
    return result.stdout


def _verify_file(root: Path, relative_path: str, expected_sha256: str,
                 reason: str) -> Path:
    path = (root / relative_path).resolve()
    if not path.is_file() or _sha256_path(path) != expected_sha256:
        raise ContractError(reason)
    return path


def _load_authority(root: Path) -> Mapping[str, object]:
    path = root / G06_4_AUTHORITY_PATH
    if not path.is_file() or _sha256_path(path) != G06_4_AUTHORITY_SHA256:
        raise ContractError("ERR_G06_4_AUTHORITY_RECORD_IDENTITY")
    try:
        authority = json.loads(path.read_text(encoding="ascii"))
    except Exception as exc:
        raise ContractError("ERR_G06_4_AUTHORITY_RECORD_SCHEMA") from exc
    required = {
        "schema_version", "gate_version", "accepted_g06_3a_commit",
        "accepted_g06_3a_subject", "g06_4_build_base_head",
        "g06_4_acceptance_derivation", "realized_weather", "boundary_filters",
        "benchmarks", "g05_execution_universe", "required_ancestry_rule",
        "supersession_policy", "carried_limitations",
    }
    if (set(authority) != required or
            authority.get("schema_version") != G06_4_AUTHORITY_SCHEMA_VERSION or
            authority.get("gate_version") != G06_4_GATE_VERSION):
        raise ContractError("ERR_G06_4_AUTHORITY_RECORD_SCHEMA")
    return MappingProxyType(authority)


def g06_4_lifecycle_authority(project_root: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    authority = _load_authority(root)
    current_head = _git(root, "rev-parse", "HEAD").stdout.strip()
    derivation = authority["g06_4_acceptance_derivation"]
    if (not isinstance(derivation, dict) or
            derivation.get("method") != "UNIQUE_GIT_ADD_COMMIT_FOR_G06_4_AUTHORITY_RECORD"):
        raise ContractError("ERR_G06_4_ACCEPTANCE_DERIVATION")
    relative_path = str(derivation.get("path", ""))
    commits = tuple(line.strip() for line in _git(
        root, "log", "--diff-filter=A", "--format=%H", "--", relative_path
    ).stdout.splitlines() if line.strip())
    if not commits:
        status = _git(root, "status", "--short", "--", relative_path).stdout.strip()
        if (current_head != authority["g06_4_build_base_head"] or
                status != f"?? {relative_path}"):
            raise ContractError("ERR_G06_4_PREACCEPTANCE_STATE")
        state, acceptance_commit = "PRE_ACCEPTANCE_AUDIT", "UNCOMMITTED"
    else:
        if len(commits) != 1:
            raise ContractError("ERR_G06_4_ACCEPTANCE_DERIVATION")
        acceptance_commit = commits[0]
        build_relation = _git(
            root, "merge-base", "--is-ancestor",
            str(authority["g06_4_build_base_head"]), acceptance_commit, check=False,
        )
        if build_relation.returncode != 0:
            raise ContractError("ERR_G06_4_ACCEPTANCE_LINEAGE")
        current_relation = _git(
            root, "merge-base", "--is-ancestor", acceptance_commit, current_head,
            check=False,
        )
        if current_relation.returncode != 0:
            raise ContractError("ERR_G06_4_ACCEPTANCE_NOT_ANCESTOR")
        frozen_paths = derivation.get("frozen_paths")
        if not isinstance(frozen_paths, list) or len(frozen_paths) != 4:
            raise ContractError("ERR_G06_4_ACCEPTANCE_DERIVATION")
        for frozen_path in frozen_paths:
            committed = _sha256_bytes(_git_blob(root, acceptance_commit, str(frozen_path)))
            current = root / str(frozen_path)
            if not current.is_file() or _sha256_path(current) != committed:
                raise ContractError(f"ERR_G06_4_FROZEN_SOURCE_CHANGED:{frozen_path}")
        state = "ACCEPTED_DESCENDANT"
    return MappingProxyType({
        "gate_version": G06_4_GATE_VERSION,
        "build_base_head": authority["g06_4_build_base_head"],
        "accepted_g06_3a_commit": authority["accepted_g06_3a_commit"],
        "current_head": current_head,
        "acceptance_state": state,
        "acceptance_commit": acceptance_commit,
        "build_base_is_ancestor": state == "PRE_ACCEPTANCE_AUDIT" or acceptance_commit != "UNCOMMITTED",
        "ancestry_rule": authority["required_ancestry_rule"],
    })


def _validate_historical_g06_3a(root: Path, directory: Path,
                                extension_authority: Mapping[str, object]) -> Mapping[str, object]:
    old_authority = _previous._load_authority(root)
    accepted_g06_commit = _g063._derive_accepted_commit(root, old_authority)
    current_head = _git(root, "rev-parse", "HEAD").stdout.strip()
    if _git(root, "merge-base", "--is-ancestor", accepted_g06_commit,
            current_head, check=False).returncode != 0:
        raise ContractError("ERR_G06_4_ACCEPTED_G06_NOT_ANCESTOR")
    derivation = old_authority["compatibility_acceptance_derivation"]
    path = str(derivation["path"])
    commits = tuple(line.strip() for line in _git(
        root, "log", "--diff-filter=A", "--format=%H", "--", path
    ).stdout.splitlines() if line.strip())
    if len(commits) != 1:
        raise ContractError("ERR_G06_4_HISTORICAL_G06_3A_DERIVATION")
    compatibility_commit = commits[0]
    if compatibility_commit != extension_authority["accepted_g06_3a_commit"]:
        raise ContractError("ERR_G06_4_ACCEPTED_G06_3A_IDENTITY")
    if _git(root, "show", "-s", "--format=%s", compatibility_commit).stdout.strip() != (
            extension_authority["accepted_g06_3a_subject"]):
        raise ContractError("ERR_G06_4_ACCEPTED_G06_3A_SUBJECT")
    if _git(root, "merge-base", "--is-ancestor",
            str(old_authority["compatibility_build_base_head"]),
            compatibility_commit, check=False).returncode != 0:
        raise ContractError("ERR_G06_4_HISTORICAL_G06_3A_LINEAGE")
    if _git(root, "merge-base", "--is-ancestor", compatibility_commit,
            current_head, check=False).returncode != 0:
        raise ContractError("ERR_G06_4_ACCEPTED_G06_3A_NOT_ANCESTOR")

    facade_path = "src/paper1_g06_2_runtime.py"
    for relative_path in derivation["frozen_paths"]:
        blob_hash = _sha256_bytes(_git_blob(root, compatibility_commit, relative_path))
        if relative_path == facade_path:
            if blob_hash != _previous.G06_3A_PRODUCTION_FACADE_SHA256:
                raise ContractError("ERR_G06_4_HISTORICAL_FACADE_IDENTITY")
        else:
            _verify_file(root, relative_path, blob_hash,
                         f"ERR_G06_4_HISTORICAL_G06_3A_SOURCE:{relative_path}")

    for relative_path, expected in old_authority["accepted_source"].items():
        blob_hash = _sha256_bytes(_git_blob(root, accepted_g06_commit, relative_path))
        if blob_hash != expected:
            raise ContractError("ERR_G06_4_HISTORICAL_ACCEPTED_SOURCE")
        if relative_path != facade_path:
            _verify_file(root, relative_path, expected,
                         f"ERR_G06_4_ACCEPTED_SOURCE_CHANGED:{relative_path}")
    for relative_path, expected in old_authority["accepted_independent_audit"].items():
        _verify_file(root, relative_path, expected,
                     f"ERR_G06_4_ACCEPTED_AUDIT_CHANGED:{relative_path}")
    decision = _g063._validate_independent_decision(root, old_authority)
    manifest = _g063._validate_generation(root, old_authority, directory)
    return MappingProxyType({
        "status": "PASS",
        "accepted_g06_commit": accepted_g06_commit,
        "accepted_g06_3a_commit": compatibility_commit,
        "current_downstream_head": current_head,
        "generation_manifest": manifest,
        "independent_verdict": decision["independent_verdict"],
        "g07_consumability": decision["g07_consumability"],
    })


def _frame_hash(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    ordered = frame.loc[:, list(columns)].sort_values(
        list(KEY_FIELDS), kind="stable"
    ).reset_index(drop=True)
    return _sha256_bytes(ordered.to_csv(index=False, lineterminator="\n").encode("utf-8"))


def _contract_unit_id(contract: ExecutionContract) -> str:
    return "|".join((
        contract.analysis_id, contract.model_family, contract.model_role,
        contract.evaluation_identity, str(contract.resolution_m),
    ))


def _contract_pairs(root: Path, family: str) -> tuple[tuple[str, str], ...]:
    cache_key = (str(root.resolve()), family)
    cached = _CONTRACT_PAIR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    contracts = tuple(
        contract for contract in governed_execution_contracts(root)
        if contract.analysis_family == family
    )
    pairs = tuple(sorted((_contract_unit_id(contract), contract.contract_sha256)
                         for contract in contracts))
    _CONTRACT_PAIR_CACHE[cache_key] = pairs
    return pairs


def _validate_contract_pairs(root: Path, family: str,
                             section: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    pairs = _contract_pairs(root, family)
    if (len(pairs) != int(section["contract_count"]) or
            _sha256_bytes(canonical_json(pairs)) != section["contract_set_sha256"]):
        raise ContractError(f"ERR_G06_4_{family}_CONTRACT_SET")
    return pairs


def _realized_authority(authority: Mapping[str, object],
                        resolution_m: int) -> RealizedWeatherAuthority:
    section = authority["realized_weather"]
    item = section["authorities"].get(str(int(resolution_m)))
    if item is None:
        raise ContractError("ERR_G06_4_REALIZED_WEATHER_RESOLUTION")
    return RealizedWeatherAuthority(
        G06_4_AUTHORITY_SCHEMA_VERSION, G06_4_GATE_VERSION,
        item["relative_path"], item["expected_sha256"],
        section["manifest_path"], section["manifest_sha256"],
        int(item["row_count"]), section["risk_set_id"], int(resolution_m),
        tuple(section["key_fields"]), section["interval_field"],
        tuple(section["fields"]), tuple(section["units"]),
        item["canonical_key_sha256"], item["key_interval_value_sha256"],
        section["semantic_role"], section["temporal_rule"], section["spatial_rule"],
        section["missingness_rule"], section["status"],
    )


def authenticate_realized_weather_artifact(
        project_root: Path, resolution_m: int, supplied_path: Path | None = None,
        requested_fields: Sequence[str] | None = None) -> AuthenticatedRealizedWeatherArtifact:
    root = Path(project_root).resolve()
    authority_record = _load_authority(root)
    g06_4_lifecycle_authority(root)
    authority = _realized_authority(authority_record, int(resolution_m))
    governed = (root / authority.relative_path).resolve()
    if supplied_path is not None and Path(supplied_path).resolve() != governed:
        raise ContractError("ERR_G06_4_REALIZED_WEATHER_CALLER_SUBSTITUTION")
    fields = authority.fields if requested_fields is None else tuple(requested_fields)
    if fields != authority.fields:
        raise ContractError("ERR_G06_4_REALIZED_WEATHER_FIELD_SET")
    _verify_file(root, authority.manifest_path, authority.manifest_sha256,
                 "ERR_G06_4_REALIZED_WEATHER_MANIFEST")
    _verify_file(root, authority.relative_path, authority.expected_sha256,
                 "ERR_G06_4_REALIZED_WEATHER_SOURCE_HASH")
    columns = (*authority.key_fields, authority.interval_field, *authority.fields)
    frame = pd.read_parquet(governed, columns=list(columns))
    if (tuple(frame.columns) != columns or len(frame) != authority.row_count or
            frame.loc[:, authority.key_fields].isna().any().any() or
            frame.loc[:, authority.key_fields].duplicated().any() or
            not frame["response_grid_m"].eq(authority.resolution_m).all()):
        raise ContractError("ERR_G06_4_REALIZED_WEATHER_ROW_KEYS")
    values = frame.loc[:, authority.fields].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    if not np.isfinite(values).all():
        raise ContractError("ERR_G06_4_REALIZED_WEATHER_MISSING_OR_NONFINITE")
    key_hash = key_sha256(frame)
    content_hash = _frame_hash(frame, columns)
    if (key_hash != authority.canonical_key_sha256 or
            content_hash != authority.key_interval_value_sha256):
        raise ContractError("ERR_G06_4_REALIZED_WEATHER_CONTENT")
    ordered = frame.sort_values(list(authority.key_fields), kind="stable").reset_index(drop=True)
    return AuthenticatedRealizedWeatherArtifact(
        "PAPER1_G06.4_REALIZED_WEATHER_HANDLE_V1", G06_4_GATE_VERSION, str(root),
        authority, _sha256_path(governed), _sha256_path(root / authority.manifest_path),
        len(ordered), key_hash, content_hash, tuple(ordered.columns),
        tuple(str(value) for value in ordered.dtypes),
        tuple(tuple(row) for row in ordered.itertuples(index=False, name=None)),
        "UNBOUND",
    )


def authenticate_realized_weather_for_contract(
        project_root: Path, contract: ExecutionContract) -> AuthenticatedRealizedWeatherArtifact:
    root = Path(project_root).resolve()
    validate_execution_contract(root, contract)
    authority = _load_authority(root)["realized_weather"]
    pairs = _validate_contract_pairs(root, "REALIZED_WEATHER", authority)
    if ((contract.analysis_family != "REALIZED_WEATHER") or
            (_contract_unit_id(contract), contract.contract_sha256) not in pairs or
            contract.risk_set_id != "PRIMARY_HYBRID"):
        raise ContractError("ERR_G06_4_REALIZED_WEATHER_CONTRACT")
    handle = authenticate_realized_weather_artifact(root, contract.resolution_m)
    return replace(handle, governed_contract_sha256=contract.contract_sha256)


def validate_authenticated_realized_weather_artifact(
        handle: AuthenticatedRealizedWeatherArtifact,
        contract: ExecutionContract | None = None) -> None:
    if (not isinstance(handle, AuthenticatedRealizedWeatherArtifact) or
            handle.schema_version != "PAPER1_G06.4_REALIZED_WEATHER_HANDLE_V1" or
            handle.gate_version != G06_4_GATE_VERSION or
            handle.authentication_result != "PASS"):
        raise ContractError("ERR_G06_4_REALIZED_WEATHER_HANDLE_TYPE")
    expected = (authenticate_realized_weather_artifact(
        Path(handle.project_root), handle.authority.resolution_m
    ) if contract is None else authenticate_realized_weather_for_contract(
        Path(handle.project_root), contract
    ))
    if handle != expected:
        raise ContractError("ERR_G06_4_REALIZED_WEATHER_HANDLE_BINDING")


def _boundary_authority(authority: Mapping[str, object]) -> BoundaryFilterAuthority:
    section = authority["boundary_filters"]
    return BoundaryFilterAuthority(
        G06_4_AUTHORITY_SCHEMA_VERSION, G06_4_GATE_VERSION,
        section["relative_path"], section["expected_sha256"], int(section["row_count"]),
        section["risk_set_id"], int(section["resolution_m"]), section["response_field"],
        tuple(section["key_fields"]), section["interval_field"],
        (section["flags"]["500"], section["flags"]["1000"]),
        section["canonical_key_sha256"], section["key_interval_flag_sha256"],
        section["semantic_role"], section["missingness_rule"],
    )


def authenticate_boundary_filter_artifact(
        project_root: Path, supplied_path: Path | None = None) -> AuthenticatedBoundaryFilterArtifact:
    root = Path(project_root).resolve()
    authority_record = _load_authority(root)
    g06_4_lifecycle_authority(root)
    authority = _boundary_authority(authority_record)
    governed = (root / authority.relative_path).resolve()
    if supplied_path is not None and Path(supplied_path).resolve() != governed:
        raise ContractError("ERR_G06_4_BOUNDARY_CALLER_SUBSTITUTION")
    _verify_file(root, authority.relative_path, authority.expected_sha256,
                 "ERR_G06_4_BOUNDARY_SOURCE_HASH")
    columns = (*authority.key_fields, authority.interval_field, *authority.flag_fields)
    frame = pd.read_parquet(governed, columns=list(columns))
    if (tuple(frame.columns) != columns or len(frame) != authority.row_count or
            frame.loc[:, authority.key_fields].isna().any().any() or
            frame.loc[:, authority.key_fields].duplicated().any() or
            not frame["response_grid_m"].eq(authority.resolution_m).all()):
        raise ContractError("ERR_G06_4_BOUNDARY_ROW_KEYS")
    for field in authority.flag_fields:
        if frame[field].isna().any() or not pd.api.types.is_bool_dtype(frame[field].dtype):
            raise ContractError("ERR_G06_4_BOUNDARY_FLAG_DOMAIN")
    key_hash = key_sha256(frame)
    content_hash = _frame_hash(frame, columns)
    if (key_hash != authority.canonical_key_sha256 or
            content_hash != authority.key_interval_flag_sha256):
        raise ContractError("ERR_G06_4_BOUNDARY_CONTENT")
    ordered = frame.sort_values(list(authority.key_fields), kind="stable").reset_index(drop=True)
    return AuthenticatedBoundaryFilterArtifact(
        "PAPER1_G06.4_BOUNDARY_FILTER_HANDLE_V1", G06_4_GATE_VERSION, str(root),
        authority, _sha256_path(governed), len(ordered), key_hash, content_hash,
        tuple(ordered.columns), tuple(str(value) for value in ordered.dtypes),
        tuple(tuple(row) for row in ordered.itertuples(index=False, name=None)),
        0, "UNBOUND", "UNBOUND",
    )


def authenticate_boundary_filter_for_contract(
        project_root: Path, contract: ExecutionContract,
        threshold_m: int) -> AuthenticatedBoundaryFilterArtifact:
    root = Path(project_root).resolve()
    validate_execution_contract(root, contract)
    section = _load_authority(root)["boundary_filters"]
    pairs = _validate_contract_pairs(
        root, "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY", section
    )
    expected_analysis = f"G05B_BOUNDARY_{int(threshold_m)}"
    if (contract.analysis_id != expected_analysis or
            (_contract_unit_id(contract), contract.contract_sha256) not in pairs or
            contract.risk_set_id != section["risk_set_id"] or
            contract.resolution_m != int(section["resolution_m"])):
        raise ContractError("ERR_G06_4_BOUNDARY_CONTRACT")
    flag = section["flags"].get(str(int(threshold_m)))
    if flag is None:
        raise ContractError("ERR_G06_4_BOUNDARY_THRESHOLD")
    handle = authenticate_boundary_filter_artifact(root)
    return replace(
        handle, governed_threshold_m=int(threshold_m), governed_flag_field=flag,
        governed_contract_sha256=contract.contract_sha256,
    )


def validate_authenticated_boundary_filter_artifact(
        handle: AuthenticatedBoundaryFilterArtifact,
        contract: ExecutionContract | None = None) -> None:
    if (not isinstance(handle, AuthenticatedBoundaryFilterArtifact) or
            handle.schema_version != "PAPER1_G06.4_BOUNDARY_FILTER_HANDLE_V1" or
            handle.gate_version != G06_4_GATE_VERSION or
            handle.predictor_use != "PROHIBITED" or
            handle.authentication_result != "PASS"):
        raise ContractError("ERR_G06_4_BOUNDARY_HANDLE_TYPE")
    expected = (authenticate_boundary_filter_artifact(Path(handle.project_root))
                if contract is None else authenticate_boundary_filter_for_contract(
                    Path(handle.project_root), contract, handle.governed_threshold_m
                ))
    if handle != expected:
        raise ContractError("ERR_G06_4_BOUNDARY_HANDLE_BINDING")


def _benchmark_payload(root: Path, benchmark_type: str,
                       evaluation_identity: str) -> dict[str, object]:
    if benchmark_type not in BENCHMARK_TYPES or evaluation_identity not in OUTER_EVALUATIONS:
        raise ContractError("ERR_G06_4_BENCHMARK_SCOPE")
    primary = governed_execution_contract(
        root, "G05A_01_PRIMARY_EVT_1KM", "L2_LOGISTIC", "baseline",
        evaluation_identity,
    )
    if benchmark_type == "TRAINING_PREVALENCE":
        fields: tuple[str, ...] = ()
        preprocessing = "NONE; JEFFREYS_SMOOTHED_TRAINING_HISTORY_ONLY"
        estimator = "NONE_CONSTANT_PROBABILITY"
        tuning = "NONE; HELDOUT_LABEL_USE_PROHIBITED"
    else:
        fields = GEOMETRY_BENCHMARK_FIELDS
        preprocessing = (
            "TRAINING_HISTORY_POPULATION_SD_DDOF0; BOTH_REFERENCE; "
            "FIXED_SCHEMA_INDICATORS; TRAINING_CONSTANT_FIXED_ZERO_COORDINATE"
        )
        estimator = (
            "SKLEARN_LOGISTIC_REGRESSION_L2_LBFGS_INTERCEPT_"
            "NO_CLASS_WEIGHT_MAXITER5000_TOL1E-8"
        )
        tuning = "INHERIT_MATCHING_PRIMARY_OUTER_SELECTED_C_RECEIPT; NO_BENCHMARK_RETUNING"
    return {
        "schema_version": "PAPER1_G06.4_BENCHMARK_CONTRACT_V1",
        "gate_version": G06_4_GATE_VERSION,
        "benchmark_id": f"PAPER1_{benchmark_type}_{evaluation_identity}",
        "benchmark_type": benchmark_type,
        "model_family": benchmark_type,
        "model_role": "benchmark",
        "scope_identity": "PRIMARY_CONFIRMATORY_1KM_PRIMARY_HYBRID_FORWARD_CHAIN",
        "risk_set_id": primary.risk_set_id,
        "resolution_m": primary.resolution_m,
        "evaluation_identity": evaluation_identity,
        "training_intervals": primary.training_intervals,
        "heldout_intervals": primary.heldout_intervals,
        "predictor_path": primary.predictor_path,
        "predictor_sha256": primary.predictor_sha256,
        "predictor_key_sha256": primary.predictor_key_sha256,
        "predictor_fields": fields,
        "support_identity": primary.support_identity,
        "support_path": primary.support_path,
        "support_sha256": primary.support_sha256,
        "outcome_path": primary.response_path,
        "outcome_sha256": primary.response_sha256,
        "outcome_key_sha256": primary.response_key_sha256,
        "outcome_key_interval_value_sha256": primary.response_key_interval_value_sha256,
        "response_field": "y",
        "preprocessing_identity": preprocessing,
        "estimator_identity": estimator,
        "tuning_identity": tuning,
        "metric_authority_sha256": primary.metric_authority_sha256,
        "prediction_schema_version": BENCHMARK_PREDICTION_SCHEMA_VERSION,
        "receipt_schema_version": BENCHMARK_RECEIPT_SCHEMA_VERSION,
        "execution_universe_relationship": "ORTHOGONAL_BENCHMARK_ROLE_NOT_A_G05_UNIT",
    }


def _build_benchmark_contracts(project_root: Path) -> tuple[BenchmarkContract, ...]:
    root = Path(project_root).resolve()
    contracts = []
    for benchmark_type in BENCHMARK_TYPES:
        for evaluation_identity in OUTER_EVALUATIONS:
            payload = _benchmark_payload(root, benchmark_type, evaluation_identity)
            contracts.append(BenchmarkContract(
                **payload, contract_sha256=_sha256_bytes(canonical_json(payload))
            ))
    return tuple(contracts)


def governed_benchmark_contracts(project_root: Path) -> tuple[BenchmarkContract, ...]:
    root = Path(project_root).resolve()
    authority = _load_authority(root)
    g06_4_lifecycle_authority(root)
    contracts = _build_benchmark_contracts(root)
    pairs = tuple((item.benchmark_id, item.contract_sha256) for item in contracts)
    section = authority["benchmarks"]
    if (len(contracts) != int(section["contract_count"]) or
            _sha256_bytes(canonical_json(pairs)) != section["contract_set_sha256"]):
        raise ContractError("ERR_G06_4_BENCHMARK_CONTRACT_SET")
    return contracts


def governed_benchmark_contract(project_root: Path, benchmark_type: str,
                                  evaluation_identity: str) -> BenchmarkContract:
    matches = tuple(
        item for item in governed_benchmark_contracts(project_root)
        if item.benchmark_type == benchmark_type and
        item.evaluation_identity == evaluation_identity
    )
    if len(matches) != 1:
        raise ContractError("ERR_G06_4_BENCHMARK_CONTRACT")
    return matches[0]


def validate_benchmark_contract(project_root: Path, contract: BenchmarkContract) -> None:
    if not isinstance(contract, BenchmarkContract):
        raise ContractError("ERR_G06_4_BENCHMARK_CONTRACT_TYPE")
    expected = governed_benchmark_contract(
        project_root, contract.benchmark_type, contract.evaluation_identity
    )
    if contract != expected:
        raise ContractError("ERR_G06_4_BENCHMARK_CONTRACT_BINDING")


def benchmark_prediction_identity(project_root: Path,
                                  contract: BenchmarkContract) -> Mapping[str, object]:
    validate_benchmark_contract(project_root, contract)
    return MappingProxyType({
        "benchmark_contract_sha256": contract.contract_sha256,
        "benchmark_id": contract.benchmark_id,
        "benchmark_type": contract.benchmark_type,
        "model_family": contract.model_family,
        "model_role": contract.model_role,
        "evaluation_identity": contract.evaluation_identity,
        "risk_set_id": contract.risk_set_id,
        "resolution_m": contract.resolution_m,
        "prediction_schema_version": contract.prediction_schema_version,
        "receipt_schema_version": contract.receipt_schema_version,
        "outcome_key_interval_value_sha256": contract.outcome_key_interval_value_sha256,
        "metric_authority_sha256": contract.metric_authority_sha256,
    })


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def build_benchmark_prediction_receipt(
        project_root: Path, contract: BenchmarkContract, artifact_path: str,
        artifact_sha256: str, artifact_bytes: int, row_count: int,
        canonical_prediction_key_sha256: str, run_id: str, generation_id: str,
        selected_primary_hyperparameter_receipt_sha256: str) -> BenchmarkPredictionReceipt:
    validate_benchmark_contract(project_root, contract)
    if (not artifact_path or not run_id or not generation_id or artifact_bytes <= 0 or
            row_count <= 0 or not _valid_sha256(artifact_sha256) or
            not _valid_sha256(canonical_prediction_key_sha256)):
        raise ContractError("ERR_G06_4_BENCHMARK_RECEIPT_INPUT")
    if contract.benchmark_type == "GEOMETRY_LOGISTIC":
        if not _valid_sha256(selected_primary_hyperparameter_receipt_sha256):
            raise ContractError("ERR_G06_4_BENCHMARK_PRIMARY_C_RECEIPT")
    elif selected_primary_hyperparameter_receipt_sha256 != "NOT_APPLICABLE":
        raise ContractError("ERR_G06_4_BENCHMARK_PREVALENCE_TUNING")
    payload = {
        "schema_version": BENCHMARK_RECEIPT_SCHEMA_VERSION,
        "gate_version": G06_4_GATE_VERSION,
        "prediction_schema_version": contract.prediction_schema_version,
        "benchmark_contract_sha256": contract.contract_sha256,
        "benchmark_id": contract.benchmark_id,
        "benchmark_type": contract.benchmark_type,
        "model_family": contract.model_family,
        "model_role": contract.model_role,
        "evaluation_identity": contract.evaluation_identity,
        "risk_set_id": contract.risk_set_id,
        "resolution_m": contract.resolution_m,
        "artifact_path": artifact_path,
        "artifact_sha256": artifact_sha256,
        "artifact_bytes": int(artifact_bytes),
        "row_count": int(row_count),
        "canonical_prediction_key_sha256": canonical_prediction_key_sha256,
        "outcome_key_interval_value_sha256": contract.outcome_key_interval_value_sha256,
        "run_id": run_id,
        "generation_id": generation_id,
        "selected_primary_hyperparameter_receipt_sha256": selected_primary_hyperparameter_receipt_sha256,
        "metric_authority_sha256": contract.metric_authority_sha256,
        "publication_state": "COMPLETE_MARKER_LAST_REQUIRED",
    }
    return BenchmarkPredictionReceipt(
        **payload, receipt_sha256=_sha256_bytes(canonical_json(payload))
    )


def validate_benchmark_prediction_receipt(
        project_root: Path, contract: BenchmarkContract,
        receipt: BenchmarkPredictionReceipt) -> None:
    if not isinstance(receipt, BenchmarkPredictionReceipt):
        raise ContractError("ERR_G06_4_BENCHMARK_RECEIPT_TYPE")
    expected = build_benchmark_prediction_receipt(
        project_root, contract, receipt.artifact_path, receipt.artifact_sha256,
        receipt.artifact_bytes, receipt.row_count,
        receipt.canonical_prediction_key_sha256, receipt.run_id,
        receipt.generation_id,
        receipt.selected_primary_hyperparameter_receipt_sha256,
    )
    if receipt != expected:
        raise ContractError("ERR_G06_4_BENCHMARK_RECEIPT_BINDING")


def _validate_authority_sources(root: Path, authority: Mapping[str, object]) -> None:
    for section_name in ("realized_weather", "boundary_filters", "benchmarks"):
        for relative_path, expected in authority[section_name]["authority_sources"].items():
            _verify_file(root, relative_path, expected,
                         f"ERR_G06_4_AUTHORITY_SOURCE:{relative_path}")


def _validate_execution_universe(root: Path, authority: Mapping[str, object]) -> Mapping[str, object]:
    contracts = governed_execution_contracts(root)
    units = tuple(_contract_unit_id(contract) for contract in contracts)
    counts = {
        "g05a_units": sum(unit.startswith("G05A_") for unit in units),
        "g05b_units": sum(unit.startswith("G05B_") for unit in units),
        "total_units": len(units),
        "executable_units": sum(contract.execution_enabled for contract in contracts),
        "disabled_units": sum(not contract.execution_enabled for contract in contracts),
    }
    expected = authority["g05_execution_universe"]
    if any(counts[key] != int(expected[key]) for key in counts):
        raise ContractError("ERR_G06_4_EXECUTION_UNIVERSE")
    return MappingProxyType(counts)


def _validate_production_facade(root: Path) -> None:
    from src import paper1_g06_2_runtime as facade

    production = facade.PRODUCTION_API_MANIFEST
    if (_sha256_path(root / "src/paper1_g06_2_runtime.py") !=
            G06_4_PRODUCTION_FACADE_SHA256 or
            production.get("production_import") != G06_4_PRODUCTION_FACADE or
            production.get("implementation_module") != G06_4_IMPLEMENTATION_MODULE or
            production.get("accepted_implementation_module") != G06_4_ACCEPTED_IMPLEMENTATION or
            facade.validate_validation_generation is not validate_validation_generation):
        raise ContractError("ERR_G06_4_PRODUCTION_FACADE")


def current_generation_authority(project_root: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    authority = _load_authority(root)
    lifecycle = g06_4_lifecycle_authority(root)
    historical = _validate_historical_g06_3a(root, root / "documentation", authority)
    _validate_authority_sources(root, authority)
    universe = _validate_execution_universe(root, authority)
    weather_pairs = _validate_contract_pairs(root, "REALIZED_WEATHER", authority["realized_weather"])
    boundary_pairs = _validate_contract_pairs(
        root, "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY", authority["boundary_filters"]
    )
    benchmarks = governed_benchmark_contracts(root)
    return MappingProxyType({
        "gate_version": G06_4_GATE_VERSION,
        "git_head": lifecycle["current_head"],
        "acceptance_state": lifecycle["acceptance_state"],
        "acceptance_commit": lifecycle["acceptance_commit"],
        "build_base_head": lifecycle["build_base_head"],
        "accepted_g06_3a_commit": lifecycle["accepted_g06_3a_commit"],
        "accepted_generation_id": historical["generation_manifest"]["generation_id"],
        "realized_weather_contract_count": len(weather_pairs),
        "boundary_filter_contract_count": len(boundary_pairs),
        "benchmark_contract_count": len(benchmarks),
        "g05_execution_universe": dict(universe),
        "carried_limitations": authority["carried_limitations"],
        "scientific_fitting_authorized": "NO",
    })


def validate_validation_generation(project_root: Path,
                                   directory: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    authority = _load_authority(root)
    lifecycle = g06_4_lifecycle_authority(root)
    historical = _validate_historical_g06_3a(root, Path(directory).resolve(), authority)
    _validate_authority_sources(root, authority)
    universe = _validate_execution_universe(root, authority)
    weather_pairs = _validate_contract_pairs(root, "REALIZED_WEATHER", authority["realized_weather"])
    boundary_pairs = _validate_contract_pairs(
        root, "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY", authority["boundary_filters"]
    )
    for resolution in (1000, 2000):
        validate_authenticated_realized_weather_artifact(
            authenticate_realized_weather_artifact(root, resolution)
        )
    validate_authenticated_boundary_filter_artifact(
        authenticate_boundary_filter_artifact(root)
    )
    benchmarks = governed_benchmark_contracts(root)
    for contract in benchmarks:
        validate_benchmark_contract(root, contract)
    _validate_production_facade(root)
    result = dict(historical["generation_manifest"])
    result["g06_4_validation"] = {
        "status": "PASS",
        "gate_version": G06_4_GATE_VERSION,
        "acceptance_state": lifecycle["acceptance_state"],
        "acceptance_commit": lifecycle["acceptance_commit"],
        "build_base_head": lifecycle["build_base_head"],
        "accepted_g06_3a_commit": lifecycle["accepted_g06_3a_commit"],
        "historical_g06_3a": historical["status"],
        "realized_weather_contract_count": len(weather_pairs),
        "boundary_filter_contract_count": len(boundary_pairs),
        "benchmark_contract_count": len(benchmarks),
        "g05a_units": universe["g05a_units"],
        "g05b_units": universe["g05b_units"],
        "total_units": universe["total_units"],
        "scientific_fitting_authorized": "NO",
        "models_fit": "NO",
        "real_predictions_generated": "NO",
        "real_performance_inspected": "NO",
    }
    return MappingProxyType(result)


PRODUCTION_API_MANIFEST = MappingProxyType({
    "api_identity": API_IDENTITY,
    "production_import": G06_4_PRODUCTION_FACADE,
    "implementation_module": G06_4_IMPLEMENTATION_MODULE,
    "accepted_implementation_module": G06_4_ACCEPTED_IMPLEMENTATION,
    "compatibility_gate": G06_4_GATE_VERSION,
    "accepted_gate": "PAPER1_G06.2g",
    "historical_compatibility_gate": "PAPER1_G06.3a",
    "legacy_policy": "NONEXPORTED_AUTHORITY_APIS_FAIL_CLOSED",
})
