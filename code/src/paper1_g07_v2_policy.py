"""Frozen policy and evidence contracts for the Paper 1 G07 V2 correction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from types import MappingProxyType, SimpleNamespace
from typing import Mapping, Sequence
import warnings

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning

from src import paper1_pr34_modeling as model_spec


POLICY_SCHEMA_VERSION = "PAPER1_G07_V2_HYPERPARAMETER_POLICY_V1"
EVIDENCE_SCHEMA_VERSION = "PAPER1_G07_V2_POST_PREDICTION_EVIDENCE_V1"
BOUNDARY_PARTIAL_EVIDENCE_SCHEMA_VERSION = "PAPER1_G07_V2_BOUNDARY1000_PARTIAL_PAIRED_EVIDENCE_V1"
PUBLICATION_SCHEMA_VERSION = "PAPER1_G07_V2_PUBLICATION_GATE_V2"
V2_SUITE_RUN_ID = "PAPER1_G07_SCIENTIFIC_V2"
V2_OUTPUT_ROOT_RELATIVE = Path("data/processed/propagation/paper1/g07_scientific_execution_v2")
RF_SEEDS = (20200908, 20200909, 20200910, 20200911, 20200912)
RF_STABILITY_METRICS = ("average_precision", "brier", "log_loss", "roc_auc")
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20200908
KEY_FIELDS = ("event_id", "interval_id", "response_grid_m", "cell_id")
INTERVAL_BLOCK = MappingProxyType({
    6: "B2", 8: "B2", 9: "B2", 10: "B2", 11: "B3", 12: "B3",
    14: "B3", 15: "B3", 16: "B4", 18: "B4", 21: "B4", 22: "B4",
})


class PolicyError(RuntimeError):
    """A fail-closed policy or evidence condition."""


class PolicyMode(str, Enum):
    TUNE = "TUNE"
    FIXED = "FIXED"
    INHERIT = "INHERIT"
    NO_TUNING = "NO_TUNING"
    NO_REFIT = "NO_REFIT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class HyperparameterPolicy:
    schema_version: str
    analysis_id: str
    analysis_family: str
    model_family: str
    model_role: str
    outer_evaluation: str
    resolution_m: int
    risk_set_id: str
    support_identity: str
    mode: PolicyMode
    candidates: tuple[float, ...]
    fixed_value: float | None
    inheritance_parent_unit_id: str | None
    authority_source: tuple[str, ...]
    policy_sha256: str


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixed(model: str) -> float:
    if model == "L2_LOGISTIC":
        return 0.1
    if model == "RANDOM_FOREST":
        return 0.05
    raise PolicyError(f"G07_V2_FIXED_MODEL_FAMILY:{model}")


def _make(contract: object, mode: PolicyMode, *, candidates: Sequence[float] = (),
          fixed: float | None = None, parent: str | None = None,
          authority: Sequence[str]) -> HyperparameterPolicy:
    parent_unit = None if parent is None else "|".join((
        parent, str(contract.model_family), str(contract.model_role),
        str(contract.evaluation_identity), str(int(contract.resolution_m))))
    payload = {
        "schema_version": POLICY_SCHEMA_VERSION, "analysis_id": str(contract.analysis_id),
        "analysis_family": str(contract.analysis_family), "model_family": str(contract.model_family),
        "model_role": str(contract.model_role), "outer_evaluation": str(contract.evaluation_identity),
        "resolution_m": int(contract.resolution_m), "risk_set_id": str(contract.risk_set_id),
        "support_identity": str(contract.support_identity), "mode": mode.value,
        "candidates": tuple(float(x) for x in candidates),
        "fixed_value": None if fixed is None else float(fixed),
        "inheritance_parent_unit_id": parent_unit, "authority_source": tuple(authority),
    }
    return HyperparameterPolicy(**{**payload, "mode": mode},
                                policy_sha256=sha256_bytes(canonical_json(payload)))


def resolve_policy(contract: object) -> HyperparameterPolicy:
    """Resolve one contract from accepted prefit authority; unknown cases halt."""
    aid, family, model = str(contract.analysis_id), str(contract.analysis_family), str(contract.model_family)
    resolution = int(contract.resolution_m)
    common = ("documentation/PAPER1_MODEL_FORMULATION_SPEC.md",
              "documentation/PAPER1_MODEL_TUNING_SPEC.csv",
              "documentation/PAPER1_MODEL_SENSITIVITY_HIERARCHY.csv")
    if not bool(contract.execution_enabled):
        return _make(contract, PolicyMode.NOT_APPLICABLE, authority=common)
    if family == "LEAVE_ONE_INTERVAL_OUT_DIAGNOSTIC" or model == "DIAGNOSTIC_NO_REFIT":
        return _make(contract, PolicyMode.NO_REFIT,
                     authority=("documentation/PAPER1_G03_HYPERPARAMETER_POLICY.csv",))
    if family == "FRACTIONAL_NEWLY_COVERED_RESPONSE" or model == "FRACTIONAL_LOGIT_GLM":
        return _make(contract, PolicyMode.NO_TUNING,
                     authority=("documentation/PAPER1_G03_HYPERPARAMETER_POLICY.csv",))
    if family == "SYMMETRIC_BLOCKED_TEMPORAL_CV":
        return _make(contract, PolicyMode.FIXED, fixed=_fixed(model),
                     authority=("documentation/PAPER1_G03_STATISTICAL_AUTHORITY.md",
                                "documentation/PAPER1_G03_HYPERPARAMETER_POLICY.csv"))
    if family == "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY":
        return _make(contract, PolicyMode.INHERIT, parent="G05A_01_PRIMARY_EVT_1KM",
                     authority=("documentation/PAPER1_G03_STATISTICAL_AUTHORITY.md",
                                "documentation/PAPER1_G03_HYPERPARAMETER_POLICY.csv"))
    if aid == "G05A_01_PRIMARY_EVT_1KM":
        grid = (0.1, 1.0) if model == "L2_LOGISTIC" else (0.02, 0.05)
        return _make(contract, PolicyMode.TUNE, candidates=grid, authority=common)
    if aid in {"G05A_02_PRIMARY_EVT_2KM", "G05A_03_PRIMARY_EVT_NO_EARLY"}:
        return _make(contract, PolicyMode.FIXED, fixed=_fixed(model), authority=common)
    if any(aid.startswith(prefix) for prefix in (
        "G05A_04_ACTIVE_FRONT_ONLY_5KM_", "G05A_05_ACTIVE_FRONT_ONLY_5KM_",
        "G05A_06_PERIMETER_ONLY_2KM_", "G05A_07_PERIMETER_ONLY_2KM_",
        "G05A_08_PERIMETER_ONLY_5KM_", "G05A_09_PERIMETER_ONLY_5KM_")):
        parent = "G05A_01_PRIMARY_EVT_1KM" if resolution == 1000 else "G05A_02_PRIMARY_EVT_2KM"
        return _make(contract, PolicyMode.INHERIT, parent=parent,
                     authority=("documentation/PAPER1_FINAL_MODEL_FAIL_CLOSED_RULES.csv:F22",
                                "documentation/PAPER1_G05A_ANALYSIS_REGISTRY.csv"))
    if family == "REALIZED_WEATHER":
        parent = "G05A_01_PRIMARY_EVT_1KM" if resolution == 1000 else "G05A_02_PRIMARY_EVT_2KM"
        return _make(contract, PolicyMode.INHERIT, parent=parent,
                     authority=("documentation/PAPER1_G04A_REALIZED_WEATHER_AUTHORITY.md:105",
                                "documentation/PAPER1_G04A_DECISION.csv"))
    if aid.startswith("G05A_") and aid.split("_")[1].isdigit() and 10 <= int(aid.split("_")[1]) <= 23:
        grid = (0.1, 1.0) if model == "L2_LOGISTIC" else (0.02, 0.05)
        return _make(contract, PolicyMode.TUNE, candidates=grid,
                     authority=("documentation/PAPER1_MODEL_TUNING_SPEC.csv:T11",
                                "documentation/PAPER1_MASTER_ANALYSIS_REGISTER.csv"))
    raise PolicyError(f"G07_V2_POLICY_UNRESOLVED:{aid}:{family}:{model}")


def validate_policy(policy: HyperparameterPolicy) -> None:
    payload = asdict(policy); payload["mode"] = policy.mode.value
    observed = payload.pop("policy_sha256")
    if observed != sha256_bytes(canonical_json(payload)):
        raise PolicyError("G07_V2_POLICY_HASH")
    if policy.mode is PolicyMode.TUNE:
        expected = (0.1, 1.0) if policy.model_family == "L2_LOGISTIC" else (0.02, 0.05)
        valid = policy.candidates == expected and policy.fixed_value is None and not policy.inheritance_parent_unit_id
    elif policy.mode is PolicyMode.FIXED:
        valid = policy.fixed_value == _fixed(policy.model_family) and not policy.candidates and not policy.inheritance_parent_unit_id
    elif policy.mode is PolicyMode.INHERIT:
        valid = bool(policy.inheritance_parent_unit_id) and not policy.candidates and policy.fixed_value is None
    else:
        valid = not policy.candidates and policy.fixed_value is None and not policy.inheritance_parent_unit_id
    if not valid:
        raise PolicyError(f"G07_V2_POLICY_SHAPE:{policy.mode.value}")
    proxy = SimpleNamespace(
        analysis_id=policy.analysis_id, analysis_family=policy.analysis_family,
        model_family=policy.model_family, model_role=policy.model_role,
        evaluation_identity=policy.outer_evaluation, resolution_m=policy.resolution_m,
        risk_set_id=policy.risk_set_id, support_identity=policy.support_identity,
        execution_enabled=policy.mode is not PolicyMode.NOT_APPLICABLE,
    )
    expected = resolve_policy(proxy)
    if policy != expected:
        raise PolicyError("G07_V2_POLICY_AUTHORITY_MISMATCH")


def policy_aggregate_sha256(policies: Sequence[HyperparameterPolicy]) -> str:
    hashes = sorted(policy.policy_sha256 for policy in policies)
    if len(hashes) != len(set(hashes)):
        raise PolicyError("G07_V2_DUPLICATE_POLICY_IDENTITY")
    return sha256_bytes(canonical_json(hashes))


def validate_checkpoint_policy(identity: Mapping[str, object], policy: HyperparameterPolicy) -> None:
    validate_policy(policy)
    if identity.get("policy_schema_version") != POLICY_SCHEMA_VERSION:
        raise PolicyError("G07_V2_CHECKPOINT_POLICY_SCHEMA")
    if identity.get("hyperparameter_policy_sha256") != policy.policy_sha256:
        raise PolicyError("G07_V2_CHECKPOINT_POLICY_HASH")


def validate_inheritance_claim(
    child_policy: HyperparameterPolicy,
    *,
    parent_unit_id: str,
    parent_policy_sha256: str,
    parent_checkpoint_sha256: str,
    parent_manifest_sha256: str,
    selected_hyperparameter: float,
) -> Mapping[str, object]:
    """Bind an INHERIT decision to immutable completed-parent evidence."""
    validate_policy(child_policy)
    if child_policy.mode is not PolicyMode.INHERIT:
        raise PolicyError("G07_V2_INHERIT_MODE")
    if parent_unit_id != child_policy.inheritance_parent_unit_id:
        raise PolicyError("G07_V2_INHERIT_PARENT")
    for name, value in (
        ("parent_policy_sha256", parent_policy_sha256),
        ("parent_checkpoint_sha256", parent_checkpoint_sha256),
        ("parent_manifest_sha256", parent_manifest_sha256),
    ):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise PolicyError(f"G07_V2_INHERIT_IDENTITY:{name}")
    if not math.isfinite(float(selected_hyperparameter)):
        raise PolicyError("G07_V2_INHERIT_VALUE")
    payload = {
        "schema_version": "PAPER1_G07_V2_INHERITANCE_AUTHORITY_V1",
        "child_policy_sha256": child_policy.policy_sha256,
        "parent_unit_id": parent_unit_id,
        "parent_policy_sha256": parent_policy_sha256,
        "parent_checkpoint_sha256": parent_checkpoint_sha256,
        "parent_manifest_sha256": parent_manifest_sha256,
        "selected_hyperparameter": float(selected_hyperparameter),
    }
    return MappingProxyType({**payload, "authority_sha256": sha256_bytes(canonical_json(payload))})


def guarded_logistic_fit(estimator: object, x: object, y: object) -> object:
    """Reject sklearn optimizer nonconvergence while tolerating FutureWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fitted = estimator.fit(x, y)
    if any(issubclass(item.category, ConvergenceWarning) for item in caught):
        raise PolicyError("G07_V2_LOGISTIC_NONCONVERGENCE_WARNING")
    coef = np.asarray(getattr(fitted, "coef_", []), dtype=float)
    intercept = np.asarray(getattr(fitted, "intercept_", []), dtype=float)
    if coef.size == 0 or intercept.size == 0 or not np.isfinite(coef).all() or not np.isfinite(intercept).all():
        raise PolicyError("G07_V2_LOGISTIC_INVALID_COEFFICIENTS")
    return fitted


def rf_seed_stability(seed_metrics: Mapping[int, Mapping[str, float | str]]) -> Mapping[str, object]:
    if tuple(sorted(seed_metrics)) != RF_SEEDS:
        raise PolicyError("G07_V2_RF_SEED_SET")
    expected_names = set(RF_STABILITY_METRICS)
    if any(set(values) != expected_names for values in seed_metrics.values()):
        raise PolicyError("G07_V2_RF_METRIC_SET")
    names = expected_names
    summaries = {}
    for name in sorted(names):
        supplied = tuple(seed_metrics[seed][name] for seed in RF_SEEDS)
        if all(value == "NOT_DEFINED" for value in supplied):
            summaries[name] = {
                "raw_per_seed_values": tuple((seed, "NOT_DEFINED") for seed in RF_SEEDS),
                "mean": "NOT_DEFINED", "minimum": "NOT_DEFINED", "maximum": "NOT_DEFINED",
                "range": "NOT_DEFINED", "population_sd": "NOT_DEFINED",
                "reason": "HELDOUT_UNIT_SINGLE_CLASS", "denominator": 5, "ddof": 0,
                "convention": "POPULATION_SD_DDOF0_COMPLETE_GOVERNED_ENSEMBLE",
            }
            continue
        if any(isinstance(value, str) for value in supplied):
            raise PolicyError(f"G07_V2_RF_METRIC_ELIGIBILITY:{name}")
        raw = tuple((seed, float(seed_metrics[seed][name])) for seed in RF_SEEDS)
        values = np.asarray([value for _, value in raw], dtype=float)
        if not np.isfinite(values).all():
            raise PolicyError(f"G07_V2_RF_METRIC_NONFINITE:{name}")
        summaries[name] = {"raw_per_seed_values": raw, "mean": float(values.mean()),
                           "minimum": float(values.min()), "maximum": float(values.max()),
                           "range": float(values.max()-values.min()),
                           "population_sd": float(values.std(ddof=0)), "denominator": 5,
                           "ddof": 0, "convention": "POPULATION_SD_DDOF0_COMPLETE_GOVERNED_ENSEMBLE"}
    return MappingProxyType({"schema_version": "PAPER1_G07_V2_RF_SEED_STABILITY_V1",
                             "seeds": RF_SEEDS, "summaries": summaries})


def validate_rf_seed_evidence(evidence: Mapping[str, object]) -> None:
    if evidence.get("schema_version") != "PAPER1_G07_V2_RF_SEED_EVIDENCE_V1":
        raise PolicyError("G07_V2_RF_EVIDENCE_SCHEMA")
    records = evidence.get("seed_records")
    if not isinstance(records, list) or tuple(record.get("seed") for record in records) != RF_SEEDS:
        raise PolicyError("G07_V2_RF_EVIDENCE_SEED_RECORDS")
    if len({record.get("seed") for record in records}) != len(RF_SEEDS):
        raise PolicyError("G07_V2_RF_EVIDENCE_DUPLICATE_SEED")
    if evidence.get("seeds") != list(RF_SEEDS):
        raise PolicyError("G07_V2_RF_EVIDENCE_SEED_IDENTITY")
    if evidence.get("principal_prediction_rule") != "ARITHMETIC_MEAN_OF_FIVE_SEED_PROBABILITIES":
        raise PolicyError("G07_V2_RF_EVIDENCE_AVERAGING_RULE")
    metrics = {int(record["seed"]): record.get("metrics", {}) for record in records}
    expected = json.loads(canonical_json(dict(rf_seed_stability(metrics))))
    if json.loads(canonical_json(evidence.get("stability"))) != expected:
        raise PolicyError("G07_V2_RF_EVIDENCE_STABILITY")


def _interval_scores(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for interval, group in frame.groupby("interval_number", sort=True):
        y = group["y"].to_numpy(float); p = group["predicted_probability"].to_numpy(float)
        if int(interval) not in INTERVAL_BLOCK or not np.isfinite(p).all() or ((p < 0)|(p > 1)).any():
            raise PolicyError("G07_V2_PAIRED_VALUE_OR_INTERVAL")
        clipped = np.clip(p, 1e-15, 1-1e-15)
        rows.append({"interval_number": int(interval), "block": INTERVAL_BLOCK[int(interval)],
                     "log_loss": float(np.mean(-(y*np.log(clipped)+(1-y)*np.log(1-clipped)))),
                     "brier": float(np.mean((y-p)**2))})
    return pd.DataFrame(rows)


@lru_cache(maxsize=64)
def _bootstrap_reconstruction(
    deltas: tuple[float, ...], block_length: int, replicates: int, seed: int,
) -> Mapping[str, object]:
    draws = model_spec.moving_block_bootstrap(
        np.asarray(deltas, dtype=float), block_length, replicates, seed
    )
    return MappingProxyType({
        "block_length": block_length, "replicates": replicates, "seed": seed,
        "target_interval_sequence": tuple(INTERVAL_BLOCK),
        "median": float(np.median(draws)), "q025": float(np.quantile(draws, .025)),
        "q975": float(np.quantile(draws, .975)),
        "draws_sha256": sha256_bytes(np.asarray(draws, dtype="<f8").tobytes()),
    })


def paired_benefit_evidence(baseline: pd.DataFrame, augmented: pd.DataFrame, *,
                            baseline_identity: Mapping[str, object], augmented_identity: Mapping[str, object],
                            source_prediction_records: Sequence[Mapping[str, object]] = (),
                            bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
                            bootstrap_seed: int = BOOTSTRAP_SEED) -> Mapping[str, object]:
    if bootstrap_replicates != BOOTSTRAP_REPLICATES or bootstrap_seed != BOOTSTRAP_SEED:
        raise PolicyError("G07_V2_BOOTSTRAP_AUTHORITY")
    for field in ("analysis_id", "model_family", "resolution_m", "support_identity", "source_identity"):
        if baseline_identity.get(field) != augmented_identity.get(field):
            raise PolicyError(f"G07_V2_PAIR_IDENTITY:{field}")
    if baseline_identity.get("model_role") != "baseline" or augmented_identity.get("model_role") != "augmented":
        raise PolicyError("G07_V2_PAIR_ROLE")
    keys = [*KEY_FIELDS, "interval_number"]; required = [*keys, "y", "predicted_probability"]
    for frame in (baseline, augmented):
        if not set(required).issubset(frame) or frame[keys].duplicated().any():
            raise PolicyError("G07_V2_PAIR_SCHEMA_OR_DUPLICATE")
    left = baseline.sort_values(keys, kind="mergesort").reset_index(drop=True)
    right = augmented.sort_values(keys, kind="mergesort").reset_index(drop=True)
    if not left[keys+["y"]].equals(right[keys+["y"]]):
        raise PolicyError("G07_V2_PAIR_KEY_OR_RESPONSE_MISMATCH")
    scores = _interval_scores(left).merge(_interval_scores(right), on=["interval_number", "block"],
                                          suffixes=("_baseline", "_augmented"), validate="one_to_one")
    for metric in ("log_loss", "brier"):
        scores[f"{metric}_benefit"] = scores[f"{metric}_baseline"] - scores[f"{metric}_augmented"]
    blocks = [{"block": block, **{f"{metric}_benefit": float(group[f"{metric}_benefit"].mean())
                                  for metric in ("log_loss", "brier")}}
              for block, group in scores.groupby("block", sort=True)]
    if tuple(row["block"] for row in blocks) != ("B2", "B3", "B4"):
        raise PolicyError("G07_V2_PAIR_REQUIRED_BLOCKS")
    aggregate = {f"{metric}_benefit": float(np.mean([row[f"{metric}_benefit"] for row in blocks]))
                 for metric in ("log_loss", "brier")}
    order = {interval: index for index, interval in enumerate(INTERVAL_BLOCK)}
    ordered = scores.sort_values("interval_number", key=lambda s: s.map(order)); bootstrap = {}
    for metric in ("log_loss", "brier"):
        deltas = tuple(float(value) for value in ordered[f"{metric}_benefit"])
        for length in (2, 3):
            bootstrap[f"{metric}_L{length}"] = dict(_bootstrap_reconstruction(
                deltas, length, bootstrap_replicates, bootstrap_seed
            ))
    payload = {"schema_version": EVIDENCE_SCHEMA_VERSION,
               "baseline_identity": dict(baseline_identity), "augmented_identity": dict(augmented_identity),
               "source_prediction_records": [dict(item) for item in source_prediction_records],
               "paired_key_sha256": sha256_bytes(left[keys].to_csv(index=False, lineterminator="\n").encode()),
               "interval_records": scores.to_dict(orient="records"), "block_records": blocks,
               "equal_weight_b2_b3_b4": aggregate, "moving_block_bootstrap": bootstrap,
               "row_weighting": "PROHIBITED"}
    return MappingProxyType({**payload, "evidence_sha256": sha256_bytes(canonical_json(payload))})


def _require_exact_number(observed: object, expected: float, marker: str) -> None:
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        raise PolicyError(marker)
    if not math.isfinite(float(observed)) or float(observed) != float(expected):
        raise PolicyError(marker)


def validate_paired_evidence(
    evidence: Mapping[str, object], *,
    baseline: pd.DataFrame | None = None,
    augmented: pd.DataFrame | None = None,
) -> None:
    """Reconstruct every paired and bootstrap claim, optionally from source rows."""
    payload = dict(evidence)
    observed = payload.pop("evidence_sha256", None)
    if observed != sha256_bytes(canonical_json(payload)):
        raise PolicyError("G07_V2_EVIDENCE_HASH")
    if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise PolicyError("G07_V2_EVIDENCE_SCHEMA")
    if payload.get("row_weighting") != "PROHIBITED":
        raise PolicyError("G07_V2_EVIDENCE_WEIGHTING")
    source_records = payload.get("source_prediction_records")
    if not isinstance(source_records, list) or any(not isinstance(item, dict) for item in source_records):
        raise PolicyError("G07_V2_EVIDENCE_SOURCE_RECORDS")
    intervals = payload.get("interval_records")
    if not isinstance(intervals, list) or tuple(
        item.get("interval_number") for item in intervals if isinstance(item, dict)
    ) != tuple(INTERVAL_BLOCK):
        raise PolicyError("G07_V2_EVIDENCE_INTERVALS")
    expected_interval_fields = {
        "interval_number", "block", "log_loss_baseline", "brier_baseline",
        "log_loss_augmented", "brier_augmented", "log_loss_benefit", "brier_benefit",
    }
    for item in intervals:
        if set(item) != expected_interval_fields:
            raise PolicyError("G07_V2_EVIDENCE_INTERVAL_FIELDS")
        interval = int(item["interval_number"])
        if item["block"] != INTERVAL_BLOCK[interval]:
            raise PolicyError("G07_V2_EVIDENCE_INTERVAL_BLOCK")
        for metric in ("log_loss", "brier"):
            expected = float(item[f"{metric}_baseline"]) - float(item[f"{metric}_augmented"])
            _require_exact_number(item[f"{metric}_benefit"], expected,
                                  "G07_V2_EVIDENCE_INTERVAL_BENEFIT")
    blocks = payload.get("block_records")
    if not isinstance(blocks, list) or tuple(item.get("block") for item in blocks) != ("B2", "B3", "B4"):
        raise PolicyError("G07_V2_EVIDENCE_BLOCKS")
    for block in blocks:
        if set(block) != {"block", "log_loss_benefit", "brier_benefit"}:
            raise PolicyError("G07_V2_EVIDENCE_BLOCK_FIELDS")
        records = [item for item in intervals if item["block"] == block["block"]]
        if len(records) != 4:
            raise PolicyError("G07_V2_EVIDENCE_BLOCK_INTERVALS")
        for metric in ("log_loss", "brier"):
            expected = float(np.mean([item[f"{metric}_benefit"] for item in records]))
            _require_exact_number(block[f"{metric}_benefit"], expected,
                                  "G07_V2_EVIDENCE_BLOCK_BENEFIT")
    aggregate = payload.get("equal_weight_b2_b3_b4")
    if not isinstance(aggregate, dict) or set(aggregate) != {"log_loss_benefit", "brier_benefit"}:
        raise PolicyError("G07_V2_EVIDENCE_AGGREGATE_FIELDS")
    for metric in ("log_loss", "brier"):
        expected = float(np.mean([item[f"{metric}_benefit"] for item in blocks]))
        _require_exact_number(aggregate[f"{metric}_benefit"], expected,
                              "G07_V2_EVIDENCE_AGGREGATE")
    bootstrap = payload.get("moving_block_bootstrap", {})
    if set(bootstrap) != {"log_loss_L2", "log_loss_L3", "brier_L2", "brier_L3"}:
        raise PolicyError("G07_V2_EVIDENCE_BOOTSTRAP_SET")
    for key, record in bootstrap.items():
        expected_length = int(key[-1])
        if not isinstance(record, dict) or set(record) != {
            "block_length", "replicates", "seed", "target_interval_sequence",
            "median", "q025", "q975", "draws_sha256"
        } or (record.get("block_length") != expected_length or
              record.get("replicates") != BOOTSTRAP_REPLICATES or
              record.get("seed") != BOOTSTRAP_SEED or
              tuple(record.get("target_interval_sequence", ())) != tuple(INTERVAL_BLOCK)):
            raise PolicyError("G07_V2_EVIDENCE_BOOTSTRAP_AUTHORITY")
        metric = key.rsplit("_", 1)[0]
        deltas = tuple(float(item[f"{metric}_benefit"]) for item in intervals)
        reconstructed_bootstrap = _bootstrap_reconstruction(
            deltas, expected_length, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED
        )
        for name in ("median", "q025", "q975"):
            expected = float(reconstructed_bootstrap[name])
            _require_exact_number(record[name], expected, "G07_V2_EVIDENCE_BOOTSTRAP_VALUE")
        if record["draws_sha256"] != reconstructed_bootstrap["draws_sha256"]:
            raise PolicyError("G07_V2_EVIDENCE_BOOTSTRAP_DRAWS")
    if (baseline is None) != (augmented is None):
        raise PolicyError("G07_V2_EVIDENCE_SOURCE_PAIR_REQUIRED")
    if baseline is not None and augmented is not None:
        reconstructed = paired_benefit_evidence(
            baseline, augmented,
            baseline_identity=payload.get("baseline_identity", {}),
            augmented_identity=payload.get("augmented_identity", {}),
            source_prediction_records=source_records,
        )
        if canonical_json(dict(reconstructed)) != canonical_json(dict(evidence)):
            raise PolicyError("G07_V2_EVIDENCE_SOURCE_RECONSTRUCTION")


def boundary_partial_benefit_evidence(
    baseline: pd.DataFrame, augmented: pd.DataFrame, *,
    baseline_identity: Mapping[str, object], augmented_identity: Mapping[str, object],
    source_prediction_records: Sequence[Mapping[str, object]],
    source_nonestimable_records: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    """Report B3/B4 while leaving the prespecified B2/B3/B4 result nonestimable."""
    if (baseline_identity.get("analysis_id") != "G05B_BOUNDARY_1000"
            or baseline_identity.get("model_family") != "L2_LOGISTIC"
            or baseline_identity.get("resolution_m") != 1000):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_SCOPE")
    for field in ("analysis_id", "model_family", "resolution_m", "support_identity", "source_identity"):
        if baseline_identity.get(field) != augmented_identity.get(field):
            raise PolicyError(f"G07_V2_BOUNDARY_PARTIAL_IDENTITY:{field}")
    if baseline_identity.get("model_role") != "baseline" or augmented_identity.get("model_role") != "augmented":
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_ROLE")
    keys = [*KEY_FIELDS, "interval_number"]
    required = [*keys, "y", "predicted_probability"]
    for frame in (baseline, augmented):
        if not set(required).issubset(frame) or frame[keys].duplicated().any():
            raise PolicyError("G07_V2_BOUNDARY_PARTIAL_SCHEMA_OR_DUPLICATE")
    left = baseline.sort_values(keys, kind="mergesort").reset_index(drop=True)
    right = augmented.sort_values(keys, kind="mergesort").reset_index(drop=True)
    if not left[keys + ["y"]].equals(right[keys + ["y"]]):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_KEY_OR_RESPONSE_MISMATCH")
    scores = _interval_scores(left).merge(_interval_scores(right), on=["interval_number", "block"],
                                           suffixes=("_baseline", "_augmented"), validate="one_to_one")
    if tuple(sorted(scores["block"].unique())) != ("B3", "B4"):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_REQUIRED_BLOCKS")
    for metric in ("log_loss", "brier"):
        scores[f"{metric}_benefit"] = scores[f"{metric}_baseline"] - scores[f"{metric}_augmented"]
    blocks = [{"block": block, **{f"{metric}_benefit": float(group[f"{metric}_benefit"].mean())
                                   for metric in ("log_loss", "brier")}}
              for block, group in scores.groupby("block", sort=True)]
    nonestimable = [dict(item) for item in source_nonestimable_records]
    if {(item.get("model_role"), item.get("evaluation")) for item in nonestimable} != {
            ("baseline", "B1_TO_B2"), ("augmented", "B1_TO_B2")}:
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_NONESTIMABLE_SET")
    payload = {
        "schema_version": BOUNDARY_PARTIAL_EVIDENCE_SCHEMA_VERSION,
        "reporting_classification": "PARTIAL_BOUNDARY_SENSITIVITY_EVIDENCE",
        "baseline_identity": dict(baseline_identity), "augmented_identity": dict(augmented_identity),
        "source_prediction_records": [dict(item) for item in source_prediction_records],
        "source_nonestimable_records": nonestimable,
        "paired_key_sha256": sha256_bytes(left[keys].to_csv(index=False, lineterminator="\n").encode()),
        "interval_records": scores.to_dict(orient="records"), "block_records": blocks,
        "equal_weight_b2_b3_b4": {
            "status": "NOT_ESTIMABLE",
            "reason": "B2_PAIR_GOVERNED_NONESTIMABLE_SINGLE_CLASS_B1_TRAINING",
            "log_loss_benefit": None, "brier_benefit": None,
        },
        "moving_block_bootstrap": {
            "status": "NOT_ESTIMABLE", "reason": "FULL_B2_B3_B4_INTERVAL_SEQUENCE_UNAVAILABLE",
            "interval": None,
        },
        "full_period_pooled_diagnostics": {"status": "NOT_ESTIMABLE", "reason": "B2_PAIR_UNAVAILABLE"},
        "row_weighting": "PROHIBITED",
    }
    return MappingProxyType({**payload, "evidence_sha256": sha256_bytes(canonical_json(payload))})


def validate_boundary_partial_benefit_evidence(
    evidence: Mapping[str, object], *, baseline: pd.DataFrame | None = None,
    augmented: pd.DataFrame | None = None,
) -> None:
    payload = dict(evidence); observed = payload.pop("evidence_sha256", None)
    if observed != sha256_bytes(canonical_json(payload)):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_HASH")
    if (payload.get("schema_version") != BOUNDARY_PARTIAL_EVIDENCE_SCHEMA_VERSION
            or payload.get("reporting_classification") != "PARTIAL_BOUNDARY_SENSITIVITY_EVIDENCE"
            or payload.get("row_weighting") != "PROHIBITED"):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_SCHEMA")
    identity_fields = {
        "analysis_id", "model_family", "resolution_m", "support_identity",
        "source_identity", "model_role",
    }
    baseline_identity = payload.get("baseline_identity")
    augmented_identity = payload.get("augmented_identity")
    if (not isinstance(baseline_identity, dict)
            or not isinstance(augmented_identity, dict)
            or set(baseline_identity) != identity_fields
            or set(augmented_identity) != identity_fields):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_IDENTITY_SCHEMA")
    expected_common = {
        "analysis_id": "G05B_BOUNDARY_1000",
        "model_family": "L2_LOGISTIC",
        "resolution_m": 1000,
    }
    if (any(baseline_identity.get(field) != value for field, value in expected_common.items())
            or {field: value for field, value in baseline_identity.items() if field != "model_role"}
            != {field: value for field, value in augmented_identity.items() if field != "model_role"}
            or baseline_identity.get("model_role") != "baseline"
            or augmented_identity.get("model_role") != "augmented"):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_IDENTITY")
    intervals, blocks = payload.get("interval_records"), payload.get("block_records")
    if (not isinstance(intervals, list) or len(intervals) != 8
            or tuple(item.get("block") for item in blocks or ()) != ("B3", "B4")):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_BLOCKS")
    expected_intervals = {
        (11, "B3"), (12, "B3"), (14, "B3"), (15, "B3"),
        (16, "B4"), (18, "B4"), (21, "B4"), (22, "B4"),
    }
    if {(item.get("interval_number"), item.get("block")) for item in intervals} != expected_intervals:
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_INTERVAL_MEMBERSHIP")
    for block in blocks:
        source = [item for item in intervals if item.get("block") == block.get("block")]
        for metric in ("log_loss", "brier"):
            expected = sum(float(item[f"{metric}_benefit"]) for item in source) / len(source)
            _require_exact_number(
                block.get(f"{metric}_benefit"), expected,
                "G07_V2_BOUNDARY_PARTIAL_BLOCK_VALUE",
            )
    if payload.get("equal_weight_b2_b3_b4") != {
            "status": "NOT_ESTIMABLE",
            "reason": "B2_PAIR_GOVERNED_NONESTIMABLE_SINGLE_CLASS_B1_TRAINING",
            "log_loss_benefit": None, "brier_benefit": None}:
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_AGGREGATE")
    if payload.get("moving_block_bootstrap") != {
            "status": "NOT_ESTIMABLE", "reason": "FULL_B2_B3_B4_INTERVAL_SEQUENCE_UNAVAILABLE",
            "interval": None}:
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_BOOTSTRAP")
    nonestimable = payload.get("source_nonestimable_records")
    expected_nonestimable = {
        f"G05B_BOUNDARY_1000|L2_LOGISTIC|{role}|B1_TO_B2|1000": role
        for role in ("baseline", "augmented")
    }
    if (not isinstance(nonestimable, list) or len(nonestimable) != 2
            or {item.get("unit_id") for item in nonestimable} != set(expected_nonestimable)
            or any(
                item.get("model_role") != expected_nonestimable.get(item.get("unit_id"))
                or item.get("evaluation") != "B1_TO_B2"
                or item.get("special_condition") != "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE"
                or item.get("terminal_disposition") != "NONESTIMABLE"
                for item in nonestimable
            )):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_NONESTIMABLE_SET")
    prediction_records = payload.get("source_prediction_records")
    expected_prediction_units = {
        f"G05B_BOUNDARY_1000|L2_LOGISTIC|{role}|{evaluation}|1000": (role, evaluation)
        for role in ("baseline", "augmented")
        for evaluation in ("B1_B2_TO_B3", "B1_B2_B3_TO_B4")
    }
    if (not isinstance(prediction_records, list) or len(prediction_records) != 4
            or {item.get("unit_id") for item in prediction_records} != set(expected_prediction_units)
            or any(
                (item.get("model_role"), item.get("evaluation"))
                != expected_prediction_units.get(item.get("unit_id"))
                for item in prediction_records
            )):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_PREDICTION_SET")
    if (baseline is None) != (augmented is None):
        raise PolicyError("G07_V2_BOUNDARY_PARTIAL_SOURCE_PAIR_REQUIRED")
    if baseline is not None:
        reconstructed = boundary_partial_benefit_evidence(
            baseline, augmented, baseline_identity=payload.get("baseline_identity", {}),
            augmented_identity=payload.get("augmented_identity", {}),
            source_prediction_records=payload.get("source_prediction_records", ()),
            source_nonestimable_records=nonestimable)
        if canonical_json(dict(reconstructed)) != canonical_json(dict(evidence)):
            raise PolicyError("G07_V2_BOUNDARY_PARTIAL_SOURCE_RECONSTRUCTION")


def publication_state(
    artifact_records: Mapping[str, Mapping[str, object]], *,
    required_artifacts: Sequence[str],
) -> Mapping[str, object]:
    required = tuple(sorted(str(item) for item in required_artifacts))
    if tuple(sorted(artifact_records)) != required:
        raise PolicyError("G07_V2_PUBLICATION_ARTIFACT_SET")
    records = {name: dict(artifact_records[name]) for name in required}
    payload = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "publication_state": "VALIDATED_READY_FOR_TERMINAL",
        "required_artifacts": required,
        "artifact_records": records,
    }
    return MappingProxyType({**payload, "publication_gate_sha256": sha256_bytes(canonical_json(payload))})


def validate_publication_state(
    publication: Mapping[str, object], *, artifact_root: Path | None = None,
    required_artifacts: Sequence[str] | None = None,
    expected_artifact_records: Mapping[str, Mapping[str, object]] | None = None,
    terminal_disposition: str | None = None,
) -> Mapping[str, object]:
    """Authenticate a publication envelope against a governed artifact inventory."""
    if terminal_disposition is not None:
        raise PolicyError("G07_V2_PUBLICATION_V1_HASH_ONLY_INTERFACE_REJECTED")
    if artifact_root is None or required_artifacts is None or expected_artifact_records is None:
        raise PolicyError("G07_V2_PUBLICATION_DISK_AUTH_REQUIRED")
    payload = dict(publication)
    observed = payload.pop("publication_gate_sha256", None)
    if observed != sha256_bytes(canonical_json(payload)):
        raise PolicyError("G07_V2_PUBLICATION_GATE_HASH")
    if (payload.get("schema_version") != PUBLICATION_SCHEMA_VERSION or
            payload.get("publication_state") != "VALIDATED_READY_FOR_TERMINAL"):
        raise PolicyError("G07_V2_PUBLICATION_SCHEMA")
    required = tuple(sorted(str(item) for item in required_artifacts))
    if tuple(payload.get("required_artifacts", ())) != required:
        raise PolicyError("G07_V2_PUBLICATION_REQUIRED_SET")
    records = payload.get("artifact_records")
    if not isinstance(records, dict) or tuple(sorted(records)) != required:
        raise PolicyError("G07_V2_PUBLICATION_ARTIFACT_SET")
    if tuple(sorted(expected_artifact_records)) != required:
        raise PolicyError("G07_V2_PUBLICATION_EXPECTED_ARTIFACT_SET")
    expected = {name: dict(expected_artifact_records[name]) for name in required}
    root = Path(artifact_root).resolve()
    for name in required:
        record = records[name]
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "schema"}:
            raise PolicyError(f"G07_V2_PUBLICATION_RECORD:{name}")
        if record != expected[name]:
            raise PolicyError(f"G07_V2_PUBLICATION_GOVERNED_RECORD:{name}")
        relative = Path(str(record["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise PolicyError(f"G07_V2_PUBLICATION_PATH:{name}")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PolicyError(f"G07_V2_PUBLICATION_PATH:{name}") from exc
        if not path.is_file():
            raise PolicyError(f"G07_V2_PUBLICATION_MISSING:{name}")
        value = record["sha256"]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise PolicyError(f"G07_V2_PUBLICATION_HASH:{name}")
        if sha256_bytes(path.read_bytes()) != value:
            raise PolicyError(f"G07_V2_PUBLICATION_DISK_HASH:{name}")
        if not isinstance(record["schema"], str) or not record["schema"]:
            raise PolicyError(f"G07_V2_PUBLICATION_SCHEMA_ID:{name}")
    return publication_state(records, required_artifacts=required)


def atomic_write_once(path: Path, payload: bytes) -> None:
    destination = Path(path)
    if destination.exists():
        raise PolicyError(f"G07_V2_IMMUTABLE_COLLISION:{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=destination.name+".", suffix=".part", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True); raise


def deterministic_tree_inventory(root: Path) -> Mapping[str, object]:
    base = Path(root); rows = []
    for path in sorted(item for item in base.rglob("*") if item.is_file()):
        payload = path.read_bytes()
        rows.append({"path": path.relative_to(base).as_posix(), "size": len(payload),
                     "sha256": sha256_bytes(payload)})
    return MappingProxyType({"file_count": len(rows), "byte_count": sum(row["size"] for row in rows),
                             "inventory_sha256": sha256_bytes(canonical_json(rows))})


def v2_interface_identity(policies: Sequence[HyperparameterPolicy]) -> Mapping[str, object]:
    payload = {"schema_version": "PAPER1_G07_V2_INTERFACE_V1",
               "policy_schema_version": POLICY_SCHEMA_VERSION,
               "policy_aggregate_sha256": policy_aggregate_sha256(policies),
               "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
               "v2_output_root": V2_OUTPUT_ROOT_RELATIVE.as_posix(), "suite_run_id": V2_SUITE_RUN_ID,
               "rf_seeds": RF_SEEDS, "bootstrap_replicates": BOOTSTRAP_REPLICATES,
               "bootstrap_seed": BOOTSTRAP_SEED,
               "rf_stability_metrics": RF_STABILITY_METRICS,
               "postprediction_requirements": (
                   "EXACT_PAIRED_KEYS", "EQUAL_INTERVAL_WITHIN_BLOCK",
                   "EQUAL_B2_B3_B4", "MOVING_BLOCK_L2", "MOVING_BLOCK_L3",
               ),
               "inheritance_edges": sorted((p.policy_sha256, p.inheritance_parent_unit_id)
                                             for p in policies if p.mode is PolicyMode.INHERIT)}
    return MappingProxyType({**payload, "interface_sha256": sha256_bytes(canonical_json(payload))})


__all__ = ("PolicyError", "PolicyMode", "HyperparameterPolicy", "POLICY_SCHEMA_VERSION",
           "EVIDENCE_SCHEMA_VERSION", "V2_SUITE_RUN_ID", "V2_OUTPUT_ROOT_RELATIVE", "RF_SEEDS",
           "RF_STABILITY_METRICS", "BOOTSTRAP_REPLICATES", "BOOTSTRAP_SEED", "resolve_policy", "validate_policy",
           "policy_aggregate_sha256", "validate_checkpoint_policy", "validate_inheritance_claim",
           "guarded_logistic_fit", "rf_seed_stability", "validate_rf_seed_evidence",
           "paired_benefit_evidence", "boundary_partial_benefit_evidence",
           "validate_paired_evidence", "validate_boundary_partial_benefit_evidence",
           "BOUNDARY_PARTIAL_EVIDENCE_SCHEMA_VERSION", "PUBLICATION_SCHEMA_VERSION", "publication_state",
           "validate_publication_state", "atomic_write_once",
           "deterministic_tree_inventory", "v2_interface_identity", "canonical_json")
