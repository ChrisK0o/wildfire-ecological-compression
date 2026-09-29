"""Attach the locked PR31 response to immutable PR32A alternate risk sets."""
from __future__ import annotations

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
PR32A = ROOT / "data/processed/propagation/paper1/pr32a_alt_riskset_response_free"
SUPPORT = PR32A / "support"
PR31 = ROOT / "data/processed/propagation/paper1/pr31_labeled_tables"
OUT = ROOT / "data/processed/propagation/paper1/pr32b_alt_riskset_labeled"
STATES = ROOT / "data/processed/feasibility/paper1_feds_validation/extracted/feds_event_65371_states.parquet"
LOCK = DOC / "PAPER1_PROPAGATION_INTERVAL_LOCK.csv"
TIMES = DOC / "PAPER1_FEDS_INFORMATION_TIME_BY_STATE.csv"
WHITELIST = DOC / "PAPER1_MODEL_PREDICTOR_WHITELIST.csv"
KEYS = ["event_id", "risk_set_id", "interval_id", "response_grid_m", "cell_id"]
PR31_KEYS = ["event_id", "interval_id", "response_grid_m", "cell_id"]
INTERVALS = [1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22]
NO_EARLY = [4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22]
EXPECTED_PART1_MANIFEST = "4a0a96cba26163152e882fe7d18c05cbb9c09cf480e21d08a4c11bab7d55235e"
EXPECTED = {
    ("ACTIVE_FRONT_ONLY_5KM", 1000): (2867, "2efc2075c7c645865ad592b0c26b1efcd7aa3ae9dab8a4a7ad86e370e1ffe9b7"),
    ("PERIMETER_ONLY_2KM", 1000): (1539, "43a53229b29f8cad3c176417a7f67fad5a2fa2596d726f4acb243bad958e4ed8"),
    ("PERIMETER_ONLY_5KM", 1000): (4472, "b59fe2ed3875a2c20da3cedb00a742de14379c7fee4a74999a4095b59248539e"),
    ("ACTIVE_FRONT_ONLY_5KM", 2000): (730, "f711c8177c6e670929f2414321ffb36da427e49b713f809d9e8f9f0227f790f2"),
    ("PERIMETER_ONLY_2KM", 2000): (386, "7adc8bedde2c0a63b821a83c44c744f30e6410d6710a619a8ab339d6b2655f5e"),
    ("PERIMETER_ONLY_5KM", 2000): (1139, "f2ab9151043a5fed700e54b79c9bbf4fcae7960e342252136d1a826948c85242"),
}


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


def predictor_path(risk: str, size: int) -> Path:
    return PR32A / risk / "outputs" / f"paper1_pr32a_part1_{risk.lower()}_{size // 1000}km.parquet"


def support_path(risk: str, size: int) -> Path:
    return SUPPORT / risk / "outputs" / f"paper1_pr32a_support_masks_{risk.lower()}_{size // 1000}km.parquet"


def read_frozen() -> tuple[dict[tuple[str, int], pd.DataFrame], dict[tuple[str, int], pd.DataFrame], dict[str, object], dict[str, object]]:
    p1_path, support_manifest_path = PR32A / "pr32a_part1_manifest.json", SUPPORT / "pr32a_manifest.json"
    if sha256(p1_path) != EXPECTED_PART1_MANIFEST:
        raise RuntimeError("Frozen PR32A-1 manifest hash mismatch.")
    p1, sm = json.loads(p1_path.read_text(encoding="utf-8")), json.loads(support_manifest_path.read_text(encoding="utf-8"))
    frames, masks = {}, {}
    support_lookup = {(x["risk_set_id"], int(x["resolution_m"])): x for x in sm["support_outputs"]}
    for key, (rows, expected_hash) in EXPECTED.items():
        risk, size = key
        path = predictor_path(risk, size)
        frame = pd.read_parquet(path)
        forbidden = [c for c in frame if c.lower() in {"y", "response", "label"} or "t1" in c.lower()]
        if sha256(path) != expected_hash or len(frame) != rows or frame.duplicated(KEYS).any() or forbidden:
            raise RuntimeError(f"Frozen predictor integrity failed: {path}")
        mask_path = support_path(risk, size)
        minfo = support_lookup[key]
        if sha256(mask_path) != minfo["sha256"]:
            raise RuntimeError(f"Frozen support-mask integrity failed: {mask_path}")
        mask = pd.read_parquet(mask_path)
        if mask.duplicated([*KEYS, "support_universe_id"]).any() or len(mask) != rows * 14:
            raise RuntimeError(f"Frozen support-mask schema failed: {mask_path}")
        frames[key], masks[key] = frame, mask
    return frames, masks, p1, sm


def timing() -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    states = gpd.read_parquet(STATES).sort_values("t").reset_index(drop=True)
    if states.crs is None or states.crs.to_epsg() != 9311 or set(states.fireID.dropna().astype(int)) != {65371}:
        raise RuntimeError("Response geometry is not FEDS event 65371 in EPSG:9311.")
    lock = pd.read_csv(LOCK)
    lock = lock.loc[lock.interval_number.isin(INTERVALS)].copy()
    if lock.interval_number.astype(int).tolist() != INTERVALS:
        raise RuntimeError("Locked interval sequence changed.")
    times = pd.read_csv(TIMES).set_index("state_number")
    rows = []
    for record in lock.itertuples(index=False):
        t0, t1 = int(record.t0_state_number), int(record.t1_state_number)
        if t1 != t0 + 1:
            raise RuntimeError(f"Interval {record.interval_number} does not use next completed state.")
        first, second = times.loc[t0], times.loc[t1]
        t0_time, t1_time = pd.Timestamp(first.earliest_theoretical_complete_state_time_utc), pd.Timestamp(second.earliest_theoretical_complete_state_time_utc)
        rows.append({"interval_number": int(record.interval_number), "t0_state_number": t0, "t1_state_number": t1,
                     "nominal_t0_bin_timestamp": record.t0_timestamp_utc, "nominal_t1_bin_timestamp": record.t1_timestamp_utc,
                     "effective_t0_observation_cutoff_utc_label": t0_time.isoformat().replace("+00:00", "Z"),
                     "effective_t1_observation_time_utc": t1_time.isoformat().replace("+00:00", "Z"),
                     "effective_response_interval_hours": (t1_time - t0_time).total_seconds() / 3600,
                     "t0_hull_sha256": hashlib.sha256(states.iloc[t0 - 1].hull.wkb).hexdigest(),
                     "t1_hull_sha256": hashlib.sha256(states.iloc[t1 - 1].hull.wkb).hexdigest()})
    return states, pd.DataFrame(rows)


def labels(frame: pd.DataFrame, states: gpd.GeoDataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    records = []
    for number, group in frame.groupby("interval_number", sort=True):
        row = meta.loc[meta.interval_number.eq(number)].iloc[0]
        hull0, hull1 = states.iloc[int(row.t0_state_number) - 1].hull, states.iloc[int(row.t1_state_number) - 1].hull
        points = shapely.points(group.center_x_epsg9311, group.center_y_epsg9311)
        reached0, reached1 = shapely.covers(hull0, points), shapely.covers(hull1, points)
        if reached0.any():
            raise RuntimeError(f"Candidate covered at t0 in interval {number}.")
        result = group[KEYS].copy()
        result["y"] = reached1.astype("int8")
        for column in ["t0_state_number", "t1_state_number", "nominal_t0_bin_timestamp", "nominal_t1_bin_timestamp", "effective_t0_observation_cutoff_utc_label", "effective_t1_observation_time_utc", "effective_response_interval_hours", "t0_hull_sha256", "t1_hull_sha256"]:
            result[column] = row[column]
        result["no_early_sensitivity_included"] = number in NO_EARLY
        result["distance_center_to_t0_boundary_m"] = shapely.distance(points, hull0.boundary)
        result["distance_center_to_t1_boundary_m"] = shapely.distance(points, hull1.boundary)
        result["within_either_boundary_500m"] = (result.distance_center_to_t0_boundary_m <= 500) | (result.distance_center_to_t1_boundary_m <= 500)
        result["within_either_boundary_1000m"] = (result.distance_center_to_t0_boundary_m <= 1000) | (result.distance_center_to_t1_boundary_m <= 1000)
        records.append(result)
    return pd.concat(records, ignore_index=True)


def support_wide(mask: pd.DataFrame) -> pd.DataFrame:
    wide = mask.pivot(index=KEYS, columns="support_universe_id", values="included")
    wide.columns = [f"support_{c.lower()}" for c in wide.columns]
    return wide.reset_index()


def column_roles(table: pd.DataFrame, whitelist: set[str]) -> pd.DataFrame:
    rows = []
    response_qc = {"t0_state_number", "t1_state_number", "nominal_t0_bin_timestamp", "nominal_t1_bin_timestamp", "effective_t0_observation_cutoff_utc_label", "effective_t1_observation_time_utc", "effective_response_interval_hours", "distance_center_to_t0_boundary_m", "distance_center_to_t1_boundary_m", "within_either_boundary_500m", "within_either_boundary_1000m", "t0_hull_sha256", "t1_hull_sha256", "no_early_sensitivity_included"}
    identifiers = {"event_id", "risk_set_id", "interval_id", "response_grid_m", "cell_id", "row", "col", "center_x_epsg9311", "center_y_epsg9311", "interval_number", "forward_chain_block"}
    for column in table.columns:
        if column == "y": role, note = "RESPONSE", "Locked next-state incorporation label."
        elif column in whitelist: role, note = "T0_MODEL_CANDIDATE", "Explicit frozen model-whitelist field from PR32A response-free table."
        elif column.startswith("support_"): role, note = "SUPPORT/APPLICABILITY_METADATA", "Frozen PR24-style paired-support receipt; never a predictor."
        elif column in response_qc: role, note = "RESPONSE_QC", "t1/response audit metadata; FORBIDDEN_MODEL_INPUT."
        elif column in identifiers: role, note = "IDENTIFIER", "Key, grid, coordinate, or grouping metadata; FORBIDDEN_MODEL_INPUT."
        else: role, note = "PROVENANCE", "Response-free source/provenance metadata; unknown columns fail closed as non-input."
        rows.append({"column": column, "role": role, "model_input_allowed": role == "T0_MODEL_CANDIDATE", "forbidden_model_input": role in {"IDENTIFIER", "RESPONSE", "RESPONSE_QC", "SUPPORT/APPLICABILITY_METADATA", "PROVENANCE"}, "notes": note})
    return pd.DataFrame(rows)


def count_rows(table: pd.DataFrame, mask: pd.DataFrame, risk: str, size: int) -> list[dict[str, object]]:
    wide = support_wide(mask)
    joined = table[KEYS + ["y", "interval_number", "forward_chain_block"]].merge(wide, on=KEYS, validate="one_to_one")
    rows = []
    for universe in [c.removeprefix("support_").upper() for c in wide if c.startswith("support_")]:
        column = f"support_{universe.lower()}"
        subset = joined.loc[joined[column]]
        for scope, value, group in [("ALL", "ALL", subset), *[("INTERVAL", str(i), subset.loc[subset.interval_number.eq(i)]) for i in INTERVALS], *[("BLOCK", f"B{i}", subset.loc[subset.forward_chain_block.eq(i)]) for i in range(1, 5)]]:
            rows.append({"risk_set_id": risk, "resolution_m": size, "support_universe_id": universe, "scope": scope, "scope_value": value, "rows": len(group), "positives": int(group.y.sum()), "negatives": int((group.y == 0).sum()), "positive_fraction": float(group.y.mean()) if len(group) else np.nan, "warning": "ZERO_CLASS" if len(group) and group.y.nunique() < 2 else "EMPTY" if not len(group) else ""})
        if universe == "PRIMARY_CONFIRMATORY":
            group = subset.loc[subset.interval_number.isin(NO_EARLY)]
            rows.append({"risk_set_id": risk, "resolution_m": size, "support_universe_id": universe, "scope": "NO_EARLY", "scope_value": "4,5,6,8,9,10,11,12,14,15,16,18,21,22", "rows": len(group), "positives": int(group.y.sum()), "negatives": int((group.y == 0).sum()), "positive_fraction": float(group.y.mean()), "warning": "ZERO_CLASS" if group.y.nunique() < 2 else ""})
    return rows


def main() -> None:
    frames, masks, part1, support_manifest = read_frozen()
    pre_hashes = {f"predictor:{risk}:{size}": sha256(predictor_path(risk, size)) for risk, size in EXPECTED}
    pre_hashes |= {f"support:{risk}:{size}": sha256(support_path(risk, size)) for risk, size in EXPECTED}
    states, meta = timing()
    whitelist = set(pd.read_csv(WHITELIST).loc[lambda x: x.required_in_primary_table.astype(str).str.upper().eq("TRUE"), "raw_column"])
    OUT.mkdir(parents=True, exist_ok=True)
    tables, output_info, all_counts, qc = {}, [], [], []
    for (risk, size), frame in sorted(frames.items(), key=lambda x: (x[0][1], x[0][0])):
        label = labels(frame, states, meta)
        table = frame.merge(label, on=KEYS, validate="one_to_one")
        if table.duplicated(KEYS).any() or table.y.isna().any() or not set(table.y.unique()) <= {0, 1}:
            raise RuntimeError("Label key/domain failure.")
        path = OUT / risk / "outputs" / f"paper1_pr32b_labeled_{risk.lower()}_{size // 1000}km.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_parquet(path, index=False)
        tables[risk, size] = table
        output_info.append({"risk_set_id": risk, "resolution_m": size, "path": rel(path), "sha256": sha256(path), "rows": len(table), "positives": int(table.y.sum()), "negatives": int((table.y == 0).sum()), "columns": len(table.columns)})
        all_counts.extend(count_rows(table, masks[risk, size], risk, size))
        wide = support_wide(masks[risk, size])
        join_ok = len(table.merge(wide, on=KEYS, validate="one_to_one")) == len(table)
        primary_rows = int(wide.support_primary_confirmatory.sum())
        qc += [{"check": "support_label_one_to_one", "risk_set_id": risk, "resolution_m": size, "status": "PASS" if join_ok else "FAIL", "value": int(join_ok), "detail": "Frozen support joined to labels by governed key."}, {"check": "primary_rows_equal_candidates", "risk_set_id": risk, "resolution_m": size, "status": "PASS" if primary_rows == len(table) else "FAIL", "value": primary_rows, "detail": "Verified, not forced."}]
    # Exact response regression against committed PR31 and cross-risk labels.
    for size in (1000, 2000):
        primary = pd.read_parquet(PR31 / "outputs" / f"paper1_pr31_labeled_table_{size // 1000}km.parquet")
        alternate = tables["PERIMETER_ONLY_5KM", size]
        merged = alternate.merge(primary[PR31_KEYS + ["y", "t1_state_number", "t1_hull_sha256"]], on=PR31_KEYS, suffixes=("_alt", "_pr31"), validate="one_to_one")
        exact = merged.y_alt.eq(merged.y_pr31).all() and merged.t1_state_number_alt.eq(merged.t1_state_number_pr31).all() and merged.t1_hull_sha256_alt.eq(merged.t1_hull_sha256_pr31).all()
        qc.append({"check": "primary_pr31_label_overlap", "risk_set_id": "PERIMETER_ONLY_5KM", "resolution_m": size, "status": "PASS" if exact else "FAIL", "value": int((~merged.y_alt.eq(merged.y_pr31)).sum()), "detail": f"overlap_rows={len(merged)}; response provenance also exact."})
        for left, right in [("ACTIVE_FRONT_ONLY_5KM", "PERIMETER_ONLY_2KM"), ("ACTIVE_FRONT_ONLY_5KM", "PERIMETER_ONLY_5KM"), ("PERIMETER_ONLY_2KM", "PERIMETER_ONLY_5KM")]:
            pair = tables[left, size].merge(tables[right, size][PR31_KEYS + ["y", "t1_state_number", "t1_hull_sha256"]], on=PR31_KEYS, suffixes=("_left", "_right"), validate="one_to_one")
            exact = pair.y_left.eq(pair.y_right).all() and pair.t1_state_number_left.eq(pair.t1_state_number_right).all() and pair.t1_hull_sha256_left.eq(pair.t1_hull_sha256_right).all()
            qc.append({"check": f"cross_risk_label_{left}_vs_{right}", "risk_set_id": "ALL", "resolution_m": size, "status": "PASS" if exact else "FAIL", "value": int((~pair.y_left.eq(pair.y_right)).sum()), "detail": f"overlap_rows={len(pair)}; t1 provenance exact."})
    ledger = column_roles(next(iter(tables.values())), whitelist)
    forbidden_in_whitelist = whitelist.intersection(set(ledger.loc[ledger.forbidden_model_input, "column"]))
    missing_whitelist = whitelist.difference(next(iter(tables.values())).columns)
    qc.append({"check": "whitelist_fail_closed", "risk_set_id": "ALL", "resolution_m": 0, "status": "PASS" if not forbidden_in_whitelist and not missing_whitelist else "FAIL", "value": len(whitelist), "detail": "Explicit whitelist only; unknown columns are forbidden."})
    post_hashes = {f"predictor:{risk}:{size}": sha256(predictor_path(risk, size)) for risk, size in EXPECTED}
    post_hashes |= {f"support:{risk}:{size}": sha256(support_path(risk, size)) for risk, size in EXPECTED}
    qc.append({"check": "frozen_input_immutability", "risk_set_id": "ALL", "resolution_m": 0, "status": "PASS" if pre_hashes == post_hashes else "FAIL", "value": int(pre_hashes == post_hashes), "detail": "All six predictors and six support masks re-hashed unchanged after t1 labeling."})
    qc = pd.DataFrame(qc)
    if not qc.status.eq("PASS").all():
        raise RuntimeError("PR32B QC failed; no decision receipt written.")
    counts = pd.DataFrame(all_counts)
    counts.to_csv(DOC / "PAPER1_ALT_RISKSET_RESPONSE_COUNTS.csv", index=False)
    ledger.to_csv(DOC / "PAPER1_ALT_RISKSET_LEAKAGE_LEDGER.csv", index=False)
    qc.to_csv(DOC / "PAPER1_ALT_RISKSET_LABEL_QC.csv", index=False)
    readiness = counts.loc[counts.scope.eq("ALL")].copy()
    readiness.to_csv(DOC / "PAPER1_ALT_RISKSET_PREMODEL_READINESS.csv", index=False)
    (DOC / "PAPER1_ALT_RISKSET_RESPONSE_LABEL_SPEC.md").write_text("""# Paper 1 Alternate Risk-Set Response Label Specification\n\nPR32B attaches the immutable PR31 response to frozen PR32A candidates: `y = 1` iff the fixed cell center is covered by the next completed FEDS event-65371 hull; otherwise `y = 0`. This is next-state incorporation among frozen still-unburned candidates, not ignition, severity, fire probability, exact arrival, or causal spread.\n\nOnly response construction reads t1. Candidate membership, predictors, support masks, and missingness remain frozen. All t1 geometry, time, boundary, and label fields are response QC or provenance and are forbidden model inputs. V5 EAG and cheatgrass retain their authorized retrospective-sensitivity classification. The explicit model whitelist is the only permitted future route to X; unknown columns fail closed.\n\nPR32B creates labels and readiness receipts only. It does not construct a design matrix, tune, standardize, select features, calculate performance, or fit a model.\n""", encoding="utf-8")
    decision = pd.DataFrame([{"gate": "PR32B", "status": "COMPLETE_WITH_LIMITATIONS", "response_rule": "Y=1 iff next completed FEDS state hull covers fixed cell center", "pr31_overlap_mismatches": 0, "cross_risk_label_mismatches": 0, "frozen_inputs_unchanged": True, "leakage_ledger_complete": True, "explicit_whitelist_pass": True, "premodel_architecture_ready_for_final_authorization_review": "YES", "model_fitting_authorized": "NO", "limitations": "FEDS observation/geometry uncertainty and historical retrospective latency remain; no model has been fit."}])
    decision.to_csv(DOC / "PAPER1_PR32B_DECISION.csv", index=False)
    manifest = {"artifact_class": "PR32B alternate-risk-set labeled candidates", "created_utc": datetime.now(timezone.utc).isoformat(), "git_head": git("rev-parse", "HEAD"), "script": rel(Path(__file__)), "script_sha256": sha256(Path(__file__)), "environment": {"python": sys.version, "platform": platform.platform()}, "response_rule": "Y=1 iff next completed FEDS state hull covers fixed cell center; else Y=0", "response_bearing_files_opened": [rel(STATES)], "y_inspected": "CREATED_ONLY", "network_acquisitions": [], "predictor_recomputation": False, "support_recomputation": False, "model_fit": False, "frozen_inputs_pre": pre_hashes, "frozen_inputs_post": post_hashes, "pr32a_part1_manifest": {"path": rel(PR32A / "pr32a_part1_manifest.json"), "sha256": EXPECTED_PART1_MANIFEST}, "pr32a_support_manifest": {"path": rel(SUPPORT / "pr32a_manifest.json"), "sha256": sha256(SUPPORT / "pr32a_manifest.json")}, "response_geometry": {"path": rel(STATES), "sha256": sha256(STATES)}, "outputs": output_info, "status": "COMPLETE_WITH_LIMITATIONS", "premodel_architecture_ready_for_final_authorization_review": "YES", "model_fitting_authorized": "NO"}
    (OUT / "pr32b_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETE_WITH_LIMITATIONS", "outputs": output_info, "pr32b_may_begin": "DONE", "model_fitting_authorized": "NO"}, indent=2))


if __name__ == "__main__":
    main()
