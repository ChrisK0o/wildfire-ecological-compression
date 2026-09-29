"""Paper 1 G05A deterministic, prefit analysis registry.

The registry wires only already-authorized analyses to frozen tables and support
masks.  It deliberately contains no estimators, fitting, prediction, scoring,
or response-derived selection.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from types import MappingProxyType

import pandas as pd


BASELINE = (
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
EVT = ("evt_tree_fraction", "evt_shrub_fraction", "evt_perennial_herbaceous_fraction", "evt_annual_herbaceous_fraction", "evt_other_fraction")
FBFM = ("fbfm_grass_grass_shrub_fraction", "fbfm_shrub_fraction", "fbfm_timber_fraction", "fbfm_slash_blowdown_fraction", "fbfm_nonburnable_fraction")
NO_EARLY = (4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22)
KEYS = ("event_id", "interval_id", "response_grid_m", "cell_id")


@dataclass(frozen=True)
class Analysis:
    analysis_id: str
    family: str
    hierarchy: str
    resolution_m: int | None
    risk_set_id: str | None
    interval_universe: str
    support_universe: str | None
    response_source: str | None
    predictor_source: str | None
    baseline_comparator: str
    augmented_fields: tuple[str, ...]
    logistic_handling: str
    rf_handling: str
    tuning_inheritance: str
    retrospective: bool
    paired_row_rule: str
    executable_status: str
    authority: str
    notes: str = ""

    def row(self) -> dict[str, object]:
        result = asdict(self)
        result["augmented_fields"] = "; ".join(self.augmented_fields)
        return result


FAMILY_FIELDS = {
    "EVC": ("evc_applicable_fraction", "evc_conditional_mean_cover_pct"),
    "EVH": ("evh_applicable_fraction", "evh_conditional_mean_height_m"),
    "LEGACY_EAG": ("legacy_eag_2019_applicable_fraction", "legacy_eag_2019_conditional_mean"),
    "V5_EAG": ("v5_eag_2019_applicable_fraction", "v5_eag_2019_conditional_mean"),
    "V5_CHEATGRASS": ("v5_cheatgrass_2019_applicable_fraction", "v5_cheatgrass_2019_conditional_mean"),
    "PRIOR_MTBS": ("prior_mapped_mtbs_disturbance_area_fraction",),
    "FOREST_HEALTH": ("forest_applicable_fraction", "documented_2016_bark_beetle_mortality_area_fraction"),
    "FACTS": ("nfs_applicable_fraction", "documented_completed_prefire_implementation_area_fraction_within_nfs"),
    "RAP": ("rangeland_applicable_fraction", "conditional_2019_total_herbaceous_production_lb_ac"),
    "FDIST": ("fdist_valid_fraction", "fdist_any_disturbance_fraction"),
}

FORECAST_WEATHER = BASELINE[-5:]
REALIZED_WEATHER = (
    "realized_hrrr_u10_mean_earth_ms", "realized_hrrr_v10_mean_earth_ms",
    "realized_hrrr_gust_max_ms", "realized_hrrr_temperature_2m_mean_c",
    "realized_hrrr_relative_humidity_2m_min_pct",
)
def _immutable_contract(**values: str) -> MappingProxyType:
    """Return a deeply immutable leaf contract for frozen registry authority."""
    return MappingProxyType(values)


CONFIDENCE_SUPPORT_AUTHORITY = MappingProxyType({
    "manifest_path": "data/processed/propagation/paper1/pr24_response_free_support/pr24_manifest.json",
    "manifest_sha256": "60b56adb20fb4fe2264c74be09c9bd04b6fbab0adfce77119dcce9e9b62fdf52",
    "resolution_key": "1000",
    "selector_field": "support_universe_id",
    "included_field": "included",
})
CONFIDENCE_FAMILIES = MappingProxyType({
    "LEGACY_EAG_CONFIDENCE": _immutable_contract(
        field="legacy_eag_confidence_2019_conditional_mean",
        abundance_family="LEGACY_EAG",
        support_universe="LEGACY_EAG_CONFIDENCE_SENSITIVITY",
    ),
    "V5_EAG_CONFIDENCE": _immutable_contract(
        field="v5_eag_confidence_2019_conditional_mean",
        abundance_family="V5_EAG",
        support_universe="V5_EAG_CONFIDENCE_SENSITIVITY",
    ),
    "V5_CHEATGRASS_CONFIDENCE": _immutable_contract(
        field="v5_cheatgrass_confidence_2019_conditional_mean",
        abundance_family="V5_CHEATGRASS",
        support_universe="V5_CHEATGRASS_CONFIDENCE_SENSITIVITY",
    ),
})
CONFIDENCE_FIELDS = {
    family: str(contract["field"])
    for family, contract in CONFIDENCE_FAMILIES.items()
}
CONFIDENCE_MODEL_FAMILIES = ("LOGISTIC", "RF")
CONFIDENCE_OUTER_EVALUATIONS = MappingProxyType({
    "OUTER_EVAL_1_B2": MappingProxyType({
        "training_blocks": ("B1",),
        "training_intervals": (1, 3, 4, 5),
        "heldout_block": "B2",
        "heldout_intervals": (6, 8, 9, 10),
    }),
    "OUTER_EVAL_2_B3": MappingProxyType({
        "training_blocks": ("B1", "B2"),
        "training_intervals": (1, 3, 4, 5, 6, 8, 9, 10),
        "heldout_block": "B3",
        "heldout_intervals": (11, 12, 14, 15),
    }),
    "OUTER_EVAL_3_B4": MappingProxyType({
        "training_blocks": ("B1", "B2", "B3"),
        "training_intervals": (1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15),
        "heldout_block": "B4",
        "heldout_intervals": (16, 18, 21, 22),
    }),
})
CONFIDENCE_RUNTIME_SEMANTICS = MappingProxyType({
    "stratification_rule": "HELD_OUT_ABUNDANCE_DELTA_BY_NUMERIC_CONFIDENCE",
    "training_scope": "CURRENT_MODEL_TRAINING_HISTORY_ONLY",
    "cutoff_source": "TRAINING_HISTORY_ONLY",
    "cutoff_statistic": "MEDIAN",
    "equality_rule": "AT_OR_BELOW_VS_ABOVE_MEDIAN",
    "lower_condition": "x <= training-history median",
    "upper_condition": "x > training-history median",
    "lower_label": "AT_OR_BELOW_MEDIAN_NUMERIC_CONFIDENCE",
    "upper_label": "ABOVE_MEDIAN_NUMERIC_CONFIDENCE",
    "numeric_interpretation": "NEUTRAL_NUMERIC_ONLY",
    "predictor_use": "PROHIBITED",
    "weight_use": "PROHIBITED",
    "no_finite_training_confidence": "FAIL_CLOSED_NO_CUTOFF",
    "training_confidence_constant": "VALID_WITH_TRAINING_CONFIDENCE_CONSTANT_FLAG",
    "single_stratum_heldout": "VALID_RETAIN_ALL_ROWS_EMPTY_STRATUM_NOT_DEFINED_NO_ROWS",
    "nonfinite_heldout_confidence": "FAIL_CLOSED_NO_DROP_OR_IMPUTATION",
    "exact_median_equality": "ASSIGN_AT_OR_BELOW_MEDIAN_NUMERIC_CONFIDENCE",
})


def stratification_contract(analysis: Analysis) -> dict[str, object]:
    """Return machine-readable confidence-stratification authority."""
    family_contract = CONFIDENCE_FAMILIES.get(analysis.family)
    field = None if family_contract is None else str(family_contract["field"])
    if field is None:
        return {
            "stratification_enabled": False,
            "stratification_field": "",
            "stratification_rule": "NOT_APPLICABLE",
            "stratification_training_scope": "NOT_APPLICABLE",
            "stratification_cutoff_source": "NOT_APPLICABLE",
            "stratification_cutoff_statistic": "NOT_APPLICABLE",
            "stratification_groups": (),
            "stratification_equality_rule": "NOT_APPLICABLE",
            "stratification_lower_condition": "NOT_APPLICABLE",
            "stratification_upper_condition": "NOT_APPLICABLE",
            "stratification_lower_label": "NOT_APPLICABLE",
            "stratification_upper_label": "NOT_APPLICABLE",
            "stratification_predictor_use": "NOT_APPLICABLE",
            "stratification_weight_use": "NOT_APPLICABLE",
            "stratification_numeric_interpretation": "NOT_APPLICABLE",
            "stratification_model_families": (),
            "stratification_outer_evaluations": {},
            "stratification_no_finite_training_confidence": "NOT_APPLICABLE",
            "stratification_training_confidence_constant": "NOT_APPLICABLE",
            "stratification_single_stratum_heldout": "NOT_APPLICABLE",
            "stratification_nonfinite_heldout_confidence": "NOT_APPLICABLE",
            "stratification_exact_median_equality": "NOT_APPLICABLE",
            "stratification_status": "NOT_APPLICABLE",
        }
    semantics = CONFIDENCE_RUNTIME_SEMANTICS
    return {
        "stratification_enabled": True,
        "stratification_field": field,
        "stratification_rule": semantics["stratification_rule"],
        "stratification_training_scope": semantics["training_scope"],
        "stratification_cutoff_source": semantics["cutoff_source"],
        "stratification_cutoff_statistic": semantics["cutoff_statistic"],
        "stratification_groups": (
            "AT_OR_BELOW_MEDIAN_NUMERIC_CONFIDENCE",
            "ABOVE_MEDIAN_NUMERIC_CONFIDENCE",
        ),
        "stratification_equality_rule": semantics["equality_rule"],
        "stratification_lower_condition": semantics["lower_condition"],
        "stratification_upper_condition": semantics["upper_condition"],
        "stratification_lower_label": semantics["lower_label"],
        "stratification_upper_label": semantics["upper_label"],
        "stratification_predictor_use": semantics["predictor_use"],
        "stratification_weight_use": semantics["weight_use"],
        "stratification_numeric_interpretation": semantics["numeric_interpretation"],
        "stratification_model_families": CONFIDENCE_MODEL_FAMILIES,
        "stratification_outer_evaluations": CONFIDENCE_OUTER_EVALUATIONS,
        "stratification_support_authority": CONFIDENCE_SUPPORT_AUTHORITY,
        "stratification_no_finite_training_confidence": semantics["no_finite_training_confidence"],
        "stratification_training_confidence_constant": semantics["training_confidence_constant"],
        "stratification_single_stratum_heldout": semantics["single_stratum_heldout"],
        "stratification_nonfinite_heldout_confidence": semantics["nonfinite_heldout_confidence"],
        "stratification_exact_median_equality": semantics["exact_median_equality"],
        "stratification_status": "READY_PREFIT",
    }


def comparator_contract(analysis: Analysis) -> dict[str, object]:
    """Return the frozen mechanical comparator semantics for G05A/G07."""
    if not analysis.executable_status.startswith("EXECUTABLE"):
        comparator = {"comparator_type": "DISABLED_NONEXECUTING", "augment_fields": (), "replace_fields": {}}
    elif analysis.family == "PRIMARY_EVT":
        comparator = {"comparator_type": "PRIMARY_EVT", "augment_fields": EVT, "replace_fields": {}}
    elif analysis.family == "DOMINANT_FBFM40":
        comparator = {
            "comparator_type": "ALTERNATE_REPRESENTATION",
            "augment_fields": (),
            "replace_fields": {field: "dominant_fbfm40" for field in FBFM},
        }
    elif analysis.family == "REALIZED_WEATHER":
        comparator = {
            "comparator_type": "REPLACE_FIELDS",
            "augment_fields": (),
            "replace_fields": dict(zip(FORECAST_WEATHER, REALIZED_WEATHER)),
        }
    else:
        comparator = {
            "comparator_type": "AUGMENT_FIELDS",
            "augment_fields": tuple(analysis.augmented_fields),
            "replace_fields": {},
        }
    return {**comparator, **stratification_contract(analysis)}


def primary_table(root: Path, resolution_m: int) -> Path:
    suffix = "1km" if resolution_m == 1000 else "2km"
    return root / "data/processed/propagation/paper1/pr31_labeled_tables/outputs" / f"paper1_pr31_labeled_table_{suffix}.parquet"


def primary_support(root: Path, resolution_m: int) -> Path:
    suffix = "1km" if resolution_m == 1000 else "2km"
    return root / "data/processed/propagation/paper1/pr24_response_free_support/outputs" / f"paper1_pr24_support_masks_{suffix}.parquet"


def alt_table(root: Path, risk_set_id: str, resolution_m: int) -> Path:
    slug = risk_set_id.lower()
    suffix = "1km" if resolution_m == 1000 else "2km"
    return root / "data/processed/propagation/paper1/pr32b_alt_riskset_labeled" / risk_set_id / "outputs" / f"paper1_pr32b_labeled_{slug}_{suffix}.parquet"


def alt_support(root: Path, risk_set_id: str, resolution_m: int) -> Path:
    slug = risk_set_id.lower()
    suffix = "1km" if resolution_m == 1000 else "2km"
    return root / "data/processed/propagation/paper1/pr32a_alt_riskset_response_free/support" / risk_set_id / "outputs" / f"paper1_pr32a_support_masks_{slug}_{suffix}.parquet"


def registry(root: Path) -> list[Analysis]:
    authority = "documentation/PAPER1_MODEL_FORMULATION_SPEC.md; documentation/PAPER1_MODEL_SENSITIVITY_HIERARCHY.csv"
    common = dict(
        response_source="PR31 binary center-covered response" , predictor_source="PR31/PR23 frozen labeled predictor table",
        baseline_comparator="baseline 24", logistic_handling="PR34 logistic encoding, canopy structural zero, training-only scaling",
        rf_handling="PR34 raw numeric/composition plus fixed hybrid one-hot", tuning_inheritance="G03/PR33 governed inheritance; fixed conservative settings where mandated; alternate risk sets never retuned",
        paired_row_rule="exact support-universe keys shared by baseline and augmented design", executable_status="EXECUTABLE_PREFIT", authority=authority,
    )
    items = [
        Analysis("G05A_01_PRIMARY_EVT_1KM", "PRIMARY_EVT", "PRIMARY_CONFIRMATORY", 1000, "PRIMARY_HYBRID", "ALL_LOCKED", "PRIMARY_CONFIRMATORY", **common, augmented_fields=EVT, retrospective=False, notes="Primary unchanged."),
        Analysis("G05A_02_PRIMARY_EVT_2KM", "PRIMARY_EVT", "REQUIRED_ROBUSTNESS", 2000, "PRIMARY_HYBRID", "ALL_LOCKED", "PRIMARY_CONFIRMATORY", **common, augmented_fields=EVT, retrospective=False, notes="Direct 2 km table."),
        Analysis("G05A_03_PRIMARY_EVT_NO_EARLY", "PRIMARY_EVT", "REQUIRED_ROBUSTNESS", 1000, "PRIMARY_HYBRID", "NO_EARLY", "PRIMARY_CONFIRMATORY", **common, augmented_fields=EVT, retrospective=False, notes="Intervals 4,5,6,8,9,10,11,12,14,15,16,18,21,22 only."),
    ]
    for risk in ("ACTIVE_FRONT_ONLY_5KM", "PERIMETER_ONLY_2KM", "PERIMETER_ONLY_5KM"):
        for resolution in (1000, 2000):
            items.append(Analysis(f"G05A_{len(items)+1:02d}_{risk}_{resolution}", "PRIMARY_EVT", "REQUIRED_RISK_SET_ROBUSTNESS", resolution, risk, "ALL_LOCKED", "PRIMARY_CONFIRMATORY", **common, augmented_fields=EVT, retrospective=False, notes="PR32A support and PR32B labels; inherit corresponding primary-hybrid setting without retuning."))
    family_rows = [
        ("EVC", "SECONDARY_CONFIRMATORY", "EVC_SENSITIVITY", False), ("EVH", "SECONDARY_CONFIRMATORY", "EVH_SENSITIVITY", False),
        ("LEGACY_EAG", "SECONDARY_CONFIRMATORY", "LEGACY_EAG_SENSITIVITY", False), ("V5_EAG", "RETROSPECTIVE_CONFIRMATORY", "V5_EAG_SENSITIVITY", True),
        ("V5_CHEATGRASS", "RETROSPECTIVE_CONFIRMATORY", "V5_CHEATGRASS_SENSITIVITY", True), ("PRIOR_MTBS", "SECONDARY_CONFIRMATORY", "PRIOR_MTBS_SENSITIVITY", False),
        ("FOREST_HEALTH", "SECONDARY_CONFIRMATORY", "FOREST_HEALTH_SENSITIVITY", False), ("FACTS", "SECONDARY_CONFIRMATORY", "FACTS_SENSITIVITY", True),
        ("RAP", "SECONDARY_CONFIRMATORY", "RAP_SENSITIVITY", True), ("FDIST", "EXPLORATORY", "FDIST_EXPLORATORY", False),
    ]
    for family, hierarchy, support, retrospective in family_rows:
        items.append(Analysis(f"G05A_{len(items)+1:02d}_{family}", family, hierarchy, 1000, "PRIMARY_HYBRID", "ALL_LOCKED", support, **common, augmented_fields=FAMILY_FIELDS[family], retrospective=retrospective, notes="One family only; no omnibus complete case."))
    for family, abundance, confidence, retrospective in (
        ("LEGACY_EAG_CONFIDENCE", "LEGACY_EAG", "legacy_eag_confidence_2019_conditional_mean", False),
        ("V5_EAG_CONFIDENCE", "V5_EAG", "v5_eag_confidence_2019_conditional_mean", True),
        ("V5_CHEATGRASS_CONFIDENCE", "V5_CHEATGRASS", "v5_cheatgrass_confidence_2019_conditional_mean", True),
    ):
        items.append(Analysis(f"G05A_{len(items)+1:02d}_{family}", family, "QUALITY_SENSITIVITY", 1000, "PRIMARY_HYBRID", "ALL_LOCKED", f"{family}_SENSITIVITY", **common, augmented_fields=FAMILY_FIELDS[abundance], retrospective=retrospective, notes=f"{confidence} is a training-history-median stratum field only; never a model predictor."))
    items.append(Analysis(f"G05A_{len(items)+1:02d}_DOMINANT_FBFM40", "DOMINANT_FBFM40", "CONFIRMATORY_AGGREGATION_SENSITIVITY", 1000, "PRIMARY_HYBRID", "ALL_LOCKED", "PRIMARY_CONFIRMATORY", **common, augmented_fields=FBFM, retrospective=False, notes="Replace the five FBFM fractions with governed dominant class; exact ties are TIE."))
    for resolution in (1000, 2000):
        items.append(Analysis(f"G05A_{len(items)+1:02d}_REALIZED_WEATHER_{resolution}", "REALIZED_WEATHER", "RETROSPECTIVE_REALIZED_WEATHER_SENSITIVITY", resolution, "PRIMARY_HYBRID", "ALL_LOCKED", "PRIMARY_CONFIRMATORY", **common, augmented_fields=("realized_hrrr_u10_mean_earth_ms", "realized_hrrr_v10_mean_earth_ms", "realized_hrrr_gust_max_ms", "realized_hrrr_temperature_2m_mean_c", "realized_hrrr_relative_humidity_2m_min_pct"), retrospective=True, notes="Replace only five forecast weather fields; nearest-native QC fields prohibited; inherit corresponding primary-hybrid setting without retuning."))
    items.extend([
        Analysis("G05A_DISABLED_RCMAP", "RCMAP", "DOCUMENT_ONLY_EXPLORATORY_CONTEXT", None, None, "NOT_APPLICABLE", None, None, None, "NOT_APPLICABLE", (), "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", False, "NOT_APPLICABLE", "DISABLED_DOCUMENT_ONLY", "documentation/PAPER1_G02_SCIENTIFIC_AUTHORITY_DECISIONS.csv"),
        Analysis("G05A_DISABLED_SECTOR", "GEOGRAPHIC_SECTOR", "SCIENTIFICALLY_DEPRECATED_BEFORE_FIT", None, None, "NOT_APPLICABLE", None, None, None, "NOT_APPLICABLE", (), "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", False, "NOT_APPLICABLE", "DISABLED_DEPRECATED", "documentation/PAPER1_G02_SCIENTIFIC_AUTHORITY_DECISIONS.csv"),
        Analysis("G05A_DISABLED_SUPPRESSION", "SUPPRESSION", "DOCUMENT_ONLY_SUPPRESSION_LIMITATION", None, None, "NOT_APPLICABLE", None, None, None, "NOT_APPLICABLE", (), "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", False, "NOT_APPLICABLE", "DISABLED_DOCUMENT_ONLY", "documentation/PAPER1_G02_SCIENTIFIC_AUTHORITY_DECISIONS.csv"),
        Analysis("G05A_DISABLED_FIREBRAND", "FIREBRAND", "DEFERRED_PENDING_DEDICATED_AUDIT", None, None, "NOT_APPLICABLE", None, None, None, "NOT_APPLICABLE", (), "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", False, "NOT_APPLICABLE", "DISABLED_DEFERRED", "documentation/PAPER1_CANDIDATE_FAMILY_DISPOSITION.csv"),
        Analysis("G05A_DISABLED_SEVERITY", "SEVERITY_DNBR_RDNBR", "SUPERSEDED_INACTIVE_PAPER1_ARCHITECTURE", None, None, "NOT_APPLICABLE", None, None, None, "NOT_APPLICABLE", (), "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", False, "NOT_APPLICABLE", "DISABLED_SUPERSEDED", "AGENTS.md"),
    ])
    return items


def rows(root: Path) -> pd.DataFrame:
    return pd.DataFrame([item.row() for item in registry(root)])
