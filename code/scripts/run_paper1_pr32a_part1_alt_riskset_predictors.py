"""Build invariant PR32A-1 response-free alternate-risk-set predictor tables.

Predictors are aggregated once on a canonical union per resolution, then each
locked risk set is an exact key subset. No response-bearing artifact is read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from eccodes import codes_get_array, codes_grib_new_from_file, codes_release
from pyproj import Proj, Transformer

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "documentation"
OUTPUT_ROOT = ROOT / "data/processed/propagation/paper1/pr32a_alt_riskset_response_free"
STATE_PATH = ROOT / "data/processed/feasibility/paper1_feds_validation/extracted/feds_event_65371_states.parquet"
LOCK_PATH = DOC / "PAPER1_PROPAGATION_INTERVAL_LOCK.csv"
PR23_SCRIPT = ROOT / "scripts/run_paper1_pr23.py"
PRIMARY_SOURCE = ROOT / "data/processed/propagation/paper1/pr23_response_free_predictors/source"
PRIMARY_OUTPUT = ROOT / "data/processed/propagation/paper1/pr23_response_free_predictors/outputs"
INTERVALS = [1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22]
RULES = {"ACTIVE_FRONT_ONLY_5KM": "A", "PERIMETER_ONLY_2KM": "P", "PERIMETER_ONLY_5KM": "P5"}
EXPECTED = {"ACTIVE_FRONT_ONLY_5KM": {1000: 2867, 2000: 730}, "PERIMETER_ONLY_2KM": {1000: 1539, 2000: 386}, "PERIMETER_ONLY_5KM": {1000: 4472, 2000: 1139}}
KEYS = ["event_id", "interval_id", "response_grid_m", "cell_id"]
PRIMARY_OUTPUT_SHA256 = {
    1000: "46c7c1cf208dace65a9c19e3f4b490fe9fa0592ad832856f44412556a0b5d2a5",
    2000: "f33d54d8158290feb4bb6a760812e5f6cedf357f6d128333ca601d1ab15e6626",
}
CANONICAL_OUTPUT_SHA256 = {
    1000: "338f968eab9201af0114eed68bf8787fd6149f707875dbbaca6b0f44bc20f681",
    2000: "c8e51a1e1633873c56cd10225638fa84aea39ac3b010540a063ca227df5c8bc3",
}
CANONICAL_CANDIDATE_SHA256 = "d534a224429464056859b395b6653e47a662c9a4cddaeee0b16d5d2f4116ae3e"
CANONICAL_PR23_SCRIPT_SHA256 = "edbfee232ad32b5d0ae08e8b4211ab28c1a33f4510aaaf090351d9426a7852fe"

# Only these fields differ when source float32 HRRR messages are read directly
# for canonical keys instead of from PR23's saved float32 bilinear extracts.
PRIMARY_OVERLAP_TOLERANCES = {
    "hrrr_temperature_2m_mean_c": (2e-5, "degrees C", "direct source float32 reconstruction"),
    "hrrr_relative_humidity_2m_min_pct": (5e-6, "percent", "direct source float32 reconstruction"),
    "hrrr_gust_max_ms": (5e-7, "m/s", "direct source float32 reconstruction"),
    "hrrr_u10_mean_earth_ms": (5e-7, "m/s", "direct source float32 reconstruction"),
    "hrrr_v10_mean_earth_ms": (5e-7, "m/s", "direct source float32 reconstruction"),
    "wind_slope_alignment": (1e-7, "unitless", "deterministically derived from HRRR vectors"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_frame(rule: str, size: int) -> pd.DataFrame:
    states = gpd.read_parquet(STATE_PATH, columns=["hull", "fline"]).reset_index(drop=True)
    locks = pd.read_csv(LOCK_PATH)
    rows = []
    for interval in INTERVALS:
        lock = locks.loc[locks.interval_number.eq(interval)].iloc[0]
        state = states.iloc[int(lock.t0_state_number) - 1]
        hull, front = state.hull, state.fline
        min_x, min_y, max_x, max_y = hull.buffer(5000).bounds
        cols = np.arange(np.floor(min_x / size), np.ceil(max_x / size), dtype=int)
        grid_rows = np.arange(np.floor(min_y / size), np.ceil(max_y / size), dtype=int)
        cc, rr = np.meshgrid(cols, grid_rows)
        x, y = (cc.ravel() + 0.5) * size, (rr.ravel() + 0.5) * size
        points = shapely.points(x, y)
        active = shapely.distance(points, front) <= 5000
        perimeter = shapely.distance(points, hull.boundary) <= 2000
        perimeter_5km = shapely.distance(points, hull.boundary) <= 5000
        selected = {"A": active, "P": perimeter, "P5": perimeter_5km}[RULES[rule]]
        keep = ~shapely.covers(hull, points) & selected
        a, p = active[keep], perimeter[keep]
        membership = np.select(
            [a & ~p, ~a & p, a & p, ~a & ~p],
            ["ACTIVE_ONLY", "PERIMETER_BACKSTOP_ONLY", "BOTH", "NEITHER_PRIMARY_COMPONENT"],
            default="INVALID",
        )
        block = 1 if interval in [1, 3, 4, 5] else 2 if interval in [6, 8, 9, 10] else 3 if interval in [11, 12, 14, 15] else 4
        rows.append(pd.DataFrame({
            "response_grid_m": size, "interval_number": interval, "forward_chain_block": block,
            "cell_id": [f"EPSG9311_{size}_{col}_{row}" for col, row in zip(cc.ravel()[keep], rr.ravel()[keep])],
            "col": cc.ravel()[keep], "row": rr.ravel()[keep], "center_x_epsg9311": x[keep], "center_y_epsg9311": y[keep],
            "distance_t0_active_front_m": shapely.distance(points[keep], front),
            "distance_t0_cumulative_perimeter_m": shapely.distance(points[keep], hull.boundary),
            "risk_membership": membership, "t0_cumulative_area_km2": hull.area / 1e6,
            "t0_perimeter_length_km": hull.boundary.length / 1000, "t0_active_front_length_km": front.length / 1000,
        }))
    frame = pd.concat(rows, ignore_index=True)
    if len(frame) != EXPECTED[rule][size] or frame.duplicated(["interval_number", "cell_id"]).any():
        raise RuntimeError(f"Candidate construction failed for {rule} at {size} m")
    return frame


def construct_unions() -> tuple[dict[tuple[str, int], pd.DataFrame], dict[int, pd.DataFrame]]:
    masks = {(rule, size): candidate_frame(rule, size) for rule in RULES for size in (1000, 2000)}
    unions = {}
    for size in (1000, 2000):
        union = pd.concat([masks[(rule, size)] for rule in RULES], ignore_index=True)
        union = union.drop_duplicates(["interval_number", "cell_id"]).sort_values(["interval_number", "row", "col"]).reset_index(drop=True)
        if union.duplicated(["interval_number", "cell_id"]).any():
            raise RuntimeError(f"Nonunique canonical union at {size} m")
        unions[size] = union
    return masks, unions


def scoped_cleanup() -> None:
    expected = OUTPUT_ROOT.resolve()
    for name in ["canonical", *RULES]:
        target = (OUTPUT_ROOT / name).resolve()
        if target.parent != expected:
            raise RuntimeError("Refusing output cleanup outside the governed PR32A directory")
        if target.exists():
            shutil.rmtree(target)


def canonical_hrrr_values(frame: pd.DataFrame, size: int) -> pd.DataFrame:
    """Reconstruct locked HRRR values for canonical keys from local messages only."""
    work = ROOT / "data/processed/feasibility/paper1_hrrr_primary"
    inventory = pd.read_csv(work / "preflight_message_inventory.csv")
    fields = ["u10", "v10", "gust_surface", "temperature_2m", "relative_humidity_2m"]
    inventory = inventory[inventory.field_key.isin(fields)]
    hrrr_crs = "+proj=lcc +lat_0=38.5 +lon_0=-97.5 +lat_1=38.5 +lat_2=38.5 +R=6371229 +units=m +no_defs"
    to_hrrr, to_lonlat = Transformer.from_crs(9311, hrrr_crs, always_xy=True), Transformer.from_crs(9311, 4326, always_xy=True)
    parts = []
    for interval in INTERVALS:
        subset = frame[(frame.response_grid_m.eq(size)) & (frame.interval_number.eq(interval))]
        xh, yh = to_hrrr.transform(subset.center_x_epsg9311.to_numpy(), subset.center_y_epsg9311.to_numpy())
        fx, fy = (np.asarray(xh) + 2697520.14252193) / 3000, (np.asarray(yh) + 1587306.1525566636) / 3000
        ix, iy, wx, wy = np.floor(fx).astype(int), np.floor(fy).astype(int), fx - np.floor(fx), fy - np.floor(fy)
        values = {}
        for field in fields:
            records = inventory[(inventory.interval_number.eq(interval)) & (inventory.field_key.eq(field))].sort_values("forecast_valid_time_utc")
            samples = []
            for record in records.itertuples(index=False):
                name = f"hrrr_{pd.Timestamp(record.initialization_utc).strftime('%Y%m%d%H')}_f{int(record.lead):02d}_{record.field_key}.grib2"
                with (work / "source_messages" / name).open("rb") as stream:
                    handle = codes_grib_new_from_file(stream)
                    native = codes_get_array(handle, "values")
                    codes_release(handle)
                samples.append(native[iy * 1799 + ix] * (1 - wx) * (1 - wy) + native[iy * 1799 + ix + 1] * wx * (1 - wy) + native[(iy + 1) * 1799 + ix] * (1 - wx) * wy + native[(iy + 1) * 1799 + ix + 1] * wx * wy)
            times = pd.to_datetime(records.forecast_valid_time_utc, utc=True).astype("int64").to_numpy() / 1e9
            start, end = pd.Timestamp(records.effective_t0_cutoff_utc.iloc[0]).value / 1e9, pd.Timestamp(records.effective_t1_observation_utc.iloc[0]).value / 1e9
            knots = np.r_[start, times[(times > start) & (times < end)], end]
            source = np.vstack(samples)
            bracketed = np.vstack([np.array([np.interp(knot, times, source[:, j]) for j in range(source.shape[1])]) for knot in knots])
            values[field] = np.max(bracketed, axis=0) if field == "gust_surface" else np.min(bracketed, axis=0) if field == "relative_humidity_2m" else np.sum((bracketed[:-1] + bracketed[1:]) * 0.5 * np.diff(knots)[:, None], axis=0) / (end - start)
        lon, lat = to_lonlat.transform(subset.center_x_epsg9311.to_numpy(), subset.center_y_epsg9311.to_numpy())
        convergence = np.deg2rad(np.asarray(Proj(hrrr_crs).get_factors(lon, lat).meridian_convergence))
        parts.append(pd.DataFrame({"_index": subset.index, "hrrr_u10_mean_earth_ms": values["u10"] * np.cos(convergence) + values["v10"] * np.sin(convergence), "hrrr_v10_mean_earth_ms": -values["u10"] * np.sin(convergence) + values["v10"] * np.cos(convergence), "hrrr_gust_max_ms": values["gust_surface"], "hrrr_temperature_2m_mean_c": values["temperature_2m"] - 273.15, "hrrr_relative_humidity_2m_min_pct": values["relative_humidity_2m"]}).set_index("_index"))
    return pd.concat(parts).sort_index()


def execute_pr23_once(unions: dict[int, pd.DataFrame]) -> tuple[dict[int, pd.DataFrame], Path]:
    canonical = OUTPUT_ROOT / "canonical"
    outputs, staging = canonical / "outputs", canonical / "documentation_staging"
    outputs.mkdir(parents=True, exist_ok=True)
    staging.mkdir(exist_ok=True)
    candidate_path = canonical / "canonical_alt_riskset_union_candidates.parquet"
    pd.concat([unions[1000], unions[2000]], ignore_index=True).to_parquet(candidate_path, index=False)
    code = PR23_SCRIPT.read_text(encoding="utf-8")
    code = code.replace(
        'if len(candidates) != 4153 or candidates.response_grid_m.value_counts().to_dict() != {1000: 3317, 2000: 836}:\n        raise ValueError("Locked candidate geometry count changed")',
        'if candidates.empty:\n        raise ValueError("Empty canonical response-free union")',
    )
    code = code.replace('geom = state.hull.boundary if row.hybrid_membership == "PERIMETER_BACKSTOP_ONLY" else state.fline', 'geom = state.fline if row.distance_t0_active_front_m <= 5000 else state.hull.boundary')
    code = code.replace('pd.read_csv(DOC / "PAPER1_HRRR_SELECTED_OBJECTS.csv")', 'pd.read_csv(ROOT / "documentation" / "PAPER1_HRRR_SELECTED_OBJECTS.csv")')
    namespace = {"__file__": str(PR23_SCRIPT), "__name__": "pr32a_canonical_pr23_reuse"}
    exec(compile(code, str(PR23_SCRIPT), "exec"), namespace)
    namespace["CANDIDATES"] = candidate_path
    namespace["WORK"], namespace["OUTPUT"], namespace["SOURCE"], namespace["DOC"] = canonical, outputs, PRIMARY_SOURCE, staging
    namespace["RECEIPTS"] = ROOT / "data/processed/propagation/paper1/pr23_response_free_predictors/receipts"
    namespace["hrrr_values"] = canonical_hrrr_values
    namespace["main"](False)
    return {size: pd.read_parquet(outputs / f"paper1_pr23_response_free_predictors_{size // 1000}km.parquet") for size in (1000, 2000)}, canonical


def compare(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, float | int]:
    a, b = left.set_index(KEYS), right.set_index(KEYS)
    common = a.index.intersection(b.index)
    a, b = a.loc[common], b.loc[common]
    categorical, maximum = 0, 0.0
    for column in [c for c in a.columns if c in b.columns and c not in {"artifact_class", "risk_set_id", "terrain_source_type"}]:
        if pd.api.types.is_numeric_dtype(a[column]):
            left_values, right_values = a[column].to_numpy(float), b[column].to_numpy(float)
            missing_mismatch = np.isnan(left_values) != np.isnan(right_values)
            if missing_mismatch.any():
                categorical += int(missing_mismatch.sum())
            both_finite = np.isfinite(left_values) & np.isfinite(right_values)
            if both_finite.any():
                maximum = max(maximum, float(np.abs(left_values[both_finite] - right_values[both_finite]).max()))
        else:
            categorical += int((a[column].fillna("__NA__").astype(str) != b[column].fillna("__NA__").astype(str)).sum())
    return {"overlap_rows": len(common), "categorical_mismatches": categorical, "maximum_numeric_difference": maximum}


def primary_overlap_audit(canonical: pd.DataFrame, primary: pd.DataFrame, size: int) -> tuple[pd.DataFrame, dict[str, object]]:
    left, right = primary.set_index(KEYS).sort_index(), canonical.set_index(KEYS).sort_index()
    common = left.index.intersection(right.index).sort_values()
    if len(common) != len(primary):
        raise RuntimeError(f"Primary key set is not fully contained in canonical output at {size} m")
    left, right = left.loc[common], right.loc[common]
    rows = []
    for field in left.columns:
        if field not in right.columns:
            raise RuntimeError(f"Canonical output lacks primary field {field!r} at {size} m")
        a, b = left[field], right[field]
        row = {"response_grid_m": size, "field": field, "overlap_rows": len(common)}
        if pd.api.types.is_bool_dtype(a) or pd.api.types.is_integer_dtype(a):
            equal = a.eq(b) | (a.isna() & b.isna())
            row.update({
                "comparison_class": "exact_integer_or_boolean",
                "differing_rows_exact": int((~equal).sum()),
                "missing_mask_mismatches": int((a.isna() != b.isna()).sum()),
                "maximum_absolute_difference": 0.0, "mean_absolute_difference": 0.0,
                "median_absolute_difference": 0.0, "p95_absolute_difference": 0.0,
                "p99_absolute_difference": 0.0, "maximum_relative_difference_at_max_abs": 0.0,
                "max_event_id": "", "max_interval_id": "", "max_cell_id": "",
                "primary_value_at_max": "", "canonical_value_at_max": "",
                "allowed_absolute_tolerance": 0.0, "units": "exact", "tolerance_rationale": "exact equality required",
                "status": "PASS" if equal.all() else "FAIL",
            })
        elif pd.api.types.is_numeric_dtype(a):
            a_values, b_values = a.to_numpy(float), b.to_numpy(float)
            missing_mismatch = np.isnan(a_values) != np.isnan(b_values)
            finite = np.isfinite(a_values) & np.isfinite(b_values)
            if not finite.all() and not np.array_equal(np.isnan(a_values), np.isnan(b_values)):
                raise RuntimeError(f"Nonmatching numeric missingness for {field!r} at {size} m")
            difference = np.zeros(len(common), dtype=float)
            difference[finite] = np.abs(a_values[finite] - b_values[finite])
            max_index = int(np.argmax(difference))
            tolerance, units, rationale = PRIMARY_OVERLAP_TOLERANCES.get(field, (0.0, "native units", "exact equality required"))
            denominator = max(abs(a_values[max_index]), abs(b_values[max_index]), np.finfo(float).tiny)
            row.update({
                "comparison_class": "floating_numeric",
                "differing_rows_exact": int((finite & (a_values != b_values)).sum()),
                "missing_mask_mismatches": int(missing_mismatch.sum()),
                "maximum_absolute_difference": float(difference.max()),
                "mean_absolute_difference": float(difference[finite].mean()) if finite.any() else 0.0,
                "median_absolute_difference": float(np.median(difference[finite])) if finite.any() else 0.0,
                "p95_absolute_difference": float(np.quantile(difference[finite], 0.95)) if finite.any() else 0.0,
                "p99_absolute_difference": float(np.quantile(difference[finite], 0.99)) if finite.any() else 0.0,
                "maximum_relative_difference_at_max_abs": float(difference[max_index] / denominator),
                "max_event_id": common[max_index][0], "max_interval_id": common[max_index][1],
                "max_cell_id": common[max_index][3], "primary_value_at_max": float(a_values[max_index]),
                "canonical_value_at_max": float(b_values[max_index]), "allowed_absolute_tolerance": tolerance,
                "units": units, "tolerance_rationale": rationale,
                "status": "PASS" if not missing_mismatch.any() and difference.max() <= tolerance else "FAIL",
            })
        else:
            equal = a.fillna("__NA__").astype(str) == b.fillna("__NA__").astype(str)
            row.update({
                "comparison_class": "exact_categorical_or_integer",
                "differing_rows_exact": int((~equal).sum()),
                "missing_mask_mismatches": int((a.isna() != b.isna()).sum()),
                "maximum_absolute_difference": 0.0, "mean_absolute_difference": 0.0,
                "median_absolute_difference": 0.0, "p95_absolute_difference": 0.0,
                "p99_absolute_difference": 0.0, "maximum_relative_difference_at_max_abs": 0.0,
                "max_event_id": "", "max_interval_id": "", "max_cell_id": "",
                "primary_value_at_max": "", "canonical_value_at_max": "",
                "allowed_absolute_tolerance": 0.0, "units": "exact", "tolerance_rationale": "exact equality required",
                "status": "PASS" if equal.all() else "FAIL",
            })
        rows.append(row)
    report = pd.DataFrame(rows)
    summary = {
        "overlap_rows": len(common),
        "categorical_mismatches": int(report.loc[report.comparison_class.ne("floating_numeric"), "differing_rows_exact"].sum()),
        "numeric_fields_with_nonzero_difference": int(((report.comparison_class.eq("floating_numeric")) & (report.maximum_absolute_difference.gt(0))).sum()),
        "maximum_numeric_difference": float(report.maximum_absolute_difference.max()),
        "status": "PASS" if report.status.eq("PASS").all() else "FAIL",
    }
    return report, summary


def canonical_paths() -> tuple[Path, Path, Path]:
    canonical = OUTPUT_ROOT / "canonical"
    return canonical, canonical / "outputs", canonical / "canonical_alt_riskset_union_candidates.parquet"


def load_validated_canonical(unions: dict[int, pd.DataFrame]) -> tuple[dict[int, pd.DataFrame], Path]:
    canonical, outputs, candidate_path = canonical_paths()
    manifest_path = canonical / "pr23_manifest.json"
    for path in [candidate_path, manifest_path, *(outputs / f"paper1_pr23_response_free_predictors_{size // 1000}km.parquet" for size in (1000, 2000))]:
        if not path.exists():
            raise FileNotFoundError(f"Cannot resume: missing canonical artifact {path}")
    if sha256(candidate_path) != CANONICAL_CANDIDATE_SHA256:
        raise RuntimeError("Cannot resume: canonical candidate hash does not match the accepted PR32A-1C construction")
    candidate = pd.read_parquet(candidate_path)
    forbidden = {"y", "response", "label", "positive"}
    if forbidden.intersection(column.lower() for column in candidate.columns) or any("t1" in column.lower() for column in candidate.columns):
        raise RuntimeError("Cannot resume: canonical candidate artifact is not response-free")
    expected = pd.concat([unions[1000], unions[2000]], ignore_index=True)
    candidate_keys = candidate[["response_grid_m", "interval_number", "cell_id"]].sort_values(["response_grid_m", "interval_number", "cell_id"]).reset_index(drop=True)
    expected_keys = expected[["response_grid_m", "interval_number", "cell_id"]].sort_values(["response_grid_m", "interval_number", "cell_id"]).reset_index(drop=True)
    if not candidate_keys.equals(expected_keys):
        raise RuntimeError("Cannot resume: canonical candidate keys differ from the locked reconstructed union")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_class") != "PR23 RESPONSE-FREE PREDICTOR DATA" or manifest.get("script") != "scripts/run_paper1_pr23.py" or manifest.get("script_sha256") != CANONICAL_PR23_SCRIPT_SHA256:
        raise RuntimeError("Cannot resume: canonical manifest does not identify the committed PR23 aggregation")
    if manifest.get("candidate_geometry", {}).get("sha256") != CANONICAL_CANDIDATE_SHA256 or manifest.get("candidate_geometry", {}).get("rows") != len(expected):
        raise RuntimeError("Cannot resume: canonical manifest does not attest to the accepted candidate union")
    tables = {}
    for size in (1000, 2000):
        path = outputs / f"paper1_pr23_response_free_predictors_{size // 1000}km.parquet"
        if sha256(path) != CANONICAL_OUTPUT_SHA256[size]:
            raise RuntimeError(f"Cannot resume: canonical {size} m hash is not the accepted PR32A-1C output")
        if manifest.get("outputs", {}).get(str(size), {}).get("sha256") != CANONICAL_OUTPUT_SHA256[size]:
            raise RuntimeError(f"Cannot resume: manifest hash mismatch at {size} m")
        table = pd.read_parquet(path)
        primary_path = PRIMARY_OUTPUT / f"paper1_pr23_response_free_predictors_{size // 1000}km.parquet"
        if sha256(primary_path) != PRIMARY_OUTPUT_SHA256[size]:
            raise RuntimeError(f"Committed primary PR23 hash mismatch at {size} m")
        primary = pd.read_parquet(primary_path)
        if len(table) != len(unions[size]) or table.columns.tolist() != primary.columns.tolist():
            raise RuntimeError(f"Cannot resume: canonical schema or row count mismatch at {size} m")
        tables[size] = table
    return tables, canonical


def write_primary_overlap_audit(unions: dict[int, pd.DataFrame]) -> dict[str, object]:
    canonical_tables, _ = load_validated_canonical(unions)
    reports, summaries = [], {}
    for size, table in canonical_tables.items():
        primary = pd.read_parquet(PRIMARY_OUTPUT / f"paper1_pr23_response_free_predictors_{size // 1000}km.parquet")
        report, summary = primary_overlap_audit(table, primary, size)
        reports.append(report)
        summaries[str(size)] = summary
    audit = pd.concat(reports, ignore_index=True).sort_values(["response_grid_m", "maximum_absolute_difference", "field"], ascending=[True, False, True])
    audit.to_csv(DOC / "PAPER1_PR32A_PRIMARY_OVERLAP_NUMERICAL_AUDIT.csv", index=False)
    print(json.dumps({"primary_overlap": summaries, "response_bearing_files_opened": "NONE", "y_inspected": "NO"}, indent=2))
    if any(summary["status"] != "PASS" for summary in summaries.values()):
        raise RuntimeError("Primary-overlap numerical audit failed")
    return summaries


def cleanup_final_subsets() -> None:
    expected = OUTPUT_ROOT.resolve()
    for name in RULES:
        target = (OUTPUT_ROOT / name).resolve()
        if target.parent != expected:
            raise RuntimeError("Refusing final-subset cleanup outside the governed PR32A directory")
        if target.exists():
            shutil.rmtree(target)
    manifest = OUTPUT_ROOT / "pr32a_part1_manifest.json"
    if manifest.exists():
        manifest.unlink()


def finalize_subsets(masks: dict[tuple[str, int], pd.DataFrame], unions: dict[int, pd.DataFrame], canonical_tables: dict[int, pd.DataFrame], canonical: Path, run_mode: str) -> None:
    primary_overlap = write_primary_overlap_audit(unions)
    cleanup_final_subsets()
    report = {"response_bearing_files_opened": "NONE", "y_inspected": "NO", "source_acquisitions": [], "canonical_union_rows": {str(k): len(v) for k, v in unions.items()}, "tables": [], "primary_overlap": primary_overlap, "cross_risk": {}, "run_mode": run_mode}
    for size, table in canonical_tables.items():
        subsets = {}
        for rule in RULES:
            keys = masks[(rule, size)][["interval_number", "cell_id"]]
            result = table.merge(keys, on=["interval_number", "cell_id"], how="inner", validate="one_to_one")
            result["risk_set_id"] = rule
            result["terrain_source_type"] = np.where(result.distance_t0_active_front_m <= 5000, "ACTIVE_FRONT", "CUMULATIVE_HULL_BOUNDARY")
            result["event_id"] = "FEDS_65371_BRATTAIN"
            result["interval_id"] = result.interval_number.map(lambda value: f"FEDS65371_I{value:02d}")
            if len(result) != EXPECTED[rule][size] or result.duplicated(KEYS).any():
                raise RuntimeError(f"Subset QC failed for {rule} at {size} m")
            target = OUTPUT_ROOT / rule / "outputs" / f"paper1_pr32a_part1_{rule.lower()}_{size // 1000}km.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            result.to_parquet(target, index=False)
            subsets[rule] = result
            report["tables"].append({"risk_set_id": rule, "resolution_m": size, "rows": len(result), "columns": len(result.columns), "path": str(target.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(target)})
        report["cross_risk"][str(size)] = {f"{a}_vs_{b}": compare(subsets[a], subsets[b]) for a, b in [("ACTIVE_FRONT_ONLY_5KM", "PERIMETER_ONLY_2KM"), ("ACTIVE_FRONT_ONLY_5KM", "PERIMETER_ONLY_5KM"), ("PERIMETER_ONLY_2KM", "PERIMETER_ONLY_5KM")]}
        if any(value["categorical_mismatches"] or value["maximum_numeric_difference"] != 0 for value in report["cross_risk"][str(size)].values()):
            raise RuntimeError(f"Cross-risk invariance failed at {size} m")
    report.update({"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(), "script_sha256": sha256(Path(__file__)), "pr23_script_sha256": sha256(PR23_SCRIPT), "pr32a0_sha256": sha256(DOC / "PAPER1_HYBRID_MEMBERSHIP_AUTHORITY_AMENDMENT.md"), "pr32a1_sha256": sha256(DOC / "PAPER1_TERRAIN_SOURCE_AUTHORITY_AMENDMENT.md"), "environment": {"python": sys.version, "platform": platform.platform()}, "created_utc": datetime.now(timezone.utc).isoformat(), "canonical_path": str(canonical.relative_to(ROOT)).replace("\\", "/")})
    (OUTPUT_ROOT / "pr32a_part1_manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


def run(resume_canonical: bool = False) -> None:
    masks, unions = construct_unions()
    if resume_canonical:
        canonical_tables, canonical = load_validated_canonical(unions)
        finalize_subsets(masks, unions, canonical_tables, canonical, "resume_canonical")
    else:
        scoped_cleanup()
        canonical_tables, canonical = execute_pr23_once(unions)
        finalize_subsets(masks, unions, canonical_tables, canonical, "fresh_canonical_aggregation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true", help="Construct only response-free candidate unions.")
    parser.add_argument("--audit-primary-overlap", action="store_true", help="Audit the accepted canonical outputs without reaggregation.")
    parser.add_argument("--resume-canonical", action="store_true", help="Validate accepted canonical outputs and derive final subsets without reaggregation.")
    args = parser.parse_args()
    if args.preflight:
        _, unions = construct_unions()
        print(json.dumps({"canonical_union_rows": {str(size): len(frame) for size, frame in unions.items()}, "response_bearing_files_opened": "NONE", "y_inspected": "NO"}, indent=2))
    elif args.audit_primary_overlap:
        _, unions = construct_unions()
        write_primary_overlap_audit(unions)
    else:
        run(resume_canonical=args.resume_canonical)
