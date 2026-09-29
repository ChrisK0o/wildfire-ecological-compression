# Paper 1 Exact Pre-Fit Model Formulation

## Decision

**Gate status: `REQUIRES_CORRECTION`. Model fitting remains unauthorized.**

The statistical architecture is fully prespecified without fitting a model or inspecting B2, B3, or B4 predictive performance. The blocking issue is upstream and bounded: the required `ACTIVE_FRONT_ONLY_5KM`, `PERIMETER_ONLY_2KM`, and `PERIMETER_ONLY_5KM` risk-set variants have response/count specifications, but no predictor-complete PR23 aggregation, PR24 paired support universe, or PR31 labeled table. They must be constructed and pass the same leakage checks before any model is fit.

## Scientific question and claim boundary

Among still-unburned landscape locations plausibly exposed to the active Brattain fire at each observed progression interval, does ecologically explicit pre-fire information add predictive information about where the fire spreads next beyond conventional fire-state, fuel, canopy, terrain, and meteorological information?

This is a paired incremental-predictive-information study. It supports only within-Brattain, later-interval, retrospective forecast-like claims. It does not support causal, operational, unseen-fire, regional-risk, ignition, exact-front-timing, exact-spotting, or 30 m propagation claims.

## Target and data identity

- Binary target: `y`, unchanged from PR31.
- `1`: an eligible cell is newly incorporated into the next completed FEDS state.
- `0`: an eligible cell remains unincorporated.
- Primary support: 1 km EPSG:9311, 3,317 rows, 200 positives, 3,117 negatives.
- Required resolution sensitivity: 2 km EPSG:9311, 836 rows, 49 positives, 787 negatives.
- Rows are forecast occasions; repeated cells are retained.
- No label smoothing, resampling, or threshold redefinition is allowed.

## Forward-chain validation

The fixed blocks are B1 = intervals 1, 3, 4, 5; B2 = 6, 8, 9, 10; B3 = 11, 12, 14, 15; B4 = 16, 18, 21, 22.

1. Train B1, test B2.
2. Train B1+B2, test B3.
3. Train B1+B2+B3, test B4.

B2, B3, and B4 never influence predictor definitions, preprocessing parameters, tuning, weighting, calibration, or thresholds for the evaluation in which they are held out. Random row splits and interval mixing are prohibited.

## Primary hypothesis

Adding the locked LF2016 EVT composition block to the locked conventional baseline is expected to improve out-of-sample probability prediction across the three later-Brattain forward-chain evaluations. Primary evidence is positive paired improvement in interval-level log loss, guarded by paired Brier-score behavior, on identical rows.

## Exact models

### Mandatory benchmarks

The prevalence benchmark predicts the Jeffreys-smoothed training-history event rate `(positives + 0.5) / (rows + 1)` for every held-out row. The geometry benchmark is the primary regularized logistic model restricted to the four completed-t0 FEDS state variables.

### Primary confirmatory learner

Use `sklearn.linear_model.LogisticRegression` with Bernoulli logit probabilities, L2 penalty, `solver='lbfgs'`, `fit_intercept=True`, `class_weight=None`, `max_iter=5000`, and `tol=1e-8`. Only `C` is tuned at 1 km. This resolves the blueprint's closely related logistic/GAM choice in favor of the lower-complexity model supported by the early event count.

### Secondary nonlinear robustness learner

Use `sklearn.ensemble.RandomForestClassifier` with `n_estimators=1000`, `criterion='log_loss'`, `max_depth=6`, `max_features='sqrt'`, `bootstrap=True`, `class_weight=None`, and `min_samples_split=2`. Only `min_samples_leaf` is tuned at 1 km. The forest is a nonlinear robustness check, not an interpretability engine or a competing primary hypothesis.

The locked execution environment is CPython 3.12.13 with scikit-learn 1.9.0, NumPy 2.5.1, SciPy 1.18.0, and pandas 3.0.3. A mismatch halts fitting until the environment is reconciled and recorded; no silent package substitution is allowed.

Gradient boosting, ExtraTrees, GAM/spline expansion, unregularized logistic regression, and neural networks are excluded for the reasons recorded in `PAPER1_MODEL_FAMILY_DECISION.csv`. There is no algorithm leaderboard.

## Exact predictor architecture

The baseline has 24 raw fields: four completed-t0 FEDS state, five terrain, five FBFM40, five canopy, and five HRRR fields. Core ecology has exactly five LF2016 EVT fractions. Exact names and model-specific representations are in `PAPER1_MODEL_PREDICTOR_WHITELIST.csv`.

Baseline and baseline+EVT use identical rows and procedures. Only the EVT construct differs. The baseline is not allowed to inherit any ecology sensitivity field.

## Composition and categorical handling

For logistic models, omit `fbfm_nonburnable_fraction` and `evt_other_fraction` as fixed reference parts. The remaining four fractions represent each full composition through contrasts against that fixed reference. No pseudocount or log-ratio is used because zeros are valid and an arbitrary zero replacement is not justified. Tree models receive all five raw fractions.

`hybrid_membership` has four fixed global levels in this order: `BOTH`, `ACTIVE_ONLY`, `PERIMETER_BACKSTOP_ONLY`, and `NEITHER_PRIMARY_COMPONENT`. The fourth state means only that a cell belongs to neither component used to define the primary hybrid risk set; it may still be eligible under a broader locked sensitivity risk set. Logistic models use `BOTH` as the reference with indicators `hybrid_ACTIVE_ONLY`, `hybrid_PERIMETER_BACKSTOP_ONLY`, and `hybrid_NEITHER_PRIMARY_COMPONENT`. The forest uses four fixed one-hot indicators with no dropped level. No ordinal coding is allowed. Missing component geometry, a missing category, or a category outside these four values halts execution; unknown-category ignoring is prohibited.

The primary hybrid universe contains no `NEITHER_PRIMARY_COMPONENT` rows, so its logistic indicator and forest indicator for that state are identically zero. Retain the fixed schema when the estimator safely accepts the all-zero feature. If an implementation library requires removing a zero-variance column, removal must be deterministic, training-performance-independent, and recorded without changing the scientific category definition or any primary artifact.

## Nonlinearity and interactions

The confirmatory model adds no splines, polynomials, or brute-force interactions. `uphill_alignment` and `wind_slope_alignment` are the only mechanistically prespecified interaction-like constructs. The Random Forest provides the bounded nonlinear robustness analysis.

## Scaling, missingness, and imbalance

Every numeric coordinate entering logistic regression is processed from the current training history only, including fractions and bounded alignments. A coordinate with positive finite population SD uses `z = (x - training_mean) / training_population_sd` with `ddof=0`. A finite coordinate with population SD exactly zero remains in its fixed feature position but is mapped to exactly `0.0` for every training, tuning-validation, and held-out row of that fit under `TRAINING_CONSTANT_FIXED_ZERO_COORDINATE`. Held-out variation cannot activate or scale it. Tiny positive SD still uses ordinary scaling; no epsilon, global, or held-out divisor is allowed. One-hot indicators are not scaled. The forest is not scaled and retains finite constant raw predictors normally. Missing/nonfinite input or nonfinite SD still halts execution.

This branch does not remove a scientific predictor, change the FBFM40 or EVT reference, impute data, or declare general irrelevance. It records that the current logistic training history contains no variation from which to estimate that slope. A later training history with positive SD uses ordinary scaling. Baseline and augmented models on identical paired rows must assign identical status to every shared coordinate.

There is no imputation in the primary comparison. Family sensitivities use their exact PR24 paired support universes; NoData, outside-domain, unknown, and unobserved states are never converted to zero.

For the four conditional canopy structural fields only, source-table `NaN` is an intentional nonapplicability state when and only when `canopy_applicable_fraction == 0`. At model-matrix construction, map those four fields to numeric `0.0` on exactly those rows while retaining `canopy_applicable_fraction` as the governing applicability coordinate. This is `STRUCTURAL_ZERO_FOR_NONAPPLICABLE_CANOPY` semantic coding, not statistical imputation, and it does not alter any frozen source table or support mask. When `canopy_applicable_fraction > 0`, all four conditional fields must remain finite and unchanged; any missing or nonfinite value halts execution. A finite nonzero conditional value paired with zero applicability is contradictory and also halts execution.

For logistic regression, apply this mapping before training-history-only standardization. Estimate the arithmetic mean and population standard deviation (`ddof=0`) from all mapped rows in the current training history, including structurally zero-coded rows, and apply those parameters to training, validation, and held-out rows. Do not estimate scaling only from canopy-applicable rows and do not zero-code after scaling. Random Forest receives the same mapped values without scaling.

All learners use unweighted probabilistic loss. Class weighting, SMOTE, over/undersampling, and synthetic observations are prohibited because they would alter the target probability without an independently supportable correction.

## Nested temporal tuning

At 1 km, logistic `C` is restricted to `{0.1, 1.0}`. Random Forest `min_samples_leaf` is restricted to `{0.02, 0.05}` with all other settings fixed.

For evaluation 1, use only B1: train intervals 1+3 and validate 4; then train 1+3+4 and validate 5. The 1-to-3 split is omitted because interval 1 contains too few positive outcomes for stable tuning. For evaluation 2, train B1 and validate B2. For evaluation 3, train B1 and validate B2, then train B1+B2 and validate B3. Preprocessing is refit inside every inner training history.

The tuning objective is the equal-weight mean of interval-level log loss. Ties within `1e-12` choose stronger regularization: `C=0.1` or `min_samples_leaf=0.05`. Two-kilometer and no-early analyses use those conservative fixed settings because their B1 histories are too sparse for credible tuning. Full details are in `PAPER1_MODEL_TUNING_SPEC.csv`.

## Randomness

Logistic regression is treated as deterministic. Forest tuning uses seed `20200908`. After the setting is selected entirely within training history, refit seeds `20200908` through `20200912` and average their probabilities. Per-seed metric range and SD are algorithmic diagnostics, not independent scientific replication.

## Metrics and calibration

Interval-level log loss is the primary decision metric. Interval-level Brier score is the co-primary probability-quality safeguard. Average precision and ROC-AUC are secondary and only computed for intervals containing both classes. Average precision is prevalence-dependent; values from different support universes are not directly compared.

Calibration-in-the-large is the intercept from unpenalized logistic recalibration with `logit(p)` as an offset. Calibration slope and intercept come from unpenalized logistic recalibration of `y` on `logit(p)`. Both use SciPy BFGS with the starts, tolerance, and iteration limit in the metric specification; nonconvergence is reported. A deterministic five-bin pooled reliability table is descriptive. No active calibration is fitted because the chronology offers too little independent calibration history. No held-out outcome may recalibrate predictions.

Paper 1 is probabilistic. No threshold is optimized. Accuracy and F1 are not central metrics; if a hard classification is required for a descriptive appendix, use 0.5 and label it secondary.

## Paired comparison and decision rule

For loss metrics, define positive ecology benefit as `baseline loss - baseline+EVT loss`. For AP and ROC-AUC, define it as `baseline+EVT - baseline`. Compute every metric on identical paired rows.

Report every interval first, then the equal-weight mean across the four intervals in each held-out block, then the equal-weight mean of B2, B3, and B4. Pooled-row metrics are descriptive only.

Classify the confirmatory EVT result as:

- `SUPPORTED`: mean paired log-loss benefit is positive, at least two of three block log-loss benefits are positive, and mean paired Brier benefit is nonnegative.
- `MIXED`: the log-loss conditions are met but Brier is negative, or required resolution/no-early/algorithmic robustness materially reverses the interpretation.
- `NOT_SUPPORTED`: mean log-loss benefit is nonpositive or fewer than two block log-loss benefits are positive.
- `INVALID`: any critical failure condition occurs.

The bootstrap interval describes uncertainty and strength; it is not converted into an iid hypothesis-test threshold. Magnitudes, block heterogeneity, calibration, and robustness are reported even when the categorical rule is met.

## Dependence-aware uncertainty

Use the twelve ordered held-out interval-level paired deltas. The primary moving-block bootstrap samples overlapping contiguous blocks of length 2 with replacement, concatenates to twelve intervals, truncates excess positions, and recomputes the equal-block aggregate. Use 10,000 replicates and seed `20200908`; repeat with block length 3.

Cells and rows are never bootstrapped independently. All repeated-cell rows remain within the interval metric that moves as a unit. The 2 km analysis is the required spatial-scale sensitivity. Residual within-interval spatial dependence is an explicit limitation; one fire and three later blocks do not justify an elaborate second-stage spatial bootstrap or classical iid p-values.

## Sensitivity hierarchy

The order is primary 1 km EVT, 2 km EVT, no-early EVT, required alternate risk sets, then one-family-at-a-time ecology sensitivities. EVC, EVH, legacy EAG, V5 EAG, V5 cheatgrass, prior MTBS, forest health, FACTS, and RAP remain paired family sensitivities. Confidence layers never enter a model: on each confidence-support universe, report the abundance-model paired deltas separately below and above the training-history median numeric confidence, labeling the strata only as lower and higher numeric values. V5 products are retrospective sensitivities and cannot support strict t0-operational language. FDist is exploratory. No all-ecology omnibus model is authorized.

The dominant-FBFM aggregation sensitivity is derived from the five stored fractions. An exact tie is encoded as its own `TIE` category; no fuel family wins an arbitrary tie. Symmetric blocked temporal CV and leave-one-interval-out analyses remain optional diagnostics and cannot replace or revise the forward-chain primary analysis.

Medusahead and field brome remain unavailable, Poa secunda remains out of scope, and RCMAP remains closed/deferred. Detailed ordering and caveats are in `PAPER1_MODEL_SENSITIVITY_HIERARCHY.csv`.

## Explainability and multiplicity

Predictor architecture cannot be changed using coefficients, impurity importance, permutation importance, SHAP, or held-out performance. Logistic coefficients may later be reported as regularized associations on the encoded scale. Forest permutation or SHAP summaries may be post hoc and secondary only.

There is one primary confirmatory EVT comparison. Other confirmatory sensitivities are secondary and interpreted hierarchically with effect estimates and uncertainty; they are not promoted to co-primary hypotheses. No multiplicity-adjusted p-value family is created because formal null-hypothesis testing is not authorized. Exploratory FDist is labeled separately.

## Failure conditions

Halt on any forbidden or unexpected design column; row/support/hash mismatch; training/test overlap; future-block preprocessing; missing or nonbinary outcome; single-class training history; tuning leakage; unknown category; missing/nonfinite input after the locked canopy structural-zero mapping; nonfinite scaling SD; a violation of the exact-zero-SD F24 branch; model nonconvergence; package-version mismatch; probability outside `[0,1]`; nonfinite prediction; paired-row mismatch; missing required interval; or exact 0/1 probability collapse caused by a numerical path. Calibration-diagnostic nonconvergence or nearly constant valid probabilities trigger an explicit limitation and correction review but do not erase otherwise valid proper-score results. Do not silently drop rows, switch solvers, widen grids, or substitute a risk set.

## Required later artifacts and manifest

Every held-out row must retain its identifiers, observed `y`, raw predicted probability for `y=1`, model family, baseline/ecology role, resolution, sensitivity universe, outer evaluation, training blocks, test block, hyperparameters, and seed. Hard classifications alone are insufficient.

The modeling manifest must record Git HEAD; input table and support-mask hashes; predictor-whitelist and formulation-spec hashes; package versions; all seeds; tuning grids and inner splits; training/test blocks; selected parameters; convergence and schema checks; and hashes for model, prediction, metric, uncertainty, and manifest artifacts.

## Bounded correction before fitting

Construct only the three already authorized alternate risk sets at 1 km and 2 km. Reuse the committed risk-set definitions; aggregate the exact PR23 baseline and EVT predictors without future information; build PR24-equivalent paired support universes; join the unchanged PR31 response rule; rerun leakage and row-identity assertions; and register hashes. Do not reopen variable discovery, outcomes, risk-set definitions, model architecture, or tuning grids.

After those artifacts pass, rerun the formulation validator. Until then, **model fitting may not begin**.
