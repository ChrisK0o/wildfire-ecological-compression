# Paper 1 Scientific Blueprint

**Status:** Authoritative propagation-era Paper 1 methodology record

**Decision date:** 2026-08-11

**Study fire:** 2020 Brattain Fire, Oregon

**Primary architecture:** FEDS-centered dynamic propagation

**Modeling status:** Not authorized

## Authority and Study-Direction Lock

Paper 1 is locked to a single-fire, observational, noncausal study of dynamic propagation during the 2020 Brattain Fire. The primary analysis is pseudo-prospective and forecast-like, conditional on an already active fire, and based on repeated FEDS next-interval spread observations. This lock is supported by the Brattain FEDS validation gate, propagation experiment-design gate, event-65371 identity audit, and prospective-validation amendment.

This record supersedes the severity architecture below as current Paper 1 authority. The severity material is preserved as historical provenance and a validated fallback. It does not authorize severity modeling or override the propagation design.

## Core Scientific Question

> Among still-unburned landscape locations plausibly exposed to the active Brattain fire at each observed progression interval, does ecologically explicit pre-fire information add predictive information about where the fire spreads next beyond conventional fire-state, fuel, canopy, terrain, and meteorological information?

The estimand is incremental predictive information from explicit pre-fire ecology for conditional next-interval incorporation into the observed FEDS cumulative extent, among units in a risk set defined using information available at `t0`. It is not an ignition, annual-risk, causal, exact-front, or regional-susceptibility estimand.

## Response Source and Identity

The primary response source is FEDS Western-US v1.2.1, `fireID/fid=65371`. Its identity classification is `UNIQUELY_ASSOCIATED_BY_SPATIOTEMPORAL_MATCH`, not an official incident-name crosswalk.

Manuscript-safe wording is locked:

> FEDS event 65371 was associated with the Brattain Fire by reproducible spatial-temporal matching to authoritative incident records and independent EDW, WFDSS, and MTBS fire perimeters; the FEDS archive itself does not supply an incident-name crosswalk.

Required limitations are five unresolved northwestern outlier detections, unrecoverable pre-dissolve FEDS merge lineage, poor September 9 geometry agreement, retrospective FEDS postprocessing, and inference from one fire.

## Response Definition and Interpretation

For eligible landscape unit `i` and retained transition `t0 -> t1`:

- `Y_i,t = 1` when the unit is newly incorporated into the observed response extent by `t1`.
- `Y_i,t = 0` when the unit was an eligible, exposed, still-unburned unit at `t0` but is not incorporated by `t1`.

The nominal FEDS `00:00`/`12:00` timestamp is a synthetic AM/PM half-daily bin identifier, not an observation or availability time. Effective `t0` and the retrospective observation-based information cutoff are the latest VIIRS observation incorporated into the completed `t0` state. Effective `t1` is the latest incorporated VIIRS observation in the next completed state. The response is therefore incorporation by the **next completed FEDS observation state**, also described as the **next FEDS interval** or an **approximately 12-hour interval**. Across the 16 retained transitions, effective observation-time horizons are 9.7-14.0 hours with a median of 12.3 hours. Historical retrospective FEDS processing/publication latency remains unresolved.

The primary center rule and partial-cell diagnostics remain those prespecified by the propagation response audit. The response is conditional next-interval incorporation into observed FEDS cumulative extent. It is not ignition probability, annual wildfire risk, a causal spread probability, exact physical flame-front passage, or exact spotting occurrence.

## Response Support

- Primary response grid: **1 km**, scientifically locked in EPSG:9311.
- Required coarser response sensitivity: **2 km**.
- 500 m: not primary; retained only as a descriptive diagnostic because it implies unsupported precision.
- 30 m: prohibited as propagation response precision.

Underlying ecology, fuels, canopy, and terrain may remain available at 30 m, but they must be aggregated with scientifically prespecified rules to the response support. Fine predictor resolution never implies fine response resolution.

## Locked Intervals and Blocks

The primary retained interval IDs are exactly `1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22`.

- Block 1: `1, 3, 4, 5`.
- Block 2: `6, 8, 9, 10`.
- Block 3: `11, 12, 14, 15`.
- Block 4: `16, 18, 21, 22`.

The required no-early-phase sensitivity is `4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22`. Interval or block membership cannot change using model performance.

## Validation Architecture

**Primary evaluation: forward chaining.**

1. Train Block 1; test Block 2.
2. Train Blocks 1-2; test Block 3.
3. Train Blocks 1-3; test Block 4.

Block 1 is the initial within-fire calibration/training period, not a test period. Paper 1 does not predict Brattain from ignition.

The four symmetric leave-contiguous-block-out folds are a **secondary temporal-interpolation robustness analysis**. Leave-one-interval-out is an **additional influential-interval/dependence diagnostic**. Neither may be described as primary pseudo-prospective evidence.

## Historical Information Boundary and Weather

Every primary test at `t0` must use only:

- `STATIC_PREFIRE`: terrain, pre-fire fuels, canopy, and audited ecological variables;
- `T0_DYNAMIC`: the completed FEDS state/front and geometry/exposure quantities available at the effective `t0` observation cutoff;
- `FORECAST_DYNAMIC`: archived HRRRv3 forecasts whose initialization and complete required lead set were available by the effective `t0` observation cutoff.

For each retained interval, select the latest HRRRv3 initialization for which every required forecast object was demonstrably archived by the effective `t0` observation cutoff. Never use a later initialization or an object archived after cutoff. The locked interval-specific lead ranges are: `1 f01-f14`; `3 f01-f13`; `4 f01-f15`; `5 f02-f14`; `6 f01-f14`; `8 f02-f17`; `9 f02-f12`; `10 f01-f16`; `11 f02-f13`; `12 f01-f16`; `14 f01-f15`; `15 f02-f14`; `16 f01-f14`; `18 f02-f17`; `21 f01-f12`; `22 f01-f16`. Exact weather aggregation formulas are not locked. Forecast payload acquisition and value QC remain incomplete.

Retrospective realized interval weather is a distinct required sensitivity. It answers a different question and cannot be mixed with or called forecast information.

Forbidden information includes `t1` geometry, future FEDS detections or growth, future realized weather in the forecast-like primary analysis, final perimeter as candidate-negative support, eventual suppression geometry as known at `t0`, and future burned cells as firebrand sources.

## Risk Set

PR08 is **LOCKED**. On the fixed 1 km EPSG:9311 response lattice, include a cell center only when it is not covered by the completed `t0` cumulative FEDS hull and either is within 5,000 m of the completed `t0` active front or within 2,000 m of the completed `t0` cumulative-perimeter boundary. The completed state becomes usable only at its effective observation cutoff, defined by its latest incorporated VIIRS observation.

Eligibility must be frozen before loading `t1` geometry or constructing `Y`. The final perimeter, `t1` geometry, later detections, future weather, and future suppression cannot define eligibility or negatives. Required finite sensitivities are active-front-only 5 km, perimeter-only 2 km, and perimeter-only 5 km, plus the already locked response-grid, boundary, and no-early-phase sensitivities. Risk-set distances and anchors cannot be reselected from model scores.

## Statistical Unit and Dependence

Candidate cells are observation rows, not independent inferential units. The primary temporal inferential structure is the retained FEDS transition. There are at most 16 retained transitions and only three pseudo-prospective test blocks. Repeated cells, shared weather, overlapping risk sets, spatial neighborhood agreement, and temporal ordering prevent use of raster-row count as effective sample size.

## Metrics and Paired Comparison

Primary metrics are interval-level Brier score and interval-level log loss. Calibration-in-the-large and calibration slope are reported where estimable. PR-AUC and ROC-AUC are secondary and are calculated only when both classes are present.

Models must be compared with paired differences on identical held-out intervals, cutoffs, response support, risk sets, candidate rows, weather information, preprocessing, interval weights, and metric definitions. Each interval is reported before equal-weight aggregation. Pooled cell rows are not independent replicates.

## Dependence-Aware Uncertainty

Preserve interval-level reporting, chronological-block differences, and paired interval contrasts. The prespecified moving-block bootstrap uses 10,000 replicates, block length 2, and seed `20200908`, with block length 3 as a required sensitivity. Naive cell bootstrap, iid cell-level standard errors, iid p-values, and conventional significance testing added for appearance are prohibited.

## Baseline Information Classes

The conventional propagation baseline must be strong and must include scientifically justified representations of:

- current `t0` fire geometry and exposure;
- terrain;
- conventional surface fuels;
- conventional canopy fuels;
- `t0`-valid meteorological forecast information.

These are locked information classes, not final variables. Exact formulas, aggregation rules, temporal validity, redundancy, and support remain subject to the predictor adjudication and construction gates.

## Ecological Augmentation and Compression Hypothesis

The ecological predictor universe is not finalized. Candidate families include explicit vegetation type, cover, and height; invasive annual grass and cheatgrass; herbaceous productivity where scientifically valid; forest mortality and beetle-related disturbance; vegetation change and disturbance history; management and treatment history; biomass or density candidates; and other previously audited ecological sources.

No family is rejected merely because access is difficult, coverage is incomplete, or implementation is inconvenient. Each requires evidence-based temporal, ecological, coverage, uncertainty, redundancy, and support adjudication.

The scientific hypothesis is incremental information beyond ecological information already compressed into conventional fuel and canopy products. Paper 1 does not claim that existing fire models ignore ecology.

## Terrain Directionality

Candidate concepts include elevation, slope magnitude, terrain gradient/uphill direction, source-target elevation difference, candidate-direction alignment with the uphill vector, and wind-slope/source-target alignment. Exact scales and feature formulas remain `PENDING_AUDIT`; no excessive feature set is authorized.

## Suppression

Suppression is an unmeasured or partially observed dynamic confounder. Eventual suppression lines are prohibited as `t0` predictors because physical completion timing is unavailable. Recovered geometry may support prespecified retrospective sensitivity, intersection/context diagnostics, and interpretation. Missing line records do not establish no suppression.

## Firebrand Boundary

Physics-informed potential firebrand exposure is `EXPLORATORY / SECONDARY PENDING_AUDIT`, not part of the baseline. Sources must be active or reached by `t0`; source, transport, and receiver components remain separate; future burned cells cannot be sources. No exact spotting interpretation, kernel, or empirical coefficient is authorized before a dedicated primary-literature and parameter audit.

## Model-Family Direction

The primary direction is a low-complexity regularized logistic GAM/discrete-time hazard formulation. The exact choice among closely related GAM, logistic, and hazard implementations remains unresolved until predictor-table and implementation audits. Random Forest is the required nonlinear comparator on identical rows, folds, weights, and information sets. A geometry/prevalence null model is mandatory.

Broad adaptive hyperparameter searches are prohibited. Use strongly prespecified settings or a tiny chronology-respecting grid; four Block-1 temporal units cannot be replaced by a large candidate-row count.

## Claim Boundaries

Allowed only after successful future validation:

- incremental predictive information from explicit ecology;
- conditional next-interval prediction within Brattain;
- pseudo-prospective or forecast-like performance for later Brattain periods;
- robustness across prespecified response, risk-set, weather, and uncertainty sensitivities.

Forbidden claims include causal effects, prediction from ignition, unseen-fire or cross-fire generalization, operational forecasting, a real-time prediction system, exact spotting attribution, universal wildfire prediction, exact 30 m fire-edge prediction, regional susceptibility, and independent sample size equal to raster-row count.

## Severity and Final-Perimeter Status

The completed dNBR/RdNBR acquisition, QC, processed data, notebooks, and provenance are preserved as a **validated fallback / superseded primary architecture**. Burn severity was the working Paper 1 outcome during an earlier phase; propagation was later selected after dedicated feasibility, satellite-rescue, FEDS-validation, identity, and design gates. This historical decision sequence must remain visible.

The final-perimeter response is **marginal / not primary** because exposure opportunity and candidate-negative semantics are not defensible for the propagation claim. It must not be revived as the primary response.

## Advancement Gates

PR08 geometry and information-time semantics are locked. Predictor-table construction remains blocked until PR09 fire-state predictor formulas and missing-front behavior are locked, PR10 HRRR forecast payload/value QC and aggregation pass, candidate ecological families are formally adjudicated for propagation, temporal validity is confirmed, predictor aggregation rules are prespecified, and expected response-support/common-support consequences are measured.

Model fitting remains unauthorized until the accepted predictor universe and common support are fixed, the response/predictor table passes information-time and leakage checks, forward-chain boundaries are implemented and audited, the low-complexity model/tuning specification is locked, and all required sensitivities and receipts are reproducible.

## Current Authority Files

- Study direction, response, validation, claims: `documentation/PAPER1_SCIENTIFIC_BLUEPRINT.md`.
- Predictor candidate status: `documentation/PAPER1_PREDICTOR_ADJUDICATION.csv`.
- Data and advancement requirements: `documentation/PAPER1_DATA_REQUIREMENTS_AND_STATUS.csv`.
- Current FEDS information-time, PR08, and HRRR timing authority: `documentation/PAPER1_PROPAGATION_TIMING_AUTHORITY_RECONCILIATION.md`.
- Earlier reconciliation and historical-authority map: `documentation/PAPER1_PROPAGATION_AUTHORITY_RECONCILIATION.md`.

# Historical Severity Architecture - Validated Fallback, Superseded Primary

The material below is preserved verbatim as historical provenance from the severity phase. It is not current authority, does not override the propagation sections above, and does not authorize modeling.

## Authority and Fire Lock

This blueprint acts on the final fire-selection evidence gate's recommendation: **RECOMMEND BRATTAIN**. Paper 1 is locked to the 2020 Brattain Fire in Oregon. Silverado was scientifically feasible but was not selected. It remains available for later multi-fire or held-out-fire generalization work. The selection follows the comparative evidence on response validity, spatial-validation viability, baseline feasibility, ecological information, support, novelty, and reproducibility; it is not based on personal motivation.

The Brattain-versus-Silverado question is closed. It may be reopened only if a fatal data-integrity error invalidates the evidence gate. The three fire-selection gate records and all Silverado evidence remain historical evidence and must not be rewritten to imply that Silverado was infeasible.

This blueprint supersedes the scientific authorization of the reduced nine-predictor/four-model design in Notebooks 23-32. Those notebooks and their documentation remain preserved as reproducible historical work, but they are conditional and cannot authorize fitting. Notebook 33 must not be recreated or run until a new post-blueprint implementation gate is passed.

## Central Scientific Question

### Technical Question

Within valid locations inside the final mapped 2020 Brattain Fire perimeter, conditional on the realized fire event, how much spatially out-of-sample predictive information about continuous MTBS dNBR is added by more disaggregated LF2016 vegetation type, cover, and height/structure beyond a strong conventional LANDFIRE/fire-model-style representation of terrain, surface fuel, canopy/fuel structure, climate, and antecedent atmospheric demand; and, within the separately defined mapped-rangeland domain, how much additional information is provided by explicit 2019 exotic annual grass abundance?

### Plain-English Question

When standard fuel and landscape products summarize vegetation into fuel classes and canopy attributes, does retaining more disaggregated vegetation type, cover, and height information improve predictions of where the Brattain Fire burned more or less severely, including a separate test of exotic annual grass only where that product is actually defined?

### Hypotheses

**Primary hypothesis.** On identical whole-fire rows and geographically separated tests, adding LF2016 EVT, EVC, and EVH vegetation type, cover, and height/structure information to M0 reduces held-out dNBR prediction error.

**Null hypothesis.** Once M0 is supplied, adding LF2016 EVT, EVC, and EVH does not reduce geographically held-out dNBR prediction error; any apparent gain is compatible with fold heterogeneity, spatial dependence, derivational overlap, redundancy, or tuning variation.

The EAG-domain contrast is a separate prespecified hypothesis. It does not alter the whole-fire primary hypothesis or estimand.

## Estimand, Responses, and Interpretation

The estimand is spatial variation in remotely sensed realized burn severity among valid pixels within the final Brattain perimeter, conditional on those locations having been reached and mapped by the realized fire. The primary response is supplied MTBS continuous dNBR. Supplied MTBS continuous RdNBR is a required normalized response sensitivity. Supplied MTBS six-class dNBR6 is secondary and descriptive.

The design permits retrospective predictive statements conditional on the Brattain event and the observed product domains. It does not estimate ignition probability, why the final perimeter formed, complete fire spread, suppression effects, causal vegetation effects, landscape probability of burning, universal wildfire susceptibility, or regional generalization.

## Two Levels of Inference

### Whole-Fire Primary Experiment

The primary experiment uses predictors whose states are scientifically defined over the accepted whole-fire modeling support. It compares a strong conventional LANDFIRE/fire-model-style representation with that same representation plus more disaggregated LF2016 vegetation type, cover, and height/structure information. All compared whole-fire information sets use the same final common-support rows, response-side edge rule, folds, buffers, tuning protocol, and metrics.

"Whole-fire" refers to the eligible final common support inside the perimeter, not every geometric pixel regardless of masks. Any source exclusions must be documented before fitting and applied identically to the compared information sets.

### Domain-Specific Ecological Experiments

A domain-specific predictor is analyzed only where its measurement semantics are valid. It never defines the whole-fire primary support. Masked values are not converted to zero, and results are conditional on that ecological/product domain.

The primary domain-specific experiment is legacy 2019 overall EAG. Valid EAG coverage is 33.8273% of complete response support and 32.4001% of the prior 200,064-cell common support. EAG therefore cannot be called a whole-fire predictor or used to redefine the primary estimand.

## LANDFIRE Temporal-Safety Decision

Authoritative LANDFIRE naming, LF2016 Remap release, version-comparison, closeout, and product metadata resolve the phrase "2020 capable fuels." LF2016 Remap is a circa-2016 base landscape. It includes mapped disturbances through 2016. Fuel-transition rules then project those known pre-existing conditions to an effective 2020 fuel state. "2020 capable" describes the rule-based effective year; it does not mean that 2017-2020 disturbances were ingested.

This differs from LF2020 version 2.2.0, which incorporates 2017-2020 disturbances and is not authorized for the Brattain pre-fire design. The LF2016 Remap Northwest products were released during 2019 and the CONUS suite in 2020; release date is separate from landscape/source-observation year. No LF2016 lineage evidence indicates that the September 2020 Brattain Fire or any post-2016 disturbance was used.

| Product | Source-observation / disturbance lineage | Effective landscape meaning | Release timing | Decision |
|---|---|---|---|---|
| FBFM40 | LF2016 base; disturbances through 2016 | Rule-transitioned expected 2020 fuel model | LF2016 Remap release cycle, before/within 2020 | **PREFIRE SAFE WITH EXPLICIT CAVEAT** |
| CC | LF2016 base; disturbances through 2016 | Modeled 2020-capable canopy cover | LF2016 Remap release cycle | **PREFIRE SAFE WITH EXPLICIT CAVEAT** |
| CH | LF2016 base; disturbances through 2016 | Modeled 2020-capable canopy height | LF2016 Remap release cycle | **PREFIRE SAFE WITH EXPLICIT CAVEAT** |
| CBH | LF2016 base; disturbances through 2016 | Modeled 2020-capable canopy base height | LF2016 Remap release cycle | **PREFIRE SAFE WITH EXPLICIT CAVEAT** |
| CBD | LF2016 base; disturbances through 2016 | Modeled 2020-capable canopy bulk density | LF2016 Remap release cycle | **PREFIRE SAFE WITH EXPLICIT CAVEAT** |

The caveat is substantive: these are modeled expected 2020 conditions based on observations and disturbances no later than 2016, not observed September 2020 field conditions. Their use is retrospective and pre-fire safe, but temporal staleness and model-transition uncertainty must be reported. The current Brattain LFPS bundle is authoritative and no replacement acquisition is required.

Primary source records include <https://www.landfire.gov/LFNameConvention>, <https://landfire.gov/data/lf2016>, the LF2016 Remap closeout report, and the saved product XML under `data/raw/landfire/final_fire_selection_gate/`.

## Final Predictor Universe

The row-level adjudication is authoritative in `documentation/PAPER1_PREDICTOR_ADJUDICATION.csv`. The design uses the following scientific roles.

### Strong Conventional Baseline

- Terrain: elevation, slope, northness, eastness.
- Surface fuel: categorical LF2016 FBFM40, including valid nonburnable states.
- Canopy/fuel structure: LF2016 CC, CH, CBH, and CBD, plus one shared forest-canopy-applicability indicator. Documented zero means nonforest/nonapplicable, not missing. These variables remain defined over the whole-fire support and must not force a forest-only analysis.
- Climate: Daymet 1981-2019 mean annual precipitation and pre-ignition 90-day precipitation.
- Atmospheric demand: pre-ignition 90-day mean daily VPD derived from Daymet tmax, tmin, and vp after acquisition and QC.

The VPD window is 2020-06-10 through 2020-09-07 inclusive. The formula follows Allen et al.'s FAO Irrigation and Drainage Paper 56 method: daily saturation vapor pressure is the mean of `0.6108 * exp(17.27*T/(T+237.3))` evaluated at daily tmax and tmin, in kPa. Daymet documentation defines tmax and tmin in degrees C, `vp` in Pa, and `vp` as daily average water vapor pressure on an approximately 1 km native grid. Daymet `vp` is converted from Pa to kPa. Daily VPD is `max(mean_es - vp/1000, 0)`; missing source values remain missing. The predictor is the mean over the fixed 90-day window. Formula, unit, negative-value rule, date count, and native-cell support must pass a separate derivation gate. The equation is locked before model fitting and cannot be changed using model performance.

Brattain 30-day precipitation remains rejected because it is constant zero. It must not be reintroduced or replaced after viewing response performance.

### Primary Explicit Vegetation Augmentation

LF2016 EVT, EVC, and EVH are not placed in the conventional baseline. FBFM40 is assigned using combinations of EVT, EVC, EVH, and other information, and the canopy products also have derivational overlap with those vegetation products. M1 intentionally compares that compressed conventional representation with the same representation plus more disaggregated LF2016 vegetation type, cover, and height/structure information. It does not test statistically independent ecological measurements, direct near-ignition physiological vegetation condition, or whether operational fire models generally ignore ecology.

The known derivational overlap is intentional to the compression-information question, not permission to ignore redundancy. Before fitting, report pairwise associations, grouped associations, diagnostics suitable for mixed categorical/continuous data, fold-specific category support, and support attrition. During evaluation, compare identical rows and use grouped held-out permutation importance and family ablation; do not select variables from outer-test performance. Improvement would mean that the explicit LF2016 representation retains predictive information not fully retained in this defined compressed baseline.

## ECOSTRESS Final Decision

Saved CMR metadata identifies 46 Version-2 ESI candidates within 90 days, 29 within 60 days, and 17 within 30 days before 2020-09-08. The prespecified biological windows were not selected using dNBR.

The smallest authenticated audit targeted the latest Brattain candidate, `ECOv002_L4T_ESI_ALEXI_12215_008_10TFN_20200831T165139_0712_01`. Its exact official LP DAAC URL returned an HTTP 303 signed-cloud redirect and then HTTP 401 when accessed without Earthdata authorization. No `.netrc`, Earthdata credential environment variable, or usable authenticated session was available. No raster byte was retained.

Consequently, actual quality-filtered ESI/uncertainty values, clear-sky support, native observed units, fragmentation, composite feasibility, and support cost cannot be verified reproducibly under the available authenticated-access setup. The final Paper 1 classification is **UNUSABLE FOR PAPER 1**, operationalized as **REJECT** in the adjudication table. This is an access-and-verifiability decision, not evidence that ECOSTRESS or physiological stress is scientifically irrelevant. Metadata counts may be mentioned as context, but ECOSTRESS is not a predictor or required future acquisition.

## EAG Adjudication

Release date and information time are separate. A retrospective study may use a product published after ignition when the historical predictor's information content is strictly pre-ignition. It may not claim contemporaneous operational availability unless that is documented. Algorithm training inputs, covariates, and source observations are audited separately from archive publication.

### Primary Lineage

The legacy USGS `P9XT1BV2` 2019 overall EAG estimate is **DOMAIN-SPECIFIC PRIMARY**. It uses 2016-2019 observations and training plots; no post-2019 observation was identified. Later archive publication does not itself cause leakage. The product has 78,301 valid response cells, 56 values from 0-56, and quantitative model-dispersion confidence. Value 255 is a mask, never zero.

The exact primary domain is: cells inside the locked Brattain response-side edge mask that are valid under the final accepted whole-fire predictor support and valid (`!=255`) in legacy 2019 overall EAG. On the prior 200,064-cell support this is 64,821 cells. The final count must be recomputed after the expanded baseline/VPD common-support gate; it must not be assumed unchanged.

Legacy confidence is quality context: lower dispersion is better. The primary domain retains all valid legacy cells. Confidence thresholds are not selected from burn-severity performance. Prespecified confidence-stratified diagnostics may report the already audited `<=1`, `<=2`, `<=3`, and `<=5` dispersion strata without redefining the confirmatory domain.

### Retrospective Sensitivities

Version 5 overall EAG and Version 5 cheatgrass are **DOMAIN-SPECIFIC SENSITIVITY** only. Their 2019 observations are historical, but the documented feature set includes a 1989-2023 climate normal, which introduces post-ignition information into the retrospective estimator. Version 5 therefore cannot support the strict primary pre-fire lineage. Its 2025 release date is not the rejection reason.

Version 5 masked value 255 remains missing/out-of-domain. Overall EAG and cheatgrass are evaluated separately on identical Version-5 valid rows; neither is automatically stacked with legacy EAG. Version-5 confidence is higher-is-better quality context, not a predictor.

## EAG-Domain Spatial-Validation Audit

The geometry-only audit used the validated legacy-EAG mask intersected with the existing 200,064-cell support. It did not fit a model or use dNBR to choose folds. Nearest-neighbor alignment reproduced exactly 64,821 cells (58.3389 km2), 536 eight-neighbor connected components, and a largest-component share of 27.3692%. Equal-count principal-axis slabs were formed from coordinates. For each outer split, new inner principal-axis folds were constructed only from the buffered outer-training region.

Operational status uses the final fire-selection gate rule: train and validation sets are nonempty; buffered training is at least as large as validation; and at least 50% of unbuffered training is retained. Distances are cell-center distances strictly greater than the nominal buffer.

| Folds | Buffer (m) | Outer operational | Fully nested operational | Minimum outer train | Minimum outer retained | Minimum inner train | Minimum inner retained | Minimum separation (m) | Maximum outer/inner components | Classification |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 4 | 300 | 4/4 | 4/4 | 46,241 | 95.11% | 29,382 | 94.59% | 301.50 | 456 / 362 | Robust |
| 4 | 600 | 4/4 | 4/4 | 43,540 | 89.56% | 26,080 | 88.05% | 600.75 | 456 / 343 | Robust |
| 4 | 900 | 4/4 | 4/4 | 40,942 | 84.22% | 22,868 | 82.00% | 900.50 | 455 / 317 | Robust |
| 4 | 1,200 | 4/4 | 4/4 | 39,089 | 80.40% | 20,488 | 76.39% | 1,200.37 | 457 / 287 | Robust |
| 4 | 1,500 | 4/4 | 4/4 | 37,246 | 76.61% | 17,752 | 69.72% | 1,500.30 | 452 / 266 | Robust |
| 4 | 2,100 | 4/4 | 4/4 | 34,234 | 70.42% | 12,779 | 54.44% | 2,100.21 | 448 / 238 | Robust |
| 5 | 300 | 5/5 | 5/5 | 49,419 | 95.30% | 35,155 | 92.28% | 301.50 | 475 / 390 | Robust |
| 5 | 600 | 5/5 | 5/5 | 47,186 | 90.99% | 31,271 | 83.55% | 600.75 | 472 / 388 | Robust |
| 5 | 900 | 5/5 | 5/5 | 44,457 | 85.73% | 27,781 | 75.46% | 900.50 | 472 / 384 | Robust |
| 5 | 1,200 | 5/5 | 5/5 | 42,128 | 81.24% | 24,515 | 67.44% | 1,200.37 | 471 / 388 | Robust |
| 5 | 1,500 | 5/5 | 5/5 | 39,909 | 76.96% | 21,392 | 59.55% | 1,500.30 | 465 / 378 | Robust |
| 5 | 2,100 | 5/5 | 4/5 | 36,171 | 69.75% | 16,542 | 48.18% | 2,100.21 | 455 / 367 | Material limitation |
| 6 | 300 | 6/6 | 6/6 | 51,839 | 95.97% | 39,462 | 93.72% | 301.50 | 499 / 449 | Robust |
| 6 | 600 | 6/6 | 6/6 | 49,447 | 91.54% | 35,994 | 87.84% | 600.75 | 496 / 430 | Robust |
| 6 | 900 | 6/6 | 6/6 | 47,268 | 87.50% | 32,152 | 80.56% | 900.50 | 485 / 407 | Robust |
| 6 | 1,200 | 6/6 | 6/6 | 45,802 | 84.79% | 27,519 | 71.07% | 1,200.37 | 480 / 392 | Robust |
| 6 | 1,500 | 6/6 | 6/6 | 43,905 | 81.28% | 24,189 | 64.20% | 1,500.30 | 470 / 390 | Robust |
| 6 | 2,100 | 6/6 | 6/6 | 39,558 | 73.23% | 19,581 | 54.65% | 2,100.21 | 456 / 391 | Robust |

For the selected five-fold, 1,500 m design, outer validation folds contain 12,964-12,965 cells; buffered outer training contains 39,909-47,896 cells. Inner validation folds contain 9,977-11,974 cells and buffered inner training contains 21,392-33,099 cells.

**Final classification: ROBUSTLY VIABLE.** The primary EAG-domain design is five outer folds with a 1,500 m buffer. Required geometry sensitivities are four and six folds at 1,500 m, and five folds at 1,200 m. The five-fold 2,100 m result is reported as a boundary stress test with a material limitation because only four of five outer iterations are fully nested-operational. The fragmented ecological domain is a required limitation even though the splits are operational.

## Disturbance Memory

Strictly pre-ignition MTBS history intersects 46,329 of 231,473 response cells (20.0149%). The five intersecting records include four wildfires and one event typed Other. Counts are only zero or one, so event count adds no information beyond an indicator.

Disturbance memory is **WHOLE-FIRE SENSITIVITY**. Its representation is two-part:

1. `known_prior_mtbs_event`: one where a qualifying prior MTBS perimeter maps the cell; zero means only "no prior MTBS event mapped."
2. `years_since_prior_mapped_mtbs`: defined only where the indicator is one, using the latest qualifying ignition date; unmapped cells remain structurally not observed, not assigned a biological age.

Models requiring complete numeric matrices must use a training-isolated missingness representation that preserves the indicator and does not imply age zero. The prior-event count is rejected. This sensitivity does not enter the confirmatory M0/M1 contrast.

## ADS and Tree Health

The authoritative USDA Forest Service IDS service exposes only damage points and damage polygons. Its layer metadata and survey handbook describe detection-level aerial sketch mapping, not a census. The service has no survey-footprint layer, while a Brattain through-2019 query returns zero intersecting damage records. Thus surveyed with no damage cannot be distinguished from not surveyed.

ADS/tree health is **REJECT** for Paper 1 modeling. Zero records must not be encoded as no damage. The historical original-study statement that a Region 6 ADS source was used remains part of the original-study record, but no reproducible source supporting that predictor has been established for the redesigned analysis.

## Direct Vertical Structure and Ladder Fuels

Canopy height, canopy base height, and canopy bulk density are modeled canopy/fuel attributes; none is relabeled as a direct ladder-fuel observation. GEDI L2A provides sparse approximately 25 m footprints from 2019 onward, not wall-to-wall vertical continuity. No date-filtered Brattain footprint audit or local pre-fire lidar source establishes coverage adequate for the geographically separated whole-fire or EAG-domain experiments.

Direct ladder fuels/GEDI are **REJECT**. They may motivate interpretation of the modeled canopy limitations, but no sparse-footprint domain is created merely to retain an appealing variable.

## Soil Moisture, Nutrients, Chemicals, and Management

| Family | Final status | Scientific reason |
|---|---|---|
| SMAP soil moisture | **CONTEXT ONLY** | Daily 9 km support supplies too few native observations for 30 m within-fire inference; no downscaling is authorized. |
| Atmospheric nitrogen deposition | **CONTEXT ONLY** | EPA/NADP TDep is approximately 4 km measurement-model fusion and is regional context, not pixel-level evidence. |
| Direct fertilizer | **REJECT** | No authoritative pre-2020 spatial source with meaningful within-fire resolution was established. |
| Pesticide/herbicide | **REJECT** | Proposed action is not executed treatment; county summaries cannot become pixels; no Brattain-wide pre-fire geometry exists. |
| Vegetation-management history | **CONTEXT ONLY** | Incomplete records may inform limitations but cannot establish treated/untreated states. |
| Fuel-treatment history | **CONTEXT ONLY** | No complete authoritative pre-fire dates and footprints exist; no mapped treatment is not proven absence. |
| Roads/barriers | **REJECT** | No audited representation exists and the mechanism risks mixing suppression/access with the conditional severity estimand. |
| Biomass/density | **REJECT** | No independent validated product exists beyond accepted canopy/EVC/EVH proxies. |

Broad discovery for these families is closed for Paper 1.

## Final Information-Set Architecture

### Confirmatory Whole-Fire Comparison

Only two confirmatory information sets are scientifically necessary. Additional sets are not retained for historical symmetry.

**M0 - Strong conventional baseline**

- elevation, slope, northness, eastness;
- categorical LF2016 FBFM40;
- LF2016 CC, CH, CBH, CBD and a shared documented canopy-applicability indicator;
- Daymet mean annual precipitation for 1981-2019;
- Daymet 90-day pre-ignition precipitation;
- Daymet 90-day mean pre-ignition VPD.

**M1 - Explicit vegetation information**

- M0;
- LF2016 EVT using the locked official subclass hierarchy and fold-safe unseen-category handling;
- physically decoded LF2016 EVC;
- physically decoded LF2016 EVH.

M0 and M1 are trained and evaluated on exactly the same accepted whole-fire rows. M0 is not allowed to use more rows simply because it omits EVC/EVH. The primary scientific contrast is paired outer-fold performance of M1 minus M0. The canopy variables are interpreted as one correlated baseline family; EVT/EVC/EVH are interpreted as one explicit ecological family.

There is no confirmatory M2 or M3. The only accepted additional whole-fire ecology/history candidate is incomplete MTBS disturbance memory, whose ascertainment makes it a sensitivity rather than a clean next information tier. A separately labeled **H sensitivity** refits M0 and M1 with the two-part MTBS history representation; it cannot replace or be pooled with the primary contrast.

### EAG-Domain Comparison

All domain models are refit and evaluated on the same rows within each lineage-specific domain. Whole-fire M0 error is never compared directly with domain D2 error.

**D0 - Domain baseline:** M0 restricted to the final legacy-EAG valid domain.

**D1 - Domain explicit vegetation:** D0 plus EVT, EVC, and EVH.

**D2 - Overall EAG:** D1 plus legacy 2019 overall EAG percent cover.

The primary EAG contrast is paired outer-fold D2 minus D1, with D0-to-D1 retained to show whether explicit vegetation adds information inside the same rangeland domain.

**D3 sensitivities** are separate, not cumulative: Version-5 overall EAG and Version-5 cheatgrass are each added to the corresponding Version-5-domain D1. Their retrospective-input caveat is printed in every result. Legacy confidence strata and Version-5 confidence strata are quality sensitivities, not additional predictors. D3 results cannot support the strict pre-fire primary claim.

## Validation Architecture

Validation geometry is chosen from coordinate/support evidence, never predictive performance.

### Whole-Fire Primary Geometry

- Resolution: 30 m computational grid, with native information support retained in interpretation.
- Outer geometry: five deterministic equal-count principal-axis spatial slabs.
- Primary buffer: 2,100 m between outer validation cells and retained outer-training cells. Brattain was fully nested-operational at this distance for 4, 5, and 6 folds in the final gate.
- Inner geometry: for each outer iteration, construct four new principal-axis inner folds using only that iteration's already buffered outer-training region. Apply the same 2,100 m inner train/validation buffer.
- Required buffer sensitivities: 1,200 m and 1,500 m using five folds.
- Required fold-count sensitivity: four and six folds at 2,100 m.
- Optional boundary stress test: 3,000 m only as a clearly incomplete geometry diagnostic; it cannot replace the complete primary design.

### EAG-Domain Geometry

- Primary: five outer folds, 1,500 m outer and inner buffers.
- Required sensitivities: four and six folds at 1,500 m; five folds at 1,200 m.
- Stress test: five folds at 2,100 m, explicitly marked as 4/5 fully nested-operational.
- Inner folds are rebuilt only from each buffered outer-training domain.

### Resolution Sensitivity

Thirty meters is the primary response/computational resolution, not a claim that all predictors supply independent 30 m information. A required 300 m sensitivity must be built from source-aware aggregation before fitting. Continuous responses and continuous predictors use documented valid-cell aggregation such as a mean, with the exact rule locked before fitting; categorical variables use a scientifically appropriate modal or fractional representation specified before fitting; northness/eastness are aggregated as components, never raw aspect angles. Physical spatial folds and buffers are rebuilt on the 300 m analysis support. Native approximately 1 km Daymet information remains interpreted at native support and is not treated as independent 300 m measurements.

### Nesting and Isolation Rules

- Outer test regions are untouched until final evaluation for that outer iteration.
- Hyperparameter tuning, category pooling, unknown-category rules, scaling, encoding, variable screening, and any data-dependent preprocessing occur inside inner training only.
- Feature or family selection may not use outer-test results.
- Each information set is tuned independently within the same nested geometry; tuning choices do not cross outer folds.
- RdNBR repeats the complete workflow with independent inner tuning on identical support and geometry.
- Random pixel cross-validation, random 80/20 splitting, zero-meter separation, tuning on outer folds, and post hoc buffer selection are prohibited.

## Model Families and Evaluation

### Required Models

**Primary learner:** Random Forest regression. It is retained because it handles nonlinearities, interactions, mixed predictors, and the established scientific protocol. It is not treated as the only valid learner or as an interpretability engine.

**Required interpretable comparator:** a generalized additive model or equivalent regularized additive model. Continuous predictors use penalized smooths with complexity selected inside inner training. Categorical FBFM40/EVT representations use penalized factors or prespecified groupings with training-only unseen-level handling. The comparator uses the same rows, folds, buffers, responses, and metrics as Random Forest. It tests whether gains require complex interactions/nonadditivity.

**Conditional robustness model:** gradient boosting may be added only if computation permits after the required analyses pass. It uses the same nested isolation and is reported as robustness, not a performance tournament. Its inclusion or omission cannot depend on which method wins preliminary tests.

**Simple benchmark:** the outer-training mean dNBR predictor is required in every outer fold. A regularized linear/additive baseline may be reported alongside the GAM but cannot replace the mean benchmark.

### Metrics and Contrasts

- Primary metric: outer-held-out RMSE, aggregated from pooled out-of-fold predictions and also reported by fold.
- Secondary metrics: MAE, median absolute error, out-of-fold R2 relative to the outer-training-mean benchmark, Spearman correlation, Pearson correlation, calibration intercept/slope, and error across observed-severity quantiles.
- Primary model comparison: paired fold-wise and pooled out-of-fold delta RMSE and percent delta RMSE for M1 versus M0; D2 versus D1 for the EAG domain.
- Robustness description: report the direction and magnitude of error change, spatial distribution of improvement, fold-specific paired contrasts, prespecified buffer and fold-count sensitivities, RdNBR response sensitivity, 300 m resolution sensitivity, and the additive comparator. No post hoc binary significance, success, stability, or minimum-effect threshold is created.

### Interpretation and Diagnostics

- Grouped held-out permutation importance is calculated on each outer test set for terrain, surface fuel, canopy/fuel structure, climate/demand, explicit vegetation, EAG, and disturbance sensitivity. Correlated member variables are not interpreted from single-variable impurity importance.
- Prespecified family ablations are evaluated with full nested retuning when used for scientific claims.
- Residual spatial dependence is reported within outer-test predictions using a prespecified distance-binned semivariogram/correlogram and Moran-type statistic on the test geometry. Remaining dependence limits effective information and uncertainty claims.
- Report fold-specific sample counts, native Daymet-cell counts, response distributions, category coverage, support components, and model performance.
- Uncertainty is represented by spatial-fold heterogeneity, paired fold contrasts, and appropriately blocked resampling if implemented. Pixel count is not treated as independent sample size and five folds are not used to claim asymptotic certainty.
- Save one out-of-fold prediction and residual map per required model/information set/response. Maps show held-out predictions only and distinguish support/domain exclusions.
- Report hyperparameter selections and stability across outer iterations. Final full-data refits, if later authorized, are descriptive deployment artifacts and never replace nested out-of-fold evidence.

## Claims and Novelty

### Permitted Contribution

Paper 1 evaluates whether a defined conventional LANDFIRE/fire-model-style representation loses useful predictive information when LF2016 vegetation type, cover, and height/structure are represented more disaggregately, using geographically separated within-fire validation for the 2020 Brattain Fire. It does not claim that operational fire models generally ignore ecology or that EVT/EVC/EVH are statistically independent ecological measurements. It also provides a prespecified rangeland-domain test of pre-fire overall EAG abundance without treating masked land as zero or extrapolating the result to the whole fire.

Permitted claims are conditional on the Brattain event, accepted common support, product lineages, spatial-validation geometry, and retrospective analysis. The study may state whether the more disaggregated LF2016 vegetation representation reduced held-out error beyond the defined baseline and describe its direction and magnitude across the required robustness analyses.

### Prohibited Claims

Paper 1 must not claim:

- first-ever wildfire machine learning or vegetation-fire analysis;
- that conventional fire models ignore ecology;
- causal vegetation effects or counterfactual severity changes;
- ignition, spread, suppression, or landscape burn-probability prediction;
- independent 30 m information from approximately 1 km Daymet inputs;
- whole-fire EAG effects or zero EAG outside its mapped domain;
- species-specific cheatgrass evidence from the legacy overall-EAG product;
- prospective operational availability for products not available at ignition;
- universal, western-US, or held-out-fire generalization;
- field-validated comprehensive ecological severity from spectral dNBR.

Whole-fire inference and EAG-domain inference are presented separately. All predictions are retrospective. Prospective operational prediction would require a separate availability audit and is not demonstrated here.

## Advancement Gates and Exact Remaining Work

The machine-readable requirements are in `documentation/PAPER1_DATA_REQUIREMENTS_AND_STATUS.csv`. Final modeling remains unauthorized. The next scientific sequence is:

1. Acquire authoritative Daymet V4 R1 2020 daily `tmax`, `tmin`, and `vp` products needed for the fixed 90-day VPD metric; preserve request metadata, hashes, dates, units, and native grid.
2. Derive and QC 90-day mean VPD without viewing model performance.
3. Decode and integrate the existing temporally safe LF2016 FBFM40/CC/CH/CBH/CBD Brattain bundle with explicit nonforest applicability semantics.
4. Build a new versioned expanded predictor stack and common-support table using the accepted baseline plus EVT/EVC/EVH. Preserve, rather than overwrite, the protected old canonical table.
5. Create the legacy-EAG domain mask from the final expanded common support; integrate legacy overall EAG/confidence and separately integrate Version-5 sensitivity domains.
6. Derive the two-part MTBS disturbance-memory sensitivity.
7. Persist and independently QC the specified whole-fire and EAG-domain nested fold/buffer geometries.
8. Build and QC the 300 m source-aware resolution-sensitivity table.
9. Write a new post-blueprint model/evaluation specification for Random Forest, the required additive comparator, metrics, diagnostics, receipts, and resumability.

No further ECOSTRESS, ADS, GEDI, SMAP, nitrogen, chemical, treatment, road, or biomass acquisition is required for Paper 1.

## Reproducibility and Integrity Constraints

- Do not modify Notebooks 01-32 to retrofit this decision. Addenda or replacements require a separate authorized task.
- Do not reuse the old reduced canonical table for final fitting or overwrite it during the expanded rebuild.
- Do not revive interrupted Notebook-33 results.
- Preserve raw MTBS, LANDFIRE, EAG, Daymet, terrain, and Silverado artifacts.
- Preserve the final fire-selection gate and prior gate documents unchanged.
- Every later advancement gate must report source hashes, exact row/domain counts, support attrition, executed code/cells, and Git-visible changes.

## Evidence Base

Primary local evidence includes:

- `documentation/final_fire_selection_evidence_gate.md`
- `documentation/silverado_vs_brattain_feasibility_gate.md`
- `documentation/silverado_vs_brattain_ecological_data_advantage_gate.md`
- `documentation/paper1_outcome_decision.md`
- `documentation/paper1_terrain_support_qc.md`
- `documentation/paper1_landfire_support_qc.md`
- `documentation/paper1_daymet_climate_predictor_qc.md`
- `documentation/paper1_predictor_integration_and_common_support_qc.md`
- `documentation/paper1_spatial_validation_geometry_specification.md`
- `data/processed/feasibility/silverado_vs_brattain/FEASIBILITY_NONCANONICAL_final_eag_support_audit.json`
- `data/processed/feasibility/silverado_vs_brattain/FEASIBILITY_NONCANONICAL_final_landfire_support_audit.json`
- `data/processed/feasibility/silverado_vs_brattain/FEASIBILITY_NONCANONICAL_prefire_mtbs_disturbance_audit.json`
- `data/processed/feasibility/silverado_vs_brattain/FEASIBILITY_NONCANONICAL_nested_buffer_geometry.csv`

The older zero-buffer spatial specification and reduced Random Forest specification remain evidence of prior decisions, not current authorization. Where they conflict with this blueprint, this blueprint governs future Paper 1 work.
