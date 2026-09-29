# Discrepancies and Manuscript Risks

1. **Estimand terminology:** Describe conditional next-interval propagation among completed-t0 eligible/exposed cell centers. Do not call the outcome severity, ignition, eventual burned area, or generic fire occurrence.
2. **Unit of analysis:** The 3317 primary rows are interval-cell occasions, with 642 unique cells. Do not describe them as independent fires or independent locations.
3. **Single-fire scope:** This is one 2020 Brattain case study. Regional, unseen-fire, or out-of-fire generalization is unsupported.
4. **Event provenance:** FEDS event 65371 is a high-confidence inferred Brattain match, not an archive-named crosswalk. Retain that qualification.
5. **Temporal framing:** Forward chronological validation is retrospective pseudo-prospective evaluation. It is not a prospective trial or operational deployment.
6. **Information timing:** HRRR variables are archived forecasts valid at t0, not realized future weather. The FEDS completed-state archive and its information-time limitations must be disclosed.
7. **Causality:** Predictor contributions are predictive associations. Avoid caused, protected, drove, mediated, or treatment-effect wording.
8. **Statistical language:** Moving-block percentile intervals are descriptive. Do not say statistically significant, p-value, hypothesis test, or confidence level beyond the exact governed percentile construction.
9. **Metric selectivity:** Primary log loss and Brier improved, while AP and ROC-AUC were slightly lower. RF Brier was slightly negative. Do not claim all metrics improved.
10. **Temporal heterogeneity:** Primary B2 benefits were negative, B3 benefits were largest, and B4 benefits were small positive. Do not imply constant effects through time.
11. **Risk-set heterogeneity:** Perimeter-only 2 km favored baseline, unlike active-front-only and perimeter-only 5 km point estimates. Avoid risk-set invariance claims.
12. **Resolution:** The 2 km point benefits were near zero and intervals crossed zero. Do not claim scale invariance.
13. **Boundary filters:** Boundary 500/1000 are response-QC exclusions, not predictors or alternative exposure definitions.
14. **Boundary 1000 estimability:** Only B3/B4 comparisons are available. The full three-block aggregate and full bootstrap are NOT_ESTIMABLE; no two-block substitute is authorized.
15. **Suppression:** No accepted temporally valid t0 suppression predictor exists. Eventual suppression geometry must not be used. Suppression remains a major limitation.
16. **Grid shorthand:** Primary response resolution is 1 km with a 2 km sensitivity. A 30 m response claim is false; finer source rasters do not change response-grid resolution.
17. **Prediction origin:** Models condition on evolving completed-t0 fire state and do not predict from ignition.
18. **Variable interpretation:** No governed causal coefficient, variable importance, or variable-level effect-size claim is produced by this audit.
19. **Scope discipline:** The primary comparison is baseline versus baseline+EVT, not an all-ecology omnibus model. Other ecology families are secondary/retrospective/exploratory according to their frozen hierarchy.
20. **Horizon:** Interval horizons varied (about 9.7-14.0 hours; median 12.3). Avoid presenting a single exact forecast horizon without qualification.
