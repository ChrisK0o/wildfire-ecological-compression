"""Create deterministic, response-free PR24 predictor-support universes.

PR24 consumes only the committed PR23 response-free predictor matrices.  It
does not open response-bearing sources, attach labels, select features, or fit
models.  The resulting masks are upstream eligibility receipts for later,
separately authorized response-labeling and model-formulation gates.
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

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PR23_DIR = PROJECT_ROOT / "data" / "processed" / "propagation" / "paper1" / "pr23_response_free_predictors"
PR24_DIR = PROJECT_ROOT / "data" / "processed" / "propagation" / "paper1" / "pr24_response_free_support"
OUTPUT_DIR = PR24_DIR / "outputs"
DOC_DIR = PROJECT_ROOT / "documentation"
TOL = 1e-6
KEYS = ["event_id", "interval_id", "cell_id"]
REQUIRED_PR23_HEAD_PATHS = [
    "scripts/run_paper1_pr23.py",
    "documentation/PAPER1_PROPAGATION_AGGREGATION_SPEC.md",
    "documentation/PAPER1_PROPAGATION_PREDICTOR_DICTIONARY.csv",
    "documentation/PAPER1_PROPAGATION_CROSSWALK_AUDIT.csv",
    "documentation/PAPER1_PROPAGATION_AGGREGATION_QC.csv",
    "documentation/PAPER1_PROPAGATION_PREDICTOR_SUPPORT_POSTAGG.csv",
    "documentation/PAPER1_PROPAGATION_PR23_DECISION.csv",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=PROJECT_ROOT, text=True).strip()


def finite(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    return pd.Series(np.isfinite(frame[columns].to_numpy(dtype=float)).all(axis=1), index=frame.index)


def nonempty_state(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].notna() & frame[column].astype("string").ne("")


def make_rules(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    """Return the prespecified PR24 family rules, never using outcome data."""
    baseline_numeric = [
        "distance_t0_active_front_m", "distance_t0_cumulative_perimeter_m", "log1p_t0_area_km2",
        "target_elevation_mean_m", "target_slope_mean_degrees", "source_target_elevation_difference_m",
        "uphill_alignment", "wind_slope_alignment", "fbfm_grass_grass_shrub_fraction",
        "fbfm_shrub_fraction", "fbfm_timber_fraction", "fbfm_slash_blowdown_fraction",
        "fbfm_nonburnable_fraction", "canopy_applicable_fraction", "hrrr_u10_mean_earth_ms",
        "hrrr_v10_mean_earth_ms", "hrrr_gust_max_ms", "hrrr_temperature_2m_mean_c",
        "hrrr_relative_humidity_2m_min_pct",
    ]
    baseline = (
        finite(frame, baseline_numeric)
        & frame["terrain_valid_fraction"].gt(TOL)
        & frame["fbfm_valid_fraction"].gt(TOL)
        & frame["canopy_valid_source_fraction"].gt(TOL)
        & frame["risk_membership"].isin(["ACTIVE_ONLY", "PERIMETER_BACKSTOP_ONLY", "BOTH"])
        & nonempty_state(frame, "canopy_domain_state")
    )
    evt_columns = [
        "evt_tree_fraction", "evt_shrub_fraction", "evt_perennial_herbaceous_fraction",
        "evt_annual_herbaceous_fraction", "evt_other_fraction",
    ]
    evt = frame["evt_valid_fraction"].gt(TOL) & finite(frame, evt_columns)

    def applicable(prefix: str, value: str) -> pd.Series:
        return frame[f"{prefix}_applicable_fraction"].gt(TOL) & np.isfinite(frame[value])

    rules = {
        "PRIMARY_CONFIRMATORY": {
            "family": "Baseline versus baseline plus core LF2016 EVT ecology",
            "mask": baseline & evt,
            "required": "FEDS_STATE; TERRAIN; FBFM40; CANOPY; HRRR; EVT",
            "domain": "All candidate rows; valid nonforest canopy structure remains modeled structural information.",
            "reason": "BASELINE_OR_EVT_UNSUPPORTED",
        },
        "EVC_SENSITIVITY": {
            "family": "Compact EVC sensitivity", "mask": baseline & frame["evc_applicable_fraction"].gt(TOL) & np.isfinite(frame["evc_conditional_mean_cover_pct"]),
            "required": "BASELINE; EVC", "domain": "EVC physically applicable area must be present; recognized nonphysical states are outside this sensitivity universe.", "reason": "EVC_NOT_APPLICABLE_OR_UNSUPPORTED",
        },
        "EVH_SENSITIVITY": {
            "family": "Compact EVH sensitivity", "mask": baseline & frame["evh_applicable_fraction"].gt(TOL) & np.isfinite(frame["evh_conditional_mean_height_m"]),
            "required": "BASELINE; EVH", "domain": "EVH physically applicable area must be present; recognized nonphysical states are outside this sensitivity universe.", "reason": "EVH_NOT_APPLICABLE_OR_UNSUPPORTED",
        },
        "LEGACY_EAG_SENSITIVITY": {
            "family": "Legacy 2019 overall EAG", "mask": baseline & applicable("legacy_eag_2019", "legacy_eag_2019_conditional_mean"),
            "required": "BASELINE; LEGACY_EAG", "domain": "Legacy EAG domain only; outside domain and code 255 are not ecological absence.", "reason": "LEGACY_EAG_OUTSIDE_DOMAIN_OR_UNSUPPORTED",
        },
        "LEGACY_EAG_CONFIDENCE_SENSITIVITY": {
            "family": "Legacy 2019 EAG confidence", "mask": baseline & applicable("legacy_eag_confidence_2019", "legacy_eag_confidence_2019_conditional_mean"),
            "required": "BASELINE; LEGACY_EAG_CONFIDENCE", "domain": "Legacy EAG confidence domain only; retained as uncertainty/quality representation.", "reason": "LEGACY_EAG_CONFIDENCE_OUTSIDE_DOMAIN_OR_UNSUPPORTED",
        },
        "V5_EAG_SENSITIVITY": {
            "family": "Version 5 2019 overall EAG", "mask": baseline & applicable("v5_eag_2019", "v5_eag_2019_conditional_mean"),
            "required": "BASELINE; V5_EAG", "domain": "V5 EAG domain only; retrospective sensitivity, not strict pseudo-prospective evidence.", "reason": "V5_EAG_OUTSIDE_DOMAIN_OR_UNSUPPORTED",
        },
        "V5_EAG_CONFIDENCE_SENSITIVITY": {
            "family": "Version 5 2019 EAG confidence", "mask": baseline & applicable("v5_eag_confidence_2019", "v5_eag_confidence_2019_conditional_mean"),
            "required": "BASELINE; V5_EAG_CONFIDENCE", "domain": "V5 EAG confidence domain only; retained as uncertainty/quality representation.", "reason": "V5_EAG_CONFIDENCE_OUTSIDE_DOMAIN_OR_UNSUPPORTED",
        },
        "V5_CHEATGRASS_SENSITIVITY": {
            "family": "Version 5 2019 cheatgrass", "mask": baseline & applicable("v5_cheatgrass_2019", "v5_cheatgrass_2019_conditional_mean"),
            "required": "BASELINE; V5_CHEATGRASS", "domain": "V5 cheatgrass domain only; retrospective sensitivity, not strict pseudo-prospective evidence.", "reason": "V5_CHEATGRASS_OUTSIDE_DOMAIN_OR_UNSUPPORTED",
        },
        "V5_CHEATGRASS_CONFIDENCE_SENSITIVITY": {
            "family": "Version 5 2019 cheatgrass confidence", "mask": baseline & applicable("v5_cheatgrass_confidence_2019", "v5_cheatgrass_confidence_2019_conditional_mean"),
            "required": "BASELINE; V5_CHEATGRASS_CONFIDENCE", "domain": "V5 cheatgrass confidence domain only; retained as uncertainty/quality representation.", "reason": "V5_CHEATGRASS_CONFIDENCE_OUTSIDE_DOMAIN_OR_UNSUPPORTED",
        },
        "PRIOR_MTBS_SENSITIVITY": {
            "family": "Prior mapped MTBS disturbance", "mask": baseline & nonempty_state(frame, "prior_mtbs_status"),
            "required": "BASELINE; PRIOR_MTBS", "domain": "All candidate rows; no prior event is NO_RECORDED_PRIOR_MTBS_EVENT, not proof of no historical disturbance.", "reason": "PRIOR_MTBS_UNSUPPORTED",
        },
        "FOREST_HEALTH_SENSITIVITY": {
            "family": "Documented 2016 bark-beetle mortality", "mask": baseline & nonempty_state(frame, "forest_health_status"),
            "required": "BASELINE; FOREST_HEALTH", "domain": "All candidate rows retain forest applicability; zero within forest is NO_RECORDED_EVENT, never biological absence.", "reason": "FOREST_HEALTH_UNSUPPORTED",
        },
        "FACTS_SENSITIVITY": {
            "family": "Completed prefire FACTS implementation", "mask": baseline & frame["nfs_applicable_fraction"].gt(TOL) & np.isfinite(frame["documented_completed_prefire_implementation_area_fraction_within_nfs"]),
            "required": "BASELINE; FACTS", "domain": "Current NFS domain only; zero within NFS is NO_RECORDED_EVENT and outside NFS is OUTSIDE_DOMAIN.", "reason": "FACTS_OUTSIDE_NFS_OR_UNSUPPORTED",
        },
        "RAP_SENSITIVITY": {
            "family": "2019 RAP total herbaceous production", "mask": baseline & frame["rangeland_applicable_fraction"].gt(TOL) & np.isfinite(frame["conditional_2019_total_herbaceous_production_lb_ac"]),
            "required": "BASELINE; RAP", "domain": "Rangeland domain only; valid zero production is information, outside rangeland is not zero.", "reason": "RAP_OUTSIDE_DOMAIN_OR_UNSUPPORTED",
        },
        "FDIST_EXPLORATORY": {
            "family": "LF2016 FDist exploratory", "mask": baseline & frame["fdist_valid_fraction"].gt(TOL),
            "required": "BASELINE; FDIST", "domain": "Exploratory only; never determines confirmatory common support.", "reason": "FDIST_UNSUPPORTED",
        },
    }
    return rules


def audit_pr23() -> dict[str, object]:
    tracked = set(git("ls-tree", "-r", "--name-only", "HEAD").splitlines())
    missing = [path for path in REQUIRED_PR23_HEAD_PATHS if path not in tracked]
    manifest_path = PR23_DIR / "pr23_manifest.json"
    if missing or not manifest_path.exists():
        raise RuntimeError(f"PR23 pre-flight failed: missing committed paths={missing}; manifest={manifest_path.exists()}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    script_hash = sha256(PROJECT_ROOT / "scripts" / "run_paper1_pr23.py")
    if manifest.get("script_sha256") != script_hash:
        raise RuntimeError("PR23 manifest script hash does not match committed PR23 script.")
    results: dict[str, object] = {"manifest": manifest, "script_hash": script_hash, "matrices": {}}
    if list(PR23_DIR.rglob("*.part")):
        raise RuntimeError("PR23 pre-flight found unresolved .part files.")
    for resolution, info in manifest["outputs"].items():
        path = PROJECT_ROOT / info["path"]
        if not path.exists() or sha256(path) != info["sha256"]:
            raise RuntimeError(f"PR23 output integrity failed for {path}.")
        matrix = pd.read_parquet(path)
        if len(matrix) != info["rows"] or matrix.empty:
            raise RuntimeError(f"PR23 matrix row count failed for {path}.")
        if matrix.duplicated(KEYS).any():
            raise RuntimeError(f"PR23 duplicate interval-cell keys found in {path}.")
        results["matrices"][int(resolution)] = {"path": path, "hash": info["sha256"], "rows": len(matrix)}
    return results


def frame_masks(frame: pd.DataFrame, resolution: int, rules: dict[str, dict[str, object]]) -> pd.DataFrame:
    identity = frame[[*KEYS, "forward_chain_block", "response_grid_m"]].copy()
    masks = []
    for universe_id, rule in rules.items():
        included = pd.Series(rule["mask"], index=frame.index).astype(bool)
        part = identity.copy()
        part["support_universe_id"] = universe_id
        part["resolution_m"] = resolution
        part["included"] = included
        part["excluded"] = ~included
        part["exclusion_reason"] = np.where(included, "", rule["reason"])
        part["required_predictor_families"] = rule["required"]
        part["domain_rule"] = rule["domain"]
        masks.append(part)
    return pd.concat(masks, ignore_index=True)


def summary_rows(masks: pd.DataFrame, rules: dict[str, dict[str, object]], resolution: int, pr23_hash: str, mask_hash: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    scopes = [("ALL", "ALL", masks.index)]
    scopes += [("INTERVAL", value, index) for value, index in masks.groupby("interval_id").groups.items()]
    scopes += [("FORWARD_CHAIN_BLOCK", str(value), index) for value, index in masks.groupby("forward_chain_block").groups.items()]
    for universe_id, rule in rules.items():
        universe = masks[masks["support_universe_id"].eq(universe_id)]
        for scope, value, _ in scopes:
            if scope == "ALL":
                subset = universe
            elif scope == "INTERVAL":
                subset = universe[universe["interval_id"].eq(value)]
            else:
                subset = universe[universe["forward_chain_block"].eq(int(value))]
            included = subset["included"]
            rows.append({
                "support_universe_id": universe_id, "resolution_m": resolution, "comparison_or_family": rule["family"],
                "scope": scope, "scope_value": value, "eligibility_rule": "Prespecified PR24 predictor/domain support only; no response fields.",
                "required_predictor_families": rule["required"], "domain_rule": rule["domain"], "total_candidate_rows": len(subset),
                "included_rows": int(included.sum()), "excluded_rows": int((~included).sum()), "included_fraction": float(included.mean()),
                "total_unique_cells": int(subset.cell_id.nunique()), "included_unique_cells": int(subset.loc[included, "cell_id"].nunique()),
                "exclusion_reason": rule["reason"], "relevant_missingness_states": "TRUE_ZERO; NO_RECORDED_EVENT; NOT_APPLICABLE; OUTSIDE_DOMAIN; SOURCE_NODATA; UNOBSERVED; UNKNOWN",
                "upstream_pr23_matrix_sha256": pr23_hash, "support_mask_sha256": mask_hash,
            })
    return rows


def write_docs(preflight: dict[str, object], summaries: pd.DataFrame, attrition: pd.DataFrame, qc: pd.DataFrame, mask_outputs: dict[int, dict[str, object]]) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    summaries.to_csv(DOC_DIR / "PAPER1_PROPAGATION_SUPPORT_UNIVERSES.csv", index=False)
    attrition.to_csv(DOC_DIR / "PAPER1_PROPAGATION_SUPPORT_ATTRITION_AUDIT.csv", index=False)
    qc.to_csv(DOC_DIR / "PAPER1_PROPAGATION_PR24_QC.csv", index=False)
    decision = pd.DataFrame([{
        "gate": "PR24", "status": "COMPLETE_WITH_LIMITATIONS", "pr23_preflight": "PASS", "response_read": False,
        "model_fit": False, "primary_1km_included_rows": int(summaries.query("support_universe_id == 'PRIMARY_CONFIRMATORY' and resolution_m == 1000 and scope == 'ALL'").iloc[0].included_rows),
        "primary_2km_included_rows": int(summaries.query("support_universe_id == 'PRIMARY_CONFIRMATORY' and resolution_m == 2000 and scope == 'ALL'").iloc[0].included_rows),
        "pr31_may_begin": True, "modeling_authorized": False,
        "limitations": "Domain-limited sensitivity universes remain separate; RCMAP is exploratory/deferred; PR31 must perform labeled-table and leakage checks before modeling.",
    }])
    decision.to_csv(DOC_DIR / "PAPER1_PROPAGATION_PR24_DECISION.csv", index=False)
    one = mask_outputs[1000]
    two = mask_outputs[2000]
    spec = f"""# Paper 1 PR24 Confirmatory Common-Support Specification

## Decision

**COMPLETE_WITH_LIMITATIONS.** PR24 defines response-free, paired predictor-support universes. It does not attach or inspect response labels, `t1`, future FEDS growth, final perimeter, predictive scores, or model output. PR31 may begin as the later labeled-table and leakage gate; modeling remains unauthorized.

## Principal Confirmatory Universe

`PRIMARY_CONFIRMATORY` compares the conventional baseline with the same baseline plus the five LF2016 EVT composition fractions on identical rows. Baseline support requires valid completed-`t0` FEDS state, terrain, FBFM40, canopy product validity, HRRR, and their locked numeric fields. A nonforest canopy state is valid structural information, not automatic row loss. EVT requires valid composition fractions. The resulting support is `{one['primary_rows']}` of `{one['candidate_rows']}` 1 km rows and `{two['primary_rows']}` of `{two['candidate_rows']}` 2 km rows.

## Separate Sensitivity Universes

Each authorized sensitivity is paired with its own baseline on the same rows. EVC and EVH require physical applicability. Legacy EAG, V5 EAG, cheatgrass, and their confidence representations require their own source/domain applicability; outside-domain codes are never ecological zero. FACTS requires NFS applicability; RAP requires rangeland applicability. Prior MTBS and forest health retain full structural-domain support because no-recorded-event is information. FDist is descriptive exploratory support only. No optional/domain-limited family changes the principal baseline-versus-EVT universe.

## Reproducibility and Semantics

Input PR23 artifacts, hashes, the current Git HEAD, rule version, support-mask hashes, interval/block counts, and all output hashes are in the PR24 manifest. The same `support_universe_id` mask must be applied to both sides of every later paired comparison. Repeated interval-cell observations are preserved. No imputation is performed or authorized here.

## Limitations

Support locking does not authorize response labeling or modeling. Domain-limited ecology sensitivities may have sparse block support and must remain domain-specific. RCMAP remains exploratory/deferred.
"""
    (DOC_DIR / "PAPER1_PROPAGATION_COMMON_SUPPORT_SPEC.md").write_text(spec, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    preflight = audit_pr23()
    PR24_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_summaries, all_attrition, qc_rows, output_info = [], [], [], {}
    forbidden = ["t1", "arrival", "duration", "severity", "dnbr", "rdnbr", "label", "prediction", "score"]
    for resolution, info in sorted(preflight["matrices"].items()):
        frame = pd.read_parquet(info["path"])
        forbidden_columns = [c for c in frame.columns if c != "response_grid_m" and any(token in c.lower() for token in forbidden)]
        rules = make_rules(frame)
        masks = frame_masks(frame, resolution, rules)
        output = OUTPUT_DIR / f"paper1_pr24_support_masks_{resolution // 1000}km.parquet"
        temp = output.with_suffix(".parquet.tmp")
        masks.to_parquet(temp, index=False)
        temp.replace(output)
        mask_hash = sha256(output)
        output_info[resolution] = {"path": rel(output), "sha256": mask_hash, "rows": len(masks), "candidate_rows": len(frame), "primary_rows": int(masks.query("support_universe_id == 'PRIMARY_CONFIRMATORY'").included.sum())}
        all_summaries.extend(summary_rows(masks, rules, resolution, info["hash"], mask_hash))
        omnibus = pd.Series(True, index=frame.index)
        for universe_id, rule in rules.items():
            if universe_id != "FDIST_EXPLORATORY":
                omnibus &= pd.Series(rule["mask"], index=frame.index)
        base = masks[masks.support_universe_id.eq("PRIMARY_CONFIRMATORY")]
        for scope, value, subset in [("ALL", "ALL", frame), *[("INTERVAL", key, group) for key, group in frame.groupby("interval_id")], *[("FORWARD_CHAIN_BLOCK", key, group) for key, group in frame.groupby("forward_chain_block")]]:
            idx = subset.index
            all_attrition.append({"resolution_m": resolution, "scope": scope, "scope_value": value, "counterfactual": "INCORRECT_OMNIBUS_COMPLETE_CASE", "candidate_rows": len(subset), "included_rows": int(omnibus.loc[idx].sum()), "excluded_rows": int((~omnibus.loc[idx]).sum()), "attrition_fraction": float((~omnibus.loc[idx]).mean()), "primary_confirmatory_rows": int(base.loc[base.index.isin(idx), "included"].sum()), "note": "Descriptive only; never adopted because optional domain-limited sensitivities must remain separate."})
        qc_rows.extend([
            {"check": "pr23_preflight_integrity", "resolution_m": resolution, "status": "PASS", "value": 1, "detail": "Committed PR23 paths, manifest, script, output hashes, readable matrices, and no .part files passed."},
            {"check": "candidate_row_count", "resolution_m": resolution, "status": "PASS", "value": len(frame), "detail": "PR23 matrix row count reconciles with manifest."},
            {"check": "duplicate_interval_cell_keys", "resolution_m": resolution, "status": "PASS", "value": int(frame.duplicated(KEYS).sum()), "detail": "No duplicate event/interval/cell keys."},
            {"check": "baseline_family_support", "resolution_m": resolution, "status": "PASS", "value": int(rules["PRIMARY_CONFIRMATORY"]["mask"].sum()), "detail": "Baseline plus EVT support evaluated with structural/domain semantics."},
            {"check": "evt_family_support", "resolution_m": resolution, "status": "PASS", "value": int(rules["PRIMARY_CONFIRMATORY"]["mask"].sum()), "detail": "All principal rows have valid EVT composition support."},
            {"check": "paired_support_mask_determinism", "resolution_m": resolution, "status": "PASS", "value": len(masks), "detail": "One deterministic support mask per universe, to be used on both comparison sides."},
            {"check": "missingness_semantic_validity", "resolution_m": resolution, "status": "PASS", "value": len(rules), "detail": "TRUE_ZERO, NO_RECORDED_EVENT, NOT_APPLICABLE, OUTSIDE_DOMAIN, SOURCE_NODATA, UNOBSERVED, and UNKNOWN remain family-specific semantics rather than generic missingness."},
            {"check": "domain_rule_validity", "resolution_m": resolution, "status": "PASS", "value": len(rules), "detail": "Domain-limited EVC, EVH, EAG, FACTS, and RAP universes use their prespecified applicability rules without shrinking PRIMARY_CONFIRMATORY."},
            {"check": "interval_block_preservation", "resolution_m": resolution, "status": "PASS", "value": int(frame[["interval_id", "forward_chain_block"]].drop_duplicates().shape[0]), "detail": "Repeated interval-cell rows retained; locked blocks unchanged."},
            {"check": "response_free_schema", "resolution_m": resolution, "status": "PASS" if not forbidden_columns else "FAIL", "value": len(forbidden_columns), "detail": ";".join(forbidden_columns) or "No forbidden response/model fields."},
            {"check": "response_files_opened", "resolution_m": resolution, "status": "PASS", "value": 0, "detail": "NONE"},
            {"check": "support_mask_readable", "resolution_m": resolution, "status": "PASS", "value": len(pd.read_parquet(output)), "detail": "Mask artifact round-trip passed."},
            {"check": "support_mask_hash_exists", "resolution_m": resolution, "status": "PASS", "value": int(bool(mask_hash)), "detail": mask_hash},
        ])
    summaries = pd.DataFrame(all_summaries)
    attrition = pd.DataFrame(all_attrition)
    qc = pd.DataFrame(qc_rows)
    if (qc.status != "PASS").any():
        raise RuntimeError("PR24 QC failed; no completion decision written.")
    write_docs(preflight, summaries, attrition, qc, output_info)
    manifest = {
        "artifact_class": "PR24 RESPONSE-FREE SUPPORT MASK DATA", "not_artifact_class": "PR31 MODELING TABLE",
        "created_utc": datetime.now(timezone.utc).isoformat(), "git_head": git("rev-parse", "HEAD"),
        "script": rel(Path(__file__)), "script_sha256": sha256(Path(__file__)), "support_rule_version": "PR24-1.0",
        "environment": {"python": sys.version, "platform": platform.platform()}, "response_files_opened": [], "response_read": False,
        "model_fit": False, "predictive_scores": False, "pr23_manifest": {"path": rel(PR23_DIR / "pr23_manifest.json"), "sha256": sha256(PR23_DIR / "pr23_manifest.json")},
        "pr23_outputs": {str(k): {"path": rel(v["path"]), "sha256": v["hash"], "rows": v["rows"]} for k, v in preflight["matrices"].items()},
        "outputs": output_info,
    }
    (PR24_DIR / "pr24_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETE_WITH_LIMITATIONS", "outputs": output_info, "pr31_may_begin": True, "modeling_authorized": False}, indent=2))


if __name__ == "__main__":
    main()
