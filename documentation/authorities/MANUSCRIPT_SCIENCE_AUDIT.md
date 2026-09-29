# Paper 1 Manuscript Science Verification Audit

## Audit status

**PASS WITH QUALIFICATIONS.** This report is a read-only fact check of the completed governed Paper 1 evidence. It did not dispatch a scientific handler, fit a model, generate a prediction, or alter the production namespace.

- Live repository: `C:\Projects\Wildfire_Research_Project`
- Branch / HEAD: `main` / `ba565d6cae23d39f28ba5fd148d380c1ed24e343`
- Final authority SHA-256: `3e6ccf05a1dcb9b94ec63463a07a91d825a60d1cd18631d8e18973db33d6e1de`
- Final descriptor SHA-256: `6131c5c1b06ae3e5a3946fa1d1fe5ecf5659ad52af772c6754c6dd11c70cd4a4`
- Final closure package SHA-256: `59a42873dac1f761fe3c9b10108ab64dccc4e861c8bf0c2c100ff2b8f48e1504`
- Production identity: 1729 files, 18139483 bytes, `620459e30b633b7b5e8f5435ff63fb22d162860cba8a0796bf4d6e0755725d58`
- Audit generated: 2026-09-26T22:11:09.188126+00:00

## Authoritative study statement

Paper 1 is a retrospective, single-fire case study of the 2020 Brattain Fire. It asks whether a locked 24-field conventional representation of completed-t0 fire state, t0-valid forecast weather, terrain, fuel, and canopy is predictively sufficient for conditional next-interval propagation among t0-eligible/exposed locations, or whether five explicit pre-fire LF2016 EVT composition fractions retain incremental predictive information. L2 logistic regression is primary; Random Forest is nonlinear robustness. The primary grid is 1 km and 2 km is a required sensitivity.

The response is not ignition, severity, eventual burned area, or 30 m propagation. For a fixed eligible cell center, `y=1` exactly when the next completed FEDS cumulative hull covers that center. Eligibility is frozen before t1 and requires that the center is outside the completed-t0 hull and is within 5 km of the completed-t0 active front or within 2 km of the completed-t0 hull boundary.

## Event and support

- FEDS source: Western US Archive v1.2.1, DOI `10.5281/zenodo.15261836`; event `fireID/fid=65371`.
- Association status: `HIGH_CONFIDENCE_INFERRED`, supported by location, September 8 timing, trajectory, final area, and EDW/MTBS/WFDSS perimeter overlap. It is not an explicit FEDS name crosswalk.
- CRS: EPSG:9311. Primary fixed lattice: 1000 m. Required sensitivity lattice: 2000 m.
- Retained intervals: 1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22.
- Blocks: B1=(1, 3, 4, 5); B2=(6, 8, 9, 10); B3=(11, 12, 14, 15); B4=(16, 18, 21, 22).
- Full labeled support: 1 km = 3317 rows, 642 unique cells, 200 positives; 2 km = 836 rows, 161 unique cells, 49 positives.
- Primary held-out B2-B4 evaluation: 2754 row occasions and 172 positives.
- Observed interval horizon: approximately 9.7-14.0 hours (median 12.3 hours); this is not an operational service-level promise.

## Predictors and model implementation

`METHODS_AUTHORITY.csv` gives the exact 24 baseline fields and five EVT fields, including units, products, and transformations. The raw-field counts are exactly 24 and 29. For logistic regression, `fbfm_nonburnable_fraction` and `evt_other_fraction` are fixed composition references, so encoded-coordinate counts should not be confused with raw-field counts.

Primary logistic regression uses scikit-learn 1.9.0 `LogisticRegression` with L2 penalty, `lbfgs`, intercept, no class weighting, `max_iter=5000`, and `tol=1e-8`. Numeric preprocessing is fit only on the exact current training history, including each inner fold, using population SD; one-hot coordinates are unscaled. There is no general imputation. The solver is deterministic, so a logistic random seed is not applicable. Candidate `C` values are 0.1 and 1.0.

Random Forest uses 1000 trees, `criterion=log_loss`, maximum depth 6, `max_features=sqrt`, bootstrap sampling, no class weighting, and candidate minimum leaf fractions 0.02 and 0.05. Tuning uses seed 20200908; final predictions average five seeds 20200908-20200912. The governed runtime used one job.

## Evaluation and uncertainty

The outer folds are B1->B2, B1+B2->B3, and B1+B2+B3->B4. Baseline and augmented models use exact paired keys and identical procedures. Metrics are computed by held-out interval. Block summaries weight their four intervals equally, and the final summary weights B2, B3, and B4 equally; row weighting is prohibited.

For loss metrics, paired benefit is baseline minus augmented, so positive values favor EVT. Uncertainty uses the ordered 12-interval paired-delta sequence and a moving-block bootstrap with lengths 2 and 3, 10000 replicates, seed 20200908, and 2.5th/97.5th percentiles. These intervals are descriptive and do not authorize significance language.

## Primary findings

The primary 1 km L2 analysis had baseline versus augmented equal-interval log loss 0.417065804414145 versus 0.401116121341003, and Brier score 0.113744697065558 versus 0.108606823480694. Paired benefits were 0.0159496830731413 for log loss and 0.00513787358486433 for Brier, equivalent to 3.824261% and 4.517023% reductions.

The temporal pattern was heterogeneous. Log-loss benefit was -0.007787 in B2, 0.052721 in B3, and 0.002915 in B4. Brier benefit was -0.000603, 0.014992, and 0.001024, respectively. AP was 0.390504511153153 baseline versus 0.373039534009025 augmented; ROC-AUC was 0.889787082524645 versus 0.886951043514291. Thus the supported conclusion concerns proper scoring rules, not universal improvement across every metric.

The exact primary and sensitivity estimates and both moving-block intervals are in `RESULTS_AUTHORITY.csv`. Random Forest was mixed (positive log-loss point benefit, slightly negative Brier point benefit); 2 km was near zero with intervals crossing zero; no-early and boundary-500 retained positive point benefits; alternate risk-set results were heterogeneous, including reversal under perimeter-only 2 km.

At the 1000 m response-boundary exclusion, B1 contained 452 rows and zero positives, so both B1->B2 model roles were governed nonestimable. B3 and B4 interval/block comparisons exist, but the originally defined equal B2-B3-B4 aggregate and full bootstrap interval do not. A two-block substitute must not be presented as the frozen estimand.

LOIO did not refit models. Every omitted-interval proper-score estimate remained positive. Interval 15 caused the largest absolute change; exact ranges are recorded in `RESULTS_AUTHORITY.csv`.

## Safe interpretation

The evidence supports a focused predictive statement: in this Brattain case study, the five EVT composition fractions retained incremental predictive information beyond the locked conventional representation under the primary proper scores. It does not establish causal ecological effects, transfer to unseen fires, operational readiness, ignition prediction, or suppression effectiveness. Suppression remains a major unmeasured limitation.

See `CLAIM_CHECKLIST.csv` for 15 verified claims, 6 claims requiring qualification, and 8 unsupported formulations. See `DISCREPANCIES_AND_RISKS.md` for drafting hazards.
