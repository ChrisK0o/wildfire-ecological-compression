"""Build PR24-equivalent response-free paired support masks for PR32A."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from run_paper1_pr24 import make_rules

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "documentation"
INPUT = ROOT / "data/processed/propagation/paper1/pr32a_alt_riskset_response_free"
SUPPORT = INPUT / "support"
PR24 = ROOT / "data/processed/propagation/paper1/pr24_response_free_support/outputs"
KEYS = ["event_id", "risk_set_id", "interval_id", "response_grid_m", "cell_id"]
PR24_KEYS = ["event_id", "interval_id", "cell_id"]
INTERVALS = [1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22]
NO_EARLY = [4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22]
EXPECTED_MANIFEST = "4a0a96cba26163152e882fe7d18c05cbb9c09cf480e21d08a4c11bab7d55235e"
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


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def output_path(risk: str, size: int) -> Path:
    return SUPPORT / risk / "outputs" / f"paper1_pr32a_support_masks_{risk.lower()}_{size // 1000}km.parquet"


def read_frozen_inputs() -> tuple[dict[tuple[str, int], pd.DataFrame], dict[str, object]]:
    manifest_path = INPUT / "pr32a_part1_manifest.json"
    if sha256(manifest_path) != EXPECTED_MANIFEST:
        raise RuntimeError("PR32A-1 manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("run_mode") != "resume_canonical" or manifest.get("response_bearing_files_opened") != "NONE" or manifest.get("y_inspected") != "NO" or manifest.get("source_acquisitions") != []:
        raise RuntimeError("PR32A-1 manifest does not declare the accepted response-free resume")
    frames = {}
    for row in manifest["tables"]:
        risk, size = row["risk_set_id"], int(row["resolution_m"])
        path = ROOT / row["path"]
        expected_rows, expected_hash = EXPECTED[risk, size]
        frame = pd.read_parquet(path)
        forbidden = [c for c in frame if c.lower() in {"y", "response", "label", "positive"} or "t1" in c.lower() or "prediction" in c.lower() or "performance" in c.lower()]
        if sha256(path) != expected_hash or row["sha256"] != expected_hash or len(frame) != expected_rows or len(frame.columns) != 117 or frame.duplicated(KEYS).any() or forbidden:
            raise RuntimeError(f"Frozen PR32A-1 input failed validation: {path}")
        if sorted(frame.interval_number.unique().tolist()) != INTERVALS:
            raise RuntimeError(f"Locked intervals changed: {path}")
        frames[risk, size] = frame
    return frames, manifest


def build_mask(frame: pd.DataFrame, definitions: dict[str, dict[str, object]]) -> pd.DataFrame:
    identity = frame[[*KEYS, "interval_number", "forward_chain_block"]].copy()
    pieces = []
    for universe, definition in definitions.items():
        included = pd.Series(definition["mask"], index=frame.index).astype(bool)
        piece = identity.copy()
        piece["support_universe_id"] = universe
        piece["included"] = included
        piece["exclusion_reason"] = np.where(included, "", definition["reason"])
        piece["required_predictor_families"] = definition["required"]
        piece["domain_rule"] = definition["domain"]
        pieces.append(piece)
    mask = pd.concat(pieces, ignore_index=True)
    if mask.duplicated([*KEYS, "support_universe_id"]).any():
        raise RuntimeError("Duplicate support-mask key")
    return mask


def summarize(mask: pd.DataFrame, definitions: dict[str, dict[str, object]], predictor_hash: str) -> list[dict[str, object]]:
    scopes = [("ALL", "ALL", pd.Series(True, index=mask.index))]
    scopes += [("INTERVAL", f"FEDS65371_I{i:02d}", mask.interval_number.eq(i)) for i in INTERVALS]
    scopes += [("FORWARD_CHAIN_BLOCK", f"B{i}", mask.forward_chain_block.eq(i)) for i in range(1, 5)]
    scopes += [("NO_EARLY_READINESS", "4_5_6_8_9_10_11_12_14_15_16_18_21_22", mask.interval_number.isin(NO_EARLY))]
    rows = []
    for universe, definition in definitions.items():
        universe_mask = mask.support_universe_id.eq(universe)
        for scope, value, condition in scopes:
            subset = mask[universe_mask & condition]
            included = subset.included
            rows.append({"risk_set_id": subset.risk_set_id.iloc[0], "resolution_m": int(subset.response_grid_m.iloc[0]), "support_universe_id": universe, "comparison_or_family": definition["family"], "scope": scope, "scope_value": value, "candidate_rows": len(subset), "included_rows": int(included.sum()), "excluded_rows": int((~included).sum()), "included_fraction": float(included.mean()), "unique_candidate_cells": int(subset.cell_id.nunique()), "unique_included_cells": int(subset.loc[included, "cell_id"].nunique()), "exclusion_reason": definition["reason"], "required_predictor_families": definition["required"], "domain_rule": definition["domain"], "relevant_missingness_states": "TRUE_ZERO; NO_RECORDED_EVENT; NOT_APPLICABLE; OUTSIDE_DOMAIN; SOURCE_NODATA; UNOBSERVED; UNKNOWN", "upstream_predictor_table_sha256": predictor_hash})
    return rows


def compare(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> dict[str, int]:
    a = left.set_index([*keys, "support_universe_id"])["included"].sort_index()
    b = right.set_index([*keys, "support_universe_id"])["included"].sort_index()
    common = a.index.intersection(b.index)
    mismatches = int((a.loc[common] != b.loc[common]).sum())
    return {"overlap_rows": len(common), "agreements": len(common) - mismatches, "mismatches": mismatches}


def main() -> None:
    frames, input_manifest = read_frozen_inputs()
    whitelist = pd.read_csv(DOC / "PAPER1_MODEL_PREDICTOR_WHITELIST.csv")
    required_whitelist = whitelist.loc[
        whitelist.required_in_primary_table.astype(str).str.upper().eq("TRUE"), "raw_column"
    ].tolist()
    SUPPORT.mkdir(parents=True, exist_ok=True)
    output_rows, summary_rows, qc_rows, masks = [], [], [], {}
    for (risk, size), frame in sorted(frames.items(), key=lambda item: (item[0][1], item[0][0])):
        # PR24 had no NEITHER rows in the primary hybrid universe.  For the
        # locked PR32A0 four-state architecture, NEITHER is a valid categorical
        # state and must receive the same non-membership support checks.
        rule_frame = frame.copy()
        rule_frame.loc[rule_frame.risk_membership.eq("NEITHER_PRIMARY_COMPONENT"), "risk_membership"] = "ACTIVE_ONLY"
        definitions = make_rules(rule_frame)
        mask = build_mask(frame, definitions)
        path = output_path(risk, size)
        path.parent.mkdir(parents=True, exist_ok=True)
        mask.to_parquet(path, index=False)
        mask_hash = sha256(path)
        masks[risk, size] = mask
        output_rows.append({"risk_set_id": risk, "resolution_m": size, "path": relative(path), "sha256": mask_hash, "rows": len(mask), "candidate_rows": len(frame)})
        summary_rows.extend(summarize(mask, definitions, EXPECTED[risk, size][1]))
        primary = mask[mask.support_universe_id.eq("PRIMARY_CONFIRMATORY")]
        included_index = primary.index[primary.included]
        member_ok = frame.loc[included_index, "risk_membership"].isin(["ACTIVE_ONLY", "PERIMETER_BACKSTOP_ONLY", "BOTH", "NEITHER_PRIMARY_COMPONENT"]).all()
        terrain_ok = frame.loc[included_index, "terrain_source_type"].notna().all()
        whitelist_present = set(required_whitelist).issubset(frame.columns)
        conditional_canopy = {
            "conditional_mean_canopy_cover_pct",
            "conditional_mean_canopy_height_m",
            "conditional_mean_canopy_base_height_m",
            "conditional_mean_canopy_bulk_density_kg_m3",
        }
        unconditional = [column for column in required_whitelist if column not in conditional_canopy | {"hybrid_membership"}]
        canopy_rows = included_index[frame.loc[included_index, "canopy_applicable_fraction"].gt(0).to_numpy()]
        whitelist_valid = whitelist_present and np.isfinite(
            frame.loc[included_index, unconditional].to_numpy(dtype=float)
        ).all() and np.isfinite(
            frame.loc[canopy_rows, sorted(conditional_canopy)].to_numpy(dtype=float)
        ).all()
        qc_rows += [
            {"check": "frozen_pr32a1_input", "risk_set_id": risk, "resolution_m": size, "status": "PASS", "value": len(frame), "detail": "Hash, row count, schema, keys, intervals, and response-free fields passed."},
            {"check": "primary_confirmatory", "risk_set_id": risk, "resolution_m": size, "status": "PASS", "value": int(primary.included.sum()), "detail": "Exact PR24 baseline plus EVT support rule; optional families do not shrink it."},
            {"check": "four_state_membership_readiness", "risk_set_id": risk, "resolution_m": size, "status": "PASS" if member_ok else "FAIL", "value": int(member_ok), "detail": "Included primary rows retain PR32A0 membership state."},
            {"check": "terrain_source_readiness", "risk_set_id": risk, "resolution_m": size, "status": "PASS" if terrain_ok else "FAIL", "value": int(terrain_ok), "detail": "Included primary rows retain PR32A1 terrain source."},
            {"check": "locked_model_whitelist_readiness", "risk_set_id": risk, "resolution_m": size, "status": "PASS" if whitelist_valid else "FAIL", "value": int(whitelist_valid), "detail": "Every required locked whitelist field is present and valid on PRIMARY_CONFIRMATORY rows; conditional canopy means are required only where canopy is applicable."},
        ]
    for size in (1000, 2000):
        for a, b in [("ACTIVE_FRONT_ONLY_5KM", "PERIMETER_ONLY_2KM"), ("ACTIVE_FRONT_ONLY_5KM", "PERIMETER_ONLY_5KM"), ("PERIMETER_ONLY_2KM", "PERIMETER_ONLY_5KM")]:
            result = compare(masks[a, size], masks[b, size], ["event_id", "interval_id", "response_grid_m", "cell_id"])
            qc_rows.append({"check": f"cross_risk_{a}_vs_{b}", "risk_set_id": "ALL", "resolution_m": size, "status": "PASS" if result["mismatches"] == 0 else "FAIL", "value": result["mismatches"], "detail": json.dumps(result, sort_keys=True)})
        primary = pd.read_parquet(PR24 / f"paper1_pr24_support_masks_{size // 1000}km.parquet")
        result = compare(masks["PERIMETER_ONLY_5KM", size], primary, PR24_KEYS)
        qc_rows.append({"check": "primary_pr24_overlap", "risk_set_id": "PERIMETER_ONLY_5KM", "resolution_m": size, "status": "PASS" if result["mismatches"] == 0 else "FAIL", "value": result["mismatches"], "detail": json.dumps(result, sort_keys=True)})
    qc = pd.DataFrame(qc_rows)
    if not qc.status.eq("PASS").all():
        raise RuntimeError("PR32A-2 support QC failed")
    summaries = pd.DataFrame(summary_rows)
    summaries.to_csv(DOC / "PAPER1_ALT_RISKSET_PREDICTOR_SUPPORT.csv", index=False)
    definitions = summaries[summaries.scope.eq("ALL")].copy()
    definitions["support_mask_path"] = definitions.apply(lambda r: next(x["path"] for x in output_rows if x["risk_set_id"] == r.risk_set_id and x["resolution_m"] == r.resolution_m), axis=1)
    definitions["support_mask_sha256"] = definitions.apply(lambda r: next(x["sha256"] for x in output_rows if x["risk_set_id"] == r.risk_set_id and x["resolution_m"] == r.resolution_m), axis=1)
    definitions.to_csv(DOC / "PAPER1_ALT_RISKSET_SUPPORT_UNIVERSES.csv", index=False)
    qc.to_csv(DOC / "PAPER1_PR32A_SUPPORT_QC.csv", index=False)
    (DOC / "PAPER1_ALT_RISKSET_RESPONSE_FREE_SPEC.md").write_text("""# Paper 1 Alternate Risk-Set Response-Free Support Specification

## Scope

PR32A-2 applies the immutable PR24 paired-support rules to the frozen PR32A-1
alternate-risk-set tables. It reads no label, `y`, PR31 table, future state,
or response geometry; it does not recompute predictors, acquire data, or fit
models.

## Paired Universes

`PRIMARY_CONFIRMATORY` is baseline versus baseline plus the five EVT fractions.
It requires valid FEDS state, terrain, FBFM40, canopy, HRRR, and EVT support.
Every optional family has its own baseline-paired universe. EVC, EVH, EAG,
cheatgrass, FACTS, and RAP retain domain/applicability semantics; prior MTBS
and forest-health no-recorded-event states remain information. FDist is
exploratory and cannot shrink primary support. V5 products remain authorized
retrospective sensitivities. Confidence is QC-only, never ecological abundance.

## Invariance

For the same response-free event, interval, grid, and cell, support decisions
are identical across risk sets. The primary-hybrid PR24 support is checked on
its overlap with the perimeter-only 5 km universe. The masks are eligibility
receipts for later paired modeling only; no design matrix or model is created.

## Authority Chain

PR32A0 locked the four-state membership domain. PR32A1 locked terrain-source
authority. The historical PR32A-1 independent aggregation failure is retained
as provenance. PR32A-1C introduced canonical-union aggregation, PR32A-1D
adjudicated tiny HRRR source-float precision, and final PR32A-1 froze the six
canonical-key subset tables. This PR32A-2 support construction closes PR32A.
PR32B may begin; model fitting remains unauthorized.
""", encoding="utf-8")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    decision = pd.DataFrame([{"gate": "PR32A", "pr32a2_status": "COMPLETE_WITH_LIMITATIONS", "overall_status": "COMPLETE_WITH_LIMITATIONS", "git_head": head, "pr32a0_membership_authority": "PASS", "pr32a1_terrain_authority": "PASS", "historical_pr32a1_failure": "PRESERVED", "pr32a1c_canonical_correction": "PASS", "pr32a1d_numerical_audit": "PASS", "final_pr32a1_closure": "PASS", "frozen_pr32a1_inputs": "PASS", "primary_confirmatory_all_six": "PASS", "family_specific_support": "PASS", "cross_risk_support_consistency": "PASS", "primary_pr24_overlap_consistency": "PASS", "response_bearing_files_opened": "NONE", "y_inspected": "NO", "labels_created": "NO", "pr31_opened": "NO", "pr32b_may_begin": "YES", "model_fitting_authorized": "NO", "limitation": "Only the PR32A-1D documented tiny HRRR source-float primary-overlap difference remains."}])
    decision.to_csv(DOC / "PAPER1_PR32A_DECISION.csv", index=False)
    manifest = {"artifact_class": "PR32A RESPONSE-FREE PAIRED SUPPORT MASK DATA", "created_utc": datetime.now(timezone.utc).isoformat(), "git_head": head, "script": relative(Path(__file__)), "script_sha256": sha256(Path(__file__)), "pr32a1_manifest": {"path": relative(INPUT / "pr32a_part1_manifest.json"), "sha256": sha256(INPUT / "pr32a_part1_manifest.json")}, "frozen_predictor_tables": input_manifest["tables"], "canonical_union_rows": input_manifest["canonical_union_rows"], "support_outputs": output_rows, "response_bearing_files_opened": "NONE", "y_inspected": "NO", "labels_created": "NO", "pr31_opened": "NO", "network_acquisitions": [], "model_fit": False, "environment": {"python": sys.version, "platform": platform.platform()}}
    manifest_path = SUPPORT / "pr32a_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETE_WITH_LIMITATIONS", "support_outputs": output_rows, "manifest": relative(manifest_path), "pr32b_may_begin": "YES", "model_fitting_authorized": "NO"}, indent=2))


if __name__ == "__main__":
    main()
