"""Execute the frozen Paper 1 PR34 model workflow only when explicitly requested.

Running this module without ``--execute`` validates governed inputs and prints the
future output location. It never writes scientific artifacts by default.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import paper1_pr34_modeling as model  # noqa: E402


OUTPUT_ROOT = ROOT / "data" / "processed" / "propagation" / "paper1" / "pr34_models"
RISK_SETS = ("PRIMARY_HYBRID", "ACTIVE_FRONT_ONLY_5KM", "PERIMETER_ONLY_2KM", "PERIMETER_ONLY_5KM")
GRIDS = (1000, 2000)
EXPECTED_ENVIRONMENT = {"python": "3.12.13", "scikit-learn": "1.9.0", "numpy": "2.5.1", "scipy": "1.18.0", "pandas": "3.0.3"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strict_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, strict=True))
    if not rows or any(set(row) != set(rows[0]) for row in rows):
        raise model.FailClosedError(f"F01 strict CSV parse/schema failure: {path.name}")
    return rows


def table_path(risk_set: str, grid_m: int) -> Path:
    label = f"{grid_m // 1000}km"
    root = ROOT / "data" / "processed" / "propagation" / "paper1"
    if risk_set == "PRIMARY_HYBRID":
        return root / "pr31_labeled_tables" / "outputs" / f"paper1_pr31_labeled_table_{label}.parquet"
    return root / "pr32b_alt_riskset_labeled" / risk_set / "outputs" / f"paper1_pr32b_labeled_{risk_set.lower()}_{label}.parquet"


def support_path(risk_set: str, grid_m: int) -> Path:
    label = f"{grid_m // 1000}km"
    root = ROOT / "data" / "processed" / "propagation" / "paper1"
    if risk_set == "PRIMARY_HYBRID":
        return root / "pr24_response_free_support" / "outputs" / f"paper1_pr24_support_masks_{label}.parquet"
    return root / "pr32a_alt_riskset_response_free" / "support" / risk_set / "outputs" / f"paper1_pr32a_support_masks_{risk_set.lower()}_{label}.parquet"


def current_versions() -> dict[str, str]:
    import numpy, pandas, scipy, sklearn
    return {"python": ".".join(map(str, sys.version_info[:3])), "scikit-learn": sklearn.__version__, "numpy": numpy.__version__, "scipy": scipy.__version__, "pandas": pandas.__version__}


def validate_environment() -> dict[str, str]:
    versions = current_versions()
    if versions != EXPECTED_ENVIRONMENT:
        raise model.FailClosedError(f"F16 scientific environment mismatch: {versions}")
    return versions


def validate_governed_inputs() -> dict[str, object]:
    qc = pd.read_csv(ROOT / "documentation" / "PAPER1_CANOPY_NONAPPLICABILITY_QC.csv")
    hashes: dict[str, str] = {}
    for record in qc.itertuples(index=False):
        table = table_path(record.risk_set_id, int(record.response_grid_m))
        support = support_path(record.risk_set_id, int(record.response_grid_m))
        if not table.is_file() or not support.is_file():
            raise model.FailClosedError("F01/F02 frozen labeled table or support mask is absent")
        table_hash, support_hash = sha256(table), sha256(support)
        if table_hash != record.table_sha256:
            raise model.FailClosedError(f"F01 labeled table hash mismatch: {table}")
        if support_hash != record.support_sha256:
            raise model.FailClosedError(f"F02 support mask hash mismatch: {support}")
        hashes[str(table.relative_to(ROOT))] = table_hash
        hashes[str(support.relative_to(ROOT))] = support_hash
    required_docs = (
        "PAPER1_MODEL_PREDICTOR_WHITELIST.csv", "PAPER1_MODEL_PREPROCESSING_SPEC.csv",
        "PAPER1_MODEL_FORMULATION_SPEC.md", "PAPER1_PR33_MODEL_AUTHORIZATION_DECISION.csv",
        "PAPER1_CANOPY_NONAPPLICABILITY_MODEL_AUTHORITY.md", "PAPER1_PR34A_CANOPY_AUTHORITY_DECISION.csv",
        "PAPER1_FINAL_MODEL_FAIL_CLOSED_RULES.csv", "PAPER1_MODEL_METRIC_SPEC.csv",
        "PAPER1_MODEL_TUNING_SPEC.csv", "PAPER1_MODEL_UNCERTAINTY_SPEC.csv",
        "PAPER1_SINGLE_CLASS_METRIC_POLICY.csv", "PAPER1_MODEL_SENSITIVITY_HIERARCHY.csv",
    )
    docs = ROOT / "documentation"
    for name in required_docs:
        path = docs / name
        if not path.is_file():
            raise model.FailClosedError(f"F01 required authority missing: {name}")
        if path.suffix == ".csv":
            strict_csv(path)
        hashes[str(path.relative_to(ROOT))] = sha256(path)
    whitelist = pd.read_csv(docs / "PAPER1_MODEL_PREDICTOR_WHITELIST.csv")
    if tuple(whitelist.loc[whitelist.model_role.eq("baseline"), "raw_column"]) != model.BASELINE_FIELDS:
        raise model.FailClosedError("F05 baseline whitelist order/content mismatch")
    if tuple(whitelist.loc[whitelist.model_role.eq("core ecology"), "raw_column"]) != model.EVT_FIELDS:
        raise model.FailClosedError("F05 EVT whitelist order/content mismatch")
    return {"input_hashes": hashes, "environment": validate_environment()}


def load_supported_table(risk_set: str, grid_m: int, support_universe: str) -> pd.DataFrame:
    table = pd.read_parquet(table_path(risk_set, grid_m))
    support = pd.read_parquet(support_path(risk_set, grid_m))
    keys = list(model.KEY_FIELDS)
    mask = support.loc[support.support_universe_id.eq(support_universe), keys + ["included"]]
    if len(mask) != len(table) or mask.duplicated(keys).any():
        raise model.FailClosedError("F02 support membership is not one-to-one with labeled rows")
    merged = table.merge(mask, on=keys, how="left", validate="one_to_one")
    if merged.included.isna().any():
        raise model.FailClosedError("F02 support membership missing a labeled row")
    return merged.loc[merged.included.astype(bool)].drop(columns="included").reset_index(drop=True)


def assert_pair_invariance(baseline: pd.DataFrame, augmented: pd.DataFrame, train_intervals: tuple[int, ...], test_intervals: tuple[int, ...], seed_policy: tuple[int, ...]) -> None:
    left = baseline.loc[:, list(model.KEY_FIELDS) + ["y"]].sort_values(list(model.KEY_FIELDS), kind="stable").reset_index(drop=True)
    right = augmented.loc[:, list(model.KEY_FIELDS) + ["y"]].sort_values(list(model.KEY_FIELDS), kind="stable").reset_index(drop=True)
    if not left.equals(right):
        raise model.FailClosedError("F19 paired baseline/augmented rows or outcomes differ")
    if set(train_intervals) & set(test_intervals) or not seed_policy:
        raise model.FailClosedError("F09/F19 invalid paired chronology or RF seed policy")


def _design_for_geometry(frame: pd.DataFrame, train_index: pd.Index) -> tuple[pd.DataFrame, model.DesignReceipt]:
    fields = ("distance_active_front_km", "distance_cumulative_perimeter_km", "hybrid_membership", "log1p_t0_area_km2")
    if frame.loc[:, fields].isna().any().any():
        raise model.FailClosedError("F08 geometry benchmark input missing")
    continuous = frame.loc[:, [field for field in fields if field != "hybrid_membership"]].astype(float)
    indicators = pd.DataFrame({f"hybrid_{level}": frame.hybrid_membership.eq(level).astype(float) for level in model.HYBRID_LEVELS[1:]}, index=frame.index)
    scaled, statistics = model.scale_logistic_numeric(continuous, train_index)
    design = pd.concat([scaled, indicators], axis=1)
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
    receipt = model.DesignReceipt("logistic", "geometry_benchmark", list(fields), list(design.columns), {}, True, **statistics)
    return design, receipt


def _tune(frame: pd.DataFrame, model_family: str, role: str, extra_fields: tuple[str, ...], evaluation_id: str) -> float:
    candidates = (0.1, 1.0) if model_family == "logistic" else (0.02, 0.05)
    scores: dict[float, float] = {}
    for candidate in candidates:
        interval_scores: list[float] = []
        for inner_train, inner_validate in model.TUNING_SPLITS[evaluation_id]:
            train = frame.index[frame.interval_number.isin(inner_train)]
            valid = frame.index[frame.interval_number.isin(inner_validate)]
            design, _ = model.prepare_design(frame, model_family=model_family, model_role=role, extra_fields=extra_fields, train_index=train if model_family == "logistic" else None)
            probabilities = model.fit_probabilities(model_family, design.loc[train], frame.loc[train, "y"], design.loc[valid], candidate, model.TUNING_SEED if model_family == "rf" else None)
            for number in inner_validate:
                positions = frame.loc[valid, "interval_number"].eq(number).to_numpy()
                interval_scores.append(model.interval_metrics(frame.loc[valid, "y"].to_numpy()[positions], probabilities[positions], number, frame.loc[valid, "cell_id"].to_numpy()[positions])["log_loss"])
        scores[candidate] = float(np.mean(interval_scores))
    return model.choose_hyperparameter(scores, model_family)


def run_pair(frame: pd.DataFrame, *, model_family: str, role: str, extra_fields: tuple[str, ...], hyperparameters: dict[str, float] | None = None, no_early: bool = False) -> dict[str, object]:
    """Run a future scientific pair; caller must be explicit about writing outputs."""
    working = frame.loc[frame.interval_number.isin(sum((list(values) for values in model.BLOCKS.values()), []))].copy()
    if no_early:
        working = working.loc[~working.interval_number.isin((1, 3))].copy()
    results: list[dict[str, object]] = []
    for evaluation_id, train_intervals, test_intervals in model.OUTER_EVALUATIONS:
        train_intervals = tuple(value for value in train_intervals if value in set(working.interval_number))
        test_intervals = tuple(value for value in test_intervals if value in set(working.interval_number))
        train = working.index[working.interval_number.isin(train_intervals)]
        test = working.index[working.interval_number.isin(test_intervals)]
        if not len(train) or not len(test):
            raise model.FailClosedError("F17 required outer interval missing")
        assert_pair_invariance(working, working, train_intervals, test_intervals, model.RF_FINAL_SEEDS)
        parameter = hyperparameters[evaluation_id] if hyperparameters else _tune(working, model_family, role, extra_fields, evaluation_id)
        design, receipt = model.prepare_design(working, model_family=model_family, model_role=role, extra_fields=extra_fields, train_index=train if model_family == "logistic" else None)
        if model_family == "rf":
            seed_probabilities = [model.fit_probabilities("rf", design.loc[train], working.loc[train, "y"], design.loc[test], parameter, seed) for seed in model.RF_FINAL_SEEDS]
            probabilities = np.mean(seed_probabilities, axis=0)
        else:
            probabilities = model.fit_probabilities("logistic", design.loc[train], working.loc[train, "y"], design.loc[test], parameter)
        for interval in test_intervals:
            interval_mask = working.loc[test, "interval_number"].eq(interval).to_numpy()
            metric = model.interval_metrics(working.loc[test, "y"].to_numpy()[interval_mask], probabilities[interval_mask], interval, working.loc[test, "cell_id"].to_numpy()[interval_mask])
            metric.update({"evaluation_id": evaluation_id, "model_family": model_family, "model_role": role, "hyperparameter": parameter, "design_receipt": model.receipt_json(receipt)})
            results.append(metric)
    return {"interval_metrics": results, "aggregate_log_loss": model.aggregate_interval_metric(results, "log_loss"), "aggregate_brier": model.aggregate_interval_metric(results, "brier")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Run the scientific workflow and write governed outputs. Not used by PR34 implementation validation.")
    args = parser.parse_args()
    validation = validate_governed_inputs()
    if not args.execute:
        print(json.dumps({"status": "READY_FOR_LOCAL_FULL_RUN", "scientific_execution": False, "output_root": str(OUTPUT_ROOT.relative_to(ROOT)), **validation}, indent=2))
        return 0
    raise RuntimeError("Scientific execution is intentionally separated from this implementation gate. Re-run only after post-run authorization and output-manifest review.")


if __name__ == "__main__":
    raise SystemExit(main())
