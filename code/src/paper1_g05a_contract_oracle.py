"""Independent frozen-authority oracle and confidence runtime guard for G05A.

This module contains no estimators or scientific execution. Comparator schema
constants remain independent frozen expectations; confidence runtime authority
comes from the immutable registry and hash-verified PR24 support artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from src import paper1_analysis_registry as registry


BASELINE_RAW = (
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
EVT_RAW = (
    "evt_tree_fraction", "evt_shrub_fraction", "evt_perennial_herbaceous_fraction",
    "evt_annual_herbaceous_fraction", "evt_other_fraction",
)
FBFM_RAW = (
    "fbfm_grass_grass_shrub_fraction", "fbfm_shrub_fraction", "fbfm_timber_fraction",
    "fbfm_slash_blowdown_fraction", "fbfm_nonburnable_fraction",
)
HYBRID_LEVELS = ("BOTH", "ACTIVE_ONLY", "PERIMETER_BACKSTOP_ONLY", "NEITHER_PRIMARY_COMPONENT")
FORECAST_WEATHER = BASELINE_RAW[-5:]
REALIZED_WEATHER = (
    "realized_hrrr_u10_mean_earth_ms", "realized_hrrr_v10_mean_earth_ms",
    "realized_hrrr_gust_max_ms", "realized_hrrr_temperature_2m_mean_c",
    "realized_hrrr_relative_humidity_2m_min_pct",
)
ORDINARY_AUGMENTATIONS = MappingProxyType({
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
})
DOMINANT_LEVELS = ("GRASS_GRASS_SHRUB", "SHRUB", "TIMBER", "SLASH_BLOWDOWN", "NONBURNABLE")
DOMINANT_RF_CODES = {
    "GRASS_GRASS_SHRUB": 0.0,
    "SHRUB": 1.0,
    "TIMBER": 2.0,
    "SLASH_BLOWDOWN": 3.0,
    "NONBURNABLE": 4.0,
    "TIE": 5.0,
}
EQUALITY_CONVENTION = str(registry.CONFIDENCE_RUNTIME_SEMANTICS["equality_rule"])
LOWER_LABEL = str(registry.CONFIDENCE_RUNTIME_SEMANTICS["lower_label"])
UPPER_LABEL = str(registry.CONFIDENCE_RUNTIME_SEMANTICS["upper_label"])
LOWER_CONDITION = str(registry.CONFIDENCE_RUNTIME_SEMANTICS["lower_condition"])
UPPER_CONDITION = str(registry.CONFIDENCE_RUNTIME_SEMANTICS["upper_condition"])
CUTOFF_SOURCE = str(registry.CONFIDENCE_RUNTIME_SEMANTICS["cutoff_source"])
NUMERIC_INTERPRETATION = str(registry.CONFIDENCE_RUNTIME_SEMANTICS["numeric_interpretation"])


@dataclass(frozen=True)
class ConfidenceRuntimeAuthority:
    """Deeply immutable references to the registry authority consumed by dispatch."""

    families: Mapping[str, Mapping[str, object]]
    support: Mapping[str, object]
    semantics: Mapping[str, object]
    model_families: tuple[str, ...]
    outer_evaluations: Mapping[str, Mapping[str, object]]


CONFIDENCE_RUNTIME_AUTHORITY = ConfidenceRuntimeAuthority(
    families=registry.CONFIDENCE_FAMILIES,
    support=registry.CONFIDENCE_SUPPORT_AUTHORITY,
    semantics=registry.CONFIDENCE_RUNTIME_SEMANTICS,
    model_families=registry.CONFIDENCE_MODEL_FAMILIES,
    outer_evaluations=registry.CONFIDENCE_OUTER_EVALUATIONS,
)


def confidence_family_authority(family: str) -> Mapping[str, object] | None:
    """Return one immutable registry family contract without creating a shadow copy."""
    return CONFIDENCE_RUNTIME_AUTHORITY.families.get(family)


def confidence_abundance_fields(family: str) -> tuple[str, ...]:
    contract = confidence_family_authority(family)
    if contract is None:
        raise ContractError("ERR_CONFIDENCE_ANALYSIS", "analysis is not governed")
    abundance_family = str(contract["abundance_family"])
    return tuple(ORDINARY_AUGMENTATIONS[abundance_family])


class ContractError(RuntimeError):
    """A G05A frozen-contract assertion failed."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class ConfidenceCutoffReceipt:
    analysis_id: str
    analysis_family: str
    outer_evaluation_identity: str
    model_families: tuple[str, ...]
    training_blocks: tuple[str, ...]
    training_intervals: tuple[int, ...]
    heldout_block: str
    heldout_intervals: tuple[int, ...]
    confidence_field: str
    support_universe: str
    governed_support_manifest: str
    governed_support_manifest_sha256: str
    governed_support_source_artifact: str
    governed_support_source_sha256: str
    governed_support_selector: str
    governed_support_row_count: int
    support_key_hash: str
    training_governed_key_count: int
    training_governed_key_hash: str
    heldout_governed_key_count: int
    heldout_governed_key_hash: str
    training_row_count: int
    finite_training_count: int
    finite_unique_training_count: int
    training_exact_equality_count: int
    heldout_row_count: int
    heldout_finite_count: int
    lower_count: int
    upper_count: int
    heldout_exact_equality_count: int
    cutoff_statistic: str
    cutoff_value: float
    cutoff_source: str
    training_scope: str
    equality_convention: str
    lower_condition: str
    upper_condition: str
    lower_label: str
    upper_label: str
    predictor_use: str
    weight_use: str
    numeric_interpretation: str
    training_status: str
    lower_summary_status: str
    upper_summary_status: str
    row_order_policy: str
    assignment_sha256: str


@dataclass(frozen=True)
class ConfidenceDispatchResult:
    receipt: ConfidenceCutoffReceipt
    strata: pd.Series


@dataclass(frozen=True)
class GovernedConfidenceSupport:
    manifest_path: str
    manifest_sha256: str
    artifact_path: str
    artifact_sha256: str
    selector: str
    keys: pd.DataFrame
    key_hash: str


def _logistic_schema(raw: Sequence[str], *, evt_reference: bool = False) -> tuple[str, ...]:
    excluded = {"hybrid_membership", "fbfm_nonburnable_fraction"}
    if evt_reference:
        excluded.add("evt_other_fraction")
    numeric = tuple(field for field in raw if field not in excluded)
    indicators = tuple(f"hybrid_{level}" for level in HYBRID_LEVELS[1:])
    return numeric + indicators


def _rf_schema(raw: Sequence[str]) -> tuple[str, ...]:
    numeric = tuple(field for field in raw if field != "hybrid_membership")
    indicators = tuple(f"hybrid_{level}" for level in HYBRID_LEVELS)
    return numeric + indicators


def expected_comparator_type(family: str) -> str:
    if family == "PRIMARY_EVT":
        return "PRIMARY_EVT"
    if family == "DOMINANT_FBFM40":
        return "ALTERNATE_REPRESENTATION"
    if family == "REALIZED_WEATHER":
        return "REPLACE_FIELDS"
    if family in ORDINARY_AUGMENTATIONS or family in CONFIDENCE_RUNTIME_AUTHORITY.families:
        return "AUGMENT_FIELDS"
    raise ContractError(f"no executable oracle contract for family: {family}")


def expected_schemas(family: str, model_family: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if model_family == "logistic":
        baseline = _logistic_schema(BASELINE_RAW)
    elif model_family == "rf":
        baseline = _rf_schema(BASELINE_RAW)
    else:
        raise ContractError(f"unknown model family: {model_family}")

    if family == "PRIMARY_EVT":
        raw = BASELINE_RAW + EVT_RAW
        augmented = _logistic_schema(raw, evt_reference=True) if model_family == "logistic" else _rf_schema(raw)
    elif family == "DOMINANT_FBFM40":
        raw = tuple(field for field in BASELINE_RAW if field not in FBFM_RAW)
        base = _logistic_schema(raw) if model_family == "logistic" else _rf_schema(raw)
        if model_family == "logistic":
            dominant = tuple(
                f"dominant_fbfm_{level}"
                for level in ("GRASS_GRASS_SHRUB", "SHRUB", "TIMBER", "SLASH_BLOWDOWN", "TIE")
            )
        else:
            dominant = ("dominant_fbfm_code",)
        augmented = base + dominant
    elif family == "REALIZED_WEATHER":
        replacement = dict(zip(FORECAST_WEATHER, REALIZED_WEATHER))
        augmented = tuple(replacement.get(field, field) for field in baseline)
    else:
        extras = (
            confidence_abundance_fields(family)
            if family in CONFIDENCE_RUNTIME_AUTHORITY.families
            else ORDINARY_AUGMENTATIONS[family]
        )
        raw = BASELINE_RAW + tuple(extras)
        augmented = _logistic_schema(raw) if model_family == "logistic" else _rf_schema(raw)
    return baseline, augmented


def expected_difference(family: str, model_family: str) -> set[str]:
    baseline, augmented = expected_schemas(family, model_family)
    return set(baseline).symmetric_difference(augmented)


def validate_pair_against_oracle(pair, family: str, model_family: str) -> None:
    baseline, augmented = expected_schemas(family, model_family)
    if pair.comparator_type != expected_comparator_type(family):
        raise ContractError("ERR_COMPARATOR_TYPE")
    if tuple(pair.baseline.columns) != baseline or tuple(pair.augmented.columns) != augmented:
        raise ContractError("ERR_COMPARATOR_SCHEMA")
    if (
        pair.baseline_keys.duplicated().any()
        or pair.augmented_keys.duplicated().any()
        or not pair.baseline_keys.equals(pair.augmented_keys)
        or not pair.baseline.index.equals(pair.augmented.index)
    ):
        raise ContractError("ERR_COMPARATOR_KEYS")
    common = pair.baseline.columns.intersection(pair.augmented.columns, sort=False)
    if not np.array_equal(
        pair.baseline.loc[:, common].to_numpy(),
        pair.augmented.loc[:, common].to_numpy(),
        equal_nan=True,
    ):
        raise ContractError("ERR_COMPARATOR_COMMON_VALUES")
    if not np.isfinite(pair.baseline.to_numpy(float)).all() or not np.isfinite(pair.augmented.to_numpy(float)).all():
        raise ContractError("ERR_COMPARATOR_NONFINITE")


def validate_support_keys(pair, expected_keys: pd.DataFrame) -> None:
    expected = expected_keys.reset_index(drop=True)
    if not pair.baseline_keys.equals(expected) or not pair.augmented_keys.equals(expected):
        raise ContractError("ERR_SUPPORT_KEYS")


def dominant_labels(frame: pd.DataFrame) -> np.ndarray:
    values = frame.loc[:, list(FBFM_RAW)].to_numpy(float)
    maxima = values.max(axis=1, keepdims=True)
    tie = (values == maxima).sum(axis=1) > 1
    levels = np.asarray(DOMINANT_LEVELS, dtype=object)
    labels = levels[np.argmax(values, axis=1)]
    labels[tie] = "TIE"
    return labels


def validate_dominant_values(pair, frame: pd.DataFrame, model_family: str) -> None:
    labels = dominant_labels(frame)
    if model_family == "logistic":
        if "dominant_fbfm_NONBURNABLE" in pair.augmented:
            raise ContractError("ERR_DOMINANT_REFERENCE")
        for level in ("GRASS_GRASS_SHRUB", "SHRUB", "TIMBER", "SLASH_BLOWDOWN", "TIE"):
            expected = (labels == level).astype(float)
            if not np.array_equal(pair.augmented[f"dominant_fbfm_{level}"].to_numpy(), expected):
                raise ContractError("ERR_DOMINANT_CATEGORY")
    else:
        expected = np.asarray([DOMINANT_RF_CODES[label] for label in labels], dtype=float)
        if not np.array_equal(pair.augmented["dominant_fbfm_code"].to_numpy(), expected):
            raise ContractError("ERR_DOMINANT_RF_CODE")


def validate_confidence_contract(analysis, contract: Mapping[str, object]) -> None:
    expected = confidence_family_authority(analysis.family)
    if expected is None:
        raise ContractError("ERR_CONFIDENCE_ANALYSIS", "analysis is not governed")
    semantics = registry.CONFIDENCE_RUNTIME_SEMANTICS
    required = {
        "stratification_enabled": True,
        "stratification_field": expected["field"],
        "stratification_rule": "HELD_OUT_ABUNDANCE_DELTA_BY_NUMERIC_CONFIDENCE",
        "stratification_training_scope": "CURRENT_MODEL_TRAINING_HISTORY_ONLY",
        "stratification_cutoff_source": CUTOFF_SOURCE,
        "stratification_cutoff_statistic": "MEDIAN",
        "stratification_groups": (LOWER_LABEL, UPPER_LABEL),
        "stratification_equality_rule": EQUALITY_CONVENTION,
        "stratification_lower_condition": LOWER_CONDITION,
        "stratification_upper_condition": UPPER_CONDITION,
        "stratification_lower_label": LOWER_LABEL,
        "stratification_upper_label": UPPER_LABEL,
        "stratification_predictor_use": "PROHIBITED",
        "stratification_weight_use": "PROHIBITED",
        "stratification_numeric_interpretation": NUMERIC_INTERPRETATION,
        "stratification_model_families": registry.CONFIDENCE_MODEL_FAMILIES,
        "stratification_outer_evaluations": registry.CONFIDENCE_OUTER_EVALUATIONS,
        "stratification_support_authority": registry.CONFIDENCE_SUPPORT_AUTHORITY,
        "stratification_no_finite_training_confidence": semantics["no_finite_training_confidence"],
        "stratification_training_confidence_constant": semantics["training_confidence_constant"],
        "stratification_single_stratum_heldout": semantics["single_stratum_heldout"],
        "stratification_nonfinite_heldout_confidence": semantics["nonfinite_heldout_confidence"],
        "stratification_exact_median_equality": semantics["exact_median_equality"],
        "stratification_status": "READY_PREFIT",
    }
    for key, value in required.items():
        if contract.get(key) != value:
            raise ContractError("ERR_CONFIDENCE_CONTRACT", key)
    if tuple(contract.get("augment_fields", ())) != confidence_abundance_fields(analysis.family):
        raise ContractError("ERR_CONFIDENCE_CONTRACT", "abundance fields")
    if analysis.support_universe != expected["support_universe"]:
        raise ContractError("ERR_CONFIDENCE_SUPPORT_IDENTITY", "analysis support universe")


def validate_confidence_cutoff(
    receipt: ConfidenceCutoffReceipt,
    frame: pd.DataFrame,
) -> None:
    canonical = frame.sort_values(list(registry.KEYS), kind="stable").reset_index(drop=True)
    intervals = _interval_numbers(canonical.loc[:, list(registry.KEYS)])
    values = canonical.loc[
        intervals.isin(receipt.training_intervals), receipt.confidence_field
    ].to_numpy(float)
    if not np.isfinite(values).all():
        raise ContractError("ERR_CONFIDENCE_NONFINITE_TRAINING")
    expected = float(np.median(values))
    if receipt.cutoff_value != expected:
        raise ContractError("ERR_CONFIDENCE_CUTOFF_SOURCE")


def confidence_support_key_hash(keys: pd.DataFrame) -> str:
    """Return the canonical hash for one governed confidence-support key set."""
    missing = [field for field in registry.KEYS if field not in keys]
    if missing:
        raise ContractError("ERR_CONFIDENCE_SUPPORT_IDENTITY", f"missing keys {missing}")
    ordered = keys.loc[:, list(registry.KEYS)].sort_values(list(registry.KEYS), kind="stable")
    if ordered.duplicated().any():
        raise ContractError("ERR_CONFIDENCE_SUPPORT_IDENTITY", "duplicate keys")
    payload = ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def authenticate_governed_file(path: Path, expected_sha256: str, label: str) -> str:
    """Fail closed unless one governed file exists and matches its frozen hash."""
    if not path.is_file():
        raise ContractError("ERR_CONFIDENCE_SUPPORT_AUTHORITY", f"missing {label}")
    observed = _sha256_file(path)
    if observed != expected_sha256:
        raise ContractError("ERR_CONFIDENCE_SUPPORT_AUTHORITY", f"{label} hash")
    return observed


@lru_cache(maxsize=None)
def _read_parquet_immutable(path_text: str) -> pd.DataFrame:
    """Reuse an authenticated immutable parquet payload within one process."""
    return pd.read_parquet(Path(path_text))


def _canonical_keys(frame: pd.DataFrame, reason: str = "ERR_CONFIDENCE_SUPPORT_KEYS") -> pd.DataFrame:
    missing = [field for field in registry.KEYS if field not in frame]
    if missing:
        raise ContractError(reason, f"missing keys {missing}")
    keys = frame.loc[:, list(registry.KEYS)].sort_values(
        list(registry.KEYS), kind="stable"
    ).reset_index(drop=True)
    if keys.duplicated().any():
        raise ContractError(reason, "duplicate keys")
    return keys


def _interval_numbers(keys: pd.DataFrame) -> pd.Series:
    extracted = keys["interval_id"].astype(str).str.extract(r"_I(\d+)$", expand=False)
    if extracted.isna().any():
        raise ContractError("ERR_CONFIDENCE_SUPPORT_KEYS", "unparseable interval_id")
    return extracted.astype(int)


def governed_confidence_support(project_root: Path, analysis) -> GovernedConfidenceSupport:
    """Resolve exact confidence support from hash-verified frozen PR24 authority."""
    authority = CONFIDENCE_RUNTIME_AUTHORITY
    family = authority.families.get(analysis.family)
    if family is None:
        raise ContractError("ERR_CONFIDENCE_ANALYSIS", "missing family authority")
    support_authority = authority.support
    manifest_relative = str(support_authority["manifest_path"])
    manifest_path = project_root / manifest_relative
    manifest_hash = authenticate_governed_file(
        manifest_path, str(support_authority["manifest_sha256"]), "PR24 manifest"
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        output = manifest["outputs"][str(support_authority["resolution_key"])]
        artifact_relative = str(output["path"])
        artifact_expected_hash = str(output["sha256"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError("ERR_CONFIDENCE_SUPPORT_AUTHORITY", "invalid PR24 manifest") from exc
    artifact_path = (project_root / artifact_relative).resolve()
    root_resolved = project_root.resolve()
    if root_resolved not in artifact_path.parents or not artifact_path.is_file():
        raise ContractError("ERR_CONFIDENCE_SUPPORT_AUTHORITY", "missing or unsafe PR24 artifact")
    artifact_hash = authenticate_governed_file(
        artifact_path, artifact_expected_hash, "PR24 artifact"
    )
    support = _read_parquet_immutable(str(artifact_path))
    selector_field = str(support_authority["selector_field"])
    included_field = str(support_authority["included_field"])
    required = {*registry.KEYS, selector_field, included_field}
    missing = sorted(required.difference(support.columns))
    if missing:
        raise ContractError("ERR_CONFIDENCE_SUPPORT_AUTHORITY", f"missing columns {missing}")
    selector = str(family["support_universe"])
    selected = support.loc[
        support[selector_field].eq(selector) & support[included_field].astype(bool)
    ]
    keys = _canonical_keys(selected)
    if keys.empty or not keys["response_grid_m"].eq(1000).all():
        raise ContractError("ERR_CONFIDENCE_SUPPORT_AUTHORITY", "empty or wrong-resolution support")
    return GovernedConfidenceSupport(
        manifest_path=manifest_relative,
        manifest_sha256=manifest_hash,
        artifact_path=artifact_relative,
        artifact_sha256=artifact_hash,
        selector=selector,
        keys=keys,
        key_hash=confidence_support_key_hash(keys),
    )


def confidence_assignment_hash(keys: pd.DataFrame, labels: Sequence[str]) -> str:
    """Hash canonical governed key-to-label records, independent of input row order."""
    missing = [field for field in registry.KEYS if field not in keys]
    if missing:
        raise ContractError("ERR_CONFIDENCE_ASSIGNMENT_IDENTITY", f"missing keys {missing}")
    if len(keys) != len(labels):
        raise ContractError("ERR_CONFIDENCE_ASSIGNMENT_IDENTITY", "row count")
    records = keys.loc[:, list(registry.KEYS)].copy()
    records["confidence_stratum"] = np.asarray(labels, dtype=object)
    records = records.sort_values(list(registry.KEYS), kind="stable").reset_index(drop=True)
    if records.loc[:, list(registry.KEYS)].duplicated().any():
        raise ContractError("ERR_CONFIDENCE_ASSIGNMENT_IDENTITY", "duplicate keys")
    payload = records.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stratify_confidence_values(
    training_values: Sequence[float],
    heldout_values: Sequence[float],
) -> dict[str, object]:
    """Apply the frozen numeric rule without issuing an authoritative receipt."""
    training = np.asarray(training_values, dtype=float)
    heldout = np.asarray(heldout_values, dtype=float)
    if training.size == 0 or not np.isfinite(training).all():
        raise ContractError("ERR_CONFIDENCE_NONFINITE_TRAINING")
    if not np.isfinite(heldout).all():
        raise ContractError("ERR_CONFIDENCE_NONFINITE_HELDOUT")
    cutoff = float(np.median(training))
    lower = heldout <= cutoff
    upper = heldout > cutoff
    if not np.all(lower ^ upper) or np.any(lower & upper):
        raise ContractError("ERR_CONFIDENCE_STRATUM_ASSIGNMENT")
    semantics = CONFIDENCE_RUNTIME_AUTHORITY.semantics
    return {
        "cutoff": cutoff,
        "training_unique": int(np.unique(training).size),
        "training_equal": int(np.count_nonzero(training == cutoff)),
        "heldout_equal": int(np.count_nonzero(heldout == cutoff)),
        "lower": lower,
        "upper": upper,
        "labels": np.where(lower, semantics["lower_label"], semantics["upper_label"]),
    }


def dispatch_confidence_strata(
    analysis_id: str,
    frame: pd.DataFrame,
    *,
    project_root: Path,
    outer_evaluation_identity: str,
    predictor_columns: Sequence[str],
    support_rows: pd.DataFrame | None = None,
    model_families: Sequence[str] | None = None,
    training_blocks: Sequence[str] | None = None,
    training_intervals: Sequence[int] | None = None,
    heldout_block: str | None = None,
    heldout_intervals: Sequence[int] | None = None,
    support_universe: str | None = None,
    sample_weight=None,
) -> ConfidenceDispatchResult:
    """Authenticate PR24 support, then freeze and apply a training-only cutoff."""
    matches = [
        item for item in registry.registry(project_root)
        if item.analysis_id == analysis_id
    ]
    if len(matches) != 1:
        raise ContractError("ERR_CONFIDENCE_ANALYSIS", "unknown or duplicate analysis_id")
    analysis = matches[0]
    authority = CONFIDENCE_RUNTIME_AUTHORITY
    expected = authority.families.get(analysis.family)
    if expected is None:
        raise ContractError("ERR_CONFIDENCE_ANALYSIS", "missing authority")
    if analysis.support_universe != expected["support_universe"]:
        raise ContractError("ERR_CONFIDENCE_SUPPORT_IDENTITY", "analysis support universe")
    if support_universe is not None and support_universe != analysis.support_universe:
        raise ContractError("ERR_CONFIDENCE_SUPPORT_IDENTITY", "support label")
    governed = governed_confidence_support(project_root, analysis)
    frame_keys = _canonical_keys(frame)
    if not frame_keys.equals(governed.keys):
        raise ContractError("ERR_CONFIDENCE_SUPPORT_KEYS", "frame differs from frozen PR24 support")
    if support_rows is not None:
        selector_field = str(authority.support["selector_field"])
        included_field = str(authority.support["included_field"])
        if selector_field not in support_rows or included_field not in support_rows:
            raise ContractError("ERR_CONFIDENCE_SUPPORT_KEYS", "caller support fields")
        supplied = support_rows.loc[
            support_rows[selector_field].eq(governed.selector)
            & support_rows[included_field].astype(bool)
        ]
        supplied_keys = _canonical_keys(supplied)
        if not supplied_keys.equals(governed.keys):
            raise ContractError("ERR_CONFIDENCE_SUPPORT_KEYS", "caller support differs from frozen PR24 support")
    field = str(expected["field"])
    if field not in frame:
        raise ContractError("ERR_CONFIDENCE_FIELD")
    if field in predictor_columns:
        raise ContractError("ERR_CONFIDENCE_PREDICTOR_PROHIBITED")
    if sample_weight is not None:
        raise ContractError("ERR_CONFIDENCE_WEIGHT_PROHIBITED")

    evaluation = authority.outer_evaluations.get(outer_evaluation_identity)
    if evaluation is None:
        raise ContractError("ERR_CONFIDENCE_EVALUATION_IDENTITY")
    if model_families is not None and tuple(model_families) != authority.model_families:
        raise ContractError("ERR_CONFIDENCE_MODEL_FAMILY")
    if training_blocks is not None and tuple(training_blocks) != tuple(evaluation["training_blocks"]):
        raise ContractError("ERR_CONFIDENCE_TRAINING_BLOCKS")
    if training_intervals is not None and tuple(int(value) for value in training_intervals) != tuple(evaluation["training_intervals"]):
        raise ContractError("ERR_CONFIDENCE_TRAINING_INTERVALS")
    if heldout_block is not None and heldout_block != evaluation["heldout_block"]:
        raise ContractError("ERR_CONFIDENCE_HELDOUT_BLOCK")
    if heldout_intervals is not None and tuple(int(value) for value in heldout_intervals) != tuple(evaluation["heldout_intervals"]):
        raise ContractError("ERR_CONFIDENCE_HELDOUT_INTERVALS")

    canonical = frame.sort_values(list(registry.KEYS), kind="stable").reset_index(drop=True)
    canonical_intervals = _interval_numbers(canonical.loc[:, list(registry.KEYS)])
    if "interval_number" not in canonical or not canonical["interval_number"].astype(int).reset_index(drop=True).equals(canonical_intervals):
        raise ContractError("ERR_CONFIDENCE_SUPPORT_KEYS", "interval_number differs from canonical interval_id")
    train_mask = canonical_intervals.isin(evaluation["training_intervals"])
    heldout_mask = canonical_intervals.isin(evaluation["heldout_intervals"])
    if not train_mask.any() or not heldout_mask.any() or (train_mask & heldout_mask).any():
        raise ContractError("ERR_CONFIDENCE_ROW_IDENTITY", "invalid governed evaluation partition")
    training_keys = canonical.loc[train_mask, list(registry.KEYS)].reset_index(drop=True)
    heldout_keys = canonical.loc[heldout_mask, list(registry.KEYS)].reset_index(drop=True)
    training_values = canonical.loc[train_mask, field].to_numpy(float)
    heldout_values = canonical.loc[heldout_mask, field].to_numpy(float)
    assigned = _stratify_confidence_values(training_values, heldout_values)
    cutoff = float(assigned["cutoff"])
    unique_training = int(assigned["training_unique"])
    training_equal = int(assigned["training_equal"])
    heldout_equal = int(assigned["heldout_equal"])
    lower = np.asarray(assigned["lower"], dtype=bool)
    upper = np.asarray(assigned["upper"], dtype=bool)
    labels = np.asarray(assigned["labels"], dtype=object)
    lower_count = int(np.count_nonzero(lower))
    upper_count = int(np.count_nonzero(upper))
    receipt = ConfidenceCutoffReceipt(
        analysis_id=analysis.analysis_id,
        analysis_family=analysis.family,
        outer_evaluation_identity=outer_evaluation_identity,
        model_families=authority.model_families,
        training_blocks=tuple(evaluation["training_blocks"]),
        training_intervals=tuple(evaluation["training_intervals"]),
        heldout_block=str(evaluation["heldout_block"]),
        heldout_intervals=tuple(evaluation["heldout_intervals"]),
        confidence_field=field,
        support_universe=str(expected["support_universe"]),
        governed_support_manifest=governed.manifest_path,
        governed_support_manifest_sha256=governed.manifest_sha256,
        governed_support_source_artifact=governed.artifact_path,
        governed_support_source_sha256=governed.artifact_sha256,
        governed_support_selector=governed.selector,
        governed_support_row_count=len(governed.keys),
        support_key_hash=governed.key_hash,
        training_governed_key_count=len(training_keys),
        training_governed_key_hash=confidence_support_key_hash(training_keys),
        heldout_governed_key_count=len(heldout_keys),
        heldout_governed_key_hash=confidence_support_key_hash(heldout_keys),
        training_row_count=len(training_keys),
        finite_training_count=len(training_values),
        finite_unique_training_count=unique_training,
        training_exact_equality_count=training_equal,
        heldout_row_count=len(heldout_keys),
        heldout_finite_count=len(heldout_values),
        lower_count=lower_count,
        upper_count=upper_count,
        heldout_exact_equality_count=heldout_equal,
        cutoff_statistic="MEDIAN",
        cutoff_value=cutoff,
        cutoff_source=str(authority.semantics["cutoff_source"]),
        training_scope="CURRENT_MODEL_TRAINING_HISTORY_ONLY",
        equality_convention=str(authority.semantics["equality_rule"]),
        lower_condition=str(authority.semantics["lower_condition"]),
        upper_condition=str(authority.semantics["upper_condition"]),
        lower_label=str(authority.semantics["lower_label"]),
        upper_label=str(authority.semantics["upper_label"]),
        predictor_use="PROHIBITED",
        weight_use="PROHIBITED",
        numeric_interpretation=str(authority.semantics["numeric_interpretation"]),
        training_status=(
            "TRAINING_CONFIDENCE_CONSTANT" if unique_training == 1
            else "TRAINING_CONFIDENCE_VARIABLE"
        ),
        lower_summary_status="READY" if lower_count else "NOT_DEFINED_NO_ROWS",
        upper_summary_status="READY" if upper_count else "NOT_DEFINED_NO_ROWS",
        row_order_policy="INPUT_ORDER_FREE_CANONICALIZE_BY_GOVERNED_KEYS",
        assignment_sha256=confidence_assignment_hash(heldout_keys, labels),
    )
    strata_index = pd.MultiIndex.from_frame(heldout_keys, names=registry.KEYS)
    return ConfidenceDispatchResult(
        receipt=receipt,
        strata=pd.Series(labels, index=strata_index, name="confidence_stratum"),
    )
