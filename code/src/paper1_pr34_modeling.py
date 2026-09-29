"""Frozen Paper 1 PR34 model implementation primitives.

This module contains no import-time I/O and never writes artifacts. The runner
controls scientific execution explicitly; validators use only the deterministic
preprocessing, metric, and receipt helpers below.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score


BASELINE_FIELDS = (
    "distance_active_front_km", "distance_cumulative_perimeter_km", "hybrid_membership",
    "log1p_t0_area_km2", "target_elevation_mean_m", "target_slope_mean_degrees",
    "source_target_elevation_difference_m", "uphill_alignment", "wind_slope_alignment",
    "fbfm_grass_grass_shrub_fraction", "fbfm_shrub_fraction", "fbfm_timber_fraction",
    "fbfm_slash_blowdown_fraction", "fbfm_nonburnable_fraction", "canopy_applicable_fraction",
    "conditional_mean_canopy_cover_pct", "conditional_mean_canopy_height_m",
    "conditional_mean_canopy_base_height_m", "conditional_mean_canopy_bulk_density_kg_m3",
    "hrrr_u10_mean_earth_ms", "hrrr_v10_mean_earth_ms", "hrrr_gust_max_ms",
    "hrrr_temperature_2m_mean_c", "hrrr_relative_humidity_2m_min_pct",
)
EVT_FIELDS = (
    "evt_tree_fraction", "evt_shrub_fraction", "evt_perennial_herbaceous_fraction",
    "evt_annual_herbaceous_fraction", "evt_other_fraction",
)
CANOPY_FIELDS = (
    "conditional_mean_canopy_cover_pct", "conditional_mean_canopy_height_m",
    "conditional_mean_canopy_base_height_m", "conditional_mean_canopy_bulk_density_kg_m3",
)
HYBRID_LEVELS = ("BOTH", "ACTIVE_ONLY", "PERIMETER_BACKSTOP_ONLY", "NEITHER_PRIMARY_COMPONENT")
FBFM_FIELDS = (
    "fbfm_grass_grass_shrub_fraction", "fbfm_shrub_fraction", "fbfm_timber_fraction",
    "fbfm_slash_blowdown_fraction", "fbfm_nonburnable_fraction",
)
KEY_FIELDS = ("event_id", "interval_id", "response_grid_m", "cell_id")
BLOCKS = {"B1": (1, 3, 4, 5), "B2": (6, 8, 9, 10), "B3": (11, 12, 14, 15), "B4": (16, 18, 21, 22)}
OUTER_EVALUATIONS = (
    ("B1_TO_B2", BLOCKS["B1"], BLOCKS["B2"]),
    ("B1_B2_TO_B3", BLOCKS["B1"] + BLOCKS["B2"], BLOCKS["B3"]),
    ("B1_B2_B3_TO_B4", BLOCKS["B1"] + BLOCKS["B2"] + BLOCKS["B3"], BLOCKS["B4"]),
)
TUNING_SPLITS = {
    "B1_TO_B2": (((1, 3), (4,)), ((1, 3, 4), (5,))),
    "B1_B2_TO_B3": ((BLOCKS["B1"], BLOCKS["B2"]),),
    "B1_B2_B3_TO_B4": ((BLOCKS["B1"], BLOCKS["B2"]), (BLOCKS["B1"] + BLOCKS["B2"], BLOCKS["B3"])),
}
RF_FINAL_SEEDS = (20200908, 20200909, 20200910, 20200911, 20200912)
TUNING_SEED = 20200908

FAMILY_FIELDS = {
    "EVC_SENSITIVITY": ("evc_applicable_fraction", "evc_conditional_mean_cover_pct"),
    "EVH_SENSITIVITY": ("evh_applicable_fraction", "evh_conditional_mean_height_m"),
    "LEGACY_EAG_SENSITIVITY": ("legacy_eag_2019_applicable_fraction", "legacy_eag_2019_conditional_mean"),
    "V5_EAG_SENSITIVITY": ("v5_eag_2019_applicable_fraction", "v5_eag_2019_conditional_mean"),
    "V5_CHEATGRASS_SENSITIVITY": ("v5_cheatgrass_2019_applicable_fraction", "v5_cheatgrass_2019_conditional_mean"),
    "PRIOR_MTBS_SENSITIVITY": ("prior_mapped_mtbs_disturbance_area_fraction",),
    "FOREST_HEALTH_SENSITIVITY": ("forest_applicable_fraction", "documented_2016_bark_beetle_mortality_area_fraction"),
    "FACTS_SENSITIVITY": ("nfs_applicable_fraction", "documented_completed_prefire_implementation_area_fraction_within_nfs"),
    "RAP_SENSITIVITY": ("rangeland_applicable_fraction", "conditional_2019_total_herbaceous_production_lb_ac"),
    "FDIST_EXPLORATORY": ("fdist_valid_fraction", "fdist_any_disturbance_fraction"),
}
CONFIDENCE_SENSITIVITIES = {
    "LEGACY_EAG_CONFIDENCE_SENSITIVITY": ("LEGACY_EAG_SENSITIVITY", "legacy_eag_confidence_2019_conditional_mean"),
    "V5_EAG_CONFIDENCE_SENSITIVITY": ("V5_EAG_SENSITIVITY", "v5_eag_confidence_2019_conditional_mean"),
    "V5_CHEATGRASS_CONFIDENCE_SENSITIVITY": ("V5_CHEATGRASS_SENSITIVITY", "v5_cheatgrass_confidence_2019_conditional_mean"),
}


class FailClosedError(RuntimeError):
    """A governed PR34 condition failed; message begins with the F-rule ID."""


@dataclass(frozen=True)
class DesignReceipt:
    model_family: str
    model_role: str
    raw_columns: list[str]
    transformed_columns: list[str]
    structural_zero_counts: dict[str, int]
    applicable_values_unchanged: bool
    training_means: dict[str, float]
    training_population_sds: dict[str, float]
    training_unique_counts: dict[str, int]
    training_minimums: dict[str, float]
    training_maximums: dict[str, float]
    coordinate_status: dict[str, str]
    heldout_differs_from_training_constant: dict[str, bool]
    constant_coordinates_all_zero: dict[str, bool]
    constant_coordinate_affected_row_counts: dict[str, int]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_key_hash(frame: pd.DataFrame) -> str:
    keys = frame.loc[:, KEY_FIELDS].sort_values(list(KEY_FIELDS), kind="stable")
    return hashlib.sha256(keys.to_csv(index=False, lineterminator="\n").encode("utf-8")).hexdigest()


def assert_requested_columns(columns: Sequence[str]) -> None:
    forbidden = {"y", "t1_state_number", "nominal_t1_bin_timestamp", "effective_t1_observation_time_utc", "effective_response_interval_hours"}
    bad = [name for name in columns if name in forbidden or name.startswith("t1_") or "future" in name.lower()]
    if bad:
        raise FailClosedError(f"F04 forbidden model column(s): {sorted(bad)}")


def structural_zero_canopy(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int], bool]:
    if "canopy_applicable_fraction" not in frame:
        raise FailClosedError("F23 missing canopy_applicable_fraction")
    output = frame.copy()
    applicability = output["canopy_applicable_fraction"]
    if not np.isfinite(applicability).all() or not applicability.between(0, 1).all():
        raise FailClosedError("F23 canopy applicability must be finite within [0, 1]")
    zero = applicability.eq(0)
    positive = applicability.gt(0)
    counts: dict[str, int] = {}
    unchanged = True
    for field in CANOPY_FIELDS:
        if field not in output:
            raise FailClosedError(f"F08 missing governed canopy field: {field}")
        raw = output[field]
        if (~np.isfinite(raw[positive])).any():
            raise FailClosedError(f"F23 nonfinite conditional canopy value where applicability > 0: {field}")
        finite_at_zero = np.isfinite(raw[zero])
        if (finite_at_zero & raw[zero].ne(0)).any():
            raise FailClosedError(f"F23 contradictory finite nonzero canopy value where applicability == 0: {field}")
        mapped = raw.where(~zero, 0.0)
        unchanged = unchanged and raw[positive].equals(mapped[positive])
        if not np.isfinite(mapped).all():
            raise FailClosedError(f"F08 nonfinite value remains after canopy structural-zero mapping: {field}")
        output[field] = mapped.astype(float)
        counts[field] = int(zero.sum())
    return output, counts, unchanged


def _hybrid_indicators(series: pd.Series, reference: bool) -> pd.DataFrame:
    if series.isna().any() or not set(series.unique()).issubset(HYBRID_LEVELS):
        raise FailClosedError("F06 unknown or missing hybrid_membership category")
    levels = HYBRID_LEVELS[1:] if reference else HYBRID_LEVELS
    return pd.DataFrame({f"hybrid_{level}": series.eq(level).astype(float) for level in levels}, index=series.index)


def scale_logistic_numeric(
    numeric: pd.DataFrame,
    train_index: pd.Index,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Apply governed training-only scaling with an exact-zero-SD branch."""
    training = numeric.loc[train_index]
    if training.empty or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise FailClosedError("F08 nonfinite governed logistic input or empty training history")
    means = training.mean(axis=0)
    sds = training.std(axis=0, ddof=0)
    unique_counts = training.nunique(dropna=False)
    minimums = training.min(axis=0)
    maximums = training.max(axis=0)
    if (~np.isfinite(sds)).any():
        raise FailClosedError("F20 nonfinite training population SD")
    transformed = pd.DataFrame(index=numeric.index, columns=numeric.columns, dtype=float)
    status: dict[str, str] = {}
    heldout_differs: dict[str, bool] = {}
    all_zero: dict[str, bool] = {}
    affected_rows: dict[str, int] = {}
    for field in numeric.columns:
        if sds[field] == 0.0:
            transformed[field] = 0.0
            status[field] = "TRAINING_CONSTANT_FIXED_ZERO_COORDINATE"
            heldout_differs[field] = bool(numeric[field].ne(means[field]).any())
            all_zero[field] = bool(transformed[field].eq(0.0).all())
            affected_rows[field] = len(transformed)
        else:
            transformed[field] = (numeric[field] - means[field]) / sds[field]
            status[field] = "STANDARDIZED"
            heldout_differs[field] = False
            all_zero[field] = False
            affected_rows[field] = 0
    if not np.isfinite(transformed.to_numpy(dtype=float)).all():
        raise FailClosedError("F24 unexpected nonfinite transformed logistic coordinate")
    return transformed, {
        "training_means": means.astype(float).to_dict(),
        "training_population_sds": sds.astype(float).to_dict(),
        "training_unique_counts": unique_counts.astype(int).to_dict(),
        "training_minimums": minimums.astype(float).to_dict(),
        "training_maximums": maximums.astype(float).to_dict(),
        "coordinate_status": status,
        "heldout_differs_from_training_constant": heldout_differs,
        "constant_coordinates_all_zero": all_zero,
        "constant_coordinate_affected_row_counts": affected_rows,
    }


def prepare_design(
    frame: pd.DataFrame,
    *,
    model_family: str,
    model_role: str,
    extra_fields: Sequence[str] = (),
    train_index: pd.Index | None = None,
) -> tuple[pd.DataFrame, DesignReceipt]:
    raw = list(BASELINE_FIELDS)
    if model_role == "baseline_plus_evt":
        raw += list(EVT_FIELDS)
    raw += list(extra_fields)
    if len(raw) != len(set(raw)):
        raise FailClosedError("F05 duplicate governed model column")
    assert_requested_columns(raw)
    missing = [field for field in raw if field not in frame]
    if missing:
        raise FailClosedError(f"F05 missing whitelisted model column(s): {missing}")
    mapped, structural_counts, unchanged = structural_zero_canopy(frame.loc[:, list(dict.fromkeys(raw + ["canopy_applicable_fraction"]))])
    if model_family == "logistic":
        numeric = mapped.loc[:, [field for field in raw if field != "hybrid_membership"]].copy()
        numeric = numeric.drop(columns=["fbfm_nonburnable_fraction"], errors="ignore")
        if model_role == "baseline_plus_evt":
            numeric = numeric.drop(columns=["evt_other_fraction"], errors="ignore")
        if train_index is None:
            raise FailClosedError("F11 logistic design requires a training-history index")
        scaled_numeric, statistics = scale_logistic_numeric(numeric, train_index)
        indicators = _hybrid_indicators(mapped["hybrid_membership"], reference=True)
        design = pd.concat([scaled_numeric, indicators], axis=1)
        for field in indicators:
            statistics["training_means"][field] = float(indicators.loc[train_index, field].mean())
            statistics["training_population_sds"][field] = float(indicators.loc[train_index, field].std(ddof=0))
            statistics["training_unique_counts"][field] = int(indicators.loc[train_index, field].nunique())
            statistics["training_minimums"][field] = float(indicators.loc[train_index, field].min())
            statistics["training_maximums"][field] = float(indicators.loc[train_index, field].max())
            statistics["coordinate_status"][field] = "FIXED_SCHEMA_INDICATOR"
            statistics["heldout_differs_from_training_constant"][field] = False
            statistics["constant_coordinates_all_zero"][field] = bool(indicators[field].eq(0).all())
            statistics["constant_coordinate_affected_row_counts"][field] = 0
        receipt = DesignReceipt(
            model_family, model_role, raw, list(design.columns), structural_counts,
            unchanged, **statistics,
        )
    elif model_family == "rf":
        numeric = mapped.loc[:, [field for field in raw if field != "hybrid_membership"]].copy()
        design = pd.concat([numeric, _hybrid_indicators(mapped["hybrid_membership"], reference=False)], axis=1)
        receipt = DesignReceipt(model_family, model_role, raw, list(design.columns), structural_counts, unchanged, {}, {}, {}, {}, {}, {}, {}, {}, {})
    else:
        raise ValueError(f"Unknown model family: {model_family}")
    if not np.isfinite(design.to_numpy(dtype=float)).all():
        raise FailClosedError("F08 nonfinite model input")
    return design.astype(float), receipt


def prevalence_probabilities(training_y: Sequence[int], n_rows: int) -> np.ndarray:
    values = np.asarray(training_y, dtype=int)
    if not set(np.unique(values)).issubset({0, 1}) or len(values) == 0:
        raise FailClosedError("F03 training outcome is missing or nonbinary")
    return np.full(n_rows, (values.sum() + 0.5) / (len(values) + 1.0), dtype=float)


def make_estimator(model_family: str, hyperparameter: float, seed: int | None = None):
    if model_family == "logistic":
        return LogisticRegression(C=hyperparameter, penalty="l2", solver="lbfgs", fit_intercept=True, class_weight=None, max_iter=5000, tol=1e-8)
    if model_family == "rf":
        return RandomForestClassifier(n_estimators=1000, criterion="log_loss", max_depth=6, max_features="sqrt", bootstrap=True, class_weight=None, min_samples_split=2, min_samples_leaf=hyperparameter, random_state=seed)
    raise ValueError(model_family)


def fit_probabilities(model_family: str, x_train: pd.DataFrame, y_train: Sequence[int], x_test: pd.DataFrame, hyperparameter: float, seed: int | None = None) -> np.ndarray:
    y = np.asarray(y_train, dtype=int)
    if set(np.unique(y)) != {0, 1}:
        raise FailClosedError("F12 training history contains one response class")
    estimator = make_estimator(model_family, hyperparameter, seed)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        try:
            estimator.fit(x_train, y)
        except ConvergenceWarning as exc:
            raise FailClosedError("F14 logistic optimizer did not converge") from exc
    probabilities = estimator.predict_proba(x_test)[:, 1]
    if not np.isfinite(probabilities).all() or (probabilities < 0).any() or (probabilities > 1).any():
        raise FailClosedError("F15 invalid predicted probabilities")
    return probabilities


def _calibration(y: np.ndarray, probabilities: np.ndarray) -> tuple[object, object]:
    if len(np.unique(y)) != 2:
        return "NOT_DEFINED", "NOT_DEFINED"
    logits = np.log(np.clip(probabilities, 1e-15, 1 - 1e-15) / (1 - np.clip(probabilities, 1e-15, 1 - 1e-15)))
    if np.ptp(logits) == 0:
        return "NOT_DEFINED", "NOT_DEFINED"
    def loss_intercept(beta: np.ndarray) -> float:
        eta = logits + beta[0]
        return float(np.logaddexp(0, eta).sum() - (y * eta).sum())
    def loss_slope(beta: np.ndarray) -> float:
        eta = beta[0] + beta[1] * logits
        return float(np.logaddexp(0, eta).sum() - (y * eta).sum())
    intercept_fit = minimize(loss_intercept, np.array([0.0]), method="BFGS", tol=1e-10, options={"maxiter": 10000})
    slope_fit = minimize(loss_slope, np.array([0.0, 1.0]), method="BFGS", tol=1e-10, options={"maxiter": 10000})
    intercept = float(intercept_fit.x[0]) if intercept_fit.success else "NOT_DEFINED"
    slope = float(slope_fit.x[1]) if slope_fit.success else "NOT_DEFINED"
    return intercept, slope


def reliability_summary(y: Sequence[int], probabilities: Sequence[float], interval: Sequence[int], cell_id: Sequence[object]) -> list[dict[str, float | int]]:
    frame = pd.DataFrame({"y": y, "p": probabilities, "interval": interval, "cell_id": cell_id})
    ordered = frame.sort_values(["p", "interval", "cell_id"], kind="stable").reset_index(drop=True)
    groups = np.array_split(np.arange(len(ordered)), 5)
    return [{"bin": index + 1, "count": len(group), "mean_probability": float(ordered.loc[group, "p"].mean()), "event_fraction": float(ordered.loc[group, "y"].mean())} for index, group in enumerate(groups) if len(group)]


def interval_metrics(y: Sequence[int], probabilities: Sequence[float], interval_number: int, cell_id: Sequence[object]) -> dict[str, object]:
    y_values = np.asarray(y, dtype=int)
    p_values = np.asarray(probabilities, dtype=float)
    if not set(np.unique(y_values)).issubset({0, 1}) or not np.isfinite(p_values).all():
        raise FailClosedError("F03/F15 invalid metric inputs")
    both_classes = len(np.unique(y_values)) == 2
    intercept, slope = _calibration(y_values, p_values)
    return {
        "interval_number": int(interval_number), "rows": int(len(y_values)), "positives": int(y_values.sum()),
        "log_loss": float(log_loss(y_values, np.clip(p_values, 1e-15, 1 - 1e-15), labels=[0, 1])),
        "brier": float(brier_score_loss(y_values, p_values)),
        "average_precision": float(average_precision_score(y_values, p_values)) if both_classes else "NOT_DEFINED",
        "roc_auc": float(roc_auc_score(y_values, p_values)) if both_classes else "NOT_DEFINED",
        "calibration_intercept": intercept, "calibration_slope": slope,
        "reliability": reliability_summary(y_values, p_values, np.repeat(interval_number, len(y_values)), cell_id),
    }


def aggregate_interval_metric(records: Sequence[dict[str, object]], metric: str) -> dict[str, float]:
    frame = pd.DataFrame(records)
    usable = frame.loc[pd.to_numeric(frame[metric], errors="coerce").notna()].copy()
    usable["block"] = usable["interval_number"].map({number: block for block, numbers in BLOCKS.items() for number in numbers})
    block_means = usable.groupby("block", sort=False)[metric].mean()
    return {"overall_equal_block_mean": float(block_means.loc[["B2", "B3", "B4"]].mean()), **{f"{block}_mean": float(block_means[block]) for block in block_means.index}}


def moving_block_bootstrap(deltas: Sequence[float], block_length: int, replicates: int = 10000, seed: int = TUNING_SEED) -> np.ndarray:
    values = np.asarray(deltas, dtype=float)
    if len(values) != 12 or block_length not in {2, 3} or not np.isfinite(values).all():
        raise ValueError("Governed bootstrap requires 12 finite interval deltas and block length 2 or 3")
    blocks = [values[start:start + block_length] for start in range(len(values) - block_length + 1)]
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates, dtype=float)
    for index in range(replicates):
        chosen = [blocks[item] for item in rng.integers(0, len(blocks), size=int(np.ceil(12 / block_length)))]
        sampled = np.concatenate(chosen)[:12]
        block_map = (np.repeat(["B2", "B3", "B4"], 4))
        draws[index] = float(pd.Series(sampled).groupby(block_map).mean().mean())
    return draws


def choose_hyperparameter(scores: dict[float, float], model_family: str) -> float:
    if not scores or not all(np.isfinite(list(scores.values()))):
        raise FailClosedError("F12/F15 nonfinite tuning score")
    best = min(scores.values())
    candidates = [value for value, score in scores.items() if abs(score - best) <= 1e-12]
    return min(candidates) if model_family == "logistic" else max(candidates)


def receipt_json(receipt: DesignReceipt) -> str:
    return json.dumps(asdict(receipt), sort_keys=True, separators=(",", ":"))
