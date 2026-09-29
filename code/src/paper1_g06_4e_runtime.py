"""Paper 1 G06.4e governed contracts and artifact-integrity interfaces.

This module freezes interfaces for future G07 execution and later independent
audit. It validates bytes, schemas, keys, histories, and deterministic
reconstructions. It does not fit estimators, generate scientific predictions,
or attest that a historical physical process occurred.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from src import paper1_g06_4_runtime as _previous
from src import paper1_g06_evaluation as _evaluation


for _name in dir(_previous):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_previous, _name)


G06_4E_GATE_VERSION = "PAPER1_G06.4e"
G06_4E_AUTHORITY_SCHEMA_VERSION = "PAPER1_G06.4E_ACCEPTED_AUTHORITY_V1"
G06_4E_AUTHORITY_PATH = "documentation/PAPER1_G06_4E_ACCEPTED_AUTHORITY.json"
G06_4E_AUTHORITY_SHA256 = "f484c685478434c9d8ce95a16e09677e4adbbd579207e6ab3b80313e697d94b0"
G06_4E_IMPLEMENTATION_MODULE = "src.paper1_g06_4e_runtime"
G06_4E_PRODUCTION_FACADE = "src.paper1_g06_2_runtime"

MANIFEST_SCHEMA_NAME = "PAPER1_G07_EXECUTION_MANIFEST"
MANIFEST_SCHEMA_VERSION = "PAPER1_G07_EXECUTION_MANIFEST_V1"
MANIFEST_ROLE = "AUDIT_AND_REPRODUCIBILITY_METADATA"
PREDICTION_ARTIFACT_SCHEMA = "PAPER1_G06.4D_PREDICTION_ARTIFACT_V1"
OUTCOME_INPUT_SCHEMA = "PAPER1_G06.4D_OUTCOME_INPUT_V1"
SYNTHETIC_OUTCOME_AUTHORITY_SCHEMA = (
    "PAPER1_G06.4E_SYNTHETIC_OUTCOME_AUTHORITY_V1"
)
EVIDENCE_CLASSIFICATIONS = ("SCIENTIFIC", "SYNTHETIC_TEST")
TERMINAL_STATUSES = (
    "COMPLETE", "PENDING_NOT_EXECUTED", "ENVIRONMENT_BLOCKED",
    "FAILED_RUNTIME", "GOVERNED_NONESTIMABLE", "MACHINE_DISABLED_NONEXECUTING",
)
CURRENT_G07_RUNNER_STATUS = "NOT_YET_ACCEPTED"
CURRENT_SCIENTIFIC_EXECUTION_STATUS = "NOT_YET_AUTHORIZED"
CURRENT_PRODUCTION_PREDICTION_EVIDENCE = "ABSENT"
CURRENT_POST_RUN_FIDELITY = "NOT_YET_EVALUATED"

BASELINE_ANALYSIS_ID = "G05A_01_PRIMARY_EVT_1KM"
BASELINE_MODEL_FAMILY = "L2_LOGISTIC"
BASELINE_MODEL_ROLE = "baseline"
GEOMETRY_C_SOURCE_ROLE = "BASELINE24_L2_LOGISTIC_PRIMARY_MODEL"
ALLOWED_BASELINE_C = (0.1, 1.0)
SELECTION_METRIC = "INTERVAL_LEVEL_LOG_LOSS"
SELECTION_RULE = "LOWER_EQUAL_WEIGHT_MEAN_WINS; WITHIN_1E-12_SELECT_C_0.1"
TIE_TOLERANCE = 1e-12
LOG_LOSS_CLIP = 1e-15

PREDICTION_INTEGRITY_COLUMNS = (
    "event_id", "interval_id", "response_grid_m", "cell_id",
    "interval_number", "predicted_probability",
)

EXECUTION_MANIFEST_REQUIRED_FIELDS = (
    "schema_name", "schema_version", "paper1_run_id",
    "runner_source_commit", "runner_identity", "scientific_run_git_commit",
    "clean_tree", "environment_identity", "package_lock_identity",
    "execution_contract_id", "analysis_id", "model_family", "model_role",
    "outer_evaluation", "training_history", "validation_history",
    "heldout_history", "hyperparameters", "hyperparameter_state",
    "random_seeds", "input_artifacts", "output_prediction_artifact",
    "checkpoints", "start_timestamp_utc", "end_timestamp_utc",
    "process_metadata", "child_process_metadata", "terminal_status",
    "exception_metadata", "evidence_classification", "manifest_role",
)

TUNING_PLAN = MappingProxyType({
    "B1_TO_B2": (((1, 3), 4), ((1, 3, 4), 5)),
    "B1_B2_TO_B3": tuple(((1, 3, 4, 5), value) for value in (6, 8, 9, 10)),
    "B1_B2_B3_TO_B4": (
        *tuple(((1, 3, 4, 5), value) for value in (6, 8, 9, 10)),
        *tuple(((1, 3, 4, 5, 6, 8, 9, 10), value)
               for value in (11, 12, 14, 15)),
    ),
})


@dataclass(frozen=True)
class ValidatedExecutionManifest:
    project_root: str
    manifest_path: str
    manifest_sha256: str
    record: Mapping[str, object]
    validation_result: str = "PASS"
    claim_level: str = MANIFEST_ROLE


@dataclass(frozen=True)
class IntegrityValidatedPredictionArtifact:
    project_root: str
    manifest_path: str
    manifest_sha256: str
    artifact_path: str
    artifact_sha256: str
    artifact_bytes: int
    row_count: int
    canonical_key_sha256: str
    execution_contract_id: str
    analysis_id: str
    model_family: str
    model_role: str
    outer_evaluation: str
    training_history: tuple[int, ...]
    validation_history: tuple[int, ...]
    heldout_history: tuple[int, ...]
    hyperparameters: tuple[tuple[str, object], ...]
    hyperparameter_state: tuple[tuple[str, object], ...]
    evidence_classification: str
    outcome_source_identity: str
    outcome_key_identity: str
    records: tuple[tuple[object, ...], ...]
    validation_result: str = "PASS"
    claim_level: str = "ARTIFACT_INTEGRITY_AND_INTERNAL_CONSISTENCY"

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame.from_records(
            self.records, columns=PREDICTION_INTEGRITY_COLUMNS)


@dataclass(frozen=True)
class IntegrityValidatedOutcomeSet:
    project_root: str
    source_path: str
    authority_path: str
    authority_identity: str
    source_identity: str
    canonical_key_interval_value_sha256: str
    evidence_classification: str
    risk_set_id: str
    resolution_m: int
    response_field: str
    records: tuple[tuple[object, ...], ...]
    validation_result: str = "PASS"

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame.from_records(
            self.records, columns=(*KEY_FIELDS, "interval_number", "y"))


@dataclass(frozen=True)
class SelectedCReconstruction:
    evaluation_identity: str
    candidate_scores: tuple[tuple[float, float], ...]
    interval_losses: tuple[tuple[float, int, float], ...]
    selected_c: float
    selection_metric: str = SELECTION_METRIC
    aggregation: str = "EQUAL_WEIGHT_MEAN_ACROSS_GOVERNED_VALIDATION_INTERVALS"
    tie_tolerance: float = TIE_TOLERANCE
    tie_break: float = 0.1
    reconstruction_result: str = "PASS"


@dataclass(frozen=True)
class PrevalenceReconstruction:
    evaluation_identity: str
    training_history: tuple[int, ...]
    heldout_history: tuple[int, ...]
    training_rows: int
    training_positive: int
    probability: float
    reconstruction_result: str = "PASS"


@dataclass(frozen=True)
class GovernedGeometryContract:
    benchmark_contract_sha256: str
    benchmark_id: str
    evaluation_identity: str
    predictor_fields: tuple[str, ...]
    model_family: str
    model_role: str
    selected_c_source_role: str
    selected_c_candidates: tuple[float, ...]
    geometry_specific_retuning: str
    fitting_authority: str
    post_run_rerun: str


@dataclass(frozen=True)
class G07EvidenceRequirement:
    evidence_id: str
    execution_role: str
    contract_source: str
    required_inputs: tuple[str, ...]
    required_metadata: tuple[str, ...]
    prediction_artifact_required: bool
    checkpoint_metadata_required: bool
    terminal_disposition_required: bool
    allowed_classifications: tuple[str, ...] = EVIDENCE_CLASSIFICATIONS


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                            text=True, check=False)
    if check and result.returncode:
        raise ContractError(f"ERR_G06_4E_GIT:{' '.join(args)}:{result.stderr.strip()}")
    return result


def _git_blob(root: Path, commit: str, relative_path: str) -> bytes:
    result = subprocess.run(["git", "show", f"{commit}:{relative_path}"],
                            cwd=root, capture_output=True, check=False)
    if result.returncode:
        raise ContractError(f"ERR_G06_4E_GIT_BLOB:{relative_path}")
    return result.stdout


def _load_json(path: Path, reason: str) -> tuple[dict[str, object], bytes]:
    if not path.is_file():
        raise ContractError(reason)
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ContractError(reason) from exc
    if not isinstance(value, dict):
        raise ContractError(reason)
    return value, raw


def _exact_keys(value: Mapping[str, object], expected: Sequence[str], reason: str) -> None:
    if set(value) != set(expected):
        raise ContractError(reason)


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _valid_commit(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _safe_project_path(root: Path, supplied: object) -> Path:
    candidate = Path(str(supplied))
    if not str(supplied) or candidate.is_absolute() or ".." in candidate.parts:
        raise ContractError("ERR_G06_4E_PATH")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ContractError("ERR_G06_4E_PATH") from exc
    return resolved


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError("ERR_G06_4E_MANIFEST_TIMESTAMP")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError("ERR_G06_4E_MANIFEST_TIMESTAMP") from exc


def _key_hash(frame: pd.DataFrame, include_value: bool = False) -> str:
    columns = [*KEY_FIELDS, "interval_number"]
    if include_value:
        columns.append("y")
    ordered = frame.loc[:, columns].sort_values(
        [*KEY_FIELDS, "interval_number"], kind="stable").reset_index(drop=True)
    return _sha(ordered.to_csv(index=False, lineterminator="\n").encode("utf-8"))


def _load_authority(root: Path) -> Mapping[str, object]:
    path = root / G06_4E_AUTHORITY_PATH
    if not path.is_file() or _path_sha(path) != G06_4E_AUTHORITY_SHA256:
        raise ContractError("ERR_G06_4E_AUTHORITY_IDENTITY")
    record, _ = _load_json(path, "ERR_G06_4E_AUTHORITY_SCHEMA")
    required = {
        "schema_version", "gate_version", "g06_4e_build_base_head",
        "boundary_decision", "acceptance_derivation", "authority_boundary",
        "tuning_authority", "benchmark_authority", "manifest_schema",
        "g07_evidence_schema", "postrun_rerun_policy", "current_state",
        "regressions", "execution_universe", "carried_limitations",
        "required_ancestry_rule",
    }
    if (set(record) != required or
            record.get("schema_version") != G06_4E_AUTHORITY_SCHEMA_VERSION or
            record.get("gate_version") != G06_4E_GATE_VERSION):
        raise ContractError("ERR_G06_4E_AUTHORITY_SCHEMA")
    return MappingProxyType(record)


def _validate_boundary_decision(root: Path, authority: Mapping[str, object]) -> None:
    decision = authority["boundary_decision"]
    if not isinstance(decision, dict) or decision.get("status") != "FROZEN_ACCEPTED":
        raise ContractError("ERR_G06_4E_BOUNDARY_DECISION")
    artifacts = decision.get("artifacts")
    if not isinstance(artifacts, dict) or len(artifacts) != 4:
        raise ContractError("ERR_G06_4E_BOUNDARY_DECISION")
    for relative, expected in artifacts.items():
        path = root / str(relative)
        if not _valid_sha256(expected) or not path.is_file() or _path_sha(path) != expected:
            raise ContractError(f"ERR_G06_4E_BOUNDARY_IDENTITY:{relative}")


def g06_4e_lifecycle_authority(project_root: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    authority = _load_authority(root)
    current = _git(root, "rev-parse", "HEAD").stdout.strip()
    derivation = authority["acceptance_derivation"]
    if (not isinstance(derivation, dict) or
            derivation.get("method") !=
            "UNIQUE_GIT_ADD_COMMIT_FOR_G06_4E_AUTHORITY_RECORD"):
        raise ContractError("ERR_G06_4E_ACCEPTANCE_DERIVATION")
    relative = str(derivation.get("path", ""))
    commits = tuple(line for line in _git(
        root, "log", "--diff-filter=A", "--format=%H", "--", relative
    ).stdout.splitlines() if line)
    if not commits:
        status = _git(root, "status", "--short", "--", relative).stdout.strip()
        if (current != authority["g06_4e_build_base_head"] or
                status != f"?? {relative}"):
            raise ContractError("ERR_G06_4E_PREACCEPTANCE_STATE")
        state, acceptance = "PRE_ACCEPTANCE_AUDIT", "UNCOMMITTED"
    else:
        if len(commits) != 1:
            raise ContractError("ERR_G06_4E_ACCEPTANCE_DERIVATION")
        acceptance = commits[0]
        if _git(root, "merge-base", "--is-ancestor",
                str(authority["g06_4e_build_base_head"]), acceptance,
                check=False).returncode:
            raise ContractError("ERR_G06_4E_ACCEPTANCE_BASE")
        if _git(root, "merge-base", "--is-ancestor", acceptance, current,
                check=False).returncode:
            raise ContractError("ERR_G06_4E_ACCEPTANCE_ANCESTRY")
        frozen = derivation.get("frozen_paths")
        if not isinstance(frozen, list) or len(frozen) != 4:
            raise ContractError("ERR_G06_4E_ACCEPTANCE_DERIVATION")
        for path_text in frozen:
            path = root / str(path_text)
            committed = _git_blob(root, acceptance, str(path_text))
            if (not path.is_file() or
                    path.read_bytes().replace(b"\r\n", b"\n") !=
                    committed.replace(b"\r\n", b"\n")):
                raise ContractError(f"ERR_G06_4E_FROZEN_SOURCE:{path_text}")
        state = "ACCEPTED_DESCENDANT"
    return MappingProxyType({
        "gate_version": G06_4E_GATE_VERSION,
        "build_base_head": authority["g06_4e_build_base_head"],
        "current_head": current,
        "acceptance_commit": acceptance,
        "acceptance_state": state,
        "ancestry_rule": authority["required_ancestry_rule"],
    })


def validate_execution_manifest(project_root: Path, manifest_path: Path,
                                verify_files: bool = True) -> ValidatedExecutionManifest:
    """Validate reproducibility metadata without claiming process origin."""
    root = Path(project_root).resolve()
    path = Path(manifest_path).resolve()
    record, raw = _load_json(path, "ERR_G06_4E_MANIFEST_SCHEMA")
    _exact_keys(record, EXECUTION_MANIFEST_REQUIRED_FIELDS,
                "ERR_G06_4E_MANIFEST_FIELDS")
    if (record["schema_name"] != MANIFEST_SCHEMA_NAME or
            record["schema_version"] != MANIFEST_SCHEMA_VERSION or
            record["manifest_role"] != MANIFEST_ROLE):
        raise ContractError("ERR_G06_4E_MANIFEST_SCHEMA")
    if not _valid_commit(record["runner_source_commit"]):
        raise ContractError("ERR_G06_4E_RUNNER_COMMIT")
    if not _valid_commit(record["scientific_run_git_commit"]):
        raise ContractError("ERR_G06_4E_SCIENTIFIC_COMMIT")
    classification = record["evidence_classification"]
    if classification not in EVIDENCE_CLASSIFICATIONS:
        raise ContractError("ERR_G06_4E_EVIDENCE_CLASSIFICATION")
    if classification == "SCIENTIFIC" and record["clean_tree"] is not True:
        raise ContractError("ERR_G06_4E_DIRTY_SCIENTIFIC_RUN")
    if not isinstance(record["clean_tree"], bool):
        raise ContractError("ERR_G06_4E_CLEAN_TREE_SCHEMA")
    for field in (
        "paper1_run_id", "runner_identity", "environment_identity",
        "package_lock_identity", "execution_contract_id", "analysis_id",
        "model_family", "model_role", "outer_evaluation",
    ):
        if not isinstance(record[field], str) or not record[field]:
            raise ContractError(f"ERR_G06_4E_MANIFEST_VALUE:{field}")
    if not _valid_sha256(record["execution_contract_id"]):
        raise ContractError("ERR_G06_4E_CONTRACT_IDENTITY")
    for field in ("training_history", "validation_history", "heldout_history"):
        value = record[field]
        if (not isinstance(value, list) or
                any(not isinstance(item, int) for item in value) or
                len(value) != len(set(value))):
            raise ContractError("ERR_G06_4E_HISTORY")
    if not isinstance(record["hyperparameters"], dict) or not isinstance(
            record["hyperparameter_state"], dict):
        raise ContractError("ERR_G06_4E_HYPERPARAMETER_SCHEMA")
    seeds = record["random_seeds"]
    if not isinstance(seeds, list) or any(not isinstance(seed, int) for seed in seeds):
        raise ContractError("ERR_G06_4E_SEED_SCHEMA")
    inputs = record["input_artifacts"]
    if not isinstance(inputs, list) or not inputs:
        raise ContractError("ERR_G06_4E_INPUT_ARTIFACTS")
    input_keys = ("path", "sha256", "schema", "key_identity")
    for item in inputs:
        if not isinstance(item, dict):
            raise ContractError("ERR_G06_4E_INPUT_ARTIFACTS")
        _exact_keys(item, input_keys, "ERR_G06_4E_INPUT_ARTIFACTS")
        if not _valid_sha256(item["sha256"]) or not _valid_sha256(item["key_identity"]):
            raise ContractError("ERR_G06_4E_INPUT_IDENTITY")
        source_path = _safe_project_path(root, item["path"])
        if verify_files and (not source_path.is_file() or
                             _path_sha(source_path) != item["sha256"]):
            raise ContractError("ERR_G06_4E_INPUT_HASH")
    terminal = record["terminal_status"]
    if terminal not in TERMINAL_STATUSES:
        raise ContractError("ERR_G06_4E_TERMINAL_STATUS")
    output = record["output_prediction_artifact"]
    if terminal == "COMPLETE":
        if not isinstance(output, dict):
            raise ContractError("ERR_G06_4E_OUTPUT_REQUIRED")
        _exact_keys(output, ("path", "sha256", "schema", "row_count",
                             "key_identity", "required_columns"),
                    "ERR_G06_4E_OUTPUT_SCHEMA")
        if (not _valid_sha256(output["sha256"]) or
                not _valid_sha256(output["key_identity"]) or
                not isinstance(output["row_count"], int) or output["row_count"] <= 0 or
                output["schema"] != PREDICTION_ARTIFACT_SCHEMA or
                tuple(output["required_columns"]) != PREDICTION_INTEGRITY_COLUMNS):
            raise ContractError("ERR_G06_4E_OUTPUT_SCHEMA")
        output_path = _safe_project_path(root, output["path"])
        if verify_files and (not output_path.is_file() or
                             _path_sha(output_path) != output["sha256"]):
            raise ContractError("ERR_G06_4E_OUTPUT_HASH")
        if record["exception_metadata"] not in (None, {}):
            raise ContractError("ERR_G06_4E_TERMINAL_EXCEPTION")
    else:
        if output is not None:
            raise ContractError("ERR_G06_4E_INCOMPLETE_OUTPUT")
        if terminal == "FAILED_RUNTIME" and not isinstance(record["exception_metadata"], dict):
            raise ContractError("ERR_G06_4E_FAILURE_METADATA")
    checkpoints = record["checkpoints"]
    if not isinstance(checkpoints, list):
        raise ContractError("ERR_G06_4E_CHECKPOINT_SCHEMA")
    previous_sequence = None
    checkpoint_keys = ("path", "sha256", "sequence", "resume_from_sequence")
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict):
            raise ContractError("ERR_G06_4E_CHECKPOINT_SCHEMA")
        _exact_keys(checkpoint, checkpoint_keys, "ERR_G06_4E_CHECKPOINT_SCHEMA")
        sequence = checkpoint["sequence"]
        if not isinstance(sequence, int) or sequence <= 0:
            raise ContractError("ERR_G06_4E_CHECKPOINT_SEQUENCE")
        if checkpoint["resume_from_sequence"] != previous_sequence:
            raise ContractError("ERR_G06_4E_CHECKPOINT_LINEAGE")
        if not _valid_sha256(checkpoint["sha256"]):
            raise ContractError("ERR_G06_4E_CHECKPOINT_IDENTITY")
        checkpoint_path = _safe_project_path(root, checkpoint["path"])
        if verify_files and (not checkpoint_path.is_file() or
                             _path_sha(checkpoint_path) != checkpoint["sha256"]):
            raise ContractError("ERR_G06_4E_CHECKPOINT_IDENTITY")
        previous_sequence = sequence
    start = _timestamp(record["start_timestamp_utc"])
    end = _timestamp(record["end_timestamp_utc"])
    if end < start:
        raise ContractError("ERR_G06_4E_MANIFEST_TIMESTAMP")
    if not isinstance(record["process_metadata"], dict) or not isinstance(
            record["child_process_metadata"], list):
        raise ContractError("ERR_G06_4E_PROCESS_METADATA")
    return ValidatedExecutionManifest(
        str(root), str(path), _sha(raw), MappingProxyType(record))


def _prediction_frame(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, dtype={
            "event_id": "string", "interval_id": "string", "cell_id": "string",
        })
    except Exception as exc:
        raise ContractError("ERR_G06_4E_PREDICTION_SCHEMA") from exc
    if tuple(frame.columns) != PREDICTION_INTEGRITY_COLUMNS:
        raise ContractError("ERR_G06_4E_PREDICTION_SCHEMA")
    if frame.empty or frame.isna().any().any():
        raise ContractError("ERR_G06_4E_PREDICTION_VALUES")
    probabilities = pd.to_numeric(frame["predicted_probability"], errors="coerce")
    if (not np.isfinite(probabilities).all() or (probabilities < 0).any() or
            (probabilities > 1).any()):
        raise ContractError("ERR_G06_4E_PREDICTION_VALUES")
    for field in ("response_grid_m", "interval_number"):
        numeric = pd.to_numeric(frame[field], errors="coerce")
        if not np.isfinite(numeric).all() or not np.equal(numeric, np.floor(numeric)).all():
            raise ContractError("ERR_G06_4E_PREDICTION_VALUES")
        frame[field] = numeric.astype(int)
    frame["predicted_probability"] = probabilities.astype(float)
    if frame.duplicated(list(KEY_FIELDS)).any():
        raise ContractError("ERR_G06_4E_DUPLICATE_KEYS")
    return frame.sort_values(list(KEY_FIELDS), kind="stable").reset_index(drop=True)


def integrity_validate_prediction_artifact(
        project_root: Path, manifest_path: Path, *, expected_contract_id: str,
        expected_analysis_id: str, expected_model_family: str,
        expected_model_role: str, expected_outer_evaluation: str,
        expected_evidence_classification: str,
        expected_heldout_keys: pd.DataFrame) -> IntegrityValidatedPredictionArtifact:
    """Validate persisted prediction identity without process-origin claims."""
    validated = validate_execution_manifest(project_root, manifest_path, True)
    root, record = Path(project_root).resolve(), validated.record
    bindings = {
        "execution_contract_id": expected_contract_id,
        "analysis_id": expected_analysis_id,
        "model_family": expected_model_family,
        "model_role": expected_model_role,
        "outer_evaluation": expected_outer_evaluation,
        "evidence_classification": expected_evidence_classification,
    }
    if any(record[key] != value for key, value in bindings.items()):
        raise ContractError("ERR_G06_4E_PREDICTION_BINDING")
    output = record["output_prediction_artifact"]
    artifact_path = _safe_project_path(root, output["path"])
    frame = _prediction_frame(artifact_path)
    key_identity = _key_hash(frame)
    if len(frame) != output["row_count"] or key_identity != output["key_identity"]:
        raise ContractError("ERR_G06_4E_PREDICTION_IDENTITY")
    required_key_columns = [*KEY_FIELDS, "interval_number"]
    if set(required_key_columns).difference(expected_heldout_keys.columns):
        raise ContractError("ERR_G06_4E_EXPECTED_KEYS")
    expected = expected_heldout_keys.loc[:, required_key_columns].sort_values(
        list(KEY_FIELDS), kind="stable").reset_index(drop=True)
    if (frame.loc[:, required_key_columns].to_dict("records") !=
            expected.to_dict("records")):
        raise ContractError("ERR_G06_4E_HELDOUT_KEYS")
    outcome_inputs = [item for item in record["input_artifacts"]
                      if item["schema"] == OUTCOME_INPUT_SCHEMA]
    if len(outcome_inputs) != 1:
        raise ContractError("ERR_G06_4E_OUTCOME_INPUT")
    outcome = outcome_inputs[0]
    return IntegrityValidatedPredictionArtifact(
        str(root), validated.manifest_path, validated.manifest_sha256,
        str(artifact_path), str(output["sha256"]), artifact_path.stat().st_size,
        len(frame), key_identity, str(record["execution_contract_id"]),
        str(record["analysis_id"]), str(record["model_family"]),
        str(record["model_role"]), str(record["outer_evaluation"]),
        tuple(record["training_history"]), tuple(record["validation_history"]),
        tuple(record["heldout_history"]),
        tuple(sorted(record["hyperparameters"].items())),
        tuple(sorted(record["hyperparameter_state"].items())),
        str(record["evidence_classification"]), str(outcome["sha256"]),
        str(outcome["key_identity"]),
        tuple(tuple(row) for row in frame.loc[:, PREDICTION_INTEGRITY_COLUMNS].itertuples(
            index=False, name=None)),
    )


def outcome_set_from_authenticated_artifact(
        artifact: AuthenticatedOutcomeArtifact) -> IntegrityValidatedOutcomeSet:
    if (not isinstance(artifact, AuthenticatedOutcomeArtifact) or
            artifact.authentication_result != "PASS"):
        raise ContractError("ERR_G06_4E_OUTCOME_AUTHENTICATION")
    refreshed = authenticate_outcome_artifact(
        Path(artifact.project_root), artifact.authority.risk_set_id,
        artifact.authority.resolution_m,
        Path(artifact.project_root) / artifact.authority.relative_path,
        artifact.authority.response_field,
    )
    if refreshed != artifact:
        raise ContractError("ERR_G06_4E_OUTCOME_HANDLE_BINDING")
    records = tuple((row.event_id, row.interval_id, row.response_grid_m,
                     row.cell_id, row.interval_number, row.response_y)
                    for row in refreshed.rows)
    return IntegrityValidatedOutcomeSet(
        refreshed.project_root, refreshed.authority.relative_path,
        refreshed.authority.authority_manifest,
        _path_sha(Path(refreshed.project_root) / refreshed.authority.authority_manifest),
        refreshed.observed_sha256,
        refreshed.observed_key_interval_response_sha256, "SCIENTIFIC",
        refreshed.authority.risk_set_id, refreshed.authority.resolution_m,
        refreshed.authority.response_field, records,
    )


def _synthetic_outcome_set(project_root: Path,
                           authority_path: Path) -> IntegrityValidatedOutcomeSet:
    root = Path(project_root).resolve()
    authority_file = Path(authority_path).resolve()
    try:
        authority_relative = authority_file.relative_to(root)
    except ValueError as exc:
        raise ContractError("ERR_G06_4E_PATH") from exc
    authority, _ = _load_json(
        authority_file, "ERR_G06_4E_SYNTHETIC_OUTCOME_AUTHORITY")
    required_authority = (
        "schema_version", "evidence_classification", "risk_set_id",
        "resolution_m", "response_field", "source_path", "source_sha256",
        "columns", "row_count", "key_identity",
        "key_interval_value_identity",
    )
    _exact_keys(authority, required_authority,
                "ERR_G06_4E_SYNTHETIC_OUTCOME_AUTHORITY")
    if (authority["schema_version"] != SYNTHETIC_OUTCOME_AUTHORITY_SCHEMA or
            authority["evidence_classification"] != "SYNTHETIC_TEST" or
            not isinstance(authority["risk_set_id"], str) or
            not isinstance(authority["resolution_m"], int) or
            authority["resolution_m"] <= 0 or
            authority["response_field"] != "y" or
            not isinstance(authority["row_count"], int) or
            authority["row_count"] <= 0 or
            not _valid_sha256(authority["source_sha256"]) or
            not _valid_sha256(authority["key_identity"]) or
            not _valid_sha256(authority["key_interval_value_identity"])):
        raise ContractError("ERR_G06_4E_SYNTHETIC_OUTCOME_AUTHORITY")
    source_path = _safe_project_path(root, authority["source_path"])
    if (not source_path.is_file() or
            _path_sha(source_path) != authority["source_sha256"]):
        raise ContractError("ERR_G06_4E_OUTCOME_SOURCE_HASH")
    try:
        frame = pd.read_csv(source_path, dtype={
            "event_id": "string", "interval_id": "string", "cell_id": "string",
        })
    except Exception as exc:
        raise ContractError("ERR_G06_4E_OUTCOME_SCHEMA") from exc
    required = (*KEY_FIELDS, "interval_number", "y")
    if (tuple(authority["columns"]) != required or
            tuple(frame.columns) != required or frame.empty or
            len(frame) != authority["row_count"] or
            frame.isna().any().any()):
        raise ContractError("ERR_G06_4E_OUTCOME_SCHEMA")
    for field in ("response_grid_m", "interval_number", "y"):
        numeric = pd.to_numeric(frame[field], errors="coerce")
        if (not np.isfinite(numeric).all() or
                not np.equal(numeric, np.floor(numeric)).all()):
            raise ContractError("ERR_G06_4E_OUTCOME_VALUES")
        frame[field] = numeric.astype(int)
    if frame.duplicated(list(KEY_FIELDS)).any() or not frame["y"].isin((0, 1)).all():
        raise ContractError("ERR_G06_4E_OUTCOME_VALUES")
    if not frame["response_grid_m"].eq(authority["resolution_m"]).all():
        raise ContractError("ERR_G06_4E_OUTCOME_VALUES")
    key_identity = _key_hash(frame)
    value_identity = _key_hash(frame, True)
    if (key_identity != authority["key_identity"] or
            value_identity != authority["key_interval_value_identity"]):
        raise ContractError("ERR_G06_4E_OUTCOME_IDENTITY")
    frame = frame.sort_values(list(KEY_FIELDS), kind="stable").reset_index(drop=True)
    records = tuple(tuple(row) for row in frame.loc[:, required].itertuples(
        index=False, name=None))
    return IntegrityValidatedOutcomeSet(
        str(root), str(Path(authority["source_path"])),
        str(authority_relative), _path_sha(authority_file),
        str(authority["source_sha256"]),
        value_identity, "SYNTHETIC_TEST", str(authority["risk_set_id"]),
        int(authority["resolution_m"]), str(authority["response_field"]), records)


def _revalidate_outcome_set(
        outcomes: IntegrityValidatedOutcomeSet) -> IntegrityValidatedOutcomeSet:
    if (not isinstance(outcomes, IntegrityValidatedOutcomeSet) or
            outcomes.validation_result != "PASS"):
        raise ContractError("ERR_G06_4E_OUTCOME_TYPE")
    if outcomes.evidence_classification == "SCIENTIFIC":
        artifact = authenticate_outcome_artifact(
            Path(outcomes.project_root), outcomes.risk_set_id,
            outcomes.resolution_m,
            Path(outcomes.project_root) / outcomes.source_path,
            outcomes.response_field,
        )
        refreshed = outcome_set_from_authenticated_artifact(artifact)
    elif outcomes.evidence_classification == "SYNTHETIC_TEST":
        refreshed = _synthetic_outcome_set(
            Path(outcomes.project_root),
            Path(outcomes.project_root) / outcomes.authority_path)
    else:
        raise ContractError("ERR_G06_4E_OUTCOME_CLASSIFICATION")
    if refreshed != outcomes:
        raise ContractError("ERR_G06_4E_OUTCOME_HANDLE_BINDING")
    return refreshed


def _revalidate_prediction_handle(
        artifact: IntegrityValidatedPredictionArtifact,
        outcomes: IntegrityValidatedOutcomeSet,
        expected_evaluation: str | None = None,
        ) -> IntegrityValidatedPredictionArtifact:
    if (not isinstance(artifact, IntegrityValidatedPredictionArtifact) or
            artifact.validation_result != "PASS"):
        raise ContractError("ERR_G06_4E_PREDICTION_HANDLE")
    root = Path(artifact.project_root).resolve()
    manifest_path = Path(artifact.manifest_path).resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise ContractError("ERR_G06_4E_PATH") from exc
    manifest = validate_execution_manifest(root, manifest_path, True)
    record = manifest.record
    output_path = _safe_project_path(root, record["output_prediction_artifact"]["path"])
    persisted = _prediction_frame(output_path)
    intervals = tuple(sorted(set(int(value) for value in persisted["interval_number"])))
    outcome_frame = outcomes.to_frame()
    expected_keys = outcome_frame.loc[
        outcome_frame["interval_number"].isin(intervals),
        [*KEY_FIELDS, "interval_number"],
    ]
    if expected_keys.empty:
        raise ContractError("ERR_G06_4E_OUTCOME_PAIRING")
    refreshed = integrity_validate_prediction_artifact(
        root, manifest_path,
        expected_contract_id=str(record["execution_contract_id"]),
        expected_analysis_id=str(record["analysis_id"]),
        expected_model_family=str(record["model_family"]),
        expected_model_role=str(record["model_role"]),
        expected_outer_evaluation=str(record["outer_evaluation"]),
        expected_evidence_classification=str(record["evidence_classification"]),
        expected_heldout_keys=expected_keys,
    )
    if expected_evaluation is not None and refreshed.outer_evaluation != expected_evaluation:
        raise ContractError("ERR_G06_4E_PREDICTION_BINDING")
    if refreshed != artifact:
        raise ContractError("ERR_G06_4E_PREDICTION_HANDLE_BINDING")
    return refreshed


def _interval_log_loss(prediction: pd.DataFrame, outcomes: pd.DataFrame) -> float:
    keys = [*KEY_FIELDS, "interval_number"]
    paired = prediction.merge(outcomes.loc[:, [*keys, "y"]], on=keys,
                              how="inner", validate="one_to_one")
    if len(paired) != len(prediction):
        raise ContractError("ERR_G06_4E_OUTCOME_PAIRING")
    y = paired["y"].to_numpy(float)
    p = np.clip(paired["predicted_probability"].to_numpy(float),
                LOG_LOSS_CLIP, 1.0 - LOG_LOSS_CLIP)
    return float(np.mean(-y * np.log(p) - (1.0 - y) * np.log(1.0 - p)))


def reconstruct_selected_c(
        artifacts: Sequence[IntegrityValidatedPredictionArtifact],
        outcomes: IntegrityValidatedOutcomeSet,
        evaluation_identity: str) -> SelectedCReconstruction:
    if evaluation_identity not in TUNING_PLAN:
        raise ContractError("ERR_G06_4E_TUNING_EVALUATION")
    outcomes = _revalidate_outcome_set(outcomes)
    expected_heldout = tuple(OUTER_EVALUATIONS[evaluation_identity][1])
    expected = {
        (candidate, tuple(training), validation)
        for candidate in ALLOWED_BASELINE_C
        for training, validation in TUNING_PLAN[evaluation_identity]
    }
    observed: dict[
        tuple[float, tuple[int, ...], int], IntegrityValidatedPredictionArtifact
    ] = {}
    for supplied_artifact in artifacts:
        artifact = _revalidate_prediction_handle(
            supplied_artifact, outcomes, evaluation_identity)
        if (artifact.analysis_id != BASELINE_ANALYSIS_ID or
                artifact.model_family != BASELINE_MODEL_FAMILY or
                artifact.model_role != BASELINE_MODEL_ROLE or
                artifact.outer_evaluation != evaluation_identity or
                artifact.heldout_history != expected_heldout or
                artifact.evidence_classification != outcomes.evidence_classification or
                artifact.outcome_source_identity != outcomes.source_identity or
                artifact.outcome_key_identity != outcomes.canonical_key_interval_value_sha256):
            raise ContractError("ERR_G06_4E_SELECTED_C_BINDING")
        hyperparameters = dict(artifact.hyperparameters)
        state = dict(artifact.hyperparameter_state)
        if set(hyperparameters) != {"C"} or set(state) != {"state", "candidate_c"}:
            raise ContractError("ERR_G06_4E_CANDIDATE_SCHEMA")
        candidate = float(hyperparameters["C"])
        if state != {"state": "CANDIDATE", "candidate_c": candidate}:
            raise ContractError("ERR_G06_4E_CANDIDATE_SCHEMA")
        if len(artifact.validation_history) != 1:
            raise ContractError("ERR_G06_4E_TUNING_CHRONOLOGY")
        validation = artifact.validation_history[0]
        key = (candidate, artifact.training_history, validation)
        if key in observed:
            raise ContractError("ERR_G06_4E_DUPLICATE_CANDIDATE")
        frame = artifact.to_frame()
        if set(frame["interval_number"]) != {validation}:
            raise ContractError("ERR_G06_4E_TUNING_CHRONOLOGY")
        observed[key] = artifact
    if set(observed) != expected:
        raise ContractError("ERR_G06_4E_CANDIDATE_SET")
    outcome_frame = outcomes.to_frame()
    interval_losses: list[tuple[float, int, float]] = []
    scores: list[tuple[float, float]] = []
    for candidate in ALLOWED_BASELINE_C:
        losses = []
        for training, validation in TUNING_PLAN[evaluation_identity]:
            artifact = observed[(candidate, tuple(training), validation)]
            loss = _interval_log_loss(artifact.to_frame(), outcome_frame)
            interval_losses.append((candidate, validation, loss))
            losses.append(loss)
        scores.append((candidate, float(np.mean(losses))))
    if abs(scores[0][1] - scores[1][1]) <= TIE_TOLERANCE:
        selected = 0.1
    else:
        selected = min(scores, key=lambda item: item[1])[0]
    return SelectedCReconstruction(
        evaluation_identity, tuple(scores), tuple(interval_losses), selected)


def validate_selected_c_claim(
        reconstruction: SelectedCReconstruction, claimed_selected_c: float,
        claimed_candidate_scores: Mapping[float, float]) -> None:
    expected = dict(reconstruction.candidate_scores)
    observed = {float(key): float(value) for key, value in claimed_candidate_scores.items()}
    if set(observed) != set(ALLOWED_BASELINE_C):
        raise ContractError("ERR_G06_4E_CLAIMED_CANDIDATES")
    if any(not math.isclose(observed[key], expected[key], rel_tol=0.0, abs_tol=1e-15)
           for key in expected):
        raise ContractError("ERR_G06_4E_RUNNER_SCORE_MISMATCH")
    if not math.isclose(float(claimed_selected_c), reconstruction.selected_c,
                        rel_tol=0.0, abs_tol=0.0):
        raise ContractError("ERR_G06_4E_ARBITRARY_SELECTED_C")


def training_prevalence_probability(training_positive: int, training_rows: int) -> float:
    positives, rows = int(training_positive), int(training_rows)
    if rows <= 0 or positives < 0 or positives > rows:
        raise ContractError("ERR_G06_4E_PREVALENCE_COUNTS")
    return (positives + 0.5) / (rows + 1.0)


def reconstruct_training_prevalence(
        outcomes: IntegrityValidatedOutcomeSet, evaluation_identity: str,
        expected_source_identity: str) -> PrevalenceReconstruction:
    if evaluation_identity not in OUTER_EVALUATIONS:
        raise ContractError("ERR_G06_4E_PREVALENCE_EVALUATION")
    outcomes = _revalidate_outcome_set(outcomes)
    if outcomes.source_identity != expected_source_identity:
        raise ContractError("ERR_G06_4E_PREVALENCE_SOURCE")
    training = tuple(OUTER_EVALUATIONS[evaluation_identity][0])
    heldout = tuple(OUTER_EVALUATIONS[evaluation_identity][1])
    frame = outcomes.to_frame()
    observed_training = frame.loc[frame["interval_number"].isin(training)]
    observed_heldout = frame.loc[frame["interval_number"].isin(heldout)]
    if observed_training.empty or observed_heldout.empty:
        raise ContractError("ERR_G06_4E_PREVALENCE_HISTORY")
    rows = len(observed_training)
    positives = int(observed_training["y"].sum())
    return PrevalenceReconstruction(
        evaluation_identity, training, heldout, rows, positives,
        training_prevalence_probability(positives, rows))


def validate_prevalence_claim(
        reconstruction: PrevalenceReconstruction, *, training_rows: int,
        training_positive: int, probability: float) -> None:
    if (int(training_rows) != reconstruction.training_rows or
            int(training_positive) != reconstruction.training_positive or
            not math.isclose(float(probability), reconstruction.probability,
                             rel_tol=0.0, abs_tol=1e-15)):
        raise ContractError("ERR_G06_4E_PREVALENCE_CLAIM")


def governed_geometry_contract(project_root: Path,
                               evaluation_identity: str) -> GovernedGeometryContract:
    matches = tuple(
        contract for contract in _previous._build_benchmark_contracts(
            Path(project_root).resolve())
        if contract.benchmark_type == "GEOMETRY_LOGISTIC" and
        contract.evaluation_identity == evaluation_identity
    )
    if len(matches) != 1:
        raise ContractError("ERR_G06_4E_GEOMETRY_SCOPE")
    contract = matches[0]
    if (tuple(contract.predictor_fields) != tuple(GEOMETRY_BENCHMARK_FIELDS) or
            contract.model_family != "GEOMETRY_LOGISTIC" or
            contract.model_role != "benchmark"):
        raise ContractError("ERR_G06_4E_GEOMETRY_CONTRACT")
    return GovernedGeometryContract(
        contract.contract_sha256, contract.benchmark_id,
        contract.evaluation_identity, tuple(contract.predictor_fields),
        contract.model_family, contract.model_role, GEOMETRY_C_SOURCE_ROLE,
        ALLOWED_BASELINE_C, "PROHIBITED", "G07_RUNNER",
        "POST_RUN_INDEPENDENT_AUDIT",
    )


def validate_governed_geometry_contract(
        project_root: Path, contract: GovernedGeometryContract) -> None:
    if (not isinstance(contract, GovernedGeometryContract) or
            contract != governed_geometry_contract(
                project_root, contract.evaluation_identity)):
        raise ContractError("ERR_G06_4E_GEOMETRY_CONTRACT_BINDING")


_G07_EVIDENCE_REQUIREMENTS = (
    G07EvidenceRequirement(
        "G07E_BASELINE_LOGISTIC_CANDIDATE", "BASELINE24_LOGISTIC_CANDIDATE",
        "G05_G06_EXECUTION_CONTRACT", ("predictors", "outcomes", "support"),
        ("candidate_c", "training_history", "validation_history",
         "outer_heldout_history"), True, True, True),
    G07EvidenceRequirement(
        "G07E_EVT_LOGISTIC_CANDIDATE", "BASELINE_PLUS_EVT_LOGISTIC_CANDIDATE",
        "G05_G06_EXECUTION_CONTRACT", ("predictors", "outcomes", "support"),
        ("candidate_c", "training_history", "validation_history",
         "outer_heldout_history"), True, True, True),
    G07EvidenceRequirement(
        "G07E_SELECTED_PRIMARY", "SELECTED_PRIMARY_CONFIGURATION",
        "G06_SELECTED_C_RECONSTRUCTION", ("candidate_prediction_artifacts",),
        ("candidate_scores", "selected_hyperparameter", "tie_rule"),
        True, True, True),
    G07EvidenceRequirement(
        "G07E_RF", "RANDOM_FOREST_EXECUTION", "G05_G06_EXECUTION_CONTRACT",
        ("predictors", "outcomes", "support"),
        ("hyperparameters", "seed", "training_history", "heldout_history"),
        True, True, True),
    G07EvidenceRequirement(
        "G07E_GEOMETRY", "GEOMETRY_BENCHMARK", "G06_GEOMETRY_CONTRACT",
        ("four_geometry_fields", "outcomes", "baseline_selected_c"),
        ("inherited_c", "source_role", "training_history", "heldout_history"),
        True, True, True),
    G07EvidenceRequirement(
        "G07E_PREVALENCE", "TRAINING_PREVALENCE_BENCHMARK",
        "G06_PREVALENCE_CONTRACT", ("validated_training_outcomes",),
        ("training_rows", "training_positive", "probability", "heldout_history"),
        True, False, True),
    G07EvidenceRequirement(
        "G07E_SENSITIVITY", "GOVERNED_SENSITIVITY_EXECUTION",
        "G05_G06_EXECUTION_CONTRACT", ("family_specific_support", "outcomes"),
        ("analysis_id", "model_family", "model_role", "governed_disposition"),
        True, True, True),
    G07EvidenceRequirement(
        "G07E_CHECKPOINT", "CHECKPOINT_RESUME", "G06_CHECKPOINT_CONTRACT",
        ("checkpoint_bytes",),
        ("sequence", "resume_lineage", "hash", "terminal_state"),
        False, True, True),
    G07EvidenceRequirement(
        "G07E_TERMINAL", "TERMINAL_FAILURE", "G06_TERMINAL_CONTRACT",
        ("run_metadata",),
        ("terminal_status", "reason", "exception_reference"),
        False, False, True),
)


def governed_g07_evidence_requirements() -> tuple[G07EvidenceRequirement, ...]:
    return _G07_EVIDENCE_REQUIREMENTS


def recompute_prediction_metrics(
        artifact: IntegrityValidatedPredictionArtifact,
        outcomes: IntegrityValidatedOutcomeSet) -> Mapping[str, object]:
    outcomes = _revalidate_outcome_set(outcomes)
    artifact = _revalidate_prediction_handle(artifact, outcomes)
    if (artifact.evidence_classification != outcomes.evidence_classification or
            artifact.outcome_source_identity != outcomes.source_identity or
            artifact.outcome_key_identity != outcomes.canonical_key_interval_value_sha256):
        raise ContractError("ERR_G06_4E_METRIC_INPUT_BINDING")
    prediction = artifact.to_frame()
    outcome = outcomes.to_frame()
    keys = [*KEY_FIELDS, "interval_number"]
    paired = prediction.merge(outcome.loc[:, [*keys, "y"]], on=keys,
                              how="inner", validate="one_to_one")
    if len(paired) != len(prediction):
        raise ContractError("ERR_G06_4E_METRIC_PAIRING")
    return MappingProxyType(_evaluation.binary_scores(
        paired["y"].to_numpy(), paired["predicted_probability"].to_numpy()))


def postrun_reconstruction_policy() -> Mapping[str, object]:
    return MappingProxyType({
        "metrics": "RECOMPUTE_ALL_FROM_INTEGRITY_VALIDATED_PREDICTIONS",
        "selected_c": "RECONSTRUCT_FROM_ALL_CANDIDATE_PREDICTION_ARTIFACTS",
        "prevalence": "RECONSTRUCT_FROM_VALIDATED_TRAINING_OUTCOMES",
        "geometry": "RERUN_ALL_DETERMINISTIC_GEOMETRY_FITS",
        "logistic": "RERUN_ALL_DETERMINISTIC_LOGISTIC_CANDIDATE_FITS",
        "random_forest": (
            "RERUN_ALL_PRIMARY_CONFIRMATORY_SEED_CONFIGURATIONS_AND_"
            "PRESPECIFIED_REPRESENTATIVE_SENSITIVITY_PATHS;_EXPAND_ON_DISCREPANCY"
        ),
        "checkpoint_resume": (
            "RECONCILE_ACTUAL_LINEAGE_AND_RUN_ONE_BOUNDED_GOVERNED_"
            "INTERRUPTION_RESUME_EQUIVALENCE_EXERCISE"
        ),
    })


def _validate_production_facade() -> None:
    from src import paper1_g06_2_runtime as facade
    manifest = facade.PRODUCTION_API_MANIFEST
    if (manifest.get("implementation_module") != G06_4E_IMPLEMENTATION_MODULE or
            manifest.get("compatibility_gate") != G06_4E_GATE_VERSION or
            facade.validate_validation_generation is not validate_validation_generation):
        raise ContractError("ERR_G06_4E_PRODUCTION_FACADE")
    forbidden = {
        "authenticate_baseline_selected_c", "authenticate_benchmark_execution",
        "build_benchmark_authority_receipt", "validate_benchmark_authority_receipt",
        "publish_primary_selected_c_receipt", "authenticate_primary_selected_c_receipt",
        "write_benchmark_prediction_artifact", "authenticate_benchmark_prediction_artifact",
        "G07_EXECUTOR_AUTHORITY_PATH", "fit_probabilities",
    }
    if forbidden.intersection(facade.__all__):
        raise ContractError("ERR_G06_4E_REJECTED_AUTHORITY_EXPORTED")


def _validate_g06_4_weather_sources(
        root: Path, extension: Mapping[str, object]) -> tuple[object, ...]:
    validated = []
    for resolution in (1000, 2000):
        authority = _previous._realized_authority(extension, resolution)
        _previous._verify_file(
            root, authority.manifest_path, authority.manifest_sha256,
            "ERR_G06_4E_REALIZED_WEATHER_MANIFEST")
        _previous._verify_file(
            root, authority.relative_path, authority.expected_sha256,
            "ERR_G06_4E_REALIZED_WEATHER_SOURCE_HASH")
        columns = (*authority.key_fields, authority.interval_field, *authority.fields)
        frame = pd.read_parquet(root / authority.relative_path, columns=list(columns))
        if (tuple(frame.columns) != columns or len(frame) != authority.row_count or
                frame.loc[:, authority.key_fields].isna().any().any() or
                frame.loc[:, authority.key_fields].duplicated().any() or
                not frame["response_grid_m"].eq(authority.resolution_m).all()):
            raise ContractError("ERR_G06_4E_REALIZED_WEATHER_ROW_KEYS")
        values = frame.loc[:, authority.fields].apply(
            pd.to_numeric, errors="coerce").to_numpy(float)
        if not np.isfinite(values).all():
            raise ContractError("ERR_G06_4E_REALIZED_WEATHER_NONFINITE")
        if (_previous.key_sha256(frame) != authority.canonical_key_sha256 or
                _previous._frame_hash(frame, columns) !=
                authority.key_interval_value_sha256):
            raise ContractError("ERR_G06_4E_REALIZED_WEATHER_CONTENT")
        validated.append(authority)
    return tuple(validated)


def _validate_g06_4_boundary_source(
        root: Path, extension: Mapping[str, object]) -> Mapping[str, object]:
    authority = _previous._boundary_authority(extension)
    _previous._verify_file(
        root, authority.relative_path, authority.expected_sha256,
        "ERR_G06_4E_BOUNDARY_SOURCE_HASH")
    columns = (*authority.key_fields, authority.interval_field, *authority.flag_fields)
    frame = pd.read_parquet(root / authority.relative_path, columns=list(columns))
    if (tuple(frame.columns) != columns or len(frame) != authority.row_count or
            frame.loc[:, authority.key_fields].isna().any().any() or
            frame.loc[:, authority.key_fields].duplicated().any() or
            not frame["response_grid_m"].eq(authority.resolution_m).all()):
        raise ContractError("ERR_G06_4E_BOUNDARY_ROW_KEYS")
    for field in authority.flag_fields:
        if frame[field].isna().any() or not pd.api.types.is_bool_dtype(frame[field].dtype):
            raise ContractError("ERR_G06_4E_BOUNDARY_FLAG_DOMAIN")
    if (_previous.key_sha256(frame) != authority.canonical_key_sha256 or
            _previous._frame_hash(frame, columns) !=
            authority.key_interval_flag_sha256):
        raise ContractError("ERR_G06_4E_BOUNDARY_CONTENT")
    excluded = tuple(int(frame[field].sum()) for field in authority.flag_fields)
    retained = tuple(len(frame) - value for value in excluded)
    if retained != (2775, 2335):
        raise ContractError("ERR_G06_4E_BOUNDARY_RETAINED_COUNTS")
    return MappingProxyType({
        "authority": authority,
        "retained_counts": retained,
        "excluded_counts": excluded,
    })


def _regression_authority(root: Path) -> Mapping[str, object]:
    extension = _previous._load_authority(root)
    historical = _previous._validate_historical_g06_3a(
        root, root / "documentation", extension)
    _previous._validate_authority_sources(root, extension)
    universe = _previous._validate_execution_universe(root, extension)
    current_contracts = _previous.governed_execution_contracts(root)
    weather = tuple(
        contract for contract in current_contracts
        if contract.analysis_family == "REALIZED_WEATHER"
    )
    boundary = tuple(
        contract for contract in current_contracts
        if contract.analysis_family == "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY"
    )
    if len(weather) != 24:
        raise ContractError("ERR_G06_4E_REALIZED_WEATHER_CONTRACT_SET")
    if len(boundary) != 24:
        raise ContractError("ERR_G06_4E_BOUNDARY_CONTRACT_SET")
    weather_sources = _validate_g06_4_weather_sources(root, extension)
    boundary_artifact = _validate_g06_4_boundary_source(root, extension)
    benchmarks = _previous._build_benchmark_contracts(root)
    if (len(benchmarks) != 6 or
            {contract.benchmark_type for contract in benchmarks} !=
            {"TRAINING_PREVALENCE", "GEOMETRY_LOGISTIC"}):
        raise ContractError("ERR_G06_4E_BENCHMARK_CONTRACT_SET")
    return MappingProxyType({
        "historical": historical,
        "universe": universe,
        "weather_contract_count": len(weather),
        "weather_source_count": len(weather_sources),
        "boundary_contract_count": len(boundary),
        "benchmark_contract_count": len(benchmarks),
        "boundary_artifact": boundary_artifact,
    })


def current_generation_authority(project_root: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    authority = _load_authority(root)
    _validate_boundary_decision(root, authority)
    lifecycle = g06_4e_lifecycle_authority(root)
    regressions = _regression_authority(root)
    _validate_production_facade()
    return MappingProxyType({
        "gate_version": G06_4E_GATE_VERSION,
        "git_head": lifecycle["current_head"],
        "build_base_head": lifecycle["build_base_head"],
        "acceptance_state": lifecycle["acceptance_state"],
        "acceptance_commit": lifecycle["acceptance_commit"],
        "authority_boundary": "GOVERNED_CONTRACT_AND_ARTIFACT_INTEGRITY",
        "manifest_role": MANIFEST_ROLE,
        "manifest_is_authority_root": "NO",
        "g07_runner_status": CURRENT_G07_RUNNER_STATUS,
        "real_scientific_execution": CURRENT_SCIENTIFIC_EXECUTION_STATUS,
        "real_production_prediction_evidence": CURRENT_PRODUCTION_PREDICTION_EVIDENCE,
        "post_run_fidelity": CURRENT_POST_RUN_FIDELITY,
        "g05_execution_universe": dict(regressions["universe"]),
        "scientific_fitting_authorized": "NO",
    })


def validate_validation_generation(project_root: Path,
                                   directory: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    authority = _load_authority(root)
    _validate_boundary_decision(root, authority)
    lifecycle = g06_4e_lifecycle_authority(root)
    regressions = _regression_authority(root)
    geometry = tuple(governed_geometry_contract(root, evaluation)
                     for evaluation in OUTER_EVALUATIONS)
    evidence = governed_g07_evidence_requirements()
    policy = postrun_reconstruction_policy()
    _validate_production_facade()
    return MappingProxyType({
        "status": "PASS",
        "gate_version": G06_4E_GATE_VERSION,
        "acceptance_state": lifecycle["acceptance_state"],
        "acceptance_commit": lifecycle["acceptance_commit"],
        "build_base_head": lifecycle["build_base_head"],
        "historical_generation": regressions["historical"]["status"],
        "realized_weather_contract_count": regressions["weather_contract_count"],
        "boundary_filter_contract_count": regressions["boundary_contract_count"],
        "benchmark_contract_count": regressions["benchmark_contract_count"],
        "geometry_contract_count": len(geometry),
        "g07_evidence_requirement_count": len(evidence),
        "manifest_required_field_count": len(EXECUTION_MANIFEST_REQUIRED_FIELDS),
        "postrun_policy": dict(policy),
        "g05a_units": regressions["universe"]["g05a_units"],
        "g05b_units": regressions["universe"]["g05b_units"],
        "total_units": regressions["universe"]["total_units"],
        "g07_runner_status": CURRENT_G07_RUNNER_STATUS,
        "real_scientific_execution": CURRENT_SCIENTIFIC_EXECUTION_STATUS,
        "real_production_prediction_evidence": CURRENT_PRODUCTION_PREDICTION_EVIDENCE,
        "post_run_fidelity": CURRENT_POST_RUN_FIDELITY,
        "models_fit": "NO",
        "real_tuning_run": "NO",
        "real_predictions_generated": "NO",
        "real_performance_inspected": "NO",
    })


PRODUCTION_API_MANIFEST = MappingProxyType({
    "api_identity": API_IDENTITY,
    "production_import": G06_4E_PRODUCTION_FACADE,
    "implementation_module": G06_4E_IMPLEMENTATION_MODULE,
    "accepted_implementation_module": "src.paper1_g06_2g_runtime",
    "compatibility_gate": G06_4E_GATE_VERSION,
    "historical_compatibility_gate": "PAPER1_G06.4",
    "authority_boundary": "CONTRACT_AND_INTEGRITY_NOT_PROCESS_ORIGIN",
    "manifest_role": MANIFEST_ROLE,
    "legacy_policy": "G06_4A_THROUGH_G06_4C_REJECTED_ROUTES_NONEXPORTED_FAIL_CLOSED",
})
