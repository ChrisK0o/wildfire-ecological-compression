"""Paper 1 G07 production-runner implementation.

The module provides a fail-closed production plan and a fully isolated synthetic
validation lifecycle. Scientific execution is deliberately unavailable until a
later gate supplies an authenticated authorization mechanism.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import inspect
from io import StringIO
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

import src.paper1_g06_2_runtime as g06
from src import paper1_g06_evaluation as evaluation_authority
from src import paper1_g06_4e_runtime as g06_4e
from src import paper1_g06_4f_runtime as g06_4f
from src import paper1_g05a_contract_oracle as schema_oracle
from src import paper1_g05a_comparators as comparators
from src import paper1_analysis_registry as analysis_registry
from src import paper1_pr34_modeling as model_spec
from src import paper1_g07_v2_policy as v2_policy


GATE_VERSION = "PAPER1_G07"
SCHEMA_VERSION = "PAPER1_G07_PRODUCTION_RUNNER_V2"
SYNTHETIC_SCHEMA_VERSION = "PAPER1_G07_SYNTHETIC_V2"
PREDICTION_STAGE_SCHEMA_VERSION = "PAPER1_G07_V2_PREDICTION_STAGE_RECEIPT_V1"
RF_SEED_METRIC_SCHEMA_VERSION = "PAPER1_G07_V2_RF_SEED_METRICS_V2"
SCIENTIFIC_RF_TREES = 1000
SCIENTIFIC_BOOTSTRAP_REPLICATES = 10_000
SYNTHETIC_RF_TREES = 12
SYNTHETIC_BOOTSTRAP_REPLICATES = 31
PRIMARY_SEED = 20200908
RF_SEEDS = (20200908, 20200909, 20200910, 20200911, 20200912)
LOGISTIC_CANDIDATES = (0.1, 1.0)
RF_LEAF_CANDIDATES = (0.02, 0.05)
GEOMETRY_FIELDS = (
    "distance_active_front_km",
    "distance_cumulative_perimeter_km",
    "hybrid_membership",
    "log1p_t0_area_km2",
)
NO_EARLY_INTERVALS = (4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22)
PRIMARY_HELDOUT_INTERVALS = (6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22)
LOIO_METRICS = ("log_loss_benefit", "brier_benefit")
LOIO_PHASES = (
    "INPUTS_VALIDATED", "RESULT_WRITTEN", "TERMINAL_EVIDENCE_WRITTEN", "COMPLETE",
)
LOIO_RESULT_COLUMNS = (
    "metric_id", "omitted_interval", "affected_block", "full_estimate",
    "omitted_estimate", "absolute_change", "rank",
)
LOIO_SOURCE_EVALUATIONS = (
    "B1_TO_B2", "B1_B2_TO_B3", "B1_B2_B3_TO_B4",
)
LOIO_INTERVAL_BLOCKS = MappingProxyType({
    6: "B2", 8: "B2", 9: "B2", 10: "B2",
    11: "B3", 12: "B3", 14: "B3", 15: "B3",
    16: "B4", 18: "B4", 21: "B4", 22: "B4",
})
EXPECTED_UNIVERSE = MappingProxyType({
    "g05a": 305,
    "g05b": 47,
    "total": 352,
    "registry_executable": 347,
    "nonestimable": 4,
    "disabled": 5,
    "authority_blocked": 0,
})
CHECKPOINT_STAGES = (
    "INITIALIZED",
    "TUNED",
    "SEED_PREDICTION_WRITTEN",
    "METRICS_WRITTEN",
    "FINALIZED",
)
PRODUCTION_PHASES = (
    "INITIALIZED", "INPUTS_VALIDATED", "TUNING_IN_PROGRESS", "TUNED",
    "FINAL_MODEL_READY", "PREDICTION_WRITTEN", "METRICS_WRITTEN",
    "POSTPREDICTION_EVIDENCE_WRITTEN", "PUBLICATION_VALIDATED",
    "TERMINAL_EVIDENCE_WRITTEN", "COMPLETE",
)
RESUME_IDENTITY_MIGRATION_SCHEMA_VERSION = (
    "PAPER1_G07_GOVERNED_RESUME_IDENTITY_MIGRATION_V1"
)
RESUME_IDENTITY_MIGRATION_ELIGIBLE_CONTRACT_FIELDS = frozenset({"git_head"})
TUNING_SPLITS = MappingProxyType({
    "B1_TO_B2": (((1, 3), (4,)), ((1, 3, 4), (5,))),
    "B1_B2_TO_B3": tuple(((1, 3, 4, 5), (value,)) for value in (6, 8, 9, 10)),
    "B1_B2_B3_TO_B4": (
        *tuple(((1, 3, 4, 5), (value,)) for value in (6, 8, 9, 10)),
        *tuple(((1, 3, 4, 5, 6, 8, 9, 10), (value,)) for value in (11, 12, 14, 15)),
    ),
})


class RunnerError(RuntimeError):
    """A fail-closed runner condition."""


def fractional_environment_ready() -> bool:
    """Return whether the exact governed fractional runtime is locally available."""
    try:
        versions = {
            name: importlib.metadata.version(name)
            for name in ("statsmodels", "patsy")
        }
    except importlib.metadata.PackageNotFoundError:
        return False
    return (
        versions == {"statsmodels": "0.14.6", "patsy": "1.0.2"}
        and callable(globals().get("dispatch_fractional_glm"))
        and callable(globals().get("_fit_fractional_probabilities"))
    )


def expected_environment_dispositions(fractional_unit_count: int) -> Mapping[str, int]:
    if fractional_unit_count < 0:
        raise RunnerError("G07_FRACTIONAL_UNIT_COUNT")
    blocked = 0 if fractional_environment_ready() else fractional_unit_count
    return MappingProxyType({
        "runner_resolvable": (
            EXPECTED_UNIVERSE["registry_executable"]
            - EXPECTED_UNIVERSE["nonestimable"]
            - blocked
        ),
        "environment_blocked": blocked,
    })


class ControlledInterruption(RuntimeError):
    """Synthetic validation interruption at a governed checkpoint."""


class PairDependenciesPending(ControlledInterruption):
    """Nonterminal pause while governed paired-source artifacts are incomplete."""

    def __init__(self, missing_unit_ids: Sequence[str]):
        self.missing_unit_ids = tuple(sorted(str(item) for item in missing_unit_ids))
        super().__init__("G07_V2_PAIR_DEPENDENCIES_PENDING:" + ",".join(self.missing_unit_ids))


class RunnerMode(str, Enum):
    SCIENTIFIC = "SCIENTIFIC"
    SYNTHETIC = "SYNTHETIC_TEST"


class TerminalDisposition(str, Enum):
    COMPLETE = "COMPLETE"
    FAILED_RUNTIME = "FAILED_RUNTIME"
    ENVIRONMENT_BLOCKED = "ENVIRONMENT_BLOCKED"
    NONESTIMABLE = "NONESTIMABLE"
    DISABLED = "DISABLED"


class DispatchDisposition(str, Enum):
    EXECUTABLE = "EXECUTABLE_RUNNER"
    DISABLED = "MACHINE_DISABLED_NONEXECUTING"
    ENVIRONMENT_BLOCKED = "ENVIRONMENT_BLOCKED"
    NONESTIMABLE = "GOVERNED_NONESTIMABLE"
    AUTHORITY_BLOCKED = "G06_FACADE_AUTHORITY_BLOCKED"


@dataclass(frozen=True)
class RunnerConfiguration:
    mode: RunnerMode
    rf_trees: int
    bootstrap_replicates: int
    rf_seeds: tuple[int, ...]
    bootstrap_seed: int


@dataclass(frozen=True)
class DispatchPlanEntry:
    unit_id: str
    contract_sha256: str
    analysis_id: str
    analysis_family: str
    model_family: str
    model_role: str
    resolution_m: int
    risk_set_id: str
    evaluation_identity: str
    training_intervals: tuple[int, ...]
    heldout_intervals: tuple[int, ...]
    environment_requirement: str
    disposition: DispatchDisposition
    handler_identity: str
    mode: RunnerMode


@dataclass(frozen=True)
class FacadeCapabilityGap:
    gap_id: str
    affected_scope: str
    missing_authority: str
    consequence: str


@dataclass(frozen=True)
class GovernedModelSchema:
    unit_id: str
    comparator_identity: str
    model_family: str
    model_role: str
    transformed_fields: tuple[str, ...]
    schema_sha256: str


@dataclass(frozen=True)
class TuningReceipt:
    schema_version: str
    model_family: str
    model_role: str
    outer_evaluation: str
    candidates: tuple[float, ...]
    splits: tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]
    split_scores: tuple[tuple[float, int, float], ...]
    candidate_scores: tuple[tuple[float, float], ...]
    selected_hyperparameter: float
    tie_rule: str
    tuning_seed: int
    training_preprocessing_sha256s: tuple[str, ...]
    candidate_prediction_receipts: tuple[tuple[float, int, str], ...]
    receipt_sha256: str


@dataclass(frozen=True)
class PersistedArtifactReceipt:
    schema_version: str
    role: str
    relative_path: str
    artifact_sha256: str
    artifact_bytes: int
    row_count: int
    key_sha256: str
    content_sha256: str
    receipt_sha256: str


@dataclass(frozen=True)
class RuntimeFailureReceipt:
    schema_version: str
    run_context_identity: str
    contract_sha256: str
    stage: str
    exception_type: str
    sanitized_message: str
    traceback_sha256: str
    artifact_path: str
    artifact_sha256: str
    evidence_classification: str
    receipt_sha256: str


@dataclass(frozen=True)
class CallerReportedFailure:
    schema_version: str
    terminal_disposition: TerminalDisposition
    evidence_classification: str
    exception_type: str
    sanitized_message: str


@dataclass(frozen=True)
class TerminalRecord:
    schema_version: str
    disposition: TerminalDisposition
    prediction_available: bool
    exception_metadata: RuntimeFailureReceipt | CallerReportedFailure | None


@dataclass(frozen=True)
class SyntheticRunResult:
    schema_version: str
    run_id: str
    mode: RunnerMode
    state: str
    resumed: bool
    completed_stages: tuple[str, ...]
    selected_hyperparameters: tuple[tuple[str, float], ...]
    prediction_receipts: tuple[tuple[str, str], ...]
    metric_receipts: tuple[tuple[str, str], ...]
    bootstrap_receipts: tuple[tuple[str, str], ...]
    scientific_payload_sha256: str
    model_fit_count: int
    child_process_count: int


@dataclass(frozen=True)
class ProductionExecutionRequest:
    """A requested governed unit; authority is established from persisted evidence."""

    unit_id: str
    run_id: str
    output_root: Path
    input_manifest_path: Path | None = None
    resume: bool = False
    interrupt_after: str | None = None
    injected_failure_stage: str | None = None
    caller_failure: CallerReportedFailure | None = None
    loio_source_manifest_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class AuthenticatedExecutionInput:
    evidence_classification: str
    validation_root: str
    frame: pd.DataFrame
    input_artifacts: tuple[Mapping[str, object], ...]
    source_manifest_sha256: str
    source_manifest_path: str
    authorized_hyperparameters: Mapping[str, object]


@dataclass(frozen=True)
class ProductionExecutionResult:
    schema_version: str
    run_id: str
    unit_id: str
    disposition: TerminalDisposition
    evidence_classification: str
    completed_phases: tuple[str, ...]
    selected_hyperparameter: float | None
    prediction_path: str | None
    metrics_path: str | None
    terminal_evidence_path: str
    manifest_path: str
    manifest_sha256: str
    checkpoint_count: int
    resumed: bool
    model_fit_count: int


@dataclass(frozen=True)
class _GovernedBenchmarkBinding:
    contract_sha256: str
    benchmark_id: str
    benchmark_type: str
    model_family: str
    model_role: str
    evaluation_identity: str
    training_intervals: tuple[int, ...]
    heldout_intervals: tuple[int, ...]


@dataclass(frozen=True)
class _DispatchContext:
    project_root: Path
    request: ProductionExecutionRequest
    plan_entry: DispatchPlanEntry
    contract: g06.ExecutionContract
    authorization_receipt: object
    capability: object
    pair_validation_scope: _PairValidationScope | None = None


@dataclass
class _PairValidationScope:
    """Ephemeral global-scan proof; never a persisted authorization capability."""

    active: bool = True
    proof: tuple[str, str, str] | None = None


_DISPATCH_CAPABILITY = object()


SCIENTIFIC_CONFIGURATION = RunnerConfiguration(
    RunnerMode.SCIENTIFIC,
    SCIENTIFIC_RF_TREES,
    SCIENTIFIC_BOOTSTRAP_REPLICATES,
    RF_SEEDS,
    PRIMARY_SEED,
)
SYNTHETIC_CONFIGURATION = RunnerConfiguration(
    RunnerMode.SYNTHETIC,
    SYNTHETIC_RF_TREES,
    SYNTHETIC_BOOTSTRAP_REPLICATES,
    RF_SEEDS,
    PRIMARY_SEED,
)


FACADE_CAPABILITY_GAPS = (
    FacadeCapabilityGap(
        "G07-G06-GAP-01",
        "24 REALIZED_WEATHER execution contracts",
        "The G06 contract authenticates the PR23 predictor table, but that table has no "
        "realized-weather fields and the facade exposes no authenticated secondary-source handle.",
        "The frozen five-field forecast-to-realized replacement cannot be executed or receipted "
        "without adding an authority path outside the accepted facade.",
    ),
    FacadeCapabilityGap(
        "G07-G06-GAP-02",
        "20 executable G05B boundary-exclusion contracts",
        "The authenticated G06 outcome handle exposes only keys, interval_number, and response; "
        "within_either_boundary_500m and within_either_boundary_1000m are not exposed.",
        "The required response-QC row filters cannot be reconstructed through the accepted facade.",
    ),
    FacadeCapabilityGap(
        "G07-G06-GAP-03",
        "training-history prevalence and four-field geometry benchmarks",
        "The 352-unit G06 universe has no benchmark execution contracts or prediction identities.",
        "G06 prediction and receipt writers cannot persist either required benchmark under an "
        "authentic governed model-family identity.",
    ),
    FacadeCapabilityGap(
        "G07-G06-GAP-04",
        "all G07 run-plan construction at accepted HEAD 9074bbd",
        "The committed G06.2g generation manifest is bound to Git HEAD 27a8d30, while the "
        "accepted G07 starting HEAD is 9074bbd; validate_validation_generation rejects it with "
        "ERR_GENERATION_GIT_HEAD_AUTHORITY.",
        "G07 cannot authenticate the accepted G06 generation or construct a production run plan "
        "without bypassing the facade's publication authority.",
    ),
)


def _accepted_g06_4e_facade() -> bool:
    """Recognize only the exact accepted G06.4e production-facade contract."""
    manifest = getattr(g06, "PRODUCTION_API_MANIFEST", {})
    required_g06 = {
        "authenticate_realized_weather_for_contract": "src.paper1_g06_4_runtime",
        "authenticate_boundary_filter_for_contract": "src.paper1_g06_4_runtime",
        "g06_4e_lifecycle_authority": "src.paper1_g06_4e_runtime",
        "governed_geometry_contract": "src.paper1_g06_4e_runtime",
        "validate_governed_geometry_contract": "src.paper1_g06_4e_runtime",
        "outcome_set_from_authenticated_artifact": "src.paper1_g06_4e_runtime",
        "validate_execution_manifest": "src.paper1_g06_4e_runtime",
        "integrity_validate_prediction_artifact": "src.paper1_g06_4e_runtime",
        "reconstruct_selected_c": "src.paper1_g06_4e_runtime",
        "reconstruct_training_prevalence": "src.paper1_g06_4e_runtime",
        "validate_prevalence_claim": "src.paper1_g06_4e_runtime",
        "governed_g07_evidence_requirements": "src.paper1_g06_4e_runtime",
        "recompute_prediction_metrics": "src.paper1_g06_4e_runtime",
    }
    required_g06_4f = (
        "governed_prevalence_contract",
        "governed_prevalence_contracts",
        "validate_governed_prevalence_contract",
        "governed_scoped_benchmark_contract",
        "governed_scoped_benchmark_contracts",
        "validate_governed_scoped_benchmark_contract",
        "reconstruct_scoped_training_prevalence",
        "validate_governed_geometry_selected_c",
    )
    return (
        getattr(g06, "__name__", None) == "src.paper1_g06_2_runtime"
        and getattr(g06_4f, "__name__", None) == "src.paper1_g06_4f_runtime"
        and manifest.get("production_import") == "src.paper1_g06_2_runtime"
        and manifest.get("compatibility_gate") == "PAPER1_G06.4e"
        and getattr(g06, "MANIFEST_SCHEMA_VERSION", None)
        == "PAPER1_G07_EXECUTION_MANIFEST_V1"
        and len(getattr(g06, "EXECUTION_MANIFEST_REQUIRED_FIELDS", ())) == 31
        and getattr(g06_4f, "G06_4F_GATE_VERSION", None) == "PAPER1_G06.4f"
        and getattr(g06_4f, "EXPECTED_CONTRACT_SET_SHA256", None)
        == "3a665d8d42639aee628d3f3bfd376658c79d611016eecf4de7ffca215ca21574"
        and getattr(g06_4f, "EXPECTED_SCOPED_CONTRACT_SET_SHA256", None)
        == "4a852c0aabc31ce78352f4b516a1c1d9d81ee33435c3a22cf573a0b6c23c8ffc"
        and getattr(g06_4f, "SCOPED_BENCHMARK_CONTRACT_COUNT", None) == 54
        and all(
            callable(getattr(g06, name, None))
            and getattr(getattr(g06, name), "__module__", None)
            == module_name
            for name, module_name in required_g06.items()
        )
        and all(
            callable(getattr(g06_4f, name, None))
            and getattr(getattr(g06_4f, name), "__module__", None)
            == "src.paper1_g06_4f_runtime"
            for name in required_g06_4f
        )
    )


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".part", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    _atomic_bytes(path, canonical_json(payload) + b"\n")


def _unit_id(contract: g06.ExecutionContract) -> str:
    return "|".join((
        contract.analysis_id,
        contract.model_family,
        contract.model_role,
        contract.evaluation_identity,
        str(contract.resolution_m),
    ))


def validate_configuration(configuration: RunnerConfiguration) -> None:
    if configuration.mode is RunnerMode.SCIENTIFIC:
        if configuration != SCIENTIFIC_CONFIGURATION:
            raise RunnerError("G07_SCIENTIFIC_CONFIGURATION_MUTATION")
    elif configuration.mode is RunnerMode.SYNTHETIC:
        if configuration != SYNTHETIC_CONFIGURATION:
            raise RunnerError("G07_SYNTHETIC_CONFIGURATION_MUTATION")
    else:
        raise RunnerError("G07_UNKNOWN_MODE")


def _handler_for(contract: g06.ExecutionContract) -> str:
    family = contract.analysis_family
    if not contract.execution_enabled:
        return "dispatch_machine_disabled"
    if contract.special_condition == "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE":
        return "dispatch_governed_nonestimable"
    if contract.environment_requirement == "statsmodels==0.14.6":
        return "dispatch_fractional_glm"
    if family == "LEAVE_ONE_INTERVAL_OUT_DIAGNOSTIC":
        return "dispatch_loio_diagnostic"
    if family == "SYMMETRIC_BLOCKED_TEMPORAL_CV":
        return "dispatch_symmetric_temporal_cv"
    if family.endswith("_CONFIDENCE"):
        return "dispatch_confidence_stratified_binary"
    return "dispatch_binary_model"


def _facade_gap_for(contract: g06.ExecutionContract) -> FacadeCapabilityGap | None:
    if _accepted_g06_4e_facade():
        return None
    if contract.analysis_family == "REALIZED_WEATHER":
        return FACADE_CAPABILITY_GAPS[0]
    if (
        contract.analysis_family == "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY"
        and contract.special_condition != "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE"
    ):
        return FACADE_CAPABILITY_GAPS[1]
    return None


def resolve_governed_model_schema(contract: g06.ExecutionContract) -> GovernedModelSchema:
    """Resolve the frozen transformed schema without loading outcomes or fitting models."""
    if not contract.execution_enabled or contract.model_family == "DIAGNOSTIC_NO_REFIT":
        fields: tuple[str, ...] = ()
    else:
        family = (
            "logistic"
            if contract.model_family in {"L2_LOGISTIC", "FRACTIONAL_LOGIT_GLM"}
            else "rf"
        )
        if contract.model_family not in {
            "L2_LOGISTIC", "RANDOM_FOREST", "FRACTIONAL_LOGIT_GLM"
        }:
            raise RunnerError(f"G07_MODEL_SCHEMA_FAMILY:{contract.model_family}")
        oracle_family = (
            "PRIMARY_EVT"
            if contract.comparator_identity == "SPECIALIZED_G05B"
            else contract.analysis_family
        )
        baseline, augmented = schema_oracle.expected_schemas(oracle_family, family)
        fields = baseline if contract.model_role == "baseline" else augmented
    payload = canonical_json({
        "unit_id": _unit_id(contract),
        "comparator_identity": contract.comparator_identity,
        "model_family": contract.model_family,
        "model_role": contract.model_role,
        "transformed_fields": fields,
    })
    return GovernedModelSchema(
        _unit_id(contract), contract.comparator_identity, contract.model_family,
        contract.model_role, tuple(fields), sha256_bytes(payload),
    )


def build_run_plan(project_root: Path) -> tuple[DispatchPlanEntry, ...]:
    root = Path(project_root).resolve()
    g06.validate_validation_generation(root, root / "documentation")
    contracts = g06.governed_execution_contracts(root)
    universe = g06.governed_execution_universe(root)
    contract_ids = tuple(sorted(_unit_id(contract) for contract in contracts))
    if contract_ids != tuple(universe.unit_ids):
        raise RunnerError("G07_EXECUTION_UNIVERSE_SET_MISMATCH")
    g05a = sum(unit.startswith("G05A_") for unit in contract_ids)
    g05b = sum(unit.startswith("G05B_") for unit in contract_ids)
    observed_registry = {
        "g05a": g05a,
        "g05b": g05b,
        "total": len(contract_ids),
        "registry_executable": universe.executable_unit_count,
        "disabled": universe.disabled_unit_count,
    }
    expected_registry = {
        key: EXPECTED_UNIVERSE[key]
        for key in ("g05a", "g05b", "total", "registry_executable", "disabled")
    }
    if observed_registry != expected_registry:
        raise RunnerError(f"G07_EXECUTION_UNIVERSE_COUNT_MISMATCH:{observed_registry}")
    plan: list[DispatchPlanEntry] = []
    for contract in contracts:
        policy = v2_policy.resolve_policy(contract)
        v2_policy.validate_policy(policy)
        if not contract.execution_enabled:
            disposition = DispatchDisposition.DISABLED
        elif contract.special_condition == "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE":
            disposition = DispatchDisposition.NONESTIMABLE
        elif contract.environment_requirement == "statsmodels==0.14.6":
            environment = g06.probe_environment(root, contract)
            disposition = (
                DispatchDisposition.EXECUTABLE
                if environment.status == "PASS" and fractional_environment_ready()
                else DispatchDisposition.ENVIRONMENT_BLOCKED
            )
        elif _facade_gap_for(contract) is not None:
            disposition = DispatchDisposition.AUTHORITY_BLOCKED
        else:
            disposition = DispatchDisposition.EXECUTABLE
        handler_identity = (
            "dispatch_authority_blocked"
            if disposition is DispatchDisposition.AUTHORITY_BLOCKED
            else _handler_for(contract)
        )
        plan.append(DispatchPlanEntry(
            _unit_id(contract), contract.contract_sha256, contract.analysis_id,
            contract.analysis_family, contract.model_family, contract.model_role,
            contract.resolution_m, contract.risk_set_id, contract.evaluation_identity,
            tuple(contract.training_intervals), tuple(contract.heldout_intervals),
            contract.environment_requirement, disposition, handler_identity,
            RunnerMode.SCIENTIFIC,
        ))
    if len({entry.unit_id for entry in plan}) != len(plan):
        raise RunnerError("G07_DUPLICATE_PLAN_UNIT")
    dispositions = {
        "runner_resolvable": sum(entry.disposition is DispatchDisposition.EXECUTABLE for entry in plan),
        "environment_blocked": sum(entry.disposition is DispatchDisposition.ENVIRONMENT_BLOCKED for entry in plan),
        "nonestimable": sum(entry.disposition is DispatchDisposition.NONESTIMABLE for entry in plan),
        "disabled": sum(entry.disposition is DispatchDisposition.DISABLED for entry in plan),
        "authority_blocked": sum(entry.disposition is DispatchDisposition.AUTHORITY_BLOCKED for entry in plan),
    }
    expected_dispositions = {
        **expected_environment_dispositions(sum(
            entry.model_family == "FRACTIONAL_LOGIT_GLM" for entry in plan
        )),
        **{key: EXPECTED_UNIVERSE[key] for key in (
            "nonestimable", "disabled", "authority_blocked"
        )},
    }
    if dispositions != expected_dispositions:
        raise RunnerError(f"G07_DISPOSITION_COUNT_MISMATCH:{dispositions}")
    handlers = {name for name, value in globals().items() if name.startswith("dispatch_") and callable(value)}
    missing = {entry.handler_identity for entry in plan} - handlers
    if missing:
        raise RunnerError(f"G07_MISSING_DISPATCH_HANDLER:{sorted(missing)}")
    return tuple(sorted(plan, key=lambda entry: entry.unit_id))


def dry_run(project_root: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    plan = build_run_plan(root)
    contracts = g06.governed_execution_contracts(root)
    policies = tuple(v2_policy.resolve_policy(contract) for contract in contracts)
    counts = {disposition.value: 0 for disposition in DispatchDisposition}
    for entry in plan:
        counts[entry.disposition.value] += 1
    return MappingProxyType({
        "status": "PASS",
        "gate": GATE_VERSION,
        "g06_4e_acceptance_commit": g06.g06_4e_lifecycle_authority(root)["acceptance_commit"],
        "plan_count": len(plan),
        "unit_ids_sha256": sha256_bytes(canonical_json([entry.unit_id for entry in plan])),
        "v2_interface": dict(v2_policy.v2_interface_identity(policies)),
        "dispositions": counts,
        "g06_4e_facade_compatibility": "PASS" if _accepted_g06_4e_facade() else "FAIL",
        "historical_g06_facade_gaps": [asdict(gap) for gap in FACADE_CAPABILITY_GAPS],
        "gate_implementation": "COMPLETE",
        "independent_acceptance": "NOT_YET_ACCEPTED",
        "scientific_fitting_authorized": False,
        "models_fit": False,
        "real_predictions_generated": False,
        "real_performance_inspected": False,
    })


def require_scientific_authorization(
    project_root: Path,
    request: ProductionExecutionRequest | None,
) -> object:
    """Consume only a committed, identity-bound G08 authorization receipt."""
    try:
        from src import paper1_g08_runtime as g08

        return g08.consume_scientific_authorization(project_root, request)
    except Exception as exc:
        raise RunnerError(f"G07_SCIENTIFIC_EXECUTION_NOT_AUTHORIZED:{exc}") from exc


def run_scientific(
    project_root: Path,
    request: ProductionExecutionRequest | None = None,
) -> ProductionExecutionResult:
    """Authorize, resolve, authenticate, dispatch, and reconcile one governed unit."""
    validate_configuration(SCIENTIFIC_CONFIGURATION)
    authorization = require_scientific_authorization(project_root, request)
    return _run_authorized_scientific(project_root, request, authorization)


def _run_authorized_scientific(project_root, request, authorization, *, before_handler=None):
    """Shared governed body; callers supply their independently validated control."""
    validate_configuration(SCIENTIFIC_CONFIGURATION)
    if not isinstance(request, ProductionExecutionRequest):
        raise RunnerError("G07_PRODUCTION_REQUEST_REQUIRED")
    root = Path(project_root).resolve()
    expected_v2_root = (root / v2_policy.V2_OUTPUT_ROOT_RELATIVE).resolve()
    if Path(request.output_root).resolve() != expected_v2_root:
        raise RunnerError("G07_V2_OUTPUT_ROOT_REQUIRED")
    if request.run_id != _v2_run_id(request.unit_id):
        raise RunnerError("G07_V2_DETERMINISTIC_RUN_ID_REQUIRED")
    plan = build_run_plan(root)
    matches = [entry for entry in plan if entry.unit_id == request.unit_id]
    if len(matches) != 1:
        raise RunnerError("G07_UNKNOWN_GOVERNED_UNIT")
    contracts = [contract for contract in g06.governed_execution_contracts(root)
                 if _unit_id(contract) == request.unit_id]
    if len(contracts) != 1:
        raise RunnerError("G07_EXECUTION_CONTRACT_RESOLUTION")
    contract = contracts[0]
    g06.validate_execution_contract(root, contract)
    entry = matches[0]
    if entry.contract_sha256 != contract.contract_sha256:
        raise RunnerError("G07_PLAN_CONTRACT_BINDING")
    handler = globals().get(entry.handler_identity)
    if not callable(handler):
        raise RunnerError("G07_DISPATCH_HANDLER_MISSING")
    context = _DispatchContext(root, request, entry, contract, authorization, _DISPATCH_CAPABILITY)
    if before_handler is not None:
        before_handler(context, handler)
    result = handler(context)
    if not isinstance(result, ProductionExecutionResult):
        raise RunnerError("G07_DISPATCH_TYPED_RESULT_REQUIRED")
    return result


def _require_dispatch_context(value: object) -> _DispatchContext:
    if not isinstance(value, _DispatchContext) or value.capability is not _DISPATCH_CAPABILITY:
        raise RunnerError("G07_INTERNAL_DISPATCH_CONTEXT_REQUIRED")
    return value


def dispatch_binary_model(context: object = None) -> ProductionExecutionResult:
    return _run_production_lifecycle(_require_dispatch_context(context), "BINARY_MODEL")


def dispatch_confidence_stratified_binary(context: object = None) -> ProductionExecutionResult:
    return _run_production_lifecycle(_require_dispatch_context(context), "CONFIDENCE_STRATIFIED_BINARY")


def dispatch_symmetric_temporal_cv(context: object = None) -> ProductionExecutionResult:
    return _run_production_lifecycle(_require_dispatch_context(context), "SYMMETRIC_TEMPORAL_CV")


def dispatch_loio_diagnostic(context: object = None) -> ProductionExecutionResult:
    return _run_loio_production_lifecycle(_require_dispatch_context(context))


def dispatch_fractional_glm(context: object = None) -> ProductionExecutionResult:
    return _run_production_lifecycle(_require_dispatch_context(context), "FRACTIONAL_GLM")


def dispatch_governed_nonestimable(context: object = None) -> ProductionExecutionResult:
    return _run_production_lifecycle(_require_dispatch_context(context), "NONESTIMABLE")


def dispatch_authority_blocked(*_args: object, **_kwargs: object) -> None:
    raise RunnerError("G07_G06_FACADE_AUTHORITY_BLOCKED")


def dispatch_machine_disabled(context: object = None) -> ProductionExecutionResult:
    return _run_production_lifecycle(_require_dispatch_context(context), "DISABLED")


def synthetic_fixture() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    intervals = tuple(number for values in model_spec.BLOCKS.values() for number in values)
    levels = model_spec.HYBRID_LEVELS
    for interval_index, interval in enumerate(intervals):
        for local in range(8):
            index = interval_index * 8 + local
            canopy_applicable = 0.0 if local in {0, 5} else 1.0
            fbfm = np.array([1 + (index + offset) % 5 for offset in range(5)], dtype=float)
            fbfm /= fbfm.sum()
            evt = np.array([2 + (index * (offset + 1)) % 7 for offset in range(5)], dtype=float)
            evt /= evt.sum()
            row: dict[str, object] = {
                "event_id": "SYNTHETIC_EVENT",
                "interval_id": f"SYN_{interval:02d}",
                "interval_number": interval,
                "response_grid_m": 1000,
                "cell_id": f"SYN_CELL_{index:04d}",
                "y": int((index + interval_index) % 3 == 0 or local == 7),
                "distance_active_front_km": 0.15 + 0.07 * local + 0.01 * interval_index,
                "distance_cumulative_perimeter_km": 0.25 + 0.04 * (7 - local),
                "hybrid_membership": levels[index % len(levels)],
                "log1p_t0_area_km2": 2.0,
                "target_elevation_mean_m": 1300.0 + 2.0 * index,
                "target_slope_mean_degrees": 2.0 + (index % 20),
                "source_target_elevation_difference_m": -20.0 + (index % 41),
                "uphill_alignment": -1.0 + 2.0 * ((index % 11) / 10.0),
                "wind_slope_alignment": -1.0 + 2.0 * ((index % 13) / 12.0),
                "canopy_applicable_fraction": canopy_applicable,
                "hrrr_u10_mean_earth_ms": -2.0 + (index % 9) * 0.5,
                "hrrr_v10_mean_earth_ms": -1.5 + (index % 7) * 0.4,
                "hrrr_gust_max_ms": 3.0 + (index % 10) * 0.3,
                "hrrr_temperature_2m_mean_c": 12.0 + (index % 14) * 0.4,
                "hrrr_relative_humidity_2m_min_pct": 15.0 + (index % 30),
            }
            for field, value in zip(model_spec.FBFM_FIELDS, fbfm, strict=True):
                row[field] = float(value)
            for field, value in zip(model_spec.EVT_FIELDS, evt, strict=True):
                row[field] = float(value)
            canopy_values = (35.0 + local, 4.0 + local / 2, 1.5 + local / 4, 0.08 + local / 100)
            for field, value in zip(model_spec.CANOPY_FIELDS, canopy_values, strict=True):
                row[field] = np.nan if canopy_applicable == 0 else value
            optional_fields = {
                field for fields in analysis_registry.FAMILY_FIELDS.values() for field in fields
            }
            optional_fields.update(analysis_registry.REALIZED_WEATHER)
            optional_fields.update(analysis_registry.CONFIDENCE_FIELDS.values())
            for optional_index, field in enumerate(sorted(optional_fields), start=1):
                row[field] = float(((index + optional_index) % 17) / 17.0)
            rows.append(row)
    frame = pd.DataFrame(rows)
    if len(frame) != 128 or frame[list(g06.KEY_FIELDS)].duplicated().any():
        raise RunnerError("G07_SYNTHETIC_FIXTURE_KEY_FAILURE")
    return frame


def _geometry_design(frame: pd.DataFrame, training_index: pd.Index) -> tuple[pd.DataFrame, Mapping[str, object]]:
    if tuple(GEOMETRY_FIELDS) != (
        "distance_active_front_km", "distance_cumulative_perimeter_km",
        "hybrid_membership", "log1p_t0_area_km2",
    ):
        raise RunnerError("G07_GEOMETRY_AUTHORITY_MUTATION")
    numeric = frame.loc[:, [field for field in GEOMETRY_FIELDS if field != "hybrid_membership"]]
    scaled, statistics = model_spec.scale_logistic_numeric(numeric, training_index)
    membership = frame["hybrid_membership"]
    if membership.isna().any() or not set(membership.unique()).issubset(model_spec.HYBRID_LEVELS):
        raise RunnerError("G07_GEOMETRY_HYBRID_CATEGORY")
    indicators = pd.DataFrame({
        f"hybrid_{level}": membership.eq(level).astype(float)
        for level in model_spec.HYBRID_LEVELS[1:]
    }, index=frame.index)
    return pd.concat([scaled, indicators], axis=1), MappingProxyType(statistics)


def _prepare_design(
    frame: pd.DataFrame,
    model_family: str,
    model_role: str,
    training_index: pd.Index,
) -> tuple[pd.DataFrame, object]:
    family = (
        "logistic"
        if model_family in {"L2_LOGISTIC", "FRACTIONAL_LOGIT_GLM"}
        else "rf"
    )
    role = "baseline_plus_evt" if model_role == "augmented" else "baseline"
    return model_spec.prepare_design(
        frame,
        model_family=family,
        model_role=role,
        train_index=training_index if family == "logistic" else None,
    )


def _fit_probabilities(
    configuration: RunnerConfiguration,
    model_family: str,
    x_train: pd.DataFrame,
    y_train: Sequence[float],
    x_test: pd.DataFrame,
    hyperparameter: float | None,
    seed: int,
) -> np.ndarray:
    validate_configuration(configuration)
    if not x_train.index.is_unique or not x_test.index.is_unique:
        raise RunnerError("G07_MODEL_ROW_IDENTITY_DUPLICATE")
    if isinstance(y_train, pd.Series) and not x_train.index.equals(y_train.index):
        raise RunnerError("G07_MODEL_X_Y_ROW_IDENTITY")
    if model_family == "FRACTIONAL_LOGIT_GLM":
        if hyperparameter is not None:
            raise RunnerError("G07_FRACTIONAL_HYPERPARAMETER_PROHIBITED")
        return _fit_fractional_probabilities(x_train, y_train, x_test)
    y_values = np.asarray(y_train, dtype=int)
    if set(np.unique(y_values)) != {0, 1}:
        raise RunnerError("G07_NONESTIMABLE_SINGLE_CLASS")
    if model_family == "L2_LOGISTIC":
        if configuration.mode is RunnerMode.SYNTHETIC:
            return _fit_synthetic_logistic(x_train, y_values, x_test, hyperparameter)
        estimator = LogisticRegression(
            C=hyperparameter, penalty="l2", solver="lbfgs", fit_intercept=True,
            class_weight=None, max_iter=5000, tol=1e-8,
        )
    elif model_family == "RANDOM_FOREST":
        expected = SCIENTIFIC_RF_TREES if configuration.mode is RunnerMode.SCIENTIFIC else SYNTHETIC_RF_TREES
        if configuration.rf_trees != expected:
            raise RunnerError("G07_RF_MODE_LEAKAGE")
        estimator = RandomForestClassifier(
            n_estimators=configuration.rf_trees, criterion="log_loss", max_depth=6,
            max_features="sqrt", bootstrap=True, class_weight=None,
            min_samples_split=2, min_samples_leaf=hyperparameter, random_state=seed,
            n_jobs=1,
        )
    else:
        raise RunnerError(f"G07_UNKNOWN_MODEL_FAMILY:{model_family}")
    if model_family == "L2_LOGISTIC" and configuration.mode is RunnerMode.SCIENTIFIC:
        try:
            v2_policy.guarded_logistic_fit(estimator, x_train, y_values)
        except v2_policy.PolicyError as exc:
            raise RunnerError(str(exc)) from exc
    else:
        estimator.fit(x_train, y_values)
    probabilities = estimator.predict_proba(x_test)[:, 1]
    if not np.isfinite(probabilities).all() or not ((probabilities >= 0) & (probabilities <= 1)).all():
        raise RunnerError("G07_INVALID_PROBABILITY")
    return probabilities


def _fit_fractional_probabilities(
    x_train: pd.DataFrame,
    y_train: Sequence[float],
    x_test: pd.DataFrame,
) -> np.ndarray:
    """Fit the frozen statsmodels fractional-logit conditional-mean model."""
    if not fractional_environment_ready():
        raise RunnerError("G07_FRACTIONAL_ENVIRONMENT_REQUIRED")
    train = x_train.to_numpy(dtype=float)
    test = x_test.to_numpy(dtype=float)
    outcomes = np.asarray(y_train, dtype=float)
    if (
        train.ndim != 2 or test.ndim != 2 or train.shape[1] != test.shape[1]
        or not len(outcomes) or len(outcomes) != len(train)
        or not np.isfinite(train).all() or not np.isfinite(test).all()
        or not np.isfinite(outcomes).all()
        or (outcomes < 0).any() or (outcomes > 1).any()
    ):
        raise RunnerError("G07_FRACTIONAL_INPUT_INVALID")
    training_mean = float(outcomes.mean())
    if not 0.0 < training_mean < 1.0 or np.unique(outcomes).size == 1:
        raise RunnerError("G07_FRACTIONAL_TRAINING_RESPONSE_NONESTIMABLE")

    from statsmodels.genmod.families import Binomial
    from statsmodels.genmod.families.links import Logit
    from statsmodels.genmod.generalized_linear_model import GLM

    train_with_intercept = np.column_stack((np.ones(len(train)), train))
    test_with_intercept = np.column_stack((np.ones(len(test)), test))
    start = np.zeros(train_with_intercept.shape[1], dtype=float)
    start[0] = math.log(training_mean / (1.0 - training_mean))
    model = GLM(
        outcomes,
        train_with_intercept,
        family=Binomial(link=Logit()),
    )
    observed_rank = int(model.df_model) + 1
    expected_rank = train_with_intercept.shape[1]
    if observed_rank != expected_rank:
        raise RunnerError(
            f"G07_FRACTIONAL_RANK_FAILURE:{observed_rank}/{expected_rank}"
        )
    fitted = model.fit(
        start_params=start,
        method="IRLS",
        maxiter=1000,
        tol=1e-8,
        scale=1,
        cov_type="nonrobust",
        wls_method="lstsq",
        full_output=True,
        disp=False,
    )
    if not bool(getattr(fitted, "converged", False)):
        raise RunnerError("G07_FRACTIONAL_NONCONVERGENCE")
    parameters = np.asarray(fitted.params, dtype=float)
    probabilities = np.asarray(fitted.predict(test_with_intercept), dtype=float)
    if (
        not np.isfinite(parameters).all() or not np.isfinite(probabilities).all()
        or (probabilities < 0).any() or (probabilities > 1).any()
    ):
        raise RunnerError("G07_FRACTIONAL_NUMERICAL_FAILURE")
    return probabilities


def _fit_synthetic_logistic(
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    x_test: pd.DataFrame,
    c_value: float,
) -> np.ndarray:
    """Deterministic test-only optimizer; scientific mode always uses governed LBFGS."""
    if c_value not in LOGISTIC_CANDIDATES:
        raise RunnerError("G07_SYNTHETIC_LOGISTIC_C")
    train_rows = x_train.to_numpy(dtype=float).tolist()
    test_rows = x_test.to_numpy(dtype=float).tolist()
    outcomes = [float(value) for value in y_train]
    coefficients = [0.0] * (len(train_rows[0]) + 1)
    penalty = 1.0 / c_value
    learning_rate = 0.04
    for _ in range(24):
        gradient = [0.0] * len(coefficients)
        for row, outcome in zip(train_rows, outcomes, strict=True):
            linear = coefficients[0] + sum(
                coefficient * value
                for coefficient, value in zip(coefficients[1:], row, strict=True)
            )
            probability = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, linear))))
            residual = probability - outcome
            gradient[0] += residual
            for index, value in enumerate(row, start=1):
                gradient[index] += residual * value
        row_count = float(len(train_rows))
        coefficients[0] -= learning_rate * gradient[0] / row_count
        for index in range(1, len(coefficients)):
            regularized = gradient[index] / row_count + penalty * coefficients[index] / row_count
            coefficients[index] -= learning_rate * regularized
    predictions = []
    for row in test_rows:
        linear = coefficients[0] + sum(
            coefficient * value
            for coefficient, value in zip(coefficients[1:], row, strict=True)
        )
        predictions.append(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, linear)))))
    probabilities = np.asarray(predictions, dtype=float)
    if not np.isfinite(probabilities).all() or not ((probabilities >= 0) & (probabilities <= 1)).all():
        raise RunnerError("G07_INVALID_SYNTHETIC_PROBABILITY")
    return probabilities


def _score_by_interval(frame: pd.DataFrame, probabilities: np.ndarray) -> float:
    scored = frame.loc[:, ["interval_number", "y"]].copy()
    scored["probability"] = probabilities
    values = []
    for _, group in scored.groupby("interval_number", sort=True):
        values.append(log_loss(group["y"], np.clip(group["probability"], 1e-15, 1 - 1e-15), labels=[0, 1]))
    return float(np.mean(values))


def tune_synthetic(
    frame: pd.DataFrame,
    configuration: RunnerConfiguration,
    model_family: str,
    model_role: str,
    outer_evaluation: str = "B1_TO_B2",
    artifact_root: Path | None = None,
) -> TuningReceipt:
    if configuration.mode is not RunnerMode.SYNTHETIC:
        raise RunnerError("G07_SYNTHETIC_TUNING_MODE_REQUIRED")
    candidates = LOGISTIC_CANDIDATES if model_family == "L2_LOGISTIC" else RF_LEAF_CANDIDATES
    if outer_evaluation not in TUNING_SPLITS:
        raise RunnerError(f"G07_UNKNOWN_OUTER_EVALUATION:{outer_evaluation}")
    splits = tuple(TUNING_SPLITS[outer_evaluation])
    split_rows: list[tuple[float, int, float]] = []
    preprocessing_hashes: list[str] = []
    candidate_receipts: list[tuple[float, int, str]] = []
    candidate_scores: dict[float, float] = {}
    for candidate in candidates:
        scores: list[float] = []
        for split_index, (training_intervals, validation_intervals) in enumerate(splits, start=1):
            training_index = frame.index[frame["interval_number"].isin(training_intervals)]
            validation_index = frame.index[frame["interval_number"].isin(validation_intervals)]
            design, receipt = _prepare_design(frame, model_family, model_role, training_index)
            probabilities = _fit_probabilities(
                configuration, model_family, design.loc[training_index], frame.loc[training_index, "y"],
                design.loc[validation_index], candidate, PRIMARY_SEED,
            )
            score = _score_by_interval(frame.loc[validation_index], probabilities)
            if artifact_root is not None:
                root = Path(artifact_root).resolve()
                prediction = _prediction_frame(
                    frame, validation_index, probabilities,
                    f"SYNTHETIC_TUNING_{model_role}", model_family, model_role,
                    outer_evaluation, PRIMARY_SEED,
                )
                relative = (
                    Path("tuning_candidates") / model_family / model_role /
                    outer_evaluation / f"candidate_{candidate}_split_{split_index}.csv"
                )
                persisted = _write_frame_artifact(
                    root / relative, prediction, "SYNTHETIC_TUNING_CANDIDATE", root
                )
                candidate_receipts.append((float(candidate), split_index, persisted.receipt_sha256))
            scores.append(score)
            split_rows.append((float(candidate), split_index, score))
            preprocessing_hashes.append(sha256_bytes(canonical_json(asdict(receipt))))
        candidate_scores[float(candidate)] = float(np.mean(scores))
    selected = model_spec.choose_hyperparameter(
        candidate_scores, "logistic" if model_family == "L2_LOGISTIC" else "rf"
    )
    tie_rule = "within 1e-12 choose C=0.1" if model_family == "L2_LOGISTIC" else "within 1e-12 choose min_samples_leaf=0.05"
    payload = {
        "schema_version": "PAPER1_G07_TUNING_RECEIPT_V1",
        "model_family": model_family,
        "model_role": model_role,
        "outer_evaluation": outer_evaluation,
        "candidates": tuple(float(value) for value in candidates),
        "splits": splits,
        "split_scores": tuple(split_rows),
        "candidate_scores": tuple(sorted(candidate_scores.items())),
        "selected_hyperparameter": float(selected),
        "tie_rule": tie_rule,
        "tuning_seed": PRIMARY_SEED,
        "training_preprocessing_sha256s": tuple(preprocessing_hashes),
        "candidate_prediction_receipts": tuple(candidate_receipts),
    }
    return TuningReceipt(**payload, receipt_sha256=sha256_bytes(canonical_json(payload)))


def _key_hash(frame: pd.DataFrame) -> str:
    ordered = frame.loc[:, list(g06.KEY_FIELDS)].sort_values(list(g06.KEY_FIELDS), kind="stable")
    return sha256_bytes(ordered.to_csv(index=False, lineterminator="\n").encode("utf-8"))


def _write_frame_artifact(path: Path, frame: pd.DataFrame, role: str, root: Path) -> PersistedArtifactReceipt:
    ordered = frame.sort_values(list(g06.KEY_FIELDS), kind="stable").reset_index(drop=True)
    payload = ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    _atomic_bytes(path, payload)
    relative = path.relative_to(root).as_posix()
    receipt_payload = {
        "schema_version": "PAPER1_G07_ARTIFACT_RECEIPT_V1",
        "role": role,
        "relative_path": relative,
        "artifact_sha256": sha256_bytes(payload),
        "artifact_bytes": len(payload),
        "row_count": len(ordered),
        "key_sha256": _key_hash(ordered),
        "content_sha256": sha256_bytes(payload),
    }
    receipt = PersistedArtifactReceipt(
        **receipt_payload, receipt_sha256=sha256_bytes(canonical_json(receipt_payload))
    )
    _atomic_json(path.with_suffix(path.suffix + ".receipt.json"), asdict(receipt))
    return receipt


def read_frame_artifact(root: Path, receipt: PersistedArtifactReceipt) -> pd.DataFrame:
    path = Path(root) / receipt.relative_path
    if not path.is_file() or sha256_file(path) != receipt.artifact_sha256:
        raise RunnerError("G07_PREDICTION_ARTIFACT_IDENTITY")
    payload = asdict(receipt)
    observed_receipt_hash = payload.pop("receipt_sha256")
    if sha256_bytes(canonical_json(payload)) != observed_receipt_hash:
        raise RunnerError("G07_PREDICTION_RECEIPT_IDENTITY")
    frame = pd.read_csv(path)
    if len(frame) != receipt.row_count or _key_hash(frame) != receipt.key_sha256:
        raise RunnerError("G07_PREDICTION_KEY_IDENTITY")
    return frame


def _write_json_artifact(path: Path, payload: Mapping[str, object], role: str, root: Path) -> PersistedArtifactReceipt:
    content = canonical_json(payload) + b"\n"
    _atomic_bytes(path, content)
    receipt_payload = {
        "schema_version": "PAPER1_G07_ARTIFACT_RECEIPT_V1",
        "role": role,
        "relative_path": path.relative_to(root).as_posix(),
        "artifact_sha256": sha256_bytes(content),
        "artifact_bytes": len(content),
        "row_count": 1,
        "key_sha256": sha256_bytes(canonical_json({"role": role})),
        "content_sha256": sha256_bytes(content),
    }
    receipt = PersistedArtifactReceipt(
        **receipt_payload, receipt_sha256=sha256_bytes(canonical_json(receipt_payload))
    )
    _atomic_json(path.with_suffix(path.suffix + ".receipt.json"), asdict(receipt))
    return receipt


def write_g06_compatible_synthetic_evidence(
    project_root: Path,
    predictions: pd.DataFrame,
    *,
    source_commit: str,
    checkpoint_records: Sequence[Mapping[str, object]] = (),
) -> Path:
    """Persist a synthetic-only 31-field G06.4e-compatible evidence bundle."""
    root = Path(project_root).resolve()
    if "SYNTHETIC" not in root.name.upper() and "SYNTHETIC" not in root.parent.name.upper():
        raise RunnerError("G07_SYNTHETIC_OUTPUT_SCOPE_REQUIRED")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RunnerError("G07_MANIFEST_SOURCE_COMMIT")
    required_source = list(g06.KEY_FIELDS) + ["interval_number", "raw_probability_y1"]
    if any(column not in predictions.columns for column in required_source):
        raise RunnerError("G07_MANIFEST_PREDICTION_SOURCE_SCHEMA")
    output = predictions.loc[:, list(g06.KEY_FIELDS) + ["interval_number"]].copy()
    output["predicted_probability"] = predictions["raw_probability_y1"].astype(float)
    output = output.loc[:, list(g06.PREDICTION_INTEGRITY_COLUMNS)]
    output = output.sort_values(list(g06.KEY_FIELDS), kind="stable").reset_index(drop=True)
    prediction_path = root / "g06_compatible" / "predictions.csv"
    _atomic_bytes(prediction_path, output.to_csv(index=False, lineterminator="\n").encode("utf-8"))

    fixture = synthetic_fixture().loc[:, list(g06.KEY_FIELDS) + ["interval_number", "y"]]
    fixture_path = root / "g06_compatible" / "synthetic_input.csv"
    _atomic_bytes(fixture_path, fixture.to_csv(index=False, lineterminator="\n").encode("utf-8"))
    contract_id = sha256_bytes(canonical_json({
        "gate": GATE_VERSION,
        "analysis": "G07_SYNTHETIC_G06_COMPATIBILITY",
        "classification": RunnerMode.SYNTHETIC.value,
    }))
    manifest = {
        "schema_name": g06.MANIFEST_SCHEMA_NAME,
        "schema_version": g06.MANIFEST_SCHEMA_VERSION,
        "paper1_run_id": "G07_SYNTHETIC_RUN",
        "runner_source_commit": source_commit,
        "runner_identity": SCHEMA_VERSION,
        "scientific_run_git_commit": source_commit,
        "clean_tree": False,
        "environment_identity": f"python-{sys.version_info.major}.{sys.version_info.minor}",
        "package_lock_identity": sha256_bytes(canonical_json({"synthetic": True})),
        "execution_contract_id": contract_id,
        "analysis_id": "G07_SYNTHETIC_G06_COMPATIBILITY",
        "model_family": "L2_LOGISTIC",
        "model_role": "baseline",
        "outer_evaluation": "B1_TO_B2",
        "training_history": [1, 3, 4, 5],
        "validation_history": [4, 5],
        "heldout_history": [6, 8, 9, 10],
        "hyperparameters": {"C": 0.1},
        "hyperparameter_state": {"selection": "SYNTHETIC_TEST_ONLY"},
        "random_seeds": [PRIMARY_SEED],
        "input_artifacts": [{
            "path": fixture_path.relative_to(root).as_posix(),
            "sha256": sha256_file(fixture_path),
            "schema": g06.OUTCOME_INPUT_SCHEMA,
            "key_identity": _g06_4e_key_identity(fixture, include_y=True),
        }],
        "output_prediction_artifact": {
            "path": prediction_path.relative_to(root).as_posix(),
            "sha256": sha256_file(prediction_path),
            "schema": g06.PREDICTION_ARTIFACT_SCHEMA,
            "row_count": len(output),
            "key_identity": _g06_4e_key_identity(output),
            "required_columns": list(g06.PREDICTION_INTEGRITY_COLUMNS),
        },
        "checkpoints": [dict(record) for record in checkpoint_records],
        "start_timestamp_utc": "2020-09-08T00:00:00Z",
        "end_timestamp_utc": "2020-09-08T00:00:01Z",
        "process_metadata": {"mode": RunnerMode.SYNTHETIC.value},
        "child_process_metadata": [],
        "terminal_status": TerminalDisposition.COMPLETE.value,
        "exception_metadata": None,
        "evidence_classification": RunnerMode.SYNTHETIC.value,
        "manifest_role": g06.MANIFEST_ROLE,
    }
    if tuple(manifest) != tuple(g06.EXECUTION_MANIFEST_REQUIRED_FIELDS):
        raise RunnerError("G07_MANIFEST_31_FIELD_ORDER")
    manifest_path = root / "g06_compatible" / "execution_manifest.json"
    _atomic_json(manifest_path, manifest)
    g06.validate_execution_manifest(root, manifest_path, verify_files=True)
    return manifest_path


def _g06_4e_key_identity(frame: pd.DataFrame, include_y: bool = False) -> str:
    columns = [*g06.KEY_FIELDS, "interval_number"]
    if include_y:
        columns.append("y")
    ordered = frame.loc[:, columns].sort_values(
        [*g06.KEY_FIELDS, "interval_number"], kind="stable"
    ).reset_index(drop=True)
    return sha256_bytes(ordered.to_csv(index=False, lineterminator="\n").encode("utf-8"))


def _prediction_frame(
    frame: pd.DataFrame,
    index: pd.Index,
    probabilities: np.ndarray,
    analysis_id: str,
    model_family: str,
    model_role: str,
    evaluation: str,
    seed: int,
) -> pd.DataFrame:
    if (not frame.index.is_unique or not index.is_unique or
            not index.isin(frame.index).all() or len(probabilities) != len(index)):
        raise RunnerError("G07_PREDICTION_ROW_IDENTITY")
    if frame.loc[index, list(g06.KEY_FIELDS)].duplicated().any():
        raise RunnerError("G07_PREDICTION_KEY_IDENTITY")
    output = frame.loc[index, list(g06.KEY_FIELDS) + ["interval_number", "y"]].copy()
    output["analysis_id"] = analysis_id
    output["outer_evaluation"] = evaluation
    output["model_family"] = model_family
    output["model_role"] = model_role
    output["seed"] = seed
    output["raw_probability_y1"] = probabilities
    return output


def _synthetic_interval_metrics(group: pd.DataFrame, interval: int) -> Mapping[str, object]:
    outcomes = [int(value) for value in group["y"]]
    probabilities = [float(value) for value in group["raw_probability_y1"]]
    both_classes = len(set(outcomes)) == 2
    logits = [math.log(max(1e-15, min(1 - 1e-15, value)) / max(1e-15, 1 - value)) for value in probabilities]
    intercept, slope = 0.0, 1.0
    if both_classes and max(logits) != min(logits):
        for _ in range(120):
            gradient_intercept = 0.0
            gradient_slope = 0.0
            for outcome, logit in zip(outcomes, logits, strict=True):
                eta = intercept + slope * logit
                fitted = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, eta))))
                residual = fitted - outcome
                gradient_intercept += residual
                gradient_slope += residual * logit
            intercept -= 0.04 * gradient_intercept / len(outcomes)
            slope -= 0.04 * gradient_slope / len(outcomes)
        calibration_intercept: float | str = intercept
        calibration_slope: float | str = slope
    else:
        calibration_intercept = "NOT_DEFINED"
        calibration_slope = "NOT_DEFINED"
    return MappingProxyType({
        "interval_number": int(interval),
        "rows": len(outcomes),
        "positives": sum(outcomes),
        "log_loss": float(log_loss(outcomes, probabilities, labels=[0, 1])),
        "brier": float(brier_score_loss(outcomes, probabilities)),
        "average_precision": float(average_precision_score(outcomes, probabilities)) if both_classes else "NOT_DEFINED",
        "roc_auc": float(roc_auc_score(outcomes, probabilities)) if both_classes else "NOT_DEFINED",
        "calibration_intercept": calibration_intercept,
        "calibration_slope": calibration_slope,
        "reliability": model_spec.reliability_summary(
            outcomes, probabilities, [interval] * len(outcomes), group["cell_id"]
        ),
    })


def _metric_payload(
    predictions: pd.DataFrame,
    configuration: RunnerConfiguration = SYNTHETIC_CONFIGURATION,
) -> Mapping[str, object]:
    validate_configuration(configuration)
    records = []
    for interval, group in predictions.groupby("interval_number", sort=True):
        if configuration.mode is RunnerMode.SYNTHETIC:
            records.append(dict(_synthetic_interval_metrics(group, int(interval))))
        else:
            records.append(model_spec.interval_metrics(
                group["y"], group["raw_probability_y1"], int(interval), group["cell_id"]
            ))
    return MappingProxyType({
        "interval_records": records,
        "log_loss_equal_interval_mean": float(np.mean([row["log_loss"] for row in records])),
        "brier_equal_interval_mean": float(np.mean([row["brier"] for row in records])),
        "aggregation_scope": "CURRENT_HELDOUT_EVALUATION_ONLY",
    })


def _fractional_metric_payload(predictions: pd.DataFrame) -> Mapping[str, object]:
    """Apply the frozen fractional-response metric contract."""
    records = []
    for interval, group in predictions.groupby("interval_number", sort=True):
        outcomes = pd.to_numeric(group["y"], errors="coerce").to_numpy(dtype=float)
        probabilities = pd.to_numeric(
            group["raw_probability_y1"], errors="coerce"
        ).to_numpy(dtype=float)
        if (
            not len(outcomes) or not np.isfinite(outcomes).all()
            or not np.isfinite(probabilities).all()
            or (outcomes < 0).any() or (outcomes > 1).any()
            or (probabilities < 0).any() or (probabilities > 1).any()
        ):
            raise RunnerError("G07_FRACTIONAL_METRIC_INPUT_INVALID")
        clipped = np.clip(probabilities, 1e-15, 1.0 - 1e-15)
        records.append({
            "interval_number": int(interval),
            "rows": len(group),
            "fractional_log_loss": float(np.mean(
                -(outcomes * np.log(clipped) + (1.0 - outcomes) * np.log(1.0 - clipped))
            )),
            "mse": float(np.mean((outcomes - probabilities) ** 2)),
            "mean_calibration_error": float(np.mean(outcomes) - np.mean(probabilities)),
        })
    reliability = [
        {
            "bin": int(row["bin"]),
            "rows": int(row["n"]),
            "mean_observed": float(row["mean_outcome"]),
            "mean_predicted": float(row["mean_prediction"]),
        }
        for row in evaluation_authority.reliability(
            pd.to_numeric(predictions["y"], errors="coerce"),
            pd.to_numeric(predictions["raw_probability_y1"], errors="coerce"),
            predictions["interval_number"],
            predictions["cell_id"],
            fractional=True,
        )
    ]
    return MappingProxyType({
        "metric_authority": "G03_FRACTIONAL_LOGIT_GLM",
        "interval_records": records,
        "fractional_log_loss_equal_interval_mean": float(np.mean([
            row["fractional_log_loss"] for row in records
        ])),
        "mse_equal_interval_mean": float(np.mean([row["mse"] for row in records])),
        "mean_calibration_error_equal_interval_mean": float(np.mean([
            row["mean_calibration_error"] for row in records
        ])),
        "reliability": reliability,
        "binary_metrics": "NOT_APPLICABLE",
        "aggregation_scope": "CURRENT_HELDOUT_EVALUATION_ONLY",
    })


def _checkpoint_payload(payload: Mapping[str, object]) -> Mapping[str, object]:
    body = dict(payload)
    return {"payload": body, "payload_sha256": sha256_bytes(canonical_json(body))}


def write_synthetic_checkpoint(path: Path, payload: Mapping[str, object]) -> None:
    _atomic_json(path, _checkpoint_payload(payload))


def synthetic_checkpoint_identity(run_id: str) -> Mapping[str, object]:
    configuration = asdict(SYNTHETIC_CONFIGURATION)
    configuration["mode"] = SYNTHETIC_CONFIGURATION.mode.value
    fixture_identity = sha256_bytes(
        synthetic_fixture().to_csv(index=False, lineterminator="\n").encode("utf-8")
    )
    identity = {
        "run_id": run_id,
        "execution_contract_id": "SYNTHETIC_G07_CONTRACT",
        "analysis_unit": "SYNTHETIC_BASELINE_EVT_BENCHMARK_SUITE",
        "model_evaluation_role": "SYNTHETIC_ALL_GOVERNED_PATHS",
        "input_identity": fixture_identity,
        "environment_identity": f"python-{sys.version_info.major}.{sys.version_info.minor}",
        "configuration_identity": sha256_bytes(canonical_json(configuration)),
        "seed_identity": sha256_bytes(canonical_json({
            "primary": PRIMARY_SEED,
            "rf": RF_SEEDS,
            "bootstrap": SYNTHETIC_CONFIGURATION.bootstrap_seed,
        })),
    }
    return MappingProxyType(identity)


def read_synthetic_checkpoint(path: Path, expected_run_id: str) -> Mapping[str, object]:
    if not path.is_file():
        raise RunnerError("G07_CHECKPOINT_MISSING")
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    payload = wrapper.get("payload")
    if not isinstance(payload, dict) or sha256_bytes(canonical_json(payload)) != wrapper.get("payload_sha256"):
        raise RunnerError("G07_CHECKPOINT_CORRUPT")
    if payload.get("schema_version") != SYNTHETIC_SCHEMA_VERSION:
        raise RunnerError("G07_CHECKPOINT_SCHEMA")
    if payload.get("run_id") != expected_run_id:
        raise RunnerError("G07_CHECKPOINT_RUN_CONTEXT")
    if payload.get("mode") != RunnerMode.SYNTHETIC.value:
        raise RunnerError("G07_CHECKPOINT_MODE")
    if payload.get("stage") not in CHECKPOINT_STAGES:
        raise RunnerError("G07_CHECKPOINT_STAGE")
    expected_identity = dict(synthetic_checkpoint_identity(expected_run_id))
    if payload.get("checkpoint_identity") != expected_identity:
        raise RunnerError("G07_CHECKPOINT_IDENTITY")
    completed = payload.get("completed_stages")
    stage_index = CHECKPOINT_STAGES.index(str(payload["stage"]))
    if completed != list(CHECKPOINT_STAGES[:stage_index + 1]):
        raise RunnerError("G07_CHECKPOINT_PHASE_TRANSITION")
    return MappingProxyType(payload)


def moving_block_bootstrap(
    deltas: Sequence[float],
    block_length: int,
    configuration: RunnerConfiguration,
) -> np.ndarray:
    validate_configuration(configuration)
    expected = (
        SCIENTIFIC_BOOTSTRAP_REPLICATES
        if configuration.mode is RunnerMode.SCIENTIFIC
        else SYNTHETIC_BOOTSTRAP_REPLICATES
    )
    if configuration.bootstrap_replicates != expected:
        raise RunnerError("G07_BOOTSTRAP_MODE_LEAKAGE")
    return model_spec.moving_block_bootstrap(
        deltas, block_length, configuration.bootstrap_replicates, configuration.bootstrap_seed
    )


def symmetric_temporal_folds() -> tuple[tuple[str, tuple[int, ...], tuple[int, ...]], ...]:
    blocks = model_spec.BLOCKS
    return tuple(
        (f"SYMMETRIC_{heldout}_HELDOUT", tuple(
            interval for block, values in blocks.items() if block != heldout for interval in values
        ), tuple(blocks[heldout]))
        for heldout in ("B1", "B2", "B3", "B4")
    )


def run_synthetic_symmetric_cv(output_root: Path) -> tuple[tuple[str, str, str], ...]:
    root = Path(output_root).resolve()
    if "SYNTHETIC" not in root.name.upper() and "SYNTHETIC" not in root.parent.name.upper():
        raise RunnerError("G07_SYNTHETIC_OUTPUT_SCOPE_REQUIRED")
    frame = synthetic_fixture()
    rows = []
    for identity, training_intervals, heldout_intervals in symmetric_temporal_folds():
        training_index = frame.index[frame["interval_number"].isin(training_intervals)]
        heldout_index = frame.index[frame["interval_number"].isin(heldout_intervals)]
        if set(training_index) & set(heldout_index):
            raise RunnerError("G07_SYMMETRIC_FOLD_OVERLAP")
        design, _ = _prepare_design(frame, "L2_LOGISTIC", "baseline", training_index)
        probabilities = _fit_probabilities(
            SYNTHETIC_CONFIGURATION, "L2_LOGISTIC", design.loc[training_index],
            frame.loc[training_index, "y"], design.loc[heldout_index], 0.1, PRIMARY_SEED,
        )
        prediction = _prediction_frame(
            frame, heldout_index, probabilities, identity, "L2_LOGISTIC", "baseline",
            identity, PRIMARY_SEED,
        )
        prediction_path = root / "predictions" / f"{identity}.csv"
        prediction_receipt = _write_frame_artifact(
            prediction_path, prediction, "SYMMETRIC_PERSISTED_PREDICTION", root
        )
        persisted = read_frame_artifact(root, prediction_receipt)
        metric_receipt = _write_json_artifact(
            root / "metrics" / f"{identity}.json", dict(_metric_payload(persisted)),
            "SYMMETRIC_GOVERNED_METRICS", root,
        )
        rows.append((identity, prediction_receipt.receipt_sha256, metric_receipt.receipt_sha256))
    return tuple(rows)


def loio_diagnostic(interval_deltas: Mapping[int, float]) -> tuple[Mapping[str, object], ...]:
    if tuple(sorted(interval_deltas)) != tuple(sorted(PRIMARY_HELDOUT_INTERVALS)):
        raise RunnerError("G07_LOIO_INTERVAL_SET")
    records = []
    block_lookup = {
        interval: block for block in ("B2", "B3", "B4") for interval in model_spec.BLOCKS[block]
    }
    full = float(np.mean([
        np.mean([interval_deltas[i] for i in model_spec.BLOCKS[block]])
        for block in ("B2", "B3", "B4")
    ]))
    for omitted in PRIMARY_HELDOUT_INTERVALS:
        block_means = []
        for block in ("B2", "B3", "B4"):
            values = [interval_deltas[i] for i in model_spec.BLOCKS[block] if i != omitted]
            block_means.append(float(np.mean(values)))
        estimate = float(np.mean(block_means))
        records.append({
            "omitted_interval": omitted,
            "affected_block": block_lookup[omitted],
            "full_estimate": full,
            "omitted_estimate": estimate,
            "absolute_change": abs(estimate - full),
        })
    ordered = sorted(records, key=lambda row: (-row["absolute_change"], row["omitted_interval"]))
    return tuple(MappingProxyType({**row, "rank": rank}) for rank, row in enumerate(ordered, start=1))


def _scientific_payload_hash(root: Path, state: Mapping[str, object]) -> str:
    receipt_hashes = {}
    for path in sorted(Path(root).rglob("*.receipt.json")):
        receipt_hashes[path.relative_to(root).as_posix()] = json.loads(path.read_text())["receipt_sha256"]
    payload = {
        "selected": state["selected"],
        "prediction_receipts": {key: receipt_hashes[value + ".receipt.json"] for key, value in state["predictions"].items()},
        "metric_receipts": {key: receipt_hashes[value + ".receipt.json"] for key, value in state["metrics"].items()},
        "bootstrap_receipts": {key: receipt_hashes[value + ".receipt.json"] for key, value in state["bootstraps"].items()},
        "terminal_states": state["terminal_states"],
        "symmetric_folds": [list(item) for item in symmetric_temporal_folds()],
        "loio": [dict(item) for item in loio_diagnostic({i: i / 1000 for i in PRIMARY_HELDOUT_INTERVALS})],
    }
    return sha256_bytes(canonical_json(payload))


def run_synthetic_lifecycle(
    output_root: Path,
    *,
    interrupt_after: str | None = None,
    resume: bool = False,
    run_id: str = "G07_SYNTHETIC_RUN",
) -> SyntheticRunResult:
    configuration = SYNTHETIC_CONFIGURATION
    validate_configuration(configuration)
    root = Path(output_root).resolve()
    if "SYNTHETIC" not in root.name.upper() and "SYNTHETIC" not in root.parent.name.upper():
        raise RunnerError("G07_SYNTHETIC_OUTPUT_SCOPE_REQUIRED")
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "checkpoint.json"
    state: dict[str, object]
    if resume:
        state = dict(read_synthetic_checkpoint(checkpoint, run_id))
        if state["stage"] == "FINALIZED":
            return _result_from_state(root, state, True)
    else:
        if checkpoint.exists():
            raise RunnerError("G07_EXISTING_CHECKPOINT_REQUIRES_RESUME")
        state = {
            "schema_version": SYNTHETIC_SCHEMA_VERSION,
            "run_id": run_id,
            "mode": RunnerMode.SYNTHETIC.value,
            "checkpoint_identity": dict(synthetic_checkpoint_identity(run_id)),
            "stage": "INITIALIZED",
            "completed_stages": ["INITIALIZED"],
            "selected": {},
            "predictions": {},
            "metrics": {},
            "bootstraps": {},
            "terminal_states": {
                "synthetic_nonestimable": "NONESTIMABLE",
                "synthetic_environment": "ENVIRONMENT_BLOCKED",
                "synthetic_disabled": "DISABLED",
            },
            "model_fit_count": 0,
        }
        write_synthetic_checkpoint(checkpoint, state)
        if interrupt_after == "INITIALIZED":
            raise ControlledInterruption("G07_CONTROLLED_INTERRUPTION:INITIALIZED")
    frame = synthetic_fixture()
    specs = (
        ("PREVALENCE", "TRAINING_PREVALENCE", "benchmark"),
        ("GEOMETRY", "L2_LOGISTIC", "geometry"),
        ("BASELINE_LOGISTIC", "L2_LOGISTIC", "baseline"),
        ("EVT_LOGISTIC", "L2_LOGISTIC", "augmented"),
        ("BASELINE_RF", "RANDOM_FOREST", "baseline"),
        ("EVT_RF", "RANDOM_FOREST", "augmented"),
    )
    if state["stage"] == "INITIALIZED":
        for analysis_id, family, role in specs:
            if family in {"L2_LOGISTIC", "RANDOM_FOREST"} and role != "geometry":
                receipt = tune_synthetic(frame, configuration, family, role, artifact_root=root)
                state["selected"][analysis_id] = receipt.selected_hyperparameter
                state["model_fit_count"] += len(receipt.candidates) * len(receipt.splits)
                _write_json_artifact(
                    root / "tuning" / f"{analysis_id}.json", asdict(receipt), "TUNING_RECEIPT", root
                )
            elif family == "L2_LOGISTIC":
                state["selected"][analysis_id] = 0.1
            else:
                state["selected"][analysis_id] = -1.0
        state["selected"]["GEOMETRY"] = state["selected"]["BASELINE_LOGISTIC"]
        state["stage"] = "TUNED"
        state["completed_stages"].append("TUNED")
        write_synthetic_checkpoint(checkpoint, state)
        if interrupt_after == "TUNED":
            raise ControlledInterruption("G07_CONTROLLED_INTERRUPTION:TUNED")
    if state["stage"] == "TUNED":
        training_intervals, heldout_intervals = model_spec.OUTER_EVALUATIONS[0][1:]
        training_index = frame.index[frame["interval_number"].isin(training_intervals)]
        heldout_index = frame.index[frame["interval_number"].isin(heldout_intervals)]
        for analysis_id, family, role in specs:
            if analysis_id in state["predictions"]:
                continue
            if family == "TRAINING_PREVALENCE":
                probabilities = model_spec.prevalence_probabilities(frame.loc[training_index, "y"], len(heldout_index))
                state["model_fit_count"] += 0
            elif role == "geometry":
                design, _ = _geometry_design(frame, training_index)
                probabilities = _fit_probabilities(
                    configuration, family, design.loc[training_index], frame.loc[training_index, "y"],
                    design.loc[heldout_index], float(state["selected"][analysis_id]), PRIMARY_SEED,
                )
                state["model_fit_count"] += 1
            else:
                design, _ = _prepare_design(frame, family, role, training_index)
                probabilities = _fit_probabilities(
                    configuration, family, design.loc[training_index], frame.loc[training_index, "y"],
                    design.loc[heldout_index], float(state["selected"][analysis_id]), PRIMARY_SEED,
                )
                state["model_fit_count"] += 1
            prediction = _prediction_frame(
                frame, heldout_index, probabilities, analysis_id, family, role, "B1_TO_B2", PRIMARY_SEED
            )
            relative = Path("predictions") / f"{analysis_id}.csv"
            _write_frame_artifact(root / relative, prediction, "PERSISTED_PREDICTION", root)
            state["predictions"][analysis_id] = relative.as_posix()
        state["stage"] = "SEED_PREDICTION_WRITTEN"
        state["completed_stages"].append("SEED_PREDICTION_WRITTEN")
        write_synthetic_checkpoint(checkpoint, state)
        if interrupt_after == "SEED_PREDICTION_WRITTEN":
            raise ControlledInterruption("G07_CONTROLLED_INTERRUPTION:SEED_PREDICTION_WRITTEN")
    if state["stage"] == "SEED_PREDICTION_WRITTEN":
        for analysis_id, relative in state["predictions"].items():
            if analysis_id in state["metrics"]:
                continue
            receipt_data = json.loads((root / (relative + ".receipt.json")).read_text())
            predictions = read_frame_artifact(root, PersistedArtifactReceipt(**receipt_data))
            metrics = dict(_metric_payload(predictions))
            metric_relative = Path("metrics") / f"{analysis_id}.json"
            _write_json_artifact(root / metric_relative, metrics, "GOVERNED_METRICS", root)
            state["metrics"][analysis_id] = metric_relative.as_posix()
        state["stage"] = "METRICS_WRITTEN"
        state["completed_stages"].append("METRICS_WRITTEN")
        write_synthetic_checkpoint(checkpoint, state)
        if interrupt_after == "METRICS_WRITTEN":
            raise ControlledInterruption("G07_CONTROLLED_INTERRUPTION:METRICS_WRITTEN")
    if state["stage"] == "METRICS_WRITTEN":
        deltas = np.linspace(-0.04, 0.07, 12)
        for length in (2, 3):
            draws = moving_block_bootstrap(deltas, length, configuration)
            payload = {
                "block_length": length,
                "replicates": configuration.bootstrap_replicates,
                "seed": configuration.bootstrap_seed,
                "draws": draws.tolist(),
            }
            relative = Path("bootstrap") / f"block_{length}.json"
            _write_json_artifact(root / relative, payload, "MOVING_BLOCK_BOOTSTRAP", root)
            state["bootstraps"][f"block_{length}"] = relative.as_posix()
        state["stage"] = "FINALIZED"
        state["completed_stages"].append("FINALIZED")
        state["scientific_payload_sha256"] = _scientific_payload_hash(root, state)
        write_synthetic_checkpoint(checkpoint, state)
        _atomic_json(root / "completion_manifest.json", {
            "schema_version": SYNTHETIC_SCHEMA_VERSION,
            "run_id": run_id,
            "state": "COMPLETE_SYNTHETIC_VALIDATION",
            "scientific_payload_sha256": state["scientific_payload_sha256"],
            "checkpoint_sha256": sha256_file(checkpoint),
            "scientific_fitting": False,
        })
    return _result_from_state(root, state, resume)


def _result_from_state(root: Path, state: Mapping[str, object], resumed: bool) -> SyntheticRunResult:
    if state["stage"] != "FINALIZED":
        raise RunnerError("G07_SYNTHETIC_RUN_NOT_FINAL")
    def receipt_pairs(mapping: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
        pairs = []
        for key, value in mapping.items():
            receipt_path = root / (value + ".receipt.json")
            if not receipt_path.is_file():
                raise RunnerError("G07_ARTIFACT_RECEIPT_MISSING")
            receipt = PersistedArtifactReceipt(**json.loads(receipt_path.read_text(encoding="utf-8")))
            payload = asdict(receipt)
            observed = payload.pop("receipt_sha256")
            if sha256_bytes(canonical_json(payload)) != observed:
                raise RunnerError("G07_ARTIFACT_RECEIPT_IDENTITY")
            artifact_path = root / receipt.relative_path
            if not artifact_path.is_file() or sha256_file(artifact_path) != receipt.artifact_sha256:
                raise RunnerError("G07_ARTIFACT_STALE_OR_CONFLICTING")
            pairs.append((key, receipt.receipt_sha256))
        return tuple(sorted(pairs))
    return SyntheticRunResult(
        SYNTHETIC_SCHEMA_VERSION,
        str(state["run_id"]),
        RunnerMode.SYNTHETIC,
        "COMPLETE_SYNTHETIC_VALIDATION",
        resumed,
        tuple(state["completed_stages"]),
        tuple(sorted((key, float(value)) for key, value in state["selected"].items())),
        receipt_pairs(state["predictions"]),
        receipt_pairs(state["metrics"]),
        receipt_pairs(state["bootstraps"]),
        str(state["scientific_payload_sha256"]),
        int(state["model_fit_count"]),
        0,
    )


def _write_once(path: Path, payload: bytes) -> None:
    """Atomically publish immutable evidence or accept an identical prior write."""
    destination = Path(path)
    if destination.exists():
        if destination.is_file() and destination.read_bytes() == payload:
            return
        raise RunnerError(f"G07_OUTPUT_COLLISION:{destination.name}")
    _atomic_bytes(destination, payload)


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    value = completed.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RunnerError("G07_GIT_HEAD_IDENTITY")
    return value


def write_authenticated_synthetic_input(
    validation_root: Path,
    contract: g06.ExecutionContract,
    *,
    source_commit: str,
    frame: pd.DataFrame | None = None,
) -> Path:
    """Create persisted G06-compatible SYNTHETIC_TEST ingress evidence."""
    root = Path(validation_root).resolve()
    fixture = synthetic_fixture() if frame is None else frame.copy()
    fixture["response_grid_m"] = int(contract.resolution_m)
    if fixture[list(g06.KEY_FIELDS)].duplicated().any():
        raise RunnerError("G07_SYNTHETIC_INPUT_KEYS_OR_RESPONSE")
    _validate_response_semantics(fixture["y"], contract)
    ingress = root / "ingress" / sha256_bytes(contract.contract_sha256.encode("ascii"))[:16]
    predictor = fixture.drop(columns="y").sort_values(list(g06.KEY_FIELDS), kind="stable")
    outcome = fixture.loc[:, [*g06.KEY_FIELDS, "interval_number", "y"]].sort_values(
        list(g06.KEY_FIELDS), kind="stable"
    )
    predictor_path = ingress / "predictors.csv"
    outcome_path = ingress / "outcome.csv"
    _write_once(predictor_path, predictor.to_csv(index=False, lineterminator="\n").encode("utf-8"))
    _write_once(outcome_path, outcome.to_csv(index=False, lineterminator="\n").encode("utf-8"))
    inputs = [
        {
            "path": predictor_path.relative_to(root).as_posix(),
            "sha256": sha256_file(predictor_path),
            "schema": "PAPER1_G07_AUTHENTICATED_PREDICTOR_INPUT_V1",
            "key_identity": _g06_4e_key_identity(predictor),
        },
        {
            "path": outcome_path.relative_to(root).as_posix(),
            "sha256": sha256_file(outcome_path),
            "schema": g06.OUTCOME_INPUT_SCHEMA,
            "key_identity": _g06_4e_key_identity(outcome, include_y=True),
        },
    ]
    manifest = _execution_manifest_record(
        contract=contract,
        run_id="G07_SYNTHETIC_INGRESS",
        source_commit=source_commit,
        classification=RunnerMode.SYNTHETIC.value,
        input_artifacts=inputs,
        output=None,
        checkpoints=[],
        terminal_status="PENDING_NOT_EXECUTED",
        exception_metadata=None,
        hyperparameters=(
            {} if contract.model_family == "FRACTIONAL_LOGIT_GLM"
            else {"selected_hyperparameter": 0.1}
        ),
        hyperparameter_state={"source": "SYNTHETIC_TEST_FIXTURE"},
        start_timestamp="2020-09-08T00:00:00Z",
        end_timestamp="2020-09-08T00:00:00Z",
    )
    manifest_path = ingress / "input_manifest.json"
    _write_once(manifest_path, canonical_json(manifest) + b"\n")
    g06.validate_execution_manifest(root, manifest_path, True)
    return manifest_path


def _execution_manifest_record(
    *,
    contract: g06.ExecutionContract | g06.BenchmarkContract | g06_4f.BenchmarkContract,
    run_id: str,
    source_commit: str,
    classification: str,
    input_artifacts: Sequence[Mapping[str, object]],
    output: Mapping[str, object] | None,
    checkpoints: Sequence[Mapping[str, object]],
    terminal_status: str,
    exception_metadata: Mapping[str, object] | None,
    hyperparameters: Mapping[str, object],
    hyperparameter_state: Mapping[str, object],
    start_timestamp: str,
    end_timestamp: str,
) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_name": g06.MANIFEST_SCHEMA_NAME,
        "schema_version": g06.MANIFEST_SCHEMA_VERSION,
        "paper1_run_id": run_id,
        "runner_source_commit": source_commit,
        "runner_identity": SCHEMA_VERSION,
        "scientific_run_git_commit": source_commit,
        "clean_tree": classification == RunnerMode.SCIENTIFIC.value,
        "environment_identity": f"python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "package_lock_identity": sha256_bytes(canonical_json({
            "numpy": np.__version__, "pandas": pd.__version__, "sklearn": LogisticRegression.__module__,
        })),
        "execution_contract_id": contract.contract_sha256,
        "analysis_id": getattr(contract, "analysis_id", getattr(contract, "benchmark_id", "")),
        "model_family": contract.model_family,
        "model_role": contract.model_role,
        "outer_evaluation": contract.evaluation_identity,
        "training_history": list(contract.training_intervals),
        "validation_history": sorted({value for _, validation in TUNING_SPLITS.get(
            contract.evaluation_identity, ()) for value in validation}),
        "heldout_history": list(contract.heldout_intervals),
        "hyperparameters": dict(hyperparameters),
        "hyperparameter_state": dict(hyperparameter_state),
        "random_seeds": list(
            RF_SEEDS if contract.model_family == "RANDOM_FOREST"
            else () if contract.model_family in {
                "TRAINING_PREVALENCE", "FRACTIONAL_LOGIT_GLM"
            }
            else (PRIMARY_SEED,)
        ),
        "input_artifacts": [dict(item) for item in input_artifacts],
        "output_prediction_artifact": None if output is None else dict(output),
        "checkpoints": [dict(item) for item in checkpoints],
        "start_timestamp_utc": start_timestamp,
        "end_timestamp_utc": end_timestamp,
        "process_metadata": {"pid": os.getpid(), "mode": classification},
        "child_process_metadata": [],
        "terminal_status": terminal_status,
        "exception_metadata": None if exception_metadata is None else dict(exception_metadata),
        "evidence_classification": classification,
        "manifest_role": g06.MANIFEST_ROLE,
    }
    if tuple(record) != tuple(g06.EXECUTION_MANIFEST_REQUIRED_FIELDS):
        raise RunnerError("G07_MANIFEST_31_FIELD_ORDER")
    return record


def _authenticate_persisted_ingress(
    contract: g06.ExecutionContract,
    manifest_path: Path,
    scientific_project_root: Path,
) -> AuthenticatedExecutionInput:
    path = Path(manifest_path).resolve()
    root = path.parents[2]
    validated = g06.validate_execution_manifest(root, path, True)
    record = validated.record
    bindings = {
        "execution_contract_id": contract.contract_sha256,
        "analysis_id": contract.analysis_id,
        "model_family": contract.model_family,
        "model_role": contract.model_role,
        "outer_evaluation": contract.evaluation_identity,
    }
    if any(record[key] != value for key, value in bindings.items()):
        raise RunnerError("G07_SYNTHETIC_INGRESS_BINDING")
    classification = str(record["evidence_classification"])
    if classification not in {RunnerMode.SYNTHETIC.value, RunnerMode.SCIENTIFIC.value}:
        raise RunnerError("G07_PERSISTED_INGRESS_CLASSIFICATION")
    if classification == RunnerMode.SCIENTIFIC.value and root != Path(scientific_project_root).resolve():
        raise RunnerError("G07_SCIENTIFIC_INGRESS_PROJECT_ROOT")
    predictor_items = [item for item in record["input_artifacts"]
                       if item["schema"] == "PAPER1_G07_AUTHENTICATED_PREDICTOR_INPUT_V1"]
    outcome_items = [item for item in record["input_artifacts"]
                     if item["schema"] == g06.OUTCOME_INPUT_SCHEMA]
    if len(predictor_items) != 1 or len(outcome_items) != 1:
        raise RunnerError("G07_SYNTHETIC_INGRESS_ARTIFACTS")
    predictor = pd.read_csv(root / predictor_items[0]["path"])
    outcome = pd.read_csv(root / outcome_items[0]["path"])
    if _g06_4e_key_identity(predictor) != predictor_items[0]["key_identity"]:
        raise RunnerError("G07_SYNTHETIC_PREDICTOR_KEY_IDENTITY")
    if _g06_4e_key_identity(outcome, include_y=True) != outcome_items[0]["key_identity"]:
        raise RunnerError("G07_SYNTHETIC_OUTCOME_KEY_IDENTITY")
    frame = predictor.merge(outcome, on=[*g06.KEY_FIELDS, "interval_number"], validate="one_to_one")
    if frame[list(g06.KEY_FIELDS)].duplicated().any():
        raise RunnerError("G07_SYNTHETIC_INGRESS_SEMANTICS")
    _validate_response_semantics(frame["y"], contract)
    return AuthenticatedExecutionInput(
        classification, str(root), frame,
        tuple(MappingProxyType(dict(item)) for item in record["input_artifacts"]),
        validated.manifest_sha256, str(path), MappingProxyType(dict(record["hyperparameters"])),
    )


def _validate_response_semantics(
    response: pd.Series,
    contract: g06.ExecutionContract,
) -> None:
    values = pd.to_numeric(response, errors="coerce").to_numpy(dtype=float)
    if contract.model_family == "FRACTIONAL_LOGIT_GLM":
        valid = (
            len(values) > 0 and np.isfinite(values).all()
            and (values >= 0).all() and (values <= 1).all()
        )
    else:
        valid = len(values) > 0 and np.isfinite(values).all() and set(values).issubset({0.0, 1.0})
    if not valid:
        raise RunnerError("G07_SYNTHETIC_INGRESS_SEMANTICS")


def _support_frame(root: Path, contract: g06.ExecutionContract) -> pd.DataFrame:
    handle = g06.authenticate_support_artifact(root, contract)
    path = root / handle.relative_path
    support = pd.read_parquet(path)
    selector, included = "support_universe_id", "included"
    required = {*g06.KEY_FIELDS, selector, included}
    if not required.issubset(support.columns):
        raise RunnerError("G07_SUPPORT_SCHEMA")
    selected = support.loc[
        support[selector].eq(contract.support_identity) & support[included].eq(True),
        list(g06.KEY_FIELDS),
    ]
    if selected.empty or selected.duplicated().any():
        raise RunnerError("G07_SUPPORT_SELECTION")
    return selected


def _merge_authoritative_interval_inputs(
    predictor: pd.DataFrame,
    support: pd.DataFrame,
    outcome: pd.DataFrame,
) -> pd.DataFrame:
    """Join governed inputs while retaining the persisted interval identity."""
    keys = list(g06.KEY_FIELDS)
    interval = "interval_number"
    for name, frame, required in (
        ("PREDICTOR", predictor, [*keys, interval]),
        ("SUPPORT", support, keys),
        ("OUTCOME", outcome, [*keys, interval]),
    ):
        missing = sorted(set(required) - set(frame.columns))
        if missing:
            raise RunnerError(f"G07_{name}_INTERVAL_SCHEMA:{missing}")
        if frame.loc[:, keys].isna().any().any() or frame.loc[:, keys].duplicated().any():
            raise RunnerError(f"G07_{name}_KEY_IDENTITY")
    if (predictor[interval].isna().any() or outcome[interval].isna().any() or
            not pd.api.types.is_integer_dtype(predictor[interval].dtype) or
            not pd.api.types.is_integer_dtype(outcome[interval].dtype) or
            predictor[interval].dtype != outcome[interval].dtype):
        raise RunnerError("G07_INTERVAL_TYPE_IDENTITY")

    predictor_selected = predictor.merge(
        support, on=keys, how="inner", validate="one_to_one"
    )
    outcome_selected = outcome.merge(
        support, on=keys, how="inner", validate="one_to_one"
    )
    if len(predictor_selected) != len(support) or len(outcome_selected) != len(support):
        raise RunnerError("G07_INTERVAL_SUPPORT_KEY_COVERAGE")
    identity_columns = [*keys, interval]
    predictor_identity = predictor_selected.loc[:, identity_columns].sort_values(
        identity_columns, kind="stable"
    ).reset_index(drop=True)
    outcome_identity = outcome_selected.loc[:, identity_columns].sort_values(
        identity_columns, kind="stable"
    ).reset_index(drop=True)
    if not predictor_identity.equals(outcome_identity):
        raise RunnerError("G07_INTERVAL_IDENTITY_CONFLICT")
    frame = predictor_selected.merge(
        outcome, on=identity_columns, how="inner", validate="one_to_one"
    )
    if len(frame) != len(support) or interval not in frame.columns:
        raise RunnerError("G07_INTERVAL_CANONICAL_MERGE")
    return frame


def _g06_4_accepted_authority(root: Path) -> Mapping[str, object]:
    g06_4e.g06_4e_lifecycle_authority(root)
    path = Path(root) / "documentation/PAPER1_G06_4_ACCEPTED_AUTHORITY.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "PAPER1_G06.4_ACCEPTED_AUTHORITY_V1":
        raise RunnerError("G07_G06_4_AUTHORITY_SCHEMA")
    return MappingProxyType(payload)


def _validate_accepted_g06_4_contract_set(
    root: Path,
    contract: g06.ExecutionContract,
    family: str,
) -> str:
    g06.validate_execution_contract(root, contract)
    authority = _g06_4_accepted_authority(root)
    section_name = (
        "realized_weather" if family == "REALIZED_WEATHER" else
        "boundary_filters" if family == "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY" else
        None
    )
    if section_name is None or contract.analysis_family != family:
        raise RunnerError("G07_G06_4_CONTRACT_FAMILY")
    section = authority[section_name]
    build_head = str(authority["g06_4_build_base_head"])
    pairs: list[tuple[str, str]] = []
    bound_hash = ""
    for item in g06.governed_execution_contracts(root):
        if item.analysis_family != family:
            continue
        values = asdict(item)
        values.pop("contract_sha256")
        values["git_head"] = build_head
        historical_hash = sha256_bytes(g06.canonical_json(values))
        unit = _unit_id(item)
        pairs.append((unit, historical_hash))
        if unit == _unit_id(contract):
            bound_hash = historical_hash
    ordered = tuple(sorted(pairs))
    if (len(ordered) != int(section["contract_count"]) or
            sha256_bytes(g06.canonical_json(ordered)) != section["contract_set_sha256"]):
        raise RunnerError(f"G07_G06_4_{family}_CONTRACT_SET")
    if not bound_hash:
        raise RunnerError(f"G07_G06_4_{family}_CONTRACT")
    return bound_hash


def _bind_realized_weather_ingress(
    root: Path,
    contract: g06.ExecutionContract,
    handle: g06.AuthenticatedRealizedWeatherArtifact,
    classification: str,
) -> g06.AuthenticatedRealizedWeatherArtifact:
    if classification != RunnerMode.SCIENTIFIC.value:
        raise RunnerError("G07_REALIZED_WEATHER_CLASSIFICATION")
    _validate_accepted_g06_4_contract_set(root, contract, "REALIZED_WEATHER")
    authority_record = _g06_4_accepted_authority(root)
    expected_authority = g06_4e._previous._realized_authority(
        authority_record, contract.resolution_m
    )
    frame = handle.to_frame()
    columns = (*expected_authority.key_fields, expected_authority.interval_field,
               *expected_authority.fields)
    if (handle.schema_version != "PAPER1_G06.4_REALIZED_WEATHER_HANDLE_V1" or
            handle.gate_version != g06.G06_4_GATE_VERSION or
            handle.authentication_result != "PASS" or
            handle.governed_contract_sha256 != "UNBOUND" or
            handle.authority != expected_authority or
            handle.observed_sha256 != expected_authority.expected_sha256 or
            handle.observed_manifest_sha256 != expected_authority.manifest_sha256 or
            handle.observed_row_count != expected_authority.row_count or
            handle.observed_key_sha256 != expected_authority.canonical_key_sha256 or
            handle.observed_key_interval_value_sha256 !=
            expected_authority.key_interval_value_sha256 or
            tuple(frame.columns) != columns or
            g06.key_sha256(frame) != expected_authority.canonical_key_sha256 or
            g06_4e._previous._frame_hash(frame, columns) !=
            expected_authority.key_interval_value_sha256 or
            handle.authority.risk_set_id != contract.risk_set_id):
        raise RunnerError("G07_REALIZED_WEATHER_HANDLE_BINDING")
    return replace(handle, governed_contract_sha256=contract.contract_sha256)


def _authenticate_realized_weather_ingress(
    root: Path,
    contract: g06.ExecutionContract,
    classification: str,
) -> g06.AuthenticatedRealizedWeatherArtifact:
    authority_record = _g06_4_accepted_authority(root)
    authorities = g06_4e._validate_g06_4_weather_sources(root, authority_record)
    matches = [item for item in authorities if item.resolution_m == contract.resolution_m]
    if len(matches) != 1:
        raise RunnerError("G07_REALIZED_WEATHER_RESOLUTION")
    authority = matches[0]
    columns = (*authority.key_fields, authority.interval_field, *authority.fields)
    frame = pd.read_parquet(Path(root) / authority.relative_path, columns=list(columns))
    ordered = frame.sort_values(list(authority.key_fields), kind="stable").reset_index(drop=True)
    handle = g06.AuthenticatedRealizedWeatherArtifact(
        "PAPER1_G06.4_REALIZED_WEATHER_HANDLE_V1", g06.G06_4_GATE_VERSION,
        str(Path(root).resolve()), authority,
        g06.sha256_file(Path(root) / authority.relative_path),
        g06.sha256_file(Path(root) / authority.manifest_path),
        len(ordered), authority.canonical_key_sha256,
        authority.key_interval_value_sha256, tuple(ordered.columns),
        tuple(str(value) for value in ordered.dtypes),
        tuple(tuple(row) for row in ordered.itertuples(index=False, name=None)),
        "UNBOUND",
    )
    return _bind_realized_weather_ingress(root, contract, handle, classification)


def _boundary_threshold_from_registry(
    contract: g06.ExecutionContract,
    registry_frame: pd.DataFrame,
) -> int:
    required = {"analysis_id", "fold_or_threshold"}
    if not required.issubset(registry_frame.columns):
        raise RunnerError("G07_BOUNDARY_THRESHOLD_SCHEMA")
    matches = registry_frame.loc[registry_frame["analysis_id"].eq(contract.analysis_id)]
    if len(matches) != 1:
        raise RunnerError("G07_BOUNDARY_THRESHOLD_AUTHORITY")
    rule = str(matches.iloc[0]["fold_or_threshold"])
    parsed = re.fullmatch(
        r"threshold_m=(500|1000); retain within_either_boundary_\1m == False", rule
    )
    if parsed is None:
        raise RunnerError("G07_BOUNDARY_THRESHOLD_RULE")
    threshold = int(parsed.group(1))
    if contract.analysis_id != f"G05B_BOUNDARY_{threshold}":
        raise RunnerError("G07_BOUNDARY_THRESHOLD_CONTRACT")
    return threshold


def _boundary_threshold_m(root: Path, contract: g06.ExecutionContract) -> int:
    g06.validate_execution_contract(root, contract)
    if contract.analysis_family != "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY":
        raise RunnerError("G07_BOUNDARY_CONTRACT_FAMILY")
    registry_path = Path(root) / contract.registry_source
    if g06.sha256_file(registry_path) != contract.registry_sha256:
        raise RunnerError("G07_BOUNDARY_REGISTRY_IDENTITY")
    threshold = _boundary_threshold_from_registry(contract, pd.read_csv(registry_path))
    authority = _g06_4_accepted_authority(root)["boundary_filters"]
    expected_flag = authority["flags"].get(str(threshold))
    if expected_flag != f"within_either_boundary_{threshold}m":
        raise RunnerError("G07_BOUNDARY_THRESHOLD_FLAG")
    return threshold


def _bind_boundary_ingress(
    root: Path,
    contract: g06.ExecutionContract,
    handle: g06.AuthenticatedBoundaryFilterArtifact,
    classification: str,
) -> g06.AuthenticatedBoundaryFilterArtifact:
    if classification != RunnerMode.SCIENTIFIC.value:
        raise RunnerError("G07_BOUNDARY_CLASSIFICATION")
    _validate_accepted_g06_4_contract_set(
        root, contract, "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY"
    )
    threshold = _boundary_threshold_m(root, contract)
    flag = f"within_either_boundary_{threshold}m"
    authority_record = _g06_4_accepted_authority(root)
    expected_authority = g06_4e._previous._boundary_authority(authority_record)
    frame = handle.to_filter_frame()
    columns = (*expected_authority.key_fields, expected_authority.interval_field,
               *expected_authority.flag_fields)
    if (handle.schema_version != "PAPER1_G06.4_BOUNDARY_FILTER_HANDLE_V1" or
            handle.gate_version != g06.G06_4_GATE_VERSION or
            handle.authentication_result != "PASS" or
            handle.predictor_use != "PROHIBITED" or
            handle.governed_contract_sha256 != "UNBOUND" or
            handle.authority != expected_authority or
            handle.observed_sha256 != expected_authority.expected_sha256 or
            handle.observed_row_count != expected_authority.row_count or
            handle.observed_key_sha256 != expected_authority.canonical_key_sha256 or
            handle.observed_key_interval_flag_sha256 !=
            expected_authority.key_interval_flag_sha256 or
            tuple(frame.columns) != columns or
            g06.key_sha256(frame) != expected_authority.canonical_key_sha256 or
            g06_4e._previous._frame_hash(frame, columns) !=
            expected_authority.key_interval_flag_sha256 or
            handle.authority.resolution_m != contract.resolution_m or
            flag not in handle.authority.flag_fields):
        raise RunnerError("G07_BOUNDARY_HANDLE_BINDING")
    return replace(
        handle, governed_threshold_m=threshold, governed_flag_field=flag,
        governed_contract_sha256=contract.contract_sha256,
    )


def _authenticate_boundary_ingress(
    root: Path,
    contract: g06.ExecutionContract,
    classification: str,
) -> g06.AuthenticatedBoundaryFilterArtifact:
    authority_record = _g06_4_accepted_authority(root)
    validated = g06_4e._validate_g06_4_boundary_source(root, authority_record)
    authority = validated["authority"]
    columns = (*authority.key_fields, authority.interval_field, *authority.flag_fields)
    frame = pd.read_parquet(Path(root) / authority.relative_path, columns=list(columns))
    ordered = frame.sort_values(list(authority.key_fields), kind="stable").reset_index(drop=True)
    handle = g06.AuthenticatedBoundaryFilterArtifact(
        "PAPER1_G06.4_BOUNDARY_FILTER_HANDLE_V1", g06.G06_4_GATE_VERSION,
        str(Path(root).resolve()), authority,
        g06.sha256_file(Path(root) / authority.relative_path), len(ordered),
        authority.canonical_key_sha256, authority.key_interval_flag_sha256,
        tuple(ordered.columns), tuple(str(value) for value in ordered.dtypes),
        tuple(tuple(row) for row in ordered.itertuples(index=False, name=None)),
        0, "UNBOUND", "UNBOUND",
    )
    return _bind_boundary_ingress(root, contract, handle, classification)


def _authenticate_scientific_ingress(
    root: Path,
    contract: g06.ExecutionContract,
) -> AuthenticatedExecutionInput:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    if status.strip():
        raise RunnerError("G07_DIRTY_SCIENTIFIC_RUN")
    return _read_scientific_ingress(root, contract)


def _read_scientific_ingress(
    root: Path, contract: g06.ExecutionContract,
) -> AuthenticatedExecutionInput:
    """Read authenticated inputs for integrity checks; grants no execution authority."""
    predictor_handle = g06.authenticate_predictor_artifact(
        root, contract.risk_set_id, contract.resolution_m, root / contract.predictor_path
    )
    predictor_data = g06.load_authenticated_predictors(predictor_handle, contract)
    g06.validate_authenticated_predictor_data(predictor_data, contract)
    predictor = predictor_data.to_frame()
    outcome_handle = g06.authenticate_outcome_for_contract(root, contract)
    outcome = pd.DataFrame([asdict(row) for row in outcome_handle.rows]).rename(
        columns={"response_y": "y"}
    )
    support = _support_frame(root, contract)
    frame = _merge_authoritative_interval_inputs(predictor, support, outcome)
    if contract.analysis_family == "REALIZED_WEATHER":
        weather = _authenticate_realized_weather_ingress(
            root, contract, RunnerMode.SCIENTIFIC.value
        )
        frame = frame.merge(
            weather.to_frame(), on=[*g06.KEY_FIELDS, "interval_number"],
            validate="one_to_one",
        )
    if contract.analysis_family == "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY":
        boundary = _authenticate_boundary_ingress(
            root, contract, RunnerMode.SCIENTIFIC.value
        )
        flags = boundary.to_filter_frame()
        frame = frame.merge(
            flags, on=[*g06.KEY_FIELDS, "interval_number"], validate="one_to_one"
        )
        frame = frame.loc[~frame[boundary.governed_flag_field].astype(bool)].copy()
    input_artifacts = (
        MappingProxyType({"path": contract.predictor_path, "sha256": contract.predictor_sha256,
                          "schema": "PAPER1_G06_AUTHENTICATED_PREDICTOR_INPUT_V1",
                          "key_identity": contract.predictor_key_sha256}),
        MappingProxyType({"path": contract.response_path, "sha256": contract.response_sha256,
                          "schema": g06.OUTCOME_INPUT_SCHEMA,
                          "key_identity": contract.response_key_interval_value_sha256}),
        MappingProxyType({"path": contract.support_path, "sha256": contract.support_sha256,
                          "schema": "PAPER1_G06_AUTHENTICATED_SUPPORT_INPUT_V1",
                          "key_identity": sha256_bytes(contract.support_identity.encode("utf-8"))}),
    )
    return AuthenticatedExecutionInput(
        RunnerMode.SCIENTIFIC.value, str(root), frame, input_artifacts,
        sha256_bytes(canonical_json([dict(item) for item in input_artifacts])),
        "G06.4E_PERSISTED_AUTHORITY", MappingProxyType({
            "hyperparameter_policy": {
                **asdict(v2_policy.resolve_policy(contract)),
                "mode": v2_policy.resolve_policy(contract).mode.value,
            },
            "hyperparameter_policy_sha256": v2_policy.resolve_policy(contract).policy_sha256,
        }),
    )


def _authenticate_execution_input(context: _DispatchContext) -> AuthenticatedExecutionInput:
    request = context.request
    if request.input_manifest_path is not None:
        return _authenticate_persisted_ingress(
            context.contract, request.input_manifest_path, context.project_root
        )
    return _authenticate_scientific_ingress(context.project_root, context.contract)


def _analysis_for_contract(root: Path, contract: g06.ExecutionContract):
    matches = [item for item in analysis_registry.registry(root)
               if item.analysis_id == contract.analysis_id]
    return matches[0] if len(matches) == 1 else None


def _prepare_governed_design(
    context: _DispatchContext,
    frame: pd.DataFrame,
    training_index: pd.Index,
) -> pd.DataFrame:
    contract = context.contract
    family = (
        "logistic"
        if contract.model_family in {"L2_LOGISTIC", "FRACTIONAL_LOGIT_GLM"}
        else "rf"
    )
    analysis = _analysis_for_contract(context.project_root, contract)
    if analysis is not None:
        realized = frame if analysis.family == "REALIZED_WEATHER" else None
        pair = comparators.build_pair(
            analysis, frame, family, tuple(contract.training_intervals),
            realized_weather=realized, training_index=training_index,
        )
        design = pair.baseline if contract.model_role == "baseline" else pair.augmented
    else:
        role = "augmented" if contract.model_role == "augmented" else "baseline"
        design = _prepare_design(frame, contract.model_family, role, training_index)[0]
    if not frame.index.is_unique or not design.index.equals(frame.index):
        raise RunnerError("G07_DESIGN_FRAME_ROW_IDENTITY")
    if frame.loc[:, list(g06.KEY_FIELDS)].duplicated().any():
        raise RunnerError("G07_DESIGN_GOVERNED_KEY_IDENTITY")
    return design


def _aligned_model_rows(
    frame: pd.DataFrame,
    design: pd.DataFrame,
    index: pd.Index,
    stage: str,
) -> tuple[pd.DataFrame, pd.Series]:
    rows = pd.Index(index)
    if (not frame.index.is_unique or not design.index.is_unique or not rows.is_unique or
            not design.index.equals(frame.index) or not rows.isin(frame.index).all()):
        raise RunnerError(f"G07_{stage}_ROW_IDENTITY")
    keys = frame.loc[rows, list(g06.KEY_FIELDS)]
    if keys.duplicated().any():
        raise RunnerError(f"G07_{stage}_KEY_IDENTITY")
    x = design.loc[rows]
    y = frame.loc[rows, "y"]
    if not x.index.equals(y.index) or not x.index.equals(rows):
        raise RunnerError(f"G07_{stage}_X_Y_KEY_ORDER")
    return x, y


def _configuration_for(classification: str) -> RunnerConfiguration:
    if classification == RunnerMode.SYNTHETIC.value:
        return SYNTHETIC_CONFIGURATION
    if classification == RunnerMode.SCIENTIFIC.value:
        return SCIENTIFIC_CONFIGURATION
    raise RunnerError("G07_EVIDENCE_CLASSIFICATION")


def _governed_policy(context: _DispatchContext) -> v2_policy.HyperparameterPolicy:
    policy = v2_policy.resolve_policy(context.contract)
    v2_policy.validate_policy(policy)
    return policy


def _v2_run_id(unit_id: str) -> str:
    return f"{v2_policy.V2_SUITE_RUN_ID}__{sha256_bytes(unit_id.encode('utf-8'))[:20]}"


def _inheritance_authority(
    context: _DispatchContext,
    policy: v2_policy.HyperparameterPolicy,
) -> Mapping[str, object]:
    from src.paper1_control_execution import active_operation
    operation = active_operation(context.project_root)
    if operation is not None:
        return operation.inheritance(context, policy)
    parent_unit = policy.inheritance_parent_unit_id
    if policy.mode is not v2_policy.PolicyMode.INHERIT or not parent_unit:
        raise RunnerError("G07_V2_INHERITANCE_POLICY_REQUIRED")
    parent_root = Path(context.request.output_root).resolve() / _v2_run_id(parent_unit)
    pointer_path = parent_root / "checkpoint.current.json"
    manifest_path = parent_root / "execution_manifest.json"
    if not pointer_path.is_file() or not manifest_path.is_file():
        raise RunnerError("G07_V2_INHERITANCE_PARENT_STAGED")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    checkpoint_path = (context.project_root / str(pointer.get("path", ""))).resolve()
    try:
        checkpoint_path.relative_to(context.project_root.resolve())
    except ValueError as exc:
        raise RunnerError("G07_V2_INHERITANCE_PARENT_CHECKPOINT_PATH") from exc
    if not checkpoint_path.is_file() or sha256_file(checkpoint_path) != pointer.get("sha256"):
        raise RunnerError("G07_V2_INHERITANCE_PARENT_STALE")
    wrapper = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if sha256_bytes(canonical_json(wrapper.get("payload"))) != wrapper.get("payload_sha256"):
        raise RunnerError("G07_V2_INHERITANCE_PARENT_HASH")
    state = wrapper["payload"]
    if state.get("current_phase") != "COMPLETE" or state.get("source_commit") != _git_head(context.project_root):
        raise RunnerError("G07_V2_INHERITANCE_PARENT_NOT_CURRENT_COMPLETE")
    if state.get("identity", {}).get("unit_id") != parent_unit:
        raise RunnerError("G07_V2_INHERITANCE_PARENT_UNIT")
    contracts = [
        item for item in g06.governed_execution_contracts(context.project_root)
        if _unit_id(item) == parent_unit
    ]
    if len(contracts) != 1:
        raise RunnerError("G07_V2_INHERITANCE_PARENT_CONTRACT")
    parent_manifest = g06.validate_execution_manifest(
        context.project_root, manifest_path, True
    ).record
    if (parent_manifest.get("paper1_run_id") != _v2_run_id(parent_unit) or
            parent_manifest.get("execution_contract_id") != contracts[0].contract_sha256 or
            parent_manifest.get("runner_identity") != SCHEMA_VERSION or
            parent_manifest.get("runner_source_commit") != _git_head(context.project_root) or
            parent_manifest.get("terminal_status") != "COMPLETE"):
        raise RunnerError("G07_V2_INHERITANCE_PARENT_MANIFEST_BINDING")
    parent_policy = v2_policy.resolve_policy(contracts[0])
    v2_policy.validate_checkpoint_policy(state.get("identity", {}), parent_policy)
    selected = state.get("selected_hyperparameter")
    if selected is None:
        raise RunnerError("G07_V2_INHERITANCE_PARENT_VALUE")
    if parent_policy.mode is v2_policy.PolicyMode.FIXED and float(selected) != parent_policy.fixed_value:
        raise RunnerError("G07_V2_INHERITANCE_PARENT_FIXED_VALUE")
    if parent_policy.mode is v2_policy.PolicyMode.TUNE and float(selected) not in parent_policy.candidates:
        raise RunnerError("G07_V2_INHERITANCE_PARENT_TUNED_VALUE")
    try:
        return v2_policy.validate_inheritance_claim(
            policy, parent_unit_id=parent_unit,
            parent_policy_sha256=parent_policy.policy_sha256,
            parent_checkpoint_sha256=str(pointer["sha256"]),
            parent_manifest_sha256=sha256_file(manifest_path),
            selected_hyperparameter=float(selected),
        )
    except v2_policy.PolicyError as exc:
        raise RunnerError(str(exc)) from exc


def _requires_tuning(context: _DispatchContext) -> bool:
    return _governed_policy(context).mode is v2_policy.PolicyMode.TUNE


def _tune_governed(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    run_root: Path,
) -> TuningReceipt:
    contract, frame = context.contract, authenticated.frame
    configuration = _configuration_for(authenticated.evidence_classification)
    policy = _governed_policy(context)
    if policy.mode is not v2_policy.PolicyMode.TUNE:
        raise RunnerError("G07_V2_TUNING_POLICY_REQUIRED")
    candidates = policy.candidates
    splits = TUNING_SPLITS[contract.evaluation_identity]
    split_rows: list[tuple[float, int, float]] = []
    preprocessing_hashes: list[str] = []
    candidate_receipts: list[tuple[float, int, str]] = []
    scores_by_candidate: dict[float, float] = {}
    for candidate in candidates:
        scores = []
        for split_index, (train_intervals, validation_intervals) in enumerate(splits, start=1):
            training_index = frame.index[frame.interval_number.isin(train_intervals)]
            validation_index = frame.index[frame.interval_number.isin(validation_intervals)]
            design = _prepare_governed_design(context, frame, training_index)
            x_train, y_train = _aligned_model_rows(
                frame, design, training_index, "INNER_TRAINING"
            )
            x_validation, _ = _aligned_model_rows(
                frame, design, validation_index, "INNER_VALIDATION"
            )
            probabilities = _fit_probabilities(
                configuration, contract.model_family, x_train,
                y_train, x_validation,
                float(candidate), PRIMARY_SEED,
            )
            score = _score_by_interval(frame.loc[validation_index], probabilities)
            evidence = _prediction_frame(
                frame, validation_index, probabilities, contract.analysis_id,
                contract.model_family, contract.model_role, contract.evaluation_identity, PRIMARY_SEED,
            )
            receipt = _write_frame_artifact(
                run_root / "tuning_candidates" / f"candidate_{candidate}_split_{split_index}.csv",
                evidence, "PRODUCTION_TUNING_CANDIDATE", run_root,
            )
            split_rows.append((float(candidate), split_index, score))
            candidate_receipts.append((float(candidate), split_index, receipt.receipt_sha256))
            preprocessing_hashes.append(sha256_bytes(canonical_json(list(design.columns))))
            scores.append(score)
        scores_by_candidate[float(candidate)] = float(np.mean(scores))
    selected = model_spec.choose_hyperparameter(scores_by_candidate, "logistic" if contract.model_family == "L2_LOGISTIC" else "rf")
    payload = {
        "schema_version": "PAPER1_G07_PRODUCTION_TUNING_RECEIPT_V1",
        "model_family": contract.model_family,
        "model_role": contract.model_role,
        "outer_evaluation": contract.evaluation_identity,
        "candidates": tuple(float(value) for value in candidates),
        "splits": tuple(splits),
        "split_scores": tuple(split_rows),
        "candidate_scores": tuple(sorted(scores_by_candidate.items())),
        "selected_hyperparameter": float(selected),
        "tie_rule": "WITHIN_1E-12_SELECT_CONSERVATIVE_SMALLER",
        "tuning_seed": PRIMARY_SEED,
        "training_preprocessing_sha256s": tuple(preprocessing_hashes),
        "candidate_prediction_receipts": tuple(candidate_receipts),
    }
    return TuningReceipt(**payload, receipt_sha256=sha256_bytes(canonical_json(payload)))


def _checkpoint_identity(context: _DispatchContext, authenticated: AuthenticatedExecutionInput) -> dict[str, object]:
    configuration = _configuration_for(authenticated.evidence_classification)
    config = asdict(configuration)
    config["mode"] = configuration.mode.value
    policy = _governed_policy(context)
    inheritance = (
        _inheritance_authority(context, policy)
        if policy.mode is v2_policy.PolicyMode.INHERIT else None
    )
    return {
        "run_id": context.request.run_id,
        "contract_sha256": context.contract.contract_sha256,
        "unit_id": context.plan_entry.unit_id,
        "classification": authenticated.evidence_classification,
        "analysis_id": context.contract.analysis_id,
        "analysis_family": context.contract.analysis_family,
        "model_family": context.contract.model_family,
        "evaluation": context.contract.evaluation_identity,
        "model_role": context.contract.model_role,
        "input_identity": authenticated.source_manifest_sha256,
        "environment_configuration_sha256": sha256_bytes(canonical_json(config)),
        "seed_identity": sha256_bytes(canonical_json(list(configuration.rf_seeds))),
        "policy_schema_version": v2_policy.POLICY_SCHEMA_VERSION,
        "hyperparameter_policy_sha256": policy.policy_sha256,
        "hyperparameter_policy_mode": policy.mode.value,
        "inheritance_authority_sha256": (
            None if inheritance is None else inheritance["authority_sha256"]
        ),
    }


def _governed_resume_authority_transition(
    context: _DispatchContext,
    historical_source_commit: str,
) -> Mapping[str, str]:
    """Authenticate the accepted G08 lineage from checkpoint to current authority."""
    try:
        from src import paper1_g08_runtime as g08

        transition = g08.validate_evidence_producer_activation(
            context.project_root, historical_source_commit
        )
    except Exception as exc:
        raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY") from exc
    if transition.get("source_commit") != historical_source_commit:
        raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
    receipt = context.authorization_receipt
    execution_identity = (
        receipt.get("execution_identity") if isinstance(receipt, Mapping) else None
    )
    identity_payload = (
        dict(execution_identity) if isinstance(execution_identity, Mapping) else {}
    )
    nested_identity_sha256 = identity_payload.pop("execution_identity_sha256", None)
    if (
        not isinstance(receipt, Mapping)
        or set(receipt) != {
            "schema_name", "schema_version", "authorization_state",
            "authorization_parent_commit", "execution_identity",
            "execution_identity_sha256",
        }
        or receipt.get("authorization_state") != "AUTHORIZED"
        or not isinstance(execution_identity, Mapping)
        or receipt.get("execution_identity_sha256")
        != nested_identity_sha256
        or nested_identity_sha256
        != sha256_bytes(canonical_json(identity_payload))
    ):
        raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
    accepted_pair = (
        str(execution_identity.get("accepted_g07_implementation_commit", "")),
        str(execution_identity.get("independent_g07_acceptance_commit", "")),
    )
    # Historical acceptance never authenticates the current source or activation.
    # Reconsume G08's committed authority even when the historical pair matches.
    try:
        current_authority = g08.repository_authority(context.project_root)
        current_receipt = g08.consume_scientific_authorization(
            context.project_root, context.request
        )
    except Exception as exc:
        raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY") from exc
    current_pair = (
        str(current_authority.get("accepted_g07_implementation_commit", "")),
        str(current_authority.get("independent_g07_acceptance_commit", "")),
    )
    if (
        accepted_pair != current_pair
        or canonical_json(dict(receipt)) != canonical_json(dict(current_receipt))
        or current_authority.get("head") != _git_head(context.project_root)
        or current_authority.get("head") != context.contract.git_head
    ):
        raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
    return MappingProxyType({
        "transition_id": str(transition["transition_id"]),
        "historical_activation_commit": historical_source_commit,
        "accepted_g07_implementation_commit": accepted_pair[0],
        "independent_g07_acceptance_commit": accepted_pair[1],
        "authorization_identity_sha256": str(receipt["execution_identity_sha256"]),
    })


def _validate_governed_resume_identity_migration(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    historical_identity: object,
    historical_source_commit: object,
    current_identity: Mapping[str, object],
) -> Mapping[str, object]:
    """Prove a provenance-only contract migration without weakening exact resume."""
    try:
        if (
            not isinstance(historical_identity, Mapping)
            or set(historical_identity) != set(current_identity)
            or not isinstance(historical_source_commit, str)
            or re.fullmatch(r"[0-9a-f]{40}", historical_source_commit) is None
        ):
            raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
        for key, expected in current_identity.items():
            if key != "contract_sha256" and historical_identity.get(key) != expected:
                raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
        from src import paper1_g08_runtime as g08

        plan, contracts = g08.governed_plan(context.project_root)
        historical_plan, historical_contracts = g08._parent_scoped_plan_and_contracts(
            plan, contracts, historical_source_commit
        )
        current_matches = [
            item for item in contracts if _unit_id(item) == context.plan_entry.unit_id
        ]
        historical_matches = [
            item for item in historical_contracts
            if _unit_id(item) == context.plan_entry.unit_id
        ]
        historical_plan_matches = [
            item for item in historical_plan
            if item.unit_id == context.plan_entry.unit_id
        ]
        if (
            len(current_matches) != 1
            or len(historical_matches) != 1
            or len(historical_plan_matches) != 1
            or asdict(current_matches[0]) != asdict(context.contract)
        ):
            raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
        historical_contract = historical_matches[0]
        if (
            historical_contract.contract_sha256
            != historical_identity.get("contract_sha256")
            or historical_plan_matches[0].contract_sha256
            != historical_contract.contract_sha256
            or current_identity.get("contract_sha256")
            != context.contract.contract_sha256
        ):
            raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
        historical_fields = asdict(historical_contract)
        current_fields = asdict(context.contract)
        differing_fields = tuple(sorted(
            key for key in current_fields
            if key != "contract_sha256"
            and current_fields[key] != historical_fields[key]
        ))
        if set(differing_fields) != set(
            RESUME_IDENTITY_MIGRATION_ELIGIBLE_CONTRACT_FIELDS
        ):
            raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
        if (
            historical_contract.git_head != historical_source_commit
            or context.contract.git_head != _git_head(context.project_root)
            or authenticated.source_manifest_sha256
            != current_identity.get("input_identity")
        ):
            raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
        authority = _governed_resume_authority_transition(
            context, historical_source_commit
        )
        payload = {
            "schema_version": RESUME_IDENTITY_MIGRATION_SCHEMA_VERSION,
            "status": "PASS_MIGRATED",
            "historical_source_commit": historical_source_commit,
            "current_source_commit": _git_head(context.project_root),
            "historical_contract_sha256": historical_contract.contract_sha256,
            "current_contract_sha256": context.contract.contract_sha256,
            "historical_identity": dict(historical_identity),
            "current_identity": dict(current_identity),
            "migration_eligible_field_differences": list(differing_fields),
            "authority_transition": dict(authority),
        }
        return MappingProxyType({
            **payload,
            "migration_receipt_sha256": sha256_bytes(canonical_json(payload)),
        })
    except RunnerError:
        raise
    except Exception as exc:
        raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY") from exc


def _validate_persisted_resume_identity_migration(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    migration: object,
    current_identity: Mapping[str, object],
) -> Mapping[str, object]:
    _validate_resume_identity_migration_structure(
        migration,
        migration.get("historical_identity") if isinstance(migration, Mapping) else None,
        current_identity,
    )
    if migration.get("current_identity") != dict(current_identity):
        raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
    expected = _validate_governed_resume_identity_migration(
        context,
        authenticated,
        migration.get("historical_identity"),
        migration.get("historical_source_commit"),
        current_identity,
    )
    if canonical_json(dict(expected)) != canonical_json(dict(migration)):
        raise RunnerError("G07_PRODUCTION_RESUME_IDENTITY")
    return expected


def _validate_resume_identity_migration_structure(
    migration: object,
    historical_identity: object,
    current_identity: object,
) -> Mapping[str, object]:
    expected_keys = {
        "schema_version", "status", "historical_source_commit",
        "current_source_commit", "historical_contract_sha256",
        "current_contract_sha256", "historical_identity", "current_identity",
        "migration_eligible_field_differences", "authority_transition",
        "migration_receipt_sha256",
    }
    if not isinstance(migration, Mapping) or set(migration) != expected_keys:
        raise RunnerError("G07_PRODUCTION_CHECKPOINT_IDENTITY_DRIFT")
    payload = dict(migration)
    observed_sha256 = payload.pop("migration_receipt_sha256")
    if (
        migration.get("schema_version")
        != RESUME_IDENTITY_MIGRATION_SCHEMA_VERSION
        or migration.get("status") != "PASS_MIGRATED"
        or observed_sha256 != sha256_bytes(canonical_json(payload))
        or migration.get("historical_identity") != historical_identity
        or migration.get("current_identity") != current_identity
        or not isinstance(historical_identity, Mapping)
        or not isinstance(current_identity, Mapping)
        or migration.get("historical_contract_sha256")
        != historical_identity.get("contract_sha256")
        or migration.get("current_contract_sha256")
        != current_identity.get("contract_sha256")
        or migration.get("migration_eligible_field_differences") != ["git_head"]
        or re.fullmatch(
            r"[0-9a-f]{40}", str(migration.get("historical_source_commit", ""))
        ) is None
        or re.fullmatch(
            r"[0-9a-f]{40}", str(migration.get("current_source_commit", ""))
        ) is None
    ):
        raise RunnerError("G07_PRODUCTION_CHECKPOINT_IDENTITY_DRIFT")
    if ({k: v for k, v in historical_identity.items() if k != "contract_sha256"}
            != {k: v for k, v in current_identity.items() if k != "contract_sha256"}):
        raise RunnerError("G07_PRODUCTION_CHECKPOINT_IDENTITY_DRIFT")
    return MappingProxyType(dict(migration))


def _state_contract_identity_matches(
    state: Mapping[str, object], observed: object, current: str,
) -> bool:
    if observed == current:
        return True
    migration = state.get("resume_identity_migration")
    return bool(
        isinstance(migration, Mapping)
        and migration.get("status") == "PASS_MIGRATED"
        and migration.get("historical_contract_sha256") == observed
        and migration.get("current_contract_sha256") == current
    )


def _read_migration_authority(
    project_root: Path, historical_source_commit: str, current_source_commit: str,
) -> Mapping[str, str]:
    """Reconstruct an evidence migration at its issuing activation; grants no execution."""
    from src import paper1_g08_runtime as g08, paper1_control_reference as reference
    if selected := reference.selected(project_root):
        return MappingProxyType(selected.migration(historical_source_commit, current_source_commit))

    root = Path(project_root).resolve()
    marker = "G07_EVIDENCE_MIGRATION_AUTHORITY"
    try:
        if historical_source_commit == current_source_commit:
            raise RunnerError(marker)
        historical_proof = g08.validate_evidence_producer_activation(root, historical_source_commit)
        g08.validate_evidence_producer_activation(root, current_source_commit)
        g08._require_ancestor(root, historical_source_commit, current_source_commit, marker)
        receipt = json.loads(g08._git_bytes(
            root, "show", f"{current_source_commit}:{g08.ACTIVE_AUTHORIZATION_RELATIVE.as_posix()}"
        ))
        identity = dict(receipt["execution_identity"])
        identity_hash = identity.pop("execution_identity_sha256")
        if (receipt.get("authorization_state") != "AUTHORIZED"
                or identity_hash != sha256_bytes(g08.canonical_json(identity))
                or receipt.get("execution_identity_sha256") != identity_hash):
            raise RunnerError(marker)
        implementation = identity["accepted_g07_implementation_commit"]
        acceptance = identity["independent_g07_acceptance_commit"]
        g08._require_ancestor(root, implementation, acceptance, marker)
        g08._require_ancestor(root, acceptance, current_source_commit, marker)

        # Resolve the route available to the issuing activation, not a route
        # introduced by later reviewer pins or a self-declared migration ID.
        frozen = g08._historical_governed_transition_record()
        if historical_source_commit == g08.PRIOR_G08_ACTIVATION_COMMIT:
            transition_id = "FROZEN_PRIOR_ACTIVATION:" + historical_source_commit
            if historical_proof["transition_id"] != transition_id:
                raise RunnerError(marker)
        elif historical_source_commit == frozen["prior_authority_tip"]:
            transition_id = str(frozen["transition_id"])
            if historical_proof["transition_id"] != transition_id:
                raise RunnerError(marker)
            g08._require_ancestor(root, str(frozen["downstream_acceptance_commit"]),
                                  current_source_commit, marker)
        else:
            gates = list(csv.DictReader(g08._git_bytes(
                root, "show", f"{current_source_commit}:{g08.INDEPENDENT_GATE_RELATIVE.as_posix()}"
            ).decode("utf-8").splitlines()))
            if len(gates) != 1:
                raise RunnerError(marker)
            gate = gates[0]
            issuer_implementation = gate["accepted_g08_implementation_commit"]
            issuer_acceptance = gate["accepted_g08_commit"]
            records = g08._load_governed_transition_extensions(root, issuer_implementation)
            matches = [r for r in records if r["prior_authority_tip"] == historical_source_commit]
            if len(matches) > 1:
                raise RunnerError(marker)
            if matches:
                validated = g08.validate_governed_downstream_transition(root, matches[0])
                g08._require_ancestor(root, validated["downstream_acceptance_commit"],
                                      current_source_commit, marker)
                transition_id = validated["transition_id"]
            else:
                issuer = g08._validate_g08_acceptance_without_pins(
                    root, issuer_implementation, issuer_acceptance)
                lineage = issuer["implementation_lineage"]
                if (lineage.get("bridge_required") is not True
                        or lineage["chain_facts"]["downstream"]["prior_authority_tip"]
                        != historical_source_commit):
                    raise RunnerError(marker)
                bridge = g08._git(root, "rev-parse", f"{current_source_commit}^")
                validated = g08._validate_bridge_history(
                    root, issuer_implementation, issuer_acceptance, bridge)
                transition_id = "PINNED_TRANSITION_BRIDGE:" + validated["bridge_commit"]
        return MappingProxyType({
            "transition_id": transition_id,
            "historical_activation_commit": historical_source_commit,
            "accepted_g07_implementation_commit": implementation,
            "independent_g07_acceptance_commit": acceptance,
            "authorization_identity_sha256": identity_hash,
        })
    except RunnerError:
        raise
    except Exception as exc:
        raise RunnerError(marker) from exc


def _state_source_commit_matches(
    state: Mapping[str, object], observed: object, current: str,
) -> bool:
    if observed == current:
        return True
    migration = state.get("resume_identity_migration")
    return bool(
        isinstance(migration, Mapping)
        and migration.get("status") == "PASS_MIGRATED"
        and migration.get("historical_source_commit") == observed
        and migration.get("current_source_commit") == current
    )


@dataclass(frozen=True)
class EvidenceProducerIdentity:
    """Read-only artifact provenance; never an execution or dispatch contract."""

    source_commit: str
    contract_sha256: str
    checkpoint_sha256: str


def _read_evidence_producer(
    project_root: Path, contract: g06.ExecutionContract, run_root: Path,
    artifact_path: Path, role: str,
) -> EvidenceProducerIdentity:
    """Bind saved evidence to its first immutable checkpoint, not reviewer HEAD."""
    fields = {
        "policy_receipt": "policy_receipt_sha256",
        "prediction_stage_receipt": "prediction_stage_receipt_sha256",
        "postprediction_receipt": "postprediction_receipt_sha256",
        "v2_execution_evidence_manifest": "v2_evidence_manifest_sha256",
        "rf_seed_evidence": "rf_seed_evidence_sha256",
    }
    if role not in {*fields, "prediction_issuance", "execution_manifest"}:
        raise RunnerError("G07_EVIDENCE_PRODUCER_ROLE")
    root, run_root = Path(project_root).resolve(), Path(run_root).resolve()
    _reopen_production_state(run_root, root)
    try:
        artifact_path.resolve().relative_to(run_root)
    except ValueError as exc:
        raise RunnerError("G07_EVIDENCE_PRODUCER_ARTIFACT") from exc
    if not artifact_path.is_file() or artifact_path.is_symlink():
        raise RunnerError("G07_EVIDENCE_PRODUCER_ARTIFACT")
    digest = sha256_file(artifact_path)
    anchors = []
    sources = set()
    source_sequence = []
    values = asdict(contract)
    values.pop("contract_sha256")
    for path in sorted((run_root / "checkpoints").glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))["payload"]
        source = body.get("source_commit")
        if not isinstance(source, str) or re.fullmatch(r"[0-9a-f]{40}", source) is None:
            raise RunnerError("G07_EVIDENCE_PRODUCER_SOURCE")
        expected_hash = sha256_bytes(g06.canonical_json({**values, "git_head": source}))
        if (body.get("identity", {}).get("contract_sha256") != expected_hash
                or body.get("identity", {}).get("unit_id") != _unit_id(contract)
                or body.get("identity", {}).get("run_id") != _v2_run_id(_unit_id(contract))):
            raise RunnerError("G07_EVIDENCE_PRODUCER_CONTRACT")
        sources.add(source)
        if not source_sequence or source_sequence[-1] != source:
            source_sequence.append(source)
        matches = (
            body.get(fields[role]) == digest if role in fields
            else body.get("current_phase") == (
                "PREDICTION_WRITTEN" if role == "prediction_issuance" else "COMPLETE"
            )
        )
        if matches:
            anchors.append((path, body))
    if not anchors:
        raise RunnerError("G07_EVIDENCE_PRODUCER_ANCHOR")
    path, body = anchors[0]
    source = body.get("source_commit")
    from src import paper1_g08_runtime as g08
    for producer in sorted(sources):
        g08.validate_evidence_producer_activation(root, producer)
    for prior, subsequent in zip(source_sequence, source_sequence[1:]):
        g08._require_ancestor(root, prior, subsequent, "G07_EVIDENCE_PRODUCER_CHRONOLOGY")
    values["git_head"] = source
    expected_hash = sha256_bytes(g06.canonical_json(values))
    if (body.get("identity", {}).get("contract_sha256") != expected_hash
            or body.get("identity", {}).get("unit_id") != _unit_id(contract)
            or body.get("identity", {}).get("run_id") != _v2_run_id(_unit_id(contract))):
        raise RunnerError("G07_EVIDENCE_PRODUCER_CONTRACT")
    return EvidenceProducerIdentity(str(source), expected_hash, sha256_file(path))


def _write_policy_receipt(
    context: _DispatchContext,
    state: dict[str, object],
    run_root: Path,
    *,
    tuning_receipt: TuningReceipt | None = None,
) -> Mapping[str, object]:
    policy = _governed_policy(context)
    inheritance = (
        _inheritance_authority(context, policy)
        if policy.mode is v2_policy.PolicyMode.INHERIT else None
    )
    selection_evidence = None
    if tuning_receipt is not None:
        selection_evidence = {
            "tuning_receipt_sha256": tuning_receipt.receipt_sha256,
            "selected_hyperparameter": tuning_receipt.selected_hyperparameter,
        }
    elif inheritance is not None:
        selection_evidence = dict(inheritance)
    elif policy.mode is v2_policy.PolicyMode.FIXED:
        selection_evidence = {
            "fixed_value": policy.fixed_value,
            "fixed_authority_sha256": policy.policy_sha256,
        }
    elif policy.mode in {v2_policy.PolicyMode.NO_TUNING, v2_policy.PolicyMode.NO_REFIT,
                         v2_policy.PolicyMode.NOT_APPLICABLE}:
        selection_evidence = {"selected_hyperparameter": None}
    payload = {
        "schema_version": "PAPER1_G07_V2_POLICY_RECEIPT_V1",
        "unit_id": context.plan_entry.unit_id,
        "contract_sha256": context.contract.contract_sha256,
        "policy": {**asdict(policy), "mode": policy.mode.value},
        "policy_sha256": policy.policy_sha256,
        "selection_evidence": selection_evidence,
        "selected_hyperparameter": state.get("selected_hyperparameter"),
        "hyperparameter_source": state.get("hyperparameter_source"),
    }
    path = run_root / "hyperparameter_policy_receipt.json"
    _write_or_validate_bytes(
        path, canonical_json(payload) + b"\n", "G07_V2_POLICY_RECEIPT_COLLISION"
    )
    state["policy_receipt_path"] = str(path)
    state["policy_receipt_sha256"] = sha256_file(path)
    return MappingProxyType(payload)


def _checkpoint_records(state: Mapping[str, object]) -> list[dict[str, object]]:
    return [dict(item) for item in state.get("checkpoint_records", [])]


def _persist_production_checkpoint(run_root: Path, state: dict[str, object], phase: str) -> None:
    from src.paper1_control_execution import active_operation
    if operation := active_operation(Path(state['validation_root'])):
        operation.bind_new_state(run_root, state)
    if phase not in PRODUCTION_PHASES:
        raise RunnerError("G07_PRODUCTION_PHASE")
    completed = list(state.get("completed_phases", []))
    phase_index = PRODUCTION_PHASES.index(phase)
    normal_transition = completed == list(PRODUCTION_PHASES[:phase_index])
    terminal_transition = phase == "TERMINAL_EVIDENCE_WRITTEN" and bool(completed) and completed[-1] not in {
        "TERMINAL_EVIDENCE_WRITTEN", "COMPLETE"
    }
    complete_transition = phase == "COMPLETE" and bool(completed) and completed[-1] == "TERMINAL_EVIDENCE_WRITTEN"
    if phase in completed or not (normal_transition or terminal_transition or complete_transition):
        raise RunnerError("G07_PRODUCTION_PHASE_TRANSITION")
    state["current_phase"] = phase
    state["completed_phases"] = completed + [phase]
    sequence = len(state["completed_phases"])
    prior = _checkpoint_records(state)
    payload = {key: value for key, value in state.items() if key != "checkpoint_records"}
    payload["resume_from_sequence"] = None if not prior else prior[-1]["sequence"]
    checkpoint_path = run_root / "checkpoints" / f"{sequence:02d}_{phase}.json"
    checkpoint_bytes = canonical_json({"payload": payload, "payload_sha256": sha256_bytes(canonical_json(payload))}) + b"\n"
    _write_once(checkpoint_path, checkpoint_bytes)
    record = {
        "path": checkpoint_path.relative_to(Path(state["validation_root"])).as_posix(),
        "sha256": sha256_file(checkpoint_path),
        "sequence": sequence,
        "resume_from_sequence": None if not prior else prior[-1]["sequence"],
    }
    state["checkpoint_records"] = prior + [record]
    pointer = {"path": record["path"], "sha256": record["sha256"]}
    _atomic_json(run_root / "checkpoint.current.json", pointer)
    if context_interrupt := state.get("interrupt_after"):
        if context_interrupt == phase:
            raise ControlledInterruption(f"G07_CONTROLLED_INTERRUPTION:{phase}")


def _reopen_production_state(run_root: Path, validation_root: Path) -> dict[str, object]:
    from src import paper1_control_reference as reference
    selected = reference.selected(validation_root)
    pointer_path = run_root / "checkpoint.current.json"
    if selected:
        selected.verify_file(pointer_path)
    if not pointer_path.is_file():
        raise RunnerError("G07_PRODUCTION_CHECKPOINT_MISSING")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    checkpoint_path = validation_root / pointer["path"]
    if not checkpoint_path.is_file() or sha256_file(checkpoint_path) != pointer["sha256"]:
        raise RunnerError("G07_PRODUCTION_CHECKPOINT_STALE")
    wrapper = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if sha256_bytes(canonical_json(wrapper["payload"])) != wrapper["payload_sha256"]:
        raise RunnerError("G07_PRODUCTION_CHECKPOINT_HASH")
    state = dict(wrapper["payload"])
    records = []
    prior_identity: object | None = None
    previous_identity: object | None = None
    prior_source: object | None = None
    migration_record: Mapping[str, object] | None = None
    for path in sorted((run_root / "checkpoints").glob("*.json")):
        if selected:
            selected.verify_file(path)
        sequence = int(path.name.split("_", 1)[0])
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        if set(checkpoint) != {"payload", "payload_sha256"}:
            raise RunnerError("G07_PRODUCTION_CHECKPOINT_SCHEMA")
        body = checkpoint["payload"]
        if sha256_bytes(canonical_json(body)) != checkpoint["payload_sha256"]:
            raise RunnerError("G07_PRODUCTION_CHECKPOINT_HASH")
        if body.get("current_phase") != path.stem.split("_", 1)[1]:
            raise RunnerError("G07_PRODUCTION_CHECKPOINT_PHASE")
        lineage = body.get("completed_phases")
        if (not isinstance(lineage, list) or len(lineage) != sequence or
                len(set(lineage)) != sequence or lineage[-1] != body.get("current_phase") or
                any(phase not in PRODUCTION_PHASES for phase in lineage) or
                any(PRODUCTION_PHASES.index(left) >= PRODUCTION_PHASES.index(right)
                    for left, right in zip(lineage, lineage[1:]))):
            raise RunnerError("G07_PRODUCTION_CHECKPOINT_PHASE_LINEAGE")
        expected_prior = None if sequence == 1 else sequence - 1
        if body.get("resume_from_sequence") != expected_prior:
            raise RunnerError("G07_PRODUCTION_CHECKPOINT_RESUME_LINEAGE")
        if prior_identity is None:
            if body.get("resume_identity_migration") is not None:
                raise RunnerError("G07_PRODUCTION_CHECKPOINT_IDENTITY_DRIFT")
            prior_identity = body.get("identity")
        elif body.get("identity") != prior_identity:
            next_migration = _validate_resume_identity_migration_structure(
                body.get("resume_identity_migration"),
                prior_identity,
                body.get("identity"),
            )
            if (next_migration.get("historical_source_commit") != prior_source
                    or next_migration.get("current_source_commit") != body.get("source_commit")):
                raise RunnerError("G07_PRODUCTION_CHECKPOINT_IDENTITY_DRIFT")
            expected_authority = _read_migration_authority(
                validation_root, next_migration["historical_source_commit"],
                next_migration["current_source_commit"],
            )
            if next_migration.get("authority_transition") != dict(expected_authority):
                raise RunnerError("G07_EVIDENCE_MIGRATION_AUTHORITY")
            migration_record = next_migration
            prior_identity = body.get("identity")
        elif migration_record is None and body.get("resume_identity_migration") is not None:
            raise RunnerError("G07_PRODUCTION_CHECKPOINT_IDENTITY_DRIFT")
        elif migration_record is not None:
            if body.get("resume_identity_migration") != migration_record:
                raise RunnerError("G07_PRODUCTION_CHECKPOINT_IDENTITY_DRIFT")
        if records and body.get("identity") == previous_identity and body.get("source_commit") != prior_source:
            raise RunnerError("G07_PRODUCTION_CHECKPOINT_IDENTITY_DRIFT")
        previous_identity = body.get("identity")
        prior_source = body.get("source_commit")
        records.append({
            "path": path.relative_to(validation_root).as_posix(), "sha256": sha256_file(path),
            "sequence": sequence, "resume_from_sequence": body["resume_from_sequence"],
        })
    state["checkpoint_records"] = records
    if [item["sequence"] for item in records] != list(range(1, len(records) + 1)):
        raise RunnerError("G07_PRODUCTION_CHECKPOINT_LINEAGE")
    if not records or pointer != {"path": records[-1]["path"], "sha256": records[-1]["sha256"]}:
        raise RunnerError("G07_PRODUCTION_CHECKPOINT_POINTER")
    from src.paper1_control_execution import active_operation
    if operation := active_operation(validation_root):
        operation.validate_new_state(run_root, state)
    return state


def _prediction_output(frame: pd.DataFrame, index: pd.Index, probabilities: np.ndarray) -> pd.DataFrame:
    if (not frame.index.is_unique or not index.is_unique or
            not index.isin(frame.index).all() or len(probabilities) != len(index)):
        raise RunnerError("G07_PREDICTION_ROW_IDENTITY")
    if frame.loc[index, list(g06.KEY_FIELDS)].duplicated().any():
        raise RunnerError("G07_PREDICTION_KEY_IDENTITY")
    output = frame.loc[index, [*g06.KEY_FIELDS, "interval_number"]].copy()
    output["predicted_probability"] = np.asarray(probabilities, dtype=float)
    return output.loc[:, list(g06.PREDICTION_INTEGRITY_COLUMNS)].sort_values(
        list(g06.KEY_FIELDS), kind="stable"
    ).reset_index(drop=True)


def _persist_prediction(path: Path, frame: pd.DataFrame) -> Mapping[str, object]:
    payload = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    _write_once(path, payload)
    return MappingProxyType({
        "path": "", "sha256": sha256_file(path), "schema": g06.PREDICTION_ARTIFACT_SCHEMA,
        "row_count": len(frame), "key_identity": _g06_4e_key_identity(frame),
        "required_columns": list(g06.PREDICTION_INTEGRITY_COLUMNS),
    })


def _write_or_validate_bytes(path: Path, payload: bytes, error: str) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise RunnerError(error)
        return
    _write_once(path, payload)


def _bound_artifact_record(validation_root: Path, path: Path, schema: str) -> Mapping[str, str]:
    root = validation_root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise RunnerError("G07_V2_ARTIFACT_OUTSIDE_VALIDATION_ROOT") from exc
    if not resolved.is_file():
        raise RunnerError("G07_V2_ARTIFACT_MISSING")
    return MappingProxyType({
        "path": relative.as_posix(), "sha256": sha256_file(resolved), "schema": schema,
    })


def _resolve_bound_artifact(
    validation_root: Path, record: Mapping[str, object], *, expected_schema: str,
) -> Path:
    if set(record) != {"path", "sha256", "schema"} or record.get("schema") != expected_schema:
        raise RunnerError("G07_V2_BOUND_ARTIFACT_RECORD")
    relative = Path(str(record["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise RunnerError("G07_V2_BOUND_ARTIFACT_PATH")
    root = validation_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RunnerError("G07_V2_BOUND_ARTIFACT_PATH") from exc
    if not path.is_file() or sha256_file(path) != record.get("sha256"):
        raise RunnerError("G07_V2_BOUND_ARTIFACT_HASH")
    return path


def _prediction_issuance_payload(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    prediction_path: Path,
    prediction: pd.DataFrame,
) -> Mapping[str, object]:
    """Bind issued prediction bytes into the pre-downstream checkpoint chain."""
    return MappingProxyType({
        "schema_version": "PAPER1_G07_V2_PREDICTION_ISSUANCE_V1",
        "run_id": context.request.run_id,
        "unit_id": context.plan_entry.unit_id,
        "contract_sha256": context.contract.contract_sha256,
        "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
        "input_identity": authenticated.source_manifest_sha256,
        "source_commit": state["source_commit"],
        "environment_configuration_sha256": state["identity"]["environment_configuration_sha256"],
        "prediction_artifact": dict(_bound_artifact_record(
            Path(authenticated.validation_root), prediction_path, g06.PREDICTION_ARTIFACT_SCHEMA
        )),
        "prediction_rows": len(prediction),
        "prediction_key_sha256": _g06_4e_key_identity(prediction),
    })


def _prediction_issuance_checkpoint_path(unit_root: Path) -> Path:
    sequence = PRODUCTION_PHASES.index("PREDICTION_WRITTEN") + 1
    return unit_root / "checkpoints" / f"{sequence:02d}_PREDICTION_WRITTEN.json"


def _reopen_prediction_issuance(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    contract: g06.ExecutionContract,
    unit_root: Path,
) -> tuple[
    Path, pd.DataFrame, Mapping[str, object], Mapping[str, object] | None,
]:
    """Authenticate prediction issuance from its earlier immutable checkpoint."""
    checkpoint_path = _prediction_issuance_checkpoint_path(unit_root)
    if not checkpoint_path.is_file():
        raise RunnerError("G07_V2_PREDICTION_ISSUANCE_CHECKPOINT_MISSING")
    wrapper = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if (set(wrapper) != {"payload", "payload_sha256"} or
            sha256_bytes(canonical_json(wrapper["payload"])) != wrapper["payload_sha256"]):
        raise RunnerError("G07_V2_PREDICTION_ISSUANCE_CHECKPOINT_HASH")
    checkpoint = wrapper["payload"]
    unit_id = _unit_id(contract)
    expected_run_id = _v2_run_id(unit_id)
    policy = v2_policy.resolve_policy(contract)
    plan_matches = [
        item for item in build_run_plan(context.project_root)
        if item.unit_id == unit_id
    ]
    if len(plan_matches) != 1:
        raise RunnerError("G07_V2_PREDICTION_ISSUANCE_PLAN")
    issuance_context = _DispatchContext(
        context.project_root,
        ProductionExecutionRequest(
            unit_id=unit_id,
            run_id=expected_run_id,
            output_root=Path(context.request.output_root),
            resume=True,
        ),
        plan_matches[0],
        contract,
        context.authorization_receipt,
        _DISPATCH_CAPABILITY,
    )
    expected_identity = _checkpoint_identity(issuance_context, authenticated)
    observed_identity = checkpoint.get("identity")
    migration = None
    if observed_identity != expected_identity:
        # This reopens evidence only. The active dispatch contract and its
        # independent current-authorization checks are not rebound or bypassed.
        producer = _read_evidence_producer(
            context.project_root, contract, unit_root, checkpoint_path,
            "prediction_issuance",
        )
        if (not isinstance(observed_identity, Mapping)
                or {k: v for k, v in observed_identity.items() if k != "contract_sha256"}
                != {k: v for k, v in expected_identity.items() if k != "contract_sha256"}):
            raise RunnerError("G07_V2_PREDICTION_ISSUANCE_BINDING")
        migration = MappingProxyType({
            "historical_contract_sha256": producer.contract_sha256,
            "historical_source_commit": producer.source_commit,
        })
    if (checkpoint.get("current_phase") != "PREDICTION_WRITTEN" or
            checkpoint.get("completed_phases") != list(PRODUCTION_PHASES[:6])):
        raise RunnerError("G07_V2_PREDICTION_ISSUANCE_CHECKPOINT_PHASE")
    issuance = checkpoint.get("prediction_issuance")
    if not isinstance(issuance, dict):
        raise RunnerError("G07_V2_PREDICTION_ISSUANCE_MISSING")
    expected_bindings = {
        "schema_version": "PAPER1_G07_V2_PREDICTION_ISSUANCE_V1",
        "run_id": expected_run_id,
        "unit_id": unit_id,
        "policy_sha256": policy.policy_sha256,
        "input_identity": expected_identity["input_identity"],
        "environment_configuration_sha256": expected_identity["environment_configuration_sha256"],
    }
    if (
        any(issuance.get(key) != value for key, value in expected_bindings.items())
        or issuance.get("contract_sha256")
        != (
            migration["historical_contract_sha256"]
            if migration is not None else contract.contract_sha256
        )
        or issuance.get("source_commit")
        != (
            migration["historical_source_commit"]
            if migration is not None else _git_head(context.project_root)
        )
    ):
        raise RunnerError("G07_V2_PREDICTION_ISSUANCE_BINDING")
    expected_path = (unit_root / "predictions.csv").resolve()
    expected_record = dict(_bound_artifact_record(
        Path(authenticated.validation_root), expected_path, g06.PREDICTION_ARTIFACT_SCHEMA
    ))
    if issuance.get("prediction_artifact") != expected_record:
        raise RunnerError("G07_V2_PREDICTION_ISSUANCE_ARTIFACT")
    prediction = pd.read_csv(expected_path)
    if (tuple(prediction.columns) != tuple(g06.PREDICTION_INTEGRITY_COLUMNS) or
            issuance.get("prediction_rows") != len(prediction) or
            issuance.get("prediction_key_sha256") != _g06_4e_key_identity(prediction)):
        raise RunnerError("G07_V2_PREDICTION_ISSUANCE_CONTENT")
    return expected_path, prediction, MappingProxyType(issuance), migration


def _prediction_stage_payload(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    prediction_path: Path,
    prediction: pd.DataFrame,
) -> Mapping[str, object]:
    payload = {
        "schema_version": PREDICTION_STAGE_SCHEMA_VERSION,
        "stage_status": "PREDICTION_VALIDATED_NOT_TERMINAL",
        "run_id": context.request.run_id,
        "unit_id": context.plan_entry.unit_id,
        "contract_sha256": context.contract.contract_sha256,
        "analysis_id": context.contract.analysis_id,
        "model_family": context.contract.model_family,
        "model_role": context.contract.model_role,
        "outer_evaluation": context.contract.evaluation_identity,
        "resolution_m": context.contract.resolution_m,
        "risk_set_id": context.contract.risk_set_id,
        "support_identity": context.contract.support_identity,
        "evidence_classification": authenticated.evidence_classification,
        "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
        "input_identity": authenticated.source_manifest_sha256,
        "source_commit": state["source_commit"],
        "environment_configuration_sha256": state["identity"]["environment_configuration_sha256"],
        "prediction_artifact": dict(_bound_artifact_record(
            Path(authenticated.validation_root), prediction_path, g06.PREDICTION_ARTIFACT_SCHEMA
        )),
        "prediction_rows": len(prediction),
        "prediction_key_sha256": _g06_4e_key_identity(prediction),
    }
    return MappingProxyType({
        **payload, "receipt_sha256": sha256_bytes(canonical_json(payload)),
    })


def _validate_prediction_stage_receipt(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    receipt_path: Path,
    expected_keys: pd.DataFrame,
) -> pd.DataFrame:
    if not receipt_path.is_file():
        raise RunnerError("G07_V2_PREDICTION_STAGE_RECEIPT_MISSING")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload = dict(receipt)
    observed = payload.pop("receipt_sha256", None)
    if observed != sha256_bytes(canonical_json(payload)):
        raise RunnerError("G07_V2_PREDICTION_STAGE_RECEIPT_HASH")
    expected_bindings = {
        "schema_version": PREDICTION_STAGE_SCHEMA_VERSION,
        "stage_status": "PREDICTION_VALIDATED_NOT_TERMINAL",
        "run_id": context.request.run_id,
        "unit_id": context.plan_entry.unit_id,
        "analysis_id": context.contract.analysis_id,
        "model_family": context.contract.model_family,
        "model_role": context.contract.model_role,
        "outer_evaluation": context.contract.evaluation_identity,
        "resolution_m": context.contract.resolution_m,
        "risk_set_id": context.contract.risk_set_id,
        "support_identity": context.contract.support_identity,
        "evidence_classification": authenticated.evidence_classification,
        "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
        "input_identity": authenticated.source_manifest_sha256,
        "environment_configuration_sha256": state["identity"]["environment_configuration_sha256"],
    }
    producer_hash = context.contract.contract_sha256
    producer_source = context.contract.git_head
    if payload.get("contract_sha256") != producer_hash:
        producer = _read_evidence_producer(
            context.project_root, context.contract, receipt_path.parent,
            receipt_path, "prediction_stage_receipt",
        )
        producer_hash, producer_source = producer.contract_sha256, producer.source_commit
    if (
        any(payload.get(key) != value for key, value in expected_bindings.items())
        or payload.get("contract_sha256") != producer_hash
        or payload.get("source_commit") != producer_source
    ):
        raise RunnerError("G07_V2_PREDICTION_STAGE_BINDING")
    issued_path, issued_prediction, issuance, _ = _reopen_prediction_issuance(
        context, authenticated, context.contract, receipt_path.parent
    )
    prediction_path = _resolve_bound_artifact(
        Path(authenticated.validation_root), payload.get("prediction_artifact", {}),
        expected_schema=g06.PREDICTION_ARTIFACT_SCHEMA,
    )
    if (prediction_path.resolve() != issued_path.resolve() or
            payload.get("prediction_artifact") != issuance.get("prediction_artifact")):
        raise RunnerError("G07_V2_PREDICTION_STAGE_ISSUANCE")
    prediction = pd.read_csv(prediction_path)
    if tuple(prediction.columns) != tuple(g06.PREDICTION_INTEGRITY_COLUMNS):
        raise RunnerError("G07_V2_PREDICTION_STAGE_SCHEMA")
    expected = expected_keys.loc[:, [*g06.KEY_FIELDS, "interval_number"]].sort_values(
        list(g06.KEY_FIELDS), kind="stable"
    ).reset_index(drop=True)
    observed_keys = prediction.loc[:, [*g06.KEY_FIELDS, "interval_number"]].sort_values(
        list(g06.KEY_FIELDS), kind="stable"
    ).reset_index(drop=True)
    if not observed_keys.equals(expected):
        raise RunnerError("G07_V2_PREDICTION_STAGE_KEYS")
    if (not prediction.equals(issued_prediction) or
            payload.get("prediction_rows") != len(prediction) or
            payload.get("prediction_key_sha256") != _g06_4e_key_identity(prediction)):
        raise RunnerError("G07_V2_PREDICTION_STAGE_IDENTITY")
    return prediction


def _write_prediction_stage_receipt(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: dict[str, object],
    run_root: Path,
    prediction_path: Path,
    prediction: pd.DataFrame,
) -> Path:
    receipt = _prediction_stage_payload(context, authenticated, state, prediction_path, prediction)
    path = run_root / "prediction_stage_receipt.json"
    _write_or_validate_bytes(
        path, canonical_json(dict(receipt)) + b"\n", "G07_V2_PREDICTION_STAGE_COLLISION"
    )
    state["prediction_stage_receipt_path"] = str(path)
    state["prediction_stage_receipt_sha256"] = sha256_file(path)
    return path


def _rf_seed_metric_values(
    metric_frame: pd.DataFrame,
    configuration: RunnerConfiguration = SCIENTIFIC_CONFIGURATION,
) -> Mapping[str, float | str]:
    payload = _metric_payload(metric_frame, configuration)
    records = payload["interval_records"]
    values: dict[str, float | str] = {
        "log_loss": float(payload["log_loss_equal_interval_mean"]),
        "brier": float(payload["brier_equal_interval_mean"]),
    }
    for source, target in (("average_precision", "average_precision"), ("roc_auc", "roc_auc")):
        observed = [record[source] for record in records]
        if all(value == "NOT_DEFINED" for value in observed):
            values[target] = "NOT_DEFINED"
        elif any(isinstance(value, str) for value in observed):
            raise RunnerError(f"G07_V2_RF_METRIC_MIXED_ELIGIBILITY:{source}")
        else:
            values[target] = float(np.mean([float(value) for value in observed]))
    return MappingProxyType(values)


def _persist_rf_seed_evidence(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: dict[str, object],
    run_root: Path,
    frame: pd.DataFrame,
    heldout_index: pd.Index,
    predictions: Mapping[int, np.ndarray],
) -> Mapping[str, object]:
    if tuple(sorted(predictions)) != v2_policy.RF_SEEDS:
        raise RunnerError("G07_V2_RF_SEED_SET")
    seed_records = []
    seed_metrics: dict[int, Mapping[str, float | str]] = {}
    configuration = _configuration_for(authenticated.evidence_classification)
    for seed in v2_policy.RF_SEEDS:
        output = _prediction_output(frame, heldout_index, predictions[seed])
        prediction_path = run_root / "rf_seed_evidence" / f"seed_{seed}_predictions.csv"
        prediction_bytes = output.to_csv(index=False, lineterminator="\n").encode("utf-8")
        _write_or_validate_bytes(prediction_path, prediction_bytes, "G07_V2_RF_SEED_PREDICTION_COLLISION")
        reopened_output = pd.read_csv(prediction_path)
        metric_frame = reopened_output.merge(
            frame.loc[heldout_index, [*g06.KEY_FIELDS, "y"]],
            on=list(g06.KEY_FIELDS), validate="one_to_one",
        ).rename(columns={"predicted_probability": "raw_probability_y1"})
        metrics = _rf_seed_metric_values(metric_frame, configuration)
        metrics_path = run_root / "rf_seed_evidence" / f"seed_{seed}_metrics.json"
        metric_payload = {
            "schema_version": RF_SEED_METRIC_SCHEMA_VERSION,
            "seed": seed,
            "run_id": context.request.run_id,
            "unit_id": context.plan_entry.unit_id,
            "contract_sha256": context.contract.contract_sha256,
            "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
            "input_identity": authenticated.source_manifest_sha256,
            "prediction_sha256": sha256_file(prediction_path),
            "prediction_key_sha256": _g06_4e_key_identity(reopened_output),
            "metrics": dict(metrics),
        }
        _write_or_validate_bytes(
            metrics_path, canonical_json(metric_payload) + b"\n",
            "G07_V2_RF_SEED_METRIC_COLLISION",
        )
        seed_metrics[seed] = metrics
        seed_records.append({
            "seed": seed,
            "prediction_path": prediction_path.relative_to(Path(authenticated.validation_root)).as_posix(),
            "prediction_sha256": sha256_file(prediction_path),
            "prediction_key_sha256": _g06_4e_key_identity(reopened_output),
            "metrics_path": metrics_path.relative_to(Path(authenticated.validation_root)).as_posix(),
            "metrics_sha256": sha256_file(metrics_path),
            "metrics": dict(metrics),
        })
    try:
        stability = dict(v2_policy.rf_seed_stability(seed_metrics))
    except v2_policy.PolicyError as exc:
        raise RunnerError(str(exc)) from exc
    payload = {
        "schema_version": "PAPER1_G07_V2_RF_SEED_EVIDENCE_V1",
        "unit_id": context.plan_entry.unit_id,
        "contract_sha256": context.contract.contract_sha256,
        "run_id": context.request.run_id,
        "analysis_id": context.contract.analysis_id,
        "model_family": context.contract.model_family,
        "model_role": context.contract.model_role,
        "outer_evaluation": context.contract.evaluation_identity,
        "resolution_m": context.contract.resolution_m,
        "risk_set_id": context.contract.risk_set_id,
        "support_identity": context.contract.support_identity,
        "evidence_classification": authenticated.evidence_classification,
        "source_commit": state["source_commit"],
        "environment_configuration_sha256": state["identity"]["environment_configuration_sha256"],
        "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
        "input_identity": authenticated.source_manifest_sha256,
        "selected_hyperparameter": state.get("selected_hyperparameter"),
        "seeds": list(v2_policy.RF_SEEDS),
        "principal_prediction_rule": "ARITHMETIC_MEAN_OF_FIVE_SEED_PROBABILITIES",
        "seed_records": seed_records,
        "stability": stability,
    }
    try:
        v2_policy.validate_rf_seed_evidence(payload)
    except v2_policy.PolicyError as exc:
        raise RunnerError(str(exc)) from exc
    path = run_root / "rf_seed_evidence" / "rf_seed_stability.json"
    _write_or_validate_bytes(path, canonical_json(payload) + b"\n", "G07_V2_RF_STABILITY_COLLISION")
    state["rf_seed_evidence_path"] = str(path)
    state["rf_seed_evidence_sha256"] = sha256_file(path)
    return MappingProxyType(payload)


def _validate_rf_seed_evidence_from_disk(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    run_root: Path,
    expected_keys: pd.DataFrame,
    principal_prediction_path: Path,
) -> Mapping[str, object]:
    evidence_path = run_root / "rf_seed_evidence" / "rf_seed_stability.json"
    if not evidence_path.is_file():
        raise RunnerError("G07_V2_RF_EVIDENCE_MISSING")
    if sha256_file(evidence_path) != state.get("rf_seed_evidence_sha256"):
        raise RunnerError("G07_V2_RF_EVIDENCE_HASH")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    producer_hash, producer_source = context.contract.contract_sha256, context.contract.git_head
    if evidence.get("contract_sha256") != producer_hash:
        producer = _read_evidence_producer(
            context.project_root, context.contract, run_root, evidence_path, "rf_seed_evidence"
        )
        producer_hash, producer_source = producer.contract_sha256, producer.source_commit
    expected_top = {
        "schema_version": "PAPER1_G07_V2_RF_SEED_EVIDENCE_V1",
        "unit_id": context.plan_entry.unit_id,
        "contract_sha256": producer_hash,
        "run_id": context.request.run_id,
        "analysis_id": context.contract.analysis_id,
        "model_family": context.contract.model_family,
        "model_role": context.contract.model_role,
        "outer_evaluation": context.contract.evaluation_identity,
        "resolution_m": context.contract.resolution_m,
        "risk_set_id": context.contract.risk_set_id,
        "support_identity": context.contract.support_identity,
        "evidence_classification": authenticated.evidence_classification,
        "source_commit": producer_source,
        "environment_configuration_sha256": state["identity"]["environment_configuration_sha256"],
        "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
        "input_identity": authenticated.source_manifest_sha256,
        "selected_hyperparameter": state.get("selected_hyperparameter"),
        "seeds": list(v2_policy.RF_SEEDS),
        "principal_prediction_rule": "ARITHMETIC_MEAN_OF_FIVE_SEED_PROBABILITIES",
    }
    if any(evidence.get(key) != value for key, value in expected_top.items()):
        raise RunnerError("G07_V2_RF_EVIDENCE_BINDING")
    records = evidence.get("seed_records")
    if not isinstance(records, list) or tuple(item.get("seed") for item in records) != v2_policy.RF_SEEDS:
        raise RunnerError("G07_V2_RF_SEED_RECORD_SET")
    root = Path(authenticated.validation_root).resolve()
    expected = expected_keys.loc[:, [*g06.KEY_FIELDS, "interval_number"]].sort_values(
        list(g06.KEY_FIELDS), kind="stable"
    ).reset_index(drop=True)
    outcome = authenticated.frame.loc[
        authenticated.frame.interval_number.isin(context.contract.heldout_intervals),
        [*g06.KEY_FIELDS, "y"],
    ]
    seed_metrics: dict[int, Mapping[str, float | str]] = {}
    seed_probabilities = []
    configuration = _configuration_for(authenticated.evidence_classification)
    for record, seed in zip(records, v2_policy.RF_SEEDS):
        if set(record) != {
            "seed", "prediction_path", "prediction_sha256", "prediction_key_sha256",
            "metrics_path", "metrics_sha256", "metrics",
        } or record["seed"] != seed:
            raise RunnerError("G07_V2_RF_SEED_RECORD_SCHEMA")
        expected_prediction_path = (
            run_root / "rf_seed_evidence" / f"seed_{seed}_predictions.csv"
        ).resolve()
        expected_metrics_path = (
            run_root / "rf_seed_evidence" / f"seed_{seed}_metrics.json"
        ).resolve()
        expected_prediction_relative = expected_prediction_path.relative_to(root).as_posix()
        expected_metrics_relative = expected_metrics_path.relative_to(root).as_posix()
        if (record["prediction_path"] != expected_prediction_relative or
                record["metrics_path"] != expected_metrics_relative):
            raise RunnerError("G07_V2_RF_SEED_GOVERNED_PATH")
        prediction_path = _resolve_bound_artifact(root, {
            "path": record["prediction_path"], "sha256": record["prediction_sha256"],
            "schema": g06.PREDICTION_ARTIFACT_SCHEMA,
        }, expected_schema=g06.PREDICTION_ARTIFACT_SCHEMA)
        if prediction_path.resolve() != expected_prediction_path:
            raise RunnerError("G07_V2_RF_SEED_GOVERNED_PATH")
        prediction = pd.read_csv(prediction_path)
        if tuple(prediction.columns) != tuple(g06.PREDICTION_INTEGRITY_COLUMNS):
            raise RunnerError("G07_V2_RF_SEED_PREDICTION_SCHEMA")
        keys = prediction.loc[:, [*g06.KEY_FIELDS, "interval_number"]].sort_values(
            list(g06.KEY_FIELDS), kind="stable"
        ).reset_index(drop=True)
        if (not keys.equals(expected) or
                record["prediction_key_sha256"] != _g06_4e_key_identity(prediction)):
            raise RunnerError("G07_V2_RF_SEED_PREDICTION_KEYS")
        metrics_path = _resolve_bound_artifact(root, {
            "path": record["metrics_path"], "sha256": record["metrics_sha256"],
            "schema": RF_SEED_METRIC_SCHEMA_VERSION,
        }, expected_schema=RF_SEED_METRIC_SCHEMA_VERSION)
        if metrics_path.resolve() != expected_metrics_path:
            raise RunnerError("G07_V2_RF_SEED_GOVERNED_PATH")
        metric_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        expected_metric_binding = {
            "schema_version": RF_SEED_METRIC_SCHEMA_VERSION,
            "seed": seed,
            "run_id": context.request.run_id,
            "unit_id": context.plan_entry.unit_id,
            "contract_sha256": producer_hash,
            "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
            "input_identity": authenticated.source_manifest_sha256,
            "prediction_sha256": record["prediction_sha256"],
            "prediction_key_sha256": record["prediction_key_sha256"],
        }
        if any(metric_payload.get(key) != value for key, value in expected_metric_binding.items()):
            raise RunnerError("G07_V2_RF_SEED_METRIC_BINDING")
        metric_frame = prediction.merge(outcome, on=list(g06.KEY_FIELDS), validate="one_to_one").rename(
            columns={"predicted_probability": "raw_probability_y1"}
        )
        reconstructed_metrics = dict(_rf_seed_metric_values(metric_frame, configuration))
        if (metric_payload.get("metrics") != reconstructed_metrics or
                record.get("metrics") != reconstructed_metrics):
            raise RunnerError("G07_V2_RF_SEED_METRIC_RECONSTRUCTION")
        seed_metrics[seed] = reconstructed_metrics
        seed_probabilities.append(prediction["predicted_probability"].to_numpy(dtype=float))
    try:
        stability = dict(v2_policy.rf_seed_stability(seed_metrics))
        v2_policy.validate_rf_seed_evidence(evidence)
    except v2_policy.PolicyError as exc:
        raise RunnerError(str(exc)) from exc
    if json.loads(canonical_json(evidence.get("stability"))) != json.loads(canonical_json(stability)):
        raise RunnerError("G07_V2_RF_STABILITY_RECONSTRUCTION")
    principal = pd.read_csv(principal_prediction_path)
    if tuple(principal.columns) != tuple(g06.PREDICTION_INTEGRITY_COLUMNS):
        raise RunnerError("G07_V2_RF_PRINCIPAL_SCHEMA")
    if not principal.loc[:, [*g06.KEY_FIELDS, "interval_number"]].sort_values(
        list(g06.KEY_FIELDS), kind="stable"
    ).reset_index(drop=True).equals(expected):
        raise RunnerError("G07_V2_RF_PRINCIPAL_KEYS")
    reconstructed_probability = np.mean(np.vstack(seed_probabilities), axis=0)
    serialized_reconstruction = principal.copy()
    serialized_reconstruction["predicted_probability"] = reconstructed_probability
    serialized_reconstruction = pd.read_csv(StringIO(
        serialized_reconstruction.to_csv(index=False, lineterminator="\n")
    ))
    if not np.array_equal(
        principal["predicted_probability"].to_numpy(dtype=float),
        serialized_reconstruction["predicted_probability"].to_numpy(dtype=float),
    ):
        raise RunnerError("G07_V2_RF_PRINCIPAL_AVERAGE")
    return MappingProxyType(evidence)


def _reopened_prediction_record(path: Path) -> Mapping[str, object]:
    frame = pd.read_csv(path)
    if tuple(frame.columns) != tuple(g06.PREDICTION_INTEGRITY_COLUMNS):
        raise RunnerError("G07_REOPENED_PREDICTION_SCHEMA")
    return MappingProxyType({
        "path": "", "sha256": sha256_file(path), "schema": g06.PREDICTION_ARTIFACT_SCHEMA,
        "row_count": len(frame), "key_identity": _g06_4e_key_identity(frame),
        "required_columns": list(g06.PREDICTION_INTEGRITY_COLUMNS),
    })


def _write_manifest(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    path: Path,
    *,
    terminal_status: str,
    output: Mapping[str, object] | None,
    exception_metadata: Mapping[str, object] | None = None,
) -> Path:
    validation_root = Path(authenticated.validation_root)
    output_record = None if output is None else dict(output)
    if output_record is not None:
        output_record["path"] = Path(state["prediction_path"]).relative_to(validation_root).as_posix()
    selected = state.get("selected_hyperparameter")
    hyperparameters = {} if selected is None else {"selected_hyperparameter": selected}
    record = _execution_manifest_record(
        contract=context.contract, run_id=context.request.run_id,
        source_commit=str(state["source_commit"]), classification=authenticated.evidence_classification,
        input_artifacts=authenticated.input_artifacts, output=output_record,
        checkpoints=_checkpoint_records(state), terminal_status=terminal_status,
        exception_metadata=exception_metadata, hyperparameters=hyperparameters,
        hyperparameter_state={"source": state.get("hyperparameter_source", "NOT_APPLICABLE")},
        start_timestamp=str(state["start_timestamp"]), end_timestamp=str(state["end_timestamp"]),
    )
    _write_once(path, canonical_json(record) + b"\n")
    g06.validate_execution_manifest(validation_root, path, True)
    return path


def _benchmark_checkpoint(
    validation_root: Path,
    benchmark_root: Path,
    identity: Mapping[str, object],
    phase: str,
    sequence: int,
    resume_from_sequence: int | None,
) -> Mapping[str, object]:
    payload = {
        "schema_version": "PAPER1_G07_BENCHMARK_CHECKPOINT_V1",
        "sequence": sequence,
        "resume_from_sequence": resume_from_sequence,
        "phase": phase,
        "identity": dict(identity),
    }
    path = benchmark_root / "checkpoints" / f"{sequence:02d}_{phase}.json"
    _write_once(path, canonical_json(payload) + b"\n")
    return MappingProxyType({
        "path": path.relative_to(validation_root).as_posix(),
        "sha256": sha256_file(path),
        "sequence": sequence,
        "resume_from_sequence": resume_from_sequence,
    })


def _governed_benchmark_authority(
    context: _DispatchContext, benchmark_type: str,
) -> g06_4f.BenchmarkContract:
    authority = g06_4f.governed_scoped_benchmark_contract(
        context.project_root,
        benchmark_type=benchmark_type,
        analysis_id=context.contract.analysis_id,
        risk_set_id=context.contract.risk_set_id,
        resolution_m=context.contract.resolution_m,
        evaluation_identity=context.contract.evaluation_identity,
    )
    g06_4f.validate_governed_scoped_benchmark_contract(
        context.project_root,
        authority,
        benchmark_type=benchmark_type,
        analysis_id=context.contract.analysis_id,
        risk_set_id=context.contract.risk_set_id,
        resolution_m=context.contract.resolution_m,
        evaluation_identity=context.contract.evaluation_identity,
    )
    return authority


def _binding_from_benchmark_contract(
    authority: g06_4f.BenchmarkContract,
) -> _GovernedBenchmarkBinding:
    return _GovernedBenchmarkBinding(
        authority.contract_sha256,
        authority.benchmark_id,
        authority.benchmark_type,
        authority.model_family,
        authority.model_role,
        authority.evaluation_identity,
        tuple(authority.training_intervals),
        tuple(authority.heldout_intervals),
    )


def _governed_geometry_binding(context: _DispatchContext) -> _GovernedBenchmarkBinding:
    return _binding_from_benchmark_contract(
        _governed_benchmark_authority(context, "GEOMETRY_LOGISTIC")
    )


def _governed_prevalence_binding(context: _DispatchContext) -> _GovernedBenchmarkBinding:
    return _binding_from_benchmark_contract(
        _governed_benchmark_authority(context, "TRAINING_PREVALENCE")
    )


def _prevalence_outcome_set(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    benchmark_root: Path,
):
    if authenticated.evidence_classification == RunnerMode.SCIENTIFIC.value:
        artifact = g06.authenticate_outcome_for_contract(
            context.project_root, context.contract
        )
        outcomes = g06.outcome_set_from_authenticated_artifact(artifact)
    elif authenticated.evidence_classification == RunnerMode.SYNTHETIC.value:
        matches = [
            dict(item) for item in authenticated.input_artifacts
            if item["schema"] == g06.OUTCOME_INPUT_SCHEMA
        ]
        if len(matches) != 1:
            raise RunnerError("G07_PREVALENCE_OUTCOME_INPUT")
        validation_root = Path(authenticated.validation_root)
        source_path = validation_root / str(matches[0]["path"])
        frame = pd.read_csv(source_path)
        authority_path = benchmark_root / "synthetic_outcome_authority.json"
        authority = {
            "schema_version": g06_4e.SYNTHETIC_OUTCOME_AUTHORITY_SCHEMA,
            "evidence_classification": RunnerMode.SYNTHETIC.value,
            "risk_set_id": context.contract.risk_set_id,
            "resolution_m": context.contract.resolution_m,
            "response_field": "y",
            "source_path": source_path.relative_to(validation_root).as_posix(),
            "source_sha256": sha256_file(source_path),
            "columns": list(frame.columns),
            "row_count": len(frame),
            "key_identity": _g06_4e_key_identity(frame),
            "key_interval_value_identity": _g06_4e_key_identity(frame, include_y=True),
        }
        _write_once(authority_path, canonical_json(authority) + b"\n")
        outcomes = g06_4e._synthetic_outcome_set(validation_root, authority_path)
    else:
        raise RunnerError("G07_PREVALENCE_CLASSIFICATION")
    if (outcomes.evidence_classification != authenticated.evidence_classification or
            outcomes.risk_set_id != context.contract.risk_set_id or
            outcomes.resolution_m != context.contract.resolution_m):
        raise RunnerError("G07_PREVALENCE_OUTCOME_BINDING")
    return outcomes


def _persist_governed_benchmark_evidence(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: dict[str, object],
    frame: pd.DataFrame,
    training_index: pd.Index,
    heldout_index: pd.Index,
    benchmark_type: str,
) -> Mapping[str, object]:
    if benchmark_type == "GEOMETRY_LOGISTIC":
        benchmark = _governed_geometry_binding(context)
    elif benchmark_type == "TRAINING_PREVALENCE":
        benchmark = _governed_prevalence_binding(context)
    else:
        raise RunnerError("G07_BENCHMARK_TYPE")
    if (benchmark.training_intervals != tuple(context.contract.training_intervals) or
            benchmark.heldout_intervals != tuple(context.contract.heldout_intervals)):
        raise RunnerError("G07_BENCHMARK_HISTORY_BINDING")
    validation_root = Path(authenticated.validation_root)
    benchmark_root = Path(state["run_root"]) / "benchmarks" / benchmark_type.lower()
    if benchmark_type == "GEOMETRY_LOGISTIC":
        selected_c = float(state["selected_hyperparameter"])
        governed_geometry = _governed_benchmark_authority(
            context, "GEOMETRY_LOGISTIC")
        g06_4f.validate_governed_geometry_selected_c(
            context.project_root,
            governed_geometry,
            analysis_id=context.contract.analysis_id,
            selected_c=selected_c,
        )
        design, _ = _geometry_design(frame, training_index)
        x_train, y_train = _aligned_model_rows(
            frame, design, training_index, "BENCHMARK_TRAINING"
        )
        x_heldout, _ = _aligned_model_rows(
            frame, design, heldout_index, "BENCHMARK_HELDOUT"
        )
        probabilities = _fit_probabilities(
            _configuration_for(authenticated.evidence_classification),
            "L2_LOGISTIC", x_train, y_train,
            x_heldout, selected_c, PRIMARY_SEED,
        )
        state["model_fit_count"] += 1
        hyperparameters: Mapping[str, object] = {
            "selected_c": selected_c,
            "selected_c_source_role": g06.GEOMETRY_C_SOURCE_ROLE,
            "retuning_count": 0,
        }
        evidence_requirement = "G07E_GEOMETRY"
    elif benchmark_type == "TRAINING_PREVALENCE":
        outcomes = _prevalence_outcome_set(context, authenticated, benchmark_root)
        governed_prevalence = _governed_benchmark_authority(
            context, "TRAINING_PREVALENCE")
        reconstruction = g06_4f.reconstruct_scoped_training_prevalence(
            context.project_root,
            outcomes,
            governed_prevalence,
            analysis_id=context.contract.analysis_id,
            expected_source_identity=outcomes.source_identity,
        )
        g06.validate_prevalence_claim(
            reconstruction,
            training_rows=reconstruction.training_rows,
            training_positive=reconstruction.training_positive,
            probability=reconstruction.probability,
        )
        if (reconstruction.training_history != benchmark.training_intervals or
                reconstruction.heldout_history != benchmark.heldout_intervals):
            raise RunnerError("G07_PREVALENCE_HISTORY_BINDING")
        training_rows = reconstruction.training_rows
        training_positive = reconstruction.training_positive
        probability = reconstruction.probability
        probabilities = np.full(len(heldout_index), probability, dtype=float)
        hyperparameters = {
            "training_rows": training_rows,
            "training_positive": training_positive,
            "probability": probability,
            "heldout_label_use": "PROHIBITED",
            "outcome_source_identity": outcomes.source_identity,
            "outcome_key_identity": outcomes.canonical_key_interval_value_sha256,
        }
        evidence_requirement = "G07E_PREVALENCE"
    prediction_path = benchmark_root / "predictions.csv"
    output = _prediction_output(frame, heldout_index, probabilities)
    output_record = dict(_persist_prediction(prediction_path, output))
    compatibility_name = (
        "benchmark_geometry.csv" if benchmark_type == "GEOMETRY_LOGISTIC"
        else "benchmark_prevalence.csv"
    )
    _write_once(Path(state["run_root"]) / compatibility_name, prediction_path.read_bytes())
    output_record["path"] = prediction_path.relative_to(validation_root).as_posix()
    identity = {
        "benchmark_contract_sha256": benchmark.contract_sha256,
        "benchmark_id": benchmark.benchmark_id,
        "benchmark_type": benchmark.benchmark_type,
        "evaluation_identity": benchmark.evaluation_identity,
        "classification": authenticated.evidence_classification,
        "source_input_identity": authenticated.source_manifest_sha256,
        "heldout_key_identity": _g06_4e_key_identity(output),
        "configuration_identity": sha256_bytes(canonical_json(dict(hyperparameters))),
    }
    checkpoints: list[Mapping[str, object]] = []
    if benchmark_type == "GEOMETRY_LOGISTIC":
        for sequence, phase in enumerate(("INPUTS_VALIDATED", "PREDICTION_WRITTEN"), start=1):
            checkpoints.append(_benchmark_checkpoint(
                validation_root, benchmark_root, identity, phase, sequence,
                None if sequence == 1 else sequence - 1,
            ))
    terminal = {
        "schema_version": "PAPER1_G07_BENCHMARK_TERMINAL_V1",
        "disposition": "COMPLETE",
        "evidence_requirement": evidence_requirement,
        "benchmark_contract_sha256": benchmark.contract_sha256,
        "prediction_sha256": output_record["sha256"],
        "model_fit_count": 1 if benchmark_type == "GEOMETRY_LOGISTIC" else 0,
        "retuning_count": 0,
    }
    terminal_path = benchmark_root / "terminal_evidence.json"
    _write_once(terminal_path, canonical_json(terminal) + b"\n")
    if benchmark_type == "GEOMETRY_LOGISTIC":
        for sequence, phase in enumerate(("TERMINAL_EVIDENCE_WRITTEN", "COMPLETE"), start=3):
            checkpoints.append(_benchmark_checkpoint(
                validation_root, benchmark_root, identity, phase, sequence,
                sequence - 1,
            ))
    start = str(state["start_timestamp"])
    manifest = _execution_manifest_record(
        contract=benchmark, run_id=f"{context.request.run_id}:{benchmark.benchmark_id}",
        source_commit=str(state["source_commit"]),
        classification=authenticated.evidence_classification,
        input_artifacts=authenticated.input_artifacts, output=output_record,
        checkpoints=checkpoints, terminal_status="COMPLETE", exception_metadata=None,
        hyperparameters=hyperparameters,
        hyperparameter_state={"source": "GOVERNED_BENCHMARK_CONTRACT"},
        start_timestamp=start, end_timestamp=str(state["end_timestamp"]),
    )
    manifest_path = benchmark_root / "execution_manifest.json"
    _write_once(manifest_path, canonical_json(manifest) + b"\n")
    expected_keys = frame.loc[heldout_index, [*g06.KEY_FIELDS, "interval_number"]]
    integrity = g06.integrity_validate_prediction_artifact(
        validation_root, manifest_path,
        expected_contract_id=benchmark.contract_sha256,
        expected_analysis_id=benchmark.benchmark_id,
        expected_model_family=benchmark.model_family,
        expected_model_role=benchmark.model_role,
        expected_outer_evaluation=benchmark.evaluation_identity,
        expected_evidence_classification=authenticated.evidence_classification,
        expected_heldout_keys=expected_keys,
    )
    evidence = {
        "schema_version": "PAPER1_G07_BENCHMARK_EVIDENCE_V1",
        "evidence_requirement": evidence_requirement,
        "benchmark_contract_sha256": benchmark.contract_sha256,
        "execution_manifest_path": manifest_path.relative_to(validation_root).as_posix(),
        "execution_manifest_sha256": sha256_file(manifest_path),
        "prediction_artifact_sha256": integrity.artifact_sha256,
        "terminal_path": terminal_path.relative_to(validation_root).as_posix(),
        "terminal_sha256": sha256_file(terminal_path),
        "checkpoint_aggregate_sha256": (
            sha256_bytes(canonical_json([dict(item) for item in checkpoints]))
            if checkpoints else None
        ),
        "heldout_key_identity": integrity.canonical_key_sha256,
        "details": dict(hyperparameters),
    }
    evidence_path = benchmark_root / "evidence_record.json"
    _write_once(evidence_path, canonical_json(evidence) + b"\n")
    return MappingProxyType({
        "manifest_path": str(manifest_path),
        "evidence_path": str(evidence_path),
        "prediction_path": str(prediction_path),
    })


def _reconcile_governed_benchmark_evidence(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    frame: pd.DataFrame,
    heldout_index: pd.Index,
    benchmark_type: str,
) -> None:
    if benchmark_type == "GEOMETRY_LOGISTIC":
        benchmark = _governed_geometry_binding(context)
    elif benchmark_type == "TRAINING_PREVALENCE":
        benchmark = _governed_prevalence_binding(context)
    else:
        raise RunnerError("G07_BENCHMARK_TYPE")
    benchmark_root = Path(str(state["run_root"])) / "benchmarks" / benchmark_type.lower()
    manifest_path = benchmark_root / "execution_manifest.json"
    evidence_path = benchmark_root / "evidence_record.json"
    terminal_path = benchmark_root / "terminal_evidence.json"
    if not all(path.is_file() for path in (manifest_path, evidence_path, terminal_path)):
        raise RunnerError("G07_BENCHMARK_EVIDENCE_MISSING")
    expected_keys = frame.loc[heldout_index, [*g06.KEY_FIELDS, "interval_number"]]
    integrity = g06.integrity_validate_prediction_artifact(
        Path(authenticated.validation_root), manifest_path,
        expected_contract_id=benchmark.contract_sha256,
        expected_analysis_id=benchmark.benchmark_id,
        expected_model_family=benchmark.model_family,
        expected_model_role=benchmark.model_role,
        expected_outer_evaluation=benchmark.evaluation_identity,
        expected_evidence_classification=authenticated.evidence_classification,
        expected_heldout_keys=expected_keys,
    )
    manifest = g06.validate_execution_manifest(
        Path(authenticated.validation_root), manifest_path, True
    ).record
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    checkpoints = [dict(item) for item in manifest["checkpoints"]]
    expected_checkpoint_aggregate = (
        sha256_bytes(canonical_json(checkpoints)) if checkpoints else None
    )
    if (evidence.get("benchmark_contract_sha256") != benchmark.contract_sha256 or
            evidence.get("execution_manifest_sha256") != sha256_file(manifest_path) or
            evidence.get("prediction_artifact_sha256") != integrity.artifact_sha256 or
            evidence.get("terminal_sha256") != sha256_file(terminal_path) or
            evidence.get("checkpoint_aggregate_sha256") != expected_checkpoint_aggregate or
            evidence.get("heldout_key_identity") != integrity.canonical_key_sha256):
        raise RunnerError("G07_BENCHMARK_EVIDENCE_RECONCILIATION")
    if ((benchmark_type == "GEOMETRY_LOGISTIC" and len(checkpoints) != 4) or
            (benchmark_type == "TRAINING_PREVALENCE" and checkpoints)):
        raise RunnerError("G07_BENCHMARK_CHECKPOINT_POLICY")
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    expected_fit_count = 1 if benchmark_type == "GEOMETRY_LOGISTIC" else 0
    if (terminal.get("disposition") != "COMPLETE" or
            terminal.get("model_fit_count") != expected_fit_count or
            terminal.get("retuning_count") != 0 or
            terminal.get("prediction_sha256") != integrity.artifact_sha256):
        raise RunnerError("G07_BENCHMARK_TERMINAL_RECONCILIATION")
    details = evidence.get("details")
    if not isinstance(details, dict):
        raise RunnerError("G07_BENCHMARK_DETAILS")
    if benchmark_type == "GEOMETRY_LOGISTIC":
        if (details.get("retuning_count") != 0 or
                float(details.get("selected_c", float("nan"))) !=
                float(state["selected_hyperparameter"])):
            raise RunnerError("G07_GEOMETRY_DETAILS")
    else:
        outcomes = _prevalence_outcome_set(context, authenticated, benchmark_root)
        governed_prevalence = _governed_benchmark_authority(
            context, "TRAINING_PREVALENCE")
        reconstruction = g06_4f.reconstruct_scoped_training_prevalence(
            context.project_root,
            outcomes,
            governed_prevalence,
            analysis_id=context.contract.analysis_id,
            expected_source_identity=outcomes.source_identity,
        )
        g06.validate_prevalence_claim(
            reconstruction,
            training_rows=int(details.get("training_rows", -1)),
            training_positive=int(details.get("training_positive", -1)),
            probability=float(details.get("probability", float("nan"))),
        )
        if (details.get("heldout_label_use") != "PROHIBITED" or
                details.get("outcome_source_identity") != outcomes.source_identity or
                details.get("outcome_key_identity") !=
                outcomes.canonical_key_interval_value_sha256):
            raise RunnerError("G07_PREVALENCE_DETAILS")


def _reconcile_completed_production_run(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
) -> None:
    if state.get("current_phase") != "COMPLETE":
        raise RunnerError("G07_COMPLETED_RESUME_STATE")
    expected_identity = _checkpoint_identity(context, authenticated)
    if state.get("identity") != expected_identity:
        raise RunnerError("G07_COMPLETED_RESUME_IDENTITY")
    contract = context.contract
    frame = authenticated.frame
    heldout_index = frame.index[frame.interval_number.isin(contract.heldout_intervals)]
    expected_keys = frame.loc[heldout_index, [*g06.KEY_FIELDS, "interval_number"]]
    run_root = Path(str(state["run_root"]))
    validation_root = Path(authenticated.validation_root)
    manifest_path = run_root / "execution_manifest.json"
    prediction_stage_receipt = run_root / "prediction_stage_receipt.json"
    terminal_path = run_root / "terminal_evidence.json"
    metrics_path = run_root / "metrics.json"
    disposition = str(state.get("terminal_disposition"))
    if disposition != TerminalDisposition.COMPLETE.value:
        if tuple(state.get("completed_phases", ())) != (
            "INITIALIZED", "INPUTS_VALIDATED", "TERMINAL_EVIDENCE_WRITTEN", "COMPLETE"
        ):
            raise RunnerError("G07_COMPLETED_RESUME_NONEXECUTION_STATE")
        manifest = g06.validate_execution_manifest(validation_root, manifest_path, True).record
        expected_terminal = {
            TerminalDisposition.ENVIRONMENT_BLOCKED.value: "ENVIRONMENT_BLOCKED",
            TerminalDisposition.NONESTIMABLE.value: "GOVERNED_NONESTIMABLE",
            TerminalDisposition.DISABLED.value: "MACHINE_DISABLED_NONEXECUTING",
            TerminalDisposition.FAILED_RUNTIME.value: "FAILED_RUNTIME",
        }.get(disposition)
        if (expected_terminal is None or manifest["terminal_status"] != expected_terminal or
                manifest["execution_contract_id"] != contract.contract_sha256 or
                manifest["analysis_id"] != contract.analysis_id or
                manifest["model_family"] != contract.model_family or
                manifest["model_role"] != contract.model_role or
                manifest["outer_evaluation"] != contract.evaluation_identity or
                manifest["evidence_classification"] != authenticated.evidence_classification):
            raise RunnerError("G07_COMPLETED_RESUME_NONEXECUTION_BINDING")
        return
    if tuple(state.get("completed_phases", ())) != PRODUCTION_PHASES:
        raise RunnerError("G07_COMPLETED_RESUME_STATE")
    try:
        v2_policy.validate_checkpoint_policy(
            state.get("identity", {}), v2_policy.resolve_policy(contract)
        )
    except v2_policy.PolicyError as exc:
        raise RunnerError(str(exc)) from exc
    if not all(path.is_file() for path in (
        manifest_path, prediction_stage_receipt, terminal_path, metrics_path,
        run_root / "hyperparameter_policy_receipt.json",
        run_root / "postprediction_unit_receipt.json",
        run_root / "paired_publication_status.json",
        run_root / "v2_execution_evidence_manifest.json",
        run_root / "v2_publication_gate.json",
    )):
        raise RunnerError("G07_COMPLETED_RESUME_ARTIFACT_MISSING")
    final_manifest = g06.validate_execution_manifest(validation_root, manifest_path, True)
    record = final_manifest.record
    manifest_contract = contract.contract_sha256
    if record.get("execution_contract_id") != manifest_contract:
        producer = _read_evidence_producer(
            context.project_root, contract, run_root, manifest_path, "execution_manifest"
        )
        if (record.get("runner_source_commit") != producer.source_commit
                or record.get("scientific_run_git_commit") != producer.source_commit):
            raise RunnerError("G07_COMPLETED_RESUME_MANIFEST_PRODUCER")
        manifest_contract = producer.contract_sha256
    expected_bindings = {
        "paper1_run_id": context.request.run_id,
        "execution_contract_id": manifest_contract,
        "analysis_id": contract.analysis_id,
        "model_family": contract.model_family,
        "model_role": contract.model_role,
        "outer_evaluation": contract.evaluation_identity,
        "evidence_classification": authenticated.evidence_classification,
        "terminal_status": "COMPLETE",
    }
    if any(record.get(key) != value for key, value in expected_bindings.items()):
        raise RunnerError("G07_COMPLETED_RESUME_MANIFEST_BINDING")
    if ([dict(item) for item in authenticated.input_artifacts] != record["input_artifacts"] or
            tuple(record["training_history"]) != tuple(contract.training_intervals) or
            tuple(record["heldout_history"]) != tuple(contract.heldout_intervals)):
        raise RunnerError("G07_COMPLETED_RESUME_INPUT_OR_HISTORY")
    selected = state.get("selected_hyperparameter")
    expected_hyperparameters = (
        {} if contract.model_family == "FRACTIONAL_LOGIT_GLM"
        else {"selected_hyperparameter": selected}
    )
    if record["hyperparameters"] != expected_hyperparameters:
        raise RunnerError("G07_COMPLETED_RESUME_CONFIGURATION")
    source = state.get("hyperparameter_source")
    policy = v2_policy.resolve_policy(contract)
    policy_receipt_path = run_root / "hyperparameter_policy_receipt.json"
    policy_receipt = json.loads(policy_receipt_path.read_text(encoding="utf-8"))
    if (sha256_file(policy_receipt_path) != state.get("policy_receipt_sha256") or
            policy_receipt.get("policy_sha256") != policy.policy_sha256 or
            policy_receipt.get("selected_hyperparameter") != selected):
        raise RunnerError("G07_V2_POLICY_RECEIPT_RECONCILIATION")
    if source == "GOVERNED_OUTER_TUNING":
        tuning_path = run_root / "tuning_receipt.json"
        if not tuning_path.is_file():
            raise RunnerError("G07_COMPLETED_RESUME_TUNING_RECEIPT")
        tuning = json.loads(tuning_path.read_text(encoding="utf-8"))
        if float(tuning.get("selected_hyperparameter")) != float(selected):
            raise RunnerError("G07_COMPLETED_RESUME_TUNING_SELECTION")
    elif source == "GOVERNED_FIXED_POLICY":
        if policy.mode is not v2_policy.PolicyMode.FIXED or float(selected) != policy.fixed_value:
            raise RunnerError("G07_V2_FIXED_SELECTION_RECONCILIATION")
    elif source == "GOVERNED_V2_PARENT_INHERITANCE":
        inherited = _inheritance_authority(context, policy)
        if (float(inherited["selected_hyperparameter"]) != float(selected) or
                inherited["authority_sha256"] != state["identity"]["inheritance_authority_sha256"]):
            raise RunnerError("G07_V2_INHERITED_SELECTION_RECONCILIATION")
    elif source == "GOVERNED_NO_TUNING" and contract.model_family == "FRACTIONAL_LOGIT_GLM":
        if selected is not None:
            raise RunnerError("G07_COMPLETED_RESUME_FRACTIONAL_SELECTION")
    else:
        raise RunnerError("G07_COMPLETED_RESUME_HYPERPARAMETER_SOURCE")
    early = _validate_prediction_stage_receipt(
        context, authenticated, state, prediction_stage_receipt, expected_keys
    )
    final = g06.integrity_validate_prediction_artifact(
        validation_root, manifest_path,
        expected_contract_id=manifest_contract,
        expected_analysis_id=contract.analysis_id,
        expected_model_family=contract.model_family,
        expected_model_role=contract.model_role,
        expected_outer_evaluation=contract.evaluation_identity,
        expected_evidence_classification=authenticated.evidence_classification,
        expected_heldout_keys=expected_keys,
    )
    if (sha256_file(Path(str(state["prediction_path"]))) != final.artifact_sha256 or
            _g06_4e_key_identity(early) != final.canonical_key_sha256):
        raise RunnerError("G07_COMPLETED_RESUME_STALE_PREDICTION")
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    if (Path(str(state.get("terminal_evidence_path", ""))).resolve() != terminal_path.resolve() or
            Path(str(state.get("publication_gate_path", ""))).resolve() !=
            (run_root / "v2_publication_gate.json").resolve()):
        raise RunnerError("G07_V2_COMPLETED_GOVERNED_PATH")
    if terminal != {
        "schema_version": "PAPER1_G07_TERMINAL_V1",
        "disposition": "COMPLETE",
        "prediction_available": True,
        "exception_metadata": None,
    }:
        raise RunnerError("G07_COMPLETED_RESUME_TERMINAL")
    _validate_preterminal_artifacts(
        context, authenticated, state, run_root, require_gate=True
    )
    if (contract.model_family == "L2_LOGISTIC" and contract.model_role == "baseline" and
            contract.analysis_family == "PRIMARY_EVT"):
        _reconcile_governed_benchmark_evidence(
            context, authenticated, state, frame, heldout_index, "GEOMETRY_LOGISTIC"
        )
        _reconcile_governed_benchmark_evidence(
            context, authenticated, state, frame, heldout_index, "TRAINING_PREVALENCE"
        )


def _result_from_production_state(
    context: _DispatchContext,
    state: Mapping[str, object],
    resumed: bool,
) -> ProductionExecutionResult:
    manifest_path = Path(str(state["manifest_path"]))
    validation_root = Path(str(state["validation_root"]))
    g06.validate_execution_manifest(validation_root, manifest_path, True)
    return ProductionExecutionResult(
        "PAPER1_G07_PRODUCTION_EXECUTION_RESULT_V1", context.request.run_id,
        context.plan_entry.unit_id, TerminalDisposition(str(state["terminal_disposition"])),
        str(state["classification"]), tuple(state["completed_phases"]),
        None if state.get("selected_hyperparameter") is None else float(state["selected_hyperparameter"]),
        state.get("prediction_path"), state.get("metrics_path"), str(state["terminal_evidence_path"]),
        str(manifest_path), sha256_file(manifest_path), len(_checkpoint_records(state)), resumed,
        int(state.get("model_fit_count", 0)),
    )


def _nonexecution_terminal(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: dict[str, object],
    disposition: TerminalDisposition,
) -> ProductionExecutionResult:
    run_root = Path(state["run_root"])
    terminal = TerminalRecord("PAPER1_G07_TERMINAL_V1", disposition, False, None)
    validate_terminal_record(terminal)
    terminal_path = run_root / "terminal_evidence.json"
    _write_once(terminal_path, canonical_json({**asdict(terminal), "disposition": disposition.value}) + b"\n")
    state["terminal_evidence_path"] = str(terminal_path)
    state["terminal_disposition"] = disposition.value
    _persist_production_checkpoint(run_root, state, "TERMINAL_EVIDENCE_WRITTEN")
    _persist_production_checkpoint(run_root, state, "COMPLETE")
    state["end_timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    statuses = {
        TerminalDisposition.ENVIRONMENT_BLOCKED: "ENVIRONMENT_BLOCKED",
        TerminalDisposition.NONESTIMABLE: "GOVERNED_NONESTIMABLE",
        TerminalDisposition.DISABLED: "MACHINE_DISABLED_NONEXECUTING",
    }
    manifest = _write_manifest(
        context, authenticated, state, run_root / "execution_manifest.json",
        terminal_status=statuses[disposition], output=None,
    )
    state["manifest_path"] = str(manifest)
    return _result_from_production_state(context, state, bool(context.request.resume))


def _runtime_failure_terminal(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: dict[str, object],
    evidence: RuntimeFailureReceipt | CallerReportedFailure,
) -> ProductionExecutionResult:
    run_root = Path(state["run_root"])
    record = TerminalRecord("PAPER1_G07_TERMINAL_V1", TerminalDisposition.FAILED_RUNTIME, False, evidence)
    validate_terminal_record(record)
    terminal_path = run_root / "terminal_evidence.json"
    serial = asdict(record)
    serial["disposition"] = TerminalDisposition.FAILED_RUNTIME.value
    _write_once(terminal_path, canonical_json(serial) + b"\n")
    state["terminal_evidence_path"] = str(terminal_path)
    state["terminal_disposition"] = TerminalDisposition.FAILED_RUNTIME.value
    _persist_production_checkpoint(run_root, state, "TERMINAL_EVIDENCE_WRITTEN")
    _persist_production_checkpoint(run_root, state, "COMPLETE")
    state["end_timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    exception_metadata = asdict(evidence)
    manifest = _write_manifest(
        context, authenticated, state, run_root / "execution_manifest.json",
        terminal_status="FAILED_RUNTIME", output=None, exception_metadata=exception_metadata,
    )
    state["manifest_path"] = str(manifest)
    return _result_from_production_state(context, state, bool(context.request.resume))


def _loio_specification_identity(root: Path) -> str:
    paths = (
        "documentation/PAPER1_G05B_LOIO_CONTRACT.csv",
        "documentation/PAPER1_G06_AGGREGATION_CONTRACT.csv",
        "documentation/PAPER1_G07_LOIO_EVIDENCE_CONTRACT.csv",
    )
    return sha256_bytes(canonical_json([
        {"path": path, "sha256": sha256_file(root / path)} for path in paths
    ]))


def _loio_configuration_identity(context: _DispatchContext, specification: str) -> str:
    return sha256_bytes(canonical_json({
        "contract_sha256": context.contract.contract_sha256,
        "governed_intervals": list(PRIMARY_HELDOUT_INTERVALS),
        "metrics": list(LOIO_METRICS),
        "aggregation": "DELETE_INTERVAL_RECOMPUTE_BLOCK_MEAN_EQUAL_MEAN_B2_B3_B4",
        "rank": "DESCENDING_ABSOLUTE_CHANGE_TIES_ASCENDING_INTERVAL",
        "specification_identity": specification,
        "model_fit_count": 0,
        "retuning_count": 0,
        "prediction_generated": False,
    }))


def _safe_relative_file(root: Path, path: Path, marker: str) -> tuple[Path, str]:
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise RunnerError(marker) from exc
    if not resolved.is_file():
        raise RunnerError(marker)
    return resolved, relative.as_posix()


def _loio_source_evidence(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
) -> tuple[list[dict[str, object]], pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object], str]:
    paths = tuple(context.request.loio_source_manifest_paths)
    if len(paths) != 6 or len({str(Path(path).resolve()) for path in paths}) != 6:
        raise RunnerError("G07_LOIO_SOURCE_MANIFEST_SET")
    validation_root = Path(authenticated.validation_root)
    expected_outcome = next(
        (dict(item) for item in authenticated.input_artifacts if item["schema"] == g06.OUTCOME_INPUT_SCHEMA),
        None,
    )
    if expected_outcome is None:
        raise RunnerError("G07_LOIO_OUTCOME_EVIDENCE")
    expected_pairs = {(evaluation, role) for evaluation in LOIO_SOURCE_EVALUATIONS
                      for role in ("baseline", "augmented")}
    observed: set[tuple[str, str]] = set()
    source_records: list[dict[str, object]] = []
    predictions: dict[str, list[pd.DataFrame]] = {"baseline": [], "augmented": []}
    source_identities: list[dict[str, object]] = []
    for supplied_path in paths:
        path, relative = _safe_relative_file(
            validation_root, Path(supplied_path), "G07_LOIO_SOURCE_MANIFEST_PATH"
        )
        validated = g06.validate_execution_manifest(validation_root, path, True)
        record = validated.record
        pair = (str(record["outer_evaluation"]), str(record["model_role"]))
        if (pair not in expected_pairs or pair in observed or
                record["analysis_id"] != "G05A_01_PRIMARY_EVT_1KM" or
                record["model_family"] != "L2_LOGISTIC" or
                record["evidence_classification"] != authenticated.evidence_classification or
                record["terminal_status"] != "COMPLETE"):
            raise RunnerError("G07_LOIO_SOURCE_BINDING")
        outcome_inputs = [item for item in record["input_artifacts"]
                          if item["schema"] == g06.OUTCOME_INPUT_SCHEMA]
        if (len(outcome_inputs) != 1 or
                outcome_inputs[0]["sha256"] != expected_outcome["sha256"] or
                outcome_inputs[0]["key_identity"] != expected_outcome["key_identity"]):
            raise RunnerError("G07_LOIO_SOURCE_OUTCOME_BINDING")
        expected_keys = authenticated.frame.loc[
            authenticated.frame["interval_number"].isin(record["heldout_history"]),
            [*g06.KEY_FIELDS, "interval_number"],
        ]
        integrity = g06.integrity_validate_prediction_artifact(
            validation_root, path,
            expected_contract_id=str(record["execution_contract_id"]),
            expected_analysis_id="G05A_01_PRIMARY_EVT_1KM",
            expected_model_family="L2_LOGISTIC",
            expected_model_role=pair[1],
            expected_outer_evaluation=pair[0],
            expected_evidence_classification=authenticated.evidence_classification,
            expected_heldout_keys=expected_keys,
        )
        prediction_relative = Path(integrity.artifact_path).relative_to(validation_root).as_posix()
        source_record = {
            "execution_manifest_path": relative,
            "execution_manifest_sha256": validated.manifest_sha256,
            "prediction_artifact_path": prediction_relative,
            "prediction_artifact_sha256": integrity.artifact_sha256,
            "analysis_id": integrity.analysis_id,
            "model_role": integrity.model_role,
            "outer_evaluation": integrity.outer_evaluation,
            "evidence_classification": integrity.evidence_classification,
            "key_identity": integrity.canonical_key_sha256,
        }
        source_records.append(source_record)
        predictions[pair[1]].append(integrity.to_frame())
        source_identities.append(source_record)
        observed.add(pair)
    if observed != expected_pairs:
        raise RunnerError("G07_LOIO_SOURCE_MANIFEST_COVERAGE")
    combined: dict[str, pd.DataFrame] = {}
    for role, frames in predictions.items():
        frame = pd.concat(frames, ignore_index=True).sort_values(
            list(g06.KEY_FIELDS), kind="stable"
        ).reset_index(drop=True)
        if (frame.duplicated(list(g06.KEY_FIELDS)).any() or
                tuple(sorted(frame["interval_number"].unique())) != PRIMARY_HELDOUT_INTERVALS):
            raise RunnerError("G07_LOIO_SOURCE_KEY_COVERAGE")
        combined[role] = frame
    outcome = authenticated.frame.loc[
        authenticated.frame["interval_number"].isin(PRIMARY_HELDOUT_INTERVALS),
        [*g06.KEY_FIELDS, "interval_number", "y"],
    ].sort_values(list(g06.KEY_FIELDS), kind="stable").reset_index(drop=True)
    keys = [*g06.KEY_FIELDS, "interval_number"]
    if (combined["baseline"].loc[:, keys].to_dict("records") !=
            combined["augmented"].loc[:, keys].to_dict("records") or
            combined["baseline"].loc[:, keys].to_dict("records") !=
            outcome.loc[:, keys].to_dict("records")):
        raise RunnerError("G07_LOIO_PAIRED_SOURCE_KEYS")
    outcome_record = {
        "outcome_artifact_path": expected_outcome["path"],
        "outcome_artifact_sha256": expected_outcome["sha256"],
        "outcome_schema": g06.OUTCOME_INPUT_SCHEMA,
        "evidence_classification": authenticated.evidence_classification,
        "key_interval_value_identity": expected_outcome["key_identity"],
    }
    aggregate = sha256_bytes(canonical_json({
        "sources": sorted(source_identities, key=lambda item: (
            str(item["outer_evaluation"]), str(item["model_role"])
        )),
        "outcome": outcome_record,
    }))
    return source_records, combined["baseline"], combined["augmented"], outcome, outcome_record, aggregate


def _reconstruct_loio_result(
    baseline: pd.DataFrame, augmented: pd.DataFrame, outcomes: pd.DataFrame,
) -> pd.DataFrame:
    keys = [*g06.KEY_FIELDS, "interval_number"]
    paired = baseline.rename(columns={"predicted_probability": "baseline_probability"}).merge(
        augmented.rename(columns={"predicted_probability": "augmented_probability"}),
        on=keys, validate="one_to_one",
    ).merge(outcomes, on=keys, validate="one_to_one")
    y = paired["y"].to_numpy(float)
    baseline_p = np.clip(paired["baseline_probability"].to_numpy(float), 1e-15, 1 - 1e-15)
    augmented_p = np.clip(paired["augmented_probability"].to_numpy(float), 1e-15, 1 - 1e-15)
    paired["log_loss_benefit"] = (
        -y * np.log(baseline_p) - (1 - y) * np.log(1 - baseline_p)
        - (-y * np.log(augmented_p) - (1 - y) * np.log(1 - augmented_p))
    )
    paired["brier_benefit"] = (
        (y - baseline_p) ** 2 - (y - augmented_p) ** 2
    )
    interval_scores = paired.groupby("interval_number", sort=True)[list(LOIO_METRICS)].mean()
    if tuple(int(value) for value in interval_scores.index) != PRIMARY_HELDOUT_INTERVALS:
        raise RunnerError("G07_LOIO_INTERVAL_SET")
    rows: list[dict[str, object]] = []
    block_intervals = {block: [interval for interval, observed in LOIO_INTERVAL_BLOCKS.items()
                               if observed == block] for block in ("B2", "B3", "B4")}
    for metric in LOIO_METRICS:
        full_blocks = {block: float(interval_scores.loc[values, metric].mean())
                       for block, values in block_intervals.items()}
        full = float(np.mean(list(full_blocks.values())))
        metric_rows = []
        for omitted in PRIMARY_HELDOUT_INTERVALS:
            affected = LOIO_INTERVAL_BLOCKS[omitted]
            omitted_blocks = dict(full_blocks)
            retained = [value for value in block_intervals[affected] if value != omitted]
            omitted_blocks[affected] = float(interval_scores.loc[retained, metric].mean())
            estimate = float(np.mean(list(omitted_blocks.values())))
            metric_rows.append({
                "metric_id": metric,
                "omitted_interval": omitted,
                "affected_block": affected,
                "full_estimate": full,
                "omitted_estimate": estimate,
                "absolute_change": abs(estimate - full),
            })
        ranked = sorted(metric_rows, key=lambda item: (-float(item["absolute_change"]),
                                                       int(item["omitted_interval"])))
        ranks = {int(item["omitted_interval"]): index for index, item in enumerate(ranked, start=1)}
        for item in metric_rows:
            item["rank"] = ranks[int(item["omitted_interval"])]
            rows.append(item)
    result = pd.DataFrame(rows, columns=LOIO_RESULT_COLUMNS).sort_values(
        ["metric_id", "omitted_interval"], kind="stable"
    ).reset_index(drop=True)
    if (len(result) != 24 or result.duplicated(["metric_id", "omitted_interval"]).any() or
            not np.isfinite(result[["full_estimate", "omitted_estimate", "absolute_change"]]).all().all()):
        raise RunnerError("G07_LOIO_RESULT_SEMANTICS")
    return result


def _loio_checkpoint(
    validation_root: Path, run_root: Path, identity: Mapping[str, object],
    phase: str, sequence: int,
) -> dict[str, object]:
    payload = {
        "schema_version": "PAPER1_G07_LOIO_CHECKPOINT_V1",
        "sequence": sequence,
        "resume_from_sequence": None if sequence == 1 else sequence - 1,
        "phase": phase,
        "identity": dict(identity),
    }
    path = run_root / "checkpoints" / f"{sequence:02d}_{phase}.json"
    _write_once(path, canonical_json(payload) + b"\n")
    return {
        "sequence": sequence,
        "resume_from_sequence": payload["resume_from_sequence"],
        "phase": phase,
        "path": path.relative_to(validation_root).as_posix(),
        "sha256": sha256_file(path),
        "identity": dict(identity),
    }


def _validate_loio_evidence(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    manifest_path: Path,
) -> tuple[dict[str, object], pd.DataFrame]:
    validation_root = Path(authenticated.validation_root)
    manifest_path, _ = _safe_relative_file(
        validation_root, manifest_path, "G07_LOIO_MANIFEST_PATH"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema_name", "schema_version", "manifest_role", "paper1_run_id",
        "execution_unit_id", "execution_contract_sha256", "analysis_id", "analysis_family",
        "model_family", "model_role", "evidence_classification", "resolution_m",
        "risk_set_id", "governed_intervals", "source_outer_evaluations",
        "loio_specification_identity", "metric_definitions", "aggregation_rule", "rank_rule",
        "source_oof_evidence", "source_outcome_evidence", "paired_source_key_identity",
        "result_artifact", "environment_identity", "configuration_identity",
        "checkpoint_records", "terminal_record", "start_timestamp_utc", "end_timestamp_utc",
        "reopen_reconciliation", "policy_schema_version", "hyperparameter_policy_sha256",
        "hyperparameter_policy_mode", "policy_receipt_sha256",
    }
    if set(manifest) != required:
        raise RunnerError("G07_LOIO_MANIFEST_FIELDS")
    specification = _loio_specification_identity(context.project_root)
    configuration = _loio_configuration_identity(context, specification)
    expected = {
        "schema_name": "PAPER1_G07_LOIO_EVIDENCE_MANIFEST",
        "schema_version": "PAPER1_G07_LOIO_EVIDENCE_MANIFEST_V1",
        "manifest_role": "AUDIT_AND_REPRODUCIBILITY_METADATA",
        "paper1_run_id": context.request.run_id,
        "execution_unit_id": context.plan_entry.unit_id,
        "execution_contract_sha256": context.contract.contract_sha256,
        "analysis_id": "G05B_LOIO_PRIMARY_FORWARD",
        "analysis_family": "LEAVE_ONE_INTERVAL_OUT_DIAGNOSTIC",
        "model_family": "DIAGNOSTIC_NO_REFIT",
        "model_role": "paired_delta",
        "evidence_classification": authenticated.evidence_classification,
        "resolution_m": 1000,
        "risk_set_id": "PRIMARY_HYBRID",
        "governed_intervals": list(PRIMARY_HELDOUT_INTERVALS),
        "source_outer_evaluations": list(LOIO_SOURCE_EVALUATIONS),
        "loio_specification_identity": specification,
        "metric_definitions": list(LOIO_METRICS),
        "aggregation_rule": "DELETE_INTERVAL_RECOMPUTE_BLOCK_MEAN_EQUAL_MEAN_B2_B3_B4",
        "rank_rule": "DESCENDING_ABSOLUTE_CHANGE_TIES_ASCENDING_INTERVAL",
        "configuration_identity": configuration,
        "policy_schema_version": v2_policy.POLICY_SCHEMA_VERSION,
        "hyperparameter_policy_sha256": v2_policy.resolve_policy(context.contract).policy_sha256,
        "hyperparameter_policy_mode": v2_policy.PolicyMode.NO_REFIT.value,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RunnerError("G07_LOIO_MANIFEST_BINDING")
    policy_receipt_path = manifest_path.parent / "hyperparameter_policy_receipt.json"
    if (not policy_receipt_path.is_file() or
            manifest.get("policy_receipt_sha256") != sha256_file(policy_receipt_path)):
        raise RunnerError("G07_V2_LOIO_POLICY_RECEIPT")
    sources, baseline, augmented, outcomes, outcome_record, source_aggregate = _loio_source_evidence(
        context, authenticated
    )
    if (manifest["source_oof_evidence"] != sources or
            manifest["source_outcome_evidence"] != outcome_record or
            manifest["paired_source_key_identity"] != _g06_4e_key_identity(outcomes)):
        raise RunnerError("G07_LOIO_SOURCE_RECONCILIATION")
    descriptor = manifest["result_artifact"]
    if set(descriptor) != {"path", "sha256", "schema", "row_count", "required_columns", "key_identity"}:
        raise RunnerError("G07_LOIO_RESULT_DESCRIPTOR")
    result_path, _ = _safe_relative_file(
        validation_root, validation_root / descriptor["path"], "G07_LOIO_RESULT_PATH"
    )
    if (descriptor["sha256"] != sha256_file(result_path) or
            descriptor["schema"] != "PAPER1_G07_LOIO_RESULT_V1" or
            descriptor["row_count"] != 24 or
            descriptor["required_columns"] != list(LOIO_RESULT_COLUMNS)):
        raise RunnerError("G07_LOIO_RESULT_DESCRIPTOR")
    observed = pd.read_csv(result_path)
    if (tuple(observed.columns) != LOIO_RESULT_COLUMNS or len(observed) != 24 or
            observed.duplicated(["metric_id", "omitted_interval"]).any() or
            descriptor["key_identity"] != sha256_bytes(canonical_json(
                observed[["metric_id", "omitted_interval"]].to_dict("records")
            ))):
        raise RunnerError("G07_LOIO_RESULT_SCHEMA")
    reconstructed = _reconstruct_loio_result(baseline, augmented, outcomes)
    if (observed[["metric_id", "omitted_interval", "affected_block", "rank"]].to_dict("records") !=
            reconstructed[["metric_id", "omitted_interval", "affected_block", "rank"]].to_dict("records") or
            not np.allclose(
                observed[["full_estimate", "omitted_estimate", "absolute_change"]],
                reconstructed[["full_estimate", "omitted_estimate", "absolute_change"]],
                rtol=0.0, atol=1e-15,
            )):
        raise RunnerError("G07_LOIO_RESULT_RECONSTRUCTION")
    checkpoints = manifest["checkpoint_records"]
    if len(checkpoints) != 4:
        raise RunnerError("G07_LOIO_CHECKPOINT_COUNT")
    checkpoint_hashes = []
    for sequence, (record, phase) in enumerate(zip(checkpoints, LOIO_PHASES), start=1):
        path, _ = _safe_relative_file(
            validation_root, validation_root / record["path"], "G07_LOIO_CHECKPOINT_PATH"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected_payload = {
            "schema_version": "PAPER1_G07_LOIO_CHECKPOINT_V1",
            "sequence": sequence,
            "resume_from_sequence": None if sequence == 1 else sequence - 1,
            "phase": phase,
            "identity": record.get("identity"),
        }
        if (record.get("sequence") != sequence or record.get("phase") != phase or
                record.get("resume_from_sequence") != (None if sequence == 1 else sequence - 1) or
                record.get("sha256") != sha256_file(path) or payload != expected_payload):
            raise RunnerError("G07_LOIO_CHECKPOINT_RECONCILIATION")
        checkpoint_hashes.append(record["sha256"])
    terminal = manifest["terminal_record"]
    terminal_path, _ = _safe_relative_file(
        validation_root, validation_root / terminal["path"], "G07_LOIO_TERMINAL_PATH"
    )
    terminal_payload = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal_claims = dict(terminal)
    terminal_claims.pop("sha256", None)
    if (terminal_payload != terminal_claims or terminal.get("sha256") != sha256_file(terminal_path) or
            terminal.get("disposition") != "COMPLETE" or
            terminal.get("execution_kind") != "NO_REFIT_DIAGNOSTIC" or
            terminal.get("model_fit_count") != 0 or terminal.get("retuning_count") != 0 or
            terminal.get("prediction_generated") is not False or
            terminal.get("result_available") is not True or terminal.get("exception_reference") is not None or
            terminal.get("result_sha256") != descriptor["sha256"]):
        raise RunnerError("G07_LOIO_TERMINAL_RECONCILIATION")
    reopen = manifest["reopen_reconciliation"]
    expected_reopen = {
        "validator_identity": "PAPER1_G07_CORRECTION_2_LOIO_VALIDATOR_V1",
        "source_aggregate_sha256": source_aggregate,
        "result_sha256": descriptor["sha256"],
        "checkpoint_aggregate_sha256": sha256_bytes(canonical_json(checkpoint_hashes)),
        "terminal_sha256": terminal["sha256"],
        "validation_result": "PASS",
    }
    if reopen != expected_reopen:
        raise RunnerError("G07_LOIO_REOPEN_RECONCILIATION")
    return manifest, observed


def _run_loio_production_lifecycle(context: _DispatchContext) -> ProductionExecutionResult:
    """Execute accepted no-refit LOIO evidence from reopened governed OOF predictions."""
    authenticated = _authenticate_execution_input(context)
    policy = _governed_policy(context)
    if policy.mode is not v2_policy.PolicyMode.NO_REFIT:
        raise RunnerError("G07_V2_LOIO_POLICY")
    if (context.contract.model_family != "DIAGNOSTIC_NO_REFIT" or
            context.contract.analysis_id != "G05B_LOIO_PRIMARY_FORWARD"):
        raise RunnerError("G07_LOIO_CONTRACT")
    if "loio_interval_deltas" in authenticated.authorized_hyperparameters:
        raise RunnerError("G07_LOIO_CALLER_DELTA_PROHIBITED")
    validation_root = Path(authenticated.validation_root)
    output_root = Path(context.request.output_root).resolve()
    try:
        output_root.relative_to(validation_root)
    except ValueError as exc:
        raise RunnerError("G07_OUTPUT_ROOT_OUTSIDE_VALIDATION_ROOT") from exc
    run_root = output_root / context.request.run_id
    run_root.mkdir(parents=True, exist_ok=True)
    policy_receipt_path = run_root / "hyperparameter_policy_receipt.json"
    policy_payload = {
        "schema_version": "PAPER1_G07_V2_POLICY_RECEIPT_V1",
        "unit_id": context.plan_entry.unit_id,
        "contract_sha256": context.contract.contract_sha256,
        "policy": {**asdict(policy), "mode": policy.mode.value},
        "policy_sha256": policy.policy_sha256,
        "selection_evidence": {"selected_hyperparameter": None},
        "selected_hyperparameter": None,
        "hyperparameter_source": "GOVERNED_NO_REFIT",
    }
    _write_or_validate_bytes(
        policy_receipt_path, canonical_json(policy_payload) + b"\n",
        "G07_V2_LOIO_POLICY_RECEIPT_COLLISION",
    )
    manifest_path = run_root / "loio_evidence_manifest.json"
    if context.request.resume and manifest_path.is_file():
        _validate_loio_evidence(context, authenticated, manifest_path)
        return ProductionExecutionResult(
            "PAPER1_G07_PRODUCTION_EXECUTION_RESULT_V1", context.request.run_id,
            context.plan_entry.unit_id, TerminalDisposition.COMPLETE,
            authenticated.evidence_classification, LOIO_PHASES,
            None, None, str(run_root / "loio_result.csv"),
            str(run_root / "terminal_evidence.json"), str(manifest_path), sha256_file(manifest_path),
            4, True, 0,
        )
    if manifest_path.exists() or (run_root / "checkpoints").exists():
        raise RunnerError("G07_EXISTING_PRODUCTION_CHECKPOINT_REQUIRES_RESUME")
    sources, baseline, augmented, outcomes, outcome_record, source_aggregate = _loio_source_evidence(
        context, authenticated
    )
    specification = _loio_specification_identity(context.project_root)
    configuration = _loio_configuration_identity(context, specification)
    paired_key_identity = _g06_4e_key_identity(outcomes)
    identity = {
        "paper1_run_id": context.request.run_id,
        "execution_unit_id": context.plan_entry.unit_id,
        "execution_contract_sha256": context.contract.contract_sha256,
        "analysis_id": context.contract.analysis_id,
        "evidence_classification": authenticated.evidence_classification,
        "source_aggregate_sha256": source_aggregate,
        "loio_specification_identity": specification,
        "environment_identity": f"python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "configuration_identity": configuration,
    }
    checkpoints = [_loio_checkpoint(validation_root, run_root, identity, "INPUTS_VALIDATED", 1)]
    result = _reconstruct_loio_result(baseline, augmented, outcomes)
    result_path = run_root / "loio_result.csv"
    _write_once(result_path, result.to_csv(index=False, lineterminator="\n").encode("utf-8"))
    checkpoints.append(_loio_checkpoint(validation_root, run_root, identity, "RESULT_WRITTEN", 2))
    descriptor = {
        "path": result_path.relative_to(validation_root).as_posix(),
        "sha256": sha256_file(result_path),
        "schema": "PAPER1_G07_LOIO_RESULT_V1",
        "row_count": 24,
        "required_columns": list(LOIO_RESULT_COLUMNS),
        "key_identity": sha256_bytes(canonical_json(
            result[["metric_id", "omitted_interval"]].to_dict("records")
        )),
    }
    terminal_path = run_root / "terminal_evidence.json"
    terminal = {
        "schema_version": "PAPER1_G07_LOIO_TERMINAL_V1",
        "path": terminal_path.relative_to(validation_root).as_posix(),
        "sha256": "PENDING",
        "disposition": "COMPLETE",
        "execution_kind": "NO_REFIT_DIAGNOSTIC",
        "model_fit_count": 0,
        "retuning_count": 0,
        "prediction_generated": False,
        "result_available": True,
        "exception_reference": None,
        "result_sha256": descriptor["sha256"],
    }
    terminal_without_hash = dict(terminal)
    terminal_without_hash.pop("sha256")
    _write_once(terminal_path, canonical_json(terminal_without_hash) + b"\n")
    terminal["sha256"] = sha256_file(terminal_path)
    # The terminal path/hash descriptor lives in the manifest; persisted terminal bytes are immutable claims.
    checkpoints.append(_loio_checkpoint(validation_root, run_root, identity, "TERMINAL_EVIDENCE_WRITTEN", 3))
    checkpoints.append(_loio_checkpoint(validation_root, run_root, identity, "COMPLETE", 4))
    terminal_descriptor = dict(terminal)
    terminal_descriptor.update(terminal_without_hash)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    checkpoint_hashes = [item["sha256"] for item in checkpoints]
    manifest = {
        "schema_name": "PAPER1_G07_LOIO_EVIDENCE_MANIFEST",
        "schema_version": "PAPER1_G07_LOIO_EVIDENCE_MANIFEST_V1",
        "manifest_role": "AUDIT_AND_REPRODUCIBILITY_METADATA",
        "paper1_run_id": context.request.run_id,
        "execution_unit_id": context.plan_entry.unit_id,
        "execution_contract_sha256": context.contract.contract_sha256,
        "analysis_id": "G05B_LOIO_PRIMARY_FORWARD",
        "analysis_family": "LEAVE_ONE_INTERVAL_OUT_DIAGNOSTIC",
        "model_family": "DIAGNOSTIC_NO_REFIT",
        "model_role": "paired_delta",
        "evidence_classification": authenticated.evidence_classification,
        "resolution_m": 1000,
        "risk_set_id": "PRIMARY_HYBRID",
        "governed_intervals": list(PRIMARY_HELDOUT_INTERVALS),
        "source_outer_evaluations": list(LOIO_SOURCE_EVALUATIONS),
        "loio_specification_identity": specification,
        "metric_definitions": list(LOIO_METRICS),
        "aggregation_rule": "DELETE_INTERVAL_RECOMPUTE_BLOCK_MEAN_EQUAL_MEAN_B2_B3_B4",
        "rank_rule": "DESCENDING_ABSOLUTE_CHANGE_TIES_ASCENDING_INTERVAL",
        "source_oof_evidence": sources,
        "source_outcome_evidence": outcome_record,
        "paired_source_key_identity": paired_key_identity,
        "result_artifact": descriptor,
        "environment_identity": identity["environment_identity"],
        "configuration_identity": configuration,
        "policy_schema_version": v2_policy.POLICY_SCHEMA_VERSION,
        "hyperparameter_policy_sha256": policy.policy_sha256,
        "hyperparameter_policy_mode": policy.mode.value,
        "policy_receipt_sha256": sha256_file(policy_receipt_path),
        "checkpoint_records": checkpoints,
        "terminal_record": terminal_descriptor,
        "start_timestamp_utc": now,
        "end_timestamp_utc": now,
        "reopen_reconciliation": {
            "validator_identity": "PAPER1_G07_CORRECTION_2_LOIO_VALIDATOR_V1",
            "source_aggregate_sha256": source_aggregate,
            "result_sha256": descriptor["sha256"],
            "checkpoint_aggregate_sha256": sha256_bytes(canonical_json(checkpoint_hashes)),
            "terminal_sha256": terminal["sha256"],
            "validation_result": "PASS",
        },
    }
    _write_once(manifest_path, canonical_json(manifest) + b"\n")
    _validate_loio_evidence(context, authenticated, manifest_path)
    return ProductionExecutionResult(
        "PAPER1_G07_PRODUCTION_EXECUTION_RESULT_V1", context.request.run_id,
        context.plan_entry.unit_id, TerminalDisposition.COMPLETE,
        authenticated.evidence_classification, LOIO_PHASES,
        None, None, str(result_path), str(terminal_path), str(manifest_path), sha256_file(manifest_path),
        4, False, 0,
    )


def _paired_group_contracts(context: _DispatchContext) -> tuple[g06.ExecutionContract, ...]:
    contract = context.contract
    if contract.model_role not in {"baseline", "augmented"}:
        return ()
    contracts = tuple(
        item for item in g06.governed_execution_contracts(context.project_root)
        if item.analysis_id == contract.analysis_id
        and item.model_family == contract.model_family
        and item.resolution_m == contract.resolution_m
        and item.support_identity == contract.support_identity
        and item.model_role in {"baseline", "augmented"}
        and item.evaluation_identity in LOIO_SOURCE_EVALUATIONS
        and item.execution_enabled
    )
    expected = {
        (role, evaluation)
        for role in ("baseline", "augmented")
        for evaluation in LOIO_SOURCE_EVALUATIONS
    }
    if {(item.model_role, item.evaluation_identity) for item in contracts} != expected:
        return ()
    return tuple(sorted(contracts, key=lambda item: (item.model_role, item.evaluation_identity)))


def _boundary_partial_pair_group(contracts: Sequence[g06.ExecutionContract]) -> bool:
    return (
        len(contracts) == 6
        and {item.analysis_id for item in contracts} == {"G05B_BOUNDARY_1000"}
        and {item.model_family for item in contracts} == {"L2_LOGISTIC"}
        and {item.resolution_m for item in contracts} == {1000}
        and {
            (item.model_role, item.evaluation_identity)
            for item in contracts if item.special_condition == "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE"
        } == {("baseline", "B1_TO_B2"), ("augmented", "B1_TO_B2")}
    )


def _reopen_pair_nonestimable_source(
    context: _DispatchContext,
    contract: g06.ExecutionContract,
    unit_root: Path,
) -> Mapping[str, object]:
    if contract.special_condition != "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE":
        raise RunnerError("G07_V2_PAIR_NONESTIMABLE_SCOPE")
    state = _reopen_production_state(unit_root, Path(context.project_root))
    prediction_artifacts = (
        "predictions.csv",
        "prediction_stage_receipt.json",
        "metrics.json",
        "postprediction_unit_receipt.json",
        "paired_publication_status.json",
        "rf_seed_evidence.json",
        "v2_execution_evidence_manifest.json",
        "v2_publication_gate.json",
    )
    if any((unit_root / name).exists() or (unit_root / name).is_symlink()
           for name in prediction_artifacts):
        raise RunnerError("G07_V2_PAIR_NONESTIMABLE_PREDICTION_EVIDENCE")
    terminal_path = unit_root / "terminal_evidence.json"
    manifest_path = unit_root / "execution_manifest.json"
    if (state.get("current_phase") != "COMPLETE"
            or state.get("terminal_disposition") != TerminalDisposition.NONESTIMABLE.value
            or not terminal_path.is_file() or not manifest_path.is_file()):
        raise RunnerError("G07_V2_PAIR_NONESTIMABLE_NOT_AUTHENTIC_TERMINAL")
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    if terminal.get("disposition") != TerminalDisposition.NONESTIMABLE.value:
        raise RunnerError("G07_V2_PAIR_NONESTIMABLE_TERMINAL")
    g06.validate_execution_manifest(Path(context.project_root), manifest_path, True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("paper1_run_id") != _v2_run_id(_unit_id(contract))
            or manifest.get("terminal_status") != "GOVERNED_NONESTIMABLE"
            or manifest.get("output_prediction_artifact") is not None):
        raise RunnerError("G07_V2_PAIR_NONESTIMABLE_MANIFEST")
    producer = _read_evidence_producer(
        context.project_root, contract, unit_root, manifest_path, "execution_manifest"
    )
    return MappingProxyType({
        "unit_id": _unit_id(contract),
        "contract_sha256": producer.contract_sha256,
        "evaluation": contract.evaluation_identity,
        "model_role": contract.model_role,
        "special_condition": contract.special_condition,
        "terminal_disposition": TerminalDisposition.NONESTIMABLE.value,
        "terminal_evidence_path": terminal_path.relative_to(Path(context.project_root)).as_posix(),
        "terminal_evidence_sha256": sha256_file(terminal_path),
        "execution_manifest_path": manifest_path.relative_to(Path(context.project_root)).as_posix(),
        "execution_manifest_sha256": sha256_file(manifest_path),
    })


def _reopen_pair_source_prediction(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    contract: g06.ExecutionContract,
    unit_root: Path,
) -> tuple[pd.DataFrame, Mapping[str, object]]:
    validation_root = Path(authenticated.validation_root)
    stage_path = unit_root / "prediction_stage_receipt.json"
    if not stage_path.is_file():
        raise RunnerError("G07_V2_PAIR_SOURCE_RECEIPT_MISSING")
    prediction_path, issued_prediction, issuance, migration = _reopen_prediction_issuance(
        context, authenticated, contract, unit_root
    )
    stage = json.loads(stage_path.read_text(encoding="utf-8"))
    stage_payload = dict(stage)
    stage_hash = stage_payload.pop("receipt_sha256", None)
    if stage_hash != sha256_bytes(canonical_json(stage_payload)):
        raise RunnerError("G07_V2_PAIR_STAGE_RECEIPT_HASH")
    policy = v2_policy.resolve_policy(contract)
    expected_inputs = [
        {"path": contract.predictor_path, "sha256": contract.predictor_sha256,
         "schema": "PAPER1_G06_AUTHENTICATED_PREDICTOR_INPUT_V1",
         "key_identity": contract.predictor_key_sha256},
        {"path": contract.response_path, "sha256": contract.response_sha256,
         "schema": g06.OUTCOME_INPUT_SCHEMA,
         "key_identity": contract.response_key_interval_value_sha256},
        {"path": contract.support_path, "sha256": contract.support_sha256,
         "schema": "PAPER1_G06_AUTHENTICATED_SUPPORT_INPUT_V1",
         "key_identity": sha256_bytes(contract.support_identity.encode("utf-8"))},
    ]
    input_identity = sha256_bytes(canonical_json(expected_inputs))
    configuration = _configuration_for(authenticated.evidence_classification)
    config = asdict(configuration)
    config["mode"] = configuration.mode.value
    expected_stage = {
        "schema_version": PREDICTION_STAGE_SCHEMA_VERSION,
        "stage_status": "PREDICTION_VALIDATED_NOT_TERMINAL",
        "run_id": _v2_run_id(_unit_id(contract)),
        "unit_id": _unit_id(contract),
        "analysis_id": contract.analysis_id,
        "model_family": contract.model_family,
        "model_role": contract.model_role,
        "outer_evaluation": contract.evaluation_identity,
        "resolution_m": contract.resolution_m,
        "risk_set_id": contract.risk_set_id,
        "support_identity": contract.support_identity,
        "evidence_classification": authenticated.evidence_classification,
        "policy_sha256": policy.policy_sha256,
        "input_identity": input_identity,
        "environment_configuration_sha256": sha256_bytes(canonical_json(config)),
    }
    if (
        any(stage_payload.get(key) != value for key, value in expected_stage.items())
        or stage_payload.get("contract_sha256")
        != (
            migration["historical_contract_sha256"]
            if migration is not None else contract.contract_sha256
        )
        or stage_payload.get("source_commit")
        != (
            migration["historical_source_commit"]
            if migration is not None else _git_head(context.project_root)
        )
    ):
        raise RunnerError("G07_V2_PAIR_STAGE_BINDING")
    recorded_prediction_path = _resolve_bound_artifact(
        validation_root, stage_payload.get("prediction_artifact", {}),
        expected_schema=g06.PREDICTION_ARTIFACT_SCHEMA,
    )
    if (recorded_prediction_path.resolve() != prediction_path.resolve() or
            stage_payload.get("prediction_artifact") != issuance.get("prediction_artifact")):
        raise RunnerError("G07_V2_PAIR_PREDICTION_ISSUANCE")
    prediction = pd.read_csv(prediction_path)
    if tuple(prediction.columns) != tuple(g06.PREDICTION_INTEGRITY_COLUMNS):
        raise RunnerError("G07_V2_PAIR_PREDICTION_SCHEMA")
    expected_keys = authenticated.frame.loc[
        authenticated.frame.interval_number.isin(contract.heldout_intervals),
        [*g06.KEY_FIELDS, "interval_number"],
    ].sort_values(list(g06.KEY_FIELDS), kind="stable").reset_index(drop=True)
    observed_keys = prediction.loc[:, [*g06.KEY_FIELDS, "interval_number"]].sort_values(
        list(g06.KEY_FIELDS), kind="stable"
    ).reset_index(drop=True)
    if (not observed_keys.equals(expected_keys) or
            stage_payload.get("prediction_rows") != len(prediction) or
            stage_payload.get("prediction_key_sha256") != _g06_4e_key_identity(prediction)):
        raise RunnerError("G07_V2_PAIR_PREDICTION_IDENTITY")
    if not prediction.equals(issued_prediction):
        raise RunnerError("G07_V2_PAIR_PREDICTION_ISSUANCE")
    source_record = {
        "unit_id": _unit_id(contract), "contract_sha256": contract.contract_sha256,
        "policy_sha256": policy.policy_sha256,
        "prediction_path": prediction_path.relative_to(validation_root).as_posix(),
        "prediction_sha256": sha256_file(prediction_path),
        "prediction_stage_receipt_path": stage_path.relative_to(validation_root).as_posix(),
        "prediction_stage_receipt_sha256": sha256_file(stage_path),
        "prediction_issuance_checkpoint_path": _prediction_issuance_checkpoint_path(
            unit_root
        ).relative_to(validation_root).as_posix(),
        "prediction_issuance_checkpoint_sha256": sha256_file(
            _prediction_issuance_checkpoint_path(unit_root)
        ),
        "evaluation": contract.evaluation_identity,
        "model_role": contract.model_role,
    }
    prediction = prediction.merge(
        authenticated.frame.loc[
            authenticated.frame.interval_number.isin(contract.heldout_intervals),
            [*g06.KEY_FIELDS, "interval_number", "y"],
        ], on=[*g06.KEY_FIELDS, "interval_number"], validate="one_to_one",
    )
    return prediction, MappingProxyType(source_record)


def _attempt_paired_evidence_publication(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    *,
    allow_write: bool = True,
) -> Mapping[str, object]:
    contracts = _paired_group_contracts(context)
    if not contracts:
        return MappingProxyType({
            "status": "NOT_APPLICABLE_NO_COMPLETE_FORWARD_PAIR_GROUP",
            "paired_evidence_path": None, "paired_evidence_sha256": None,
        })
    validation_root = Path(authenticated.validation_root)
    output_root = Path(context.request.output_root).resolve()
    # Reopen a frozen group generation at its recorded provenance. Rebuilding
    # its identity using the reviewer's HEAD would change immutable receipts.
    from src import paper1_g08_runtime as g08
    existing = []
    expected_units = {_unit_id(item) for item in contracts}
    for candidate in sorted((output_root / "paired_evidence").glob("*/paired_benefit_evidence.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        records = payload.get("source_prediction_records", [])
        nonestimable_records = payload.get("source_nonestimable_records", [])
        if {item.get("unit_id") for item in (*records, *nonestimable_records)
                if isinstance(item, dict)} == expected_units:
            existing.append((candidate, payload))
    if len(existing) > 1:
        raise RunnerError("G07_V2_PAIR_GENERATION_DUPLICATE")
    scope = context.pair_validation_scope
    binding = sha256_bytes(canonical_json({
        "project_root": str(Path(context.project_root).resolve()),
        "validation_root": str(validation_root.resolve()),
        "output_root": str(output_root),
        "contracts": sorted((_unit_id(item), item.contract_sha256) for item in contracts),
        "input_identity": authenticated.source_manifest_sha256,
    }))
    if scope is not None and not scope.active:
        raise RunnerError("G07_V2_PAIR_VALIDATION_SCOPE_EXPIRED")
    local = scope is not None and scope.proof is not None
    if local:
        if (len(existing) != 1 or scope.proof[0] != binding or
                scope.proof[1] != str(existing[0][0].resolve()) or
                scope.proof[2] != sha256_file(existing[0][0])):
            raise RunnerError("G07_V2_PAIR_VALIDATION_SCOPE_BINDING")
        # A successful global pass only narrows scope. Reopen all six sources
        # below and compare the complete reconstructed canonical pair bytes.
        allow_write = False
    if existing and not local:
        path, payload = existing[0]
        pair_hash = sha256_file(path)
        all_contracts = g06.governed_execution_contracts(context.project_root)
        policy_records = tuple(
            g08._policy_record(_unit_id(item), v2_policy.resolve_policy(item))
            for item in all_contracts
        )
        g08._validate_governed_shared_paired_evidence(
            validation_root, Path(context.project_root), output_root,
            context.plan_entry.unit_id, all_contracts, policy_records,
        )
        if sha256_file(path) != pair_hash:
            raise RunnerError("G07_V2_PAIR_CHANGED_DURING_GLOBAL_VALIDATION")
        if scope is not None:
            scope.proof = (binding, str(path.resolve()), pair_hash)
        return MappingProxyType({
            "status": "PUBLISHED_AND_VALIDATED",
            "paired_evidence_path": path.relative_to(validation_root).as_posix(),
            "paired_evidence_sha256": sha256_file(path),
            "evidence_sha256": payload["evidence_sha256"],
        })
    missing = []
    frames: dict[str, list[pd.DataFrame]] = {"baseline": [], "augmented": []}
    unit_records = []
    nonestimable_records = []
    partial_boundary = _boundary_partial_pair_group(contracts)
    for contract in contracts:
        unit_id = _unit_id(contract)
        unit_root = output_root / _v2_run_id(unit_id)
        if contract.special_condition == "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE":
            if not partial_boundary:
                raise RunnerError("G07_V2_PAIR_UNDECLARED_NONESTIMABLE_MEMBER")
            if not (unit_root / "checkpoint.current.json").is_file():
                missing.append(unit_id)
                continue
            nonestimable_records.append(dict(
                _reopen_pair_nonestimable_source(context, contract, unit_root)
            ))
            continue
        stage_path = unit_root / "prediction_stage_receipt.json"
        prediction_path = unit_root / "predictions.csv"
        metrics_path = unit_root / "metrics.json"
        issuance_path = _prediction_issuance_checkpoint_path(unit_root)
        if not all(path.is_file() for path in (
            stage_path, prediction_path, metrics_path, issuance_path
        )):
            missing.append(unit_id)
            continue
        prediction, source_record = _reopen_pair_source_prediction(
            context, authenticated, contract, unit_root
        )
        frames[contract.model_role].append(prediction)
        unit_records.append(dict(source_record))
    if missing:
        if local:
            raise RunnerError("G07_V2_PAIR_LOCAL_SOURCE_MISSING")
        return MappingProxyType({
            "status": "STAGED_WAITING_FOR_GOVERNED_PAIR_UNITS",
            "missing_unit_ids": tuple(sorted(missing)),
            "paired_evidence_path": None, "paired_evidence_sha256": None,
        })
    baseline = pd.concat(frames["baseline"], ignore_index=True)
    augmented = pd.concat(frames["augmented"], ignore_index=True)
    source_identity = sha256_bytes(canonical_json({
        "analysis_id": context.contract.analysis_id,
        "model_family": context.contract.model_family,
        "resolution_m": context.contract.resolution_m,
        "support_identity": context.contract.support_identity,
        "response_sha256": context.contract.response_sha256,
        "unit_records": sorted(
            [*unit_records, *nonestimable_records], key=lambda item: item["unit_id"]
        ),
    }))
    common = {
        "analysis_id": context.contract.analysis_id,
        "model_family": context.contract.model_family,
        "resolution_m": context.contract.resolution_m,
        "support_identity": context.contract.support_identity,
        "source_identity": source_identity,
    }
    try:
        if partial_boundary:
            evidence = v2_policy.boundary_partial_benefit_evidence(
                baseline, augmented,
                baseline_identity={**common, "model_role": "baseline"},
                augmented_identity={**common, "model_role": "augmented"},
                source_prediction_records=sorted(unit_records, key=lambda item: item["unit_id"]),
                source_nonestimable_records=sorted(
                    nonestimable_records, key=lambda item: item["unit_id"]
                ),
            )
            v2_policy.validate_boundary_partial_benefit_evidence(
                evidence, baseline=baseline, augmented=augmented
            )
        else:
            evidence = v2_policy.paired_benefit_evidence(
                baseline, augmented,
                baseline_identity={**common, "model_role": "baseline"},
                augmented_identity={**common, "model_role": "augmented"},
                source_prediction_records=sorted(unit_records, key=lambda item: item["unit_id"]),
            )
            v2_policy.validate_paired_evidence(evidence, baseline=baseline, augmented=augmented)
    except v2_policy.PolicyError as exc:
        raise RunnerError(str(exc)) from exc
    group_id = sha256_bytes(canonical_json(common))
    path = output_root / "paired_evidence" / group_id / "paired_benefit_evidence.json"
    payload = canonical_json(dict(evidence)) + b"\n"
    if local and (str(path.resolve()) != scope.proof[1] or
                  sha256_bytes(payload) != scope.proof[2]):
        raise RunnerError("G07_V2_PAIR_LOCAL_RECONSTRUCTION")
    if allow_write:
        _write_or_validate_bytes(path, payload, "G07_V2_PAIR_EVIDENCE_COLLISION")
    elif not path.is_file() or path.read_bytes() != payload:
        raise RunnerError("G07_V2_PAIR_EVIDENCE_RECONSTRUCTION")
    return MappingProxyType({
        "status": "PUBLISHED_AND_VALIDATED",
        "paired_evidence_path": path.relative_to(validation_root).as_posix(),
        "paired_evidence_sha256": sha256_file(path),
        "evidence_sha256": evidence["evidence_sha256"],
    })


def _validate_paired_publication_status(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    run_root: Path,
) -> Mapping[str, object]:
    status_path = run_root / "paired_publication_status.json"
    if not status_path.is_file():
        raise RunnerError("G07_V2_PAIR_STATUS_MISSING")
    observed = json.loads(status_path.read_text(encoding="utf-8"))
    if observed.get("schema_version") != "PAPER1_G07_V2_PAIRED_STATUS_V1":
        raise RunnerError("G07_V2_PAIR_STATUS_SCHEMA")
    reconstructed = dict(_attempt_paired_evidence_publication(
        context, authenticated, allow_write=False
    ))
    if observed != {"schema_version": "PAPER1_G07_V2_PAIRED_STATUS_V1", **reconstructed}:
        raise RunnerError("G07_V2_PAIR_STATUS_RECONSTRUCTION")
    return MappingProxyType(reconstructed)


def _write_postprediction_receipt(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: dict[str, object],
    run_root: Path,
) -> Mapping[str, object]:
    paired = _attempt_paired_evidence_publication(context, authenticated)
    if paired.get("status") == "STAGED_WAITING_FOR_GOVERNED_PAIR_UNITS":
        # Staging remains checkpoint state only. No immutable final-status file is
        # created until the governed dependencies can produce PUBLISHED evidence.
        raise PairDependenciesPending(paired.get("missing_unit_ids", ()))
    prediction_path = Path(str(state["prediction_path"]))
    metrics_path = Path(str(state["metrics_path"]))
    prediction_stage_receipt = run_root / "prediction_stage_receipt.json"
    payload = {
        "schema_version": "PAPER1_G07_V2_POSTPREDICTION_UNIT_RECEIPT_V1",
        "unit_id": context.plan_entry.unit_id,
        "contract_sha256": context.contract.contract_sha256,
        "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
        "input_identity": authenticated.source_manifest_sha256,
        "prediction_sha256": sha256_file(prediction_path),
        "metrics_sha256": sha256_file(metrics_path),
        "prediction_stage_receipt_sha256": sha256_file(prediction_stage_receipt),
        "rf_seed_evidence_sha256": state.get("rf_seed_evidence_sha256"),
        "postprediction_requirements": dict(v2_policy.v2_interface_identity([
            v2_policy.resolve_policy(context.contract)
        ]))["postprediction_requirements"],
    }
    path = run_root / "postprediction_unit_receipt.json"
    _write_or_validate_bytes(path, canonical_json(payload) + b"\n", "G07_V2_POSTPREDICTION_COLLISION")
    state["postprediction_receipt_path"] = str(path)
    state["postprediction_receipt_sha256"] = sha256_file(path)
    paired_status_path = run_root / "paired_publication_status.json"
    _write_or_validate_bytes(
        paired_status_path, canonical_json({
            "schema_version": "PAPER1_G07_V2_PAIRED_STATUS_V1", **dict(paired)
        }) + b"\n",
        "G07_V2_PAIR_STATUS_COLLISION",
    )
    state["paired_publication_status_path"] = str(paired_status_path)
    state["paired_publication_status_sha256"] = sha256_file(paired_status_path)
    return MappingProxyType({**payload, "paired_publication": dict(paired)})


def _build_production_metrics(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    prediction: pd.DataFrame,
    prediction_sha256: str,
) -> Mapping[str, object]:
    frame = authenticated.frame
    contract = context.contract
    configuration = _configuration_for(authenticated.evidence_classification)
    training_index = frame.index[frame.interval_number.isin(contract.training_intervals)]
    heldout_index = frame.index[frame.interval_number.isin(contract.heldout_intervals)]
    metric_frame = prediction.merge(
        frame.loc[heldout_index, [*g06.KEY_FIELDS, "y"]],
        on=list(g06.KEY_FIELDS), validate="one_to_one",
    ).rename(columns={"predicted_probability": "raw_probability_y1"})
    metrics = dict(
        _fractional_metric_payload(metric_frame)
        if contract.model_family == "FRACTIONAL_LOGIT_GLM"
        else _metric_payload(metric_frame, configuration)
    )
    metrics["schema_version"] = "PAPER1_G07_RECONSTRUCTED_METRICS_V1"
    metrics["prediction_artifact_sha256"] = prediction_sha256
    analysis = _analysis_for_contract(context.project_root, contract)
    if analysis is not None and contract.analysis_family.endswith("_CONFIDENCE"):
        stratification = analysis_registry.stratification_contract(analysis)
        field = str(stratification["stratification_field"])
        training_values = pd.to_numeric(frame.loc[training_index, field], errors="coerce")
        if not np.isfinite(training_values).all() or training_values.nunique() < 2:
            raise RunnerError("G07_CONFIDENCE_TRAINING_STRATUM_NONESTIMABLE")
        cutoff = float(training_values.median())
        heldout_confidence = frame.loc[heldout_index, [*g06.KEY_FIELDS, field]]
        stratified = metric_frame.merge(
            heldout_confidence, on=list(g06.KEY_FIELDS), validate="one_to_one"
        )
        stratified["confidence_stratum"] = np.where(
            pd.to_numeric(stratified[field], errors="coerce") <= cutoff,
            "AT_OR_BELOW_MEDIAN_NUMERIC_CONFIDENCE",
            "ABOVE_MEDIAN_NUMERIC_CONFIDENCE",
        )
        metrics["confidence_stratification"] = {
            "field": field, "training_median": cutoff,
            "predictor_use": "PROHIBITED_AS_MODEL_PREDICTOR",
            "records": [
                {
                    "stratum": str(label), "rows": len(group),
                    "log_loss": float(log_loss(
                        group["y"], group["raw_probability_y1"], labels=[0, 1]
                    )),
                    "brier": float(brier_score_loss(
                        group["y"], group["raw_probability_y1"]
                    )),
                }
                for label, group in stratified.groupby("confidence_stratum", sort=True)
            ],
        }
    return MappingProxyType(metrics)


def _write_v2_execution_evidence_manifest(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: dict[str, object],
    run_root: Path,
) -> Path:
    artifacts = {
        "policy_receipt": state["policy_receipt_sha256"],
        "prediction": sha256_file(Path(str(state["prediction_path"]))),
        "metrics": sha256_file(Path(str(state["metrics_path"]))),
        "postprediction_receipt": state["postprediction_receipt_sha256"],
        "paired_publication_status": state["paired_publication_status_sha256"],
        "prediction_stage_receipt": sha256_file(run_root / "prediction_stage_receipt.json"),
    }
    if state.get("rf_seed_evidence_sha256") is not None:
        artifacts["rf_seed_evidence"] = state["rf_seed_evidence_sha256"]
    payload = {
        "schema_version": "PAPER1_G07_V2_EXECUTION_EVIDENCE_MANIFEST_V1",
        "runner_identity": SCHEMA_VERSION,
        "v2_interface": dict(v2_policy.v2_interface_identity([
            v2_policy.resolve_policy(context.contract)
        ])),
        "unit_id": context.plan_entry.unit_id,
        "contract_sha256": context.contract.contract_sha256,
        "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
        "inheritance_authority_sha256": state["identity"]["inheritance_authority_sha256"],
        "input_identity": authenticated.source_manifest_sha256,
        "source_commit": state["source_commit"],
        "selected_hyperparameter": state.get("selected_hyperparameter"),
        "hyperparameter_source": state.get("hyperparameter_source"),
        "artifact_hashes": artifacts,
        "publication_state": "READY_FOR_TERMINAL_AFTER_VALIDATION",
    }
    path = run_root / "v2_execution_evidence_manifest.json"
    _write_or_validate_bytes(path, canonical_json(payload) + b"\n", "G07_V2_EVIDENCE_MANIFEST_COLLISION")
    state["v2_evidence_manifest_path"] = str(path)
    state["v2_evidence_manifest_sha256"] = sha256_file(path)
    return path


def _publication_artifact_paths(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    run_root: Path,
) -> Mapping[str, tuple[Path, str]]:
    artifacts: dict[str, tuple[Path, str]] = {
        "policy_receipt": (
            run_root / "hyperparameter_policy_receipt.json", "PAPER1_G07_V2_POLICY_RECEIPT_V1"
        ),
        "prediction": (
            run_root / "predictions.csv", g06.PREDICTION_ARTIFACT_SCHEMA
        ),
        "prediction_stage_receipt": (
            run_root / "prediction_stage_receipt.json", PREDICTION_STAGE_SCHEMA_VERSION
        ),
        "metrics": (run_root / "metrics.json", "PAPER1_G07_RECONSTRUCTED_METRICS_V1"),
        "postprediction_receipt": (
            run_root / "postprediction_unit_receipt.json",
            "PAPER1_G07_V2_POSTPREDICTION_UNIT_RECEIPT_V1",
        ),
        "paired_publication_status": (
            run_root / "paired_publication_status.json", "PAPER1_G07_V2_PAIRED_STATUS_V1"
        ),
        "v2_execution_evidence_manifest": (
            run_root / "v2_execution_evidence_manifest.json",
            "PAPER1_G07_V2_EXECUTION_EVIDENCE_MANIFEST_V1",
        ),
    }
    if state.get("rf_seed_evidence_sha256") is not None:
        artifacts["rf_seed_evidence"] = (
            run_root / "rf_seed_evidence" / "rf_seed_stability.json",
            "PAPER1_G07_V2_RF_SEED_EVIDENCE_V1",
        )
    paired = _validate_paired_publication_status(context, authenticated, run_root)
    if paired.get("status") == "PUBLISHED_AND_VALIDATED":
        pair_path = Path(authenticated.validation_root) / str(paired["paired_evidence_path"])
        pair_schema = json.loads(pair_path.read_text(encoding="utf-8")).get("schema_version")
        if pair_schema not in {
            v2_policy.EVIDENCE_SCHEMA_VERSION,
            v2_policy.BOUNDARY_PARTIAL_EVIDENCE_SCHEMA_VERSION,
        }:
            raise RunnerError("G07_V2_PUBLICATION_PAIR_SCHEMA")
        artifacts["paired_evidence"] = (
            pair_path, pair_schema,
        )
    return MappingProxyType(artifacts)


def _validate_publication_artifact_content(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    role: str,
    path: Path,
    expected_schema: str,
) -> None:
    """Parse current canonical bytes using the schema governed by artifact role."""
    if not path.is_file():
        raise RunnerError(f"G07_V2_PUBLICATION_CONTENT_MISSING:{role}")
    if role == "prediction":
        try:
            frame = pd.read_csv(path)
        except Exception as exc:
            raise RunnerError("G07_V2_PUBLICATION_PREDICTION_PARSE") from exc
        if tuple(frame.columns) != tuple(g06.PREDICTION_INTEGRITY_COLUMNS):
            raise RunnerError("G07_V2_PUBLICATION_PREDICTION_SCHEMA")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RunnerError(f"G07_V2_PUBLICATION_JSON_PARSE:{role}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != expected_schema:
        raise RunnerError(f"G07_V2_PUBLICATION_ACTUAL_SCHEMA:{role}")
    unit_id = context.plan_entry.unit_id
    contract_sha256 = context.contract.contract_sha256
    identity_requirements: dict[str, tuple[str, object]] = {
        "policy_receipt": ("unit_id", unit_id),
        "prediction_stage_receipt": ("unit_id", unit_id),
        "postprediction_receipt": ("unit_id", unit_id),
        "v2_execution_evidence_manifest": ("unit_id", unit_id),
        "rf_seed_evidence": ("unit_id", unit_id),
    }
    if role in identity_requirements:
        field, value = identity_requirements[role]
        if payload.get("contract_sha256") != contract_sha256:
            producer = _read_evidence_producer(
                context.project_root, context.contract, Path(str(state["run_root"])), path, role
            )
            contract_sha256 = producer.contract_sha256
        contract_matches = payload.get("contract_sha256") == contract_sha256
        if payload.get(field) != value or not contract_matches:
            raise RunnerError(f"G07_V2_PUBLICATION_ACTUAL_IDENTITY:{role}")
    if role == "prediction_stage_receipt":
        receipt = dict(payload)
        observed = receipt.pop("receipt_sha256", None)
        if observed != sha256_bytes(canonical_json(receipt)):
            raise RunnerError("G07_V2_PUBLICATION_STAGE_RECEIPT_HASH")
    elif role == "metrics":
        if (payload.get("prediction_artifact_sha256") !=
                sha256_file(path.parent / "predictions.csv") or
                not isinstance(payload.get("interval_records"), list)):
            raise RunnerError("G07_V2_PUBLICATION_METRICS_CONTENT")
    elif role == "paired_publication_status":
        if payload.get("status") not in {
            "PUBLISHED_AND_VALIDATED", "NOT_APPLICABLE_NO_COMPLETE_FORWARD_PAIR_GROUP"
        }:
            raise RunnerError("G07_V2_PUBLICATION_PAIR_STATUS_CONTENT")
    elif role == "paired_evidence":
        try:
            if payload.get("schema_version") == v2_policy.BOUNDARY_PARTIAL_EVIDENCE_SCHEMA_VERSION:
                v2_policy.validate_boundary_partial_benefit_evidence(payload)
            else:
                v2_policy.validate_paired_evidence(payload)
        except v2_policy.PolicyError as exc:
            raise RunnerError(str(exc)) from exc
    elif role == "rf_seed_evidence":
        try:
            v2_policy.validate_rf_seed_evidence(payload)
        except v2_policy.PolicyError as exc:
            raise RunnerError(str(exc)) from exc


def _publication_records(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    run_root: Path,
) -> Mapping[str, Mapping[str, str]]:
    root = Path(authenticated.validation_root)
    records = {}
    for name, (path, schema) in _publication_artifact_paths(
        context, authenticated, state, run_root
    ).items():
        _validate_publication_artifact_content(
            context, authenticated, state, name, path, schema
        )
        records[name] = _bound_artifact_record(root, path, schema)
    return MappingProxyType(records)


def _validate_preterminal_artifacts(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: Mapping[str, object],
    run_root: Path,
    *,
    require_gate: bool,
) -> Mapping[str, object] | None:
    contract = context.contract
    frame = authenticated.frame
    heldout_index = frame.index[frame.interval_number.isin(contract.heldout_intervals)]
    expected_keys = frame.loc[heldout_index, [*g06.KEY_FIELDS, "interval_number"]]
    stage_path = run_root / "prediction_stage_receipt.json"
    prediction = _validate_prediction_stage_receipt(
        context, authenticated, state, stage_path, expected_keys
    )
    prediction_path = run_root / "predictions.csv"
    metrics_path = run_root / "metrics.json"
    if (Path(str(state.get("prediction_path", ""))).resolve() != prediction_path.resolve() or
            Path(str(state.get("metrics_path", ""))).resolve() != metrics_path.resolve()):
        raise RunnerError("G07_V2_GOVERNED_RUN_ARTIFACT_PATH")
    if sha256_file(prediction_path) != json.loads(
        stage_path.read_text(encoding="utf-8")
    )["prediction_artifact"]["sha256"]:
        raise RunnerError("G07_V2_PRETERMINAL_PREDICTION_HASH")
    if not metrics_path.is_file():
        raise RunnerError("G07_V2_METRICS_MISSING")
    persisted_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    reconstructed_metrics = dict(_build_production_metrics(
        context, authenticated, prediction, sha256_file(prediction_path)
    ))
    if persisted_metrics != reconstructed_metrics:
        raise RunnerError("G07_V2_METRICS_RECONSTRUCTION")
    policy_path = run_root / "hyperparameter_policy_receipt.json"
    policy_receipt = json.loads(policy_path.read_text(encoding="utf-8"))
    policy = v2_policy.resolve_policy(contract)
    policy_contract = contract.contract_sha256
    if policy_receipt.get("contract_sha256") != policy_contract:
        policy_contract = _read_evidence_producer(
            context.project_root, contract, run_root, policy_path, "policy_receipt"
        ).contract_sha256
    if (policy_receipt.get("schema_version") != "PAPER1_G07_V2_POLICY_RECEIPT_V1" or
            policy_receipt.get("unit_id") != context.plan_entry.unit_id or
            policy_receipt.get("contract_sha256") != policy_contract or
            policy_receipt.get("policy_sha256") != policy.policy_sha256 or
            policy_receipt.get("selected_hyperparameter") != state.get("selected_hyperparameter")):
        raise RunnerError("G07_V2_POLICY_RECEIPT_RECONSTRUCTION")
    post_path = run_root / "postprediction_unit_receipt.json"
    post = json.loads(post_path.read_text(encoding="utf-8"))
    post_contract = contract.contract_sha256
    if post.get("contract_sha256") != post_contract:
        post_contract = _read_evidence_producer(
            context.project_root, contract, run_root, post_path, "postprediction_receipt"
        ).contract_sha256
    expected_post = {
        "schema_version": "PAPER1_G07_V2_POSTPREDICTION_UNIT_RECEIPT_V1",
        "unit_id": context.plan_entry.unit_id,
        "contract_sha256": post_contract,
        "policy_sha256": state["identity"]["hyperparameter_policy_sha256"],
        "input_identity": authenticated.source_manifest_sha256,
        "prediction_sha256": sha256_file(prediction_path),
        "metrics_sha256": sha256_file(metrics_path),
        "prediction_stage_receipt_sha256": sha256_file(stage_path),
        "rf_seed_evidence_sha256": state.get("rf_seed_evidence_sha256"),
        "postprediction_requirements": dict(v2_policy.v2_interface_identity([
            policy
        ]))["postprediction_requirements"],
    }
    if canonical_json(post) != canonical_json(expected_post):
        raise RunnerError("G07_V2_POSTPREDICTION_RECONSTRUCTION")
    _validate_paired_publication_status(context, authenticated, run_root)
    if contract.model_family == "RANDOM_FOREST":
        _validate_rf_seed_evidence_from_disk(
            context, authenticated, state, run_root, expected_keys, prediction_path
        )
    evidence_path = run_root / "v2_execution_evidence_manifest.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_contract, evidence_source = contract.contract_sha256, contract.git_head
    if evidence.get("contract_sha256") != evidence_contract:
        producer = _read_evidence_producer(
            context.project_root, contract, run_root, evidence_path,
            "v2_execution_evidence_manifest",
        )
        evidence_contract, evidence_source = producer.contract_sha256, producer.source_commit
    expected_artifact_hashes = {
        "policy_receipt": sha256_file(policy_path),
        "prediction": sha256_file(prediction_path),
        "metrics": sha256_file(metrics_path),
        "postprediction_receipt": sha256_file(post_path),
        "paired_publication_status": sha256_file(run_root / "paired_publication_status.json"),
        "prediction_stage_receipt": sha256_file(stage_path),
    }
    if state.get("rf_seed_evidence_sha256") is not None:
        expected_artifact_hashes["rf_seed_evidence"] = sha256_file(
            run_root / "rf_seed_evidence" / "rf_seed_stability.json"
        )
    if (evidence.get("schema_version") != "PAPER1_G07_V2_EXECUTION_EVIDENCE_MANIFEST_V1" or
            evidence.get("runner_identity") != SCHEMA_VERSION or
            evidence.get("unit_id") != context.plan_entry.unit_id or
            evidence.get("contract_sha256") != evidence_contract or
            evidence.get("policy_sha256") != policy.policy_sha256 or
            evidence.get("input_identity") != authenticated.source_manifest_sha256 or
            evidence.get("source_commit") != evidence_source or
            evidence.get("artifact_hashes") != expected_artifact_hashes or
            evidence.get("publication_state") != "READY_FOR_TERMINAL_AFTER_VALIDATION"):
        raise RunnerError("G07_V2_EXECUTION_EVIDENCE_RECONSTRUCTION")
    if not require_gate:
        return None
    gate_path = run_root / "v2_publication_gate.json"
    if not gate_path.is_file():
        raise RunnerError("G07_V2_PUBLICATION_GATE_MISSING")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    records = _publication_records(context, authenticated, state, run_root)
    required = tuple(records)
    try:
        reconstructed = v2_policy.validate_publication_state(
            gate, artifact_root=Path(authenticated.validation_root),
            required_artifacts=required,
            expected_artifact_records=records,
        )
    except v2_policy.PolicyError as exc:
        raise RunnerError(str(exc)) from exc
    if canonical_json(dict(reconstructed)) != canonical_json(gate):
        raise RunnerError("G07_V2_PUBLICATION_RECONSTRUCTION")
    return MappingProxyType(gate)


def _write_publication_gate(
    context: _DispatchContext,
    authenticated: AuthenticatedExecutionInput,
    state: dict[str, object],
    run_root: Path,
) -> Mapping[str, object]:
    _validate_preterminal_artifacts(
        context, authenticated, state, run_root, require_gate=False
    )
    records = _publication_records(context, authenticated, state, run_root)
    try:
        gate = v2_policy.publication_state(records, required_artifacts=tuple(records))
        v2_policy.validate_publication_state(
            gate, artifact_root=Path(authenticated.validation_root),
            required_artifacts=tuple(records),
            expected_artifact_records=records,
        )
    except v2_policy.PolicyError as exc:
        raise RunnerError(str(exc)) from exc
    path = run_root / "v2_publication_gate.json"
    _write_or_validate_bytes(
        path, canonical_json(dict(gate)) + b"\n", "G07_V2_PUBLICATION_GATE_COLLISION"
    )
    state["publication_gate_path"] = str(path)
    state["publication_gate_sha256"] = sha256_file(path)
    _validate_preterminal_artifacts(
        context, authenticated, state, run_root, require_gate=True
    )
    return gate


def _reconcile_published_pair_siblings_without_refit(context: _DispatchContext) -> int:
    """Resume METRICS_WRITTEN siblings after their paired evidence becomes available."""
    contracts = _paired_group_contracts(context)
    if not contracts:
        return 0
    scope = context.pair_validation_scope
    if scope is None or not scope.active or scope.proof is None:
        raise RunnerError("G07_V2_PAIR_REENTRY_REQUIRES_GLOBAL_VALIDATION")
    entries = {entry.unit_id: entry for entry in build_run_plan(context.project_root)}
    output_root = Path(context.request.output_root).resolve()
    resumed = 0
    for contract in contracts:
        unit_id = _unit_id(contract)
        if unit_id == context.plan_entry.unit_id:
            continue
        run_root = output_root / _v2_run_id(unit_id)
        if not (run_root / "checkpoint.current.json").is_file():
            continue
        sibling_state = _reopen_production_state(run_root, Path(context.project_root))
        phase = sibling_state.get("current_phase")
        if phase == "COMPLETE":
            continue
        if phase != "METRICS_WRITTEN":
            raise RunnerError(f"G07_V2_PAIR_REENTRY_PHASE:{unit_id}:{phase}")
        entry = entries.get(unit_id)
        if entry is None or entry.contract_sha256 != contract.contract_sha256:
            raise RunnerError("G07_V2_PAIR_REENTRY_PLAN")
        request = ProductionExecutionRequest(
            unit_id=unit_id,
            run_id=_v2_run_id(unit_id),
            output_root=output_root,
            resume=True,
        )
        sibling_context = _DispatchContext(
            context.project_root, request, entry, contract,
            context.authorization_receipt, _DISPATCH_CAPABILITY, scope,
        )
        before_fit_count = int(sibling_state.get("model_fit_count", -1))
        result = _run_production_lifecycle(
            sibling_context, str(sibling_state.get("handler_class")),
            reconcile_pair_group=False,
        )
        if result.model_fit_count != before_fit_count:
            raise RunnerError("G07_V2_PAIR_REENTRY_REFIT")
        resumed += 1
    return resumed


def _run_production_lifecycle(
    context: _DispatchContext,
    handler_class: str,
    *,
    reconcile_pair_group: bool = True,
) -> ProductionExecutionResult:
    scope = context.pair_validation_scope
    if scope is not None:
        if reconcile_pair_group or not scope.active or scope.proof is None:
            raise RunnerError("G07_V2_PAIR_INTERNAL_SCOPE_REQUIRED")
        return _run_production_lifecycle_in_scope(
            context, handler_class, reconcile_pair_group=False
        )
    scope = _PairValidationScope()
    context = replace(context, pair_validation_scope=scope)
    try:
        return _run_production_lifecycle_in_scope(
            context, handler_class, reconcile_pair_group=reconcile_pair_group
        )
    finally:
        scope.active = False
        scope.proof = None


def _run_production_lifecycle_in_scope(
    context: _DispatchContext,
    handler_class: str,
    *,
    reconcile_pair_group: bool = True,
) -> ProductionExecutionResult:
    authenticated = _authenticate_execution_input(context)
    configuration = _configuration_for(authenticated.evidence_classification)
    validation_root = Path(authenticated.validation_root)
    output_root = Path(context.request.output_root).resolve()
    try:
        output_root.relative_to(validation_root)
    except ValueError as exc:
        raise RunnerError("G07_OUTPUT_ROOT_OUTSIDE_VALIDATION_ROOT") from exc
    run_root = output_root / context.request.run_id
    identity = _checkpoint_identity(context, authenticated)
    run_root.mkdir(parents=True, exist_ok=True)
    if context.request.resume:
        state = _reopen_production_state(run_root, validation_root)
        if state.get("identity") != identity:
            migration = _validate_governed_resume_identity_migration(
                context,
                authenticated,
                state.get("identity"),
                state.get("source_commit"),
                identity,
            )
            state["resume_identity_migration"] = dict(migration)
            state["identity"] = dict(identity)
            state["source_commit"] = _git_head(context.project_root)
        elif state.get("resume_identity_migration") is not None:
            _validate_persisted_resume_identity_migration(
                context,
                authenticated,
                state.get("resume_identity_migration"),
                identity,
            )
        state["interrupt_after"] = context.request.interrupt_after
        if state.get("current_phase") == "COMPLETE":
            _reconcile_completed_production_run(context, authenticated, state)
            return _result_from_production_state(context, state, True)
    else:
        if (run_root / "checkpoint.current.json").exists():
            raise RunnerError("G07_EXISTING_PRODUCTION_CHECKPOINT_REQUIRES_RESUME")
        state = {
            "schema_version": "PAPER1_G07_PRODUCTION_CHECKPOINT_V1",
            "identity": identity,
            "classification": authenticated.evidence_classification,
            "validation_root": str(validation_root), "run_root": str(run_root),
            "source_commit": _git_head(context.project_root),
            "start_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "completed_phases": [], "checkpoint_records": [], "interrupt_after": context.request.interrupt_after,
            "selected_hyperparameter": None, "hyperparameter_source": "NOT_APPLICABLE",
            "policy_receipt_path": None, "policy_receipt_sha256": None,
            "prediction_stage_receipt_path": None, "prediction_stage_receipt_sha256": None,
            "rf_seed_evidence_path": None, "rf_seed_evidence_sha256": None,
            "postprediction_receipt_path": None, "postprediction_receipt_sha256": None,
            "publication_gate_path": None, "publication_gate_sha256": None,
            "prediction_path": None, "metrics_path": None, "terminal_evidence_path": None,
            "manifest_path": str(run_root / "execution_manifest.json"),
            "terminal_disposition": None, "model_fit_count": 0,
            "handler_class": handler_class,
        }
        _persist_production_checkpoint(run_root, state, "INITIALIZED")
    completed = state["completed_phases"]
    if "INPUTS_VALIDATED" not in completed:
        _persist_production_checkpoint(run_root, state, "INPUTS_VALIDATED")
    disposition = context.plan_entry.disposition
    if disposition is DispatchDisposition.ENVIRONMENT_BLOCKED:
        return _nonexecution_terminal(context, authenticated, state, TerminalDisposition.ENVIRONMENT_BLOCKED)
    if disposition is DispatchDisposition.NONESTIMABLE:
        return _nonexecution_terminal(context, authenticated, state, TerminalDisposition.NONESTIMABLE)
    if disposition is DispatchDisposition.DISABLED:
        return _nonexecution_terminal(context, authenticated, state, TerminalDisposition.DISABLED)
    if disposition is not DispatchDisposition.EXECUTABLE:
        raise RunnerError("G07_UNEXECUTABLE_DISPOSITION")
    frame, contract = authenticated.frame, context.contract
    training_index = frame.index[frame.interval_number.isin(contract.training_intervals)]
    heldout_index = frame.index[frame.interval_number.isin(contract.heldout_intervals)]
    if training_index.empty or heldout_index.empty:
        raise RunnerError("G07_EMPTY_GOVERNED_HISTORY")
    if "TUNING_IN_PROGRESS" not in state["completed_phases"]:
        _persist_production_checkpoint(run_root, state, "TUNING_IN_PROGRESS")
    if "TUNED" not in state["completed_phases"]:
        policy = _governed_policy(context)
        tuning_receipt = None
        if policy.mode is v2_policy.PolicyMode.TUNE:
            receipt = _tune_governed(context, authenticated, run_root)
            tuning_path = run_root / "tuning_receipt.json"
            _write_once(tuning_path, canonical_json(asdict(receipt)) + b"\n")
            state["selected_hyperparameter"] = receipt.selected_hyperparameter
            state["hyperparameter_source"] = "GOVERNED_OUTER_TUNING"
            state["model_fit_count"] += len(receipt.candidates) * len(receipt.splits)
            tuning_receipt = receipt
        elif policy.mode is v2_policy.PolicyMode.FIXED:
            state["selected_hyperparameter"] = float(policy.fixed_value)
            state["hyperparameter_source"] = "GOVERNED_FIXED_POLICY"
        elif policy.mode is v2_policy.PolicyMode.INHERIT:
            inherited = _inheritance_authority(context, policy)
            state["selected_hyperparameter"] = float(inherited["selected_hyperparameter"])
            state["hyperparameter_source"] = "GOVERNED_V2_PARENT_INHERITANCE"
        elif policy.mode is v2_policy.PolicyMode.NO_TUNING:
            state["selected_hyperparameter"] = None
            state["hyperparameter_source"] = "GOVERNED_NO_TUNING"
        else:
            raise RunnerError(f"G07_V2_EXECUTABLE_POLICY_MODE:{policy.mode.value}")
        _write_policy_receipt(
            context, state, run_root, tuning_receipt=tuning_receipt
        )
        _persist_production_checkpoint(run_root, state, "TUNED")
    if "FINAL_MODEL_READY" not in state["completed_phases"]:
        _persist_production_checkpoint(run_root, state, "FINAL_MODEL_READY")
    if context.request.caller_failure is not None:
        return _runtime_failure_terminal(context, authenticated, state, context.request.caller_failure)
    if context.request.injected_failure_stage == "FINAL_MODEL_READY":
        failure = execute_with_failure_provenance(
            lambda: (_ for _ in ()).throw(RuntimeError("controlled synthetic production failure")),
            run_context_identity=context.request.run_id, contract_sha256=contract.contract_sha256,
            stage="FINAL_MODEL_READY", artifact_path=run_root / "runtime_exception.json",
        )
        if not isinstance(failure, RuntimeFailureReceipt):
            raise RunnerError("G07_FAILURE_INJECTION_NOT_CAPTURED")
        return _runtime_failure_terminal(context, authenticated, state, failure)
    output_record: Mapping[str, object]
    prediction_path = run_root / "predictions.csv"
    if "PREDICTION_WRITTEN" not in state["completed_phases"]:
        design = _prepare_governed_design(context, frame, training_index)
        x_train, y_train = _aligned_model_rows(
            frame, design, training_index, "FINAL_TRAINING"
        )
        x_heldout, _ = _aligned_model_rows(
            frame, design, heldout_index, "FINAL_HELDOUT"
        )
        seeds = configuration.rf_seeds if contract.model_family == "RANDOM_FOREST" else (PRIMARY_SEED,)
        predictions: dict[int, np.ndarray] = {}
        for seed in seeds:
            predictions[int(seed)] = _fit_probabilities(
                configuration, contract.model_family, x_train, y_train,
                x_heldout, (
                    None if contract.model_family == "FRACTIONAL_LOGIT_GLM"
                    else float(state["selected_hyperparameter"])
                ), int(seed),
            )
        if contract.model_family == "RANDOM_FOREST":
            _persist_rf_seed_evidence(
                context, authenticated, state, run_root, frame, heldout_index, predictions
            )
            persisted_seed_frames = [
                pd.read_csv(
                    run_root / "rf_seed_evidence" / f"seed_{int(seed)}_predictions.csv"
                )
                for seed in seeds
            ]
            output = persisted_seed_frames[0].loc[:, [
                *g06.KEY_FIELDS, "interval_number"
            ]].copy()
            output["predicted_probability"] = np.mean(np.vstack([
                item["predicted_probability"].to_numpy(dtype=float)
                for item in persisted_seed_frames
            ]), axis=0)
        else:
            probabilities = np.mean(np.vstack([predictions[int(seed)] for seed in seeds]), axis=0)
            output = _prediction_output(frame, heldout_index, probabilities)
        state["model_fit_count"] += len(seeds)
        output_record = _persist_prediction(prediction_path, output)
        state["prediction_path"] = str(prediction_path)
        state["prediction_issuance"] = dict(_prediction_issuance_payload(
            context, authenticated, state, prediction_path, output
        ))
        if contract.model_family == "L2_LOGISTIC" and contract.model_role == "baseline" and contract.analysis_family == "PRIMARY_EVT":
            _persist_governed_benchmark_evidence(
                context, authenticated, state, frame, training_index, heldout_index,
                "TRAINING_PREVALENCE",
            )
            _persist_governed_benchmark_evidence(
                context, authenticated, state, frame, training_index, heldout_index,
                "GEOMETRY_LOGISTIC",
            )
        _persist_production_checkpoint(run_root, state, "PREDICTION_WRITTEN")
    output_record = _reopened_prediction_record(prediction_path)
    expected_keys = frame.loc[heldout_index, [*g06.KEY_FIELDS, "interval_number"]]
    prediction_stage_receipt = run_root / "prediction_stage_receipt.json"
    if not prediction_stage_receipt.exists():
        _write_prediction_stage_receipt(
            context, authenticated, state, run_root, prediction_path, pd.read_csv(prediction_path)
        )
    integrity_frame = _validate_prediction_stage_receipt(
        context, authenticated, state, prediction_stage_receipt, expected_keys
    )
    prediction_sha256 = sha256_file(prediction_path)
    if "METRICS_WRITTEN" not in state["completed_phases"]:
        metrics = dict(_build_production_metrics(
            context, authenticated, integrity_frame, prediction_sha256
        ))
        metrics_path = run_root / "metrics.json"
        _write_once(metrics_path, canonical_json(metrics) + b"\n")
        state["metrics_path"] = str(metrics_path)
        _persist_production_checkpoint(run_root, state, "METRICS_WRITTEN")
    if "POSTPREDICTION_EVIDENCE_WRITTEN" not in state["completed_phases"]:
        _write_postprediction_receipt(context, authenticated, state, run_root)
        _write_v2_execution_evidence_manifest(context, authenticated, state, run_root)
        _persist_production_checkpoint(run_root, state, "POSTPREDICTION_EVIDENCE_WRITTEN")
    if "PUBLICATION_VALIDATED" not in state["completed_phases"]:
        _write_publication_gate(context, authenticated, state, run_root)
        _persist_production_checkpoint(run_root, state, "PUBLICATION_VALIDATED")
    if "TERMINAL_EVIDENCE_WRITTEN" not in state["completed_phases"]:
        terminal = TerminalRecord("PAPER1_G07_TERMINAL_V1", TerminalDisposition.COMPLETE, True, None)
        validate_terminal_record(terminal)
        terminal_path = run_root / "terminal_evidence.json"
        _write_once(terminal_path, canonical_json({**asdict(terminal), "disposition": "COMPLETE"}) + b"\n")
        state["terminal_evidence_path"] = str(terminal_path)
        state["terminal_disposition"] = TerminalDisposition.COMPLETE.value
        _persist_production_checkpoint(run_root, state, "TERMINAL_EVIDENCE_WRITTEN")
    if "COMPLETE" not in state["completed_phases"]:
        _persist_production_checkpoint(run_root, state, "COMPLETE")
    state["end_timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    final_manifest = _write_manifest(
        context, authenticated, state, run_root / "execution_manifest.json",
        terminal_status="COMPLETE", output=output_record,
    )
    state["manifest_path"] = str(final_manifest)
    final = g06.integrity_validate_prediction_artifact(
        validation_root, final_manifest,
        expected_contract_id=contract.contract_sha256, expected_analysis_id=contract.analysis_id,
        expected_model_family=contract.model_family, expected_model_role=contract.model_role,
        expected_outer_evaluation=contract.evaluation_identity,
        expected_evidence_classification=authenticated.evidence_classification,
        expected_heldout_keys=expected_keys,
    )
    if final.artifact_sha256 != prediction_sha256:
        raise RunnerError("G07_FINAL_RECONCILIATION")
    result = _result_from_production_state(context, state, bool(context.request.resume))
    if reconcile_pair_group:
        if context.pair_validation_scope.proof is None:
            _attempt_paired_evidence_publication(context, authenticated, allow_write=False)
        _reconcile_published_pair_siblings_without_refit(context)
    return result


def _sanitize_exception_message(message: str) -> str:
    value = " ".join(str(message).split())[:500]
    value = re.sub(
        r"(?i)(password|token|secret|authorization|cookie)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        value,
    )
    return value


def execute_with_failure_provenance(
    operation: Callable[[], object],
    *,
    run_context_identity: str,
    contract_sha256: str,
    stage: str,
    artifact_path: Path,
) -> object | RuntimeFailureReceipt:
    if stage not in set(CHECKPOINT_STAGES).union(PRODUCTION_PHASES):
        raise RunnerError("G07_FAILURE_STAGE")
    try:
        return operation()
    except Exception as exc:
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        artifact_payload = {
            "schema_version": "PAPER1_G07_RUNTIME_EXCEPTION_ARTIFACT_V1",
            "run_context_identity": run_context_identity,
            "contract_sha256": contract_sha256,
            "stage": stage,
            "exception_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
            "sanitized_message": _sanitize_exception_message(str(exc)),
            "traceback_sha256": sha256_bytes(trace.encode("utf-8")),
        }
        _atomic_json(artifact_path, artifact_payload)
        receipt_payload = {
            **artifact_payload,
            "artifact_path": str(Path(artifact_path)),
            "artifact_sha256": sha256_file(artifact_path),
            "evidence_classification": "TYPED_PERSISTED_EXCEPTION",
        }
        receipt = RuntimeFailureReceipt(
            **receipt_payload, receipt_sha256=sha256_bytes(canonical_json(receipt_payload))
        )
        _atomic_json(Path(artifact_path).with_suffix(".receipt.json"), asdict(receipt))
        return receipt


def validate_runtime_failure_receipt(receipt: RuntimeFailureReceipt) -> None:
    if not isinstance(receipt, RuntimeFailureReceipt):
        raise RunnerError("G07_FAILURE_RECEIPT_TYPE")
    if receipt.evidence_classification != "TYPED_PERSISTED_EXCEPTION":
        raise RunnerError("G07_FAILURE_EVIDENCE_CLASSIFICATION")
    payload = asdict(receipt)
    observed = payload.pop("receipt_sha256")
    if sha256_bytes(canonical_json(payload)) != observed:
        raise RunnerError("G07_FAILURE_RECEIPT_HASH")
    path = Path(receipt.artifact_path)
    if not path.is_file() or sha256_file(path) != receipt.artifact_sha256:
        raise RunnerError("G07_FAILURE_ARTIFACT_IDENTITY")
    artifact = json.loads(path.read_text(encoding="utf-8"))
    expected_artifact = {
        key: getattr(receipt, key)
        for key in (
            "schema_version", "run_context_identity", "contract_sha256", "stage",
            "exception_type", "sanitized_message", "traceback_sha256",
        )
    }
    if artifact != expected_artifact:
        raise RunnerError("G07_FAILURE_ARTIFACT_SEMANTICS")
    persisted_path = path.with_suffix(".receipt.json")
    if not persisted_path.is_file() or json.loads(persisted_path.read_text(encoding="utf-8")) != asdict(receipt):
        raise RunnerError("G07_FAILURE_RECEIPT_NOT_PERSISTED")


def caller_reported_failure(exception_type: str, message: str) -> CallerReportedFailure:
    if not exception_type.strip() or not message.strip():
        raise RunnerError("G07_CALLER_REPORTED_FAILURE_MALFORMED")
    return CallerReportedFailure(
        "PAPER1_G07_CALLER_REPORTED_FAILURE_V1",
        TerminalDisposition.FAILED_RUNTIME,
        "CALLER_REPORTED_UNAUTHENTICATED",
        exception_type.strip(),
        _sanitize_exception_message(message),
    )


def validate_terminal_record(record: TerminalRecord) -> None:
    if not isinstance(record, TerminalRecord):
        raise RunnerError("G07_TERMINAL_RECORD_TYPE")
    if record.disposition is TerminalDisposition.COMPLETE:
        if not record.prediction_available or record.exception_metadata is not None:
            raise RunnerError("G07_TERMINAL_COMPLETE_EVIDENCE")
    elif record.disposition is TerminalDisposition.FAILED_RUNTIME:
        if record.prediction_available or record.exception_metadata is None:
            raise RunnerError("G07_TERMINAL_FAILURE_DISPOSITION")
        if isinstance(record.exception_metadata, RuntimeFailureReceipt):
            validate_runtime_failure_receipt(record.exception_metadata)
        elif not (
            isinstance(record.exception_metadata, CallerReportedFailure)
            and record.exception_metadata.evidence_classification == "CALLER_REPORTED_UNAUTHENTICATED"
            and record.exception_metadata.terminal_disposition is TerminalDisposition.FAILED_RUNTIME
        ):
            raise RunnerError("G07_TERMINAL_FAILURE_METADATA")
    elif record.disposition in {
        TerminalDisposition.ENVIRONMENT_BLOCKED,
        TerminalDisposition.NONESTIMABLE,
        TerminalDisposition.DISABLED,
    }:
        if record.prediction_available or record.exception_metadata is not None:
            raise RunnerError("G07_TERMINAL_NONEXECUTION_EVIDENCE")
    else:
        raise RunnerError("G07_TERMINAL_DISPOSITION")


def _cli_payload(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), sort_keys=True, default=str)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper 1 G07 fail-closed runner")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--list-units", action="store_true")
    parser.add_argument("--unit-id")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-scientific", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--synthetic-run", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--synthetic-resume", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--synthetic-interrupt-after", choices=CHECKPOINT_STAGES, help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.synthetic_run is not None:
        result = run_synthetic_lifecycle(
            arguments.synthetic_run, interrupt_after=arguments.synthetic_interrupt_after
        )
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0
    if arguments.synthetic_resume is not None:
        result = run_synthetic_lifecycle(arguments.synthetic_resume, resume=True)
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0
    if arguments.run_scientific or arguments.resume:
        request = None
        if arguments.unit_id and arguments.output_root:
            request = ProductionExecutionRequest(
                arguments.unit_id, f"G07_{arguments.unit_id.replace('|', '_')}",
                arguments.output_root, resume=arguments.resume,
            )
        result = run_scientific(arguments.project_root, request)
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0
    if arguments.list_units or arguments.unit_id:
        plan = build_run_plan(arguments.project_root)
        if arguments.unit_id:
            matches = [entry for entry in plan if entry.unit_id == arguments.unit_id]
            if len(matches) != 1:
                raise RunnerError("G07_UNKNOWN_GOVERNED_UNIT")
            print(json.dumps(asdict(matches[0]), sort_keys=True, default=str))
        else:
            print(json.dumps([asdict(entry) for entry in plan], sort_keys=True, default=str))
        return 0
    result = dry_run(arguments.project_root)
    print(_cli_payload(result))
    return 0


__all__ = (
    "GATE_VERSION", "SCHEMA_VERSION", "SCIENTIFIC_RF_TREES",
    "SCIENTIFIC_BOOTSTRAP_REPLICATES", "SYNTHETIC_RF_TREES",
    "SYNTHETIC_BOOTSTRAP_REPLICATES", "PRIMARY_SEED", "RF_SEEDS",
    "LOGISTIC_CANDIDATES", "RF_LEAF_CANDIDATES", "GEOMETRY_FIELDS",
    "NO_EARLY_INTERVALS", "PRIMARY_HELDOUT_INTERVALS", "EXPECTED_UNIVERSE",
    "CHECKPOINT_STAGES", "TUNING_SPLITS", "RunnerError", "ControlledInterruption",
    "PairDependenciesPending", "RunnerMode",
    "TerminalDisposition", "DispatchDisposition", "RunnerConfiguration", "DispatchPlanEntry",
    "FacadeCapabilityGap", "GovernedModelSchema", "FACADE_CAPABILITY_GAPS",
    "TuningReceipt", "PersistedArtifactReceipt", "RuntimeFailureReceipt",
    "CallerReportedFailure", "TerminalRecord",
    "SyntheticRunResult", "ProductionExecutionRequest", "AuthenticatedExecutionInput",
    "ProductionExecutionResult", "SCIENTIFIC_CONFIGURATION", "SYNTHETIC_CONFIGURATION",
    "canonical_json", "sha256_bytes", "sha256_file", "validate_configuration",
    "build_run_plan", "dry_run", "resolve_governed_model_schema",
    "require_scientific_authorization",
    "run_scientific", "dispatch_binary_model", "dispatch_confidence_stratified_binary",
    "dispatch_symmetric_temporal_cv", "dispatch_loio_diagnostic",
    "dispatch_fractional_glm", "dispatch_governed_nonestimable",
    "dispatch_authority_blocked",
    "dispatch_machine_disabled", "synthetic_fixture", "tune_synthetic",
    "read_frame_artifact", "write_g06_compatible_synthetic_evidence",
    "write_authenticated_synthetic_input", "PRODUCTION_PHASES",
    "write_synthetic_checkpoint", "read_synthetic_checkpoint", "synthetic_checkpoint_identity",
    "moving_block_bootstrap", "symmetric_temporal_folds", "loio_diagnostic",
    "run_synthetic_symmetric_cv", "run_synthetic_lifecycle", "execute_with_failure_provenance",
    "validate_runtime_failure_receipt", "caller_reported_failure", "validate_terminal_record", "main",
)
