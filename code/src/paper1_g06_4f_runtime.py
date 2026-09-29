"""Descendant-safe benchmark authority for Paper 1 G06.4f.

The original interface preserves the three historically frozen prevalence
contracts. The scoped interface adds first-class contracts for every accepted
baseline-L2 PRIMARY_EVT consumer without changing benchmark science. This
module performs no fitting, prediction, scoring, or outcome inspection.
"""
from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from src import paper1_g06_4e_runtime as _accepted
from src import paper1_g06_2_runtime as _execution_authority


G06_4F_GATE_VERSION = "PAPER1_G06.4f"
PREVALENCE_BENCHMARK_TYPE = "TRAINING_PREVALENCE"
PREVALENCE_RULE = "(training_positive + 0.5) / (training_rows + 1)"
HELDOUT_LABEL_USE = "PROHIBITED"
EXPECTED_CONTRACT_SHA256 = MappingProxyType({
    "B1_TO_B2": "f4f46395207ed015b55b4a2282946f46617a997c37ab97d00b29bf535d4eb7bf",
    "B1_B2_TO_B3": "049abbdbec8eb52f1fb5c4ff69b25c151b61e6974f47776ed17cb63303577e9d",
    "B1_B2_B3_TO_B4": "d9a0fd4fa67da9d8d9c1a4a402ddb9677d70c9427a7965546b8fbfd8633e45ed",
})
EXPECTED_CONTRACT_SET_SHA256 = (
    "3a665d8d42639aee628d3f3bfd376658c79d611016eecf4de7ffca215ca21574"
)
SCOPED_BENCHMARK_GATE_VERSION = "PAPER1_G06.4F_SCOPED_BENCHMARK_AUTHORITY_V1"
SCOPED_BENCHMARK_CONTRACT_COUNT = 54
EXPECTED_SCOPED_CONTRACT_SET_SHA256 = (
    "4a852c0aabc31ce78352f4b516a1c1d9d81ee33435c3a22cf573a0b6c23c8ffc"
)
PRIMARY_EVT_ANALYSIS_FAMILY = "PRIMARY_EVT"
PRIMARY_ANALYSIS_ID = "G05A_01_PRIMARY_EVT_1KM"
NO_EARLY_ANALYSIS_ID = "G05A_03_PRIMARY_EVT_NO_EARLY"
SCOPED_BENCHMARK_TYPES = ("TRAINING_PREVALENCE", "GEOMETRY_LOGISTIC")

BenchmarkContract = _accepted.BenchmarkContract
ContractError = _accepted.ContractError
OUTER_EVALUATIONS = _accepted.OUTER_EVALUATIONS
training_prevalence_probability = _accepted.training_prevalence_probability
reconstruct_training_prevalence = _accepted.reconstruct_training_prevalence
validate_prevalence_claim = _accepted.validate_prevalence_claim


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _accepted_prevalence_authority(root: Path) -> Mapping[str, object]:
    lifecycle = _accepted.g06_4e_lifecycle_authority(root)
    if lifecycle.get("acceptance_state") != "ACCEPTED_DESCENDANT":
        raise ContractError("ERR_G06_4F_G06_4E_NOT_ACCEPTED")
    authority = _accepted._load_authority(root)
    section = authority.get("benchmark_authority")
    if not isinstance(section, dict):
        raise ContractError("ERR_G06_4F_PREVALENCE_AUTHORITY")
    expected = {
        "prevalence_rule": PREVALENCE_RULE,
        "heldout_label_use_for_prevalence": HELDOUT_LABEL_USE,
        "g06_fitting": "PROHIBITED",
    }
    if any(section.get(key) != value for key, value in expected.items()):
        raise ContractError("ERR_G06_4F_PREVALENCE_AUTHORITY")
    return MappingProxyType(dict(section))


def _validate_frozen_contract(contract: BenchmarkContract) -> None:
    evaluation = contract.evaluation_identity
    expected_hash = EXPECTED_CONTRACT_SHA256.get(evaluation)
    if expected_hash is None or evaluation not in OUTER_EVALUATIONS:
        raise ContractError("ERR_G06_4F_PREVALENCE_SCOPE")
    payload = asdict(contract)
    observed_hash = payload.pop("contract_sha256")
    training, heldout = OUTER_EVALUATIONS[evaluation]
    exact = {
        "schema_version": "PAPER1_G06.4_BENCHMARK_CONTRACT_V1",
        "gate_version": "PAPER1_G06.4",
        "benchmark_id": f"PAPER1_TRAINING_PREVALENCE_{evaluation}",
        "benchmark_type": PREVALENCE_BENCHMARK_TYPE,
        "model_family": PREVALENCE_BENCHMARK_TYPE,
        "model_role": "benchmark",
        "scope_identity": "PRIMARY_CONFIRMATORY_1KM_PRIMARY_HYBRID_FORWARD_CHAIN",
        "risk_set_id": "PRIMARY_HYBRID",
        "resolution_m": 1000,
        "evaluation_identity": evaluation,
        "training_intervals": tuple(training),
        "heldout_intervals": tuple(heldout),
        "predictor_fields": (),
        "support_identity": "PRIMARY_CONFIRMATORY",
        "response_field": "y",
        "preprocessing_identity": "NONE; JEFFREYS_SMOOTHED_TRAINING_HISTORY_ONLY",
        "estimator_identity": "NONE_CONSTANT_PROBABILITY",
        "tuning_identity": "NONE; HELDOUT_LABEL_USE_PROHIBITED",
        "prediction_schema_version": "PAPER1_G06.4_BENCHMARK_PREDICTION_V1",
        "receipt_schema_version": "PAPER1_G06.4_BENCHMARK_RECEIPT_V1",
        "execution_universe_relationship": "ORTHOGONAL_BENCHMARK_ROLE_NOT_A_G05_UNIT",
    }
    if any(payload.get(key) != value for key, value in exact.items()):
        raise ContractError("ERR_G06_4F_PREVALENCE_SEMANTICS")
    if observed_hash != expected_hash or _sha256(payload) != expected_hash:
        raise ContractError("ERR_G06_4F_PREVALENCE_IDENTITY")


def governed_prevalence_contracts(
        project_root: Path) -> tuple[BenchmarkContract, ...]:
    """Return the exact three frozen training-prevalence contracts."""
    root = Path(project_root).resolve()
    _accepted_prevalence_authority(root)
    contracts = tuple(
        contract for contract in _accepted._previous._build_benchmark_contracts(root)
        if contract.benchmark_type == PREVALENCE_BENCHMARK_TYPE
    )
    if len(contracts) != len(EXPECTED_CONTRACT_SHA256):
        raise ContractError("ERR_G06_4F_PREVALENCE_COUNT")
    for contract in contracts:
        _validate_frozen_contract(contract)
    pairs = tuple((item.benchmark_id, item.contract_sha256) for item in contracts)
    if _sha256(pairs) != EXPECTED_CONTRACT_SET_SHA256:
        raise ContractError("ERR_G06_4F_PREVALENCE_SET")
    return contracts


def governed_prevalence_contract(
        project_root: Path, outer_evaluation: str) -> BenchmarkContract:
    """Return one frozen prevalence contract for a governed outer evaluation."""
    matches = tuple(
        contract for contract in governed_prevalence_contracts(project_root)
        if contract.evaluation_identity == outer_evaluation
    )
    if len(matches) != 1:
        raise ContractError("ERR_G06_4F_PREVALENCE_CONTRACT")
    return matches[0]


def validate_governed_prevalence_contract(
        project_root: Path, contract: BenchmarkContract) -> None:
    """Reject any object not identical to its governed frozen contract."""
    if not isinstance(contract, BenchmarkContract):
        raise ContractError("ERR_G06_4F_PREVALENCE_CONTRACT_TYPE")
    expected = governed_prevalence_contract(
        project_root, contract.evaluation_identity)
    if contract != expected:
        raise ContractError("ERR_G06_4F_PREVALENCE_CONTRACT_BINDING")


def _ordinary_benchmark_contract(
        project_root: Path, benchmark_type: str,
        evaluation_identity: str) -> BenchmarkContract:
    matches = tuple(
        contract for contract in _accepted._previous._build_benchmark_contracts(
            Path(project_root).resolve())
        if contract.benchmark_type == benchmark_type and
        contract.evaluation_identity == evaluation_identity
    )
    if len(matches) != 1:
        raise ContractError("ERR_G06_4F_ORDINARY_BENCHMARK_CONTRACT")
    contract = matches[0]
    if benchmark_type == PREVALENCE_BENCHMARK_TYPE:
        _validate_frozen_contract(contract)
    else:
        geometry = _accepted.governed_geometry_contract(
            project_root, evaluation_identity)
        _accepted.validate_governed_geometry_contract(project_root, geometry)
        if geometry.benchmark_contract_sha256 != contract.contract_sha256:
            raise ContractError("ERR_G06_4F_ORDINARY_GEOMETRY_IDENTITY")
    return contract


def _benchmark_consuming_execution_contracts(
        project_root: Path) -> tuple[object, ...]:
    contracts = tuple(
        contract for contract in
        _execution_authority.governed_execution_contracts(project_root)
        if contract.execution_enabled and
        contract.analysis_family == PRIMARY_EVT_ANALYSIS_FAMILY and
        contract.model_family == "L2_LOGISTIC" and
        contract.model_role == "baseline"
    )
    if len(contracts) != 27:
        raise ContractError("ERR_G06_4F_SCOPED_EXECUTION_COUNT")
    keys = tuple(
        (contract.analysis_id, contract.risk_set_id, contract.resolution_m,
         contract.evaluation_identity)
        for contract in contracts
    )
    if len(set(keys)) != len(keys):
        raise ContractError("ERR_G06_4F_SCOPED_EXECUTION_DUPLICATE")
    return contracts


def _scoped_benchmark_payload(
        execution_contract: object, benchmark_type: str) -> dict[str, object]:
    if benchmark_type not in SCOPED_BENCHMARK_TYPES:
        raise ContractError("ERR_G06_4F_SCOPED_BENCHMARK_TYPE")
    if benchmark_type == PREVALENCE_BENCHMARK_TYPE:
        fields: tuple[str, ...] = ()
        preprocessing = "NONE; JEFFREYS_SMOOTHED_TRAINING_HISTORY_ONLY"
        estimator = "NONE_CONSTANT_PROBABILITY"
        tuning = "NONE; HELDOUT_LABEL_USE_PROHIBITED"
    else:
        fields = tuple(_accepted.GEOMETRY_BENCHMARK_FIELDS)
        preprocessing = (
            "TRAINING_HISTORY_POPULATION_SD_DDOF0; BOTH_REFERENCE; "
            "FIXED_SCHEMA_INDICATORS; TRAINING_CONSTANT_FIXED_ZERO_COORDINATE"
        )
        estimator = (
            "SKLEARN_LOGISTIC_REGRESSION_L2_LBFGS_INTERCEPT_"
            "NO_CLASS_WEIGHT_MAXITER5000_TOL1E-8"
        )
        tuning = (
            "INHERIT_MATCHING_SCOPE_OUTER_SELECTED_OR_FIXED_C_RECEIPT; "
            "NO_BENCHMARK_RETUNING"
        )
    scope = (
        f"{PRIMARY_EVT_ANALYSIS_FAMILY}|{execution_contract.analysis_id}|"
        f"{execution_contract.risk_set_id}|{execution_contract.resolution_m}M|"
        f"{execution_contract.evaluation_identity}"
    )
    return {
        "schema_version": "PAPER1_G06.4_BENCHMARK_CONTRACT_V1",
        "gate_version": SCOPED_BENCHMARK_GATE_VERSION,
        "benchmark_id": (
            f"PAPER1_{benchmark_type}_{execution_contract.analysis_id}_"
            f"{execution_contract.resolution_m}M_"
            f"{execution_contract.evaluation_identity}"
        ),
        "benchmark_type": benchmark_type,
        "model_family": benchmark_type,
        "model_role": "benchmark",
        "scope_identity": scope,
        "risk_set_id": execution_contract.risk_set_id,
        "resolution_m": execution_contract.resolution_m,
        "evaluation_identity": execution_contract.evaluation_identity,
        "training_intervals": tuple(execution_contract.training_intervals),
        "heldout_intervals": tuple(execution_contract.heldout_intervals),
        "predictor_path": execution_contract.predictor_path,
        "predictor_sha256": execution_contract.predictor_sha256,
        "predictor_key_sha256": execution_contract.predictor_key_sha256,
        "predictor_fields": fields,
        "support_identity": execution_contract.support_identity,
        "support_path": execution_contract.support_path,
        "support_sha256": execution_contract.support_sha256,
        "outcome_path": execution_contract.response_path,
        "outcome_sha256": execution_contract.response_sha256,
        "outcome_key_sha256": execution_contract.response_key_sha256,
        "outcome_key_interval_value_sha256": (
            execution_contract.response_key_interval_value_sha256
        ),
        "response_field": "y",
        "preprocessing_identity": preprocessing,
        "estimator_identity": estimator,
        "tuning_identity": tuning,
        "metric_authority_sha256": execution_contract.metric_authority_sha256,
        "prediction_schema_version": "PAPER1_G06.4_BENCHMARK_PREDICTION_V1",
        "receipt_schema_version": "PAPER1_G06.4_BENCHMARK_RECEIPT_V1",
        "execution_universe_relationship": (
            "ORTHOGONAL_BENCHMARK_ROLE_NOT_A_G05_UNIT"
        ),
    }


@lru_cache(maxsize=4)
def _build_scoped_benchmark_contracts(
        project_root: Path) -> tuple[BenchmarkContract, ...]:
    root = Path(project_root).resolve()
    contracts: list[BenchmarkContract] = []
    for execution_contract in _benchmark_consuming_execution_contracts(root):
        for benchmark_type in SCOPED_BENCHMARK_TYPES:
            if (execution_contract.analysis_id == PRIMARY_ANALYSIS_ID and
                    execution_contract.risk_set_id == "PRIMARY_HYBRID" and
                    execution_contract.resolution_m == 1000):
                contract = _ordinary_benchmark_contract(
                    root, benchmark_type,
                    execution_contract.evaluation_identity)
            else:
                payload = _scoped_benchmark_payload(
                    execution_contract, benchmark_type)
                contract = BenchmarkContract(
                    **payload, contract_sha256=_sha256(payload))
            contracts.append(contract)
    return tuple(sorted(
        contracts,
        key=lambda item: (
            item.benchmark_type, item.benchmark_id, item.evaluation_identity),
    ))


def governed_scoped_benchmark_contracts(
        project_root: Path) -> tuple[BenchmarkContract, ...]:
    """Return scope-exact benchmark contracts for all accepted consumers."""
    contracts = _build_scoped_benchmark_contracts(Path(project_root).resolve())
    if len(contracts) != SCOPED_BENCHMARK_CONTRACT_COUNT:
        raise ContractError("ERR_G06_4F_SCOPED_BENCHMARK_COUNT")
    pairs = tuple((item.benchmark_id, item.contract_sha256) for item in contracts)
    if _sha256(pairs) != EXPECTED_SCOPED_CONTRACT_SET_SHA256:
        raise ContractError("ERR_G06_4F_SCOPED_BENCHMARK_SET")
    for contract in contracts:
        payload = asdict(contract)
        observed_hash = payload.pop("contract_sha256")
        if _sha256(payload) != observed_hash:
            raise ContractError("ERR_G06_4F_SCOPED_BENCHMARK_IDENTITY")
    return contracts


def governed_scoped_benchmark_contract(
        project_root: Path, *, benchmark_type: str, analysis_id: str,
        risk_set_id: str, resolution_m: int,
        evaluation_identity: str) -> BenchmarkContract:
    """Resolve one benchmark by its complete accepted execution scope."""
    matches = tuple(
        contract for contract in governed_scoped_benchmark_contracts(project_root)
        if contract.benchmark_type == benchmark_type and
        contract.risk_set_id == risk_set_id and
        contract.resolution_m == int(resolution_m) and
        contract.evaluation_identity == evaluation_identity and
        (
            analysis_id == PRIMARY_ANALYSIS_ID and
            contract.benchmark_id == f"PAPER1_{benchmark_type}_{evaluation_identity}"
            or contract.benchmark_id.startswith(
                f"PAPER1_{benchmark_type}_{analysis_id}_{int(resolution_m)}M_"
            )
        )
    )
    if len(matches) != 1:
        raise ContractError("ERR_G06_4F_SCOPED_BENCHMARK_CONTRACT")
    return matches[0]


def validate_governed_scoped_benchmark_contract(
        project_root: Path, contract: BenchmarkContract, *, analysis_id: str,
        risk_set_id: str, resolution_m: int,
        evaluation_identity: str, benchmark_type: str) -> None:
    """Reject any contract not identical to the full governed scope."""
    if not isinstance(contract, BenchmarkContract):
        raise ContractError("ERR_G06_4F_SCOPED_BENCHMARK_CONTRACT_TYPE")
    expected = governed_scoped_benchmark_contract(
        project_root, benchmark_type=benchmark_type, analysis_id=analysis_id,
        risk_set_id=risk_set_id, resolution_m=resolution_m,
        evaluation_identity=evaluation_identity)
    if contract != expected:
        raise ContractError("ERR_G06_4F_SCOPED_BENCHMARK_CONTRACT_BINDING")


def reconstruct_scoped_training_prevalence(
        project_root: Path, outcomes: object, contract: BenchmarkContract, *,
        analysis_id: str, expected_source_identity: str):
    """Reconstruct prevalence from the contract's governed history."""
    validate_governed_scoped_benchmark_contract(
        project_root, contract, analysis_id=analysis_id,
        risk_set_id=contract.risk_set_id, resolution_m=contract.resolution_m,
        evaluation_identity=contract.evaluation_identity,
        benchmark_type=PREVALENCE_BENCHMARK_TYPE)
    outcomes = _accepted._revalidate_outcome_set(outcomes)
    if (outcomes.source_identity != expected_source_identity or
            outcomes.risk_set_id != contract.risk_set_id or
            outcomes.resolution_m != contract.resolution_m):
        raise ContractError("ERR_G06_4F_SCOPED_PREVALENCE_SOURCE")
    frame = outcomes.to_frame()
    observed_training = frame.loc[
        frame["interval_number"].isin(contract.training_intervals)]
    observed_heldout = frame.loc[
        frame["interval_number"].isin(contract.heldout_intervals)]
    if observed_training.empty or observed_heldout.empty:
        raise ContractError("ERR_G06_4F_SCOPED_PREVALENCE_HISTORY")
    rows = len(observed_training)
    positives = int(observed_training["y"].sum())
    return _accepted.PrevalenceReconstruction(
        contract.evaluation_identity, tuple(contract.training_intervals),
        tuple(contract.heldout_intervals), rows, positives,
        training_prevalence_probability(positives, rows))


def validate_governed_geometry_selected_c(
        project_root: Path, contract: BenchmarkContract, *, analysis_id: str,
        selected_c: float) -> None:
    """Validate the scoped geometry contract and governed selected C."""
    validate_governed_scoped_benchmark_contract(
        project_root, contract, analysis_id=analysis_id,
        risk_set_id=contract.risk_set_id, resolution_m=contract.resolution_m,
        evaluation_identity=contract.evaluation_identity,
        benchmark_type="GEOMETRY_LOGISTIC")
    if selected_c not in tuple(_accepted.ALLOWED_BASELINE_C):
        raise ContractError("ERR_G06_4F_SCOPED_GEOMETRY_SELECTED_C")
