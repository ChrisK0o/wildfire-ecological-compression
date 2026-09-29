"""True baseline-versus-analysis design construction for G05A.1."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import paper1_analysis_registry as registry
from src import paper1_pr34_modeling as model


@dataclass(frozen=True)
class ComparatorPair:
    comparator_type: str
    baseline_keys: pd.DataFrame
    augmented_keys: pd.DataFrame
    baseline: pd.DataFrame
    augmented: pd.DataFrame
    tie_rows: int = 0


def stable_hash(values) -> str:
    return hashlib.sha256("\n".join(map(str, values)).encode("utf-8")).hexdigest()


def _standard(frame: pd.DataFrame, family: str, role: str, train: pd.Index, extras=()) -> pd.DataFrame:
    return model.prepare_design(
        frame,
        model_family=family,
        model_role=role,
        extra_fields=tuple(extras),
        train_index=train if family == "logistic" else None,
    )[0]


def _dominant(frame: pd.DataFrame, family: str, train: pd.Index) -> tuple[pd.DataFrame, int]:
    raw_fields = [field for field in registry.BASELINE if field not in registry.FBFM]
    mapped, _, _ = model.structural_zero_canopy(frame.loc[:, raw_fields])
    fractions = frame.loc[:, list(registry.FBFM)].to_numpy(float)
    maximum = fractions.max(axis=1, keepdims=True)
    tie = (fractions == maximum).sum(axis=1) > 1
    levels = np.array(("GRASS_GRASS_SHRUB", "SHRUB", "TIMBER", "SLASH_BLOWDOWN", "NONBURNABLE"), dtype=object)
    labels = levels[np.argmax(fractions, axis=1)]
    labels[tie] = "TIE"
    if family == "logistic":
        numeric, _ = model.scale_logistic_numeric(mapped.drop(columns="hybrid_membership"), train)
        hybrid = pd.DataFrame(
            {f"hybrid_{level}": mapped.hybrid_membership.eq(level).astype(float) for level in model.HYBRID_LEVELS[1:]},
            index=frame.index,
        )
        dominant = pd.DataFrame(
            {f"dominant_fbfm_{level}": (labels == level).astype(float) for level in ("GRASS_GRASS_SHRUB", "SHRUB", "TIMBER", "SLASH_BLOWDOWN", "TIE")},
            index=frame.index,
        )
        return pd.concat((numeric, hybrid, dominant), axis=1), int(tie.sum())
    hybrid = pd.DataFrame(
        {f"hybrid_{level}": mapped.hybrid_membership.eq(level).astype(float) for level in model.HYBRID_LEVELS},
        index=frame.index,
    )
    codes = {"GRASS_GRASS_SHRUB": 0.0, "SHRUB": 1.0, "TIMBER": 2.0, "SLASH_BLOWDOWN": 3.0, "NONBURNABLE": 4.0, "TIE": 5.0}
    dominant = pd.DataFrame({"dominant_fbfm_code": [codes[label] for label in labels]}, index=frame.index)
    return pd.concat((mapped.drop(columns="hybrid_membership"), hybrid, dominant), axis=1), int(tie.sum())


def build_pair(
    analysis: registry.Analysis,
    frame: pd.DataFrame,
    family: str,
    train_intervals: tuple[int, ...] = (1, 3, 4, 5),
    realized_weather: pd.DataFrame | None = None,
    *,
    training_index: pd.Index | None = None,
) -> ComparatorPair:
    if not frame.index.is_unique:
        raise ValueError("duplicate authoritative row index")
    governed_keys = frame.loc[:, list(registry.KEYS)]
    if governed_keys.duplicated().any():
        raise ValueError("duplicate paired key")
    train = (
        frame.index[frame.interval_number.isin(train_intervals)]
        if training_index is None else pd.Index(training_index)
    )
    if not train.is_unique or not train.isin(frame.index).all():
        raise ValueError("invalid training row identity")
    if len(train) == 0:
        raise ValueError("empty training history")
    baseline = _standard(frame, family, "baseline", train)
    contract = registry.comparator_contract(analysis)
    kind = str(contract["comparator_type"])
    ties = 0
    if kind == "PRIMARY_EVT":
        augmented = _standard(frame, family, "baseline_plus_evt", train)
    elif kind == "AUGMENT_FIELDS":
        augmented = _standard(frame, family, "baseline", train, contract["augment_fields"])
    elif kind == "ALTERNATE_REPRESENTATION":
        augmented, ties = _dominant(frame, family, train)
    elif kind == "REPLACE_FIELDS":
        if realized_weather is None:
            raise ValueError("realized-weather replacement requires its frozen source")
        weather_fields = list(registry.REALIZED_WEATHER)
        weather = realized_weather.loc[:, list(registry.KEYS) + weather_fields]
        if weather.loc[:, list(registry.KEYS)].duplicated().any():
            raise ValueError("duplicate realized-weather key")
        frame_key_index = pd.MultiIndex.from_frame(governed_keys)
        weather_key_index = pd.MultiIndex.from_frame(weather.loc[:, list(registry.KEYS)])
        if len(weather) != len(frame) or set(weather_key_index) != set(frame_key_index):
            raise ValueError("realized-weather key coverage failure")
        aligned_weather = weather.set_index(list(registry.KEYS)).reindex(frame_key_index)
        aligned_weather.index = frame.index
        if aligned_weather[weather_fields].isna().any().any():
            raise ValueError("realized-weather key coverage failure")
        replaced = frame.copy()
        for realized in weather_fields:
            replaced[realized] = aligned_weather[realized]
        for forecast, realized in zip(registry.FORECAST_WEATHER, registry.REALIZED_WEATHER):
            replaced[forecast] = replaced[realized]
        augmented = _standard(replaced, family, "baseline", train).rename(columns=dict(zip(registry.FORECAST_WEATHER, registry.REALIZED_WEATHER)))
    else:
        raise ValueError(f"nonexecutable or unknown comparator type: {kind}")
    if not baseline.index.equals(frame.index) or not augmented.index.equals(frame.index):
        raise ValueError("design row identity mismatch")
    keys = governed_keys.copy()
    return ComparatorPair(kind, keys, keys.copy(), baseline, augmented, ties)


def validate_pair(pair: ComparatorPair, expected_type: str, allowed_difference: set[str]) -> None:
    if pair.comparator_type != expected_type:
        raise ValueError("comparator type mismatch")
    if (
        pair.baseline_keys.duplicated().any()
        or pair.augmented_keys.duplicated().any()
        or not pair.baseline_keys.equals(pair.augmented_keys)
        or not pair.baseline.index.equals(pair.augmented.index)
    ):
        raise ValueError("paired key/order mismatch")
    difference = set(pair.baseline.columns).symmetric_difference(pair.augmented.columns)
    if difference != allowed_difference:
        raise ValueError(f"governed schema difference mismatch: {sorted(difference)}")
    if pair.baseline.columns.equals(pair.augmented.columns) and expected_type != "UNIVERSE_ONLY":
        raise ValueError("baseline and augmented schemas are identical")


def validate_dominant_values(pair: ComparatorPair, frame: pd.DataFrame, family: str) -> None:
    fractions = frame.loc[:, list(registry.FBFM)].to_numpy(float)
    maximum = fractions.max(axis=1, keepdims=True)
    tie = (fractions == maximum).sum(axis=1) > 1
    levels = np.array(("GRASS_GRASS_SHRUB", "SHRUB", "TIMBER", "SLASH_BLOWDOWN", "NONBURNABLE"), dtype=object)
    labels = levels[np.argmax(fractions, axis=1)]
    labels[tie] = "TIE"
    if family == "logistic":
        if "dominant_fbfm_NONBURNABLE" in pair.augmented:
            raise ValueError("nonburnable must remain the dominant-FBFM logistic reference")
        for level in ("GRASS_GRASS_SHRUB", "SHRUB", "TIMBER", "SLASH_BLOWDOWN", "TIE"):
            expected = (labels == level).astype(float)
            if not np.array_equal(pair.augmented[f"dominant_fbfm_{level}"].to_numpy(), expected):
                raise ValueError("dominant-FBFM category/tie mismatch")
    else:
        codes = {"GRASS_GRASS_SHRUB": 0.0, "SHRUB": 1.0, "TIMBER": 2.0, "SLASH_BLOWDOWN": 3.0, "NONBURNABLE": 4.0, "TIE": 5.0}
        expected = np.asarray([codes[label] for label in labels], dtype=float)
        if not np.array_equal(pair.augmented["dominant_fbfm_code"].to_numpy(), expected):
            raise ValueError("dominant-FBFM RF code mismatch")
