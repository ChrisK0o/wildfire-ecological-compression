"""Authority-bound, prefit-only runtime contracts for Paper 1 G06.2d.

The module contains no estimator calls. Predictor authentication and outcome
authentication remain separate; outcomes enter only prediction validation and
metric eligibility after prediction bytes exist.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import importlib.metadata
import inspect
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd


GATE_VERSION = "PAPER1_G06.2d"
API_IDENTITY = "PAPER1_G06.2D_SINGLE_SECURE_PRODUCTION_API_V1"
EXECUTION_SCHEMA_VERSION = "PAPER1_G06.2D_EXECUTION_V1"
PREDICTION_SCHEMA_VERSION = "PAPER1_G06.2D_PREDICTION_V1"
PREDICTION_RECEIPT_SCHEMA_VERSION = "PAPER1_G06.2D_PREDICTION_RECEIPT_V1"
RUN_RECEIPT_SCHEMA_VERSION = "PAPER1_G06.2D_RUN_RECEIPT_V1"
CHECKPOINT_SCHEMA_VERSION = "PAPER1_G06.2D_CHECKPOINT_V1"
GENERATION_SCHEMA_VERSION = "PAPER1_G06.2D_VALIDATION_GENERATION_V1"
KEY_FIELDS = ("event_id", "interval_id", "response_grid_m", "cell_id")
OUTCOME_FIELDS = (*KEY_FIELDS, "interval_number", "y")
RF_SEEDS = (20200908, 20200909, 20200910, 20200911, 20200912)
RF_SD_CONVENTION = "POPULATION_SD_DDOF0_COMPLETE_GOVERNED_ENSEMBLE"
CHECKPOINT_STAGES = ("INITIALIZED", "TUNED", "SEED_PREDICTION_WRITTEN", "METRICS_WRITTEN", "FINALIZED")
OUTER_EVALUATIONS = MappingProxyType({
    "B1_TO_B2": ((1, 3, 4, 5), (6, 8, 9, 10)),
    "B1_B2_TO_B3": ((1, 3, 4, 5, 6, 8, 9, 10), (11, 12, 14, 15)),
    "B1_B2_B3_TO_B4": ((1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15), (16, 18, 21, 22)),
})
G05A_REGISTRY_SOURCE = "src/paper1_analysis_registry.py"
G05A_REGISTRY_SOURCE_SHA256 = "2a949da781f610d1c0c7c9dc0dc1832812b2c1b1ce54fa3e4fa41e78b90f5327"
G05B_REGISTRY_SOURCE = "documentation/PAPER1_G05B_SPECIALIZED_ANALYSIS_REGISTRY.csv"
G05B_REGISTRY_SOURCE_SHA256 = "f3f20f5f1b035d50ce3e9387d863f0bb41e64ac0a60dc80148c95af999f8c294"
METRIC_AUTHORITY_SOURCE = "documentation/PAPER1_G03_METRIC_OUTPUT_MATRIX.csv"
METRIC_AUTHORITY_SHA256 = "54c511fb1fe40c20c910936a125f0fc368e22063bdc12fc010312bd10c11359c"
UNCERTAINTY_AUTHORITY_SOURCE = "documentation/PAPER1_MODEL_UNCERTAINTY_SPEC.csv"
UNCERTAINTY_AUTHORITY_SHA256 = "5b0b0494e7e3635aba01aa7bb84cd2c20a6f04c235aaaf8307741e2b693572ca"
RF_AUTHORITY_SOURCE = "documentation/PAPER1_G06_2A_RF_SD_DECISION.csv"
RF_AUTHORITY_SHA256 = "4a63b1859707a047adc6d5ac0629fba7353d6df9d00ff26d785f01e3cac59732"


class ContractError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class ExecutionState(str, Enum):
    COMPLETE = "COMPLETE"
    PENDING = "PENDING_NOT_EXECUTED"
    ENVIRONMENT_BLOCKED = "ENVIRONMENT_BLOCKED"
    FAILED = "FAILED_RUNTIME"
    GOVERNED_NONESTIMABLE = "GOVERNED_NONESTIMABLE"
    MACHINE_DISABLED = "MACHINE_DISABLED_NONEXECUTING"


class TerminalReasonCode(str, Enum):
    NONE = "NONE"
    PENDING_NOT_EXECUTED = "PENDING_NOT_EXECUTED"
    RUNTIME_EXCEPTION = "RUNTIME_EXCEPTION"
    DISABLED_BY_FROZEN_REGISTRY = "DISABLED_BY_FROZEN_REGISTRY"
    BOUNDARY_1000_B1_ALL_NEGATIVE = "BOUNDARY_1000_B1_ALL_NEGATIVE"
    STATSMODELS_0_14_6_REQUIRED = "STATSMODELS_0_14_6_REQUIRED"


class MetricName(str, Enum):
    LOG_LOSS = "LOG_LOSS"
    BRIER_SCORE = "BRIER_SCORE"
    AVERAGE_PRECISION = "AVERAGE_PRECISION"
    ROC_AUC = "ROC_AUC"


class MetricRole(str, Enum):
    PRIMARY = "PRIMARY"
    CO_PRIMARY = "CO_PRIMARY"
    SECONDARY = "SECONDARY"


@dataclass(frozen=True)
class ArtifactAuthority:
    relative_path: str
    expected_sha256: str
    row_count: int
    canonical_key_sha256: str
    authority_manifest: str
    authority_manifest_sha256: str


@dataclass(frozen=True)
class OutcomeAuthority(ArtifactAuthority):
    risk_set_id: str
    resolution_m: int
    response_field: str
    response_domain: str
    key_interval_response_sha256: str
    schema_columns: tuple[str, ...] = OUTCOME_FIELDS


@dataclass(frozen=True)
class OutcomeRow:
    event_id: str
    interval_id: str
    response_grid_m: int
    cell_id: str
    interval_number: int
    response_y: int

    @property
    def key(self) -> tuple[object, ...]:
        return (self.event_id, self.interval_id, self.response_grid_m, self.cell_id)


@dataclass(frozen=True)
class AuthenticatedOutcomeArtifact:
    project_root: str
    authority: OutcomeAuthority
    observed_sha256: str
    observed_row_count: int
    observed_key_sha256: str
    observed_key_interval_response_sha256: str
    rows: tuple[OutcomeRow, ...]
    authentication_result: str = "PASS"


@dataclass(frozen=True)
class AuthenticatedPredictorArtifact:
    project_root: str
    authority: ArtifactAuthority
    risk_set_id: str
    resolution_m: int
    observed_sha256: str
    observed_row_count: int
    observed_key_sha256: str
    authentication_result: str = "PASS"


@dataclass(frozen=True)
class ExecutionContract:
    schema_version: str
    git_head: str
    analysis_id: str
    analysis_family: str
    comparator_identity: str
    model_family: str
    model_role: str
    risk_set_id: str
    resolution_m: int
    evaluation_identity: str
    training_intervals: tuple[int, ...]
    heldout_intervals: tuple[int, ...]
    predictor_path: str
    predictor_sha256: str
    predictor_key_sha256: str
    support_identity: str
    support_path: str
    support_sha256: str
    response_path: str
    response_sha256: str
    response_key_sha256: str
    response_key_interval_value_sha256: str
    preprocessing_identity: str
    tuning_identity: str
    governed_seeds: tuple[int, ...]
    metric_authority_sha256: str
    uncertainty_authority_sha256: str
    environment_requirement: str
    prediction_schema_version: str
    checkpoint_schema_version: str
    generation_schema_version: str
    registry_source: str
    registry_sha256: str
    execution_enabled: bool
    special_condition: str
    contract_sha256: str


@dataclass(frozen=True)
class RunContext:
    run_id: str
    generation_id: str
    git_head: str
    environment_identity: str
    execution_contract_sha256: str


PREDICTION_COLUMNS = (
    "schema_version", "run_id", "generation_id", "analysis_id", "outer_evaluation",
    "model_family", "model_role", "seed", "event_id", "interval_id", "response_grid_m",
    "cell_id", "interval_number", "heldout", "predicted_probability", "response_y",
)
PREDICTION_KEY = ("analysis_id", "outer_evaluation", "model_family", "model_role", "seed", *KEY_FIELDS)


@dataclass(frozen=True)
class PredictionArtifactReceipt:
    schema_version: str
    path: str
    artifact_sha256: str
    artifact_bytes: int
    row_count: int
    canonical_key_sha256: str
    outcome_key_interval_value_sha256: str
    run_id: str
    generation_id: str
    execution_contract_sha256: str
    analysis_id: str
    outer_evaluation: str
    model_family: str
    model_role: str
    seed: int
    resolution_m: int
    publication_state: str


@dataclass(frozen=True)
class AuthenticatedPredictionArtifact:
    project_root: str
    relative_path: str
    receipt: PredictionArtifactReceipt
    execution_contract: ExecutionContract
    run_context: RunContext
    authentication_result: str = "PASS"


@dataclass(frozen=True)
class TerminalEvidence:
    reason_code: TerminalReasonCode
    semantic_class: str
    authority_source: str
    analysis_id: str
    evaluation_identity: str
    evidence: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RunReceipt:
    schema_version: str
    gate_version: str
    run_id: str
    generation_id: str
    git_head: str
    execution_contract_sha256: str
    analysis_id: str
    model_family: str
    model_role: str
    evaluation_identity: str
    resolution_m: int
    predictor_path: str
    predictor_sha256: str
    predictor_key_sha256: str
    support_path: str
    support_sha256: str
    response_path: str
    response_sha256: str
    response_key_interval_value_sha256: str
    preprocessing_identity: str
    tuning_identity: str
    governed_seeds: tuple[int, ...]
    environment_identity: str
    prediction_path: str
    prediction_sha256: str
    execution_state: ExecutionState
    reason_code: TerminalReasonCode
    reason_authority: str
    no_predictions_fabricated: bool


@dataclass(frozen=True)
class CheckpointReceipt:
    schema_version: str
    run_id: str
    generation_id: str
    git_head: str
    execution_contract_sha256: str
    analysis_id: str
    model_family: str
    model_role: str
    resolution_m: int
    evaluation_identity: str
    training_intervals: tuple[int, ...]
    heldout_intervals: tuple[int, ...]
    predictor_sha256: str
    support_sha256: str
    response_sha256: str
    response_key_interval_value_sha256: str
    preprocessing_identity: str
    tuning_identity: str
    environment_identity: str
    seed: int
    stage: str
    payload_sha256: str
    payload_bytes: int
    prior_prediction_sha256s: tuple[str, ...]
    completion_state: ExecutionState


@dataclass(frozen=True)
class MetricAuthority:
    name: MetricName
    role: MetricRole
    single_class_defined: bool
    undefined_reason: str
    include_when_defined: bool
    value_minimum: float
    value_maximum: float | None


@dataclass(frozen=True)
class MetricRecord:
    metric_name: MetricName
    metric_role: MetricRole
    analysis_id: str
    model_family: str
    model_role: str
    evaluation_identity: str
    row_universe_sha256: str
    row_count: int
    class_count: int
    eligibility_status: str
    value: float | None
    reason_code: str
    include_in_aggregate: bool


@dataclass(frozen=True)
class AuthenticatedMetricUniverse:
    analysis_id: str
    evaluation_identity: str
    row_count: int
    positive_count: int
    negative_count: int
    row_universe_sha256: str
    authority_source: str


@dataclass(frozen=True)
class RFSeedMetricRecord:
    prediction: AuthenticatedPredictionArtifact
    metric: MetricRecord


@dataclass(frozen=True)
class RFStabilitySummary:
    analysis_id: str
    model_role: str
    evaluation_identity: str
    metric_name: MetricName
    seed_artifact_sha256s: tuple[tuple[int, str], ...]
    raw_per_seed_values: tuple[tuple[int, float], ...] | None
    mean: float | None
    minimum: float | None
    maximum: float | None
    range: float | None
    population_sd: float | None
    denominator: int
    ddof: int
    convention: str
    defined_status: str
    undefined_reason: str


METRIC_AUTHORITIES = MappingProxyType({
    MetricName.LOG_LOSS: MetricAuthority(MetricName.LOG_LOSS, MetricRole.PRIMARY, True, "", True, 0.0, None),
    MetricName.BRIER_SCORE: MetricAuthority(MetricName.BRIER_SCORE, MetricRole.CO_PRIMARY, True, "", True, 0.0, 1.0),
    MetricName.AVERAGE_PRECISION: MetricAuthority(MetricName.AVERAGE_PRECISION, MetricRole.SECONDARY, False, "HELDOUT_UNIT_SINGLE_CLASS", True, 0.0, 1.0),
    MetricName.ROC_AUC: MetricAuthority(MetricName.ROC_AUC, MetricRole.SECONDARY, False, "HELDOUT_UNIT_SINGLE_CLASS", True, 0.0, 1.0),
})


@dataclass(frozen=True)
class GenerationAuthority:
    schema_version: str
    manifest_name: str
    required_payloads: tuple[str, ...]
    required_blocker_tests: tuple[str, ...]


G06_2C_GENERATION_AUTHORITY = GenerationAuthority(
    GENERATION_SCHEMA_VERSION,
    "PAPER1_G06_2C_GENERATION_MANIFEST.json",
    (
        "PAPER1_G06_2C_CORRECTION.md",
        "PAPER1_G06_2C_OUTCOME_AUTHENTICATION_QC.csv",
        "PAPER1_G06_2C_RECEIPT_AUTHORITY_QC.csv",
        "PAPER1_G06_2C_EXECUTION_STATE_REASON_QC.csv",
        "PAPER1_G06_2C_CHECKPOINT_QC.csv",
        "PAPER1_G06_2C_RF_ARTIFACT_AUTH_QC.csv",
        "PAPER1_G06_2C_METRIC_AUTHORITY_QC.csv",
        "PAPER1_G06_2C_GENERATION_QC.csv",
        "PAPER1_G06_2C_TEST_EXECUTION.csv",
        "PAPER1_G06_2C_DECISION.csv",
    ),
    tuple(f"SOLG062-{number:03d}" for number in range(1, 11)),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(Path(temporary).read_bytes()).digest() != hashlib.sha256(content).digest():
            raise ContractError("ERR_TEMPORARY_HASH")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _canonical_key_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if any(field not in frame for field in KEY_FIELDS):
        raise ContractError("ERR_KEY_COLUMNS_MISSING")
    keys = frame.loc[:, KEY_FIELDS]
    if keys.isna().any().any():
        raise ContractError("ERR_KEY_NULL")
    if keys.duplicated().any():
        raise ContractError("ERR_KEY_DUPLICATE")
    return keys.sort_values(list(KEY_FIELDS), kind="stable").reset_index(drop=True)


def _frame_hash(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    ordered = frame.loc[:, columns].sort_values(list(KEY_FIELDS), kind="stable").reset_index(drop=True)
    return hashlib.sha256(ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")).hexdigest()


def _contract_hash(values: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(values)).hexdigest()


_PR31_MANIFEST = "data/processed/propagation/paper1/pr31_labeled_tables/pr31_manifest.json"
_PR31_MANIFEST_SHA = "4165338edd0a04c53941dd37ee579c72b85d967d5769abbc3283abf49fe36ab9"
_PR32B_MANIFEST = "data/processed/propagation/paper1/pr32b_alt_riskset_labeled/pr32b_manifest.json"
_PR32B_MANIFEST_SHA = "86bf676308fad4b5ac1e0e752a148cd04dba138282225a0a809b91dddbf5a282"


OUTCOME_AUTHORITIES = MappingProxyType({
    ("PRIMARY_HYBRID", 1000): OutcomeAuthority(
        "data/processed/propagation/paper1/pr31_labeled_tables/outputs/paper1_pr31_labeled_table_1km.parquet",
        "923b069feb1f89857ae53e35ce3d04e7d167d49d6c2da77370130a6c44092567", 3317,
        "dbfbb3cae3a0b0d3bfebfe6718820d3cd3e228136cc115a1a79a5b46c54eaceb",
        _PR31_MANIFEST, _PR31_MANIFEST_SHA, "PRIMARY_HYBRID", 1000, "y", "BINARY_0_1",
        "43d686c734d7700f049cbe01c99a588fbfa4941aed4f444018889453162a6c74",
    ),
    ("PRIMARY_HYBRID", 2000): OutcomeAuthority(
        "data/processed/propagation/paper1/pr31_labeled_tables/outputs/paper1_pr31_labeled_table_2km.parquet",
        "bfb3cfb0ee251e478d3530d61593a68dee0d6d150fdcf8ee3b0209a6d60119aa", 836,
        "f8d587401c7fd9604efe5d8025ddf57be222942db1419defc0b90ddf47e9d24c",
        _PR31_MANIFEST, _PR31_MANIFEST_SHA, "PRIMARY_HYBRID", 2000, "y", "BINARY_0_1",
        "03d828d2e69f567212b3500831e4a2e5e18393d28caddbfeaf3615c4d3a227df",
    ),
    ("ACTIVE_FRONT_ONLY_5KM", 1000): OutcomeAuthority(
        "data/processed/propagation/paper1/pr32b_alt_riskset_labeled/ACTIVE_FRONT_ONLY_5KM/outputs/paper1_pr32b_labeled_active_front_only_5km_1km.parquet",
        "0f3ec098b8fc4f469ee32de5682830209b84188468e8d18c884edb3697e65f03", 2867,
        "c29dad4c374ff002345710570197d3e5cc2971bbd544341c88a0bf341c0e3488",
        _PR32B_MANIFEST, _PR32B_MANIFEST_SHA, "ACTIVE_FRONT_ONLY_5KM", 1000, "y", "BINARY_0_1",
        "c3e3a4d018607eef9344e784984f1c3c31ea0d15df75695e403857dd8216a690",
    ),
    ("ACTIVE_FRONT_ONLY_5KM", 2000): OutcomeAuthority(
        "data/processed/propagation/paper1/pr32b_alt_riskset_labeled/ACTIVE_FRONT_ONLY_5KM/outputs/paper1_pr32b_labeled_active_front_only_5km_2km.parquet",
        "ce5bba5dde6d881f17423c9d18fe6ed4595f9dd810054649f1d6e84a97ebd174", 730,
        "b7d880e55e87127357bcd07ae881bd7bb23b7462e5d2f1627b8cddc433ba7f5f",
        _PR32B_MANIFEST, _PR32B_MANIFEST_SHA, "ACTIVE_FRONT_ONLY_5KM", 2000, "y", "BINARY_0_1",
        "2252c2be5b2cb95207bc332cfaedfd747b75d412206482d539c4431089e67de6",
    ),
    ("PERIMETER_ONLY_2KM", 1000): OutcomeAuthority(
        "data/processed/propagation/paper1/pr32b_alt_riskset_labeled/PERIMETER_ONLY_2KM/outputs/paper1_pr32b_labeled_perimeter_only_2km_1km.parquet",
        "8d649905ec424afc617ae875f6f718f4e26b8b4cb31ba497470478ad2fcbd9b2", 1539,
        "75705abbbc69f7ba1ce3393d0fda7ab8ebf4333e90b84450681fb64786a2d14d",
        _PR32B_MANIFEST, _PR32B_MANIFEST_SHA, "PERIMETER_ONLY_2KM", 1000, "y", "BINARY_0_1",
        "17be5ad50ed5e9c92c95f813d97e37acdc2bdd4239944754687c176790aaff6d",
    ),
    ("PERIMETER_ONLY_2KM", 2000): OutcomeAuthority(
        "data/processed/propagation/paper1/pr32b_alt_riskset_labeled/PERIMETER_ONLY_2KM/outputs/paper1_pr32b_labeled_perimeter_only_2km_2km.parquet",
        "ef2b4f3a44ce242cae011cf3477707a50819129532029840ccb2f52f562d1dcf", 386,
        "ddee921486e355b0ccbed7852c54651e82c40ae0c3d248c26a3ab2ef4cdfda5c",
        _PR32B_MANIFEST, _PR32B_MANIFEST_SHA, "PERIMETER_ONLY_2KM", 2000, "y", "BINARY_0_1",
        "e24153e7006cb93f78a4c6b41e138bd6423d57faa7f99b3ca09335861c63a709",
    ),
    ("PERIMETER_ONLY_5KM", 1000): OutcomeAuthority(
        "data/processed/propagation/paper1/pr32b_alt_riskset_labeled/PERIMETER_ONLY_5KM/outputs/paper1_pr32b_labeled_perimeter_only_5km_1km.parquet",
        "f4ea45fef85754cb080a9f2df458a533476de701f97e9c16371c64333b8fa808", 4472,
        "46feac73c1501fa245a39bbb88c264bc0294c346c3112f34ffc9f8a9ba42dbb1",
        _PR32B_MANIFEST, _PR32B_MANIFEST_SHA, "PERIMETER_ONLY_5KM", 1000, "y", "BINARY_0_1",
        "cdd0a7067b11773d666cf15f98801b0838477440d76fc5e15176dc423a7124b4",
    ),
    ("PERIMETER_ONLY_5KM", 2000): OutcomeAuthority(
        "data/processed/propagation/paper1/pr32b_alt_riskset_labeled/PERIMETER_ONLY_5KM/outputs/paper1_pr32b_labeled_perimeter_only_5km_2km.parquet",
        "04ed5244c8a442594fa0bfe3298011d4091b4fd3f8d251e309aa15f33eefba64", 1139,
        "d27bc4f529f9d82bd565c2f26febdfe608d4a01ff7c24fbbbeb9db4bd7e30958",
        _PR32B_MANIFEST, _PR32B_MANIFEST_SHA, "PERIMETER_ONLY_5KM", 2000, "y", "BINARY_0_1",
        "79e24e0ab57ca7dbc5a229857e12bf163d2d042fa8aa2e9abbab888fbe2d8b23",
    ),
})


_PR23_MANIFEST = "data/processed/propagation/paper1/pr23_response_free_predictors/pr23_manifest.json"
_PR23_MANIFEST_SHA = "366a40de95c238c3066ab38955df44d9397b4e4cbaa1654c8be655d02d973d92"
_PR24_MANIFEST = "data/processed/propagation/paper1/pr24_response_free_support/pr24_manifest.json"
_PR24_MANIFEST_SHA = "60b56adb20fb4fe2264c74be09c9bd04b6fbab0adfce77119dcce9e9b62fdf52"
_PR32A_MANIFEST = "data/processed/propagation/paper1/pr32a_alt_riskset_response_free/support/pr32a_manifest.json"
_PR32A_MANIFEST_SHA = "7305ccdbf2426164ba0c5c061cdee65ea802a202a8939d539b2d66d9ac6a6f11"


PREDICTOR_AUTHORITIES = MappingProxyType({
    ("PRIMARY_HYBRID", 1000): ArtifactAuthority(
        "data/processed/propagation/paper1/pr23_response_free_predictors/outputs/paper1_pr23_response_free_predictors_1km.parquet",
        "46c7c1cf208dace65a9c19e3f4b490fe9fa0592ad832856f44412556a0b5d2a5", 3317,
        "dbfbb3cae3a0b0d3bfebfe6718820d3cd3e228136cc115a1a79a5b46c54eaceb", _PR23_MANIFEST, _PR23_MANIFEST_SHA),
    ("PRIMARY_HYBRID", 2000): ArtifactAuthority(
        "data/processed/propagation/paper1/pr23_response_free_predictors/outputs/paper1_pr23_response_free_predictors_2km.parquet",
        "f33d54d8158290feb4bb6a760812e5f6cedf357f6d128333ca601d1ab15e6626", 836,
        "f8d587401c7fd9604efe5d8025ddf57be222942db1419defc0b90ddf47e9d24c", _PR23_MANIFEST, _PR23_MANIFEST_SHA),
    ("ACTIVE_FRONT_ONLY_5KM", 1000): ArtifactAuthority(
        "data/processed/propagation/paper1/pr32a_alt_riskset_response_free/ACTIVE_FRONT_ONLY_5KM/outputs/paper1_pr32a_part1_active_front_only_5km_1km.parquet",
        "2efc2075c7c645865ad592b0c26b1efcd7aa3ae9dab8a4a7ad86e370e1ffe9b7", 2867,
        "c29dad4c374ff002345710570197d3e5cc2971bbd544341c88a0bf341c0e3488", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("ACTIVE_FRONT_ONLY_5KM", 2000): ArtifactAuthority(
        "data/processed/propagation/paper1/pr32a_alt_riskset_response_free/ACTIVE_FRONT_ONLY_5KM/outputs/paper1_pr32a_part1_active_front_only_5km_2km.parquet",
        "f711c8177c6e670929f2414321ffb36da427e49b713f809d9e8f9f0227f790f2", 730,
        "b7d880e55e87127357bcd07ae881bd7bb23b7462e5d2f1627b8cddc433ba7f5f", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("PERIMETER_ONLY_2KM", 1000): ArtifactAuthority(
        "data/processed/propagation/paper1/pr32a_alt_riskset_response_free/PERIMETER_ONLY_2KM/outputs/paper1_pr32a_part1_perimeter_only_2km_1km.parquet",
        "43a53229b29f8cad3c176417a7f67fad5a2fa2596d726f4acb243bad958e4ed8", 1539,
        "75705abbbc69f7ba1ce3393d0fda7ab8ebf4333e90b84450681fb64786a2d14d", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("PERIMETER_ONLY_2KM", 2000): ArtifactAuthority(
        "data/processed/propagation/paper1/pr32a_alt_riskset_response_free/PERIMETER_ONLY_2KM/outputs/paper1_pr32a_part1_perimeter_only_2km_2km.parquet",
        "7adc8bedde2c0a63b821a83c44c744f30e6410d6710a619a8ab339d6b2655f5e", 386,
        "ddee921486e355b0ccbed7852c54651e82c40ae0c3d248c26a3ab2ef4cdfda5c", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("PERIMETER_ONLY_5KM", 1000): ArtifactAuthority(
        "data/processed/propagation/paper1/pr32a_alt_riskset_response_free/PERIMETER_ONLY_5KM/outputs/paper1_pr32a_part1_perimeter_only_5km_1km.parquet",
        "b59fe2ed3875a2c20da3cedb00a742de14379c7fee4a74999a4095b59248539e", 4472,
        "46feac73c1501fa245a39bbb88c264bc0294c346c3112f34ffc9f8a9ba42dbb1", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("PERIMETER_ONLY_5KM", 2000): ArtifactAuthority(
        "data/processed/propagation/paper1/pr32a_alt_riskset_response_free/PERIMETER_ONLY_5KM/outputs/paper1_pr32a_part1_perimeter_only_5km_2km.parquet",
        "f2ab9151043a5fed700e54b79c9bbf4fcae7960e342252136d1a826948c85242", 1139,
        "d27bc4f529f9d82bd565c2f26febdfe608d4a01ff7c24fbbbeb9db4bd7e30958", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
})


SUPPORT_AUTHORITIES = MappingProxyType({
    ("PRIMARY_HYBRID", 1000): ("data/processed/propagation/paper1/pr24_response_free_support/outputs/paper1_pr24_support_masks_1km.parquet", "a79d424f8bcb4003f8d6c6a91eee640213b23d278e1ec8d08cf0f757b7be66dc", _PR24_MANIFEST, _PR24_MANIFEST_SHA),
    ("PRIMARY_HYBRID", 2000): ("data/processed/propagation/paper1/pr24_response_free_support/outputs/paper1_pr24_support_masks_2km.parquet", "3572b3129b367d231df0df112e96f32a89933541e3f3a87ea4fe02831cc6fef1", _PR24_MANIFEST, _PR24_MANIFEST_SHA),
    ("ACTIVE_FRONT_ONLY_5KM", 1000): ("data/processed/propagation/paper1/pr32a_alt_riskset_response_free/support/ACTIVE_FRONT_ONLY_5KM/outputs/paper1_pr32a_support_masks_active_front_only_5km_1km.parquet", "a30ba105a1982cde67557647ce3f48ca4f560e0376f225ca116b4d35be21d0b2", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("ACTIVE_FRONT_ONLY_5KM", 2000): ("data/processed/propagation/paper1/pr32a_alt_riskset_response_free/support/ACTIVE_FRONT_ONLY_5KM/outputs/paper1_pr32a_support_masks_active_front_only_5km_2km.parquet", "4157165335746349ea54827547068f308acb1ebbc4f54f7153f56d0bafeafc88", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("PERIMETER_ONLY_2KM", 1000): ("data/processed/propagation/paper1/pr32a_alt_riskset_response_free/support/PERIMETER_ONLY_2KM/outputs/paper1_pr32a_support_masks_perimeter_only_2km_1km.parquet", "bf4bba90c126f72583ff0828ad6ff61a6d9cb672e9f0212a53ad2e90fb2506f6", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("PERIMETER_ONLY_2KM", 2000): ("data/processed/propagation/paper1/pr32a_alt_riskset_response_free/support/PERIMETER_ONLY_2KM/outputs/paper1_pr32a_support_masks_perimeter_only_2km_2km.parquet", "d5a401e323b767e5954ec657a5a2c02a3fd8b3a826adb1901d19d165a4e0d0d7", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("PERIMETER_ONLY_5KM", 1000): ("data/processed/propagation/paper1/pr32a_alt_riskset_response_free/support/PERIMETER_ONLY_5KM/outputs/paper1_pr32a_support_masks_perimeter_only_5km_1km.parquet", "2ee8012b99bcd77216363b89eef66655ba50cb1853b359840d721087ded47bc7", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
    ("PERIMETER_ONLY_5KM", 2000): ("data/processed/propagation/paper1/pr32a_alt_riskset_response_free/support/PERIMETER_ONLY_5KM/outputs/paper1_pr32a_support_masks_perimeter_only_5km_2km.parquet", "b121af770940eafae938362a56236f7633b581a5810bd5309b3807590f636ec5", _PR32A_MANIFEST, _PR32A_MANIFEST_SHA),
})


def _verify_authority_file(root: Path, relative_path: str, expected_sha256: str, error: str) -> Path:
    path = (root / relative_path).resolve()
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ContractError(error)
    return path


def authenticate_outcome_artifact(project_root: Path, risk_set_id: str, resolution_m: int,
                                  supplied_path: Path | None = None) -> AuthenticatedOutcomeArtifact:
    root = Path(project_root).resolve()
    authority = OUTCOME_AUTHORITIES.get((risk_set_id, int(resolution_m)))
    if authority is None:
        raise ContractError("ERR_OUTCOME_AUTHORITY")
    governed = (root / authority.relative_path).resolve()
    if supplied_path is not None and Path(supplied_path).resolve() != governed:
        raise ContractError("ERR_CALLER_OUTCOME_SUBSTITUTION")
    _verify_authority_file(root, authority.authority_manifest, authority.authority_manifest_sha256,
                           "ERR_OUTCOME_AUTHORITY_MANIFEST")
    _verify_authority_file(root, authority.relative_path, authority.expected_sha256, "ERR_OUTCOME_FILE_HASH")
    frame = pd.read_parquet(governed, columns=list(OUTCOME_FIELDS))
    if tuple(frame.columns) != OUTCOME_FIELDS:
        raise ContractError("ERR_OUTCOME_SCHEMA")
    if len(frame) != authority.row_count:
        raise ContractError("ERR_OUTCOME_ROW_COUNT")
    if not frame["response_grid_m"].eq(authority.resolution_m).all():
        raise ContractError("ERR_OUTCOME_RESOLUTION")
    if not frame["y"].isin([0, 1]).all():
        raise ContractError("ERR_OUTCOME_DOMAIN")
    key_hash = _frame_hash(frame, KEY_FIELDS)
    map_hash = _frame_hash(frame, OUTCOME_FIELDS)
    if key_hash != authority.canonical_key_sha256:
        raise ContractError("ERR_OUTCOME_KEY_HASH")
    if map_hash != authority.key_interval_response_sha256:
        raise ContractError("ERR_OUTCOME_KEY_INTERVAL_VALUE_HASH")
    ordered = frame.sort_values(list(KEY_FIELDS), kind="stable")
    rows = tuple(OutcomeRow(str(row.event_id), str(row.interval_id), int(row.response_grid_m),
                            str(row.cell_id), int(row.interval_number), int(row.y))
                 for row in ordered.itertuples(index=False))
    return AuthenticatedOutcomeArtifact(
        str(root), authority, sha256_file(governed), len(frame), key_hash, map_hash, rows,
    )


def authenticate_predictor_artifact(project_root: Path, risk_set_id: str, resolution_m: int,
                                    supplied_path: Path | None = None) -> AuthenticatedPredictorArtifact:
    root = Path(project_root).resolve()
    authority = PREDICTOR_AUTHORITIES.get((risk_set_id, int(resolution_m)))
    if authority is None:
        raise ContractError("ERR_PREDICTOR_AUTHORITY")
    governed = (root / authority.relative_path).resolve()
    if supplied_path is not None and Path(supplied_path).resolve() != governed:
        raise ContractError("ERR_CALLER_PREDICTOR_SUBSTITUTION")
    _verify_authority_file(root, authority.authority_manifest, authority.authority_manifest_sha256,
                           "ERR_PREDICTOR_AUTHORITY_MANIFEST")
    _verify_authority_file(root, authority.relative_path, authority.expected_sha256, "ERR_PREDICTOR_FILE_HASH")
    frame = pd.read_parquet(governed, columns=list(KEY_FIELDS))
    key_hash = _frame_hash(frame, KEY_FIELDS)
    if len(frame) != authority.row_count:
        raise ContractError("ERR_PREDICTOR_ROW_COUNT")
    if key_hash != authority.canonical_key_sha256:
        raise ContractError("ERR_PREDICTOR_KEY_HASH")
    return AuthenticatedPredictorArtifact(str(root), authority, risk_set_id, int(resolution_m),
                                          sha256_file(governed), len(frame), key_hash)


def _verify_handle(handle: AuthenticatedOutcomeArtifact) -> AuthenticatedOutcomeArtifact:
    if not isinstance(handle, AuthenticatedOutcomeArtifact) or handle.authentication_result != "PASS":
        raise ContractError("ERR_OUTCOME_HANDLE_TYPE")
    refreshed = authenticate_outcome_artifact(
        Path(handle.project_root), handle.authority.risk_set_id, handle.authority.resolution_m,
        Path(handle.project_root) / handle.authority.relative_path,
    )
    if refreshed != handle:
        raise ContractError("ERR_OUTCOME_HANDLE_BINDING")
    return refreshed


def _verify_predictor_handle(handle: AuthenticatedPredictorArtifact) -> AuthenticatedPredictorArtifact:
    if not isinstance(handle, AuthenticatedPredictorArtifact) or handle.authentication_result != "PASS":
        raise ContractError("ERR_PREDICTOR_HANDLE_TYPE")
    refreshed = authenticate_predictor_artifact(
        Path(handle.project_root), handle.risk_set_id, handle.resolution_m,
        Path(handle.project_root) / handle.authority.relative_path,
    )
    if refreshed != handle:
        raise ContractError("ERR_PREDICTOR_HANDLE_BINDING")
    return refreshed


def _contract_payload(values: Mapping[str, object]) -> dict[str, object]:
    payload = dict(values)
    payload.pop("contract_sha256", None)
    return payload


def governed_execution_contract(project_root: Path, analysis_id: str, model_family: str,
                                model_role: str, evaluation_identity: str) -> ExecutionContract:
    root = Path(project_root).resolve()
    if analysis_id.startswith("G05A_DISABLED_"):
        return _governed_disabled_contract(root, analysis_id, model_family, model_role, evaluation_identity)
    if analysis_id.startswith("G05B_"):
        return _governed_g05b_contract(root, analysis_id, model_family, model_role, evaluation_identity)
    if model_family not in {"L2_LOGISTIC", "RANDOM_FOREST"}:
        raise ContractError("ERR_CONTRACT_MODEL_FAMILY")
    if model_role not in {"baseline", "augmented"}:
        raise ContractError("ERR_CONTRACT_MODEL_ROLE")
    if evaluation_identity not in OUTER_EVALUATIONS:
        raise ContractError("ERR_CONTRACT_EVALUATION")
    _verify_authority_file(root, G05A_REGISTRY_SOURCE, G05A_REGISTRY_SOURCE_SHA256,
                           "ERR_G05A_REGISTRY_AUTHORITY")
    from src import paper1_analysis_registry as registry

    candidates = [item for item in registry.registry(root) if item.analysis_id == analysis_id]
    if len(candidates) != 1 or not candidates[0].executable_status.startswith("EXECUTABLE"):
        raise ContractError("ERR_CONTRACT_ANALYSIS")
    analysis = candidates[0]
    risk = str(analysis.risk_set_id)
    resolution = int(analysis.resolution_m)
    predictor = PREDICTOR_AUTHORITIES[(risk, resolution)]
    outcome = OUTCOME_AUTHORITIES[(risk, resolution)]
    support_path, support_hash, support_manifest, support_manifest_hash = SUPPORT_AUTHORITIES[(risk, resolution)]
    _verify_authority_file(root, support_manifest, support_manifest_hash, "ERR_SUPPORT_AUTHORITY_MANIFEST")
    _verify_authority_file(root, support_path, support_hash, "ERR_SUPPORT_FILE_HASH")
    training, heldout = OUTER_EVALUATIONS[evaluation_identity]
    if analysis.interval_universe == "NO_EARLY":
        allowed = set(registry.NO_EARLY)
        training = tuple(value for value in training if value in allowed)
        heldout = tuple(value for value in heldout if value in allowed)
    comparator = registry.comparator_contract(analysis)["comparator_type"]
    values = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "git_head": _git_head(root),
        "analysis_id": analysis.analysis_id,
        "analysis_family": analysis.family,
        "comparator_identity": str(comparator),
        "model_family": model_family,
        "model_role": model_role,
        "risk_set_id": risk,
        "resolution_m": resolution,
        "evaluation_identity": evaluation_identity,
        "training_intervals": tuple(training),
        "heldout_intervals": tuple(heldout),
        "predictor_path": predictor.relative_path,
        "predictor_sha256": predictor.expected_sha256,
        "predictor_key_sha256": predictor.canonical_key_sha256,
        "support_identity": str(analysis.support_universe),
        "support_path": support_path,
        "support_sha256": support_hash,
        "response_path": outcome.relative_path,
        "response_sha256": outcome.expected_sha256,
        "response_key_sha256": outcome.canonical_key_sha256,
        "response_key_interval_value_sha256": outcome.key_interval_response_sha256,
        "preprocessing_identity": analysis.logistic_handling if model_family == "L2_LOGISTIC" else analysis.rf_handling,
        "tuning_identity": analysis.tuning_inheritance,
        "governed_seeds": () if model_family == "L2_LOGISTIC" else RF_SEEDS,
        "metric_authority_sha256": METRIC_AUTHORITY_SHA256,
        "uncertainty_authority_sha256": UNCERTAINTY_AUTHORITY_SHA256,
        "environment_requirement": "WILDFIRE_LOCKED_ENVIRONMENT",
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "generation_schema_version": GENERATION_SCHEMA_VERSION,
        "registry_source": G05A_REGISTRY_SOURCE,
        "registry_sha256": G05A_REGISTRY_SOURCE_SHA256,
        "execution_enabled": True,
        "special_condition": "NONE",
    }
    return ExecutionContract(**values, contract_sha256=_contract_hash(values))


def _governed_disabled_contract(root: Path, analysis_id: str, model_family: str,
                                model_role: str, evaluation_identity: str) -> ExecutionContract:
    if (model_family, model_role, evaluation_identity) != ("DISABLED", "nonexecuting", "NOT_APPLICABLE"):
        raise ContractError("ERR_DISABLED_CONTRACT_IDENTITY")
    _verify_authority_file(root, G05A_REGISTRY_SOURCE, G05A_REGISTRY_SOURCE_SHA256,
                           "ERR_G05A_REGISTRY_AUTHORITY")
    from src import paper1_analysis_registry as registry
    matches = [item for item in registry.registry(root) if item.analysis_id == analysis_id]
    if len(matches) != 1 or matches[0].executable_status.startswith("EXECUTABLE"):
        raise ContractError("ERR_CONTRACT_ANALYSIS")
    analysis = matches[0]
    values = {
        "schema_version": EXECUTION_SCHEMA_VERSION, "git_head": _git_head(root),
        "analysis_id": analysis_id, "analysis_family": analysis.family,
        "comparator_identity": "DISABLED_NONEXECUTING", "model_family": model_family,
        "model_role": model_role, "risk_set_id": "NOT_APPLICABLE", "resolution_m": 0,
        "evaluation_identity": evaluation_identity, "training_intervals": (), "heldout_intervals": (),
        "predictor_path": "", "predictor_sha256": "", "predictor_key_sha256": "",
        "support_identity": "NOT_APPLICABLE", "support_path": "", "support_sha256": "",
        "response_path": "", "response_sha256": "", "response_key_sha256": "",
        "response_key_interval_value_sha256": "", "preprocessing_identity": "NOT_APPLICABLE",
        "tuning_identity": "NOT_APPLICABLE", "governed_seeds": (),
        "metric_authority_sha256": METRIC_AUTHORITY_SHA256,
        "uncertainty_authority_sha256": UNCERTAINTY_AUTHORITY_SHA256,
        "environment_requirement": "NOT_APPLICABLE",
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "generation_schema_version": GENERATION_SCHEMA_VERSION,
        "registry_source": G05A_REGISTRY_SOURCE, "registry_sha256": G05A_REGISTRY_SOURCE_SHA256,
        "execution_enabled": False, "special_condition": analysis.executable_status,
    }
    return ExecutionContract(**values, contract_sha256=_contract_hash(values))


def _governed_g05b_contract(root: Path, analysis_id: str, model_family: str,
                            model_role: str, evaluation_identity: str) -> ExecutionContract:
    _verify_authority_file(root, G05B_REGISTRY_SOURCE, G05B_REGISTRY_SOURCE_SHA256,
                           "ERR_G05B_REGISTRY_AUTHORITY")
    registry = pd.read_csv(root / G05B_REGISTRY_SOURCE)
    matches = registry.loc[registry["analysis_id"].eq(analysis_id)]
    if len(matches) != 1 or not str(matches.iloc[0]["executable_status"]).startswith("EXECUTABLE"):
        raise ContractError("ERR_CONTRACT_ANALYSIS")
    row = matches.iloc[0]
    if evaluation_identity != str(row["fold_or_threshold"]):
        raise ContractError("ERR_CONTRACT_EVALUATION")
    if analysis_id == "G05B_LOIO_PRIMARY_FORWARD":
        allowed = {("DIAGNOSTIC_NO_REFIT", "paired_delta")}
    elif analysis_id == "G05B_FRACTIONAL_RESPONSE":
        allowed = {("FRACTIONAL_LOGIT_GLM", "baseline"), ("FRACTIONAL_LOGIT_GLM", "augmented")}
    else:
        allowed = {(family, role) for family in ("L2_LOGISTIC", "RANDOM_FOREST")
                   for role in ("baseline", "augmented")}
    if (model_family, model_role) not in allowed:
        raise ContractError("ERR_CONTRACT_MODEL_ROLE")
    predictor = PREDICTOR_AUTHORITIES[("PRIMARY_HYBRID", 1000)]
    outcome = OUTCOME_AUTHORITIES[("PRIMARY_HYBRID", 1000)]
    response_path = outcome.relative_path
    response_sha = outcome.expected_sha256
    response_map_sha = outcome.key_interval_response_sha256
    if analysis_id == "G05B_FRACTIONAL_RESPONSE":
        response_path = "data/processed/propagation/paper1/g04b_fractional_response/outputs/paper1_g04b_fractional_newly_covered_1km.parquet"
        response_sha = "666c4c786a3fa4fb797a023bf528fa15ff8d4fbdd30a67c9bbfcc2b250ee7d93"
        response_map_sha = "3c6b91a660f7c4731b99d59153c0ed6cd611fa3bf4d5de2b5be9266517786bb7"
    support_path, support_hash, _, _ = SUPPORT_AUTHORITIES[("PRIMARY_HYBRID", 1000)]
    values = {
        "schema_version": EXECUTION_SCHEMA_VERSION, "git_head": _git_head(root),
        "analysis_id": analysis_id, "analysis_family": str(row["family"]),
        "comparator_identity": "SPECIALIZED_G05B", "model_family": model_family,
        "model_role": model_role, "risk_set_id": "PRIMARY_HYBRID", "resolution_m": 1000,
        "evaluation_identity": evaluation_identity, "training_intervals": (), "heldout_intervals": (),
        "predictor_path": predictor.relative_path, "predictor_sha256": predictor.expected_sha256,
        "predictor_key_sha256": predictor.canonical_key_sha256,
        "support_identity": str(row["support_universe"]), "support_path": support_path,
        "support_sha256": support_hash, "response_path": response_path,
        "response_sha256": response_sha, "response_key_sha256": outcome.canonical_key_sha256,
        "response_key_interval_value_sha256": response_map_sha,
        "preprocessing_identity": str(row["logistic_policy"]),
        "tuning_identity": str(row["random_forest_policy"]),
        "governed_seeds": RF_SEEDS if model_family == "RANDOM_FOREST" else (),
        "metric_authority_sha256": METRIC_AUTHORITY_SHA256,
        "uncertainty_authority_sha256": UNCERTAINTY_AUTHORITY_SHA256,
        "environment_requirement": "statsmodels==0.14.6" if analysis_id == "G05B_FRACTIONAL_RESPONSE" else "WILDFIRE_LOCKED_ENVIRONMENT",
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "generation_schema_version": GENERATION_SCHEMA_VERSION,
        "registry_source": G05B_REGISTRY_SOURCE, "registry_sha256": G05B_REGISTRY_SOURCE_SHA256,
        "execution_enabled": True,
        "special_condition": "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE" if analysis_id == "G05B_BOUNDARY_1000" else "STATSMODELS_0.14.6_ENVIRONMENT_REQUIRED" if analysis_id == "G05B_FRACTIONAL_RESPONSE" else "NONE",
    }
    return ExecutionContract(**values, contract_sha256=_contract_hash(values))


def governed_execution_contracts(project_root: Path) -> tuple[ExecutionContract, ...]:
    root = Path(project_root).resolve()
    from src import paper1_analysis_registry as registry
    contracts: list[ExecutionContract] = []
    for analysis in registry.registry(root):
        if not analysis.executable_status.startswith("EXECUTABLE"):
            continue
        for evaluation in OUTER_EVALUATIONS:
            for family in ("L2_LOGISTIC", "RANDOM_FOREST"):
                for role in ("baseline", "augmented"):
                    contracts.append(governed_execution_contract(root, analysis.analysis_id, family, role, evaluation))
    g05b = pd.read_csv(root / G05B_REGISTRY_SOURCE)
    for row in g05b.itertuples(index=False):
        if row.analysis_id == "G05B_LOIO_PRIMARY_FORWARD":
            roles = (("DIAGNOSTIC_NO_REFIT", "paired_delta"),)
        elif row.analysis_id == "G05B_FRACTIONAL_RESPONSE":
            roles = (("FRACTIONAL_LOGIT_GLM", "baseline"), ("FRACTIONAL_LOGIT_GLM", "augmented"))
        else:
            roles = tuple((family, role) for family in ("L2_LOGISTIC", "RANDOM_FOREST")
                          for role in ("baseline", "augmented"))
        for family, role in roles:
            contracts.append(governed_execution_contract(root, row.analysis_id, family, role,
                                                          str(row.fold_or_threshold)))
    return tuple(contracts)


def validate_execution_contract(project_root: Path, contract: ExecutionContract) -> None:
    expected = governed_execution_contract(project_root, contract.analysis_id, contract.model_family,
                                           contract.model_role, contract.evaluation_identity)
    if contract != expected:
        differing = next(field for field in asdict(expected) if getattr(contract, field) != getattr(expected, field))
        raise ContractError(f"ERR_EXECUTION_CONTRACT_{differing.upper()}")


def execution_context(project_root: Path, contract: ExecutionContract, run_id: str, generation_id: str,
                      environment_identity: str) -> RunContext:
    validate_execution_contract(project_root, contract)
    if not run_id or not generation_id or not environment_identity:
        raise ContractError("ERR_RUN_CONTEXT_IDENTITY")
    return RunContext(run_id, generation_id, contract.git_head, environment_identity, contract.contract_sha256)


def _outcome_rows_for_contract(contract: ExecutionContract, outcome: AuthenticatedOutcomeArtifact) -> tuple[OutcomeRow, ...]:
    _verify_handle(outcome)
    if (outcome.authority.risk_set_id, outcome.authority.resolution_m) != (contract.risk_set_id, contract.resolution_m):
        raise ContractError("ERR_OUTCOME_CONTRACT_SCOPE")
    if outcome.observed_sha256 != contract.response_sha256 or outcome.observed_key_interval_response_sha256 != contract.response_key_interval_value_sha256:
        raise ContractError("ERR_OUTCOME_CONTRACT_IDENTITY")
    rows = tuple(row for row in outcome.rows if row.interval_number in set(contract.heldout_intervals))
    if not rows:
        raise ContractError("ERR_OUTCOME_HELDOUT_EMPTY")
    return rows


def prediction_template(contract: ExecutionContract, outcome: AuthenticatedOutcomeArtifact,
                        context: RunContext, seed: int, probabilities: Sequence[float]) -> pd.DataFrame:
    """Construct a typed prediction payload after predictions already exist."""
    validate_execution_contract(Path(outcome.project_root), contract)
    if context.execution_contract_sha256 != contract.contract_sha256 or context.git_head != contract.git_head:
        raise ContractError("ERR_RUN_CONTEXT_CONTRACT")
    if contract.model_family == "RANDOM_FOREST":
        if seed not in contract.governed_seeds:
            raise ContractError("ERR_PREDICTION_SEED")
    elif seed != 0:
        raise ContractError("ERR_PREDICTION_SEED")
    rows = _outcome_rows_for_contract(contract, outcome)
    values = np.asarray(probabilities, dtype=float)
    if len(values) != len(rows):
        raise ContractError("ERR_PREDICTION_ROW_UNIVERSE")
    records = []
    for row, probability in zip(rows, values):
        records.append({
            "schema_version": PREDICTION_SCHEMA_VERSION,
            "run_id": context.run_id,
            "generation_id": context.generation_id,
            "analysis_id": contract.analysis_id,
            "outer_evaluation": contract.evaluation_identity,
            "model_family": contract.model_family,
            "model_role": contract.model_role,
            "seed": int(seed),
            "event_id": row.event_id,
            "interval_id": row.interval_id,
            "response_grid_m": row.response_grid_m,
            "cell_id": row.cell_id,
            "interval_number": row.interval_number,
            "heldout": True,
            "predicted_probability": float(probability),
            "response_y": row.response_y,
        })
    return pd.DataFrame.from_records(records, columns=PREDICTION_COLUMNS)


def validate_predictions(frame: pd.DataFrame, contract: ExecutionContract,
                         outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                         seed: int) -> pd.DataFrame:
    if tuple(frame.columns) != PREDICTION_COLUMNS:
        raise ContractError("ERR_PREDICTION_SCHEMA_COLUMNS")
    if frame.empty:
        raise ContractError("ERR_PREDICTION_EMPTY")
    validate_execution_contract(Path(outcome.project_root), contract)
    if context.execution_contract_sha256 != contract.contract_sha256 or context.git_head != contract.git_head:
        raise ContractError("ERR_RUN_CONTEXT_CONTRACT")
    constants = {
        "schema_version": PREDICTION_SCHEMA_VERSION,
        "run_id": context.run_id,
        "generation_id": context.generation_id,
        "analysis_id": contract.analysis_id,
        "outer_evaluation": contract.evaluation_identity,
        "model_family": contract.model_family,
        "model_role": contract.model_role,
        "seed": int(seed),
        "response_grid_m": contract.resolution_m,
    }
    for field, expected in constants.items():
        if not frame[field].eq(expected).all():
            raise ContractError(f"ERR_PREDICTION_IDENTITY_{field.upper()}")
    if frame.loc[:, PREDICTION_KEY].duplicated().any():
        raise ContractError("ERR_PREDICTION_DUPLICATE_KEY")
    probabilities = pd.to_numeric(frame["predicted_probability"], errors="coerce").to_numpy(float)
    if not np.isfinite(probabilities).all():
        raise ContractError("ERR_PREDICTION_NONFINITE")
    if ((probabilities < 0.0) | (probabilities > 1.0)).any():
        raise ContractError("ERR_PREDICTION_PROBABILITY_RANGE")
    if not frame["heldout"].map(lambda value: isinstance(value, (bool, np.bool_))).all() or not frame["heldout"].all():
        raise ContractError("ERR_HELDOUT_MEMBERSHIP")
    governed = {row.key: (row.interval_id, row.interval_number, row.response_y)
                for row in _outcome_rows_for_contract(contract, outcome)}
    observed_keys = [tuple(row) for row in frame.loc[:, KEY_FIELDS].itertuples(index=False, name=None)]
    if len(observed_keys) != len(governed) or set(observed_keys) != set(governed):
        raise ContractError("ERR_PREDICTION_ROW_UNIVERSE")
    for record, key in zip(frame.itertuples(index=False), observed_keys):
        authoritative_interval_id, authoritative_number, authoritative_y = governed[key]
        if str(record.interval_id) != authoritative_interval_id:
            raise ContractError("ERR_PREDICTION_INTERVAL_ID_AUTHORITY")
        try:
            observed_number = int(record.interval_number)
        except (TypeError, ValueError) as exc:
            raise ContractError("ERR_PREDICTION_INTERVAL_NUMBER_AUTHORITY") from exc
        if observed_number != authoritative_number:
            raise ContractError("ERR_PREDICTION_INTERVAL_NUMBER_AUTHORITY")
        if pd.isna(record.response_y) or int(record.response_y) != authoritative_y:
            raise ContractError("ERR_PREDICTION_RESPONSE_AUTHORITY")
    return frame.sort_values(list(PREDICTION_KEY), kind="stable").reset_index(drop=True)


def _prediction_receipt(path: Path, raw: bytes, canonical: pd.DataFrame, contract: ExecutionContract,
                        outcome: AuthenticatedOutcomeArtifact, context: RunContext, seed: int) -> PredictionArtifactReceipt:
    key_hash = hashlib.sha256(canonical.loc[:, PREDICTION_KEY].to_csv(index=False, lineterminator="\n").encode("utf-8")).hexdigest()
    outcome_hash = _frame_hash(
        canonical.rename(columns={"response_y": "y"}), OUTCOME_FIELDS,
    )
    resolved = Path(path).resolve()
    try:
        relative = str(resolved.relative_to(Path(outcome.project_root).resolve())).replace("\\", "/")
    except ValueError:
        relative = resolved.as_posix()
    return PredictionArtifactReceipt(
        PREDICTION_RECEIPT_SCHEMA_VERSION, relative, hashlib.sha256(raw).hexdigest(), len(raw),
        len(canonical), key_hash, outcome_hash, context.run_id, context.generation_id,
        contract.contract_sha256, contract.analysis_id, contract.evaluation_identity,
        contract.model_family, contract.model_role, int(seed), contract.resolution_m,
        "COMPLETE_MARKER_LAST",
    )


def write_prediction_artifact(path: Path, frame: pd.DataFrame, contract: ExecutionContract,
                              outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                              seed: int) -> AuthenticatedPredictionArtifact:
    canonical = validate_predictions(frame, contract, outcome, context, seed)
    raw = canonical.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode("utf-8")
    receipt = _prediction_receipt(Path(path), raw, canonical, contract, outcome, context, seed)
    _atomic_bytes(Path(path), raw)
    _atomic_bytes(Path(str(path) + ".receipt.json"), canonical_json(asdict(receipt)))
    return read_prediction_artifact(path, contract, outcome, context, seed)


def read_prediction_artifact(path: Path, contract: ExecutionContract,
                             outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                             seed: int) -> AuthenticatedPredictionArtifact:
    path = Path(path)
    marker = Path(str(path) + ".receipt.json")
    if not path.is_file() or not marker.is_file():
        raise ContractError("ERR_PREDICTION_PUBLICATION_INCOMPLETE")
    raw = path.read_bytes()
    try:
        observed = PredictionArtifactReceipt(**json.loads(marker.read_text(encoding="ascii")))
    except Exception as exc:
        raise ContractError("ERR_PREDICTION_RECEIPT_SCHEMA") from exc
    if observed.artifact_sha256 != hashlib.sha256(raw).hexdigest():
        raise ContractError("ERR_PREDICTION_RECEIPT_ARTIFACT_SHA256")
    if observed.artifact_bytes != len(raw):
        raise ContractError("ERR_PREDICTION_RECEIPT_ARTIFACT_BYTES")
    frame = pd.read_csv(path, dtype={
        "schema_version": str, "run_id": str, "generation_id": str, "analysis_id": str,
        "outer_evaluation": str, "model_family": str, "model_role": str,
        "event_id": str, "interval_id": str, "cell_id": str,
    })
    frame["heldout"] = frame["heldout"].map({True: True, False: False, "True": True, "False": False})
    canonical = validate_predictions(frame, contract, outcome, context, seed)
    derived = _prediction_receipt(path, raw, canonical, contract, outcome, context, seed)
    if observed != derived:
        differing = next(field for field in asdict(derived) if getattr(observed, field) != getattr(derived, field))
        raise ContractError(f"ERR_PREDICTION_RECEIPT_{differing.upper()}")
    return AuthenticatedPredictionArtifact(str(Path(outcome.project_root).resolve()), derived.path, derived,
                                           contract, context)


def validate_prediction_receipt(receipt: PredictionArtifactReceipt, path: Path,
                                contract: ExecutionContract, outcome: AuthenticatedOutcomeArtifact,
                                context: RunContext, seed: int) -> None:
    authenticated = read_prediction_artifact(path, contract, outcome, context, seed)
    if receipt != authenticated.receipt:
        differing = next(field for field in asdict(authenticated.receipt)
                         if getattr(receipt, field) != getattr(authenticated.receipt, field))
        raise ContractError(f"ERR_PREDICTION_RECEIPT_{differing.upper()}")


def governed_terminal_evidence(contract: ExecutionContract, state: ExecutionState,
    observed_environment: str = "") -> TerminalEvidence:
    if state is ExecutionState.GOVERNED_NONESTIMABLE:
        if contract.analysis_id != "G05B_BOUNDARY_1000":
            raise ContractError("ERR_TERMINAL_REASON_SCOPE")
        return TerminalEvidence(
            TerminalReasonCode.BOUNDARY_1000_B1_ALL_NEGATIVE, "GOVERNED_NONESTIMABLE",
            "documentation/PAPER1_G05B_BOUNDARY_SUPPORT_QC.csv", contract.analysis_id,
            contract.evaluation_identity,
            (("affected_outer", "B1_TO_B2"), ("training_rows", "452"),
             ("training_positive", "0"), ("training_negative", "452")),
        )
    if state is ExecutionState.ENVIRONMENT_BLOCKED:
        if contract.analysis_id != "G05B_FRACTIONAL_RESPONSE":
            raise ContractError("ERR_TERMINAL_REASON_SCOPE")
        if observed_environment == "statsmodels==0.14.6":
            raise ContractError("ERR_ENVIRONMENT_EVIDENCE_CONTRADICTORY")
        return TerminalEvidence(
            TerminalReasonCode.STATSMODELS_0_14_6_REQUIRED, "ENVIRONMENT_BLOCKED",
            "documentation/PAPER1_G05B_FRACTIONAL_DISPATCH_QC.csv", contract.analysis_id,
            contract.evaluation_identity,
            (("required", "statsmodels==0.14.6"), ("observed", observed_environment or "NOT_INSTALLED")),
        )
    if state is ExecutionState.MACHINE_DISABLED:
        if contract.execution_enabled:
            raise ContractError("ERR_DISABLED_EXECUTABLE_CONTRACT")
        return TerminalEvidence(TerminalReasonCode.DISABLED_BY_FROZEN_REGISTRY, "MACHINE_DISABLED",
                                contract.registry_source, contract.analysis_id, contract.evaluation_identity,
                                (("execution_enabled", "false"),))
    if state is ExecutionState.PENDING:
        return TerminalEvidence(TerminalReasonCode.PENDING_NOT_EXECUTED, "PENDING", GATE_VERSION,
                                contract.analysis_id, contract.evaluation_identity, (("attempted", "false"),))
    if state is ExecutionState.FAILED:
        return TerminalEvidence(TerminalReasonCode.RUNTIME_EXCEPTION, "FAILED_RUNTIME", GATE_VERSION,
                                contract.analysis_id, contract.evaluation_identity, (("exception_recorded", "true"),))
    if state is ExecutionState.COMPLETE:
        return TerminalEvidence(TerminalReasonCode.NONE, "COMPLETE", GATE_VERSION,
                                contract.analysis_id, contract.evaluation_identity, ())
    raise ContractError("ERR_EXECUTION_STATE_UNKNOWN")


def validate_terminal_evidence(contract: ExecutionContract, state: ExecutionState,
                               evidence: TerminalEvidence, observed_environment: str = "") -> None:
    expected = governed_terminal_evidence(contract, state, observed_environment)
    if evidence != expected:
        raise ContractError("ERR_TERMINAL_REASON_AUTHORITY")


def build_run_receipt(contract: ExecutionContract, predictor: AuthenticatedPredictorArtifact,
                      outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                      state: ExecutionState, evidence: TerminalEvidence,
                      prediction: AuthenticatedPredictionArtifact | None = None) -> RunReceipt:
    validate_execution_contract(Path(outcome.project_root), contract)
    _verify_predictor_handle(predictor)
    _verify_handle(outcome)
    validate_terminal_evidence(contract, state, evidence, context.environment_identity)
    if predictor.observed_sha256 != contract.predictor_sha256 or predictor.observed_key_sha256 != contract.predictor_key_sha256:
        raise ContractError("ERR_RUN_PREDICTOR_IDENTITY")
    if state is ExecutionState.COMPLETE:
        if prediction is None:
            raise ContractError("ERR_COMPLETE_WITHOUT_PREDICTION")
        refreshed = read_prediction_artifact(
            Path(prediction.project_root) / prediction.relative_path, contract, outcome, context,
            prediction.receipt.seed,
        )
        prediction_path, prediction_hash = refreshed.relative_path, refreshed.receipt.artifact_sha256
    else:
        if prediction is not None:
            raise ContractError("ERR_NONCOMPLETE_WITH_PREDICTION")
        prediction_path = prediction_hash = ""
    return RunReceipt(
        RUN_RECEIPT_SCHEMA_VERSION, GATE_VERSION, context.run_id, context.generation_id,
        context.git_head, contract.contract_sha256, contract.analysis_id, contract.model_family,
        contract.model_role, contract.evaluation_identity, contract.resolution_m,
        predictor.authority.relative_path, predictor.observed_sha256, predictor.observed_key_sha256,
        contract.support_path, contract.support_sha256, outcome.authority.relative_path,
        outcome.observed_sha256, outcome.observed_key_interval_response_sha256,
        contract.preprocessing_identity, contract.tuning_identity, contract.governed_seeds,
        context.environment_identity, prediction_path, prediction_hash, state, evidence.reason_code,
        evidence.authority_source, state is not ExecutionState.COMPLETE,
    )


def validate_run_receipt(receipt: RunReceipt, contract: ExecutionContract,
                         predictor: AuthenticatedPredictorArtifact,
                         outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                         evidence: TerminalEvidence,
                         prediction: AuthenticatedPredictionArtifact | None = None) -> None:
    expected = build_run_receipt(contract, predictor, outcome, context, receipt.execution_state,
                                 evidence, prediction)
    if receipt != expected:
        differing = next(field for field in asdict(expected) if getattr(receipt, field) != getattr(expected, field))
        raise ContractError(f"ERR_RUN_RECEIPT_{differing.upper()}")


def validate_manifest_states(project_root: Path, required_units: Sequence[str], states: Mapping[str, ExecutionState],
                             evidence: Mapping[str, TerminalEvidence],
                             contracts: Mapping[str, ExecutionContract]) -> Mapping[str, object]:
    required = tuple(required_units)
    if set(states) != set(required) or set(evidence) != set(required) or set(contracts) != set(required):
        raise ContractError("ERR_MANIFEST_UNIT_SET")
    for unit in required:
        validate_execution_contract(project_root, contracts[unit])
        state = states[unit]
        if not isinstance(state, ExecutionState):
            raise ContractError("ERR_EXECUTION_STATE_UNKNOWN")
        validate_terminal_evidence(contracts[unit], state, evidence[unit],
                                   dict(evidence[unit].evidence).get("observed", ""))
    terminal = {ExecutionState.COMPLETE, ExecutionState.ENVIRONMENT_BLOCKED, ExecutionState.FAILED,
                ExecutionState.GOVERNED_NONESTIMABLE, ExecutionState.MACHINE_DISABLED}
    accounting_complete = all(state in terminal for state in states.values())
    executable_units = [unit for unit in required if contracts[unit].execution_enabled]
    completed = [unit for unit in executable_units if states[unit] is ExecutionState.COMPLETE]
    attempted = [unit for unit in executable_units if states[unit] is not ExecutionState.PENDING]
    scientific_success = bool(executable_units) and len(completed) == len(executable_units)
    return MappingProxyType({
        "accounting_complete": accounting_complete,
        "scientific_execution_attempted": bool(attempted),
        "scientific_execution_units_completed": len(completed),
        "required_executable_units": len(executable_units),
        "scientific_execution_succeeded": scientific_success,
        "state_counts": MappingProxyType({state.value: sum(value is state for value in states.values())
                                           for state in ExecutionState}),
    })


def _checkpoint_receipt(contract: ExecutionContract, predictor: AuthenticatedPredictorArtifact,
                        outcome: AuthenticatedOutcomeArtifact, context: RunContext, stage: str,
                        seed: int, payload: bytes,
                        prior_predictions: Sequence[AuthenticatedPredictionArtifact],
                        completion_state: ExecutionState) -> CheckpointReceipt:
    validate_execution_contract(Path(outcome.project_root), contract)
    _verify_predictor_handle(predictor)
    _verify_handle(outcome)
    if stage not in CHECKPOINT_STAGES:
        raise ContractError("ERR_CHECKPOINT_STAGE")
    if contract.model_family == "RANDOM_FOREST" and seed not in RF_SEEDS:
        raise ContractError("ERR_CHECKPOINT_SEED")
    if completion_state is ExecutionState.COMPLETE and stage != "FINALIZED":
        raise ContractError("ERR_CHECKPOINT_FALSE_COMPLETE")
    prior_hashes = []
    for handle in prior_predictions:
        refreshed = read_prediction_artifact(
            Path(handle.project_root) / handle.relative_path, contract, outcome, context,
            handle.receipt.seed,
        )
        prior_hashes.append(refreshed.receipt.artifact_sha256)
    if completion_state is ExecutionState.COMPLETE and not prior_hashes:
        raise ContractError("ERR_CHECKPOINT_FALSE_COMPLETE")
    return CheckpointReceipt(
        CHECKPOINT_SCHEMA_VERSION, context.run_id, context.generation_id, context.git_head,
        contract.contract_sha256, contract.analysis_id, contract.model_family, contract.model_role,
        contract.resolution_m, contract.evaluation_identity, contract.training_intervals,
        contract.heldout_intervals, predictor.observed_sha256, contract.support_sha256,
        outcome.observed_sha256, outcome.observed_key_interval_response_sha256,
        contract.preprocessing_identity, contract.tuning_identity, context.environment_identity,
        int(seed), stage, hashlib.sha256(payload).hexdigest(), len(payload), tuple(prior_hashes),
        completion_state,
    )


def write_checkpoint(path: Path, payload: bytes, contract: ExecutionContract,
                     predictor: AuthenticatedPredictorArtifact,
                     outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                     stage: str, seed: int,
                     prior_predictions: Sequence[AuthenticatedPredictionArtifact] = (),
                     completion_state: ExecutionState = ExecutionState.PENDING) -> CheckpointReceipt:
    receipt = _checkpoint_receipt(contract, predictor, outcome, context, stage, seed, payload,
                                  prior_predictions, completion_state)
    _atomic_bytes(Path(path), payload)
    marker = asdict(receipt)
    marker["completion_state"] = receipt.completion_state.value
    _atomic_bytes(Path(str(path) + ".checkpoint.json"), canonical_json(marker))
    return receipt


def read_checkpoint(path: Path, contract: ExecutionContract,
                    predictor: AuthenticatedPredictorArtifact,
                    outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                    stage: str, seed: int,
                    prior_predictions: Sequence[AuthenticatedPredictionArtifact] = (),
                    completion_state: ExecutionState = ExecutionState.PENDING) -> tuple[bytes, CheckpointReceipt]:
    path = Path(path)
    marker = Path(str(path) + ".checkpoint.json")
    if not path.is_file() or not marker.is_file():
        raise ContractError("ERR_CHECKPOINT_PUBLICATION_INCOMPLETE")
    payload = path.read_bytes()
    expected = _checkpoint_receipt(contract, predictor, outcome, context, stage, seed, payload,
                                   prior_predictions, completion_state)
    data = json.loads(marker.read_text(encoding="ascii"))
    data["completion_state"] = ExecutionState(data["completion_state"])
    for field in ("training_intervals", "heldout_intervals", "prior_prediction_sha256s"):
        data[field] = tuple(data[field])
    try:
        observed = CheckpointReceipt(**data)
    except Exception as exc:
        raise ContractError("ERR_CHECKPOINT_SCHEMA") from exc
    if observed != expected:
        differing = next(field for field in asdict(expected) if getattr(observed, field) != getattr(expected, field))
        raise ContractError(f"ERR_CHECKPOINT_{differing.upper()}")
    return payload, observed


def _metric_universe(contract: ExecutionContract, outcome: AuthenticatedOutcomeArtifact,
                     interval_number: int | None = None) -> tuple[tuple[int, ...], str]:
    rows = _outcome_rows_for_contract(contract, outcome)
    if interval_number is not None:
        if interval_number not in contract.heldout_intervals:
            raise ContractError("ERR_METRIC_EVALUATION_SCOPE")
        rows = tuple(row for row in rows if row.interval_number == interval_number)
    if not rows:
        raise ContractError("ERR_METRIC_EMPTY_UNIVERSE")
    frame = pd.DataFrame([(*row.key, row.interval_number, row.response_y) for row in rows], columns=OUTCOME_FIELDS)
    return tuple(row.response_y for row in rows), _frame_hash(frame, OUTCOME_FIELDS)


def governed_metric_universe_from_terminal(contract: ExecutionContract,
                                           evidence: TerminalEvidence) -> AuthenticatedMetricUniverse:
    validate_terminal_evidence(contract, ExecutionState.GOVERNED_NONESTIMABLE, evidence)
    values = dict(evidence.evidence)
    rows = int(values["training_rows"])
    positives = int(values["training_positive"])
    negatives = int(values["training_negative"])
    if rows != positives + negatives:
        raise ContractError("ERR_METRIC_CLASS_COUNT_EVIDENCE")
    identity = hashlib.sha256(canonical_json({
        "analysis_id": contract.analysis_id, "evaluation": values["affected_outer"],
        "rows": rows, "positives": positives, "negatives": negatives,
        "authority": evidence.authority_source,
    })).hexdigest()
    return AuthenticatedMetricUniverse(contract.analysis_id, values["affected_outer"], rows,
                                       positives, negatives, identity, evidence.authority_source)


def _metric_from_counts(contract: ExecutionContract, name: MetricName, value: float | None,
                        evaluation: str, universe_hash: str, row_count: int,
                        class_count: int) -> MetricRecord:
    authority = METRIC_AUTHORITIES[name]
    if class_count == 1 and not authority.single_class_defined:
        if value is not None:
            raise ContractError("ERR_METRIC_UNDEFINED_VALUE")
        return MetricRecord(name, authority.role, contract.analysis_id, contract.model_family,
                            contract.model_role, evaluation, universe_hash, row_count, class_count,
                            "UNDEFINED_SINGLE_CLASS", None, authority.undefined_reason, False)
    if value is None or not np.isfinite(value):
        raise ContractError("ERR_METRIC_VALUE")
    numeric = float(value)
    if numeric < authority.value_minimum or (authority.value_maximum is not None and numeric > authority.value_maximum):
        raise ContractError("ERR_METRIC_VALUE_DOMAIN")
    return MetricRecord(name, authority.role, contract.analysis_id, contract.model_family,
                        contract.model_role, evaluation, universe_hash, row_count, class_count,
                        "DEFINED", numeric, "", authority.include_when_defined)


def metric_record_from_governed_universe(contract: ExecutionContract,
                                         universe: AuthenticatedMetricUniverse,
                                         metric_name: MetricName | str,
                                         value: float | None) -> MetricRecord:
    try:
        name = MetricName(metric_name)
    except ValueError as exc:
        raise ContractError("ERR_METRIC_UNKNOWN") from exc
    if universe.analysis_id != contract.analysis_id:
        raise ContractError("ERR_METRIC_ANALYSIS_ID")
    class_count = int(universe.positive_count > 0) + int(universe.negative_count > 0)
    return _metric_from_counts(contract, name, value, universe.evaluation_identity,
                               universe.row_universe_sha256, universe.row_count, class_count)


def validate_metric_record_from_governed_universe(record: MetricRecord,
                                                  contract: ExecutionContract,
                                                  universe: AuthenticatedMetricUniverse) -> None:
    try:
        authority = METRIC_AUTHORITIES[MetricName(record.metric_name)]
    except (KeyError, ValueError) as exc:
        raise ContractError("ERR_METRIC_UNKNOWN") from exc
    class_count = int(universe.positive_count > 0) + int(universe.negative_count > 0)
    expected_status = "DEFINED" if class_count > 1 or authority.single_class_defined else "UNDEFINED_SINGLE_CLASS"
    if record.eligibility_status != expected_status:
        raise ContractError("ERR_METRIC_ELIGIBILITY_STATUS")
    expected = metric_record_from_governed_universe(contract, universe, record.metric_name, record.value)
    if record != expected:
        differing = next(field for field in asdict(expected) if getattr(record, field) != getattr(expected, field))
        raise ContractError(f"ERR_METRIC_{differing.upper()}")


def metric_record(contract: ExecutionContract, outcome: AuthenticatedOutcomeArtifact,
                  metric_name: MetricName | str, value: float | None,
                  interval_number: int | None = None) -> MetricRecord:
    try:
        name = MetricName(metric_name)
    except ValueError as exc:
        raise ContractError("ERR_METRIC_UNKNOWN") from exc
    y, universe_hash = _metric_universe(contract, outcome, interval_number)
    class_count = len(set(y))
    evaluation = contract.evaluation_identity if interval_number is None else f"{contract.evaluation_identity}:INTERVAL_{interval_number}"
    return _metric_from_counts(contract, name, value, evaluation, universe_hash, len(y), class_count)


def validate_metric_record(record: MetricRecord, contract: ExecutionContract,
                           outcome: AuthenticatedOutcomeArtifact,
                           interval_number: int | None = None) -> None:
    expected = metric_record(contract, outcome, record.metric_name, record.value, interval_number)
    if record != expected:
        differing = next(field for field in asdict(expected) if getattr(record, field) != getattr(expected, field))
        raise ContractError(f"ERR_METRIC_{differing.upper()}")


def metric_aggregation(records: Sequence[MetricRecord], contract: ExecutionContract,
                       outcome: AuthenticatedOutcomeArtifact,
                       interval_numbers: Sequence[int | None]) -> Mapping[str, object]:
    if len(records) != len(interval_numbers) or not records:
        raise ContractError("ERR_METRIC_EVALUATION_SET")
    for record, interval in zip(records, interval_numbers):
        validate_metric_record(record, contract, outcome, interval)
    identity_fields = ("metric_name", "metric_role", "analysis_id", "model_family", "model_role")
    for field in identity_fields:
        if len({getattr(record, field) for record in records}) != 1:
            raise ContractError(f"ERR_METRIC_AGGREGATION_{field.upper()}")
    if len({record.evaluation_identity for record in records}) != len(records):
        raise ContractError("ERR_METRIC_DUPLICATE_EVALUATION")
    defined = tuple(record for record in records if record.eligibility_status == "DEFINED")
    undefined = tuple(record for record in records if record.eligibility_status != "DEFINED")
    if any(not record.include_in_aggregate for record in defined):
        raise ContractError("ERR_METRIC_DEFINED_EXCLUDED")
    if any(record.include_in_aggregate for record in undefined):
        raise ContractError("ERR_METRIC_UNDEFINED_INCLUDED")
    return MappingProxyType({
        "governed_unit_count": len(records),
        "eligible_unit_count": len(defined),
        "defined_unit_count": len(defined),
        "undefined_unit_count": len(undefined),
        "excluded_unit_count": len(undefined),
        "aggregation_denominator": len(defined),
        "included_evaluation_ids": tuple(record.evaluation_identity for record in defined),
        "excluded_reasons": tuple((record.evaluation_identity, record.reason_code) for record in undefined),
    })


def rf_stability(project_root: Path, seed_metrics: Sequence[RFSeedMetricRecord],
                 outcome: AuthenticatedOutcomeArtifact) -> RFStabilitySummary:
    if len(seed_metrics) != len(RF_SEEDS):
        raise ContractError("ERR_RF_SEED_SET")
    authenticated: list[tuple[AuthenticatedPredictionArtifact, MetricRecord]] = []
    for record in seed_metrics:
        if not isinstance(record, RFSeedMetricRecord) or not isinstance(record.prediction, AuthenticatedPredictionArtifact):
            raise ContractError("ERR_RF_SEED_ARTIFACT_HANDLE")
        handle = record.prediction
        contract = handle.execution_contract
        if contract.model_family != "RANDOM_FOREST":
            raise ContractError("ERR_RF_MODEL_FAMILY")
        refreshed = read_prediction_artifact(Path(project_root) / handle.relative_path, contract, outcome,
                                             handle.run_context, handle.receipt.seed)
        if refreshed != handle:
            raise ContractError("ERR_RF_SEED_HANDLE_BINDING")
        validate_metric_record(record.metric, contract, outcome)
        authenticated.append((refreshed, record.metric))
    seeds = tuple(sorted(handle.receipt.seed for handle, _ in authenticated))
    if seeds != RF_SEEDS:
        raise ContractError("ERR_RF_SEED_SET")
    artifacts = tuple(handle.receipt.artifact_sha256 for handle, _ in authenticated)
    if len(set(artifacts)) != len(RF_SEEDS):
        raise ContractError("ERR_RF_SEED_ARTIFACT_DUPLICATE")
    metrics = tuple(metric for _, metric in authenticated)
    for field in ("analysis_id", "model_role", "evaluation_identity", "metric_name",
                  "metric_role", "row_universe_sha256"):
        if len({getattr(metric, field) for metric in metrics}) != 1:
            raise ContractError(f"ERR_RF_METRIC_IDENTITY_{field.upper()}")
    states = {metric.eligibility_status for metric in metrics}
    first = metrics[0]
    ordered = sorted(zip((handle.receipt.seed for handle, _ in authenticated), artifacts, metrics))
    if states == {"DEFINED"}:
        values = tuple(float(metric.value) for _, _, metric in ordered)
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
        return RFStabilitySummary(first.analysis_id, first.model_role, first.evaluation_identity,
                                  first.metric_name, tuple((seed, artifact) for seed, artifact, _ in ordered),
                                  tuple((seed, float(metric.value)) for seed, _, metric in ordered),
                                  mean, min(values), max(values), max(values) - min(values), math.sqrt(variance),
                                  5, 0, RF_SD_CONVENTION, "DEFINED", "")
    if states == {"UNDEFINED_SINGLE_CLASS"} and {metric.reason_code for metric in metrics} == {"HELDOUT_UNIT_SINGLE_CLASS"}:
        return RFStabilitySummary(first.analysis_id, first.model_role, first.evaluation_identity,
                                  first.metric_name, tuple((seed, artifact) for seed, artifact, _ in ordered),
                                  None, None, None, None, None, None, 5, 0, RF_SD_CONVENTION,
                                  "NOT_DEFINED", "HELDOUT_UNIT_SINGLE_CLASS")
    raise ContractError("ERR_RF_METRIC_MIXED_ELIGIBILITY")


def _validation_generation_metadata(root: Path, payloads: Mapping[str, bytes]) -> dict[str, object]:
    required = set(G06_2C_GENERATION_AUTHORITY.required_payloads)
    if set(payloads) != required:
        missing = required - set(payloads)
        if missing:
            raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_MISSING")
        raise ContractError("ERR_GENERATION_UNEXPECTED_PAYLOAD")
    tests = pd.read_csv(io.BytesIO(payloads["PAPER1_G06_2C_TEST_EXECUTION.csv"]))
    required_columns = {"test_id", "provenance_class", "result", "expected_reason", "observed_reason"}
    if not required_columns.issubset(tests.columns):
        raise ContractError("ERR_GENERATION_TEST_SCHEMA")
    blocker = tests.loc[tests["test_id"].isin(G06_2C_GENERATION_AUTHORITY.required_blocker_tests)]
    if set(blocker["test_id"]) != set(G06_2C_GENERATION_AUTHORITY.required_blocker_tests):
        raise ContractError("ERR_GENERATION_BLOCKER_TEST_SET")
    if not blocker["result"].eq("PASS").all():
        raise ContractError("ERR_GENERATION_BLOCKER_TEST_FAILURE")
    if not tests.loc[tests["provenance_class"].eq("BEHAVIORAL"), "result"].eq("PASS").all():
        raise ContractError("ERR_GENERATION_BEHAVIORAL_TEST_FAILURE")
    decision = pd.read_csv(io.BytesIO(payloads["PAPER1_G06_2C_DECISION.csv"]))
    if set(decision.columns) != {"gate", "status", "model_fitting_authorized", "real_predictions_generated", "real_performance_inspected"} or len(decision) != 1:
        raise ContractError("ERR_GENERATION_DECISION_SCHEMA")
    row = decision.iloc[0]
    if row["gate"] != GATE_VERSION or row["status"] != "COMPLETE":
        raise ContractError("ERR_GENERATION_FALSE_COMPLETE")
    if str(row["model_fitting_authorized"]).upper() not in {"FALSE", "NO"}:
        raise ContractError("ERR_GENERATION_MODEL_AUTHORIZATION")
    if str(row["real_predictions_generated"]).upper() not in {"FALSE", "NO"} or str(row["real_performance_inspected"]).upper() not in {"FALSE", "NO"}:
        raise ContractError("ERR_GENERATION_REAL_RESULT_CLAIM")
    return {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "gate_version": GATE_VERSION,
        "git_head": _git_head(root),
        "runtime_source_sha256": sha256_file(root / "src/paper1_g06_2c_runtime.py"),
        "validator_source_sha256": sha256_file(root / "scripts/validate_paper1_g06_2c.py"),
        "g05a_registry_sha256": G05A_REGISTRY_SOURCE_SHA256,
        "g05b_registry_sha256": G05B_REGISTRY_SOURCE_SHA256,
        "metric_authority_sha256": METRIC_AUTHORITY_SHA256,
        "rf_authority_sha256": RF_AUTHORITY_SHA256,
        "decision_status": "COMPLETE",
        "behavioral_test_count": int(tests["provenance_class"].eq("BEHAVIORAL").sum()),
        "static_assertion_count": int(tests["provenance_class"].eq("STATIC_AUTHORITY").sum()),
        "contract_combination_count": int(tests["provenance_class"].eq("CONTRACT_COMBINATION").sum()),
        "behavioral_failures": int(((tests["provenance_class"] == "BEHAVIORAL") & (tests["result"] != "PASS")).sum()),
        "required_payload_roles": sorted(required),
        "execution_state": "VALIDATION_COMPLETE_NO_SCIENTIFIC_EXECUTION",
    }


def publish_validation_generation(project_root: Path, directory: Path,
                                  payloads: Mapping[str, bytes],
                                  fail_after: int | None = None) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    staged = {name: bytes(content) for name, content in payloads.items()}
    metadata = _validation_generation_metadata(root, staged)
    entries = {name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "role": name}
               for name, content in staged.items()}
    generation_id = hashlib.sha256(canonical_json({"metadata": metadata, "payloads": entries})).hexdigest()
    manifest = {**metadata, "generation_id": generation_id, "payloads": entries,
                "publication_protocol": "PAYLOADS_THEN_MARKER_LAST"}
    directory = Path(directory)
    for index, name in enumerate(G06_2C_GENERATION_AUTHORITY.required_payloads, start=1):
        _atomic_bytes(directory / name, staged[name])
        if fail_after == index:
            raise ContractError("ERR_INJECTED_PUBLICATION_FAILURE")
    _atomic_bytes(directory / G06_2C_GENERATION_AUTHORITY.manifest_name, canonical_json(manifest))
    return MappingProxyType(manifest)


def validate_validation_generation(project_root: Path, directory: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    directory = Path(directory)
    marker = directory / G06_2C_GENERATION_AUTHORITY.manifest_name
    if not marker.is_file():
        raise ContractError("ERR_GENERATION_MARKER_MISSING")
    manifest = json.loads(marker.read_text(encoding="ascii"))
    declared = manifest.get("payloads", {})
    required = set(G06_2C_GENERATION_AUTHORITY.required_payloads)
    if set(declared) != required:
        if required - set(declared):
            raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_MISSING")
        raise ContractError("ERR_GENERATION_UNEXPECTED_PAYLOAD")
    payloads: dict[str, bytes] = {}
    for name in G06_2C_GENERATION_AUTHORITY.required_payloads:
        path = directory / name
        if not path.is_file():
            raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_MISSING")
        raw = path.read_bytes()
        identity = declared[name]
        if identity.get("role") != name or identity.get("bytes") != len(raw) or identity.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise ContractError("ERR_GENERATION_PAYLOAD_IDENTITY")
        payloads[name] = raw
    extras = {path.name for path in directory.iterdir()
              if path.is_file() and path.name.startswith("PAPER1_G06_2C_")} - required - {marker.name}
    if extras:
        raise ContractError("ERR_GENERATION_UNEXPECTED_PAYLOAD")
    metadata = _validation_generation_metadata(root, payloads)
    for field, expected in metadata.items():
        if manifest.get(field) != expected:
            raise ContractError(f"ERR_GENERATION_{field.upper()}")
    expected_generation = hashlib.sha256(canonical_json({"metadata": metadata, "payloads": declared})).hexdigest()
    if manifest.get("generation_id") != expected_generation:
        raise ContractError("ERR_GENERATION_IDENTITY")
    if manifest.get("publication_protocol") != "PAYLOADS_THEN_MARKER_LAST":
        raise ContractError("ERR_GENERATION_PUBLICATION_PROTOCOL")
    return MappingProxyType(manifest)


def publish_generation(*_args, **_kwargs):
    """Reject the superseded caller-defined G06.2b generation interface."""
    raise ContractError("ERR_SUPERSEDED_CALLER_ORACLE_API")


def validate_generation(*_args, **_kwargs):
    """Reject the superseded expected_metadata generation interface."""
    raise ContractError("ERR_SUPERSEDED_CALLER_ORACLE_API")


def assert_runtime_authority_immutable() -> None:
    for authority in (OUTCOME_AUTHORITIES, PREDICTOR_AUTHORITIES, SUPPORT_AUTHORITIES,
                      METRIC_AUTHORITIES, OUTER_EVALUATIONS):
        try:
            authority["MUTATION"] = "FORBIDDEN"  # type: ignore[index]
        except TypeError:
            continue
        raise ContractError("ERR_RUNTIME_AUTHORITY_MUTABLE")


# G06.2d correction layer. The definitions below replace the rejected G06.2c
# production bindings while retaining its verified prediction, RF, and metric
# mechanics in this implementation module.

ENVIRONMENT_SCHEMA_VERSION = "PAPER1_G06.2D_ENVIRONMENT_RECEIPT_V1"
RUN_CONTEXT_SCHEMA_VERSION = "PAPER1_G06.2D_RUN_CONTEXT_V1"
EXECUTION_UNIVERSE_SCHEMA_VERSION = "PAPER1_G06.2D_EXECUTION_UNIVERSE_V1"
VALIDATED_TEST_RUN_SCHEMA_VERSION = "PAPER1_G06.2D_VALIDATED_TEST_RUN_V1"
G05B_BOUNDARY_SOURCE = "documentation/PAPER1_G05B_BOUNDARY_SUPPORT_QC.csv"
G05B_BOUNDARY_SOURCE_SHA256 = "9b67db7096231b3709529c1edcad14a2903b46988738c5087c03101f44e7b094"
G04B_FRACTIONAL_MANIFEST = "data/processed/propagation/paper1/g04b_fractional_response/g04b_manifest.json"
G04B_FRACTIONAL_MANIFEST_SHA256 = "9db7b24914f9e627dc02b9c692b56dcd71bd36ecd0908d63fb716bdf12088b20"


@dataclass(frozen=True)
class AuthenticatedSupportArtifact:
    project_root: str
    relative_path: str
    observed_sha256: str
    contract_sha256: str
    authentication_result: str = "PASS"


@dataclass(frozen=True)
class AuthenticatedPredictorData:
    handle: AuthenticatedPredictorArtifact
    contract_sha256: str
    columns: tuple[str, ...]
    dtypes: tuple[str, ...]
    records: tuple[tuple[object, ...], ...]
    content_sha256: str
    row_count: int
    canonical_key_sha256: str

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame.from_records(self.records, columns=self.columns)


@dataclass(frozen=True)
class AuthenticatedEnvironmentReceipt:
    schema_version: str
    gate_version: str
    git_head: str
    execution_contract_sha256: str
    dependency_name: str
    required_specification: str
    observed_version: str
    probe_mechanism: str
    interpreter_identity: str
    requirement_authority: str
    requirement_authority_sha256: str
    status: str
    receipt_sha256: str


@dataclass(frozen=True)
class RunContext:
    schema_version: str
    api_identity: str
    run_id: str
    generation_id: str
    git_head: str
    environment_identity: str
    environment_receipt_sha256: str
    execution_contract_sha256: str
    runtime_source_sha256: str


@dataclass(frozen=True)
class TerminalEvidence:
    reason_code: TerminalReasonCode
    semantic_class: str
    authority_source: str
    authority_expected_sha256: str
    authority_observed_sha256: str
    analysis_id: str
    evaluation_identity: str
    evidence: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class GovernedExecutionUniverse:
    schema_version: str
    gate_version: str
    git_head: str
    scope_identity: str
    unit_ids: tuple[str, ...]
    contract_sha256s: tuple[tuple[str, str], ...]
    executable_unit_count: int
    disabled_unit_count: int
    authority_sha256: str


@dataclass(frozen=True)
class BehavioralTestSpec:
    test_id: str
    category: str
    requirement: str
    callable_identity: str
    required: bool = True


@dataclass(frozen=True)
class ValidatedTestRun:
    schema_version: str
    gate_version: str
    git_head: str
    runtime_source_sha256: str
    facade_source_sha256: str
    validator_source_sha256: str
    behavioral_universe_sha256: str
    static_universe_sha256: str
    behavioral_results: tuple[tuple[str, str, str], ...]
    static_results: tuple[tuple[str, str, str], ...]
    integration_results: tuple[tuple[str, str, str], ...]
    contract_combination_count: int
    execution_identity: str
    status: str
    receipt_sha256: str


@dataclass(frozen=True)
class ValidatedGenerationPayloads:
    schema_version: str
    gate_version: str
    git_head: str
    validator_source_sha256: str
    validated_test_run_receipt_sha256: str
    payloads: tuple[tuple[str, bytes], ...]
    payload_sha256s: tuple[tuple[str, str], ...]
    receipt_sha256: str


_FRACTIONAL_FIELDS = (*KEY_FIELDS, "interval_number", "fractional_newly_covered")
FRACTIONAL_OUTCOME_AUTHORITY = OutcomeAuthority(
    "data/processed/propagation/paper1/g04b_fractional_response/outputs/paper1_g04b_fractional_newly_covered_1km.parquet",
    "666c4c786a3fa4fb797a023bf528fa15ff8d4fbdd30a67c9bbfcc2b250ee7d93",
    3317,
    "dbfbb3cae3a0b0d3bfebfe6718820d3cd3e228136cc115a1a79a5b46c54eaceb",
    G04B_FRACTIONAL_MANIFEST,
    G04B_FRACTIONAL_MANIFEST_SHA256,
    "PRIMARY_HYBRID",
    1000,
    "fractional_newly_covered",
    "CONTINUOUS_UNIT_INTERVAL",
    "3c6b91a660f7c4731b99d59153c0ed6cd611fa3bf4d5de2b5be9266517786bb7",
    _FRACTIONAL_FIELDS,
)
ALL_OUTCOME_AUTHORITIES = MappingProxyType({
    **{(risk, resolution, "y"): authority for (risk, resolution), authority in OUTCOME_AUTHORITIES.items()},
    ("PRIMARY_HYBRID", 1000, "fractional_newly_covered"): FRACTIONAL_OUTCOME_AUTHORITY,
})


def canonical_key_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return _canonical_key_frame(frame)


def key_sha256(frame: pd.DataFrame) -> str:
    return _frame_hash(frame, KEY_FIELDS)


def _dataframe_content_sha256(frame: pd.DataFrame) -> str:
    metadata = canonical_json({"columns": list(frame.columns), "dtypes": [str(v) for v in frame.dtypes]})
    values = pd.util.hash_pandas_object(frame, index=False).to_numpy(dtype="uint64").tobytes()
    return hashlib.sha256(metadata + values).hexdigest()


def authenticate_outcome_artifact(project_root: Path, risk_set_id: str, resolution_m: int,
                                  supplied_path: Path | None = None,
                                  response_field: str = "y") -> AuthenticatedOutcomeArtifact:
    root = Path(project_root).resolve()
    authority = ALL_OUTCOME_AUTHORITIES.get((risk_set_id, int(resolution_m), response_field))
    if authority is None:
        raise ContractError("ERR_OUTCOME_AUTHORITY")
    governed = (root / authority.relative_path).resolve()
    if supplied_path is not None and Path(supplied_path).resolve() != governed:
        raise ContractError("ERR_CALLER_OUTCOME_SUBSTITUTION")
    _verify_authority_file(root, authority.authority_manifest, authority.authority_manifest_sha256,
                           "ERR_OUTCOME_AUTHORITY_MANIFEST")
    _verify_authority_file(root, authority.relative_path, authority.expected_sha256, "ERR_OUTCOME_FILE_HASH")
    columns = tuple(authority.schema_columns)
    frame = pd.read_parquet(governed, columns=list(columns))
    if tuple(frame.columns) != columns or len(frame) != authority.row_count:
        raise ContractError("ERR_OUTCOME_SCHEMA_OR_ROW_COUNT")
    if not frame["response_grid_m"].eq(authority.resolution_m).all():
        raise ContractError("ERR_OUTCOME_RESOLUTION")
    values = pd.to_numeric(frame[authority.response_field], errors="coerce").to_numpy(float)
    if not np.isfinite(values).all():
        raise ContractError("ERR_OUTCOME_DOMAIN")
    if authority.response_domain == "BINARY_0_1" and not frame[authority.response_field].isin([0, 1]).all():
        raise ContractError("ERR_OUTCOME_DOMAIN")
    if authority.response_domain == "CONTINUOUS_UNIT_INTERVAL" and ((values < 0.0) | (values > 1.0)).any():
        raise ContractError("ERR_OUTCOME_DOMAIN")
    key_hash = _frame_hash(frame, KEY_FIELDS)
    map_hash = _frame_hash(frame, columns)
    if key_hash != authority.canonical_key_sha256 or map_hash != authority.key_interval_response_sha256:
        raise ContractError("ERR_OUTCOME_KEY_INTERVAL_VALUE_HASH")
    ordered = frame.sort_values(list(KEY_FIELDS), kind="stable")
    rows = tuple(
        OutcomeRow(str(row.event_id), str(row.interval_id), int(row.response_grid_m), str(row.cell_id),
                   int(row.interval_number), float(getattr(row, authority.response_field)))
        for row in ordered.itertuples(index=False)
    )
    return AuthenticatedOutcomeArtifact(str(root), authority, sha256_file(governed), len(frame),
                                        key_hash, map_hash, rows)


def authenticate_outcome_for_contract(project_root: Path,
                                      contract: ExecutionContract) -> AuthenticatedOutcomeArtifact:
    field = "fractional_newly_covered" if contract.analysis_id == "G05B_FRACTIONAL_RESPONSE" else "y"
    handle = authenticate_outcome_artifact(project_root, contract.risk_set_id, contract.resolution_m,
                                           response_field=field)
    _validate_outcome_contract(handle, contract)
    return handle


def _verify_handle(handle: AuthenticatedOutcomeArtifact) -> AuthenticatedOutcomeArtifact:
    if not isinstance(handle, AuthenticatedOutcomeArtifact) or handle.authentication_result != "PASS":
        raise ContractError("ERR_OUTCOME_HANDLE_TYPE")
    refreshed = authenticate_outcome_artifact(
        Path(handle.project_root), handle.authority.risk_set_id, handle.authority.resolution_m,
        Path(handle.project_root) / handle.authority.relative_path, handle.authority.response_field,
    )
    if refreshed != handle:
        raise ContractError("ERR_OUTCOME_HANDLE_BINDING")
    return refreshed


def _validate_outcome_contract(handle: AuthenticatedOutcomeArtifact, contract: ExecutionContract) -> None:
    _verify_handle(handle)
    if (handle.authority.risk_set_id != contract.risk_set_id or
            handle.authority.resolution_m != contract.resolution_m or
            handle.authority.relative_path != contract.response_path or
            handle.observed_sha256 != contract.response_sha256 or
            handle.observed_key_sha256 != contract.response_key_sha256 or
            handle.observed_key_interval_response_sha256 != contract.response_key_interval_value_sha256):
        raise ContractError("ERR_OUTCOME_CONTRACT_IDENTITY")


def authenticate_support_artifact(project_root: Path,
                                  contract: ExecutionContract) -> AuthenticatedSupportArtifact:
    root = Path(project_root).resolve()
    validate_execution_contract(root, contract)
    path = _verify_authority_file(root, contract.support_path, contract.support_sha256,
                                  "ERR_SUPPORT_FILE_HASH")
    return AuthenticatedSupportArtifact(str(root), contract.support_path, sha256_file(path),
                                        contract.contract_sha256)


def _verify_support_handle(handle: AuthenticatedSupportArtifact,
                           contract: ExecutionContract) -> AuthenticatedSupportArtifact:
    if not isinstance(handle, AuthenticatedSupportArtifact) or handle.authentication_result != "PASS":
        raise ContractError("ERR_SUPPORT_HANDLE_TYPE")
    refreshed = authenticate_support_artifact(Path(handle.project_root), contract)
    if refreshed != handle:
        raise ContractError("ERR_SUPPORT_HANDLE_BINDING")
    return refreshed


def load_authenticated_predictors(handle: AuthenticatedPredictorArtifact,
                                  contract: ExecutionContract) -> AuthenticatedPredictorData:
    refreshed = _verify_predictor_handle(handle)
    validate_execution_contract(Path(handle.project_root), contract)
    if (handle.risk_set_id != contract.risk_set_id or handle.resolution_m != contract.resolution_m or
            handle.authority.relative_path != contract.predictor_path or
            handle.observed_sha256 != contract.predictor_sha256 or
            handle.observed_key_sha256 != contract.predictor_key_sha256):
        raise ContractError("ERR_PREDICTOR_CONTRACT_IDENTITY")
    frame = pd.read_parquet(Path(handle.project_root) / handle.authority.relative_path)
    forbidden = {"y", "response_y", "fractional_newly_covered"}.intersection(frame.columns)
    if forbidden:
        raise ContractError("ERR_PREDICTOR_RESPONSE_LEAKAGE")
    if len(frame) != refreshed.observed_row_count or _frame_hash(frame, KEY_FIELDS) != refreshed.observed_key_sha256:
        raise ContractError("ERR_PREDICTOR_HANDOFF_KEY_UNIVERSE")
    return AuthenticatedPredictorData(
        refreshed, contract.contract_sha256, tuple(frame.columns), tuple(str(v) for v in frame.dtypes),
        tuple(tuple(row) for row in frame.itertuples(index=False, name=None)),
        _dataframe_content_sha256(frame), len(frame), refreshed.observed_key_sha256,
    )


def validate_authenticated_predictor_data(data: AuthenticatedPredictorData,
                                          contract: ExecutionContract) -> None:
    if not isinstance(data, AuthenticatedPredictorData):
        raise ContractError("ERR_PREDICTOR_DATA_HANDLE_TYPE")
    expected = load_authenticated_predictors(data.handle, contract)
    metadata_equal = (
        data.handle == expected.handle and
        data.contract_sha256 == expected.contract_sha256 and
        data.columns == expected.columns and
        data.dtypes == expected.dtypes and
        data.content_sha256 == expected.content_sha256 and
        data.row_count == expected.row_count and
        data.canonical_key_sha256 == expected.canonical_key_sha256 and
        len(data.records) == len(expected.records)
    )
    records_equal = metadata_equal and all(
        len(observed) == len(authoritative) and all(
            (pd.isna(left) and pd.isna(right)) or left == right
            for left, right in zip(observed, authoritative)
        )
        for observed, authoritative in zip(data.records, expected.records)
    )
    if not records_equal:
        raise ContractError("ERR_PREDICTOR_DATA_BINDING")


_g06c_governed_execution_contract = governed_execution_contract


def _g05b_row(root: Path, analysis_id: str) -> pd.Series:
    _verify_authority_file(root, G05B_REGISTRY_SOURCE, G05B_REGISTRY_SOURCE_SHA256,
                           "ERR_G05B_REGISTRY_AUTHORITY")
    registry = pd.read_csv(root / G05B_REGISTRY_SOURCE)
    matches = registry.loc[registry["analysis_id"].eq(analysis_id)]
    if len(matches) != 1 or not str(matches.iloc[0]["executable_status"]).startswith("EXECUTABLE"):
        raise ContractError("ERR_CONTRACT_ANALYSIS")
    return matches.iloc[0]


def _symmetric_intervals(analysis_id: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    blocks = {
        "B1": (1, 3, 4, 5), "B2": (6, 8, 9, 10),
        "B3": (11, 12, 14, 15), "B4": (16, 18, 21, 22),
    }
    block = next((name for name in blocks if f"_{name}_HELDOUT" in analysis_id), None)
    if block is None:
        raise ContractError("ERR_CONTRACT_EVALUATION")
    training = tuple(value for name, values in blocks.items() if name != block for value in values)
    return f"SYMMETRIC_{block}_HELDOUT", training, blocks[block]


def _g05b_contract_values(root: Path, analysis_id: str, model_family: str,
                          model_role: str, evaluation_identity: str) -> Mapping[str, object]:
    row = _g05b_row(root, analysis_id)
    if analysis_id.startswith("G05B_BOUNDARY_") or analysis_id == "G05B_FRACTIONAL_RESPONSE":
        if evaluation_identity not in OUTER_EVALUATIONS:
            raise ContractError("ERR_CONTRACT_EVALUATION")
        training, heldout = OUTER_EVALUATIONS[evaluation_identity]
    elif analysis_id.startswith("G05B_SYMMETRIC_CV_"):
        expected, training, heldout = _symmetric_intervals(analysis_id)
        if evaluation_identity != expected:
            raise ContractError("ERR_CONTRACT_EVALUATION")
    elif analysis_id == "G05B_LOIO_PRIMARY_FORWARD":
        if (model_family, model_role, evaluation_identity) != (
                "DIAGNOSTIC_NO_REFIT", "paired_delta", "LOIO_PRIMARY_FORWARD"):
            raise ContractError("ERR_CONTRACT_MODEL_ROLE")
        training, heldout = (), tuple(value for values in OUTER_EVALUATIONS.values() for value in values[1])
    else:
        raise ContractError("ERR_CONTRACT_ANALYSIS")
    if analysis_id == "G05B_FRACTIONAL_RESPONSE":
        allowed = {("FRACTIONAL_LOGIT_GLM", "baseline"), ("FRACTIONAL_LOGIT_GLM", "augmented")}
        outcome = FRACTIONAL_OUTCOME_AUTHORITY
    elif analysis_id == "G05B_LOIO_PRIMARY_FORWARD":
        allowed = {("DIAGNOSTIC_NO_REFIT", "paired_delta")}
        outcome = OUTCOME_AUTHORITIES[("PRIMARY_HYBRID", 1000)]
    else:
        allowed = {(family, role) for family in ("L2_LOGISTIC", "RANDOM_FOREST")
                   for role in ("baseline", "augmented")}
        outcome = OUTCOME_AUTHORITIES[("PRIMARY_HYBRID", 1000)]
    if (model_family, model_role) not in allowed:
        raise ContractError("ERR_CONTRACT_MODEL_ROLE")
    predictor = PREDICTOR_AUTHORITIES[("PRIMARY_HYBRID", 1000)]
    support_path, support_hash, support_manifest, support_manifest_hash = SUPPORT_AUTHORITIES[("PRIMARY_HYBRID", 1000)]
    _verify_authority_file(root, support_manifest, support_manifest_hash, "ERR_SUPPORT_AUTHORITY_MANIFEST")
    _verify_authority_file(root, support_path, support_hash, "ERR_SUPPORT_FILE_HASH")
    special = "NONE"
    if analysis_id == "G05B_BOUNDARY_1000" and evaluation_identity == "B1_TO_B2":
        special = "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE"
    elif analysis_id == "G05B_FRACTIONAL_RESPONSE":
        special = "STATSMODELS_0.14.6_ENVIRONMENT_REQUIRED"
    elif analysis_id == "G05B_LOIO_PRIMARY_FORWARD":
        special = "NO_REFIT_DIAGNOSTIC_CONSUMES_AUTHENTICATED_OOF"
    return {
        "schema_version": EXECUTION_SCHEMA_VERSION, "git_head": _git_head(root),
        "analysis_id": analysis_id, "analysis_family": str(row["family"]),
        "comparator_identity": "SPECIALIZED_G05B", "model_family": model_family,
        "model_role": model_role, "risk_set_id": "PRIMARY_HYBRID", "resolution_m": 1000,
        "evaluation_identity": evaluation_identity, "training_intervals": tuple(training),
        "heldout_intervals": tuple(dict.fromkeys(heldout)),
        "predictor_path": predictor.relative_path, "predictor_sha256": predictor.expected_sha256,
        "predictor_key_sha256": predictor.canonical_key_sha256,
        "support_identity": str(row["support_universe"]), "support_path": support_path,
        "support_sha256": support_hash, "response_path": outcome.relative_path,
        "response_sha256": outcome.expected_sha256, "response_key_sha256": outcome.canonical_key_sha256,
        "response_key_interval_value_sha256": outcome.key_interval_response_sha256,
        "preprocessing_identity": str(row["logistic_policy"]),
        "tuning_identity": str(row["random_forest_policy"]),
        "governed_seeds": RF_SEEDS if model_family == "RANDOM_FOREST" else (),
        "metric_authority_sha256": METRIC_AUTHORITY_SHA256,
        "uncertainty_authority_sha256": UNCERTAINTY_AUTHORITY_SHA256,
        "environment_requirement": "statsmodels==0.14.6" if analysis_id == "G05B_FRACTIONAL_RESPONSE" else "WILDFIRE_LOCKED_ENVIRONMENT",
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "generation_schema_version": GENERATION_SCHEMA_VERSION,
        "registry_source": G05B_REGISTRY_SOURCE, "registry_sha256": G05B_REGISTRY_SOURCE_SHA256,
        "execution_enabled": True, "special_condition": special,
    }


def governed_execution_contract(project_root: Path, analysis_id: str, model_family: str,
                                 model_role: str, evaluation_identity: str) -> ExecutionContract:
    root = Path(project_root).resolve()
    if analysis_id.startswith("G05B_"):
        values = dict(_g05b_contract_values(root, analysis_id, model_family, model_role,
                                            evaluation_identity))
        return ExecutionContract(**values, contract_sha256=_contract_hash(values))
    return _g06c_governed_execution_contract(root, analysis_id, model_family, model_role,
                                              evaluation_identity)


def governed_execution_contracts(project_root: Path) -> tuple[ExecutionContract, ...]:
    root = Path(project_root).resolve()
    from src import paper1_analysis_registry as registry
    contracts: list[ExecutionContract] = []
    for analysis in registry.registry(root):
        if analysis.executable_status.startswith("EXECUTABLE"):
            for evaluation in OUTER_EVALUATIONS:
                for family in ("L2_LOGISTIC", "RANDOM_FOREST"):
                    for role in ("baseline", "augmented"):
                        contracts.append(governed_execution_contract(root, analysis.analysis_id,
                                                                      family, role, evaluation))
        else:
            contracts.append(governed_execution_contract(root, analysis.analysis_id, "DISABLED",
                                                          "nonexecuting", "NOT_APPLICABLE"))
    g05b = pd.read_csv(root / G05B_REGISTRY_SOURCE)
    for analysis_id in g05b["analysis_id"]:
        if analysis_id.startswith("G05B_BOUNDARY_"):
            evaluations = tuple(OUTER_EVALUATIONS)
            roles = tuple((f, r) for f in ("L2_LOGISTIC", "RANDOM_FOREST") for r in ("baseline", "augmented"))
        elif analysis_id == "G05B_FRACTIONAL_RESPONSE":
            evaluations = tuple(OUTER_EVALUATIONS)
            roles = (("FRACTIONAL_LOGIT_GLM", "baseline"), ("FRACTIONAL_LOGIT_GLM", "augmented"))
        elif analysis_id.startswith("G05B_SYMMETRIC_CV_"):
            evaluations = (_symmetric_intervals(analysis_id)[0],)
            roles = tuple((f, r) for f in ("L2_LOGISTIC", "RANDOM_FOREST") for r in ("baseline", "augmented"))
        else:
            evaluations = ("LOIO_PRIMARY_FORWARD",)
            roles = (("DIAGNOSTIC_NO_REFIT", "paired_delta"),)
        for evaluation in evaluations:
            for family, role in roles:
                contracts.append(governed_execution_contract(root, analysis_id, family, role, evaluation))
    return tuple(contracts)


def validate_execution_contract(project_root: Path, contract: ExecutionContract) -> None:
    expected = governed_execution_contract(project_root, contract.analysis_id, contract.model_family,
                                            contract.model_role, contract.evaluation_identity)
    if contract != expected:
        differing = next(field for field in asdict(expected)
                         if getattr(contract, field) != getattr(expected, field))
        raise ContractError(f"ERR_EXECUTION_CONTRACT_{differing.upper()}")


def _unit_id(contract: ExecutionContract) -> str:
    return "|".join((contract.analysis_id, contract.model_family, contract.model_role,
                     contract.evaluation_identity, str(contract.resolution_m)))


def governed_execution_universe(project_root: Path,
                                scope_identity: str = "PAPER1_ALL_G05") -> GovernedExecutionUniverse:
    if scope_identity != "PAPER1_ALL_G05":
        raise ContractError("ERR_EXECUTION_UNIVERSE_SCOPE")
    root = Path(project_root).resolve()
    contracts = governed_execution_contracts(root)
    pairs = tuple(sorted((_unit_id(contract), contract.contract_sha256) for contract in contracts))
    if len({unit for unit, _ in pairs}) != len(pairs):
        raise ContractError("ERR_EXECUTION_UNIVERSE_DUPLICATE")
    payload = {
        "schema_version": EXECUTION_UNIVERSE_SCHEMA_VERSION, "gate_version": GATE_VERSION,
        "git_head": _git_head(root), "scope_identity": scope_identity,
        "contracts": pairs,
        "executable_unit_count": sum(contract.execution_enabled for contract in contracts),
        "disabled_unit_count": sum(not contract.execution_enabled for contract in contracts),
    }
    return GovernedExecutionUniverse(
        payload["schema_version"], payload["gate_version"], payload["git_head"], scope_identity,
        tuple(unit for unit, _ in pairs), pairs, payload["executable_unit_count"],
        payload["disabled_unit_count"], hashlib.sha256(canonical_json(payload)).hexdigest(),
    )


_ISSUED_ENVIRONMENT_RECEIPTS: dict[int, AuthenticatedEnvironmentReceipt] = {}
_ENVIRONMENT_RECEIPTS_BY_HASH: dict[str, AuthenticatedEnvironmentReceipt] = {}
_ISSUED_RUN_CONTEXTS: dict[int, RunContext] = {}
_ISSUED_VALIDATED_TEST_RUNS: dict[int, ValidatedTestRun] = {}
_ISSUED_GENERATION_PAYLOADS: dict[int, ValidatedGenerationPayloads] = {}


def _environment_receipt_payload(root: Path, contract: ExecutionContract) -> dict[str, object]:
    validate_execution_contract(root, contract)
    requirement = contract.environment_requirement
    if requirement == "statsmodels==0.14.6":
        dependency = "statsmodels"
        try:
            observed = importlib.metadata.version(dependency)
        except importlib.metadata.PackageNotFoundError:
            observed = "ABSENT"
        status = "PASS" if observed == "0.14.6" else "BLOCK"
        mechanism = "importlib.metadata.version('statsmodels')"
    elif requirement == "WILDFIRE_LOCKED_ENVIRONMENT":
        dependency = "python_environment"
        observed = Path(sys.prefix).name
        status = "PASS" if observed.lower() == "wildfire" else "BLOCK"
        mechanism = "pathlib.Path(sys.prefix).name"
    elif requirement == "NOT_APPLICABLE":
        dependency, observed, status, mechanism = "none", "NOT_APPLICABLE", "NOT_APPLICABLE", "none"
    else:
        raise ContractError("ERR_ENVIRONMENT_REQUIREMENT_UNKNOWN")
    interpreter = hashlib.sha256(
        canonical_json({"executable": str(Path(sys.executable).resolve()),
                        "version": tuple(sys.version_info[:3]), "prefix": str(Path(sys.prefix).resolve())})
    ).hexdigest()
    return {
        "schema_version": ENVIRONMENT_SCHEMA_VERSION, "gate_version": GATE_VERSION,
        "git_head": _git_head(root), "execution_contract_sha256": contract.contract_sha256,
        "dependency_name": dependency, "required_specification": requirement,
        "observed_version": observed, "probe_mechanism": mechanism,
        "interpreter_identity": interpreter, "requirement_authority": contract.registry_source,
        "requirement_authority_sha256": contract.registry_sha256, "status": status,
    }


def probe_environment(project_root: Path,
                      contract: ExecutionContract) -> AuthenticatedEnvironmentReceipt:
    root = Path(project_root).resolve()
    payload = _environment_receipt_payload(root, contract)
    receipt = AuthenticatedEnvironmentReceipt(
        **payload, receipt_sha256=hashlib.sha256(canonical_json(payload)).hexdigest(),
    )
    _ISSUED_ENVIRONMENT_RECEIPTS[id(receipt)] = receipt
    _ENVIRONMENT_RECEIPTS_BY_HASH[receipt.receipt_sha256] = receipt
    return receipt


def validate_environment_receipt(project_root: Path, contract: ExecutionContract,
                                 receipt: AuthenticatedEnvironmentReceipt) -> None:
    if (not isinstance(receipt, AuthenticatedEnvironmentReceipt) or
            _ISSUED_ENVIRONMENT_RECEIPTS.get(id(receipt)) is not receipt):
        raise ContractError("ERR_ENVIRONMENT_RECEIPT_NOT_PROBE_ISSUED")
    payload = _environment_receipt_payload(Path(project_root).resolve(), contract)
    expected = AuthenticatedEnvironmentReceipt(
        **payload, receipt_sha256=hashlib.sha256(canonical_json(payload)).hexdigest(),
    )
    if receipt != expected:
        raise ContractError("ERR_ENVIRONMENT_RECEIPT_BINDING")


def build_authenticated_run_context(project_root: Path, contract: ExecutionContract,
                                    environment: AuthenticatedEnvironmentReceipt,
                                    run_id: str, generation_id: str) -> RunContext:
    root = Path(project_root).resolve()
    validate_execution_contract(root, contract)
    validate_environment_receipt(root, contract, environment)
    if not run_id or not generation_id:
        raise ContractError("ERR_RUN_CONTEXT_IDENTITY")
    runtime_hash = sha256_file(root / "src/paper1_g06_2d_runtime.py")
    context = RunContext(
        RUN_CONTEXT_SCHEMA_VERSION, API_IDENTITY, str(run_id), str(generation_id), _git_head(root),
        environment.receipt_sha256, environment.receipt_sha256, contract.contract_sha256, runtime_hash,
    )
    _ISSUED_RUN_CONTEXTS[id(context)] = context
    return context


def validate_run_context(project_root: Path, contract: ExecutionContract,
                         environment: AuthenticatedEnvironmentReceipt,
                         context: RunContext) -> None:
    root = Path(project_root).resolve()
    if (not isinstance(context, RunContext) or
            _ISSUED_RUN_CONTEXTS.get(id(context)) is not context):
        raise ContractError("ERR_RUN_CONTEXT_NOT_FACTORY_ISSUED")
    expected = build_authenticated_run_context(root, contract, environment,
                                               context.run_id, context.generation_id)
    if context != expected:
        raise ContractError("ERR_RUN_CONTEXT_BINDING")


def _outcome_rows_for_contract(contract: ExecutionContract,
                               outcome: AuthenticatedOutcomeArtifact) -> tuple[OutcomeRow, ...]:
    _validate_outcome_contract(outcome, contract)
    if contract.model_family == "DIAGNOSTIC_NO_REFIT":
        raise ContractError("ERR_PREDICTION_NOT_APPLICABLE")
    rows = tuple(row for row in outcome.rows if row.interval_number in set(contract.heldout_intervals))
    if not rows:
        raise ContractError("ERR_OUTCOME_HELDOUT_EMPTY")
    return rows


def prediction_template(contract: ExecutionContract, outcome: AuthenticatedOutcomeArtifact,
                        context: RunContext, environment: AuthenticatedEnvironmentReceipt,
                        seed: int, probabilities: Sequence[float]) -> pd.DataFrame:
    root = Path(outcome.project_root)
    validate_run_context(root, contract, environment, context)
    if environment.status != "PASS":
        raise ContractError("ERR_ENVIRONMENT_BLOCKED")
    if contract.model_family == "RANDOM_FOREST":
        if seed not in contract.governed_seeds:
            raise ContractError("ERR_PREDICTION_SEED")
    elif seed != 0:
        raise ContractError("ERR_PREDICTION_SEED")
    rows = _outcome_rows_for_contract(contract, outcome)
    values = np.asarray(probabilities, dtype=float)
    if len(values) != len(rows):
        raise ContractError("ERR_PREDICTION_ROW_UNIVERSE")
    records = []
    for row, probability in zip(rows, values):
        records.append({
            "schema_version": PREDICTION_SCHEMA_VERSION, "run_id": context.run_id,
            "generation_id": context.generation_id, "analysis_id": contract.analysis_id,
            "outer_evaluation": contract.evaluation_identity, "model_family": contract.model_family,
            "model_role": contract.model_role, "seed": int(seed), "event_id": row.event_id,
            "interval_id": row.interval_id, "response_grid_m": row.response_grid_m,
            "cell_id": row.cell_id, "interval_number": row.interval_number, "heldout": True,
            "predicted_probability": float(probability), "response_y": row.response_y,
        })
    return pd.DataFrame.from_records(records, columns=PREDICTION_COLUMNS)


def validate_predictions(frame: pd.DataFrame, contract: ExecutionContract,
                         outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                         environment: AuthenticatedEnvironmentReceipt, seed: int) -> pd.DataFrame:
    if tuple(frame.columns) != PREDICTION_COLUMNS or frame.empty:
        raise ContractError("ERR_PREDICTION_SCHEMA_OR_EMPTY")
    validate_run_context(Path(outcome.project_root), contract, environment, context)
    if environment.status != "PASS":
        raise ContractError("ERR_ENVIRONMENT_BLOCKED")
    constants = {
        "schema_version": PREDICTION_SCHEMA_VERSION, "run_id": context.run_id,
        "generation_id": context.generation_id, "analysis_id": contract.analysis_id,
        "outer_evaluation": contract.evaluation_identity, "model_family": contract.model_family,
        "model_role": contract.model_role, "seed": int(seed), "response_grid_m": contract.resolution_m,
    }
    for field, expected in constants.items():
        if not frame[field].eq(expected).all():
            raise ContractError(f"ERR_PREDICTION_IDENTITY_{field.upper()}")
    if frame.loc[:, PREDICTION_KEY].duplicated().any():
        raise ContractError("ERR_PREDICTION_DUPLICATE_KEY")
    probabilities = pd.to_numeric(frame["predicted_probability"], errors="coerce").to_numpy(float)
    if not np.isfinite(probabilities).all() or ((probabilities < 0.0) | (probabilities > 1.0)).any():
        raise ContractError("ERR_PREDICTION_PROBABILITY")
    if not frame["heldout"].map(lambda value: isinstance(value, (bool, np.bool_))).all() or not frame["heldout"].all():
        raise ContractError("ERR_HELDOUT_MEMBERSHIP")
    governed = {row.key: (row.interval_id, row.interval_number, float(row.response_y))
                for row in _outcome_rows_for_contract(contract, outcome)}
    observed_keys = [tuple(row) for row in frame.loc[:, KEY_FIELDS].itertuples(index=False, name=None)]
    if len(observed_keys) != len(governed) or set(observed_keys) != set(governed):
        raise ContractError("ERR_PREDICTION_ROW_UNIVERSE")
    for record, key in zip(frame.itertuples(index=False), observed_keys):
        interval_id, interval_number, response = governed[key]
        if str(record.interval_id) != interval_id:
            raise ContractError("ERR_PREDICTION_INTERVAL_ID_AUTHORITY")
        try:
            observed_interval = int(record.interval_number)
        except (TypeError, ValueError) as exc:
            raise ContractError("ERR_PREDICTION_INTERVAL_NUMBER_AUTHORITY") from exc
        if observed_interval != interval_number:
            raise ContractError("ERR_PREDICTION_INTERVAL_NUMBER_AUTHORITY")
        observed_response = float(record.response_y)
        if not np.isfinite(observed_response) or observed_response != response:
            raise ContractError("ERR_PREDICTION_RESPONSE_AUTHORITY")
    return frame.sort_values(list(PREDICTION_KEY), kind="stable").reset_index(drop=True)


def _prediction_receipt(path: Path, raw: bytes, canonical: pd.DataFrame,
                        contract: ExecutionContract, outcome: AuthenticatedOutcomeArtifact,
                        context: RunContext, seed: int) -> PredictionArtifactReceipt:
    key_hash = hashlib.sha256(
        canonical.loc[:, PREDICTION_KEY].to_csv(index=False, lineterminator="\n").encode("utf-8")
    ).hexdigest()
    # validate_predictions has already established exact key, interval, and
    # response equality. Use the authenticated source mapping identity to avoid
    # CSV parser dtype changes altering the receipt for equivalent 0/1 values.
    outcome_hash = outcome.observed_key_interval_response_sha256
    resolved = Path(path).resolve()
    try:
        relative = str(resolved.relative_to(Path(outcome.project_root).resolve())).replace("\\", "/")
    except ValueError:
        relative = resolved.as_posix()
    return PredictionArtifactReceipt(
        PREDICTION_RECEIPT_SCHEMA_VERSION, relative, hashlib.sha256(raw).hexdigest(), len(raw),
        len(canonical), key_hash, outcome_hash, context.run_id, context.generation_id,
        contract.contract_sha256, contract.analysis_id, contract.evaluation_identity,
        contract.model_family, contract.model_role, int(seed), contract.resolution_m,
        "COMPLETE_MARKER_LAST",
    )


def write_prediction_artifact(path: Path, frame: pd.DataFrame, contract: ExecutionContract,
                              outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                              environment: AuthenticatedEnvironmentReceipt,
                              seed: int) -> AuthenticatedPredictionArtifact:
    canonical = validate_predictions(frame, contract, outcome, context, environment, seed)
    raw = canonical.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode("utf-8")
    receipt = _prediction_receipt(Path(path), raw, canonical, contract, outcome, context, seed)
    _atomic_bytes(Path(path), raw)
    _atomic_bytes(Path(str(path) + ".receipt.json"), canonical_json(asdict(receipt)))
    return read_prediction_artifact(path, contract, outcome, context, environment, seed)


def read_prediction_artifact(path: Path, contract: ExecutionContract,
                             outcome: AuthenticatedOutcomeArtifact, context: RunContext,
                             environment: AuthenticatedEnvironmentReceipt,
                             seed: int) -> AuthenticatedPredictionArtifact:
    validate_run_context(Path(outcome.project_root), contract, environment, context)
    path = Path(path)
    marker = Path(str(path) + ".receipt.json")
    if not path.is_file() or not marker.is_file():
        raise ContractError("ERR_PREDICTION_PUBLICATION_INCOMPLETE")
    raw = path.read_bytes()
    try:
        observed = PredictionArtifactReceipt(**json.loads(marker.read_text(encoding="ascii")))
    except Exception as exc:
        raise ContractError("ERR_PREDICTION_RECEIPT_SCHEMA") from exc
    if observed.artifact_sha256 != hashlib.sha256(raw).hexdigest() or observed.artifact_bytes != len(raw):
        raise ContractError("ERR_PREDICTION_RECEIPT_ARTIFACT_IDENTITY")
    frame = pd.read_csv(path, dtype={
        "schema_version": str, "run_id": str, "generation_id": str, "analysis_id": str,
        "outer_evaluation": str, "model_family": str, "model_role": str,
        "event_id": str, "interval_id": str, "cell_id": str,
    })
    frame["heldout"] = frame["heldout"].map({True: True, False: False, "True": True, "False": False})
    canonical = validate_predictions(frame, contract, outcome, context, environment, seed)
    derived = _prediction_receipt(path, raw, canonical, contract, outcome, context, seed)
    if observed != derived:
        differing = next(field for field in asdict(derived)
                         if getattr(observed, field) != getattr(derived, field))
        raise ContractError(f"ERR_PREDICTION_RECEIPT_{differing.upper()}")
    return AuthenticatedPredictionArtifact(str(Path(outcome.project_root).resolve()), derived.path,
                                           derived, contract, context)


def validate_prediction_receipt(receipt: PredictionArtifactReceipt, path: Path,
                                contract: ExecutionContract, outcome: AuthenticatedOutcomeArtifact,
                                context: RunContext, environment: AuthenticatedEnvironmentReceipt,
                                seed: int) -> None:
    authenticated = read_prediction_artifact(path, contract, outcome, context, environment, seed)
    if receipt != authenticated.receipt:
        raise ContractError("ERR_PREDICTION_RECEIPT_BINDING")


def governed_terminal_evidence(project_root: Path, contract: ExecutionContract,
                               state: ExecutionState,
                               environment: AuthenticatedEnvironmentReceipt | None = None) -> TerminalEvidence:
    root = Path(project_root).resolve()
    validate_execution_contract(root, contract)
    if state is ExecutionState.GOVERNED_NONESTIMABLE:
        if contract.analysis_id != "G05B_BOUNDARY_1000" or contract.evaluation_identity != "B1_TO_B2":
            raise ContractError("ERR_TERMINAL_REASON_SCOPE")
        path = _verify_authority_file(root, G05B_BOUNDARY_SOURCE, G05B_BOUNDARY_SOURCE_SHA256,
                                      "ERR_NONESTIMABILITY_AUTHORITY")
        table = pd.read_csv(path)
        rows = table.loc[(table["analysis_id"] == contract.analysis_id) &
                         (table["evaluation"] == contract.evaluation_identity)]
        if len(rows) != 1:
            raise ContractError("ERR_NONESTIMABILITY_AUTHORITY_ROW")
        row = rows.iloc[0]
        counts = (int(row["training_rows"]), int(row["training_positive"]), int(row["training_negative"]))
        if counts != (452, 0, 452):
            raise ContractError("ERR_NONESTIMABILITY_AUTHORITY_COUNTS")
        return TerminalEvidence(
            TerminalReasonCode.BOUNDARY_1000_B1_ALL_NEGATIVE, "GOVERNED_NONESTIMABLE",
            G05B_BOUNDARY_SOURCE, G05B_BOUNDARY_SOURCE_SHA256, sha256_file(path),
            contract.analysis_id, contract.evaluation_identity,
            (("training_rows", "452"), ("training_positive", "0"), ("training_negative", "452")),
        )
    if state is ExecutionState.ENVIRONMENT_BLOCKED:
        if environment is None:
            raise ContractError("ERR_ENVIRONMENT_RECEIPT_REQUIRED")
        validate_environment_receipt(root, contract, environment)
        if contract.analysis_id != "G05B_FRACTIONAL_RESPONSE" or environment.status != "BLOCK":
            raise ContractError("ERR_TERMINAL_REASON_SCOPE")
        return TerminalEvidence(
            TerminalReasonCode.STATSMODELS_0_14_6_REQUIRED, "ENVIRONMENT_BLOCKED",
            environment.requirement_authority, environment.requirement_authority_sha256,
            environment.requirement_authority_sha256, contract.analysis_id,
            contract.evaluation_identity,
            (("required", environment.required_specification),
             ("observed", environment.observed_version),
             ("environment_receipt_sha256", environment.receipt_sha256)),
        )
    source_hash = sha256_file(root / "src/paper1_g06_2d_runtime.py")
    common = ("src/paper1_g06_2d_runtime.py", source_hash, source_hash,
              contract.analysis_id, contract.evaluation_identity)
    if state is ExecutionState.MACHINE_DISABLED:
        if contract.execution_enabled:
            raise ContractError("ERR_DISABLED_EXECUTABLE_CONTRACT")
        return TerminalEvidence(TerminalReasonCode.DISABLED_BY_FROZEN_REGISTRY,
                                "MACHINE_DISABLED", *common, (("execution_enabled", "false"),))
    if state is ExecutionState.PENDING:
        return TerminalEvidence(TerminalReasonCode.PENDING_NOT_EXECUTED, "PENDING", *common,
                                (("attempted", "false"),))
    if state is ExecutionState.FAILED:
        return TerminalEvidence(TerminalReasonCode.RUNTIME_EXCEPTION, "FAILED_RUNTIME", *common,
                                (("exception_receipt_required", "true"),))
    if state is ExecutionState.COMPLETE:
        return TerminalEvidence(TerminalReasonCode.NONE, "COMPLETE", *common, ())
    raise ContractError("ERR_EXECUTION_STATE_UNKNOWN")


def validate_terminal_evidence(project_root: Path, contract: ExecutionContract,
                               state: ExecutionState, evidence: TerminalEvidence,
                               environment: AuthenticatedEnvironmentReceipt | None = None) -> None:
    expected = governed_terminal_evidence(project_root, contract, state, environment)
    if evidence != expected:
        raise ContractError("ERR_TERMINAL_REASON_AUTHORITY")


def governed_metric_universe_from_terminal(project_root: Path, contract: ExecutionContract,
                                           evidence: TerminalEvidence) -> AuthenticatedMetricUniverse:
    validate_terminal_evidence(project_root, contract, ExecutionState.GOVERNED_NONESTIMABLE,
                               evidence)
    values = dict(evidence.evidence)
    rows = int(values["training_rows"])
    positives = int(values["training_positive"])
    negatives = int(values["training_negative"])
    if rows != positives + negatives:
        raise ContractError("ERR_METRIC_CLASS_COUNT_EVIDENCE")
    identity = hashlib.sha256(canonical_json({
        "analysis_id": contract.analysis_id, "evaluation": contract.evaluation_identity,
        "rows": rows, "positives": positives, "negatives": negatives,
        "authority": evidence.authority_observed_sha256,
    })).hexdigest()
    return AuthenticatedMetricUniverse(contract.analysis_id, contract.evaluation_identity,
                                       rows, positives, negatives, identity,
                                       f"{evidence.authority_source}@{evidence.authority_observed_sha256}")


def _validate_contract_inputs(project_root: Path, contract: ExecutionContract,
                              predictor: AuthenticatedPredictorArtifact,
                              outcome: AuthenticatedOutcomeArtifact,
                              support: AuthenticatedSupportArtifact,
                              context: RunContext,
                              environment: AuthenticatedEnvironmentReceipt) -> None:
    root = Path(project_root).resolve()
    validate_execution_contract(root, contract)
    refreshed_predictor = _verify_predictor_handle(predictor)
    if (refreshed_predictor.risk_set_id != contract.risk_set_id or
            refreshed_predictor.resolution_m != contract.resolution_m or
            refreshed_predictor.authority.relative_path != contract.predictor_path or
            refreshed_predictor.observed_sha256 != contract.predictor_sha256 or
            refreshed_predictor.observed_key_sha256 != contract.predictor_key_sha256):
        raise ContractError("ERR_INPUT_PREDICTOR_CONTRACT_IDENTITY")
    _validate_outcome_contract(outcome, contract)
    _verify_support_handle(support, contract)
    validate_run_context(root, contract, environment, context)


def build_run_receipt(project_root: Path, contract: ExecutionContract,
                      predictor: AuthenticatedPredictorArtifact,
                      outcome: AuthenticatedOutcomeArtifact,
                      support: AuthenticatedSupportArtifact,
                      context: RunContext,
                      environment: AuthenticatedEnvironmentReceipt,
                      state: ExecutionState, evidence: TerminalEvidence,
                      prediction: AuthenticatedPredictionArtifact | None = None) -> RunReceipt:
    root = Path(project_root).resolve()
    _validate_contract_inputs(root, contract, predictor, outcome, support, context, environment)
    validate_terminal_evidence(root, contract, state, evidence, environment)
    if state is ExecutionState.COMPLETE:
        if prediction is None:
            raise ContractError("ERR_COMPLETE_WITHOUT_PREDICTION")
        refreshed = read_prediction_artifact(
            root / prediction.relative_path, contract, outcome, context, environment,
            prediction.receipt.seed,
        )
        if refreshed != prediction:
            raise ContractError("ERR_RUN_PREDICTION_HANDLE_BINDING")
        prediction_path, prediction_hash = refreshed.relative_path, refreshed.receipt.artifact_sha256
    else:
        if prediction is not None:
            raise ContractError("ERR_NONCOMPLETE_WITH_PREDICTION")
        prediction_path = prediction_hash = ""
    return RunReceipt(
        RUN_RECEIPT_SCHEMA_VERSION, GATE_VERSION, context.run_id, context.generation_id,
        context.git_head, contract.contract_sha256, contract.analysis_id, contract.model_family,
        contract.model_role, contract.evaluation_identity, contract.resolution_m,
        predictor.authority.relative_path, predictor.observed_sha256, predictor.observed_key_sha256,
        support.relative_path, support.observed_sha256, outcome.authority.relative_path,
        outcome.observed_sha256, outcome.observed_key_interval_response_sha256,
        contract.preprocessing_identity, contract.tuning_identity, contract.governed_seeds,
        environment.receipt_sha256, prediction_path, prediction_hash, state, evidence.reason_code,
        f"{evidence.authority_source}@{evidence.authority_observed_sha256}",
        state is not ExecutionState.COMPLETE,
    )


def validate_run_receipt(project_root: Path, receipt: RunReceipt,
                         contract: ExecutionContract,
                         predictor: AuthenticatedPredictorArtifact,
                         outcome: AuthenticatedOutcomeArtifact,
                         support: AuthenticatedSupportArtifact,
                         context: RunContext,
                         environment: AuthenticatedEnvironmentReceipt,
                         evidence: TerminalEvidence,
                         prediction: AuthenticatedPredictionArtifact | None = None) -> None:
    expected = build_run_receipt(project_root, contract, predictor, outcome, support, context,
                                 environment, receipt.execution_state, evidence, prediction)
    if receipt != expected:
        differing = next(field for field in asdict(expected)
                         if getattr(receipt, field) != getattr(expected, field))
        raise ContractError(f"ERR_RUN_RECEIPT_{differing.upper()}")


def _checkpoint_receipt(project_root: Path, contract: ExecutionContract,
                        predictor: AuthenticatedPredictorArtifact,
                        outcome: AuthenticatedOutcomeArtifact,
                        support: AuthenticatedSupportArtifact,
                        context: RunContext,
                        environment: AuthenticatedEnvironmentReceipt,
                        stage: str, seed: int, payload: bytes,
                        prior_predictions: Sequence[AuthenticatedPredictionArtifact],
                        completion_state: ExecutionState) -> CheckpointReceipt:
    root = Path(project_root).resolve()
    _validate_contract_inputs(root, contract, predictor, outcome, support, context, environment)
    if stage not in CHECKPOINT_STAGES:
        raise ContractError("ERR_CHECKPOINT_STAGE")
    if contract.model_family == "RANDOM_FOREST":
        if seed not in RF_SEEDS:
            raise ContractError("ERR_CHECKPOINT_SEED")
    elif seed != 0:
        raise ContractError("ERR_CHECKPOINT_SEED")
    if completion_state is ExecutionState.COMPLETE and stage != "FINALIZED":
        raise ContractError("ERR_CHECKPOINT_FALSE_COMPLETE")
    prior_hashes: list[str] = []
    for handle in prior_predictions:
        refreshed = read_prediction_artifact(root / handle.relative_path, contract, outcome,
                                             context, environment, handle.receipt.seed)
        if refreshed != handle:
            raise ContractError("ERR_CHECKPOINT_PRIOR_ARTIFACT_BINDING")
        prior_hashes.append(refreshed.receipt.artifact_sha256)
    if completion_state is ExecutionState.COMPLETE and not prior_hashes:
        raise ContractError("ERR_CHECKPOINT_FALSE_COMPLETE")
    return CheckpointReceipt(
        CHECKPOINT_SCHEMA_VERSION, context.run_id, context.generation_id, context.git_head,
        contract.contract_sha256, contract.analysis_id, contract.model_family, contract.model_role,
        contract.resolution_m, contract.evaluation_identity, contract.training_intervals,
        contract.heldout_intervals, predictor.observed_sha256, support.observed_sha256,
        outcome.observed_sha256, outcome.observed_key_interval_response_sha256,
        contract.preprocessing_identity, contract.tuning_identity, environment.receipt_sha256,
        int(seed), stage, hashlib.sha256(payload).hexdigest(), len(payload), tuple(prior_hashes),
        completion_state,
    )


def write_checkpoint(path: Path, payload: bytes, project_root: Path,
                     contract: ExecutionContract,
                     predictor: AuthenticatedPredictorArtifact,
                     outcome: AuthenticatedOutcomeArtifact,
                     support: AuthenticatedSupportArtifact,
                     context: RunContext,
                     environment: AuthenticatedEnvironmentReceipt,
                     stage: str, seed: int,
                     prior_predictions: Sequence[AuthenticatedPredictionArtifact] = (),
                     completion_state: ExecutionState = ExecutionState.PENDING) -> CheckpointReceipt:
    receipt = _checkpoint_receipt(project_root, contract, predictor, outcome, support, context,
                                  environment, stage, seed, payload, prior_predictions, completion_state)
    _atomic_bytes(Path(path), payload)
    marker = asdict(receipt)
    marker["completion_state"] = receipt.completion_state.value
    _atomic_bytes(Path(str(path) + ".checkpoint.json"), canonical_json(marker))
    return receipt


def read_checkpoint(path: Path, project_root: Path, contract: ExecutionContract,
                    predictor: AuthenticatedPredictorArtifact,
                    outcome: AuthenticatedOutcomeArtifact,
                    support: AuthenticatedSupportArtifact,
                    context: RunContext,
                    environment: AuthenticatedEnvironmentReceipt,
                    stage: str, seed: int,
                    prior_predictions: Sequence[AuthenticatedPredictionArtifact] = (),
                    completion_state: ExecutionState = ExecutionState.PENDING) -> tuple[bytes, CheckpointReceipt]:
    path = Path(path)
    marker = Path(str(path) + ".checkpoint.json")
    if not path.is_file() or not marker.is_file():
        raise ContractError("ERR_CHECKPOINT_PUBLICATION_INCOMPLETE")
    payload = path.read_bytes()
    expected = _checkpoint_receipt(project_root, contract, predictor, outcome, support, context,
                                   environment, stage, seed, payload, prior_predictions, completion_state)
    try:
        data = json.loads(marker.read_text(encoding="ascii"))
        data["completion_state"] = ExecutionState(data["completion_state"])
        for field in ("training_intervals", "heldout_intervals", "prior_prediction_sha256s"):
            data[field] = tuple(data[field])
        observed = CheckpointReceipt(**data)
    except Exception as exc:
        raise ContractError("ERR_CHECKPOINT_SCHEMA") from exc
    if observed != expected:
        differing = next(field for field in asdict(expected)
                         if getattr(observed, field) != getattr(expected, field))
        raise ContractError(f"ERR_CHECKPOINT_{differing.upper()}")
    return payload, observed


def validate_manifest_states(project_root: Path, universe: GovernedExecutionUniverse,
                             states: Mapping[str, ExecutionState],
                             evidence: Mapping[str, TerminalEvidence],
                             contracts: Mapping[str, ExecutionContract],
                             environments: Mapping[str, AuthenticatedEnvironmentReceipt | None]) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    expected_universe = governed_execution_universe(root, universe.scope_identity)
    if universe != expected_universe:
        raise ContractError("ERR_EXECUTION_UNIVERSE_BINDING")
    required = set(universe.unit_ids)
    for supplied in (set(states), set(evidence), set(contracts), set(environments)):
        if supplied != required:
            raise ContractError("ERR_MANIFEST_UNIT_SET")
    expected_hashes = dict(universe.contract_sha256s)
    for unit in universe.unit_ids:
        contract = contracts[unit]
        if _unit_id(contract) != unit or contract.contract_sha256 != expected_hashes[unit]:
            raise ContractError("ERR_MANIFEST_CONTRACT_IDENTITY")
        validate_execution_contract(root, contract)
        state = states[unit]
        if not isinstance(state, ExecutionState):
            raise ContractError("ERR_EXECUTION_STATE_UNKNOWN")
        validate_terminal_evidence(root, contract, state, evidence[unit], environments[unit])
    terminal = {ExecutionState.COMPLETE, ExecutionState.ENVIRONMENT_BLOCKED, ExecutionState.FAILED,
                ExecutionState.GOVERNED_NONESTIMABLE, ExecutionState.MACHINE_DISABLED}
    accounting_complete = all(state in terminal for state in states.values())
    executable = [unit for unit in universe.unit_ids if contracts[unit].execution_enabled]
    completed = [unit for unit in executable if states[unit] is ExecutionState.COMPLETE]
    attempted = [unit for unit in executable if states[unit] is not ExecutionState.PENDING]
    return MappingProxyType({
        "accounting_complete": accounting_complete,
        "scientific_execution_attempted": bool(attempted),
        "scientific_execution_units_completed": len(completed),
        "required_executable_units": len(executable),
        "scientific_execution_succeeded": bool(executable) and len(completed) == len(executable),
        "state_counts": MappingProxyType({state.value: sum(value is state for value in states.values())
                                           for state in ExecutionState}),
        "execution_universe_sha256": universe.authority_sha256,
    })


def rf_stability(project_root: Path, seed_metrics: Sequence[RFSeedMetricRecord],
                 outcome: AuthenticatedOutcomeArtifact) -> RFStabilitySummary:
    if len(seed_metrics) != len(RF_SEEDS):
        raise ContractError("ERR_RF_SEED_SET")
    authenticated: list[tuple[AuthenticatedPredictionArtifact, MetricRecord]] = []
    for record in seed_metrics:
        if not isinstance(record, RFSeedMetricRecord) or not isinstance(record.prediction, AuthenticatedPredictionArtifact):
            raise ContractError("ERR_RF_SEED_ARTIFACT_HANDLE")
        handle = record.prediction
        contract = handle.execution_contract
        if contract.model_family != "RANDOM_FOREST":
            raise ContractError("ERR_RF_MODEL_FAMILY")
        environment = _ENVIRONMENT_RECEIPTS_BY_HASH.get(handle.run_context.environment_receipt_sha256)
        if environment is None:
            raise ContractError("ERR_RF_ENVIRONMENT_RECEIPT")
        refreshed = read_prediction_artifact(Path(project_root) / handle.relative_path, contract, outcome,
                                             handle.run_context, environment, handle.receipt.seed)
        if refreshed != handle:
            raise ContractError("ERR_RF_SEED_HANDLE_BINDING")
        validate_metric_record(record.metric, contract, outcome)
        authenticated.append((refreshed, record.metric))
    seeds = tuple(sorted(handle.receipt.seed for handle, _ in authenticated))
    if seeds != RF_SEEDS:
        raise ContractError("ERR_RF_SEED_SET")
    artifacts = tuple(handle.receipt.artifact_sha256 for handle, _ in authenticated)
    if len(set(artifacts)) != len(RF_SEEDS):
        raise ContractError("ERR_RF_SEED_ARTIFACT_DUPLICATE")
    metrics = tuple(metric for _, metric in authenticated)
    for field in ("analysis_id", "model_role", "evaluation_identity", "metric_name",
                  "metric_role", "row_universe_sha256"):
        if len({getattr(metric, field) for metric in metrics}) != 1:
            raise ContractError(f"ERR_RF_METRIC_IDENTITY_{field.upper()}")
    states = {metric.eligibility_status for metric in metrics}
    first = metrics[0]
    ordered = sorted(zip((handle.receipt.seed for handle, _ in authenticated), artifacts, metrics))
    if states == {"DEFINED"}:
        values = tuple(float(metric.value) for _, _, metric in ordered)
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
        return RFStabilitySummary(
            first.analysis_id, first.model_role, first.evaluation_identity, first.metric_name,
            tuple((seed, artifact) for seed, artifact, _ in ordered),
            tuple((seed, float(metric.value)) for seed, _, metric in ordered),
            mean, min(values), max(values), max(values) - min(values), math.sqrt(variance),
            5, 0, RF_SD_CONVENTION, "DEFINED", "",
        )
    if states == {"UNDEFINED_SINGLE_CLASS"} and {metric.reason_code for metric in metrics} == {"HELDOUT_UNIT_SINGLE_CLASS"}:
        return RFStabilitySummary(
            first.analysis_id, first.model_role, first.evaluation_identity, first.metric_name,
            tuple((seed, artifact) for seed, artifact, _ in ordered), None,
            None, None, None, None, None, 5, 0, RF_SD_CONVENTION,
            "NOT_DEFINED", "HELDOUT_UNIT_SINGLE_CLASS",
        )
    raise ContractError("ERR_RF_METRIC_MIXED_ELIGIBILITY")


_BEHAVIORAL_IDS = (
    "API-FACADE-EXPLICIT", "API-LEGACY-DISABLED", "PREDICTOR-HANDOFF-VALID",
    "PREDICTOR-RAW-DATAFRAME", "PREDICTOR-WRONG-CONTRACT", "PREDICTOR-WRONG-RESOLUTION",
    "PREDICTOR-WRONG-VALUES", "PREDICTOR-WRONG-SOURCE", "PREDICTOR-STALE-HANDLE",
    "PREDICTOR-BYTE-IDENTITY-MUTATED", "PREDICTOR-SUBSTITUTED-PATH",
    "OUTCOME-BINARY-AUTH", "OUTCOME-FRACTIONAL-AUTH", "OUTCOME-Y-MUTATION",
    "PREDICTION-INTERVAL-AUTH", "PREDICTION-RESPONSE-AUTH", "PREDICTION-RECEIPT-BYTES",
    "PREDICTION-RECEIPT-FORGED", "CONTRACT-FORGED", "ENVIRONMENT-PROBE-VALID",
    "ENVIRONMENT-NOT-INSTALLED", "ENVIRONMENT-BANANA", "ENVIRONMENT-FALSE-VERSION",
    "ENVIRONMENT-WRONG-DEPENDENCY", "ENVIRONMENT-WRONG-ANALYSIS", "ENVIRONMENT-STALE",
    "ENVIRONMENT-ABSENT-AS-PRESENT", "ENVIRONMENT-PRESENT-AS-ABSENT",
    "ENVIRONMENT-CALLER-BUILT", "ENVIRONMENT-MUTATED", "CONTEXT-FACTORY-VALID",
    "CONTEXT-FAKE-DIRECT", "CONTEXT-WRONG-CONTRACT", "CONTEXT-WRONG-HEAD",
    "CONTEXT-BANANA", "CONTEXT-WRONG-CONTRACT-HASH", "CONTEXT-STALE-GENERATION",
    "CONTEXT-COPIED-ID-ALTERED", "NONESTIMABILITY-VALID", "NONESTIMABILITY-WRONG-COUNT",
    "NONESTIMABILITY-WRONG-EVALUATION", "NONESTIMABILITY-SOURCE-PATH",
    "NONESTIMABILITY-EXPECTED-HASH", "NONESTIMABILITY-OBSERVED-HASH",
    "NONESTIMABILITY-WRONG-ANALYSIS", "NONESTIMABILITY-NO-SOURCE-RECEIPT",
    "RUN-RECEIPT-VALID", "RUN-RECEIPT-WRONG-OUTCOME", "RUN-RECEIPT-WRONG-PREDICTOR",
    "RUN-RECEIPT-FAKE-CONTEXT", "RUN-RECEIPT-WRONG-ENVIRONMENT",
    "RUN-RECEIPT-WRONG-CONTRACT", "RUN-RECEIPT-WRONG-SUPPORT",
    "RUN-RECEIPT-STALE-PREDICTION", "CHECKPOINT-VALID", "CHECKPOINT-WRONG-OUTCOME",
    "CHECKPOINT-WRONG-PREDICTOR", "CHECKPOINT-FAKE-CONTEXT", "CHECKPOINT-WRONG-ENVIRONMENT",
    "CHECKPOINT-WRONG-SUPPORT", "CHECKPOINT-WRONG-CONTRACT", "CHECKPOINT-WRONG-SEED",
    "CHECKPOINT-WRONG-STAGE", "CHECKPOINT-STALE-PRIOR", "CHECKPOINT-WRONG-HEAD",
    "CHECKPOINT-CORRUPT", "UNIVERSE-AUTHORITY", "UNIVERSE-MISSING-UNIT",
    "UNIVERSE-EXTRA-UNIT", "UNIVERSE-DUPLICATE-UNIT", "UNIVERSE-WRONG-CONTRACT",
    "UNIVERSE-EXECUTABLE-DISABLED", "G05B-BOUNDARY-PREDICTION",
    "G05B-FRACTIONAL-OUTCOME", "G05B-SYMMETRIC-CONTRACT", "DISABLED-ONLY-NOT-SUCCESS",
    "RF-FIVE-AUTHENTIC", "RF-INVENTED-HASH", "RF-SD-DDOF0", "METRIC-ROLES",
    "METRIC-SINGLE-CLASS", "METRIC-DENOMINATOR", "GENERATION-ARBITRARY-LEDGER",
    "GENERATION-TEN-PASS-LEDGER", "GENERATION-FULL-FABRICATED-LEDGER",
    "GENERATION-OMITTED-TEST", "GENERATION-DUPLICATE-TEST", "GENERATION-RELABEL-STATIC",
    "GENERATION-RELABEL-CONTRACT", "GENERATION-STALE-RUN", "GENERATION-PAYLOAD-SET",
    "GENERATION-DIRECT-PAYLOAD-BUNDLE", "GENERATION-STALE-MIXED-PAYLOAD",
    "GENERATION-FALSE-DECISION", "GENERATION-MARKER-LAST",
)
BEHAVIORAL_TEST_REGISTRY = tuple(
    BehavioralTestSpec(test_id, "BEHAVIORAL", test_id.replace("-", " "),
                       f"scripts/validate_paper1_g06_2d.py:behavioral_case:{test_id}")
    for test_id in _BEHAVIORAL_IDS
)
STATIC_TEST_REGISTRY = tuple(
    BehavioralTestSpec(test_id, "STATIC_AUTHORITY", test_id.replace("-", " "),
                       f"scripts/validate_paper1_g06_2d.py:static_case:{test_id}")
    for test_id in (
        "STATIC-HEAD", "STATIC-G05A-HASH", "STATIC-G05B-HASH", "STATIC-METRIC-HASH",
        "STATIC-RF-HASH", "STATIC-NO-RESULTS", "STATIC-AUTHORITY-IMMUTABLE",
        "STATIC-FACADE-SURFACE", "STATIC-SYNTHETIC-ONLY",
    )
)
INTEGRATION_TEST_IDS = (
    "INTEGRATION-G05A-LOGISTIC", "INTEGRATION-G05A-RF",
    "INTEGRATION-G05A-DISABLED", "INTEGRATION-G05B-BOUNDARY",
    "INTEGRATION-G05B-FRACTIONAL-BLOCKED",
)


def _test_registry_hash(registry: Sequence[BehavioralTestSpec]) -> str:
    return hashlib.sha256(canonical_json([asdict(spec) for spec in registry])).hexdigest()


BEHAVIORAL_UNIVERSE_SHA256 = _test_registry_hash(BEHAVIORAL_TEST_REGISTRY)
STATIC_UNIVERSE_SHA256 = _test_registry_hash(STATIC_TEST_REGISTRY)


def _validate_runner_callable(function: Callable[..., tuple[str, str]],
                              validator_path: Path, expected_name: str) -> None:
    source = inspect.getsourcefile(function)
    if function.__name__ != expected_name or source is None or Path(source).resolve() != validator_path.resolve():
        raise ContractError("ERR_VALIDATOR_CALLABLE_IDENTITY")


def _assemble_validated_test_run(root: Path, validator_path: Path,
                                 behavioral: tuple[tuple[str, str, str], ...],
                                 static: tuple[tuple[str, str, str], ...],
                                 integration: tuple[tuple[str, str, str], ...]) -> ValidatedTestRun:
    universe = governed_execution_universe(root)
    payload = {
        "schema_version": VALIDATED_TEST_RUN_SCHEMA_VERSION, "gate_version": GATE_VERSION,
        "git_head": _git_head(root),
        "runtime_source_sha256": sha256_file(root / "src/paper1_g06_2d_runtime.py"),
        "facade_source_sha256": sha256_file(root / "src/paper1_g06_2_runtime.py"),
        "validator_source_sha256": sha256_file(validator_path),
        "behavioral_universe_sha256": BEHAVIORAL_UNIVERSE_SHA256,
        "static_universe_sha256": STATIC_UNIVERSE_SHA256,
        "behavioral_results": behavioral, "static_results": static,
        "integration_results": integration,
        "contract_combination_count": len(universe.unit_ids),
        "execution_identity": hashlib.sha256(canonical_json({
            "behavioral": behavioral, "static": static, "integration": integration,
            "head": _git_head(root), "validator": sha256_file(validator_path),
        })).hexdigest(),
        "status": "PASS",
    }
    receipt = ValidatedTestRun(**payload,
                               receipt_sha256=hashlib.sha256(canonical_json(payload)).hexdigest())
    _ISSUED_VALIDATED_TEST_RUNS[id(receipt)] = receipt
    return receipt


def execute_validated_test_run(project_root: Path,
                               behavioral_runner: Callable[[BehavioralTestSpec, ValidatedTestRun | None], tuple[str, str]],
                               static_runner: Callable[[BehavioralTestSpec], tuple[str, str]],
                               integration_runner: Callable[[str], tuple[str, str]],
                               validator_source: Path) -> ValidatedTestRun:
    root = Path(project_root).resolve()
    validator_path = Path(validator_source).resolve()
    _validate_runner_callable(behavioral_runner, validator_path, "behavioral_case")
    _validate_runner_callable(static_runner, validator_path, "static_case")
    _validate_runner_callable(integration_runner, validator_path, "integration_case")
    static = tuple((spec.test_id, *static_runner(spec)) for spec in STATIC_TEST_REGISTRY)
    integration = tuple((test_id, *integration_runner(test_id)) for test_id in INTEGRATION_TEST_IDS)
    generation_ids = {spec.test_id for spec in BEHAVIORAL_TEST_REGISTRY
                      if spec.test_id.startswith("GENERATION-")}
    early = tuple((spec.test_id, *behavioral_runner(spec, None))
                  for spec in BEHAVIORAL_TEST_REGISTRY if spec.test_id not in generation_ids)
    if any(row[1] != "PASS" for row in (*early, *static, *integration)):
        raise ContractError("ERR_VALIDATOR_TEST_FAILURE")
    provisional_rows = tuple(
        next((row for row in early if row[0] == spec.test_id), (spec.test_id, "PASS", "PROVISIONAL"))
        for spec in BEHAVIORAL_TEST_REGISTRY
    )
    provisional = _assemble_validated_test_run(root, validator_path, provisional_rows, static, integration)
    late = tuple((spec.test_id, *behavioral_runner(spec, provisional))
                 for spec in BEHAVIORAL_TEST_REGISTRY if spec.test_id in generation_ids)
    lookup = {row[0]: row for row in (*early, *late)}
    behavioral = tuple(lookup[spec.test_id] for spec in BEHAVIORAL_TEST_REGISTRY)
    for rows, expected_ids in (
        (behavioral, tuple(spec.test_id for spec in BEHAVIORAL_TEST_REGISTRY)),
        (static, tuple(spec.test_id for spec in STATIC_TEST_REGISTRY)),
        (integration, INTEGRATION_TEST_IDS),
    ):
        if tuple(row[0] for row in rows) != expected_ids or len(set(row[0] for row in rows)) != len(rows):
            raise ContractError("ERR_VALIDATOR_EXECUTED_TEST_SET")
    if any(row[1] != "PASS" for row in (*behavioral, *static, *integration)):
        raise ContractError("ERR_VALIDATOR_TEST_FAILURE")
    return _assemble_validated_test_run(root, validator_path, behavioral, static, integration)


G06_2D_REQUIRED_PAYLOADS = (
    "PAPER1_G06_2D_CORRECTION.md", "PAPER1_G06_2D_API_SURFACE_QC.csv",
    "PAPER1_G06_2D_PREDICTOR_HANDOFF_QC.csv", "PAPER1_G06_2D_ENVIRONMENT_QC.csv",
    "PAPER1_G06_2D_G05B_AUTHORITY_QC.csv", "PAPER1_G06_2D_RUN_CONTEXT_QC.csv",
    "PAPER1_G06_2D_RECEIPT_CHECKPOINT_QC.csv", "PAPER1_G06_2D_EXECUTION_UNIVERSE_QC.csv",
    "PAPER1_G06_2D_VALIDATOR_PROVENANCE_QC.csv", "PAPER1_G06_2D_INTEGRATION_QC.csv",
    "PAPER1_G06_2D_TEST_EXECUTION.csv", "PAPER1_G06_2D_DECISION.csv",
)
G06_2D_MANIFEST_NAME = "PAPER1_G06_2D_GENERATION_MANIFEST.json"


def _validated_test_frame(run: ValidatedTestRun) -> pd.DataFrame:
    rows = []
    for provenance, values in (("BEHAVIORAL", run.behavioral_results),
                               ("STATIC_AUTHORITY", run.static_results),
                               ("INTEGRATION_LIFECYCLE", run.integration_results)):
        rows.extend({"test_id": test_id, "provenance_class": provenance,
                     "result": result, "observed_reason": reason}
                    for test_id, result, reason in values)
    return pd.DataFrame(rows, columns=["test_id", "provenance_class", "result", "observed_reason"])


def _validate_test_run_current(root: Path, run: ValidatedTestRun,
                               require_issued: bool) -> None:
    if not isinstance(run, ValidatedTestRun):
        raise ContractError("ERR_VALIDATED_TEST_RUN_TYPE")
    if require_issued and _ISSUED_VALIDATED_TEST_RUNS.get(id(run)) is not run:
        raise ContractError("ERR_VALIDATED_TEST_RUN_NOT_ISSUED")
    payload = asdict(run)
    observed_receipt = payload.pop("receipt_sha256")
    if hashlib.sha256(canonical_json(payload)).hexdigest() != observed_receipt:
        raise ContractError("ERR_VALIDATED_TEST_RUN_RECEIPT")
    expected = {
        "git_head": _git_head(root),
        "runtime_source_sha256": sha256_file(root / "src/paper1_g06_2d_runtime.py"),
        "facade_source_sha256": sha256_file(root / "src/paper1_g06_2_runtime.py"),
        "validator_source_sha256": sha256_file(root / "scripts/validate_paper1_g06_2d.py"),
        "behavioral_universe_sha256": BEHAVIORAL_UNIVERSE_SHA256,
        "static_universe_sha256": STATIC_UNIVERSE_SHA256,
        "status": "PASS",
    }
    if any(getattr(run, field) != value for field, value in expected.items()):
        raise ContractError("ERR_VALIDATED_TEST_RUN_STALE")
    if tuple(row[0] for row in run.behavioral_results) != tuple(spec.test_id for spec in BEHAVIORAL_TEST_REGISTRY):
        raise ContractError("ERR_VALIDATED_TEST_RUN_BEHAVIORAL_SET")
    if len(set(row[0] for row in run.behavioral_results)) != len(run.behavioral_results):
        raise ContractError("ERR_VALIDATED_TEST_RUN_DUPLICATE")


def _validate_generation_payload_content(validated_run: ValidatedTestRun,
                                         staged: Mapping[str, bytes]) -> None:
    if set(staged) != set(G06_2D_REQUIRED_PAYLOADS):
        raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_SET")
    observed_tests = pd.read_csv(io.BytesIO(staged["PAPER1_G06_2D_TEST_EXECUTION.csv"]))
    expected_tests = _validated_test_frame(validated_run)
    if not observed_tests.equals(expected_tests):
        raise ContractError("ERR_GENERATION_TEST_LEDGER_BINDING")
    decision = pd.read_csv(io.BytesIO(staged["PAPER1_G06_2D_DECISION.csv"]))
    required_decision = {"gate", "status", "model_fitting_authorized",
                         "real_predictions_generated", "real_performance_inspected"}
    if not required_decision.issubset(decision.columns) or len(decision) != 1:
        raise ContractError("ERR_GENERATION_DECISION_SCHEMA")
    row = decision.iloc[0]
    if row["gate"] != GATE_VERSION or row["status"] != "COMPLETE":
        raise ContractError("ERR_GENERATION_FALSE_COMPLETE")
    for field in ("model_fitting_authorized", "real_predictions_generated", "real_performance_inspected"):
        if str(row[field]).upper() not in {"FALSE", "NO"}:
            raise ContractError("ERR_GENERATION_SAFETY_CLAIM")


def build_validated_generation_payloads(
        project_root: Path,
        validated_run: ValidatedTestRun,
        payload_builder: Callable[[ValidatedTestRun], Mapping[str, bytes]],
        validator_source: Path) -> ValidatedGenerationPayloads:
    root = Path(project_root).resolve()
    validator_path = Path(validator_source).resolve()
    _validate_test_run_current(root, validated_run, True)
    _validate_runner_callable(payload_builder, validator_path, "generation_payloads")
    staged = {name: bytes(content) for name, content in payload_builder(validated_run).items()}
    _validate_generation_payload_content(validated_run, staged)
    payloads = tuple((name, staged[name]) for name in G06_2D_REQUIRED_PAYLOADS)
    payload_hashes = tuple((name, hashlib.sha256(content).hexdigest()) for name, content in payloads)
    authority = {
        "schema_version": "PAPER1_G06.2D_VALIDATED_PAYLOADS_V1",
        "gate_version": GATE_VERSION,
        "git_head": _git_head(root),
        "validator_source_sha256": sha256_file(validator_path),
        "validated_test_run_receipt_sha256": validated_run.receipt_sha256,
        "payload_sha256s": payload_hashes,
    }
    bundle = ValidatedGenerationPayloads(
        **authority, payloads=payloads,
        receipt_sha256=hashlib.sha256(canonical_json(authority)).hexdigest(),
    )
    _ISSUED_GENERATION_PAYLOADS[id(bundle)] = bundle
    return bundle


def _validate_generation_payload_bundle(root: Path, validated_run: ValidatedTestRun,
                                        bundle: ValidatedGenerationPayloads,
                                        require_issued: bool) -> dict[str, bytes]:
    if not isinstance(bundle, ValidatedGenerationPayloads):
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_TYPE")
    if require_issued and _ISSUED_GENERATION_PAYLOADS.get(id(bundle)) is not bundle:
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_NOT_ISSUED")
    staged = dict(bundle.payloads)
    hashes = tuple((name, hashlib.sha256(content).hexdigest())
                   for name, content in bundle.payloads)
    authority = {
        "schema_version": bundle.schema_version,
        "gate_version": bundle.gate_version,
        "git_head": bundle.git_head,
        "validator_source_sha256": bundle.validator_source_sha256,
        "validated_test_run_receipt_sha256": bundle.validated_test_run_receipt_sha256,
        "payload_sha256s": bundle.payload_sha256s,
    }
    if (bundle.schema_version != "PAPER1_G06.2D_VALIDATED_PAYLOADS_V1" or
            bundle.gate_version != GATE_VERSION or bundle.git_head != _git_head(root) or
            bundle.validator_source_sha256 != validated_run.validator_source_sha256 or
            bundle.validated_test_run_receipt_sha256 != validated_run.receipt_sha256 or
            hashes != bundle.payload_sha256s or
            hashlib.sha256(canonical_json(authority)).hexdigest() != bundle.receipt_sha256):
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_BINDING")
    _validate_generation_payload_content(validated_run, staged)
    return staged


def publish_validation_generation(project_root: Path, directory: Path,
                                  validated_run: ValidatedTestRun,
                                  payload_bundle: ValidatedGenerationPayloads,
                                  fail_after: int | None = None) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    _validate_test_run_current(root, validated_run, True)
    staged = _validate_generation_payload_bundle(root, validated_run, payload_bundle, True)
    entries = {name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "role": name}
               for name, content in staged.items()}
    metadata = {
        "schema_version": GENERATION_SCHEMA_VERSION, "gate_version": GATE_VERSION,
        "api_identity": API_IDENTITY, "git_head": _git_head(root),
        "runtime_source_sha256": validated_run.runtime_source_sha256,
        "facade_source_sha256": validated_run.facade_source_sha256,
        "validator_source_sha256": validated_run.validator_source_sha256,
        "behavioral_universe_sha256": validated_run.behavioral_universe_sha256,
        "static_universe_sha256": validated_run.static_universe_sha256,
        "validated_payload_bundle_receipt_sha256": payload_bundle.receipt_sha256,
        "validated_test_run": asdict(validated_run), "decision_status": "COMPLETE",
        "publication_protocol": "PAYLOADS_THEN_MARKER_LAST",
    }
    generation_id = hashlib.sha256(canonical_json({"metadata": metadata, "payloads": entries})).hexdigest()
    manifest = {**metadata, "generation_id": generation_id, "payloads": entries}
    directory = Path(directory)
    for index, name in enumerate(G06_2D_REQUIRED_PAYLOADS, start=1):
        _atomic_bytes(directory / name, staged[name])
        if fail_after == index:
            raise ContractError("ERR_INJECTED_PUBLICATION_FAILURE")
    _atomic_bytes(directory / G06_2D_MANIFEST_NAME, canonical_json(manifest))
    return MappingProxyType(manifest)


def validate_validation_generation(project_root: Path, directory: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    directory = Path(directory)
    marker = directory / G06_2D_MANIFEST_NAME
    if not marker.is_file():
        raise ContractError("ERR_GENERATION_MARKER_MISSING")
    manifest = json.loads(marker.read_text(encoding="ascii"))
    declared = manifest.get("payloads", {})
    if set(declared) != set(G06_2D_REQUIRED_PAYLOADS):
        raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_SET")
    payloads = {}
    for name in G06_2D_REQUIRED_PAYLOADS:
        path = directory / name
        if not path.is_file():
            raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_SET")
        raw = path.read_bytes()
        identity = declared[name]
        if identity.get("role") != name or identity.get("bytes") != len(raw) or identity.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise ContractError("ERR_GENERATION_PAYLOAD_IDENTITY")
        payloads[name] = raw
    run_data = dict(manifest.get("validated_test_run", {}))
    for field in ("behavioral_results", "static_results", "integration_results"):
        run_data[field] = tuple(tuple(row) for row in run_data.get(field, ()))
    try:
        run = ValidatedTestRun(**run_data)
    except Exception as exc:
        raise ContractError("ERR_VALIDATED_TEST_RUN_SCHEMA") from exc
    _validate_test_run_current(root, run, False)
    observed_tests = pd.read_csv(io.BytesIO(payloads["PAPER1_G06_2D_TEST_EXECUTION.csv"]))
    if not observed_tests.equals(_validated_test_frame(run)):
        raise ContractError("ERR_GENERATION_TEST_LEDGER_BINDING")
    payload_hashes = tuple((name, hashlib.sha256(payloads[name]).hexdigest())
                           for name in G06_2D_REQUIRED_PAYLOADS)
    payload_authority = {
        "schema_version": "PAPER1_G06.2D_VALIDATED_PAYLOADS_V1",
        "gate_version": GATE_VERSION,
        "git_head": run.git_head,
        "validator_source_sha256": run.validator_source_sha256,
        "validated_test_run_receipt_sha256": run.receipt_sha256,
        "payload_sha256s": payload_hashes,
    }
    if manifest.get("validated_payload_bundle_receipt_sha256") != hashlib.sha256(
            canonical_json(payload_authority)).hexdigest():
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_BINDING")
    metadata = {key: manifest[key] for key in (
        "schema_version", "gate_version", "api_identity", "git_head",
        "runtime_source_sha256", "facade_source_sha256", "validator_source_sha256",
        "behavioral_universe_sha256", "static_universe_sha256", "validated_test_run",
        "validated_payload_bundle_receipt_sha256", "decision_status", "publication_protocol",
    )}
    expected_generation = hashlib.sha256(canonical_json({"metadata": metadata, "payloads": declared})).hexdigest()
    if manifest.get("generation_id") != expected_generation:
        raise ContractError("ERR_GENERATION_IDENTITY")
    return MappingProxyType(manifest)


# G06.2g adds publication-time execution attestation for the existing sixteen
# fresh-process disk attacks. Scientific, statistical, artifact, and metric
# contracts above remain the accepted G06.2e/G06.2d implementations.
GENERATION_GATE_VERSION = "PAPER1_G06.2g"
GENERATION_SCHEMA_VERSION = "PAPER1_G06.2G_VALIDATION_GENERATION_V1"
VALIDATED_TEST_RUN_SCHEMA_VERSION = "PAPER1_G06.2G_VALIDATED_TEST_RUN_V1"
VALIDATED_PAYLOAD_SCHEMA_VERSION = "PAPER1_G06.2G_VALIDATED_PAYLOADS_V1"
FRESH_EXECUTION_RECEIPT_SCHEMA_VERSION = "PAPER1_G06.2G_FRESH_EXECUTION_RECEIPT_V1"
GENERATION_PUBLICATION_PROTOCOL = "PAYLOADS_THEN_MARKER_LAST"
GENERATION_VALIDATOR_SOURCE = "scripts/validate_paper1_g06_2g.py"
GENERATION_RUNTIME_SOURCE = "src/paper1_g06_2g_runtime.py"
GENERATION_FACADE_SOURCE = "src/paper1_g06_2_runtime.py"

_G06_2E_BEHAVIORAL_IDS = (
    "API-FACADE-EXPLICIT", "API-LEGACY-DISABLED",
    "PREDICTOR-HANDOFF-VALID", "PREDICTOR-RAW-DATAFRAME",
    "PREDICTOR-WRONG-CONTRACT", "OUTCOME-BINARY-AUTH",
    "OUTCOME-FRACTIONAL-AUTH", "OUTCOME-Y-MUTATION",
    "PREDICTION-INTERVAL-AUTH", "ENVIRONMENT-PROBE-VALID",
    "ENVIRONMENT-BANANA", "ENVIRONMENT-FALSE-VERSION",
    "CONTEXT-FACTORY-VALID", "CONTEXT-FAKE-DIRECT",
    "NONESTIMABILITY-VALID", "NONESTIMABILITY-EXPECTED-HASH",
    "RUN-RECEIPT-VALID", "RUN-RECEIPT-WRONG-OUTCOME",
    "CHECKPOINT-VALID", "CHECKPOINT-CORRUPT",
    "UNIVERSE-AUTHORITY", "UNIVERSE-MISSING-UNIT",
    "RF-FIVE-AUTHENTIC", "RF-INVENTED-HASH", "RF-SD-DDOF0",
    "METRIC-ROLES", "METRIC-SINGLE-CLASS", "METRIC-DENOMINATOR",
    "GENERATION-ARBITRARY-LEDGER", "GENERATION-MARKER-LAST",
)
FRESH_PROCESS_TEST_IDS = (
    "FRESH-GEN-WRONG-HEAD",
    "FRESH-GEN-WRONG-RUNTIME-HASH",
    "FRESH-GEN-WRONG-VALIDATOR-HASH",
    "FRESH-GEN-WRONG-BEHAVIORAL-UNIVERSE",
    "FRESH-GEN-WRONG-PUBLICATION-PROTOCOL",
    "FRESH-GEN-FALSE-DECISION-FITTING-AUTHORIZED",
    "FRESH-GEN-FALSE-DECISION-MODEL-FITTING-AUTHORIZED",
    "FRESH-GEN-FALSE-DECISION-G07-AUTHORIZED",
    "FRESH-GEN-FALSE-DECISION-MODEL-FIT",
    "FRESH-GEN-FALSE-DECISION-REAL-PREDICTIONS",
    "FRESH-GEN-FALSE-DECISION-PERFORMANCE-INSPECTED",
    "FRESH-GEN-FALSE-DECISION-GATE-STATUS",
    "FRESH-GEN-STALE-CORRECTION-PAYLOAD",
    "FRESH-GEN-MIXED-SEMANTIC-PAYLOAD",
    "FRESH-GEN-MISSING-MARKER",
    "FRESH-GEN-PAYLOAD-BYTE-MUTATION",
)
FRESH_PROCESS_EXPECTED_REASONS = MappingProxyType({
    "FRESH-GEN-WRONG-HEAD": "ERR_GENERATION_GIT_HEAD_AUTHORITY",
    "FRESH-GEN-WRONG-RUNTIME-HASH": "ERR_GENERATION_RUNTIME_AUTHORITY",
    "FRESH-GEN-WRONG-VALIDATOR-HASH": "ERR_GENERATION_VALIDATOR_AUTHORITY",
    "FRESH-GEN-WRONG-BEHAVIORAL-UNIVERSE": "ERR_GENERATION_BEHAVIORAL_UNIVERSE_AUTHORITY",
    "FRESH-GEN-WRONG-PUBLICATION-PROTOCOL": "ERR_GENERATION_PUBLICATION_PROTOCOL",
    "FRESH-GEN-FALSE-DECISION-FITTING-AUTHORIZED": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-MODEL-FITTING-AUTHORIZED": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-G07-AUTHORIZED": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-MODEL-FIT": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-REAL-PREDICTIONS": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-PERFORMANCE-INSPECTED": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-GATE-STATUS": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-STALE-CORRECTION-PAYLOAD": "ERR_GENERATION_SEMANTIC_PAYLOAD_STALE",
    "FRESH-GEN-MIXED-SEMANTIC-PAYLOAD": "ERR_GENERATION_FRESH_RECEIPT_QC",
    "FRESH-GEN-MISSING-MARKER": "ERR_GENERATION_MARKER_MISSING",
    "FRESH-GEN-PAYLOAD-BYTE-MUTATION": "ERR_GENERATION_PAYLOAD_IDENTITY",
})
FROZEN_CONTRACT_COMBINATION_COUNT = 352

PUBLICATION_GUARD_TEST_IDS = (
    "GENERATION-SKIP-FRESH-RUNNER",
    "GENERATION-EMPTY-FRESH-RESULTS",
    "GENERATION-FABRICATED-FRESH-DATAFRAME",
    "GENERATION-PARTIAL-FRESH-RECEIPT",
    "GENERATION-DUPLICATE-FRESH-RECEIPT",
    "GENERATION-WRONG-REASON-FRESH-RECEIPT",
    "GENERATION-DIRECT-FRESH-RECEIPT",
    "GENERATION-STALE-FRESH-RECEIPT",
    "GENERATION-MUTABLE-GLOBAL-INJECTION",
    "GENERATION-FAKE-FRESH-RUNNER",
)

LOCAL_PROVENANCE_TEST_IDS = (
    "GENERATION-SUBSTITUTE-CALLABLE-NOT-ACCEPTED",
    "GENERATION-MODULE-BOUND-REPLACEMENT-NOT-AUTHORITY",
    "GENERATION-ZERO-CHILD-NO-RECEIPT",
    "GENERATION-ROW-COUNT-NOT-CHILD-COUNT",
    "GENERATION-PARTIAL-CHILD-EXECUTION",
    "GENERATION-CHILD-WRONG-RESULT",
    "GENERATION-CHILD-FAILURE",
)

_G06_2G_BEHAVIORAL_IDS = tuple(
    test_id for test_id in _G06_2E_BEHAVIORAL_IDS
    if test_id != "GENERATION-MARKER-LAST"
) + PUBLICATION_GUARD_TEST_IDS + LOCAL_PROVENANCE_TEST_IDS
BEHAVIORAL_TEST_REGISTRY = tuple(
    BehavioralTestSpec(
        test_id,
        "BEHAVIORAL",
        test_id.replace("-", " "),
        f"scripts/validate_paper1_g06_2g.py:behavioral_case:{test_id}",
    )
    for test_id in _G06_2G_BEHAVIORAL_IDS
)
STATIC_TEST_REGISTRY = tuple(
    BehavioralTestSpec(
        test_id,
        "STATIC_AUTHORITY",
        test_id.replace("-", " "),
        f"scripts/validate_paper1_g06_2g.py:static_case:{test_id}",
    )
    for test_id in (
        "STATIC-HEAD", "STATIC-G05A-HASH", "STATIC-G05B-HASH",
        "STATIC-METRIC-HASH", "STATIC-RF-HASH", "STATIC-NO-RESULTS",
        "STATIC-AUTHORITY-IMMUTABLE", "STATIC-FACADE-SURFACE",
        "STATIC-SYNTHETIC-ONLY",
    )
)
BEHAVIORAL_UNIVERSE_SHA256 = _test_registry_hash(BEHAVIORAL_TEST_REGISTRY)
STATIC_UNIVERSE_SHA256 = _test_registry_hash(STATIC_TEST_REGISTRY)
FRESH_PROCESS_UNIVERSE_SHA256 = hashlib.sha256(
    canonical_json(list(FRESH_PROCESS_TEST_IDS))
).hexdigest()
FRESH_PROCESS_EXPECTED_REASONS = MappingProxyType({
    **dict(FRESH_PROCESS_EXPECTED_REASONS),
    "FRESH-GEN-MIXED-SEMANTIC-PAYLOAD": "ERR_GENERATION_FRESH_RECEIPT_QC",
})
INTEGRATION_UNIVERSE_SHA256 = hashlib.sha256(
    canonical_json(list(INTEGRATION_TEST_IDS))
).hexdigest()

G06_2G_REQUIRED_PAYLOADS = (
    "PAPER1_G06_2G_CORRECTION.md",
    "PAPER1_G06_2G_CHILD_EXECUTION_QC.csv",
    "PAPER1_G06_2G_PUBLICATION_PROVENANCE_QC.csv",
    "PAPER1_G06_2G_TEST_EXECUTION.csv",
    "PAPER1_G06_2G_DECISION.csv",
)
G06_2G_MANIFEST_NAME = "PAPER1_G06_2G_GENERATION_MANIFEST.json"

G06_2G_DECISION_SEMANTICS = MappingProxyType({
    "gate": GENERATION_GATE_VERSION,
    "status": "COMPLETE",
    "independent_acceptance_may_proceed": "YES",
    "g07_may_begin": "NO",
    "g08_status": "BLOCKED",
    "scientific_fitting_authorized": "NO",
    "model_fitting_authorized": "NO",
    "models_fit": "NO",
    "real_predictions_generated": "NO",
    "real_performance_inspected": "NO",
    "f04_provenance_status": "NONBLOCKING_PROVENANCE",
    "f04_downstream_requirement": (
        "TYPED_EXCEPTION_RECEIPT_OR_CALLER_REPORTED_UNAUTHENTICATED_BEFORE_SCIENTIFIC_RUN"
    ),
    "f05_code_quality_status": "NONBLOCKING_CODE_QUALITY_DEFERRED_POST_ACCEPTANCE_CLEANUP",
})


@dataclass(frozen=True)
class FreshProcessExecutionReceipt:
    schema_version: str
    gate_version: str
    git_head: str
    validator_source_sha256: str
    fresh_process_universe_sha256: str
    expected_test_ids: tuple[str, ...]
    results: tuple[tuple[str, str, str, str], ...]
    execution_count: int
    unique_test_count: int
    child_process_count: int
    successful_result_count: int
    child_execution_records: tuple[tuple[str, int, int, str, str], ...]
    child_execution_ledger_sha256: str
    ledger_sha256: str
    status: str
    receipt_sha256: str


@dataclass(frozen=True)
class ValidatedGenerationPayloads:
    schema_version: str
    gate_version: str
    git_head: str
    validator_source_sha256: str
    validated_test_run_receipt_sha256: str
    fresh_execution_receipt_sha256: str
    payloads: tuple[tuple[str, bytes], ...]
    payload_sha256s: tuple[tuple[str, str], ...]
    receipt_sha256: str


_ISSUED_FRESH_EXECUTION_RECEIPTS: dict[int, FreshProcessExecutionReceipt] = {}
_CURRENT_GENERATION_AUTHORITY_CACHE = {}


def current_generation_authority(project_root: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    cached = _CURRENT_GENERATION_AUTHORITY_CACHE.get(root)
    if cached is not None:
        return cached
    _verify_authority_file(root, G05A_REGISTRY_SOURCE, G05A_REGISTRY_SOURCE_SHA256,
                           "ERR_GENERATION_G05A_AUTHORITY")
    _verify_authority_file(root, G05B_REGISTRY_SOURCE, G05B_REGISTRY_SOURCE_SHA256,
                           "ERR_GENERATION_G05B_AUTHORITY")
    _verify_authority_file(root, RF_AUTHORITY_SOURCE, RF_AUTHORITY_SHA256,
                           "ERR_GENERATION_RF_AUTHORITY")
    _verify_authority_file(root, METRIC_AUTHORITY_SOURCE, METRIC_AUTHORITY_SHA256,
                           "ERR_GENERATION_METRIC_AUTHORITY")
    authority = MappingProxyType({
        "gate_version": GENERATION_GATE_VERSION,
        "schema_version": GENERATION_SCHEMA_VERSION,
        "api_identity": API_IDENTITY,
        "git_head": _git_head(root),
        "facade_source_sha256": sha256_file(root / GENERATION_FACADE_SOURCE),
        "runtime_source_sha256": sha256_file(root / GENERATION_RUNTIME_SOURCE),
        "validator_source_sha256": sha256_file(root / GENERATION_VALIDATOR_SOURCE),
        "behavioral_universe_sha256": BEHAVIORAL_UNIVERSE_SHA256,
        "static_universe_sha256": STATIC_UNIVERSE_SHA256,
        "integration_universe_sha256": INTEGRATION_UNIVERSE_SHA256,
        "fresh_process_universe_sha256": FRESH_PROCESS_UNIVERSE_SHA256,
        "g05a_authority_sha256": G05A_REGISTRY_SOURCE_SHA256,
        "g05b_authority_sha256": G05B_REGISTRY_SOURCE_SHA256,
        "rf_authority_sha256": RF_AUTHORITY_SHA256,
        "metric_authority_sha256": METRIC_AUTHORITY_SHA256,
        "behavioral_test_count": len(BEHAVIORAL_TEST_REGISTRY),
        "static_test_count": len(STATIC_TEST_REGISTRY),
        "integration_test_count": len(INTEGRATION_TEST_IDS),
        "fresh_process_test_count": len(FRESH_PROCESS_TEST_IDS),
        "publication_guard_test_count": len(PUBLICATION_GUARD_TEST_IDS),
        "local_provenance_test_count": len(LOCAL_PROVENANCE_TEST_IDS),
        "contract_combination_count": FROZEN_CONTRACT_COMBINATION_COUNT,
        "required_payload_roles": list(G06_2G_REQUIRED_PAYLOADS),
        "publication_protocol": GENERATION_PUBLICATION_PROTOCOL,
        "decision_status": "COMPLETE",
    })
    _CURRENT_GENERATION_AUTHORITY_CACHE[root] = authority
    return authority


def _fresh_receipt_payload(receipt: FreshProcessExecutionReceipt) -> dict[str, object]:
    payload = asdict(receipt)
    payload.pop("receipt_sha256")
    return payload


def _validate_fresh_execution_receipt(project_root: Path,
                                      receipt: FreshProcessExecutionReceipt,
                                      require_issued: bool) -> None:
    if not isinstance(receipt, FreshProcessExecutionReceipt):
        raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_TYPE")
    if require_issued and _ISSUED_FRESH_EXECUTION_RECEIPTS.get(id(receipt)) is not receipt:
        raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_NOT_ISSUED")
    payload = _fresh_receipt_payload(receipt)
    if hashlib.sha256(canonical_json(payload)).hexdigest() != receipt.receipt_sha256:
        raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_HASH")
    authority = current_generation_authority(project_root)
    expected_authority = {
        "schema_version": FRESH_EXECUTION_RECEIPT_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "fresh_process_universe_sha256": authority["fresh_process_universe_sha256"],
    }
    if any(getattr(receipt, field) != value for field, value in expected_authority.items()):
        raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_STALE")
    expected_ids = tuple(FRESH_PROCESS_TEST_IDS)
    observed_ids = tuple(row[0] for row in receipt.results)
    if receipt.expected_test_ids != expected_ids or observed_ids != expected_ids:
        raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_TEST_SET")
    if len(set(observed_ids)) != len(observed_ids):
        raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_DUPLICATE")
    for test_id, result, expected_reason, observed_reason in receipt.results:
        if expected_reason != FRESH_PROCESS_EXPECTED_REASONS[test_id]:
            raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_EXPECTED_REASON")
        if result != "PASS" or observed_reason != expected_reason:
            raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_OBSERVED_REASON")
    count = len(expected_ids)
    if (receipt.execution_count != count or receipt.unique_test_count != count or
            receipt.child_process_count != count or
            receipt.successful_result_count != count or receipt.status != "PASS"):
        raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_COUNTS")
    _validate_completed_child_evidence(receipt.results, receipt.child_execution_records)
    if receipt.child_execution_ledger_sha256 != hashlib.sha256(
            canonical_json(list(receipt.child_execution_records))).hexdigest():
        raise ContractError("ERR_FRESH_EXECUTION_CHILD_LEDGER")
    if receipt.ledger_sha256 != hashlib.sha256(canonical_json(list(receipt.results))).hexdigest():
        raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_LEDGER")


def _validate_completed_child_evidence(
        results: Sequence[tuple[str, str, str, str]],
        child_records: Sequence[tuple[str, int, int, str, str]]) -> None:
    expected_ids = tuple(FRESH_PROCESS_TEST_IDS)
    result_ids = tuple(row[0] for row in results)
    child_ids = tuple(row[0] for row in child_records)
    if result_ids != expected_ids or child_ids != expected_ids:
        raise ContractError("ERR_FRESH_EXECUTION_CHILD_SET")
    if len(set(child_ids)) != len(child_ids):
        raise ContractError("ERR_FRESH_EXECUTION_CHILD_DUPLICATE")
    if len(child_records) != len(expected_ids):
        raise ContractError("ERR_FRESH_EXECUTION_CHILD_INCOMPLETE")
    for result, child in zip(results, child_records, strict=True):
        test_id, status, expected_reason, observed_reason = result
        child_id, child_pid, returncode, protocol, child_reason = child
        if (child_id != test_id or child_pid <= 0 or returncode != 0 or
                protocol != "PAPER1_G06.2G_FRESH_CHILD_V1"):
            raise ContractError("ERR_FRESH_EXECUTION_CHILD_EVIDENCE")
        if (status != "PASS" or expected_reason != FRESH_PROCESS_EXPECTED_REASONS[test_id] or
                observed_reason != expected_reason or child_reason != observed_reason):
            raise ContractError("ERR_FRESH_EXECUTION_CHILD_WRONG_RESULT")


def execute_fresh_process_attack_run(
        project_root: Path,
        fixture_directory: Path) -> FreshProcessExecutionReceipt:
    root = Path(project_root).resolve()
    validator_path = (root / GENERATION_VALIDATOR_SOURCE).resolve()
    fixture = Path(fixture_directory).resolve()
    if not fixture.is_dir():
        raise ContractError("ERR_FRESH_EXECUTION_FIXTURE_MISSING")
    validate_validation_generation(root, fixture)
    rows: list[tuple[str, str, str, str]] = []
    child_records: list[tuple[str, int, int, str, str]] = []
    with tempfile.TemporaryDirectory(prefix="paper1_g06_2g_children_") as temp_name:
        temp_root = Path(temp_name)
        for test_id in FRESH_PROCESS_TEST_IDS:
            expected_reason = FRESH_PROCESS_EXPECTED_REASONS[test_id]
            attack = temp_root / test_id.lower()
            shutil.copytree(fixture, attack)
            command = [
                sys.executable, str(validator_path), "--g06-2g-fresh-child",
                test_id, str(attack),
            ]
            try:
                child = subprocess.Popen(
                    command, cwd=root, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as exc:
                raise ContractError(
                    f"ERR_FRESH_EXECUTION_CHILD_LAUNCH:{test_id}:{type(exc).__name__}"
                ) from exc
            try:
                stdout, stderr = child.communicate(timeout=120)
            except subprocess.TimeoutExpired as exc:
                child.kill()
                child.communicate()
                raise ContractError(f"ERR_FRESH_EXECUTION_CHILD_TIMEOUT:{test_id}") from exc
            if child.returncode != 0:
                raise ContractError(
                    f"ERR_FRESH_EXECUTION_CHILD_FAILURE:{test_id}:{child.returncode}:{stderr.strip()}"
                )
            lines = [line for line in stdout.splitlines() if line.strip()]
            if len(lines) != 1:
                raise ContractError(f"ERR_FRESH_EXECUTION_CHILD_OUTPUT:{test_id}")
            try:
                observed = json.loads(lines[0])
            except Exception as exc:
                raise ContractError(f"ERR_FRESH_EXECUTION_CHILD_OUTPUT:{test_id}") from exc
            if (observed.get("protocol") != "PAPER1_G06.2G_FRESH_CHILD_V1" or
                    observed.get("test_id") != test_id or observed.get("result") != "PASS"):
                raise ContractError(f"ERR_FRESH_EXECUTION_CHILD_PROTOCOL:{test_id}")
            observed_reason = str(observed.get("observed_reason", ""))
            if observed_reason != expected_reason:
                raise ContractError(
                    f"ERR_FRESH_EXECUTION_WRONG_REASON:{test_id}:{expected_reason}:{observed_reason}"
                )
            rows.append((test_id, "PASS", expected_reason, observed_reason))
            child_records.append((
                test_id, int(child.pid), int(child.returncode),
                "PAPER1_G06.2G_FRESH_CHILD_V1", observed_reason,
            ))
    results = tuple(rows)
    completed_children = tuple(child_records)
    _validate_completed_child_evidence(results, completed_children)
    authority = current_generation_authority(root)
    payload = {
        "schema_version": FRESH_EXECUTION_RECEIPT_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "fresh_process_universe_sha256": authority["fresh_process_universe_sha256"],
        "expected_test_ids": tuple(FRESH_PROCESS_TEST_IDS),
        "results": results,
        "execution_count": len(results),
        "unique_test_count": len({row[0] for row in results}),
        "child_process_count": len(completed_children),
        "successful_result_count": sum(row[1] == "PASS" for row in results),
        "child_execution_records": completed_children,
        "child_execution_ledger_sha256": hashlib.sha256(
            canonical_json(list(completed_children))).hexdigest(),
        "ledger_sha256": hashlib.sha256(canonical_json(list(results))).hexdigest(),
        "status": "PASS",
    }
    receipt = FreshProcessExecutionReceipt(
        **payload,
        receipt_sha256=hashlib.sha256(canonical_json(payload)).hexdigest(),
    )
    _validate_fresh_execution_receipt(root, receipt, False)
    _ISSUED_FRESH_EXECUTION_RECEIPTS[id(receipt)] = receipt
    return receipt


def _fresh_receipt_frame(receipt: FreshProcessExecutionReceipt) -> pd.DataFrame:
    child_lookup = {row[0]: row for row in receipt.child_execution_records}
    return pd.DataFrame([
        {
            "test_id": test_id,
            "provenance_class": "FRESH_PROCESS_DISK_GENERATION",
            "result": result,
            "expected_reason": expected_reason,
            "observed_reason": observed_reason,
            "child_pid": child_lookup[test_id][1],
            "child_returncode": child_lookup[test_id][2],
            "child_protocol": child_lookup[test_id][3],
            "child_execution_ledger_sha256": receipt.child_execution_ledger_sha256,
            "fresh_execution_receipt_sha256": receipt.receipt_sha256,
        }
        for test_id, result, expected_reason, observed_reason in receipt.results
    ], columns=[
        "test_id", "provenance_class", "result", "expected_reason",
        "observed_reason", "child_pid", "child_returncode", "child_protocol",
        "child_execution_ledger_sha256", "fresh_execution_receipt_sha256",
    ])


def _publication_guard_frame(run: ValidatedTestRun) -> pd.DataFrame:
    lookup = {row[0]: row for row in run.behavioral_results}
    rows = []
    for test_id in (*PUBLICATION_GUARD_TEST_IDS, *LOCAL_PROVENANCE_TEST_IDS):
        if test_id not in lookup:
            raise ContractError("ERR_PUBLICATION_GUARD_TEST_SET")
        _, result, observed_reason = lookup[test_id]
        if result != "PASS":
            raise ContractError("ERR_PUBLICATION_GUARD_TEST_FAILURE")
        rows.append({
            "test_id": test_id,
            "provenance_class": "PUBLICATION_PROVENANCE_GUARD",
            "result": result,
            "observed_reason": observed_reason,
        })
    return pd.DataFrame(rows, columns=[
        "test_id", "provenance_class", "result", "observed_reason",
    ])


def _validate_decision_semantics(raw: bytes) -> None:
    try:
        frame = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:
        raise ContractError("ERR_GENERATION_DECISION_SEMANTICS") from exc
    if len(frame) != 1 or set(frame.columns) != set(G06_2G_DECISION_SEMANTICS):
        raise ContractError("ERR_GENERATION_DECISION_SEMANTICS")
    row = frame.iloc[0]
    for field, expected in G06_2G_DECISION_SEMANTICS.items():
        if _normalize_decision_value(row[field]) != _normalize_decision_value(expected):
            raise ContractError("ERR_GENERATION_DECISION_SEMANTICS")


def _validate_generation_payload_content(
        root: Path,
        validated_run: ValidatedTestRun,
        fresh_receipt: FreshProcessExecutionReceipt,
        staged: Mapping[str, bytes]) -> None:
    if set(staged) != set(G06_2G_REQUIRED_PAYLOADS):
        raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_SET")
    _validate_fresh_execution_receipt(root, fresh_receipt, False)
    authority = current_generation_authority(root)
    correction = staged["PAPER1_G06_2G_CORRECTION.md"].decode("utf-8", errors="strict")
    required_lines = (
        f"gate={GENERATION_GATE_VERSION}",
        f"git_head={authority['git_head']}",
        f"runtime_source_sha256={authority['runtime_source_sha256']}",
        f"facade_source_sha256={authority['facade_source_sha256']}",
        f"validator_source_sha256={authority['validator_source_sha256']}",
        f"fresh_execution_receipt_sha256={fresh_receipt.receipt_sha256}",
    )
    if any(line not in correction for line in required_lines):
        raise ContractError("ERR_GENERATION_SEMANTIC_PAYLOAD_STALE")
    observed_receipt = pd.read_csv(io.BytesIO(
        staged["PAPER1_G06_2G_CHILD_EXECUTION_QC.csv"]
    ), dtype=str, keep_default_na=False)
    if not observed_receipt.equals(_fresh_receipt_frame(fresh_receipt).astype(str)):
        raise ContractError("ERR_GENERATION_FRESH_RECEIPT_QC")
    observed_guards = pd.read_csv(io.BytesIO(
        staged["PAPER1_G06_2G_PUBLICATION_PROVENANCE_QC.csv"]
    ), dtype=str, keep_default_na=False)
    if not observed_guards.equals(_publication_guard_frame(validated_run).astype(str)):
        raise ContractError("ERR_GENERATION_PUBLICATION_GUARD_QC")
    observed_tests = pd.read_csv(io.BytesIO(
        staged["PAPER1_G06_2G_TEST_EXECUTION.csv"]
    ), dtype=str, keep_default_na=False)
    base_tests = _validated_test_frame(validated_run).copy()
    base_tests["expected_reason"] = ""
    base_tests["child_pid"] = ""
    base_tests["child_returncode"] = ""
    base_tests["child_protocol"] = ""
    base_tests["child_execution_ledger_sha256"] = ""
    base_tests["fresh_execution_receipt_sha256"] = ""
    base_tests = base_tests[[
        "test_id", "provenance_class", "result", "expected_reason",
        "observed_reason", "child_pid", "child_returncode", "child_protocol",
        "child_execution_ledger_sha256", "fresh_execution_receipt_sha256",
    ]]
    expected_tests = pd.concat(
        [base_tests, _fresh_receipt_frame(fresh_receipt)], ignore_index=True
    ).astype(str)
    if not observed_tests.equals(expected_tests):
        raise ContractError("ERR_GENERATION_TEST_LEDGER_BINDING")
    _validate_decision_semantics(staged["PAPER1_G06_2G_DECISION.csv"])


def build_validated_generation_payloads(
        project_root: Path,
        validated_run: ValidatedTestRun,
        fresh_receipt: FreshProcessExecutionReceipt,
        payload_builder: Callable[[ValidatedTestRun, FreshProcessExecutionReceipt],
                                  Mapping[str, bytes]],
        validator_source: Path) -> ValidatedGenerationPayloads:
    root = Path(project_root).resolve()
    validator_path = Path(validator_source).resolve()
    _validate_test_run_current(root, validated_run, True)
    _validate_fresh_execution_receipt(root, fresh_receipt, True)
    _validate_runner_callable(payload_builder, validator_path, "generation_payloads")
    staged = {
        name: bytes(content)
        for name, content in payload_builder(validated_run, fresh_receipt).items()
    }
    _validate_generation_payload_content(root, validated_run, fresh_receipt, staged)
    payloads = tuple((name, staged[name]) for name in G06_2G_REQUIRED_PAYLOADS)
    payload_hashes = tuple(
        (name, hashlib.sha256(content).hexdigest()) for name, content in payloads
    )
    authority = current_generation_authority(root)
    receipt_authority = {
        "schema_version": VALIDATED_PAYLOAD_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "validated_test_run_receipt_sha256": validated_run.receipt_sha256,
        "fresh_execution_receipt_sha256": fresh_receipt.receipt_sha256,
        "payload_sha256s": payload_hashes,
    }
    bundle = ValidatedGenerationPayloads(
        **receipt_authority,
        payloads=payloads,
        receipt_sha256=hashlib.sha256(canonical_json(receipt_authority)).hexdigest(),
    )
    _ISSUED_GENERATION_PAYLOADS[id(bundle)] = bundle
    return bundle


def _validate_generation_payload_bundle(
        root: Path,
        validated_run: ValidatedTestRun,
        fresh_receipt: FreshProcessExecutionReceipt,
        bundle: ValidatedGenerationPayloads,
        require_issued: bool) -> dict[str, bytes]:
    if not isinstance(bundle, ValidatedGenerationPayloads):
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_TYPE")
    if require_issued and _ISSUED_GENERATION_PAYLOADS.get(id(bundle)) is not bundle:
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_NOT_ISSUED")
    _validate_fresh_execution_receipt(root, fresh_receipt, require_issued)
    staged = dict(bundle.payloads)
    hashes = tuple(
        (name, hashlib.sha256(content).hexdigest()) for name, content in bundle.payloads
    )
    authority = current_generation_authority(root)
    expected = {
        "schema_version": VALIDATED_PAYLOAD_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "validated_test_run_receipt_sha256": validated_run.receipt_sha256,
        "fresh_execution_receipt_sha256": fresh_receipt.receipt_sha256,
        "payload_sha256s": hashes,
    }
    observed = {
        "schema_version": bundle.schema_version,
        "gate_version": bundle.gate_version,
        "git_head": bundle.git_head,
        "validator_source_sha256": bundle.validator_source_sha256,
        "validated_test_run_receipt_sha256": bundle.validated_test_run_receipt_sha256,
        "fresh_execution_receipt_sha256": bundle.fresh_execution_receipt_sha256,
        "payload_sha256s": bundle.payload_sha256s,
    }
    if (observed != expected or
            hashlib.sha256(canonical_json(expected)).hexdigest() != bundle.receipt_sha256):
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_BINDING")
    _validate_generation_payload_content(root, validated_run, fresh_receipt, staged)
    return staged


def _manifest_metadata(authority: Mapping[str, object], run: ValidatedTestRun,
                       fresh_receipt: FreshProcessExecutionReceipt,
                       bundle: ValidatedGenerationPayloads) -> dict[str, object]:
    return {
        **dict(authority),
        "validated_payload_bundle_receipt_sha256": bundle.receipt_sha256,
        "validated_test_run": asdict(run),
        "fresh_process_execution_receipt": asdict(fresh_receipt),
    }


def publish_validation_generation(
        project_root: Path,
        directory: Path,
        validated_run: ValidatedTestRun,
        fresh_receipt: FreshProcessExecutionReceipt,
        payload_bundle: ValidatedGenerationPayloads,
        fail_after: int | None = None) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    _validate_test_run_current(root, validated_run, True)
    _validate_fresh_execution_receipt(root, fresh_receipt, True)
    staged = _validate_generation_payload_bundle(
        root, validated_run, fresh_receipt, payload_bundle, True
    )
    authority = current_generation_authority(root)
    entries = {
        name: {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "role": name,
        }
        for name, content in staged.items()
    }
    metadata = _manifest_metadata(authority, validated_run, fresh_receipt, payload_bundle)
    generation_id = hashlib.sha256(canonical_json({
        "metadata": metadata,
        "payloads": entries,
    })).hexdigest()
    manifest = {**metadata, "generation_id": generation_id, "payloads": entries}
    directory = Path(directory)
    for index, name in enumerate(G06_2G_REQUIRED_PAYLOADS, start=1):
        _atomic_bytes(directory / name, staged[name])
        if fail_after == index:
            raise ContractError("ERR_INJECTED_PUBLICATION_FAILURE")
    _atomic_bytes(directory / G06_2G_MANIFEST_NAME, canonical_json(manifest))
    return MappingProxyType(manifest)


def validate_validation_generation(project_root: Path, directory: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    directory = Path(directory)
    marker = directory / G06_2G_MANIFEST_NAME
    if not marker.is_file():
        raise ContractError("ERR_GENERATION_MARKER_MISSING")
    try:
        manifest = json.loads(marker.read_text(encoding="ascii"))
    except Exception as exc:
        raise ContractError("ERR_GENERATION_MANIFEST_SCHEMA") from exc
    authority = current_generation_authority(root)
    _require_manifest_authority(manifest, authority)
    declared = manifest.get("payloads", {})
    if set(declared) != set(G06_2G_REQUIRED_PAYLOADS):
        raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_SET")
    payloads: dict[str, bytes] = {}
    for name in G06_2G_REQUIRED_PAYLOADS:
        path = directory / name
        if not path.is_file():
            raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_SET")
        raw = path.read_bytes()
        identity = declared[name]
        if (identity.get("role") != name or identity.get("bytes") != len(raw) or
                identity.get("sha256") != hashlib.sha256(raw).hexdigest()):
            raise ContractError("ERR_GENERATION_PAYLOAD_IDENTITY")
        payloads[name] = raw

    run_data = dict(manifest.get("validated_test_run", {}))
    for field in ("behavioral_results", "static_results", "integration_results"):
        run_data[field] = tuple(tuple(row) for row in run_data.get(field, ()))
    try:
        run = ValidatedTestRun(**run_data)
    except Exception as exc:
        raise ContractError("ERR_VALIDATED_TEST_RUN_SCHEMA") from exc
    _validate_test_run_current(root, run, False)
    shared = {
        "git_head": "git_head",
        "runtime_source_sha256": "runtime_source_sha256",
        "facade_source_sha256": "facade_source_sha256",
        "validator_source_sha256": "validator_source_sha256",
        "behavioral_universe_sha256": "behavioral_universe_sha256",
        "static_universe_sha256": "static_universe_sha256",
        "contract_combination_count": "contract_combination_count",
    }
    if any(not _json_equal(manifest.get(top), getattr(run, field))
           for top, field in shared.items()):
        raise ContractError("ERR_GENERATION_TEST_RUN_TOP_LEVEL_CONSISTENCY")

    fresh_data = dict(manifest.get("fresh_process_execution_receipt", {}))
    fresh_data["expected_test_ids"] = tuple(fresh_data.get("expected_test_ids", ()))
    fresh_data["results"] = tuple(tuple(row) for row in fresh_data.get("results", ()))
    try:
        fresh_receipt = FreshProcessExecutionReceipt(**fresh_data)
    except Exception as exc:
        raise ContractError("ERR_FRESH_EXECUTION_RECEIPT_SCHEMA") from exc
    _validate_fresh_execution_receipt(root, fresh_receipt, False)

    _validate_generation_payload_content(root, run, fresh_receipt, payloads)
    payload_hashes = tuple(
        (name, hashlib.sha256(payloads[name]).hexdigest())
        for name in G06_2G_REQUIRED_PAYLOADS
    )
    receipt_authority = {
        "schema_version": VALIDATED_PAYLOAD_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "validated_test_run_receipt_sha256": run.receipt_sha256,
        "fresh_execution_receipt_sha256": fresh_receipt.receipt_sha256,
        "payload_sha256s": payload_hashes,
    }
    expected_bundle = hashlib.sha256(canonical_json(receipt_authority)).hexdigest()
    if manifest.get("validated_payload_bundle_receipt_sha256") != expected_bundle:
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_BINDING")
    pseudo_bundle = ValidatedGenerationPayloads(
        **receipt_authority,
        payloads=tuple((name, payloads[name]) for name in G06_2G_REQUIRED_PAYLOADS),
        receipt_sha256=expected_bundle,
    )
    metadata = _manifest_metadata(authority, run, fresh_receipt, pseudo_bundle)
    expected_generation = hashlib.sha256(canonical_json({
        "metadata": metadata,
        "payloads": declared,
    })).hexdigest()
    if manifest.get("generation_id") != expected_generation:
        raise ContractError("ERR_GENERATION_IDENTITY")
    return MappingProxyType(manifest)


_G06_2G_BINDINGS = {
    name: globals()[name]
    for name in (
        "GENERATION_GATE_VERSION", "GENERATION_SCHEMA_VERSION",
        "VALIDATED_TEST_RUN_SCHEMA_VERSION", "VALIDATED_PAYLOAD_SCHEMA_VERSION",
        "FRESH_EXECUTION_RECEIPT_SCHEMA_VERSION", "GENERATION_PUBLICATION_PROTOCOL",
        "GENERATION_VALIDATOR_SOURCE", "GENERATION_RUNTIME_SOURCE",
        "GENERATION_FACADE_SOURCE", "PUBLICATION_GUARD_TEST_IDS",
        "LOCAL_PROVENANCE_TEST_IDS",
        "FRESH_PROCESS_TEST_IDS", "FRESH_PROCESS_EXPECTED_REASONS",
        "FRESH_PROCESS_UNIVERSE_SHA256", "INTEGRATION_UNIVERSE_SHA256",
        "FROZEN_CONTRACT_COMBINATION_COUNT", "BEHAVIORAL_TEST_REGISTRY",
        "STATIC_TEST_REGISTRY", "BEHAVIORAL_UNIVERSE_SHA256",
        "STATIC_UNIVERSE_SHA256", "G06_2G_REQUIRED_PAYLOADS",
        "G06_2G_MANIFEST_NAME", "G06_2G_DECISION_SEMANTICS",
        "FreshProcessExecutionReceipt", "ValidatedGenerationPayloads",
        "_ISSUED_FRESH_EXECUTION_RECEIPTS", "_CURRENT_GENERATION_AUTHORITY_CACHE",
        "current_generation_authority",
        "_fresh_receipt_payload", "_validate_fresh_execution_receipt",
        "execute_fresh_process_attack_run", "_fresh_receipt_frame",
        "_publication_guard_frame", "_validate_decision_semantics",
        "_validate_generation_payload_content", "build_validated_generation_payloads",
        "_validate_generation_payload_bundle", "_manifest_metadata",
        "publish_validation_generation", "validate_validation_generation",
    )
}


def publish_generation(*_args, **_kwargs):
    raise ContractError("ERR_G06_LEGACY_API_DISABLED")


def validate_generation(*_args, **_kwargs):
    raise ContractError("ERR_G06_LEGACY_API_DISABLED")


# G06.2e is a narrow generation-validation overlay. The execution, prediction,
# receipt, checkpoint, RF, and metric contracts above remain the accepted
# G06.2d implementations.
GENERATION_GATE_VERSION = "PAPER1_G06.2e"
GENERATION_SCHEMA_VERSION = "PAPER1_G06.2E_VALIDATION_GENERATION_V1"
VALIDATED_TEST_RUN_SCHEMA_VERSION = "PAPER1_G06.2E_VALIDATED_TEST_RUN_V1"
VALIDATED_PAYLOAD_SCHEMA_VERSION = "PAPER1_G06.2E_VALIDATED_PAYLOADS_V1"
GENERATION_PUBLICATION_PROTOCOL = "PAYLOADS_THEN_MARKER_LAST"
GENERATION_VALIDATOR_SOURCE = "scripts/validate_paper1_g06_2e.py"
GENERATION_RUNTIME_SOURCE = "src/paper1_g06_2e_runtime.py"
GENERATION_FACADE_SOURCE = "src/paper1_g06_2_runtime.py"

_G06_2E_BEHAVIORAL_IDS = (
    "API-FACADE-EXPLICIT", "API-LEGACY-DISABLED",
    "PREDICTOR-HANDOFF-VALID", "PREDICTOR-RAW-DATAFRAME",
    "PREDICTOR-WRONG-CONTRACT", "OUTCOME-BINARY-AUTH",
    "OUTCOME-FRACTIONAL-AUTH", "OUTCOME-Y-MUTATION",
    "PREDICTION-INTERVAL-AUTH", "ENVIRONMENT-PROBE-VALID",
    "ENVIRONMENT-BANANA", "ENVIRONMENT-FALSE-VERSION",
    "CONTEXT-FACTORY-VALID", "CONTEXT-FAKE-DIRECT",
    "NONESTIMABILITY-VALID", "NONESTIMABILITY-EXPECTED-HASH",
    "RUN-RECEIPT-VALID", "RUN-RECEIPT-WRONG-OUTCOME",
    "CHECKPOINT-VALID", "CHECKPOINT-CORRUPT",
    "UNIVERSE-AUTHORITY", "UNIVERSE-MISSING-UNIT",
    "RF-FIVE-AUTHENTIC", "RF-INVENTED-HASH", "RF-SD-DDOF0",
    "METRIC-ROLES", "METRIC-SINGLE-CLASS", "METRIC-DENOMINATOR",
    "GENERATION-ARBITRARY-LEDGER",
    "GENERATION-MARKER-LAST",
)
BEHAVIORAL_TEST_REGISTRY = tuple(
    BehavioralTestSpec(test_id, "BEHAVIORAL", test_id.replace("-", " "),
                       f"scripts/validate_paper1_g06_2e.py:behavioral_case:{test_id}")
    for test_id in _G06_2E_BEHAVIORAL_IDS
)
STATIC_TEST_REGISTRY = tuple(
    BehavioralTestSpec(test_id, "STATIC_AUTHORITY", test_id.replace("-", " "),
                       f"scripts/validate_paper1_g06_2e.py:static_case:{test_id}")
    for test_id in (
        "STATIC-HEAD", "STATIC-G05A-HASH", "STATIC-G05B-HASH",
        "STATIC-METRIC-HASH", "STATIC-RF-HASH", "STATIC-NO-RESULTS",
        "STATIC-AUTHORITY-IMMUTABLE", "STATIC-FACADE-SURFACE",
        "STATIC-SYNTHETIC-ONLY",
    )
)
BEHAVIORAL_UNIVERSE_SHA256 = _test_registry_hash(BEHAVIORAL_TEST_REGISTRY)
STATIC_UNIVERSE_SHA256 = _test_registry_hash(STATIC_TEST_REGISTRY)

FRESH_PROCESS_TEST_IDS = (
    "FRESH-GEN-WRONG-HEAD",
    "FRESH-GEN-WRONG-RUNTIME-HASH",
    "FRESH-GEN-WRONG-VALIDATOR-HASH",
    "FRESH-GEN-WRONG-BEHAVIORAL-UNIVERSE",
    "FRESH-GEN-WRONG-PUBLICATION-PROTOCOL",
    "FRESH-GEN-FALSE-DECISION-FITTING-AUTHORIZED",
    "FRESH-GEN-FALSE-DECISION-MODEL-FITTING-AUTHORIZED",
    "FRESH-GEN-FALSE-DECISION-G07-AUTHORIZED",
    "FRESH-GEN-FALSE-DECISION-MODEL-FIT",
    "FRESH-GEN-FALSE-DECISION-REAL-PREDICTIONS",
    "FRESH-GEN-FALSE-DECISION-PERFORMANCE-INSPECTED",
    "FRESH-GEN-FALSE-DECISION-GATE-STATUS",
    "FRESH-GEN-STALE-CORRECTION-PAYLOAD",
    "FRESH-GEN-MIXED-SEMANTIC-PAYLOAD",
    "FRESH-GEN-MISSING-MARKER",
    "FRESH-GEN-PAYLOAD-BYTE-MUTATION",
)
FRESH_PROCESS_EXPECTED_REASONS = MappingProxyType({
    "FRESH-GEN-WRONG-HEAD": "ERR_GENERATION_GIT_HEAD_AUTHORITY",
    "FRESH-GEN-WRONG-RUNTIME-HASH": "ERR_GENERATION_RUNTIME_AUTHORITY",
    "FRESH-GEN-WRONG-VALIDATOR-HASH": "ERR_GENERATION_VALIDATOR_AUTHORITY",
    "FRESH-GEN-WRONG-BEHAVIORAL-UNIVERSE": "ERR_GENERATION_BEHAVIORAL_UNIVERSE_AUTHORITY",
    "FRESH-GEN-WRONG-PUBLICATION-PROTOCOL": "ERR_GENERATION_PUBLICATION_PROTOCOL",
    "FRESH-GEN-FALSE-DECISION-FITTING-AUTHORIZED": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-MODEL-FITTING-AUTHORIZED": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-G07-AUTHORIZED": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-MODEL-FIT": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-REAL-PREDICTIONS": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-PERFORMANCE-INSPECTED": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-FALSE-DECISION-GATE-STATUS": "ERR_GENERATION_DECISION_SEMANTICS",
    "FRESH-GEN-STALE-CORRECTION-PAYLOAD": "ERR_GENERATION_SEMANTIC_PAYLOAD_STALE",
    "FRESH-GEN-MIXED-SEMANTIC-PAYLOAD": "ERR_GENERATION_TOP_LEVEL_AUTHORITY_QC",
    "FRESH-GEN-MISSING-MARKER": "ERR_GENERATION_MARKER_MISSING",
    "FRESH-GEN-PAYLOAD-BYTE-MUTATION": "ERR_GENERATION_PAYLOAD_IDENTITY",
})
FRESH_PROCESS_UNIVERSE_SHA256 = hashlib.sha256(
    canonical_json(list(FRESH_PROCESS_TEST_IDS))
).hexdigest()
INTEGRATION_UNIVERSE_SHA256 = hashlib.sha256(
    canonical_json(list(INTEGRATION_TEST_IDS))
).hexdigest()
FROZEN_CONTRACT_COMBINATION_COUNT = 352

G06_2E_REQUIRED_PAYLOADS = (
    "PAPER1_G06_2E_CORRECTION.md",
    "PAPER1_G06_2E_TOP_LEVEL_AUTHORITY_QC.csv",
    "PAPER1_G06_2E_DECISION_SEMANTICS_QC.csv",
    "PAPER1_G06_2E_FRESH_PROCESS_GENERATION_QC.csv",
    "PAPER1_G06_2E_TEST_EXECUTION.csv",
    "PAPER1_G06_2E_DECISION.csv",
)
G06_2E_MANIFEST_NAME = "PAPER1_G06_2E_GENERATION_MANIFEST.json"

G06_2E_DECISION_SEMANTICS = MappingProxyType({
    "gate": GENERATION_GATE_VERSION,
    "status": "COMPLETE",
    "g07_may_begin": "NO",
    "g08_status": "BLOCKED",
    "scientific_fitting_authorized": "NO",
    "model_fitting_authorized": "NO",
    "models_fit": "NO",
    "real_predictions_generated": "NO",
    "real_performance_inspected": "NO",
    "f04_provenance_status": "NONBLOCKING_PROVENANCE",
    "f04_downstream_requirement": (
        "TYPED_EXCEPTION_RECEIPT_OR_CALLER_REPORTED_UNAUTHENTICATED_BEFORE_SCIENTIFIC_RUN"
    ),
    "f05_code_quality_status": "NONBLOCKING_CODE_QUALITY_DEFERRED_POST_ACCEPTANCE_CLEANUP",
})


def _json_equal(left: object, right: object) -> bool:
    return canonical_json(left) == canonical_json(right)


_CURRENT_GENERATION_AUTHORITY_CACHE: dict[Path, Mapping[str, object]] = {}


def current_generation_authority(project_root: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    cached = _CURRENT_GENERATION_AUTHORITY_CACHE.get(root)
    if cached is not None:
        return cached
    _verify_authority_file(root, G05A_REGISTRY_SOURCE, G05A_REGISTRY_SOURCE_SHA256,
                           "ERR_GENERATION_G05A_AUTHORITY")
    _verify_authority_file(root, G05B_REGISTRY_SOURCE, G05B_REGISTRY_SOURCE_SHA256,
                           "ERR_GENERATION_G05B_AUTHORITY")
    _verify_authority_file(root, RF_AUTHORITY_SOURCE, RF_AUTHORITY_SHA256,
                           "ERR_GENERATION_RF_AUTHORITY")
    _verify_authority_file(root, METRIC_AUTHORITY_SOURCE, METRIC_AUTHORITY_SHA256,
                           "ERR_GENERATION_METRIC_AUTHORITY")
    authority = MappingProxyType({
        "gate_version": GENERATION_GATE_VERSION,
        "schema_version": GENERATION_SCHEMA_VERSION,
        "api_identity": API_IDENTITY,
        "git_head": _git_head(root),
        "facade_source_sha256": sha256_file(root / GENERATION_FACADE_SOURCE),
        "runtime_source_sha256": sha256_file(root / GENERATION_RUNTIME_SOURCE),
        "validator_source_sha256": sha256_file(root / GENERATION_VALIDATOR_SOURCE),
        "behavioral_universe_sha256": BEHAVIORAL_UNIVERSE_SHA256,
        "static_universe_sha256": STATIC_UNIVERSE_SHA256,
        "integration_universe_sha256": INTEGRATION_UNIVERSE_SHA256,
        "fresh_process_universe_sha256": FRESH_PROCESS_UNIVERSE_SHA256,
        "g05a_authority_sha256": G05A_REGISTRY_SOURCE_SHA256,
        "g05b_authority_sha256": G05B_REGISTRY_SOURCE_SHA256,
        "rf_authority_sha256": RF_AUTHORITY_SHA256,
        "metric_authority_sha256": METRIC_AUTHORITY_SHA256,
        "behavioral_test_count": len(BEHAVIORAL_TEST_REGISTRY),
        "static_test_count": len(STATIC_TEST_REGISTRY),
        "integration_test_count": len(INTEGRATION_TEST_IDS),
        "fresh_process_test_count": len(FRESH_PROCESS_TEST_IDS),
        "contract_combination_count": FROZEN_CONTRACT_COMBINATION_COUNT,
        "required_payload_roles": list(G06_2E_REQUIRED_PAYLOADS),
        "publication_protocol": GENERATION_PUBLICATION_PROTOCOL,
        "decision_status": "COMPLETE",
    })
    _CURRENT_GENERATION_AUTHORITY_CACHE[root] = authority
    return authority


def _assemble_validated_test_run(root: Path, validator_path: Path,
                                 behavioral: tuple[tuple[str, str, str], ...],
                                 static: tuple[tuple[str, str, str], ...],
                                 integration: tuple[tuple[str, str, str], ...]) -> ValidatedTestRun:
    authority = current_generation_authority(root)
    payload = {
        "schema_version": VALIDATED_TEST_RUN_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "runtime_source_sha256": authority["runtime_source_sha256"],
        "facade_source_sha256": authority["facade_source_sha256"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "behavioral_universe_sha256": authority["behavioral_universe_sha256"],
        "static_universe_sha256": authority["static_universe_sha256"],
        "behavioral_results": behavioral,
        "static_results": static,
        "integration_results": integration,
        "contract_combination_count": authority["contract_combination_count"],
        "execution_identity": hashlib.sha256(canonical_json({
            "behavioral": behavioral, "static": static, "integration": integration,
            "authority": dict(authority),
        })).hexdigest(),
        "status": "PASS",
    }
    receipt = ValidatedTestRun(
        **payload, receipt_sha256=hashlib.sha256(canonical_json(payload)).hexdigest()
    )
    _ISSUED_VALIDATED_TEST_RUNS[id(receipt)] = receipt
    return receipt


def _validate_test_run_current(root: Path, run: ValidatedTestRun,
                               require_issued: bool) -> None:
    if not isinstance(run, ValidatedTestRun):
        raise ContractError("ERR_VALIDATED_TEST_RUN_TYPE")
    if require_issued and _ISSUED_VALIDATED_TEST_RUNS.get(id(run)) is not run:
        raise ContractError("ERR_VALIDATED_TEST_RUN_NOT_ISSUED")
    payload = asdict(run)
    receipt = payload.pop("receipt_sha256")
    if hashlib.sha256(canonical_json(payload)).hexdigest() != receipt:
        raise ContractError("ERR_VALIDATED_TEST_RUN_RECEIPT")
    authority = current_generation_authority(root)
    expected = {
        "schema_version": VALIDATED_TEST_RUN_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "runtime_source_sha256": authority["runtime_source_sha256"],
        "facade_source_sha256": authority["facade_source_sha256"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "behavioral_universe_sha256": authority["behavioral_universe_sha256"],
        "static_universe_sha256": authority["static_universe_sha256"],
        "contract_combination_count": authority["contract_combination_count"],
        "status": "PASS",
    }
    if any(getattr(run, field) != value for field, value in expected.items()):
        raise ContractError("ERR_VALIDATED_TEST_RUN_STALE")
    expected_sets = (
        (run.behavioral_results, tuple(spec.test_id for spec in BEHAVIORAL_TEST_REGISTRY)),
        (run.static_results, tuple(spec.test_id for spec in STATIC_TEST_REGISTRY)),
        (run.integration_results, INTEGRATION_TEST_IDS),
    )
    for rows, ids in expected_sets:
        if tuple(row[0] for row in rows) != ids or len({row[0] for row in rows}) != len(rows):
            raise ContractError("ERR_VALIDATED_TEST_RUN_EXECUTED_SET")
        if any(row[1] != "PASS" for row in rows):
            raise ContractError("ERR_VALIDATED_TEST_RUN_FAILURE")


def _validated_test_frame(run: ValidatedTestRun) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for provenance, values in (
        ("BEHAVIORAL", run.behavioral_results),
        ("STATIC_AUTHORITY", run.static_results),
        ("INTEGRATION_LIFECYCLE", run.integration_results),
    ):
        rows.extend({"test_id": test_id, "provenance_class": provenance,
                     "result": result, "observed_reason": reason}
                    for test_id, result, reason in values)
    return pd.DataFrame(rows, columns=["test_id", "provenance_class", "result", "observed_reason"])


def _expected_fresh_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"test_id": test_id, "provenance_class": "FRESH_PROCESS_DISK_GENERATION",
         "result": "PASS", "observed_reason": FRESH_PROCESS_EXPECTED_REASONS[test_id]}
        for test_id in FRESH_PROCESS_TEST_IDS
    ])


def _normalize_decision_value(value: object) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "YES" if bool(value) else "NO"
    return str(value).strip().upper()


def _validate_decision_semantics(raw: bytes) -> None:
    try:
        frame = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:
        raise ContractError("ERR_GENERATION_DECISION_SEMANTICS") from exc
    if len(frame) != 1 or set(frame.columns) != set(G06_2E_DECISION_SEMANTICS):
        raise ContractError("ERR_GENERATION_DECISION_SEMANTICS")
    row = frame.iloc[0]
    for field, expected in G06_2E_DECISION_SEMANTICS.items():
        if _normalize_decision_value(row[field]) != _normalize_decision_value(expected):
            raise ContractError("ERR_GENERATION_DECISION_SEMANTICS")


def _authority_qc_expected(authority: Mapping[str, object]) -> pd.DataFrame:
    return pd.DataFrame([
        {"authority_field": field,
         "expected_value": json.dumps(value, sort_keys=True, separators=(",", ":")),
         "result": "PASS"}
        for field, value in authority.items()
    ])


def _validate_generation_payload_content(root: Path, validated_run: ValidatedTestRun,
                                         staged: Mapping[str, bytes]) -> None:
    if set(staged) != set(G06_2E_REQUIRED_PAYLOADS):
        raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_SET")
    authority = current_generation_authority(root)
    correction = staged["PAPER1_G06_2E_CORRECTION.md"].decode("utf-8", errors="strict")
    required_lines = (
        f"gate={GENERATION_GATE_VERSION}",
        f"git_head={authority['git_head']}",
        f"runtime_source_sha256={authority['runtime_source_sha256']}",
        f"facade_source_sha256={authority['facade_source_sha256']}",
        f"validator_source_sha256={authority['validator_source_sha256']}",
    )
    if any(line not in correction for line in required_lines):
        raise ContractError("ERR_GENERATION_SEMANTIC_PAYLOAD_STALE")
    observed_authority = pd.read_csv(io.BytesIO(
        staged["PAPER1_G06_2E_TOP_LEVEL_AUTHORITY_QC.csv"]
    ), dtype=str, keep_default_na=False)
    expected_authority = _authority_qc_expected(authority).astype(str)
    if not observed_authority.equals(expected_authority):
        raise ContractError("ERR_GENERATION_TOP_LEVEL_AUTHORITY_QC")
    decision_qc = pd.read_csv(io.BytesIO(
        staged["PAPER1_G06_2E_DECISION_SEMANTICS_QC.csv"]
    ), dtype=str, keep_default_na=False)
    required_decision_attacks = (
        "FALSE-FITTING-AUTHORIZED", "FALSE-G07-AUTHORIZED", "FALSE-MODELS-FIT",
        "FALSE-PREDICTIONS-GENERATED", "FALSE-PERFORMANCE-INSPECTED",
        "FALSE-GATE-OR-STATUS",
    )
    if (tuple(decision_qc.get("test_id", ())) != required_decision_attacks or
            not decision_qc.get("result", pd.Series(dtype=str)).eq("PASS").all() or
            not decision_qc.get("observed_reason", pd.Series(dtype=str)).eq(
                "ERR_GENERATION_DECISION_SEMANTICS").all()):
        raise ContractError("ERR_GENERATION_DECISION_QC")
    fresh = pd.read_csv(io.BytesIO(
        staged["PAPER1_G06_2E_FRESH_PROCESS_GENERATION_QC.csv"]
    ), dtype=str, keep_default_na=False)
    if not fresh.equals(_expected_fresh_frame().astype(str)):
        raise ContractError("ERR_GENERATION_FRESH_PROCESS_QC")
    tests = pd.read_csv(io.BytesIO(staged["PAPER1_G06_2E_TEST_EXECUTION.csv"]),
                        dtype=str, keep_default_na=False)
    expected_tests = pd.concat(
        [_validated_test_frame(validated_run), _expected_fresh_frame()], ignore_index=True
    ).astype(str)
    if not tests.equals(expected_tests):
        raise ContractError("ERR_GENERATION_TEST_LEDGER_BINDING")
    _validate_decision_semantics(staged["PAPER1_G06_2E_DECISION.csv"])


def build_validated_generation_payloads(
        project_root: Path, validated_run: ValidatedTestRun,
        payload_builder: Callable[[ValidatedTestRun], Mapping[str, bytes]],
        validator_source: Path) -> ValidatedGenerationPayloads:
    root = Path(project_root).resolve()
    validator_path = Path(validator_source).resolve()
    _validate_test_run_current(root, validated_run, True)
    _validate_runner_callable(payload_builder, validator_path, "generation_payloads")
    staged = {name: bytes(content) for name, content in payload_builder(validated_run).items()}
    _validate_generation_payload_content(root, validated_run, staged)
    payloads = tuple((name, staged[name]) for name in G06_2E_REQUIRED_PAYLOADS)
    payload_hashes = tuple((name, hashlib.sha256(content).hexdigest()) for name, content in payloads)
    authority = current_generation_authority(root)
    receipt_authority = {
        "schema_version": VALIDATED_PAYLOAD_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "validated_test_run_receipt_sha256": validated_run.receipt_sha256,
        "payload_sha256s": payload_hashes,
    }
    bundle = ValidatedGenerationPayloads(
        **receipt_authority, payloads=payloads,
        receipt_sha256=hashlib.sha256(canonical_json(receipt_authority)).hexdigest(),
    )
    _ISSUED_GENERATION_PAYLOADS[id(bundle)] = bundle
    return bundle


def _validate_generation_payload_bundle(root: Path, validated_run: ValidatedTestRun,
                                        bundle: ValidatedGenerationPayloads,
                                        require_issued: bool) -> dict[str, bytes]:
    if not isinstance(bundle, ValidatedGenerationPayloads):
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_TYPE")
    if require_issued and _ISSUED_GENERATION_PAYLOADS.get(id(bundle)) is not bundle:
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_NOT_ISSUED")
    staged = dict(bundle.payloads)
    hashes = tuple((name, hashlib.sha256(content).hexdigest()) for name, content in bundle.payloads)
    authority = current_generation_authority(root)
    expected = {
        "schema_version": VALIDATED_PAYLOAD_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "validated_test_run_receipt_sha256": validated_run.receipt_sha256,
        "payload_sha256s": hashes,
    }
    observed = {
        "schema_version": bundle.schema_version,
        "gate_version": bundle.gate_version,
        "git_head": bundle.git_head,
        "validator_source_sha256": bundle.validator_source_sha256,
        "validated_test_run_receipt_sha256": bundle.validated_test_run_receipt_sha256,
        "payload_sha256s": bundle.payload_sha256s,
    }
    if observed != expected or hashlib.sha256(canonical_json(expected)).hexdigest() != bundle.receipt_sha256:
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_BINDING")
    _validate_generation_payload_content(root, validated_run, staged)
    return staged


def _manifest_metadata(authority: Mapping[str, object], run: ValidatedTestRun,
                       bundle: ValidatedGenerationPayloads) -> dict[str, object]:
    return {
        **dict(authority),
        "validated_payload_bundle_receipt_sha256": bundle.receipt_sha256,
        "validated_test_run": asdict(run),
    }


def publish_validation_generation(project_root: Path, directory: Path,
                                  validated_run: ValidatedTestRun,
                                  payload_bundle: ValidatedGenerationPayloads,
                                  fail_after: int | None = None) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    _validate_test_run_current(root, validated_run, True)
    staged = _validate_generation_payload_bundle(root, validated_run, payload_bundle, True)
    authority = current_generation_authority(root)
    entries = {name: {"sha256": hashlib.sha256(content).hexdigest(),
                      "bytes": len(content), "role": name}
               for name, content in staged.items()}
    metadata = _manifest_metadata(authority, validated_run, payload_bundle)
    generation_id = hashlib.sha256(canonical_json({
        "metadata": metadata, "payloads": entries
    })).hexdigest()
    manifest = {**metadata, "generation_id": generation_id, "payloads": entries}
    directory = Path(directory)
    for index, name in enumerate(G06_2E_REQUIRED_PAYLOADS, start=1):
        _atomic_bytes(directory / name, staged[name])
        if fail_after == index:
            raise ContractError("ERR_INJECTED_PUBLICATION_FAILURE")
    _atomic_bytes(directory / G06_2E_MANIFEST_NAME, canonical_json(manifest))
    return MappingProxyType(manifest)


def _require_manifest_authority(manifest: Mapping[str, object],
                                authority: Mapping[str, object]) -> None:
    errors = {
        "gate_version": "ERR_GENERATION_GATE_AUTHORITY",
        "schema_version": "ERR_GENERATION_SCHEMA_AUTHORITY",
        "api_identity": "ERR_GENERATION_API_AUTHORITY",
        "git_head": "ERR_GENERATION_GIT_HEAD_AUTHORITY",
        "facade_source_sha256": "ERR_GENERATION_FACADE_AUTHORITY",
        "runtime_source_sha256": "ERR_GENERATION_RUNTIME_AUTHORITY",
        "validator_source_sha256": "ERR_GENERATION_VALIDATOR_AUTHORITY",
        "behavioral_universe_sha256": "ERR_GENERATION_BEHAVIORAL_UNIVERSE_AUTHORITY",
        "static_universe_sha256": "ERR_GENERATION_STATIC_UNIVERSE_AUTHORITY",
        "integration_universe_sha256": "ERR_GENERATION_INTEGRATION_UNIVERSE_AUTHORITY",
        "fresh_process_universe_sha256": "ERR_GENERATION_FRESH_UNIVERSE_AUTHORITY",
        "publication_protocol": "ERR_GENERATION_PUBLICATION_PROTOCOL",
        "decision_status": "ERR_GENERATION_DECISION_STATUS_AUTHORITY",
        "required_payload_roles": "ERR_GENERATION_REQUIRED_PAYLOAD_AUTHORITY",
    }
    for field, expected in authority.items():
        if not _json_equal(manifest.get(field), expected):
            raise ContractError(errors.get(field, "ERR_GENERATION_CURRENT_AUTHORITY"))


def validate_validation_generation(project_root: Path, directory: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    directory = Path(directory)
    marker = directory / G06_2E_MANIFEST_NAME
    if not marker.is_file():
        raise ContractError("ERR_GENERATION_MARKER_MISSING")
    try:
        manifest = json.loads(marker.read_text(encoding="ascii"))
    except Exception as exc:
        raise ContractError("ERR_GENERATION_MANIFEST_SCHEMA") from exc
    authority = current_generation_authority(root)
    _require_manifest_authority(manifest, authority)
    declared = manifest.get("payloads", {})
    if set(declared) != set(G06_2E_REQUIRED_PAYLOADS):
        raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_SET")
    payloads: dict[str, bytes] = {}
    for name in G06_2E_REQUIRED_PAYLOADS:
        path = directory / name
        if not path.is_file():
            raise ContractError("ERR_GENERATION_REQUIRED_PAYLOAD_SET")
        raw = path.read_bytes()
        identity = declared[name]
        if (identity.get("role") != name or identity.get("bytes") != len(raw) or
                identity.get("sha256") != hashlib.sha256(raw).hexdigest()):
            raise ContractError("ERR_GENERATION_PAYLOAD_IDENTITY")
        payloads[name] = raw
    run_data = dict(manifest.get("validated_test_run", {}))
    for field in ("behavioral_results", "static_results", "integration_results"):
        run_data[field] = tuple(tuple(row) for row in run_data.get(field, ()))
    try:
        run = ValidatedTestRun(**run_data)
    except Exception as exc:
        raise ContractError("ERR_VALIDATED_TEST_RUN_SCHEMA") from exc
    _validate_test_run_current(root, run, False)
    shared = {
        "git_head": "git_head",
        "runtime_source_sha256": "runtime_source_sha256",
        "facade_source_sha256": "facade_source_sha256",
        "validator_source_sha256": "validator_source_sha256",
        "behavioral_universe_sha256": "behavioral_universe_sha256",
        "static_universe_sha256": "static_universe_sha256",
        "contract_combination_count": "contract_combination_count",
    }
    if any(not _json_equal(manifest.get(top), getattr(run, field))
           for top, field in shared.items()):
        raise ContractError("ERR_GENERATION_TEST_RUN_TOP_LEVEL_CONSISTENCY")
    _validate_generation_payload_content(root, run, payloads)
    payload_hashes = tuple((name, hashlib.sha256(payloads[name]).hexdigest())
                           for name in G06_2E_REQUIRED_PAYLOADS)
    receipt_authority = {
        "schema_version": VALIDATED_PAYLOAD_SCHEMA_VERSION,
        "gate_version": GENERATION_GATE_VERSION,
        "git_head": authority["git_head"],
        "validator_source_sha256": authority["validator_source_sha256"],
        "validated_test_run_receipt_sha256": run.receipt_sha256,
        "payload_sha256s": payload_hashes,
    }
    expected_bundle = hashlib.sha256(canonical_json(receipt_authority)).hexdigest()
    if manifest.get("validated_payload_bundle_receipt_sha256") != expected_bundle:
        raise ContractError("ERR_VALIDATED_PAYLOAD_BUNDLE_BINDING")
    pseudo_bundle = ValidatedGenerationPayloads(
        **receipt_authority, payloads=tuple((name, payloads[name]) for name in G06_2E_REQUIRED_PAYLOADS),
        receipt_sha256=expected_bundle,
    )
    metadata = _manifest_metadata(authority, run, pseudo_bundle)
    expected_generation = hashlib.sha256(canonical_json({
        "metadata": metadata, "payloads": declared
    })).hexdigest()
    if manifest.get("generation_id") != expected_generation:
        raise ContractError("ERR_GENERATION_IDENTITY")
    return MappingProxyType(manifest)


# The G06.2g overlay is intentionally captured before the retained G06.2e
# implementation above. Restore those bindings last so the public module
# exposes only the corrected G06.2g generation contract.
globals().update(_G06_2G_BINDINGS)
