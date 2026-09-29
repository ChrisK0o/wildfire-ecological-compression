# Paper 1 Canopy Nonapplicability Model Authority

## Decision

PR34A is `COMPLETE`. The bounded canopy representation conflict found by PR34 is resolved without changing any frozen predictor table, label, risk set, support mask, response rule, predictor family, validation architecture, or tuning authority. Model fitting remains unauthorized; PR34 may now be rerun.

## Scientific Meaning

`canopy_applicable_fraction` records the fraction of a response-grid cell for which the LANDFIRE canopy structural products are physically applicable. The four governed conditional fields describe canopy cover, canopy height, canopy base height, and canopy bulk density conditional on that applicable subarea. When applicability is zero, there is no applicable canopy subarea over which a conditional mean exists.

Accordingly, a source-table `NaN` in a governed conditional field paired with `canopy_applicable_fraction == 0` means **nonapplicable**, not unknown, unobserved, outside-domain, or source-NoData. This meaning is limited to these four fields under the exact applicability rule below.

## Locked Representation

At design-matrix construction, apply `STRUCTURAL_ZERO_FOR_NONAPPLICABLE_CANOPY`:

1. Preserve `canopy_applicable_fraction` as a model predictor.
2. For each governed conditional canopy field, map its value to numeric `0.0` if and only if `canopy_applicable_fraction == 0`.
3. Where `canopy_applicable_fraction > 0`, preserve the source conditional value exactly.
4. Do not modify or rewrite the source Parquet table.

The governed fields are:

- `conditional_mean_canopy_cover_pct`
- `conditional_mean_canopy_height_m`
- `conditional_mean_canopy_base_height_m`
- `conditional_mean_canopy_bulk_density_kg_m3`

The pair of `canopy_applicable_fraction` and each mapped conditional value distinguishes structural absence/nonapplicability from a physically applicable conditional zero. The mapping adds no predictor and creates no missingness indicator.

## Why This Is Not Statistical Imputation

The replacement is dictated entirely by a prespecified physical domain indicator and is independent of outcomes, folds, model performance, neighboring values, or estimated distributional quantities. It does not estimate an unknown value. It encodes the structural state "no applicable canopy" numerically while retaining the indicator that gives zero its meaning.

This authority does not permit converting other NoData, outside-domain, unknown, unobserved, or inapplicable values to zero. It is not a generic missing-value policy.

## Frozen-Artifact Audit

All eight frozen labeled predictor tables were audited: primary hybrid and the three locked alternate risk sets at both 1 km and 2 km. Across every table:

- applicability was finite and within `[0,1]`;
- all four conditional fields were `NaN` on every zero-applicability row;
- no finite structural value occurred on a zero-applicability row;
- all four fields were finite on every positive-applicability row;
- no mixed zero-applicability representation was found.

The paired PR24/PR32A support artifacts were also audited. The semantic source-table `NaN` state occurs on retained support rows and therefore must not cause row loss. The exact counts and immutable hashes are recorded in `PAPER1_CANOPY_NONAPPLICABILITY_QC.csv`.

## Fail-Closed Conditions

Execution must halt if:

- `canopy_applicable_fraction` is missing, nonfinite, below zero, or above one;
- any governed conditional value is missing or nonfinite where applicability is positive;
- any governed conditional value is finite and nonzero where applicability is zero;
- the mapping changes a conditional value where applicability is positive;
- a mapped design value is nonfinite;
- a frozen source-table or support-mask hash differs from its governed identity.

Zero applicability with finite zero conditional values is semantically compatible with this authority, but the current frozen artifacts do not use that source representation. Any future mixed representation must be reported explicitly and pass the same contradiction checks.

## Scaling and Validation

For logistic regression, perform the structural-zero mapping before training-history-only standardization. Fit means and population standard deviations (`ddof=0`) using every mapped row in the current training history, then apply those fitted parameters to the corresponding validation or test rows. Do not fit scaling parameters on canopy-applicable rows alone and do not replace structural values with the training mean. Random Forest receives the mapped raw numeric values without scaling. Existing F20 zero/nonfinite training-SD behavior remains unchanged.

The mapping is deterministic and identical across folds, resolutions, risk sets, and model families. It must never be learned or selected from held-out performance.

## Future Design Receipts

Each PR34 fit receipt must record, for every conditional canopy coordinate:

- the count of structurally zero-coded rows;
- `canopy_applicable_fraction == 0` as the source condition;
- confirmation that every positive-applicability value was unchanged;
- the logistic training-history mean and population SD after mapping;
- the final transformed feature order.

## Benchmarks and Claims

The training-prevalence and geometry-only benchmarks do not use these canopy fields and are unaffected. Baseline and augmented models must use the identical mapping on identical paired rows.

The coding is not evidence that a nonforest cell contains observed zero canopy structure, that the source measured zero, or that canopy absence causally affects spread. It is a deterministic predictive representation of structural nonapplicability.

## Authority Boundary

This correction changes model-time representation authority only. It does not authorize design-matrix construction, model fitting, performance analysis, row filtering, support rebuilding, predictor substitution, or modification of immutable artifacts. Historical PR33 and failed PR34 records remain unchanged as provenance.
