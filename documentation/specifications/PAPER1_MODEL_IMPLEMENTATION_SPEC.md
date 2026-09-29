# Paper 1 Model Implementation Specification

## PR34 Status

**PR34 MAY RESUME.** PR34A resolved the former canopy nonapplicability
ambiguity. PR34B then completed the response-free variance audit and replaced
the former unconditional zero-SD halt with the governed
`TRAINING_CONSTANT_FIXED_ZERO_COORDINATE` branch. The resumed PR34 blocker is
resolved without changing rows, support, predictor definitions, feature order,
FBFM40/EVT references, or Random Forest inputs.

No model was fit, no scientific design matrix was retained, no held-out
prediction was generated, and no scientific performance was calculated.

## Historical Blocking Input Condition

The 1 km immutable primary PR31 labeled table has 3,317
`PRIMARY_CONFIRMATORY` rows. On 946 rows,
`canopy_applicable_fraction` equals zero and each of these four governed
baseline fields is `NaN`:

- `conditional_mean_canopy_cover_pct`
- `conditional_mean_canopy_height_m`
- `conditional_mean_canopy_base_height_m`
- `conditional_mean_canopy_bulk_density_kg_m3`

Those fields are finite on all canopy-applicable rows. The primary support
nevertheless retains every row.

## Authority Conflict

The modeling whitelist includes the four conditional canopy means in the
24-field baseline. Preprocessing rule P10 and fail-closed rules F08/F20
require no primary imputation and halt on a missing or nonfinite model input.
The propagation support specification retains nonforest canopy structure as
valid information, while the scientific blueprint calls for explicit
nonforest coding. Neither current document specifies the model-time numeric
representation of the four conditional means when canopy is inapplicable.

Replacing these `NaN` values with zero, adding missingness indicators,
dropping the four conditional fields, or filtering the rows would each be a
new methodological choice. PR34 is not authorized to make one.

## Historical Required Correction

Before model implementation, current authority must explicitly select and
record one representation for nonapplicable canopy conditional means, define
whether it is semantic coding rather than imputation, and update the
whitelist/preprocessing/support rules consistently. The choice must preserve
the frozen candidate rows, labels, support masks, and response architecture.

The historical canopy conflict is preserved above as provenance. It was
resolved by committed PR34A authority and is no longer the active blocker.

## Resumed PR34 Input Condition

The frozen primary 1 km labeled table has these zero-SD results after the
required canopy structural-zero mapping and before logistic standardization:

- B1 (`1;3;4;5`): 563 rows; `fbfm_slash_blowdown_fraction` minimum `0.0`,
  maximum `0.0`, one unique value.
- B1+B2: 1,299 rows; the same coordinate remains exactly `0.0`.
- B1+B2+B3: 2,329 rows; the same coordinate remains exactly `0.0`.

This field is one of the four nonreference FBFM40 logistic composition
coordinates in the locked 24-field baseline. It is not a fixed hybrid schema
indicator. Existing F20 authority requires a halt; it does not authorize
feature removal, a substitute divisor, a different composition reference, or
another transformation.

## Historical Zero-SD Required Correction

This was resolved by PR34B. A finite continuous logistic coordinate with exact
training-history population SD zero remains in the fixed design schema and is
mapped to exactly zero for every row of that fit. Validation or held-out values
cannot activate it. Positive finite SD retains ordinary training-only scaling;
nonfinite input or SD remains fail-closed. Random Forest remains unscaled.

The complete audit covered 193 governed logistic fit-history schemas and 4,392
numeric coordinate-history cases. All 193 zero-SD cases were finite training
constants involving `fbfm_slash_blowdown_fraction` or, within its optional
support, `fdist_valid_fraction`; no nonfinite-SD case was found. The immutable
input and support hashes were unchanged. PR34B fit no model and inspected no
prediction or performance. Scientific model fitting remains outside PR34B and
may occur only when PR34 is explicitly resumed under the locked implementation.
