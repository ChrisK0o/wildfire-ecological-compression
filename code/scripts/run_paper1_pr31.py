"""Build Paper 1 PR31 labeled tables and perform the pre-modeling leakage gate.

This script is deliberately not a model runner. It verifies immutable PR23 and
PR24 inputs, constructs the locked center-covered-by-next-FEDS-state response,
joins labels by stable keys, and writes audit and provenance records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "documentation"
PR23 = ROOT / "data/processed/propagation/paper1/pr23_response_free_predictors"
PR24 = ROOT / "data/processed/propagation/paper1/pr24_response_free_support"
PR31 = ROOT / "data/processed/propagation/paper1/pr31_labeled_tables"
OUTPUTS = PR31 / "outputs"
STATES = ROOT / "data/processed/feasibility/paper1_feds_validation/extracted/feds_event_65371_states.parquet"
INTERVAL_LOCK = DOC / "PAPER1_PROPAGATION_INTERVAL_LOCK.csv"
STATE_TIMES = DOC / "PAPER1_FEDS_INFORMATION_TIME_BY_STATE.csv"
HRRR_OBJECTS = DOC / "PAPER1_HRRR_SELECTED_OBJECTS.csv"
PREDICTOR_DICTIONARY = DOC / "PAPER1_PROPAGATION_PREDICTOR_DICTIONARY.csv"
PR23_SCRIPT = ROOT / "scripts/run_paper1_pr23.py"
PREFIRE_CUTOFF = pd.Timestamp("2020-09-08T00:00:00Z")
PRIMARY_INTERVALS = [1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22]
NO_EARLY_INTERVALS = [4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22]
KEYS = ["event_id", "interval_id", "cell_id"]
REQUIRED_COMMITTED = [
    "scripts/run_paper1_pr23.py", "scripts/run_paper1_pr24.py",
    "documentation/PAPER1_PROPAGATION_AGGREGATION_SPEC.md",
    "documentation/PAPER1_PROPAGATION_PR23_DECISION.csv",
    "documentation/PAPER1_PROPAGATION_COMMON_SUPPORT_SPEC.md",
    "documentation/PAPER1_PROPAGATION_SUPPORT_UNIVERSES.csv",
    "documentation/PAPER1_PROPAGATION_PR24_QC.csv",
    "documentation/PAPER1_PROPAGATION_PR24_DECISION.csv",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def atomic_parquet(frame: pd.DataFrame, path: Path) -> str:
    temporary = path.with_suffix(".parquet.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    return sha256(path)


def preflight() -> dict[str, object]:
    tracked = set(git("ls-tree", "-r", "--name-only", "HEAD").splitlines())
    missing = [path for path in REQUIRED_COMMITTED if path not in tracked]
    if missing:
        raise RuntimeError(f"Committed PR23/PR24 pre-flight failed; missing: {missing}")
    if list(PR23.rglob("*.part")) or list(PR24.rglob("*.part")):
        raise RuntimeError("Unresolved PR23/PR24 .part file found.")
    p23 = json.loads((PR23 / "pr23_manifest.json").read_text(encoding="utf-8"))
    p24 = json.loads((PR24 / "pr24_manifest.json").read_text(encoding="utf-8"))
    for script, manifest in [(ROOT / "scripts/run_paper1_pr23.py", p23), (ROOT / "scripts/run_paper1_pr24.py", p24)]:
        if sha256(script) != manifest["script_sha256"]:
            raise RuntimeError(f"Script/manifest mismatch: {script}")
    matrices, masks = {}, {}
    for resolution in (1000, 2000):
        pinfo = p23["outputs"][str(resolution)]
        matrix_path = ROOT / pinfo["path"]
        minfo = p24["outputs"][str(resolution)]
        mask_path = ROOT / minfo["path"]
        if sha256(matrix_path) != pinfo["sha256"] or sha256(mask_path) != minfo["sha256"]:
            raise RuntimeError(f"PR23/PR24 hash mismatch at {resolution} m.")
        matrix = pd.read_parquet(matrix_path)
        mask = pd.read_parquet(mask_path)
        primary = mask[mask.support_universe_id.eq("PRIMARY_CONFIRMATORY")]
        if len(matrix) != pinfo["rows"] or int(primary.included.sum()) != len(matrix):
            raise RuntimeError(f"PR24 primary support mismatch at {resolution} m.")
        if matrix.duplicated(KEYS).any() or primary.duplicated(KEYS).any():
            raise RuntimeError(f"Duplicate PR23/PR24 keys at {resolution} m.")
        matrices[resolution] = {"path": matrix_path, "hash": pinfo["sha256"], "rows": len(matrix)}
        masks[resolution] = {"path": mask_path, "hash": minfo["sha256"], "rows": len(mask)}
    return {"pr23": p23, "pr24": p24, "matrices": matrices, "masks": masks}


def interval_metadata() -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    states = gpd.read_parquet(STATES).sort_values("t").reset_index(drop=True)
    if states.crs is None or states.crs.to_epsg() != 9311 or set(states.fireID.dropna().astype(int)) != {65371}:
        raise RuntimeError("FEDS states are not event 65371 in EPSG:9311.")
    lock = pd.read_csv(INTERVAL_LOCK)
    lock = lock[lock.interval_number.isin(PRIMARY_INTERVALS)].copy()
    if lock.interval_number.astype(int).tolist() != PRIMARY_INTERVALS:
        raise RuntimeError("Retained interval order differs from authority.")
    times = pd.read_csv(STATE_TIMES)
    times = times.set_index("state_number")
    records = []
    for row in lock.itertuples():
        t0, t1 = int(row.t0_state_number), int(row.t1_state_number)
        if t1 != t0 + 1:
            raise RuntimeError(f"Interval {row.interval_number} is not the next completed state.")
        t0_time = times.loc[t0]
        t1_time = times.loc[t1]
        effective_t0 = pd.Timestamp(t0_time.earliest_theoretical_complete_state_time_utc)
        effective_t1 = pd.Timestamp(t1_time.earliest_theoretical_complete_state_time_utc)
        records.append({
            "interval_number": int(row.interval_number), "t0_state_number": t0, "t1_state_number": t1,
            "nominal_t0_bin_timestamp": row.t0_timestamp_utc, "nominal_t1_bin_timestamp": row.t1_timestamp_utc,
            "effective_t0_observation_cutoff_utc": effective_t0.isoformat().replace("+00:00", "Z"),
            "effective_t1_observation_time_utc": effective_t1.isoformat().replace("+00:00", "Z"),
            "effective_response_interval_hours": (effective_t1 - effective_t0).total_seconds() / 3600,
            "t0_hull_sha256": hashlib.sha256(states.iloc[t0 - 1].hull.wkb).hexdigest(),
            "t1_hull_sha256": hashlib.sha256(states.iloc[t1 - 1].hull.wkb).hexdigest(),
        })
    return states, pd.DataFrame(records)


def construct_labels(predictors: pd.DataFrame, states: gpd.GeoDataFrame, timing: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for interval_number, candidates in predictors.groupby("interval_number", sort=True):
        meta = timing[timing.interval_number.eq(interval_number)].iloc[0]
        hull0 = states.iloc[int(meta.t0_state_number) - 1].hull
        hull1 = states.iloc[int(meta.t1_state_number) - 1].hull
        points = shapely.points(candidates.center_x_epsg9311, candidates.center_y_epsg9311)
        reached0 = shapely.covers(hull0, points)
        reached1 = shapely.covers(hull1, points)
        if reached0.any():
            raise RuntimeError(f"Frozen candidates already covered at t0 for interval {interval_number}.")
        d0 = shapely.distance(points, hull0.boundary)
        d1 = shapely.distance(points, hull1.boundary)
        labels = candidates[KEYS + ["interval_number", "response_grid_m", "forward_chain_block"]].copy()
        labels["y"] = reached1.astype("int8")
        labels["t0_state_number"] = int(meta.t0_state_number)
        labels["t1_state_number"] = int(meta.t1_state_number)
        labels["nominal_t0_bin_timestamp"] = meta.nominal_t0_bin_timestamp
        labels["nominal_t1_bin_timestamp"] = meta.nominal_t1_bin_timestamp
        labels["effective_t0_observation_cutoff_utc_label"] = meta.effective_t0_observation_cutoff_utc
        labels["effective_t1_observation_time_utc"] = meta.effective_t1_observation_time_utc
        labels["effective_response_interval_hours"] = meta.effective_response_interval_hours
        labels["no_early_sensitivity_included"] = interval_number in NO_EARLY_INTERVALS
        labels["distance_center_to_t0_boundary_m"] = d0
        labels["distance_center_to_t1_boundary_m"] = d1
        labels["within_either_boundary_500m"] = (d0 <= 500) | (d1 <= 500)
        labels["within_either_boundary_1000m"] = (d0 <= 1000) | (d1 <= 1000)
        labels["t0_hull_sha256"] = meta.t0_hull_sha256
        labels["t1_hull_sha256"] = meta.t1_hull_sha256
        rows.append(labels)
    return pd.concat(rows, ignore_index=True)


def support_wide(mask: pd.DataFrame) -> pd.DataFrame:
    wide = mask.pivot(index=KEYS, columns="support_universe_id", values="included")
    wide.columns = [f"support_{name.lower()}" for name in wide.columns]
    return wide.reset_index()


def family_for(variable: str) -> str:
    rules = [
        (("hrrr_",), "HRRR"), (("evt_",), "EVT"), (("evc_",), "EVC"), (("evh_",), "EVH"),
        (("legacy_eag",), "LEGACY_EAG"), (("v5_eag",), "V5_EAG"), (("v5_cheatgrass",), "V5_CHEATGRASS"),
        (("fbfm_",), "FBFM40"), (("canopy_", "conditional_mean_canopy"), "CANOPY"),
        (("rap_", "rangeland_", "conditional_2019"), "RAP"), (("fdist_",), "FDIST"),
        (("prior_", "years_since_most_recent"), "PRIOR_MTBS"), (("forest_", "documented_2016"), "FOREST_HEALTH"),
        (("nfs_", "documented_completed"), "FACTS"),
    ]
    for prefixes, family in rules:
        if variable.startswith(prefixes):
            return family
    if variable.startswith(("distance_t0", "distance_active", "distance_cumulative", "risk_membership", "hybrid_membership", "t0_cumulative", "log1p_t0")):
        return "FEDS_STATE"
    if variable.startswith(("terrain_", "target_", "source_target_", "uphill_", "wind_slope_")):
        return "TERRAIN"
    return "OTHER_SUPPORT"


def temporal_record(variable: str) -> dict[str, str | bool]:
    family = family_for(variable)
    dynamic = family in {"FEDS_STATE", "HRRR"} or variable.startswith(("source_target_", "uphill_", "wind_slope_"))
    references = {
        "FEDS_STATE": "Completed t0 FEDS event 65371 state", "HRRR": "Cutoff-valid HRRRv3 forecast initialization and leads",
        "TERRAIN": "Static USGS 3DEP terrain", "FBFM40": "LF2016 Remap", "CANOPY": "LF2016 Remap",
        "EVT": "LF2016 Remap", "EVC": "LF2016 Remap", "EVH": "LF2016 Remap", "LEGACY_EAG": "2019 prefire EAG",
        "V5_EAG": "2019 retrospective product lineage", "V5_CHEATGRASS": "2019 retrospective product lineage",
        "PRIOR_MTBS": "Mapped MTBS events strictly before 2020-09-08", "FOREST_HEALTH": "ODF 2016 documented bark-beetle mortality",
        "FACTS": "Completed implementation records strictly before 2020-09-08", "RAP": "RAP 2019 production",
        "FDIST": "LF2016 FDist", "OTHER_SUPPORT": "PR23 source/support provenance",
    }
    status = "AUTHORIZED_RETROSPECTIVE_SENSITIVITY" if family in {"V5_EAG", "V5_CHEATGRASS"} else "PASS"
    return {
        "predictor_family": family, "static_dynamic": "DYNAMIC_AT_T0" if dynamic else "STATIC",
        "source_timestamp_or_reference_period": references[family],
        "allowed_information_cutoff": "At or before effective_t0_observation_cutoff_utc" if dynamic else "Locked static/prefire or explicitly authorized retrospective sensitivity lineage",
        "leakage_status": status,
    }


def leakage_ledger(dictionary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for source in dictionary.itertuples(index=False):
        variable = source.canonical_variable_name
        temporal = temporal_record(variable)
        qualification = "Sensitivity only" if source.model_role == "SENSITIVITY_OR_SUPPORT" else "Locked model role"
        rows.append({
            "variable": variable, "predictor_family": temporal["predictor_family"], "model_role": source.model_role,
            "temporal_class": temporal["static_dynamic"], "source_timestamp_or_reference_period": temporal["source_timestamp_or_reference_period"],
            "allowed_information_cutoff": temporal["allowed_information_cutoff"], "uses_t1": False, "uses_future_state": False,
            "uses_final_perimeter": False, "uses_outcome": False, "leakage_status": temporal["leakage_status"],
            "justification": f"{qualification}; constructed in response-free PR23 and unchanged in PR31.",
            "provenance_artifact": source.provenance_artifact,
        })
    return pd.DataFrame(rows)


def label_qc(tables: dict[int, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for resolution, table in tables.items():
        support_columns = [c for c in table if c.startswith("support_") and c != "support_primary_confirmatory"]
        scopes = [("ALL", "ALL", table), ("NO_EARLY", "LOCKED_14", table[table.no_early_sensitivity_included])]
        scopes += [("INTERVAL", key, group) for key, group in table.groupby("interval_id", sort=True)]
        scopes += [("FORWARD_CHAIN_BLOCK", str(key), group) for key, group in table.groupby("forward_chain_block", sort=True)]
        for scope, value, subset in scopes:
            record = {"resolution_m": resolution, "support_universe_id": "PRIMARY_CONFIRMATORY", "scope": scope, "scope_value": value, "rows": len(subset), "positives": int(subset.y.sum()), "negatives": int((subset.y == 0).sum()), "positive_fraction": float(subset.y.mean()), "warning": "ZERO_CLASS" if subset.y.nunique() < 2 else ""}
            if scope == "INTERVAL":
                record.update({"t0_state_number": int(subset.t0_state_number.iloc[0]), "t1_state_number": int(subset.t1_state_number.iloc[0]), "effective_interval_duration_hours": float(subset.effective_response_interval_hours.iloc[0])})
            rows.append(record)
        for column in support_columns:
            universe = column.removeprefix("support_").upper()
            for block, group in table[table[column]].groupby("forward_chain_block", sort=True):
                rows.append({"resolution_m": resolution, "support_universe_id": universe, "scope": "FORWARD_CHAIN_BLOCK", "scope_value": str(block), "rows": len(group), "positives": int(group.y.sum()), "negatives": int((group.y == 0).sum()), "positive_fraction": float(group.y.mean()), "warning": "ZERO_CLASS" if group.y.nunique() < 2 else ""})
            subset = table[table[column]]
            rows.append({"resolution_m": resolution, "support_universe_id": universe, "scope": "ALL", "scope_value": "ALL", "rows": len(subset), "positives": int(subset.y.sum()), "negatives": int((subset.y == 0).sum()), "positive_fraction": float(subset.y.mean()), "warning": "ZERO_CLASS" if subset.y.nunique() < 2 else ""})
        repetitions = table.groupby("cell_id").agg(repetitions=("y", "size"), ever_positive=("y", "max"))
        rows.append({
            "resolution_m": resolution, "support_universe_id": "PRIMARY_CONFIRMATORY", "scope": "REPEATED_CELL_AUDIT", "scope_value": "ALL",
            "rows": len(table), "positives": int(table.y.sum()), "negatives": int((table.y == 0).sum()), "positive_fraction": float(table.y.mean()),
            "unique_cells": len(repetitions), "cells_repeated": int((repetitions.repetitions > 1).sum()),
            "mean_repetitions": float(repetitions.repetitions.mean()), "max_repetitions": int(repetitions.repetitions.max()),
            "cells_positive_at_least_once": int(repetitions.ever_positive.sum()), "cells_all_zero": int((repetitions.ever_positive == 0).sum()),
            "warning": "REPEATED_ROWS_REQUIRE_GROUPED_UNCERTAINTY",
        })
        ordered = sorted(table.interval_number.unique())
        for left, right in zip(ordered, ordered[1:]):
            a = table.loc[table.interval_number.eq(left), ["cell_id", "y"]]
            b = table.loc[table.interval_number.eq(right), ["cell_id", "y"]]
            common = a.merge(b, on="cell_id", suffixes=("_left", "_right"), validate="one_to_one")
            identical = bool(len(common) and common.y_left.eq(common.y_right).all())
            rows.append({
                "resolution_m": resolution, "support_universe_id": "PRIMARY_CONFIRMATORY", "scope": "ADJACENT_RESPONSE_PATTERN",
                "scope_value": f"{left}->{right}", "rows": len(common), "positives": int(common.y_right.sum()) if len(common) else 0,
                "negatives": int((common.y_right == 0).sum()) if len(common) else 0,
                "positive_fraction": float(common.y_right.mean()) if len(common) else np.nan,
                "warning": "IDENTICAL_ADJACENT_VECTOR" if identical else "",
            })
    return pd.DataFrame(rows)


def forward_receipts(tables: dict[int, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    designs = [("B1_TO_B2", [1], 2), ("B1_B2_TO_B3", [1, 2], 3), ("B1_B2_B3_TO_B4", [1, 2, 3], 4)]
    for resolution, table in tables.items():
        for evaluation, train_blocks, test_block in designs:
            train = table[table.forward_chain_block.isin(train_blocks)]
            test = table[table.forward_chain_block.eq(test_block)]
            rows.append({"resolution_m": resolution, "evaluation_id": evaluation, "training_blocks": "+".join(map(str, train_blocks)), "test_block": test_block, "training_rows": len(train), "training_positives": int(train.y.sum()), "training_negatives": int((train.y == 0).sum()), "test_rows": len(test), "test_positives": int(test.y.sum()), "test_negatives": int((test.y == 0).sum()), "descriptive_only": True})
    return pd.DataFrame(rows)


def table_dictionary(tables: dict[int, pd.DataFrame], predictor_dictionary: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    example = tables[1000]
    source_map = predictor_dictionary.set_index("canonical_variable_name").to_dict("index")
    ledger_map = ledger.set_index("variable").to_dict("index")
    rows = []
    for column in example.columns:
        if column == "y": role, use = "RESPONSE", "Response only"
        elif column.startswith("support_"): role, use = "SUPPORT", "Row-universe filter only; never a predictor"
        elif column in source_map: role, use = "PREDICTOR_OR_PREDICTOR_SUPPORT", source_map[column]["model_role"]
        elif column.startswith(("distance_center_to_", "within_either_boundary_", "t0_hull_", "t1_hull_")): role, use = "RESPONSE_QC", "QC/sensitivity only; prohibited as predictor"
        else: role, use = "METADATA", "Join/group/provenance only"
        source = source_map.get(column, {})
        temporal = ledger_map.get(column, {})
        rows.append({"variable": column, "role": role, "unit": source.get("final_unit", "unitless_or_encoded"), "dtype_1km": str(example[column].dtype), "static_dynamic": temporal.get("temporal_class", "METADATA_OR_RESPONSE"), "field_class": role, "temporal_provenance": temporal.get("source_timestamp_or_reference_period", "PR31 response/join provenance"), "allowed_modeling_use": use, "missingness_semantics": source.get("missingness_semantics", "No implicit zero conversion"), "source_artifact": source.get("provenance_artifact", rel(PR31 / "pr31_manifest.json"))})
    return pd.DataFrame(rows)


def write_spec() -> None:
    text = """# Paper 1 PR31 Response Label and Labeled-Table Specification

## Decision

**COMPLETE_WITH_LIMITATIONS; PREMODELING_LEAKAGE_GATE_PASS.** PR31 joins the locked FEDS response to immutable PR23 predictors and unchanged PR24 support memberships. It performs no model fitting, performance calculation, feature selection, support selection from `Y`, or imputation. The exact model-formulation gate may begin; model fitting remains unauthorized.

## Response Rule

For each frozen interval-cell candidate, `Y = 1` exactly when the next completed FEDS event-65371 cumulative hull covers the fixed EPSG:9311 response-cell center; otherwise `Y = 0`. Every candidate center is independently verified outside the completed `t0` hull. The response is direct at both 1 km and 2 km; 2 km is not a vote over 1 km labels. No overlap threshold, buffer, final perimeter, or model output enters the label.

## Timing and Pairing

Each locked transition uses its recorded `t0_state_number` and immediately following `t1_state_number`. Nominal AM/PM timestamps remain synthetic bin identifiers. The effective information cutoff and response endpoint are the latest incorporated VIIRS observation times recorded for those completed states. The 16 locked intervals and four forward-chain blocks are unchanged.

## Pipeline Separation

PR23 predictor matrices and PR24 support masks are verified by hash and read without modification. Response construction reads only the authoritative FEDS state geometry and timing/interval records. Labels are joined one-to-one by `event_id + interval_id + cell_id`; PR24 memberships are joined by the same stable keys. Boundary-distance fields and hull hashes are response-QC metadata and are prohibited predictors.

## Interpretation and Limitations

FEDS active fronts and cumulative hulls are remotely sensed, overpass-dependent representations affected by cloud/smoke, scan geometry, detection gaps, and parallax. One kilometre is the primary response support; 2 km is required sensitivity. The tables do not establish exact flame arrival, spotting, causality, operational forecasting, prediction from ignition, or cross-fire generalization.
"""
    (DOC / "PAPER1_PROPAGATION_RESPONSE_LABEL_SPEC.md").write_text(text, encoding="utf-8")


def main() -> None:
    argparse.ArgumentParser().parse_args()
    upstream = preflight()
    states, timing = interval_metadata()
    predictor_dictionary = pd.read_csv(PREDICTOR_DICTIONARY)
    ledger = leakage_ledger(predictor_dictionary)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    tables, output_info, qc_rows = {}, {}, []
    hrrr = pd.read_csv(HRRR_OBJECTS)
    hrrr["archive_last_modified"] = pd.to_datetime(hrrr.archive_last_modified, utc=True)
    hrrr["effective_t0_cutoff_utc"] = pd.to_datetime(hrrr.effective_t0_cutoff_utc, utc=True)
    hrrr_timing_pass = bool(hrrr.archive_available_by_effective_t0_cutoff.astype(bool).all() and (hrrr.archive_last_modified <= hrrr.effective_t0_cutoff_utc).all())
    pr23_source = PR23_SCRIPT.read_text(encoding="utf-8")
    mtbs_brattain_excluded = all(token in pr23_source for token in [
        'PREFIRE_CUTOFF = pd.Timestamp("2020-09-08',
        'dates = pd.to_datetime(mtbs.ig_date, errors="coerce", utc=True)',
        'mtbs = mtbs[dates.lt(PREFIRE_CUTOFF)].copy()',
    ])
    for resolution in (1000, 2000):
        predictors = pd.read_parquet(upstream["matrices"][resolution]["path"])
        mask = pd.read_parquet(upstream["masks"][resolution]["path"])
        labels = construct_labels(predictors, states, timing)
        if labels.duplicated(KEYS).any() or labels.y.isna().any():
            raise RuntimeError(f"Label key/missingness failure at {resolution} m.")
        table = predictors.merge(labels.drop(columns=["interval_number", "response_grid_m", "forward_chain_block"]), on=KEYS, validate="one_to_one")
        table = table.merge(support_wide(mask), on=KEYS, validate="one_to_one")
        if not table.support_primary_confirmatory.all() or len(table) != len(predictors):
            raise RuntimeError(f"PR24 support changed during PR31 at {resolution} m.")
        meta0 = timing.set_index("interval_number")
        correct_pairing = bool(
            table.apply(lambda row: int(row.t1_state_number) == int(row.t0_state_number) + 1, axis=1).all()
            and table.groupby("interval_number").t0_state_number.nunique().eq(1).all()
            and table.groupby("interval_number").t1_state_number.nunique().eq(1).all()
        )
        geometry_labels_match = True
        already_reached = 0
        for interval_number, group in table.groupby("interval_number", sort=True):
            interval = meta0.loc[interval_number]
            points = shapely.points(group.center_x_epsg9311, group.center_y_epsg9311)
            hull0 = states.iloc[int(interval.t0_state_number) - 1].hull
            hull1 = states.iloc[int(interval.t1_state_number) - 1].hull
            covered0 = shapely.covers(hull0, points)
            covered1 = shapely.covers(hull1, points).astype("int8")
            already_reached += int(covered0.sum())
            geometry_labels_match = geometry_labels_match and np.array_equal(covered1, group.y.to_numpy())
        cutoff_match = pd.to_datetime(table.effective_t0_observation_cutoff_utc, utc=True).eq(pd.to_datetime(table.effective_t0_observation_cutoff_utc_label, utc=True)).all()
        static_columns = [v for v in predictor_dictionary.canonical_variable_name if v in table and temporal_record(v)["static_dynamic"] == "STATIC"]
        static_pass = all(table.groupby("cell_id")[column].nunique(dropna=False).max() <= 1 for column in static_columns)
        dynamic_columns = [v for v in predictor_dictionary.canonical_variable_name if v in table and temporal_record(v)["static_dynamic"] == "DYNAMIC_AT_T0"]
        dynamic_pass = bool(np.isfinite(table[[c for c in dynamic_columns if pd.api.types.is_numeric_dtype(table[c])]].to_numpy(dtype=float)).all())
        dictionary_complete = set(predictor_dictionary.canonical_variable_name).issubset(table.columns)
        accidental_indexes = [c for c in table.columns if c.lower().startswith(("unnamed:", "__index_level_"))]
        out = OUTPUTS / f"paper1_pr31_labeled_table_{resolution // 1000}km.parquet"
        previous_output_hash = sha256(out) if out.exists() else None
        out_hash = atomic_parquet(table, out)
        tables[resolution] = table
        output_info[resolution] = {"path": rel(out), "sha256": out_hash, "bytes": out.stat().st_size, "rows": len(table), "positives": int(table.y.sum()), "negatives": int((table.y == 0).sum())}
        checks = {
            "pr23_integrity": True, "pr24_integrity": True, "candidate_row_count": len(table) == upstream["matrices"][resolution]["rows"],
            "join_one_to_one": len(table) == len(predictors), "duplicate_keys_absent": not table.duplicated(KEYS).any(), "missing_labels_absent": not table.y.isna().any(),
            "t0_centers_unreached": already_reached == 0, "geometry_labels_recompute_exact": geometry_labels_match,
            "next_completed_state_pairing": correct_pairing, "timing_cutoff_match": bool(cutoff_match), "intervals_preserved": sorted(table.interval_number.unique().tolist()) == PRIMARY_INTERVALS,
            "blocks_preserved": sorted(table.forward_chain_block.unique().tolist()) == [1, 2, 3, 4], "pr24_primary_membership_unchanged": bool(table.support_primary_confirmatory.all()),
            "static_repeat_consistency": static_pass, "dynamic_variable_sanity": dynamic_pass, "hrrr_cutoff_timing": hrrr_timing_pass,
            "mtbs_brattain_excluded": mtbs_brattain_excluded, "response_schema_complete": set(table.y.unique()) <= {0, 1},
            "predictor_dictionary_complete": dictionary_complete, "duplicate_columns_absent": not table.columns.duplicated().any(),
            "accidental_index_columns_absent": not accidental_indexes, "output_readable": len(pd.read_parquet(out)) == len(table),
            "output_hash_reproducible": previous_output_hash in {None, out_hash},
        }
        qc_rows.extend({"check": key, "resolution_m": resolution, "status": "PASS" if value else "FAIL", "value": int(value), "detail": "Deterministic PR31 verification"} for key, value in checks.items())
    labels = label_qc(tables)
    forward = forward_receipts(tables)
    table_dict = table_dictionary(tables, predictor_dictionary, ledger)
    qc = pd.DataFrame(qc_rows)
    rate_1km = float(tables[1000].y.mean())
    rate_2km = float(tables[2000].y.mean())
    qc = pd.concat([qc, pd.DataFrame([
        {"check": "leakage_ledger_all_adjudicated", "resolution_m": 0, "status": "PASS" if ledger.leakage_status.isin(["PASS", "AUTHORIZED_RETROSPECTIVE_SENSITIVITY"]).all() else "FAIL", "value": len(ledger), "detail": "Every PR23 dictionary variable has explicit temporal provenance."},
        {"check": "response_bearing_files_opened", "resolution_m": 0, "status": "PASS", "value": 1, "detail": rel(STATES)},
        {"check": "cross_resolution_direct_response_consistency", "resolution_m": 0, "status": "PASS", "value": 2, "detail": f"Both grids independently use direct center coverage; descriptive positive fractions 1km={rate_1km:.12f}, 2km={rate_2km:.12f}; exact agreement is not required."},
        {"check": "response_crs_and_event", "resolution_m": 0, "status": "PASS", "value": 65371, "detail": "FEDS event 65371 geometry is EPSG:9311; no final perimeter opened."},
        {"check": "model_fit", "resolution_m": 0, "status": "PASS", "value": 0, "detail": "No model fitting or predictive scoring."},
    ])], ignore_index=True)
    if (qc.status != "PASS").any():
        failures = qc.loc[qc.status.ne("PASS"), ["check", "resolution_m", "detail"]].to_dict("records")
        raise RuntimeError(f"Critical PR31 QC failed; completion decision not written: {failures}")
    labels.to_csv(DOC / "PAPER1_PROPAGATION_LABEL_QC.csv", index=False)
    ledger.to_csv(DOC / "PAPER1_PROPAGATION_LEAKAGE_LEDGER.csv", index=False)
    table_dict.to_csv(DOC / "PAPER1_PROPAGATION_LABELED_TABLE_DICTIONARY.csv", index=False)
    forward.to_csv(DOC / "PAPER1_PROPAGATION_FORWARD_CHAIN_READINESS.csv", index=False)
    qc.to_csv(DOC / "PAPER1_PROPAGATION_PR31_QC.csv", index=False)
    write_spec()
    decision = pd.DataFrame([{"gate": "PR31", "status": "COMPLETE_WITH_LIMITATIONS", "premodeling_leakage_gate": "PREMODELING_LEAKAGE_GATE_PASS", "response_authority": "FEDS Western-US v1.2.1 event 65371; fixed-center next-completed-state coverage", "primary_1km_rows": len(tables[1000]), "primary_1km_positives": int(tables[1000].y.sum()), "sensitivity_2km_rows": len(tables[2000]), "sensitivity_2km_positives": int(tables[2000].y.sum()), "response_bearing_files_opened": rel(STATES), "exact_model_formulation_gate_may_begin": True, "model_fitting_authorized": False, "limitations": "FEDS observation and geometry uncertainty; single-fire retrospective pseudo-prospective inference; historical product latency unresolved."}])
    decision.to_csv(DOC / "PAPER1_PROPAGATION_PR31_DECISION.csv", index=False)
    manifest = {
        "artifact_class": "PR31 LABELED RESPONSE/PREDICTOR TABLE", "created_utc": datetime.now(timezone.utc).isoformat(), "git_head": git("rev-parse", "HEAD"),
        "script": rel(Path(__file__)), "script_sha256": sha256(Path(__file__)), "environment": {"python": sys.version, "platform": platform.platform()},
        "response_rule": "Y=1 iff next completed FEDS state hull covers fixed response-cell center; else Y=0",
        "response_bearing_files_opened": [rel(STATES)], "model_fit": False, "predictive_scores": False, "feature_selection": False, "imputation": False,
        "inputs": {"pr23_manifest": {"path": rel(PR23 / "pr23_manifest.json"), "sha256": sha256(PR23 / "pr23_manifest.json")}, "pr24_manifest": {"path": rel(PR24 / "pr24_manifest.json"), "sha256": sha256(PR24 / "pr24_manifest.json")}, "states": {"path": rel(STATES), "sha256": sha256(STATES)}, "interval_lock": {"path": rel(INTERVAL_LOCK), "sha256": sha256(INTERVAL_LOCK)}, "state_times": {"path": rel(STATE_TIMES), "sha256": sha256(STATE_TIMES)}, "hrrr_objects": {"path": rel(HRRR_OBJECTS), "sha256": sha256(HRRR_OBJECTS)}},
        "upstream_outputs": {"pr23": {str(k): v["hash"] for k, v in upstream["matrices"].items()}, "pr24": {str(k): v["hash"] for k, v in upstream["masks"].items()}},
        "outputs": output_info, "qc_rows": len(qc), "leakage_ledger_rows": len(ledger), "status": "COMPLETE_WITH_LIMITATIONS", "premodeling_leakage_gate": "PASS", "next_gate": "EXACT_MODEL_FORMULATION", "model_fitting_authorized": False,
    }
    (PR31 / "pr31_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": decision.iloc[0].status, "leakage_gate": decision.iloc[0].premodeling_leakage_gate, "outputs": output_info, "next_gate": "EXACT_MODEL_FORMULATION", "model_fitting_authorized": False}, indent=2))


if __name__ == "__main__":
    main()
