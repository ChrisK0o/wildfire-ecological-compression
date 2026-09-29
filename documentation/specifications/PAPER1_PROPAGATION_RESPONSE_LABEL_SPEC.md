# Paper 1 PR31 Response Label and Labeled-Table Specification

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
